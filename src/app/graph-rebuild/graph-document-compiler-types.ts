import type {
    EvidenceSpan,
    GraphDocumentSidecarSummary,
    GraphFactCandidate,
    RetrievalUnit,
} from './graph-document-sidecar';
import type {
    GraphDocumentReviewState,
    GraphDocumentReviewSummary,
} from './graph-document-review';

export type GraphDocumentCompileOutputKind =
    | 'entity_mention'
    | 'relation_candidate'
    | 'hyperedge'
    | 'evidence_backed_edge'
    | 'cross_doc_bridge'
    | 'document_structure_edge'
    | 'retrieval_overlay';

export type GraphDocumentCompileStatus =
    | 'pending_commit'
    | 'reviewable'
    | 'blocked'
    | 'ledger_only'
    | 'overlay_only';

export interface GraphDocumentCompilerBaseline {
    atomCount: number;
    factCount: number;
    edgeCount: number;
}

export interface GraphDocumentCompilerProvenance {
    sourceObjectId: string;
    sourceObjectKind: string;
    sourceReviewRowId?: string;
    reviewState?: GraphDocumentReviewState;
    noteId: string;
    sourceStart: number;
    sourceEnd: number;
    evidenceSpanIds: string[];
    lineageUnitIds: string[];
    reasons: string[];
}

export interface GraphDocumentCompiledEntityMention {
    id: string;
    surface: string;
    normalizedSurface: string;
    resolvedEntityId?: string;
    role: string;
    syntacticRoles?: string[];
    roleConfidence?: number;
    roleFailureReasons?: string[];
    recoveryKinds?: string[];
    roleDetectorReasons?: string[];
    noteId: string;
    sourceStart: number;
    sourceEnd: number;
    confidence: number;
    status: GraphDocumentCompileStatus;
    anchorPolicy: 'mention_only_not_user_anchor';
    evidenceSpanIds: string[];
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentRelationCandidate {
    id: string;
    predicate: string;
    frame?: string;
    frameFamily?: string;
    factuality?: string;
    speechAct?: string;
    semanticSituationId?: string;
    stateIntervalIds?: string[];
    eventOrderingIds?: string[];
    temporalConflictIds?: string[];
    subjectMentionIds: string[];
    objectMentionIds: string[];
    subjectEntityIds: string[];
    objectEntityIds: string[];
    evidenceSpanIds: string[];
    confidence: number;
    status: GraphDocumentCompileStatus;
    provenance: GraphDocumentCompilerProvenance;
}

export type GraphDocumentHyperedgeSlotType =
    | 'participant'
    | 'context'
    | 'evidence'
    | 'source_unit';

export interface GraphDocumentHyperedgeRole {
    id: string;
    role: string;
    semanticRole?: string;
    slotType?: GraphDocumentHyperedgeSlotType;
    syntacticRoles?: string[];
    targetId: string;
    targetKind: 'entity' | 'entity_mention' | 'evidence_span' | 'document_unit' | 'retrieval_unit';
    surface?: string;
    confidence: number;
    required?: boolean;
    resolved?: boolean;
    failureReasons?: string[];
    recoveryKinds?: string[];
    detectorReasons?: string[];
}

export interface GraphDocumentHyperedge {
    id: string;
    predicate: string;
    triggerPredicate?: string;
    frame?: string;
    frameFamily?: string;
    situationKind?: 'event' | 'state';
    factuality?: string;
    speechAct?: string;
    worldStateEligible?: boolean;
    semanticSituationId?: string;
    semanticPropositionId?: string;
    stateIntervalIds?: string[];
    eventOrderingIds?: string[];
    temporalConflictIds?: string[];
    compilationBasis?: 'semantic_situation_frame';
    mergeKey?: string;
    sourceKind: GraphFactCandidate['kind'];
    roles: GraphDocumentHyperedgeRole[];
    evidenceSpanIds: string[];
    confidence: number;
    status: GraphDocumentCompileStatus;
    nary: boolean;
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentEvidenceBackedEdge {
    id: string;
    sourceId: string;
    targetId: string;
    relationType: string;
    evidenceSpanIds: string[];
    confidence: number;
    status: GraphDocumentCompileStatus;
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentCrossDocBridge {
    id: string;
    topic: string;
    noteIds: string[];
    retrievalUnitId: string;
    semanticSituationIds?: string[];
    confidence: number;
    status: 'overlay_only';
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentStructureEdge {
    id: string;
    parentUnitId: string;
    childUnitId: string;
    relationType: 'document_contains';
    confidence: number;
    status: 'overlay_only';
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentRetrievalOverlay {
    id: string;
    retrievalUnitId: string;
    retrievalKind: RetrievalUnit['kind'];
    semanticSituationIds?: string[];
    keyedBy?: 'semantic_situation' | 'retrieval_unit_fallback';
    targetChunkIds: string[];
    evidenceSpanIds: string[];
    confidence: number;
    status: 'overlay_only' | 'ledger_only';
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentTemporalImpact {
    semanticSituationId?: string;
    stateIntervalIds: string[];
    eventOrderingIds: string[];
    temporalConflictIds: string[];
    factualityDecision: 'eligible' | 'review_required' | 'blocked' | 'not_applicable';
    temporalDecision: 'stable' | 'review_required' | 'blocked' | 'not_applicable';
}

export interface GraphDocumentTopologyDiff {
    id: string;
    outputKind: GraphDocumentCompileOutputKind;
    outputId: string;
    operation:
        | 'add_entity_mentions'
        | 'add_relation_candidate'
        | 'add_hyperedge'
        | 'add_evidence_edge'
        | 'add_cross_doc_bridge'
        | 'add_document_structure_edge'
        | 'add_retrieval_overlay';
    status: GraphDocumentCompileStatus;
    nativeCompileCandidate?: boolean;
    mutationAllowed: boolean;
    topologyCommit: boolean;
    beforeGraph: GraphDocumentCompilerBaseline;
    afterGraph: GraphDocumentCompilerBaseline;
    createdAtomIds: string[];
    createdFactIds: string[];
    createdEdgeIds: string[];
    evidenceSpanIds: string[];
    temporalImpact?: GraphDocumentTemporalImpact;
    rationale: string[];
}

export interface GraphDocumentTopologyReceipt {
    id: string;
    topologyDiffId: string;
    outputKind: GraphDocumentCompileOutputKind;
    outputId: string;
    semanticSituationId?: string;
    reversible: true;
    mutationAllowed: boolean;
    invariant:
        | 'document_compiler_native_payload_candidate'
        | 'document_compiler_ledger_only_no_topology_commit';
    undoPatch: {
        operation: 'remove_document_compiler_ledger_row';
        removeAtomIds: string[];
        removeFactIds: string[];
        removeEdgeIds: string[];
        restoreReviewState?: GraphDocumentReviewState;
    };
    detail: string;
    createdAt: number;
}

export interface GraphDocumentCompilationReviewItem {
    id: string;
    kind: 'contradiction' | 'merge';
    state: 'proposed';
    title: string;
    detail: string;
    situationIds: string[];
    hyperedgeIds: string[];
    evidenceSpanIds: string[];
    confidence: number;
    reasons: string[];
    recommendedAction: 'resolve_temporal_conflict' | 'merge_duplicate_situations';
    mutationAllowed: false;
}

export interface GraphDocumentCompilerCounters {
    entityMentions: number;
    relationCandidates: number;
    hyperedges: number;
    situationFrameHyperedges?: number;
    rawPredicateFactsBlocked?: number;
    factualityBlocked?: number;
    temporalBlocked?: number;
    naryHyperedges: number;
    evidenceBackedEdges: number;
    crossDocBridges: number;
    documentStructureEdges: number;
    retrievalOverlays: number;
    situationKeyedRetrievalOverlays?: number;
    contradictionReviewItems?: number;
    mergeReviewItems?: number;
    topologyDiffs: number;
    topologyCommits: number;
    nativeCompileCandidates?: number;
    ledgerOnly: number;
    overlayOnly: number;
    reviewable: number;
    blocked: number;
    receipts: number;
    reversibleReceipts: number;
    mutationAllowed: number;
    highConfidenceFacts: number;
    reviewedFacts: number;
    ambiguousFacts: number;
    byKind: Record<string, number>;
    byStatus: Record<string, number>;
}

export interface GraphDocumentCompilerSummary {
    schemaVersion: 'phoenix-document-compiler/v2';
    authority?: 'typescript_compile_plan';
    nativeCompilerRequired?: boolean;
    mutationPolicy?: 'ts_never_commits_document_graph';
    builtAt: number;
    sourceSidecarBuiltAt: number;
    sourceReviewBuiltAt: number;
    compilePolicy: 'situation_frames_reviewed_or_high_confidence_only';
    sidecarPolicy: 'structure_is_disposable_anchors_are_durable';
    topologyPolicy: 'topology_commits_require_reversible_situation_receipts';
    highConfidenceThreshold: number;
    entityMentions: GraphDocumentCompiledEntityMention[];
    relationCandidates: GraphDocumentRelationCandidate[];
    hyperedges: GraphDocumentHyperedge[];
    evidenceBackedEdges: GraphDocumentEvidenceBackedEdge[];
    crossDocBridges: GraphDocumentCrossDocBridge[];
    documentStructureEdges: GraphDocumentStructureEdge[];
    retrievalOverlays: GraphDocumentRetrievalOverlay[];
    contradictionReviewQueue?: GraphDocumentCompilationReviewItem[];
    mergeReviewQueue?: GraphDocumentCompilationReviewItem[];
    topologyDiffs: GraphDocumentTopologyDiff[];
    receipts: GraphDocumentTopologyReceipt[];
    counters: GraphDocumentCompilerCounters;
}

export interface BuildGraphDocumentCompilerInput {
    sidecar: GraphDocumentSidecarSummary;
    review: GraphDocumentReviewSummary;
    builtAt: number;
    baseline?: Partial<GraphDocumentCompilerBaseline>;
    highConfidenceThreshold?: number;
    entities?: Array<{ id: string; label: string; aliases?: string[] }>;
}

export interface GraphDocumentCompilerIndexes {
    evidenceById: Map<string, EvidenceSpan>;
}
