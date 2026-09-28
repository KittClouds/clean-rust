use crate::DiscoveryViewError;
use phoenix_graph_kernel::KernelRelationClass;
use serde::{Deserialize, Serialize};

#[repr(u16)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiscoveryRelationFamily {
    Structural = 1,
    Semantic = 2,
    Identity = 3,
    Resolution = 4,
    Temporal = 5,
    Calendar = 6,
    Memory = 7,
    Narrative = 8,
    Custom = 9,
}

impl DiscoveryRelationFamily {
    pub const ALL: [Self; 9] = [
        Self::Structural,
        Self::Semantic,
        Self::Identity,
        Self::Resolution,
        Self::Temporal,
        Self::Calendar,
        Self::Memory,
        Self::Narrative,
        Self::Custom,
    ];

    pub const fn code(self) -> u16 {
        self as u16
    }

    pub const fn from_code(code: u16) -> Option<Self> {
        match code {
            1 => Some(Self::Structural),
            2 => Some(Self::Semantic),
            3 => Some(Self::Identity),
            4 => Some(Self::Resolution),
            5 => Some(Self::Temporal),
            6 => Some(Self::Calendar),
            7 => Some(Self::Memory),
            8 => Some(Self::Narrative),
            9 => Some(Self::Custom),
            _ => None,
        }
    }

    pub(crate) fn from_kernel(value: &KernelRelationClass) -> Option<Self> {
        match value {
            KernelRelationClass::Structural => Some(Self::Structural),
            KernelRelationClass::Semantic => Some(Self::Semantic),
            KernelRelationClass::Identity => Some(Self::Identity),
            KernelRelationClass::Resolution => Some(Self::Resolution),
            KernelRelationClass::Temporal => Some(Self::Temporal),
            KernelRelationClass::Calendar => Some(Self::Calendar),
            KernelRelationClass::Memory => Some(Self::Memory),
            KernelRelationClass::Narrative => Some(Self::Narrative),
            KernelRelationClass::Custom => Some(Self::Custom),
            KernelRelationClass::Candidate => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RelationFamilyRule {
    pub family: DiscoveryRelationFamily,
    pub traversal_weight_millis: u16,
    pub community_eligible: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryRelationPolicy {
    pub policy_id: String,
    pub policy_version: String,
    pub families: Vec<RelationFamilyRule>,
}

impl DiscoveryRelationPolicy {
    pub fn phoenix_asserted_v1() -> Self {
        use DiscoveryRelationFamily as Family;
        Self {
            policy_id: "phoenix-asserted-discovery-relations".to_owned(),
            policy_version: "1".to_owned(),
            families: vec![
                rule(Family::Structural, 500, false),
                rule(Family::Semantic, 1_000, true),
                rule(Family::Identity, 750, true),
                rule(Family::Resolution, 250, false),
                rule(Family::Temporal, 1_000, true),
                rule(Family::Calendar, 500, false),
                rule(Family::Memory, 750, true),
                rule(Family::Narrative, 1_000, true),
                rule(Family::Custom, 500, false),
            ],
        }
    }

    pub fn validate(&self) -> Result<(), DiscoveryViewError> {
        if self.policy_id.trim().is_empty() || self.policy_version.trim().is_empty() {
            return Err(DiscoveryViewError::Invalid(
                "relation policy identity is empty".to_owned(),
            ));
        }
        for family in DiscoveryRelationFamily::ALL {
            let matches = self
                .families
                .iter()
                .filter(|rule| rule.family == family)
                .count();
            if matches != 1 {
                return Err(DiscoveryViewError::Invalid(format!(
                    "relation policy must define family {family:?} exactly once"
                )));
            }
        }
        if self
            .families
            .iter()
            .any(|rule| rule.traversal_weight_millis == 0)
        {
            return Err(DiscoveryViewError::Invalid(
                "relation policy contains a zero traversal weight".to_owned(),
            ));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<[u8; 32], DiscoveryViewError> {
        self.validate()?;
        let mut rules = self.families.clone();
        rules.sort_unstable_by_key(|rule| rule.family.code());
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix-discovery-relation-policy/v1\0");
        hasher.update(self.policy_id.as_bytes());
        hasher.update(&[0]);
        hasher.update(self.policy_version.as_bytes());
        for rule in rules {
            hasher.update(&rule.family.code().to_le_bytes());
            hasher.update(&rule.traversal_weight_millis.to_le_bytes());
            hasher.update(&[u8::from(rule.community_eligible)]);
        }
        Ok(*hasher.finalize().as_bytes())
    }
}

fn rule(
    family: DiscoveryRelationFamily,
    traversal_weight_millis: u16,
    community_eligible: bool,
) -> RelationFamilyRule {
    RelationFamilyRule {
        family,
        traversal_weight_millis,
        community_eligible,
    }
}
