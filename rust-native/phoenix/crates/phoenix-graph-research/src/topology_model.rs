use crate::{ResearchEvaluationError, ResearchSplit, PROPOSAL_FEATURE_DIM};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const TRAIN_TOPOLOGY_FEATURE_SCHEMA: &str = "phoenix-train-topology-features/v1";
pub const TRAIN_TOPOLOGY_BINARY_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrainTopologyFeaturePolicy {
    pub incidence_negatives_per_positive: u8,
}

impl TrainTopologyFeaturePolicy {
    pub fn validate(self) -> Result<(), ResearchEvaluationError> {
        if !(1..=32).contains(&self.incidence_negatives_per_positive) {
            return Err(ResearchEvaluationError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DerivedFeatureCertificate {
    pub task_id: CompactString,
    pub feature_schema_id: CompactString,
    pub column: u16,
    pub name: CompactString,
    pub dtype: CompactString,
    pub transform: CompactString,
    pub fit_split: ResearchSplit,
    pub fit_through_ms: i64,
    pub leave_one_positive_out: bool,
    pub label_free: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DerivedFeatureRow {
    pub positive_index: u32,
    pub candidate: u32,
    pub split: ResearchSplit,
    pub label: bool,
    pub features: [f32; PROPOSAL_FEATURE_DIM],
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrainTopologyAudit {
    pub fit_edges: u64,
    pub fit_incidences: u64,
    pub link_examples: u64,
    pub incidence_examples: u64,
    pub latest_fit_edge_ms: Option<i64>,
    pub topology_blake3: CompactString,
    pub train_only: bool,
    pub asserted_edges_only: bool,
    pub resolved_incidences_only: bool,
    pub leave_one_positive_out: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrainTopologyFeatureSnapshot {
    pub schema_version: CompactString,
    pub derivation_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_tensor_id: CompactString,
    pub evaluation_protocol_id: CompactString,
    pub policy: TrainTopologyFeaturePolicy,
    pub audit: TrainTopologyAudit,
    pub feature_certificates: Vec<DerivedFeatureCertificate>,
    pub link_rows: Vec<DerivedFeatureRow>,
    pub incidence_rows: Vec<DerivedFeatureRow>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrainTopologyFeatureManifest {
    pub schema_version: CompactString,
    pub derivation_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_tensor_id: CompactString,
    pub evaluation_protocol_id: CompactString,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub link_rows: u64,
    pub incidence_rows: u64,
    pub audit: TrainTopologyAudit,
    pub feature_certificates: Vec<DerivedFeatureCertificate>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrainTopologyFeaturePaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
}
