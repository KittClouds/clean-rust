import { describe, expect, it } from 'vitest';

import { LORENTZ_MANIFOLD_CAPABILITIES, type ManifoldAtlasSnapshot } from '../../../../../services/manifold-atlas.types';
import type { SemanticAtlasEmbeddingAtlas } from '../../../../../services/phoenix-ui-api.service';
import { buildGalaxyScene, mergeGalaxySettings } from './graph-galaxy-engine';
import { buildLorentzAtlas, projectLorentzKlein } from './graph-lorentz-atlas';

describe('Lorentz tree galaxy visualization data', () => {
    it('projects H4 points into a deterministic bounded Klein ball', () => {
        const coords = hyperboloidPoint(1.15, [1, 0, 0, 0]);
        const first = projectLorentzKlein(coords);
        const second = projectLorentzKlein(coords);

        expect(first.klein).toEqual(second.klein);
        expect(first.valid).toBe(true);
        expect(first.radius).toBeGreaterThan(0);
        expect(first.radius).toBeLessThanOrEqual(0.96);
    });

    it('builds one node identity with multiple hierarchy lanes', () => {
        const atlas = buildLorentzAtlas(lorentzSnapshot());
        const kai = atlas.nodes.find((node) => node.id === 'kai');
        const lorentz = kai?.metadata?.['lorentz'] as Record<string, unknown> | undefined;
        const memberships = lorentz?.['memberships'] as unknown[] | undefined;

        expect(atlas.nodes.map((node) => node.id).sort()).toEqual(['echo', 'kai', 'ruby']);
        expect(memberships?.length).toBe(2);
        expect(atlas.edges.filter((edge) => edge.type.startsWith('lorentz-tree')).length).toBe(2);
    });

    it('emits Lorentz guides without Hopf guide data in Lorentz mode', () => {
        const atlas = buildLorentzAtlas(lorentzSnapshot());
        const first = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const second = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));

        expect(first.layoutMode).toBe('lorentzTree');
        expect(first.hopfRibbons).toBeUndefined();
        expect(first.lorentzGuides?.length).toBeGreaterThan(3);
        expect(first.nodes.map(positionOf)).toEqual(second.nodes.map(positionOf));
        expect(new Set(first.lorentzGuides?.map((guide) => guide.guideKind))).toEqual(new Set([
            'membership',
            'rootLane',
            'levelShell',
            'wAxis',
        ]));
    });

    it('uses the Lorentz slot as hierarchy caps for graph rebuild targets', () => {
        const scene = buildGalaxyScene([
            capNode('doc', 'Document', 'note', 0.18, 0.66, 'documentStructure', [0.05, 0.1, 1]),
            capNode('chunk', 'Sharp chunk', 'chunk', 0.93, 0.18, 'documentStructure', [0.12, 0.18, 1]),
            capNode('cause', 'Cause bridge', 'event', 0.76, 0.34, 'causal', [1, -0.2, 0.22]),
        ], [
            { id: 'doc-chunk', sourceId: 'doc', targetId: 'chunk', type: 'note-chunk', confidence: 0.9 },
            { id: 'chunk-cause', sourceId: 'chunk', targetId: 'cause', type: 'causal', confidence: 0.84 },
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(scene.layoutMode).toBe('lorentzTree');
        expect(byId.get('doc')!.depth).toBeGreaterThan(byId.get('chunk')!.depth);
        expect(byId.get('chunk')!.depth).toBeGreaterThan(byId.get('cause')!.depth);
        expect(scene.lorentzGuides?.some((guide) => guide.id.startsWith('caps:boundary:'))).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.treeKind === 'causal')).toBe(true);
    });

    it('keeps canon entities outside derived signals and context in hierarchy caps', () => {
        const scene = buildGalaxyScene([
            capNode('kai', 'Kai', 'entity', 0.86, 0.08, 'entity', [0.2, 0.1, 1], 0.94, 'CHARACTER'),
            capNode('signal', 'Kai trusts Hazel', 'event', 0.68, 0.24, 'relationship', [0.2, 0.1, 1], 0.72),
            capNode('context', 'Unresolved memory', 'memoryState', 0.48, 0.58, 'evidence', [0.2, 0.1, 1], 0.44),
        ], [
            { id: 'entity-signal', sourceId: 'kai', targetId: 'signal', type: 'supports', confidence: 0.82 },
            { id: 'signal-context', sourceId: 'signal', targetId: 'context', type: 'memory', confidence: 0.62 },
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(byId.get('kai')!.depth).toBeGreaterThan(byId.get('signal')!.depth);
        expect(byId.get('signal')!.depth).toBeGreaterThan(byId.get('context')!.depth);
    });

    it('honors explicit graph-rebuild cap shell radii without changing fallback Lorentz fixtures', () => {
        const scene = buildGalaxyScene([
            capShellNode('doc', 'Red Mesa', 'note', 2.08, 'document_spine'),
            capShellNode('chunk', 'Chunk 1', 'chunk', 1.72, 'chunk_spine'),
            capShellNode('entity', 'Kai', 'entity', 1.42, 'entity_anchor'),
            capShellNode('evidence', 'Kai mention', 'anchor', 1.04, 'anchor_evidence'),
        ], [
            { id: 'doc-chunk', sourceId: 'doc', targetId: 'chunk', type: 'contains', confidence: 0.9 },
            { id: 'chunk-entity', sourceId: 'chunk', targetId: 'entity', type: 'contains', confidence: 0.86 },
            { id: 'entity-evidence', sourceId: 'entity', targetId: 'evidence', type: 'evidence', confidence: 0.82 },
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(byId.get('doc')!.depth).toBeGreaterThan(byId.get('chunk')!.depth);
        expect(byId.get('chunk')!.depth).toBeGreaterThan(byId.get('entity')!.depth);
        expect(byId.get('entity')!.depth).toBeGreaterThan(byId.get('evidence')!.depth);
    });

    it('does not emit Lorentz guide data for Hybrid or Hopf universes', () => {
        const atlas = buildLorentzAtlas(lorentzSnapshot());
        const hybrid = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'hybridSpace' }));
        const hopf = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'hopfProjection' }));

        expect(hybrid.lorentzGuides).toBeUndefined();
        expect(hopf.lorentzGuides).toBeUndefined();
    });

    it('clamps Lorentz visual intensity independently of Hopf intensity', () => {
        const high = mergeGalaxySettings({ lorentzSpaceIntensity: 99, hopfSpaceIntensity: 0.2 });
        const low = mergeGalaxySettings({ lorentzSpaceIntensity: -4, hopfSpaceIntensity: 0.2 });

        expect(high.lorentzSpaceIntensity).toBe(1.4);
        expect(low.lorentzSpaceIntensity).toBe(0);
        expect(high.hopfSpaceIntensity).toBe(0.2);
        expect(mergeGalaxySettings().lorentzSpaceVisible).toBe(true);
    });
});

function lorentzSnapshot(): ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas> {
    return {
        manifold: 'lorentz',
        geometryVersion: 'lorentz_h4_forest_v1',
        sourceLabel: 'test lorentz forest',
        capabilities: LORENTZ_MANIFOLD_CAPABILITIES,
        payload: {
            sourceLabel: 'test lorentz forest',
            projectionSource: 'real_snapshot_vectors',
            nodes: [
                { id: 'kai', label: 'Kai', sourceType: 'lorentz_node', vector: hyperboloidPoint(0.28, [1, 0, 0, 0]), kind: 'CHARACTER' },
                { id: 'echo', label: 'Echo', sourceType: 'lorentz_node', vector: hyperboloidPoint(0.74, [1, 0.2, 0, 0]), kind: 'EVENT' },
                { id: 'ruby', label: 'Ruby', sourceType: 'lorentz_node', vector: hyperboloidPoint(0.92, [0.1, 1, 0.2, 0]), kind: 'POWER' },
            ],
            edges: [],
            lorentzTrees: [
                { treeId: 'identity', treeKind: 'identity', label: 'Identity', rootNodeId: 'kai', geometryVersion: 'lorentz_h4_forest_v1' },
                { treeId: 'causal', treeKind: 'causal', label: 'Causal', rootNodeId: 'kai', geometryVersion: 'lorentz_h4_forest_v1' },
            ],
            lorentzMemberships: [
                membership('identity', 'kai', null, 0, 0, 'identity/kai'),
                membership('identity', 'echo', 'kai', 1, 0, 'identity/kai/echo'),
                membership('causal', 'kai', null, 0, 0, 'causal/kai'),
                membership('causal', 'ruby', 'kai', 1, 0, 'causal/kai/ruby'),
            ],
        },
    };
}

function membership(treeId: string, nodeId: string, parentNodeId: string | null, level: number, localRank: number, pathKey: string) {
    return {
        treeId,
        nodeId,
        parentNodeId,
        level,
        localRank,
        pathKey,
        branchWeight: 1,
        confidence: 1,
        sourceCount: 2,
        geometryVersion: 'lorentz_h4_forest_v1',
    };
}

function capNode(
    id: string,
    label: string,
    sourceType: string,
    specificity: number,
    ambiguity: number,
    treeKind: string,
    capDirection: [number, number, number],
    targetConfidence = 0.72,
    kind = sourceType,
) {
    return {
        id,
        label,
        kind,
        atlasX: capDirection[0],
        atlasY: capDirection[1],
        atlasZ: capDirection[2],
        totalMentions: 2,
        metadata: {
            sourceType,
            targetConfidence,
            lorentz: {
                capId: `cap:${treeKind}`,
                capDirection,
                capPhase: 0.25,
                specificity,
                ambiguity,
                primaryTreeKind: treeKind,
            },
        },
    };
}

function capShellNode(id: string, label: string, sourceType: string, shellRadius: number, signalLane: string) {
    return {
        id,
        label,
        kind: sourceType,
        atlasX: 0.2,
        atlasY: 0.1,
        atlasZ: 1,
        totalMentions: 2,
        metadata: {
            sourceType,
            signalLane,
            targetConfidence: 0.9,
            lorentz: {
                capId: 'document:note-1',
                capDirection: [0.2, 0.1, 1],
                capPhase: 0.25,
                shellRadius,
                signalLane,
                specificity: 0.82,
                ambiguity: 0.04,
                primaryTreeKind: 'documentStructure',
            },
        },
    };
}

function hyperboloidPoint(radius: number, direction: [number, number, number, number]): [number, number, number, number, number] {
    const norm = Math.hypot(...direction) || 1;
    const scale = Math.sinh(radius) / norm;
    return [Math.cosh(radius), direction[0] * scale, direction[1] * scale, direction[2] * scale, direction[3] * scale];
}

function positionOf(node: { x: number; y: number; z: number }): [number, number, number] {
    return [
        Number(node.x.toFixed(6)),
        Number(node.y.toFixed(6)),
        Number(node.z.toFixed(6)),
    ];
}
