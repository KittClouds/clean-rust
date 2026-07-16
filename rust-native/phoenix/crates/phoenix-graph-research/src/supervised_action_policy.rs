use compact_str::{format_compact, CompactString};
use phoenix_types::GraphDecisionActionKind;
use serde::{Deserialize, Serialize};

use crate::{
    validate_counterfactual_candidate_groups, validate_native_rgcn_multitask_identity,
    CounterfactualCandidateGroupsError, FrozenCounterfactualCandidateGroups,
    NativeRgcnMultitaskIdentity, NativeRgcnMultitaskPromotionCertificate,
    SUPERVISED_GRAPH_ACTION_POLICY_SCHEMA,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisedActionRankingLoss {
    RecordedActionGroupCrossEntropy,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisedActionCalibration {
    ValidationTemperatureScaling,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisedGraphActionPolicyLaunchGate {
    pub gate_id: CompactString,
    pub counterfactual_dataset_id: CompactString,
    pub workhorse_model_identity: CompactString,
    pub workhorse_promotion_certificate_id: CompactString,
    pub group_count: u64,
    pub fully_observed_candidate_count: u64,
    pub authorized: bool,
    pub reason: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisedGraphActionPolicyIdentity {
    pub schema_version: CompactString,
    pub policy_identity: CompactString,
    pub launch_gate_id: CompactString,
    pub counterfactual_dataset_id: CompactString,
    pub workhorse_model_identity: CompactString,
    pub workhorse_promotion_certificate_id: CompactString,
    pub evaluator_protocol_id: CompactString,
    pub action_vocabulary: Vec<GraphDecisionActionKind>,
    pub ranking_loss: SupervisedActionRankingLoss,
    pub calibration: SupervisedActionCalibration,
    pub abstention_label_policy_id: CompactString,
    pub seed: u64,
    pub optimizer_identity: CompactString,
    pub clipping_partition_identity: CompactString,
    pub batch_schedule_identity: CompactString,
    pub checkpoint_selection_rule: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisedGraphActionPolicyMetrics {
    pub filtered_mrr_micros: u32,
    pub hits_at_1_micros: u32,
    pub brier_micros: u32,
    pub log_loss_micros: u32,
    pub calibration_error_micros: u32,
    pub abstention_risk_micros: u32,
    pub abstention_coverage_basis_points: u16,
    pub mean_reward_micros: i64,
    pub mean_regret_micros: u64,
    pub hard_constraint_violations: u64,
    pub unsupported_action_count: u64,
    pub unnecessary_edit_cost_micros: u64,
    pub future_stability_micros: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisedGraphActionPolicyEvidence {
    pub evaluation_report_id: CompactString,
    pub strongest_baseline_id: CompactString,
    pub certified_seed_count: u16,
    pub policy_metrics: SupervisedGraphActionPolicyMetrics,
    pub behavior_policy_metrics: SupervisedGraphActionPolicyMetrics,
    pub beats_strongest_baseline: bool,
    pub action_probabilities_calibrated: bool,
    pub abstention_trained: bool,
    pub paired_query_improvement: bool,
    pub weights_reproduced: bool,
    pub certificates_reproduced: bool,
    pub cold_restart_passed: bool,
    pub future_leakage_rejected: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisedGraphActionPolicyCertificate {
    pub certificate_id: CompactString,
    pub policy_identity: CompactString,
    pub evaluation_report_id: CompactString,
    pub anchor_metrics: SupervisedGraphActionPolicyMetrics,
    pub behavior_policy_metrics: SupervisedGraphActionPolicyMetrics,
    pub promoted_as_anchor: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphActionPolicyNonRegressionCertificate {
    pub certificate_id: CompactString,
    pub supervised_anchor_certificate_id: CompactString,
    pub candidate_policy_id: CompactString,
    pub candidate_metrics: SupervisedGraphActionPolicyMetrics,
    pub passed: bool,
}

pub fn certify_supervised_graph_action_launch(
    dataset: &FrozenCounterfactualCandidateGroups,
    workhorse: &NativeRgcnMultitaskIdentity,
    promotion: &NativeRgcnMultitaskPromotionCertificate,
) -> Result<SupervisedGraphActionPolicyLaunchGate, CounterfactualCandidateGroupsError> {
    validate_counterfactual_candidate_groups(dataset)?;
    validate_native_rgcn_multitask_identity(workhorse).map_err(|_| {
        CounterfactualCandidateGroupsError::InvalidInput("workhorse model identity")
    })?;
    let mut promotion_candidate = promotion.clone();
    let promotion_identity = promotion_candidate.certificate_id.clone();
    promotion_candidate.certificate_id = "pending".into();
    let promotion_valid = promotion.promoted
        && promotion.model_identity == workhorse.model_identity
        && is_blake3(&promotion.certificate_id)
        && content_id(&promotion_candidate)? == promotion_identity
        && promotion.head_evidence.len() == crate::NativeRgcnTaskHeadKind::ALL.len()
        && promotion
            .head_evidence
            .iter()
            .all(|row| row.passes(promotion.important_task_regression_limit_basis_points));
    if !promotion_valid {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "workhorse promotion certificate",
        ));
    }
    let mut gate = SupervisedGraphActionPolicyLaunchGate {
        gate_id: "pending".into(),
        counterfactual_dataset_id: dataset.dataset_id.clone(),
        workhorse_model_identity: workhorse.model_identity.clone(),
        workhorse_promotion_certificate_id: promotion.certificate_id.clone(),
        group_count: dataset.groups.len() as u64,
        fully_observed_candidate_count: dataset.certificate.fully_observed_reward_vectors,
        authorized: true,
        reason: "counterfactual outcomes and promoted workhorse certified".into(),
    };
    gate.gate_id = content_id(&gate)?;
    Ok(gate)
}

pub fn certify_supervised_graph_action_policy_identity(
    gate: &SupervisedGraphActionPolicyLaunchGate,
    mut identity: SupervisedGraphActionPolicyIdentity,
) -> Result<SupervisedGraphActionPolicyIdentity, CounterfactualCandidateGroupsError> {
    let mut gate_candidate = gate.clone();
    let gate_identity = gate_candidate.gate_id.clone();
    gate_candidate.gate_id = "pending".into();
    if content_id(&gate_candidate)? != gate_identity
        || !gate.authorized
        || !is_blake3(&gate.gate_id)
        || identity.schema_version != SUPERVISED_GRAPH_ACTION_POLICY_SCHEMA
        || identity.launch_gate_id != gate.gate_id
        || identity.counterfactual_dataset_id != gate.counterfactual_dataset_id
        || identity.workhorse_model_identity != gate.workhorse_model_identity
        || identity.workhorse_promotion_certificate_id != gate.workhorse_promotion_certificate_id
        || !is_blake3(&identity.evaluator_protocol_id)
        || identity.action_vocabulary != GraphDecisionActionKind::ALL
        || identity.abstention_label_policy_id.trim().is_empty()
        || !is_blake3(&identity.optimizer_identity)
        || !is_blake3(&identity.clipping_partition_identity)
        || !is_blake3(&identity.batch_schedule_identity)
        || identity.checkpoint_selection_rule.trim().is_empty()
    {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "supervised policy identity",
        ));
    }
    identity.policy_identity = "pending".into();
    identity.policy_identity = content_id(&identity)?;
    Ok(identity)
}

pub fn certify_supervised_graph_action_anchor(
    identity: &SupervisedGraphActionPolicyIdentity,
    evidence: SupervisedGraphActionPolicyEvidence,
) -> Result<SupervisedGraphActionPolicyCertificate, CounterfactualCandidateGroupsError> {
    validate_policy_identity(identity)?;
    let metrics = &evidence.policy_metrics;
    let behavior = &evidence.behavior_policy_metrics;
    if !is_blake3(&evidence.evaluation_report_id)
        || !is_blake3(&evidence.strongest_baseline_id)
        || evidence.certified_seed_count < 2
        || !evidence.beats_strongest_baseline
        || !evidence.action_probabilities_calibrated
        || !evidence.abstention_trained
        || !evidence.paired_query_improvement
        || !evidence.weights_reproduced
        || !evidence.certificates_reproduced
        || !evidence.cold_restart_passed
        || !evidence.future_leakage_rejected
        || !valid_metrics(metrics)
        || !valid_metrics(behavior)
        || !policy_not_worse_than(metrics, behavior)
    {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "supervised anchor evidence",
        ));
    }
    let mut certificate = SupervisedGraphActionPolicyCertificate {
        certificate_id: "pending".into(),
        policy_identity: identity.policy_identity.clone(),
        evaluation_report_id: evidence.evaluation_report_id,
        anchor_metrics: evidence.policy_metrics,
        behavior_policy_metrics: evidence.behavior_policy_metrics,
        promoted_as_anchor: true,
    };
    certificate.certificate_id = content_id(&certificate)?;
    Ok(certificate)
}

pub fn certify_graph_action_policy_non_regression(
    anchor: &SupervisedGraphActionPolicyCertificate,
    candidate_policy_id: CompactString,
    candidate_metrics: SupervisedGraphActionPolicyMetrics,
) -> Result<GraphActionPolicyNonRegressionCertificate, CounterfactualCandidateGroupsError> {
    let mut anchor_candidate = anchor.clone();
    let anchor_identity = anchor_candidate.certificate_id.clone();
    anchor_candidate.certificate_id = "pending".into();
    if content_id(&anchor_candidate)? != anchor_identity
        || !anchor.promoted_as_anchor
        || !is_blake3(&anchor.certificate_id)
        || !is_blake3(&candidate_policy_id)
        || !valid_metrics(&candidate_metrics)
        || !policy_not_worse_than(&candidate_metrics, &anchor.anchor_metrics)
    {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "policy regressed behind supervised anchor",
        ));
    }
    let mut certificate = GraphActionPolicyNonRegressionCertificate {
        certificate_id: "pending".into(),
        supervised_anchor_certificate_id: anchor.certificate_id.clone(),
        candidate_policy_id,
        candidate_metrics,
        passed: true,
    };
    certificate.certificate_id = content_id(&certificate)?;
    Ok(certificate)
}

fn validate_policy_identity(
    identity: &SupervisedGraphActionPolicyIdentity,
) -> Result<(), CounterfactualCandidateGroupsError> {
    let mut candidate = identity.clone();
    let expected = candidate.policy_identity.clone();
    candidate.policy_identity = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(CounterfactualCandidateGroupsError::Identity(
            "supervised policy identity",
        ));
    }
    Ok(())
}

fn policy_not_worse_than(
    candidate: &SupervisedGraphActionPolicyMetrics,
    reference: &SupervisedGraphActionPolicyMetrics,
) -> bool {
    candidate.filtered_mrr_micros >= reference.filtered_mrr_micros
        && candidate.hits_at_1_micros >= reference.hits_at_1_micros
        && candidate.brier_micros <= reference.brier_micros
        && candidate.log_loss_micros <= reference.log_loss_micros
        && candidate.calibration_error_micros <= reference.calibration_error_micros
        && candidate.abstention_risk_micros <= reference.abstention_risk_micros
        && candidate.abstention_coverage_basis_points >= reference.abstention_coverage_basis_points
        && candidate.mean_reward_micros >= reference.mean_reward_micros
        && candidate.mean_regret_micros <= reference.mean_regret_micros
        && candidate.hard_constraint_violations <= reference.hard_constraint_violations
        && candidate.unsupported_action_count <= reference.unsupported_action_count
        && candidate.unnecessary_edit_cost_micros <= reference.unnecessary_edit_cost_micros
        && candidate.future_stability_micros >= reference.future_stability_micros
}

fn valid_metrics(metrics: &SupervisedGraphActionPolicyMetrics) -> bool {
    metrics.filtered_mrr_micros <= 1_000_000
        && metrics.hits_at_1_micros <= 1_000_000
        && metrics.brier_micros <= 1_000_000
        && metrics.abstention_risk_micros <= 1_000_000
        && metrics.abstention_coverage_basis_points <= 10_000
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn content_id(value: &impl Serialize) -> Result<CompactString, CounterfactualCandidateGroupsError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
