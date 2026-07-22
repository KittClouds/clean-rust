import { describe, expect, it, vi } from 'vitest';

import {
    buildGraphGenerationReceipt,
    type GraphGenerationArtifactRef,
} from '../graph-rebuild/graph-generation-receipt';
import { graphGenerationSnapshotShell } from '../graph-rebuild/graph-rebuild.service';
import type { GraphIndexRunReceipt, GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';
import { GraphGenerationLifetimeService } from './graph-generation-lifetime.service';

describe('GraphGenerationLifetimeService', () => {
    it('fails closed before artifacts are ready and releases exact current V3 roots afterward', async () => {
        const coldStart = { releaseGeneration: vi.fn(() => true) };
        const retrieval = { evict: vi.fn(() => true) };
        const lifetime = new GraphGenerationLifetimeService(coldStart as never, retrieval as never);
        const source = snapshot();
        const pending = await buildGraphGenerationReceipt({
            snapshot: source,
            runReceipt: runReceipt(source),
            inputIdentity: 'input:7',
        });
        await lifetime.accept(pending);

        await expect(lifetime.releaseRichGeneration(
            pending,
            { ...source, generationReceiptId: pending.receiptId } as GraphRebuildSnapshot,
            vi.fn(),
        )).rejects.toThrow(/not release-authorized/);

        const ready = await buildGraphGenerationReceipt({
            snapshot: source,
            runReceipt: runReceipt(source),
            inputIdentity: 'input:7',
            assertedQuery: artifact('asserted-query'),
            sceneIndex: artifact('scene-index'),
        });
        await lifetime.accept(ready);
        const shell = graphGenerationSnapshotShell(source, ready);
        const releaseRoots = vi.fn();

        const result = await lifetime.releaseRichGeneration(ready, shell, releaseRoots);

        expect(releaseRoots).toHaveBeenCalledOnce();
        expect(coldStart.releaseGeneration).toHaveBeenCalledWith('authority:7');
        expect(retrieval.evict).toHaveBeenCalledWith('snapshot:7');
        expect(lifetime.releasedShell()).toBe(shell);
        expect(result.released).toBe(true);
    });
});

function artifact(kind: 'asserted-query' | 'scene-index'): GraphGenerationArtifactRef {
    return {
        schemaVersion: 'phoenix-graph-generation-artifact-ref/v1',
        kind,
        status: 'ready',
        id: `${kind}:7`,
        digest: `sha256-${'7'.repeat(64)}`,
        schema: `test-${kind}/v1`,
    };
}

function snapshot(): GraphRebuildSnapshot {
    const counts = {
        notes: 1,
        chunks: 1,
        mentions: 0,
        anchors: 0,
        relationships: 0,
        events: 0,
        temporalEdges: 0,
        causalEdges: 0,
        memoryState: 0,
        coreferenceRecoveries: 0,
        nodes: 1,
        edges: 0,
        embeddingTargets: 1,
        admittedEmbeddingTargets: 1,
        packetObjects: 1,
        packetTargets: 1,
        packetParentLinks: 0,
        packetFamilies: { entity: 1 },
    };
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot:7',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note:7'],
        builtAt: 7,
        chunks: [{ id: 'chunk:7' }],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: [{ id: 'target:7' }],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [{ id: 'node:7' }],
        edges: [],
        authorityContract: {
            schemaVersion: 'phoenix-graph-snapshot-authority/v1',
            authority: 'graph_rebuild_live_contract',
            snapshotId: 'snapshot:7',
            scopeId: 'global',
            contentHash: 'authority:7',
            counts,
        },
        contentManifest: {
            schemaVersion: 'phoenix-graph-rebuild-content-manifest/v1',
            snapshotId: 'snapshot:7',
            scopeId: 'global',
            builtAt: 7,
            refs: {},
        },
        interactiveRunAuthority: {
            schemaVersion: 'phoenix-interactive-graph-run-authority/v1',
            inputIdentity: 'input:7',
            snapshotId: 'snapshot:7',
            scopeId: 'global',
            durable: {
                schemaVersion: 'phoenix-graph-run-durable-receipt/v1',
                runHandle: 'run:7',
                scopeId: 'global',
                snapshotId: 'snapshot:7',
                manifestId: 'manifest:7',
                changedSections: 1,
                reusedSections: 0,
                encodedSections: 1,
                compressedSections: 1,
                rawBytesWritten: 1,
                compressedBytesWritten: 1,
            },
        },
        counters: {
            notes: 1,
            chunks: 1,
            nodes: 1,
            edges: 0,
            embeddingTargets: 1,
            dropReasons: {},
        },
    } as GraphRebuildSnapshot;
}

function runReceipt(source: GraphRebuildSnapshot): GraphIndexRunReceipt {
    return {
        id: 'run:7',
        snapshotId: source.id,
        counters: source.counters,
    } as GraphIndexRunReceipt;
}
