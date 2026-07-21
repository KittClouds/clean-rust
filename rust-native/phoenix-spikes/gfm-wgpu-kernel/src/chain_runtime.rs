use std::sync::Arc;
use std::time::{Duration, Instant};

use bytemuck::{Pod, Zeroable};

use crate::chain_support::{
    bind_group, bytes, compute_2d, compute_3d, copy_and_map, empty_storage, micros, read_pods,
    readback, storage,
};
use crate::{
    AdapterReceipt, ChainTiming, ChainTraceOutput, CompactChainOutput, GpuError,
    ResidentChainInput, TopKRecord, ValidatedResidentChain,
};

const GPU_WAIT: Duration = Duration::from_secs(60);
const SHADER: &str = include_str!("resident_chain.wgsl");

pub struct GpuResidentChainRuntime {
    device: Arc<wgpu::Device>,
    queue: Arc<wgpu::Queue>,
    aggregate: wgpu::ComputePipeline,
    dense: wgpu::ComputePipeline,
    norm: wgpu::ComputePipeline,
    score_dense: wgpu::ComputePipeline,
    score_logits: wgpu::ComputePipeline,
    top_k: wgpu::ComputePipeline,
    limits: wgpu::Limits,
    maximum_resident_bytes: u64,
    receipt: AdapterReceipt,
}

pub struct ResidentModelChain<'a> {
    runtime: &'a GpuResidentChainRuntime,
    layers: Vec<LayerDispatch>,
    score_dense: wgpu::BindGroup,
    score_logits: wgpu::BindGroup,
    top_k: Vec<TopKDispatch>,
    final_hidden: wgpu::Buffer,
    logits: wgpu::Buffer,
    candidate_scores_a: wgpu::Buffer,
    candidate_ids_a: wgpu::Buffer,
    candidate_scores_b: wgpu::Buffer,
    candidate_ids_b: wgpu::Buffer,
    compact_readback: wgpu::Buffer,
    shape: ValidatedResidentChain,
    dense_dispatch: [u32; 3],
    node_dispatch: [u32; 2],
    score_dense_dispatch: [u32; 3],
    final_candidates_in_a: bool,
    prepare_micros: u64,
}

struct LayerDispatch {
    aggregate: wgpu::BindGroup,
    dense: wgpu::BindGroup,
    norm: wgpu::BindGroup,
}

struct TopKDispatch {
    bind_group: wgpu::BindGroup,
    dispatch: [u32; 2],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct ChainParams {
    nodes: u32,
    edges: u32,
    relations: u32,
    dim: u32,
    layer: u32,
    dispatch_width: u32,
    score_dim: u32,
    entity_enabled: u32,
    dense_dispatch_height: u32,
    pad: [u32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct TopKParams {
    items: u32,
    top_k: u32,
    dispatch_width: u32,
    pad: u32,
}

impl GpuResidentChainRuntime {
    pub fn request(maximum_resident_bytes: u64) -> Result<Self, GpuError> {
        if maximum_resident_bytes == 0 {
            return Err(GpuError::Residency(
                "resident chain byte budget must be nonzero".to_owned(),
            ));
        }
        pollster::block_on(Self::request_async(maximum_resident_bytes))
    }

    async fn request_async(maximum_resident_bytes: u64) -> Result<Self, GpuError> {
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
                label: Some("phoenix-gfm-resident-chain"),
                required_limits: limits.clone(),
                memory_hints: wgpu::MemoryHints::Performance,
                ..Default::default()
            })
            .await
            .map_err(|error| GpuError::Device(error.to_string()))?;
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("gfm-resident-chain"),
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
        let aggregate = pipeline("chain_distmult");
        let dense = pipeline("chain_dense_update");
        let norm = pipeline("chain_norm_residual");
        let score_dense = pipeline("chain_score_dense");
        let score_logits = pipeline("chain_score_logits");
        let top_k = pipeline("chain_reduce_topk");
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
            aggregate,
            dense,
            norm,
            score_dense,
            score_logits,
            top_k,
            limits,
            maximum_resident_bytes,
            receipt,
        })
    }

    pub fn adapter_receipt(&self) -> &AdapterReceipt {
        &self.receipt
    }

    pub fn upload<'a>(
        &'a self,
        input: ResidentChainInput<'_>,
    ) -> Result<ResidentModelChain<'a>, GpuError> {
        let started = Instant::now();
        let shape = input.validate()?;
        if shape.resident_bytes > self.maximum_resident_bytes {
            return Err(GpuError::Residency(format!(
                "{} bytes exceed the configured {} byte resident-chain budget",
                shape.resident_bytes, self.maximum_resident_bytes
            )));
        }
        self.validate_bindings(&input, shape)?;
        let offsets = input
            .offsets
            .iter()
            .map(|&offset| offset as u32)
            .collect::<Vec<_>>();
        let node_ids = (0..shape.nodes).collect::<Vec<_>>();
        let node_dispatch = self.dispatch_2d(shape.nodes)?;
        let dense_dispatch = self.dispatch_dense(shape.nodes, shape.dim)?;
        let score_dense_dispatch = self.dispatch_dense(shape.nodes, shape.score_dim)?;
        let offsets = storage(&self.device, "chain-offsets", &offsets, false);
        let sources = storage(&self.device, "chain-sources", input.sources, false);
        let relation_ids = storage(
            &self.device,
            "chain-relation-ids",
            input.relation_ids,
            false,
        );
        let initial_hidden = storage(
            &self.device,
            "chain-initial-hidden",
            input.initial_hidden,
            false,
        );
        let hidden_a = empty_storage(
            &self.device,
            "chain-hidden-a",
            bytes(input.initial_hidden),
            true,
        );
        let hidden_b = empty_storage(
            &self.device,
            "chain-hidden-b",
            bytes(input.initial_hidden),
            true,
        );
        let boundary = storage(&self.device, "chain-boundary", input.boundary, false);
        let relations = storage(
            &self.device,
            "chain-layer-relations",
            input.layer_relations,
            false,
        );
        let old_weights = storage(&self.device, "chain-old-weights", input.old_weights, false);
        let aggregate_weights = storage(
            &self.device,
            "chain-aggregate-weights",
            input.aggregate_weights,
            false,
        );
        let update_bias = storage(&self.device, "chain-update-bias", input.update_bias, false);
        let norm_scale = storage(&self.device, "chain-norm-scale", input.norm_scale, false);
        let norm_bias = storage(&self.device, "chain-norm-bias", input.norm_bias, false);
        let aggregate_output = empty_storage(
            &self.device,
            "chain-aggregate-output",
            bytes(input.initial_hidden),
            false,
        );
        let update_output = empty_storage(
            &self.device,
            "chain-update-output",
            bytes(input.initial_hidden),
            false,
        );
        let mut layers = Vec::with_capacity(shape.layers as usize);
        for layer in 0..shape.layers {
            let params = storage(
                &self.device,
                "chain-layer-params",
                &[ChainParams::new(
                    shape,
                    layer,
                    node_dispatch[0],
                    dense_dispatch[1],
                )],
                false,
            );
            let (old, next) = if layer == 0 {
                (&initial_hidden, &hidden_a)
            } else if layer % 2 == 1 {
                (&hidden_a, &hidden_b)
            } else {
                (&hidden_b, &hidden_a)
            };
            layers.push(LayerDispatch {
                aggregate: bind_group(
                    &self.device,
                    &self.aggregate,
                    "chain-distmult",
                    &[
                        &offsets,
                        &sources,
                        &relation_ids,
                        old,
                        &relations,
                        &boundary,
                        &aggregate_output,
                        &params,
                    ],
                ),
                dense: bind_group(
                    &self.device,
                    &self.dense,
                    "chain-dense-update",
                    &[
                        old,
                        &aggregate_output,
                        &old_weights,
                        &aggregate_weights,
                        &update_bias,
                        &update_output,
                        &params,
                    ],
                ),
                norm: bind_group(
                    &self.device,
                    &self.norm,
                    "chain-norm-residual",
                    &[old, &update_output, &norm_scale, &norm_bias, next, &params],
                ),
            });
        }
        let final_hidden = if shape.layers % 2 == 1 {
            hidden_a
        } else {
            hidden_b
        };
        self.finish_upload(
            started,
            input,
            shape,
            layers,
            final_hidden,
            node_ids,
            node_dispatch,
            dense_dispatch,
            score_dense_dispatch,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn finish_upload<'a>(
        &'a self,
        started: Instant,
        input: ResidentChainInput<'_>,
        shape: ValidatedResidentChain,
        layers: Vec<LayerDispatch>,
        final_hidden: wgpu::Buffer,
        node_ids: Vec<u32>,
        node_dispatch: [u32; 2],
        dense_dispatch: [u32; 3],
        score_dense_dispatch: [u32; 3],
    ) -> Result<ResidentModelChain<'a>, GpuError> {
        let entity = storage(
            &self.device,
            "chain-score-entity",
            input.scorer_entity.unwrap_or(&[0.0]),
            false,
        );
        let entity_weight = storage(
            &self.device,
            "chain-score-entity-weight",
            input.scorer_entity_weight.unwrap_or(&[0.0]),
            false,
        );
        let hidden_weight = storage(
            &self.device,
            "chain-score-hidden-weight",
            input.scorer_hidden_weight,
            false,
        );
        let query_term = storage(
            &self.device,
            "chain-score-query-term",
            input.scorer_query_term,
            false,
        );
        let score_bias = storage(&self.device, "chain-score-bias", input.scorer_bias, false);
        let output_weight = storage(
            &self.device,
            "chain-score-output-weight",
            input.scorer_output_weight,
            false,
        );
        let output_bias = storage(
            &self.device,
            "chain-score-output-bias",
            &[input.scorer_output_bias],
            false,
        );
        let score_activation_bytes =
            u64::from(shape.nodes) * u64::from(shape.score_dim) * size_of::<f32>() as u64;
        let score_activation = empty_storage(
            &self.device,
            "chain-score-activation",
            score_activation_bytes,
            false,
        );
        let logits = empty_storage(
            &self.device,
            "chain-logits",
            u64::from(shape.nodes) * 4,
            true,
        );
        let score_params = storage(
            &self.device,
            "chain-score-params",
            &[ChainParams::new(
                shape,
                0,
                node_dispatch[0],
                score_dense_dispatch[1],
            )],
            false,
        );
        let score_dense = bind_group(
            &self.device,
            &self.score_dense,
            "chain-score-dense",
            &[
                &final_hidden,
                &entity,
                &hidden_weight,
                &entity_weight,
                &query_term,
                &score_bias,
                &score_activation,
                &score_params,
            ],
        );
        let score_logits = bind_group(
            &self.device,
            &self.score_logits,
            "chain-score-logits",
            &[
                &score_activation,
                &output_weight,
                &output_bias,
                &logits,
                &score_params,
            ],
        );
        let node_ids = storage(&self.device, "chain-node-ids", &node_ids, false);
        let candidate_capacity = u64::from(shape.nodes.div_ceil(256)) * u64::from(shape.top_k);
        let candidate_bytes = candidate_capacity.max(1) * 4;
        let candidate_scores_a = empty_storage(
            &self.device,
            "chain-candidate-scores-a",
            candidate_bytes,
            true,
        );
        let candidate_ids_a =
            empty_storage(&self.device, "chain-candidate-ids-a", candidate_bytes, true);
        let candidate_scores_b = empty_storage(
            &self.device,
            "chain-candidate-scores-b",
            candidate_bytes,
            true,
        );
        let candidate_ids_b =
            empty_storage(&self.device, "chain-candidate-ids-b", candidate_bytes, true);
        let mut reductions = Vec::new();
        let mut items = shape.nodes;
        let mut output_a = true;
        let mut first = true;
        loop {
            let blocks = items.div_ceil(256);
            let dispatch = self.dispatch_2d(blocks)?;
            let params = storage(
                &self.device,
                "chain-top-k-params",
                &[TopKParams {
                    items,
                    top_k: shape.top_k,
                    dispatch_width: dispatch[0],
                    pad: 0,
                }],
                false,
            );
            let (input_scores, input_ids) = if first {
                (&logits, &node_ids)
            } else if output_a {
                (&candidate_scores_b, &candidate_ids_b)
            } else {
                (&candidate_scores_a, &candidate_ids_a)
            };
            let (output_scores, output_ids) = if output_a {
                (&candidate_scores_a, &candidate_ids_a)
            } else {
                (&candidate_scores_b, &candidate_ids_b)
            };
            reductions.push(TopKDispatch {
                bind_group: bind_group(
                    &self.device,
                    &self.top_k,
                    "chain-reduce-top-k",
                    &[input_scores, input_ids, output_scores, output_ids, &params],
                ),
                dispatch,
            });
            items = blocks * shape.top_k;
            first = false;
            if items == shape.top_k {
                break;
            }
            output_a = !output_a;
        }
        let compact_readback = readback(
            &self.device,
            "chain-compact-readback",
            shape.compact_readback_bytes,
        );
        Ok(ResidentModelChain {
            runtime: self,
            layers,
            score_dense,
            score_logits,
            top_k: reductions,
            final_hidden,
            logits,
            candidate_scores_a,
            candidate_ids_a,
            candidate_scores_b,
            candidate_ids_b,
            compact_readback,
            shape,
            dense_dispatch,
            node_dispatch,
            score_dense_dispatch,
            final_candidates_in_a: output_a,
            prepare_micros: micros(started.elapsed()),
        })
    }

    fn validate_bindings(
        &self,
        input: &ResidentChainInput<'_>,
        shape: ValidatedResidentChain,
    ) -> Result<(), GpuError> {
        let limit = self
            .limits
            .max_buffer_size
            .min(self.limits.max_storage_buffer_binding_size);
        let candidate_bytes = u64::from(shape.nodes.div_ceil(256)) * u64::from(shape.top_k) * 4;
        let sections = [
            bytes(input.initial_hidden),
            bytes(input.layer_relations),
            bytes(input.old_weights),
            bytes(input.aggregate_weights),
            bytes(input.scorer_hidden_weight),
            input.scorer_entity.map(bytes).unwrap_or(4),
            input.scorer_entity_weight.map(bytes).unwrap_or(4),
            u64::from(shape.nodes) * u64::from(shape.score_dim) * 4,
            candidate_bytes,
        ];
        if let Some(size) = sections.into_iter().find(|size| *size > limit) {
            return Err(GpuError::Residency(format!(
                "{size} byte chain buffer exceeds adapter binding limit {limit}"
            )));
        }
        Ok(())
    }

    fn dispatch_2d(&self, workgroups: u32) -> Result<[u32; 2], GpuError> {
        let limit = self.limits.max_compute_workgroups_per_dimension;
        let x = workgroups.min(limit).max(1);
        let y = workgroups.div_ceil(x).max(1);
        if y > limit {
            return Err(GpuError::Residency(format!(
                "{workgroups} chain workgroups exceed portable 2D dispatch"
            )));
        }
        Ok([x, y])
    }

    fn dispatch_dense(&self, nodes: u32, outputs: u32) -> Result<[u32; 3], GpuError> {
        let limit = self.limits.max_compute_workgroups_per_dimension;
        let x = outputs.div_ceil(16);
        let node_tiles = nodes.div_ceil(16);
        let y = node_tiles.min(limit).max(1);
        let z = node_tiles.div_ceil(y).max(1);
        if x > limit || z > limit {
            return Err(GpuError::Residency(
                "dense chain extent exceeds portable 3D dispatch".to_owned(),
            ));
        }
        Ok([x, y, z])
    }
}

impl ResidentModelChain<'_> {
    pub fn shape(&self) -> ValidatedResidentChain {
        self.shape
    }

    pub fn execute_top_k(&self) -> Result<CompactChainOutput, GpuError> {
        let dispatch = self.dispatch_and_wait()?;
        let (top_k, readback) = self.read_top_k()?;
        Ok(CompactChainOutput {
            top_k,
            timing: ChainTiming {
                prepare_micros: self.prepare_micros,
                dispatch_micros: micros(dispatch),
                readback_micros: micros(readback),
                resident_bytes: self.shape.resident_bytes,
                readback_bytes: self.shape.compact_readback_bytes,
            },
        })
    }

    pub fn execute_trace(&self) -> Result<ChainTraceOutput, GpuError> {
        let dispatch = self.dispatch_and_wait()?;
        let (hidden, logits, readback) = self.read_trace()?;
        Ok(ChainTraceOutput {
            hidden,
            logits,
            timing: ChainTiming {
                prepare_micros: self.prepare_micros,
                dispatch_micros: micros(dispatch),
                readback_micros: micros(readback),
                resident_bytes: self.shape.resident_bytes,
                readback_bytes: self.shape.trace_readback_bytes,
            },
        })
    }

    pub fn dispatch_and_wait(&self) -> Result<Duration, GpuError> {
        let started = Instant::now();
        let mut encoder =
            self.runtime
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("gfm-resident-chain-dispatch"),
                });
        for layer in &self.layers {
            compute_2d(
                &mut encoder,
                &self.runtime.aggregate,
                &layer.aggregate,
                self.node_dispatch,
                "chain-distmult",
            );
            compute_3d(
                &mut encoder,
                &self.runtime.dense,
                &layer.dense,
                self.dense_dispatch,
                "chain-dense-update",
            );
            compute_2d(
                &mut encoder,
                &self.runtime.norm,
                &layer.norm,
                self.node_dispatch,
                "chain-norm-residual",
            );
        }
        compute_3d(
            &mut encoder,
            &self.runtime.score_dense,
            &self.score_dense,
            self.score_dense_dispatch,
            "chain-score-dense",
        );
        compute_2d(
            &mut encoder,
            &self.runtime.score_logits,
            &self.score_logits,
            self.node_dispatch,
            "chain-score-logits",
        );
        for reduction in &self.top_k {
            compute_2d(
                &mut encoder,
                &self.runtime.top_k,
                &reduction.bind_group,
                reduction.dispatch,
                "chain-reduce-top-k",
            );
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

    pub fn read_top_k(&self) -> Result<(Vec<TopKRecord>, Duration), GpuError> {
        let (scores, ids) = if self.final_candidates_in_a {
            (&self.candidate_scores_a, &self.candidate_ids_a)
        } else {
            (&self.candidate_scores_b, &self.candidate_ids_b)
        };
        let section = u64::from(self.shape.top_k) * 4;
        let (bytes, elapsed) = copy_and_map(
            &self.runtime.device,
            &self.runtime.queue,
            &[(scores, 0, section), (ids, 0, section)],
            &self.compact_readback,
            self.shape.compact_readback_bytes,
        )?;
        let scores = read_pods::<f32>(&bytes[..section as usize])?;
        let ids = read_pods::<u32>(&bytes[section as usize..])?;
        Ok((
            scores
                .into_iter()
                .zip(ids)
                .map(|(score, node)| TopKRecord { score, node })
                .collect(),
            elapsed,
        ))
    }

    pub fn read_trace(&self) -> Result<(Vec<f32>, Vec<f32>, Duration), GpuError> {
        let transient_bytes = self
            .shape
            .resident_bytes
            .checked_add(self.shape.trace_readback_bytes)
            .ok_or_else(|| GpuError::Residency("trace byte accounting overflow".to_owned()))?;
        if transient_bytes > self.runtime.maximum_resident_bytes {
            return Err(GpuError::Residency(format!(
                "explicit trace requires {transient_bytes} bytes beyond the configured chain budget"
            )));
        }
        let trace_readback = readback(
            &self.runtime.device,
            "chain-trace-readback",
            self.shape.trace_readback_bytes,
        );
        let hidden_bytes = u64::from(self.shape.nodes) * u64::from(self.shape.dim) * 4;
        let logit_bytes = u64::from(self.shape.nodes) * 4;
        let (bytes, elapsed) = copy_and_map(
            &self.runtime.device,
            &self.runtime.queue,
            &[
                (&self.final_hidden, 0, hidden_bytes),
                (&self.logits, 0, logit_bytes),
            ],
            &trace_readback,
            self.shape.trace_readback_bytes,
        )?;
        Ok((
            read_pods(&bytes[..hidden_bytes as usize])?,
            read_pods(&bytes[hidden_bytes as usize..])?,
            elapsed,
        ))
    }
}

impl ChainParams {
    fn new(
        shape: ValidatedResidentChain,
        layer: u32,
        dispatch_width: u32,
        dense_dispatch_height: u32,
    ) -> Self {
        Self {
            nodes: shape.nodes,
            edges: shape.edges,
            relations: shape.relations,
            dim: shape.dim,
            layer,
            dispatch_width,
            score_dim: shape.score_dim,
            entity_enabled: u32::from(shape.entity_enabled),
            dense_dispatch_height,
            pad: [0; 3],
        }
    }
}
