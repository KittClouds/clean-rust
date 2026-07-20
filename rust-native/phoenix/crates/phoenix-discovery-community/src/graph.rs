use crate::{CommunityArtifactError, DeterministicCommunityPolicy};
use hashbrown::HashMap;
use phoenix_discovery_view::{AssertedDiscoveryView, DiscoveryRelationPolicy, DiscoveryStableId};
use rayon::prelude::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct WeightedEdge {
    pub source: u32,
    pub target: u32,
    pub weight: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Neighbor {
    pub node: u32,
    pub weight: u64,
}

pub(crate) struct SemanticCoreGraph {
    pub node_count: usize,
    pub stable: Vec<DiscoveryStableId>,
    pub core_nodes: Vec<u32>,
    pub component_of_node: Vec<u32>,
    pub component_offsets: Vec<u64>,
    pub component_nodes: Vec<u32>,
    pub edges: Vec<WeightedEdge>,
    offsets: Vec<u64>,
    neighbors: Vec<Neighbor>,
}

struct WeakComponentColumns {
    node_component: Vec<u32>,
    offsets: Vec<u64>,
    nodes: Vec<u32>,
}

impl SemanticCoreGraph {
    pub fn build(
        view: &AssertedDiscoveryView,
        relation_policy: &DiscoveryRelationPolicy,
        community_policy: &DeterministicCommunityPolicy,
    ) -> Result<Self, CommunityArtifactError> {
        relation_policy.validate()?;
        if view.manifest().relation_policy_digest != hex(&relation_policy.digest()?) {
            return Err(CommunityArtifactError::Invalid(
                "relation policy does not match the asserted discovery artifact".to_owned(),
            ));
        }
        if view.manifest().admitted_candidate_edges != 0 {
            return Err(CommunityArtifactError::Invalid(
                "community source admits candidate edges".to_owned(),
            ));
        }
        view.validate_payload()?;
        let node_count = view.node_count();
        ensure_u32(node_count, "node")?;
        let mut stable = Vec::with_capacity(node_count);
        let mut core = vec![false; node_count];
        let mut core_nodes = Vec::new();
        for (node, is_core) in core.iter_mut().enumerate() {
            let dense = node as u32;
            stable.push(view.node_identity(dense)?);
            if DeterministicCommunityPolicy::is_core_node(view.node_kind(dense)?) {
                *is_core = true;
                core_nodes.push(dense);
            }
        }
        core_nodes.par_sort_unstable_by_key(|node| stable_key(stable[*node as usize]));

        let relation_weights = view
            .manifest()
            .relations
            .iter()
            .filter_map(|entry| {
                community_policy
                    .relation_weight_millis(entry.family, &entry.relation, relation_policy)
                    .map(|weight| (entry.code, weight))
            })
            .collect::<HashMap<_, _>>();
        let mut edges = Vec::new();
        for edge_index in 0..view.edge_count() {
            let edge = view.edge(edge_index as u32)?;
            if edge.source == edge.target
                || !core[edge.source as usize]
                || !core[edge.target as usize]
            {
                continue;
            }
            let Some(&relation_weight) = relation_weights.get(&edge.relation_code) else {
                continue;
            };
            let confidence_millis = (f64::from(edge.confidence) * 1_000.0).round() as u64;
            let weight = u64::from(relation_weight)
                .checked_mul(confidence_millis)
                .ok_or_else(|| {
                    CommunityArtifactError::Invalid("semantic edge weight overflow".to_owned())
                })?;
            if weight == 0 {
                continue;
            }
            edges.push(WeightedEdge {
                source: edge.source.min(edge.target),
                target: edge.source.max(edge.target),
                weight,
            });
        }
        edges.par_sort_unstable_by_key(|edge| (edge.source, edge.target));
        edges = collapse_parallel(edges)?;
        let (offsets, neighbors) = adjacency(node_count, &edges)?;
        let components = weak_components(node_count, &core_nodes, &edges, &stable)?;
        Ok(Self {
            node_count,
            stable,
            core_nodes,
            component_of_node: components.node_component,
            component_offsets: components.offsets,
            component_nodes: components.nodes,
            edges,
            offsets,
            neighbors,
        })
    }

    pub fn neighbors(&self, node: u32) -> &[Neighbor] {
        let start = self.offsets[node as usize] as usize;
        let end = self.offsets[node as usize + 1] as usize;
        &self.neighbors[start..end]
    }

    pub fn component_count(&self) -> usize {
        self.component_offsets.len().saturating_sub(1)
    }

    pub fn component_nodes(&self, component: usize) -> &[u32] {
        let start = self.component_offsets[component] as usize;
        let end = self.component_offsets[component + 1] as usize;
        &self.component_nodes[start..end]
    }
}

fn collapse_parallel(
    edges: Vec<WeightedEdge>,
) -> Result<Vec<WeightedEdge>, CommunityArtifactError> {
    let mut collapsed: Vec<WeightedEdge> = Vec::with_capacity(edges.len());
    for edge in edges {
        if let Some(last) = collapsed.last_mut() {
            if (last.source, last.target) == (edge.source, edge.target) {
                last.weight = last.weight.checked_add(edge.weight).ok_or_else(|| {
                    CommunityArtifactError::Invalid("parallel edge weight overflow".to_owned())
                })?;
                continue;
            }
        }
        collapsed.push(edge);
    }
    Ok(collapsed)
}

fn adjacency(
    node_count: usize,
    edges: &[WeightedEdge],
) -> Result<(Vec<u64>, Vec<Neighbor>), CommunityArtifactError> {
    let mut counts = vec![0_u64; node_count];
    for edge in edges {
        counts[edge.source as usize] += 1;
        counts[edge.target as usize] += 1;
    }
    let mut offsets = Vec::with_capacity(node_count + 1);
    offsets.push(0_u64);
    for count in counts {
        let next = offsets
            .last()
            .copied()
            .unwrap()
            .checked_add(count)
            .ok_or_else(|| {
                CommunityArtifactError::Invalid("adjacency offset overflow".to_owned())
            })?;
        offsets.push(next);
    }
    let mut neighbors = vec![Neighbor { node: 0, weight: 0 }; offsets[node_count] as usize];
    let mut cursor = offsets[..node_count].to_vec();
    for edge in edges {
        let source = cursor[edge.source as usize] as usize;
        neighbors[source] = Neighbor {
            node: edge.target,
            weight: edge.weight,
        };
        cursor[edge.source as usize] += 1;
        let target = cursor[edge.target as usize] as usize;
        neighbors[target] = Neighbor {
            node: edge.source,
            weight: edge.weight,
        };
        cursor[edge.target as usize] += 1;
    }
    Ok((offsets, neighbors))
}

fn weak_components(
    node_count: usize,
    core_nodes: &[u32],
    edges: &[WeightedEdge],
    stable: &[DiscoveryStableId],
) -> Result<WeakComponentColumns, CommunityArtifactError> {
    let mut parent = (0..node_count as u32).collect::<Vec<_>>();
    for edge in edges {
        union(&mut parent, edge.source, edge.target, stable);
    }
    let mut rows = Vec::with_capacity(core_nodes.len());
    for &node in core_nodes {
        let root = find(&mut parent, node);
        rows.push((root, node));
    }
    rows.par_sort_unstable_by_key(|(root, node)| {
        (
            stable_key(stable[*root as usize]),
            stable_key(stable[*node as usize]),
        )
    });
    let mut component_of_node = vec![u32::MAX; node_count];
    let mut component_offsets = vec![0_u64];
    let mut component_nodes = Vec::with_capacity(rows.len());
    let mut previous_root = None;
    let mut component = 0_u32;
    let mut next_component = 0_u32;
    for (root, node) in rows {
        if previous_root != Some(root) {
            if previous_root.is_some() {
                component_offsets.push(component_nodes.len() as u64);
            }
            component = next_component;
            next_component = next_component.checked_add(1).ok_or_else(|| {
                CommunityArtifactError::Invalid("component count exceeds u32".to_owned())
            })?;
            previous_root = Some(root);
        }
        component_of_node[node as usize] = component;
        component_nodes.push(node);
    }
    if previous_root.is_some() {
        component_offsets.push(component_nodes.len() as u64);
    }
    Ok(WeakComponentColumns {
        node_component: component_of_node,
        offsets: component_offsets,
        nodes: component_nodes,
    })
}

fn find(parent: &mut [u32], node: u32) -> u32 {
    let mut root = node;
    while parent[root as usize] != root {
        root = parent[root as usize];
    }
    let mut current = node;
    while parent[current as usize] != current {
        let next = parent[current as usize];
        parent[current as usize] = root;
        current = next;
    }
    root
}

fn union(parent: &mut [u32], left: u32, right: u32, stable: &[DiscoveryStableId]) {
    let left = find(parent, left);
    let right = find(parent, right);
    if left == right {
        return;
    }
    let (keep, merge) = if stable_key(stable[left as usize]) <= stable_key(stable[right as usize]) {
        (left, right)
    } else {
        (right, left)
    };
    parent[merge as usize] = keep;
}

pub(crate) const fn stable_key(identity: DiscoveryStableId) -> (u64, u16) {
    (identity.hash, identity.collision)
}

fn ensure_u32(value: usize, kind: &str) -> Result<(), CommunityArtifactError> {
    if value > u32::MAX as usize {
        return Err(CommunityArtifactError::Invalid(format!(
            "{kind} count exceeds packed u32 capacity"
        )));
    }
    Ok(())
}

fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
