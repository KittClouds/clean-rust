use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const GRADIENT_PRESSURE_AUDIT_SCHEMA: &str = "phoenix-real-batch-gradient-pressure-audit/v1";
pub const GRADIENT_PRESSURE_SEED: u64 = 0x51a7_e001;

#[derive(Clone, Debug, PartialEq)]
pub struct GradientPressureAuditRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub checkpoint_manifest: PathBuf,
    pub output_root: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GradientPressureAuditPaths {
    pub receipt: PathBuf,
    pub audit_id: CompactString,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum NegativePressureKind {
    FrozenRealBatch,
    PrimaryTarget,
    QualifierValue,
    QualifierRole,
    Mixed,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BiasRoutingProbe {
    Normal,
    Frozen,
    ExcludedFromGlobalNorm,
    SeparateClipGroup,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PressureDecision {
    ClippingDominant,
    ObjectiveDominant,
    CancellationDominant,
    ClippingAndObjective,
    HealthyQualifierPressure,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GradientPressureBlock {
    pub name: CompactString,
    pub raw_gradient_l2: f64,
    pub global_norm_share: f64,
    pub post_clip_gradient_l2: f64,
    pub clip_coefficient: f64,
    pub update_l2: f64,
    pub update_to_weight: f64,
    pub changed_parameter_bits: u64,
    pub changed_parameter_bits_measured: bool,
    pub parameters: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BiasProbeReceipt {
    pub probe: BiasRoutingProbe,
    pub global_norm: f64,
    pub non_bias_clip_coefficient: f64,
    pub bias_clip_coefficient: f64,
    pub blocks: Vec<GradientPressureBlock>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CancellationBlockReceipt {
    pub name: CompactString,
    pub aggregate_gradient_l2: f64,
    pub sum_individual_gradient_l2: f64,
    pub cancellation_ratio: f64,
    pub sign_agreement: f64,
    pub nonzero_sign_comparisons: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CancellationReceipt {
    pub stratum: CompactString,
    pub examples: u64,
    pub schedule_blake3: CompactString,
    pub split_half_cosine_similarity: f64,
    pub blocks: Vec<CancellationBlockReceipt>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NegativePressureReceipt {
    pub schedule_name: CompactString,
    pub kind: NegativePressureKind,
    pub positive_negative_pairs: u64,
    pub schedule_blake3: CompactString,
    pub optimizer_identity: CompactString,
    pub raw_global_gradient_l2: f64,
    pub global_clip_coefficient: f64,
    pub decoder_bias_norm_share: f64,
    pub qualifier_projection_norm_share: f64,
    pub qualifier_to_decoder_gradient_ratio: f64,
    pub qualifier_value_embedding_raw_l2: f64,
    pub qualifier_role_embedding_raw_l2: f64,
    pub blocks: Vec<GradientPressureBlock>,
    pub bias_probes: Vec<BiasProbeReceipt>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GradientPressureAuditReceipt {
    pub schema_version: CompactString,
    pub audit_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub seed: u64,
    pub optimizer_identity: CompactString,
    pub initialization_blake3: CompactString,
    pub checkpoint_model_id: CompactString,
    pub checkpoint_manifest_id: CompactString,
    pub checkpoint_weights_blake3: CompactString,
    pub sample_pairs_per_schedule: u32,
    pub decoder_weights_present: bool,
    pub primary_graph_mutated: bool,
    pub corruptions_filtered_against_train: bool,
    pub semantic_row_gradient_estimator: CompactString,
    pub test_partition_accessed: bool,
    pub negative_pressure: Vec<NegativePressureReceipt>,
    pub cancellation: Vec<CancellationReceipt>,
    pub decision: PressureDecision,
    pub decision_evidence_blake3: CompactString,
    pub next_cut: CompactString,
    pub stop_condition: CompactString,
    pub external_calibration: CompactString,
    pub phoenix_native_value: CompactString,
    pub exit_criterion: CompactString,
}
