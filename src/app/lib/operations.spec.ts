import { beforeEach, describe, expect, it, vi } from 'vitest';

const notesMock = vi.hoisted(() => ({
    rows: new Map<string, any>(),
    get: vi.fn(async (id: string) => notesMock.rows.get(id)),
    bulkGet: vi.fn(async (ids: string[]) => ids.map((id) => notesMock.rows.get(id))),
    put: vi.fn(async (note: any) => {
        notesMock.rows.set(note.id, note);
    }),
    delete: vi.fn(async (id: string) => {
        notesMock.rows.delete(id);
    }),
}));

const prettyTextApiMock = vi.hoisted(() => ({
    upsertNote: vi.fn(async () => undefined),
}));

vi.mock('./dexie/db', () => ({
    db: {
        notes: {
            get: notesMock.get,
            bulkGet: notesMock.bulkGet,
            put: notesMock.put,
            delete: notesMock.delete,
        },
    },
}));

vi.mock('./notes/note-structure-projection', () => ({
    clearNoteStructureProjection: vi.fn(async () => undefined),
    deleteNoteStructureProjection: vi.fn(async () => undefined),
    replaceNoteStructureProjection: vi.fn(async () => undefined),
}));

vi.mock('./notes/context-islands', () => ({
    isGlobalContextScope: vi.fn(() => false),
    scheduleGlobalContextIslandRefresh: vi.fn(),
}));

vi.mock('./notes/entity-occurrence-index', () => ({
    deleteNoteEntityOccurrences: vi.fn(async () => undefined),
}));

vi.mock('../api/pretty-text-api', () => ({
    getPhoenixUiApi: () => prettyTextApiMock,
}));

import {
    commitNoteTransaction,
    getNotesByIds,
    setPhoenixStoreBridge,
    updateNote,
    type Note,
} from './operations';

describe('operations note recovery', () => {
    beforeEach(() => {
        notesMock.rows.clear();
        notesMock.get.mockClear();
        notesMock.bulkGet.mockClear();
        notesMock.put.mockClear();
        notesMock.delete.mockClear();
        prettyTextApiMock.upsertNote.mockClear();
    });

    it('rehydrates a missing native note from the Dexie cache before saving', async () => {
        const store = createStoreMock();
        store.getNote.mockResolvedValue(null);
        setPhoenixStoreBridge(store as any);
        notesMock.rows.set('note-1', noteRow({
            id: 'note-1',
            markdownContent: 'old text',
            content: 'old text',
        }));

        const saved = await updateNote('note-1', {
            markdownContent: 'new text',
            content: 'new text',
        });

        expect(store.upsertNote).toHaveBeenCalledWith(expect.objectContaining({
            id: 'note-1',
            markdownContent: 'new text',
            content: 'new text',
        }));
        expect(saved).toEqual(expect.objectContaining({
            id: 'note-1',
            markdownContent: 'new text',
            hasBody: true,
        }));
        expect(notesMock.put).toHaveBeenCalledWith(expect.objectContaining({
            id: 'note-1',
            markdownContent: 'new text',
            hasBody: true,
        }));
    });

    it('uses Dexie bodies for ids missing from the native note batch', async () => {
        const store = createStoreMock();
        store.getNotesByIds.mockResolvedValue([storeNote({ id: 'native-note', markdownContent: 'native' })]);
        setPhoenixStoreBridge(store as any);
        notesMock.rows.set('cached-note', noteRow({
            id: 'cached-note',
            markdownContent: 'cached body',
            content: 'cached body',
        }));

        const notes = await getNotesByIds(['cached-note', 'native-note']);

        expect(store.getNotesByIds).toHaveBeenCalledWith(['cached-note', 'native-note']);
        expect(notes.map((note) => note.id)).toEqual(['cached-note', 'native-note']);
        expect(notes.map((note) => note.markdownContent)).toEqual(['cached body', 'native']);
    });

    it('warms Dexie with native batch note bodies', async () => {
        const store = createStoreMock();
        store.getNotesByIds.mockResolvedValue([storeNote({ id: 'native-note', markdownContent: 'full body' })]);
        setPhoenixStoreBridge(store as any);

        await getNotesByIds(['native-note']);

        expect(notesMock.put).toHaveBeenCalledWith(expect.objectContaining({
            id: 'native-note',
            markdownContent: 'full body',
            hasBody: true,
        }));
    });

    it('publishes a committed Canvas transaction and invalidates note projections', async () => {
        const store = createStoreMock();
        const committed = storeNote({
            id: 'note-1',
            content: JSON.stringify({ type: 'doc', content: [{ type: 'paragraph' }] }),
            markdownContent: 'after',
            version: 102,
            updatedAt: 102,
        });
        store.commitNoteTransaction.mockResolvedValue({
            transactionId: 'txn-1',
            status: 'committed',
            note: committed,
            expectedRevision: 101,
            actualRevision: 102,
            timing: { totalMs: 4 },
        });
        setPhoenixStoreBridge(store as any);

        const result = await commitNoteTransaction({
            transactionId: 'txn-1',
            noteId: 'note-1',
            expectedRevision: 101,
            content: { type: 'doc', content: [{ type: 'paragraph' }] },
            markdownContent: 'after',
        });

        expect(result).toEqual(expect.objectContaining({
            status: 'committed',
            expectedRevision: 101,
            actualRevision: 102,
            commitMs: 4,
        }));
        expect(notesMock.put).toHaveBeenCalledWith(expect.objectContaining({
            id: 'note-1',
            markdownContent: 'after',
            version: 102,
        }));
        expect(store.scheduleDocumentSemanticMaterialization).toHaveBeenCalledWith(committed);
    });

    it('does not warm or reindex a Canvas transaction conflict', async () => {
        const store = createStoreMock();
        store.commitNoteTransaction.mockResolvedValue({
            transactionId: 'txn-2',
            status: 'conflict',
            note: storeNote({ id: 'note-1', version: 202, updatedAt: 202 }),
            expectedRevision: 101,
            actualRevision: 202,
            timing: { totalMs: 0 },
        });
        setPhoenixStoreBridge(store as any);

        const result = await commitNoteTransaction({
            transactionId: 'txn-2',
            noteId: 'note-1',
            expectedRevision: 101,
            content: { type: 'doc', content: [] },
            markdownContent: 'staged',
        });

        expect(result.status).toBe('conflict');
        expect(result.actualRevision).toBe(202);
        expect(notesMock.put).not.toHaveBeenCalled();
        expect(prettyTextApiMock.upsertNote).not.toHaveBeenCalled();
    });
});

function createStoreMock() {
    return {
        isReady: true,
        initialize: vi.fn(async () => undefined),
        getNote: vi.fn(async () => null),
        getNotesByIds: vi.fn(async () => []),
        upsertNote: vi.fn(async () => undefined),
        commitNoteTransaction: vi.fn(),
        scheduleDocumentSemanticMaterialization: vi.fn(),
    };
}

function noteRow(overrides: Partial<Note>): Note {
    const now = 100;
    return {
        id: 'note',
        worldId: '',
        title: 'Untitled Note',
        content: '',
        markdownContent: '',
        folderId: '',
        ownerId: '',
        createdAt: now,
        updatedAt: now,
        version: now,
        order: 0,
        hasBody: true,
        ...overrides,
    };
}

function storeNote(overrides: Partial<Note>) {
    const note = noteRow(overrides);
    return {
        id: note.id,
        worldId: note.worldId,
        title: note.title,
        content: String(note.content || ''),
        markdownContent: note.markdownContent,
        folderId: note.folderId,
        entityKind: note.entityKind || '',
        entitySubtype: note.entitySubtype || '',
        isEntity: note.isEntity || false,
        isPinned: note.isPinned || false,
        favorite: note.favorite || false,
        ownerId: note.ownerId,
        narrativeId: note.narrativeId || '',
        order: note.order,
        createdAt: note.createdAt,
        updatedAt: note.updatedAt,
        version: note.version,
    };
}
