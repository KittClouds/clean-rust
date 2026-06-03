import { CommonModule } from '@angular/common';
import { ScrollingModule } from '@angular/cdk/scrolling';
import { Component, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, computed, inject, signal } from '@angular/core';
import {
    BookOpen,
    Calendar,
    Check,
    ChevronDown,
    ChevronRight,
    Lightbulb,
    MapPin,
    Package,
    PanelLeft,
    PanelLeftClose,
    Pencil,
    Plus,
    Search,
    Shield,
    Sparkles,
    Trash2,
    User,
    Users,
    X,
} from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import { entitySourceLabel, type RegisteredEntity } from '../../../../lib/registry';
import type { EntitySuggestionProviderId } from '../../../../lib/entity-suggestions/entity-suggestion.types';
import { entityColorStore } from '../../../../lib/store/entityColorStore';
import type { NerSuggestion } from '../../../../services/ner.service';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GraphLensMode } from './graph-lens';
import { buildProductDiagnosticsView, type ProductDiagnosticsView } from './graph-product-diagnostics';

interface EntityGroup {
    kind: string;
    entities: RegisteredEntity[];
    expanded: boolean;
}

type DiagnosticsQualityTone = 'ready' | 'review' | 'danger' | 'quiet';

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
    FACTION: Shield,
    EVENT: Calendar,
    CONCEPT: Lightbulb,
};

@Component({
    selector: 'app-graph-entity-sidebar',
    standalone: true,
    imports: [CommonModule, ScrollingModule, LucideAngularModule],
    templateUrl: './graph-entity-sidebar.component.html',
    styleUrls: ['./graph-entity-sidebar.component.css', './graph-entity-sidebar.review-clusters.css'],
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
    readonly controlsOpen = signal(false);
    readonly entitySearch = signal('');
    readonly expandedKinds = signal<Set<string>>(new Set());
    readonly diagnosticsSnapshot = signal<GraphRebuildSnapshot | null>(null);
    readonly diagnosticsLoading = signal(false);
    readonly diagnosticsError = signal<string | null>(null);
    private readonly selectedDiagnosticsEntity = signal<RegisteredEntity | null>(null);
    private readonly dataRevision = signal(0);
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

    readonly lensModes: { id: GraphLensMode; label: string }[] = [
        { id: 'global', label: 'Global' },
        { id: 'narrative', label: 'Narrative' },
        { id: 'note', label: 'Note' },
        { id: 'multiNote', label: 'Compare' },
    ];

    readonly BookIcon = BookOpen;
    readonly CheckIcon = Check;
    readonly ChevronDownIcon = ChevronDown;
    readonly ChevronRightIcon = ChevronRight;
    readonly PanelLeftIcon = PanelLeft;
    readonly PanelLeftCloseIcon = PanelLeftClose;
    readonly PencilIcon = Pencil;
    readonly PlusIcon = Plus;
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
            const nextKinds = new Set(this.entities.map((entity) => entity.kind));
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

    toggleControls(): void {
        this.controlsOpen.update((open) => !open);
        if (!this.diagnosticsSnapshot()) void this.refreshDiagnosticsSnapshot();
    }

    toggleActions(): void {
        this.toggleControls();
    }

    toggleKind(kind: string): void {
        this.expandedKinds.update((current) => {
            const next = new Set(current);
            next.has(kind) ? next.delete(kind) : next.add(kind);
            return next;
        });
    }

    getIcon(kind: string): any {
        return ENTITY_ICONS[kind] || Sparkles;
    }

    getColor(kind: string): string {
        return entityColorStore.getEntityColor(kind);
    }

    getEntityBadgeColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityColor(entity.kind);
    }

    getEntityBadgeBgColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityBgColor(entity.kind, 0.13);
    }

    getEntityBadgeBorderColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityBgColor(entity.kind, 0.34);
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

    private groupedEntities(): EntityGroup[] {
        const query = this.entitySearch().trim().toLowerCase();
        const groups = new Map<string, RegisteredEntity[]>();
        for (const entity of this.entities) {
            if (query && !this.matchesQuery(entity, query)) continue;
            const list = groups.get(entity.kind) ?? [];
            list.push(entity);
            groups.set(entity.kind, list);
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
        return entity.label.toLowerCase().includes(query)
            || entity.kind.toLowerCase().includes(query)
            || entity.aliases.some((alias) => alias.toLowerCase().includes(query));
    }

    private matchesSuggestionQuery(suggestion: NerSuggestion, query: string): boolean {
        return suggestion.label.toLowerCase().includes(query)
            || suggestion.kind.toLowerCase().includes(query)
            || this.sourceLabel(suggestion.source).toLowerCase().includes(query);
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
