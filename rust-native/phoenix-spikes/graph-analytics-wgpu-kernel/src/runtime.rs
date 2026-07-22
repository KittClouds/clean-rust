use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use crate::cpu::validate_input;
use crate::gpu_storage::{
    Buffers, Params, ReadbackLayout, bind_group, dispatch, incoming_csr, input_storage, micros,
    output_storage, pipeline, rank_storage, read_f32, read_u32, readback_buffer, uniform,
    validate_accumulator_bounds,
};
use crate::{AnalyticsInput, AnalyticsOutput, AnalyticsTiming, GraphAnalyticsError, RunConfig};

mod resident;
pub use resident::ResidentGraphAnalytics;

const GPU_WAIT: Duration = Duration::from_secs(60);
const WORKGROUP_SIZE: u32 = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdapterReceipt {
    pub name: String,
    pub backend: String,
    pub device_type: String,
    pub driver: String,
    pub driver_info: String,
    pub vendor: u32,
    pub device: u32,
    pub maximum_buffer_bytes: u64,
    pub maximum_storage_binding_bytes: u64,
    pub maximum_workgroups_per_dimension: u32,
}

pub struct GpuGraphAnalyticsRuntime {
    device: Arc<wgpu::Device>,
    queue: Arc<wgpu::Queue>,
    mask_pipeline: wgpu::ComputePipeline,
    degree_pipeline: wgpu::ComputePipeline,
    bridge_pipeline: wgpu::ComputePipeline,
    neighborhood_pipeline: wgpu::ComputePipeline,
    component_init_pipeline: wgpu::ComputePipeline,
    component_hook_pipeline: wgpu::ComputePipeline,
    component_compress_pipeline: wgpu::ComputePipeline,
    component_check_pipeline: wgpu::ComputePipeline,
    diffusion_pipeline: wgpu::ComputePipeline,
    limits: wgpu::Limits,
    maximum_resident_bytes: u64,
    receipt: AdapterReceipt,
}

impl GpuGraphAnalyticsRuntime {
    pub fn request(maximum_resident_bytes: u64) -> Result<Self, GraphAnalyticsError> {
        if maximum_resident_bytes == 0 {
            return Err(GraphAnalyticsError::Residency(
                "configured resident byte budget must be nonzero".to_owned(),
            ));
        }
        pollster::block_on(Self::request_async(maximum_resident_bytes))
    }

    async fn request_async(maximum_resident_bytes: u64) -> Result<Self, GraphAnalyticsError> {
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
            .map_err(|error| GraphAnalyticsError::Adapter(error.to_string()))?;
        let info = adapter.get_info();
        let limits = adapter.limits();
        if limits.max_storage_buffers_per_shader_stage < 8 {
            return Err(GraphAnalyticsError::Device(format!(
                "adapter exposes {} storage buffers per stage; diffusion requires 8",
                limits.max_storage_buffers_per_shader_stage
            )));
        }
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("phoenix-offline-graph-analytics"),
                required_limits: limits.clone(),
                memory_hints: wgpu::MemoryHints::Performance,
                ..Default::default()
            })
            .await
            .map_err(|error| GraphAnalyticsError::Device(error.to_string()))?;
        let mask_pipeline = pipeline(
            &device,
            "policy mask",
            include_str!("policy_mask.wgsl"),
            "classify_edges",
        );
        let degree_pipeline = pipeline(
            &device,
            "degree stats",
            include_str!("degree_stats.wgsl"),
            "accumulate_degrees",
        );
        let bridge_pipeline = pipeline(
            &device,
            "bridge stats",
            include_str!("bridge_stats.wgsl"),
            "accumulate_bridge_inputs",
        );
        let neighborhood_pipeline = pipeline(
            &device,
            "neighborhood stats",
            include_str!("neighborhood_stats.wgsl"),
            "accumulate_neighborhoods",
        );
        let component_source = include_str!("components.wgsl");
        let component_init_pipeline = pipeline(
            &device,
            "component init",
            component_source,
            "initialize_components",
        );
        let component_hook_pipeline = pipeline(
            &device,
            "component hook",
            component_source,
            "hook_components",
        );
        let component_compress_pipeline = pipeline(
            &device,
            "component compress",
            component_source,
            "compress_components",
        );
        let component_check_pipeline = pipeline(
            &device,
            "component check",
            component_source,
            "check_components",
        );
        let diffusion_pipeline = pipeline(
            &device,
            "multi-source diffusion",
            include_str!("diffusion.wgsl"),
            "diffuse",
        );
        let receipt = AdapterReceipt {
            name: info.name,
            backend: format!("{:?}", info.backend),
            device_type: format!("{:?}", info.device_type),
            driver: info.driver,
            driver_info: info.driver_info,
            vendor: info.vendor,
            device: info.device,
            maximum_buffer_bytes: limits.max_buffer_size,
            maximum_storage_binding_bytes: limits.max_storage_buffer_binding_size,
            maximum_workgroups_per_dimension: limits.max_compute_workgroups_per_dimension,
        };
        Ok(Self {
            device: Arc::new(device),
            queue: Arc::new(queue),
            mask_pipeline,
            degree_pipeline,
            bridge_pipeline,
            neighborhood_pipeline,
            component_init_pipeline,
            component_hook_pipeline,
            component_compress_pipeline,
            component_check_pipeline,
            diffusion_pipeline,
            limits,
            maximum_resident_bytes,
            receipt,
        })
    }

    pub fn adapter_receipt(&self) -> &AdapterReceipt {
        &self.receipt
    }

    pub fn analyze(
        &self,
        input: AnalyticsInput<'_>,
        config: RunConfig,
    ) -> Result<AnalyticsOutput, GraphAnalyticsError> {
        let prepare_started = Instant::now();
        validate_input(input, config)?;
        validate_accumulator_bounds(input)?;
        let edge_count = u32::try_from(input.edges.len()).map_err(|_| {
            GraphAnalyticsError::Input("edge count exceeds packed u32 capacity".to_owned())
        })?;
        let rank_count = input
            .node_count
            .checked_mul(input.diffusion_source_count)
            .ok_or_else(|| {
                GraphAnalyticsError::Input("diffusion rank extent overflow".to_owned())
            })?;
        let edge_groups = self.dispatch_groups(edge_count)?;
        let node_groups = self.dispatch_groups(input.node_count)?;
        let rank_groups = self.dispatch_groups(rank_count)?;
        let check_groups = self.dispatch_groups(input.node_count.max(edge_count))?;
        let (incoming_offsets, incoming_edges) = incoming_csr(input)?;
        let layout = ReadbackLayout::new(input, rank_count)?;
        let params = Params {
            node_count: input.node_count,
            edge_count,
            family_count: input.relation_family_count,
            family_mask: input.edge_policy.admitted_relation_families,
            minimum_weight: input.edge_policy.minimum_weight,
            source_count: input.diffusion_source_count,
            wcc_iterations: config.weak_component_iterations,
            diffusion_iterations: config.diffusion_iterations,
            damping: config.diffusion_damping,
            restart: 1.0 - config.diffusion_damping,
            pad0: 0,
            pad1: 0,
        };
        let buffers = self.allocate(input, &params, &incoming_offsets, &incoming_edges, &layout)?;
        let prepare_micros = micros(prepare_started.elapsed());

        let mask_bind = bind_group(
            &self.device,
            &self.mask_pipeline,
            "policy mask",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (2, &buffers.node_mask),
                (3, &buffers.active),
            ],
        );
        let degree_bind = bind_group(
            &self.device,
            &self.degree_pipeline,
            "degree stats",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (2, &buffers.active),
                (3, &buffers.out_degree),
                (4, &buffers.in_degree),
                (5, &buffers.incident_degree),
                (6, &buffers.family_histogram),
                (7, &buffers.out_strength),
            ],
        );
        let bridge_bind = bind_group(
            &self.device,
            &self.bridge_pipeline,
            "bridge stats",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (2, &buffers.active),
                (3, &buffers.partition),
                (4, &buffers.total_strength),
                (5, &buffers.boundary_degree),
                (6, &buffers.boundary_strength),
            ],
        );
        let neighborhood_bind = bind_group(
            &self.device,
            &self.neighborhood_pipeline,
            "neighborhood stats",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (2, &buffers.active),
                (3, &buffers.incident_degree),
                (4, &buffers.neighbor_degree_sum),
            ],
        );
        let component_init_bind = bind_group(
            &self.device,
            &self.component_init_pipeline,
            "component init",
            &[
                (0, &buffers.params),
                (2, &buffers.node_mask),
                (4, &buffers.labels),
            ],
        );
        let component_hook_bind = bind_group(
            &self.device,
            &self.component_hook_pipeline,
            "component hook",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (3, &buffers.active),
                (4, &buffers.labels),
            ],
        );
        let component_compress_bind = bind_group(
            &self.device,
            &self.component_compress_pipeline,
            "component compress",
            &[(0, &buffers.params), (4, &buffers.labels)],
        );
        let component_check_bind = bind_group(
            &self.device,
            &self.component_check_pipeline,
            "component check",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (3, &buffers.active),
                (4, &buffers.labels),
                (5, &buffers.changed),
            ],
        );
        let diffusion_ab = self.diffusion_bind(&buffers, &buffers.rank_a, &buffers.rank_b);
        let diffusion_ba = self.diffusion_bind(&buffers, &buffers.rank_b, &buffers.rank_a);

        let execute_started = Instant::now();
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("offline graph analytics"),
            });
        for buffer in buffers.zeroed_outputs() {
            encoder.clear_buffer(buffer, 0, None);
        }
        dispatch(
            &mut encoder,
            &self.mask_pipeline,
            &mask_bind,
            edge_groups,
            "policy mask",
        );
        dispatch(
            &mut encoder,
            &self.degree_pipeline,
            &degree_bind,
            edge_groups,
            "degree stats",
        );
        dispatch(
            &mut encoder,
            &self.bridge_pipeline,
            &bridge_bind,
            edge_groups,
            "bridge stats",
        );
        dispatch(
            &mut encoder,
            &self.neighborhood_pipeline,
            &neighborhood_bind,
            edge_groups,
            "neighborhood stats",
        );
        dispatch(
            &mut encoder,
            &self.component_init_pipeline,
            &component_init_bind,
            node_groups,
            "component init",
        );
        for _ in 0..config.weak_component_iterations {
            dispatch(
                &mut encoder,
                &self.component_hook_pipeline,
                &component_hook_bind,
                edge_groups,
                "component hook",
            );
            dispatch(
                &mut encoder,
                &self.component_compress_pipeline,
                &component_compress_bind,
                node_groups,
                "component compress",
            );
        }
        dispatch(
            &mut encoder,
            &self.component_check_pipeline,
            &component_check_bind,
            check_groups,
            "component check",
        );
        for iteration in 0..config.diffusion_iterations {
            let bind = if iteration.is_multiple_of(2) {
                &diffusion_ab
            } else {
                &diffusion_ba
            };
            dispatch(
                &mut encoder,
                &self.diffusion_pipeline,
                bind,
                rank_groups,
                "diffusion",
            );
        }
        self.submit(encoder)?;
        let execute_micros = micros(execute_started.elapsed());

        let final_ranks = if config.diffusion_iterations.is_multiple_of(2) {
            &buffers.rank_a
        } else {
            &buffers.rank_b
        };
        let readback_started = Instant::now();
        let bytes = self.readback(&buffers, final_ranks, &layout)?;
        let readback_micros = micros(readback_started.elapsed());
        let changed = read_u32(&bytes, layout.changed).into_iter().next().unwrap();
        if changed != 0 {
            return Err(GraphAnalyticsError::ComponentsDidNotConverge {
                iterations: config.weak_component_iterations,
            });
        }
        Ok(AnalyticsOutput {
            active_edge_mask: read_u32(&bytes, layout.active),
            out_degree: read_u32(&bytes, layout.out_degree),
            in_degree: read_u32(&bytes, layout.in_degree),
            incident_degree: read_u32(&bytes, layout.incident_degree),
            relation_family_histogram: read_u32(&bytes, layout.family_histogram),
            component_labels: read_u32(&bytes, layout.labels),
            out_strength: read_u32(&bytes, layout.out_strength),
            total_strength: read_u32(&bytes, layout.total_strength),
            boundary_degree: read_u32(&bytes, layout.boundary_degree),
            boundary_strength: read_u32(&bytes, layout.boundary_strength),
            neighbor_degree_sum: read_u32(&bytes, layout.neighbor_degree_sum),
            diffusion_ranks: read_f32(&bytes, layout.ranks),
            timing: AnalyticsTiming {
                prepare_micros,
                execute_micros,
                readback_micros,
                gpu_resident_bytes: buffers.resident_bytes,
                readback_bytes: layout.total,
            },
        })
    }

    fn diffusion_bind<'a>(
        &self,
        buffers: &'a Buffers,
        input: &'a wgpu::Buffer,
        output: &'a wgpu::Buffer,
    ) -> wgpu::BindGroup {
        bind_group(
            &self.device,
            &self.diffusion_pipeline,
            "diffusion",
            &[
                (0, &buffers.params),
                (1, &buffers.edges),
                (2, &buffers.active),
                (3, &buffers.incoming_offsets),
                (4, &buffers.incoming_edges),
                (5, &buffers.out_strength),
                (6, &buffers.seeds),
                (7, input),
                (8, output),
            ],
        )
    }

    fn allocate(
        &self,
        input: AnalyticsInput<'_>,
        params: &Params,
        incoming_offsets: &[u32],
        incoming_edges: &[u32],
        layout: &ReadbackLayout,
    ) -> Result<Buffers, GraphAnalyticsError> {
        let nodes = input.node_count as u64;
        let edges = input.edges.len() as u64;
        let families = input.relation_family_count as u64;
        let ranks = input.diffusion_seeds.len() as u64;
        let bytes = |count: u64| {
            count.checked_mul(4).ok_or_else(|| {
                GraphAnalyticsError::Residency("GPU byte accounting overflow".to_owned())
            })
        };
        let edge_bytes = edges.checked_mul(16).ok_or_else(|| {
            GraphAnalyticsError::Residency("GPU edge byte accounting overflow".to_owned())
        })?;
        let node_bytes = bytes(nodes)?;
        let edge_word_bytes = bytes(edges)?;
        let family_bytes = bytes(families)?;
        let rank_bytes = bytes(ranks)?;
        let incoming_offset_bytes = bytes(nodes + 1)?;
        let incoming_edge_bytes = bytes(incoming_edges.len() as u64)?;
        let binding_limit = self
            .limits
            .max_buffer_size
            .min(self.limits.max_storage_buffer_binding_size);
        for extent in [
            edge_bytes,
            node_bytes,
            edge_word_bytes,
            family_bytes,
            rank_bytes,
            incoming_offset_bytes,
            incoming_edge_bytes,
        ] {
            if extent > binding_limit {
                return Err(GraphAnalyticsError::Residency(format!(
                    "{extent} byte binding exceeds adapter limit {binding_limit}"
                )));
            }
        }
        let resident_bytes = 48
            + edge_bytes
            + node_bytes * 11
            + edge_word_bytes
            + family_bytes
            + incoming_offset_bytes
            + incoming_edge_bytes
            + rank_bytes * 3
            + 4
            + layout.total;
        if resident_bytes > self.maximum_resident_bytes {
            return Err(GraphAnalyticsError::Residency(format!(
                "{resident_bytes} bytes exceed configured {} byte budget",
                self.maximum_resident_bytes
            )));
        }
        let output = |label, size| output_storage(&self.device, label, size);
        let partition = output("partition labels", node_bytes);
        self.queue
            .write_buffer(&partition, 0, bytemuck::cast_slice(input.partition_labels));
        Ok(Buffers {
            params: uniform(
                &self.device,
                "analytics params",
                std::slice::from_ref(params),
            ),
            edges: input_storage(&self.device, "analytics edges", input.edges),
            node_mask: input_storage(&self.device, "node policy mask", input.node_policy_mask),
            partition,
            active: output("active edges", edge_word_bytes),
            out_degree: output("out degree", node_bytes),
            in_degree: output("in degree", node_bytes),
            incident_degree: output("incident degree", node_bytes),
            family_histogram: output("family histogram", family_bytes),
            out_strength: output("out strength", node_bytes),
            total_strength: output("total strength", node_bytes),
            boundary_degree: output("boundary degree", node_bytes),
            boundary_strength: output("boundary strength", node_bytes),
            neighbor_degree_sum: output("neighbor degree sum", node_bytes),
            labels: output("component labels", node_bytes),
            changed: output("component changed", 4),
            incoming_offsets: input_storage(&self.device, "incoming offsets", incoming_offsets),
            incoming_edges: input_storage(&self.device, "incoming edges", incoming_edges),
            seeds: input_storage(&self.device, "diffusion seeds", input.diffusion_seeds),
            rank_a: rank_storage(&self.device, "rank a", input.diffusion_seeds),
            rank_b: output("rank b", rank_bytes),
            readback: readback_buffer(&self.device, "analytics readback", layout.total),
            resident_bytes,
        })
    }

    fn dispatch_groups(&self, invocations: u32) -> Result<u32, GraphAnalyticsError> {
        let groups = invocations.div_ceil(WORKGROUP_SIZE);
        if groups > self.limits.max_compute_workgroups_per_dimension {
            return Err(GraphAnalyticsError::Residency(format!(
                "{invocations} invocations exceed one-dimensional adapter dispatch capacity"
            )));
        }
        Ok(groups)
    }

    fn submit(&self, encoder: wgpu::CommandEncoder) -> Result<(), GraphAnalyticsError> {
        let submission = self.queue.submit([encoder.finish()]);
        self.device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(GPU_WAIT),
            })
            .map_err(|error| GraphAnalyticsError::Execution(error.to_string()))?;
        Ok(())
    }

    fn readback(
        &self,
        buffers: &Buffers,
        ranks: &wgpu::Buffer,
        layout: &ReadbackLayout,
    ) -> Result<Vec<u8>, GraphAnalyticsError> {
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("analytics readback"),
            });
        for (source, extent) in [
            (&buffers.active, layout.active),
            (&buffers.out_degree, layout.out_degree),
            (&buffers.in_degree, layout.in_degree),
            (&buffers.incident_degree, layout.incident_degree),
            (&buffers.family_histogram, layout.family_histogram),
            (&buffers.out_strength, layout.out_strength),
            (&buffers.total_strength, layout.total_strength),
            (&buffers.boundary_degree, layout.boundary_degree),
            (&buffers.boundary_strength, layout.boundary_strength),
            (&buffers.neighbor_degree_sum, layout.neighbor_degree_sum),
            (&buffers.labels, layout.labels),
            (&buffers.changed, layout.changed),
            (ranks, layout.ranks),
        ] {
            if extent.1 != 0 {
                encoder.copy_buffer_to_buffer(source, 0, &buffers.readback, extent.0, extent.1);
            }
        }
        let submission = self.queue.submit([encoder.finish()]);
        let slice = buffers.readback.slice(..layout.total);
        let (sender, receiver) = mpsc::sync_channel(1);
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = sender.send(result);
        });
        self.device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(GPU_WAIT),
            })
            .map_err(|error| GraphAnalyticsError::Execution(error.to_string()))?;
        receiver
            .recv_timeout(GPU_WAIT)
            .map_err(|error| GraphAnalyticsError::Execution(error.to_string()))?
            .map_err(|error| GraphAnalyticsError::Execution(error.to_string()))?;
        let mapped = slice
            .get_mapped_range()
            .map_err(|error| GraphAnalyticsError::Execution(error.to_string()))?;
        let bytes = mapped.to_vec();
        drop(mapped);
        buffers.readback.unmap();
        Ok(bytes)
    }
}
