//! Durable, policy-bound deep research state for the Phoenix AI harness.
//!
//! The model may propose actions, but this crate owns phase transitions,
//! budgets, source identity, gap convergence, and citation verification.

mod engine;
mod process_guard;
mod provider;
mod renderer;
mod types;
mod verify;
mod web;

pub use engine::{ResearchError, ResearchSession};
pub use provider::{SearchProviderRegistry, WebSearchProvider};
pub use types::{
    CitationInput, CitationRecord, ClaimInput, ClaimRecord, GapInput, GapRecord, QueryRecord,
    ResearchBudget, ResearchPhase, ResearchReceipt, ResearchUsage, SourceRecord, VerificationIssue,
    VerificationReport,
};
pub use verify::verify_session;
pub use web::{
    NativeWebClient, WebFetch, WebFetchMode, WebFetchReceipt, WebFetcher, WebSearchHit,
    WebSearchResults,
};

#[cfg(test)]
mod tests;
