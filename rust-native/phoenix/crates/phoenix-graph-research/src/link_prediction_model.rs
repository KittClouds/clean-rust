use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub const LINK_PREDICTION_TASK_SCHEMA: &str = "phoenix-canonical-link-prediction-task/v1";
pub const LINK_PREDICTION_TASK_BINARY_VERSION: u16 = 1;
pub const LINK_PREDICTION_TEST_LOCK_SCHEMA: &str = "phoenix-link-prediction-test-lock/v1";
pub const LINK_PREDICTION_SCORE_SCHEMA: &str = "phoenix-link-prediction-score/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum LinkPredictionSplit {
    Validation = 2,
    Test = 3,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct LinkPredictionQuery {
    pub observed_at: i64,
    pub source: u32,
    pub relation: u32,
    pub conflict_offset: u32,
    pub conflict_count: u32,
    pub split: LinkPredictionSplit,
    pub inverse: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct LinkPredictionTaskSnapshot {
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub validation_pickle_blake3: CompactString,
    pub test_pickle_blake3: CompactString,
    pub validation_parity_blake3: CompactString,
    pub test_parity_blake3: CompactString,
    pub queries: Vec<LinkPredictionQuery>,
    pub conflicts: Vec<u32>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LinkPredictionQueryView {
    pub observed_at: i64,
    pub source: u32,
    pub relation: u32,
    pub split: LinkPredictionSplit,
    pub inverse: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LinkPredictionTaskManifest {
    pub schema_version: CompactString,
    pub task_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub strategy: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub derived_relation_count: u32,
    pub validation_pickle_blake3: CompactString,
    pub test_pickle_blake3: CompactString,
    pub validation_parity_blake3: CompactString,
    pub test_parity_blake3: CompactString,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub validation_queries: u64,
    pub validation_positives: u64,
    pub test_queries: u64,
    pub test_positives: u64,
    pub inverse_queries: u64,
    pub test_locked: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LinkPredictionTaskPaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
    pub task_id: CompactString,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FilteredRankingMetrics {
    pub mean_reciprocal_rank: f64,
    pub hits_at_1: f64,
    pub hits_at_3: f64,
    pub hits_at_10: f64,
    pub queries: u64,
    pub positives: u64,
    pub candidates_scored: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LinkPredictionScoreCertificate {
    pub schema_version: CompactString,
    pub certificate_id: CompactString,
    pub task_id: CompactString,
    pub model_id: CompactString,
    pub split: LinkPredictionSplit,
    pub score_blake3: CompactString,
    pub mean_reciprocal_rank: f64,
    pub hits_at_1: f64,
    pub hits_at_3: f64,
    pub hits_at_10: f64,
    pub queries: u64,
    pub positives: u64,
    pub candidates_scored: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LinkPredictionTestLockInput {
    pub task_id: CompactString,
    pub selection_ledger_id: CompactString,
    pub selected_model_id: CompactString,
    pub validation_certificate_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LinkPredictionTestLock {
    pub schema_version: CompactString,
    pub lock_id: CompactString,
    pub task_id: CompactString,
    pub selection_ledger_id: CompactString,
    pub selected_model_id: CompactString,
    pub validation_certificate_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LinkPredictionTestLockPaths {
    pub receipt: PathBuf,
    pub lock_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LinkPredictionTestResultPaths {
    pub claim: PathBuf,
    pub certificate: PathBuf,
}

#[derive(Debug, Error)]
pub enum LinkPredictionError {
    #[error("link-prediction task input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("unsupported TGB pickle opcode: 0x{0:02x}")]
    UnsupportedPickleOpcode(u8),
    #[error("TGB pickle structure is invalid: {0}")]
    InvalidPickle(&'static str),
    #[error("official TGB negative parity failed for {0:?}")]
    NegativeParity(LinkPredictionSplit),
    #[error("link-prediction artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("link-prediction artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("test evaluation is already claimed: {0}")]
    TestAlreadyClaimed(PathBuf),
    #[error("link-prediction scorer failed: {0}")]
    Scorer(String),
    #[error("link-prediction I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("link-prediction JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
