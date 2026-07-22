use std::mem::size_of;
use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::{
    CompactTopKOutput, DispatchBackend, DispatchPolicy, QuantizedRows, RawVectorInput, TopKRecord,
    ValidatedCorpus, ValidatedPreprocess, ValidatedRerankBatch, VectorCorpusInput, VectorError,
    VectorRerankBatch,
};

const GPU_WAIT: Duration = Duration::from_secs(60);
const SHADER: &str = include_str!("bounded_rerank.wgsl");
const PREPROCESS_SHADER: &str = include_str!("normalize_quantize.wgsl");

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdapterReceipt {
    pub name: String,
    pub backend: String,
    pub device_type: String,
    pub driver: String,
    pub driver_info: String,
    pub vendor: u32,
    pub device: u32,
    pub max_buffer_bytes: u64,
    pub max_storage_binding_bytes: u64,
    pub max_workgroups_per_dimension: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResidencyReceipt {
    pub corpus: ValidatedCorpus,
    pub upload_micros: u64,
    pub resident_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchReceipt {
    pub batch: ValidatedRerankBatch,
    pub batch_upload_micros: u64,
    pub dispatch_micros: u64,
    pub readback_micros: u64,
    pub returned_records: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GpuTopKOutput {
    pub top_k: CompactTopKOutput,
    pub receipt: DispatchReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreprocessReceipt {
    pub shape: ValidatedPreprocess,
    pub upload_micros: u64,
    pub dispatch_micros: u64,
    pub readback_micros: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GpuPreprocessOutput {
    pub normalized: Vec<f32>,
    pub quantized: QuantizedRows,
    pub receipt: PreprocessReceipt,
}

#[derive(Clone)]
pub struct GpuVectorRuntime {
    core: Arc<GpuVectorCore>,
}

struct GpuVectorCore {
    device: Arc<wgpu::Device>,
    queue: Arc<wgpu::Queue>,
    pipeline: wgpu::ComputePipeline,
    preprocess_pipeline: wgpu::ComputePipeline,
    limits: wgpu::Limits,
    policy: DispatchPolicy,
    receipt: AdapterReceipt,
}

pub struct ResidentVectorCorpus {
    runtime: Arc<GpuVectorCore>,
    vectors: wgpu::Buffer,
    lexical_ranks: wgpu::Buffer,
    shape: ValidatedCorpus,
    receipt: ResidencyReceipt,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct GpuParams {
    corpus_rows: u32,
    dimensions: u32,
    queries: u32,
    top_k: u32,
    dispatch_width: u32,
    minimum_similarity: f32,
    pad: [u32; 2],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct PreprocessParams {
    rows: u32,
    dimensions: u32,
    packed_words_per_row: u32,
    dispatch_width: u32,
}

impl GpuVectorRuntime {
    pub fn request(policy: DispatchPolicy) -> Result<Self, VectorError> {
        if policy.maximum_resident_bytes == 0 {
            return Err(VectorError::Residency(
                "vector GPU byte budget must be nonzero".to_owned(),
            ));
        }
        pollster::block_on(Self::request_async(policy))
    }

    async fn request_async(policy: DispatchPolicy) -> Result<Self, VectorError> {
        let instance =
            wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle_from_env());
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                force_fallback_adapter: false,
                compatible_surface: None,
                ..Default::default()
            })
            .await
            .map_err(|error| VectorError::Adapter(error.to_string()))?;
        let info = adapter.get_info();
        let limits = adapter.limits();
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("phoenix-vector-rerank"),
                required_limits: limits.clone(),
                memory_hints: wgpu::MemoryHints::Performance,
                ..Default::default()
            })
            .await
            .map_err(|error| VectorError::Device(error.to_string()))?;
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("phoenix-bounded-vector-rerank"),
            source: wgpu::ShaderSource::Wgsl(SHADER.into()),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("exact-cosine-top-k"),
            layout: None,
            module: &shader,
            entry_point: Some("exact_cosine_top_k"),
            compilation_options: Default::default(),
            cache: None,
        });
        let preprocess_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("phoenix-vector-normalize-quantize"),
            source: wgpu::ShaderSource::Wgsl(PREPROCESS_SHADER.into()),
        });
        let preprocess_pipeline =
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some("normalize-quantize"),
                layout: None,
                module: &preprocess_shader,
                entry_point: Some("normalize_quantize"),
                compilation_options: Default::default(),
                cache: None,
            });
        let receipt = AdapterReceipt {
            name: info.name,
            backend: format!("{:?}", info.backend),
            device_type: format!("{:?}", info.device_type),
            driver: info.driver,
            driver_info: info.driver_info,
            vendor: info.vendor,
            device: info.device,
            max_buffer_bytes: limits.max_buffer_size,
            max_storage_binding_bytes: limits.max_storage_buffer_binding_size,
            max_workgroups_per_dimension: limits.max_compute_workgroups_per_dimension,
        };
        Ok(Self {
            core: Arc::new(GpuVectorCore {
                device: Arc::new(device),
                queue: Arc::new(queue),
                pipeline,
                preprocess_pipeline,
                limits,
                policy,
                receipt,
            }),
        })
    }

    pub fn adapter_receipt(&self) -> &AdapterReceipt {
        &self.core.receipt
    }

    pub fn upload(
        &self,
        corpus: VectorCorpusInput<'_>,
    ) -> Result<ResidentVectorCorpus, VectorError> {
        let started = Instant::now();
        let shape = corpus.validate()?;
        if shape.resident_bytes > self.core.policy.maximum_resident_bytes {
            return Err(VectorError::Residency(format!(
                "{} corpus bytes exceed the configured {} byte budget",
                shape.resident_bytes, self.core.policy.maximum_resident_bytes
            )));
        }
        self.core
            .validate_binding("corpus vectors", shape.vector_bytes)?;
        self.core
            .validate_binding("lexical ranks", shape.lexical_rank_bytes)?;
        let vectors = storage(&self.core.device, "vector-corpus", corpus.values, false);
        let lexical_ranks = storage(
            &self.core.device,
            "vector-lexical-ranks",
            corpus.lexical_ranks,
            false,
        );
        let receipt = ResidencyReceipt {
            corpus: shape,
            upload_micros: micros(started.elapsed()),
            resident_bytes: shape.resident_bytes,
        };
        Ok(ResidentVectorCorpus {
            runtime: Arc::clone(&self.core),
            vectors,
            lexical_ranks,
            shape,
            receipt,
        })
    }

    pub fn normalize_quantize(
        &self,
        input: RawVectorInput<'_>,
    ) -> Result<GpuPreprocessOutput, VectorError> {
        let upload_started = Instant::now();
        let shape = input.validate()?;
        let total_bytes = shape
            .resident_bytes
            .checked_add(
                shape
                    .normalized_bytes
                    .checked_add(shape.quantized_bytes)
                    .and_then(|value| value.checked_add(shape.scale_bytes))
                    .ok_or_else(|| {
                        VectorError::Residency("preprocess readback overflow".to_owned())
                    })?,
            )
            .ok_or_else(|| VectorError::Residency("preprocess byte overflow".to_owned()))?;
        if total_bytes > self.core.policy.maximum_resident_bytes {
            return Err(VectorError::Residency(format!(
                "{total_bytes} bytes exceed the configured {} byte vector budget",
                self.core.policy.maximum_resident_bytes
            )));
        }
        for (label, bytes) in [
            ("preprocess input", shape.input_bytes),
            ("normalized output", shape.normalized_bytes),
            ("quantized output", shape.quantized_bytes),
            ("quantization scales", shape.scale_bytes),
        ] {
            self.core.validate_binding(label, bytes)?;
        }
        let dispatch = dispatch_2d(
            shape.rows,
            self.core.limits.max_compute_workgroups_per_dimension,
        )?;
        let input_values = storage(
            &self.core.device,
            "vector-preprocess-input",
            input.values,
            false,
        );
        let normalized = empty_storage(
            &self.core.device,
            "vector-normalized-output",
            shape.normalized_bytes,
            true,
        );
        let quantized = empty_storage(
            &self.core.device,
            "vector-quantized-output",
            shape.quantized_bytes,
            true,
        );
        let scales = empty_storage(
            &self.core.device,
            "vector-quantization-scales",
            shape.scale_bytes,
            true,
        );
        let params = storage(
            &self.core.device,
            "vector-preprocess-params",
            &[PreprocessParams {
                rows: shape.rows,
                dimensions: shape.dimensions,
                packed_words_per_row: shape.packed_words_per_row,
                dispatch_width: dispatch[0],
            }],
            false,
        );
        let bind_group = bind_group(
            &self.core.device,
            &self.core.preprocess_pipeline,
            &[&input_values, &normalized, &quantized, &scales, &params],
        );
        let readback_bytes = shape
            .normalized_bytes
            .checked_add(shape.quantized_bytes)
            .and_then(|value| value.checked_add(shape.scale_bytes))
            .ok_or_else(|| VectorError::Residency("preprocess readback overflow".to_owned()))?;
        let mapped = readback(
            &self.core.device,
            "vector-preprocess-readback",
            readback_bytes,
        );
        let upload_micros = micros(upload_started.elapsed());
        let dispatch_started = Instant::now();
        let mut encoder =
            self.core
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("vector-preprocess-dispatch"),
                });
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("vector-preprocess-dispatch"),
                timestamp_writes: None,
            });
            pass.set_pipeline(&self.core.preprocess_pipeline);
            pass.set_bind_group(0, &bind_group, &[]);
            pass.dispatch_workgroups(dispatch[0], dispatch[1], 1);
        }
        let submission = self.core.queue.submit([encoder.finish()]);
        wait(&self.core.device, submission)?;
        let dispatch_micros = micros(dispatch_started.elapsed());
        let readback_started = Instant::now();
        let bytes = copy_sections_and_map(
            &self.core.device,
            &self.core.queue,
            &[
                (&normalized, shape.normalized_bytes),
                (&quantized, shape.quantized_bytes),
                (&scales, shape.scale_bytes),
            ],
            &mapped,
        )?;
        let normalized_end = shape.normalized_bytes as usize;
        let quantized_end = normalized_end + shape.quantized_bytes as usize;
        let normalized = read_pods::<f32>(&bytes[..normalized_end])?;
        let packed = read_pods::<u32>(&bytes[normalized_end..quantized_end])?;
        let scales = read_pods::<f32>(&bytes[quantized_end..])?;
        let mut values = Vec::with_capacity(shape.rows as usize * shape.dimensions as usize);
        for row in 0..shape.rows as usize {
            let packed_start = row * shape.packed_words_per_row as usize;
            let row_end = (row + 1) * shape.dimensions as usize;
            for word in &packed[packed_start..packed_start + shape.packed_words_per_row as usize] {
                for byte in word.to_le_bytes() {
                    if values.len() >= row_end {
                        break;
                    }
                    values.push(byte as i8);
                }
            }
        }
        values.truncate(shape.rows as usize * shape.dimensions as usize);
        Ok(GpuPreprocessOutput {
            normalized,
            quantized: QuantizedRows {
                values,
                scales,
                rows: shape.rows,
                dimensions: shape.dimensions,
            },
            receipt: PreprocessReceipt {
                shape,
                upload_micros,
                dispatch_micros,
                readback_micros: micros(readback_started.elapsed()),
            },
        })
    }
}

impl GpuVectorCore {
    fn validate_binding(&self, label: &str, bytes: u64) -> Result<(), VectorError> {
        let limit = self
            .limits
            .max_buffer_size
            .min(self.limits.max_storage_buffer_binding_size);
        if bytes > limit {
            return Err(VectorError::Residency(format!(
                "{label} requires {bytes} bytes but the adapter permits {limit}"
            )));
        }
        Ok(())
    }
}

impl ResidentVectorCorpus {
    pub fn receipt(&self) -> &ResidencyReceipt {
        &self.receipt
    }

    pub fn adapter_receipt(&self) -> &AdapterReceipt {
        &self.runtime.receipt
    }

    pub fn dispatch_backend(
        &self,
        batch: VectorRerankBatch<'_>,
        gpu_available: bool,
    ) -> Result<DispatchBackend, VectorError> {
        let shape = batch.validate(self.shape)?;
        let total = self.total_resident_bytes(shape)?;
        Ok(self.runtime.policy.select(shape, total, gpu_available))
    }

    pub fn rerank(&self, batch: VectorRerankBatch<'_>) -> Result<GpuTopKOutput, VectorError> {
        let upload_started = Instant::now();
        let shape = batch.validate(self.shape)?;
        self.validate_batch_residency(batch, shape)?;
        let dispatch = dispatch_2d(
            shape.queries,
            self.runtime.limits.max_compute_workgroups_per_dimension,
        )?;
        let queries = storage(
            &self.runtime.device,
            "vector-query-batch",
            batch.queries,
            false,
        );
        let offsets = storage(
            &self.runtime.device,
            "vector-candidate-offsets",
            batch.candidate_offsets,
            false,
        );
        let candidates = storage(
            &self.runtime.device,
            "vector-candidate-identities",
            batch.candidate_ids,
            false,
        );
        let record_bytes =
            u64::from(shape.queries) * u64::from(shape.top_k) * size_of::<TopKRecord>() as u64;
        let count_bytes = u64::from(shape.queries) * size_of::<u32>() as u64;
        let output_records = empty_storage(
            &self.runtime.device,
            "vector-top-k-records",
            record_bytes,
            true,
        );
        let output_counts = empty_storage(
            &self.runtime.device,
            "vector-top-k-counts",
            count_bytes,
            true,
        );
        let params = storage(
            &self.runtime.device,
            "vector-rerank-params",
            &[GpuParams {
                corpus_rows: self.shape.rows,
                dimensions: self.shape.dimensions,
                queries: shape.queries,
                top_k: shape.top_k,
                dispatch_width: dispatch[0],
                minimum_similarity: batch.minimum_similarity,
                pad: [0; 2],
            }],
            false,
        );
        let bind_group = bind_group(
            &self.runtime.device,
            &self.runtime.pipeline,
            &[
                &self.vectors,
                &self.lexical_ranks,
                &queries,
                &offsets,
                &candidates,
                &output_records,
                &output_counts,
                &params,
            ],
        );
        let readback = readback(
            &self.runtime.device,
            "vector-top-k-readback",
            shape.readback_bytes,
        );
        let batch_upload_micros = micros(upload_started.elapsed());
        let dispatch_started = Instant::now();
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("vector-rerank-dispatch"),
                });
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("vector-rerank-dispatch"),
                timestamp_writes: None,
            });
            pass.set_pipeline(&self.runtime.pipeline);
            pass.set_bind_group(0, &bind_group, &[]);
            pass.dispatch_workgroups(dispatch[0], dispatch[1], 1);
        }
        let submission = self.runtime.queue.submit([encoder.finish()]);
        wait(&self.runtime.device, submission)?;
        let dispatch_micros = micros(dispatch_started.elapsed());
        let readback_started = Instant::now();
        let bytes = copy_and_map(
            &self.runtime.device,
            &self.runtime.queue,
            &output_counts,
            &output_records,
            &readback,
            count_bytes,
            record_bytes,
        )?;
        let top_k = compact_output(&bytes, shape, count_bytes as usize)?;
        let readback_micros = micros(readback_started.elapsed());
        Ok(GpuTopKOutput {
            receipt: DispatchReceipt {
                batch: shape,
                batch_upload_micros,
                dispatch_micros,
                readback_micros,
                returned_records: top_k.records.len() as u64,
            },
            top_k,
        })
    }

    fn validate_batch_residency(
        &self,
        batch: VectorRerankBatch<'_>,
        shape: ValidatedRerankBatch,
    ) -> Result<(), VectorError> {
        let total = self.total_resident_bytes(shape)?;
        if total > self.runtime.policy.maximum_resident_bytes {
            return Err(VectorError::Residency(format!(
                "{total} bytes exceed the configured {} byte vector budget",
                self.runtime.policy.maximum_resident_bytes
            )));
        }
        let record_bytes =
            u64::from(shape.queries) * u64::from(shape.top_k) * size_of::<TopKRecord>() as u64;
        let sections = [
            ("query vectors", shape.query_bytes),
            (
                "candidate offsets",
                batch.candidate_offsets.len() as u64 * 4,
            ),
            ("candidate identities", batch.candidate_ids.len() as u64 * 4),
            ("top-k records", record_bytes),
            ("top-k counts", u64::from(shape.queries) * 4),
        ];
        for (label, bytes) in sections {
            self.runtime.validate_binding(label, bytes)?;
        }
        Ok(())
    }

    fn total_resident_bytes(&self, batch: ValidatedRerankBatch) -> Result<u64, VectorError> {
        let doubled_readback = batch
            .readback_bytes
            .checked_mul(2)
            .ok_or_else(|| VectorError::Residency("vector byte accounting overflow".to_owned()))?;
        self.shape
            .resident_bytes
            .checked_add(batch.query_bytes)
            .and_then(|bytes| bytes.checked_add(batch.candidate_bytes))
            .and_then(|bytes| bytes.checked_add(doubled_readback))
            .ok_or_else(|| VectorError::Residency("vector byte accounting overflow".to_owned()))
    }
}

fn compact_output(
    bytes: &[u8],
    shape: ValidatedRerankBatch,
    count_bytes: usize,
) -> Result<CompactTopKOutput, VectorError> {
    if bytes.len() != shape.readback_bytes as usize || count_bytes > bytes.len() {
        return Err(VectorError::Execution(
            "vector readback extent drift".to_owned(),
        ));
    }
    let counts = read_pods::<u32>(&bytes[..count_bytes])?;
    let fixed = read_pods::<TopKRecord>(&bytes[count_bytes..])?;
    let mut offsets = Vec::with_capacity(shape.queries as usize + 1);
    let mut records = Vec::with_capacity(fixed.len());
    offsets.push(0);
    for (query, count) in counts.into_iter().enumerate() {
        if count > shape.top_k {
            return Err(VectorError::Execution(
                "GPU top-k count exceeds the requested bound".to_owned(),
            ));
        }
        let start = query * shape.top_k as usize;
        let selected = &fixed[start..start + count as usize];
        if selected
            .iter()
            .any(|record| record.candidate_id == crate::INVALID_CANDIDATE)
        {
            return Err(VectorError::Execution(
                "GPU returned an invalid selected candidate identity".to_owned(),
            ));
        }
        records.extend_from_slice(selected);
        offsets.push(records.len() as u32);
    }
    Ok(CompactTopKOutput { offsets, records })
}

fn dispatch_2d(items: u32, limit: u32) -> Result<[u32; 2], VectorError> {
    let width = items.min(limit);
    let height = items.div_ceil(width);
    if height > limit {
        return Err(VectorError::Residency(format!(
            "{items} query rows exceed the adapter dispatch extent"
        )));
    }
    Ok([width, height])
}

fn bind_group(
    device: &wgpu::Device,
    pipeline: &wgpu::ComputePipeline,
    buffers: &[&wgpu::Buffer],
) -> wgpu::BindGroup {
    let layout = pipeline.get_bind_group_layout(0);
    let entries = buffers
        .iter()
        .enumerate()
        .map(|(binding, buffer)| wgpu::BindGroupEntry {
            binding: binding as u32,
            resource: buffer.as_entire_binding(),
        })
        .collect::<Vec<_>>();
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("vector-exact-rerank"),
        layout: &layout,
        entries: &entries,
    })
}

fn storage<T: Pod>(
    device: &wgpu::Device,
    label: &'static str,
    values: &[T],
    copy_source: bool,
) -> wgpu::Buffer {
    let zero = T::zeroed();
    let values = if values.is_empty() {
        std::slice::from_ref(&zero)
    } else {
        values
    };
    let mut usage = wgpu::BufferUsages::STORAGE;
    if copy_source {
        usage |= wgpu::BufferUsages::COPY_SRC;
    }
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(label),
        contents: bytemuck::cast_slice(values),
        usage,
    })
}

fn empty_storage(
    device: &wgpu::Device,
    label: &'static str,
    size: u64,
    copy_source: bool,
) -> wgpu::Buffer {
    let mut usage = wgpu::BufferUsages::STORAGE;
    if copy_source {
        usage |= wgpu::BufferUsages::COPY_SRC;
    }
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size: size.max(4),
        usage,
        mapped_at_creation: false,
    })
}

fn readback(device: &wgpu::Device, label: &'static str, size: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

fn copy_and_map(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    counts: &wgpu::Buffer,
    records: &wgpu::Buffer,
    target: &wgpu::Buffer,
    count_bytes: u64,
    record_bytes: u64,
) -> Result<Vec<u8>, VectorError> {
    copy_sections_and_map(
        device,
        queue,
        &[(counts, count_bytes), (records, record_bytes)],
        target,
    )
}

fn copy_sections_and_map(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    sections: &[(&wgpu::Buffer, u64)],
    target: &wgpu::Buffer,
) -> Result<Vec<u8>, VectorError> {
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("vector-top-k-readback"),
    });
    let mut target_offset = 0;
    for (source, bytes) in sections {
        encoder.copy_buffer_to_buffer(source, 0, target, target_offset, *bytes);
        target_offset += bytes;
    }
    let submission = queue.submit([encoder.finish()]);
    let slice = target.slice(..target_offset);
    let (sender, receiver) = mpsc::sync_channel(1);
    slice.map_async(wgpu::MapMode::Read, move |result| {
        let _ = sender.send(result);
    });
    wait(device, submission)?;
    receiver
        .recv_timeout(GPU_WAIT)
        .map_err(|error| VectorError::Execution(error.to_string()))?
        .map_err(|error| VectorError::Execution(error.to_string()))?;
    let mapped = slice
        .get_mapped_range()
        .map_err(|error| VectorError::Execution(error.to_string()))?;
    let bytes = mapped.to_vec();
    drop(mapped);
    target.unmap();
    Ok(bytes)
}

fn wait(device: &wgpu::Device, submission: wgpu::SubmissionIndex) -> Result<(), VectorError> {
    device
        .poll(wgpu::PollType::Wait {
            submission_index: Some(submission),
            timeout: Some(GPU_WAIT),
        })
        .map_err(|error| VectorError::Execution(error.to_string()))?;
    Ok(())
}

fn read_pods<T: Pod>(bytes: &[u8]) -> Result<Vec<T>, VectorError> {
    let width = size_of::<T>();
    if width == 0 || !bytes.len().is_multiple_of(width) {
        return Err(VectorError::Execution(
            "vector readback does not match record width".to_owned(),
        ));
    }
    Ok(bytes
        .chunks_exact(width)
        .map(bytemuck::pod_read_unaligned)
        .collect())
}

fn micros(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}
