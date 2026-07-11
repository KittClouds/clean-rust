import { describe, expect, it } from 'vitest';

import {
    GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION,
    type GraphPromotionVerdictCertificate,
} from './graph-promotion-verdict';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import {
    GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION,
    type GraphReviewAdjudicationRunCertificate,
} from './graph-review-adjudication-certificate';
import {
    ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION,
    buildAtlasControlContract,
    type AtlasControlCard,
} from './atlas-control-contract';
import { GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION } from './graph-cross-document-bridge-certificate';

describe('buildAtlasControlContract', () => {
    it('publishes typed lanes, exact inventories, receipts, and text-pair NLI metadata', () => {
        const snapshot = snapshotFixture();
        const contract = buildAtlasControlContract({
            snapshot,
            entityCount: 50,
            edgeCount: 213,
            promotionCertificate: promotionCertificateFixture(),
        });

        expect(contract.schemaVersion).toBe(ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION);
        expect(contract.owner).toBe('atlas_control_contract_service');
        expect(contract.invariants.typedRowIdentities.status).toBe('passed');
        expect(contract.invariants.exactInventory.status).toBe('passed');
        expect(contract.invariants.reviewNliSeparated.status).toBe('passed');
        expect(contract.certificates.reviewAdjudication.model.inputKind).toBe('text_pair');

        expect(contract.inventoryById.review_ledger_rows).toMatchObject({
            totalRows: 2,
            visibleRows: 1,
            lane: 'review_ledger',
        });
        expect(contract.inventoryById.manual_decision_rows).toMatchObject({
            totalRows: 1,
            visibleRows: 1,
            lane: 'manual_decision',
            actionability: 'manual_receipt',
        });
        const manual = contract.rows.find((row) => row.identity.lane === 'manual_decision');
        expect(manual).toMatchObject({
            identity: { sourceContract: 'document_review', kind: 'graph_fact_candidate' },
            allowedActions: ['accept_review_row', 'reject_review_row'],
            receiptPolicy: {
                required: true,
                kind: 'document_review_action_receipt',
                reversible: true,
                topologyMutationAllowed: false,
            },
        });
        expect(new Set(contract.rows.map((row) => row.identity.id)).size).toBe(contract.rows.length);
    });

    it('enables one shared NLI action only when text-pair inputs exist', () => {
        const snapshot = snapshotFixture({ nliPairRows: 12 });
        const contract = buildAtlasControlContract({ snapshot });

        expect(card(contract, 'header-nli-pairs')).toMatchObject({
            value: 12,
            lane: 'nli_pair',
            actionability: 'model_run',
            allowedActions: ['run_nli'],
            receiptPolicy: { kind: 'review_adjudication_run_certificate' },
        });
        expect(card(contract, 'review-nli-pairs')).toMatchObject({
            value: 12,
            allowedActions: ['run_nli'],
        });
    });

    it('uses pending proofs when certificates are absent instead of passing by default', () => {
        const contract = buildAtlasControlContract({ snapshot: null });

        expect(contract.snapshotId).toBe('no-snapshot');
        expect(contract.invariants.noTopologyWrites.status).toBe('pending');
        expect(contract.invariants.candidateOnlyGovernance.status).toBe('pending');
        expect(contract.invariants.promotionReceiptGated.status).toBe('pending');
        expect(card(contract, 'header-graph-edges').value).toBe(0);
    });

    it('projects cross-document coverage and excerpts into the continuity room', () => {
        const snapshot = snapshotFixture();
        snapshot.crossDocumentBridgeCertificate = {
            schemaVersion: GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION,
            sourceDocumentIds: ['early', 'late'],
            generatedCandidates: 2,
            eligibleCandidates: 2,
            selectedCandidates: 1,
            rejectedCandidates: 1,
            pairCoverage: [{
                sourceDocumentId: 'early', targetDocumentId: 'late',
                generatedCandidates: 2, eligibleCandidates: 2,
                selectedCandidates: 1, rejectedCandidates: 1,
                selectedBridgeTypes: ['setup_payoff'], coverageMillis: 500,
            }],
            rejectionCounts: [{ reason: 'document_pair_type_quota', count: 1 }],
            selectedRows: [crossDocumentRow('selected')],
            rejectedRows: [{ ...crossDocumentRow('rejected'), rejectionReason: 'document_pair_type_quota' }],
            weakestRows: [crossDocumentRow('selected')],
            noTopologyWrites: true,
            invariantReceipts: ['chunk_semantic_bridge_candidate:no_topology_commit'],
        };

        const contract = buildAtlasControlContract({ snapshot });
        const inventory = contract.inventoryById.continuity_cross_document_rows;
        const candidate = inventory.rowIds
            .map((id) => contract.rowsById[id])
            .find((row) => row.identity.rawId.startsWith('selected:'));

        expect(inventory.totalRows).toBe(3);
        expect(contract.roomsById.continuity.inventoryCategoryIds)
            .toContain('continuity_cross_document_rows');
        expect(candidate).toMatchObject({
            sourceExcerpt: 'The warning was sealed beneath the gate.',
            targetExcerpt: 'The old warning was answered at the gate.',
            targetDocumentId: 'late',
            state: 'candidate',
        });
    });

    it('namespaces repeated raw row ids without losing their audit identity', () => {
        const snapshot = snapshotFixture();
        snapshot.documentReviewSummary!.rows.push({ ...snapshot.documentReviewSummary!.rows[0] });
        const contract = buildAtlasControlContract({ snapshot });
        const repeated = contract.rows.filter((row) => row.identity.rawId === 'review:ledger');

        expect(repeated).toHaveLength(2);
        expect(repeated.map((row) => row.identity.id)).toEqual([
            'document_review:review_ledger:review:ledger',
            'document_review:review_ledger:review:ledger#2',
        ]);
    });

    it('projects every Atlas room from declared inventories without summing review subsets', () => {
        const contract = buildAtlasControlContract({
            snapshot: snapshotFixture(),
            entityCount: 50,
            promotionCertificate: promotionCertificateFixture(),
        });

        expect(contract.roomIds).toEqual(['entities', 'structure', 'facts', 'continuity', 'review', 'discourse', 'metrics']);
        expect(contract.roomsById.review.totalRows).toBe(2);
        expect(contract.roomsById.review.visibleRows).toBe(1);
        expect(contract.inventoryById.manual_decision_rows.totalRows).toBe(1);
        expect(contract.inventoryById.promotion_verdict_rows.totalRows).toBe(1);
        expect(contract.roomsById.entities).toMatchObject({ totalRows: 50, visibleRows: 0, coverage: 'none' });
        for (const roomId of contract.roomIds) {
            for (const rowId of contract.roomsById[roomId].rowIds) {
                expect(contract.rowsById[rowId], `${roomId} references missing row ${rowId}`).toBeTruthy();
            }
        }
    });

    it('derives the Review room NLI button state from the shared pair inventory only', () => {
        const empty = buildAtlasControlContract({ snapshot: snapshotFixture() });
        const planned = buildAtlasControlContract({ snapshot: snapshotFixture({ nliPairRows: 12 }) });

        expect(empty.roomActionsById['review:run_nli']).toMatchObject({
            enabled: false,
            disabledReason: 'No premise/hypothesis pairs are available for ModernBERT.',
        });
        expect(planned.roomActionsById['review:run_nli']).toMatchObject({
            enabled: true,
            disabledReason: '',
        });
    });
});

function card(contract: ReturnType<typeof buildAtlasControlContract>, id: string): AtlasControlCard {
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
        memoryGovernanceCandidates: [governanceCandidate()],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        counters: {
            entities: 50,
            edges: 213,
            embeddingTargets: 661,
            factRows: 260,
            structureRows: 1218,
            discourseRows: 20,
            metricsRows: 1322,
        },
        documentReviewSummary: {
            rows: [
                reviewRow('review:ledger', false),
                reviewRow('review:manual', true),
            ],
        },
        reviewAdjudicationCertificate: reviewCertificateFixture(queue),
    } as unknown as GraphRebuildSnapshot;
}

function reviewRow(id: string, manual: boolean): any {
    return {
        id,
        objectId: `${id}:object`,
        objectKind: manual ? 'graph_fact_candidate' : 'document_unit',
        state: 'proposed',
        title: manual ? 'Candidate fact' : 'Audit row',
        subtitle: '',
        detail: 'deterministic review row',
        noteId: 'note:test',
        sourceStart: 0,
        sourceEnd: 10,
        confidence: 0.8,
        detector: 'test',
        parentUnitIds: [],
        childUnitIds: [],
        evidenceSpanIds: [],
        relatedObjectIds: [],
        why: [],
        availableActions: manual
            ? [reviewAction('accept_fact', true), reviewAction('reject_fact', true)]
            : [reviewAction('inspect_evidence_path', false)],
        receiptIds: [],
    };
}

function reviewAction(kind: string, requiresUserIntent: boolean): any {
    return {
        id: `action:${kind}`,
        kind,
        label: kind,
        targetObjectId: 'target',
        destructive: false,
        requiresUserIntent,
    };
}

function governanceCandidate(): any {
    return {
        schemaVersion: 'phoenix-memory-governance-candidate/v1',
        id: 'governance:1',
        targetId: 'chunk:1',
        targetKind: 'chunk',
        action: 'retain',
        reason: 'keep vivid',
        evidenceIds: ['evidence:1'],
        supportingEntityIds: [],
        relatedEventIds: [],
        relatedChunkIds: [],
        signals: {},
        confidence: 0.8,
        status: 'candidate',
        commitPolicy: 'candidate_only_no_topology_commit',
        noTopologyCommit: true,
        rationale: [],
    };
}

function crossDocumentRow(id: string): any {
    return {
        id: `bridge:${id}`,
        sourceDocumentId: 'early',
        targetDocumentId: 'late',
        sourceChunkId: 'early:chunk:0',
        targetChunkId: 'late:chunk:0',
        sourceExcerpt: 'The warning was sealed beneath the gate.',
        targetExcerpt: 'The old warning was answered at the gate.',
        bridgeType: 'setup_payoff',
        claim: 'The answer resolves the warning.',
        evidenceIds: ['evidence:early', 'evidence:late'],
        supportingEntityIds: ['entity:gate'],
        confidenceMillis: 820,
        noTopologyCommit: true,
    };
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
            input: {
                kind: 'text_pair',
                premiseField: 'premise',
                hypothesisField: 'hypothesis',
                outputLabels: ['entailment', 'neutral', 'contradiction'],
            },
        },
        queue: {
            ledgerRows: 2,
            manualDecisionRows: 1,
            nliPairRows: 0,
            nliExcludedRows: 0,
            duplicatePairs: 0,
            judgedRows: 0,
            appliedRows: 0,
            topologyWrites: 0,
            nliEligibilityPercent: 0,
            categories: [],
            excludedReasons: [],
            ...queue,
        },
        proof: {
            status: 'passed',
            candidateOnly: { status: 'passed', detail: 'candidate only' },
            noTopologyWrites: { status: 'passed', detail: 'no writes' },
            inputContract: { status: queue.nliPairRows ? 'passed' : 'pending', detail: 'text pair' },
            modelExecution: { status: 'pending', detail: 'not run' },
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
        receiptCount: 1,
        commitCount: 0,
        audit: {
            total: 1,
            acceptable: 1,
            alreadyCommitted: 0,
            blocked: 0,
            deferred: 0,
            rejected: 0,
            rollbackAvailable: 1,
            evidenceBlocked: 0,
            contradictionBlocked: 0,
            nliBlocked: 0,
            userOverrides: 0,
        },
        rows: [{
            id: 'verdict:1',
            receiptId: 'receipt:1',
            proposalId: 'proposal:1',
            family: 'backbone_promotion',
            truth: { subject: 'Kai', predicate: 'co_occurs_with', object: 'Rift' },
            candidateStatus: 'candidate',
            outcome: 'acceptable',
            status: 'acceptable',
            evidenceRefs: ['evidence:1'],
            witnessCount: 1,
            applyPlan: { rationale: 'test' },
            rollbackPlan: {
                availableNow: false,
                availableAfterCommit: true,
                rationale: 'reversible after commit',
            },
            gates: [],
            rationale: 'all gates passed',
        }],
    };
}
