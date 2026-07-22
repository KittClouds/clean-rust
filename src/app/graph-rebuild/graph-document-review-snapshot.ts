import {
    applyGraphOperatorMutationDecisionToSnapshot,
    type GraphOperatorMutationDecision,
} from './graph-operator-mutation-journal';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export type GraphDocumentReviewDecision = GraphOperatorMutationDecision;

export function applyGraphDocumentReviewDecisionToSnapshot(
    snapshot: GraphRebuildSnapshot | null,
    objectIds: string[],
    decision: GraphDocumentReviewDecision,
    builtAt = Date.now(),
): GraphRebuildSnapshot | null {
    return applyGraphOperatorMutationDecisionToSnapshot(snapshot, objectIds, decision, builtAt);
}
