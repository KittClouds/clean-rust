use crate::{
    GradientBlockEconomics, HyperEpochEconomics, HyperOptimizerConfig, ParameterDeltaReceipt,
};
use compact_str::CompactString;
use phoenix_graph_research::{
    HyperRelationalMetricSlice, HyperRelationalRankingMetrics, HyperRelationalScoreCertificate,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const OPTIMIZATION_ENVELOPE_SCHEMA: &str = "phoenix-wd50k-grouped-pressure-envelope/v1";
pub const OPTIMIZATION_ENVELOPE_TRAINER: &str = "phoenix-fused-hyper-grouped-pressure/v1";
pub const OPTIMIZATION_ENVELOPE_SEED: u64 = 0x51a7_e001;
pub const OPTIMIZATION_ENVELOPE_CHECKPOINTS: [u32; 7] = [0, 1, 2, 4, 8, 16, 32];

#[derive(Clone, Debug, PartialEq)]
pub struct OptimizationEnvelopeRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub output_root: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OptimizationEnvelopePaths {
    pub manifest: PathBuf,
    pub envelope_id: CompactString,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum EnvelopeArm {
    Compgcn,
    QualifierGradientNull,
    ValueOnly,
    FullStare,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrainScoreReceipt {
    pub score_blake3: CompactString,
    pub binary_cross_entropy: f64,
    pub mean_positive_score: f64,
    pub mean_negative_score: f64,
    pub mean_positive_negative_margin: f64,
    pub correctly_ordered_pair_fraction: f64,
    pub examples: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ParameterBlockReceipt {
    pub name: CompactString,
    pub delta: ParameterDeltaReceipt,
    pub economics: GradientBlockEconomics,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StructuralValidationSlices {
    pub relation_frequency: Vec<HyperRelationalMetricSlice>,
    pub target_entity_degree: Vec<HyperRelationalMetricSlice>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RankArtifactReceipt {
    pub file: CompactString,
    pub blake3: CompactString,
    pub bytes: u64,
    pub queries: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PairedRankDeltaReceipt {
    pub left: EnvelopeArm,
    pub right: EnvelopeArm,
    pub wins: u64,
    pub losses: u64,
    pub ties: u64,
    pub mean_reciprocal_rank_delta: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CausalRankArtifactReceipt {
    pub file: CompactString,
    pub blake3: CompactString,
    pub bytes: u64,
    pub queries: u64,
    pub comparisons: Vec<PairedRankDeltaReceipt>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnvelopeArmCheckpoint {
    pub arm: EnvelopeArm,
    pub checkpoint_epoch: u32,
    pub model_id: CompactString,
    pub model_manifest_id: CompactString,
    pub model_manifest_file: CompactString,
    pub base_checkpoint_model_id: Option<CompactString>,
    pub qualifier_parameter_source_model_id: Option<CompactString>,
    pub routing_digest: Option<CompactString>,
    pub train: TrainScoreReceipt,
    pub validation: HyperRelationalScoreCertificate,
    pub structural_slices: StructuralValidationSlices,
    pub ranks: RankArtifactReceipt,
    pub parameter_blocks: Vec<ParameterBlockReceipt>,
    pub final_batch: Option<HyperEpochEconomics>,
    #[serde(default)]
    pub batch_pressure: Vec<HyperEpochEconomics>,
    pub pre_clip_gradient_norm: f64,
    pub clip_coefficient: f64,
    pub clip_activation_rate: f64,
    #[serde(default)]
    pub non_bias_clip_activation_rate: f64,
    #[serde(default)]
    pub decoder_bias_clip_activation_rate: f64,
    #[serde(default)]
    pub non_bias_update_recovery_vs_legacy_global: f64,
    pub optimizer_steps: u64,
    pub cold_restart_exact: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnvelopeCheckpoint {
    pub epoch: u32,
    pub arms: Vec<EnvelopeArmCheckpoint>,
    pub causal_rank_deltas: CausalRankArtifactReceipt,
    pub fixed_qualifier_feature_mrr_delta: f64,
    pub qualifier_conditioned_learning_mrr_delta: f64,
    pub total_qualifier_value_mrr_delta: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OptimizationEnvelopeManifest {
    pub schema_version: CompactString,
    pub envelope_id: CompactString,
    pub trainer_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub seed: u64,
    pub checkpoints: Vec<EnvelopeCheckpoint>,
    pub optimizer: HyperOptimizerConfig,
    pub optimizer_identity: CompactString,
    #[serde(default)]
    pub clip_partition_blake3: CompactString,
    #[serde(default)]
    pub clip_group_ordering: Vec<crate::HyperClipGroup>,
    #[serde(default)]
    pub clip_group_maximum_norms: Vec<f32>,
    #[serde(default)]
    pub decoder_weights_present: bool,
    pub initialization_blake3: CompactString,
    pub example_schedule_blake3: CompactString,
    pub training_examples: u64,
    pub test_partition_accessed: bool,
    pub validation_only: bool,
    pub cumulative_checkpoint_lineage: bool,
    pub exact_rank_encoding: CompactString,
    pub relation_frequency_authority: CompactString,
    pub entity_degree_authority: CompactString,
    pub independent_replay_required: bool,
}

pub(crate) fn empty_metrics() -> HyperRelationalRankingMetrics {
    HyperRelationalRankingMetrics {
        mean_reciprocal_rank: 0.0,
        hits_at_1: 0.0,
        hits_at_3: 0.0,
        hits_at_5: 0.0,
        hits_at_10: 0.0,
        queries: 0,
        candidates_scored: 0,
    }
}
