//! Kammi Library v2 store.
//!
//! Physical representation only: identities and authority rules are exactly v1's.
//!
//! - Journals are append-only segments of frames that carry the unchanged canonical v1 event
//!   envelope plus its payload inline. Event IDs, `seq`/`prev` chains and payload IDs are the
//!   v1 values. A committed prefix is never shortened; only an incomplete (torn) tail of the
//!   active segment is moved to `recovery/` and cut. A complete frame that fails its checksum
//!   is corruption and refuses to open.
//! - Objects keep their raw-byte SHA-256 identity; small ones live in packs, large ones loose.
//! - Segment indexes, object logs and lookup tables are derived and rebuilt from the
//!   authoritative bytes when missing or inconsistent. Checkpoints are accelerators only.
//! - One OS-held lock per store root; the head is always the last committed journal frame.

mod checkpoint;
mod durable;
mod error;
pub mod fault;
mod follow;
mod frame;
mod idx;
mod journal;
mod keyindex;
mod lock;
mod objects;
mod store;

pub use checkpoint::{Checkpoint, Checkpoints, Position};
pub use error::{Result, StoreError};
pub use follow::{JournalFollower, ObjectReader};
pub use idx::IdxRecord;
pub use journal::{
    Journal, JournalOptions, JournalReport, NewEvent, StoredEvent, EVENT_FIELDS, EVENT_SCHEMA,
};
pub use objects::{ObjectOptions, ObjectReport, Objects};
pub use store::{Recovery, Store, StoreOptions, VerifyReport, STORE_SCHEMA};
