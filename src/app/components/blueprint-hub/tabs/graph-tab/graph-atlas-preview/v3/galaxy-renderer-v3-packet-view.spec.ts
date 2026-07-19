import { describe, expect, it } from 'vitest';

import { packGalaxyScenePacketV2 } from '../graph-galaxy-scene-packet-v2';
import type { GalaxySceneV2 } from '../graph-galaxy-scene-v2';
import {
    galaxyRendererV3Labels,
    galaxyRendererV3NodeIds,
    galaxyRendererV3PacketResidentBytes,
    galaxyRendererV3ResidentPages,
} from './galaxy-renderer-v3-packet-view';

describe('Galaxy Renderer V3 packed boundary', () => {
    it('installs typed views over transferred pages without object expansion', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'generation:v3',
            authorityReceipt: 'receipt:v3',
        });
        const pages = galaxyRendererV3ResidentPages(packet);

        expect(pages.positions3d.buffer).toBe(packet.pages['manifold/positions-3d']);
        expect(pages.edgePairs.buffer).toBe(packet.pages['shared/edge-pairs']);
        expect(pages.nodeColorsRgba8.buffer).toBe(packet.pages['manifold/node-colors-rgba8']);
        expect(Array.from(pages.edgePairs)).toEqual([0, 1]);
    });

    it('keeps identity and labels lazy until interaction asks for them', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'generation:detail',
            authorityReceipt: 'receipt:detail',
        });

        expect(galaxyRendererV3NodeIds(packet)).toEqual(['node:a', 'node:b']);
        expect(galaxyRendererV3Labels(packet, [1])).toEqual(new Map([[1, 'Node B']]));
        expect(galaxyRendererV3PacketResidentBytes(packet)).toBeLessThan(
            Object.values(packet.pages).reduce((sum, page) => sum + page.byteLength, 0),
        );
    });

    it('fails closed when a resident page drifts from its receipt', () => {
        const packet = packGalaxyScenePacketV2(scene(), {
            generationId: 'generation:drift',
            authorityReceipt: 'receipt:drift',
        });
        new Uint8Array(packet.pages['manifold/positions-3d'])[0] ^= 0xff;

        expect(() => galaxyRendererV3ResidentPages(packet)).toThrow(/hash drift/);
    });
});

function scene(): GalaxySceneV2 {
    return {
        sourceMode: 'embeddings',
        layoutMode: 'single',
        ids: ['node:a', 'node:b'],
        labels: ['Node A', 'Node B'],
        kinds: ['entity', 'chunk'],
        groupIds: ['group:1', 'group:1'],
        hopfBaseIds: ['', ''],
        hopfCellIds: ['', ''],
        hopfFiberIds: ['', ''],
        hopfLaneIds: ['', ''],
        hopfRoles: new Uint8Array([0, 0]),
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array([0, 1, 2, 3, 4, 5]),
        positions2d: new Float32Array([0, 1, 0, 3, 4, 0]),
        radii: new Float32Array([1, 2]),
        colors: new Float32Array([1, 0, 0, 0, 1, 0]),
        edgePairs: new Uint32Array([0, 1]),
        edgeIds: ['edge:a-b'],
        edgeTypes: ['evidence'],
        edgeColors: new Float32Array([1, 0, 0, 0, 1, 0]),
        edgeAlpha: new Float32Array([0.4]),
        edgeKinds: new Uint8Array([1]),
    };
}
