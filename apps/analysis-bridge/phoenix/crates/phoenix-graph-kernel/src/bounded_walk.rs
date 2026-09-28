use crate::chrono_region::{CachedEdgeLayer, RegionTraversalIndex};
use crate::pcst_region::compact_region_with_pcst;
use crate::{KernelEdge, KernelGraphSnapshot, KernelQuerySurface, KernelRegionProfile};
use rustc_hash::{FxHashMap, FxHashSet};
use std::cmp::Ordering;
use std::collections::BinaryHeap;

#[path = "bounded_walk_support.rs"]
mod support;

#[cfg(test)]
#[path = "bounded_walk_tests.rs"]
mod tests;

use support::{
    backfill_edges, contradiction_debt_millis, edge_cost_millis, include_vertex, node_prize_millis,
    normalize_budget, projected_csr_memory_bytes, seed_prizes, stale_edge_debt, stale_vertex_debt,
    vertex_family_slot, DEFAULT_FRESHNESS_WINDOW_MS,
};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub enum KernelWalkSeedFamily {
    #[default]
    Graph,
    Lexical,
    Semantic,
    Entity,
    ContextIsland,
    QueryParse,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KernelWalkSeed {
    pub vertex_id: String,
    pub family: KernelWalkSeedFamily,
    pub prize_millis: u32,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KernelWalkBudget {
    pub max_nodes: usize,
    pub max_edges: usize,
    pub max_depth: usize,
    pub max_per_family_fanout: usize,
    pub max_per_island_expansion: usize,
    pub max_contradiction_debt_millis: i32,
    pub max_stale_evidence_millis: i32,
    pub profile: KernelRegionProfile,
    pub compact: bool,
    pub projected_csr_diagnostics: bool,
}

impl Default for KernelWalkBudget {
    fn default() -> Self {
        Self {
            max_nodes: 64,
            max_edges: 160,
            max_depth: 3,
            max_per_family_fanout: 8,
            max_per_island_expansion: 24,
            max_contradiction_debt_millis: 800,
            max_stale_evidence_millis: 900,
            profile: KernelRegionProfile::Generic,
            compact: true,
            projected_csr_diagnostics: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KernelWalkScoring {
    pub min_include_utility_millis: i32,
    pub depth_cost_millis: i32,
    pub cross_island_cost_millis: i32,
    pub high_fanout_degree: usize,
    pub high_fanout_cost_millis: i32,
    pub reference_time_ms: Option<i64>,
    pub freshness_window_ms: i64,
}

impl Default for KernelWalkScoring {
    fn default() -> Self {
        Self {
            min_include_utility_millis: -250,
            depth_cost_millis: 45,
            cross_island_cost_millis: 220,
            high_fanout_degree: 24,
            high_fanout_cost_millis: 180,
            reference_time_ms: None,
            freshness_window_ms: DEFAULT_FRESHNESS_WINDOW_MS,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KernelWalkStats {
    pub considered_edges: usize,
    pub pruned_by_node_budget: usize,
    pub pruned_by_edge_budget: usize,
    pub pruned_by_family_fanout: usize,
    pub pruned_by_island_budget: usize,
    pub pruned_by_contradiction_debt: usize,
    pub pruned_by_stale_evidence: usize,
    pub projected_csr_memory_bytes: usize,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KernelWalkResult {
    pub snapshot: KernelGraphSnapshot,
    pub seed_vertex_ids: Vec<String>,
    pub included_vertex_ids: Vec<String>,
    pub total_prize_millis: i32,
    pub total_cost_millis: i32,
    pub contradiction_debt_millis: i32,
    pub stale_evidence_millis: i32,
    pub truncated: bool,
    pub stats: KernelWalkStats,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct FrontierItem {
    utility_millis: i32,
    depth: usize,
    insertion_order: usize,
    index: usize,
    contradiction_debt_millis: i32,
    stale_evidence_millis: i32,
}

impl Ord for FrontierItem {
    fn cmp(&self, other: &Self) -> Ordering {
        self.utility_millis
            .cmp(&other.utility_millis)
            .then_with(|| other.depth.cmp(&self.depth))
            .then_with(|| other.insertion_order.cmp(&self.insertion_order))
            .then_with(|| other.index.cmp(&self.index))
    }
}

impl PartialOrd for FrontierItem {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
struct EdgeSlot {
    layer: CachedEdgeLayer,
    index: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WalkCandidate {
    neighbor: usize,
    edge_slot: EdgeSlot,
    utility_millis: i32,
    next_depth: usize,
    family_slot: usize,
    contradiction_debt_millis: i32,
    stale_evidence_millis: i32,
}

pub fn bounded_walk_projected_graph(
    view: &KernelQuerySurface,
    anchor_vertex_ids: &[String],
    seeds: &[KernelWalkSeed],
    budget: KernelWalkBudget,
    scoring: KernelWalkScoring,
    edge_allowed: fn(&KernelEdge) -> bool,
) -> KernelWalkResult {
    let budget = normalize_budget(budget);
    let dense = view.vertex_index();
    if view.vertices().is_empty() {
        return KernelWalkResult::default();
    }
    let traversal = view.region_traversal_index(budget.profile, edge_allowed);
    let seed_prizes = seed_prizes(view, seeds);
    let anchor_indices = anchor_vertex_ids
        .iter()
        .filter_map(|id| dense.get(id.as_str()).copied())
        .collect::<FxHashSet<_>>();
    let seed_indices = seeds
        .iter()
        .filter_map(|seed| dense.get(seed.vertex_id.as_str()).copied())
        .collect::<FxHashSet<_>>();
    if anchor_indices.is_empty() && seed_indices.is_empty() {
        return KernelWalkResult::default();
    }

    let mut included = vec![false; view.vertices().len()];
    let mut expanded = vec![false; view.vertices().len()];
    let mut frontier = BinaryHeap::<FrontierItem>::new();
    let mut selected_edges = FxHashSet::<EdgeSlot>::default();
    let mut island_counts = FxHashMap::<String, usize>::default();
    let mut insertion_order = 0usize;
    let mut stats = KernelWalkStats {
        projected_csr_memory_bytes: projected_csr_memory_bytes(
            &traversal,
            view.vertices().len(),
            budget.projected_csr_diagnostics,
        ),
        ..KernelWalkStats::default()
    };

    for &index in anchor_indices.iter().chain(seed_indices.iter()) {
        if include_vertex(
            index,
            view,
            &mut included,
            &mut island_counts,
            &budget,
            &mut stats,
        ) {
            let prize = seed_prizes[index].max(node_prize_millis(&view.vertices()[index]));
            frontier.push(FrontierItem {
                utility_millis: prize,
                depth: 0,
                insertion_order,
                index,
                contradiction_debt_millis: 0,
                stale_evidence_millis: stale_vertex_debt(&view.vertices()[index], &scoring),
            });
            insertion_order += 1;
        }
    }

    let mut truncated = false;
    while let Some(item) = frontier.pop() {
        if item.depth >= budget.max_depth || expanded[item.index] {
            continue;
        }
        expanded[item.index] = true;
        let mut candidates = collect_candidates(
            view,
            &traversal,
            item,
            &included,
            &seed_indices,
            &seed_prizes,
            &budget,
            &scoring,
            &mut stats,
        );
        candidates.sort_by(|left, right| {
            right
                .utility_millis
                .cmp(&left.utility_millis)
                .then_with(|| left.next_depth.cmp(&right.next_depth))
                .then_with(|| {
                    view.vertices()[left.neighbor]
                        .id
                        .0
                        .cmp(&view.vertices()[right.neighbor].id.0)
                })
        });

        let mut family_fanout = [0usize; 8];
        for candidate in candidates {
            if family_fanout[candidate.family_slot] >= budget.max_per_family_fanout {
                stats.pruned_by_family_fanout += 1;
                continue;
            }
            if !included[candidate.neighbor] && selected_edges.len() >= budget.max_edges {
                stats.pruned_by_edge_budget += 1;
                truncated = true;
                continue;
            }
            if include_vertex(
                candidate.neighbor,
                view,
                &mut included,
                &mut island_counts,
                &budget,
                &mut stats,
            ) {
                family_fanout[candidate.family_slot] += 1;
                selected_edges.insert(candidate.edge_slot);
                frontier.push(FrontierItem {
                    utility_millis: candidate.utility_millis,
                    depth: candidate.next_depth,
                    insertion_order,
                    index: candidate.neighbor,
                    contradiction_debt_millis: candidate.contradiction_debt_millis,
                    stale_evidence_millis: candidate.stale_evidence_millis,
                });
                insertion_order += 1;
            } else if included[candidate.neighbor] && selected_edges.len() < budget.max_edges {
                family_fanout[candidate.family_slot] += 1;
                selected_edges.insert(candidate.edge_slot);
            } else {
                truncated = true;
            }
        }
    }

    let compacted = if budget.compact {
        compact_region_with_pcst(
            view,
            &included,
            &anchor_indices,
            &seed_indices,
            &traversal,
            budget.profile,
        )
    } else {
        included
    };
    materialize_walk(
        view,
        &traversal,
        &compacted,
        selected_edges,
        seeds,
        budget.max_edges,
        truncated,
        stats,
        &scoring,
    )
}

fn collect_candidates(
    view: &KernelQuerySurface,
    traversal: &RegionTraversalIndex,
    item: FrontierItem,
    included: &[bool],
    seed_indices: &FxHashSet<usize>,
    seed_prizes: &[i32],
    budget: &KernelWalkBudget,
    scoring: &KernelWalkScoring,
    stats: &mut KernelWalkStats,
) -> Vec<WalkCandidate> {
    let mut best_by_neighbor = FxHashMap::<usize, WalkCandidate>::default();
    let current = &view.vertices()[item.index];
    for arc in traversal.neighbor_arcs(item.index) {
        stats.considered_edges += 1;
        if arc.neighbor == item.index {
            continue;
        }
        let edge = arc.edge.edge(view);
        let neighbor = &view.vertices()[arc.neighbor];
        let edge_cost = edge_cost_millis(edge, current, neighbor, traversal, arc.neighbor, scoring);
        let contradiction_debt =
            item.contradiction_debt_millis + contradiction_debt_millis(edge, neighbor);
        if contradiction_debt > budget.max_contradiction_debt_millis {
            stats.pruned_by_contradiction_debt += 1;
            continue;
        }
        let stale_debt = item.stale_evidence_millis
            + stale_edge_debt(edge, scoring)
            + stale_vertex_debt(neighbor, scoring);
        if stale_debt > budget.max_stale_evidence_millis {
            stats.pruned_by_stale_evidence += 1;
            continue;
        }
        let mut prize = node_prize_millis(neighbor).max(seed_prizes[arc.neighbor]);
        if seed_indices.contains(&arc.neighbor) {
            prize += 400;
        }
        let next_depth = item.depth + 1;
        let utility = item.utility_millis + prize
            - edge_cost
            - (next_depth as i32 * scoring.depth_cost_millis);
        if !included[arc.neighbor] && utility < scoring.min_include_utility_millis {
            continue;
        }
        let candidate = WalkCandidate {
            neighbor: arc.neighbor,
            edge_slot: EdgeSlot::from(arc.edge),
            utility_millis: utility,
            next_depth,
            family_slot: vertex_family_slot(neighbor),
            contradiction_debt_millis: contradiction_debt,
            stale_evidence_millis: stale_debt,
        };
        match best_by_neighbor.get(&arc.neighbor) {
            Some(existing) if existing.utility_millis >= utility => {}
            _ => {
                best_by_neighbor.insert(arc.neighbor, candidate);
            }
        }
    }
    best_by_neighbor.into_values().collect()
}

fn materialize_walk(
    view: &KernelQuerySurface,
    traversal: &RegionTraversalIndex,
    included: &[bool],
    mut selected_edges: FxHashSet<EdgeSlot>,
    seeds: &[KernelWalkSeed],
    max_edges: usize,
    truncated: bool,
    stats: KernelWalkStats,
    scoring: &KernelWalkScoring,
) -> KernelWalkResult {
    backfill_edges(
        view,
        traversal,
        included,
        &mut selected_edges,
        max_edges,
        scoring,
    );
    let mut vertices = view
        .vertices()
        .iter()
        .enumerate()
        .filter(|(index, _)| included[*index])
        .map(|(_, vertex)| vertex.clone())
        .collect::<Vec<_>>();
    let mut asserted_edges = Vec::new();
    let mut candidate_edges = Vec::new();
    let mut total_cost = 0i32;
    let mut contradiction_debt = 0i32;
    let mut stale_debt = 0i32;
    for edge_ref in traversal.allowed_edges() {
        if !selected_edges.contains(&EdgeSlot::from(*edge_ref)) {
            continue;
        }
        if !included[edge_ref.source] || !included[edge_ref.target] {
            continue;
        }
        let edge = edge_ref.edge(view).clone();
        total_cost += edge_cost_millis(
            &edge,
            &view.vertices()[edge_ref.source],
            &view.vertices()[edge_ref.target],
            traversal,
            edge_ref.target,
            scoring,
        );
        contradiction_debt += contradiction_debt_millis(&edge, &view.vertices()[edge_ref.target]);
        stale_debt += stale_edge_debt(&edge, scoring);
        match edge_ref.layer {
            CachedEdgeLayer::Asserted => asserted_edges.push(edge),
            CachedEdgeLayer::Candidate => candidate_edges.push(edge),
        }
    }
    vertices.sort_by(|left, right| left.id.0.cmp(&right.id.0));
    asserted_edges.sort_by(|left, right| left.source_id.0.cmp(&right.source_id.0));
    candidate_edges.sort_by(|left, right| left.source_id.0.cmp(&right.source_id.0));
    let included_vertex_ids = vertices.iter().map(|vertex| vertex.id.0.clone()).collect();
    let seed_vertex_ids = seeds.iter().map(|seed| seed.vertex_id.clone()).collect();
    let total_prize = vertices.iter().map(node_prize_millis).sum::<i32>();
    KernelWalkResult {
        snapshot: KernelGraphSnapshot {
            vertices,
            asserted_edges,
            candidate_edges,
        },
        seed_vertex_ids,
        included_vertex_ids,
        total_prize_millis: total_prize,
        total_cost_millis: total_cost,
        contradiction_debt_millis: contradiction_debt,
        stale_evidence_millis: stale_debt,
        truncated,
        stats,
    }
}
