// @vitest-environment jsdom
import '@angular/compiler';
import {
    Injector,
    SimpleChange,
    createEnvironmentInjector,
    runInInjectionContext,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RegisteredEntity } from '../../../../lib/registry';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import { GraphEntitySidebarComponent } from './graph-entity-sidebar.component';

describe('GraphEntitySidebarComponent discourse focus', () => {
    let injector: EnvironmentInjector;
    let component: GraphEntitySidebarComponent;

    beforeEach(() => {
        injector = createEnvironmentInjector([
            {
                provide: GraphRebuildService,
                useValue: {
                    loadPersistedSnapshot: vi.fn(async () => null),
                },
            },
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        component = runInInjectionContext(injector, () => new GraphEntitySidebarComponent());
        component.entities = entities();
        component.ngOnChanges({
            entities: new SimpleChange([], component.entities, true),
        });
    });

    afterEach(() => {
        component?.ngOnDestroy();
        injector?.destroy();
        vi.clearAllMocks();
    });

    it('keeps discourse button focus out of the shared entity search', () => {
        component.sidebarView.set('discourse');

        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));
        const visibleEntityRows = component.rows().filter((row) => row.type === 'entity').length;

        component.highlightDiscourseQuery('discourse overlay');

        expect(component.sidebarView()).toBe('discourse');
        expect(component.entitySearch()).toBe('');
        expect(component.focusedDiscourseQuery()).toBe('discourse overlay');
        expect(component.rows().filter((row) => row.type === 'entity').length).toBe(visibleEntityRows);
        expect(emittedSearches).toEqual([]);
    });

    it('still emits explicit entity searches for atlas filtering', () => {
        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));

        component.updateEntitySearch('Kai');

        expect(component.entitySearch()).toBe('Kai');
        expect(emittedSearches).toEqual(['Kai']);
    });

    it('selects discourse workbench rows without mutating atlas search', () => {
        component.sidebarView.set('discourse');
        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));

        component.selectDiscourseRecord('gaps:row-1');

        expect(component.selectedDiscourseRecordId()).toBe('gaps:row-1');
        expect(component.entitySearch()).toBe('');
        expect(emittedSearches).toEqual([]);
    });

    it('uses the explicit discourse focus action to update atlas search', () => {
        component.sidebarView.set('discourse');
        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));

        component.focusDiscourseRecord({
            id: 'gaps:row-1',
            focusQuery: 'Kai Hazel bridge',
        } as any);

        expect(component.focusedDiscourseQuery()).toBe('Kai Hazel bridge');
        expect(emittedSearches).toEqual(['Kai Hazel bridge']);
    });
});

function entities(): RegisteredEntity[] {
    return [
        { id: 'kai', label: 'Kai', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'mesa', label: 'Red Mesa', kind: 'LOCATION', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
    ] as RegisteredEntity[];
}
