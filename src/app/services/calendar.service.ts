import { Injectable, computed, signal, effect, inject } from '@angular/core';
import { getSetting, setSetting } from '../lib/dexie/settings.service';
import { toSignal } from '@angular/core/rxjs-interop';
import { NotesService } from '../lib/dexie/notes.service';
import { FolderService } from '../lib/services/folder.service';
import { Note, Folder } from '../lib/dexie/db';
import { ScopeService, type ResolvedScope } from '../lib/services/scope.service';
import { TabStore } from '../lib/store/tab.store';
import {
    CalendarDefinition,
    FantasyDate,
    CalendarEvent,
    MonthDefinition,
    EraDefinition,
    WeekdayDefinition,
    Period,
    EditorScope,
    EntityRef,
    CausalChain,
    TimeMarker,
    OrbitalMechanics,
    EpochDefinition
} from '../lib/fantasy-calendar/types';

// Re-export EditorScope for consumers
export type { EditorScope } from '../lib/fantasy-calendar/types';
import {
    getDaysInMonth,
    formatFantasyDate,
    formatYearWithEra,
    navigateYear as utilNavigateYear,
    generateUUID
} from '../lib/fantasy-calendar/utils';
import { generateOrbitalCalendar } from '../lib/fantasy-calendar/orbital';
import { ScopedTimelineEventStoreService } from '../lib/services/scoped-timeline-event-store.service';
import { CalendarNoteSnapshotService } from '../lib/services/calendar-note-snapshot.service';
import { buildCalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
import * as ops from '../lib/operations';

export interface CalendarEventTargetNote {
    noteId: string;
    title: string;
    folderId: string;
    narrativeId: string;
    active: boolean;
}

// Config interface for creating a calendar
export interface CalendarConfig {
    name: string;
    startingYear: number;
    eraName: string;
    eraAbbreviation: string;
    monthNames: string[];
    weekdayNames: string[];
    orbitalMechanics?: OrbitalMechanics;
    eras?: EraDefinition[];
    epochs?: EpochDefinition[];
    timeMarkers?: TimeMarker[];
    hasYearZero?: boolean;
}

// Default calendar implementation
export const DEFAULT_CALENDAR: CalendarDefinition = {
    id: 'cal_default',
    name: 'New World Calendar',
    hoursPerDay: 24,
    minutesPerHour: 60,
    secondsPerMinute: 60,
    weekdays: Array.from({ length: 7 }, (_, i) => ({
        id: `wd_${i}`, index: i, name: `Day ${i + 1}`, shortName: `D${i + 1}`
    })),
    months: Array.from({ length: 12 }, (_, i) => ({
        id: `mo_${i}`, index: i, name: `Month ${i + 1}`, shortName: `M${i + 1}`, days: 30
    })),
    eras: [{ id: 'era_1', name: 'Common Era', abbreviation: 'CE', startYear: 1, direction: 'ascending' }],
    defaultEraId: 'era_1',
    epochs: [],
    timeMarkers: [],
    hasYearZero: false,
    moons: [{ id: 'moon_1', name: 'Luna', cycleDays: 28, color: '#e2e8f0' }],
    seasons: [],
    createdFrom: 'manual'
};

@Injectable({
    providedIn: 'root'
})
export class CalendarService {
    // === STATE SIGNALS ===
    private notesService = inject(NotesService);
    private folderService = inject(FolderService);
    private scopeService = inject(ScopeService);
    private tabStore = inject(TabStore);
    private scopedTimelineEvents = inject(ScopedTimelineEventStoreService);
    private noteSnapshotService = inject(CalendarNoteSnapshotService);

    // === STATE SIGNALS ===
    readonly calendar = signal<CalendarDefinition>(DEFAULT_CALENDAR);
    private readonly allNotes = toSignal(this.notesService.getAllNotes$(), { initialValue: [] as Note[] });
    private readonly legacyEventNotes = toSignal(this.notesService.getNotesByEntityKind$('EVENT'), { initialValue: [] as Note[] });
    private readonly allFolders = toSignal(this.folderService.getAllFolders$(), { initialValue: [] as Folder[] });

    // Derived events from scoped timeline events + legacy event notes + dated folders.
    readonly events = computed(() => {
        const scope = this.scopeService.resolvedScope();
        const folders = this.allFolders();
        const folderMap = new Map(folders.map(folder => [folder.id, folder] as const));
        const scopedEvents = this.scopedTimelineEvents.events()
            .filter(event => !!event.calendarDate)
            .map(event => this.mapScopedEventToCalendarEvent(event.id));
        const legacyEvents = this.legacyEventNotes()
            .filter(note => this.isNoteInScope(note, scope, folderMap))
            .map(note => this.mapNoteToEvent(note));
        const folderEvents = folders
            .filter(folder => !!folder.metadata?.date && this.isFolderInScope(folder, scope, folderMap))
            .map(folder => this.mapFolderToEvent(folder));

        return [
            ...scopedEvents.filter((event): event is CalendarEvent => !!event),
            ...legacyEvents,
            ...folderEvents,
        ];
    });

    readonly eligibleOpenNoteTargets = computed<CalendarEventTargetNote[]>(() => {
        const scope = this.scopeService.resolvedScope();
        if (!scope.narrativeId || scope.scopeFolderId === 'vault:global') {
            return [];
        }

        const folderMap = new Map(this.allFolders().map(folder => [folder.id, folder] as const));
        const notesById = new Map(this.allNotes().map(note => [note.id, note] as const));
        const activeNoteId = this.tabStore.tabs().find(tab => tab.active)?.noteId || null;

        return this.tabStore.tabs()
            .map(tab => notesById.get(tab.noteId))
            .filter((note): note is Note => !!note)
            .filter(note => note.entityKind !== 'EVENT')
            .filter(note => this.isNoteInScope(note, scope, folderMap))
            .map(note => ({
                noteId: note.id,
                title: note.title || 'Untitled Note',
                folderId: note.folderId,
                narrativeId: note.narrativeId,
                active: note.id === activeNoteId,
            }));
    });

    readonly periods = signal<Period[]>([]);
    readonly viewDate = signal<FantasyDate>({ year: 1, monthIndex: 0, dayIndex: 0 });
    readonly highlightedEventId = signal<string | null>(null);
    readonly editorScope = signal<EditorScope>('day');
    readonly isGenerating = signal<boolean>(false);

    readonly calendarRegistrySnapshot = computed(() => {
        const scope = this.scopeService.resolvedScope();
        const folders = this.allFolders();
        const folderMap = new Map(folders.map(folder => [folder.id, folder] as const));
        const datedFolders = folders
            .filter(folder => !!folder.metadata?.date && this.isFolderInScope(folder, scope, folderMap));
        const datedFolderIds = new Set(datedFolders.map(folder => folder.id));
        return buildCalendarRegistrySnapshot({
            calendar: this.calendar(),
            periods: this.periods(),
            events: this.events().filter(event => !datedFolderIds.has(event.id)),
            datedFolders,
            scope: {
                kind: scope.type,
                scopeId: scope.scopeFolderId,
                narrativeId: scope.narrativeId,
                folderId: scope.scopeFolderId,
                noteIds: scope.selectedNoteId ? [scope.selectedNoteId] : [],
            },
        });
    });

    // === COMPUTED VALUES ===
    readonly currentMonth = computed(() => {
        const cal = this.calendar();
        const date = this.viewDate();
        return cal.months[date.monthIndex] || cal.months[0];
    });

    readonly daysInCurrentMonth = computed(() => {
        return getDaysInMonth(this.currentMonth(), this.viewDate().year);
    });

    readonly viewYearFormatted = computed(() => {
        return formatYearWithEra(this.calendar(), this.viewDate().year);
    });

    readonly eventsForCurrentMonth = computed(() => {
        const allEvents = this.events();
        const date = this.viewDate();
        // Intentionally not filtering by entity focus yet (can add later)
        return allEvents.filter(e =>
            e.date.year === date.year &&
            e.date.monthIndex === date.monthIndex
        );
    });

    readonly scopedEvents = computed(() => {
        const scope = this.editorScope();
        const events = this.events();
        const viewDate = this.viewDate();
        const currentMonth = this.currentMonth();
        const daysInMonth = this.daysInCurrentMonth();
        const monthEvents = this.eventsForCurrentMonth();

        switch (scope) {
            case 'day':
                return events.filter(e =>
                    e.date.year === viewDate.year &&
                    e.date.monthIndex === viewDate.monthIndex &&
                    e.date.dayIndex === viewDate.dayIndex
                );
            case 'week': {
                const weekStart = viewDate.dayIndex; // Simplified: week starts at current day?
                // Actually, let's stick to the React logic: 
                // Logic was: weekStart = viewDate.dayIndex, weekEnd = min(weekStart+6, daysInMonth-1)
                const weekEnd = Math.min(weekStart + 6, daysInMonth - 1);
                return events.filter(e =>
                    e.date.year === viewDate.year &&
                    e.date.monthIndex === viewDate.monthIndex &&
                    e.date.dayIndex >= weekStart &&
                    e.date.dayIndex <= weekEnd
                );
            }
            case 'month':
                return monthEvents;
            case 'period':
                return events; // Return all for now, logic needed for actual period filter
            default:
                return events;
        }
    });

    constructor() {
        // Load from Dexie settings if available
        const savedCal = getSetting<CalendarDefinition | null>('fantasy_calendar_def', null);
        if (savedCal) {
            this.calendar.set(savedCal);
        }

        const savedPeriods = getSetting<Period[] | null>('fantasy_calendar_periods', null);
        if (savedPeriods) {
            this.periods.set(savedPeriods);
        }

        // Auto-save effect
        effect(() => {
            setSetting('fantasy_calendar_def', this.calendar());
            // Events are now handled by Dexie/NotesService, no need to save separately
            setSetting('fantasy_calendar_periods', this.periods());
        });
    }

    // === NAVIGATION ===

    navigateMonth(dir: 'prev' | 'next') {
        const current = this.viewDate();
        const cal = this.calendar();

        let newMonth = current.monthIndex + (dir === 'next' ? 1 : -1);
        let newYear = current.year;

        if (newMonth < 0) {
            newMonth = cal.months.length - 1;
            newYear = utilNavigateYear(current.year, 'prev', cal.hasYearZero);
        } else if (newMonth >= cal.months.length) {
            newMonth = 0;
            newYear = utilNavigateYear(current.year, 'next', cal.hasYearZero);
        }

        this.viewDate.set({ ...current, monthIndex: newMonth, year: newYear, dayIndex: 0 });
    }

    navigateYear(dir: 'prev' | 'next') {
        const current = this.viewDate();
        const cal = this.calendar();
        this.viewDate.set({
            ...current,
            year: utilNavigateYear(current.year, dir, cal.hasYearZero)
        });
    }

    navigateDay(dir: 'prev' | 'next') {
        const current = this.viewDate();
        const cal = this.calendar();
        const daysInMonth = getDaysInMonth(cal.months[current.monthIndex], current.year);

        let newDay = current.dayIndex + (dir === 'next' ? 1 : -1);
        let newMonth = current.monthIndex;
        let newYear = current.year;

        if (newDay < 0) {
            newMonth = current.monthIndex - 1;
            if (newMonth < 0) {
                newMonth = cal.months.length - 1;
                newYear = utilNavigateYear(current.year, 'prev', cal.hasYearZero);
            }
            const prevMonthDef = cal.months[newMonth];
            // simplified logic
            newDay = getDaysInMonth(prevMonthDef, newYear) - 1;
        } else if (newDay >= daysInMonth) {
            newMonth = current.monthIndex + 1;
            if (newMonth >= cal.months.length) {
                newMonth = 0;
                newYear = utilNavigateYear(current.year, 'next', cal.hasYearZero);
            }
            newDay = 0;
        }

        this.viewDate.set({ ...current, dayIndex: newDay, monthIndex: newMonth, year: newYear });
    }

    selectDay(dayIndex: number) {
        this.viewDate.update(d => ({ ...d, dayIndex }));
    }

    goToYear(year: number) {
        this.viewDate.update(d => ({ ...d, year, monthIndex: 0, dayIndex: 0 }));
    }

    // === EVENT CRUD ===

    // === EVENT CRUD ===

    async addEvent(eventData: Omit<CalendarEvent, 'id' | 'calendarId'>, targetNoteId: string): Promise<string> {
        const note = await ops.getNote(targetNoteId);
        if (!note) {
            throw new Error(`Target note ${targetNoteId} was not found`);
        }

        const createdEvent = await this.scopedTimelineEvents.createEvent({
            title: eventData.title,
            description: eventData.description || '',
            entityIds: [],
            displayTime: formatFantasyDate(this.calendar(), eventData.date),
            linkedNoteId: targetNoteId,
            linkedNoteTitle: note.title || 'Untitled Note',
            calendarDate: { ...eventData.date },
            source: 'calendar',
            status: eventData.status || 'todo',
            color: eventData.color,
            eventTypeId: eventData.eventTypeId,
            importance: eventData.importance,
            category: eventData.category,
            type: eventData.type,
            tags: eventData.tags,
        });

        if (!createdEvent) {
            throw new Error('Cannot create event without an active narrative scope');
        }

        try {
            await this.noteSnapshotService.appendEventSnapshot({
                noteId: targetNoteId,
                calendar: this.calendar(),
                date: eventData.date,
                title: eventData.title,
                description: eventData.description,
            });
        } catch (error) {
            await this.scopedTimelineEvents.deleteEvent(createdEvent.id);
            throw error;
        }

        return createdEvent.id;
    }

    async updateEvent(id: string, updates: Partial<CalendarEvent>) {
        const scopedEvent = this.scopedTimelineEvents.events().find(event => event.id === id && !!event.calendarDate);
        if (scopedEvent?.calendarDate) {
            const nextDate = updates.date || scopedEvent.calendarDate;
            await this.scopedTimelineEvents.updateEvent(id, {
                title: updates.title ?? scopedEvent.title,
                description: updates.description ?? scopedEvent.description,
                displayTime: formatFantasyDate(this.calendar(), nextDate),
                calendarDate: { ...nextDate },
                status: updates.status ?? scopedEvent.status,
                color: updates.color ?? scopedEvent.color,
                eventTypeId: updates.eventTypeId ?? scopedEvent.eventTypeId,
                importance: updates.importance ?? scopedEvent.importance,
                category: updates.category ?? scopedEvent.category,
                type: updates.type ?? scopedEvent.type,
                tags: updates.tags ?? scopedEvent.tags,
            });
            return;
        }

        const legacyNote = this.legacyEventNotes().find(note => note.id === id);
        if (!legacyNote) {
            return;
        }

        const currentEvent = this.mapNoteToEvent(legacyNote);
        const updatedEvent = { ...currentEvent, ...updates, updatedAt: new Date().toISOString() };
        const noteUpdates: Partial<Note> = {
            title: updatedEvent.title,
            updatedAt: Date.now(),
            content: JSON.stringify(updatedEvent),
            markdownContent: updatedEvent.description || '',
        };

        await this.notesService.updateNote(id, noteUpdates);
    }

    async removeEvent(id: string) {
        const scopedEvent = this.scopedTimelineEvents.events().find(event => event.id === id && !!event.calendarDate);
        if (scopedEvent?.calendarDate) {
            await this.scopedTimelineEvents.deleteEvent(id);
            return;
        }

        const legacyNote = this.legacyEventNotes().find(note => note.id === id);
        if (legacyNote) {
            await this.notesService.deleteNote(id);
        }
    }

    async toggleEventStatus(id: string) {
        const event = this.events().find(e => e.id === id);
        if (!event) return;

        const statusCycle: Record<string, 'todo' | 'in-progress' | 'completed'> = {
            'undefined': 'in-progress',
            'todo': 'in-progress',
            'in-progress': 'completed',
            'completed': 'todo'
        };

        const currentStatus = event.status || 'todo';
        await this.updateEvent(id, { status: statusCycle[currentStatus] });
    }

    // === MAPPERS ===

    private mapNoteToEvent(note: Note): CalendarEvent {
        let eventData: Partial<CalendarEvent> = {};
        try {
            eventData = JSON.parse(note.content);
        } catch (e) {
            console.error('Failed to parse event data for note', note.id, e);
            // Fallback for broken JSON
        }

        return {
            id: note.id,
            calendarId: eventData.calendarId || this.calendar().id,
            title: note.title,
            date: eventData.date || { year: 1, monthIndex: 0, dayIndex: 0 },
            endDate: eventData.endDate,
            color: eventData.color,
            description: eventData.description,
            importance: eventData.importance,
            type: eventData.type,
            entityId: eventData.entityId,
            tags: eventData.tags,
            status: eventData.status,
            createdAt: new Date(note.createdAt).toISOString(),
            updatedAt: new Date(note.updatedAt).toISOString()
        };
    }

    private mapScopedEventToCalendarEvent(id: string): CalendarEvent | null {
        const event = this.scopedTimelineEvents.events().find(item => item.id === id && !!item.calendarDate);
        if (!event?.calendarDate) {
            return null;
        }

        return {
            id: event.id,
            calendarId: this.calendar().id,
            title: event.title,
            description: event.description || undefined,
            date: { ...event.calendarDate },
            color: event.color,
            importance: event.importance,
            category: event.category,
            type: event.type,
            eventTypeId: event.eventTypeId,
            tags: event.tags,
            status: this.normalizeCalendarStatus(event.status),
            sourceNoteId: event.linkedNoteId,
            createdAt: new Date(event.createdAt).toISOString(),
            updatedAt: new Date(event.updatedAt).toISOString(),
        };
    }

    // === PERIOD CONFIG ===

    addPeriod(periodData: Omit<Period, 'id' | 'calendarId'>): Period {
        const newPeriod: Period = {
            ...periodData,
            id: generateUUID(),
            calendarId: this.calendar().id,
            createdAt: new Date().toISOString()
        };
        this.periods.update(list => [...list, newPeriod]);
        return newPeriod;
    }

    updatePeriod(id: string, updates: Partial<Period>) {
        this.periods.update(list =>
            list.map(p => p.id === id ? { ...p, ...updates, updatedAt: new Date().toISOString() } : p)
        );
    }

    removePeriod(id: string) {
        this.periods.update(list => list.filter(p => p.id !== id));
    }

    // === EDITOR SCOPE ===

    setEditorScope(scope: EditorScope) {
        this.editorScope.set(scope);
    }

    getEventsForScope(): CalendarEvent[] {
        return this.scopedEvents();
    }

    // Export EditorScope type for consumers


    // === CALENDAR GENERATION ===

    private mapFolderToEvent(folder: Folder): CalendarEvent {
        // Default assumption: use metadata date or fallback to year 1
        const date = folder.metadata?.date || { year: 1, monthIndex: 0, dayIndex: 0 };
        return {
            id: folder.id,
            calendarId: this.calendar().id,
            title: folder.name,
            date: date,
            color: folder.color || '#3b82f6', // Default blue if no color
            description: `Entity Folder: ${folder.entityKind}`,
            importance: 'major', // Acts/Chapters are usually major
            type: folder.entityKind, // e.g., 'ACT', 'CHAPTER'
            status: 'completed', // Folders "exist", so they are "completed" events? Or just generic.
            entityId: folder.id, // Link back to folder
            tags: [folder.entityKind],
            createdAt: new Date(folder.createdAt).toISOString(),
            updatedAt: new Date(folder.updatedAt).toISOString()
        };
    }

    private normalizeCalendarStatus(status: string | undefined): 'todo' | 'in-progress' | 'completed' | undefined {
        switch (status) {
            case 'todo':
            case 'in-progress':
            case 'completed':
                return status;
            default:
                return undefined;
        }
    }

    private isFolderInScope(
        folder: Folder,
        scope: ResolvedScope,
        folderMap: Map<string, Folder>
    ): boolean {
        if (scope.type === 'global') {
            return true;
        }

        if (!scope.narrativeId) {
            return this.isFolderDescendantOf(folder.id, scope.scopeFolderId, folderMap);
        }

        if (folder.narrativeId !== scope.narrativeId) {
            return false;
        }

        switch (scope.type) {
            case 'narrative':
                return true;
            case 'act':
            case 'folder':
                return this.isFolderDescendantOf(folder.id, scope.scopeFolderId, folderMap);
            case 'note':
                return scope.selectedNoteId ? folder.id === scope.scopeFolderId : false;
            default:
                return false;
        }
    }

    private isNoteInScope(
        note: Note,
        scope: ResolvedScope,
        folderMap: Map<string, Folder>
    ): boolean {
        if (scope.type === 'global') {
            return true;
        }

        if (!scope.narrativeId) {
            return !!note.folderId && this.isFolderDescendantOf(note.folderId, scope.scopeFolderId, folderMap);
        }

        if (note.narrativeId !== scope.narrativeId) {
            return false;
        }

        switch (scope.type) {
            case 'narrative':
                return true;
            case 'act':
            case 'folder':
                return !!note.folderId && this.isFolderDescendantOf(note.folderId, scope.scopeFolderId, folderMap);
            case 'note':
                return note.id === (scope.selectedNoteId || scope.id);
            default:
                return false;
        }
    }

    private isFolderDescendantOf(folderId: string, ancestorId: string, folderMap: Map<string, Folder>): boolean {
        let currentId = folderId;

        while (currentId) {
            if (currentId === ancestorId) {
                return true;
            }

            currentId = folderMap.get(currentId)?.parentId || '';
        }

        return false;
    }

    async createCalendar(config: CalendarConfig) {
        this.isGenerating.set(true);

        // Simulate async work
        await new Promise(resolve => setTimeout(resolve, 500));

        const calId = generateUUID();
        const eraId = generateUUID();

        // Default months if none
        let months: MonthDefinition[] = config.monthNames.map((name, i) => ({
            id: generateUUID(),
            index: i,
            name: name || `Month ${i + 1}`,
            shortName: name?.substring(0, 3) || `M${i + 1}`,
            days: 30
        }));

        if (months.length === 0) {
            for (let i = 0; i < 12; i++) {
                months.push({
                    id: generateUUID(),
                    index: i,
                    name: `Month ${i + 1}`,
                    shortName: `M${i + 1}`,
                    days: 30
                });
            }
        }

        const era: EraDefinition = {
            id: eraId,
            name: config.eraName || 'Common Era',
            abbreviation: config.eraAbbreviation || 'CE',
            startYear: 1,
            direction: 'ascending'
        };

        const weekdays: WeekdayDefinition[] = (config.weekdayNames || []).map((name, i) => ({
            id: generateUUID(),
            index: i,
            name: name || `Day ${i + 1}`,
            shortName: `D${i + 1}`
        }));

        if (weekdays.length === 0) {
            // Default 7 days
            for (let i = 0; i < 7; i++) {
                weekdays.push({ id: generateUUID(), index: i, name: `Day ${i + 1}`, shortName: `D${i + 1}` });
            }
        }

        const eras = config.eras && config.eras.length > 0 ? config.eras : [era];

        const newCalendar: CalendarDefinition = {
            ...DEFAULT_CALENDAR,
            id: calId,
            name: config.name || 'Unnamed Calendar',
            weekdays,
            months,
            eras,
            defaultEraId: eras[0].id,
            epochs: config.epochs || [],
            timeMarkers: config.timeMarkers || [],
            hasYearZero: config.hasYearZero ?? false,
            orbitalMechanics: config.orbitalMechanics,
            createdFrom: config.orbitalMechanics ? 'orbital' : 'manual'
        };

        this.calendar.set(newCalendar);
        this.viewDate.set({
            year: config.startingYear || 1,
            monthIndex: 0,
            dayIndex: 0,
            eraId: eras[0].id
        });

        this.isGenerating.set(false);
    }
}
