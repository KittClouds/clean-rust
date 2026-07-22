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
    it('reports exact ledger, text-pair, exclusion, and judgment categories', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'manual_stage8',
            rawResult: {
                inputCount: 96,
                plannedInputCount: 92,
                duplicateInputCount: 4,
                excludedInputCount: 11,
                resultCount: 92,
                topologyWrites: 0,
                stageSummaries: [
                    { stage: 'candidatePlan', durationMs: 12, counts: { plannedInputs: 92 } },
                ],
            },
            modelId: 'onnx-community/ModernBERT-base-nli-ONNX',
            modelLabel: 'ModernBERT NLI',
        });

        expect(certificate.schemaVersion).toBe(GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION);
        expect(certificate.queue).toMatchObject({
            ledgerRows: 1300,
            manualDecisionRows: 0,
            nliPairRows: 92,
            duplicatePairs: 4,
            judgedRows: 92,
            topologyWrites: 0,
            nliExcludedRows: 11,
        });
        expect(certificate.queue.excludedReasons.map((reason) => reason.id)).toEqual([
            'invalid_nli_pair',
            'duplicate_pair',
        ]);
        expect(certificate.model.input).toEqual({
            kind: 'text_pair',
            premiseField: 'premise',
            hypothesisField: 'hypothesis',
            outputLabels: ['entailment', 'neutral', 'contradiction'],
        });
        expect(certificate.proof).toMatchObject({
            status: 'passed',
            candidateOnly: { status: 'passed' },
            noTopologyWrites: { status: 'passed' },
            inputContract: { status: 'passed' },
            modelExecution: { status: 'passed' },
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
            },
        });

        expect(certificate.queue.nliPairRows).toBe(1);
        expect(certificate.queue.judgedRows).toBe(1);
        expect(certificate.queue.duplicatePairs).toBe(1);
    });

    it('does not couple text-pair NLI to a graph embedding dimension', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'manual_stage8',
            rawResult: {
                plannedInputCount: 24,
                resultCount: 24,
                dimension: 384,
            },
        });

        expect(certificate.model.input.kind).toBe('text_pair');
        expect(certificate.proof.inputContract.status).toBe('passed');
        expect(certificate.model).not.toHaveProperty('dimension');
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
            },
        });

        applyReviewAdjudicationCertificate(graph, certificate);

        expect(graph.reviewAdjudicationCertificate).toBe(certificate);
        expect(graph.counters).toMatchObject({
            reviewAdjudicationTotalRows: 1300,
            reviewAdjudicationEligibleRows: 12,
            reviewAdjudicationExcludedRows: 0,
            reviewAdjudicationJudgedRows: 0,
            reviewAdjudicationTopologyWrites: 0,
        });
    });

    it('publishes the shared view contract that blocks a zero-eligible NLI run', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'derived',
            rawResult: {},
        });

        const contract = buildReviewAdjudicationViewContract(certificate, {
            modelInitialized: true,
            hasScope: true,
        });

        expect(contract.schemaVersion).toBe(GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION);
        expect(contract.queue).toMatchObject({
            ledgerRows: 1300,
            nliPairRows: 0,
            nliExcludedRows: 0,
            totalLabel: '1,300 ledger rows',
            eligibleLabel: '0 NLI pairs',
        });
        expect(contract.action).toMatchObject({
            label: 'No NLI pairs',
            disabled: true,
            status: 'blocked',
        });
        expect(contract.action.reason).toContain('premise/hypothesis pairs');
        expect(contract.model.inputDetail).toContain('premise + hypothesis');
    });

    it('uses one action state for runnable pairwise review rows', () => {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: snapshot(),
            source: 'manual_stage8',
            rawResult: {
                plannedInputCount: 8,
            },
        });

        const contract = buildReviewAdjudicationViewContract(certificate, {
            modelInitialized: false,
            hasScope: true,
        });

        expect(contract.queue.summary).toBe('0 manual decisions / 8 NLI pairs / 1,300 ledger rows');
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
