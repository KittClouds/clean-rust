//! Hookable Stage 1 search dynamics over the frozen Stage 0 trace contract.
//!
//! Stage 0 crates are path dependencies and are never patched here. The
//! runtime receives only InferenceTask plus declared frozen semantic arrays;
//! exact validator labels remain post-hoc in r1_search::annotate_posthoc.

mod feature_io;
mod features;
mod inference;
mod inference_v02;
mod policy;
mod policy_adapter;
mod policy_v02;
mod qterminal_delta_policy;
mod qterminal_delta_v05;
mod replay;
mod run_config;
mod scheduler;
mod terminal;
mod trace_io;
mod trace_types;

pub use feature_io::{FeatureLoadError, MappedSensorExtraction};
pub use features::{FeatureError, SemanticFeatures};
pub use inference::{
    FrozenProposalValueV01, InferenceError, PROPOSAL_V01_SHA256, V_REACH_V01_SHA256,
};
pub use inference_v02::{
    FrozenProposalValueV02, InferenceV02Error, ProposalMixV03, ProposalScoresV02,
    PROPOSAL_V02_SHA256, V_REACH_V02_64_SHA256, V_REACH_V03_SCALED_H_SHA256,
    V_REACH_V05_STRESS_SHA256, V_REACH_V06_STRESS_SHA256,
};
pub use policy::{
    DeterministicRng, Edit, PolicyCosts, PolicyError, PolicyLatentUpdate, PolicyScores,
    PolicyValue, ProposalStrategy, SearchPolicy, SelectorInput, TransitionInput, ValueInput,
};
pub use policy_adapter::{FrozenProposalPolicyV01, TerminalScorer};
pub use policy_v02::{FrozenProposalPolicyV02, ProposalScoreAuditV03};
pub use qterminal_delta_policy::QDeltaProposalPolicy;
pub use qterminal_delta_v05::{
    FrozenQTerminalDeltaV05, QDeltaBatch, QDeltaError, QTERMINAL_V05_CHECKPOINT_SHA256,
};
pub use r1_search::{
    Arm, InitialParticle, OperationCosts, OperationLedger, PrefixBudget, PrefixMetrics, RunConfig,
    RunTrace, TraceEvent,
};
pub use replay::{verify_replay, ReplayReport};
pub use run_config::{MergeMode, SearchAllocationPolicy, Stage1RunConfig, ValueRefreshPolicy};
pub use scheduler::{run, SearchError};
pub use terminal::{
    CalibratedIdentityTerminalV06, ExpectedActionDeltaBatch, IdentityCompositionV03,
    QTerminalCalibrationV06, TaskPooledIdentityTerminalV07, TerminalError, TerminalPrediction,
    IDENTITY_LINEAR_V03_BINARY_SHA256, IDENTITY_LINEAR_V03_METADATA_SHA256,
    Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256, Q_TERMINAL_V06_CALIBRATION_METADATA_SHA256,
    Q_TERMINAL_V06_REFERENCE_SHA256, Q_TERMINAL_V07_TASK_POOLED_WEIGHT,
};
pub use trace_io::write_stage1_trace_v2;
pub use trace_types::{
    MergeParticleSnapshot, Stage1Run, Stage1RunManifest, Stage1TraceEventDiagnostic,
};
