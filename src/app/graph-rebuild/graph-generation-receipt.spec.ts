import {
    assertGraphGenerationReceipt,
    buildGraphGenerationReceipt,
    withGraphGenerationArtifact,
    type GraphGenerationArtifactRef,
} from './graph-generation-receipt';
import { graphGenerationSnapshotShell } from './graph-rebuild.service';
import type {
    GraphIndexRunReceipt,
    GraphRebuildSnapshot,
    GraphSnapshotAuthorityCounts,
} from './graph-rebuild-snapshot';

describe('GraphGenerationReceiptV2', () => {
    it('binds the compact generation to its existing authority and stays release-closed', async () => {
        const receipt = await buildGraphGenerationReceipt({
            snapshot: snapshot(),
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
        });

        expect(receipt.schemaVersion).toBe('phoenix-graph-generation-receipt/v2');
        expect(receipt.authorityDigestSha256).toMatch(/^sha256-[0-9a-f]{64}$/);
        expect(receipt.digestSha256).toMatch(/^sha256-[0-9a-f]{64}$/);
        expect(receipt.artifacts.analysisRun.status).toBe('ready');
        expect(receipt.artifacts.assertedQuery.status).toBe('pending');
        expect(receipt.artifacts.sceneIndex.status).toBe('pending');
        expect(receipt.releaseAuthorized).toBe(false);
        expect(receipt.candidateEdgesAdmitted).toBe(0);
        expect(receipt.topologyWrites).toBe(0);
        await expect(assertGraphGenerationReceipt(receipt)).resolves.toBeUndefined();
    });

    it('authorizes release only when asserted query, analysis, and scene artifacts are ready', async () => {
        const receipt = await buildGraphGenerationReceipt({
            snapshot: snapshot(),
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
            assertedQuery: readyArtifact('asserted-query', 'query:7'),
            sceneIndex: readyArtifact('scene-index', 'scene:7'),
        });

        expect(receipt.releaseAuthorized).toBe(true);
        await expect(assertGraphGenerationReceipt(receipt)).resolves.toBeUndefined();
    });

    it('rejects tampering and a forged release bit', async () => {
        const receipt = await buildGraphGenerationReceipt({
            snapshot: snapshot(),
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
        });
        receipt.uiSummary.counts.nodes += 1;
        receipt.releaseAuthorized = true;

        await expect(assertGraphGenerationReceipt(receipt)).rejects.toThrow();
    });

    it('contains no rich graph row arrays', async () => {
        const receipt = await buildGraphGenerationReceipt({
            snapshot: snapshot(),
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
        });
        const json = JSON.stringify(receipt);

        for (const forbidden of ['"chunks":[]', '"nodes":[]', '"edges":[]', 'embeddingVectors']) {
            expect(json).not.toContain(forbidden);
        }
        expect(new TextEncoder().encode(json).byteLength).toBeLessThan(64 * 1024);
    });

    it('re-seals every artifact transition instead of mutating authority in place', async () => {
        const initial = await buildGraphGenerationReceipt({
            snapshot: snapshot(),
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
        });
        const updated = await withGraphGenerationArtifact(
            initial,
            'assertedQuery',
            readyArtifact('asserted-query', 'query:7'),
        );

        expect(updated).not.toBe(initial);
        expect(initial.artifacts.assertedQuery.status).toBe('pending');
        expect(updated.artifacts.assertedQuery.status).toBe('ready');
        expect(updated.digestSha256).not.toBe(initial.digestSha256);
        await expect(assertGraphGenerationReceipt(updated)).resolves.toBeUndefined();
    });

    it('creates a receipt-bound compact shell only after release authorization', async () => {
        const source = snapshot();
        source.nodes = [{ id: 'node-1' } as GraphRebuildSnapshot['nodes'][number]];
        source.embeddingTargets = [{ id: 'target-1' } as GraphRebuildSnapshot['embeddingTargets'][number]];
        const pending = await buildGraphGenerationReceipt({
            snapshot: source,
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
        });
        expect(() => graphGenerationSnapshotShell(source, pending)).toThrow(/not authorized/);

        const ready = await buildGraphGenerationReceipt({
            snapshot: source,
            runReceipt: runReceipt(),
            inputIdentity: 'sha256-input',
            assertedQuery: readyArtifact('asserted-query', 'query:7'),
            sceneIndex: readyArtifact('scene-index', 'scene:7'),
        });
        const shell = graphGenerationSnapshotShell(source, ready);

        expect(shell.generationReceiptId).toBe(ready.receiptId);
        expect(shell.generationDigestSha256).toBe(ready.digestSha256);
        expect(shell.nodes).toEqual([]);
        expect(shell.embeddingTargets).toEqual([]);
        expect(shell.authorityContract).toEqual(source.authorityContract);
    });
});

function readyArtifact(
    kind: GraphGenerationArtifactRef['kind'],
    id: string,
): GraphGenerationArtifactRef {
    return {
        schemaVersion: 'phoenix-graph-generation-artifact-ref/v1',
        kind,
        status: 'ready',
        id,
        digest: 'a'.repeat(64),
        schema: `test-${kind}/v1`,
    };
}

function snapshot(): GraphRebuildSnapshot {
    const counts = authorityCounts();
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot-7',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        builtAt: 7,
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
        authorityContract: {
            schemaVersion: 'phoenix-graph-snapshot-authority/v1',
            authority: 'graph_rebuild_live_contract',
            snapshotId: 'snapshot-7',
            scopeId: 'global',
            contentHash: 'fnv64-authority',
            counts,
        },
        contentManifest: {
            schemaVersion: 'phoenix-graph-rebuild-content-manifest/v1',
            snapshotId: 'snapshot-7',
            scopeId: 'global',
            builtAt: 7,
            refs: {},
        },
        interactiveRunAuthority: {
            schemaVersion: 'phoenix-interactive-graph-run-authority/v1',
            inputIdentity: 'sha256-input',
            snapshotId: 'snapshot-7',
            scopeId: 'global',
            durable: {
                schemaVersion: 'phoenix-graph-run-durable-receipt/v1',
                runHandle: 'graph-run:7',
                scopeId: 'global',
                snapshotId: 'snapshot-7',
                manifestId: 'manifest-7',
                changedSections: 8,
                reusedSections: 0,
                encodedSections: 8,
                compressedSections: 8,
                rawBytesWritten: 4_096,
                compressedBytesWritten: 1_024,
            },
        },
        counters: countersFixture(),
    };
}

function authorityCounts(): GraphSnapshotAuthorityCounts {
    return {
        notes: 1,
        chunks: 2,
        mentions: 3,
        anchors: 4,
        relationships: 5,
        events: 6,
        temporalEdges: 7,
        causalEdges: 8,
        memoryState: 9,
        coreferenceRecoveries: 0,
        nodes: 10,
        edges: 11,
        embeddingTargets: 12,
        admittedEmbeddingTargets: 12,
        packetObjects: 13,
        packetTargets: 12,
        packetParentLinks: 11,
        packetFamilies: { entity: 10 },
    };
}

function countersFixture(): GraphRebuildSnapshot['counters'] {
    return {
        notes: 1,
        chunks: 2,
        mentions: 3,
        acceptedAnchors: 4,
        relationships: 5,
        acceptedRelationships: 5,
        reviewRelationships: 0,
        rejectedRelationships: 0,
        events: 6,
        temporalEdges: 7,
        causalEdges: 8,
        memoryStates: 9,
        nodes: 10,
        edges: 11,
        embeddingTargets: 12,
        embeddingVectors: 0,
        dropReasons: {},
    } as GraphRebuildSnapshot['counters'];
}

function runReceipt(): GraphIndexRunReceipt {
    const source = snapshot();
    return {
        schemaVersion: 'phoenix-graph-index-run/v1',
        id: 'run-7',
        scope: { kind: 'global', scopeId: 'global', label: 'Global', noteIds: ['note-1'] },
        policy: 'force',
        delta: false,
        status: 'completed',
        modelSelection: {
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'encoder',
            embeddingModelLabel: 'Encoder',
            embeddingDimensionLabel: '768',
            nliModelId: 'nli',
        },
        modelReadiness: [],
        startedAt: 1,
        completedAt: 7,
        durationMs: 6,
        stageReceipts: [],
        projectionReceipts: [],
        layerReceipts: [],
        snapshotId: source.id,
        authorityContract: source.authorityContract,
        counters: source.counters,
        dropReasons: source.counters.dropReasons,
        message: 'ok',
    };
}
