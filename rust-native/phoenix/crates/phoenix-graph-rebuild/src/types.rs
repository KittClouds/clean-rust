use compact_str::CompactString;
use phoenix_types::EntityId;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphScopeKind {
    Global,
    Folder,
    Narrative,
    Note,
    MultiNote,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphChunk {
    pub id: CompactString,
    pub note_id: CompactString,
    pub start: u32,
    pub end: u32,
    pub ordinal: u32,
    pub source: CompactString,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphMention {
    pub id: CompactString,
    pub note_id: CompactString,
    pub chunk_id: Option<CompactString>,
    pub surface: CompactString,
    pub source_start: u32,
    pub source_end: u32,
    pub source: CompactString,
    pub confidence: f32,
    pub entity_id: Option<EntityId>,
    pub status: CompactString,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphAnchor {
    pub id: CompactString,
    pub entity_id: EntityId,
    pub note_id: CompactString,
    pub chunk_id: Option<CompactString>,
    pub surface: CompactString,
    pub source_start: u32,
    pub source_end: u32,
    pub source: CompactString,
    pub confidence: f32,
    pub generation: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphNode {
    pub id: EntityId,
    pub entity_id: EntityId,
    pub label: CompactString,
    pub kind: CompactString,
    pub aliases: Vec<CompactString>,
    pub anchor_ids: Vec<CompactString>,
    pub note_ids: Vec<CompactString>,
    pub total_mentions: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphEdge {
    pub id: CompactString,
    pub source_id: EntityId,
    pub target_id: EntityId,
    #[serde(alias = "type")]
    pub edge_type: CompactString,
    pub weight: u32,
    pub confidence: f32,
    pub evidence_anchor_ids: Vec<CompactString>,
    pub scope_keys: Vec<CompactString>,
    pub note_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphRelationship {
    pub id: CompactString,
    pub source_entity_id: EntityId,
    pub target_entity_id: EntityId,
    pub relation_type: CompactString,
    pub evidence_anchor_ids: Vec<CompactString>,
    pub confidence: f32,
    pub status: CompactString,
    pub adjudication_source: CompactString,
    pub adjudication_score: f32,
    pub rationale: CompactString,
    pub decision_evidence: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphEvent {
    pub id: CompactString,
    pub note_id: CompactString,
    pub chunk_id: Option<CompactString>,
    pub label: CompactString,
    pub entity_ids: Vec<EntityId>,
    pub evidence_anchor_ids: Vec<CompactString>,
    pub confidence: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphEpisode {
    pub id: CompactString,
    pub note_id: CompactString,
    pub event_ids: Vec<CompactString>,
    pub entity_ids: Vec<EntityId>,
    pub label: CompactString,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphEpisodeProjectionEdge {
    pub schema_version: CompactString,
    pub id: CompactString,
    pub kind: CompactString,
    pub source_id: CompactString,
    pub target_id: CompactString,
    pub source_target_id: CompactString,
    pub target_target_id: CompactString,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub episode_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_episode_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_episode_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub event_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub episode_connection_id: Option<CompactString>,
    pub relation_type: CompactString,
    pub evidence_ids: Vec<CompactString>,
    pub confidence: f32,
    pub status: CompactString,
    pub no_topology_commit: bool,
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphTemporalEdge {
    pub id: CompactString,
    pub source_id: CompactString,
    pub target_id: CompactString,
    pub relation_type: CompactString,
    pub evidence_ids: Vec<CompactString>,
    pub confidence: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphMemoryState {
    pub id: CompactString,
    pub entity_id: EntityId,
    pub note_id: Option<CompactString>,
    pub key: CompactString,
    pub value: CompactString,
    pub evidence_ids: Vec<CompactString>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphMemoryGovernanceTargetKind {
    Chunk,
    Episode,
}

impl GraphMemoryGovernanceTargetKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Chunk => "chunk",
            Self::Episode => "episode",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphMemoryGovernanceAction {
    Retain,
    Attenuate,
    Compress,
    Quarantine,
    Retire,
}

impl GraphMemoryGovernanceAction {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Retain => "retain",
            Self::Attenuate => "attenuate",
            Self::Compress => "compress",
            Self::Quarantine => "quarantine",
            Self::Retire => "retire",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphMemoryGovernanceStatus {
    Candidate,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphMemoryGovernanceCommitPolicy {
    NoTopologyCommit,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphMemoryGovernanceSignals {
    pub age: f32,
    pub access_frequency: f32,
    pub redundancy: f32,
    pub contradiction_risk: f32,
    pub causal_importance: f32,
    pub narrative_salience: f32,
    pub retrieval_utility: f32,
    pub evidence_strength: f32,
    pub user_pinned: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphMemoryGovernanceCandidate {
    pub schema_version: CompactString,
    pub id: CompactString,
    pub target_id: CompactString,
    pub target_kind: GraphMemoryGovernanceTargetKind,
    pub action: GraphMemoryGovernanceAction,
    pub reason: CompactString,
    #[serde(default)]
    pub evidence_ids: Vec<CompactString>,
    #[serde(default)]
    pub supporting_entity_ids: Vec<CompactString>,
    #[serde(default)]
    pub related_event_ids: Vec<CompactString>,
    #[serde(default)]
    pub related_chunk_ids: Vec<CompactString>,
    pub signals: GraphMemoryGovernanceSignals,
    pub confidence: f32,
    pub status: GraphMemoryGovernanceStatus,
    pub commit_policy: GraphMemoryGovernanceCommitPolicy,
    pub no_topology_commit: bool,
    #[serde(default)]
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphEmbeddingTarget {
    pub id: CompactString,
    pub kind: CompactString,
    pub source_id: CompactString,
    pub note_id: Option<CompactString>,
    pub chunk_id: Option<CompactString>,
    pub entity_id: Option<EntityId>,
    #[serde(default)]
    pub entity_kind: Option<CompactString>,
    pub label: CompactString,
    pub text: CompactString,
    pub evidence_ids: Vec<CompactString>,
    #[serde(default)]
    pub lane: Option<CompactString>,
    #[serde(default)]
    pub structural_role: Option<CompactString>,
    #[serde(default)]
    pub admission_status: Option<CompactString>,
    #[serde(default)]
    pub work_status: Option<CompactString>,
    #[serde(default)]
    pub style_key: Option<CompactString>,
    #[serde(default)]
    pub document_unit_kind: Option<CompactString>,
    #[serde(default)]
    pub state_context_kind: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub parent_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphProjectionRef {
    pub target_id: CompactString,
    pub manifold: CompactString,
    pub projection_id: CompactString,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDropReasons {
    pub missing_entity: usize,
    pub invalid_span: usize,
    pub duplicate_anchor: usize,
    pub singleton_bucket: usize,
    pub missing_chunk: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCounters {
    pub entities: usize,
    pub aliases: usize,
    pub candidates: usize,
    pub mentions: usize,
    pub accepted_anchors: usize,
    pub chunks: usize,
    pub anchor_evidence: usize,
    pub relation_signals: usize,
    pub promoted_facts: usize,
    pub relationship_candidates: usize,
    pub relationships: usize,
    pub accepted_relationships: usize,
    pub review_relationships: usize,
    pub rejected_relationships: usize,
    pub events: usize,
    pub episodes: usize,
    #[serde(default)]
    pub episode_projection_edges: usize,
    #[serde(default)]
    pub episode_projection_structural_edges: usize,
    #[serde(default)]
    pub episode_projection_derived_edges: usize,
    #[serde(default)]
    pub episode_projection_candidate_edges: usize,
    pub temporal_edges: usize,
    pub causal_edges: usize,
    pub memory_state: usize,
    #[serde(default)]
    pub memory_governance_candidates: usize,
    #[serde(default)]
    pub memory_governance_retain: usize,
    #[serde(default)]
    pub memory_governance_attenuate: usize,
    #[serde(default)]
    pub memory_governance_compress: usize,
    #[serde(default)]
    pub memory_governance_quarantine: usize,
    #[serde(default)]
    pub memory_governance_retire: usize,
    pub embedding_targets: usize,
    pub embedding_vectors: usize,
    pub projection_refs: usize,
    pub nodes: usize,
    pub edges: usize,
    pub drop_reasons: GraphDropReasons,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCalendarRegistryBridgeCounters {
    #[serde(default)]
    pub anchor_count: usize,
    #[serde(default)]
    pub receipt_count: usize,
    #[serde(default)]
    pub accepted_temporal_receipts: usize,
    #[serde(default)]
    pub registry_only_receipts: usize,
    #[serde(default)]
    pub deferred_invalid_receipts: usize,
    #[serde(default)]
    pub custom_ordinal_receipts: usize,
    #[serde(default)]
    pub real_epoch_receipts: usize,
    #[serde(default)]
    pub event_receipts: usize,
    #[serde(default)]
    pub folder_receipts: usize,
    #[serde(default)]
    pub period_receipts: usize,
    #[serde(default)]
    pub marker_receipts: usize,
    #[serde(default)]
    pub mutation_allowed_count: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCalendarRegistryReceipt {
    pub id: CompactString,
    pub calendar_anchor_id: CompactString,
    pub source_kind: CompactString,
    pub source_id: CompactString,
    pub status: CompactString,
    pub date_key: CompactString,
    pub normalized_value: CompactString,
    pub display_date: CompactString,
    pub ordinal: i64,
    pub end_ordinal: Option<i64>,
    pub real_epoch_ms: Option<i64>,
    pub real_interval_end_ms: Option<i64>,
    #[serde(default)]
    pub source_note_ids: Vec<CompactString>,
    #[serde(default)]
    pub evidence_refs: Vec<CompactString>,
    #[serde(default)]
    pub affected_graph_atoms: Vec<CompactString>,
    #[serde(default)]
    pub affected_graph_facts: Vec<CompactString>,
    #[serde(default)]
    pub reversible: bool,
    #[serde(default)]
    pub mutation_allowed: bool,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCalendarRegistryBridgeSummary {
    pub schema_version: CompactString,
    pub generated_at: u64,
    pub source_snapshot_id: CompactString,
    pub source_calendar_registry_id: CompactString,
    pub calendar_id: CompactString,
    pub calendar_fingerprint: CompactString,
    pub calendar_mode: CompactString,
    pub scope_kind: CompactString,
    pub scope_id: CompactString,
    #[serde(default)]
    pub receipts: Vec<GraphCalendarRegistryReceipt>,
    #[serde(default)]
    pub counters: GraphCalendarRegistryBridgeCounters,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentConfidence {
    #[serde(default)]
    pub score: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentEvidenceSpan {
    pub id: CompactString,
    pub note_id: CompactString,
    #[serde(default)]
    pub unit_id: Option<CompactString>,
    #[serde(default)]
    pub chunk_id: Option<CompactString>,
    pub start: u32,
    pub end: u32,
    #[serde(default)]
    pub preview: Option<CompactString>,
    #[serde(default)]
    pub confidence: GraphDocumentConfidence,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentSidecarSummary {
    #[serde(default)]
    pub units: Vec<GraphDocumentUnitSummary>,
    #[serde(default)]
    pub sections: Vec<GraphDocumentUnitSummary>,
    #[serde(default)]
    pub regions: Vec<GraphDocumentUnitSummary>,
    #[serde(default)]
    pub rhetorical_units: Vec<GraphDocumentUnitSummary>,
    #[serde(default)]
    pub retrieval_units: Vec<GraphDocumentUnitSummary>,
    #[serde(default)]
    pub graph_fact_candidates: Vec<GraphDocumentUnitSummary>,
    #[serde(default)]
    pub evidence_spans: Vec<GraphDocumentEvidenceSpan>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentUnitSummary {
    pub id: CompactString,
    pub note_id: CompactString,
    pub kind: CompactString,
    pub label: CompactString,
    #[serde(default)]
    pub start: u32,
    #[serde(default)]
    pub end: u32,
    #[serde(default)]
    pub depth: u32,
    #[serde(default)]
    pub parent_id: Option<CompactString>,
    #[serde(default)]
    pub child_ids: Vec<CompactString>,
    #[serde(default)]
    pub evidence_span_ids: Vec<CompactString>,
    #[serde(default)]
    pub target_chunk_ids: Vec<CompactString>,
    #[serde(default)]
    pub subject_surfaces: Vec<CompactString>,
    #[serde(default)]
    pub object_surfaces: Vec<CompactString>,
    #[serde(default)]
    pub predicate: Option<CompactString>,
    #[serde(default)]
    pub relation_type: Option<CompactString>,
    #[serde(default)]
    pub frame_family: Option<CompactString>,
    #[serde(default)]
    pub semantic_situation_id: Option<CompactString>,
    #[serde(default)]
    pub state_interval_ids: Vec<CompactString>,
    #[serde(default)]
    pub event_ordering_ids: Vec<CompactString>,
    #[serde(default)]
    pub temporal_conflict_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentReviewSummary {
    #[serde(default)]
    pub rows: Vec<GraphDocumentReviewRow>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentReviewRow {
    pub id: CompactString,
    pub object_id: CompactString,
    pub object_kind: CompactString,
    pub state: CompactString,
    pub title: CompactString,
    #[serde(default)]
    pub subtitle: CompactString,
    #[serde(default)]
    pub detail: CompactString,
    pub note_id: CompactString,
    #[serde(default)]
    pub source_start: u32,
    #[serde(default)]
    pub source_end: u32,
    #[serde(default)]
    pub confidence: f32,
    #[serde(default)]
    pub detector: CompactString,
    #[serde(default)]
    pub parent_unit_ids: Vec<CompactString>,
    #[serde(default)]
    pub child_unit_ids: Vec<CompactString>,
    #[serde(default)]
    pub evidence_span_ids: Vec<CompactString>,
    #[serde(default)]
    pub related_object_ids: Vec<CompactString>,
    #[serde(default)]
    pub why: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDiscourseSpineSummary {
    #[serde(default)]
    pub targets: Vec<GraphDiscourseSpineTargetSummary>,
    #[serde(default)]
    pub clusters: Vec<GraphDiscourseSpineCluster>,
    #[serde(default)]
    pub bridges: Vec<GraphDiscourseSpineBridge>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDiscourseSpineTargetSummary {
    pub target_id: CompactString,
    pub source_id: CompactString,
    pub kind: CompactString,
    pub label: CompactString,
    #[serde(default)]
    pub note_id: Option<CompactString>,
    #[serde(default)]
    pub chunk_id: Option<CompactString>,
    #[serde(default)]
    pub parent_target_ids: Vec<CompactString>,
    #[serde(default)]
    pub entity_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDiscourseSpineCluster {
    pub id: CompactString,
    pub kind: CompactString,
    pub label: CompactString,
    #[serde(default)]
    pub target_ids: Vec<CompactString>,
    #[serde(default)]
    pub score: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDiscourseSpineBridge {
    pub id: CompactString,
    pub kind: CompactString,
    pub status: CompactString,
    pub source_target_id: CompactString,
    pub target_target_id: CompactString,
    pub label: CompactString,
    #[serde(default)]
    pub evidence_target_ids: Vec<CompactString>,
    #[serde(default)]
    pub shared_label_ids: Vec<CompactString>,
    #[serde(default)]
    pub shared_entity_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentCompilerProvenance {
    #[serde(default)]
    pub source_object_id: CompactString,
    #[serde(default)]
    pub source_object_kind: CompactString,
    #[serde(default)]
    pub source_review_row_id: Option<CompactString>,
    #[serde(default)]
    pub review_state: Option<CompactString>,
    pub note_id: CompactString,
    #[serde(default)]
    pub source_start: u32,
    #[serde(default)]
    pub source_end: u32,
    #[serde(default)]
    pub evidence_span_ids: Vec<CompactString>,
    #[serde(default)]
    pub lineage_unit_ids: Vec<CompactString>,
    #[serde(default)]
    pub reasons: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentCompilerHyperedgeRole {
    pub id: CompactString,
    pub role: CompactString,
    #[serde(default)]
    pub semantic_role: Option<CompactString>,
    #[serde(default)]
    pub slot_type: Option<CompactString>,
    pub target_id: CompactString,
    pub target_kind: CompactString,
    #[serde(default)]
    pub surface: Option<CompactString>,
    #[serde(default)]
    pub confidence: f32,
    #[serde(default)]
    pub required: Option<bool>,
    #[serde(default)]
    pub resolved: Option<bool>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentCompilerHyperedge {
    pub id: CompactString,
    pub predicate: CompactString,
    #[serde(default)]
    pub trigger_predicate: Option<CompactString>,
    #[serde(default)]
    pub frame: Option<CompactString>,
    #[serde(default)]
    pub frame_family: Option<CompactString>,
    #[serde(default)]
    pub situation_kind: Option<CompactString>,
    #[serde(default)]
    pub factuality: Option<CompactString>,
    #[serde(default)]
    pub speech_act: Option<CompactString>,
    #[serde(default)]
    pub semantic_situation_id: Option<CompactString>,
    #[serde(default)]
    pub semantic_proposition_id: Option<CompactString>,
    #[serde(default)]
    pub state_interval_ids: Vec<CompactString>,
    #[serde(default)]
    pub event_ordering_ids: Vec<CompactString>,
    #[serde(default)]
    pub temporal_conflict_ids: Vec<CompactString>,
    #[serde(default)]
    pub compilation_basis: Option<CompactString>,
    #[serde(default)]
    pub roles: Vec<GraphDocumentCompilerHyperedgeRole>,
    #[serde(default)]
    pub evidence_span_ids: Vec<CompactString>,
    #[serde(default)]
    pub confidence: f32,
    pub status: CompactString,
    #[serde(default)]
    pub provenance: Option<GraphDocumentCompilerProvenance>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDocumentCompilerSummary {
    #[serde(default)]
    pub hyperedges: Vec<GraphDocumentCompilerHyperedge>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphRebuildSnapshot {
    pub schema_version: CompactString,
    pub id: CompactString,
    pub source: CompactString,
    pub scope_kind: GraphScopeKind,
    pub scope_id: CompactString,
    pub note_ids: Vec<CompactString>,
    pub built_at: u64,
    pub chunks: Vec<GraphChunk>,
    pub mentions: Vec<GraphMention>,
    pub entity_anchors: Vec<GraphAnchor>,
    pub relationships: Vec<GraphRelationship>,
    pub events: Vec<GraphEvent>,
    pub episodes: Vec<GraphEpisode>,
    #[serde(default)]
    pub episode_projection_edges: Vec<GraphEpisodeProjectionEdge>,
    pub temporal_edges: Vec<GraphTemporalEdge>,
    pub causal_edges: Vec<GraphTemporalEdge>,
    pub memory_state: Vec<GraphMemoryState>,
    #[serde(default)]
    pub memory_governance_candidates: Vec<GraphMemoryGovernanceCandidate>,
    pub embedding_targets: Vec<GraphEmbeddingTarget>,
    pub embedding_vectors: Vec<CompactString>,
    pub projection_refs: Vec<GraphProjectionRef>,
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    #[serde(default)]
    pub calendar_registry_summary: Option<GraphCalendarRegistryBridgeSummary>,
    #[serde(default)]
    pub document_sidecar_summary: Option<GraphDocumentSidecarSummary>,
    #[serde(default)]
    pub document_review_summary: Option<GraphDocumentReviewSummary>,
    #[serde(default)]
    pub document_compiler_summary: Option<GraphDocumentCompilerSummary>,
    #[serde(default)]
    pub discourse_spine_summary: Option<GraphDiscourseSpineSummary>,
    pub counters: GraphCounters,
}
