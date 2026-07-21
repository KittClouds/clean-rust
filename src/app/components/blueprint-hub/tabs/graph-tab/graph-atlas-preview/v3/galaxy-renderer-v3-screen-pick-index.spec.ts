import { describe, expect, it } from 'vitest';

import { GalaxyRendererV3ScreenPickIndex } from './galaxy-renderer-v3-screen-pick-index';

describe('Galaxy Renderer V3 screen pick index', () => {
    it('selects from local screen buckets and uses depth as an exact tie-breaker', () => {
        const index = new GalaxyRendererV3ScreenPickIndex();
        index.begin(4, 320, 200);
        index.project(0, 20, 20, 0.5);
        index.project(1, 200, 120, 0.4);
        index.project(2, 200, 120, -0.2);
        index.project(3, 600, 600, 0);
        index.seal();

        expect(index.pick(200, 120, new Float32Array([2, 2, 2, 2]))).toBe(2);
        expect(index.lastExamined).toBe(2);
        expect(index.pick(90, 90, new Float32Array([2, 2, 2, 2]))).toBe(-1);
        expect(index.lastExamined).toBe(0);
    });

    it('bounds pathological overlap instead of allowing a hover corpus scan', () => {
        const nodeCount = 2_000;
        const index = new GalaxyRendererV3ScreenPickIndex();
        index.begin(nodeCount, 320, 200);
        for (let node = 0; node < nodeCount; node++) index.project(node, 120, 80, node / nodeCount);
        index.seal();

        expect(index.pick(120, 80, new Float32Array(nodeCount).fill(4))).toBe(0);
        expect(index.lastExamined).toBe(512);
        expect(index.droppedNodeCount).toBe(nodeCount - 512);
    });

    it('reuses the index after a camera projection rebuild', () => {
        const index = new GalaxyRendererV3ScreenPickIndex();
        const radii = new Float32Array([3]);
        index.begin(1, 200, 100);
        index.project(0, 40, 40, 0);
        index.seal();
        expect(index.pick(40, 40, radii)).toBe(0);

        index.begin(1, 200, 100);
        index.project(0, 160, 60, 0);
        index.seal();
        expect(index.pick(40, 40, radii)).toBe(-1);
        expect(index.pick(160, 60, radii)).toBe(0);
    });
});
