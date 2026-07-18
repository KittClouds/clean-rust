import { describe, expect, it } from 'vitest';

import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import {
    assertGraphEncoderVectorIndex,
    buildGraphEncoderVectorIndex,
    installGraphEncoderVectorIndex,
    type GraphEncoderVectorPage,
} from './graph-encoder-vector-index';
import { assertGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';

describe('real encoder vector index', () => {
    it('indexes evidence-registry identities and emits bounded candidate neighborhoods', () => {
        const snapshot = fixture();
        const registry = assertGraphEvidenceTargetRegistry(snapshot);
        const page = vectorPage(registry.exposedTargets.map((target) => target.id), 6);

        const index = buildGraphEncoderVectorIndex(snapshot, page, {
            neighborhoodK: 2,
            maxCandidatesPerTarget: 3,
            minimumSimilarity: 0.1,
        });
        installGraphEncoderVectorIndex(snapshot, index);

        expect(index.contract.authority).toBe('real_encoder');
        expect(index.contract.candidateOnly).toBe(true);
        expect(index.contract.committedTopologyWrites).toBe(0);
        expect(index.contract.vectorCount).toBe(registry.contract.exposedTargets);
        expect(index.contract.evaluatedPairs).toBeLessThanOrEqual(index.contract.vectorCount * 3);
        expect(index.neighborhoods.every((row) => row.neighbors.length <= 2)).toBe(true);
        expect(snapshot.counters.embeddingVectors).toBe(index.contract.vectorCount);
        expect(() => assertGraphEncoderVectorIndex(snapshot)).not.toThrow();
    });

    it('fails closed on non-registry identities, collisions, and fake execution providers', () => {
        const snapshot = fixture();
        const targetIds = assertGraphEvidenceTargetRegistry(snapshot).exposedTargets.map((target) => target.id);
        const unknown = vectorPage([...targetIds.slice(1), 'target:not-in-registry'], 4);
        const duplicate = vectorPage(targetIds.map((id, index) => index === 1 ? targetIds[0] : id), 4);
        const fake = { ...vectorPage(targetIds, 4), executionProvider: 'signature-preview' } as GraphEncoderVectorPage;

        expect(() => buildGraphEncoderVectorIndex(snapshot, unknown)).toThrow(/outside the evidence registry/);
        expect(() => buildGraphEncoderVectorIndex(snapshot, duplicate)).toThrow(/identity collides/);
        expect(() => buildGraphEncoderVectorIndex(snapshot, fake)).toThrow(/execution provider is not real/);
    });

    it('rejects malformed dense pages before candidate construction', () => {
        const snapshot = fixture();
        const targetIds = assertGraphEvidenceTargetRegistry(snapshot).exposedTargets.map((target) => target.id);
        const page = vectorPage(targetIds, 4);
        page.values[0] = Number.NaN;

        expect(() => buildGraphEncoderVectorIndex(snapshot, page)).toThrow(/not finite/);
    });

    it('caps similarity work per target even when every vector shares an LSH bucket', () => {
        const snapshot = chunkFixture(240);
        const targetIds = assertGraphEvidenceTargetRegistry(snapshot).exposedTargets.map((target) => target.id);
        const index = buildGraphEncoderVectorIndex(snapshot, vectorPage(targetIds, 8), {
            neighborhoodK: 4,
            maxCandidatesPerTarget: 12,
            minimumSimilarity: -1,
        });

        expect(index.contract.vectorCount).toBe(240);
        expect(index.contract.evaluatedPairs).toBeLessThanOrEqual(240 * 12);
        expect(index.contract.evaluatedPairs).toBeLessThan((240 * 239) / 2);
    });

    it('answers arbitrary encoder queries without scanning the vector corpus', () => {
        const snapshot = chunkFixture(240);
        const targetIds = assertGraphEvidenceTargetRegistry(snapshot).exposedTargets.map((target) => target.id);
        const index = buildGraphEncoderVectorIndex(snapshot, vectorPage(targetIds, 8), {
            neighborhoodK: 4,
            maxCandidatesPerTarget: 12,
            minimumSimilarity: -1,
        });

        const result = index.query(new Float32Array([1, 0.05, 0.025, 0, 0, 0, 0, 0]), {
            limit: 5,
            maxCandidates: 9,
            minimumSimilarity: -1,
        });

        expect(result.neighbors).toHaveLength(5);
        expect(result.evaluatedCandidates).toBeLessThanOrEqual(9);
        expect(result.evaluatedCandidates).toBeLessThan(targetIds.length);
    });
});

function vectorPage(targetIds: string[], dimensions: number): GraphEncoderVectorPage {
    const values = new Float32Array(targetIds.length * dimensions);
    for (let row = 0; row < targetIds.length; row += 1) {
        const offset = row * dimensions;
        values[offset] = 1;
        values[offset + 1] = (row % 3) * 0.05;
        values[offset + 2] = ((row + 1) % 3) * 0.025;
    }
    return {
        modelId: 'test-real-encoder',
        modelVersion: 'fixture-v1',
        executionProvider: 'external-encoder',
        dimensions,
        generation: 10,
        targetIds,
        values,
        normalized: false,
    };
}

function fixture() {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:encoder-index',
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

function chunkFixture(count: number) {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:encoder-scale',
        noteIds: ['note-scale'],
        entities: [],
        occurrences: [],
        chunks: Array.from({ length: count }, (_, ordinal) => ({
            id: `note-scale:block:${ordinal}`,
            noteId: 'note-scale',
            start: ordinal * 12,
            end: ordinal * 12 + 10,
            ordinal,
            source: 'note-block' as const,
        })),
        builtAt: 11,
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
