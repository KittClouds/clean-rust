/**
 * PrettyTextAPI — Thin facade between the Editor and the Scan Pipeline.
 *
 * Responsibilities (after refactor):
 *   1. ProseMirror doc ↔ text conversion (via ProseMirrorBridge)
 *   2. Delegating to ScanPipeline.run() for all scanning
 *   3. Span caching (Dexie read/write)
 *   4. Style/config/subscribe (UI concerns)
 *
 * Everything else has been extracted into focused modules:
 *   - HighlightScanner  (implicit entity spans)
 *   - DiscoveryScanner  (unsupervised NER + filter)
 *   - GraphScanner      (relationship extraction)
 *   - ScanPipeline      (sequential orchestrator)
 */

import type {
    DecorationSpan,
    HighlighterConfig,
    HighlightMode,
    AnalyticsHighlightKind,
    AnalyticsHighlightPaletteKey,
} from '../lib/Scanner';
import { getDecorationStyle, getDecorationClass } from '../lib/Scanner';
import type { EntityKind } from '../lib/Scanner/types';
import { getScanCoordinator } from '../lib/Scanner/scanCoordinatorInstance';
import { realignSpans } from '../lib/Scanner/anchor-utils';

// Modular Scanner Pipeline
import {
    type ProseMirrorDoc,
    extractText,
    extractProjectedText,
    docContent,
    remapSpans,
    remapSpansPermissive,
} from '../lib/Scanner/prosemirror-bridge';
import { createKeywordFocusSpans } from '../lib/Scanner/keyword-focus';
import { HighlightScanner } from '../lib/Scanner/highlight-scanner';
import { DiscoveryScanner } from '../lib/Scanner/discovery-scanner';
import { GraphScanner } from '../lib/Scanner/graph-scanner';
import { ScanPipeline } from '../lib/Scanner/scan-pipeline';

import { highlightingStore } from '../lib/store/highlightingStore';
import { analyticsHighlightStore } from '../lib/store/analyticsHighlightStore';
import { keywordHighlightStore } from '../lib/store/keywordHighlightStore';
import { searchHighlightStore } from '../lib/store/searchHighlightStore';
import { PhoenixUiApiService } from '../services/phoenix-ui-api.service';
import {
    getNoteDecorations,
    saveNoteDecorations,
    getDecorationContentHash,
    hashContent
} from '../lib/dexie/decorations';
import { smartGraphRegistry } from '../lib/registry';
import { DiscoveryStore } from '../lib/store/discoveryStore';
import type { AnalyticsHighlightRange } from '../lib/analytics';
import { filterCachedEntitySpans } from './pretty-text-cache';
import type { SentenceVariationBucket } from '../lib/Scanner/types';
import type { AnalyticsHighlightSelection } from '../lib/store/analyticsHighlightStore';

// ─────────────────────────────────────────────────────────────────────────────
// Module-level wiring (legacy bridge — to be replaced with DI over time)
// ─────────────────────────────────────────────────────────────────────────────

let discoveryStore: DiscoveryStore | null = null;
let phoenixUiApi: PhoenixUiApiService | null = null;
let scanPipeline: ScanPipeline | null = null;

export function setDiscoveryStore(store: DiscoveryStore) {
    discoveryStore = store;
}

export function setPhoenixUiApi(service: PhoenixUiApiService) {
    phoenixUiApi = service;

    // Build the pipeline when Phoenix native becomes available
    scanPipeline = new ScanPipeline(
        new HighlightScanner(service),
        new DiscoveryScanner(service, {
            isRegisteredEntity: (token) => smartGraphRegistry.isRegisteredEntity(token),
        }),
        new GraphScanner(service, {
            upsertRelationship: (rel) => smartGraphRegistry.upsertRelationship(rel),
        }),
    );
    console.log('[PrettyTextAPI] ScanPipeline initialized');
}

export function getPhoenixUiApi(): PhoenixUiApiService | null {
    return phoenixUiApi;
}

// ─────────────────────────────────────────────────────────────────────────────
// Interface (unchanged — backward compatible)
// ─────────────────────────────────────────────────────────────────────────────

export { ProseMirrorDoc };

export interface PrettyTextApi {
    getDecorations(doc: ProseMirrorDoc): DecorationSpan[];
    scanForSpansAsync(doc: ProseMirrorDoc): Promise<DecorationSpan[]>;
    getImplicitDecorations(doc: ProseMirrorDoc): DecorationSpan[];
    getStyle(span: DecorationSpan): string;
    getClass(span: DecorationSpan): string;
    getMode(): HighlightMode;
    setMode(mode: HighlightMode): void;
    getConfig(): HighlighterConfig;
    setConfig(config: Partial<HighlighterConfig>): void;
    subscribe(callback: () => void): () => void;
    setNoteId(noteId: string, narrativeId?: string): void;
    primeImplicitDecorations(doc: ProseMirrorDoc): void;
    scheduleImplicitRefresh(doc: ProseMirrorDoc, options?: ImplicitRefreshOptions): void;
    setKeywordHighlights(noteId: string, keywords: string[]): void;
    toggleKeywordHighlight(noteId: string, keyword: string): void;
    clearKeywordHighlights(noteId: string): void;
    setSearchHighlightTerms(terms: string[]): void;
    clearSearchHighlights(): void;
    setAnalyticsHighlights(noteId: string, key: string, kind: AnalyticsHighlightKind, label: string, ranges: AnalyticsHighlightRange[], paletteKey?: AnalyticsHighlightPaletteKey): void;
    toggleAnalyticsHighlights(noteId: string, key: string, kind: AnalyticsHighlightKind, label: string, ranges: AnalyticsHighlightRange[], paletteKey?: AnalyticsHighlightPaletteKey): void;
    clearAnalyticsHighlights(): void;
    clearAnalyticsDetailHighlights(): void;
    setSentenceVariationHighlights(noteId: string, buckets: ReadonlySet<SentenceVariationBucket>, selections: AnalyticsHighlightSelection[]): void;
    clearSentenceVariationHighlights(noteId?: string): void;
    onKeystroke(char: string, cursorPos: number, contextText: string): void;
    forceRescan(): void;
}

export interface ImplicitRefreshOptions {
    delayMs?: number;
    immediate?: boolean;
    force?: boolean;
    useCache?: boolean;
    allowRealign?: boolean;
    rescanAfterRealign?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Implementation (thin facade)
// ─────────────────────────────────────────────────────────────────────────────

class PrettyTextAPI implements PrettyTextApi {
    private enableEntityRefs = true;
    private implicitDecorations: DecorationSpan[] = [];
    private implicitDecorationsHash: string | null = null;
    private lastContext: string = '';
    private lastScannedContext: string = '';
    private listeners: Set<() => void> = new Set();
    private scanVersion = 0;
    private refreshRequestVersion = 0;
    private currentNoteId: string = '';
    private currentNarrativeId?: string;
    private hasScannedOnOpen = false;
    private lastKnownEntityCount = 0;
    private lastSentenceEndPos = 0;
    private pendingRescan = false;
    private pendingImplicitRefreshTimer: ReturnType<typeof setTimeout> | null = null;
    private lastDoc: ProseMirrorDoc | null = null;
    private selectedKeywords: string[] = [];
    private searchHighlightTerms: string[] = [];
    private analyticsHighlightSpans: DecorationSpan[] = [];

    constructor() {
        this.searchHighlightTerms = searchHighlightStore.getTerms();

        if (typeof window !== 'undefined') {
            window.addEventListener('phoenix-ready', () => {
                console.log('[PrettyTextAPI] Phoenix ready - triggering implicit refresh');
                if (this.lastDoc && this.currentNoteId) {
                    this.scheduleImplicitRefresh(this.lastDoc, { immediate: true, force: true });
                    return;
                }
                this.pendingRescan = true;
                this.notifyListeners();
            });

            window.addEventListener('fst-toggle', ((e: CustomEvent) => {
                const enabled = e.detail?.enabled;
                if (!enabled) {
                    this.implicitDecorations = this.implicitDecorations.filter(
                        d => d.type !== 'entity_candidate'
                    );
                    this.notifyListeners();
                } else {
                    if (this.lastDoc && this.currentNoteId) {
                        this.scheduleImplicitRefresh(this.lastDoc, { immediate: true, force: true });
                        return;
                    }
                    this.pendingRescan = true;
                    this.notifyListeners();
                }
            }) as EventListener);
        }

        highlightingStore.subscribe(() => this.notifyListeners());
        keywordHighlightStore.subscribe(() => {
            const nextKeywords = keywordHighlightStore.getKeywordsForNote(this.currentNoteId);
            if (JSON.stringify(nextKeywords) !== JSON.stringify(this.selectedKeywords)) {
                this.selectedKeywords = nextKeywords;
                this.notifyListeners();
            }
        });
        searchHighlightStore.subscribe(() => {
            const nextTerms = searchHighlightStore.getTerms();
            if (JSON.stringify(nextTerms) !== JSON.stringify(this.searchHighlightTerms)) {
                this.searchHighlightTerms = nextTerms;
                this.notifyListeners();
            }
        });
        analyticsHighlightStore.subscribe(() => {
            this.notifyListeners();
        });
    }

    // ── Note Context ──────────────────────────────────────────────────────

    setNoteId(noteId: string, narrativeId?: string): void {
        const prevNoteId = this.currentNoteId;
        this.currentNoteId = noteId;
        this.currentNarrativeId = narrativeId;

        if (noteId !== prevNoteId) {
            this.refreshRequestVersion++;
            this.clearPendingImplicitRefresh();
            this.implicitDecorations = [];
            this.implicitDecorationsHash = null;
            this.hasScannedOnOpen = false;
            this.lastKnownEntityCount = 0;
            this.lastSentenceEndPos = 0;
            this.lastContext = '';
            this.lastScannedContext = '';
            analyticsHighlightStore.clearForNote(prevNoteId);
        }

        this.selectedKeywords = keywordHighlightStore.getKeywordsForNote(noteId);
        this.notifyListeners();
    }

    primeImplicitDecorations(doc: ProseMirrorDoc): void {
        if (!doc) return;
        this.pendingRescan = false;
        this.lastDoc = doc;
        const text = docContent(doc);
        this.lastContext = text;
        const requestId = ++this.refreshRequestVersion;
        void this.tryLoadCachedOrScan(doc, text, {
            requestId,
            useCache: true,
            allowRealign: true,
            rescanAfterRealign: true,
        });
    }

    scheduleImplicitRefresh(doc: ProseMirrorDoc, options: ImplicitRefreshOptions = {}): void {
        if (!doc) return;
        this.pendingRescan = false;
        this.lastDoc = doc;
        const text = docContent(doc);
        this.lastContext = text;

        const requestId = ++this.refreshRequestVersion;
        const runRefresh = () => {
            this.pendingImplicitRefreshTimer = null;

            if (options.useCache) {
                void this.tryLoadCachedOrScan(doc, text, {
                    requestId,
                    useCache: true,
                    allowRealign: !!options.allowRealign,
                    rescanAfterRealign: !!options.rescanAfterRealign,
                });
                return;
            }

            this.triggerPipelineScan(doc, text, requestId);
        };

        this.clearPendingImplicitRefresh();

        if (options.immediate || (options.delayMs ?? 0) <= 0) {
            runRefresh();
            return;
        }

        this.pendingImplicitRefreshTimer = setTimeout(runRefresh, options.delayMs ?? 250);
    }

    setKeywordHighlights(noteId: string, keywords: string[]): void {
        keywordHighlightStore.setKeywordsForNote(noteId, keywords);
    }

    toggleKeywordHighlight(noteId: string, keyword: string): void {
        keywordHighlightStore.toggleKeyword(noteId, keyword);
    }

    clearKeywordHighlights(noteId: string): void {
        keywordHighlightStore.clearKeywordsForNote(noteId);
    }

    setSearchHighlightTerms(terms: string[]): void {
        searchHighlightStore.setTerms(terms);
    }

    clearSearchHighlights(): void {
        searchHighlightStore.clear();
    }

    setAnalyticsHighlights(
        noteId: string,
        key: string,
        kind: AnalyticsHighlightKind,
        label: string,
        ranges: AnalyticsHighlightRange[],
        paletteKey?: AnalyticsHighlightPaletteKey,
    ): void {
        const selection = { noteId, key, kind, label, ranges, paletteKey };
        analyticsHighlightStore.setSelection(selection);
    }

    toggleAnalyticsHighlights(
        noteId: string,
        key: string,
        kind: AnalyticsHighlightKind,
        label: string,
        ranges: AnalyticsHighlightRange[],
        paletteKey?: AnalyticsHighlightPaletteKey,
    ): void {
        const selection = { noteId, key, kind, label, ranges, paletteKey };
        analyticsHighlightStore.toggleSelection(selection);
    }

    clearAnalyticsHighlights(): void {
        analyticsHighlightStore.clear();
    }

    clearAnalyticsDetailHighlights(): void {
        analyticsHighlightStore.clearDetailSelection();
    }

    setSentenceVariationHighlights(
        noteId: string,
        buckets: ReadonlySet<SentenceVariationBucket>,
        selections: AnalyticsHighlightSelection[],
    ): void {
        analyticsHighlightStore.setSentenceVariationHighlights(noteId, buckets, selections);
    }

    clearSentenceVariationHighlights(noteId?: string): void {
        analyticsHighlightStore.clearSentenceVariationHighlights(noteId);
    }

    onKeystroke(char: string, cursorPos: number, contextText: string): void {
        if (!this.currentNoteId) return;
        getScanCoordinator().onKeystroke(char, cursorPos, contextText, this.currentNoteId);
    }

    forceRescan(): void {
        if (!this.lastDoc || !this.currentNoteId) return;
        this.scheduleImplicitRefresh(this.lastDoc, { immediate: true, force: true });
    }

    // ── Decorations ───────────────────────────────────────────────────────

    getDecorations(doc: ProseMirrorDoc): DecorationSpan[] {
        this.lastDoc = doc;
        const settings = highlightingStore.getSettings();
        const { text: editorText, segments } = extractText(doc);
        const analyticsProjection = extractProjectedText(doc);
        const focusTerms = [...new Set([...this.selectedKeywords, ...this.searchHighlightTerms])];
        const keywordSpans = createKeywordFocusSpans(segments, focusTerms);
        const analyticsSpans = this.getAnalyticsHighlightSpans(analyticsProjection.segments);

        if (settings.mode === 'off') return [...keywordSpans, ...analyticsSpans];

        const text = docContent(doc);
        const currentTextHash = hashContent(text);

        if (this.pendingRescan) {
            this.pendingRescan = false;
            this.scheduleImplicitRefresh(doc, { immediate: true, force: true });
        }

        // Build output spans
        const allSpans: DecorationSpan[] = [];
        const implicitsAreValid = this.implicitDecorationsHash === currentTextHash;

        if (implicitsAreValid) {
            for (const implicit of this.implicitDecorations) {
                const overlaps = allSpans.some(explicit =>
                    (implicit.from >= explicit.from && implicit.from < explicit.to) ||
                    (implicit.to > explicit.from && implicit.to <= explicit.to) ||
                    (implicit.from <= explicit.from && implicit.to >= explicit.to)
                );
                if (!overlaps) {
                    allSpans.push(implicit);
                }
            }
        }

        allSpans.sort((a, b) => a.from - b.from);

        const filteredSpans = allSpans.filter(span => {
            // @ts-ignore
            if (span.type === 'entity_ref' && !this.enableEntityRefs) return false;
            return true;
        });

        const combinedSpans = [...filteredSpans, ...keywordSpans, ...analyticsSpans];
        combinedSpans.sort((a, b) => a.from - b.from);

        // Emit to ScanCoordinator for entity-event tracking
        if (this.currentNoteId) {
            const entitySpans = combinedSpans.filter(s =>
                s.type === 'entity' ||
                s.type === 'entity_ref' ||
                s.type === 'relationship' ||
                s.type === 'predicate'
            );
            for (const span of entitySpans) {
                getScanCoordinator().onEntityDecoration(span, this.currentNoteId);
            }
        }

        return combinedSpans;
    }

    getImplicitDecorations(doc: ProseMirrorDoc): DecorationSpan[] {
        const text = docContent(doc);
        const currentHash = hashContent(text);
        if (this.implicitDecorationsHash !== currentHash) {
            return [];
        }
        return this.implicitDecorations.filter(span => span.type === 'entity_implicit');
    }

    /** Async scan that waits for Phoenix native to return spans (used on note open) */
    async scanForSpansAsync(doc: ProseMirrorDoc): Promise<DecorationSpan[]> {
        if (!scanPipeline) return [];

        const { text, segments } = extractText(doc);
        if (segments.length === 0) return [];

        console.log(`[PrettyTextAPI] scanForSpansAsync: ${text.length} chars, ${segments.length} segments`);

        const { highlights } = await scanPipeline.run(text, {
            skipDiscovery: true,
            skipGraph: true,
        });

        const { spans, dropped, crossed } = remapSpansPermissive(highlights, segments);
        console.log(`[PrettyTextAPI] Mapped ${spans.length} spans. Dropped: ${dropped}, Crossed: ${crossed}.`);

        return spans;
    }

    // ── Style / Config ────────────────────────────────────────────────────

    getStyle(span: DecorationSpan): string {
        const mode = highlightingStore.getMode();
        return getDecorationStyle(span, mode);
    }

    getClass(span: DecorationSpan): string {
        return getDecorationClass(span);
    }

    getMode(): HighlightMode {
        return highlightingStore.getMode();
    }

    setMode(mode: HighlightMode): void {
        highlightingStore.setMode(mode);
    }

    getConfig(): HighlighterConfig {
        const settings = highlightingStore.getSettings();
        return {
            mode: settings.mode,
            enableWikilinks: true, // Always on in Highlighter C
            enableEntityRefs: this.enableEntityRefs,
        };
    }

    setConfig(config: Partial<HighlighterConfig>): void {
        if (config.mode) highlightingStore.setMode(config.mode);
        if (config.enableEntityRefs !== undefined) {
            this.enableEntityRefs = config.enableEntityRefs;
            this.notifyListeners();
        }
    }

    subscribe(callback: () => void): () => void {
        this.listeners.add(callback);
        return () => this.listeners.delete(callback);
    }

    // ── Internal Pipeline Integration ─────────────────────────────────────

    private async tryLoadCachedOrScan(
        doc: ProseMirrorDoc,
        text: string,
        options: Required<Pick<ImplicitRefreshOptions, 'useCache' | 'allowRealign' | 'rescanAfterRealign'>> & { requestId: number }
    ): Promise<void> {
        if (!this.currentNoteId || !options.useCache) {
            this.triggerPipelineScan(doc, text, options.requestId);
            return;
        }

        const noteId = this.currentNoteId;
        const currentHash = hashContent(text);

        try {
            const cached = await getNoteDecorations(noteId);
            if (!this.isCurrentRefreshRequest(options.requestId, noteId)) {
                return;
            }

            if (cached) {
                const storedHash = await getDecorationContentHash(noteId);
                if (!this.isCurrentRefreshRequest(options.requestId, noteId)) {
                    return;
                }

                const filteredCached = filterCachedEntitySpans(cached, smartGraphRegistry);

                if (filteredCached.length !== cached.length) {
                    await saveNoteDecorations(noteId, filteredCached, storedHash ?? currentHash);
                }

                if (storedHash === currentHash) {
                    this.applyImplicitDecorations(filteredCached, currentHash);
                    return;
                }

                if (options.allowRealign) {
                    const realigned = realignSpans(filteredCached, text);
                    const filteredRealigned = filterCachedEntitySpans(realigned, smartGraphRegistry);
                    if (filteredRealigned.length > 0) {
                        if (filteredRealigned.length !== realigned.length) {
                            await saveNoteDecorations(noteId, filteredRealigned, currentHash);
                        }
                        if (!this.isCurrentRefreshRequest(options.requestId, noteId)) {
                            return;
                        }
                        this.applyImplicitDecorations(filteredRealigned, currentHash);
                        if (options.rescanAfterRealign) {
                            this.triggerPipelineScan(doc, text, options.requestId);
                        }
                        return;
                    }
                }
            }
        } catch (err) {
            console.warn('[PrettyTextAPI] Dexie read failed:', err);
        }

        if (!this.isCurrentRefreshRequest(options.requestId, noteId)) {
            return;
        }

        this.triggerPipelineScan(doc, text, options.requestId);
    }

    private getAnalyticsHighlightSpans(
        segments: ReturnType<typeof extractProjectedText>['segments'],
    ): DecorationSpan[] {
        const selections = analyticsHighlightStore.getSelections(this.currentNoteId)
            .filter(selection => selection.ranges.length > 0);
        if (selections.length === 0) {
            this.analyticsHighlightSpans = [];
            return [];
        }

        const rawSpans = selections.flatMap(selection =>
            selection.ranges
                .filter((range: AnalyticsHighlightRange) => range.to > range.from)
                .map((range: AnalyticsHighlightRange, index: number) => ({
                    type: 'analytics_highlight' as const,
                    from: range.from,
                    to: range.to,
                    label: selection.label,
                    matchedText: range.text,
                    highlightKind: selection.kind,
                    analyticsPaletteKey: selection.paletteKey,
                    annotationId: `${selection.key}:${index}`,
                })),
        );

        this.analyticsHighlightSpans = remapSpansPermissive(rawSpans, segments).spans;
        return this.analyticsHighlightSpans;
    }

    private triggerPipelineScan(doc: ProseMirrorDoc, text?: string, requestId?: number) {
        if (!scanPipeline) return;

        const myVersion = ++this.scanVersion;
        const { text: fullText, segments } = extractText(doc);
        const scanText = text || fullText;

        if (segments.length === 0) {
            this.applyImplicitDecorations([], null);
            return;
        }

        const noteIdForSave = this.currentNoteId;
        const contentHashForSave = hashContent(scanText);
        const pipelinePromise = scanPipeline.run(scanText, {
            skipDiscovery: true,
            skipGraph: true,
        });

        pipelinePromise.then(async (result) => {
            if (this.scanVersion !== myVersion) return;
            if (requestId !== undefined && !this.isCurrentRefreshRequest(requestId, noteIdForSave)) {
                return;
            }

            // Scanner spans are produced over flat note text. Historic marks can split
            // one entity surface across adjacent text nodes, so the highlight remapper
            // must preserve cross-segment entity spans instead of dropping them.
            const mergedSpans = remapSpansPermissive(result.highlights, segments).spans;
            this.applyImplicitDecorations(mergedSpans, contentHashForSave);

            // Save to Dexie cache
            if (noteIdForSave) {
                try {
                    await saveNoteDecorations(noteIdForSave, mergedSpans, contentHashForSave);
                } catch (err) {
                    console.warn('[PrettyTextAPI] Dexie write failed:', err);
                }
            }
        }).catch(console.error);
    }

    private applyImplicitDecorations(spans: DecorationSpan[], textHash: string | null): void {
        const changed = !this.spansEqual(this.implicitDecorations, spans) || this.implicitDecorationsHash !== textHash;
        this.implicitDecorations = spans;
        this.implicitDecorationsHash = textHash;
        if (changed) {
            this.notifyListeners();
        }
    }

    private isCurrentRefreshRequest(requestId: number, noteId: string): boolean {
        return requestId === this.refreshRequestVersion && noteId === this.currentNoteId;
    }

    private clearPendingImplicitRefresh(): void {
        if (!this.pendingImplicitRefreshTimer) {
            return;
        }
        clearTimeout(this.pendingImplicitRefreshTimer);
        this.pendingImplicitRefreshTimer = null;
    }

    // ── Utilities ──────────────────────────────────────────────────────────

    private createCandidateSpans(
        _text: string,
        candidates: Array<{ token: string; score: number }>,
        segments: Array<{ pmPos: number; concatStart: number; length: number; text: string }>,
    ): DecorationSpan[] {
        const spans: DecorationSpan[] = [];

        for (const seg of segments) {
            for (const candidate of candidates) {
                const tokenLower = candidate.token.toLowerCase();
                const regex = new RegExp(`\\b${this.escapeRegex(tokenLower)}\\b`, 'gi');
                let match: RegExpExecArray | null;

                while ((match = regex.exec(seg.text)) !== null) {
                    const from = seg.pmPos + match.index;
                    const to = seg.pmPos + match.index + match[0].length;

                    if (smartGraphRegistry.isRegisteredEntity(candidate.token)) continue;

                    const alreadyCovered = this.implicitDecorations.some(d =>
                        d.type === 'entity_implicit' && d.from <= from && d.to >= to
                    );

                    if (!alreadyCovered) {
                        spans.push({
                            type: 'entity_candidate',
                            from,
                            to,
                            label: candidate.token,
                            matchedText: String(candidate.score.toFixed(2)),
                            kind: 'UNKNOWN',
                            resolved: false,
                        });
                    }
                }
            }
        }

        return spans;
    }

    private escapeRegex(str: string): string {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    private spansEqual(a: DecorationSpan[], b: DecorationSpan[]): boolean {
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) {
            if (a[i].from !== b[i].from || a[i].to !== b[i].to || a[i].label !== b[i].label) {
                return false;
            }
        }
        return true;
    }

    private detectSentenceEnd(text: string): boolean {
        const pos = text.length - 1;
        if (pos <= this.lastSentenceEndPos) return false;

        for (let i = pos; i >= Math.max(0, pos - 5); i--) {
            const char = text[i];
            if (char === '.' || char === '!' || char === '?') {
                this.lastSentenceEndPos = pos;
                return true;
            }
        }
        return false;
    }

    private notifyListeners() {
        this.listeners.forEach(cb => cb());
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Singleton management (backward compatible)
// ─────────────────────────────────────────────────────────────────────────────

let _instance: PrettyTextApi | null = null;

export function getPrettyTextApi(): PrettyTextApi {
    if (!_instance) {
        _instance = new PrettyTextAPI();
    }
    return _instance;
}

export const getHighlighterApi = getPrettyTextApi;

export function setPrettyTextApi(api: PrettyTextApi): void {
    _instance = api;
}

export const setHighlighterApi = setPrettyTextApi;
