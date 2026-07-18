import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_ASSERTED_TRUTH_AUTHORITY = 'deterministic_graph_processing' as const;
export const GRAPH_SEMANTIC_DISCOVERY_POLICY = 'candidate_only_explicit_promotion_required' as const;

export function assertGraphAssertedTruthAuthority(snapshot: GraphRebuildSnapshot): void {
    const issues: string[] = [];
    const semanticEdgeCount = snapshot.edges.filter((edge) =>
        edge.id.startsWith('semantic-adjudication:'),
    ).length;
    const adjudication = snapshot.semanticAdjudicationSummary;

    if (semanticEdgeCount) issues.push(`semantic adjudication edges ${semanticEdgeCount}`);
    if (snapshot.counters.semanticAdjudicationMutations) {
        issues.push(`semantic mutation counter ${snapshot.counters.semanticAdjudicationMutations}`);
    }
    if (snapshot.counters.semanticAdjudicationTopologyCommits) {
        issues.push(`semantic topology commit counter ${snapshot.counters.semanticAdjudicationTopologyCommits}`);
    }
    if (adjudication?.mutations.length) {
        issues.push(`semantic topology mutations ${adjudication.mutations.length}`);
    }
    if (adjudication?.counters.mutationCount || adjudication?.counters.appliedMutationCount) {
        issues.push('semantic mutation summary');
    }
    if (adjudication?.counters.topologyCommitCount) {
        issues.push(`semantic topology commits ${adjudication.counters.topologyCommitCount}`);
    }
    if (adjudication?.receipts.some((receipt) => receipt.mutationAllowed)) {
        issues.push('semantic mutation receipt');
    }
    if (adjudication?.receipts.some((receipt) => receipt.invariant !== GRAPH_SEMANTIC_DISCOVERY_POLICY)) {
        issues.push('semantic discovery policy drift');
    }
    if (adjudication?.decisions.some((decision) =>
        !decision.ledgerOnly
        || Boolean(decision.mutationId)
        || decision.affectedGraphAtomIds.length > 0
        || decision.affectedGraphFactIds.length > 0,
    )) {
        issues.push('semantic decision owns asserted topology');
    }

    if (issues.length) {
        throw new Error(
            `Graph asserted truth authority failed for ${snapshot.id}: `
            + `${GRAPH_ASSERTED_TRUTH_AUTHORITY} required; ${issues.join(', ')}`,
        );
    }
}
