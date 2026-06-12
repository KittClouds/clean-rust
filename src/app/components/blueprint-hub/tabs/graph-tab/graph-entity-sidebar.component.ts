import { CommonModule } from '@angular/common';
import { ScrollingModule } from '@angular/cdk/scrolling';
import { Component, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, computed, inject, signal } from '@angular/core';
import {
    BookOpen,
    BrainCircuit,
    Calendar,
    Check,
    ChevronDown,
    ChevronRight,
    Copy,
    Eye,
    Lightbulb,
    MapPin,
    Network,
    Package,
    PanelLeft,
    PanelLeftClose,
    Pencil,
    Plus,
    RefreshCw,
    Search,
    Sparkles,
    Trash2,
    User,
    Users,
    X,
} from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import { entitySourceLabel, type RegisteredEntity } from '../../../../lib/registry';
import type { EntitySuggestionProviderId } from '../../../../lib/entity-suggestions/entity-suggestion.types';
import { entityColorStore, normalizeEntityKind } from '../../../../lib/store/entityColorStore';
import type { NerSuggestion } from '../../../../services/ner.service';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GraphLensMode } from './graph-lens';
import {
    buildGraphDiscourseAnalyticsView,
    type GraphDiscourseTabId,
    type GraphDiscourseTone,
} from './graph-discourse-analytics';
import {
    buildGraphDiscourseWorkbenchView,
    type GraphDiscourseWorkbenchDecision,
    type GraphDiscourseWorkbenchRecord,
} from './graph-discourse-workbench';
import { buildProductDiagnosticsView, type ProductDiagnosticsView } from './graph-product-diagnostics';

interface EntityGroup {
    kind: string;
    entities: RegisteredEntity[];
    expanded: boolean;
}

type DiagnosticsQualityTone = 'ready' | 'review' | 'danger' | 'quiet';
type GraphSidebarView = 'entities' | 'diagnostics' | 'discourse';

interface DiagnosticsQualityLane {
    id: string;
    label: string;
    value: number;
    detail: string;
    tone: DiagnosticsQualityTone;
}

interface DiagnosticsReceiptView {
    id: string;
    label: string;
    detail: string;
    tone: DiagnosticsQualityTone;
}

interface DiagnosticsQualityView {
    modelLabel: string;
    summary: string;
    lanes: DiagnosticsQualityLane[];
    receipts: DiagnosticsReceiptView[];
}

type EntitySidebarRow =
    | { type: 'suggestion-group'; count: number }
    | { type: 'suggestion'; suggestion: NerSuggestion }
    | { type: 'group'; kind: string; count: number; expanded: boolean }
    | { type: 'entity'; entity: RegisteredEntity };

const ENTITY_ICONS: Record<string, any> = {
    CHARACTER: User,
    LOCATION: MapPin,
    NPC: Users,
    ITEM: Package,
    FACTION: Network,
    NETWORK: Network,
    EVENT: Calendar,
    CONCEPT: Lightbulb,
};

@Component({
    selector: 'app-graph-entity-sidebar',
    standalone: true,
    imports: [CommonModule, ScrollingModule, LucideAngularModule],
    templateUrl: './graph-entity-sidebar.component.html',
    styleUrls: ['./graph-entity-sidebar.component.css', './graph-entity-sidebar.review-clusters.css', './graph-entity-sidebar.discourse.css'],
})
export class GraphEntitySidebarComponent implements OnChanges, OnDestroy {
    private readonly graphRebuild = inject(GraphRebuildService);

    @Input() entities: RegisteredEntity[] = [];
    @Input() suggestions: NerSuggestion[] = [];
    @Input() selectedEntity: RegisteredEntity | null = null;
    @Input() linkCount = 0;
    @Input() lensMode: GraphLensMode = 'global';
    @Input() isScanning = false;
    @Input() scanError: string | null = null;
    @Input() contextId = 'global';
    @Input() searchText = '';

    @Output() entitySelected = new EventEmitter<RegisteredEntity>();
    @Output() editEntityRequested = new EventEmitter<RegisteredEntity>();
    @Output() deleteEntityRequested = new EventEmitter<RegisteredEntity>();
    @Output() addEntityRequested = new EventEmitter<void>();
    @Output() flushRequested = new EventEmitter<void>();
    @Output() acceptSuggestionRequested = new EventEmitter<string>();
    @Output() rejectSuggestionRequested = new EventEmitter<string>();
    @Output() styleRequested = new EventEmitter<void>();
    @Output() scanRequested = new EventEmitter<void>();
    @Output() lensModeChange = new EventEmitter<GraphLensMode>();
    @Output() searchTextChange = new EventEmitter<string>();

    readonly isOpen = signal(true);
    readonly sidebarView = signal<GraphSidebarView>('entities');
    readonly entitySearch = signal('');
    readonly expandedKinds = signal<Set<string>>(new Set());
    readonly diagnosticsSnapshot = signal<GraphRebuildSnapshot | null>(null);
    readonly diagnosticsLoading = signal(false);
    readonly diagnosticsError = signal<string | null>(null);
    readonly selectedDiscourseTab = signal<GraphDiscourseTabId>('ideas');
    readonly selectedDiscourseRecordId = signal('');
    readonly discourseRecordDecisions = signal<Record<string, GraphDiscourseWorkbenchDecision>>({});
    readonly underlyingIdeasOpen = signal(false);
    readonly discourseActionNotice = signal('');
    readonly focusedDiscourseQuery = signal('');
    private readonly selectedDiagnosticsEntity = signal<RegisteredEntity | null>(null);
    private readonly dataRevision = signal(0);
    private discourseNoticeTimer: ReturnType<typeof setTimeout> | undefined;
    private readonly unsubscribeColors = entityColorStore.subscribe(() => {
        this.dataRevision.update((revision) => revision + 1);
    });

    readonly rows = computed<EntitySidebarRow[]>(() => {
        this.dataRevision();
        return this.flattenRows(this.groupedEntities());
    });
    readonly productDiagnostics = computed(() =>
        buildProductDiagnosticsView(this.diagnosticsSnapshot(), this.selectedDiagnosticsEntity()),
    );
    readonly stage8Diagnostics = computed(() =>
        buildDiagnosticsQualityView(this.diagnosticsSnapshot(), this.productDiagnostics()),
    );
    readonly discourseAnalytics = computed(() => {
        this.dataRevision();
        return buildGraphDiscourseAnalyticsView(
            this.diagnosticsSnapshot(),
            this.productDiagnostics(),
            this.selectedDiagnosticsEntity(),
            this.entities,
        );
    });
    readonly activeDiscoursePanel = computed(() => {
        const discourse = this.discourseAnalytics();
        return discourse?.panels[this.selectedDiscourseTab()] ?? null;
    });
    readonly discourseWorkbench = computed(() => {
        this.dataRevision();
        return buildGraphDiscourseWorkbenchView(this.diagnosticsSnapshot(), this.entities);
    });
    readonly activeDiscourseRecords = computed(() => {
        const workbench = this.discourseWorkbench();
        return workbench?.recordsByTab[this.selectedDiscourseTab()] ?? [];
    });
    readonly selectedDiscourseRecord = computed(() => {
        const records = this.activeDiscourseRecords();
        const selectedId = this.selectedDiscourseRecordId();
        return records.find((record) => record.id === selectedId) ?? records[0] ?? null;
    });
    readonly primaryDiscourseQuestion = computed(() => this.discourseAnalytics()?.questions[0] ?? null);

    readonly lensModes: { id: GraphLensMode; label: string }[] = [
        { id: 'global', label: 'Global' },
        { id: 'narrative', label: 'Narrative' },
        { id: 'note', label: 'Note' },
        { id: 'multiNote', label: 'Compare' },
    ];

    readonly BookIcon = BookOpen;
    readonly BrainIcon = BrainCircuit;
    readonly CheckIcon = Check;
    readonly ChevronDownIcon = ChevronDown;
    readonly ChevronRightIcon = ChevronRight;
    readonly CopyIcon = Copy;
    readonly EyeIcon = Eye;
    readonly NetworkIcon = Network;
    readonly PanelLeftIcon = PanelLeft;
    readonly PanelLeftCloseIcon = PanelLeftClose;
    readonly PencilIcon = Pencil;
    readonly PlusIcon = Plus;
    readonly RefreshIcon = RefreshCw;
    readonly SearchIcon = Search;
    readonly SparklesIcon = Sparkles;
    readonly TrashIcon = Trash2;
    readonly XIcon = X;

    private readonly snapshotUpdated = (event: Event) => {
        const detail = (event as CustomEvent<{ scopeId?: string }>).detail;
        if (!detail?.scopeId || detail.scopeId === this.contextId) void this.refreshDiagnosticsSnapshot();
    };

    constructor() {
        if (typeof window !== 'undefined') {
            window.addEventListener('graph-rebuild-snapshot-updated', this.snapshotUpdated);
            window.addEventListener('graph-index-run-completed', this.snapshotUpdated);
        }
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['entities']) {
            const nextKinds = new Set(this.entities.map((entity) => this.canonicalKind(entity.kind)));
            this.expandedKinds.update((current) => new Set([...current, ...nextKinds]));
            this.dataRevision.update((value) => value + 1);
        }
        if (changes['suggestions']) {
            this.dataRevision.update((value) => value + 1);
        }
        if (changes['selectedEntity']) {
            this.selectedDiagnosticsEntity.set(this.selectedEntity);
        }
        if (changes['searchText'] && this.searchText !== this.entitySearch()) {
            this.entitySearch.set(this.searchText || '');
            this.dataRevision.update((value) => value + 1);
        }
        if (changes['contextId']) {
            void this.refreshDiagnosticsSnapshot();
        }
    }

    ngOnDestroy(): void {
        this.unsubscribeColors();
        if (this.discourseNoticeTimer) clearTimeout(this.discourseNoticeTimer);
        if (typeof window !== 'undefined') {
            window.removeEventListener('graph-rebuild-snapshot-updated', this.snapshotUpdated);
            window.removeEventListener('graph-index-run-completed', this.snapshotUpdated);
        }
    }

    updateEntitySearch(value: string): void {
        this.entitySearch.set(value);
        this.searchTextChange.emit(value);
        this.dataRevision.update((revision) => revision + 1);
    }

    toggleOpen(): void {
        this.isOpen.update((open) => !open);
    }

    setSidebarView(view: GraphSidebarView): void {
        this.sidebarView.set(view);
        if (view !== 'entities' && !this.diagnosticsSnapshot()) void this.refreshDiagnosticsSnapshot();
    }

    reloadGraphSidebarSnapshot(): void {
        void this.refreshDiagnosticsSnapshot();
    }

    toggleControls(): void {
        this.setSidebarView(this.sidebarView() === 'diagnostics' ? 'entities' : 'diagnostics');
    }

    toggleActions(): void {
        this.toggleControls();
    }

    setDiscourseTab(tab: GraphDiscourseTabId): void {
        this.selectedDiscourseTab.set(tab);
        this.selectedDiscourseRecordId.set(this.discourseWorkbench()?.recordsByTab[tab]?.[0]?.id || '');
    }

    toggleUnderlyingIdeas(): void {
        this.underlyingIdeasOpen.update((open) => !open);
    }

    toneClass(prefix: string, tone: GraphDiscourseTone | DiagnosticsQualityTone): string {
        return `${prefix}-${tone}`;
    }

    async copyDiscourseSummary(): Promise<void> {
        const discourse = this.discourseAnalytics();
        const panel = this.activeDiscoursePanel();
        if (!discourse || !panel) return;
        const text = [
            discourse.title,
            discourse.summary,
            '',
            `${panel.title}: ${panel.summary}`,
            ...panel.bullets.map((bullet) => `- ${bullet}`),
            '',
            ...discourse.questions.map((question) => `Question: ${question.prompt}`),
        ].join('\n');
        await navigator.clipboard?.writeText(text);
        this.flashDiscourseNotice('Copied discourse read');
    }

    selectDiscourseRecord(recordId: string, event?: Event): void {
        event?.stopPropagation();
        this.selectedDiscourseRecordId.set(recordId);
    }

    focusDiscourseRecord(record: GraphDiscourseWorkbenchRecord, event?: Event): void {
        event?.stopPropagation();
        const focus = record.focusQuery.trim();
        if (!focus) return;
        this.focusedDiscourseQuery.set(focus);
        this.searchTextChange.emit(focus);
        this.flashDiscourseNotice('Atlas focus updated');
    }

    async copyDiscourseRecord(record: GraphDiscourseWorkbenchRecord, event?: Event): Promise<void> {
        event?.stopPropagation();
        await navigator.clipboard?.writeText(this.discourseRecordText(record));
        this.flashDiscourseNotice('Copied discourse record');
    }

    stageDiscourseRecordDecision(
        record: GraphDiscourseWorkbenchRecord,
        decision: GraphDiscourseWorkbenchDecision,
        event?: Event,
    ): void {
        event?.stopPropagation();
        this.discourseRecordDecisions.update((current) => ({ ...current, [record.id]: decision }));
        this.selectedDiscourseRecordId.set(record.id);
        this.flashDiscourseNotice(`Staged ${decision}`);
    }

    stagedDiscourseDecision(record: GraphDiscourseWorkbenchRecord): GraphDiscourseWorkbenchDecision | '' {
        return this.discourseRecordDecisions()[record.id] || '';
    }

    isDiscourseRecordSelected(record: GraphDiscourseWorkbenchRecord): boolean {
        return this.selectedDiscourseRecord()?.id === record.id;
    }

    hasDiscourseAction(record: GraphDiscourseWorkbenchRecord, actionKind: string): boolean {
        return record.actionKinds.includes(actionKind);
    }

    highlightDiscourseQuery(query: string): void {
        const focus = query.trim();
        if (!focus) return;
        this.focusedDiscourseQuery.set(focus);
        this.sidebarView.set('discourse');
        this.flashDiscourseNotice('Discourse focus updated');
    }

    isFocusedDiscourseQuery(query: string): boolean {
        const focus = this.focusedDiscourseQuery().trim().toLowerCase();
        return !!focus && query.trim().toLowerCase() === focus;
    }

    toggleKind(kind: string): void {
        this.expandedKinds.update((current) => {
            const next = new Set(current);
            next.has(kind) ? next.delete(kind) : next.add(kind);
            return next;
        });
    }

    getIcon(kind: string): any {
        return ENTITY_ICONS[this.canonicalKind(kind)] || Sparkles;
    }

    getColor(kind: string): string {
        return entityColorStore.getEntityColor(this.canonicalKind(kind));
    }

    getEntityBadgeColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityColor(this.canonicalKind(entity.kind));
    }

    getEntityBadgeBgColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityBgColor(this.canonicalKind(entity.kind), 0.13);
    }

    getEntityBadgeBorderColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityBgColor(this.canonicalKind(entity.kind), 0.34);
    }

    displayKind(kind: string): string {
        return this.canonicalKind(kind);
    }

    getEntitySourceLabel(entity: RegisteredEntity): string {
        return entitySourceLabel(entity);
    }

    trackRow(_index: number, row: EntitySidebarRow): string {
        if (row.type === 'suggestion-group') return 'suggestion-group';
        if (row.type === 'suggestion') return `suggestion:${row.suggestion.id}`;
        return row.type === 'group' ? `group:${row.kind}` : `entity:${row.entity.id}`;
    }

    editClicked(entity: RegisteredEntity, event: Event): void {
        event.stopPropagation();
        this.editEntityRequested.emit(entity);
    }

    deleteClicked(entity: RegisteredEntity, event: Event): void {
        event.stopPropagation();
        this.deleteEntityRequested.emit(entity);
    }

    acceptSuggestionClicked(id: string, event: Event): void {
        event.stopPropagation();
        this.acceptSuggestionRequested.emit(id);
    }

    rejectSuggestionClicked(id: string, event: Event): void {
        event.stopPropagation();
        this.rejectSuggestionRequested.emit(id);
    }

    confidencePercent(value: number): number {
        return Math.round(Math.max(0, Math.min(1, value || 0)) * 100);
    }

    scorePercent(value: number): number {
        return this.confidencePercent(value);
    }

    sourceLabel(source: EntitySuggestionProviderId): string {
        if (source === 'atlas_surface') return 'Atlas Surface';
        if (source === 'dynamic_ner') return 'Dynamic NER';
        if (source === 'lfm_local_experiment') return 'LFM';
        if (source === 'gliner_local') return 'GLiNER';
        return 'Phoenix';
    }

    private flashDiscourseNotice(message: string): void {
        this.discourseActionNotice.set(message);
        if (this.discourseNoticeTimer) clearTimeout(this.discourseNoticeTimer);
        this.discourseNoticeTimer = setTimeout(() => this.discourseActionNotice.set(''), 2400);
    }

    private discourseRecordText(record: GraphDiscourseWorkbenchRecord): string {
        return [
            record.title,
            record.subtitle,
            record.detail,
            '',
            `Kind: ${record.kind}`,
            `Status: ${record.status}`,
            `Score: ${record.scoreLabel}`,
            record.candidateId ? `Candidate: ${record.candidateId}` : '',
            record.decisionId ? `Decision: ${record.decisionId}` : '',
            record.sourceIds.length ? `Sources: ${record.sourceIds.join(', ')}` : '',
            record.targetIds.length ? `Targets: ${record.targetIds.join(', ')}` : '',
            record.evidenceIds.length ? `Evidence: ${record.evidenceIds.join(', ')}` : '',
            '',
            ...record.facts.map((fact) => `${fact.label}: ${fact.value}`),
            '',
            ...record.rationale.map((line) => `- ${line}`),
        ].filter(Boolean).join('\n');
    }

    private groupedEntities(): EntityGroup[] {
        const query = this.entitySearch().trim().toLowerCase();
        const groups = new Map<string, RegisteredEntity[]>();
        for (const entity of this.entities) {
            if (query && !this.matchesQuery(entity, query)) continue;
            const kind = this.canonicalKind(entity.kind);
            const list = groups.get(kind) ?? [];
            list.push(entity);
            groups.set(kind, list);
        }
        const expanded = this.expandedKinds();
        return [...groups.entries()]
            .sort(([left], [right]) => left.localeCompare(right))
            .map(([kind, entities]) => ({
                kind,
                entities: entities.sort((left, right) => left.label.localeCompare(right.label)),
                expanded: expanded.has(kind),
            }));
    }

    private flattenRows(groups: EntityGroup[]): EntitySidebarRow[] {
        const rows: EntitySidebarRow[] = [];
        const suggestions = this.filteredSuggestions();
        if (suggestions.length) {
            rows.push({ type: 'suggestion-group', count: suggestions.length });
            rows.push(...suggestions.map((suggestion) => ({ type: 'suggestion' as const, suggestion })));
        }
        for (const group of groups) {
            rows.push({ type: 'group', kind: group.kind, count: group.entities.length, expanded: group.expanded });
            if (group.expanded) rows.push(...group.entities.map((entity) => ({ type: 'entity' as const, entity })));
        }
        return rows;
    }

    private filteredSuggestions(): NerSuggestion[] {
        const query = this.entitySearch().trim().toLowerCase();
        return this.suggestions
            .filter((suggestion) => !query || this.matchesSuggestionQuery(suggestion, query))
            .sort((left, right) => right.confidence - left.confidence || left.label.localeCompare(right.label));
    }

    private matchesQuery(entity: RegisteredEntity, query: string): boolean {
        const kind = this.canonicalKind(entity.kind);
        return entity.label.toLowerCase().includes(query)
            || kind.toLowerCase().includes(query)
            || entity.aliases.some((alias) => alias.toLowerCase().includes(query));
    }

    private matchesSuggestionQuery(suggestion: NerSuggestion, query: string): boolean {
        const kind = this.canonicalKind(suggestion.kind);
        return suggestion.label.toLowerCase().includes(query)
            || kind.toLowerCase().includes(query)
            || this.sourceLabel(suggestion.source).toLowerCase().includes(query);
    }

    private canonicalKind(kind: string): string {
        return normalizeEntityKind(kind) || kind;
    }

    private async refreshDiagnosticsSnapshot(): Promise<void> {
        const scopeId = this.contextId || 'global';
        this.diagnosticsLoading.set(true);
        try {
            const snapshot = await this.graphRebuild.loadPersistedSnapshot(scopeId);
            this.diagnosticsSnapshot.set(snapshot);
            this.diagnosticsError.set(null);
        } catch (error) {
            this.diagnosticsError.set(error instanceof Error ? error.message : String(error));
        } finally {
            this.diagnosticsLoading.set(false);
        }
    }
}

function buildDiagnosticsQualityView(
    snapshot: GraphRebuildSnapshot | null,
    diagnostics: ProductDiagnosticsView | null,
): DiagnosticsQualityView | null {
    if (!snapshot || !diagnostics) return null;
    const counters = snapshot.counters;
    const finalLog = snapshot.finalLinkPatchLog;
    const receiptFailures = finalLog?.counters.failedReceipts || counters.finalLinkReceiptFailures || 0;
    const reviewTotal = diagnostics.reviewClusters.length
        + (snapshot.resolutionSuggestions?.length || 0)
        + (finalLog?.counters.planned || 0);
    const frameCount = (counters.meaningFrameChunks || 0)
        + counters.relationships
        + counters.events;
    const evidenceCount = counters.anchorEvidence || snapshot.entityAnchors.length;
    const temporalCount = counters.temporalEdges + counters.causalEdges + counters.memoryState;
    const lanes: DiagnosticsQualityLane[] = [
        qualityLane('identity', 'Identity', counters.entityLinking?.candidateLinks || counters.shadowLinkSuggestions || 0, `${counters.entityLinking?.sameEntity || 0} same / ${counters.entityLinking?.ambiguous || 0} ambiguous`, reviewTotal ? 'review' : 'quiet'),
        qualityLane('frames', 'Frames', frameCount, `${counters.relationships} relations / ${counters.events} events`, frameCount ? 'ready' : 'quiet'),
        qualityLane('evidence', 'Evidence', evidenceCount, `${counters.mentions} mentions / ${counters.acceptedAnchors} anchors`, evidenceCount ? 'ready' : 'quiet'),
        qualityLane('temporal', 'Temporal', temporalCount, `${counters.temporalEdges} temporal / ${counters.memoryState} memory`, temporalCount ? 'ready' : 'quiet'),
        qualityLane('review', 'Review', reviewTotal, `${diagnostics.reviewClusters.length} families / ${finalLog?.counters.planned || 0} patches`, receiptFailures ? 'danger' : reviewTotal ? 'review' : 'quiet'),
        qualityLane('router', 'Router', counters.embeddingTargets, `${counters.embeddingTargets} targets / ${counters.embeddingVectors} vectors`, counters.embeddingVectors ? 'ready' : 'quiet'),
    ];
    const receipts: DiagnosticsReceiptView[] = [
        ...(snapshot.graphCompileReceipts?.invariantFailures || []).map((failure, index) => ({
            id: `compiler:${index}`,
            label: 'Compiler invariant',
            detail: failure,
            tone: 'danger' as const,
        })),
        ...(finalLog?.receipts || []).map((receipt) => ({
            id: receipt.id,
            label: receipt.invariant,
            detail: receipt.detail,
            tone: receipt.status === 'failed' ? 'danger' as const : 'ready' as const,
        })),
    ].slice(0, 4);
    return {
        modelLabel: `${diagnostics.modelLabel} / ${diagnostics.dimensionLabel}`,
        summary: `${diagnostics.summary.targetCount} targets / ${diagnostics.summary.clusterCount} clusters / ${reviewTotal} review`,
        lanes,
        receipts,
    };
}

function qualityLane(
    id: string,
    label: string,
    value: number,
    detail: string,
    tone: DiagnosticsQualityTone,
): DiagnosticsQualityLane {
    return { id, label, value, detail, tone };
}
