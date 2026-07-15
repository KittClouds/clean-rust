use compact_str::{format_compact, CompactString};
use hashbrown::HashMap;
use phoenix_types::{
    GraphDecisionActionKind, GraphDecisionRewardSignal, GraphDecisionRewardVector,
};
use serde::Serialize;

use crate::{
    evaluate_binary_scores, DecisionClassificationMetrics, DecisionEvaluationSliceResult,
    DecisionPolicyMetrics, DecisionRankingMetrics, DecisionSliceDimension, FrozenDecisionRecord,
    FrozenDecisionTrajectoryTables, NativeDecisionEvaluationError, NativeDecisionEvaluationInput,
    NativeDecisionEvaluationProtocol, NativeDecisionEvaluationReport, NativeDecisionPrediction,
    NativeDecisionTaskFamily, PolicyRewardScalarization, RiskCoveragePoint,
    NATIVE_DECISION_EVALUATION_SCHEMA, NATIVE_DECISION_SLICE_POLICY, NATIVE_DECISION_TIE_POLICY,
};

struct ResolvedRow<'a> {
    record: &'a FrozenDecisionRecord,
    input: &'a NativeDecisionEvaluationInput,
}

type TaskMetrics = (
    Option<DecisionRankingMetrics>,
    Option<DecisionClassificationMetrics>,
    Option<DecisionPolicyMetrics>,
);

pub fn certify_native_decision_evaluation_protocol(
    mut protocol: NativeDecisionEvaluationProtocol,
) -> Result<NativeDecisionEvaluationProtocol, NativeDecisionEvaluationError> {
    if protocol.schema_version.as_str() != NATIVE_DECISION_EVALUATION_SCHEMA
        || protocol.dataset_id.trim().is_empty()
        || protocol.calibration_bins < 2
        || protocol.recall_at_k == 0
        || protocol.ndcg_at_k == 0
        || protocol.tie_policy != NATIVE_DECISION_TIE_POLICY
        || protocol.slice_policy_id != NATIVE_DECISION_SLICE_POLICY
        || protocol.risk_coverage_basis_points.is_empty()
        || protocol
            .risk_coverage_basis_points
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || protocol
            .risk_coverage_basis_points
            .iter()
            .any(|&value| value == 0 || value > 10_000)
        || (protocol.task_family == NativeDecisionTaskFamily::Policy
            && protocol.reward_scalarization.is_none())
        || (protocol.task_family != NativeDecisionTaskFamily::Policy
            && protocol.reward_scalarization.is_some())
    {
        return Err(NativeDecisionEvaluationError::InvalidInput("protocol"));
    }
    if let Some(policy) = protocol.reward_scalarization.as_mut() {
        if policy.pending_signal_policy != "fail_closed"
            || policy.weights_micros.iter().all(|&weight| weight == 0)
        {
            return Err(NativeDecisionEvaluationError::InvalidInput(
                "pending reward policy",
            ));
        }
        policy.policy_id = "pending".into();
        policy.policy_id = content_id(policy)?;
    }
    protocol.protocol_id = "pending".into();
    protocol.protocol_id = content_id(&protocol)?;
    Ok(protocol)
}

pub fn certify_native_decision_prediction(
    mut prediction: NativeDecisionPrediction,
) -> Result<NativeDecisionPrediction, NativeDecisionEvaluationError> {
    validate_prediction_shape(&prediction)?;
    prediction.prediction_id = "pending".into();
    prediction.prediction_id = content_id(&prediction)?;
    Ok(prediction)
}

pub fn evaluate_native_decisions(
    tables: &FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    inputs: &[NativeDecisionEvaluationInput],
) -> Result<NativeDecisionEvaluationReport, NativeDecisionEvaluationError> {
    validate_protocol_identity(protocol)?;
    if !tables.provenance.leakage_certificate.passes() {
        return Err(NativeDecisionEvaluationError::InvalidInput(
            "trajectory leakage certificate",
        ));
    }
    let by_id = index_inputs(inputs)?;
    let mut rows = Vec::new();
    for record in &tables.decisions {
        if record.split != protocol.partition {
            continue;
        }
        let input = by_id.get(record.decision_id.as_str()).ok_or(
            NativeDecisionEvaluationError::InvalidInput("missing partition prediction"),
        )?;
        validate_row(tables, record, input, protocol.task_family)?;
        rows.push(ResolvedRow { record, input });
    }
    if rows.is_empty() || rows.len() != inputs.len() {
        return Err(NativeDecisionEvaluationError::InvalidInput(
            "partition prediction set",
        ));
    }
    let prediction_set_id = content_id(
        &rows
            .iter()
            .map(|row| row.input.prediction.prediction_id.as_str())
            .collect::<Vec<_>>(),
    )?;
    let (ranking, classification, policy) = aggregate(tables, protocol, &rows)?;
    let slices = slice_results(tables, protocol, &rows)?;
    let mut report = NativeDecisionEvaluationReport {
        schema_version: NATIVE_DECISION_EVALUATION_SCHEMA.into(),
        report_id: "pending".into(),
        protocol_id: protocol.protocol_id.clone(),
        dataset_id: protocol.dataset_id.clone(),
        prediction_set_id,
        task_family: protocol.task_family,
        partition: protocol.partition,
        decisions: rows.len() as u64,
        ranking,
        classification,
        policy,
        slices,
    };
    report.report_id = content_id(&report)?;
    Ok(report)
}

fn aggregate(
    tables: &FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    rows: &[ResolvedRow<'_>],
) -> Result<TaskMetrics, NativeDecisionEvaluationError> {
    match protocol.task_family {
        NativeDecisionTaskFamily::Ranking => {
            Ok((Some(ranking_metrics(tables, protocol, rows)?), None, None))
        }
        NativeDecisionTaskFamily::Classification => Ok((
            None,
            Some(classification_metrics(tables, protocol, rows)?),
            None,
        )),
        NativeDecisionTaskFamily::Policy => {
            Ok((None, None, Some(policy_metrics(tables, protocol, rows)?)))
        }
    }
}

fn ranking_metrics(
    tables: &FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    rows: &[ResolvedRow<'_>],
) -> Result<DecisionRankingMetrics, NativeDecisionEvaluationError> {
    let mut reciprocal = 0.0;
    let mut hits = [0.0; 3];
    let mut recall = 0.0;
    let mut ndcg = 0.0;
    let mut covered = 0_u64;
    let mut candidates = 0_u64;
    let mut paired_delta = 0.0;
    let mut paired = [0_u64; 3];
    for row in rows {
        let selected = selected_local(tables, row.record)?;
        let prediction = &row.input.prediction;
        let eligible_count = prediction.eligible.iter().filter(|&&value| value).count();
        candidates += eligible_count as u64;
        let rank = if prediction.eligible[selected] {
            covered += 1;
            average_tie_rank(&prediction.scores, &prediction.eligible, selected)
        } else {
            eligible_count as f64 + 1.0
        };
        reciprocal += 1.0 / rank;
        for (slot, cutoff) in [1_u32, 3, 10].into_iter().enumerate() {
            hits[slot] +=
                fractional_hit(&prediction.scores, &prediction.eligible, selected, cutoff);
        }
        recall += recall_at_k(tables, row.record, prediction, protocol.recall_at_k)?;
        ndcg += ndcg_at_k(tables, row.record, prediction, protocol.ndcg_at_k)?;
        if let Some(reference) = prediction.reference_scores.as_deref() {
            let reference_rank = average_tie_rank(reference, &prediction.eligible, selected);
            let delta = reference_rank - rank;
            paired_delta += delta;
            paired[if delta > 0.0 {
                0
            } else if delta < 0.0 {
                1
            } else {
                2
            }] += 1;
        }
    }
    let count = rows.len() as f64;
    let paired_count = paired.iter().sum::<u64>();
    Ok(DecisionRankingMetrics {
        queries: rows.len() as u64,
        candidates,
        filtered_mean_reciprocal_rank: reciprocal / count,
        hits_at_1: hits[0] / count,
        hits_at_3: hits[1] / count,
        hits_at_10: hits[2] / count,
        recall_at_k: recall / count,
        ndcg_at_k: ndcg / count,
        candidate_coverage: covered as f64 / count,
        paired_mean_rank_delta: (paired_count != 0).then_some(paired_delta / paired_count as f64),
        paired_wins: paired[0],
        paired_losses: paired[1],
        paired_ties: paired[2],
    })
}

fn classification_metrics(
    tables: &FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    rows: &[ResolvedRow<'_>],
) -> Result<DecisionClassificationMetrics, NativeDecisionEvaluationError> {
    let mut labels = Vec::new();
    let mut probabilities = Vec::new();
    let mut confusion = [[[0_u64; 2]; 2]; 11];
    let mut confidence_rows = Vec::with_capacity(rows.len());
    let mut abstained = 0_u64;
    for row in rows {
        let selected = selected_local(tables, row.record)?;
        let prediction = &row.input.prediction;
        for index in 0..prediction.probabilities.len() {
            if prediction.eligible[index] {
                labels.push(prediction.relevant[index]);
                probabilities.push(prediction.probabilities[index]);
            }
        }
        let truth_kind = selected_kind(tables, row.record)?;
        let predicted_kind = prediction
            .predicted_candidate_ordinal
            .map(|value| candidate_kind(tables, row.record, value as usize))
            .transpose()?;
        if predicted_kind.is_none() {
            abstained += 1;
        }
        for kind in GraphDecisionActionKind::ALL {
            let actual = usize::from(kind == truth_kind);
            let predicted = usize::from(predicted_kind == Some(kind));
            confusion[action_kind_index(kind)][actual][predicted] += 1;
        }
        confidence_rows.push((
            prediction.confidence,
            row.record.decision_id.clone(),
            predicted_kind == Some(truth_kind),
        ));
        if !prediction.relevant[selected] {
            return Err(NativeDecisionEvaluationError::InvalidInput(
                "selected action relevance",
            ));
        }
    }
    let binary = evaluate_binary_scores(&labels, &probabilities, protocol.calibration_bins)
        .map_err(|_| NativeDecisionEvaluationError::Metric)?;
    let observed_classes = confusion
        .iter()
        .filter(|matrix| matrix[1][0] + matrix[1][1] != 0)
        .count();
    let macro_f1 = confusion
        .iter()
        .filter(|matrix| matrix[1][0] + matrix[1][1] != 0)
        .map(|matrix| {
            let tp = matrix[1][1] as f64;
            let fp = matrix[0][1] as f64;
            let fn_count = matrix[1][0] as f64;
            if tp + fp + fn_count == 0.0 {
                0.0
            } else {
                (2.0 * tp) / (2.0 * tp + fp + fn_count)
            }
        })
        .sum::<f64>()
        / observed_classes.max(1) as f64;
    Ok(DecisionClassificationMetrics {
        decisions: rows.len() as u64,
        candidate_samples: labels.len() as u64,
        average_precision: binary.average_precision,
        macro_f1,
        brier_score: binary.brier_score,
        log_loss: binary.log_loss,
        expected_calibration_error: binary.expected_calibration_error,
        abstained,
        risk_coverage: risk_coverage(&mut confidence_rows, &protocol.risk_coverage_basis_points),
    })
}

fn policy_metrics(
    tables: &FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    rows: &[ResolvedRow<'_>],
) -> Result<DecisionPolicyMetrics, NativeDecisionEvaluationError> {
    let scalarization = protocol.reward_scalarization.as_ref().ok_or(
        NativeDecisionEvaluationError::InvalidInput("reward scalarization"),
    )?;
    let mut relative = 0_i128;
    let mut regret = 0_i128;
    let mut violations = 0_u64;
    let mut unsupported = 0_u64;
    let mut edit_cost = 0_u128;
    let mut stability = 0_i128;
    for row in rows {
        let selected = selected_local(tables, row.record)?;
        let prediction = &row.input.prediction;
        let predicted = prediction.predicted_candidate_ordinal.ok_or(
            NativeDecisionEvaluationError::InvalidInput(
                "policy abstention must be an explicit candidate",
            ),
        )? as usize;
        let outcomes = prediction.policy_outcomes.as_ref().ok_or(
            NativeDecisionEvaluationError::InvalidInput("policy outcomes"),
        )?;
        let recorded = observed_rewards(&tables.rewards[row.record.reward_ordinal as usize])?;
        if outcomes[selected].reward_micros != recorded {
            return Err(NativeDecisionEvaluationError::InvalidInput(
                "recorded reward authority",
            ));
        }
        let recorded_score = scalarize(&recorded, scalarization);
        let predicted_score = scalarize(&outcomes[predicted].reward_micros, scalarization);
        relative += i128::from(predicted_score - recorded_score);
        regret += i128::from(recorded_score - predicted_score);
        violations += u64::from(outcomes[predicted].hard_constraint_violations);
        unsupported += u64::from(!outcomes[predicted].supported);
        edit_cost += u128::from(
            outcomes[predicted]
                .edit_cost_micros
                .saturating_sub(outcomes[selected].edit_cost_micros),
        );
        stability += i128::from(outcomes[predicted].future_stability_micros);
    }
    let count = rows.len() as f64;
    Ok(DecisionPolicyMetrics {
        decisions: rows.len() as u64,
        mean_relative_reward_micros: relative as f64 / count,
        mean_regret_against_recorded_micros: regret as f64 / count,
        hard_constraint_violations: violations,
        unsupported_action_rate: unsupported as f64 / count,
        mean_unnecessary_edit_cost_micros: edit_cost as f64 / count,
        mean_future_graph_stability_micros: stability as f64 / count,
    })
}

fn slice_results(
    tables: &FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    rows: &[ResolvedRow<'_>],
) -> Result<Vec<DecisionEvaluationSliceResult>, NativeDecisionEvaluationError> {
    let mut output = Vec::new();
    for dimension in DecisionSliceDimension::ALL {
        let mut keys = rows
            .iter()
            .map(|row| slice_key(row.input, dimension))
            .collect::<Vec<_>>();
        keys.sort_unstable();
        keys.dedup();
        for key in keys {
            let selected = rows
                .iter()
                .filter(|row| slice_key(row.input, dimension) == key)
                .map(|row| ResolvedRow {
                    record: row.record,
                    input: row.input,
                })
                .collect::<Vec<_>>();
            let (ranking, classification, policy) = aggregate(tables, protocol, &selected)?;
            output.push(DecisionEvaluationSliceResult {
                dimension,
                key,
                decisions: selected.len() as u64,
                ranking,
                classification,
                policy,
            });
        }
    }
    Ok(output)
}

fn validate_protocol_identity(
    protocol: &NativeDecisionEvaluationProtocol,
) -> Result<(), NativeDecisionEvaluationError> {
    let mut candidate = protocol.clone();
    let expected = candidate.protocol_id.clone();
    candidate.protocol_id = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(NativeDecisionEvaluationError::Identity("protocol"));
    }
    if let Some(policy) = &protocol.reward_scalarization {
        let mut candidate = policy.clone();
        let expected = candidate.policy_id.clone();
        candidate.policy_id = "pending".into();
        if content_id(&candidate)? != expected {
            return Err(NativeDecisionEvaluationError::Identity("reward policy"));
        }
    }
    Ok(())
}

fn index_inputs(
    inputs: &[NativeDecisionEvaluationInput],
) -> Result<HashMap<&str, &NativeDecisionEvaluationInput>, NativeDecisionEvaluationError> {
    let mut output = HashMap::with_capacity(inputs.len());
    for input in inputs {
        if input.decision_id != input.prediction.decision_id
            || output.insert(input.decision_id.as_str(), input).is_some()
            || input.slices.temporal.trim().is_empty()
            || input.slices.relation_frequency.trim().is_empty()
            || input.slices.entity_degree.trim().is_empty()
            || input.slices.evidence_count.trim().is_empty()
        {
            return Err(NativeDecisionEvaluationError::InvalidInput(
                "prediction binding or slices",
            ));
        }
    }
    Ok(output)
}

fn validate_row(
    tables: &FrozenDecisionTrajectoryTables,
    record: &FrozenDecisionRecord,
    input: &NativeDecisionEvaluationInput,
    family: NativeDecisionTaskFamily,
) -> Result<(), NativeDecisionEvaluationError> {
    validate_prediction_shape(&input.prediction)?;
    let mut candidate = input.prediction.clone();
    let expected = candidate.prediction_id.clone();
    candidate.prediction_id = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(NativeDecisionEvaluationError::Identity("prediction"));
    }
    let length = usize::try_from(record.candidate_actions.length)
        .map_err(|_| NativeDecisionEvaluationError::InvalidInput("candidate range"))?;
    if input.prediction.scores.len() != length
        || input.slices.action_family != selected_kind(tables, record)?
        || !input.prediction.relevant[selected_local(tables, record)?]
        || (family == NativeDecisionTaskFamily::Policy
            && input
                .prediction
                .policy_outcomes
                .as_ref()
                .is_none_or(|value| value.len() != length))
    {
        return Err(NativeDecisionEvaluationError::InvalidInput("decision row"));
    }
    Ok(())
}

fn validate_prediction_shape(
    prediction: &NativeDecisionPrediction,
) -> Result<(), NativeDecisionEvaluationError> {
    let count = prediction.scores.len();
    if prediction.decision_id.trim().is_empty()
        || prediction.producer_model_id.trim().is_empty()
        || count == 0
        || prediction.probabilities.len() != count
        || prediction.eligible.len() != count
        || prediction.relevant.len() != count
        || prediction.scores.iter().any(|value| !value.is_finite())
        || prediction
            .probabilities
            .iter()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
        || !prediction.confidence.is_finite()
        || !(0.0..=1.0).contains(&prediction.confidence)
        || prediction
            .predicted_candidate_ordinal
            .is_some_and(|value| value as usize >= count || !prediction.eligible[value as usize])
        || prediction
            .reference_scores
            .as_ref()
            .is_some_and(|scores| scores.len() != count || scores.iter().any(|v| !v.is_finite()))
        || !prediction.eligible.iter().any(|&value| value)
        || !prediction.relevant.iter().any(|&value| value)
        || prediction.policy_outcomes.as_ref().is_some_and(|outcomes| {
            outcomes.len() != count
                || outcomes.iter().any(|outcome| {
                    outcome.authority_id.trim().is_empty()
                        || outcome
                            .reward_micros
                            .iter()
                            .any(|reward| !(-1_000_000..=1_000_000).contains(reward))
                        || !(-1_000_000..=1_000_000).contains(&outcome.future_stability_micros)
                })
        })
    {
        return Err(NativeDecisionEvaluationError::InvalidInput("prediction"));
    }
    Ok(())
}

fn selected_local(
    tables: &FrozenDecisionTrajectoryTables,
    record: &FrozenDecisionRecord,
) -> Result<usize, NativeDecisionEvaluationError> {
    let selected = tables
        .selected_actions
        .get(record.selected_label_ordinal as usize)
        .ok_or(NativeDecisionEvaluationError::InvalidInput(
            "selected action",
        ))?;
    usize::try_from(
        selected
            .selected_candidate_ordinal
            .checked_sub(record.candidate_actions.offset)
            .ok_or(NativeDecisionEvaluationError::InvalidInput(
                "selected candidate range",
            ))?,
    )
    .map_err(|_| NativeDecisionEvaluationError::InvalidInput("selected candidate"))
}

fn selected_kind(
    tables: &FrozenDecisionTrajectoryTables,
    record: &FrozenDecisionRecord,
) -> Result<GraphDecisionActionKind, NativeDecisionEvaluationError> {
    Ok(tables
        .selected_actions
        .get(record.selected_label_ordinal as usize)
        .ok_or(NativeDecisionEvaluationError::InvalidInput(
            "selected action",
        ))?
        .action
        .kind())
}

fn candidate_kind(
    tables: &FrozenDecisionTrajectoryTables,
    record: &FrozenDecisionRecord,
    local: usize,
) -> Result<GraphDecisionActionKind, NativeDecisionEvaluationError> {
    let global = record.candidate_actions.offset as usize + local;
    Ok(tables
        .candidate_actions
        .get(global)
        .ok_or(NativeDecisionEvaluationError::InvalidInput(
            "candidate action",
        ))?
        .action
        .kind())
}

fn average_tie_rank(scores: &[f32], eligible: &[bool], selected: usize) -> f64 {
    if !eligible[selected] {
        return eligible.iter().filter(|&&value| value).count() as f64 + 1.0;
    }
    let score = scores[selected];
    let greater = scores
        .iter()
        .zip(eligible)
        .filter(|(value, include)| **include && **value > score)
        .count();
    let tied_others = scores
        .iter()
        .zip(eligible)
        .enumerate()
        .filter(|(index, (value, include))| *index != selected && **include && **value == score)
        .count();
    1.0 + greater as f64 + tied_others as f64 * 0.5
}

fn fractional_hit(scores: &[f32], eligible: &[bool], selected: usize, cutoff: u32) -> f64 {
    if !eligible[selected] {
        return 0.0;
    }
    let score = scores[selected];
    let greater = scores
        .iter()
        .zip(eligible)
        .filter(|(value, include)| **include && **value > score)
        .count();
    let tied = scores
        .iter()
        .zip(eligible)
        .filter(|(value, include)| **include && **value == score)
        .count();
    ((cutoff as i64 - greater as i64) as f64 / tied as f64).clamp(0.0, 1.0)
}

fn recall_at_k(
    tables: &FrozenDecisionTrajectoryTables,
    record: &FrozenDecisionRecord,
    prediction: &NativeDecisionPrediction,
    cutoff: u32,
) -> Result<f64, NativeDecisionEvaluationError> {
    let mut order = (0..prediction.scores.len())
        .filter(|&index| prediction.eligible[index])
        .collect::<Vec<_>>();
    order.sort_unstable_by(|&left, &right| {
        prediction.scores[right]
            .total_cmp(&prediction.scores[left])
            .then_with(|| {
                let offset = record.candidate_actions.offset as usize;
                tables.candidate_actions[offset + left]
                    .action_identity
                    .cmp(&tables.candidate_actions[offset + right].action_identity)
            })
    });
    let relevant = order
        .iter()
        .filter(|&&index| prediction.relevant[index])
        .count();
    if relevant == 0 {
        return Ok(0.0);
    }
    Ok(order
        .iter()
        .take(cutoff as usize)
        .filter(|&&index| prediction.relevant[index])
        .count() as f64
        / relevant as f64)
}

fn ndcg_at_k(
    tables: &FrozenDecisionTrajectoryTables,
    record: &FrozenDecisionRecord,
    prediction: &NativeDecisionPrediction,
    cutoff: u32,
) -> Result<f64, NativeDecisionEvaluationError> {
    let mut order = (0..prediction.scores.len())
        .filter(|&index| prediction.eligible[index])
        .collect::<Vec<_>>();
    order.sort_unstable_by(|&left, &right| {
        prediction.scores[right]
            .total_cmp(&prediction.scores[left])
            .then_with(|| {
                let offset = record.candidate_actions.offset as usize;
                tables.candidate_actions[offset + left]
                    .action_identity
                    .cmp(&tables.candidate_actions[offset + right].action_identity)
            })
    });
    let dcg = order
        .iter()
        .take(cutoff as usize)
        .enumerate()
        .filter(|(_, index)| prediction.relevant[**index])
        .map(|(rank, _)| 1.0 / ((rank + 2) as f64).log2())
        .sum::<f64>();
    let relevant = order
        .iter()
        .filter(|&&index| prediction.relevant[index])
        .count()
        .min(cutoff as usize);
    let ideal = (0..relevant)
        .map(|rank| 1.0 / ((rank + 2) as f64).log2())
        .sum::<f64>();
    Ok(if ideal == 0.0 { 0.0 } else { dcg / ideal })
}

fn risk_coverage(
    rows: &mut [(f32, CompactString, bool)],
    coverages: &[u16],
) -> Vec<RiskCoveragePoint> {
    rows.sort_unstable_by(|left, right| {
        right
            .0
            .total_cmp(&left.0)
            .then_with(|| left.1.cmp(&right.1))
    });
    coverages
        .iter()
        .map(|&coverage| {
            let retained = (rows.len() as u64 * u64::from(coverage)).div_ceil(10_000);
            let errors = rows
                .iter()
                .take(retained as usize)
                .filter(|(_, _, correct)| !correct)
                .count();
            RiskCoveragePoint {
                requested_coverage_basis_points: coverage,
                retained,
                risk: errors as f64 / retained.max(1) as f64,
            }
        })
        .collect()
}

fn observed_rewards(
    rewards: &GraphDecisionRewardVector,
) -> Result<[i32; 8], NativeDecisionEvaluationError> {
    let mut output = [0_i32; 8];
    for (index, (_, signal)) in rewards.dimensions().into_iter().enumerate() {
        let GraphDecisionRewardSignal::Observed { score_micros, .. } = signal else {
            return Err(NativeDecisionEvaluationError::InvalidInput(
                "pending policy reward",
            ));
        };
        output[index] = *score_micros;
    }
    Ok(output)
}

fn scalarize(rewards: &[i32; 8], policy: &PolicyRewardScalarization) -> i64 {
    rewards
        .iter()
        .zip(policy.weights_micros)
        .map(|(&reward, weight)| i64::from(reward) * i64::from(weight))
        .sum::<i64>()
        / 1_000_000
}

fn slice_key(
    input: &NativeDecisionEvaluationInput,
    dimension: DecisionSliceDimension,
) -> CompactString {
    match dimension {
        DecisionSliceDimension::Temporal => input.slices.temporal.clone(),
        DecisionSliceDimension::RelationFrequency => input.slices.relation_frequency.clone(),
        DecisionSliceDimension::EntityDegree => input.slices.entity_degree.clone(),
        DecisionSliceDimension::EvidenceCount => input.slices.evidence_count.clone(),
        DecisionSliceDimension::ActionFamily => action_kind_name(input.slices.action_family).into(),
    }
}

const fn action_kind_index(kind: GraphDecisionActionKind) -> usize {
    match kind {
        GraphDecisionActionKind::AcceptDelta => 0,
        GraphDecisionActionKind::RejectDelta => 1,
        GraphDecisionActionKind::DeferDelta => 2,
        GraphDecisionActionKind::MergeDelta => 3,
        GraphDecisionActionKind::AttachToEpisode => 4,
        GraphDecisionActionKind::CreateEpisode => 5,
        GraphDecisionActionKind::LinkEvidence => 6,
        GraphDecisionActionKind::ClassifyDiscrepancy => 7,
        GraphDecisionActionKind::ProposeRelation => 8,
        GraphDecisionActionKind::RepairGraphRegion => 9,
        GraphDecisionActionKind::Abstain => 10,
    }
}

const fn action_kind_name(kind: GraphDecisionActionKind) -> &'static str {
    match kind {
        GraphDecisionActionKind::AcceptDelta => "accept_delta",
        GraphDecisionActionKind::RejectDelta => "reject_delta",
        GraphDecisionActionKind::DeferDelta => "defer_delta",
        GraphDecisionActionKind::MergeDelta => "merge_delta",
        GraphDecisionActionKind::AttachToEpisode => "attach_to_episode",
        GraphDecisionActionKind::CreateEpisode => "create_episode",
        GraphDecisionActionKind::LinkEvidence => "link_evidence",
        GraphDecisionActionKind::ClassifyDiscrepancy => "classify_discrepancy",
        GraphDecisionActionKind::ProposeRelation => "propose_relation",
        GraphDecisionActionKind::RepairGraphRegion => "repair_graph_region",
        GraphDecisionActionKind::Abstain => "abstain",
    }
}

fn content_id(value: &impl Serialize) -> Result<CompactString, NativeDecisionEvaluationError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
