import { describe, expect, it } from 'vitest';
import {
    CANVAS_NOTE_TRANSACTION_KIND,
    contentMatchesTransaction,
    createCanvasNoteUri,
    formatCanvasReplacementDiff,
    parseCanvasStagedTransaction,
    type CanvasStagedNoteTransaction,
} from './canvas-note-transaction';

describe('Canvas note transaction contract', () => {
    it('gives a note a stable file-like URI', () => {
        expect(createCanvasNoteUri('story one', 'note/7')).toBe('note://story%20one/note%2F7');
        expect(createCanvasNoteUri('', 'note-7')).toBe('note://__global__/note-7');
    });

    it('renders an exact selected-range diff', () => {
        expect(formatCanvasReplacementDiff({
            noteUri: 'note://story/note-7',
            baseRevision: 41,
            from: 8,
            to: 19,
            beforeText: 'their cars\nlike monkeys',
            replacement: 'their vehicles\nlike maniacs',
        })).toBe([
            '--- note://story/note-7@41',
            '+++ note://story/note-7@staged',
            '@@ selection 8:19 @@',
            '-their cars',
            '-like monkeys',
            '+their vehicles',
            '+like maniacs',
        ].join('\n'));
    });

    it('rejects malformed persisted transactions and recognizes an idempotent commit', () => {
        const transaction = stagedTransaction();
        expect(parseCanvasStagedTransaction(transaction)).toEqual(transaction);
        expect(parseCanvasStagedTransaction({ ...transaction, noteId: '' })).toBeNull();
        expect(contentMatchesTransaction(
            JSON.stringify(transaction.stagedContent),
            transaction.stagedMarkdown,
            transaction,
        )).toBe(true);
        expect(contentMatchesTransaction('{}', transaction.stagedMarkdown, transaction)).toBe(false);
    });
});

function stagedTransaction(): CanvasStagedNoteTransaction {
    return {
        kind: CANVAS_NOTE_TRANSACTION_KIND,
        transactionId: 'txn-1',
        runId: 'run-1',
        noteUri: 'note://story/note-7',
        noteId: 'note-7',
        noteTitle: 'Shortrun B',
        baseStoreRevision: 41,
        baseEditorRevision: 11,
        stagedEditorRevision: 12,
        from: 8,
        to: 19,
        beforeText: 'their cars',
        replacement: 'their vehicles',
        baseContent: { type: 'doc', content: [] },
        baseMarkdown: 'their cars',
        stagedContent: { type: 'doc', content: [{ type: 'paragraph' }] },
        stagedMarkdown: 'their vehicles',
        diffPreview: 'diff',
        stagedAt: 100,
        stageMs: 2,
    };
}
