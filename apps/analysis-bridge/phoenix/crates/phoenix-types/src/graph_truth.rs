use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;

pub const GRAPH_TRUTH_COMMIT_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphTruthPlane {
    WorldState,
    Reported,
    Conditional,
    Hypothetical,
    Planned,
    Mixed,
    #[default]
    Unknown,
}

impl GraphTruthPlane {
    pub const fn is_assertable(self) -> bool {
        matches!(
            self,
            Self::WorldState
                | Self::Reported
                | Self::Conditional
                | Self::Hypothetical
                | Self::Planned
        )
    }

    pub const fn is_world_state(self) -> bool {
        matches!(self, Self::WorldState)
    }

    pub fn from_modalities<'a>(modalities: impl IntoIterator<Item = &'a str>) -> Self {
        let mut planes = 0_u8;
        for modality in modalities {
            planes |= match modality {
                "asserted" | "observed" | "inferred" | "negated" => 1,
                "reported" | "reportedSpeech" | "attributedClaim" => 1 << 1,
                "conditional" => 1 << 2,
                "hypothetical" => 1 << 3,
                "planned" => 1 << 4,
                _ => 0,
            };
        }

        if planes.count_ones() > 1 {
            return Self::Mixed;
        }
        match planes {
            1 => Self::WorldState,
            2 => Self::Reported,
            4 => Self::Conditional,
            8 => Self::Hypothetical,
            16 => Self::Planned,
            _ => Self::Unknown,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphTruthKind {
    #[default]
    Structural,
    Identity,
    Assertion,
    Temporal,
    Causal,
    Semantic,
}

impl GraphTruthKind {
    pub const fn requires_plane(self) -> bool {
        matches!(
            self,
            Self::Assertion | Self::Temporal | Self::Causal | Self::Semantic
        )
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphTruthOperation {
    #[default]
    Assert,
    Supersede,
    Retract,
    Revert,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphTruthDescriptor {
    pub kind: GraphTruthKind,
    pub plane: Option<GraphTruthPlane>,
}

impl GraphTruthDescriptor {
    pub const fn validate(self) -> Result<(), GraphTruthVocabularyError> {
        if self.kind.requires_plane() {
            return match self.plane {
                Some(plane) if plane.is_assertable() => Ok(()),
                Some(plane) => Err(GraphTruthVocabularyError::NonAssertablePlane(plane)),
                None => Err(GraphTruthVocabularyError::MissingPlane(self.kind)),
            };
        }
        if self.plane.is_some() {
            return Err(GraphTruthVocabularyError::UnexpectedPlane(self.kind));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GraphTruthVocabularyError {
    MissingPlane(GraphTruthKind),
    NonAssertablePlane(GraphTruthPlane),
    UnexpectedPlane(GraphTruthKind),
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct GraphTruthDigest(pub [u8; 32]);

impl GraphTruthDigest {
    pub const fn is_zero(self) -> bool {
        let mut index = 0;
        while index < self.0.len() {
            if self.0[index] != 0 {
                return false;
            }
            index += 1;
        }
        true
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphTruthSourceGenerationRef {
    pub source_id: CompactString,
    pub generation: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphTruthCompilerPolicy {
    pub compiler_id: CompactString,
    pub compiler_version: CompactString,
    pub policy_id: CompactString,
    pub policy_version: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphTruthCommitHeader {
    pub schema_version: u16,
    pub commit_id: CompactString,
    pub generation: u64,
    pub operation: GraphTruthOperation,
    pub truth: GraphTruthDescriptor,
    #[serde(default)]
    pub source_generations: SmallVec<[GraphTruthSourceGenerationRef; 4]>,
    #[serde(default)]
    pub receipt_ids: SmallVec<[CompactString; 4]>,
    pub compiler_policy: GraphTruthCompilerPolicy,
    #[serde(default)]
    pub predecessor_commit_ids: SmallVec<[CompactString; 2]>,
    pub reverses_commit_id: Option<CompactString>,
    pub idempotency_hash: GraphTruthDigest,
    pub committed_at: i64,
}

impl Default for GraphTruthCommitHeader {
    fn default() -> Self {
        Self {
            schema_version: GRAPH_TRUTH_COMMIT_SCHEMA_VERSION,
            commit_id: CompactString::default(),
            generation: 0,
            operation: GraphTruthOperation::Assert,
            truth: GraphTruthDescriptor::default(),
            source_generations: SmallVec::new(),
            receipt_ids: SmallVec::new(),
            compiler_policy: GraphTruthCompilerPolicy::default(),
            predecessor_commit_ids: SmallVec::new(),
            reverses_commit_id: None,
            idempotency_hash: GraphTruthDigest::default(),
            committed_at: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn modality_planes_preserve_epistemic_boundaries() {
        assert_eq!(
            GraphTruthPlane::from_modalities(["asserted"]),
            GraphTruthPlane::WorldState
        );
        assert_eq!(
            GraphTruthPlane::from_modalities(["reportedSpeech"]),
            GraphTruthPlane::Reported
        );
        assert_eq!(
            GraphTruthPlane::from_modalities(["conditional"]),
            GraphTruthPlane::Conditional
        );
        assert_eq!(
            GraphTruthPlane::from_modalities(["hypothetical"]),
            GraphTruthPlane::Hypothetical
        );
        assert_eq!(
            GraphTruthPlane::from_modalities(["planned"]),
            GraphTruthPlane::Planned
        );
        assert_eq!(
            GraphTruthPlane::from_modalities(["observed", "reported"]),
            GraphTruthPlane::Mixed
        );
    }

    #[test]
    fn asserted_kinds_reject_missing_unknown_and_mixed_planes() {
        for plane in [
            None,
            Some(GraphTruthPlane::Unknown),
            Some(GraphTruthPlane::Mixed),
        ] {
            assert!(GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane,
            }
            .validate()
            .is_err());
        }
        for plane in [
            GraphTruthPlane::WorldState,
            GraphTruthPlane::Reported,
            GraphTruthPlane::Conditional,
            GraphTruthPlane::Hypothetical,
            GraphTruthPlane::Planned,
        ] {
            assert!(GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane: Some(plane),
            }
            .validate()
            .is_ok());
        }
    }

    #[test]
    fn speculative_planes_round_trip_without_becoming_world_state() {
        for plane in [
            GraphTruthPlane::Reported,
            GraphTruthPlane::Conditional,
            GraphTruthPlane::Hypothetical,
            GraphTruthPlane::Planned,
        ] {
            let encoded = serde_json::to_vec(&plane).expect("serialize truth plane");
            let decoded: GraphTruthPlane =
                serde_json::from_slice(&encoded).expect("deserialize truth plane");

            assert_eq!(decoded, plane);
            assert!(!decoded.is_world_state());
            assert!(decoded.is_assertable());
        }
    }

    #[test]
    fn structural_and_identity_truth_do_not_accept_planes() {
        assert!(GraphTruthDescriptor {
            kind: GraphTruthKind::Structural,
            plane: None,
        }
        .validate()
        .is_ok());
        assert!(GraphTruthDescriptor {
            kind: GraphTruthKind::Identity,
            plane: Some(GraphTruthPlane::WorldState),
        }
        .validate()
        .is_err());
    }
}
