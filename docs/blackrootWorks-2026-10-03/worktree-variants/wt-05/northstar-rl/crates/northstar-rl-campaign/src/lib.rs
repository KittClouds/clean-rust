//! Inert experiment control plane for Northstar strategy research.
//!
//! This crate specifies campaigns and evaluation, but contains no learner executor.

pub mod contracts;
pub mod evaluate;
pub mod fixture;
pub mod partition;
pub mod qualify;
pub mod transform;

pub use contracts::*;
pub use evaluate::*;
pub use fixture::*;
pub use partition::*;
pub use qualify::*;
pub use transform::*;

use thiserror::Error;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Error)]
pub enum Error {
    #[error(transparent)]
    Core(#[from] northstar_rl_core::Error),
    #[error("campaign contract error: {0}")]
    Contract(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

pub fn campaign_implementation_hashes() -> Vec<northstar_rl_core::Digest> {
    [
        (
            b"contracts".as_slice(),
            include_bytes!("contracts.rs").as_slice(),
        ),
        (
            b"evaluate".as_slice(),
            include_bytes!("evaluate.rs").as_slice(),
        ),
        (
            b"partition".as_slice(),
            include_bytes!("partition.rs").as_slice(),
        ),
        (
            b"transform".as_slice(),
            include_bytes!("transform.rs").as_slice(),
        ),
    ]
    .into_iter()
    .map(|(name, source)| {
        northstar_rl_core::Digest::hash_parts(b"northstar-campaign-source-v1", [name, source])
    })
    .collect()
}
