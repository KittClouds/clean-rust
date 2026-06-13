import { describe, expect, it } from 'vitest';

import {
    applyGraphOperatorMutationDecisionToSnapshot,
    replayGraphOperatorMutationJournal,
} from './graph-operator-mutation-journal';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('graph operator mutation journal', () => {
    it('replays operator review decisions onto a rebuilt snapshot', () => {
        const base = snapshotFixture(10);
        const factId = firstFactObjectId(base);
        const mutated = applyGraphOperatorMutationDecisionToSnapshot(base, [factId], 'accepted', 20);
        expect(mutated?.operatorMutationJournal?.counters).toMatchObject({
            intents: 1,
            applied: 1,
            receipts: 1,
        });
        expect(rowState(mutated!, factId)).toBe('accepted');

        const rebuilt = snapshotFixture(30, mutated!.operatorMutationJournal);
        expect(rowState(rebuilt, factId)).toBe('accepted');
        expect(rebuilt.documentReviewSummary?.receipts).toHaveLength(1);
        expect(rebuilt.operatorMutationJournal?.intents[0]).toMatchObject({
            targetObjectId: factId,
            requestedState: 'accepted',
            status: 'applied',
        });
    });

    it('marks stale operator decisions conflicted when the source row no longer matches', () => {
        const base = snapshotFixture(40);
        const factId = firstFactObjectId(base);
        const mutated = applyGraphOperatorMutationDecisionToSnapshot(base, [factId], 'accepted', 41);
        const stale = {
            ...snapshotFixture(42),
            documentReviewSummary: {
                ...snapshotFixture(42).documentReviewSummary!,
                rows: snapshotFixture(42).documentReviewSummary!.rows.map((row) =>
                    row.objectId === factId ? { ...row, detector: 'changed_detector' } : row,
                ),
            },
        };
        const replayed = replayGraphOperatorMutationJournal(stale, mutated!.operatorMutationJournal!, 43).snapshot;

        expect(rowState(replayed, factId)).toBe('proposed');
        expect(replayed.operatorMutationJournal?.counters).toMatchObject({
            intents: 1,
            conflicted: 1,
            receipts: 1,
        });
        expect(replayed.operatorMutationJournal?.intents[0].conflictReason).toBe('source_fingerprint_changed');
    });
});

function snapshotFixture(
    builtAt: number,
    operatorMutationJournal?: GraphRebuildSnapshot['operatorMutationJournal'],
): GraphRebuildSnapshot {
    const text = [
        '# Operator Journal Note',
        'Policy means Amara moved from Red Mesa to Halcyon because Captain Ilya changed the archive route.',
        'Therefore Morgan shows the evidence to Kai and Hazel before the council decision.',
    ].join('\n\n');
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'operator-journal-note',
        noteIds: ['operator-journal-note'],
        entities: [],
        occurrences: [],
        chunks: buildAdaptiveGraphRebuildChunks('operator-journal-note', text),
        noteTexts: { 'operator-journal-note': text },
        builtAt,
        postProcessMode: 'core',
        embeddingStagePolicy: { entityLinkerEnabled: false },
        operatorMutationJournal,
    });
}

function firstFactObjectId(snapshot: GraphRebuildSnapshot): string {
    const row = snapshot.documentReviewSummary?.rows.find((candidate) => candidate.objectKind === 'graph_fact_candidate');
    expect(row).toBeTruthy();
    return row!.objectId;
}

function rowState(snapshot: GraphRebuildSnapshot, objectId: string): string | undefined {
    return snapshot.documentReviewSummary?.rows.find((row) => row.objectId === objectId)?.state;
}
