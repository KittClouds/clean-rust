import { describe, expect, it } from 'vitest';

import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { assertGraphSemanticDiscoveriesRemainCandidates } from './graph-semantic-discovery-authority';

describe('semantic discovery candidate authority', () => {
    it('certifies semantic sidecars without granting topology authority', () => {
        const snapshot = fixture();

        const receipt = assertGraphSemanticDiscoveriesRemainCandidates(snapshot);

        expect(receipt).toMatchObject({
            policy: 'candidate_only_explicit_promotion_required',
            candidateOnly: true,
            explicitPromotionRequired: true,
            assertedTopologyLeaks: 0,
            committedTopologyWrites: 0,
        });
        expect(snapshot.semanticAdjudicationSummary?.mutations).toEqual([]);
        expect(snapshot.semanticAdjudicationSummary?.decisions.every((row) => row.ledgerOnly)).toBe(true);
        expect(snapshot.semanticAdjudicationSummary?.receipts.every((row) => !row.mutationAllowed)).toBe(true);
    });

    it('fails closed when a semantic receipt claims mutation authority', () => {
        const snapshot = fixture();
        snapshot.semanticTaskSummary = {
            sourceSnapshotId: snapshot.id,
            tasks: [{ id: 'semantic-task:leak', mutationAllowed: true }],
            receipts: [],
            counters: { mutationAllowedCount: 1 },
        } as any;

        expect(() => assertGraphSemanticDiscoveriesRemainCandidates(snapshot))
            .toThrow(/candidate boundary.*semantic tasks mutation allowed/i);
    });

    it('rejects semantic edge-shaped rows in asserted topology', () => {
        const snapshot = fixture();
        snapshot.edges.push({
            id: 'ordinary-looking-id',
            sourceId: 'e-kai',
            targetId: 'e-rift',
            type: 'semantic::relation-link',
            weight: 1,
            confidence: 0.9,
            evidenceAnchorIds: [],
            scopeKeys: [],
            noteIds: ['note-1'],
        });

        expect(() => assertGraphSemanticDiscoveriesRemainCandidates(snapshot))
            .toThrow(/semantic edges in asserted topology 1/i);
    });

    it('rejects candidate identities reused as asserted edge identities', () => {
        const snapshot = fixture();
        const assertedEdgeId = snapshot.edges[0].id;
        snapshot.graphAwareLinkSuggestions = [{
            id: assertedEdgeId,
            sourceEntityId: 'e-kai',
            targetEntityId: 'e-rift',
        }] as any;

        expect(() => assertGraphSemanticDiscoveriesRemainCandidates(snapshot))
            .toThrow(/candidate identities in asserted topology 1/i);
    });
});

function fixture() {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:semantic-authority',
        noteIds: ['note-1'],
        entities: [entity('e-kai', 'Kai'), entity('e-rift', 'Rift')],
        chunks: [{
            id: 'note-1:block:0',
            noteId: 'note-1',
            start: 0,
            end: 72,
            ordinal: 0,
            source: 'note-block',
        }],
        occurrences: [
            occurrence('e-kai', 'Kai', 0, 3),
            occurrence('e-rift', 'Rift', 24, 28),
        ],
        noteTexts: { 'note-1': 'Kai crossed the threshold with Rift because the route was failing.' },
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
