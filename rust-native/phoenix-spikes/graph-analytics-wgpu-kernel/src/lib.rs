//! Isolated GPU preprocessing for large, generation-bound graph analytics.
//!
//! The output is derived data only. In particular, this crate intentionally
//! has no Leiden/local-move API: deterministic community authority remains in
//! `phoenix-discovery-community` on CPU Rust.

mod cpu;
mod error;
mod gpu_storage;
mod policy;
mod runtime;
mod types;

pub use cpu::cpu_analyze;
pub use error::GraphAnalyticsError;
pub use policy::{DispatchBackend, DispatchPolicy, WorkloadShape};
pub use runtime::{AdapterReceipt, GpuGraphAnalyticsRuntime, ResidentGraphAnalytics};
pub use types::{
    AnalyticsInput, AnalyticsOutput, AnalyticsTiming, BridgePreprocessOutput, EdgePolicy,
    PackedEdge, PrepartitionOutput, RunConfig,
};
