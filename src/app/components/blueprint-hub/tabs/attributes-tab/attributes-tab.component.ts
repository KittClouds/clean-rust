import { CommonModule } from '@angular/common';
import { Component, OnDestroy, ViewChild, computed, inject, signal } from '@angular/core';

import { smartGraphRegistry, type RegisteredEntity } from '../../../../lib/registry';
import { EntitySelectionService } from '../../../../lib/services/entity-selection.service';
import { ScopeService } from '../../../../lib/services/scope.service';
import { NoteEditorStore } from '../../../../lib/store/note-editor.store';
import { PhoenixMachineControlService } from '../../../../services/phoenix-machine-control.service';
import { PhoenixProjectionService } from '../../../../services/phoenix-projection.service';
import { AtlasControlContractService } from '../../../../services/atlas-control-contract.service';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import type { GraphDocumentReviewDecision } from '../../../../graph-rebuild/graph-document-review-snapshot';
import { SearchPanelComponent } from '../../../search-panel/search-panel.component';
import {
    EntityCreatorData,
    EntityCreatorDialogComponent,
} from '../graph-tab/entity-creator-dialog/entity-creator-dialog.component';
import type { AtlasControlTone } from '../../../../graph-rebuild/atlas-control-contract';
import type {
    AtlasControlRoomActionRequest,
    AtlasControlRoomId,
} from '../../../../graph-rebuild/atlas-control-room-contract';
import {
    appendStoryContinuityActionReceipt,
    type GraphContinuityAction,
} from '../../../../graph-rebuild/graph-story-continuity';
import { AtlasControlRoomsComponent } from './atlas-control-rooms.component';

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
        AtlasControlRoomsComponent,
        EntityCreatorDialogComponent,
    ],
    templateUrl: './attributes-tab.component.html',
    styleUrls: [
        './attributes-tab.component.css',
        './attributes-tab-workflow.component.css',
    ],
})
export class AttributesTabComponent implements OnDestroy {
    @ViewChild(SearchPanelComponent) private searchPanel?: SearchPanelComponent;

    private readonly scopeService = inject(ScopeService);
    private readonly noteStore = inject(NoteEditorStore);
    private readonly projection = inject(PhoenixProjectionService);
    private readonly atlasControl = inject(AtlasControlContractService);
    private readonly graphRebuild = inject(GraphRebuildService);
    private readonly machine = inject(PhoenixMachineControlService);
    private readonly entitySelection = inject(EntitySelectionService);

    readonly entities = computed(() => this.projection.entities());
    readonly graphSnapshot = this.graphRebuild.snapshot;
    readonly selectedEntity = signal<RegisteredEntity | null>(null);
    readonly isCreatorOpen = signal(false);
    readonly editingEntity = signal<EntityCreatorData | undefined>(undefined);
    readonly selectedRoomId = signal<AtlasControlRoomId>('review');
    readonly activeScope = this.scopeService.activeScope;

    readonly atlasControlContract = this.atlasControl.contract;
    readonly atlasProofPaging = this.atlasControl.proofPaging;
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
    setOperatingRoom(room: AtlasControlRoomId): void {
        this.selectedRoomId.set(room);
    }

    loadNextAtlasProofPage(): void {
        void this.atlasControl.loadNextProofPage();
    }

    ngOnDestroy(): void {
        void this.atlasControl.releaseProofLease();
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

    async dispatchRoomAction(request: AtlasControlRoomActionRequest): Promise<void> {
        const row = request.rowId
            ? this.atlasControlContract().rowsById[request.rowId] ?? null
            : null;
        if (request.action === 'add_entity') {
            this.openCreator();
            return;
        }
        if (request.action === 'edit_entity' || request.action === 'delete_entity') {
            const entityId = row?.entityIds[0] ?? row?.identity.rawId;
            const entity = this.entities().find((candidate) => candidate.id === entityId);
            if (!entity) return;
            if (request.action === 'edit_entity') this.editEntity(entity);
            else await this.deleteEntity(entity);
            return;
        }
        if (request.action === 'refresh_review') {
            await this.searchPanel?.runTruthReviewLane();
            return;
        }
        if (request.action === 'run_nli') {
            await this.searchPanel?.runModernBertNliReview();
            return;
        }
        if (!row) return;
        if (isContinuityAction(request.action)) {
            const current = this.graphSnapshot();
            if (!current) return;
            const next = structuredClone(current);
            const receipt = appendStoryContinuityActionReceipt(next, row.identity.rawId, request.action);
            if (receipt) await this.graphRebuild.restorePersistedSnapshot(next);
            return;
        }
        if (request.action === 'jump_to_source' && row.noteId) {
            await this.noteStore.openNote(row.noteId);
            this.requestRowFocus(row);
            return;
        }
        const decision = reviewDecisionForAction(request.action);
        if (decision) {
            const targetId = row.sourceIds[0] ?? row.identity.rawId;
            await this.graphRebuild.applyOperatorReviewDecision(targetId, decision);
            return;
        }
        this.requestRowFocus(row);
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

    private requestRowFocus(row: { label: string; detail: string }): void {
        this.machine.requestGraphFocus({
            query: row.label,
            scope: this.machineScope(),
            title: row.detail || row.label,
        });
    }
}

function isContinuityAction(action: AtlasControlRoomActionRequest['action']): action is GraphContinuityAction {
    return CONTINUITY_ACTIONS.has(action as GraphContinuityAction);
}

const CONTINUITY_ACTIONS = new Set<GraphContinuityAction>([
    'split_episode',
    'merge_episodes',
    'confirm_boundary',
    'confirm_ordering',
    'reject_ordering',
    'confirm_causal_link',
    'reject_causal_link',
    'resolve_continuity_conflict',
]);

function reviewDecisionForAction(action: AtlasControlRoomActionRequest['action']): GraphDocumentReviewDecision | null {
    const decisions: Partial<Record<AtlasControlRoomActionRequest['action'], GraphDocumentReviewDecision>> = {
        accept_review_row: 'accepted',
        reject_review_row: 'rejected',
        promote_to_anchor: 'promoted_to_anchor',
        merge_duplicates: 'accepted',
        demote_to_sidecar: 'ledger_only',
        mute_pattern: 'muted',
        compile_to_graph: 'compiled_to_graph',
    };
    return decisions[action] ?? null;
}

function atlasToneFromContract(tone: AtlasControlTone): AtlasWorkflowTone {
    if (tone === 'danger' || tone === 'warning') return 'warning';
    return tone;
}
