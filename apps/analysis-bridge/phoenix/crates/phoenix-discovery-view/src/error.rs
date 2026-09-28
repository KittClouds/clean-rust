use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DiscoveryViewError {
    #[error("discovery view I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("discovery view manifest error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid discovery view: {0}")]
    Invalid(String),
    #[error("discovery view already has an active build directory: {0}")]
    BuildCollision(PathBuf),
    #[error("discovery generation {generation} is already bound to artifact {existing}")]
    GenerationConflict { generation: u64, existing: String },
}
