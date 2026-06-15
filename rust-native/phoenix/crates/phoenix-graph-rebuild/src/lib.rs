//! Clean Phoenix graph rebuild spine.
//!
//! This crate owns the explicit graph snapshot contract between trusted Alex
//! identity, text chunks, accepted anchors, graph facts, embedding targets, and
//! projection consumers. It does not call the legacy staged orchestrator.

mod adjudication;
mod atlas_packet;
mod builder;
mod compiler;
mod embedding;
mod facts;
mod semantic;
#[cfg(test)]
mod tests;
mod types;

pub use atlas_packet::{
    build_atlas_packet, AtlasFamilyCount, AtlasObject, AtlasObjectStatus, AtlasPacket,
    AtlasPacketCounters, AtlasSourceContract, AtlasVectorStatus, GraphFamily, ManifoldAdmission,
    ManifoldTarget,
};
pub use builder::{
    build_graph_rebuild_snapshot, GraphRebuildBuilder, GraphRebuildError, GraphRebuildInput,
};
pub use compiler::{
    assert_graph_compile_invariants, compile_dual_write_snapshot, compile_graph_snapshot,
    compile_legacy_snapshot, compile_legacy_snapshot_strict, project_ui_edges,
    verify_graph_compile_output, BundleCommitmentInput, BundleCommitmentPoint,
    BundleCommitmentPolicy, BundleCompressionInput, BundleCompressionModel,
    BundleCompressionPolicy, BundleEmbedding, BundlePrototype, BundleRerankScore,
    BundleRerankSource, EvidenceAnchor, EvidenceBundleKind, EvidenceKind, FactBundle,
    FactBundleCommitment, FactBundleCompression, FactBundlePrototypeScore, FactLane, FactRole,
    GraphAtom, GraphAtomKind, GraphCompileCounters, GraphCompileReceipts, GraphCompilerDualWrite,
    GraphCompilerError, GraphCompilerInput, GraphCompilerOutput, GraphPrototypeFamily,
    GraphRootReceipt, ProjectedGraphEdge, RelationFact,
};
pub use embedding::build_snapshot_embedding_targets;
pub use phoenix_chunker_native::{
    build_chunks, classify_document_profiles, Chunk, ChunkerConfig, DocumentProfileRequest,
    DocumentProfileSummary,
};
pub use semantic::{
    build_document_semantic_summary, DocumentSemanticArgument, DocumentSemanticAttributionFrame,
    DocumentSemanticConditionalFrame, DocumentSemanticCounters, DocumentSemanticDocument,
    DocumentSemanticEntity, DocumentSemanticEventOrdering, DocumentSemanticFactualityEnvelope,
    DocumentSemanticFrame, DocumentSemanticInput, DocumentSemanticProposition,
    DocumentSemanticRecoveredArgument, DocumentSemanticRequest, DocumentSemanticScope,
    DocumentSemanticSituationInstance, DocumentSemanticSpeechOrBeliefFrame,
    DocumentSemanticStateInterval, DocumentSemanticSummary, DocumentSemanticTemporalConflict,
};
pub use types::{
    GraphAnchor, GraphCalendarRegistryBridgeCounters, GraphCalendarRegistryBridgeSummary,
    GraphCalendarRegistryReceipt, GraphChunk, GraphCounters, GraphDocumentCompilerHyperedge,
    GraphDocumentCompilerHyperedgeRole, GraphDocumentCompilerSummary, GraphDocumentConfidence,
    GraphDocumentEvidenceSpan, GraphDocumentReviewRow, GraphDocumentReviewSummary,
    GraphDocumentSidecarSummary, GraphDocumentUnitSummary, GraphDropReasons, GraphEdge,
    GraphEmbeddingTarget, GraphEpisode, GraphEvent, GraphMemoryState, GraphMention, GraphNode,
    GraphProjectionRef, GraphRebuildSnapshot, GraphRelationship, GraphScopeKind, GraphTemporalEdge,
};
