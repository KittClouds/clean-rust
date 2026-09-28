mod build;
mod families;
mod format;
mod persistence;

use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use thiserror::Error;

pub use build::{build_document_index_shard, DocumentIndexInput};
pub use families::{
    document_index_family_routes, document_index_family_routes_with_mask, DocumentIndexFamilyMask,
    DocumentIndexFamilyRoute, DocumentIndexFamilyRouteLimits, DocumentIndexFamilyRoutes,
    DocumentIndexFamilyTarget, DocumentIndexFamilyTargetKind, DocumentIndexRouteFamily,
};
pub use format::{DocumentIndexUnit, DocumentIndexUnitKind, MmapDocumentIndex};
pub use persistence::{
    document_index_shard_path, persist_document_index_shard, DocumentIndexShardWrite,
};

pub const DOCUMENT_INDEX_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentIndexShardRef {
    pub schema_version: u16,
    pub document_id: String,
    pub note_id: Option<String>,
    pub content_hash: String,
    pub byte_len: u64,
    pub unit_count: u32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreparedDocumentIndexShard {
    pub reference: DocumentIndexShardRef,
    pub bytes: Arc<[u8]>,
}

#[derive(Debug, Error)]
pub enum DocumentIndexError {
    #[error("document index input is too large: {0}")]
    InputTooLarge(&'static str),
    #[error("invalid document index: {0}")]
    Invalid(String),
    #[error("document index I/O at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
}

pub(crate) fn io_error(path: impl Into<PathBuf>, source: std::io::Error) -> DocumentIndexError {
    DocumentIndexError::Io {
        path: path.into(),
        source,
    }
}

#[cfg(test)]
mod tests;
