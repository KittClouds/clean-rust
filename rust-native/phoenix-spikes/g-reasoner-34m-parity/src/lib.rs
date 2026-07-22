//! Isolated Rust parity implementation for G-reasoner-34M.
//!
//! The crate consumes immutable asserted-graph snapshots. It has no dependency
//! on Phoenix persistence, training, or graph-mutation crates.

pub mod adapter;
pub mod artifact;
pub mod checkpoint;
pub mod constants;
pub mod error;
pub mod graph;
pub mod kernel;
pub mod model;
#[cfg(feature = "qwen")]
pub mod qwen;
#[cfg(feature = "qwen-onnx")]
pub mod qwen_onnx;
pub mod ranker;

pub use error::{GfmError, Result};
