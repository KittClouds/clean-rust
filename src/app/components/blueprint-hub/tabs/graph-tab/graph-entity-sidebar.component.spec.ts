// @vitest-environment jsdom
import '@angular/compiler';
import { SimpleChange } from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RegisteredEntity } from '../../../../lib/registry';
import { entityColorStore } from '../../../../lib/store/entityColorStore';
import { GraphEntitySidebarComponent } from './graph-entity-sidebar.component';

describe('GraphEntitySidebarComponent', () => {
    let component: GraphEntitySidebarComponent;

    beforeEach(() => {
        component = new GraphEntitySidebarComponent();
        setEntities(component, entities());
    });

    afterEach(() => {
        component.ngOnDestroy();
        vi.restoreAllMocks();
    });

    it('renders only grouped entity rows from the registry input', () => {
        const groups = component.rows().filter((row) => row.type === 'group');
        const entityRows = component.rows().filter((row) => row.type === 'entity');

        expect(groups.map((row) => row.type === 'group' ? row.kind : '')).toEqual(['CHARACTER', 'LOCATION']);
        expect(entityRows).toHaveLength(3);
        expect(component.visibleEntityCount()).toBe(3);
    });

    it('filters by entity label, alias, and kind and emits the shared graph search', () => {
        const searches: string[] = [];
        component.searchTextChange.subscribe((value) => searches.push(value));

        component.updateEntitySearch('Red');
        expect(visibleLabels(component)).toEqual(['Kai']);

        component.updateEntitySearch('location');
        expect(visibleLabels(component)).toEqual(['Halcyon']);
        expect(searches).toEqual(['Red', 'location']);
    });

    it('accepts external graph search state without echoing it as a user action', () => {
        const searches: string[] = [];
        component.searchTextChange.subscribe((value) => searches.push(value));
        component.searchText = 'Hazel';

        component.ngOnChanges({
            searchText: new SimpleChange('', 'Hazel', false),
        });

        expect(component.entitySearch()).toBe('Hazel');
        expect(visibleLabels(component)).toEqual(['Hazel']);
        expect(searches).toEqual([]);
    });

    it('emits selection, add, and Style Lab commands', () => {
        const selected: string[] = [];
        let adds = 0;
        let styles = 0;
        component.entitySelected.subscribe((entity) => selected.push(entity.id));
        component.addEntityRequested.subscribe(() => adds += 1);
        component.styleRequested.subscribe(() => styles += 1);

        component.entitySelected.emit(component.entities[0]);
        component.addEntityRequested.emit();
        component.styleRequested.emit();

        expect(selected).toEqual(['kai']);
        expect(adds).toBe(1);
        expect(styles).toBe(1);
    });

    it('emits edit and delete without selecting the row', () => {
        const edited: string[] = [];
        const deleted: string[] = [];
        const stopPropagation = vi.fn();
        component.editEntityRequested.subscribe((entity) => edited.push(entity.id));
        component.deleteEntityRequested.subscribe((entity) => deleted.push(entity.id));

        component.editClicked(component.entities[0], { stopPropagation } as unknown as Event);
        component.deleteClicked(component.entities[1], { stopPropagation } as unknown as Event);

        expect(stopPropagation).toHaveBeenCalledTimes(2);
        expect(edited).toEqual(['kai']);
        expect(deleted).toEqual(['hazel']);
    });

    it('marks the current graph selection by stable entity id', () => {
        component.selectedEntity = component.entities[1];

        expect(component.isSelected(component.entities[0])).toBe(false);
        expect(component.isSelected(component.entities[1])).toBe(true);
    });

    it('updates a family color directly from entity management', () => {
        const original = entityColorStore.getRawHsl('CHARACTER');
        const stopPropagation = vi.fn();

        component.updateKindColor('CHARACTER', '#12b8a6', { stopPropagation } as unknown as Event);

        expect(stopPropagation).toHaveBeenCalledOnce();
        expect(component.getHexColor('CHARACTER')).toBe('#12b8a6');
        entityColorStore.setColor('CHARACTER', original);
    });
});

function setEntities(component: GraphEntitySidebarComponent, value: RegisteredEntity[]): void {
    component.entities = value;
    component.ngOnChanges({
        entities: new SimpleChange([], value, true),
    });
}

function visibleLabels(component: GraphEntitySidebarComponent): string[] {
    return component.rows()
        .filter((row): row is Extract<ReturnType<typeof component.rows>[number], { type: 'entity' }> => row.type === 'entity')
        .map((row) => row.entity.label);
}

function entities(): RegisteredEntity[] {
    return [
        entity('kai', 'Kai', 'CHARACTER', ['Red claimant']),
        entity('hazel', 'Hazel', 'CHARACTER'),
        entity('halcyon', 'Halcyon', 'LOCATION'),
    ];
}

function entity(id: string, label: string, kind: string, aliases: string[] = []): RegisteredEntity {
    return {
        id,
        label,
        kind,
        aliases,
        attributes: {},
        createdAt: 1,
        updatedAt: 1,
    } as RegisteredEntity;
}
