//! Isolated, inference-only parity implementation for GFM-RAG-8M.
//!
//! This crate deliberately has no dependency on Phoenix persistence or graph
//! mutation crates. Inputs are immutable snapshot views; dense IDs exist only
//! for the lifetime of a derived inference artifact.

pub mod adapter;
pub mod artifact;
pub mod checkpoint;
pub mod constants;
pub mod error;
pub mod graph;
pub mod kernel;
pub mod model;
#[cfg(feature = "mpnet-onnx")]
pub mod mpnet;
pub mod ranker;

pub use error::{GfmError, Result};
