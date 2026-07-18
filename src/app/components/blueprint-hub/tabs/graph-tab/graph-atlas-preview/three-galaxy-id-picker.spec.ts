import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { ThreeGalaxyIdPicker } from './three-galaxy-id-picker';

describe('ThreeGalaxyIdPicker', () => {
    it('keeps numeric IDs and positions in packed GPU attributes', () => {
        const picker = new ThreeGalaxyIdPicker();
        picker.bind(scene(), new Float32Array([-1, 0, 0, 1, 0, 0]), 1);
        const internal = picker as unknown as {
            points: THREE.Points<THREE.BufferGeometry, THREE.RawShaderMaterial>;
        };
        const geometry = internal.points.geometry;

        expect(geometry.getAttribute('aPickId').array).toBeInstanceOf(Uint32Array);
        expect(geometry.getAttribute('position').array).toBeInstanceOf(Float32Array);
        expect(internal.points.material.vertexShader).toContain('in uint aPickId;');
        expect(internal.points.material.fragmentShader).toContain('vPickId >> 24u');
        picker.dispose();
    });
});

function scene(): GalaxySceneV2 {
    return {
        sourceMode: 'graph',
        layoutMode: 'single',
        ids: ['a', 'b'],
        labels: ['A', 'B'],
        kinds: ['entity', 'entity'],
        groupIds: ['', ''],
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array(6),
        positions2d: new Float32Array(6),
        radii: new Float32Array([0.1, 0.1]),
        colors: new Float32Array(6),
        edgePairs: new Uint32Array([0, 1]),
        edgeIds: ['a-b'],
        edgeTypes: ['related'],
        edgeColors: new Float32Array(6),
        edgeAlpha: new Float32Array([1]),
        edgeKinds: new Uint8Array([0]),
    };
}
