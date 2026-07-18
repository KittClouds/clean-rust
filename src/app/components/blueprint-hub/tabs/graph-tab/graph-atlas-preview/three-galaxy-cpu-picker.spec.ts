import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { mergeGalaxySettings } from './graph-galaxy-engine';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { ThreeGalaxyCpuPicker } from './three-galaxy-cpu-picker';

describe('ThreeGalaxyCpuPicker bounded fallback', () => {
    it('preserves small-scene node, edge, group, and lasso hit parity', () => {
        const picker = new ThreeGalaxyCpuPicker();
        const data = scene();
        const camera = new THREE.OrthographicCamera(-2, 2, 2, -2, 0.01, 20);
        camera.position.set(0, 0, 5);
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();
        camera.updateMatrixWorld();
        const viewport = { width: 400, height: 400 };

        expect(picker.pickNode(
            data,
            data.positions3d,
            camera,
            { ...viewport, x: 100, y: 200 },
            mergeGalaxySettings(null),
        )).toBe(0);
        expect(picker.pickEdge(
            data,
            data.positions3d,
            camera,
            { ...viewport, x: 200, y: 200 },
        )).toBe(0);
        expect(picker.pickGroup(
            data,
            camera,
            { ...viewport, x: 200, y: 200 },
            '3d',
        )).toMatchObject({ kind: 'cluster', id: 'group:all' });
        expect(picker.nodesInRect(data, data.positions3d, camera, {
            ...viewport,
            left: 0,
            top: 0,
            right: 200,
            bottom: 400,
        })).toEqual(['a']);
    });
});

function scene(): GalaxySceneV2 {
    return {
        sourceMode: 'graph',
        layoutMode: 'single',
        ids: ['a', 'b'],
        labels: ['A', 'B'],
        kinds: ['entity', 'entity'],
        groupIds: ['group:all', 'group:all'],
        groups: [{
            id: 'group:all',
            label: 'All',
            kind: 'other',
            nodeIds: ['a', 'b'],
            center: { x: 0, y: 0, z: 0 },
            radius: 1.2,
            color: { r: 1, g: 1, b: 1 },
            importance: 1,
        }],
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
        edgeAlpha: new Float32Array([1]),
        edgeKinds: new Uint8Array([0]),
    };
}
