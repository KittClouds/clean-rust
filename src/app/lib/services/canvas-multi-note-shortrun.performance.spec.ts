import { describe, expect, it } from 'vitest';
import {
    applyCanvasTextEdits,
    formatCanvasMultiNoteDiff,
    type CanvasStagedNoteMutation,
} from './canvas-multi-note-transaction';

describe('Canvas multi-note Shortrun performance', () => {
    it('stages two bounded note patches and their real diff inside the interaction budget', () => {
        const startedAt = performance.now();
        const mutations = [
            mutation('shortrun-a', 'Shortrun A', 'The city waited. The road stayed empty.'),
            mutation('shortrun-b', 'Shortrun B', 'Their cars crossed New Rome before sunrise.'),
        ];
        const diff = formatCanvasMultiNoteDiff(mutations);
        const stageMs = performance.now() - startedAt;
        const diffBytes = new TextEncoder().encode(diff).byteLength;

        console.info(`[Canvas Multi Shortrun] notes=2 edits=4 stageMs=${stageMs.toFixed(3)} diffBytes=${diffBytes}`);
        expect(diff).toContain('note://story-1/shortrun-b');
        expect(diffBytes).toBeLessThan(16_384);
        expect(stageMs).toBeLessThan(100);
    });
});

function mutation(noteId: string, title: string, markdown: string): CanvasStagedNoteMutation {
    const midpoint = Math.floor(markdown.length / 2);
    const after = applyCanvasTextEdits(markdown, [
        { from: 0, to: 3, replacement: markdown.slice(0, 3).toUpperCase(), expectedText: markdown.slice(0, 3) },
        { from: midpoint, to: midpoint, replacement: ' carefully' },
    ]);
    const note = (body: string) => ({
        id: noteId, worldId: '', title, content: { type: 'doc' }, markdownContent: body,
        folderId: 'chapters', entityKind: '', entitySubtype: '', isEntity: false, isPinned: false,
        favorite: false, ownerId: '', narrativeId: 'story-1', order: 0, createdAt: 1, updatedAt: 10, version: 10,
    });
    return {
        noteId,
        noteUri: `note://story-1/${noteId}`,
        operationKinds: ['patch'],
        expectedRevision: 10,
        before: note(markdown),
        after: note(after),
    };
}
