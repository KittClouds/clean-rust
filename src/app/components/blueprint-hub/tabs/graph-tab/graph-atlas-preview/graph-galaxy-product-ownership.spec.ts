import { describe, expect, it } from 'vitest';

import type { GalaxyEdge, GalaxyNode } from './graph-galaxy-engine';
import { compileProductOwnership } from './graph-galaxy-product-ownership';

describe('Transit graph ownership compiler', () => {
    it('cascades every graph-model family through document, chunk, entity, event, and evidence parents', () => {
        const nodes = [
            node('embed:note:n1', 'note', [], { noteId: 'n1' }),
            node('embed:structure-root:n1:document-structure', 'structure-root', ['embed:note:n1'], { noteId: 'n1' }),
            node('embed:structure-root:n1:identity', 'structure-root', ['embed:note:n1'], { noteId: 'n1' }),
            node('embed:structure-root:n1:temporal', 'structure-root', ['embed:note:n1'], { noteId: 'n1' }),
            node('embed:structure-root:n1:causal', 'structure-root', ['embed:note:n1'], { noteId: 'n1' }),
            node('embed:structure-root:n1:evidence', 'structure-root', ['embed:note:n1'], { noteId: 'n1' }),
            node('embed:chunk:c1', 'chunk', ['embed:structure-root:n1:document-structure'], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:entity:kai', 'entity', ['embed:chunk:c1', 'embed:structure-root:n1:identity'], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:event:e1', 'event', ['embed:structure-root:n1:temporal', 'embed:chunk:c1', 'embed:entity:kai'], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:causalFact:cf1', 'causal-fact', ['embed:structure-root:n1:causal', 'embed:event:e1'], { noteId: 'n1', signalLane: 'causal_fact' }),
            node('embed:temporalFact:tf1', 'temporal-fact', ['embed:structure-root:n1:temporal', 'embed:event:e1'], { noteId: 'n1', signalLane: 'temporal_fact' }),
            node('embed:graph-fact:rel1', 'graph-fact', ['embed:entity:kai', 'embed:chunk:c1'], { noteId: 'n1', chunkId: 'c1', signalLane: 'relationship_fact' }),
            node('embed:memory:m1', 'memory-state', ['embed:structure-root:n1:identity', 'embed:entity:kai'], { noteId: 'n1', signalLane: 'memory_state' }),
            node('embed:anchor:a1', 'anchor', ['embed:structure-root:n1:evidence', 'embed:chunk:c1', 'embed:entity:kai'], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:graph-fact:weak1', 'graph-fact', ['embed:entity:kai', 'embed:chunk:c1'], { noteId: 'n1', chunkId: 'c1', signalLane: 'cooccurrence_weak' }),
        ];
        const records = byId(compileProductOwnership(nodes, []));
        const chunkRegion = 'transit:story:n1:chunk:c1';
        const ownedIds = [
            'embed:causalFact:cf1',
            'embed:temporalFact:tf1',
            'embed:graph-fact:rel1',
            'embed:memory:m1',
            'embed:anchor:a1',
            'embed:graph-fact:weak1',
        ];

        expect(records.get('embed:chunk:c1')!.regionId).toBe(chunkRegion);
        expect(records.get('embed:entity:kai')!.regionId).toBe(chunkRegion);
        expect(records.get('embed:event:e1')!.regionId).toBe(chunkRegion);
        for (const id of ownedIds) {
            const record = records.get(id)!;
            expect(record.regionId).toBe(chunkRegion);
            expect(record.ownerEntityId).toBe('kai');
            expect(record.noteIds).toContain('n1');
            expect(record.chunkIds).toContain('c1');
            expect(record.ancestorIds).toContain('embed:chunk:c1');
        }
        expect(records.get('embed:causalFact:cf1')!.primaryParentId).toBe('embed:event:e1');
        expect(records.get('embed:temporalFact:tf1')!.primaryParentId).toBe('embed:event:e1');
        expect(records.get('embed:graph-fact:rel1')!.primaryParentId).toBe('embed:entity:kai');
        expect(records.get('embed:memory:m1')!.primaryParentId).toBe('embed:entity:kai');
        expect(records.get('embed:graph-fact:weak1')!.lane).toBe('cooccurrence');
        expect(records.get('embed:graph-fact:weak1')!.role).toBe('bridge');
    });

    it('uses GraphModelV2 fact-role edges as ownership when parentIds are sparse', () => {
        const nodes = [
            node('embed:chunk:c1', 'chunk', [], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:entity:kai', 'entity', ['embed:chunk:c1'], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:event:e1', 'event', ['embed:chunk:c1'], { noteId: 'n1', chunkId: 'c1' }),
            node('embed:causalFact:cf1', 'causal-fact', [], { noteId: 'n1', signalLane: 'causal_fact' }),
            node('embed:graph-fact:rel1', 'graph-fact', [], { noteId: 'n1', signalLane: 'relationship_fact' }),
            node('embed:memory:m1', 'memory-state', [], { noteId: 'n1', signalLane: 'memory_state' }),
        ];
        const edges: GalaxyEdge[] = [
            edge(3, 2, 'cause'),
            edge(4, 1, 'source'),
            edge(5, 1, 'subject'),
            edge(2, 1, 'event-entity'),
        ];
        const records = byId(compileProductOwnership(nodes, edges));

        expect(records.get('embed:causalFact:cf1')!.ownerEntityId).toBe('kai');
        expect(records.get('embed:graph-fact:rel1')!.ownerEntityId).toBe('kai');
        expect(records.get('embed:memory:m1')!.ownerEntityId).toBe('kai');
        expect(records.get('embed:causalFact:cf1')!.primaryParentId).toBe('embed:event:e1');
        expect(records.get('embed:graph-fact:rel1')!.primaryParentId).toBe('embed:entity:kai');
    });
});

function byId(records: ReturnType<typeof compileProductOwnership>): Map<string, ReturnType<typeof compileProductOwnership>[number]> {
    return new Map(records.map((record) => [record.nodeId, record]));
}

function node(id: string, sourceType: string, parentIds: string[], metadata: Record<string, unknown>): GalaxyNode {
    return {
        entity: {
            id,
            label: id,
            kind: sourceType,
            metadata: {
                sourceType,
                signalParentIds: parentIds,
                ...metadata,
            },
        },
        x: 0, y: 0, z: 0, baseX: 0, baseY: 0, baseZ: 0,
        radius: 1, sx: 0, sy: 0, depth: 0, galaxyOpacity: 1,
        r: 0, g: 0, b: 0,
    };
}

function edge(source: number, target: number, type: string): GalaxyEdge {
    return { id: `${type}:${source}:${target}`, source, target, type, confidence: 0.9, alpha: 1, curve: 0, flowOffset: 0 };
}
