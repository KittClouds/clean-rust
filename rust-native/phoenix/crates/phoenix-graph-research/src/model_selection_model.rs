use crate::{
    BinaryMetrics, FrozenModelError, FrozenModelPaths, FrozenModelScoreCertificate,
    FrozenModelSourceIdentity, ResearchEvaluationError, SeedCertificate,
};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const FROZEN_MODEL_SELECTION_SCHEMA: &str = "phoenix-frozen-model-selection/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelSelectionPolicy {
    pub task_id: CompactString,
    pub evaluator_schema: CompactString,
    pub calibration_bins: u8,
}

#[derive(Clone, Copy)]
pub struct FrozenBinaryEvaluationSet<'a> {
    pub features: &'a [[f32; 16]],
    pub labels: &'a [bool],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelCandidateReceipt {
    pub configuration_id: CompactString,
    pub model_id: CompactString,
    pub weights_blake3: CompactString,
    pub selected_repeat: u16,
    pub selected_seed: u64,
    pub validation_score_certificate: FrozenModelScoreCertificate,
    pub validation_metrics: BinaryMetrics,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelConfigurationSummary {
    pub configuration_id: CompactString,
    pub model_ids: Vec<CompactString>,
    pub repeats: u16,
    pub mean_validation_average_precision: f64,
    pub mean_validation_brier_score: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelSelectionLedger {
    pub schema_version: CompactString,
    pub ledger_id: CompactString,
    pub source: FrozenModelSourceIdentity,
    pub seed_certificate: SeedCertificate,
    pub policy: FrozenModelSelectionPolicy,
    pub selection_rule: CompactString,
    pub candidates: Vec<FrozenModelCandidateReceipt>,
    pub configuration_summaries: Vec<FrozenModelConfigurationSummary>,
    pub selected_configuration_id: CompactString,
    pub selected_validation_model_id: CompactString,
    pub finalized_model_id: CompactString,
    pub selected_weights_blake3: CompactString,
    pub locked_test_claim_id: CompactString,
    pub locked_test_executions: u8,
    pub test_score_certificate: FrozenModelScoreCertificate,
    pub test_metrics: BinaryMetrics,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenModelSelectionPaths {
    pub test_claim: PathBuf,
    pub ledger: PathBuf,
    pub finalized_model: FrozenModelPaths,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FrozenModelSelectionOutcome {
    pub ledger: FrozenModelSelectionLedger,
    pub paths: FrozenModelSelectionPaths,
}

pub struct FrozenModelSelection {
    pub(crate) source: FrozenModelSourceIdentity,
    pub(crate) seed_certificate: SeedCertificate,
    pub(crate) policy: FrozenModelSelectionPolicy,
    pub(crate) candidates: Vec<FrozenModelCandidateReceipt>,
    pub(crate) summaries: Vec<FrozenModelConfigurationSummary>,
    pub(crate) selected_configuration_id: CompactString,
    pub(crate) selected_validation_model_id: CompactString,
    pub(crate) selected_manifest: PathBuf,
}

impl FrozenModelSelection {
    pub fn selected_configuration_id(&self) -> &str {
        self.selected_configuration_id.as_str()
    }

    pub fn selected_validation_model_id(&self) -> &str {
        self.selected_validation_model_id.as_str()
    }

    pub fn configuration_summaries(&self) -> &[FrozenModelConfigurationSummary] {
        &self.summaries
    }
}

#[derive(Debug, thiserror::Error)]
pub enum FrozenModelSelectionError {
    #[error("frozen model selection contract is invalid: {0}")]
    InvalidContract(&'static str),
    #[error("frozen model selection input failed validation: {0}")]
    Model(#[from] FrozenModelError),
    #[error("frozen model selection evaluation failed: {0}")]
    Evaluation(#[from] ResearchEvaluationError),
    #[error("frozen model selection artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("locked test was already claimed: {0}")]
    LockedTestAlreadyClaimed(PathBuf),
    #[error("frozen model selection I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("frozen model selection encoding failed: {0}")]
    Json(#[from] serde_json::Error),
}
