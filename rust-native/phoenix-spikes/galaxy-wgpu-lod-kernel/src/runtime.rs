use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use bytemuck::{Pod, Zeroable};
use thiserror::Error;
use wgpu::util::DeviceExt;

use crate::cpu::{validate_edges, validate_order, validate_ranges, validate_tile_bits};
use crate::{
    BundleKeyOutput, EdgeInput, LodAggregate, LodOutput, LodRange, RawBundleKey, SpatialOutput,
    StageTiming,
};

const GPU_WAIT: Duration = Duration::from_secs(60);
const WORKGROUP_SIZE: u32 = 256;
const SHADER: &str = include_str!("galaxy_lod.wgsl");

#[derive(Debug, Error)]
pub enum GalaxyGpuError {
    #[error("invalid Galaxy GPU input: {0}")]
    Input(String),
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

pub struct GalaxyGpuRuntime {
    device: Arc<wgpu::Device>,
    queue: Arc<wgpu::Queue>,
    reset_pipeline: wgpu::ComputePipeline,
    bounds_pipeline: wgpu::ComputePipeline,
    morton_pipeline: wgpu::ComputePipeline,
    lod_pipeline: wgpu::ComputePipeline,
    edge_pipeline: wgpu::ComputePipeline,
    limits: wgpu::Limits,
    maximum_resident_bytes: u64,
    receipt: AdapterReceipt,
}

pub struct ResidentPositions<'a> {
    runtime: &'a GalaxyGpuRuntime,
    positions: wgpu::Buffer,
    bounds: wgpu::Buffer,
    morton_keys: wgpu::Buffer,
    node_tiles: wgpu::Buffer,
    readback: wgpu::Buffer,
    reset_bind_group: wgpu::BindGroup,
    bounds_bind_group: wgpu::BindGroup,
    morton_bind_group: wgpu::BindGroup,
    nodes: u32,
    dispatch: [u32; 2],
    prepare_micros: u64,
    gpu_bytes: u64,
}

pub struct ResidentLod<'a> {
    runtime: &'a GalaxyGpuRuntime,
    aggregate_bind_group: wgpu::BindGroup,
    node_to_lod: wgpu::Buffer,
    aggregates: wgpu::Buffer,
    readback: wgpu::Buffer,
    nodes: u32,
    ranges: u32,
    dispatch: [u32; 2],
    prepare_micros: u64,
    gpu_bytes: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct SpatialParams {
    nodes: u32,
    tile_bits: u32,
    dispatch_groups_x: u32,
    pad: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct LodParams {
    nodes: u32,
    ranges: u32,
    dispatch_groups_x: u32,
    pad: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct EdgeParams {
    edges: u32,
    nodes: u32,
    dispatch_groups_x: u32,
    pad: u32,
}

impl GalaxyGpuRuntime {
    pub fn request(maximum_resident_bytes: u64) -> Result<Self, GalaxyGpuError> {
        if maximum_resident_bytes == 0 {
            return Err(GalaxyGpuError::Residency(
                "configured byte budget must be nonzero".to_owned(),
            ));
        }
        pollster::block_on(Self::request_async(maximum_resident_bytes))
    }

    async fn request_async(maximum_resident_bytes: u64) -> Result<Self, GalaxyGpuError> {
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
            .map_err(|error| GalaxyGpuError::Adapter(error.to_string()))?;
        let info = adapter.get_info();
        let limits = adapter.limits();
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("phoenix-galaxy-wgpu-lod"),
                required_limits: limits.clone(),
                memory_hints: wgpu::MemoryHints::Performance,
                ..Default::default()
            })
            .await
            .map_err(|error| GalaxyGpuError::Device(error.to_string()))?;
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("phoenix-galaxy-lod"),
            source: wgpu::ShaderSource::Wgsl(SHADER.into()),
        });
        let pipeline = |entry: &'static str| {
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(entry),
                layout: None,
                module: &shader,
                entry_point: Some(entry),
                compilation_options: Default::default(),
                cache: None,
            })
        };
        let reset_pipeline = pipeline("reset_position_bounds");
        let bounds_pipeline = pipeline("accumulate_position_bounds");
        let morton_pipeline = pipeline("build_morton_keys");
        let lod_pipeline = pipeline("aggregate_lod");
        let edge_pipeline = pipeline("remap_edge_bundles");
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
            reset_pipeline,
            bounds_pipeline,
            morton_pipeline,
            lod_pipeline,
            edge_pipeline,
            limits,
            maximum_resident_bytes,
            receipt,
        })
    }

    pub fn adapter_receipt(&self) -> &AdapterReceipt {
        &self.receipt
    }

    pub fn upload_positions<'a>(
        &'a self,
        positions: &[[f32; 3]],
        tile_bits: u8,
    ) -> Result<ResidentPositions<'a>, GalaxyGpuError> {
        let started = Instant::now();
        validate_tile_bits(tile_bits)?;
        let nodes = u32::try_from(positions.len()).map_err(|_| {
            GalaxyGpuError::Input("position count exceeds u32 identity space".to_owned())
        })?;
        if nodes == 0 {
            return Err(GalaxyGpuError::Input(
                "at least one position is required".to_owned(),
            ));
        }
        let dispatch = self.invocation_dispatch(nodes)?;
        let position_bytes = bytes_for::<[f32; 3]>(nodes as usize)?;
        let bounds_bytes = 6 * 4;
        let key_bytes = bytes_for::<[u32; 2]>(nodes as usize)?;
        let readback_bytes = bounds_bytes + key_bytes * 2;
        let gpu_bytes = checked_sum(&[
            position_bytes,
            bounds_bytes,
            key_bytes,
            key_bytes,
            readback_bytes,
            16,
        ])?;
        self.validate_residency(gpu_bytes, &[position_bytes, bounds_bytes, key_bytes])?;
        let positions = storage(&self.device, "galaxy-positions", positions, false);
        let bounds = empty_storage(&self.device, "galaxy-bounds", bounds_bytes, true);
        let morton_keys = empty_storage(&self.device, "galaxy-morton-keys", key_bytes, true);
        let node_tiles = empty_storage(&self.device, "galaxy-node-tiles", key_bytes, true);
        let readback = readback(&self.device, "galaxy-spatial-readback", readback_bytes);
        let params = storage(
            &self.device,
            "galaxy-spatial-params",
            &[SpatialParams {
                nodes,
                tile_bits: u32::from(tile_bits),
                dispatch_groups_x: dispatch[0],
                pad: 0,
            }],
            false,
        );
        let reset_bind_group = bind_group(
            &self.device,
            &self.reset_pipeline,
            "galaxy-reset-bounds",
            &[&bounds],
        );
        let bounds_bind_group = bind_group(
            &self.device,
            &self.bounds_pipeline,
            "galaxy-accumulate-bounds",
            &[&positions, &bounds, &params],
        );
        let morton_bind_group = bind_group(
            &self.device,
            &self.morton_pipeline,
            "galaxy-build-morton",
            &[&positions, &bounds, &morton_keys, &node_tiles, &params],
        );
        Ok(ResidentPositions {
            runtime: self,
            positions,
            bounds,
            morton_keys,
            node_tiles,
            readback,
            reset_bind_group,
            bounds_bind_group,
            morton_bind_group,
            nodes,
            dispatch,
            prepare_micros: micros(started.elapsed()),
            gpu_bytes,
        })
    }

    fn invocation_dispatch(&self, invocations: u32) -> Result<[u32; 2], GalaxyGpuError> {
        self.workgroup_dispatch(invocations.div_ceil(WORKGROUP_SIZE))
    }

    fn workgroup_dispatch(&self, groups: u32) -> Result<[u32; 2], GalaxyGpuError> {
        let max = self.limits.max_compute_workgroups_per_dimension;
        let x = groups.min(max).max(1);
        let y = groups.div_ceil(x).max(1);
        if y > max {
            return Err(GalaxyGpuError::Residency(format!(
                "{groups} workgroups exceed the portable two-dimensional dispatch extent"
            )));
        }
        Ok([x, y])
    }

    fn validate_residency(
        &self,
        total_bytes: u64,
        binding_bytes: &[u64],
    ) -> Result<(), GalaxyGpuError> {
        if total_bytes > self.maximum_resident_bytes {
            return Err(GalaxyGpuError::Residency(format!(
                "{total_bytes} bytes exceed the configured {} byte budget",
                self.maximum_resident_bytes
            )));
        }
        let limit = self
            .limits
            .max_buffer_size
            .min(self.limits.max_storage_buffer_binding_size);
        if let Some(bytes) = binding_bytes.iter().find(|bytes| **bytes > limit) {
            return Err(GalaxyGpuError::Residency(format!(
                "{bytes} byte storage binding exceeds adapter limit {limit}"
            )));
        }
        Ok(())
    }

    fn submit(&self, encoder: wgpu::CommandEncoder) -> Result<Duration, GalaxyGpuError> {
        let started = Instant::now();
        let submission = self.queue.submit([encoder.finish()]);
        self.device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(GPU_WAIT),
            })
            .map_err(|error| GalaxyGpuError::Execution(error.to_string()))?;
        Ok(started.elapsed())
    }

    fn copy_and_map(
        &self,
        source_copies: &[(&wgpu::Buffer, u64, u64)],
        target: &wgpu::Buffer,
        target_bytes: u64,
    ) -> Result<(Vec<u8>, Duration), GalaxyGpuError> {
        let started = Instant::now();
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("galaxy-gpu-readback"),
            });
        let mut target_offset = 0;
        for (source, source_offset, bytes) in source_copies {
            encoder.copy_buffer_to_buffer(source, *source_offset, target, target_offset, *bytes);
            target_offset += bytes;
        }
        debug_assert_eq!(target_offset, target_bytes);
        let submission = self.queue.submit([encoder.finish()]);
        let slice = target.slice(..target_bytes);
        let (sender, receiver) = mpsc::sync_channel(1);
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = sender.send(result);
        });
        self.device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(GPU_WAIT),
            })
            .map_err(|error| GalaxyGpuError::Execution(error.to_string()))?;
        receiver
            .recv_timeout(GPU_WAIT)
            .map_err(|error| GalaxyGpuError::Execution(error.to_string()))?
            .map_err(|error| GalaxyGpuError::Execution(error.to_string()))?;
        let mapped = slice
            .get_mapped_range()
            .map_err(|error| GalaxyGpuError::Execution(error.to_string()))?;
        let bytes = mapped.to_vec();
        drop(mapped);
        target.unmap();
        Ok((bytes, started.elapsed()))
    }
}

impl ResidentPositions<'_> {
    pub fn execute_spatial(&self) -> Result<SpatialOutput, GalaxyGpuError> {
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("galaxy-spatial-dispatch"),
                });
        compute_pass(
            &mut encoder,
            &self.runtime.reset_pipeline,
            &self.reset_bind_group,
            [1, 1],
            "galaxy-reset-bounds",
        );
        compute_pass(
            &mut encoder,
            &self.runtime.bounds_pipeline,
            &self.bounds_bind_group,
            self.dispatch,
            "galaxy-accumulate-bounds",
        );
        compute_pass(
            &mut encoder,
            &self.runtime.morton_pipeline,
            &self.morton_bind_group,
            self.dispatch,
            "galaxy-build-morton",
        );
        let dispatch = self.runtime.submit(encoder)?;
        let bounds_bytes = 24;
        let key_bytes = u64::from(self.nodes) * 8;
        let readback_bytes = bounds_bytes + key_bytes * 2;
        let (bytes, readback) = self.runtime.copy_and_map(
            &[
                (&self.bounds, 0, bounds_bytes),
                (&self.morton_keys, 0, key_bytes),
                (&self.node_tiles, 0, key_bytes),
            ],
            &self.readback,
            readback_bytes,
        )?;
        let ordered = read_pods::<u32>(&bytes[..bounds_bytes as usize])?;
        let pairs = read_pods::<[u32; 2]>(&bytes[bounds_bytes as usize..])?;
        let split = self.nodes as usize;
        Ok(SpatialOutput {
            bounds_min: [
                ordered_float(ordered[0]),
                ordered_float(ordered[1]),
                ordered_float(ordered[2]),
            ],
            bounds_max: [
                ordered_float(ordered[3]),
                ordered_float(ordered[4]),
                ordered_float(ordered[5]),
            ],
            morton_keys: pairs[..split].iter().map(|pair| pair_u64(*pair)).collect(),
            node_tiles: pairs[split..].iter().map(|pair| pair_u64(*pair)).collect(),
            timing: StageTiming {
                prepare_micros: self.prepare_micros,
                dispatch_micros: micros(dispatch),
                readback_micros: micros(readback),
                gpu_bytes: self.gpu_bytes,
            },
        })
    }

    pub fn build_lod<'a>(
        &'a self,
        order: &[u32],
        ranges: &[LodRange],
    ) -> Result<ResidentLod<'a>, GalaxyGpuError> {
        let started = Instant::now();
        validate_order(self.nodes as usize, order)?;
        validate_ranges(self.nodes as usize, ranges)?;
        let range_count = u32::try_from(ranges.len())
            .map_err(|_| GalaxyGpuError::Input("LOD range count exceeds u32".to_owned()))?;
        let dispatch = self.runtime.workgroup_dispatch(range_count)?;
        let order_bytes = bytes_for::<u32>(order.len())?;
        let range_bytes = bytes_for::<LodRange>(ranges.len())?;
        let aggregate_bytes = bytes_for::<LodAggregate>(ranges.len())?;
        let map_bytes = bytes_for::<u32>(self.nodes as usize)?;
        let readback_bytes = aggregate_bytes + map_bytes;
        let stage_bytes = checked_sum(&[
            order_bytes,
            range_bytes,
            aggregate_bytes,
            map_bytes,
            readback_bytes,
            16,
        ])?;
        let gpu_bytes = self
            .gpu_bytes
            .checked_add(stage_bytes)
            .ok_or_else(|| GalaxyGpuError::Residency("GPU byte accounting overflow".to_owned()))?;
        self.runtime.validate_residency(
            gpu_bytes,
            &[order_bytes, range_bytes, aggregate_bytes, map_bytes],
        )?;
        let order = storage(&self.runtime.device, "galaxy-spatial-order", order, false);
        let ranges = storage(&self.runtime.device, "galaxy-lod-ranges", ranges, false);
        let aggregates = empty_storage(
            &self.runtime.device,
            "galaxy-lod-aggregates",
            aggregate_bytes,
            true,
        );
        let node_to_lod =
            empty_storage(&self.runtime.device, "galaxy-node-to-lod", map_bytes, true);
        let readback = readback(&self.runtime.device, "galaxy-lod-readback", readback_bytes);
        let params = storage(
            &self.runtime.device,
            "galaxy-lod-params",
            &[LodParams {
                nodes: self.nodes,
                ranges: range_count,
                dispatch_groups_x: dispatch[0],
                pad: 0,
            }],
            false,
        );
        let aggregate_bind_group = bind_group(
            &self.runtime.device,
            &self.runtime.lod_pipeline,
            "galaxy-aggregate-lod",
            &[
                &self.positions,
                &order,
                &ranges,
                &aggregates,
                &node_to_lod,
                &params,
            ],
        );
        Ok(ResidentLod {
            runtime: self.runtime,
            aggregate_bind_group,
            node_to_lod,
            aggregates,
            readback,
            nodes: self.nodes,
            ranges: range_count,
            dispatch,
            prepare_micros: micros(started.elapsed()),
            gpu_bytes,
        })
    }
}

impl ResidentLod<'_> {
    pub fn execute(&self) -> Result<LodOutput, GalaxyGpuError> {
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("galaxy-lod-dispatch"),
                });
        compute_pass(
            &mut encoder,
            &self.runtime.lod_pipeline,
            &self.aggregate_bind_group,
            self.dispatch,
            "galaxy-aggregate-lod",
        );
        let dispatch = self.runtime.submit(encoder)?;
        let aggregate_bytes = u64::from(self.ranges) * size_of_u64::<LodAggregate>();
        let map_bytes = u64::from(self.nodes) * 4;
        let readback_bytes = aggregate_bytes + map_bytes;
        let (bytes, readback) = self.runtime.copy_and_map(
            &[
                (&self.aggregates, 0, aggregate_bytes),
                (&self.node_to_lod, 0, map_bytes),
            ],
            &self.readback,
            readback_bytes,
        )?;
        Ok(LodOutput {
            aggregates: read_pods(&bytes[..aggregate_bytes as usize])?,
            node_to_lod: read_pods(&bytes[aggregate_bytes as usize..])?,
            timing: StageTiming {
                prepare_micros: self.prepare_micros,
                dispatch_micros: micros(dispatch),
                readback_micros: micros(readback),
                gpu_bytes: self.gpu_bytes,
            },
        })
    }

    pub fn remap_edges(&self, edges: &[EdgeInput]) -> Result<BundleKeyOutput, GalaxyGpuError> {
        let started = Instant::now();
        validate_edges(edges, self.nodes as usize)?;
        if edges.is_empty() {
            return Ok(BundleKeyOutput {
                keys: Vec::new(),
                timing: StageTiming {
                    prepare_micros: micros(started.elapsed()),
                    gpu_bytes: self.gpu_bytes,
                    ..StageTiming::default()
                },
            });
        }
        let edge_count = u32::try_from(edges.len())
            .map_err(|_| GalaxyGpuError::Input("edge count exceeds u32".to_owned()))?;
        let dispatch_shape = self.runtime.invocation_dispatch(edge_count)?;
        let edge_bytes = bytes_for::<EdgeInput>(edges.len())?;
        let key_bytes = bytes_for::<RawBundleKey>(edges.len())?;
        let stage_bytes = checked_sum(&[edge_bytes, key_bytes, key_bytes, 16])?;
        let gpu_bytes = self
            .gpu_bytes
            .checked_add(stage_bytes)
            .ok_or_else(|| GalaxyGpuError::Residency("GPU byte accounting overflow".to_owned()))?;
        self.runtime
            .validate_residency(gpu_bytes, &[edge_bytes, key_bytes])?;
        let edge_buffer = storage(&self.runtime.device, "galaxy-edges", edges, false);
        let keys = empty_storage(
            &self.runtime.device,
            "galaxy-raw-bundle-keys",
            key_bytes,
            true,
        );
        let readback = readback(&self.runtime.device, "galaxy-edge-readback", key_bytes);
        let params = storage(
            &self.runtime.device,
            "galaxy-edge-params",
            &[EdgeParams {
                edges: edge_count,
                nodes: self.nodes,
                dispatch_groups_x: dispatch_shape[0],
                pad: 0,
            }],
            false,
        );
        let bind_group = bind_group(
            &self.runtime.device,
            &self.runtime.edge_pipeline,
            "galaxy-remap-edge-bundles",
            &[&edge_buffer, &self.node_to_lod, &keys, &params],
        );
        let prepare_micros = micros(started.elapsed());
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("galaxy-edge-dispatch"),
                });
        compute_pass(
            &mut encoder,
            &self.runtime.edge_pipeline,
            &bind_group,
            dispatch_shape,
            "galaxy-remap-edge-bundles",
        );
        let dispatch = self.runtime.submit(encoder)?;
        let (bytes, readback_time) =
            self.runtime
                .copy_and_map(&[(&keys, 0, key_bytes)], &readback, key_bytes)?;
        Ok(BundleKeyOutput {
            keys: read_pods(&bytes)?,
            timing: StageTiming {
                prepare_micros,
                dispatch_micros: micros(dispatch),
                readback_micros: micros(readback_time),
                gpu_bytes,
            },
        })
    }
}

fn compute_pass(
    encoder: &mut wgpu::CommandEncoder,
    pipeline: &wgpu::ComputePipeline,
    bind_group: &wgpu::BindGroup,
    dispatch: [u32; 2],
    label: &'static str,
) {
    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
        label: Some(label),
        timestamp_writes: None,
    });
    pass.set_pipeline(pipeline);
    pass.set_bind_group(0, bind_group, &[]);
    pass.dispatch_workgroups(dispatch[0], dispatch[1], 1);
}

fn bind_group(
    device: &wgpu::Device,
    pipeline: &wgpu::ComputePipeline,
    label: &'static str,
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
        label: Some(label),
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
        size,
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

fn bytes_for<T>(count: usize) -> Result<u64, GalaxyGpuError> {
    u64::try_from(count)
        .ok()
        .and_then(|count| count.checked_mul(size_of_u64::<T>()))
        .ok_or_else(|| GalaxyGpuError::Residency("GPU byte accounting overflow".to_owned()))
}

const fn size_of_u64<T>() -> u64 {
    std::mem::size_of::<T>() as u64
}

fn checked_sum(values: &[u64]) -> Result<u64, GalaxyGpuError> {
    values.iter().try_fold(0u64, |total, value| {
        total
            .checked_add(*value)
            .ok_or_else(|| GalaxyGpuError::Residency("GPU byte accounting overflow".to_owned()))
    })
}

fn read_pods<T: Pod>(bytes: &[u8]) -> Result<Vec<T>, GalaxyGpuError> {
    let width = std::mem::size_of::<T>();
    if width == 0 || !bytes.len().is_multiple_of(width) {
        return Err(GalaxyGpuError::Execution(
            "readback byte extent does not match output record".to_owned(),
        ));
    }
    Ok(bytes
        .chunks_exact(width)
        .map(bytemuck::pod_read_unaligned)
        .collect())
}

fn pair_u64(pair: [u32; 2]) -> u64 {
    u64::from(pair[0]) | (u64::from(pair[1]) << 32)
}

fn ordered_float(value: u32) -> f32 {
    let bits = if value & 0x8000_0000 == 0 {
        !value
    } else {
        value ^ 0x8000_0000
    };
    f32::from_bits(bits)
}

fn micros(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}
