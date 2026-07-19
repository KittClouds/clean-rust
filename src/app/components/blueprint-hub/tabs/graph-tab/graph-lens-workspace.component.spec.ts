// @vitest-environment jsdom
import '@angular/compiler';
import {
    Injector,
    createEnvironmentInjector,
    runInInjectionContext,
    signal,
    ɵChangeDetectionScheduler as ChangeDetectionScheduler,
    ɵEffectScheduler as EffectScheduler,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const dbMock = vi.hoisted(() => ({
    notes: {
        toArray: vi.fn(async () => [{ id: 'note-1', title: 'One', updatedAt: 10 }]),
    },
    entityNoteIndex: {
        where: vi.fn(() => ({
            equals: vi.fn(() => ({
                toArray: vi.fn(async () => []),
            })),
        })),
    },
}));

const settingsMock = vi.hoisted(() => ({
    store: new Map<string, any>(),
}));

vi.mock('../../../../lib/dexie/db', () => ({
    db: dbMock,
}));

vi.mock('../../../../lib/dexie/settings.service', () => ({
    getSetting: vi.fn((key: string, defaultValue: any) => (
        settingsMock.store.has(key) ? settingsMock.store.get(key) : defaultValue
    )),
    setSetting: vi.fn((key: string, value: any) => {
        settingsMock.store.set(key, value);
    }),
}));

import {
    GraphLensWorkspaceComponent,
} from './graph-lens-workspace.component';
import { graphSnapshotRenderIdentity, sameGraphRenderIdentity } from './graph-render-identity';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import { PhoenixProjectionService } from '../../../../services/phoenix-projection.service';
import { NoteEditorStore } from '../../../../lib/store/note-editor.store';
import { EditorService } from '../../../../services/editor.service';
import { BlueprintHubService } from '../../blueprint-hub.service';
import { GraphCanvasColdStartService } from '../../../../services/graph-canvas-cold-start.service';

let latestEffectScheduler: ReturnType<typeof createImmediateEffectScheduler> | null = null;

describe('GraphLensWorkspaceComponent read-only snapshot loading', () => {
    let injector: EnvironmentInjector;
    let graphRebuild: ReturnType<typeof createGraphRebuildMock>;
    let component: GraphLensWorkspaceComponent;
    let effectScheduler: ReturnType<typeof createImmediateEffectScheduler>;
    let snapshotToLoad: any;

    beforeEach(() => {
        settingsMock.store.clear();
        snapshotToLoad = null;
        graphRebuild = createGraphRebuildMock();
        effectScheduler = createImmediateEffectScheduler();
        latestEffectScheduler = effectScheduler;
        injector = createEnvironmentInjector([
            { provide: GraphRebuildService, useValue: graphRebuild },
            { provide: GraphCanvasColdStartService, useValue: createColdStartMock() },
            { provide: PhoenixProjectionService, useValue: createProjectionMock() },
            ...sourceNavigationProviders(),
            { provide: ChangeDetectionScheduler, useValue: { notify: vi.fn(), runningTick: false } },
            { provide: EffectScheduler, useValue: effectScheduler },
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        component = runInInjectionContext(injector, () => new GraphLensWorkspaceComponent());
    });

    afterEach(() => {
        component?.ngOnDestroy();
        injector?.destroy();
        vi.clearAllMocks();
    });

    it('loads cached graph snapshots without invoking graph rebuild on lens or anchor changes', async () => {
        await flushAsync();

        expect(graphRebuild.loadPersistedSnapshot).toHaveBeenCalledWith('global');
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();

        component.setLensMode('note');
        component.toggleNote('note-1');
        await flushAsync();

        expect(graphRebuild.loadPersistedSnapshot).toHaveBeenCalledWith('note:note-1');
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();

        window.dispatchEvent(new CustomEvent('graph-rebuild-anchors-changed'));
        await flushAsync();

        expect(component.graphSnapshotStale()).toBe(true);
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();

        window.dispatchEvent(new CustomEvent('graph-rebuild-snapshot-updated'));
        await flushAsync();

        expect(graphRebuild.loadPersistedSnapshot).toHaveBeenCalledTimes(3);
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('hydrates the lens from Dexie settings and persists later scope changes', async () => {
        settingsMock.store.set('graph.lens.state.v1', {
            mode: 'multiNote',
            primaryNoteId: 'note-1',
            selectedNoteIds: ['note-1'],
        });
        component?.ngOnDestroy();
        injector?.destroy();
        graphRebuild = createGraphRebuildMock();
        effectScheduler = createImmediateEffectScheduler();
        latestEffectScheduler = effectScheduler;
        injector = createEnvironmentInjector([
            { provide: GraphRebuildService, useValue: graphRebuild },
            { provide: GraphCanvasColdStartService, useValue: createColdStartMock() },
            { provide: PhoenixProjectionService, useValue: createProjectionMock() },
            ...sourceNavigationProviders(),
            { provide: ChangeDetectionScheduler, useValue: { notify: vi.fn(), runningTick: false } },
            { provide: EffectScheduler, useValue: effectScheduler },
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        component = runInInjectionContext(injector, () => new GraphLensWorkspaceComponent());

        expect(component.lens().mode).toBe('multiNote');

        component.setLensMode('global');

        expect(settingsMock.store.get('graph.lens.state.v1')).toEqual({
            mode: 'global',
            primaryNoteId: null,
            selectedNoteIds: [],
        });
    });

    it('does not reload or replace render state for a receipt with the same graph identity', async () => {
        await flushAsync();
        const first = renderSnapshot('snapshot-a', 'authority-a');
        snapshotToLoad = first;
        window.dispatchEvent(new CustomEvent('graph-rebuild-snapshot-updated'));
        await flushAsync();

        expect(component.graphRebuildSnapshot()).toBe(first);
        expect(graphRebuild.loadPersistedSnapshot).toHaveBeenCalledTimes(2);

        snapshotToLoad = { ...first, buildTimings: { totalMs: 1 } };
        window.dispatchEvent(new CustomEvent('graph-index-run-completed', {
            detail: { scopeId: 'global', snapshotId: 'snapshot-a', authorityHash: 'authority-a' },
        }));
        await flushAsync();

        expect(graphRebuild.loadPersistedSnapshot).toHaveBeenCalledTimes(2);
        expect(component.graphRebuildSnapshot()).toBe(first);
    });

    it('treats timing-only snapshot clones as the same render identity', () => {
        const first = renderSnapshot('snapshot-a', 'authority-a');
        const timingClone = { ...first, buildTimings: { totalMs: 2 } };
        expect(graphSnapshotRenderIdentity(first)).toBe(graphSnapshotRenderIdentity(timingClone));
        expect(sameGraphRenderIdentity(first, timingClone)).toBe(true);
        expect(sameGraphRenderIdentity(first, renderSnapshot('snapshot-a', 'authority-b'))).toBe(false);
    });

    function createGraphRebuildMock() {
        return {
            loadPersistedSnapshot: vi.fn(async () => snapshotToLoad),
            buildAndPersistSnapshot: vi.fn(async () => null),
        };
    }

    function createColdStartMock() {
        return { preparePersistedManifold: vi.fn(async () => undefined) };
    }
});

function renderSnapshot(id: string, contentHash: string): any {
    return {
        id,
        scopeId: 'global',
        authorityContract: { contentHash },
    };
}

function createProjectionMock() {
    return {
        entities: signal([]),
        getEdgesForEntity: vi.fn(() => []),
    };
}

function sourceNavigationProviders() {
    return [
        { provide: NoteEditorStore, useValue: { openNote: vi.fn(async () => undefined) } },
        { provide: EditorService, useValue: { selectProjectedRange: vi.fn() } },
        { provide: BlueprintHubService, useValue: { close: vi.fn() } },
    ];
}

function createImmediateEffectScheduler() {
    const scheduled = new Set<any>();
    const run = (effect: any) => {
        if (typeof effect?.run === 'function') effect.run();
    };
    return {
        add: vi.fn((effect: any) => {
            scheduled.add(effect);
        }),
        schedule: vi.fn((effect: any) => {
            scheduled.add(effect);
        }),
        flush: vi.fn(() => {
            for (const effect of [...scheduled]) run(effect);
        }),
        remove: vi.fn((effect: any) => {
            scheduled.delete(effect);
        }),
    };
}

async function flushAsync(): Promise<void> {
    latestEffectScheduler?.flush();
    await Promise.resolve();
    latestEffectScheduler?.flush();
    await Promise.resolve();
}
