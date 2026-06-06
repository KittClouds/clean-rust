import { describe, expect, it } from 'vitest';

import { buildGraphDiscourseEvalLedgerSummary } from './graph-discourse-eval-ledger';

describe('Graph Discourse Eval Ledger', () => {
    it('exports adjudicated bridge decisions as compact training rows without graph changes', () => {
        const snapshot = fakeSnapshot();
        const summary = buildGraphDiscourseEvalLedgerSummary(snapshot as any, 99);

        expect(summary.schemaVersion).toBe('phoenix-discourse-eval-ledger/v1');
        expect(summary.datasetPurpose).toEqual(expect.arrayContaining([
            'classifier_training',
            'reranker_eval',
            'document_cluster_eval',
            'cross_doc_resolver_training',
        ]));
        expect(summary.entries).toHaveLength(3);
        expect(summary.counters.acceptedCandidates).toBe(1);
        expect(summary.counters.rejectedCandidates).toBe(1);
        expect(summary.counters.ambiguousCases).toBe(1);
        expect(summary.counters.modelDisagreements).toBe(1);
        expect(summary.counters.evalDisagreements).toBe(1);
        expect(summary.counters.manifoldDisagreements).toBeGreaterThan(0);
        expect(summary.counters.graphChangeRows).toBe(0);
        expect(summary.compactExport.rowCount).toBe(3);
        expect(summary.compactExport.rows.every((row) =>
            row.evidence > 0
            && row.changedEdges === 0
            && row.changedFacts === 0,
        )).toBe(true);
        expect(summary.entries.every((entry) =>
            entry.beforeGraph.edgeCount === entry.afterGraph.edgeCount
            && entry.afterGraph.edgeIds.length === 0
            && entry.afterGraph.factIds.length === 0,
        )).toBe(true);
    });
});

function fakeSnapshot() {
    const candidates = [
        candidate('accepted', 'discourse_resonance', 0.86),
        candidate('ambiguous', 'document_cluster_review', 0.62),
        candidate('rejected', 'cross_doc_resolution', 0.22),
    ];
    const judgments = [
        judgment(candidates[0].id, 'accept', 'meaningful_resonance', 0.86),
        judgment(candidates[1].id, 'review', 'document_cluster_review', 0.58),
        judgment(candidates[2].id, 'accept', 'cross_doc_resolution', 0.38),
    ];
    const evalRows = [
        evalRow(candidates[0].id, judgments[0].id, true, 'accepted_looking_resonance', 0.86),
        evalRow(candidates[1].id, judgments[1].id, true, 'weak_resonance', 0.58),
        evalRow(candidates[2].id, judgments[2].id, false, 'cross_doc_resolver_pressure', 0.38),
    ];
    const decisions = [
        decision(candidates[0].id, judgments[0].id, evalRows[0].id, 'accepted', 0.88),
        decision(candidates[1].id, judgments[1].id, evalRows[1].id, 'supported', 0.6),
        decision(candidates[2].id, judgments[2].id, evalRows[2].id, 'rejected', 0.31),
    ];
    return {
        id: 'snapshot:discourse-eval',
        scopeId: 'scope:discourse-eval',
        builtAt: 99,
        counters: { edges: 12 },
        discourseBridgeCandidateSummary: { candidates, judgments, evalRows },
        discourseBridgeAdjudicationSummary: { generatedAt: 99, decisions },
    };
}

function candidate(suffix: string, kind: string, score: number) {
    return {
        id: `candidate:${suffix}`,
        kind,
        sourceTargetId: `source:${suffix}`,
        targetTargetId: `target:${suffix}`,
        sharedEntityIds: suffix === 'rejected' ? ['entity:kai'] : [],
        scoringBundle: {
            semanticScore: suffix === 'rejected' ? 0.12 : score,
            labelAgreement: suffix === 'accepted' ? 0.14 : score,
            entityOverlap: suffix === 'rejected' ? 0.84 : 0.02,
            distanceScore: score,
            corefPressure: suffix === 'rejected' ? 0.9 : 0.04,
            finalScore: score,
        },
    };
}

function judgment(candidateId: string, decision: string, topLabelKind: string, score: number) {
    return {
        id: `judgment:${candidateId}`,
        candidateId,
        decision,
        scoreSource: 'deterministic_calibration',
        topLabelKind,
        relevanceScore: score,
        calibratedScore: score,
    };
}

function evalRow(candidateId: string, judgmentId: string, passed: boolean, kind: string, score: number) {
    return {
        id: `eval:${candidateId}`,
        candidateId,
        judgmentId,
        kind,
        expectedLabelKind: kind === 'cross_doc_resolver_pressure' ? 'cross_doc_resolution' : 'meaningful_resonance',
        score,
        passed,
        failureModes: passed ? [] : ['forced disagreement'],
    };
}

function decision(candidateId: string, judgmentId: string, evalRowId: string, state: string, score: number) {
    return {
        id: `decision:${candidateId}`,
        candidateId,
        judgmentId,
        evalRowId,
        candidateKind: candidateId.includes('rejected') ? 'cross_doc_resolution' : 'discourse_resonance',
        state,
        sourceHypothesis: `hypothesis:${candidateId}`,
        evidenceTargetIds: [`source:${candidateId}`, `target:${candidateId}`],
        scoringBundle: { finalScore: score },
        rationale: [`state:${state}`],
    };
}
