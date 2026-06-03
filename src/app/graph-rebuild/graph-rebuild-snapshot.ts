import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import type {
    GraphCompileReceipts,
    GraphCompilerDualWriteSidecar,
    GraphCompilerOutput,
    GraphCompilerProjectedUiEdge,
    GraphCompilerSource,
} from './graph-compiler-read-model';
import type { GraphModelV2Snapshot } from './graph-model-v2';

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
    admissionTier?: number;
    admissionStatus?: GraphRebuildSignalAdmissionStatus;
    admissionReason?: string;
    deferReason?: string;
    parentIds?: string[];
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
    lanes: GraphRebuildSignalTargetLaneReceipt[];
}

export interface GraphRebuildEmbeddingVector {
    targetId: string;
    modelId: string;
    dims: number;
    generation: number;
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
    mutationAllowed: boolean;
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
    ledgerOnly: boolean;
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
    temporalEdges: number;
    causalEdges: number;
    memoryState: number;
    embeddingTargets: number;
    embeddingTargetCandidates?: number;
    embeddingTargetDeferred?: number;
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
    entityLinking?: GraphRebuildEntityLinkCounters;
    meaningFrameChunks?: number;
    eventAspects?: number;
    dropReasons: GraphRebuildDropReasons;
    resolution?: GraphRebuildResolutionCounters;
}

export interface GraphRebuildBuildTimings {
    occurrenceLoadMs: number;
    chunkLoadMs: number;
    noteTextLoadMs: number;
    noteFolderLoadMs: number;
    dbLoadMs: number;
    occurrenceRecoverMs: number;
    snapshotBuildMs: number;
    stateCommitMs: number;
    snapshotPersistMs: number;
    snapshotSerializeMs: number;
    snapshotStoreMs: number;
    snapshotEventMs: number;
    snapshotPayloadChars: number;
    dbOpsMs: number;
    totalMs: number;
}

export interface GraphRebuildSnapshot {
    schemaVersion: 'phoenix-graph-rebuild/v1';
    id: string;
    source: 'phoenix-graph-rebuild';
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    noteIds: string[];
    builtAt: number;
    chunks: GraphRebuildChunk[];
    mentions: GraphRebuildMention[];
    entityAnchors: GraphRebuildEntityAnchor[];
    relationships: GraphRebuildRelationship[];
    events: GraphRebuildEvent[];
    episodes: GraphRebuildEpisode[];
    temporalEdges: GraphRebuildTemporalEdge[];
    causalEdges: GraphRebuildCausalEdge[];
    memoryState: GraphRebuildMemoryState[];
    embeddingTargets: GraphRebuildEmbeddingTarget[];
    embeddingTargetPlan?: GraphRebuildEmbeddingTargetPlan;
    embeddingVectors: GraphRebuildEmbeddingVector[];
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
    counters: GraphRebuildCounters;
    buildTimings?: GraphRebuildBuildTimings;
    resolutionSuggestions?: GraphRebuildResolutionSuggestion[];
}

export type GraphIndexPolicy = 'delta' | 'force';
export type GraphIndexPostProcessMode = 'core' | 'full';
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
    modelSelection: GraphIndexModelSelection;
    embeddingStagePolicy?: GraphIndexEmbeddingStagePolicy;
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
    postProcessFingerprint?: string;
    postProcessDiscoveryFingerprint?: string;
    postProcessCacheHit?: boolean;
    modelReadiness: GraphIndexModelReadiness[];
    startedAt: number;
    completedAt: number;
    durationMs: number;
    stageReceipts: GraphIndexStageReceipt[];
    projectionReceipts: GraphIndexProjectionReceipt[];
    snapshotId?: string;
    counters: GraphRebuildCounters;
    dropReasons: GraphRebuildDropReasons;
    message: string;
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
