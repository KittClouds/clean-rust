use crate::{LinkPredictionScoreCertificate, TemporalRgcnConfig, TemporalRgcnRuntimeIdentity};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const TEMPORAL_COMPGCN_SCHEMA: &str = "phoenix-temporal-compgcn-link-predictor/v1";
pub const TEMPORAL_COMPGCN_BINARY_VERSION: u16 = 1;
pub const TEMPORAL_COMPGCN_HIDDEN: usize = 16;
pub const TEMPORAL_COMPGCN_DIRECTIONS: usize = 3;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum TemporalComposition {
    Multiply,
    Subtract,
    CircularCorrelation,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum TemporalRelationUpdate {
    JointLinear,
    Frozen,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalCompgcnConfig {
    pub base: TemporalRgcnConfig,
    pub composition: TemporalComposition,
    pub relation_update: TemporalRelationUpdate,
}

impl Default for TemporalCompgcnConfig {
    fn default() -> Self {
        Self {
            base: TemporalRgcnConfig::default(),
            composition: TemporalComposition::Multiply,
            relation_update: TemporalRelationUpdate::JointLinear,
        }
    }
}

impl TemporalCompgcnConfig {
    pub fn validate(self) -> Result<(), TemporalCompgcnError> {
        self.base
            .validate()
            .map_err(|_| TemporalCompgcnError::InvalidContract("configuration"))
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalCompgcnTrainingReceipt {
    pub trainer_id: CompactString,
    pub train_facts: u64,
    pub directed_messages: u64,
    pub training_examples: u64,
    pub optimizer_steps: u64,
    pub optimizer_state_blake3: CompactString,
    pub train_topology_blake3: CompactString,
    pub relation_state_bytes: u64,
    pub test_locked_during_training: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalCompgcnWeights {
    pub node_embeddings: Vec<f32>,
    pub direction_weights: Vec<f32>,
    pub relation_embeddings: Vec<f32>,
    pub relation_projection: Vec<f32>,
    pub decoder_bias: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalCompgcnSnapshot {
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub control_manifest_id: CompactString,
    pub control_model_id: CompactString,
    pub config: TemporalCompgcnConfig,
    pub runtime: TemporalRgcnRuntimeIdentity,
    pub training: TemporalCompgcnTrainingReceipt,
    pub baseline: LinkPredictionScoreCertificate,
    pub control: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub weights: TemporalCompgcnWeights,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalCompgcnManifest {
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
    pub control_manifest_id: CompactString,
    pub control_model_id: CompactString,
    pub config: TemporalCompgcnConfig,
    pub runtime: TemporalRgcnRuntimeIdentity,
    pub training: TemporalCompgcnTrainingReceipt,
    pub baseline: LinkPredictionScoreCertificate,
    pub control: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub weights_file: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemporalCompgcnPaths {
    pub manifest: PathBuf,
    pub weights: PathBuf,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
}

#[derive(Debug, thiserror::Error)]
pub enum TemporalCompgcnError {
    #[error("temporal CompGCN contract is invalid: {0}")]
    InvalidContract(&'static str),
    #[error("temporal CompGCN artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("temporal CompGCN artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("temporal R-GCN control failed validation: {0}")]
    Control(#[from] crate::TemporalRgcnError),
    #[error("canonical link task failed validation: {0}")]
    Task(#[from] crate::LinkPredictionError),
    #[error("temporal CompGCN I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("temporal CompGCN JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
