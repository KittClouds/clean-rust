//! Immutable, leakage-aware research snapshots over authoritative Phoenix graph state.

mod artifact;
mod baselines;
#[cfg(feature = "graph-build")]
mod build;
mod evaluation;
mod evaluation_artifact;
mod evaluation_model;
mod external_dataset_artifact;
mod external_dataset_import;
mod external_dataset_model;
mod frozen_model_artifact;
mod frozen_model_model;
mod hyper_encoder;
mod hyper_encoder_artifact;
mod hyper_encoder_model;
mod hyper_relational_artifact;
mod hyper_relational_binary;
mod hyper_relational_build;
mod hyper_relational_eval;
mod hyper_relational_model;
mod link_prediction_artifact;
mod link_prediction_build;
mod link_prediction_canonical_eval;
mod link_prediction_eval;
mod link_prediction_model;
mod model;
mod model_selection;
mod model_selection_model;
mod ranking;
mod ranking_artifact;
mod ranking_model;
mod rgcn;
mod temporal_compgcn;
mod temporal_compgcn_artifact;
mod temporal_compgcn_model;
mod temporal_rgcn;
mod temporal_rgcn_artifact;
mod temporal_rgcn_candidate_simd;
mod temporal_rgcn_model;
mod tensor_artifact;
mod tensor_model;
mod tensorize;
mod tgb_pickle;
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
pub use external_dataset_artifact::{
    ExternalDatasetBundle, ExternalDatasetMapped, ExternalFactRecord, ExternalQualifierRecord,
};
pub use external_dataset_import::{import_tkgl_smallpedia, import_wd50k};
pub use external_dataset_model::*;
pub use frozen_model_artifact::{
    certify_model_scores, certify_model_seed_receipt, score_mlp16_tensors, FrozenModelBundle,
    FrozenModelMapped, ModelLeF32,
};
pub use frozen_model_model::*;
pub use hyper_encoder::*;
pub use hyper_encoder_artifact::*;
pub use hyper_encoder_model::*;
pub use hyper_relational_artifact::HyperRelationalTaskMapped;
pub use hyper_relational_build::build_canonical_hyper_relational_task;
pub use hyper_relational_eval::{
    create_hyper_relational_test_lock, evaluate_hyper_relational_validation_batched,
    evaluate_locked_hyper_relational_test_batched, DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
};
pub use hyper_relational_model::*;
pub use link_prediction_artifact::LinkPredictionTaskMapped;
pub use link_prediction_build::build_canonical_link_prediction_task;
pub use link_prediction_canonical_eval::{
    evaluate_link_prediction_validation_canonical_batched,
    evaluate_link_prediction_validation_canonical_batched_profiled,
    link_prediction_canonical_arena_bytes, CanonicalScoreMatrixMut,
    LINK_PREDICTION_SCORE_PREFIX_WORDS,
};
pub use link_prediction_eval::{
    create_link_prediction_test_lock, evaluate_link_prediction_validation,
    evaluate_link_prediction_validation_batched,
    evaluate_link_prediction_validation_batched_profiled, evaluate_locked_link_prediction_test,
    evaluate_locked_link_prediction_test_batched, link_prediction_hash_buffer_bytes,
    LinkPredictionEvaluationProfile, ProfiledLinkPredictionEvaluation,
    DEFAULT_LINK_PREDICTION_QUERY_BATCH, LINK_PREDICTION_SCORE_PREFIX_BYTES,
};
pub use link_prediction_model::*;
pub use model::*;
pub use model_selection::{
    finalize_frozen_model_selection, open_frozen_model_selection_ledger, select_frozen_models,
};
pub use model_selection_model::*;
pub use ranking::{evaluate_ranking_scores, run_structural_ranking_baselines};
pub use ranking_artifact::RankingEvaluationBundle;
pub use ranking_model::*;
pub use rgcn::*;
pub use temporal_compgcn::{encode_temporal_compgcn, encode_temporal_compgcn_weights};
pub use temporal_compgcn_artifact::{
    temporal_compgcn_model_identity, temporal_compgcn_weights_identity, write_temporal_compgcn,
    TemporalCompgcnMapped,
};
pub use temporal_compgcn_model::*;
pub use temporal_rgcn::*;
pub use temporal_rgcn_artifact::{
    temporal_rgcn_model_identity, write_temporal_rgcn, TemporalRgcnMapped,
};
pub use temporal_rgcn_model::*;
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

#[cfg(test)]
mod external_dataset_tests;

#[cfg(test)]
mod link_prediction_tests;

#[cfg(test)]
mod hyper_relational_tests;
