// src/app/lib/store/note-editor.store.ts
// Single source of truth for the currently active note
// Uses signals + Dexie liveQuery for reactive state
// INCLUDES: Dexie settings persistence for active note and lightweight editor session

import { Injectable, signal, computed, effect, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { Observable, Subject, from, of, switchMap, debounceTime, distinctUntilChanged } from 'rxjs';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { liveQuery, Observable as DexieObservable } from 'dexie';
import { db, Note } from '../dexie/db';
import { setSetting, removeSetting } from '../dexie/settings.service';
import * as ops from '../operations';
import {
    type EditorSessionState,
    type LegacyEditorPosition,
    type StoredEditorPosition,
    EDITOR_SESSION_KEY,
    LEGACY_ACTIVE_NOTE_KEY,
    LEGACY_EDITOR_POSITION_KEY,
    OPEN_TABS_STORAGE_KEY,
    canRevealCachedEditorNote,
    createSessionPositionFromLegacy,
    getFallbackActiveNoteIdFromTabs,
    normalizeEditorSessionState,
    normalizeLegacyEditorPosition,
    shouldRestoreStoredPosition,
} from './note-editor-session';

@Injectable({
    providedIn: 'root'
})
export class NoteEditorStore {
    private readonly isBrowser: boolean;
    private editorSessionState: EditorSessionState = { activeNoteId: null };
    private legacyKeysMigrated = false;
    private initialSession: {
        session: EditorSessionState | null;
        fallbackNoteId: string | null;
        legacyPosition?: LegacyEditorPosition;
    } | null = null;

    /** ID of the currently open note (null = no note open) */
    readonly activeNoteId = signal<string | null>(null);

    /** Loading state for UI feedback */
    readonly isLoading = signal(false);

    /** Saving state for UI feedback */
    readonly isSaving = signal(false);

    /** Computed: whether a note is currently open */
    readonly isNoteOpen = computed(() => this.activeNoteId() !== null);

    /** Pending save content (debounced) */
    private saveSubject = new Subject<{ noteId: string; json: object; markdown: string }>();

    /** Cached editor position for restoration */
    private pendingPosition: StoredEditorPosition | null = null;

    /** Flag to prevent clearing storage during initial restoration */
    private isRestoring = true;

    /**
     * Reactive stream of the active note data.
     * Automatically updates when:
     * - activeNoteId changes
     * - The note is modified in Dexie (from any source)
     */
    readonly activeNote$: Observable<Note | undefined> = toObservable(this.activeNoteId).pipe(
        distinctUntilChanged(),
        switchMap(id => {
            if (!id) return of(undefined);
            return from(liveQuery(() => db.notes.get(id)) as DexieObservable<Note | undefined>);
        })
    );

    /** Signal-based accessor for the current note (for signal consumers like AnalyticsPanel) */
    readonly currentNote = toSignal(this.activeNote$, { initialValue: undefined });

    constructor(@Inject(PLATFORM_ID) platformId: Object) {
        this.isBrowser = isPlatformBrowser(platformId);
        console.log('[NoteEditorStore] Constructor called');

        // AppComponent may reveal a revisioned Dexie body immediately, then
        // restoreActiveNote() reconciles it after native hydration completes.

        this.saveSubject.pipe(
            debounceTime(300)
        ).subscribe(async ({ noteId, json, markdown }) => {
            if (this.activeNoteId() !== noteId) {
                console.log(`[NoteEditorStore] Skipped save for ${noteId} (no longer active)`);
                return;
            }
            try {
                const savedNote = await ops.updateNote(noteId, {
                    content: JSON.stringify(json),
                    markdownContent: markdown,
                });
                this.refreshStoredPositionMetadata(savedNote);
                console.log(`[NoteEditorStore] Saved note ${noteId}`);
            } catch (e) {
                console.error('[NoteEditorStore] Failed to save note:', e);
            }
        });

        effect(() => {
            const noteId = this.activeNoteId();
            if (noteId === null && this.isRestoring) {
                console.log('[NoteEditorStore] Skipping editor session update during restoration');
                return;
            }

            this.editorSessionState = this.withActiveNote(noteId);
            this.persistEditorSession();
        });

        effect(() => {
            const note = this.currentNote();
            const position = this.editorSessionState.position;
            if (!note || !position || position.noteId !== note.id) {
                return;
            }

            if (position.noteVersion === note.version && position.noteUpdatedAt === note.updatedAt) {
                return;
            }

            this.editorSessionState = {
                activeNoteId: this.editorSessionState.activeNoteId,
                position: {
                    ...position,
                    noteVersion: note.version,
                    noteUpdatedAt: note.updatedAt,
                },
            };
            this.persistEditorSession();
        });
    }

    /**
     * Reveal a complete cached active note without waiting for native recovery.
     * The authoritative restore still runs after hydration and may replace it.
     */
    async restoreCachedActiveNote(): Promise<boolean> {
        if (!this.isBrowser) return false;

        const resolved = await this.loadInitialEditorSession();
        const targetNoteId = resolved.session?.activeNoteId ?? resolved.fallbackNoteId;
        if (!targetNoteId) return false;

        const cachedNote = await db.notes.get(targetNoteId);
        if (!canRevealCachedEditorNote(cachedNote)) return false;

        const resolvedPosition = this.resolveRestorablePosition(cachedNote, resolved.legacyPosition);
        this.pendingPosition = resolvedPosition;
        this.editorSessionState = resolvedPosition
            ? { activeNoteId: targetNoteId, position: resolvedPosition }
            : { activeNoteId: targetNoteId };
        this.activeNoteId.set(targetNoteId);
        console.log(`[NoteEditorStore] Revealed cached active note: ${targetNoteId}`);
        return true;
    }

    /**
     * Restore the previously-active note from Dexie settings.
     * MUST be called AFTER Dexie hydration from Phoenix is complete.
     */
    async restoreActiveNote(): Promise<void> {
        if (!this.isBrowser) return;

        console.log('[NoteEditorStore] restoreActiveNote: checking settings...');

        try {
            const resolved = await this.loadInitialEditorSession();
            this.editorSessionState = resolved.session ?? { activeNoteId: null };

            const targetNoteId = resolved.session?.activeNoteId ?? resolved.fallbackNoteId;
            console.log(`[NoteEditorStore] restoreActiveNote: target ID = "${targetNoteId}"`);

            if (!targetNoteId) {
                return;
            }

            const noteHeader = await ops.getNoteHeader(targetNoteId);
            if (!noteHeader) {
                console.log(`[NoteEditorStore] Note ${targetNoteId} no longer exists; clearing editor session`);
                this.clearStoredEditorSession();
                this.activeNoteId.set(null);
                return;
            }

            const resolvedPosition = this.resolveRestorablePosition(noteHeader, resolved.legacyPosition);
            this.pendingPosition = resolvedPosition;
            this.editorSessionState = resolvedPosition
                ? { activeNoteId: targetNoteId, position: resolvedPosition }
                : { activeNoteId: targetNoteId };

            await this.activateNote(targetNoteId);
            console.log(`[NoteEditorStore] Restored active note: ${targetNoteId}`);
        } catch (e) {
            console.error('[NoteEditorStore] Restoration failed:', e);
        } finally {
            this.isRestoring = false;
            console.log('[NoteEditorStore] Restoration complete. isRestoring = false');
        }
    }

    /**
     * Get pending position for restoration (consumed once).
     * Called by editor component after loading.
     */
    getPendingPosition(): StoredEditorPosition | null {
        const position = this.pendingPosition;
        this.pendingPosition = null;
        return position;
    }

    async hasStoredActiveNoteIntent(): Promise<boolean> {
        if (!this.isBrowser) return false;
        const resolved = await this.loadInitialEditorSession();
        return Boolean(resolved.session?.activeNoteId ?? resolved.fallbackNoteId);
    }

    /**
     * Save current editor position (called by editor on scroll/cursor change).
     * Debounce this call from the editor side.
     */
    saveEditorPosition(scrollTop: number, anchor: number, head: number, targetNoteId?: string): void {
        if (!this.isBrowser) return;

        const noteId = targetNoteId || this.activeNoteId();
        if (!noteId) return;

        const note = this.currentNote();
        const matchingNote = note?.id === noteId ? note : undefined;
        const existingPosition = this.editorSessionState.position?.noteId === noteId
            ? this.editorSessionState.position
            : undefined;

        this.editorSessionState = {
            activeNoteId: noteId,
            position: {
                noteId,
                scrollTop,
                anchor,
                head,
                noteVersion: matchingNote?.version ?? existingPosition?.noteVersion,
                noteUpdatedAt: matchingNote?.updatedAt ?? existingPosition?.noteUpdatedAt ?? Date.now(),
                savedAt: Date.now(),
            },
        };
        this.persistEditorSession();
    }

    /**
     * Open a note for editing.
     * This sets the activeNoteId, which triggers activeNote$ to emit.
     */
    async openNote(id: string): Promise<void> {
        if (this.activeNoteId() === id) return;

        console.log(`[NoteEditorStore] Opening note: ${id}`);
        this.isLoading.set(true);
        this.pendingPosition = null;
        try {
            await this.activateNote(id);
        } finally {
            setTimeout(() => this.isLoading.set(false), 100);
        }
    }

    /**
     * Close the current note (clear editor).
     */
    closeNote(): void {
        console.log('[NoteEditorStore] Closing note');
        const previousNoteId = this.activeNoteId();
        this.pendingPosition = null;
        this.activeNoteId.set(null);
        if (previousNoteId) {
            void this.releaseNoteBody(previousNoteId);
        }
    }

    /**
     * Queue a content save (debounced).
     * Called by EditorComponent on every document change.
     * Captures noteId at call time to prevent race conditions when switching notes.
     */
    saveContent(json: object, markdown: string): void {
        const noteId = this.activeNoteId();
        if (!noteId) return;
        this.saveSubject.next({ noteId, json, markdown });
    }

    /**
     * Force an immediate save (bypass debounce).
     * Useful for explicit "Save" button or before navigation.
     */
    async saveContentNow(json: object, markdown: string, targetNoteId?: string): Promise<void> {
        const noteId = targetNoteId || this.activeNoteId();
        if (!noteId) return;

        this.isSaving.set(true);
        try {
            const savedNote = await ops.updateNote(noteId, {
                content: JSON.stringify(json),
                markdownContent: markdown,
            });
            this.refreshStoredPositionMetadata(savedNote);
            console.log(`[NoteEditorStore] Force-saved note ${noteId}`);
        } finally {
            this.isSaving.set(false);
        }
    }

    /**
     * Create a new note and immediately open it for editing.
     */
    async createAndOpenNote(folderId: string = '', narrativeId: string = ''): Promise<string> {
        console.log(`[NoteEditorStore] Creating new note in folder: ${folderId || 'root'}`);

        const id = await ops.createNote({
            worldId: '',
            title: 'Untitled Note',
            content: '{}',
            markdownContent: '',
            folderId,
            entityKind: '',
            entitySubtype: '',
            isEntity: false,
            isPinned: false,
            favorite: false,
            ownerId: '',
            narrativeId,
        });

        void this.openNote(id);
        return id;
    }

    /**
     * Update the title of the active note.
     */
    async updateTitle(title: string): Promise<void> {
        const noteId = this.activeNoteId();
        if (!noteId) return;

        const savedNote = await ops.updateNote(noteId, { title });
        this.refreshStoredPositionMetadata(savedNote);
        console.log(`[NoteEditorStore] Updated title: ${title}`);
    }

    /**
     * Rename any note by ID.
     */
    async renameNote(id: string, title: string): Promise<void> {
        const savedNote = await ops.updateNote(id, { title });
        this.refreshStoredPositionMetadata(savedNote);
        console.log(`[NoteEditorStore] Renamed note ${id} to "${title}"`);
    }

    async releaseNoteBody(id: string): Promise<void> {
        if (this.activeNoteId() === id) {
            return;
        }
        await ops.trimNoteBody(id);
    }

    private async activateNote(id: string): Promise<void> {
        const previousNoteId = this.activeNoteId();
        const note = await ops.ensureNoteBodyLoaded(id);
        if (!note) {
            return;
        }
        this.activeNoteId.set(id);
    }

    private withActiveNote(noteId: string | null): EditorSessionState {
        const position = this.editorSessionState.position;
        return {
            activeNoteId: noteId,
            position: position && position.noteId === noteId ? position : undefined,
        };
    }

    private persistEditorSession(): void {
        if (!this.isBrowser) return;
        setSetting(EDITOR_SESSION_KEY, this.editorSessionState);
        if (!this.legacyKeysMigrated) {
            removeSetting(LEGACY_ACTIVE_NOTE_KEY);
            removeSetting(LEGACY_EDITOR_POSITION_KEY);
            this.legacyKeysMigrated = true;
        }
    }

    private clearStoredEditorSession(): void {
        this.pendingPosition = null;
        this.editorSessionState = { activeNoteId: null };
        this.persistEditorSession();
    }

    private refreshStoredPositionMetadata(note: ops.Note | undefined): void {
        if (!note) {
            return;
        }

        const position = this.editorSessionState.position;
        if (!position || position.noteId !== note.id) {
            return;
        }

        this.editorSessionState = {
            activeNoteId: this.editorSessionState.activeNoteId,
            position: {
                ...position,
                noteVersion: note.version,
                noteUpdatedAt: note.updatedAt,
                savedAt: Date.now(),
            },
        };
        this.persistEditorSession();
    }

    private resolveRestorablePosition(note: ops.Note, legacyPosition?: LegacyEditorPosition): StoredEditorPosition | null {
        const sessionPosition = this.editorSessionState.position;
        if (shouldRestoreStoredPosition(sessionPosition, note)) {
            return sessionPosition;
        }

        if (legacyPosition && legacyPosition.noteId === note.id) {
            return createSessionPositionFromLegacy(legacyPosition, note);
        }

        return null;
    }

    private async loadInitialEditorSession(): Promise<{
        session: EditorSessionState | null;
        fallbackNoteId: string | null;
        legacyPosition?: LegacyEditorPosition;
    }> {
        if (this.initialSession) {
            return this.initialSession;
        }
        const sessionSetting = await db.settings.get(EDITOR_SESSION_KEY);
        const normalizedSession = normalizeEditorSessionState(sessionSetting?.value);
        if (normalizedSession) {
            this.legacyKeysMigrated = true;
            this.initialSession = {
                session: normalizedSession,
                fallbackNoteId: null,
            };
            return this.initialSession;
        }

        const legacyActiveSetting = await db.settings.get(LEGACY_ACTIVE_NOTE_KEY);
        const legacyPositionSetting = await db.settings.get(LEGACY_EDITOR_POSITION_KEY);
        const legacyActiveNoteId = typeof legacyActiveSetting?.value === 'string' && legacyActiveSetting.value.trim().length > 0
            ? legacyActiveSetting.value
            : null;
        const legacyPosition = normalizeLegacyEditorPosition(legacyPositionSetting?.value);

        if (legacyActiveNoteId) {
            this.initialSession = {
                session: { activeNoteId: legacyActiveNoteId },
                fallbackNoteId: null,
                legacyPosition,
            };
            return this.initialSession;
        }

        const tabsSetting = await db.settings.get(OPEN_TABS_STORAGE_KEY);
        this.initialSession = {
            session: null,
            fallbackNoteId: getFallbackActiveNoteIdFromTabs(tabsSetting?.value),
        };
        return this.initialSession;
    }
}
