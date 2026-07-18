import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import {
    galaxyEdgeOverdrawAttenuation,
    galaxyEdgeVisualAlpha,
    GalaxyGpuEdgeCurve,
    GalaxyGpuEdgeSurface,
} from './three-galaxy-edge-surface';

describe('GalaxyGpuEdgeSurface', () => {
    it('keeps resident storage linear in edges instead of segments times edges', () => {
        const edgeCount = 10_000;
        const nodeCount = 4_096;
        const pairs = new Uint32Array(edgeCount * 2);
        const curves = new Uint8Array(edgeCount);
        for (let edge = 0; edge < edgeCount; edge++) {
            pairs[edge * 2] = edge % nodeCount;
            pairs[edge * 2 + 1] = (edge * 17 + 1) % nodeCount;
            curves[edge] = edge % 3 === 0
                ? GalaxyGpuEdgeCurve.Straight
                : edge % 3 === 1 ? GalaxyGpuEdgeCurve.Arc : GalaxyGpuEdgeCurve.Hopf;
        }

        const surface = new GalaxyGpuEdgeSurface({ nodeCount, edgePairs: pairs, curveKinds: curves });
        const lines = surface.children.filter((child) => child.userData['edgePass'] === 'base') as THREE.LineSegments[];
        const templateVertices = lines.reduce((sum, line) => sum + line.geometry.getAttribute('position').count, 0);
        const instanceBytes = lines.reduce((sum, line) => sum
            + line.geometry.getAttribute('aEndpoints').array.byteLength
            + line.geometry.getAttribute('aStyle').array.byteLength
            + line.geometry.getAttribute('aLift').array.byteLength
            + line.geometry.getAttribute('aSourceColor').array.byteLength
            + line.geometry.getAttribute('aTargetColor').array.byteLength, 0);

        expect(surface.bucketInstanceCounts().reduce((sum, count) => sum + count, 0)).toBe(edgeCount);
        expect(templateVertices).toBe(2 + 24 + 48);
        expect(instanceBytes).toBe(edgeCount * 24);
        expect(lines).toHaveLength(3);
        expect(surface.children.filter((child) => child.userData['edgePass'] === 'emphasis')).toHaveLength(3);
        surface.dispose();
    });

    it('fetches endpoints and performs subpixel suppression in the shader', () => {
        const surface = new GalaxyGpuEdgeSurface({
            nodeCount: 2,
            edgePairs: new Uint32Array([0, 1]),
            curveKinds: new Uint8Array([GalaxyGpuEdgeCurve.Arc]),
        });
        const line = surface.children[0] as THREE.LineSegments;
        const material = line.material as THREE.RawShaderMaterial;

        expect(material.vertexShader).toContain('texelFetch(uNodePositions');
        expect(material.vertexShader).toContain('pixelSpan >= 0.70');
        const endpoints = line.geometry.getAttribute('aEndpoints');
        expect(endpoints.array).toBeInstanceOf(Uint32Array);
        expect(material.vertexShader).toContain('in uvec2 aEndpoints;');
        expect(material.vertexShader).toContain('vec3 nodePosition(uint packedNodeIndex)');
        expect(material.vertexShader).toContain('vCurveT = t;');
        expect(material.fragmentShader).toContain('float terminalTaper(float t)');
        expect(material.fragmentShader).toContain('terminalAttenuation');
        expect(material.vertexShader).not.toContain('in vec2 aEndpoints;');
        expect(line.geometry.getAttribute('aStyle').array).toBeInstanceOf(Uint8Array);
        surface.dispose();
    });

    it('bounds background energy as visible edge density rises', () => {
        expect(galaxyEdgeOverdrawAttenuation(1_200, 1_000, 1_000)).toBe(1);

        const dense = galaxyEdgeOverdrawAttenuation(24_000, 1_000, 600);
        const doubled = galaxyEdgeOverdrawAttenuation(48_000, 1_000, 600);
        const roomierViewport = galaxyEdgeOverdrawAttenuation(24_000, 2_000, 1_200);

        expect(dense).toBeLessThan(0.3);
        expect(dense).toBeGreaterThanOrEqual(0.18);
        expect(doubled).toBeLessThan(dense);
        expect(roomierViewport).toBeGreaterThan(dense);
    });

    it('keeps legacy edge strength readable without flattening confidence differences', () => {
        expect(galaxyEdgeVisualAlpha(0.052)).toBeCloseTo(0.58, 6);
        expect(galaxyEdgeVisualAlpha(0.18)).toBeGreaterThan(0.7);
        expect(galaxyEdgeVisualAlpha(0.34)).toBeCloseTo(0.9, 6);
    });
});
