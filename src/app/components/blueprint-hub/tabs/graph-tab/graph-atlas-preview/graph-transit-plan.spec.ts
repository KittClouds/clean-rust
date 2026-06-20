import { describe, expect, it } from 'vitest';

import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import { buildTransitPlan } from './graph-transit-plan';

describe('TransitPlan builder', () => {
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
