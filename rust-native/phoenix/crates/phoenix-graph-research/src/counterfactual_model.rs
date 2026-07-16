use std::path::PathBuf;

use compact_str::CompactString;
use phoenix_types::{
    GraphDecisionAction, GraphDecisionHardConstraintReceipt, GraphDecisionHardConstraintViolation,
    GraphDecisionRewardVector,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{ExactRange, GraphDecisionSplit};

pub const COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA: &str =
    "phoenix-counterfactual-candidate-groups/v1";
pub const COUNTERFACTUAL_CANDIDATE_GROUPS_BINARY_VERSION: u16 = 1;
pub const SUPERVISED_GRAPH_ACTION_POLICY_SCHEMA: &str = "phoenix-supervised-graph-action-policy/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u8)]
pub enum CounterfactualCandidateRole {
    RecordedAction = 1,
    HardPlausibleAlternative = 2,
    SafeAbstention = 3,
    MinimalRepair = 4,
    AggressiveRepair = 5,
    EvidenceRichAlternative = 6,
    TemporallyAttractiveInvalidAlternative = 7,
}

impl CounterfactualCandidateRole {
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

pub type CounterfactualHardConstraintViolation = GraphDecisionHardConstraintViolation;
pub type CounterfactualHardConstraintResult = GraphDecisionHardConstraintReceipt;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CounterfactualCandidateOutcome {
    pub role: CounterfactualCandidateRole,
    pub action_identity: CompactString,
    pub action: GraphDecisionAction,
    pub reward_vector: GraphDecisionRewardVector,
    pub hard_constraints: CounterfactualHardConstraintResult,
    pub outcome_authority_id: CompactString,
    pub outcome_available_at: i64,
    pub outcome_used_as_feature: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CounterfactualCandidateGroupInput {
    pub decision_id: CompactString,
    pub behavior_policy_id: CompactString,
    pub candidates: Vec<CounterfactualCandidateOutcome>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrozenCounterfactualGroupRecord {
    pub group_id: CompactString,
    pub decision_id: CompactString,
    pub observation_cutoff: i64,
    pub pre_state_snapshot_id: CompactString,
    pub behavior_policy_id: CompactString,
    pub candidates: ExactRange,
    pub recorded_candidate_ordinal: u64,
    pub split: GraphDecisionSplit,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CounterfactualDatasetCertificate {
    pub groups_checked: u64,
    pub candidates_checked: u64,
    pub complete_role_groups: u64,
    pub recorded_actions_covered: u64,
    pub fully_observed_reward_vectors: u64,
    pub hard_constraint_receipts: u64,
    pub labels_after_observation: u64,
    pub outcomes_used_as_features: u64,
    pub outcomes_after_freeze: u64,
    pub duplicate_action_identities: u64,
    pub invalid_temporal_sentinels: u64,
}

impl CounterfactualDatasetCertificate {
    pub fn passes(&self) -> bool {
        self.groups_checked > 0
            && self.candidates_checked
                == self.groups_checked * CounterfactualCandidateRole::ALL.len() as u64
            && self.complete_role_groups == self.groups_checked
            && self.recorded_actions_covered == self.groups_checked
            && self.fully_observed_reward_vectors == self.candidates_checked
            && self.hard_constraint_receipts == self.candidates_checked
            && self.outcomes_used_as_features == 0
            && self.outcomes_after_freeze == 0
            && self.duplicate_action_identities == 0
            && self.invalid_temporal_sentinels == 0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrozenCounterfactualCandidateGroups {
    pub schema_version: CompactString,
    pub dataset_id: CompactString,
    pub source_trajectory_id: CompactString,
    pub frozen_at: i64,
    pub groups: Vec<FrozenCounterfactualGroupRecord>,
    pub candidates: Vec<CounterfactualCandidateOutcome>,
    pub certificate: CounterfactualDatasetCertificate,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CounterfactualCandidateGroupsManifest {
    pub schema_version: CompactString,
    pub dataset_id: CompactString,
    pub source_trajectory_id: CompactString,
    pub binary_version: u16,
    pub payload_file: PathBuf,
    pub payload_bytes: u64,
    pub payload_blake3: CompactString,
    pub group_count: u64,
    pub candidate_count: u64,
    pub certificate: CounterfactualDatasetCertificate,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CounterfactualCandidateGroupsPaths {
    pub manifest: PathBuf,
    pub payload: PathBuf,
}

#[derive(Debug, Error)]
pub enum CounterfactualCandidateGroupsError {
    #[error("counterfactual candidate group input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("counterfactual candidate group leaks authority: {0}")]
    Leakage(&'static str),
    #[error("counterfactual candidate group identity mismatch: {0}")]
    Identity(&'static str),
    #[error("counterfactual candidate group artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("counterfactual candidate group artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("counterfactual candidate group IO failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("counterfactual candidate group JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("counterfactual action contract failed: {0}")]
    Action(#[from] phoenix_types::GraphDecisionValidationError),
    #[error("counterfactual reward contract failed: {0}")]
    Reward(#[from] phoenix_types::GraphDecisionRewardError),
    #[error("source trajectory contract failed: {0}")]
    Source(#[from] crate::FrozenGraphDecisionTrajectoryError),
    #[error("native decision receipt contract failed: {0}")]
    NativeReceipt(#[from] phoenix_types::NativeDecisionReceiptError),
}
