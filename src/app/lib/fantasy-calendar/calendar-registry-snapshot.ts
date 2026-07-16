import type { Folder } from '../dexie/db';
import type {
    CalendarDefinition,
    CalendarEvent,
    FantasyDate,
    Period,
    TimeMarker,
} from './types';
import { formatFantasyDate, formatYearWithEra, getDaysInMonth } from './utils';

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;

export type CalendarRegistryMode = 'realEpochCompatible' | 'customOrdinal';
export type CalendarRegistryGranularity = 'year' | 'month' | 'day' | 'hour' | 'minute' | 'period';
export type CalendarRegistryAnchorKind =
    | 'user_calendar_event'
    | 'user_calendar_folder'
    | 'user_calendar_period'
    | 'calendar_time_marker'
    | 'calendar_now_marker';

export interface CalendarRegistryScope {
    kind?: string;
    scopeId?: string;
    narrativeId?: string;
    folderId?: string;
    noteIds?: string[];
}

export interface CalendarRegistrySnapshotInput {
    calendar: CalendarDefinition;
    periods?: Period[];
    events?: CalendarEvent[];
    datedFolders?: Folder[];
    scope?: CalendarRegistryScope;
    builtAt?: number;
}

export interface CalendarRegistryCalendarReceipt {
    id: string;
    name: string;
    fingerprint: string;
    mode: CalendarRegistryMode;
    createdFrom: CalendarDefinition['createdFrom'];
    monthCount: number;
    weekdayCount: number;
    hasYearZero: boolean;
    defaultEraId: string;
}

export interface CalendarRegistryAnchor {
    id: string;
    kind: CalendarRegistryAnchorKind;
    sourceId: string;
    sourceLabel: string;
    calendarId: string;
    calendarFingerprint: string;
    dateKey: string;
    endDateKey?: string;
    normalizedValue: string;
    displayDate: string;
    granularity: CalendarRegistryGranularity;
    date: Partial<FantasyDate>;
    endDate?: Partial<FantasyDate>;
    ordinal: number;
    endOrdinal?: number;
    realEpochMs?: number;
    realIntervalEndMs?: number;
    noteId?: string;
    folderId?: string;
    narrativeId?: string;
    description?: string;
    status?: string;
    confidence: number;
    evidenceRefs: string[];
    attributes: Record<string, unknown>;
}

export interface CalendarRegistrySummary {
    anchorCount: number;
    eventAnchorCount: number;
    folderAnchorCount: number;
    periodAnchorCount: number;
    markerAnchorCount: number;
    realCompatibleAnchorCount: number;
    customOrdinalAnchorCount: number;
    sourceKindCounts: Record<string, number>;
    diagnostics: Record<string, number>;
    firstOrdinal?: number;
    lastOrdinal?: number;
}

export interface CalendarRegistrySnapshot {
    schemaVersion: 'phoenix-calendar-registry/v1';
    id: string;
    builtAt: number;
    calendar: CalendarRegistryCalendarReceipt;
    scope?: CalendarRegistryScope;
    anchors: CalendarRegistryAnchor[];
    summary: CalendarRegistrySummary;
}

export function buildCalendarRegistrySnapshot(input: CalendarRegistrySnapshotInput): CalendarRegistrySnapshot {
    const builtAt = input.builtAt ?? Date.now();
    const calendar = input.calendar;
    const fingerprint = calendarDefinitionFingerprint(calendar);
    const mode: CalendarRegistryMode = isEarthCompatibleCalendar(calendar)
        ? 'realEpochCompatible'
        : 'customOrdinal';
    const diagnostics: Record<string, number> = {};
    const anchors: CalendarRegistryAnchor[] = [];

    for (const event of [...(input.events || [])].sort(byId)) {
        const anchor = eventAnchor(calendar, fingerprint, mode, event, diagnostics);
        if (anchor) anchors.push(anchor);
    }
    for (const folder of [...(input.datedFolders || [])].sort(byId)) {
        const anchor = folderAnchor(calendar, fingerprint, mode, folder, diagnostics);
        if (anchor) anchors.push(anchor);
    }
    for (const period of [...(input.periods || [])].sort(byId)) {
        const anchor = periodAnchor(calendar, fingerprint, mode, period, diagnostics);
        if (anchor) anchors.push(anchor);
    }
    for (const marker of [...calendar.timeMarkers].sort(byId)) {
        const anchor = timeMarkerAnchor(calendar, fingerprint, mode, marker, diagnostics);
        if (anchor) anchors.push(anchor);
    }
    if (calendar.currentDate) {
        const anchor = currentDateAnchor(calendar, fingerprint, mode, diagnostics);
        if (anchor) anchors.push(anchor);
    }

    anchors.sort((left, right) =>
        left.ordinal - right.ordinal
        || left.kind.localeCompare(right.kind)
        || left.id.localeCompare(right.id)
    );

    return {
        schemaVersion: 'phoenix-calendar-registry/v1',
        id: stableId('calendar-registry', [
            calendar.id,
            fingerprint,
            input.scope?.scopeId || '',
            String(builtAt),
        ]),
        builtAt,
        calendar: {
            id: calendar.id,
            name: calendar.name,
            fingerprint,
            mode,
            createdFrom: calendar.createdFrom,
            monthCount: calendar.months.length,
            weekdayCount: calendar.weekdays.length,
            hasYearZero: calendar.hasYearZero,
            defaultEraId: calendar.defaultEraId,
        },
        scope: input.scope ? cloneDefined(input.scope) : undefined,
        anchors,
        summary: summarize(anchors, diagnostics),
    };
}

export function calendarDefinitionFingerprint(calendar: CalendarDefinition): string {
    return stableId('calfp', [stableJson({
        id: calendar.id,
        name: calendar.name,
        hoursPerDay: calendar.hoursPerDay,
        minutesPerHour: calendar.minutesPerHour,
        secondsPerMinute: calendar.secondsPerMinute,
        weekdays: calendar.weekdays,
        months: calendar.months,
        defaultEraId: calendar.defaultEraId,
        eras: calendar.eras,
        epochs: calendar.epochs,
        timeMarkers: calendar.timeMarkers,
        hasYearZero: calendar.hasYearZero,
        moons: calendar.moons,
        seasons: calendar.seasons,
        createdFrom: calendar.createdFrom,
        orbitalMechanics: calendar.orbitalMechanics,
    })]);
}

export function calendarDateKey(calendar: CalendarDefinition, date: Partial<FantasyDate>): string {
    const era = date.eraId || calendar.defaultEraId || 'default';
    const parts = [`cal:${calendar.id}`, `era:${era}`, `y:${date.year ?? '*'}`];
    if (date.monthIndex !== undefined) parts.push(`m:${date.monthIndex + 1}`);
    if (date.dayIndex !== undefined) parts.push(`d:${date.dayIndex + 1}`);
    if (date.hour !== undefined) parts.push(`h:${date.hour}`);
    if (date.minute !== undefined) parts.push(`min:${date.minute}`);
    return parts.join(':');
}

export function fantasyDateOrdinal(calendar: CalendarDefinition, date: FantasyDate): number {
    const epochYear = calendar.hasYearZero ? 0 : 1;
    let days = 0;
    if (date.year >= epochYear) {
        for (let year = epochYear; year < date.year; year += 1) {
            if (!calendar.hasYearZero && year === 0) continue;
            days += getDaysInYear(calendar, year);
        }
    } else {
        for (let year = date.year; year < epochYear; year += 1) {
            if (!calendar.hasYearZero && year === 0) continue;
            days -= getDaysInYear(calendar, year);
        }
    }
    for (let month = 0; month < date.monthIndex; month += 1) {
        days += getDaysInMonth(calendar.months[month], date.year);
    }
    return days + date.dayIndex;
}

export function isEarthCompatibleCalendar(calendar: CalendarDefinition): boolean {
    const monthNames = [
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december',
    ];
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (calendar.months.length !== 12 || calendar.weekdays.length !== 7) return false;
    return calendar.months.every((month, index) => {
        const leap = month.leapDayRule;
        const leapOk = index !== 1
            ? leap === undefined
            : !!leap && leap.interval === 4 && leap.daysToAdd === 1;
        return month.name.toLowerCase() === monthNames[index]
            && month.days === monthDays[index]
            && leapOk;
    });
}

function eventAnchor(
    calendar: CalendarDefinition,
    fingerprint: string,
    mode: CalendarRegistryMode,
    event: CalendarEvent,
    diagnostics: Record<string, number>,
): CalendarRegistryAnchor | null {
    if (!isValidDate(calendar, event.date)) {
        bump(diagnostics, 'invalid_event_date');
        return null;
    }
    const endDate = event.endDate && isValidDate(calendar, event.endDate) ? event.endDate : undefined;
    const date = dateFacts(calendar, mode, event.date, endDate);
    return baseAnchor(calendar, fingerprint, mode, {
        kind: 'user_calendar_event',
        sourceId: event.id,
        sourceLabel: event.title || 'Untitled Event',
        description: event.description,
        noteId: event.sourceNoteId,
        date,
        status: event.status,
        confidence: 0.96,
        evidenceRefs: [
            `calendar:event:${event.id}`,
            ...(event.sourceNoteId ? [`note:${event.sourceNoteId}`] : []),
        ],
        attributes: cloneDefined({
            category: event.category,
            importance: event.importance,
            eventTypeId: event.eventTypeId,
            type: event.type,
            tags: event.tags,
            periodId: event.periodId,
            entityId: event.entityId,
            entityKind: event.entityKind,
        }),
    });
}

function folderAnchor(
    calendar: CalendarDefinition,
    fingerprint: string,
    mode: CalendarRegistryMode,
    folder: Folder,
    diagnostics: Record<string, number>,
): CalendarRegistryAnchor | null {
    const date = folder.metadata?.date;
    if (!date || !isValidDate(calendar, date)) {
        bump(diagnostics, 'invalid_folder_date');
        return null;
    }
    return baseAnchor(calendar, fingerprint, mode, {
        kind: 'user_calendar_folder',
        sourceId: folder.id,
        sourceLabel: folder.name || 'Untitled Folder',
        folderId: folder.id,
        narrativeId: folder.narrativeId,
        date: dateFacts(calendar, mode, date),
        confidence: 0.98,
        evidenceRefs: [`calendar:folder:${folder.id}`, `folder:${folder.id}`],
        attributes: cloneDefined({
            entityKind: folder.entityKind,
            parentId: folder.parentId,
            worldId: folder.worldId,
        }),
    });
}

function periodAnchor(
    calendar: CalendarDefinition,
    fingerprint: string,
    mode: CalendarRegistryMode,
    period: Period,
    diagnostics: Record<string, number>,
): CalendarRegistryAnchor | null {
    const start = {
        year: period.startYear,
        monthIndex: period.startMonth ?? 0,
        dayIndex: 0,
    };
    if (!isValidDate(calendar, start)) {
        bump(diagnostics, 'invalid_period_start');
        return null;
    }
    const end = period.endYear === undefined ? undefined : {
        year: period.endYear,
        monthIndex: period.endMonth ?? calendar.months.length - 1,
        dayIndex: getDaysInMonth(calendar.months[period.endMonth ?? calendar.months.length - 1], period.endYear) - 1,
    };
    if (end && !isValidDate(calendar, end)) {
        bump(diagnostics, 'invalid_period_end');
        return null;
    }
    return baseAnchor(calendar, fingerprint, mode, {
        kind: 'user_calendar_period',
        sourceId: period.id,
        sourceLabel: period.name || 'Untitled Period',
        description: period.summary || period.description,
        date: dateFacts(calendar, mode, start, end, period.startMonth === undefined ? 'year' : 'month'),
        confidence: 0.94,
        evidenceRefs: [`calendar:period:${period.id}`],
        attributes: cloneDefined({
            periodType: period.periodType,
            parentPeriodId: period.parentPeriodId,
            arcType: period.arcType,
            dominantTheme: period.dominantTheme,
        }),
    });
}

function timeMarkerAnchor(
    calendar: CalendarDefinition,
    fingerprint: string,
    mode: CalendarRegistryMode,
    marker: TimeMarker,
    diagnostics: Record<string, number>,
): CalendarRegistryAnchor | null {
    const date = {
        year: marker.year,
        monthIndex: marker.monthIndex ?? 0,
        dayIndex: marker.dayIndex ?? 0,
        eraId: marker.eraId,
    };
    if (!isValidDate(calendar, date)) {
        bump(diagnostics, 'invalid_time_marker_date');
        return null;
    }
    return baseAnchor(calendar, fingerprint, mode, {
        kind: 'calendar_time_marker',
        sourceId: marker.id,
        sourceLabel: marker.name,
        description: marker.description,
        date: dateFacts(calendar, mode, date, undefined, marker.dayIndex !== undefined ? 'day' : marker.monthIndex !== undefined ? 'month' : 'year'),
        confidence: 0.9,
        evidenceRefs: [`calendar:marker:${marker.id}`],
        attributes: cloneDefined({
            importance: marker.importance,
            color: marker.color,
        }),
    });
}

function currentDateAnchor(
    calendar: CalendarDefinition,
    fingerprint: string,
    mode: CalendarRegistryMode,
    diagnostics: Record<string, number>,
): CalendarRegistryAnchor | null {
    const date = calendar.currentDate;
    if (!date || !isValidDate(calendar, date)) {
        bump(diagnostics, 'invalid_current_date');
        return null;
    }
    return baseAnchor(calendar, fingerprint, mode, {
        kind: 'calendar_now_marker',
        sourceId: `${calendar.id}:currentDate`,
        sourceLabel: 'Current Date',
        date: dateFacts(calendar, mode, date),
        confidence: 0.88,
        evidenceRefs: [`calendar:${calendar.id}:currentDate`],
        attributes: {},
    });
}

function dateFacts(
    calendar: CalendarDefinition,
    mode: CalendarRegistryMode,
    date: FantasyDate,
    endDate?: FantasyDate,
    granularity: CalendarRegistryGranularity = date.minute !== undefined ? 'minute' : date.hour !== undefined ? 'hour' : 'day',
) {
    const startMs = mode === 'realEpochCompatible' ? realEpochMs(calendar, date) : undefined;
    const endMs = mode === 'realEpochCompatible'
        ? realEpochMs(calendar, endDate || date)
        : undefined;
    return {
        date,
        endDate,
        dateKey: calendarDateKey(calendar, date),
        endDateKey: endDate ? calendarDateKey(calendar, endDate) : undefined,
        displayDate: formatFantasyDate(calendar, date),
        normalizedValue: `CAL:${calendar.id}:${calendarDateKey(calendar, date)}`,
        granularity,
        ordinal: fantasyDateOrdinal(calendar, date),
        endOrdinal: endDate ? fantasyDateOrdinal(calendar, endDate) : undefined,
        realEpochMs: startMs,
        realIntervalEndMs: endMs === undefined
            ? undefined
            : endMs + realIntervalDurationMs(granularity) - 1,
    };
}

function baseAnchor(
    calendar: CalendarDefinition,
    fingerprint: string,
    mode: CalendarRegistryMode,
    input: {
        kind: CalendarRegistryAnchorKind;
        sourceId: string;
        sourceLabel: string;
        date: ReturnType<typeof dateFacts>;
        description?: string;
        noteId?: string;
        folderId?: string;
        narrativeId?: string;
        status?: string;
        confidence: number;
        evidenceRefs: string[];
        attributes: Record<string, unknown>;
    },
): CalendarRegistryAnchor {
    return {
        id: stableId('calanchor', [fingerprint, input.kind, input.sourceId, input.date.dateKey]),
        kind: input.kind,
        sourceId: input.sourceId,
        sourceLabel: input.sourceLabel,
        calendarId: calendar.id,
        calendarFingerprint: fingerprint,
        dateKey: input.date.dateKey,
        endDateKey: input.date.endDateKey,
        normalizedValue: input.date.normalizedValue,
        displayDate: input.date.displayDate,
        granularity: input.date.granularity,
        date: cloneDefined(input.date.date),
        endDate: input.date.endDate ? cloneDefined(input.date.endDate) : undefined,
        ordinal: input.date.ordinal,
        endOrdinal: input.date.endOrdinal,
        realEpochMs: input.date.realEpochMs,
        realIntervalEndMs: input.date.realIntervalEndMs,
        noteId: input.noteId,
        folderId: input.folderId,
        narrativeId: input.narrativeId,
        description: input.description,
        status: input.status,
        confidence: input.confidence,
        evidenceRefs: input.evidenceRefs,
        attributes: input.attributes,
    };
}

function summarize(
    anchors: CalendarRegistryAnchor[],
    diagnostics: Record<string, number>,
): CalendarRegistrySummary {
    const sourceKindCounts: Record<string, number> = {};
    let realCompatibleAnchorCount = 0;
    for (const anchor of anchors) {
        bump(sourceKindCounts, anchor.kind);
        if (anchor.realEpochMs !== undefined) realCompatibleAnchorCount += 1;
    }
    const ordinals = anchors.map(anchor => anchor.ordinal);
    return {
        anchorCount: anchors.length,
        eventAnchorCount: sourceKindCounts['user_calendar_event'] || 0,
        folderAnchorCount: sourceKindCounts['user_calendar_folder'] || 0,
        periodAnchorCount: sourceKindCounts['user_calendar_period'] || 0,
        markerAnchorCount: (sourceKindCounts['calendar_time_marker'] || 0) + (sourceKindCounts['calendar_now_marker'] || 0),
        realCompatibleAnchorCount,
        customOrdinalAnchorCount: anchors.length - realCompatibleAnchorCount,
        sourceKindCounts,
        diagnostics,
        firstOrdinal: ordinals.length ? Math.min(...ordinals) : undefined,
        lastOrdinal: ordinals.length ? Math.max(...ordinals) : undefined,
    };
}

function isValidDate(calendar: CalendarDefinition, date: Partial<FantasyDate>): date is FantasyDate {
    return typeof date.year === 'number'
        && typeof date.monthIndex === 'number'
        && typeof date.dayIndex === 'number'
        && (calendar.hasYearZero || date.year !== 0)
        && date.monthIndex >= 0
        && date.monthIndex < calendar.months.length
        && date.dayIndex >= 0
        && date.dayIndex < getDaysInMonth(calendar.months[date.monthIndex], date.year)
        && (date.hour === undefined || (date.hour >= 0 && date.hour < calendar.hoursPerDay))
        && (date.minute === undefined || (date.minute >= 0 && date.minute < calendar.minutesPerHour));
}

function realEpochMs(calendar: CalendarDefinition, date: FantasyDate): number {
    const month = date.monthIndex + 1;
    const day = date.dayIndex + 1;
    return daysFromCivil(date.year, month, day) * DAY_MS
        + (date.hour || 0) * HOUR_MS
        + (date.minute || 0) * MINUTE_MS;
}

function realIntervalDurationMs(granularity: CalendarRegistryGranularity): number {
    if (granularity === 'minute') return MINUTE_MS;
    if (granularity === 'hour') return HOUR_MS;
    return DAY_MS;
}

function getDaysInYear(calendar: CalendarDefinition, year: number): number {
    return calendar.months.reduce((sum, month) => sum + getDaysInMonth(month, year), 0);
}

function daysFromCivil(year: number, month: number, day: number): number {
    const y = year - (month <= 2 ? 1 : 0);
    const era = Math.trunc((y >= 0 ? y : y - 399) / 400);
    const yoe = y - era * 400;
    const shiftedMonth = month + (month > 2 ? -3 : 9);
    const doy = Math.trunc((153 * shiftedMonth + 2) / 5) + day - 1;
    const doe = yoe * 365 + Math.trunc(yoe / 4) - Math.trunc(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
}

function stableId(prefix: string, parts: string[]): string {
    let hash = 0xcbf29ce484222325n;
    for (const part of parts) {
        for (let index = 0; index < part.length; index += 1) {
            hash ^= BigInt(part.charCodeAt(index) & 0xff);
            hash = BigInt.asUintN(64, hash * 0x100000001b3n);
        }
        hash ^= 0xffn;
        hash = BigInt.asUintN(64, hash * 0x100000001b3n);
    }
    return `${prefix}:${hash.toString(16).padStart(16, '0')}`;
}

function stableJson(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
    if (!value || typeof value !== 'object') return JSON.stringify(value);
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object)
        .filter(key => object[key] !== undefined)
        .sort()
        .map(key => `${JSON.stringify(key)}:${stableJson(object[key])}`)
        .join(',')}}`;
}

function cloneDefined<T extends object>(value: T): T {
    return Object.fromEntries(
        Object.entries(value).filter(([, item]) => item !== undefined)
    ) as T;
}

function byId(left: { id: string }, right: { id: string }): number {
    return left.id.localeCompare(right.id);
}

function bump(counts: Record<string, number>, key: string): void {
    counts[key] = (counts[key] || 0) + 1;
}

export function formatCalendarRegistryYear(calendar: CalendarDefinition, year: number, eraId?: string): string {
    return formatYearWithEra(calendar, year, eraId);
}
