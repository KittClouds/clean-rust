use std::path::PathBuf;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum InferenceArtifactError {
    #[error("I/O failed for {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid inference artifact: {0}")]
    InvalidArtifact(String),
    #[error("invalid authoritative projection: {0}")]
    InvalidProjection(String),
    #[error("model hot cache failed: {0}")]
    HotCache(#[from] phoenix_model_hot_cache::HotCacheError),
    #[error("JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("8M inference failed: {0}")]
    Gfm8(#[from] gfm_rag_8m_parity::GfmError),
    #[error("34M inference failed: {0}")]
    Reasoner34(#[from] g_reasoner_34m_parity::GfmError),
    #[error("tensor operation failed: {0}")]
    Tensor(#[from] candle_core::Error),
}

pub type Result<T> = std::result::Result<T, InferenceArtifactError>;

pub(crate) fn io_error(path: impl Into<PathBuf>, source: std::io::Error) -> InferenceArtifactError {
    InferenceArtifactError::Io {
        path: path.into(),
        source,
    }
}
