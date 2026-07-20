//! Production adapters and immutable persistence for asserted-graph discovery.
//!
//! This crate can resolve bounded lexical/vector seeds and publish discovery
//! candidates. It intentionally exposes no asserted graph mutation surface;
//! promotion remains an external, evidence-backed authority operation.

mod ledger;
mod pipeline;
mod seeds;

pub use ledger::{
    CandidateReviewDecision, CandidateReviewEvent, DiscoveryCandidateArtifact,
    DiscoveryCandidateLedger, DiscoveryQueryRunArtifact, LedgerPublication,
};
pub use pipeline::{execute_and_publish, PublishedDiscoveryQuery};
pub use seeds::{ProductionSeedAdapter, ProductionSeedLimits};

#[cfg(test)]
mod tests;
