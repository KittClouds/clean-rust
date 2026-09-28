//! Offline proposal and continuation-value target construction for R1 Stage 1.
//!
//! This crate has no model runtime and performs no fitting. The teacher and
//! rollout labels are training-only artifacts built from private exact worlds.

mod rollout;
mod teacher;

pub mod simulator_v03;

pub use rollout::{
    build_reachability_dataset, FrozenProposal, IndividualState, LabelDataset,
    ProposalActionProbability, ProposalContext, PublicFeatures, ReachabilityLabel, RolloutError,
    RolloutLabel,
};
pub use teacher::{
    build_teacher_target, ExactSolutionClasses, SolutionClass, TeacherEditTarget, TeacherError,
    TeacherOutcome, TeacherTarget,
};

#[cfg(test)]
mod tests;
