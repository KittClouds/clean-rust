use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum GfmError {
    #[error("I/O error for {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid graph: {0}")]
    InvalidGraph(String),
    #[error("invalid artifact: {0}")]
    InvalidArtifact(String),
    #[error("invalid checkpoint: {0}")]
    InvalidCheckpoint(String),
    #[error("shape mismatch: {0}")]
    Shape(String),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("safetensors error: {0}")]
    Safetensors(#[from] safetensors::SafeTensorError),
    #[error("tensor error: {0}")]
    Candle(#[from] candle_core::Error),
    #[cfg(feature = "mpnet-onnx")]
    #[error("tokenizer error: {0}")]
    Tokenizer(String),
    #[cfg(feature = "mpnet-onnx")]
    #[error("ONNX Runtime error: {0}")]
    Ort(String),
}

pub type Result<T> = std::result::Result<T, GfmError>;

pub(crate) fn io_error(path: impl Into<PathBuf>, source: std::io::Error) -> GfmError {
    GfmError::Io {
        path: path.into(),
        source,
    }
}
