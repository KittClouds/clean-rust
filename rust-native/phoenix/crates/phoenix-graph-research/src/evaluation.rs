use crate::{
    BinaryMetrics, EvaluationPolicy, FeatureColumnCertificate, FrozenGraphResearchSnapshot,
    FrozenTensorSnapshot, LeakageAudit, ResearchAuthority, ResearchEvaluationError,
    ResearchEvaluationProtocol, ResearchProposalLabel, ResearchSplit, SeedCertificate,
    TaskDefinition, PROPOSAL_FEATURE_DIM, RESEARCH_EVALUATION_SCHEMA,
};
use compact_str::{format_compact, CompactString};
use hashbrown::HashSet;
use serde::Serialize;

pub fn certify_evaluation_protocol(
    source: &FrozenGraphResearchSnapshot,
    tensors: &FrozenTensorSnapshot,
    policy: EvaluationPolicy,
) -> Result<ResearchEvaluationProtocol, ResearchEvaluationError> {
    policy.validate()?;
    if tensors.source_dataset_id != source.dataset_id {
        return Err(ResearchEvaluationError::SourceIdentityMismatch);
    }
    validate_tensor_shapes(tensors)?;
    validate_feature_schema(tensors, &policy.feature_schema_id)?;
    let leakage_audit = audit_leakage(source, tensors, &policy.feature_schema_id)?;
    let seed_certificate = certify_seeds(tensors, &policy);
    let tasks = task_definitions();
    let mut protocol = ResearchEvaluationProtocol {
        schema_version: RESEARCH_EVALUATION_SCHEMA.into(),
        protocol_id: "pending".into(),
        tensor_id: tensors.tensor_id.clone(),
        source_dataset_id: source.dataset_id.clone(),
        split_policy: source.split_policy,
        policy,
        seed_certificate,
        tasks,
        leakage_audit,
    };
    protocol.protocol_id = content_id(&protocol)?;
    Ok(protocol)
}

pub fn evaluate_binary_scores(
    labels: &[bool],
    probabilities: &[f32],
    calibration_bins: u8,
) -> Result<BinaryMetrics, ResearchEvaluationError> {
    if labels.is_empty()
        || labels.len() != probabilities.len()
        || calibration_bins < 2
        || probabilities
            .iter()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
    {
        return Err(ResearchEvaluationError::InvalidMetricInput);
    }
    let mut log_loss = 0.0_f64;
    let mut brier = 0.0_f64;
    let mut bins = vec![(0_u64, 0.0_f64, 0_u64); calibration_bins as usize];
    let mut positives = 0_u64;
    for (&label, &probability) in labels.iter().zip(probabilities) {
        let p = f64::from(probability).clamp(1.0e-7, 1.0 - 1.0e-7);
        let y = u64::from(label);
        positives += y;
        log_loss -= if label { p.ln() } else { (1.0 - p).ln() };
        brier += (p - y as f64).powi(2);
        let bin = ((p * f64::from(calibration_bins)) as usize).min(bins.len() - 1);
        bins[bin].0 += 1;
        bins[bin].1 += p;
        bins[bin].2 += y;
    }
    let samples = labels.len() as u64;
    let ece = bins
        .into_iter()
        .filter(|bin| bin.0 != 0)
        .map(|(count, probability_sum, positive_count)| {
            (count as f64 / samples as f64)
                * ((probability_sum / count as f64) - (positive_count as f64 / count as f64)).abs()
        })
        .sum();
    Ok(BinaryMetrics {
        samples,
        positives,
        log_loss: log_loss / samples as f64,
        brier_score: brier / samples as f64,
        expected_calibration_error: ece,
        average_precision: average_precision(labels, probabilities),
        roc_auc: roc_auc(labels, probabilities),
    })
}

fn validate_tensor_shapes(tensors: &FrozenTensorSnapshot) -> Result<(), ResearchEvaluationError> {
    let nodes = tensors.node_ids.len();
    if [
        tensors.node_type_ids.len(),
        tensors.node_authority.len(),
        tensors.node_splits.len(),
        tensors.node_available_at_ms.len(),
    ]
    .into_iter()
    .any(|count| count != nodes)
    {
        return Err(ResearchEvaluationError::TensorShape("node arrays"));
    }
    let edges = tensors.coo_sources.len();
    if [
        tensors.coo_targets.len(),
        tensors.coo_relation_types.len(),
        tensors.coo_authority.len(),
        tensors.coo_splits.len(),
        tensors.coo_available_at_ms.len(),
        tensors.coo_weights.len(),
    ]
    .into_iter()
    .any(|count| count != edges)
    {
        return Err(ResearchEvaluationError::TensorShape("edge arrays"));
    }
    let proposals = tensors.proposal_labels.len();
    if [
        tensors.proposal_label_observed.len(),
        tensors.proposal_splits.len(),
        tensors.proposal_observed_at_ms.len(),
        tensors.proposal_label_available_at_ms.len(),
        tensors.proposal_feature_schema_ids.len(),
    ]
    .into_iter()
    .any(|count| count != proposals)
        || tensors.proposal_features.len() != proposals * PROPOSAL_FEATURE_DIM
    {
        return Err(ResearchEvaluationError::TensorShape("proposal arrays"));
    }
    let incidences = tensors.incidence_hyperedges.len();
    if [
        tensors.incidence_participants.len(),
        tensors.incidence_role_types.len(),
        tensors.incidence_splits.len(),
        tensors.incidence_resolved.len(),
    ]
    .into_iter()
    .any(|count| count != incidences)
    {
        return Err(ResearchEvaluationError::TensorShape("incidence arrays"));
    }
    if tensors.csr_row_offsets.len() != nodes + 1
        || tensors.csr_columns.len() != edges
        || tensors.csr_edge_indices.len() != edges
    {
        return Err(ResearchEvaluationError::TensorShape("csr arrays"));
    }
    Ok(())
}

fn validate_feature_schema(
    tensors: &FrozenTensorSnapshot,
    selected: &str,
) -> Result<(), ResearchEvaluationError> {
    let Some(schema_index) = tensors
        .feature_schema_vocabulary
        .iter()
        .position(|schema| schema == selected)
    else {
        return Err(ResearchEvaluationError::FeatureSchema(selected.to_owned()));
    };
    let certificates = tensors
        .feature_certificates
        .iter()
        .filter(|row| row.feature_schema_id == selected)
        .collect::<Vec<_>>();
    if certificates.len() != PROPOSAL_FEATURE_DIM
        || !certificates.iter().all(certified_column)
        || !tensors
            .proposal_feature_schema_ids
            .iter()
            .any(|&value| value as usize == schema_index)
    {
        return Err(ResearchEvaluationError::FeatureSchema(selected.to_owned()));
    }
    Ok(())
}

fn certified_column(row: &&FeatureColumnCertificate) -> bool {
    row.column < PROPOSAL_FEATURE_DIM as u16
        && row.dtype == "i16"
        && row.normalization == "divide_by_1000"
        && row.available_at == "proposal_observed_at_ms"
        && row.label_free
}

fn audit_leakage(
    source: &FrozenGraphResearchSnapshot,
    tensors: &FrozenTensorSnapshot,
    selected_schema: &str,
) -> Result<LeakageAudit, ResearchEvaluationError> {
    if source.proposals.len() != tensors.proposal_labels.len() {
        return Err(ResearchEvaluationError::TensorShape("source proposals"));
    }
    for (index, row) in source.proposals.iter().enumerate() {
        let assignment_time = row.observed_at_ms.max(row.label_available_at_ms);
        let expected_observed = row.label != ResearchProposalLabel::Uncommitted;
        if row.split != source.split_policy.split(assignment_time)
            || tensors.proposal_splits[index] != row.split
            || tensors.proposal_labels[index] != row.label
            || tensors.proposal_label_observed[index] != expected_observed
            || tensors.proposal_observed_at_ms[index] != row.observed_at_ms
            || tensors.proposal_label_available_at_ms[index] != row.label_available_at_ms
            || tensors.proposal_features
                [index * PROPOSAL_FEATURE_DIM..(index + 1) * PROPOSAL_FEATURE_DIM]
                != row.features
            || tensors
                .feature_schema_vocabulary
                .get(tensors.proposal_feature_schema_ids[index] as usize)
                != Some(&row.feature_schema_id)
            || assignment_time > source.frozen_at_ms
        {
            return Err(ResearchEvaluationError::Leakage("proposal chronology"));
        }
    }
    if source.nodes.len() != tensors.node_ids.len() {
        return Err(ResearchEvaluationError::TensorShape("source nodes"));
    }
    for index in 0..tensors.node_ids.len() {
        let Some(source_node) = source.nodes.get(index) else {
            return Err(ResearchEvaluationError::TensorShape("source nodes"));
        };
        if tensors.node_ids[index] != source_node.id
            || tensors.node_authority[index] != source_node.authority
            || tensors.node_available_at_ms[index] != source_node.available_at_ms
            || tensors.node_splits[index] != source_node.split
            || tensors.node_available_at_ms[index] > source.frozen_at_ms
            || tensors.node_splits[index]
                != source
                    .split_policy
                    .split(tensors.node_available_at_ms[index])
        {
            return Err(ResearchEvaluationError::Leakage("node chronology"));
        }
    }
    if source.incidences.len() != tensors.incidence_hyperedges.len() {
        return Err(ResearchEvaluationError::TensorShape("source incidences"));
    }
    for (index, row) in source.incidences.iter().enumerate() {
        if tensors.incidence_hyperedges[index] != row.hyperedge
            || tensors.incidence_participants[index] != row.participant
            || tensors.incidence_splits[index] != row.split
            || tensors.incidence_resolved[index] != row.resolved
            || tensors
                .role_vocabulary
                .get(tensors.incidence_role_types[index] as usize)
                != Some(&row.role)
        {
            return Err(ResearchEvaluationError::Leakage("incidence projection"));
        }
    }
    let mut expected_edges = source
        .edges
        .iter()
        .map(|edge| {
            let relation = tensors
                .relation_vocabulary
                .iter()
                .position(|value| value == edge.relation)
                .ok_or(ResearchEvaluationError::TensorShape("edge relation"))?;
            Ok((
                edge.source,
                edge.target,
                relation as u32,
                edge.authority as u8,
                edge.split as u8,
                edge.available_at_ms,
                edge.weight.to_bits(),
            ))
        })
        .collect::<Result<Vec<_>, ResearchEvaluationError>>()?;
    let mut tensor_edges = (0..tensors.coo_sources.len())
        .map(|index| {
            (
                tensors.coo_sources[index],
                tensors.coo_targets[index],
                tensors.coo_relation_types[index],
                tensors.coo_authority[index] as u8,
                tensors.coo_splits[index] as u8,
                tensors.coo_available_at_ms[index],
                tensors.coo_weights[index].to_bits(),
            )
        })
        .collect::<Vec<_>>();
    expected_edges.sort_unstable();
    tensor_edges.sort_unstable();
    if expected_edges != tensor_edges {
        return Err(ResearchEvaluationError::TensorShape("source edges"));
    }
    for index in 0..tensors.coo_sources.len() {
        let source_ix = tensors.coo_sources[index] as usize;
        let target_ix = tensors.coo_targets[index] as usize;
        let time = tensors.coo_available_at_ms[index];
        if source_ix >= tensors.node_ids.len()
            || target_ix >= tensors.node_ids.len()
            || time > source.frozen_at_ms
            || tensors.node_available_at_ms[source_ix] > time
            || tensors.node_available_at_ms[target_ix] > time
            || tensors.coo_splits[index] != source.split_policy.split(time)
        {
            return Err(ResearchEvaluationError::Leakage("edge chronology"));
        }
    }
    audit_negatives(tensors)?;
    let schema_index = tensors
        .feature_schema_vocabulary
        .iter()
        .position(|schema| schema == selected_schema)
        .ok_or_else(|| ResearchEvaluationError::FeatureSchema(selected_schema.to_owned()))?
        as u32;
    let mut split_counts = [0_u64; 3];
    for index in 0..tensors.proposal_labels.len() {
        if tensors.proposal_feature_schema_ids[index] == schema_index
            && tensors.proposal_label_observed[index]
        {
            split_counts[split_slot(tensors.proposal_splits[index])] += 1;
        }
    }
    Ok(LeakageAudit {
        nodes_checked: tensors.node_ids.len() as u64,
        edges_checked: tensors.coo_sources.len() as u64,
        incidences_checked: tensors.incidence_hyperedges.len() as u64,
        proposals_checked: tensors.proposal_labels.len() as u64,
        observed_proposals: tensors
            .proposal_label_observed
            .iter()
            .filter(|&&value| value)
            .count() as u64,
        censored_proposals: tensors
            .proposal_label_observed
            .iter()
            .filter(|&&value| !value)
            .count() as u64,
        negatives_checked: tensors.negatives.len() as u64,
        feature_columns_checked: PROPOSAL_FEATURE_DIM as u64,
        train_examples: split_counts[0],
        validation_examples: split_counts[1],
        test_examples: split_counts[2],
        no_future_rows: true,
        no_label_before_availability: true,
        no_censored_supervision: true,
        no_feature_schema_mixing: true,
        no_negative_collisions: true,
    })
}

fn audit_negatives(tensors: &FrozenTensorSnapshot) -> Result<(), ResearchEvaluationError> {
    let existing = tensors
        .coo_sources
        .iter()
        .copied()
        .zip(tensors.coo_targets.iter().copied())
        .zip(tensors.coo_relation_types.iter().copied())
        .map(|((source, target), relation)| (source, target, relation))
        .collect::<HashSet<_>>();
    let mut unique = HashSet::with_capacity(tensors.negatives.len());
    for row in &tensors.negatives {
        let edge = row.positive_edge as usize;
        let target = row.target as usize;
        if edge >= tensors.coo_sources.len()
            || target >= tensors.node_ids.len()
            || row.source != tensors.coo_sources[edge]
            || row.relation_type != tensors.coo_relation_types[edge]
            || row.split != tensors.coo_splits[edge]
            || tensors.node_type_ids[target]
                != tensors.node_type_ids[tensors.coo_targets[edge] as usize]
            || tensors.node_authority[target] != ResearchAuthority::Asserted
            || tensors.node_available_at_ms[target] > tensors.coo_available_at_ms[edge]
            || existing.contains(&(row.source, row.target, row.relation_type))
            || !unique.insert((row.positive_edge, row.target))
        {
            return Err(ResearchEvaluationError::Leakage("negative collision"));
        }
    }
    Ok(())
}

fn certify_seeds(tensors: &FrozenTensorSnapshot, policy: &EvaluationPolicy) -> SeedCertificate {
    let namespace = format_compact!(
        "{RESEARCH_EVALUATION_SCHEMA}:{}:{}",
        tensors.tensor_id,
        policy.feature_schema_id
    );
    let mut seeds = Vec::with_capacity(policy.repeats as usize);
    let mut certificate = blake3::Hasher::new();
    for repeat in 0..policy.repeats {
        let mut hasher = blake3::Hasher::new();
        hasher.update(namespace.as_bytes());
        hasher.update(&policy.seed_root.to_le_bytes());
        hasher.update(&repeat.to_le_bytes());
        let digest = hasher.finalize();
        let seed = u64::from_le_bytes(digest.as_bytes()[..8].try_into().expect("seed bytes"));
        certificate.update(&seed.to_le_bytes());
        seeds.push(seed);
    }
    SeedCertificate {
        namespace,
        digest: format_compact!("b3-{}", certificate.finalize().to_hex()),
        seeds,
    }
}

fn task_definitions() -> Vec<TaskDefinition> {
    vec![
        TaskDefinition {
            task_id: "proposal-outcome-binary/v1".into(),
            examples: "observed proposals from exactly one certified feature schema".into(),
            target: "active=positive; superseded,retracted,reverted=negative; uncommitted=censored"
                .into(),
            split_authority: "max(observedAtMs,labelAvailableAtMs) chronological split".into(),
            metrics: vec![
                "average-precision".into(),
                "roc-auc".into(),
                "log-loss".into(),
                "brier".into(),
                "ece".into(),
            ],
            executable_in_v1: true,
        },
        TaskDefinition {
            task_id: "typed-link-prediction/v1".into(),
            examples: "asserted typed edges with certified constrained corruptions".into(),
            target: "rank asserted target above type- and time-constrained targets".into(),
            split_authority: "edge availableAtMs chronological split".into(),
            metrics: vec![
                "filtered-mrr".into(),
                "hits@1".into(),
                "hits@3".into(),
                "hits@10".into(),
            ],
            executable_in_v1: false,
        },
        TaskDefinition {
            task_id: "hyperedge-role-completion/v1".into(),
            examples: "resolved typed incidence with one participant role masked".into(),
            target: "rank the held-out participant within the certified node type".into(),
            split_authority: "incidence chronological split; train-visible incidence only".into(),
            metrics: vec![
                "filtered-mrr".into(),
                "hits@1".into(),
                "hits@3".into(),
                "hits@10".into(),
            ],
            executable_in_v1: false,
        },
    ]
}

fn average_precision(labels: &[bool], scores: &[f32]) -> Option<f64> {
    let positives = labels.iter().filter(|&&label| label).count();
    if positives == 0 {
        return None;
    }
    let mut order = (0..labels.len()).collect::<Vec<_>>();
    order.sort_unstable_by(|&left, &right| {
        scores[right]
            .total_cmp(&scores[left])
            .then(left.cmp(&right))
    });
    let mut seen_positive = 0_u64;
    let mut precision_sum = 0.0;
    for (rank, index) in order.into_iter().enumerate() {
        if labels[index] {
            seen_positive += 1;
            precision_sum += seen_positive as f64 / (rank + 1) as f64;
        }
    }
    Some(precision_sum / positives as f64)
}

fn roc_auc(labels: &[bool], scores: &[f32]) -> Option<f64> {
    let positives = labels.iter().filter(|&&label| label).count();
    let negatives = labels.len() - positives;
    if positives == 0 || negatives == 0 {
        return None;
    }
    let mut order = (0..labels.len()).collect::<Vec<_>>();
    order.sort_unstable_by(|&left, &right| {
        scores[left]
            .total_cmp(&scores[right])
            .then(left.cmp(&right))
    });
    let mut positive_rank_sum = 0.0_f64;
    let mut start = 0_usize;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && scores[order[end]] == scores[order[start]] {
            end += 1;
        }
        let average_rank = ((start + 1 + end) as f64) * 0.5;
        positive_rank_sum += order[start..end]
            .iter()
            .filter(|&&index| labels[index])
            .count() as f64
            * average_rank;
        start = end;
    }
    Some(
        (positive_rank_sum - (positives * (positives + 1) / 2) as f64)
            / (positives * negatives) as f64,
    )
}

fn split_slot(split: ResearchSplit) -> usize {
    match split {
        ResearchSplit::Train => 0,
        ResearchSplit::Validation => 1,
        ResearchSplit::Test => 2,
    }
}

fn content_id(value: &impl Serialize) -> Result<CompactString, ResearchEvaluationError> {
    let bytes = serde_json::to_vec(value)?;
    Ok(format_compact!("b3-{}", blake3::hash(&bytes).to_hex()))
}
