use crate::LinkPredictionSplit;
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const HYPER_RELATIONAL_TASK_SCHEMA: &str =
    "phoenix-canonical-hyper-relational-link-prediction-task/v1";
pub const HYPER_RELATIONAL_TASK_BINARY_VERSION: u16 = 1;
pub const HYPER_RELATIONAL_SCORE_SCHEMA: &str = "phoenix-hyper-relational-link-prediction-score/v1";
pub const HYPER_RELATIONAL_TEST_LOCK_SCHEMA: &str = "phoenix-hyper-relational-test-lock/v1";

pub const ENTITY_ROLE_SUBJECT: u8 = 1;
pub const ENTITY_ROLE_OBJECT: u8 = 2;
pub const ENTITY_ROLE_QUALIFIER: u8 = 4;
pub const ENTITY_ROLE_PRIMARY: u8 = ENTITY_ROLE_SUBJECT | ENTITY_ROLE_OBJECT;
pub const RELATION_ROLE_PRIMARY: u8 = 1;
pub const RELATION_ROLE_QUALIFIER: u8 = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum HyperRelationalCandidatePolicy {
    FullEntity = 1,
    PrimaryRole = 2,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct HyperRelationalQuery {
    pub statement_id: u32,
    pub source: u32,
    pub target: u32,
    pub relation: u32,
    pub qualifier_context: u32,
    pub truth_group: u32,
    pub qualifier_offset: u32,
    pub qualifier_count: u32,
    pub split: LinkPredictionSplit,
    pub inverse: bool,
    pub target_role: u8,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct HyperRelationalTruthGroup {
    pub source: u32,
    pub relation: u32,
    pub qualifier_context: u32,
    pub target_offset: u32,
    pub target_count: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct HyperRelationalQualifierContext {
    pub qualifier_offset: u32,
    pub qualifier_count: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalLeakageAudit {
    pub train_validation_primary_overlap: u64,
    pub train_test_primary_overlap: u64,
    pub validation_test_primary_overlap: u64,
    pub train_validation_direct_inverse_overlap: u64,
    pub train_test_direct_inverse_overlap: u64,
    pub validation_test_direct_inverse_overlap: u64,
    pub train_validation_statement_duplicates: u64,
    pub train_test_statement_duplicates: u64,
    pub validation_test_statement_duplicates: u64,
    pub cross_split_reordered_qualifier_duplicates: u64,
    pub semantic_inverse_policy: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct HyperRelationalTaskSnapshot {
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub official_split_blake3: CompactString,
    pub statement_blake3: CompactString,
    pub original_qualifier_order_blake3: CompactString,
    pub canonical_qualifier_order_blake3: CompactString,
    pub leakage_audit: HyperRelationalLeakageAudit,
    pub queries: Vec<HyperRelationalQuery>,
    pub truth_groups: Vec<HyperRelationalTruthGroup>,
    pub truth_targets: Vec<u32>,
    pub qualifier_contexts: Vec<HyperRelationalQualifierContext>,
    pub entity_roles: Vec<u8>,
    pub relation_roles: Vec<u8>,
    pub train_statements: u64,
    pub validation_statements: u64,
    pub test_statements: u64,
    pub train_qualifier_statements: u64,
    pub validation_qualifier_statements: u64,
    pub test_qualifier_statements: u64,
    pub max_qualifiers: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HyperRelationalQueryView {
    pub source: u32,
    pub relation: u32,
    pub qualifier_offset: u32,
    pub qualifier_count: u32,
    pub split: LinkPredictionSplit,
    pub inverse: bool,
    pub target_role: u8,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalTaskManifest {
    pub schema_version: CompactString,
    pub task_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub strategy: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
    pub derived_relation_count: u32,
    pub official_split_blake3: CompactString,
    pub statement_blake3: CompactString,
    pub original_qualifier_order_blake3: CompactString,
    pub canonical_qualifier_order_blake3: CompactString,
    pub leakage_audit: HyperRelationalLeakageAudit,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub train_statements: u64,
    pub validation_statements: u64,
    pub test_statements: u64,
    pub validation_queries: u64,
    pub test_queries: u64,
    pub truth_groups: u64,
    pub truth_targets: u64,
    pub qualifier_contexts: u64,
    pub train_qualifier_statements: u64,
    pub validation_qualifier_statements: u64,
    pub test_qualifier_statements: u64,
    pub max_qualifiers: u32,
    pub primary_entities: u64,
    pub qualifier_only_entities: u64,
    pub primary_relations: u64,
    pub qualifier_only_relations: u64,
    pub qualifiers_borrowed_from_source: bool,
    pub test_locked: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HyperRelationalTaskPaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
    pub task_id: CompactString,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalRankingMetrics {
    pub mean_reciprocal_rank: f64,
    pub hits_at_1: f64,
    pub hits_at_3: f64,
    pub hits_at_5: f64,
    pub hits_at_10: f64,
    pub queries: u64,
    pub candidates_scored: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalMetricSlice {
    pub label: CompactString,
    pub metrics: HyperRelationalRankingMetrics,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalScoreCertificate {
    pub schema_version: CompactString,
    pub certificate_id: CompactString,
    pub task_id: CompactString,
    pub model_id: CompactString,
    pub split: LinkPredictionSplit,
    pub candidate_policy: HyperRelationalCandidatePolicy,
    pub score_blake3: CompactString,
    pub metrics: HyperRelationalRankingMetrics,
    pub qualifier_presence: Vec<HyperRelationalMetricSlice>,
    pub qualifier_count: Vec<HyperRelationalMetricSlice>,
    pub primary_relation: Vec<HyperRelationalMetricSlice>,
    pub target_provenance: Vec<HyperRelationalMetricSlice>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalTestLockInput {
    pub task_id: CompactString,
    pub selection_ledger_id: CompactString,
    pub selected_model_id: CompactString,
    pub validation_certificate_id: CompactString,
    pub candidate_policy: HyperRelationalCandidatePolicy,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperRelationalTestLock {
    pub schema_version: CompactString,
    pub lock_id: CompactString,
    pub task_id: CompactString,
    pub selection_ledger_id: CompactString,
    pub selected_model_id: CompactString,
    pub validation_certificate_id: CompactString,
    pub candidate_policy: HyperRelationalCandidatePolicy,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HyperRelationalTestLockPaths {
    pub receipt: PathBuf,
    pub lock_id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HyperRelationalTestResultPaths {
    pub claim: PathBuf,
    pub certificate: PathBuf,
}

#[derive(Debug, thiserror::Error)]
pub enum HyperRelationalTaskError {
    #[error("hyper-relational task input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("hyper-relational task artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("hyper-relational task artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("hyper-relational test evaluation is already claimed: {0}")]
    TestAlreadyClaimed(PathBuf),
    #[error("hyper-relational scorer failed: {0}")]
    Scorer(String),
    #[error("hyper-relational source failed validation: {0}")]
    Source(#[from] crate::ExternalDatasetError),
    #[error("hyper-relational task I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("hyper-relational task JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
