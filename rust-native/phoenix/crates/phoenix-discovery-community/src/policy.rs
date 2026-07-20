use crate::CommunityArtifactError;
use phoenix_discovery_view::{DiscoveryNodeKind, DiscoveryRelationFamily, DiscoveryRelationPolicy};
use serde::{Deserialize, Serialize};

const CAUSAL_RELATIONS: [&str; 11] = [
    "causes",
    "caused_by",
    "enables",
    "enabled_by",
    "prevents",
    "prevented_by",
    "motivates",
    "motivated_by",
    "leads_to",
    "results_in",
    "depends_on",
];
const CAUSAL_PREFIXES: [&str; 2] = ["causal:", "causal_"];
const CAUSAL_WEIGHT_MILLIS: u16 = 1_000;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeterministicCommunityPolicy {
    policy_id: String,
    policy_version: String,
    resolution_micros: u32,
    max_local_passes: u16,
    max_levels: u16,
    bridge_participation_weight: u16,
    bridge_boundary_weight: u16,
    bridge_conductance_weight: u16,
}

impl DeterministicCommunityPolicy {
    pub fn phoenix_semantic_core_v1() -> Self {
        Self {
            policy_id: "phoenix-deterministic-semantic-communities".to_owned(),
            policy_version: "1".to_owned(),
            resolution_micros: 1_000_000,
            max_local_passes: 64,
            max_levels: 32,
            bridge_participation_weight: 400,
            bridge_boundary_weight: 400,
            bridge_conductance_weight: 200,
        }
    }

    pub fn policy_id(&self) -> &str {
        &self.policy_id
    }

    pub fn policy_version(&self) -> &str {
        &self.policy_version
    }

    pub(crate) const fn resolution_micros(&self) -> u32 {
        self.resolution_micros
    }

    pub(crate) const fn max_local_passes(&self) -> usize {
        self.max_local_passes as usize
    }

    pub(crate) const fn max_levels(&self) -> usize {
        self.max_levels as usize
    }

    pub(crate) const fn bridge_weights(&self) -> (u16, u16, u16) {
        (
            self.bridge_participation_weight,
            self.bridge_boundary_weight,
            self.bridge_conductance_weight,
        )
    }

    pub(crate) const fn is_core_node(kind: DiscoveryNodeKind) -> bool {
        matches!(
            kind,
            DiscoveryNodeKind::Entity | DiscoveryNodeKind::Event | DiscoveryNodeKind::Episode
        )
    }

    pub(crate) fn relation_weight_millis(
        &self,
        family: DiscoveryRelationFamily,
        relation: &str,
        relation_policy: &DiscoveryRelationPolicy,
    ) -> Option<u16> {
        let family_rule = relation_policy
            .families
            .iter()
            .find(|rule| rule.family == family)?;
        if family_rule.community_eligible {
            return Some(family_rule.traversal_weight_millis);
        }
        (family == DiscoveryRelationFamily::Custom && is_causal_relation(relation))
            .then_some(CAUSAL_WEIGHT_MILLIS)
    }

    pub fn validate(
        &self,
        relation_policy: &DiscoveryRelationPolicy,
    ) -> Result<(), CommunityArtifactError> {
        relation_policy.validate()?;
        if self.policy_id.trim().is_empty()
            || self.policy_version.trim().is_empty()
            || self.resolution_micros == 0
            || self.max_local_passes == 0
            || self.max_levels == 0
        {
            return Err(CommunityArtifactError::Invalid(
                "community policy has an empty identity or zero execution bound".to_owned(),
            ));
        }
        let bridge_total = u32::from(self.bridge_participation_weight)
            + u32::from(self.bridge_boundary_weight)
            + u32::from(self.bridge_conductance_weight);
        if bridge_total != 1_000 {
            return Err(CommunityArtifactError::Invalid(
                "bridge metric weights must sum to 1000".to_owned(),
            ));
        }
        Ok(())
    }

    pub fn digest(
        &self,
        relation_policy: &DiscoveryRelationPolicy,
    ) -> Result<[u8; 32], CommunityArtifactError> {
        self.validate(relation_policy)?;
        let relation_digest = relation_policy.digest()?;
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix-deterministic-community-policy/v1\0");
        hasher.update(self.policy_id.as_bytes());
        hasher.update(&[0]);
        hasher.update(self.policy_version.as_bytes());
        hasher.update(&self.resolution_micros.to_le_bytes());
        hasher.update(&self.max_local_passes.to_le_bytes());
        hasher.update(&self.max_levels.to_le_bytes());
        hasher.update(&self.bridge_participation_weight.to_le_bytes());
        hasher.update(&self.bridge_boundary_weight.to_le_bytes());
        hasher.update(&self.bridge_conductance_weight.to_le_bytes());
        for kind in [
            DiscoveryNodeKind::Entity,
            DiscoveryNodeKind::Event,
            DiscoveryNodeKind::Episode,
        ] {
            hasher.update(&kind.code().to_le_bytes());
        }
        hasher.update(&CAUSAL_WEIGHT_MILLIS.to_le_bytes());
        for relation in CAUSAL_RELATIONS {
            hasher.update(relation.as_bytes());
            hasher.update(&[0]);
        }
        for prefix in CAUSAL_PREFIXES {
            hasher.update(prefix.as_bytes());
            hasher.update(&[0]);
        }
        hasher.update(&relation_digest);
        Ok(*hasher.finalize().as_bytes())
    }
}

fn is_causal_relation(relation: &str) -> bool {
    let relation = relation.to_ascii_lowercase();
    CAUSAL_RELATIONS.contains(&relation.as_str())
        || CAUSAL_PREFIXES
            .iter()
            .any(|prefix| relation.starts_with(prefix))
}
