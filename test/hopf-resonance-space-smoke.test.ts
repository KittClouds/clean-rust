import { existsSync, readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { EntityOccurrence } from '../src/app/lib/dexie/db';
import type { RegisteredEntity } from '../src/app/lib/registry';
import { buildGraphRebuildSnapshot } from '../src/app/graph-rebuild/graph-rebuild-builder';
import { dynamicChunksForNote } from '../src/app/graph-rebuild/graph-rebuild.service';
import { hopfResonanceSpaceSummary } from '../src/app/graph-rebuild/graph-hopf-resonance-space';

describe('Hopf resonance space doc smoke', () => {
    it('builds a full-space contract from a document', () => {
        const documents = loadSmokeDocuments();
        const surfaces = candidateSurfaces(documents.map((doc) => doc.text).join('\n')).slice(0, 28);
        const entities = surfaces.map((surface, index) => registeredEntity(`smoke-${index}:${safeId(surface)}`, surface));
        const occurrences = entities.flatMap((entity) =>
            documents.flatMap((doc) =>
                surfaceOccurrences(doc.text, doc.noteId, entity.id, entity.label, 'CHARACTER', 18),
            ),
        );
        const started = performance.now();
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: documents.length > 1 ? 'multiNote' : 'note',
            scopeId: documents.length > 1
                ? `multi:${documents.map((doc) => doc.noteId).join('+')}`
                : `note:${documents[0].noteId}`,
            noteIds: documents.map((doc) => doc.noteId),
            entities,
            chunks: documents.flatMap((doc) => doc.chunks),
            occurrences,
            candidateCount: occurrences.length,
            noteTexts: Object.fromEntries(documents.map((doc) => [doc.noteId, doc.text])),
            builtAt: 44,
        });
        const elapsedMs = Math.max(1, Math.round(performance.now() - started));
        const space = snapshot.hopfResonanceSpace;
        expect(space).toBeTruthy();
        const charts = new Map(space!.docCharts.map((chart) => [chart.noteId, chart]));
        const summary = {
            docs: documents.map((doc) => ({
                path: doc.path,
                noteId: doc.noteId,
                chars: doc.text.length,
                chunks: doc.chunks.length,
            })),
            elapsedMs,
            targetsPerSec: Math.round((space!.assignments.length / elapsedMs) * 1000),
            chars: documents.reduce((sum, doc) => sum + doc.text.length, 0),
            chunks: documents.reduce((sum, doc) => sum + doc.chunks.length, 0),
            entities: entities.length,
            occurrences: occurrences.length,
            ...hopfResonanceSpaceSummary(space!),
            docCharts: documents.map((doc) => {
                const chart = charts.get(doc.noteId);
                return {
                    noteId: doc.noteId,
                    cells: chart?.cellWeights.length || 0,
                    entropy: chart?.coverageEntropy || 0,
                    roots: chart?.rootTargetIds.length || 0,
                    chunks: chart?.chunkTargetIds.length || 0,
                    dominant: chart?.dominantCellIds || [],
                };
            }),
        };

        console.info('hopf-resonance-space-smoke', JSON.stringify(summary));
        expect(space!.assignments).toHaveLength(snapshot.embeddingTargets.length);
        expect(snapshot.counters.hopfResonanceAssignments).toBe(snapshot.embeddingTargets.length);
        expect(space!.counters.droppedTargets).toBe(0);
        expect(space!.counters.mutationAllowedCount).toBe(0);
        expect(space!.docCharts).toHaveLength(documents.length);
        for (const doc of documents) {
            const chart = charts.get(doc.noteId);
            expect(chart?.chunkTargetIds.length).toBe(doc.chunks.length);
            expect(chart?.rootTargetIds.length).toBeGreaterThanOrEqual(5);
        }
        expect(space!.counters.occupiedCellCount).toBeGreaterThan(1);
    });
});

function loadSmokeDocuments() {
    const docs = smokeDocPaths();
    return docs.map((docPath, index) => {
        const path = resolve(docPath);
        expect(existsSync(path), `missing doc: ${path}`).toBe(true);
        const text = readFileSync(path, 'utf8');
        const base = safeId(basename(path).replace(/\.[^.]+$/, '')) || `hopf-smoke-${index + 1}`;
        const noteId = docs.length > 1 ? `${base}-${index + 1}` : base;
        return {
            path,
            noteId,
            text,
            chunks: dynamicChunksForNote({ id: noteId, markdownContent: text, content: '' }),
        };
    });
}

function smokeDocPaths(): string[] {
    if (process.env.HOPF_SPACE_DOCS) {
        const parsed = JSON.parse(process.env.HOPF_SPACE_DOCS);
        if (Array.isArray(parsed) && parsed.length) return parsed.map(String);
    }
    return [process.env.HOPF_SPACE_DOC || 'docs/shortrun.md'];
}

function candidateSurfaces(text: string): string[] {
    const counts = new Map<string, number>();
    const pattern = /\b[A-Z][a-zA-Z'-]{2,}(?:\s+[A-Z][a-zA-Z'-]{2,}){0,2}\b/g;
    for (const match of text.matchAll(pattern)) {
        const surface = match[0].trim();
        if (STOP_SURFACES.has(surface.toLowerCase())) continue;
        counts.set(surface, (counts.get(surface) || 0) + 1);
    }
    return [...counts.entries()]
        .filter(([, count]) => count >= 2)
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .map(([surface]) => surface);
}

function surfaceOccurrences(
    text: string,
    noteId: string,
    entityId: string,
    label: string,
    entityKind: string,
    limit: number,
): EntityOccurrence[] {
    const pattern = new RegExp(`\\b${escapeRegex(label)}\\b`, 'gi');
    const occurrences: EntityOccurrence[] = [];
    for (const match of text.matchAll(pattern)) {
        if (occurrences.length >= limit) break;
        const start = match.index || 0;
        occurrences.push({
            id: `${noteId}:${entityId}:${start}`,
            noteId,
            entityId,
            entityLabel: label,
            entityKind,
            sourceStart: start,
            sourceEnd: start + label.length,
            surface: match[0],
            source: 'dictionary_match',
            confidence: 0.92,
            excerpt: text.slice(Math.max(0, start - 80), Math.min(text.length, start + label.length + 80)),
            generation: 1,
            createdAt: 44,
            updatedAt: 44,
        });
    }
    return occurrences;
}

function registeredEntity(id: string, label: string): RegisteredEntity {
    return {
        id,
        label,
        kind: 'CHARACTER' as RegisteredEntity['kind'],
        aliases: [],
        firstNote: 'hopf-smoke',
        mentionsByNote: new Map(),
        totalMentions: 0,
        lastSeenDate: new Date(44),
        createdAt: new Date(44),
        createdBy: 'smoke',
        registeredAt: 44,
    };
}

function safeId(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const STOP_SURFACES = new Set([
    'chapter',
    'common era',
    'new world calendar',
    'the',
    'this',
    'that',
    'still',
]);
