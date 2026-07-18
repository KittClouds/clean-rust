//! Immutable production inference artifacts for revision-impact model overlays.
//!
//! This crate can read authoritative Phoenix projections, but it has no graph
//! persistence dependency and exposes no mutation API.

pub mod bundle;
#[cfg(feature = "duel")]
pub mod cached_reasoner;
#[cfg(feature = "duel")]
pub mod duel;
#[cfg(feature = "duel")]
pub mod duel_runtime;
pub mod error;
#[cfg(feature = "duel")]
pub mod focused_metrics;
pub mod matrix;
pub mod metrics;
pub mod projection;
#[cfg(feature = "duel")]
pub mod review;
#[cfg(feature = "encoders")]
pub mod runner;

pub use bundle::*;
#[cfg(feature = "duel")]
pub use cached_reasoner::*;
#[cfg(feature = "duel")]
pub use duel::*;
#[cfg(feature = "duel")]
pub use duel_runtime::*;
pub use error::*;
#[cfg(feature = "duel")]
pub use focused_metrics::*;
pub use matrix::*;
pub use metrics::*;
pub use projection::*;
#[cfg(feature = "duel")]
pub use review::*;
#[cfg(feature = "encoders")]
pub use runner::*;
