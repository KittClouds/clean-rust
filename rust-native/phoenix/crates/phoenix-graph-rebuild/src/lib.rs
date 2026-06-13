//! Clean Phoenix graph rebuild spine.
//!
//! This crate owns the explicit graph snapshot contract between trusted Alex
//! identity, text chunks, accepted anchors, graph facts, embedding targets, and
//! projection consumers. It does not call the legacy staged orchestrator.

mod adjudication;
mod builder;
mod compiler;
mod embedding;
mod facts;
#[cfg(test)]
mod tests;
mod types;

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
pub use phoenix_chunker_native::{
    build_chunks, classify_document_profiles, Chunk, ChunkerConfig, DocumentProfileRequest,
    DocumentProfileSummary,
};
pub use types::{
    GraphAnchor, GraphCalendarRegistryBridgeCounters, GraphCalendarRegistryBridgeSummary,
    GraphCalendarRegistryReceipt, GraphChunk, GraphCounters, GraphDropReasons, GraphEdge,
    GraphEmbeddingTarget, GraphEpisode, GraphEvent, GraphMemoryState, GraphMention, GraphNode,
    GraphProjectionRef, GraphRebuildSnapshot, GraphRelationship, GraphScopeKind, GraphTemporalEdge,
};
