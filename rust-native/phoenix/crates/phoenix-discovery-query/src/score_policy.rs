use crate::DiscoveryQueryError;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryScorePolicy {
    pub policy_id: String,
    pub policy_version: String,
    pub seed_weight_millis: u16,
    pub ppr_weight_millis: u16,
    pub evidence_weight_millis: u16,
    pub confidence_weight_millis: u16,
    pub bridge_weight_millis: u16,
    pub affinity_weight_millis: u16,
    pub temporal_weight_millis: u16,
    pub novelty_bonus_micros: i64,
    pub common_relation_penalty_micros: i64,
    pub path_length_penalty_micros: i64,
    pub redundancy_penalty_micros: i64,
    pub model_boost_ceiling_micros: i64,
}

impl DiscoveryScorePolicy {
    pub fn phoenix_discovery_v1() -> Self {
        Self {
            policy_id: "phoenix-discovery-log-score".to_owned(),
            policy_version: "1".to_owned(),
            seed_weight_millis: 1_000,
            ppr_weight_millis: 750,
            evidence_weight_millis: 500,
            confidence_weight_millis: 1_000,
            bridge_weight_millis: 300,
            affinity_weight_millis: 300,
            temporal_weight_millis: 300,
            novelty_bonus_micros: 125_000,
            common_relation_penalty_micros: 100_000,
            path_length_penalty_micros: 75_000,
            redundancy_penalty_micros: 400_000,
            model_boost_ceiling_micros: 250_000,
        }
    }

    pub fn validate(&self) -> Result<(), DiscoveryQueryError> {
        let weights = [
            self.seed_weight_millis,
            self.ppr_weight_millis,
            self.evidence_weight_millis,
            self.confidence_weight_millis,
            self.bridge_weight_millis,
            self.affinity_weight_millis,
            self.temporal_weight_millis,
        ];
        if self.policy_id.trim().is_empty()
            || self.policy_version.trim().is_empty()
            || weights.iter().any(|weight| *weight > 1_000)
            || self.novelty_bonus_micros < 0
            || self.common_relation_penalty_micros < 0
            || self.path_length_penalty_micros < 0
            || self.redundancy_penalty_micros < 0
            || self.model_boost_ceiling_micros < 0
        {
            return Err(DiscoveryQueryError::Invalid(
                "score policy is outside the fixed-point scoring contract".to_owned(),
            ));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<[u8; 32], DiscoveryQueryError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self)
            .map_err(|error| DiscoveryQueryError::Invalid(error.to_string()))?;
        Ok(*blake3::hash(&bytes).as_bytes())
    }
}
