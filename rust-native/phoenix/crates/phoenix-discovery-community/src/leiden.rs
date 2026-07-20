use crate::graph::{stable_key, Neighbor, SemanticCoreGraph, WeightedEdge};
use crate::{CommunityArtifactError, DeterministicCommunityPolicy};
use hashbrown::HashMap;
use phoenix_discovery_view::DiscoveryStableId;
use rayon::prelude::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct CommunityRecord {
    pub stable: DiscoveryStableId,
    pub component: u32,
    pub size: u32,
}

pub(crate) struct PartitionResult {
    pub node_community: Vec<u32>,
    pub communities: Vec<CommunityRecord>,
}

struct LevelGraph {
    stable: Vec<DiscoveryStableId>,
    edges: Vec<WeightedEdge>,
    self_weight: Vec<u64>,
    offsets: Vec<u64>,
    neighbors: Vec<Neighbor>,
    degree: Vec<u64>,
    total_degree: u64,
}

pub(crate) fn deterministic_leiden(
    graph: &SemanticCoreGraph,
    policy: &DeterministicCommunityPolicy,
) -> Result<PartitionResult, CommunityArtifactError> {
    let (component_offsets, component_edges) = edges_by_component(graph)?;
    let mut provisional = vec![u32::MAX; graph.node_count];
    let mut provisional_records = Vec::new();
    for component in 0..graph.component_count() {
        let nodes = graph.component_nodes(component);
        let edge_start = component_offsets[component] as usize;
        let edge_end = component_offsets[component + 1] as usize;
        let partition =
            component_partition(graph, nodes, &component_edges[edge_start..edge_end], policy)?;
        let local_count = partition.iter().copied().max().map_or(0, |value| value + 1);
        let mut sizes = vec![0_u32; local_count as usize];
        let mut minima = vec![None; local_count as usize];
        for (local_node, &local_community) in partition.iter().enumerate() {
            let global = nodes[local_node];
            sizes[local_community as usize] += 1;
            let identity = graph.stable[global as usize];
            let slot = &mut minima[local_community as usize];
            if slot.is_none_or(|current| stable_key(identity) < stable_key(current)) {
                *slot = Some(identity);
            }
            provisional[global as usize] = provisional_records.len() as u32 + local_community;
        }
        for local_community in 0..local_count as usize {
            provisional_records.push(CommunityRecord {
                stable: minima[local_community].expect("non-empty Leiden community"),
                component: component as u32,
                size: sizes[local_community],
            });
        }
    }

    let mut order = (0..provisional_records.len() as u32).collect::<Vec<_>>();
    order.sort_unstable_by_key(|community| {
        stable_key(provisional_records[*community as usize].stable)
    });
    let mut canonical = vec![0_u32; order.len()];
    let mut communities = Vec::with_capacity(order.len());
    for (dense, old) in order.into_iter().enumerate() {
        canonical[old as usize] = dense as u32;
        communities.push(provisional_records[old as usize]);
    }
    for community in &mut provisional {
        if *community != u32::MAX {
            *community = canonical[*community as usize];
        }
    }
    Ok(PartitionResult {
        node_community: provisional,
        communities,
    })
}

fn edges_by_component(
    graph: &SemanticCoreGraph,
) -> Result<(Vec<u64>, Vec<WeightedEdge>), CommunityArtifactError> {
    let mut rows = graph
        .edges
        .iter()
        .map(|edge| (graph.component_of_node[edge.source as usize], *edge))
        .collect::<Vec<_>>();
    rows.par_sort_unstable_by_key(|(component, edge)| (*component, edge.source, edge.target));
    let mut counts = vec![0_u64; graph.component_count()];
    for (component, _) in &rows {
        if *component == u32::MAX {
            return Err(CommunityArtifactError::Invalid(
                "semantic edge is outside a weak component".to_owned(),
            ));
        }
        counts[*component as usize] += 1;
    }
    let mut offsets = Vec::with_capacity(counts.len() + 1);
    offsets.push(0_u64);
    for count in counts {
        offsets.push(offsets.last().copied().unwrap() + count);
    }
    Ok((offsets, rows.into_iter().map(|(_, edge)| edge).collect()))
}

fn component_partition(
    graph: &SemanticCoreGraph,
    nodes: &[u32],
    edges: &[WeightedEdge],
    policy: &DeterministicCommunityPolicy,
) -> Result<Vec<u32>, CommunityArtifactError> {
    let mut global_to_local = HashMap::with_capacity(nodes.len());
    for (local, &global) in nodes.iter().enumerate() {
        global_to_local.insert(global, local as u32);
    }
    let local_edges = edges
        .iter()
        .map(|edge| WeightedEdge {
            source: global_to_local[&edge.source],
            target: global_to_local[&edge.target],
            weight: edge.weight,
        })
        .collect::<Vec<_>>();
    let stable = nodes
        .iter()
        .map(|node| graph.stable[*node as usize])
        .collect::<Vec<_>>();
    let mut level = LevelGraph::new(stable, local_edges, vec![0; nodes.len()])?;
    let mut original_to_level = (0..nodes.len() as u32).collect::<Vec<_>>();
    let mut initial = (0..nodes.len() as u32).collect::<Vec<_>>();
    let mut final_partition = initial.clone();
    for _ in 0..policy.max_levels() {
        let coarse = local_move(&level, &initial, policy)?;
        final_partition = original_to_level
            .iter()
            .map(|node| coarse[*node as usize])
            .collect();
        let refined = deterministic_refinement(&level, &coarse, policy)?;
        let count = refined.iter().copied().max().map_or(0, |value| value + 1) as usize;
        if count == level.stable.len() {
            break;
        }
        let mut projected_coarse = vec![u32::MAX; count];
        for (node, &refined_community) in refined.iter().enumerate() {
            let slot = &mut projected_coarse[refined_community as usize];
            if *slot == u32::MAX {
                *slot = coarse[node];
            } else if *slot != coarse[node] {
                return Err(CommunityArtifactError::Invalid(
                    "Leiden refinement crossed a coarse community".to_owned(),
                ));
            }
        }
        for level_node in &mut original_to_level {
            *level_node = refined[*level_node as usize];
        }
        level = aggregate(&level, &refined, count)?;
        initial = canonicalize_labels(&projected_coarse, &level.stable)?;
    }
    canonicalize_partition(&final_partition, nodes, &graph.stable)
}

fn local_move(
    graph: &LevelGraph,
    initial: &[u32],
    policy: &DeterministicCommunityPolicy,
) -> Result<Vec<u32>, CommunityArtifactError> {
    let count = graph.stable.len();
    if initial.len() != count {
        return Err(CommunityArtifactError::Invalid(
            "Leiden initial partition length mismatch".to_owned(),
        ));
    }
    let mut community = canonicalize_labels(initial, &graph.stable)?;
    if graph.total_degree == 0 {
        return Ok(community);
    }
    let mut totals = vec![0_u64; count];
    for (node, &label) in community.iter().enumerate() {
        totals[label as usize] = totals[label as usize]
            .checked_add(graph.degree[node])
            .ok_or_else(|| {
                CommunityArtifactError::Invalid("initial community degree overflow".to_owned())
            })?;
    }
    let mut order = (0..count as u32).collect::<Vec<_>>();
    order.sort_unstable_by_key(|node| stable_key(graph.stable[*node as usize]));
    let mut candidates = HashMap::<u32, u64>::new();
    for _ in 0..policy.max_local_passes() {
        let mut changed = false;
        for &node in &order {
            let index = node as usize;
            let current = community[index];
            let degree = graph.degree[index];
            totals[current as usize] -= degree;
            candidates.clear();
            candidates.insert(current, graph.self_weight[index].saturating_mul(2));
            for neighbor in graph.neighbors(node) {
                *candidates
                    .entry(community[neighbor.node as usize])
                    .or_default() += neighbor.weight;
            }
            let mut best = current;
            let mut best_score = score(
                candidates.get(&current).copied().unwrap_or_default(),
                degree,
                totals[current as usize],
                graph.total_degree,
                policy.resolution_micros(),
            );
            for (&candidate, &inside) in &candidates {
                let candidate_score = score(
                    inside,
                    degree,
                    totals[candidate as usize],
                    graph.total_degree,
                    policy.resolution_micros(),
                );
                if candidate_score > best_score
                    || (candidate_score == best_score && candidate < best)
                {
                    best = candidate;
                    best_score = candidate_score;
                }
            }
            community[index] = best;
            totals[best as usize] = totals[best as usize].checked_add(degree).ok_or_else(|| {
                CommunityArtifactError::Invalid("community degree overflow".to_owned())
            })?;
            changed |= best != current;
        }
        if !changed {
            break;
        }
    }
    canonicalize_labels(&community, &graph.stable)
}

fn score(inside: u64, degree: u64, total: u64, graph_total: u64, resolution: u32) -> i128 {
    i128::from(inside) * i128::from(graph_total) * 1_000_000_i128
        - i128::from(resolution) * i128::from(degree) * i128::from(total)
}

fn deterministic_refinement(
    graph: &LevelGraph,
    coarse: &[u32],
    policy: &DeterministicCommunityPolicy,
) -> Result<Vec<u32>, CommunityArtifactError> {
    let count = coarse.len();
    let mut refined = (0..count as u32).collect::<Vec<_>>();
    let mut totals = graph.degree.clone();
    let mut sizes = vec![1_u32; count];
    let mut order = (0..count as u32).collect::<Vec<_>>();
    order.sort_unstable_by_key(|node| stable_key(graph.stable[*node as usize]));
    let mut candidates = HashMap::<u32, u64>::new();
    for &node in &order {
        let index = node as usize;
        let current = refined[index];
        if sizes[current as usize] != 1 {
            continue;
        }
        let degree = graph.degree[index];
        totals[current as usize] -= degree;
        candidates.clear();
        candidates.insert(current, graph.self_weight[index].saturating_mul(2));
        for neighbor in graph.neighbors(node) {
            if coarse[neighbor.node as usize] == coarse[index] {
                *candidates
                    .entry(refined[neighbor.node as usize])
                    .or_default() += neighbor.weight;
            }
        }
        let mut best = current;
        let mut best_score = score(
            candidates.get(&current).copied().unwrap_or_default(),
            degree,
            0,
            graph.total_degree,
            policy.resolution_micros(),
        );
        for (&candidate, &inside) in &candidates {
            if candidate == current {
                continue;
            }
            let candidate_score = score(
                inside,
                degree,
                totals[candidate as usize],
                graph.total_degree,
                policy.resolution_micros(),
            );
            if candidate_score > best_score || (candidate_score == best_score && candidate < best) {
                best = candidate;
                best_score = candidate_score;
            }
        }
        refined[index] = best;
        totals[best as usize] = totals[best as usize].checked_add(degree).ok_or_else(|| {
            CommunityArtifactError::Invalid("refined community degree overflow".to_owned())
        })?;
        if best != current {
            sizes[current as usize] = 0;
            sizes[best as usize] += 1;
        }
    }
    canonicalize_labels(&refined, &graph.stable)
}

fn aggregate(
    graph: &LevelGraph,
    partition: &[u32],
    count: usize,
) -> Result<LevelGraph, CommunityArtifactError> {
    let mut stable = vec![
        DiscoveryStableId {
            hash: 0,
            collision: 0
        };
        count
    ];
    let mut initialized = vec![false; count];
    let mut self_weight = vec![0_u64; count];
    for (node, &community) in partition.iter().enumerate() {
        let slot = community as usize;
        let identity = graph.stable[node];
        if !initialized[slot] || stable_key(identity) < stable_key(stable[slot]) {
            stable[slot] = identity;
            initialized[slot] = true;
        }
        self_weight[slot] = self_weight[slot]
            .checked_add(graph.self_weight[node])
            .ok_or_else(|| CommunityArtifactError::Invalid("self weight overflow".to_owned()))?;
    }
    let mut edges = Vec::with_capacity(graph.edges.len());
    for edge in &graph.edges {
        let source = partition[edge.source as usize];
        let target = partition[edge.target as usize];
        if source == target {
            self_weight[source as usize] = self_weight[source as usize]
                .checked_add(edge.weight)
                .ok_or_else(|| {
                    CommunityArtifactError::Invalid("internal weight overflow".to_owned())
                })?;
        } else {
            edges.push(WeightedEdge {
                source: source.min(target),
                target: source.max(target),
                weight: edge.weight,
            });
        }
    }
    edges.sort_unstable_by_key(|edge| (edge.source, edge.target));
    let mut collapsed: Vec<WeightedEdge> = Vec::with_capacity(edges.len());
    for edge in edges {
        if let Some(last) = collapsed.last_mut() {
            if (last.source, last.target) == (edge.source, edge.target) {
                last.weight = last.weight.checked_add(edge.weight).ok_or_else(|| {
                    CommunityArtifactError::Invalid("aggregate edge overflow".to_owned())
                })?;
                continue;
            }
        }
        collapsed.push(edge);
    }
    LevelGraph::new(stable, collapsed, self_weight)
}

impl LevelGraph {
    fn new(
        stable: Vec<DiscoveryStableId>,
        edges: Vec<WeightedEdge>,
        self_weight: Vec<u64>,
    ) -> Result<Self, CommunityArtifactError> {
        let count = stable.len();
        let mut degree = self_weight
            .iter()
            .map(|weight| weight.saturating_mul(2))
            .collect::<Vec<_>>();
        let mut counts = vec![0_u64; count];
        for edge in &edges {
            degree[edge.source as usize] += edge.weight;
            degree[edge.target as usize] += edge.weight;
            counts[edge.source as usize] += 1;
            counts[edge.target as usize] += 1;
        }
        let mut offsets = Vec::with_capacity(count + 1);
        offsets.push(0_u64);
        for value in counts {
            offsets.push(offsets.last().copied().unwrap() + value);
        }
        let mut neighbors = vec![Neighbor { node: 0, weight: 0 }; offsets[count] as usize];
        let mut cursor = offsets[..count].to_vec();
        for edge in &edges {
            let left = cursor[edge.source as usize] as usize;
            neighbors[left] = Neighbor {
                node: edge.target,
                weight: edge.weight,
            };
            cursor[edge.source as usize] += 1;
            let right = cursor[edge.target as usize] as usize;
            neighbors[right] = Neighbor {
                node: edge.source,
                weight: edge.weight,
            };
            cursor[edge.target as usize] += 1;
        }
        let total_degree = degree.iter().try_fold(0_u64, |sum, value| {
            sum.checked_add(*value)
                .ok_or_else(|| CommunityArtifactError::Invalid("graph degree overflow".to_owned()))
        })?;
        Ok(Self {
            stable,
            edges,
            self_weight,
            offsets,
            neighbors,
            degree,
            total_degree,
        })
    }

    fn neighbors(&self, node: u32) -> &[Neighbor] {
        let start = self.offsets[node as usize] as usize;
        let end = self.offsets[node as usize + 1] as usize;
        &self.neighbors[start..end]
    }
}

fn canonicalize_labels(
    labels: &[u32],
    stable: &[DiscoveryStableId],
) -> Result<Vec<u32>, CommunityArtifactError> {
    let nodes = (0..labels.len() as u32).collect::<Vec<_>>();
    canonicalize_partition(labels, &nodes, stable)
}

fn canonicalize_partition(
    labels: &[u32],
    nodes: &[u32],
    stable: &[DiscoveryStableId],
) -> Result<Vec<u32>, CommunityArtifactError> {
    let mut minima = HashMap::<u32, DiscoveryStableId>::new();
    for (index, &label) in labels.iter().enumerate() {
        let identity = stable[nodes[index] as usize];
        minima
            .entry(label)
            .and_modify(|current| {
                if stable_key(identity) < stable_key(*current) {
                    *current = identity;
                }
            })
            .or_insert(identity);
    }
    let mut labels_by_minimum = minima.into_iter().collect::<Vec<_>>();
    labels_by_minimum.sort_unstable_by_key(|(_, identity)| stable_key(*identity));
    if labels_by_minimum.len() > u32::MAX as usize {
        return Err(CommunityArtifactError::Invalid(
            "community count exceeds packed u32 capacity".to_owned(),
        ));
    }
    let remap = labels_by_minimum
        .into_iter()
        .enumerate()
        .map(|(dense, (old, _))| (old, dense as u32))
        .collect::<HashMap<_, _>>();
    Ok(labels.iter().map(|label| remap[label]).collect())
}
