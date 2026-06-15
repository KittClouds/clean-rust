import { describe, expect, it } from 'vitest';

import { buildGraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-builder';
import { buildAdaptiveGraphRebuildChunks } from '../../../../graph-rebuild/graph-rebuild-meaning-frames';
import { buildGraphEvaluationDashboard } from './graph-evaluation-dashboard';

describe('buildGraphEvaluationDashboard', () => {
    it('scores the complete Phase 7 metric set from a persisted snapshot', () => {
        const text = [
            '# Evaluation Note',
            'Amara moved from Red Mesa to Halcyon because the report changed the plan.',
            'The recovered record is evidence for the decision.',
            '- Review the route.',
            '- Preserve the source span.',
        ].join('\n\n');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:evaluation',
            noteIds: ['evaluation'],
            entities: [],
            occurrences: [],
            chunks: buildAdaptiveGraphRebuildChunks('evaluation', text),
            noteTexts: { evaluation: text },
            builtAt: 100,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });
        snapshot.buildTimings = timings();

        const dashboard = buildGraphEvaluationDashboard(snapshot, null);

        expect(dashboard.verdict).not.toBe('No data');
        expect(dashboard.metrics.map((metric) => metric.id)).toEqual([
            'chunk-size',
            'overlap-rate',
            'hierarchy-depth',
            'orphan-chunks',
            'section-coverage',
            'document-adaptation',
            'evidence-density',
            'entity-prior-noise',
            'proposition-substrate',
            'predicate-precision',
            'temporal-continuity',
            'review-ratio',
            'graph-mutations',
            'retrieval-quality',
            'bridge-quality',
            'indexing-time',
            'index-memory',
        ]);
        expect(dashboard.categories).toHaveLength(6);
        expect(dashboard.metricsById['chunk-size'].distribution).toHaveLength(5);
        expect(dashboard.metricsById['indexing-time'].value).toBe('2.0 s');
        expect(dashboard.metricsById['document-adaptation'].value).toContain('Reference Article');
        expect(dashboard.metricsById['document-adaptation'].records[0]?.id).toBe('profile:evaluation');
        expect(dashboard.stageRows.some((row) => row.id === 'snapshotBuildMs')).toBe(true);
    });

    it('labels snapshot footprint separately from unavailable peak memory telemetry', () => {
        const text = 'A short document still produces an honest memory read.';
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:memory',
            noteIds: ['memory'],
            entities: [],
            occurrences: [],
            chunks: buildAdaptiveGraphRebuildChunks('memory', text),
            noteTexts: { memory: text },
            builtAt: 200,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });
        snapshot.buildTimings = timings();

        const memory = buildGraphEvaluationDashboard(snapshot, null).metricsById['index-memory'];

        expect(memory.score).toBeNull();
        expect(memory.value).toContain('snapshot');
        expect(memory.summary).toContain('Peak process memory is not instrumented');
    });

    it('returns an explicit empty state without manufacturing health', () => {
        const dashboard = buildGraphEvaluationDashboard(null, null);

        expect(dashboard).toMatchObject({ verdict: 'No data', score: null, metrics: [] });
        expect(dashboard.categories.every((category) => category.score === null)).toBe(true);
    });
});

function timings() {
    return {
        occurrenceLoadMs: 30,
        chunkLoadMs: 40,
        noteTextLoadMs: 20,
        noteFolderLoadMs: 10,
        dbLoadMs: 100,
        occurrenceRecoverMs: 5,
        snapshotBuildMs: 1200,
        stateCommitMs: 35,
        snapshotPersistMs: 400,
        snapshotSerializeMs: 100,
        snapshotStoreMs: 200,
        snapshotEventMs: 10,
        snapshotPayloadChars: 100_000,
        snapshotPrimaryCompressedBytes: 30_000,
        snapshotOverGraphCompressedBytes: 10_000,
        dbOpsMs: 200,
        totalMs: 2000,
    };
}
