use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::GraphDecisionSplit;

pub const NATIVE_RGCN_FEATURE_SCHEMA: &str = "phoenix-rgcn-native-features/v1";
pub const NATIVE_RGCN_FEATURE_DIM: usize = 16;
pub const NATIVE_RGCN_FEATURE_SCALE: i16 = 1_000;
pub const NATIVE_RGCN_MULTITASK_SCHEMA: &str = "phoenix-rgcn-multitask-workhorse/v3";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRgcnFeatureFamily {
    TypedAdjacency,
    QualifierIncidence,
    TemporalHistory,
    Evidence,
    RevisionStructure,
    EpisodeMembership,
    ProposalHistory,
    DiscrepancyState,
    AuthorityConfidence,
}

impl NativeRgcnFeatureFamily {
    pub const ALL: [Self; 9] = [
        Self::TypedAdjacency,
        Self::QualifierIncidence,
        Self::TemporalHistory,
        Self::Evidence,
        Self::RevisionStructure,
        Self::EpisodeMembership,
        Self::ProposalHistory,
        Self::DiscrepancyState,
        Self::AuthorityConfidence,
    ];

    pub const fn columns(self) -> (usize, usize) {
        match self {
            Self::TypedAdjacency => (0, 3),
            Self::QualifierIncidence => (3, 5),
            Self::TemporalHistory => (5, 7),
            Self::Evidence => (7, 9),
            Self::RevisionStructure => (9, 10),
            Self::EpisodeMembership => (10, 11),
            Self::ProposalHistory => (11, 13),
            Self::DiscrepancyState => (13, 14),
            Self::AuthorityConfidence => (14, 16),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDiscrepancyState {
    None,
    Open,
    Contradiction,
    TemporalRevision,
    ContextualDifference,
    SourceDisagreement,
    DuplicateEvidence,
    Resolved,
}

impl NativeDiscrepancyState {
    pub const fn ordinal(self) -> u32 {
        match self {
            Self::None => 0,
            Self::Open => 1,
            Self::Contradiction => 2,
            Self::TemporalRevision => 3,
            Self::ContextualDifference => 4,
            Self::SourceDisagreement => 5,
            Self::DuplicateEvidence => 6,
            Self::Resolved => 7,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeRgcnRawFeatureAuthority {
    pub typed_in_degree: u32,
    pub typed_out_degree: u32,
    pub typed_neighbor_overlap_basis_points: u16,
    pub qualifier_incidence_count: u32,
    pub qualifier_role_diversity: u32,
    pub latest_visible_fact_at: Option<i64>,
    pub prior_visible_fact_at: Option<i64>,
    pub evidence_count: u32,
    pub evidence_source_diversity: u32,
    pub revision_depth: u32,
    pub visible_episode_memberships: u32,
    pub prior_accepted_proposals: u32,
    pub prior_rejected_proposals: u32,
    pub discrepancy_state: NativeDiscrepancyState,
    pub authority_class: u8,
    pub confidence_class: u8,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeRgcnFeatureAuthorityRow {
    pub decision_id: CompactString,
    pub candidate_action_identity: CompactString,
    pub split: GraphDecisionSplit,
    pub observation_cutoff: i64,
    pub pre_state_snapshot_id: CompactString,
    pub topology_identity: CompactString,
    pub topology_fit_split: GraphDecisionSplit,
    pub topology_fit_through: i64,
    pub authority_id: CompactString,
    pub source_receipt_ids: Vec<CompactString>,
    pub available_through: i64,
    pub source_node: u32,
    pub target_node: u32,
    pub relation_type: u32,
    pub raw: NativeRgcnRawFeatureAuthority,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRgcnFeatureAblation {
    Real,
    Masked,
    Shuffled,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnFeatureDerivationPolicy {
    pub feature_family: NativeRgcnFeatureFamily,
    pub ablation: NativeRgcnFeatureAblation,
    pub shuffle_seed: Option<u64>,
    pub fixed_scale: i16,
    pub temporal_cap_ms: u64,
}

impl NativeRgcnFeatureDerivationPolicy {
    pub fn real(feature_family: NativeRgcnFeatureFamily) -> Self {
        Self {
            feature_family,
            ablation: NativeRgcnFeatureAblation::Real,
            shuffle_seed: None,
            fixed_scale: NATIVE_RGCN_FEATURE_SCALE,
            temporal_cap_ms: 31_536_000_000,
        }
    }

    pub fn masked(feature_family: NativeRgcnFeatureFamily) -> Self {
        Self {
            ablation: NativeRgcnFeatureAblation::Masked,
            ..Self::real(feature_family)
        }
    }

    pub fn shuffled(feature_family: NativeRgcnFeatureFamily, seed: u64) -> Self {
        Self {
            ablation: NativeRgcnFeatureAblation::Shuffled,
            shuffle_seed: Some(seed),
            ..Self::real(feature_family)
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnFeatureCertificate {
    pub column: u16,
    pub name: CompactString,
    pub family: NativeRgcnFeatureFamily,
    pub dtype: CompactString,
    pub transform: CompactString,
    pub fixed_scale: i16,
    pub available_at_rule: CompactString,
    pub label_free: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnDerivedFeatureRow {
    pub decision_ordinal: u64,
    pub candidate_ordinal: u64,
    pub decision_id: CompactString,
    pub candidate_action_identity: CompactString,
    pub split: GraphDecisionSplit,
    pub source_node: u32,
    pub target_node: u32,
    pub relation_type: u32,
    pub features: [i16; NATIVE_RGCN_FEATURE_DIM],
}

impl NativeRgcnDerivedFeatureRow {
    pub fn features_f32(&self) -> [f32; NATIVE_RGCN_FEATURE_DIM] {
        self.features
            .map(|value| f32::from(value) / f32::from(NATIVE_RGCN_FEATURE_SCALE))
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnFeatureLeakageAudit {
    pub rows_checked: u64,
    pub candidate_coverage_basis_points: u16,
    pub future_authority_rows: u64,
    pub pre_state_identity_mismatches: u64,
    pub split_mismatches: u64,
    pub duplicate_candidate_rows: u64,
    pub cross_split_shuffle_moves: u64,
    pub future_leak_sentinel_rejected: bool,
    pub fit_free_transforms: bool,
    pub label_free: bool,
}

impl NativeRgcnFeatureLeakageAudit {
    pub fn passes(&self) -> bool {
        self.candidate_coverage_basis_points == 10_000
            && self.future_authority_rows == 0
            && self.pre_state_identity_mismatches == 0
            && self.split_mismatches == 0
            && self.duplicate_candidate_rows == 0
            && self.cross_split_shuffle_moves == 0
            && self.future_leak_sentinel_rejected
            && self.fit_free_transforms
            && self.label_free
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnFeatureSnapshot {
    pub schema_version: CompactString,
    pub derivation_id: CompactString,
    pub source_trajectory_dataset_id: CompactString,
    pub topology_identities: Vec<CompactString>,
    pub policy: NativeRgcnFeatureDerivationPolicy,
    pub feature_contract: Vec<NativeRgcnFeatureCertificate>,
    pub audit: NativeRgcnFeatureLeakageAudit,
    pub rows: Vec<NativeRgcnDerivedFeatureRow>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnFeatureAblationSuite {
    pub suite_id: CompactString,
    pub feature_family: NativeRgcnFeatureFamily,
    pub real: NativeRgcnFeatureSnapshot,
    pub masked: NativeRgcnFeatureSnapshot,
    pub shuffled: NativeRgcnFeatureSnapshot,
    pub future_leak_sentinel_rejected: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnMultitaskLaunchGate {
    pub gate_id: CompactString,
    pub baseline_ladder_id: Option<CompactString>,
    pub authoritative_task_count: u32,
    pub single_task_baselines_understood: bool,
    pub important_task_regression_limit_basis_points: u16,
    pub authorized: bool,
    pub reason: CompactString,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRgcnTaskHeadKind {
    EpisodeAssignment,
    DeltaDisposition,
    DiscrepancyClassifier,
    EvidenceRanker,
    RelationProposal,
    RepairAction,
}

impl NativeRgcnTaskHeadKind {
    pub const ALL: [Self; 6] = [
        Self::EpisodeAssignment,
        Self::DeltaDisposition,
        Self::DiscrepancyClassifier,
        Self::EvidenceRanker,
        Self::RelationProposal,
        Self::RepairAction,
    ];
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRgcnComparisonMode {
    IndependentSingleTask,
    SharedMultiTask,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRgcnLossReduction {
    PerTaskMeanThenWeightedSum,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnTaskSamplingStep {
    pub task: NativeRgcnTaskHeadKind,
    pub batches_per_cycle: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnTaskHeadArchitecture {
    pub task: NativeRgcnTaskHeadKind,
    pub input_features: u16,
    pub hidden_features: u16,
    pub output_features: u16,
    pub activation: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnMultitaskIdentity {
    pub schema_version: CompactString,
    pub model_identity: CompactString,
    pub launch_gate_id: CompactString,
    pub comparison_mode: NativeRgcnComparisonMode,
    pub task_set: Vec<NativeRgcnTaskHeadKind>,
    pub task_sampling_schedule: Vec<NativeRgcnTaskSamplingStep>,
    pub loss_reduction: NativeRgcnLossReduction,
    pub loss_weights_micros: Vec<u32>,
    pub head_architectures: Vec<NativeRgcnTaskHeadArchitecture>,
    pub feature_schema_id: CompactString,
    pub topology_identity: CompactString,
    pub seed: u64,
    pub optimizer_identity: CompactString,
    pub clipping_partition_identity: CompactString,
    pub checkpoint_selection_rule: CompactString,
    pub encoder_width: u16,
    pub encoder_layers: u8,
    pub propagation_rule: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnTaskPromotionEvidence {
    pub task: NativeRgcnTaskHeadKind,
    pub strongest_baseline_id: CompactString,
    pub certified_seed_count: u16,
    pub beats_baseline: bool,
    pub weights_reproduced: bool,
    pub certificates_reproduced: bool,
    pub cold_restart_passed: bool,
    pub future_leakage_rejected: bool,
    pub calibration_maintained: bool,
    pub paired_query_improvement: bool,
    pub epoch_allocation_bytes: u64,
    pub allocation_deviation_explanation: Option<CompactString>,
    pub important_task_regression_basis_points: u16,
}

impl NativeRgcnTaskPromotionEvidence {
    pub fn passes(&self, regression_limit_basis_points: u16) -> bool {
        self.strongest_baseline_id.starts_with("b3-")
            && self.certified_seed_count > 1
            && self.beats_baseline
            && self.weights_reproduced
            && self.certificates_reproduced
            && self.cold_restart_passed
            && self.future_leakage_rejected
            && self.calibration_maintained
            && self.paired_query_improvement
            && (self.epoch_allocation_bytes == 0
                || self
                    .allocation_deviation_explanation
                    .as_ref()
                    .is_some_and(|value| !value.trim().is_empty()))
            && self.important_task_regression_basis_points <= regression_limit_basis_points
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnMultitaskPromotionCertificate {
    pub certificate_id: CompactString,
    pub model_identity: CompactString,
    pub important_task_regression_limit_basis_points: u16,
    pub head_evidence: Vec<NativeRgcnTaskPromotionEvidence>,
    pub promoted: bool,
}

#[derive(Debug, Error)]
pub enum NativeRgcnFeatureError {
    #[error("native R-GCN feature input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("native R-GCN feature authority leaks future state: {0}")]
    FutureLeak(&'static str),
    #[error("native R-GCN feature identity mismatch: {0}")]
    Identity(&'static str),
    #[error("native R-GCN multi-task workhorse is locked: {0}")]
    MultiTaskLocked(&'static str),
    #[error("native R-GCN feature JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
