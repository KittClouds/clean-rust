use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{DocumentId, MentionId, NoteId, TextRange};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AtlasEvidenceArtifactKind {
    Mention,
    KindVote,
    AliasProposal,
    IdentityReceipt,
    CandidateSuggestion,
    GraphEdge,
    FrameTrigger,
    FrameArgument,
    FrameFact,
    UserCorrection,
    Rejection,
    DatasetExample,
}

impl Default for AtlasEvidenceArtifactKind {
    fn default() -> Self {
        Self::Mention
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AtlasEvidenceDecisionStatus {
    Observed,
    Accepted,
    Proposed,
    Deferred,
    Rejected,
    Corrected,
    Reverted,
}

impl Default for AtlasEvidenceDecisionStatus {
    fn default() -> Self {
        Self::Observed
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AtlasDatasetExampleKind {
    NerSpan,
    KindVote,
    AliasDecision,
    IdentityResolution,
    CandidateSuggestion,
    GraphEdge,
    FrameExtraction,
}

impl Default for AtlasDatasetExampleKind {
    fn default() -> Self {
        Self::NerSpan
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasEvidenceReceiptSummary {
    pub receipt_id: String,
    pub scan_id: String,
    pub document_id: Option<DocumentId>,
    pub note_id: Option<NoteId>,
    pub stage: String,
    pub artifact_kind: AtlasEvidenceArtifactKind,
    pub decision_status: AtlasEvidenceDecisionStatus,
    pub subject: String,
    pub predicate: Option<String>,
    pub object: Option<String>,
    pub surface: Option<String>,
    pub normalized: Option<String>,
    pub range: Option<TextRange>,
    pub confidence: f32,
    pub source: String,
    pub source_version: String,
    #[serde(default)]
    pub mention_ids: Vec<MentionId>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    #[serde(default)]
    pub supersedes: Vec<String>,
    #[serde(default)]
    pub reverts: Vec<String>,
    #[serde(default)]
    pub payload: Value,
    pub created_at: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasEvidenceLedgerSummary {
    pub receipt_count: usize,
    #[serde(default)]
    pub counts_by_stage: BTreeMap<String, usize>,
    #[serde(default)]
    pub counts_by_kind: BTreeMap<String, usize>,
    #[serde(default)]
    pub counts_by_decision: BTreeMap<String, usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasDatasetExampleSummary {
    pub example_id: String,
    pub snapshot_id: String,
    pub dataset_kind: String,
    pub example_kind: AtlasDatasetExampleKind,
    pub document_id: Option<DocumentId>,
    pub label: String,
    pub input_text: String,
    #[serde(default)]
    pub target: Value,
    #[serde(default)]
    pub source_receipt_ids: Vec<String>,
    pub split: String,
    #[serde(default)]
    pub payload: Value,
    pub created_at: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasDatasetSnapshotSummary {
    pub snapshot_id: String,
    pub scan_id: String,
    pub dataset_kind: String,
    pub example_count: usize,
    pub source_receipt_count: usize,
    #[serde(default)]
    pub counts_by_kind: BTreeMap<String, usize>,
    #[serde(default)]
    pub examples: Vec<AtlasDatasetExampleSummary>,
    pub created_at: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasDatasetFactorySummary {
    pub snapshot_count: usize,
    pub example_count: usize,
    #[serde(default)]
    pub snapshots: Vec<AtlasDatasetSnapshotSummary>,
}
