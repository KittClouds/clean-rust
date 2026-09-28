use std::error::Error;
use std::fmt;

use compact_str::{format_compact, CompactString};
use serde::{Deserialize, Serialize};

use crate::{
    GraphDecisionRewardDimension, NativeDecisionAuthorityClass, GRAPH_DECISION_REWARD_SCALE_MICROS,
};

pub const NATIVE_DECISION_REWARD_EVIDENCE_SCHEMA_VERSION: u16 = 1;
pub const CANONICAL_REWARD_STABILITY_HORIZON_MS: i64 = 24 * 60 * 60 * 1_000;
pub const CANONICAL_HUMAN_EVALUATION_POLICY: &str = "phoenix-canonical-human-evaluation/v1";
pub const CANONICAL_FUTURE_STABILITY_POLICY: &str = "phoenix-canonical-future-stability/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionRewardEvidenceReceipt {
    pub schema_version: u16,
    pub receipt_id: CompactString,
    pub decision_receipt_id: CompactString,
    pub decision_id: CompactString,
    pub candidate_action_identity: CompactString,
    pub truth_link_id: CompactString,
    pub graph_truth_commit_id: CompactString,
    pub dimension: GraphDecisionRewardDimension,
    pub score_micros: i32,
    pub observed_at: i64,
    pub stability_eligible_at: i64,
    pub authority_class: NativeDecisionAuthorityClass,
    pub authority_id: CompactString,
    pub policy_id: CompactString,
    pub lineage_generation: u64,
    pub source_receipt_ids: Vec<CompactString>,
}

impl NativeDecisionRewardEvidenceReceipt {
    pub fn validate(&self) -> Result<(), NativeDecisionRewardEvidenceError> {
        validate_evidence(self, true)
    }
}

pub fn certify_native_decision_reward_evidence(
    mut receipt: NativeDecisionRewardEvidenceReceipt,
) -> Result<NativeDecisionRewardEvidenceReceipt, NativeDecisionRewardEvidenceError> {
    receipt.receipt_id = "pending".into();
    validate_evidence(&receipt, false)?;
    receipt.receipt_id = content_id(&receipt)?;
    Ok(receipt)
}

fn validate_evidence(
    receipt: &NativeDecisionRewardEvidenceReceipt,
    check_identity: bool,
) -> Result<(), NativeDecisionRewardEvidenceError> {
    if receipt.schema_version != NATIVE_DECISION_REWARD_EVIDENCE_SCHEMA_VERSION
        || !is_blake3(&receipt.decision_receipt_id)
        || receipt.decision_id.trim().is_empty()
        || !is_blake3(&receipt.candidate_action_identity)
        || !is_blake3(&receipt.truth_link_id)
        || receipt.graph_truth_commit_id.trim().is_empty()
        || receipt.observed_at <= 0
        || receipt.stability_eligible_at <= 0
        || receipt.authority_id.trim().is_empty()
        || receipt.policy_id.trim().is_empty()
        || receipt.lineage_generation == 0
        || receipt.source_receipt_ids.is_empty()
        || !(-GRAPH_DECISION_REWARD_SCALE_MICROS..=GRAPH_DECISION_REWARD_SCALE_MICROS)
            .contains(&receipt.score_micros)
    {
        return Err(NativeDecisionRewardEvidenceError::InvalidContract);
    }
    match receipt.dimension {
        GraphDecisionRewardDimension::HumanAcceptance
            if receipt.authority_class == NativeDecisionAuthorityClass::OperatorPreference
                && receipt.policy_id == CANONICAL_HUMAN_EVALUATION_POLICY
                && receipt.score_micros == GRAPH_DECISION_REWARD_SCALE_MICROS
                && receipt.observed_at < receipt.stability_eligible_at => {}
        GraphDecisionRewardDimension::FutureStability
            if receipt.authority_class
                == NativeDecisionAuthorityClass::AuthoritativeGraphOutcome
                && receipt.policy_id == CANONICAL_FUTURE_STABILITY_POLICY
                && receipt.observed_at >= receipt.stability_eligible_at
                && receipt.score_micros.unsigned_abs()
                    == GRAPH_DECISION_REWARD_SCALE_MICROS as u32 => {}
        _ => return Err(NativeDecisionRewardEvidenceError::InvalidDimensionAuthority),
    }
    for (index, source) in receipt.source_receipt_ids.iter().enumerate() {
        if source.trim().is_empty() || receipt.source_receipt_ids[..index].contains(source) {
            return Err(NativeDecisionRewardEvidenceError::InvalidSourceReceipts);
        }
    }
    if check_identity {
        let mut candidate = receipt.clone();
        let expected = candidate.receipt_id.clone();
        candidate.receipt_id = "pending".into();
        if !is_blake3(&expected) || content_id(&candidate)? != expected {
            return Err(NativeDecisionRewardEvidenceError::ReceiptIdentity);
        }
    }
    Ok(())
}

fn content_id(value: &impl Serialize) -> Result<CompactString, NativeDecisionRewardEvidenceError> {
    let payload = serde_json::to_vec(value)
        .map_err(|error| NativeDecisionRewardEvidenceError::Json(error.to_string()))?;
    Ok(format_compact!("b3-{}", blake3::hash(&payload).to_hex()))
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NativeDecisionRewardEvidenceError {
    InvalidContract,
    InvalidDimensionAuthority,
    InvalidSourceReceipts,
    ReceiptIdentity,
    Json(String),
}

impl fmt::Display for NativeDecisionRewardEvidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "invalid native decision reward evidence: {self:?}"
        )
    }
}

impl Error for NativeDecisionRewardEvidenceError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn human_and_future_evidence_have_distinct_authority_contracts() {
        let human = certify_native_decision_reward_evidence(fixture(
            GraphDecisionRewardDimension::HumanAcceptance,
            NativeDecisionAuthorityClass::OperatorPreference,
            CANONICAL_HUMAN_EVALUATION_POLICY,
            100,
            GRAPH_DECISION_REWARD_SCALE_MICROS,
        ))
        .expect("human evidence");
        assert!(human.receipt_id.starts_with("b3-"));

        let future = certify_native_decision_reward_evidence(fixture(
            GraphDecisionRewardDimension::FutureStability,
            NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
            CANONICAL_FUTURE_STABILITY_POLICY,
            200,
            -GRAPH_DECISION_REWARD_SCALE_MICROS,
        ))
        .expect("future evidence");
        assert_ne!(human.receipt_id, future.receipt_id);
    }

    fn fixture(
        dimension: GraphDecisionRewardDimension,
        authority_class: NativeDecisionAuthorityClass,
        policy: &str,
        observed_at: i64,
        score_micros: i32,
    ) -> NativeDecisionRewardEvidenceReceipt {
        NativeDecisionRewardEvidenceReceipt {
            schema_version: NATIVE_DECISION_REWARD_EVIDENCE_SCHEMA_VERSION,
            receipt_id: "pending".into(),
            decision_receipt_id: digest('1').into(),
            decision_id: "decision:1".into(),
            candidate_action_identity: digest('2').into(),
            truth_link_id: digest('3').into(),
            graph_truth_commit_id: "commit:1".into(),
            dimension,
            score_micros,
            observed_at,
            stability_eligible_at: 150,
            authority_class,
            authority_id: "authority:1".into(),
            policy_id: policy.into(),
            lineage_generation: 1,
            source_receipt_ids: vec!["source:1".into()],
        }
    }

    fn digest(byte: char) -> String {
        format!("b3-{}", byte.to_string().repeat(64))
    }
}
