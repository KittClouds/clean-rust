//! Deterministic financial world for `NORTHSTAR_RL_SURFACE_V1`.
//!
//! The crate owns market/feature/episode tapes and all simulation semantics.
//! Python is intentionally only a protocol adapter.

pub mod account;
pub mod artifact;
pub mod batch;
pub mod contracts;
pub mod environment;
pub mod episode;
pub mod feature;
pub mod fixtures;
pub mod identity;
pub mod replay;
pub mod tape;

pub use account::*;
pub use artifact::*;
pub use batch::*;
pub use contracts::*;
pub use environment::*;
pub use episode::*;
pub use feature::*;
pub use fixtures::*;
pub use identity::*;
pub use replay::*;
pub use tape::*;

use thiserror::Error;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Error)]
pub enum Error {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid contract: {0}")]
    InvalidContract(String),
    #[error("invalid tape: {0}")]
    InvalidTape(String),
    #[error("environment state error: {0}")]
    Environment(String),
}
