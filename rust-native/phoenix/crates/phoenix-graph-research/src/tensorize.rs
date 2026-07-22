use crate::{
    FeatureColumnCertificate, FrozenGraphResearchError, FrozenGraphResearchSnapshot,
    FrozenTensorSnapshot, ResearchAuthority, TensorizationPolicy, TypedNegativeSample,
    PROPOSAL_FEATURE_DIM,
};
use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use serde::Serialize;
use std::collections::BTreeSet;

type CsrArrays = (Vec<u64>, Vec<u32>, Vec<u32>);

pub fn tensorize_frozen_graph(
    source: &FrozenGraphResearchSnapshot,
    policy: TensorizationPolicy,
) -> Result<FrozenTensorSnapshot, FrozenGraphResearchError> {
    policy.validate()?;
    validate_source(source)?;
    let node_type_vocabulary = vocabulary(source.nodes.iter().map(|node| node.kind.as_str()));
    let relation_vocabulary = vocabulary(source.edges.iter().map(|edge| edge.relation.as_str()));
    let role_vocabulary = vocabulary(source.incidences.iter().map(|row| row.role.as_str()));
    let feature_schema_vocabulary = vocabulary(
        source
            .proposals
            .iter()
            .map(|row| row.feature_schema_id.as_str()),
    );
    let node_type_index = vocabulary_index(&node_type_vocabulary);
    let relation_index = vocabulary_index(&relation_vocabulary);
    let role_index = vocabulary_index(&role_vocabulary);
    let feature_schema_index = vocabulary_index(&feature_schema_vocabulary);

    let node_ids = source.nodes.iter().map(|node| node.id.clone()).collect();
    let node_type_ids = source
        .nodes
        .iter()
        .map(|node| indexed(&node_type_index, &node.kind))
        .collect::<Result<Vec<_>, _>>()?;
    let node_authority = source.nodes.iter().map(|node| node.authority).collect();
    let node_splits = source.nodes.iter().map(|node| node.split).collect();
    let node_available_at_ms = source
        .nodes
        .iter()
        .map(|node| node.available_at_ms)
        .collect();

    let mut ordered_edges = source.edges.iter().enumerate().collect::<Vec<_>>();
    ordered_edges.sort_unstable_by(|left, right| {
        left.1
            .source
            .cmp(&right.1.source)
            .then_with(|| left.1.relation.cmp(&right.1.relation))
            .then_with(|| left.1.target.cmp(&right.1.target))
            .then_with(|| authority_rank(left.1.authority).cmp(&authority_rank(right.1.authority)))
            .then_with(|| left.0.cmp(&right.0))
    });
    let mut coo_sources = Vec::with_capacity(ordered_edges.len());
    let mut coo_targets = Vec::with_capacity(ordered_edges.len());
    let mut coo_relation_types = Vec::with_capacity(ordered_edges.len());
    let mut coo_authority = Vec::with_capacity(ordered_edges.len());
    let mut coo_splits = Vec::with_capacity(ordered_edges.len());
    let mut coo_available_at_ms = Vec::with_capacity(ordered_edges.len());
    let mut coo_weights = Vec::with_capacity(ordered_edges.len());
    for (_, edge) in ordered_edges {
        coo_sources.push(edge.source);
        coo_targets.push(edge.target);
        coo_relation_types.push(indexed(&relation_index, &edge.relation)?);
        coo_authority.push(edge.authority);
        coo_splits.push(edge.split);
        coo_available_at_ms.push(edge.available_at_ms);
        coo_weights.push(edge.weight);
    }
    let (csr_row_offsets, csr_columns, csr_edge_indices) =
        build_csr(source.nodes.len(), &coo_sources, &coo_targets)?;

    let incidence_hyperedges = source.incidences.iter().map(|row| row.hyperedge).collect();
    let incidence_participants = source
        .incidences
        .iter()
        .map(|row| row.participant)
        .collect();
    let incidence_role_types = source
        .incidences
        .iter()
        .map(|row| indexed(&role_index, &row.role))
        .collect::<Result<Vec<_>, _>>()?;
    let incidence_splits = source.incidences.iter().map(|row| row.split).collect();
    let incidence_resolved = source.incidences.iter().map(|row| row.resolved).collect();

    let proposal_features = source
        .proposals
        .iter()
        .flat_map(|row| row.features)
        .collect();
    let proposal_labels = source.proposals.iter().map(|row| row.label).collect();
    let proposal_label_observed = source
        .proposals
        .iter()
        .map(|row| row.label != crate::ResearchProposalLabel::Uncommitted)
        .collect();
    let proposal_splits = source.proposals.iter().map(|row| row.split).collect();
    let proposal_observed_at_ms = source
        .proposals
        .iter()
        .map(|row| row.observed_at_ms)
        .collect();
    let proposal_label_available_at_ms = source
        .proposals
        .iter()
        .map(|row| row.label_available_at_ms)
        .collect();
    let proposal_feature_schema_ids = source
        .proposals
        .iter()
        .map(|row| indexed(&feature_schema_index, &row.feature_schema_id))
        .collect::<Result<Vec<_>, _>>()?;
    let feature_certificates = feature_certificates(&feature_schema_vocabulary);
    let negatives = build_negatives(
        source,
        &node_type_ids,
        &coo_sources,
        &coo_targets,
        &coo_relation_types,
        &coo_authority,
        &coo_splits,
        &coo_available_at_ms,
        policy,
    );
    let mut tensor_hasher = blake3::Hasher::new();
    hash_json(&mut tensor_hasher, source.dataset_id.as_str())?;
    hash_json(&mut tensor_hasher, &policy)?;
    hash_json(&mut tensor_hasher, &node_ids)?;
    hash_json(&mut tensor_hasher, &node_type_vocabulary)?;
    hash_json(&mut tensor_hasher, &relation_vocabulary)?;
    hash_json(&mut tensor_hasher, &role_vocabulary)?;
    hash_json(&mut tensor_hasher, &feature_schema_vocabulary)?;
    hash_json(&mut tensor_hasher, &node_type_ids)?;
    hash_json(&mut tensor_hasher, &node_authority)?;
    hash_json(&mut tensor_hasher, &node_splits)?;
    hash_json(&mut tensor_hasher, &node_available_at_ms)?;
    hash_json(&mut tensor_hasher, &coo_sources)?;
    hash_json(&mut tensor_hasher, &coo_targets)?;
    hash_json(&mut tensor_hasher, &coo_relation_types)?;
    hash_json(&mut tensor_hasher, &coo_authority)?;
    hash_json(&mut tensor_hasher, &coo_splits)?;
    hash_json(&mut tensor_hasher, &coo_available_at_ms)?;
    hash_json(&mut tensor_hasher, &coo_weights)?;
    hash_json(&mut tensor_hasher, &csr_row_offsets)?;
    hash_json(&mut tensor_hasher, &incidence_hyperedges)?;
    hash_json(&mut tensor_hasher, &incidence_participants)?;
    hash_json(&mut tensor_hasher, &incidence_role_types)?;
    hash_json(&mut tensor_hasher, &incidence_splits)?;
    hash_json(&mut tensor_hasher, &incidence_resolved)?;
    hash_json(&mut tensor_hasher, &proposal_features)?;
    hash_json(&mut tensor_hasher, &proposal_labels)?;
    hash_json(&mut tensor_hasher, &proposal_label_observed)?;
    hash_json(&mut tensor_hasher, &proposal_splits)?;
    hash_json(&mut tensor_hasher, &proposal_observed_at_ms)?;
    hash_json(&mut tensor_hasher, &proposal_label_available_at_ms)?;
    hash_json(&mut tensor_hasher, &proposal_feature_schema_ids)?;
    hash_json(&mut tensor_hasher, &feature_certificates)?;
    hash_json(&mut tensor_hasher, &negatives)?;
    let tensor_id = tensor_hasher.finalize().to_hex().to_string();
    Ok(FrozenTensorSnapshot {
        tensor_id: format_compact!("b3-{tensor_id}"),
        source_dataset_id: source.dataset_id.clone(),
        policy,
        node_ids,
        node_type_vocabulary,
        relation_vocabulary,
        role_vocabulary,
        feature_schema_vocabulary,
        node_type_ids,
        node_authority,
        node_splits,
        node_available_at_ms,
        coo_sources,
        coo_targets,
        coo_relation_types,
        coo_authority,
        coo_splits,
        coo_available_at_ms,
        coo_weights,
        csr_row_offsets,
        csr_columns,
        csr_edge_indices,
        incidence_hyperedges,
        incidence_participants,
        incidence_role_types,
        incidence_splits,
        incidence_resolved,
        proposal_features,
        proposal_labels,
        proposal_label_observed,
        proposal_splits,
        proposal_observed_at_ms,
        proposal_label_available_at_ms,
        proposal_feature_schema_ids,
        feature_certificates,
        negatives,
    })
}

fn validate_source(source: &FrozenGraphResearchSnapshot) -> Result<(), FrozenGraphResearchError> {
    let node_count = source.nodes.len();
    for edge in &source.edges {
        if edge.source as usize >= node_count || edge.target as usize >= node_count {
            return Err(FrozenGraphResearchError::CorruptArtifact(
                "tensor source edge bounds",
            ));
        }
        if source.nodes[edge.source as usize].available_at_ms > edge.available_at_ms
            || source.nodes[edge.target as usize].available_at_ms > edge.available_at_ms
        {
            return Err(FrozenGraphResearchError::FutureGraphData);
        }
    }
    for row in &source.incidences {
        if row.hyperedge as usize >= node_count || row.participant as usize >= node_count {
            return Err(FrozenGraphResearchError::CorruptArtifact(
                "tensor source incidence bounds",
            ));
        }
    }
    Ok(())
}

fn vocabulary<'a>(values: impl Iterator<Item = &'a str>) -> Vec<CompactString> {
    values
        .map(CompactString::new)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn vocabulary_index(values: &[CompactString]) -> HashMap<CompactString, u32> {
    values
        .iter()
        .enumerate()
        .map(|(index, value)| (value.clone(), index as u32))
        .collect()
}

fn indexed(
    index: &HashMap<CompactString, u32>,
    value: &CompactString,
) -> Result<u32, FrozenGraphResearchError> {
    index
        .get(value)
        .copied()
        .ok_or(FrozenGraphResearchError::CorruptArtifact(
            "vocabulary lookup",
        ))
}

fn build_csr(
    node_count: usize,
    sources: &[u32],
    targets: &[u32],
) -> Result<CsrArrays, FrozenGraphResearchError> {
    let mut offsets = vec![0_u64; node_count + 1];
    for &source in sources {
        let slot = offsets
            .get_mut(source as usize + 1)
            .ok_or(FrozenGraphResearchError::CorruptArtifact("csr source"))?;
        *slot += 1;
    }
    for index in 1..offsets.len() {
        offsets[index] += offsets[index - 1];
    }
    Ok((
        offsets,
        targets.to_vec(),
        (0..sources.len() as u32).collect(),
    ))
}

#[allow(clippy::too_many_arguments)]
fn build_negatives(
    source: &FrozenGraphResearchSnapshot,
    node_type_ids: &[u32],
    edge_sources: &[u32],
    edge_targets: &[u32],
    relation_types: &[u32],
    authorities: &[ResearchAuthority],
    splits: &[crate::ResearchSplit],
    available_at: &[i64],
    policy: TensorizationPolicy,
) -> Vec<TypedNegativeSample> {
    let existing = edge_sources
        .iter()
        .copied()
        .zip(edge_targets.iter().copied())
        .zip(relation_types.iter().copied())
        .map(|((left, right), relation)| (left, right, relation))
        .collect::<HashSet<_>>();
    let mut by_type = HashMap::<u32, Vec<u32>>::new();
    for (ordinal, node) in source.nodes.iter().enumerate() {
        if node.authority == ResearchAuthority::Asserted {
            by_type
                .entry(node_type_ids[ordinal])
                .or_default()
                .push(ordinal as u32);
        }
    }
    let mut negatives = Vec::new();
    for edge_index in 0..edge_sources.len() {
        if authorities[edge_index] != ResearchAuthority::Asserted {
            continue;
        }
        let source_ix = edge_sources[edge_index];
        let target_ix = edge_targets[edge_index];
        let relation = relation_types[edge_index];
        let target_type = node_type_ids[target_ix as usize];
        let Some(candidates) = by_type.get(&target_type) else {
            continue;
        };
        let (start, step) =
            candidate_permutation(&source.dataset_id, edge_index as u32, candidates.len());
        let mut accepted = 0_usize;
        let mut candidate_index = start;
        for _ in 0..candidates.len() {
            let target = candidates[candidate_index];
            candidate_index = (candidate_index + step) % candidates.len();
            if target == source_ix
                || target == target_ix
                || source.nodes[target as usize].available_at_ms > available_at[edge_index]
                || existing.contains(&(source_ix, target, relation))
            {
                continue;
            }
            negatives.push(TypedNegativeSample {
                positive_edge: edge_index as u32,
                source: source_ix,
                target,
                relation_type: relation,
                split: splits[edge_index],
            });
            accepted += 1;
            if accepted == policy.negatives_per_asserted_edge as usize {
                break;
            }
        }
    }
    negatives
}

fn candidate_permutation(dataset_id: &str, edge: u32, count: usize) -> (usize, usize) {
    if count <= 1 {
        return (0, 1);
    }
    let mut hasher = blake3::Hasher::new();
    hasher.update(dataset_id.as_bytes());
    hasher.update(&edge.to_le_bytes());
    let digest = hasher.finalize();
    let bytes = digest.as_bytes();
    let start =
        u64::from_le_bytes(bytes[..8].try_into().expect("eight digest bytes")) as usize % count;
    let mut step =
        (u64::from_le_bytes(bytes[8..16].try_into().expect("eight digest bytes")) as usize % count)
            .max(1);
    while greatest_common_divisor(step, count) != 1 {
        step = step % (count - 1) + 1;
    }
    (start, step)
}

fn greatest_common_divisor(mut left: usize, mut right: usize) -> usize {
    while right != 0 {
        (left, right) = (right, left % right);
    }
    left
}

fn feature_certificates(schemas: &[CompactString]) -> Vec<FeatureColumnCertificate> {
    let mut certificates = Vec::with_capacity(schemas.len() * PROPOSAL_FEATURE_DIM);
    for schema in schemas {
        for column in 0..PROPOSAL_FEATURE_DIM {
            certificates.push(FeatureColumnCertificate {
                feature_schema_id: schema.clone(),
                column: column as u16,
                name: format_compact!("policy_feature_{column}"),
                dtype: "i16".into(),
                normalization: "divide_by_1000".into(),
                available_at: "proposal_observed_at_ms".into(),
                label_free: true,
            });
        }
    }
    certificates
}

fn authority_rank(value: ResearchAuthority) -> u8 {
    value as u8
}

fn hash_json(
    hasher: &mut blake3::Hasher,
    value: &(impl Serialize + ?Sized),
) -> Result<(), FrozenGraphResearchError> {
    let bytes = serde_json::to_vec(value)?;
    hasher.update(&(bytes.len() as u64).to_le_bytes());
    hasher.update(&bytes);
    Ok(())
}
