import { describe, expect, it } from 'vitest';

import {
    buildIncidentCsr,
    captureGalaxyRendererV3Positions,
    galaxyRendererV3SuppressNodeActivation,
    GalaxyRendererV3InteractionState,
    restoreGalaxyRendererV3Positions,
} from './galaxy-renderer-v3-interaction';

describe('Galaxy Renderer V3 bounded interaction state', () => {
    it('builds deterministic packed incident CSR without object adjacency', () => {
        const index = buildIncidentCsr(4, Uint32Array.of(0, 1, 1, 2, 1, 3));

        expect(Array.from(index.offsets)).toEqual([0, 1, 4, 5, 6]);
        expect(Array.from(index.incidentEdges)).toEqual([0, 0, 1, 2, 1, 2]);
    });

    it('keeps the hovered node and every bounded incident neighbor illuminated', () => {
        const state = new GalaxyRendererV3InteractionState(4, Uint32Array.of(0, 1, 1, 2, 1, 3));

        const neighborhood = state.applyFocus(1);

        expect(Array.from(neighborhood.nodes)).toEqual([0, 2, 3]);
        expect(Array.from(state.nodeOpacity)).toEqual([1, 1, 1, 1]);
        expect(Array.from(state.edgeOpacity)).toEqual([1, 1, 1]);
    });

    it('restores the unfiltered presentation when hover clears', () => {
        const state = new GalaxyRendererV3InteractionState(3, Uint32Array.of(0, 1));
        state.applyFocus(0);

        state.applyFocus(-1);

        expect(Array.from(state.nodeOpacity)).toEqual([1, 1, 1]);
        expect(Array.from(state.edgeOpacity)).toEqual([1]);
    });

    it('bounds neighborhoods deterministically', () => {
        const state = new GalaxyRendererV3InteractionState(5, Uint32Array.of(0, 1, 0, 2, 0, 3, 0, 4));

        expect(state.neighborhood(0, 2)).toEqual({
            nodes: Uint32Array.of(1, 2),
            edges: Uint32Array.of(0, 1),
            truncated: true,
        });
    });

    it('keeps a short stationary node press eligible for direct-click activation', () => {
        expect(galaxyRendererV3SuppressNodeActivation(true, 0, 120)).toBe(false);
    });

    it('suppresses activation after cumulative node-drag travel', () => {
        expect(galaxyRendererV3SuppressNodeActivation(true, 4.1, 120)).toBe(true);
    });

    it('suppresses activation after a click-and-hold without movement', () => {
        expect(galaxyRendererV3SuppressNodeActivation(true, 0, 350)).toBe(true);
    });

    it('does not apply node activation suppression to camera gestures', () => {
        expect(galaxyRendererV3SuppressNodeActivation(false, 80, 800)).toBe(false);
    });

    it('restores exactly the bounded presentation rows captured for stretch', () => {
        const positions = Float32Array.of(1, 2, 3, 4, 5, 6, 7, 8, 9);
        const indexes = Uint32Array.of(0, 2);
        const snapshot = captureGalaxyRendererV3Positions(positions, indexes);
        positions.set([10, 20, 30], 0);
        positions.set([70, 80, 90], 6);

        restoreGalaxyRendererV3Positions(positions, indexes, snapshot);

        expect(Array.from(positions)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
    });
});
