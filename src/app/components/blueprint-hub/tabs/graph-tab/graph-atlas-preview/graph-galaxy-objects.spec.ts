import { describe, expect, it } from 'vitest';

import {
    SPHERE_NODE_RENDER_SCALE,
    buildGalaxyGlows,
    buildGalaxyNodes,
    galaxyBillboardNodeBatch,
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

    it('A/B flips sphere nodes between solid and the B-aurora reliquary', () => {
        const scene = { ids: ['node:a'] } as GalaxySceneV2;
        const texture = new THREE.Texture();
        const solid = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'solid' }), texture, texture);
        const glass = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'sphere', sphereSurface: 'glass' }), texture, texture);
        const batch = galaxySphereNodeBatch(glass);
        const solidBatch = galaxySphereNodeBatch(solid);

        expect((solid?.children[0] as THREE.Mesh).material).toBeInstanceOf(THREE.MeshBasicMaterial);
        expect(solidBatch?.meshes).toHaveLength(4);
        expect(batch?.meshes[1].material).toBeInstanceOf(THREE.ShaderMaterial);
        const material = batch?.meshes[1].material as THREE.ShaderMaterial | undefined;
        expect(material?.name).toBe('BAuroraReliquary');
        expect(material?.userData['sphereDesign']).toBe('b-aurora-reliquary');
        expect(material?.userData['sphereSurface']).toBe('glass');
        expect(material?.vertexShader).toContain('instanceColor');
        expect(material?.fragmentShader).toContain('rimStrength');
        expect(material?.fragmentShader).toContain('auroraRibbon');
        expect(material?.fragmentShader).toContain('eclipseCore');
        expect(material?.fragmentShader).toContain('coronaColor');
        expect(material?.fragmentShader).toContain('source / max(sourcePeak');
        expect(material?.fragmentShader).not.toContain('source.gbr');
        expect(material?.fragmentShader).not.toContain('source.brg');
        expect(material?.fragmentShader).not.toContain('shellBand');
        expect(material?.fragmentShader).not.toContain('bloom');
        expect(material?.uniforms['opacity'].value).toBeGreaterThan(0.7);
        expect(material?.uniforms['sheen'].value).toBeLessThan(0.05);
        expect(material?.transparent).toBe(true);
        expect(material?.depthWrite).toBe(false);

        texture.dispose();
    });

    it('batches atom and halo nodes into one textured draw each', () => {
        const scene = { ids: ['node:a', 'node:b', 'node:c'] } as GalaxySceneV2;
        const nodeTexture = new THREE.Texture();
        const atomTexture = new THREE.Texture();
        const atom = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'atom' }), nodeTexture, atomTexture);
        const halo = buildGalaxyNodes(scene, mergeGalaxySettings({ nodeShape: 'halo' }), nodeTexture, atomTexture);
        const atomBatch = galaxyBillboardNodeBatch(atom);
        const haloBatch = galaxyBillboardNodeBatch(halo);

        expect(atom?.children).toHaveLength(1);
        expect(halo?.children).toHaveLength(1);
        expect(atomBatch?.points).toBeInstanceOf(THREE.Points);
        expect(haloBatch?.points).toBeInstanceOf(THREE.Points);
        expect(atomBatch?.positions).toHaveLength(scene.ids.length * 3);
        expect(atomBatch?.points.material.uniforms['nodeTexture'].value).toBe(atomTexture);
        expect(haloBatch?.points.material.uniforms['nodeTexture'].value).toBe(nodeTexture);
        expect(atomBatch?.points.material.fragmentShader).toContain('0.055');
        expect(atomBatch?.points.material.vertexColors).toBe(true);
        expect(atomBatch?.points.material.vertexShader).not.toContain('attribute vec3 color;');

        const glow = buildGalaxyGlows(scene, nodeTexture);
        const glowMaterial = (glow?.children[0] as THREE.Points | undefined)?.material as THREE.ShaderMaterial | undefined;
        expect(glowMaterial?.vertexColors).toBe(true);
        expect(glowMaterial?.vertexShader).not.toContain('attribute vec3 color;');

        atom?.traverse((object) => (object as THREE.Mesh).geometry?.dispose());
        halo?.traverse((object) => (object as THREE.Mesh).geometry?.dispose());
        glow?.traverse((object) => (object as THREE.Mesh).geometry?.dispose());
        nodeTexture.dispose();
        atomTexture.dispose();
    });

    it('batches B-aurora spheres into colored shader instances instead of per-node meshes', () => {
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
