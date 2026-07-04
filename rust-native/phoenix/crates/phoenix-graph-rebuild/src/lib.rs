//! Clean Phoenix graph rebuild spine.
//!
//! This crate owns the explicit graph snapshot contract between trusted Alex
//! identity, text chunks, accepted anchors, graph facts, embedding targets, and
//! projection consumers. It does not call the legacy staged orchestrator.

mod adjudication;
mod atlas_packet;
mod builder;
mod chunk_semantic_bridge;
mod compiler;
mod embedding;
mod episode_projection;
#[cfg(test)]
mod fact_extraction_tests;
mod facts;
mod memory_governance;
mod memory_governance_adversarial;
#[cfg(test)]
mod memory_governance_adversarial_tests;
#[cfg(test)]
mod negative_relation_tests;
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
pub use chunk_semantic_bridge::{
    assert_chunk_semantic_bridge_candidate_only, audit_chunk_semantic_bridge_quality_gate,
    bridge_quality_gate_decision, build_chunk_semantic_bridge_candidates,
    build_chunk_semantic_bridge_candidates_from_snapshot,
    build_chunk_semantic_bridge_shortrun_parity_report, is_same_entity_only_bridge_suspect,
    promote_chunk_semantic_bridge_candidates, BridgeCandidateOnlyAudit, BridgeCounts,
    BridgeQualityGateAudit, BridgeQualityGateDecision, BridgeRepresentativeRow,
    BridgeShortrunParityComparison, BridgeShortrunParityReport, BridgeTimingReport,
    ChunkSemanticBridgeCandidate, ChunkSemanticBridgeChunk, ChunkSemanticBridgeCommitPolicy,
    ChunkSemanticBridgeEngineInput, ChunkSemanticBridgeEntity, ChunkSemanticBridgeEvent,
    ChunkSemanticBridgeEventEdge, ChunkSemanticBridgeEvidence, ChunkSemanticBridgePromotionAudit,
    ChunkSemanticBridgePromotionChunk, ChunkSemanticBridgePromotionCommitPolicy,
    ChunkSemanticBridgePromotionInput, ChunkSemanticBridgePromotionOutput,
    ChunkSemanticBridgePromotionProposal, ChunkSemanticBridgePromotionRejection,
    ChunkSemanticBridgePromotionStatus, ChunkSemanticBridgeSnapshotDocument,
    ChunkSemanticBridgeStatus, ChunkSemanticBridgeType, CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
    CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT, CHUNK_SEMANTIC_BRIDGE_PROMOTION_COMMIT_POLICY,
    CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT,
    CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION, CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
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
pub use embedding::{
    build_snapshot_embedding_target_report, build_snapshot_embedding_targets,
    GraphEmbeddingTargetBuild, GraphEmbeddingTargetOriginCount,
};
pub use memory_governance::{
    assert_memory_governance_candidate_only, build_memory_governance_candidates,
    build_memory_governance_candidates_from_snapshot, build_memory_governance_retrieval_preview,
    build_memory_governance_retrieval_preview_with_policy,
    build_memory_governance_retrieval_weighting_experiment,
    build_memory_governance_shortrun_golden_report, MemoryGovernanceCandidateOnlyAudit,
    MemoryGovernanceConfidenceSummary, MemoryGovernanceCounts, MemoryGovernanceEngineInput,
    MemoryGovernancePerformanceBudget, MemoryGovernanceRepresentativeRow,
    MemoryGovernanceRetrievalCandidate, MemoryGovernanceRetrievalPreview,
    MemoryGovernanceRetrievalPreviewInput, MemoryGovernanceRetrievalPreviewRow,
    MemoryGovernanceRetrievalPreviewSummary, MemoryGovernanceRetrievalWeightPolicy,
    MemoryGovernanceRetrievalWeightingExperiment, MemoryGovernanceRetrievalWeightingVariant,
    MemoryGovernanceShortrunComparison, MemoryGovernanceShortrunGoldenReport,
    MemoryGovernanceTimingReport, MEMORY_GOVERNANCE_COMMIT_POLICY,
    MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT, MEMORY_GOVERNANCE_RETRIEVAL_PREVIEW_SCHEMA_VERSION,
    MEMORY_GOVERNANCE_RETRIEVAL_WEIGHTING_EXPERIMENT_SCHEMA_VERSION,
    MEMORY_GOVERNANCE_SCHEMA_VERSION,
};
pub use memory_governance_adversarial::{
    build_memory_governance_adversarial_certificate, MemoryGovernanceAdversarialCandidateRow,
    MemoryGovernanceAdversarialCertificate, MemoryGovernanceAdversarialCheck,
    MemoryGovernanceAdversarialFixtureResult, MemoryGovernanceAdversarialNegativeRelationRow,
    MemoryGovernanceAdversarialNoTopologyProof, MemoryGovernanceAdversarialRetrievalRow,
    MemoryGovernanceAdversarialTiming, MEMORY_GOVERNANCE_ADVERSARIAL_CERTIFICATE_SCHEMA_VERSION,
};
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
    GraphEmbeddingTarget, GraphEpisode, GraphEpisodeProjectionEdge, GraphEvent,
    GraphMemoryGovernanceAction, GraphMemoryGovernanceCandidate, GraphMemoryGovernanceCommitPolicy,
    GraphMemoryGovernanceSignals, GraphMemoryGovernanceStatus, GraphMemoryGovernanceTargetKind,
    GraphMemoryState, GraphMention, GraphNode, GraphProjectionRef, GraphRebuildSnapshot,
    GraphRelationship, GraphScopeKind, GraphTemporalEdge,
};
