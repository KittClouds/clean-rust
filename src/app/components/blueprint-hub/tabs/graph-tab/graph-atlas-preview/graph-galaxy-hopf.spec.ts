import { describe, expect, it } from 'vitest';

import {
    buildGalaxyScene,
    mergeGalaxySettings,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
} from './graph-galaxy-engine';

const hopfNodes: GalaxyRenderableNode[] = [
    {
        id: 'hopf:anchor:kai',
        label: 'Kai',
        kind: 'HOPF_ANCHOR',
        atlasX: 0.7,
        atlasY: 0.2,
        atlasZ: 0.4,
        totalMentions: 8,
        metadata: { sourceType: 'hopf_anchor', hopf: { role: 'anchor', baseId: 'kai', phase: 0 } },
    },
    {
        id: 'hopf:fiber:kai:evidence',
        label: 'Kai evidence',
        kind: 'HOPF_FIBER:evidence',
        atlasX: 0.68,
        atlasY: 0.24,
        atlasZ: 0.38,
        totalMentions: 5,
        metadata: { sourceType: 'hopf_fiber', hopf: { role: 'fiber', baseId: 'kai', fiberKind: 'evidence', phase: 0.75 } },
    },
    {
        id: 'hopf:fiber:kai:causal',
        label: 'Kai causal',
        kind: 'HOPF_FIBER:causal',
        atlasX: 0.66,
        atlasY: 0.2,
        atlasZ: 0.42,
        totalMentions: 3,
        metadata: { sourceType: 'hopf_fiber', hopf: { role: 'fiber', baseId: 'kai', fiberKind: 'causal', phase: 0.64 } },
    },
];

const hopfEdges: GalaxyInputEdge[] = [
    { id: 'anchor-edge', sourceId: 'hopf:anchor:kai', targetId: 'hopf:fiber:kai:evidence', type: 'hopf-anchor-fiber', confidence: 0.9 },
    { id: 'fiber-edge', sourceId: 'hopf:fiber:kai:evidence', targetId: 'hopf:fiber:kai:causal', type: 'hopf-fiber-edge:causal', confidence: 0.8 },
];

describe('Hopf galaxy visualization data', () => {
    it('keeps Hopf projection deterministic while emitting only data-formed fibers', () => {
        const settings = mergeGalaxySettings({ layoutMode: 'hopfProjection' });
        const first = buildGalaxyScene(hopfNodes, hopfEdges, settings);
        const second = buildGalaxyScene(hopfNodes, hopfEdges, settings);

        expect(first.layoutMode).toBe('hopfProjection');
        expect(first.nodes.map(positionOf)).toEqual(second.nodes.map(positionOf));
        expect(first.hopfRibbons?.length).toBe(1);
        expect(new Set(first.hopfRibbons?.map((ribbon) => ribbon.guideKind))).toEqual(new Set(['dataFiber']));
        expect(first.hopfRibbons?.[0]?.nodeIds).toEqual([
            'hopf:anchor:kai',
            'hopf:fiber:kai:evidence',
            'hopf:fiber:kai:causal',
        ]);
        expect((first.hopfRibbons?.[0]?.positions3d.length || 0) / 6).toBeGreaterThan(48);
        expect(segmentLoopGap(first.hopfRibbons![0].positions3d)).toBeLessThan(0.00001);
    });

    it('does not emit Hopf guide geometry for the hybrid universe', () => {
        const scene = buildGalaxyScene(hopfNodes, hopfEdges, mergeGalaxySettings({ layoutMode: 'hybridSpace' }));

        expect(scene.layoutMode).toBe('hybridSpace');
        expect(scene.hopfRibbons).toBeUndefined();
    });

    it('turns cross-base Hopf links into faint braid guides', () => {
        const nodes: GalaxyRenderableNode[] = [
            hopfTarget('embed:entity:kai', 'Kai', 'anchor', 'embed:entity:kai', 0),
            hopfTarget('embed:graph-fact:kai', 'Kai fact', 'fiber', 'embed:entity:kai', 0.32),
            hopfTarget('embed:entity:hazel', 'Hazel', 'anchor', 'embed:entity:hazel', 0),
            hopfTarget('embed:graph-fact:hazel', 'Hazel fact', 'fiber', 'embed:entity:hazel', 0.68),
        ];
        const scene = buildGalaxyScene(nodes, [
            { id: 'same-base', sourceId: 'embed:entity:kai', targetId: 'embed:graph-fact:kai', type: 'embedding-backbone', confidence: 0.9 },
            { id: 'cross-base', sourceId: 'embed:graph-fact:kai', targetId: 'embed:graph-fact:hazel', type: 'embedding-bridge', confidence: 0.9 },
        ], mergeGalaxySettings({ layoutMode: 'hopfProjection' }));

        const cross = scene.links.find((link) => link.id === 'cross-base')!;
        const braid = scene.hopfRibbons?.find((ribbon) => ribbon.guideKind === 'crossFiberBraid');
        expect(cross.alpha).toBeLessThanOrEqual(0.07);
        expect(braid).toBeTruthy();
        expect((braid?.positions3d.length || 0) / 6).toBeGreaterThan(32);
        expect(polylineLength(braid!.positions3d)).toBeGreaterThan(directSegmentLength(braid!.positions3d) * 1.05);
    });

    it('keeps low-count semantic fibers visible when high-importance fibers fill the guide budget', () => {
        const crowded = Array.from({ length: 64 }, (_, index) =>
            hopfTarget(`embed:entity:busy-${index}`, `Busy ${index}`, 'anchor', `embed:entity:busy-${index}`, index / 64),
        );
        const status = hopfTarget('embed:memory:kai-status', 'Kai status', 'fiber', 'embed:entity:kai:hopf:memory-status', 0.4);
        status.kind = 'memory-state';
        status.totalMentions = 1;
        status.metadata = {
            sourceType: 'memoryState',
            hopf: { role: 'fiber', baseId: 'embed:entity:kai:hopf:memory-status', fiberKind: 'memory-state', phase: 0.4 },
        };
        const scene = buildGalaxyScene([...crowded, status], [], mergeGalaxySettings({ layoutMode: 'hopfProjection' }));

        const dataRibbons = scene.hopfRibbons?.filter((ribbon) => ribbon.guideKind === 'dataFiber') || [];
        expect(dataRibbons.length).toBeLessThanOrEqual(48);
        expect(dataRibbons.some((ribbon) => ribbon.nodeIds.includes('embed:memory:kai-status'))).toBe(true);
    });

    it('clamps Hopf visual intensity independently of hybrid shell opacity', () => {
        const high = mergeGalaxySettings({ hopfSpaceIntensity: 99, hybridShellOpacity: 2 });
        const low = mergeGalaxySettings({ hopfSpaceIntensity: -4, hybridShellOpacity: -3 });

        expect(high.hopfSpaceIntensity).toBe(1.4);
        expect(low.hopfSpaceIntensity).toBe(0);
        expect(high.hybridShellOpacity).toBe(1);
        expect(low.hybridShellOpacity).toBe(0);
        expect(mergeGalaxySettings().hopfSpaceVisible).toBe(true);
    });
});

function hopfTarget(
    id: string,
    label: string,
    role: 'anchor' | 'fiber',
    baseId: string,
    phase: number,
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: role === 'anchor' ? 'entity' : 'graph-fact',
        atlasX: phase + 0.12,
        atlasY: 0.28,
        atlasZ: 0.42,
        totalMentions: 4,
        metadata: { sourceType: role, hopf: { role, baseId, fiberKind: 'identity', phase } },
    };
}

function positionOf(node: { x: number; y: number; z: number }): [number, number, number] {
    return [
        Number(node.x.toFixed(6)),
        Number(node.y.toFixed(6)),
        Number(node.z.toFixed(6)),
    ];
}

function segmentLoopGap(positions: Float32Array): number {
    const last = positions.length - 3;
    return Math.hypot(
        positions[0] - positions[last],
        positions[1] - positions[last + 1],
        positions[2] - positions[last + 2],
    );
}

function directSegmentLength(positions: Float32Array): number {
    return segmentLoopGap(positions);
}

function polylineLength(positions: Float32Array): number {
    let length = 0;
    for (let offset = 0; offset < positions.length; offset += 6) {
        length += Math.hypot(
            positions[offset] - positions[offset + 3],
            positions[offset + 1] - positions[offset + 4],
            positions[offset + 2] - positions[offset + 5],
        );
    }
    return length;
}
