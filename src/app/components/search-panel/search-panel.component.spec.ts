import '@angular/compiler';
import {
    Injector,
    computed,
    createEnvironmentInjector,
    runInInjectionContext,
    signal,
    type EnvironmentInjector,
} from '@angular/core';
import { BehaviorSubject } from 'rxjs';
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

vi.mock('../../lib/dexie/db', () => ({
    db: {
        notes: {
            bulkGet: dbNotesMock.bulkGet,
            toArray: dbNotesMock.toArray,
            where: dbNotesMock.where,
        },
    },
}));

import { SearchPanelComponent } from './search-panel.component';
import { NotesService } from '../../lib/dexie/notes.service';
import { NoteEditorStore } from '../../lib/store/note-editor.store';
import { PhoenixMachineControlService } from '../../services/phoenix-machine-control.service';
import { NerService } from '../../services/ner.service';
import { AtlasScanCoordinatorService } from '../../services/atlas-scan-coordinator.service';
import { BlueprintHubService } from '../blueprint-hub/blueprint-hub.service';
import { NliWorkerService } from '../../lib/services/nli-worker.service';
import { AtlasCapabilityRuntimeService } from '../../services/atlas-capability-runtime.service';
import { GraphRebuildPipelineService } from '../../graph-rebuild/graph-rebuild-pipeline.service';
import { PhoenixUiApiService } from '../../services/phoenix-ui-api.service';
import { PhoenixBackendService } from '../../services/phoenix-backend.service';
import { CalendarService } from '../../services/calendar.service';

describe('SearchPanelComponent model recipe lifecycle', () => {
    let injector: EnvironmentInjector;
    let component: SearchPanelComponent;
    let machine: ReturnType<typeof createMachineMock>;
    let ner: ReturnType<typeof createNerMock>;
    let atlasScan: ReturnType<typeof createAtlasScanMock>;
    let nli: ReturnType<typeof createNliMock>;

    beforeEach(() => {
        dbNotesMock.rows.clear();
        dbNotesMock.bulkGet.mockClear();
        dbNotesMock.toArray.mockClear();
        dbNotesMock.where.mockClear();
        machine = createMachineMock();
        ner = createNerMock();
        atlasScan = createAtlasScanMock();
        nli = createNliMock();
        const parentInjector = Injector.create({ providers: [] }) as unknown as EnvironmentInjector;
        injector = createEnvironmentInjector([
            { provide: NotesService, useValue: createNotesMock() },
            { provide: NoteEditorStore, useValue: createNoteStoreMock() },
            { provide: PhoenixMachineControlService, useValue: machine },
            { provide: NerService, useValue: ner },
            { provide: AtlasScanCoordinatorService, useValue: atlasScan },
            { provide: BlueprintHubService, useValue: { openPage: vi.fn() } },
            { provide: NliWorkerService, useValue: nli },
            { provide: PhoenixUiApiService, useValue: createPhoenixUiApiMock() },
            { provide: PhoenixBackendService, useValue: createPhoenixBackendMock() },
            { provide: GraphRebuildPipelineService, useValue: createFullAtlasPipelineMock() },
            { provide: CalendarService, useValue: createCalendarMock() },
            AtlasCapabilityRuntimeService,
        ], parentInjector);
        component = runInInjectionContext(injector, () => new SearchPanelComponent());
    });

    afterEach(() => {
        injector.destroy();
        vi.clearAllMocks();
    });

    it('loads the semantic model before Semantic Graph runs', async () => {
        await component.runAtlasRecipe('semanticGraph');

        expect(ner.warmProvider).toHaveBeenCalledWith('dynamic_ner');
        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            plainText: expect.stringContaining('Aella'),
        }));
        expect(machine.loadSemanticModel).toHaveBeenCalledWith(
            'jina-v5-nano-retrieval',
            'Jina v5 Nano',
            '768d',
        );
        expect(atlasScan.runRichEmbeddingScan).toHaveBeenCalledWith(expect.objectContaining({
            includeSemanticAtlas: true,
            modelId: 'jina-v5-nano-retrieval',
            modelLabel: 'Jina v5 Nano',
            dimensionLabel: '768d',
        }));
        expect(machine.loadSemanticModel.mock.invocationCallOrder[0])
            .toBeLessThan(atlasScan.runRichEmbeddingScan.mock.invocationCallOrder[0]);
    });

    it('anchors Text Graph with Dynamic NER while keeping semantic and NLI lanes out', async () => {
        await component.runAtlasRecipe('textGraph');
        component.setBuildPolicy('force');
        await component.runAtlasRecipe('textGraph');

        expect(ner.warmProvider).toHaveBeenCalledWith('dynamic_ner');
        expect(ner.runDynamicScan).toHaveBeenCalledTimes(2);
        expect(machine.loadSemanticModel).not.toHaveBeenCalled();
        expect(nli.initialize).not.toHaveBeenCalled();
        expect(atlasScan.runRichEmbeddingScan).toHaveBeenNthCalledWith(1, expect.objectContaining({
            policy: 'dirty-only',
            includeSemanticAtlas: false,
        }));
        expect(atlasScan.runRichEmbeddingScan).toHaveBeenNthCalledWith(2, expect.objectContaining({
            policy: 'force',
            includeSemanticAtlas: false,
        }));
    });

    it('runs the NER suggestion stage without opening or rebuilding the graph', async () => {
        component.selectRecipe('semanticGraph');

        await component.runEntitySuggestionStage();

        expect(component.selectedRecipe()).toBe('semanticGraph');
        expect(ner.warmProvider).toHaveBeenCalledWith('dynamic_ner');
        expect(ner.runDynamicScan).toHaveBeenCalledWith(expect.objectContaining({
            noteId: 'note-1',
            noteTitle: 'Runtime Note',
            plainText: expect.stringContaining('Aella'),
        }));
        expect(atlasScan.runRichEmbeddingScan).not.toHaveBeenCalled();
        expect(machine.requestGraphFocus).not.toHaveBeenCalled();
    });

    it('stops the run when required model warming fails', async () => {
        machine.loadSemanticModel.mockRejectedValueOnce(new Error('semantic load failed'));

        await component.runAtlasRecipe('semanticGraph');

        expect(atlasScan.runRichEmbeddingScan).not.toHaveBeenCalled();
        expect(component.failedRecipeStep()).toBe('warm');
        expect(machine.error()).toBe('semantic load failed');
    });

    it('offers whole-path presets and the full backend graph target map', () => {
        expect(component.graphBuildRecipes.map((recipe) => recipe.id)).toEqual([
            'textGraph',
            'semanticGraph',
            'adjudicatedSemanticGraph',
            'reasoningGraph',
        ]);

        const targetIds = component.backendGraphTargets().map((target) => target.capability.id);
        expect(targetIds).toEqual(expect.arrayContaining([
            'dynamicSurface',
            'dynamicChunking',
            'dynamicNer',
            'assertedKernel',
            'relationGraph',
            'temporalGraph',
            'eventIdentity',
            'memoryState',
            'causalGraph',
            'semanticAtlas',
            'nliAdjudication',
            'hopfProjection',
            'lorentzForest',
        ]));

        component.selectCapability('causalGraph');
        expect(component.selectedCapabilityState().status).toBe('ready');
        expect(component.selectedCapabilityState().operationKind).toBe('nativeStoreProbe');
        expect(component.selectedRecipe()).toBe('reasoningGraph');
        expect(component.isRecipeDisabled(component.selectedRecipe())).toBe(false);
    });

    it('exposes model review lanes from Atlas Command state', () => {
        const lanes = component.modelLaneViews();

        expect(lanes.map((lane) => lane.label)).toEqual([
            'Dynamic NER',
            'Co-occurrence',
            'Semantic Embedding',
            'NLI',
            'Manifold Projection',
        ]);
    });

    it('exposes layered and sleeping capabilities from Atlas Command state', () => {
        expect(component.capabilityLayers().map((layer) => layer.label)).toEqual([
            'Text Surface',
            'Entity + Mention Intelligence',
            'Graph Commit',
            'Reasoning Graphs',
            'Semantic + Adjudication',
            'Manifold / Geometry',
            'Retrieval / Visualization',
        ]);
        expect(component.sleepingCapabilities().map((capability) => capability.id)).toContain('causalGraph');
        expect(component.capabilityListLabel(['dynamicSurface', 'causalGraph'])).toBe('Dynamic Text Surface → Causal Graph');
    });

    it('surfaces runtime graph build plans and contextual warm labels', () => {
        component.selectRecipe('textGraph');
        const textPlan = component.selectedRecipePlan();

        expect(textPlan.requiredModels.map((model) => model.id)).toEqual(['dynamicNer']);
        expect(component.modelRequirementLabel(textPlan.requiredModels)).toContain('Dynamic NER');
        expect(component.warmButtonLabel()).toBe('Warmed');
        expect(textPlan.backendRoute).toContain('includeSemanticAtlas=false');
        expect(component.expectedOutputLabel(textPlan.expectedOutputs)).toContain('graph delta counts');

        component.selectRecipe('semanticGraph');
        const semanticPlan = component.selectedRecipePlan();

        expect(semanticPlan.requiredModels.map((model) => model.id)).toEqual(['dynamicNer', 'semanticEmbedding']);
        expect(component.warmButtonLabel()).toBe('Warm Embedding');
        expect(component.serviceRequirementLabel(semanticPlan.requiredServices)).toContain('PhoenixMachineControlService.loadSemanticModel');
        expect(component.expectedOutputLabel(semanticPlan.expectedOutputs)).toContain('relation candidates');

        component.selectRecipe('adjudicatedSemanticGraph');
        expect(component.warmButtonLabel()).toBe('Warm Embedding + NLI');
        expect(component.selectedPipelineRail().map((stage) => stage.label)).toContain('NLI Adjudication');

        component.selectRecipe('reasoningGraph');
        expect(component.selectedRecipePlan().requiredModels.map((model) => model.id)).toEqual(['dynamicNer', 'semanticEmbedding', 'nli']);
        expect(component.selectedPipelineRail().map((stage) => stage.label)).toEqual(expect.arrayContaining([
            'Relation Graph',
            'Temporal Graph',
            'Memory / State',
            'Causal Graph',
        ]));
    });

    it('syncs graph recipe chips to their involved target toggles', () => {
        component.selectedCapabilityIds.set(['relationGraph', 'hybridManifold', 'galaxyVisualization']);

        component.selectRecipe('textGraph');

        expect(component.selectedCapabilityIds()).toEqual([
            'dynamicSurface',
            'dynamicChunking',
            'dynamicNer',
            'mentionGraph',
            'evidenceGraph',
            'surfaceGraph',
            'assertedKernel',
        ]);
        expect(component.isCapabilitySelected('semanticEmbedding')).toBe(false);
        expect(component.isCapabilitySelected('hybridManifold')).toBe(false);

        component.selectRecipe('semanticGraph');

        expect(component.selectedCapabilityIds()).toEqual([
            'dynamicSurface',
            'dynamicChunking',
            'dynamicNer',
            'mentionGraph',
            'evidenceGraph',
            'surfaceGraph',
            'assertedKernel',
            'semanticEmbedding',
            'semanticAtlas',
            'semanticCandidate',
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
            'productManifold',
        ]);
        expect(component.isCapabilitySelected('nliAdjudication')).toBe(false);

        component.selectRecipe('adjudicatedSemanticGraph');

        expect(component.selectedCapabilityIds()).toEqual(expect.arrayContaining([
            'semanticCandidate',
            'nliAdjudication',
        ]));
        expect(component.isCapabilitySelected('relationGraph')).toBe(false);

        component.selectRecipe('reasoningGraph');

        expect(component.selectedCapabilityIds()).toEqual(expect.arrayContaining([
            'dynamicNer',
            'semanticEmbedding',
            'semanticAtlas',
            'semanticCandidate',
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
            'nliAdjudication',
            'relationGraph',
            'temporalGraph',
            'eventIdentity',
            'memoryState',
            'causalGraph',
        ]));
        expect(component.isCapabilitySelected('causalGraph')).toBe(true);
    });

    it('drives the selected rail from the backend capability dependency chain', () => {
        component.selectedCapabilityIds.set(['semanticEmbedding', 'semanticAtlas']);
        component.selectCapability('assertedKernel');

        expect(component.selectedCapabilityIds()).toEqual([
            'dynamicSurface',
            'dynamicChunking',
            'dynamicNer',
            'mentionGraph',
            'evidenceGraph',
            'surfaceGraph',
            'assertedKernel',
        ]);
        expect(component.isCapabilitySelected('semanticEmbedding')).toBe(false);
        expect(component.selectedPipelineRail().map((stage) => stage.label)).toEqual(expect.arrayContaining([
            'Global',
            'Dynamic Text Surface',
            'Dynamic Chunking',
            'Dynamic NER',
            'Mention / Co-occurrence Graph',
            'Evidence Graph',
            'Surface Graph',
            'Asserted Kernel',
        ]));

        component.selectCapability('temporalGraph');
        expect(component.selectedCapabilityState().operationKind).toBe('nativeStoreProbe');
        expect(component.selectedRecipe()).toBe('reasoningGraph');
        expect(component.selectedCapabilityIds()).toEqual(expect.arrayContaining([
            'dynamicNer',
            'semanticEmbedding',
            'nliAdjudication',
            'temporalGraph',
        ]));
    });

    it('keeps projection selections attached to the semantic embedding contract', () => {
        for (const capabilityId of ['hybridManifold', 'hopfProjection', 'lorentzForest'] as const) {
            component.selectCapability(capabilityId);

            expect(component.selectedRecipe()).toBe('semanticGraph');
            expect(component.selectedCapabilityIds()).toEqual(expect.arrayContaining([
                'dynamicNer',
                'semanticEmbedding',
                'semanticAtlas',
                'semanticCandidate',
                'hybridManifold',
                'hopfProjection',
                'lorentzForest',
                capabilityId,
            ]));
            expect(component.isCapabilitySelected('nliAdjudication')).toBe(false);
            expect(component.isCapabilitySelected('relationGraph')).toBe(false);
            expect(component.isCapabilitySelected('causalGraph')).toBe(false);
        }
    });

    it('preserves graph target scroll position while selecting capabilities', async () => {
        const scrollHost = { scrollTop: 640 };
        (component as any).workbenchScroll = { nativeElement: scrollHost };

        const group = component.backendGraphTargetGroups()[0];
        const target = group.targets[0];

        expect(component.trackCapabilityGroup(0, group)).toBe(group.id);
        expect(component.trackCapabilityTarget(0, target)).toBe(target.capability.id);

        component.selectCapability('temporalGraph');
        scrollHost.scrollTop = 0;
        await Promise.resolve();

        expect(scrollHost.scrollTop).toBe(640);
    });

    it('passes selected multi-note source into graph build runtime options', async () => {
        dbNotesMock.rows.set('note-a', {
            id: 'note-a',
            title: 'A',
            content: 'Aella met Kai.',
            markdownContent: '',
            folderId: '',
        });
        dbNotesMock.rows.set('note-b', {
            id: 'note-b',
            title: 'B',
            content: 'Kai followed Ruby.',
            markdownContent: '',
            folderId: '',
        });
        component.notes.set([
            { id: 'note-a', title: 'A', content: 'Aella met Kai.', narrativeId: '', folderId: '', hasBody: true },
            { id: 'note-b', title: 'B', content: 'Kai followed Ruby.', narrativeId: '', folderId: '', hasBody: true },
        ]);
        component.setBuildScopeMode('multiNote');
        component.selectedBuildNoteIds.set([]);
        component.toggleBuildNote('note-a');
        component.toggleBuildNote('note-b');

        await component.runAtlasRecipe('textGraph');

        expect(atlasScan.runRichEmbeddingScan).toHaveBeenCalledWith(expect.objectContaining({
            noteIds: ['note-a', 'note-b'],
            buildScope: { mode: 'multiNote', noteIds: ['note-a', 'note-b'] },
        }));
    });

    it('hydrates unopened build-scope note bodies before estimating chunks', async () => {
        const longA = 'Kai mapped Red Mesa before Hazel answered. '.repeat(160);
        const longB = 'Rowan watched Boundary Keep while Brynwyn listened. '.repeat(160);
        dbNotesMock.rows.set('note-a', {
            id: 'note-a',
            title: 'A',
            content: longA,
            markdownContent: longA,
            folderId: '',
            hasBody: true,
        });
        dbNotesMock.rows.set('note-b', {
            id: 'note-b',
            title: 'B',
            content: longB,
            markdownContent: longB,
            folderId: '',
            hasBody: true,
        });
        component.notes.set([
            { id: 'note-a', title: 'A', content: '', narrativeId: '', folderId: '', hasBody: false },
            { id: 'note-b', title: 'B', content: '', narrativeId: '', folderId: '', hasBody: false },
        ]);
        component.setBuildScopeMode('multiNote');
        component.selectedBuildNoteIds.set(['note-a', 'note-b']);

        await (component as any).hydrateBuildScopeNotes(component.scopedNotes());

        expect(component.hydratedBuildScopeNotes().map((note) => note.content.length)).toEqual([longA.length, longB.length]);
        expect(component.chunkingStatus().estimatedChunks).toBeGreaterThan(2);
    });

    it('runs the one-shot Build Graph path from the explicit primary button', async () => {
        const pipeline = injector.get(GraphRebuildPipelineService) as unknown as ReturnType<typeof createFullAtlasPipelineMock>;
        pipeline.graphModelsReady.mockReturnValue(true);
        pipeline.modelReadiness.mockReturnValue([
            { id: 'dynamicNer', label: 'Dynamic NER', status: 'ready', detail: 'ready' },
            { id: 'semanticEmbedding', label: 'Semantic Embedding', status: 'idle', detail: 'idle' },
            { id: 'nli', label: 'NLI', status: 'ready', detail: 'ready' },
        ]);

        component.setBuildScopeMode('note');
        await component.buildGraphAtlas();

        expect(pipeline.buildGraph).toHaveBeenCalledTimes(1);
        expect(pipeline.buildGraph.mock.calls[0][0]).toEqual(expect.objectContaining({
            policy: 'delta',
            postProcessMode: 'full',
            calendarRegistrySnapshot: expect.objectContaining({ id: 'calendar-registry:test' }),
            scope: expect.objectContaining({
                kind: 'note',
                scopeId: 'note:note-1',
                noteIds: ['note-1'],
            }),
        }));
        expect(component.lastRunStatus().label).toBe('Graph build complete');
        expect(machine.requestGraphFocus).toHaveBeenCalled();
    });

    it('keeps Jina out of Build Graph and uses it only for Embed Atlas', async () => {
        const pipeline = injector.get(GraphRebuildPipelineService) as unknown as ReturnType<typeof createFullAtlasPipelineMock>;
        pipeline.graphModelsReady.mockReturnValue(true);
        pipeline.embeddingModelReady.mockReturnValue(false);
        component.notes.set([
            {
                id: 'note-1',
                title: 'Runtime Note',
                content: 'Aella met Kai near the harbor.',
                narrativeId: '',
                folderId: 'folder-1',
                hasBody: true,
            },
        ]);
        component.setBuildScopeMode('note');

        await component.buildGraphAtlas();

        expect(pipeline.buildGraph).toHaveBeenCalledTimes(1);
        expect(machine.loadSemanticModel).not.toHaveBeenCalled();
        expect(machine.indexSemanticDocuments).not.toHaveBeenCalled();

        await component.embedAtlas();

        expect(machine.loadSemanticModel).toHaveBeenCalledWith(
            'jina-v5-nano-retrieval',
            'Jina v5 Nano',
            '768d',
        );
        expect(machine.indexSemanticDocuments).toHaveBeenCalledWith([
            expect.objectContaining({
                id: 'note-1',
                title: 'Runtime Note',
                content: expect.stringContaining('Aella'),
            }),
        ]);
    });

    it('surfaces product graph stage and projection timings in the last run panel model', async () => {
        const pipeline = injector.get(GraphRebuildPipelineService) as unknown as ReturnType<typeof createFullAtlasPipelineMock>;

        await component.buildGraphAtlas();

        expect(component.lastRunStatus().label).toBe('Graph build complete');
        expect(component.lastRunReceiptRows()[0].detail).not.toContain('started');
        expect(component.lastRunReceiptRows()[0].detail).not.toContain('completed at');
        expect(component.lastRunReceiptRows()).toEqual([
            expect.objectContaining({
                kind: 'stage',
                label: 'Build Graph Snapshot',
                durationMs: 31,
                detail: expect.stringContaining('accepted relationships 16'),
            }),
            expect.objectContaining({
                kind: 'stage',
                label: 'Signal Target Coverage',
                durationMs: 0,
                detail: expect.stringContaining('targets 666'),
            }),
            expect.objectContaining({
                kind: 'stage',
                label: 'DB Ops',
                durationMs: 15,
                detail: expect.stringContaining('snapshot persist 13 ms'),
            }),
            expect.objectContaining({
                kind: 'stage',
                label: 'Snapshot Payload',
                durationMs: 2,
                detail: expect.stringContaining('primary 1,200 chars'),
            }),
            expect.objectContaining({
                kind: 'stage',
                label: 'Transport Ops',
                durationMs: 30,
                detail: expect.stringContaining('calls 4'),
            }),
            expect.objectContaining({
                kind: 'stage',
                label: 'Receipt DB Ops',
                durationMs: 15,
                detail: expect.stringContaining('persist 15 ms'),
            }),
            expect.objectContaining({
                kind: 'projection',
                label: 'Product Projection',
                durationMs: 9,
                detail: 'snapshot-owned / 3 targets / read-model topology',
            }),
        ]);
    });
});

function createMachineMock() {
    const notice = signal<string | null>(null);
    const error = signal<string | null>(null);
    const activeJob = signal<any>(null);
    const vectorStatus = signal<any>('idle');
    return {
        query: signal(''),
        scope: signal('global'),
        lanes: signal({ lexical: true, semantic: false, graph: false, entities: false, evidence: false }),
        activeLanes: computed(() => ['lexical']),
        graphFocus: signal(null),
        graphLensMode: signal('unified'),
        stages: signal({}),
        activeSignals: signal({ count: 0 }),
        vectorStatus,
        graphStatus: signal<any>('idle'),
        graphAudit: signal(null),
        manifoldMode: signal('hybrid'),
        manifoldStatus: signal<any>('idle'),
        manifoldStatuses: signal<any>({ hybrid: 'idle', hopf: 'idle', lorentz: 'idle' }),
        notice,
        error,
        activeJob,
        lastSummary: signal(null),
        graphNodes: computed(() => 0),
        graphEdges: computed(() => 0),
        registryEntities: computed(() => 0),
        liveDocuments: computed(() => 0),
        indexedDocuments: computed(() => 0),
        staleDocuments: computed(() => 0),
        graphIssueCount: computed(() => 0),
        hasCommittedGraph: computed(() => false),
        setScope: vi.fn(),
        toggleLane: vi.fn(),
        requestGraphFocus: vi.fn(),
        setNotice: vi.fn((message: string) => notice.set(message)),
        loadSemanticModel: vi.fn(async () => {
            vectorStatus.set('ready');
        }),
        indexSemanticDocuments: vi.fn(async () => {
            vectorStatus.set('ready');
        }),
        refreshAuditSafe: vi.fn(),
        search: vi.fn(async () => []),
    };
}

function createNerMock() {
    const status = { ready: true, loading: false, device: null };
    return {
        providerStatuses: computed(() => ({
            atlas_surface: status,
            dynamic_ner: status,
            fst: status,
            lfm_local_experiment: status,
            gliner_local: status,
        })),
        isAnalyzing: signal(false),
        warmProvider: vi.fn(async () => undefined),
        runDynamicScan: vi.fn(async () => undefined),
        suggestions: signal([]),
    };
}

function createAtlasScanMock() {
    return {
        phase: signal('idle'),
        message: signal(null),
        lastResult: signal(null),
        running: computed(() => false),
        runRichEmbeddingScan: vi.fn(async () => ({ mode: 'rich-embeddings' })),
    };
}

function createNliMock() {
    return {
        isInitialized: signal(false),
        modelId: signal<string | null>(null),
        isProcessing: signal(false),
        device: signal('wasm'),
        initialize: vi.fn(async () => undefined),
        classifyStream: vi.fn(async () => undefined),
    };
}

function createNotesMock() {
    return {
        getAllNotes$: () => new BehaviorSubject([]),
        getAllFolders$: () => new BehaviorSubject([]),
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
        loadManifoldAtlasSnapshot: vi.fn(async () => ({ nodes: [], edges: [] })),
    };
}

function createPhoenixBackendMock() {
    return {
        storeCommand: vi.fn(async () => []),
    };
}

function createCalendarMock() {
    return {
        calendarRegistrySnapshot: vi.fn(() => ({
            schemaVersion: 'phoenix-calendar-registry/v1',
            id: 'calendar-registry:test',
            builtAt: 1,
            calendar: {
                id: 'calendar:test',
                name: 'Test Calendar',
                fingerprint: 'calendar:fingerprint:test',
                mode: 'customOrdinal',
                createdFrom: 'manual',
                monthCount: 12,
                weekdayCount: 7,
                hasYearZero: false,
            },
            scope: { kind: 'note', scopeId: 'note:note-1', noteIds: ['note-1'] },
            anchors: [],
            diagnostics: {},
            summary: {
                anchorCount: 0,
                sourceKindCounts: {},
                eventAnchorCount: 0,
                folderAnchorCount: 0,
                periodAnchorCount: 0,
                markerAnchorCount: 0,
                realCompatibleAnchorCount: 0,
                customOrdinalAnchorCount: 0,
                diagnostics: {},
            },
        })),
    };
}

function createFullAtlasPipelineMock() {
    const running = signal(false);
    const lastReceipt = signal<any>(null);
    return {
        running: computed(() => running()),
        lastReceipt: computed(() => lastReceipt()),
        modelReadiness: vi.fn(() => [
            { id: 'dynamicNer', label: 'Dynamic NER', status: 'ready', detail: 'ready' },
            { id: 'semanticEmbedding', label: 'Semantic Embedding', status: 'idle', detail: 'idle' },
            { id: 'nli', label: 'NLI', status: 'idle', detail: 'idle' },
        ]),
        modelsReady: vi.fn(() => false),
        coreModelsReady: vi.fn(() => true),
        graphModelsReady: vi.fn(() => true),
        embeddingModelReady: vi.fn(() => false),
        loadModels: vi.fn(async () => undefined),
        loadGraphModels: vi.fn(async () => undefined),
        loadEmbeddingModel: vi.fn(async () => undefined),
        warmOptionalModel: vi.fn(async () => undefined),
        buildGraph: vi.fn(async () => {
            const receipt = {
                id: 'graph-atlas:note:note-1:123',
                status: 'completed',
                message: 'Build Graph produced 2 nodes, 1 edges, and 3 embedding targets.',
                postProcessMode: 'full',
                durationMs: 12,
                stageReceipts: [
                    {
                        id: 'buildGraphSnapshot',
                        label: 'Build Graph Snapshot',
                        status: 'completed',
                        durationMs: 31,
                        outputCount: 926,
                        counters: { acceptedRelationships: 16, anchors: 358, chunks: 16 },
                        message: 'Build Graph snapshot',
                    },
                    {
                        id: 'signalTargetCoverage',
                        label: 'Signal Target Coverage',
                        status: 'completed',
                        durationMs: 0,
                        outputCount: 0,
                        counters: {
                            targets: 666,
                            candidateTargets: 666,
                            deferredTargets: 442,
                            documentSpine: 2,
                            chunkSpine: 16,
                            entityAnchors: 28,
                        },
                        message: 'Signal target coverage',
                    },
                    {
                        id: 'snapshotDbOps',
                        label: 'DB Ops',
                        status: 'completed',
                        durationMs: 15,
                        outputCount: 0,
                        counters: {
                            occurrenceLoadMs: 1,
                            dbLoadMs: 2,
                            snapshotPersistMs: 13,
                            snapshotStoreMs: 11,
                            snapshotPrimaryStoreMs: 7,
                            snapshotOverGraphStoreMs: 4,
                            snapshotSerializeMs: 2,
                            snapshotPrimaryEncodeMs: 1,
                            snapshotOverGraphEncodeMs: 1,
                            snapshotPayloadProfileMs: 1,
                            snapshotPayloadChars: 1200,
                        },
                        message: 'Snapshot DB reads and persist timing',
                    },
                    {
                        id: 'snapshotPayloadProfile',
                        label: 'Snapshot Payload',
                        status: 'completed',
                        durationMs: 2,
                        outputCount: 0,
                        counters: {
                            snapshotPrimaryPayloadChars: 1200,
                            snapshotPrimaryRawPayloadChars: 1400,
                            snapshotCompressionSavedChars: 200,
                            snapshotCompressionRatioPct: 86,
                            snapshotOverGraphPayloadChars: 400,
                            snapshotTotalScopedPayloadChars: 1600,
                            payloadChunksChars: 300,
                            payloadGraphModelV2Chars: 700,
                            payloadEmbeddingGraphPostProcessChars: 500,
                        },
                        message: 'Top-level snapshot JSON payload section sizes',
                    },
                    {
                        id: 'transportOps',
                        label: 'Transport Ops',
                        status: 'completed',
                        durationMs: 30,
                        outputCount: 0,
                        counters: {
                            transportCalls: 4,
                            transportTotalMs: 30,
                            transportMaxMs: 15,
                            transportRequestBytes: 5632,
                            transportResponseBytes: 1664,
                            jsonRpcCalls: 4,
                            jsonRpcRequestBytes: 5632,
                            jsonRpcResponseBytes: 1664,
                            storeCommandCalls: 3,
                            storeCommandRequestBytes: 5632,
                            storeCommandResponseBytes: 1664,
                            scopedDocumentReadCalls: 1,
                            scopedDocumentReadRequestBytes: 1024,
                            scopedDocumentReadResponseBytes: 640,
                            snapshotDocumentReadCalls: 1,
                            snapshotDocumentReadRequestBytes: 1024,
                            snapshotDocumentReadResponseBytes: 640,
                            applyWalBatchCalls: 1,
                            applyWalBatchRequestBytes: 2048,
                            applyWalBatchResponseBytes: 256,
                            compileDualWriteCalls: 1,
                            compileDualWriteRequestBytes: 2560,
                            compileDualWriteResponseBytes: 768,
                            compileDualWriteRawBytes: 4096,
                            compileDualWriteCompressedBytes: 512,
                        },
                        message: 'TauRPC transport calls and payload volume during this graph run',
                    },
                    {
                        id: 'receiptDbOps',
                        label: 'Receipt DB Ops',
                        status: 'completed',
                        durationMs: 15,
                        outputCount: 0,
                        counters: {
                            receiptPersistMs: 15,
                            receiptPayloadChars: 4096,
                            receiptStoreRecords: 1,
                            receiptStorePayloadChars: 4096,
                            receiptStoreQueueWaitMs: 2,
                            receiptStoreAppendWalMs: 3,
                            receiptStoreManifestMs: 1,
                            receiptStoreNativeApplyMs: 4,
                            receiptStoreTotalMs: 10,
                            receiptJsonRpcCalls: 1,
                            receiptApplyWalBatchRequestBytes: 2048,
                        },
                        message: 'Run receipt persisted to scoped documents',
                    },
                ],
                projectionReceipts: [
                    {
                        mode: 'product',
                        status: 'synced',
                        durationMs: 9,
                        targetCount: 3,
                        vectorCount: 3,
                        counters: { graphRebuildReadModelProjection: 1 },
                        message: 'Product projection synced',
                    },
                ],
            };
            lastReceipt.set(receipt);
            return {
                receipt,
                snapshot: { counters: { nodes: 2, edges: 1, embeddingTargets: 3 } },
            };
        }),
    };
}
