import { describe, expect, it } from 'vitest';
import {
    applyCanvasTextEdits,
    parseCanvasMultiNoteTransaction,
    type CanvasMultiNoteTransaction,
} from './canvas-multi-note-transaction';

describe('Canvas multi-note transaction contract', () => {
    it('applies non-overlapping file edits against one immutable base', () => {
        expect(applyCanvasTextEdits('alpha beta gamma', [
            { from: 0, to: 5, replacement: 'ALPHA', expectedText: 'alpha' },
            { from: 11, to: 16, replacement: 'GAMMA', expectedText: 'gamma' },
        ])).toBe('ALPHA beta GAMMA');
    });

    it('rejects overlapping, out-of-bounds, and stale edits before staging', () => {
        expect(() => applyCanvasTextEdits('abcdef', [
            { from: 1, to: 4, replacement: 'x' },
            { from: 3, to: 5, replacement: 'y' },
        ])).toThrow(/overlap/i);
        expect(() => applyCanvasTextEdits('abc', [
            { from: 0, to: 9, replacement: 'x' },
        ])).toThrow(/range/i);
        expect(() => applyCanvasTextEdits('abc', [
            { from: 0, to: 1, replacement: 'x', expectedText: 'z' },
        ])).toThrow(/expected text/i);
    });

    it('parses only complete versioned transactions', () => {
        expect(parseCanvasMultiNoteTransaction(transaction())).toEqual(transaction());
        expect(parseCanvasMultiNoteTransaction({ ...transaction(), mutations: [] })).toBeNull();
        expect(parseCanvasMultiNoteTransaction({ ...transaction(), narrativeId: '' })).toBeNull();
    });
});

function transaction(): CanvasMultiNoteTransaction {
    return {
        kind: 'canvas_multi_note_transaction_v1',
        transactionId: 'multi-1',
        runId: 'run-1',
        narrativeId: 'story-1',
        mutations: [{
            noteId: 'note-1',
            noteUri: 'note://story-1/note-1',
            operationKinds: ['patch'],
            expectedRevision: 11,
            before: note('before', 11),
            after: note('after', 11),
        }],
        diffPreview: '--- before\n+++ after',
        stagedAt: 1,
        stageMs: 2,
    };
}

function note(markdown: string, revision: number) {
    return {
        id: 'note-1',
        worldId: '',
        title: 'One',
        content: { type: 'doc' },
        markdownContent: markdown,
        folderId: 'folder-1',
        entityKind: '',
        entitySubtype: '',
        isEntity: false,
        isPinned: false,
        favorite: false,
        ownerId: '',
        narrativeId: 'story-1',
        order: 0,
        createdAt: 1,
        updatedAt: revision,
        version: revision,
    };
}
