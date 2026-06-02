//! Desktop workspace bridge for the canonical dynamic NER engine.

#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/alias_resolution.rs"]
mod alias_resolution;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/engine.rs"]
mod engine;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/graph.rs"]
mod graph;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/hints.rs"]
mod hints;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/identity_resolution.rs"]
mod identity_resolution;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/known_lane.rs"]
mod known_lane;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/label_catalog.rs"]
mod label_catalog;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/native_lane.rs"]
mod native_lane;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/router.rs"]
mod router;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/schema.rs"]
mod schema;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/scoring.rs"]
mod scoring;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/semantic_router.rs"]
mod semantic_router;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/surface_memory.rs"]
mod surface_memory;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/traits.rs"]
mod traits;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-dynamic-ner/src/types.rs"]
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
