import * as THREE from 'three/webgpu';
import {
    Fn,
    atomicMax,
    floatBitsToUint,
    instanceIndex,
    storage,
    uint,
} from 'three/tsl';

import type { GalaxyRendererV3ResidentPages } from './galaxy-renderer-v3-contract';

const MINIMUM_SCENE_RADIUS_SQUARED_BITS = 0x3f80_0000;
const SCENE_RADIUS_READBACK_BYTES = Uint32Array.BYTES_PER_ELEMENT;

export interface GalaxyRendererV3SceneReduction {
    radius: number;
    elapsedMs: number;
    readbackBytes: number;
}

/** Owns the browser-GPU representation shared by V3 compute and draw stages. */
export class GalaxyRendererV3GpuPages {
    readonly capacity: number;
    readonly positionsAttribute: THREE.StorageBufferAttribute;
    readonly radiiAttribute: THREE.StorageBufferAttribute;
    readonly positions: ReturnType<typeof vec4Storage>;
    readonly radii: ReturnType<typeof floatStorage>;

    private readonly sceneRadiusBitsAttribute: THREE.StorageBufferAttribute;
    private readonly sceneRadiusBits: ReturnType<typeof uintStorage>;
    private readonly sceneRadiusReadback = new THREE.ReadbackBuffer(SCENE_RADIUS_READBACK_BYTES);
    private readonly positionWords: Float32Array;
    private readonly radiusWords: Float32Array;
    private readonly sceneRadiusWords = new Uint32Array([MINIMUM_SCENE_RADIUS_SQUARED_BITS]);
    private nodeCount = 0;

    constructor(nodeCount: number, pages: GalaxyRendererV3ResidentPages) {
        this.capacity = galaxyRendererV3GpuCapacity(nodeCount);
        // WebGPU storage rows are 16-byte aligned. Owning vec4 rows explicitly
        // avoids Three.js' implicit vec3-to-vec4 repack on every update.
        this.positionWords = new Float32Array(this.capacity * 4);
        this.radiusWords = new Float32Array(this.capacity);
        this.positionsAttribute = new THREE.StorageBufferAttribute(this.positionWords, 4);
        this.positionsAttribute.name = 'galaxy-v3-positions';
        this.radiiAttribute = new THREE.StorageBufferAttribute(this.radiusWords, 1);
        this.radiiAttribute.name = 'galaxy-v3-radii';
        this.positions = vec4Storage(this.positionsAttribute, this.capacity).toReadOnly();
        this.radii = floatStorage(this.radiiAttribute, this.capacity).toReadOnly();
        this.sceneRadiusBitsAttribute = new THREE.StorageBufferAttribute(this.sceneRadiusWords, 1);
        this.sceneRadiusBitsAttribute.name = 'galaxy-v3-scene-radius-bits';
        this.sceneRadiusReadback.name = 'galaxy-v3-scene-radius';
        this.sceneRadiusBits = uintStorage(this.sceneRadiusBitsAttribute, 1).toAtomic();
        this.update(nodeCount, pages);
    }

    private update(nodeCount: number, pages: GalaxyRendererV3ResidentPages): void {
        this.nodeCount = nodeCount;
        writePositions(this.positionWords, pages.positions3d, nodeCount);
        this.radiusWords.set(pages.radii.subarray(0, nodeCount));
        this.sceneRadiusWords[0] = MINIMUM_SCENE_RADIUS_SQUARED_BITS;
        this.positionsAttribute.needsUpdate = true;
        this.radiiAttribute.needsUpdate = true;
        this.sceneRadiusBitsAttribute.needsUpdate = true;
    }

    nodePositionNode() {
        return this.positions.element(instanceIndex).xyz;
    }

    nodeSizeNode() {
        return this.radii.element(instanceIndex).mul(1.65).clamp(1.5, 18);
    }

    updatePositions(positions3d: Float32Array): void {
        writePositions(this.positionWords, positions3d, this.nodeCount);
        this.positionsAttribute.needsUpdate = true;
    }

    async reduceSceneRadius(renderer: THREE.WebGPURenderer): Promise<GalaxyRendererV3SceneReduction> {
        if (!this.nodeCount) return { radius: 1, elapsedMs: 0, readbackBytes: 0 };
        const compute = Fn(() => {
            const position = this.positions.element(instanceIndex).xyz;
            atomicMax(
                this.sceneRadiusBits.element(uint(0)),
                floatBitsToUint(position.dot(position)),
            );
        })().compute(this.nodeCount, [256]);
        const started = performance.now();
        await renderer.computeAsync(compute);
        const readback = await renderer.getArrayBufferAsync(
            this.sceneRadiusBitsAttribute,
            this.sceneRadiusReadback,
            0,
            SCENE_RADIUS_READBACK_BYTES,
        );
        const radius = sceneRadiusFromSquaredBits(new Uint32Array(readback.buffer!)[0]);
        readback.release();
        if (!Number.isFinite(radius)) throw new Error('Galaxy Renderer V3 scene-radius reduction produced a non-finite value.');
        return {
            radius,
            elapsedMs: performance.now() - started,
            readbackBytes: SCENE_RADIUS_READBACK_BYTES,
        };
    }

    dispose(): void {
        this.positionsAttribute.dispose();
        this.radiiAttribute.dispose();
        this.sceneRadiusBitsAttribute.dispose();
        this.sceneRadiusReadback.dispose();
    }
}

export function sceneRadiusFromSquaredBits(bits: number): number {
    const words = new Uint32Array([bits >>> 0]);
    const squared = new Float32Array(words.buffer)[0];
    return Math.sqrt(squared);
}

export function galaxyRendererV3GpuCapacity(nodeCount: number): number {
    let capacity = 1;
    while (capacity < nodeCount) capacity *= 2;
    return capacity;
}

function writePositions(target: Float32Array, source: Float32Array, nodeCount: number): void {
    for (let index = 0; index < nodeCount; index++) {
        const sourceOffset = index * 3;
        const targetOffset = index * 4;
        target[targetOffset] = source[sourceOffset];
        target[targetOffset + 1] = source[sourceOffset + 1];
        target[targetOffset + 2] = source[sourceOffset + 2];
    }
}

function vec4Storage(attribute: THREE.StorageBufferAttribute, count: number) {
    return storage(attribute, 'vec4', count);
}

function floatStorage(attribute: THREE.StorageBufferAttribute, count: number) {
    return storage(attribute, 'float', count);
}

function uintStorage(attribute: THREE.StorageBufferAttribute, count: number) {
    return storage(attribute, 'uint', count);
}
