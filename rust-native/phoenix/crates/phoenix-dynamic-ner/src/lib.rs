//! Phoenix Dynamic NER — Surface Intelligence Layer
//!
//! A mention compiler that produces high-quality mention evidence through
//! four lanes: known surface (Alex), native discovery, dynamic model, and
//! adjudication. NER creates mention evidence; entity identity is a later
//! graph problem.

mod alias_resolution;
#[cfg(test)]
mod alias_resolution_tests;
mod engine;
mod graph;
mod hints;
mod identity_resolution;
#[cfg(test)]
mod identity_resolution_tests;
#[cfg(all(feature = "jina-router", not(target_arch = "wasm32")))]
mod jina_router;
mod known_lane;
mod label_catalog;
#[cfg(test)]
mod label_catalog_tests;
mod native_lane;
mod router;
mod schema;
mod scoring;
mod semantic_router;
mod surface_memory;
mod traits;
mod types;

pub use alias_resolution::{
    resolve_aliases, AliasRegistryEntity, AliasResolutionInput, AliasResolutionReport,
};
pub use engine::{
    NerError, PhoenixNerEngine, PhoenixNerEngineBuilder, SurfaceNerInput, SurfaceNerMetrics,
    SurfaceNerOutput,
};
pub use graph::{MentionEdge, MentionEdgeKind, MentionGraph, MentionGraphBuilder};
pub use hints::{ChunkHint, ChunkHintKind, ChunkHintSource};
pub use identity_resolution::{
    resolve_identity_dag, IdentityEdge, IdentityEdgeKind, IdentityLinkerCandidate, IdentityNode,
    IdentityNodeKind, IdentityResolutionDag, IdentityResolutionInput,
};
#[cfg(all(feature = "jina-router", not(target_arch = "wasm32")))]
pub use jina_router::{JinaRouterOptions, JinaSemanticLabelRouter};
pub use known_lane::KnownSurfaceLane;
pub use label_catalog::{
    canonical_label, confusion_group, domain_pack, label_compatibility, label_description,
    label_family, label_spec, labels_are_confusable, labels_for_domain, negative_labels_for_domain,
    push_domain_labels, push_labels, push_unique_label, ConfusionGroup, DomainLabelPack,
    KindCompatibility, LabelFamily, LabelSpec, LABEL_ONTOLOGY_VERSION, ROUTABLE_LABELS,
    UNIVERSAL_CORE,
};
pub use native_lane::NativeDiscoveryLane;
pub use router::SurfaceRouter;
pub use schema::DynamicSchemaBuilder;
pub use scoring::{MentionWorkspace, ScoreTable};
pub use semantic_router::{
    LexicalSemanticLabelRouter, SemanticLabelRouter, SemanticRouteHint, SemanticRouteInput,
};
pub use surface_memory::{
    SurfaceCandidateEdge, SurfaceCandidateKind, SurfaceCandidateTarget, SurfaceMemoryEntry,
    SurfaceMemoryReport,
};
pub use traits::{
    AdjudicationCase, AdjudicationDecision, AdjudicationError, DecisionKind, DiscoveredSpan,
    DynamicNerModel, InstructTask, MentionAdjudicator, Modality, ModelNerRequest, ModelNerWindow,
    NerModelError, Polarity, VerificationCase,
};
pub use types::{
    DomainProfile, EntityLabel, LabelBankContext, LabelBankSource, LabelPack, LocalMentionId,
    MentionContext, MentionKind, MentionPacket, MentionSemantics, MentionSourceKind, MentionStatus,
    MentionSyntax, MentionVote, NerNeedVector, NerRoute, VoteReason,
};
