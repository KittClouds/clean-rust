import { describe, expect, it } from 'vitest';

import {
    boundedLocalGalaxyPath,
    GalaxyInteractionQueryController,
} from './graph-galaxy-interaction-query';
import {
    GALAXY_LOCAL_PATH_NODE_LIMIT,
    type GalaxyNativeInteractionQueryPort,
} from './graph-galaxy-interaction.model';
import { attachGalaxySceneRuntimeIndex, type GalaxySceneV2 } from './graph-galaxy-scene-v2';

describe('galaxy interaction query authority', () => {
    it('returns only the bounded path overlay for a small resident graph', () => {
        const scene = attachGalaxySceneRuntimeIndex(chainScene(12));
        const overlay = boundedLocalGalaxyPath(scene, authority(), 1, 'node:0', 'node:11');

        expect(overlay?.found).toBe(true);
        expect(Array.from(overlay?.nodeIndices ?? [])).toEqual(
            Array.from({ length: 12 }, (_, index) => index),
        );
        expect(Array.from(overlay?.edgeIndices ?? [])).toEqual(
            Array.from({ length: 11 }, (_, index) => index),
        );
    });

    it('fails closed above the local path threshold', () => {
        const scene = attachGalaxySceneRuntimeIndex(chainScene(GALAXY_LOCAL_PATH_NODE_LIMIT + 1));

        expect(boundedLocalGalaxyPath(
            scene,
            authority(),
            2,
            'node:0',
            `node:${GALAXY_LOCAL_PATH_NODE_LIMIT}`,
        )).toBeNull();
    });

    it('fails closed for large local region queries when no native port exists', async () => {
        const controller = new GalaxyInteractionQueryController();
        const scene = chainScene(GALAXY_LOCAL_PATH_NODE_LIMIT + 1);
        let localCalls = 0;
        const ids = await controller.region(
            scene,
            authority(),
            { left: 0, top: 0, right: 10, bottom: 10, width: 100, height: 100 },
            new Float32Array(16),
            () => {
                localCalls += 1;
                return ['node:0'];
            },
        );

        expect(ids).toEqual([]);
        expect(localCalls).toBe(0);
    });

    it('rejects stale native path results after a newer query cancels them', async () => {
        let firstSignal: AbortSignal | undefined;
        const native: GalaxyNativeInteractionQueryPort = {
            queryRegion: async (request) => ({ ...request, nodeIndices: new Uint32Array(0) }),
            queryPath: (request, signal) => {
                if (request.sourceNodeId === 'node:0') {
                    firstSignal = signal;
                    return new Promise((_resolve, reject) => {
                        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
                    });
                }
                return Promise.resolve({
                    ...request,
                    nodeIndices: Uint32Array.of(1, 2),
                    edgeIndices: Uint32Array.of(1),
                    found: true,
                });
            },
        };
        const controller = new GalaxyInteractionQueryController({ native });
        const scene = chainScene(4);
        const stale = controller.path(scene, authority(), 'node:0', 'node:3').catch(() => null);
        const current = controller.path(scene, authority(), 'node:1', 'node:2');

        expect(await current).toMatchObject({ sourceNodeId: 'node:1', targetNodeId: 'node:2', found: true });
        expect(await stale).toBeNull();
        expect(firstSignal?.aborted).toBe(true);
    });
});

function authority() {
    return {
        generationId: 'generation-a',
        manifoldId: 'single',
        authorityReceipt: 'receipt-a',
    };
}

function chainScene(count: number): GalaxySceneV2 {
    const edgeCount = Math.max(0, count - 1);
    const edgePairs = new Uint32Array(edgeCount * 2);
    for (let edge = 0; edge < edgeCount; edge++) {
        edgePairs[edge * 2] = edge;
        edgePairs[edge * 2 + 1] = edge + 1;
    }
    return {
        sourceMode: 'graph',
        layoutMode: 'single',
        ids: Array.from({ length: count }, (_, index) => `node:${index}`),
        labels: Array.from({ length: count }, (_, index) => `Node ${index}`),
        kinds: Array.from({ length: count }, () => 'entity'),
        groupIds: Array.from({ length: count }, () => ''),
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array(count * 3),
        positions2d: new Float32Array(count * 3),
        radii: new Float32Array(count),
        colors: new Float32Array(count * 3),
        edgePairs,
        edgeIds: Array.from({ length: edgeCount }, (_, index) => `edge:${index}`),
        edgeTypes: Array.from({ length: edgeCount }, () => 'related'),
        edgeColors: new Float32Array(edgeCount * 6),
        edgeAlpha: new Float32Array(edgeCount),
        edgeKinds: new Uint8Array(edgeCount),
    };
}
