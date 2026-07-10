import { describe, expect, it } from 'vitest';

import {
    applyReviewAdjudicationCertificate,
    buildReviewAdjudicationViewContract,
    buildReviewAdjudicationRunCertificate,
    GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION,
    GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION,
} from './graph-review-adjudication-certificate';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('buildReviewAdjudicationRunCertificate', () => {
    it('reports the total review queue, NLI-eligible rows, and excluded reasons', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'manual_stage8',
            rawResult: {
                inputCount: 96,
                plannedInputCount: 92,
                duplicateInputCount: 4,
                resultCount: 92,
                topologyWrites: 0,
                dimension: 768,
                stageSummaries: [
                    { stage: 'candidatePlan', durationMs: 12, counts: { plannedInputs: 92 } },
                ],
            },
            modelId: 'onnx-community/ModernBERT-base-nli-ONNX',
            modelLabel: 'ModernBERT NLI',
            dimensionLabel: '768d',
            embeddingDimension: 768,
        });

        expect(certificate.schemaVersion).toBe(GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION);
        expect(certificate.queue).toMatchObject({
            totalReviewRows: 1300,
            nliEligibleRows: 92,
            duplicateRows: 4,
            judgedRows: 92,
            topologyWrites: 0,
            excludedRows: 1204,
        });
        expect(certificate.queue.excludedReasons.map((reason) => reason.id)).toEqual([
            'non_nli_review_row',
            'duplicate_pair',
        ]);
        expect(certificate.proof).toMatchObject({
            candidateOnly: true,
            noTopologyWrites: true,
            dimensionContractPassed: true,
            modelRan: true,
        });
    });

    it('counts result arrays when the native response omits explicit row counters', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'graph_build',
            rawResult: {
                inputs: [{ id: 1 }, { id: 2 }],
                plannedInputs: [{ id: 1 }],
                judgments: [{ judgmentId: 'j1', predictedLabel: 'entailment', confidence: 0.9 }],
                duplicateInputCount: 1,
                dimension: 768,
            },
            dimensionLabel: '768d',
        });

        expect(certificate.queue.nliEligibleRows).toBe(1);
        expect(certificate.queue.judgedRows).toBe(1);
        expect(certificate.queue.duplicateRows).toBe(1);
    });

    it('fails the dimension proof when the runtime output violates the explicit contract', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'manual_stage8',
            rawResult: {
                plannedInputCount: 24,
                resultCount: 24,
                dimension: 384,
            },
            dimensionLabel: '768d',
        });

        expect(certificate.model).toMatchObject({
            dimension: 384,
            dimensionLabel: '768d',
        });
        expect(certificate.proof.dimensionContractPassed).toBe(false);
    });

    it('attaches the certificate counters to the snapshot without graph writes', () => {
        const graph = snapshot();
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: graph,
            source: 'derived',
            rawResult: {
                plannedInputCount: 12,
                resultCount: 0,
                topologyWrites: 0,
                dimension: 768,
            },
            dimensionLabel: '768d',
        });

        applyReviewAdjudicationCertificate(graph, certificate);

        expect(graph.reviewAdjudicationCertificate).toBe(certificate);
        expect(graph.counters).toMatchObject({
            reviewAdjudicationTotalRows: 1300,
            reviewAdjudicationEligibleRows: 12,
            reviewAdjudicationExcludedRows: 1288,
            reviewAdjudicationJudgedRows: 0,
            reviewAdjudicationTopologyWrites: 0,
            reviewAdjudicationDimension: 768,
        });
    });

    it('publishes the shared view contract that blocks a zero-eligible NLI run', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'derived',
            rawResult: {},
            dimensionLabel: '768d',
        });

        const contract = buildReviewAdjudicationViewContract(certificate, {
            modelInitialized: true,
            hasScope: true,
        });

        expect(contract.schemaVersion).toBe(GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION);
        expect(contract.queue).toMatchObject({
            totalReviewRows: 1300,
            nliEligibleRows: 0,
            excludedRows: 1300,
            totalLabel: '1,300 review rows',
            eligibleLabel: '0 NLI eligible',
        });
        expect(contract.action).toMatchObject({
            label: 'No NLI pairs',
            disabled: true,
            status: 'blocked',
        });
        expect(contract.action.reason).toContain('pairwise ModernBERT input contract');
        expect(contract.model.embeddingDimensionDetail).toContain('embedding target contract');
    });

    it('uses one action state for runnable pairwise review rows', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'manual_stage8',
            rawResult: {
                plannedInputCount: 8,
                dimension: 768,
            },
            dimensionLabel: '768d',
        });

        const contract = buildReviewAdjudicationViewContract(certificate, {
            modelInitialized: false,
            hasScope: true,
        });

        expect(contract.queue.summary).toBe('8 NLI eligible / 1,300 review rows');
        expect(contract.action).toMatchObject({
            label: 'Load + Run',
            disabled: false,
            status: 'planned',
        });
        expect(contract.proof.tone).toBe('review');
    });
});

function snapshot(): GraphRebuildSnapshot {
    return {
        id: 'snapshot:review-certificate',
        scopeKind: 'note',
        scopeId: 'note:shortrun',
        noteIds: ['note:shortrun'],
        counters: {
            documentReviewRows: 1300,
            semanticEvalLedgerRows: 627,
            discourseEvalLedgerRows: 0,
        },
        embeddingProfile: {
            dimensionLabel: '768d',
            selectedDimensions: 768,
        },
    } as unknown as GraphRebuildSnapshot;
}
