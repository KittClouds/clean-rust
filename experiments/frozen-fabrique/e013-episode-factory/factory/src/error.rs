use std::path::PathBuf;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum FactoryError {
    #[error("invalid E013 input: {0}")]
    Invalid(String),
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("git command failed ({command}): {stderr}")]
    Git { command: String, stderr: String },
    #[error("command setup failed in phase {phase}: {source}")]
    CommandSetup {
        phase: String,
        #[source]
        source: std::io::Error,
    },
    #[error("episode seal verification failed: {0}")]
    Seal(String),
    #[error("cross-bank disjointness failure: {0}")]
    Disjointness(String),
}

pub(crate) fn io_error(path: impl Into<PathBuf>, source: std::io::Error) -> FactoryError {
    FactoryError::Io {
        path: path.into(),
        source,
    }
}
