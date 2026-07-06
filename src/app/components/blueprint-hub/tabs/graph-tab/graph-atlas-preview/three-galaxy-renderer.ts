import * as THREE from 'three';

import type { GalaxyBusemannHorosphereView, GalaxyHopfRibbonView, GalaxyLorentzGuideView, GalaxySceneGroupView, GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { buildGalaxyFocusMask, type GalaxyFocusMask } from './graph-galaxy-focus';
import { isTransitLayoutMode, mergeGalaxySettings, type GalaxyRenderSettings } from './graph-galaxy-engine';
import { GraphGalaxyForceController, transitManifoldExpansionScale } from './graph-galaxy-force-controller';
import {
    buildGalaxyGlows,
    buildGalaxyNodes,
    galaxySphereNodeBatch,
    galaxySphereNodeStateIndex,
    galaxyGlowBatch,
    galaxyNodePickShapeBoost,
    galaxyNodeShapeScale,
    type GalaxySphereNodeBatch,
    type GalaxyGlowBatch,
    type GalaxyNodeMaterial,
    type GalaxyNodeObject,
} from './graph-galaxy-objects';
import { GraphGalaxyParticles } from './graph-galaxy-particles';
import { makeAtomTexture, makeHaloTexture, makeLabelSprite, makeNodeTexture, type LabelSprite } from './graph-galaxy-textures';
import type { GraphRendererMode, GraphRendererPointer, GraphRendererPort } from './graph-renderer-port';
import type { GraphCanvasHit } from './graph-canvas-interaction';
import { setHopfEdgeCurvePoint, type GalaxyCurvePoint } from './graph-galaxy-edge-curves';

const MAX_EDGE_SEGMENTS = 8;
const CURVED_EDGE_SEGMENTS = 16;
const LEAN_CURVED_EDGE_SEGMENTS = 12;
const TREE_FILAMENT_EDGE_SEGMENTS = 18;
const MAX_EDGE_TUBE_SEGMENTS = 18;
const HOPF_EDGE_SEGMENTS = 24;
const HOPF_CROSS_EDGE_SEGMENTS = 32;
const MAX_EDGE_STROKES = 5;
const LEAN_EDGE_STYLE_THRESHOLD = 1200;
const LEAN_EDGE_STROKES = 2;
const LEAN_HOPF_EDGE_SEGMENTS = 20;
const LEAN_HOPF_CROSS_EDGE_SEGMENTS = 24;
const MAX_HOPF_RIBBON_GUIDES = 128;
const MAX_HOPF_DATA_TUBES = 20;
const MAX_HOPF_TORUS_TUBES = 12;
const HOPF_TUBE_SEGMENTS = 96;
const HOPF_TUBE_RADIAL_SEGMENTS = 6;
const HOPF_LINE_SEGMENTS = 144;
const HOPF_CROSS_BAND_LINE_SEGMENTS = 72;
const HOPF_LINE_SEGMENT_LIMIT = 192;
const MAX_LORENTZ_GUIDES = 260;
const MAX_LORENTZ_TUBES = 40;
const LORENTZ_TUBE_SEGMENTS = 64;
const LORENTZ_TUBE_RADIAL_SEGMENTS = 5;
const TRANSIT_HOPF_TUBE_SCALE = 0.75;
const CAPS_SURFACE_EDGE_MIN_RADIUS = 0.34;
const CAPS_SURFACE_EDGE_MAX_RADIUS_DELTA = 0.36;
const CAPS_SHELL_RADII = [0.54, 0.98, 1.22, 1.34, 1.48, 1.68, 1.92];
const HYBRID_SURFACE_EDGE_MIN_RADIUS = 2.32 * 0.92;
const HYBRID_SURFACE_EDGE_MAX_RADIUS_DELTA = 0.42;
const MAX_CAMERA_VIEW_SHIFT = 2.6;
const TREE_FILAMENT_EDGE_LAYOUTS = new Set(['lorentzTree', 'transitManifold', 'productManifold', 'siegelFinsler']);
type GuideSurface = 'default' | 'transit';
type EdgeStyleData = Pick<GalaxySceneV2, 'edgeAlpha' | 'edgeKinds'> & Partial<Pick<GalaxySceneV2, 'edgePairs' | 'layoutMode'>>;
interface GuideAttachmentContract {
    liveLorentzGuides: boolean;
    localScale: number;
}

function pointSegmentDistanceSquared(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    if (lengthSquared <= 0.000001) return (px - ax) ** 2 + (py - ay) ** 2;
    const t = THREE.MathUtils.clamp(((px - ax) * dx + (py - ay) * dy) / lengthSquared, 0, 1);
    const x = ax + t * dx;
    const y = ay + t * dy;
    return (px - x) ** 2 + (py - y) ** 2;
}

export interface ThreeGalaxyRendererTimings {
    rendererSetSceneMs: number;
    applyModeMs: number;
    liveGeometryMs: number;
    focusMs: number;
    instancesMs: number;
    edgeGeometryMs: number;
    labelsMs: number;
    pickMs: number;
    drawMs: number;
}

function emptyRendererTimings(): ThreeGalaxyRendererTimings {
    return {
        rendererSetSceneMs: 0,
        applyModeMs: 0,
        liveGeometryMs: 0,
        focusMs: 0,
        instancesMs: 0,
        edgeGeometryMs: 0,
        labelsMs: 0,
        pickMs: 0,
        drawMs: 0,
    };
}

export class ThreeGalaxyRenderer implements GraphRendererPort {
    private renderer: THREE.WebGLRenderer | null = null;
    private readonly scene = new THREE.Scene();
    private readonly raycaster = new THREE.Raycaster();
    private readonly pointer = new THREE.Vector2();
    private readonly dragPlane = new THREE.Plane();
    private readonly dragPlanePoint = new THREE.Vector3();
    private readonly dragHit = new THREE.Vector3();
    private readonly dragOffset = new THREE.Vector3();
    private readonly dragTarget = new THREE.Vector3();
    private readonly zoomPlane = new THREE.Plane();
    private readonly zoomBefore = new THREE.Vector3();
    private readonly zoomNormal = new THREE.Vector3();
    private readonly zoomProjected = new THREE.Vector3();
    private readonly pickVector = new THREE.Vector3();
    private readonly pickVectorB = new THREE.Vector3();
    private readonly cameraTarget = new THREE.Vector3();
    private readonly perspective = new THREE.PerspectiveCamera(48, 1, 0.01, 100);
    private readonly ortho = new THREE.OrthographicCamera(-4, 4, 3, -3, 0.01, 100);
    private readonly color = new THREE.Color();
    private readonly densityVector = new THREE.Vector3();
    private readonly edgeSurfacePoint = new THREE.Vector3();
    private readonly edgeCurvePoint: GalaxyCurvePoint = { x: 0, y: 0, z: 0 };
    private readonly fieldVector = new THREE.Vector3();
    private readonly instanceMatrix = new THREE.Matrix4();
    private readonly instancePosition = new THREE.Vector3();
    private readonly instanceQuaternion = new THREE.Quaternion();
    private readonly instanceScale = new THREE.Vector3();
    private readonly force = new GraphGalaxyForceController();
    private readonly dragVector = new THREE.Vector3();
    private readonly atomTexture = makeAtomTexture();
    private readonly nodeTexture = makeNodeTexture();
    private readonly haloTexture = makeHaloTexture();
    private readonly particles = new GraphGalaxyParticles();
    private mode: GraphRendererMode = '3d';
    private sceneData: GalaxySceneV2 | null = null;
    private nodes: THREE.Group | null = null;
    private glows: THREE.Group | null = null;
    private shells: THREE.Group | null = null;
    private edges: THREE.LineSegments | null = null;
    private labels: LabelSprite[] = [];
    private focusMask: GalaxyFocusMask | null = null;
    private selectedId: string | null = null;
    private hoverId: string | null = null;
    private settings: GalaxyRenderSettings = mergeGalaxySettings();
    private nodeShape = this.settings.nodeShape;
    private yaw = -0.34;
    private pitch = 0.22;
    private distance = 7.2;
    private panX = 0;
    private panY = 0;
    private panZ = 0;
    private viewShiftX = 0;
    private viewShiftY = 0;
    private dragReady = false;
    private densityBins = new Uint16Array(0);
    private densityNodeBins = new Int32Array(0);
    private densityFactors = new Float32Array(0);
    private guidePositionBuffer = new Float32Array(0);
    private labelSignature = '';
    private readonly timings: ThreeGalaxyRendererTimings = emptyRendererTimings();

    constructor() {
        const skyLight = new THREE.HemisphereLight(0xc9f5ff, 0x160b24, 1.35);
        const keyLight = new THREE.DirectionalLight(0xffffff, 2.1);
        const rimLight = new THREE.DirectionalLight(0x67e8f9, 1.15);
        keyLight.position.set(-3.5, 5.2, 4.4);
        rimLight.position.set(4.8, -1.6, -3.2);
        this.scene.add(skyLight, keyLight, rimLight);
    }

    mount(canvas: HTMLCanvasElement): boolean {
        if (this.renderer) return false;
        this.scene.background = new THREE.Color(0x02040a);
        this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
        this.renderer.setClearColor(0x02040a, 1);
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
        this.scene.add(this.particles.points);
        this.resetCamera();
        return true;
    }

    hasContext(): boolean {
        return Boolean(this.renderer);
    }

    releaseContext(): void {
        const renderer = this.renderer;
        if (!renderer) return;
        renderer.forceContextLoss();
        renderer.dispose();
        this.renderer = null;
    }

    setScene(scene: GalaxySceneV2): void {
        const started = this.now();
        this.sceneData = scene;
        this.clearObjects();
        this.nodeShape = this.settings.nodeShape;
        this.shells = this.buildGroupShells(scene);
        this.nodes = buildGalaxyNodes(scene, this.settings, this.nodeTexture, this.atomTexture);
        this.glows = buildGalaxyGlows(scene, this.haloTexture);
        this.updateGlowViewport();
        this.edges = this.buildEdges(scene);
        this.force.bind(scene);
        this.force.setSettings(this.settings);
        this.particles.bind(scene, this.settings);
        this.force.setMode(this.mode);
        if (this.shells) this.scene.add(this.shells);
        if (this.edges) this.scene.add(this.edges);
        if (this.glows) this.scene.add(this.glows);
        if (this.nodes) this.scene.add(this.nodes);
        this.applyModePositions();
        this.recordTiming('rendererSetSceneMs', started);
        this.render();
    }

    setSettings(settings: Partial<GalaxyRenderSettings> | null): void {
        const previousShape = this.settings.nodeShape;
        const previousSphereSurface = this.settings.sphereSurface;
        const previousHybridField = `${this.settings.hybridHorospheresVisible}:${this.settings.hybridPrototypeRaysVisible}`;
        this.settings = mergeGalaxySettings(settings);
        this.force.setSettings(this.settings);
        if (this.sceneData) this.particles.bind(this.sceneData, this.settings);
        const nextHybridField = `${this.settings.hybridHorospheresVisible}:${this.settings.hybridPrototypeRaysVisible}`;
        if (this.sceneData?.layoutMode === 'hybridSpace' && previousHybridField !== nextHybridField) {
            this.rebuildShellObjects(this.sceneData);
        }
        if (this.sceneData && (previousShape !== this.settings.nodeShape
            || previousSphereSurface !== this.settings.sphereSurface)) {
            this.nodeShape = this.settings.nodeShape;
            this.rebuildNodeObjects(this.sceneData);
            this.applyModePositions();
            this.render();
            return;
        }
        this.applyMaterialSettings();
        this.applyModePositions();
        this.render();
    }

    private rebuildShellObjects(data: GalaxySceneV2): void {
        if (this.shells) {
            this.scene.remove(this.shells);
            this.shells.traverse((child) => {
                const drawable = child as THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
                drawable.geometry?.dispose();
                const material = drawable.material;
                if (Array.isArray(material)) material.forEach((item) => item.dispose());
                else material?.dispose();
            });
        }
        this.shells = this.buildGroupShells(data);
        if (this.shells) this.scene.add(this.shells);
    }

    setMode(mode: GraphRendererMode): void {
        this.mode = mode;
        this.force.setMode(mode);
        this.applyModePositions();
        this.updateCamera();
    }

    resize(width: number, height: number, dpr: number): void {
        if (!this.renderer) return;
        this.renderer.setPixelRatio(dpr);
        this.renderer.setSize(width, height, false);
        this.perspective.aspect = Math.max(0.01, width / Math.max(1, height));
        const aspect = this.perspective.aspect;
        this.ortho.left = -4.2 * aspect;
        this.ortho.right = 4.2 * aspect;
        this.ortho.top = 3.1;
        this.ortho.bottom = -3.1;
        this.updateCamera();
        this.updateGlowViewport();
    }

    render(): void {
        const renderer = this.renderer;
        if (!renderer) return;
        const started = this.now();
        this.particles.update(this.sceneData, this.positions(), this.settings, performance.now(), this.focusMask);
        renderer.render(this.scene, this.camera());
        this.recordTiming('drawMs', started);
    }

    rotate(deltaX: number, deltaY: number): void {
        if (this.mode === '2d') {
            this.pan(deltaX, deltaY);
            return;
        }
        this.yaw += deltaX * 0.006;
        this.pitch = THREE.MathUtils.clamp(this.pitch + deltaY * 0.004, -1.35, 1.35);
        this.updateCamera();
    }

    pan(deltaX: number, deltaY: number): void {
        const scale = this.mode === '2d' ? 0.008 * this.distance : 0.0045 * this.distance;
        this.panX -= deltaX * scale;
        this.panY += deltaY * scale;
        this.updateCamera();
    }

    zoom(delta: number): void {
        const nextDistance = THREE.MathUtils.clamp(this.distance * Math.exp(delta * 0.0012), 2.2, 22);
        if (nextDistance === this.distance) return;
        this.distance = nextDistance;
        this.updateCamera();
    }

    zoomAt(delta: number, pointer: GraphRendererPointer): void {
        const nextDistance = THREE.MathUtils.clamp(this.distance * Math.exp(delta * 0.0012), 2.2, 22);
        if (nextDistance === this.distance) return;
        const hasAnchor = this.pointerToCameraTargetPlane(pointer, this.zoomBefore);
        this.distance = nextDistance;
        if (!hasAnchor) {
            this.updateCamera();
            return;
        }
        this.updateCamera(false);
        this.zoomProjected.copy(this.zoomBefore).project(this.camera());
        if (Number.isFinite(this.zoomProjected.x) && Number.isFinite(this.zoomProjected.y)) {
            const pointerX = (pointer.x / Math.max(1, pointer.width)) * 2 - 1;
            const pointerY = -(pointer.y / Math.max(1, pointer.height)) * 2 + 1;
            this.viewShiftX = THREE.MathUtils.clamp(
                this.viewShiftX + pointerX - this.zoomProjected.x,
                -MAX_CAMERA_VIEW_SHIFT,
                MAX_CAMERA_VIEW_SHIFT,
            );
            this.viewShiftY = THREE.MathUtils.clamp(
                this.viewShiftY + pointerY - this.zoomProjected.y,
                -MAX_CAMERA_VIEW_SHIFT,
                MAX_CAMERA_VIEW_SHIFT,
            );
        }
        this.updateCamera();
    }

    resetCamera(): void {
        this.yaw = -0.34;
        this.pitch = 0.22;
        this.distance = 7.2;
        this.panX = 0;
        this.panY = 0;
        this.panZ = 0;
        this.clearViewShift();
        this.updateCamera();
    }

    fitToGraph(): void {
        this.distance = this.mode === '2d' ? 6.2 : 7.2;
        this.panX = 0;
        this.panY = 0;
        this.panZ = 0;
        this.clearViewShift();
        this.updateCamera();
    }

    focusNode(id: string): void {
        const data = this.sceneData;
        if (!data) return;
        const index = data.ids.indexOf(id);
        if (index < 0) return;
        const positions = this.mode === '2d' ? data.positions2d : data.positions3d;
        this.panX = positions[index * 3];
        this.panY = positions[index * 3 + 1];
        this.panZ = positions[index * 3 + 2];
        this.distance = Math.min(this.distance, 5.4);
        this.clearViewShift();
        this.updateCamera();
    }

    clearFocus(): void {
        this.panX = this.panY = this.panZ = 0;
        this.clearViewShift();
        this.updateCamera();
    }

    beginNodeDrag(id: string, pointer: GraphRendererPointer): boolean {
        if (!this.force.begin(id)) return false;
        this.dragReady = this.configureNodeDrag(pointer);
        return this.dragReady;
    }

    dragNode(pointer: GraphRendererPointer): boolean {
        if (this.settings.nodeDragMode === 'camera') return false;
        if (!this.dragReady || !this.pointerToDragPlane(pointer, this.dragHit)) return false;
        this.dragTarget.copy(this.dragHit).add(this.dragOffset);
        if (this.mode === '2d') this.dragTarget.z = 0;
        if (!this.force.dragTo(this.dragTarget, this.settings.nodeDragMode)) return false;
        this.updateLiveGeometry();
        return true;
    }

    endNodeDrag(): boolean {
        this.dragReady = false;
        return this.force.end(this.settings.nodeDragMode);
    }

    tickForces(): boolean {
        const active = this.force.tick();
        active ? this.updateLiveGeometry() : this.applyModePositions();
        return active;
    }

    hasActiveForces(): boolean {
        return this.force.active();
    }

    selectNode(id: string | null): void {
        if (this.selectedId === id) return;
        this.selectedId = id;
        this.applyFocusState();
    }

    hoverNode(id: string | null): void {
        if (this.hoverId === id) return;
        this.hoverId = id;
        this.applyFocusState();
    }

    pick(pointer: GraphRendererPointer): string | null {
        const hit = this.pickObject(pointer);
        return hit?.kind === 'node' ? hit.id : null;
    }

    pickObject(pointer: GraphRendererPointer): GraphCanvasHit | null {
        const started = this.now();
        try {
            if (!this.sceneData) return null;
            const screenHit = this.screenSpacePick(pointer);
            if (screenHit >= 0) return { kind: 'node', id: this.sceneData.ids[screenHit] };
            const skipRaycastFallback = this.sceneData.ids.length > 600 || Boolean(galaxySphereNodeBatch(this.nodes));
            if (this.nodes && !skipRaycastFallback) {
                this.pointer.x = (pointer.x / Math.max(1, pointer.width)) * 2 - 1;
                this.pointer.y = -(pointer.y / Math.max(1, pointer.height)) * 2 + 1;
                this.raycaster.setFromCamera(this.pointer, this.camera());
                const hit = this.raycaster.intersectObjects(this.nodes.children, false)[0];
                const index = Number(hit?.object.userData['index']);
                if (Number.isFinite(index)) return { kind: 'node', id: this.sceneData.ids[index] };
            }
            const edgeIndex = this.screenSpaceEdgePick(pointer);
            if (edgeIndex >= 0) {
                const sourceIndex = this.sceneData.edgePairs[edgeIndex * 2];
                const targetIndex = this.sceneData.edgePairs[edgeIndex * 2 + 1];
                return {
                    kind: 'edge',
                    id: this.sceneData.edgeIds[edgeIndex],
                    sourceId: this.sceneData.ids[sourceIndex],
                    targetId: this.sceneData.ids[targetIndex],
                };
            }
            return this.screenSpaceGroupPick(pointer);
        } finally {
            this.recordTiming('pickMs', started);
        }
    }

    nodesInRect(rect: { left: number; top: number; right: number; bottom: number; width: number; height: number }): string[] {
        const data = this.sceneData;
        const positions = this.positions();
        if (!data || !positions || rect.width <= 0 || rect.height <= 0) return [];
        const camera = this.camera();
        const ids: string[] = [];
        for (let index = 0; index < data.ids.length; index++) {
            const offset = index * 3;
            this.pickVector.set(positions[offset], positions[offset + 1], positions[offset + 2]).project(camera);
            if (this.pickVector.z < -1 || this.pickVector.z > 1) continue;
            const x = (this.pickVector.x * 0.5 + 0.5) * rect.width;
            const y = (-this.pickVector.y * 0.5 + 0.5) * rect.height;
            if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) ids.push(data.ids[index]);
        }
        return ids;
    }

    snapshotTimings(): ThreeGalaxyRendererTimings {
        return { ...this.timings };
    }

    dispose(): void {
        this.clearObjects();
        this.atomTexture.dispose();
        this.nodeTexture.dispose();
        this.haloTexture.dispose();
        this.scene.remove(this.particles.points);
        this.particles.dispose();
        this.releaseContext();
        this.renderer = null;
    }

    private buildEdges(scene: GalaxySceneV2): THREE.LineSegments | null {
        if (!scene.edgePairs.length) return null;
        const geometry = new THREE.BufferGeometry();
        const edgeCount = scene.edgePairs.length / 2;
        const denseEdges = this.isDenseEdgeScene(scene);
        const maxEdgeSegments = denseEdges
            ? Math.max(LEAN_CURVED_EDGE_SEGMENTS, LEAN_HOPF_CROSS_EDGE_SEGMENTS)
            : Math.max(MAX_EDGE_TUBE_SEGMENTS, HOPF_CROSS_EDGE_SEGMENTS);
        const maxEdgeStrokes = denseEdges ? LEAN_EDGE_STROKES : MAX_EDGE_STROKES;
        const vertexCapacity = edgeCount * maxEdgeSegments * 2 * maxEdgeStrokes;
        geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vertexCapacity * 3), 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(vertexCapacity * 3), 3));
        const material = new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: this.edgeMaterialOpacity(),
            linewidth: this.edgeMaterialWidth(),
            blending: THREE.NormalBlending,
            toneMapped: false,
        });
        return new THREE.LineSegments(geometry, material);
    }

    private applyModePositions(): void {
        const data = this.sceneData;
        if (!data) return;
        const started = this.now();
        const positions = this.mode === '2d' ? data.positions2d : data.positions3d;
        const focusStarted = this.now();
        const focus = buildGalaxyFocusMask(data, this.selectedId, this.hoverId);
        this.recordTiming('focusMs', focusStarted);
        this.focusMask = focus;
        this.updateGroupShells(data);
        this.updateLorentzGuideGeometry(data, positions);
        this.updateGuideFocus(data, focus);
        const instancesStarted = this.now();
        this.updateInstances(data, positions, focus);
        this.recordTiming('instancesMs', instancesStarted);
        const edgeStarted = this.now();
        this.updateEdgeGeometry(data, positions, focus);
        this.recordTiming('edgeGeometryMs', edgeStarted);
        const labelsStarted = this.now();
        this.updateLabels(data, positions, true);
        this.recordTiming('labelsMs', labelsStarted);
        this.recordTiming('applyModeMs', started);
    }

    private applyFocusState(): void {
        const data = this.sceneData;
        const positions = this.positions();
        if (!data || !positions) return;
        const started = this.now();
        const focusStarted = this.now();
        const focus = buildGalaxyFocusMask(data, this.selectedId, this.hoverId);
        this.recordTiming('focusMs', focusStarted);
        this.focusMask = focus;
        this.updateGuideFocus(data, focus);
        const instancesStarted = this.now();
        this.updateInstances(data, positions, focus);
        this.recordTiming('instancesMs', instancesStarted);
        const edgeStarted = this.now();
        this.updateEdgeColors(data, positions, focus);
        this.recordTiming('edgeGeometryMs', edgeStarted);
        const labelsStarted = this.now();
        this.updateLabels(data, positions, false);
        this.recordTiming('labelsMs', labelsStarted);
        this.recordTiming('applyModeMs', started);
    }

    private updateLiveGeometry(): void {
        const data = this.sceneData;
        if (!data) return;
        const positions = this.positions();
        if (!positions) return;
        const started = this.now();
        const focusStarted = this.now();
        const focus = buildGalaxyFocusMask(data, this.selectedId, this.hoverId);
        this.recordTiming('focusMs', focusStarted);
        this.focusMask = focus;
        this.updateGroupShells(data);
        this.updateLorentzGuideGeometry(data, positions);
        this.updateGuideFocus(data, focus);
        const instancesStarted = this.now();
        this.updateInstances(data, positions, focus);
        this.recordTiming('instancesMs', instancesStarted);
        const edgeStarted = this.now();
        this.updateEdgeGeometry(data, positions, focus);
        this.recordTiming('edgeGeometryMs', edgeStarted);
        this.recordTiming('liveGeometryMs', started);
    }

    private updateInstances(data: GalaxySceneV2, positions: Float32Array, focus: GalaxyFocusMask): void {
        if (!this.nodes || !this.glows) return;
        const density = this.nodeDensityFactors(data, positions);
        const sphereBatch = galaxySphereNodeBatch(this.nodes);
        const glowBatch = galaxyGlowBatch(this.glows);
        for (let i = 0; i < data.ids.length; i++) {
            const densityFactor = density[i] ?? 1;
            const active = data.ids[i] === this.selectedId;
            const hovered = data.ids[i] === this.hoverId;
            const level = focus.nodeLevels[i] ?? 1;
            const dimmed = focus.hasFocus && level === 0;
            const neighbor = focus.hasFocus && level === 2;
            const pulse = active && this.settings.selectedPulse ? 1.14 : 1;
            const core = Math.max(0.038, data.radii[i] * 0.021) * pulse;
            const sphere = this.nodeShape === 'sphere';
            const atom = this.nodeShape === 'atom';
            const transitAtom = atom && isTransitLayoutMode(data.layoutMode);
            const halo = atom ? 0 : core * this.settings.glow * (sphere
                    ? (hovered ? 1.94 : active ? 2.12 : neighbor ? 1.28 : dimmed ? 0.52 : 0.94)
                    : (hovered ? 4.9 : active ? 5.05 : neighbor ? 3.1 : dimmed ? 1.15 : 2.45));
            const offset = i * 3;
            const x = positions[offset];
            const y = positions[offset + 1];
            const z = positions[offset + 2];
            const nodeScale = core * galaxyNodeShapeScale(this.nodeShape, {
                active,
                hovered,
                neighbor,
                dimmed,
                transitAtom,
            });
            this.nodeColor(data, i);
            if (sphereBatch) {
                this.writeSphereNodeInstance(
                    sphereBatch,
                    i,
                    galaxySphereNodeStateIndex(active, hovered, neighbor, dimmed),
                    x,
                    y,
                    z,
                    nodeScale,
                );
            } else {
                const node = this.nodes.children[i] as GalaxyNodeObject | undefined;
                if (!node) continue;
                node.position.set(x, y, z);
                node.scale.setScalar(nodeScale);
                const material = node.material as GalaxyNodeMaterial;
                material.color.copy(this.color);
                const baseOpacity = transitAtom
                    ? (dimmed ? 0.16 : neighbor ? 0.86 : hovered || active ? 1 : 0.98)
                    : (dimmed ? 0.18 : neighbor ? 0.82 : hovered || active ? 1 : 0.94);
                material.opacity = material instanceof THREE.MeshPhysicalMaterial
                    ? baseOpacity * (hovered || active ? 0.88 : neighbor ? 0.8 : 0.76)
                    : baseOpacity;
                if (material instanceof THREE.MeshPhysicalMaterial) {
                    material.emissive.copy(this.color);
                    material.emissiveIntensity = dimmed ? 0.06 : hovered || active ? 0.34 : neighbor ? 0.22 : 0.16;
                }
            }
            this.glowColor(data, i);
            const glowBase = atom ? 0 : sphere
                    ? (dimmed ? 0.012 : hovered || active ? 0.28 : neighbor ? 0.11 : 0.078)
                    : (dimmed ? 0.04 : hovered || active ? 0.58 : neighbor ? 0.28 : 0.22);
            const glowOpacity = THREE.MathUtils.clamp(glowBase * this.settings.glow * densityFactor, 0, 0.24);
            const glowScale = halo * (0.82 + densityFactor * 0.18);
            if (glowBatch) {
                this.writeGlowPoint(glowBatch, i, x, y, z, glowScale, glowOpacity);
            } else {
                const glow = this.glows.children[i] as THREE.Sprite | undefined;
                if (!glow) continue;
                glow.position.set(x, y, z);
                glow.scale.setScalar(glowScale);
                glow.material.color.copy(this.color);
                glow.material.opacity = glowOpacity;
                glow.visible = glowOpacity > 0;
            }
        }
        if (sphereBatch) this.markSphereNodeBatchDirty(sphereBatch);
        if (glowBatch) this.markGlowBatchDirty(glowBatch);
    }

    private writeSphereNodeInstance(
        batch: GalaxySphereNodeBatch,
        index: number,
        stateIndex: number,
        x: number,
        y: number,
        z: number,
        scale: number,
    ): void {
        this.instancePosition.set(x, y, z);
        for (let meshIndex = 0; meshIndex < batch.meshes.length; meshIndex++) {
            const mesh = batch.meshes[meshIndex];
            this.instanceScale.setScalar(meshIndex === stateIndex ? scale : 0);
            this.instanceMatrix.compose(this.instancePosition, this.instanceQuaternion, this.instanceScale);
            mesh.setMatrixAt(index, this.instanceMatrix);
            if (meshIndex === stateIndex) {
                mesh.setColorAt(index, this.color);
            }
        }
    }

    private markSphereNodeBatchDirty(batch: GalaxySphereNodeBatch): void {
        for (const mesh of batch.meshes) {
            mesh.instanceMatrix.needsUpdate = true;
            if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
        }
    }

    private writeGlowPoint(batch: GalaxyGlowBatch, index: number, x: number, y: number, z: number, size: number, alpha: number): void {
        const offset = index * 3;
        batch.positions[offset] = x;
        batch.positions[offset + 1] = y;
        batch.positions[offset + 2] = z;
        batch.colors[offset] = this.color.r;
        batch.colors[offset + 1] = this.color.g;
        batch.colors[offset + 2] = this.color.b;
        batch.sizes[index] = alpha > 0 ? size : 0;
        batch.alphas[index] = alpha;
    }

    private markGlowBatchDirty(batch: GalaxyGlowBatch): void {
        const geometry = batch.points.geometry;
        (geometry.getAttribute('position') as THREE.BufferAttribute).needsUpdate = true;
        (geometry.getAttribute('color') as THREE.BufferAttribute).needsUpdate = true;
        (geometry.getAttribute('aSize') as THREE.BufferAttribute).needsUpdate = true;
        (geometry.getAttribute('aAlpha') as THREE.BufferAttribute).needsUpdate = true;
    }

    private updateGlowViewport(): void {
        const batch = galaxyGlowBatch(this.glows);
        const height = this.renderer?.domElement.height || this.renderer?.domElement.clientHeight || 800;
        if (batch) batch.points.material.uniforms['viewportHeight'].value = Math.max(1, height);
    }

    private nodeDensityFactors(data: GalaxySceneV2, positions: Float32Array): Float32Array {
        const count = data.ids.length;
        if (this.densityFactors.length < count) this.densityFactors = new Float32Array(count);
        this.densityFactors.fill(1, 0, count);
        if (count < 2) return this.densityFactors;

        const renderer = this.renderer;
        const canvas = renderer?.domElement;
        const width = Math.max(1, canvas?.clientWidth || canvas?.width || 1);
        const height = Math.max(1, canvas?.clientHeight || canvas?.height || 1);
        const cellSize = 26;
        const cols = Math.max(1, Math.ceil(width / cellSize));
        const rows = Math.max(1, Math.ceil(height / cellSize));
        const binCount = cols * rows;
        if (this.densityBins.length < binCount) this.densityBins = new Uint16Array(binCount);
        if (this.densityNodeBins.length < count) this.densityNodeBins = new Int32Array(count);
        this.densityBins.fill(0, 0, binCount);
        this.densityNodeBins.fill(-1, 0, count);

        const camera = this.camera();
        for (let i = 0; i < count; i++) {
            const offset = i * 3;
            this.densityVector.set(positions[offset], positions[offset + 1], positions[offset + 2]).project(camera);
            if (this.densityVector.z < -1 || this.densityVector.z > 1) continue;
            const sx = (this.densityVector.x * 0.5 + 0.5) * width;
            const sy = (-this.densityVector.y * 0.5 + 0.5) * height;
            if (sx < 0 || sx >= width || sy < 0 || sy >= height) continue;
            const bin = Math.floor(sx / cellSize) + Math.floor(sy / cellSize) * cols;
            this.densityNodeBins[i] = bin;
            if (this.densityBins[bin] < 65535) this.densityBins[bin]++;
        }

        for (let i = 0; i < count; i++) {
            const bin = this.densityNodeBins[i];
            if (bin < 0) continue;
            const x = bin % cols;
            const y = Math.floor(bin / cols);
            let local = 0;
            for (let yy = Math.max(0, y - 1); yy <= Math.min(rows - 1, y + 1); yy++) {
                for (let xx = Math.max(0, x - 1); xx <= Math.min(cols - 1, x + 1); xx++) {
                    local += this.densityBins[xx + yy * cols];
                }
            }
            this.densityFactors[i] = THREE.MathUtils.clamp(1 / Math.sqrt(1 + Math.max(0, local - 1) * 0.42), 0.28, 1);
        }
        return this.densityFactors;
    }

    private updateEdgeGeometry(data: GalaxySceneV2, positions: Float32Array, focus: GalaxyFocusMask): void {
        if (!this.edges) return;
        const positionAttr = this.edges.geometry.getAttribute('position') as THREE.BufferAttribute;
        const colorAttr = this.edges.geometry.getAttribute('color') as THREE.BufferAttribute;
        positionAttr.array.fill(0);
        colorAttr.array.fill(0);
        let cursor = 0;
        const tubeMode = this.settings.edgeMode === 'tube';
        const treeFilaments = this.usesTreeFilamentEdges(data);
        const leanEdges = this.usesLeanEdgeContract(data);
        const baseSteps = tubeMode
            ? MAX_EDGE_SEGMENTS
            : this.settings.edgeMode === 'curved'
            ? (treeFilaments && !leanEdges ? TREE_FILAMENT_EDGE_SEGMENTS : leanEdges ? LEAN_CURVED_EDGE_SEGMENTS : CURVED_EDGE_SEGMENTS)
            : 1;
        for (let edge = 0; edge < data.edgePairs.length / 2; edge++) {
            const interGalaxy = data.edgeKinds[edge] === 1;
            const source = data.edgePairs[edge * 2];
            const target = data.edgePairs[edge * 2 + 1];
            const ax = positions[source * 3], ay = positions[source * 3 + 1], az = positions[source * 3 + 2];
            const bx = positions[target * 3], by = positions[target * 3 + 1], bz = positions[target * 3 + 2];
            const surfaceEdge = this.capsSurfaceEdge(data, ax, ay, az, bx, by, bz);
            const hopfEdge = !surfaceEdge && !tubeMode && this.mode === '3d' && data.layoutMode === 'hopfProjection' && this.settings.edgeMode === 'curved';
            const hopfCrossBase = hopfEdge && this.isHopfCrossBaseEdge(data, source, target);
            const steps = surfaceEdge
                ? (treeFilaments && !leanEdges ? TREE_FILAMENT_EDGE_SEGMENTS : leanEdges ? LEAN_CURVED_EDGE_SEGMENTS : CURVED_EDGE_SEGMENTS)
                : hopfEdge
                ? (hopfCrossBase ? (leanEdges ? LEAN_HOPF_CROSS_EDGE_SEGMENTS : HOPF_CROSS_EDGE_SEGMENTS) : (leanEdges ? LEAN_HOPF_EDGE_SEGMENTS : HOPF_EDGE_SEGMENTS))
                : baseSteps;
            const curveScale = THREE.MathUtils.clamp(this.settings.edgeCurveStrength, 0.25, 1.2) * (interGalaxy ? 0.92 : 0.58);
            const lift = tubeMode
                ? this.edgeTubeLift(data, edge, source, target)
                : this.settings.edgeMode === 'curved'
                ? treeFilaments
                    ? this.treeFilamentEdgeLift(data, edge, source, target, curveScale)
                    : (0.08 + Math.abs(source - target) * 0.002) * curveScale + (interGalaxy ? 0.18 : 0) + (hopfCrossBase ? 0.1 : 0)
                : 0;
            const dx = bx - ax;
            const dy = by - ay;
            const length = Math.hypot(dx, dy) || 1;
            const normalX = -dy / length;
            const normalY = dx / length;
            const strokes = this.edgeStrokeCount(data, edge);
            const strokeOffset = this.edgeStrokeOffset(data, edge);
            for (let stroke = 0; stroke < strokes; stroke++) {
                const side = stroke === 0 ? 0 : Math.ceil(stroke / 2) * (stroke % 2 === 0 ? -1 : 1);
                const ox = normalX * side * strokeOffset;
                const oy = normalY * side * strokeOffset;
                const tone = this.edgeStrokeTone(stroke, strokes);
                for (let step = 0; step < steps; step++) {
                    const t0 = step / steps;
                    const t1 = (step + 1) / steps;
                    if (surfaceEdge) {
                        cursor = this.writeCapsSurfaceEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax, ay, az, bx, by, bz, ox, oy, t0, tone);
                        cursor = this.writeCapsSurfaceEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax, ay, az, bx, by, bz, ox, oy, t1, tone);
                    } else if (tubeMode && treeFilaments) {
                        cursor = this.writeTreeTubeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax, ay, az, bx, by, bz, ox, oy, lift, t0, tone);
                        cursor = this.writeTreeTubeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax, ay, az, bx, by, bz, ox, oy, lift, t1, tone);
                    } else if (tubeMode) {
                        cursor = this.writeTubeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox, ay + oy, az, bx + ox, by + oy, bz, lift, t0, tone);
                        cursor = this.writeTubeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox, ay + oy, az, bx + ox, by + oy, bz, lift, t1, tone);
                    } else if (hopfEdge) {
                        cursor = this.writeHopfEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox, ay + oy, az, bx + ox, by + oy, bz, lift, t0, tone, hopfCrossBase);
                        cursor = this.writeHopfEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox, ay + oy, az, bx + ox, by + oy, bz, lift, t1, tone, hopfCrossBase);
                    } else if (treeFilaments) {
                        cursor = this.writeTreeFilamentEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax, ay, az, bx, by, bz, ox, oy, lift, t0, tone);
                        cursor = this.writeTreeFilamentEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax, ay, az, bx, by, bz, ox, oy, lift, t1, tone);
                    } else {
                        cursor = this.writeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox, ay + oy, az, bx + ox, by + oy, bz, lift, t0, tone);
                        cursor = this.writeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox, ay + oy, az, bx + ox, by + oy, bz, lift, t1, tone);
                    }
                }
            }
        }
        this.edges.geometry.setDrawRange(0, cursor);
        positionAttr.needsUpdate = true;
        colorAttr.needsUpdate = true;
        this.edges.geometry.computeBoundingSphere();
    }

    private updateEdgeColors(data: GalaxySceneV2, positions: Float32Array, focus: GalaxyFocusMask): void {
        if (!this.edges) return;
        const colorAttr = this.edges.geometry.getAttribute('color') as THREE.BufferAttribute;
        colorAttr.array.fill(0);
        let cursor = 0;
        const tubeMode = this.settings.edgeMode === 'tube';
        const treeFilaments = this.usesTreeFilamentEdges(data);
        const leanEdges = this.usesLeanEdgeContract(data);
        const baseSteps = tubeMode
            ? MAX_EDGE_SEGMENTS
            : this.settings.edgeMode === 'curved'
            ? (treeFilaments && !leanEdges ? TREE_FILAMENT_EDGE_SEGMENTS : leanEdges ? LEAN_CURVED_EDGE_SEGMENTS : CURVED_EDGE_SEGMENTS)
            : 1;
        for (let edge = 0; edge < data.edgePairs.length / 2; edge++) {
            const source = data.edgePairs[edge * 2];
            const target = data.edgePairs[edge * 2 + 1];
            const ax = positions[source * 3], ay = positions[source * 3 + 1], az = positions[source * 3 + 2];
            const bx = positions[target * 3], by = positions[target * 3 + 1], bz = positions[target * 3 + 2];
            const surfaceEdge = this.capsSurfaceEdge(data, ax, ay, az, bx, by, bz);
            const hopfEdge = !surfaceEdge && !tubeMode && this.mode === '3d' && data.layoutMode === 'hopfProjection' && this.settings.edgeMode === 'curved';
            const hopfCrossBase = hopfEdge && this.isHopfCrossBaseEdge(data, source, target);
            const steps = surfaceEdge
                ? (treeFilaments && !leanEdges ? TREE_FILAMENT_EDGE_SEGMENTS : leanEdges ? LEAN_CURVED_EDGE_SEGMENTS : CURVED_EDGE_SEGMENTS)
                : hopfEdge
                ? (hopfCrossBase ? (leanEdges ? LEAN_HOPF_CROSS_EDGE_SEGMENTS : HOPF_CROSS_EDGE_SEGMENTS) : (leanEdges ? LEAN_HOPF_EDGE_SEGMENTS : HOPF_EDGE_SEGMENTS))
                : baseSteps;
            const strokes = this.edgeStrokeCount(data, edge);
            for (let stroke = 0; stroke < strokes; stroke++) {
                const tone = this.edgeStrokeTone(stroke, strokes);
                for (let step = 0; step < steps; step++) {
                    this.writeEdgeColor(colorAttr, cursor++, data, focus, edge, step / steps, tone);
                    this.writeEdgeColor(colorAttr, cursor++, data, focus, edge, (step + 1) / steps, tone);
                }
            }
        }
        colorAttr.needsUpdate = true;
    }

    private isHopfCrossBaseEdge(data: GalaxySceneV2, source: number, target: number): boolean {
        if (data.layoutMode !== 'hopfProjection') return false;
        const sourceBase = data.hopfBaseIds?.[source] || '';
        const targetBase = data.hopfBaseIds?.[target] || '';
        return Boolean(sourceBase && targetBase && sourceBase !== targetBase);
    }

    private updateLabels(data: GalaxySceneV2, positions: Float32Array, force: boolean): void {
        const signature = this.labelSetSignature(data);
        if (!force && signature === this.labelSignature) return;
        this.labelSignature = signature;
        this.rebuildLabels(data, positions);
    }

    private labelSetSignature(data: GalaxySceneV2): string {
        if (this.settings.labelMode === 'off') return 'off';
        const selected = this.selectedId ? data.ids.indexOf(this.selectedId) : -1;
        const hovered = this.hoverId ? data.ids.indexOf(this.hoverId) : -1;
        return `${this.settings.labelMode}:${this.settings.labelLimit}:${data.ids.length}:${selected}:${hovered}`;
    }

    private rebuildLabels(data: GalaxySceneV2, positions: Float32Array): void {
        this.clearLabels();
        if (this.settings.labelMode === 'off') return;
        const limit = data.ids.length <= 18 ? data.ids.length : Math.max(1, this.settings.labelLimit);
        const important = [...data.ids.keys()].sort((a, b) => data.radii[b] - data.radii[a]).slice(0, limit);
        const selected = this.selectedId ? data.ids.indexOf(this.selectedId) : -1;
        const hovered = this.hoverId ? data.ids.indexOf(this.hoverId) : -1;
        const labelIndexes = new Set<number>();
        if (this.settings.labelMode === 'always' || this.settings.labelMode === 'important') {
            for (const index of important) labelIndexes.add(index);
        }
        if (selected >= 0) labelIndexes.add(selected);
        if (hovered >= 0) labelIndexes.add(hovered);
        for (const index of labelIndexes) {
            const active = index === selected || index === hovered;
            const sprite = makeLabelSprite(data.labels[index], active);
            sprite.position.set(positions[index * 3], positions[index * 3 + 1] + Math.max(0.11, data.radii[index] * 0.045), positions[index * 3 + 2]);
            sprite.scale.set(active ? 0.72 : 0.52, active ? 0.2 : 0.15, 1);
            this.labels.push(sprite);
            this.scene.add(sprite);
        }
    }

    private updateCamera(render = true): void {
        const target = this.cameraTarget.set(this.panX, this.panY, this.panZ);
        if (this.mode === '3d') {
            const x = target.x + Math.sin(this.yaw) * Math.cos(this.pitch) * this.distance;
            const y = target.y + Math.sin(this.pitch) * this.distance;
            const z = target.z + Math.cos(this.yaw) * Math.cos(this.pitch) * this.distance;
            this.perspective.position.set(x, y, z);
            this.perspective.lookAt(target);
            this.perspective.updateProjectionMatrix();
            this.applyViewShift(this.perspective);
            this.perspective.updateMatrixWorld();
        } else {
            this.ortho.position.set(target.x, target.y, this.distance);
            this.ortho.lookAt(target);
            this.ortho.zoom = THREE.MathUtils.clamp(8 / this.distance, 0.45, 3.5);
            this.ortho.updateProjectionMatrix();
            this.applyViewShift(this.ortho);
            this.ortho.updateMatrixWorld();
        }
        if (render) this.render();
    }

    private clearViewShift(): void {
        this.viewShiftX = 0;
        this.viewShiftY = 0;
    }

    private applyViewShift(camera: THREE.PerspectiveCamera | THREE.OrthographicCamera): void {
        if (this.viewShiftX === 0 && this.viewShiftY === 0) return;
        const matrix = camera.projectionMatrix.elements;
        if (camera instanceof THREE.PerspectiveCamera) {
            matrix[8] -= this.viewShiftX;
            matrix[9] -= this.viewShiftY;
        } else {
            matrix[12] += this.viewShiftX;
            matrix[13] += this.viewShiftY;
        }
        camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
    }

    private camera(): THREE.Camera {
        return this.mode === '3d' ? this.perspective : this.ortho;
    }

    private configureNodeDrag(pointer: GraphRendererPointer): boolean {
        if (!this.force.writeActivePosition(this.dragPlanePoint)) return false;
        this.camera().getWorldDirection(this.dragVector).normalize();
        this.dragPlane.setFromNormalAndCoplanarPoint(this.dragVector, this.dragPlanePoint);
        if (!this.pointerToDragPlane(pointer, this.dragHit)) {
            this.dragOffset.set(0, 0, 0);
            return true;
        }
        this.dragOffset.copy(this.dragPlanePoint).sub(this.dragHit);
        return true;
    }

    private pointerToDragPlane(pointer: GraphRendererPointer, out: THREE.Vector3): boolean {
        this.pointer.x = (pointer.x / Math.max(1, pointer.width)) * 2 - 1;
        this.pointer.y = -(pointer.y / Math.max(1, pointer.height)) * 2 + 1;
        this.raycaster.setFromCamera(this.pointer, this.camera());
        return Boolean(this.raycaster.ray.intersectPlane(this.dragPlane, out));
    }

    private pointerToCameraTargetPlane(pointer: GraphRendererPointer, out: THREE.Vector3): boolean {
        this.pointer.x = (pointer.x / Math.max(1, pointer.width)) * 2 - 1;
        this.pointer.y = -(pointer.y / Math.max(1, pointer.height)) * 2 + 1;
        this.camera().getWorldDirection(this.zoomNormal).normalize();
        this.zoomPlane.setFromNormalAndCoplanarPoint(this.zoomNormal, this.cameraTarget.set(this.panX, this.panY, this.panZ));
        this.raycaster.setFromCamera(this.pointer, this.camera());
        return Boolean(this.raycaster.ray.intersectPlane(this.zoomPlane, out));
    }

    private colorPart(data: GalaxySceneV2, index: number, channel: number): number {
        const value = data.colors[index * 3 + channel];
        const red = data.colors[index * 3];
        const green = data.colors[index * 3 + 1];
        const blue = data.colors[index * 3 + 2];
        if (!Number.isFinite(value) || red + green + blue <= 0.001) return [0.82, 0.36, 1][channel];
        return value;
    }

    private nodeColor(data: GalaxySceneV2, index: number): void {
        this.color.setRGB(this.colorPart(data, index, 0), this.colorPart(data, index, 1), this.colorPart(data, index, 2));
    }

    private glowColor(data: GalaxySceneV2, index: number): void {
        this.color.setRGB(this.colorPart(data, index, 0), this.colorPart(data, index, 1), this.colorPart(data, index, 2));
    }

    private applyMaterialSettings(): void {
        if (this.edges) {
            this.edges.visible = this.settings.edgeMode !== 'hidden';
            const material = this.edges.material as THREE.LineBasicMaterial;
            material.opacity = this.settings.edgeMode === 'hidden' ? 0 : this.edgeMaterialOpacity();
            material.linewidth = this.edgeMaterialWidth();
            material.needsUpdate = true;
        }
        const glowBatch = galaxyGlowBatch(this.glows);
        if (glowBatch) {
            glowBatch.points.material.needsUpdate = true;
        } else {
            this.glows?.children.forEach((child) => {
                const material = (child as THREE.Sprite).material;
                material.opacity = THREE.MathUtils.clamp(this.settings.glow * 0.2, 0, 0.34);
                material.needsUpdate = true;
            });
        }
        this.shells?.traverse((child) => {
            const drawable = child as THREE.Mesh | THREE.LineSegments;
            const material = drawable.material as THREE.Material | undefined;
            if (!material) return;
            const guideKind = child.userData['guideKind'];
            if (guideKind === 'hopf') {
                const weight = Number(child.userData['guideWeight'] ?? 1);
                const layer = String(child.userData['hopfLayer'] ?? 'line');
                const hopfGuideKind = child.userData['hopfGuideKind'] as GalaxyHopfRibbonView['guideKind'] | undefined;
                const surface = this.guideSurface(child);
                this.setGuideOpacity(material, this.hopfLayerOpacity(layer, hopfGuideKind, weight, surface));
            } else if (guideKind === 'lorentz') {
                const weight = Number(child.userData['guideWeight'] ?? 1);
                const layer = String(child.userData['lorentzLayer'] ?? 'line');
                const lorentzGuideKind = child.userData['lorentzGuideKind'] as GalaxyLorentzGuideView['guideKind'] | undefined;
                const treeKind = String(child.userData['treeKind'] ?? '');
                const surface = this.guideSurface(child);
                this.setGuideOpacity(material, this.lorentzLayerOpacity(layer, lorentzGuideKind, treeKind, weight, surface));
            } else if (guideKind === 'multi') {
                this.setGuideOpacity(material, this.multiShellOpacity());
            } else if (guideKind === 'hybrid-field') {
                // Field guides carry per-object opacity from Busemann receipts.
            } else {
                this.setGuideOpacity(material, this.hybridShellOpacity());
            }
            material.needsUpdate = true;
        });
        this.particles.updateSettings(this.settings);
    }

    private updateGuideFocus(data: GalaxySceneV2, focus: GalaxyFocusMask): void {
        this.shells?.traverse((child) => {
            if (child.userData['guideKind'] !== 'lorentz') return;
            const drawable = child as THREE.Mesh | THREE.LineSegments;
            const material = drawable.material as THREE.Material | undefined;
            if (!material) return;
            const surface = this.guideSurface(child);
            const layer = String(child.userData['lorentzLayer'] ?? 'line');
            const guideKind = child.userData['lorentzGuideKind'] as GalaxyLorentzGuideView['guideKind'] | undefined;
            const treeKind = String(child.userData['treeKind'] ?? '');
            const weight = Number(child.userData['guideWeight'] ?? 1);
            const baseOpacity = this.lorentzLayerOpacity(layer, guideKind, treeKind, weight, surface);
            const guides = child.userData['lorentzGuides'] as GalaxyLorentzGuideView[] | undefined;
            if (drawable instanceof THREE.LineSegments && Array.isArray(guides)) {
                this.updateLorentzGuideLineColors(drawable, guides, surface, focus, data);
                this.setGuideOpacity(material, baseOpacity);
            } else {
                const nodeIds = Array.isArray(child.userData['nodeIds']) ? child.userData['nodeIds'] as string[] : [];
                const focusScale = this.lorentzGuideFocusMultiplier(data, focus, nodeIds);
                this.setGuideOpacity(material, baseOpacity * focusScale);
            }
            material.needsUpdate = true;
        });
    }

    private updateLorentzGuideGeometry(data: GalaxySceneV2, positions: Float32Array): void {
        const contract = this.guideAttachmentContract(data);
        if (!contract.liveLorentzGuides || !this.shells) return;
        const indexById = this.nodeIndexById(data);
        const guidePositions = this.guidePositionsForContract(positions, contract);
        this.shells.traverse((child) => {
            if (child.userData['guideKind'] !== 'lorentz') return;
            const guides = child.userData['lorentzGuides'] as GalaxyLorentzGuideView[] | undefined;
            if (child instanceof THREE.LineSegments && Array.isArray(guides)) {
                this.updateLorentzGuideLinePositions(child, guides, data, guidePositions, indexById);
                return;
            }
            const guide = child.userData['lorentzGuide'] as GalaxyLorentzGuideView | undefined;
            const layer = child.userData['lorentzLayer'];
            if (!(child instanceof THREE.Mesh) || !guide || (layer !== 'tubeCore' && layer !== 'tubeGlow')) return;
            const points = this.lorentzGuidePath(guide, data, guidePositions, indexById);
            if (points.length < 4) return;
            const previous = child.geometry;
            const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.35);
            child.geometry = new THREE.TubeGeometry(curve, LORENTZ_TUBE_SEGMENTS, this.lorentzTubeRadius(guide, layer, this.guideSurface(child)), LORENTZ_TUBE_RADIAL_SEGMENTS, false);
            previous.dispose();
        });
    }

    private guideAttachmentContract(data: GalaxySceneV2): GuideAttachmentContract {
        if (isTransitLayoutMode(data.layoutMode)) {
            return {
                liveLorentzGuides: true,
                localScale: transitManifoldExpansionScale(this.settings),
            };
        }
        if (data.layoutMode === 'lorentzTree' || data.layoutMode === 'siegelFinsler') {
            return { liveLorentzGuides: true, localScale: 1 };
        }
        return { liveLorentzGuides: false, localScale: 1 };
    }

    private guidePositionsForContract(positions: Float32Array, contract: GuideAttachmentContract): Float32Array {
        if (Math.abs(contract.localScale - 1) < 0.0001) return positions;
        if (this.guidePositionBuffer.length !== positions.length) this.guidePositionBuffer = new Float32Array(positions.length);
        const scale = 1 / Math.max(0.0001, contract.localScale);
        for (let index = 0; index < positions.length; index++) this.guidePositionBuffer[index] = positions[index] * scale;
        return this.guidePositionBuffer;
    }

    private updateLorentzGuideLinePositions(
        line: THREE.LineSegments,
        guides: GalaxyLorentzGuideView[],
        data: GalaxySceneV2,
        positions: Float32Array,
        indexById: Map<string, number>,
    ): void {
        const positionAttr = line.geometry.getAttribute('position') as THREE.BufferAttribute | undefined;
        if (!positionAttr) return;
        const output = positionAttr.array as Float32Array;
        let cursor = 0;
        for (const guide of guides) {
            cursor = this.writeLorentzGuidePositions(output, cursor, guide, data, positions, indexById);
        }
        positionAttr.needsUpdate = true;
        line.geometry.computeBoundingSphere();
    }

    private writeLorentzGuidePositions(
        output: Float32Array,
        cursor: number,
        guide: GalaxyLorentzGuideView,
        data: GalaxySceneV2,
        positions: Float32Array,
        indexById: Map<string, number>,
    ): number {
        const sourceIndex = this.liveGuideNodeIndex(guide, data, indexById, 0);
        const targetIndex = this.liveGuideNodeIndex(guide, data, indexById, 1);
        if (guide.guideKind === 'rootLane' && this.usesTreeFilamentEdges(data)) {
            return this.writeSlantedRootLanePositions(output, cursor, guide);
        }
        if (guide.guideKind !== 'membership' || sourceIndex < 0 || targetIndex < 0) {
            output.set(guide.positions3d, cursor);
            return cursor + guide.positions3d.length;
        }
        const oldLast = guide.positions3d.length - 3;
        const oldAx = guide.positions3d[0], oldAy = guide.positions3d[1], oldAz = guide.positions3d[2];
        const oldBx = guide.positions3d[oldLast], oldBy = guide.positions3d[oldLast + 1], oldBz = guide.positions3d[oldLast + 2];
        const newA = sourceIndex * 3;
        const newB = targetIndex * 3;
        return this.writeReanchoredGuidePositions(
            output,
            cursor,
            guide.positions3d,
            oldAx, oldAy, oldAz,
            oldBx, oldBy, oldBz,
            positions[newA], positions[newA + 1], positions[newA + 2],
            positions[newB], positions[newB + 1], positions[newB + 2],
            this.usesTreeFilamentEdges(data),
        );
    }

    private writeReanchoredGuidePositions(
        output: Float32Array,
        cursor: number,
        source: Float32Array,
        oldAx: number, oldAy: number, oldAz: number,
        oldBx: number, oldBy: number, oldBz: number,
        newAx: number, newAy: number, newAz: number,
        newBx: number, newBy: number, newBz: number,
        terminalTaper = false,
    ): number {
        const segments = Math.floor(source.length / 6);
        if (segments < 1 || segments * 6 !== source.length) {
            output.set(source, cursor);
            return cursor + source.length;
        }
        const odx = oldBx - oldAx, ody = oldBy - oldAy, odz = oldBz - oldAz;
        const ndx = newBx - newAx, ndy = newBy - newAy, ndz = newBz - newAz;
        const oldLenSq = Math.max(0.000001, odx * odx + ody * ody + odz * odz);
        const offsetScale =
            THREE.MathUtils.clamp(Math.sqrt((ndx * ndx + ndy * ndy + ndz * ndz) / oldLenSq), 0.25, 1.65) * (terminalTaper ? 0.92 : 1);
        let liftX = 0, liftY = 0, liftZ = 0, weightSum = 0;
        for (let index = 0; index < source.length; index += 3) {
            const px = source[index], py = source[index + 1], pz = source[index + 2];
            const t = THREE.MathUtils.clamp(((px - oldAx) * odx + (py - oldAy) * ody + (pz - oldAz) * odz) / oldLenSq, 0, 1);
            const oldBaseX = oldAx + odx * t, oldBaseY = oldAy + ody * t, oldBaseZ = oldAz + odz * t;
            const weight = Math.sin(Math.PI * t);
            if (weight <= 0.000001) continue;
            liftX += (px - oldBaseX) * weight;
            liftY += (py - oldBaseY) * weight;
            liftZ += (pz - oldBaseZ) * weight;
            weightSum += weight;
        }
        const liftScale = weightSum > 0 ? offsetScale / weightSum : 0;
        liftX *= liftScale;
        liftY *= liftScale;
        liftZ *= liftScale;
        const cx = (newAx + newBx) * 0.5 + liftX * 2;
        const cy = (newAy + newBy) * 0.5 + liftY * 2;
        const cz = (newAz + newBz) * 0.5 + liftZ * 2;
        for (let segment = 0; segment < segments; segment++) {
            cursor = this.writeQuadraticGuidePoint(output, cursor, newAx, newAy, newAz, cx, cy, cz, newBx, newBy, newBz, segment / segments);
            cursor = this.writeQuadraticGuidePoint(output, cursor, newAx, newAy, newAz, cx, cy, cz, newBx, newBy, newBz, (segment + 1) / segments);
        }
        return cursor;
    }

    private writeQuadraticGuidePoint(
        output: Float32Array,
        cursor: number,
        ax: number, ay: number, az: number,
        cx: number, cy: number, cz: number,
        bx: number, by: number, bz: number,
        t: number,
    ): number {
        const left = (1 - t) * (1 - t);
        const mid = 2 * (1 - t) * t;
        const right = t * t;
        output[cursor++] = left * ax + mid * cx + right * bx;
        output[cursor++] = left * ay + mid * cy + right * by;
        output[cursor++] = left * az + mid * cz + right * bz;
        return cursor;
    }

    private writeSlantedRootLanePositions(output: Float32Array, cursor: number, guide: Pick<GalaxyLorentzGuideView, 'id' | 'positions3d'>): number {
        const seed = this.stableUnit(`root-lane-slant:${guide.id}`);
        const slope = 0.1 + seed * 0.08;
        const depthSlope = 0.025 + seed * 0.035;
        const phase = (seed - 0.5) * 0.12;
        for (let index = 0; index < guide.positions3d.length; index += 3) {
            const x = guide.positions3d[index];
            output[cursor++] = x;
            output[cursor++] = guide.positions3d[index + 1] + x * slope + phase;
            output[cursor++] = guide.positions3d[index + 2] + x * depthSlope;
        }
        return cursor;
    }

    private treeFilamentTerminalTaper(t: number): number {
        const start = THREE.MathUtils.smoothstep(t, 0.02, 0.16);
        const end = 1 - THREE.MathUtils.smoothstep(t, 0.58, 0.96);
        return THREE.MathUtils.clamp(start * end, 0, 1);
    }

    private nodeIndexById(data: GalaxySceneV2): Map<string, number> {
        const indexes = new Map<string, number>();
        for (let index = 0; index < data.ids.length; index++) indexes.set(data.ids[index], index);
        return indexes;
    }

    private liveGuideNodeIndex(guide: GalaxyLorentzGuideView, data: GalaxySceneV2, indexById: Map<string, number>, nodeOffset: number): number {
        const id = guide.nodeIds[nodeOffset];
        const index = id ? indexById.get(id) : undefined;
        return index !== undefined && index >= 0 && index < data.ids.length ? index : -1;
    }

    private updateLorentzGuideLineColors(
        line: THREE.LineSegments,
        guides: GalaxyLorentzGuideView[],
        surface: GuideSurface,
        focus: GalaxyFocusMask,
        data: GalaxySceneV2,
    ): void {
        const colorAttr = line.geometry.getAttribute('color') as THREE.BufferAttribute | undefined;
        if (!colorAttr) return;
        let cursor = 0;
        for (const [guideIndex, guide] of guides.entries()) {
            const focusScale = this.lorentzGuideFocusMultiplier(data, focus, guide.nodeIds);
            for (let source = 0; source < guide.positions3d.length; source += 3) {
                const phase = source / Math.max(3, guide.positions3d.length - 3);
                this.writeLorentzGuideColor(colorAttr.array as Float32Array, cursor, guide, guideIndex, phase, surface, focusScale);
                cursor += 3;
            }
        }
        colorAttr.needsUpdate = true;
    }

    private lorentzGuideFocusMultiplier(data: GalaxySceneV2, focus: GalaxyFocusMask, nodeIds: readonly string[]): number {
        if (!focus.hasFocus || focus.focusIndex < 0) return 1;
        const focusId = data.ids[focus.focusIndex];
        if (!focusId) return 1;
        if (!nodeIds.length) return 0.22;
        return nodeIds.includes(focusId) ? 1.18 : 0.12;
    }

    private setGuideOpacity(material: THREE.Material, opacity: number): void {
        const shader = material as THREE.ShaderMaterial;
        if (shader.uniforms?.['opacity']) {
            shader.uniforms['opacity'].value = opacity;
        } else {
            material.opacity = opacity;
        }
    }

    private guideSurface(object: THREE.Object3D): GuideSurface {
        const surface = object.userData['guideSurface'];
        return surface === 'transit' || surface === 'product' ? 'transit' : 'default';
    }

    private hybridShellOpacity(): number {
        if (!this.settings.hybridShellVisible) return 0;
        const shellOpacity = THREE.MathUtils.clamp(this.settings.hybridShellOpacity, 0, 1);
        const glow = THREE.MathUtils.clamp(this.settings.glow, 0, 1.8);
        return THREE.MathUtils.clamp(0.02 + glow * 0.004, 0.014, 0.032) * shellOpacity;
    }

    private multiShellOpacity(): number {
        if (!this.settings.hybridShellVisible) return 0;
        const shellOpacity = THREE.MathUtils.clamp(this.settings.hybridShellOpacity, 0, 1);
        const glow = THREE.MathUtils.clamp(this.settings.glow, 0, 1.8);
        return THREE.MathUtils.clamp(0.014 + glow * 0.003, 0.01, 0.026) * shellOpacity;
    }

    private edgeMaterialOpacity(): number {
        const glow = THREE.MathUtils.clamp(this.settings.glow, 0, 1.8);
        return Math.max(0.008, this.settings.edgeOpacity * (0.22 + glow * 0.085));
    }

    private edgeMaterialBlending(data: GalaxySceneV2 | null = this.sceneData): THREE.Blending {
        return THREE.NormalBlending;
    }

    private edgeMaterialWidth(): number {
        const glow = THREE.MathUtils.clamp(this.settings.glow, 0, 1.8);
        return Math.max(1, this.settings.edgeWidth * (0.58 + glow * 0.045));
    }

    private edgeStrokeCount(data?: EdgeStyleData, edge = 0): number {
        if (this.settings.edgeMode === 'hidden') return 1;
        if (this.usesLeanEdgeContract(data)) return this.leanEdgeStrokeCount();
        if (this.usesTreeFilamentEdges(data as GalaxySceneV2 | undefined)) {
            const signal = this.normalizedEdgeSignal(data, edge);
            const hierarchyBoost = data?.edgeKinds[edge] === 2 ? 1 : 0;
            const bridgeBoost = data?.edgeKinds[edge] === 1 ? 1 : 0;
            return THREE.MathUtils.clamp(3 + Math.round(signal * 1.8 + hierarchyBoost + bridgeBoost), 3, MAX_EDGE_STROKES);
        }
        if (this.settings.edgeMode === 'tube') {
            const confidence = THREE.MathUtils.clamp(data?.edgeAlpha[edge] ?? 0.45, 0.12, 1);
            const bridgeBoost = data?.edgeKinds[edge] === 1 ? 1 : 0;
            return THREE.MathUtils.clamp(2 + Math.round(this.settings.edgeWidth * 1.15 + confidence * 1.6 + bridgeBoost), 2, MAX_EDGE_STROKES);
        }
        const width = Math.max(0, this.settings.edgeWidth - 0.55);
        return THREE.MathUtils.clamp(1 + Math.round(width * 1.4), 1, MAX_EDGE_STROKES);
    }

    private edgeStrokeOffset(data?: EdgeStyleData, edge = 0): number {
        if (this.usesLeanEdgeContract(data)) return 0.0032 * Math.max(0, this.settings.edgeWidth - 0.55);
        if (this.usesTreeFilamentEdges(data as GalaxySceneV2 | undefined)) {
            const signal = this.normalizedEdgeSignal(data, edge);
            const hierarchyBoost = data?.edgeKinds[edge] === 2 ? 1.22 : data?.edgeKinds[edge] === 1 ? 1.14 : 1;
            return 0.0082 * hierarchyBoost * (0.72 + this.settings.edgeWidth * 0.42 + signal * 0.82);
        }
        if (this.settings.edgeMode === 'tube') {
            const confidence = THREE.MathUtils.clamp(data?.edgeAlpha[edge] ?? 0.45, 0.12, 1);
            const bridgeBoost = data?.edgeKinds[edge] === 1 ? 1.18 : 1;
            return 0.0022 * bridgeBoost * (0.65 + this.settings.edgeWidth * 0.55 + confidence * 0.52);
        }
        return 0.0032 * Math.max(0, this.settings.edgeWidth - 0.55);
    }

    private edgeStrokeTone(stroke: number, strokes: number): number {
        if (this.usesLeanEdgeContract()) return stroke === 0 ? 1 : 0.66;
        if (this.usesTreeFilamentEdges()) {
            if (stroke === 0) return 1.18;
            const ring = Math.ceil(stroke / 2);
            return THREE.MathUtils.clamp(0.78 - ring * 0.11 + strokes * 0.038, 0.44, 0.82);
        }
        if (this.settings.edgeMode !== 'tube') return 1;
        if (stroke === 0) return 1.08;
        const ring = Math.ceil(stroke / 2);
        return THREE.MathUtils.clamp(0.86 - ring * 0.18 + strokes * 0.02, 0.42, 0.88);
    }

    private leanEdgeStrokeCount(): number {
        const width = Math.max(0, this.settings.edgeWidth - 0.55);
        return THREE.MathUtils.clamp(1 + Math.round(width * 1.4), 1, LEAN_EDGE_STROKES);
    }

    private usesLeanEdgeContract(data: Partial<Pick<GalaxySceneV2, 'edgePairs'>> | null | undefined = this.sceneData): boolean {
        return this.settings.edgeMode === 'tube' || this.isDenseEdgeScene(data);
    }

    private isDenseEdgeScene(data: Partial<Pick<GalaxySceneV2, 'edgePairs'>> | null | undefined): boolean {
        const edgeCount = data?.edgePairs?.length ? data.edgePairs.length / 2 : 0;
        return edgeCount >= LEAN_EDGE_STYLE_THRESHOLD;
    }

    private usesTreeFilamentEdges(data: Pick<GalaxySceneV2, 'layoutMode'> | null | undefined = this.sceneData): boolean {
        return this.settings.edgeMode !== 'hidden' && Boolean(data && TREE_FILAMENT_EDGE_LAYOUTS.has(data.layoutMode));
    }

    private normalizedEdgeSignal(data?: Pick<GalaxySceneV2, 'edgeAlpha'>, edge = 0): number {
        const alpha = data?.edgeAlpha[edge] ?? 0.18;
        return THREE.MathUtils.clamp((alpha - 0.052) / 0.288, 0, 1);
    }

    private treeFilamentEdgeLift(data: Pick<GalaxySceneV2, 'edgeAlpha' | 'edgeKinds'>, edge: number, source: number, target: number, curveScale: number): number {
        const signal = this.normalizedEdgeSignal(data, edge);
        const span = Math.sqrt(Math.max(1, Math.abs(source - target)));
        const spanLift = THREE.MathUtils.clamp(span * 0.022, 0.045, 0.42);
        const kindBoost = data.edgeKinds[edge] === 1 ? 1.42 : data.edgeKinds[edge] === 2 ? 1.24 : 1;
        const signalBoost = 0.82 + signal * 0.55;
        return (0.11 + spanLift + signal * 0.14) * curveScale * kindBoost * signalBoost;
    }

    private rebuildNodeObjects(data: GalaxySceneV2): void {
        for (const group of [this.nodes, this.glows]) {
            if (!group) continue;
            this.scene.remove(group);
            group.traverse((child) => {
                const drawable = child as THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
                drawable.geometry?.dispose();
                const material = drawable.material;
                if (Array.isArray(material)) material.forEach((item) => item.dispose());
                else material?.dispose();
            });
        }
        this.nodes = buildGalaxyNodes(data, this.settings, this.nodeTexture, this.atomTexture);
        this.glows = buildGalaxyGlows(data, this.haloTexture);
        this.updateGlowViewport();
        if (this.glows) this.scene.add(this.glows);
        if (this.nodes) this.scene.add(this.nodes);
    }

    private buildGroupShells(scene: GalaxySceneV2): THREE.Group | null {
        if (scene.layoutMode === 'hybridSpace') return this.buildHybridGuides(scene);
        if (scene.layoutMode === 'hopfProjection') return this.buildHopfGuides(scene);
        if (scene.layoutMode === 'lorentzTree') return this.buildLorentzGuides(scene);
        if (scene.layoutMode === 'siegelFinsler') return this.buildLorentzGuides(scene);
        if (isTransitLayoutMode(scene.layoutMode)) return this.buildTransitGuides(scene);
        if (scene.layoutMode !== 'multiGalaxy' || scene.groups.length < 2) return null;
        const group = new THREE.Group();
        for (const shell of scene.groups) {
            const geometry = new THREE.SphereGeometry(shell.radius, 40, 20);
            const material = this.multiGlassMaterial(shell);
            const mesh = new THREE.Mesh(geometry, material);
            mesh.position.set(shell.center.x, shell.center.y, shell.center.z);
            mesh.userData['groupId'] = shell.id;
            mesh.userData['guideKind'] = 'multi';
            mesh.userData['pickable'] = false;
            group.add(mesh);
        }
        return group;
    }

    private multiGlassMaterial(shell: GalaxySceneGroupView): THREE.ShaderMaterial {
        const tint = new THREE.Color(shell.color.r, shell.color.g, shell.color.b);
        return new THREE.ShaderMaterial({
            uniforms: {
                coreColor: { value: new THREE.Color(0.055, 0.28, 0.255) },
                rimColor: { value: new THREE.Color(0.42, 1.0, 0.92) },
                depthColor: { value: new THREE.Color(0.58, 0.32, 1.0) },
                tintColor: { value: tint },
                opacity: { value: this.multiShellOpacity() },
            },
            vertexShader: `
                varying vec3 vNormal;
                varying vec3 vView;
                varying vec3 vWorld;
                void main() {
                    vec4 worldPosition = modelMatrix * vec4(position, 1.0);
                    vNormal = normalize(normalMatrix * normal);
                    vView = normalize(cameraPosition - worldPosition.xyz);
                    vWorld = worldPosition.xyz;
                    gl_Position = projectionMatrix * viewMatrix * worldPosition;
                }
            `,
            fragmentShader: `
                uniform vec3 coreColor;
                uniform vec3 rimColor;
                uniform vec3 depthColor;
                uniform vec3 tintColor;
                uniform float opacity;
                varying vec3 vNormal;
                varying vec3 vView;
                varying vec3 vWorld;
                void main() {
                    float rim = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.2);
                    float vertical = smoothstep(-1.65, 1.65, vWorld.y);
                    float latitude = 0.5 + 0.5 * sin(vWorld.y * 2.0);
                    vec3 base = mix(coreColor, depthColor, vertical * 0.42 + latitude * 0.12);
                    vec3 tinted = mix(base, tintColor, 0.16);
                    vec3 hue = mix(tinted, rimColor, smoothstep(0.22, 0.98, rim) * 0.72);
                    float glass = 0.12 + smoothstep(0.04, 0.92, rim) * 0.74;
                    gl_FragColor = vec4(hue, opacity * glass);
                }
            `,
            transparent: true,
            side: THREE.BackSide,
            depthWrite: false,
            depthTest: true,
            blending: THREE.NormalBlending,
            toneMapped: false,
        });
    }

    private buildHybridGuides(scene?: GalaxySceneV2): THREE.Group {
        const group = new THREE.Group();
        const outer = new THREE.Mesh(new THREE.SphereGeometry(2.32, 48, 24), this.hybridGlassMaterial());
        outer.userData['guideKind'] = 'hybrid';
        outer.userData['pickable'] = false;
        group.add(outer);
        if (scene?.layoutMode === 'hybridSpace') {
            const field = this.buildBusemannFieldGuides(scene.busemannHorospheres ?? []);
            if (field.children.length) group.add(field);
        }
        return group;
    }

    private buildBusemannFieldGuides(specs: GalaxyBusemannHorosphereView[]): THREE.Group {
        const group = new THREE.Group();
        if (!this.settings.hybridHorospheresVisible || !specs.length) return group;
        for (const spec of specs.slice(0, 36)) {
            const material = new THREE.LineBasicMaterial({
                color: new THREE.Color(spec.color.r, spec.color.g, spec.color.b),
                transparent: true,
                opacity: THREE.MathUtils.clamp(spec.opacity, 0, 0.16),
                depthWrite: false,
                depthTest: true,
                blending: THREE.NormalBlending,
                toneMapped: false,
            });
            const wire = new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.SphereGeometry(spec.radius, 28, 14)), material);
            wire.position.set(spec.center.x, spec.center.y, spec.center.z);
            wire.userData['guideKind'] = 'hybrid-field';
            wire.userData['pickable'] = false;
            group.add(wire);
        }
        if (this.settings.hybridPrototypeRaysVisible) {
            const rays = this.buildBusemannPrototypeRays(specs);
            if (rays) group.add(rays);
        }
        return group;
    }

    private buildBusemannPrototypeRays(specs: GalaxyBusemannHorosphereView[]): THREE.LineSegments | null {
        const seen = new Map<string, GalaxyBusemannHorosphereView>();
        for (const spec of specs) if (!seen.has(spec.prototypeId)) seen.set(spec.prototypeId, spec);
        if (!seen.size) return null;
        const positions = new Float32Array(seen.size * 2 * 3);
        const colors = new Float32Array(seen.size * 2 * 3);
        let cursor = 0;
        let colorCursor = 0;
        for (const spec of seen.values()) {
            const direction = this.fieldVector.set(spec.center.x, spec.center.y, spec.center.z).normalize().multiplyScalar(2.22);
            positions[cursor++] = 0;
            positions[cursor++] = 0;
            positions[cursor++] = 0;
            positions[cursor++] = direction.x;
            positions[cursor++] = direction.y;
            positions[cursor++] = direction.z;
            for (let i = 0; i < 2; i++) {
                colors[colorCursor++] = spec.color.r * (i ? 0.84 : 0.22);
                colors[colorCursor++] = spec.color.g * (i ? 0.84 : 0.22);
                colors[colorCursor++] = spec.color.b * (i ? 0.84 : 0.22);
            }
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        const material = new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: THREE.MathUtils.clamp((this.settings.hybridInteriorOpacity ?? 1) * 0.18, 0, 0.24),
            depthWrite: false,
            depthTest: true,
            blending: THREE.NormalBlending,
            toneMapped: false,
        });
        const rays = new THREE.LineSegments(geometry, material);
        rays.userData['guideKind'] = 'hybrid-field';
        rays.userData['pickable'] = false;
        return rays;
    }

    private buildTransitGuides(scene: GalaxySceneV2): THREE.Group {
        const group = new THREE.Group();
        const lorentz = this.buildLorentzGuides(scene, 'transit');
        if (lorentz.children.length) group.add(lorentz);
        return group;
    }

    private hybridGlassMaterial(): THREE.ShaderMaterial {
        return new THREE.ShaderMaterial({
            uniforms: {
                coreColor: { value: new THREE.Color(0.055, 0.28, 0.255) },
                rimColor: { value: new THREE.Color(0.42, 1.0, 0.92) },
                depthColor: { value: new THREE.Color(0.58, 0.32, 1.0) },
                opacity: { value: this.hybridShellOpacity() },
            },
            vertexShader: `
                varying vec3 vNormal;
                varying vec3 vView;
                varying vec3 vWorld;
                void main() {
                    vec4 worldPosition = modelMatrix * vec4(position, 1.0);
                    vNormal = normalize(normalMatrix * normal);
                    vView = normalize(cameraPosition - worldPosition.xyz);
                    vWorld = worldPosition.xyz;
                    gl_Position = projectionMatrix * viewMatrix * worldPosition;
                }
            `,
            fragmentShader: `
                uniform vec3 coreColor;
                uniform vec3 rimColor;
                uniform vec3 depthColor;
                uniform float opacity;
                varying vec3 vNormal;
                varying vec3 vView;
                varying vec3 vWorld;
                void main() {
                    float rim = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.25);
                    float vertical = smoothstep(-1.85, 1.85, vWorld.y);
                    float latitude = 0.5 + 0.5 * sin(vWorld.y * 2.25);
                    vec3 hue = mix(coreColor, depthColor, vertical * 0.5 + latitude * 0.18);
                    hue = mix(hue, rimColor, smoothstep(0.18, 0.95, rim));
                    float glass = 0.16 + smoothstep(0.05, 0.92, rim) * 0.84;
                    gl_FragColor = vec4(hue, opacity * glass);
                }
            `,
            transparent: true,
            side: THREE.BackSide,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            toneMapped: false,
        });
    }

    private buildLorentzGuides(scene: GalaxySceneV2, surface: GuideSurface = 'default'): THREE.Group {
        const group = new THREE.Group();
        const shells = this.buildLorentzGlassShells(scene.lorentzGuides, surface);
        if (shells) group.add(shells);
        const tubes = this.buildLorentzTubeLayer(scene.lorentzGuides, surface);
        if (tubes) group.add(tubes);
        const lines = this.buildLorentzGuideSegments(scene.lorentzGuides, surface);
        if (lines) group.add(lines);
        return group;
    }

    private buildLorentzGlassShells(guides: GalaxyLorentzGuideView[], surface: GuideSurface): THREE.Group | null {
        const shells = guides
            .filter((guide) => guide.guideKind === 'levelShell')
            .sort((left, right) => left.level - right.level)
            .slice(0, 7);
        if (!shells.length) return null;
        const group = new THREE.Group();
        for (const guide of shells) {
            const radius = this.lorentzShellRadius(guide);
            const geometry = new THREE.SphereGeometry(radius, 48, 24);
            const material = this.lorentzGlassMaterial(guide, surface);
            const mesh = new THREE.Mesh(geometry, material);
            mesh.userData['guideKind'] = 'lorentz';
            mesh.userData['guideSurface'] = surface;
            mesh.userData['lorentzGuideKind'] = guide.guideKind;
            mesh.userData['lorentzLayer'] = 'shell';
            mesh.userData['guideWeight'] = guide.guideWeight;
            mesh.userData['treeKind'] = guide.treeKind;
            mesh.userData['nodeIds'] = guide.nodeIds;
            mesh.userData['pickable'] = false;
            group.add(mesh);
        }
        return group.children.length ? group : null;
    }

    private lorentzGlassMaterial(guide: GalaxyLorentzGuideView, surface: GuideSurface): THREE.ShaderMaterial {
        const tint = this.lorentzGuideTint(guide, 0, surface);
        return new THREE.ShaderMaterial({
            uniforms: {
                color: { value: new THREE.Color(tint.r, tint.g, tint.b) },
                opacity: { value: this.lorentzLayerOpacity('shell', guide.guideKind, guide.treeKind, guide.guideWeight, surface) },
            },
            vertexShader: `
                varying vec3 vNormal;
                varying vec3 vView;
                void main() {
                    vec4 worldPosition = modelMatrix * vec4(position, 1.0);
                    vNormal = normalize(normalMatrix * normal);
                    vView = normalize(cameraPosition - worldPosition.xyz);
                    gl_Position = projectionMatrix * viewMatrix * worldPosition;
                }
            `,
            fragmentShader: `
                uniform vec3 color;
                uniform float opacity;
                varying vec3 vNormal;
                varying vec3 vView;
                void main() {
                    float rim = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.1);
                    float breath = smoothstep(0.08, 0.96, rim);
                    gl_FragColor = vec4(color, opacity * (0.18 + breath * 0.82));
                }
            `,
            transparent: true,
            side: THREE.BackSide,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            toneMapped: false,
        });
    }

    private buildLorentzTubeLayer(guides: GalaxyLorentzGuideView[], surface: GuideSurface): THREE.Group | null {
        const lanes = guides
            .filter((guide) => guide.guideKind === 'membership' || guide.guideKind === 'rootLane')
            .sort((left, right) => right.importance - left.importance || left.id.localeCompare(right.id))
            .slice(0, MAX_LORENTZ_TUBES);
        if (!lanes.length) return null;
        const group = new THREE.Group();
        for (const [index, guide] of lanes.entries()) {
            const glow = this.buildLorentzTubeMesh(guide, index, 'tubeGlow', surface);
            const core = this.buildLorentzTubeMesh(guide, index, 'tubeCore', surface);
            if (glow) group.add(glow);
            if (core) group.add(core);
        }
        return group.children.length ? group : null;
    }

    private buildLorentzTubeMesh(guide: GalaxyLorentzGuideView, index: number, layer: 'tubeCore' | 'tubeGlow', surface: GuideSurface): THREE.Mesh | null {
        const points = this.lorentzGuidePath(guide);
        if (points.length < 4) return null;
        const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.35);
        const geometry = new THREE.TubeGeometry(curve, LORENTZ_TUBE_SEGMENTS, this.lorentzTubeRadius(guide, layer, surface), LORENTZ_TUBE_RADIAL_SEGMENTS, false);
        const tint = this.lorentzGuideTint(guide, index, surface);
        const material = new THREE.MeshBasicMaterial({
            color: new THREE.Color(tint.r, tint.g, tint.b),
            transparent: true,
            opacity: this.lorentzLayerOpacity(layer, guide.guideKind, guide.treeKind, guide.guideWeight, surface),
            depthWrite: false,
            depthTest: true,
            blending: THREE.NormalBlending,
            toneMapped: false,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData['guideKind'] = 'lorentz';
        mesh.userData['guideSurface'] = surface;
        mesh.userData['lorentzGuideKind'] = guide.guideKind;
        mesh.userData['lorentzLayer'] = layer;
        mesh.userData['guideWeight'] = guide.guideWeight;
        mesh.userData['treeKind'] = guide.treeKind;
        mesh.userData['nodeIds'] = guide.nodeIds;
        mesh.userData['lorentzGuide'] = guide;
        mesh.userData['pickable'] = false;
        return mesh;
    }

    private buildLorentzGuideSegments(guides: GalaxyLorentzGuideView[], surface: GuideSurface): THREE.Group | null {
        const visible = guides.slice(0, MAX_LORENTZ_GUIDES);
        if (!visible.length) return null;
        const grouped = new Map<GalaxyLorentzGuideView['guideKind'], GalaxyLorentzGuideView[]>();
        for (const guide of visible) {
            const group = grouped.get(guide.guideKind) ?? [];
            group.push(guide);
            grouped.set(guide.guideKind, group);
        }
        const result = new THREE.Group();
        for (const [guideKind, groupGuides] of grouped) {
            const line = this.buildLorentzGuideLine(groupGuides, guideKind, surface);
            if (line) result.add(line);
        }
        return result.children.length ? result : null;
    }

    private buildLorentzGuideLine(guides: GalaxyLorentzGuideView[], guideKind: GalaxyLorentzGuideView['guideKind'], surface: GuideSurface): THREE.LineSegments | null {
        const vertexCount = guides.reduce((total, guide) => total + guide.positions3d.length / 3, 0);
        if (!vertexCount) return null;
        const positions = new Float32Array(vertexCount * 3);
        const colors = new Float32Array(vertexCount * 3);
        let cursor = 0;
        for (const [guideIndex, guide] of guides.entries()) {
            for (let source = 0; source < guide.positions3d.length; source += 3) {
                const phase = source / Math.max(3, guide.positions3d.length - 3);
                positions[cursor] = guide.positions3d[source];
                positions[cursor + 1] = guide.positions3d[source + 1];
                positions[cursor + 2] = guide.positions3d[source + 2];
                this.writeLorentzGuideColor(colors, cursor, guide, guideIndex, phase, surface);
                cursor += 3;
            }
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        const material = new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: this.lorentzLayerOpacity('line', guideKind, guides[0]?.treeKind, this.lorentzGuideWeightForKind(guideKind), surface),
            depthWrite: false,
            depthTest: true,
            blending: THREE.NormalBlending,
            toneMapped: false,
        });
        const line = new THREE.LineSegments(geometry, material);
        line.userData['guideKind'] = 'lorentz';
        line.userData['guideSurface'] = surface;
        line.userData['lorentzGuideKind'] = guideKind;
        line.userData['lorentzLayer'] = 'line';
        line.userData['guideWeight'] = this.lorentzGuideWeightForKind(guideKind);
        line.userData['treeKind'] = guides[0]?.treeKind ?? '';
        line.userData['lorentzGuides'] = guides;
        line.userData['pickable'] = false;
        return line;
    }

    private buildHopfGuides(scene: GalaxySceneV2, surface: GuideSurface = 'default'): THREE.Group {
        const group = new THREE.Group();
        const tubes = this.buildHopfTubeLayer(scene.hopfRibbons, surface);
        if (tubes) group.add(tubes);
        const ribbons = this.buildHopfRibbonSegments(scene.hopfRibbons, surface);
        if (ribbons) group.add(ribbons);
        return group;
    }

    private buildHopfTubeLayer(ribbons: GalaxyHopfRibbonView[], surface: GuideSurface): THREE.Group | null {
        if (!ribbons.length) return null;
        const group = new THREE.Group();
        const dataFibers = ribbons
            .filter((ribbon) => ribbon.guideKind === 'dataFiber')
            .sort((left, right) => right.importance - left.importance)
            .slice(0, MAX_HOPF_DATA_TUBES);
        const torusFibers = ribbons
            .filter((ribbon) => ribbon.guideKind === 'torusBand')
            .filter((_, index) => index % 3 === 0)
            .slice(0, MAX_HOPF_TORUS_TUBES);
        for (const [index, ribbon] of dataFibers.entries()) {
            const glow = this.buildHopfTubeMesh(ribbon, index, 'tubeGlow', surface);
            const core = this.buildHopfTubeMesh(ribbon, index, 'tubeCore', surface);
            if (glow) group.add(glow);
            if (core) group.add(core);
        }
        if (surface === 'default') {
            for (const [index, ribbon] of torusFibers.entries()) {
                const glow = this.buildHopfTubeMesh(ribbon, index, 'tubeGlow', surface);
                const core = this.buildHopfTubeMesh(ribbon, index, 'tubeCore', surface);
                if (glow) group.add(glow);
                if (core) group.add(core);
            }
        }
        return group.children.length ? group : null;
    }

    private buildHopfTubeMesh(ribbon: GalaxyHopfRibbonView, index: number, layer: 'tubeCore' | 'tubeGlow', surface: GuideSurface): THREE.Mesh | null {
        const points = this.hopfRibbonPath(ribbon);
        if (points.length < 4) return null;
        const closed = ribbon.guideKind !== 'crossFiberBraid';
        const curve = new THREE.CatmullRomCurve3(points, closed, 'centripetal', 0.45);
        const radius = this.hopfTubeRadius(ribbon.guideKind, layer, surface);
        const geometry = new THREE.TubeGeometry(curve, HOPF_TUBE_SEGMENTS, radius, HOPF_TUBE_RADIAL_SEGMENTS, closed);
        const tint = this.hopfRibbonTint(ribbon, index, surface);
        const material = new THREE.MeshBasicMaterial({
            color: new THREE.Color(tint.r, tint.g, tint.b),
            transparent: true,
            opacity: this.hopfLayerOpacity(layer, ribbon.guideKind, this.hopfGuideWeightForKind(ribbon.guideKind, surface), surface),
            depthWrite: false,
            depthTest: true,
            blending: surface === 'transit' ? THREE.NormalBlending : THREE.AdditiveBlending,
            toneMapped: false,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData['guideKind'] = 'hopf';
        mesh.userData['guideSurface'] = surface;
        mesh.userData['hopfGuideKind'] = ribbon.guideKind;
        mesh.userData['hopfLayer'] = layer;
        mesh.userData['guideWeight'] = this.hopfGuideWeightForKind(ribbon.guideKind, surface);
        mesh.userData['pickable'] = false;
        return mesh;
    }

    private hopfRibbonPath(ribbon: GalaxyHopfRibbonView): THREE.Vector3[] {
        const segmentCount = Math.floor(ribbon.positions3d.length / 6);
        if (segmentCount < 2) return [];
        const stride = Math.max(1, Math.floor(segmentCount / 72));
        const points: THREE.Vector3[] = [];
        for (let segment = 0; segment < segmentCount; segment += stride) {
            const offset = segment * 6;
            points.push(new THREE.Vector3(
                ribbon.positions3d[offset],
                ribbon.positions3d[offset + 1],
                ribbon.positions3d[offset + 2],
            ));
        }
        if (ribbon.guideKind === 'crossFiberBraid') {
            const offset = (segmentCount - 1) * 6 + 3;
            points.push(new THREE.Vector3(
                ribbon.positions3d[offset],
                ribbon.positions3d[offset + 1],
                ribbon.positions3d[offset + 2],
            ));
        }
        return points;
    }

    private buildHopfRibbonSegments(ribbons: GalaxyHopfRibbonView[], surface: GuideSurface): THREE.Group | null {
        if (!ribbons.length) return null;
        const visible = this.sortedHopfRibbons(ribbons, surface).slice(0, MAX_HOPF_RIBBON_GUIDES);
        const grouped = new Map<GalaxyHopfRibbonView['guideKind'], GalaxyHopfRibbonView[]>();
        for (const ribbon of visible) {
            const group = grouped.get(ribbon.guideKind) ?? [];
            group.push(ribbon);
            grouped.set(ribbon.guideKind, group);
        }
        const result = new THREE.Group();
        for (const [guideKind, groupRibbons] of grouped) {
            const line = this.buildHopfRibbonLine(groupRibbons, guideKind, surface);
            if (line) result.add(line);
        }
        return result.children.length ? result : null;
    }

    private sortedHopfRibbons(ribbons: GalaxyHopfRibbonView[], surface: GuideSurface): GalaxyHopfRibbonView[] {
        if (surface === 'default') return ribbons;
        const rank = (kind: GalaxyHopfRibbonView['guideKind']) =>
            kind === 'dataFiber' ? 0 : kind === 'crossFiberBraid' ? 1 : kind === 'torusBand' ? 2 : kind === 'spaceFiber' ? 3 : 4;
        return [...ribbons].sort((left, right) => rank(left.guideKind) - rank(right.guideKind) || right.importance - left.importance);
    }

    private buildHopfRibbonLine(ribbons: GalaxyHopfRibbonView[], guideKind: GalaxyHopfRibbonView['guideKind'], surface: GuideSurface): THREE.LineSegments | null {
        const plans = ribbons
            .map((ribbon) => ({
                ribbon,
                points: this.hopfRibbonPath(ribbon),
                segmentCount: this.hopfRibbonLineSegmentCount(ribbon),
                closed: ribbon.guideKind !== 'crossFiberBraid',
            }))
            .filter((plan) => plan.points.length >= 2 && plan.segmentCount > 0);
        if (!plans.length) return null;

        const vertexCount = plans.reduce((total, plan) => total + plan.segmentCount * 2, 0);
        const positions = new Float32Array(vertexCount * 3);
        const colors = new Float32Array(vertexCount * 3);
        let cursor = 0;
        for (const [ribbonIndex, plan] of plans.entries()) {
            const curve = new THREE.CatmullRomCurve3(plan.points, plan.closed, 'centripetal', plan.closed ? 0.45 : 0.35);
            for (let segment = 0; segment < plan.segmentCount; segment++) {
                const startPhase = segment / plan.segmentCount;
                const endPhase = (segment + 1) / plan.segmentCount;
                const start = curve.getPoint(startPhase);
                const end = curve.getPoint(endPhase);
                positions[cursor] = start.x;
                positions[cursor + 1] = start.y;
                positions[cursor + 2] = start.z;
                this.writeHopfRibbonColor(colors, cursor, plan.ribbon, ribbonIndex, startPhase, surface);
                cursor += 3;
                positions[cursor] = end.x;
                positions[cursor + 1] = end.y;
                positions[cursor + 2] = end.z;
                this.writeHopfRibbonColor(colors, cursor, plan.ribbon, ribbonIndex, endPhase, surface);
                cursor += 3;
            }
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        const material = new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: this.hopfGuideOpacity(this.hopfGuideWeightForKind(guideKind, surface), guideKind, surface),
            depthWrite: false,
            depthTest: true,
            blending: surface === 'transit' ? THREE.NormalBlending : THREE.AdditiveBlending,
            toneMapped: false,
        });
        const line = new THREE.LineSegments(geometry, material);
        line.userData['guideKind'] = 'hopf';
        line.userData['guideSurface'] = surface;
        line.userData['guideWeight'] = this.hopfGuideWeightForKind(guideKind, surface);
        line.userData['hopfGuideKind'] = guideKind;
        line.userData['hopfLayer'] = 'line';
        line.userData['pickable'] = false;
        return line;
    }

    private hopfRibbonLineSegmentCount(ribbon: GalaxyHopfRibbonView): number {
        const sourceSegments = Math.floor(ribbon.positions3d.length / 6);
        const targetSegments = ribbon.guideKind === 'crossFiberBraid' ? HOPF_CROSS_BAND_LINE_SEGMENTS : HOPF_LINE_SEGMENTS;
        return Math.max(2, Math.min(HOPF_LINE_SEGMENT_LIMIT, Math.max(sourceSegments, targetSegments)));
    }

    private hopfRibbonTint(ribbon: GalaxyHopfRibbonView, index: number, surface: GuideSurface): { r: number; g: number; b: number } {
        const sourceColor = this.guideSourceColor(ribbon, surface);
        if (sourceColor) return sourceColor;
        const palette = this.hopfRibbonPalette(ribbon, index, 0.35, surface);
        return this.hslColor(palette.h, palette.s, palette.l);
    }

    private writeHopfRibbonColor(colors: Float32Array, offset: number, ribbon: GalaxyHopfRibbonView, index: number, phase: number, surface: GuideSurface): void {
        const sourceColor = this.guideSourceColor(ribbon, surface);
        if (sourceColor) {
            // Lane/route guides keep their own style color; per-node guides may inherit source color.
            colors[offset] = sourceColor.r;
            colors[offset + 1] = sourceColor.g;
            colors[offset + 2] = sourceColor.b;
            return;
        }
        const palette = this.hopfRibbonPalette(ribbon, index, phase, surface);
        this.writeHslColor(colors, offset, palette.h, palette.s, palette.l);
        if (ribbon.guideKind === 'dataFiber' || ribbon.guideKind === 'crossFiberBraid') {
            const mix = surface === 'transit' ? 0.44 : 0.2;
            colors[offset] = THREE.MathUtils.lerp(colors[offset], ribbon.color.r, mix);
            colors[offset + 1] = THREE.MathUtils.lerp(colors[offset + 1], ribbon.color.g, mix);
            colors[offset + 2] = THREE.MathUtils.lerp(colors[offset + 2], ribbon.color.b, mix);
        }
    }

    private hopfRibbonPalette(ribbon: GalaxyHopfRibbonView, index: number, phase: number, surface: GuideSurface): { h: number; s: number; l: number } {
        const seed = this.stableUnit(ribbon.id);
        if (surface === 'transit') {
            switch (ribbon.guideKind) {
                case 'dataFiber':
                    return { h: 0.48 + seed * 0.26 + phase * 0.04, s: 0.8, l: 0.52 + Math.sin(phase * Math.PI) * 0.047 };
                case 'crossFiberBraid':
                    return { h: 0.5 + seed * 0.22 + phase * 0.035, s: 0.64, l: 0.38 };
                case 'torusBand': {
                    const latitude = this.torusBandIndex(ribbon.id);
                    return { h: 0.62 + latitude * 0.036 + seed * 0.012, s: 0.48, l: 0.2 };
                }
                case 'spaceFiber':
                    return { h: 0.58 + seed * 0.08, s: 0.36, l: 0.17 + (index % 2) * 0.018 };
                case 'axis':
                    return { h: 0.52, s: 0.58, l: 0.26 };
            }
        }
        switch (ribbon.guideKind) {
            case 'dataFiber':
                return { h: 0.5 + seed * 0.3 + phase * 0.055, s: 0.68, l: 0.47 + Math.sin(phase * Math.PI) * 0.05 };
            case 'crossFiberBraid':
                return { h: 0.5 + seed * 0.24 + phase * 0.04, s: 0.58, l: 0.36 + Math.sin(phase * Math.PI) * 0.024 };
            case 'torusBand': {
                const latitude = this.torusBandIndex(ribbon.id);
                return { h: 0.62 + latitude * 0.045 + seed * 0.018 + phase * 0.025, s: 0.64, l: 0.34 };
            }
            case 'spaceFiber':
                return { h: 0.46 + seed * 0.12 + phase * 0.018, s: 0.48, l: 0.25 + (index % 2) * 0.025 };
            case 'axis':
                return { h: 0.52 + phase * 0.02, s: 0.74, l: 0.42 };
        }
    }

    private hopfGuideOpacity(weight = 1, kind?: GalaxyHopfRibbonView['guideKind'], surface: GuideSurface = 'default'): number {
        // Legacy hopfSpaceVisible stays as the master switch; guideFibersVisible
        // is the dedicated per-family override (defaults visible via mergeGalaxySettings).
        if (!this.settings.hopfSpaceVisible) return 0;
        if (this.settings.guideFibersVisible === false) return 0;
        const intensity = THREE.MathUtils.clamp(this.settings.hopfSpaceIntensity, 0, 1.4);
        if (surface === 'transit') {
            const data = kind === 'dataFiber';
            const braid = kind === 'crossFiberBraid';
            if (braid) return THREE.MathUtils.clamp((0.018 + this.settings.glow * 0.007) * weight * intensity, 0, 0.052);
            const base = data ? 0.036 + this.settings.glow * 0.0215 : 0.0105 + this.settings.glow * 0.005;
            return THREE.MathUtils.clamp(base * weight * intensity, 0, data ? 0.13 : 0.032);
        }
        if (kind === 'crossFiberBraid') return THREE.MathUtils.clamp((0.018 + this.settings.glow * 0.009) * weight * intensity, 0, 0.07);
        return THREE.MathUtils.clamp((0.035 + this.settings.glow * 0.024) * weight * intensity, 0, 0.16);
    }

    private hopfLayerOpacity(layer: string, kind: GalaxyHopfRibbonView['guideKind'] | undefined, weight = 1, surface: GuideSurface = 'default'): number {
        if (!this.settings.hopfSpaceVisible) return 0;
        if (layer === 'tubeCore') return this.hopfTubeOpacity(kind, false, surface);
        if (layer === 'tubeGlow') return this.hopfTubeOpacity(kind, true, surface);
        return this.hopfGuideOpacity(weight, kind, surface);
    }

    private hopfTubeOpacity(kind: GalaxyHopfRibbonView['guideKind'] | undefined, glow: boolean, surface: GuideSurface): number {
        const intensity = THREE.MathUtils.clamp(this.settings.hopfSpaceIntensity, 0, 1.4);
        const globalGlow = THREE.MathUtils.clamp(this.settings.glow, 0, 1.8);
        if (surface === 'transit') {
            if (kind === 'dataFiber') {
                return THREE.MathUtils.clamp((glow ? 0.0325 : 0.112) * intensity * (0.78 + globalGlow * 0.24), 0, glow ? 0.052 : 0.168);
            }
            return 0;
        }
        if (kind === 'dataFiber') {
            return THREE.MathUtils.clamp((glow ? 0.03 : 0.12) * intensity * (0.76 + globalGlow * 0.24), 0, glow ? 0.055 : 0.22);
        }
        if (kind === 'crossFiberBraid') return 0;
        if (kind === 'torusBand') {
            return THREE.MathUtils.clamp((glow ? 0.012 : 0.045) * intensity * (0.8 + globalGlow * 0.18), 0, glow ? 0.026 : 0.085);
        }
        return 0;
    }

    private hopfTubeRadius(kind: GalaxyHopfRibbonView['guideKind'], layer: 'tubeCore' | 'tubeGlow', surface: GuideSurface): number {
        if (surface === 'transit') {
            if (kind === 'dataFiber') return (layer === 'tubeGlow' ? 0.0216 : 0.00675) * TRANSIT_HOPF_TUBE_SCALE;
            return 0.002;
        }
        if (kind === 'dataFiber') return layer === 'tubeGlow' ? 0.012 : 0.0055;
        if (kind === 'torusBand') return layer === 'tubeGlow' ? 0.008 : 0.0038;
        return 0.003;
    }

    private hopfGuideWeightForKind(kind: GalaxyHopfRibbonView['guideKind'], surface: GuideSurface = 'default'): number {
        if (surface === 'transit') {
            switch (kind) {
                case 'dataFiber':
                    return 1.58;
                case 'crossFiberBraid':
                    return 0.38;
                case 'spaceFiber':
                    return 0.16;
                case 'torusBand':
                    return 0.18;
                case 'axis':
                    return 0.1;
            }
        }
        switch (kind) {
            case 'dataFiber':
                return 1.22;
            case 'crossFiberBraid':
                return 0.56;
            case 'spaceFiber':
                return 0.34;
            case 'torusBand':
                return 0.54;
            case 'axis':
                return 0.24;
        }
    }

    private lorentzGuidePath(
        guide: GalaxyLorentzGuideView,
        data?: GalaxySceneV2,
        positions?: Float32Array,
        indexById?: Map<string, number>,
    ): THREE.Vector3[] {
        const segmentCount = Math.floor(guide.positions3d.length / 6);
        if (segmentCount < 2) return [];
        const pathSource = data && positions && indexById && guide.guideKind === 'membership'
            ? this.reanchoredLorentzGuidePositions(guide, data, positions, indexById)
            : guide.positions3d;
        const stride = Math.max(1, Math.floor(segmentCount / 40));
        const points: THREE.Vector3[] = [];
        points.push(new THREE.Vector3(pathSource[0], pathSource[1], pathSource[2]));
        for (let segment = 0; segment < segmentCount; segment += stride) {
            const offset = segment * 6 + 3;
            points.push(new THREE.Vector3(
                pathSource[offset],
                pathSource[offset + 1],
                pathSource[offset + 2],
            ));
        }
        const lastOffset = pathSource.length - 3;
        points.push(new THREE.Vector3(pathSource[lastOffset], pathSource[lastOffset + 1], pathSource[lastOffset + 2]));
        return points;
    }

    private reanchoredLorentzGuidePositions(
        guide: GalaxyLorentzGuideView,
        data: GalaxySceneV2,
        positions: Float32Array,
        indexById: Map<string, number>,
    ): Float32Array {
        const output = new Float32Array(guide.positions3d.length);
        this.writeLorentzGuidePositions(output, 0, guide, data, positions, indexById);
        return output;
    }

    private writeLorentzGuideColor(
        colors: Float32Array,
        offset: number,
        guide: GalaxyLorentzGuideView,
        index: number,
        phase: number,
        surface: GuideSurface,
        focusScale = 1,
    ): void {
        const sourceColor = this.guideSourceColor(guide, surface);
        if (sourceColor) {
            colors[offset] = sourceColor.r;
            colors[offset + 1] = sourceColor.g;
            colors[offset + 2] = sourceColor.b;
            return;
        }
        const pulse = Math.sin((phase + this.stableUnit(guide.id)) * Math.PI) * 0.08;
        const level = Number.isFinite(guide.level) ? guide.level : 0;
        const levelShade = THREE.MathUtils.clamp(0.08 - level * 0.012, -0.04, 0.08);
        const base = guide.color;
        colors[offset] = THREE.MathUtils.clamp(base.r * (0.58 + pulse + levelShade), 0, 0.78);
        colors[offset + 1] = THREE.MathUtils.clamp(base.g * (0.62 + pulse + levelShade), 0, 0.84);
        colors[offset + 2] = THREE.MathUtils.clamp(base.b * (0.66 + pulse + levelShade), 0, 0.86);
        if (guide.guideKind === 'wAxis') {
            colors[offset] = THREE.MathUtils.clamp(0.16 + index * 0.002, 0, 0.42);
            colors[offset + 1] = 0.74;
            colors[offset + 2] = 0.82;
        }
        if (focusScale !== 1) {
            colors[offset] = THREE.MathUtils.clamp(colors[offset] * focusScale, 0, 0.78);
            colors[offset + 1] = THREE.MathUtils.clamp(colors[offset + 1] * focusScale, 0, 0.84);
            colors[offset + 2] = THREE.MathUtils.clamp(colors[offset + 2] * focusScale, 0, 0.86);
        }
    }

    private guideSourceColor(guide: { id?: string; sourceColor?: { r: number; g: number; b: number } }, surface: GuideSurface = 'default'): { r: number; g: number; b: number } | undefined {
        if (surface === 'transit' && this.isTransitLaneOrRouteGuide(guide)) return undefined;
        return guide.sourceColor;
    }

    private isTransitLaneOrRouteGuide(guide: { id?: string }): boolean {
        const id = String(guide.id || '');
        return id.startsWith('transit:backbone:lane:')
            || id.startsWith('transit:backbone:route:')
            || id.startsWith('transit:plan:lane:')
            || id.startsWith('transit:plan:route:');
    }

    private lorentzGuideTint(guide: GalaxyLorentzGuideView, index: number, surface: GuideSurface = 'default'): { r: number; g: number; b: number } {
        const sourceColor = this.guideSourceColor(guide, surface);
        if (sourceColor) return sourceColor;
        const tintBase = guide.color;
        const offset = this.stableUnit(`${guide.id}:${index}`) * 0.08;
        const tint = {
            r: THREE.MathUtils.clamp(tintBase.r + offset, 0, 1),
            g: THREE.MathUtils.clamp(tintBase.g + offset * 0.45, 0, 1),
            b: THREE.MathUtils.clamp(tintBase.b + offset * 0.72, 0, 1),
        };
        if (surface !== 'transit') return tint;
        if (guide.guideKind === 'wAxis') return {
            r: 0.18,
            g: 0.82,
            b: 0.94,
        };
        return tint;
    }

    private lorentzLayerOpacity(layer: string, guideKind: GalaxyLorentzGuideView['guideKind'] | undefined, treeKind = '', weight = 1, surface: GuideSurface = 'default'): number {
        // Legacy lorentzSpaceVisible stays as the master switch; guideRoutesVisible
        // is the dedicated per-family override (defaults visible via mergeGalaxySettings).
        if (!this.settings.lorentzSpaceVisible) return 0;
        if (this.settings.guideRoutesVisible === false) return 0;
        const intensity = THREE.MathUtils.clamp(this.settings.lorentzSpaceIntensity, 0, 1.4);
        const globalGlow = THREE.MathUtils.clamp(this.settings.glow, 0, 1.8);
        const treeBoost = treeKind === 'evidence' || treeKind === 'causal' ? 1.05 : 1;
        if (surface === 'transit') {
            const rootBoost = guideKind === 'rootLane' ? 1.12 : 1;
            if (layer === 'tubeCore') return THREE.MathUtils.clamp(0.072 * intensity * treeBoost * rootBoost * weight, 0, 0.14);
            if (layer === 'tubeGlow') return THREE.MathUtils.clamp(0.014 * intensity * (0.72 + globalGlow * 0.12) * weight, 0, 0.034);
            if (layer === 'shell') return THREE.MathUtils.clamp(0.018 * intensity * (0.68 + globalGlow * 0.16) * weight, 0, 0.045);
            return THREE.MathUtils.clamp((0.02 + globalGlow * 0.006) * intensity * weight * this.lorentzGuideWeightForKind(guideKind), 0, 0.082);
        }
        if (layer === 'tubeCore') return THREE.MathUtils.clamp(0.084 * intensity * treeBoost * weight, 0, 0.16);
        if (layer === 'tubeGlow') return THREE.MathUtils.clamp(0.016 * intensity * (0.74 + globalGlow * 0.12) * weight, 0, 0.038);
        if (layer === 'shell') return THREE.MathUtils.clamp(0.022 * intensity * (0.72 + globalGlow * 0.18) * weight, 0, 0.055);
        return THREE.MathUtils.clamp((0.022 + globalGlow * 0.01) * intensity * weight * this.lorentzGuideWeightForKind(guideKind), 0, 0.096);
    }

    private lorentzTubeRadius(guide: GalaxyLorentzGuideView, layer: 'tubeCore' | 'tubeGlow', surface: GuideSurface = 'default'): number {
        const rootBoost = guide.guideKind === 'rootLane' ? 1.2 : 1;
        const weightBoost = THREE.MathUtils.clamp(0.78 + Math.sqrt(Math.max(0.08, guide.guideWeight || 0.7)) * 0.32, 0.88, 1.22);
        const core = surface === 'transit' ? 0.00372 : 0.00405;
        const glow = surface === 'transit' ? 0.0084 : 0.0096;
        return (layer === 'tubeGlow' ? glow : core) * rootBoost * weightBoost;
    }

    private lorentzGuideWeightForKind(kind: GalaxyLorentzGuideView['guideKind'] | undefined): number {
        switch (kind) {
            case 'membership':
                return 0.86;
            case 'rootLane':
                return 1.08;
            case 'levelShell':
                return 0.46;
            case 'wAxis':
                return 0.24;
            default:
                return 0.7;
        }
    }

    private lorentzShellRadius(guide: GalaxyLorentzGuideView): number {
        const segment = guide.positions3d.length >= 3
            ? Math.hypot(guide.positions3d[0], guide.positions3d[1], guide.positions3d[2])
            : 0;
        return THREE.MathUtils.clamp(segment || 0.58 + guide.level * 0.24, 0.58, 2.18);
    }

    private torusBandIndex(id: string): number {
        const match = id.match(/torus-band:(\d+)/);
        return match ? Math.min(2, Math.max(0, Number(match[1]) || 0)) : 1;
    }

    private stableUnit(value: string): number {
        let hash = 2166136261;
        for (let index = 0; index < value.length; index++) {
            hash ^= value.charCodeAt(index);
            hash = Math.imul(hash, 16777619);
        }
        return (hash >>> 0) / 4294967295;
    }

    private hslColor(h: number, s: number, l: number): { r: number; g: number; b: number } {
        const buffer = new Float32Array(3);
        this.writeHslColor(buffer, 0, h, s, l);
        return { r: buffer[0], g: buffer[1], b: buffer[2] };
    }

    private writeHslColor(colors: Float32Array, offset: number, h: number, s: number, l: number): void {
        const hue = ((h % 1) + 1) % 1;
        if (s <= 0) {
            colors[offset] = colors[offset + 1] = colors[offset + 2] = l;
            return;
        }
        const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
        const p = 2 * l - q;
        colors[offset] = this.hueToRgb(p, q, hue + 1 / 3);
        colors[offset + 1] = this.hueToRgb(p, q, hue);
        colors[offset + 2] = this.hueToRgb(p, q, hue - 1 / 3);
    }

    private hueToRgb(p: number, q: number, t: number): number {
        let hue = t;
        if (hue < 0) hue += 1;
        if (hue > 1) hue -= 1;
        if (hue < 1 / 6) return p + (q - p) * 6 * hue;
        if (hue < 1 / 2) return q;
        if (hue < 2 / 3) return p + (q - p) * (2 / 3 - hue) * 6;
        return p;
    }

    private updateGroupShells(data: GalaxySceneV2): void {
        if (!this.shells) return;
        if (isTransitLayoutMode(data.layoutMode)) {
            const scale = transitManifoldExpansionScale(this.settings);
            this.shells.scale.set(scale, scale, this.mode === '2d' ? 0.08 : scale);
            return;
        }
        if (data.layoutMode === 'hybridSpace' || data.layoutMode === 'hopfProjection' || data.layoutMode === 'lorentzTree' || data.layoutMode === 'siegelFinsler') {
            this.shells.scale.set(1, 1, this.mode === '2d' ? 0.08 : 1);
            return;
        }
        data.groups.forEach((group, index) => {
            const mesh = this.shells?.children[index] as THREE.Mesh | undefined;
            if (!mesh) return;
            const center = this.groupCenterForMode(group);
            mesh.position.set(center.x, center.y, center.z);
            mesh.scale.set(1, 1, this.mode === '2d' ? 0.08 : 1);
        });
    }

    private groupCenterForMode(group: GalaxySceneGroupView): { x: number; y: number; z: number } {
        return this.mode === '2d'
            ? { x: group.center.x, y: group.center.y, z: 0 }
            : group.center;
    }

    private positions(): Float32Array | null {
        if (!this.sceneData) return null;
        return this.mode === '2d' ? this.sceneData.positions2d : this.sceneData.positions3d;
    }

    private screenSpacePick(pointer: GraphRendererPointer): number {
        const data = this.sceneData;
        const positions = this.positions();
        if (!data || !positions || pointer.width <= 0 || pointer.height <= 0) return -1;
        const camera = this.camera();
        let best = -1;
        let bestScore = Number.POSITIVE_INFINITY;
        const glowBoost = this.settings.glow * 4;
        const shapeBoost = galaxyNodePickShapeBoost(this.settings.nodeShape);
        const densityPenalty = data.ids.length > 160 ? 4 : 0;

        for (let i = 0; i < data.ids.length; i++) {
            const offset = i * 3;
            this.pickVector.set(positions[offset], positions[offset + 1], positions[offset + 2]).project(camera);
            if (this.pickVector.z < -1 || this.pickVector.z > 1) continue;
            const sx = (this.pickVector.x * 0.5 + 0.5) * pointer.width;
            const sy = (-this.pickVector.y * 0.5 + 0.5) * pointer.height;
            const dx = sx - pointer.x;
            const dy = sy - pointer.y;
            const radius = THREE.MathUtils.clamp(11 + data.radii[i] * 1.9 + glowBoost + shapeBoost - densityPenalty, 10, 34);
            const score = (dx * dx + dy * dy) / (radius * radius);
            if (score <= 1 && score < bestScore) {
                bestScore = score;
                best = i;
            }
        }

        return best;
    }

    private screenSpaceEdgePick(pointer: GraphRendererPointer): number {
        const data = this.sceneData;
        const positions = this.positions();
        if (!data || !positions || pointer.width <= 0 || pointer.height <= 0) return -1;
        const camera = this.camera();
        let best = -1;
        let bestDistance = 9 * 9;
        for (let index = 0; index < data.edgeIds.length; index++) {
            const sourceOffset = data.edgePairs[index * 2] * 3;
            const targetOffset = data.edgePairs[index * 2 + 1] * 3;
            this.pickVector.set(positions[sourceOffset], positions[sourceOffset + 1], positions[sourceOffset + 2]).project(camera);
            this.pickVectorB.set(positions[targetOffset], positions[targetOffset + 1], positions[targetOffset + 2]).project(camera);
            if (this.pickVector.z < -1 || this.pickVector.z > 1 || this.pickVectorB.z < -1 || this.pickVectorB.z > 1) continue;
            const ax = (this.pickVector.x * 0.5 + 0.5) * pointer.width;
            const ay = (-this.pickVector.y * 0.5 + 0.5) * pointer.height;
            const bx = (this.pickVectorB.x * 0.5 + 0.5) * pointer.width;
            const by = (-this.pickVectorB.y * 0.5 + 0.5) * pointer.height;
            const distance = pointSegmentDistanceSquared(pointer.x, pointer.y, ax, ay, bx, by);
            if (distance < bestDistance) {
                best = index;
                bestDistance = distance;
            }
        }
        return best;
    }

    private screenSpaceGroupPick(pointer: GraphRendererPointer): GraphCanvasHit | null {
        const data = this.sceneData;
        if (!data || pointer.width <= 0 || pointer.height <= 0) return null;
        const camera = this.camera();
        let best: GalaxySceneGroupView | null = null;
        let bestScore = Number.POSITIVE_INFINITY;
        for (const group of data.groups) {
            const center = this.groupCenterForMode(group);
            this.pickVector.set(center.x, center.y, center.z).project(camera);
            this.pickVectorB.set(center.x + group.radius, center.y, center.z).project(camera);
            if (this.pickVector.z < -1 || this.pickVector.z > 1) continue;
            const x = (this.pickVector.x * 0.5 + 0.5) * pointer.width;
            const y = (-this.pickVector.y * 0.5 + 0.5) * pointer.height;
            const radius = Math.max(18, Math.abs(this.pickVectorB.x - this.pickVector.x) * pointer.width * 0.5);
            const distance = Math.hypot(pointer.x - x, pointer.y - y);
            const score = distance / radius;
            if (score <= 1 && score < bestScore) {
                best = group;
                bestScore = score;
            }
        }
        return best ? { kind: 'cluster', id: best.id, label: best.label, nodeIds: best.nodeIds } : null;
    }

    private capsSurfaceEdge(data: GalaxySceneV2, ax: number, ay: number, az: number, bx: number, by: number, bz: number): boolean {
        if (this.mode !== '3d') return false;
        const ar = Math.hypot(ax, ay, az);
        const br = Math.hypot(bx, by, bz);
        if (data.layoutMode === 'hybridSpace') return this.hybridSurfaceEdge(ar, br, ax, ay, az, bx, by, bz);
        if (data.layoutMode !== 'lorentzTree') return false;
        if (ar < CAPS_SURFACE_EDGE_MIN_RADIUS || br < CAPS_SURFACE_EDGE_MIN_RADIUS) return false;
        if (Math.abs(ar - br) > CAPS_SURFACE_EDGE_MAX_RADIUS_DELTA) return false;
        if (this.capsShellIndex(ar) !== this.capsShellIndex(br)) return false;
        const dot = (ax * bx + ay * by + az * bz) / Math.max(0.000001, ar * br);
        return dot > -0.985;
    }

    private hybridSurfaceEdge(ar: number, br: number, ax: number, ay: number, az: number, bx: number, by: number, bz: number): boolean {
        if (ar < HYBRID_SURFACE_EDGE_MIN_RADIUS || br < HYBRID_SURFACE_EDGE_MIN_RADIUS) return false;
        if (Math.abs(ar - br) > HYBRID_SURFACE_EDGE_MAX_RADIUS_DELTA) return false;
        const dot = (ax * bx + ay * by + az * bz) / Math.max(0.000001, ar * br);
        return dot > -0.985;
    }

    private capsShellIndex(radius: number): number {
        let best = 0;
        let bestDistance = Number.POSITIVE_INFINITY;
        for (let index = 0; index < CAPS_SHELL_RADII.length; index++) {
            const distance = Math.abs(radius - CAPS_SHELL_RADII[index]);
            if (distance >= bestDistance) continue;
            best = index;
            bestDistance = distance;
        }
        return best;
    }

    private capsSurfacePoint(out: THREE.Vector3, ax: number, ay: number, az: number, bx: number, by: number, bz: number, t: number): boolean {
        const ar = Math.hypot(ax, ay, az);
        const br = Math.hypot(bx, by, bz);
        if (ar <= 0.000001 || br <= 0.000001) return false;
        const anx = ax / ar, any = ay / ar, anz = az / ar;
        const bnx = bx / br, bny = by / br, bnz = bz / br;
        const radius = THREE.MathUtils.lerp(ar, br, t);
        const dot = THREE.MathUtils.clamp(anx * bnx + any * bny + anz * bnz, -1, 1);

        if (dot > 0.9995) {
            const x = THREE.MathUtils.lerp(anx, bnx, t);
            const y = THREE.MathUtils.lerp(any, bny, t);
            const z = THREE.MathUtils.lerp(anz, bnz, t);
            const len = Math.hypot(x, y, z);
            if (len <= 0.000001) return false;
            out.set(x / len * radius, y / len * radius, z / len * radius);
            return true;
        }

        if (dot < -0.985) return false;
        const theta = Math.acos(dot);
        const sinTheta = Math.sin(theta);
        if (Math.abs(sinTheta) <= 0.000001) return false;
        const sourceScale = Math.sin((1 - t) * theta) / sinTheta;
        const targetScale = Math.sin(t * theta) / sinTheta;
        out.set(
            (anx * sourceScale + bnx * targetScale) * radius,
            (any * sourceScale + bny * targetScale) * radius,
            (anz * sourceScale + bnz * targetScale) * radius,
        );
        return true;
    }

    private edgeTubeLift(data: GalaxySceneV2, edge: number, source: number, target: number): number {
        const curveScale = THREE.MathUtils.clamp(this.settings.edgeCurveStrength, 0.25, 1.2);
        if (this.usesTreeFilamentEdges(data)) {
            const kindScale = data.edgeKinds[edge] === 1 ? 0.74 : data.edgeKinds[edge] === 2 ? 0.68 : 0.62;
            return this.treeFilamentEdgeLift(data, edge, source, target, curveScale * kindScale);
        }
        const confidence = THREE.MathUtils.clamp(data.edgeAlpha[edge] ?? 0.45, 0.12, 1);
        const bridgeBoost = data.edgeKinds[edge] === 1 ? 1.38 : 1;
        const span = Math.sqrt(Math.max(1, Math.abs(source - target)));
        return (0.045 + confidence * 0.13 + span * 0.004) * bridgeBoost * curveScale;
    }

    private writeTreeTubeEdgeVertex(
        positionAttr: THREE.BufferAttribute,
        colorAttr: THREE.BufferAttribute,
        cursor: number,
        data: GalaxySceneV2,
        focus: GalaxyFocusMask,
        edge: number,
        ax: number,
        ay: number,
        az: number,
        bx: number,
        by: number,
        bz: number,
        ox: number,
        oy: number,
        lift: number,
        t: number,
        tone = 1,
    ): number {
        const envelope = this.treeFilamentTerminalTaper(t);
        return this.writeTubeEdgeVertex(
            positionAttr,
            colorAttr,
            cursor,
            data,
            focus,
            edge,
            ax + ox * envelope,
            ay + oy * envelope,
            az,
            bx + ox * envelope,
            by + oy * envelope,
            bz,
            lift,
            t,
            tone,
        );
    }

    private writeTubeEdgeVertex(
        positionAttr: THREE.BufferAttribute,
        colorAttr: THREE.BufferAttribute,
        cursor: number,
        data: GalaxySceneV2,
        focus: GalaxyFocusMask,
        edge: number,
        ax: number,
        ay: number,
        az: number,
        bx: number,
        by: number,
        bz: number,
        lift: number,
        t: number,
        tone = 1,
    ): number {
        const dx = bx - ax;
        const dy = by - ay;
        const xy = Math.hypot(dx, dy) || 1;
        const sign = this.stableUnit(`tube-edge:${edge}`) < 0.5 ? -1 : 1;
        const sweep = Math.sin(Math.PI * t);
        const braid = Math.sin(Math.PI * 2 * t + sign * 0.72) * lift * 0.08;
        const flourish = this.tubeEdgeTerminalFlourish(data, t, lift, sign);
        const lateral = lift * 0.34 * sweep * sign + flourish;
        positionAttr.setXYZ(
            cursor,
            THREE.MathUtils.lerp(ax, bx, t) + (-dy / xy) * lateral,
            THREE.MathUtils.lerp(ay, by, t) + (dx / xy) * lateral + lift * 0.38 * sweep + Math.abs(flourish) * 0.08,
            THREE.MathUtils.lerp(az, bz, t) + (this.mode === '3d' ? lift * 0.24 * sweep * sign + braid + flourish * 0.42 : 0),
        );
        this.writeEdgeColor(colorAttr, cursor, data, focus, edge, t, tone);
        return cursor + 1;
    }

    private tubeEdgeTerminalFlourish(data: GalaxySceneV2, t: number, lift: number, sign: number): number {
        if (!TREE_FILAMENT_EDGE_LAYOUTS.has(data.layoutMode)) return 0;
        const width = isTransitLayoutMode(data.layoutMode) ? 0.3 : 0.26;
        const end = t > 1 - width ? Math.sin(Math.PI * (1 - t) / width) : 0;
        const style = data.layoutMode === 'siegelFinsler' ? 0.21 : data.layoutMode === 'lorentzTree' ? 0.18 : 0.16;
        return lift * style * sign * end;
    }

    private writeHopfEdgeVertex(
        positionAttr: THREE.BufferAttribute,
        colorAttr: THREE.BufferAttribute,
        cursor: number,
        data: GalaxySceneV2,
        focus: GalaxyFocusMask,
        edge: number,
        ax: number,
        ay: number,
        az: number,
        bx: number,
        by: number,
        bz: number,
        lift: number,
        t: number,
        tone = 1,
        crossBase = false,
    ): number {
        const seed = this.stableUnit(`hopf-edge:${edge}`);
        setHopfEdgeCurvePoint(this.edgeCurvePoint, ax, ay, az, bx, by, bz, lift, t, this.settings.edgeCurveStrength, seed, crossBase);
        positionAttr.setXYZ(cursor, this.edgeCurvePoint.x, this.edgeCurvePoint.y, this.edgeCurvePoint.z);
        this.writeEdgeColor(colorAttr, cursor, data, focus, edge, t, tone);
        return cursor + 1;
    }

    private writeEdgeVertex(
        positionAttr: THREE.BufferAttribute,
        colorAttr: THREE.BufferAttribute,
        cursor: number,
        data: GalaxySceneV2,
        focus: GalaxyFocusMask,
        edge: number,
        ax: number,
        ay: number,
        az: number,
        bx: number,
        by: number,
        bz: number,
        lift: number,
        t: number,
        tone = 1,
    ): number {
        const curve = lift * Math.sin(Math.PI * t);
        positionAttr.setXYZ(cursor, THREE.MathUtils.lerp(ax, bx, t), THREE.MathUtils.lerp(ay, by, t) + curve, THREE.MathUtils.lerp(az, bz, t));
        this.writeEdgeColor(colorAttr, cursor, data, focus, edge, t, tone);
        return cursor + 1;
    }

    private writeTreeFilamentEdgeVertex(
        positionAttr: THREE.BufferAttribute,
        colorAttr: THREE.BufferAttribute,
        cursor: number,
        data: GalaxySceneV2,
        focus: GalaxyFocusMask,
        edge: number,
        ax: number,
        ay: number,
        az: number,
        bx: number,
        by: number,
        bz: number,
        ox: number,
        oy: number,
        lift: number,
        t: number,
        tone = 1,
    ): number {
        const envelope = this.treeFilamentTerminalTaper(t);
        const curve = lift * Math.sin(Math.PI * t);
        positionAttr.setXYZ(
            cursor,
            THREE.MathUtils.lerp(ax, bx, t) + ox * envelope,
            THREE.MathUtils.lerp(ay, by, t) + oy * envelope + curve,
            THREE.MathUtils.lerp(az, bz, t),
        );
        this.writeEdgeColor(colorAttr, cursor, data, focus, edge, t, tone);
        return cursor + 1;
    }

    private writeCapsSurfaceEdgeVertex(
        positionAttr: THREE.BufferAttribute,
        colorAttr: THREE.BufferAttribute,
        cursor: number,
        data: GalaxySceneV2,
        focus: GalaxyFocusMask,
        edge: number,
        ax: number,
        ay: number,
        az: number,
        bx: number,
        by: number,
        bz: number,
        ox: number,
        oy: number,
        t: number,
        tone = 1,
    ): number {
        const envelope = this.usesTreeFilamentEdges(data) ? this.treeFilamentTerminalTaper(t) : 1;
        if (!this.capsSurfacePoint(this.edgeSurfacePoint, ax, ay, az, bx, by, bz, t)) {
            return this.writeEdgeVertex(positionAttr, colorAttr, cursor, data, focus, edge, ax + ox * envelope, ay + oy * envelope, az, bx + ox * envelope, by + oy * envelope, bz, 0, t, tone);
        }
        positionAttr.setXYZ(cursor, this.edgeSurfacePoint.x + ox * envelope, this.edgeSurfacePoint.y + oy * envelope, this.edgeSurfacePoint.z);
        this.writeEdgeColor(colorAttr, cursor, data, focus, edge, t, tone);
        return cursor + 1;
    }

    private writeEdgeColor(colorAttr: THREE.BufferAttribute, cursor: number, data: GalaxySceneV2, focus: GalaxyFocusMask, edge: number, t: number, tone = 1): void {
        const color = this.edgeColor(data, edge, t);
        const bridgeBoost = data.edgeKinds[edge] === 1 ? 1.1 : 1;
        const glowBoost = 0.58 + THREE.MathUtils.clamp(this.settings.glow, 0, 1.8) * 0.12;
        const focusBoost = focus.hasFocus ? (focus.edgeLevels[edge] ? 1 : 0.08) : 0.72;
        const boost = focusBoost * bridgeBoost * glowBoost * tone;
        colorAttr.setXYZ(cursor, Math.min(0.62, color.r * boost), Math.min(0.68, color.g * boost), Math.min(0.7, color.b * boost));
    }

    private edgeColor(data: GalaxySceneV2, edge: number, t: number): THREE.Color {
        if (data.edgeKinds[edge] === 1 && (this.settings.edgeColorMode === 'entityBlend' || this.settings.edgeColorMode === 'aqua' || this.settings.edgeColorMode === 'cyan')) {
            return this.color.setRGB(
                THREE.MathUtils.lerp(0.12, 0.46, t),
                THREE.MathUtils.lerp(0.64, 0.24, t),
                THREE.MathUtils.lerp(0.7, 0.86, t),
            );
        }
        switch (this.settings.edgeColorMode) {
            case 'muted':
                return this.color.setRGB(0.13, 0.15, 0.2);
            case 'aqua':
            case 'cyan':
                return this.color.setRGB(0.07, 0.5, 0.58);
            case 'orchid':
                return this.color.setRGB(0.4, 0.18, 0.62);
            case 'gold':
                return this.color.setRGB(0.58, 0.36, 0.12);
            case 'confidence': {
                const confidence = THREE.MathUtils.clamp(data.edgeAlpha[edge] * 2.4, 0.16, 0.82);
                return this.color.setRGB(0.08 + confidence * 0.1, 0.24 + confidence * 0.32, 0.42 + confidence * 0.22);
            }
            default: {
                const offset = edge * 6 + (t < 0.5 ? 0 : 3);
                this.color.setRGB(data.edgeColors[offset], data.edgeColors[offset + 1], data.edgeColors[offset + 2]);
                this.color.offsetHSL(0, 0.06, -0.2);
                return this.color;
            }
        }
    }

    private clearObjects(): void {
        for (const object of [this.nodes, this.glows, this.shells, this.edges]) {
            if (!object) continue;
            this.scene.remove(object);
            if (object instanceof THREE.Group) {
                object.traverse((child) => {
                    const drawable = child as THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
                    const geometry = drawable.geometry;
                    geometry?.dispose();
                    const material = drawable.material;
                    if (Array.isArray(material)) material.forEach((item) => item.dispose());
                    else material?.dispose();
                });
            } else {
                object.geometry.dispose();
                const material = object.material;
                Array.isArray(material) ? material.forEach((item) => item.dispose()) : material.dispose();
            }
        }
        this.clearLabels();
        this.labelSignature = '';
        this.nodes = null;
        this.glows = null;
        this.shells = null;
        this.edges = null;
    }

    private clearLabels(): void {
        for (const label of this.labels) {
            this.scene.remove(label);
            label.material.map.dispose();
            label.material.dispose();
        }
        this.labels = [];
    }

    private recordTiming(key: keyof ThreeGalaxyRendererTimings, started: number): void {
        this.timings[key] = Math.max(0, Math.round(this.now() - started));
    }

    private now(): number {
        return typeof performance !== 'undefined' ? performance.now() : Date.now();
    }
}
