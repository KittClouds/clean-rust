import '@angular/compiler';
import { Injector, computed, createEnvironmentInjector, runInInjectionContext, signal, type EnvironmentInjector } from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const notesMock = vi.hoisted(() => ({
    rows: [] as any[],
    bodyRows: new Map<string, any>(),
    bulkGet: vi.fn(async (ids: string[]) => ids.map((id) => notesMock.bodyRows.get(id) || notesMock.rows.find((row) => row.id === id))),
    toArray: vi.fn(async () => notesMock.rows),
}));

const registryMock = vi.hoisted(() => ({
    entities: [] as any[],
    getAllEntities: vi.fn(() => registryMock.entities),
    updateEntity: vi.fn((id: string, updates: any) => {
        const entity = registryMock.entities.find((row) => row.id === id);
        if (!entity) return null;
        Object.assign(entity, updates, {
            attributes: { ...(entity.attributes || {}), ...(updates.attributes || {}) },
        });
        return entity;
    }),
}));

vi.mock('../lib/dexie/db', () => ({
    db: {
        notes: {
            bulkGet: notesMock.bulkGet,
            toArray: notesMock.toArray,
        },
    },
}));

vi.mock('../lib/registry', () => ({
    smartGraphRegistry: registryMock,
}));

import { GraphRebuildPipelineService } from './graph-rebuild-pipeline.service';
import { GraphRebuildService } from './graph-rebuild.service';
import { AtlasCapabilityRuntimeService } from '../services/atlas-capability-runtime.service';
import { NerService } from '../services/ner.service';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixUiApiService } from '../services/phoenix-ui-api.service';
import type { GraphIndexRunReceipt, GraphIndexRunRequest, GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import { sealGraphSnapshotAuthority } from './graph-snapshot-authority';
import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
import type { GraphCalendarRegistryBridgeSummary } from './graph-calendar-registry-bridge';
import type { GraphMemoryGraphRagBridgeSummary } from './graph-memory-graphrag-bridge';
import type { GraphDiscourseSpineSummary } from './graph-discourse-spine';
import type { GraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';
import type { GraphDiscourseBridgeAdjudicationSummary } from './graph-discourse-bridge-adjudication';
import type { GraphDiscourseEvalLedgerSummary } from './graph-discourse-eval-ledger';
import type { GraphDiscoursePromotionSurfaceSummary } from './graph-discourse-promotion-surface';
import type { GraphDiscourseCompilerOverlaySummary } from './graph-discourse-compiler-overlay';
import {
    GRAPH_ATLAS_BUILDER_ROLE,
    GRAPH_ATLAS_IDENTITY_AUTHORITY,
    GRAPH_ATLAS_PACKET_AUTHORITY,
} from './graph-atlas-packet';

describe('GraphRebuildPipelineService', () => {
    let injector: EnvironmentInjector;
    let graphRebuild: ReturnType<typeof createGraphRebuildMock>;
    let atlasRuntime: ReturnType<typeof createAtlasRuntimeMock>;
    let ner: ReturnType<typeof createNerMock>;
    let store: ReturnType<typeof createPhoenixStoreMock>;
    let phoenixUiApi: ReturnType<typeof createPhoenixUiApiMock>;
    let service: GraphRebuildPipelineService;

    beforeEach(() => {
        notesMock.bodyRows.clear();
        notesMock.rows = [{
            id: 'note-1',
            title: 'Short Run',
            markdownContent: 'Kai met Hazel. Hazel answered Kai.',
            content: '',
            folderId: '',
            updatedAt: 10,
            version: 2,
        }];
        notesMock.bulkGet.mockClear();
        notesMock.toArray.mockClear();
        registryMock.entities = [
            { id: 'entity-kai', label: 'Kai', aliases: [], kind: 'CHARACTER' },
            { id: 'entity-hazel', label: 'Hazel', aliases: [], kind: 'CHARACTER' },
        ];
        registryMock.getAllEntities.mockClear();
        registryMock.updateEntity.mockClear();
        graphRebuild = createGraphRebuildMock();
        atlasRuntime = createAtlasRuntimeMock();
        ner = createNerMock();
        store = createPhoenixStoreMock();
        phoenixUiApi = createPhoenixUiApiMock();
        injector = createEnvironmentInjector([
            { provide: GraphRebuildService, useValue: graphRebuild },
            { provide: AtlasCapabilityRuntimeService, useValue: atlasRuntime },
            { provide: NerService, useValue: ner },
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: {
                isReady: true,
                currentRuntimeInfo: () => ({
                    ready: true,
                    buildGitSha: 'test',
                    buildProfile: 'test',
                    target: 'test',
                    storage: 'test',
                    schemaVersion: 'test',
                    binaryBlake3: 'b3-test',
                    nativeGraphContract: 'phoenix-verified-force/v2',
                }),
            } },
            { provide: PhoenixUiApiService, useValue: phoenixUiApi },
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        service = runInInjectionContext(injector, () => new GraphRebuildPipelineService());
    });

    afterEach(async () => {
        await flushPostCommitDiagnostics(service);
        await flushReceiptPersistence(service);
        injector.destroy();
        vi.unstubAllGlobals();
        vi.clearAllMocks();
    });

    it('blocks graph builds while the dynamic NER prerequisite is cold', async () => {
        atlasRuntime.capabilityState.mockImplementation((capability: string) => ({
            requiredModels: [{
                id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                readiness: capability === 'dynamicNer' ? 'idle' : 'ready',
                statusLabel: 'idle',
            }],
        }));

        await expect(service.buildGraph({ ...request(), policy: 'force' })).rejects.toThrow('Load graph models first');

        expect(ner.scanDynamicBatch).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('rejects a quarantined persisted scope before documents or models run', async () => {
        graphRebuild.assertBuildPolicyAuthorized.mockImplementation(() => {
            throw new Error('Automatic cold fallback is disabled');
        });

        await expect(service.buildGraph({ ...request(), policy: 'delta' }))
            .rejects.toThrow('Automatic cold fallback is disabled');

        expect(notesMock.bulkGet).not.toHaveBeenCalled();
        expect(ner.scanDynamicBatch).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('stages only the lightweight build prerequisite and leaves NLI on demand', async () => {
        await service.loadGraphModels(request());

        expect(atlasRuntime.warmModelLane).toHaveBeenCalledTimes(1);
        expect(atlasRuntime.warmModelLane).toHaveBeenCalledWith('dynamicNer', expect.any(Object));
        expect(atlasRuntime.warmModelLane).not.toHaveBeenCalledWith('nli', expect.any(Object));
    });

    it('restores exact compact generation content for embedding after a fresh pipeline start', async () => {
        const shell = {
            id: 'snapshot-lease-1',
            scopeId: 'global',
            authorityContract: { contentHash: 'authority-lease-1' },
            interactiveRunAuthority: { inputIdentity: 'input-lease-1' },
            generationReceiptId: 'receipt-lease-1',
            generationDigestSha256: 'digest-lease-1',
            contentManifest: {
                refs: { evidenceTargetRegistryPage: { key: 'page-1' } },
            },
        } as GraphRebuildSnapshot;
        const receipt = {
            receiptId: 'receipt-lease-1',
            digestSha256: 'digest-lease-1',
            snapshotId: 'snapshot-lease-1',
            scopeId: 'global',
            inputIdentity: 'input-lease-1',
            authority: { contentHash: 'authority-lease-1' },
        };
        const hydrated = { ...shell, embeddingTargets: [{ id: 'target-1' }] } as GraphRebuildSnapshot;
        graphRebuild.loadPersistedSnapshotShell.mockResolvedValueOnce(shell);
        graphRebuild.loadPersistedGenerationReceipt.mockResolvedValueOnce(receipt);
        graphRebuild.loadVerifiedGenerationSnapshotContent.mockResolvedValueOnce(hydrated);

        await expect(service.loadSnapshotContentForEmbedding('global')).resolves.toBe(hydrated);

        expect(graphRebuild.loadPersistedSnapshotShell).toHaveBeenCalledWith('global');
        expect(graphRebuild.loadVerifiedGenerationSnapshotContent).toHaveBeenCalledWith(shell);
    });

    it('requires explicit migration for a resident legacy snapshot before embedding', async () => {
        graphRebuild.snapshot.mockReturnValue({
            id: 'legacy-snapshot',
            scopeId: 'global',
        } as GraphRebuildSnapshot);

        await expect(service.loadSnapshotContentForEmbedding('global'))
            .rejects.toThrow('PHX_GRAPH_CONTENT_LEASE_CAPABILITY_MISSING');

        expect(graphRebuild.loadVerifiedGenerationSnapshotContent).not.toHaveBeenCalled();
    });

    it('builds the graph in one pass without invoking Semantic Atlas', async () => {
        atlasRuntime.capabilityState.mockImplementation((capability: string) => ({
            requiredModels: [{
                id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                readiness: capability === 'semanticAtlas' ? 'idle' : 'ready',
                statusLabel: capability === 'semanticAtlas' ? 'idle' : 'ready',
            }],
        }));

        const result = await service.buildGraph({
            ...request(),
            policy: 'force',
        });

        expect(ner.scanDynamicBatch).toHaveBeenCalledTimes(1);
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('semanticAtlas', expect.anything());
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('nliAdjudication', expect.objectContaining({
            buildPolicy: 'force',
            skipModelWarm: true,
        }));
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledTimes(1);
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            postProcessMode: 'full',
            relationshipHints: [expect.objectContaining({
                sourceId: 'entity-kai',
                targetId: 'entity-hazel',
                status: 'accepted',
            })],
        }));
        expect(result.receipt.id).toContain('graph-atlas:');
        expect(result.receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({ id: 'dynamicNer', label: 'Dynamic NER + Alex Deltas' }),
            expect.objectContaining({ id: 'deltaPostprocessPlan', label: 'Delta Postprocess Plan' }),
            expect.objectContaining({ id: 'signalCandidatePlan', label: 'Signal Candidate Plan' }),
            expect.objectContaining({ id: 'nliCandidatePlan', label: 'NLI Candidate Plan' }),
            expect.objectContaining({ id: 'graphBuildSnapshot', label: 'Build Graph Snapshot' }),
            expect.objectContaining({ id: 'receiptDbOps', label: 'Receipt DB Ops' }),
        ]));
        expect(result.receipt.projectionReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                mode: 'hybrid',
                status: 'synced',
                counters: expect.objectContaining({
                    graphRebuildReadModelProjection: 1,
                    nativeSemanticSidecarBypassed: 1,
                }),
            }),
        ]));
        expect(result.receipt.layerReceipts.map((layer) => layer.id)).toEqual(expect.arrayContaining([
            'input-signals',
            'snapshot-truth',
            'native-atlas-packet',
            'authority-seal',
            'persistence-payload',
            'projection-lenses',
            'diagnostic-ledgers',
            'transport-boundary',
            'ui-commit',
        ]));
        expect(result.receipt.layerReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'authority-seal',
                status: 'complete',
                contentHash: result.snapshot.authorityContract?.contentHash,
            }),
            expect.objectContaining({
                id: 'projection-lenses',
                status: 'complete',
                projectionModes: expect.arrayContaining(['hybrid', 'hopf', 'lorentz', 'product', 'siegel']),
            }),
        ]));
    });

    it('routes interactive FORCE exclusively through verified native v2', async () => {
        const seeded = await seedVerifiedForceV2(service, graphRebuild, ner, atlasRuntime);

        const result = await service.buildGraph({ ...request(), durabilityMode: 'interactive' });

        expect(result.receipt.pathId).toBe('native_verified_force_v2');
        expect(result.receipt.fallbackCount).toBe(0);
        expect(result.receipt.snapshotId).toBe(seeded.snapshot.id);
        expect(graphRebuild.verifyForceV2FromAuthority).toHaveBeenCalledTimes(1);
        expect(ner.scanDynamicBatch).not.toHaveBeenCalled();
        expect(atlasRuntime.runCapability).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
        await flushReceiptPersistence(service);
        const persisted = graphRebuild.persistRunReceipt.mock.calls.at(-1)?.[0] as GraphIndexRunReceipt;
        expect(persisted.stageReceipts.find((stage) => stage.id === 'verifiedForceV2'))
            .toMatchObject({
                spanId: expect.stringContaining(':verifiedForceV2'),
                parentSpanId: persisted.spanId,
                counters: { pathVerified: 1, fallbackCount: 0 },
            });
    });

    it('refreshes observable note versions without changing the verified content cohort', async () => {
        const seeded = await seedVerifiedForceV2(service, graphRebuild, ner, atlasRuntime, {
            version: 3,
            updatedAt: 4,
        });

        const result = await service.buildGraph({ ...request(), durabilityMode: 'interactive' });

        expect(result.receipt.replayManifest?.cohortId).toBe(seeded.receipt.replayManifest?.cohortId);
        expect(result.receipt.replayManifest?.documents[0]).toMatchObject({ version: 3, updatedAt: 4 });
        expect(result.receipt.stageReceipts.find((stage) => stage.id === 'verifiedForceV2')?.counters)
            .toMatchObject({ sourceVersionEnvelopeChanged: 1 });
    });

    it('fails closed when interactive FORCE has no exact persisted replay', async () => {
        await expect(service.buildGraph({ ...request(), durabilityMode: 'interactive' }))
            .rejects.toThrow('PHX_FORCE_V2_REPLAY_MISSING');

        expect(ner.scanDynamicBatch).not.toHaveBeenCalled();
        expect(atlasRuntime.runCapability).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('offers a named one-time bootstrap without weakening ordinary FORCE rejection', async () => {
        const result = await service.bootstrapVerifiedForceV2({
            ...request(),
            durabilityMode: 'interactive',
        });

        expect(result.receipt.pathId).toBe('explicit_force_v2_bootstrap_v1');
        expect(result.receipt.fallbackCount).toBe(0);
        expect(result.receipt.message).toContain('Explicit V2 bootstrap');
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledTimes(1);
        expect(graphRebuild.persistForceV2Authority).toHaveBeenCalledTimes(1);
        expect(result.receipt.verifiedForceAuthority).toMatchObject({
            schemaVersion: 'phoenix-verified-force-authority-ref/v1',
            snapshotId: result.snapshot.id,
        });
    });

    it('allows explicit bootstrap only to migrate a missing durable registry page', async () => {
        graphRebuild.loadPersistedRunReceipt.mockResolvedValueOnce({
            replayManifest: { schemaVersion: 'phoenix-graph-rebuild-replay-manifest/v1' },
        });
        graphRebuild.loadPersistedSnapshotShell.mockResolvedValueOnce({
            id: 'old-snapshot',
            scopeId: 'global',
            contentManifest: { refs: {} },
        } as GraphRebuildSnapshot);

        const result = await service.bootstrapVerifiedForceV2({
            ...request(),
            durabilityMode: 'interactive',
        });

        expect(result.receipt.pathId).toBe('explicit_force_v2_bootstrap_v1');
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledTimes(1);
    });

    it('never enters legacy reconstruction after a native v2 rejection', async () => {
        await seedVerifiedForceV2(service, graphRebuild, ner, atlasRuntime);
        graphRebuild.verifyForceV2FromAuthority.mockRejectedValueOnce(
            new Error('PHX_FORCE_V2_SECTION_INVALID: durable section rejected'),
        );

        await expect(service.buildGraph({ ...request(), durabilityMode: 'interactive' }))
            .rejects.toThrow('PHX_FORCE_V2_SECTION_INVALID');

        expect(ner.scanDynamicBatch).not.toHaveBeenCalled();
        expect(atlasRuntime.runCapability).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('makes Delta structurally reuse-only when no authoritative graph exists', async () => {
        atlasRuntime.capabilityState.mockImplementation((capability: string) => ({
            requiredModels: [{
                id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                readiness: 'idle',
                statusLabel: 'idle',
            }],
        }));

        await expect(service.buildGraph({ ...request(), policy: 'delta', durabilityMode: 'interactive' }))
            .rejects.toThrow('Delta cannot reconstruct');

        expect(ner.scanDynamicBatch).not.toHaveBeenCalled();
        expect(atlasRuntime.runCapability).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('debounces post-commit work and cancels stale diagnostics before they start', async () => {
        const timers: ScheduledCallback[] = [];
        const idleCallbacks: ScheduledCallback[] = [];
        vi.stubGlobal('window', {
            setTimeout: (callback: () => void) => {
                const row = scheduledCallback(timers, callback);
                return row.id;
            },
            clearTimeout: (id: number) => {
                const row = timers.find((timer) => timer.id === id);
                if (row) row.cancelled = true;
            },
            requestIdleCallback: (callback: () => void) => {
                const row = scheduledCallback(idleCallbacks, callback);
                return row.id;
            },
            cancelIdleCallback: (id: number) => {
                const row = idleCallbacks.find((callback) => callback.id === id);
                if (row) row.cancelled = true;
            },
        });
        const internal = service as any;
        internal.lastSnapshotState.set({ id: 'snapshot-current' });
        const input = {
            scope: request().scope,
            entities: request().entities,
            acceptedNerOccurrences: [],
            relationshipHints: [],
            request: request(),
            nerCandidates: 0,
            baseRunSerial: 7,
        };

        internal.scheduleInteractivePostCommitWork({ ...input, snapshotId: 'snapshot-stale' });
        internal.scheduleInteractivePostCommitWork({ ...input, snapshotId: 'snapshot-current' });
        runScheduledCallbacks(timers);
        expect(idleCallbacks).toHaveLength(1);

        internal.lastSnapshotState.set({ id: 'snapshot-new' });
        internal.scheduleInteractivePostCommitWork({ ...input, snapshotId: 'snapshot-new', baseRunSerial: 8 });
        runScheduledCallbacks(idleCallbacks);
        await flushPostCommitDiagnostics(service);
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();

        runScheduledCallbacks(timers);
        runScheduledCallbacks(idleCallbacks);
        await flushPostCommitDiagnostics(service);
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            durabilityMode: 'diagnostic',
            diagnosticBaseSnapshotId: 'snapshot-new',
            diagnosticBaseSnapshotRunSerial: 8,
        }));
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledTimes(1);
    });

    it('expands global graph rebuilds to loaded note ids for deterministic chunking', async () => {
        notesMock.rows = [
            {
                id: 'note-1',
                title: 'First',
                markdownContent: 'Kai mapped Red Mesa.',
                content: '',
                folderId: '',
                updatedAt: 10,
                version: 2,
            },
            {
                id: 'note-2',
                title: 'Second',
                markdownContent: 'Rowan watched Boundary Keep.',
                content: '',
                folderId: '',
                updatedAt: 11,
                version: 3,
            },
        ];

        await service.buildGraph({
            ...request(),
            scope: { kind: 'global', scopeId: 'global', label: 'Global', noteIds: [] },
            policy: 'force',
        });
        await flushReceiptPersistence(service);

        expect(notesMock.toArray).toHaveBeenCalled();
        expect(ner.scanDynamicBatch).toHaveBeenCalledTimes(1);
        expect(ner.scanDynamicBatch).toHaveBeenCalledWith([
            expect.objectContaining({ noteId: 'note-1' }),
            expect.objectContaining({ noteId: 'note-2' }),
        ]);
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
        }));
        expect(graphRebuild.persistRunReceipt).toHaveBeenCalledWith(expect.objectContaining({
            scope: expect.objectContaining({
                kind: 'global',
                scopeId: 'global',
                noteIds: ['note-1', 'note-2'],
            }),
        }));
    });

    it('removes stale selected ids from multi-note graph rebuild scopes', async () => {
        notesMock.rows = [
            {
                id: 'note-1',
                title: 'First',
                markdownContent: 'Kai mapped Red Mesa.',
                content: '',
                folderId: '',
                updatedAt: 10,
                version: 2,
            },
            {
                id: 'note-2',
                title: 'Second',
                markdownContent: 'Rowan watched Boundary Keep.',
                content: '',
                folderId: '',
                updatedAt: 11,
                version: 3,
            },
        ];

        await service.buildGraph({
            ...request(),
            scope: {
                kind: 'multiNote',
                scopeId: 'multi:note-1|deleted-note|note-2',
                label: '3 notes',
                noteIds: ['note-1', 'deleted-note', 'note-2'],
            },
            policy: 'force',
        });
        await flushReceiptPersistence(service);

        expect(notesMock.bulkGet).toHaveBeenCalledWith(['note-1', 'deleted-note', 'note-2']);
        expect(ner.scanDynamicBatch).toHaveBeenCalledTimes(1);
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            scopeKind: 'multiNote',
            noteIds: ['note-1', 'note-2'],
        }));
        expect(graphRebuild.persistRunReceipt).toHaveBeenCalledWith(expect.objectContaining({
            scope: expect.objectContaining({
                kind: 'multiNote',
                noteIds: ['note-1', 'note-2'],
            }),
        }));
    });

    it('hydrates unopened selected notes before graph rebuild stages', async () => {
        notesMock.rows = [
            {
                id: 'note-1',
                title: 'First',
                markdownContent: '',
                content: '',
                folderId: '',
                updatedAt: 10,
                version: 2,
                hasBody: false,
            },
            {
                id: 'note-2',
                title: 'Second',
                markdownContent: '',
                content: '',
                folderId: '',
                updatedAt: 11,
                version: 3,
                hasBody: false,
            },
        ];
        notesMock.bodyRows.set('note-1', {
            ...notesMock.rows[0],
            markdownContent: 'Kai mapped Red Mesa. '.repeat(120),
            hasBody: true,
        });
        notesMock.bodyRows.set('note-2', {
            ...notesMock.rows[1],
            markdownContent: 'Rowan watched Boundary Keep. '.repeat(120),
            hasBody: true,
        });

        await service.buildGraph({
            ...request(),
            scope: {
                kind: 'multiNote',
                scopeId: 'multi:note-1|note-2',
                label: '2 notes',
                noteIds: ['note-1', 'note-2'],
            },
            policy: 'force',
        });

        expect(notesMock.bulkGet).toHaveBeenCalledWith(['note-1', 'note-2']);
        expect(ner.scanDynamicBatch).toHaveBeenCalledWith([
            expect.objectContaining({
                noteId: 'note-1',
                plainText: expect.stringContaining('Kai mapped Red Mesa. Kai mapped Red Mesa.'),
            }),
            expect.objectContaining({
                noteId: 'note-2',
                plainText: expect.stringContaining('Rowan watched Boundary Keep. Rowan watched Boundary Keep.'),
            }),
        ]);
    });

    it('resumes content checkpoints once clean graph receipt persistence is queued', async () => {
        await service.buildGraph(request());
        await flushReceiptPersistence(service);

        expect(store.pauseSnapshots).toHaveBeenCalledTimes(1);
        expect(store.resumeSnapshots).toHaveBeenCalledTimes(1);
        expect(store.pauseSnapshots.mock.invocationCallOrder[0])
            .toBeLessThan(graphRebuild.buildAndPersistSnapshot.mock.invocationCallOrder[0]);
        expect(graphRebuild.buildAndPersistSnapshot.mock.invocationCallOrder[0])
            .toBeLessThan(store.resumeSnapshots.mock.invocationCallOrder[0]);
        expect(store.resumeSnapshots.mock.invocationCallOrder[0])
            .toBeLessThan(graphRebuild.persistRunReceipt.mock.invocationCallOrder[0]);
    });

    it('returns buildGraph before the queued run receipt write completes', async () => {
        const persistGate = deferred<void>();
        graphRebuild.persistRunReceipt.mockImplementationOnce(async () => {
            await persistGate.promise;
            return receiptStoreTiming();
        });

        const result = await service.buildGraph(request());
        const receiptDbOps = result.receipt.stageReceipts.find((stage) => stage.id === 'receiptDbOps');

        expect(receiptDbOps).toEqual(expect.objectContaining({
            status: 'running',
            counters: expect.objectContaining({
                receiptPersistenceQueued: 1,
                receiptPersistenceAsync: 1,
            }),
        }));
        expect(store.resumeSnapshots).toHaveBeenCalledTimes(1);
        expect(graphRebuild.persistRunReceipt).not.toHaveBeenCalled();
        expect(result.receipt.stageReceipts.find((stage) => stage.id === 'receiptDbOps')?.status).toBe('running');

        try {
            await waitForReceiptPersistenceStart();
            expect(graphRebuild.persistRunReceipt).toHaveBeenCalledTimes(1);
            expect(store.resumeSnapshots.mock.invocationCallOrder[0])
                .toBeLessThan(graphRebuild.persistRunReceipt.mock.invocationCallOrder[0]);
        } finally {
            persistGate.resolve();
        }
        await flushReceiptPersistence(service);

        expect(service.lastReceipt()?.stageReceipts.find((stage) => stage.id === 'receiptDbOps'))
            .toEqual(expect.objectContaining({
                status: 'completed',
                counters: expect.objectContaining({
                    receiptPersistenceAsync: 1,
                    receiptStoreScopedDocuments: 1,
                }),
            }));
    });

    it('coalesces queued run receipt writes by scope before persistence starts', async () => {
        const internal = service as any;
        const first = receiptForPersistenceTest('receipt:first', 'note:note-1', 'delta');
        const second = receiptForPersistenceTest('receipt:second', 'note:note-1', 'force');

        internal.enqueueRunReceiptPersistence(first);
        internal.enqueueRunReceiptPersistence(second);
        await flushReceiptPersistence(service);

        expect(graphRebuild.persistRunReceipt).toHaveBeenCalledTimes(1);
        const persisted = graphRebuild.persistRunReceipt.mock.calls[0][0] as GraphIndexRunReceipt;
        expect(persisted.id).toBe(second.id);
        expect(persisted.policy).toBe('force');
        expect(persisted.stageReceipts.some((stage) => stage.id === 'receiptDbOps')).toBe(false);
    });

    it('keeps queued receipt writes for different scopes', async () => {
        const internal = service as any;
        const first = receiptForPersistenceTest('receipt:first', 'note:note-1', 'delta');
        const second = receiptForPersistenceTest('receipt:second', 'note:note-2', 'force');

        internal.enqueueRunReceiptPersistence(first);
        internal.enqueueRunReceiptPersistence(second);
        await flushReceiptPersistence(service);

        expect(graphRebuild.persistRunReceipt).toHaveBeenCalledTimes(2);
        expect(graphRebuild.persistRunReceipt.mock.calls.map((call) => call[0].id))
            .toEqual(['receipt:first', 'receipt:second']);
    });

    it('runs post-commit diagnostics after queued receipt persistence', async () => {
        const receiptGate = deferred<void>();
        const internal = service as any;
        internal.receiptPersistenceQueue = receiptGate.promise;
        internal.postCommitDiagnosticToken = 1;
        internal.lastSnapshotState.set({ id: 'snapshot-current' });
        const input = {
            scope: request().scope,
            snapshotId: 'snapshot-current',
            entities: request().entities,
            acceptedNerOccurrences: [],
            relationshipHints: [],
            request: request(),
            nerCandidates: 0,
            baseRunSerial: 9,
        };

        const work = internal.runPostCommitDiagnosticWork(input, 1) as Promise<void>;
        await Promise.resolve();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
        receiptGate.resolve();
        await work;

        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            durabilityMode: 'diagnostic',
            diagnosticBaseSnapshotId: 'snapshot-current',
            diagnosticBaseSnapshotRunSerial: 9,
        }));
    });

    it('resumes deferred content checkpoints after graph snapshot failures', async () => {
        graphRebuild.buildAndPersistSnapshot.mockRejectedValueOnce(new Error('snapshot boom'));

        await expect(service.buildGraph(request())).rejects.toThrow('snapshot boom');

        expect(store.pauseSnapshots).toHaveBeenCalledTimes(1);
        expect(store.resumeSnapshots).toHaveBeenCalledTimes(1);
    });

    it('does not rewrite entity kinds from Angular location context during rebuild', async () => {
        notesMock.rows = [{
            id: 'note-1',
            title: 'Release Terms',
            markdownContent: "Germany's price is exchange. Kai said yes.",
            content: '',
            folderId: '',
            updatedAt: 10,
            version: 2,
        }];
        registryMock.entities = [
            { id: 'entity-germany', label: 'Germany', aliases: [], kind: 'CHARACTER', attributes: {} },
            { id: 'entity-kai', label: 'Kai', aliases: [], kind: 'CHARACTER', attributes: {} },
        ];

        await service.buildGraph(request());

        expect(registryMock.updateEntity).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            entities: expect.arrayContaining([
                expect.objectContaining({ id: 'entity-germany', kind: 'CHARACTER' }),
            ]),
        }));
    });
});

function request(): GraphIndexRunRequest {
    return {
        scope: { kind: 'note', scopeId: 'note:note-1', label: 'Short Run', noteIds: ['note-1'] },
        policy: 'force',
        durabilityMode: 'diagnostic',
        modelSelection: {
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'mongodb-leaf-mt',
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
            nliModelId: 'modernbert-nli',
        },
        calendarRegistrySnapshot: calendarRegistrySnapshot(),
        entities: registryMock.entities,
    };
}

async function seedVerifiedForceV2(
    service: GraphRebuildPipelineService,
    graphRebuild: ReturnType<typeof createGraphRebuildMock>,
    ner: ReturnType<typeof createNerMock>,
    atlasRuntime: ReturnType<typeof createAtlasRuntimeMock>,
    sourceVersionEnvelope?: { version: number; updatedAt: number },
) {
    const legacy = await service.buildGraph(request());
    const durable = nativeDurableReuseReceipt();
    const snapshot: GraphRebuildSnapshot = {
        ...legacy.snapshot,
        interactiveRunAuthority: {
            schemaVersion: 'phoenix-interactive-graph-run-authority/v1',
            inputIdentity: 'sha256:interactive-input',
            snapshotId: legacy.snapshot.id,
            scopeId: legacy.snapshot.scopeId,
            durable,
        },
    };
    const authorityHash = snapshot.authorityContract!.contentHash;
    const replay = legacy.receipt.replayManifest!;
    const receipt: GraphIndexRunReceipt = {
        ...legacy.receipt,
        durabilityMode: 'interactive',
        snapshotId: snapshot.id,
        authorityContract: snapshot.authorityContract,
        verifiedForceAuthority: {
            schemaVersion: 'phoenix-verified-force-authority-ref/v1',
            snapshotId: snapshot.id,
            authorityHash,
            manifestId: durable.manifestId,
            runHandle: durable.runHandle,
        },
    };
    const verifiedSections = [
        'bridge', 'continuity', 'governance', 'hyperedges',
        'metadata', 'promotion', 'retrieval', 'siegel',
    ].map((name) => ({ name, identity: `b3-${name}`, rowCount: 1, rawBytes: 100, compressedBytes: 50 }));
    graphRebuild.loadPersistedRunReceipt.mockResolvedValue(receipt);
    graphRebuild.verifyForceV2FromAuthority.mockResolvedValue({
        result: {
            schemaVersion: 'phoenix-force-rebuild-v2-shadow-result/v1',
            contractVersion: 'phoenix-verified-force/v2',
            pathId: 'native_verified_force_v2',
            fallbackCount: 0,
            status: 'durable_verified',
            scopeId: snapshot.scopeId,
            snapshotId: snapshot.id,
            authorityHash,
            manifestId: durable.manifestId,
            runHandle: durable.runHandle,
            analysisSource: 'durable_verified',
            analysisKernelMicros: 0,
            verifiedSections,
            criticalResponseBytes: 24_000,
            nativeCrossings: 2,
            sourceBodyReads: replay.documents.length,
            sourceUtf8Bytes: replay.aggregate.utf8Bytes,
            transportedSourceBytes: 0,
            sourceDocuments: replay.documents.map((document) => ({
                noteId: document.noteId,
                sha256: document.sha256,
                jsCodeUnitChars: document.jsCodeUnitChars,
                utf8Bytes: document.utf8Bytes,
                version: sourceVersionEnvelope?.version ?? document.version,
                updatedAt: sourceVersionEnvelope?.updatedAt ?? document.updatedAt,
            })),
            sourceVersionEnvelopeChanged: sourceVersionEnvelope !== undefined,
            authorityPacket: snapshot,
            parentSpanId: 'span:root',
            spanId: 'span:v2',
            error: null,
        },
        snapshot,
    });
    ner.scanDynamicBatch.mockClear();
    atlasRuntime.runCapability.mockClear();
    graphRebuild.buildAndPersistSnapshot.mockClear();
    graphRebuild.verifyForceV2FromAuthority.mockClear();
    return { receipt, snapshot };
}

function calendarRegistrySnapshot(): CalendarRegistrySnapshot {
    return {
        schemaVersion: 'phoenix-calendar-registry/v1',
        id: 'calendar-registry:test',
        builtAt: 1,
        calendar: {
            id: 'calendar:test',
            name: 'Pipeline Calendar',
            fingerprint: 'calendar:fingerprint:test',
            mode: 'customOrdinal',
            createdFrom: 'manual',
            monthCount: 12,
            weekdayCount: 7,
            hasYearZero: false,
            defaultEraId: 'era-1',
        },
        scope: { kind: 'note', scopeId: 'note:note-1', noteIds: ['note-1'] },
        anchors: [{
            id: 'calendar-anchor:event-1',
            kind: 'user_calendar_event',
            sourceId: 'event-1',
            sourceLabel: 'Festival',
            calendarId: 'calendar:test',
            calendarFingerprint: 'calendar:fingerprint:test',
            dateKey: 'cal:calendar:test|era:era-1|y:1|m:0|d:0',
            normalizedValue: 'CAL:calendar:test:cal:calendar:test|era:era-1|y:1|m:0|d:0',
            displayDate: 'Month 1 1, 1 CE',
            granularity: 'day',
            date: { year: 1, monthIndex: 0, dayIndex: 0, eraId: 'era-1' },
            ordinal: 0,
            noteId: 'note-1',
            confidence: 0.9,
            evidenceRefs: ['calendar:event:event-1'],
            attributes: {},
        }],
        summary: {
            anchorCount: 1,
            eventAnchorCount: 1,
            folderAnchorCount: 0,
            periodAnchorCount: 0,
            markerAnchorCount: 0,
            realCompatibleAnchorCount: 0,
            customOrdinalAnchorCount: 1,
            sourceKindCounts: { user_calendar_event: 1 },
            diagnostics: {},
            firstOrdinal: 0,
            lastOrdinal: 0,
        },
    };
}

function calendarRegistryBridgeSummary(): GraphCalendarRegistryBridgeSummary {
    return {
        schemaVersion: 'phoenix-calendar-registry-bridge/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        sourceCalendarRegistryId: 'calendar-registry:test',
        calendarId: 'calendar:test',
        calendarFingerprint: 'calendar:fingerprint:test',
        calendarMode: 'customOrdinal',
        scopeKind: 'note',
        scopeId: 'note:note-1',
        receipts: [],
        counters: {
            anchorCount: 1,
            receiptCount: 1,
            acceptedTemporalReceipts: 1,
            registryOnlyReceipts: 0,
            deferredInvalidReceipts: 0,
            customOrdinalReceipts: 1,
            realEpochReceipts: 0,
            eventReceipts: 1,
            folderReceipts: 0,
            periodReceipts: 0,
            markerReceipts: 0,
            mutationAllowedCount: 0,
            diagnostics: {},
        },
    };
}

function memoryGraphRagBridgeSummary(): GraphMemoryGraphRagBridgeSummary {
    return {
        schemaVersion: 'phoenix-memory-graphrag-bridge/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        paperShape: {
            paperName: 'MemGraphRAG: Memory-based Multi-Agent System for Graph Retrieval-Augmented Generation',
            arxivId: '2606.00610',
            implementationMode: 'phoenix_bridge_contract',
            mappedLayers: [],
            skippedRuntimePieces: [],
        },
        agentContracts: [],
        records: [],
        evalRows: [],
        receipts: [],
        compactEvalLedger: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            byLayer: { schema: 1, fact: 1, passage: 1 },
            bySurface: { retrieval_context: 3 },
            byEvalKind: { hierarchical_retrieval: 1, reflection_seed: 1 },
            recordCount: 3,
            schemaRecords: 1,
            factRecords: 1,
            passageRecords: 1,
            observerSeedRecords: 1,
            reflectorSeedRecords: 1,
            retrievalRecords: 3,
            conflictRecords: 0,
            evalRowCount: 2,
            passedEvalRows: 2,
            failedEvalRows: 0,
            receiptCount: 5,
            reversibleReceiptCount: 5,
            mutationAllowedCount: 0,
        },
    };
}

function discourseSpineSummary(): GraphDiscourseSpineSummary {
    return {
        schemaVersion: 'phoenix-discourse-spine/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        implementationMode: 'deterministic_registry',
        invariant: 'wormholes_are_proposals_not_edges',
        targets: [],
        labels: [],
        clusters: [],
        bridges: [],
        receipts: [],
        compactBridgeLedger: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            targetCount: 3,
            documentRoots: 1,
            documents: 1,
            chunks: 1,
            labelCount: 21,
            clusterCount: 2,
            bridgeCount: 2,
            resonanceCandidates: 1,
            resolutionCandidates: 1,
            proposedBridges: 1,
            deferredBridges: 1,
            rejectedBridges: 0,
            receiptCount: 25,
            reversibleReceiptCount: 25,
            mutationAllowedCount: 0,
            byLabelKind: { domain: 3 },
            byClusterKind: { document_family: 1 },
            byBridgeKind: { resonance: 1, resolution: 1 },
        },
    };
}

function discourseBridgeCandidateSummary(): GraphDiscourseBridgeCandidateSummary {
    return {
        schemaVersion: 'phoenix-discourse-bridge-candidates/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        sourceDiscourseSpineId: 'snapshot-1',
        modelId: 'knowledgator/gliclass-instruct-base-v1.0',
        runner: 'gliclass-query-label-rerank',
        scoreSource: 'deterministic_calibration',
        invariant: 'discourse_bridges_are_candidates_not_edges',
        labels: [],
        candidates: [],
        inputs: [],
        judgments: [],
        evalRows: [],
        receipts: [],
        compactEvalLedger: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            byCandidateKind: { discourse_resonance: 1, cross_doc_resolution: 1 },
            byStatus: { proposed: 2 },
            byDecision: { accept: 1, review: 1 },
            byEvalKind: { accepted_looking_resonance: 1, cross_doc_resolver_pressure: 1 },
            byScoreSource: { deterministic_calibration: 2 },
            candidateCount: 2,
            inputCount: 2,
            judgmentCount: 2,
            evalRowCount: 2,
            passedEvalRows: 2,
            failedEvalRows: 0,
            receiptCount: 6,
            reversibleReceiptCount: 6,
            mutationAllowedCount: 0,
            plannedModelCalls: 8,
            acceptedLookingResonance: 1,
            weakResonance: 0,
            crossDocResolverPressure: 1,
            entityOverlapWithoutMeaning: 0,
            meaningOverlapWithoutEntity: 0,
            maxCandidates: 128,
            maxPassageChars: 2200,
        },
    };
}

function discourseBridgeAdjudicationSummary(): GraphDiscourseBridgeAdjudicationSummary {
    return {
        schemaVersion: 'phoenix-discourse-bridge-adjudication/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        sourceCandidateSummaryId: 'snapshot-1:discourse-bridge-candidates:1',
        invariant: 'discourse_bridge_decisions_are_ledger_only',
        states: ['proposed', 'supported', 'accepted', 'deferred', 'rejected', 'invalidated', 'superseded'],
        dagEdges: [],
        decisions: [],
        receipts: [],
        compactDecisionLedger: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            byState: { accepted: 1, supported: 1 },
            byCandidateKind: { discourse_resonance: 1, cross_doc_resolution: 1 },
            decisionCount: 2,
            acceptedCount: 1,
            supportedCount: 1,
            deferredCount: 0,
            rejectedCount: 0,
            invalidatedCount: 0,
            supersededCount: 0,
            receiptCount: 2,
            reversibleReceiptCount: 2,
            ledgerOnlyCount: 2,
            topologyCommitCount: 0,
            mutationAllowedCount: 0,
            compactRowCount: 2,
        },
    };
}

function discourseEvalLedgerSummary(): GraphDiscourseEvalLedgerSummary {
    return {
        schemaVersion: 'phoenix-discourse-eval-ledger/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        sourceAdjudicationSummaryId: 'snapshot-1:discourse-bridge-adjudication:1',
        datasetPurpose: [
            'classifier_training',
            'reranker_eval',
            'router_tuning',
            'model_swap_regression',
            'document_cluster_eval',
            'cross_doc_resolver_training',
        ],
        entries: [],
        compactExport: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            rowCount: 2,
            byLabel: { accepted_candidate: 1, ambiguous_case: 1 },
            byCandidateKind: { discourse_resonance: 1, cross_doc_resolution: 1 },
            byState: { accepted: 1, supported: 1 },
            acceptedCandidates: 1,
            rejectedCandidates: 0,
            ambiguousCases: 1,
            userCorrections: 0,
            modelDisagreements: 0,
            manifoldDisagreements: 1,
            evalDisagreements: 0,
            graphChangeRows: 0,
            resonanceRows: 1,
            resolutionRows: 1,
            clusterReviewRows: 0,
        },
    };
}

function discoursePromotionSurfaceSummary(): GraphDiscoursePromotionSurfaceSummary {
    return {
        schemaVersion: 'phoenix-discourse-promotion-surface/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        sourceEvalLedgerId: 'snapshot-1:discourse-eval-ledger:1',
        invariant: 'discourse_promotion_surface_no_topology_commit',
        chunkWormholes: [],
        documentClusters: [],
        resolverCandidates: [],
        compilerHints: [],
        receipts: [],
        compactSurface: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            byHintKind: { chunk_wormhole: 1, document_cluster: 1 },
            byLabel: { accepted_candidate: 1, ambiguous_case: 1 },
            chunkWormholeCount: 1,
            documentClusterCount: 1,
            resolverCandidateCount: 0,
            compilerHintCount: 2,
            receiptCount: 2,
            reversibleReceiptCount: 2,
            graphPatchCount: 0,
            mutationAllowedCount: 0,
            acceptedRows: 1,
            ambiguousRows: 1,
        },
    };
}

function discourseCompilerOverlaySummary(): GraphDiscourseCompilerOverlaySummary {
    return {
        schemaVersion: 'phoenix-discourse-compiler-overlay/v1',
        generatedAt: 1,
        sourceSnapshotId: 'snapshot-1',
        sourcePromotionSurfaceId: 'snapshot-1:discourse-promotion-surface:1',
        invariant: 'discourse_compiler_overlay_no_topology_commit',
        overlayEdges: [],
        receipts: [],
        compactOverlay: { scopeId: 'note:note-1', builtAt: 1, rowCount: 2, rows: [] },
        counters: {
            byKind: { chunk_wormhole: 1, document_cluster: 1 },
            overlayEdgeCount: 2,
            chunkWormholeEdges: 1,
            documentClusterEdges: 1,
            resolverEdges: 0,
            receiptCount: 2,
            reversibleReceiptCount: 2,
            graphPatchCount: 0,
            mutationAllowedCount: 0,
        },
    };
}

function receiptForPersistenceTest(
    id: string,
    scopeId: string,
    policy: 'delta' | 'force',
): GraphIndexRunReceipt {
    const startedAt = Date.now();
    return {
        schemaVersion: 'phoenix-graph-index-run/v1',
        id,
        scope: { kind: 'note', scopeId, label: scopeId, noteIds: [scopeId.replace('note:', '')] },
        policy,
        delta: policy !== 'force',
        status: 'completed',
        modelSelection: request().modelSelection,
        postProcessMode: 'full',
        durabilityMode: 'interactive',
        modelReadiness: [],
        startedAt,
        completedAt: startedAt,
        durationMs: 0,
        stageReceipts: [{
            id: 'buildGraphSnapshot',
            label: 'Build Graph Snapshot',
            status: 'completed',
            startedAt,
            completedAt: startedAt,
            durationMs: 0,
            outputCount: 1,
            counters: { nodes: 1 },
            message: 'snapshot built',
        }],
        projectionReceipts: [],
        layerReceipts: [],
        snapshotId: 'snapshot-1',
        counters: {
            nodes: 1,
            edges: 0,
            chunks: 0,
            acceptedAnchors: 0,
            embeddingTargets: 0,
            graphAwareLinkSuggestions: 0,
            dropReasons: {
                missingEntity: 0,
                invalidSpan: 0,
                duplicateAnchor: 0,
                singletonBucket: 0,
                missingChunk: 0,
            },
        },
        dropReasons: {
            missingEntity: 0,
            invalidSpan: 0,
            duplicateAnchor: 0,
            singletonBucket: 0,
            missingChunk: 0,
        },
        message: 'test receipt',
    };
}

function createGraphRebuildMock() {
    let generationReceipt: any = null;
    return {
        assertBuildPolicyAuthorized: vi.fn(),
        buildAndPersistSnapshot: vi.fn(async (request: { interactiveInputIdentity?: string }) => authorityReadySnapshot({
            id: 'snapshot-1',
            scopeId: 'note:note-1',
            scopeKind: 'note',
            embeddingGraphPostProcess: { schemaVersion: 'phoenix-embedding-graph-postprocess/v1' },
            embeddingTargets: [
                { id: 'embed:entity:entity-kai', kind: 'entity', sourceId: 'entity-kai', label: 'Kai', text: 'Kai', evidenceIds: [] },
                { id: 'embed:graph-fact:1', kind: 'graphFact', sourceId: 'rel-1', label: 'Kai supports Hazel', text: 'fact', evidenceIds: [] },
                { id: 'embed:event:1', kind: 'event', sourceId: 'event-1', label: 'Event', text: 'event', evidenceIds: [] },
            ],
            semanticAdjudicationSummary: {
                schemaVersion: 'phoenix-semantic-adjudication-dag/v1',
                generatedAt: 1,
                sourceSnapshotId: 'snapshot-1',
                states: ['proposed', 'supported', 'accepted', 'deferred', 'rejected', 'invalidated', 'superseded'],
                dagEdges: [],
                decisions: [],
                mutations: [],
                receipts: [],
                counters: {
                    byState: { deferred: 1 },
                    byCandidateKind: {},
                    decisionCount: 1,
                    mutationCount: 0,
                    appliedMutationCount: 0,
                    ledgerOnlyCount: 1,
                    receiptCount: 1,
                    reversibleReceiptCount: 1,
                    topologyCommitCount: 0,
                },
            },
            semanticEvalLedgerSummary: {
                schemaVersion: 'phoenix-semantic-eval-ledger/v1',
                generatedAt: 1,
                sourceSnapshotId: 'snapshot-1',
                datasetPurpose: ['classifier_training', 'reranker_eval', 'router_tuning', 'model_swap_regression'],
                entries: [],
                compactExport: { scopeId: 'note:note-1', builtAt: 1, rowCount: 1, rows: [] },
                counters: {
                    rowCount: 1,
                    byLabel: { ambiguous_case: 1 },
                    byCandidateKind: {},
                    acceptedCandidates: 0,
                    rejectedCandidates: 0,
                    ambiguousCases: 1,
                    userCorrections: 0,
                    modelDisagreements: 0,
                    manifoldDisagreements: 0,
                    graphChangeRows: 0,
                },
            },
            memoryGraphRagBridgeSummary: memoryGraphRagBridgeSummary(),
            discourseSpineSummary: discourseSpineSummary(),
            discourseBridgeCandidateSummary: discourseBridgeCandidateSummary(),
            discourseBridgeAdjudicationSummary: discourseBridgeAdjudicationSummary(),
            discourseEvalLedgerSummary: discourseEvalLedgerSummary(),
            discoursePromotionSurfaceSummary: discoursePromotionSurfaceSummary(),
            discourseCompilerOverlaySummary: discourseCompilerOverlaySummary(),
            calendarRegistrySummary: calendarRegistryBridgeSummary(),
            counters: {
                nodes: 2,
                edges: 1,
                chunks: 1,
                acceptedAnchors: 2,
                memoryGraphRagRecords: 3,
                memoryGraphRagEvalRows: 2,
                memoryGraphRagMutationAllowed: 0,
                discourseSpineTargets: 3,
                discourseSpineBridges: 2,
                discourseSpineMutationAllowed: 0,
                discourseBridgeCandidates: 2,
                discourseBridgeEvalRows: 2,
                discourseBridgeMutationAllowed: 0,
                discourseBridgeAdjudicationDecisions: 2,
                discourseBridgeAdjudicationLedgerOnly: 2,
                discourseBridgeAdjudicationTopologyCommits: 0,
                discourseBridgeAdjudicationMutationAllowed: 0,
                discourseEvalLedgerRows: 2,
                discourseEvalAcceptedCandidates: 1,
                discourseEvalAmbiguousCases: 1,
                discourseEvalGraphChangeRows: 0,
                discoursePromotionChunkWormholes: 1,
                discoursePromotionDocumentClusters: 1,
                discoursePromotionCompilerHints: 2,
                discoursePromotionGraphPatches: 0,
                discoursePromotionMutationAllowed: 0,
                discourseCompilerOverlayEdges: 2,
                discourseCompilerOverlayChunkWormholes: 1,
                discourseCompilerOverlayDocumentClusters: 1,
                discourseCompilerOverlayGraphPatches: 0,
                discourseCompilerOverlayMutationAllowed: 0,
                calendarRegistryAnchors: 1,
                calendarRegistryReceipts: 1,
                calendarRegistryMutationAllowed: 0,
                embeddingTargets: 3,
                embeddingVectors: 3,
                graphAwareLinkSuggestions: 2,
                dropReasons: {
                    missingEntity: 0,
                    invalidSpan: 0,
                    duplicateAnchor: 0,
                    singletonBucket: 0,
                    missingChunk: 0,
                },
            },
            buildTimings: {
                occurrenceLoadMs: 3,
                chunkLoadMs: 4,
                noteTextLoadMs: 5,
                dbLoadMs: 12,
                occurrenceRecoverMs: 2,
                snapshotBuildMs: 8,
                stateCommitMs: 1,
                snapshotPersistMs: 6,
                snapshotSerializeMs: 2,
                snapshotStoreMs: 4,
                snapshotEventMs: 0,
                snapshotPayloadChars: 1200,
                dbOpsMs: 18,
                totalMs: 27,
            },
            interactiveRunAuthority: request.interactiveInputIdentity ? {
                schemaVersion: 'phoenix-interactive-graph-run-authority/v1',
                inputIdentity: request.interactiveInputIdentity,
                snapshotId: 'snapshot-1',
                scopeId: 'note:note-1',
                durable: nativeDurableReuseReceipt(),
            } : undefined,
        })),
        snapshot: vi.fn(() => null as GraphRebuildSnapshot | null),
        loadPersistedSnapshot: vi.fn(async () => null),
        loadPersistedSnapshotShell: vi.fn(async () => null),
        loadVerifiedGenerationSnapshotContent: vi.fn(async (snapshot: GraphRebuildSnapshot) => snapshot),
        loadPersistedGenerationReceipt: vi.fn(async () => generationReceipt),
        persistGenerationReceipt: vi.fn(async (receipt: any) => {
            generationReceipt = receipt;
        }),
        persistForceV2Authority: vi.fn(async () => ({
            schemaVersion: 'phoenix-force-v2-authority-persist/v1',
            artifactId: 'b3-force-authority',
            rawBytes: 24_000,
            compressedBytes: 8_000,
            encoded: true,
            serializerMicros: 500,
            atomicPersistMicros: 2_000,
        })),
        verifyForceV2FromAuthority: vi.fn(async () => {
            throw new Error('verified FORCE v2 test seed is missing');
        }),
        prepareAssertedQueryArtifact: vi.fn(async () => ({
            schemaVersion: 'phoenix-graph-generation-artifact-ref/v1' as const,
            kind: 'asserted-query' as const,
            status: 'ready' as const,
            id: 'asserted-query:snapshot-1',
            digest: `sha256-${'b'.repeat(64)}`,
            schema: 'phoenix-discovery-view/v1',
            byteLength: 1024,
        })),
        loadPersistedRunReceipt: vi.fn(async () => null),
        loadPostProcessCache: vi.fn(async () => null),
        persistRunReceipt: vi.fn(async () => receiptStoreTiming()),
        persistPostProcessCache: vi.fn(async () => undefined),
        restorePersistedSnapshot: vi.fn(async () => undefined),
        persistResidentNativeGraphRun: vi.fn(async () => null as ReturnType<typeof nativeDurableReuseReceipt> | null),
        restorePersistedNativeGraphRun: vi.fn(async () => null as ReturnType<typeof nativeDurableReuseReceipt> | null),
    };
}

function nativeDurableReuseReceipt() {
    return {
        schemaVersion: 'phoenix-graph-run-durable-receipt/v1' as const,
        runHandle: 'graph-run:test',
        scopeId: 'note:note-1',
        snapshotId: 'snapshot-1',
        manifestId: 'manifest:test',
        changedSections: 0,
        reusedSections: 7,
        encodedSections: 0,
        compressedSections: 0,
        rawBytesWritten: 0,
        compressedBytesWritten: 0,
    };
}

function receiptStoreTiming() {
    return {
        records: 1,
        noteMutations: 0,
        relationUpserts: 1,
        relationDeletes: 0,
        scopedDocumentUpserts: 1,
        payloadChars: 4096,
        serializedWaitMs: 2,
        appendWalMs: 3,
        manifestCommitMs: 1,
        runtimeApplyMs: 4,
        runtimeReloadMs: 0,
        totalMs: 10,
        checkpointScheduled: 1,
        runtimeReloaded: 0,
    };
}

function deferred<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise;
        reject = rejectPromise;
    });
    return { promise, resolve, reject };
}

async function flushReceiptPersistence(service: GraphRebuildPipelineService): Promise<void> {
    const queue = (service as any)?.receiptPersistenceQueue as Promise<void> | undefined;
    await queue;
}

async function flushPostCommitDiagnostics(service: GraphRebuildPipelineService): Promise<void> {
    const queue = (service as any)?.postCommitDiagnosticQueue as Promise<void> | undefined;
    await queue;
    const generationQueue = (service as any)?.generationArtifactQueue as Promise<void> | undefined;
    await generationQueue;
}

async function waitForReceiptPersistenceStart(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await Promise.resolve();
}

type ScheduledCallback = {
    id: number;
    callback: () => void;
    cancelled: boolean;
    ran: boolean;
};

function scheduledCallback(rows: ScheduledCallback[], callback: () => void): ScheduledCallback {
    const row = {
        id: rows.length + 1,
        callback,
        cancelled: false,
        ran: false,
    };
    rows.push(row);
    return row;
}

function runScheduledCallbacks(rows: ScheduledCallback[]): void {
    for (const row of rows) {
        if (row.cancelled || row.ran) continue;
        row.ran = true;
        row.callback();
    }
}

function authorityReadySnapshot(input: Partial<GraphRebuildSnapshot>): GraphRebuildSnapshot {
    const targets = input.embeddingTargets || [];
    const snapshot = {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: input.id || 'snapshot-1',
        source: 'phoenix-graph-rebuild',
        scopeKind: input.scopeKind || 'note',
        scopeId: input.scopeId || 'note:note-1',
        noteIds: ['note-1'],
        builtAt: 1,
        chunks: [{ id: 'chunk-1', noteId: 'note-1', start: 0, end: 20, ordinal: 0, source: 'dynamic-chunking' }],
        mentions: [
            { id: 'mention-1', noteId: 'note-1', surface: 'Kai', sourceStart: 0, sourceEnd: 3, source: 'dynamic-ner', confidence: 1, entityId: 'entity-kai', status: 'accepted' },
            { id: 'mention-2', noteId: 'note-1', surface: 'Hazel', sourceStart: 8, sourceEnd: 13, source: 'dynamic-ner', confidence: 1, entityId: 'entity-hazel', status: 'accepted' },
        ],
        entityAnchors: [
            { id: 'anchor-1', noteId: 'note-1', surface: 'Kai', sourceStart: 0, sourceEnd: 3, source: 'dynamic-ner', confidence: 1, entityId: 'entity-kai', status: 'accepted', generation: 1 },
            { id: 'anchor-2', noteId: 'note-1', surface: 'Hazel', sourceStart: 8, sourceEnd: 13, source: 'dynamic-ner', confidence: 1, entityId: 'entity-hazel', status: 'accepted', generation: 1 },
        ],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: targets,
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [
            { id: 'entity-kai', entityId: 'entity-kai', label: 'Kai', kind: 'CHARACTER', aliases: [], anchorIds: ['anchor-1'], noteIds: ['note-1'], totalMentions: 1 },
            { id: 'entity-hazel', entityId: 'entity-hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], anchorIds: ['anchor-2'], noteIds: ['note-1'], totalMentions: 1 },
        ],
        edges: [{ id: 'edge-1', sourceId: 'entity-kai', targetId: 'entity-hazel', type: 'semantic-related', weight: 1, confidence: 0.9, evidenceAnchorIds: ['anchor-1', 'anchor-2'], scopeKeys: ['note:note-1'], noteIds: ['note-1'] }],
        ...input,
        counters: {
            mentions: 2,
            relationships: 0,
            events: 0,
            temporalEdges: 0,
            causalEdges: 0,
            memoryState: 0,
            ...input.counters,
        },
    } as GraphRebuildSnapshot;
    const familyFor = (kind: string) => kind === 'entity' ? 'registry' as const : 'fact' as const;
    const objects = targets.map((target) => ({
        id: `atlas:${target.id}`,
        family: familyFor(target.kind),
        status: 'accepted' as const,
        kind: target.kind,
        label: target.label,
        noteIds: target.noteId ? [target.noteId] : [],
        chunkIds: target.chunkId ? [target.chunkId] : [],
        anchorIds: [],
        evidenceIds: target.evidenceIds,
        sourceIds: [target.sourceId],
        targetIds: [],
    }));
    snapshot.atlasPacket = {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: snapshot.id,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        sourceContract: {
            authority: GRAPH_ATLAS_PACKET_AUTHORITY,
            identityAuthority: GRAPH_ATLAS_IDENTITY_AUTHORITY,
            vectorContract: 'vectors-missing',
            tsGraphBuilderRole: GRAPH_ATLAS_BUILDER_ROLE,
        },
        objects,
        manifoldTargets: targets.map((target) => ({
            id: target.id,
            objectId: `atlas:${target.id}`,
            family: familyFor(target.kind),
            admission: 'admitted',
            vectorStatus: 'missing',
            coordinateSource: 'none',
            status: 'accepted',
            kind: target.kind,
            label: target.label,
            sourceId: target.sourceId,
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds,
        })),
        counters: {
            objects: objects.length,
            manifoldTargets: targets.length,
            registryEntities: snapshot.nodes.length,
            evidenceAnchors: snapshot.entityAnchors.length,
            modelVectors: 0,
            families: [
                { family: 'registry', count: objects.filter((object) => object.family === 'registry').length },
                { family: 'fact', count: objects.filter((object) => object.family === 'fact').length },
            ].filter((row) => row.count > 0),
        },
    };
    sealGraphSnapshotAuthority(snapshot);
    snapshot.contentManifest = {
        schemaVersion: 'phoenix-graph-rebuild-content-manifest/v1',
        snapshotId: snapshot.id,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        refs: {},
    };
    return snapshot;
}

function createPhoenixStoreMock() {
    return {
        pauseSnapshots: vi.fn(),
        resumeSnapshots: vi.fn(),
    };
}

function createPhoenixUiApiMock() {
    return {
        loadStagedGraphScenePacket: vi.fn(async () => ({
            version: 'graph-scene-packet/v1' as const,
            source: 'manifoldSnapshot',
            sourceLabel: 'Spec packet',
            manifold: 'siegel',
            layoutMode: 'siegelFinsler' as const,
            sourceMode: 'embeddings' as const,
            counters: {
                inputNodes: 3,
                inputEdges: 0,
                renderedNodes: 3,
                renderedEdges: 0,
                droppedEdges: 0,
                bufferBytes: 132,
            },
            ids: ['embed:entity:entity-kai', 'embed:graph-fact:1', 'embed:event:1'],
            labels: ['Kai', 'Kai supports Hazel', 'Event'],
            kinds: ['entity', 'graphFact', 'event'],
            groupIds: ['entity', 'graphFact', 'event'],
            positions3d: encodeF32([0, 0, 0, 1, 1, 1, 2, 2, 2]),
            positions2d: encodeF32([0, 0, 0, 1, 1, 0, 2, 2, 0]),
            radii: encodeF32([1, 0.8, 0.6]),
            colors: encodeF32([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]),
            edgeIds: [],
            edgePairs: encodeU32([]),
            edgeColors: encodeF32([]),
            edgeAlpha: encodeF32([]),
            edgeKinds: encodeU8([]),
            hierarchyShellRadii: encodeF32([3, 2, 1]),
            hierarchyShellRanks: encodeU8([0, 1, 2]),
            hierarchyHints: [
                hierarchyHint('embed:entity:entity-kai', 'identity:entity-kai', 'embed:structure-root:note-1:identity', 3),
                hierarchyHint('embed:graph-fact:1', 'document:note-1:chunk:note-1:0:facts:relationship', 'embed:chunk:note-1:0', 5),
                hierarchyHint('embed:event:1', 'event:1', 'embed:chunk:note-1:0', 4),
            ],
        })),
    };
}

function hierarchyHint(nodeId: string, capId: string, parentNodeId: string, level: number) {
    return {
        nodeId,
        primaryTreeId: capId.split(':').slice(0, 2).join(':'),
        capId,
        parentNodeId,
        shellRadius: 1,
        hierarchyLevel: level,
        role: 'test',
        confidence: 0.94,
        memberships: [
            {
                treeId: capId.split(':').slice(0, 2).join(':'),
                nodeId,
                parentNodeId,
                depth: level,
                localRank: level,
                pathKey: `${capId}/${parentNodeId}/${nodeId}`,
                role: 'test',
                confidence: 0.94,
                primary: true,
            },
        ],
    };
}

function encodeF32(values: number[]): string {
    const bytes = new Uint8Array(values.length * 4);
    const view = new DataView(bytes.buffer);
    values.forEach((value, index) => view.setFloat32(index * 4, value, true));
    return encodeBytes(bytes);
}

function encodeU32(values: number[]): string {
    const bytes = new Uint8Array(values.length * 4);
    const view = new DataView(bytes.buffer);
    values.forEach((value, index) => view.setUint32(index * 4, value, true));
    return encodeBytes(bytes);
}

function encodeU8(values: number[]): string {
    return encodeBytes(Uint8Array.from(values));
}

function encodeBytes(bytes: Uint8Array): string {
    let binary = '';
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
}

function createAtlasRuntimeMock() {
    return {
        capabilityState: vi.fn((capability: string) => ({
            requiredModels: [{
                id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                readiness: 'ready',
                statusLabel: 'ready',
            }],
        })),
        warmModelLane: vi.fn(async () => undefined),
        runCapability: vi.fn(async (capability: string) => ({
            rawResult: capability === 'semanticAtlas'
                ? {
                    startedAt: 1000,
                    completedAt: 2000,
                    durationMs: 1000,
                    candidateSuggestions: 2,
                    exportableMentions: 2,
                    nativeResult: {
                        processedDocuments: 1,
                        relationCandidateCount: 3,
                        embeddingCounts: { leafVectors: 7 },
                    },
                }
                : capability === 'assertedKernel'
                ? {
                    candidateSuggestions: 3,
                    indexedDocuments: 1,
                    nativeResult: {
                        processedDocuments: 1,
                        stageSummaries: [{
                            stage: 'dynamicSurface',
                            status: 'completed',
                            durationMs: 42,
                            counts: {
                                documents: 1,
                                mentions: 12,
                                candidateSuggestions: 3,
                            },
                        }],
                        graphDeltaCounts: { nodes: 4, edges: 5 },
                    },
                }
                : capability === 'nliAdjudication'
                ? {
                    inputCount: 2,
                    plannedInputCount: 1,
                    duplicateInputCount: 1,
                    resultCount: 2,
                    stageSummaries: [
                        {
                            stage: 'candidatePlan',
                            status: 'completed',
                            durationMs: 4,
                            counts: {
                                rawInputs: 2,
                                validInputs: 2,
                                plannedInputs: 1,
                                duplicateInputs: 1,
                                uniquePairs: 1,
                            },
                        },
                        {
                            stage: 'classification',
                            status: 'completed',
                            durationMs: 9,
                            counts: {
                                plannedInputs: 1,
                                results: 1,
                                batches: 1,
                                entailment: 1,
                                neutral: 0,
                                contradiction: 0,
                            },
                        },
                        {
                            stage: 'apply',
                            status: 'completed',
                            durationMs: 3,
                            counts: {
                                results: 1,
                                appliedRows: 1,
                            },
                        },
                    ],
                    judgments: [{
                        judgmentId: 'j-1',
                        sourceId: 'entity-kai',
                        targetId: 'entity-hazel',
                        edgeType: 'supports',
                        predictedLabel: 'contradiction',
                        nliVote: {
                            source: 'modernBertNli',
                            role: 'canonFactAdjudication',
                            decision: 'supported',
                            confidenceMillis: 930,
                            entailmentMillis: 930,
                            contradictionMillis: 20,
                            neutralMillis: 50,
                        },
                        classificationVote: {
                            source: 'gliclass',
                            role: 'relationFrameClassification',
                            label: 'supports',
                            scoreMillis: 870,
                        },
                    }],
                }
                : { payload: { nodes: [1, 2], edges: [1] } },
        })),
    };
}

function createNerMock() {
    const suggestions = signal([
        { id: 's1', label: 'Kai', kind: 'CHARACTER', confidence: 0.9, source: 'dynamic_ner' },
        { id: 's2', label: 'Hazel', kind: 'CHARACTER', confidence: 0.9, source: 'dynamic_ner' },
    ]);
    return {
        suggestions: computed(() => suggestions()),
        runDynamicScan: vi.fn(async () => undefined),
        scanDynamicBatch: vi.fn(async (requests: any[]) => requests.map(() => [])),
        applyDynamicScanResult: vi.fn(async () => undefined),
        acceptSuggestionForContext: vi.fn(async (id: string) => {
            const suggestion = suggestions().find((row) => row.id === id);
            suggestions.set(suggestions().filter((suggestion) => suggestion.id !== id));
            return suggestion ? acceptedOccurrence(suggestion.label) : null;
        }),
    };
}

function acceptedOccurrence(label: string) {
    const key = label.toLowerCase();
    const start = label === 'Hazel' ? 8 : 0;
    return {
        id: `note-1:entity-${key}:${start}:${start + label.length}:machine_suggestion`,
        noteId: 'note-1',
        entityId: `entity-${key}`,
        entityLabel: label,
        entityKind: 'CHARACTER',
        sourceStart: start,
        sourceEnd: start + label.length,
        surface: label,
        source: 'machine_suggestion',
        confidence: 0.9,
        excerpt: label,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}
