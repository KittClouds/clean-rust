import '@angular/compiler';
import { Injector, computed, createEnvironmentInjector, runInInjectionContext, signal, type EnvironmentInjector } from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const notesMock = vi.hoisted(() => ({
    rows: [] as any[],
    bulkGet: vi.fn(async (ids: string[]) => ids.map((id) => notesMock.rows.find((row) => row.id === id))),
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
import type { GraphIndexRunRequest } from './graph-rebuild-snapshot';
import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
import type { GraphCalendarRegistryBridgeSummary } from './graph-calendar-registry-bridge';

describe('GraphRebuildPipelineService', () => {
    let injector: EnvironmentInjector;
    let graphRebuild: ReturnType<typeof createGraphRebuildMock>;
    let atlasRuntime: ReturnType<typeof createAtlasRuntimeMock>;
    let ner: ReturnType<typeof createNerMock>;
    let service: GraphRebuildPipelineService;

    beforeEach(() => {
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
        injector = createEnvironmentInjector([
            { provide: GraphRebuildService, useValue: graphRebuild },
            { provide: AtlasCapabilityRuntimeService, useValue: atlasRuntime },
            { provide: NerService, useValue: ner },
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        service = runInInjectionContext(injector, () => new GraphRebuildPipelineService());
    });

    afterEach(() => {
        injector.destroy();
        vi.clearAllMocks();
    });

    it('blocks a full atlas build while required models are cold', async () => {
        atlasRuntime.capabilityState.mockImplementation((capability: string) => ({
            requiredModels: [{
                id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                readiness: capability === 'dynamicNer' ? 'ready' : 'idle',
                statusLabel: 'idle',
            }],
        }));

        await expect(service.buildFullAtlas(request())).rejects.toThrow('Load models first');

        expect(ner.runDynamicScan).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).not.toHaveBeenCalled();
    });

    it('builds the clean graph stage with only Dynamic NER warm', async () => {
        atlasRuntime.capabilityState.mockImplementation((capability: string) => ({
            requiredModels: [{
                id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                readiness: capability === 'dynamicNer' ? 'ready' : 'idle',
                statusLabel: capability === 'dynamicNer' ? 'ready' : 'idle',
            }],
        }));

        await service.buildCoreGraph(request());

        expect(ner.runDynamicScan).toHaveBeenCalledTimes(1);
        expect(atlasRuntime.runCapability).not.toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            postProcessMode: 'core',
        }));
        expect(graphRebuild.persistRunReceipt).toHaveBeenCalledWith(expect.objectContaining({
            postProcessMode: 'core',
            projectionReceipts: [],
            message: expect.stringContaining('Clean graph built'),
            stageReceipts: expect.arrayContaining([
                expect.objectContaining({
                    id: 'deltaPostprocessPlan',
                    label: 'Delta Postprocess Plan',
                    counters: expect.objectContaining({
                        targetReplanDirty: 1,
                    }),
                }),
                expect.objectContaining({
                    id: 'signalCandidatePlan',
                    label: 'Signal Candidate Plan',
                    counters: expect.objectContaining({
                        discoveryCandidates: 2,
                        exportableMentions: 2,
                    }),
                }),
                expect.objectContaining({
                    id: 'signalTargetCoverage',
                    label: 'Signal Target Coverage',
                    counters: expect.objectContaining({
                        targets: 3,
                        entityTargets: 1,
                        graphFactTargets: 1,
                        eventTargets: 1,
                    }),
                }),
                expect.objectContaining({
                    id: 'graphTruthContract',
                    label: 'Graph Truth Contract',
                    counters: expect.objectContaining({
                        graphTruthTotal: 3,
                    }),
                }),
                expect.objectContaining({
                    id: 'entityLinkerPlan',
                    label: 'Entity Linker Plan',
                    counters: expect.objectContaining({
                        narrowRetrieverReady: 1,
                        modelRunnerReady: 0,
                    }),
                }),
                expect.objectContaining({
                    id: 'edgeTypeJudgmentPlan',
                    label: 'Edge Type Judgment Plan',
                }),
                expect.objectContaining({
                    id: 'semanticAdjudicationDag',
                    label: 'Semantic Adjudication DAG',
                }),
                expect.objectContaining({
                    id: 'semanticEvalLedger',
                    label: 'Semantic Eval Ledger',
                }),
            ]),
        }));
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

        await service.buildCoreGraph({
            ...request(),
            scope: { kind: 'global', scopeId: 'global', label: 'Global', noteIds: [] },
            policy: 'force',
        });

        expect(notesMock.toArray).toHaveBeenCalled();
        expect(ner.runDynamicScan).toHaveBeenCalledTimes(2);
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

        await service.buildCoreGraph({
            ...request(),
            scope: {
                kind: 'multiNote',
                scopeId: 'multi:note-1|deleted-note|note-2',
                label: '3 notes',
                noteIds: ['note-1', 'deleted-note', 'note-2'],
            },
            policy: 'force',
        });

        expect(notesMock.bulkGet).toHaveBeenCalledWith(['note-1', 'deleted-note', 'note-2']);
        expect(ner.runDynamicScan).toHaveBeenCalledTimes(2);
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

    it('runs full atlas stages, then builds the final snapshot from NLI hints', async () => {
        await service.buildFullAtlas(request());

        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            noteId: 'note-1',
            plainText: expect.stringContaining('Kai met Hazel'),
        }));
        expect(ner.acceptSuggestionForContext).toHaveBeenCalledTimes(2);
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            scopeKind: 'note',
            scopeId: 'note:note-1',
            noteIds: ['note-1'],
            candidateCount: 2,
            calendarRegistrySnapshot: expect.objectContaining({ id: 'calendar-registry:test' }),
            relationshipHints: [expect.objectContaining({
                sourceId: 'entity-kai',
                targetId: 'entity-hazel',
                status: 'accepted',
            })],
        }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('semanticAtlas', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('nliAdjudication', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('relationGraph', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('temporalGraph', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('eventIdentity', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('memoryState', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('causalGraph', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('hybridManifold', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('hopfProjection', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('lorentzForest', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('productManifold', expect.objectContaining({ skipModelWarm: true }));
        expect(graphRebuild.persistRunReceipt).toHaveBeenCalledWith(expect.objectContaining({
            status: 'completed',
            snapshotId: 'snapshot-1',
            counters: expect.objectContaining({ nodes: 2, edges: 1 }),
            postProcessMode: 'full',
            postProcessFingerprint: expect.any(String),
            projectionReceipts: expect.arrayContaining([
                expect.objectContaining({ mode: 'hybrid', status: 'synced' }),
                expect.objectContaining({ mode: 'hopf', status: 'synced' }),
                expect.objectContaining({ mode: 'lorentz', status: 'synced' }),
                expect.objectContaining({ mode: 'product', status: 'synced' }),
            ]),
        }));
        const receipt = graphRebuild.persistRunReceipt.mock.calls[0][0];
        const semanticStage = receipt.stageReceipts.find((stage: any) => stage.id === 'semanticAtlas');
        expect(semanticStage).toEqual(expect.objectContaining({
            outputCount: 15,
            counters: expect.objectContaining({
                startedAt: 1000,
                completedAt: 2000,
                candidateSuggestions: 2,
                'nativeResult.embeddingCounts.leafVectors': 7,
            }),
        }));
        expect(receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'calendarRegistryBridge',
                label: 'Calendar Registry Bridge',
                counters: expect.objectContaining({
                    anchors: 1,
                    receipts: 1,
                    acceptedTemporalReceipts: 1,
                    mutationAllowed: 0,
                }),
            }),
        ]));
        expect(service.lastSnapshot()?.id).toBe('snapshot-1');
    });

    it('uses projection-only orchestration when the scope and adapter fingerprint match', async () => {
        const first = await service.postProcessAtlas(request());
        expect(graphRebuild.persistPostProcessCache).not.toHaveBeenCalled();
        graphRebuild.loadPostProcessCache.mockResolvedValue(null);
        graphRebuild.loadPersistedRunReceipt.mockResolvedValue(first.receipt);
        graphRebuild.loadPersistedSnapshot.mockResolvedValue(first.snapshot);
        atlasRuntime.runCapability.mockClear();

        const second = await service.postProcessAtlas(request());

        expect(atlasRuntime.runCapability).toHaveBeenCalledTimes(4);
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('hybridManifold', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('hopfProjection', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('lorentzForest', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('productManifold', expect.objectContaining({ skipModelWarm: true }));
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('nliAdjudication', expect.anything());
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledTimes(1);
        expect(graphRebuild.restorePersistedSnapshot).toHaveBeenCalledWith(first.snapshot);
        expect(second.receipt.postProcessCacheHit).toBe(true);
        expect(second.receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'deltaPostprocessPlan',
                counters: expect.objectContaining({
                    projectionOnlyRoute: 1,
                    targetReplanDirty: 0,
                }),
            }),
            expect.objectContaining({
                id: 'postProcessCache',
                status: 'completed',
                counters: expect.objectContaining({
                    projectionOnly: 1,
                    targetReplanSkipped: 1,
                }),
            }),
            expect.objectContaining({ id: 'uiCommit', status: 'completed' }),
        ]));
        expect(second.receipt.projectionReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({ mode: 'hybrid', status: 'synced' }),
            expect.objectContaining({ mode: 'hopf', status: 'synced' }),
            expect.objectContaining({ mode: 'lorentz', status: 'synced' }),
            expect.objectContaining({ mode: 'product', status: 'synced' }),
        ]));
    });

    it('skips entity discovery during force postprocess when docs are unchanged', async () => {
        const first = await service.postProcessAtlas(request());
        graphRebuild.loadPostProcessCache.mockResolvedValue(null);
        graphRebuild.loadPersistedRunReceipt.mockResolvedValue(first.receipt);
        graphRebuild.loadPersistedSnapshot.mockResolvedValue(first.snapshot);
        atlasRuntime.runCapability.mockClear();
        graphRebuild.buildAndPersistSnapshot.mockClear();

        const second = await service.postProcessAtlas({
            ...request(),
            policy: 'force',
        });

        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('assertedKernel', expect.anything());
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('nliAdjudication', expect.objectContaining({
            buildPolicy: 'dirty-only',
            skipModelWarm: true,
        }));
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledTimes(1);
        expect(second.receipt.postProcessCacheHit).toBe(false);
        expect(second.receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'postProcessDiscovery',
                status: 'skipped',
                counters: expect.objectContaining({ postprocessDiscoverySkipped: 1 }),
            }),
        ]));
    });

    it('force postprocess carries cached anchors into the rebuilt snapshot', async () => {
        const first = await service.postProcessAtlas(request());
        Object.assign(first.snapshot, {
            nodes: [
                { entityId: 'entity-kai', label: 'Kai', kind: 'CHARACTER' },
                { entityId: 'entity-hazel', label: 'Hazel', kind: 'CHARACTER' },
            ],
            entityAnchors: [
                {
                    id: 'anchor:kai',
                    noteId: 'note-1',
                    entityId: 'entity-kai',
                    surface: 'Kai',
                    sourceStart: 0,
                    sourceEnd: 3,
                    source: 'machine_suggestion',
                    confidence: 0.9,
                    status: 'accepted',
                    generation: 2,
                },
                {
                    id: 'anchor:hazel',
                    noteId: 'note-1',
                    entityId: 'entity-hazel',
                    surface: 'Hazel',
                    sourceStart: 8,
                    sourceEnd: 13,
                    source: 'machine_suggestion',
                    confidence: 0.88,
                    status: 'accepted',
                    generation: 2,
                },
            ],
        });
        graphRebuild.loadPostProcessCache.mockResolvedValue(null);
        graphRebuild.loadPersistedRunReceipt.mockResolvedValue(first.receipt);
        graphRebuild.loadPersistedSnapshot.mockResolvedValue(first.snapshot);
        graphRebuild.buildAndPersistSnapshot.mockClear();

        await service.postProcessAtlas({
            ...request(),
            policy: 'force',
        });

        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            postProcessMode: 'full',
            fallbackOccurrences: expect.arrayContaining([
                expect.objectContaining({ entityId: 'entity-kai', surface: 'Kai' }),
                expect.objectContaining({ entityId: 'entity-hazel', surface: 'Hazel' }),
            ]),
        }));
    });

    it('keeps postprocess entity discovery disabled when only accepted entities change', async () => {
        const first = await service.postProcessAtlas(request());
        registryMock.entities = [
            ...registryMock.entities,
            { id: 'entity-red-mesa', label: 'Red Mesa', aliases: [], kind: 'LOCATION' },
        ];
        graphRebuild.loadPostProcessCache.mockResolvedValue(null);
        graphRebuild.loadPersistedRunReceipt.mockResolvedValue(first.receipt);
        graphRebuild.loadPersistedSnapshot.mockResolvedValue(first.snapshot);
        atlasRuntime.runCapability.mockClear();

        const second = await service.postProcessAtlas({
            ...request(),
            policy: 'force',
        });

        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('assertedKernel', expect.anything());
        expect(second.receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'postProcessDiscovery',
                status: 'skipped',
                counters: expect.objectContaining({ postprocessDiscoverySkipped: 1 }),
            }),
        ]));
    });

    it('force postprocess does not invoke Semantic Atlas', async () => {
        const result = await service.postProcessAtlas({
            ...request(),
            policy: 'force',
        });

        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('semanticAtlas', expect.anything());
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('hybridManifold', expect.anything());
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('hopfProjection', expect.anything());
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('lorentzForest', expect.anything());
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('productManifold', expect.anything());
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('assertedKernel', expect.anything());
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('nliAdjudication', expect.objectContaining({ skipModelWarm: true }));
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            postProcessMode: 'full',
        }));
        expect(result.receipt.stageReceipts.some((stage) => stage.id === 'semanticAtlas')).toBe(false);
        expect(result.receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({ id: 'postProcessDiscovery', label: 'Entity Discovery' }),
            expect.objectContaining({
                id: 'nliCandidatePlan',
                label: 'NLI Candidate Plan',
                counters: expect.objectContaining({
                    rawInputs: 2,
                    plannedInputs: 1,
                    duplicateInputs: 1,
                }),
            }),
            expect.objectContaining({
                id: 'nliClassification',
                label: 'NLI Classification',
                counters: expect.objectContaining({
                    plannedInputs: 1,
                    results: 1,
                }),
            }),
            expect.objectContaining({
                id: 'nliApply',
                label: 'NLI Apply',
                counters: expect.objectContaining({
                    appliedRows: 1,
                }),
            }),
            expect.objectContaining({
                id: 'signalCandidatePlan',
                label: 'Signal Candidate Plan',
                counters: expect.objectContaining({
                    documents: 1,
                    discoverySkipped: 1,
                    discoveryCandidates: 0,
                    plannedModelCalls: 0,
                }),
            }),
            expect.objectContaining({
                id: 'signalTargetCoverage',
                label: 'Signal Target Coverage',
                counters: expect.objectContaining({
                    targets: 3,
                    candidateTargets: 3,
                    deferredTargets: 0,
                    entityTargets: 1,
                    graphFactTargets: 1,
                    eventTargets: 1,
                    causalFactTargets: 0,
                }),
            }),
            expect.objectContaining({
                id: 'graphTruthContract',
                label: 'Graph Truth Contract',
            }),
            expect.objectContaining({ id: 'snapshotDbOps', label: 'DB Ops' }),
            expect.objectContaining({ id: 'snapshotCpu', label: 'Snapshot CPU' }),
            expect.objectContaining({ id: 'uiCommit', label: 'UI Commit' }),
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
            expect.objectContaining({ mode: 'hopf', status: 'synced' }),
            expect.objectContaining({ mode: 'lorentz', status: 'synced' }),
            expect.objectContaining({ mode: 'product', status: 'synced' }),
        ]));
    });

    it('postprocess skips entity discovery and Dynamic NER', async () => {
        const result = await service.postProcessAtlas(request());

        expect(ner.runDynamicScan).not.toHaveBeenCalled();
        expect(ner.acceptSuggestionForContext).not.toHaveBeenCalled();
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('assertedKernel', expect.anything());
        expect(result.receipt.stageReceipts).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'postProcessDiscovery',
                label: 'Entity Discovery',
                status: 'skipped',
                counters: expect.objectContaining({
                    postprocessDiscoverySkipped: 1,
                    plannedModelCalls: 0,
                }),
            }),
            expect.objectContaining({
                id: 'signalCandidatePlan',
                counters: expect.objectContaining({
                    discoverySkipped: 1,
                    discoveryCandidates: 0,
                    entities: 2,
                }),
            }),
        ]));
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            postProcessMode: 'full',
            relationshipHints: [expect.objectContaining({
                sourceId: 'entity-kai',
                targetId: 'entity-hazel',
                status: 'accepted',
            })],
        }));
    });

    it('postprocesses global scopes against loaded note ids instead of an empty occurrence fallback', async () => {
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

        await service.postProcessAtlas({
            ...request(),
            scope: { kind: 'global', scopeId: 'global', label: 'Global', noteIds: [] },
            policy: 'force',
        });

        expect(notesMock.toArray).toHaveBeenCalled();
        expect(graphRebuild.buildAndPersistSnapshot).toHaveBeenCalledWith(expect.objectContaining({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
            postProcessMode: 'full',
        }));
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('semanticAtlas', expect.anything());
        expect(atlasRuntime.runCapability).not.toHaveBeenCalledWith('assertedKernel', expect.anything());
        expect(atlasRuntime.runCapability).toHaveBeenCalledWith('nliAdjudication', expect.objectContaining({
            buildPolicy: 'dirty-only',
            noteIds: ['note-1', 'note-2'],
            skipModelWarm: true,
        }));
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

        await service.buildFullAtlas(request());

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
        policy: 'delta',
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

function createGraphRebuildMock() {
    return {
        buildAndPersistSnapshot: vi.fn(async () => ({
            id: 'snapshot-1',
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
            calendarRegistrySummary: calendarRegistryBridgeSummary(),
            counters: {
                nodes: 2,
                edges: 1,
                chunks: 1,
                acceptedAnchors: 2,
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
        })),
        loadPersistedSnapshot: vi.fn(async () => null),
        loadPersistedRunReceipt: vi.fn(async () => null),
        loadPostProcessCache: vi.fn(async () => null),
        persistRunReceipt: vi.fn(async () => undefined),
        persistPostProcessCache: vi.fn(async () => undefined),
        restorePersistedSnapshot: vi.fn(async () => undefined),
    };
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
                        predictedLabel: 'entailment',
                        confidence: 0.93,
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
        acceptSuggestionForContext: vi.fn(async (id: string) => {
            suggestions.set(suggestions().filter((suggestion) => suggestion.id !== id));
            return true;
        }),
    };
}
