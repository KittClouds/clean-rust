//! Immutable, leakage-aware research snapshots over authoritative Phoenix graph state.

mod artifact;
mod baselines;
#[cfg(feature = "graph-build")]
mod build;
mod evaluation;
mod evaluation_artifact;
mod evaluation_model;
mod frozen_model_artifact;
mod frozen_model_model;
mod model;
mod model_selection;
mod model_selection_model;
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
#[cfg(feature = "graph-build")]
pub use build::{freeze_graph_research_snapshot, FrozenGraphResearchInput};
pub use evaluation::{certify_evaluation_protocol, evaluate_binary_scores};
pub use evaluation_artifact::ResearchEvaluationBundle;
pub use evaluation_model::*;
pub use frozen_model_artifact::{
    certify_model_scores, certify_model_seed_receipt, score_mlp16_tensors, FrozenModelBundle,
    FrozenModelMapped, ModelLeF32,
};
pub use frozen_model_model::*;
pub use model::*;
pub use model_selection::{
    finalize_frozen_model_selection, open_frozen_model_selection_ledger, select_frozen_models,
};
pub use model_selection_model::*;
pub use ranking::{evaluate_ranking_scores, run_structural_ranking_baselines};
pub use ranking_artifact::RankingEvaluationBundle;
pub use ranking_model::*;
pub use tensor_artifact::{FrozenTensorBundle, FrozenTensorMapped};
pub use tensor_model::*;
pub use tensorize::tensorize_frozen_graph;
pub use topology_artifact::{TrainTopologyFeatureBundle, TrainTopologyFeatureMapped};
pub use topology_derive::derive_train_topology_features;
pub use topology_model::*;

#[cfg(all(test, feature = "graph-build"))]
mod tests;

#[cfg(all(test, feature = "graph-build"))]
mod topology_tests;

#[cfg(all(test, feature = "graph-build"))]
mod ranking_tests;

#[cfg(test)]
mod frozen_model_tests;

#[cfg(test)]
mod model_selection_tests;
