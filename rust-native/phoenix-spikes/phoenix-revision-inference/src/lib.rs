//! Immutable production inference artifacts for revision-impact model overlays.
//!
//! This crate can read authoritative Phoenix projections, but it has no graph
//! persistence dependency and exposes no mutation API.

#[cfg(feature = "encoders")]
pub mod bounded_reasoner;
pub mod bundle;
#[cfg(feature = "duel")]
pub mod cached_reasoner;
#[cfg(feature = "duel")]
pub mod duel;
#[cfg(feature = "duel")]
pub mod duel_runtime;
#[cfg(feature = "encoders")]
pub mod embedding_cache;
pub mod error;
#[cfg(feature = "duel")]
pub mod focused_metrics;
#[cfg(feature = "encoders")]
pub mod index_builder;
pub mod matrix;
pub mod metrics;
pub mod projection;
#[cfg(feature = "duel")]
pub mod review;
#[cfg(feature = "encoders")]
pub mod runner;

#[cfg(feature = "encoders")]
pub use bounded_reasoner::*;
pub use bundle::*;
#[cfg(feature = "duel")]
pub use cached_reasoner::*;
#[cfg(feature = "duel")]
pub use duel::*;
#[cfg(feature = "duel")]
pub use duel_runtime::*;
#[cfg(feature = "encoders")]
pub use embedding_cache::*;
pub use error::*;
#[cfg(feature = "duel")]
pub use focused_metrics::*;
#[cfg(feature = "encoders")]
pub use index_builder::*;
pub use matrix::*;
pub use metrics::*;
pub use projection::*;
#[cfg(feature = "duel")]
pub use review::*;
#[cfg(feature = "encoders")]
pub use runner::*;
