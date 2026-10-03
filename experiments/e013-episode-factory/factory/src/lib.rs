//! Construction, replay, audit, and sealing primitives for E013 local-commit episodes.
//!
//! This crate has no observer integration or model client. Family adapters create an
//! [`EpisodeDraft`]; the core validates it, replays every patch from an independent
//! checkout, and emits a public projection plus a separate private receipt.

mod audit;
mod canonical;
mod error;
mod hash;
mod materialize;
mod order;
mod package;
mod paths;
mod replay;
mod schema;

pub use audit::{audit_bank_disjointness, audit_episode_draft, BankAudit, DraftAudit};
pub use canonical::canonical_json;
pub use error::FactoryError;
pub use hash::{hash_bytes, hash_file, root_hash, FileDigest};
pub use materialize::{materialize_snapshot, verify_snapshot};
pub use order::candidate_order;
pub use package::{build_episode, verify_episode, BuildEpisodeOptions, EpisodeBuildResult};
pub use replay::{replay_candidates, CandidateReplay, PhaseOutcome, PhaseStatus};
pub use schema::*;

#[cfg(test)]
mod tests;
