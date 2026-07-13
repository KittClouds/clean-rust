use crate::{
    certify_evaluation_protocol, DerivedFeatureCertificate, DerivedFeatureRow,
    FrozenGraphResearchSnapshot, FrozenTensorSnapshot, ResearchAuthority, ResearchEvaluationError,
    ResearchEvaluationProtocol, ResearchSplit, TrainTopologyAudit, TrainTopologyFeaturePolicy,
    TrainTopologyFeatureSnapshot, PROPOSAL_FEATURE_DIM, TRAIN_TOPOLOGY_FEATURE_SCHEMA,
};
use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use serde::Serialize;

#[derive(Clone, Copy)]
struct AdjEdge {
    other: u32,
    relation: u32,
    index: u32,
}

struct FlatAdjacency {
    offsets: Vec<usize>,
    rows: Vec<AdjEdge>,
}

impl FlatAdjacency {
    fn rows(&self, node: u32) -> &[AdjEdge] {
        &self.rows[self.offsets[node as usize]..self.offsets[node as usize + 1]]
    }
}

pub fn derive_train_topology_features(
    source: &FrozenGraphResearchSnapshot,
    tensors: &FrozenTensorSnapshot,
    protocol: &ResearchEvaluationProtocol,
    policy: TrainTopologyFeaturePolicy,
) -> Result<TrainTopologyFeatureSnapshot, ResearchEvaluationError> {
    policy.validate()?;
    let certified = certify_evaluation_protocol(source, tensors, protocol.policy.clone())?;
    if certified != *protocol {
        return Err(ResearchEvaluationError::Leakage(
            "evaluation protocol drift",
        ));
    }
    let (outgoing, incoming, train_edges, topology_blake3, latest_fit_edge_ms) =
        build_train_adjacency(tensors, protocol.split_policy.train_through_ms)?;
    let link_rows = derive_link_rows(tensors, &outgoing, &incoming);
    let incidence_rows = derive_incidence_rows(tensors, &outgoing, &incoming, policy);
    let fit_incidences = tensors
        .incidence_splits
        .iter()
        .zip(&tensors.incidence_resolved)
        .filter(|(split, resolved)| **split == ResearchSplit::Train && **resolved)
        .count();
    let audit = TrainTopologyAudit {
        fit_edges: train_edges as u64,
        fit_incidences: fit_incidences as u64,
        link_examples: link_rows.len() as u64,
        incidence_examples: incidence_rows.len() as u64,
        latest_fit_edge_ms,
        topology_blake3,
        train_only: true,
        asserted_edges_only: true,
        resolved_incidences_only: true,
        leave_one_positive_out: true,
    };
    let mut snapshot = TrainTopologyFeatureSnapshot {
        schema_version: TRAIN_TOPOLOGY_FEATURE_SCHEMA.into(),
        derivation_id: "pending".into(),
        source_dataset_id: tensors.source_dataset_id.clone(),
        source_tensor_id: tensors.tensor_id.clone(),
        evaluation_protocol_id: protocol.protocol_id.clone(),
        policy,
        audit,
        feature_certificates: feature_certificates(protocol.split_policy.train_through_ms),
        link_rows,
        incidence_rows,
    };
    snapshot.derivation_id = content_id(&snapshot)?;
    Ok(snapshot)
}

type AdjacencyBuild = (
    FlatAdjacency,
    FlatAdjacency,
    usize,
    CompactString,
    Option<i64>,
);

fn build_train_adjacency(
    tensors: &FrozenTensorSnapshot,
    train_through_ms: i64,
) -> Result<AdjacencyBuild, ResearchEvaluationError> {
    let node_count = tensors.node_ids.len();
    let mut train_indices = Vec::new();
    let mut out_counts = vec![0_usize; node_count];
    let mut in_counts = vec![0_usize; node_count];
    let mut digest = blake3::Hasher::new();
    let mut count = 0_usize;
    let mut latest = None;
    for index in 0..tensors.coo_sources.len() {
        if tensors.coo_splits[index] != ResearchSplit::Train
            || tensors.coo_authority[index] != ResearchAuthority::Asserted
        {
            continue;
        }
        let time = tensors.coo_available_at_ms[index];
        if time > train_through_ms {
            return Err(ResearchEvaluationError::Leakage("future train edge"));
        }
        let source = tensors.coo_sources[index] as usize;
        let target = tensors.coo_targets[index] as usize;
        let relation = tensors.coo_relation_types[index];
        if source >= node_count || target >= node_count {
            return Err(ResearchEvaluationError::TensorShape("train adjacency"));
        }
        out_counts[source] += 1;
        in_counts[target] += 1;
        train_indices.push(index as u32);
        digest.update(&(source as u32).to_le_bytes());
        digest.update(&(target as u32).to_le_bytes());
        digest.update(&relation.to_le_bytes());
        digest.update(&time.to_le_bytes());
        latest = Some(latest.map_or(time, |value: i64| value.max(time)));
        count += 1;
    }
    for index in 0..tensors.incidence_hyperedges.len() {
        if tensors.incidence_splits[index] == ResearchSplit::Train
            && tensors.incidence_resolved[index]
        {
            digest.update(&tensors.incidence_hyperedges[index].to_le_bytes());
            digest.update(&tensors.incidence_participants[index].to_le_bytes());
            digest.update(&tensors.incidence_role_types[index].to_le_bytes());
        }
    }
    let outgoing = flat_adjacency(tensors, &train_indices, out_counts, false);
    let incoming = flat_adjacency(tensors, &train_indices, in_counts, true);
    Ok((
        outgoing,
        incoming,
        count,
        format_compact!("b3-{}", digest.finalize().to_hex()),
        latest,
    ))
}

fn flat_adjacency(
    tensors: &FrozenTensorSnapshot,
    train_indices: &[u32],
    counts: Vec<usize>,
    reverse: bool,
) -> FlatAdjacency {
    let mut offsets = Vec::with_capacity(counts.len() + 1);
    offsets.push(0);
    for count in counts {
        offsets.push(offsets.last().copied().unwrap_or(0) + count);
    }
    let mut rows = vec![
        AdjEdge {
            other: 0,
            relation: 0,
            index: 0,
        };
        train_indices.len()
    ];
    let mut cursors = offsets[..offsets.len() - 1].to_vec();
    for &edge in train_indices {
        let index = edge as usize;
        let (owner, other) = if reverse {
            (tensors.coo_targets[index], tensors.coo_sources[index])
        } else {
            (tensors.coo_sources[index], tensors.coo_targets[index])
        };
        let cursor = &mut cursors[owner as usize];
        rows[*cursor] = AdjEdge {
            other,
            relation: tensors.coo_relation_types[index],
            index: edge,
        };
        *cursor += 1;
    }
    for node in 0..offsets.len() - 1 {
        rows[offsets[node]..offsets[node + 1]]
            .sort_unstable_by_key(|row| (row.other, row.relation, row.index));
    }
    FlatAdjacency { offsets, rows }
}

fn derive_link_rows(
    tensors: &FrozenTensorSnapshot,
    outgoing: &FlatAdjacency,
    incoming: &FlatAdjacency,
) -> Vec<DerivedFeatureRow> {
    let mut negatives = vec![Vec::new(); tensors.coo_sources.len()];
    for row in &tensors.negatives {
        if let Some(bucket) = negatives.get_mut(row.positive_edge as usize) {
            bucket.push(row.target);
        }
    }
    let mut rows = Vec::with_capacity(tensors.coo_sources.len() + tensors.negatives.len());
    for (edge, edge_negatives) in negatives.iter().enumerate() {
        if tensors.coo_authority[edge] != ResearchAuthority::Asserted {
            continue;
        }
        let excluded = (tensors.coo_splits[edge] == ResearchSplit::Train).then_some(edge as u32);
        let source = tensors.coo_sources[edge];
        let target = tensors.coo_targets[edge];
        let relation = tensors.coo_relation_types[edge];
        rows.push(DerivedFeatureRow {
            positive_index: edge as u32,
            candidate: target,
            split: tensors.coo_splits[edge],
            label: true,
            features: link_features(source, target, relation, excluded, outgoing, incoming),
        });
        for &candidate in edge_negatives {
            rows.push(DerivedFeatureRow {
                positive_index: edge as u32,
                candidate,
                split: tensors.coo_splits[edge],
                label: false,
                features: link_features(source, candidate, relation, excluded, outgoing, incoming),
            });
        }
    }
    rows
}

fn link_features(
    source: u32,
    target: u32,
    relation: u32,
    excluded: Option<u32>,
    outgoing: &FlatAdjacency,
    incoming: &FlatAdjacency,
) -> [f32; PROPOSAL_FEATURE_DIM] {
    let source_out = degree(outgoing.rows(source), excluded);
    let source_in = degree(incoming.rows(source), excluded);
    let target_out = degree(outgoing.rows(target), excluded);
    let target_in = degree(incoming.rows(target), excluded);
    let mut values = [0.0; PROPOSAL_FEATURE_DIM];
    values[0] = count_feature(source_out);
    values[1] = count_feature(target_in);
    values[2] = count_feature(source_in);
    values[3] = count_feature(target_out);
    values[4] = count_feature(relation_degree(outgoing.rows(source), relation, excluded));
    values[5] = count_feature(relation_degree(incoming.rows(target), relation, excluded));
    values[6] = count_feature(common_neighbors(
        outgoing.rows(source),
        outgoing.rows(target),
        excluded,
    ));
    values[7] = count_feature(common_neighbors(
        incoming.rows(source),
        incoming.rows(target),
        excluded,
    ));
    values[8] = f32::from(has_edge(outgoing.rows(target), source, excluded));
    values[9] = f32::from(has_edge(outgoing.rows(source), target, excluded));
    values[10] = count_feature(source_out.saturating_mul(target_in));
    values[11] = f32::from(source == target);
    values
}

fn derive_incidence_rows(
    tensors: &FrozenTensorSnapshot,
    outgoing: &FlatAdjacency,
    incoming: &FlatAdjacency,
    policy: TrainTopologyFeaturePolicy,
) -> Vec<DerivedFeatureRow> {
    let mut participant_degree = vec![0_u32; tensors.node_ids.len()];
    let mut hyperedge_degree = vec![0_u32; tensors.node_ids.len()];
    let mut participant_role = HashMap::<(u32, u32), u32>::new();
    let mut role_degree = vec![0_u32; tensors.role_vocabulary.len()];
    for index in 0..tensors.incidence_hyperedges.len() {
        if tensors.incidence_splits[index] == ResearchSplit::Train
            && tensors.incidence_resolved[index]
        {
            participant_degree[tensors.incidence_participants[index] as usize] += 1;
            hyperedge_degree[tensors.incidence_hyperedges[index] as usize] += 1;
            role_degree[tensors.incidence_role_types[index] as usize] += 1;
            *participant_role
                .entry((
                    tensors.incidence_participants[index],
                    tensors.incidence_role_types[index],
                ))
                .or_default() += 1;
        }
    }
    let existing = (0..tensors.incidence_hyperedges.len())
        .map(|index| {
            (
                tensors.incidence_hyperedges[index],
                tensors.incidence_participants[index],
                tensors.incidence_role_types[index],
            )
        })
        .collect::<HashSet<_>>();
    let mut by_type = vec![Vec::new(); tensors.node_type_vocabulary.len()];
    for node in 0..tensors.node_ids.len() {
        if tensors.node_authority[node] == ResearchAuthority::Asserted {
            by_type[tensors.node_type_ids[node] as usize].push(node as u32);
        }
    }
    let mut rows = Vec::new();
    for incidence in 0..tensors.incidence_hyperedges.len() {
        if !tensors.incidence_resolved[incidence] {
            continue;
        }
        let hyperedge = tensors.incidence_hyperedges[incidence];
        let participant = tensors.incidence_participants[incidence];
        let role = tensors.incidence_role_types[incidence];
        let split = tensors.incidence_splits[incidence];
        let excluded = (split == ResearchSplit::Train).then_some((participant, role));
        rows.push(DerivedFeatureRow {
            positive_index: incidence as u32,
            candidate: participant,
            split,
            label: true,
            features: incidence_features(
                participant,
                hyperedge,
                role,
                excluded,
                &participant_degree,
                &hyperedge_degree,
                &participant_role,
                &role_degree,
                outgoing,
                incoming,
            ),
        });
        let pool = &by_type[tensors.node_type_ids[participant as usize] as usize];
        let (mut cursor, step) = permutation(&tensors.tensor_id, incidence as u32, pool.len());
        let mut accepted = 0_u8;
        for _ in 0..pool.len() {
            let candidate = pool[cursor];
            cursor = (cursor + step) % pool.len().max(1);
            if candidate == participant
                || tensors.node_splits[candidate as usize] as u8 > split as u8
                || existing.contains(&(hyperedge, candidate, role))
            {
                continue;
            }
            rows.push(DerivedFeatureRow {
                positive_index: incidence as u32,
                candidate,
                split,
                label: false,
                features: incidence_features(
                    candidate,
                    hyperedge,
                    role,
                    excluded,
                    &participant_degree,
                    &hyperedge_degree,
                    &participant_role,
                    &role_degree,
                    outgoing,
                    incoming,
                ),
            });
            accepted += 1;
            if accepted == policy.incidence_negatives_per_positive {
                break;
            }
        }
    }
    rows
}

#[allow(clippy::too_many_arguments)]
fn incidence_features(
    participant: u32,
    hyperedge: u32,
    role: u32,
    excluded: Option<(u32, u32)>,
    participant_degree: &[u32],
    hyperedge_degree: &[u32],
    participant_role: &HashMap<(u32, u32), u32>,
    role_degree: &[u32],
    outgoing: &FlatAdjacency,
    incoming: &FlatAdjacency,
) -> [f32; PROPOSAL_FEATURE_DIM] {
    let subtract = u32::from(excluded == Some((participant, role)));
    let mut values = [0.0; PROPOSAL_FEATURE_DIM];
    values[0] = count_feature(participant_degree[participant as usize].saturating_sub(subtract));
    values[1] = count_feature(
        participant_role
            .get(&(participant, role))
            .copied()
            .unwrap_or(0)
            .saturating_sub(subtract),
    );
    values[2] = count_feature(
        hyperedge_degree[hyperedge as usize].saturating_sub(u32::from(excluded.is_some())),
    );
    values[3] = count_feature(role_degree[role as usize].saturating_sub(subtract));
    values[4] = count_feature(outgoing.rows(participant).len() as u32);
    values[5] = count_feature(incoming.rows(participant).len() as u32);
    values[6] = count_feature(outgoing.rows(hyperedge).len() as u32);
    values[7] = count_feature(incoming.rows(hyperedge).len() as u32);
    values
}

fn degree(rows: &[AdjEdge], excluded: Option<u32>) -> u32 {
    rows.len() as u32 - u32::from(rows.iter().any(|row| Some(row.index) == excluded))
}

fn relation_degree(rows: &[AdjEdge], relation: u32, excluded: Option<u32>) -> u32 {
    rows.iter()
        .filter(|row| row.relation == relation && Some(row.index) != excluded)
        .count() as u32
}

fn has_edge(rows: &[AdjEdge], target: u32, excluded: Option<u32>) -> bool {
    rows.iter()
        .any(|row| row.other == target && Some(row.index) != excluded)
}

fn common_neighbors(left: &[AdjEdge], right: &[AdjEdge], excluded: Option<u32>) -> u32 {
    let mut count = 0_u32;
    let mut previous = None;
    for row in left.iter().filter(|row| Some(row.index) != excluded) {
        if previous == Some(row.other) {
            continue;
        }
        previous = Some(row.other);
        count += u32::from(has_edge(right, row.other, excluded));
    }
    count
}

fn count_feature(value: u32) -> f32 {
    (value as f32).ln_1p()
}

fn permutation(identity: &str, index: u32, count: usize) -> (usize, usize) {
    if count <= 1 {
        return (0, 1);
    }
    let mut hasher = blake3::Hasher::new();
    hasher.update(identity.as_bytes());
    hasher.update(&index.to_le_bytes());
    let digest = hasher.finalize();
    let start =
        u64::from_le_bytes(digest.as_bytes()[..8].try_into().expect("digest")) as usize % count;
    let mut step =
        (u64::from_le_bytes(digest.as_bytes()[8..16].try_into().expect("digest")) as usize % count)
            .max(1);
    while gcd(step, count) != 1 {
        step = step % (count - 1) + 1;
    }
    (start, step)
}

fn gcd(mut left: usize, mut right: usize) -> usize {
    while right != 0 {
        (left, right) = (right, left % right);
    }
    left
}

fn feature_certificates(train_through_ms: i64) -> Vec<DerivedFeatureCertificate> {
    let link = [
        "source_out_degree",
        "target_in_degree",
        "source_in_degree",
        "target_out_degree",
        "source_relation_out_degree",
        "target_relation_in_degree",
        "common_out_neighbors",
        "common_in_neighbors",
        "reciprocal_edge",
        "direct_edge",
        "preferential_attachment",
        "self_loop",
        "reserved_12",
        "reserved_13",
        "reserved_14",
        "reserved_15",
    ];
    let incidence = [
        "participant_incidence_degree",
        "participant_role_degree",
        "hyperedge_incidence_degree",
        "role_global_degree",
        "participant_graph_out_degree",
        "participant_graph_in_degree",
        "hyperedge_graph_out_degree",
        "hyperedge_graph_in_degree",
        "reserved_8",
        "reserved_9",
        "reserved_10",
        "reserved_11",
        "reserved_12",
        "reserved_13",
        "reserved_14",
        "reserved_15",
    ];
    let mut rows = Vec::with_capacity(32);
    for (task, schema, names) in [
        (
            "typed-link-prediction/v1",
            "train-topology-link-features/v1",
            link,
        ),
        (
            "hyperedge-role-completion/v1",
            "train-topology-incidence-features/v1",
            incidence,
        ),
    ] {
        for (column, name) in names.into_iter().enumerate() {
            rows.push(DerivedFeatureCertificate {
                task_id: task.into(),
                feature_schema_id: schema.into(),
                column: column as u16,
                name: name.into(),
                dtype: "f32-le".into(),
                transform: if name.starts_with("reserved") {
                    "constant-zero"
                } else if name.ends_with("edge") || name == "self_loop" {
                    "boolean"
                } else {
                    "ln1p-count"
                }
                .into(),
                fit_split: ResearchSplit::Train,
                fit_through_ms: train_through_ms,
                leave_one_positive_out: true,
                label_free: true,
            });
        }
    }
    rows
}

fn content_id(value: &impl Serialize) -> Result<CompactString, ResearchEvaluationError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
