import { beforeEach, describe, expect, it, vi } from 'vitest';

const settings = vi.hoisted(() => new Map<string, unknown>());
vi.mock('../dexie/settings.service', () => ({
    getSetting: (key: string, fallback: unknown) => settings.has(key) ? settings.get(key) : fallback,
    setSetting: (key: string, value: unknown) => settings.set(key, value),
}));

import { CanvasTrustedGrantService } from './canvas-trusted-grant.service';
import type { CanvasMultiNoteTransaction } from './canvas-multi-note-transaction';

describe('CanvasTrustedGrantService', () => {
    beforeEach(() => settings.clear());

    it('authorizes only the issued run, narrative, notes, folders, and operations', () => {
        const service = new CanvasTrustedGrantService();
        service.issueForTransaction(transaction(), 2, 60_000);

        expect(service.consume(transaction()).allowed).toBe(true);
        expect(service.consume({ ...transaction(), runId: 'other-run' }).allowed).toBe(false);
        expect(service.consume({ ...transaction(), narrativeId: 'other-story' }).allowed).toBe(false);
    });

    it('does not let a scoped grant expand to another note or operation', () => {
        const service = new CanvasTrustedGrantService();
        service.issueForTransaction(transaction(), 2, 60_000);
        const widened = structuredClone(transaction());
        widened.mutations[0].noteId = 'note-2';
        widened.mutations[0].noteUri = 'note://story-1/note-2';
        widened.mutations[0].operationKinds = ['rename'];

        expect(service.consume(widened).allowed).toBe(false);
    });

    it('expires, exhausts, and revokes grants fail closed', () => {
        const service = new CanvasTrustedGrantService();
        const grant = service.issueForTransaction(transaction(), 1, 60_000);
        expect(service.consume(transaction()).allowed).toBe(true);
        expect(service.consume(transaction()).allowed).toBe(false);

        const next = service.issueForTransaction(transaction(), 2, 60_000);
        service.revokeRun('run-1');
        expect(service.consume(transaction()).allowed).toBe(false);
        expect(service.listActive().some((item) => item.id === grant.id || item.id === next.id)).toBe(false);
    });
});

function transaction(): CanvasMultiNoteTransaction {
    return {
        kind: 'canvas_multi_note_transaction_v1',
        transactionId: 'txn-1',
        runId: 'run-1',
        narrativeId: 'story-1',
        mutations: [{
            noteId: 'note-1',
            noteUri: 'note://story-1/note-1',
            operationKinds: ['patch', 'move'],
            expectedRevision: 10,
            before: null,
            after: {
                id: 'note-1', worldId: '', title: 'One', content: { type: 'doc' },
                markdownContent: 'after', folderId: 'folder-2', entityKind: '', entitySubtype: '',
                isEntity: false, isPinned: false, favorite: false, ownerId: '', narrativeId: 'story-1',
                order: 0, createdAt: 1, updatedAt: 10, version: 10,
            },
        }],
        diffPreview: 'diff', stagedAt: 1, stageMs: 1,
    };
}
