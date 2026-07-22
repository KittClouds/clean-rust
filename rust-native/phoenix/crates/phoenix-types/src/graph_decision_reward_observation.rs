use std::error::Error;
use std::fmt;

use compact_str::{format_compact, CompactString};
use serde::{Deserialize, Serialize};

use crate::{
    GraphDecisionEvidenceRef, GraphDecisionRewardDimension, NativeDecisionAuthorityClass,
    GRAPH_DECISION_REWARD_SCALE_MICROS,
};

pub const NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionRewardObservationOperation {
    Observe,
    Revise,
    Retract,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionRewardObservationReceipt {
    pub schema_version: u16,
    pub receipt_id: CompactString,
    pub decision_receipt_id: CompactString,
    pub decision_id: CompactString,
    pub candidate_action_identity: CompactString,
    pub truth_link_id: CompactString,
    pub graph_truth_commit_id: CompactString,
    pub dimension: GraphDecisionRewardDimension,
    pub operation: NativeDecisionRewardObservationOperation,
    pub score_micros: Option<i32>,
    pub observed_at: i64,
    pub authority_class: NativeDecisionAuthorityClass,
    pub authority_id: CompactString,
    pub predecessor_observation_receipt_id: Option<CompactString>,
    pub evidence_anchors: Vec<GraphDecisionEvidenceRef>,
}

impl NativeDecisionRewardObservationReceipt {
    pub fn validate(&self) -> Result<(), NativeDecisionRewardObservationError> {
        validate_observation(self, true)
    }
}

pub fn certify_native_decision_reward_observation(
    mut receipt: NativeDecisionRewardObservationReceipt,
) -> Result<NativeDecisionRewardObservationReceipt, NativeDecisionRewardObservationError> {
    receipt.receipt_id = "pending".into();
    validate_observation(&receipt, false)?;
    receipt.receipt_id = content_id(&receipt)?;
    Ok(receipt)
}

fn validate_observation(
    receipt: &NativeDecisionRewardObservationReceipt,
    check_identity: bool,
) -> Result<(), NativeDecisionRewardObservationError> {
    if receipt.schema_version != NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION
        || !is_blake3(&receipt.decision_receipt_id)
        || receipt.decision_id.trim().is_empty()
        || !is_blake3(&receipt.candidate_action_identity)
        || !is_blake3(&receipt.truth_link_id)
        || receipt.graph_truth_commit_id.trim().is_empty()
        || receipt.observed_at <= 0
        || receipt.authority_class == NativeDecisionAuthorityClass::CompilerInference
        || receipt.authority_id.trim().is_empty()
        || receipt.evidence_anchors.is_empty()
    {
        return Err(NativeDecisionRewardObservationError::InvalidContract);
    }
    match receipt.operation {
        NativeDecisionRewardObservationOperation::Observe => {
            if receipt.predecessor_observation_receipt_id.is_some()
                || receipt.score_micros.is_none()
            {
                return Err(NativeDecisionRewardObservationError::InvalidOperation);
            }
        }
        NativeDecisionRewardObservationOperation::Revise => {
            if receipt
                .predecessor_observation_receipt_id
                .as_deref()
                .is_none_or(|value| !is_blake3(value))
                || receipt.score_micros.is_none()
            {
                return Err(NativeDecisionRewardObservationError::InvalidOperation);
            }
        }
        NativeDecisionRewardObservationOperation::Retract => {
            if receipt
                .predecessor_observation_receipt_id
                .as_deref()
                .is_none_or(|value| !is_blake3(value))
                || receipt.score_micros.is_some()
            {
                return Err(NativeDecisionRewardObservationError::InvalidOperation);
            }
        }
    }
    if receipt.score_micros.is_some_and(|score| {
        !(-GRAPH_DECISION_REWARD_SCALE_MICROS..=GRAPH_DECISION_REWARD_SCALE_MICROS).contains(&score)
    }) {
        return Err(NativeDecisionRewardObservationError::ScoreOutOfRange);
    }
    for (index, evidence) in receipt.evidence_anchors.iter().enumerate() {
        if evidence.evidence_id.trim().is_empty()
            || evidence.authority_id.trim().is_empty()
            || evidence.available_at <= 0
            || evidence.available_at > receipt.observed_at
            || receipt.evidence_anchors[..index]
                .iter()
                .any(|prior| prior.evidence_id == evidence.evidence_id)
        {
            return Err(NativeDecisionRewardObservationError::InvalidEvidence);
        }
    }
    if check_identity {
        let mut candidate = receipt.clone();
        let expected = candidate.receipt_id.clone();
        candidate.receipt_id = "pending".into();
        if !is_blake3(&expected) || content_id(&candidate)? != expected {
            return Err(NativeDecisionRewardObservationError::ReceiptIdentity);
        }
    }
    Ok(())
}

fn content_id(
    value: &impl Serialize,
) -> Result<CompactString, NativeDecisionRewardObservationError> {
    let payload = serde_json::to_vec(value)
        .map_err(|error| NativeDecisionRewardObservationError::Json(error.to_string()))?;
    Ok(format_compact!("b3-{}", blake3::hash(&payload).to_hex()))
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NativeDecisionRewardObservationError {
    InvalidContract,
    InvalidOperation,
    ScoreOutOfRange,
    InvalidEvidence,
    ReceiptIdentity,
    Json(String),
}

impl fmt::Display for NativeDecisionRewardObservationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "invalid native decision reward observation: {self:?}"
        )
    }
}

impl Error for NativeDecisionRewardObservationError {}
