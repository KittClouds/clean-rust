// src/app/lib/services/app-state.service.ts
// Centralized UI state management with Dexie persistence and liveQuery reactivity
// Following: https://dexie.org/docs/liveQuery()#svelte-and-angular

import { Injectable, signal, computed, effect, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { from, Observable } from 'rxjs';
import { toSignal } from '@angular/core/rxjs-interop';
import { liveQuery } from 'dexie';
import { db, UIState, getDefaultUIState, LeftSidebarMode, RightSidebarMode, RightSidebarPanel, SearchMode, CalendarView, ThemePreference, HighlightMode } from '../dexie/db';

const STATE_ID = 'app-state';

function normalizeRightSidebarPanel(panel: string | undefined): RightSidebarPanel {
    switch (panel) {
        case 'analytics':
        case 'timeline':
        case 'ai':
        case 'history':
        case 'entities':
            return panel;
        case 'chat':
            return 'ai';
        default:
            return 'entities';
    }
}

@Injectable({
    providedIn: 'root'
})
export class AppStateService {
    private isBrowser: boolean;

    // ─────────────────────────────────────────────────────────────
    // Reactive State via liveQuery
    // ─────────────────────────────────────────────────────────────

    /**
     * Observable stream of UI state from Dexie.
     * Automatically emits when the state changes in IndexedDB.
     */
    private state$: Observable<UIState | undefined> = from(
        liveQuery(() => db.uiState.get(STATE_ID))
    );

    /**
     * Signal for use in templates and computed values.
     * Falls back to default state if not found.
     */
    private stateSignal = toSignal(this.state$, {
        initialValue: undefined as UIState | undefined
    });
    private localState = signal<UIState | undefined>(undefined);

    // ─────────────────────────────────────────────────────────────
    // Computed State Slices (for convenience)
    // ─────────────────────────────────────────────────────────────

    /** Full state object (with defaults applied) */
    readonly state = computed(() => this.localState() ?? this.stateSignal() ?? getDefaultUIState());

    // Sidebar states
    readonly leftSidebarMode = computed(() => this.state().leftSidebarMode);
    readonly rightSidebarMode = computed(() => this.state().rightSidebarMode);
    readonly rightSidebarActivePanel = computed(() => normalizeRightSidebarPanel(this.state().rightSidebarActivePanel));

    // Panel dimensions
    readonly leftSidebarWidth = computed(() => this.state().leftSidebarWidth);
    readonly rightSidebarWidth = computed(() => this.state().rightSidebarWidth);
    readonly hubHeight = computed(() => this.state().hubHeight);

    // Folder expansion
    readonly expandedFolderIds = computed(() => this.state().expandedFolderIds);
    readonly expandedFoldersSet = computed(() => new Set(this.state().expandedFolderIds));

    // Search state
    readonly searchQuery = computed(() => this.state().searchQuery);
    readonly searchMode = computed(() => this.state().searchMode);
    readonly searchScope = computed(() => this.state().searchScope);

    // Calendar state
    readonly calendarView = computed(() => this.state().calendarView);
    readonly calendarSelectedDate = computed(() => this.state().calendarSelectedDate);

    // Theme
    readonly theme = computed(() => this.state().theme);
    readonly highlightMode = computed(() => this.state().highlightMode);
    readonly focusedEntityKinds = computed(() => this.state().focusedEntityKinds);

    // ─────────────────────────────────────────────────────────────
    // Constructor
    // ─────────────────────────────────────────────────────────────

    constructor(@Inject(PLATFORM_ID) platformId: Object) {
        this.isBrowser = isPlatformBrowser(platformId);

        // Ensure state exists on first run
        if (this.isBrowser) {
            this.ensureStateExists();
        }

        effect(() => {
            const persisted = this.stateSignal();
            if (persisted) {
                const current = this.localState();
                if (!current || persisted.updatedAt >= current.updatedAt) {
                    this.localState.set(persisted);
                }
            }
        });

        effect(() => {
            const panel = this.stateSignal()?.rightSidebarActivePanel;
            const normalized = normalizeRightSidebarPanel(panel);
            if (panel && panel !== normalized) {
                this.updateState({ rightSidebarActivePanel: normalized });
            }
        });
    }

    // ─────────────────────────────────────────────────────────────
    // Private Methods
    // ─────────────────────────────────────────────────────────────

    private async ensureStateExists(): Promise<void> {
        const existing = await db.uiState.get(STATE_ID);
        if (!existing) {
            const defaults = getDefaultUIState();
            this.localState.set(defaults);
            await db.uiState.put(defaults);
            console.log('[AppStateService] Created default UI state');
        }
    }

    /**
     * Update state with partial changes.
     * Merges with existing state and persists to Dexie.
     */
    private async updateState(partial: Partial<UIState>): Promise<void> {
        if (!this.isBrowser) return;

        const updated: UIState = {
            ...this.state(),
            ...partial,
            updatedAt: Date.now()
        };
        this.localState.set(updated);
        await db.uiState.put(updated);
    }

    // ─────────────────────────────────────────────────────────────
    // Public Actions: Sidebar
    // ─────────────────────────────────────────────────────────────

    setLeftSidebarMode(mode: LeftSidebarMode): void {
        this.updateState({ leftSidebarMode: mode });
    }

    toggleLeftSidebar(): void {
        const current = this.leftSidebarMode();
        const next: LeftSidebarMode = current === 'open' ? 'collapsed' : 'open';
        this.setLeftSidebarMode(next);
    }

    setRightSidebarMode(mode: RightSidebarMode): void {
        this.updateState({ rightSidebarMode: mode });
    }

    toggleRightSidebar(): void {
        const current = this.rightSidebarMode();
        const next: RightSidebarMode = current === 'open' ? 'closed' : 'open';
        this.setRightSidebarMode(next);
    }

    setRightSidebarActivePanel(panel: RightSidebarPanel): void {
        this.updateState({ rightSidebarActivePanel: normalizeRightSidebarPanel(panel) });
    }

    // ─────────────────────────────────────────────────────────────
    // Public Actions: Panel Dimensions
    // ─────────────────────────────────────────────────────────────

    setLeftSidebarWidth(width: number): void {
        this.updateState({ leftSidebarWidth: Math.max(200, Math.min(600, width)) });
    }

    setRightSidebarWidth(width: number): void {
        this.updateState({ rightSidebarWidth: Math.max(200, Math.min(600, width)) });
    }

    setHubHeight(height: number): void {
        this.updateState({ hubHeight: Math.max(100, Math.min(800, height)) });
    }

    // ─────────────────────────────────────────────────────────────
    // Public Actions: Folder Expansion
    // ─────────────────────────────────────────────────────────────

    toggleFolderExpansion(folderId: string): void {
        const current = this.expandedFoldersSet();
        const next = new Set(current);
        if (next.has(folderId)) {
            next.delete(folderId);
        } else {
            next.add(folderId);
        }
        this.updateState({ expandedFolderIds: [...next] });
    }

    setFolderExpanded(folderId: string, expanded: boolean): void {
        const current = this.expandedFoldersSet();
        const next = new Set(current);
        if (expanded) {
            next.add(folderId);
        } else {
            next.delete(folderId);
        }
        this.updateState({ expandedFolderIds: [...next] });
    }

    expandAllFolders(folderIds: string[]): void {
        this.updateState({ expandedFolderIds: folderIds });
    }

    collapseAllFolders(): void {
        this.updateState({ expandedFolderIds: [] });
    }

    isFolderExpanded(folderId: string): boolean {
        return this.expandedFoldersSet().has(folderId);
    }

    // ─────────────────────────────────────────────────────────────
    // Public Actions: Search
    // ─────────────────────────────────────────────────────────────

    setSearchQuery(query: string): void {
        this.updateState({ searchQuery: query });
    }

    setSearchMode(mode: SearchMode): void {
        this.updateState({ searchMode: mode });
    }

    setSearchScope(scope: 'all' | 'narrative'): void {
        this.updateState({ searchScope: scope });
    }

    // ─────────────────────────────────────────────────────────────
    // Public Actions: Calendar
    // ─────────────────────────────────────────────────────────────

    setCalendarView(view: CalendarView): void {
        this.updateState({ calendarView: view });
    }

    setCalendarSelectedDate(date: string): void {
        this.updateState({ calendarSelectedDate: date });
    }

    // ─────────────────────────────────────────────────────────────
    // Public Actions: Theme
    // ─────────────────────────────────────────────────────────────

    setTheme(theme: ThemePreference): void {
        this.updateState({ theme });
    }

    setHighlightMode(mode: HighlightMode): void {
        this.updateState({ highlightMode: mode });
    }

    setFocusedEntityKinds(kinds: string[]): void {
        this.updateState({ focusedEntityKinds: kinds });
    }

    toggleFocusedEntityKind(kind: string): void {
        const current = this.focusedEntityKinds();
        const next = current.includes(kind)
            ? current.filter(k => k !== kind)
            : [...current, kind];
        this.updateState({ focusedEntityKinds: next });
    }
}
