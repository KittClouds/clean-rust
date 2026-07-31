//! Isolated positional BM25F/QPS V2 experiment.
//!
//! This crate has no production registration. It exists to compare a bounded,
//! query-aware positional model with Phoenix's pinned BM25 implementation.

mod builder;
mod fixture;
mod index;
mod score;
mod selection;
mod tokenize;
mod types;

pub use builder::QpsBuilder;
pub use fixture::{
    benchmark_corpus, fixed_match_corpus, judged_fixture, representative_fixture, FixtureDocument,
    JudgedQuery,
};
pub use index::{IndexStats, QpsIndex, SearchScratch};
pub use types::{
    CandidateSelection, DocumentId, DocumentInput, Expansion, FieldConfig, QpsConfig, QpsError,
    QueryGroup, SearchHit, SearchReceipt,
};
