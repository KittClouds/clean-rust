use phoenix_types::{
    AtlasIdentityReceiptSummary, AtlasIdentityResolutionSummary, EntityId, EntityKind,
};
use smallvec::SmallVec;

use crate::alias_resolution::{AliasRegistryEntity, AliasResolutionReport};
use crate::graph::MentionGraph;
use crate::surface_memory::SurfaceMemoryReport;
use crate::types::{LocalMentionId, MentionPacket};

pub struct IdentityResolutionInput<'a> {
    pub document_id: &'a str,
    pub mentions: &'a [MentionPacket],
    pub mention_graph: &'a MentionGraph,
    pub surface_memory: &'a SurfaceMemoryReport,
    pub alias_report: Option<&'a AliasResolutionReport>,
    pub registry_entities: &'a [AliasRegistryEntity],
    pub linker_candidates: &'a [IdentityLinkerCandidate],
}

#[derive(Clone, Debug, PartialEq)]
pub struct IdentityLinkerCandidate {
    pub mention_id: LocalMentionId,
    pub entity_id: EntityId,
    pub canonical_name: String,
    pub kind: Option<EntityKind>,
    pub score: f32,
    pub evidence_note: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IdentityResolutionDag {
    pub nodes: Vec<IdentityNode>,
    pub edges: Vec<IdentityEdge>,
    pub receipts: Vec<AtlasIdentityReceiptSummary>,
    pub summary: AtlasIdentityResolutionSummary,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IdentityNodeKind {
    Mention,
    KnownEntity,
    RunLocalEntity,
    DeferredCase,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IdentityNode {
    pub node_id: String,
    pub kind: IdentityNodeKind,
    pub label: String,
    pub entity_kind: Option<EntityKind>,
    pub mention_ids: SmallVec<[u64; 4]>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IdentityEdgeKind {
    KnownReference,
    AliasProposal,
    SurfaceMemory,
    SameSurfaceCluster,
    MentionGraph,
    LinkerCandidate,
    DocumentCoreference,
    Conflict,
}

#[derive(Clone, Debug, PartialEq)]
pub struct IdentityEdge {
    pub left: String,
    pub right: String,
    pub kind: IdentityEdgeKind,
    pub weight: f32,
    pub evidence_refs: SmallVec<[String; 2]>,
}
