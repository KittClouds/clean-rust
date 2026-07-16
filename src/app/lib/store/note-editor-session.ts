export const EDITOR_SESSION_KEY = 'kittclouds-editor-session-v2';
export const LEGACY_ACTIVE_NOTE_KEY = 'kittclouds-active-note';
export const LEGACY_EDITOR_POSITION_KEY = 'kittclouds-editor-position';
export const OPEN_TABS_STORAGE_KEY = 'kittclouds-open-tabs';

export interface StoredEditorPosition {
    noteId: string;
    anchor: number;
    head: number;
    scrollTop: number;
    noteVersion?: number;
    noteUpdatedAt: number;
    savedAt: number;
}

export interface EditorSessionState {
    activeNoteId: string | null;
    position?: StoredEditorPosition;
}

export interface EditorSessionNoteMeta {
    id: string;
    version?: number;
    updatedAt: number;
}

export interface CachedEditorNoteMeta extends EditorSessionNoteMeta {
    hasBody?: boolean;
}

export interface LegacyEditorPosition {
    noteId: string;
    scrollTop: number;
    cursorFrom: number;
    cursorTo: number;
}

interface PersistedTabLike {
    noteId?: unknown;
    active?: unknown;
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' ? value as Record<string, unknown> : null;
}

function asFiniteNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asOptionalPositiveNumber(value: unknown): number | undefined {
    const parsed = asFiniteNumber(value);
    return parsed !== null && parsed > 0 ? parsed : undefined;
}

function asOptionalString(value: unknown): string | null {
    return typeof value === 'string' && value.trim().length > 0 ? value : null;
}

export function normalizeStoredEditorPosition(value: unknown): StoredEditorPosition | undefined {
    const record = asRecord(value);
    if (!record) {
        return undefined;
    }

    const noteId = asOptionalString(record['noteId']);
    const anchor = asFiniteNumber(record['anchor']);
    const head = asFiniteNumber(record['head']);
    const scrollTop = asFiniteNumber(record['scrollTop']);
    const noteUpdatedAt = asFiniteNumber(record['noteUpdatedAt']);
    const savedAt = asFiniteNumber(record['savedAt']);

    if (!noteId || anchor === null || head === null || scrollTop === null || noteUpdatedAt === null || savedAt === null) {
        return undefined;
    }

    return {
        noteId,
        anchor,
        head,
        scrollTop,
        noteVersion: asOptionalPositiveNumber(record['noteVersion']),
        noteUpdatedAt,
        savedAt,
    };
}

export function normalizeEditorSessionState(value: unknown): EditorSessionState | null {
    const record = asRecord(value);
    if (!record || !('activeNoteId' in record)) {
        return null;
    }

    const activeNoteIdRaw = record['activeNoteId'];
    const activeNoteId = activeNoteIdRaw === null ? null : asOptionalString(activeNoteIdRaw);
    if (activeNoteIdRaw !== null && activeNoteId === null) {
        return null;
    }

    const position = normalizeStoredEditorPosition(record['position']);
    if (position && position.noteId !== activeNoteId) {
        return { activeNoteId };
    }

    return position ? { activeNoteId, position } : { activeNoteId };
}

export function normalizeLegacyEditorPosition(value: unknown): LegacyEditorPosition | undefined {
    const record = asRecord(value);
    if (!record) {
        return undefined;
    }

    const noteId = asOptionalString(record['noteId']);
    const scrollTop = asFiniteNumber(record['scrollTop']);
    const cursorFrom = asFiniteNumber(record['cursorFrom']);
    const cursorTo = asFiniteNumber(record['cursorTo']);

    if (!noteId || scrollTop === null || cursorFrom === null || cursorTo === null) {
        return undefined;
    }

    return {
        noteId,
        scrollTop,
        cursorFrom,
        cursorTo,
    };
}

export function createSessionPositionFromLegacy(
    position: LegacyEditorPosition,
    note: EditorSessionNoteMeta,
    savedAt = Date.now(),
): StoredEditorPosition {
    return {
        noteId: position.noteId,
        anchor: position.cursorFrom,
        head: position.cursorTo,
        scrollTop: position.scrollTop,
        noteVersion: note.version,
        noteUpdatedAt: note.updatedAt,
        savedAt,
    };
}

export function shouldRestoreStoredPosition(
    position: StoredEditorPosition | undefined,
    note: EditorSessionNoteMeta,
): position is StoredEditorPosition {
    if (!position || position.noteId !== note.id) {
        return false;
    }

    const currentVersion = typeof note.version === 'number' && Number.isFinite(note.version) && note.version > 0
        ? note.version
        : undefined;
    const storedVersion = typeof position.noteVersion === 'number' && Number.isFinite(position.noteVersion) && position.noteVersion > 0
        ? position.noteVersion
        : undefined;

    if (currentVersion !== undefined && storedVersion !== undefined) {
        return currentVersion === storedVersion;
    }

    return position.noteUpdatedAt === note.updatedAt;
}

export function canRevealCachedEditorNote(
    note: CachedEditorNoteMeta | null | undefined,
): note is CachedEditorNoteMeta & { hasBody: true } {
    return note?.hasBody === true;
}

export function cachedEditorBodyMatchesAuthoritativeHeader(
    authoritative: EditorSessionNoteMeta,
    cached: CachedEditorNoteMeta | null | undefined,
): boolean {
    if (!canRevealCachedEditorNote(cached) || cached.id !== authoritative.id) {
        return false;
    }
    const authoritativeRevision = authoritative.version ?? authoritative.updatedAt;
    const cachedRevision = cached.version ?? cached.updatedAt;
    return authoritativeRevision === cachedRevision;
}

export function getFallbackActiveNoteIdFromTabs(value: unknown): string | null {
    if (!Array.isArray(value) || value.length === 0) {
        return null;
    }

    const tabs = value as PersistedTabLike[];
    const activeTab = tabs.find((tab) => tab?.active === true && typeof tab.noteId === 'string' && tab.noteId.trim().length > 0);
    if (activeTab?.noteId && typeof activeTab.noteId === 'string') {
        return activeTab.noteId;
    }

    const firstTab = tabs.find((tab) => typeof tab?.noteId === 'string' && tab.noteId.trim().length > 0);
    return firstTab?.noteId && typeof firstTab.noteId === 'string' ? firstTab.noteId : null;
}
