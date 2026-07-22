use compact_str::CompactString;
use serde::{Deserialize, Serialize};

pub const STORY_CONTINUITY_SCHEMA_VERSION: &str = "phoenix-story-continuity/v1";
pub const STORY_CONTINUITY_CERTIFICATE_SCHEMA_VERSION: &str =
    "phoenix-story-continuity-run-certificate/v1";
pub const STORY_CONTINUITY_NO_TOPOLOGY_COMMIT: &str =
    "story_continuity:candidate_only:no_topology_commit";

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryContinuityDocument {
    pub note_id: CompactString,
    pub text: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContinuityStatus {
    Structural,
    Candidate,
    ReviewRequired,
    Blocked,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContinuityEvidenceClass {
    SourceSpan,
    ExplicitCue,
    Calendar,
    DocumentOrder,
    SemanticBridge,
    StateTransition,
    LegacyAdjacency,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpisodeBoundaryDecision {
    DocumentStart,
    Heading,
    SceneBreak,
    CompositeTransition,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityBoundarySignal {
    pub kind: CompactString,
    pub detail: CompactString,
    pub evidence_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EpisodeBoundaryReceipt {
    pub id: CompactString,
    pub note_id: CompactString,
    pub before_chunk_id: Option<CompactString>,
    pub after_chunk_id: CompactString,
    pub source_offset: u32,
    pub decision: EpisodeBoundaryDecision,
    pub signals: Vec<ContinuityBoundarySignal>,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityEventIdentity {
    pub id: CompactString,
    pub source_situation_id: Option<CompactString>,
    pub source_event_id: Option<CompactString>,
    pub note_id: CompactString,
    pub chunk_id: CompactString,
    pub source_start: u32,
    pub source_end: u32,
    pub predicate: CompactString,
    pub participant_entity_ids: Vec<CompactString>,
    pub evidence_ids: Vec<CompactString>,
    pub factuality: CompactString,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryEpisodeCandidate {
    pub id: CompactString,
    pub note_id: CompactString,
    pub label: CompactString,
    pub source_start: u32,
    pub source_end: u32,
    pub chunk_ids: Vec<CompactString>,
    pub event_ids: Vec<CompactString>,
    pub entity_ids: Vec<CompactString>,
    pub boundary_receipt_ids: Vec<CompactString>,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContinuityTemporalRelation {
    Before,
    After,
    Overlaps,
    During,
    Contains,
    Starts,
    Finishes,
    RecursAfter,
    Supersedes,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityTemporalCandidate {
    pub id: CompactString,
    pub source_id: CompactString,
    pub target_id: CompactString,
    pub relation: ContinuityTemporalRelation,
    pub evidence_class: ContinuityEvidenceClass,
    pub evidence_ids: Vec<CompactString>,
    pub cue: Option<CompactString>,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityStateIntervalCandidate {
    pub id: CompactString,
    pub note_id: CompactString,
    pub subject_key: CompactString,
    pub state_key: CompactString,
    pub value: Option<CompactString>,
    pub polarity: CompactString,
    pub start_event_id: CompactString,
    pub end_event_id: Option<CompactString>,
    pub source_start: u32,
    pub source_end: Option<u32>,
    pub persists: bool,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContinuityCausalRelation {
    DirectCause,
    EnablingCondition,
    Prevention,
    Motivation,
    Explanation,
    Consequence,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityCausalCandidate {
    pub id: CompactString,
    pub source_event_id: CompactString,
    pub target_event_id: CompactString,
    pub relation: ContinuityCausalRelation,
    pub evidence_class: ContinuityEvidenceClass,
    pub evidence_ids: Vec<CompactString>,
    pub cue: Option<CompactString>,
    pub polarity: CompactString,
    pub modality: CompactString,
    pub attribution_entity_id: Option<CompactString>,
    pub temporal_legal: bool,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpisodeContinuityKind {
    Continuation,
    SetupPayoff,
    Recurrence,
    ParallelAction,
    Flashback,
    StateTransition,
    CrossDocumentContinuation,
    MotifEcho,
    EvidenceReframe,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EpisodeContinuityCandidate {
    pub id: CompactString,
    pub source_episode_id: CompactString,
    pub target_episode_id: CompactString,
    pub kind: EpisodeContinuityKind,
    pub evidence_class: ContinuityEvidenceClass,
    pub evidence_ids: Vec<CompactString>,
    pub supporting_entity_ids: Vec<CompactString>,
    pub rationale: Vec<CompactString>,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityConflictCandidate {
    pub id: CompactString,
    pub note_id: CompactString,
    pub kind: CompactString,
    pub row_ids: Vec<CompactString>,
    pub evidence_ids: Vec<CompactString>,
    pub severity: CompactString,
    pub confidence_millis: u16,
    pub status: ContinuityStatus,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryContinuityCounters {
    pub events: usize,
    pub boundary_receipts: usize,
    pub episodes: usize,
    pub temporal_candidates: usize,
    pub state_intervals: usize,
    pub causal_candidates: usize,
    pub episode_connections: usize,
    pub conflicts: usize,
    pub cross_document_connections: usize,
    pub review_required: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryContinuityRunCertificate {
    pub schema_version: CompactString,
    pub source_snapshot_id: CompactString,
    pub source_document_ids: Vec<CompactString>,
    pub build_micros: u64,
    pub event_identity_micros: u64,
    pub episode_boundary_micros: u64,
    pub relation_resolution_micros: u64,
    pub counters: StoryContinuityCounters,
    pub no_topology_writes: bool,
    pub all_rows_evidenced: bool,
    pub stable_source_identities: bool,
    pub fixed_batching_detected: bool,
    pub invariant_receipts: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryContinuityContract {
    pub schema_version: CompactString,
    pub source: CompactString,
    pub source_snapshot_id: CompactString,
    pub generated_at: u64,
    pub commit_policy: CompactString,
    pub no_topology_commit: bool,
    pub events: Vec<ContinuityEventIdentity>,
    pub boundary_receipts: Vec<EpisodeBoundaryReceipt>,
    pub episodes: Vec<StoryEpisodeCandidate>,
    pub temporal_candidates: Vec<ContinuityTemporalCandidate>,
    pub state_intervals: Vec<ContinuityStateIntervalCandidate>,
    pub causal_candidates: Vec<ContinuityCausalCandidate>,
    pub episode_connections: Vec<EpisodeContinuityCandidate>,
    pub conflicts: Vec<ContinuityConflictCandidate>,
    pub certificate: StoryContinuityRunCertificate,
}
