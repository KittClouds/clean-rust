use std::sync::mpsc;
use std::time::Instant;

use bytemuck::Pod;

use super::*;
use crate::{BridgePreprocessOutput, PrepartitionOutput};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ResidentStage {
    Uploaded,
    Prepartitioned,
    Completed,
}

/// Upload-once graph generation. Prepartition analytics and post-Leiden bridge
/// preprocessing share the same edge, policy, and scratch buffers.
pub struct ResidentGraphAnalytics<'a> {
    runtime: &'a GpuGraphAnalyticsRuntime,
    buffers: Buffers,
    config: RunConfig,
    edge_count: u32,
    node_count: u32,
    family_count: u32,
    rank_count: u32,
    edge_groups: u32,
    node_groups: u32,
    rank_groups: u32,
    check_groups: u32,
    prepare_micros: u64,
    stage: ResidentStage,
}

impl GpuGraphAnalyticsRuntime {
    pub fn upload_generation(
        &self,
        input: AnalyticsInput<'_>,
        config: RunConfig,
    ) -> Result<ResidentGraphAnalytics<'_>, GraphAnalyticsError> {
        let started = Instant::now();
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
        Ok(ResidentGraphAnalytics {
            runtime: self,
            buffers,
            config,
            edge_count,
            node_count: input.node_count,
            family_count: input.relation_family_count,
            rank_count,
            edge_groups,
            node_groups,
            rank_groups,
            check_groups,
            prepare_micros: micros(started.elapsed()),
            stage: ResidentStage::Uploaded,
        })
    }
}

impl ResidentGraphAnalytics<'_> {
    pub fn resident_bytes(&self) -> u64 {
        self.buffers.resident_bytes
    }

    pub fn prepartition(&mut self) -> Result<PrepartitionOutput, GraphAnalyticsError> {
        if self.stage != ResidentStage::Uploaded {
            return Err(GraphAnalyticsError::Input(
                "resident prepartition stage may execute exactly once".to_owned(),
            ));
        }
        let mask = bind_group(
            &self.runtime.device,
            &self.runtime.mask_pipeline,
            "resident policy mask",
            &[
                (0, &self.buffers.params),
                (1, &self.buffers.edges),
                (2, &self.buffers.node_mask),
                (3, &self.buffers.active),
            ],
        );
        let degree = bind_group(
            &self.runtime.device,
            &self.runtime.degree_pipeline,
            "resident degree stats",
            &[
                (0, &self.buffers.params),
                (1, &self.buffers.edges),
                (2, &self.buffers.active),
                (3, &self.buffers.out_degree),
                (4, &self.buffers.in_degree),
                (5, &self.buffers.incident_degree),
                (6, &self.buffers.family_histogram),
                (7, &self.buffers.out_strength),
            ],
        );
        let neighborhood = bind_group(
            &self.runtime.device,
            &self.runtime.neighborhood_pipeline,
            "resident neighborhood stats",
            &[
                (0, &self.buffers.params),
                (1, &self.buffers.edges),
                (2, &self.buffers.active),
                (3, &self.buffers.incident_degree),
                (4, &self.buffers.neighbor_degree_sum),
            ],
        );
        let component_init = bind_group(
            &self.runtime.device,
            &self.runtime.component_init_pipeline,
            "resident component init",
            &[
                (0, &self.buffers.params),
                (2, &self.buffers.node_mask),
                (4, &self.buffers.labels),
            ],
        );
        let component_hook = bind_group(
            &self.runtime.device,
            &self.runtime.component_hook_pipeline,
            "resident component hook",
            &[
                (0, &self.buffers.params),
                (1, &self.buffers.edges),
                (3, &self.buffers.active),
                (4, &self.buffers.labels),
            ],
        );
        let component_compress = bind_group(
            &self.runtime.device,
            &self.runtime.component_compress_pipeline,
            "resident component compress",
            &[(0, &self.buffers.params), (4, &self.buffers.labels)],
        );
        let component_check = bind_group(
            &self.runtime.device,
            &self.runtime.component_check_pipeline,
            "resident component check",
            &[
                (0, &self.buffers.params),
                (1, &self.buffers.edges),
                (3, &self.buffers.active),
                (4, &self.buffers.labels),
                (5, &self.buffers.changed),
            ],
        );
        let diffusion_ab =
            self.runtime
                .diffusion_bind(&self.buffers, &self.buffers.rank_a, &self.buffers.rank_b);
        let diffusion_ba =
            self.runtime
                .diffusion_bind(&self.buffers, &self.buffers.rank_b, &self.buffers.rank_a);

        let execute_started = Instant::now();
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("resident graph prepartition"),
                });
        for buffer in [
            &self.buffers.active,
            &self.buffers.out_degree,
            &self.buffers.in_degree,
            &self.buffers.incident_degree,
            &self.buffers.family_histogram,
            &self.buffers.out_strength,
            &self.buffers.neighbor_degree_sum,
            &self.buffers.labels,
            &self.buffers.changed,
        ] {
            encoder.clear_buffer(buffer, 0, None);
        }
        dispatch(
            &mut encoder,
            &self.runtime.mask_pipeline,
            &mask,
            self.edge_groups,
            "resident policy mask",
        );
        dispatch(
            &mut encoder,
            &self.runtime.degree_pipeline,
            &degree,
            self.edge_groups,
            "resident degree stats",
        );
        dispatch(
            &mut encoder,
            &self.runtime.neighborhood_pipeline,
            &neighborhood,
            self.edge_groups,
            "resident neighborhood stats",
        );
        dispatch(
            &mut encoder,
            &self.runtime.component_init_pipeline,
            &component_init,
            self.node_groups,
            "resident component init",
        );
        for _ in 0..self.config.weak_component_iterations {
            dispatch(
                &mut encoder,
                &self.runtime.component_hook_pipeline,
                &component_hook,
                self.edge_groups,
                "resident component hook",
            );
            dispatch(
                &mut encoder,
                &self.runtime.component_compress_pipeline,
                &component_compress,
                self.node_groups,
                "resident component compress",
            );
        }
        dispatch(
            &mut encoder,
            &self.runtime.component_check_pipeline,
            &component_check,
            self.check_groups,
            "resident component check",
        );
        for iteration in 0..self.config.diffusion_iterations {
            let bind = if iteration.is_multiple_of(2) {
                &diffusion_ab
            } else {
                &diffusion_ba
            };
            dispatch(
                &mut encoder,
                &self.runtime.diffusion_pipeline,
                bind,
                self.rank_groups,
                "resident diffusion",
            );
        }
        self.runtime.submit(encoder)?;
        let execute_micros = micros(execute_started.elapsed());
        let final_ranks = if self.config.diffusion_iterations.is_multiple_of(2) {
            &self.buffers.rank_a
        } else {
            &self.buffers.rank_b
        };
        let node_bytes = u64::from(self.node_count) * 4;
        let readback_started = Instant::now();
        let bytes = self.readback_selected(&[
            (&self.buffers.active, u64::from(self.edge_count) * 4),
            (&self.buffers.out_degree, node_bytes),
            (&self.buffers.in_degree, node_bytes),
            (&self.buffers.incident_degree, node_bytes),
            (
                &self.buffers.family_histogram,
                u64::from(self.family_count) * 4,
            ),
            (&self.buffers.out_strength, node_bytes),
            (&self.buffers.neighbor_degree_sum, node_bytes),
            (&self.buffers.labels, node_bytes),
            (&self.buffers.changed, 4),
            (final_ranks, u64::from(self.rank_count) * 4),
        ])?;
        let readback_micros = micros(readback_started.elapsed());
        let readback_bytes = bytes.len() as u64;
        let mut cursor = PodCursor::new(&bytes);
        let active_edge_mask = cursor.u32(self.edge_count)?;
        let out_degree = cursor.u32(self.node_count)?;
        let in_degree = cursor.u32(self.node_count)?;
        let incident_degree = cursor.u32(self.node_count)?;
        let relation_family_histogram = cursor.u32(self.family_count)?;
        let out_strength = cursor.u32(self.node_count)?;
        let neighbor_degree_sum = cursor.u32(self.node_count)?;
        let component_labels = cursor.u32(self.node_count)?;
        let changed = cursor.u32(1)?[0];
        let diffusion_ranks = cursor.f32(self.rank_count)?;
        cursor.finish()?;
        if changed != 0 {
            return Err(GraphAnalyticsError::ComponentsDidNotConverge {
                iterations: self.config.weak_component_iterations,
            });
        }
        self.stage = ResidentStage::Prepartitioned;
        Ok(PrepartitionOutput {
            active_edge_mask,
            out_degree,
            in_degree,
            incident_degree,
            relation_family_histogram,
            component_labels,
            out_strength,
            neighbor_degree_sum,
            diffusion_ranks,
            timing: AnalyticsTiming {
                prepare_micros: self.prepare_micros,
                execute_micros,
                readback_micros,
                gpu_resident_bytes: self.buffers.resident_bytes,
                readback_bytes,
            },
        })
    }

    pub fn postpartition(
        &mut self,
        partition_labels: &[u32],
    ) -> Result<BridgePreprocessOutput, GraphAnalyticsError> {
        if self.stage != ResidentStage::Prepartitioned {
            return Err(GraphAnalyticsError::Input(
                "resident postpartition requires one completed prepartition stage".to_owned(),
            ));
        }
        if partition_labels.len() != self.node_count as usize {
            return Err(GraphAnalyticsError::Input(
                "postpartition labels must match resident node_count".to_owned(),
            ));
        }
        let execute_started = Instant::now();
        self.runtime.queue.write_buffer(
            &self.buffers.partition,
            0,
            bytemuck::cast_slice(partition_labels),
        );
        let bridge = bind_group(
            &self.runtime.device,
            &self.runtime.bridge_pipeline,
            "resident bridge stats",
            &[
                (0, &self.buffers.params),
                (1, &self.buffers.edges),
                (2, &self.buffers.active),
                (3, &self.buffers.partition),
                (4, &self.buffers.total_strength),
                (5, &self.buffers.boundary_degree),
                (6, &self.buffers.boundary_strength),
            ],
        );
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("resident graph postpartition"),
                });
        for buffer in [
            &self.buffers.total_strength,
            &self.buffers.boundary_degree,
            &self.buffers.boundary_strength,
        ] {
            encoder.clear_buffer(buffer, 0, None);
        }
        dispatch(
            &mut encoder,
            &self.runtime.bridge_pipeline,
            &bridge,
            self.edge_groups,
            "resident bridge stats",
        );
        self.runtime.submit(encoder)?;
        let execute_micros = micros(execute_started.elapsed());
        let node_bytes = u64::from(self.node_count) * 4;
        let readback_started = Instant::now();
        let bytes = self.readback_selected(&[
            (&self.buffers.total_strength, node_bytes),
            (&self.buffers.boundary_degree, node_bytes),
            (&self.buffers.boundary_strength, node_bytes),
        ])?;
        let readback_micros = micros(readback_started.elapsed());
        let readback_bytes = bytes.len() as u64;
        let mut cursor = PodCursor::new(&bytes);
        let total_strength = cursor.u32(self.node_count)?;
        let boundary_degree = cursor.u32(self.node_count)?;
        let boundary_strength = cursor.u32(self.node_count)?;
        cursor.finish()?;
        self.stage = ResidentStage::Completed;
        Ok(BridgePreprocessOutput {
            total_strength,
            boundary_degree,
            boundary_strength,
            timing: AnalyticsTiming {
                prepare_micros: 0,
                execute_micros,
                readback_micros,
                gpu_resident_bytes: self.buffers.resident_bytes,
                readback_bytes,
            },
        })
    }

    fn readback_selected(
        &self,
        sources: &[(&wgpu::Buffer, u64)],
    ) -> Result<Vec<u8>, GraphAnalyticsError> {
        let total = sources.iter().try_fold(0_u64, |sum, (_, bytes)| {
            sum.checked_add(*bytes).ok_or_else(|| {
                GraphAnalyticsError::Execution("resident readback extent overflow".to_owned())
            })
        })?;
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("resident analytics readback"),
                });
        let mut offset = 0_u64;
        for (source, bytes) in sources {
            if *bytes != 0 {
                encoder.copy_buffer_to_buffer(source, 0, &self.buffers.readback, offset, *bytes);
                offset += bytes;
            }
        }
        let submission = self.runtime.queue.submit([encoder.finish()]);
        let slice = self.buffers.readback.slice(..total);
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
        self.buffers.readback.unmap();
        Ok(bytes)
    }
}

struct PodCursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> PodCursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn u32(&mut self, count: u32) -> Result<Vec<u32>, GraphAnalyticsError> {
        self.pods(count)
    }

    fn f32(&mut self, count: u32) -> Result<Vec<f32>, GraphAnalyticsError> {
        self.pods(count)
    }

    fn pods<T: Pod>(&mut self, count: u32) -> Result<Vec<T>, GraphAnalyticsError> {
        let bytes = (count as usize)
            .checked_mul(std::mem::size_of::<T>())
            .and_then(|width| self.offset.checked_add(width).map(|end| (width, end)))
            .ok_or_else(|| {
                GraphAnalyticsError::Execution("resident output extent overflow".to_owned())
            })?;
        let slice = self.bytes.get(self.offset..bytes.1).ok_or_else(|| {
            GraphAnalyticsError::Execution("resident output is truncated".to_owned())
        })?;
        self.offset += bytes.0;
        Ok(slice
            .chunks_exact(std::mem::size_of::<T>())
            .map(bytemuck::pod_read_unaligned)
            .collect())
    }

    fn finish(self) -> Result<(), GraphAnalyticsError> {
        if self.offset == self.bytes.len() {
            Ok(())
        } else {
            Err(GraphAnalyticsError::Execution(
                "resident output contains trailing bytes".to_owned(),
            ))
        }
    }
}
