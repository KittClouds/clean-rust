import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';

import { smartGraphRegistry, type RegisteredEntity } from '../../../../lib/registry';
import { EntitySelectionService } from '../../../../lib/services/entity-selection.service';
import { ScopeService } from '../../../../lib/services/scope.service';
import { NoteEditorStore } from '../../../../lib/store/note-editor.store';
import { parseContentToPlainText } from '../../../../lib/analytics';
import { clearRejectedSuggestionFeedback } from '../../../../lib/entity-learning/entity-feedback';
import { NerService } from '../../../../services/ner.service';
import { AtlasScanCoordinatorService } from '../../../../services/atlas-scan-coordinator.service';
import { PhoenixMachineControlService } from '../../../../services/phoenix-machine-control.service';
import { PhoenixProjectionService } from '../../../../services/phoenix-projection.service';
import { AtlasControlContractService } from '../../../../services/atlas-control-contract.service';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import { SearchPanelComponent } from '../../../search-panel/search-panel.component';
import {
    EntityCreatorData,
    EntityCreatorDialogComponent,
} from '../graph-tab/entity-creator-dialog/entity-creator-dialog.component';
import { GraphEntitySidebarComponent } from '../graph-tab/graph-entity-sidebar.component';
import type { AtlasPreviewEdge } from '../graph-tab/graph-atlas-preview/graph-atlas-preview.component';
import { buildGraphAtlasReadContext } from '../graph-tab/graph-atlas-preview/graph-atlas-read-context';
import { GraphStyleDrawerComponent } from '../graph-tab/graph-style-drawer/graph-style-drawer.component';
import type { GraphLensState } from '../graph-tab/graph-lens';
import type { GraphOperatingRoomId } from '../graph-tab/graph-operating-room';
import type { AtlasControlTone } from '../../../../graph-rebuild/atlas-control-contract';
import { buildAtlasControlReviewDeck } from './atlas-control-review';
import type {
    GraphPromotionVerdictCertificate,
    GraphPromotionVerdictGate,
    GraphPromotionVerdictRow,
    GraphPromotionTruthAtom,
} from '../../../../graph-rebuild/graph-promotion-verdict';

type AtlasWorkflowTone = 'ready' | 'review' | 'warning' | 'quiet';

interface AtlasWorkflowStep {
    id: string;
    label: string;
    value: string;
    detail: string;
    tone: AtlasWorkflowTone;
}

@Component({
    selector: 'app-attributes-tab',
    standalone: true,
    imports: [
        CommonModule,
        SearchPanelComponent,
        GraphEntitySidebarComponent,
        GraphStyleDrawerComponent,
        EntityCreatorDialogComponent,
    ],
    templateUrl: './attributes-tab.component.html',
    styleUrls: [
        './attributes-tab.component.css',
        './attributes-tab-promotion.component.css',
        './attributes-tab-workflow.component.css',
    ],
})
export class AttributesTabComponent {
    private readonly scopeService = inject(ScopeService);
    private readonly nerService = inject(NerService);
    private readonly noteStore = inject(NoteEditorStore);
    private readonly projection = inject(PhoenixProjectionService);
    private readonly atlasControl = inject(AtlasControlContractService);
    private readonly graphRebuild = inject(GraphRebuildService);
    private readonly machine = inject(PhoenixMachineControlService);
    private readonly entitySelection = inject(EntitySelectionService);
    private readonly atlasScan = inject(AtlasScanCoordinatorService);

    readonly entities = computed(() => this.projection.entities());
    readonly suggestions = this.nerService.suggestions;
    readonly graphLensMode = this.machine.graphLensMode;
    readonly graphSnapshot = this.graphRebuild.snapshot;
    readonly isScanningSuggestions = computed(() => this.nerService.isAnalyzing() || this.atlasScan.running());
    readonly suggestionError = computed(() => this.atlasScan.error() || this.nerService.errorMessage());
    readonly atlasSearch = signal('');
    readonly selectedEntity = signal<RegisteredEntity | null>(null);
    readonly isCreatorOpen = signal(false);
    readonly editingEntity = signal<EntityCreatorData | undefined>(undefined);
    readonly isStyleDrawerOpen = signal(false);
    readonly operatingRoom = signal<GraphOperatingRoomId>('metrics');
    readonly activeScope = this.scopeService.activeScope;

    readonly activeEntity = computed(() => {
        const local = this.selectedEntity();
        if (local) return local;
        const selectedId = this.entitySelection.selectedEntityId();
        return this.entities().find((entity) => entity.id === selectedId) ?? null;
    });
    readonly entityLabelById = computed(() => {
        const labels = new Map<string, string>();
        for (const entity of this.entities()) {
            labels.set(entity.id, entity.label);
            labels.set(cleanEntityLookupKey(entity.id), entity.label);
        }
        return labels;
    });

    readonly atlasEdges = computed<AtlasPreviewEdge[]>(() => {
        const entityIds = new Set(this.entities().map((entity) => entity.id));
        const seen = new Set<string>();
        const edges: AtlasPreviewEdge[] = [];

        for (const entity of this.entities()) {
            for (const edge of this.projection.getEdgesForEntity(entity.id)) {
                if (!entityIds.has(edge.sourceId) || !entityIds.has(edge.targetId)) continue;
                const id = edge.id || `${edge.sourceId}:${edge.type}:${edge.targetId}`;
                if (seen.has(id)) continue;
                seen.add(id);
                edges.push({
                    id,
                    sourceId: edge.sourceId,
                    targetId: edge.targetId,
                    type: edge.type,
                    confidence: edge.confidence,
                });
            }
        }

        return edges;
    });

    readonly reviewDeck = computed(() => buildAtlasControlReviewDeck(
        this.graphSnapshot(),
        this.entities(),
    ));
    readonly atlasControlContract = this.atlasControl.contract;
    readonly reviewAdjudicationCertificate = this.atlasControl.reviewCertificate;
    readonly reviewAdjudicationContract = this.atlasControl.reviewView;
    readonly governanceCertificate = computed(() => this.atlasControlContract().certificates.governance);
    readonly promotionCertificate = computed(() => this.atlasControlContract().certificates.promotion);
    readonly headerCards = computed(() => this.atlasControlContract().header);
    readonly workflowSteps = computed<AtlasWorkflowStep[]>(() => {
        return this.atlasControlContract().workflow.map((step) => ({
            id: step.id,
            label: step.label,
            value: step.valueLabel,
            detail: step.detail,
            tone: atlasToneFromContract(step.tone),
        }));
    });
    readonly promotionRows = computed(() =>
        this.promotionCertificate()?.rows.slice(0, 48) ?? [],
    );

    selectEntity(entity: RegisteredEntity): void {
        this.selectedEntity.set(entity);
        this.entitySelection.select(entity.id);
        this.machine.requestGraphFocus({
            query: entity.label,
            scope: this.machineScope(),
            title: entity.label,
        });
    }

    setOperatingRoom(room: GraphOperatingRoomId): void {
        this.operatingRoom.set(room);
    }

    openCreator(): void {
        this.editingEntity.set(undefined);
        this.isCreatorOpen.set(true);
    }

    editEntity(entity: RegisteredEntity): void {
        this.editingEntity.set({
            id: entity.id,
            label: entity.label,
            kind: entity.kind,
            aliases: entity.aliases || [],
        });
        this.isCreatorOpen.set(true);
    }

    async deleteEntity(entity: RegisteredEntity): Promise<void> {
        const deleted = await smartGraphRegistry.deleteEntity(entity.id);
        if (!deleted) return;
        if (this.selectedEntity()?.id === entity.id) this.selectedEntity.set(null);
        if (this.entitySelection.selectedEntityId() === entity.id) this.entitySelection.clear();
    }

    async onSaveEntity(data: EntityCreatorData): Promise<void> {
        if (data.id) {
            const updated = await smartGraphRegistry.updateEntityDurable(data.id, {
                label: data.label,
                kind: data.kind as any,
                aliases: data.aliases,
            });
            if (!updated) return;
            this.selectedEntity.set(updated);
            this.entitySelection.select(updated.id);
            return;
        }

        const context = this.manualEntityContext();
        const result = await smartGraphRegistry.registerEntity(
            data.label,
            data.kind as any,
            context.noteId,
            {
                source: 'user',
                aliases: data.aliases,
                attributes: context.narrativeId ? { narrativeId: context.narrativeId } : undefined,
            },
        );
        this.selectedEntity.set(result.entity);
        this.entitySelection.select(result.entity.id);
    }

    async flushRegistry(): Promise<void> {
        if (!confirm(`Delete all ${this.entities().length} entities? This cannot be undone.`)) return;
        const cleared = await smartGraphRegistry.clearAll();
        const clearedRejects = await Promise.all([
            clearRejectedSuggestionFeedback('atlas_surface'),
            clearRejectedSuggestionFeedback('dynamic_ner'),
        ]);
        if (cleared === 0 && clearedRejects.every((count) => count === 0)) return;
        this.selectedEntity.set(null);
        this.entitySelection.clear();
    }

    async runSuggestionScan(_source: 'sidebar' | 'canvas' = 'sidebar', lens?: GraphLensState): Promise<void> {
        const currentNote = this.noteStore.currentNote();
        if (!currentNote) return;
        const plainText = parseContentToPlainText(currentNote.content || currentNote.markdownContent || '');
        await this.nerService.runDynamicScan({
            noteId: currentNote.id,
            noteTitle: currentNote.title || 'Untitled Note',
            plainText,
        });

        if (!lens) return;
        const context = buildGraphAtlasReadContext(lens);
        this.machine.setScope(context.noteIds[0] || 'global');
    }

    async acceptSuggestion(id: string): Promise<void> {
        await this.nerService.acceptSuggestion(id);
    }

    async rejectSuggestion(id: string): Promise<void> {
        await this.nerService.rejectSuggestion(id);
    }

    openStyleDrawer(): void {
        this.isStyleDrawerOpen.set(true);
    }

    closeStyleDrawer(): void {
        this.isStyleDrawerOpen.set(false);
    }

    machineScope(): 'global' | string {
        const scope = this.activeScope();
        if (scope.type === 'global' || scope.scopeFolderId === 'vault:global') return 'global';
        return scope.scopeFolderId || scope.id || 'global';
    }

    percent(value: number): string {
        return `${Math.round(value * 100)}%`;
    }

    millis(value: number | undefined): string {
        return value === undefined ? '--' : `${value.toLocaleString()} ms`;
    }

    micros(value: number | undefined): string {
        return value === undefined ? '--' : `${value.toLocaleString()} us`;
    }

    compactId(value: string | undefined): string {
        if (!value) return '--';
        return value.length <= 18 ? value : value.slice(-18);
    }

    promotionVerdictLabel(row: GraphPromotionVerdictRow): string {
        return titleLabel(row.status);
    }

    promotionTruthLabel(row: GraphPromotionVerdictRow): string {
        const atomLabel = this.promotionAtomLabel(row.atom);
        if (atomLabel) return atomLabel;

        const truth = row.truth || {};
        const subject = cleanUnknownText(truth.subject);
        const predicate = cleanUnknownText(truth.predicate);
        const object = cleanUnknownText(truth.object);
        if (subject && predicate && object) return `${subject} ${predicate} ${object}`;
        if (subject && object) return `${subject} -> ${object}`;
        return row.family || row.proposalId || row.id;
    }

    promotionTruthMeta(row: GraphPromotionVerdictRow): string {
        if (row.atom?.kind === 'edge') return `${titleLabel(edgeTypeLabel(row.atom.edge_type))} edge`;
        if (row.atom?.kind === 'vertex') return 'Vertex atom';
        return titleLabel(row.family);
    }

    promotionGateLabel(row: GraphPromotionVerdictRow): string {
        const blocking = row.gates.filter((gate) => gate.status === 'block').length;
        const passed = row.gates.filter((gate) => gate.status === 'pass' || gate.status === 'override').length;
        return blocking > 0 ? `${blocking} blocked / ${passed} passed` : `${passed} passed`;
    }

    promotionGateChipLabel(gate: GraphPromotionVerdictGate): string {
        return titleLabel(gate.kind);
    }

    promotionGateTitle(gate: GraphPromotionVerdictGate): string {
        return `${titleLabel(gate.kind)}: ${gate.summary}`;
    }

    promotionApplyLabel(row: GraphPromotionVerdictRow): string {
        return row.applyPlan.operation ? titleLabel(row.applyPlan.operation) : 'No write';
    }

    promotionRollbackLabel(row: GraphPromotionVerdictRow): string {
        if (row.rollbackPlan.availableNow) return 'Ready';
        if (row.rollbackPlan.availableAfterCommit) return 'After commit';
        return 'Unavailable';
    }

    promotionTiming(certificate: GraphPromotionVerdictCertificate | null): string {
        const micros = this.graphSnapshot()?.buildTimings?.nativePromotionVerdictRustMicros;
        if (micros !== undefined) return this.micros(micros);
        return certificate ? 'attached' : '--';
    }

    private promotionAtomLabel(atom: GraphPromotionTruthAtom | undefined): string {
        if (!atom) return '';
        if (atom.kind === 'vertex') return this.entityLabel(atom.vertex_id);
        const source = this.entityLabel(atom.source_id);
        const relation = titleLabel(edgeTypeLabel(atom.edge_type));
        const target = this.entityLabel(atom.target_id);
        if (!source || !target) return '';
        return `${source} -> ${relation} -> ${target}`;
    }

    private entityLabel(rawId: string): string {
        const id = cleanUnknownText(rawId);
        if (!id) return '';
        const labels = this.entityLabelById();
        return labels.get(id)
            ?? labels.get(cleanEntityLookupKey(id))
            ?? titleLabel(cleanEntityLookupKey(id));
    }

    private manualEntityContext(): { noteId: string; narrativeId?: string } {
        const currentNote = this.noteStore.currentNote();
        const scope = this.activeScope();
        return {
            noteId: currentNote?.id || scope.selectedNoteId || (scope.type === 'note' ? scope.id : 'manual'),
            narrativeId: currentNote?.narrativeId || scope.narrativeId || (scope.type === 'narrative' ? scope.id : undefined),
        };
    }
}

function atlasToneFromContract(tone: AtlasControlTone): AtlasWorkflowTone {
    if (tone === 'danger' || tone === 'warning') return 'warning';
    return tone;
}

function titleLabel(value: string | undefined | null): string {
    if (!value) return '--';
    return value
        .replace(/([a-z])([A-Z])/g, '$1 $2')
        .replace(/[_:-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function cleanUnknownText(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function cleanEntityLookupKey(value: string): string {
    return value
        .trim()
        .replace(/^atom:entity:/, '')
        .replace(/^entity:/, '');
}

function edgeTypeLabel(value: string): string {
    return cleanUnknownText(value)
        .replace(/^semantic::/, '')
        .replace(/^relation::/, '');
}
