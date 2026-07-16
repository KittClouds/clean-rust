use compact_str::CompactString;
use phoenix_types::{
    GraphDecisionAction, GraphDecisionAuthority, GraphDecisionEvidenceRef,
    GraphDecisionRewardVector,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub const FROZEN_GRAPH_DECISION_TRAJECTORIES_SCHEMA: &str =
    "phoenix-frozen-graph-decision-trajectories/v1";
pub const FROZEN_GRAPH_DECISION_TRAJECTORIES_BINARY_VERSION: u16 = 1;
pub const FROZEN_GRAPH_DECISION_SECTION_COUNT: usize = 10;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u8)]
pub enum GraphDecisionSplit {
    Train = 1,
    Validation = 2,
    Test = 3,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u8)]
pub enum DecisionCandidateSourceKind {
    ActiveCompatibleEpisode,
    TemporallyPlausibleEpisode,
    SameEntityEpisode,
    RelatedEntityEpisode,
    DifficultNearNeighborEpisode,
    SameRelationHardNegative,
    EvidenceConfusableAlternative,
    TemporallyPlausibleIncorrectAction,
    StructurallyValidSemanticNegative,
    MinimalEditRepairAlternative,
    ExplicitCreateEpisode,
    ExplicitAbstain,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrozenCandidateAction {
    pub action_identity: CompactString,
    pub sources: Vec<DecisionCandidateSourceKind>,
    pub action: GraphDecisionAction,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CandidateGenerationReceipt {
    pub generator_id: CompactString,
    pub generator_version: CompactString,
    pub generator_input_id: CompactString,
    pub candidate_identity: CompactString,
    pub candidate_count: u32,
    pub hard_negative_composition: Vec<CandidateSourceCount>,
    pub invalid_candidates_rejected: u32,
    pub allocation_volume_bytes: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandidateSourceCount {
    pub source: DecisionCandidateSourceKind,
    pub count: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CandidateGenerationPerformanceReceipt {
    pub candidate_identity: CompactString,
    pub generation_latency_ns: u64,
    pub allocation_volume_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandidateGenerationPerformanceCertificate {
    pub schema_version: CompactString,
    pub dataset_id: CompactString,
    pub receipt_id: CompactString,
    pub group_count: u64,
    pub generation_latency_ns: u64,
    pub allocation_volume_bytes: u64,
    pub groups: Vec<CandidateGenerationPerformanceReceipt>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DecisionCandidateGroup {
    pub candidate_group_id: CompactString,
    pub candidates: Vec<FrozenCandidateAction>,
    pub generation: CandidateGenerationReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionDeltaReference {
    pub before_delta_id: CompactString,
    pub after_delta_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionLeakageWitness {
    pub pre_state_max_fact_available_at: i64,
    pub post_decision_edges_in_pre_state: u64,
    pub future_episode_memberships_in_features: u64,
    pub validation_test_facts_in_training_topology: u64,
    pub outcome_fields_used_as_inputs: u64,
    pub candidate_generation_used_held_out_label: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionProvenance {
    pub decision_fingerprint: CompactString,
    pub source_receipt_ids: Vec<CompactString>,
    pub label_authority_id: CompactString,
    pub label_available_at: i64,
    pub leakage_witness: GraphDecisionLeakageWitness,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionTrajectoryExample {
    pub decision_id: CompactString,
    pub observation_cutoff: i64,
    pub pre_state_snapshot_id: CompactString,
    pub candidate_group: DecisionCandidateGroup,
    pub selected_action: GraphDecisionAction,
    pub evidence_references: Vec<GraphDecisionEvidenceRef>,
    pub delta: GraphDecisionDeltaReference,
    pub post_state_snapshot_id: CompactString,
    pub reward_vector: GraphDecisionRewardVector,
    pub authority: GraphDecisionAuthority,
    pub split: GraphDecisionSplit,
    pub provenance: GraphDecisionProvenance,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExactRange {
    pub offset: u64,
    pub length: u64,
}

impl ExactRange {
    pub fn end(self) -> Option<u64> {
        self.offset.checked_add(self.length)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenDecisionRecord {
    pub decision_id: CompactString,
    pub observation_cutoff: i64,
    pub state_ordinal: u64,
    pub candidate_group_ordinal: u64,
    pub candidate_actions: ExactRange,
    pub selected_label_ordinal: u64,
    pub evidence: ExactRange,
    pub reward_ordinal: u64,
    pub delta_ordinal: u64,
    pub provenance_ordinal: u64,
    pub split: GraphDecisionSplit,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenStateIdentityRecord {
    pub pre_state_snapshot_id: CompactString,
    pub post_state_snapshot_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenCandidateGroupRecord {
    pub candidate_group_id: CompactString,
    pub candidate_identity: CompactString,
    pub action_range: ExactRange,
    pub generation: CandidateGenerationReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenSelectedActionRecord {
    pub selected_action_identity: CompactString,
    pub selected_candidate_ordinal: u64,
    pub action: GraphDecisionAction,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenSplitIndexRecord {
    pub decision_ordinal: u64,
    pub observation_cutoff: i64,
    pub split: GraphDecisionSplit,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDecisionLeakageCertificate {
    pub decisions_checked: u64,
    pub evidence_checked: u64,
    pub correct_action_candidate_coverage_basis_points: u16,
    pub missing_correct_actions: u64,
    pub evidence_after_cutoff: u64,
    pub post_decision_edges_in_pre_state: u64,
    pub duplicate_fingerprints_across_splits: u64,
    pub future_episode_memberships_exposed: u64,
    pub held_out_facts_in_training_topology: u64,
    pub outcomes_used_as_inputs: u64,
    pub label_influenced_candidate_groups: u64,
}

impl GraphDecisionLeakageCertificate {
    pub fn passes(&self) -> bool {
        self.correct_action_candidate_coverage_basis_points == 10_000
            && self.missing_correct_actions == 0
            && self.evidence_after_cutoff == 0
            && self.post_decision_edges_in_pre_state == 0
            && self.duplicate_fingerprints_across_splits == 0
            && self.future_episode_memberships_exposed == 0
            && self.held_out_facts_in_training_topology == 0
            && self.outcomes_used_as_inputs == 0
            && self.label_influenced_candidate_groups == 0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandidateDatasetCertificate {
    pub candidate_groups: u64,
    pub candidates: u64,
    pub candidate_count_min: u32,
    pub candidate_count_p50: u32,
    pub candidate_count_p95: u32,
    pub candidate_count_max: u32,
    pub hard_negative_composition: Vec<CandidateSourceCount>,
    pub invalid_candidates_rejected: u64,
    pub allocation_volume_bytes: u64,
    pub candidate_identities: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenDecisionProvenanceSection {
    pub entries: Vec<GraphDecisionProvenance>,
    pub leakage_certificate: GraphDecisionLeakageCertificate,
    pub candidate_certificate: CandidateDatasetCertificate,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenDecisionTrajectoryTables {
    pub decisions: Vec<FrozenDecisionRecord>,
    pub states: Vec<FrozenStateIdentityRecord>,
    pub candidate_groups: Vec<FrozenCandidateGroupRecord>,
    pub candidate_actions: Vec<FrozenCandidateAction>,
    pub selected_actions: Vec<FrozenSelectedActionRecord>,
    pub evidence: Vec<GraphDecisionEvidenceRef>,
    pub rewards: Vec<GraphDecisionRewardVector>,
    pub deltas: Vec<GraphDecisionDeltaReference>,
    pub split_index: Vec<FrozenSplitIndexRecord>,
    pub provenance: FrozenDecisionProvenanceSection,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u8)]
pub enum FrozenDecisionSectionKind {
    DecisionRecords = 1,
    PreStateIdentities = 2,
    CandidateGroupOffsets = 3,
    CandidateActionPayloads = 4,
    SelectedActionLabels = 5,
    EvidenceReferences = 6,
    RewardVectors = 7,
    GraphDeltaReferences = 8,
    TemporalSplitIndex = 9,
    ProvenanceLeakageCertificate = 10,
}

impl FrozenDecisionSectionKind {
    pub const ALL: [Self; FROZEN_GRAPH_DECISION_SECTION_COUNT] = [
        Self::DecisionRecords,
        Self::PreStateIdentities,
        Self::CandidateGroupOffsets,
        Self::CandidateActionPayloads,
        Self::SelectedActionLabels,
        Self::EvidenceReferences,
        Self::RewardVectors,
        Self::GraphDeltaReferences,
        Self::TemporalSplitIndex,
        Self::ProvenanceLeakageCertificate,
    ];
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenDecisionSectionManifest {
    pub kind: FrozenDecisionSectionKind,
    pub offset: u64,
    pub length: u64,
    pub blake3: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenGraphDecisionTrajectoryManifest {
    pub schema_version: CompactString,
    pub dataset_id: CompactString,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub decisions: u64,
    pub candidates: u64,
    pub train_decisions: u64,
    pub validation_decisions: u64,
    pub test_decisions: u64,
    pub sections: Vec<FrozenDecisionSectionManifest>,
    pub leakage_certificate: GraphDecisionLeakageCertificate,
    pub candidate_certificate: CandidateDatasetCertificate,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenGraphDecisionTrajectoryPaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
    pub performance_receipt: PathBuf,
    pub dataset_id: CompactString,
}

#[derive(Debug, Error)]
pub enum FrozenGraphDecisionTrajectoryError {
    #[error("frozen decision trajectory input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("frozen decision trajectory leakage tribunal failed: {0}")]
    Leakage(&'static str),
    #[error("frozen decision trajectory artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("frozen decision trajectory artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("frozen decision trajectory action is invalid: {0}")]
    InvalidAction(#[from] phoenix_types::GraphDecisionValidationError),
    #[error("frozen decision trajectory reward is invalid: {0}")]
    InvalidReward(#[from] phoenix_types::GraphDecisionRewardError),
    #[error("frozen decision trajectory I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("frozen decision trajectory JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
