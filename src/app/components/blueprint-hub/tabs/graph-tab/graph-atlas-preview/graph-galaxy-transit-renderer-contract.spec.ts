import { describe, expect, it } from 'vitest';

import {
    buildGalaxyScene,
    mergeGalaxySettings,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
} from './graph-galaxy-engine';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';

describe('Graph galaxy Transit renderer contract', () => {
    it('attaches a packet-backed TransitPlan before layout', () => {
        const nodes = packetNodes();
        const edges = packetEdges();

        const transit = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'transitManifold' }));
        const productCompat = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const single = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'single' }));

        expect(transit.transitPlan?.receipt).toMatchObject({
            stationCount: 3,
            routeCount: 2,
            packetBackedStations: 3,
            packetBackedRoutes: 2,
            droppedUntracedNodes: 0,
            missingEndpointRoutes: 0,
        });
        expect(transit.transitPlan?.receipt.laneCounts).toMatchObject({
            document: 1,
            chunk: 1,
            identity: 1,
        });
        expect(productCompat.layoutMode).toBe('transitManifold');
        expect(productCompat.transitPlan?.receipt.stationCount).toBe(3);
        expect(single.transitPlan).toBeUndefined();
    });

    it('preserves packet traceability through the renderer-facing V2 scene', () => {
        const scene = buildGalaxyScene(packetNodes(), packetEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const rendererScene = galaxySceneToV2(scene, 'embeddings');

        expect(rendererScene.layoutMode).toBe('transitManifold');
        expect(rendererScene.transitPlan).toBe(scene.transitPlan);
        expect(rendererScene.transitPlan?.receipt).toMatchObject({
            stationCount: 3,
            routeCount: 2,
            packetBackedStations: 3,
            packetBackedRoutes: 2,
        });
        expect(rendererScene.transitPlan?.stations.every((station) => station.packetBacked)).toBe(true);
        expect(rendererScene.transitPlan?.routes.every((route) => route.packetBacked)).toBe(true);
        expect(rendererScene.transitPlan?.stations.find((station) => station.nodeId === 'kai')).toMatchObject({
            lane: 'identity',
            packetSnapshotId: 'snapshot-transit-engine',
            trace: {
                source: 'rust_atlas_packet',
                packetObjectId: 'object:kai',
                packetTargetId: 'target:kai',
            },
        });
        expect(rendererScene.transitPlan?.routes.find((route) => route.edgeId === 'chunk-kai')).toMatchObject({
            sourceLane: 'chunk',
            targetLane: 'identity',
            trace: {
                source: 'rust_atlas_packet',
                packetSnapshotId: 'snapshot-transit-engine',
            },
        });
    });

    it('renders route stages, lane guides, and obstructions without Transit-local Hopf ribbons', () => {
        const scene = buildGalaxyScene([
            productNode('evidence', 'Chunk evidence', 'chunk', 'evidence', 'chunk'),
            productNode('entity', 'Kai', 'entity', 'identity', 'entity'),
            productNode('causal', 'Kai causes signal', 'event', 'causal', 'event'),
            productNode('dead-end', 'unsupported bridge', 'event', 'bridge', 'event', 'outlier'),
        ], [
            { id: 'evidence-entity', sourceId: 'evidence', targetId: 'entity', type: 'evidence_anchor', confidence: 0.9 },
            { id: 'entity-causal', sourceId: 'entity', targetId: 'causal', type: 'causal', confidence: 0.82 },
            { id: 'causal-dead-end', sourceId: 'causal', targetId: 'dead-end', type: 'embedding-bridge', confidence: 0.18 },
        ], mergeGalaxySettings({ layoutMode: 'transitManifold' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(scene.layoutMode).toBe('transitManifold');
        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(byId.get('evidence')!.x).toBeLessThan(byId.get('entity')!.x);
        expect(byId.get('entity')!.x).toBeLessThan(byId.get('causal')!.x);
        expect(byId.get('dead-end')).toBeTruthy();
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'transit:lane:evidence' && guide.guideKind === 'rootLane')).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'transit:route:causal-dead-end' && /unsupported|mismatch|missing/i.test(guide.treeKind))).toBe(true);
    });
});

function packetNodes(): GalaxyRenderableNode[] {
    return [
        transitPacketNode('doc', 'Note', 'structure', 'document', 'note-1', { noteIds: ['note-1'] }),
        transitPacketNode('chunk', 'Chunk', 'structure', 'chunk', 'chunk-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        transitPacketNode('kai', 'Kai', 'registry', 'entity', 'kai', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
    ];
}

function packetEdges(): GalaxyInputEdge[] {
    return [
        transitPacketEdge('doc-chunk', 'doc', 'chunk', 'manifold_parent', 'structure'),
        transitPacketEdge('chunk-kai', 'chunk', 'kai', 'chunk-entity', 'registry'),
    ];
}

function productNode(
    id: string,
    label: string,
    kind: string,
    lane: string,
    sourceType: string,
    role = 'core',
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind,
        totalMentions: 1,
        metadata: {
            sourceType,
            productLaneKind: lane,
            productRegionRole: role,
            graphKind: kind,
            graphRelationFamily: lane === 'causal' || lane === 'temporal' ? lane : undefined,
            product: {
                dominantLane: lane,
                region: {
                    laneKind: lane,
                    role,
                    clusterId: `chart:${lane}`,
                    outlierScore: role === 'outlier' ? 0.82 : 0.08,
                    hubScore: role === 'core' ? 0.72 : 0.22,
                },
                fiber: { phase: lane.length * 0.37 },
                lanes: { laneWeights: { [lane]: 0.92 } },
            },
        },
    };
}

function transitPacketNode(
    id: string,
    label: string,
    family: string,
    kind: string,
    sourceId: string,
    refs: { noteIds?: string[]; chunkIds?: string[]; evidenceIds?: string[] } = {},
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: family,
        totalMentions: 1,
        metadata: {
            sourceContract: 'rust-atlas-packet',
            vectorContract: 'vectors-missing',
            visualTrace: transitTrace(id, family, kind, sourceId, refs),
            visualSourceId: sourceId,
            visualFamily: family,
            graphFamily: family,
            atlasFamily: family,
            atlasKind: kind,
            packetSnapshotId: 'snapshot-transit-engine',
            packetScopeId: 'global',
            noteIds: refs.noteIds || [],
            chunkIds: refs.chunkIds || [],
            evidenceIds: refs.evidenceIds || [],
        },
    };
}

function transitPacketEdge(id: string, sourceId: string, targetId: string, type: string, family: string): GalaxyInputEdge {
    return {
        id,
        sourceId,
        targetId,
        type,
        confidence: 0.9,
        metadata: {
            sourceContract: 'rust-atlas-packet',
            graphFamily: family,
            visualTrace: {
                source: 'rust_atlas_packet',
                sourceId,
                family,
                packetSnapshotId: 'snapshot-transit-engine',
                packetScopeId: 'global',
                sourceContract: 'rust-atlas-packet',
                vectorContract: 'vectors-missing',
                packetObjectId: `object:${sourceId}`,
                packetTargetId: `object:${targetId}`,
            },
        },
    };
}

function transitTrace(
    id: string,
    family: string,
    kind: string,
    sourceId: string,
    refs: { noteIds?: string[]; chunkIds?: string[]; evidenceIds?: string[] },
) {
    return {
        source: 'rust_atlas_packet',
        sourceId,
        family,
        packetSnapshotId: 'snapshot-transit-engine',
        packetScopeId: 'global',
        sourceContract: 'rust-atlas-packet',
        vectorContract: 'vectors-missing',
        packetObjectId: `object:${id}`,
        packetTargetId: `target:${id}`,
        objectKind: kind,
        targetKind: kind,
        noteIds: refs.noteIds || [],
        chunkIds: refs.chunkIds || [],
        evidenceIds: refs.evidenceIds || [],
    };
}
