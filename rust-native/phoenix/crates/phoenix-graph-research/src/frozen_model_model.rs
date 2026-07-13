use crate::{ResearchSplit, SeedCertificate};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const FROZEN_MODEL_SCHEMA: &str = "phoenix-frozen-model/v1";
pub const FROZEN_MODEL_BINARY_VERSION: u16 = 1;
pub const MODEL_HIDDEN_WEIGHT: &str = "hidden.weight";
pub const MODEL_HIDDEN_BIAS: &str = "hidden.bias";
pub const MODEL_OUTPUT_WEIGHT: &str = "output.weight";
pub const MODEL_OUTPUT_BIAS: &str = "output.bias";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum FrozenModelFamily {
    Mlp16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelSourceIdentity {
    pub dataset_id: CompactString,
    pub checkpoint_id: CompactString,
    pub checkpoint_generation: u64,
    pub tensor_id: CompactString,
    pub topology_derivation_id: CompactString,
    pub topology_blake3: CompactString,
    pub evaluation_protocol_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelArchitecture {
    pub family: FrozenModelFamily,
    pub input_features: u16,
    pub hidden_features: u16,
    pub output_features: u16,
    pub hidden_activation: CompactString,
    pub output_activation: CompactString,
    pub weight_layout: CompactString,
}

impl FrozenModelArchitecture {
    pub fn mlp16() -> Self {
        Self {
            family: FrozenModelFamily::Mlp16,
            input_features: 16,
            hidden_features: 16,
            output_features: 1,
            hidden_activation: "relu".into(),
            output_activation: "sigmoid".into(),
            weight_layout: "row-major-output-input".into(),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelHyperparameters {
    pub epochs: u32,
    pub batch_size: u32,
    pub learning_rate: f32,
    pub l2: f32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelRuntimeIdentity {
    pub framework: CompactString,
    pub framework_version: CompactString,
    pub backend: CompactString,
    pub target: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenOptimizerReceipt {
    pub algorithm: CompactString,
    pub implementation_version: CompactString,
    pub steps_completed: u64,
    pub state_blake3: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenTrainingReceipt {
    pub trainer_id: CompactString,
    pub training_examples: u64,
    pub validation_examples: u64,
    pub epochs_completed: u32,
    pub training_executions: u32,
    pub selected_on_validation: bool,
    pub test_locked_during_selection: bool,
    pub optimizer: FrozenOptimizerReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelSeedReceipt {
    pub certificate: SeedCertificate,
    pub selected_repeat: u16,
}

impl FrozenModelSeedReceipt {
    pub fn selected_seed(&self) -> Option<u64> {
        self.certificate
            .seeds
            .get(self.selected_repeat as usize)
            .copied()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelScoreCertificate {
    pub task_id: CompactString,
    pub evaluator_schema: CompactString,
    pub split: ResearchSplit,
    pub score_count: u64,
    pub score_dtype: CompactString,
    pub score_blake3: CompactString,
    pub metrics_blake3: CompactString,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelTensor {
    pub name: CompactString,
    pub shape: Vec<u64>,
    pub values: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelSnapshot {
    pub source: FrozenModelSourceIdentity,
    pub architecture: FrozenModelArchitecture,
    pub hyperparameters: FrozenModelHyperparameters,
    pub seeds: FrozenModelSeedReceipt,
    pub runtime: FrozenModelRuntimeIdentity,
    pub training: FrozenTrainingReceipt,
    pub score_certificates: Vec<FrozenModelScoreCertificate>,
    pub tensors: Vec<FrozenModelTensor>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelTensorManifest {
    pub name: CompactString,
    pub shape: Vec<u64>,
    pub element_count: u64,
    pub byte_offset: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenModelManifest {
    pub schema_version: CompactString,
    pub model_id: CompactString,
    pub source: FrozenModelSourceIdentity,
    pub architecture: FrozenModelArchitecture,
    pub hyperparameters: FrozenModelHyperparameters,
    pub seeds: FrozenModelSeedReceipt,
    pub runtime: FrozenModelRuntimeIdentity,
    pub training: FrozenTrainingReceipt,
    pub score_certificates: Vec<FrozenModelScoreCertificate>,
    pub weights_file: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
    pub tensors: Vec<FrozenModelTensorManifest>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenModelPaths {
    pub manifest: PathBuf,
    pub weights: PathBuf,
}

#[derive(Debug, thiserror::Error)]
pub enum FrozenModelError {
    #[error("frozen model contract is invalid: {0}")]
    InvalidContract(&'static str),
    #[error("frozen model tensor layout is invalid: {0}")]
    InvalidTensorLayout(&'static str),
    #[error("frozen model identity does not match its manifest")]
    IdentityMismatch,
    #[error("frozen model artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("frozen model artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("frozen model artifact I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("frozen model manifest encoding failed: {0}")]
    Json(#[from] serde_json::Error),
}
