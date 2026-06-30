import { describe, expect, it } from 'vitest';

import {
    buildGalaxyScene,
    mergeGalaxySettings,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
} from './graph-galaxy-engine';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';
import {
    transitStationLaneOffset,
    transitVisualLanePoint,
} from './graph-transit-backbone-guides';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';

describe('Graph galaxy Transit renderer contract', () => {
    it('attaches a packet-backed TransitPlan before layout', () => {
        const nodes = packetNodes();
        const edges = packetEdges();

        const transit = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'transitManifold' }));
        const productCompat = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const single = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'single' }));

        expect(transit.transitPlan?.receipt).toMatchObject({
            stationCount: 4,
            routeCount: 3,
            packetBackedStations: 4,
            packetBackedRoutes: 3,
            droppedUntracedNodes: 0,
            missingEndpointRoutes: 0,
        });
        expect(transit.transitPlan?.receipt.laneCounts).toMatchObject({
            document: 1,
            root: 1,
            chunk: 1,
            identity: 1,
        });
        expect(productCompat.layoutMode).toBe('transitManifold');
        expect(productCompat.transitPlan?.receipt.stationCount).toBe(4);
        expect(single.transitPlan).toBeUndefined();
    });

    it('preserves packet traceability through the renderer-facing V2 scene', () => {
        const scene = buildGalaxyScene(packetNodes(), packetEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const rendererScene = galaxySceneToV2(scene, 'embeddings');

        expect(rendererScene.layoutMode).toBe('transitManifold');
        expect(rendererScene.transitPlan).toBe(scene.transitPlan);
        expect(rendererScene.transitPlan?.receipt).toMatchObject({
            stationCount: 4,
            routeCount: 3,
            packetBackedStations: 4,
            packetBackedRoutes: 3,
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

    it('renders the packet-native document/root/chunk backbone as guide structure first', () => {
        const scene = buildGalaxyScene(packetNodes(), packetEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const rendererScene = galaxySceneToV2(scene, 'embeddings');
        const guides = rendererScene.lorentzGuides.filter((guide) => guide.treeId === 'transit:backbone');

        expect(guides.map((guide) => guide.id)).toEqual(expect.arrayContaining([
            'transit:backbone:lane:document',
            'transit:backbone:lane:root',
            'transit:backbone:lane:chunk',
            'transit:backbone:route:doc-root',
            'transit:backbone:route:root-chunk',
        ]));
        expect(guides.filter((guide) => guide.guideKind === 'rootLane').map((guide) => guide.treeKind)).toEqual([
            'backbone:document',
            'backbone:root',
            'backbone:chunk',
        ]);
        expect(guides.find((guide) => guide.id === 'transit:backbone:lane:document')).toMatchObject({
            nodeIds: ['doc'],
            guideWeight: expect.any(Number),
        });
        expect(guides.find((guide) => guide.id === 'transit:backbone:route:root-chunk')).toMatchObject({
            nodeIds: ['root', 'chunk'],
            guideKind: 'membership',
            treeKind: 'backbone:root>chunk',
        });
    });

    it('uses Style Lab chunk color for Transit chunk nodes and backbone guides', () => {
        entityColorStore.setGraphNodeColor('chunk', '0 100% 50%');
        try {
            const scene = buildGalaxyScene(packetNodes(), packetEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
            const rendererScene = galaxySceneToV2(scene, 'embeddings');
            const chunk = scene.nodes.find((node) => node.entity.id === 'chunk');
            const chunkLane = scene.lorentzGuides.find((guide) => guide.id === 'transit:backbone:lane:chunk');
            const rootChunk = scene.lorentzGuides.find((guide) => guide.id === 'transit:backbone:route:root-chunk');
            const rendererRootChunk = rendererScene.lorentzGuides.find((guide) => guide.id === 'transit:backbone:route:root-chunk');

            expect(chunk).toMatchObject({ r: 255, g: 0, b: 0 });
            expect(chunkLane).toMatchObject({ r: 255, g: 0, b: 0 });
            expect(rootChunk).toMatchObject({ r: 255, g: 0, b: 0 });
            expect(rendererRootChunk?.color).toEqual({ r: 1, g: 0, b: 0 });
            expect(rendererRootChunk?.sourceColor).toBeUndefined();
        } finally {
            entityColorStore.reset();
        }
    });

    it('uses Style Lab graph-node colors for Transit plan lane guides', () => {
        const originalAnchor = entityColorStore.getRawGraphNodeHsl('anchor');
        const originalEvent = entityColorStore.getRawGraphNodeHsl('eventNode');
        entityColorStore.setGraphNodeColor('anchor', '0 100% 50%');
        entityColorStore.setGraphNodeColor('eventNode', '120 100% 50%');
        try {
            const scene = buildGalaxyScene(lanePacketNodes(), lanePacketEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
            const rendererScene = galaxySceneToV2(scene, 'embeddings');
            const guideById = new Map(rendererScene.lorentzGuides.map((guide) => [guide.id, guide]));

            expect(guideById.get('transit:plan:lane:evidence')?.color).toEqual({ r: 1, g: 0, b: 0 });
            expect(guideById.get('transit:plan:lane:event')?.color).toEqual({ r: 0, g: 1, b: 0 });
            expect(guideById.get('transit:plan:lane:evidence')?.sourceColor).toBeUndefined();
            expect(guideById.get('transit:plan:hub:kai')?.sourceColor).toEqual(rendererNodeColor(rendererScene, 'kai'));
        } finally {
            entityColorStore.setGraphNodeColor('anchor', originalAnchor);
            entityColorStore.setGraphNodeColor('eventNode', originalEvent);
        }
    });

    it('adds packet-native evidence, identity, route, side-band, and review lanes', () => {
        const scene = buildGalaxyScene(lanePacketNodes(), lanePacketEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const rendererScene = galaxySceneToV2(scene, 'embeddings');
        const guideById = new Map(rendererScene.lorentzGuides.map((guide) => [guide.id, guide]));

        expect([...guideById.keys()]).toEqual(expect.arrayContaining([
            'transit:plan:lane:evidence',
            'transit:plan:lane:identity',
            'transit:plan:lane:event',
            'transit:plan:lane:timeline',
            'transit:plan:lane:causal',
            'transit:plan:lane:state',
            'transit:plan:lane:context',
            'transit:plan:lane:discourse',
            'transit:plan:lane:review',
            'transit:plan:lane:proposed',
            'transit:plan:stop:evidence',
            'transit:plan:hub:kai',
            'transit:plan:route:kai-event',
            'transit:plan:route:event-timeline',
            'transit:plan:route:event-causal',
        ]));
        expect(guideById.get('transit:plan:lane:state')).toMatchObject({
            treeId: 'transit:plan-side-bands',
            treeKind: 'side-band:state',
            nodeIds: ['state'],
        });
        expect(guideById.get('transit:plan:lane:proposed')).toMatchObject({
            treeId: 'transit:plan-lanes',
            treeKind: 'lane:proposed',
            nodeIds: ['proposed'],
        });
        expect(guideById.get('transit:plan:route:event-causal')).toMatchObject({
            guideKind: 'membership',
            treeKind: 'route:causal',
            nodeIds: ['event', 'causal'],
        });
    });

    it('uses TransitPlan as layout authority instead of anchoring over Product layout', () => {
        const scene = buildGalaxyScene(lanePacketNodes(), lanePacketEdges(), mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const rendererScene = galaxySceneToV2(scene, 'embeddings');

        for (const id of ['doc', 'root', 'chunk', 'evidence', 'kai', 'event', 'timeline', 'causal', 'state', 'context', 'discourse', 'review', 'proposed']) {
            expect(distanceToStationTarget(rendererScene, id)).toBeLessThan(0.22);
        }
        expect(rendererScene.lorentzGuides.some((guide) => guide.id.startsWith('transit:lane:'))).toBe(false);
        expect(rendererScene.lorentzGuides.some((guide) => guide.id.startsWith('transit:route:'))).toBe(false);
    });

    it('keeps packet chunk stations on their lane when they share a Transit stop', () => {
        const ids = ['chunk-a', 'chunk-b', 'chunk-c', 'chunk-d', 'chunk-e', 'chunk-f'];
        const scene = buildGalaxyScene(
            ids.map((id) => sharedChunkStopNode(id)),
            [],
            mergeGalaxySettings({ layoutMode: 'productManifold' }),
        );
        const rendererScene = galaxySceneToV2(scene, 'embeddings');

        for (const id of ids) expect(distanceToStationTarget(rendererScene, id)).toBeLessThan(0.01);
        expect(axisSpan(rendererScene, ids, 0)).toBeGreaterThan(0.18);
        expect(axisSpan(rendererScene, ids, 1)).toBeLessThan(0.001);
    });

    it('keeps non-chunk Transit rings on their independent offsets', () => {
        const ids = ['kai', 'hazel', 'rift', 'borrik', 'nara', 'orrin'];
        const scene = buildGalaxyScene(
            ids.map((id) => sharedIdentityRingNode(id)),
            [],
            mergeGalaxySettings({ layoutMode: 'productManifold' }),
        );
        const rendererScene = galaxySceneToV2(scene, 'embeddings');

        expect(axisSpan(rendererScene, ids, 0)).toBeGreaterThan(0.5);
    });

    it('does not resurrect Product route-stage guides for untraced compatibility rows', () => {
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

        expect(scene.layoutMode).toBe('transitManifold');
        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(scene.transitPlan?.receipt.droppedUntracedNodes).toBe(4);
        expect(scene.lorentzGuides?.some((guide) => guide.id.startsWith('transit:lane:'))).toBe(false);
        expect(scene.lorentzGuides?.some((guide) => guide.id.startsWith('transit:route:'))).toBe(false);
    });
});

function packetNodes(): GalaxyRenderableNode[] {
    return [
        transitPacketNode('doc', 'Note', 'structure', 'document', 'note-1', { noteIds: ['note-1'] }),
        transitPacketNode('root', 'Root', 'structure', 'structureRoot', 'root-1', { noteIds: ['note-1'] }),
        transitPacketNode('chunk', 'Chunk', 'structure', 'chunk', 'chunk-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        transitPacketNode('kai', 'Kai', 'registry', 'entity', 'kai', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
    ];
}

function packetEdges(): GalaxyInputEdge[] {
    return [
        transitPacketEdge('doc-root', 'doc', 'root', 'manifold_parent', 'structure'),
        transitPacketEdge('root-chunk', 'root', 'chunk', 'manifold_parent', 'structure'),
        transitPacketEdge('chunk-kai', 'chunk', 'kai', 'chunk-entity', 'registry'),
    ];
}

function lanePacketNodes(): GalaxyRenderableNode[] {
    return [
        ...packetNodes(),
        transitPacketNode('evidence', 'Evidence span', 'evidence', 'evidenceSpan', 'evidence-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
        transitPacketNode('event', 'Door opens', 'fact', 'event', 'event-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
        transitPacketNode('timeline', 'Before alarm', 'temporal', 'temporalFact', 'temporal-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
        transitPacketNode('causal', 'Door causes alarm', 'causal', 'causalFact', 'causal-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
        transitPacketNode('state', 'Kai cautious', 'memory', 'memoryState', 'state-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
        transitPacketNode('context', 'Service context', 'context', 'serviceContext', 'context-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        transitPacketNode('discourse', 'Discourse bridge', 'discourse', 'discourseBridge', 'discourse-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        transitPacketNode('review', 'Review row', 'review', 'reviewCandidate', 'review-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
        transitPacketNode('proposed', 'Proposed relation', 'proposed', 'proposedRelationship', 'proposed-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'], evidenceIds: ['evidence-1'] }),
    ];
}

function lanePacketEdges(): GalaxyInputEdge[] {
    return [
        ...packetEdges(),
        transitPacketEdge('chunk-evidence', 'chunk', 'evidence', 'evidence_anchor', 'evidence'),
        transitPacketEdge('evidence-kai', 'evidence', 'kai', 'identity_anchor', 'registry'),
        transitPacketEdge('kai-event', 'kai', 'event', 'event_identity', 'fact'),
        transitPacketEdge('event-timeline', 'event', 'timeline', 'temporal_before', 'temporal'),
        transitPacketEdge('event-causal', 'event', 'causal', 'causal_effect', 'causal'),
        transitPacketEdge('kai-state', 'kai', 'state', 'memory_state', 'memory'),
        transitPacketEdge('kai-context', 'kai', 'context', 'service_context', 'context'),
        transitPacketEdge('chunk-discourse', 'chunk', 'discourse', 'discourse_bridge', 'discourse'),
        transitPacketEdge('review-proposed', 'review', 'proposed', 'proposed_candidate', 'proposed'),
    ];
}

function distanceToStationTarget(
    scene: ReturnType<typeof galaxySceneToV2>,
    nodeId: string,
): number {
    const station = scene.transitPlan?.stations.find((item) => item.nodeId === nodeId);
    if (!station) return Number.POSITIVE_INFINITY;
    const target = transitVisualLanePoint(station.lane, transitStationLaneOffset(station));
    const index = scene.ids.indexOf(nodeId);
    if (!target || index < 0) return Number.POSITIVE_INFINITY;
    const offset = index * 3;
    return Math.hypot(
        scene.positions3d[offset] - target.x,
        scene.positions3d[offset + 1] - target.y,
        scene.positions3d[offset + 2] - target.z,
    );
}

function axisSpan(scene: ReturnType<typeof galaxySceneToV2>, ids: string[], axis: 0 | 1 | 2): number {
    const values = ids
        .map((id) => scene.ids.indexOf(id))
        .filter((index) => index >= 0)
        .map((index) => scene.positions3d[index * 3 + axis]);
    return Math.max(...values) - Math.min(...values);
}

function rendererNodeColor(scene: ReturnType<typeof galaxySceneToV2>, nodeId: string): { r: number; g: number; b: number } | undefined {
    const index = scene.ids.indexOf(nodeId);
    if (index < 0) return undefined;
    const offset = index * 3;
    return {
        r: scene.colors[offset],
        g: scene.colors[offset + 1],
        b: scene.colors[offset + 2],
    };
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

function sharedChunkStopNode(id: string): GalaxyRenderableNode {
    const node = transitPacketNode(id, id, 'structure', 'chunk', id, { noteIds: ['note-1'], chunkIds: ['chunk-1'] });
    return {
        ...node,
        metadata: {
            ...node.metadata,
            visualTrace: {
                ...(node.metadata?.['visualTrace'] as Record<string, unknown>),
                packetTargetId: 'target:chunk-1:identity-stop',
            },
        },
    };
}

function sharedIdentityRingNode(id: string): GalaxyRenderableNode {
    return transitPacketNode(id, id, 'registry', 'entity', id, { noteIds: ['note-1'], chunkIds: ['chunk-1'] });
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
