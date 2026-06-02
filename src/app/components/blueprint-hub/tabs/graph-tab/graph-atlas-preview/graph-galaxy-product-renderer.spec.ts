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
import { buildGalaxyGlows } from './graph-galaxy-objects';
import { ThreeGalaxyRenderer } from './three-galaxy-renderer';

type RendererProbe = {
    setSettings(settings: Record<string, unknown>): void;
    edgeMaterialOpacity(): number;
    edgeStrokeCount(data?: { edgeAlpha: Float32Array; edgeKinds: Uint8Array }, edge?: number): number;
    edgeStrokeOffset(data?: { edgeAlpha: Float32Array; edgeKinds: Uint8Array }, edge?: number): number;
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
    productKleinLayerOpacity(layer: string): number;
    tubeEdgeTerminalFlourish(data: { layoutMode: string }, t: number, lift: number, sign: number): number;
    capsSurfaceEdge(data: { layoutMode: string }, ax: number, ay: number, az: number, bx: number, by: number, bz: number): boolean;
    capsSurfacePoint(out: THREE.Vector3, ax: number, ay: number, az: number, bx: number, by: number, bz: number, t: number): boolean;
    writeLorentzGuidePositions(output: Float32Array, cursor: number, guide: Record<string, unknown>, data: { ids: string[] }, positions: Float32Array, indexById: Map<string, number>): number;
    guideAttachmentContract(data: { layoutMode: string }): { liveLorentzGuides: boolean; localScale: number };
    guidePositionsForContract(positions: Float32Array, contract: { liveLorentzGuides: boolean; localScale: number }): Float32Array;
};

type CameraProbe = RendererProbe & {
    renderer: { render: ReturnType<typeof vi.fn>; domElement: { clientWidth: number; clientHeight: number } };
    perspective: THREE.PerspectiveCamera;
    panX: number;
    panY: number;
    panZ: number;
    viewShiftX: number;
    viewShiftY: number;
    resetCamera(): void;
    rotate(deltaX: number, deltaY: number): void;
    zoomAt(delta: number, pointer: { x: number; y: number; width: number; height: number }): void;
    pointerToCameraTargetPlane(pointer: { x: number; y: number; width: number; height: number }, out: THREE.Vector3): boolean;
};

function mountCameraProbe(): CameraProbe {
    const renderer = new ThreeGalaxyRenderer() as unknown as CameraProbe;
    renderer.renderer = { render: vi.fn(), domElement: { clientWidth: 800, clientHeight: 600 } };
    renderer.resetCamera();
    return renderer;
}

describe('Galaxy camera controls', () => {
    it('keeps wheel zoom framing separate from the 3D orbit pivot', () => {
        const renderer = mountCameraProbe();
        const pointer = { x: 620, y: 250, width: 800, height: 600 };
        const anchor = new THREE.Vector3();
        const pointerNdcX = (pointer.x / pointer.width) * 2 - 1;
        const pointerNdcY = -(pointer.y / pointer.height) * 2 + 1;

        expect(renderer.pointerToCameraTargetPlane(pointer, anchor)).toBe(true);

        renderer.zoomAt(-360, pointer);

        expect(renderer.panX).toBeCloseTo(0);
        expect(renderer.panY).toBeCloseTo(0);
        expect(renderer.panZ).toBeCloseTo(0);
        expect(Math.abs(renderer.viewShiftX) + Math.abs(renderer.viewShiftY)).toBeGreaterThan(0.001);

        const projected = anchor.clone().project(renderer.perspective);
        expect(projected.x).toBeCloseTo(pointerNdcX, 4);
        expect(projected.y).toBeCloseTo(pointerNdcY, 4);

        renderer.rotate(80, -20);

        expect(renderer.panX).toBeCloseTo(0);
        expect(renderer.panY).toBeCloseTo(0);
        expect(renderer.panZ).toBeCloseTo(0);
    });
});

describe('Product manifold guide styling', () => {
    it('keeps evidence fibers visually above scaffold and Lorentz guides', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const productDataWeight = renderer.hopfGuideWeightForKind('dataFiber', 'product');
        const productScaffoldWeight = renderer.hopfGuideWeightForKind('torusBand', 'product');

        const productData = renderer.hopfLayerOpacity('line', 'dataFiber', productDataWeight, 'product');
        const productScaffold = renderer.hopfLayerOpacity('line', 'torusBand', productScaffoldWeight, 'product');
        const productLorentz = renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'product');

        expect(productData).toBeGreaterThan(productScaffold * 4);
        expect(productData).toBeGreaterThan(productLorentz);
        expect(renderer.hopfTubeOpacity('torusBand', false, 'product')).toBe(0);
        expect(renderer.hopfTubeOpacity('torusBand', false, 'default')).toBeGreaterThan(0);
    });

    it('keeps Product fibers leaner and dimmer while preserving Hopf space control', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        expect(renderer.hopfTubeRadius('dataFiber', 'tubeCore', 'product')).toBeCloseTo(0.0050625);
        expect(renderer.hopfTubeRadius('dataFiber', 'tubeGlow', 'product')).toBeCloseTo(0.0162);
        expect(renderer.hopfTubeOpacity('dataFiber', false, 'product')).toBeCloseTo(0.11424);

        renderer.setSettings({ hopfSpaceIntensity: 0 });
        expect(renderer.hopfTubeOpacity('dataFiber', false, 'product')).toBe(0);
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

    it('makes Lorentz space and Glow sliders affect visible Product geometry', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        const baseLorentz = renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'product');
        renderer.setSettings({ lorentzSpaceIntensity: 0 });
        expect(renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'product')).toBe(0);
        renderer.setSettings({ lorentzSpaceIntensity: 1.4 });
        expect(renderer.lorentzLayerOpacity('line', 'membership', 'identity', 1, 'product')).toBeGreaterThan(baseLorentz * 1.25);

        renderer.setSettings({ glow: 0 });
        const lowEdge = renderer.edgeMaterialOpacity();
        const lowShell = renderer.hybridShellOpacity();
        renderer.setSettings({ glow: 1.8 });
        expect(renderer.edgeMaterialOpacity()).toBeGreaterThan(lowEdge * 1.6);
        expect(renderer.hybridShellOpacity()).toBeLessThan(lowShell * 1.5);
    });

    it('adds a tube edge mode with confidence-weighted thickness', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const data = {
            edgeAlpha: new Float32Array([0.18, 1]),
            edgeKinds: new Uint8Array([0, 1]),
        };

        renderer.setSettings({ edgeMode: 'tube', edgeWidth: 1.1, edgeOpacity: 0.7, glow: 1.8 });

        expect(renderer.edgeMaterialOpacity()).toBeLessThan(0.35);
        expect(renderer.edgeStrokeCount(data, 1)).toBeGreaterThan(renderer.edgeStrokeCount(data, 0));
        expect(renderer.edgeStrokeOffset(data, 1)).toBeGreaterThan(renderer.edgeStrokeOffset(data, 0));
    });

    it('adds a terminal curl only to Lorentz-style tube edges', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'siegelFinsler' }, 0.9, 0.3, 1)).toBeGreaterThan(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'siegelFinsler' }, 0.5, 0.3, 1)).toBe(0);
        expect(renderer.tubeEdgeTerminalFlourish({ layoutMode: 'productManifold' }, 0.9, 0.3, 1)).toBe(0);
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

        expect(renderer.lorentzTubeRadius({ guideKind: 'membership' }, 'tubeCore', 'product')).toBeCloseTo(0.00396);
        expect(renderer.lorentzTubeRadius({ guideKind: 'membership' }, 'tubeGlow', 'product')).toBeCloseTo(0.01125);
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

    it('preserves Product Lorentz lane colors instead of washing them to cyan', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        const causalGuide = {
            id: 'lorentz:product-guide:causal',
            guideKind: 'membership',
            treeKind: 'causal',
            level: 2,
            color: { r: 0.92, g: 0.38, b: 0.12 },
        };
        const documentGuide = {
            id: 'lorentz:product-guide:document',
            guideKind: 'membership',
            treeKind: 'documentStructure',
            level: 1,
            color: { r: 0.14, g: 0.46, b: 0.9 },
        };
        const causalTint = renderer.lorentzGuideTint(causalGuide, 0, 'product');
        const documentTint = renderer.lorentzGuideTint(documentGuide, 0, 'product');
        const causalLine = new Float32Array(3);

        renderer.writeLorentzGuideColor(causalLine, 0, causalGuide, 0, 0.5, 'product');

        expect(causalTint.r).toBeGreaterThan(causalTint.b * 2);
        expect(documentTint.b).toBeGreaterThan(documentTint.r * 2);
        expect(causalLine[0]).toBeGreaterThan(causalLine[2] * 2);
    });

    it('keeps the Product Klein ball as its own toggleable layer', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;

        expect(renderer.productKleinLayerOpacity('boundary')).toBeGreaterThan(0);
        expect(renderer.productKleinLayerOpacity('chord')).toBeGreaterThan(renderer.productKleinLayerOpacity('boundary'));

        renderer.setSettings({ productKleinVisible: false });
        expect(renderer.productKleinLayerOpacity('boundary')).toBe(0);
        expect(renderer.productKleinLayerOpacity('chord')).toBe(0);
    });

    it('prevents dense node overlaps from additive halo blowout', () => {
        const glows = buildGalaxyGlows({ ids: ['a'] } as any, new THREE.Texture());
        const material = glows?.children[0] instanceof THREE.Sprite ? glows.children[0].material : null;
        expect(material?.blending).toBe(THREE.NormalBlending);

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

    it('uses one live guide attachment contract for Product and Siegel spaces', () => {
        const renderer = new ThreeGalaxyRenderer() as unknown as RendererProbe;
        renderer.setSettings({ edgeLength: 1.4, nodeDistance: 1.25 });
        const product = renderer.guideAttachmentContract({ layoutMode: 'productManifold' });
        const siegel = renderer.guideAttachmentContract({ layoutMode: 'siegelFinsler' });
        const caps = renderer.guideAttachmentContract({ layoutMode: 'lorentzTree' });
        const hybrid = renderer.guideAttachmentContract({ layoutMode: 'hybridSpace' });
        const positions = new Float32Array([2, 0, 0, 4, 0, 0]);
        const productLocal = renderer.guidePositionsForContract(positions, product);

        expect(product.liveLorentzGuides).toBe(true);
        expect(product.localScale).toBeGreaterThan(1);
        expect(productLocal[0]).toBeLessThan(positions[0]);
        expect(siegel).toEqual({ liveLorentzGuides: true, localScale: 1 });
        expect(caps).toEqual({ liveLorentzGuides: true, localScale: 1 });
        expect(hybrid.liveLorentzGuides).toBe(false);
    });
});
