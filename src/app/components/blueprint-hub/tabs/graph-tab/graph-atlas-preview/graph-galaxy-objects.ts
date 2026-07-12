import * as THREE from 'three';

import type { GalaxyRenderSettings, GalaxySphereSurfaceMode } from './graph-galaxy-engine';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

export type GalaxyNodeObject = THREE.Sprite | THREE.Mesh;
export type GalaxyNodeMaterial = THREE.SpriteMaterial | THREE.MeshBasicMaterial | THREE.MeshPhysicalMaterial;
export type GalaxySphereNodeState = 'dimmed' | 'normal' | 'neighbor' | 'active';

export interface GalaxySphereNodeBatch {
    meshes: readonly THREE.InstancedMesh[];
}

export interface GalaxyGlowBatch {
    points: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;
    positions: Float32Array;
    colors: Float32Array;
    sizes: Float32Array;
    alphas: Float32Array;
}

export interface GalaxyBillboardNodeBatch {
    points: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;
    positions: Float32Array;
    colors: Float32Array;
    sizes: Float32Array;
    alphas: Float32Array;
}

export const SPHERE_NODE_RENDER_SCALE = 0.45;

const SPHERE_NODE_STATES: readonly { state: GalaxySphereNodeState; opacity: number; rimStrength: number; innerStrength: number; sheen: number }[] = [
    { state: 'dimmed', opacity: 0.5, rimStrength: 0.66, innerStrength: 0.5, sheen: 0.012 },
    { state: 'normal', opacity: 0.78, rimStrength: 0.86, innerStrength: 0.78, sheen: 0.024 },
    { state: 'neighbor', opacity: 0.84, rimStrength: 0.94, innerStrength: 0.84, sheen: 0.032 },
    { state: 'active', opacity: 0.9, rimStrength: 1.02, innerStrength: 0.92, sheen: 0.04 },
];

export function galaxyNodeShapeScale(
    shape: GalaxyRenderSettings['nodeShape'],
    state: { active: boolean; hovered: boolean; neighbor: boolean; dimmed: boolean; transitAtom: boolean },
): number {
    const { active, hovered, neighbor, dimmed, transitAtom } = state;
    if (shape === 'atom') {
        return (hovered || active ? 2.38 : neighbor ? 1.84 : dimmed ? 1.15 : 1.6)
            * (transitAtom ? 0.93 : 1);
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

export function galaxySphereNodeStateIndex(active: boolean, hovered: boolean, neighbor: boolean, dimmed: boolean): number {
    if (dimmed) return 0;
    if (hovered || active) return 3;
    return neighbor ? 2 : 1;
}

export function galaxySphereNodeBatch(group: THREE.Group | null): GalaxySphereNodeBatch | null {
    return group?.userData['sphereNodeBatch'] as GalaxySphereNodeBatch | undefined || null;
}

export function galaxyGlowBatch(group: THREE.Group | null): GalaxyGlowBatch | null {
    return group?.userData['glowBatch'] as GalaxyGlowBatch | undefined || null;
}

export function galaxyBillboardNodeBatch(group: THREE.Group | null): GalaxyBillboardNodeBatch | null {
    return group?.userData['billboardNodeBatch'] as GalaxyBillboardNodeBatch | undefined || null;
}

export function buildGalaxyNodes(scene: GalaxySceneV2, settings: GalaxyRenderSettings, nodeTexture: THREE.Texture, atomTexture: THREE.Texture): THREE.Group | null {
    if (!scene.ids.length) return null;
    const sphereSurface = settings.sphereSurface || 'solid';
    if (settings.nodeShape === 'sphere') {
        return buildStyledSphereNodes(scene, sphereSurface);
    }
    return buildBillboardNodes(scene, settings.nodeShape === 'atom' ? atomTexture : nodeTexture, settings.nodeShape === 'atom');
}

function buildBillboardNodes(scene: GalaxySceneV2, texture: THREE.Texture, atom: boolean): THREE.Group {
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
        name: atom ? 'GalaxyAtomBatch' : 'GalaxyHaloNodeBatch',
        uniforms: {
            nodeTexture: { value: texture },
            viewportHeight: { value: 800 },
        },
        vertexShader: `
            attribute float aSize;
            attribute float aAlpha;
            varying vec3 vColor;
            varying float vAlpha;
            uniform float viewportHeight;
            void main() {
                vColor = color;
                vAlpha = aAlpha;
                vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
                float perspectiveScale = projectionMatrix[1][1] * 0.5 / max(0.01, -mvPosition.z);
                gl_PointSize = clamp(aSize * perspectiveScale * viewportHeight, 0.0, 192.0);
                gl_Position = projectionMatrix * mvPosition;
            }
        `,
        fragmentShader: `
            uniform sampler2D nodeTexture;
            varying vec3 vColor;
            varying float vAlpha;
            void main() {
                vec4 texel = texture2D(nodeTexture, gl_PointCoord);
                float alpha = texel.a * vAlpha;
                if (alpha <= ${atom ? '0.055' : '0.002'}) discard;
                gl_FragColor = vec4(texel.rgb * vColor, alpha);
            }
        `,
        transparent: true,
        depthWrite: false,
        depthTest: true,
        blending: THREE.NormalBlending,
        toneMapped: false,
        vertexColors: true,
    });
    const points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    const batch: GalaxyBillboardNodeBatch = { points, positions, colors, sizes, alphas };
    group.userData['billboardNodeBatch'] = batch;
    group.add(points);
    return group;
}

function buildStyledSphereNodes(scene: GalaxySceneV2, surface: GalaxySphereSurfaceMode): THREE.Group {
    const group = new THREE.Group();
    const hidden = new THREE.Matrix4().makeScale(0, 0, 0);
    const batch: GalaxySphereNodeBatch = {
        meshes: SPHERE_NODE_STATES.map((state, stateIndex) => {
            const geometry = new THREE.SphereGeometry(1, 16, 10);
            const material = sphereSurfaceMaterial(surface, state);
            const mesh = new THREE.InstancedMesh(geometry, material, scene.ids.length);
            mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            mesh.instanceColor = glassInstanceColors(scene.ids.length);
            mesh.frustumCulled = false;
            mesh.renderOrder = 8 + stateIndex;
            mesh.userData['sphereNodeState'] = state.state;
            for (let index = 0; index < scene.ids.length; index++) mesh.setMatrixAt(index, hidden);
            group.add(mesh);
            return mesh;
        }),
    };
    group.userData['sphereNodeBatch'] = batch;
    group.userData['sphereSurface'] = surface;
    return group;
}

function glassInstanceColors(count: number): THREE.InstancedBufferAttribute {
    const colors = new Float32Array(count * 3);
    colors.fill(1);
    return new THREE.InstancedBufferAttribute(colors, 3).setUsage(THREE.DynamicDrawUsage);
}

function sphereSurfaceMaterial(
    surface: GalaxySphereSurfaceMode,
    state: (typeof SPHERE_NODE_STATES)[number],
): THREE.Material {
    if (surface === 'solid') return solidSphereMaterial(state.state);
    if (surface === 'spellglass') return spellglassSphereMaterial(state);
    if (surface === 'obsidian') return obsidianSphereMaterial(state);
    if (surface === 'starcore') return starcoreSphereMaterial(state);
    return glassSphereMaterial(state);
}

function solidSphereMaterial(state: GalaxySphereNodeState): THREE.MeshBasicMaterial {
    const opacity = state === 'dimmed' ? 0.18 : state === 'neighbor' ? 0.82 : state === 'active' ? 1 : 0.94;
    const material = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity,
        depthWrite: false,
        depthTest: true,
        toneMapped: false,
    });
    material.userData['sphereSurface'] = 'solid';
    material.userData['sphereState'] = state;
    return material;
}

function glassSphereMaterial(state: (typeof SPHERE_NODE_STATES)[number]): THREE.ShaderMaterial {
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
    material.userData['sphereSurface'] = 'glass';
    material.userData['glassState'] = state.state;
    material.userData['sphereState'] = state.state;
    return material;
}

const STYLED_SPHERE_VERTEX_SHADER = `
    varying vec3 vSphereColor;
    varying vec3 vSphereNormal;
    varying vec3 vSphereView;
    varying vec3 vSphereLocal;

    void main() {
        vec4 instancedPosition = vec4(position, 1.0);
        vec3 instancedNormal = normal;

        #ifdef USE_INSTANCING
            instancedPosition = instanceMatrix * instancedPosition;
            instancedNormal = mat3(instanceMatrix) * instancedNormal;
        #endif

        vec4 worldPosition = modelMatrix * instancedPosition;
        vSphereNormal = normalize(mat3(modelMatrix) * instancedNormal);
        vSphereView = normalize(cameraPosition - worldPosition.xyz);
        vSphereLocal = position;

        #ifdef USE_INSTANCING_COLOR
            vSphereColor = instanceColor;
        #else
            vSphereColor = vec3(0.42, 1.0, 0.92);
        #endif

        gl_Position = projectionMatrix * viewMatrix * worldPosition;
    }
`;

function spellglassSphereMaterial(state: (typeof SPHERE_NODE_STATES)[number]): THREE.ShaderMaterial {
    return styledSphereMaterial('CSpellglassMarble', 'spellglass', state, `
        uniform float opacity;
        uniform float rimStrength;
        uniform float innerStrength;
        uniform float sheen;
        varying vec3 vSphereColor;
        varying vec3 vSphereNormal;
        varying vec3 vSphereView;
        varying vec3 vSphereLocal;

        void main() {
            vec3 normal = normalize(vSphereNormal);
            vec3 view = normalize(vSphereView);
            vec3 source = max(vSphereColor, vec3(0.06));
            float fresnel = pow(1.0 - clamp(abs(dot(normal, view)), 0.0, 1.0), 2.2);
            float radial = length(vSphereLocal.xz);
            // Etched meridian + spiral facets. Powers lowered from ^12/^16 to ^5/^6
            // so the etch web is actually visible instead of a sub-pixel filament.
            float shellBand = pow(1.0 - abs(sin((radial * 6.0 + vSphereLocal.y * 1.6) * 3.14159265)), 5.0);
            float spiral = pow(1.0 - abs(sin(atan(vSphereLocal.z, vSphereLocal.x) * 2.0 + vSphereLocal.y * 6.8)), 6.0);
            float facet = clamp(shellBand * 0.62 + spiral * 0.48, 0.0, 1.0);
            float phase = vSphereLocal.x * 4.2 - vSphereLocal.y * 5.6 + vSphereLocal.z * 3.4;
            vec3 prism = mix(source, source.gbr, 0.42 + sin(phase) * 0.26);
            // Luminous tinted body — no dark center. Source lifted toward ~0.70 so
            // the marble reads at a glance instead of dissolving into the nebula.
            vec3 body = source * (0.66 + innerStrength * 0.22);
            vec3 hue = body + prism * facet * (0.50 + innerStrength * 0.50);
            hue += mix(source.brg, vec3(0.74, 0.95, 1.0), 0.30) * fresnel * rimStrength * 0.70;
            hue += vec3(1.0, 0.82, 0.56) * pow(max(dot(normal, normalize(vec3(-0.4, 0.5, 0.76))), 0.0), 26.0) * (0.20 + sheen);
            // Alpha floor raised so the orb stays visible; fresnel adds a brighter edge.
            float alpha = opacity * (0.62 + fresnel * 0.30 + facet * 0.08);
            if (alpha <= 0.008) discard;
            gl_FragColor = vec4(hue, alpha);
        }
    `);
}

function obsidianSphereMaterial(state: (typeof SPHERE_NODE_STATES)[number]): THREE.ShaderMaterial {
    return styledSphereMaterial('DObsidianCrescent', 'obsidian', state, `
        uniform float opacity;
        uniform float rimStrength;
        uniform float innerStrength;
        uniform float sheen;
        varying vec3 vSphereColor;
        varying vec3 vSphereNormal;
        varying vec3 vSphereView;
        varying vec3 vSphereLocal;

        void main() {
            vec3 normal = normalize(vSphereNormal);
            vec3 view = normalize(vSphereView);
            vec3 source = max(vSphereColor, vec3(0.028));
            vec3 lightDir = normalize(vec3(-0.58, 0.42, 0.7));
            float facing = clamp(dot(normal, lightDir), -1.0, 1.0);
            float crescent = smoothstep(-0.12, 0.58, facing) * (1.0 - smoothstep(0.64, 0.96, facing));
            float rim = pow(1.0 - clamp(abs(dot(normal, view)), 0.0, 1.0), 3.1);
            float mineral = 0.5 + 0.5 * sin(dot(vSphereLocal, vec3(17.0, 11.0, 23.0)) + vSphereLocal.y * 9.0);
            vec3 blackGlass = vec3(0.004, 0.007, 0.013) + source * (0.045 + mineral * 0.035);
            vec3 colorCrescent = mix(source * 1.18, vec3(1.0, 0.9, 0.7), 0.18) * crescent;
            vec3 hue = blackGlass + colorCrescent * (0.7 + innerStrength * 0.42);
            hue += mix(source, vec3(0.72, 0.88, 1.0), 0.42) * rim * rimStrength * 0.48;
            hue += vec3(1.0) * pow(max(facing, 0.0), 48.0) * (0.2 + sheen * 2.0);
            float alpha = opacity * (0.72 + crescent * 0.16 + rim * 0.12);
            if (alpha <= 0.008) discard;
            gl_FragColor = vec4(hue, alpha);
        }
    `);
}

function starcoreSphereMaterial(state: (typeof SPHERE_NODE_STATES)[number]): THREE.ShaderMaterial {
    return styledSphereMaterial('EStarcore', 'starcore', state, `
        uniform float opacity;
        uniform float rimStrength;
        uniform float innerStrength;
        uniform float sheen;
        varying vec3 vSphereColor;
        varying vec3 vSphereNormal;
        varying vec3 vSphereView;
        varying vec3 vSphereLocal;

        void main() {
            vec3 normal = normalize(vSphereNormal);
            vec3 view = normalize(vSphereView);
            vec3 source = max(vSphereColor, vec3(0.04));
            vec3 lightDir = normalize(vec3(-0.46, 0.58, 0.68));
            float diffuse = 0.5 + 0.5 * max(dot(normal, lightDir), 0.0);
            float facing = clamp(dot(normal, view), 0.0, 1.0);
            float rim = pow(1.0 - facing, 2.65);
            float equator = pow(1.0 - abs(vSphereLocal.y), 7.0);
            float hotCore = pow(facing, 3.2) * (0.72 + 0.28 * max(dot(normal, lightDir), 0.0));
            float hemisphere = smoothstep(-0.72, 0.78, vSphereLocal.x - vSphereLocal.z * 0.32);
            vec3 body = mix(source * 0.54, source.brg * 0.78, hemisphere * 0.38);
            body *= 0.72 + diffuse * 0.48 + innerStrength * 0.12;
            vec3 seam = mix(source * 1.28, vec3(1.0, 0.72, 0.34), 0.32) * equator * 0.68;
            vec3 core = mix(source, vec3(1.0, 0.9, 0.7), 0.36) * hotCore * (0.34 + sheen * 2.0);
            vec3 hue = body + seam + core;
            hue += mix(source.brg, vec3(0.68, 0.94, 1.0), 0.36) * rim * rimStrength * 0.52;
            float alpha = opacity * (0.84 + rim * 0.12 + equator * 0.04);
            if (alpha <= 0.008) discard;
            gl_FragColor = vec4(hue, alpha);
        }
    `);
}

function styledSphereMaterial(
    name: string,
    surface: Exclude<GalaxySphereSurfaceMode, 'solid' | 'glass'>,
    state: (typeof SPHERE_NODE_STATES)[number],
    fragmentShader: string,
    blending: THREE.Blending = THREE.NormalBlending,
): THREE.ShaderMaterial {
    const material = new THREE.ShaderMaterial({
        name,
        uniforms: {
            opacity: { value: state.opacity },
            rimStrength: { value: state.rimStrength },
            innerStrength: { value: state.innerStrength },
            sheen: { value: state.sheen },
        },
        vertexShader: STYLED_SPHERE_VERTEX_SHADER,
        fragmentShader,
        transparent: true,
        depthWrite: false,
        depthTest: true,
        blending,
        side: THREE.FrontSide,
        toneMapped: false,
    });
    material.userData['sphereSurface'] = surface;
    material.userData['sphereState'] = state.state;
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
        vertexColors: true,
    });
    const points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    const batch: GalaxyGlowBatch = { points, positions, colors, sizes, alphas };
    group.userData['glowBatch'] = batch;
    group.add(points);
    return group;
}
