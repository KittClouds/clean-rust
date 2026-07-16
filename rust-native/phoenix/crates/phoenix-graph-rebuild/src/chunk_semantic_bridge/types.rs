use compact_str::CompactString;
use phoenix_types::EntityId;
use serde::{Deserialize, Serialize};

pub const CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION: &str = "phoenix-chunk-semantic-bridge/v1";
pub const CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY: &str = "no_topology_commit";
pub const CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT: &str =
    "chunk_semantic_bridge_candidate:no_topology_commit";
pub const CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION: &str =
    "phoenix-cross-document-bridge-run-certificate/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSemanticBridgeType {
    SetupPayoff,
    CauseEffect,
    StateDelta,
    RelationshipDelta,
    TopicContinuation,
    EvidenceReframe,
    MotifEcho,
    RouteContinuity,
}

impl ChunkSemanticBridgeType {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SetupPayoff => "setup_payoff",
            Self::CauseEffect => "cause_effect",
            Self::StateDelta => "state_delta",
            Self::RelationshipDelta => "relationship_delta",
            Self::TopicContinuation => "topic_continuation",
            Self::EvidenceReframe => "evidence_reframe",
            Self::MotifEcho => "motif_echo",
            Self::RouteContinuity => "route_continuity",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSemanticBridgeStatus {
    Candidate,
    OverlayOnly,
}

impl ChunkSemanticBridgeStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Candidate => "candidate",
            Self::OverlayOnly => "overlay_only",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSemanticBridgeCommitPolicy {
    NoTopologyCommit,
}

impl ChunkSemanticBridgeCommitPolicy {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NoTopologyCommit => CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgeEntity<'a> {
    pub id: &'a EntityId,
    pub label: &'a str,
    pub kind: Option<&'a str>,
}

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgeEvidence<'a> {
    pub id: &'a str,
    pub source_id: Option<&'a str>,
    pub chunk_id: Option<&'a str>,
    pub event_id: Option<&'a str>,
}

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgeChunk<'a> {
    pub id: &'a str,
    pub note_id: &'a str,
    pub ordinal: u32,
    pub text: &'a str,
    pub role: Option<&'a str>,
    pub episode_id: Option<&'a str>,
    pub entity_ids: &'a [EntityId],
    pub evidence_ids: &'a [CompactString],
}

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgeEvent<'a> {
    pub id: &'a str,
    pub note_id: &'a str,
    pub chunk_id: Option<&'a str>,
    pub label: &'a str,
    pub entity_ids: &'a [EntityId],
    pub evidence_ids: &'a [CompactString],
    pub confidence: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgeEventEdge<'a> {
    pub source_event_id: &'a str,
    pub target_event_id: &'a str,
    pub relation_type: &'a str,
    pub cue: Option<&'a str>,
    pub evidence_ids: &'a [CompactString],
    pub confidence: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ChunkSemanticBridgeEngineInput<'a> {
    pub chunks: &'a [ChunkSemanticBridgeChunk<'a>],
    pub events: &'a [ChunkSemanticBridgeEvent<'a>],
    pub entities: &'a [ChunkSemanticBridgeEntity<'a>],
    pub evidence: &'a [ChunkSemanticBridgeEvidence<'a>],
    pub temporal_edges: &'a [ChunkSemanticBridgeEventEdge<'a>],
    pub causal_edges: &'a [ChunkSemanticBridgeEventEdge<'a>],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgeCandidate {
    pub schema_version: CompactString,
    pub id: CompactString,
    pub bridge_type: ChunkSemanticBridgeType,
    pub source_chunk_id: CompactString,
    pub target_chunk_id: CompactString,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_event_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_event_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_episode_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_episode_id: Option<CompactString>,
    pub claim: CompactString,
    #[serde(default)]
    pub evidence_ids: Vec<CompactString>,
    #[serde(default)]
    pub supporting_entity_ids: Vec<CompactString>,
    pub confidence: f32,
    pub status: ChunkSemanticBridgeStatus,
    pub commit_policy: ChunkSemanticBridgeCommitPolicy,
    #[serde(default)]
    pub semantic_verbs: Vec<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_cue: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_cue: Option<CompactString>,
    #[serde(default)]
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrossDocumentBridgePairCoverage {
    pub source_document_id: CompactString,
    pub target_document_id: CompactString,
    pub generated_candidates: usize,
    pub eligible_candidates: usize,
    pub selected_candidates: usize,
    pub rejected_candidates: usize,
    pub selected_bridge_types: Vec<ChunkSemanticBridgeType>,
    pub coverage_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrossDocumentBridgeAuditRow {
    pub id: CompactString,
    pub source_document_id: CompactString,
    pub target_document_id: CompactString,
    pub source_chunk_id: CompactString,
    pub target_chunk_id: CompactString,
    pub source_excerpt: CompactString,
    pub target_excerpt: CompactString,
    pub bridge_type: ChunkSemanticBridgeType,
    pub claim: CompactString,
    pub evidence_ids: Vec<CompactString>,
    pub supporting_entity_ids: Vec<CompactString>,
    pub confidence_millis: u16,
    pub rejection_reason: Option<CompactString>,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrossDocumentBridgeRejectionCount {
    pub reason: CompactString,
    pub count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrossDocumentBridgeRunCertificate {
    pub schema_version: CompactString,
    pub source_document_ids: Vec<CompactString>,
    pub generated_candidates: usize,
    pub eligible_candidates: usize,
    pub selected_candidates: usize,
    pub rejected_candidates: usize,
    pub pair_coverage: Vec<CrossDocumentBridgePairCoverage>,
    pub rejection_counts: Vec<CrossDocumentBridgeRejectionCount>,
    pub selected_rows: Vec<CrossDocumentBridgeAuditRow>,
    pub rejected_rows: Vec<CrossDocumentBridgeAuditRow>,
    pub weakest_rows: Vec<CrossDocumentBridgeAuditRow>,
    pub no_topology_writes: bool,
    pub invariant_receipts: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgeRun {
    pub candidates: Vec<ChunkSemanticBridgeCandidate>,
    pub cross_document_certificate: CrossDocumentBridgeRunCertificate,
}
