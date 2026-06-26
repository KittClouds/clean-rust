import { describe, expect, it } from 'vitest';

import {
    buildGalaxyScene,
    mergeGalaxySettings,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
} from './graph-galaxy-engine';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';

describe('Product compatibility Transit contract', () => {
    it('maps productManifold onto packet-native Transit without old Product guide furniture', () => {
        const scene = buildGalaxyScene(packetNodes(), packetEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const guideIds = scene.lorentzGuides?.map((guide) => guide.id) ?? [];

        expect(scene.layoutMode).toBe('transitManifold');
        expect(scene.transitPlan?.receipt).toMatchObject({
            stationCount: 5,
            routeCount: 4,
            packetBackedStations: 5,
            packetBackedRoutes: 4,
            droppedUntracedNodes: 0,
        });
        expect(scene.transitPlan?.receipt.laneCounts).toMatchObject({
            document: 1,
            root: 1,
            chunk: 1,
            identity: 1,
            evidence: 1,
        });
        expect(guideIds).toEqual(expect.arrayContaining([
            'transit:backbone:lane:document',
            'transit:backbone:lane:root',
            'transit:backbone:lane:chunk',
            'transit:plan:lane:evidence',
            'transit:plan:lane:identity',
            'transit:plan:stop:evidence',
            'transit:plan:hub:kai',
        ]));
        expect(guideIds.some((id) => id.startsWith('transit:lane:'))).toBe(false);
        expect(guideIds.some((id) => id.startsWith('transit:route:'))).toBe(false);
        expect(guideIds.some((id) => id.toLowerCase().includes('product'))).toBe(false);
        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
    });

    it('keeps packet traceability through the renderer scene for the compatibility alias', () => {
        const scene = buildGalaxyScene(packetNodes(), packetEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const rendererScene = galaxySceneToV2(scene, 'embeddings');

        expect(rendererScene.layoutMode).toBe('transitManifold');
        expect(rendererScene.transitPlan).toBe(scene.transitPlan);
        expect(rendererScene.transitPlan?.stations.find((station) => station.nodeId === 'kai')).toMatchObject({
            lane: 'identity',
            packetBacked: true,
            trace: {
                source: 'rust_atlas_packet',
                packetObjectId: 'object:kai',
                packetTargetId: 'target:kai',
            },
        });
        expect(rendererScene.transitPlan?.routes.find((route) => route.edgeId === 'chunk-kai')).toMatchObject({
            sourceLane: 'chunk',
            targetLane: 'identity',
            packetBacked: true,
            trace: {
                source: 'rust_atlas_packet',
                packetSnapshotId: 'snapshot-product-compat',
            },
        });
    });

    it('quarantines untraced legacy Product rows instead of rebuilding Product topology', () => {
        const scene = buildGalaxyScene([
            legacyProductNode('legacy:kai', 'Kai', 'identity'),
            legacyProductNode('legacy:echo', 'Echo', 'causal'),
            legacyProductNode('legacy:evidence', 'Evidence', 'evidence'),
        ], [{
            id: 'legacy:kai:echo',
            sourceId: 'legacy:kai',
            targetId: 'legacy:echo',
            type: 'embedding-bridge',
            confidence: 0.82,
        }], mergeGalaxySettings({ layoutMode: 'productManifold' }));

        expect(scene.layoutMode).toBe('transitManifold');
        expect(scene.transitPlan?.receipt).toMatchObject({
            stationCount: 0,
            routeCount: 0,
            droppedUntracedNodes: 3,
            missingEndpointRoutes: 1,
        });
        expect(scene.lorentzGuides?.length ?? 0).toBe(0);
        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(scene.links.every((link) => link.alpha <= 0.08)).toBe(true);
        expect(scene.nodes.every((node) => node.y < -1.7)).toBe(true);
    });

    it('keeps embedding topology as a selectable lens without merging nodes', () => {
        const nodes: GalaxyRenderableNode[] = [
            topologyNode('embed:entity:kai', 'Kai', 'embedding-cluster:0', 'embed:entity:kai', 0.1, 0.9),
            topologyNode('embed:entity:rowan', 'Rowan', 'embedding-cluster:0', 'embed:entity:kai', 0.2, 0.4),
            topologyNode('embed:entity:rook', 'Rook', 'embedding-cluster:1', 'embed:entity:rook', 0.84, 0.2),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'embedding-backbone:kai:rowan', sourceId: 'embed:entity:kai', targetId: 'embed:entity:rowan', type: 'embedding-backbone', confidence: 0.84 },
            { id: 'embedding-bridge:rowan:rook', sourceId: 'embed:entity:rowan', targetId: 'embed:entity:rook', type: 'embedding-bridge', confidence: 0.72 },
        ];

        const medoids = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'medoids' }));
        const outliers = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'outliers' }));
        const backbone = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'backbone' }));
        const regions = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'regions' }));
        const lanes = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'lanes' }));

        expect(medoids.nodes.find((node) => node.entity.id === 'embed:entity:kai')?.radius)
            .toBeGreaterThan(medoids.nodes.find((node) => node.entity.id === 'embed:entity:rowan')?.radius || 0);
        expect(outliers.nodes.find((node) => node.entity.id === 'embed:entity:rook')?.radius)
            .toBeGreaterThan(outliers.nodes.find((node) => node.entity.id === 'embed:entity:rowan')?.radius || 0);
        expect(backbone.links.find((edge) => edge.type === 'embedding-backbone')?.alpha)
            .toBeGreaterThan(backbone.links.find((edge) => edge.type === 'embedding-bridge')?.alpha || 0);
        expect(regions.nodes.find((node) => node.entity.id === 'embed:entity:rook')?.radius)
            .toBeGreaterThan(regions.nodes.find((node) => node.entity.id === 'embed:entity:rowan')?.radius || 0);
        expect(lanes.nodes.some((node) => node.r !== medoids.nodes.find((other) => other.entity.id === node.entity.id)?.r)).toBe(true);
        expect(new Set(backbone.nodes.map((node) => node.entity.id)).size).toBe(3);
    });
});

function packetNodes(): GalaxyRenderableNode[] {
    return [
        packetNode('doc', 'Note', 'structure', 'document', 'note-1', { noteIds: ['note-1'] }),
        packetNode('root', 'Root', 'structure', 'structureRoot', 'root-1', { noteIds: ['note-1'] }),
        packetNode('chunk', 'Chunk', 'structure', 'chunk', 'chunk-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        packetNode('kai', 'Kai', 'registry', 'entity', 'kai', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        packetNode('evidence', 'Evidence span', 'evidence', 'evidenceSpan', 'evidence-1', {
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
        }),
    ];
}

function packetEdges(): GalaxyInputEdge[] {
    return [
        packetEdge('doc-root', 'doc', 'root', 'manifold_parent', 'structure'),
        packetEdge('root-chunk', 'root', 'chunk', 'manifold_parent', 'structure'),
        packetEdge('chunk-kai', 'chunk', 'kai', 'chunk-entity', 'registry'),
        packetEdge('chunk-evidence', 'chunk', 'evidence', 'evidence_anchor', 'evidence'),
    ];
}

function packetNode(
    id: string,
    label: string,
    family: string,
    kind: string,
    sourceId: string,
    refs: { noteIds?: string[]; chunkIds?: string[]; evidenceIds?: string[] },
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: family,
        totalMentions: 1,
        metadata: {
            sourceContract: 'rust-atlas-packet',
            visualTrace: packetTrace(id, family, kind, sourceId, refs),
            visualSourceId: sourceId,
            visualFamily: family,
            graphFamily: family,
            atlasFamily: family,
            atlasKind: kind,
            packetSnapshotId: 'snapshot-product-compat',
            packetScopeId: 'global',
            noteIds: refs.noteIds || [],
            chunkIds: refs.chunkIds || [],
            evidenceIds: refs.evidenceIds || [],
        },
    };
}

function packetEdge(id: string, sourceId: string, targetId: string, type: string, family: string): GalaxyInputEdge {
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
                packetSnapshotId: 'snapshot-product-compat',
                packetScopeId: 'global',
                sourceContract: 'rust-atlas-packet',
                packetObjectId: `object:${sourceId}`,
                packetTargetId: `object:${targetId}`,
            },
        },
    };
}

function packetTrace(
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
        packetSnapshotId: 'snapshot-product-compat',
        packetScopeId: 'global',
        sourceContract: 'rust-atlas-packet',
        packetObjectId: `object:${id}`,
        packetTargetId: `target:${id}`,
        objectKind: kind,
        targetKind: kind,
        noteIds: refs.noteIds || [],
        chunkIds: refs.chunkIds || [],
        evidenceIds: refs.evidenceIds || [],
    };
}

function legacyProductNode(id: string, label: string, lane: string): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: 'PRODUCT:NODE',
        totalMentions: 1,
        metadata: {
            productLaneKind: lane,
            productRegionRole: 'core',
            product: {
                dominantLane: lane,
                lanes: { laneWeights: { [lane]: 1 } },
                fiber: { phase: lane.length * 0.1 },
            },
        },
    };
}

function topologyNode(
    id: string,
    label: string,
    clusterId: string,
    medoidTargetId: string,
    outlierScore: number,
    hubScore: number,
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: 'entity',
        totalMentions: 3,
        metadata: {
            embeddingClusterId: clusterId,
            embeddingMedoidTargetId: medoidTargetId,
            embeddingOutlierScore: outlierScore,
            embeddingHubScore: hubScore,
            productRegionRole: outlierScore >= 0.72 ? 'outlier' : id === medoidTargetId ? 'core' : 'boundary',
            productLaneKind: id.includes('rook') ? 'document' : 'entity',
            product: {
                lanes: {
                    laneWeights: {
                        document: id.includes('rook') ? 0.9 : 0.2,
                        entity: id.includes('rook') ? 0.2 : 0.8,
                    },
                },
            },
        },
    };
}
