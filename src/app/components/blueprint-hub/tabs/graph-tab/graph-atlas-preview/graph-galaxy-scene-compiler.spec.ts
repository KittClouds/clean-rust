import { describe, expect, it } from 'vitest';

import type { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import { mergeGalaxySettings, type GalaxyRenderableNode } from './graph-galaxy-engine';
import { compileGalaxyScene } from './graph-galaxy-scene-compiler';
import { compactGalaxySceneForTransfer, hydrateGalaxySceneFromTransfer } from './graph-galaxy-worker-scene';

describe('graph galaxy compiled scene cache', () => {
    it('reuses the exact compiled layout for the same render identity', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'a', label: 'A', kind: 'concept' }];
        const settings = mergeGalaxySettings({ layoutMode: 'single' });

        const first = await compileGalaxyScene(backend, entities, [], settings, 'receipt:same');
        const second = await compileGalaxyScene(backend, [...entities], [], settings, 'receipt:same');

        expect(second).toBe(first);
    });

    it('does not reuse a layout when a layout setting changes', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'b', label: 'B', kind: 'concept' }];

        const first = await compileGalaxyScene(backend, entities, [], mergeGalaxySettings({ edgeLength: 1 }), 'receipt:settings');
        const second = await compileGalaxyScene(backend, entities, [], mergeGalaxySettings({ edgeLength: 2 }), 'receipt:settings');

        expect(second).not.toBe(first);
    });

    it('returns only compact geometry across the worker boundary at the 5,119-node target scale', () => {
        const entities = Array.from({ length: 5_119 }, (_, index): GalaxyRenderableNode => ({
            id: `node:${index}`,
            label: `Node ${index}`,
            kind: 'evidence',
            metadata: { payload: 'frozen-receipt-metadata'.repeat(24), ordinal: index },
        }));
        const scene = {
            nodes: entities.map((entity, index) => ({
                entity,
                x: index / 5_119,
                y: -index / 5_119,
                z: index % 11,
                baseX: index / 5_119,
                baseY: -index / 5_119,
                baseZ: index % 11,
                radius: 2.1,
                r: 12,
                g: 220,
                b: 240,
                sx: 0,
                sy: 0,
                depth: 0,
                galaxyOpacity: 1,
            })),
            links: [],
            layoutMode: 'single' as const,
            groups: [],
        };

        const compact = compactGalaxySceneForTransfer(scene);
        const hydrated = hydrateGalaxySceneFromTransfer(compact, entities);

        expect(compact.nodes).toHaveLength(5_119);
        expect('entity' in compact.nodes[0]).toBe(false);
        expect(hydrated.nodes[4_000].entity).toBe(entities[4_000]);
        expect(hydrated.nodes[4_000].x).toBe(scene.nodes[4_000].x);
        expect(JSON.stringify(compact).length).toBeLessThan(JSON.stringify(scene).length * 0.35);
    });

    it('compiles the 5,119-node and 987-edge Siegel workload within the one-second CPU budget', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities = Array.from({ length: 5_119 }, (_, index): GalaxyRenderableNode => ({
            id: `siegel:${index}`,
            label: `Signal ${index}`,
            kind: index % 5 === 0 ? 'chunk' : 'evidence',
            totalMentions: 1 + index % 7,
            atlasX: ((index % 97) - 48) / 48,
            atlasY: ((index % 89) - 44) / 44,
            atlasZ: ((index % 83) - 41) / 41,
            metadata: {
                graphKind: index % 5 === 0 ? 'chunk' : 'anchor',
                signalLane: index % 3 === 0 ? 'document' : 'evidence',
                signalStructuralRole: index % 5 === 0 ? 'spine' : 'evidence',
            },
        }));
        const edges = Array.from({ length: 987 }, (_, index) => ({
            id: `edge:${index}`,
            sourceId: entities[index].id,
            targetId: entities[(index * 7 + 31) % entities.length].id,
            type: index % 4 === 0 ? 'target-parent' : 'evidence',
            confidence: 0.8,
        }));
        const started = performance.now();
        const scene = await compileGalaxyScene(
            backend,
            entities,
            edges,
            mergeGalaxySettings({ layoutMode: 'siegelFinsler' }),
            'perf:siegel:5119:987',
        );
        const elapsedMs = performance.now() - started;

        expect(scene.nodes).toHaveLength(5_119);
        expect(scene.links.length).toBeGreaterThan(900);
        expect(elapsedMs).toBeLessThan(1_000);
    });
});
