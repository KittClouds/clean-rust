import { describe, expect, it } from 'vitest';

import {
    cachedEditorBodyMatchesAuthoritativeHeader,
    canRevealCachedEditorNote,
    createSessionPositionFromLegacy,
    getFallbackActiveNoteIdFromTabs,
    normalizeEditorSessionState,
    normalizeLegacyEditorPosition,
    shouldRestoreStoredPosition,
} from './note-editor-session';

describe('note editor session helpers', () => {
    it('normalizes compact v2 editor session state', () => {
        const session = normalizeEditorSessionState({
            activeNoteId: 'note-1',
            position: {
                noteId: 'note-1',
                anchor: 12,
                head: 15,
                scrollTop: 42,
                noteVersion: 99,
                noteUpdatedAt: 1234,
                savedAt: 5678,
            },
        });

        expect(session).toEqual({
            activeNoteId: 'note-1',
            position: {
                noteId: 'note-1',
                anchor: 12,
                head: 15,
                scrollTop: 42,
                noteVersion: 99,
                noteUpdatedAt: 1234,
                savedAt: 5678,
            },
        });
    });

    it('drops positions that point at a different note than the active note', () => {
        const session = normalizeEditorSessionState({
            activeNoteId: 'note-2',
            position: {
                noteId: 'note-1',
                anchor: 1,
                head: 1,
                scrollTop: 0,
                noteUpdatedAt: 100,
                savedAt: 100,
            },
        });

        expect(session).toEqual({ activeNoteId: 'note-2' });
    });

    it('migrates legacy cursor payloads into the v2 shape using note metadata', () => {
        const legacyPosition = normalizeLegacyEditorPosition({
            noteId: 'note-1',
            scrollTop: 24,
            cursorFrom: 7,
            cursorTo: 9,
        });

        expect(legacyPosition).toBeDefined();
        expect(createSessionPositionFromLegacy(legacyPosition!, {
            id: 'note-1',
            version: 123,
            updatedAt: 456,
        }, 789)).toEqual({
            noteId: 'note-1',
            anchor: 7,
            head: 9,
            scrollTop: 24,
            noteVersion: 123,
            noteUpdatedAt: 456,
            savedAt: 789,
        });
    });

    it('restores stored positions only when version or updatedAt still matches', () => {
        expect(shouldRestoreStoredPosition({
            noteId: 'note-1',
            anchor: 4,
            head: 4,
            scrollTop: 8,
            noteVersion: 12,
            noteUpdatedAt: 100,
            savedAt: 200,
        }, {
            id: 'note-1',
            version: 12,
            updatedAt: 999,
        })).toBe(true);

        expect(shouldRestoreStoredPosition({
            noteId: 'note-1',
            anchor: 4,
            head: 4,
            scrollTop: 8,
            noteUpdatedAt: 100,
            savedAt: 200,
        }, {
            id: 'note-1',
            updatedAt: 100,
        })).toBe(true);

        expect(shouldRestoreStoredPosition({
            noteId: 'note-1',
            anchor: 4,
            head: 4,
            scrollTop: 8,
            noteVersion: 11,
            noteUpdatedAt: 100,
            savedAt: 200,
        }, {
            id: 'note-1',
            version: 12,
            updatedAt: 100,
        })).toBe(false);
    });

    it('falls back to the active persisted tab when there is no editor session yet', () => {
        expect(getFallbackActiveNoteIdFromTabs([
            { noteId: 'note-1', active: false },
            { noteId: 'note-2', active: true },
        ])).toBe('note-2');

        expect(getFallbackActiveNoteIdFromTabs([
            { noteId: 'note-1', active: false },
        ])).toBe('note-1');
    });

    it('reveals only complete cached bodies and retains them only at authoritative revision parity', () => {
        const cached = { id: 'note-1', version: 12, updatedAt: 100, hasBody: true };

        expect(canRevealCachedEditorNote(cached)).toBe(true);
        expect(canRevealCachedEditorNote({ ...cached, hasBody: false })).toBe(false);
        expect(cachedEditorBodyMatchesAuthoritativeHeader(
            { id: 'note-1', version: 12, updatedAt: 999 },
            cached,
        )).toBe(true);
        expect(cachedEditorBodyMatchesAuthoritativeHeader(
            { id: 'note-1', version: 13, updatedAt: 100 },
            cached,
        )).toBe(false);
    });
});
