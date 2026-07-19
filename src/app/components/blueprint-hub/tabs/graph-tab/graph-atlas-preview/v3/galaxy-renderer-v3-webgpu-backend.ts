import * as THREE from 'three/webgpu';
import {
    instanceIndex,
    instancedBufferAttribute,
    shapeCircle,
    storage,
    uint,
    vertexIndex,
} from 'three/tsl';

import type { GraphRendererMode, GraphRendererPointer } from '../graph-renderer-port';
import type { GalaxyRenderSettings } from '../graph-galaxy-engine';
import type {
    GalaxyRendererV3Backend,
    GalaxyRendererV3Generation,
    GalaxyRendererV3Metrics,
    GalaxyRendererV3ResidentPages,
} from './galaxy-renderer-v3-contract';
import { galaxyRendererV3Metrics } from './galaxy-renderer-v3-metrics';
import {
    galaxyRendererV3NodeIds,
    galaxyRendererV3PacketResidentBytes,
    galaxyRendererV3ResidentPages,
} from './galaxy-renderer-v3-packet-view';

type DisposableGalaxyObject = THREE.Object3D & {
    geometry?: THREE.BufferGeometry;
    material?: THREE.Material | THREE.Material[];
};

export class GalaxyRendererV3WebGpuBackend implements GalaxyRendererV3Backend {
    readonly metrics: GalaxyRendererV3Metrics = {
        authorityReceipt: '',
        generationId: '',
        backend: 'unavailable',
        residentNodes: 0,
        residentEdges: 0,
        gpuBytes: 0,
        installMs: 0,
        firstPixelMs: 0,
        frames: 0,
        failures: 0,
    };

    private readonly scene = new THREE.Scene();
    private readonly root = new THREE.Group();
    private readonly perspective = new THREE.PerspectiveCamera(46, 1, 0.01, 5_000);
    private readonly orthographic = new THREE.OrthographicCamera(-4, 4, 4, -4, 0.01, 5_000);
    private renderer: THREE.WebGPURenderer | null = null;
    private pages: GalaxyRendererV3ResidentPages | null = null;
    private generation: GalaxyRendererV3Generation | null = null;
    private settings!: GalaxyRenderSettings;
    private mode: GraphRendererMode = '3d';
    private nodeIds: string[] | null = null;
    private nodeIndexById: Map<string, number> | null = null;
    private nodeObject: THREE.Sprite | null = null;
    private edgeObject: THREE.LineSegments | null = null;
    private overlayObject: THREE.Sprite | null = null;
    private selectedIds: readonly string[] = [];
    private hoveredId: string | null = null;
    private fitRadius = 2;
    private viewportWidth = 1;
    private viewportHeight = 1;
    private renderInFlight = false;
    private disposed = false;

    constructor() {
        this.scene.background = new THREE.Color(0x02040a);
        this.scene.add(this.root);
        this.resetCamera();
    }

    async mount(canvas: HTMLCanvasElement): Promise<void> {
        if (this.renderer) return;
        if (!(navigator as Navigator & { gpu?: unknown }).gpu) {
            this.failClosed(new Error('Galaxy Renderer V3 requires WebGPU; legacy fallback is intentionally disabled.'));
        }
        const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, alpha: false });
        renderer.setClearColor(0x02040a, 1);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.setPixelRatio(1);
        renderer.setSize(this.viewportWidth, this.viewportHeight, false);
        await renderer.init();
        if (this.disposed) {
            renderer.dispose();
            return;
        }
        this.renderer = renderer;
        this.updateMetrics({ backend: 'webgpu' });
    }

    async openGeneration(generation: GalaxyRendererV3Generation, settings: GalaxyRenderSettings): Promise<void> {
        if (!this.renderer) throw new Error('Galaxy Renderer V3 must mount before opening a generation.');
        if (generation.generationId !== generation.packet.manifest.generationId) {
            throw new Error('Galaxy Renderer V3 generation does not match its packet.');
        }
        if (generation.authorityReceipt !== generation.packet.manifest.authorityReceipt) {
            throw new Error('Galaxy Renderer V3 authority receipt does not match its packet.');
        }
        const started = performance.now();
        this.clearResidentObjects();
        this.generation = generation;
        this.pages = galaxyRendererV3ResidentPages(generation.packet);
        this.settings = settings;
        this.nodeIds = null;
        this.nodeIndexById = null;
        this.fitRadius = sceneRadius(this.pages.positions3d);
        this.nodeObject = buildNodeSurface(this.pages);
        this.edgeObject = buildEdgeSurface(this.pages, settings);
        if (this.edgeObject) this.root.add(this.edgeObject);
        if (this.nodeObject) this.root.add(this.nodeObject);
        this.applyMode();
        this.fitToGraph();
        const installMs = performance.now() - started;
        this.updateMetrics({
            generationId: generation.generationId,
            authorityReceipt: generation.authorityReceipt,
            residentNodes: this.pages.nodeCount,
            residentEdges: this.pages.edgeCount,
            gpuBytes: galaxyRendererV3PacketResidentBytes(generation.packet),
            installMs,
        });
        const firstPixelStarted = performance.now();
        await this.renderer.renderAsync(this.scene, this.activeCamera());
        this.updateMetrics({ firstPixelMs: performance.now() - firstPixelStarted, frames: this.metrics.frames + 1 });
        this.rebuildOverlay();
    }

    setSettings(settings: GalaxyRenderSettings): void {
        this.settings = settings;
        if (!this.generation || !this.pages) return;
        const generation = this.generation;
        void this.openGeneration(generation, settings).catch((error) => this.recordFailure(toError(error)));
    }

    setMode(mode: GraphRendererMode): void {
        this.mode = mode;
        this.applyMode();
        this.render();
    }

    resize(width: number, height: number, dpr: number): void {
        this.viewportWidth = Math.max(1, width);
        this.viewportHeight = Math.max(1, height);
        const aspect = this.viewportWidth / this.viewportHeight;
        this.perspective.aspect = aspect;
        this.perspective.updateProjectionMatrix();
        const span = Math.max(1, this.fitRadius * 1.35);
        this.orthographic.left = -span * aspect;
        this.orthographic.right = span * aspect;
        this.orthographic.top = span;
        this.orthographic.bottom = -span;
        this.orthographic.updateProjectionMatrix();
        if (this.renderer) {
            this.renderer.setPixelRatio(Math.max(1, Math.min(2, dpr)));
            this.renderer.setSize(this.viewportWidth, this.viewportHeight, false);
        }
        this.render();
    }

    render(): void {
        if (!this.renderer || this.renderInFlight || this.disposed) return;
        this.renderInFlight = true;
        void this.renderer.renderAsync(this.scene, this.activeCamera())
            .then(() => this.updateMetrics({ frames: this.metrics.frames + 1 }))
            .catch((error) => this.recordFailure(toError(error)))
            .finally(() => { this.renderInFlight = false; });
    }

    rotate(deltaX: number, deltaY: number): void {
        this.root.rotation.y += deltaX * 0.006;
        this.root.rotation.x = clamp(this.root.rotation.x + deltaY * 0.006, -1.35, 1.35);
        this.render();
    }

    pan(deltaX: number, deltaY: number): void {
        const scale = this.mode === '2d' ? this.fitRadius / 600 : this.perspective.position.z / 900;
        this.root.position.x += deltaX * scale;
        this.root.position.y -= deltaY * scale;
        this.render();
    }

    zoomAt(delta: number, _pointer: GraphRendererPointer): void {
        const factor = Math.exp(clamp(delta, -800, 800) * 0.0012);
        if (this.mode === '2d') {
            this.orthographic.zoom = clamp(this.orthographic.zoom / factor, 0.08, 80);
            this.orthographic.updateProjectionMatrix();
        } else {
            this.perspective.position.z = clamp(this.perspective.position.z * factor, 0.08, 2_500);
        }
        this.render();
    }

    resetCamera(): void {
        this.root.position.set(0, 0, 0);
        this.root.rotation.set(0, 0, 0);
        this.perspective.position.set(0, 0, 8);
        this.perspective.lookAt(0, 0, 0);
        this.orthographic.position.set(0, 0, 20);
        this.orthographic.lookAt(0, 0, 0);
        this.orthographic.zoom = 1;
        this.orthographic.updateProjectionMatrix();
        this.render();
    }

    fitToGraph(): void {
        this.root.position.set(0, 0, 0);
        const distance = Math.max(2.2, this.fitRadius / Math.tan(THREE.MathUtils.degToRad(this.perspective.fov * 0.5)) * 1.15);
        this.perspective.position.set(0, 0, distance);
        this.perspective.lookAt(0, 0, 0);
        this.orthographic.zoom = 1;
        this.resize(this.viewportWidth, this.viewportHeight, 1);
    }

    focusIdentity(identity: string): void {
        const index = this.identityIndex(identity);
        if (index < 0 || !this.pages) return;
        const offset = index * 3;
        this.root.position.set(
            -this.pages.positions3d[offset],
            -this.pages.positions3d[offset + 1],
            -this.pages.positions3d[offset + 2],
        );
        this.render();
    }

    setSelectedIdentities(identities: readonly string[]): void {
        this.selectedIds = [...identities];
        this.rebuildOverlay();
    }

    setHoveredIdentity(identity: string | null): void {
        this.hoveredId = identity;
        this.rebuildOverlay();
    }

    async pick(_pointer: GraphRendererPointer): Promise<string | null> {
        return null;
    }

    dispose(): void {
        this.disposed = true;
        this.clearResidentObjects();
        this.renderer?.dispose();
        this.renderer = null;
    }

    private activeCamera(): THREE.Camera {
        return this.mode === '2d' ? this.orthographic : this.perspective;
    }

    private applyMode(): void {
        this.root.scale.z = this.mode === '2d' ? 0.0001 : 1;
    }

    private identityIndex(identity: string): number {
        if (!this.generation) return -1;
        if (!this.nodeIds) this.nodeIds = galaxyRendererV3NodeIds(this.generation.packet);
        if (!this.nodeIndexById) {
            this.nodeIndexById = new Map(this.nodeIds.map((id, index) => [id, index] as const));
        }
        return this.nodeIndexById.get(identity) ?? -1;
    }

    private rebuildOverlay(): void {
        disposeObject(this.root, this.overlayObject);
        this.overlayObject = null;
        if (!this.pages) return;
        const indexes = new Set<number>();
        for (const id of this.selectedIds) {
            const index = this.identityIndex(id);
            if (index >= 0) indexes.add(index);
        }
        if (this.hoveredId) {
            const index = this.identityIndex(this.hoveredId);
            if (index >= 0) indexes.add(index);
        }
        if (!indexes.size) return;
        this.overlayObject = buildOverlaySurface(this.pages, [...indexes]);
        this.root.add(this.overlayObject);
        this.render();
    }

    private clearResidentObjects(): void {
        disposeObject(this.root, this.overlayObject);
        disposeObject(this.root, this.nodeObject);
        disposeObject(this.root, this.edgeObject);
        this.overlayObject = null;
        this.nodeObject = null;
        this.edgeObject = null;
        this.pages = null;
    }

    private updateMetrics(patch: Partial<GalaxyRendererV3Metrics>): void {
        Object.assign(this.metrics, patch);
        galaxyRendererV3Metrics.update(this.metrics);
    }

    private recordFailure(error: Error): void {
        this.updateMetrics({ failures: this.metrics.failures + 1 });
        console.error('[GalaxyRendererV3] WebGPU operation failed.', error);
    }

    private failClosed(error: Error): never {
        this.recordFailure(error);
        throw error;
    }
}

function buildNodeSurface(pages: GalaxyRendererV3ResidentPages): THREE.Sprite | null {
    if (!pages.nodeCount) return null;
    const positions = new THREE.InstancedBufferAttribute(pages.positions3d, 3);
    const colors = new THREE.InstancedBufferAttribute(pages.nodeColorsRgba8, 4, true);
    const sizes = new THREE.InstancedBufferAttribute(scaledNodeSizes(pages.radii), 1);
    const material = new THREE.PointsNodeMaterial({
        positionNode: instancedBufferAttribute(positions, 'vec3'),
        colorNode: instancedBufferAttribute<'vec4'>(colors, 'vec4').rgb,
        opacityNode: shapeCircle(),
        sizeNode: instancedBufferAttribute(sizes, 'float'),
        sizeAttenuation: false,
        transparent: true,
        depthWrite: false,
        alphaToCoverage: true,
    });
    const sprite = new THREE.Sprite(material);
    sprite.count = pages.nodeCount;
    sprite.renderOrder = 4;
    return sprite;
}

function buildEdgeSurface(pages: GalaxyRendererV3ResidentPages, settings: GalaxyRenderSettings): THREE.LineSegments | null {
    if (!pages.edgeCount || settings.edgeMode === 'hidden') return null;
    const geometry = new THREE.InstancedBufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0, 0, 0], 3));
    geometry.instanceCount = pages.edgeCount;
    const positions = storage(
        new THREE.StorageBufferAttribute(pages.positions3d, 3),
        'vec3',
        pages.nodeCount,
    );
    const pairs = storage(
        new THREE.StorageBufferAttribute(pages.edgePairs, 1),
        'uint',
        pages.edgePairs.length,
    );
    const endpointOffset = instanceIndex.mul(uint(2)).add(vertexIndex);
    const endpointIndex = pairs.element(endpointOffset);
    const material = new THREE.LineBasicNodeMaterial({
        color: 0x67a8b8,
        transparent: true,
        opacity: denseEdgeOpacity(pages.edgeCount),
        depthWrite: false,
    });
    material.positionNode = positions.element(endpointIndex);
    const lines = new THREE.LineSegments(geometry, material);
    lines.frustumCulled = false;
    lines.renderOrder = 2;
    return lines;
}

function buildOverlaySurface(pages: GalaxyRendererV3ResidentPages, indexes: readonly number[]): THREE.Sprite {
    const positions = new Float32Array(indexes.length * 3);
    const sizes = new Float32Array(indexes.length);
    const colors = new Float32Array(indexes.length * 3);
    for (let output = 0; output < indexes.length; output++) {
        const source = indexes[output];
        positions.set(pages.positions3d.subarray(source * 3, source * 3 + 3), output * 3);
        sizes[output] = Math.max(8, pages.radii[source] * 4.2);
        colors.set([0.78, 1, 0.96], output * 3);
    }
    const material = new THREE.PointsNodeMaterial({
        positionNode: instancedBufferAttribute(new THREE.InstancedBufferAttribute(positions, 3), 'vec3'),
        colorNode: instancedBufferAttribute(new THREE.InstancedBufferAttribute(colors, 3), 'vec3'),
        opacityNode: shapeCircle(),
        sizeNode: instancedBufferAttribute(new THREE.InstancedBufferAttribute(sizes, 1), 'float'),
        sizeAttenuation: false,
        transparent: true,
        depthWrite: false,
        alphaToCoverage: true,
    });
    const sprite = new THREE.Sprite(material);
    sprite.count = indexes.length;
    sprite.renderOrder = 8;
    return sprite;
}

function scaledNodeSizes(radii: Float32Array): Float32Array {
    const scale = 1.65;
    const output = new Float32Array(radii.length);
    for (let index = 0; index < radii.length; index++) output[index] = clamp(radii[index] * scale, 1.5, 18);
    return output;
}

function denseEdgeOpacity(edgeCount: number): number {
    return clamp(0.2 / Math.sqrt(Math.max(1, edgeCount / 1_500)), 0.018, 0.18);
}

function sceneRadius(positions: Float32Array): number {
    let radius = 1;
    for (let offset = 0; offset < positions.length; offset += 3) {
        radius = Math.max(radius, Math.hypot(positions[offset], positions[offset + 1], positions[offset + 2]));
    }
    return radius;
}

function disposeObject(parent: THREE.Object3D, object: DisposableGalaxyObject | null): void {
    if (!object) return;
    parent.remove(object);
    object.geometry?.dispose();
    const materials = Array.isArray(object.material) ? object.material : object.material ? [object.material] : [];
    for (const material of materials) material.dispose();
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

function toError(error: unknown): Error {
    return error instanceof Error ? error : new Error(String(error));
}
