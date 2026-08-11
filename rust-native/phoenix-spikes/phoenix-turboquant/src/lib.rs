//! Clean-room TurboQuant experiment for Phoenix's immutable embedding pages.
//!
//! The crate deliberately implements a narrow contract: normalized or finite
//! `f32` vectors are encoded into 2-bit or 4-bit scalar codes after a
//! deterministic orthogonal mixing transform, published atomically, reopened
//! through a verified read-only mmap, and searched with scalar/AVX2 parity.
//! It is experimental derived data and never graph or source authority.

mod codebook;
mod encode;
mod error;
mod exact;
mod format;
mod index;
mod rotation;
mod search;
mod throughput;

pub use codebook::LloydMaxCodebook;
pub use encode::{encode_vectors, EncodedVectors};
pub use error::{Result, TurboQuantError};
pub use exact::{
    exact_rerank_candidates_into, exact_search, exact_search_into,
    profile_exact_parallel_search_into, profile_exact_search_into, ExactPhaseTimings,
    ExactSearchScratch,
};
pub use format::{ArtifactAuthority, ArtifactHeader, QuantizedFormat, HEADER_BYTES, MAGIC};
pub use index::{write_quantized_artifact_new, VerifiedQuantizedIndex};
pub use rotation::{Rotation, ROTATION_CONTRACT};
pub use search::{
    BatchSearchScratch, BlockLocalPhaseTimings, BlockLocalTopKConfig, PhaseTimings,
    QueryPreparationTimings, SearchExecution, SearchHit, SearchKernel, SearchScratch,
    MAX_BATCH_QUERIES, MAX_BLOCK_ROWS, MAX_LOCAL_K,
};
pub use throughput::{
    recommend_search_dispatch, recommend_search_throughput, SearchDispatchPlan,
    SearchThroughputMode, SearchThroughputPlan,
};

/// Stable artifact extension for the first clean-room experiment.
pub const ARTIFACT_EXTENSION: &str = "phxq1";
