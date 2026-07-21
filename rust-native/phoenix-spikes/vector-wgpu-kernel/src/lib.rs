//! Vendor-neutral GPU exact scoring for ANN-produced candidate batches.
//!
//! This crate cannot discover candidates, scan a graph, or mutate Phoenix
//! truth. Callers retain ownership of HNSW/LSH candidate generation and pass
//! only bounded candidate identities into the resident GPU reranker.

mod cpu;
mod policy;
mod reconcile;
mod residency;
mod runtime;
mod shadow;
mod types;

pub use cpu::{CpuResidentCorpus, cpu_exact_top_k, normalize_rows, quantize_symmetric_i8};
pub use policy::{DispatchBackend, DispatchPolicy};
pub use residency::{GpuResidencyCache, ResidencyKey, ResidentLease};
pub use runtime::{
    AdapterReceipt, DispatchReceipt, GpuPreprocessOutput, GpuTopKOutput, GpuVectorRuntime,
    PreprocessReceipt, ResidencyReceipt, ResidentVectorCorpus,
};
pub use shadow::{
    GpuShadowReceipt, ShadowDisposition, ShadowInput, verify_gpu_shadow,
    verify_gpu_shadow_with_provider, verify_gpu_shadow_with_provider_and_scorer,
};
pub use types::{
    CompactTopKOutput, INVALID_CANDIDATE, MAX_CANDIDATES_PER_QUERY, MAX_DIMENSIONS, MAX_TOP_K,
    QuantizedRows, RawVectorInput, TopKRecord, ValidatedCorpus, ValidatedPreprocess,
    ValidatedRerankBatch, VectorCorpusInput, VectorError, VectorRerankBatch, WORKGROUP_WIDTH,
};
