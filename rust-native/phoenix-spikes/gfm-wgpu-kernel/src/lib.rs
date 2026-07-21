//! Vendor-neutral GPU proof for the shared GFM incoming-CSR aggregation seam.
//!
//! This crate is deliberately inference-only. It cannot access Phoenix stores,
//! publish graph artifacts, or mutate graph truth. The established AVX2/FMA
//! kernels remain the production path and independent parity oracles.

mod chain;
mod chain_cpu;
mod chain_runtime;
mod chain_support;
mod input;
mod policy;
mod runtime;

pub use chain::{
    ChainTiming, ChainTraceOutput, CompactChainOutput, MAX_TOP_K, ResidentChainInput, TopKRecord,
    ValidatedResidentChain,
};
pub use chain_cpu::{CpuChainOutput, cpu_resident_chain};
pub use chain_runtime::{GpuResidentChainRuntime, ResidentModelChain};
pub use input::{DistMultInput, ValidatedDistMult, WORKGROUP_WIDTH};
pub use policy::{DispatchBackend, DispatchPolicy};
pub use runtime::{
    AdapterReceipt, DispatchOutput, DispatchReceipt, GpuError, GpuKernelRuntime, ResidencyReceipt,
    ResidentDistMult,
};
