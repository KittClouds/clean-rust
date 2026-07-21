use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use bytemuck::{Pod, Zeroable};
use thiserror::Error;
use wgpu::util::DeviceExt;

use crate::{DispatchPolicy, DistMultInput, ValidatedDistMult};

const GPU_WAIT: Duration = Duration::from_secs(60);
const SHADER: &str = include_str!("distmult_sum.wgsl");

#[derive(Debug, Error)]
pub enum GpuError {
    #[error("invalid DistMult input: {0}")]
    Shape(String),
    #[error("GPU adapter unavailable: {0}")]
    Adapter(String),
    #[error("GPU device unavailable: {0}")]
    Device(String),
    #[error("GPU residency rejected: {0}")]
    Residency(String),
    #[error("GPU execution failed: {0}")]
    Execution(String),
}

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
    pub shape: ValidatedDistMult,
    /// Host-side validation, buffer initialization, and pipeline preparation.
    /// The first dispatch receipt includes any deferred device upload.
    pub prepare_micros: u64,
    pub resident_bytes: u64,
    pub readback_bytes: u64,
    pub dispatch_x: u32,
    pub dispatch_y: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchReceipt {
    pub dispatch_micros: u64,
    pub readback_micros: u64,
    pub output_values: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DispatchOutput {
    pub values: Vec<f32>,
    pub receipt: DispatchReceipt,
}

pub struct GpuKernelRuntime {
    device: Arc<wgpu::Device>,
    queue: Arc<wgpu::Queue>,
    pipeline: wgpu::ComputePipeline,
    limits: wgpu::Limits,
    policy: DispatchPolicy,
    receipt: AdapterReceipt,
}

pub struct ResidentDistMult<'a> {
    runtime: &'a GpuKernelRuntime,
    bind_group: wgpu::BindGroup,
    output: wgpu::Buffer,
    readback: wgpu::Buffer,
    receipt: ResidencyReceipt,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct GpuParams {
    nodes: u32,
    edges: u32,
    relation_count: u32,
    dim: u32,
    dispatch_width: u32,
    pad: [u32; 3],
}

impl GpuKernelRuntime {
    pub fn request(policy: DispatchPolicy) -> Result<Self, GpuError> {
        pollster::block_on(Self::request_async(policy))
    }

    async fn request_async(policy: DispatchPolicy) -> Result<Self, GpuError> {
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
            .map_err(|error| GpuError::Adapter(error.to_string()))?;
        let info = adapter.get_info();
        let limits = adapter.limits();
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("phoenix-gfm-wgpu-kernel"),
                required_limits: limits.clone(),
                memory_hints: wgpu::MemoryHints::Performance,
                ..Default::default()
            })
            .await
            .map_err(|error| GpuError::Device(error.to_string()))?;
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("gfm-distmult-sum"),
            source: wgpu::ShaderSource::Wgsl(SHADER.into()),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("gfm-distmult-sum"),
            layout: None,
            module: &shader,
            entry_point: Some("distmult_sum"),
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
            device: Arc::new(device),
            queue: Arc::new(queue),
            pipeline,
            limits,
            policy,
            receipt,
        })
    }

    pub fn adapter_receipt(&self) -> &AdapterReceipt {
        &self.receipt
    }

    pub fn upload<'a>(
        &'a self,
        input: DistMultInput<'_>,
    ) -> Result<ResidentDistMult<'a>, GpuError> {
        let started = Instant::now();
        let shape = input.validate()?;
        self.validate_residency(shape, &input)?;
        let offsets = input
            .offsets
            .iter()
            .map(|&offset| offset as u32)
            .collect::<Vec<_>>();
        let max_dispatch = self.limits.max_compute_workgroups_per_dimension;
        let dispatch_x = shape.nodes.min(max_dispatch);
        let dispatch_y = shape.nodes.div_ceil(dispatch_x);
        if dispatch_y > max_dispatch {
            return Err(GpuError::Residency(format!(
                "{} nodes exceed the portable two-dimensional dispatch extent",
                shape.nodes
            )));
        }
        let params = GpuParams {
            nodes: shape.nodes,
            edges: shape.edges,
            relation_count: shape.relations,
            dim: shape.dim,
            dispatch_width: dispatch_x,
            pad: [0; 3],
        };
        let offsets = storage(&self.device, "gfm-offsets", &offsets, false);
        let sources = storage(&self.device, "gfm-sources", input.sources, false);
        let relation_ids = storage(
            &self.device,
            "gfm-relation-identities",
            input.relation_ids,
            false,
        );
        let input_state = storage(&self.device, "gfm-input", input.input, false);
        let relations = storage(&self.device, "gfm-relations", input.relations, false);
        let boundary = storage(&self.device, "gfm-boundary", input.boundary, false);
        let output = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("gfm-output"),
            size: shape.readback_bytes,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("gfm-readback"),
            size: shape.readback_bytes,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let params = storage(
            &self.device,
            "gfm-params",
            std::slice::from_ref(&params),
            false,
        );
        let layout = self.pipeline.get_bind_group_layout(0);
        let buffers = [
            &offsets,
            &sources,
            &relation_ids,
            &input_state,
            &relations,
            &boundary,
            &output,
            &params,
        ];
        let entries = buffers
            .iter()
            .enumerate()
            .map(|(binding, buffer)| wgpu::BindGroupEntry {
                binding: binding as u32,
                resource: buffer.as_entire_binding(),
            })
            .collect::<Vec<_>>();
        let bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("gfm-distmult-sum"),
            layout: &layout,
            entries: &entries,
        });
        let receipt = ResidencyReceipt {
            shape,
            prepare_micros: micros(started.elapsed()),
            resident_bytes: shape.resident_bytes,
            readback_bytes: shape.readback_bytes,
            dispatch_x,
            dispatch_y,
        };
        Ok(ResidentDistMult {
            runtime: self,
            bind_group,
            output,
            readback,
            receipt,
        })
    }

    fn validate_residency(
        &self,
        shape: ValidatedDistMult,
        input: &DistMultInput<'_>,
    ) -> Result<(), GpuError> {
        let total = shape
            .resident_bytes
            .checked_add(shape.readback_bytes)
            .ok_or_else(|| GpuError::Residency("GPU byte accounting overflow".to_owned()))?;
        if total > self.policy.maximum_resident_bytes {
            return Err(GpuError::Residency(format!(
                "{total} bytes exceed the configured {} byte budget",
                self.policy.maximum_resident_bytes
            )));
        }
        let binding_limit = self
            .limits
            .max_storage_buffer_binding_size
            .min(self.limits.max_buffer_size);
        let sections = [
            ("offsets", input.offsets.len() as u64 * 4),
            ("sources", input.sources.len() as u64 * 4),
            ("relation identities", input.relation_ids.len() as u64 * 4),
            ("input", input.input.len() as u64 * 4),
            ("relations", input.relations.len() as u64 * 4),
            ("boundary", input.boundary.len() as u64 * 4),
            ("output", shape.readback_bytes),
        ];
        if let Some((name, bytes)) = sections
            .into_iter()
            .find(|(_, bytes)| *bytes > binding_limit)
        {
            return Err(GpuError::Residency(format!(
                "{name} buffer requires {bytes} bytes but adapter permits {binding_limit}"
            )));
        }
        Ok(())
    }
}

impl ResidentDistMult<'_> {
    pub fn receipt(&self) -> &ResidencyReceipt {
        &self.receipt
    }

    pub fn execute(&self) -> Result<DispatchOutput, GpuError> {
        let dispatch_micros = micros(self.dispatch_and_wait()?);
        let (values, readback) = self.read_output()?;
        Ok(DispatchOutput {
            receipt: DispatchReceipt {
                dispatch_micros,
                readback_micros: micros(readback),
                output_values: values.len() as u64,
            },
            values,
        })
    }

    pub fn dispatch_and_wait(&self) -> Result<Duration, GpuError> {
        let started = Instant::now();
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("gfm-distmult-dispatch"),
                });
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("gfm-distmult-dispatch"),
                timestamp_writes: None,
            });
            pass.set_pipeline(&self.runtime.pipeline);
            pass.set_bind_group(0, &self.bind_group, &[]);
            pass.dispatch_workgroups(self.receipt.dispatch_x, self.receipt.dispatch_y, 1);
        }
        let submission = self.runtime.queue.submit([encoder.finish()]);
        self.runtime
            .device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(GPU_WAIT),
            })
            .map_err(|error| GpuError::Execution(error.to_string()))?;
        Ok(started.elapsed())
    }

    pub fn read_output(&self) -> Result<(Vec<f32>, Duration), GpuError> {
        let started = Instant::now();
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("gfm-distmult-readback"),
                });
        encoder.copy_buffer_to_buffer(
            &self.output,
            0,
            &self.readback,
            0,
            self.receipt.readback_bytes,
        );
        let submission = self.runtime.queue.submit([encoder.finish()]);
        let slice = self.readback.slice(..);
        let (sender, receiver) = mpsc::sync_channel(1);
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = sender.send(result);
        });
        self.runtime
            .device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(GPU_WAIT),
            })
            .map_err(|error| GpuError::Execution(error.to_string()))?;
        receiver
            .recv_timeout(GPU_WAIT)
            .map_err(|error| GpuError::Execution(error.to_string()))?
            .map_err(|error| GpuError::Execution(error.to_string()))?;
        let mapped = slice
            .get_mapped_range()
            .map_err(|error| GpuError::Execution(error.to_string()))?;
        let values = bytemuck::cast_slice::<u8, f32>(&mapped).to_vec();
        drop(mapped);
        self.readback.unmap();
        Ok((values, started.elapsed()))
    }
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

fn micros(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}
