import * as THREE from 'three';

import type { GraphRendererPointer } from './graph-renderer-port';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

const PICK_TARGET_SIZE = 9;
const PICK_CENTER = Math.floor(PICK_TARGET_SIZE / 2);

export class ThreeGalaxyIdPicker {
    private readonly scene = new THREE.Scene();
    private readonly target = new THREE.WebGLRenderTarget(PICK_TARGET_SIZE, PICK_TARGET_SIZE, {
        depthBuffer: true,
        stencilBuffer: false,
        type: THREE.UnsignedByteType,
        format: THREE.RGBAFormat,
        colorSpace: THREE.NoColorSpace,
        magFilter: THREE.NearestFilter,
        minFilter: THREE.NearestFilter,
    });
    private readonly pixels = new Uint8Array(PICK_TARGET_SIZE * PICK_TARGET_SIZE * 4);
    private readonly viewport = new THREE.Vector4();
    private readonly scissor = new THREE.Vector4();
    private readonly clearColor = new THREE.Color();
    private points: THREE.Points<THREE.BufferGeometry, THREE.RawShaderMaterial> | null = null;

    bind(scene: GalaxySceneV2, positions: Float32Array, glow: number): void {
        this.clearPoints();
        if (!scene.ids.length) return;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage));
        geometry.setAttribute('aRadius', new THREE.BufferAttribute(scene.radii, 1));
        const ids = new Uint32Array(scene.ids.length);
        for (let index = 0; index < ids.length; index++) ids[index] = index + 1;
        geometry.setAttribute('aPickId', new THREE.BufferAttribute(ids, 1));
        const material = new THREE.RawShaderMaterial({
            glslVersion: THREE.GLSL3,
            uniforms: {
                uGlow: { value: glow },
            },
            vertexShader: ID_PICK_VERTEX_SHADER,
            fragmentShader: ID_PICK_FRAGMENT_SHADER,
            depthTest: true,
            depthWrite: true,
            transparent: false,
            toneMapped: false,
        });
        this.points = new THREE.Points(geometry, material);
        this.points.frustumCulled = false;
        this.scene.add(this.points);
    }

    updatePositions(positions: Float32Array): void {
        if (!this.points) return;
        const current = this.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        if (current.array !== positions) {
            this.points.geometry.setAttribute(
                'position',
                new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage),
            );
        } else {
            current.needsUpdate = true;
        }
    }

    setGlow(glow: number): void {
        if (this.points) this.points.material.uniforms['uGlow'].value = glow;
    }

    pick(
        renderer: THREE.WebGLRenderer,
        camera: THREE.PerspectiveCamera | THREE.OrthographicCamera,
        pointer: GraphRendererPointer,
    ): number {
        if (!this.points || pointer.width <= 0 || pointer.height <= 0) return -1;
        const fullWidth = Math.max(1, Math.floor(pointer.width));
        const fullHeight = Math.max(1, Math.floor(pointer.height));
        const offsetX = THREE.MathUtils.clamp(
            Math.floor(pointer.x) - PICK_CENTER,
            0,
            Math.max(0, fullWidth - PICK_TARGET_SIZE),
        );
        const offsetY = THREE.MathUtils.clamp(
            Math.floor(pointer.y) - PICK_CENTER,
            0,
            Math.max(0, fullHeight - PICK_TARGET_SIZE),
        );
        const previousTarget = renderer.getRenderTarget();
        const previousScissorTest = renderer.getScissorTest();
        const previousClearAlpha = renderer.getClearAlpha();
        renderer.getViewport(this.viewport);
        renderer.getScissor(this.scissor);
        renderer.getClearColor(this.clearColor);
        camera.setViewOffset(fullWidth, fullHeight, offsetX, offsetY, PICK_TARGET_SIZE, PICK_TARGET_SIZE);
        try {
            renderer.setRenderTarget(this.target);
            renderer.setViewport(0, 0, PICK_TARGET_SIZE, PICK_TARGET_SIZE);
            renderer.setScissor(0, 0, PICK_TARGET_SIZE, PICK_TARGET_SIZE);
            renderer.setScissorTest(true);
            renderer.setClearColor(0x000000, 0);
            renderer.clear(true, true, false);
            renderer.render(this.scene, camera);
            renderer.readRenderTargetPixels(
                this.target,
                0,
                0,
                PICK_TARGET_SIZE,
                PICK_TARGET_SIZE,
                this.pixels,
            );
            return nearestDecodedId(this.pixels);
        } finally {
            camera.clearViewOffset();
            renderer.setRenderTarget(previousTarget);
            renderer.setViewport(this.viewport);
            renderer.setScissor(this.scissor);
            renderer.setScissorTest(previousScissorTest);
            renderer.setClearColor(this.clearColor, previousClearAlpha);
        }
    }

    dispose(): void {
        this.clearPoints();
        this.target.dispose();
    }

    private clearPoints(): void {
        if (!this.points) return;
        this.scene.remove(this.points);
        this.points.geometry.dispose();
        this.points.material.dispose();
        this.points = null;
    }
}

function nearestDecodedId(pixels: Uint8Array): number {
    let best = -1;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let y = 0; y < PICK_TARGET_SIZE; y++) {
        for (let x = 0; x < PICK_TARGET_SIZE; x++) {
            const offset = (x + y * PICK_TARGET_SIZE) * 4;
            const encoded = pixels[offset]
                | pixels[offset + 1] << 8
                | pixels[offset + 2] << 16
                | pixels[offset + 3] << 24;
            const unsigned = encoded >>> 0;
            if (!unsigned) continue;
            const distance = (x - PICK_CENTER) ** 2 + (y - PICK_CENTER) ** 2;
            if (distance < bestDistance) {
                bestDistance = distance;
                best = unsigned - 1;
            }
        }
    }
    return best;
}

const ID_PICK_VERTEX_SHADER = /* glsl */ `
precision highp float;
precision highp int;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform float uGlow;

in vec3 position;
in float aRadius;
in uint aPickId;

flat out uint vPickId;

void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = clamp(11.0 + aRadius * 1.9 + uGlow * 4.0, 10.0, 34.0);
    vPickId = aPickId;
}
`;

const ID_PICK_FRAGMENT_SHADER = /* glsl */ `
precision highp float;
precision highp int;

flat in uint vPickId;
out vec4 outColor;

void main() {
    vec2 centered = gl_PointCoord * 2.0 - 1.0;
    if (dot(centered, centered) > 1.0) discard;
    outColor = vec4(
        float(vPickId & 255u),
        float((vPickId >> 8u) & 255u),
        float((vPickId >> 16u) & 255u),
        float((vPickId >> 24u) & 255u)
    ) / 255.0;
}
`;
