use std::mem::size_of;

use bytemuck::{Pod, Zeroable};

use crate::GpuError;

pub const MAX_TOP_K: usize = 32;

#[derive(Clone, Copy)]
pub struct ResidentChainInput<'a> {
    pub offsets: &'a [u64],
    pub sources: &'a [u32],
    pub relation_ids: &'a [u32],
    pub initial_hidden: &'a [f32],
    pub boundary: &'a [f32],
    pub layer_relations: &'a [f32],
    pub old_weights: &'a [f32],
    pub aggregate_weights: &'a [f32],
    pub update_bias: &'a [f32],
    pub norm_scale: &'a [f32],
    pub norm_bias: &'a [f32],
    pub scorer_hidden_weight: &'a [f32],
    pub scorer_entity: Option<&'a [f32]>,
    pub scorer_entity_weight: Option<&'a [f32]>,
    pub scorer_query_term: &'a [f32],
    pub scorer_bias: &'a [f32],
    pub scorer_output_weight: &'a [f32],
    pub scorer_output_bias: f32,
    pub dim: usize,
    pub layers: usize,
    pub score_dim: usize,
    pub top_k: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedResidentChain {
    pub nodes: u32,
    pub edges: u32,
    pub relations: u32,
    pub dim: u32,
    pub layers: u32,
    pub score_dim: u32,
    pub top_k: u32,
    pub entity_enabled: bool,
    pub resident_bytes: u64,
    pub compact_readback_bytes: u64,
    pub trace_readback_bytes: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Pod, Zeroable)]
pub struct TopKRecord {
    pub score: f32,
    pub node: u32,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ChainTiming {
    pub prepare_micros: u64,
    pub dispatch_micros: u64,
    pub readback_micros: u64,
    pub resident_bytes: u64,
    pub readback_bytes: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CompactChainOutput {
    pub top_k: Vec<TopKRecord>,
    pub timing: ChainTiming,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ChainTraceOutput {
    pub hidden: Vec<f32>,
    pub logits: Vec<f32>,
    pub timing: ChainTiming,
}

impl ResidentChainInput<'_> {
    pub fn validate(&self) -> Result<ValidatedResidentChain, GpuError> {
        if self.dim == 0 || self.layers == 0 || self.score_dim == 0 {
            return Err(GpuError::Shape(
                "resident chain dimensions and layer count must be nonzero".to_owned(),
            ));
        }
        if self.top_k == 0 || self.top_k > MAX_TOP_K {
            return Err(GpuError::Shape(format!("top_k must be in 1..={MAX_TOP_K}")));
        }
        if self.offsets.len() < 2 || self.offsets[0] != 0 {
            return Err(GpuError::Shape(
                "resident chain CSR must contain at least one node and start at zero".to_owned(),
            ));
        }
        let nodes = self.offsets.len() - 1;
        let edges = self.sources.len();
        if self.relation_ids.len() != edges
            || self.offsets[nodes] != edges as u64
            || self.offsets.windows(2).any(|pair| pair[0] > pair[1])
        {
            return Err(GpuError::Shape(
                "resident chain CSR sections disagree".to_owned(),
            ));
        }
        let node_values = extent(nodes, self.dim, "node tensor")?;
        if self.initial_hidden.len() != node_values || self.boundary.len() != node_values {
            return Err(GpuError::Shape(format!(
                "initial hidden and boundary must both contain {node_values} values"
            )));
        }
        if self.layer_relations.is_empty()
            || !self
                .layer_relations
                .len()
                .is_multiple_of(self.layers * self.dim)
        {
            return Err(GpuError::Shape(
                "layer relation tensor must be L x R x D".to_owned(),
            ));
        }
        let relations = self.layer_relations.len() / (self.layers * self.dim);
        if self.sources.iter().any(|&node| node as usize >= nodes)
            || self
                .relation_ids
                .iter()
                .any(|&relation| relation as usize >= relations)
        {
            return Err(GpuError::Shape(
                "CSR source or relation identity exceeds chain extent".to_owned(),
            ));
        }
        let layer_matrix = extent(self.layers, self.dim * self.dim, "layer matrix")?;
        let layer_vector = extent(self.layers, self.dim, "layer vector")?;
        check_len("old weights", self.old_weights, layer_matrix)?;
        check_len("aggregate weights", self.aggregate_weights, layer_matrix)?;
        check_len("update bias", self.update_bias, layer_vector)?;
        check_len("norm scale", self.norm_scale, layer_vector)?;
        check_len("norm bias", self.norm_bias, layer_vector)?;
        let score_matrix = extent(self.score_dim, self.dim, "scorer matrix")?;
        check_len(
            "scorer hidden weights",
            self.scorer_hidden_weight,
            score_matrix,
        )?;
        check_len("scorer query term", self.scorer_query_term, self.score_dim)?;
        check_len("scorer bias", self.scorer_bias, self.score_dim)?;
        check_len(
            "scorer output weights",
            self.scorer_output_weight,
            self.score_dim,
        )?;
        let entity_enabled = match (self.scorer_entity, self.scorer_entity_weight) {
            (None, None) => false,
            (Some(entity), Some(weight)) => {
                check_len("scorer entity", entity, node_values)?;
                check_len("scorer entity weights", weight, score_matrix)?;
                true
            }
            _ => {
                return Err(GpuError::Shape(
                    "scorer entity state and weights must be supplied together".to_owned(),
                ));
            }
        };
        if self
            .offsets
            .iter()
            .any(|&offset| offset > u64::from(u32::MAX))
        {
            return Err(GpuError::Shape(
                "CSR offset exceeds u32 GPU extent".to_owned(),
            ));
        }
        let nodes = as_u32(nodes, "nodes")?;
        let edges = as_u32(edges, "edges")?;
        let relations = as_u32(relations, "relations")?;
        let dim = as_u32(self.dim, "dimension")?;
        let layers = as_u32(self.layers, "layers")?;
        let score_dim = as_u32(self.score_dim, "score dimension")?;
        let top_k = as_u32(self.top_k.min(nodes as usize), "top_k")?;
        let candidate_capacity = nodes.div_ceil(256) as usize * top_k as usize;
        let persistent_values = self
            .float_value_count(entity_enabled, candidate_capacity)?
            .checked_mul(size_of::<f32>())
            .ok_or_else(|| GpuError::Shape("resident byte extent overflow".to_owned()))?;
        let integer_values = self
            .offsets
            .len()
            .checked_add(edges as usize * 2)
            .and_then(|value| value.checked_add(nodes as usize))
            .and_then(|value| value.checked_add(candidate_capacity * 2))
            .ok_or_else(|| GpuError::Shape("resident integer extent overflow".to_owned()))?;
        let compact_readback_bytes = u64::from(top_k) * size_of::<TopKRecord>() as u64;
        let resident_bytes = u64::try_from(
            persistent_values
                .checked_add(integer_values * size_of::<u32>())
                .and_then(|value| value.checked_add(compact_readback_bytes as usize))
                .and_then(|value| value.checked_add(512))
                .ok_or_else(|| GpuError::Shape("resident byte extent overflow".to_owned()))?,
        )
        .map_err(|_| GpuError::Shape("resident byte extent exceeds u64".to_owned()))?;
        Ok(ValidatedResidentChain {
            nodes,
            edges,
            relations,
            dim,
            layers,
            score_dim,
            top_k,
            entity_enabled,
            resident_bytes,
            compact_readback_bytes,
            trace_readback_bytes: u64::from(nodes) * u64::from(dim + 1) * 4,
        })
    }

    fn float_value_count(
        &self,
        entity_enabled: bool,
        candidate_capacity: usize,
    ) -> Result<usize, GpuError> {
        let slices = [
            self.initial_hidden.len(),
            self.boundary.len(),
            self.layer_relations.len(),
            self.old_weights.len(),
            self.aggregate_weights.len(),
            self.update_bias.len(),
            self.norm_scale.len(),
            self.norm_bias.len(),
            self.scorer_hidden_weight.len(),
            self.scorer_query_term.len(),
            self.scorer_bias.len(),
            self.scorer_output_weight.len(),
        ];
        let mut total = slices.into_iter().try_fold(0usize, |total, value| {
            total.checked_add(value).ok_or_else(|| {
                GpuError::Shape("resident floating-point extent overflow".to_owned())
            })
        })?;
        if entity_enabled {
            total = total
                .checked_add(self.scorer_entity.unwrap().len())
                .and_then(|value| value.checked_add(self.scorer_entity_weight.unwrap().len()))
                .ok_or_else(|| GpuError::Shape("entity scorer extent overflow".to_owned()))?;
        }
        let node_values = self.initial_hidden.len();
        let node_workspace = node_values
            .checked_mul(4)
            .ok_or_else(|| GpuError::Shape("chain node workspace extent overflow".to_owned()))?;
        total
            .checked_add(node_workspace)
            .and_then(|value| value.checked_add(self.offsets.len() - 1))
            .and_then(|value| value.checked_add(candidate_capacity * 2))
            .and_then(|value| value.checked_add(self.score_dim * (self.offsets.len() - 1)))
            .ok_or_else(|| GpuError::Shape("chain workspace extent overflow".to_owned()))
    }
}

fn extent(left: usize, right: usize, name: &str) -> Result<usize, GpuError> {
    left.checked_mul(right)
        .ok_or_else(|| GpuError::Shape(format!("{name} extent overflow")))
}

fn check_len(name: &str, values: &[f32], expected: usize) -> Result<(), GpuError> {
    if values.len() != expected {
        return Err(GpuError::Shape(format!(
            "{name} has {} values; expected {expected}",
            values.len()
        )));
    }
    Ok(())
}

fn as_u32(value: usize, name: &str) -> Result<u32, GpuError> {
    u32::try_from(value).map_err(|_| GpuError::Shape(format!("{name} exceeds u32 GPU extent")))
}
