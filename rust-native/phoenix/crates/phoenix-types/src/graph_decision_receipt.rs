use std::error::Error;
use std::fmt;

use compact_str::{format_compact, CompactString};
use serde::{Deserialize, Serialize};

use crate::{
    GraphDecisionAction, GraphDecisionAuthority, GraphDecisionEvidenceRef,
    GraphDecisionRewardSignal, GraphDecisionRewardVector,
};

pub const NATIVE_DECISION_RECEIPT_SCHEMA_VERSION: u16 = 1;
pub const NATIVE_DECISION_OUTCOME_SCHEMA_VERSION: u16 = 1;
pub const GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionTaskFamily {
    CanonicalEpisodeAssignment,
    DeltaAdjudication,
    DiscrepancyClassification,
    EvidenceRanking,
    RelationCompletion,
    GraphRepair,
    TemporalPrediction,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionAuthorityClass {
    CompilerInference,
    OperatorPreference,
    AuthoritativeGraphOutcome,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionCandidateDisposition {
    Chosen,
    Rejected,
    Deferred,
    Unselected,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionCounterfactualRole {
    RecordedAction,
    HardPlausibleAlternative,
    SafeAbstention,
    MinimalRepair,
    AggressiveRepair,
    EvidenceRichAlternative,
    TemporallyAttractiveInvalidAlternative,
}

impl NativeDecisionCounterfactualRole {
    pub const ALL: [Self; 7] = [
        Self::RecordedAction,
        Self::HardPlausibleAlternative,
        Self::SafeAbstention,
        Self::MinimalRepair,
        Self::AggressiveRepair,
        Self::EvidenceRichAlternative,
        Self::TemporallyAttractiveInvalidAlternative,
    ];
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionHardConstraintViolation {
    FutureInformation,
    IllegalPrecondition,
    GraphInvariant,
    MissingEvidence,
    InsufficientAuthority,
    TemporalOrder,
    UnsupportedAction,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionHardConstraintReceipt {
    pub schema_version: u16,
    pub receipt_id: CompactString,
    pub policy_id: CompactString,
    pub evaluated_at: i64,
    pub passed: bool,
    pub violations: Vec<GraphDecisionHardConstraintViolation>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionAuthorityBridge {
    pub source_authority_id: CompactString,
    pub research_authority_id: CompactString,
    pub source_state_receipt_id: CompactString,
    pub bridged_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionCandidateReceipt {
    pub action_identity: CompactString,
    pub action: GraphDecisionAction,
    pub disposition: NativeDecisionCandidateDisposition,
    pub counterfactual_role: Option<NativeDecisionCounterfactualRole>,
    pub source_labels: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionReceipt {
    pub schema_version: u16,
    pub receipt_id: CompactString,
    pub decision_id: CompactString,
    pub task_family: NativeDecisionTaskFamily,
    pub scope_key: CompactString,
    pub lineage_ids: Vec<CompactString>,
    pub observed_at: i64,
    pub label_available_at: i64,
    pub pre_state_snapshot_id: CompactString,
    pub candidate_set_id: CompactString,
    pub generator_id: CompactString,
    pub generator_version: CompactString,
    pub generator_input_id: CompactString,
    pub invalid_candidates_rejected: u32,
    pub generation_latency_ns: u64,
    pub allocation_volume_bytes: u64,
    pub candidates: Vec<NativeDecisionCandidateReceipt>,
    pub chosen_candidate_ordinal: u32,
    pub authority: GraphDecisionAuthority,
    pub authority_class: NativeDecisionAuthorityClass,
    pub evidence_anchors: Vec<GraphDecisionEvidenceRef>,
    pub bridge: NativeDecisionAuthorityBridge,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum NativeDecisionEffect {
    NoChange {
        post_state_snapshot_id: CompactString,
    },
    GraphMutation {
        post_state_snapshot_id: CompactString,
        before_delta_id: CompactString,
        after_delta_id: CompactString,
        graph_truth_commit_id: CompactString,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionOutcomeOperation {
    Observe,
    Revise,
    Retract,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionOutcomeReceipt {
    pub schema_version: u16,
    pub receipt_id: CompactString,
    pub decision_receipt_id: CompactString,
    pub decision_id: CompactString,
    pub candidate_action_identity: CompactString,
    pub operation: NativeDecisionOutcomeOperation,
    pub observed_at: i64,
    pub authority_class: NativeDecisionAuthorityClass,
    pub outcome_authority_id: CompactString,
    pub reward_vector: Option<GraphDecisionRewardVector>,
    pub hard_constraints: GraphDecisionHardConstraintReceipt,
    pub effect: Option<NativeDecisionEffect>,
    pub predecessor_outcome_receipt_id: Option<CompactString>,
    pub evidence_anchors: Vec<GraphDecisionEvidenceRef>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeResolvedDecisionCandidate {
    pub candidate: NativeDecisionCandidateReceipt,
    pub outcome: NativeDecisionOutcomeReceipt,
}

impl NativeDecisionReceipt {
    pub fn counterfactual_complete(&self) -> bool {
        if self.candidates.len() != NativeDecisionCounterfactualRole::ALL.len() {
            return false;
        }
        let mut roles = self
            .candidates
            .iter()
            .filter_map(|candidate| candidate.counterfactual_role)
            .collect::<Vec<_>>();
        roles.sort_unstable_by_key(|role| *role as u8);
        roles == NativeDecisionCounterfactualRole::ALL
    }

    pub fn validate(&self) -> Result<(), NativeDecisionReceiptError> {
        validate_decision_receipt(self, true)
    }
}

impl GraphDecisionHardConstraintReceipt {
    pub fn validate(&self) -> Result<(), NativeDecisionReceiptError> {
        validate_hard_constraints(self, true)
    }
}

impl NativeDecisionOutcomeReceipt {
    pub fn validate(&self) -> Result<(), NativeDecisionReceiptError> {
        validate_outcome_receipt(self, true)
    }
}

pub fn graph_decision_action_identity(
    action: &GraphDecisionAction,
) -> Result<CompactString, NativeDecisionReceiptError> {
    let mut value = serde_json::to_value(action)?;
    if let Some(header) = value
        .get_mut("parameters")
        .and_then(|parameters| parameters.get_mut("header"))
        .and_then(serde_json::Value::as_object_mut)
    {
        header.insert("approval".to_owned(), serde_json::Value::Null);
    }
    content_id(&value)
}

pub fn native_decision_candidate_set_identity(
    candidates: &[NativeDecisionCandidateReceipt],
) -> Result<CompactString, NativeDecisionReceiptError> {
    let identities = candidates
        .iter()
        .map(|candidate| candidate.action_identity.as_str())
        .collect::<Vec<_>>();
    content_id(&("phoenix-native-decision-candidates/v1", identities))
}

pub fn certify_graph_decision_hard_constraints(
    mut receipt: GraphDecisionHardConstraintReceipt,
) -> Result<GraphDecisionHardConstraintReceipt, NativeDecisionReceiptError> {
    validate_hard_constraints(&receipt, false)?;
    receipt.receipt_id = "pending".into();
    receipt.receipt_id = content_id(&receipt)?;
    Ok(receipt)
}

pub fn certify_native_decision_receipt(
    mut receipt: NativeDecisionReceipt,
) -> Result<NativeDecisionReceipt, NativeDecisionReceiptError> {
    receipt.candidate_set_id = native_decision_candidate_set_identity(&receipt.candidates)?;
    receipt.receipt_id = "pending".into();
    validate_decision_receipt(&receipt, false)?;
    receipt.receipt_id = content_id(&receipt)?;
    Ok(receipt)
}

pub fn certify_native_decision_outcome_receipt(
    mut receipt: NativeDecisionOutcomeReceipt,
) -> Result<NativeDecisionOutcomeReceipt, NativeDecisionReceiptError> {
    receipt.receipt_id = "pending".into();
    validate_outcome_receipt(&receipt, false)?;
    receipt.receipt_id = content_id(&receipt)?;
    Ok(receipt)
}

pub fn resolve_complete_native_decision_outcomes(
    decision: &NativeDecisionReceipt,
    outcomes: &[NativeDecisionOutcomeReceipt],
    frozen_at: i64,
) -> Result<Vec<NativeResolvedDecisionCandidate>, NativeDecisionReceiptError> {
    decision.validate()?;
    if frozen_at < decision.label_available_at {
        return Err(NativeDecisionReceiptError::FutureOutcome);
    }
    let mut resolved = Vec::with_capacity(decision.candidates.len());
    for candidate in &decision.candidates {
        let mut rows = outcomes
            .iter()
            .filter(|outcome| {
                outcome.decision_receipt_id == decision.receipt_id
                    && outcome.candidate_action_identity == candidate.action_identity
                    && outcome.observed_at <= frozen_at
            })
            .collect::<Vec<_>>();
        if rows.is_empty() {
            return Err(NativeDecisionReceiptError::MissingCandidateOutcome(
                candidate.action_identity.clone(),
            ));
        }
        rows.sort_unstable_by_key(|outcome| outcome.observed_at);
        validate_outcome_chain(decision, candidate, &rows)?;
        let terminal = rows.last().expect("non-empty outcome chain");
        if terminal.operation == NativeDecisionOutcomeOperation::Retract {
            return Err(NativeDecisionReceiptError::RetractedCandidateOutcome(
                candidate.action_identity.clone(),
            ));
        }
        if terminal.reward_vector.is_none() {
            return Err(NativeDecisionReceiptError::IncompleteReward);
        }
        resolved.push(NativeResolvedDecisionCandidate {
            candidate: candidate.clone(),
            outcome: (*terminal).clone(),
        });
    }
    Ok(resolved)
}

fn validate_decision_receipt(
    receipt: &NativeDecisionReceipt,
    check_identity: bool,
) -> Result<(), NativeDecisionReceiptError> {
    if receipt.schema_version != NATIVE_DECISION_RECEIPT_SCHEMA_VERSION
        || receipt.decision_id.trim().is_empty()
        || receipt.scope_key.trim().is_empty()
        || receipt.lineage_ids.is_empty()
        || receipt.observed_at <= 0
        || receipt.label_available_at < receipt.observed_at
        || !is_blake3(&receipt.pre_state_snapshot_id)
        || receipt.generator_id.trim().is_empty()
        || receipt.generator_version.trim().is_empty()
        || !is_blake3(&receipt.generator_input_id)
        || receipt.generation_latency_ns == 0
        || receipt.candidates.len() < 2
        || receipt.chosen_candidate_ordinal as usize >= receipt.candidates.len()
        || receipt.bridge.source_authority_id.trim().is_empty()
        || receipt.bridge.research_authority_id.trim().is_empty()
        || !is_blake3(&receipt.bridge.source_state_receipt_id)
        || receipt.bridge.bridged_at < receipt.observed_at
    {
        return Err(NativeDecisionReceiptError::InvalidDecisionContract);
    }
    validate_unique_ids(&receipt.lineage_ids)?;
    validate_evidence(&receipt.evidence_anchors, receipt.observed_at)?;
    let expected_set = native_decision_candidate_set_identity(&receipt.candidates)?;
    if expected_set != receipt.candidate_set_id {
        return Err(NativeDecisionReceiptError::CandidateSetIdentity);
    }
    let mut action_ids = Vec::with_capacity(receipt.candidates.len());
    let mut chosen = 0_usize;
    for (index, candidate) in receipt.candidates.iter().enumerate() {
        candidate.action.validate_candidate()?;
        let header = candidate.action.header();
        if header.decision_id != receipt.decision_id
            || header.pre_state_id != receipt.pre_state_snapshot_id
            || header.decided_at != receipt.observed_at
            || header.authority != receipt.authority
            || header.approval.is_some()
            || graph_decision_action_identity(&candidate.action)? != candidate.action_identity
            || candidate.source_labels.is_empty()
            || action_ids.contains(&candidate.action_identity)
        {
            return Err(NativeDecisionReceiptError::InvalidCandidate(index));
        }
        action_ids.push(candidate.action_identity.clone());
        if candidate.disposition == NativeDecisionCandidateDisposition::Chosen {
            chosen += 1;
            if index != receipt.chosen_candidate_ordinal as usize {
                return Err(NativeDecisionReceiptError::ChosenCandidate);
            }
        }
    }
    if chosen != 1 {
        return Err(NativeDecisionReceiptError::ChosenCandidate);
    }
    if check_identity {
        let mut candidate = receipt.clone();
        let expected = candidate.receipt_id.clone();
        candidate.receipt_id = "pending".into();
        if !is_blake3(&expected) || content_id(&candidate)? != expected {
            return Err(NativeDecisionReceiptError::ReceiptIdentity);
        }
    }
    Ok(())
}

fn validate_outcome_receipt(
    receipt: &NativeDecisionOutcomeReceipt,
    check_identity: bool,
) -> Result<(), NativeDecisionReceiptError> {
    if receipt.schema_version != NATIVE_DECISION_OUTCOME_SCHEMA_VERSION
        || !is_blake3(&receipt.decision_receipt_id)
        || receipt.decision_id.trim().is_empty()
        || !is_blake3(&receipt.candidate_action_identity)
        || receipt.observed_at <= 0
        || receipt.authority_class == NativeDecisionAuthorityClass::CompilerInference
        || receipt.outcome_authority_id.trim().is_empty()
    {
        return Err(NativeDecisionReceiptError::InvalidOutcomeContract);
    }
    validate_evidence(&receipt.evidence_anchors, receipt.observed_at)?;
    validate_hard_constraints(&receipt.hard_constraints, true)?;
    if receipt.hard_constraints.evaluated_at > receipt.observed_at {
        return Err(NativeDecisionReceiptError::FutureOutcome);
    }
    match receipt.operation {
        NativeDecisionOutcomeOperation::Observe => {
            if receipt.predecessor_outcome_receipt_id.is_some() {
                return Err(NativeDecisionReceiptError::InvalidOutcomeOperation);
            }
        }
        NativeDecisionOutcomeOperation::Revise => {
            if receipt
                .predecessor_outcome_receipt_id
                .as_deref()
                .is_none_or(|value| !is_blake3(value))
                || receipt.reward_vector.is_none()
            {
                return Err(NativeDecisionReceiptError::InvalidOutcomeOperation);
            }
        }
        NativeDecisionOutcomeOperation::Retract => {
            if receipt
                .predecessor_outcome_receipt_id
                .as_deref()
                .is_none_or(|value| !is_blake3(value))
                || receipt.reward_vector.is_some()
                || receipt.effect.is_some()
            {
                return Err(NativeDecisionReceiptError::InvalidOutcomeOperation);
            }
        }
    }
    if let Some(reward) = &receipt.reward_vector {
        reward.validate()?;
        if reward.decision_id != receipt.decision_id || !reward_is_fully_observed(reward) {
            return Err(NativeDecisionReceiptError::IncompleteReward);
        }
        for (_, signal) in reward.dimensions() {
            let GraphDecisionRewardSignal::Observed { observed_at, .. } = signal else {
                return Err(NativeDecisionReceiptError::IncompleteReward);
            };
            if *observed_at > receipt.observed_at {
                return Err(NativeDecisionReceiptError::FutureOutcome);
            }
        }
    }
    if let Some(effect) = &receipt.effect {
        validate_effect(effect)?;
    }
    if check_identity {
        let mut candidate = receipt.clone();
        let expected = candidate.receipt_id.clone();
        candidate.receipt_id = "pending".into();
        if !is_blake3(&expected) || content_id(&candidate)? != expected {
            return Err(NativeDecisionReceiptError::ReceiptIdentity);
        }
    }
    Ok(())
}

fn validate_outcome_chain(
    decision: &NativeDecisionReceipt,
    candidate: &NativeDecisionCandidateReceipt,
    rows: &[&NativeDecisionOutcomeReceipt],
) -> Result<(), NativeDecisionReceiptError> {
    for (index, outcome) in rows.iter().enumerate() {
        outcome.validate()?;
        if outcome.decision_id != decision.decision_id {
            return Err(NativeDecisionReceiptError::OutcomeDecisionMismatch);
        }
        match index {
            0 if outcome.operation != NativeDecisionOutcomeOperation::Observe => {
                return Err(NativeDecisionReceiptError::BrokenOutcomeLineage)
            }
            0 => {}
            _ if outcome.observed_at <= rows[index - 1].observed_at => {
                return Err(NativeDecisionReceiptError::BrokenOutcomeLineage)
            }
            _ if outcome.predecessor_outcome_receipt_id.as_ref()
                != Some(&rows[index - 1].receipt_id) =>
            {
                return Err(NativeDecisionReceiptError::BrokenOutcomeLineage)
            }
            _ => {}
        }
    }
    if rows
        .iter()
        .any(|row| row.candidate_action_identity != candidate.action_identity)
    {
        return Err(NativeDecisionReceiptError::OutcomeDecisionMismatch);
    }
    Ok(())
}

fn validate_hard_constraints(
    receipt: &GraphDecisionHardConstraintReceipt,
    check_identity: bool,
) -> Result<(), NativeDecisionReceiptError> {
    let mut unique = Vec::with_capacity(receipt.violations.len());
    if receipt.schema_version != GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION
        || receipt.policy_id.trim().is_empty()
        || receipt.evaluated_at <= 0
        || receipt.passed != receipt.violations.is_empty()
        || receipt.violations.iter().any(|value| {
            let duplicate = unique.contains(value);
            unique.push(*value);
            duplicate
        })
    {
        return Err(NativeDecisionReceiptError::InvalidHardConstraints);
    }
    if check_identity {
        let mut candidate = receipt.clone();
        let expected = candidate.receipt_id.clone();
        candidate.receipt_id = "pending".into();
        if !is_blake3(&expected) || content_id(&candidate)? != expected {
            return Err(NativeDecisionReceiptError::ReceiptIdentity);
        }
    }
    Ok(())
}

fn validate_effect(effect: &NativeDecisionEffect) -> Result<(), NativeDecisionReceiptError> {
    let valid = match effect {
        NativeDecisionEffect::NoChange {
            post_state_snapshot_id,
        } => is_blake3(post_state_snapshot_id),
        NativeDecisionEffect::GraphMutation {
            post_state_snapshot_id,
            before_delta_id,
            after_delta_id,
            graph_truth_commit_id,
        } => {
            is_blake3(post_state_snapshot_id)
                && is_blake3(before_delta_id)
                && is_blake3(after_delta_id)
                && is_blake3(graph_truth_commit_id)
        }
    };
    if !valid {
        return Err(NativeDecisionReceiptError::InvalidEffect);
    }
    Ok(())
}

fn validate_evidence(
    evidence: &[GraphDecisionEvidenceRef],
    available_at: i64,
) -> Result<(), NativeDecisionReceiptError> {
    for (index, row) in evidence.iter().enumerate() {
        if row.evidence_id.trim().is_empty()
            || row.authority_id.trim().is_empty()
            || row.available_at <= 0
            || row.available_at > available_at
            || evidence[..index]
                .iter()
                .any(|prior| prior.evidence_id == row.evidence_id)
        {
            return Err(NativeDecisionReceiptError::InvalidEvidence);
        }
    }
    Ok(())
}

fn validate_unique_ids(values: &[CompactString]) -> Result<(), NativeDecisionReceiptError> {
    for (index, value) in values.iter().enumerate() {
        if value.trim().is_empty() || values[..index].contains(value) {
            return Err(NativeDecisionReceiptError::InvalidLineage);
        }
    }
    Ok(())
}

fn reward_is_fully_observed(reward: &GraphDecisionRewardVector) -> bool {
    reward
        .dimensions()
        .iter()
        .all(|(_, signal)| matches!(signal, GraphDecisionRewardSignal::Observed { .. }))
}

fn content_id(value: &impl Serialize) -> Result<CompactString, NativeDecisionReceiptError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NativeDecisionReceiptError {
    InvalidDecisionContract,
    InvalidOutcomeContract,
    InvalidCandidate(usize),
    CandidateSetIdentity,
    ChosenCandidate,
    InvalidEvidence,
    InvalidLineage,
    InvalidHardConstraints,
    InvalidOutcomeOperation,
    IncompleteReward,
    FutureOutcome,
    InvalidEffect,
    ReceiptIdentity,
    OutcomeDecisionMismatch,
    BrokenOutcomeLineage,
    MissingCandidateOutcome(CompactString),
    RetractedCandidateOutcome(CompactString),
    Action(crate::GraphDecisionValidationError),
    Reward(crate::GraphDecisionRewardError),
    Json(String),
}

impl fmt::Display for NativeDecisionReceiptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid native decision receipt: {self:?}")
    }
}

impl Error for NativeDecisionReceiptError {}

impl From<crate::GraphDecisionValidationError> for NativeDecisionReceiptError {
    fn from(error: crate::GraphDecisionValidationError) -> Self {
        Self::Action(error)
    }
}

impl From<crate::GraphDecisionRewardError> for NativeDecisionReceiptError {
    fn from(error: crate::GraphDecisionRewardError) -> Self {
        Self::Reward(error)
    }
}

impl From<serde_json::Error> for NativeDecisionReceiptError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error.to_string())
    }
}

#[cfg(test)]
#[path = "graph_decision_receipt_tests.rs"]
mod tests;
