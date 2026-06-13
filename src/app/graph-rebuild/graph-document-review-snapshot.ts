import { buildGraphDocumentCompilerSummary } from './graph-document-compiler';
import {
    applyGraphDocumentReviewAction,
    type GraphDocumentReviewActionKind,
} from './graph-document-review';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export type GraphDocumentReviewDecision =
    | 'accepted'
    | 'rejected'
    | 'muted'
    | 'promoted_to_anchor'
    | 'compiled_to_graph'
    | 'ledger_only';

export function applyGraphDocumentReviewDecisionToSnapshot(
    snapshot: GraphRebuildSnapshot | null,
    objectIds: string[],
    decision: GraphDocumentReviewDecision,
    builtAt = Date.now(),
): GraphRebuildSnapshot | null {
    const review = snapshot?.documentReviewSummary;
    const sidecar = snapshot?.documentSidecarSummary;
    const actionKind = reviewActionKind(decision);
    if (!snapshot || !review || !sidecar || !actionKind || !objectIds.length) return null;

    const selectedIds = new Set(objectIds);
    let nextReview = review;
    let changed = false;
    for (const row of review.rows) {
        if (!selectedIds.has(row.objectId)) continue;
        if (!row.availableActions.some((action) => action.kind === actionKind)) continue;
        nextReview = applyGraphDocumentReviewAction(nextReview, { rowId: row.id, actionKind, createdAt: builtAt });
        changed = true;
    }
    if (!changed) return null;
    nextReview = { ...nextReview, builtAt };

    const nextCompiler = buildGraphDocumentCompilerSummary({
        sidecar,
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

    return {
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
    };
}

function reviewActionKind(decision: GraphDocumentReviewDecision): GraphDocumentReviewActionKind | null {
    if (decision === 'accepted') return 'accept_fact';
    if (decision === 'rejected') return 'reject_fact';
    if (decision === 'muted') return 'mute_detector_pattern';
    if (decision === 'promoted_to_anchor') return 'promote_sidecar_to_anchor';
    if (decision === 'compiled_to_graph') return 'compile_to_graph';
    if (decision === 'ledger_only') return 'demote_graph_fact_to_sidecar';
    return null;
}
