import { describe, expect, it } from 'vitest';

import type { CalendarDefinition, CalendarEvent, Period } from './types';
import {
    buildCalendarRegistrySnapshot,
    calendarDefinitionFingerprint,
    fantasyDateOrdinal,
    isEarthCompatibleCalendar,
} from './calendar-registry-snapshot';
import type { Folder } from '../dexie/db';

describe('calendar registry snapshot', () => {
    it('projects custom calendar events, folders, periods, and markers as ordinal anchors', () => {
        const calendar = customCalendar({
            timeMarkers: [{
                id: 'marker-1',
                calendarId: 'cal-custom',
                name: 'Founding',
                year: 1,
                importance: 'major',
            }],
            currentDate: { year: 1, monthIndex: 0, dayIndex: 4 },
        });
        const event: CalendarEvent = {
            id: 'event-1',
            calendarId: calendar.id,
            title: 'Coronation',
            description: 'The crown changes hands.',
            date: { year: 1, monthIndex: 0, dayIndex: 1 },
            sourceNoteId: 'note-1',
            status: 'todo',
        };
        const folder = datedFolder('folder-1', { year: 1, monthIndex: 0, dayIndex: 2 });
        const period: Period = {
            id: 'period-1',
            calendarId: calendar.id,
            name: 'First Age',
            startYear: 1,
            endYear: 2,
            periodType: 'age',
            color: '#22c55e',
        };

        const snapshot = buildCalendarRegistrySnapshot({
            calendar,
            events: [event],
            datedFolders: [folder],
            periods: [period],
            builtAt: 77,
            scope: { kind: 'act', scopeId: 'act-1', narrativeId: 'narr-1' },
        });

        expect(snapshot.schemaVersion).toBe('phoenix-calendar-registry/v1');
        expect(snapshot.calendar.mode).toBe('customOrdinal');
        expect(snapshot.summary.anchorCount).toBe(5);
        expect(snapshot.summary.customOrdinalAnchorCount).toBe(5);
        expect(snapshot.summary.realCompatibleAnchorCount).toBe(0);
        expect(snapshot.summary.sourceKindCounts).toMatchObject({
            user_calendar_event: 1,
            user_calendar_folder: 1,
            user_calendar_period: 1,
            calendar_time_marker: 1,
            calendar_now_marker: 1,
        });

        const eventAnchor = snapshot.anchors.find(anchor => anchor.kind === 'user_calendar_event');
        expect(eventAnchor).toMatchObject({
            sourceId: 'event-1',
            sourceLabel: 'Coronation',
            noteId: 'note-1',
            displayDate: '2 Month 1, 1 CE',
            ordinal: 1,
            calendarFingerprint: snapshot.calendar.fingerprint,
            realEpochMs: undefined,
        });
        expect(eventAnchor?.evidenceRefs).toContain('note:note-1');

        const folderAnchor = snapshot.anchors.find(anchor => anchor.kind === 'user_calendar_folder');
        expect(folderAnchor).toMatchObject({
            sourceId: 'folder-1',
            folderId: 'folder-1',
            ordinal: 2,
        });

        const periodAnchor = snapshot.anchors.find(anchor => anchor.kind === 'user_calendar_period');
        expect(periodAnchor).toMatchObject({
            sourceId: 'period-1',
            ordinal: 0,
            endOrdinal: 719,
            granularity: 'year',
        });
    });

    it('grounds real-compatible calendars into epoch millisecond windows', () => {
        const calendar = earthCalendar();
        const snapshot = buildCalendarRegistrySnapshot({
            calendar,
            events: [{
                id: 'event-1',
                calendarId: calendar.id,
                title: 'Arrival',
                date: { year: 2020, monthIndex: 4, dayIndex: 7 },
            }],
            builtAt: 88,
        });

        expect(isEarthCompatibleCalendar(calendar)).toBe(true);
        expect(snapshot.calendar.mode).toBe('realEpochCompatible');
        expect(snapshot.summary.realCompatibleAnchorCount).toBe(1);
        expect(snapshot.anchors[0]).toMatchObject({
            realEpochMs: 1588896000000,
            realIntervalEndMs: 1588982399999,
            displayDate: '8 May, 2020 CE',
        });
    });

    it('does not treat Earth-named 30-day calendars as real Gregorian calendars', () => {
        const calendar = customCalendar({
            id: 'cal-earthish',
            name: 'Earth Calendar',
            months: [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December',
            ].map((name, index) => ({
                id: `mo-${index}`,
                index,
                name,
                shortName: name.slice(0, 3),
                days: 30,
            })),
        });

        expect(isEarthCompatibleCalendar(calendar)).toBe(false);
        expect(buildCalendarRegistrySnapshot({ calendar, builtAt: 1 }).calendar.mode).toBe('customOrdinal');
    });

    it('keeps fingerprints stable until date interpretation changes', () => {
        const left = customCalendar();
        const right = customCalendar();
        const changed = customCalendar({
            months: left.months.map(month => month.index === 0 ? { ...month, days: 31 } : month),
        });

        expect(calendarDefinitionFingerprint(left)).toBe(calendarDefinitionFingerprint(right));
        expect(calendarDefinitionFingerprint(left)).not.toBe(calendarDefinitionFingerprint(changed));
    });

    it('calculates ordinals across no-year-zero calendar boundaries', () => {
        const calendar = customCalendar();

        expect(fantasyDateOrdinal(calendar, { year: 1, monthIndex: 0, dayIndex: 0 })).toBe(0);
        expect(fantasyDateOrdinal(calendar, { year: 1, monthIndex: 1, dayIndex: 0 })).toBe(30);
        expect(fantasyDateOrdinal(calendar, { year: 2, monthIndex: 0, dayIndex: 0 })).toBe(360);
        expect(fantasyDateOrdinal(calendar, { year: -1, monthIndex: 0, dayIndex: 0 })).toBe(-360);

        const invalid = buildCalendarRegistrySnapshot({
            calendar,
            events: [{
                id: 'event-zero',
                calendarId: calendar.id,
                title: 'Impossible Year',
                date: { year: 0, monthIndex: 0, dayIndex: 0 },
            }],
            builtAt: 2,
        });
        expect(invalid.summary.anchorCount).toBe(0);
        expect(invalid.summary.diagnostics).toEqual({ invalid_event_date: 1 });
    });
});

function customCalendar(overrides: Partial<CalendarDefinition> = {}): CalendarDefinition {
    return {
        id: 'cal-custom',
        name: 'Custom Calendar',
        hoursPerDay: 24,
        minutesPerHour: 60,
        secondsPerMinute: 60,
        weekdays: Array.from({ length: 7 }, (_, index) => ({
            id: `wd-${index}`,
            index,
            name: `Day ${index + 1}`,
            shortName: `D${index + 1}`,
        })),
        months: Array.from({ length: 12 }, (_, index) => ({
            id: `mo-${index}`,
            index,
            name: `Month ${index + 1}`,
            shortName: `M${index + 1}`,
            days: 30,
        })),
        defaultEraId: 'era-1',
        eras: [{ id: 'era-1', name: 'Common Era', abbreviation: 'CE', startYear: 1, direction: 'ascending' }],
        epochs: [],
        timeMarkers: [],
        hasYearZero: false,
        moons: [],
        seasons: [],
        createdFrom: 'manual',
        ...overrides,
    };
}

function earthCalendar(): CalendarDefinition {
    const monthNames = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
    ];
    const days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    return customCalendar({
        id: 'cal-earth',
        name: 'Earth Calendar',
        months: monthNames.map((name, index) => ({
            id: `mo-${index}`,
            index,
            name,
            shortName: name.slice(0, 3),
            days: days[index],
            leapDayRule: index === 1 ? { interval: 4, daysToAdd: 1 } : undefined,
        })),
    });
}

function datedFolder(id: string, date: { year: number; monthIndex: number; dayIndex: number }): Folder {
    return {
        id,
        worldId: 'world-1',
        name: 'Act Folder',
        parentId: 'narr-1',
        entityKind: 'ACT',
        entitySubtype: '',
        entityLabel: '',
        color: '',
        isTypedRoot: true,
        isSubtypeRoot: false,
        collapsed: false,
        ownerId: 'local',
        createdAt: 1,
        updatedAt: 1,
        narrativeId: 'narr-1',
        isNarrativeRoot: false,
        metadata: { date },
        order: 1000,
    };
}
