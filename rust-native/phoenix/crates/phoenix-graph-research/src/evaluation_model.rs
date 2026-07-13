use crate::{ResearchSplit, TemporalSplitPolicy};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub const RESEARCH_EVALUATION_SCHEMA: &str = "phoenix-research-evaluation-protocol/v1";
pub const BASELINE_LADDER_SCHEMA: &str = "phoenix-baseline-ladder/v1";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EvaluationPolicy {
    pub feature_schema_id: CompactString,
    pub seed_root: u64,
    pub repeats: u16,
    pub calibration_bins: u8,
    pub ftrl: FtrlConfig,
    pub mlp: MlpConfig,
}

impl EvaluationPolicy {
    pub fn validate(&self) -> Result<(), ResearchEvaluationError> {
        if self.feature_schema_id.is_empty()
            || !(1..=64).contains(&self.repeats)
            || !(2..=50).contains(&self.calibration_bins)
            || self.ftrl.epochs == 0
            || self.ftrl.alpha <= 0.0
            || self.ftrl.beta < 0.0
            || self.ftrl.l1 < 0.0
            || self.ftrl.l2 < 0.0
            || self.mlp.epochs == 0
            || self.mlp.learning_rate <= 0.0
            || self.mlp.l2 < 0.0
        {
            return Err(ResearchEvaluationError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FtrlConfig {
    pub epochs: u16,
    pub alpha: f32,
    pub beta: f32,
    pub l1: f32,
    pub l2: f32,
}

impl Default for FtrlConfig {
    fn default() -> Self {
        Self {
            epochs: 12,
            alpha: 0.08,
            beta: 1.0,
            l1: 0.002,
            l2: 0.04,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MlpConfig {
    pub epochs: u16,
    pub learning_rate: f32,
    pub l2: f32,
}

impl Default for MlpConfig {
    fn default() -> Self {
        Self {
            epochs: 24,
            learning_rate: 0.025,
            l2: 0.0005,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskDefinition {
    pub task_id: CompactString,
    pub examples: CompactString,
    pub target: CompactString,
    pub split_authority: CompactString,
    pub metrics: Vec<CompactString>,
    pub executable_in_v1: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SeedCertificate {
    pub namespace: CompactString,
    pub digest: CompactString,
    pub seeds: Vec<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LeakageAudit {
    pub nodes_checked: u64,
    pub edges_checked: u64,
    pub incidences_checked: u64,
    pub proposals_checked: u64,
    pub observed_proposals: u64,
    pub censored_proposals: u64,
    pub negatives_checked: u64,
    pub feature_columns_checked: u64,
    pub train_examples: u64,
    pub validation_examples: u64,
    pub test_examples: u64,
    pub no_future_rows: bool,
    pub no_label_before_availability: bool,
    pub no_censored_supervision: bool,
    pub no_feature_schema_mixing: bool,
    pub no_negative_collisions: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchEvaluationProtocol {
    pub schema_version: CompactString,
    pub protocol_id: CompactString,
    pub tensor_id: CompactString,
    pub source_dataset_id: CompactString,
    pub split_policy: TemporalSplitPolicy,
    pub policy: EvaluationPolicy,
    pub seed_certificate: SeedCertificate,
    pub tasks: Vec<TaskDefinition>,
    pub leakage_audit: LeakageAudit,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BaselineFamily {
    PriorHeuristic,
    FtrlLogistic,
    Mlp16,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BinaryMetrics {
    pub samples: u64,
    pub positives: u64,
    pub log_loss: f64,
    pub brier_score: f64,
    pub expected_calibration_error: f64,
    pub average_precision: Option<f64>,
    pub roc_auc: Option<f64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BaselineSeedRun {
    pub family: BaselineFamily,
    pub seed: u64,
    pub train: BinaryMetrics,
    pub validation: BinaryMetrics,
    pub held_out_test: Option<BinaryMetrics>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FamilyValidationSummary {
    pub family: BaselineFamily,
    pub mean_average_precision: f64,
    pub mean_brier_score: f64,
    pub repeats: u16,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BaselineLadderReport {
    pub schema_version: CompactString,
    pub report_id: CompactString,
    pub protocol_id: CompactString,
    pub selected_family: BaselineFamily,
    pub selection_rule: CompactString,
    pub validation_summaries: Vec<FamilyValidationSummary>,
    pub runs: Vec<BaselineSeedRun>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchEvaluationPaths {
    pub protocol: PathBuf,
    pub baselines: PathBuf,
}

#[derive(Debug, Error)]
pub enum ResearchEvaluationError {
    #[error("evaluation policy is invalid")]
    InvalidPolicy,
    #[error("evaluation source and tensor identities differ")]
    SourceIdentityMismatch,
    #[error("evaluation tensor arrays are inconsistent: {0}")]
    TensorShape(&'static str),
    #[error("evaluation leakage audit failed: {0}")]
    Leakage(&'static str),
    #[error("feature schema is absent or uncertified: {0}")]
    FeatureSchema(String),
    #[error("split {0:?} lacks both observed classes for the selected schema")]
    InsufficientSplit(ResearchSplit),
    #[error("metric input is invalid")]
    InvalidMetricInput,
    #[error("baseline report does not reference its protocol")]
    ReportProtocolMismatch,
    #[error("evaluation artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("evaluation artifact I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("train-topology artifact is corrupt: {0}")]
    CorruptTopologyArtifact(&'static str),
    #[error("evaluation serialization failed: {0}")]
    Json(#[from] serde_json::Error),
}
