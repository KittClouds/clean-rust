//! Immutable, leakage-aware research snapshots over authoritative Phoenix graph state.

mod artifact;
mod baselines;
mod build;
mod evaluation;
mod evaluation_artifact;
mod evaluation_model;
mod model;
mod ranking;
mod ranking_artifact;
mod ranking_model;
mod tensor_artifact;
mod tensor_model;
mod tensorize;
mod topology_artifact;
mod topology_derive;
mod topology_model;

pub use artifact::{FrozenGraphResearchBundle, FrozenGraphResearchMapped};
pub use baselines::{run_baseline_ladder, run_baseline_ladder_for_protocol};
pub use build::{freeze_graph_research_snapshot, FrozenGraphResearchInput};
pub use evaluation::{certify_evaluation_protocol, evaluate_binary_scores};
pub use evaluation_artifact::ResearchEvaluationBundle;
pub use evaluation_model::*;
pub use model::*;
pub use ranking::{evaluate_ranking_scores, run_structural_ranking_baselines};
pub use ranking_artifact::RankingEvaluationBundle;
pub use ranking_model::*;
pub use tensor_artifact::{FrozenTensorBundle, FrozenTensorMapped};
pub use tensor_model::*;
pub use tensorize::tensorize_frozen_graph;
pub use topology_artifact::{TrainTopologyFeatureBundle, TrainTopologyFeatureMapped};
pub use topology_derive::derive_train_topology_features;
pub use topology_model::*;

#[cfg(test)]
mod tests;

#[cfg(test)]
mod topology_tests;

#[cfg(test)]
mod ranking_tests;
