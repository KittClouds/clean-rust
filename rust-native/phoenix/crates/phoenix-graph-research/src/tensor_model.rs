use crate::{FrozenGraphResearchError, ResearchAuthority, ResearchProposalLabel, ResearchSplit};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const FROZEN_TENSOR_SCHEMA: &str = "phoenix-frozen-tensorization/v1";
pub const FROZEN_TENSOR_BINARY_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TensorizationPolicy {
    pub negatives_per_asserted_edge: u8,
}

impl TensorizationPolicy {
    pub fn validate(self) -> Result<(), FrozenGraphResearchError> {
        if !(1..=32).contains(&self.negatives_per_asserted_edge) {
            return Err(FrozenGraphResearchError::InvalidTensorPolicy(
                "negatives_per_asserted_edge must be in 1..=32",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FeatureColumnCertificate {
    pub feature_schema_id: CompactString,
    pub column: u16,
    pub name: CompactString,
    pub dtype: CompactString,
    pub normalization: CompactString,
    pub available_at: CompactString,
    pub label_free: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TypedNegativeSample {
    pub positive_edge: u32,
    pub source: u32,
    pub target: u32,
    pub relation_type: u32,
    pub split: ResearchSplit,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenTensorSnapshot {
    pub tensor_id: CompactString,
    pub source_dataset_id: CompactString,
    pub policy: TensorizationPolicy,
    pub node_ids: Vec<CompactString>,
    pub node_type_vocabulary: Vec<CompactString>,
    pub relation_vocabulary: Vec<CompactString>,
    pub role_vocabulary: Vec<CompactString>,
    pub feature_schema_vocabulary: Vec<CompactString>,
    pub node_type_ids: Vec<u32>,
    pub node_authority: Vec<ResearchAuthority>,
    pub node_splits: Vec<ResearchSplit>,
    pub node_available_at_ms: Vec<i64>,
    pub coo_sources: Vec<u32>,
    pub coo_targets: Vec<u32>,
    pub coo_relation_types: Vec<u32>,
    pub coo_authority: Vec<ResearchAuthority>,
    pub coo_splits: Vec<ResearchSplit>,
    pub coo_available_at_ms: Vec<i64>,
    pub coo_weights: Vec<f32>,
    pub csr_row_offsets: Vec<u64>,
    pub csr_columns: Vec<u32>,
    pub csr_edge_indices: Vec<u32>,
    pub incidence_hyperedges: Vec<u32>,
    pub incidence_participants: Vec<u32>,
    pub incidence_role_types: Vec<u32>,
    pub incidence_splits: Vec<ResearchSplit>,
    pub incidence_resolved: Vec<bool>,
    pub proposal_features: Vec<i16>,
    pub proposal_labels: Vec<ResearchProposalLabel>,
    pub proposal_label_observed: Vec<bool>,
    pub proposal_splits: Vec<ResearchSplit>,
    pub proposal_observed_at_ms: Vec<i64>,
    pub proposal_label_available_at_ms: Vec<i64>,
    pub proposal_feature_schema_ids: Vec<u32>,
    pub feature_certificates: Vec<FeatureColumnCertificate>,
    pub negatives: Vec<TypedNegativeSample>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenTensorManifest {
    pub schema_version: CompactString,
    pub tensor_id: CompactString,
    pub source_dataset_id: CompactString,
    pub policy: TensorizationPolicy,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub nodes: u64,
    pub edges: u64,
    pub incidences: u64,
    pub proposals: u64,
    pub negatives: u64,
    pub node_type_vocabulary: Vec<CompactString>,
    pub relation_vocabulary: Vec<CompactString>,
    pub role_vocabulary: Vec<CompactString>,
    pub feature_schema_vocabulary: Vec<CompactString>,
    pub feature_certificates: Vec<FeatureColumnCertificate>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenTensorPaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
}
