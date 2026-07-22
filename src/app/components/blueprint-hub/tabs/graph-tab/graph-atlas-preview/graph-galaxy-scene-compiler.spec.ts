import { describe, expect, it } from 'vitest';

import type { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import { mergeGalaxySettings, type GalaxyRenderableNode } from './graph-galaxy-engine';
import {
    compileAuthoritativeGalaxyScene,
    compileGalaxyScene,
    seedAuthoritativeGalaxyScenePacket,
} from './graph-galaxy-scene-compiler';
import {
    galaxyScenePacketV2TransferList,
    packGalaxyScenePacketV2,
    unpackGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';

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

    it('keeps renderer-only styling on the retained scene path', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'style', label: 'Style', kind: 'concept' }];

        const first = await compileGalaxyScene(
            backend,
            entities,
            [],
            mergeGalaxySettings({ labelMode: 'hover' }),
            'receipt:renderer-only',
        );
        const second = await compileGalaxyScene(
            backend,
            entities,
            [],
            mergeGalaxySettings({ labelMode: 'always' }),
            'receipt:renderer-only',
        );

        expect(second).toBe(first);
    });

    it('evicts an inactive expanded manifold scene', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'resident', label: 'Resident', kind: 'concept' }];
        const settings = mergeGalaxySettings({ layoutMode: 'single' });
        const identities = ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'];

        const first = await compileGalaxyScene(backend, entities, [], settings, `resident:${identities[0]}`);
        for (const identity of identities.slice(1)) {
            await compileGalaxyScene(backend, entities, [], settings, `resident:${identity}`);
        }
        const returned = await compileGalaxyScene(backend, entities, [], settings, `resident:${identities[0]}`);

        expect(returned).not.toBe(first);
    });

    it('retains the active expanded scene', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'bounded', label: 'Bounded', kind: 'concept' }];
        const settings = mergeGalaxySettings({ layoutMode: 'single' });
        await compileGalaxyScene(backend, entities, [], settings, 'bounded:0');
        const active = await compileGalaxyScene(backend, entities, [], settings, 'bounded:1');

        expect(await compileGalaxyScene(backend, entities, [], settings, 'bounded:1')).toBe(active);
    });

    it('fails closed when an authoritative packed worker is unavailable', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'strict', label: 'Strict', kind: 'concept' }];

        await expect(compileAuthoritativeGalaxyScene(
            backend,
            entities,
            [],
            mergeGalaxySettings({ layoutMode: 'hybridSpace' }),
            'authority:strict-worker',
            'embeddings',
        )).rejects.toThrow('main-thread compilation is forbidden');
    });

    it('installs a fused prewarm packet into the authoritative scene cache', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'fused', label: 'Fused', kind: 'concept' }];
        const settings = mergeGalaxySettings({ layoutMode: 'hybridSpace', sourceMode: 'embeddings' });
        const renderIdentity = 'generation:fused\u0000embeddings\u0000hybrid\u0000entities\u0000all\u0000';
        const source = galaxySceneToV2({
            nodes: [{
                entity: entities[0],
                x: 1,
                y: 2,
                z: 3,
                baseX: 1,
                baseY: 2,
                baseZ: 3,
                radius: 2,
                r: 20,
                g: 30,
                b: 40,
                sx: 0,
                sy: 0,
                depth: 0,
                galaxyOpacity: 1,
            }],
            links: [],
            layoutMode: 'hybridSpace',
            groups: [],
        }, 'embeddings');
        const packet = packGalaxyScenePacketV2(source, {
            generationId: 'generation:fused',
            authorityReceipt: renderIdentity,
        });

        const installed = seedAuthoritativeGalaxyScenePacket(
            packet,
            settings,
            renderIdentity,
            'embeddings',
        );
        const returned = await compileAuthoritativeGalaxyScene(
            backend,
            entities,
            [],
            settings,
            renderIdentity,
            'embeddings',
        );

        expect(returned).toBe(installed);
        expect(returned.positions3d).toEqual(new Float32Array([1, 2, 3]));
    });

    it('rejects a fused prewarm packet with a mismatched authority receipt', () => {
        const settings = mergeGalaxySettings({ layoutMode: 'hybridSpace', sourceMode: 'embeddings' });
        const source = galaxySceneToV2({ nodes: [], links: [], layoutMode: 'hybridSpace', groups: [] }, 'embeddings');
        const packet = packGalaxyScenePacketV2(source, {
            generationId: 'generation:receipt',
            authorityReceipt: 'wrong-receipt',
        });

        expect(() => seedAuthoritativeGalaxyScenePacket(
            packet,
            settings,
            'generation:receipt\u0000embeddings\u0000hybrid',
            'embeddings',
        )).toThrow('receipt does not match');
    });

    it('returns a small manifest and transferable pages at the 5,119-node target scale', () => {
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

        const source = galaxySceneToV2(scene);
        const packet = packGalaxyScenePacketV2(source, {
            generationId: 'snapshot:5119',
            authorityReceipt: 'receipt:5119',
        });
        const hydrated = unpackGalaxyScenePacketV2(packet);

        expect(packet.manifest.nodeCount).toBe(5_119);
        expect(hydrated.ids[4_000]).toBe(entities[4_000].id);
        expect(hydrated.positions3d[4_000 * 3]).toBe(source.positions3d[4_000 * 3]);
        expect(galaxyScenePacketV2TransferList(packet)).toHaveLength(packet.manifest.pages.length);
        expect(JSON.stringify(packet.manifest).length).toBeLessThan(JSON.stringify(scene).length * 0.05);
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

        expect(scene.ids).toHaveLength(5_119);
        expect(scene.edgePairs.length / 2).toBeGreaterThan(900);
        expect(elapsedMs).toBeLessThan(1_000);
    });
});
