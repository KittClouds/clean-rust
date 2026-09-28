use serde::{Deserialize, Serialize};
use std::time::Instant;

use super::{
    build_directed_pairs_into, contract_from_counters, evaluate_pairs_g3, SiegelDirectedEdgeView,
    SiegelEdgeKind, SiegelFinslerConfig, SiegelFinslerContract, SiegelFinslerTimings,
    SiegelKernelCaps, SiegelKernelCounters, SiegelLane, SiegelMatrixG3, SiegelTargetView,
    DEFAULT_SIEGEL_GENUS,
};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelKernelRunRequest {
    pub genus: Option<u16>,
    pub targets: Vec<SiegelTargetInput>,
    pub edges: Vec<SiegelEdgeInput>,
    pub caps: Option<SiegelKernelCaps>,
    pub config: Option<SiegelFinslerConfig>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelTargetInput {
    pub stable_hash: u64,
    pub lane: String,
    pub hierarchy_depth: u16,
    pub confidence_milli: Option<u16>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelEdgeInput {
    pub from_ord: u32,
    pub to_ord: u32,
    pub kind: String,
    pub weight_milli: Option<u16>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SiegelKernelRunReceipt {
    pub contract: SiegelFinslerContract,
    pub counters: SiegelKernelCounters,
    pub parent_pairs: usize,
    pub backbone_pairs: usize,
    pub bridge_pairs: usize,
}

impl Default for SiegelTargetInput {
    fn default() -> Self {
        Self {
            stable_hash: 0,
            lane: "unknown".to_owned(),
            hierarchy_depth: 0,
            confidence_milli: Some(1_000),
        }
    }
}

impl Default for SiegelEdgeInput {
    fn default() -> Self {
        Self {
            from_ord: 0,
            to_ord: 0,
            kind: "associative".to_owned(),
            weight_milli: Some(1_000),
        }
    }
}

pub fn run_siegel_finsler_kernel(request: &SiegelKernelRunRequest) -> SiegelKernelRunReceipt {
    let started = Instant::now();
    let caps = request.caps.unwrap_or_default();
    let config = request.config.unwrap_or_default();
    let genus = request.genus.unwrap_or(DEFAULT_SIEGEL_GENUS).max(1);
    let target_limit = request.targets.len().min(caps.max_targets);
    let edge_limit = request.edges.len().min(caps.max_directed_edges);

    let mut targets = Vec::with_capacity(target_limit);
    for (ord, input) in request.targets.iter().take(target_limit).enumerate() {
        targets.push(SiegelTargetView {
            ord: ord as u32,
            stable_hash: input.stable_hash,
            lane: SiegelLane::from_graph_lane(input.lane.as_str()),
            hierarchy_depth: input.hierarchy_depth,
            confidence_milli: input.confidence_milli.unwrap_or(1_000).min(1_000),
        });
    }

    let mut edges = Vec::with_capacity(edge_limit);
    for input in request.edges.iter().take(edge_limit) {
        edges.push(SiegelDirectedEdgeView {
            from_ord: input.from_ord,
            to_ord: input.to_ord,
            kind: SiegelEdgeKind::from_graph_role(input.kind.as_str()),
            weight_milli: input.weight_milli.unwrap_or(1_000).max(1),
        });
    }

    let mut pairs = Vec::with_capacity(edge_limit.min(caps.max_pairs));
    let mut counters = build_directed_pairs_into(&targets, &edges, caps, &mut pairs);
    let built = Instant::now();
    counters.capped_edge_count = counters
        .capped_edge_count
        .saturating_add(request.edges.len().saturating_sub(edge_limit));
    let matrices = build_matrices_g3(&targets);
    let matrix_planned = Instant::now();
    let eval = evaluate_pairs_g3(&targets, &matrices, &pairs, caps, config);
    let distances_done = Instant::now();
    counters.distance_evaluations = eval.distance_evaluations;
    counters.asymmetric_pair_count = eval.asymmetric_pair_count;
    counters.hierarchy_violation_count = eval.hierarchy_violation_count;
    counters.capped_distance_count = eval.capped_distance_count;

    let (parent_pairs, backbone_pairs, bridge_pairs) = count_pair_kinds(&pairs);
    let contract = contract_from_counters(
        counters,
        genus,
        SiegelFinslerTimings {
            build_ms: built.duration_since(started).as_millis() as u64,
            matrix_plan_ms: matrix_planned.duration_since(built).as_millis() as u64,
            distance_ms: distances_done.duration_since(matrix_planned).as_millis() as u64,
            hierarchy_ms: 0,
            serialize_ms: 0,
        },
    );
    SiegelKernelRunReceipt {
        contract,
        counters,
        parent_pairs,
        backbone_pairs,
        bridge_pairs,
    }
}

pub fn build_matrices_g3(targets: &[SiegelTargetView]) -> Vec<SiegelMatrixG3> {
    let mut matrices = Vec::with_capacity(targets.len());
    for target in targets {
        matrices.push(matrix_from_target_g3(*target));
    }
    matrices
}

#[inline]
pub fn matrix_from_target_g3(target: SiegelTargetView) -> SiegelMatrixG3 {
    let h0 = hash_unit(target.stable_hash);
    let h1 = hash_unit(target.stable_hash.rotate_left(17));
    let lane = target.lane.code() as f32 / 10.0;
    let depth = (target.hierarchy_depth as f32 / 8.0).min(1.0);
    let confidence = target.confidence();
    SiegelMatrixG3::new([
        0.25 + (0.50 * confidence),
        0.08 + (0.35 * lane),
        0.06 + (0.30 * depth),
        0.10 + (0.40 * h0),
        0.10 + (0.35 * h1),
        0.20 + (0.30 * (1.0 - confidence)),
    ])
}

fn count_pair_kinds(pairs: &[super::SiegelDirectedPair]) -> (usize, usize, usize) {
    let mut parent = 0usize;
    let mut backbone = 0usize;
    let mut bridge = 0usize;
    for pair in pairs {
        match pair.kind {
            SiegelEdgeKind::Parent => parent += 1,
            SiegelEdgeKind::Backbone => backbone += 1,
            SiegelEdgeKind::Bridge => bridge += 1,
            _ => {}
        }
    }
    (parent, backbone, bridge)
}

#[inline]
fn hash_unit(hash: u64) -> f32 {
    let mantissa = (hash >> 40) as u32;
    mantissa as f32 / 16_777_215.0
}
