import { describe, expect, it } from 'vitest';
import {
    attachGraphReceiptSpans,
    buildGraphReplayManifest,
    GRAPH_FORCE_V1_PATH_ID,
} from './graph-rebuild-replay-contract';
import type { GraphIndexStageReceipt } from './graph-rebuild-snapshot';

describe('graph rebuild replay contract', () => {
    it('freezes exact source measurements and hashes without conflating editor counters', async () => {
        const manifest = await buildGraphReplayManifest({
            scope: { kind: 'note', scopeId: 'note:1', label: 'One', noteIds: ['note-1'] },
            action: 'force',
            documents: [{ noteId: 'note-1', title: 'One', text: 'Kai\r\nmet Zoë. 🚀', version: 7 }],
            model: {
                dynamicNerId: 'dynamic_ner', embeddingModelId: 'embed', embeddingModelLabel: 'Embed',
                embeddingDimensionLabel: '768d', nliModelId: 'nli',
            },
            dependencyIdentity: 'sha256:dependencies',
            runtime: { buildGitSha: 'abc', binaryBlake3: 'b3-binary' },
            cache: {
                documentBodyEntries: 1, capabilityEntries: 2,
                residentInteractiveRun: false, nativeRuntimeReady: true,
            },
            queues: {
                receiptPersistencePending: 0, postCommitDiagnosticScheduled: false,
                postCommitDiagnosticToken: 3, generationArtifactPending: 0,
            },
            pathId: GRAPH_FORCE_V1_PATH_ID,
            fallbackCount: 0,
        });

        expect(manifest.documents[0]).toMatchObject({
            noteId: 'note-1', jsCodeUnitChars: 16, unicodeScalarChars: 15,
            nonLineBreakChars: 14, lineBreaks: 1, words: 3,
        });
        expect(manifest.documents[0].sha256).toHaveLength(64);
        expect(manifest.cohortId).toMatch(/^sha256:[a-f0-9]{64}$/);
    });

    it('assigns stable parent and child spans to overlapping timing telemetry', () => {
        const stages = [stage('nliAdjudication'), stage('nliCandidatePlan'), stage('snapshotCpu')];
        const root = attachGraphReceiptSpans('receipt-1', stages);
        expect(root).toEqual({ spanId: 'receipt-1:span:root', parentSpanId: null });
        expect(stages[1].parentSpanId).toBe(stages[0].spanId);
        expect(stages[2].parentSpanId).toBe('receipt-1:span:root');
    });
});

function stage(id: string): GraphIndexStageReceipt {
    return {
        id, label: id, status: 'completed', startedAt: 1, completedAt: 2,
        durationMs: 1, outputCount: 0, counters: {}, message: id,
    };
}
