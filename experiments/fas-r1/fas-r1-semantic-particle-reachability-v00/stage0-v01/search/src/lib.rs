//! Model-free R1 search dynamics and replayable transition traces.
//!
//! The online runner intentionally has no validator or solution-set input.  A
//! closed `RunTrace` can be joined with a separate post-hoc sidecar only after
//! `run` has returned.

mod policy;
mod posthoc;
mod replay;
mod scheduler;
mod types;

pub use posthoc::{annotate_posthoc, prefix_metrics};
pub use replay::{read_jsonl, verify_replay, write_jsonl, ReplayReport, TraceIoError};
pub use scheduler::{run, SearchError};
pub use types::{
    Arm, InitialParticle, OperationCosts, OperationLedger, PosthocEventLabel, PosthocSidecar,
    PrefixBudget, PrefixBudgetRecord, PrefixMetrics, ProposalMode, ResamplingRecord, RunConfig,
    RunTrace, SelectorMode, TraceEvent, TraceHeader,
};
