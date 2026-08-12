use std::path::PathBuf;

use thiserror::Error;

pub type Result<T, E = CorpusError> = std::result::Result<T, E>;

#[derive(Debug, Error)]
pub enum CorpusError {
    #[error("I/O failure at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("JSON failure at {path}: {source}")]
    Json {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },
    #[error("unsupported or invalid contract: {0}")]
    Contract(String),
    #[error("sealed artifact is missing: {0}")]
    Missing(PathBuf),
    #[error("sealed artifact was mutated: {path} ({detail})")]
    Mutation { path: PathBuf, detail: String },
    #[error("unexpected file in immutable run: {0}")]
    ExtraFile(PathBuf),
    #[error("TSV error at {path}, row {row}: {detail}")]
    Tsv {
        path: PathBuf,
        row: usize,
        detail: String,
    },
    #[error("relational invariant failed for {run_key}: {detail}")]
    Relational { run_key: String, detail: String },
}

pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> CorpusError {
    CorpusError::Io {
        path: path.into(),
        source,
    }
}
