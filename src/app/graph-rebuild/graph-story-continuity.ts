import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_STORY_CONTINUITY_SCHEMA_VERSION = 'phoenix-story-continuity/v1' as const;
export const GRAPH_STORY_CONTINUITY_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-story-continuity-run-certificate/v1' as const;

export type GraphContinuityStatus = 'structural' | 'candidate' | 'review_required' | 'blocked';
export type GraphContinuityEvidenceClass =
    | 'source_span' | 'explicit_cue' | 'calendar' | 'document_order'
    | 'semantic_bridge' | 'state_transition' | 'legacy_adjacency';
export type GraphEpisodeBoundaryDecision =
    | 'document_start' | 'heading' | 'scene_break' | 'composite_transition';
export type GraphContinuityTemporalRelation =
    | 'before' | 'after' | 'overlaps' | 'during' | 'contains'
    | 'starts' | 'finishes' | 'recurs_after' | 'supersedes';
export type GraphContinuityCausalRelation =
    | 'direct_cause' | 'enabling_condition' | 'prevention'
    | 'motivation' | 'explanation' | 'consequence';
export type GraphEpisodeContinuityKind =
    | 'continuation' | 'setup_payoff' | 'recurrence' | 'parallel_action'
    | 'flashback' | 'state_transition' | 'cross_document_continuation'
    | 'motif_echo' | 'evidence_reframe';

export interface GraphContinuityEvent {
    id: string;
    sourceSituationId?: string;
    sourceEventId?: string;
    noteId: string;
    chunkId: string;
    sourceStart: number;
    sourceEnd: number;
    predicate: string;
    participantEntityIds: string[];
    evidenceIds: string[];
    factuality: string;
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphEpisodeBoundaryReceipt {
    id: string;
    noteId: string;
    beforeChunkId?: string;
    afterChunkId: string;
    sourceOffset: number;
    decision: GraphEpisodeBoundaryDecision;
    signals: Array<{ kind: string; detail: string; evidenceIds: string[] }>;
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphStoryEpisode {
    id: string;
    noteId: string;
    label: string;
    sourceStart: number;
    sourceEnd: number;
    chunkIds: string[];
    eventIds: string[];
    entityIds: string[];
    boundaryReceiptIds: string[];
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphContinuityTemporalCandidate {
    id: string;
    sourceId: string;
    targetId: string;
    relation: GraphContinuityTemporalRelation;
    evidenceClass: GraphContinuityEvidenceClass;
    evidenceIds: string[];
    cue?: string;
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphContinuityStateIntervalCandidate {
    id: string;
    noteId: string;
    subjectKey: string;
    stateKey: string;
    value?: string;
    polarity: string;
    startEventId: string;
    endEventId?: string;
    sourceStart: number;
    sourceEnd?: number;
    persists: boolean;
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphContinuityCausalCandidate {
    id: string;
    sourceEventId: string;
    targetEventId: string;
    relation: GraphContinuityCausalRelation;
    polarity: string;
    modality: string;
    attributionEntityId?: string;
    cue?: string;
    temporalLegal: boolean;
    evidenceClass: GraphContinuityEvidenceClass;
    evidenceIds: string[];
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphEpisodeContinuityCandidate {
    id: string;
    sourceEpisodeId: string;
    targetEpisodeId: string;
    kind: GraphEpisodeContinuityKind;
    evidenceClass: GraphContinuityEvidenceClass;
    evidenceIds: string[];
    supportingEntityIds: string[];
    rationale: string[];
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphContinuityConflictCandidate {
    id: string;
    noteId: string;
    kind: string;
    rowIds: string[];
    evidenceIds: string[];
    severity: string;
    confidenceMillis: number;
    status: GraphContinuityStatus;
    noTopologyCommit: boolean;
}

export interface GraphStoryContinuityCounters {
    events: number;
    boundaryReceipts: number;
    episodes: number;
    temporalCandidates: number;
    stateIntervals: number;
    causalCandidates: number;
    episodeConnections: number;
    conflicts: number;
    crossDocumentConnections: number;
    reviewRequired: number;
}

export interface GraphStoryContinuityRunCertificate {
    schemaVersion: typeof GRAPH_STORY_CONTINUITY_CERTIFICATE_SCHEMA_VERSION;
    sourceSnapshotId: string;
    sourceDocumentIds: string[];
    buildMicros: number;
    eventIdentityMicros: number;
    episodeBoundaryMicros: number;
    relationResolutionMicros: number;
    counters: GraphStoryContinuityCounters;
    noTopologyWrites: boolean;
    allRowsEvidenced: boolean;
    stableSourceIdentities: boolean;
    fixedBatchingDetected: boolean;
    invariantReceipts: string[];
}

export type GraphContinuityAction =
    | 'split_episode' | 'merge_episodes' | 'confirm_boundary'
    | 'confirm_ordering' | 'reject_ordering'
    | 'confirm_causal_link' | 'reject_causal_link'
    | 'resolve_continuity_conflict';

export interface GraphContinuityActionReceipt {
    schemaVersion: 'phoenix-story-continuity-action-receipt/v1';
    id: string;
    sourceSnapshotId: string;
    targetRowId: string;
    action: GraphContinuityAction;
    status: 'proposed';
    createdAt: number;
    reversible: true;
    noTopologyCommit: true;
}

export interface GraphStoryContinuityContract {
    schemaVersion: typeof GRAPH_STORY_CONTINUITY_SCHEMA_VERSION;
    source: 'rust_story_continuity';
    sourceSnapshotId: string;
    generatedAt: number;
    commitPolicy: 'candidate_only';
    noTopologyCommit: true;
    events: GraphContinuityEvent[];
    boundaryReceipts: GraphEpisodeBoundaryReceipt[];
    episodes: GraphStoryEpisode[];
    temporalCandidates: GraphContinuityTemporalCandidate[];
    stateIntervals: GraphContinuityStateIntervalCandidate[];
    causalCandidates: GraphContinuityCausalCandidate[];
    episodeConnections: GraphEpisodeContinuityCandidate[];
    conflicts: GraphContinuityConflictCandidate[];
    actionReceipts?: GraphContinuityActionReceipt[];
    certificate: GraphStoryContinuityRunCertificate;
}

export interface NativeStoryContinuityOutput {
    schemaVersion: 'phoenix-story-continuity-native-output/v1';
    source: 'rust';
    contract: GraphStoryContinuityContract;
    timing: { continuityBuildMicros: number; totalMicros: number };
}

export function isNativeStoryContinuityOutput(
    value: NativeStoryContinuityOutput | null | undefined,
): value is NativeStoryContinuityOutput {
    const contract = value?.contract;
    if (value?.schemaVersion !== 'phoenix-story-continuity-native-output/v1'
        || value.source !== 'rust'
        || !contract
        || contract.schemaVersion !== GRAPH_STORY_CONTINUITY_SCHEMA_VERSION
        || contract.source !== 'rust_story_continuity'
        || contract.commitPolicy !== 'candidate_only'
        || contract.noTopologyCommit !== true
        || contract.certificate?.noTopologyWrites !== true) return false;
    const rows = [
        ...contract.events, ...contract.boundaryReceipts, ...contract.episodes,
        ...contract.temporalCandidates, ...contract.stateIntervals,
        ...contract.causalCandidates, ...contract.episodeConnections, ...contract.conflicts,
    ];
    return rows.every((row) => row.noTopologyCommit === true)
        && contract.temporalCandidates.every((row) => !!row.sourceId && !!row.targetId)
        && contract.stateIntervals.every((row) =>
            !!row.subjectKey && !!row.stateKey && !!row.startEventId)
        && contract.conflicts.every((row) =>
            !!row.noteId && !!row.kind && Array.isArray(row.rowIds));
}

export function applyNativeStoryContinuityContract(
    snapshot: GraphRebuildSnapshot,
    contract: GraphStoryContinuityContract,
): void {
    snapshot.storyContinuity = contract;
    snapshot.counters = {
        ...snapshot.counters,
        continuityEvents: contract.events.length,
        continuityBoundaryReceipts: contract.boundaryReceipts.length,
        continuityEpisodes: contract.episodes.length,
        continuityTemporalCandidates: contract.temporalCandidates.length,
        continuityCausalCandidates: contract.causalCandidates.length,
        continuityStateIntervals: contract.stateIntervals.length,
        continuityEpisodeConnections: contract.episodeConnections.length,
        continuityConflicts: contract.conflicts.length,
        continuityCrossDocumentConnections: contract.certificate.counters.crossDocumentConnections,
        continuityReviewRequired: contract.certificate.counters.reviewRequired,
    };
}

export function appendStoryContinuityActionReceipt(
    snapshot: GraphRebuildSnapshot,
    targetRowId: string,
    action: GraphContinuityAction,
    createdAt = Date.now(),
): GraphContinuityActionReceipt | null {
    const contract = snapshot.storyContinuity;
    if (!contract) return null;
    const targetExists = [
        ...contract.boundaryReceipts,
        ...contract.episodes,
        ...contract.temporalCandidates,
        ...contract.causalCandidates,
        ...contract.conflicts,
    ].some((row) => row.id === targetRowId);
    if (!targetExists) return null;
    const receipt: GraphContinuityActionReceipt = {
        schemaVersion: 'phoenix-story-continuity-action-receipt/v1',
        id: `continuity-action:${snapshot.id}:${createdAt}:${action}:${targetRowId}`,
        sourceSnapshotId: snapshot.id,
        targetRowId,
        action,
        status: 'proposed',
        createdAt,
        reversible: true,
        noTopologyCommit: true,
    };
    contract.actionReceipts = [...(contract.actionReceipts || []), receipt];
    return receipt;
}
