import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { DEFAULT_GALAXY_SETTINGS } from './graph-galaxy-engine';
import { buildGalaxyFocusMask } from './graph-galaxy-focus';
import { GraphGalaxyParticles } from './graph-galaxy-particles';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { setHopfEdgeCurvePoint, type GalaxyCurvePoint } from './graph-galaxy-edge-curves';

describe('GraphGalaxyParticles', () => {
    it('renders a bounded particle for every edge using the destination node color', () => {
        const scene = particleScene();
        const particles = new GraphGalaxyParticles();
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1 };

        particles.bind(scene, settings);
        particles.update(scene, scene.positions3d, settings, 0);

        const material = particles.points.material as THREE.ShaderMaterial;
        const color = particles.points.geometry.getAttribute('color') as THREE.BufferAttribute;
        const size = particles.points.geometry.getAttribute('flowSize') as THREE.BufferAttribute;
        expect(material.fragmentShader).toContain('gl_PointCoord');
        expect(color.count).toBe(2);
        expect(material.uniforms['uBaseSize'].value).toBeGreaterThan(4);
        expect(material.uniforms['uBaseSize'].value).toBeLessThan(5);
        expect(size.getX(0)).toBeGreaterThan(0.7);
        expect(size.getX(0)).toBeLessThan(0.75);
        expect(color.getX(0)).toBeCloseTo(0.1, 5);
        expect(color.getY(0)).toBeCloseTo(0.8, 5);
        expect(color.getZ(0)).toBeCloseTo(1, 5);
        expect(color.getX(1)).toBeCloseTo(0.9, 5);
        expect(color.getY(1)).toBeCloseTo(0.2, 5);
        expect(color.getZ(1)).toBeCloseTo(0.7, 5);

        particles.dispose();
    });

    it('follows the curved edge path and hides non-focused flow on hover', () => {
        const scene = particleScene();
        const particles = new GraphGalaxyParticles();
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'curved' as const };
        const focus = buildGalaxyFocusMask(scene, 'a', null);

        particles.bind(scene, settings);
        particles.update(scene, scene.positions3d, settings, 0, focus);

        const position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        const alpha = particles.points.geometry.getAttribute('alpha') as THREE.BufferAttribute;
        expect(position.getY(0)).toBeGreaterThan(0);
        expect(alpha.getX(0)).toBeGreaterThan(0);
        expect(alpha.getX(1)).toBe(0);

        particles.dispose();
    });

    it('keeps Hopf particles on the rendered curved edge arcs', () => {
        const scene = hopfParticleScene();
        const particles = new GraphGalaxyParticles();
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'curved' as const, edgeCurveStrength: 1 };
        const probe = particles as unknown as { seeds: number[] };

        particles.bind(scene, settings);
        probe.seeds[0] = 0.5;
        particles.update(scene, scene.positions3d, settings, 0);

        const expected = hopfArcPoint(scene, settings.edgeCurveStrength, 0, 0.5);
        const position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        const genericY = THREE.MathUtils.lerp(scene.positions3d[1], scene.positions3d[4], 0.5) + expected.lift;
        expect(position.getX(0)).toBeCloseTo(expected.x, 5);
        expect(position.getY(0)).toBeCloseTo(expected.y, 5);
        expect(position.getZ(0)).toBeCloseTo(expected.z, 5);
        expect(position.getY(0)).not.toBeCloseTo(genericY, 2);

        particles.dispose();
    });

    it('keeps particle flow on the tube edge design', () => {
        const scene = particleScene();
        const particles = new GraphGalaxyParticles();
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'tube' as const };
        const probe = particles as unknown as { seeds: number[] };

        particles.bind(scene, settings);
        probe.seeds[0] = 0.5;
        particles.update(scene, scene.positions3d, settings, 0);

        const position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        const size = particles.points.geometry.getAttribute('flowSize') as THREE.BufferAttribute;
        expect(position.getX(0)).toBeCloseTo(1, 1);
        expect(position.getY(0)).toBeGreaterThan(0);
        expect(Math.abs(position.getZ(0))).toBeGreaterThan(0);
        expect(size.getX(0)).toBeGreaterThan(0.76);

        particles.dispose();
    });

    it('keeps tree-space tube particles on the target-styled edge path', () => {
        const scene = particleScene();
        const particles = new GraphGalaxyParticles();
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'tube' as const };
        const probe = particles as unknown as {
            seeds: number[];
            edgeTubeLift(data: GalaxySceneV2, settings: typeof settings, edge: number, source: number, target: number): number;
            tubeEdgeTerminalFlourish(data: GalaxySceneV2, t: number, lift: number, sign: number): number;
        };

        const lift = probe.edgeTubeLift(scene, settings, 0, 0, 1);
        expect(lift).toBeGreaterThan(probe.edgeTubeLift({ ...scene, layoutMode: 'single' }, settings, 0, 0, 1));
        expect(probe.tubeEdgeTerminalFlourish(scene, 0.9, lift, 1)).toBeGreaterThan(0);
        expect(probe.tubeEdgeTerminalFlourish(scene, 0.1, lift, 1)).toBe(0);

        particles.bind(scene, settings);
        probe.seeds[0] = 0.9;
        particles.update(scene, scene.positions3d, settings, 0);

        const position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(position.getY(0)).toBeGreaterThan(0);
        expect(Math.abs(position.getZ(0))).toBeGreaterThan(0.01);

        particles.dispose();
    });

    it('focuses Caps selection through structural ancestors instead of semantic hubs', () => {
        const scene = structuralCapsScene();
        const focus = buildGalaxyFocusMask(scene, 'kai', null);

        expect([...focus.edgeLevels]).toEqual([2, 2, 2, 2]);
        expect(focus.nodeLevels[0]).toBeGreaterThan(0);
        expect(focus.nodeLevels[1]).toBeGreaterThan(0);
        expect(focus.nodeLevels[2]).toBeGreaterThan(0);
        expect(focus.nodeLevels[3]).toBe(3);
        expect(focus.nodeLevels[4]).toBe(2);
    });

    it('focuses Caps hierarchy both upward and downward from shell nodes', () => {
        const scene = structuralCapsScene();
        const rootFocus = buildGalaxyFocusMask(scene, 'doc', null);
        const leafFocus = buildGalaxyFocusMask(scene, 'kai', null);

        expect([...rootFocus.edgeLevels]).toEqual([2, 2, 2, 0]);
        expect(rootFocus.nodeLevels[1]).toBeGreaterThan(0);
        expect(rootFocus.nodeLevels[2]).toBeGreaterThan(0);
        expect(rootFocus.nodeLevels[3]).toBeGreaterThan(0);
        expect(rootFocus.nodeLevels[4]).toBe(0);
        expect(leafFocus.nodeLevels[0]).toBeGreaterThan(0);
        expect(leafFocus.nodeLevels[1]).toBeGreaterThan(0);
        expect(leafFocus.nodeLevels[2]).toBeGreaterThan(0);
    });

    it('focuses Siegel graph walks by Finsler hierarchy instead of dense incident edges', () => {
        const scene = siegelFocusScene();
        const focus = buildGalaxyFocusMask(scene, null, 'kai');

        expect(focus.nodeLevels[0]).toBeGreaterThan(0);
        expect(focus.nodeLevels[1]).toBeGreaterThan(0);
        expect(focus.nodeLevels[2]).toBeGreaterThan(0);
        expect(focus.nodeLevels[3]).toBe(3);
        expect(focus.nodeLevels[4]).toBeGreaterThan(0);
        expect(focus.nodeLevels[5]).toBeGreaterThan(0);
        expect(focus.nodeLevels[6]).toBe(0);
        expect(focus.nodeLevels[7]).toBe(0);
        expect([...focus.edgeLevels]).toEqual([2, 2, 2, 2, 2, 0, 0]);
    });

    it('keeps Caps particles on spherical shell edges without affecting map paths', () => {
        const scene = capsParticleScene();
        const particles = new GraphGalaxyParticles();
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'straight' as const };
        const probe = particles as unknown as { seeds: number[] };

        particles.bind(scene, settings);
        probe.seeds[0] = 0.5;
        particles.update(scene, scene.positions3d, settings, 0);

        const position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(Math.hypot(position.getX(0), position.getY(0), position.getZ(0))).toBeCloseTo(2.08);
        expect(position.getX(0)).toBeGreaterThan(1.4);
        expect(position.getY(0)).toBeGreaterThan(1.4);

        particles.update(scene, scene.positions2d, settings, 0);
        expect(position.getX(0)).toBeCloseTo(1.04);
        expect(position.getY(0)).toBeCloseTo(1.04);

        particles.dispose();
    });

    it('matches shell-aware Caps and Hybrid surface routing for particles', () => {
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'straight' as const };
        const caps = capsParticleScene(0.98);
        const hybrid = { ...capsParticleScene(2.32), layoutMode: 'hybridSpace' as const };
        const particles = new GraphGalaxyParticles();
        const probe = particles as unknown as { seeds: number[] };

        particles.bind(caps, settings);
        probe.seeds[0] = 0.5;
        particles.update(caps, caps.positions3d, settings, 0);
        let position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(Math.hypot(position.getX(0), position.getY(0), position.getZ(0))).toBeCloseTo(0.98);

        caps.positions3d = new Float32Array([1.34, 0, 0, 0, 1.48, 0]);
        particles.update(caps, caps.positions3d, settings, 0);
        position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(position.getX(0)).toBeCloseTo(0.67);
        expect(position.getY(0)).toBeCloseTo(0.74);

        particles.bind(hybrid, settings);
        probe.seeds[0] = 0.5;
        particles.update(hybrid, hybrid.positions3d, settings, 0);
        position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(Math.hypot(position.getX(0), position.getY(0), position.getZ(0))).toBeCloseTo(2.32);

        hybrid.positions3d = new Float32Array([2.32, 0, 0, 0, 1.74, 0]);
        particles.update(hybrid, hybrid.positions3d, settings, 0);
        position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(position.getX(0)).toBeCloseTo(1.16);
        expect(position.getY(0)).toBeCloseTo(0.87);

        particles.dispose();
    });

    it('adds flow particles to live Transit and Siegel guide lines', () => {
        const settings = { ...DEFAULT_GALAXY_SETTINGS, particleFlow: true, particleSpeed: 0, particleOpacity: 1, edgeMode: 'straight' as const };
        const transit = guideParticleScene('transitManifold');
        const siegel = guideParticleScene('siegelFinsler');
        const particles = new GraphGalaxyParticles();
        const probe = particles as unknown as { seeds: number[]; flowSources: Array<{ kind: string; index: number }> };

        particles.bind(transit, settings);
        probe.seeds[0] = 0.5;
        particles.update(transit, transit.positions3d, settings, 0);
        let position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        let color = particles.points.geometry.getAttribute('color') as THREE.BufferAttribute;
        expect(probe.flowSources).toEqual([{ kind: 'guide', index: 0 }]);
        expect(position.getX(0)).toBeCloseTo(1);
        expect(position.getY(0)).toBeGreaterThan(0);
        expect(color.getZ(0)).toBeLessThan(0.9);
        expect(color.getZ(0)).toBeGreaterThan(0.8);

        transit.positions3d = new Float32Array([2, 0, 0, 6, 0, 0]);
        particles.update(transit, transit.positions3d, settings, 0);
        expect(position.getX(0)).toBeCloseTo(3);

        probe.seeds[0] = 0.95;
        particles.update(transit, transit.positions3d, settings, 0);
        expect(Math.abs(position.getY(0))).toBeLessThan(0.2);

        particles.bind(siegel, settings);
        probe.seeds[0] = 0.5;
        particles.update(siegel, siegel.positions3d, settings, 0);
        position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        expect(position.getX(0)).toBeCloseTo(1);

        particles.dispose();
    });

    it('fans walk particles from documents and splits them at structural forks', () => {
        const scene = walkParticleScene();
        const particles = new GraphGalaxyParticles();
        const settings = {
            ...DEFAULT_GALAXY_SETTINGS,
            particleFlow: true,
            particleFlowMode: 'walk' as const,
            particleSpeed: 1,
            particleOpacity: 1,
            edgeMode: 'straight' as const,
        };

        particles.bind(scene, settings);
        particles.update(scene, scene.positions3d, settings, 100);
        particles.update(scene, scene.positions3d, settings, 300);

        const position = particles.points.geometry.getAttribute('position') as THREE.BufferAttribute;
        const alpha = particles.points.geometry.getAttribute('alpha') as THREE.BufferAttribute;
        expect(position.count).toBe(6);
        expect([position.getX(0), position.getX(1)].sort((a, b) => a - b)).toEqual([-3, 1]);
        expect(activeParticleIndexes(alpha)).toEqual([0, 1]);

        particles.update(scene, scene.positions3d, settings, 2960);
        expect(activeParticleIndexes(alpha)).toEqual([2, 3]);

        particles.update(scene, scene.positions3d, settings, 4460);
        expect(activeParticleIndexes(alpha)).toEqual(expect.arrayContaining([4, 5]));
        expect(position.getX(4)).toBeGreaterThan(-1);
        expect(position.getY(4)).toBeGreaterThan(0);

        particles.dispose();
    });
});

function particleScene(): GalaxySceneV2 {
    return {
        sourceMode: 'embeddings',
        layoutMode: 'transitManifold',
        ids: ['a', 'b', 'c'],
        labels: ['A', 'B', 'C'],
        kinds: ['character', 'location', 'network'],
        groupIds: ['', '', ''],
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: new Float32Array([0, 0, 0, 2, 0, 0, 4, 0, 0]),
        positions2d: new Float32Array([0, 0, 0, 2, 0, 0, 4, 0, 0]),
        radii: new Float32Array([0.08, 0.08, 0.08]),
        colors: new Float32Array([1, 0, 0, 0.1, 0.8, 1, 0.9, 0.2, 0.7]),
        edgePairs: new Uint32Array([0, 1, 1, 2]),
        edgeColors: new Float32Array([
            1, 0, 0, 0.1, 0.8, 1,
            0.1, 0.8, 1, 0.9, 0.2, 0.7,
        ]),
        edgeAlpha: new Float32Array([1, 1]),
        edgeKinds: new Uint8Array([0, 0]),
    };
}

function capsParticleScene(radius = 2.08): GalaxySceneV2 {
    return {
        ...particleScene(),
        layoutMode: 'lorentzTree',
        ids: ['a', 'b'],
        labels: ['A', 'B'],
        kinds: ['character', 'location'],
        groupIds: ['', ''],
        positions3d: new Float32Array([radius, 0, 0, 0, radius, 0]),
        positions2d: new Float32Array([radius, 0, 0, 0, radius, 0]),
        radii: new Float32Array([0.08, 0.08]),
        colors: new Float32Array([1, 0, 0, 0.1, 0.8, 1]),
        edgePairs: new Uint32Array([0, 1]),
        edgeColors: new Float32Array([1, 0, 0, 0.1, 0.8, 1]),
        edgeAlpha: new Float32Array([1]),
        edgeKinds: new Uint8Array([0]),
    };
}

function walkParticleScene(): GalaxySceneV2 {
    return {
        ...particleScene(),
        layoutMode: 'single',
        ids: ['doc-a', 'root-a', 'chunk-a', 'entity-a', 'doc-b', 'root-b', 'chunk-b', 'fact-a'],
        labels: ['Doc A', 'Root A', 'Chunk A', 'Entity A', 'Doc B', 'Root B', 'Chunk B', 'Fact A'],
        kinds: ['note', 'structureRoot', 'leaf_chunk', 'concept', 'document', 'section', 'leaf_chunk', 'claim'],
        groupIds: ['', '', '', '', '', '', '', ''],
        positions3d: new Float32Array([
            -3, 0, 0, -2, 0, 0, -1, 0, 0, 0, 0, 0,
            1, 0, 0, 2, 0, 0, 3, 0, 0, 0, 1, 0,
        ]),
        positions2d: new Float32Array([
            -3, 0, 0, -2, 0, 0, -1, 0, 0, 0, 0, 0,
            1, 0, 0, 2, 0, 0, 3, 0, 0, 0, 1, 0,
        ]),
        radii: new Float32Array(8).fill(0.08),
        colors: new Float32Array([
            0.1, 0.8, 1, 0.2, 0.7, 1, 0.3, 0.6, 1, 0.4, 0.5, 1,
            1, 0.4, 0.2, 1, 0.5, 0.2, 1, 0.6, 0.2, 0.9, 0.2, 0.7,
        ]),
        edgePairs: new Uint32Array([0, 1, 1, 2, 2, 3, 4, 5, 5, 6, 2, 7]),
        edgeIds: ['a-root', 'a-chunk', 'a-entity', 'b-root', 'b-chunk', 'a-fact'],
        edgeTypes: ['target-parent', 'target-parent', 'chunk-entity', 'target-parent', 'target-parent', 'chunk-anchor'],
        edgeColors: new Float32Array(6 * 6),
        edgeAlpha: new Float32Array(6).fill(1),
        edgeKinds: new Uint8Array(6).fill(2),
    };
}

function activeParticleIndexes(alpha: THREE.BufferAttribute): number[] {
    return Array.from({ length: alpha.count }, (_, index) => index).filter((index) => alpha.getX(index) > 0.05);
}

function hopfParticleScene(): GalaxySceneV2 {
    return {
        ...particleScene(),
        layoutMode: 'hopfProjection',
        ids: ['a', 'b'],
        labels: ['A', 'B'],
        kinds: ['character', 'location'],
        groupIds: ['', ''],
        hopfBaseIds: ['entity:a', 'entity:b'],
        positions3d: new Float32Array([1.18, 0.12, 0.18, -0.14, 1.06, 0.52]),
        positions2d: new Float32Array([1.18, 0.12, 0, -0.14, 1.06, 0]),
        radii: new Float32Array([0.08, 0.08]),
        colors: new Float32Array([1, 0, 0, 0.1, 0.8, 1]),
        edgePairs: new Uint32Array([0, 1]),
        edgeColors: new Float32Array([1, 0, 0, 0.1, 0.8, 1]),
        edgeAlpha: new Float32Array([1]),
        edgeKinds: new Uint8Array([0]),
    };
}

function hopfArcPoint(scene: GalaxySceneV2, edgeCurveStrength: number, edge: number, t: number): { x: number; y: number; z: number; lift: number } {
    const point: GalaxyCurvePoint = { x: 0, y: 0, z: 0 };
    const source = scene.edgePairs[edge * 2];
    const target = scene.edgePairs[edge * 2 + 1];
    const sourceOffset = source * 3;
    const targetOffset = target * 3;
    const ax = scene.positions3d[sourceOffset], ay = scene.positions3d[sourceOffset + 1], az = scene.positions3d[sourceOffset + 2];
    const bx = scene.positions3d[targetOffset], by = scene.positions3d[targetOffset + 1], bz = scene.positions3d[targetOffset + 2];
    const seed = stableUnit(`hopf-edge:${edge}`);
    const crossBase = Boolean(scene.hopfBaseIds?.[source] && scene.hopfBaseIds?.[target] && scene.hopfBaseIds[source] !== scene.hopfBaseIds[target]);
    const curveScale = THREE.MathUtils.clamp(edgeCurveStrength, 0.25, 1.2);
    const liftScale = curveScale * (scene.edgeKinds[edge] === 1 ? 0.92 : 0.58);
    const lift = (0.08 + Math.abs(source - target) * 0.002) * liftScale + (scene.edgeKinds[edge] === 1 ? 0.18 : 0) + (crossBase ? 0.1 : 0);
    setHopfEdgeCurvePoint(point, ax, ay, az, bx, by, bz, lift, t, edgeCurveStrength, seed, crossBase);
    return { x: point.x, y: point.y, z: point.z, lift };
}

function stableUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}

function structuralCapsScene(): GalaxySceneV2 {
    return {
        ...particleScene(),
        layoutMode: 'lorentzTree',
        ids: ['doc', 'root', 'chunk', 'kai', 'rowan'],
        labels: ['Document', 'Identity root', 'Chunk 1', 'Kai', 'Rowan'],
        kinds: ['note', 'structureRoot', 'chunk', 'character', 'character'],
        groupIds: ['', '', '', '', ''],
        positions3d: new Float32Array([
            0, 0, 2.08,
            0, 0, 1.92,
            0, 0, 1.72,
            0, 0, 1.42,
            1.42, 0, 0,
        ]),
        positions2d: new Float32Array([
            0, 0, 2.08,
            0, 0, 1.92,
            0, 0, 1.72,
            0, 0, 1.42,
            1.42, 0, 0,
        ]),
        radii: new Float32Array([0.08, 0.08, 0.08, 0.08, 0.08]),
        colors: new Float32Array([
            0.1, 0.8, 1,
            0.1, 0.8, 1,
            0.1, 0.8, 1,
            0.9, 0.2, 0.7,
            0.9, 0.2, 0.7,
        ]),
        edgePairs: new Uint32Array([0, 1, 1, 2, 2, 3, 3, 4]),
        edgeColors: new Float32Array(4 * 6),
        edgeAlpha: new Float32Array([1, 1, 1, 1]),
        edgeKinds: new Uint8Array([2, 2, 2, 0]),
    };
}

function siegelFocusScene(): GalaxySceneV2 {
    return {
        ...particleScene(),
        layoutMode: 'siegelFinsler',
        ids: ['doc', 'root', 'chunk', 'kai', 'event', 'anchor', 'dense-a', 'dense-b'],
        labels: ['Document', 'Root', 'Chunk', 'Kai', 'Event', 'Anchor', 'Dense A', 'Dense B'],
        kinds: ['note', 'structureRoot', 'chunk', 'character', 'event', 'anchor', 'character', 'location'],
        groupIds: ['', '', '', '', '', '', '', ''],
        positions3d: new Float32Array([
            -1.4, 0, 0,
            -1.1, 0, 0,
            -0.8, 0, 0,
            -0.2, 0, 0,
            0.2, 0, 0,
            0.5, 0, 0,
            -0.2, 0.7, 0,
            0.4, 0.7, 0,
        ]),
        positions2d: new Float32Array([
            -1.4, 0, 0,
            -1.1, 0, 0,
            -0.8, 0, 0,
            -0.2, 0, 0,
            0.2, 0, 0,
            0.5, 0, 0,
            -0.2, 0.7, 0,
            0.4, 0.7, 0,
        ]),
        radii: new Float32Array(8).fill(0.08),
        colors: new Float32Array(8 * 3).fill(0.5),
        edgePairs: new Uint32Array([
            0, 1,
            1, 2,
            2, 3,
            4, 3,
            5, 3,
            3, 6,
            6, 7,
        ]),
        edgeColors: new Float32Array(7 * 6),
        edgeAlpha: new Float32Array(7).fill(1),
        edgeKinds: new Uint8Array([2, 2, 2, 2, 2, 0, 0]),
    };
}

function guideParticleScene(layoutMode: 'transitManifold' | 'siegelFinsler'): GalaxySceneV2 {
    return {
        ...particleScene(),
        layoutMode,
        ids: ['a', 'b'],
        labels: ['A', 'B'],
        kinds: ['character', 'location'],
        groupIds: ['', ''],
        positions3d: new Float32Array([0, 0, 0, 4, 0, 0]),
        positions2d: new Float32Array([0, 0, 0, 4, 0, 0]),
        radii: new Float32Array([0.08, 0.08]),
        colors: new Float32Array([1, 0, 0, 0.1, 0.8, 1]),
        edgePairs: new Uint32Array(0),
        edgeColors: new Float32Array(0),
        edgeAlpha: new Float32Array(0),
        edgeKinds: new Uint8Array(0),
        lorentzGuides: [{
            id: `${layoutMode}:guide:a-b`,
            nodeIds: ['a', 'b'],
            positions3d: new Float32Array([
                0, 0, 0, 1, 0.5, 0,
                1, 0.5, 0, 4, 0, 0,
            ]),
            positions2d: new Float32Array([
                0, 0, 0, 1, 0.5, 0,
                1, 0.5, 0, 4, 0, 0,
            ]),
            color: { r: 0.2, g: 0.7, b: 1 },
            importance: 1,
            treeId: 'guide',
            treeKind: 'relationship',
            level: 1,
            guideKind: 'membership',
            guideWeight: 1,
        }],
    };
}
