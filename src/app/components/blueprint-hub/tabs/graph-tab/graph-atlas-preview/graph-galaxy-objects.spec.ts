import { describe, expect, it } from 'vitest';

import {
    SPHERE_NODE_RENDER_SCALE,
    buildGalaxyNodes,
    galaxyNodePickShapeBoost,
    galaxyNodeShapeScale,
    galaxySphereNodeBatch,
} from './graph-galaxy-objects';
import { mergeGalaxySettings, type GalaxySphereSurfaceMode } from './graph-galaxy-engine';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import * as THREE from 'three';

describe('galaxy node shape rendering', () => {
    const baseState = {
        active: false,
        hovered: false,
        neighbor: false,
        dimmed: false,
        transitAtom: false,
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

    it('A/B flips sphere nodes between solid and colored B-glass', () => {
        const scene = { ids: ['node:a'] } as GalaxySceneV2;
        const texture = new THREE.Texture();
        const solid = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'solid' }), texture, texture);
        const glass = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'glass' }), texture, texture);
        const batch = galaxySphereNodeBatch(glass);

        expect((solid?.children[0] as THREE.Mesh).material).toBeInstanceOf(THREE.MeshBasicMaterial);
        expect(batch?.meshes[1].material).toBeInstanceOf(THREE.ShaderMaterial);
        const material = batch?.meshes[1].material as THREE.ShaderMaterial | undefined;
        expect(material?.userData['glassSurface']).toBe('b-glass-marble');
        expect(material?.userData['sphereSurface']).toBe('glass');
        expect(material?.vertexShader).toContain('instanceColor');
        expect(material?.fragmentShader).toContain('rimStrength');
        expect(material?.fragmentShader).toContain('sheen');
        expect(material?.fragmentShader).not.toContain('bloom');
        expect(material?.uniforms['opacity'].value).toBeGreaterThan(0.7);
        expect(material?.uniforms['sheen'].value).toBeLessThan(0.05);
        expect(material?.transparent).toBe(true);
        expect(material?.depthWrite).toBe(false);

        texture.dispose();
    });

    it('batches B-glass spheres into colored shader instances instead of per-node meshes', () => {
        const scene = { ids: ['node:a', 'node:b', 'node:c'] } as GalaxySceneV2;
        const texture = new THREE.Texture();
        const glass = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'glass' }), texture, texture);
        const batch = galaxySphereNodeBatch(glass);

        expect(batch?.meshes).toHaveLength(4);
        expect(glass?.children).toHaveLength(4);
        expect(batch?.meshes.every((mesh) => mesh instanceof THREE.InstancedMesh)).toBe(true);
        expect(batch?.meshes.every((mesh) => mesh.count === scene.ids.length)).toBe(true);
        expect(batch?.meshes.every((mesh) => mesh.material instanceof THREE.ShaderMaterial)).toBe(true);
        expect(batch?.meshes.every((mesh) => mesh.instanceColor?.count === scene.ids.length)).toBe(true);
        expect(batch?.meshes.every((mesh) => mesh.instanceColor?.usage === THREE.DynamicDrawUsage)).toBe(true);
        expect((batch?.meshes[1].material as THREE.ShaderMaterial | undefined)?.userData['sphereState']).toBe('normal');

        texture.dispose();
    });

    it('keeps C, D, and E visually distinct inside the shared instanced sphere contract', () => {
        const scene = { ids: ['node:a', 'node:b'] } as GalaxySceneV2;
        const texture = new THREE.Texture();
        const recipes = [
            { surface: 'spellglass' as const, name: 'CSpellglassMarble', token: 'shellBand', blending: THREE.NormalBlending },
            { surface: 'obsidian' as const, name: 'DObsidianCrescent', token: 'crescent', blending: THREE.NormalBlending },
            { surface: 'starcore' as const, name: 'EStarcore', token: 'equator', blending: THREE.NormalBlending },
        ];

        for (const recipe of recipes) {
            const group = buildGalaxyNodes(
                scene,
                mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: recipe.surface }),
                texture,
                texture,
            );
            const batch = galaxySphereNodeBatch(group);
            const material = batch?.meshes[1].material as THREE.ShaderMaterial | undefined;
            expect(batch?.meshes).toHaveLength(4);
            expect(batch?.meshes.every((mesh) => mesh instanceof THREE.InstancedMesh)).toBe(true);
            expect(batch?.meshes.every((mesh) => mesh.count === scene.ids.length)).toBe(true);
            expect(material?.name).toBe(recipe.name);
            expect(material?.userData['sphereSurface']).toBe(recipe.surface);
            expect(material?.fragmentShader).toContain(recipe.token);
            expect(material?.blending).toBe(recipe.blending);
            expect(material?.depthWrite).toBe(false);
        }

        expect(mergeGalaxySettings({ sphereSurface: 'spellglass' }).sphereSurface).toBe('spellglass');
        expect(mergeGalaxySettings({ sphereSurface: 'obsidian' }).sphereSurface).toBe('obsidian');
        expect(mergeGalaxySettings({ sphereSurface: 'starcore' }).sphereSurface).toBe('starcore');
        expect(mergeGalaxySettings({ sphereSurface: 'lattice' as GalaxySphereSurfaceMode }).sphereSurface).toBe('starcore');
        expect(mergeGalaxySettings({ sphereSurface: 'retired' as GalaxySphereSurfaceMode }).sphereSurface).toBe('solid');

        texture.dispose();
    });
});
