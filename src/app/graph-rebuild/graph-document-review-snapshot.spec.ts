import { describe, expect, it } from 'vitest';

import { buildGraphDocumentReviewSummary } from './graph-document-review';
import { applyGraphDocumentReviewDecisionToSnapshot } from './graph-document-review-snapshot';
import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('graph document review snapshot actions', () => {
    it('applies a batch decision with reversible receipts and refreshes the compiler read model', () => {
        const text = 'Amara entered the Archive because the signal changed.';
        const sidecar = buildGraphDocumentSidecar({
            noteIds: ['note:1'],
            noteTexts: { 'note:1': text },
            chunks: [{ id: 'chunk:1', noteId: 'note:1', start: 0, end: text.length, ordinal: 0, source: 'dynamic-chunking' }],
            builtAt: 10,
        });
        const review = buildGraphDocumentReviewSummary(sidecar, 10);
        const fact = sidecar.graphFactCandidates[0];
        const next = applyGraphDocumentReviewDecisionToSnapshot(baseSnapshot(sidecar, review), [fact.id], 'accepted', 20);

        expect(next?.documentReviewSummary?.rows.find((row) => row.objectId === fact.id)?.state).toBe('accepted');
        expect(next?.documentReviewSummary?.receipts.at(-1)).toMatchObject({
            targetObjectId: fact.id,
            previousState: 'proposed',
            nextState: 'accepted',
            reversible: true,
            mutationAllowed: false,
        });
        expect(next?.documentCompilerSummary?.builtAt).toBe(20);
    });
});

function baseSnapshot(sidecar: ReturnType<typeof buildGraphDocumentSidecar>, review: ReturnType<typeof buildGraphDocumentReviewSummary>): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1', source: 'phoenix-graph-rebuild', scopeKind: 'note',
        scopeId: 'review-snapshot-note', noteIds: sidecar.noteIds, id: 'snapshot:1', builtAt: 10,
        chunks: [], mentions: [], entityAnchors: [], embeddingTargets: [], embeddingVectors: [],
        projectionRefs: [], nodes: [], edges: [], relationships: [], events: [], episodes: [], temporalEdges: [],
        causalEdges: [], memoryState: [], documentSidecarSummary: sidecar, documentReviewSummary: review, counters: {},
    } as unknown as GraphRebuildSnapshot;
}
