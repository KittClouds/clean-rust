use crate::budget::{EdgeBudget, EdgePhase};
use crate::score::confidence_micros;
use crate::scratch::{Neighbor, QueryScratch, QueueEntry};
use crate::{
    BudgetExhaustion, CancellationPhase, CancellationProbe, DiscoveryQueryError, QueryLimits,
};
use phoenix_discovery_view::AssertedDiscoveryView;
use std::num::NonZeroU64;

const PPR_MASS: u64 = 1_000_000_000;
const RESTART_MICROS: u64 = 150_000;
const MIN_QUEUE_MASS: u64 = 64;

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct PprStats {
    pub visited: u32,
    pub pushes: u32,
}

pub(crate) fn run_ppr(
    view: &AssertedDiscoveryView,
    weights: &[u16; 10],
    limits: QueryLimits,
    scratch: &mut QueryScratch,
    budget: &mut EdgeBudget,
    exhaustion: &mut BudgetExhaustion,
    cancellation: &dyn CancellationProbe,
) -> Result<PprStats, DiscoveryQueryError> {
    let score_sum: u64 = scratch
        .seeds
        .iter()
        .map(|(_, score)| u64::from(*score))
        .sum();
    if score_sum == 0 {
        return Ok(PprStats {
            visited: 0,
            pushes: 0,
        });
    }
    let mut assigned = 0_u64;
    for (index, &(node, score)) in scratch.seeds.iter().enumerate() {
        let mass = if index + 1 == scratch.seeds.len() {
            PPR_MASS.saturating_sub(assigned)
        } else {
            PPR_MASS.saturating_mul(u64::from(score)) / score_sum
        };
        assigned = assigned.saturating_add(mass);
        scratch.residual.insert(node, mass);
        let stable_hash = view.node_identity(node)?.hash;
        scratch.queue.push(QueueEntry {
            mass,
            node,
            stable_hash,
        });
    }

    let mut pushes = 0_u32;
    let push_cap = limits.ppr_visited_vertices.saturating_mul(8);
    while let Some(entry) = scratch.queue.pop() {
        if pushes & 63 == 0
            && scratch
                .cancellation
                .check(cancellation, CancellationPhase::Ppr)
        {
            break;
        }
        if pushes >= push_cap {
            exhaustion.ppr_vertices = true;
            scratch.pruning.ppr_vertices = scratch.pruning.ppr_vertices.saturating_add(1);
            break;
        }
        let current = scratch.residual.get(&entry.node).copied().unwrap_or(0);
        if current != entry.mass || current < MIN_QUEUE_MASS {
            continue;
        }
        if !scratch.reserve.contains_key(&entry.node)
            && scratch.reserve.len() >= limits.ppr_visited_vertices as usize
        {
            exhaustion.ppr_vertices = true;
            scratch.pruning.ppr_vertices = scratch.pruning.ppr_vertices.saturating_add(1);
            break;
        }
        scratch.residual.insert(entry.node, 0);
        let restart = current.saturating_mul(RESTART_MICROS) / 1_000_000;
        *scratch.reserve.entry(entry.node).or_default() += restart;
        let onward = current.saturating_sub(restart);
        collect_neighbors(
            view,
            weights,
            entry.node,
            limits,
            EdgePhase::Ppr,
            scratch,
            budget,
            exhaustion,
            cancellation,
        )?;
        let weight_sum: u64 = scratch
            .neighbors
            .iter()
            .map(|neighbor| u64::from(neighbor.quality_micros))
            .sum();
        if let Some(weight_sum) = NonZeroU64::new(weight_sum) {
            for neighbor in scratch.neighbors.iter().copied() {
                let mass =
                    onward.saturating_mul(u64::from(neighbor.quality_micros)) / weight_sum.get();
                if mass == 0 {
                    continue;
                }
                if !scratch.residual.contains_key(&neighbor.target)
                    && scratch.residual.len() >= limits.ppr_visited_vertices as usize
                {
                    exhaustion.ppr_vertices = true;
                    scratch.pruning.ppr_vertices = scratch.pruning.ppr_vertices.saturating_add(1);
                    continue;
                }
                let updated = scratch.residual.entry(neighbor.target).or_default();
                *updated = updated.saturating_add(mass);
                if *updated >= MIN_QUEUE_MASS {
                    scratch.queue.push(QueueEntry {
                        mass: *updated,
                        node: neighbor.target,
                        stable_hash: neighbor.target_hash,
                    });
                }
            }
        } else {
            *scratch.reserve.entry(entry.node).or_default() += onward;
        }
        pushes += 1;
        if exhaustion.total_edges || exhaustion.ppr_edges || scratch.cancellation.observed() {
            break;
        }
    }
    Ok(PprStats {
        visited: scratch.reserve.len() as u32,
        pushes,
    })
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn collect_neighbors(
    view: &AssertedDiscoveryView,
    weights: &[u16; 10],
    node: u32,
    limits: QueryLimits,
    phase: EdgePhase,
    scratch: &mut QueryScratch,
    budget: &mut EdgeBudget,
    exhaustion: &mut BudgetExhaustion,
    cancellation: &dyn CancellationProbe,
) -> Result<(), DiscoveryQueryError> {
    scratch.neighbors.clear();
    let outgoing = view.outgoing_edges(node)?;
    let scan_cap = usize::from(limits.edge_scan_per_state);
    if outgoing.len() > scan_cap {
        exhaustion.fanout = true;
        scratch.pruning.edge_scan = scratch
            .pruning
            .edge_scan
            .saturating_add((outgoing.len() - scan_cap).min(u32::MAX as usize) as u32);
    }
    for edge_index in outgoing.iter().take(scan_cap) {
        if budget.total_used() & 63 == 0
            && scratch.cancellation.check(
                cancellation,
                match phase {
                    EdgePhase::Ppr => CancellationPhase::Ppr,
                    EdgePhase::Beam => CancellationPhase::Beam,
                },
            )
        {
            break;
        }
        if !budget.take(phase, exhaustion) {
            break;
        }
        let edge = view.edge(edge_index)?;
        let family_weight = u32::from(weights[edge.family.code() as usize]);
        let quality = family_weight.saturating_mul(confidence_micros(edge.confidence)) / 1_000;
        if quality == 0 {
            scratch.pruning.zero_quality_edges =
                scratch.pruning.zero_quality_edges.saturating_add(1);
            continue;
        }
        scratch.neighbors.push(Neighbor {
            edge: edge_index,
            target: edge.target,
            quality_micros: quality,
            target_hash: view.node_identity(edge.target)?.hash,
            edge_hash: edge.identity.hash,
        });
    }
    scratch.neighbors.sort_unstable_by(|left, right| {
        right
            .quality_micros
            .cmp(&left.quality_micros)
            .then_with(|| left.target_hash.cmp(&right.target_hash))
            .then_with(|| left.edge_hash.cmp(&right.edge_hash))
    });
    if scratch.neighbors.len() > usize::from(limits.fanout_per_state) {
        let pruned = scratch.neighbors.len() - usize::from(limits.fanout_per_state);
        scratch.pruning.fanout_neighbors = scratch
            .pruning
            .fanout_neighbors
            .saturating_add(pruned.min(u32::MAX as usize) as u32);
        scratch
            .neighbors
            .truncate(usize::from(limits.fanout_per_state));
        exhaustion.fanout = true;
    }
    Ok(())
}
