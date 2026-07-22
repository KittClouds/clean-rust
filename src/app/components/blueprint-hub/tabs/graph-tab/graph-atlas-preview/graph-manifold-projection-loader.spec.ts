import { describe, expect, it, vi } from 'vitest';

import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { AtlasManifoldMode } from '../../../../../services/manifold-atlas.types';
import type { EmbeddingAtlasData } from './graph-embedding-atlas';
import {
    buildGraphRebuildEmbeddingAtlas,
    seedGraphRebuildEmbeddingAtlas,
} from './graph-rebuild-embedding-atlas';
import { loadManifoldProjection, manifoldProjectionRequestKey } from './graph-manifold-projection-loader';

const MODES: readonly AtlasManifoldMode[] = ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'];

describe('manifold projection switching', () => {
    it('uses the frozen graph snapshot for every manifold without a native round trip', async () => {
        const snapshot = projectionSnapshot(1_500);
        const loadNative = vi.fn<() => Promise<EmbeddingAtlasData>>();
        const durations = new Map<AtlasManifoldMode, number>();

        for (const mode of MODES) {
            buildGraphRebuildEmbeddingAtlas(snapshot, mode);
            const startedAt = performance.now();
            const projection = await loadManifoldProjection(snapshot, mode, loadNative);
            durations.set(mode, performance.now() - startedAt);

            expect(projection.source).toBe('graph-rebuild-snapshot');
            expect(projection.atlas.nodes).toHaveLength(1_500);
        }
        for (const [mode, durationMs] of durations) {
            expect(durationMs, `${mode} projection took ${durationMs.toFixed(2)} ms`).toBeLessThan(1_000);
        }
        expect(loadNative).not.toHaveBeenCalled();
    });

    it('reuses the exact compiled projection for an unchanged snapshot identity', async () => {
        const snapshot = projectionSnapshot(64);
        const loadNative = vi.fn<() => Promise<EmbeddingAtlasData>>();
        buildGraphRebuildEmbeddingAtlas(snapshot, 'siegel');
        const first = await loadManifoldProjection(snapshot, 'siegel', loadNative);
        const rehydratedReceipt = structuredClone(snapshot);
        const second = await loadManifoldProjection(rehydratedReceipt, 'siegel', loadNative);

        expect(second.atlas).toBe(first.atlas);
        expect(loadNative).not.toHaveBeenCalled();
    });

    it('keeps all five small projections hot for an unchanged snapshot', async () => {
        const snapshot = projectionSnapshot(96);
        const loadNative = vi.fn<() => Promise<EmbeddingAtlasData>>();
        buildGraphRebuildEmbeddingAtlas(snapshot, 'hybrid');
        const firstHybrid = await loadManifoldProjection(snapshot, 'hybrid', loadNative);

        for (const mode of MODES.slice(1)) buildGraphRebuildEmbeddingAtlas(snapshot, mode);
        const secondHybrid = await loadManifoldProjection(snapshot, 'hybrid', loadNative);

        expect(secondHybrid.atlas).toBe(firstHybrid.atlas);
        expect(firstHybrid.atlas.nodes).toHaveLength(96);
        expect(loadNative).not.toHaveBeenCalled();
    });

    it('evicts the oldest projection when the resident element ceiling is crossed', async () => {
        const snapshot = projectionSnapshot(96);
        const loadNative = vi.fn<() => Promise<EmbeddingAtlasData>>();
        const firstHybrid = buildGraphRebuildEmbeddingAtlas(snapshot, 'hybrid');
        const repeatedNode = firstHybrid.nodes[0]!;

        for (const mode of MODES.slice(1)) {
            seedGraphRebuildEmbeddingAtlas(snapshot, mode, {
                ...firstHybrid,
                nodes: Array(40_001).fill(repeatedNode),
            });
        }

        await expect(loadManifoldProjection(snapshot, 'hybrid', loadNative)).rejects.toThrow(
            'synchronous rebuild is forbidden',
        );
        expect(loadNative).not.toHaveBeenCalled();
    });

    it('keeps every authoritative current-corpus manifold cache read below one second', async () => {
        const snapshot = projectionSnapshot(6_000);
        const loadNative = vi.fn<() => Promise<EmbeddingAtlasData>>();
        const durations = new Map<AtlasManifoldMode, number>();
        for (const mode of MODES) {
            buildGraphRebuildEmbeddingAtlas(snapshot, mode);
            const startedAt = performance.now();
            const projection = await loadManifoldProjection(snapshot, mode, loadNative);
            durations.set(mode, performance.now() - startedAt);
            expect(projection.atlas.nodes).toHaveLength(6_000);
        }

        for (const [mode, durationMs] of durations) {
            expect(durationMs, `${mode} current-corpus projection took ${durationMs.toFixed(2)} ms`).toBeLessThan(1_000);
        }
        expect(loadNative).not.toHaveBeenCalled();
    });

    it('fails closed instead of rebuilding or invoking native loading on an authoritative cache miss', async () => {
        const snapshot = projectionSnapshot(32);
        const loadNative = vi.fn<() => Promise<EmbeddingAtlasData>>();

        await expect(loadManifoldProjection(snapshot, 'product', loadNative)).rejects.toThrow(
            'synchronous rebuild is forbidden',
        );
        expect(loadNative).not.toHaveBeenCalled();
    });

    it('retains native loading only when no frozen graph projection exists', async () => {
        const nativeAtlas: EmbeddingAtlasData = {
            nodes: [],
            edges: [],
            searchIndex: [],
            sourceLabel: 'native fallback',
        };
        const loadNative = vi.fn(async () => nativeAtlas);

        const projection = await loadManifoldProjection(null, 'hopf', loadNative);

        expect(projection).toEqual({ atlas: nativeAtlas, source: 'native-manifold-snapshot' });
        expect(loadNative).toHaveBeenCalledOnce();
    });

    it('keys unchanged termination to the immutable snapshot identity', () => {
        const snapshot = projectionSnapshot(8);

        expect(manifoldProjectionRequestKey(snapshot, 'product', 'global')).toBe(
            'projection-performance-8:product:global',
        );
        expect(manifoldProjectionRequestKey(null, 'product', 'global')).toBe('native:product:global');
    });
});

function projectionSnapshot(targetCount: number): GraphRebuildSnapshot {
    const manifoldTargets = Array.from({ length: targetCount }, (_, index) => ({
        id: `embed:entity:entity-${index}`,
        objectId: `object:entity-${index}`,
        family: 'registry',
        admission: 'admitted',
        status: 'accepted',
        vectorStatus: 'missing',
        coordinateSource: 'deterministic-signature',
        kind: 'entity',
        label: `Entity ${index}`,
        styleKey: 'character',
        sourceId: `entity-${index}`,
        registryEntityId: `entity-${index}`,
        entityKind: 'CHARACTER',
        evidenceIds: [],
    }));
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: `projection-performance-${targetCount}`,
        authorityContract: {
            contentHash: `projection-authority-${targetCount}`,
        },
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: [],
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
        counters: { embeddingTargets: targetCount },
        hopfResonanceSpace: {
            assignments: manifoldTargets.map((target, index) => ({
                targetId: target.id,
                targetKind: target.kind,
                label: target.label,
                role: 'fiber-sample',
                fiberKind: 'entity_sample',
                baseCellId: 'hopf:cell:0',
                secondaryCellIds: [],
                direction: [1, 0, 0],
                tangent: [0, 1, 0],
                phase: index / Math.max(1, targetCount),
                phaseRadians: 0,
                strandKey: 'entity_sample',
                strandIndex: index,
                strandCount: targetCount,
                phaseSpread: 0,
                assignmentScore: 1,
                residualScore: 0,
                salience: 1,
                evidenceIds: [],
                parentIds: [],
                receipt: `frozen:${target.id}`,
            })),
            cells: [{ id: 'hopf:cell:0', anchorTargetIds: [manifoldTargets[0]?.id] }],
            fibers: [],
        },
        atlasPacket: {
            schemaVersion: 'phoenix-atlas-packet/v1',
            snapshotId: `projection-performance-${targetCount}`,
            scopeKind: 'global',
            scopeId: 'global',
            builtAt: 1,
            sourceContract: {
                authority: 'rust-atlas-packet',
                identityAuthority: 'registry-entities-and-accepted-anchors',
                vectorContract: 'vectors missing',
                tsGraphBuilderRole: 'native-atlas-packet-authority',
            },
            objects: [],
            manifoldTargets,
            counters: {
                objects: 0,
                manifoldTargets: targetCount,
                registryEntities: targetCount,
                evidenceAnchors: 0,
                modelVectors: 0,
                families: [],
            },
        },
    } as unknown as GraphRebuildSnapshot;
}
