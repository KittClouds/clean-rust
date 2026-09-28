use super::{
    EdgeSlot, KernelWalkBudget, KernelWalkScoring, KernelWalkSeed, KernelWalkSeedFamily,
    KernelWalkStats,
};
use crate::chrono_region::{CachedEdgeRef, RegionTraversalIndex};
use crate::{
    KernelEdge, KernelGraphLayer, KernelQuerySurface, KernelRelationClass, KernelVertex,
    KernelVertexClass,
};
use rustc_hash::{FxHashMap, FxHashSet};
use scirs2_graph::compressed::CsrGraph;

pub(super) const DEFAULT_FRESHNESS_WINDOW_MS: i64 = 30 * 24 * 60 * 60 * 1000;

pub(super) fn normalize_budget(mut budget: KernelWalkBudget) -> KernelWalkBudget {
    budget.max_nodes = budget.max_nodes.clamp(2, 512);
    budget.max_edges = budget.max_edges.clamp(1, 2048);
    budget.max_depth = budget.max_depth.clamp(1, 8);
    budget.max_per_family_fanout = budget.max_per_family_fanout.clamp(1, 64);
    budget.max_per_island_expansion = budget.max_per_island_expansion.clamp(1, 256);
    budget
}

pub(super) fn include_vertex(
    index: usize,
    view: &KernelQuerySurface,
    included: &mut [bool],
    island_counts: &mut FxHashMap<String, usize>,
    budget: &KernelWalkBudget,
    stats: &mut KernelWalkStats,
) -> bool {
    if included[index] {
        return true;
    }
    if included.iter().filter(|slot| **slot).count() >= budget.max_nodes {
        stats.pruned_by_node_budget += 1;
        return false;
    }
    if let Some(island_id) = context_island_id(&view.vertices()[index]) {
        let count = island_counts.get(island_id).copied().unwrap_or(0);
        if count >= budget.max_per_island_expansion {
            stats.pruned_by_island_budget += 1;
            return false;
        }
        island_counts.insert(island_id.to_owned(), count + 1);
    }
    included[index] = true;
    true
}

pub(super) fn seed_prizes(view: &KernelQuerySurface, seeds: &[KernelWalkSeed]) -> Vec<i32> {
    let mut prizes = vec![0i32; view.vertices().len()];
    for seed in seeds {
        let Some(&index) = view.vertex_index().get(seed.vertex_id.as_str()) else {
            continue;
        };
        let family_bonus = match seed.family {
            KernelWalkSeedFamily::Lexical => 900,
            KernelWalkSeedFamily::Semantic => 820,
            KernelWalkSeedFamily::Entity => 1100,
            KernelWalkSeedFamily::ContextIsland => 720,
            KernelWalkSeedFamily::QueryParse => 980,
            KernelWalkSeedFamily::Graph => 760,
        };
        let prize = seed.prize_millis.min(i32::MAX as u32) as i32 + family_bonus;
        prizes[index] = prizes[index].max(prize);
    }
    prizes
}

pub(super) fn node_prize_millis(vertex: &KernelVertex) -> i32 {
    let base = match vertex_family_slot(vertex) {
        0 => 1500,
        1 => 1250,
        2 => 1120,
        3 => 780,
        4 => 520,
        5 => 420,
        _ => 160,
    };
    let active_bonus = if status_of(vertex) == Some("active") {
        180
    } else {
        0
    };
    let confidence_bonus =
        (vertex.provenance.confidence.unwrap_or(0.0).clamp(0.0, 1.0) * 220.0).round() as i32;
    let evidence_bonus = vertex.provenance.evidence_refs.len().min(8) as i32 * 45;
    base + active_bonus + confidence_bonus + evidence_bonus
}

pub(super) fn edge_cost_millis(
    edge: &KernelEdge,
    source: &KernelVertex,
    target: &KernelVertex,
    traversal: &RegionTraversalIndex,
    target_index: usize,
    scoring: &KernelWalkScoring,
) -> i32 {
    let family_cost = match edge_family_slot(edge) {
        0 => 75,
        1 => 90,
        2 => 105,
        3 => 115,
        4 => 135,
        5 => 220,
        _ => 260,
    };
    let layer_cost = match edge.layer {
        KernelGraphLayer::Asserted => 20,
        KernelGraphLayer::Candidate => 160,
    };
    let confidence_discount =
        (edge.provenance.confidence.unwrap_or(0.0).clamp(0.0, 1.0) * 90.0).round() as i32;
    let bridge_cost = if context_island_id(source).is_some()
        && context_island_id(target).is_some()
        && context_island_id(source) != context_island_id(target)
    {
        scoring.cross_island_cost_millis
    } else {
        0
    };
    let fanout_cost = if traversal.neighbor_arcs(target_index).len() > scoring.high_fanout_degree {
        scoring.high_fanout_cost_millis
    } else {
        0
    };
    (family_cost + layer_cost + bridge_cost + fanout_cost - confidence_discount).max(10)
}

pub(super) fn contradiction_debt_millis(edge: &KernelEdge, vertex: &KernelVertex) -> i32 {
    let edge_type = edge.edge_type.0.as_str();
    let mut debt = 0;
    if edge_type.contains("contradict") || edge_type.contains("conflict") {
        debt += 420;
    }
    if matches!(vertex.kind.as_str(), "conflict" | "gap")
        || status_of(vertex).is_some_and(|status| matches!(status, "rejected" | "conflict"))
    {
        debt += 320;
    }
    debt
}

pub(super) fn stale_edge_debt(edge: &KernelEdge, scoring: &KernelWalkScoring) -> i32 {
    let mut debt = 0;
    if matches!(edge_status(edge), Some("expired" | "superseded" | "stale")) {
        debt += 360;
    }
    debt + temporal_stale_debt(edge.temporal.recorded_at, scoring)
}

pub(super) fn stale_vertex_debt(vertex: &KernelVertex, scoring: &KernelWalkScoring) -> i32 {
    let mut debt = 0;
    if matches!(status_of(vertex), Some("expired" | "superseded" | "stale")) {
        debt += 360;
    }
    debt + temporal_stale_debt(vertex.temporal.recorded_at, scoring)
}

pub(super) fn temporal_stale_debt(recorded_at: Option<i64>, scoring: &KernelWalkScoring) -> i32 {
    let Some(now) = scoring.reference_time_ms else {
        return 0;
    };
    let Some(recorded_at) = recorded_at else {
        return 80;
    };
    let age = now.saturating_sub(recorded_at);
    if age <= scoring.freshness_window_ms.max(1) {
        return 0;
    }
    ((age / scoring.freshness_window_ms.max(1)).min(8) as i32) * 120
}

pub(super) fn vertex_family_slot(vertex: &KernelVertex) -> usize {
    match vertex.class {
        KernelVertexClass::Event => 0,
        KernelVertexClass::State => 1,
        KernelVertexClass::Entity => 3,
        KernelVertexClass::TimeAnchor | KernelVertexClass::CalendarAnchor => 4,
        KernelVertexClass::Document
        | KernelVertexClass::Chunk
        | KernelVertexClass::Alias
        | KernelVertexClass::Mention
        | KernelVertexClass::Narrative
        | KernelVertexClass::Episode => 5,
        KernelVertexClass::Generic | KernelVertexClass::Memory | KernelVertexClass::Task => {
            match vertex.kind.as_str() {
                "event" => 0,
                "state" | "conflict" | "gap" => 1,
                "claim" => 2,
                "entity" => 3,
                "time_anchor" | "calendar_anchor" => 4,
                "chunk" | "document" | "alias" | "mention" | "narrative" | "episode" => 5,
                _ => 6,
            }
        }
    }
}

pub(super) fn status_of(vertex: &KernelVertex) -> Option<&str> {
    vertex
        .value
        .get("status")
        .and_then(serde_json::Value::as_str)
        .or_else(|| {
            vertex
                .attributes
                .get("status")
                .and_then(serde_json::Value::as_str)
        })
}

pub(super) fn context_island_id(vertex: &KernelVertex) -> Option<&str> {
    string_attr(vertex, "contextIslandId")
        .or_else(|| string_attr(vertex, "islandId"))
        .or_else(|| string_attr(vertex, "worldId"))
        .or_else(|| vertex.document_id.as_deref())
}

pub(super) fn projected_csr_memory_bytes(
    traversal: &RegionTraversalIndex,
    node_count: usize,
    enabled: bool,
) -> usize {
    if !enabled {
        return 0;
    }
    let mut row_ptr = Vec::with_capacity(node_count + 1);
    let mut col_indices = Vec::with_capacity(traversal.arc_count());
    row_ptr.push(0);
    for index in 0..node_count {
        col_indices.extend(
            traversal
                .neighbor_arcs(index)
                .iter()
                .map(|arc| arc.neighbor),
        );
        row_ptr.push(col_indices.len());
    }
    let values = vec![1.0; col_indices.len()];
    CsrGraph::from_raw(node_count, row_ptr, col_indices, values, true)
        .map(|graph| graph.memory_bytes())
        .unwrap_or(0)
}

pub(super) fn backfill_edges(
    view: &KernelQuerySurface,
    traversal: &RegionTraversalIndex,
    included: &[bool],
    selected_edges: &mut FxHashSet<EdgeSlot>,
    max_edges: usize,
    scoring: &KernelWalkScoring,
) {
    if selected_edges.len() >= max_edges {
        return;
    }
    let mut candidates = traversal
        .allowed_edges()
        .iter()
        .filter(|edge_ref| included[edge_ref.source] && included[edge_ref.target])
        .filter(|edge_ref| !selected_edges.contains(&EdgeSlot::from(**edge_ref)))
        .map(|edge_ref| {
            let edge = edge_ref.edge(view);
            let cost = edge_cost_millis(
                edge,
                &view.vertices()[edge_ref.source],
                &view.vertices()[edge_ref.target],
                traversal,
                edge_ref.target,
                scoring,
            );
            (*edge_ref, cost)
        })
        .collect::<Vec<_>>();
    candidates.sort_by(|(left, left_cost), (right, right_cost)| {
        left_cost
            .cmp(right_cost)
            .then_with(|| left.source.cmp(&right.source))
            .then_with(|| left.target.cmp(&right.target))
    });
    for (edge_ref, _) in candidates {
        if selected_edges.len() >= max_edges {
            break;
        }
        selected_edges.insert(EdgeSlot::from(edge_ref));
    }
}

fn edge_family_slot(edge: &KernelEdge) -> usize {
    match edge.relation_class {
        KernelRelationClass::Temporal | KernelRelationClass::Calendar => return 2,
        KernelRelationClass::Identity | KernelRelationClass::Resolution => return 3,
        KernelRelationClass::Semantic | KernelRelationClass::Candidate => return 4,
        KernelRelationClass::Structural
        | KernelRelationClass::Memory
        | KernelRelationClass::Narrative
        | KernelRelationClass::Custom => {}
    }
    match edge.edge_type.0.as_str() {
        "causal_link" | "semantic::missing_intermediate_cause" => 0,
        "supported_by" | "state_of" | "state_value" | "about" | "subject" | "object" => 1,
        edge_type if edge_type.contains("time") || edge_type.contains("date") => 2,
        "canonicalized_as" | "alias_of" => 3,
        "semantic::same_process" | "semantic::related_event" => 4,
        "bridge" | "context_island_bridge" => 5,
        _ => 6,
    }
}

fn edge_status(edge: &KernelEdge) -> Option<&str> {
    edge.attributes
        .get("status")
        .and_then(serde_json::Value::as_str)
        .or_else(|| {
            edge.data
                .as_ref()?
                .get("status")
                .and_then(serde_json::Value::as_str)
        })
}

fn string_attr<'a>(vertex: &'a KernelVertex, key: &str) -> Option<&'a str> {
    vertex
        .attributes
        .get(key)
        .and_then(serde_json::Value::as_str)
        .or_else(|| vertex.value.get(key).and_then(serde_json::Value::as_str))
}

impl From<CachedEdgeRef> for EdgeSlot {
    fn from(edge_ref: CachedEdgeRef) -> Self {
        Self {
            layer: edge_ref.layer,
            index: edge_ref.index,
        }
    }
}
