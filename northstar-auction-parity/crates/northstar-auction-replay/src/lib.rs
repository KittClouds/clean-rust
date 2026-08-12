//! Independent reconstruction of the sealed Phase 10.5 analytical interface.

mod grammar;
mod interface;

pub use grammar::{
    GoldenGrammarReport, GrammarDirection, SemanticLedger, run_golden_semantics,
    verify_golden_grammar,
};
pub use interface::{
    InterfaceParityReport, ResearchInterfaceVerifier, TargetCount, ViewCardinalities,
};
