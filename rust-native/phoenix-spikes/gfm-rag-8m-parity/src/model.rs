use candle_core::{Device, Tensor};
use candle_nn::{LayerNorm, Module};

use crate::artifact::MappedIncomingCsr;
use crate::checkpoint::MappedCheckpoint;
use crate::constants::{EMBEDDING_DIM, HIDDEN_DIM, LAYER_COUNT};
use crate::graph::IncomingCsr;
use crate::kernel::{FastKernel, fast_distmult_sum, scalar_distmult_sum};
use crate::{GfmError, Result};

pub trait IncomingGraph {
    fn node_count(&self) -> usize;
    fn relation_count(&self) -> usize;
    fn dst_offsets(&self) -> &[u64];
    fn src_nodes(&self) -> &[u32];
    fn relation_ids(&self) -> &[u32];
}

impl IncomingGraph for IncomingCsr {
    fn node_count(&self) -> usize {
        self.node_count()
    }
    fn relation_count(&self) -> usize {
        self.relation_count()
    }
    fn dst_offsets(&self) -> &[u64] {
        self.dst_offsets()
    }
    fn src_nodes(&self) -> &[u32] {
        self.src_nodes()
    }
    fn relation_ids(&self) -> &[u32] {
        self.relation_ids()
    }
}

impl IncomingGraph for MappedIncomingCsr {
    fn node_count(&self) -> usize {
        self.node_count()
    }
    fn relation_count(&self) -> usize {
        self.relation_count()
    }
    fn dst_offsets(&self) -> &[u64] {
        self.dst_offsets()
    }
    fn src_nodes(&self) -> &[u32] {
        self.src_nodes()
    }
    fn relation_ids(&self) -> &[u32] {
        self.relation_ids()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AggregationBackend {
    Scalar,
    Fast,
}

#[derive(Debug)]
pub struct ForwardTrace {
    pub question_projection: Tensor,
    pub relation_projection: Tensor,
    pub boundary: Tensor,
    pub layer0_relation_projection: Tensor,
    pub layer0_aggregate: Tensor,
    pub layer0_hidden: Tensor,
    pub six_layer_hidden: Tensor,
    pub logits: Tensor,
    pub fast_kernel: Option<FastKernel>,
}

/// Minimal production output. Unlike [`ForwardTrace`], this retains no
/// intermediate parity tensors after the inference call returns.
#[derive(Debug)]
pub struct InferenceResult {
    pub logits: Tensor,
    pub fast_kernel: Option<FastKernel>,
}

enum ModelOutput {
    Trace(ForwardTrace),
    Inference(InferenceResult),
}

struct LinearWeights {
    weight: Tensor,
    bias: Tensor,
}

impl LinearWeights {
    fn load(checkpoint: &MappedCheckpoint, prefix: &str, device: &Device) -> Result<Self> {
        Ok(Self {
            weight: checkpoint.tensor(&format!("{prefix}.weight"), device)?,
            bias: checkpoint.tensor(&format!("{prefix}.bias"), device)?,
        })
    }

    fn forward_2d(&self, input: &Tensor) -> Result<Tensor> {
        Ok(input.matmul(&self.weight.t()?)?.broadcast_add(&self.bias)?)
    }
}

struct RelationalLayer {
    relation_first: LinearWeights,
    relation_second: LinearWeights,
    update: LinearWeights,
    norm: LayerNorm,
}

pub struct GfmModel {
    question: LinearWeights,
    relation: LinearWeights,
    layers: Vec<RelationalLayer>,
    scorer_first: LinearWeights,
    scorer_second: LinearWeights,
    tile_nodes: usize,
    device: Device,
}

impl GfmModel {
    pub fn load(checkpoint: &MappedCheckpoint, device: &Device, tile_nodes: usize) -> Result<Self> {
        if tile_nodes == 0 {
            return Err(GfmError::Shape("tile_nodes must be nonzero".into()));
        }
        let mut layers = Vec::with_capacity(LAYER_COUNT);
        for layer in 0..LAYER_COUNT {
            let prefix = format!("entity_model.layers.{layer}");
            layers.push(RelationalLayer {
                relation_first: LinearWeights::load(
                    checkpoint,
                    &format!("{prefix}.relation_projection.0"),
                    device,
                )?,
                relation_second: LinearWeights::load(
                    checkpoint,
                    &format!("{prefix}.relation_projection.2"),
                    device,
                )?,
                update: LinearWeights::load(checkpoint, &format!("{prefix}.linear"), device)?,
                norm: LayerNorm::new(
                    checkpoint.tensor(&format!("{prefix}.layer_norm.weight"), device)?,
                    checkpoint.tensor(&format!("{prefix}.layer_norm.bias"), device)?,
                    1e-5,
                ),
            });
        }
        Ok(Self {
            question: LinearWeights::load(checkpoint, "question_mlp", device)?,
            relation: LinearWeights::load(checkpoint, "rel_mlp", device)?,
            layers,
            scorer_first: LinearWeights::load(checkpoint, "entity_model.mlp.0", device)?,
            scorer_second: LinearWeights::load(checkpoint, "entity_model.mlp.2", device)?,
            tile_nodes,
            device: device.clone(),
        })
    }

    pub fn forward<G: IncomingGraph>(
        &self,
        graph: &G,
        question_raw: &Tensor,
        relations_raw: &Tensor,
        start_mask: &[f32],
        entity_frequency: &[f32],
        backend: AggregationBackend,
    ) -> Result<ForwardTrace> {
        match self.run(
            graph,
            question_raw,
            relations_raw,
            start_mask,
            entity_frequency,
            backend,
            true,
        )? {
            ModelOutput::Trace(trace) => Ok(trace),
            ModelOutput::Inference(_) => unreachable!("trace capture was requested"),
        }
    }

    pub fn infer_logits<G: IncomingGraph>(
        &self,
        graph: &G,
        question_raw: &Tensor,
        relations_raw: &Tensor,
        start_mask: &[f32],
        entity_frequency: &[f32],
        backend: AggregationBackend,
    ) -> Result<InferenceResult> {
        match self.run(
            graph,
            question_raw,
            relations_raw,
            start_mask,
            entity_frequency,
            backend,
            false,
        )? {
            ModelOutput::Inference(result) => Ok(result),
            ModelOutput::Trace(_) => unreachable!("trace capture was disabled"),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn run<G: IncomingGraph>(
        &self,
        graph: &G,
        question_raw: &Tensor,
        relations_raw: &Tensor,
        start_mask: &[f32],
        entity_frequency: &[f32],
        backend: AggregationBackend,
        capture_trace: bool,
    ) -> Result<ModelOutput> {
        if question_raw.dims() != [EMBEDDING_DIM]
            || relations_raw.dims() != [graph.relation_count(), EMBEDDING_DIM]
            || start_mask.len() != graph.node_count()
            || entity_frequency.len() != graph.node_count()
        {
            return Err(GfmError::Shape("inference input shape mismatch".into()));
        }
        let question_projection = self
            .question
            .forward_2d(&question_raw.unsqueeze(0)?)?
            .squeeze(0)?;
        let relation_projection = self.relation.forward_2d(relations_raw)?;
        let start_weights: Vec<f32> = start_mask
            .iter()
            .zip(entity_frequency)
            .map(|(&mask, &frequency)| {
                if frequency > 0.0 {
                    mask / frequency
                } else {
                    0.0
                }
            })
            .collect();
        let weights = Tensor::from_vec(start_weights, (graph.node_count(), 1), &self.device)?;
        let boundary = weights.broadcast_mul(&question_projection.unsqueeze(0)?)?;
        let trace_boundary = capture_trace.then(|| boundary.clone());
        let boundary_values = boundary.flatten_all()?.to_vec1::<f32>()?;
        let mut hidden = boundary;
        let mut layer0_relation = None;
        let mut layer0_aggregate = None;
        let mut layer0_hidden = None;
        let mut selected_fast_kernel = None;

        for (index, layer) in self.layers.iter().enumerate() {
            let projected_relations = layer.relation_second.forward_2d(
                &layer
                    .relation_first
                    .forward_2d(&relation_projection)?
                    .relu()?,
            )?;
            let input = hidden.flatten_all()?.to_vec1::<f32>()?;
            let relations = projected_relations.flatten_all()?.to_vec1::<f32>()?;
            let aggregated = match backend {
                AggregationBackend::Scalar => scalar_distmult_sum(
                    graph.dst_offsets(),
                    graph.src_nodes(),
                    graph.relation_ids(),
                    &input,
                    &relations,
                    &boundary_values,
                    HIDDEN_DIM,
                )?,
                AggregationBackend::Fast => {
                    let (values, kernel) = fast_distmult_sum(
                        graph.dst_offsets(),
                        graph.src_nodes(),
                        graph.relation_ids(),
                        &input,
                        &relations,
                        &boundary_values,
                        HIDDEN_DIM,
                    )?;
                    selected_fast_kernel = Some(kernel);
                    values
                }
            };
            drop(input);
            drop(relations);
            let aggregated =
                Tensor::from_vec(aggregated, (graph.node_count(), HIDDEN_DIM), &self.device)?;
            let next_hidden = self.tiled_update(layer, &hidden, &aggregated)?;
            if capture_trace && index == 0 {
                layer0_relation = Some(projected_relations.clone());
                layer0_aggregate = Some(aggregated.clone());
                layer0_hidden = Some(next_hidden.clone());
            }
            hidden = next_hidden;
        }
        let logits = self.tiled_score(&hidden, &question_projection)?;
        if capture_trace {
            Ok(ModelOutput::Trace(ForwardTrace {
                question_projection,
                relation_projection,
                boundary: trace_boundary.expect("trace boundary was captured"),
                layer0_relation_projection: layer0_relation
                    .expect("six-layer model always captures layer zero"),
                layer0_aggregate: layer0_aggregate
                    .expect("six-layer model always captures layer zero"),
                layer0_hidden: layer0_hidden.expect("six-layer model always captures layer zero"),
                six_layer_hidden: hidden,
                logits,
                fast_kernel: selected_fast_kernel,
            }))
        } else {
            Ok(ModelOutput::Inference(InferenceResult {
                logits,
                fast_kernel: selected_fast_kernel,
            }))
        }
    }

    /// Splits the checkpoint's [old | aggregate] weight matrix by columns and
    /// evaluates node tiles. No N x 1024 activation is ever allocated.
    fn tiled_update(
        &self,
        layer: &RelationalLayer,
        old: &Tensor,
        aggregate: &Tensor,
    ) -> Result<Tensor> {
        let nodes = old.dim(0)?;
        let old_weight = layer.update.weight.narrow(1, 0, HIDDEN_DIM)?.t()?;
        let aggregate_weight = layer.update.weight.narrow(1, HIDDEN_DIM, HIDDEN_DIM)?.t()?;
        let mut tiles = Vec::with_capacity(nodes.div_ceil(self.tile_nodes));
        for start in (0..nodes).step_by(self.tile_nodes) {
            let length = self.tile_nodes.min(nodes - start);
            let old_tile = old.narrow(0, start, length)?;
            let aggregate_tile = aggregate.narrow(0, start, length)?;
            let update = old_tile
                .matmul(&old_weight)?
                .add(&aggregate_tile.matmul(&aggregate_weight)?)?
                .broadcast_add(&layer.update.bias)?;
            let update = layer.norm.forward(&update)?.relu()?.add(&old_tile)?;
            tiles.push(update);
        }
        Ok(Tensor::cat(&tiles, 0)?)
    }

    /// Applies the scorer's first 1024-wide input without materializing
    /// [node_hidden | repeated_query].
    fn tiled_score(&self, hidden: &Tensor, question: &Tensor) -> Result<Tensor> {
        let nodes = hidden.dim(0)?;
        let hidden_weight = self.scorer_first.weight.narrow(1, 0, HIDDEN_DIM)?.t()?;
        let query_weight = self
            .scorer_first
            .weight
            .narrow(1, HIDDEN_DIM, HIDDEN_DIM)?
            .t()?;
        let query_term = question.unsqueeze(0)?.matmul(&query_weight)?;
        let mut tiles = Vec::with_capacity(nodes.div_ceil(self.tile_nodes));
        for start in (0..nodes).step_by(self.tile_nodes) {
            let length = self.tile_nodes.min(nodes - start);
            let first = hidden
                .narrow(0, start, length)?
                .matmul(&hidden_weight)?
                .broadcast_add(&query_term)?
                .broadcast_add(&self.scorer_first.bias)?
                .relu()?;
            tiles.push(self.scorer_second.forward_2d(&first)?);
        }
        Ok(Tensor::cat(&tiles, 0)?.squeeze(1)?)
    }
}
