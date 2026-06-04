import '@angular/compiler';
import { BehaviorSubject } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getSettingMock, setSettingMock, getNoteMock, effectMock } = vi.hoisted(() => ({
    getSettingMock: vi.fn(),
    setSettingMock: vi.fn(),
    getNoteMock: vi.fn(),
    effectMock: vi.fn((callback: () => void) => {
        callback();
        return { destroy: vi.fn() };
    }),
}));

vi.mock('@angular/core', async () => {
    const actual = await vi.importActual<typeof import('@angular/core')>('@angular/core');
    return {
        ...actual,
        effect: effectMock,
    };
});

vi.mock('../lib/dexie/settings.service', () => ({
    getSetting: getSettingMock,
    setSetting: setSettingMock,
}));

vi.mock('../lib/operations', () => ({
    getNote: getNoteMock,
}));

import {
    Injector,
    computed,
    runInInjectionContext,
    signal,
} from '@angular/core';
import type { Folder, Note } from '../lib/dexie/db';
import type { ResolvedScope } from '../lib/services/scope.service';
import { NotesService } from '../lib/dexie/notes.service';
import { FolderService } from '../lib/services/folder.service';
import { CalendarNoteSnapshotService } from '../lib/services/calendar-note-snapshot.service';
import { ScopeService } from '../lib/services/scope.service';
import { ScopedTimelineEventStoreService } from '../lib/services/scoped-timeline-event-store.service';
import { TabStore } from '../lib/store/tab.store';
import { CalendarService } from './calendar.service';

const ACT_SCOPE: ResolvedScope = {
    type: 'act',
    id: 'act-1',
    narrativeId: 'narr-1',
    actId: 'act-1',
    scopeType: 'act',
    scopeFolderId: 'act-1',
    actFolderId: 'act-1',
    lineageFolderIds: ['narr-1', 'act-1'],
    label: 'Act One',
};

function makeFolder(overrides: Partial<Folder> = {}): Folder {
    return {
        id: 'folder-1',
        worldId: 'world-1',
        name: 'Folder',
        parentId: '',
        entityKind: 'ACT',
        entitySubtype: '',
        entityLabel: 'Folder',
        color: '',
        isTypedRoot: false,
        isSubtypeRoot: false,
        collapsed: false,
        ownerId: 'local',
        createdAt: 1,
        updatedAt: 1,
        narrativeId: 'narr-1',
        isNarrativeRoot: false,
        order: 1000,
        ...overrides,
    };
}

function makeNote(overrides: Partial<Note> = {}): Note {
    return {
        id: 'note-1',
        worldId: 'world-1',
        title: 'Note',
        content: '{}',
        markdownContent: '',
        folderId: 'act-1',
        entityKind: '',
        entitySubtype: '',
        isEntity: false,
        isPinned: false,
        favorite: false,
        ownerId: 'local',
        createdAt: 1,
        updatedAt: 1,
        narrativeId: 'narr-1',
        order: 1000,
        ...overrides,
    };
}

describe('CalendarService', () => {
    let injector: Injector & { destroy?: () => void };
    let notesSubject: BehaviorSubject<Note[]>;
    let legacyEventNotesSubject: BehaviorSubject<Note[]>;
    let foldersSubject: BehaviorSubject<Folder[]>;
    let scopeSignal: ReturnType<typeof signal<ResolvedScope>>;
    let tabSignal: ReturnType<typeof signal<Array<{ id: string; noteId: string; title: string; active: boolean }>>>;
    let notesServiceMock: {
        getAllNotes$: ReturnType<typeof vi.fn>;
        getNotesByEntityKind$: ReturnType<typeof vi.fn>;
        createNote: ReturnType<typeof vi.fn>;
        updateNote: ReturnType<typeof vi.fn>;
        deleteNote: ReturnType<typeof vi.fn>;
    };
    let folderServiceMock: {
        getAllFolders$: ReturnType<typeof vi.fn>;
    };
    let timelineStoreMock: {
        events: ReturnType<typeof signal<any[]>>;
        createEvent: ReturnType<typeof vi.fn>;
        updateEvent: ReturnType<typeof vi.fn>;
        deleteEvent: ReturnType<typeof vi.fn>;
    };
    let noteSnapshotMock: {
        appendEventSnapshot: ReturnType<typeof vi.fn>;
    };
    let service: CalendarService;

    beforeEach(() => {
        getSettingMock.mockReturnValue(null);

        notesSubject = new BehaviorSubject<Note[]>([]);
        legacyEventNotesSubject = new BehaviorSubject<Note[]>([]);
        foldersSubject = new BehaviorSubject<Folder[]>([]);
        scopeSignal = signal<ResolvedScope>(ACT_SCOPE);
        tabSignal = signal([
            { id: 'tab-1', noteId: 'note-1', title: 'In Scope', active: true },
            { id: 'tab-2', noteId: 'note-2', title: 'Out Of Scope', active: false },
            { id: 'tab-3', noteId: 'note-3', title: 'Legacy Event Note', active: false },
        ]);

        notesServiceMock = {
            getAllNotes$: vi.fn(() => notesSubject.asObservable()),
            getNotesByEntityKind$: vi.fn(() => legacyEventNotesSubject.asObservable()),
            createNote: vi.fn(),
            updateNote: vi.fn().mockResolvedValue(undefined),
            deleteNote: vi.fn().mockResolvedValue(undefined),
        };
        folderServiceMock = {
            getAllFolders$: vi.fn(() => foldersSubject.asObservable()),
        };
        timelineStoreMock = {
            events: signal([]),
            createEvent: vi.fn(),
            updateEvent: vi.fn().mockResolvedValue(undefined),
            deleteEvent: vi.fn().mockResolvedValue(undefined),
        };
        noteSnapshotMock = {
            appendEventSnapshot: vi.fn().mockResolvedValue(undefined),
        };

        injector = Injector.create({
            providers: [
                { provide: NotesService, useValue: notesServiceMock },
                { provide: FolderService, useValue: folderServiceMock },
                {
                    provide: ScopeService,
                    useValue: {
                        resolvedScope: computed(() => scopeSignal()),
                    },
                },
                { provide: TabStore, useValue: { tabs: tabSignal } },
                { provide: ScopedTimelineEventStoreService, useValue: timelineStoreMock },
                { provide: CalendarNoteSnapshotService, useValue: noteSnapshotMock },
            ],
        }) as Injector & { destroy?: () => void };

        service = runInInjectionContext(injector, () => new CalendarService());
    });

    afterEach(() => {
        injector.destroy?.();
        vi.clearAllMocks();
    });

    it('limits eligible target notes to open tabs within the active scope', () => {
        foldersSubject.next([
            makeFolder({ id: 'narr-1', name: 'Narrative Root', narrativeId: 'narr-1', isNarrativeRoot: true }),
            makeFolder({ id: 'act-1', name: 'Act One', parentId: 'narr-1', narrativeId: 'narr-1' }),
            makeFolder({ id: 'act-2', name: 'Act Two', parentId: 'narr-1', narrativeId: 'narr-1' }),
        ]);
        notesSubject.next([
            makeNote({ id: 'note-1', title: 'Scene One', folderId: 'act-1' }),
            makeNote({ id: 'note-2', title: 'Scene Two', folderId: 'act-2' }),
            makeNote({ id: 'note-3', title: 'Old Event Note', folderId: 'act-1', entityKind: 'EVENT' }),
        ]);

        expect(service.eligibleOpenNoteTargets()).toEqual([
            {
                noteId: 'note-1',
                title: 'Scene One',
                folderId: 'act-1',
                narrativeId: 'narr-1',
                active: true,
            },
        ]);
    });

    it('creates shared calendar events without creating standalone EVENT notes', async () => {
        notesSubject.next([
            makeNote({ id: 'note-1', title: 'Chapter One', folderId: 'act-1' }),
        ]);
        foldersSubject.next([
            makeFolder({ id: 'narr-1', name: 'Narrative Root', narrativeId: 'narr-1', isNarrativeRoot: true }),
            makeFolder({ id: 'act-1', name: 'Act One', parentId: 'narr-1', narrativeId: 'narr-1' }),
        ]);
        getNoteMock.mockResolvedValue({
            id: 'note-1',
            title: 'Chapter One',
        });
        timelineStoreMock.createEvent.mockResolvedValue({
            id: 'event-1',
            title: 'Coronation',
            description: '',
            order: 1,
            entityIds: [],
            source: 'calendar',
            linkedNoteId: 'note-1',
            linkedNoteTitle: 'Chapter One',
            calendarDate: { year: 1, monthIndex: 0, dayIndex: 1 },
            createdAt: 1,
            updatedAt: 1,
        });

        const createdId = await service.addEvent({
            title: 'Coronation',
            description: 'The crown changes hands.',
            date: { year: 1, monthIndex: 0, dayIndex: 1 },
            status: 'todo',
        }, 'note-1');

        expect(createdId).toBe('event-1');
        expect(notesServiceMock.createNote).not.toHaveBeenCalled();
        expect(timelineStoreMock.createEvent).toHaveBeenCalledWith(expect.objectContaining({
            title: 'Coronation',
            description: 'The crown changes hands.',
            linkedNoteId: 'note-1',
            linkedNoteTitle: 'Chapter One',
            source: 'calendar',
            status: 'todo',
            displayTime: '2 Month 1, 1 CE',
            calendarDate: { year: 1, monthIndex: 0, dayIndex: 1 },
        }));
        expect(noteSnapshotMock.appendEventSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            noteId: 'note-1',
            title: 'Coronation',
            description: 'The crown changes hands.',
            date: { year: 1, monthIndex: 0, dayIndex: 1 },
        }));
    });

    it('exposes a scoped read-only calendar registry snapshot', () => {
        foldersSubject.next([
            makeFolder({ id: 'narr-1', name: 'Narrative Root', narrativeId: 'narr-1', isNarrativeRoot: true }),
            makeFolder({ id: 'act-1', name: 'Act One', parentId: 'narr-1', narrativeId: 'narr-1' }),
            makeFolder({
                id: 'folder-dated',
                name: 'Dated Act',
                parentId: 'act-1',
                narrativeId: 'narr-1',
                metadata: { date: { year: 1, monthIndex: 0, dayIndex: 2 } },
            }),
        ]);
        timelineStoreMock.events.set([{
            id: 'event-1',
            title: 'Coronation',
            description: 'The crown changes hands.',
            order: 1,
            entityIds: [],
            source: 'calendar',
            linkedNoteId: 'note-1',
            linkedNoteTitle: 'Chapter One',
            calendarDate: { year: 1, monthIndex: 0, dayIndex: 1 },
            status: 'todo',
            createdAt: 1,
            updatedAt: 1,
        }]);
        service.periods.set([{
            id: 'period-1',
            calendarId: service.calendar().id,
            name: 'First Age',
            startYear: 1,
            periodType: 'age',
            color: '#22c55e',
        }]);

        const snapshot = service.calendarRegistrySnapshot();

        expect(snapshot.scope).toMatchObject({
            kind: 'act',
            scopeId: 'act-1',
            narrativeId: 'narr-1',
        });
        expect(snapshot.summary).toMatchObject({
            anchorCount: 3,
            eventAnchorCount: 1,
            folderAnchorCount: 1,
            periodAnchorCount: 1,
        });
        expect(snapshot.anchors.filter(anchor => anchor.kind === 'user_calendar_event')).toHaveLength(1);
        expect(snapshot.anchors.find(anchor => anchor.kind === 'user_calendar_event')).toMatchObject({
            sourceId: 'event-1',
            noteId: 'note-1',
            calendarFingerprint: snapshot.calendar.fingerprint,
            displayDate: '2 Month 1, 1 CE',
        });
        expect(snapshot.anchors.find(anchor => anchor.kind === 'user_calendar_folder')).toMatchObject({
            sourceId: 'folder-dated',
            folderId: 'folder-dated',
            ordinal: 2,
        });
    });
});
