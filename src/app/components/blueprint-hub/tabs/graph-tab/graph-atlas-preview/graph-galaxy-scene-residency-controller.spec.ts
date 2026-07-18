import { describe, expect, it } from 'vitest';

import { mergeGalaxySettings } from './graph-galaxy-engine';
import { GalaxySceneResidencyController } from './graph-galaxy-scene-residency-controller';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

describe('GalaxySceneResidencyController compatibility bridge', () => {
    it('routes current whole scenes through the bounded double-buffer authority', async () => {
        const activations: string[] = [];
        const counters: Array<{ generationId: string; transitioning: boolean; residentTiles: number }> = [];
        const controller = new GalaxySceneResidencyController({
            activate: ({ scene }) => activations.push(`${scene.layoutMode}:${scene.ids.join(',')}`),
            counters: (value) => counters.push({
                generationId: value.generationId,
                transitioning: value.transitioning,
                residentTiles: value.residentTiles,
            }),
        });

        await controller.install({
            generationId: 'generation-a',
            authorityReceipt: 'receipt-a',
            corpus: { nodes: 10_000_000, edges: 10_000_000 },
            payload: {
                scene: scene('hybridSpace', ['a', 'b']),
                settings: mergeGalaxySettings(null),
                mode: '3d',
                selectedIds: [],
            },
        });
        await controller.install({
            generationId: 'generation-a',
            authorityReceipt: 'receipt-b',
            corpus: { nodes: 10_000_000, edges: 10_000_000 },
            payload: {
                scene: scene('hopfProjection', ['a', 'b']),
                settings: mergeGalaxySettings(null),
                mode: '3d',
                selectedIds: ['a'],
            },
        });

        expect(activations).toEqual([
            'hybridSpace:a,b',
            'hopfProjection:a,b',
        ]);
        expect(controller.snapshotCounters()).toMatchObject({
            generationId: 'generation-a',
            manifoldId: 'hopfProjection',
            transitioning: false,
            corpus: { nodes: 10_000_000, edges: 10_000_000 },
            resident: { nodes: 2, edges: 1 },
            residentTiles: 1,
        });
        expect(counters.some((value) => value.transitioning)).toBe(true);
        controller.dispose();
    });

    it('keeps resident canvas counts fixed when the declared corpus doubles', async () => {
        const controller = new GalaxySceneResidencyController({
            activate: () => undefined,
            counters: () => undefined,
        });
        const payload = {
            scene: scene('hybridSpace', ['a', 'b']),
            settings: mergeGalaxySettings(null),
            mode: '3d' as const,
            selectedIds: [],
        };

        await controller.install({
            generationId: 'generation-10m',
            authorityReceipt: 'receipt-10m',
            corpus: { nodes: 10_000_000, edges: 10_000_000 },
            payload,
        });
        const tenMillion = controller.snapshotCounters();
        await controller.install({
            generationId: 'generation-20m',
            authorityReceipt: 'receipt-20m',
            corpus: { nodes: 20_000_000, edges: 20_000_000 },
            payload,
        });
        const twentyMillion = controller.snapshotCounters();

        expect(twentyMillion.resident).toEqual(tenMillion.resident);
        expect(twentyMillion.drawn).toEqual(tenMillion.drawn);
        expect(twentyMillion.residentBytes).toBe(tenMillion.residentBytes);
        expect(twentyMillion.corpus).toEqual({ nodes: 20_000_000, edges: 20_000_000 });
        controller.dispose();
    });
});

function scene(layoutMode: GalaxySceneV2['layoutMode'], ids: string[]): GalaxySceneV2 {
    return {
        sourceMode: 'graph',
        layoutMode,
        ids,
        labels: ids,
        kinds: ids.map(() => 'entity'),
        groupIds: ids.map(() => ''),
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array([-1, 0, 0, 1, 0, 0]),
        positions2d: new Float32Array([-1, 0, 0, 1, 0, 0]),
        radii: new Float32Array([0.1, 0.1]),
        colors: new Float32Array([1, 0, 0, 0, 1, 1]),
        edgePairs: new Uint32Array([0, 1]),
        edgeIds: ['a->b'],
        edgeTypes: ['related'],
        edgeColors: new Float32Array([1, 0, 0, 0, 1, 1]),
        edgeAlpha: new Float32Array([0.5]),
        edgeKinds: new Uint8Array([0]),
    };
}
