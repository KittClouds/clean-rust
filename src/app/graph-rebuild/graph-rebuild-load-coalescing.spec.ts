import '@angular/compiler';
import { Injector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import {
    GraphRebuildService,
    attachInteractiveAtlasPacketForSnapshotTargets,
    graphRebuildSnapshotContentBlobDocuments,
    graphRebuildSnapshotToScopedDocument,
} from './graph-rebuild.service';

describe('GraphRebuildService persisted snapshot loading', () => {
    it('coalesces concurrent same-scope hydration into one durable read', async () => {
        let finishRead!: (value: null) => void;
        const read = new Promise<null>((resolve) => { finishRead = resolve; });
        const store = { getScopedDocument: vi.fn(() => read) };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: { target: 'web' } },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        const first = service.loadPersistedSnapshot('global');
        const second = service.loadPersistedSnapshot('global');

        expect(store.getScopedDocument).toHaveBeenCalledTimes(1);
        finishRead(null);
        await expect(Promise.all([first, second])).resolves.toEqual([null, null]);
        injector.destroy();
    });

    it('hydrates content-addressed snapshot blobs through one bounded native read', async () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai')],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 3, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [occurrence('note-1', 'entity-kai', 0, 3)],
            noteTexts: { 'note-1': 'Kai' },
            builtAt: 42,
        });
        attachInteractiveAtlasPacketForSnapshotTargets(snapshot);
        const primary = graphRebuildSnapshotToScopedDocument(snapshot);
        const blobs = graphRebuildSnapshotContentBlobDocuments(snapshot);
        const store = {
            getScopedDocument: vi.fn(async () => primary),
            getScopedDocumentsByKeys: vi.fn(async () => blobs),
        };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: { target: 'web' } },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        const loaded = await service.loadPersistedSnapshot('global');

        expect(loaded?.embeddingTargets).toEqual(snapshot.embeddingTargets);
        expect(store.getScopedDocumentsByKeys).toHaveBeenCalledTimes(1);
        expect(store.getScopedDocumentsByKeys).toHaveBeenCalledWith(
            'global',
            'phoenix_graph_rebuild_v1',
            blobs.map((blob) => blob.documentKey),
        );
        expect(store.getScopedDocument).toHaveBeenCalledTimes(1);
        injector.destroy();
    });
});

function entity(id: string, label: string): RegisteredEntity {
    return { id, label, aliases: [], kind: 'CHARACTER', createdAt: 1, updatedAt: 1 } as RegisteredEntity;
}

function occurrence(noteId: string, entityId: string, sourceStart: number, sourceEnd: number): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}:${sourceStart}`,
        noteId,
        entityId,
        sourceStart,
        sourceEnd,
        surface: 'Kai',
        confidence: 1,
        createdAt: 1,
        updatedAt: 1,
    } as EntityOccurrence;
}
