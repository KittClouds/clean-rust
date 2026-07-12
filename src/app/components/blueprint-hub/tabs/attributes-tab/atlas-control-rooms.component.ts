import { CommonModule } from '@angular/common';
import { Component, computed, input, output, signal } from '@angular/core';
import { LucideAngularModule, Plus, Search, X } from 'lucide-angular';

import type {
    AtlasControlAction,
    AtlasControlContract,
    AtlasControlInventoryCategoryId,
    AtlasControlRow,
} from '../../../../graph-rebuild/atlas-control-contract';
import type {
    AtlasControlRoomActionDescriptor,
    AtlasControlRoomActionRequest,
    AtlasControlRoomId,
} from '../../../../graph-rebuild/atlas-control-room-contract';
import type { AtlasProofPagingState } from '../../../../services/atlas-control-contract.service';

const ROW_LIMIT = 160;

@Component({
    selector: 'app-atlas-control-rooms',
    standalone: true,
    imports: [CommonModule, LucideAngularModule],
    templateUrl: './atlas-control-rooms.component.html',
    styleUrl: './atlas-control-rooms.component.css',
})
export class AtlasControlRoomsComponent {
    readonly contract = input.required<AtlasControlContract>();
    readonly paging = input<AtlasProofPagingState>({
        runHandle: null,
        status: 'idle',
        loadedRows: 0,
        totalRows: 0,
        nextOffset: null,
        error: null,
    });
    readonly selectedRoomId = input<AtlasControlRoomId>('entities');
    readonly roomChange = output<AtlasControlRoomId>();
    readonly actionRequested = output<AtlasControlRoomActionRequest>();
    readonly nextPageRequested = output<void>();

    readonly selectedInventoryId = signal<AtlasControlInventoryCategoryId | null>(null);
    readonly selectedRowId = signal<string | null>(null);
    readonly query = signal('');

    readonly roomIds = computed(() => this.contract().roomIds);
    readonly activeRoom = computed(() => this.contract().roomsById[this.selectedRoomId()]);
    readonly inventories = computed(() => this.activeRoom().inventoryCategoryIds
        .map((id) => this.contract().inventoryById[id]));
    readonly proofRows = computed(() => this.activeRoom().proofIds
        .map((id) => ({ id, proof: this.contract().invariants[id as keyof AtlasControlContract['invariants']] }))
        .filter((item) => !!item.proof));
    readonly roomActions = computed(() => this.activeRoom().actionIds
        .map((id) => this.contract().roomActionsById[id])
        .filter((action): action is AtlasControlRoomActionDescriptor => !!action)
        .filter((action) => !['inspect', 'jump_to_source', 'compare_context', 'show_reason'].includes(action.action)));
    readonly filteredRowIds = computed(() => {
        const room = this.activeRoom();
        const inventoryId = this.selectedInventoryId();
        const sourceIds = inventoryId && room.inventoryCategoryIds.includes(inventoryId)
            ? this.contract().inventoryById[inventoryId].rowIds
            : room.rowIds;
        const query = this.query().trim().toLowerCase();
        if (!query) return sourceIds;
        return sourceIds.filter((id) => {
            const row = this.contract().rowsById[id];
            return row && `${row.label} ${row.detail} ${row.identity.kind} ${row.state}`.toLowerCase().includes(query);
        });
    });
    readonly visibleRows = computed(() => this.filteredRowIds().slice(0, ROW_LIMIT)
        .map((id) => this.contract().rowsById[id])
        .filter((row): row is AtlasControlRow => !!row));
    readonly selectedRow = computed(() => {
        const rows = this.visibleRows();
        return rows.find((row) => row.identity.id === this.selectedRowId()) ?? rows[0] ?? null;
    });
    readonly rowActions = computed(() => {
        const row = this.selectedRow();
        if (!row) return [];
        return row.allowedActions.map((action) => this.actionDescriptor(action))
            .filter((item): item is AtlasControlRoomActionDescriptor => !!item);
    });

    readonly PlusIcon = Plus;
    readonly SearchIcon = Search;
    readonly XIcon = X;

    selectRoom(roomId: AtlasControlRoomId): void {
        if (roomId === this.selectedRoomId()) return;
        this.selectedInventoryId.set(null);
        this.selectedRowId.set(null);
        this.query.set('');
        this.roomChange.emit(roomId);
        this.requestNextPageIfAvailable();
    }

    selectInventory(id: AtlasControlInventoryCategoryId): void {
        this.selectedInventoryId.update((current) => current === id ? null : id);
        this.selectedRowId.set(null);
        this.requestNextPageIfAvailable();
    }

    selectRow(rowId: string): void {
        this.selectedRowId.set(rowId);
    }

    isSelectedRow(rowId: string): boolean {
        return this.selectedRow()?.identity.id === rowId;
    }

    updateQuery(value: string): void {
        this.query.set(value);
        this.selectedRowId.set(null);
    }

    clearQuery(): void {
        this.query.set('');
    }

    requestNextPage(): void {
        if (this.paging().status === 'loading' || this.paging().nextOffset == null) return;
        this.nextPageRequested.emit();
    }

    dispatch(action: AtlasControlRoomActionDescriptor, rowId: string | null = null): void {
        if (!action.enabled) return;
        if (action.action === 'inspect' && rowId) this.selectedRowId.set(rowId);
        this.actionRequested.emit({ roomId: this.activeRoom().id, action: action.action, rowId });
    }

    percent(value: number | null): string {
        if (value == null) return '--';
        return `${Math.round(value * 100)}%`;
    }

    private actionDescriptor(action: AtlasControlAction): AtlasControlRoomActionDescriptor | null {
        return this.contract().roomActionsById[`${this.activeRoom().id}:${action}`] ?? null;
    }

    private requestNextPageIfAvailable(): void {
        if (this.paging().status === 'ready' && this.paging().nextOffset != null) {
            this.nextPageRequested.emit();
        }
    }
}
