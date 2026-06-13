import { describe, expect, it } from 'vitest';

import {
    SPHERE_NODE_RENDER_SCALE,
    buildGalaxyNodes,
    galaxyNodePickShapeBoost,
    galaxyNodeShapeScale,
} from './graph-galaxy-objects';
import { mergeGalaxySettings } from './graph-galaxy-engine';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import * as THREE from 'three';

describe('galaxy node shape rendering', () => {
    const baseState = {
        active: false,
        hovered: false,
        neighbor: false,
        dimmed: false,
        productAtom: false,
    };

    it('renders sphere nodes at 45% of their original scale in every focus state', () => {
        expect(SPHERE_NODE_RENDER_SCALE).toBe(0.45);
        expect(galaxyNodeShapeScale('sphere', baseState)).toBeCloseTo(0.27, 6);
        expect(galaxyNodeShapeScale('sphere', { ...baseState, active: true })).toBeCloseTo(0.4005, 6);
        expect(galaxyNodeShapeScale('sphere', { ...baseState, neighbor: true })).toBeCloseTo(0.324, 6);
        expect(galaxyNodeShapeScale('sphere', { ...baseState, dimmed: true })).toBeCloseTo(0.234, 6);
    });

    it('keeps atom and halo scales unchanged while tightening sphere picking', () => {
        expect(galaxyNodeShapeScale('atom', baseState)).toBeCloseTo(1.6, 6);
        expect(galaxyNodeShapeScale('halo', baseState)).toBeCloseTo(1.72, 6);
        expect(galaxyNodePickShapeBoost('sphere')).toBe(2);
    });

    it('A/B flips sphere nodes between solid and tinted physical glass', () => {
        const scene = { ids: ['node:a'] } as GalaxySceneV2;
        const texture = new THREE.Texture();
        const solid = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'solid' }), texture, texture);
        const glass = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'glass' }), texture, texture);

        expect((solid?.children[0] as THREE.Mesh).material).toBeInstanceOf(THREE.MeshBasicMaterial);
        expect((glass?.children[0] as THREE.Mesh).material).toBeInstanceOf(THREE.MeshPhysicalMaterial);
        const glassMaterial = (glass?.children[0] as THREE.Mesh).material as THREE.MeshPhysicalMaterial;
        expect(glassMaterial.transmission).toBeCloseTo(0.2, 6);
        expect(glassMaterial.clearcoat).toBe(1);

        texture.dispose();
    });
});
