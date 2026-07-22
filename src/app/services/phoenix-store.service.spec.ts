// @vitest-environment jsdom
import '@angular/compiler';
import { TestBed, getTestBed } from '@angular/core/testing';
import {
    BrowserDynamicTestingModule,
    platformBrowserDynamicTesting,
} from '@angular/platform-browser-dynamic/testing';
import { describe, expect, it, vi } from 'vitest';

import {
    derivedGraphRepairPrunedDocuments,
    formatPhoenixPersistenceSummary,
    hasActivePhoenixPersistence,
    rowToScopedDocument,
    scopedDocumentToRow,
    PhoenixStoreService,
} from './phoenix-store.service';
import { PhoenixBackendService } from './phoenix-backend.service';
import { SqlitePersistenceService } from '../lib/sqlite/persistence/SqlitePersistenceService';
import type { LoadedPhoenixManifestState } from '../lib/sqlite/persistence/phoenix-wal';
import { createEmptyPhoenixManifest } from '../lib/sqlite/persistence/phoenix-wal';
import {
    PHOENIX_STORE_API_VERSION,
    REQUIRED_PHOENIX_RUNTIME_CAPABILITIES,
} from '../lib/phoenix/phoenix-runtime-compat';

try {
    getTestBed().initTestEnvironment(
        BrowserDynamicTestingModule,
        platformBrowserDynamicTesting(),
    );
} catch {
    // Test environment already initialized for this Vitest worker.
}

function createLoadedState(overrides: Partial<LoadedPhoenixManifestState> = {}): LoadedPhoenixManifestState {
    return {
        manifest: null,
        manifestBytes: 0,
        backupManifestBytes: 0,
        contentCheckpoint: null,
        derivedCheckpoint: null,
        closedSegments: [],
        activeSegment: null,
        staleLegacyFiles: [],
        recoveredFromBackup: false,
        ...overrides,
    };
}

describe('PhoenixStoreService persistence diagnostics helpers', () => {
    it('treats legacy sqlite.db artifacts as non-active restore state', () => {
        const state = createLoadedState({
            staleLegacyFiles: ['sqlite.db', 'sqlite.db.bak'],
        });

        expect(hasActivePhoenixPersistence(state)).toBe(false);
        expect(formatPhoenixPersistenceSummary(state)).toContain('manifest=no');
        expect(formatPhoenixPersistenceSummary(state)).toContain('legacyArtifacts=2');
    });

    it('treats a manifest-free boot as empty Phoenix persistence', () => {
        const state = createLoadedState();

        expect(hasActivePhoenixPersistence(state)).toBe(false);
        expect(formatPhoenixPersistenceSummary(state)).toContain('contentCheckpointBytes=0');
        expect(formatPhoenixPersistenceSummary(state)).toContain('activeWalBytes=0');
    });

    it('treats manifest/checkpoint/WAL data as active Phoenix persistence', () => {
        const state = createLoadedState({
            manifest: createEmptyPhoenixManifest(1),
            manifestBytes: 128,
            contentCheckpoint: { file: 'checkpoints/content-2.bin', bytes: 512 },
            derivedCheckpoint: { file: 'checkpoints/derived-2.bin', bytes: 64 },
            activeSegment: { file: 'wal/content-active.log', bytes: 32 },
        });

        expect(hasActivePhoenixPersistence(state)).toBe(true);
        expect(formatPhoenixPersistenceSummary(state)).toContain('manifest=yes');
        expect(formatPhoenixPersistenceSummary(state)).toContain('contentCheckpointBytes=512');
        expect(formatPhoenixPersistenceSummary(state)).toContain('activeWalBytes=32');
    });

    it('normalizes native graph repair pruning counts', () => {
        expect(derivedGraphRepairPrunedDocuments({ prunedDocuments: 3 })).toBe(3);
        expect(derivedGraphRepairPrunedDocuments({ prunedDocuments: 0 })).toBe(0);
        expect(derivedGraphRepairPrunedDocuments(null)).toBe(0);
    });

    it('keeps scoped document payloads opaque for fast WAL writes', () => {
        const payload = JSON.stringify({ nested: { rows: Array.from({ length: 4 }, (_, id) => ({ id })) } });
        const row = scopedDocumentToRow({
            id: 'doc-1',
            scopeFolderId: 'global',
            narrativeId: '',
            namespace: 'test',
            documentKey: 'snapshot',
            payload,
            createdAt: 1,
            updatedAt: 2,
        });

        expect(row['payload']).toBe(payload);
        expect(rowToScopedDocument(row).payload).toBe(payload);
    });

    it('loads a bounded scoped-document key set through one native command', async () => {
        const row = scopedDocumentToRow({
            id: 'doc-1',
            scopeFolderId: 'global',
            narrativeId: '',
            namespace: 'phoenix_graph_rebuild_v1',
            documentKey: 'snapshot-blob:atlasPacket:hash',
            payload: '{}',
            createdAt: 1,
            updatedAt: 2,
        });
        const backend = { storeCommand: vi.fn(async () => [row]) };
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [
            PhoenixStoreService,
            { provide: PhoenixBackendService, useValue: backend },
            { provide: SqlitePersistenceService, useValue: {} },
        ] });
        const service = TestBed.inject(PhoenixStoreService);
        Object.assign(service as any, { initialized: true });

        const documents = await service.getScopedDocumentsByKeys(
            'global',
            'phoenix_graph_rebuild_v1',
            ['snapshot-blob:atlasPacket:hash', 'snapshot-blob:atlasPacket:hash'],
        );

        expect(backend.storeCommand).toHaveBeenCalledOnce();
        expect(backend.storeCommand).toHaveBeenCalledWith('scopedDocuments:getMany', {
            scopeFolderId: 'global',
            namespace: 'phoenix_graph_rebuild_v1',
            documentKeys: ['snapshot-blob:atlasPacket:hash'],
        });
        expect(documents).toEqual([rowToScopedDocument(row)]);
    });
});

describe('PhoenixStoreService boot ordering', () => {
    it('starts persistence metadata loading before native runtime readiness resolves', async () => {
        const events: string[] = [];
        let resolveRuntime!: () => void;
        const runtimeReady = new Promise<void>((resolve) => { resolveRuntime = resolve; });
        const backend = {
            target: 'native',
            loadRuntime: () => {
                events.push('runtime:start');
                return runtimeReady;
            },
            storeCommand: async (command: string) => {
                expect(command).toBe('runtime:capabilities');
                return {
                    storeApiVersion: PHOENIX_STORE_API_VERSION,
                    capabilities: [...REQUIRED_PHOENIX_RUNTIME_CAPABILITIES],
                };
            },
        };
        const persistence = {
            loadManifestMeta: async () => {
                events.push('persistence:start');
                return createLoadedState();
            },
        };
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [
            PhoenixStoreService,
            { provide: PhoenixBackendService, useValue: backend },
            { provide: SqlitePersistenceService, useValue: persistence },
        ] });
        const service = TestBed.inject(PhoenixStoreService);

        const initialization = service.initialize();
        await Promise.resolve();
        expect(events).toEqual(['persistence:start', 'runtime:start']);

        resolveRuntime();
        await initialization;
        expect(service.isReady).toBe(true);
    });
});

describe('PhoenixStoreService Canvas transaction CAS', () => {
    it('commits once, rejects a stale different patch, and accepts an idempotent replay', async () => {
        let row: Record<string, unknown> = noteRow(101, 'before');
        const backend = {
            isReady: true,
            storeCommand: async (command: string, payload?: any) => {
                if (command === 'note:get') return row;
                if (command === 'persistence:applyWalBatch') {
                    row = payload.records[0].payload.row;
                    return null;
                }
                throw new Error(`Unexpected command: ${command}`);
            },
        };
        const persistence = {
            appendWalBatch: async () => ({
                activeSegmentBytes: 128,
                activeSegmentRecordCount: 1,
                bytesWritten: 128,
            }),
            commitManifest: async () => undefined,
        };
        TestBed.configureTestingModule({
            providers: [
                PhoenixStoreService,
                { provide: PhoenixBackendService, useValue: backend },
                { provide: SqlitePersistenceService, useValue: persistence },
            ],
        });
        const service = TestBed.inject(PhoenixStoreService);
        Object.assign(service as any, {
            initialized: true,
            manifest: createEmptyPhoenixManifest(1),
        });
        service.pauseSnapshots();

        const committed = await service.commitNoteTransaction({
            transactionId: 'txn-1',
            noteId: 'note-1',
            expectedRevision: 101,
            content: 'after-json',
            markdownContent: 'after',
        });
        const stale = await service.commitNoteTransaction({
            transactionId: 'txn-stale',
            noteId: 'note-1',
            expectedRevision: 101,
            content: 'different-json',
            markdownContent: 'different',
        });
        const replay = await service.commitNoteTransaction({
            transactionId: 'txn-1',
            noteId: 'note-1',
            expectedRevision: 101,
            content: 'after-json',
            markdownContent: 'after',
        });

        expect(committed.status).toBe('committed');
        expect(committed.actualRevision).toBeGreaterThan(101);
        expect(stale.status).toBe('conflict');
        expect(stale.actualRevision).toBe(committed.actualRevision);
        expect(replay.status).toBe('already_committed');
        expect(replay.actualRevision).toBe(committed.actualRevision);
        expect(row['content']).toBe('after-json');
        expect(row['markdown_content']).toBe('after');
    });

    it('publishes every multi-note mutation in one WAL batch', async () => {
        const rows = new Map<string, Record<string, unknown>>([
            ['note-1', noteRow(10, 'one', 'note-1', 'story-1')],
            ['note-2', noteRow(20, 'two', 'note-2', 'story-1')],
        ]);
        const batches: any[] = [];
        let marker: Record<string, unknown> | null = null;
        const backend = {
            isReady: true,
            storeCommand: async (command: string, payload?: any) => {
                if (command === 'note:get') return rows.get(payload.id) || null;
                if (command === 'relation:getFirst') return marker;
                if (command === 'persistence:applyWalBatch') {
                    for (const record of payload.records) {
                        if (record.command === 'note:upsert') rows.set(record.payload.row.id, record.payload.row);
                        if (record.command === 'relation:upsert') marker = record.payload.row;
                    }
                    return null;
                }
                throw new Error(`Unexpected command: ${command}`);
            },
        };
        const persistence = {
            appendWalBatch: async (batch: any) => {
                batches.push(batch);
                return { activeSegmentBytes: 256, activeSegmentRecordCount: 2, bytesWritten: 256 };
            },
            commitManifest: async () => undefined,
        };
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [
            PhoenixStoreService,
            { provide: PhoenixBackendService, useValue: backend },
            { provide: SqlitePersistenceService, useValue: persistence },
        ] });
        const service = TestBed.inject(PhoenixStoreService);
        Object.assign(service as any, { initialized: true, manifest: createEmptyPhoenixManifest(1) });
        service.pauseSnapshots();

        const result = await service.commitMultiNoteTransaction({
            transactionId: 'multi-1',
            mutations: [
                { noteId: 'note-1', expectedRevision: 10, after: storeNote('note-1', 10, 'ONE') },
                { noteId: 'note-2', expectedRevision: 20, after: storeNote('note-2', 20, 'TWO') },
            ],
        });
        const replay = await service.commitMultiNoteTransaction({
            transactionId: 'multi-1',
            mutations: [
                { noteId: 'note-1', expectedRevision: 10, after: storeNote('note-1', 10, 'ONE') },
                { noteId: 'note-2', expectedRevision: 20, after: storeNote('note-2', 20, 'TWO') },
            ],
        });

        expect(result.status).toBe('committed');
        expect(replay.status).toBe('already_committed');
        expect(batches).toHaveLength(1);
        expect(batches[0].records).toHaveLength(3);
        expect(batches[0].records[2]).toEqual(expect.objectContaining({
            command: 'relation:upsert',
            payload: expect.objectContaining({ relation: 'canvas_note_transactions' }),
        }));
        expect(rows.get('note-1')?.['markdown_content']).toBe('ONE');
        expect(rows.get('note-2')?.['markdown_content']).toBe('TWO');
        expect(result.notes[0].version).toBe(result.notes[1].version);
    });

    it('rejects all mutations before WAL publication when any note conflicts', async () => {
        const rows = new Map<string, Record<string, unknown>>([
            ['note-1', noteRow(10, 'one', 'note-1', 'story-1')],
            ['note-2', noteRow(21, 'two', 'note-2', 'story-1')],
        ]);
        let appendCount = 0;
        const backend = {
            isReady: true,
            storeCommand: async (command: string, payload?: any) => {
                if (command === 'note:get') return rows.get(payload.id) || null;
                if (command === 'relation:getFirst') return null;
                throw new Error(`Unexpected command: ${command}`);
            },
        };
        const persistence = {
            appendWalBatch: async () => { appendCount++; return {}; },
            commitManifest: async () => undefined,
        };
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [
            PhoenixStoreService,
            { provide: PhoenixBackendService, useValue: backend },
            { provide: SqlitePersistenceService, useValue: persistence },
        ] });
        const service = TestBed.inject(PhoenixStoreService);
        Object.assign(service as any, { initialized: true, manifest: createEmptyPhoenixManifest(1) });
        service.pauseSnapshots();

        const result = await service.commitMultiNoteTransaction({
            transactionId: 'multi-conflict',
            mutations: [
                { noteId: 'note-1', expectedRevision: 10, after: storeNote('note-1', 10, 'ONE') },
                { noteId: 'note-2', expectedRevision: 20, after: storeNote('note-2', 20, 'TWO') },
            ],
        });

        expect(result.status).toBe('conflict');
        expect(result.conflicts).toEqual([expect.objectContaining({ noteId: 'note-2', actualRevision: 21 })]);
        expect(appendCount).toBe(0);
        expect(rows.get('note-1')?.['markdown_content']).toBe('one');
    });
});

function noteRow(version: number, markdown: string, id = 'note-1', narrativeId = ''): Record<string, unknown> {
    return {
        id,
        version,
        world_id: '',
        title: 'Shortrun B',
        content: `${markdown}-json`,
        markdown_content: markdown,
        folder_id: null,
        entity_kind: null,
        entity_subtype: null,
        is_entity: false,
        is_pinned: false,
        favorite: false,
        owner_id: null,
        narrative_id: narrativeId,
        order: 0,
        created_at: 1,
        updated_at: version,
    };
}

function storeNote(id: string, version: number, markdownContent: string) {
    return PhoenixStoreService.fromDexieNote({
        id, version, updatedAt: version, createdAt: 1, title: id,
        content: `${markdownContent}-json`, markdownContent,
        folderId: '', narrativeId: 'story-1', order: 0,
    });
}
