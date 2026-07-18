import { describe, expect, it } from 'vitest';

import {
    galaxyResidencyBudgetForDevice,
    galaxyResidencyTileKey,
    type GalaxyResidencyManifest,
    type GalaxyResidencyTileDescriptor,
    type GalaxyResidencyView,
} from './graph-galaxy-residency.model';
import {
    galaxySphereIntersectsFrustum,
    planGalaxyResidencyRequests,
} from './graph-galaxy-residency-priority';

describe('galaxy residency priority', () => {
    it('selects explicit bounded envelopes for constrained, balanced, and workstation devices', () => {
        expect(galaxyResidencyBudgetForDevice({ deviceMemoryGiB: 4, hardwareConcurrency: 4 })).toMatchObject({
            deviceClass: 'constrained',
            maxNodes: 150_000,
            maxEdges: 250_000,
        });
        expect(galaxyResidencyBudgetForDevice({ deviceMemoryGiB: 8, hardwareConcurrency: 8 })).toMatchObject({
            deviceClass: 'balanced',
            maxNodes: 400_000,
            maxEdges: 700_000,
        });
        expect(galaxyResidencyBudgetForDevice({ deviceMemoryGiB: 32, hardwareConcurrency: 16 })).toMatchObject({
            deviceClass: 'workstation',
            maxNodes: 800_000,
            maxEdges: 1_400_000,
        });
    });

    it('requests visible near-camera coarse coverage before farther tiles', () => {
        const manifest = manifestWithTiles([
            tile('near', 2, [0, 0, 0], 1),
            tile('near', 0, [0, 0, 0], 0.05),
            tile('far', 2, [0, 0, -60], 1),
            tile('far', 0, [0, 0, -60], 0.05),
        ]);
        const requests = planGalaxyResidencyRequests(manifest, view(), {
            token: 1,
            slot: 'front',
            residentKeys: new Set(),
            inFlightKeys: new Set(),
        });

        expect(requests.map((request) => [request.descriptor.spatialKey, request.descriptor.lod])).toEqual([
            ['near', 2],
            ['far', 2],
        ]);
        expect(requests.every((request) => request.reason === 'coverage')).toBe(true);
    });

    it('progressively requests only the next finer LOD when projected error remains high', () => {
        const coarse = tile('near', 2, [0, 0, 0], 2);
        const middle = tile('near', 1, [0, 0, 0], 0.5);
        const fine = tile('near', 0, [0, 0, 0], 0.05);
        const requests = planGalaxyResidencyRequests(manifestWithTiles([coarse, middle, fine]), view(), {
            token: 2,
            slot: 'back',
            residentKeys: new Set([galaxyResidencyTileKey(coarse)]),
            inFlightKeys: new Set(),
        });

        expect(requests).toHaveLength(1);
        expect(requests[0].descriptor.lod).toBe(1);
        expect(requests[0].reason).toBe('refinement');
    });

    it('rejects tiles outside the active frustum before request ranking', () => {
        const activeView = view({
            frustum: [{ normal: [1, 0, 0], constant: 2 }],
        });
        expect(galaxySphereIntersectsFrustum(tile('inside', 0, [0, 0, 0], 0.1).bounds, activeView)).toBe(true);
        expect(galaxySphereIntersectsFrustum(tile('outside', 0, [-10, 0, 0], 0.1).bounds, activeView)).toBe(false);
    });

    it('ranks fifty thousand tile descriptors within the interactive planning budget', () => {
        const tiles = Array.from({ length: 50_000 }, (_, index) =>
            tile(`tile-${index}`, 0, [index % 250, Math.floor(index / 250), -20], 0.1),
        );
        const started = performance.now();
        const requests = planGalaxyResidencyRequests(manifestWithTiles(tiles), view(), {
            token: 3,
            slot: 'front',
            residentKeys: new Set(),
            inFlightKeys: new Set(),
        });
        const elapsed = performance.now() - started;

        expect(requests).toHaveLength(50_000);
        expect(elapsed).toBeLessThan(500);
    });
});

function tile(
    spatialKey: string,
    lod: number,
    center: [number, number, number],
    geometricError: number,
): GalaxyResidencyTileDescriptor {
    return {
        generationId: 'generation-a',
        manifoldId: 'hybridSpace',
        tileId: `${spatialKey}:${lod}`,
        spatialKey,
        lod,
        contentHash: `${spatialKey}:${lod}:hash`,
        authorityReceipt: 'receipt-a',
        bounds: { center, radius: 1 },
        geometricError,
        byteLength: 4096,
        nodeCount: 100,
        edgeCount: 160,
        drawnNodeCount: 80,
        drawnEdgeCount: 100,
        aggregatedNodeCount: lod > 0 ? 20 : 0,
        aggregatedEdgeCount: lod > 0 ? 30 : 0,
    };
}

function manifestWithTiles(tiles: GalaxyResidencyTileDescriptor[]): GalaxyResidencyManifest {
    return {
        generationId: 'generation-a',
        manifoldId: 'hybridSpace',
        authorityReceipt: 'receipt-a',
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
