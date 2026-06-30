import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { entityColorStore, hexColorToHsl } from '../../../../../lib/store/entityColorStore';
import { buildGalaxyScene, hslToRgb, mergeGalaxySettings } from './graph-galaxy-engine';
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

    it('does not recolor source-node Transit guides away from the Style Lab chunk color', () => {
        const renderer = Object.create(ThreeGalaxyRenderer.prototype) as RendererColorHarness;
        const expected = sceneWithStyleLabColor('#1560c1').expected;
        const sourceColor = { r: expected.r, g: expected.g, b: expected.b };
        const guide = {
            id: 'transit:backbone:lane:chunk',
            guideKind: 'rootLane',
            level: 2,
            color: { r: 0.1, g: 0.9, b: 0.85 },
            sourceColor,
        };
        const colors = new Float32Array(3);

        renderer.writeLorentzGuideColor(colors, 0, guide, 0, 0.25, 'transit');
        expectRendererColor(new THREE.Color(colors[0], colors[1], colors[2]), expected);

        const tint = renderer.lorentzGuideTint(guide, 3, 'transit');
        expectRendererColor(new THREE.Color(tint.r, tint.g, tint.b), expected);
    });
});
