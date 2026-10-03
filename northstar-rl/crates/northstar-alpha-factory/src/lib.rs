//! Financially directed strategy factory with a hard Northstar-science firewall.
//!
//! Qualification fixtures prove machinery only. They can never be admitted as
//! alpha evidence by the authority verifier.

pub mod authority;
pub mod contracts;
pub mod engine;
pub mod fixture;
pub mod partition;
pub mod qualify;

pub use authority::*;
pub use contracts::*;
pub use engine::*;
pub use fixture::*;
pub use partition::*;
pub use qualify::*;

use thiserror::Error;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Error)]
pub enum Error {
    #[error(transparent)]
    Core(#[from] northstar_rl_core::Error),
    #[error("alpha authority violation: {0}")]
    Authority(String),
    #[error("alpha contract violation: {0}")]
    Contract(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

pub fn implementation_hashes() -> Vec<northstar_rl_core::Digest> {
    [
        (b"authority".as_slice(), include_bytes!("authority.rs").as_slice()),
        (b"contracts".as_slice(), include_bytes!("contracts.rs").as_slice()),
        (b"engine".as_slice(), include_bytes!("engine.rs").as_slice()),
        (b"partition".as_slice(), include_bytes!("partition.rs").as_slice()),
    ]
    .into_iter()
    .map(|(name, source)| {
        northstar_rl_core::Digest::hash_parts(b"northstar-alpha-source-v1", [name, source])
    })
    .collect()
}
