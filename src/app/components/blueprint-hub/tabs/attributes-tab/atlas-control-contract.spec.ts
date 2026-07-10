import { describe, expect, it } from 'vitest';

import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import {
    GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION,
    type GraphPromotionVerdictCertificate,
} from '../../../../graph-rebuild/graph-promotion-verdict';
import {
    GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION,
    type GraphReviewAdjudicationRunCertificate,
} from '../../../../graph-rebuild/graph-review-adjudication-certificate';
import {
    ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION,
    buildAtlasControlContract,
    type AtlasControlCard,
} from './atlas-control-contract';

describe('buildAtlasControlContract', () => {
    it('separates total review rows from pairwise ModernBERT work', () => {
        const contract = buildAtlasControlContract({
            snapshot: snapshotFixture(),
            entityCount: 50,
            edgeCount: 213,
        });

        expect(contract.schemaVersion).toBe(ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION);
        expect(contract.invariants.graphTabSourceOfTruth).toBe('atlas_control');
        expect(contract.invariants.reviewNliSeparated).toBe(true);

        expect(card(contract, 'review-ledger')).toMatchObject({
            value: 1300,
            intent: 'read_only_ledger',
            countScope: 'total_ledger',
            actionability: 'inspect_only',
        });
        expect(card(contract, 'review-nli-pairs')).toMatchObject({
            value: 0,
            intent: 'model_action',
            countScope: 'nli_pairwise',
            actionability: 'none',
            allowedActions: [],
        });
        expect(card(contract, 'workflow-nli-pairs').detail).toContain('none match');
    });

    it('only enables the NLI action when the pair queue has rows', () => {
        const snapshot = snapshotFixture({
            nliEligibleRows: 12,
            excludedRows: 1288,
        });
        const contract = buildAtlasControlContract({ snapshot });

        expect(card(contract, 'header-nli-eligible')).toMatchObject({
            value: 12,
            actionability: 'model_run',
            allowedActions: ['run_nli'],
        });
        expect(card(contract, 'review-nli-pairs')).toMatchObject({
            value: 12,
            actionability: 'model_run',
            allowedActions: ['run_nli'],
        });
    });

    it('marks governance and promotion as certificate surfaces', () => {
        const contract = buildAtlasControlContract({
            snapshot: snapshotFixture(),
            promotionCertificate: promotionCertificateFixture(),
        });

        expect(contract.invariants.noTopologyWrites).toBe(true);
        expect(contract.invariants.candidateOnlyGovernance).toBe(true);
        expect(card(contract, 'governance-candidates')).toMatchObject({
            value: 23,
            intent: 'diagnostic_proof',
            countScope: 'certificate',
        });
        expect(card(contract, 'promotion-verdicts')).toMatchObject({
            value: 24,
            intent: 'promotion_preview',
            actionability: 'promotion_preview',
        });
    });

    it('returns a waiting contract without a snapshot', () => {
        const contract = buildAtlasControlContract({ snapshot: null });

        expect(contract.snapshotId).toBe('no-snapshot');
        expect(card(contract, 'header-graph-edges').value).toBe(0);
        expect(card(contract, 'workflow-run-proof')).toMatchObject({
            value: '--',
            actionability: 'none',
        });
    });
});

function card(
    contract: ReturnType<typeof buildAtlasControlContract>,
    id: string,
): AtlasControlCard {
    const found = contract.cardsById[id];
    expect(found, `missing card ${id}`).toBeTruthy();
    return found;
}

function snapshotFixture(
    queue: Partial<GraphReviewAdjudicationRunCertificate['queue']> = {},
): GraphRebuildSnapshot {
    return {
        id: 'obal:test-snapshot',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note:test'],
        nodes: [],
        edges: [],
        chunks: [],
        mentions: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        memoryGovernanceCandidates: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        counters: {
            entities: 50,
            edges: 213,
            embeddingTargets: 661,
            memoryGovernanceCandidates: 23,
            promotionVerdictRows: 24,
            documentReviewActionableRows: 161,
        },
        reviewAdjudicationCertificate: reviewCertificateFixture(queue),
    } as unknown as GraphRebuildSnapshot;
}

function reviewCertificateFixture(
    queue: Partial<GraphReviewAdjudicationRunCertificate['queue']> = {},
): GraphReviewAdjudicationRunCertificate {
    return {
        schemaVersion: GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION,
        generatedAt: 1,
        source: 'manual_stage8',
        document: {
            snapshotId: 'obal:test-snapshot',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note:test'],
        },
        model: {
            modelId: 'onnx-community/ModernBERT-base-nli',
            modelLabel: 'ModernBERT NLI',
            dimension: 768,
            dimensionLabel: '768d',
        },
        queue: {
            totalReviewRows: 1300,
            nliEligibleRows: 0,
            excludedRows: 1300,
            duplicateRows: 0,
            judgedRows: 0,
            appliedRows: 0,
            topologyWrites: 0,
            nliEligibilityPercent: 0,
            excludedReasons: [
                {
                    id: 'non-nli-review-row',
                    label: 'Non-NLI review rows',
                    count: 1300,
                    detail: 'Only pairwise candidate rows enter ModernBERT.',
                },
            ],
            ...queue,
        },
        proof: {
            candidateOnly: true,
            noTopologyWrites: true,
            dimensionContractPassed: true,
            modelRan: false,
        },
        rows: [],
        stageSummaries: [],
    };
}

function promotionCertificateFixture(): GraphPromotionVerdictCertificate {
    return {
        schemaVersion: GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION,
        source: 'test',
        noTopologyWrites: true,
        receiptCount: 24,
        commitCount: 0,
        audit: {
            total: 24,
            acceptable: 24,
            alreadyCommitted: 0,
            blocked: 0,
            deferred: 0,
            rejected: 0,
            rollbackAvailable: 0,
            evidenceBlocked: 0,
            contradictionBlocked: 0,
            nliBlocked: 0,
            userOverrides: 0,
        },
        rows: [],
    };
}
