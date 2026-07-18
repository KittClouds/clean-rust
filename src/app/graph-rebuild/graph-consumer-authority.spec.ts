import { describe, expect, it } from 'vitest';

import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import {
    assertGraphConsumerReadOnly,
    assertSnapshotGraphConsumersReadOnly,
    withGraphConsumerAuthority,
} from './graph-consumer-authority';

describe('manifold and GFM graph consumer authority', () => {
    it('certifies projected manifold nodes and edges as read-only presentation', () => {
        const output = {
            manifold: 'hopf',
            payload: {
                nodes: [{ id: 'node:a', position: [0, 1, 0] }],
                edges: [{ id: 'edge:a:b', sourceId: 'node:a', targetId: 'node:b' }],
                committedTopologyWrites: 0,
            },
        };

        const sealed = withGraphConsumerAuthority('manifold', 'snapshot:1', output);

        expect(sealed.consumerAuthority).toMatchObject({
            consumer: 'manifold',
            readOnly: true,
            mutationAllowed: false,
            promotionAllowed: false,
            noTopologyWrites: true,
            graphTruthCommitIds: [],
        });
    });

    it('certifies GFM rankings without granting visible or truth authority', () => {
        const receipt = assertGraphConsumerReadOnly('gfm', 'snapshot:1', {
            results: [{ stableId: 'document:1', score: 0.9 }],
            noTopologyWrites: true,
            mutationAllowed: false,
            promotionAllowed: false,
            visibleRankingUnchanged: true,
        });

        expect(receipt.outputAuthority).toBe('projection_or_ranking_only');
        expect(receipt.inputAuthority).toBe('deterministic_graph_processing');
    });

    it('keeps authority work constant across corpus-sized projection arrays', () => {
        const small = assertGraphConsumerReadOnly('manifold', 'snapshot:1', {
            payload: { nodes: [{ id: 'node:0' }], edges: [{ id: 'edge:0' }] },
        });
        const large = assertGraphConsumerReadOnly('manifold', 'snapshot:1', {
            payload: {
                nodes: Array.from({ length: 100_000 }, (_, index) => ({ id: `node:${index}` })),
                edges: Array.from({ length: 100_000 }, (_, index) => ({ id: `edge:${index}` })),
            },
        });

        expect(large.checkedObjects).toBe(small.checkedObjects);
        expect(large.opaqueBulkRows).toBe(200_000);
    });

    it('rejects mutation, promotion, patch, commit, and truth-operation claims', () => {
        const unsafe = [
            { mutationAllowed: true },
            { promotionAllowed: true },
            { graphPatchCount: 1 },
            { graphTruthCommitIds: ['commit:1'] },
            { operation: 'assert' },
            { consumerAuthority: { readOnly: false } },
        ];

        for (const output of unsafe) {
            expect(() => assertGraphConsumerReadOnly('gfm', 'snapshot:1', output))
                .toThrow(/crossed the read-only authority boundary/i);
        }
    });

    it('fails snapshot sealing when a manifold receipt claims topology authority', () => {
        const snapshot = fixture();
        const summary = snapshot.manifoldSpecializationSummary!;
        summary.receipts[0].mutationAllowed = true as false;
        summary.counters.mutationAllowedCount = 1;

        expect(() => assertSnapshotGraphConsumersReadOnly(snapshot))
            .toThrow(/manifold.*read-only authority boundary/i);
    });
});

function fixture() {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:consumer-authority',
        noteIds: ['note-1'],
        entities: [entity('e-kai', 'Kai'), entity('e-rift', 'Rift')],
        chunks: [{
            id: 'note-1:block:0',
            noteId: 'note-1',
            start: 0,
            end: 64,
            ordinal: 0,
            source: 'note-block',
        }],
        occurrences: [occurrence('e-kai', 'Kai', 0, 3), occurrence('e-rift', 'Rift', 20, 24)],
        noteTexts: { 'note-1': 'Kai followed Rift through the harbor while the storm was rising.' },
        builtAt: 40,
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

function occurrence(entityId: string, surface: string, sourceStart: number, sourceEnd: number): EntityOccurrence {
    return {
        id: `note-1:${entityId}`,
        noteId: 'note-1',
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd,
        surface,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: surface,
        chunkId: 'note-1:block:0',
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}
