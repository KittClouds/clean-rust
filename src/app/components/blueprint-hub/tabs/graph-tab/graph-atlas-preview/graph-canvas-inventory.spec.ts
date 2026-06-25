import { describe, expect, it } from 'vitest';

import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { filterGraphForCanvasLens } from './graph-canvas-interaction';
import { buildGraphCanvasInventory } from './graph-canvas-inventory';

describe('graph canvas inventory', () => {
    it('renders Rust Atlas packet families and status as the graph canvas contract', () => {
        const inventory = buildGraphCanvasInventory(snapshot());

        expect(inventory.sourceLabel).toBe('rust-atlas-packet / no model vectors persisted');
        expect(inventory.kindCounts).toEqual([
            { kind: 'structure', count: 2 },
            { kind: 'discourse', count: 1 },
            { kind: 'entity', count: 1 },
            { kind: 'fact', count: 1 },
            { kind: 'review', count: 1 },
        ]);

        const entity = inventory.nodes.find((node) => node.id === 'entity:amara');
        const fact = inventory.nodes.find((node) => node.id === 'fact:rel-1');
        const review = inventory.nodes.find((node) => node.id === 'review:row-1');
        const discourse = inventory.nodes.find((node) => node.id === 'discourse:bridge-1');
        const chunk = inventory.nodes.find((node) => node.id === 'chunk:note-1:0');
        const parentEdge = inventory.edges.find((edge) => edge.id === 'atlas-packet:manifold_parent:document:note-1->chunk:note-1:0');

        expect(entity?.kind).toBe('entity');
        expect(entity?.metadata?.['canvasLens']).toBe('entities');
        expect(entity?.metadata?.['reviewState']).toBe('accepted');
        expect(fact?.kind).toBe('fact');
        expect(fact?.metadata?.['canvasLens']).toBe('facts');
        expect(fact?.metadata?.['reviewState']).toBe('accepted');
        expect(fact?.metadata?.['graphColorKind']).toBe('cooccurrence');
        expect(fact?.metadata?.['graphRelationFamily']).toBe('cooccurrence');
        expect(review?.kind).toBe('review');
        expect(review?.metadata?.['canvasLens']).toBe('facts');
        expect(review?.metadata?.['reviewState']).toBe('proposed');
        expect(discourse?.kind).toBe('discourse');
        expect(discourse?.metadata?.['canvasLens']).toBe('discourse');
        expect(discourse?.metadata?.['graphColorKind']).toBe('communication');
        expect(chunk?.metadata?.['atlasTargetId']).toBe('embed:chunk:note-1:0');
        expect(parentEdge).toMatchObject({
            sourceId: 'document:note-1',
            targetId: 'chunk:note-1:0',
            type: 'manifold_parent',
        });
        for (const node of inventory.nodes) {
            expect(node.metadata).toMatchObject({
                sourceContract: 'rust-atlas-packet',
                packetSnapshotId: 'snapshot-1',
                packetScopeId: 'scope-1',
                visualTrace: expect.objectContaining({
                    source: 'rust_atlas_packet',
                    family: node.kind,
                    packetSnapshotId: 'snapshot-1',
                    sourceContract: 'rust-atlas-packet',
                }),
            });
            expect(String(node.metadata?.['visualSourceId'] || '')).not.toBe('');
        }
        for (const edge of inventory.edges) {
            expect(edge.metadata).toMatchObject({
                sourceContract: 'rust-atlas-packet',
                packetSnapshotId: 'snapshot-1',
                packetScopeId: 'scope-1',
                visualTrace: expect.objectContaining({
                    source: 'rust_atlas_packet',
                    family: edge.metadata?.['graphFamily'],
                    packetSnapshotId: 'snapshot-1',
                    sourceContract: 'rust-atlas-packet',
                }),
            });
            expect(String(edge.metadata?.['visualSourceId'] || '')).not.toBe('');
        }

        const factLens = filterGraphForCanvasLens(inventory.nodes, inventory.edges, 'facts');
        expect(factLens.nodes.map((node) => node.id).sort()).toEqual([
            'entity:amara',
            'fact:rel-1',
            'review:row-1',
        ]);

        const proposedLens = filterGraphForCanvasLens(inventory.nodes, inventory.edges, 'proposed');
        expect(proposedLens.nodes.map((node) => node.id).sort()).toEqual([
            'chunk:note-1:0',
            'discourse:bridge-1',
            'document:note-1',
            'fact:rel-1',
            'review:row-1',
        ]);

        const discourseLens = filterGraphForCanvasLens(inventory.nodes, inventory.edges, 'discourse');
        expect(discourseLens.nodes.map((node) => node.id)).toEqual(['discourse:bridge-1']);
    });

    it('derives Style Lab keys from Rust Atlas object kinds', () => {
        const next = snapshot();
        next.atlasPacket!.objects.push(
            atlasObject('fact:event-1', 'fact', 'accepted', 'event', 'Amara enters'),
            atlasObject('temporal:1', 'temporal', 'accepted', 'temporalFact', 'before'),
            atlasObject('causal:1', 'causal', 'accepted', 'causalFact', 'because'),
            {
                ...atlasObject('memory:1', 'memory', 'accepted', 'memoryState', 'plain label'),
                styleKey: 'decisionState',
                stateContextKind: 'decisionState',
                lane: 'memory_state',
                structuralRole: 'child',
            },
        );

        const inventory = buildGraphCanvasInventory(next);
        const styleKey = (id: string) => inventory.nodes.find((node) => node.id === id)?.metadata?.['graphColorKind'];

        expect(styleKey('fact:rel-1')).toBe('cooccurrence');
        expect(styleKey('fact:event-1')).toBe('eventNode');
        expect(styleKey('temporal:1')).toBe('temporalFact');
        expect(styleKey('causal:1')).toBe('causalFact');
        expect(styleKey('memory:1')).toBe('decisionState');
    });

    it('does not synthesize TS graph rows when the Rust packet is absent', () => {
        const inventory = buildGraphCanvasInventory(null);

        expect(inventory.nodes).toEqual([]);
        expect(inventory.edges).toEqual([]);
        expect(inventory.sourceLabel).toBe('rust atlas packet missing');
    });
});

function snapshot(): GraphRebuildSnapshot {
    return {
        atlasPacket: {
            schemaVersion: 'phoenix-atlas-packet/v1',
            snapshotId: 'snapshot-1',
            scopeKind: 'folder',
            scopeId: 'scope-1',
            builtAt: 1,
            sourceContract: {
                authority: 'rust-atlas-packet',
                identityAuthority: 'registry-entities-and-accepted-anchors',
                vectorContract: 'no model vectors persisted',
                tsGraphBuilderRole: 'native-atlas-packet-authority',
            },
            objects: [
                {
                    id: 'entity:amara',
                    family: 'entity',
                    status: 'accepted',
                    kind: 'character',
                    label: 'Amara',
                    registryEntityId: 'entity:amara',
                    noteIds: ['note-1'],
                    chunkIds: ['note-1:0'],
                    anchorIds: ['anchor-1'],
                    evidenceIds: ['anchor-1'],
                    sourceIds: ['entity:amara'],
                    targetIds: [],
                },
                {
                    id: 'document:note-1',
                    family: 'structure',
                    status: 'ledgerOnly',
                    kind: 'document',
                    label: 'Note 1',
                    noteIds: ['note-1'],
                    chunkIds: [],
                    anchorIds: [],
                    evidenceIds: [],
                    sourceIds: ['note-1'],
                    targetIds: [],
                },
                {
                    id: 'chunk:note-1:0',
                    family: 'structure',
                    status: 'ledgerOnly',
                    kind: 'chunk',
                    label: 'Chunk 1',
                    noteIds: ['note-1'],
                    chunkIds: ['note-1:0'],
                    anchorIds: [],
                    evidenceIds: [],
                    sourceIds: ['note-1:0'],
                    targetIds: [],
                },
                {
                    id: 'fact:rel-1',
                    family: 'fact',
                    status: 'compiledToGraph',
                    kind: 'co_occurs_with',
                    label: 'Amara co-occurs',
                    noteIds: ['note-1'],
                    chunkIds: ['note-1:0'],
                    anchorIds: [],
                    evidenceIds: ['evidence-1'],
                    sourceIds: ['rel-1'],
                    targetIds: ['entity:amara'],
                },
                {
                    id: 'review:row-1',
                    family: 'review',
                    status: 'review',
                    kind: 'candidate',
                    label: 'Review row',
                    noteIds: ['note-1'],
                    chunkIds: ['note-1:0'],
                    anchorIds: [],
                    evidenceIds: ['evidence-1'],
                    sourceIds: ['row-1'],
                    targetIds: ['fact:rel-1'],
                },
                {
                    id: 'discourse:bridge-1',
                    family: 'discourse',
                    status: 'review',
                    kind: 'discourseBridge',
                    label: 'Kai and Rift echo across chunks',
                    noteIds: ['note-1'],
                    chunkIds: ['note-1:0'],
                    anchorIds: [],
                    evidenceIds: ['embed:chunk:note-1:0'],
                    sourceIds: ['discourse-bridge:1'],
                    targetIds: [],
                },
            ],
            manifoldTargets: [
                {
                    id: 'embed:document:note-1',
                    objectId: 'document:note-1',
                    family: 'structure',
                    admission: 'candidate',
                    status: 'proposed',
                    vectorStatus: 'missing',
                    coordinateSource: 'none',
                    kind: 'document',
                    label: 'Note 1',
                    sourceId: 'note-1',
                    noteId: 'note-1',
                    evidenceIds: [],
                    parentIds: [],
                },
                {
                    id: 'embed:chunk:note-1:0',
                    objectId: 'chunk:note-1:0',
                    family: 'structure',
                    admission: 'candidate',
                    status: 'proposed',
                    vectorStatus: 'missing',
                    coordinateSource: 'none',
                    kind: 'chunk',
                    label: 'Chunk 1',
                    sourceId: 'note-1:0',
                    noteId: 'note-1',
                    chunkId: 'note-1:0',
                    evidenceIds: [],
                    parentIds: ['embed:document:note-1'],
                },
            ],
            counters: {
                objects: 6,
                manifoldTargets: 2,
                registryEntities: 1,
                evidenceAnchors: 1,
                modelVectors: 0,
                families: [],
            },
        },
    } as unknown as GraphRebuildSnapshot;
}

function atlasObject(
    id: string,
    family: string,
    status: string,
    kind: string,
    label: string,
) {
    return {
        id,
        family,
        status,
        kind,
        label,
        noteIds: ['note-1'],
        chunkIds: ['note-1:0'],
        anchorIds: [],
        evidenceIds: ['evidence-1'],
        sourceIds: [id],
        targetIds: [],
    } as any;
}
