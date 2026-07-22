import { describe, expect, it } from 'vitest';

import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { assertGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildGraphRetrievalFusionRuntime } from './graph-retrieval-fusion';

describe('bounded retrieval fusion', () => {
    it('fuses lexical and vector candidates, then expands through asserted evidence topology', () => {
        const snapshot = fixture();
        const registry = assertGraphEvidenceTargetRegistry(snapshot);
        const entityTarget = registry.typedGraphObjects.find((target) => target.sourceId === 'e-kai')!;
        const chunkTarget = registry.chunks[0];
        const runtime = buildGraphRetrievalFusionRuntime(snapshot);

        const result = runtime.retrieve({
            query: 'threshold route',
            limit: 8,
            graphMaxHops: 2,
            graphMaxVisited: 16,
            graphMaxEdges: 32,
        }, {
            available: true,
            candidates: [{ targetId: entityTarget.id, score: 0.98, rank: 1 }],
            evaluated: 4,
            truncated: false,
        });

        expect(result.hits.some((hit) => hit.lanes.includes('lexical'))).toBe(true);
        expect(result.hits.find((hit) => hit.targetId === entityTarget.id)?.lanes).toContain('vector');
        expect(result.hits.find((hit) => hit.targetId === chunkTarget.id)).toBeDefined();
        const graphExpansion = runtime.retrieve({ query: 'term-not-present', limit: 8 }, {
            available: true,
            candidates: [{ targetId: entityTarget.id, score: 0.98, rank: 1 }],
            evaluated: 1,
            truncated: false,
        });
        expect(graphExpansion.hits.find((hit) => hit.targetId === chunkTarget.id)?.lanes).toContain('graph');
        expect(result.receipt.candidateOnly).toBe(true);
        expect(result.receipt.assertedTraversalOnly).toBe(true);
        expect(result.receipt.committedTopologyWrites).toBe(0);
        expect(result.receipt.traversal.candidateEdgesTraversed).toBe(0);
    });

    it('ignores candidate graph suggestions and enforces graph work budgets', () => {
        const snapshot = denseFixture(80);
        snapshot.graphAwareLinkSuggestions = [{ sourceId: 'candidate:a', targetId: 'candidate:b' }] as any;
        const registry = assertGraphEvidenceTargetRegistry(snapshot);
        const runtime = buildGraphRetrievalFusionRuntime(snapshot);
        const seed = registry.chunks[0];

        const result = runtime.retrieve({
            query: 'term-not-present-anywhere',
            limit: 5,
            lexicalLimit: 5,
            vectorLimit: 5,
            graphLimit: 5,
            graphSeedLimit: 1,
            graphMaxHops: 3,
            graphMaxVisited: 8,
            graphMaxEdges: 6,
        }, {
            available: true,
            candidates: [{ targetId: seed.id, score: 1, rank: 1 }],
            evaluated: 1,
            truncated: false,
        });

        expect(result.receipt.traversal.visitedTargets).toBeLessThanOrEqual(8);
        expect(result.receipt.traversal.edgesExamined).toBeLessThanOrEqual(6);
        expect(result.receipt.traversal.candidateEdgesTraversed).toBe(0);
        expect(result.receipt.lanes.find((lane) => lane.lane === 'graph')?.truncated).toBe(true);
        expect(result.hits.every((hit) => registry.exposedTargets.some((target) => target.id === hit.targetId))).toBe(true);
    });

    it('degrades transparently when the real vector index is unavailable', () => {
        const snapshot = fixture();
        const runtime = buildGraphRetrievalFusionRuntime(snapshot);
        const result = runtime.retrieve({ query: 'Kai', limit: 5 }, {
            available: false,
            candidates: [],
            evaluated: 0,
            truncated: false,
            reason: 'real encoder index is not resident',
        });

        expect(result.hits.length).toBeGreaterThan(0);
        expect(result.receipt.lanes.find((lane) => lane.lane === 'vector')).toMatchObject({
            available: false,
            reason: 'real encoder index is not resident',
        });
    });
});

function fixture() {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:retrieval-fusion',
        noteIds: ['note-1'],
        entities: [entity('e-kai', 'Kai'), entity('e-rift', 'Rift')],
        chunks: [{
            id: 'note-1:block:0',
            noteId: 'note-1',
            start: 0,
            end: 80,
            ordinal: 0,
            source: 'note-block',
        }],
        occurrences: [
            occurrence('e-kai', 'Kai', 0, 3),
            occurrence('e-rift', 'Rift', 24, 28),
        ],
        noteTexts: { 'note-1': 'Kai crossed the threshold with Rift because the route was failing.' },
        builtAt: 30,
    });
}

function denseFixture(count: number) {
    const entities = Array.from({ length: count }, (_, index) => entity(`e-${index}`, `Entity ${index}`));
    const text = entities.map((row) => row.label).join(' and ');
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:retrieval-dense',
        noteIds: ['note-dense'],
        entities,
        chunks: [{
            id: 'note-dense:block:0',
            noteId: 'note-dense',
            start: 0,
            end: text.length,
            ordinal: 0,
            source: 'note-block',
        }],
        occurrences: entities.map((row, index) => occurrence(
            row.id,
            row.label,
            index * 12,
            index * 12 + row.label.length,
            'note-dense',
        )),
        noteTexts: { 'note-dense': text },
        builtAt: 31,
    });
}

function entity(id: string, label: string): RegisteredEntity {
    return {
        id,
        label,
        kind: 'CHARACTER',
        aliases: [],
        firstNote: 'note-1',
        mentionsByNote: new Map(),
        totalMentions: 1,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
    };
}

function occurrence(
    entityId: string,
    surface: string,
    sourceStart: number,
    sourceEnd: number,
    noteId = 'note-1',
): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}`,
        noteId,
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd,
        surface,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: surface,
        chunkId: `${noteId}:block:0`,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}
