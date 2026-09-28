use std::path::PathBuf;

use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: &str = "E013-TRUST-SIGNAL-DEVELOPMENT-v0.2";
pub const ARTIFACT_SCHEMA_VERSION: &str = "e013-episode-artifact/v0.1";

pub trait EpisodeFamily: Send + Sync {
    fn family_id(&self) -> &'static str;
    fn generate(&self, context: &GenerationContext) -> Result<EpisodeDraft, crate::FactoryError>;
}

#[derive(Clone, Debug)]
pub struct GenerationContext {
    pub bank_id: String,
    pub family_id: String,
    pub episode_id: String,
    pub task_id: String,
    pub cell_id: String,
    pub cell_task_ordinal: u16,
    pub cell_task_count: u16,
    /// Private assignment, computed once per bank/repository/family cell.
    pub cell_empty_ordinal: u16,
    /// Private namespaced seeds; persisted only in the private construction receipt.
    pub cell_seed: u64,
    pub generation_seed: u64,
    pub candidate_order_seed: u64,
    /// Optional private matched-pair assignment; unused by the selected v0.2 contract.
    pub matched_pair: Option<MatchedPairContext>,
    pub repo: RepoSnapshot,
    /// Verified checkout used to construct commit-relative patches. Never serialized.
    pub repo_snapshot_root: PathBuf,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MatchedPairContext {
    pub pair_id: String,
    pub member_index: u8,
    pub candidate_pool_seed: u64,
    pub candidate_order_seed: u64,
}

impl GenerationContext {
    pub fn is_empty_valid_task(&self) -> bool {
        self.cell_task_ordinal == self.cell_empty_ordinal
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RepoSnapshot {
    pub repo_id: String,
    pub commit_sha: String,
    pub tree_sha: String,
}

/// Runtime-only template root. It is not part of a canonical episode identity.
#[derive(Clone, Debug)]
pub struct RepoTemplate {
    pub repo_id: String,
    pub template_root: PathBuf,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EpisodeDraft {
    pub task: Task,
    pub candidates: Vec<CandidatePatch>,
    pub visible_fixtures: Vec<Asset>,
    pub visible_evidence: Vec<Asset>,
    pub hidden_adjudicator: HiddenAdjudicator,
    pub validation: ValidationPlan,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Task {
    pub text: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidatePatch {
    pub candidate_id: String,
    pub unified_diff: Vec<u8>,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Asset {
    /// Logical slash-separated path, relative to its visible or private root.
    pub path: String,
    pub media_type: String,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HiddenAdjudicator {
    /// Internal filename only; never emitted in the observer-safe manifest.
    pub path: String,
    pub bytes: Vec<u8>,
    /// Exact strings that must not occur in observer-visible bytes.
    pub leakage_canaries: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Provenance {
    pub generator_name: String,
    pub generator_version: String,
    pub generator_source_sha256: String,
    pub source_refs: Vec<SourceReference>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SourceReference {
    pub artifact_id: String,
    pub sha256: String,
    pub role: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ValidationPlan {
    pub compile: CommandSpec,
    pub visible: CommandSpec,
    pub hidden: CommandSpec,
}

/// A program and argv pair; core never invokes a shell to expand or interpret it.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CommandSpec {
    pub program: String,
    pub args: Vec<String>,
    #[serde(default)]
    pub env: std::collections::BTreeMap<String, String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EpisodeManifest {
    pub schema_version: String,
    pub protocol_version: String,
    pub protocol_sha256: String,
    pub protocol_lock_sha256: String,
    pub episode_id: String,
    pub task_id: String,
    pub family_id: String,
    pub repo: RepoSnapshot,
    pub task: Task,
    pub candidates: Vec<CandidateRecord>,
    /// Explicit observer-facing order, derived from the private order seed and IDs.
    pub candidate_order: Vec<String>,
    pub visible_fixtures: Vec<ArtifactRecord>,
    pub visible_evidence: Vec<ArtifactRecord>,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidateRecord {
    pub candidate_id: String,
    pub patch_path: String,
    pub patch_sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactRecord {
    pub path: String,
    pub byte_len: u64,
    pub sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrivateConstructionReceipt {
    pub schema_version: String,
    pub protocol_version: String,
    pub episode_id: String,
    pub bank_id: String,
    pub family_id: String,
    pub cell_id: String,
    pub cell_task_ordinal: u16,
    pub cell_task_count: u16,
    pub cell_empty_ordinal: u16,
    pub cell_seed: u64,
    pub generation_seed: u64,
    pub candidate_order_seed: u64,
    pub matched_pair: Option<MatchedPairContext>,
    pub scratch_root: String,
    pub cargo_target_dir: String,
    pub compile_timeout_secs: u64,
    pub validation_timeout_secs: u64,
    pub hidden_adjudicator: ArtifactRecord,
    pub leakage_canaries: Vec<String>,
    pub valid_candidate_ids: Vec<String>,
    pub candidate_provenance: Vec<CandidateProvenanceRecord>,
    pub replay: Vec<crate::CandidateReplay>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidateProvenanceRecord {
    pub candidate_id: String,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SealEntry {
    pub artifact_id: String,
    pub path: String,
    pub byte_len: u64,
    pub sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EpisodeSeal {
    pub schema_version: String,
    pub seal_id: String,
    pub status: String,
    pub protocol_version: String,
    pub protocol_sha256: String,
    pub protocol_lock_sha256: String,
    pub construction_contract_sha256: String,
    pub root_sha256: String,
    pub entry_count: usize,
    pub entries: Vec<SealEntry>,
}
