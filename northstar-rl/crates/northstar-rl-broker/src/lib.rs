//! Read-only broker observation and deterministic wind-tunnel replay.
//!
//! This crate deliberately has no order-placement API. Live bytes establish capture
//! authority; sealed normalized bytes establish offline replay authority.

pub mod capture;
pub mod contracts;
pub mod fixture;
pub mod live;
pub mod observer;
pub mod qualify;
pub mod wind_tunnel;

pub use capture::*;
pub use contracts::*;
pub use fixture::*;
pub use live::*;
pub use observer::*;
pub use qualify::*;
pub use wind_tunnel::*;

use thiserror::Error;

use northstar_rl_core::Digest;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Error)]
pub enum Error {
    #[error(transparent)]
    Core(#[from] northstar_rl_core::Error),
    #[error("broker contract error: {0}")]
    Contract(String),
    #[error("broker transport error: {0}")]
    Transport(String),
    #[error("credential error: {0}")]
    Credential(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

/// Source-bound identities for broker semantics included in an RL world.
pub fn broker_implementation_hashes() -> Vec<Digest> {
    [
        (
            b"capture".as_slice(),
            include_bytes!("capture.rs").as_slice(),
        ),
        (
            b"contracts".as_slice(),
            include_bytes!("contracts.rs").as_slice(),
        ),
        (
            b"fixture".as_slice(),
            include_bytes!("fixture.rs").as_slice(),
        ),
        (
            b"observer".as_slice(),
            include_bytes!("observer.rs").as_slice(),
        ),
        (
            b"wind_tunnel".as_slice(),
            include_bytes!("wind_tunnel.rs").as_slice(),
        ),
    ]
    .into_iter()
    .map(|(name, source)| Digest::hash_parts(b"northstar-broker-source-v1", [name, source]))
    .collect()
}
