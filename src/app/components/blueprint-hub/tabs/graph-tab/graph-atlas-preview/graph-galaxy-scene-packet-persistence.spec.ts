import { describe, expect, it } from 'vitest';

import { packGalaxyScenePacketV2 } from './graph-galaxy-scene-packet-v2';
import {
    assertPersistedGalaxySceneMatches,
    galaxySceneGenerationIndexReceipt,
    galaxyScenePacketPersistenceRecords,
    restoreGalaxyScenePacketHotPersistenceRecords,
    restoreGalaxyScenePacketPersistenceRecords,
    type GalaxyScenePacketPersistenceIdentity,
} from './graph-galaxy-scene-packet-persistence';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';

describe('Galaxy scene packet restart persistence', () => {
    it('stores a small receipt separately from raw binary pages and restores exact parity', () => {
        const packet = packGalaxyScenePacketV2(scene(), packetContext());
        const records = galaxyScenePacketPersistenceRecords(identity(), packet, snapshotShell(), 42);

        expect(records.receipt).not.toHaveProperty('pages');
        expect(records.receipt.manifest.pages.length).toBeGreaterThan(0);
        expect(records.pages.every((page) => page.buffer instanceof ArrayBuffer)).toBe(true);
        expect(JSON.stringify(records.receipt)).not.toContain('base64');

        const restored = restoreGalaxyScenePacketPersistenceRecords(records);
        expect(restored.packet.manifest).toEqual(packet.manifest);
        expect(restored.snapshotShell.id).toBe(identity().snapshotId);
        expect(Object.keys(restored.packet.pages)).toEqual(Object.keys(packet.pages));
        assertPersistedGalaxySceneMatches(restored, identity());
    });

    it('restores only resident first-pixel pages and leaves detail bytes on demand', () => {
        const packet = packGalaxyScenePacketV2(scene(), packetContext());
        const records = galaxyScenePacketPersistenceRecords(identity(), packet, snapshotShell(), 42);
        const residentIds = new Set(packet.manifest.pages
            .filter((page) => page.loadPolicy === 'resident')
            .map((page) => page.id));
        const restored = restoreGalaxyScenePacketHotPersistenceRecords(
            records.receipt,
            records.pages.filter((page) => residentIds.has(page.pageId)),
            records.pages.length,
        );

        expect(Object.keys(restored.packet.pages).every((pageId) => residentIds.has(pageId))).toBe(true);
        expect(restored.packet.pages['detail/groups']).toBeUndefined();
        expect(restored.packet.manifest.pages.some((page) => page.id === 'detail/groups')).toBe(true);
    });

    it('fails closed when a persisted binary page is changed', () => {
        const packet = packGalaxyScenePacketV2(scene(), packetContext());
        const records = galaxyScenePacketPersistenceRecords(identity(), packet, snapshotShell());
        const changed = records.pages.map((page, index) => {
            if (index !== 0) return page;
            const buffer = page.buffer.slice(0);
            new Uint8Array(buffer)[0] ^= 0xff;
            return { ...page, buffer };
        });

        expect(() => restoreGalaxyScenePacketPersistenceRecords({
            receipt: records.receipt,
            pages: changed,
        })).toThrow(/hash drift/);
    });

    it('fails closed when the compact boot shell is changed', () => {
        const packet = packGalaxyScenePacketV2(scene(), packetContext());
        const records = galaxyScenePacketPersistenceRecords(identity(), packet, snapshotShell());

        expect(() => restoreGalaxyScenePacketPersistenceRecords({
            receipt: {
                ...records.receipt,
                snapshotShell: { ...records.receipt.snapshotShell, id: 'snapshot:changed' },
            },
            pages: records.pages,
        })).toThrow(/boot shell hash drift/);
    });

    it('rejects stale snapshot and presentation receipts', () => {
        const packet = packGalaxyScenePacketV2(scene(), packetContext());
        const restored = restoreGalaxyScenePacketPersistenceRecords(
            galaxyScenePacketPersistenceRecords(identity(), packet, snapshotShell()),
        );

        expect(() => assertPersistedGalaxySceneMatches(restored, {
            ...identity(),
            snapshotId: 'snapshot:new',
        })).toThrow(/snapshotId/);
        expect(() => assertPersistedGalaxySceneMatches(restored, {
            ...identity(),
            authorityReceipt: 'receipt:new-view',
        })).toThrow(/authorityReceipt/);
    });

    it('seals only a complete, authority-consistent five-manifold generation', async () => {
        const entries = (['hybrid', 'hopf', 'lorentz', 'product', 'siegel'] as const).map((manifold) => {
            const packet = packGalaxyScenePacketV2(scene(), {
                generationId: identity().generationId,
                authorityReceipt: `receipt:${manifold}`,
            });
            const records = galaxyScenePacketPersistenceRecords({
                ...identity(),
                manifold,
                authorityReceipt: `receipt:${manifold}`,
            }, packet, snapshotShell());
            return { receipt: records.receipt, pageCount: records.pages.length };
        });

        const index = await galaxySceneGenerationIndexReceipt('global', identity().generationId, entries);

        expect(index.packetCount).toBe(5);
        expect(index.packets.map((packet) => packet.manifold)).toEqual([
            'hybrid', 'hopf', 'lorentz', 'product', 'siegel',
        ]);
        expect(index.digestSha256).toMatch(/^sha256-[0-9a-f]{64}$/);
        await expect(galaxySceneGenerationIndexReceipt(
            'global',
            identity().generationId,
            entries.slice(0, 4),
        )).rejects.toThrow(/every manifold/);
        await expect(galaxySceneGenerationIndexReceipt(
            'global',
            identity().generationId,
            entries.map((entry, index) => index === 0 ? { ...entry, pageCount: 0 } : entry),
        )).rejects.toThrow(/incomplete pages/);
    });
});

function identity(): GalaxyScenePacketPersistenceIdentity {
    return {
        scopeId: 'global',
        snapshotId: 'snapshot:a',
        generationId: 'generation:a',
        manifold: 'hopf',
        authorityReceipt: 'receipt:hopf',
    };
}

function snapshotShell(): GraphRebuildSnapshot {
    return {
        id: identity().snapshotId,
        scopeId: identity().scopeId,
        counters: { embeddingTargets: 1 },
        authorityContract: {
            snapshotId: identity().snapshotId,
            scopeId: identity().scopeId,
            contentHash: identity().generationId,
            counts: { embeddingTargets: 1 },
        },
        contentManifest: {
            schemaVersion: 'phoenix-graph-rebuild-content-manifest/v1',
            snapshotId: identity().snapshotId,
            scopeId: identity().scopeId,
            builtAt: 1,
            refs: {},
        },
    } as GraphRebuildSnapshot;
}

function packetContext(): { generationId: string; authorityReceipt: string } {
    return {
        generationId: identity().generationId,
        authorityReceipt: identity().authorityReceipt,
    };
}

function scene(): GalaxySceneV2 {
    return {
        layoutMode: 'hopfProjection',
        sourceMode: 'embeddings',
        ids: ['node:a'],
        labels: ['A'],
        kinds: ['concept'],
        groupIds: ['group:a'],
        positions3d: new Float32Array([1, 2, 3]),
        basePositions3d: new Float32Array([1, 2, 3]),
        radii: new Float32Array([2]),
        colors: new Float32Array([0.1, 0.2, 0.3]),
        paletteSlots: new Uint8Array([0xff]),
        galaxyOpacity: new Float32Array([1]),
        screenPositions2d: new Float32Array(2),
        edgeIds: [],
        edgeTypes: [],
        edgePairs: new Uint32Array(0),
        edgeColors: new Float32Array(0),
        edgeAlpha: new Float32Array(0),
        edgeKinds: new Uint8Array(0),
        edgeCurveOffsets: new Float32Array(0),
    };
}
