import { Injectable, inject, signal } from '@angular/core';

import { parseContentToPlainText } from '../lib/analytics';
import { db } from '../lib/dexie/db';
import {
    DEFAULT_GRAPH_EMBEDDING_DIMENSION_LABEL,
    DEFAULT_GRAPH_EMBEDDING_MODEL_ID,
    DEFAULT_GRAPH_EMBEDDING_MODEL_LABEL,
} from '../lib/embeddings/models/ModelRegistry';
import { NoteEditorStore } from '../lib/store/note-editor.store';
import type { EntitySuggestionScanRequest } from '../lib/entity-suggestions/entity-suggestion.types';
import {
    ATLAS_CAPABILITY_RECIPES,
    atlasCapabilityById,
    atlasRecipeDefinitionById,
    type AtlasCapabilityId,
    type AtlasCapabilityMutationPolicy,
    type AtlasModelLaneId,
    type AtlasRecipeId,
} from '../components/search-panel/atlas-capability.model';
import { BlueprintHubService } from '../components/blueprint-hub/blueprint-hub.service';
import {
    NliWorkerService,
    type NliClassificationResult,
    type NliPairClassificationInput,
} from '../lib/services/nli-worker.service';
import { ATLAS_RICH_SCAN_QUARANTINE_MESSAGE, rejectAtlasRichScan } from './atlas-rich-scan-quarantine';
import { NerService } from './ner.service';
import { PhoenixBackendService } from './phoenix-backend.service';
import { ATLAS_EXPORTABLE_MENTION_STATUSES } from './atlas-capability-runtime.model';
import {
    PhoenixMachineControlService,
    type PhoenixMachineModelId,
} from './phoenix-machine-control.service';
import { PhoenixUiApiService, type SearchScope } from './phoenix-ui-api.service';
import type {
    AtlasCapabilityOperationKind,
    AtlasCapabilityRunPolicy,
    AtlasCapabilityRunResult,
    AtlasCapabilityRuntimeState,
    AtlasBuildContract,
    AtlasBuildReceipt,
    AtlasBuildStageReceipt,
    AtlasBridgeCommand,
    AtlasBuildScope,
    AtlasExpectedOutput,
    AtlasModelRequirement,
    AtlasOutputProbe,
    AtlasRecipeExecutionPlan,
    AtlasRecipeRunResult,
    AtlasRecipeRuntimeState,
    AtlasRunOptions,
    AtlasRuntimeModelRequirementId,
    AtlasRuntimeOperation,
    AtlasServiceRequirement,
} from './atlas-capability-runtime.model';
import type { AtlasManifoldMode } from './manifold-atlas.types';

const NLI_MODEL_ID = 'onnx-community/ModernBERT-base-nli-ONNX';

const TEXT_GRAPH_CAPABILITIES: AtlasCapabilityId[] = [
    'dynamicSurface',
    'dynamicChunking',
    'dynamicNer',
    'mentionGraph',
    'evidenceGraph',
    'surfaceGraph',
    'assertedKernel',
];

const SEMANTIC_SCAN_CAPABILITIES: AtlasCapabilityId[] = [
    'semanticAtlas',
    'semanticCandidate',
];

const QUARANTINED_RICH_SCAN_CAPABILITIES = new Set<AtlasCapabilityId>([
    ...TEXT_GRAPH_CAPABILITIES.filter((id) => id !== 'dynamicNer'),
    ...SEMANTIC_SCAN_CAPABILITIES,
]);

const QUARANTINED_RICH_SCAN_ROUTE = 'QUARANTINED: legacy atlas_rich_scan has no runtime binding';

const NATIVE_STORE_PROBE_CAPABILITIES: AtlasCapabilityId[] = [
    'relationGraph',
    'temporalGraph',
    'eventIdentity',
    'memoryState',
    'causalGraph',
];

const MANIFOLD_CAPABILITIES: Partial<Record<AtlasCapabilityId, AtlasManifoldMode>> = {
    hybridManifold: 'hybrid',
    hopfProjection: 'hopf',
    lorentzForest: 'lorentz',
    productManifold: 'product',
};

const MANIFOLD_PROJECTION_CAPABILITIES: AtlasCapabilityId[] = [
    'hybridManifold',
    'hopfProjection',
    'lorentzForest',
    'productManifold',
];

const MANIFOLD_PROJECTION_OPERATIONS: AtlasRuntimeOperation[] = [
    { kind: 'manifoldSnapshot', service: 'PhoenixUiApiService.loadManifoldAtlasSnapshot', policy: 'read-only', manifold: 'hybrid' },
    { kind: 'manifoldSnapshot', service: 'PhoenixUiApiService.loadManifoldAtlasSnapshot', policy: 'read-only', manifold: 'hopf' },
    { kind: 'manifoldSnapshot', service: 'PhoenixUiApiService.loadManifoldAtlasSnapshot', policy: 'read-only', manifold: 'lorentz' },
    { kind: 'manifoldSnapshot', service: 'PhoenixUiApiService.loadManifoldAtlasSnapshot', policy: 'read-only', manifold: 'product' },
];

const MANIFOLD_MODE_CAPABILITIES: Partial<Record<AtlasManifoldMode, AtlasCapabilityId>> = {
    hybrid: 'hybridManifold',
    hopf: 'hopfProjection',
    lorentz: 'lorentzForest',
    product: 'productManifold',
};

type NativeStoreProbeConfig = {
    relation: string;
    filter?: Record<string, unknown>;
    label: string;
    rowLabel: string;
};

const NATIVE_STORE_PROBES: Partial<Record<AtlasCapabilityId, NativeStoreProbeConfig>> = {
    relationGraph: {
        relation: 'graph_candidate_edges',
        label: 'Relation graph candidate edge probe',
        rowLabel: 'candidate edge row',
    },
    temporalGraph: {
        relation: 'graph_edges',
        filter: { edge_type: 'active_during' },
        label: 'Temporal graph active-during edge probe',
        rowLabel: 'temporal edge row',
    },
    eventIdentity: {
        relation: 'semantic_node_prototypes',
        filter: { node_kind: 'event' },
        label: 'Event identity semantic prototype probe',
        rowLabel: 'event prototype row',
    },
    memoryState: {
        relation: 'memories',
        label: 'Memory/state store probe',
        rowLabel: 'memory row',
    },
    causalGraph: {
        relation: 'graph_edges',
        filter: { edge_type: 'causal_link' },
        label: 'Causal graph causal-link edge probe',
        rowLabel: 'causal edge row',
    },
};

const NLI_BATCH_SIZE = 4;

type RuntimeTarget = {
    requiredModels: AtlasModelRequirement[];
};

interface NerScopeDocument {
    id: string;
    title: string;
    content: string;
    folderId: string;
}

interface NerScopeScanRequest {
    request: EntitySuggestionScanRequest;
    documentCount: number;
}

interface AtlasRuntimeRecipeDefinition {
    requiredCapabilities: AtlasCapabilityId[];
    optionalCapabilities: AtlasCapabilityId[];
    skippedCapabilities: AtlasCapabilityId[];
    dependencyChain: AtlasCapabilityId[];
    requiredModels: AtlasModelRequirement[];
    optionalModels: AtlasModelRequirement[];
    operations: AtlasRuntimeOperation[];
    expectedOutputs: AtlasExpectedOutput[];
    mutationPolicy: AtlasCapabilityMutationPolicy;
    runPolicy: AtlasCapabilityRunPolicy;
    backendRoute: string;
    runnable: boolean;
    skippedLanes: AtlasModelLaneId[];
    blockedReason?: string;
}

@Injectable({ providedIn: 'root' })
export class AtlasCapabilityRuntimeService {
    private readonly machine = inject(PhoenixMachineControlService);
    private readonly ner = inject(NerService);
    private readonly nli = inject(NliWorkerService);
    private readonly hub = inject(BlueprintHubService);
    private readonly noteStore = inject(NoteEditorStore);
    private readonly phoenixUiApi = inject(PhoenixUiApiService);
    private readonly phoenix = inject(PhoenixBackendService);

    readonly lastBuildContract = signal<AtlasBuildContract | null>(null);
    readonly lastBuildReceipt = signal<AtlasBuildReceipt | null>(null);

    capabilityState(id: AtlasCapabilityId, options: AtlasRunOptions = {}): AtlasCapabilityRuntimeState {
        const binding = this.capabilityBinding(id, options);
        const status = binding.blockedReason
            ? 'blocked'
            : binding.readinessProbe.status;
        return {
            ...binding,
            status,
            statusLabel: statusLabel(status),
        };
    }

    capabilityBinding(id: AtlasCapabilityId, options: AtlasRunOptions = {}): AtlasCapabilityRuntimeState {
        const capability = atlasCapabilityById(id);
        const operationKind = this.operationKindForCapability(id);
        const blockedReason = this.blockedReasonForCapability(id);
        const runnable = !blockedReason && operationKind !== 'notWired';
        const requiredModels = this.requiredModelsForCapability(id, options);
        const requiredServices = this.requiredServicesForCapability(id, options);
        const mutationPolicy = this.mutationPolicyForCapability(id, capability.mutationPolicy);
        const runPolicy = this.runPolicyForCapability(id);
        const readinessProbe = this.readinessProbeForCapability(id, operationKind, blockedReason);
        const outputProbe = this.outputProbeForCapability(id, operationKind);
        const status = blockedReason ? 'blocked' : readinessProbe.status;

        return {
            capabilityId: id,
            runnable,
            operationKind,
            requiredModels,
            requiredServices,
            mutationPolicy,
            runPolicy,
            readinessProbe,
            outputProbe,
            blockedReason,
            status,
            statusLabel: statusLabel(status),
        };
    }

    recipeState(id: AtlasRecipeId, options: AtlasRunOptions = {}): AtlasRecipeRuntimeState {
        const plan = this.recipePlan(id, options);
        const hasError = plan.requiredModels.some((model) => model.readiness === 'error');
        const modelsReady = plan.requiredModels.every((model) => model.readiness === 'ready');
        const status = !plan.runnable
            ? 'blocked'
            : hasError
                ? 'error'
                : modelsReady || !plan.requiredModels.length
                    ? 'ready'
                    : 'idle';
        return {
            ...plan,
            status,
            statusLabel: statusLabel(status),
        };
    }

    recipePlan(id: AtlasRecipeId, options: AtlasRunOptions = {}): AtlasRecipeExecutionPlan {
        const recipe = atlasRecipeDefinitionById(id);
        const runtime = this.runtimeRecipeDefinition(id, options);
        const requiredServices = uniqueServices(runtime.requiredCapabilities
            .flatMap((capabilityId) => this.capabilityBinding(capabilityId, options).requiredServices));

        return {
            id,
            label: recipe.label,
            description: recipe.description,
            actionLabel: recipe.actionLabel,
            requiredCapabilities: runtime.requiredCapabilities,
            optionalCapabilities: runtime.optionalCapabilities,
            skippedCapabilities: runtime.skippedCapabilities,
            dependencyChain: runtime.dependencyChain,
            requiredModels: runtime.requiredModels,
            optionalModels: runtime.optionalModels,
            requiredServices,
            operations: runtime.operations,
            skips: runtime.skippedCapabilities,
            expectedOutputs: runtime.expectedOutputs,
            outputLabel: recipe.outputLabel,
            mutationPolicy: runtime.mutationPolicy,
            runPolicy: runtime.runPolicy,
            cost: recipe.cost,
            backendRoute: runtime.backendRoute,
            runnable: runtime.runnable,
            blockedReason: runtime.blockedReason,
            requiredLanes: runtime.requiredModels.map((model) => model.laneId),
            optionalLanes: runtime.optionalModels.map((model) => model.laneId),
            skippedLanes: runtime.skippedLanes,
        };
    }

    buildRecipeContract(id: AtlasRecipeId, options: AtlasRunOptions = {}): AtlasBuildContract {
        const plan = this.recipePlan(id, options);
        const scope = this.contractScope(options);
        const noteIds = uniqueIds(options.noteIds?.length ? options.noteIds : noteIdsFromBuildScope(scope));
        const embedding = plan.requiredModels.find((model) => model.id === 'semanticEmbedding');
        return {
            contractId: `${id}:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 8)}`,
            recipeId: id,
            label: plan.label,
            scope,
            noteIds,
            policy: contractPolicy(plan.runPolicy),
            requiredStages: plan.requiredCapabilities,
            optionalStages: plan.optionalCapabilities,
            skippedStages: plan.skippedCapabilities,
            exportableMentionStatuses: [...ATLAS_EXPORTABLE_MENTION_STATUSES],
            modelLanes: plan.requiredModels.map((model) => model.laneId),
            requiredModels: plan.requiredModels,
            ...(embedding ? {
                embeddingModel: {
                    id: embedding.selectedModelId || this.embeddingModelId(options),
                    label: embedding.selectedModelLabel || this.embeddingModelLabel(options),
                    dimensionLabel: embedding.dims || this.embeddingDimensionLabel(options),
                },
            } : {}),
            operations: plan.operations,
            bridgeCommands: plan.operations.map((operation) => bridgeCommandForOperation(operation)),
            expectedOutputs: plan.expectedOutputs,
            backendRoute: plan.backendRoute,
        };
    }

    recipeBridgeAudit(id: AtlasRecipeId, options: AtlasRunOptions = {}): AtlasBridgeCommand[] {
        return this.buildRecipeContract(id, options).bridgeCommands;
    }

    async warmRequiredModels(target: RuntimeTarget, options: AtlasRunOptions = {}): Promise<void> {
        for (const model of target.requiredModels) {
            await this.warmModel(model.id, options);
        }
    }

    async warmModelLane(laneId: AtlasModelLaneId, options: AtlasRunOptions = {}): Promise<void> {
        switch (laneId) {
            case 'dynamicNer':
                await this.warmModel('dynamicNer', options);
                return;
            case 'semanticEmbedding':
                await this.warmModel('semanticEmbedding', options);
                return;
            case 'nli':
                await this.warmModel('nli', options);
                return;
            case 'coOccurrence':
                await this.ner.warmProvider('fst');
                return;
            case 'manifoldProjection':
                return;
        }
    }

    async runCapability(id: AtlasCapabilityId, options: AtlasRunOptions = {}): Promise<AtlasCapabilityRunResult> {
        const binding = this.capabilityBinding(id, options);
        if (!binding.runnable) {
            throw new Error(binding.blockedReason || `${atlasCapabilityById(id).label} is not wired.`);
        }
        if (!options.skipModelWarm) {
            await this.warmRequiredModels(binding, options);
        }
        const rawResult = await this.executeCapabilityOperation(id, binding.operationKind, binding.runPolicy, options);
        return {
            capabilityId: id,
            operationKind: binding.operationKind,
            mutationPolicy: binding.mutationPolicy,
            runPolicy: binding.runPolicy,
            outputProof: [this.outputProbeForCapability(id, binding.operationKind)],
            rawResult,
        };
    }

    async runRecipe(id: AtlasRecipeId, options: AtlasRunOptions = {}): Promise<AtlasRecipeRunResult> {
        const contract = this.buildRecipeContract(id, options);
        const receipt = await this.runAtlasBuild(contract, options);
        const recipe = atlasRecipeDefinitionById(id);

        return {
            recipeId: id,
            label: contract.label,
            contract,
            receipt,
            mutationPolicy: recipe.mutationPolicy,
            runPolicy: receipt.policy,
            outputProof: this.recipeOutputProof(id),
            operationResults: receipt.operationResults,
        };
    }

    async runAtlasBuild(contract: AtlasBuildContract, options: AtlasRunOptions = {}): Promise<AtlasBuildReceipt> {
        const plan = this.recipePlan(contract.recipeId, options);
        if (!plan.runnable) {
            throw new Error(plan.blockedReason || `${plan.label} is not wired.`);
        }

        const executionOptions = this.optionsFromContract(contract, options);
        const startedAt = performance.now();
        const stageReceipts: AtlasBuildStageReceipt[] = [];
        const operationResults: AtlasCapabilityRunResult[] = [];
        const warmedBeforeRun = !executionOptions.skipModelWarm;

        this.lastBuildContract.set(contract);
        if (!executionOptions.skipModelWarm) {
            for (const model of contract.requiredModels) {
                await this.warmModel(model.id, executionOptions);
                stageReceipts.push(modelWarmReceipt(model));
            }
        }

        for (const operation of contract.operations) {
            if (operation.kind === 'warmModel' && (executionOptions.skipModelWarm || warmedBeforeRun)) {
                stageReceipts.push(skippedWarmReceipt(operation));
                continue;
            }
            const result = await this.executeBuildOperation(operation, contract, executionOptions);
            if (!result) continue;
            operationResults.push(result);
            stageReceipts.push(stageReceiptFromResult(result, operation));
        }

        const completedAt = performance.now();
        const receipt: AtlasBuildReceipt = {
            contractId: contract.contractId,
            recipeId: contract.recipeId,
            label: contract.label,
            scope: contract.scope,
            policy: contract.policy,
            startedAt,
            completedAt,
            durationMs: Math.round(completedAt - startedAt),
            stageReceipts,
            operationResults,
        };
        this.lastBuildReceipt.set(receipt);
        return receipt;
    }

    modelRequirementLabel(models: AtlasModelRequirement[]): string {
        return models.length
            ? models.map((model) => model.dims ? `${model.label} ${model.dims}` : model.label).join(' / ')
            : 'none';
    }

    serviceRequirementLabel(services: AtlasServiceRequirement[]): string {
        return services.length ? services.map((service) => service.service).join(' / ') : 'none';
    }

    expectedOutputLabel(outputs: AtlasExpectedOutput[]): string {
        return outputs.length ? outputs.map((output) => output.label).join(' / ') : 'none';
    }

    private async executeBuildOperation(
        operation: AtlasRuntimeOperation,
        contract: AtlasBuildContract,
        options: AtlasRunOptions,
    ): Promise<AtlasCapabilityRunResult | null> {
        switch (operation.kind) {
            case 'warmModel':
            case 'modelWarm':
                if (!operation.model) return null;
                await this.warmModel(operation.model!, options);
                return null;
            case 'dynamicNerScan': {
                const rawResult = await this.runDynamicNerScan(options);
                return this.buildOperationResult(contract, 'dynamicNer', operation.kind, rawResult);
            }
            case 'richTextGraphScan': {
                const rawResult = await this.runTextGraphScan(operation.policy === 'force' ? 'force' : 'dirty-only', options);
                return this.buildOperationResult(contract, 'assertedKernel', operation.kind, rawResult);
            }
            case 'semanticAtlasScan': {
                const rawResult = await this.runSemanticAtlasScan(options, operation.policy === 'force' ? 'force' : 'dirty-only');
                return this.buildOperationResult(contract, 'semanticAtlas', operation.kind, rawResult);
            }
            case 'nativeStoreProbe': {
                const capabilityId = operation.args?.['capabilityId'] as AtlasCapabilityId | undefined;
                if (!capabilityId) return null;
                const rawResult = await this.runNativeStoreProbe(capabilityId);
                return this.buildOperationResult(contract, capabilityId, operation.kind, rawResult);
            }
            case 'nliAdjudication': {
                const rawResult = await this.runNliAdjudication(options);
                return this.buildOperationResult(contract, 'nliAdjudication', operation.kind, rawResult);
            }
            case 'graphVisualization': {
                const rawResult = this.openGraphVisualization(options);
                return this.buildOperationResult(contract, 'galaxyVisualization', operation.kind, rawResult);
            }
            case 'manifoldSnapshot': {
                const manifold = operation.manifold || 'hybrid';
                const rawResult = await this.runManifoldSnapshot(manifold, options);
                return this.buildOperationResult(contract, capabilityForManifoldMode(manifold), operation.kind, rawResult);
            }
            case 'retrievalWalk': {
                const rawResult = await this.runRetrievalWalk(options);
                return this.buildOperationResult(contract, 'retrievalWalk', operation.kind, rawResult);
            }
            case 'nativeReasoningPass':
            case 'notWired':
                throw new Error(`${contract.label} has no runtime binding.`);
        }
    }

    private buildOperationResult(
        contract: AtlasBuildContract,
        capabilityId: AtlasCapabilityId,
        operationKind: AtlasCapabilityOperationKind,
        rawResult: unknown,
    ): AtlasCapabilityRunResult {
        return {
            capabilityId,
            operationKind,
            mutationPolicy: this.mutationPolicyForCapability(capabilityId, atlasRecipeDefinitionById(contract.recipeId).mutationPolicy),
            runPolicy: this.runPolicyForCapability(capabilityId),
            outputProof: this.recipeOutputProof(contract.recipeId),
            rawResult,
        };
    }

    private async executeCapabilityOperation(
        id: AtlasCapabilityId,
        operationKind: AtlasCapabilityOperationKind,
        runPolicy: AtlasCapabilityRunPolicy,
        options: AtlasRunOptions,
    ): Promise<unknown> {
        switch (operationKind) {
            case 'modelWarm':
                if (id === 'semanticEmbedding') return this.warmModel('semanticEmbedding', options);
                return null;
            case 'dynamicNerScan':
                return this.runDynamicNerScan(options);
            case 'richTextGraphScan':
                return this.runTextGraphScan(runPolicy === 'force' ? 'force' : 'dirty-only', options);
            case 'semanticAtlasScan':
                return this.runSemanticAtlasScan(options, runPolicy === 'force' ? 'force' : 'dirty-only');
            case 'nativeStoreProbe':
                return this.runNativeStoreProbe(id);
            case 'nliAdjudication':
                return this.runNliAdjudication(options);
            case 'manifoldSnapshot':
                return this.runManifoldSnapshot(MANIFOLD_CAPABILITIES[id] || 'hybrid', options);
            case 'graphVisualization':
                return this.openGraphVisualization(options);
            case 'retrievalWalk':
                return this.runRetrievalWalk(options);
            case 'nativeReasoningPass':
            case 'notWired':
                throw new Error(this.blockedReasonForCapability(id) || `${atlasCapabilityById(id).label} has no runtime binding.`);
        }
    }

    private async warmModel(modelId: AtlasRuntimeModelRequirementId, options: AtlasRunOptions): Promise<void> {
        switch (modelId) {
            case 'dynamicNer':
                await this.ner.warmProvider('dynamic_ner');
                return;
            case 'semanticEmbedding':
                if (this.machine.vectorStatus() === 'ready') return;
                await this.machine.loadSemanticModel(
                    this.embeddingModelId(options),
                    this.embeddingModelLabel(options),
                    this.embeddingDimensionLabel(options),
                );
                return;
            case 'nli':
                if (this.nli.isInitialized()) return;
                await this.nli.initialize(NLI_MODEL_ID);
                return;
        }
    }

    private async runDynamicNerScan(options: AtlasRunOptions): Promise<{ suggestions: number; documents: number; exportableMentions: number }> {
        const scopeScan = await this.buildScopedNerScanRequest(options);
        if (!scopeScan) {
            throw new Error('Choose an Atlas scope with rendered note text before running Dynamic NER.');
        }
        await this.ner.runDynamicScan(scopeScan.request);
        const suggestions = this.ner.suggestions().length;
        const documentLabel = scopeScan.documentCount === 1 ? '1 document' : `${scopeScan.documentCount} documents`;
        this.machine.setNotice(`Dynamic NER scan complete for ${documentLabel}. ${suggestions} exportable candidate${suggestions === 1 ? '' : 's'} available for review.`);
        return { suggestions, documents: scopeScan.documentCount, exportableMentions: suggestions };
    }

    private runTextGraphScan(policy: 'dirty-only' | 'force', options: AtlasRunOptions): Promise<unknown> {
        void policy;
        void options;
        return rejectAtlasRichScan();
    }

    private runSemanticAtlasScan(options: AtlasRunOptions, policy: 'dirty-only' | 'force' = 'dirty-only'): Promise<unknown> {
        void options;
        void policy;
        return rejectAtlasRichScan();
    }

    private async runManifoldSnapshot(manifold: AtlasManifoldMode, options: AtlasRunOptions): Promise<unknown> {
        const load = this.machine.beginManifoldLoad(manifold);
        try {
            const snapshot = await this.phoenixUiApi.loadManifoldAtlasSnapshot(manifold, this.searchScope(options));
            if (this.machine.isCurrentManifoldLoad(load)) {
                this.machine.finishManifoldLoad(load, manifoldReadyLabel(manifold), manifoldSnapshotDetails(snapshot));
            }
            return snapshot;
        } catch (error) {
            if (this.machine.isCurrentManifoldLoad(load)) {
                this.machine.failManifoldLoad(load, error);
            }
            throw error;
        }
    }

    private async runRetrievalWalk(options: AtlasRunOptions): Promise<unknown> {
        const query = (options.query || '').trim();
        if (!query) {
            this.machine.setNotice('Retrieval Walk is read-only and ready. Enter a query to execute ranked retrieval.');
            return [];
        }
        return this.machine.search(query, 60, this.searchScope(options));
    }

    private async runNativeStoreProbe(id: AtlasCapabilityId): Promise<unknown> {
        const config = NATIVE_STORE_PROBES[id];
        if (!config) {
            throw new Error(`${atlasCapabilityById(id).label} does not have a registered read-only store probe.`);
        }
        const payload = config.filter
            ? { relation: config.relation, filter: config.filter }
            : { relation: config.relation };
        const rows = await this.phoenix.storeCommand(config.relation === 'runtime:capabilities' ? 'runtime:capabilities' : 'relation:list', payload);
        const rowList = Array.isArray(rows) ? rows : [];
        this.machine.setNotice(`${atlasCapabilityById(id).label} probe returned ${rowList.length} ${config.rowLabel}${rowList.length === 1 ? '' : 's'}. No graph data was mutated.`);
        return {
            capabilityId: id,
            command: 'relation:list',
            relation: config.relation,
            filter: config.filter || null,
            count: rowList.length,
            sample: rowList.slice(0, 5),
        };
    }

    private async runNliAdjudication(options: AtlasRunOptions): Promise<unknown> {
        const documentIds = Array.from(new Set((options.noteIds || noteIdsFromBuildScope(options.buildScope)).filter(Boolean)));
        const planStarted = performance.now();
        const dimensionLabel = this.embeddingDimensionLabel(options);
        const dimension = this.embeddingDimension(options);
        const inputsPayload = await this.phoenix.storeCommand('semantic:listNliJudgmentInputs', {
            documentIds,
            modelId: NLI_MODEL_ID,
            embeddingModelId: this.embeddingModelId(options),
            dimensionLabel,
            dimension,
        });
        const rawInputCount = Array.isArray(inputsPayload) ? inputsPayload.length : 0;
        const inputs = normalizeNliInputs(inputsPayload);
        const plannedInputs = uniqueNliInputs(inputs);
        const stageSummaries = [nliStageSummary('candidatePlan', planStarted, {
            rawInputs: rawInputCount,
            validInputs: inputs.length,
            plannedInputs: plannedInputs.length,
            duplicateInputs: Math.max(0, inputs.length - plannedInputs.length),
            uniquePairs: uniqueNliPairCount(plannedInputs),
            documentIds: documentIds.length,
        })];
        if (!plannedInputs.length) {
            this.machine.setNotice('NLI adjudication queue is empty for the current scope. No graph data was mutated.');
            return {
                inputCount: inputs.length,
                plannedInputCount: 0,
                duplicateInputCount: Math.max(0, inputs.length - plannedInputs.length),
                modelId: NLI_MODEL_ID,
                dimensionLabel,
                dimension,
                applied: null,
                stageSummaries,
            };
        }

        const results: NliClassificationResult[] = [];
        let labelCounts: Record<string, number> = {};
        let applied: unknown = null;
        let device = this.nli.device();
        const warmStarted = performance.now();
        let releaseStarted = warmStarted;
        try {
            await this.nli.withEphemeralSession(NLI_MODEL_ID, async () => {
                stageSummaries.push(nliStageSummary('modelWarm', warmStarted, {
                    plannedInputs: plannedInputs.length,
                }));

                const classifyStarted = performance.now();
                await this.nli.classifyStream(
                    plannedInputs,
                    (batch) => results.push(...batch.results),
                    NLI_BATCH_SIZE,
                );
                labelCounts = results.reduce((counts, result) => {
                    counts[result.predictedLabel] = (counts[result.predictedLabel] || 0) + 1;
                    return counts;
                }, {} as Record<string, number>);
                stageSummaries.push(nliStageSummary('classification', classifyStarted, {
                    plannedInputs: plannedInputs.length,
                    results: results.length,
                    batches: Math.ceil(plannedInputs.length / NLI_BATCH_SIZE),
                    entailment: labelCounts['entailment'] || 0,
                    neutral: labelCounts['neutral'] || 0,
                    contradiction: labelCounts['contradiction'] || 0,
                }));

                const applyStarted = performance.now();
                device = this.nli.device();
                applied = await this.phoenix.storeCommand('semantic:applyNliJudgments', {
                    modelId: NLI_MODEL_ID,
                    embeddingModelId: this.embeddingModelId(options),
                    dimensionLabel,
                    dimension,
                    device,
                    results,
                });
                stageSummaries.push(nliStageSummary('apply', applyStarted, {
                    results: results.length,
                    appliedRows: appliedRowCount(applied),
                }));
                releaseStarted = performance.now();
            });
        } finally {
            stageSummaries.push(nliStageSummary('modelRelease', releaseStarted, {
                released: this.nli.residencySnapshot().resident ? 0 : 1,
            }));
        }
        this.machine.setNotice(`NLI adjudication classified ${results.length} pair${results.length === 1 ? '' : 's'} and applied native candidate-edge judgments.`);
        return {
            inputCount: inputs.length,
            plannedInputCount: plannedInputs.length,
            duplicateInputCount: Math.max(0, inputs.length - plannedInputs.length),
            resultCount: results.length,
            labelCounts,
            modelId: NLI_MODEL_ID,
            dimensionLabel,
            dimension,
            stageSummaries,
            judgments: results.map((result) => ({
                judgmentId: result.judgmentId,
                groupId: result.groupId,
                sourceId: result.sourceId,
                targetId: result.targetId,
                edgeType: result.edgeType,
                predictedLabel: result.predictedLabel,
                confidence: result.confidence,
                entailment: result.entailment,
                neutral: result.neutral,
                contradiction: result.contradiction,
            })),
            applied,
        };
    }

    private openGraphVisualization(options: AtlasRunOptions): { opened: true } {
        this.machine.requestGraphFocus({
            query: (options.query || '').trim(),
            scope: options.scope || this.machine.scope(),
        });
        this.hub.openPage('graph');
        this.machine.setNotice('Loaded current graph snapshot for visualization. No backend mutation was run.');
        return { opened: true };
    }

    private async buildScopedNerScanRequest(options: AtlasRunOptions): Promise<NerScopeScanRequest | null> {
        const documents = await this.loadScopedNerDocuments(options);
        const textDocuments = documents
            .map((document) => ({
                ...document,
                plainText: parseContentToPlainText(document.content).trim(),
            }))
            .filter((document) => document.plainText.length > 0);

        if (!textDocuments.length) return null;
        if (textDocuments.length === 1) {
            const document = textDocuments[0];
            return {
                documentCount: 1,
                request: {
                    noteId: document.id,
                    noteTitle: document.title,
                    plainText: document.plainText,
                },
            };
        }

        return {
            documentCount: textDocuments.length,
            request: {
                noteId: this.nerScopeRequestId(options),
                noteTitle: this.nerScopeTitle(options, textDocuments.length),
                plainText: textDocuments.map((document) => document.plainText).join('\n\n'),
            },
        };
    }

    private async loadScopedNerDocuments(options: AtlasRunOptions): Promise<NerScopeDocument[]> {
        const active = this.activeNerDocument();
        const explicitNoteIds = uniqueIds(options.noteIds?.length
            ? options.noteIds
            : noteIdsFromBuildScope(options.buildScope));

        if (explicitNoteIds.length) return this.loadNerDocumentsByIds(explicitNoteIds, active);
        if (options.buildScope?.mode === 'note' || options.buildScope?.mode === 'multiNote') return [];
        if (options.buildScope?.mode === 'folder') return this.loadNerDocumentsByFolder(options.buildScope.folderId, active);
        if (options.buildScope?.mode === 'global') return this.loadAllNerDocuments(active);

        const scope = options.scope || this.machine.scope();
        if (scope && scope !== 'global') return this.loadNerDocumentsByFolder(scope, active);
        return active ? [active] : [];
    }

    private async loadNerDocumentsByIds(ids: string[], active: NerScopeDocument | null): Promise<NerScopeDocument[]> {
        const activeId = active?.id || '';
        const missingIds = ids.filter((id) => id !== activeId);
        const rows = missingIds.length ? await db.notes.bulkGet(missingIds) : [];
        const byId = new Map<string, NerScopeDocument>();

        for (const row of rows) {
            const document = this.toNerDocument(row);
            if (document) byId.set(document.id, document);
        }
        if (active) byId.set(active.id, active);

        return ids.map((id) => byId.get(id)).filter(isNerScopeDocument);
    }

    private async loadNerDocumentsByFolder(folderId: string, active: NerScopeDocument | null): Promise<NerScopeDocument[]> {
        if (!folderId) return [];
        const rows = await db.notes.where('folderId').equals(folderId).toArray();
        return this.overlayActiveNerDocument(rows.map((row) => this.toNerDocument(row)).filter(isNerScopeDocument), active, active?.folderId === folderId);
    }

    private async loadAllNerDocuments(active: NerScopeDocument | null): Promise<NerScopeDocument[]> {
        const rows = await db.notes.toArray();
        return this.overlayActiveNerDocument(rows.map((row) => this.toNerDocument(row)).filter(isNerScopeDocument), active, !!active);
    }

    private overlayActiveNerDocument(
        documents: NerScopeDocument[],
        active: NerScopeDocument | null,
        includeActive: boolean,
    ): NerScopeDocument[] {
        if (!active || !includeActive) return documents;
        const byId = new Map(documents.map((document) => [document.id, document]));
        byId.set(active.id, active);
        return Array.from(byId.values());
    }

    private activeNerDocument(): NerScopeDocument | null {
        return this.toNerDocument(this.noteStore.currentNote());
    }

    private toNerDocument(note: {
        id?: string;
        title?: string;
        content?: string;
        markdownContent?: string;
        folderId?: string;
    } | null | undefined): NerScopeDocument | null {
        const id = String(note?.id || '').trim();
        if (!id) return null;
        return {
            id,
            title: String(note?.title || 'Untitled Note'),
            content: String(note?.content || note?.markdownContent || ''),
            folderId: String(note?.folderId || ''),
        };
    }

    private nerScopeRequestId(options: AtlasRunOptions): string {
        const scope = options.buildScope;
        if (scope?.mode === 'folder') return `scope:folder:${scope.folderId}`;
        if (scope?.mode === 'global') return 'scope:global';
        return 'scope:multiNote';
    }

    private nerScopeTitle(options: AtlasRunOptions, documentCount: number): string {
        const scope = options.buildScope;
        if (scope?.mode === 'folder') return `Folder scope (${documentCount} notes)`;
        if (scope?.mode === 'global') return `Global scope (${documentCount} notes)`;
        return `${documentCount} selected notes`;
    }

    private runtimeRecipeDefinition(id: AtlasRecipeId, options: AtlasRunOptions): AtlasRuntimeRecipeDefinition {
        const dynamicNer = this.dynamicNerRequirement(true);
        const semantic = this.semanticEmbeddingRequirement(options, true);
        const nli = this.nliRequirement(true);
        const buildPolicy = options.buildPolicy === 'force' ? 'force' : 'dirty-only';
        const buildMutationPolicy = buildPolicy === 'force' ? 'force rebuild' : 'dirty-only';
        const richScanBlockedReason = ATLAS_RICH_SCAN_QUARANTINE_MESSAGE;
        const semanticCoreCapabilities: AtlasCapabilityId[] = [
            ...TEXT_GRAPH_CAPABILITIES,
            'semanticEmbedding',
            'semanticAtlas',
            'semanticCandidate',
        ];
        const semanticCapabilities: AtlasCapabilityId[] = [
            ...semanticCoreCapabilities,
            ...MANIFOLD_PROJECTION_CAPABILITIES,
        ];
        const adjudicatedCapabilities: AtlasCapabilityId[] = [
            ...semanticCapabilities,
            'nliAdjudication',
        ];
        const reasoningCapabilities: AtlasCapabilityId[] = [
            ...adjudicatedCapabilities,
            'relationGraph',
            'eventIdentity',
            'temporalGraph',
            'memoryState',
            'causalGraph',
        ];
        const entityAnchorOperations: AtlasRuntimeOperation[] = [
            warmOperation('dynamicNer'),
            { kind: 'dynamicNerScan', service: 'NerService.runDynamicScan', policy: 'read-only' },
        ];
        const semanticOperations: AtlasRuntimeOperation[] = [
            ...entityAnchorOperations,
            warmOperation('semanticEmbedding'),
            { kind: 'semanticAtlasScan', service: 'quarantined', policy: buildPolicy },
            ...MANIFOLD_PROJECTION_OPERATIONS,
        ];
        const adjudicationOperations: AtlasRuntimeOperation[] = [
            ...semanticOperations,
            warmOperation('nli'),
            { kind: 'nliAdjudication', service: 'PhoenixBackendService.storeCommand + NliWorkerService.classifyStream', policy: 'native-only' },
        ];

        switch (id) {
            case 'textGraph':
                return {
                    requiredCapabilities: TEXT_GRAPH_CAPABILITIES,
                    optionalCapabilities: [] as AtlasCapabilityId[],
                    skippedCapabilities: ['semanticEmbedding', 'semanticAtlas', 'semanticCandidate', 'nliAdjudication', 'hybridManifold', 'hopfProjection', 'lorentzForest', 'productManifold', 'retrievalWalk', 'galaxyVisualization', 'relationGraph', 'temporalGraph', 'eventIdentity', 'memoryState', 'causalGraph'] as AtlasCapabilityId[],
                    dependencyChain: TEXT_GRAPH_CAPABILITIES,
                    requiredModels: [dynamicNer],
                    optionalModels: [],
                    operations: [
                        ...entityAnchorOperations,
                        { kind: 'richTextGraphScan', service: 'quarantined', policy: buildPolicy },
                    ] as AtlasRuntimeOperation[],
                    expectedOutputs: [
                        expected('candidateSuggestions', 'entity anchors', 'NerService.suggestions()'),
                        expected('graphDeltaCounts', 'graph delta counts', 'AtlasRichScanResult.graphDeltaCounts'),
                        expected('graphAudit.graphNodes', 'graph nodes', 'PhoenixMachineControlService.graphAudit'),
                        expected('graphAudit.graphEdges', 'graph edges', 'PhoenixMachineControlService.graphAudit'),
                    ],
                    mutationPolicy: buildMutationPolicy as AtlasCapabilityMutationPolicy,
                    runPolicy: buildPolicy as AtlasCapabilityRunPolicy,
                    backendRoute: QUARANTINED_RICH_SCAN_ROUTE,
                    runnable: false,
                    blockedReason: richScanBlockedReason,
                    skippedLanes: ['semanticEmbedding', 'nli', 'manifoldProjection'] as AtlasModelLaneId[],
                };
            case 'semanticGraph':
                return {
                    requiredCapabilities: semanticCapabilities,
                    optionalCapabilities: [] as AtlasCapabilityId[],
                    skippedCapabilities: ['nliAdjudication', 'relationGraph', 'temporalGraph', 'eventIdentity', 'memoryState', 'causalGraph'] as AtlasCapabilityId[],
                    dependencyChain: semanticCapabilities,
                    requiredModels: [dynamicNer, semantic],
                    optionalModels: [],
                    operations: semanticOperations,
                    expectedOutputs: [
                        expected('candidateSuggestions', 'entity anchors', 'NerService.suggestions()'),
                        expected('embeddingCounts', 'leaf/entity/lens vectors', 'AtlasRichScanResult.embeddingCounts'),
                        expected('graphDeltaCounts.candidateEdges', 'candidate links', 'AtlasRichScanResult.graphDeltaCounts.candidateEdges'),
                        expected('relationCandidateCount', 'relation candidates', 'AtlasRichScanResult.relationCandidateCount'),
                        expected('manifoldSnapshot.hybrid', 'Hybrid embedding manifold', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(hybrid)'),
                        expected('manifoldSnapshot.hopf', 'Hopf projection', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(hopf)'),
                        expected('manifoldSnapshot.lorentz', 'Lorentz forest', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(lorentz)'),
                        expected('manifoldSnapshot.product', 'Product manifold', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(product)'),
                    ],
                    mutationPolicy: buildMutationPolicy as AtlasCapabilityMutationPolicy,
                    runPolicy: buildPolicy as AtlasCapabilityRunPolicy,
                    backendRoute: QUARANTINED_RICH_SCAN_ROUTE,
                    runnable: false,
                    blockedReason: richScanBlockedReason,
                    skippedLanes: ['nli'] as AtlasModelLaneId[],
                };
            case 'adjudicatedSemanticGraph':
                return {
                    requiredCapabilities: adjudicatedCapabilities,
                    optionalCapabilities: [] as AtlasCapabilityId[],
                    skippedCapabilities: ['relationGraph', 'temporalGraph', 'eventIdentity', 'memoryState', 'causalGraph'] as AtlasCapabilityId[],
                    dependencyChain: adjudicatedCapabilities,
                    requiredModels: [dynamicNer, semantic, nli],
                    optionalModels: [],
                    operations: adjudicationOperations,
                    expectedOutputs: [
                        expected('candidateSuggestions', 'entity anchors', 'NerService.suggestions()'),
                        expected('embeddingCounts', 'leaf/entity/lens vectors', 'AtlasRichScanResult.embeddingCounts'),
                        expected('relationCandidateCount', 'candidate relations', 'AtlasRichScanResult.relationCandidateCount'),
                        expected('manifoldSnapshot.hybrid', 'Hybrid embedding manifold', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(hybrid)'),
                        expected('manifoldSnapshot.hopf', 'Hopf projection', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(hopf)'),
                        expected('manifoldSnapshot.lorentz', 'Lorentz forest', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(lorentz)'),
                        expected('manifoldSnapshot.product', 'Product manifold', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(product)'),
                        expected('nliJudgments', 'NLI candidate-edge judgments', 'semantic:applyNliJudgments'),
                    ],
                    mutationPolicy: buildMutationPolicy as AtlasCapabilityMutationPolicy,
                    runPolicy: buildPolicy as AtlasCapabilityRunPolicy,
                    backendRoute: `Semantic graph -> semantic:listNliJudgmentInputs -> semantic:applyNliJudgments`,
                    runnable: false,
                    blockedReason: richScanBlockedReason,
                    skippedLanes: [] as AtlasModelLaneId[],
                };
            case 'reasoningGraph':
                return {
                    requiredCapabilities: reasoningCapabilities,
                    optionalCapabilities: [] as AtlasCapabilityId[],
                    skippedCapabilities: [] as AtlasCapabilityId[],
                    dependencyChain: reasoningCapabilities,
                    requiredModels: [dynamicNer, semantic, nli],
                    optionalModels: [],
                    operations: [
                        ...adjudicationOperations,
                        { kind: 'nativeStoreProbe', service: 'PhoenixBackendService.storeCommand', policy: 'read-only', args: { capabilityId: 'relationGraph' } },
                        { kind: 'nativeStoreProbe', service: 'PhoenixBackendService.storeCommand', policy: 'read-only', args: { capabilityId: 'eventIdentity' } },
                        { kind: 'nativeStoreProbe', service: 'PhoenixBackendService.storeCommand', policy: 'read-only', args: { capabilityId: 'temporalGraph' } },
                        { kind: 'nativeStoreProbe', service: 'PhoenixBackendService.storeCommand', policy: 'read-only', args: { capabilityId: 'memoryState' } },
                        { kind: 'nativeStoreProbe', service: 'PhoenixBackendService.storeCommand', policy: 'read-only', args: { capabilityId: 'causalGraph' } },
                    ] as AtlasRuntimeOperation[],
                    expectedOutputs: [
                        expected('manifoldSnapshot.hybrid', 'Hybrid embedding manifold', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(hybrid)'),
                        expected('manifoldSnapshot.hopf', 'Hopf projection', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(hopf)'),
                        expected('manifoldSnapshot.lorentz', 'Lorentz forest', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(lorentz)'),
                        expected('manifoldSnapshot.product', 'Product manifold', 'PhoenixUiApiService.loadManifoldAtlasSnapshot(product)'),
                        expected('nliJudgments', 'NLI candidate-edge judgments', 'semantic:applyNliJudgments'),
                        expected('graph_candidate_edges', 'relation rows', 'relation:list(graph_candidate_edges)'),
                        expected('graph_edges.active_during', 'temporal rows', 'relation:list(graph_edges, active_during)'),
                        expected('memories', 'memory rows', 'relation:list(memories)'),
                        expected('graph_edges.causal_link', 'causal rows', 'relation:list(graph_edges, causal_link)'),
                    ],
                    mutationPolicy: 'native-only' as AtlasCapabilityMutationPolicy,
                    runPolicy: 'native-only' as AtlasCapabilityRunPolicy,
                    backendRoute: 'Adjudicated semantic graph -> relation/event/temporal/memory/causal native probes',
                    runnable: false,
                    blockedReason: richScanBlockedReason,
                    skippedLanes: [] as AtlasModelLaneId[],
                };
            case 'runNer':
                return {
                    requiredCapabilities: ['dynamicSurface', 'dynamicNer'] as AtlasCapabilityId[],
                    optionalCapabilities: [] as AtlasCapabilityId[],
                    skippedCapabilities: this.allExcept(['dynamicSurface', 'dynamicNer']),
                    dependencyChain: ['dynamicSurface', 'dynamicNer'] as AtlasCapabilityId[],
                    requiredModels: [dynamicNer],
                    optionalModels: [],
                    operations: [
                        warmOperation('dynamicNer'),
                        { kind: 'dynamicNerScan', service: 'NerService.runDynamicScan', policy: 'read-only' },
                    ] as AtlasRuntimeOperation[],
                    expectedOutputs: [expected('candidateSuggestions', 'candidate suggestions', 'NerService.suggestions()')],
                    mutationPolicy: 'read-only' as AtlasCapabilityMutationPolicy,
                    runPolicy: 'read-only' as AtlasCapabilityRunPolicy,
                    backendRoute: 'NerService.runDynamicScan / PhoenixUiApi.scanDiscovery / scan_json',
                    runnable: true,
                    skippedLanes: ['semanticEmbedding', 'nli', 'manifoldProjection'] as AtlasModelLaneId[],
                };
        }
    }

    private operationKindForCapability(id: AtlasCapabilityId): AtlasCapabilityOperationKind {
        if (id === 'dynamicNer') return 'dynamicNerScan';
        if (TEXT_GRAPH_CAPABILITIES.includes(id)) return 'richTextGraphScan';
        if (id === 'semanticEmbedding') return 'modelWarm';
        if (NATIVE_STORE_PROBE_CAPABILITIES.includes(id)) return 'nativeStoreProbe';
        if (id === 'nliAdjudication') return 'nliAdjudication';
        if (SEMANTIC_SCAN_CAPABILITIES.includes(id)) return 'semanticAtlasScan';
        if (id === 'galaxyVisualization') return 'graphVisualization';
        if (id === 'retrievalWalk') return 'retrievalWalk';
        if (MANIFOLD_CAPABILITIES[id]) return 'manifoldSnapshot';
        return 'notWired';
    }

    private requiredModelsForCapability(id: AtlasCapabilityId, options: AtlasRunOptions): AtlasModelRequirement[] {
        if (id === 'dynamicNer') return [this.dynamicNerRequirement(true)];
        if (id === 'semanticEmbedding' || SEMANTIC_SCAN_CAPABILITIES.includes(id)) {
            return [this.semanticEmbeddingRequirement(options, true)];
        }
        if (id === 'nliAdjudication') return [this.nliRequirement(true)];
        return [];
    }

    private requiredServicesForCapability(id: AtlasCapabilityId, options: AtlasRunOptions): AtlasServiceRequirement[] {
        const blockedReason = this.blockedReasonForCapability(id);
        if (blockedReason) {
            return [service('atlas-rich-scan-quarantine', 'Quarantined legacy scan', 'none', 'none', false, blockedReason)];
        }
        if (id === 'nliAdjudication') {
            return [
                service('nli-worker', 'NLI worker classify/apply', 'NliWorkerService.classifyStream', NLI_MODEL_ID, true),
                service('nli-store-queue', 'Native NLI queue + apply', 'PhoenixBackendService.storeCommand', 'semantic:listNliJudgmentInputs → semantic:applyNliJudgments', true),
            ];
        }
        const operationKind = this.operationKindForCapability(id);
        switch (operationKind) {
            case 'dynamicNerScan':
                return [service('dynamic-ner', 'Dynamic NER scan', 'NerService.runDynamicScan', 'PhoenixUiApi.scanDiscovery / scan_json', true)];
            case 'richTextGraphScan':
                return [service('atlas-rich-scan-quarantine', 'Quarantined legacy scan', 'none', 'none', false, ATLAS_RICH_SCAN_QUARANTINE_MESSAGE)];
            case 'semanticAtlasScan':
                return [service('atlas-rich-scan-quarantine', 'Quarantined legacy scan', 'none', 'none', false, ATLAS_RICH_SCAN_QUARANTINE_MESSAGE)];
            case 'nativeStoreProbe': {
                const config = NATIVE_STORE_PROBES[id];
                return [service('native-store-probe', config?.label || 'Native store probe', 'PhoenixBackendService.storeCommand', config ? `relation:list(${config.relation})` : 'relation:list', true)];
            }
            case 'nliAdjudication':
                return [
                    service('nli-worker', 'NLI worker classify/apply', 'NliWorkerService.classifyStream', NLI_MODEL_ID, true),
                    service('nli-store-queue', 'Native NLI queue + apply', 'PhoenixBackendService.storeCommand', 'semantic:listNliJudgmentInputs -> semantic:applyNliJudgments', true),
                ];
            case 'modelWarm':
                return [service('semantic-model', 'Semantic model loader', 'PhoenixMachineControlService.loadSemanticModel', this.embeddingModelLabel(options), true)];
            case 'manifoldSnapshot': {
                const mode = manifoldModeForCapability(id);
                return [service('manifold-snapshot', `${manifoldModeLabel(mode)} snapshot`, 'PhoenixUiApiService.loadManifoldAtlasSnapshot', `manifold_snapshot_json(${mode})`, true)];
            }
            case 'graphVisualization':
                return [service('graph-focus', 'Graph focus', 'PhoenixMachineControlService.requestGraphFocus', 'BlueprintHubService.openPage(graph)', true)];
            case 'retrievalWalk':
                return [service('retrieval-walk', 'Retrieval walk', 'PhoenixMachineControlService.search', 'PhoenixUiApi.searchScoped', true)];
            case 'nativeReasoningPass':
            case 'notWired':
                return [service('missing-runtime-binding', 'Missing runtime binding', 'not registered', 'not wired', false, this.blockedReasonForCapability(id))];
        }
    }

    private runPolicyForCapability(id: AtlasCapabilityId): AtlasCapabilityRunPolicy {
        if (id === 'semanticEmbedding') return 'warm-only';
        if (id === 'nliAdjudication') return 'native-only';
        if (NATIVE_STORE_PROBE_CAPABILITIES.includes(id)) return 'read-only';
        if (id === 'dynamicNer' || id === 'retrievalWalk' || id === 'galaxyVisualization' || MANIFOLD_CAPABILITIES[id]) return 'read-only';
        if (SEMANTIC_SCAN_CAPABILITIES.includes(id) || TEXT_GRAPH_CAPABILITIES.includes(id)) return 'dirty-only';
        return 'native-only';
    }

    private mutationPolicyForCapability(
        id: AtlasCapabilityId,
        fallback: AtlasCapabilityMutationPolicy,
    ): AtlasCapabilityMutationPolicy {
        if (id === 'dynamicNer' || id === 'retrievalWalk' || id === 'galaxyVisualization' || MANIFOLD_CAPABILITIES[id]) {
            return 'read-only';
        }
        if (NATIVE_STORE_PROBE_CAPABILITIES.includes(id)) return 'read-only';
        if (id === 'semanticEmbedding') return 'model warm';
        if (id === 'nliAdjudication') return 'native-only';
        if (SEMANTIC_SCAN_CAPABILITIES.includes(id) || TEXT_GRAPH_CAPABILITIES.includes(id)) return 'dirty-only';
        return fallback;
    }

    private blockedReasonForCapability(id: AtlasCapabilityId): string | undefined {
        if (QUARANTINED_RICH_SCAN_CAPABILITIES.has(id)) {
            return ATLAS_RICH_SCAN_QUARANTINE_MESSAGE;
        }
        return undefined;
    }

    private readinessProbeForCapability(
        id: AtlasCapabilityId,
        operationKind: AtlasCapabilityOperationKind,
        blockedReason?: string,
    ) {
        if (blockedReason) {
            return {
                label: 'Not wired',
                status: 'blocked' as const,
                source: 'AtlasCapabilityRuntimeService',
                detail: blockedReason,
            };
        }
        switch (operationKind) {
            case 'dynamicNerScan': {
                const status = this.ner.providerStatuses().dynamic_ner;
                const runtimeStatus = this.ner.isAnalyzing()
                    ? 'running'
                    : status.loading
                        ? 'warming'
                        : status.error
                            ? 'error'
                            : status.ready
                                ? 'ready'
                                : 'idle';
                return probe('Dynamic NER provider', runtimeStatus, 'NerService.providerStatuses.dynamic_ner', status.error || (status.ready ? 'provider ready' : 'provider cold'));
            }
            case 'richTextGraphScan':
                return probe('Text graph runtime', graphStatusToRuntime(this.machine.graphStatus()), 'PhoenixMachineControlService.graphStatus', this.machine.hasCommittedGraph() ? 'committed graph present' : 'ready to run atlas_rich_scan');
            case 'semanticAtlasScan':
            case 'modelWarm':
                return probe('Semantic embedding runner', vectorStatusToRuntime(this.machine.vectorStatus()), 'PhoenixMachineControlService.vectorStatus + native Rust semantic runner', this.machine.vectorStatus());
            case 'nativeStoreProbe': {
                const config = NATIVE_STORE_PROBES[id];
                return probe(config?.label || 'Native store probe', 'ready', 'PhoenixBackendService.storeCommand', config ? `read-only relation:list probe for ${config.relation}` : 'read-only store probe registered');
            }
            case 'nliAdjudication': {
                const runtimeStatus = this.nli.isProcessing()
                    ? 'running'
                    : this.nli.isInitialized()
                        ? 'ready'
                        : 'idle';
                return probe('NLI adjudication queue', runtimeStatus, 'semantic:listNliJudgmentInputs + NliWorkerService.classifyStream', this.nli.isInitialized() ? 'NLI worker ready to classify native queue inputs' : 'NLI worker cold; queue can be listed before model warm');
            }
            case 'manifoldSnapshot': {
                const mode = MANIFOLD_CAPABILITIES[id] || 'hybrid';
                return probe(`${mode} manifold snapshot`, manifoldStatusToRuntime(this.machine.manifoldStatuses()[mode]), `PhoenixMachineControlService.manifoldStatuses.${mode}`, this.machine.manifoldStatuses()[mode]);
            }
            case 'graphVisualization':
                return probe('Graph visualization', this.machine.hasCommittedGraph() ? 'ready' : 'idle', 'PhoenixMachineControlService.graphAudit', this.machine.hasCommittedGraph() ? 'graph snapshot available' : 'no committed graph snapshot yet');
            case 'retrievalWalk':
                return probe('Retrieval lanes', this.machine.activeLanes().length ? 'ready' : 'idle', 'RetrievalWorkbenchStateService.activeLanes', this.machine.activeLanes().join(' + ') || 'lexical fallback');
            case 'nativeReasoningPass':
            case 'notWired':
                return probe('Not wired', 'blocked', 'AtlasCapabilityRuntimeService', 'runtime binding missing');
        }
    }

    private outputProbeForCapability(id: AtlasCapabilityId, operationKind: AtlasCapabilityOperationKind): AtlasOutputProbe {
        switch (operationKind) {
            case 'dynamicNerScan':
                return output('Candidate suggestions', 'NerService.suggestions()', `${this.ner.suggestions().length} current candidates`, this.ner.suggestions().length);
            case 'richTextGraphScan':
                return output('Graph audit + delta counts', 'AtlasRichScanResult.graphDeltaCounts + GraphAuditService.snapshot', `${this.machine.graphNodes()} nodes / ${this.machine.graphEdges()} edges`, this.machine.graphNodes() + this.machine.graphEdges());
            case 'semanticAtlasScan': {
                return output('Quarantined legacy output', 'AtlasCapabilityRuntimeService', ATLAS_RICH_SCAN_QUARANTINE_MESSAGE, null);
            }
            case 'nativeStoreProbe': {
                const config = NATIVE_STORE_PROBES[id];
                return output('Read-only native store rows', config ? `relation:list(${config.relation})` : 'relation:list', config ? `${config.label}; no mutation` : 'read-only probe; no mutation', null);
            }
            case 'nliAdjudication':
                return output('NLI candidate-edge judgments', 'semantic:applyNliJudgments', 'classified entailment/contradiction rows applied to native candidate graph', this.nli.isInitialized() ? 'worker ready' : 'worker cold');
            case 'modelWarm':
                return output('Model readiness', 'PhoenixMachineControlService.vectorStatus', this.machine.vectorStatus(), this.machine.vectorStatus());
            case 'manifoldSnapshot': {
                const mode = manifoldModeForCapability(id);
                return output(`${manifoldModeLabel(mode)} snapshot`, 'PhoenixUiApiService.loadManifoldAtlasSnapshot', `${mode} payload / topology rows`, this.machine.manifoldStatuses()[mode]);
            }
            case 'graphVisualization':
                return output('Graph lens focus', 'PhoenixMachineControlService.graphFocus', this.machine.graphFocus() ? 'focus requested' : 'graph tab opens current snapshot', this.machine.graphFocus() ? 'focused' : 'idle');
            case 'retrievalWalk':
                return output('Ranked results', 'PhoenixMachineControlService.search', 'query-time ranked hits', this.machine.activeLanes().join(' + ') || 'lexical');
            case 'nativeReasoningPass':
            case 'notWired':
                return output('No output', 'not wired', this.blockedReasonForCapability(id) || 'runtime binding missing', null);
        }
    }

    private recipeOutputProof(id: AtlasRecipeId): AtlasOutputProbe[] {
        switch (id) {
            case 'textGraph':
                return [this.outputProbeForCapability('assertedKernel', 'richTextGraphScan')];
            case 'semanticGraph':
                return [
                    this.outputProbeForCapability('semanticAtlas', 'semanticAtlasScan'),
                    this.outputProbeForCapability('hybridManifold', 'manifoldSnapshot'),
                    this.outputProbeForCapability('hopfProjection', 'manifoldSnapshot'),
                    this.outputProbeForCapability('lorentzForest', 'manifoldSnapshot'),
                    this.outputProbeForCapability('productManifold', 'manifoldSnapshot'),
                ];
            case 'adjudicatedSemanticGraph':
                return [
                    this.outputProbeForCapability('semanticAtlas', 'semanticAtlasScan'),
                    this.outputProbeForCapability('hybridManifold', 'manifoldSnapshot'),
                    this.outputProbeForCapability('hopfProjection', 'manifoldSnapshot'),
                    this.outputProbeForCapability('lorentzForest', 'manifoldSnapshot'),
                    this.outputProbeForCapability('productManifold', 'manifoldSnapshot'),
                    this.outputProbeForCapability('nliAdjudication', 'nliAdjudication'),
                ];
            case 'reasoningGraph':
                return [
                    this.outputProbeForCapability('semanticAtlas', 'semanticAtlasScan'),
                    this.outputProbeForCapability('hybridManifold', 'manifoldSnapshot'),
                    this.outputProbeForCapability('hopfProjection', 'manifoldSnapshot'),
                    this.outputProbeForCapability('lorentzForest', 'manifoldSnapshot'),
                    this.outputProbeForCapability('productManifold', 'manifoldSnapshot'),
                    this.outputProbeForCapability('nliAdjudication', 'nliAdjudication'),
                    this.outputProbeForCapability('relationGraph', 'nativeStoreProbe'),
                    this.outputProbeForCapability('eventIdentity', 'nativeStoreProbe'),
                    this.outputProbeForCapability('temporalGraph', 'nativeStoreProbe'),
                    this.outputProbeForCapability('memoryState', 'nativeStoreProbe'),
                    this.outputProbeForCapability('causalGraph', 'nativeStoreProbe'),
                ];
            case 'runNer':
                return [this.outputProbeForCapability('dynamicNer', 'dynamicNerScan')];
        }
    }

    private dynamicNerRequirement(required: boolean): AtlasModelRequirement {
        const status = this.ner.providerStatuses().dynamic_ner;
        const readiness = this.ner.isAnalyzing()
            ? 'running'
            : status.loading
                ? 'warming'
                : status.error
                    ? 'error'
                    : status.ready
                        ? 'ready'
                        : 'idle';
        return {
            id: 'dynamicNer',
            laneId: 'dynamicNer',
            label: 'BI-small Dynamic NER',
            provider: 'dynamic_ner',
            service: 'NerService.warmProvider(dynamic_ner)',
            required,
            readiness,
            statusLabel: status.error || statusLabel(readiness),
        };
    }

    private semanticEmbeddingRequirement(options: AtlasRunOptions, required: boolean): AtlasModelRequirement {
        const readiness = vectorStatusToRuntime(this.machine.vectorStatus());
        return {
            id: 'semanticEmbedding',
            laneId: 'semanticEmbedding',
            label: this.embeddingModelLabel(options),
            selectedModelId: this.embeddingModelId(options),
            selectedModelLabel: this.embeddingModelLabel(options),
            dims: this.embeddingDimensionLabel(options),
            service: 'PhoenixMachineControlService.loadSemanticModel',
            required,
            readiness,
            statusLabel: this.machine.vectorStatus() === 'ready'
                ? `${this.embeddingModelLabel(options)} ${this.embeddingDimensionLabel(options)} ready`
                : statusLabel(readiness),
        };
    }

    private nliRequirement(required: boolean): AtlasModelRequirement {
        const readiness = this.nli.isProcessing()
            ? 'running'
            : this.nli.isInitialized()
                ? 'ready'
                : 'idle';
        return {
            id: 'nli',
            laneId: 'nli',
            label: 'ModernBERT NLI',
            selectedModelId: NLI_MODEL_ID,
            selectedModelLabel: 'onnx-community ModernBERT NLI',
            service: 'NliWorkerService.initialize',
            required,
            readiness,
            statusLabel: this.nli.modelId() || statusLabel(readiness),
        };
    }

    private embeddingModelId(options: AtlasRunOptions): PhoenixMachineModelId {
        return options.selectedModel || (DEFAULT_GRAPH_EMBEDDING_MODEL_ID as PhoenixMachineModelId);
    }

    private embeddingModelLabel(options: AtlasRunOptions): string {
        return options.selectedModelLabel || (options.selectedModel ? this.embeddingModelId(options) : DEFAULT_GRAPH_EMBEDDING_MODEL_LABEL);
    }

    private embeddingDimensionLabel(options: AtlasRunOptions): string {
        return options.dimensionLabel || DEFAULT_GRAPH_EMBEDDING_DIMENSION_LABEL;
    }

    private embeddingDimension(options: AtlasRunOptions): number {
        if (typeof options.embeddingDimension === 'number'
            && Number.isFinite(options.embeddingDimension)
            && options.embeddingDimension > 0) {
            return Math.floor(options.embeddingDimension);
        }
        const match = this.embeddingDimensionLabel(options).match(/(\d+)/);
        return match ? Number(match[1]) : 0;
    }

    private searchScope(options: AtlasRunOptions): SearchScope | undefined {
        const buildScope = options.buildScope;
        if (buildScope?.mode === 'global') return undefined;
        if (buildScope?.mode === 'folder') return { folderId: buildScope.folderId, folderPath: buildScope.folderId };
        if (buildScope?.mode === 'note') return { mode: 'note', noteId: buildScope.noteId };
        if (buildScope?.mode === 'multiNote') return { mode: 'multiNote', noteIds: buildScope.noteIds };
        const scope = options.scope || this.machine.scope();
        return scope === 'global' ? undefined : { folderId: scope, folderPath: scope };
    }

    private contractScope(options: AtlasRunOptions): AtlasBuildScope {
        if (options.buildScope) return options.buildScope;
        const noteIds = uniqueIds(options.noteIds || []);
        if (noteIds.length === 1) return { mode: 'note', noteId: noteIds[0] };
        if (noteIds.length > 1) return { mode: 'multiNote', noteIds };
        const active = this.activeNerDocument();
        if (active) return { mode: 'note', noteId: active.id };
        const scope = options.scope || this.machine.scope();
        return scope && scope !== 'global'
            ? { mode: 'folder', folderId: scope }
            : { mode: 'global' };
    }

    private optionsFromContract(contract: AtlasBuildContract, options: AtlasRunOptions): AtlasRunOptions {
        return {
            ...options,
            buildScope: contract.scope,
            noteIds: contract.noteIds,
            buildPolicy: contract.policy === 'force' ? 'force' : 'dirty-only',
            ...(contract.embeddingModel ? {
                selectedModel: contract.embeddingModel.id as PhoenixMachineModelId,
                selectedModelLabel: contract.embeddingModel.label,
                dimensionLabel: contract.embeddingModel.dimensionLabel,
            } : {}),
        };
    }

    private allExcept(kept: AtlasCapabilityId[]): AtlasCapabilityId[] {
        const keep = new Set(kept);
        return ATLAS_CAPABILITY_RECIPES
            .flatMap((recipe) => [...recipe.requiredCapabilities, ...recipe.optionalCapabilities, ...recipe.skippedCapabilities])
            .filter((id, index, ids): id is AtlasCapabilityId => !!id && ids.indexOf(id) === index && !keep.has(id));
    }
}

function contractPolicy(runPolicy: AtlasCapabilityRunPolicy): AtlasBuildContract['policy'] {
    if (runPolicy === 'force') return 'force';
    if (runPolicy === 'native-only') return 'native-only';
    if (runPolicy === 'dirty-only') return 'dirty-only';
    return 'read-only';
}

function modelWarmReceipt(model: AtlasModelRequirement): AtlasBuildStageReceipt {
    const capabilityId = modelCapabilityId(model.id);
    const bridge = bridgeCommandForModel(model);
    return {
        stageId: model.id,
        ...(capabilityId ? { capabilityId } : {}),
        operationKind: 'warmModel',
        frontendService: bridge.frontendService,
        backendCommand: bridge.backendCommand,
        backendRoute: bridge.backendRoute,
        commandKind: bridge.commandKind,
        status: 'ran',
        ran: true,
        source: bridge.frontendService,
        summary: `${model.label} warm requested`,
        counts: {},
    };
}

function skippedWarmReceipt(operation: AtlasRuntimeOperation): AtlasBuildStageReceipt {
    const bridge = bridgeCommandForOperation(operation);
    return {
        stageId: bridge.stageId,
        ...(bridge.capabilityId ? { capabilityId: bridge.capabilityId } : {}),
        operationKind: 'warmModel',
        frontendService: bridge.frontendService,
        backendCommand: bridge.backendCommand,
        backendRoute: bridge.backendRoute,
        commandKind: bridge.commandKind,
        status: 'skipped',
        ran: false,
        source: bridge.frontendService,
        summary: 'Model warm was handled before this operation.',
        counts: {},
    };
}

function stageReceiptFromResult(
    result: AtlasCapabilityRunResult,
    operation: AtlasRuntimeOperation,
): AtlasBuildStageReceipt {
    const counts = receiptCounts(result.rawResult);
    const bridge = bridgeCommandForOperation(operation, result.capabilityId);
    return {
        stageId: result.capabilityId,
        capabilityId: result.capabilityId,
        operationKind: result.operationKind,
        frontendService: bridge.frontendService,
        backendCommand: bridge.backendCommand,
        backendRoute: bridge.backendRoute,
        commandKind: bridge.commandKind,
        status: 'ran',
        ran: true,
        source: bridge.frontendService,
        summary: receiptSummary(result.capabilityId, counts),
        counts,
    };
}

function bridgeCommandForModel(model: AtlasModelRequirement): AtlasBridgeCommand {
    const operation = warmOperation(model.id);
    return bridgeCommandForOperation(operation, modelCapabilityId(model.id));
}

function bridgeCommandForOperation(
    operation: AtlasRuntimeOperation,
    capabilityOverride?: AtlasCapabilityId,
): AtlasBridgeCommand {
    const capabilityId = capabilityOverride || operationCapabilityId(operation);
    const stageId = String(capabilityId || operation.model || operation.kind);

    switch (operation.kind) {
        case 'dynamicNerScan':
            return bridge(stageId, capabilityId, operation, 'NerService.runDynamicScan', 'scanDiscovery', 'PhoenixUiApi.scanDiscovery -> PhoenixBackendService.scanDiscovery -> scan_json', 'native');
        case 'richTextGraphScan':
            return bridge(stageId, capabilityId, operation, 'none', 'none', QUARANTINED_RICH_SCAN_ROUTE, 'frontend');
        case 'semanticAtlasScan':
            return bridge(stageId, capabilityId, operation, 'none', 'none', QUARANTINED_RICH_SCAN_ROUTE, 'frontend');
        case 'nliAdjudication':
            return bridge(stageId, capabilityId, operation, 'PhoenixBackendService.storeCommand + NliWorkerService.classifyStream', 'semantic:listNliJudgmentInputs -> semantic:applyNliJudgments', 'native queue -> browser NLI worker -> native apply', 'mixed');
        case 'nativeStoreProbe': {
            const config = capabilityId ? NATIVE_STORE_PROBES[capabilityId] : undefined;
            const route = config
                ? `PhoenixBackendService.storeCommand('relation:list', relation=${config.relation}${config.filter ? `, filter=${JSON.stringify(config.filter)}` : ''})`
                : "PhoenixBackendService.storeCommand('relation:list')";
            return bridge(stageId, capabilityId, operation, 'PhoenixBackendService.storeCommand', 'relation:list', route, 'native');
        }
        case 'manifoldSnapshot': {
            const mode = operation.manifold || manifoldModeForCapability(capabilityId);
            return bridge(stageId, capabilityId, operation, 'PhoenixUiApiService.loadManifoldAtlasSnapshot', `manifoldSnapshot(${mode})`, `PhoenixBackendService.manifoldSnapshot(manifold=${mode}) -> semantic_atlas_rows adapter`, 'native');
        }
        case 'graphVisualization':
            return bridge(stageId, capabilityId, operation, 'PhoenixMachineControlService.requestGraphFocus', 'none', 'frontend graph lens focus only', 'frontend');
        case 'retrievalWalk':
            return bridge(stageId, capabilityId, operation, 'PhoenixMachineControlService.search', 'query', 'PhoenixUiApi.searchScoped -> native query', 'native');
        case 'warmModel':
        case 'modelWarm':
            if (operation.model === 'dynamicNer') {
                return bridge(stageId, capabilityId, operation, 'NerService.warmProvider(dynamic_ner)', 'none', 'provider readiness only; scanDiscovery runs during Dynamic NER scan', 'frontend');
            }
            if (operation.model === 'semanticEmbedding') {
                return bridge(stageId, capabilityId, operation, 'PhoenixMachineControlService.loadSemanticModel', 'none', 'warms the semantic model only; graph compilation remains quarantined', 'frontend');
            }
            if (operation.model === 'nli') {
                return bridge(stageId, capabilityId, operation, 'NliWorkerService.initialize', 'none', 'browser ONNX worker warm; native queue/apply run during NLI adjudication', 'worker');
            }
            return bridge(stageId, capabilityId, operation, operation.service, 'none', 'warm-only frontend operation', 'frontend');
        case 'nativeReasoningPass':
        case 'notWired':
            return bridge(stageId, capabilityId, operation, operation.service, 'not wired', 'no backend command registered', 'frontend');
    }
}

function operationCapabilityId(operation: AtlasRuntimeOperation): AtlasCapabilityId | undefined {
    if (operation.model) return modelCapabilityId(operation.model);
    if (operation.kind === 'dynamicNerScan') return 'dynamicNer';
    if (operation.kind === 'richTextGraphScan') return 'assertedKernel';
    if (operation.kind === 'semanticAtlasScan') return 'semanticAtlas';
    if (operation.kind === 'nliAdjudication') return 'nliAdjudication';
    if (operation.kind === 'manifoldSnapshot') return capabilityForManifoldMode(operation.manifold || 'hybrid');
    if (operation.kind === 'graphVisualization') return 'galaxyVisualization';
    if (operation.kind === 'retrievalWalk') return 'retrievalWalk';
    if (operation.kind === 'nativeStoreProbe') return operation.args?.['capabilityId'] as AtlasCapabilityId | undefined;
    return undefined;
}

function capabilityForManifoldMode(mode: AtlasManifoldMode): AtlasCapabilityId {
    return MANIFOLD_MODE_CAPABILITIES[mode] || 'galaxyVisualization';
}

function manifoldModeForCapability(id: AtlasCapabilityId | undefined): AtlasManifoldMode {
    return id ? MANIFOLD_CAPABILITIES[id] || 'hybrid' : 'hybrid';
}

function manifoldModeLabel(mode: AtlasManifoldMode): string {
    if (mode === 'hopf') return 'Hopf';
    if (mode === 'lorentz') return 'Caps';
    if (mode === 'product') return 'Product';
    if (mode === 'siegel') return 'Siegel';
    return 'Hybrid';
}

function manifoldReadyLabel(mode: AtlasManifoldMode): string {
    return mode === 'hybrid'
        ? 'Hybrid embedding manifold ready'
        : `${manifoldModeLabel(mode)} projection ready`;
}

function manifoldSnapshotDetails(snapshot: unknown): Record<string, unknown> {
    if (!isRecord(snapshot)) return {};
    const payload = isRecord(snapshot['payload']) ? snapshot['payload'] : snapshot;
    const timings = isRecord(snapshot['timings']) ? snapshot['timings'] : {};
    return {
        manifold: snapshot['manifold'],
        geometryVersion: snapshot['geometryVersion'] ?? snapshot['geometry_version'],
        nodes: Array.isArray(payload['nodes']) ? payload['nodes'].length : 0,
        edges: Array.isArray(payload['edges']) ? payload['edges'].length : 0,
        cells: Array.isArray(payload['cells']) ? payload['cells'].length : 0,
        lorentzTrees: Array.isArray(payload['lorentzTrees']) ? payload['lorentzTrees'].length : 0,
        lorentzMemberships: Array.isArray(payload['lorentzMemberships']) ? payload['lorentzMemberships'].length : 0,
        runtimeLoadMs: timings['runtimeLoadMs'],
        nativeSnapshotMs: timings['nativeSnapshotMs'],
        fallbackLoadMs: timings['fallbackLoadMs'],
        totalLoadMs: timings['totalMs'],
        sourceLabel: snapshot['sourceLabel'] ?? snapshot['source_label'],
    };
}

function bridge(
    stageId: string,
    capabilityId: AtlasCapabilityId | undefined,
    operation: AtlasRuntimeOperation,
    frontendService: string,
    backendCommand: string,
    backendRoute: string,
    commandKind: AtlasBridgeCommand['commandKind'],
): AtlasBridgeCommand {
    return {
        stageId,
        ...(capabilityId ? { capabilityId } : {}),
        operationKind: operation.kind,
        frontendService,
        backendCommand,
        backendRoute,
        commandKind,
    };
}

function modelCapabilityId(id: AtlasRuntimeModelRequirementId): AtlasCapabilityId | undefined {
    if (id === 'dynamicNer') return 'dynamicNer';
    if (id === 'semanticEmbedding') return 'semanticEmbedding';
    if (id === 'nli') return 'nliAdjudication';
    return undefined;
}

function receiptSummary(capabilityId: AtlasCapabilityId, counts: Record<string, number>): string {
    const label = atlasCapabilityById(capabilityId).label;
    const entries = Object.entries(counts).filter(([, value]) => Number.isFinite(value));
    if (!entries.length) return `${label} completed`;
    return `${label}: ${entries.slice(0, 4).map(([key, value]) => `${key}=${value}`).join(', ')}`;
}

function receiptCounts(rawResult: unknown): Record<string, number> {
    const counts: Record<string, number> = {};
    if (!isRecord(rawResult)) return counts;

    setNumber(counts, 'documents', rawResult['documents']);
    setNumber(counts, 'suggestions', rawResult['suggestions']);
    setNumber(counts, 'exportableMentions', rawResult['exportableMentions']);
    setNumber(counts, 'inputCount', rawResult['inputCount']);
    setNumber(counts, 'resultCount', rawResult['resultCount']);
    setNumber(counts, 'rows', rawResult['count']);
    if (rawResult['opened'] === true) counts['opened'] = 1;

    const manifoldPayload = isRecord(rawResult['payload']) ? rawResult['payload'] : rawResult;
    setArrayLength(counts, 'manifold.nodes', manifoldPayload['nodes']);
    setArrayLength(counts, 'manifold.edges', manifoldPayload['edges']);
    setArrayLength(counts, 'manifold.cells', manifoldPayload['cells']);
    setArrayLength(counts, 'manifold.charts', manifoldPayload['charts']);
    setArrayLength(counts, 'manifold.coneTraces', manifoldPayload['coneTraces']);
    setArrayLength(counts, 'manifold.anchorProjections', manifoldPayload['anchorProjections']);
    setArrayLength(counts, 'manifold.lorentzTrees', manifoldPayload['lorentzTrees']);
    setArrayLength(counts, 'manifold.lorentzMemberships', manifoldPayload['lorentzMemberships']);

    setNumber(counts, 'indexedDocuments', rawResult['indexedDocuments']);
    setNumber(counts, 'candidateSuggestions', rawResult['candidateSuggestions']);
    setNumber(counts, 'relationCandidates', rawResult['relationCandidates']);

    const nativeResult = rawResult['nativeResult'];
    if (isRecord(nativeResult)) {
        setNumber(counts, 'processedDocuments', nativeResult['processedDocuments']);
        setNumber(counts, 'skippedDocuments', nativeResult['skippedDocuments']);
        setNumber(counts, 'relationCandidateCount', nativeResult['relationCandidateCount']);
        copyCountRecord(counts, 'graph', nativeResult['graphDeltaCounts']);
        copyCountRecord(counts, 'embedding', nativeResult['embeddingCounts']);
    }
    return counts;
}

function copyCountRecord(target: Record<string, number>, prefix: string, value: unknown): void {
    if (!isRecord(value)) return;
    for (const [key, count] of Object.entries(value)) {
        setNumber(target, `${prefix}.${key}`, count);
    }
}

function setArrayLength(target: Record<string, number>, key: string, value: unknown): void {
    if (Array.isArray(value)) {
        target[key] = value.length;
    }
}

function setNumber(target: Record<string, number>, key: string, value: unknown): void {
    if (typeof value === 'number' && Number.isFinite(value)) {
        target[key] = value;
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object';
}

function warmOperation(model: AtlasRuntimeModelRequirementId): AtlasRuntimeOperation {
    return {
        kind: 'warmModel',
        service: model === 'dynamicNer'
            ? 'NerService.warmProvider'
            : model === 'semanticEmbedding'
                ? 'PhoenixMachineControlService.loadSemanticModel'
                : 'NliWorkerService.initialize',
        model,
        ifCold: true,
        policy: 'warm-only',
    };
}

function normalizeNliInputs(payload: unknown): NliPairClassificationInput[] {
    if (!Array.isArray(payload)) return [];
    return payload
        .map((row) => normalizeNliInput(row))
        .filter((row): row is NliPairClassificationInput => !!row);
}

function normalizeNliInput(row: unknown): NliPairClassificationInput | null {
    if (!row || typeof row !== 'object') return null;
    const record = row as Record<string, unknown>;
    const input: NliPairClassificationInput = {
        judgmentId: stringField(record, 'judgmentId', 'judgment_id'),
        groupId: stringField(record, 'groupId', 'group_id'),
        sourceId: stringField(record, 'sourceId', 'source_id'),
        targetId: stringField(record, 'targetId', 'target_id'),
        edgeType: stringField(record, 'edgeType', 'edge_type'),
        direction: stringField(record, 'direction'),
        premise: stringField(record, 'premise'),
        hypothesis: stringField(record, 'hypothesis'),
    };
    return input.judgmentId && input.groupId && input.sourceId && input.targetId && input.edgeType && input.premise && input.hypothesis
        ? input
        : null;
}

function uniqueNliInputs(inputs: NliPairClassificationInput[]): NliPairClassificationInput[] {
    const seen = new Set<string>();
    const out: NliPairClassificationInput[] = [];
    for (const input of inputs) {
        const key = [
            input.sourceId,
            input.targetId,
            input.edgeType,
            input.direction,
            input.premise,
            input.hypothesis,
        ].join('\u001f');
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(input);
    }
    return out;
}

function uniqueNliPairCount(inputs: NliPairClassificationInput[]): number {
    return new Set(inputs.map((input) => `${input.sourceId}\u001f${input.targetId}\u001f${input.edgeType}`)).size;
}

function nliStageSummary(stage: string, startedAt: number, counts: Record<string, number>) {
    return {
        stage,
        status: 'completed',
        durationMs: Math.max(0, Math.round(performance.now() - startedAt)),
        counts,
    };
}

function appliedRowCount(applied: unknown): number {
    if (Array.isArray(applied)) return applied.length;
    if (!isRecord(applied)) return 0;
    const direct = applied['count'] ?? applied['applied'] ?? applied['appliedRows'] ?? applied['rows'];
    if (typeof direct === 'number' && Number.isFinite(direct)) return direct;
    for (const value of Object.values(applied)) {
        if (Array.isArray(value)) return value.length;
    }
    return 0;
}

function stringField(record: Record<string, unknown>, primary: string, fallback?: string): string {
    const value = record[primary] ?? (fallback ? record[fallback] : undefined);
    return typeof value === 'string' ? value : '';
}

function noteIdsFromBuildScope(scope: AtlasBuildScope | undefined): string[] {
    if (!scope) return [];
    if (scope.mode === 'note') return [scope.noteId];
    if (scope.mode === 'multiNote') return scope.noteIds;
    return [];
}

function uniqueIds(ids: string[]): string[] {
    return Array.from(new Set(ids.map((id) => String(id || '').trim()).filter(Boolean)));
}

function isNerScopeDocument(document: NerScopeDocument | undefined | null): document is NerScopeDocument {
    return !!document;
}

function service(
    id: string,
    label: string,
    serviceName: string,
    backendRoute: string,
    ready: boolean,
    detail?: string,
): AtlasServiceRequirement {
    return { id, label, service: serviceName, backendRoute, ready, detail };
}

function probe(
    label: string,
    status: AtlasCapabilityRuntimeState['status'],
    source: string,
    detail: string,
) {
    return { label, status, source, detail };
}

function output(label: string, source: string, detail: string, lastValue?: number | string | null): AtlasOutputProbe {
    return { label, source, detail, lastValue };
}

function expected(key: string, label: string, source: string): AtlasExpectedOutput {
    return { key, label, source };
}

function graphStatusToRuntime(status: ReturnType<PhoenixMachineControlService['graphStatus']>): AtlasCapabilityRuntimeState['status'] {
    if (status === 'building' || status === 'searching') return 'running';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    return 'idle';
}

function vectorStatusToRuntime(status: ReturnType<PhoenixMachineControlService['vectorStatus']>): AtlasCapabilityRuntimeState['status'] {
    if (status === 'loading' || status === 'indexing') return status === 'loading' ? 'warming' : 'running';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    return 'idle';
}

function manifoldStatusToRuntime(status: string): AtlasCapabilityRuntimeState['status'] {
    if (status === 'loading') return 'running';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    return 'idle';
}

function statusLabel(status: AtlasCapabilityRuntimeState['status']): string {
    switch (status) {
        case 'idle':
            return 'idle';
        case 'warming':
            return 'warming';
        case 'running':
            return 'running';
        case 'ready':
            return 'ready';
        case 'blocked':
            return 'not wired';
        case 'error':
            return 'error';
    }
}

function uniqueServices(services: AtlasServiceRequirement[]): AtlasServiceRequirement[] {
    const seen = new Set<string>();
    return services.filter((service) => {
        if (seen.has(service.id)) return false;
        seen.add(service.id);
        return true;
    });
}
