import { describe, expect, it } from 'vitest';

import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import {
    buildGraphEvidenceTargetRegistry,
    sealGraphEvidenceTargetRegistry,
} from './graph-evidence-target-registry';

describe('graph evidence target registry', () => {
    it('exposes exact chunks and only evidence-linked typed graph objects', () => {
        const snapshot = fixture();
        const registry = buildGraphEvidenceTargetRegistry(snapshot);
        const evidenceIds = new Set([
            ...snapshot.entityAnchors.map((row) => row.id),
            ...(snapshot.documentSidecarSummary?.evidenceSpans || []).map((row) => row.id),
        ]);

        expect(registry.contract).toEqual(snapshot.evidenceTargetRegistry);
        expect(registry.chunks.map((target) => target.sourceId)).toEqual(snapshot.chunks.map((row) => row.id));
        expect(registry.typedGraphObjects.length).toBeGreaterThan(0);
        expect(registry.contract.duplicateTargets).toBe(0);
        expect(registry.contract.orphanTargets).toBe(0);
        expect(registry.typedGraphObjects.every((target) => (
            target.evidenceIds.length > 0 && target.evidenceIds.every((id) => evidenceIds.has(id))
        ))).toBe(true);
        expect(registry.typedGraphObjects.every((target) => registry.objectKind(target.id) !== undefined)).toBe(true);
    });

    it('keeps compiler candidates in support inventory rather than exposing them as asserted truth', () => {
        const snapshot = fixture();
        snapshot.embeddingTargets.push({
            id: 'target:candidate:uncommitted',
            kind: 'graphFact',
            sourceId: 'fact:document-hyperedge:candidate',
            sourceScopeId: snapshot.scopeId,
            label: 'Uncommitted compiler candidate',
            text: 'candidate only',
            evidenceIds: [],
            entityIds: [],
            chunkId: null,
            importance: 0.1,
            metadata: { commitPolicy: 'pending_commit' },
        });

        const registry = buildGraphEvidenceTargetRegistry(snapshot);

        expect(registry.get('target:candidate:uncommitted')).toBeTruthy();
        expect(registry.exposedTargets.some((target) => target.id === 'target:candidate:uncommitted')).toBe(false);
        expect(registry.contract.supportTargets).toBe(
            registry.contract.canonicalTargets - registry.contract.exposedTargets,
        );
    });

    it('fails closed when canonical target identities collide', () => {
        const snapshot = fixture();
        snapshot.embeddingTargets.push({ ...snapshot.embeddingTargets[0] });

        expect(() => sealGraphEvidenceTargetRegistry(snapshot)).toThrow(/duplicate targets 1/);
    });
});

function fixture() {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:registry',
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
        builtAt: 10,
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
