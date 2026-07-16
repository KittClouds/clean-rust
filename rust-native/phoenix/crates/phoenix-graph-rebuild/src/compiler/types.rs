use compact_str::CompactString;
use phoenix_alex::SurfaceHit;
use phoenix_chunker_native::{LensChunk, LensMentionGraph};
use phoenix_types::{EntityId, TextRange};
use serde::{Deserialize, Serialize};

use crate::types::{
    GraphAnchor, GraphCalendarRegistryBridgeSummary, GraphChunk, GraphEdge, GraphEvent,
    GraphMemoryState, GraphMention, GraphNode, GraphRelationship, GraphScopeKind,
    GraphTemporalEdge,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum FactLane {
    DocumentSpine,
    ChunkSpine,
    EntityAnchor,
    RelationshipFact,
    CooccurrenceWeak,
    EventIdentity,
    TemporalFact,
    CausalFact,
    MemoryState,
    EntityLinker,
    AnchorEvidence,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphAtomKind {
    Document,
    DocumentRoot,
    LaneRoot,
    Chunk,
    Frame,
    SourceSpan,
    EvidenceAnchor,
    Entity,
    Concept,
    Event,
    State,
    Claim,
    RelationFact,
    TimeAnchor,
    Root,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum EvidenceKind {
    SurfaceHit,
    MentionPacket,
    CueHit,
    LensFrame,
    SourceSpan,
    UserAccepted,
    ModelVote,
    AdjudicationVote,
    EventReference,
    CalendarRegistry,
    MentionGraphEdge,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum EvidenceBundleKind {
    Span,
    Frame,
    Neighborhood,
    SemanticSimilarity,
    ShadowIdentity,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BundleCompressionModel {
    JinaV5Nano,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BundleRerankSource {
    GliClass,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub enum GraphPrototypeFamily {
    EntityKind,
    RelationFamily,
    EvidenceAuthority,
    GraphStage,
    ConceptDomain,
}

#[derive(Clone, Copy, Debug)]
pub struct BundleCompressionPolicy {
    pub cluster_similarity_threshold: f32,
    pub duplicate_similarity_threshold: f32,
    pub outlier_score_threshold: f32,
}

impl Default for BundleCompressionPolicy {
    fn default() -> Self {
        Self {
            cluster_similarity_threshold: 0.72,
            duplicate_similarity_threshold: 0.96,
            outlier_score_threshold: 0.72,
        }
    }
}

pub struct BundleEmbedding<'a> {
    pub bundle_id: &'a str,
    pub vector: &'a [f32],
}

pub struct BundleRerankScore<'a> {
    pub bundle_id: &'a str,
    pub source: BundleRerankSource,
    pub score: f32,
}

pub struct BundleCompressionInput<'a> {
    pub model: BundleCompressionModel,
    pub embeddings: &'a [BundleEmbedding<'a>],
    pub rerank_scores: &'a [BundleRerankScore<'a>],
    pub policy: BundleCompressionPolicy,
}

#[derive(Clone, Copy, Debug)]
pub struct BundleCommitmentPolicy {
    pub family: GraphPrototypeFamily,
    pub curvature: f32,
    pub commitment_weight: f32,
    pub radial_weight: f32,
    pub ambiguity_threshold: f32,
    pub promotion_margin: f32,
    pub top_k: usize,
}

impl Default for BundleCommitmentPolicy {
    fn default() -> Self {
        Self {
            family: GraphPrototypeFamily::RelationFamily,
            curvature: 1.0,
            commitment_weight: 2.0,
            radial_weight: 0.25,
            ambiguity_threshold: 0.45,
            promotion_margin: 0.35,
            top_k: 4,
        }
    }
}

pub struct BundlePrototype<'a> {
    pub prototype_id: &'a str,
    pub family: GraphPrototypeFamily,
    pub label: &'a str,
    pub direction: &'a [f32],
}

pub struct BundleCommitmentPoint<'a> {
    pub bundle_id: &'a str,
    pub point: &'a [f32],
}

pub struct BundleCommitmentInput<'a> {
    pub prototypes: &'a [BundlePrototype<'a>],
    pub points: &'a [BundleCommitmentPoint<'a>],
    pub policy: BundleCommitmentPolicy,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FactBundlePrototypeScore {
    pub prototype_id: CompactString,
    pub family: GraphPrototypeFamily,
    pub score: f32,
    pub probability: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FactBundleCommitment {
    pub family: GraphPrototypeFamily,
    pub top_prototype_id: CompactString,
    pub top_label: CompactString,
    pub top_score: f32,
    pub top_probability: f32,
    pub second_prototype_id: Option<CompactString>,
    pub second_score: Option<f32>,
    pub second_probability: Option<f32>,
    pub margin: f32,
    pub entropy: f32,
    pub ambiguity_score: f32,
    pub classification_confidence: f32,
    pub promotion_ready: bool,
    pub radial_strength: f32,
    pub top_k_scores: Vec<FactBundlePrototypeScore>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FactBundleCompression {
    pub model: BundleCompressionModel,
    pub cluster_id: CompactString,
    pub canonical_bundle_id: CompactString,
    pub duplicate_of_bundle_id: Option<CompactString>,
    pub outlier_score: f32,
    pub neighbor_count: u16,
    pub semantic_rank: u16,
    pub rerank_score: Option<f32>,
    pub rerank_source: Option<BundleRerankSource>,
    pub signals: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphAtom {
    pub id: CompactString,
    pub kind: GraphAtomKind,
    pub source_id: CompactString,
    pub label: CompactString,
    pub note_id: Option<CompactString>,
    pub chunk_id: Option<CompactString>,
    pub entity_id: Option<EntityId>,
    pub evidence_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidenceAnchor {
    pub id: CompactString,
    pub kind: EvidenceKind,
    pub note_id: Option<CompactString>,
    pub chunk_id: Option<CompactString>,
    pub source_range: Option<TextRange>,
    pub source_id: CompactString,
    pub confidence: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RelationFact {
    pub id: CompactString,
    pub lane: FactLane,
    pub predicate: CompactString,
    pub source_record_id: CompactString,
    pub status: CompactString,
    pub evidence_ids: Vec<CompactString>,
    pub confidence: f32,
    #[serde(default)]
    pub semantic_situation_id: Option<CompactString>,
    #[serde(default)]
    pub semantic_frame: Option<CompactString>,
    #[serde(default)]
    pub factuality: Option<CompactString>,
    #[serde(default)]
    pub state_interval_ids: Vec<CompactString>,
    #[serde(default)]
    pub event_ordering_ids: Vec<CompactString>,
    #[serde(default)]
    pub temporal_conflict_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FactBundle {
    pub id: CompactString,
    pub lane: FactLane,
    pub bundle_kind: EvidenceBundleKind,
    pub group_key: CompactString,
    pub predicate: CompactString,
    pub source_record_id: CompactString,
    pub status: CompactString,
    pub evidence_ids: Vec<CompactString>,
    pub confidence: f32,
    pub compression: Option<FactBundleCompression>,
    pub commitment: Option<FactBundleCommitment>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FactRole {
    pub fact_id: CompactString,
    pub role: CompactString,
    pub atom_id: CompactString,
    pub confidence: f32,
    #[serde(default)]
    pub semantic_role: Option<CompactString>,
    #[serde(default)]
    pub slot_type: Option<CompactString>,
    #[serde(default)]
    pub required: Option<bool>,
    #[serde(default)]
    pub resolved: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectedGraphEdge {
    pub id: CompactString,
    pub source_id: CompactString,
    pub target_id: CompactString,
    pub edge_type: CompactString,
    pub projection_kind: CompactString,
    pub source_fact_id: Option<CompactString>,
    pub source_bundle_id: Option<CompactString>,
    pub confidence: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCompileCounters {
    pub atoms: usize,
    pub evidence_anchors: usize,
    pub bundles: usize,
    pub facts: usize,
    pub roles: usize,
    pub projected_edges: usize,
    pub invariant_failures: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphRootReceipt {
    pub lane: FactLane,
    pub atoms: usize,
    pub evidence_anchors: usize,
    pub bundles: usize,
    pub facts: usize,
    pub roles: usize,
    pub projected_edges: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCompileReceipts {
    pub roots: Vec<GraphRootReceipt>,
    pub counters: GraphCompileCounters,
    pub invariant_failures: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCompilerOutput {
    pub schema_version: CompactString,
    pub scope_kind: GraphScopeKind,
    pub scope_id: CompactString,
    pub built_at: u64,
    pub atoms: Vec<GraphAtom>,
    pub evidence_anchors: Vec<EvidenceAnchor>,
    pub bundles: Vec<FactBundle>,
    pub facts: Vec<RelationFact>,
    pub roles: Vec<FactRole>,
    pub projected_edges: Vec<ProjectedGraphEdge>,
    pub receipts: GraphCompileReceipts,
}

pub struct GraphCompilerInput<'a> {
    pub scope_kind: GraphScopeKind,
    pub scope_id: &'a str,
    pub built_at: u64,
    pub note_ids: &'a [CompactString],
    pub chunks: &'a [GraphChunk],
    pub surface_hits: &'a [SurfaceHit],
    pub mentions: &'a [GraphMention],
    pub mention_graph: Option<&'a LensMentionGraph>,
    pub lens_frames: &'a [LensChunk],
    pub entity_anchors: &'a [GraphAnchor],
    pub nodes: &'a [GraphNode],
    pub relationships: &'a [GraphRelationship],
    pub events: &'a [GraphEvent],
    pub temporal_edges: &'a [GraphTemporalEdge],
    pub causal_edges: &'a [GraphTemporalEdge],
    pub memory_state: &'a [GraphMemoryState],
    pub calendar_registry: Option<&'a GraphCalendarRegistryBridgeSummary>,
    pub document_sidecar: Option<&'a crate::types::GraphDocumentSidecarSummary>,
    pub document_compiler: Option<&'a crate::types::GraphDocumentCompilerSummary>,
    pub legacy_edges: &'a [GraphEdge],
    pub bundle_compression: Option<&'a BundleCompressionInput<'a>>,
    pub bundle_commitment: Option<&'a BundleCommitmentInput<'a>>,
}
