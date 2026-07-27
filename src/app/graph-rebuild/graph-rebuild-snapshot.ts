import type { EntityOccurrence } from '../lib/dexie/db';
import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
import type { RegisteredEntity } from '../lib/registry';
import type {
    GraphCompileReceipts,
    GraphCompilerDualWriteSidecar,
    GraphCompilerOutput,
    GraphCompilerProjectedUiEdge,
    GraphCompilerSource,
} from './graph-compiler-read-model';
import type { GraphModelV2Snapshot } from './graph-model-v2';
import type { GraphCalendarRegistryBridgeSummary } from './graph-calendar-registry-bridge';
import type { GraphMemoryGraphRagBridgeSummary } from './graph-memory-graphrag-bridge';
import type { GraphCrossDocumentBridgeRunCertificate } from './graph-cross-document-bridge-certificate';
import type { GraphDiscourseSpineSummary } from './graph-discourse-spine';
import type { GraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';
import type { GraphDiscourseBridgeAdjudicationSummary } from './graph-discourse-bridge-adjudication';
import type { GraphDiscourseEvalLedgerSummary } from './graph-discourse-eval-ledger';
import type { GraphDiscoursePromotionSurfaceSummary } from './graph-discourse-promotion-surface';
import type { GraphDiscourseCompilerOverlaySummary } from './graph-discourse-compiler-overlay';
import type { HopfResonanceSpace } from './graph-hopf-resonance-space';
import type { GraphDocumentSidecarSummary } from './graph-document-sidecar';
import type { GraphDocumentProfileSummary } from './graph-document-profile';
import type { GraphDocumentSemanticSummary } from './graph-document-semantic';
import type { GraphDocumentReviewSummary } from './graph-document-review';
import type { GraphDocumentCompilerSummary } from './graph-document-compiler';
import type { GraphDocumentGraphMutationLedger } from './graph-document-durable-commit';
import type { GraphOperatorMutationJournal } from './graph-operator-mutation-journal';
import type { GraphTruthCommitLedger } from './graph-truth-commit-ledger';
import type { GraphAtlasPacket } from './graph-atlas-packet';
import type { GraphRebuildBuildTimings } from './graph-rebuild-build-timings';
import type { GraphRebuildCpuProfiler } from './graph-rebuild-cpu-profile';
import type { GraphPromotionVerdictCertificate } from './graph-promotion-verdict';
import type { GraphReviewAdjudicationRunCertificate } from './graph-review-adjudication-certificate';
import type { GraphStoryContinuityContract } from './graph-story-continuity';
import type { GraphRebuildReplayManifest } from './graph-rebuild-replay-contract';

export type GraphRebuildScopeKind = 'global' | 'folder' | 'narrative' | 'note' | 'multiNote';
export type GraphRebuildAnchorSource = EntityOccurrence['source'] | 'accepted_suggestion';
export type GraphRebuildEdgeType = string;
export type GraphRebuildEmbeddingTargetKind = string;
export type GraphRebuildAdjudicationStatus = 'accepted' | 'review' | 'rejected';
export type GraphRebuildChunkRole =
    | 'dialogue'
    | 'scene_action'
    | 'exposition_packet'
    | 'authority_chain'
    | 'evidence_block'
    | 'transition'
    | 'mixed';

export interface GraphRebuildChunkEntityPrior {
    surface: string;
    likelyKinds: string[];
    reason: string;
    confidence: number;
}

export interface GraphRebuildMeaningFrame {
    role: GraphRebuildChunkRole;
    splitReason: string;
    breakPressure: number;
    mergePressure: number;
    entityPriors: GraphRebuildChunkEntityPrior[];
    eventCues: string[];
    modalCues: string[];
    temporalCues: string[];
    authorityCues: string[];
    evidenceCues: string[];
    carryoverIn: string[];
    carryoverOut: string[];
}

export interface GraphRebuildChunk {
    id: string;
    noteId: string;
    start: number;
    end: number;
    ordinal: number;
    source: 'dynamic-chunking' | 'note-block' | 'note-fallback' | 'anchor-derived';
    textHash?: string;
    role?: GraphRebuildChunkRole;
    splitReason?: string;
    meaningFrame?: GraphRebuildMeaningFrame;
}

export interface GraphRebuildMention {
    id: string;
    noteId: string;
    chunkId?: string;
    surface: string;
    sourceStart: number;
    sourceEnd: number;
    source: GraphRebuildAnchorSource;
    confidence: number;
    entityId?: string;
    status: 'candidate' | 'accepted' | 'dropped';
}

export interface GraphRebuildEntityAnchor extends GraphRebuildMention {
    entityId: string;
    status: 'accepted';
    generation: number;
}

export interface GraphRebuildNode {
    id: string;
    entityId: string;
    label: string;
    kind: string;
    aliases: string[];
    anchorIds: string[];
    noteIds: string[];
    totalMentions: number;
}

export interface GraphRebuildEdge {
    id: string;
    sourceId: string;
    targetId: string;
    type: GraphRebuildEdgeType;
    weight: number;
    confidence: number;
    evidenceAnchorIds: string[];
    scopeKeys: string[];
    noteIds: string[];
}

export interface GraphRebuildRelationship {
    id: string;
    sourceEntityId: string;
    targetEntityId: string;
    relationType: string;
    evidenceAnchorIds: string[];
    confidence: number;
    status: GraphRebuildAdjudicationStatus;
    adjudicationSource: string;
    adjudicationScore: number;
    rationale: string;
    decisionEvidence: string[];
}

export interface GraphRebuildRelationshipHint {
    sourceId: string;
    targetId: string;
    relationType?: string;
    status: GraphRebuildAdjudicationStatus;
    confidence: number;
    source: string;
    evidence?: string[];
}

export type GraphRebuildEventAspectKind =
    | 'state'
    | 'activity'
    | 'process'
    | 'performance'
    | 'endeavor'
    | 'habitual'
    | 'transition';

export type GraphRebuildEventCompletion =
    | 'completed'
    | 'ongoing'
    | 'planned'
    | 'attempted'
    | 'reported'
    | 'hypothetical'
    | 'unknown';

export interface GraphRebuildEventAspect {
    kind: GraphRebuildEventAspectKind;
    completion: GraphRebuildEventCompletion;
    confidence: number;
    cues: string[];
    rationale: string;
}

export interface GraphRebuildEvent {
    id: string;
    noteId: string;
    chunkId?: string;
    label: string;
    entityIds: string[];
    evidenceAnchorIds: string[];
    confidence: number;
    aspect?: GraphRebuildEventAspect;
}

export interface GraphRebuildEpisode {
    id: string;
    noteId: string;
    eventIds: string[];
    entityIds: string[];
    label: string;
}

export type GraphRebuildChunkSemanticBridgeType =
    | 'setup_payoff'
    | 'cause_effect'
    | 'state_delta'
    | 'relationship_delta'
    | 'topic_continuation'
    | 'evidence_reframe'
    | 'motif_echo'
    | 'route_continuity';

export const GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION = 'phoenix-chunk-semantic-bridge/v1' as const;
export const GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY = 'no_topology_commit' as const;
export const GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT =
    'chunk_semantic_bridge_candidate:no_topology_commit' as const;

export type GraphRebuildChunkSemanticBridgeSchemaVersion =
    typeof GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION;

export type GraphRebuildChunkSemanticBridgeCommitPolicy =
    typeof GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY;

export type GraphRebuildChunkSemanticBridgeStatus =
    | 'candidate'
    | 'overlay_only';

export interface GraphRebuildChunkSemanticBridge {
    schemaVersion: GraphRebuildChunkSemanticBridgeSchemaVersion;
    id: string;
    bridgeType: GraphRebuildChunkSemanticBridgeType;
    sourceChunkId: string;
    targetChunkId: string;
    sourceEventId?: string;
    targetEventId?: string;
    sourceEpisodeId?: string;
    targetEpisodeId?: string;
    claim: string;
    evidenceIds: string[];
    supportingEntityIds: string[];
    confidence: number;
    status: GraphRebuildChunkSemanticBridgeStatus;
    commitPolicy: GraphRebuildChunkSemanticBridgeCommitPolicy;
    semanticVerbs: string[];
    sourceCue?: string;
    targetCue?: string;
    rationale: string[];
}

export type GraphRebuildEpisodeConnectionKind =
    | 'episode_temporal'
    | 'episode_causal'
    | 'episode_wormhole';

export type GraphRebuildEpisodeConnectionStatus =
    | 'derived'
    | 'overlay_only';

export interface GraphRebuildEpisodeConnection {
    id: string;
    kind: GraphRebuildEpisodeConnectionKind;
    sourceEpisodeId: string;
    targetEpisodeId: string;
    relationType: string;
    eventEdgeIds: string[];
    chunkBridgeIds?: string[];
    bridgeType?: GraphRebuildChunkSemanticBridgeType;
    claim?: string;
    evidenceIds: string[];
    sharedEntityIds: string[];
    confidence: number;
    status: GraphRebuildEpisodeConnectionStatus;
    semanticVerbs?: string[];
    rationale: string[];
}

export type GraphRebuildEpisodeProjectionEdgeKind =
    | 'document_contains_episode'
    | 'episode_contains_event'
    | 'episode_contains_chunk'
    | 'episode_temporal'
    | 'episode_causal'
    | 'episode_wormhole_candidate';

export type GraphRebuildEpisodeProjectionEdgeStatus =
    | 'structural'
    | 'derived'
    | 'candidate_overlay';

export interface GraphRebuildEpisodeProjectionEdge {
    schemaVersion: 'phoenix-episode-projection-edge/v1';
    id: string;
    kind: GraphRebuildEpisodeProjectionEdgeKind;
    sourceId: string;
    targetId: string;
    sourceTargetId: string;
    targetTargetId: string;
    noteId?: string;
    episodeId?: string;
    sourceEpisodeId?: string;
    targetEpisodeId?: string;
    eventId?: string;
    chunkId?: string;
    episodeConnectionId?: string;
    relationType: string;
    evidenceIds: string[];
    confidence: number;
    status: GraphRebuildEpisodeProjectionEdgeStatus;
    noTopologyCommit: true;
    rationale: string[];
}

export const GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION = 'phoenix-memory-governance-candidate/v1' as const;
export const GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY = 'no_topology_commit' as const;
export const GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT =
    'memory_governance_candidate:no_topology_commit' as const;

export type GraphMemoryGovernanceTargetKind = 'chunk' | 'episode';

export type GraphMemoryGovernanceAction =
    | 'retain'
    | 'attenuate'
    | 'compress'
    | 'quarantine'
    | 'retire';

export type GraphMemoryGovernanceStatus = 'candidate';

export interface GraphMemoryGovernanceSignals {
    age: number;
    accessFrequency: number;
    redundancy: number;
    contradictionRisk: number;
    causalImportance: number;
    narrativeSalience: number;
    retrievalUtility: number;
    evidenceStrength: number;
    userPinned: boolean;
}

export interface GraphMemoryGovernanceCandidate {
    schemaVersion: typeof GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION;
    id: string;
    targetId: string;
    targetKind: GraphMemoryGovernanceTargetKind;
    action: GraphMemoryGovernanceAction;
    reason: string;
    evidenceIds: string[];
    supportingEntityIds: string[];
    relatedEventIds: string[];
    relatedChunkIds: string[];
    signals: GraphMemoryGovernanceSignals;
    confidence: number;
    status: GraphMemoryGovernanceStatus;
    commitPolicy: typeof GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY;
    noTopologyCommit: true;
    rationale: string[];
}

export const GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION =
    'phoenix-memory-governance-retrieval-weighting-experiment/v1' as const;

export interface GraphMemoryGovernanceRetrievalCandidate {
    id: string;
    targetId: string;
    targetKind: GraphMemoryGovernanceTargetKind;
    score: number;
}

export interface GraphMemoryGovernanceRetrievalPreviewSummary {
    candidateCount: number;
    governedCount: number;
    retainedCount: number;
    attenuatedCount: number;
    compressedCount: number;
    unchangedCount: number;
    changedRankCount: number;
    promotedCount: number;
    demotedCount: number;
}

export interface GraphMemoryGovernanceRetrievalWeightPolicy {
    id: string;
    retainConfidenceBoost: number;
    retainCausalBoost: number;
    retainRetrievalBoost: number;
    compressConfidenceBoost: number;
    compressNarrativeBoost: number;
    compressMaxBoost: number;
    compressScoreCeiling: number;
    compressFanoutDampening: number;
    attenuateConfidencePenalty: number;
    quarantineMultiplier: number;
    retireMultiplier: number;
}

export interface GraphMemoryGovernanceRetrievalPreviewRow {
    id: string;
    targetId: string;
    targetKind: GraphMemoryGovernanceTargetKind;
    originalRank: number;
    adjustedRank: number;
    originalScore: number;
    adjustedScore: number;
    scoreDelta: number;
    governanceCandidateId?: string;
    governanceAction?: GraphMemoryGovernanceAction;
    governanceConfidence?: number;
    reason?: string;
    rationale: string[];
    noTopologyCommit: true;
}

export interface GraphMemoryGovernanceRetrievalFullRowProof {
    rowCount: number;
    noTopologyRows: number;
    compressionDominance: GraphMemoryGovernanceCompressionDominanceProof;
}

export interface GraphMemoryGovernanceCompressionDominanceProof {
    passed: boolean;
    compressedRows: number;
    policyRows: number;
    boundedRows: number;
    maxPositiveDelta: number;
    maxAdjustedScore: number;
    violationCount: number;
    violations: string[];
}

export interface GraphMemoryGovernanceRetrievalWeightingVariant {
    policy: GraphMemoryGovernanceRetrievalWeightPolicy;
    summary: GraphMemoryGovernanceRetrievalPreviewSummary;
    fullRowProof?: GraphMemoryGovernanceRetrievalFullRowProof;
    topRows: GraphMemoryGovernanceRetrievalPreviewRow[];
    meanAbsRankDeltaMillis: number;
    retainedMeanScoreDeltaMillis: number;
    compressedMeanScoreDeltaMillis: number;
    attenuatedMeanScoreDeltaMillis: number;
}

export interface GraphMemoryGovernanceRetrievalWeightingExperiment {
    schemaVersion: typeof GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION;
    baselinePolicyId: string;
    variants: GraphMemoryGovernanceRetrievalWeightingVariant[];
    noTopologyCommit: true;
}

export interface GraphRebuildTemporalEdge {
    id: string;
    sourceId: string;
    targetId: string;
    relationType: string;
    evidenceIds: string[];
    confidence: number;
}

export type GraphRebuildCausalStatus =
    | 'candidate'
    | 'accepted'
    | 'supported'
    | 'contradicted'
    | 'superseded'
    | 'invalidated'
    | 'deferred'
    | 'rejected';

export type GraphRebuildCausalPolarity = 'support' | 'contradict' | 'underspecify' | 'unknown';
export type GraphRebuildCausalSourceKind =
    | 'explicit_link'
    | 'explicit_cue'
    | 'candidate_cue'
    | 'local_temporal_pair'
    | 'graph_support'
    | 'reverse_conflict'
    | 'quote_attribution'
    | 'counterfactual_competition'
    | 'chain_bridge'
    | 'sidecar_review';
export type GraphRebuildCausalEvidenceClass =
    | 'world_support'
    | 'reported_support'
    | 'attributed_support'
    | 'graph_support'
    | 'local_temporal_pair';
export type GraphRebuildCausalSourceSemantics =
    | 'world_assertion'
    | 'reported_speech'
    | 'attributed_claim'
    | 'unknown';
export type GraphRebuildCausalModality =
    | 'asserted'
    | 'conditional'
    | 'planned'
    | 'hypothetical'
    | 'negated'
    | 'unknown';

export interface GraphRebuildCausalEdge extends GraphRebuildTemporalEdge {
    relationKind?: string;
    status: GraphRebuildCausalStatus;
    sourceKind: GraphRebuildCausalSourceKind;
    evidenceClass: GraphRebuildCausalEvidenceClass;
    polarity: GraphRebuildCausalPolarity;
    modality: GraphRebuildCausalModality;
    sourceSemantics: GraphRebuildCausalSourceSemantics;
    cue?: string;
    attributedTo?: string;
    supportIds: string[];
    diagnosticCodes?: string[];
    rationale?: string;
    temporalLegal?: boolean;
    sentenceDistance?: number;
    graphSupportCount?: number;
}

export type GraphRebuildCausalSidecarNodeRef = string | {
    id?: string;
    nodeId?: string;
    semanticNodeId?: string;
    canonicalEventId?: string;
    label?: string;
    kind?: string;
    [key: string]: unknown;
};

export interface GraphRebuildCausalSidecarEdge {
    edgeId?: string;
    caseId?: string;
    documentId?: string;
    source?: GraphRebuildCausalSidecarNodeRef;
    target?: GraphRebuildCausalSidecarNodeRef;
    canonicalCauseEventId?: string | null;
    canonicalEffectEventId?: string | null;
    kind?: string;
    relationKind?: string;
    status?: string;
    confidenceMillis?: number;
    cue?: string | null;
    attributedTo?: string | null;
    polarity?: string;
    evidenceRefs?: string[];
    claimAtomIds?: string[];
    temporalCertaintyMillis?: number;
}

export interface GraphRebuildCausalSidecarReviewCase {
    caseId?: string;
    documentId?: string;
    source?: GraphRebuildCausalSidecarNodeRef;
    target?: GraphRebuildCausalSidecarNodeRef;
    canonicalCauseEventId?: string | null;
    canonicalEffectEventId?: string | null;
    kind?: string;
    relationKind?: string;
    baseConfidenceMillis?: number;
    baseStatus?: string;
    cue?: string | null;
    polarity?: string;
    attributedTo?: string | null;
    sentenceDistance?: number;
    temporalLegal?: boolean;
    quotedEvidence?: boolean;
    attributedEvidence?: boolean;
    quotedOrAttributed?: boolean;
    sourceSemantics?: string;
    modalitySemantics?: string;
    sharedParticipantCount?: number;
    graphSupportCount?: number;
    evidenceRefs?: string[];
    seedSource?: string;
}

export interface GraphRebuildCausalSidecarChain {
    chainId?: string;
    edgeIds?: string[];
    canonicalEventIds?: string[];
    weakestStatus?: string;
    confidenceMillis?: number;
    speculative?: boolean;
    evidenceRefs?: string[];
}

export interface GraphRebuildCausalSidecarInput {
    edgeRecords?: GraphRebuildCausalSidecarEdge[];
    edgeAdditions?: GraphRebuildCausalSidecarEdge[];
    reviewCases?: GraphRebuildCausalSidecarReviewCase[];
    shadowLocalPairCases?: GraphRebuildCausalSidecarReviewCase[];
    chains?: GraphRebuildCausalSidecarChain[];
}

export interface GraphRebuildMemoryState {
    id: string;
    entityId: string;
    noteId?: string;
    key: string;
    value: string;
    evidenceIds: string[];
}

export interface GraphRebuildVisualTrace {
    source: 'rust_atlas_packet' | 'graph_rebuild_embedding_target';
    sourceId: string;
    family: string;
    packetSnapshotId?: string;
    packetScopeId?: string;
    sourceContract?: string;
    vectorContract?: string;
    identityAuthority?: string;
    packetObjectId?: string;
    packetTargetId?: string;
    objectKind?: string;
    targetKind?: string;
    noteIds?: string[];
    chunkIds?: string[];
    evidenceIds?: string[];
}

export interface GraphRebuildEmbeddingTarget {
    id: string;
    kind: GraphRebuildEmbeddingTargetKind;
    sourceId: string;
    noteId?: string;
    chunkId?: string;
    folderId?: string;
    folderLabel?: string;
    folderKind?: string;
    folderParentId?: string;
    entityId?: string;
    entityKind?: string;
    label: string;
    text: string;
    evidenceIds: string[];
    lane?: GraphRebuildSignalTargetLane;
    structuralRole?: GraphRebuildSignalStructuralRole;
    styleKey?: string;
    documentUnitKind?: string;
    stateContextKind?: string;
    atlasFamily?: string;
    atlasStatus?: string;
    admissionTier?: number;
    admissionStatus?: GraphRebuildSignalAdmissionStatus;
    workStatus?: GraphRebuildSignalWorkStatus;
    admissionReason?: string;
    deferReason?: string;
    parentIds?: string[];
    visualTrace?: GraphRebuildVisualTrace;
}

export type GraphRebuildSignalTargetLane =
    | 'document_spine'
    | 'chunk_spine'
    | 'entity_anchor'
    | 'relationship_fact'
    | 'temporal_fact'
    | 'causal_fact'
    | 'memory_state'
    | 'event_identity'
    | 'story_signal'
    | 'cooccurrence_weak'
    | 'entity_linker'
    | 'anchor_evidence'
    | 'unknown';

export type GraphRebuildSignalStructuralRole =
    | 'root'
    | 'spine'
    | 'child'
    | 'fact'
    | 'bridge'
    | 'evidence'
    | 'context'
    | 'deferred';

export type GraphRebuildSignalAdmissionStatus = 'admitted' | 'deferred';

export type GraphRebuildSignalWorkStatus =
    | 'queued'
    | 'deferred_by_scheduler'
    | 'deferred_by_policy';

export interface GraphRebuildSignalTargetLaneReceipt {
    lane: GraphRebuildSignalTargetLane;
    candidates: number;
    admitted: number;
    deferred: number;
    tier: number;
}

export interface GraphRebuildEmbeddingTargetPlan {
    schemaVersion: 'phoenix-signal-target-plan/v1';
    candidateCount: number;
    admittedCount: number;
    deferredCount: number;
    maxAdmitted: number;
    canonicalCount: number;
    queuedCount: number;
    schedulerDeferredCount: number;
    policyDeferredCount: number;
    maxQueued: number;
    queuedTargetIds: string[];
    schedulerDeferredTargetIds: string[];
    policyDeferredTargetIds: string[];
    lanes: GraphRebuildSignalTargetLaneReceipt[];
}

export type GraphEvidenceTargetObjectKind =
    | 'entity'
    | 'relationship'
    | 'event'
    | 'episode'
    | 'temporal_edge'
    | 'causal_edge'
    | 'memory_state';

export interface GraphEvidenceTargetRegistryContract {
    schemaVersion: 'phoenix-evidence-target-registry/v1';
    authority: 'deterministic_graph_processing';
    sourceSnapshotId: string;
    sourceScopeId: string;
    canonicalTargets: number;
    exposedTargets: number;
    chunks: number;
    typedGraphObjects: number;
    supportTargets: number;
    evidenceLinks: number;
    duplicateTargets: number;
    orphanTargets: number;
    identityHash: string;
}

export interface GraphEvidenceTargetRegistryPage {
    schemaVersion: 'phoenix-evidence-target-registry-page/v1';
    sourceSnapshotId: string;
    sourceScopeId: string;
    documentEvidenceIds: string[];
}

export interface GraphRebuildEmbeddingVector {
    targetId: string;
    modelId: string;
    dims: number;
    generation: number;
}

export interface GraphEncoderCandidateNeighbor {
    targetId: string;
    score: number;
    rank: number;
}

export interface GraphEncoderCandidateNeighborhood {
    sourceTargetId: string;
    neighbors: GraphEncoderCandidateNeighbor[];
}

export interface GraphEncoderVectorIndexContract {
    schemaVersion: 'phoenix-encoder-vector-index/v1';
    authority: 'real_encoder';
    sourceSnapshotId: string;
    sourceRegistryHash: string;
    modelId: string;
    modelVersion: string;
    executionProvider: 'native-rust' | 'transformers-worker' | 'external-encoder';
    dimensions: number;
    generation: number;
    vectorCount: number;
    normalized: true;
    metric: 'cosine';
    indexMethod: 'bounded-lsh';
    candidateOnly: true;
    committedTopologyWrites: 0;
    neighborhoodK: number;
    minimumSimilarity: number;
    lshBands: number;
    lshBits: number;
    maxCandidatesPerTarget: number;
    evaluatedPairs: number;
    neighborhoodCount: number;
    neighborCount: number;
    missingRegistryTargets: number;
    rejectedVectors: number;
    indexHash: string;
    neighborhoodHash: string;
}

export type GraphRebuildEmbeddingTaskProfile =
    | 'retrieval'
    | 'semantic_topology'
    | 'multi_task'
    | 'unknown';

export type GraphRebuildEmbeddingNormalization =
    | 'unit_l2'
    | 'none';

export type GraphRebuildEmbeddingTopologySupport =
    | 'none'
    | 'derived'
    | 'native';

export type GraphRebuildEmbeddingVectorHeadKind =
    | 'dense'
    | 'query'
    | 'document'
    | 'topology'
    | 'classification';

export interface GraphRebuildEmbeddingVectorHead {
    id: string;
    kind: GraphRebuildEmbeddingVectorHeadKind;
    dimensions: number;
    normalized: boolean;
    required: boolean;
    purpose: string;
}

export interface GraphRebuildEmbeddingProfile {
    schemaVersion: 'phoenix-embedding-profile/v1';
    modelId: string;
    modelLabel: string;
    modelFamily: string;
    dimensionLabel: string;
    nativeDimensions: number;
    selectedDimensions: number;
    taskProfile: GraphRebuildEmbeddingTaskProfile;
    vectorSource: 'signature-preview' | 'semantic-runner' | 'external';
    normalized: boolean;
    normalization: GraphRebuildEmbeddingNormalization;
    topologySupport: GraphRebuildEmbeddingTopologySupport;
    supportsMultiVector: boolean;
    vectorHeads: GraphRebuildEmbeddingVectorHead[];
}

export interface GraphRebuildEmbeddingModelAdapter {
    schemaVersion: 'phoenix-embedding-model-adapter/v1';
    modelId: string;
    modelLabel: string;
    modelFamily: string;
    dimensionLabel: string;
    nativeDimensions: number;
    selectedDimensions: number;
    taskProfile: GraphRebuildEmbeddingTaskProfile;
    vectorSource: 'semantic-runner' | 'signature-preview' | 'external';
    normalized: boolean;
    normalization: GraphRebuildEmbeddingNormalization;
    topologySupport: GraphRebuildEmbeddingTopologySupport;
    supportsTopology: boolean;
    supportsMultiTask: boolean;
    supportsMultiVector: boolean;
    vectorHeads: GraphRebuildEmbeddingVectorHead[];
}

export interface GraphRebuildProjectionRef {
    targetId: string;
    manifold: 'hybrid' | 'hopf' | 'lorentz' | 'product' | 'siegel' | 'hyperbolic';
    projectionId: string;
}

export type GraphRebuildStructuralNodeRole = 'isolated' | 'leaf' | 'connector' | 'hub' | 'bridge';
export type GraphRebuildStructuralEdgeRole = 'local' | 'backbone' | 'bridge';

export interface GraphRebuildStructuralComponent {
    id: string;
    nodeIds: string[];
    edgeIds: string[];
    size: number;
    density: number;
}

export interface GraphRebuildStructuralNode {
    entityId: string;
    role: GraphRebuildStructuralNodeRole;
    degree: number;
    componentId: string;
}

export interface GraphRebuildStructuralEdge {
    edgeId: string;
    role: GraphRebuildStructuralEdgeRole;
    sourceId: string;
    targetId: string;
    componentId: string;
}

export interface GraphRebuildStructuralPostProcess {
    schemaVersion: 'phoenix-graph-structure/v1';
    components: GraphRebuildStructuralComponent[];
    nodes: GraphRebuildStructuralNode[];
    edges: GraphRebuildStructuralEdge[];
    hubEntityIds: string[];
    bridgeEdgeIds: string[];
}

export type GraphRebuildEmbeddingClusterRole =
    | 'document_region'
    | 'entity_region'
    | 'fact_region'
    | 'event_region'
    | 'mixed_region';

export type GraphRebuildEmbeddingBackboneRole = 'local' | 'backbone' | 'bridge';

export type GraphRebuildProductLaneKind =
    | 'semantic'
    | 'document'
    | 'relation'
    | 'temporal'
    | 'causal'
    | 'evidence'
    | 'entity';

export type GraphRebuildProductTopologyRegionRole =
    | 'core'
    | 'backbone'
    | 'bridge'
    | 'boundary'
    | 'outlier';

export interface GraphRebuildProductLaneFeatures {
    semanticDepth: number;
    documentDepth: number;
    relationDepth: number;
    clusterRadius: number;
    fiberPhase: number;
    confidence: number;
    dominantLane: GraphRebuildProductLaneKind;
    laneWeights: Record<GraphRebuildProductLaneKind, number>;
}

export interface GraphRebuildProductTopologyRegion {
    id: string;
    role: GraphRebuildProductTopologyRegionRole;
    laneKind: GraphRebuildProductLaneKind;
    clusterId: string;
    medoidTargetId: string;
    memberCount: number;
    density: number;
    confidence: number;
    bridgeTargetIds: string[];
    backboneTargetIds: string[];
}

export interface GraphRebuildEmbeddingCluster {
    id: string;
    role: GraphRebuildEmbeddingClusterRole;
    targetIds: string[];
    medoidTargetId: string;
    size: number;
    density: number;
    confidence: number;
    topKinds: string[];
    outlierTargetIds: string[];
}

export interface GraphRebuildEmbeddingTargetPostProcess {
    targetId: string;
    clusterId: string;
    clusterRole: GraphRebuildEmbeddingClusterRole;
    medoidTargetId: string;
    outlierScore: number;
    hubScore: number;
    neighborCount: number;
    productLaneFeatures: GraphRebuildProductLaneFeatures;
    productTopologyRegion: GraphRebuildProductTopologyRegion;
}

export interface GraphRebuildEmbeddingBackboneEdge {
    id: string;
    sourceTargetId: string;
    targetTargetId: string;
    role: GraphRebuildEmbeddingBackboneRole;
    score: number;
    semanticScore: number;
    structuralScore: number;
    reason: string[];
}

export interface GraphRebuildEmbeddingGraphMetrics {
    clusterCount: number;
    singletonCount: number;
    largestClusterSize: number;
    largestClusterRatio: number;
    backboneEdgeCount: number;
    bridgeEdgeCount: number;
    outlierCount: number;
    maxHubScore: number;
    meanNeighborCount: number;
    plannedPairCount?: number;
    theoreticalPairCount?: number;
    prunedPairCount?: number;
}

export interface GraphRebuildEmbeddingGraphPostProcess {
    schemaVersion: 'phoenix-embedding-graph-postprocess/v1';
    profile: GraphRebuildEmbeddingProfile;
    adapter: GraphRebuildEmbeddingModelAdapter;
    targetCount: number;
    vectorDimensions: number;
    clusters: GraphRebuildEmbeddingCluster[];
    productTopologyRegions: GraphRebuildProductTopologyRegion[];
    targets: GraphRebuildEmbeddingTargetPostProcess[];
    backboneEdges: GraphRebuildEmbeddingBackboneEdge[];
    bridgeEdges: GraphRebuildEmbeddingBackboneEdge[];
    outlierTargetIds: string[];
    metrics: GraphRebuildEmbeddingGraphMetrics;
}

export type GraphRebuildLinkSuggestionKind =
    | 'bridge_review'
    | 'hub_affiliation'
    | 'backbone_promotion'
    | 'missing_triangle'
    | 'suspicious_leaf';

export interface GraphRebuildLinkSuggestion {
    id: string;
    kind: GraphRebuildLinkSuggestionKind;
    sourceEntityId: string;
    targetEntityId: string;
    suggestedRelationType: string;
    status: 'review' | 'confirmed';
    confidence: number;
    rerankScore?: number;
    semanticStatus: GraphRebuildAdjudicationStatus | 'none';
    structuralRole: GraphRebuildStructuralEdgeRole | GraphRebuildStructuralNodeRole | 'shared_component';
    embeddingRole?: GraphRebuildEmbeddingBackboneRole | 'same_cluster' | 'cross_cluster' | 'outlier';
    productRegionRole?: GraphRebuildProductTopologyRegionRole | 'cross_region';
    productLane?: GraphRebuildProductLaneKind | 'mixed';
    rerankSignals?: string[];
    rationale: string[];
    evidenceIds: string[];
}

export type GraphRebuildEntityLinkDecision =
    | 'same_entity'
    | 'alias_of'
    | 'new_entity'
    | 'ambiguous'
    | 'reject';

export interface GraphRebuildEntityLinkSuggestion {
    id: string;
    mentionId?: string;
    surface: string;
    normalizedSurface: string;
    noteId?: string;
    chunkId?: string;
    sourceStart?: number;
    sourceEnd?: number;
    candidateEntityId?: string;
    candidateLabel?: string;
    candidateKind?: string;
    decision: GraphRebuildEntityLinkDecision;
    status: 'review' | 'confirmed';
    confidence: number;
    rerankScore: number;
    structuralRole?: GraphRebuildStructuralEdgeRole | GraphRebuildStructuralNodeRole | 'shared_component';
    embeddingRole?: GraphRebuildEmbeddingBackboneRole | 'same_cluster' | 'cross_cluster' | 'outlier';
    productRegionRole?: GraphRebuildProductTopologyRegionRole | 'cross_region';
    productLane?: GraphRebuildProductLaneKind | 'mixed';
    linkerCandidateEntityIds?: string[];
    linkerWindowId?: string;
    competingEntityIds: string[];
    evidenceIds: string[];
    rerankSignals: string[];
    rationale: string[];
}

export type GraphRebuildShadowLinkKind =
    | 'bundle_dedupe'
    | 'alias_suspicion'
    | 'same_entity_suspicion'
    | 'relation_duplicate_suspicion'
    | 'cluster_hint'
    | 'query_assist';

export interface GraphRebuildShadowLink extends GraphRebuildEntityLinkSuggestion {
    phase: 'shadow';
    shadowKind: GraphRebuildShadowLinkKind;
    mutationAllowed: false;
    promotionState: 'shadow' | 'promoted' | 'blocked';
    promotionBlockedReasons: string[];
    relatedBundleIds?: string[];
    relatedRelationIds?: string[];
    clusterHintIds?: string[];
}

export type GraphRebuildFinalLinkPatchKind =
    | 'canonical_identity'
    | 'same_as'
    | 'alias_of'
    | 'merge_record';

export interface GraphRebuildFinalLinkReceipt {
    id: string;
    sourceShadowLinkId: string;
    invariant: string;
    status: 'passed' | 'failed';
    detail: string;
}

export interface GraphRebuildFinalLinkPatch {
    id: string;
    kind: GraphRebuildFinalLinkPatchKind;
    status: 'planned' | 'applied' | 'reverted';
    sourceShadowLinkId: string;
    operation: string;
    canonicalEntityId?: string;
    sourceEntityId?: string;
    targetEntityId?: string;
    alias?: string;
    mergeRecordId?: string;
    confidence: number;
    evidenceIds: string[];
    receipts: GraphRebuildFinalLinkReceipt[];
    reversiblePatch: {
        undoOperation: string;
        targetId?: string;
        previousValue?: string;
        createdEdgeId?: string;
        createdAlias?: string;
    };
    createdAt: number;
}

export interface GraphRebuildFinalLinkPatchLog {
    schemaVersion: 'phoenix-final-linker-patch-log/v1';
    generatedAt: number;
    patches: GraphRebuildFinalLinkPatch[];
    receipts: GraphRebuildFinalLinkReceipt[];
    counters: {
        planned: number;
        applied: number;
        reverted: number;
        blocked: number;
        failedReceipts: number;
    };
}

export type GraphSemanticTaskKind =
    | 'link_prediction'
    | 'edge_classification'
    | 'node_classification'
    | 'graph_completion'
    | 'community_detection'
    | 'anomaly_detection'
    | 'path_reasoning';

export type GraphSemanticProposalKind =
    | 'semantic_link'
    | 'identity_link'
    | 'relation_type'
    | 'causal_type'
    | 'temporal_type'
    | 'entity_kind'
    | 'domain_vote'
    | 'missing_entity'
    | 'missing_edge'
    | 'missing_frame'
    | 'semantic_bundle'
    | 'contradiction_review'
    | 'duplicate_review'
    | 'brittle_link'
    | 'outlier_review'
    | 'causal_chain'
    | 'temporal_chain'
    | 'belief_chain';

export type GraphSemanticTaskStatus = 'prepared' | 'proposed' | 'deferred' | 'blocked';
export type GraphSemanticTaskSourceKind =
    | 'embedding_target'
    | 'manifold'
    | 'graph_postprocess'
    | 'identity_linker'
    | 'relationship_fact'
    | 'temporal_fact'
    | 'causal_fact'
    | 'ontology_policy'
    | 'evidence_ledger';

export type GraphSemanticTaskScoreKind =
    | 'semantic'
    | 'manifold'
    | 'structural'
    | 'evidence'
    | 'ontology'
    | 'temporal'
    | 'causal'
    | 'identity'
    | 'anomaly';

export interface GraphSemanticTaskSource {
    kind: GraphSemanticTaskSourceKind;
    id: string;
    label: string;
    lane?: GraphRebuildSignalTargetLane;
    modelId?: string;
    manifold?: string;
    targetKind?: string;
}

export interface GraphSemanticTaskScore {
    kind: GraphSemanticTaskScoreKind;
    score: number;
    weight: number;
    sourceId: string;
    rationale: string;
}

export interface GraphSemanticTaskReceipt {
    id: string;
    taskId: string;
    status: GraphSemanticTaskStatus;
    reversible: true;
    mutationAllowed: false;
    invariant: string;
    evidenceIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphSemanticTask {
    id: string;
    taskKind: GraphSemanticTaskKind;
    proposalKind: GraphSemanticProposalKind;
    status: GraphSemanticTaskStatus;
    sourceTargetIds: string[];
    targetIds: string[];
    sources: GraphSemanticTaskSource[];
    scores: GraphSemanticTaskScore[];
    confidence: number;
    rationale: string[];
    evidenceIds: string[];
    reversibleReceiptIds: string[];
    mutationAllowed: false;
    createdAt: number;
}

export interface GraphSemanticTaskCounters {
    byTaskKind: Record<string, number>;
    byProposalKind: Record<string, number>;
    bySourceKind: Record<string, number>;
    byStatus: Record<string, number>;
    byManifold: Record<string, number>;
    sourceTargetCount: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
}

export interface GraphSemanticTaskSummary {
    schemaVersion: 'phoenix-graph-semantic-tasks/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    tasks: GraphSemanticTask[];
    receipts: GraphSemanticTaskReceipt[];
    counters: GraphSemanticTaskCounters;
}

export type GraphSemanticCandidateKind =
    | 'entity_link'
    | 'relation_link'
    | 'missing_frame'
    | 'causal_bridge'
    | 'temporal_bridge'
    | 'contradiction_review'
    | 'outlier_review';

export type GraphSemanticCandidateStatus = 'proposed' | 'deferred' | 'blocked';
export type GraphSemanticCandidateSourceKind =
    | 'semantic_task'
    | 'embedding_target'
    | 'manifold'
    | 'graph_postprocess'
    | 'identity_linker'
    | 'relationship_fact'
    | 'temporal_fact'
    | 'causal_fact'
    | 'frame_gap'
    | 'evidence_anchor';

export interface GraphSemanticCandidateSource {
    kind: GraphSemanticCandidateSourceKind;
    id: string;
    label: string;
    taskId?: string;
    taskKind?: GraphSemanticTaskKind;
    proposalKind?: GraphSemanticProposalKind;
    manifold?: string;
}

export interface GraphSemanticCandidate {
    id: string;
    kind: GraphSemanticCandidateKind;
    status: GraphSemanticCandidateStatus;
    sourceTaskIds: string[];
    sourceTargetIds: string[];
    targetIds: string[];
    evidenceIds: string[];
    sources: GraphSemanticCandidateSource[];
    scores: GraphSemanticTaskScore[];
    confidence: number;
    noiseScore: number;
    rank: number;
    rationale: string[];
    reversibleReceiptIds: string[];
    manifoldContributionIds?: string[];
    semanticRerankJudgmentIds?: string[];
    mutationAllowed: false;
    createdAt: number;
}

export interface GraphSemanticCandidateReceipt {
    id: string;
    candidateId: string;
    status: GraphSemanticCandidateStatus;
    reversible: true;
    mutationAllowed: false;
    invariant: string;
    evidenceIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphSemanticCandidateCounters {
    byKind: Record<string, number>;
    byStatus: Record<string, number>;
    bySourceKind: Record<string, number>;
    sourceTaskCount: number;
    sourceTargetCount: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
    proposedCount: number;
    deferredCount: number;
    blockedCount: number;
    maxCandidates: number;
    averageNoiseScore: number;
}

export interface GraphSemanticCandidateSummary {
    schemaVersion: 'phoenix-semantic-candidate-factory/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    candidates: GraphSemanticCandidate[];
    receipts: GraphSemanticCandidateReceipt[];
    counters: GraphSemanticCandidateCounters;
}

export type GraphSemanticManifoldKind =
    | 'hybrid'
    | 'hopf'
    | 'caps'
    | 'product'
    | 'siegel'
    | 'lorentz'
    | 'hyperbolic';

export type GraphManifoldRole =
    | 'semantic_neighborhood'
    | 'recurrence_cycle'
    | 'evidence_cap_hierarchy'
    | 'cross_family_bridge'
    | 'structured_route'
    | 'hierarchy_compression'
    | 'ancestry_depth';

export interface GraphManifoldContributionRule {
    id: string;
    description: string;
    candidateKinds: GraphSemanticCandidateKind[];
    requiredSignals: string[];
}

export interface GraphManifoldRoleProfile {
    manifold: GraphSemanticManifoldKind;
    manifoldRole: GraphManifoldRole;
    label: string;
    scoreInterpretation: string;
    candidateKinds: GraphSemanticCandidateKind[];
    contributionRules: GraphManifoldContributionRule[];
}

export interface GraphManifoldCandidateContribution {
    id: string;
    candidateId: string;
    candidateKind: GraphSemanticCandidateKind;
    manifold: GraphSemanticManifoldKind;
    manifoldRole: GraphManifoldRole;
    ruleId: string;
    score: number;
    scoreInterpretation: string;
    sourceTargetIds: string[];
    evidenceIds: string[];
    rationale: string;
    reversibleReceiptId: string;
}

export interface GraphManifoldSpecializationReceipt {
    id: string;
    contributionId: string;
    candidateId: string;
    manifold: GraphSemanticManifoldKind;
    reversible: true;
    mutationAllowed: false;
    invariant: string;
    evidenceIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphManifoldSpecializationCounters {
    byManifold: Record<string, number>;
    byRole: Record<string, number>;
    byCandidateKind: Record<string, number>;
    contributionCount: number;
    explainedCandidateCount: number;
    unexplainedCandidateCount: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
    maxContributions: number;
}

export interface GraphManifoldSpecializationSummary {
    schemaVersion: 'phoenix-manifold-specialization/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    profiles: GraphManifoldRoleProfile[];
    contributions: GraphManifoldCandidateContribution[];
    receipts: GraphManifoldSpecializationReceipt[];
    counters: GraphManifoldSpecializationCounters;
}

export type GraphSemanticRerankLabelKind =
    | 'strong_identity_alias'
    | 'strong_relation_bridge'
    | 'strong_missing_frame'
    | 'strong_causal_bridge'
    | 'strong_temporal_bridge'
    | 'strong_contradiction_review'
    | 'strong_outlier_review'
    | 'defer_for_review'
    | 'reject_as_noise';

export type GraphSemanticRerankDecision = 'accept' | 'defer' | 'reject' | 'review';
export type GraphSemanticRerankScoreSource = 'gliclass_instruct' | 'deterministic_calibration';

export interface GraphSemanticRerankLabel {
    id: string;
    kind: GraphSemanticRerankLabelKind;
    query: string;
    threshold: number;
    candidateKinds: GraphSemanticCandidateKind[];
}

export interface GraphSemanticRerankInput {
    id: string;
    candidateId: string;
    candidateKind: GraphSemanticCandidateKind;
    passage: string;
    labelIds: string[];
    queryLabels: string[];
    manifoldContributionIds: string[];
    evidenceIds: string[];
    maxPassageChars: number;
}

export interface GraphSemanticRerankScore {
    labelId: string;
    labelKind: GraphSemanticRerankLabelKind;
    query: string;
    score: number;
    source: GraphSemanticRerankScoreSource;
    rationale: string;
}

export interface GraphSemanticRerankJudgment {
    id: string;
    candidateId: string;
    candidateKind: GraphSemanticCandidateKind;
    inputId: string;
    decision: GraphSemanticRerankDecision;
    topLabelId: string;
    topLabelKind: GraphSemanticRerankLabelKind;
    modelId: string;
    runner: string;
    scoreSource: GraphSemanticRerankScoreSource;
    relevanceScore: number;
    calibratedScore: number;
    scores: GraphSemanticRerankScore[];
    evidenceIds: string[];
    manifoldContributionIds: string[];
    rationale: string[];
    reversibleReceiptId: string;
}

export interface GraphSemanticRerankReceipt {
    id: string;
    judgmentId: string;
    candidateId: string;
    reversible: true;
    mutationAllowed: false;
    invariant: string;
    evidenceIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphSemanticRerankCounters {
    byDecision: Record<string, number>;
    byTopLabelKind: Record<string, number>;
    byCandidateKind: Record<string, number>;
    byScoreSource: Record<string, number>;
    inputCount: number;
    judgmentCount: number;
    receiptCount: number;
    plannedModelCalls: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
    maxInputs: number;
    averageCalibratedScore: number;
}

export interface GraphSemanticRerankSummary {
    schemaVersion: 'phoenix-semantic-rerank/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    modelId: string;
    runner: 'gliclass-query-label-rerank';
    scoreSource: GraphSemanticRerankScoreSource;
    labels: GraphSemanticRerankLabel[];
    inputs: GraphSemanticRerankInput[];
    judgments: GraphSemanticRerankJudgment[];
    receipts: GraphSemanticRerankReceipt[];
    counters: GraphSemanticRerankCounters;
}

export type GraphSemanticAdjudicationState =
    | 'proposed'
    | 'supported'
    | 'accepted'
    | 'deferred'
    | 'rejected'
    | 'invalidated'
    | 'superseded';

export interface GraphSemanticAdjudicationScorePart {
    id: string;
    score: number;
    weight: number;
}

export interface GraphSemanticAdjudicationScoringBundle {
    candidateRank: number;
    candidateConfidence: number;
    candidateNoise: number;
    rerankRelevance: number;
    rerankCalibrated: number;
    rerankSource: GraphSemanticRerankScoreSource | 'missing_rerank';
    topLabelKind?: GraphSemanticRerankLabelKind;
    finalScore: number;
    scoreParts: GraphSemanticAdjudicationScorePart[];
}

export interface GraphSemanticAdjudicationReceipt {
    id: string;
    candidateId: string;
    judgmentId?: string;
    state: GraphSemanticAdjudicationState;
    reversible: true;
    mutationAllowed: false;
    invariant: string;
    evidenceTargetIds: string[];
    affectedGraphAtomIds: string[];
    affectedGraphFactIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphSemanticAdjudicationMutation {
    id: string;
    decisionId: string;
    candidateId: string;
    operation: 'add_semantic_edge';
    status: 'applied' | 'reverted';
    createdEdgeId: string;
    createdFactIds: string[];
    affectedGraphAtomIds: string[];
    affectedGraphFactIds: string[];
    createdEdge?: GraphRebuildEdge;
    undoReceiptId: string;
    reversiblePatch: {
        undoOperation: 'remove_semantic_edge_and_fact';
        removeEdgeId: string;
        removeFactIds: string[];
    };
    createdAt: number;
}

export interface GraphSemanticAdjudicationDecision {
    id: string;
    proposalNodeId: string;
    supportedNodeId: string;
    candidateId: string;
    candidateKind: GraphSemanticCandidateKind;
    judgmentId?: string;
    state: GraphSemanticAdjudicationState;
    sourceHypothesis: string;
    evidenceTargetIds: string[];
    scoringBundle: GraphSemanticAdjudicationScoringBundle;
    rationale: string[];
    undoReceiptId: string;
    mutationId?: string;
    affectedGraphAtomIds: string[];
    affectedGraphFactIds: string[];
    ledgerOnly: true;
    createdAt: number;
}

export interface GraphSemanticAdjudicationCounters {
    byState: Record<string, number>;
    byCandidateKind: Record<string, number>;
    decisionCount: number;
    mutationCount: number;
    appliedMutationCount: number;
    ledgerOnlyCount: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    topologyCommitCount: number;
}

export interface GraphSemanticAdjudicationDAGSummary {
    schemaVersion: 'phoenix-semantic-adjudication-dag/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    states: GraphSemanticAdjudicationState[];
    dagEdges: Array<{ from: string; to: string; label: string }>;
    decisions: GraphSemanticAdjudicationDecision[];
    mutations: GraphSemanticAdjudicationMutation[];
    receipts: GraphSemanticAdjudicationReceipt[];
    counters: GraphSemanticAdjudicationCounters;
}

export type GraphSemanticEvalLedgerLabel =
    | 'accepted_candidate'
    | 'rejected_candidate'
    | 'ambiguous_case'
    | 'model_disagreement'
    | 'manifold_disagreement';

export interface GraphSemanticEvalLedgerEntry {
    id: string;
    candidateId: string;
    decisionId: string;
    label: GraphSemanticEvalLedgerLabel;
    candidateKind: GraphSemanticCandidateKind;
    adjudicationState: GraphSemanticAdjudicationState;
    sourceHypothesis: string;
    evidenceTargetIds: string[];
    score: number;
    scoringBundle: GraphSemanticAdjudicationScoringBundle;
    rerank?: {
        judgmentId: string;
        decision: GraphSemanticRerankDecision;
        scoreSource: GraphSemanticRerankScoreSource;
        topLabelKind: GraphSemanticRerankLabelKind;
        relevanceScore: number;
        calibratedScore: number;
    };
    manifoldVotes: Array<{
        id: string;
        manifold: GraphSemanticManifoldKind;
        role: GraphManifoldRole;
        score: number;
        ruleId: string;
    }>;
    flags: string[];
    beforeGraph: {
        edgeCount: number;
        factIds: string[];
        edgeIds: string[];
    };
    afterGraph: {
        edgeCount: number;
        factIds: string[];
        edgeIds: string[];
    };
    userCorrectionIds: string[];
    rationale: string[];
}

export interface GraphSemanticEvalLedgerCounters {
    rowCount: number;
    byLabel: Record<string, number>;
    byCandidateKind: Record<string, number>;
    acceptedCandidates: number;
    rejectedCandidates: number;
    ambiguousCases: number;
    userCorrections: number;
    modelDisagreements: number;
    manifoldDisagreements: number;
    graphChangeRows: number;
}

export interface GraphSemanticEvalLedgerSummary {
    schemaVersion: 'phoenix-semantic-eval-ledger/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    datasetPurpose: Array<'classifier_training' | 'reranker_eval' | 'router_tuning' | 'model_swap_regression'>;
    entries: GraphSemanticEvalLedgerEntry[];
    compactExport: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            label: GraphSemanticEvalLedgerLabel;
            kind: GraphSemanticCandidateKind;
            state: GraphSemanticAdjudicationState;
            score: number;
            flags: string[];
            evidence: number;
            changedEdges: number;
            changedFacts: number;
        }>;
    };
    counters: GraphSemanticEvalLedgerCounters;
}

export type GraphDiscourseSpineTargetKind = 'document_root' | 'document' | 'chunk';
export type GraphDiscourseSpineLabelKind =
    | 'domain'
    | 'story_aspect'
    | 'narrative_function'
    | 'evidence_role'
    | 'temporal_scope'
    | 'tone_mood'
    | 'world_context';
export type GraphDiscourseSpineClusterKind = 'domain_region' | 'aspect_region' | 'document_family';
export type GraphDiscourseSpineBridgeKind = 'resonance' | 'resolution';
export type GraphDiscourseSpineBridgeStatus = 'proposed' | 'deferred' | 'rejected';

export interface GraphDiscourseSpineLabel {
    id: string;
    targetId: string;
    targetKind: GraphDiscourseSpineTargetKind;
    labelKind: GraphDiscourseSpineLabelKind;
    value: string;
    score: number;
    cues: string[];
    rationale: string;
    receiptId: string;
}

export interface GraphDiscourseSpineCluster {
    id: string;
    kind: GraphDiscourseSpineClusterKind;
    label: string;
    targetIds: string[];
    medoidTargetId: string;
    score: number;
    rationale: string[];
    receiptId: string;
}

export interface GraphDiscourseSpineScorePart {
    id: string;
    score: number;
    weight: number;
}

export interface GraphDiscourseSpineScoringBundle {
    semanticScore: number;
    labelAgreement: number;
    entityOverlap: number;
    distanceScore: number;
    corefPressure: number;
    finalScore: number;
    scoreParts: GraphDiscourseSpineScorePart[];
}

export interface GraphDiscourseSpineBridge {
    id: string;
    kind: GraphDiscourseSpineBridgeKind;
    status: GraphDiscourseSpineBridgeStatus;
    sourceTargetId: string;
    targetTargetId: string;
    sourceKind: GraphDiscourseSpineTargetKind;
    targetKind: GraphDiscourseSpineTargetKind;
    label: string;
    evidenceTargetIds: string[];
    sharedLabelIds: string[];
    sharedEntityIds: string[];
    scoringBundle: GraphDiscourseSpineScoringBundle;
    rationale: string[];
    adjudicationState: 'proposed';
    mutationAllowed: false;
    receiptId: string;
    createdAt: number;
}

export interface GraphDiscourseSpineReceipt {
    id: string;
    labelId?: string;
    clusterId?: string;
    bridgeId?: string;
    reversible: true;
    mutationAllowed: false;
    invariant: 'discourse_spine_no_topology_commit';
    evidenceTargetIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphDiscourseSpineCounters {
    targetCount: number;
    documentRoots: number;
    documents: number;
    chunks: number;
    labelCount: number;
    clusterCount: number;
    bridgeCount: number;
    resonanceCandidates: number;
    resolutionCandidates: number;
    proposedBridges: number;
    deferredBridges: number;
    rejectedBridges: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
    byLabelKind: Record<string, number>;
    byClusterKind: Record<string, number>;
    byBridgeKind: Record<string, number>;
}

export type GraphDiscourseBridgeCandidateKind =
    | 'discourse_resonance'
    | 'cross_doc_resolution'
    | 'document_cluster_review';
export type GraphDiscourseBridgeCandidateStatus = 'proposed' | 'deferred' | 'rejected';
export type GraphDiscourseBridgeEvalKind =
    | 'accepted_looking_resonance'
    | 'weak_resonance'
    | 'cross_doc_resolver_pressure'
    | 'entity_overlap_without_meaning'
    | 'meaning_overlap_without_entity';
export type GraphDiscourseBridgeRerankLabelKind =
    | 'meaningful_resonance'
    | 'cross_doc_resolution'
    | 'document_cluster_review'
    | 'weak_resonance'
    | 'entity_only_overlap'
    | 'meaning_only_overlap'
    | 'reject_noise';

export interface GraphDiscourseBridgeRerankLabel {
    id: string;
    kind: GraphDiscourseBridgeRerankLabelKind;
    query: string;
    threshold: number;
    candidateKinds: GraphDiscourseBridgeCandidateKind[];
}

export interface GraphDiscourseBridgeCandidate {
    id: string;
    kind: GraphDiscourseBridgeCandidateKind;
    status: GraphDiscourseBridgeCandidateStatus;
    sourceBridgeId?: string;
    sourceClusterId?: string;
    sourceTargetId: string;
    targetTargetId: string;
    evidenceTargetIds: string[];
    sharedLabelIds: string[];
    sharedEntityIds: string[];
    score: number;
    scoringBundle: GraphDiscourseSpineScoringBundle;
    rationale: string[];
    reversibleReceiptIds: string[];
    mutationAllowed: false;
    createdAt: number;
}

export interface GraphDiscourseBridgeRerankInput {
    id: string;
    candidateId: string;
    candidateKind: GraphDiscourseBridgeCandidateKind;
    passage: string;
    labelIds: string[];
    queryLabels: string[];
    evidenceTargetIds: string[];
    maxPassageChars: number;
}

export interface GraphDiscourseBridgeRerankScore {
    labelId: string;
    labelKind: GraphDiscourseBridgeRerankLabelKind;
    query: string;
    score: number;
    source: GraphSemanticRerankScoreSource;
    rationale: string;
}

export interface GraphDiscourseBridgeRerankJudgment {
    id: string;
    candidateId: string;
    candidateKind: GraphDiscourseBridgeCandidateKind;
    inputId: string;
    decision: GraphSemanticRerankDecision;
    topLabelId: string;
    topLabelKind: GraphDiscourseBridgeRerankLabelKind;
    modelId: string;
    runner: 'gliclass-query-label-rerank';
    scoreSource: GraphSemanticRerankScoreSource;
    relevanceScore: number;
    calibratedScore: number;
    scores: GraphDiscourseBridgeRerankScore[];
    evidenceTargetIds: string[];
    rationale: string[];
    reversibleReceiptId: string;
}

export interface GraphDiscourseBridgeEvalRow {
    id: string;
    kind: GraphDiscourseBridgeEvalKind;
    candidateId: string;
    judgmentId: string;
    bridgeId?: string;
    expectedLabelKind: GraphDiscourseBridgeRerankLabelKind;
    score: number;
    passed: boolean;
    failureModes: string[];
    evidenceTargetIds: string[];
    flags: string[];
    rationale: string[];
}

export interface GraphDiscourseBridgeCandidateReceipt {
    id: string;
    candidateId?: string;
    judgmentId?: string;
    evalRowId?: string;
    reversible: true;
    mutationAllowed: false;
    invariant: 'discourse_bridge_candidates_no_topology_commit';
    evidenceTargetIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphDiscourseBridgeCandidateCounters {
    byCandidateKind: Record<string, number>;
    byStatus: Record<string, number>;
    byDecision: Record<string, number>;
    byEvalKind: Record<string, number>;
    byScoreSource: Record<string, number>;
    candidateCount: number;
    inputCount: number;
    judgmentCount: number;
    evalRowCount: number;
    passedEvalRows: number;
    failedEvalRows: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
    plannedModelCalls: number;
    acceptedLookingResonance: number;
    weakResonance: number;
    crossDocResolverPressure: number;
    entityOverlapWithoutMeaning: number;
    meaningOverlapWithoutEntity: number;
    maxCandidates: number;
    maxPassageChars: number;
}

export type GraphDiscourseBridgeAdjudicationState =
    | 'proposed'
    | 'supported'
    | 'accepted'
    | 'deferred'
    | 'rejected'
    | 'invalidated'
    | 'superseded';

export interface GraphDiscourseBridgeAdjudicationScorePart {
    id: string;
    score: number;
    weight: number;
}

export interface GraphDiscourseBridgeAdjudicationScoringBundle {
    candidateScore: number;
    spineFinalScore: number;
    rerankRelevance: number;
    rerankCalibrated: number;
    rerankSource: GraphSemanticRerankScoreSource | 'missing_rerank';
    topLabelKind?: GraphDiscourseBridgeRerankLabelKind;
    evalScore: number;
    evalPassed: boolean;
    finalScore: number;
    scoreParts: GraphDiscourseBridgeAdjudicationScorePart[];
}

export interface GraphDiscourseBridgeAdjudicationDecision {
    id: string;
    proposalNodeId: string;
    supportedNodeId: string;
    candidateId: string;
    candidateKind: GraphDiscourseBridgeCandidateKind;
    sourceBridgeId?: string;
    sourceClusterId?: string;
    judgmentId?: string;
    evalRowId?: string;
    state: GraphDiscourseBridgeAdjudicationState;
    sourceHypothesis: string;
    evidenceTargetIds: string[];
    scoringBundle: GraphDiscourseBridgeAdjudicationScoringBundle;
    rationale: string[];
    undoReceiptId: string;
    affectedGraphAtomIds: string[];
    affectedGraphFactIds: string[];
    ledgerOnly: true;
    mutationAllowed: false;
    createdAt: number;
}

export interface GraphDiscourseBridgeAdjudicationReceipt {
    id: string;
    candidateId: string;
    judgmentId?: string;
    evalRowId?: string;
    state: GraphDiscourseBridgeAdjudicationState;
    reversible: true;
    mutationAllowed: false;
    invariant: 'discourse_bridge_adjudication_ledger_only';
    evidenceTargetIds: string[];
    affectedGraphAtomIds: string[];
    affectedGraphFactIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphDiscourseBridgeAdjudicationCounters {
    byState: Record<string, number>;
    byCandidateKind: Record<string, number>;
    decisionCount: number;
    acceptedCount: number;
    supportedCount: number;
    deferredCount: number;
    rejectedCount: number;
    invalidatedCount: number;
    supersededCount: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    ledgerOnlyCount: number;
    topologyCommitCount: number;
    mutationAllowedCount: number;
    compactRowCount: number;
}

export type GraphDiscourseEvalLedgerLabel =
    | 'accepted_candidate'
    | 'rejected_candidate'
    | 'ambiguous_case'
    | 'model_disagreement'
    | 'manifold_disagreement';

export interface GraphDiscourseEvalLedgerEntry {
    id: string;
    candidateId: string;
    decisionId: string;
    label: GraphDiscourseEvalLedgerLabel;
    candidateKind: GraphDiscourseBridgeCandidateKind;
    adjudicationState: GraphDiscourseBridgeAdjudicationState;
    sourceHypothesis: string;
    evidenceTargetIds: string[];
    score: number;
    scoringBundle: GraphDiscourseBridgeAdjudicationScoringBundle;
    rerank?: {
        judgmentId: string;
        decision: GraphSemanticRerankDecision;
        scoreSource: GraphSemanticRerankScoreSource;
        topLabelKind: GraphDiscourseBridgeRerankLabelKind;
        relevanceScore: number;
        calibratedScore: number;
    };
    candidateEval?: {
        evalRowId: string;
        kind: GraphDiscourseBridgeEvalKind;
        expectedLabelKind: GraphDiscourseBridgeRerankLabelKind;
        score: number;
        passed: boolean;
        failureModes: string[];
    };
    discourseReceipts: {
        semanticScore: number;
        labelAgreement: number;
        entityOverlap: number;
        distanceScore: number;
        corefPressure: number;
        finalScore: number;
    };
    flags: string[];
    beforeGraph: {
        edgeCount: number;
        factIds: string[];
        edgeIds: string[];
    };
    afterGraph: {
        edgeCount: number;
        factIds: string[];
        edgeIds: string[];
    };
    userCorrectionIds: string[];
    rationale: string[];
}

export interface GraphDiscourseEvalLedgerCounters {
    rowCount: number;
    byLabel: Record<string, number>;
    byCandidateKind: Record<string, number>;
    byState: Record<string, number>;
    acceptedCandidates: number;
    rejectedCandidates: number;
    ambiguousCases: number;
    userCorrections: number;
    modelDisagreements: number;
    manifoldDisagreements: number;
    evalDisagreements: number;
    graphChangeRows: number;
    resonanceRows: number;
    resolutionRows: number;
    clusterReviewRows: number;
}

export type GraphDiscoursePromotionHintKind =
    | 'chunk_wormhole'
    | 'document_cluster'
    | 'cross_doc_resolution';

export interface GraphDiscoursePromotionCompilerHint {
    id: string;
    kind: GraphDiscoursePromotionHintKind;
    sourceLedgerEntryId: string;
    candidateId: string;
    decisionId: string;
    sourceTargetId: string;
    targetTargetId?: string;
    memberTargetIds: string[];
    evidenceTargetIds: string[];
    proposedEdgeType?: string;
    confidence: number;
    status: 'read_model_only';
    mutationAllowed: false;
    rationale: string[];
}

export interface GraphDiscourseChunkWormhole {
    id: string;
    sourceLedgerEntryId: string;
    candidateId: string;
    decisionId: string;
    sourceTargetId: string;
    targetTargetId: string;
    score: number;
    label: GraphDiscourseEvalLedgerLabel;
    state: GraphDiscourseBridgeAdjudicationState;
    evidenceTargetIds: string[];
    flags: string[];
    compilerHintId: string;
    mutationAllowed: false;
}

export interface GraphDiscourseDocumentClusterView {
    id: string;
    sourceLedgerEntryId: string;
    candidateId: string;
    decisionId: string;
    sourceClusterId?: string;
    medoidTargetId: string;
    memberTargetIds: string[];
    score: number;
    label: GraphDiscourseEvalLedgerLabel;
    state: GraphDiscourseBridgeAdjudicationState;
    flags: string[];
    compilerHintId: string;
    mutationAllowed: false;
}

export interface GraphDiscourseResolverCandidateView {
    id: string;
    sourceLedgerEntryId: string;
    candidateId: string;
    decisionId: string;
    sourceTargetId: string;
    targetTargetId: string;
    sharedEntityIds: string[];
    score: number;
    label: GraphDiscourseEvalLedgerLabel;
    state: GraphDiscourseBridgeAdjudicationState;
    evidenceTargetIds: string[];
    flags: string[];
    compilerHintId: string;
    mutationAllowed: false;
}

export interface GraphDiscoursePromotionReceipt {
    id: string;
    sourceLedgerEntryId: string;
    compilerHintId: string;
    reversible: true;
    mutationAllowed: false;
    invariant: 'discourse_promotion_surface_no_topology_commit';
    evidenceTargetIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphDiscoursePromotionCounters {
    byHintKind: Record<string, number>;
    byLabel: Record<string, number>;
    chunkWormholeCount: number;
    documentClusterCount: number;
    resolverCandidateCount: number;
    compilerHintCount: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    graphPatchCount: number;
    mutationAllowedCount: number;
    acceptedRows: number;
    ambiguousRows: number;
}

export interface GraphRebuildEntityLinkCounters {
    candidateMentions: number;
    candidateLinks: number;
    sameEntity: number;
    aliasOf: number;
    newEntity: number;
    ambiguous: number;
    rejected: number;
    shadowLinks?: number;
    linkerCandidates?: number;
    autoConfirmable: number;
}

export interface GraphRebuildDropReasons {
    missingEntity: number;
    invalidSpan: number;
    duplicateAnchor: number;
    singletonBucket: number;
    missingChunk: number;
}

export type GraphRebuildResolutionSuggestionKind =
    | 'ambiguous_surface'
    | 'kind_conflict'
    | 'possible_alias'
    | 'possible_duplicate'
    | 'possible_split';

export interface GraphRebuildResolutionSuggestion {
    id: string;
    kind: GraphRebuildResolutionSuggestionKind;
    surface: string;
    noteId?: string;
    sourceStart?: number;
    sourceEnd?: number;
    entityIds: string[];
    status: 'review';
    rationale: string;
}

export interface GraphRebuildResolutionCounters {
    resolvedById: number;
    resolvedByLabel: number;
    resolvedByAlias: number;
    ambiguousSurfaces: number;
    kindConflicts: number;
    possibleAliases: number;
    droppedDuplicateSpans: number;
}

export interface GraphRebuildCounters {
    entities: number;
    aliases: number;
    candidates: number;
    mentions: number;
    acceptedAnchors: number;
    chunks: number;
    anchorEvidence?: number;
    relationSignals?: number;
    promotedFacts?: number;
    relationshipCandidates: number;
    relationships: number;
    acceptedRelationships: number;
    reviewRelationships: number;
    rejectedRelationships: number;
    events: number;
    episodes: number;
    chunkSemanticBridges?: number;
    chunkSetupPayoffBridges?: number;
    chunkCauseEffectBridges?: number;
    chunkStateDeltaBridges?: number;
    chunkRelationshipDeltaBridges?: number;
    chunkTopicContinuationBridges?: number;
    chunkEvidenceReframeBridges?: number;
    chunkMotifEchoBridges?: number;
    chunkRouteContinuityBridges?: number;
    episodeConnections?: number;
    episodeTemporalConnections?: number;
    episodeCausalConnections?: number;
    episodeWormholeConnections?: number;
    episodeProjectionEdges?: number;
    episodeProjectionStructuralEdges?: number;
    episodeProjectionDerivedEdges?: number;
    episodeProjectionCandidateEdges?: number;
    temporalEdges: number;
    causalEdges: number;
    memoryState: number;
    memoryGovernanceCandidates?: number;
    memoryGovernanceBuildMicros?: number;
    memoryGovernanceRetain?: number;
    memoryGovernanceAttenuate?: number;
    memoryGovernanceCompress?: number;
    memoryGovernanceQuarantine?: number;
    memoryGovernanceRetire?: number;
    memoryGovernanceRetrievalCandidates?: number;
    memoryGovernanceRetrievalGoverned?: number;
    memoryGovernanceRetrievalChangedRanks?: number;
    memoryGovernanceRetrievalPolicies?: number;
    promotionVerdictRows?: number;
    promotionVerdictAcceptable?: number;
    promotionVerdictBlocked?: number;
    promotionVerdictAlreadyCommitted?: number;
    promotionVerdictRollbackAvailable?: number;
    reviewAdjudicationTotalRows?: number;
    reviewAdjudicationEligibleRows?: number;
    reviewAdjudicationExcludedRows?: number;
    reviewAdjudicationDuplicateRows?: number;
    reviewAdjudicationJudgedRows?: number;
    reviewAdjudicationAppliedRows?: number;
    reviewAdjudicationTopologyWrites?: number;
    reviewAdjudicationDimension?: number;
    continuityEvents?: number;
    continuityBoundaryReceipts?: number;
    continuityEpisodes?: number;
    continuityTemporalCandidates?: number;
    continuityCausalCandidates?: number;
    continuityStateIntervals?: number;
    continuityEpisodeConnections?: number;
    continuityConflicts?: number;
    continuityCrossDocumentConnections?: number;
    continuityReviewRequired?: number;
    embeddingTargets: number;
    evidenceRegistryExposedTargets?: number;
    evidenceRegistryChunks?: number;
    evidenceRegistryTypedGraphObjects?: number;
    evidenceRegistryEvidenceLinks?: number;
    encoderIndexedTargets?: number;
    encoderCandidateNeighborhoods?: number;
    encoderCandidateNeighbors?: number;
    encoderEvaluatedPairs?: number;
    embeddingTargetCandidates?: number;
    embeddingQueuedTargets?: number;
    embeddingTargetDeferred?: number;
    embeddingSchedulerDeferredTargets?: number;
    embeddingPolicyDeferredTargets?: number;
    embeddingDocumentSpine?: number;
    embeddingChunkSpine?: number;
    embeddingEntityAnchors?: number;
    embeddingRelationshipFacts?: number;
    embeddingTemporalFacts?: number;
    embeddingCausalFacts?: number;
    embeddingMemoryStates?: number;
    embeddingEventIdentities?: number;
    embeddingAnchorEvidence?: number;
    embeddingVectors: number;
    projectionRefs: number;
    nodes: number;
    edges: number;
    structuralComponents?: number;
    structuralHubs?: number;
    structuralBridgeEdges?: number;
    embeddingClusters?: number;
    embeddingSingletonClusters?: number;
    embeddingBackboneEdges?: number;
    embeddingBridgeEdges?: number;
    embeddingOutliers?: number;
    embeddingPlannedPairs?: number;
    embeddingTheoreticalPairs?: number;
    embeddingPrunedPairs?: number;
    graphAwareLinkSuggestions?: number;
    entityLinkSuggestions?: number;
    shadowLinkSuggestions?: number;
    finalLinkPatches?: number;
    finalLinkReceiptFailures?: number;
    semanticTasks?: number;
    semanticTaskReceipts?: number;
    semanticTaskMutationAllowed?: number;
    semanticCandidates?: number;
    semanticCandidateReceipts?: number;
    semanticCandidateMutationAllowed?: number;
    semanticCandidateDeferred?: number;
    manifoldSpecializations?: number;
    manifoldCandidateContributions?: number;
    manifoldContributionReceipts?: number;
    manifoldCandidateExplained?: number;
    manifoldSpecializationMutationAllowed?: number;
    semanticRerankInputs?: number;
    semanticRerankJudgments?: number;
    semanticRerankReceipts?: number;
    semanticRerankPlannedModelCalls?: number;
    semanticRerankMutationAllowed?: number;
    semanticAdjudicationDecisions?: number;
    semanticAdjudicationMutations?: number;
    semanticAdjudicationReceipts?: number;
    semanticAdjudicationTopologyCommits?: number;
    semanticAdjudicationLedgerOnly?: number;
    semanticEvalLedgerRows?: number;
    semanticEvalAcceptedCandidates?: number;
    semanticEvalRejectedCandidates?: number;
    semanticEvalAmbiguousCases?: number;
    semanticEvalModelDisagreements?: number;
    semanticEvalManifoldDisagreements?: number;
    semanticEvalGraphChangeRows?: number;
    hopfResonanceAssignments?: number;
    hopfResonanceOccupiedCells?: number;
    hopfResonanceFibers?: number;
    hopfResonanceDocCharts?: number;
    hopfResonanceBraids?: number;
    hopfResonanceDroppedTargets?: number;
    hopfResonanceMutationAllowed?: number;
    memoryGraphRagRecords?: number;
    memoryGraphRagSchemaRecords?: number;
    memoryGraphRagFactRecords?: number;
    memoryGraphRagPassageRecords?: number;
    memoryGraphRagEvalRows?: number;
    memoryGraphRagPassedEvalRows?: number;
    memoryGraphRagReceipts?: number;
    memoryGraphRagMutationAllowed?: number;
    discourseSpineTargets?: number;
    discourseSpineLabels?: number;
    discourseSpineClusters?: number;
    discourseSpineBridges?: number;
    discourseSpineResonance?: number;
    discourseSpineResolution?: number;
    discourseSpineReceipts?: number;
    discourseSpineMutationAllowed?: number;
    discourseBridgeCandidates?: number;
    discourseBridgeInputs?: number;
    discourseBridgeJudgments?: number;
    discourseBridgeEvalRows?: number;
    discourseBridgeReceipts?: number;
    discourseBridgePlannedModelCalls?: number;
    discourseBridgeMutationAllowed?: number;
    discourseBridgeAdjudicationDecisions?: number;
    discourseBridgeAdjudicationAccepted?: number;
    discourseBridgeAdjudicationSupported?: number;
    discourseBridgeAdjudicationDeferred?: number;
    discourseBridgeAdjudicationRejected?: number;
    discourseBridgeAdjudicationReceipts?: number;
    discourseBridgeAdjudicationLedgerOnly?: number;
    discourseBridgeAdjudicationTopologyCommits?: number;
    discourseBridgeAdjudicationMutationAllowed?: number;
    discourseEvalLedgerRows?: number;
    discourseEvalAcceptedCandidates?: number;
    discourseEvalRejectedCandidates?: number;
    discourseEvalAmbiguousCases?: number;
    discourseEvalModelDisagreements?: number;
    discourseEvalManifoldDisagreements?: number;
    discourseEvalGraphChangeRows?: number;
    discoursePromotionChunkWormholes?: number;
    discoursePromotionDocumentClusters?: number;
    discoursePromotionResolverCandidates?: number;
    discoursePromotionCompilerHints?: number;
    discoursePromotionReceipts?: number;
    discoursePromotionGraphPatches?: number;
    discoursePromotionMutationAllowed?: number;
    discourseCompilerOverlayEdges?: number;
    discourseCompilerOverlayChunkWormholes?: number;
    discourseCompilerOverlayDocumentClusters?: number;
    discourseCompilerOverlayResolvers?: number;
    discourseCompilerOverlayReceipts?: number;
    discourseCompilerOverlayGraphPatches?: number;
    discourseCompilerOverlayMutationAllowed?: number;
    calendarRegistryAnchors?: number;
    calendarRegistryReceipts?: number;
    calendarRegistryAcceptedTemporalReceipts?: number;
    calendarRegistryRealEpochReceipts?: number;
    calendarRegistryCustomOrdinalReceipts?: number;
    calendarRegistryMutationAllowed?: number;
    entityLinking?: GraphRebuildEntityLinkCounters;
    meaningFrameChunks?: number;
    documentSidecarUnits?: number;
    documentSidecarSections?: number;
    documentSidecarRegions?: number;
    documentSidecarRhetoricalUnits?: number;
    documentSidecarRetrievalUnits?: number;
    documentSidecarGraphFacts?: number;
    documentSidecarSituationInstances?: number;
    documentSidecarStateIntervals?: number;
    documentSidecarEventOrderings?: number;
    documentSidecarTemporalConflicts?: number;
    documentSidecarEvidenceSpans?: number;
    documentSidecarAnchorPromotions?: number;
    documentSemanticPropositions?: number;
    documentSemanticArguments?: number;
    documentSemanticResolvedArguments?: number;
    documentSemanticRoleAnnotations?: number;
    documentSemanticUnresolvedRoleSurfaces?: number;
    documentSemanticRoleFailureReasons?: number;
    documentSemanticFrameAnnotations?: number;
    documentSemanticLexicalFrames?: number;
    documentSemanticFallbackFrames?: number;
    documentSemanticLowConfidenceFrames?: number;
    documentSemanticFrameFailureReasons?: number;
    documentSemanticFactualityAnnotations?: number;
    documentSemanticScopedFactuality?: number;
    documentSemanticAttributedFactuality?: number;
    documentSemanticQuotedFactuality?: number;
    documentSemanticConditionalFactuality?: number;
    documentSemanticSpeechOrBeliefFrames?: number;
    documentSemanticLowConfidenceFactuality?: number;
    documentSemanticFactualityFailureReasons?: number;
    documentSemanticArgumentRecoveries?: number;
    documentSemanticLocalCoreferenceRecoveries?: number;
    documentSemanticAliasContinuityRecoveries?: number;
    documentSemanticOmittedSubjectRecoveries?: number;
    documentSemanticQuoteSpeakerRecoveries?: number;
    documentSemanticRepeatedEventLinks?: number;
    documentSemanticWindowArgumentCompletions?: number;
    documentSemanticLowConfidenceRecoveries?: number;
    documentSemanticRecoveryFailureReasons?: number;
    documentSemanticSituationInstances?: number;
    documentSemanticStateIntervals?: number;
    documentSemanticEventOrderings?: number;
    documentSemanticExplicitEventOrderings?: number;
    documentSemanticRecurrenceOrderings?: number;
    documentSemanticPersistentStateIntervals?: number;
    documentSemanticTerminatedStateIntervals?: number;
    documentSemanticTemporalConflicts?: number;
    documentSemanticWorldStateIneligibleSituations?: number;
    documentSemanticNegated?: number;
    documentSemanticModal?: number;
    documentSemanticConditional?: number;
    documentSemanticAttributed?: number;
    documentSemanticQuoted?: number;
    documentSemanticQuestions?: number;
    documentSemanticDirectives?: number;
    documentSemanticNary?: number;
    documentSemanticReviewable?: number;
    documentSemanticLedgerOnly?: number;
    documentSemanticPredicateModifiers?: number;
    documentSemanticPredicateNoise?: number;
    documentReviewRows?: number;
    documentReviewActionableRows?: number;
    documentReviewStateRecords?: number;
    documentReviewActions?: number;
    documentReviewReceipts?: number;
    documentReviewReversibleReceipts?: number;
    documentReviewProposedRows?: number;
    documentReviewAcceptedRows?: number;
    documentReviewRejectedRows?: number;
    documentReviewMutedRows?: number;
    documentReviewPromotedToAnchorRows?: number;
    documentReviewCompiledToGraphRows?: number;
    documentReviewLedgerOnlyRows?: number;
    operatorMutationIntents?: number;
    operatorMutationActive?: number;
    operatorMutationApplied?: number;
    operatorMutationConflicted?: number;
    operatorMutationUndone?: number;
    operatorMutationReceipts?: number;
    documentCompilerEntityMentions?: number;
    documentCompilerRelationCandidates?: number;
    documentCompilerHyperedges?: number;
    documentCompilerNaryHyperedges?: number;
    documentCompilerEvidenceEdges?: number;
    documentCompilerCrossDocBridges?: number;
    documentCompilerStructureEdges?: number;
    documentCompilerRetrievalOverlays?: number;
    documentCompilerTopologyDiffs?: number;
    documentCompilerTopologyCommits?: number;
    documentCompilerNativeCompileCandidates?: number;
    documentCompilerLedgerOnly?: number;
    documentCompilerOverlayOnly?: number;
    documentCompilerReviewable?: number;
    documentCompilerBlocked?: number;
    documentCompilerReceipts?: number;
    documentCompilerReversibleReceipts?: number;
    documentCompilerMutationAllowed?: number;
    documentCompilerHighConfidenceFacts?: number;
    documentCompilerReviewedFacts?: number;
    documentCompilerAmbiguousFacts?: number;
    eventAspects?: number;
    dropReasons: GraphRebuildDropReasons;
    resolution?: GraphRebuildResolutionCounters;
}

export type { GraphRebuildBuildTimings } from './graph-rebuild-build-timings';

export type GraphRebuildContentBlobField =
    | 'sourceRows'
    | 'renderRows'
    | 'evidenceTargetRegistryPage'
    | 'embeddingTargets'
    | 'embeddingTargetPlan'
    | 'embeddingGraphPostProcess'
    | 'graphModelV2'
    | 'semanticCandidateSummary'
    | 'manifoldSpecializationSummary'
    | 'storyContinuity'
    | 'atlasPacket';

export interface GraphRebuildContentBlobRef {
    schemaVersion: 'phoenix-graph-rebuild-content-blob-ref/v1';
    field: GraphRebuildContentBlobField;
    hash: string;
    documentKey: string;
    sourceSchemaVersion: string;
    rawChars: number;
    payloadChars: number;
    compressedBytes: number;
    itemCount?: number;
    createdAt: number;
}

export interface GraphRebuildContentManifest {
    schemaVersion: 'phoenix-graph-rebuild-content-manifest/v1';
    snapshotId: string;
    scopeId: string;
    builtAt: number;
    refs: Partial<Record<GraphRebuildContentBlobField, GraphRebuildContentBlobRef>>;
}

export const GRAPH_SNAPSHOT_LIVE_AUTHORITY = 'graph_rebuild_live_contract' as const;

export type GraphSnapshotAuthority = typeof GRAPH_SNAPSHOT_LIVE_AUTHORITY;

export interface GraphSnapshotAuthorityCounts {
    notes: number;
    chunks: number;
    mentions: number;
    anchors: number;
    relationships: number;
    events: number;
    temporalEdges: number;
    causalEdges: number;
    memoryState: number;
    coreferenceRecoveries: number;
    nodes: number;
    edges: number;
    embeddingTargets: number;
    admittedEmbeddingTargets: number;
    packetObjects: number;
    packetTargets: number;
    packetParentLinks: number;
    packetFamilies: Record<string, number>;
}

export interface GraphSnapshotAuthorityContract {
    schemaVersion: 'phoenix-graph-snapshot-authority/v1';
    authority: GraphSnapshotAuthority;
    snapshotId: string;
    scopeId: string;
    contentHash: string;
    counts: GraphSnapshotAuthorityCounts;
}

export interface GraphInteractiveRunAuthorityReceipt {
    schemaVersion: 'phoenix-interactive-graph-run-authority/v1';
    inputIdentity: string;
    snapshotId: string;
    scopeId: string;
    durable: {
        schemaVersion: 'phoenix-graph-run-durable-receipt/v1';
        runHandle: string;
        scopeId: string;
        snapshotId: string;
        manifestId: string;
        changedSections: number;
        reusedSections: number;
        encodedSections: number;
        compressedSections: number;
        rawBytesWritten: number;
        compressedBytesWritten: number;
    };
}

export interface GraphRebuildSnapshot {
    schemaVersion: 'phoenix-graph-rebuild/v1';
    id: string;
    source: 'phoenix-graph-rebuild';
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    noteIds: string[];
    builtAt: number;
    generationReceiptId?: string;
    generationDigestSha256?: string;
    chunks: GraphRebuildChunk[];
    mentions: GraphRebuildMention[];
    entityAnchors: GraphRebuildEntityAnchor[];
    relationships: GraphRebuildRelationship[];
    events: GraphRebuildEvent[];
    episodes: GraphRebuildEpisode[];
    chunkSemanticBridges?: GraphRebuildChunkSemanticBridge[];
    crossDocumentBridgeCertificate?: GraphCrossDocumentBridgeRunCertificate;
    episodeConnections?: GraphRebuildEpisodeConnection[];
    episodeProjectionEdges?: GraphRebuildEpisodeProjectionEdge[];
    temporalEdges: GraphRebuildTemporalEdge[];
    causalEdges: GraphRebuildCausalEdge[];
    memoryState: GraphRebuildMemoryState[];
    memoryGovernanceCandidates?: GraphMemoryGovernanceCandidate[];
    memoryGovernanceRetrievalExperiment?: GraphMemoryGovernanceRetrievalWeightingExperiment;
    promotionVerdictCertificate?: GraphPromotionVerdictCertificate;
    reviewAdjudicationCertificate?: GraphReviewAdjudicationRunCertificate;
    storyContinuity?: GraphStoryContinuityContract;
    embeddingTargets: GraphRebuildEmbeddingTarget[];
    embeddingTargetPlan?: GraphRebuildEmbeddingTargetPlan;
    evidenceTargetRegistry?: GraphEvidenceTargetRegistryContract;
    evidenceTargetRegistryPage?: GraphEvidenceTargetRegistryPage;
    embeddingVectors: GraphRebuildEmbeddingVector[];
    encoderVectorIndex?: GraphEncoderVectorIndexContract;
    embeddingProfile?: GraphRebuildEmbeddingProfile;
    embeddingModelAdapter?: GraphRebuildEmbeddingModelAdapter;
    embeddingGraphPostProcess?: GraphRebuildEmbeddingGraphPostProcess;
    projectionRefs: GraphRebuildProjectionRef[];
    nodes: GraphRebuildNode[];
    edges: GraphRebuildEdge[];
    structuralPostProcess?: GraphRebuildStructuralPostProcess;
    graphCompiler?: GraphCompilerOutput;
    graphCompileReceipts?: GraphCompileReceipts;
    graphCompilerSource?: GraphCompilerSource;
    projectedUiGraph?: GraphCompilerProjectedUiEdge[];
    atlasPacket?: GraphAtlasPacket;
    graphModelV2?: GraphModelV2Snapshot;
    graphAwareLinkSuggestions?: GraphRebuildLinkSuggestion[];
    entityLinkSuggestions?: GraphRebuildEntityLinkSuggestion[];
    shadowLinkSuggestions?: GraphRebuildShadowLink[];
    finalLinkPatchLog?: GraphRebuildFinalLinkPatchLog;
    semanticTaskSummary?: GraphSemanticTaskSummary;
    semanticCandidateSummary?: GraphSemanticCandidateSummary;
    manifoldSpecializationSummary?: GraphManifoldSpecializationSummary;
    semanticRerankSummary?: GraphSemanticRerankSummary;
    semanticAdjudicationSummary?: GraphSemanticAdjudicationDAGSummary;
    semanticEvalLedgerSummary?: GraphSemanticEvalLedgerSummary;
    hopfResonanceSpace?: HopfResonanceSpace;
    memoryGraphRagBridgeSummary?: GraphMemoryGraphRagBridgeSummary;
    discourseSpineSummary?: GraphDiscourseSpineSummary;
    discourseBridgeCandidateSummary?: GraphDiscourseBridgeCandidateSummary;
    discourseBridgeAdjudicationSummary?: GraphDiscourseBridgeAdjudicationSummary;
    discourseEvalLedgerSummary?: GraphDiscourseEvalLedgerSummary;
    discoursePromotionSurfaceSummary?: GraphDiscoursePromotionSurfaceSummary;
    discourseCompilerOverlaySummary?: GraphDiscourseCompilerOverlaySummary;
    documentSidecarSummary?: GraphDocumentSidecarSummary;
    documentSemanticSummary?: GraphDocumentSemanticSummary;
    documentSemanticArtifactHandle?: string;
    documentReviewSummary?: GraphDocumentReviewSummary;
    documentCompilerSummary?: GraphDocumentCompilerSummary;
    graphTruthCommitLedger?: GraphTruthCommitLedger;
    authorityContract?: GraphSnapshotAuthorityContract;
    interactiveRunAuthority?: GraphInteractiveRunAuthorityReceipt;
    documentGraphMutationLedger?: GraphDocumentGraphMutationLedger;
    operatorMutationJournal?: GraphOperatorMutationJournal;
    calendarRegistrySummary?: GraphCalendarRegistryBridgeSummary;
    contentManifest?: GraphRebuildContentManifest;
    counters: GraphRebuildCounters;
    buildTimings?: GraphRebuildBuildTimings;
    resolutionSuggestions?: GraphRebuildResolutionSuggestion[];
}

export type GraphIndexPolicy = 'delta' | 'force';
export type GraphIndexPostProcessMode = 'core' | 'full';
export type GraphBuildDurabilityMode = 'interactive' | 'durable' | 'diagnostic';
export type GraphIndexRunStatus = 'blocked' | 'running' | 'completed' | 'failed';
export type GraphIndexStageStatus = 'blocked' | 'skipped' | 'running' | 'completed' | 'failed';
export type GraphIndexProjectionMode = 'hybrid' | 'hopf' | 'lorentz' | 'product' | 'siegel';

export interface GraphIndexRunScope {
    kind: GraphRebuildScopeKind;
    scopeId: string;
    label: string;
    noteIds: string[];
}

export interface GraphIndexModelSelection {
    dynamicNerId: 'dynamic_ner';
    embeddingModelId: string;
    embeddingModelLabel: string;
    embeddingDimensionLabel: string;
    nliModelId: string;
}

export interface GraphIndexEmbeddingStagePolicy {
    enabledLanes?: GraphRebuildSignalTargetLane[];
    entityLinkerEnabled?: boolean;
}

export interface GraphIndexRunRequest {
    scope: GraphIndexRunScope;
    policy: GraphIndexPolicy;
    postProcessMode?: GraphIndexPostProcessMode;
    durabilityMode?: GraphBuildDurabilityMode;
    modelSelection: GraphIndexModelSelection;
    embeddingStagePolicy?: GraphIndexEmbeddingStagePolicy;
    calendarRegistrySnapshot?: CalendarRegistrySnapshot;
    entities: RegisteredEntity[];
}

export interface GraphIndexModelReadiness {
    id: 'dynamicNer' | 'semanticEmbedding' | 'nli' | 'entityLinker';
    label: string;
    status: 'idle' | 'warming' | 'running' | 'ready' | 'error';
    detail: string;
    optional?: boolean;
}

export interface GraphIndexStageReceipt {
    id: string;
    label: string;
    status: GraphIndexStageStatus;
    startedAt: number;
    completedAt: number;
    durationMs: number;
    outputCount: number;
    counters: Record<string, number>;
    message: string;
    spanId?: string;
    parentSpanId?: string;
}

export interface GraphIndexProjectionReceipt {
    mode: GraphIndexProjectionMode;
    status: 'synced' | 'stale' | 'error' | 'skipped';
    startedAt: number;
    completedAt: number;
    durationMs: number;
    targetCount: number;
    vectorCount: number;
    counters?: Record<string, number>;
    snapshotId?: string;
    snapshotHash?: string;
    message: string;
}

export type GraphIndexLayerKind =
    | 'input'
    | 'model'
    | 'truth'
    | 'native'
    | 'authority'
    | 'persistence'
    | 'projection'
    | 'diagnostic'
    | 'transport'
    | 'ui';

export type GraphIndexLayerStatus = 'complete' | 'partial' | 'skipped' | 'failed';

export interface GraphIndexLayerReceipt {
    id: string;
    label: string;
    kind: GraphIndexLayerKind;
    status: GraphIndexLayerStatus;
    owner: string;
    source: string;
    consumes: string[];
    produces: string[];
    stageIds: string[];
    projectionModes?: GraphIndexProjectionMode[];
    authority?: string;
    contentHash?: string;
    counters: Record<string, number>;
    message: string;
}

export interface GraphIndexRunReceipt {
    schemaVersion: 'phoenix-graph-index-run/v1';
    id: string;
    scope: GraphIndexRunScope;
    policy: GraphIndexPolicy;
    delta: boolean;
    status: GraphIndexRunStatus;
    modelSelection: GraphIndexModelSelection;
    postProcessMode?: GraphIndexPostProcessMode;
    durabilityMode?: GraphBuildDurabilityMode;
    postProcessFingerprint?: string;
    postProcessDiscoveryFingerprint?: string;
    postProcessCacheHit?: boolean;
    modelReadiness: GraphIndexModelReadiness[];
    startedAt: number;
    completedAt: number;
    durationMs: number;
    stageReceipts: GraphIndexStageReceipt[];
    projectionReceipts: GraphIndexProjectionReceipt[];
    layerReceipts: GraphIndexLayerReceipt[];
    snapshotId?: string;
    authorityContract?: GraphSnapshotAuthorityContract;
    generationReceiptId?: string;
    generationDigestSha256?: string;
    counters: GraphRebuildCounters;
    dropReasons: GraphRebuildDropReasons;
    message: string;
    spanId?: string;
    parentSpanId?: null;
    pathId?: string;
    fallbackCount?: number;
    replayManifest?: GraphRebuildReplayManifest;
    verifiedForceAuthority?: {
        schemaVersion: 'phoenix-verified-force-authority-ref/v1';
        snapshotId: string;
        authorityHash: string;
        manifestId: string;
        runHandle: string;
    };
}

export interface GraphRebuildCandidate {
    label: string;
    kind: string;
    aliases?: string[];
    confidence?: number;
}

export interface BuildGraphRebuildSnapshotInput {
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    noteIds?: string[];
    noteFolders?: Record<string, GraphRebuildNoteFolderContext>;
    entities: RegisteredEntity[];
    occurrences: EntityOccurrence[];
    chunks?: GraphRebuildChunk[];
    relationshipHints?: GraphRebuildRelationshipHint[];
    noteTexts?: Record<string, string>;
    causalSidecar?: GraphRebuildCausalSidecarInput;
    embeddingProfile?: Partial<GraphRebuildEmbeddingProfile>;
    postProcessMode?: GraphIndexPostProcessMode;
    embeddingStagePolicy?: GraphIndexEmbeddingStagePolicy;
    candidateCount?: number;
    builtAt?: number;
    graphCompilerSidecar?: GraphCompilerDualWriteSidecar;
    calendarRegistrySnapshot?: CalendarRegistrySnapshot;
    documentProfileSummary?: GraphDocumentProfileSummary;
    documentSemanticSummary?: GraphDocumentSemanticSummary;
    operatorMutationJournal?: GraphOperatorMutationJournal;
    durabilityMode?: GraphBuildDurabilityMode;
    cpuProfiler?: GraphRebuildCpuProfiler;
}

export interface GraphRebuildNoteFolderContext {
    folderId: string;
    folderLabel: string;
    folderKind?: string;
    folderParentId?: string;
    narrativeId?: string;
    isNarrativeRoot?: boolean;
    isTypedRoot?: boolean;
}
