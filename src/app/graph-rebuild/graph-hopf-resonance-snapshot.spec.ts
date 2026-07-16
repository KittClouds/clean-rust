import { describe, expect, it } from 'vitest';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { GraphRebuildChunk } from './graph-rebuild-snapshot';

describe('Hopf resonance space snapshot integration', () => {
    it('attaches the Hopf universe to every rebuild snapshot without dropping targets', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'multiNote',
            scopeId: 'multi:hopf',
            noteIds: ['chapter-a', 'chapter-b'],
            entities: [],
            occurrences: [],
            chunks: [
                chunk('chapter-a', 0, 'oath memory winter bridge'),
                chunk('chapter-a', 1, 'market copper debt ledger'),
                chunk('chapter-b', 0, 'oath echo moon bridge'),
                chunk('chapter-b', 1, 'storm shelter lantern mercy'),
            ],
            noteTexts: {
                'chapter-a': 'oath memory winter bridge\nmarket copper debt ledger',
                'chapter-b': 'oath echo moon bridge\nstorm shelter lantern mercy',
            },
            builtAt: 55,
        });
        const space = snapshot.hopfResonanceSpace;

        expect(space).toBeTruthy();
        expect(space?.assignments).toHaveLength(snapshot.embeddingTargets.length);
        expect(snapshot.counters.hopfResonanceAssignments).toBe(snapshot.embeddingTargets.length);
        expect(snapshot.counters.hopfResonanceDroppedTargets).toBe(0);
        expect(snapshot.counters.hopfResonanceMutationAllowed).toBe(0);
        expect(snapshot.counters.hopfResonanceDocCharts).toBe(2);
        expect(snapshot.counters.hopfResonanceOccupiedCells).toBeGreaterThan(1);
    });

    it('keeps every document chart wired to five roots and its own chunks', () => {
        const chunks = [
            chunk('doc-one', 0, 'first room hidden bell'),
            chunk('doc-one', 1, 'second room silver road'),
            chunk('doc-two', 0, 'third room mirror road'),
        ];
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'multiNote',
            scopeId: 'multi:doc-contract',
            noteIds: ['doc-one', 'doc-two'],
            entities: [],
            occurrences: [],
            chunks,
            noteTexts: {
                'doc-one': 'first room hidden bell\nsecond room silver road',
                'doc-two': 'third room mirror road',
            },
            builtAt: 56,
        });
        const charts = new Map(snapshot.hopfResonanceSpace?.docCharts.map((chart) => [chart.noteId, chart]));

        expect(charts.get('doc-one')?.rootTargetIds).toHaveLength(5);
        expect(charts.get('doc-two')?.rootTargetIds).toHaveLength(5);
        expect(charts.get('doc-one')?.chunkTargetIds).toHaveLength(2);
        expect(charts.get('doc-two')?.chunkTargetIds).toHaveLength(1);
    });
});

function chunk(noteId: string, ordinal: number, text: string): GraphRebuildChunk {
    const start = ordinal * 100;
    return {
        id: `${noteId}:chunk:${ordinal}`,
        noteId,
        start,
        end: start + text.length,
        ordinal,
        source: 'dynamic-chunking',
    };
}
