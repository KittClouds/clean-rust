import { describe, expect, it } from 'vitest';

import { buildGraphDiscourseBridgeAdjudicationSummary } from './graph-discourse-bridge-adjudication';
import type { GraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';

describe('Graph Discourse Bridge Adjudication', () => {
    it('turns bridge candidates into reversible ledger-only decisions', () => {
        const summary = buildGraphDiscourseBridgeAdjudicationSummary(
            { id: 'snapshot:adjudication', scopeId: 'scope:adjudication', builtAt: 88 } as any,
            fakeCandidateSummary(),
            88,
        );

        expect(summary.schemaVersion).toBe('phoenix-discourse-bridge-adjudication/v1');
        expect(summary.invariant).toBe('discourse_bridge_decisions_are_ledger_only');
        expect(summary.decisions).toHaveLength(3);
        expect(summary.counters.acceptedCount).toBe(1);
        expect(summary.counters.supersededCount).toBe(1);
        expect(summary.counters.rejectedCount).toBe(1);
        expect(summary.counters.ledgerOnlyCount).toBe(3);
        expect(summary.counters.topologyCommitCount).toBe(0);
        expect(summary.counters.mutationAllowedCount).toBe(0);
        expect(summary.compactDecisionLedger.rowCount).toBe(3);
        expect(summary.compactDecisionLedger.rows.every((row) =>
            row.changedAtoms === 0 && row.changedFacts === 0 && row.changedEdges === 0,
        )).toBe(true);
        expect(summary.receipts.every((receipt) =>
            receipt.reversible
            && receipt.mutationAllowed === false
            && receipt.invariant === 'discourse_bridge_adjudication_ledger_only',
        )).toBe(true);
        expect(summary.decisions.every((decision) =>
            decision.ledgerOnly
            && decision.mutationAllowed === false
            && decision.affectedGraphAtomIds.length === 0
            && decision.affectedGraphFactIds.length === 0
            && decision.sourceHypothesis.length > 0,
        )).toBe(true);
    });
});

function fakeCandidateSummary(): GraphDiscourseBridgeCandidateSummary {
    const candidates = [
        candidate('strong', 0.82, 'embed:chunk:a', 'embed:chunk:b'),
        candidate('duplicate', 0.78, 'embed:chunk:b', 'embed:chunk:a'),
        candidate('noise', 0.28, 'embed:chunk:c', 'embed:chunk:d'),
    ];
    const judgments = [
        judgment(candidates[0].id, 'accept', 'meaningful_resonance', 0.84),
        judgment(candidates[1].id, 'accept', 'meaningful_resonance', 0.78),
        judgment(candidates[2].id, 'reject', 'reject_noise', 0.24),
    ];
    const evalRows = [
        evalRow(candidates[0].id, judgments[0].id, true, 0.84),
        evalRow(candidates[1].id, judgments[1].id, true, 0.78),
        evalRow(candidates[2].id, judgments[2].id, false, 0.24),
    ];
    return {
        schemaVersion: 'phoenix-discourse-bridge-candidates/v1',
        generatedAt: 88,
        sourceSnapshotId: 'snapshot:adjudication',
        sourceDiscourseSpineId: 'snapshot:adjudication',
        modelId: 'knowledgator/gliclass-instruct-base-v1.0',
        runner: 'gliclass-query-label-rerank',
        scoreSource: 'deterministic_calibration',
        invariant: 'discourse_bridges_are_candidates_not_edges',
        labels: [],
        candidates,
        inputs: [],
        judgments,
        evalRows,
        receipts: [],
        compactEvalLedger: { scopeId: 'scope:adjudication', builtAt: 88, rowCount: 3, rows: [] },
        counters: {} as any,
    };
}

function candidate(suffix: string, score: number, sourceTargetId: string, targetTargetId: string) {
    return {
        id: `candidate:${suffix}`,
        kind: 'discourse_resonance' as const,
        status: 'proposed' as const,
        sourceBridgeId: `bridge:${suffix}`,
        sourceTargetId,
        targetTargetId,
        evidenceTargetIds: [sourceTargetId, targetTargetId],
        sharedLabelIds: [`label:${suffix}`],
        sharedEntityIds: [],
        score,
        scoringBundle: {
            semanticScore: score,
            labelAgreement: score,
            entityOverlap: 0,
            distanceScore: score,
            corefPressure: 0,
            finalScore: score,
            scoreParts: [],
        },
        rationale: [`candidate ${suffix}`],
        reversibleReceiptIds: [`receipt:${suffix}`],
        mutationAllowed: false as const,
        createdAt: 88,
    };
}

function judgment(
    candidateId: string,
    decision: 'accept' | 'reject',
    topLabelKind: 'meaningful_resonance' | 'reject_noise',
    score: number,
) {
    return {
        id: `judgment:${candidateId}`,
        candidateId,
        candidateKind: 'discourse_resonance' as const,
        inputId: `input:${candidateId}`,
        decision,
        topLabelId: `label:${topLabelKind}`,
        topLabelKind,
        modelId: 'knowledgator/gliclass-instruct-base-v1.0',
        runner: 'gliclass-query-label-rerank' as const,
        scoreSource: 'deterministic_calibration' as const,
        relevanceScore: score,
        calibratedScore: score,
        scores: [],
        evidenceTargetIds: [`evidence:${candidateId}`],
        rationale: [`judgment ${decision}`],
        reversibleReceiptId: `receipt:judgment:${candidateId}`,
    };
}

function evalRow(candidateId: string, judgmentId: string, passed: boolean, score: number) {
    return {
        id: `eval:${candidateId}`,
        kind: passed ? 'accepted_looking_resonance' as const : 'weak_resonance' as const,
        candidateId,
        judgmentId,
        bridgeId: `bridge:${candidateId}`,
        expectedLabelKind: passed ? 'meaningful_resonance' as const : 'reject_noise' as const,
        score,
        passed,
        failureModes: passed ? [] : ['noise'],
        evidenceTargetIds: [`evidence:${candidateId}`],
        flags: passed ? ['accepted_looking'] : ['noise'],
        rationale: [`eval ${passed ? 'passed' : 'failed'}`],
    };
}
