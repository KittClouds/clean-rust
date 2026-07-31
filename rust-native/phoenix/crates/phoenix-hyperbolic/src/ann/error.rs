use crate::{MetricIdentity, StableVectorId};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum HyperbolicDiskError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("legacy serialization error: {0}")]
    Bincode(#[from] bincode::Error),
    #[error("vector dimension must be in 1..={maximum}; got {actual}")]
    InvalidDimension { actual: usize, maximum: usize },
    #[error("vector {id:?} has dimension {actual}; expected {expected}")]
    DimensionMismatch {
        id: StableVectorId,
        expected: usize,
        actual: usize,
    },
    #[error("vector {id:?} already exists")]
    DuplicateVectorId { id: StableVectorId },
    #[error("stable vector ID zero is reserved")]
    ZeroVectorId,
    #[error("vector contains a non-finite component")]
    NonFiniteVector,
    #[error("invalid HNSW configuration: {0}")]
    InvalidConfig(&'static str),
    #[error("invalid search parameters: {0}")]
    InvalidSearch(&'static str),
    #[error("index is too large for dense u32 identifiers")]
    DenseIdOverflow,
    #[error("archive already exists: {0}")]
    ImmutableTargetExists(PathBuf),
    #[error("archive range or alignment is invalid")]
    InvalidArchiveRange,
    #[error("archive magic, version, endian marker, or scalar type is unsupported")]
    UnsupportedArchive,
    #[error("archive section {section} is missing")]
    MissingSection { section: u32 },
    #[error("archive section {section} is duplicated")]
    DuplicateSection { section: u32 },
    #[error("archive section {section} hash does not match")]
    CorruptSection { section: u32 },
    #[error("archive root hash does not match")]
    CorruptRoot,
    #[error("archive topology is invalid: {0}")]
    InvalidTopology(&'static str),
    #[error("archive declares {declared} bytes; configured maximum is {maximum}")]
    OversizedArchive { declared: u64, maximum: u64 },
    #[error("archive metric {actual:?} does not match requested metric {expected:?}")]
    MetricMismatch {
        expected: MetricIdentity,
        actual: MetricIdentity,
    },
    #[error("index error: {0}")]
    IndexError(String),
}
