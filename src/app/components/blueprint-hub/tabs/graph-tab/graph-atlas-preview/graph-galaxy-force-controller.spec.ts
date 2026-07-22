import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import {
    GALAXY_INTERACTIVE_FORCE_NEIGHBOR_LIMIT,
    GALAXY_INTERACTIVE_FORCE_NODE_LIMIT,
    GraphGalaxyForceController,
    transitManifoldExpansionScale,
} from './graph-galaxy-force-controller';
import { attachGalaxySceneRuntimeIndex, type GalaxySceneV2 } from './graph-galaxy-scene-v2';

describe('GraphGalaxyForceController Hybrid constraints', () => {
    it('keeps shell nodes on the Hybrid shell when force dragging', () => {
        const scene = hybridScene([
            [2.32, 0, 0],
            [0.55, 0.1, 0.08],
        ]);
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('shell')).toBe(true);
        controller.dragTo(new THREE.Vector3(8, 0, 0), 'force');

        expect(radius3d(scene.positions3d, 0)).toBeCloseTo(2.32, 3);
        expect(radius3d(scene.positions3d, 1)).toBeLessThanOrEqual(2.32);
    });

    it('clamps inner Hybrid nodes inside the shell when stretched past the boundary', () => {
        const scene = hybridScene([
            [2.32, 0, 0],
            [0.55, 0.1, 0.08],
        ]);
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('inner')).toBe(true);
        controller.dragTo(new THREE.Vector3(-9, 0, 0), 'force');

        expect(radius3d(scene.positions3d, 1)).toBeLessThanOrEqual(2.32);
    });

    it('keeps Hopf force dragging inside the projection envelope', () => {
        const scene = hopfScene([
            [1.2, 0.1, 0.05],
            [0.45, -0.25, 0.2],
        ]);
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('shell')).toBe(true);
        controller.dragTo(new THREE.Vector3(9, 0, 0), 'force');

        expect(radius3d(scene.positions3d, 0)).toBeLessThanOrEqual(1.95);
        expect(radius3d(scene.positions3d, 1)).toBeLessThanOrEqual(1.95);
    });

    it('keeps hierarchy cap nodes on the Lorentz skin while force dragging', () => {
        const scene = capsScene([
            [2.14, 0, 0],
            [0.62, 0.2, 0.04],
        ]);
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('shell')).toBe(true);
        controller.dragTo(new THREE.Vector3(8, 1, 0), 'force');

        expect(radius3d(scene.positions3d, 0)).toBeCloseTo(2.14, 3);
        expect(radius3d(scene.positions3d, 1)).toBeLessThanOrEqual(2.18);
    });

    it('repairs explicit Caps hierarchy shells before rendering', () => {
        const scene = capsScene([
            [0.82, 0, 0],
            [2.04, 0, 0],
        ], new Float32Array([2.08, 1.42]));
        const controller = new GraphGalaxyForceController();

        controller.bind(scene);
        controller.setMode('3d');

        expect(radius3d(scene.positions3d, 0)).toBeCloseTo(2.08, 3);
        expect(radius3d(scene.positions3d, 1)).toBeCloseTo(1.42, 3);
    });

    it('pulls Hopf fiber nodes back toward their rail during stretched interactions', () => {
        const scene = hopfScene([
            [1.2, 0.1, 0.05],
            [0, 0.8, 0.2],
        ], new Uint8Array([1, 2]));
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('shell')).toBe(true);
        controller.drag(new THREE.Vector3(1, 0, 0), 'stretch');

        expect(scene.positions3d[3]).toBeGreaterThan(0);
        expect(scene.positions3d[3]).toBeLessThan(0.14);
    });

    it('expands Transit positions volumetrically from the canonical shape', () => {
        const scene = productScene([
            [1, 0.25, 0.5],
            [-0.5, 0.2, -0.4],
        ]);
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);

        controller.setSettings({ layoutMode: 'transitManifold', nodeDistance: 2.2, edgeLength: 1.7 });

        const scale = transitManifoldExpansionScale({ nodeDistance: 2.2, edgeLength: 1.7 });
        expect(scene.positions3d[0]).toBeCloseTo(1 * scale, 5);
        expect(scene.positions3d[1]).toBeCloseTo(0.25 * scale, 5);
        expect(scene.positions3d[2]).toBeCloseTo(0.5 * scale, 5);
        expect(radius3d(scene.positions3d, 1)).toBeCloseTo(Math.hypot(-0.5, 0.2, -0.4) * scale, 5);
    });

    it('keeps Transit force mode bounded instead of starting raw graph physics', () => {
        const scene = productScene([
            [1.2, 0.1, 0.05],
            [0.45, -0.25, 0.2],
        ]);
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('shell')).toBe(true);
        controller.dragTo(new THREE.Vector3(9, 9, 9), 'force');
        expect(radius3d(scene.positions3d, 0)).toBeLessThanOrEqual(2.32);

        controller.end('force');
        for (let tick = 0; tick < 8; tick++) controller.tick();

        expect(radius3d(scene.positions3d, 0)).toBeLessThanOrEqual(2.32);
        expect(radius3d(scene.positions3d, 1)).toBeLessThanOrEqual(2.32);
    });

    it('fails closed above the force threshold and moves only a bounded local neighborhood', () => {
        const scene = attachGalaxySceneRuntimeIndex(largeStarScene(GALAXY_INTERACTIVE_FORCE_NODE_LIMIT + 80));
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);
        controller.setMode('3d');

        expect(controller.begin('node:0')).toBe(true);
        expect(controller.dragTo(new THREE.Vector3(1, 0, 0), 'force')).toBe(true);
        expect(controller.end('force')).toBe(false);
        expect(controller.tick()).toBe(false);

        let moved = 0;
        for (let index = 0; index < scene.ids.length; index++) {
            if (scene.positions3d[index * 3] !== 0) moved += 1;
        }
        expect(moved).toBeLessThanOrEqual(GALAXY_INTERACTIVE_FORCE_NEIGHBOR_LIMIT + 1);
        expect(moved).toBeGreaterThan(1);
    });

    it('rejects large projected-manifold dragging without a bounded native neighborhood', () => {
        const scene = attachGalaxySceneRuntimeIndex(largeStarScene(GALAXY_INTERACTIVE_FORCE_NODE_LIMIT + 1));
        scene.layoutMode = 'hopfProjection';
        const controller = new GraphGalaxyForceController();
        controller.bind(scene);

        expect(controller.begin('node:0')).toBe(false);
    });
});

function hybridScene(points: Array<[number, number, number]>): GalaxySceneV2 {
    return projectedScene('hybridSpace', points);
}

function hopfScene(points: Array<[number, number, number]>, hopfRoles?: Uint8Array): GalaxySceneV2 {
    return projectedScene('hopfProjection', points, hopfRoles);
}

function productScene(points: Array<[number, number, number]>): GalaxySceneV2 {
    return projectedScene('transitManifold', points);
}

function capsScene(points: Array<[number, number, number]>, hierarchyShellRadii?: Float32Array): GalaxySceneV2 {
    return projectedScene('lorentzTree', points, undefined, hierarchyShellRadii);
}

function projectedScene(
    layoutMode: GalaxySceneV2['layoutMode'],
    points: Array<[number, number, number]>,
    hopfRoles?: Uint8Array,
    hierarchyShellRadii?: Float32Array,
): GalaxySceneV2 {
    const positions3d = new Float32Array(points.length * 3);
    const positions2d = new Float32Array(points.length * 3);
    for (let index = 0; index < points.length; index++) {
        const offset = index * 3;
        const [x, y, z] = points[index];
        positions3d[offset] = x;
        positions3d[offset + 1] = y;
        positions3d[offset + 2] = z;
        positions2d[offset] = x;
        positions2d[offset + 1] = y;
    }
    return {
        sourceMode: 'embeddings',
        layoutMode,
        ids: ['shell', 'inner'],
        labels: ['Shell', 'Inner'],
        kinds: ['leaf', 'entity'],
        groupIds: ['', ''],
        hopfRoles,
        hierarchyShellRadii,
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d,
        positions2d,
        radii: new Float32Array([0.08, 0.08]),
        colors: new Float32Array([0, 1, 1, 0.7, 0.2, 1]),
        edgePairs: new Uint32Array([0, 1]),
        edgeColors: new Float32Array(6),
        edgeAlpha: new Float32Array([1]),
        edgeKinds: new Uint8Array([0]),
    };
}

function radius3d(buffer: Float32Array, index: number): number {
    const offset = index * 3;
    return Math.hypot(buffer[offset], buffer[offset + 1], buffer[offset + 2]);
}

function largeStarScene(count: number): GalaxySceneV2 {
    const edgeCount = count - 1;
    const edgePairs = new Uint32Array(edgeCount * 2);
    for (let edge = 0; edge < edgeCount; edge++) {
        edgePairs[edge * 2] = 0;
        edgePairs[edge * 2 + 1] = edge + 1;
    }
    return {
        ...projectedScene('single', Array.from({ length: count }, () => [0, 0, 0])),
        ids: Array.from({ length: count }, (_, index) => `node:${index}`),
        labels: Array.from({ length: count }, (_, index) => `Node ${index}`),
        kinds: Array.from({ length: count }, () => 'entity'),
        groupIds: Array.from({ length: count }, () => ''),
        radii: new Float32Array(count).fill(0.08),
        colors: new Float32Array(count * 3),
        edgePairs,
        edgeIds: Array.from({ length: edgeCount }, (_, index) => `edge:${index}`),
        edgeTypes: Array.from({ length: edgeCount }, () => 'related'),
        edgeColors: new Float32Array(edgeCount * 6),
        edgeAlpha: new Float32Array(edgeCount).fill(1),
        edgeKinds: new Uint8Array(edgeCount),
    };
}
