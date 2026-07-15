import { buildGraphDocumentCompilePlanSummary } from './graph-document-compiler';
import {
    applyGraphDocumentReviewAction,
    type GraphDocumentReviewActionKind,
    type GraphDocumentReviewObjectKind,
    type GraphDocumentReviewRow,
    type GraphDocumentReviewState,
} from './graph-document-review';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import {
    graphTruthCommitLedgerFor,
    normalizeGraphTruthCommits,
    type GraphTruthCommitLike,
    type GraphTruthUiState,
} from './graph-truth-commit-ledger';

export const GRAPH_OPERATOR_MUTATION_JOURNAL_SCHEMA_VERSION = 'phoenix-graph-operator-mutation-journal/v1';
export const GRAPH_OPERATOR_MUTATION_INTENT_SCHEMA_VERSION = 'phoenix-graph-operator-mutation-intent/v1';

export type GraphOperatorMutationDecision =
    | 'accepted'
    | 'rejected'
    | 'deferred'
    | 'muted'
    | 'promoted_to_anchor'
    | 'compiled_to_graph'
    | 'ledger_only';

export type GraphOperatorMutationIntentStatus =
    | 'active'
    | 'applied'
    | 'conflicted'
    | 'undone';

export interface GraphOperatorMutationIntent {
    schemaVersion: typeof GRAPH_OPERATOR_MUTATION_INTENT_SCHEMA_VERSION;
    id: string;
    scopeId: string;
    sourceSnapshotId: string;
    sourceSnapshotBuiltAt: number;
    targetObjectId: string;
    targetObjectKind: GraphDocumentReviewObjectKind;
    actionKind: GraphDocumentReviewActionKind;
    previousState: GraphDocumentReviewState;
    requestedState: GraphDocumentReviewState;
    sourceFingerprint: string;
    sourceReceiptIds: string[];
    status: GraphOperatorMutationIntentStatus;
    canonicalState?: GraphTruthUiState;
    canonicalCommitId?: string;
    createdAt: number;
    appliedAt?: number;
    conflictedAt?: number;
    conflictReason?: string;
    undoneAt?: number;
    nativeDecisionId?: string;
    nativeDecisionReceiptId?: string;
}

export interface GraphOperatorMutationReceipt {
    id: string;
    intentId: string;
    actionKind: GraphDocumentReviewActionKind;
    targetObjectId: string;
    targetObjectKind: GraphDocumentReviewObjectKind;
    previousState: GraphDocumentReviewState;
    nextState: GraphDocumentReviewState;
    reversible: true;
    mutationAllowed: false;
    invariant: 'operator_mutation_journal_replays_review_state_before_topology_commit';
    canonicalState?: GraphTruthUiState;
    canonicalCommitId?: string;
    sourceFingerprint: string;
    detail: string;
    createdAt: number;
    nativeDecisionId?: string;
    nativeDecisionReceiptId?: string;
}

export interface GraphOperatorMutationJournalCounters {
    intents: number;
    active: number;
    applied: number;
    conflicted: number;
    undone: number;
    receipts: number;
    canonicalAccepted: number;
    canonicalCommitted: number;
    canonicalReverted: number;
    canonicalSuperseded: number;
}

export interface GraphOperatorMutationJournal {
    schemaVersion: typeof GRAPH_OPERATOR_MUTATION_JOURNAL_SCHEMA_VERSION;
    scopeId: string;
    updatedAt: number;
    intents: GraphOperatorMutationIntent[];
    receipts: GraphOperatorMutationReceipt[];
    counters: GraphOperatorMutationJournalCounters;
}

export interface GraphOperatorMutationReplayResult {
    snapshot: GraphRebuildSnapshot;
    journal: GraphOperatorMutationJournal;
    appliedIntentIds: string[];
    conflictedIntentIds: string[];
}

export interface GraphOperatorMutationReviewReplayResult {
    review: NonNullable<GraphRebuildSnapshot['documentReviewSummary']>;
    journal: GraphOperatorMutationJournal;
    appliedIntentIds: string[];
    conflictedIntentIds: string[];
    changedReview: boolean;
}

export function emptyGraphOperatorMutationJournal(
    scopeId: string,
    updatedAt = Date.now(),
): GraphOperatorMutationJournal {
    return withJournalCounters({
        schemaVersion: GRAPH_OPERATOR_MUTATION_JOURNAL_SCHEMA_VERSION,
        scopeId,
        updatedAt,
        intents: [],
        receipts: [],
    });
}

export function isGraphOperatorMutationJournal(value: unknown): value is GraphOperatorMutationJournal {
    const candidate = value as Partial<GraphOperatorMutationJournal> | null;
    return !!candidate
        && candidate.schemaVersion === GRAPH_OPERATOR_MUTATION_JOURNAL_SCHEMA_VERSION
        && typeof candidate.scopeId === 'string'
        && Array.isArray(candidate.intents)
        && Array.isArray(candidate.receipts);
}

export function graphOperatorMutationJournalFromTruthCommits(
    scopeId: string,
    commits: GraphTruthCommitLike[] | unknown,
    updatedAt = Date.now(),
): GraphOperatorMutationJournal {
    const truthLedger = graphTruthCommitLedgerFor(normalizeGraphTruthCommits(commits));
    const projected = truthLedger.records
        .filter((record) => record.targetKind !== 'commit')
        .sort((left, right) => left.generation - right.generation || left.targetId.localeCompare(right.targetId));
    const intents: GraphOperatorMutationIntent[] = projected.map((record) => ({
        schemaVersion: GRAPH_OPERATOR_MUTATION_INTENT_SCHEMA_VERSION,
        id: `operator-mutation:truth:${record.targetKind}:${record.targetId}`,
        scopeId,
        sourceSnapshotId: `graph-truth:${record.commitId}`,
        sourceSnapshotBuiltAt: record.committedAt,
        targetObjectId: record.targetId,
        targetObjectKind: 'graph_fact_candidate',
        actionKind: actionKindForTruthState(record.state),
        previousState: 'proposed',
        requestedState: requestedReviewStateForTruthState(record.state),
        sourceFingerprint: record.commitId,
        sourceReceiptIds: [record.targetKind === 'receipt' ? record.targetId : record.commitId],
        status: record.state === 'reverted' ? 'undone' : record.state === 'superseded' ? 'conflicted' : 'applied',
        canonicalState: record.state,
        canonicalCommitId: record.commitId,
        createdAt: record.committedAt,
        appliedAt: record.state === 'accepted' || record.state === 'committed' ? record.committedAt : undefined,
        conflictedAt: record.state === 'superseded' ? record.resolvedAt || updatedAt : undefined,
        conflictReason: record.state === 'superseded' ? 'canonical_commit_superseded' : undefined,
        undoneAt: record.state === 'reverted' ? record.resolvedAt || updatedAt : undefined,
    }));
    const receipts: GraphOperatorMutationReceipt[] = projected.map((record) => ({
        id: `operator-mutation-receipt:truth:${record.targetKind}:${record.targetId}`,
        intentId: `operator-mutation:truth:${record.targetKind}:${record.targetId}`,
        actionKind: actionKindForTruthState(record.state),
        targetObjectId: record.targetId,
        targetObjectKind: 'graph_fact_candidate',
        previousState: 'proposed',
        nextState: requestedReviewStateForTruthState(record.state),
        reversible: true,
        mutationAllowed: false,
        invariant: 'operator_mutation_journal_replays_review_state_before_topology_commit',
        canonicalState: record.state,
        canonicalCommitId: record.commitId,
        sourceFingerprint: record.commitId,
        detail: `canonical ${record.state} from ${record.commitId}`,
        createdAt: record.committedAt,
    }));
    return withJournalCounters({
        schemaVersion: GRAPH_OPERATOR_MUTATION_JOURNAL_SCHEMA_VERSION,
        scopeId,
        updatedAt,
        intents,
        receipts,
    });
}

export function mergeGraphOperatorMutationJournals(
    canonical: GraphOperatorMutationJournal,
    operator: GraphOperatorMutationJournal | undefined,
): GraphOperatorMutationJournal {
    if (!operator) return canonical;
    if (canonical.scopeId !== operator.scopeId) {
        throw new Error('Cannot merge operator mutation journals from different scopes.');
    }
    const intents = new Map(canonical.intents.map((intent) => [intent.id, intent]));
    const receipts = new Map(canonical.receipts.map((receipt) => [receipt.id, receipt]));
    for (const intent of operator.intents) intents.set(intent.id, intent);
    for (const receipt of operator.receipts) receipts.set(receipt.id, receipt);
    return withJournalCounters({
        schemaVersion: GRAPH_OPERATOR_MUTATION_JOURNAL_SCHEMA_VERSION,
        scopeId: canonical.scopeId,
        updatedAt: Math.max(canonical.updatedAt, operator.updatedAt),
        intents: [...intents.values()].sort((left, right) => left.createdAt - right.createdAt || left.id.localeCompare(right.id)),
        receipts: [...receipts.values()].sort((left, right) => left.createdAt - right.createdAt || left.id.localeCompare(right.id)),
    });
}

export function applyGraphOperatorMutationDecisionToSnapshot(
    snapshot: GraphRebuildSnapshot | null,
    objectIds: string[],
    decision: GraphOperatorMutationDecision,
    builtAt = Date.now(),
): GraphRebuildSnapshot | null {
    const review = snapshot?.documentReviewSummary;
    const actionKind = reviewActionKind(decision);
    if (!snapshot || !review || !snapshot.documentSidecarSummary || !actionKind || !objectIds.length) return null;

    const selectedIds = new Set(objectIds);
    const journal = snapshot.operatorMutationJournal
        || emptyGraphOperatorMutationJournal(snapshot.scopeId, builtAt);
    let nextJournal = journal;
    let added = false;
    for (const row of review.rows) {
        if (!selectedIds.has(row.objectId)) continue;
        const intent = createGraphOperatorMutationIntent(snapshot, row, actionKind, builtAt);
        if (!intent) continue;
        nextJournal = appendGraphOperatorMutationIntent(nextJournal, intent);
        added = true;
    }
    if (!added) return null;
    return replayGraphOperatorMutationJournal(snapshot, nextJournal, builtAt).snapshot;
}

export function replayGraphOperatorMutationJournal(
    snapshot: GraphRebuildSnapshot,
    journal: GraphOperatorMutationJournal,
    builtAt = Date.now(),
): GraphOperatorMutationReplayResult {
    const review = snapshot.documentReviewSummary;
    const sidecar = snapshot.documentSidecarSummary;
    if (!review || !sidecar) {
        const emptyReplay = withJournalCounters({ ...journal, updatedAt: builtAt });
        return {
            snapshot: withOperatorJournalCounters(snapshot, emptyReplay),
            journal: emptyReplay,
            appliedIntentIds: [],
            conflictedIntentIds: [],
        };
    }

    const replay = replayGraphOperatorMutationJournalReview(
        review,
        journal,
        snapshot.scopeId,
        builtAt,
    );
    const nextSnapshot = replay.changedReview
        ? withReviewCompiler(snapshot, replay.review, builtAt, replay.journal)
        : withOperatorJournalCounters(snapshot, replay.journal);
    return {
        snapshot: nextSnapshot,
        journal: replay.journal,
        appliedIntentIds: replay.appliedIntentIds,
        conflictedIntentIds: replay.conflictedIntentIds,
    };
}

export function replayGraphOperatorMutationJournalReview(
    review: NonNullable<GraphRebuildSnapshot['documentReviewSummary']>,
    journal: GraphOperatorMutationJournal,
    scopeId: string,
    builtAt = Date.now(),
): GraphOperatorMutationReviewReplayResult {
    let nextReview = review;
    let changedReview = false;
    const receiptsById = new Map(journal.receipts.map((receipt) => [receipt.id, receipt]));
    const appliedIntentIds: string[] = [];
    const conflictedIntentIds: string[] = [];
    const intents = [...journal.intents]
        .sort((left, right) => left.createdAt - right.createdAt || left.id.localeCompare(right.id))
        .map((intent) => {
            if (intent.status === 'undone') return intent;
            const row = nextReview.rows.find((candidate) => candidate.objectId === intent.targetObjectId);
            if (!row) {
                conflictedIntentIds.push(intent.id);
                return conflictedIntent(intent, builtAt, 'target_object_missing');
            }
            if (fingerprintGraphDocumentReviewRow(row) !== intent.sourceFingerprint) {
                conflictedIntentIds.push(intent.id);
                return conflictedIntent(intent, builtAt, 'source_fingerprint_changed');
            }
            if (row.state === intent.requestedState) {
                appliedIntentIds.push(intent.id);
                upsertOperatorReceipt(receiptsById, intent, row);
                return appliedIntent(intent, builtAt);
            }
            if (row.state !== intent.previousState) {
                conflictedIntentIds.push(intent.id);
                return conflictedIntent(intent, builtAt, `state_precondition_failed:${row.state}`);
            }
            if (!row.availableActions.some((action) => action.kind === intent.actionKind)) {
                conflictedIntentIds.push(intent.id);
                return conflictedIntent(intent, builtAt, 'action_unavailable');
            }
            nextReview = applyGraphDocumentReviewAction(nextReview, {
                rowId: row.id,
                actionKind: intent.actionKind,
                createdAt: intent.createdAt,
            });
            changedReview = true;
            appliedIntentIds.push(intent.id);
            upsertOperatorReceipt(receiptsById, intent, row);
            return appliedIntent(intent, builtAt);
        });

    const nextJournal = withJournalCounters({
        ...journal,
        scopeId,
        updatedAt: builtAt,
        intents,
        receipts: [...receiptsById.values()].sort((left, right) => left.createdAt - right.createdAt || left.id.localeCompare(right.id)),
    });
    return {
        review: changedReview ? { ...nextReview, builtAt } : nextReview,
        journal: nextJournal,
        appliedIntentIds,
        conflictedIntentIds,
        changedReview,
    };
}

export function fingerprintGraphDocumentReviewRow(row: GraphDocumentReviewRow): string {
    return simpleHash([
        row.objectId,
        row.objectKind,
        row.noteId,
        row.sourceStart,
        row.sourceEnd,
        row.detector,
        Math.round(row.confidence * 1000),
        row.title,
        row.subtitle,
        row.detail,
        row.parentUnitIds.join('|'),
        row.childUnitIds.join('|'),
        row.evidenceSpanIds.join('|'),
        row.relatedObjectIds.join('|'),
        row.availableActions.map((action) => action.kind).sort().join('|'),
    ].join('\u001f'));
}

function createGraphOperatorMutationIntent(
    snapshot: GraphRebuildSnapshot,
    row: GraphDocumentReviewRow,
    actionKind: GraphDocumentReviewActionKind,
    createdAt: number,
): GraphOperatorMutationIntent | null {
    const action = row.availableActions.find((candidate) => candidate.kind === actionKind);
    if (!action?.nextState) return null;
    const fingerprint = fingerprintGraphDocumentReviewRow(row);
    return {
        schemaVersion: GRAPH_OPERATOR_MUTATION_INTENT_SCHEMA_VERSION,
        id: `operator-mutation:intent:${simpleHash(`${snapshot.scopeId}:${row.objectId}:${actionKind}:${row.state}:${createdAt}`)}`,
        scopeId: snapshot.scopeId,
        sourceSnapshotId: snapshot.id,
        sourceSnapshotBuiltAt: snapshot.builtAt,
        targetObjectId: row.objectId,
        targetObjectKind: row.objectKind,
        actionKind,
        previousState: row.state,
        requestedState: action.nextState,
        sourceFingerprint: fingerprint,
        sourceReceiptIds: [...row.receiptIds],
        status: 'active',
        createdAt,
    };
}

function appendGraphOperatorMutationIntent(
    journal: GraphOperatorMutationJournal,
    intent: GraphOperatorMutationIntent,
): GraphOperatorMutationJournal {
    const intents = journal.intents.some((candidate) => candidate.id === intent.id)
        ? journal.intents
        : [...journal.intents, intent];
    return withJournalCounters({ ...journal, scopeId: intent.scopeId, updatedAt: intent.createdAt, intents });
}

function reviewActionKind(decision: GraphOperatorMutationDecision): GraphDocumentReviewActionKind | null {
    if (decision === 'accepted') return 'accept_fact';
    if (decision === 'rejected') return 'reject_fact';
    if (decision === 'muted') return 'mute_detector_pattern';
    if (decision === 'promoted_to_anchor') return 'promote_sidecar_to_anchor';
    if (decision === 'compiled_to_graph') return 'compile_to_graph';
    if (decision === 'ledger_only') return 'demote_graph_fact_to_sidecar';
    return null;
}

function actionKindForTruthState(state: GraphTruthUiState): GraphDocumentReviewActionKind {
    if (state === 'reverted') return 'demote_graph_fact_to_sidecar';
    if (state === 'superseded') return 'reject_fact';
    if (state === 'committed') return 'compile_to_graph';
    return 'accept_fact';
}

function requestedReviewStateForTruthState(state: GraphTruthUiState): GraphDocumentReviewState {
    if (state === 'reverted') return 'ledger_only';
    if (state === 'superseded') return 'rejected';
    if (state === 'committed') return 'compiled_to_graph';
    return 'accepted';
}

function appliedIntent(intent: GraphOperatorMutationIntent, appliedAt: number): GraphOperatorMutationIntent {
    return {
        ...intent,
        status: 'applied',
        appliedAt,
        conflictedAt: undefined,
        conflictReason: undefined,
    };
}

function conflictedIntent(
    intent: GraphOperatorMutationIntent,
    conflictedAt: number,
    conflictReason: string,
): GraphOperatorMutationIntent {
    return {
        ...intent,
        status: 'conflicted',
        conflictedAt,
        conflictReason,
    };
}

function upsertOperatorReceipt(
    receiptsById: Map<string, GraphOperatorMutationReceipt>,
    intent: GraphOperatorMutationIntent,
    row: GraphDocumentReviewRow,
): void {
    const id = `operator-mutation-receipt:${simpleHash(intent.id)}`;
    if (receiptsById.has(id)) return;
    receiptsById.set(id, {
        id,
        intentId: intent.id,
        actionKind: intent.actionKind,
        targetObjectId: intent.targetObjectId,
        targetObjectKind: intent.targetObjectKind,
        previousState: intent.previousState,
        nextState: intent.requestedState,
        reversible: true,
        mutationAllowed: false,
        invariant: 'operator_mutation_journal_replays_review_state_before_topology_commit',
        sourceFingerprint: intent.sourceFingerprint,
        detail: `${intent.actionKind} ${row.title}`,
        createdAt: intent.createdAt,
    });
}

function withReviewCompiler(
    snapshot: GraphRebuildSnapshot,
    nextReview: NonNullable<GraphRebuildSnapshot['documentReviewSummary']>,
    builtAt: number,
    journal: GraphOperatorMutationJournal,
): GraphRebuildSnapshot {
    const nextCompiler = buildGraphDocumentCompilePlanSummary({
        sidecar: snapshot.documentSidecarSummary!,
        review: nextReview,
        builtAt,
        entities: snapshot.nodes.map((node) => ({ id: node.entityId, label: node.label, aliases: node.aliases })),
        baseline: {
            atomCount: snapshot.nodes.length,
            factCount: snapshot.relationships.length
                + snapshot.events.length
                + snapshot.temporalEdges.length
                + snapshot.causalEdges.length
                + snapshot.memoryState.length,
            edgeCount: snapshot.edges.length,
        },
    });
    return withOperatorJournalCounters({
        ...snapshot,
        documentReviewSummary: nextReview,
        documentCompilerSummary: nextCompiler,
        counters: {
            ...snapshot.counters,
            documentReviewRows: nextReview.counters.rows,
            documentReviewActionableRows: nextReview.counters.actionableRows,
            documentReviewStateRecords: nextReview.counters.stateRecords,
            documentReviewActions: nextReview.counters.actions,
            documentReviewReceipts: nextReview.counters.receipts,
            documentReviewReversibleReceipts: nextReview.counters.reversibleReceipts,
            documentReviewProposedRows: nextReview.counters.proposedRows,
            documentReviewAcceptedRows: nextReview.counters.acceptedRows,
            documentReviewRejectedRows: nextReview.counters.rejectedRows,
            documentReviewMutedRows: nextReview.counters.mutedRows,
            documentReviewPromotedToAnchorRows: nextReview.counters.promotedToAnchorRows,
            documentReviewCompiledToGraphRows: nextReview.counters.compiledToGraphRows,
            documentReviewLedgerOnlyRows: nextReview.counters.ledgerOnlyRows,
            documentCompilerEntityMentions: nextCompiler.counters.entityMentions,
            documentCompilerRelationCandidates: nextCompiler.counters.relationCandidates,
            documentCompilerHyperedges: nextCompiler.counters.hyperedges,
            documentCompilerNaryHyperedges: nextCompiler.counters.naryHyperedges,
            documentCompilerEvidenceEdges: nextCompiler.counters.evidenceBackedEdges,
            documentCompilerCrossDocBridges: nextCompiler.counters.crossDocBridges,
            documentCompilerStructureEdges: nextCompiler.counters.documentStructureEdges,
            documentCompilerRetrievalOverlays: nextCompiler.counters.retrievalOverlays,
            documentCompilerTopologyDiffs: nextCompiler.counters.topologyDiffs,
            documentCompilerTopologyCommits: nextCompiler.counters.topologyCommits,
            documentCompilerNativeCompileCandidates: nextCompiler.counters.nativeCompileCandidates || 0,
            documentCompilerLedgerOnly: nextCompiler.counters.ledgerOnly,
            documentCompilerOverlayOnly: nextCompiler.counters.overlayOnly,
            documentCompilerReviewable: nextCompiler.counters.reviewable,
            documentCompilerBlocked: nextCompiler.counters.blocked,
            documentCompilerReceipts: nextCompiler.counters.receipts,
            documentCompilerReversibleReceipts: nextCompiler.counters.reversibleReceipts,
            documentCompilerMutationAllowed: nextCompiler.counters.mutationAllowed,
            documentCompilerHighConfidenceFacts: nextCompiler.counters.highConfidenceFacts,
            documentCompilerReviewedFacts: nextCompiler.counters.reviewedFacts,
            documentCompilerAmbiguousFacts: nextCompiler.counters.ambiguousFacts,
        },
    }, journal);
}

function withOperatorJournalCounters(
    snapshot: GraphRebuildSnapshot,
    journal: GraphOperatorMutationJournal,
): GraphRebuildSnapshot {
    return {
        ...snapshot,
        operatorMutationJournal: journal,
        counters: {
            ...snapshot.counters,
            operatorMutationIntents: journal.counters.intents,
            operatorMutationActive: journal.counters.active,
            operatorMutationApplied: journal.counters.applied,
            operatorMutationConflicted: journal.counters.conflicted,
            operatorMutationUndone: journal.counters.undone,
            operatorMutationReceipts: journal.counters.receipts,
        },
    };
}

function withJournalCounters(
    journal: Omit<GraphOperatorMutationJournal, 'counters'>,
): GraphOperatorMutationJournal {
    return {
        ...journal,
        counters: {
            intents: journal.intents.length,
            active: journal.intents.filter((intent) => intent.status === 'active').length,
            applied: journal.intents.filter((intent) => intent.status === 'applied').length,
            conflicted: journal.intents.filter((intent) => intent.status === 'conflicted').length,
            undone: journal.intents.filter((intent) => intent.status === 'undone').length,
            receipts: journal.receipts.length,
            canonicalAccepted: journal.intents.filter((intent) => intent.canonicalState === 'accepted').length,
            canonicalCommitted: journal.intents.filter((intent) => intent.canonicalState === 'committed').length,
            canonicalReverted: journal.intents.filter((intent) => intent.canonicalState === 'reverted').length,
            canonicalSuperseded: journal.intents.filter((intent) => intent.canonicalState === 'superseded').length,
        },
    };
}

function simpleHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}
