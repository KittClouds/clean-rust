import { Component, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { smartGraphRegistry } from '../../../../lib/registry';
import type { RegisteredEntity } from '../../../../lib/registry';
import { entityColorStore } from '../../../../lib/store/entityColorStore';
import { GraphDetailComponent } from './graph-detail/graph-detail.component';
import { GraphStyleDrawerComponent } from './graph-style-drawer/graph-style-drawer.component';
import type { AtlasPreviewEdge } from './graph-atlas-preview/graph-atlas-preview.component';
import { GraphEntitySidebarComponent } from './graph-entity-sidebar.component';
import { GraphLensWorkspaceComponent } from './graph-lens-workspace.component';
import { EntityCreatorDialogComponent, EntityCreatorData } from './entity-creator-dialog/entity-creator-dialog.component';
import { ScopeService } from '../../../../lib/services/scope.service';
import { NoteEditorStore } from '../../../../lib/store/note-editor.store';
import { parseContentToPlainText } from '../../../../lib/analytics';
import { NerService } from '../../../../services/ner.service';
import { PhoenixProjectionService } from '../../../../services/phoenix-projection.service';
import { PhoenixMachineControlService } from '../../../../services/phoenix-machine-control.service';
import { EntitySelectionService } from '../../../../lib/services/entity-selection.service';
import { AtlasScanCoordinatorService } from '../../../../services/atlas-scan-coordinator.service';
import type { AtlasMode } from './graph-atlas-preview/graph-atlas-preview.component';
import type { GraphLensState } from './graph-lens';
import { buildGraphAtlasReadContext } from './graph-atlas-preview/graph-atlas-read-context';
import { clearRejectedSuggestionFeedback } from '../../../../lib/entity-learning/entity-feedback';
import type { GraphOperatingRoomId } from './graph-operating-room';

@Component({
    selector: 'app-graph-tab',
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        GraphDetailComponent,
        GraphStyleDrawerComponent,
        GraphEntitySidebarComponent,
        GraphLensWorkspaceComponent,
        EntityCreatorDialogComponent,
    ],
    templateUrl: './graph-tab.component.html',
    styleUrl: './graph-tab.component.css'
})
export class GraphTabComponent {
    private scopeService = inject(ScopeService);
    private nerService = inject(NerService);
    private noteStore = inject(NoteEditorStore);
    private projection = inject(PhoenixProjectionService);
    private machine = inject(PhoenixMachineControlService);
    private entitySelection = inject(EntitySelectionService);
    private atlasScan = inject(AtlasScanCoordinatorService);

    // State — entities now derived from ScopeService signal
    entities = computed(() => this.projection.entities());
    selectedEntity = signal<RegisteredEntity | null>(null);
    graphLensMode = this.machine.graphLensMode;
    isCreatorOpen = signal(false);
    editingEntity = signal<EntityCreatorData | undefined>(undefined);
    isStyleDrawerOpen = signal(false);
    atlasSearch = signal('');
    atlasMode = signal<AtlasMode>('graph');
    operatingRoom = signal<GraphOperatingRoomId>('entities');

    // Scope state — driven by ScopeService
    scopeLabel = this.scopeService.scopeLabel;
    activeScope = this.scopeService.activeScope;

    suggestions = this.nerService.suggestions;
    isScanningSuggestions = computed(() => this.nerService.isAnalyzing() || this.atlasScan.running());
    activeSuggestionProvider = this.nerService.activeProvider;
    suggestionError = computed(() => this.atlasScan.error() || this.nerService.errorMessage());

    totalEntities = computed(() => this.entities().length);
    activeEntity = computed(() => {
        const local = this.selectedEntity();
        if (local) return local;
        const selectedId = this.entitySelection.selectedEntityId();
        return this.entities().find((entity) => entity.id === selectedId) ?? null;
    });
    selectedEntityConnectionCount = computed(() => {
        const entity = this.activeEntity();
        return entity ? this.projection.getEdgesForEntity(entity.id).length : 0;
    });
    atlasEdges = computed<AtlasPreviewEdge[]>(() => {
        const entityIds = new Set(this.entities().map((entity) => entity.id));
        const seen = new Set<string>();
        const edges: AtlasPreviewEdge[] = [];

        for (const entity of this.entities()) {
            for (const edge of this.projection.getEdgesForEntity(entity.id)) {
                if (!entityIds.has(edge.sourceId) || !entityIds.has(edge.targetId)) {
                    continue;
                }
                const id = edge.id || `${edge.sourceId}:${edge.type}:${edge.targetId}`;
                if (seen.has(id)) {
                    continue;
                }
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
    styleTargetKind = computed(() => this.activeEntity()?.kind ?? 'CHARACTER');
    stewardContextId = computed(() => this.machineScope());

    // No manual registry subscription needed — entities are a computed signal

    selectEntity(entity: RegisteredEntity) {
        this.selectedEntity.set(entity);
        this.entitySelection.select(entity.id);
        this.machine.requestGraphFocus({
            query: entity.label,
            scope: this.machineScope(),
            title: entity.label,
        });
    }

    showAtlas() {
        this.selectedEntity.set(null);
    }

    setOperatingRoom(room: GraphOperatingRoomId): void {
        this.operatingRoom.set(room);
        if (room === 'metrics') this.showAtlas();
    }

    toggleStyleDrawer() {
        this.isStyleDrawerOpen.update((open) => !open);
    }

    closeStyleDrawer() {
        this.isStyleDrawerOpen.set(false);
    }

    navigateToEntity(entity: RegisteredEntity) {
        this.selectedEntity.set(entity);
        this.entitySelection.select(entity.id);
        this.machine.requestGraphFocus({
            query: entity.label,
            scope: this.machineScope(),
            title: entity.label,
        });
    }

    openCreator() {
        this.editingEntity.set(undefined);
        this.isCreatorOpen.set(true);
    }

    editEntity(entity: RegisteredEntity, event?: Event) {
        event?.stopPropagation();
        this.editingEntity.set({
            id: entity.id,
            label: entity.label,
            kind: entity.kind,
            aliases: entity.aliases || [],
        });
        this.isCreatorOpen.set(true);
    }

    async deleteEntity(entity: RegisteredEntity, event: MouseEvent) {
        event.stopPropagation();
        await this.deleteEntityFromSidebar(entity);
    }

    async deleteEntityFromSidebar(entity: RegisteredEntity) {
        const deleted = await smartGraphRegistry.deleteEntity(entity.id);
        if (!deleted) return;
        // Entities auto-refresh via computed signal
        if (this.selectedEntity()?.id === entity.id) {
            this.selectedEntity.set(null);
        }
        if (this.entitySelection.selectedEntityId() === entity.id) {
            this.entitySelection.clear();
        }
    }

    async onSaveEntity(data: EntityCreatorData) {
        if (data.id) {
            const updated = await smartGraphRegistry.updateEntityDurable(data.id, {
                label: data.label,
                kind: data.kind as any,
                aliases: data.aliases,
            });
            if (updated && this.selectedEntity()?.id === updated.id) {
                this.selectedEntity.set(updated);
            }
            if (updated) {
                this.entitySelection.select(updated.id);
            }
        } else {
            const context = this.manualEntityContext();
            const result = await smartGraphRegistry.registerEntity(
                data.label,
                data.kind as any,
                context.noteId,
                {
                    source: 'user',
                    aliases: data.aliases,
                    attributes: context.narrativeId ? { narrativeId: context.narrativeId } : undefined,
                }
            );
            this.selectedEntity.set(result.entity);
            this.entitySelection.select(result.entity.id);
        }
    }

    async flushRegistry() {
        if (confirm(`Delete all ${this.totalEntities()} entities? This cannot be undone.`)) {
            const cleared = await smartGraphRegistry.clearAll();
            const clearedRejects = await Promise.all([
                clearRejectedSuggestionFeedback('atlas_surface'),
                clearRejectedSuggestionFeedback('dynamic_ner'),
            ]);
            if (cleared === 0 && clearedRejects.every((count) => count === 0)) return;
            this.selectedEntity.set(null);
            this.entitySelection.clear();
        }
    }

    async runSuggestionScan(source: 'sidebar' | 'canvas' = 'sidebar', lens?: GraphLensState) {
        if (this.atlasMode() !== 'embeddings') {
            const currentNote = this.noteStore.currentNote();
            if (!currentNote) return;
            const plainText = parseContentToPlainText(currentNote.content || currentNote.markdownContent || '');
            await this.nerService.runDynamicScan({
                noteId: currentNote.id,
                noteTitle: currentNote.title || 'Untitled Note',
                plainText,
            });
            return;
        }
        try {
            const context = buildGraphAtlasReadContext(lens || {
                mode: this.graphLensMode(),
                primaryNoteId: null,
                selectedNoteIds: [],
            });
            this.machine.setScope(context.noteIds[0] || 'global');
            await this.atlasScan.runRichEmbeddingScan({
                source,
                requireActiveNote: false,
                lensMode: context.lensMode,
                noteIds: context.noteIds,
            });
        } catch (err) {
            console.error('[GraphTab] Semantic Atlas scan failed', err);
        }
    }

    async acceptSuggestion(id: string) {
        await this.nerService.acceptSuggestion(id);
    }

    async rejectSuggestion(id: string) {
        await this.nerService.rejectSuggestion(id);
    }

    getColor(kind: string): string {
        // Use entityColorStore for color parity across the app
        return entityColorStore.getEntityColor(kind);
    }

    private machineScope(): 'global' | string {
        const scope = this.activeScope();
        if (scope.type === 'global' || scope.scopeFolderId === 'vault:global') return 'global';
        return scope.scopeFolderId || scope.id || 'global';
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
