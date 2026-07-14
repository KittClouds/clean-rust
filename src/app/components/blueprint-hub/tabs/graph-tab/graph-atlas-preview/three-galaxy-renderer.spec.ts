import { describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';

vi.mock('./graph-galaxy-textures', async () => {
    const three = await import('three');
    const texture = () => new three.Texture();
    return {
        makeAtomTexture: texture,
        makeHaloTexture: texture,
        makeNodeTexture: texture,
        makeLabelSprite: () => new three.Sprite(new three.SpriteMaterial({ map: texture() })),
    };
});

import { entityColorStore, hexColorToHsl } from '../../../../../lib/store/entityColorStore';
import { buildGalaxyScene, hslToRgb, mergeGalaxySettings } from './graph-galaxy-engine';
import { buildGalaxyFocusMask } from './graph-galaxy-focus';
import { galaxySceneToV2, type GalaxyLorentzGuideView, type GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { ThreeGalaxyRenderer } from './three-galaxy-renderer';

type RendererColorHarness = {
    color: THREE.Color;
    nodeColor(data: GalaxySceneV2, index: number): void;
    glowColor(data: GalaxySceneV2, index: number): void;
    writeLorentzGuideColor(
        colors: Float32Array,
        offset: number,
        guide: {
            id: string;
            guideKind: string;
            level: number;
            color: { r: number; g: number; b: number };
            sourceColor?: { r: number; g: number; b: number };
        },
        index: number,
        phase: number,
        surface: 'default' | 'transit',
        focusScale?: number,
    ): void;
    lorentzGuideTint(
        guide: {
            id: string;
            guideKind: string;
            color: { r: number; g: number; b: number };
            sourceColor?: { r: number; g: number; b: number };
        },
        index: number,
        surface?: 'default' | 'transit',
    ): { r: number; g: number; b: number };
};

type EdgeGeometryHarness = {
    settings: ReturnType<typeof mergeGalaxySettings>;
    mode: '3d';
    edges: THREE.LineSegments | null;
    edgeSurfacePoint: THREE.Vector3;
    edgeCurvePoint: { x: number; y: number; z: number };
    color: THREE.Color;
    buildEdges(scene: GalaxySceneV2): THREE.LineSegments | null;
    updateEdgeGeometry(data: GalaxySceneV2, positions: Float32Array, focus: ReturnType<typeof buildGalaxyFocusMask>): void;
    updateEdgeColors(data: GalaxySceneV2, positions: Float32Array, focus: ReturnType<typeof buildGalaxyFocusMask>): void;
};

type GuideRetentionHarness = {
    guideEndpointsChanged(
        owner: THREE.Object3D,
        guide: GalaxyLorentzGuideView,
        data: GalaxySceneV2,
        positions: Float32Array,
        indexById: Map<string, number>,
    ): boolean;
};

type PickIndexHarness = {
    pickIndexDirty: boolean;
    pickNodeBins: number[][];
    ensureScreenPickIndex(pointer: { x: number; y: number; width: number; height: number }): void;
    pickCandidates(bins: number[][], x: number, y: number): readonly number[];
};

type MapPanHarness = {
    mode: '2d';
    ortho: THREE.OrthographicCamera;
    viewportHeight: number;
    panX: number;
    panY: number;
    pan(deltaX: number, deltaY: number): void;
    updateCamera(): void;
};

function sceneWithStyleLabColor(hex: string): { scene: GalaxySceneV2; expected: THREE.Color } {
    const rgb = hslToRgb(hexColorToHsl(hex));
    const scene = {
        colors: new Float32Array([rgb.r / 255, rgb.g / 255, rgb.b / 255]),
    } as GalaxySceneV2;
    return { scene, expected: new THREE.Color(rgb.r / 255, rgb.g / 255, rgb.b / 255) };
}

function expectRendererColor(color: THREE.Color, expected: THREE.Color): void {
    expect(color.r).toBeCloseTo(expected.r, 6);
    expect(color.g).toBeCloseTo(expected.g, 6);
    expect(color.b).toBeCloseTo(expected.b, 6);
}

describe('ThreeGalaxyRenderer map panning', () => {
    it('moves the orthographic view one screen pixel per pointer pixel', () => {
        const renderer = Object.create(ThreeGalaxyRenderer.prototype) as MapPanHarness;
        renderer.mode = '2d';
        renderer.ortho = new THREE.OrthographicCamera(-4.2, 4.2, 3.1, -3.1, 0.01, 100);
        renderer.ortho.zoom = 2;
        renderer.viewportHeight = 620;
        renderer.panX = 0;
        renderer.panY = 0;
        renderer.updateCamera = vi.fn();

        renderer.pan(100, -50);

        const worldUnitsPerPixel = 6.2 / 2 / 620;
        expect(renderer.panX).toBeCloseTo(-100 * worldUnitsPerPixel, 10);
        expect(renderer.panY).toBeCloseTo(-50 * worldUnitsPerPixel, 10);
        expect(renderer.updateCamera).toHaveBeenCalledOnce();
    });
});

describe('ThreeGalaxyRenderer Style Lab node colors', () => {
    it('uses the scene buffer color exactly for chunk nodes and glows', () => {
        const renderer = Object.create(ThreeGalaxyRenderer.prototype) as RendererColorHarness;
        renderer.color = new THREE.Color();
        const { scene, expected } = sceneWithStyleLabColor('#1560c1');

        renderer.nodeColor(scene, 0);
        expectRendererColor(renderer.color, expected);

        renderer.glowColor(scene, 0);
        expectRendererColor(renderer.color, expected);
    });

    it('keeps graph-source chunk colors on the Style Lab contract through render', () => {
        const chunkHsl = hexColorToHsl('#1560c1');
        entityColorStore.setGraphNodeColor('chunk', chunkHsl);
        try {
            const scene = buildGalaxyScene([{
                id: 'graph:chunk:one',
                label: 'Chunk one',
                kind: 'chunk',
                colorHsl: '176 70% 46%',
                metadata: {
                    graphColorKind: 'chunk',
                    graphKind: 'chunk',
                    sourceType: 'chunk',
                },
            }], [], mergeGalaxySettings({
                layoutMode: 'transitManifold',
                embeddingTopologyMode: 'lanes',
            }));
            const v2 = galaxySceneToV2(scene, 'graph');
            const renderer = Object.create(ThreeGalaxyRenderer.prototype) as RendererColorHarness;
            renderer.color = new THREE.Color();
            const expected = sceneWithStyleLabColor('#1560c1').expected;

            expectRendererColor(new THREE.Color(v2.colors[0], v2.colors[1], v2.colors[2]), expected);

            renderer.nodeColor(v2, 0);
            expectRendererColor(renderer.color, expected);
        } finally {
            entityColorStore.reset();
        }
    });

    it('uses Transit guide colors even when sourceColor belongs to another node', () => {
        const renderer = Object.create(ThreeGalaxyRenderer.prototype) as RendererColorHarness & { stableUnit: () => number };
        renderer.stableUnit = () => 0;
        const expected = sceneWithStyleLabColor('#1560c1').expected;
        const sourceColor = { r: 0.14, g: 0.78, b: 0.74 };
        const laneGuide = {
            id: 'transit:backbone:lane:chunk',
            guideKind: 'rootLane',
            level: 0,
            color: { r: expected.r, g: expected.g, b: expected.b },
            sourceColor,
        };
        const laneColors = new Float32Array(3);
        const guide = {
            id: 'transit:backbone:route:root-chunk',
            guideKind: 'membership',
            level: 2,
            color: { r: expected.r, g: expected.g, b: expected.b },
            sourceColor,
        };
        const colors = new Float32Array(3);

        renderer.writeLorentzGuideColor(laneColors, 0, laneGuide, 0, 0, 'transit');
        expect(laneColors[0]).toBeCloseTo(expected.r * 0.66, 6);
        expect(laneColors[1]).toBeCloseTo(expected.g * 0.7, 6);
        expect(laneColors[2]).toBeCloseTo(expected.b * 0.74, 6);

        const laneTint = renderer.lorentzGuideTint(laneGuide, 0, 'transit');
        expectRendererColor(new THREE.Color(laneTint.r, laneTint.g, laneTint.b), expected);

        renderer.writeLorentzGuideColor(colors, 0, guide, 0, 0.25, 'transit');
        expect(colors[2]).toBeGreaterThan(colors[1]);
        expect(colors[1]).toBeLessThan(sourceColor.g * 0.6);

        const tint = renderer.lorentzGuideTint(guide, 3, 'transit');
        expect(tint.b).toBeGreaterThan(tint.g);
        expect(tint.g).toBeLessThan(sourceColor.g * 0.8);

        const hubGuide = {
            id: 'transit:plan:hub:kai',
            guideKind: 'rootLane',
            level: 2,
            color: { r: 0.2, g: 0.2, b: 0.2 },
            sourceColor,
        };
        const hubColors = new Float32Array(3);

        renderer.writeLorentzGuideColor(hubColors, 0, hubGuide, 0, 0.25, 'transit');
        expectRendererColor(new THREE.Color(hubColors[0], hubColors[1], hubColors[2]), new THREE.Color(sourceColor.r, sourceColor.g, sourceColor.b));

        const hubTint = renderer.lorentzGuideTint(hubGuide, 3, 'transit');
        expectRendererColor(new THREE.Color(hubTint.r, hubTint.g, hubTint.b), new THREE.Color(sourceColor.r, sourceColor.g, sourceColor.b));
    });
});

describe('ThreeGalaxyRenderer curved edge geometry', () => {
    it('samples normal curved edges densely enough to avoid faceted kinks', () => {
        const scene = rendererEdgeScene();
        const renderer = edgeGeometryHarness();

        renderer.edges = renderer.buildEdges(scene);
        renderer.updateEdgeGeometry(scene, scene.positions3d, buildGalaxyFocusMask(scene, null, null));

        expect(renderer.edges?.geometry.drawRange.count).toBe(32);
        expect(renderer.edges?.geometry.getAttribute('position').array.length).toBe(32 * 3);
        expect(renderer.edges?.geometry.getAttribute('color').array.length).toBe(32 * 3);
        renderer.edges?.geometry.dispose();
        (renderer.edges?.material as THREE.Material | undefined)?.dispose();
    });

    it('allocates nothing for hidden edges', () => {
        const renderer = edgeGeometryHarness();
        renderer.settings = mergeGalaxySettings({ edgeMode: 'hidden' });

        expect(renderer.buildEdges(rendererEdgeScene())).toBeNull();
    });

    it('updates focus colors without uploading edge positions', () => {
        const scene = rendererEdgeScene();
        const renderer = edgeGeometryHarness();
        renderer.edges = renderer.buildEdges(scene);
        renderer.updateEdgeGeometry(scene, scene.positions3d, buildGalaxyFocusMask(scene, null, null));
        const position = renderer.edges?.geometry.getAttribute('position') as THREE.BufferAttribute;
        const version = position.version;

        renderer.updateEdgeColors(scene, scene.positions3d, buildGalaxyFocusMask(scene, 'a', null));

        expect(position.version).toBe(version);
        renderer.edges?.geometry.dispose();
        (renderer.edges?.material as THREE.Material | undefined)?.dispose();
    });
});

describe('ThreeGalaxyRenderer guide geometry retention', () => {
    it('invalidates a membership guide only when one of its endpoints changes', () => {
        const renderer = Object.create(ThreeGalaxyRenderer.prototype) as GuideRetentionHarness;
        const owner = new THREE.Object3D();
        const scene = rendererEdgeScene();
        const guide = {
            id: 'membership:a-b',
            nodeIds: ['a', 'b'],
            positions3d: scene.positions3d,
            positions2d: scene.positions2d,
            color: { r: 1, g: 1, b: 1 },
            importance: 1,
            treeId: 'tree',
            treeKind: 'document',
            level: 1,
            guideKind: 'membership',
            guideWeight: 1,
        } satisfies GalaxyLorentzGuideView;
        const index = new Map([['a', 0], ['b', 1]]);

        expect(renderer.guideEndpointsChanged(owner, guide, scene, scene.positions3d, index)).toBe(true);
        expect(renderer.guideEndpointsChanged(owner, guide, scene, scene.positions3d, index)).toBe(false);
        scene.positions3d[3] += 0.25;
        expect(renderer.guideEndpointsChanged(owner, guide, scene, scene.positions3d, index)).toBe(true);
    });
});

describe('ThreeGalaxyRenderer large-scene picking performance contract', () => {
    it('retains the screen index and narrows a 10k-node pointer query to local bins', () => {
        const renderer = new ThreeGalaxyRenderer();
        const scene = largePickScene(10_000);
        renderer.installScene(scene, mergeGalaxySettings({ edgeMode: 'hidden' }), '3d');
        renderer.resetCamera();
        const harness = renderer as unknown as PickIndexHarness;
        const pointer = { x: 400, y: 300, width: 800, height: 600 };

        harness.ensureScreenPickIndex(pointer);
        const bins = harness.pickNodeBins;
        const centerCandidates = harness.pickCandidates(bins, pointer.x, pointer.y).length;
        harness.ensureScreenPickIndex(pointer);

        expect(harness.pickIndexDirty).toBe(false);
        expect(harness.pickNodeBins).toBe(bins);
        expect(centerCandidates).toBeGreaterThan(0);
        expect(centerCandidates).toBeLessThan(1_000);
        renderer.dispose();
    });
});

describe('ThreeGalaxyRenderer shortest-path overlay', () => {
    it('allocates only the selected walk when ordinary edges are hidden', () => {
        const renderer = new ThreeGalaxyRenderer();
        const scene = rendererEdgeScene();
        renderer.installScene(scene, mergeGalaxySettings({ edgeMode: 'hidden' }), '3d', ['a', 'b']);
        const harness = renderer as unknown as {
            edges: THREE.LineSegments | null;
            pathEdges: THREE.LineSegments | null;
            focusMask: ReturnType<typeof buildGalaxyFocusMask> | null;
        };

        expect(harness.edges).toBeNull();
        expect(harness.focusMask?.pathFound).toBe(true);
        expect(Array.from(harness.focusMask?.pathEdgeIndices ?? [])).toEqual([0]);
        expect(harness.pathEdges).not.toBeNull();
        expect(harness.pathEdges?.geometry.getAttribute('position').count).toBe(32);
        expect(harness.pathEdges?.material.blending).toBe(THREE.AdditiveBlending);

        const retainedOverlay = harness.pathEdges;
        const retainedGeometry = harness.pathEdges?.geometry;
        renderer.hoverNode('a');
        expect(harness.pathEdges).toBe(retainedOverlay);
        expect(harness.pathEdges?.geometry).toBe(retainedGeometry);

        renderer.selectNodes([]);
        expect(harness.pathEdges).toBeNull();
        renderer.dispose();
    });

    it('follows a Caps shell geodesic instead of cutting a straight chord through it', () => {
        const renderer = new ThreeGalaxyRenderer();
        const scene = rendererEdgeScene();
        scene.layoutMode = 'lorentzTree';
        scene.positions3d = new Float32Array([1, 0, 0, 0, 1, 0]);
        scene.positions2d = scene.positions3d.slice();
        renderer.installScene(scene, mergeGalaxySettings({ edgeMode: 'hidden' }), '3d', ['a', 'b']);
        const harness = renderer as unknown as { pathEdges: THREE.LineSegments | null };
        const positions = harness.pathEdges?.geometry.getAttribute('position').array as Float32Array;
        let minimumRadius = Number.POSITIVE_INFINITY;
        for (let offset = 0; offset < positions.length; offset += 3) {
            minimumRadius = Math.min(minimumRadius, Math.hypot(positions[offset], positions[offset + 1], positions[offset + 2]));
        }

        expect(minimumRadius).toBeGreaterThan(0.99);
        renderer.dispose();
    });
});

function edgeGeometryHarness(): EdgeGeometryHarness {
    const renderer = Object.create(ThreeGalaxyRenderer.prototype) as EdgeGeometryHarness;
    renderer.settings = mergeGalaxySettings({ edgeMode: 'curved', edgeWidth: 0.45 });
    renderer.mode = '3d';
    renderer.edges = null;
    renderer.edgeSurfacePoint = new THREE.Vector3();
    renderer.edgeCurvePoint = { x: 0, y: 0, z: 0 };
    renderer.color = new THREE.Color();
    return renderer;
}

function rendererEdgeScene(): GalaxySceneV2 {
    return {
        sourceMode: 'graph',
        layoutMode: 'single',
        ids: ['a', 'b'],
        labels: ['A', 'B'],
        kinds: ['concept', 'concept'],
        groupIds: ['', ''],
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array([0, 0, 0, 2, 0, 0]),
        positions2d: new Float32Array([0, 0, 0, 2, 0, 0]),
        radii: new Float32Array([0.08, 0.08]),
        colors: new Float32Array([1, 0.2, 0.1, 0.1, 0.8, 1]),
        edgePairs: new Uint32Array([0, 1]),
        edgeIds: ['edge:a-b'],
        edgeTypes: ['related'],
        edgeColors: new Float32Array([1, 0.2, 0.1, 0.1, 0.8, 1]),
        edgeAlpha: new Float32Array([1]),
        edgeKinds: new Uint8Array([0]),
    };
}

function largePickScene(count: number): GalaxySceneV2 {
    const positions = new Float32Array(count * 3);
    for (let index = 0; index < count; index++) {
        positions[index * 3] = (index % 100 - 50) * 0.04;
        positions[index * 3 + 1] = (Math.floor(index / 100) - 50) * 0.04;
    }
    return {
        ...rendererEdgeScene(),
        ids: Array.from({ length: count }, (_, index) => `node:${index}`),
        labels: Array.from({ length: count }, (_, index) => `Node ${index}`),
        kinds: Array.from({ length: count }, () => 'concept'),
        groupIds: Array.from({ length: count }, () => ''),
        positions3d: positions,
        positions2d: positions.slice(),
        radii: new Float32Array(count).fill(0.08),
        colors: new Float32Array(count * 3).fill(0.5),
        edgePairs: new Uint32Array(0),
        edgeIds: [],
        edgeTypes: [],
        edgeColors: new Float32Array(0),
        edgeAlpha: new Float32Array(0),
        edgeKinds: new Uint8Array(0),
    };
}
