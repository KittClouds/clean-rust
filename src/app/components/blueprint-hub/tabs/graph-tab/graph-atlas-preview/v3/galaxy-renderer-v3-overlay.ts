import * as THREE from 'three/webgpu';
import { instancedBufferAttribute, shapeCircle } from 'three/tsl';

import type { GalaxyRendererV3ResidentPages } from './galaxy-renderer-v3-contract';

/** Persistent prepared overlay buffers; hover only mutates their active prefix. */
export class GalaxyRendererV3Overlay {
    readonly capacity: number;
    readonly object: THREE.Sprite;

    private readonly positions: Float32Array;
    private readonly sizes: Float32Array;
    private readonly colors: Float32Array;
    private readonly positionAttribute: THREE.InstancedBufferAttribute;
    private readonly sizeAttribute: THREE.InstancedBufferAttribute;
    private readonly colorAttribute: THREE.InstancedBufferAttribute;

    constructor(nodeCapacity: number) {
        this.capacity = galaxyRendererV3OverlayCapacity(nodeCapacity);
        this.positions = new Float32Array(this.capacity * 3);
        this.sizes = new Float32Array(this.capacity);
        this.colors = new Float32Array(this.capacity * 3);
        for (let index = 0; index < this.capacity; index++) {
            const offset = index * 3;
            this.colors[offset] = 0.78;
            this.colors[offset + 1] = 1;
            this.colors[offset + 2] = 0.96;
        }
        this.positionAttribute = new THREE.InstancedBufferAttribute(this.positions, 3);
        this.sizeAttribute = new THREE.InstancedBufferAttribute(this.sizes, 1);
        this.colorAttribute = new THREE.InstancedBufferAttribute(this.colors, 3);
        const material = new THREE.PointsNodeMaterial({
            positionNode: instancedBufferAttribute(this.positionAttribute, 'vec3'),
            colorNode: instancedBufferAttribute(this.colorAttribute, 'vec3'),
            opacityNode: shapeCircle(),
            sizeNode: instancedBufferAttribute(this.sizeAttribute, 'float'),
            sizeAttenuation: false,
            transparent: true,
            depthWrite: false,
            alphaToCoverage: true,
        });
        this.object = new THREE.Sprite(material);
        this.object.count = 0;
        this.object.renderOrder = 8;
    }

    canFit(count: number): boolean {
        return count <= this.capacity;
    }

    update(pages: GalaxyRendererV3ResidentPages, indexes: ReadonlySet<number>): void {
        if (!this.canFit(indexes.size)) {
            throw new Error(`Galaxy Renderer V3 overlay capacity ${this.capacity} cannot fit ${indexes.size} identities.`);
        }
        let output = 0;
        for (const source of indexes) {
            if (source < 0 || source >= pages.nodeCount) {
                throw new Error(`Galaxy Renderer V3 overlay index is out of bounds: ${source}.`);
            }
            const sourceOffset = source * 3;
            const targetOffset = output * 3;
            this.positions[targetOffset] = pages.positions3d[sourceOffset];
            this.positions[targetOffset + 1] = pages.positions3d[sourceOffset + 1];
            this.positions[targetOffset + 2] = pages.positions3d[sourceOffset + 2];
            this.sizes[output] = Math.max(8, pages.radii[source] * 4.2);
            output += 1;
        }
        this.object.count = indexes.size;
        markPrefix(this.positionAttribute, indexes.size * 3);
        markPrefix(this.sizeAttribute, indexes.size);
    }

    clear(): void {
        this.object.count = 0;
    }

    dispose(): void {
        this.object.material.dispose();
    }
}

export function galaxyRendererV3OverlayCapacity(nodeCount: number): number {
    let capacity = 1;
    while (capacity < Math.max(1, nodeCount)) capacity *= 2;
    return capacity;
}

function markPrefix(attribute: THREE.InstancedBufferAttribute, componentCount: number): void {
    attribute.clearUpdateRanges();
    if (componentCount) attribute.addUpdateRange(0, componentCount);
    attribute.needsUpdate = true;
}
