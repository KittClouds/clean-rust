import { describe, expect, it } from 'vitest';

import { buildGalaxyFocusMask } from './graph-galaxy-focus';
import { boundedLocalGalaxyPath } from './graph-galaxy-interaction-query';
import { attachGalaxySceneRuntimeIndex, type GalaxySceneV2 } from './graph-galaxy-scene-v2';

describe('graph galaxy focus runtime index', () => {
    it('preserves exact hierarchy focus while limiting traversal to incident edges', () => {
        const unindexed = focusScene();
        const indexed = attachGalaxySceneRuntimeIndex(focusScene());

        const expected = buildGalaxyFocusMask(unindexed, 'child', null);
        const actual = buildGalaxyFocusMask(indexed, 'child', null);

        expect(Array.from(actual.nodeLevels)).toEqual(Array.from(expected.nodeLevels));
        expect(Array.from(actual.edgeLevels)).toEqual(Array.from(expected.edgeLevels));
        expect(actual.focusIndex).toBe(expected.focusIndex);
        expect(indexed.runtimeIndex?.nodeById.get('child')).toBe(1);
        const runtime = indexed.runtimeIndex!;
        expect(Array.from(runtime.incidentEdges.subarray(
            runtime.incidentOffsets[1],
            runtime.incidentOffsets[2],
        ))).toEqual([0, 1, 3]);
    });

    it('finds one deterministic unweighted shortest walk and dims everything outside it', () => {
        const scene = attachGalaxySceneRuntimeIndex(focusScene());
        const overlay = boundedLocalGalaxyPath(scene, authority(), 1, 'root', 'aside');
        const focus = buildGalaxyFocusMask(scene, ['root', 'aside'], 'remote', overlay);

        expect(focus.pathFound).toBe(true);
        expect(Array.from(focus.pathNodeIndices)).toEqual([0, 1, 2, 3]);
        expect(Array.from(focus.pathEdgeIndices)).toEqual([0, 1, 2]);
        expect(Array.from(focus.selectedIndices)).toEqual([0, 3]);
        expect(Array.from(focus.nodeLevels)).toEqual([3, 2, 2, 3, 0]);
        expect(Array.from(focus.edgeLevels)).toEqual([3, 3, 3, 0]);
    });

    it('keeps disconnected endpoints selected without inventing a walk', () => {
        const scene = focusScene();
        scene.edgePairs = new Uint32Array([0, 1, 1, 2]);
        scene.edgeIds = ['root-child', 'child-leaf'];
        scene.edgeTypes = ['contains', 'contains'];
        scene.edgeColors = new Float32Array(12);
        scene.edgeAlpha = new Float32Array([1, 1]);
        scene.edgeKinds = new Uint8Array([2, 2]);
        const indexed = attachGalaxySceneRuntimeIndex(scene);
        const overlay = boundedLocalGalaxyPath(indexed, authority(), 2, 'root', 'aside');
        const focus = buildGalaxyFocusMask(indexed, ['root', 'aside'], null, overlay);

        expect(focus.pathFound).toBe(false);
        expect(Array.from(focus.pathNodeIndices)).toEqual([0, 3]);
        expect(focus.pathEdgeIndices).toHaveLength(0);
        expect(Array.from(focus.nodeLevels)).toEqual([3, 0, 0, 3, 0]);
    });

    it('fails closed instead of walking a 10k-node chain in the browser', () => {
        const scene = attachGalaxySceneRuntimeIndex(pathChainScene(10_000));
        const started = performance.now();
        const overlay = boundedLocalGalaxyPath(scene, authority(), 3, 'node:0', 'node:9999');
        const focus = buildGalaxyFocusMask(scene, ['node:0', 'node:9999'], null, overlay);

        expect(overlay).toBeNull();
        expect(focus.pathFound).toBe(false);
        expect(focus.pathNodeIndices).toEqual(Uint32Array.of(0, 9_999));
        expect(performance.now() - started).toBeLessThan(20);
    });
});

function authority() {
    return {
        generationId: 'generation-a',
        manifoldId: 'single',
        authorityReceipt: 'receipt-a',
    };
}

function focusScene(): GalaxySceneV2 {
    return {
        sourceMode: 'graph',
        layoutMode: 'lorentzTree',
        ids: ['root', 'child', 'leaf', 'aside', 'remote'],
        labels: ['Root', 'Child', 'Leaf', 'Aside', 'Remote'],
        kinds: ['concept', 'concept', 'concept', 'concept', 'concept'],
        groupIds: ['', '', '', '', ''],
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array([4, 0, 0, 3, 0, 0, 2, 0, 0, 2, 1, 0, 1, 2, 0]),
        positions2d: new Float32Array([4, 0, 0, 3, 0, 0, 2, 0, 0, 2, 1, 0, 1, 2, 0]),
        radii: new Float32Array([0.1, 0.1, 0.1, 0.1, 0.1]),
        colors: new Float32Array(15),
        edgePairs: new Uint32Array([0, 1, 1, 2, 2, 3, 1, 4]),
        edgeIds: ['root-child', 'child-leaf', 'leaf-aside', 'child-remote'],
        edgeTypes: ['contains', 'contains', 'contains', 'related'],
        edgeColors: new Float32Array(24),
        edgeAlpha: new Float32Array([1, 1, 1, 1]),
        edgeKinds: new Uint8Array([2, 2, 2, 0]),
    };
}

function pathChainScene(count: number): GalaxySceneV2 {
    const edgeCount = count - 1;
    const edgePairs = new Uint32Array(edgeCount * 2);
    for (let edge = 0; edge < edgeCount; edge++) {
        edgePairs[edge * 2] = edge;
        edgePairs[edge * 2 + 1] = edge + 1;
    }
    return {
        ...focusScene(),
        layoutMode: 'single',
        ids: Array.from({ length: count }, (_, index) => `node:${index}`),
        labels: Array.from({ length: count }, (_, index) => `Node ${index}`),
        kinds: Array.from({ length: count }, () => 'concept'),
        groupIds: Array.from({ length: count }, () => ''),
        positions3d: new Float32Array(count * 3),
        positions2d: new Float32Array(count * 3),
        radii: new Float32Array(count).fill(0.1),
        colors: new Float32Array(count * 3),
        edgePairs,
        edgeIds: Array.from({ length: edgeCount }, (_, index) => `edge:${index}`),
        edgeTypes: Array.from({ length: edgeCount }, () => 'related'),
        edgeColors: new Float32Array(edgeCount * 6),
        edgeAlpha: new Float32Array(edgeCount).fill(1),
        edgeKinds: new Uint8Array(edgeCount),
    };
}
