import '@angular/compiler';
import { describe, expect, it } from 'vitest';

import {
    appendStoryContinuityActionReceipt,
    applyNativeStoryContinuityContract,
    isNativeStoryContinuityOutput,
    type GraphStoryContinuityContract,
} from './graph-story-continuity';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import type { GraphRebuildContentBlobField } from './graph-rebuild-snapshot';
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

describe('graph story continuity contract', () => {
    it('attaches candidate-only authority and exact counters', () => {
        const snapshot = snapshotFixture();
        const contract = contractFixture();

        applyNativeStoryContinuityContract(snapshot, contract);

        expect(snapshot.storyContinuity).toBe(contract);
        expect(snapshot.counters.continuityEpisodes).toBe(1);
        expect(snapshot.counters.continuityBoundaryReceipts).toBe(1);
        expect(snapshot.counters.continuityTemporalCandidates).toBe(1);
        expect(snapshot.counters.continuityCausalCandidates).toBe(0);
    });

    it('records reversible action receipts without changing topology', () => {
        const snapshot = snapshotFixture();
        applyNativeStoryContinuityContract(snapshot, contractFixture());
        const beforeNodes = snapshot.nodes.length;
        const beforeEdges = snapshot.edges.length;

        const receipt = appendStoryContinuityActionReceipt(
            snapshot,
            'boundary:1',
            'confirm_boundary',
            99,
        );

        expect(receipt).toMatchObject({
            targetRowId: 'boundary:1',
            action: 'confirm_boundary',
            status: 'proposed',
            reversible: true,
            noTopologyCommit: true,
        });
        expect(snapshot.storyContinuity?.actionReceipts).toEqual([receipt]);
        expect(snapshot.nodes).toHaveLength(beforeNodes);
        expect(snapshot.edges).toHaveLength(beforeEdges);
    });

    it('rejects stale cross-language row shapes at the native boundary', () => {
        const contract = contractFixture();
        const valid = {
            schemaVersion: 'phoenix-story-continuity-native-output/v1' as const,
            source: 'rust' as const,
            contract,
            timing: { continuityBuildMicros: 10, totalMicros: 12 },
        };
        expect(isNativeStoryContinuityOutput(valid)).toBe(true);

        const stale = structuredClone(valid) as unknown as {
            contract: { temporalCandidates: Array<Record<string, unknown>> };
        };
        stale.contract.temporalCandidates[0] = {
            id: 'temporal:stale', sourceEventId: 'event:1', targetEventId: 'event:2',
            relation: 'before', evidenceClass: 'document_order', evidenceIds: ['chunk:1'],
            confidenceMillis: 700, status: 'candidate', noTopologyCommit: true,
        };
        expect(isNativeStoryContinuityOutput(stale as never)).toBe(false);
    });

    it('persists and hydrates continuity authority through its dedicated blob', () => {
        const snapshot = snapshotFixture();
        applyNativeStoryContinuityContract(snapshot, contractFixture());
        appendStoryContinuityActionReceipt(snapshot, 'boundary:1', 'confirm_boundary', 99);

        const persisted = scopedDocumentToGraphRebuildSnapshot(
            graphRebuildSnapshotToScopedDocument(snapshot),
        )!;
        expect(persisted.storyContinuity).toBeUndefined();
        const blobs = Object.fromEntries(
            graphRebuildSnapshotContentBlobDocuments(snapshot).map((document) => {
                const blob = scopedDocumentToGraphRebuildContentBlob(document)!;
                return [blob.field, blob];
            }),
        ) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;
        expect(blobs.storyContinuity).toBeTruthy();

        const hydrated = hydrateGraphSnapshotContent(persisted, blobs);
        expect(hydrated.storyContinuity).toEqual(snapshot.storyContinuity);
        expect(hydrated.storyContinuity?.actionReceipts).toHaveLength(1);
    });
});

function contractFixture(): GraphStoryContinuityContract {
    return {
        schemaVersion: 'phoenix-story-continuity/v1',
        source: 'rust_story_continuity',
        sourceSnapshotId: 'snapshot:1',
        generatedAt: 1,
        commitPolicy: 'candidate_only',
        noTopologyCommit: true,
        events: [],
        boundaryReceipts: [{
            id: 'boundary:1', noteId: 'note:1', afterChunkId: 'chunk:1', sourceOffset: 0,
            decision: 'document_start', signals: [], confidenceMillis: 1000,
            status: 'candidate', noTopologyCommit: true,
        }],
        episodes: [{
            id: 'episode:1', noteId: 'note:1', label: 'Episode 1', sourceStart: 0, sourceEnd: 20,
            chunkIds: ['chunk:1'], eventIds: [], entityIds: [], boundaryReceiptIds: ['boundary:1'],
            confidenceMillis: 1000, status: 'candidate', noTopologyCommit: true,
        }],
        temporalCandidates: [{
            id: 'temporal:1', sourceId: 'event:1', targetId: 'event:2', relation: 'before',
            evidenceClass: 'document_order', evidenceIds: ['chunk:1'], confidenceMillis: 700,
            status: 'candidate', noTopologyCommit: true,
        }],
        stateIntervals: [],
        causalCandidates: [],
        episodeConnections: [],
        conflicts: [],
        certificate: {
            schemaVersion: 'phoenix-story-continuity-run-certificate/v1',
            sourceSnapshotId: 'snapshot:1', sourceDocumentIds: ['note:1'], buildMicros: 10,
            eventIdentityMicros: 2, episodeBoundaryMicros: 3, relationResolutionMicros: 5,
            counters: {
                events: 0, boundaryReceipts: 1, episodes: 1, temporalCandidates: 1,
                stateIntervals: 0, causalCandidates: 0, episodeConnections: 0,
                conflicts: 0, crossDocumentConnections: 0, reviewRequired: 0,
            },
            noTopologyWrites: true, allRowsEvidenced: true, stableSourceIdentities: true,
            fixedBatchingDetected: false, invariantReceipts: ['candidate_only'],
        },
    };
}

function snapshotFixture(): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1', id: 'snapshot:1', source: 'phoenix-graph-rebuild',
        scopeKind: 'global', scopeId: 'global', noteIds: ['note:1'], builtAt: 1,
        chunks: [], mentions: [], entityAnchors: [], relationships: [], events: [], episodes: [],
        temporalEdges: [], causalEdges: [], memoryState: [], embeddingTargets: [], embeddingVectors: [],
        projectionRefs: [], nodes: [], edges: [], counters: {
            entities: 0, aliases: 0, candidates: 0, mentions: 0, acceptedAnchors: 0, chunks: 0,
            relationshipCandidates: 0, relationships: 0, acceptedRelationships: 0,
            reviewRelationships: 0, rejectedRelationships: 0, events: 0, episodes: 0,
            temporalEdges: 0, causalEdges: 0, memoryState: 0, embeddingTargets: 0,
            embeddingVectors: 0, projectionRefs: 0, nodes: 0, edges: 0, dbOpsMs: 0, totalMs: 0,
        },
    };
}
