use compact_str::CompactString;
use phoenix_types::GraphDecisionActionKind;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

use crate::GraphDecisionSplit;

pub const NATIVE_DECISION_EVALUATION_SCHEMA: &str = "phoenix-native-decision-evaluation/v1";
pub const DECISION_BASELINE_LADDER_SCHEMA: &str = "phoenix-native-decision-baseline-ladder/v1";
pub const NATIVE_DECISION_TIE_POLICY: &str =
    "filtered average rank; fractional hits; action-id recall/ndcg tie break";
pub const NATIVE_DECISION_SLICE_POLICY: &str =
    "temporal+relation_frequency+entity_degree+evidence_count+action_family/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDecisionTaskFamily {
    Ranking,
    Classification,
    Policy,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PolicyRewardScalarization {
    pub policy_id: CompactString,
    pub weights_micros: [i32; 8],
    pub pending_signal_policy: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionEvaluationProtocol {
    pub schema_version: CompactString,
    pub protocol_id: CompactString,
    pub dataset_id: CompactString,
    pub task_family: NativeDecisionTaskFamily,
    pub partition: GraphDecisionSplit,
    pub calibration_bins: u8,
    pub recall_at_k: u32,
    pub ndcg_at_k: u32,
    pub risk_coverage_basis_points: Vec<u16>,
    pub tie_policy: CompactString,
    pub slice_policy_id: CompactString,
    pub reward_scalarization: Option<PolicyRewardScalarization>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DecisionPolicyOutcome {
    pub reward_micros: [i32; 8],
    pub hard_constraint_violations: u32,
    pub supported: bool,
    pub edit_cost_micros: u32,
    pub future_stability_micros: i32,
    pub authority_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionPrediction {
    pub decision_id: CompactString,
    pub prediction_id: CompactString,
    pub producer_model_id: CompactString,
    pub scores: Vec<f32>,
    pub probabilities: Vec<f32>,
    pub eligible: Vec<bool>,
    pub relevant: Vec<bool>,
    pub predicted_candidate_ordinal: Option<u32>,
    pub confidence: f32,
    pub reference_scores: Option<Vec<f32>>,
    pub policy_outcomes: Option<Vec<DecisionPolicyOutcome>>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DecisionEvaluationSliceKeys {
    pub temporal: CompactString,
    pub relation_frequency: CompactString,
    pub entity_degree: CompactString,
    pub evidence_count: CompactString,
    pub action_family: GraphDecisionActionKind,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionEvaluationInput {
    pub decision_id: CompactString,
    pub prediction: NativeDecisionPrediction,
    pub slices: DecisionEvaluationSliceKeys,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionSliceDimension {
    Temporal,
    RelationFrequency,
    EntityDegree,
    EvidenceCount,
    ActionFamily,
}

impl DecisionSliceDimension {
    pub const ALL: [Self; 5] = [
        Self::Temporal,
        Self::RelationFrequency,
        Self::EntityDegree,
        Self::EvidenceCount,
        Self::ActionFamily,
    ];
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DecisionRankingMetrics {
    pub queries: u64,
    pub candidates: u64,
    pub filtered_mean_reciprocal_rank: f64,
    pub hits_at_1: f64,
    pub hits_at_3: f64,
    pub hits_at_10: f64,
    pub recall_at_k: f64,
    pub ndcg_at_k: f64,
    pub candidate_coverage: f64,
    pub paired_mean_rank_delta: Option<f64>,
    pub paired_wins: u64,
    pub paired_losses: u64,
    pub paired_ties: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RiskCoveragePoint {
    pub requested_coverage_basis_points: u16,
    pub retained: u64,
    pub risk: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DecisionClassificationMetrics {
    pub decisions: u64,
    pub candidate_samples: u64,
    pub average_precision: Option<f64>,
    pub macro_f1: f64,
    pub brier_score: f64,
    pub log_loss: f64,
    pub expected_calibration_error: f64,
    pub abstained: u64,
    pub risk_coverage: Vec<RiskCoveragePoint>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DecisionPolicyMetrics {
    pub decisions: u64,
    pub mean_relative_reward_micros: f64,
    pub mean_regret_against_recorded_micros: f64,
    pub hard_constraint_violations: u64,
    pub unsupported_action_rate: f64,
    pub mean_unnecessary_edit_cost_micros: f64,
    pub mean_future_graph_stability_micros: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DecisionEvaluationSliceResult {
    pub dimension: DecisionSliceDimension,
    pub key: CompactString,
    pub decisions: u64,
    pub ranking: Option<DecisionRankingMetrics>,
    pub classification: Option<DecisionClassificationMetrics>,
    pub policy: Option<DecisionPolicyMetrics>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeDecisionEvaluationReport {
    pub schema_version: CompactString,
    pub report_id: CompactString,
    pub protocol_id: CompactString,
    pub dataset_id: CompactString,
    pub prediction_set_id: CompactString,
    pub task_family: NativeDecisionTaskFamily,
    pub partition: GraphDecisionSplit,
    pub decisions: u64,
    pub ranking: Option<DecisionRankingMetrics>,
    pub classification: Option<DecisionClassificationMetrics>,
    pub policy: Option<DecisionPolicyMetrics>,
    pub slices: Vec<DecisionEvaluationSliceResult>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionFeatureFamily {
    LabelPrevalence,
    Metadata,
    Topology,
    TemporalHistory,
    Evidence,
    RevisionStructure,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionBaselineRung {
    FrequencyRecency,
    TypedDegreeStructuralOverlap,
    Ftrl,
    Mlp16,
    FrozenRgcnExistingTopology,
    FrozenRgcnWithMetadata,
    FrozenRgcnWithTemporalHistory,
    FrozenRgcnWithEvidence,
    FrozenRgcnWithRevisionStructure,
}

impl DecisionBaselineRung {
    pub const REQUIRED: [Self; 9] = [
        Self::FrequencyRecency,
        Self::TypedDegreeStructuralOverlap,
        Self::Ftrl,
        Self::Mlp16,
        Self::FrozenRgcnExistingTopology,
        Self::FrozenRgcnWithMetadata,
        Self::FrozenRgcnWithTemporalHistory,
        Self::FrozenRgcnWithEvidence,
        Self::FrozenRgcnWithRevisionStructure,
    ];

    pub const fn isolated_feature(self) -> DecisionFeatureFamily {
        match self {
            Self::FrequencyRecency => DecisionFeatureFamily::LabelPrevalence,
            Self::TypedDegreeStructuralOverlap => DecisionFeatureFamily::Metadata,
            Self::Ftrl | Self::Mlp16 => DecisionFeatureFamily::Metadata,
            Self::FrozenRgcnExistingTopology => DecisionFeatureFamily::Topology,
            Self::FrozenRgcnWithMetadata => DecisionFeatureFamily::Metadata,
            Self::FrozenRgcnWithTemporalHistory => DecisionFeatureFamily::TemporalHistory,
            Self::FrozenRgcnWithEvidence => DecisionFeatureFamily::Evidence,
            Self::FrozenRgcnWithRevisionStructure => DecisionFeatureFamily::RevisionStructure,
        }
    }

    pub fn enabled_features(self) -> Vec<DecisionFeatureFamily> {
        use DecisionFeatureFamily as Feature;
        match self {
            Self::FrequencyRecency => vec![Feature::LabelPrevalence, Feature::TemporalHistory],
            Self::TypedDegreeStructuralOverlap => vec![Feature::Metadata, Feature::Topology],
            Self::Ftrl | Self::Mlp16 => vec![
                Feature::LabelPrevalence,
                Feature::Metadata,
                Feature::Topology,
                Feature::TemporalHistory,
                Feature::Evidence,
                Feature::RevisionStructure,
            ],
            Self::FrozenRgcnExistingTopology => vec![Feature::Topology],
            Self::FrozenRgcnWithMetadata => vec![Feature::Topology, Feature::Metadata],
            Self::FrozenRgcnWithTemporalHistory => {
                vec![Feature::Topology, Feature::TemporalHistory]
            }
            Self::FrozenRgcnWithEvidence => vec![Feature::Topology, Feature::Evidence],
            Self::FrozenRgcnWithRevisionStructure => {
                vec![Feature::Topology, Feature::RevisionStructure]
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DecisionBaselineSubmission {
    pub rung: DecisionBaselineRung,
    pub model_id: CompactString,
    pub feature_manifest_id: CompactString,
    pub enabled_feature_families: Vec<DecisionFeatureFamily>,
    pub inputs: Vec<NativeDecisionEvaluationInput>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DecisionBaselineResult {
    pub rung: DecisionBaselineRung,
    pub isolated_feature: DecisionFeatureFamily,
    pub model_id: CompactString,
    pub feature_manifest_id: CompactString,
    pub enabled_feature_families: Vec<DecisionFeatureFamily>,
    pub report: NativeDecisionEvaluationReport,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DecisionBaselineLadderReport {
    pub schema_version: CompactString,
    pub ladder_id: CompactString,
    pub protocol_id: CompactString,
    pub dataset_id: CompactString,
    pub single_task_only: bool,
    pub test_accessed: bool,
    pub rungs: Vec<DecisionBaselineResult>,
}

#[derive(Debug, Error)]
pub enum NativeDecisionEvaluationError {
    #[error("native decision evaluation input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("native decision evaluation identity mismatch: {0}")]
    Identity(&'static str),
    #[error("native decision evaluation metric input is invalid")]
    Metric,
    #[error("native decision evaluation baseline order is invalid")]
    BaselineOrder,
    #[error("native decision evaluation test access is locked")]
    TestLocked,
    #[error("native decision evaluation artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("native decision evaluation artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("native decision evaluation I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("native decision evaluation JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
