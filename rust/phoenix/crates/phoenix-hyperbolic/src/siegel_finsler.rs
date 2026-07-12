use serde::{Deserialize, Serialize};

mod run;
pub use run::*;

pub const SIEGEL_FINSLER_PROJECTION_SPACE: &str = "siegel_finsler_v1";
pub const DEFAULT_SIEGEL_GENUS: u16 = 3;
pub const DEFAULT_SIEGEL_MAX_TARGETS: usize = 4_096;
pub const DEFAULT_SIEGEL_MAX_DIRECTED_EDGES: usize = 16_384;
pub const DEFAULT_SIEGEL_MAX_PAIRS: usize = 16_384;
pub const DEFAULT_SIEGEL_MAX_DISTANCE_EVALUATIONS: usize = 65_536;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelFinslerTimings {
    pub build_ms: u64,
    pub matrix_plan_ms: u64,
    pub distance_ms: u64,
    pub hierarchy_ms: u64,
    pub serialize_ms: u64,
}

impl SiegelFinslerTimings {
    #[inline]
    pub fn total_observed_ms(self) -> u64 {
        self.build_ms
            .saturating_add(self.matrix_plan_ms)
            .saturating_add(self.distance_ms)
            .saturating_add(self.hierarchy_ms)
            .saturating_add(self.serialize_ms)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelFinslerContract {
    pub projection_space: String,
    pub target_count: usize,
    pub directed_edge_count: usize,
    pub genus: u16,
    pub matrix_cells: usize,
    pub distance_evaluations: usize,
    pub asymmetric_pair_count: usize,
    pub hierarchy_violation_count: usize,
    pub estimated_bytes: usize,
    pub timings: SiegelFinslerTimings,
}

impl SiegelFinslerContract {
    pub fn new(input: SiegelFinslerContractInput) -> Self {
        let genus = input.genus.max(1);
        let matrix_cells = siegel_matrix_cells(genus);
        let estimated_bytes =
            estimate_siegel_contract_bytes(input.target_count, input.directed_edge_count, genus);

        Self {
            projection_space: SIEGEL_FINSLER_PROJECTION_SPACE.to_owned(),
            target_count: input.target_count,
            directed_edge_count: input.directed_edge_count,
            genus,
            matrix_cells,
            distance_evaluations: input.distance_evaluations,
            asymmetric_pair_count: input.asymmetric_pair_count,
            hierarchy_violation_count: input.hierarchy_violation_count,
            estimated_bytes,
            timings: input.timings,
        }
    }

    pub fn empty(genus: u16) -> Self {
        Self::new(SiegelFinslerContractInput {
            genus,
            ..SiegelFinslerContractInput::default()
        })
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct SiegelFinslerContractInput {
    pub target_count: usize,
    pub directed_edge_count: usize,
    pub genus: u16,
    pub distance_evaluations: usize,
    pub asymmetric_pair_count: usize,
    pub hierarchy_violation_count: usize,
    pub timings: SiegelFinslerTimings,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SiegelLane {
    Document,
    Chunk,
    Entity,
    Fact,
    Event,
    Temporal,
    Causal,
    Memory,
    Evidence,
    CoOccurrence,
    Other,
}

impl SiegelLane {
    pub fn from_graph_lane(value: &str) -> Self {
        match value {
            "document_spine" | "document" => Self::Document,
            "chunk_spine" | "chunk" => Self::Chunk,
            "entity_anchor" | "entity" => Self::Entity,
            "relationship_fact" | "graph_fact" | "fact" => Self::Fact,
            "event_identity" | "event" => Self::Event,
            "temporal_fact" | "temporal" => Self::Temporal,
            "causal_fact" | "causal" => Self::Causal,
            "memory_state" | "memory" => Self::Memory,
            "anchor_evidence" | "evidence" => Self::Evidence,
            "cooccurrence_weak" | "co_occurrence" | "cooccurrence" => Self::CoOccurrence,
            _ => Self::Other,
        }
    }

    #[inline]
    pub const fn code(self) -> u8 {
        match self {
            Self::Document => 0,
            Self::Chunk => 1,
            Self::Entity => 2,
            Self::Fact => 3,
            Self::Event => 4,
            Self::Temporal => 5,
            Self::Causal => 6,
            Self::Memory => 7,
            Self::Evidence => 8,
            Self::CoOccurrence => 9,
            Self::Other => 10,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SiegelTargetView {
    pub ord: u32,
    pub stable_hash: u64,
    pub lane: SiegelLane,
    pub hierarchy_depth: u16,
    pub confidence_milli: u16,
}

impl SiegelTargetView {
    pub const fn new(ord: u32, stable_hash: u64, lane: SiegelLane, hierarchy_depth: u16) -> Self {
        Self {
            ord,
            stable_hash,
            lane,
            hierarchy_depth,
            confidence_milli: 1_000,
        }
    }

    #[inline]
    pub fn confidence(self) -> f32 {
        self.confidence_milli as f32 / 1_000.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SiegelEdgeKind {
    Parent,
    Backbone,
    Bridge,
    Evidence,
    Associative,
}

impl SiegelEdgeKind {
    pub fn from_graph_role(value: &str) -> Self {
        match value {
            "parent" | "contains" | "document_contains" | "chunk_contains" => Self::Parent,
            "backbone" | "spine" | "local" => Self::Backbone,
            "bridge" | "cross_region" => Self::Bridge,
            "evidence" | "supports" => Self::Evidence,
            _ => Self::Associative,
        }
    }

    #[inline]
    pub const fn is_directed_kernel_edge(self) -> bool {
        matches!(self, Self::Parent | Self::Backbone | Self::Bridge)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SiegelDirectedEdgeView {
    pub from_ord: u32,
    pub to_ord: u32,
    pub kind: SiegelEdgeKind,
    pub weight_milli: u16,
}

impl SiegelDirectedEdgeView {
    pub const fn new(from_ord: u32, to_ord: u32, kind: SiegelEdgeKind) -> Self {
        Self {
            from_ord,
            to_ord,
            kind,
            weight_milli: 1_000,
        }
    }

    #[inline]
    pub fn weight(self) -> f32 {
        self.weight_milli as f32 / 1_000.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SiegelDirectedPair {
    pub from_ord: u32,
    pub to_ord: u32,
    pub kind: SiegelEdgeKind,
    pub weight_milli: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelKernelCaps {
    pub max_targets: usize,
    pub max_directed_edges: usize,
    pub max_pairs: usize,
    pub max_distance_evaluations: usize,
}

impl Default for SiegelKernelCaps {
    fn default() -> Self {
        Self {
            max_targets: DEFAULT_SIEGEL_MAX_TARGETS,
            max_directed_edges: DEFAULT_SIEGEL_MAX_DIRECTED_EDGES,
            max_pairs: DEFAULT_SIEGEL_MAX_PAIRS,
            max_distance_evaluations: DEFAULT_SIEGEL_MAX_DISTANCE_EVALUATIONS,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelKernelCounters {
    pub target_count: usize,
    pub directed_edge_count: usize,
    pub pair_count: usize,
    pub skipped_edge_count: usize,
    pub capped_edge_count: usize,
    pub capped_pair_count: usize,
    pub capped_distance_count: usize,
    pub distance_evaluations: usize,
    pub asymmetric_pair_count: usize,
    pub hierarchy_violation_count: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelFinslerConfig {
    pub direction_bias: f32,
    pub bridge_penalty: f32,
    pub hierarchy_violation_penalty: f32,
    pub confidence_penalty: f32,
}

impl Default for SiegelFinslerConfig {
    fn default() -> Self {
        Self {
            direction_bias: 0.08,
            bridge_penalty: 0.06,
            hierarchy_violation_penalty: 0.35,
            confidence_penalty: 0.08,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SymmetricMatrix<const CELLS: usize> {
    cells: [f32; CELLS],
}

pub type SiegelMatrixG3 = SymmetricMatrix<6>;

impl<const CELLS: usize> SymmetricMatrix<CELLS> {
    pub const fn new(cells: [f32; CELLS]) -> Self {
        Self { cells }
    }

    #[inline]
    pub fn cell(&self, idx: usize) -> f32 {
        self.cells[idx]
    }

    #[inline]
    pub const fn cells(&self) -> &[f32; CELLS] {
        &self.cells
    }
}

pub fn build_directed_pairs_into(
    targets: &[SiegelTargetView],
    edges: &[SiegelDirectedEdgeView],
    caps: SiegelKernelCaps,
    out: &mut Vec<SiegelDirectedPair>,
) -> SiegelKernelCounters {
    out.clear();

    let target_count = targets.len().min(caps.max_targets);
    let edge_scan_limit = edges.len().min(caps.max_directed_edges);
    let mut counters = SiegelKernelCounters {
        target_count,
        directed_edge_count: edge_scan_limit,
        capped_edge_count: edges.len().saturating_sub(edge_scan_limit),
        ..SiegelKernelCounters::default()
    };

    if out.capacity() < edge_scan_limit.min(caps.max_pairs) {
        out.reserve(edge_scan_limit.min(caps.max_pairs) - out.capacity());
    }

    for edge in edges.iter().take(edge_scan_limit) {
        if !edge.kind.is_directed_kernel_edge() {
            counters.skipped_edge_count += 1;
            continue;
        }

        if edge.from_ord as usize >= target_count || edge.to_ord as usize >= target_count {
            counters.skipped_edge_count += 1;
            continue;
        }

        if out.len() >= caps.max_pairs {
            counters.capped_pair_count += 1;
            continue;
        }

        out.push(SiegelDirectedPair {
            from_ord: edge.from_ord,
            to_ord: edge.to_ord,
            kind: edge.kind,
            weight_milli: edge.weight_milli,
        });
    }

    counters.pair_count = out.len();
    counters
}

pub fn evaluate_pairs_g3(
    targets: &[SiegelTargetView],
    matrices: &[SiegelMatrixG3],
    pairs: &[SiegelDirectedPair],
    caps: SiegelKernelCaps,
    config: SiegelFinslerConfig,
) -> SiegelKernelCounters {
    let mut counters = SiegelKernelCounters {
        target_count: targets.len().min(caps.max_targets),
        directed_edge_count: pairs.len(),
        pair_count: pairs.len().min(caps.max_pairs),
        ..SiegelKernelCounters::default()
    };

    let eval_limit = counters.pair_count.min(caps.max_distance_evaluations);

    counters.capped_distance_count = counters.pair_count.saturating_sub(eval_limit);

    for pair in pairs.iter().take(eval_limit) {
        let from_idx = pair.from_ord as usize;
        let to_idx = pair.to_ord as usize;

        let Some(from_target) = targets.get(from_idx).copied() else {
            continue;
        };
        let Some(to_target) = targets.get(to_idx).copied() else {
            continue;
        };
        let Some(from_matrix) = matrices.get(from_idx) else {
            continue;
        };
        let Some(to_matrix) = matrices.get(to_idx) else {
            continue;
        };

        let forward =
            finsler_distance(from_target, to_target, from_matrix, to_matrix, pair, config);
        let reverse_pair = SiegelDirectedPair {
            from_ord: pair.to_ord,
            to_ord: pair.from_ord,
            kind: pair.kind,
            weight_milli: pair.weight_milli,
        };
        let reverse = finsler_distance(
            to_target,
            from_target,
            to_matrix,
            from_matrix,
            &reverse_pair,
            config,
        );

        counters.distance_evaluations += 2;
        if (forward - reverse).abs() > 1e-5 {
            counters.asymmetric_pair_count += 1;
        }
        if to_target.hierarchy_depth <= from_target.hierarchy_depth {
            counters.hierarchy_violation_count += 1;
        }
    }

    counters
}

pub fn contract_from_counters(
    counters: SiegelKernelCounters,
    genus: u16,
    timings: SiegelFinslerTimings,
) -> SiegelFinslerContract {
    SiegelFinslerContract::new(SiegelFinslerContractInput {
        target_count: counters.target_count,
        directed_edge_count: counters.directed_edge_count,
        genus,
        distance_evaluations: counters.distance_evaluations,
        asymmetric_pair_count: counters.asymmetric_pair_count,
        hierarchy_violation_count: counters.hierarchy_violation_count,
        timings,
    })
}

#[inline]
pub fn finsler_distance<const CELLS: usize>(
    from: SiegelTargetView,
    to: SiegelTargetView,
    from_matrix: &SymmetricMatrix<CELLS>,
    to_matrix: &SymmetricMatrix<CELLS>,
    pair: &SiegelDirectedPair,
    config: SiegelFinslerConfig,
) -> f32 {
    let mut sum = 0.0f32;

    for idx in 0..CELLS {
        let delta = to_matrix.cell(idx) - from_matrix.cell(idx);
        let forward_weight = if delta >= 0.0 {
            1.0 + config.direction_bias
        } else {
            1.0 - (config.direction_bias * 0.5)
        };
        sum += delta.abs() * forward_weight;
    }

    let bridge_penalty = if pair.kind == SiegelEdgeKind::Bridge {
        config.bridge_penalty
    } else {
        0.0
    };
    let hierarchy_penalty = if to.hierarchy_depth <= from.hierarchy_depth {
        config.hierarchy_violation_penalty
    } else {
        0.0
    };
    let confidence_penalty =
        (2.0 - from.confidence() - to.confidence()).max(0.0) * config.confidence_penalty;
    let weight = pair.weight_milli.max(1) as f32 / 1_000.0;

    ((sum / CELLS.max(1) as f32) + bridge_penalty + hierarchy_penalty + confidence_penalty) / weight
}

#[inline]
pub const fn siegel_matrix_cells(genus: u16) -> usize {
    let g = genus as usize;
    (g * (g + 1)) / 2
}

#[inline]
pub const fn estimate_siegel_contract_bytes(
    target_count: usize,
    directed_edge_count: usize,
    genus: u16,
) -> usize {
    let cell_bytes = siegel_matrix_cells(genus) * 2 * core::mem::size_of::<f32>();
    let edge_bytes = directed_edge_count * 2 * core::mem::size_of::<u32>();
    target_count * cell_bytes + edge_bytes
}

#[cfg(test)]
mod tests;
