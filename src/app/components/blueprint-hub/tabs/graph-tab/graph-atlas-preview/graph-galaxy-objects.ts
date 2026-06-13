import * as THREE from 'three';

import type { GalaxyRenderSettings } from './graph-galaxy-engine';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

export type GalaxyNodeObject = THREE.Sprite | THREE.Mesh;
export type GalaxyNodeMaterial = THREE.SpriteMaterial | THREE.MeshBasicMaterial | THREE.MeshPhysicalMaterial;

export const SPHERE_NODE_RENDER_SCALE = 0.45;

export function galaxyNodeShapeScale(
    shape: GalaxyRenderSettings['nodeShape'],
    state: { active: boolean; hovered: boolean; neighbor: boolean; dimmed: boolean; productAtom: boolean },
): number {
    const { active, hovered, neighbor, dimmed, productAtom } = state;
    if (shape === 'atom') {
        return (hovered || active ? 2.38 : neighbor ? 1.84 : dimmed ? 1.15 : 1.6)
            * (productAtom ? 0.93 : 1);
    }
    if (shape === 'sphere') {
        return (hovered || active ? 0.89 : neighbor ? 0.72 : dimmed ? 0.52 : 0.6)
            * SPHERE_NODE_RENDER_SCALE;
    }
    return hovered || active ? 2.65 : neighbor ? 2.02 : dimmed ? 1.34 : 1.72;
}

export function galaxyNodePickShapeBoost(shape: GalaxyRenderSettings['nodeShape']): number {
    return shape === 'sphere' ? 2 : shape === 'atom' ? 1 : 2;
}

export function buildGalaxyNodes(scene: GalaxySceneV2, settings: GalaxyRenderSettings, nodeTexture: THREE.Texture, atomTexture: THREE.Texture): THREE.Group | null {
    if (!scene.ids.length) return null;
    const group = new THREE.Group();
    const productAtom = settings.nodeShape === 'atom' && scene.layoutMode === 'productManifold';
    for (let index = 0; index < scene.ids.length; index++) {
        const glassSphere = settings.nodeShape === 'sphere' && settings.sphereSurface === 'glass';
        const material: GalaxyNodeMaterial = settings.nodeShape === 'sphere'
            ? glassSphere ? new THREE.MeshPhysicalMaterial({
                color: 0xffffff,
                emissive: 0x101018,
                emissiveIntensity: 0.22,
                transparent: true,
                opacity: 0.76,
                transmission: 0.2,
                thickness: 0.72,
                ior: 1.46,
                roughness: 0.08,
                metalness: 0,
                clearcoat: 1,
                clearcoatRoughness: 0.06,
                depthWrite: false,
                depthTest: true,
                toneMapped: false,
            }) : new THREE.MeshBasicMaterial({
                color: 0xffffff,
                transparent: true,
                opacity: 0.92,
                depthWrite: false,
                depthTest: true,
                toneMapped: false,
            })
            : new THREE.SpriteMaterial({
                map: settings.nodeShape === 'atom' ? atomTexture : nodeTexture,
                color: 0xffffff,
                transparent: true,
                opacity: productAtom ? 0.98 : 0.96,
                alphaTest: productAtom ? 0.055 : 0,
                depthWrite: false,
                depthTest: true,
                blending: THREE.NormalBlending,
                toneMapped: false,
            });
        const object: GalaxyNodeObject = settings.nodeShape === 'sphere'
            ? new THREE.Mesh(new THREE.SphereGeometry(1, 16, 10), material as THREE.MeshBasicMaterial | THREE.MeshPhysicalMaterial)
            : new THREE.Sprite(material as THREE.SpriteMaterial);
        object.userData['index'] = index;
        group.add(object);
    }
    return group;
}

export function buildGalaxyGlows(scene: GalaxySceneV2, haloTexture: THREE.Texture): THREE.Group | null {
    if (!scene.ids.length) return null;
    const group = new THREE.Group();
    for (let index = 0; index < scene.ids.length; index++) {
        const material = new THREE.SpriteMaterial({
            map: haloTexture,
            color: 0xffffff,
            transparent: true,
            opacity: 0.38,
            depthWrite: false,
            depthTest: false,
            blending: THREE.NormalBlending,
            toneMapped: false,
        });
        const sprite = new THREE.Sprite(material);
        sprite.userData['index'] = index;
        group.add(sprite);
    }
    return group;
}
