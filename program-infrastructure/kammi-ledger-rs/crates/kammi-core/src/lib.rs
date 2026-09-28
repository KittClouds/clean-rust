//! Kammi Library domain logic, ported from the Python `ledgerd` daemon.
//!
//! [`Ledger`] owns a [`kammi_store::Store`], replays both journals into [`state::State`] and
//! [`memory::Memory`], and exposes every operation of the Python service with the same rules,
//! the same payload shapes and the same `ValueError` messages. Replay never reads a clock;
//! commands read the injected [`time::Clock`].

pub mod embed;
pub mod error;
pub mod json;
pub mod ledger;
pub mod memory;
pub mod ops_access;
pub mod ops_custody;
pub mod ops_local;
pub mod ops_remote;
pub mod ops_vault;
pub mod rules;
pub mod safe;
pub mod state;
pub mod time;
pub mod verify_cache;

pub use embed::{Embedder, Embeddings, Input, ModelIdentity, Role};
pub use error::{LedgerError, Result};
#[doc(hidden)]
pub use kammi_jcs as __jcs;
pub use ledger::{FlightIdentity, Ledger, LedgerOptions, Prior};
pub use memory::{HashingEmbedder, MemoryIndex};
pub use time::{Clock, ManualClock, SystemClock, Timestamp};
