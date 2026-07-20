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
import { GalaxyRendererV3GpuPages } from './galaxy-renderer-v3-gpu-pages';
import {
    captureGalaxyRendererV3Positions,
    GALAXY_RENDERER_V3_CPU_PICK_LIMIT,
    GALAXY_RENDERER_V3_DRAG_NODE_LIMIT,
    GALAXY_RENDERER_V3_NEIGHBOR_LIMIT,
    GalaxyRendererV3InteractionState,
    restoreGalaxyRendererV3Positions,
} from './galaxy-renderer-v3-interaction';
import {
    galaxyRendererV3NodeIds,
    galaxyRendererV3PacketResidentBytes,
    galaxyRendererV3ResidentPages,
} from './galaxy-renderer-v3-packet-view';

type DisposableGalaxyObject = THREE.Object3D & {
    geometry?: THREE.BufferGeometry;
    material?: THREE.Material | THREE.Material[];
};

type WebGpuBackendWithQueue = {
    device?: {
        queue?: {
            onSubmittedWorkDone(): Promise<void>;
        };
    };
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
        sceneComputeMs: 0,
        sceneReadbackBytes: 0,
        nodeSizeScratchBytes: 0,
        frames: 0,
        failures: 0,
    };

    private readonly scene = new THREE.Scene();
    private readonly root = new THREE.Group();
    private readonly perspective = new THREE.PerspectiveCamera(46, 1, 0.01, 5_000);
    private readonly orthographic = new THREE.OrthographicCamera(-4, 4, 4, -4, 0.01, 5_000);
    private renderer: THREE.WebGPURenderer | null = null;
    private pages: GalaxyRendererV3ResidentPages | null = null;
    private gpuPages: GalaxyRendererV3GpuPages | null = null;
    private interactionState: GalaxyRendererV3InteractionState | null = null;
    private nodeFocusAttribute: THREE.InstancedBufferAttribute | null = null;
    private edgeFocusAttribute: THREE.InstancedBufferAttribute | null = null;
    private generation: GalaxyRendererV3Generation | null = null;
    private settings!: GalaxyRenderSettings;
    private mode: GraphRendererMode = '3d';
    private nodeIds: string[] | null = null;
    private nodeIndexById: Map<string, number> | null = null;
    private nodeObject: THREE.Sprite | null = null;
    private edgeObject: THREE.LineSegments | null = null;
    private overlayObject: THREE.Sprite | null = null;
    private readonly retiredObjects: DisposableGalaxyObject[] = [];
    private readonly retiredGpuPages: GalaxyRendererV3GpuPages[] = [];
    private selectedIds: readonly string[] = [];
    private hoveredId: string | null = null;
    private readonly pointerNdc = new THREE.Vector2();
    private readonly pointerRaycaster = new THREE.Raycaster();
    private readonly pickPosition = new THREE.Vector3();
    private readonly zoomAnchor = new THREE.Vector3();
    private readonly zoomPlane = new THREE.Plane();
    private readonly zoomNormal = new THREE.Vector3();
    private readonly dragPlane = new THREE.Plane();
    private readonly dragHit = new THREE.Vector3();
    private readonly dragOffset = new THREE.Vector3();
    private readonly dragTarget = new THREE.Vector3();
    private dragIndex = -1;
    private dragNeighbors: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
    private dragRestoreIndexes: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
    private dragRestorePositions: Float32Array<ArrayBufferLike> = new Float32Array(0);
    private fitRadius = 2;
    private viewportWidth = 1;
    private viewportHeight = 1;
    private renderInFlight = false;
    private renderTask: Promise<void> | null = null;
    private generationEpoch = 0;
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
        const epoch = ++this.generationEpoch;
        await this.waitForGpuIdle();
        if (epoch !== this.generationEpoch || this.disposed) return;
        const pages = galaxyRendererV3ResidentPages(generation.packet);
        const gpuPages = new GalaxyRendererV3GpuPages(pages.nodeCount, pages);
        this.clearResidentObjects();
        const reduction = await gpuPages.reduceSceneRadius(this.renderer);
        if (epoch !== this.generationEpoch || this.disposed) {
            gpuPages.dispose();
            return;
        }
        this.generation = generation;
        this.pages = pages;
        this.gpuPages = gpuPages;
        this.interactionState = new GalaxyRendererV3InteractionState(pages.nodeCount, pages.edgePairs);
        this.nodeFocusAttribute = new THREE.InstancedBufferAttribute(this.interactionState.nodeOpacity, 1);
        this.edgeFocusAttribute = new THREE.InstancedBufferAttribute(this.interactionState.edgeOpacity, 1);
        this.settings = settings;
        this.nodeIds = null;
        this.nodeIndexById = null;
        this.fitRadius = reduction.radius;
        this.nodeObject = buildNodeSurface(this.pages, gpuPages, this.nodeFocusAttribute);
        this.edgeObject = buildEdgeSurface(this.pages, gpuPages, this.edgeFocusAttribute, settings);
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
            sceneComputeMs: reduction.elapsedMs,
            sceneReadbackBytes: reduction.readbackBytes,
            nodeSizeScratchBytes: 0,
        });
        const firstPixelStarted = performance.now();
        const firstPixelTask = this.renderer.renderAsync(this.scene, this.activeCamera());
        this.renderTask = firstPixelTask;
        try {
            await firstPixelTask;
        } finally {
            if (this.renderTask === firstPixelTask) this.renderTask = null;
        }
        await this.flushRetiredResources();
        this.updateMetrics({ firstPixelMs: performance.now() - firstPixelStarted, frames: this.metrics.frames + 1 });
        this.rebuildOverlay();
    }

    setSettings(settings: GalaxyRenderSettings): void {
        this.settings = settings;
        this.syncEdgePresentation();
        this.render();
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
        const renderTask = this.renderer.renderAsync(this.scene, this.activeCamera())
            .then(() => this.updateMetrics({ frames: this.metrics.frames + 1 }))
            .catch((error) => this.recordFailure(toError(error)))
            .finally(() => {
                this.renderInFlight = false;
                if (this.renderTask === renderTask) this.renderTask = null;
            });
        this.renderTask = renderTask;
        void renderTask
            .then(() => this.flushRetiredResources())
            .catch((error) => this.recordFailure(toError(error)));
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

    zoomAt(delta: number, pointer: GraphRendererPointer): void {
        const factor = Math.exp(clamp(delta, -800, 800) * 0.0012);
        const anchored = this.zoomAnchorForPointer(pointer, this.zoomAnchor);
        if (this.mode === '2d') {
            this.orthographic.zoom = clamp(this.orthographic.zoom / factor, 0.08, 80);
            this.orthographic.updateProjectionMatrix();
        } else {
            const previousDistance = this.perspective.position.z;
            const nextDistance = clamp(previousDistance * factor, 0.08, 2_500);
            this.perspective.position.z = nextDistance;
        }
        if (anchored) this.restorePointerAnchor(pointer, this.zoomAnchor);
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

    beginNodeDrag(identity: string, pointer: GraphRendererPointer): boolean {
        if (!this.pages || !this.interactionState || this.settings.nodeDragMode === 'camera') return false;
        if (this.pages.nodeCount > GALAXY_RENDERER_V3_DRAG_NODE_LIMIT) return false;
        const index = this.identityIndex(identity);
        if (index < 0) return false;
        this.scene.updateMatrixWorld(true);
        this.pickPosition.fromArray(this.pages.positions3d, index * 3).applyMatrix4(this.root.matrixWorld);
        this.activeCamera().getWorldDirection(this.zoomNormal).normalize();
        this.dragPlane.setFromNormalAndCoplanarPoint(this.zoomNormal, this.pickPosition);
        if (!this.pointerToPlane(pointer, this.dragPlane, this.dragHit)) return false;
        this.dragOffset.copy(this.pickPosition).sub(this.dragHit);
        this.dragIndex = index;
        const neighborhood = this.interactionState.neighborhood(index, GALAXY_RENDERER_V3_NEIGHBOR_LIMIT);
        this.dragNeighbors = uniqueNodeIndexes(neighborhood.nodes, index);
        this.dragRestoreIndexes = new Uint32Array(this.dragNeighbors.length + 1);
        this.dragRestoreIndexes[0] = index;
        this.dragRestoreIndexes.set(this.dragNeighbors, 1);
        this.dragRestorePositions = captureGalaxyRendererV3Positions(
            this.pages.positions3d,
            this.dragRestoreIndexes,
        );
        this.retireObject(this.overlayObject);
        this.overlayObject = null;
        return true;
    }

    dragNode(pointer: GraphRendererPointer): boolean {
        if (this.dragIndex < 0 || !this.pages || !this.gpuPages) return false;
        if (!this.pointerToPlane(pointer, this.dragPlane, this.dragHit)) return false;
        this.scene.updateMatrixWorld(true);
        this.dragTarget.copy(this.dragHit).add(this.dragOffset);
        this.root.worldToLocal(this.dragTarget);
        const positions = this.pages.positions3d;
        const offset = this.dragIndex * 3;
        const dx = this.dragTarget.x - positions[offset];
        const dy = this.dragTarget.y - positions[offset + 1];
        const dz = this.mode === '2d' ? 0 : this.dragTarget.z - positions[offset + 2];
        positions[offset] = this.dragTarget.x;
        positions[offset + 1] = this.dragTarget.y;
        if (this.mode !== '2d') positions[offset + 2] = this.dragTarget.z;
        const pull = this.settings.nodeDragMode === 'pin' ? 0.18 : 0.14;
        for (const neighbor of this.dragNeighbors) {
            const neighborOffset = neighbor * 3;
            positions[neighborOffset] += dx * pull;
            positions[neighborOffset + 1] += dy * pull;
            if (this.mode !== '2d') positions[neighborOffset + 2] += dz * pull;
        }
        this.gpuPages.updatePositions(positions);
        this.render();
        return true;
    }

    endNodeDrag(): void {
        if (this.dragIndex < 0) return;
        if (this.settings.nodeDragMode === 'stretch' && this.pages && this.gpuPages) {
            restoreGalaxyRendererV3Positions(
                this.pages.positions3d,
                this.dragRestoreIndexes,
                this.dragRestorePositions,
            );
            this.gpuPages.updatePositions(this.pages.positions3d);
            this.render();
        }
        this.dragIndex = -1;
        this.dragNeighbors = new Uint32Array(0);
        this.dragRestoreIndexes = new Uint32Array(0);
        this.dragRestorePositions = new Float32Array(0);
        this.rebuildOverlay();
    }

    setSelectedIdentities(identities: readonly string[]): void {
        this.selectedIds = [...identities];
        this.applyFocusPresentation();
        this.rebuildOverlay();
    }

    setHoveredIdentity(identity: string | null): void {
        if (this.hoveredId === identity) return;
        this.hoveredId = identity;
        this.applyFocusPresentation();
        this.rebuildOverlay();
    }

    async pick(pointer: GraphRendererPointer): Promise<string | null> {
        const pages = this.pages;
        if (!pages?.nodeCount || pages.nodeCount > GALAXY_RENDERER_V3_CPU_PICK_LIMIT) return null;
        this.scene.updateMatrixWorld(true);
        const camera = this.activeCamera();
        camera.updateMatrixWorld(true);
        let bestIndex = -1;
        let bestDistance = Number.POSITIVE_INFINITY;
        let bestDepth = Number.POSITIVE_INFINITY;
        for (let index = 0; index < pages.nodeCount; index++) {
            this.pickPosition.fromArray(pages.positions3d, index * 3).applyMatrix4(this.root.matrixWorld).project(camera);
            if (this.pickPosition.z < -1 || this.pickPosition.z > 1) continue;
            const screenX = (this.pickPosition.x * 0.5 + 0.5) * pointer.width;
            const screenY = (-this.pickPosition.y * 0.5 + 0.5) * pointer.height;
            const dx = pointer.x - screenX;
            const dy = pointer.y - screenY;
            const distance = dx * dx + dy * dy;
            const radius = Math.max(7, clamp(pages.radii[index] * 1.65, 1.5, 18) * 0.7 + 3);
            if (distance > radius * radius) continue;
            if (distance < bestDistance || (distance === bestDistance && this.pickPosition.z < bestDepth)) {
                bestIndex = index;
                bestDistance = distance;
                bestDepth = this.pickPosition.z;
            }
        }
        if (bestIndex < 0) return null;
        if (!this.nodeIds) this.nodeIds = galaxyRendererV3NodeIds(this.generation!.packet);
        return this.nodeIds[bestIndex] || null;
    }

    dispose(): void {
        this.disposed = true;
        this.generationEpoch++;
        const renderer = this.renderer;
        const idleTask = this.waitForGpuIdle();
        this.renderer = null;
        void idleTask.finally(() => {
            this.clearResidentObjects();
            this.disposeRetiredResources(true);
            renderer?.dispose();
        });
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
        this.retireObject(this.overlayObject);
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

    private applyFocusPresentation(): void {
        if (!this.interactionState || !this.nodeFocusAttribute || !this.edgeFocusAttribute) return;
        const focusId = this.hoveredId || this.selectedIds[0] || null;
        this.interactionState.applyFocus(focusId ? this.identityIndex(focusId) : -1);
        this.nodeFocusAttribute.needsUpdate = true;
        this.edgeFocusAttribute.needsUpdate = true;
        this.render();
    }

    private syncEdgePresentation(): void {
        if (!this.pages || !this.gpuPages || !this.edgeFocusAttribute) return;
        if (this.settings.edgeMode === 'hidden') {
            if (this.edgeObject) this.edgeObject.visible = false;
            return;
        }
        if (!this.edgeObject) {
            this.edgeObject = buildEdgeSurface(
                this.pages,
                this.gpuPages,
                this.edgeFocusAttribute,
                this.settings,
            );
            if (this.edgeObject) this.root.add(this.edgeObject);
            return;
        }
        this.edgeObject.visible = true;
    }

    private zoomAnchorForPointer(pointer: GraphRendererPointer, out: THREE.Vector3): boolean {
        if (this.pages && this.hoveredId) {
            const index = this.identityIndex(this.hoveredId);
            if (index >= 0) {
                this.scene.updateMatrixWorld(true);
                out.fromArray(this.pages.positions3d, index * 3).applyMatrix4(this.root.matrixWorld);
                this.pickPosition.copy(out).project(this.activeCamera());
                const screenX = (this.pickPosition.x * 0.5 + 0.5) * pointer.width;
                const screenY = (-this.pickPosition.y * 0.5 + 0.5) * pointer.height;
                if (Number.isFinite(screenX) && Number.isFinite(screenY)
                    && Math.hypot(pointer.x - screenX, pointer.y - screenY) <= 48) {
                    this.activeCamera().getWorldDirection(this.zoomNormal).normalize();
                    this.zoomPlane.setFromNormalAndCoplanarPoint(this.zoomNormal, out);
                    return this.pointerToPlane(pointer, this.zoomPlane, out);
                }
            }
        }
        return this.pointerToTargetPlane(pointer, out);
    }

    private restorePointerAnchor(pointer: GraphRendererPointer, anchor: THREE.Vector3): void {
        this.activeCamera().updateMatrixWorld(true);
        this.activeCamera().getWorldDirection(this.zoomNormal).normalize();
        this.zoomPlane.setFromNormalAndCoplanarPoint(this.zoomNormal, anchor);
        if (!this.pointerToPlane(pointer, this.zoomPlane, this.dragHit)) return;
        this.root.position.add(this.dragHit.sub(anchor));
    }

    private pointerToTargetPlane(pointer: GraphRendererPointer, out: THREE.Vector3): boolean {
        this.activeCamera().getWorldDirection(this.zoomNormal).normalize();
        this.zoomPlane.setFromNormalAndCoplanarPoint(this.zoomNormal, this.root.position);
        return this.pointerToPlane(pointer, this.zoomPlane, out);
    }

    private pointerToPlane(pointer: GraphRendererPointer, plane: THREE.Plane, out: THREE.Vector3): boolean {
        this.pointerNdc.set(
            (pointer.x / Math.max(1, pointer.width)) * 2 - 1,
            -(pointer.y / Math.max(1, pointer.height)) * 2 + 1,
        );
        this.pointerRaycaster.setFromCamera(this.pointerNdc, this.activeCamera());
        return Boolean(this.pointerRaycaster.ray.intersectPlane(plane, out));
    }

    private clearResidentObjects(): void {
        this.retireObject(this.overlayObject);
        this.retireObject(this.nodeObject);
        this.retireObject(this.edgeObject);
        this.overlayObject = null;
        this.nodeObject = null;
        this.edgeObject = null;
        if (this.gpuPages) this.retiredGpuPages.push(this.gpuPages);
        this.gpuPages = null;
        this.interactionState = null;
        this.nodeFocusAttribute = null;
        this.edgeFocusAttribute = null;
        this.dragIndex = -1;
        this.dragNeighbors = new Uint32Array(0);
        this.pages = null;
    }

    private retireObject(object: DisposableGalaxyObject | null): void {
        if (!object) return;
        this.root.remove(object);
        this.retiredObjects.push(object);
    }

    private async flushRetiredResources(): Promise<void> {
        if (!this.retiredObjects.length && !this.retiredGpuPages.length) return;
        await this.waitForGpuIdle();
        this.disposeRetiredResources(true);
    }

    private disposeRetiredResources(disposeGpuPages: boolean): void {
        for (const object of this.retiredObjects.splice(0)) disposeDetachedObject(object);
        if (disposeGpuPages) {
            for (const gpuPages of this.retiredGpuPages.splice(0)) gpuPages.dispose();
        }
    }

    private async waitForGpuIdle(): Promise<void> {
        const renderTask = this.renderTask;
        if (renderTask) await renderTask;
        const backend = this.renderer?.backend as WebGpuBackendWithQueue | undefined;
        await backend?.device?.queue?.onSubmittedWorkDone();
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

function buildNodeSurface(
    pages: GalaxyRendererV3ResidentPages,
    gpuPages: GalaxyRendererV3GpuPages,
    focus: THREE.InstancedBufferAttribute,
): THREE.Sprite | null {
    if (!pages.nodeCount) return null;
    const colors = new THREE.InstancedBufferAttribute(pages.nodeColorsRgba8, 4, true);
    const focusNode = instancedBufferAttribute<'float'>(focus, 'float');
    const material = new THREE.PointsNodeMaterial({
        positionNode: gpuPages.nodePositionNode(),
        colorNode: instancedBufferAttribute<'vec4'>(colors, 'vec4').rgb.mul(focusNode),
        opacityNode: shapeCircle(),
        sizeNode: gpuPages.nodeSizeNode(),
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

function buildEdgeSurface(
    pages: GalaxyRendererV3ResidentPages,
    gpuPages: GalaxyRendererV3GpuPages,
    focus: THREE.InstancedBufferAttribute,
    settings: GalaxyRenderSettings,
): THREE.LineSegments | null {
    if (!pages.edgeCount || settings.edgeMode === 'hidden') return null;
    const geometry = new THREE.InstancedBufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0, 0, 0], 3));
    geometry.instanceCount = pages.edgeCount;
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
        depthWrite: false,
    });
    material.positionNode = gpuPages.positions.element(endpointIndex).xyz;
    material.opacityNode = instancedBufferAttribute<'float'>(focus, 'float').mul(denseEdgeOpacity(pages.edgeCount));
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

function denseEdgeOpacity(edgeCount: number): number {
    return clamp(0.2 / Math.sqrt(Math.max(1, edgeCount / 1_500)), 0.018, 0.18);
}

function disposeDetachedObject(object: DisposableGalaxyObject): void {
    // Three.js shares one internal quad geometry across every Sprite instance.
    // Disposing it here invalidates the next node/overlay draw submission.
    if (!(object instanceof THREE.Sprite)) object.geometry?.dispose();
    const materials = Array.isArray(object.material) ? object.material : object.material ? [object.material] : [];
    for (const material of materials) material.dispose();
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

function uniqueNodeIndexes(indexes: Uint32Array, excluded: number): Uint32Array {
    const unique = new Set<number>();
    for (const index of indexes) {
        if (index !== excluded) unique.add(index);
    }
    return Uint32Array.from(unique);
}

function toError(error: unknown): Error {
    return error instanceof Error ? error : new Error(String(error));
}
