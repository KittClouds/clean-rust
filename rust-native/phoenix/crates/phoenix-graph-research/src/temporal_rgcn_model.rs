use crate::LinkPredictionScoreCertificate;
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const TEMPORAL_RGCN_SCHEMA: &str = "phoenix-temporal-rgcn-link-predictor/v1";
pub const TEMPORAL_RGCN_BINARY_VERSION: u16 = 1;
pub const TEMPORAL_RGCN_HIDDEN: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRgcnConfig {
    pub epochs: u32,
    pub learning_rate: f32,
    pub l2: f32,
    pub negatives_per_positive: u16,
    pub residual_scale: f32,
    pub seed: u64,
}

impl Default for TemporalRgcnConfig {
    fn default() -> Self {
        Self {
            epochs: 4,
            learning_rate: 0.02,
            l2: 0.000_01,
            negatives_per_positive: 1,
            residual_scale: 0.01,
            seed: 0x7068_6f65_6e69_7801,
        }
    }
}

impl TemporalRgcnConfig {
    pub fn validate(self) -> Result<(), TemporalRgcnError> {
        if self.epochs == 0
            || !self.learning_rate.is_finite()
            || self.learning_rate <= 0.0
            || !self.l2.is_finite()
            || self.l2 < 0.0
            || self.negatives_per_positive == 0
            || !self.residual_scale.is_finite()
            || self.residual_scale <= 0.0
        {
            return Err(TemporalRgcnError::InvalidContract("configuration"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRgcnRuntimeIdentity {
    pub framework: CompactString,
    pub framework_version: CompactString,
    pub backend: CompactString,
    pub target: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRgcnTrainingReceipt {
    pub trainer_id: CompactString,
    pub train_facts: u64,
    pub directed_messages: u64,
    pub training_examples: u64,
    pub optimizer_steps: u64,
    pub optimizer_state_blake3: CompactString,
    pub train_topology_blake3: CompactString,
    pub test_locked_during_training: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalRgcnWeights {
    pub node_embeddings: Vec<f32>,
    pub self_weight: Vec<f32>,
    pub relation_weights: Vec<f32>,
    pub decoder_relations: Vec<f32>,
    pub decoder_bias: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalRgcnSnapshot {
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub config: TemporalRgcnConfig,
    pub runtime: TemporalRgcnRuntimeIdentity,
    pub training: TemporalRgcnTrainingReceipt,
    pub baseline: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub weights: TemporalRgcnWeights,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRgcnManifest {
    pub schema_version: CompactString,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub directed_relation_count: u32,
    pub hidden_features: u16,
    pub config: TemporalRgcnConfig,
    pub runtime: TemporalRgcnRuntimeIdentity,
    pub training: TemporalRgcnTrainingReceipt,
    pub baseline: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub weights_file: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemporalRgcnPaths {
    pub manifest: PathBuf,
    pub weights: PathBuf,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRgcnStagingProfile {
    pub source_facts: u64,
    pub train_facts: u64,
    pub directed_messages: u64,
    pub training_examples: u64,
    pub staged_bytes: u64,
    pub staging_micros: u64,
    pub train_topology_blake3: CompactString,
    pub train_only: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum TemporalRgcnError {
    #[error("temporal R-GCN contract is invalid: {0}")]
    InvalidContract(&'static str),
    #[error("temporal R-GCN artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("temporal R-GCN artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("external source failed validation: {0}")]
    Source(#[from] crate::ExternalDatasetError),
    #[error("canonical link task failed validation: {0}")]
    Task(#[from] crate::LinkPredictionError),
    #[error("temporal R-GCN I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("temporal R-GCN JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
