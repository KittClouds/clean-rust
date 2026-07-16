import '@angular/compiler';
import { describe, expect, it } from 'vitest';

import {
    GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION,
    isGraphCrossDocumentBridgeRunCertificate,
    type GraphCrossDocumentBridgeRunCertificate,
} from './graph-cross-document-bridge-certificate';
import type {
    GraphRebuildContentBlobField,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import {
    graphRebuildSnapshotContentBlobDocuments,
    graphRebuildSnapshotToScopedDocument,
    scopedDocumentToGraphRebuildContentBlob,
    scopedDocumentToGraphRebuildSnapshot,
} from './graph-rebuild.service';
import {
    hydrateGraphSnapshotContent,
    type GraphSnapshotHydrationBlob,
} from './graph-snapshot-authority';

describe('GraphCrossDocumentBridgeRunCertificate', () => {
    it('accepts source-derived excerpts and candidate-only proof', () => {
        expect(isGraphCrossDocumentBridgeRunCertificate(certificate())).toBe(true);
    });

    it('rejects a certificate that cannot prove no topology writes', () => {
        const value = certificate();
        value.noTopologyWrites = false;
        expect(isGraphCrossDocumentBridgeRunCertificate(value)).toBe(false);
    });

    it('rejects certificate counts that do not reconcile with pair coverage', () => {
        const value = certificate();
        value.pairCoverage[0].rejectedCandidates = 0;
        expect(isGraphCrossDocumentBridgeRunCertificate(value)).toBe(false);
    });

    it('accepts explicitly paged audit rows without weakening strict validation', () => {
        const value = certificate();
        value.selectedRows = [];

        expect(isGraphCrossDocumentBridgeRunCertificate(value)).toBe(false);
        expect(isGraphCrossDocumentBridgeRunCertificate(value, true)).toBe(true);
    });

    it('persists and hydrates the native certificate through source rows', () => {
        const snapshot = snapshotFixture();
        snapshot.crossDocumentBridgeCertificate = certificate();

        const persisted = scopedDocumentToGraphRebuildSnapshot(
            graphRebuildSnapshotToScopedDocument(snapshot),
        )!;
        expect(persisted.crossDocumentBridgeCertificate).toBeUndefined();

        const blobs = Object.fromEntries(
            graphRebuildSnapshotContentBlobDocuments(snapshot).map((document) => {
                const blob = scopedDocumentToGraphRebuildContentBlob(document)!;
                return [blob.field, blob];
            }),
        ) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;

        const hydrated = hydrateGraphSnapshotContent(persisted, blobs);
        expect(hydrated.crossDocumentBridgeCertificate).toEqual(
            snapshot.crossDocumentBridgeCertificate,
        );
    });
});

function certificate(): GraphCrossDocumentBridgeRunCertificate {
    const row = {
        id: 'bridge:early:late',
        sourceDocumentId: 'early',
        targetDocumentId: 'late',
        sourceChunkId: 'early:chunk:0',
        targetChunkId: 'late:chunk:0',
        sourceExcerpt: 'The warning was sealed beneath the gate.',
        targetExcerpt: 'The old warning was answered at the gate.',
        bridgeType: 'setup_payoff' as const,
        claim: 'The answer resolves the warning.',
        evidenceIds: ['evidence:early', 'evidence:late'],
        supportingEntityIds: ['entity:gate'],
        confidenceMillis: 820,
        noTopologyCommit: true,
    };
    return {
        schemaVersion: GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION,
        sourceDocumentIds: ['early', 'late'],
        generatedCandidates: 2,
        eligibleCandidates: 2,
        selectedCandidates: 1,
        rejectedCandidates: 1,
        pairCoverage: [{
            sourceDocumentId: 'early',
            targetDocumentId: 'late',
            generatedCandidates: 2,
            eligibleCandidates: 2,
            selectedCandidates: 1,
            rejectedCandidates: 1,
            selectedBridgeTypes: ['setup_payoff'],
            coverageMillis: 500,
        }],
        rejectionCounts: [{ reason: 'document_pair_type_quota', count: 1 }],
        selectedRows: [row],
        rejectedRows: [{ ...row, id: 'bridge:rejected', rejectionReason: 'document_pair_type_quota' }],
        weakestRows: [row],
        noTopologyWrites: true,
        invariantReceipts: ['chunk_semantic_bridge_candidate:no_topology_commit'],
    };
}

function snapshotFixture(): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot:cross-document',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['early', 'late'],
        builtAt: 1,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
        counters: {
            entities: 0, aliases: 0, candidates: 0, mentions: 0, acceptedAnchors: 0,
            chunks: 0, relationshipCandidates: 0, relationships: 0,
            acceptedRelationships: 0, reviewRelationships: 0, rejectedRelationships: 0,
            events: 0, episodes: 0, temporalEdges: 0, causalEdges: 0, memoryState: 0,
            embeddingTargets: 0, embeddingVectors: 0, projectionRefs: 0, nodes: 0,
            edges: 0, dbOpsMs: 0, totalMs: 0,
        },
    };
}
