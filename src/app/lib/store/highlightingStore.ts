// src/app/lib/store/highlightingStore.ts
// Highlighting Mode Settings - Pure TypeScript Store with Dexie persistence
// Controls how entities are decorated in the editor with LIVE updates

import { getSetting, setSetting } from '../dexie/settings.service';

// ============================================
// TYPES
// ============================================

export type HighlightMode = 'clean' | 'vivid' | 'subtle' | 'gradient' | 'off';

export interface HighlightSettings {
    /** Current highlighting mode */
    mode: HighlightMode;
    /** Whether to show wikilink decorations */
    showWikilinks: boolean;
    /** Whether to show tag decorations */
    showTags: boolean;
    /** Whether to show @mention decorations */
    showMentions: boolean;
    /** Whether to show temporal expression decorations */
    showTemporal: boolean;
}

/** Default settings - Clean mode as default */
export const DEFAULT_HIGHLIGHT_SETTINGS: HighlightSettings = {
    mode: 'vivid',
    showWikilinks: true,
    showTags: true,
    showMentions: true,
    showTemporal: true,
};

/** Human-readable mode labels */
export const HIGHLIGHT_MODE_LABELS: Record<HighlightMode, string> = {
    clean: 'Clean',
    vivid: 'Vivid',
    subtle: 'Subtle',
    gradient: 'Gradient',
    off: 'Off',
};

/** Mode descriptions for UI tooltips */
export const HIGHLIGHT_MODE_DESCRIPTIONS: Record<HighlightMode, string> = {
    clean: 'Plain text rendering with entity metadata still attached',
    vivid: 'Full colorful highlighting - all entities always visible',
    subtle: 'Static gradient text without pill chrome or motion',
    gradient: 'Gradient inline text without pill chrome',
    off: 'No entity highlighting',
};

// ============================================
// STORAGE KEY
// ============================================

const STORAGE_KEY = 'highlighting-settings';

// ============================================
// STORE CLASS
// ============================================

class HighlightingStore {
    private settings: HighlightSettings;
    private listeners: Set<() => void> = new Set();
    // CACHED snapshot for useSyncExternalStore - same reference until data changes
    private snapshot: HighlightSettings;

    constructor() {
        // Load from Dexie settings (already in memory from boot cache)
        this.settings = this.loadFromStorage();
        this.snapshot = this.settings; // Initial snapshot
    }

    // ============================================
    // SUBSCRIPTIONS (for Angular effects / React hooks)
    // ============================================

    subscribe(listener: () => void): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    private notify(): void {
        // Create new snapshot reference when data changes
        this.snapshot = { ...this.settings };
        this.listeners.forEach(fn => fn());
    }

    // ============================================
    // GETTERS - STABLE REFERENCES
    // ============================================

    /** 
     * Get settings snapshot - returns SAME reference until data changes
     * (Required for React useSyncExternalStore to avoid infinite loops)
     */
    getSnapshot(): HighlightSettings {
        return this.snapshot;
    }

    /** @deprecated Use getSnapshot() for React hooks */
    getSettings(): HighlightSettings {
        return this.snapshot;
    }

    getMode(): HighlightMode {
        return this.settings.mode;
    }

    reloadFromStorage(): void {
        const next = this.loadFromStorage();
        if (this.settingsEqual(this.settings, next)) {
            return;
        }

        this.settings = next;
        this.notify();
    }

    // ============================================
    // SETTERS (with live notification)
    // ============================================

    setSettings(updates: Partial<HighlightSettings>): void {
        this.settings = { ...this.settings, ...updates };
        this.saveToStorage();
        this.notify();
    }

    setMode(mode: HighlightMode): void {
        if (this.settings.mode === mode) return; // No-op if same
        this.settings = { ...this.settings, mode };
        this.saveToStorage();
        this.notify();
    }

    // ============================================
    // PERSISTENCE
    // ============================================

    private loadFromStorage(): HighlightSettings {
        const stored = getSetting<(Omit<Partial<HighlightSettings>, 'mode'> & { mode?: string }) | null>(STORAGE_KEY, null);
        if (stored) {
            const persistedMode = stored.mode;
            const mode = persistedMode === 'focus'
                ? 'subtle'
                : this.isHighlightMode(persistedMode) ? persistedMode : DEFAULT_HIGHLIGHT_SETTINGS.mode;
            return {
                mode,
                showWikilinks: stored.showWikilinks ?? DEFAULT_HIGHLIGHT_SETTINGS.showWikilinks,
                showTags: stored.showTags ?? DEFAULT_HIGHLIGHT_SETTINGS.showTags,
                showMentions: stored.showMentions ?? DEFAULT_HIGHLIGHT_SETTINGS.showMentions,
                showTemporal: stored.showTemporal ?? DEFAULT_HIGHLIGHT_SETTINGS.showTemporal,
            };
        }
        return { ...DEFAULT_HIGHLIGHT_SETTINGS };
    }

    private saveToStorage(): void {
        setSetting(STORAGE_KEY, this.settings);
    }

    private settingsEqual(left: HighlightSettings, right: HighlightSettings): boolean {
        return left.mode === right.mode
            && left.showWikilinks === right.showWikilinks
            && left.showTags === right.showTags
            && left.showMentions === right.showMentions
            && left.showTemporal === right.showTemporal;
    }

    private isHighlightMode(mode: string | undefined): mode is HighlightMode {
        return mode === 'clean'
            || mode === 'vivid'
            || mode === 'subtle'
            || mode === 'gradient'
            || mode === 'off';
    }

    reset(): void {
        this.settings = { ...DEFAULT_HIGHLIGHT_SETTINGS };
        this.saveToStorage();
        this.notify();
    }
}

// ============================================
// SINGLETON INSTANCE
// ============================================

export const highlightingStore = new HighlightingStore();
