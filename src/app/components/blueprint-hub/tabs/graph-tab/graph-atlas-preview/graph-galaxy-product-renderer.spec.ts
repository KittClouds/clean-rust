// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

vi.mock('./graph-galaxy-textures', async () => {
    const THREE = await import('three');
    const texture = () => new THREE.Texture();
    return {
        makeAtomTexture: texture,
        makeHaloTexture: texture,
        makeLabelSprite: vi.fn(),
        makeNodeTexture: texture,
    };
});

import * as THREE from 'three';

import { buildGalaxyFocusMask } from './graph-galaxy-focus';
import { buildGalaxyGlows, galaxyGlowBatch } from './graph-galaxy-objects';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { GalaxyGpuEdgeCurve, type GalaxyGpuEdgeSurface } from './three-galaxy-edge-surface';
import { ThreeGalaxyRenderer } from './three-galaxy-renderer';

type RendererProbe = {
    setSettings(settings: Record<string, unknown>): void;
    edgeMaterialOpacity(): number;
    edgeColor(data: { layoutMode: string; edgeAlpha: Float32Array; edgeColors: Float32Array; edgeKinds: Uint8Array }, edge: number, t: number): THREE.Color;
    buildEdges(data: GalaxySceneV2): GalaxyGpuEdgeSurface | null;
    normalizedEdgeSignal(data?: { edgeAlpha: Float32Array }, edge?: number): number;
    treeFilamentEdgeLift(data: { edgeAlpha: Float32Array; edgeKinds: Uint8Array }, edge: number, source: number, target: number, curveScale: number): number;
    treeFilamentTerminalTaper(t: number): number;
    edgeTubeLift(data: { layoutMode: string; edgeAlpha: Float32Array; edgeKinds: Uint8Array }, edge: number, source: number, target: number): number;
    hybridShellOpacity(): number;
    hopfGuideWeightForKind(kind: string, surface?: string): number;
    hopfLayerOpacity(layer: string, kind: string, weight?: number, surface?: string): number;
    hopfTubeOpacity(kind: string, glow: boolean, surface: string): number;
    hopfTubeRadius(kind: string, layer: 'tubeCore' | 'tubeGlow', surface: string): number;
    lorentzGuideFocusMultiplier(data: { ids: string[] }, focus: ReturnType<typeof buildGalaxyFocusMask>, nodeIds: readonly string[]): number;
    lorentzGuideTint(guide: Record<string, unknown>, index: number, surface?: string): { r: number; g: number; b: number };
    lorentzLayerOpacity(layer: string, guideKind: string, treeKind?: string, weight?: number, surface?: string): number;
    lorentzTubeRadius(guide: { guideKind: string }, layer: 'tubeCore' | 'tubeGlow', surface?: string): number;
    buildLorentzTubeMesh(guide: Record<string, unknown>, index: number, layer: 'tubeCore' | 'tubeGlow', surface: string): THREE.Mesh | null;
    writeLorentzGuideColor(colors: Float32Array, offset: number, guide: Record<string, unknown>, index: number, phase: number, surface: string, focusScale?: number): void;
    nodeDensityFactors(data: { ids: string[] }, positions: Float32Array): Float32Array;
    tubeEdgeTerminalFlourish(data: { layoutMode: string }, t: number, lift: number, sign: number): number;
    capsSurfaceEdge(data: { layoutMode: string }, ax: number, ay: number, az: number, bx: number, by: number, bz: number): boolean;
    capsSurfacePoint(out: THREE.Vector3, ax: number, ay: number, az: number, bx: number, by: number, bz: number, t: number): boolean;
    writeLorentzGuidePositions(output: Float32Array, cursor: number, guide: Record<string, unknown>, data: { ids: string[]; layoutMode?: string }, positions: Float32Array, indexById: Map<string, number>): number;
    guideAttachmentContract(data: { layoutMode: string }): { liveLorentzGuides: boolean; localScale: number };
    guidePositionsForContract(positions: Float32Array, contract: { liveLorentzGuides: boolean; localScale: number }): Float32Array;
    buildTransitGuides(scene: GalaxySceneV2): THREE.Group;
    sceneData: unknown;
};

type CameraProbe = RendererProbe & {
    renderer: { render: ReturnType<typeof vi.fn>; domElement: { clientWidth: number; clientHeight: number } };
    perspective: THREE.PerspectiveCamera;
    panX: number;
    panY: number;
    panZ: number;
    sceneData: GalaxySceneV2 | null;
    hoverId: string | null;
    resetCamera(): void;
    pan(deltaX: number, deltaY: number): void;
    rotate(deltaX: number, deltaY: number): void;
    zoomAt(delta: number, pointer: { x: number; y: number; width: number; height: number }): void;
    pointerToCameraTargetPlane(pointer: { x: number; y: number; width: number; height: number }, out: THREE.Vector3): boolean;
};

function mountCameraProbe(): CameraProbe {
    const renderer = new ThreeGalaxyRenderer() as unknown as CameraProbe;
    renderer.renderer = { render: vi.fn(), domElement: { clientWidth: 800, clientHeight: 600 } };
    renderer.resetCamera();
    vi.spyOn(renderer as unknown as ThreeGalaxyRenderer, 'render').mockImplementation(() => undefined);
    return renderer;
}

describe('Galaxy camera controls', () => {
    it('keeps zoom-out centered on the camera target regardless of pointer position', () => {
        const left = mountCameraProbe();
        const right = mountCameraProbe();
        const leftPointer = { x: 80, y: 180, width: 800, height: 600 };
        const rightPointer = { x: 720, y: 420, width: 800, height: 600 };

        left.pan(48, -24);
        right.pan(48, -24);
        left.zoomAt(640, leftPointer);
        right.zoomAt(640, rightPointer);

        expect(left.perspective.position.toArray()).toEqual(right.perspective.position.toArray());
        const target = new THREE.Vector3(left.panX, left.panY, left.panZ);
        const projected = target.clone().project(left.perspective);
        expect(projected.x).toBeCloseTo(0, 6);
        expect(projected.y).toBeCloseTo(0, 6);

        const graphCenterBefore = new THREE.Vector3().project(left.perspective);
        left.rotate(80, -20);
        const graphCenterAfter = new THREE.Vector3().project(left.perspective);
        expect(graphCenterAfter.x).toBeCloseTo(graphCenterBefore.x, 6);
        expect(graphCenterAfter.y).toBeCloseTo(graphCenterBefore.y, 6);
        expect(new THREE.Vector3(left.panX, left.panY, left.panZ).project(left.perspective).x).toBeCloseTo(0, 6);
        expect(new THREE.Vector3(left.panX, left.panY, left.panZ).project(left.perspective).y).toBeCloseTo(0, 6);
    });

    it('keeps cursor zoom framing while rotation continues around the graph center', () => {
        const renderer = mountCameraProbe();
        const pointer = { x: 650, y: 210, width: 800, height: 600 };
        const anchor = new THREE.Vector3();
        const pointerNdcX = (pointer.x / pointer.width) * 2 - 1;
        const pointerNdcY = -(pointer.y / pointer.height) * 2 + 1;

        expect(renderer.pointerToCameraTargetPlane(pointer, anchor)).toBe(true);
        renderer.zoomAt(-360, pointer);

        expect(anchor.clone().project(renderer.perspective).x).toBeCloseTo(pointerNdcX, 6);
        expect(anchor.clone().project(renderer.perspective).y).toBeCloseTo(pointerNdcY, 6);
        expect(Math.abs(renderer.panX) + Math.abs(renderer.panY) + Math.abs(renderer.panZ)).toBeGreaterThan(0.001);

        const graphCenterBefore = new THREE.Vector3().project(renderer.perspective);
        renderer.rotate(80, -20);
        const graphCenterAfter = new THREE.Vector3().project(renderer.perspective);
        expect(graphCenterAfter.x).toBeCloseTo(graphCenterBefore.x, 6);
        expect(graphCenterAfter.y).toBeCloseTo(graphCenterBefore.y, 6);
        expect(new THREE.Vector3(renderer.panX, renderer.panY, renderer.panZ).project(renderer.perspective).x).toBeCloseTo(0, 6);
        expect(new THREE.Vector3(renderer.panX, renderer.panY, renderer.panZ).project(renderer.perspective).y).toBeCloseTo(0, 6);
    });

    it('uses the exact hovered node as the zoom-in anchor', () => {
        const renderer = mountCameraProbe();
        const node = new THREE.Vector3(1.3, 0.7, -0.4);
        renderer.sceneData = {
            ...emptyRendererScene(),
            ids: ['hovered'],
            positions3d: new Float32Array(node.toArray()),
            positions2d: new Float32Array([node.x, node.y, 0]),
            runtimeIndex: {
                nodeById: new Map([['hovered', 0]]),
                incidentOffsets: new Uint32Array(2),
                incidentEdges: new Uint32Array(),
            },
        };
        renderer.hoverId = 'hovered';
        const before = node.clone().project(renderer.perspective);
        const pointer = {
            x: (before.x * 0.5 + 0.5) * 800,
            y: (-before.y * 0.5 + 0.5) * 600,
            width: 800,
            height: 600,
        };

        renderer.zoomAt(-360, pointer);

        const after = node.clone().project(renderer.perspective);
        expect(after.x).toBeCloseTo(before.x, 6);
        expect(after.y).toBeCloseTo(before.y, 6);
        expect(Math.abs(renderer.panZ)).toBeGreaterThan(0.001);
    });
});

describe('Transit manifold guide styling', () => {
    it('installs a changed scene with one layout application and one draw', () => {
        const renderer = new ThreeGalaxyRenderer();
        const harness = renderer as unknown as { applyModePositions(): void };
        const applyModePositions = vi.spyOn(harness, 'applyModePositions');
        const render = vi.spyOn(renderer, 'render');

        renderer.installScene(emptyRendererScene(), { edgeMode: 'curved' }, '3d');

        expect(applyModePositions).toHaveBeenCalledTimes(1);
        expect(render).toHaveBeenCalledTimes(1);
        renderer.dispose();
    });

    it('routes hover and selection through focus refresh instead of full geometry refresh', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as {
            selectNode(id: string | null): void;
            hoverNode(id: string | null): void;
            applyFocusState: ReturnType<typeof vi.fn>;
            applyModePositions: ReturnType<typeof vi.fn>;
        };
        renderer.applyFocusState = vi.fn();
        renderer.applyModePositions = vi.fn();

        renderer.selectNode('node:a');
        renderer.hoverNode('node:b');

        expect(renderer.applyFocusState).toHaveBeenCalledTimes(2);
        expect(renderer.applyModePositions).not.toHaveBeenCalled();
    });

    it('keeps evidence fibers visually above scaffold and Lorentz guides', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const transitDataWeight = renderer.hopfGuideWeightForKind('dataFiber', 'transit');
        const transitScaffoldWeight = renderer.hopfGuideWeightForKind('torusBand', 'transit');

        const transitData = renderer.hopfLayerOpacity('line', 'dataFiber', transitDataWeight, 'transit');
        const transitScaffold = renderer.hopfLayerOpacity('line', 'torusBand', transitScaffoldWeight, 'transit');
        const transitLorentz = renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'transit');

        expect(transitData).toBeGreaterThan(transitScaffold * 4);
        expect(transitData).toBeGreaterThan(transitLorentz);
        expect(renderer.hopfTubeOpacity('torusBand', false, 'transit')).toBe(0);
        expect(renderer.hopfTubeOpacity('torusBand', false, 'default')).toBeGreaterThan(0);
    });

    it('keeps Transit fibers leaner and dimmer while preserving Hopf space control', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        expect(renderer.hopfTubeRadius('dataFiber', 'tubeCore', 'transit')).toBeCloseTo(0.0050625);
        expect(renderer.hopfTubeRadius('dataFiber', 'tubeGlow', 'transit')).toBeCloseTo(0.0162);
        expect(renderer.hopfTubeOpacity('dataFiber', false, 'transit')).toBeCloseTo(0.11424);

        renderer.setSettings({ hopfSpaceIntensity: 0 });
        expect(renderer.hopfTubeOpacity('dataFiber', false, 'transit')).toBe(0);
    });

    it('keeps default Hopf glow sleeves lean while preserving the space slider', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        expect(renderer.hopfTubeRadius('dataFiber', 'tubeCore', 'default')).toBeCloseTo(0.0055);
        expect(renderer.hopfTubeRadius('dataFiber', 'tubeGlow', 'default')).toBeCloseTo(0.012);
        expect(renderer.hopfTubeOpacity('dataFiber', false, 'default')).toBeGreaterThan(0.08);

        renderer.setSettings({ hopfSpaceIntensity: 0 });
        expect(renderer.hopfTubeOpacity('dataFiber', false, 'default')).toBe(0);
        expect(renderer.hopfLayerOpacity('line', 'dataFiber', renderer.hopfGuideWeightForKind('dataFiber'), 'default')).toBe(0);
    });

    it('makes Lorentz space and Glow sliders affect visible Transit geometry', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        const baseLorentz = renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'transit');
        renderer.setSettings({ lorentzSpaceIntensity: 0 });
        expect(renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'transit')).toBe(0);
        renderer.setSettings({ lorentzSpaceIntensity: 1.4 });
        expect(renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'transit')).toBeGreaterThan(baseLorentz * 1.25);

        renderer.setSettings({ glow: 0 });
        const lowEdge = renderer.edgeMaterialOpacity();
        const lowShell = renderer.hybridShellOpacity();
        renderer.setSettings({ glow: 1.8 });
        expect(renderer.edgeMaterialOpacity()).toBeGreaterThan(lowEdge * 1.6);
        expect(renderer.hybridShellOpacity()).toBeLessThan(lowShell * 1.5);
    });

    it('keeps tube edge mode in one bounded GPU curve bucket', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const data = gpuEdgeScene('single', 2);
        data.edgeAlpha.set([0.18, 1]);
        data.edgeKinds.set([0, 1]);

        renderer.setSettings({ edgeMode: 'tube', edgeWidth: 1.1, edgeOpacity: 0.7, glow: 1.8 });
        const surface = renderer.buildEdges(data);

        expect(renderer.edgeMaterialOpacity()).toBeLessThan(0.35);
        expect(surface?.bucketInstanceCounts()).toEqual([0, 2, 0]);
        expect(surface?.edgeCurve(0)).toBe(GalaxyGpuEdgeCurve.Tube);
        expect(surface?.edgeCurve(1)).toBe(GalaxyGpuEdgeCurve.Tube);
        surface?.dispose();
    });

    it('keeps dense manifold routing on a fixed GPU template', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const denseTree = gpuEdgeScene('siegelFinsler', 1300);

        renderer.setSettings({ edgeMode: 'curved', edgeWidth: 1.1, glow: 1.8 });
        const surface = renderer.buildEdges(denseTree);
        const line = surface?.children[0] as THREE.LineSegments;

        expect(surface?.bucketInstanceCounts()).toEqual([0, 1300, 0]);
        expect(line.geometry.getAttribute('position').count).toBe(24);
        expect(line.geometry.getAttribute('aEndpoints').count).toBe(1300);
        surface?.dispose();
    });

    it('keeps tree-space shape helpers without overriding edge colors', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const data = gpuEdgeScene('lorentzTree', 2);
        data.edgeAlpha.set([0.22, 0.34]);
        data.edgeKinds.set([0, 2]);
        data.edgeColors.set([
                1, 0, 0,
                1, 0, 0,
                0.8, 0.15, 0.9,
                0.8, 0.15, 0.9,
        ]);
        renderer.sceneData = data;
        const surface = renderer.buildEdges(data);

        expect(renderer.edgeMaterialOpacity()).toBeLessThan(0.35);
        expect(surface?.bucketInstanceCounts()).toEqual([0, 2, 0]);
        expect(surface?.edgeCurve(0)).toBe(GalaxyGpuEdgeCurve.TreeArc);
        expect(renderer.normalizedEdgeSignal(data, 1)).toBeGreaterThan(renderer.normalizedEdgeSignal(data, 0));
        expect(renderer.treeFilamentEdgeLift(data, 1, 0, 90, 0.58)).toBeGreaterThan(renderer.treeFilamentEdgeLift(data, 0, 0, 4, 0.58));
        expect(renderer.treeFilamentTerminalTaper(0.5)).toBeCloseTo(1);
        expect(renderer.treeFilamentTerminalTaper(0.9)).toBeLessThan(0.25);

        const color = renderer.edgeColor(data, 0, 0.5);
        expect(color.r).toBeGreaterThan(color.g);
        expect(color.r).toBeGreaterThan(color.b);
        surface?.dispose();
    });

    it('carries target-side Lorentz styling into tree-space tube edges', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const data = {
            layoutMode: 'transitManifold',
            edgeAlpha: new Float32Array([1]),
            edgeKinds: new Uint8Array([0]),
        };
        const genericData = { ...data, layoutMode: 'single' };

        expect(renderer.edgeTubeLift(data, 0, 0, 28)).toBeGreaterThan(renderer.edgeTubeLift(genericData, 0, 0, 28));
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'lorentzTree' }, 0.9, 0.3, 1)).toBeGreaterThan(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'transitManifold' }, 0.9, 0.3, 1)).toBeGreaterThan(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'siegelFinsler' }, 0.9, 0.3, 1)).toBeGreaterThan(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'siegelFinsler' }, 0.5, 0.3, 1)).toBe(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'siegelFinsler' }, 0.1, 0.3, 1)).toBe(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'single' }, 0.9, 0.3, 1)).toBe(0);
    });

    it('dims Lorentz guides by node focus without changing graph edge focus', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const data = {
            ids: ['kai', 'cael', 'hazel'],
            edgePairs: new Uint32Array([0, 1]),
        } as any;
        const focus = buildGalaxyFocusMask(data, null, 'kai');

        expect(renderer.lorentzGuideFocusMultiplier(data, focus, ['kai', 'cael'])).toBeGreaterThan(1);
        expect(renderer.lorentzGuideFocusMultiplier(data, focus, ['hazel'])).toBeLessThan(0.2);
        expect(renderer.lorentzGuideFocusMultiplier(data, focus, [])).toBeLessThan(0.3);
    });

    it('keeps Lorentz structure ten percent leaner', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        expect(renderer.lorentzTubeRadius({ guideKind: 'membership' }, 'tubeCore', 'transit')).toBeCloseTo(0.00396);
        expect(renderer.lorentzTubeRadius({ guideKind: 'membership' }, 'tubeGlow', 'transit')).toBeCloseTo(0.01125);
        expect(renderer.lorentzTubeRadius({ guideKind: 'membership' }, 'tubeCore')).toBeCloseTo(0.00432);
    });

    it('renders Lorentz tubes with edge-like normal blending and capped glow energy', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const guide = {
            id: 'caps:bridge:a-b',
            guideKind: 'membership',
            treeKind: 'relationship',
            guideWeight: 1,
            color: { r: 0.8, g: 0.22, b: 0.72 },
            positions3d: new Float32Array([
                0, 0, 0, 0.6, 0.18, 0,
                0.6, 0.18, 0, 1.2, 0, 0,
            ]),
        };

        const core = renderer.buildLorentzTubeMesh(guide, 0, 'tubeCore', 'default');
        const glow = renderer.buildLorentzTubeMesh(guide, 0, 'tubeGlow', 'default');
        const lineColor = new Float32Array(3);
        renderer.writeLorentzGuideColor(lineColor, 0, guide, 0, 0.5, 'default', 1.4);

        expect((core?.material as THREE.MeshBasicMaterial).blending).toBe(THREE.NormalBlending);
        expect((glow?.material as THREE.MeshBasicMaterial).blending).toBe(THREE.NormalBlending);
        expect((glow?.material as THREE.MeshBasicMaterial).opacity).toBeLessThan(0.04);
        expect(Math.max(...lineColor)).toBeLessThanOrEqual(0.86);

        core?.geometry.dispose();
        (core?.material as THREE.Material | undefined)?.dispose();
        glow?.geometry.dispose();
        (glow?.material as THREE.Material | undefined)?.dispose();
    });

    it('preserves Transit Lorentz lane colors instead of washing them to cyan', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const causalGuide = {
            id: 'lorentz:transit-guide:causal',
            guideKind: 'membership',
            treeKind: 'causal',
            level: 2,
            color: { r: 0.92, g: 0.38, b: 0.12 },
        };
        const documentGuide = {
            id: 'lorentz:transit-guide:document',
            guideKind: 'membership',
            treeKind: 'documentStructure',
            level: 1,
            color: { r: 0.14, g: 0.46, b: 0.9 },
        };
        const causalTint = renderer.lorentzGuideTint(causalGuide, 0, 'transit');
        const documentTint = renderer.lorentzGuideTint(documentGuide, 0, 'transit');
        const causalLine = new Float32Array(3);

        renderer.writeLorentzGuideColor(causalLine, 0, causalGuide, 0, 0.5, 'transit');

        expect(causalTint.r).toBeGreaterThan(causalTint.b * 2);
        expect(documentTint.b).toBeGreaterThan(documentTint.r * 2);
        expect(causalLine[0]).toBeGreaterThan(causalLine[2] * 2);
    });

    it('builds Transit guides from packet rows without mounting the old route ball', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const group = renderer.buildTransitGuides(minimalTransitScene());
        const guideKinds = collectGuideKinds(group);

        expect(group.children.length).toBeGreaterThan(0);
        expect(guideKinds.has('lorentz')).toBe(true);
        expect(guideKinds.has('transit-route-ball')).toBe(false);
        expect([...guideKinds].some((kind) => kind.includes('hopf') || kind.includes('hybrid'))).toBe(false);
    });

    it('prevents dense node overlaps from additive halo blowout', () => {
        const glows = buildGalaxyGlows({ ids: ['a'] } as any, new THREE.Texture());
        const batch = galaxyGlowBatch(glows);
        expect(batch?.points).toBeInstanceOf(THREE.Points);
        expect(batch?.points.material.blending).toBe(THREE.NormalBlending);
        expect(batch?.points.material.name).toBe('GalaxyGlowBatch');
        expect(batch?.points.material.vertexColors).toBe(true);
        expect(batch?.positions.length).toBe(3);

        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe & {
            renderer: { domElement: { clientWidth: number; clientHeight: number } };
            perspective: THREE.PerspectiveCamera;
        };
        renderer.renderer = { domElement: { clientWidth: 100, clientHeight: 100 } };
        renderer.perspective.position.set(0, 0, 7);
        renderer.perspective.lookAt(0, 0, 0);
        renderer.perspective.updateMatrixWorld();
        renderer.perspective.updateProjectionMatrix();

        const positions = new Float32Array([
            0, 0, 0,
            0.01, 0, 0,
            -0.01, 0, 0,
            0, 0.01, 0,
        ]);
        const factors = renderer.nodeDensityFactors({ ids: ['a', 'b', 'c', 'd'] }, positions);

        expect(Math.max(...factors)).toBeLessThan(1);
        expect(Math.min(...factors)).toBeGreaterThanOrEqual(0.28);
    });

    it('keeps spherical edge routing scoped to shell nodes in the Caps view', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const caps = { layoutMode: 'lorentzTree' };
        const hybrid = { layoutMode: 'hybridSpace' };
        const mid = new THREE.Vector3();

        expect(renderer.capsSurfaceEdge(caps, 2.08, 0, 0, 0, 2.04, 0)).toBe(true);
        expect(renderer.capsSurfaceEdge(hybrid, 2.08, 0, 0, 0, 2.04, 0)).toBe(false);
        expect(renderer.capsSurfaceEdge(hybrid, 2.32, 0, 0, 0, 2.28, 0)).toBe(true);
        expect(renderer.capsSurfaceEdge(hybrid, 2.32, 0, 0, 0, 1.74, 0)).toBe(false);
        expect(renderer.capsSurfaceEdge(hybrid, 1.34, 0, 0, 0, 1.32, 0)).toBe(false);
        expect(renderer.capsSurfaceEdge(caps, 2.08, 0, 0, 0.6, 0.24, 0)).toBe(false);
        expect(renderer.capsSurfaceEdge(caps, 0.98, 0, 0, 0, 0.96, 0)).toBe(true);
        expect(renderer.capsSurfaceEdge(caps, 1.34, 0, 0, 0, 1.48, 0)).toBe(false);
        expect(renderer.capsSurfacePoint(mid, 2.08, 0, 0, 0, 2.08, 0, 0.5)).toBe(true);
        expect(mid.length()).toBeCloseTo(2.08);
        expect(mid.x).toBeGreaterThan(1.4);
        expect(mid.y).toBeGreaterThan(1.4);
    });

    it('reanchors Caps membership guides to live node positions', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const guide = {
            id: 'caps:bridge:a-b',
            guideKind: 'membership',
            nodeIds: ['a', 'b'],
            positions3d: new Float32Array([
                0, 0, 0, 0.5, 0.2, 0,
                0.5, 0.2, 0, 1, 0, 0,
            ]),
        };
        const output = new Float32Array(guide.positions3d.length);

        renderer.writeLorentzGuidePositions(
            output,
            0,
            guide,
            { ids: ['a', 'b'] },
            new Float32Array([2, 0, 0, 4, 0, 0]),
            new Map([['a', 0], ['b', 1]]),
        );

        expect(Array.from(output.slice(0, 3))).toEqual([2, 0, 0]);
        expect(Array.from(output.slice(output.length - 3))).toEqual([4, 0, 0]);
        expect(output[4]).toBeGreaterThan(0);
    });

    it('slants Caps root lanes so tree guides read as depth cues instead of flat rulers', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const guide = {
            id: 'caps:root-lane:0',
            guideKind: 'rootLane',
            nodeIds: [],
            positions3d: new Float32Array([
                -2, 0, 0,
                2, 0, 0,
            ]),
        };
        const output = new Float32Array(guide.positions3d.length);

        renderer.writeLorentzGuidePositions(output, 0, guide, { ids: [], layoutMode: 'lorentzTree' }, new Float32Array(), new Map());

        expect(output[0]).toBe(-2);
        expect(output[3]).toBe(2);
        expect(Math.abs(output[4] - output[1])).toBeGreaterThan(0.3);
        expect(Math.abs(output[5] - output[2])).toBeGreaterThan(0.08);
    });

    it('renders live membership routes as one continuous gentle swoop', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const guide = {
            id: 'caps:bridge:a-b',
            guideKind: 'membership',
            nodeIds: ['a', 'b'],
            positions3d: new Float32Array([
                0, 0, 0,
                0.5, 0.6, 0,
                0.9, 0.6, 0,
                1, 0, 0,
            ]),
        };
        const output = new Float32Array(guide.positions3d.length);

        renderer.writeLorentzGuidePositions(
            output,
            0,
            guide,
            { ids: ['a', 'b'], layoutMode: 'lorentzTree' },
            new Float32Array([0, 0, 0, 10, 0, 0]),
            new Map([['a', 0], ['b', 1]]),
        );

        expect(Array.from(output.slice(0, 3))).toEqual([0, 0, 0]);
        expect(output[3]).toBeCloseTo(output[6]);
        expect(output[4]).toBeCloseTo(output[7]);
        expect(output[4]).toBeGreaterThan(0.8);
        expect(output[9]).toBe(10);
        expect(output[10]).toBe(0);
        expect(Array.from(output.slice(output.length - 3))).toEqual([10, 0, 0]);
    });

    it('uses one live guide attachment contract for Transit and Siegel spaces', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        renderer.setSettings({ edgeLength: 1.4, nodeDistance: 1.25 });
        const transit = renderer.guideAttachmentContract({ layoutMode: 'transitManifold' });
        const siegel = renderer.guideAttachmentContract({ layoutMode: 'siegelFinsler' });
        const caps = renderer.guideAttachmentContract({ layoutMode: 'lorentzTree' });
        const hybrid = renderer.guideAttachmentContract({ layoutMode: 'hybridSpace' });
        const positions = new Float32Array([2, 0, 0, 4, 0, 0]);
        const transitLocal = renderer.guidePositionsForContract(positions, transit);

        expect(transit.liveLorentzGuides).toBe(true);
        expect(transit.localScale).toBeGreaterThan(1);
        expect(transitLocal[0]).toBeLessThan(positions[0]);
        expect(siegel).toEqual({ liveLorentzGuides: true, localScale: 1 });
        expect(caps).toEqual({ liveLorentzGuides: true, localScale: 1 });
        expect(hybrid.liveLorentzGuides).toBe(false);
    });
});

function minimalTransitScene(): GalaxySceneV2 {
    return {
        sourceMode: 'embeddings',
        layoutMode: 'transitManifold',
        ids: [],
        labels: [],
        kinds: [],
        groupIds: [],
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [{
            id: 'transit:plan:lane:evidence',
            nodeIds: ['evidence'],
            positions3d: new Float32Array([
                -1, 0, 0,
                0, 0.04, 0.02,
                0, 0.04, 0.02,
                1, 0, 0,
            ]),
            positions2d: new Float32Array(),
            color: { r: 0.6, g: 0.36, b: 1 },
            importance: 7,
            treeId: 'transit:plan-lanes',
            treeKind: 'lane:evidence',
            level: 3,
            guideKind: 'rootLane',
            guideWeight: 0.5,
        }],
        positions3d: new Float32Array(),
        positions2d: new Float32Array(),
        radii: new Float32Array(),
        colors: new Float32Array(),
        edgePairs: new Uint32Array(),
        edgeIds: [],
        edgeTypes: [],
        edgeColors: new Float32Array(),
        edgeAlpha: new Float32Array(),
        edgeKinds: new Uint8Array(),
    };
}

function emptyRendererScene(): GalaxySceneV2 {
    return {
        sourceMode: 'graph',
        layoutMode: 'single',
        ids: [],
        labels: [],
        kinds: [],
        groupIds: [],
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array(),
        positions2d: new Float32Array(),
        radii: new Float32Array(),
        colors: new Float32Array(),
        edgePairs: new Uint32Array(),
        edgeIds: [],
        edgeTypes: [],
        edgeColors: new Float32Array(),
        edgeAlpha: new Float32Array(),
        edgeKinds: new Uint8Array(),
    };
}

function gpuEdgeScene(layoutMode: GalaxySceneV2['layoutMode'], edgeCount: number): GalaxySceneV2 {
    const nodeCount = edgeCount + 1;
    const pairs = new Uint32Array(edgeCount * 2);
    for (let edge = 0; edge < edgeCount; edge++) {
        pairs[edge * 2] = edge;
        pairs[edge * 2 + 1] = edge + 1;
    }
    return {
        ...emptyRendererScene(),
        layoutMode,
        ids: Array.from({ length: nodeCount }, (_, index) => `node:${index}`),
        labels: Array.from({ length: nodeCount }, (_, index) => `Node ${index}`),
        kinds: Array.from({ length: nodeCount }, () => 'concept'),
        groupIds: Array.from({ length: nodeCount }, () => ''),
        positions3d: new Float32Array(nodeCount * 3),
        positions2d: new Float32Array(nodeCount * 3),
        radii: new Float32Array(nodeCount).fill(0.08),
        colors: new Float32Array(nodeCount * 3).fill(0.5),
        edgePairs: pairs,
        edgeIds: Array.from({ length: edgeCount }, (_, index) => `edge:${index}`),
        edgeTypes: Array.from({ length: edgeCount }, () => 'related'),
        edgeColors: new Float32Array(edgeCount * 6).fill(0.5),
        edgeAlpha: new Float32Array(edgeCount).fill(0.18),
        edgeKinds: new Uint8Array(edgeCount),
    };
}

function collectGuideKinds(root: THREE.Object3D): Set<string> {
    const kinds = new Set<string>();
    root.traverse((child) => {
        const kind = child.userData?.['guideKind'];
        if (typeof kind === 'string') kinds.add(kind);
    });
    return kinds;
}
