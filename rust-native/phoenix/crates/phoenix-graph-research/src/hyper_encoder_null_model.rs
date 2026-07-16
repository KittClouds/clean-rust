use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const QUALIFIER_NULL_COMPOSITION_SCHEMA: &str =
    "phoenix-role-scoped-qualifier-null-composition/v1";
pub const QUALIFIER_NULL_EVALUATION_SURFACE: &str = "phoenix-stare-evaluation-surface/v1";
pub const QUALIFIER_NULL_ROUTING_POLICY: &str = "phoenix-role-scoped-qualifier-routing/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperParameterClass {
    EntityEmbedding,
    RelationEmbedding,
    QualifierProjection,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperSemanticRole {
    PrimaryEntity,
    PrimaryRelation,
    QualifierValue,
    QualifierRole,
    QualifierProjection,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperParameterSource {
    TrainedBackbone,
    CheckpointZero,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QualifierNullCompositionManifest {
    pub schema_version: CompactString,
    pub composition_id: CompactString,
    pub trained_backbone_model_id: CompactString,
    pub trained_backbone_manifest_id: CompactString,
    pub trained_backbone_manifest_file: CompactString,
    pub checkpoint_zero_model_id: CompactString,
    pub checkpoint_zero_manifest_id: CompactString,
    pub checkpoint_zero_manifest_file: CompactString,
    pub evaluation_surface_id: CompactString,
    pub parameter_routing_policy_id: CompactString,
    pub optimizer_identity: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_identity: CompactString,
    pub task_binary_blake3: CompactString,
    pub checkpoint_epoch: u32,
    pub candidate_universe: u32,
    pub directed_relation_count: u32,
    pub redundant_weight_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualifierNullCompositionPaths {
    pub manifest: PathBuf,
    pub composition_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QualifierNullRoutingReceipt {
    pub routing_digest: CompactString,
    pub trained_backbone_model_id: CompactString,
    pub checkpoint_zero_model_id: CompactString,
    pub primary_entity_reads: u64,
    pub primary_relation_reads: u64,
    pub qualifier_value_reads: u64,
    pub qualifier_role_reads: u64,
    pub qualifier_projection_reads: u64,
    pub same_id_dual_role_entities: u64,
    pub same_id_dual_role_relations: u64,
}
