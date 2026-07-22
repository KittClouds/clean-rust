import * as THREE from 'three/webgpu';
import { describe, expect, it } from 'vitest';

import { mergeGalaxySettings } from '../graph-galaxy-engine';
import type { GalaxyScenePacketV2GuideDetails } from '../graph-galaxy-scene-packet-v2';
import {
    buildGalaxyRendererV3GuideSurface,
    syncGalaxyRendererV3GuidePresentation,
} from './galaxy-renderer-v3-guide-surface';

describe('Galaxy Renderer V3 guide surface', () => {
    it('restores bounded route and fiber geometry from packet guide details', () => {
        const surface = buildGalaxyRendererV3GuideSurface(details());

        expect(surface.fiberGuideCount).toBe(1);
        expect(surface.routeGuideCount).toBe(1);
        expect(drawableCount(surface.fibers)).toBeGreaterThan(0);
        expect(drawableCount(surface.routes)).toBeGreaterThan(0);
        expect(surface.root.name).toBe('v3-guides');
    });

    it('applies route and fiber toggles in place without rebuilding geometry', () => {
        const surface = buildGalaxyRendererV3GuideSurface(details());
        const fiberGeometry = firstGeometry(surface.fibers);
        const routeGeometry = firstGeometry(surface.routes);

        syncGalaxyRendererV3GuidePresentation(surface, mergeGalaxySettings({
            guideFibersVisible: false,
            guideRoutesVisible: true,
        }));
        expect(surface.fibers.visible).toBe(false);
        expect(surface.routes.visible).toBe(true);

        syncGalaxyRendererV3GuidePresentation(surface, mergeGalaxySettings({
            guideFibersVisible: true,
            guideRoutesVisible: false,
        }));
        expect(surface.fibers.visible).toBe(true);
        expect(surface.routes.visible).toBe(false);
        expect(firstGeometry(surface.fibers)).toBe(fiberGeometry);
        expect(firstGeometry(surface.routes)).toBe(routeGeometry);
    });
});

function details(): GalaxyScenePacketV2GuideDetails {
    const fiberPositions = circleSegments(1.2, 12);
    return {
        hopfRibbons: [{
            id: 'hopf:fiber:one',
            nodeIds: ['node:a'],
            positions3d: fiberPositions,
            positions2d: fiberPositions.slice(),
            color: { r: 0.92, g: 0.2, b: 0.72 },
            sourceColor: { r: 0.2, g: 0.92, b: 0.74 },
            importance: 1,
            guideKind: 'dataFiber',
            guideWeight: 1,
        }],
        lorentzGuides: [{
            id: 'caps:membership:a-b',
            nodeIds: ['node:a', 'node:b'],
            positions3d: new Float32Array([
                -1, 0, 0, -0.3, 0.45, 0,
                -0.3, 0.45, 0, 0.4, 0.2, 0,
                0.4, 0.2, 0, 1, 0.8, 0,
            ]),
            positions2d: new Float32Array([
                -1, 0, 0, -0.3, 0.45, 0,
                -0.3, 0.45, 0, 0.4, 0.2, 0,
                0.4, 0.2, 0, 1, 0.8, 0,
            ]),
            color: { r: 0.25, g: 0.72, b: 1 },
            importance: 1,
            treeId: 'caps',
            treeKind: 'evidence',
            level: 1,
            guideKind: 'membership',
            guideWeight: 1,
        }],
    };
}

function circleSegments(radius: number, count: number): Float32Array {
    const values = new Float32Array(count * 6);
    for (let index = 0; index < count; index++) {
        const start = index / count * Math.PI * 2;
        const end = (index + 1) / count * Math.PI * 2;
        values.set([
            Math.cos(start) * radius, Math.sin(start) * radius, 0,
            Math.cos(end) * radius, Math.sin(end) * radius, 0,
        ], index * 6);
    }
    return values;
}

function drawableCount(group: THREE.Group): number {
    let count = 0;
    group.traverse((object) => {
        if ((object as THREE.Mesh | THREE.LineSegments).geometry) count++;
    });
    return count;
}

function firstGeometry(group: THREE.Group): THREE.BufferGeometry | undefined {
    let result: THREE.BufferGeometry | undefined;
    group.traverse((object) => {
        result ||= (object as THREE.Mesh | THREE.LineSegments).geometry;
    });
    return result;
}
