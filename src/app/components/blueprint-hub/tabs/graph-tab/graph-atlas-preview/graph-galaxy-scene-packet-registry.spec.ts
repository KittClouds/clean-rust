import { beforeEach, describe, expect, it } from 'vitest';

import { packGalaxyScenePacketV2 } from './graph-galaxy-scene-packet-v2';
import {
    cachedGalaxyScenePacket,
    clearGalaxyScenePacketRegistry,
    galaxyScenePacketRegistrySnapshot,
    seedGalaxyScenePacket,
    subscribeGalaxyScenePacket,
} from './graph-galaxy-scene-packet-registry';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

describe('Galaxy scene packet registry', () => {
    beforeEach(() => clearGalaxyScenePacketRegistry());

    it('retains one bounded packed packet for every manifold in a generation', () => {
        for (const manifold of ['hybrid', 'hopf', 'lorentz', 'product', 'siegel']) {
            seedGalaxyScenePacket(packet('generation:a', `receipt:${manifold}`));
        }

        expect(galaxyScenePacketRegistrySnapshot()).toMatchObject({
            packets: 5,
            generationId: 'generation:a',
        });
        expect(cachedGalaxyScenePacket('receipt:hybrid', 'generation:a', 'embeddings')).not.toBeNull();
        expect(cachedGalaxyScenePacket('receipt:siegel', 'generation:a', 'embeddings')).not.toBeNull();
    });

    it('evicts the oldest packed variant instead of exceeding the five-manifold bound', () => {
        for (let index = 0; index < 6; index++) {
            seedGalaxyScenePacket(packet('generation:a', `receipt:${index}`));
        }

        expect(galaxyScenePacketRegistrySnapshot().packets).toBe(5);
        expect(cachedGalaxyScenePacket('receipt:0', 'generation:a', 'embeddings')).toBeNull();
        expect(cachedGalaxyScenePacket('receipt:5', 'generation:a', 'embeddings')).not.toBeNull();
    });

    it('drops an older generation atomically', () => {
        seedGalaxyScenePacket(packet('generation:a', 'receipt:a'));
        seedGalaxyScenePacket(packet('generation:b', 'receipt:b'));

        expect(cachedGalaxyScenePacket('receipt:a', 'generation:a', 'embeddings')).toBeNull();
        expect(galaxyScenePacketRegistrySnapshot()).toMatchObject({
            packets: 1,
            generationId: 'generation:b',
        });
    });

    it('wakes only the canvas waiting for the exact restored receipt', () => {
        const received: string[] = [];
        const unsubscribe = subscribeGalaxyScenePacket('receipt:hopf', (value) => {
            received.push(value.manifest.authorityReceipt);
        });

        seedGalaxyScenePacket(packet('generation:a', 'receipt:hybrid'));
        seedGalaxyScenePacket(packet('generation:a', 'receipt:hopf'));
        unsubscribe();
        seedGalaxyScenePacket(packet('generation:a', 'receipt:hopf'));

        expect(received).toEqual(['receipt:hopf']);
    });
});

function packet(generationId: string, authorityReceipt: string) {
    return packGalaxyScenePacketV2(scene(), { generationId, authorityReceipt });
}

function scene(): GalaxySceneV2 {
    return {
        layoutMode: 'hybridSpace',
        sourceMode: 'embeddings',
        ids: ['node:a'],
        labels: ['A'],
        kinds: ['concept'],
        groupIds: ['group:a'],
        positions3d: new Float32Array([1, 2, 3]),
        basePositions3d: new Float32Array([1, 2, 3]),
        radii: new Float32Array([2]),
        colors: new Float32Array([0.1, 0.2, 0.3]),
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
