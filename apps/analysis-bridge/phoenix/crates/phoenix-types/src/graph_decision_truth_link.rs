use std::error::Error;
use std::fmt;

use compact_str::format_compact;
use serde::{Deserialize, Serialize};

pub const NATIVE_DECISION_TRUTH_LINK_SCHEMA: &str = "phoenix-native-decision-truth-link/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionGraphTruthLinkRequest {
    pub schema_version: String,
    pub decision_receipt_id: String,
    pub operator_mutation_receipt_id: String,
    pub graph_truth_commit_id: String,
    pub linked_at: i64,
    pub stability_horizon_ms: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionGraphTruthLink {
    pub schema_version: String,
    pub link_id: String,
    pub decision_id: String,
    pub decision_receipt_id: String,
    pub chosen_action_identity: String,
    pub operator_mutation_receipt_id: String,
    pub graph_truth_commit_id: String,
    pub committed_at: i64,
    pub linked_at: i64,
    pub stability_eligible_at: i64,
    pub reward_complete: bool,
}

pub fn content_address_native_decision_graph_truth_link(
    mut link: NativeDecisionGraphTruthLink,
) -> Result<NativeDecisionGraphTruthLink, NativeDecisionTruthLinkIdentityError> {
    if link.schema_version != NATIVE_DECISION_TRUTH_LINK_SCHEMA
        || link.decision_id.trim().is_empty()
        || !is_blake3(&link.decision_receipt_id)
        || !is_blake3(&link.chosen_action_identity)
        || link.operator_mutation_receipt_id.trim().is_empty()
        || link.graph_truth_commit_id.trim().is_empty()
        || link.committed_at <= 0
        || link.linked_at < link.committed_at
        || link.stability_eligible_at <= link.committed_at
        || link.reward_complete
    {
        return Err(NativeDecisionTruthLinkIdentityError::InvalidContract);
    }
    link.link_id = "pending".to_owned();
    let payload = serde_json::to_vec(&link)
        .map_err(|error| NativeDecisionTruthLinkIdentityError::Json(error.to_string()))?;
    link.link_id = format_compact!("b3-{}", blake3::hash(&payload).to_hex()).to_string();
    Ok(link)
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NativeDecisionTruthLinkIdentityError {
    InvalidContract,
    Json(String),
}

impl fmt::Display for NativeDecisionTruthLinkIdentityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "invalid native decision truth-link identity: {self:?}"
        )
    }
}

impl Error for NativeDecisionTruthLinkIdentityError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truth_link_identity_is_content_addressed_and_requires_an_unfinished_reward() {
        let link = content_address_native_decision_graph_truth_link(NativeDecisionGraphTruthLink {
            schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
            link_id: "pending".to_owned(),
            decision_id: "decision:1".to_owned(),
            decision_receipt_id: digest('1'),
            chosen_action_identity: digest('2'),
            operator_mutation_receipt_id: "operator:1".to_owned(),
            graph_truth_commit_id: "commit:1".to_owned(),
            committed_at: 10,
            linked_at: 11,
            stability_eligible_at: 20,
            reward_complete: false,
        })
        .expect("truth link");
        assert!(link.link_id.starts_with("b3-"));

        let mut invalid = link;
        invalid.reward_complete = true;
        assert!(content_address_native_decision_graph_truth_link(invalid).is_err());
    }

    fn digest(byte: char) -> String {
        format!("b3-{}", byte.to_string().repeat(64))
    }
}
