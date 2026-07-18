import { describe, expect, it } from 'vitest';

import {
    assertGalaxyScenePacketV2,
    galaxySceneIdentityCollisionPages,
    galaxyScenePacketV2TransferList,
    GalaxyScenePacketV2SharedPagePool,
    GALAXY_SCENE_PACKET_LITTLE_ENDIAN_RUNTIME,
    packGalaxyScenePacketV2,
    unpackGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

describe('GalaxyScenePacketV2', () => {
    it('fails closed unless typed pages use the declared little-endian runtime', () => {
        expect(GALAXY_SCENE_PACKET_LITTLE_ENDIAN_RUNTIME).toBe(true);
        expect(Array.from(new Uint8Array(Uint32Array.of(0x01020304).buffer))).toEqual([4, 3, 2, 1]);
    });

    it('round-trips the current renderer scene through packed binary pages', () => {
        const source = scene();
        const packet = packGalaxyScenePacketV2(source, {
            generationId: 'snapshot:g1',
            authorityReceipt: 'authority:g1',
        });
        const restored = unpackGalaxyScenePacketV2(packet);

        expect(restored.sourceMode).toBe(source.sourceMode);
        expect(restored.layoutMode).toBe(source.layoutMode);
        expect(restored.ids).toEqual(source.ids);
        expect(restored.labels).toEqual(source.labels);
        expect(restored.kinds).toEqual(source.kinds);
        expect(restored.groupIds).toEqual(source.groupIds);
        expect(restored.hopfBaseIds).toEqual(source.hopfBaseIds);
        expect(restored.hopfCellIds).toEqual(source.hopfCellIds);
        expect(restored.hopfFiberIds).toEqual(source.hopfFiberIds);
        expect(restored.hopfLaneIds).toEqual(source.hopfLaneIds);
        expect(Array.from(restored.positions3d)).toEqual(Array.from(source.positions3d));
        expect(Array.from(restored.positions2d)).toEqual(Array.from(source.positions2d));
        expect(Array.from(restored.radii)).toEqual(Array.from(source.radii));
        expect(Array.from(restored.colors)).toEqual(Array.from(source.colors));
        expect(Array.from(restored.edgePairs)).toEqual(Array.from(source.edgePairs));
        expect(restored.edgeIds).toEqual(source.edgeIds);
        expect(restored.edgeTypes).toEqual(source.edgeTypes);
        expect(Array.from(restored.edgeColors)).toEqual(Array.from(source.edgeColors));
        expect(Array.from(restored.edgeAlpha)).toEqual(Array.from(source.edgeAlpha));
        expect(Array.from(restored.edgeKinds)).toEqual(Array.from(source.edgeKinds));
        expect(restored.groups).toEqual(source.groups);
        expect(restored.runtimeIndex?.nodeById.get('node:b')).toBe(1);
        expect(Array.from(restored.runtimeIndex?.incidentOffsets ?? [])).toEqual([0, 1, 2]);
        expect(Array.from(restored.runtimeIndex?.incidentEdges ?? [])).toEqual([0, 0]);
    });

    it('keeps JSON manifest metadata-only and moves strings into on-demand slabs', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'snapshot:g2',
            authorityReceipt: 'authority:g2',
        });
        const manifestJson = JSON.stringify(packet.manifest);
        const detailPages = packet.manifest.pages.filter((page) => page.domain === 'detail');

        expect(manifestJson).not.toContain('Secret Node Label');
        expect(manifestJson).not.toContain('node:a');
        expect(detailPages.length).toBeGreaterThanOrEqual(3);
        expect(detailPages.every((page) => page.loadPolicy === 'on-demand')).toBe(true);
        expect(Object.values(packet.pages).every((page) => page instanceof ArrayBuffer)).toBe(true);
        expect(manifestJson).not.toMatch(/[A-Za-z0-9+/]{80,}={0,2}/);
    });

    it('stamps every page with generation, tile, lod, hash, and authority', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'snapshot:g3',
            authorityReceipt: 'authority:g3',
            tileId: 'full-current-graph',
            lod: 0,
        });

        for (const page of packet.manifest.pages) {
            expect(page).toMatchObject({
                generationId: 'snapshot:g3',
                tileId: 'full-current-graph',
                lod: 0,
                authorityReceipt: 'authority:g3',
            });
            expect(page.contentHash).toMatch(/^fnv1a64:[0-9a-f]{16}$/);
            expect(page.byteLength).toBe(packet.pages[page.id].byteLength);
        }
        expect(() => assertGalaxyScenePacketV2(packet)).not.toThrow();
    });

    it('separates shared identity/topology pages from manifold coordinates and styles', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'snapshot:g4',
            authorityReceipt: 'authority:g4',
        });
        const domains = new Map(packet.manifest.pages.map((page) => [page.id, page.domain]));

        expect(domains.get('shared/node-identity-keys')).toBe('shared');
        expect(domains.get('shared/edge-identity-keys')).toBe('shared');
        expect(domains.get('shared/edge-pairs')).toBe('shared');
        expect(domains.get('manifold/positions-3d')).toBe('manifold');
        expect(domains.get('manifold/node-colors-rgba8')).toBe('manifold');
    });

    it('reuses identical shared pages while replacing manifold pages', () => {
        const pool = new GalaxyScenePacketV2SharedPagePool();
        const hybrid = packGalaxyScenePacketV2(scene(), {
            generationId: 'snapshot:shared',
            authorityReceipt: 'snapshot:shared\u0000hybrid',
        });
        const hopfScene = scene();
        hopfScene.positions3d[0] = 99;
        const hopf = packGalaxyScenePacketV2(hopfScene, {
            generationId: 'snapshot:shared',
            authorityReceipt: 'snapshot:shared\u0000hopf',
        });
        pool.reuse(hybrid);
        const hybridEdges = hybrid.pages['shared/edge-pairs'];
        const hybridPositions = hybrid.pages['manifold/positions-3d'];
        pool.reuse(hopf);

        expect(hopf.pages['shared/edge-pairs']).toBe(hybridEdges);
        expect(hopf.pages['manifold/positions-3d']).not.toBe(hybridPositions);
        expect(new Float32Array(hopf.pages['manifold/positions-3d'])[0]).toBe(99);
    });

    it('transfers ownership of every page without cloning the buffers', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'snapshot:g5',
            authorityReceipt: 'authority:g5',
        });
        const transfer = galaxyScenePacketV2TransferList(packet);
        const original = [...transfer] as ArrayBuffer[];
        const received = structuredClone(packet, { transfer });

        expect(new Set(original).size).toBe(original.length);
        expect(original.every((buffer) => buffer.byteLength === 0)).toBe(true);
        expect(unpackGalaxyScenePacketV2(received).ids).toEqual(['node:a', 'node:b']);
    });

    it('rejects a page whose bytes no longer match its receipt hash', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'snapshot:g6',
            authorityReceipt: 'authority:g6',
        });
        const page = new Uint8Array(packet.pages['manifold/positions-3d']);
        page[0] ^= 0xff;

        expect(() => unpackGalaxyScenePacketV2(packet)).toThrow(/hash drift/);
    });

    it('records only true numeric-key collisions and their exact members', () => {
        const collisions = galaxySceneIdentityCollisionPages(
            ['alpha', 'beta', 'alpha', 'gamma'],
            new Uint32Array([
                7, 9,
                7, 9,
                7, 9,
                2, 4,
            ]),
        );

        expect(collisions.collisionCount).toBe(1);
        expect(Array.from(collisions.records)).toEqual([7, 9, 0, 3]);
        expect(Array.from(collisions.members)).toEqual([0, 2, 1]);
    });
});

function scene(): GalaxySceneV2 {
    return {
        sourceMode: 'embeddings',
        layoutMode: 'single',
        ids: ['node:a', 'node:b'],
        labels: ['Secret Node Label', 'Node B'],
        kinds: ['entity', 'chunk'],
        groupIds: ['group:1', 'group:1'],
        hopfBaseIds: ['base:1', 'base:1'],
        hopfCellIds: ['base:1', 'base:1'],
        hopfFiberIds: ['fiber:1', 'fiber:2'],
        hopfLaneIds: ['fiber:1:lane:0', 'fiber:2:lane:0'],
        hopfRoles: new Uint8Array([1, 2]),
        groups: [{
            id: 'group:1',
            label: 'Group One',
            kind: 'cluster',
            center: { x: 0.5, y: 1.5, z: 2.5 },
            radius: 3,
            color: { r: 12 / 255, g: 34 / 255, b: 56 / 255 },
            nodeIds: ['node:a', 'node:b'],
            importance: 1,
        }],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array([0, 1, 2, 3, 4, 5]),
        positions2d: new Float32Array([0, 1, 0, 3, 4, 0]),
        radii: new Float32Array([1.25, 2.5]),
        colors: new Float32Array([
            12 / 255, 34 / 255, 56 / 255,
            78 / 255, 90 / 255, 123 / 255,
        ]),
        edgePairs: new Uint32Array([0, 1]),
        edgeIds: ['edge:a-b'],
        edgeTypes: ['evidence'],
        edgeColors: new Float32Array([
            12 / 255, 34 / 255, 56 / 255,
            78 / 255, 90 / 255, 123 / 255,
        ]),
        edgeAlpha: new Float32Array([0.25]),
        edgeKinds: new Uint8Array([2]),
    };
}
