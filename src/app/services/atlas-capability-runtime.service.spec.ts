import '@angular/compiler';
import {
    Injector,
    computed,
    createEnvironmentInjector,
    inject,
    runInInjectionContext,
    signal,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const dbNotesMock = vi.hoisted(() => {
    const rows = new Map<string, any>();
    return {
        rows,
        bulkGet: vi.fn(async (ids: string[]) => ids.map((id) => rows.get(id))),
        toArray: vi.fn(async () => Array.from(rows.values())),
        where: vi.fn((field: string) => ({
            equals: vi.fn((value: string) => ({
                toArray: vi.fn(async () => Array.from(rows.values()).filter((row) => row?.[field] === value)),
            })),
        })),
    };
});

vi.mock('../lib/dexie/db', () => ({
    db: {
        notes: {
            bulkGet: dbNotesMock.bulkGet,
            toArray: dbNotesMock.toArray,
            where: dbNotesMock.where,
        },
    },
}));

import { AtlasCapabilityRuntimeService } from './atlas-capability-runtime.service';
import { ATLAS_RICH_SCAN_QUARANTINE_MESSAGE } from './atlas-rich-scan-quarantine';
import { PhoenixMachineControlService } from './phoenix-machine-control.service';
import { NerService } from './ner.service';
import { AtlasScanCoordinatorService } from './atlas-scan-coordinator.service';
import { NliWorkerService } from '../lib/services/nli-worker.service';
import { BlueprintHubService } from '../components/blueprint-hub/blueprint-hub.service';
import { NoteEditorStore } from '../lib/store/note-editor.store';
import { PhoenixUiApiService } from './phoenix-ui-api.service';
import { PhoenixBackendService } from './phoenix-backend.service';
import type { AtlasCapabilityId } from '../components/search-panel/atlas-capability.model';

describe('AtlasCapabilityRuntimeService', () => {
    let injector: EnvironmentInjector;
    let service: AtlasCapabilityRuntimeService;
    let machine: ReturnType<typeof createMachineMock>;
    let ner: ReturnType<typeof createNerMock>;
    let atlasScan: ReturnType<typeof createAtlasScanMock>;
    let nli: ReturnType<typeof createNliMock>;
    let noteStore: ReturnType<typeof createNoteStoreMock>;
    let phoenixUiApi: ReturnType<typeof createPhoenixUiApiMock>;
    let phoenix: ReturnType<typeof createPhoenixBackendMock>;

    beforeEach(() => {
        dbNotesMock.rows.clear();
        dbNotesMock.rows.set('note-2', {
            id: 'note-2',
            title: 'Second Runtime Note',
            content: 'Branna crossed the bridge with Lucien.',
            markdownContent: '',
            folderId: 'folder-1',
        });
        dbNotesMock.rows.set('note-3', {
            id: 'note-3',
            title: 'Third Runtime Note',
            content: 'Calder watched Merrow near the terrace.',
            markdownContent: '',
            folderId: 'folder-1',
        });
        dbNotesMock.bulkGet.mockClear();
        dbNotesMock.toArray.mockClear();
        dbNotesMock.where.mockClear();

        machine = createMachineMock();
        ner = createNerMock();
        atlasScan = createAtlasScanMock();
        nli = createNliMock();
        noteStore = createNoteStoreMock();
        phoenixUiApi = createPhoenixUiApiMock();
        phoenix = createPhoenixBackendMock();

        const parentInjector = Injector.create({ providers: [] }) as unknown as EnvironmentInjector;
        injector = createEnvironmentInjector([
            AtlasCapabilityRuntimeService,
            { provide: PhoenixMachineControlService, useValue: machine },
            { provide: NerService, useValue: ner },
            { provide: AtlasScanCoordinatorService, useValue: atlasScan },
            { provide: NliWorkerService, useValue: nli },
            { provide: BlueprintHubService, useValue: { openPage: vi.fn() } },
            { provide: NoteEditorStore, useValue: noteStore },
            { provide: PhoenixUiApiService, useValue: phoenixUiApi },
            { provide: PhoenixBackendService, useValue: phoenix },
        ], parentInjector);

        service = runInInjectionContext(injector, () => inject(AtlasCapabilityRuntimeService));
    });

    afterEach(() => {
        injector.destroy();
        vi.clearAllMocks();
    });

    it('blocks Text Graph before warming a model or scanning a document', async () => {
        const plan = service.recipePlan('textGraph', {
            buildScope: { mode: 'multiNote', noteIds: ['note-2', 'note-3'] },
            buildPolicy: 'dirty-only',
        });

        expect(plan.runnable).toBe(false);
        expect(plan.blockedReason).toBe(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        await expect(service.runRecipe('textGraph', {
            buildScope: { mode: 'multiNote', noteIds: ['note-2', 'note-3'] },
        })).rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        expect(ner.warmProvider).not.toHaveBeenCalled();
        expect(ner.runDynamicScan).not.toHaveBeenCalled();
        expect(atlasScan.runRichEmbeddingScan).not.toHaveBeenCalled();
        expect(machine.loadSemanticModel).not.toHaveBeenCalled();
        expect(nli.initialize).not.toHaveBeenCalled();
    });

    it('builds one explicit contract for semantic graph handoff', () => {
        const contract = service.buildRecipeContract('semanticGraph', {
            selectedModel: 'mongodb-leaf-mt',
            selectedModelLabel: 'MDBR Leaf MT',
            dimensionLabel: '384d',
            buildScope: { mode: 'folder', folderId: 'folder-1' },
            buildPolicy: 'force',
        });

        expect(contract).toEqual(expect.objectContaining({
            recipeId: 'semanticGraph',
            scope: { mode: 'folder', folderId: 'folder-1' },
            noteIds: [],
            policy: 'force',
            exportableMentionStatuses: ['AcceptedKnown', 'AcceptedNew', 'AliasCandidate'],
            modelLanes: ['dynamicNer', 'semanticEmbedding'],
            embeddingModel: {
                id: 'mongodb-leaf-mt',
                label: 'MDBR Leaf MT',
                dimensionLabel: '384d',
            },
            requiredStages: expect.arrayContaining([
                'dynamicNer',
                'semanticEmbedding',
                'semanticAtlas',
                'semanticCandidate',
                'hybridManifold',
                'hopfProjection',
                'lorentzForest',
                'productManifold',
            ]),
            optionalStages: [],
            expectedOutputs: expect.arrayContaining([
                expect.objectContaining({ key: 'embeddingCounts' }),
                expect.objectContaining({ key: 'relationCandidateCount' }),
                expect.objectContaining({ key: 'manifoldSnapshot.hybrid' }),
                expect.objectContaining({ key: 'manifoldSnapshot.hopf' }),
                expect.objectContaining({ key: 'manifoldSnapshot.lorentz' }),
                expect.objectContaining({ key: 'manifoldSnapshot.product' }),
            ]),
        }));
        expect(contract.operations.map((operation) => operation.kind)).toEqual([
            'warmModel',
            'dynamicNerScan',
            'warmModel',
            'semanticAtlasScan',
            'manifoldSnapshot',
            'manifoldSnapshot',
            'manifoldSnapshot',
            'manifoldSnapshot',
        ]);
        expect(contract.operations.filter((operation) => operation.kind === 'manifoldSnapshot').map((operation) => operation.manifold)).toEqual([
            'hybrid',
            'hopf',
            'lorentz',
            'product',
        ]);
        expect(contract.bridgeCommands).toEqual(expect.arrayContaining([
            expect.objectContaining({
                stageId: 'dynamicNer',
                backendCommand: 'scanDiscovery',
            }),
            expect.objectContaining({
                stageId: 'semanticEmbedding',
                frontendService: 'PhoenixMachineControlService.loadSemanticModel',
                backendCommand: 'none',
                backendRoute: expect.stringContaining('model only'),
            }),
            expect.objectContaining({
                stageId: 'semanticAtlas',
                frontendService: 'none',
                backendCommand: 'none',
                backendRoute: expect.stringContaining('QUARANTINED:'),
            }),
            expect.objectContaining({
                stageId: 'hybridManifold',
                backendCommand: 'manifoldSnapshot(hybrid)',
            }),
            expect.objectContaining({
                stageId: 'hopfProjection',
                backendCommand: 'manifoldSnapshot(hopf)',
            }),
            expect.objectContaining({
                stageId: 'lorentzForest',
                backendCommand: 'manifoldSnapshot(lorentz)',
            }),
            expect.objectContaining({
                stageId: 'productManifold',
                backendCommand: 'manifoldSnapshot(product)',
            }),
        ]));
    });

    it('audits the backend command path for reasoning graph before Rust debugging', () => {
        const audit = service.recipeBridgeAudit('reasoningGraph', {
            buildScope: { mode: 'note', noteId: 'note-1' },
        });

        expect(audit).toEqual(expect.arrayContaining([
            expect.objectContaining({
                stageId: 'dynamicNer',
                backendCommand: 'scanDiscovery',
            }),
            expect.objectContaining({
                stageId: 'semanticAtlas',
                frontendService: 'none',
                backendCommand: 'none',
                backendRoute: expect.stringContaining('QUARANTINED:'),
            }),
            expect.objectContaining({
                stageId: 'nliAdjudication',
                backendCommand: 'semantic:listNliJudgmentInputs -> semantic:applyNliJudgments',
                commandKind: 'mixed',
            }),
            expect.objectContaining({
                stageId: 'relationGraph',
                backendCommand: 'relation:list',
                backendRoute: expect.stringContaining('graph_candidate_edges'),
            }),
            expect.objectContaining({
                stageId: 'temporalGraph',
                backendCommand: 'relation:list',
                backendRoute: expect.stringContaining('graph_edges'),
            }),
            expect.objectContaining({
                stageId: 'memoryState',
                backendCommand: 'relation:list',
                backendRoute: expect.stringContaining('memories'),
            }),
            expect.objectContaining({
                stageId: 'causalGraph',
                backendCommand: 'relation:list',
                backendRoute: expect.stringContaining('causal_link'),
            }),
        ]));
    });

    it('blocks Semantic Graph before model warm or native execution', async () => {
        const options = {
            selectedModel: 'mongodb-leaf-mt' as const,
            selectedModelLabel: 'MDBR Leaf MT',
            dimensionLabel: '384d',
            buildScope: { mode: 'folder' as const, folderId: 'folder-1' },
            buildPolicy: 'force' as const,
        };

        const plan = service.recipePlan('semanticGraph', options);
        expect(plan.runnable).toBe(false);
        expect(plan.blockedReason).toBe(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        await expect(service.runRecipe('semanticGraph', options)).rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        expect(machine.loadSemanticModel).not.toHaveBeenCalled();
        expect(atlasScan.runRichEmbeddingScan).not.toHaveBeenCalled();
        expect(phoenixUiApi.loadManifoldAtlasSnapshot).not.toHaveBeenCalled();
    });

    it('blocks Adjudicated Semantic Graph before NLI initialization', async () => {
        await expect(service.runRecipe('adjudicatedSemanticGraph', {
            selectedModel: 'mongodb-leaf-mt',
            selectedModelLabel: 'MDBR Leaf MT',
            dimensionLabel: '384d',
            buildScope: { mode: 'note', noteId: 'note-1' },
        })).rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        expect(nli.initialize).not.toHaveBeenCalled();
        expect(phoenix.storeCommand).not.toHaveBeenCalled();
    });

    it('does not load a selected embedding model for a quarantined recipe', async () => {
        const options = {
            selectedModel: 'mongodb-leaf-mt' as const,
            selectedModelLabel: 'MDBR Leaf MT',
            dimensionLabel: '384d',
            buildScope: { mode: 'note' as const, noteId: 'note-1' },
        };

        const plan = service.recipePlan('semanticGraph', options);
        expect(plan.runnable).toBe(false);
        await expect(service.runRecipe('semanticGraph', options)).rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        expect(ner.warmProvider).not.toHaveBeenCalled();
        expect(machine.loadSemanticModel).not.toHaveBeenCalled();
        expect(atlasScan.runRichEmbeddingScan).not.toHaveBeenCalled();
        expect(phoenixUiApi.loadManifoldAtlasSnapshot).not.toHaveBeenCalled();
        expect(nli.initialize).not.toHaveBeenCalled();
    });

    it('blocks Reasoning Graph before any dependent stage starts', async () => {
        await expect(service.runRecipe('reasoningGraph', {
            selectedModel: 'mongodb-leaf-mt',
            selectedModelLabel: 'MDBR Leaf MT',
            dimensionLabel: '384d',
            buildScope: { mode: 'note', noteId: 'note-1' },
        })).rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        expect(ner.warmProvider).not.toHaveBeenCalled();
        expect(machine.loadSemanticModel).not.toHaveBeenCalled();
        expect(nli.initialize).not.toHaveBeenCalled();
        expect(phoenix.storeCommand).not.toHaveBeenCalled();
    });

    it('runs Dynamic NER through NerService using the open note when no scope is provided', async () => {
        await service.runRecipe('runNer');

        expect(ner.warmProvider).toHaveBeenCalledWith('dynamic_ner');
        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            noteId: 'note-1',
            noteTitle: 'Runtime Note',
            plainText: expect.stringContaining('Aella'),
        }));
        expect(atlasScan.runRichEmbeddingScan).not.toHaveBeenCalled();
    });

    it('runs Dynamic NER over the selected multi-note scope', async () => {
        await service.runRecipe('runNer', {
            buildScope: { mode: 'multiNote', noteIds: ['note-2', 'note-3'] },
            noteIds: ['note-2', 'note-3'],
        });

        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            noteId: 'scope:multiNote',
            noteTitle: '2 selected notes',
            plainText: expect.stringContaining('Branna crossed the bridge'),
        }));
        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            plainText: expect.stringContaining('Calder watched Merrow'),
        }));
        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            plainText: expect.not.stringContaining('Aella met Kai'),
        }));
        expect(machine.setNotice).toHaveBeenCalledWith(expect.stringContaining('2 documents'));
    });

    it('keeps Dynamic NER required for folder graph builds without add-ons', () => {
        const plan = service.recipePlan('textGraph', {
            buildScope: { mode: 'folder', folderId: 'folder-1' },
        });

        expect(plan.requiredModels.map((model) => model.id)).toEqual(['dynamicNer']);
        expect(plan.dependencyChain).toContain('dynamicNer');
        expect(plan.operations.map((operation) => operation.kind)).toEqual([
            'warmModel',
            'dynamicNerScan',
            'richTextGraphScan',
        ]);
    });

    it('reports legacy text graph capabilities as blocked while Dynamic NER remains runnable', () => {
        const textGraphCapabilities: AtlasCapabilityId[] = [
            'dynamicSurface',
            'dynamicChunking',
            'mentionGraph',
            'evidenceGraph',
            'surfaceGraph',
            'assertedKernel',
        ];

        for (const capabilityId of textGraphCapabilities) {
            const state = service.capabilityState(capabilityId);

            expect(state.runnable).toBe(false);
            expect(state.status).toBe('blocked');
            expect(state.blockedReason).toBe(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
            expect(state.operationKind).toBe('richTextGraphScan');
            expect(state.requiredModels).toEqual([]);
            expect(service.modelRequirementLabel(state.requiredModels)).toBe('none');
        }

        const nerState = service.capabilityState('dynamicNer');
        expect(nerState.runnable).toBe(true);
        expect(nerState.operationKind).toBe('dynamicNerScan');
        expect(nerState.requiredModels.map((model) => model.id)).toEqual(['dynamicNer']);
    });

    it('exposes native reasoning store probes as read-only runnable commands', async () => {
        const probeCapabilities: AtlasCapabilityId[] = [
            'relationGraph',
            'temporalGraph',
            'eventIdentity',
            'memoryState',
            'causalGraph',
        ];

        for (const capabilityId of probeCapabilities) {
            const state = service.capabilityState(capabilityId);

            expect(state.runnable).toBe(true);
            expect(state.operationKind).toBe('nativeStoreProbe');
            expect(state.status).toBe('ready');
            expect(state.runPolicy).toBe('read-only');
            expect(state.mutationPolicy).toBe('read-only');
            expect(state.requiredServices[0].ready).toBe(true);

            const result = await service.runCapability(capabilityId);

            expect(result.operationKind).toBe('nativeStoreProbe');
            expect(result.rawResult).toEqual(expect.objectContaining({
                capabilityId,
                command: 'relation:list',
                count: 1,
            }));
        }

        expect(phoenix.storeCommand).toHaveBeenCalledWith('relation:list', expect.objectContaining({
            relation: 'graph_candidate_edges',
        }));
        expect(machine.setNotice).toHaveBeenCalledWith(expect.stringContaining('No graph data was mutated'));
    });

    it('exposes causal graph through the safe read-only native probe', () => {
        const state = service.capabilityState('causalGraph');

        expect(state.runnable).toBe(true);
        expect(state.operationKind).toBe('nativeStoreProbe');
        expect(state.status).toBe('ready');
        expect(state.runPolicy).toBe('read-only');
        expect(state.mutationPolicy).toBe('read-only');
        expect(state.readinessProbe.detail).toContain('graph_edges');
    });

    it('keeps Hybrid, Hopf, and Lorentz as separate read-only manifold commands', async () => {
        const capabilities: Array<[AtlasCapabilityId, string]> = [
            ['hybridManifold', 'hybrid'],
            ['hopfProjection', 'hopf'],
            ['lorentzForest', 'lorentz'],
            ['productManifold', 'product'],
        ];

        for (const [capabilityId, mode] of capabilities) {
            const state = service.capabilityState(capabilityId);
            expect(state.operationKind).toBe('manifoldSnapshot');
            expect(state.runPolicy).toBe('read-only');
            expect(state.mutationPolicy).toBe('read-only');
            expect(state.requiredServices[0].backendRoute).toContain(mode);

            const result = await service.runCapability(capabilityId, {
                buildScope: { mode: 'note', noteId: 'note-1' },
            });

            expect(result.capabilityId).toBe(capabilityId);
            expect(result.operationKind).toBe('manifoldSnapshot');
            expect(result.rawResult).toEqual(expect.objectContaining({ manifold: mode }));
        }

        expect(phoenixUiApi.loadManifoldAtlasSnapshot.mock.calls.map((call) => call[0])).toEqual([
            'hybrid',
            'hopf',
            'lorentz',
            'product',
        ]);
        expect(phoenixUiApi.loadManifoldAtlasSnapshot.mock.calls[0][1]).toEqual({ mode: 'note', noteId: 'note-1' });
    });

    it('runs all embedding projections before native reasoning probes', () => {
        const semantic = service.recipePlan('semanticGraph');
        const reasoning = service.recipePlan('reasoningGraph');

        expect(semantic.operations.some((operation) => operation.kind === 'nativeStoreProbe')).toBe(false);
        expect(semantic.operations.filter((operation) => operation.kind === 'manifoldSnapshot').map((operation) => operation.manifold)).toEqual([
            'hybrid',
            'hopf',
            'lorentz',
            'product',
        ]);
        expect(reasoning.operations.filter((operation) => operation.kind === 'manifoldSnapshot').map((operation) => operation.manifold)).toEqual([
            'hybrid',
            'hopf',
            'lorentz',
            'product',
        ]);
        expect(reasoning.requiredCapabilities).toEqual(expect.arrayContaining([
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
            'productManifold',
            'relationGraph',
            'eventIdentity',
            'temporalGraph',
            'memoryState',
            'causalGraph',
        ]));
        expect(reasoning.optionalCapabilities).toEqual([]);
    });

    it('runs NLI adjudication through the native queue and apply commands', async () => {
        const state = service.capabilityState('nliAdjudication');

        expect(state.runnable).toBe(true);
        expect(state.operationKind).toBe('nliAdjudication');
        expect(state.runPolicy).toBe('native-only');
        expect(state.requiredModels.map((model) => model.id)).toEqual(['nli']);

        const result = await service.runCapability('nliAdjudication', { noteIds: ['note-1'] });

        expect(phoenix.storeCommand).toHaveBeenNthCalledWith(1, 'semantic:listNliJudgmentInputs', expect.objectContaining({
            documentIds: ['note-1'],
            modelId: 'onnx-community/ModernBERT-base-nli-ONNX',
            embeddingModelId: 'jina-v5-nano-retrieval',
            dimensionLabel: '768d',
            dimension: 768,
        }));
        expect(nli.initialize).toHaveBeenCalledWith('onnx-community/ModernBERT-base-nli-ONNX');
        expect(nli.classifyStream).toHaveBeenCalledWith(
            expect.arrayContaining([expect.objectContaining({ judgmentId: 'judgment-1' })]),
            expect.any(Function),
            4,
        );
        expect(nli.classifyStream.mock.calls[0][0]).toHaveLength(1);
        expect(phoenix.storeCommand).toHaveBeenNthCalledWith(2, 'semantic:applyNliJudgments', expect.objectContaining({
            modelId: 'onnx-community/ModernBERT-base-nli-ONNX',
            embeddingModelId: 'jina-v5-nano-retrieval',
            dimensionLabel: '768d',
            dimension: 768,
            results: expect.arrayContaining([expect.objectContaining({ predictedLabel: 'entailment' })]),
        }));
        expect(result.rawResult).toEqual(expect.objectContaining({
            inputCount: 2,
            plannedInputCount: 1,
            duplicateInputCount: 1,
            stageSummaries: expect.arrayContaining([
                expect.objectContaining({
                    stage: 'candidatePlan',
                    counts: expect.objectContaining({
                        rawInputs: 2,
                        plannedInputs: 1,
                        duplicateInputs: 1,
                    }),
                }),
                expect.objectContaining({ stage: 'classification' }),
                expect.objectContaining({ stage: 'apply' }),
            ]),
        }));
    });
});

function createMachineMock() {
    const notice = signal<string | null>(null);
    const graphFocus = signal<unknown>(null);
    const manifoldStatuses = signal<any>({ hybrid: 'idle', hopf: 'idle', lorentz: 'idle', product: 'idle' });
    let manifoldLoadSeq = 0;
    const loadIds: Record<string, number> = { hybrid: 0, hopf: 0, lorentz: 0, product: 0 };
    return {
        query: signal(''),
        scope: signal('global'),
        vectorStatus: signal<any>('idle'),
        graphStatus: signal<any>('idle'),
        graphAudit: signal(null),
        manifoldStatus: signal<any>('idle'),
        manifoldStatuses,
        notice,
        graphFocus,
        activeLanes: computed(() => ['lexical']),
        graphNodes: computed(() => 0),
        graphEdges: computed(() => 0),
        hasCommittedGraph: computed(() => false),
        setNotice: vi.fn((message: string) => notice.set(message)),
        loadSemanticModel: vi.fn(async () => undefined),
        search: vi.fn(async () => []),
        requestGraphFocus: vi.fn((focus: unknown) => graphFocus.set(focus)),
        beginManifoldLoad: vi.fn((mode = 'hybrid') => {
            const loadId = ++manifoldLoadSeq;
            loadIds[mode] = loadId;
            manifoldStatuses.update((statuses: Record<string, string>) => ({ ...statuses, [mode]: 'loading' }));
            return { mode, startedAt: performance.now(), loadId };
        }),
        isCurrentManifoldLoad: vi.fn((load: { mode: string; loadId: number }) => loadIds[load.mode] === load.loadId),
        finishManifoldLoad: vi.fn((load: { mode: string; loadId: number }) => {
            if (loadIds[load.mode] !== load.loadId) return;
            loadIds[load.mode] = 0;
            manifoldStatuses.update((statuses: Record<string, string>) => ({ ...statuses, [load.mode]: 'ready' }));
        }),
        failManifoldLoad: vi.fn((load: { mode: string; loadId: number }) => {
            if (loadIds[load.mode] !== load.loadId) return;
            loadIds[load.mode] = 0;
            manifoldStatuses.update((statuses: Record<string, string>) => ({ ...statuses, [load.mode]: 'error' }));
        }),
    };
}

function createNerMock() {
    const cold = { ready: false, loading: false, error: undefined, device: null };
    return {
        providerStatuses: computed(() => ({
            atlas_surface: cold,
            dynamic_ner: cold,
            fst: cold,
            lfm_local_experiment: cold,
            gliner_local: cold,
        })),
        isAnalyzing: signal(false),
        warmProvider: vi.fn(async () => undefined),
        runDynamicScan: vi.fn(async () => undefined),
        suggestions: signal([{ id: 'suggestion-1' }]),
    };
}

function createAtlasScanMock() {
    return {
        lastResult: signal(null),
        running: computed(() => false),
        runRichEmbeddingScan: vi.fn(async () => ({
            mode: 'rich-embeddings',
            indexedDocuments: 2,
            candidateSuggestions: 1,
            exportableMentions: 1,
            relationCandidates: 8,
            nativeResult: {
                scanId: 'scan-1',
                processedDocuments: 2,
                skippedDocuments: 0,
                stageSummaries: [],
                lensChunkCounts: {},
                graphDeltaCounts: { vertices: 3, candidateEdges: 4 },
                embeddingCounts: { leaf: 5, entity: 6, lens: 7 },
                relationCandidateCount: 8,
                candidateSuggestions: [],
            },
        })),
    };
}

function createNliMock() {
    return {
        isInitialized: signal(false),
        modelId: signal<string | null>(null),
        isProcessing: signal(false),
        device: signal('wasm'),
        initialize: vi.fn(async () => undefined),
        classifyStream: vi.fn(async (
            _inputs: unknown,
            onBatch: (batch: { results: unknown[] }) => void,
        ) => {
            onBatch({
                results: [{
                    judgmentId: 'judgment-1',
                    groupId: 'group-1',
                    sourceId: 'source-1',
                    targetId: 'target-1',
                    edgeType: 'supports',
                    direction: 'forward',
                    premise: 'Aella met Kai near the harbor.',
                    hypothesis: 'Aella encountered Kai.',
                    entailment: 0.91,
                    neutral: 0.06,
                    contradiction: 0.03,
                    predictedLabel: 'entailment',
                    confidence: 0.91,
                }],
            });
        }),
    };
}

function createNoteStoreMock() {
    return {
        currentNote: signal({
            id: 'note-1',
            title: 'Runtime Note',
            content: 'Aella met Kai near the harbor.',
            markdownContent: '',
            folderId: 'folder-1',
        }),
        openNote: vi.fn(),
    };
}

function createPhoenixUiApiMock() {
    return {
        loadManifoldAtlasSnapshot: vi.fn(async (manifold: 'hybrid' | 'hopf' | 'lorentz' | 'product') => ({
            manifold,
            geometryVersion: `${manifold}_test_v1`,
            sourceLabel: `${manifold} test snapshot`,
            capabilities: { ann: true, anchors: true, fibers: manifold === 'hopf', phase: manifold === 'hopf', cones: manifold !== 'hybrid' },
            payload: {
                nodes: [{ id: `${manifold}:node` }],
                edges: [{ id: `${manifold}:edge` }],
                cells: manifold === 'hopf' ? [{ id: 'cell-1' }] : [],
                charts: [],
                coneTraces: manifold === 'hopf' ? [{ id: 'cone-1' }] : [],
                anchorProjections: manifold === 'hopf' ? [{ id: 'anchor-1' }] : [],
                lorentzTrees: manifold === 'lorentz' ? [{ treeId: 'identity' }] : [],
                lorentzMemberships: manifold === 'lorentz' ? [{ treeId: 'identity', nodeId: 'node-1' }] : [],
            },
        })),
    };
}

function createPhoenixBackendMock() {
    return {
        storeCommand: vi.fn(async (command: string) => {
            if (command === 'semantic:listNliJudgmentInputs') {
                return [{
                    judgmentId: 'judgment-1',
                    groupId: 'group-1',
                    sourceId: 'source-1',
                    targetId: 'target-1',
                    edgeType: 'supports',
                    direction: 'forward',
                    premise: 'Aella met Kai near the harbor.',
                    hypothesis: 'Aella encountered Kai.',
                }, {
                    judgmentId: 'judgment-duplicate',
                    groupId: 'group-1',
                    sourceId: 'source-1',
                    targetId: 'target-1',
                    edgeType: 'supports',
                    direction: 'forward',
                    premise: 'Aella met Kai near the harbor.',
                    hypothesis: 'Aella encountered Kai.',
                }];
            }
            if (command === 'semantic:applyNliJudgments') {
                return { applied: 1 };
            }
            return [{ id: 'row-1' }];
        }),
    };
}

