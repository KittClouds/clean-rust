import { describe, expect, it } from 'vitest';

import { GalaxyTsResidencyManager } from './graph-galaxy-residency-manager';
import {
    assertGalaxyTsMaterializationBound,
    galaxyResidencyBudgetForDevice,
    type GalaxyResidencyGpuPort,
    type GalaxyResidencyManifest,
    type GalaxyResidencyRequest,
    type GalaxyResidencyTileDescriptor,
    type GalaxyResidencyTileProvider,
    type GalaxyResidencyView,
    type GalaxyResidentTile,
} from './graph-galaxy-residency.model';

type Payload = { id: string };

describe('GalaxyTsResidencyManager', () => {
    it('rejects whole-corpus TS materialization above the device envelope', () => {
        const budget = galaxyResidencyBudgetForDevice({ deviceMemoryGiB: 8, hardwareConcurrency: 8 });

        expect(() => assertGalaxyTsMaterializationBound(
            { nodes: 10_000_000, edges: 10_000_000 },
            { nodes: 10_000_000, edges: 10_000_000 },
            budget,
        )).toThrow(/whole-corpus materialization rejected/);
        expect(() => assertGalaxyTsMaterializationBound(
            { nodes: 20_000_000, edges: 20_000_000 },
            { nodes: 100_000, edges: 160_000 },
            budget,
        )).not.toThrow();
    });

    it('installs coarse coverage first, activates it, then replaces it with finer LOD', async () => {
        const events: string[] = [];
        const coarse = tile('generation-a', 'hybrid', 'near', 1, 2);
        const fine = tile('generation-a', 'hybrid', 'near', 0, 0.02);
        const manager = managerWith({
            events,
            provider: immediateProvider(),
            minimumTransitionCoverage: 1,
        });

        manager.beginTransition(manifest('generation-a', 'hybrid', [coarse, fine]));
        manager.updateView(view());
        await manager.waitForIdle();

        expect(events).toEqual([
            'install:front:near:1',
            'activate:front:generation-a:hybrid',
            'install:front:near:0',
            'evict:front:near:1',
        ]);
        expect(manager.snapshotCounters()).toMatchObject({
            transitioning: false,
            resident: { nodes: 100, edges: 160 },
            visible: { nodes: 100, edges: 160 },
            drawn: { nodes: 80, edges: 100 },
            aggregated: { nodes: 0, edges: 0 },
        });
    });

    it('cancels stale generation requests and never installs their late result', async () => {
        const events: string[] = [];
        let staleSignal: AbortSignal | undefined;
        const provider: GalaxyResidencyTileProvider<Payload> = {
            loadTile: (request, signal) => {
                if (request.descriptor.generationId === 'generation-stale') {
                    staleSignal = signal;
                    return new Promise((_resolve, reject) => {
                        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
                    });
                }
                return Promise.resolve(residentTile(request));
            },
        };
        const manager = managerWith({ events, provider });

        manager.beginTransition(manifest('generation-stale', 'hybrid', [
            tile('generation-stale', 'hybrid', 'stale', 0, 0.01),
        ]));
        manager.updateView(view());
        await Promise.resolve();
        manager.beginTransition(manifest('generation-current', 'caps', [
            tile('generation-current', 'caps', 'current', 0, 0.01),
        ]));
        manager.updateView(view({ epoch: 2 }));
        await manager.waitForIdle();

        expect(staleSignal?.aborted).toBe(true);
        expect(events.some((event) => event.includes('stale'))).toBe(false);
        expect(events.some((event) => event.endsWith(':generation-current:caps'))).toBe(true);
    });

    it('keeps the front buffer active until back-buffer coverage is ready', async () => {
        const events: string[] = [];
        const next = deferred<GalaxyResidentTile<Payload>>();
        const provider: GalaxyResidencyTileProvider<Payload> = {
            loadTile: (request) => request.descriptor.generationId === 'generation-b'
                ? next.promise
                : Promise.resolve(residentTile(request)),
        };
        const manager = managerWith({ events, provider });

        manager.beginTransition(manifest('generation-a', 'hybrid', [
            tile('generation-a', 'hybrid', 'full', 0, 0.01),
        ]));
        manager.updateView(view());
        await manager.waitForIdle();
        manager.beginTransition(manifest('generation-b', 'hopf', [
            tile('generation-b', 'hopf', 'full', 0, 0.01),
        ]));
        manager.updateView(view({ epoch: 2 }));
        await Promise.resolve();

        expect(manager.snapshotCounters().transitioning).toBe(true);
        expect(events.at(-1)).toBe('activate:front:generation-a:hybrid');

        next.resolve({
            descriptor: tile('generation-b', 'hopf', 'full', 0, 0.01),
            payload: { id: 'generation-b:full:0' },
        });
        await manager.waitForIdle();

        const activateBack = events.indexOf('activate:back:generation-b:hopf');
        const evictFront = events.indexOf('evict:front:full:0');
        expect(activateBack).toBeGreaterThan(-1);
        expect(evictFront).toBeGreaterThan(activateBack);
    });

    it('admits only the nearest tiles that fit the device envelope', async () => {
        const events: string[] = [];
        const budget = {
            ...galaxyResidencyBudgetForDevice({ deviceMemoryGiB: 4, hardwareConcurrency: 4 }),
            maxTiles: 2,
            maxNodes: 200,
            maxEdges: 320,
            maxConcurrentRequests: 4,
        };
        const manager = managerWith({
            events,
            provider: immediateProvider(),
            budget,
            minimumTransitionCoverage: 0.5,
        });
        const tiles = [
            tile('generation-a', 'hybrid', 'near', 0, 0.01, [0, 0, 0]),
            tile('generation-a', 'hybrid', 'middle', 0, 0.01, [0, 0, -20]),
            tile('generation-a', 'hybrid', 'far', 0, 0.01, [0, 0, -80]),
        ];

        manager.beginTransition(manifest('generation-a', 'hybrid', tiles));
        manager.updateView(view());
        await manager.waitForIdle();

        expect(events.filter((event) => event.startsWith('install')).map((event) => event.split(':')[2])).toEqual([
            'near',
            'middle',
        ]);
        expect(manager.snapshotCounters()).toMatchObject({
            residentTiles: 2,
            resident: { nodes: 200, edges: 320 },
        });
    });
});

function managerWith(options: {
    events: string[];
    provider: GalaxyResidencyTileProvider<Payload>;
    budget?: ReturnType<typeof galaxyResidencyBudgetForDevice>;
    minimumTransitionCoverage?: number;
}): GalaxyTsResidencyManager<Payload> {
    const gpu: GalaxyResidencyGpuPort<Payload> = {
        installTile: (tile, slot) => options.events.push(`install:${slot}:${tile.descriptor.tileId}`),
        evictTile: (tile, slot) => options.events.push(`evict:${slot}:${tile.descriptor.tileId}`),
        activate: (slot, generationId, manifoldId) =>
            options.events.push(`activate:${slot}:${generationId}:${manifoldId}`),
    };
    return new GalaxyTsResidencyManager({
        budget: options.budget ?? galaxyResidencyBudgetForDevice({ deviceMemoryGiB: 8, hardwareConcurrency: 8 }),
        provider: options.provider,
        gpu,
        minimumTransitionCoverage: options.minimumTransitionCoverage,
    });
}

function immediateProvider(): GalaxyResidencyTileProvider<Payload> {
    return { loadTile: async (request) => residentTile(request) };
}

function residentTile(request: GalaxyResidencyRequest): GalaxyResidentTile<Payload> {
    return {
        descriptor: request.descriptor,
        payload: { id: `${request.descriptor.generationId}:${request.descriptor.tileId}` },
    };
}

function tile(
    generationId: string,
    manifoldId: string,
    spatialKey: string,
    lod: number,
    geometricError: number,
    center: [number, number, number] = [0, 0, 0],
): GalaxyResidencyTileDescriptor {
    return {
        generationId,
        manifoldId,
        tileId: `${spatialKey}:${lod}`,
        spatialKey,
        lod,
        contentHash: `${generationId}:${manifoldId}:${spatialKey}:${lod}`,
        authorityReceipt: `${generationId}:receipt`,
        bounds: { center, radius: 1 },
        geometricError,
        byteLength: 4096,
        nodeCount: 100,
        edgeCount: 160,
        drawnNodeCount: 80,
        drawnEdgeCount: 100,
        aggregatedNodeCount: lod ? 20 : 0,
        aggregatedEdgeCount: lod ? 30 : 0,
    };
}

function manifest(
    generationId: string,
    manifoldId: string,
    tiles: GalaxyResidencyTileDescriptor[],
): GalaxyResidencyManifest {
    return {
        generationId,
        manifoldId,
        authorityReceipt: `${generationId}:receipt`,
        corpus: { nodes: 10_000_000, edges: 10_000_000 },
        tiles,
    };
}

function view(overrides: Partial<GalaxyResidencyView> = {}): GalaxyResidencyView {
    return {
        camera: [0, 0, 8],
        viewportHeight: 1080,
        verticalFovRadians: Math.PI / 3,
        targetErrorPixels: 1.25,
        frustum: [],
        epoch: 1,
        ...overrides,
    };
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void;
    return {
        promise: new Promise<T>((complete) => { resolve = complete; }),
        resolve,
    };
}
