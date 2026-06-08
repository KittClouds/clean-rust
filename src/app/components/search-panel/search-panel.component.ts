import { Component, computed, DestroyRef, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgIcon, provideIcons } from '@ng-icons/core';
import {
  lucideAlertCircle,
  lucideCheck,
  lucideChevronDown,
  lucideCpu,
  lucideFileText,
  lucideFolder,
  lucideGitBranch,
  lucideGlobe,
  lucideLayers,
  lucideLoader2,
  lucideMicrochip,
  lucideMoreVertical,
  lucideSearch,
  lucideSparkles,
  lucideX,
  lucideZap,
} from '@ng-icons/lucide';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { ButtonModule } from 'primeng/button';

import { type SearchScope } from '../../services/phoenix-ui-api.service';
import { NotesService } from '../../lib/dexie/notes.service';
import { NoteEditorStore } from '../../lib/store/note-editor.store';
import * as ops from '../../lib/operations';
import { type RetrievalLane } from '../../services/retrieval-workbench-state.service';
import { PhoenixMachineControlService } from '../../services/phoenix-machine-control.service';
import { NerService } from '../../services/ner.service';
import { AtlasScanCoordinatorService } from '../../services/atlas-scan-coordinator.service';
import { BlueprintHubService } from '../blueprint-hub/blueprint-hub.service';
import { NliWorkerService } from '../../lib/services/nli-worker.service';
import { AtlasCapabilityRuntimeService } from '../../services/atlas-capability-runtime.service';
import { GraphRebuildPipelineService } from '../../graph-rebuild/graph-rebuild-pipeline.service';
import { CalendarService } from '../../services/calendar.service';
import type {
  GraphIndexProjectionReceipt,
  GraphIndexModelReadiness,
  GraphIndexRunRequest,
  GraphIndexRunScope,
  GraphIndexRunReceipt,
  GraphIndexStageReceipt,
  GraphRebuildSignalTargetLane,
  GraphRebuildEntityLinkSuggestion,
  GraphRebuildLinkSuggestion,
  GraphRebuildShadowLink,
  GraphRebuildSnapshot,
} from '../../graph-rebuild/graph-rebuild-snapshot';
import { smartGraphRegistry } from '../../lib/registry';
import type {
  AtlasCapabilityRuntimeState,
  AtlasBuildScope,
  AtlasBuildReceipt,
  AtlasExpectedOutput,
  AtlasModelRequirement,
  AtlasRunOptions,
  AtlasServiceRequirement,
} from '../../services/atlas-capability-runtime.model';
import {
  EMBEDDING_MODELS,
  DEFAULT_SEARCH_MODEL_ID,
  RETRIEVAL_LANE_OPTIONS,
  buildSearchSnippet,
  type ModelId,
  type SearchMode,
  type SearchPanelNote,
  type SearchResultView,
} from './search-panel.model';
import {
  buildAtlasCommandStatus,
  estimateDynamicChunks,
  type AtlasRecipeId,
} from './atlas-command-status.model';
import {
  buildAtlasModelLaneViews,
  buildAtlasRecipeLifecycle,
  laneListLabel,
  type AtlasModelLaneId,
  type AtlasRecipeLifecycleId,
} from './atlas-model-recipe.model';
import {
  ATLAS_GRAPH_BUILD_RECIPE_IDS,
  ATLAS_CAPABILITY_LAYERS,
  ATLAS_CAPABILITY_REGISTRY,
  atlasCapabilityById,
  atlasRecipeDefinitionById,
  capabilityListLabel,
  type AtlasCapability,
  type AtlasCapabilityId,
} from './atlas-capability.model';
import {
  buildReviewClusterViews,
  type ProductDiagnosticsReviewCluster,
} from '../blueprint-hub/tabs/graph-tab/graph-product-diagnostics';

type BuilderCapabilityCard = {
  capability: AtlasCapability;
  state: AtlasCapabilityRuntimeState;
  layerLabel: string;
  chain: AtlasCapabilityId[];
};

type BuilderCapabilityGroup = {
  id: string;
  label: string;
  count: number;
  selectedCount: number;
  targets: BuilderCapabilityCard[];
};

interface LastRunReceiptRow {
  id: string;
  label: string;
  detail: string;
  durationMs: number;
  outputCount: number;
  status: string;
  kind: 'stage' | 'projection';
}

interface PostprocessLaneView {
  id: string;
  label: string;
  admitted: number;
  candidates: number;
  deferred: number;
  percent: number;
}

interface PostprocessStagingView {
  title: string;
  mode: 'plan' | 'budget';
  targets: number;
  candidates: number;
  deferred: number;
  lanes: PostprocessLaneView[];
}

type CompilerTone = 'ready' | 'review' | 'danger' | 'quiet';

interface CompilerMetricView {
  id: string;
  label: string;
  value: number;
  detail: string;
  tone: CompilerTone;
}

type CompilerQueueId = 'lanes' | 'bundles' | 'identity' | 'graph-links' | 'final-patches' | 'receipts';
type CompilerQueueAction = 'toggle-lane' | 'promote' | 'dismiss' | 'accept-link' | 'reject-link' | 'apply-patch' | 'revert-patch';
type CompilerQueueDecision = 'promoted' | 'dismissed' | 'applied' | 'reverted';

interface CompilerQueueView {
  id: CompilerQueueId;
  label: string;
  detail: string;
  count: number;
  tone: CompilerTone;
}

interface CompilerQueueItemView {
  id: string;
  queue: CompilerQueueId;
  label: string;
  detail: string;
  kind: string;
  confidence: number;
  tone: CompilerTone;
  status: string;
  evidenceCount: number;
  blockedReasons: string[];
  receiptSummary: string;
  primaryLabel?: string;
  primaryAction?: CompilerQueueAction;
  secondaryLabel?: string;
  secondaryAction?: CompilerQueueAction;
}

interface CompilerWorkbenchView {
  source: string;
  detail: string;
  blocked: number;
  activeQueue: CompilerQueueId;
  activeLabel: string;
  activeDetail: string;
  metrics: CompilerMetricView[];
  queues: CompilerQueueView[];
  items: CompilerQueueItemView[];
  staging: PostprocessStagingView | null;
}

type Stage8LaneId =
  | 'identity'
  | 'aliases'
  | 'frames'
  | 'evidence'
  | 'coref'
  | 'ontology'
  | 'temporal'
  | 'belief'
  | 'router';

interface Stage8RouterView {
  model: string;
  dimension: string;
  status: string;
  detail: string;
  gate: string;
  budget: string;
  timing: string;
  tone: CompilerTone;
}

interface Stage8LaneView {
  id: Stage8LaneId;
  label: string;
  value: number;
  detail: string;
  tone: CompilerTone;
  queue?: CompilerQueueId;
}

interface Stage8ReviewItemView {
  id: string;
  label: string;
  family: string;
  detail: string;
  action: string;
  confidence: number;
  tone: CompilerTone;
  signals: string[];
  queue?: CompilerQueueId;
}

interface Stage8WorkbenchView {
  label: string;
  detail: string;
  router: Stage8RouterView;
  lanes: Stage8LaneView[];
  reviewItems: Stage8ReviewItemView[];
  receipts: LastRunReceiptRow[];
}

const EMBEDDING_STAGE_LANES: Array<{ id: GraphRebuildSignalTargetLane; label: string }> = [
  { id: 'document_spine', label: 'Document spine' },
  { id: 'chunk_spine', label: 'Chunk spine' },
  { id: 'entity_anchor', label: 'Entity anchors' },
  { id: 'relationship_fact', label: 'Relationship facts' },
  { id: 'temporal_fact', label: 'Temporal facts' },
  { id: 'causal_fact', label: 'Causal facts' },
  { id: 'memory_state', label: 'Memory states' },
  { id: 'event_identity', label: 'Event identity' },
  { id: 'anchor_evidence', label: 'Anchor evidence' },
  { id: 'cooccurrence_weak', label: 'Co-occurrence' },
];

@Component({
  selector: 'app-search-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    NgIcon,
    InputTextModule,
    SelectModule,
    ButtonModule,
  ],
  providers: [provideIcons({
    lucideAlertCircle,
    lucideCheck,
    lucideChevronDown,
    lucideCpu,
    lucideFileText,
    lucideFolder,
    lucideGitBranch,
    lucideGlobe,
    lucideLayers,
    lucideLoader2,
    lucideMicrochip,
    lucideMoreVertical,
    lucideSearch,
    lucideSparkles,
    lucideX,
    lucideZap,
  })],
  templateUrl: './search-panel.component.html',
  styleUrls: [
    './search-panel.component.css',
    './search-panel.content.css',
    './search-panel.run-ledger.css',
    './search-panel.compiler-workbench.css',
    './search-panel.stage8-workbench.css',
    './search-panel.pipeline-map.css',
    './search-panel.pipeline-map-panels.css',
    './search-panel.pipeline-map-rails.css',
  ],
})
export class SearchPanelComponent implements OnInit {
  @ViewChild('workbenchScroll') private workbenchScroll?: ElementRef<HTMLElement>;

  private readonly destroyRef = inject(DestroyRef);
  private readonly notesService = inject(NotesService);
  private readonly noteStore = inject(NoteEditorStore);
  private readonly machine = inject(PhoenixMachineControlService);
  private readonly nerService = inject(NerService);
  private readonly atlasScan = inject(AtlasScanCoordinatorService);
  private readonly hubService = inject(BlueprintHubService);
  private readonly nli = inject(NliWorkerService);
  private readonly atlasRuntime = inject(AtlasCapabilityRuntimeService);
  private readonly fullAtlasPipeline = inject(GraphRebuildPipelineService);
  private readonly calendar = inject(CalendarService);

  readonly query = this.machine.query;
  readonly indexScope = this.machine.scope;
  readonly lanes = this.machine.lanes;
  readonly results = signal<SearchResultView[]>([]);
  readonly notice = this.machine.notice;
  readonly error = this.machine.error;
  readonly isSearching = signal(false);
  readonly searchTime = signal(0);

  readonly vectorStatus = this.machine.vectorStatus;
  readonly graphStatus = this.machine.graphStatus;
  readonly graphAudit = this.machine.graphAudit;
  readonly machineStages = this.machine.stages;
  readonly activeSignals = this.machine.activeSignals;
  readonly activeJob = this.machine.activeJob;
  readonly lastSummary = this.machine.lastSummary;
  readonly nerStatus = this.nerService.providerStatuses;
  readonly isDynamicScanning = computed(() => this.nerService.isAnalyzing() || this.atlasScan.running());

  readonly selectedModel = signal<ModelId>(DEFAULT_SEARCH_MODEL_ID);
  readonly selectedRecipe = signal<AtlasRecipeId>('textGraph');
  readonly selectedCapabilityId = signal<AtlasCapabilityId>('assertedKernel');
  readonly selectedCapabilityIds = signal<AtlasCapabilityId[]>(capabilityIdsForRecipe('textGraph'));
  readonly activeRecipe = signal<AtlasRecipeId | null>(null);
  readonly activeLaneWarm = signal<AtlasModelLaneId | null>(null);
  readonly activeRecipeStep = signal<AtlasRecipeLifecycleId | null>(null);
  readonly completedRecipeSteps = signal<AtlasRecipeLifecycleId[]>([]);
  readonly failedRecipeStep = signal<AtlasRecipeLifecycleId | null>(null);
  readonly folders = signal<Array<{ id: string; name: string }>>([]);
  readonly notes = signal<SearchPanelNote[]>([]);
  readonly buildScopeMode = signal<AtlasBuildScope['mode']>('global');
  readonly selectedBuildFolderId = signal('');
  readonly selectedBuildNoteIds = signal<string[]>([]);
  readonly buildNoteQuery = signal('');
  readonly hydratedBuildScopeNotes = signal<SearchPanelNote[]>([]);
  readonly graphTargetQuery = signal('');
  readonly collapsedCapabilityGroups = signal<string[]>([]);
  readonly buildPolicy = signal<'dirty-only' | 'force'>('dirty-only');
  readonly linkSuggestionDecisions = signal<Record<string, 'accepted' | 'rejected'>>({});
  readonly activeCompilerQueue = signal<CompilerQueueId>('lanes');
  readonly compilerQueueDecisions = signal<Record<string, CompilerQueueDecision>>({});

  readonly laneOptions = RETRIEVAL_LANE_OPTIONS;
  readonly models = EMBEDDING_MODELS;
  readonly buildScopeModes: AtlasBuildScope['mode'][] = ['global', 'folder', 'note', 'multiNote'];
  readonly graphBuildRecipes = ATLAS_GRAPH_BUILD_RECIPE_IDS.map((id) => {
    const recipe = atlasRecipeDefinitionById(id);
    return {
      id: recipe.id,
      label: recipe.label,
      subtitle: recipe.subtitle,
      output: recipe.outputLabel,
      icon: recipe.icon,
    };
  });
  readonly backendGraphTargets = computed<BuilderCapabilityCard[]>(() => {
    const options = this.atlasRunOptions();
    return BUILDER_CAPABILITY_IDS.map((id) => {
      const capability = atlasCapabilityById(id);
      return {
        capability,
        state: this.atlasRuntime.capabilityState(id, options),
        layerLabel: layerLabelForCapability(id),
        chain: expandCapabilityChain(id),
      };
    });
  });
  readonly filteredBackendGraphTargets = computed(() => {
    const query = this.graphTargetQuery().trim().toLowerCase();
    const targets = this.backendGraphTargets();
    if (!query) return targets;
    return targets.filter((target) => {
      const haystack = [
        target.capability.label,
        target.capability.graphTargetLabel || '',
        target.layerLabel,
        target.capability.family,
        target.capability.backendRoute,
        target.state.runPolicy,
        target.state.operationKind,
      ].join(' ').toLowerCase();
      return haystack.includes(query);
    });
  });
  readonly backendGraphTargetGroups = computed<BuilderCapabilityGroup[]>(() => {
    const targets = this.filteredBackendGraphTargets();
    const selected = new Set(this.selectedCapabilityIds());
    return ATLAS_CAPABILITY_LAYERS
      .map((layer) => {
        const layerTargets = targets.filter((target) => layer.capabilityIds.includes(target.capability.id));
        return {
          id: layer.id,
          label: layer.label,
          count: layerTargets.length,
          selectedCount: layerTargets.filter((target) => selected.has(target.capability.id)).length,
          targets: layerTargets,
        };
      })
      .filter((group) => group.count > 0);
  });
  readonly atlasPhase = this.atlasScan.phase;
  readonly atlasMessage = this.atlasScan.message;
  readonly lastAtlasResult = this.atlasScan.lastResult;

  readonly selectedBuildScope = computed<AtlasBuildScope>(() => {
    const mode = this.buildScopeMode();
    if (mode === 'global') return { mode: 'global' };
    if (mode === 'folder') {
      const folderId = this.selectedBuildFolderId()
        || (this.indexScope() !== 'global' ? this.indexScope() : '')
        || this.folders()[0]?.id
        || '';
      return folderId ? { mode: 'folder', folderId } : { mode: 'global' };
    }
    if (mode === 'note') {
      const noteId = this.noteStore.currentNote()?.id || this.selectedBuildNoteIds()[0] || this.notes()[0]?.id || '';
      return noteId ? { mode: 'note', noteId } : { mode: 'global' };
    }
    return { mode: 'multiNote', noteIds: this.selectedBuildNoteIds() };
  });
  readonly buildNoteIds = computed(() => noteIdsFromBuildScope(this.selectedBuildScope()));
  readonly scopedNotes = computed(() => {
    const scope = this.selectedBuildScope();
    const notes = this.notes();
    if (scope.mode === 'global') return notes;
    if (scope.mode === 'folder') return notes.filter((note) => note.folderId === scope.folderId);
    const ids = new Set(noteIdsFromBuildScope(scope));
    return notes.filter((note) => ids.has(note.id));
  });
  private buildScopeHydrationGeneration = 0;
  readonly buildScopeLabel = computed(() => {
    const scope = this.selectedBuildScope();
    if (scope.mode === 'global') return 'Global';
    if (scope.mode === 'folder') return this.folders().find((folder) => folder.id === scope.folderId)?.name || 'Folder';
    if (scope.mode === 'note') return this.notes().find((note) => note.id === scope.noteId)?.title || 'Active Note';
    return `${scope.noteIds.length} notes`;
  });
  readonly filteredBuildNotes = computed(() => {
    const query = this.buildNoteQuery().trim().toLowerCase();
    const notes = this.notes();
    if (!query) return notes.slice(0, 24);
    return notes.filter((note) => note.title.toLowerCase().includes(query)).slice(0, 24);
  });

  readonly graphNodes = this.machine.graphNodes;
  readonly graphEdges = this.machine.graphEdges;
  readonly registryEntities = this.machine.registryEntities;
  readonly staleDocuments = this.machine.staleDocuments;
  readonly staleDocumentSamples = computed(() => this.graphAudit()?.staleDocumentSamples || []);
  readonly visibleStaleDocumentSamples = computed(() => this.staleDocumentSamples().slice(0, 3));
  readonly graphIssueCount = this.machine.graphIssueCount;
  readonly duplicateEdgeSamples = computed(() => this.graphAudit()?.duplicateEdgeSamples.slice(0, 3) || []);
  readonly orphanEdgeSamples = computed(() => this.graphAudit()?.orphanEdgeSamples.slice(0, 3) || []);
  readonly hasCommittedGraph = this.machine.hasCommittedGraph;
  readonly selectedModelDefinition = computed(() =>
    this.models.find((model) => model.id === this.selectedModel()) || this.models[0]
  );
  readonly embeddingsReady = computed(() => this.vectorStatus() === 'ready');
  readonly activeEmbeddingDimensionLabel = computed(() => {
    return `${this.selectedModelDefinition().dims}d`;
  });
  readonly headerSubtitle = computed(() => {
    const labels = this.enabledLaneLabels();
    return labels.length ? labels.join(' + ') : 'Lexical retrieval';
  });
  readonly buildScopeNotesForEstimate = computed(() => {
    const hydrated = this.hydratedBuildScopeNotes();
    return hydrated.length ? hydrated : this.scopedNotes();
  });
  readonly vectorRouteLabel = computed(() =>
    this.embeddingsReady() ? 'Native Rust semantic runner ready' : 'Native Rust semantic runner idle'
  );
  readonly scopeLabel = computed(() => {
    const scope = this.selectedBuildScope();
    if (scope.mode === 'global') return 'Global (all notes)';
    if (scope.mode === 'folder') return this.folders().find((folder) => folder.id === scope.folderId)?.name || scope.folderId;
    if (scope.mode === 'note') return this.notes().find((note) => note.id === scope.noteId)?.title || 'Active note';
    return `${scope.noteIds.length} selected notes`;
  });
  readonly commandStatus = computed(() => buildAtlasCommandStatus({
    scopeLabel: this.scopeLabel(),
    noteCount: this.scopedNotes().length,
    estimatedChunks: estimateDynamicChunks(this.buildScopeNotesForEstimate()),
    audit: this.graphAudit(),
    stages: this.machineStages(),
    activeJob: this.activeJob(),
    lastSummary: this.lastSummary(),
    lastRichScan: this.lastAtlasResult()?.nativeResult || null,
    vectorStatus: this.vectorStatus(),
    graphStatus: this.graphStatus(),
    manifoldMode: this.machine.manifoldMode(),
    manifoldStatus: this.machine.manifoldStatus(),
    manifoldStatuses: this.machine.manifoldStatuses(),
    dynamicNerStatus: this.dynamicNerLabel(),
    enabledLanes: this.enabledLanes(),
    embeddingModelLabel: this.currentModelLabel(),
    embeddingDimensionLabel: this.activeEmbeddingDimensionLabel(),
  }));
  readonly ledgerGroups = computed(() => this.commandStatus().ledgerGroups);
  readonly inventoryMetrics = computed(() => this.commandStatus().metrics);
  readonly pipelineStages = computed(() => this.commandStatus().stages);
  readonly capabilityLayers = computed(() => this.commandStatus().capabilityLayers);
  readonly sleepingCapabilities = computed(() => this.commandStatus().sleepingCapabilities);
  readonly sidecarMetrics = computed(() => this.commandStatus().sidecars);
  readonly chunkingStatus = computed(() => this.commandStatus().chunking);
  readonly lastRunStatus = computed(() => {
    const fullAtlasReceipt = this.fullAtlasPipeline.lastReceipt();
    if (fullAtlasReceipt) {
      return {
        label: graphIndexReceiptLabel(fullAtlasReceipt),
        detail: fullAtlasReceipt.message,
        durationMs: fullAtlasReceipt.durationMs,
      };
    }
    const receipt = this.atlasRuntime.lastBuildReceipt();
    if (receipt) {
      return {
        label: receipt.label,
        detail: buildReceiptDetail(receipt),
        durationMs: receipt.durationMs,
      };
    }
    return this.commandStatus().lastRun;
  });
  readonly lastRunReceiptRows = computed(() =>
    buildLastRunReceiptRows(this.fullAtlasPipeline.lastReceipt())
  );
  readonly selectedEmbeddingStageLanes = signal<GraphRebuildSignalTargetLane[]>(
    EMBEDDING_STAGE_LANES.map((lane) => lane.id)
  );
  readonly entityLinkerStageEnabled = signal(true);
  readonly enabledPostprocessStageCount = computed(() =>
    this.selectedEmbeddingStageLanes().length + (this.entityLinkerStageEnabled() ? 1 : 0)
  );
  readonly embeddingStageControls = computed(() => {
    const selected = new Set(this.selectedEmbeddingStageLanes());
    return EMBEDDING_STAGE_LANES.map((lane) => ({
      ...lane,
      enabled: selected.has(lane.id),
    }));
  });
  readonly postprocessStaging = computed(() =>
    buildPostprocessStagingView(this.fullAtlasPipeline.lastSnapshot(), this.fullAtlasPipeline.lastReceipt())
  );
  readonly graphAwareLinkSuggestionTotal = computed(() =>
    this.fullAtlasPipeline.lastSnapshot()?.counters.graphAwareLinkSuggestions
      ?? this.fullAtlasPipeline.lastReceipt()?.counters.graphAwareLinkSuggestions
      ?? this.fullAtlasPipeline.lastSnapshot()?.graphAwareLinkSuggestions?.length
      ?? 0
  );
  readonly graphAwareLinkSuggestions = computed(() =>
    (this.fullAtlasPipeline.lastSnapshot()?.graphAwareLinkSuggestions || [])
      .filter((suggestion) => !this.linkSuggestionDecisions()[this.linkSuggestionDecisionKey(suggestion)])
  );
  readonly graphAwareLinkSuggestionCount = computed(() => this.graphAwareLinkSuggestions().length);
  readonly entityLinkSuggestionTotal = computed(() =>
    this.fullAtlasPipeline.lastSnapshot()?.counters.shadowLinkSuggestions
      ?? this.fullAtlasPipeline.lastSnapshot()?.counters.entityLinkSuggestions
      ?? this.fullAtlasPipeline.lastReceipt()?.counters.entityLinkSuggestions
      ?? this.fullAtlasPipeline.lastSnapshot()?.shadowLinkSuggestions?.length
      ?? this.fullAtlasPipeline.lastSnapshot()?.entityLinkSuggestions?.length
      ?? 0
  );
  readonly entityLinkSuggestions = computed(() =>
    (this.fullAtlasPipeline.lastSnapshot()?.shadowLinkSuggestions
      || this.fullAtlasPipeline.lastSnapshot()?.entityLinkSuggestions
      || []).slice(0, 12)
  );
  readonly reviewClusters = computed<ProductDiagnosticsReviewCluster[]>(() =>
    buildReviewClusterViews(this.fullAtlasPipeline.lastSnapshot())
  );
  readonly compilerWorkbench = computed<CompilerWorkbenchView | null>(() =>
    buildCompilerWorkbenchView(
      this.fullAtlasPipeline.lastSnapshot(),
      this.fullAtlasPipeline.lastReceipt(),
      this.postprocessStaging(),
      this.reviewClusters(),
      this.graphAwareLinkSuggestions(),
      this.activeCompilerQueue(),
      this.compilerQueueDecisions(),
      this.linkSuggestionDecisions(),
      this.selectedEmbeddingStageLanes(),
      this.entityLinkerStageEnabled(),
    )
  );
  readonly stage8Workbench = computed<Stage8WorkbenchView>(() =>
    buildStage8WorkbenchView(
      this.fullAtlasPipeline.lastSnapshot(),
      this.fullAtlasPipeline.lastReceipt(),
      this.currentModelLabel(),
      this.activeEmbeddingDimensionLabel(),
      this.vectorStatus(),
      this.dynamicNerLabel(),
      this.reviewClusters(),
      this.graphAwareLinkSuggestions(),
    )
  );
  readonly selectedRecipePlan = computed(() => this.atlasRuntime.recipeState(this.selectedRecipe(), this.atlasRunOptions()));
  readonly selectedCapability = computed(() => atlasCapabilityById(this.selectedCapabilityId()));
  readonly selectedCapabilityState = computed(() =>
    this.atlasRuntime.capabilityState(this.selectedCapabilityId(), this.atlasRunOptions())
  );
  readonly selectedCapabilityChain = computed(() =>
    this.selectedCapabilityIds().map((id) => ({
      capability: atlasCapabilityById(id),
      state: this.atlasRuntime.capabilityState(id, this.atlasRunOptions()),
    }))
  );
  readonly selectedPipelineRail = computed(() => this.buildSelectedPipelineRail());
  readonly runtimeCapabilities = computed(() =>
    ATLAS_CAPABILITY_REGISTRY.map((capability) => this.atlasRuntime.capabilityState(capability.id, this.atlasRunOptions()))
  );
  readonly blockedRuntimeCapabilities = computed(() =>
    this.runtimeCapabilities().filter((capability) => !capability.runnable || capability.blockedReason)
  );
  readonly modelLaneViews = computed(() => {
    const statuses = this.nerStatus();
    const coOccurrence = statuses.fst;
    return buildAtlasModelLaneViews({
      dynamicNerStatus: this.dynamicNerLabel(),
      coOccurrenceReady: coOccurrence.ready,
      coOccurrenceLoading: coOccurrence.loading,
      coOccurrenceError: coOccurrence.error,
      vectorStatus: this.vectorStatus(),
      semanticReady: this.embeddingsReady() || this.vectorStatus() === 'ready',
      semanticDetail: `${this.currentModelLabel()} ${this.activeEmbeddingDimensionLabel()}`,
      nliInitialized: this.nli.isInitialized(),
      nliProcessing: this.nli.isProcessing(),
      nliModelId: this.nli.modelId(),
      manifoldStatuses: this.machine.manifoldStatuses(),
    });
  });
  readonly fullAtlasRequest = computed<GraphIndexRunRequest>(() => ({
    scope: this.graphIndexScope(),
    policy: this.buildPolicy() === 'force' ? 'force' : 'delta',
    modelSelection: {
      dynamicNerId: 'dynamic_ner',
      embeddingModelId: this.selectedModel(),
      embeddingModelLabel: this.currentModelLabel(),
      embeddingDimensionLabel: this.activeEmbeddingDimensionLabel(),
      nliModelId: this.nli.modelId() || 'onnx-community/ModernBERT-base-nli',
    },
    embeddingStagePolicy: {
      enabledLanes: this.selectedEmbeddingStageLanes(),
      entityLinkerEnabled: this.entityLinkerStageEnabled(),
    },
    calendarRegistrySnapshot: this.calendar.calendarRegistrySnapshot(),
    entities: smartGraphRegistry.getAllEntities(),
  }));
  readonly fullAtlasModelReadiness = computed(() => this.fullAtlasPipeline.modelReadiness(this.fullAtlasRequest()));
  readonly fullAtlasModelsReady = computed(() => this.fullAtlasPipeline.modelsReady(this.fullAtlasRequest()));
  readonly fullAtlasCoreReady = computed(() => this.fullAtlasPipeline.coreModelsReady(this.fullAtlasRequest()));
  readonly fullAtlasBusy = this.fullAtlasPipeline.running;
  readonly recipeLifecycle = computed(() => buildAtlasRecipeLifecycle(
    this.activeRecipeStep(),
    this.completedRecipeSteps(),
    this.failedRecipeStep(),
  ));
  readonly pipelineStateLabel = computed(() => {
    const activeJob = this.activeJob();
    if (activeJob && activeJob !== 'manifold-load' && activeJob !== 'graph-focus') return 'running';
    if (this.error()) return 'error';
    const statuses = Object.values(this.machineStages()).map((stage) => stage.status);
    if (statuses.includes('error')) return 'error';
    if (statuses.includes('running')) return 'running';
    if (statuses.includes('queued')) return 'queued';
    if (statuses.includes('dirty')) return 'dirty';
    if (statuses.includes('ready') || this.graphStatus() === 'ready') return 'ready';
    return 'idle';
  });
  readonly dynamicNerLabel = computed(() => {
    const status = this.nerStatus().dynamic_ner;
    if (this.isDynamicScanning()) return 'running';
    if (status.loading) return 'warming';
    if (status.error) return 'error';
    return status.ready ? 'ready' : 'cold';
  });
  ngOnInit(): void {
    this.notesService.getAllNotes$()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((notes) => {
        this.notes.set(notes.map((note) => ({
          id: note.id,
          title: note.title || 'Untitled',
          content: note.markdownContent || note.content || '',
          narrativeId: note.narrativeId || '',
          folderId: note.folderId || '',
          hasBody: !!note.hasBody,
        })));
        this.queueBuildScopeHydration();
      });

    this.notesService.getAllFolders$()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((folders) => {
        this.folders.set(folders.map((folder) => ({ id: folder.id, name: folder.name })));
      });

    void this.hydrateUiState();
  }

  async handleSearch(): Promise<void> {
    const query = this.query().trim();
    if (!query) {
      this.results.set([]);
      this.notice.set(null);
      this.error.set(null);
      return;
    }

    this.isSearching.set(true);
    this.notice.set(null);
    this.error.set(null);
    const start = performance.now();

    try {
      await this.runUnifiedSearch();
      this.searchTime.set(Math.round(performance.now() - start));
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    } finally {
      this.isSearching.set(false);
    }
  }

  toggleLane(lane: RetrievalLane): void {
    this.machine.toggleLane(lane);
    if (lane === 'graph') {
      void this.machine.refreshAuditSafe();
    }
  }

  toggleEmbeddingStageLane(lane: GraphRebuildSignalTargetLane): void {
    this.selectedEmbeddingStageLanes.update((lanes) =>
      lanes.includes(lane)
        ? lanes.filter((current) => current !== lane)
        : [...lanes, lane]
    );
  }

  toggleEntityLinkerStage(): void {
    this.entityLinkerStageEnabled.update((enabled) => !enabled);
  }

  onScopeChange(scope: 'global' | string): void {
    this.machine.setScope(scope || 'global');
    void this.machine.refreshAuditSafe();
  }

  setBuildScopeMode(mode: AtlasBuildScope['mode']): void {
    this.buildScopeMode.set(mode);
    if (mode === 'global') {
      this.machine.setScope('global');
      void this.machine.refreshAuditSafe();
      this.queueBuildScopeHydration();
      return;
    }
    if (mode === 'folder') {
      const folderId = this.selectedBuildFolderId() || this.folders()[0]?.id || '';
      if (folderId) {
        this.selectedBuildFolderId.set(folderId);
        this.machine.setScope(folderId);
        void this.machine.refreshAuditSafe();
      }
      this.queueBuildScopeHydration();
      return;
    }
    if (mode === 'note') {
      const noteId = this.noteStore.currentNote()?.id || this.notes()[0]?.id || '';
      if (noteId) this.selectedBuildNoteIds.set([noteId]);
      this.queueBuildScopeHydration();
      return;
    }
    if (!this.selectedBuildNoteIds().length) {
      const noteId = this.noteStore.currentNote()?.id || this.notes()[0]?.id || '';
      if (noteId) this.selectedBuildNoteIds.set([noteId]);
    }
    this.queueBuildScopeHydration();
  }

  onBuildFolderChange(folderId: string): void {
    this.selectedBuildFolderId.set(folderId);
    this.buildScopeMode.set('folder');
    this.machine.setScope(folderId || 'global');
    void this.machine.refreshAuditSafe();
    this.queueBuildScopeHydration();
  }

  toggleBuildNote(noteId: string): void {
    if (!noteId) return;
    if (this.buildScopeMode() === 'note') {
      this.selectedBuildNoteIds.set([noteId]);
      return;
    }
    this.buildScopeMode.set('multiNote');
    this.selectedBuildNoteIds.update((ids) =>
      ids.includes(noteId) ? ids.filter((id) => id !== noteId) : [...ids, noteId],
    );
    this.queueBuildScopeHydration();
  }

  isBuildNoteSelected(noteId: string): boolean {
    return this.buildNoteIds().includes(noteId);
  }

  setBuildPolicy(policy: 'dirty-only' | 'force'): void {
    this.buildPolicy.set(policy);
  }

  async loadVectorModel(): Promise<void> {
    try {
      await this.machine.loadSemanticModel(
        this.selectedModel(),
        this.currentModelLabel(),
        this.activeEmbeddingDimensionLabel()
      );
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    }
  }

  async indexVectorNotes(): Promise<void> {
    if (this.vectorStatus() !== 'ready' && this.vectorStatus() !== 'error') return;
    try {
      const notes = await this.loadScopedNotesWithBodies();
      await this.machine.indexSemanticDocuments(notes.map((note) => ({
        id: note.id,
        narrativeId: note.narrativeId,
        title: note.title,
        content: note.content,
      })));
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    }
  }

  async loadFullAtlasModels(): Promise<void> {
    if (this.fullAtlasBusy()) return;
    this.error.set(null);
    try {
      await this.fullAtlasPipeline.loadModels(this.fullAtlasRequest());
      this.notice.set('Full Atlas Index models are warm. No graph data was built.');
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    }
  }

  async warmFullAtlasModel(modelId: GraphIndexModelReadiness['id'], optional = false): Promise<void> {
    if (!optional || this.fullAtlasBusy()) return;
    this.error.set(null);
    try {
      await this.fullAtlasPipeline.warmOptionalModel(modelId);
      this.notice.set('Optional Entity Linker lane is staged. No graph data was built.');
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    }
  }

  async buildFullAtlas(): Promise<void> {
    await this.buildCoreAtlas();
  }

  async buildCoreAtlas(): Promise<void> {
    if (this.isFullAtlasBuildDisabled()) return;
    this.error.set(null);
    try {
      const result = await this.fullAtlasPipeline.buildCoreGraph({
        ...this.fullAtlasRequest(),
        postProcessMode: 'core',
      });
      this.notice.set(result.receipt.message);
      this.openGraphLens();
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    }
  }

  async postProcessAtlas(): Promise<void> {
    if (this.isPostProcessDisabled()) return;
    this.error.set(null);
    try {
      const result = await this.fullAtlasPipeline.postProcessAtlas({
        ...this.fullAtlasRequest(),
        postProcessMode: 'full',
      });
      this.notice.set(result.receipt.message);
      this.openGraphLens();
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    }
  }

  isFullAtlasBuildDisabled(): boolean {
    return this.fullAtlasBusy() || !this.fullAtlasCoreReady() || !this.hasRunnableBuildScope();
  }

  isPostProcessDisabled(): boolean {
    return this.fullAtlasBusy() || !this.fullAtlasModelsReady() || !this.hasRunnableBuildScope();
  }

  fullAtlasBuildButtonLabel(): string {
    if (this.fullAtlasBusy()) return 'Building Core';
    if (!this.fullAtlasCoreReady()) return 'Load NER First';
    return this.buildPolicy() === 'force' ? 'Force Build Core' : 'Build Clean Graph';
  }

  postProcessButtonLabel(): string {
    if (this.fullAtlasBusy()) return 'Working';
    if (!this.fullAtlasModelsReady()) return 'Load Models First';
    return this.buildPolicy() === 'force' ? 'Force Postprocess' : 'Postprocess';
  }

  loadModelsButtonLabel(): string {
    if (this.fullAtlasBusy()) return 'Working';
    return this.fullAtlasModelsReady() ? 'Models Warm' : 'Load Models';
  }

  async runEntitySuggestionStage(): Promise<void> {
    if (this.isRunNerDisabled()) return;
    await this.runAtlasRecipe('runNer', { preserveSelection: true });
  }

  isRunNerDisabled(): boolean {
    return this.isRecipeDisabled('runNer');
  }

  nerSuggestionsButtonLabel(): string {
    if (this.isRecipeBusy('runNer')) return 'Scanning NER';
    if (!this.hasRunnableBuildScope()) return 'Pick Scope';
    return 'Run NER';
  }

  modelReadinessTone(status: string): string {
    if (status === 'ready') return 'ready';
    if (status === 'warming' || status === 'running') return 'running';
    if (status === 'error') return 'error';
    return 'idle';
  }

  async runAtlasRecipe(recipeId: AtlasRecipeId, options: { preserveSelection?: boolean } = {}): Promise<void> {
    if (this.activeRecipe()) return;
    if (options.preserveSelection) {
      this.resetRecipeProgress();
    } else {
      this.applyRecipeSelection(recipeId);
    }
    this.activeRecipe.set(recipeId);
    this.error.set(null);
    try {
      const options = this.atlasRunOptions();
      const plan = this.atlasRuntime.recipePlan(recipeId, options);
      this.beginRecipeStep('scope');
      this.completeRecipeStep('scope');
      this.beginRecipeStep('warm');
      await this.atlasRuntime.warmRequiredModels(plan, options);
      this.completeRecipeStep('warm');
      this.beginRecipeStep('run');
      await this.atlasRuntime.runRecipe(recipeId, { ...options, skipModelWarm: true });
      this.completeRecipeStep('run');
      this.beginRecipeStep('refresh');
      this.completeRecipeStep('refresh');
    } catch (err) {
      this.failRecipeStep(this.activeRecipeStep() || 'run');
      this.error.set(this.toErrorMessage(err));
    } finally {
      this.activeRecipe.set(null);
      this.activeRecipeStep.set(null);
    }
  }

  openGraphLens(): void {
    const scope = this.selectedBuildScope();
    const noteIds = noteIdsFromBuildScope(scope);
    this.machine.requestGraphFocus({
      query: this.query().trim(),
      scope: scope.mode === 'folder' ? scope.folderId : 'global',
      noteId: noteIds[0],
      title: noteIds.length > 1 ? `${noteIds.length} selected notes` : this.buildScopeLabel(),
    });
    this.hubService.openPage('graph');
  }

  openResult(result: SearchResultView): void {
    this.noteStore.openNote(result.noteId);
  }

  showResultInGraph(event: Event, result: SearchResultView): void {
    event.stopPropagation();
    this.machine.requestGraphFocus({
      query: this.query().trim() || result.title,
      scope: this.indexScope(),
      noteId: result.noteId,
      title: result.title,
    });
    this.hubService.openPage('graph');
  }

  formatScore(score: number): string {
    if (score <= 1) return `${(score * 100).toFixed(1)}%`;
    return score.toFixed(2);
  }

  laneLabel(lane: RetrievalLane): string {
    return this.laneOptions.find((option) => option.id === lane)?.label || lane;
  }

  laneIcon(lane: RetrievalLane): string {
    return this.laneOptions.find((option) => option.id === lane)?.icon || 'lucideSparkles';
  }

  vectorStatusLabel(): string {
    if (this.embeddingsReady() && this.vectorStatus() === 'idle') {
      return this.activeEmbeddingDimensionLabel();
    }

    switch (this.vectorStatus()) {
      case 'loading':
        return 'Loading';
      case 'ready':
        return this.activeEmbeddingDimensionLabel();
      case 'indexing':
        return 'Indexing';
      case 'error':
        return 'Error';
      default:
        return 'Idle';
    }
  }

  countLabel(value: number | null): string {
    return value === null ? 'unavailable' : value.toLocaleString();
  }

  modelRequirementLabel(models: AtlasModelRequirement[]): string {
    return this.atlasRuntime.modelRequirementLabel(models);
  }

  serviceRequirementLabel(services: AtlasServiceRequirement[]): string {
    return this.atlasRuntime.serviceRequirementLabel(services);
  }

  expectedOutputLabel(outputs: AtlasExpectedOutput[]): string {
    return this.atlasRuntime.expectedOutputLabel(outputs);
  }

  capabilityRuntimeLabel(state: AtlasCapabilityRuntimeState): string {
    return ATLAS_CAPABILITY_REGISTRY.find((capability) => capability.id === state.capabilityId)?.label || state.capabilityId;
  }

  trackCapabilityGroup(_index: number, group: BuilderCapabilityGroup): string {
    return group.id;
  }

  trackCapabilityTarget(_index: number, target: BuilderCapabilityCard): AtlasCapabilityId {
    return target.capability.id;
  }

  selectCapability(capabilityId: AtlasCapabilityId): void {
    if (this.activeRecipe()) return;
    this.preserveWorkbenchScroll(() => {
      const recipeId = recipeForCapability(capabilityId);
      this.selectedCapabilityId.set(capabilityId);
      this.selectedRecipe.set(recipeId);
      this.selectedCapabilityIds.set(capabilityIdsForRecipe(recipeId, capabilityId));
      this.resetRecipeProgress();
    });
  }

  isCapabilitySelected(capabilityId: AtlasCapabilityId): boolean {
    return this.selectedCapabilityIds().includes(capabilityId);
  }

  toggleCapabilityGroup(groupId: string): void {
    this.preserveWorkbenchScroll(() => {
      this.collapsedCapabilityGroups.update((ids) =>
        ids.includes(groupId) ? ids.filter((id) => id !== groupId) : [...ids, groupId],
      );
    });
  }

  isCapabilityGroupCollapsed(groupId: string): boolean {
    return this.collapsedCapabilityGroups().includes(groupId);
  }

  selectRecipe(recipeId: AtlasRecipeId): void {
    if (this.activeRecipe()) return;
    this.preserveWorkbenchScroll(() => {
      this.applyRecipeSelection(recipeId);
    });
  }

  private applyRecipeSelection(recipeId: AtlasRecipeId): void {
    this.selectedRecipe.set(recipeId);
    this.selectedCapabilityId.set(capabilityForRecipe(recipeId));
    this.selectedCapabilityIds.set(capabilityIdsForRecipe(recipeId));
    this.resetRecipeProgress();
  }

  private preserveWorkbenchScroll(update: () => void): void {
    const scrollContainer = this.workbenchScroll?.nativeElement;
    const scrollTop = scrollContainer?.scrollTop ?? 0;
    update();
    if (!scrollContainer) return;

    const restore = () => {
      scrollContainer.scrollTop = scrollTop;
    };
    queueMicrotask(restore);
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(restore);
    }
  }

  async runSelectedRecipe(): Promise<void> {
    await this.runAtlasRecipe(this.selectedRecipe());
  }

  async warmSelectedRecipeModels(): Promise<void> {
    if (this.activeRecipe()) return;
    const recipeId = this.selectedRecipe();
    this.activeRecipe.set(recipeId);
    this.resetRecipeProgress();
    this.error.set(null);
    try {
      this.beginRecipeStep('scope');
      this.completeRecipeStep('scope');
      this.beginRecipeStep('warm');
      await this.prepareRecipeModels(recipeId);
      this.completeRecipeStep('warm');
      this.notice.set(`${this.selectedRecipePlan().label} required runtime models are warm. No graph data was mutated.`);
    } catch (err) {
      this.failRecipeStep(this.activeRecipeStep() || 'warm');
      this.error.set(this.toErrorMessage(err));
    } finally {
      this.activeRecipe.set(null);
      this.activeRecipeStep.set(null);
    }
  }

  async warmModelLaneFromCard(laneId: AtlasModelLaneId): Promise<void> {
    if (this.activeRecipe() || this.activeLaneWarm() || laneId === 'manifoldProjection') return;
    this.error.set(null);
    this.activeLaneWarm.set(laneId);
    try {
      await this.atlasRuntime.warmModelLane(laneId, this.atlasRunOptions());
      this.notice.set(`${laneListLabel([laneId])} is warm.`);
    } catch (err) {
      this.error.set(this.toErrorMessage(err));
    } finally {
      this.activeLaneWarm.set(null);
    }
  }

  laneCardActionLabel(laneId: AtlasModelLaneId, status: string): string {
    if (this.activeLaneWarm() === laneId) return 'warming';
    if (laneId === 'manifoldProjection') return 'read-only';
    return status === 'ready' ? 'warm' : 'click to warm';
  }

  linkSuggestionKindLabel(kind: GraphRebuildLinkSuggestion['kind']): string {
    switch (kind) {
      case 'bridge_review': return 'Bridge';
      case 'hub_affiliation': return 'Hub';
      case 'backbone_promotion': return 'Backbone';
      case 'missing_triangle': return 'Triangle';
      case 'suspicious_leaf': return 'Leaf';
    }
  }

  linkSuggestionTitle(suggestion: GraphRebuildLinkSuggestion): string {
    return `${this.compactEntityId(suggestion.sourceEntityId)} -> ${this.compactEntityId(suggestion.targetEntityId)}`;
  }

  entityLinkDecisionLabel(decision: GraphRebuildEntityLinkSuggestion['decision']): string {
    switch (decision) {
      case 'same_entity': return 'Same';
      case 'alias_of': return 'Alias';
      case 'new_entity': return 'New';
      case 'ambiguous': return 'Review';
      case 'reject': return 'Reject';
    }
  }

  entityLinkTitle(suggestion: GraphRebuildEntityLinkSuggestion): string {
    const target = suggestion.candidateLabel || suggestion.candidateEntityId || 'new entity';
    return `${suggestion.surface} -> ${target}`;
  }

  shadowLinkKindLabel(suggestion: GraphRebuildEntityLinkSuggestion): string {
    const kind = (suggestion as Partial<GraphRebuildShadowLink>).shadowKind;
    switch (kind) {
      case 'bundle_dedupe': return 'bundle dedupe';
      case 'alias_suspicion': return 'alias suspicion';
      case 'same_entity_suspicion': return 'same entity';
      case 'relation_duplicate_suspicion': return 'relation duplicate';
      case 'cluster_hint': return 'cluster hint';
      case 'query_assist': return 'query assist';
      default: return suggestion.status;
    }
  }

  compilerToneClass(tone: CompilerTone): string {
    return `compiler-tone-${tone}`;
  }

  setCompilerQueue(queueId: CompilerQueueId): void {
    this.activeCompilerQueue.set(queueId);
  }

  runCompilerQueueAction(item: CompilerQueueItemView, slot: 'primary' | 'secondary', event?: Event): void {
    event?.stopPropagation();
    const action = slot === 'primary' ? item.primaryAction : item.secondaryAction;
    if (!action) return;
    if (action === 'accept-link' || action === 'reject-link') {
      const suggestion = this.fullAtlasPipeline.lastSnapshot()?.graphAwareLinkSuggestions
        ?.find((row) => `graph-link:${row.id}` === item.id || row.id === item.id);
      if (!suggestion) return;
      if (action === 'accept-link') this.acceptLinkSuggestion(suggestion, event);
      else this.rejectLinkSuggestion(suggestion, event);
      return;
    }
    if (action === 'toggle-lane') {
      const laneId = item.id.replace(/^lane:/, '') as GraphRebuildSignalTargetLane | 'entity_linker';
      if (laneId === 'entity_linker') this.toggleEntityLinkerStage();
      else this.toggleEmbeddingStageLane(laneId);
      return;
    }
    const decision: CompilerQueueDecision =
      action === 'apply-patch' ? 'applied'
        : action === 'revert-patch' ? 'reverted'
          : action === 'promote' ? 'promoted'
            : 'dismissed';
    this.compilerQueueDecisions.update((decisions) => ({ ...decisions, [item.id]: decision }));
    this.notice.set(`${item.label}: ${compilerDecisionLabel(decision)}.`);
  }

  acceptLinkSuggestion(suggestion: GraphRebuildLinkSuggestion, event?: Event): void {
    event?.stopPropagation();
    smartGraphRegistry.createEdge(
      suggestion.sourceEntityId,
      suggestion.targetEntityId,
      suggestion.suggestedRelationType,
      {
        weight: suggestion.confidence,
        provenance: 'manual',
        attributes: {
          source: 'graph_aware_link_suggestion',
          suggestionId: suggestion.id,
          kind: suggestion.kind,
          semanticStatus: suggestion.semanticStatus,
          structuralRole: suggestion.structuralRole,
          embeddingRole: suggestion.embeddingRole,
          rerankScore: suggestion.rerankScore,
          rerankSignals: suggestion.rerankSignals,
          evidenceIds: suggestion.evidenceIds,
        },
      },
    );
    this.setLinkSuggestionDecision(suggestion, 'accepted');
    this.notice.set(`Accepted graph-aware link: ${this.linkSuggestionTitle(suggestion)}`);
  }

  rejectLinkSuggestion(suggestion: GraphRebuildLinkSuggestion, event?: Event): void {
    event?.stopPropagation();
    this.setLinkSuggestionDecision(suggestion, 'rejected');
    this.notice.set(`Rejected link review: ${this.linkSuggestionTitle(suggestion)}`);
  }

  confidencePercent(value: number): number {
    return Math.round(Math.max(0, Math.min(1, value)) * 100);
  }

  compactEntityId(id: string): string {
    return id.replace(/^entity:/, '').replace(/^e-/, '');
  }

  private setLinkSuggestionDecision(suggestion: GraphRebuildLinkSuggestion, decision: 'accepted' | 'rejected'): void {
    const key = this.linkSuggestionDecisionKey(suggestion);
    this.linkSuggestionDecisions.update((decisions) => ({ ...decisions, [key]: decision }));
  }

  private linkSuggestionDecisionKey(suggestion: GraphRebuildLinkSuggestion): string {
    return `${this.fullAtlasPipeline.lastSnapshot()?.id || 'latest'}:${suggestion.id}`;
  }

  isLaneCardDisabled(laneId: AtlasModelLaneId): boolean {
    return laneId === 'manifoldProjection' || !!this.activeRecipe() || !!this.activeLaneWarm();
  }

  laneListLabel(lanes: AtlasModelLaneId[]): string {
    return laneListLabel(lanes);
  }

  capabilityListLabel(capabilities: AtlasCapabilityId[]): string {
    return capabilityListLabel(capabilities);
  }

  buildScopeModeLabel(mode: AtlasBuildScope['mode']): string {
    switch (mode) {
      case 'global':
        return 'Global';
      case 'folder':
        return 'Folder';
      case 'note':
        return 'Active Note';
      case 'multiNote':
        return 'Multi-note';
    }
  }

  isRecipeBusy(recipeId: AtlasRecipeId): boolean {
    return this.activeRecipe() === recipeId || (!!this.activeJob() && this.activeRecipe() === recipeId);
  }

  capabilityStatusClass(state: AtlasCapabilityRuntimeState): string {
    return `capability-${state.status}`;
  }

  capabilityIconName(capability: AtlasCapability): string {
    switch (capability.family) {
      case 'surface':
        return 'lucideFileText';
      case 'entity':
        return 'lucideCpu';
      case 'graph':
      case 'manifold':
      case 'visualization':
        return 'lucideLayers';
      case 'semantic':
        return 'lucideMicrochip';
      case 'reasoning':
        return 'lucideSparkles';
      case 'retrieval':
        return 'lucideSearch';
    }
  }

  compactPolicyLabel(policy: string): string {
    switch (policy) {
      case 'dirty-only':
        return 'Dirty';
      case 'read-only':
        return 'RO';
      case 'warm-only':
        return 'Warm';
      case 'native-only':
        return 'Native';
      default:
        return policy;
    }
  }

  compactOperationLabel(kind: string): string {
    return kind
      .replace('richTextGraphScan', 'Rich')
      .replace('semanticAtlasScan', 'Semantic')
      .replace('dynamicNerScan', 'Dynamic')
      .replace('nativeStoreProbe', 'Native')
      .replace('nliAdjudication', 'NLI')
      .replace('manifoldSnapshot', 'Manifold')
      .replace('graphVisualization', 'Graph View')
      .replace('retrievalWalk', 'Retrieve')
      .replace('modelWarm', 'Model');
  }

  isRecipeDisabled(recipeId: AtlasRecipeId): boolean {
    const activeJob = this.activeJob();
    const blockingJob = activeJob && activeJob !== 'manifold-load' && activeJob !== 'graph-focus';
    return !!this.activeRecipe() || !!blockingJob || this.isDynamicScanning() || !this.hasRunnableBuildScope();
  }

  isWarmDisabled(): boolean {
    const activeJob = this.activeJob();
    const blockingJob = activeJob && activeJob !== 'manifold-load' && activeJob !== 'graph-focus';
    return !!this.activeRecipe() || !!blockingJob || !this.selectedRecipePlan().requiredModels.length;
  }

  selectedCapabilityModelSummary(): string {
    const models = this.selectedRecipePlan().requiredModels;
    const chain = this.selectedCapabilityChain().map((item) => item.capability.id);
    const labels = models.map((model) => model.dims ? `${model.label} ${model.dims}` : model.label);
    if (chain.includes('dynamicNer')) {
      labels.unshift('Native GLiNER BI-small auto-load');
    }
    if (!labels.length) return 'none';
    return Array.from(new Set(labels)).join(' / ');
  }

  warmButtonLabel(): string {
    const required = this.selectedRecipePlan().requiredModels;
    if (!required.length) return 'No Warm Needed';
    if (this.activeRecipeStep() === 'warm') return 'Warming';
    if (this.requiredRecipeModelsReady()) return 'Warmed';
    const ids = required.map((model) => model.id);
    if (ids.includes('semanticEmbedding') && ids.includes('nli')) return 'Warm Embedding + NLI';
    if (ids.includes('semanticEmbedding')) return 'Warm Embedding';
    if (ids.includes('dynamicNer')) return 'Warm Dynamic NER';
    return 'Warm Required';
  }

  warmButtonTone(): string {
    const required = this.selectedRecipePlan().requiredModels;
    if (!required.length) return 'warm-neutral';
    if (this.activeRecipeStep() === 'warm') return 'warm-running';
    return this.requiredRecipeModelsReady() ? 'warm-ready' : 'warm-required';
  }

  laneStatusLabel(lane: RetrievalLane): string {
    switch (lane) {
      case 'lexical':
        return 'Ready';
      case 'semantic':
        if (this.vectorStatus() === 'loading') return 'Loading';
        if (this.vectorStatus() === 'indexing') return 'Indexing';
        if (this.vectorStatus() === 'error') return 'Error';
        if (this.embeddingsReady() || this.vectorStatus() === 'ready') return 'Loaded';
        return 'Unavailable';
      case 'graph':
        return this.hasCommittedGraph() ? 'Ready' : 'Unavailable';
      case 'entities':
        return this.registryEntities() > 0 ? 'Ready' : 'Unavailable';
      case 'evidence':
        return this.graphEdges() > 0 ? 'Ready' : 'Unavailable';
    }
  }

  laneSourceLabel(lane: RetrievalLane): string {
    switch (lane) {
      case 'lexical':
        return 'source: scope notes';
      case 'semantic':
        return 'source: semantic sidecar';
      case 'graph':
        return 'source: committed graph';
      case 'entities':
        return 'source: registry';
      case 'evidence':
        return 'source: claims + support paths';
    }
  }

  emptyStateTitle(): string {
    if (this.isSearching()) return 'Searching workspace';
    if (!this.query().trim()) {
      return 'Search across the active sources';
    }
    return 'No results found';
  }

  emptyStateMessage(): string {
    if (this.isSearching()) {
      return 'Running the selected retrieval path against the current scope.';
    }
    if (!this.query().trim()) {
      return 'Lexical search is always on. Semantic and graph sources join when they are loaded and indexed.';
    }
    return 'Try a broader query, change the scope, or switch retrieval modes.';
  }

  private async runUnifiedSearch(): Promise<void> {
    const enabled = this.enabledLanes();
    if (enabled.includes('semantic') && this.vectorStatus() === 'idle') {
      this.notice.set('Semantic lane is selected but the local model is not loaded yet. Lexical retrieval still ran.');
    }
    if (enabled.includes('graph') && !this.hasCommittedGraph()) {
      this.notice.set('Graph lane is selected but this scope has no committed graph yet. Search stayed read-only.');
    }
    if (enabled.includes('graph') && this.hasCommittedGraph()) {
      this.graphStatus.set('searching');
    }
    const rawResults = await this.machine.search(this.query(), 60, this.buildScope());
    this.results.set(await this.mapGoResults(rawResults, this.resultSource(), enabled));
  }

  private async prepareRecipeModels(recipeId: AtlasRecipeId): Promise<void> {
    const options = this.atlasRunOptions();
    await this.atlasRuntime.warmRequiredModels(
      this.atlasRuntime.recipePlan(recipeId, options),
      options,
    );
  }

  private requiredRecipeModelsReady(): boolean {
    const required = this.selectedRecipePlan().requiredModels;
    if (!required.length) return false;
    return required.every((model) => model.readiness === 'ready');
  }

  private hasRunnableBuildScope(): boolean {
    const scope = this.selectedBuildScope();
    if (scope.mode === 'note') return !!scope.noteId;
    if (scope.mode === 'multiNote') return scope.noteIds.length > 0;
    if (scope.mode === 'folder') return !!scope.folderId;
    return true;
  }

  private buildSelectedPipelineRail(): Array<{ id: string; label: string; status: string }> {
    const rail: Array<{ id: string; label: string; status: string }> = [
      { id: 'scope', label: this.buildScopeLabel(), status: this.hasRunnableBuildScope() ? 'ready' : 'idle' },
    ];
    for (const item of this.selectedCapabilityChain()) {
      rail.push({
        id: item.capability.id,
        label: item.capability.label,
        status: item.state.status,
      });
    }
    return rail;
  }

  private resetRecipeProgress(): void {
    this.activeRecipeStep.set(null);
    this.completedRecipeSteps.set([]);
    this.failedRecipeStep.set(null);
  }

  private beginRecipeStep(step: AtlasRecipeLifecycleId): void {
    this.activeRecipeStep.set(step);
    this.failedRecipeStep.set(null);
  }

  private completeRecipeStep(step: AtlasRecipeLifecycleId): void {
    this.completedRecipeSteps.update((steps) => Array.from(new Set([...steps, step])));
    if (this.activeRecipeStep() === step) {
      this.activeRecipeStep.set(null);
    }
  }

  private failRecipeStep(step: AtlasRecipeLifecycleId): void {
    this.failedRecipeStep.set(step);
    this.activeRecipeStep.set(null);
  }

  private atlasRunOptions(): AtlasRunOptions {
    return {
      selectedModel: this.selectedModel(),
      selectedModelLabel: this.currentModelLabel(),
      dimensionLabel: this.activeEmbeddingDimensionLabel(),
      scope: this.indexScope(),
      buildScope: this.selectedBuildScope(),
      buildPolicy: this.buildPolicy(),
      noteIds: this.buildDocumentIdsForRun(),
      query: this.query().trim(),
    };
  }

  private graphIndexScope(): GraphIndexRunScope {
    const scope = this.selectedBuildScope();
    if (scope.mode === 'global') {
      return { kind: 'global', scopeId: 'global', label: 'Global', noteIds: this.buildDocumentIdsForRun() };
    }
    if (scope.mode === 'folder') {
      const label = this.folders().find((folder) => folder.id === scope.folderId)?.name || 'Folder';
      return { kind: 'folder', scopeId: `folder:${scope.folderId}`, label, noteIds: this.buildDocumentIdsForRun() };
    }
    if (scope.mode === 'note') {
      const label = this.notes().find((note) => note.id === scope.noteId)?.title || 'Active Note';
      return { kind: 'note', scopeId: `note:${scope.noteId}`, label, noteIds: scope.noteId ? [scope.noteId] : [] };
    }
    return {
      kind: 'multiNote',
      scopeId: `multi:${scope.noteIds.join('|') || 'none'}`,
      label: `${scope.noteIds.length} notes`,
      noteIds: scope.noteIds,
    };
  }

  private async mapGoResults(rawResults: any[], source: SearchMode, lanes: RetrievalLane[]): Promise<SearchResultView[]> {
    const allowedNoteIds = new Set(this.scopedNotes().map((note) => note.id));
    const baseResults = rawResults
      .map((result) => {
        const noteId = result.DocID || result.docID || result.id || '';
        return {
          noteId,
          score: result.Score || result.score || 0,
          source,
          sourceLabel: this.sourceLabel(source),
          meta: this.sourceMeta(source),
          lanes,
        };
      })
      .filter((result) => allowedNoteIds.has(result.noteId))
      .slice(0, 12);
    const noteMap = await this.loadNoteMapByIds(baseResults.map((result) => result.noteId));
    return baseResults.map((result) => {
      const note = noteMap.get(result.noteId);
      return {
        ...result,
        title: note?.title || 'Untitled',
        excerpt: buildSearchSnippet(note?.content || '', this.query()),
      };
    });
  }

  private buildDocumentIdsForRun(): string[] {
    const scope = this.selectedBuildScope();
    if (scope.mode === 'global') return [];
    if (scope.mode === 'folder') return this.scopedNotes().map((note) => note.id);
    return noteIdsFromBuildScope(scope);
  }

  private async hydrateUiState(): Promise<void> {
    await this.machine.refreshAuditSafe();
  }

  private sourceLabel(source: SearchMode): string {
    if (source === 'graph') return 'Unified graph';
    if (source === 'vector') return 'Unified semantic';
    return 'Unified lexical';
  }

  private sourceMeta(source: SearchMode): string {
    if (source === 'graph') return 'Committed graph + lexical seeds';
    if (source === 'vector') return this.vectorRouteLabel();
    return 'Phoenix line search';
  }

  private resultSource(): SearchMode {
    const enabled = this.enabledLanes();
    if (enabled.includes('graph') && this.hasCommittedGraph()) return 'graph';
    if (enabled.includes('semantic') && this.embeddingsReady()) return 'vector';
    return 'notes';
  }

  private enabledLanes(): RetrievalLane[] {
    return this.machine.activeLanes();
  }

  private enabledLaneLabels(): string[] {
    return this.enabledLanes().map((lane) => this.laneLabel(lane));
  }

  private buildScope(): SearchScope | undefined {
    const scope = this.indexScope();
    if (scope === 'global') return undefined;
    return { folderId: scope, folderPath: scope };
  }

  private toErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  currentModelLabel(): string {
    return this.selectedModelDefinition().label;
  }

  private async loadScopedNotesWithBodies(): Promise<SearchPanelNote[]> {
    return this.loadNotesByIds(this.scopedNotes().map((note) => note.id));
  }

  private async hydrateBuildScopeNotes(notes: SearchPanelNote[]): Promise<void> {
    const generation = ++this.buildScopeHydrationGeneration;
    if (!notes.length) {
      this.hydratedBuildScopeNotes.set([]);
      return;
    }
    const ids = notes.map((note) => note.id).filter(Boolean);
    const hydrated = await this.loadNotesByIds(ids);
    if (generation !== this.buildScopeHydrationGeneration) return;
    const hydratedById = new Map(hydrated.map((note) => [note.id, note]));
    const merged: SearchPanelNote[] = [];
    for (const id of ids) {
      const note = hydratedById.get(id) || notes.find((candidate) => candidate.id === id);
      if (note) merged.push(note);
    }
    this.hydratedBuildScopeNotes.set(merged);
  }

  private queueBuildScopeHydration(): void {
    void this.hydrateBuildScopeNotes(this.scopedNotes());
  }

  private async loadNoteMapByIds(ids: string[]): Promise<Map<string, SearchPanelNote>> {
    const notes = await this.loadNotesByIds(ids);
    return new Map(notes.map((note) => [note.id, note]));
  }

  private async loadNotesByIds(ids: string[]): Promise<SearchPanelNote[]> {
    const uniqueIds = Array.from(new Set(ids.filter(Boolean)));
    if (!uniqueIds.length) {
      return [];
    }

    const cachedMap = new Map(this.notes().map((note) => [note.id, note]));
    const idsToLoad = uniqueIds.filter((id) => !cachedMap.get(id)?.hasBody);
    const loaded = idsToLoad.length > 0 ? await ops.getNotesByIds(idsToLoad) : [];
    const loadedMap = new Map(loaded.map((note) => [note.id, note]));

    return uniqueIds.map((id) => {
      const full = loadedMap.get(id);
      const cached = cachedMap.get(id);
      return {
        id,
        title: full?.title || cached?.title || 'Untitled',
        content: full?.markdownContent || full?.content || cached?.content || '',
        narrativeId: full?.narrativeId || cached?.narrativeId || '',
        folderId: full?.folderId || cached?.folderId || '',
        hasBody: !!full || !!cached?.hasBody,
      };
    });
  }
}

function noteIdsFromBuildScope(scope: AtlasBuildScope): string[] {
  if (scope.mode === 'note') return scope.noteId ? [scope.noteId] : [];
  if (scope.mode === 'multiNote') return scope.noteIds.filter(Boolean);
  return [];
}

const BUILDER_CAPABILITY_IDS: AtlasCapabilityId[] = [
  'dynamicSurface',
  'dynamicChunking',
  'dynamicNer',
  'mentionGraph',
  'evidenceGraph',
  'surfaceGraph',
  'assertedKernel',
  'relationGraph',
  'temporalGraph',
  'eventIdentity',
  'memoryState',
  'causalGraph',
  'semanticEmbedding',
  'semanticAtlas',
  'semanticCandidate',
  'nliAdjudication',
  'hybridManifold',
  'hopfProjection',
  'lorentzForest',
  'productManifold',
  'retrievalWalk',
  'galaxyVisualization',
];

function expandCapabilityChain(id: AtlasCapabilityId, seen = new Set<AtlasCapabilityId>()): AtlasCapabilityId[] {
  if (seen.has(id)) return [];
  seen.add(id);
  const capability = atlasCapabilityById(id);
  const chain = capability.dependencies.flatMap((dependency) => expandCapabilityChain(dependency, seen));
  return [...chain, id].filter((capabilityId, index, values) => values.indexOf(capabilityId) === index);
}

function capabilityIdsForRecipe(recipeId: AtlasRecipeId, focusCapabilityId?: AtlasCapabilityId): AtlasCapabilityId[] {
  const recipe = atlasRecipeDefinitionById(recipeId);
  const skipped = new Set(recipe.skippedCapabilities);
  const requiredChain = recipe.requiredCapabilities.flatMap((id) => expandCapabilityChain(id));
  const focusChain = focusCapabilityId ? expandCapabilityChain(focusCapabilityId) : [];
  const selected = new Set(requiredChain.filter((id) => !skipped.has(id)));
  for (const id of focusChain) {
    if (!skipped.has(id)) selected.add(id);
  }
  return BUILDER_CAPABILITY_IDS.filter((id) => selected.has(id));
}

function layerLabelForCapability(id: AtlasCapabilityId): string {
  return ATLAS_CAPABILITY_LAYERS.find((layer) => layer.capabilityIds.includes(id))?.label || atlasCapabilityById(id).family;
}

function recipeForCapability(id: AtlasCapabilityId): AtlasRecipeId {
  if (id === 'relationGraph' || id === 'temporalGraph' || id === 'eventIdentity' || id === 'memoryState' || id === 'causalGraph') {
    return 'reasoningGraph';
  }
  if (id === 'nliAdjudication') return 'adjudicatedSemanticGraph';
  if (id === 'semanticEmbedding' || id === 'semanticAtlas' || id === 'semanticCandidate') return 'semanticGraph';
  if (id === 'hybridManifold' || id === 'hopfProjection' || id === 'lorentzForest' || id === 'productManifold') return 'semanticGraph';
  return 'textGraph';
}

function capabilityForRecipe(id: AtlasRecipeId): AtlasCapabilityId {
  switch (id) {
    case 'semanticGraph':
      return 'semanticAtlas';
    case 'adjudicatedSemanticGraph':
      return 'nliAdjudication';
    case 'reasoningGraph':
      return 'relationGraph';
    case 'runNer':
      return 'dynamicNer';
    case 'textGraph':
      return 'assertedKernel';
  }
}

function buildReceiptDetail(receipt: AtlasBuildReceipt): string {
  const ranStages = receipt.stageReceipts.filter((stage) => stage.ran);
  const countText = `${ranStages.length} stage${ranStages.length === 1 ? '' : 's'} ran`;
  const proof = ranStages
    .map((stage) => stage.summary)
    .filter(Boolean)
    .slice(0, 2)
    .join(' / ');
  return proof ? `${receipt.policy}; ${countText}; ${proof}` : `${receipt.policy}; ${countText}`;
}

function buildLastRunReceiptRows(receipt: GraphIndexRunReceipt | null): LastRunReceiptRow[] {
  if (!receipt) return [];
  return [
    ...(receipt.stageReceipts || []).map(stageReceiptRow),
    ...(receipt.projectionReceipts || []).map(projectionReceiptRow),
  ];
}

function buildPostprocessStagingView(
  snapshot: GraphRebuildSnapshot | null,
  receipt: GraphIndexRunReceipt | null,
): PostprocessStagingView | null {
  if (snapshot?.embeddingTargetPlan?.lanes?.length) {
    const plan = snapshot.embeddingTargetPlan;
    const maxLane = Math.max(1, ...plan.lanes.map((lane) => lane.admitted));
    const lanes = plan.lanes
      .map((lane) => ({
        id: lane.lane,
        label: signalLaneLabel(lane.lane),
        admitted: lane.admitted,
        candidates: lane.candidates,
        deferred: lane.deferred,
        percent: Math.max(4, Math.min(100, (lane.admitted / maxLane) * 100)),
      }))
      .filter((lane) => lane.admitted > 0 || lane.candidates > 0 || zeroVisiblePostprocessLane(lane.id));
    const mode = receipt?.postProcessMode === 'full' ? 'budget' : 'plan';
    return {
      title: mode === 'budget' ? 'Lane Budget Matrix' : 'Lane Plan Matrix',
      mode,
      targets: plan.canonicalCount || plan.candidateCount,
      candidates: plan.candidateCount,
      deferred: plan.deferredCount,
      lanes,
    };
  }
  if (!receipt?.stageReceipts?.length) return null;
  const coverage = receipt.stageReceipts.find((stage) => stage.id === 'signalTargetCoverage');
  if (!coverage) return null;
  const counters = coverage.counters || {};
  const targets = counterValue(counters, 'targets') || receipt.counters.embeddingTargets || 0;
  const candidates = counterValue(counters, 'candidateTargets') || receipt.counters.embeddingTargetCandidates || targets;
  const deferred = counterValue(counters, 'deferredTargets') || receipt.counters.embeddingTargetDeferred || 0;
  const laneRows = [
    ['documentSpine', 'Document spine'],
    ['chunkSpine', 'Chunk spine'],
    ['entityAnchors', 'Entity anchors'],
    ['relationshipFacts', 'Relationship facts'],
    ['temporalFacts', 'Temporal facts'],
    ['causalFacts', 'Causal facts'],
    ['memoryStates', 'Memory states'],
    ['eventIdentities', 'Event identity'],
    ['anchorEvidence', 'Anchor evidence'],
    ['weakCooccurrence', 'Co-occurrence'],
  ] as const;
  const rawLanes = laneRows
    .map(([key, label]) => ({
      id: key,
      label,
      admitted: counterValue(counters, key),
      candidates: counterValue(counters, `${key}Candidates`) || counterValue(counters, key),
      deferred: counterValue(counters, `${key}Deferred`),
      percent: 0,
    }))
    .filter((lane) => lane.admitted > 0 || lane.candidates > 0 || zeroVisiblePostprocessLane(lane.id));
  const maxLane = Math.max(1, ...rawLanes.map((lane) => lane.admitted));
  const lanes = rawLanes.map((lane) => ({
    ...lane,
    percent: Math.max(4, Math.min(100, (lane.admitted / maxLane) * 100)),
  }));
  const mode = receipt.postProcessMode === 'full' ? 'budget' : 'plan';
  return { title: mode === 'budget' ? 'Lane Budget Matrix' : 'Lane Plan Matrix', mode, targets, candidates, deferred, lanes };
}

function buildStage8WorkbenchView(
  snapshot: GraphRebuildSnapshot | null,
  receipt: GraphIndexRunReceipt | null,
  modelLabel: string,
  dimensionLabel: string,
  vectorStatus: string,
  dynamicNerStatus: string,
  reviewClusters: ProductDiagnosticsReviewCluster[],
  graphLinks: GraphRebuildLinkSuggestion[],
): Stage8WorkbenchView {
  const counters = snapshot?.counters || receipt?.counters;
  const entityLinking = counters?.entityLinking;
  const shadowLinks = counters?.shadowLinkSuggestions
    ?? snapshot?.shadowLinkSuggestions?.length
    ?? counters?.entityLinkSuggestions
    ?? snapshot?.entityLinkSuggestions?.length
    ?? 0;
  const identityReviews = entityLinking?.candidateLinks ?? shadowLinks;
  const aliasPatches = (snapshot?.finalLinkPatchLog?.patches || []).filter((patch) => patch.kind === 'alias_of').length;
  const frameCount = (counters?.meaningFrameChunks ?? snapshot?.chunks.filter((chunk) => !!chunk.meaningFrame).length ?? 0)
    + (counters?.relationships ?? snapshot?.relationships.length ?? 0)
    + (counters?.events ?? snapshot?.events.length ?? 0);
  const evidenceCount = counters?.anchorEvidence ?? snapshot?.entityAnchors.length ?? 0;
  const resolution = counters?.resolution;
  const corefCount = snapshot?.resolutionSuggestions?.length
    ?? ((resolution?.ambiguousSurfaces || 0) + (resolution?.kindConflicts || 0) + (resolution?.possibleAliases || 0));
  const temporalCount = (counters?.temporalEdges ?? snapshot?.temporalEdges.length ?? 0)
    + (counters?.causalEdges ?? snapshot?.causalEdges.length ?? 0)
    + (counters?.memoryState ?? snapshot?.memoryState.length ?? 0);
  const beliefCount = (counters?.memoryState ?? snapshot?.memoryState.length ?? 0)
    + (counters?.eventAspects ?? snapshot?.events.filter((event) => !!event.aspect).length ?? 0);
  const embeddingTargets = counters?.embeddingTargets ?? snapshot?.embeddingTargets.length ?? 0;
  const embeddingVectors = counters?.embeddingVectors ?? snapshot?.embeddingVectors.length ?? 0;
  const receiptFailures = counters?.finalLinkReceiptFailures ?? snapshot?.finalLinkPatchLog?.counters.failedReceipts ?? 0;
  const routerStage = stage8RouterStage(receipt);
  const semanticReady = vectorStatus === 'ready'
    || receipt?.modelReadiness?.some((model) => model.id === 'semanticEmbedding' && model.status === 'ready')
    || false;
  const routerTone: CompilerTone = vectorStatus === 'error'
    ? 'danger'
    : semanticReady
      ? 'ready'
      : dynamicNerStatus === 'ready'
        ? 'review'
        : 'quiet';

  return {
    label: 'Stage 8 Quality Deck',
    detail: snapshot
      ? `${snapshot.nodes.length} nodes / ${snapshot.edges.length} edges / ${reviewClusters.length} review families`
      : 'Router and review lanes are staged for the next Full Atlas run',
    router: {
      model: modelLabel,
      dimension: dimensionLabel,
      status: semanticReady ? 'ready' : vectorStatus,
      detail: `${embeddingTargets.toLocaleString()} targets / ${embeddingVectors.toLocaleString()} vectors`,
      gate: 'lexical 0.48',
      budget: '24 windows',
      timing: routerStage ? `${routerStage.durationMs.toLocaleString()} ms` : 'pending',
      tone: routerTone,
    },
    lanes: [
      stage8Lane('identity', 'Identity', identityReviews, `${entityLinking?.sameEntity || 0} same / ${entityLinking?.ambiguous || 0} ambiguous`, identityReviews ? 'review' : 'quiet', 'identity'),
      stage8Lane('aliases', 'Aliases', counters?.aliases || 0, `${aliasPatches} alias patches / ${entityLinking?.aliasOf || 0} linker votes`, aliasPatches ? 'review' : 'ready', 'identity'),
      stage8Lane('frames', 'Frames', frameCount, `${counters?.relationships || 0} relations / ${counters?.events || 0} events`, frameCount ? 'ready' : 'quiet', 'bundles'),
      stage8Lane('evidence', 'Evidence', evidenceCount, `${counters?.mentions || 0} mentions / ${counters?.acceptedAnchors || 0} anchors`, evidenceCount ? 'ready' : 'quiet', 'receipts'),
      stage8Lane('coref', 'Coref', corefCount, `${resolution?.ambiguousSurfaces || 0} surfaces / ${resolution?.possibleAliases || 0} alias hints`, corefCount ? 'review' : 'quiet', 'identity'),
      stage8Lane('ontology', 'Ontology', counters?.entities || snapshot?.nodes.length || 0, `${snapshot?.nodes.length || counters?.nodes || 0} nodes / ${snapshot?.edges.length || counters?.edges || 0} edges`, counters?.entities ? 'ready' : 'quiet'),
      stage8Lane('temporal', 'Temporal', temporalCount, `${counters?.temporalEdges || 0} temporal / ${counters?.causalEdges || 0} causal`, temporalCount ? 'ready' : 'quiet', 'bundles'),
      stage8Lane('belief', 'Belief', beliefCount, `${counters?.memoryState || 0} memory / ${counters?.eventAspects || 0} aspects`, beliefCount ? 'ready' : 'quiet', 'bundles'),
      stage8Lane('router', 'Router', embeddingTargets, `${embeddingTargets} targets / ${embeddingVectors} vectors`, routerTone, 'lanes'),
    ],
    reviewItems: buildStage8ReviewItems(snapshot, reviewClusters, graphLinks),
    receipts: buildLastRunReceiptRows(receipt).slice(0, 4),
  };
}

function stage8RouterStage(receipt: GraphIndexRunReceipt | null): GraphIndexStageReceipt | undefined {
  return receipt?.stageReceipts.find((stage) => {
    const haystack = `${stage.id} ${stage.label}`.toLowerCase();
    return haystack.includes('router')
      || haystack.includes('semantic')
      || haystack.includes('embedding')
      || haystack.includes('signal');
  });
}

function stage8Lane(
  id: Stage8LaneId,
  label: string,
  value: number,
  detail: string,
  tone: CompilerTone,
  queue?: CompilerQueueId,
): Stage8LaneView {
  return { id, label, value, detail, tone, queue };
}

function buildStage8ReviewItems(
  snapshot: GraphRebuildSnapshot | null,
  clusters: ProductDiagnosticsReviewCluster[],
  graphLinks: GraphRebuildLinkSuggestion[],
): Stage8ReviewItemView[] {
  const items: Stage8ReviewItemView[] = [];
  for (const cluster of clusters.slice(0, 3)) {
    items.push(stage8ReviewItem({
      id: `cluster:${cluster.id}`,
      label: cluster.label,
      family: cluster.kind === 'entity-link' ? 'Identity' : 'Graph',
      detail: `${cluster.count} items / ${cluster.conflicts} conflicts`,
      action: cluster.action,
      confidence: cluster.confidence,
      tone: cluster.conflicts ? 'danger' : 'review',
      signals: cluster.signals,
      queue: cluster.kind === 'entity-link' ? 'identity' : 'graph-links',
    }));
  }
  for (const suggestion of (snapshot?.shadowLinkSuggestions || snapshot?.entityLinkSuggestions || []).slice(0, 2)) {
    items.push(stage8ReviewItem({
      id: `identity:${suggestion.id}`,
      label: entityLinkItemTitle(suggestion),
      family: 'Alias',
      detail: `${suggestion.decision.replace(/_/g, ' ')} / ${suggestion.candidateKind || 'untyped'}`,
      action: isShadowLink(suggestion) ? suggestion.promotionState : suggestion.status,
      confidence: suggestion.rerankScore || suggestion.confidence,
      tone: isShadowLink(suggestion) && suggestion.promotionBlockedReasons.length ? 'danger' : 'review',
      signals: suggestion.rerankSignals || suggestion.rationale || [],
      queue: 'identity',
    }));
  }
  for (const suggestion of (snapshot?.resolutionSuggestions || []).slice(0, 2)) {
    items.push(stage8ReviewItem({
      id: `coref:${suggestion.id}`,
      label: suggestion.surface,
      family: 'Coref',
      detail: `${suggestion.kind.replace(/_/g, ' ')} / ${suggestion.entityIds.length} entities`,
      action: suggestion.status,
      confidence: 0.5,
      tone: 'review',
      signals: [suggestion.rationale],
      queue: 'identity',
    }));
  }
  for (const patch of (snapshot?.finalLinkPatchLog?.patches || []).filter((row) => row.status === 'planned').slice(0, 2)) {
    const failed = patch.receipts.some((receipt) => receipt.status === 'failed');
    items.push(stage8ReviewItem({
      id: `patch:${patch.id}`,
      label: patch.operation,
      family: 'Patch',
      detail: `${patch.kind.replace(/_/g, ' ')} / ${patch.evidenceIds.length} evidence`,
      action: failed ? 'blocked' : patch.status,
      confidence: patch.confidence,
      tone: failed ? 'danger' : 'ready',
      signals: patch.receipts.map((receipt) => `${receipt.invariant}: ${receipt.status}`),
      queue: 'final-patches',
    }));
  }
  for (const link of graphLinks.slice(0, 2)) {
    items.push(stage8ReviewItem({
      id: `graph:${link.id}`,
      label: `${link.sourceEntityId} -> ${link.targetEntityId}`,
      family: 'Frame',
      detail: `${link.suggestedRelationType} / ${link.structuralRole}`,
      action: link.kind.replace(/_/g, ' '),
      confidence: link.rerankScore || link.confidence,
      tone: 'review',
      signals: link.rerankSignals || link.rationale || [],
      queue: 'graph-links',
    }));
  }
  if (!items.length) {
    items.push(stage8ReviewItem({
      id: 'stage8:clear',
      label: 'Review queue clear',
      family: 'Ready',
      detail: 'No high-blast decisions surfaced yet',
      action: 'watch',
      confidence: 1,
      tone: 'ready',
      signals: ['Full Atlas receipts will appear after the next run'],
    }));
  }
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  }).slice(0, 6);
}

function stage8ReviewItem(item: Stage8ReviewItemView): Stage8ReviewItemView {
  return {
    ...item,
    signals: item.signals.filter(Boolean).slice(0, 3),
  };
}

function buildCompilerWorkbenchView(
  snapshot: GraphRebuildSnapshot | null,
  receipt: GraphIndexRunReceipt | null,
  staging: PostprocessStagingView | null,
  reviewClusters: ProductDiagnosticsReviewCluster[],
  graphLinks: GraphRebuildLinkSuggestion[],
  activeQueue: CompilerQueueId,
  decisions: Record<string, CompilerQueueDecision>,
  linkDecisions: Record<string, 'accepted' | 'rejected'>,
  enabledLanes: GraphRebuildSignalTargetLane[],
  entityLinkerEnabled: boolean,
): CompilerWorkbenchView | null {
  if (!snapshot && !receipt) return null;
  const counters = snapshot?.counters || receipt?.counters;
  const graphModelCounters = snapshot?.graphModelV2?.counters;
  const graphCompileCounters = snapshot?.graphCompileReceipts?.counters;
  const patchLogCounters = snapshot?.finalLinkPatchLog?.counters;
  const laneItems = compilerLaneItems(staging, enabledLanes, entityLinkerEnabled);
  const bundleItems = compilerBundleItems(reviewClusters, decisions);
  const identityItems = compilerIdentityItems(snapshot, decisions);
  const graphItems = compilerGraphLinkItems(graphLinks, linkDecisions);
  const patchItems = compilerPatchItems(snapshot, decisions);
  const receiptItems = compilerReceiptItems(snapshot);
  const receiptFailures = receiptItems.length || patchLogCounters?.failedReceipts || counters?.finalLinkReceiptFailures || 0;
  const bundles = graphModelCounters?.bundles ?? graphCompileCounters?.bundles ?? bundleItems.length;
  const facts = graphModelCounters?.facts ?? graphCompileCounters?.facts ?? 0;
  const projections = snapshot?.projectedUiGraph?.length
    ?? graphModelCounters?.projectionEdges
    ?? graphCompileCounters?.projectedEdges
    ?? 0;
  const compilerSource = snapshot?.graphCompilerSource === 'rust'
    ? 'Rust compiler'
    : snapshot?.graphCompilerSource === 'typescriptCompatibility'
      ? 'TS compatibility bridge'
      : 'Compiler pending';
  const buckets: Record<CompilerQueueId, CompilerQueueItemView[]> = {
    lanes: laneItems,
    bundles: bundleItems,
    identity: identityItems,
    'graph-links': graphItems,
    'final-patches': patchItems,
    receipts: receiptItems,
  };
  const queues = [
    queue('lanes', staging?.title || 'Lane Plan', laneItems.length, staging ? `${staging.targets} admitted / ${staging.deferred} deferred` : 'No target plan yet', laneItems.length ? 'ready' : 'quiet'),
    queue('bundles', 'Bundles', bundleItems.length, 'Clustered bundle families and promotions', bundleItems.length ? 'review' : 'quiet'),
    queue('identity', 'Identity', identityItems.length, 'ShadowLinker suspicions and promotions', identityItems.length ? 'review' : 'quiet'),
    queue('graph-links', 'Graph Links', graphItems.length, 'Graph-aware suggestions with accept/reject', graphItems.length ? 'review' : 'quiet'),
    queue('final-patches', 'Final Patches', patchItems.length, 'Receipt-gated reversible writes', receiptFailures ? 'danger' : patchItems.length ? 'ready' : 'quiet'),
    queue('receipts', 'Receipts', receiptItems.length, 'Failed or blocking invariants', receiptFailures ? 'danger' : 'quiet'),
  ];
  const active = queues.some((queueView) => queueView.id === activeQueue) ? activeQueue : 'graph-links';
  const activeView = queues.find((queueView) => queueView.id === active) || queues[0];
  return {
    source: compilerSource,
    detail: 'Prepared artifacts -> staged bundles -> promoted facts -> projected read models',
    blocked: receiptFailures,
    activeQueue: active,
    activeLabel: activeView.label,
    activeDetail: activeView.detail,
    metrics: [
      metric('chunks', 'Chunks', counters?.chunks || 0, 'prepared source spans', 'ready'),
      metric('mentions', 'Mentions', counters?.mentions || 0, 'NER + anchor packets', 'ready'),
      metric('bundles', 'Bundles', bundles, 'staged fact bundles', bundles ? 'review' : 'quiet'),
      metric('facts', 'Facts', facts, 'promoted relation facts', facts ? 'ready' : 'quiet'),
      metric('projections', 'Projection edges', projections, 'UI read-model output', projections ? 'ready' : 'quiet'),
      metric('shadow', 'Shadow links', identityItems.length, 'non-mutating suspicions', identityItems.length ? 'review' : 'quiet'),
      metric('patches', 'Final patches', patchItems.length, 'reversible mutation log', patchItems.length ? 'ready' : 'quiet'),
      metric('receipts', 'Receipt failures', receiptFailures, 'blocked invariants', receiptFailures ? 'danger' : 'ready'),
    ],
    queues,
    items: buckets[active],
    staging,
  };
}

function compilerLaneItems(
  staging: PostprocessStagingView | null,
  enabledLanes: GraphRebuildSignalTargetLane[],
  entityLinkerEnabled: boolean,
): CompilerQueueItemView[] {
  const enabled = new Set(enabledLanes);
  const laneStats = new Map<GraphRebuildSignalTargetLane, PostprocessLaneView>();
  for (const lane of staging?.lanes || []) {
    const normalized = normalizeSignalLaneId(lane.id);
    if (normalized) laneStats.set(normalized, lane);
  }
  const rows = EMBEDDING_STAGE_LANES.map((lane) => {
    const stats = laneStats.get(lane.id);
    const active = enabled.has(lane.id);
    const admitted = stats?.admitted ?? 0;
    const candidates = stats?.candidates ?? 0;
    const deferred = stats?.deferred ?? 0;
    return compilerItem({
      id: `lane:${lane.id}`,
      queue: 'lanes',
      label: lane.label,
      detail: `${admitted} admitted / ${candidates} candidates / ${deferred} deferred`,
      kind: 'lane',
      confidence: stats?.percent ? stats.percent / 100 : active ? 1 : 0,
      tone: active ? 'ready' : 'quiet',
      status: active ? 'enabled next run' : 'off next run',
      primaryLabel: active ? 'Turn off' : 'Turn on',
      primaryAction: 'toggle-lane',
    });
  });
  rows.push(compilerItem({
    id: 'lane:entity_linker',
    queue: 'lanes',
    label: 'Entity linker',
    detail: 'Shadow linking and identity review lane',
    kind: 'lane',
    confidence: entityLinkerEnabled ? 1 : 0,
    tone: entityLinkerEnabled ? 'ready' : 'quiet',
    status: entityLinkerEnabled ? 'enabled next run' : 'off next run',
    primaryLabel: entityLinkerEnabled ? 'Turn off' : 'Turn on',
    primaryAction: 'toggle-lane',
  }));
  return rows;
}

function compilerBundleItems(
  clusters: ProductDiagnosticsReviewCluster[],
  decisions: Record<string, CompilerQueueDecision>,
): CompilerQueueItemView[] {
  return clusters
    .filter((cluster) => decisions[`bundle:${cluster.id}`] !== 'dismissed')
    .map((cluster) => {
      const id = `bundle:${cluster.id}`;
      const decision = decisions[id];
      return compilerItem({
        id,
        queue: 'bundles',
        label: cluster.label,
        detail: `${cluster.action} / ${cluster.count} items / ${cluster.representativeCount} examples`,
        kind: cluster.kind === 'entity-link' ? 'entity' : 'graph',
        confidence: cluster.confidence,
        tone: cluster.conflicts > 0 ? 'danger' : 'review',
        status: decision ? compilerDecisionLabel(decision) : cluster.action,
        evidenceCount: cluster.representativeCount,
        blockedReasons: cluster.conflicts > 0 ? [`${cluster.conflicts} conflicts`] : [],
        receiptSummary: cluster.signals.slice(0, 3).join(' / '),
        primaryLabel: decision === 'promoted' ? undefined : 'Promote',
        primaryAction: decision === 'promoted' ? undefined : 'promote',
        secondaryLabel: 'Dismiss',
        secondaryAction: 'dismiss',
      });
    });
}

function compilerIdentityItems(
  snapshot: GraphRebuildSnapshot | null,
  decisions: Record<string, CompilerQueueDecision>,
): CompilerQueueItemView[] {
  return (snapshot?.shadowLinkSuggestions || snapshot?.entityLinkSuggestions || [])
    .filter((suggestion) => decisions[`identity:${suggestion.id}`] !== 'dismissed')
    .slice(0, 24)
    .map((suggestion) => {
      const id = `identity:${suggestion.id}`;
      const decision = decisions[id];
      const blockedReasons = isShadowLink(suggestion) ? suggestion.promotionBlockedReasons : [];
      return compilerItem({
        id,
        queue: 'identity',
        label: entityLinkItemTitle(suggestion),
        detail: `${shadowLinkKindText(suggestion)} / ${suggestion.candidateKind || 'untyped'}`,
        kind: suggestion.decision,
        confidence: suggestion.confidence,
        tone: blockedReasons.length ? 'danger' : 'review',
        status: decision ? compilerDecisionLabel(decision) : isShadowLink(suggestion) ? suggestion.promotionState : suggestion.status,
        evidenceCount: suggestion.evidenceIds?.length || 0,
        blockedReasons,
        receiptSummary: suggestion.rationale?.slice(0, 2).join(' / ') || suggestion.rerankSignals?.slice(0, 3).join(' / '),
        primaryLabel: blockedReasons.length || decision === 'promoted' ? undefined : 'Promote',
        primaryAction: blockedReasons.length || decision === 'promoted' ? undefined : 'promote',
        secondaryLabel: 'Dismiss',
        secondaryAction: 'dismiss',
      });
    });
}

function compilerGraphLinkItems(
  suggestions: GraphRebuildLinkSuggestion[],
  linkDecisions: Record<string, 'accepted' | 'rejected'>,
): CompilerQueueItemView[] {
  return suggestions
    .filter((suggestion) => !Object.keys(linkDecisions).some((key) => key.endsWith(`:${suggestion.id}`)))
    .slice(0, 24)
    .map((suggestion) => compilerItem({
      id: `graph-link:${suggestion.id}`,
      queue: 'graph-links',
      label: `${suggestion.sourceEntityId} -> ${suggestion.targetEntityId}`,
      detail: `${suggestion.suggestedRelationType} / ${suggestion.semanticStatus} / ${suggestion.structuralRole}`,
      kind: suggestion.kind,
      confidence: suggestion.confidence,
      tone: 'review',
      status: suggestion.kind.replace(/_/g, ' '),
      evidenceCount: suggestion.evidenceIds?.length || 0,
      receiptSummary: suggestion.rerankSignals?.slice(0, 3).join(' / '),
      primaryLabel: 'Accept',
      primaryAction: 'accept-link',
      secondaryLabel: 'Reject',
      secondaryAction: 'reject-link',
    }));
}

function compilerPatchItems(
  snapshot: GraphRebuildSnapshot | null,
  decisions: Record<string, CompilerQueueDecision>,
): CompilerQueueItemView[] {
  return (snapshot?.finalLinkPatchLog?.patches || [])
    .filter((patch) => !['applied', 'reverted'].includes(decisions[`patch:${patch.id}`] || patch.status))
    .slice(0, 24)
    .map((patch) => {
      const failed = patch.receipts.filter((receipt) => receipt.status === 'failed');
      return compilerItem({
        id: `patch:${patch.id}`,
        queue: 'final-patches',
        label: patch.operation,
        detail: `${patch.kind.replace(/_/g, ' ')} / ${patch.sourceEntityId || patch.alias || patch.sourceShadowLinkId}`,
        kind: patch.kind,
        confidence: patch.confidence,
        tone: failed.length ? 'danger' : 'ready',
        status: failed.length ? 'blocked' : patch.status,
        evidenceCount: patch.evidenceIds?.length || 0,
        blockedReasons: failed.map((receipt) => receipt.detail),
        receiptSummary: patch.receipts.map((receipt) => `${receipt.invariant}: ${receipt.status}`).slice(0, 2).join(' / '),
        primaryLabel: failed.length ? undefined : 'Apply',
        primaryAction: failed.length ? undefined : 'apply-patch',
        secondaryLabel: 'Revert',
        secondaryAction: 'revert-patch',
      });
    });
}

function compilerReceiptItems(snapshot: GraphRebuildSnapshot | null): CompilerQueueItemView[] {
  return (snapshot?.finalLinkPatchLog?.receipts || [])
    .filter((receipt) => receipt.status === 'failed')
    .slice(0, 24)
    .map((receipt) => compilerItem({
      id: `receipt:${receipt.id}`,
      queue: 'receipts',
      label: receipt.invariant,
      detail: receipt.detail,
      kind: 'receipt',
      confidence: 0,
      tone: 'danger',
      status: receipt.status,
      receiptSummary: `source ${receipt.sourceShadowLinkId}`,
    }));
}

function compilerItem(item: {
  id: string;
  queue: CompilerQueueId;
  label: string;
  detail: string;
  kind: string;
  confidence: number;
  tone: CompilerTone;
  status: string;
  evidenceCount?: number;
  blockedReasons?: string[];
  receiptSummary?: string;
  primaryLabel?: string;
  primaryAction?: CompilerQueueAction;
  secondaryLabel?: string;
  secondaryAction?: CompilerQueueAction;
}): CompilerQueueItemView {
  return {
    evidenceCount: 0,
    blockedReasons: [],
    receiptSummary: '',
    ...item,
  };
}

function compilerDecisionLabel(decision: CompilerQueueDecision): string {
  switch (decision) {
    case 'promoted': return 'promoted overlay';
    case 'dismissed': return 'dismissed';
    case 'applied': return 'applied overlay';
    case 'reverted': return 'reverted overlay';
  }
}

function signalLaneLabel(lane: GraphRebuildSignalTargetLane | string): string {
  const known = EMBEDDING_STAGE_LANES.find((row) => row.id === lane);
  if (known) return known.label;
  if (lane === 'entity_linker') return 'Entity linker';
  if (lane === 'story_signal') return 'Story signal';
  if (lane === 'unknown') return 'Unknown';
  return titleCase(String(lane).replace(/_/g, ' '));
}

function normalizeSignalLaneId(id: string): GraphRebuildSignalTargetLane | null {
  const direct = EMBEDDING_STAGE_LANES.find((lane) => lane.id === id)?.id;
  if (direct) return direct;
  const aliases: Record<string, GraphRebuildSignalTargetLane> = {
    documentSpine: 'document_spine',
    chunkSpine: 'chunk_spine',
    entityAnchors: 'entity_anchor',
    relationshipFacts: 'relationship_fact',
    temporalFacts: 'temporal_fact',
    causalFacts: 'causal_fact',
    memoryStates: 'memory_state',
    eventIdentities: 'event_identity',
    anchorEvidence: 'anchor_evidence',
    weakCooccurrence: 'cooccurrence_weak',
    entityLinker: 'entity_linker',
  };
  return aliases[id] || null;
}

function isShadowLink(suggestion: GraphRebuildEntityLinkSuggestion): suggestion is GraphRebuildShadowLink {
  return (suggestion as Partial<GraphRebuildShadowLink>).phase === 'shadow';
}

function entityLinkItemTitle(suggestion: GraphRebuildEntityLinkSuggestion): string {
  const target = suggestion.candidateLabel || suggestion.candidateEntityId || 'new entity';
  return `${suggestion.surface} -> ${target}`;
}

function shadowLinkKindText(suggestion: GraphRebuildEntityLinkSuggestion): string {
  const kind = (suggestion as Partial<GraphRebuildShadowLink>).shadowKind;
  switch (kind) {
    case 'bundle_dedupe': return 'bundle dedupe';
    case 'alias_suspicion': return 'alias suspicion';
    case 'same_entity_suspicion': return 'same entity';
    case 'relation_duplicate_suspicion': return 'relation duplicate';
    case 'cluster_hint': return 'cluster hint';
    case 'query_assist': return 'query assist';
    default: return suggestion.status;
  }
}

function metric(
  id: string,
  label: string,
  value: number,
  detail: string,
  tone: CompilerTone,
): CompilerMetricView {
  return { id, label, value, detail, tone };
}

function queue(
  id: CompilerQueueId,
  label: string,
  count: number,
  detail: string,
  tone: CompilerTone,
): CompilerQueueView {
  return { id, label, count, detail, tone };
}

function counterValue(counters: Record<string, number> | undefined, key: string): number {
  const value = counters?.[key];
  return Number.isFinite(value) ? Number(value) : 0;
}

function zeroVisiblePostprocessLane(id: string): boolean {
  const lane = normalizeSignalLaneId(id);
  return lane === 'relationship_fact'
    || lane === 'temporal_fact'
    || lane === 'causal_fact'
    || lane === 'memory_state'
    || lane === 'event_identity';
}

function graphIndexReceiptLabel(receipt: GraphIndexRunReceipt): string {
  const noun = graphIndexReceiptNoun(receipt);
  return receipt.status === 'completed' ? `${noun} complete` : `${noun} failed`;
}

function graphIndexReceiptNoun(receipt: GraphIndexRunReceipt): string {
  const id = receipt.id || '';
  const message = receipt.message || '';
  if (id.startsWith('postprocess-atlas') || message.startsWith('Postprocess')) return 'Postprocess';
  if (id.startsWith('core-atlas') || message.startsWith('Clean graph')) return 'Clean graph';
  return 'Full Atlas Index';
}

function stageReceiptRow(stage: GraphIndexStageReceipt): LastRunReceiptRow {
  return {
    id: `stage:${stage.id}`,
    label: stage.label,
    detail: receiptRowDetail(stage.status, stage.outputCount, stage.counters, stage.id),
    durationMs: stage.durationMs,
    outputCount: stage.outputCount,
    status: stage.status,
    kind: 'stage',
  };
}

function projectionReceiptRow(projection: GraphIndexProjectionReceipt): LastRunReceiptRow {
  return {
    id: `projection:${projection.mode}`,
    label: projection.mode === 'siegel' ? 'Siegel-Finsler Backbone' : `${titleCase(projection.mode)} Projection`,
    detail: projectionReceiptDetail(projection),
    durationMs: projection.durationMs,
    outputCount: projection.targetCount,
    status: projection.status,
    kind: 'projection',
  };
}

function projectionReceiptDetail(projection: GraphIndexProjectionReceipt): string {
  const counters = projection.counters || {};
  if (counters['graphRebuildReadModelProjection'] || counters['nativeSemanticSidecarBypassed']) {
    return [
      'snapshot-owned',
      valueLabel(projection.targetCount, 'target'),
      'read-model topology',
    ].join(' / ');
  }
  const backendMs = counters['nativeLoadMs'] || counters['fallbackLoadMs'] || 0;
  const backendLabel = counters['nativeLoadMs'] ? 'native' : counters['fallbackLoadMs'] ? 'fallback' : '';
  const uiMs = counters['uiWrapperMs'] || 0;
  const nodes = counters['payloadNodes'] || 0;
  const edges = counters['payloadEdges'] || 0;
  const parts = [
    projection.status,
    valueLabel(projection.targetCount, 'target'),
    valueLabel(projection.vectorCount, 'vector'),
  ];
  if (backendMs > 0) parts.push(`${backendLabel} ${formatDuration(backendMs)}`);
  if (uiMs > 0) parts.push(`ui ${formatDuration(uiMs)}`);
  if (projection.mode === 'siegel') {
    parts.push(counters['siegelNative'] ? 'native' : 'fallback');
    parts.push(`g${counters['siegelGenus'] || 0}`);
    parts.push(`${formatCount(counters['siegelDirectedEdges'] || 0)} directed`);
    parts.push(`${formatCount(counters['siegelPairs'] || counters['siegelDirectedEdges'] || 0)} pairs`);
    parts.push(`${formatCount(counters['siegelDistanceEvaluations'] || 0)} evals`);
    parts.push(`${formatCount(counters['siegelAsymmetricPairs'] || 0)} asymmetric`);
    const capped = (counters['siegelCappedEdges'] || 0)
      + (counters['siegelCappedPairs'] || 0)
      + (counters['siegelCappedDistances'] || 0);
    if (capped > 0) parts.push(`${formatCount(capped)} capped`);
    if (counters['siegelSkippedEdges']) parts.push(`${formatCount(counters['siegelSkippedEdges'])} skipped`);
    if (counters['siegelEstimatedBytes']) parts.push(formatBytes(counters['siegelEstimatedBytes']));
  }
  if (nodes > 0 || edges > 0) parts.push(`payload ${formatCount(nodes)}n/${formatCount(edges)}e`);
  return parts.join(' / ');
}

function receiptRowDetail(
  status: string,
  outputCount: number,
  counters: Record<string, number>,
  stageId = '',
): string {
  if (stageId === 'receiptDbOps') {
    return receiptDbOpsDetail(status, outputCount, counters);
  }
  if (stageId === 'snapshotDbOps') {
    return snapshotDbOpsDetail(status, outputCount, counters);
  }
  if (stageId === 'snapshotPayloadProfile') {
    return snapshotPayloadProfileDetail(status, outputCount, counters);
  }
  if (stageId === 'transportOps') {
    return transportOpsDetail(status, outputCount, counters);
  }
  const entries = Object.entries(counters || {})
    .filter(([key, value]) => isVisibleReceiptCounter(key, value, stageId));
  const orderedEntries = prioritizeReceiptCounters(entries, receiptCounterPriority(stageId));
  const counterLimit = receiptCounterLimit(stageId);
  const counterText = orderedEntries
    .slice(0, counterLimit)
    .map(([key, value]) => `${labelFromKey(key)} ${formatReceiptCounterValue(key, value)}`)
    .join(' / ');
  const outputText = valueLabel(outputCount, 'output');
  return counterText ? `${status} / ${outputText} / ${counterText}` : `${status} / ${outputText}`;
}

function receiptDbOpsDetail(
  status: string,
  outputCount: number,
  counters: Record<string, number>,
): string {
  const parts = [status, valueLabel(outputCount, 'output')];
  const storeCountersPresent = Object.keys(counters || {}).some((key) => key.startsWith('receiptStore'));
  const addMs = (label: string, key: string, includeZero = false): void => {
    const value = counterValue(counters, key);
    if (includeZero || value > 0) parts.push(`${label} ${formatDuration(value)}`);
  };

  addMs('persist', 'receiptPersistMs');
  if (storeCountersPresent) {
    addMs('store', 'receiptStoreTotalMs', true);
    addMs('queue', 'receiptStoreQueueWaitMs', true);
    addMs('append', 'receiptStoreAppendWalMs', true);
    addMs('manifest', 'receiptStoreManifestMs', true);
    addMs('native', 'receiptStoreNativeApplyMs', true);
  }

  const rpcCalls = counterValue(counters, 'receiptJsonRpcCalls');
  if (rpcCalls > 0) parts.push(`rpc ${formatCount(rpcCalls)}`);
  const walBytes = counterValue(counters, 'receiptApplyWalBatchRequestBytes');
  if (walBytes > 0) {
    parts.push(`wal ${formatBytes(walBytes)}`);
  } else {
    const payloadChars = counterValue(counters, 'receiptPayloadChars')
      || counterValue(counters, 'receiptStorePayloadChars');
    if (payloadChars > 0) parts.push(`payload ${formatCount(payloadChars)} chars`);
  }
  return parts.join(' / ');
}

function snapshotDbOpsDetail(
  status: string,
  outputCount: number,
  counters: Record<string, number>,
): string {
  const parts = [status, valueLabel(outputCount, 'output')];
  const addMs = (label: string, key: string): void => {
    const value = counterValue(counters, key);
    if (value > 0) parts.push(`${label} ${formatDuration(value)}`);
  };
  const addChars = (label: string, key: string): void => {
    const value = counterValue(counters, key);
    if (value > 0) parts.push(`${label} ${formatCount(value)} chars`);
  };

  addMs('db load', 'dbLoadMs');
  addMs('snapshot persist', 'snapshotPersistMs');
  addMs('snapshot serialize', 'snapshotSerializeMs');
  addMs('primary encode', 'snapshotPrimaryEncodeMs');
  addMs('overgraph encode', 'snapshotOverGraphEncodeMs');
  addMs('payload profile', 'snapshotPayloadProfileMs');
  addMs('snapshot store', 'snapshotStoreMs');
  addMs('primary store', 'snapshotPrimaryStoreMs');
  addMs('overgraph store', 'snapshotOverGraphStoreMs');
  addChars('payload', 'snapshotPayloadChars');
  return parts.join(' / ');
}

const SNAPSHOT_PAYLOAD_SECTION_LIMIT = 8;

function snapshotPayloadProfileDetail(
  status: string,
  outputCount: number,
  counters: Record<string, number>,
): string {
  const parts = [status, valueLabel(outputCount, 'output')];
  const aggregateCounters: Array<[string, string]> = [
    ['primary', 'snapshotPrimaryPayloadChars'],
    ['raw', 'snapshotPrimaryRawPayloadChars'],
    ['saved', 'snapshotCompressionSavedChars'],
    ['ratio', 'snapshotCompressionRatioPct'],
    ['overgraph', 'snapshotOverGraphPayloadChars'],
    ['overgraph raw', 'snapshotOverGraphRawPayloadChars'],
    ['overgraph saved', 'snapshotOverGraphCompressionSavedChars'],
    ['overgraph ratio', 'snapshotOverGraphCompressionRatioPct'],
    ['total', 'snapshotTotalScopedPayloadChars'],
  ];
  for (const [label, key] of aggregateCounters) {
    const value = counterValue(counters, key);
    if (value <= 0) continue;
    if (key === 'snapshotCompressionRatioPct' || key === 'snapshotOverGraphCompressionRatioPct') {
      parts.push(`${label} ${formatCount(value)}%`);
    } else {
      parts.push(`${label} ${formatCount(value)} chars`);
    }
  }
  const sectionEntries = Object.entries(counters || {})
    .filter(([key, value]) => isSnapshotPayloadSectionCounter(key, value))
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, SNAPSHOT_PAYLOAD_SECTION_LIMIT);
  for (const [key, value] of sectionEntries) {
    parts.push(`${snapshotPayloadSectionLabel(key)} ${formatCount(value)} chars`);
  }
  return parts.join(' / ');
}

function transportOpsDetail(
  status: string,
  outputCount: number,
  counters: Record<string, number>,
): string {
  const parts = [status, valueLabel(outputCount, 'output')];
  const addCount = (label: string, key: string): void => {
    const value = counterValue(counters, key);
    if (value > 0) parts.push(`${label} ${formatCount(value)}`);
  };
  const addDuration = (label: string, key: string): void => {
    const value = counterValue(counters, key);
    if (value > 0) parts.push(`${label} ${formatDuration(value)}`);
  };
  const addBytes = (label: string, key: string): void => {
    const value = counterValue(counters, key);
    if (value > 0) parts.push(`${label} ${formatBytes(value)}`);
  };

  addCount('calls', 'transportCalls');
  addDuration('total', 'transportTotalMs');
  addDuration('max', 'transportMaxMs');
  addBytes('request', 'transportRequestBytes');
  addBytes('response', 'transportResponseBytes');
  addBytes('json response', 'jsonRpcResponseBytes');
  addBytes('typed response', 'typedRpcResponseBytes');
  addBytes('boot snapshot response', 'bootSnapshotJsonResponseBytes');
  addBytes('scan response', 'scanJsonResponseBytes');
  addBytes('atlas scan response', 'atlasRichScanJsonResponseBytes');
  addBytes('graph delta response', 'graphDeltaJsonResponseBytes');
  addBytes('init response', 'initRuntimeResponseBytes');
  addCount('store', 'storeCommandCalls');
  addBytes('store request', 'storeCommandRequestBytes');
  addBytes('store response', 'storeCommandResponseBytes');
  addBytes('relation list response', 'relationListResponseBytes');
  addCount('scoped reads', 'scopedDocumentReadCalls');
  addBytes('scoped read response', 'scopedDocumentReadResponseBytes');
  addBytes('snapshot read response', 'snapshotDocumentReadResponseBytes');
  addBytes('receipt read response', 'receiptDocumentReadResponseBytes');
  addBytes('cache read response', 'postprocessCacheReadResponseBytes');
  addBytes('overgraph read response', 'overGraphDocumentReadResponseBytes');
  addBytes('note body response', 'noteBodyReadResponseBytes');
  addCount('wal calls', 'applyWalBatchCalls');
  addBytes('wal request', 'applyWalBatchRequestBytes');
  addBytes('wal response', 'applyWalBatchResponseBytes');
  addCount('compile calls', 'compileDualWriteCalls');
  addBytes('compile request', 'compileDualWriteRequestBytes');
  addBytes('compile response', 'compileDualWriteResponseBytes');
  addBytes('compile raw', 'compileDualWriteRawBytes');
  addBytes('compile zipped', 'compileDualWriteCompressedBytes');
  addBytes('galaxy request', 'compileGalaxySceneRequestBytes');
  addBytes('galaxy response', 'compileGalaxySceneResponseBytes');
  return parts.join(' / ');
}

function isSnapshotPayloadSectionCounter(key: string, value: number): boolean {
  return key.startsWith('payload')
    && key.endsWith('Chars')
    && Number.isFinite(value)
    && value > 0;
}

function snapshotPayloadSectionLabel(key: string): string {
  return labelFromKey(key.replace(/^payload/, '').replace(/Chars$/i, ''));
}

function prioritizeReceiptCounters(
  entries: Array<[string, number]>,
  priority: string[],
): Array<[string, number]> {
  const rank = new Map(priority.map((key, index) => [key, index]));
  return [...entries].sort((left, right) => {
    const leftRank = rank.get(left[0]) ?? Number.MAX_SAFE_INTEGER;
    const rightRank = rank.get(right[0]) ?? Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank || left[0].localeCompare(right[0]);
  });
}

function receiptCounterPriority(stageId: string): string[] {
  if (stageId === 'postProcessDiscovery') {
    return ['postprocessDiscoverySkipped', 'plannedModelCalls', 'documents', 'dynamicSurfaceMs', 'dynamicSurfaceCandidateSuggestions', 'dynamicSurfaceMentions', 'dynamicSurfaceHints', 'processedDocuments', 'candidateSuggestions', 'indexedDocuments', 'graph.nodes'];
  }
  if (stageId === 'nliCandidatePlan') {
    return ['rawInputs', 'validInputs', 'plannedInputs', 'duplicateInputs', 'uniquePairs', 'documentIds'];
  }
  if (stageId === 'nliClassification') {
    return ['plannedInputs', 'results', 'batches', 'entailment', 'neutral', 'contradiction'];
  }
  if (stageId === 'nliApply') {
    return ['results', 'appliedRows'];
  }
  if (stageId === 'graphSnapshot' || stageId === 'postProcessSnapshot') {
    return ['embeddingTargets', 'embeddingPlannedPairs', 'embeddingPrunedPairs', 'embeddingBackboneEdges', 'embeddingClusters', 'linkSuggestions', 'entityLinks'];
  }
  if (stageId === 'snapshotDbOps') {
    return ['dbLoadMs', 'snapshotPersistMs', 'snapshotStoreMs', 'snapshotSerializeMs', 'snapshotPayloadProfileMs', 'snapshotPayloadChars', 'snapshotPrimaryRawPayloadChars', 'snapshotCompressionSavedChars', 'snapshotCompressionRatioPct', 'snapshotOverGraphPayloadChars', 'snapshotOverGraphRawPayloadChars', 'snapshotOverGraphCompressionSavedChars', 'snapshotOverGraphCompressionRatioPct', 'snapshotTotalPayloadChars'];
  }
  if (stageId === 'snapshotPayloadProfile') {
    return [
      'snapshotPrimaryPayloadChars',
      'snapshotPrimaryRawPayloadChars',
      'snapshotCompressionSavedChars',
      'snapshotCompressionRatioPct',
      'snapshotOverGraphPayloadChars',
      'snapshotOverGraphRawPayloadChars',
      'snapshotOverGraphCompressionSavedChars',
      'snapshotOverGraphCompressionRatioPct',
      'snapshotTotalScopedPayloadChars',
      'snapshotTotalScopedRawPayloadChars',
      'payloadEmbeddingTargetsChars',
      'payloadEmbeddingTargetPlanChars',
      'payloadEmbeddingGraphPostProcessChars',
      'payloadHopfResonanceSpaceChars',
      'payloadGraphModelV2Chars',
      'payloadGraphCompilerChars',
      'payloadProjectedUiGraphChars',
      'payloadSemanticRerankSummaryChars',
      'payloadSemanticAdjudicationSummaryChars',
      'payloadSemanticEvalLedgerSummaryChars',
      'payloadMemoryGraphRagBridgeSummaryChars',
      'payloadDiscourseSpineSummaryChars',
      'payloadDiscourseBridgeCandidateSummaryChars',
      'payloadDiscourseBridgeAdjudicationSummaryChars',
      'payloadDiscourseEvalLedgerSummaryChars',
      'payloadDiscoursePromotionSurfaceSummaryChars',
      'payloadDiscourseCompilerOverlaySummaryChars',
      'payloadGraphAwareLinkSuggestionsChars',
      'payloadEntityLinkSuggestionsChars',
      'payloadShadowLinkSuggestionsChars',
      'payloadChunksChars',
      'payloadMentionsChars',
      'payloadEntityAnchorsChars',
      'payloadRelationshipsChars',
      'payloadEventsChars',
      'payloadTemporalEdgesChars',
      'payloadCausalEdgesChars',
      'payloadMemoryStateChars',
      'payloadNodesChars',
      'payloadEdgesChars',
    ];
  }
  if (stageId === 'signalCandidatePlan') {
    return ['documents', 'documentChars', 'entities', 'discoverySkipped', 'discoveryCandidates', 'exportableMentions', 'discoveryCacheHit', 'priorTargets', 'plannedModelCalls'];
  }
  if (stageId === 'signalTargetCoverage') {
    return [
      'targets',
      'candidateTargets',
      'deferredTargets',
      'documentSpine',
      'chunkSpine',
      'entityAnchors',
      'relationshipFacts',
      'temporalFacts',
      'causalFacts',
      'memoryStates',
      'eventIdentities',
      'anchorEvidence',
      'weakCooccurrence',
      'graphFactTargets',
    ];
  }
  return [];
}

function receiptCounterLimit(stageId: string): number {
  if (stageId === 'postProcessDiscovery') return 8;
  if (stageId === 'nliCandidatePlan' || stageId === 'nliClassification' || stageId === 'nliApply') return 6;
  if (stageId === 'graphSnapshot' || stageId === 'postProcessSnapshot') return 7;
  if (stageId === 'snapshotDbOps') return 5;
  if (stageId === 'signalCandidatePlan') return 8;
  if (stageId === 'signalTargetCoverage') return 12;
  return 3;
}

const signalCoverageZeroCounterKeys = new Set([
  'deferredTargets',
  'documentSpine',
  'chunkSpine',
  'entityAnchors',
  'relationshipFacts',
  'temporalFacts',
  'causalFacts',
  'memoryStates',
  'eventIdentities',
  'anchorEvidence',
  'weakCooccurrence',
  'graphFactTargets',
  'eventTargets',
  'temporalFactTargets',
  'causalFactTargets',
  'memoryStateTargets',
]);

function isVisibleReceiptCounter(key: string, value: number, stageId = ''): boolean {
  if (!Number.isFinite(value)) return false;
  if (stageId === 'signalTargetCoverage' && signalCoverageZeroCounterKeys.has(key)) return true;
  if (value <= 0) return false;
  return !/(started|completed|duration|elapsed|wall|timestamp|time)/i.test(key);
}

function valueLabel(value: number, singular: string): string {
  const count = Math.max(0, Math.round(Number(value) || 0));
  return `${formatCount(count)} ${singular}${count === 1 ? '' : 's'}`;
}

function formatReceiptCounterValue(key: string, value: number): string {
  if (/bytes$/i.test(key)) return formatBytes(value);
  return /ms$/i.test(key) ? formatDuration(value) : formatCount(value);
}

function formatDuration(value: number): string {
  return `${formatCount(value)} ms`;
}

function formatCount(value: number): string {
  return Math.max(0, Math.round(Number(value) || 0)).toLocaleString('en-US');
}

function formatBytes(value: number): string {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${formatCount(bytes)} B`;
}

function labelFromKey(key: string): string {
  return key
    .replace(/Ms$/i, '')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .toLowerCase();
}

function titleCase(value: string): string {
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}
