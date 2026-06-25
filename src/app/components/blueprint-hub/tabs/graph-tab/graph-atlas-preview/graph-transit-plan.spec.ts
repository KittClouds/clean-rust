import { describe, expect, it } from 'vitest';

import type {
    GraphAtlasFamily,
    GraphAtlasObjectStatus,
    GraphAtlasPacket,
} from '../../../../../graph-rebuild/graph-atlas-packet';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import { buildGraphPacketRowAdapter } from './graph-packet-row-adapter';
import { buildTransitPlan } from './graph-transit-plan';

describe('TransitPlan builder', () => {
    it('freezes a packet-backed golden snapshot shape as Transit stations and routes', () => {
        const rows = buildGraphPacketRowAdapter(transitPacketFixture());

        const plan = buildTransitPlan(rows.graphNodes, rows.graphEdges);

        expect(rows.sourceLabel).toBe('rust-atlas-packet / vectors-missing');
        expect(plan.receipt).toMatchObject({
            stationCount: 12,
            routeCount: 29,
            packetBackedStations: 12,
            packetBackedRoutes: 29,
            droppedUntracedNodes: 0,
            missingEndpointRoutes: 0,
            edgeTraceFallbackRoutes: 0,
        });
        expect(plan.receipt.laneCounts).toEqual({
            document: 1,
            root: 1,
            chunk: 1,
            evidence: 1,
            identity: 1,
            relationship: 1,
            event: 1,
            timeline: 1,
            causal: 1,
            state: 1,
            discourse: 1,
            review: 1,
        });
        expect(plan.receipt.routeLaneCounts).toMatchObject({
            root: 1,
            chunk: 1,
            evidence: 1,
            identity: 1,
            timeline: 1,
            causal: 1,
            transfer: 18,
        });
        expect(plan.regions.map((region) => region.id)).toEqual(expect.arrayContaining([
            'transit:document:note-1',
            'transit:chunk:chunk-1',
            'transit:family:causal',
            'transit:family:discourse',
        ]));
        expect(plan.stations.every((station) => station.trace?.packetSnapshotId === 'snapshot-transit-golden')).toBe(true);
        expect(plan.routes.every((route) => route.trace?.source === 'rust_atlas_packet')).toBe(true);
        expect(plan.stations.find((station) => station.nodeId === 'causal:alarm')).toMatchObject({
            lane: 'causal',
            packetBacked: true,
            packetObjectId: 'causal:alarm',
            regionIds: expect.arrayContaining(['transit:family:causal', 'transit:chunk:chunk-1']),
        });
        expect(plan.routes.find((route) => route.edgeId === 'atlas-packet:manifold_parent:event:door->causal:alarm')).toMatchObject({
            lane: 'causal',
            sourceLane: 'event',
            targetLane: 'causal',
            directed: true,
            packetBacked: true,
        });
    });

    it('builds stations, routes, and regions from packet-backed render rows', () => {
        const nodes = [
            stationNode('note', 'Note', 'structure', 'document', 'note-1', { noteIds: ['note-1'] }),
            stationNode('root', 'Identity root', 'structure', 'structureRoot', 'note-1:identity', { noteIds: ['note-1'] }),
            stationNode('chunk', 'Chunk', 'structure', 'chunk', 'chunk-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
            stationNode('kai', 'Kai', 'registry', 'entity', 'kai', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
            stationNode('event', 'Door opens', 'fact', 'event', 'event-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
            stationNode('memory', 'Kai is cautious', 'memory', 'memoryState', 'memory-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
            stationNode('cause', 'Door causes alarm', 'causal', 'causalFact', 'cause-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        ];
        const edges = [
            routeEdge('note-root', 'note', 'root', 'manifold_parent', 'structure'),
            routeEdge('root-chunk', 'root', 'chunk', 'manifold_parent', 'structure'),
            routeEdge('chunk-kai', 'chunk', 'kai', 'chunk-entity', 'registry'),
            routeEdge('kai-event', 'kai', 'event', 'event-entity', 'fact'),
            routeEdge('event-cause', 'event', 'cause', 'causes', 'causal'),
            routeEdge('kai-memory', 'kai', 'memory', 'memory-entity', 'memory'),
        ];

        const plan = buildTransitPlan(nodes, edges);
        const laneByNode = new Map(plan.stations.map((station) => [station.nodeId, station.lane]));

        expect(plan.schemaVersion).toBe('graph-transit-plan/v1');
        expect(plan.receipt).toMatchObject({
            stationCount: 7,
            routeCount: 6,
            packetBackedStations: 7,
            packetBackedRoutes: 6,
            droppedUntracedNodes: 0,
            missingEndpointRoutes: 0,
        });
        expect(laneByNode).toEqual(new Map([
            ['note', 'document'],
            ['root', 'root'],
            ['chunk', 'chunk'],
            ['kai', 'identity'],
            ['event', 'event'],
            ['memory', 'state'],
            ['cause', 'causal'],
        ]));
        expect(plan.receipt.familyCounts).toMatchObject({ structure: 3, registry: 1, fact: 1, memory: 1, causal: 1 });
        expect(plan.receipt.routeLaneCounts).toMatchObject({ causal: 1, event: 1, evidence: 1 });
        expect(plan.regions.map((region) => region.id)).toEqual(expect.arrayContaining([
            'transit:document:note-1',
            'transit:chunk:chunk-1',
            'transit:family:registry',
            'transit:family:causal',
        ]));
        expect(plan.routes.find((route) => route.edgeId === 'event-cause')).toMatchObject({
            lane: 'causal',
            sourceLane: 'event',
            targetLane: 'causal',
            directed: true,
            packetBacked: true,
        });
    });

    it('keeps endpoint-derived trace when an edge has no packet trace', () => {
        const nodes = [
            stationNode('chunk', 'Chunk', 'structure', 'chunk', 'chunk-1', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
            stationNode('kai', 'Kai', 'registry', 'entity', 'kai', { noteIds: ['note-1'], chunkIds: ['chunk-1'] }),
        ];
        const edges: GalaxyInputEdge[] = [{ id: 'chunk-kai', sourceId: 'chunk', targetId: 'kai', type: 'chunk-entity', confidence: 0.9 }];

        const plan = buildTransitPlan(nodes, edges);

        expect(plan.receipt.edgeTraceFallbackRoutes).toBe(1);
        expect(plan.routes[0]).toMatchObject({
            edgeId: 'chunk-kai',
            packetBacked: true,
            trace: expect.objectContaining({ source: 'rust_atlas_packet' }),
            sourceTrace: expect.objectContaining({ packetObjectId: 'object:chunk' }),
            targetTrace: expect.objectContaining({ packetObjectId: 'object:kai' }),
        });
    });

    it('drops untraced nodes by default and reports routes that lose endpoints', () => {
        const nodes: GalaxyRenderableNode[] = [
            stationNode('kai', 'Kai', 'registry', 'entity', 'kai'),
            { id: 'loose', label: 'Loose', kind: 'fact', metadata: { sourceId: 'loose' } },
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'kai-loose', sourceId: 'kai', targetId: 'loose', type: 'target', confidence: 0.4 },
        ];

        const plan = buildTransitPlan(nodes, edges);

        expect(plan.stations.map((station) => station.nodeId)).toEqual(['kai']);
        expect(plan.routes).toEqual([]);
        expect(plan.receipt).toMatchObject({
            droppedUntracedNodes: 1,
            missingEndpointRoutes: 1,
        });
    });
});

function stationNode(
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
        metadata: {
            sourceType: 'rust-atlas-packet-object',
            sourceId,
            sourceContract: 'rust-atlas-packet',
            vectorContract: 'vectors-missing',
            visualTrace: trace(id, family, kind, sourceId, refs),
            visualSourceId: sourceId,
            visualFamily: family,
            graphFamily: family,
            atlasFamily: family,
            atlasKind: kind,
            packetSnapshotId: 'snapshot-transit',
            packetScopeId: 'global',
            noteIds: refs.noteIds || [],
            chunkIds: refs.chunkIds || [],
            evidenceIds: refs.evidenceIds || [],
        },
    };
}

function routeEdge(id: string, sourceId: string, targetId: string, type: string, family: string): GalaxyInputEdge {
    return {
        id,
        sourceId,
        targetId,
        type,
        confidence: 0.82,
        metadata: {
            sourceContract: 'rust-atlas-packet',
            graphFamily: family,
            visualTrace: {
                source: 'rust_atlas_packet',
                sourceId,
                family,
                packetSnapshotId: 'snapshot-transit',
                packetScopeId: 'global',
                sourceContract: 'rust-atlas-packet',
                vectorContract: 'vectors-missing',
                packetObjectId: `object:${sourceId}`,
                packetTargetId: `object:${targetId}`,
            },
        },
    };
}

function trace(
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
        packetSnapshotId: 'snapshot-transit',
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

function transitPacketFixture(): GraphAtlasPacket {
    const objects = [
        atlasObject('document:note-1', 'structure', 'ledgerOnly', 'document', 'Note 1', {
            sourceIds: ['note-1'],
            noteIds: ['note-1'],
            targetIds: ['root:note-1'],
        }),
        atlasObject('root:note-1', 'structure', 'ledgerOnly', 'structureRoot', 'Identity root', {
            sourceIds: ['root:note-1'],
            noteIds: ['note-1'],
            targetIds: ['chunk:note-1:0'],
            structuralRole: 'root',
            documentUnitKind: 'section',
        }),
        atlasObject('chunk:note-1:0', 'structure', 'ledgerOnly', 'chunk', 'Chunk 1', {
            sourceIds: ['chunk-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            targetIds: ['evidence:span-1', 'entity:kai', 'event:door', 'memory:kai-state'],
        }),
        atlasObject('evidence:span-1', 'evidence', 'promotedToAnchor', 'evidenceSpan', 'Source span', {
            sourceIds: ['evidence-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            anchorIds: ['anchor-1'],
            targetIds: ['fact:rel-1'],
        }),
        atlasObject('entity:kai', 'registry', 'accepted', 'character', 'Kai', {
            sourceIds: ['entity:kai'],
            registryEntityId: 'entity:kai',
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['anchor-1'],
            targetIds: ['fact:rel-1', 'memory:kai-state'],
            styleKey: 'CHARACTER',
        }),
        atlasObject('fact:rel-1', 'fact', 'compiledToGraph', 'graphFact', 'Kai opens the door', {
            sourceIds: ['rel-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            targetIds: ['entity:kai', 'event:door'],
            styleKey: 'communication',
        }),
        atlasObject('event:door', 'fact', 'accepted', 'event', 'Door opens', {
            sourceIds: ['event-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            targetIds: ['temporal:before', 'causal:alarm'],
            styleKey: 'eventNode',
        }),
        atlasObject('temporal:before', 'temporal', 'accepted', 'temporalFact', 'Before the alarm', {
            sourceIds: ['temporal-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            targetIds: ['event:door'],
        }),
        atlasObject('causal:alarm', 'causal', 'accepted', 'causalFact', 'Door causes alarm', {
            sourceIds: ['causal-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            targetIds: ['event:door'],
        }),
        atlasObject('memory:kai-state', 'memory', 'proposed', 'memoryState', 'Kai is cautious', {
            sourceIds: ['memory-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            targetIds: ['entity:kai'],
            stateContextKind: 'decisionState',
        }),
        atlasObject('discourse:bridge-1', 'discourse', 'review', 'discourseBridge', 'Echo across chunks', {
            sourceIds: ['discourse-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['chunk-1'],
            targetIds: ['chunk:note-1:0'],
        }),
        atlasObject('review:row-1', 'review', 'review', 'candidate', 'Proposed relationship', {
            sourceIds: ['review-1'],
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            evidenceIds: ['evidence-1'],
            targetIds: ['fact:rel-1'],
        }),
    ];
    const targets = objects.map((object) => atlasTarget(object, parentTargetIds(object.id)));
    return {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: 'snapshot-transit-golden',
        scopeKind: 'global',
        scopeId: 'global',
        builtAt: 1,
        sourceContract: {
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            vectorContract: 'vectors-missing',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        },
        objects,
        manifoldTargets: targets,
        counters: {
            objects: objects.length,
            manifoldTargets: targets.length,
            registryEntities: 1,
            evidenceAnchors: 1,
            modelVectors: 0,
            families: Object.entries(objects.reduce<Record<string, number>>((counts, object) => {
                counts[object.family] = (counts[object.family] || 0) + 1;
                return counts;
            }, {})).map(([family, count]) => ({ family: family as GraphAtlasFamily, count })),
        },
    };
}

function atlasObject(
    id: string,
    family: GraphAtlasFamily,
    status: GraphAtlasObjectStatus,
    kind: string,
    label: string,
    overrides: Partial<GraphAtlasPacket['objects'][number]>,
): GraphAtlasPacket['objects'][number] {
    return {
        id,
        family,
        status,
        kind,
        label,
        noteIds: [],
        chunkIds: [],
        anchorIds: [],
        evidenceIds: [],
        sourceIds: [],
        targetIds: [],
        ...overrides,
    };
}

function atlasTarget(
    object: GraphAtlasPacket['objects'][number],
    parentIds: string[],
): GraphAtlasPacket['manifoldTargets'][number] {
    return {
        id: `target:${object.id}`,
        objectId: object.id,
        family: object.family,
        admission: object.status === 'rejected' ? 'rejected' : object.status === 'accepted' || object.status === 'compiledToGraph' || object.status === 'promotedToAnchor' ? 'admitted' : 'candidate',
        status: object.status || 'unknown',
        vectorStatus: 'missing',
        coordinateSource: 'packet-golden',
        kind: object.kind,
        label: object.label,
        styleKey: object.styleKey,
        lane: object.lane,
        structuralRole: object.structuralRole,
        documentUnitKind: object.documentUnitKind,
        stateContextKind: object.stateContextKind,
        sourceId: object.sourceIds[0] || object.id,
        registryEntityId: object.registryEntityId,
        noteId: object.noteIds[0],
        chunkId: object.chunkIds[0],
        evidenceIds: object.evidenceIds,
        parentIds,
    };
}

function parentTargetIds(objectId: string): string[] {
    switch (objectId) {
        case 'root:note-1': return ['target:document:note-1'];
        case 'chunk:note-1:0': return ['target:root:note-1'];
        case 'evidence:span-1':
        case 'entity:kai':
        case 'event:door':
        case 'discourse:bridge-1':
            return ['target:chunk:note-1:0'];
        case 'fact:rel-1': return ['target:evidence:span-1'];
        case 'temporal:before':
        case 'causal:alarm':
            return ['target:event:door'];
        case 'memory:kai-state': return ['target:entity:kai'];
        case 'review:row-1': return ['target:fact:rel-1'];
        default: return [];
    }
}
