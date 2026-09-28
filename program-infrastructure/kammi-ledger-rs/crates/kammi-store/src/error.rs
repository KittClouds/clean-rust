use std::path::PathBuf;

use kammi_jcs::{JcsError, Sha256Id};

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error("I/O error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("writable store already owned by another writer: {0}")]
    Busy(PathBuf),
    #[error("not a v2 store (missing or invalid STORE.json): {0}")]
    NotAStore(PathBuf),
    #[error("refusing to create a store in a non-empty directory: {0}")]
    AlreadyExists(PathBuf),
    #[error("corrupt {what} in {path} at offset {offset}: {reason}")]
    Corrupt {
        what: &'static str,
        path: PathBuf,
        offset: u64,
        reason: String,
    },
    #[error("invalid event: {0}")]
    InvalidEvent(String),
    #[error("duplicate request ID: {0}")]
    DuplicateRequest(String),
    #[error("event chain mismatch: expected seq {expected_seq} after head {expected_prev}")]
    Chain {
        expected_seq: u64,
        expected_prev: Sha256Id,
    },
    #[error("payload bytes do not hash to payload_artifact {0}")]
    PayloadMismatch(Sha256Id),
    #[error("CAS object missing: {0}")]
    ObjectMissing(Sha256Id),
    #[error("CAS object corrupt: {0}")]
    ObjectCorrupt(Sha256Id),
    #[error("{0} exceeds its size limit")]
    TooLarge(&'static str),
    #[error("journal {0} failed mid-write; reopen the store to recover")]
    Poisoned(String),
    #[error("unknown event sequence {0}")]
    UnknownSeq(u64),
    #[error(transparent)]
    Jcs(#[from] JcsError),
}

pub type Result<T> = std::result::Result<T, StoreError>;

pub(crate) fn io(path: impl Into<PathBuf>) -> impl FnOnce(std::io::Error) -> StoreError {
    let path = path.into();
    move |source| StoreError::Io { path, source }
}

pub(crate) fn corrupt(
    what: &'static str,
    path: impl Into<PathBuf>,
    offset: u64,
    reason: impl Into<String>,
) -> StoreError {
    StoreError::Corrupt {
        what,
        path: path.into(),
        offset,
        reason: reason.into(),
    }
}
