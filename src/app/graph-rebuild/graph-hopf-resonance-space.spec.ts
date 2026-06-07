import { describe, expect, it } from 'vitest';
import type { GraphRebuildEmbeddingTarget, GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import { buildHopfResonanceSpace, hopfResonanceSpaceSummary } from './graph-hopf-resonance-space';

describe('Hopf resonance space contract', () => {
    it('assigns every embedding target to an icosahedral base cell and fiber phase', () => {
        const targets = [
            target('embed:note:a', 'note', 'note-a', 'Chapter A', 'doc about mercy and memory'),
            target('embed:root:a:doc', 'structureRoot', 'note-a', 'Document structure', 'document spine root', {
                parentIds: ['embed:note:a'],
            }),
            target('embed:chunk:a:0', 'chunk', 'note-a', 'Chunk 1', 'oath mercy memory bell winter road', {
                chunkId: 'a:0',
                parentIds: ['embed:root:a:doc'],
            }),
            target('embed:entity:kai', 'entity', undefined, 'Kai', 'kind character oath memory', {
                entityId: 'kai',
                entityKind: 'CHARACTER',
                evidenceIds: ['anchor:kai:1', 'anchor:kai:2'],
            }),
        ];

        const space = buildHopfResonanceSpace(snapshot(targets), { generatedAt: 10, cellResolution: 2 });
        const cellIds = new Set(space.cells.map((cell) => cell.id));

        expect(space.schemaVersion).toBe('phoenix-hopf-resonance-space/v1');
        expect(space.assignments).toHaveLength(targets.length);
        expect(space.counters.droppedTargets).toBe(0);
        expect(space.counters.mutationAllowedCount).toBe(0);
        expect(space.assignments.every((row) => cellIds.has(row.baseCellId))).toBe(true);
        expect(space.assignments.every((row) => row.phase >= 0 && row.phase <= 1)).toBe(true);
        expect(space.fibers.length).toBeGreaterThan(0);
    });

    it('keeps document roots and chunks as a chart instead of collapsing the doc to one point', () => {
        const targets = [
            target('embed:note:wide', 'note', 'wide', 'Wide Note', 'doc spanning trade, storm, and sanctuary'),
            target('embed:root:wide:doc', 'structureRoot', 'wide', 'Document structure', 'document spine root', {
                parentIds: ['embed:note:wide'],
            }),
            target('embed:root:wide:identity', 'structureRoot', 'wide', 'Identity root', 'identity aliases and people root', {
                parentIds: ['embed:note:wide'],
            }),
            target('embed:chunk:wide:0', 'chunk', 'wide', 'Chunk 1', 'market trade copper ledgers caravan', {
                chunkId: 'wide:0',
            }),
            target('embed:chunk:wide:1', 'chunk', 'wide', 'Chunk 2', 'storm lightning weather roof shelter', {
                chunkId: 'wide:1',
            }),
            target('embed:chunk:wide:2', 'chunk', 'wide', 'Chunk 3', 'sanctuary mercy vow candle memory', {
                chunkId: 'wide:2',
            }),
        ];

        const space = buildHopfResonanceSpace(snapshot(targets, ['wide']), { generatedAt: 11, cellResolution: 3 });
        const chart = space.docCharts.find((row) => row.noteId === 'wide');

        expect(chart?.sourceTargetId).toBe('embed:note:wide');
        expect(chart?.rootTargetIds.sort()).toEqual(['embed:root:wide:doc', 'embed:root:wide:identity']);
        expect(chart?.chunkTargetIds.sort()).toEqual([
            'embed:chunk:wide:0',
            'embed:chunk:wide:1',
            'embed:chunk:wide:2',
        ]);
        expect(chart?.cellWeights.length).toBeGreaterThan(1);
        expect(chart?.coverageSpread).toBeGreaterThan(0);
    });

    it('does not let shared entity ids force unrelated passages into the same base cell', () => {
        const targets = [
            target('embed:chunk:left', 'chunk', 'a', 'Fire passage', [
                'volcano magma basalt ash furnace obsidian eruption heat',
                'volcano magma basalt ash furnace obsidian eruption heat',
            ].join(' '), { chunkId: 'left', entityId: 'kai' }),
            target('embed:chunk:right', 'chunk', 'b', 'Archive passage', [
                'library parchment archive theorem quiet lantern index moon',
                'library parchment archive theorem quiet lantern index moon',
            ].join(' '), { chunkId: 'right', entityId: 'kai' }),
        ];

        const space = buildHopfResonanceSpace(snapshot(targets, ['a', 'b']), { generatedAt: 12, cellResolution: 3 });
        const left = assignment(space, 'embed:chunk:left');
        const right = assignment(space, 'embed:chunk:right');

        expect(left.entityId).toBe(right.entityId);
        expect(left.baseCellId).not.toBe(right.baseCellId);
    });

    it('is stable for the same snapshot and options', () => {
        const targets = Array.from({ length: 18 }, (_, index) =>
            target(`embed:chunk:stable:${index}`, 'chunk', 'stable', `Chunk ${index}`, `theme ${index % 3} motif ${index} memory road`, {
                chunkId: `stable:${index}`,
            }),
        );
        const first = buildHopfResonanceSpace(snapshot(targets, ['stable']), { generatedAt: 13, cellResolution: 2 });
        const second = buildHopfResonanceSpace(snapshot(targets, ['stable']), { generatedAt: 13, cellResolution: 2 });

        expect(first.assignments.map((row) => [row.targetId, row.baseCellId, row.phase])).toEqual(
            second.assignments.map((row) => [row.targetId, row.baseCellId, row.phase]),
        );
        expect(hopfResonanceSpaceSummary(first)).toMatchObject({
            targets: targets.length,
            assignments: targets.length,
            dropped: 0,
        });
    });

    it('does not downsample full-scale target sets at the space-contract layer', () => {
        const targets = Array.from({ length: 1500 }, (_, index) =>
            target(`embed:chunk:bulk:${index}`, 'chunk', `note-${index % 9}`, `Chunk ${index}`, `bulk theme ${index % 41} lane ${index % 13}`, {
                chunkId: `bulk:${index}`,
            }),
        );

        const space = buildHopfResonanceSpace(snapshot(targets), { generatedAt: 14, cellResolution: 2 });

        expect(space.targetCount).toBe(1500);
        expect(space.assignments).toHaveLength(1500);
        expect(space.counters.droppedTargets).toBe(0);
        expect(space.counters.occupiedCellCount).toBeGreaterThan(1);
    });
});

function assignment(space: ReturnType<typeof buildHopfResonanceSpace>, id: string) {
    const found = space.assignments.find((row) => row.targetId === id);
    expect(found).toBeTruthy();
    return found!;
}

function target(
    id: string,
    kind: string,
    noteId: string | undefined,
    label: string,
    text: string,
    patch: Partial<GraphRebuildEmbeddingTarget> = {},
): GraphRebuildEmbeddingTarget {
    return {
        id,
        kind,
        sourceId: id,
        noteId,
        label,
        text,
        evidenceIds: [],
        ...patch,
    };
}

function snapshot(targets: GraphRebuildEmbeddingTarget[], noteIds = ['note-a']): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'graph-rebuild:test:hopf-space',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'multiNote',
        scopeId: 'test',
        noteIds,
        builtAt: 1,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: targets,
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
        counters: {
            entities: 0,
            aliases: 0,
            candidates: 0,
            mentions: 0,
            acceptedAnchors: 0,
            chunks: 0,
            relationshipCandidates: 0,
            relationships: 0,
            acceptedRelationships: 0,
            reviewRelationships: 0,
            rejectedRelationships: 0,
            events: 0,
            episodes: 0,
            temporalEdges: 0,
            causalEdges: 0,
            memoryState: 0,
            embeddingTargets: targets.length,
            embeddingVectors: 0,
            projectionRefs: 0,
            nodes: 0,
            edges: 0,
        },
    };
}
