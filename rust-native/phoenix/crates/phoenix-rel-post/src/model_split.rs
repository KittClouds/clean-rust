use serde::{Deserialize, Serialize};

pub const MODEL_SPLIT_SCHEMA_VERSION: &str = "phoenix-model-split/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PhoenixModelLane {
    Gliclass,
    ModernBertNli,
    Hybrid,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PhoenixModelRole {
    EvidenceClaimAdjudication,
    FastLabelRouting,
    RelationFrameClassification,
    HallucinationTriage,
    CanonFactAdjudication,
    HumanReviewTriage,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PhoenixModelSplitRule {
    #[serde(default = "default_model_split_schema_version")]
    pub schema_version: String,
    pub role: PhoenixModelRole,
    pub primary_lane: PhoenixModelLane,
    pub nli_truth_vote: bool,
}

fn default_model_split_schema_version() -> String {
    MODEL_SPLIT_SCHEMA_VERSION.to_owned()
}

pub fn default_model_split_contract() -> Vec<PhoenixModelSplitRule> {
    vec![
        PhoenixModelSplitRule {
            schema_version: default_model_split_schema_version(),
            role: PhoenixModelRole::EvidenceClaimAdjudication,
            primary_lane: PhoenixModelLane::ModernBertNli,
            nli_truth_vote: true,
        },
        PhoenixModelSplitRule {
            schema_version: default_model_split_schema_version(),
            role: PhoenixModelRole::FastLabelRouting,
            primary_lane: PhoenixModelLane::Gliclass,
            nli_truth_vote: false,
        },
        PhoenixModelSplitRule {
            schema_version: default_model_split_schema_version(),
            role: PhoenixModelRole::RelationFrameClassification,
            primary_lane: PhoenixModelLane::Gliclass,
            nli_truth_vote: false,
        },
        PhoenixModelSplitRule {
            schema_version: default_model_split_schema_version(),
            role: PhoenixModelRole::HallucinationTriage,
            primary_lane: PhoenixModelLane::Gliclass,
            nli_truth_vote: false,
        },
        PhoenixModelSplitRule {
            schema_version: default_model_split_schema_version(),
            role: PhoenixModelRole::CanonFactAdjudication,
            primary_lane: PhoenixModelLane::ModernBertNli,
            nli_truth_vote: true,
        },
        PhoenixModelSplitRule {
            schema_version: default_model_split_schema_version(),
            role: PhoenixModelRole::HumanReviewTriage,
            primary_lane: PhoenixModelLane::Hybrid,
            nli_truth_vote: true,
        },
    ]
}

pub fn model_lane_for_role(role: PhoenixModelRole) -> PhoenixModelLane {
    default_model_split_contract()
        .into_iter()
        .find(|rule| rule.role == role)
        .map(|rule| rule.primary_lane)
        .unwrap_or(PhoenixModelLane::Hybrid)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn model_split_keeps_truth_votes_on_nli_lane() {
        let contract = default_model_split_contract();
        let canon = contract
            .iter()
            .find(|rule| rule.role == PhoenixModelRole::CanonFactAdjudication)
            .expect("canon rule");
        assert_eq!(canon.primary_lane, PhoenixModelLane::ModernBertNli);
        assert!(canon.nli_truth_vote);

        let relation = contract
            .iter()
            .find(|rule| rule.role == PhoenixModelRole::RelationFrameClassification)
            .expect("relation rule");
        assert_eq!(relation.primary_lane, PhoenixModelLane::Gliclass);
        assert!(!relation.nli_truth_vote);
    }

    #[test]
    fn model_split_serializes_v1_schema() {
        let contract = default_model_split_contract();
        let value = serde_json::to_value(&contract[0]).expect("model split rule json");

        assert_eq!(value["schemaVersion"], MODEL_SPLIT_SCHEMA_VERSION);

        let legacy = serde_json::json!({
            "role": "canonFactAdjudication",
            "primaryLane": "modernBertNli",
            "nliTruthVote": true
        });
        let parsed: PhoenixModelSplitRule =
            serde_json::from_value(legacy).expect("legacy split rule");
        assert_eq!(parsed.schema_version, MODEL_SPLIT_SCHEMA_VERSION);
    }
}
