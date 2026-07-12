import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const template = readFileSync(join(here, 'atlas-control-rooms.component.html'), 'utf8');
const source = readFileSync(join(here, 'atlas-control-rooms.component.ts'), 'utf8');

describe('AtlasControlRoomsComponent contract boundary', () => {
    it('renders rooms, inventories, rows, actions, and proofs from one required contract', () => {
        expect(source).toContain('input.required<AtlasControlContract>()');
        expect(source).toContain('this.contract().roomIds');
        expect(source).toContain('this.contract().roomsById');
        expect(source).toContain('this.contract().inventoryById');
        expect(source).toContain('this.contract().rowsById');
        expect(source).toContain('this.contract().roomActionsById');
        expect(template).toContain('@for (roomId of roomIds(); track roomId)');
        expect(template).not.toContain('app-graph-entity-sidebar');
    });

    it('emits only typed room action requests and renders bounded row projections', () => {
        expect(source).toContain('output<AtlasControlRoomActionRequest>()');
        expect(source).toContain('this.actionRequested.emit({ roomId: this.activeRoom().id, action: action.action, rowId })');
        expect(source).toContain('const ROW_LIMIT = 160');
        expect(source).toContain('.slice(0, ROW_LIMIT)');
        expect(template).toContain('(click)="dispatch(action, row.identity.id)"');
    });

    it('requests native proof pages without manufacturing an empty ledger', () => {
        expect(source).toContain('output<void>()');
        expect(source).toContain('this.nextPageRequested.emit()');
        expect(template).toContain('Proof rows are still native');
        expect(template).toContain('Load next proof page');
        expect(template).toContain('Retry native proof page');
    });
});
