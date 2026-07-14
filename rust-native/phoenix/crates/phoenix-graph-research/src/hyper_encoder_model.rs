use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const HYPER_ENCODER_SCHEMA: &str = "phoenix-stare-compgcn-encoder/v1";
pub const HYPER_ENCODER_HIDDEN: usize = 16;
pub const HYPER_ENCODER_DIRECTIONS: usize = 3;
pub const HYPER_ENCODER_MODEL_SCHEMA: &str = "phoenix-hyper-encoder-model/v1";
pub const HYPER_ENCODER_PAIR_SCHEMA: &str = "phoenix-hyper-encoder-pair/v1";
pub const HYPER_ENCODER_MODEL_BINARY_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperEncoderMode {
    CompgcnTriple,
    StareQualifiers,
    RoleOnly,
    ValueOnly,
    Shuffled,
    Detached,
    QueryOnly,
    MessageOnly,
}

impl HyperEncoderMode {
    pub fn uses_query_qualifiers(self) -> bool {
        !matches!(self, Self::CompgcnTriple | Self::MessageOnly)
    }

    pub fn uses_message_qualifiers(self) -> bool {
        !matches!(self, Self::CompgcnTriple | Self::QueryOnly)
    }

    pub fn propagates_qualifier_gradients(self) -> bool {
        !matches!(self, Self::CompgcnTriple | Self::Detached)
    }

    pub fn uses_shuffled_qualifiers(self) -> bool {
        self == Self::Shuffled
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderConfig {
    pub seed: u64,
    pub mode: HyperEncoderMode,
}

impl HyperEncoderConfig {
    pub fn compgcn(seed: u64) -> Self {
        Self {
            seed,
            mode: HyperEncoderMode::CompgcnTriple,
        }
    }

    pub fn stare(seed: u64) -> Self {
        Self {
            seed,
            mode: HyperEncoderMode::StareQualifiers,
        }
    }

    pub fn with_mode(seed: u64, mode: HyperEncoderMode) -> Self {
        Self { seed, mode }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct HyperEncoderWeights {
    pub node_embeddings: Vec<f32>,
    pub direction_weights: Vec<f32>,
    pub relation_embeddings: Vec<f32>,
    pub relation_projection: Vec<f32>,
    pub qualifier_projection: Vec<f32>,
    pub decoder_bias: Vec<f32>,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderTrainingConfig {
    pub epochs: u32,
    pub learning_rate: f32,
    pub l2: f32,
    pub negatives_per_positive: u8,
}

impl Default for HyperEncoderTrainingConfig {
    fn default() -> Self {
        Self {
            epochs: 4,
            learning_rate: 0.04,
            l2: 0.000_05,
            negatives_per_positive: 1,
        }
    }
}

impl HyperEncoderTrainingConfig {
    pub fn validate(self) -> Result<(), HyperEncoderError> {
        if self.epochs == 0
            || !self.learning_rate.is_finite()
            || self.learning_rate <= 0.0
            || !self.l2.is_finite()
            || self.l2 < 0.0
            || self.negatives_per_positive == 0
        {
            return Err(HyperEncoderError::InvalidContract("training configuration"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderTrainingReceipt {
    pub trainer_id: CompactString,
    pub initialization_blake3: CompactString,
    pub train_topology_blake3: CompactString,
    pub example_schedule_blake3: CompactString,
    pub train_statements: u64,
    pub directed_messages: u64,
    pub training_examples: u64,
    pub optimizer_steps: u64,
    pub optimizer_state_blake3: CompactString,
    pub gradient_arena_bytes: u64,
    pub epoch_allocation_bytes: u64,
    pub epoch_allocation_count: u64,
    pub test_locked_during_training: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct HyperEncoderModelSnapshot {
    pub pair_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub config: HyperEncoderConfig,
    pub training_config: HyperEncoderTrainingConfig,
    pub training: HyperEncoderTrainingReceipt,
    pub validation: crate::HyperRelationalScoreCertificate,
    pub weights: HyperEncoderWeights,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderModelManifest {
    pub schema_version: CompactString,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
    pub pair_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub directed_relation_count: u32,
    pub hidden_features: u16,
    pub config: HyperEncoderConfig,
    pub training_config: HyperEncoderTrainingConfig,
    pub training: HyperEncoderTrainingReceipt,
    pub validation: crate::HyperRelationalScoreCertificate,
    pub weights_file: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HyperEncoderModelPaths {
    pub manifest: PathBuf,
    pub weights: PathBuf,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderPairManifest {
    pub schema_version: CompactString,
    pub pair_id: CompactString,
    pub trainer_id: CompactString,
    pub source_dataset_id: CompactString,
    pub task_id: CompactString,
    pub seed: u64,
    pub training_config: HyperEncoderTrainingConfig,
    pub initialization_blake3: CompactString,
    pub example_schedule_blake3: CompactString,
    pub compgcn_manifest_id: CompactString,
    pub compgcn_model_id: CompactString,
    pub compgcn_validation_certificate_id: CompactString,
    pub stare_manifest_id: CompactString,
    pub stare_model_id: CompactString,
    pub stare_validation_certificate_id: CompactString,
    pub qualifier_intervention_only: bool,
    pub test_partition_accessed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HyperEncoderPairPaths {
    pub manifest: PathBuf,
    pub pair_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderStagingProfile {
    pub train_statements: u64,
    pub directed_messages: u64,
    pub canonical_qualifier_refs: u64,
    pub canonical_ref_bytes: u64,
    pub staged_bytes: u64,
    pub staging_micros: u64,
    pub train_topology_blake3: CompactString,
    pub original_filter_order_preserved: bool,
    pub qualifier_payload_bytes_copied: u64,
    pub train_only: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEncoderPairResult {
    pub compgcn_model_id: CompactString,
    pub stare_model_id: CompactString,
    pub compgcn: crate::HyperRelationalScoreCertificate,
    pub stare: crate::HyperRelationalScoreCertificate,
}

#[derive(Debug, thiserror::Error)]
pub enum HyperEncoderError {
    #[error("hyper encoder contract is invalid: {0}")]
    InvalidContract(&'static str),
    #[error("external dataset failed validation: {0}")]
    Source(#[from] crate::ExternalDatasetError),
    #[error("hyper-relational task failed validation: {0}")]
    Task(#[from] crate::HyperRelationalTaskError),
    #[error("hyper encoder identity failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("hyper encoder artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("hyper encoder artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("hyper encoder artifact I/O failed: {0}")]
    Io(#[from] std::io::Error),
}
