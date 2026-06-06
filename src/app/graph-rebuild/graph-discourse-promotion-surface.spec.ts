import { describe, expect, it } from 'vitest';

import { buildGraphDiscoursePromotionSurfaceSummary } from './graph-discourse-promotion-surface';

describe('Graph Discourse Promotion Surface', () => {
    it('surfaces ledger rows as read-only wormholes, clusters, resolver hints, and compiler hints', () => {
        const summary = buildGraphDiscoursePromotionSurfaceSummary(fakeSnapshot() as any, 111);

        expect(summary.schemaVersion).toBe('phoenix-discourse-promotion-surface/v1');
        expect(summary.invariant).toBe('discourse_promotion_surface_no_topology_commit');
        expect(summary.chunkWormholes).toHaveLength(1);
        expect(summary.documentClusters).toHaveLength(1);
        expect(summary.resolverCandidates).toHaveLength(1);
        expect(summary.compilerHints).toHaveLength(3);
        expect(summary.compactSurface.rowCount).toBe(3);
        expect(summary.counters.graphPatchCount).toBe(0);
        expect(summary.counters.mutationAllowedCount).toBe(0);
        expect(summary.compilerHints.every((hint) =>
            hint.status === 'read_model_only'
            && hint.mutationAllowed === false
            && hint.proposedEdgeType,
        )).toBe(true);
        expect(summary.receipts.every((receipt) =>
            receipt.reversible
            && receipt.mutationAllowed === false
            && receipt.invariant === 'discourse_promotion_surface_no_topology_commit',
        )).toBe(true);
    });
});

function fakeSnapshot() {
    const candidates = [
        candidate('wormhole', 'discourse_resonance', 'source:a', 'target:a'),
        candidate('cluster', 'document_cluster_review', 'source:b', 'target:b'),
        candidate('resolver', 'cross_doc_resolution', 'source:c', 'target:c'),
    ];
    const entries = [
        entry(candidates[0].id, 'accepted_candidate', 'accepted', 0.9),
        entry(candidates[1].id, 'ambiguous_case', 'supported', 0.62),
        entry(candidates[2].id, 'accepted_candidate', 'accepted', 0.74),
    ];
    return {
        id: 'snapshot:promotion',
        scopeId: 'scope:promotion',
        builtAt: 111,
        discourseBridgeCandidateSummary: { candidates },
        discourseEvalLedgerSummary: { generatedAt: 111, entries },
    };
}

function candidate(suffix: string, kind: string, sourceTargetId: string, targetTargetId: string) {
    return {
        id: `candidate:${suffix}`,
        kind,
        sourceClusterId: suffix === 'cluster' ? 'cluster:domain:one' : undefined,
        sourceTargetId,
        targetTargetId,
        evidenceTargetIds: [sourceTargetId, targetTargetId, `evidence:${suffix}`],
        sharedEntityIds: suffix === 'resolver' ? ['entity:kai'] : [],
    };
}

function entry(candidateId: string, label: string, state: string, score: number) {
    return {
        id: `entry:${candidateId}`,
        candidateId,
        decisionId: `decision:${candidateId}`,
        label,
        adjudicationState: state,
        score,
        evidenceTargetIds: [`evidence:${candidateId}`],
        flags: label === 'ambiguous_case' ? ['ambiguous_case'] : ['accepted_candidate'],
    };
}
