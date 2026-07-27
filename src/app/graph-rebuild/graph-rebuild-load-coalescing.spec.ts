import '@angular/compiler';
import { Injector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { assertGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import { sealGraphSnapshotAuthority } from './graph-snapshot-authority';
import {
    GraphRebuildService,
    attachInteractiveAtlasPacketForSnapshotTargets,
    graphRebuildSnapshotContentBlobDocuments,
    graphRebuildSnapshotToScopedDocument,
    scopedDocumentToGraphRebuildSnapshot,
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

    it('leases exact generation content without reinstalling rich rows in the hot snapshot state', async () => {
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
        sealGraphSnapshotAuthority(snapshot);
        const primary = graphRebuildSnapshotToScopedDocument(snapshot);
        const shell = scopedDocumentToGraphRebuildSnapshot(primary)!;
        shell.generationReceiptId = 'generation-receipt-1';
        shell.generationDigestSha256 = 'sha256-generation-1';
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

        const loaded = await service.loadVerifiedGenerationSnapshotContent(shell);

        expect(loaded.embeddingTargets).toEqual(snapshot.embeddingTargets);
        expect(assertGraphEvidenceTargetRegistry(loaded).contract).toEqual(snapshot.evidenceTargetRegistry);
        expect(service.snapshot()).toBeNull();
        expect(store.getScopedDocument).toHaveBeenCalledTimes(1);
        expect(store.getScopedDocumentsByKeys).toHaveBeenCalledTimes(1);
        injector.destroy();
    });

    it('fails closed when a compact generation points at different durable snapshot content', async () => {
        const expected = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai')],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 3, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [occurrence('note-1', 'entity-kai', 0, 3)],
            noteTexts: { 'note-1': 'Kai' },
            builtAt: 42,
        });
        attachInteractiveAtlasPacketForSnapshotTargets(expected);
        sealGraphSnapshotAuthority(expected);
        const expectedPrimary = graphRebuildSnapshotToScopedDocument(expected);
        const shell = scopedDocumentToGraphRebuildSnapshot(expectedPrimary)!;
        shell.generationReceiptId = 'generation-receipt-1';
        shell.generationDigestSha256 = 'sha256-generation-1';
        const drifted = { ...shell, id: 'snapshot-drifted' };
        const store = {
            getScopedDocument: vi.fn(async () => graphRebuildSnapshotToScopedDocument(drifted)),
            getScopedDocumentsByKeys: vi.fn(async () => []),
        };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: { target: 'web' } },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        await expect(service.loadVerifiedGenerationSnapshotContent(shell))
            .rejects.toThrow('PHX_GRAPH_CONTENT_LEASE_IDENTITY_DRIFT');
        expect(store.getScopedDocumentsByKeys).not.toHaveBeenCalled();
        injector.destroy();
    });

    it('requires explicit migration when an older generation has no durable registry page', async () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global', scopeId: 'global', noteIds: [], entities: [], chunks: [],
            occurrences: [], noteTexts: {}, builtAt: 42,
        });
        attachInteractiveAtlasPacketForSnapshotTargets(snapshot);
        sealGraphSnapshotAuthority(snapshot);
        const shell = scopedDocumentToGraphRebuildSnapshot(graphRebuildSnapshotToScopedDocument(snapshot))!;
        shell.generationReceiptId = 'generation-receipt-1';
        shell.generationDigestSha256 = 'sha256-generation-1';
        delete shell.contentManifest?.refs.evidenceTargetRegistryPage;
        const store = { getScopedDocument: vi.fn(), getScopedDocumentsByKeys: vi.fn() };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: { target: 'web' } },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        await expect(service.loadVerifiedGenerationSnapshotContent(shell))
            .rejects.toThrow('PHX_GRAPH_CONTENT_LEASE_CAPABILITY_MISSING');
        expect(store.getScopedDocument).not.toHaveBeenCalled();
        injector.destroy();
    });

    it('rejects every direct Delta attempt at the snapshot reconstruction boundary', async () => {
        const store = { getScopedDocument: vi.fn() };
        const backend = { target: 'web', executeStoreCommand: vi.fn() };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: backend },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        await expect(service.buildAndPersistSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai')],
            buildPolicy: 'delta',
        })).rejects.toThrow('Delta is authority-reuse only');

        expect(store.getScopedDocument).not.toHaveBeenCalled();
        expect(backend.executeStoreCommand).not.toHaveBeenCalled();
        injector.destroy();
    });

    it('preserves rejected persisted authority and blocks automatic cold fallback', async () => {
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
        const persisted = scopedDocumentToGraphRebuildSnapshot(primary)!;
        persisted.counters = { ...persisted.counters, edges: persisted.counters.edges + 1 };
        const rejectedPrimary = graphRebuildSnapshotToScopedDocument(persisted);
        const blobs = graphRebuildSnapshotContentBlobDocuments(snapshot);
        const store = {
            getScopedDocument: vi.fn(async () => rejectedPrimary),
            getScopedDocumentsByKeys: vi.fn(async () => blobs),
        };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: { target: 'web' } },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        await expect(service.loadPersistedSnapshot('global')).resolves.toBeNull();
        await expect(service.buildAndPersistSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai')],
            buildPolicy: 'delta',
        })).rejects.toThrow('Automatic cold fallback is disabled');

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
