use candle_core::{Device, Tensor};
use candle_nn::{LayerNorm, Module};

use crate::artifact::MappedIncomingCsr;
use crate::checkpoint::MappedCheckpoint;
use crate::constants::{FEATURE_DIM, HIDDEN_DIM, LAYER_COUNT};
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
    pub entity_projection: Tensor,
    pub start_boundary: Tensor,
    pub early_fused: Tensor,
    pub layer0_relation_projection: Tensor,
    pub layer0_aggregate: Tensor,
    pub layer0_hidden: Tensor,
    pub six_layer_hidden: Tensor,
    pub logits: Tensor,
    pub fast_kernel: Option<FastKernel>,
}

#[derive(Debug)]
pub struct InferenceResult {
    pub logits: Tensor,
    pub fast_kernel: Option<FastKernel>,
}

enum RunOutput {
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

pub struct GraphReasonerModel {
    question: LinearWeights,
    relation: LinearWeights,
    entity: LinearWeights,
    early_first: LinearWeights,
    early_second: LinearWeights,
    layers: Vec<RelationalLayer>,
    predict_first: LinearWeights,
    predict_second: LinearWeights,
    tile_nodes: usize,
    device: Device,
}

impl GraphReasonerModel {
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
            entity: LinearWeights::load(checkpoint, "ent_mlp", device)?,
            early_first: LinearWeights::load(checkpoint, "early_fuse_mlp.0", device)?,
            early_second: LinearWeights::load(checkpoint, "early_fuse_mlp.2", device)?,
            layers,
            predict_first: LinearWeights::load(checkpoint, "predict_mlp.0", device)?,
            predict_second: LinearWeights::load(checkpoint, "predict_mlp.2", device)?,
            tile_nodes,
            device: device.clone(),
        })
    }

    pub fn forward<G: IncomingGraph>(
        &self,
        graph: &G,
        question_raw: &Tensor,
        relations_raw: &Tensor,
        entities_raw: &Tensor,
        start_mask: &[f32],
        backend: AggregationBackend,
    ) -> Result<ForwardTrace> {
        match self.run(
            graph,
            question_raw,
            relations_raw,
            entities_raw,
            start_mask,
            backend,
            true,
        )? {
            RunOutput::Trace(trace) => Ok(trace),
            RunOutput::Inference(_) => unreachable!("trace run returned inference output"),
        }
    }

    pub fn infer_logits<G: IncomingGraph>(
        &self,
        graph: &G,
        question_raw: &Tensor,
        relations_raw: &Tensor,
        entities_raw: &Tensor,
        start_mask: &[f32],
        backend: AggregationBackend,
    ) -> Result<InferenceResult> {
        match self.run(
            graph,
            question_raw,
            relations_raw,
            entities_raw,
            start_mask,
            backend,
            false,
        )? {
            RunOutput::Inference(output) => Ok(output),
            RunOutput::Trace(_) => unreachable!("inference run returned trace output"),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn run<G: IncomingGraph>(
        &self,
        graph: &G,
        question_raw: &Tensor,
        relations_raw: &Tensor,
        entities_raw: &Tensor,
        start_mask: &[f32],
        backend: AggregationBackend,
        capture_trace: bool,
    ) -> Result<RunOutput> {
        if question_raw.dims() != [FEATURE_DIM]
            || relations_raw.dims() != [graph.relation_count(), FEATURE_DIM]
            || entities_raw.dims() != [graph.node_count(), FEATURE_DIM]
            || start_mask.len() != graph.node_count()
        {
            return Err(GfmError::Shape("inference input shape mismatch".into()));
        }
        let question_projection = self
            .question
            .forward_2d(&question_raw.unsqueeze(0)?)?
            .squeeze(0)?;
        let relation_projection = self.relation.forward_2d(relations_raw)?;
        let entity_projection = self.tiled_linear(&self.entity, entities_raw)?;
        let weights = Tensor::from_vec(start_mask.to_vec(), (graph.node_count(), 1), &self.device)?;
        let start_boundary = weights.broadcast_mul(&question_projection.unsqueeze(0)?)?;
        let early_fused = self.tiled_early_fusion(&start_boundary, &entity_projection)?;
        let trace_start_boundary = capture_trace.then(|| start_boundary.clone());
        drop(start_boundary);
        let boundary_values = early_fused.flatten_all()?.to_vec1::<f32>()?;
        let trace_early_fused = capture_trace.then(|| early_fused.clone());
        let mut hidden = early_fused;
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
            if index == 0 && capture_trace {
                layer0_relation = Some(projected_relations.clone());
                layer0_aggregate = Some(aggregated.clone());
                layer0_hidden = Some(next_hidden.clone());
            }
            hidden = next_hidden;
        }
        let logits = self.tiled_predict(&hidden, &question_projection, &entity_projection)?;
        if capture_trace {
            Ok(RunOutput::Trace(ForwardTrace {
                question_projection,
                relation_projection,
                entity_projection,
                start_boundary: trace_start_boundary.unwrap(),
                early_fused: trace_early_fused.unwrap(),
                layer0_relation_projection: layer0_relation.unwrap(),
                layer0_aggregate: layer0_aggregate.unwrap(),
                layer0_hidden: layer0_hidden.unwrap(),
                six_layer_hidden: hidden,
                logits,
                fast_kernel: selected_fast_kernel,
            }))
        } else {
            Ok(RunOutput::Inference(InferenceResult {
                logits,
                fast_kernel: selected_fast_kernel,
            }))
        }
    }

    fn tiled_linear(&self, linear: &LinearWeights, input: &Tensor) -> Result<Tensor> {
        let nodes = input.dim(0)?;
        let mut tiles = Vec::with_capacity(nodes.div_ceil(self.tile_nodes));
        for start in (0..nodes).step_by(self.tile_nodes) {
            let length = self.tile_nodes.min(nodes - start);
            tiles.push(linear.forward_2d(&input.narrow(0, start, length)?)?);
        }
        Ok(Tensor::cat(&tiles, 0)?)
    }

    /// Splits the [boundary | entity] early-fusion weight by columns. No
    /// N x 2048 activation is materialized.
    fn tiled_early_fusion(&self, boundary: &Tensor, entity: &Tensor) -> Result<Tensor> {
        let nodes = boundary.dim(0)?;
        let boundary_weight = self.early_first.weight.narrow(1, 0, HIDDEN_DIM)?.t()?;
        let entity_weight = self
            .early_first
            .weight
            .narrow(1, HIDDEN_DIM, HIDDEN_DIM)?
            .t()?;
        let mut tiles = Vec::with_capacity(nodes.div_ceil(self.tile_nodes));
        for start in (0..nodes).step_by(self.tile_nodes) {
            let length = self.tile_nodes.min(nodes - start);
            let first = boundary
                .narrow(0, start, length)?
                .matmul(&boundary_weight)?
                .add(&entity.narrow(0, start, length)?.matmul(&entity_weight)?)?
                .broadcast_add(&self.early_first.bias)?
                .relu()?;
            tiles.push(self.early_second.forward_2d(&first)?);
        }
        Ok(Tensor::cat(&tiles, 0)?)
    }

    /// Splits the layer's [old | aggregate] weight by columns.
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
            let update = old_tile
                .matmul(&old_weight)?
                .add(
                    &aggregate
                        .narrow(0, start, length)?
                        .matmul(&aggregate_weight)?,
                )?
                .broadcast_add(&layer.update.bias)?;
            tiles.push(layer.norm.forward(&update)?.relu()?.add(&old_tile)?);
        }
        Ok(Tensor::cat(&tiles, 0)?)
    }

    /// Evaluates [final_hidden | query | entity] in three projections. No
    /// N x 3072 scoring activation is materialized.
    fn tiled_predict(&self, hidden: &Tensor, query: &Tensor, entity: &Tensor) -> Result<Tensor> {
        let nodes = hidden.dim(0)?;
        let hidden_weight = self.predict_first.weight.narrow(1, 0, HIDDEN_DIM)?.t()?;
        let query_weight = self
            .predict_first
            .weight
            .narrow(1, HIDDEN_DIM, HIDDEN_DIM)?
            .t()?;
        let entity_weight = self
            .predict_first
            .weight
            .narrow(1, HIDDEN_DIM * 2, HIDDEN_DIM)?
            .t()?;
        let query_term = query.unsqueeze(0)?.matmul(&query_weight)?;
        let mut tiles = Vec::with_capacity(nodes.div_ceil(self.tile_nodes));
        for start in (0..nodes).step_by(self.tile_nodes) {
            let length = self.tile_nodes.min(nodes - start);
            let first = hidden
                .narrow(0, start, length)?
                .matmul(&hidden_weight)?
                .broadcast_add(&query_term)?
                .add(&entity.narrow(0, start, length)?.matmul(&entity_weight)?)?
                .broadcast_add(&self.predict_first.bias)?
                .relu()?;
            tiles.push(self.predict_second.forward_2d(&first)?);
        }
        Ok(Tensor::cat(&tiles, 0)?.squeeze(1)?)
    }
}
