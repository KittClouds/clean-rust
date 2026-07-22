import { describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';

import { disposeGalaxyObject } from './three-galaxy-resource-owner';

describe('disposeGalaxyObject', () => {
    it('removes and disposes a drawable exactly once', () => {
        const scene = new THREE.Scene();
        const geometry = new THREE.BufferGeometry();
        const material = new THREE.LineBasicMaterial();
        const geometryDispose = vi.spyOn(geometry, 'dispose');
        const materialDispose = vi.spyOn(material, 'dispose');
        const line = new THREE.LineSegments(geometry, material);
        scene.add(line);

        disposeGalaxyObject(scene, line);

        expect(scene.children).not.toContain(line);
        expect(geometryDispose).toHaveBeenCalledTimes(1);
        expect(materialDispose).toHaveBeenCalledTimes(1);
    });

    it('walks group children and disposes material arrays', () => {
        const scene = new THREE.Scene();
        const group = new THREE.Group();
        const geometry = new THREE.BufferGeometry();
        const first = new THREE.MeshBasicMaterial();
        const second = new THREE.MeshBasicMaterial();
        const firstDispose = vi.spyOn(first, 'dispose');
        const secondDispose = vi.spyOn(second, 'dispose');
        group.add(new THREE.Mesh(geometry, [first, second]));
        scene.add(group);

        disposeGalaxyObject(scene, group);

        expect(firstDispose).toHaveBeenCalledTimes(1);
        expect(secondDispose).toHaveBeenCalledTimes(1);
    });
});
