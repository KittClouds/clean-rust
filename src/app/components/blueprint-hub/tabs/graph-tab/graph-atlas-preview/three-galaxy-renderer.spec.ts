import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { entityColorStore, hexColorToHsl } from '../../../../../lib/store/entityColorStore';
import { buildGalaxyScene, hslToRgb, mergeGalaxySettings } from './graph-galaxy-engine';
import { buildGalaxyFocusMask } from './graph-galaxy-focus';
import { galaxySceneToV2, type GalaxySceneV2 } from './graph-galaxy-scene-v2';
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
        renderer.edges?.geometry.dispose();
        (renderer.edges?.material as THREE.Material | undefined)?.dispose();
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
