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

import { getNotesByIds, setPhoenixStoreBridge, updateNote, type Note } from './operations';

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
});

function createStoreMock() {
    return {
        isReady: true,
        initialize: vi.fn(async () => undefined),
        getNote: vi.fn(async () => null),
        getNotesByIds: vi.fn(async () => []),
        upsertNote: vi.fn(async () => undefined),
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
