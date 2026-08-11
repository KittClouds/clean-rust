use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum TurboQuantError {
    #[error("unsupported bit width {0}; expected 2 or 4")]
    UnsupportedBitWidth(u8),
    #[error("dimension {0} must be a non-zero multiple of eight")]
    InvalidDimension(usize),
    #[error("vector slab length {actual} does not match rows {rows} x dimension {dimension}")]
    InvalidVectorLength {
        actual: usize,
        rows: usize,
        dimension: usize,
    },
    #[error("query dimension {actual} does not match index dimension {expected}")]
    QueryDimension { actual: usize, expected: usize },
    #[error("non-finite value at row {row}, coordinate {coordinate}")]
    NonFinite { row: usize, coordinate: usize },
    #[error("subject ids must be non-zero, unique, and strictly increasing")]
    NonCanonicalIds,
    #[error("quantized artifact I/O failed at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("quantized artifact already exists at {0}")]
    AlreadyExists(PathBuf),
    #[error("quantized artifact is too small")]
    TooSmall,
    #[error("unsupported quantized artifact magic or version")]
    UnsupportedArtifact,
    #[error("quantized artifact is incomplete")]
    IncompleteArtifact,
    #[error("quantized artifact layout is invalid")]
    InvalidLayout,
    #[error("quantized artifact hash mismatch for {0}")]
    HashMismatch(&'static str),
    #[error("quantized artifact authority mismatch for {0}")]
    AuthorityMismatch(&'static str),
    #[error("quantized artifact scale {row} is invalid")]
    InvalidScale { row: usize },
    #[error("arithmetic overflow while constructing artifact")]
    Overflow,
    #[error("query scratch has not been prepared")]
    UnpreparedQuery,
    #[error("prepared query belongs to a different quantizer contract")]
    PreparedContractMismatch,
    #[error("batch query count {actual} is outside the supported range 1..={maximum}")]
    InvalidBatchSize { actual: usize, maximum: usize },
    #[error("batch output count {actual} does not match query count {expected}")]
    BatchOutputLength { actual: usize, expected: usize },
    #[error("block-local rows {0} must be a non-zero multiple of eight no larger than 4096")]
    InvalidBlockRows(usize),
    #[error("block-local k {local_k} must be between global k {top_k} and 128")]
    InvalidLocalK { local_k: usize, top_k: usize },
    #[error("block-local top-k supports global k no larger than 64, received {0}")]
    BlockLocalTopKTooLarge(usize),
}

impl TurboQuantError {
    pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::Io {
            path: path.into(),
            source,
        }
    }
}

pub type Result<T> = std::result::Result<T, TurboQuantError>;
