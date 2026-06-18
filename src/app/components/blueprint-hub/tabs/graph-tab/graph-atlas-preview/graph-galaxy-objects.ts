import * as THREE from 'three';

import type { GalaxyRenderSettings } from './graph-galaxy-engine';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

export type GalaxyNodeObject = THREE.Sprite | THREE.Mesh;
export type GalaxyNodeMaterial = THREE.SpriteMaterial | THREE.MeshBasicMaterial | THREE.MeshPhysicalMaterial;
export type GalaxyGlassNodeState = 'dimmed' | 'normal' | 'neighbor' | 'active';

export interface GalaxyGlassNodeBatch {
    meshes: readonly THREE.InstancedMesh[];
}

export interface GalaxyGlowBatch {
    points: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;
    positions: Float32Array;
    colors: Float32Array;
    sizes: Float32Array;
    alphas: Float32Array;
}

export const SPHERE_NODE_RENDER_SCALE = 0.45;

const GLASS_NODE_STATES: readonly { state: GalaxyGlassNodeState; opacity: number; rimStrength: number; innerStrength: number; sheen: number }[] = [
    { state: 'dimmed', opacity: 0.5, rimStrength: 0.66, innerStrength: 0.5, sheen: 0.012 },
    { state: 'normal', opacity: 0.78, rimStrength: 0.86, innerStrength: 0.78, sheen: 0.024 },
    { state: 'neighbor', opacity: 0.84, rimStrength: 0.94, innerStrength: 0.84, sheen: 0.032 },
    { state: 'active', opacity: 0.9, rimStrength: 1.02, innerStrength: 0.92, sheen: 0.04 },
];

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

export function galaxyGlassNodeStateIndex(active: boolean, hovered: boolean, neighbor: boolean, dimmed: boolean): number {
    if (dimmed) return 0;
    if (hovered || active) return 3;
    return neighbor ? 2 : 1;
}

export function galaxyGlassNodeBatch(group: THREE.Group | null): GalaxyGlassNodeBatch | null {
    return group?.userData['glassNodeBatch'] as GalaxyGlassNodeBatch | undefined || null;
}

export function galaxyGlowBatch(group: THREE.Group | null): GalaxyGlowBatch | null {
    return group?.userData['glowBatch'] as GalaxyGlowBatch | undefined || null;
}

export function buildGalaxyNodes(scene: GalaxySceneV2, settings: GalaxyRenderSettings, nodeTexture: THREE.Texture, atomTexture: THREE.Texture): THREE.Group | null {
    if (!scene.ids.length) return null;
    if (settings.nodeShape === 'sphere' && settings.sphereSurface === 'glass') {
        return buildGlassSphereNodes(scene);
    }
    const group = new THREE.Group();
    const productAtom = settings.nodeShape === 'atom' && scene.layoutMode === 'productManifold';
    for (let index = 0; index < scene.ids.length; index++) {
        const material: GalaxyNodeMaterial = settings.nodeShape === 'sphere'
            ? new THREE.MeshBasicMaterial({
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

function buildGlassSphereNodes(scene: GalaxySceneV2): THREE.Group {
    const group = new THREE.Group();
    const hidden = new THREE.Matrix4().makeScale(0, 0, 0);
    const batch: GalaxyGlassNodeBatch = {
        meshes: GLASS_NODE_STATES.map((state, stateIndex) => {
            const geometry = new THREE.SphereGeometry(1, 16, 10);
            const material = glassSphereMaterial(state);
            const mesh = new THREE.InstancedMesh(geometry, material, scene.ids.length);
            mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            mesh.instanceColor = glassInstanceColors(scene.ids.length);
            mesh.frustumCulled = false;
            mesh.renderOrder = 8 + stateIndex;
            mesh.userData['glassNodeState'] = state.state;
            for (let index = 0; index < scene.ids.length; index++) mesh.setMatrixAt(index, hidden);
            group.add(mesh);
            return mesh;
        }),
    };
    group.userData['glassNodeBatch'] = batch;
    return group;
}

function glassInstanceColors(count: number): THREE.InstancedBufferAttribute {
    const colors = new Float32Array(count * 3);
    colors.fill(1);
    return new THREE.InstancedBufferAttribute(colors, 3).setUsage(THREE.DynamicDrawUsage);
}

function glassSphereMaterial(state: (typeof GLASS_NODE_STATES)[number]): THREE.ShaderMaterial {
    const material = new THREE.ShaderMaterial({
        name: 'BGlassInstancedMarble',
        uniforms: {
            opacity: { value: state.opacity },
            rimStrength: { value: state.rimStrength },
            innerStrength: { value: state.innerStrength },
            sheen: { value: state.sheen },
        },
        vertexShader: `
            varying vec3 vGlassColor;
            varying vec3 vGlassNormal;
            varying vec3 vGlassView;
            varying vec3 vGlassLocal;

            void main() {
                vec4 instancedPosition = vec4(position, 1.0);
                vec3 instancedNormal = normal;

                #ifdef USE_INSTANCING
                    instancedPosition = instanceMatrix * instancedPosition;
                    instancedNormal = mat3(instanceMatrix) * instancedNormal;
                #endif

                vec4 worldPosition = modelMatrix * instancedPosition;
                vGlassNormal = normalize(mat3(modelMatrix) * instancedNormal);
                vGlassView = normalize(cameraPosition - worldPosition.xyz);
                vGlassLocal = position;

                #ifdef USE_INSTANCING_COLOR
                    vGlassColor = instanceColor;
                #else
                    vGlassColor = vec3(0.42, 1.0, 0.92);
                #endif

                gl_Position = projectionMatrix * viewMatrix * worldPosition;
            }
        `,
        fragmentShader: `
            uniform float opacity;
            uniform float rimStrength;
            uniform float innerStrength;
            uniform float sheen;
            varying vec3 vGlassColor;
            varying vec3 vGlassNormal;
            varying vec3 vGlassView;
            varying vec3 vGlassLocal;

            void main() {
                vec3 normal = normalize(vGlassNormal);
                vec3 view = normalize(vGlassView);
                vec3 source = max(vGlassColor, vec3(0.025));
                float maxChannel = max(max(source.r, source.g), source.b);
                float lift = 0.36 / max(maxChannel, 0.001);
                float lowChroma = 1.0 - smoothstep(0.0, 0.36, maxChannel);
                source = mix(source, min(source * lift, vec3(1.0)), lowChroma * 0.45);

                float rim = pow(1.0 - clamp(abs(dot(normal, view)), 0.0, 1.0), 2.65);
                rim = smoothstep(0.12, 0.88, rim);
                float latitude = 0.5 + 0.5 * sin(vGlassLocal.y * 7.4 + vGlassLocal.x * 2.8 + vGlassLocal.z * 1.9);
                float vein = 0.5 + 0.5 * sin(vGlassLocal.x * 12.0 + vGlassLocal.y * 5.2 - vGlassLocal.z * 3.4);
                float cap = smoothstep(-0.9, 0.92, vGlassLocal.y);
                vec3 depth = mix(vec3(0.018, 0.032, 0.044), source * 0.78, 0.56 + cap * 0.18);
                vec3 core = source * (0.76 + latitude * 0.34 - vein * 0.055) + vec3(0.024, 0.032, 0.04);
                vec3 rimColor = mix(vec3(0.44, 0.96, 0.9), min(source + vec3(0.16), vec3(1.0)), 0.62);
                vec3 lightDir = normalize(vec3(-0.32, 0.46, 0.82));
                vec3 highlight = vec3(1.0, 0.94, 0.78) * pow(max(dot(normal, lightDir), 0.0), 22.0) * 0.32;
                vec3 hue = mix(depth, core, innerStrength);
                hue = mix(hue, rimColor, rim * rimStrength);
                hue += highlight + source * sheen * (0.08 + rim * 0.14);
                float alpha = opacity * (0.3 + rim * 0.56 + latitude * 0.035);
                if (alpha <= 0.008) discard;
                gl_FragColor = vec4(hue, alpha);
            }
        `,
        transparent: true,
        depthWrite: false,
        depthTest: true,
        blending: THREE.NormalBlending,
        side: THREE.FrontSide,
        toneMapped: false,
    });
    material.userData['glassSurface'] = 'b-glass-marble';
    material.userData['glassState'] = state.state;
    return material;
}

export function buildGalaxyGlows(scene: GalaxySceneV2, haloTexture: THREE.Texture): THREE.Group | null {
    if (!scene.ids.length) return null;
    const group = new THREE.Group();
    const count = scene.ids.length;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const alphas = new Float32Array(count);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute('aAlpha', new THREE.BufferAttribute(alphas, 1).setUsage(THREE.DynamicDrawUsage));
    const material = new THREE.ShaderMaterial({
        name: 'GalaxyGlowBatch',
        uniforms: {
            haloTexture: { value: haloTexture },
            viewportHeight: { value: 800 },
        },
        vertexShader: `
            attribute vec3 color;
            attribute float aSize;
            attribute float aAlpha;
            varying vec3 vColor;
            varying float vAlpha;
            uniform float viewportHeight;

            void main() {
                vColor = color;
                vAlpha = aAlpha;
                vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
                float perspectiveScale = viewportHeight * projectionMatrix[1][1] * 0.5 / max(0.01, -mvPosition.z);
                gl_PointSize = clamp(aSize * perspectiveScale, 0.0, 96.0);
                gl_Position = projectionMatrix * mvPosition;
            }
        `,
        fragmentShader: `
            uniform sampler2D haloTexture;
            varying vec3 vColor;
            varying float vAlpha;

            void main() {
                vec4 halo = texture2D(haloTexture, gl_PointCoord);
                gl_FragColor = vec4(vColor, vAlpha) * halo;
                if (gl_FragColor.a <= 0.002) discard;
            }
        `,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.NormalBlending,
        toneMapped: false,
    });
    const points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    const batch: GalaxyGlowBatch = { points, positions, colors, sizes, alphas };
    group.userData['glowBatch'] = batch;
    group.add(points);
    return group;
}
