use crate::graph::SemanticCoreGraph;
use crate::leiden::PartitionResult;
use crate::{CommunityArtifactError, DeterministicCommunityPolicy};
use hashbrown::HashMap;
use rayon::prelude::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct BridgeMetric {
    pub node: u32,
    pub neighboring_communities: u32,
    pub total_strength: u64,
    pub boundary_strength: u64,
    pub participation_micros: u32,
    pub boundary_micros: u32,
    pub conductance_micros: u32,
    pub score_micros: u32,
}

pub(crate) struct CommunityMetrics {
    pub affinity_offsets: Vec<u64>,
    pub affinity_targets: Vec<u32>,
    pub affinity_weights: Vec<u64>,
    pub bridges: Vec<BridgeMetric>,
}

type SparseAffinityColumns = (Vec<u64>, Vec<u32>, Vec<u64>);

pub(crate) fn compute_metrics(
    graph: &SemanticCoreGraph,
    partition: &PartitionResult,
    policy: &DeterministicCommunityPolicy,
) -> Result<CommunityMetrics, CommunityArtifactError> {
    let community_count = partition.communities.len();
    let mut affinities = HashMap::<(u32, u32), u64>::new();
    let mut volume = vec![0_u64; community_count];
    let mut cut = vec![0_u64; community_count];
    for &node in &graph.core_nodes {
        let community = partition.node_community[node as usize];
        let strength = graph.neighbors(node).iter().try_fold(0_u64, |sum, edge| {
            sum.checked_add(edge.weight)
                .ok_or_else(|| CommunityArtifactError::Invalid("node strength overflow".to_owned()))
        })?;
        volume[community as usize] = volume[community as usize]
            .checked_add(strength)
            .ok_or_else(|| CommunityArtifactError::Invalid("volume overflow".to_owned()))?;
    }
    for edge in &graph.edges {
        let source = partition.node_community[edge.source as usize];
        let target = partition.node_community[edge.target as usize];
        if source == target {
            continue;
        }
        add_weight(&mut affinities, (source, target), edge.weight)?;
        add_weight(&mut affinities, (target, source), edge.weight)?;
        cut[source as usize] = cut[source as usize]
            .checked_add(edge.weight)
            .ok_or_else(|| CommunityArtifactError::Invalid("cut overflow".to_owned()))?;
        cut[target as usize] = cut[target as usize]
            .checked_add(edge.weight)
            .ok_or_else(|| CommunityArtifactError::Invalid("cut overflow".to_owned()))?;
    }
    let total_volume = volume.iter().try_fold(0_u64, |sum, value| {
        sum.checked_add(*value)
            .ok_or_else(|| CommunityArtifactError::Invalid("total volume overflow".to_owned()))
    })?;
    let conductance = volume
        .iter()
        .zip(&cut)
        .map(|(&community_volume, &community_cut)| {
            let denominator = community_volume.min(total_volume.saturating_sub(community_volume));
            ratio_micros(community_cut, denominator)
        })
        .collect::<Vec<_>>();
    let (affinity_offsets, affinity_targets, affinity_weights) =
        sparse_affinity(community_count, affinities)?;
    let bridges = bridge_metrics(graph, partition, policy, &conductance)?;
    Ok(CommunityMetrics {
        affinity_offsets,
        affinity_targets,
        affinity_weights,
        bridges,
    })
}

fn bridge_metrics(
    graph: &SemanticCoreGraph,
    partition: &PartitionResult,
    policy: &DeterministicCommunityPolicy,
    conductance: &[u32],
) -> Result<Vec<BridgeMetric>, CommunityArtifactError> {
    let mut strengths = HashMap::<u32, u64>::new();
    let mut bridges = Vec::new();
    let (participation_weight, boundary_weight, conductance_weight) = policy.bridge_weights();
    for &node in &graph.core_nodes {
        let own = partition.node_community[node as usize];
        strengths.clear();
        let mut total = 0_u64;
        for neighbor in graph.neighbors(node) {
            total = total.checked_add(neighbor.weight).ok_or_else(|| {
                CommunityArtifactError::Invalid("bridge strength overflow".to_owned())
            })?;
            let community = partition.node_community[neighbor.node as usize];
            add_weight(&mut strengths, community, neighbor.weight)?;
        }
        let internal = strengths.get(&own).copied().unwrap_or_default();
        let boundary = total.saturating_sub(internal);
        if boundary == 0 || total == 0 {
            continue;
        }
        let square_sum = strengths.values().fold(0_u128, |sum, strength| {
            sum + u128::from(*strength) * u128::from(*strength)
        });
        let total_square = u128::from(total) * u128::from(total);
        let participation = 1_000_000_u128
            .saturating_sub(square_sum.saturating_mul(1_000_000) / total_square)
            as u32;
        let boundary_micros = ratio_micros(boundary, total);
        let conductance_micros = conductance[own as usize];
        let score = (u64::from(participation) * u64::from(participation_weight)
            + u64::from(boundary_micros) * u64::from(boundary_weight)
            + u64::from(conductance_micros) * u64::from(conductance_weight))
            / 1_000;
        bridges.push(BridgeMetric {
            node,
            neighboring_communities: strengths
                .keys()
                .filter(|community| **community != own)
                .count() as u32,
            total_strength: total,
            boundary_strength: boundary,
            participation_micros: participation,
            boundary_micros,
            conductance_micros,
            score_micros: score as u32,
        });
    }
    bridges.sort_unstable_by_key(|bridge| bridge.node);
    Ok(bridges)
}

fn sparse_affinity(
    community_count: usize,
    affinities: HashMap<(u32, u32), u64>,
) -> Result<SparseAffinityColumns, CommunityArtifactError> {
    let mut rows = affinities
        .into_iter()
        .map(|((source, target), weight)| (source, target, weight))
        .collect::<Vec<_>>();
    rows.par_sort_unstable_by_key(|(source, target, _)| (*source, *target));
    let mut counts = vec![0_u64; community_count];
    for (source, _, _) in &rows {
        counts[*source as usize] += 1;
    }
    let mut offsets = Vec::with_capacity(community_count + 1);
    offsets.push(0_u64);
    for count in counts {
        offsets.push(offsets.last().copied().unwrap() + count);
    }
    Ok((
        offsets,
        rows.iter().map(|(_, target, _)| *target).collect(),
        rows.into_iter().map(|(_, _, weight)| weight).collect(),
    ))
}

fn add_weight<K: Eq + std::hash::Hash>(
    map: &mut HashMap<K, u64>,
    key: K,
    weight: u64,
) -> Result<(), CommunityArtifactError> {
    let slot = map.entry(key).or_default();
    *slot = slot
        .checked_add(weight)
        .ok_or_else(|| CommunityArtifactError::Invalid("metric weight overflow".to_owned()))?;
    Ok(())
}

fn ratio_micros(numerator: u64, denominator: u64) -> u32 {
    if denominator == 0 {
        return 0;
    }
    ((u128::from(numerator).saturating_mul(1_000_000) / u128::from(denominator)).min(1_000_000))
        as u32
}
