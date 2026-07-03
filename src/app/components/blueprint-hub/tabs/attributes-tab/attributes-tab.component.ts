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
    styleUrl: './attributes-tab.component.css',
})
export class AttributesTabComponent {
    private readonly scopeService = inject(ScopeService);
    private readonly nerService = inject(NerService);
    private readonly noteStore = inject(NoteEditorStore);
    private readonly projection = inject(PhoenixProjectionService);
    private readonly machine = inject(PhoenixMachineControlService);
    private readonly entitySelection = inject(EntitySelectionService);
    private readonly atlasScan = inject(AtlasScanCoordinatorService);

    readonly entities = computed(() => this.projection.entities());
    readonly suggestions = this.nerService.suggestions;
    readonly graphLensMode = this.machine.graphLensMode;
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

    readonly graphSummary = computed(() => ({
        entities: this.entities().length,
        edges: this.atlasEdges().length,
        suggestions: this.suggestions().length,
        room: this.operatingRoom(),
    }));

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

    private manualEntityContext(): { noteId: string; narrativeId?: string } {
        const currentNote = this.noteStore.currentNote();
        const scope = this.activeScope();
        return {
            noteId: currentNote?.id || scope.selectedNoteId || (scope.type === 'note' ? scope.id : 'manual'),
            narrativeId: currentNote?.narrativeId || scope.narrativeId || (scope.type === 'narrative' ? scope.id : undefined),
        };
    }
}
