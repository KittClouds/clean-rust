// src/lib/store/entityColorStore.ts
// Unified Entity Color System - Single source of truth for all entity colors
// Uses CSS custom properties for live updates across the entire app
// Supports both PILL colors (background/border) and TEXT colors (foreground)

import type { EntityKind } from '../Scanner/types';

export type GraphNodeColorKind =
    | 'cooccurrence'
    | 'observation'
    | 'communication'
    | 'authority'
    | 'approval'
    | 'family'
    | 'intimacy'
    | 'transfer'
    | 'scenePresence'
    | 'causal'
    | 'temporal'
    | 'relationship'
    | 'document'
    | 'chunk'
    | 'anchor'
    | 'graphFact'
    | 'eventNode'
    | 'temporalFact'
    | 'causalFact'
    | 'memoryState'
    | 'decisionState'
    | 'rankStatus'
    | 'serviceContext'
    | 'affiliationContext'
    | 'familyContext';

// ============================================
// DEFAULT COLORS (HSL VALUES)
// ============================================

// HSL values without the hsl() wrapper - used in CSS as: hsl(var(--entity-character))
// These are used for pill backgrounds/borders
export const DEFAULT_ENTITY_COLORS: Record<EntityKind, string> = {
    CHARACTER: '280 70% 60%',      // Purple
    LOCATION: '200 75% 55%',       // Blue
    NPC: '30 80% 55%',             // Orange
    ITEM: '45 90% 50%',            // Gold
    FACTION: '0 70% 55%',          // Red
    SCENE: '330 70% 60%',          // Pink
    EVENT: '25 90% 55%',           // Orange
    CONCEPT: '170 65% 45%',        // Teal
    ARC: '270 70% 60%',            // Violet
    ACT: '230 80% 55%',            // Royal Blue
    CHAPTER: '175 65% 45%',        // Teal
    BEAT: '320 70% 55%',           // Magenta
    TIMELINE: '50 85% 50%',        // Gold
    NARRATIVE: '250 60% 55%',      // Indigo
    NETWORK: '190 70% 50%',        // Cyan
    CUSTOM: '0 0% 50%',            // Gray
    OTHER: '0 0% 50%',             // Gray
    UNKNOWN: '0 0% 50%',
    ORGANIZATION: '300 70% 60%',   // Magenta-ish/Pink
    CREATURE: '140 70% 50%',       // Green
};

// Default TEXT colors - typically same as pill colors but can be customized separately
// These are used for text foreground (implicit entities, headers, etc.)
export const DEFAULT_ENTITY_TEXT_COLORS: Record<EntityKind, string> = {
    CHARACTER: '280 70% 60%',      // Purple
    LOCATION: '200 75% 55%',       // Blue
    NPC: '30 80% 55%',             // Orange
    ITEM: '45 90% 50%',            // Gold
    FACTION: '0 70% 55%',          // Red
    SCENE: '330 70% 60%',          // Pink
    EVENT: '25 90% 55%',           // Orange
    CONCEPT: '170 65% 45%',        // Teal
    ARC: '270 70% 60%',            // Violet
    ACT: '230 80% 55%',            // Royal Blue
    CHAPTER: '175 65% 45%',        // Teal
    BEAT: '320 70% 55%',           // Magenta
    TIMELINE: '50 85% 50%',        // Gold
    NARRATIVE: '250 60% 55%',      // Indigo
    NETWORK: '190 70% 50%',        // Cyan
    CUSTOM: '0 0% 50%',            // Gray
    OTHER: '0 0% 50%',             // Gray
    UNKNOWN: '0 0% 50%',
    ORGANIZATION: '300 70% 60%',   // Magenta-ish/Pink
    CREATURE: '140 70% 50%',       // Green
};

export const DEFAULT_GRAPH_NODE_COLORS: Record<GraphNodeColorKind, string> = {
    cooccurrence: '215 10% 62%',
    observation: '188 82% 62%',
    communication: '162 72% 57%',
    authority: '356 78% 62%',
    approval: '112 72% 55%',
    family: '338 76% 66%',
    intimacy: '312 76% 64%',
    transfer: '58 94% 56%',
    scenePresence: '18 88% 61%',
    causal: '12 90% 60%',
    temporal: '64 84% 52%',
    relationship: '292 76% 65%',
    document: '210 82% 58%',
    chunk: '176 70% 46%',
    anchor: '262 78% 66%',
    graphFact: '38 92% 57%',
    eventNode: '24 92% 58%',
    temporalFact: '199 80% 58%',
    causalFact: '345 82% 61%',
    memoryState: '145 70% 50%',
    decisionState: '88 84% 56%',
    rankStatus: '246 82% 58%',
    serviceContext: '32 88% 58%',
    affiliationContext: '176 70% 48%',
    familyContext: '326 76% 62%',
};

export function normalizeEntityKind(kind: EntityKind | string | null | undefined): EntityKind | null {
    const normalized = String(kind || '').trim().toUpperCase().replace(/[-\s]+/g, '_') as EntityKind;
    if (normalized === 'FACTION') return 'NETWORK' as EntityKind;
    return Object.prototype.hasOwnProperty.call(DEFAULT_ENTITY_COLORS, normalized) ? normalized : null;
}

const GRAPH_NODE_KIND_ALIASES: Record<string, GraphNodeColorKind> = {
    co_occurrence: 'cooccurrence',
    co_occurs: 'cooccurrence',
    co_occurs_with: 'cooccurrence',
    cooccurs: 'cooccurrence',
    cooccurrence: 'cooccurrence',
    observe: 'observation',
    observes: 'observation',
    observation: 'observation',
    comment: 'communication',
    comments: 'communication',
    communication: 'communication',
    authority: 'authority',
    command: 'authority',
    approval: 'approval',
    family: 'family',
    intimacy: 'intimacy',
    transfer: 'transfer',
    scene_presence: 'scenePresence',
    scenepresence: 'scenePresence',
    causal: 'causal',
    causal_fact: 'causalFact',
    causalfact: 'causalFact',
    state: 'memoryState',
    decision: 'decisionState',
    decision_state: 'decisionState',
    decisionstate: 'decisionState',
    rank: 'rankStatus',
    rank_status: 'rankStatus',
    rankstatus: 'rankStatus',
    rank_or_status: 'rankStatus',
    rankorstatus: 'rankStatus',
    service: 'serviceContext',
    service_context: 'serviceContext',
    servicecontext: 'serviceContext',
    service_rank: 'serviceContext',
    servicerank: 'serviceContext',
    affiliation: 'affiliationContext',
    affiliate_context: 'affiliationContext',
    affiliatecontext: 'affiliationContext',
    affiliant_context: 'affiliationContext',
    affiliantcontext: 'affiliationContext',
    affiliation_context: 'affiliationContext',
    affiliationcontext: 'affiliationContext',
    family_context: 'familyContext',
    familycontext: 'familyContext',
    temporal: 'temporal',
    temporal_fact: 'temporalFact',
    temporalfact: 'temporalFact',
    timeanchor: 'temporal',
    time_anchor: 'temporal',
    relationship: 'relationship',
    document: 'document',
    note: 'document',
    chunk: 'chunk',
    leaf: 'chunk',
    anchor: 'anchor',
    mention: 'anchor',
    graph_fact: 'graphFact',
    graphfact: 'graphFact',
    event: 'eventNode',
    event_node: 'eventNode',
    eventnode: 'eventNode',
    memory: 'memoryState',
    memory_state: 'memoryState',
    memorystate: 'memoryState',
};

export function normalizeGraphNodeColorKind(kind: GraphNodeColorKind | string | null | undefined): GraphNodeColorKind | null {
    const normalized = String(kind || '').trim().replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase().replace(/[-\s]+/g, '_');
    const alias = GRAPH_NODE_KIND_ALIASES[normalized];
    return alias || (Object.prototype.hasOwnProperty.call(DEFAULT_GRAPH_NODE_COLORS, kind as string) ? kind as GraphNodeColorKind : null);
}

// ============================================
// STORE CLASS - PERSISTED RUNTIME REGISTRY
// CSS variables are the live source of truth; localStorage restores user choices.
// ============================================

const STORAGE_KEY = 'graph-style-lab:entity-colors:v1';

interface PersistedEntityColors {
    colors?: Partial<Record<EntityKind, string>>;
    textColors?: Partial<Record<EntityKind, string>>;
    graphNodeColors?: Partial<Record<GraphNodeColorKind, string>>;
}

class EntityColorStore {
    private colors: Record<EntityKind, string>;
    private textColors: Record<EntityKind, string>;
    private graphNodeColors: Record<GraphNodeColorKind, string>;
    private listeners: Set<() => void> = new Set();
    private initialized = false;
    // Cached snapshots for useSyncExternalStore - same reference until data changes
    private snapshot: Record<EntityKind, string>;
    private textSnapshot: Record<EntityKind, string>;

    constructor() {
        this.colors = { ...DEFAULT_ENTITY_COLORS };
        this.textColors = { ...DEFAULT_ENTITY_TEXT_COLORS };
        this.graphNodeColors = { ...DEFAULT_GRAPH_NODE_COLORS };
        this.snapshot = this.colors;
        this.textSnapshot = this.textColors;
    }

    /**
     * Initialize store - must be called after DOM is ready.
     * Defaults are overlaid with any persisted Style Lab choices.
     */
    initialize(): void {
        if (this.initialized) return;

        this.colors = { ...DEFAULT_ENTITY_COLORS };
        this.textColors = { ...DEFAULT_ENTITY_TEXT_COLORS };
        this.graphNodeColors = { ...DEFAULT_GRAPH_NODE_COLORS };
        this.loadPersistedColors();
        this.snapshot = { ...this.colors };
        this.textSnapshot = { ...this.textColors };

        // Sync all colors to CSS variables
        this.syncAllToCssVars();

        this.initialized = true;
        console.log('[EntityColorStore] Initialized with', Object.keys(this.colors).length, 'entity colors and', Object.keys(this.graphNodeColors).length, 'graph node colors');
    }

    // ============================================
    // GETTERS - CSS Variable Format
    // ============================================

    /**
     * Get pill color as CSS hsl() string using CSS variable
     * Returns: 'hsl(var(--entity-character))'
     */
    getEntityColor(kind: EntityKind | string): string {
        const varName = this.getCssVarName(kind);
        return `hsl(var(${varName}))`;
    }

    /**
     * Get text color as CSS hsl() string using CSS variable
     * Returns: 'hsl(var(--entity-character-text))'
     */
    getEntityTextColor(kind: EntityKind | string): string {
        const varName = this.getTextCssVarName(kind);
        return `hsl(var(${varName}))`;
    }

    /**
     * Get background color with opacity
     * Returns: 'hsl(var(--entity-character) / 0.2)'
     */
    getEntityBgColor(kind: EntityKind | string, opacity = 0.2): string {
        const varName = this.getCssVarName(kind);
        return `hsl(var(${varName}) / ${opacity})`;
    }

    /**
     * Get CSS variable name for pill color
     * Returns: '--entity-character'
     */
    getCssVarName(kind: EntityKind | string): string {
        return `--entity-${(normalizeEntityKind(kind) ?? 'UNKNOWN').toLowerCase().replace(/_/g, '-')}`;
    }

    getTextCssVarName(kind: EntityKind | string): string {
        return `--entity-${(normalizeEntityKind(kind) ?? 'UNKNOWN').toLowerCase().replace(/_/g, '-')}-text`;
    }

    getGraphNodeCssVarName(kind: GraphNodeColorKind | string): string {
        return `--graph-node-${(normalizeGraphNodeColorKind(kind) ?? 'graphFact').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase()}`;
    }

    /**
     * Get raw HSL value for pill color (without hsl() wrapper)
     * Returns: '280 70% 60%'
     */
    getRawHsl(kind: EntityKind | string): string {
        const normalized = normalizeEntityKind(kind);
        return normalized ? this.colors[normalized] : '220 10% 50%';
    }

    /**
     * Get raw HSL value for text color (without hsl() wrapper)
     * Returns: '280 70% 60%'
     */
    getRawTextHsl(kind: EntityKind | string): string {
        const normalized = normalizeEntityKind(kind);
        return normalized ? this.textColors[normalized] : '220 10% 50%';
    }

    getRawGraphNodeHsl(kind: GraphNodeColorKind | string): string {
        const normalized = normalizeGraphNodeColorKind(kind);
        return normalized ? this.graphNodeColors[normalized] : DEFAULT_GRAPH_NODE_COLORS.graphFact;
    }

    /**
     * Get snapshot of all pill colors - returns STABLE reference for useSyncExternalStore
     */
    getSnapshot(): Record<EntityKind, string> {
        return this.snapshot;
    }

    /**
     * Get snapshot of all text colors - returns STABLE reference for useSyncExternalStore
     */
    getTextSnapshot(): Record<EntityKind, string> {
        return this.textSnapshot;
    }

    /**
     * Get all pill colors (creates new object - use getSnapshot for React hooks)
     */
    getAllColors(): Record<EntityKind, string> {
        return { ...this.colors };
    }

    /**
     * Get all text colors (creates new object - use getTextSnapshot for React hooks)
     */
    getAllTextColors(): Record<EntityKind, string> {
        return { ...this.textColors };
    }

    // ============================================
    // SETTERS - Update CSS variables live (session only)
    // ============================================

    /**
     * Set pill color for a kind - updates CSS variable immediately
     */
    setColor(kind: EntityKind | string, hslValue: string): void {
        const normalized = normalizeEntityKind(kind);
        if (!normalized) return;
        this.colors[normalized] = hslValue;
        this.setCssVar(normalized, hslValue);
        this.persist();
        this.notify();
    }

    /**
     * Set text color for a kind - updates CSS variable immediately
     */
    setTextColor(kind: EntityKind | string, hslValue: string): void {
        const normalized = normalizeEntityKind(kind);
        if (!normalized) return;
        this.textColors[normalized] = hslValue;
        this.setTextCssVar(normalized, hslValue);
        this.persist();
        this.notify();
    }

    setGraphNodeColor(kind: GraphNodeColorKind | string, hslValue: string): void {
        const normalized = normalizeGraphNodeColorKind(kind);
        if (!normalized) return;
        this.graphNodeColors[normalized] = hslValue;
        this.setGraphNodeCssVar(normalized, hslValue);
        this.persist();
        this.notify();
    }

    /**
     * Set multiple pill colors at once
     */
    setColors(colors: Partial<Record<EntityKind, string>>): void {
        for (const [kind, hsl] of Object.entries(colors)) {
            const normalized = normalizeEntityKind(kind);
            if (!normalized || !hsl) continue;
            this.colors[normalized] = hsl;
            this.setCssVar(normalized, hsl);
        }
        this.persist();
        this.notify();
    }

    /**
     * Set multiple text colors at once
     */
    setTextColors(colors: Partial<Record<EntityKind, string>>): void {
        for (const [kind, hsl] of Object.entries(colors)) {
            const normalized = normalizeEntityKind(kind);
            if (!normalized || !hsl) continue;
            this.textColors[normalized] = hsl;
            this.setTextCssVar(normalized, hsl);
        }
        this.persist();
        this.notify();
    }

    /**
     * Reset all colors to defaults
     */
    reset(): void {
        this.colors = { ...DEFAULT_ENTITY_COLORS };
        this.textColors = { ...DEFAULT_ENTITY_TEXT_COLORS };
        this.graphNodeColors = { ...DEFAULT_GRAPH_NODE_COLORS };
        this.syncAllToCssVars();
        this.persist();
        this.notify();
    }

    private loadPersistedColors(): void {
        const persisted = this.readPersistedColors();
        if (!persisted) return;
        this.applyPersistedEntityColors(this.colors, persisted.colors);
        this.applyPersistedEntityColors(this.textColors, persisted.textColors);
        this.applyPersistedGraphNodeColors(persisted.graphNodeColors);
    }

    private readPersistedColors(): PersistedEntityColors | null {
        if (typeof localStorage === 'undefined') return null;
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw) as PersistedEntityColors;
            return parsed && typeof parsed === 'object' ? parsed : null;
        } catch {
            return null;
        }
    }

    private applyPersistedEntityColors(
        target: Record<EntityKind, string>,
        colors: Partial<Record<EntityKind, string>> | undefined,
    ): void {
        if (!colors) return;
        for (const [kind, hsl] of Object.entries(colors)) {
            const normalized = normalizeEntityKind(kind);
            if (!normalized || !this.isValidHsl(hsl)) continue;
            target[normalized] = hsl;
        }
    }

    private applyPersistedGraphNodeColors(
        colors: Partial<Record<GraphNodeColorKind, string>> | undefined,
    ): void {
        if (!colors) return;
        for (const [kind, hsl] of Object.entries(colors)) {
            const normalized = normalizeGraphNodeColorKind(kind);
            if (!normalized || !this.isValidHsl(hsl)) continue;
            this.graphNodeColors[normalized] = hsl;
        }
    }

    private persist(): void {
        if (typeof localStorage === 'undefined') return;
        try {
            const payload: PersistedEntityColors = {
                colors: this.colors,
                textColors: this.textColors,
                graphNodeColors: this.graphNodeColors,
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        } catch {
            // Color choices are non-critical; keep live CSS updates even if storage is unavailable.
        }
    }

    private isValidHsl(value: unknown): value is string {
        return typeof value === 'string' && /^\d{1,3}(?:\.\d+)?\s+\d{1,3}(?:\.\d+)?%\s+\d{1,3}(?:\.\d+)?%$/.test(value.trim());
    }

    // ============================================
    // CSS VARIABLE MANAGEMENT
    // ============================================

    private setCssVar(kind: EntityKind | string, hslValue: string): void {
        const varName = this.getCssVarName(kind);
        // Only run on client
        if (typeof document !== 'undefined') {
            document.documentElement.style.setProperty(varName, hslValue);
        }
    }

    private setTextCssVar(kind: EntityKind | string, hslValue: string): void {
        const varName = this.getTextCssVarName(kind);
        // Only run on client
        if (typeof document !== 'undefined') {
            document.documentElement.style.setProperty(varName, hslValue);
        }
    }

    private setGraphNodeCssVar(kind: GraphNodeColorKind | string, hslValue: string): void {
        const varName = this.getGraphNodeCssVarName(kind);
        if (typeof document !== 'undefined') {
            document.documentElement.style.setProperty(varName, hslValue);
        }
    }

    private syncAllToCssVars(): void {
        for (const [kind, hsl] of Object.entries(this.colors)) {
            this.setCssVar(kind, hsl);
        }
        for (const [kind, hsl] of Object.entries(this.textColors)) {
            this.setTextCssVar(kind, hsl);
        }
        for (const [kind, hsl] of Object.entries(this.graphNodeColors)) {
            this.setGraphNodeCssVar(kind, hsl);
        }
    }

    // ============================================
    // SUBSCRIPTIONS
    // ============================================

    subscribe(listener: () => void): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    private notify(): void {
        // Create new snapshot references so useSyncExternalStore detects change
        this.snapshot = { ...this.colors };
        this.textSnapshot = { ...this.textColors };
        this.listeners.forEach(fn => fn());
    }
}

// ============================================
// SINGLETON INSTANCE
// ============================================

export const entityColorStore = new EntityColorStore();

// ============================================
// CONVENIENCE FUNCTIONS (for easy import)
// ============================================

/**
 * Get entity pill color as CSS hsl() string using CSS variable
 * Usage: style={{ backgroundColor: getEntityColor('CHARACTER') }}
 * Returns: 'hsl(var(--entity-character))'
 */
export function getEntityColor(kind: EntityKind | string | undefined): string {
    if (!kind) return 'hsl(var(--entity-unknown))';
    return entityColorStore.getEntityColor(kind);
}

/**
 * Get entity text color as CSS hsl() string using CSS variable
 * Usage: style={{ color: getEntityTextColor('CHARACTER') }}
 * Returns: 'hsl(var(--entity-character-text))'
 */
export function getEntityTextColor(kind: EntityKind | string | undefined): string {
    if (!kind) return 'hsl(var(--entity-unknown-text))';
    return entityColorStore.getEntityTextColor(kind);
}

/**
 * Get entity background color with opacity
 * Usage: style={{ backgroundColor: getEntityBgColor('CHARACTER') }}
 * Returns: 'hsl(var(--entity-character) / 0.2)'
 */
export function getEntityBgColor(kind: EntityKind | string | undefined, opacity = 0.2): string {
    if (!kind) return `hsl(var(--entity-unknown) / ${opacity})`;
    return entityColorStore.getEntityBgColor(kind, opacity);
}

/**
 * Get CSS variable name for pill color
 * Returns: '--entity-character'
 */
export function getEntityColorVar(kind: EntityKind | string): string {
    return entityColorStore.getCssVarName(kind);
}

/**
 * Get CSS variable name for text color
 * Returns: '--entity-character-text'
 */
export function getEntityTextColorVar(kind: EntityKind | string): string {
    return entityColorStore.getTextCssVarName(kind);
}
