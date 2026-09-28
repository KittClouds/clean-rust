//! Read-only access to Python (v1) Kammi Library stores.
//!
//! The live Python daemon owns these files. Everything here opens them with ordinary shared
//! read handles and positional reads, and never memory-maps them: on Windows a mapping would
//! make Python's torn-tail truncation fail. A partially written final frame is reported as
//! "nothing new yet", never repaired — repair belongs to the owning writer.

mod journal;
mod store;
mod vocabulary;

pub use journal::{JournalReader, V1Event};
pub use store::V1Store;
pub use vocabulary::{EVENT_FIELDS, EVENT_SCHEMA, EVENT_TYPES};

use std::path::PathBuf;

use kammi_jcs::{JcsError, Sha256Id};

/// Largest committed frame the v1 journal accepts (`journal.py:MAX_EVENT_BYTES`).
pub const MAX_EVENT_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum V1Error {
    #[error("I/O error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid journal frame length {length} at offset {offset}")]
    FrameLength { offset: u64, length: u64 },
    #[error("journal checksum mismatch at offset {offset}")]
    Checksum { offset: u64 },
    #[error("journal frame at offset {offset} is not strict JSON: {source}")]
    Json {
        offset: u64,
        #[source]
        source: JcsError,
    },
    #[error("noncanonical journal event at offset {offset}")]
    NonCanonical { offset: u64 },
    #[error("event at offset {offset} does not match the registered vocabulary: {reason}")]
    Vocabulary { offset: u64, reason: &'static str },
    #[error("broken journal chain at offset {offset}")]
    Chain { offset: u64 },
    #[error("duplicate journal request ID at offset {offset}")]
    DuplicateRequest { offset: u64 },
    #[error("journal shrank below committed history: expected at least {expected} bytes, found {actual}")]
    HistoryRewritten { expected: u64, actual: u64 },
    #[error("not a v1 store (missing journal/events.log): {0}")]
    NotAStore(PathBuf),
    #[error("CAS object missing: {0}")]
    ObjectMissing(Sha256Id),
    #[error("CAS object corrupt: {0}")]
    ObjectCorrupt(Sha256Id),
}

impl V1Error {
    pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        V1Error::Io {
            path: path.into(),
            source,
        }
    }
}
