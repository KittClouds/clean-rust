import { describe, expect, it } from 'vitest';

import { buildGalaxyFocusMask } from './graph-galaxy-focus';
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
        expect(indexed.runtimeIndex?.incidentEdges[1]).toEqual([0, 1, 3]);
    });
});

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
