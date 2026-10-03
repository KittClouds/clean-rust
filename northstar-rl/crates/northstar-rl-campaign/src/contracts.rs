use northstar_rl_core::Digest;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

pub const PARTITION_TAPE_V1: &str = "PARTITION_TAPE_V1";
pub const TRANSFORM_STATE_V1: &str = "TRANSFORM_STATE_V1";
pub const LEARNER_SPEC_V1: &str = "LEARNER_SPEC_V1";
pub const EXPERIMENT_SPEC_V1: &str = "EXPERIMENT_SPEC_V1";
pub const EVALUATION_SPEC_V1: &str = "EVALUATION_SPEC_V1";
pub const POLICY_ARTIFACT_V1: &str = "POLICY_ARTIFACT_V1";
pub const CAMPAIGN_SPEC_V1: &str = "CAMPAIGN_SPEC_V1";
pub const CAMPAIGN_RUN_RECEIPT_V1: &str = "CAMPAIGN_RUN_RECEIPT_V1";

#[derive(
    Clone, Copy, Debug, Eq, Hash, JsonSchema, Ord, PartialEq, PartialOrd, Serialize, Deserialize,
)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PartitionRole {
    Train,
    Development,
    Evaluation,
    ExcludedEmbargo,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EpisodePartitionInput {
    pub episode_id: Digest,
    pub instrument_id: u32,
    pub group_id: String,
    pub start_time_ns: i64,
    pub end_time_ns: i64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PartitionAssignment {
    pub episode_id: Digest,
    pub group_id: String,
    pub chronological_ordinal: u64,
    pub role: PartitionRole,
    pub reason_code: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PartitionTape {
    pub schema_version: String,
    pub partition_tape_id: Digest,
    pub source_episode_tape_id: Digest,
    pub strategy: String,
    pub group_key: String,
    pub chronology_key: String,
    pub embargo_ns: i64,
    pub assignments: Vec<PartitionAssignment>,
    pub episode_population_hash: Digest,
    pub sealed: bool,
    pub content_hash: Digest,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TransformMethod {
    Identity,
    StandardScore,
    RobustMedianIqr,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct FeatureTransformState {
    pub feature_id: String,
    pub method: TransformMethod,
    pub center: f64,
    pub scale: f64,
    pub clip_low: Option<f64>,
    pub clip_high: Option<f64>,
    pub fitted_sample_count: u64,
    pub missingness_rule: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct TransformState {
    pub schema_version: String,
    pub transform_state_id: Digest,
    pub source_feature_tape_id: Digest,
    pub partition_tape_id: Digest,
    pub fit_role: PartitionRole,
    pub fitted_episode_set_hash: Digest,
    pub ordered_features: Vec<FeatureTransformState>,
    pub numeric_contract: String,
    pub implementation_hash: Digest,
    pub content_hash: Digest,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LearnerAlgorithm {
    FutureSb3Ppo,
    FutureSb3Sac,
    ExternalExecutor,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PolicyArchitecture {
    pub policy_class: String,
    pub hidden_layers: Vec<u32>,
    pub activation: String,
    pub shared_backbone: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct LearnerSpec {
    pub schema_version: String,
    pub learner_spec_id: Digest,
    pub algorithm: LearnerAlgorithm,
    pub policy_architecture: PolicyArchitecture,
    pub optimizer: String,
    pub learning_rate: f64,
    pub rollout_length: u32,
    pub batch_size: u32,
    pub gamma: f64,
    pub gae_lambda: f64,
    pub entropy_coefficient: f64,
    pub value_coefficient: f64,
    pub max_gradient_norm: f64,
    pub seed: u64,
    pub executor_name: String,
    pub executor_version: String,
    pub implementation_identity: Digest,
    pub execution_permission: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExperimentSpec {
    pub schema_version: String,
    pub experiment_id: Digest,
    pub environment_id: Digest,
    pub feature_tape_id: Digest,
    pub observation_spec_id: Digest,
    pub partition_tape_id: Digest,
    pub transform_state_id: Digest,
    pub learner_spec_id: Digest,
    pub evaluation_spec_id: Digest,
    pub root_seed: u64,
    pub immutable_input_hashes: Vec<Digest>,
    pub implementation_hashes: Vec<Digest>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct StressVariant {
    pub stress_id: String,
    pub execution_calibration_id: Option<Digest>,
    pub parameter_overrides: Vec<(String, String)>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EvaluationMetricRule {
    pub metric_id: String,
    pub direction: String,
    pub aggregation: String,
    pub missingness: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EvaluationSpec {
    pub schema_version: String,
    pub evaluation_spec_id: Digest,
    pub partition_tape_id: Digest,
    pub evaluation_episode_ids: Vec<Digest>,
    pub deterministic_policy_inference: bool,
    pub policy_selection_uses_evaluation: bool,
    pub metrics: Vec<EvaluationMetricRule>,
    pub stress_variants: Vec<StressVariant>,
    pub aggregation_order: Vec<String>,
    pub implementation_hash: Digest,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PolicyMaterializationState {
    ContractOnlyPreLearner,
    MaterializedWeights,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct InferenceSignature {
    pub input_dtype: String,
    pub input_shape: Vec<u32>,
    pub output_dtype: String,
    pub output_shape: Vec<u32>,
    pub deterministic: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PolicyArtifact {
    pub schema_version: String,
    pub policy_artifact_id: Digest,
    pub materialization_state: PolicyMaterializationState,
    pub originating_experiment_id: Digest,
    pub weights_hash: Option<Digest>,
    pub observation_dictionary_hash: Digest,
    pub action_spec_id: Digest,
    pub transform_state_id: Digest,
    pub environment_id: Digest,
    pub executor_name: String,
    pub executor_version: String,
    pub inference_signature: InferenceSignature,
    pub onnx_export_identity: Option<Digest>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignSpec {
    pub schema_version: String,
    pub campaign_id: Digest,
    pub experiment_id: Digest,
    pub partition_tape_id: Digest,
    pub run_seeds: Vec<u64>,
    pub run_budget_steps: u64,
    pub variance_axes: Vec<String>,
    pub state: String,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CampaignRunStatus {
    Planned,
    Executing,
    Completed,
    Failed,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignRunReceipt {
    pub schema_version: String,
    pub run_id: Digest,
    pub campaign_id: Digest,
    pub experiment_id: Digest,
    pub seed: u64,
    pub status: CampaignRunStatus,
    pub learner_steps_executed: u64,
    pub checkpoint_hashes: Vec<Digest>,
    pub policy_artifact_id: Option<Digest>,
    pub reason_code: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignReceipt {
    pub schema_version: String,
    pub campaign_id: Digest,
    pub run_receipt_ids: Vec<Digest>,
    pub learner_execution: String,
    pub receipt_id: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EvaluationAggregate {
    pub metric_id: String,
    pub value: f64,
    pub episode_count: u64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EvaluationReceipt {
    pub schema_version: String,
    pub evaluation_spec_id: Digest,
    pub subject_class: String,
    pub subject_id: Digest,
    pub episode_ids: Vec<Digest>,
    pub aggregates: Vec<EvaluationAggregate>,
    pub deterministic_rebuild_hash: Digest,
    pub receipt_id: Digest,
}
