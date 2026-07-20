//! Production adapters and immutable persistence for asserted-graph discovery.
//!
//! This crate can resolve bounded lexical/vector seeds and publish discovery
//! candidates. It intentionally exposes no asserted graph mutation surface;
//! promotion remains an external, evidence-backed authority operation.

mod graph_proposal;
mod ledger;
mod path_receipt;
mod pipeline;
mod seeds;

pub use graph_proposal::{
    DiscoveryGraphProposalError, GraphProposalBatchPublication, HumanGraphProposalIdentification,
};
pub use ledger::{
    CandidateReviewDecision, CandidateReviewEvent, DiscoveryCandidateArtifact,
    DiscoveryCandidateLedger, DiscoveryQueryRunArtifact, LedgerPublication,
};
pub use path_receipt::{DiscoveryPathAuthority, DiscoveryPathExecution, DiscoveryPathReceipt};
pub use pipeline::{
    execute_and_publish, execute_and_publish_with_cancellation, PublishedDiscoveryQuery,
};
pub use seeds::{ProductionSeedAdapter, ProductionSeedLimits};

#[cfg(test)]
mod tests;
