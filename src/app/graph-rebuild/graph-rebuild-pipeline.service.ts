import { Injectable, computed, inject, signal } from '@angular/core';

import { db, type EntityOccurrence, type Note } from '../lib/dexie/db';
import * as ops from '../lib/operations';
import { smartGraphRegistry } from '../lib/registry';
import type { AtlasCapabilityId } from '../components/search-panel/atlas-capability.model';
import type { AtlasBuildScope, AtlasRunOptions } from '../services/atlas-capability-runtime.model';
import { AtlasCapabilityRuntimeService } from '../services/atlas-capability-runtime.service';
import { NerService } from '../services/ner.service';
import { phoenixTransportAudit, type PhoenixTransportAuditSnapshot } from '../services/phoenix-transport-audit';
import { PhoenixStoreService, type PhoenixContentMutationTiming } from '../services/phoenix-store.service';
import { PhoenixUiApiService } from '../services/phoenix-ui-api.service';
import { buildGraphRebuildDeltaPostProcessPlan, deltaPostProcessPlanCounters, type GraphRebuildDeltaPostProcessPlan } from './graph-rebuild-delta-postprocess-plan';
import { buildGraphRebuildEdgeJudgmentPlan, edgeJudgmentPlanCounters } from './graph-rebuild-edge-type-judgment-plan';
import { embeddingProfileFromModelSelection } from './graph-rebuild-embedding-signatures';
import { GLINER_LINKER_MODEL_ID } from './graph-rebuild-entity-linking';
import { buildGraphIndexLayerReceipts } from './graph-index-layer-receipts';
import { GraphRebuildService } from './graph-rebuild.service';
import { buildSiegelBackboneProjectionReceipt } from './graph-rebuild-siegel-backbone';
import { assertGraphSnapshotAuthority } from './graph-snapshot-authority';
import type {
    GraphIndexModelReadiness,
    GraphIndexPostProcessMode,
    GraphIndexProjectionMode,
    GraphIndexProjectionReceipt,
    GraphIndexRunReceipt,
    GraphIndexRunRequest,
    GraphIndexRunStatus,
    GraphIndexRunScope,
    GraphIndexStageReceipt,
    GraphBuildDurabilityMode,
    GraphRebuildCounters,
    GraphRebuildDropReasons,
    GraphRebuildEntityLinkCounters,
    GraphRebuildRelationshipHint,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

const POSTPROCESS_FACT_CAPABILITIES: AtlasCapabilityId[] = [
    'nliAdjudication',
    'relationGraph',
    'temporalGraph',
    'eventIdentity',
    'memoryState',
    'causalGraph',
];

const PROJECTION_CAPABILITIES: Array<{ capability: AtlasCapabilityId; mode: GraphIndexProjectionMode }> = [
    { capability: 'hybridManifold', mode: 'hybrid' },
    { capability: 'hopfProjection', mode: 'hopf' },
    { capability: 'lorentzForest', mode: 'lorentz' },
    { capability: 'productManifold', mode: 'product' },
];

const POST_COMMIT_DIAGNOSTIC_DEBOUNCE_MS = 250;
const POST_COMMIT_DIAGNOSTIC_IDLE_TIMEOUT_MS = 2_000;
const INTERACTIVE_PERSISTED_RECEIPT_STAGE_IDS = new Set([
    'dynamicNer',
    'nliAdjudication',
    'graphBuildSnapshot',
    'signalTargetCoverage',
    'snapshotAuthorityContract',
    'snapshotDbOps',
    'snapshotPayloadProfile',
    'snapshotCpu',
    'nativeCompilerBoundary',
    'stagedNativeScenePacket',
    'transportOps',
    'uiCommit',
    'postCommitEnrichment',
]);

interface GraphNerDeltaResult {
    counts: Record<string, number>;
    acceptedOccurrences: EntityOccurrence[];
}

type PipelineResult = {
    receipt: GraphIndexRunReceipt;
    snapshot: GraphRebuildSnapshot;
};

type ScopedDocument = {
    id: string;
    title: string;
    plainText: string;
    folderId?: string;
    version?: number;
    updatedAt?: number;
};

type PostCommitDiagnosticInput = {
    scope: GraphIndexRunScope;
    snapshotId: string;
    entities: GraphIndexRunRequest['entities'];
    acceptedNerOccurrences: EntityOccurrence[];
    relationshipHints: GraphRebuildRelationshipHint[];
    request: GraphIndexRunRequest;
    nerCandidates: number;
    baseRunSerial: number;
};

type ReceiptPersistenceJob = {
    receipt: GraphIndexRunReceipt;
    persistedReceipt: GraphIndexRunReceipt;
    receiptStage: GraphIndexStageReceipt;
};

type PostCommitSchedulerWindow = Window & {
    requestIdleCallback?: (
        callback: () => void,
        options?: { timeout?: number },
    ) => number;
    cancelIdleCallback?: (handle: number) => void;
};

@Injectable({ providedIn: 'root' })
export class GraphRebuildPipelineService {
    private readonly graphRebuild = inject(GraphRebuildService);
    private readonly atlasRuntime = inject(AtlasCapabilityRuntimeService);
    private readonly ner = inject(NerService);
    private readonly store = inject(PhoenixStoreService);
    private readonly phoenixUiApi = inject(PhoenixUiApiService);
    private readonly runningState = signal(false);
    private readonly entityLinkerWarmState = signal(false);
    private readonly lastReceiptState = signal<GraphIndexRunReceipt | null>(null);
    private readonly lastSnapshotState = signal<GraphRebuildSnapshot | null>(null);
    private receiptPersistenceQueue: Promise<void> = Promise.resolve();
    private readonly pendingReceiptPersistenceJobs = new Map<string, ReceiptPersistenceJob>();
    private receiptPersistenceDrainScheduled = false;
    private postCommitDiagnosticQueue: Promise<void> = Promise.resolve();
    private postCommitDiagnosticToken = 0;
    private cancelScheduledPostCommitDiagnostic: (() => void) | null = null;

    readonly running = computed(() => this.runningState());
    readonly lastReceipt = computed(() => this.lastReceiptState());
    readonly lastSnapshot = computed(() => this.lastSnapshotState());

    modelReadiness(request: GraphIndexRunRequest): GraphIndexModelReadiness[] {
        const options = this.atlasOptions(request);
        const dynamicNer = this.requiredModelState('dynamicNer', 'Dynamic NER', 'dynamicNer', options);
        const semanticEmbedding = this.requiredModelState('semanticEmbedding', 'Semantic Embedding', 'semanticAtlas', options);
        const nli = this.requiredModelState('nli', 'NLI', 'nliAdjudication', options);
        const entityLinker = this.entityLinkerModelState();
        return [dynamicNer, semanticEmbedding, nli, entityLinker];
    }

    graphModelsReady(request: GraphIndexRunRequest): boolean {
        const readiness = this.modelReadiness(request);
        return ['dynamicNer', 'nli'].every((id) =>
            readiness.find((model) => model.id === id)?.status === 'ready',
        );
    }

    embeddingModelReady(request: GraphIndexRunRequest): boolean {
        return this.modelReadiness(request).find((model) => model.id === 'semanticEmbedding')?.status === 'ready';
    }

    async warmOptionalModel(modelId: GraphIndexModelReadiness['id']): Promise<void> {
        if (modelId === 'entityLinker') {
            await this.warmEntityLinker();
        }
    }

    async loadGraphModels(request: GraphIndexRunRequest): Promise<void> {
        if (this.runningState()) return;
        this.runningState.set(true);
        try {
            const options = this.atlasOptions(request);
            await this.atlasRuntime.warmModelLane('dynamicNer', options);
            await this.atlasRuntime.warmModelLane('nli', options);
        } finally {
            this.runningState.set(false);
        }
    }

    async loadEmbeddingModel(request: GraphIndexRunRequest): Promise<void> {
        if (this.runningState()) return;
        this.runningState.set(true);
        try {
            await this.atlasRuntime.warmModelLane('semanticEmbedding', this.atlasOptions(request));
        } finally {
            this.runningState.set(false);
        }
    }

    async buildGraph(request: GraphIndexRunRequest): Promise<PipelineResult> {
        if (this.runningState()) {
            throw new Error('Full Atlas Index is already running.');
        }
        const durabilityMode = request.durabilityMode || 'interactive';
        const modelReadiness = this.modelReadiness(request);
        const graphCold = modelReadiness
            .filter((model) => model.id === 'dynamicNer' || model.id === 'nli')
            .filter((model) => model.status !== 'ready');
        if (graphCold.length) {
            throw new Error(`Load graph models first: ${graphCold.map((model) => model.label).join(', ')}.`);
        }

        this.runningState.set(true);
        const runStarted = Date.now();
        const transportStarted = phoenixTransportAudit.snapshot();
        const stageReceipts: GraphIndexStageReceipt[] = [];
        const projectionReceipts: GraphIndexProjectionReceipt[] = [];
        const snapshotRef: { value?: GraphRebuildSnapshot } = {};
        let relationshipHints: GraphRebuildRelationshipHint[] = [];
        let postProcessFingerprintValue: string | undefined;
        let resumeContentCheckpoints: (() => void) | null = null;
        let acceptedNerOccurrences: EntityOccurrence[] = [];
        try {
            const docs = await this.loadScopedDocuments(request.scope.noteIds);
            const scope = expandScopeNoteIds(request.scope, docs);
            const noteTexts = Object.fromEntries(docs.map((doc) => [doc.id, doc.plainText]));
            const options = this.atlasOptions({ ...request, scope, postProcessMode: 'full' });
            const entities = smartGraphRegistry.getAllEntities().length
                ? smartGraphRegistry.getAllEntities()
                : request.entities;
            const fingerprint = postProcessFingerprint(scope, docs, entities, request.modelSelection, request.embeddingStagePolicy);
            postProcessFingerprintValue = fingerprint;

            const nerStage = await this.runStage('dynamicNer', 'Dynamic NER + Alex Deltas', async () => {
                const delta = await this.runNerDeltas(docs);
                acceptedNerOccurrences = delta.acceptedOccurrences;
                const counts = delta.counts;
                return {
                    outputCount: counts['acceptedAnchors'] || 0,
                    counters: counts,
                    message: `${counts['acceptedAnchors'] || 0} accepted anchors from ${counts['candidates'] || 0} candidates`,
                };
            });
            stageReceipts.push(nerStage);
            assertStageCompleted(nerStage);

            appendDeltaPostProcessPlanStage(stageReceipts, {
                policy: request.policy,
                docs,
                entities,
                cachedSnapshot: null,
                fingerprintMatched: false,
            });
            stageReceipts.push(signalCandidatePlanStage({
                discoveryStage: nerStage,
                docs,
                entities,
                cachedSnapshot: null,
            }));

            for (const capability of POSTPROCESS_FACT_CAPABILITIES) {
                let rawStageResult: unknown;
                const captureRelationshipHints = capability === 'nliAdjudication'
                    ? (rawResult: unknown) => {
                        rawStageResult = rawResult;
                        relationshipHints = relationshipHintsFromNliResult(rawResult);
                    }
                    : undefined;
                const receipt = await this.runCapabilityStage(capability, options, captureRelationshipHints);
                stageReceipts.push(receipt);
                assertStageCompleted(receipt);
                if (capability === 'nliAdjudication') {
                    appendNliStagingStages(stageReceipts, rawStageResult);
                }
            }

            resumeContentCheckpoints = this.deferContentCheckpoints();
            const graphStage = await this.runStage('graphBuildSnapshot', 'Build Graph Snapshot', async () => {
                const snapshot = await this.graphRebuild.buildAndPersistSnapshot({
                    scopeKind: scope.kind,
                    scopeId: scope.scopeId,
                    noteIds: scope.noteIds,
                    entities,
                    noteTexts,
                    sourceEvidence: { stagedOccurrences: acceptedNerOccurrences },
                    relationshipHints,
                    embeddingProfile: embeddingProfileFromModelSelection(request.modelSelection),
                    postProcessMode: 'full',
                    durabilityMode,
                    embeddingStagePolicy: request.embeddingStagePolicy,
                    candidateCount: nerStage.counters['candidates'] || 0,
                    calendarRegistrySnapshot: request.calendarRegistrySnapshot,
                });
                snapshotRef.value = snapshot;
                return {
                    outputCount: (snapshot.counters.nodes || 0)
                        + (snapshot.counters.edges || 0)
                        + (snapshot.counters.embeddingTargets || 0),
                    counters: {
                        chunks: snapshot.counters.chunks,
                        anchors: snapshot.counters.acceptedAnchors,
                        nodes: snapshot.counters.nodes,
                        edges: snapshot.counters.edges,
                        acceptedRelationships: snapshot.counters.acceptedRelationships,
                        reviewRelationships: snapshot.counters.reviewRelationships,
                        rejectedRelationships: snapshot.counters.rejectedRelationships,
                        embeddingTargets: snapshot.counters.embeddingTargets,
                        embeddingClusters: snapshot.counters.embeddingClusters || 0,
                        embeddingBackboneEdges: snapshot.counters.embeddingBackboneEdges || 0,
                        embeddingOutliers: snapshot.counters.embeddingOutliers || 0,
                        embeddingPlannedPairs: snapshot.counters.embeddingPlannedPairs || 0,
                        embeddingPrunedPairs: snapshot.counters.embeddingPrunedPairs || 0,
                        linkSuggestions: snapshot.counters.graphAwareLinkSuggestions || 0,
                        entityLinks: snapshot.counters.entityLinkSuggestions || 0,
                        nliHints: relationshipHints.length,
                    },
                    message: `${snapshot.counters.nodes} nodes / ${snapshot.counters.edges} edges / ${snapshot.counters.embeddingTargets} targets`,
                };
            });
            stageReceipts.push(graphStage);
            assertStageCompleted(graphStage);

            const completedSnapshot = snapshotRef.value;
            if (!completedSnapshot) {
                throw new Error('Build graph stage completed without a snapshot.');
            }
            appendSignalCoverageStages(stageReceipts, completedSnapshot);
            appendGraphTruthContractStage(stageReceipts, completedSnapshot);
            appendEntityLinkerPlanStage(stageReceipts, completedSnapshot, request.embeddingStagePolicy?.entityLinkerEnabled !== false);
            appendEdgeJudgmentPlanStage(stageReceipts, completedSnapshot);
            appendSemanticRerankStage(stageReceipts, completedSnapshot);
            if (durabilityMode !== 'interactive') {
                appendMemoryGraphRagBridgeStage(stageReceipts, completedSnapshot);
                appendDiscourseSpineStage(stageReceipts, completedSnapshot);
                appendDiscourseBridgeCandidateStage(stageReceipts, completedSnapshot);
                appendDiscourseBridgeAdjudicationStage(stageReceipts, completedSnapshot);
                appendDiscourseEvalLedgerStage(stageReceipts, completedSnapshot);
                appendDiscoursePromotionSurfaceStage(stageReceipts, completedSnapshot);
                appendDiscourseCompilerOverlayStage(stageReceipts, completedSnapshot);
            }
            appendCalendarRegistryStage(stageReceipts, completedSnapshot);
            appendSnapshotTimingStages(stageReceipts, completedSnapshot);
            appendStagedNativeScenePacketSkippedStage(stageReceipts, completedSnapshot);

            for (const projection of PROJECTION_CAPABILITIES) {
                projectionReceipts.push(snapshotOwnedProjectionReceipt(projection.mode, completedSnapshot));
            }
            projectionReceipts.push(await buildSiegelBackboneProjectionReceipt(completedSnapshot));
            appendTransportTimingStage(stageReceipts, transportStarted, phoenixTransportAudit.snapshot());

            const completedAt = Date.now();
            const receipt = this.buildRunReceipt({
                idPrefix: 'graph-atlas',
                scope,
                policy: request.policy,
                postProcessMode: 'full',
                durabilityMode,
                postProcessFingerprint: fingerprint,
                postProcessCacheHit: false,
                modelSelection: request.modelSelection,
                modelReadiness: this.modelReadiness({ ...request, scope }),
                startedAt: runStarted,
                completedAt,
                stageReceipts,
                projectionReceipts,
                snapshot: completedSnapshot,
                message: `Build Graph produced ${completedSnapshot.counters.nodes} nodes, ${completedSnapshot.counters.edges} edges, and ${completedSnapshot.counters.embeddingTargets} targets.`,
            });
            await this.publishRunReceipt(receipt, completedSnapshot);
            if (durabilityMode === 'interactive') {
                appendInteractivePostCommitStage(stageReceipts, completedSnapshot);
                this.refreshLayerReceipts(receipt, completedSnapshot);
            }
            this.enqueueRunReceiptPersistence(receipt);
            if (durabilityMode === 'interactive') {
                this.scheduleInteractivePostCommitWork({
                    scope,
                    snapshotId: completedSnapshot.id,
                    entities,
                    acceptedNerOccurrences,
                    relationshipHints,
                    request,
                    nerCandidates: nerStage.counters['candidates'] || 0,
                    baseRunSerial: typeof this.graphRebuild.currentSnapshotRunSerial === 'function'
                        ? this.graphRebuild.currentSnapshotRunSerial()
                        : 0,
                });
            }
            resumeContentCheckpoints();
            return { receipt, snapshot: completedSnapshot };
        } catch (error) {
            const completedAt = Date.now();
            const snapshot = snapshotRef.value || null;
            const failedReceipt = this.buildRunReceipt({
                idPrefix: 'graph-atlas:failed',
                scope: request.scope,
                policy: request.policy,
                postProcessMode: 'full',
                durabilityMode,
                postProcessFingerprint: snapshot ? postProcessFingerprintValue : undefined,
                modelSelection: request.modelSelection,
                modelReadiness,
                startedAt: runStarted,
                completedAt,
                stageReceipts,
                projectionReceipts,
                snapshot,
                status: 'failed',
                message: error instanceof Error ? error.message : String(error),
            });
            if (snapshot) this.lastSnapshotState.set(snapshot);
            this.lastReceiptState.set(failedReceipt);
            throw error;
        } finally {
            resumeContentCheckpoints?.();
            this.runningState.set(false);
        }
    }

    private buildRunReceipt(input: {
        idPrefix: string;
        scope: GraphIndexRunScope;
        policy: GraphIndexRunRequest['policy'];
        postProcessMode?: GraphIndexPostProcessMode;
        durabilityMode?: GraphBuildDurabilityMode;
        postProcessFingerprint?: string;
        postProcessDiscoveryFingerprint?: string;
        postProcessCacheHit?: boolean;
        modelSelection: GraphIndexRunRequest['modelSelection'];
        modelReadiness: GraphIndexModelReadiness[];
        startedAt: number;
        completedAt: number;
        stageReceipts: GraphIndexStageReceipt[];
        projectionReceipts: GraphIndexProjectionReceipt[];
        snapshot: GraphRebuildSnapshot | null;
        status?: GraphIndexRunStatus;
        message: string;
    }): GraphIndexRunReceipt {
        const receipt: GraphIndexRunReceipt = {
            schemaVersion: 'phoenix-graph-index-run/v1',
            id: `${input.idPrefix}:${input.scope.scopeId}:${input.completedAt}`,
            scope: input.scope,
            policy: input.policy,
            delta: input.policy !== 'force',
            status: input.status || 'completed',
            modelSelection: input.modelSelection,
            postProcessMode: input.postProcessMode,
            durabilityMode: input.durabilityMode,
            postProcessFingerprint: input.postProcessFingerprint,
            postProcessDiscoveryFingerprint: input.postProcessDiscoveryFingerprint,
            postProcessCacheHit: input.postProcessCacheHit,
            modelReadiness: input.modelReadiness,
            startedAt: input.startedAt,
            completedAt: input.completedAt,
            durationMs: input.completedAt - input.startedAt,
            stageReceipts: input.stageReceipts,
            projectionReceipts: input.projectionReceipts,
            layerReceipts: [],
            snapshotId: input.snapshot?.id,
            authorityContract: input.snapshot?.authorityContract,
            counters: input.snapshot?.counters || emptyCounters(),
            dropReasons: input.snapshot?.counters.dropReasons || emptyDropReasons(),
            message: input.message,
        };
        this.refreshLayerReceipts(receipt, input.snapshot);
        return receipt;
    }

    private refreshLayerReceipts(receipt: GraphIndexRunReceipt, snapshot: GraphRebuildSnapshot | null): void {
        receipt.layerReceipts = buildGraphIndexLayerReceipts({ receipt, snapshot });
    }

    private async publishRunReceipt(
        receipt: GraphIndexRunReceipt,
        snapshot: GraphRebuildSnapshot | null,
    ): Promise<void> {
        if (snapshot) assertRunReceiptParity(receipt, snapshot);
        const startedAt = Date.now();
        const uiStage: GraphIndexStageReceipt = {
            id: 'uiCommit',
            label: 'UI Commit',
            status: 'completed',
            startedAt,
            completedAt: startedAt,
            durationMs: 0,
            outputCount: 0,
            counters: {},
            message: 'Receipt and snapshot published to UI signals',
        };
        receipt.stageReceipts.push(uiStage);
        this.refreshLayerReceipts(receipt, snapshot);
        const signalStarted = performance.now();
        if (snapshot) this.lastSnapshotState.set(snapshot);
        this.lastReceiptState.set({ ...receipt, stageReceipts: [...receipt.stageReceipts], layerReceipts: [...receipt.layerReceipts] });
        const signalCommitMs = elapsedTimingMs(signalStarted);
        const frameStarted = performance.now();
        await waitForUiFrame();
        const uiFrameMs = elapsedTimingMs(frameStarted);
        const completedAt = Date.now();
        uiStage.completedAt = completedAt;
        uiStage.durationMs = completedAt - startedAt;
        uiStage.counters = {
            signalCommitMs,
            uiFrameMs,
        };
        receipt.completedAt = Math.max(receipt.completedAt, completedAt);
        receipt.durationMs = receipt.completedAt - receipt.startedAt;
        this.refreshLayerReceipts(receipt, snapshot);
        this.lastReceiptState.set({ ...receipt, stageReceipts: [...receipt.stageReceipts], layerReceipts: [...receipt.layerReceipts] });
    }

    private scheduleInteractivePostCommitWork(input: PostCommitDiagnosticInput): void {
        const scheduler = postCommitSchedulerWindow();
        if (!scheduler) return;
        const token = ++this.postCommitDiagnosticToken;
        this.cancelScheduledPostCommitDiagnostic?.();
        this.cancelScheduledPostCommitDiagnostic = null;
        const debounceHandle = scheduler.setTimeout(() => {
            if (!this.isCurrentPostCommitDiagnostic(input, token)) return;
            this.cancelScheduledPostCommitDiagnostic = schedulePostCommitIdleWork(scheduler, () => {
                this.cancelScheduledPostCommitDiagnostic = null;
                this.enqueuePostCommitDiagnosticWork(input, token);
            });
        }, POST_COMMIT_DIAGNOSTIC_DEBOUNCE_MS);
        this.cancelScheduledPostCommitDiagnostic = () => scheduler.clearTimeout(debounceHandle);
    }

    private enqueuePostCommitDiagnosticWork(input: PostCommitDiagnosticInput, token: number): void {
        this.postCommitDiagnosticQueue = this.postCommitDiagnosticQueue.then(
            () => this.runPostCommitDiagnosticWork(input, token),
            () => this.runPostCommitDiagnosticWork(input, token),
        );
        void this.postCommitDiagnosticQueue;
    }

    private async runPostCommitDiagnosticWork(input: PostCommitDiagnosticInput, token: number): Promise<void> {
        if (!this.isCurrentPostCommitDiagnostic(input, token)) return;
        try {
            await this.receiptPersistenceQueue;
            if (!this.isCurrentPostCommitDiagnostic(input, token)) return;
            await this.graphRebuild.buildAndPersistSnapshot({
                scopeKind: input.scope.kind,
                scopeId: input.scope.scopeId,
                noteIds: input.scope.noteIds,
                entities: input.entities,
                sourceEvidence: { stagedOccurrences: input.acceptedNerOccurrences },
                relationshipHints: input.relationshipHints,
                embeddingProfile: embeddingProfileFromModelSelection(input.request.modelSelection),
                postProcessMode: 'full',
                durabilityMode: 'diagnostic',
                diagnosticBaseSnapshotId: input.snapshotId,
                diagnosticBaseSnapshotRunSerial: input.baseRunSerial,
                embeddingStagePolicy: input.request.embeddingStagePolicy,
                candidateCount: input.nerCandidates,
                calendarRegistrySnapshot: input.request.calendarRegistrySnapshot,
            });
        } catch (error) {
            console.warn('[GraphRebuildPipeline] Post-commit graph enrichment failed', error);
        }
    }

    private isCurrentPostCommitDiagnostic(input: PostCommitDiagnosticInput, token: number): boolean {
        return token === this.postCommitDiagnosticToken
            && this.lastSnapshotState()?.id === input.snapshotId;
    }

    private deferContentCheckpoints(): () => void {
        let resumed = false;
        this.store.pauseSnapshots();
        return () => {
            if (resumed) return;
            resumed = true;
            this.store.resumeSnapshots();
        };
    }

    private enqueueRunReceiptPersistence(receipt: GraphIndexRunReceipt): void {
        const queuedAt = Date.now();
        const receiptStage: GraphIndexStageReceipt = {
            id: 'receiptDbOps',
            label: 'Receipt DB Ops',
            status: 'running',
            startedAt: queuedAt,
            completedAt: queuedAt,
            durationMs: 0,
            outputCount: 0,
            counters: {
                receiptPersistenceQueued: 1,
                receiptPersistenceAsync: 1,
            },
            message: 'Run receipt persistence queued after UI commit',
        };
        receipt.stageReceipts.push(receiptStage);
        receipt.completedAt = Math.max(receipt.completedAt, queuedAt);
        receipt.durationMs = receipt.completedAt - receipt.startedAt;
        this.refreshLayerReceipts(receipt, this.lastSnapshotState());
        this.publishReceiptUpdateIfCurrent(receipt);
        const persistedReceipt = graphIndexReceiptForPersistence(receipt);
        this.pendingReceiptPersistenceJobs.set(receiptPersistenceKey(receipt), { receipt, persistedReceipt, receiptStage });
        this.scheduleReceiptPersistenceDrain();
    }

    private scheduleReceiptPersistenceDrain(): void {
        if (this.receiptPersistenceDrainScheduled) return;
        this.receiptPersistenceDrainScheduled = true;
        this.receiptPersistenceQueue = this.receiptPersistenceQueue.then(
            () => this.drainReceiptPersistenceQueue(),
            () => this.drainReceiptPersistenceQueue(),
        );
        void this.receiptPersistenceQueue;
    }

    private async drainReceiptPersistenceQueue(): Promise<void> {
        try {
            while (true) {
                await deferReceiptPersistenceTurn();
                const jobs = [...this.pendingReceiptPersistenceJobs.values()];
                if (!jobs.length) return;
                this.pendingReceiptPersistenceJobs.clear();
                for (const job of jobs) {
                    await this.persistRunReceiptWithTiming(job.receipt, job.persistedReceipt, job.receiptStage);
                }
            }
        } finally {
            this.receiptPersistenceDrainScheduled = false;
            if (this.pendingReceiptPersistenceJobs.size) this.scheduleReceiptPersistenceDrain();
        }
    }

    private async persistRunReceiptWithTiming(
        receipt: GraphIndexRunReceipt,
        persistedReceipt: GraphIndexRunReceipt,
        receiptStage: GraphIndexStageReceipt,
    ): Promise<void> {
        const queuedAt = receiptStage.startedAt;
        const startedAt = Date.now();
        const started = performance.now();
        const receiptPayloadChars = jsonPayloadChars(persistedReceipt);
        const transportStarted = phoenixTransportAudit.snapshot();
        try {
            const storeTiming = await this.graphRebuild.persistRunReceipt(persistedReceipt);
            const durationMs = elapsedTimingMs(started);
            const completedAt = Date.now();
            receiptStage.status = 'completed';
            receiptStage.completedAt = completedAt;
            receiptStage.durationMs = completedAt - queuedAt;
            receiptStage.counters = {
                receiptPersistMs: durationMs,
                receiptPayloadChars,
                receiptPersistenceAsync: 1,
                receiptPersistenceQueueWaitMs: Math.max(0, startedAt - queuedAt),
                ...contentMutationTimingCounters(storeTiming, 'receiptStore'),
                ...prefixedCounters(
                    transportDeltaCounters(transportStarted, phoenixTransportAudit.snapshot()),
                    'receipt',
                ),
            };
            receiptStage.message = 'Run receipt persisted to scoped documents';
        } catch (error) {
            const durationMs = elapsedTimingMs(started);
            const completedAt = Date.now();
            receiptStage.status = 'failed';
            receiptStage.completedAt = completedAt;
            receiptStage.durationMs = completedAt - queuedAt;
            receiptStage.counters = {
                receiptPersistMs: durationMs,
                receiptPayloadChars,
                receiptPersistenceAsync: 1,
                receiptPersistenceFailed: 1,
                receiptPersistenceQueueWaitMs: Math.max(0, startedAt - queuedAt),
                ...prefixedCounters(
                    transportDeltaCounters(transportStarted, phoenixTransportAudit.snapshot()),
                    'receipt',
                ),
            };
            receiptStage.message = `Run receipt persistence failed: ${error instanceof Error ? error.message : String(error)}`;
            console.warn('[GraphRebuildPipeline] Run receipt persistence failed', error);
        } finally {
            this.refreshLayerReceipts(receipt, this.lastSnapshotState());
            this.publishReceiptUpdateIfCurrent(receipt);
        }
    }

    private publishReceiptUpdateIfCurrent(receipt: GraphIndexRunReceipt): void {
        if (this.lastReceiptState()?.id !== receipt.id) return;
        this.lastReceiptState.set({
            ...receipt,
            stageReceipts: [...receipt.stageReceipts],
            layerReceipts: [...receipt.layerReceipts],
        });
    }

    private async runNerDeltas(docs: ScopedDocument[]): Promise<GraphNerDeltaResult> {
        let candidates = 0;
        let acceptedAnchors = 0;
        let dropped = 0;
        const acceptedOccurrences: EntityOccurrence[] = [];
        for (const doc of docs) {
            if (!doc.plainText.trim()) continue;
            await this.ner.runDynamicScan({
                noteId: doc.id,
                noteTitle: doc.title || 'Untitled Note',
                plainText: doc.plainText,
            });
            const suggestions = [...this.ner.suggestions()];
            candidates += suggestions.length;
            for (const suggestion of suggestions) {
                const accepted = await this.ner.acceptSuggestionForContext(suggestion.id, {
                    noteId: doc.id,
                    noteTitle: doc.title,
                    plainText: doc.plainText,
                    generation: doc.version || doc.updatedAt || Date.now(),
                    registrationSource: 'extraction',
                });
                acceptedAnchors += accepted ? 1 : 0;
                dropped += accepted ? 0 : 1;
                if (isEntityOccurrence(accepted)) acceptedOccurrences.push(accepted);
            }
        }
        return {
            counts: { documents: docs.length, candidates, acceptedAnchors, dropped },
            acceptedOccurrences,
        };
    }

    private async runCapabilityStage(
        capability: AtlasCapabilityId,
        options: AtlasRunOptions,
        onRawResult?: (result: unknown) => void,
    ): Promise<GraphIndexStageReceipt> {
        return this.runStage(capability, capabilityLabel(capability), async () => {
            const result = await this.atlasRuntime.runCapability(capability, { ...options, skipModelWarm: true });
            onRawResult?.(result.rawResult);
            const counters = numberCounts(result.rawResult);
            return {
                outputCount: sumOutputCounts(counters),
                counters,
                message: `${capabilityLabel(capability)} completed`,
            };
        });
    }

    private async runStage(
        id: string,
        label: string,
        action: () => Promise<{ outputCount: number; counters: Record<string, number>; message: string }>,
    ): Promise<GraphIndexStageReceipt> {
        const startedAt = Date.now();
        try {
            const result = await action();
            const completedAt = Date.now();
            return {
                id,
                label,
                status: 'completed',
                startedAt,
                completedAt,
                durationMs: completedAt - startedAt,
                outputCount: result.outputCount,
                counters: result.counters,
                message: result.message,
            };
        } catch (error) {
            const completedAt = Date.now();
            return {
                id,
                label,
                status: 'failed',
                startedAt,
                completedAt,
                durationMs: completedAt - startedAt,
                outputCount: 0,
                counters: {},
                message: error instanceof Error ? error.message : String(error),
            };
        }
    }

    private async loadScopedDocuments(noteIds: string[]): Promise<ScopedDocument[]> {
        const rows = await this.loadScopedNotesWithBodies(noteIds);
        return rows.map((note) => ({
            id: note.id,
            title: note.title || 'Untitled Note',
            plainText: String(note.markdownContent || note.content || ''),
            folderId: note.folderId,
            version: note.version,
            updatedAt: note.updatedAt,
        }));
    }

    private async loadScopedNotesWithBodies(noteIds: string[]): Promise<Note[]> {
        if (noteIds.length) {
            return (await ops.getNotesByIds(noteIds)) as unknown as Note[];
        }
        const cached = await db.notes.toArray();
        const ids = cached.map((note) => note.id).filter(Boolean);
        if (!ids.length) return cached;
        const hydrated = await ops.getNotesByIds(ids) as unknown as Note[];
        return hydrated.length ? hydrated : cached;
    }

    private atlasOptions(request: GraphIndexRunRequest): AtlasRunOptions {
        return {
            selectedModel: request.modelSelection.embeddingModelId as any,
            selectedModelLabel: request.modelSelection.embeddingModelLabel,
            dimensionLabel: request.modelSelection.embeddingDimensionLabel,
            scope: request.scope.kind === 'global' ? 'global' : request.scope.scopeId,
            buildScope: atlasScopeFromGraphScope(request.scope),
            buildPolicy: request.policy === 'force' ? 'force' : 'dirty-only',
            noteIds: request.scope.noteIds,
        };
    }

    private requiredModelState(
        modelId: GraphIndexModelReadiness['id'],
        label: string,
        capability: AtlasCapabilityId,
        options: AtlasRunOptions,
    ): GraphIndexModelReadiness {
        const requirement = this.atlasRuntime
            .capabilityState(capability, options)
            .requiredModels.find((model) => model.id === modelId);
        return {
            id: modelId,
            label,
            status: (requirement?.readiness || 'idle') as GraphIndexModelReadiness['status'],
            detail: requirement?.statusLabel || 'idle',
        };
    }

    private entityLinkerModelState(): GraphIndexModelReadiness {
        return {
            id: 'entityLinker',
            label: 'Entity Linker',
            status: this.entityLinkerWarmState() ? 'ready' : 'idle',
            detail: this.entityLinkerWarmState()
                ? `${GLINER_LINKER_MODEL_ID} staged; native runner pending`
                : `narrow retriever ready; ${GLINER_LINKER_MODEL_ID} runner pending`,
            optional: true,
        };
    }

    private async warmEntityLinker(): Promise<void> {
        this.entityLinkerWarmState.set(true);
    }
}

function isEntityOccurrence(value: unknown): value is EntityOccurrence {
    const row = value && typeof value === 'object'
        ? value as Partial<EntityOccurrence>
        : null;
    return typeof row?.id === 'string'
        && typeof row.noteId === 'string'
        && typeof row.entityId === 'string'
        && typeof row.sourceStart === 'number'
        && typeof row.sourceEnd === 'number'
        && typeof row.surface === 'string';
}

function expandScopeNoteIds(scope: GraphIndexRunScope, docs: ScopedDocument[]): GraphIndexRunScope {
    const loadedNoteIds = docs.map((doc) => doc.id);
    if (scope.kind === 'global') return { ...scope, noteIds: loadedNoteIds };
    if (!scope.noteIds.length) return { ...scope, noteIds: loadedNoteIds };
    if (scope.kind === 'multiNote' || scope.kind === 'folder') return { ...scope, noteIds: loadedNoteIds };
    return scope;
}

function appendSnapshotTimingStages(
    stageReceipts: GraphIndexStageReceipt[],
    snapshot: GraphRebuildSnapshot,
): void {
    const timings = snapshot.buildTimings;
    if (!timings) return;
    stageReceipts.push(instrumentationStage(
        'snapshotDbOps',
        'DB Ops',
        Math.round(timings.dbOpsMs),
        {
            dbLoadMs: timings.dbLoadMs,
            snapshotPersistMs: timings.snapshotPersistMs,
            snapshotStoreMs: timings.snapshotStoreMs || 0,
            snapshotPrimaryStoreMs: timings.snapshotPrimaryStoreMs || 0,
            snapshotOverGraphStoreMs: timings.snapshotOverGraphStoreMs || 0,
            snapshotStoreDocuments: timings.snapshotStoreDocuments || 0,
            snapshotPrimaryWriteSkipped: timings.snapshotPrimaryWriteSkipped || 0,
            snapshotPrimaryIdentityReused: timings.snapshotPrimaryIdentityReused || 0,
            snapshotContentBlobReads: timings.snapshotContentBlobReads || 0,
            snapshotContentBlobManifestTrusted: timings.snapshotContentBlobManifestTrusted || 0,
            snapshotContentBlobManifestMatches: timings.snapshotContentBlobManifestMatches || 0,
            snapshotContentBlobManifestMisses: timings.snapshotContentBlobManifestMisses || 0,
            snapshotWrittenContentBlobs: timings.snapshotWrittenContentBlobs || 0,
            snapshotReusedContentBlobs: timings.snapshotReusedContentBlobs || 0,
            snapshotSerializeMs: timings.snapshotSerializeMs || 0,
            snapshotPrimaryEncodeMs: timings.snapshotPrimaryEncodeMs || 0,
            snapshotOverGraphEncodeMs: timings.snapshotOverGraphEncodeMs || 0,
            snapshotOverGraphSkipped: timings.snapshotOverGraphSkipped || 0,
            snapshotPayloadProfileMs: timings.snapshotPayloadProfileMs || 0,
            snapshotPayloadChars: timings.snapshotPayloadChars || 0,
            snapshotPrimaryRawPayloadChars: timings.snapshotPrimaryRawPayloadChars || 0,
            snapshotCompressionSavedChars: timings.snapshotCompressionSavedChars || 0,
            snapshotCompressionRatioPct: timings.snapshotCompressionRatioPct || 0,
            snapshotOverGraphPayloadChars: timings.snapshotOverGraphPayloadChars || 0,
            snapshotOverGraphRawPayloadChars: timings.snapshotOverGraphRawPayloadChars || 0,
            snapshotOverGraphCompressedBytes: timings.snapshotOverGraphCompressedBytes || 0,
            snapshotOverGraphCompressionSavedChars: timings.snapshotOverGraphCompressionSavedChars || 0,
            snapshotOverGraphCompressionRatioPct: timings.snapshotOverGraphCompressionRatioPct || 0,
            snapshotTotalPayloadChars: timings.snapshotTotalPayloadChars || 0,
            occurrenceLoadMs: timings.occurrenceLoadMs,
            chunkLoadMs: timings.chunkLoadMs,
            noteTextLoadMs: timings.noteTextLoadMs,
            noteFolderLoadMs: timings.noteFolderLoadMs,
            previousSnapshotHydrationSkipped: timings.previousSnapshotHydrationSkipped || 0,
            documentSemanticSkipped: timings.documentSemanticSkipped || 0,
            nativeChunkerSkipped: timings.nativeChunkerSkipped || 0,
        },
        'Snapshot DB reads and persist timing',
    ));
    const payloadBreakdown = timings.snapshotPayloadBreakdown || {};
    if (Object.keys(payloadBreakdown).length) {
        stageReceipts.push(instrumentationStage(
            'snapshotPayloadProfile',
            'Snapshot Payload',
            Math.round(timings.snapshotPayloadProfileMs || 0),
            payloadBreakdown,
            'Top-level snapshot JSON payload section sizes',
        ));
    }
    stageReceipts.push(instrumentationStage(
        'snapshotCpu',
        'Snapshot CPU',
        Math.round(
            (timings.nativeCompilerMs || 0)
            + timings.occurrenceRecoverMs
            + timings.snapshotBuildMs
            + (timings.authoritySealMs || 0)
            + (timings.authorityAssertMs || 0),
        ),
        {
            occurrenceRecoverMs: timings.occurrenceRecoverMs,
            snapshotBuildMs: timings.snapshotBuildMs,
            nativeCompilerMs: timings.nativeCompilerMs || 0,
            nativeCompilerSkipped: timings.nativeCompilerSkipped || 0,
            authoritySealMs: timings.authoritySealMs || 0,
            authorityAssertMs: timings.authorityAssertMs || 0,
            serviceStateCommitMs: timings.stateCommitMs,
            totalBuildMs: timings.totalMs,
        },
        'Graph rebuild CPU and service state timing',
    ));
    const inputFamilies = timings.nativeCompilerInputBytesByFamily || {};
    const targetFamilies = timings.nativeTargetsByOriginatingFamily || {};
    stageReceipts.push(instrumentationStage(
        'nativeCompilerBoundary',
        'Native Compiler Boundary',
        Math.round(timings.nativeCompilerMs || 0),
        {
            nativeCompilerInputBytes: Object.values(inputFamilies).reduce((sum, value) => sum + value, 0),
            nativeCompilerSkipped: timings.nativeCompilerSkipped || 0,
            nativeAtlasSeedRawBytes: timings.nativeAtlasSeedRawBytes || 0,
            nativeAtlasSeedCompressedBytes: timings.nativeAtlasSeedCompressedBytes || 0,
            nativeTargets: Object.values(targetFamilies).reduce((sum, value) => sum + value, 0),
            ...Object.fromEntries(Object.entries(inputFamilies).map(([family, bytes]) =>
                [`compilerInput.${family}.bytes`, bytes],
            )),
            ...Object.fromEntries(Object.entries(targetFamilies).map(([family, count]) =>
                [`nativeTargets.${family}`, count],
            )),
        },
        'Compiler request bytes and admitted native targets by originating family',
    ));
}

function appendTransportTimingStage(
    stageReceipts: GraphIndexStageReceipt[],
    before: PhoenixTransportAuditSnapshot,
    after: PhoenixTransportAuditSnapshot,
): void {
    const counters = transportDeltaCounters(before, after);
    if (!counters['transportCalls'] && !counters['transportTotalMs']) return;
    stageReceipts.push(instrumentationStage(
        'transportOps',
        'Transport Ops',
        counters['transportTotalMs'],
        counters,
        'TauRPC transport calls and payload volume during this graph run',
    ));
}

type TransportAggregate = PhoenixTransportAuditSnapshot['calls'][number];

function contentMutationTimingCounters(
    timing: PhoenixContentMutationTiming | undefined,
    prefix: string,
): Record<string, number> {
    if (!timing) return {};
    return {
        [`${prefix}Records`]: timing.records,
        [`${prefix}PayloadChars`]: timing.payloadChars,
        [`${prefix}ScopedDocuments`]: timing.scopedDocumentUpserts,
        [`${prefix}QueueWaitMs`]: timing.serializedWaitMs,
        [`${prefix}AppendWalMs`]: timing.appendWalMs,
        [`${prefix}ManifestMs`]: timing.manifestCommitMs,
        [`${prefix}NativeApplyMs`]: timing.runtimeApplyMs,
        [`${prefix}ReloadMs`]: timing.runtimeReloadMs,
        [`${prefix}TotalMs`]: timing.totalMs,
        [`${prefix}CheckpointScheduled`]: timing.checkpointScheduled,
        [`${prefix}RuntimeReloaded`]: timing.runtimeReloaded,
    };
}

function transportDeltaCounters(
    before: PhoenixTransportAuditSnapshot,
    after: PhoenixTransportAuditSnapshot,
): Record<string, number> {
    const beforeByKey = new Map(before.calls.map((call) => [transportAggregateKey(call), call]));
    const counters: Record<string, number> = {
        transportCalls: 0,
        transportErrors: 0,
        transportTotalMs: 0,
        transportMaxMs: 0,
        transportRequestBytes: 0,
        transportResponseBytes: 0,
        jsonRpcCalls: 0,
        jsonRpcRequestBytes: 0,
        jsonRpcResponseBytes: 0,
        typedRpcCalls: 0,
        typedRpcRequestBytes: 0,
        typedRpcResponseBytes: 0,
        bootSnapshotJsonCalls: 0,
        bootSnapshotJsonRequestBytes: 0,
        bootSnapshotJsonResponseBytes: 0,
        scanJsonCalls: 0,
        scanJsonRequestBytes: 0,
        scanJsonResponseBytes: 0,
        atlasRichScanJsonCalls: 0,
        atlasRichScanJsonRequestBytes: 0,
        atlasRichScanJsonResponseBytes: 0,
        graphDeltaJsonCalls: 0,
        graphDeltaJsonRequestBytes: 0,
        graphDeltaJsonResponseBytes: 0,
        initRuntimeCalls: 0,
        initRuntimeRequestBytes: 0,
        initRuntimeResponseBytes: 0,
        storeCommandCalls: 0,
        storeCommandTotalMs: 0,
        storeCommandRequestBytes: 0,
        storeCommandResponseBytes: 0,
        applyWalBatchCalls: 0,
        applyWalBatchRequestBytes: 0,
        applyWalBatchResponseBytes: 0,
        compileDualWriteCalls: 0,
        compileDualWriteRequestBytes: 0,
        compileDualWriteResponseBytes: 0,
        compileDualWriteRawBytes: 0,
        compileDualWriteCompressedBytes: 0,
        compileGalaxySceneCalls: 0,
        compileGalaxySceneRequestBytes: 0,
        compileGalaxySceneResponseBytes: 0,
        graphScenePacketCalls: 0,
        graphScenePacketRequestBytes: 0,
        graphScenePacketResponseBytes: 0,
        applyWalBatchNativeParseMs: 0,
        applyWalBatchNativeApplyMs: 0,
        applyWalBatchNativeRelationMs: 0,
        applyWalBatchNativeLexMs: 0,
        applyWalBatchNativeLexRebuilt: 0,
        applyWalBatchNativeScopedDocumentUpserts: 0,
    };
    for (const call of after.calls) {
        const previous = beforeByKey.get(transportAggregateKey(call));
        const count = Math.max(0, call.count - (previous?.count || 0));
        if (!count) continue;
        const totalMs = Math.max(0, call.totalMs - (previous?.totalMs || 0));
        const requestBytes = Math.max(0, call.totalRequestBytes - (previous?.totalRequestBytes || 0));
        const responseBytes = Math.max(0, call.totalResponseBytes - (previous?.totalResponseBytes || 0));
        const errors = Math.max(0, call.errors - (previous?.errors || 0));
        const localMaxMs = call.maxMs > (previous?.maxMs || 0)
            ? call.maxMs
            : (count ? totalMs / count : 0);
        counters['transportCalls'] += count;
        counters['transportErrors'] += errors;
        counters['transportTotalMs'] += totalMs;
        counters['transportRequestBytes'] += requestBytes;
        counters['transportResponseBytes'] += responseBytes;
        counters['transportMaxMs'] = Math.max(counters['transportMaxMs'], localMaxMs);
        if (call.kind === 'taurpc-json') {
            addTransportFamilyCounters(counters, 'jsonRpc', count, totalMs, requestBytes, responseBytes);
        }
        if (call.kind === 'taurpc-typed') {
            addTransportFamilyCounters(counters, 'typedRpc', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name === 'phoenix.boot_snapshot_json') {
            addTransportFamilyCounters(counters, 'bootSnapshotJson', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name === 'phoenix.scan_json') {
            addTransportFamilyCounters(counters, 'scanJson', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name === 'phoenix.atlas_rich_scan_json') {
            addTransportFamilyCounters(counters, 'atlasRichScanJson', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name === 'phoenix.graph_delta_json') {
            addTransportFamilyCounters(counters, 'graphDeltaJson', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name === 'phoenix.init_runtime') {
            addTransportFamilyCounters(counters, 'initRuntime', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name.startsWith('phoenix.store_command:')) {
            addTransportFamilyCounters(counters, 'storeCommand', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name.startsWith('phoenix.store_command:relation:list:')) {
            addTransportFamilyCounters(counters, 'relationList', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name.startsWith('phoenix.store_command:relation:getFirst:')) {
            addTransportFamilyCounters(counters, 'relationGetFirst', count, totalMs, requestBytes, responseBytes);
        }
        if (call.name.startsWith('phoenix.store_command:relation:getFirst:scoped_documents')) {
            addTransportFamilyCounters(counters, 'scopedDocumentRead', count, totalMs, requestBytes, responseBytes);
            if (call.name.endsWith(':snapshot')) {
                addTransportFamilyCounters(counters, 'snapshotDocumentRead', count, totalMs, requestBytes, responseBytes);
            } else if (call.name.endsWith(':receipt')) {
                addTransportFamilyCounters(counters, 'receiptDocumentRead', count, totalMs, requestBytes, responseBytes);
            } else if (call.name.endsWith(':postprocess-cache')) {
                addTransportFamilyCounters(counters, 'postprocessCacheRead', count, totalMs, requestBytes, responseBytes);
            } else if (call.name.endsWith(':overgraph')) {
                addTransportFamilyCounters(counters, 'overGraphDocumentRead', count, totalMs, requestBytes, responseBytes);
            }
        }
        if (call.name.startsWith('phoenix.store_command:note:')) {
            addTransportFamilyCounters(counters, 'noteCommand', count, totalMs, requestBytes, responseBytes);
            if (call.name.endsWith(':body')) {
                addTransportFamilyCounters(counters, 'noteBodyRead', count, totalMs, requestBytes, responseBytes);
            }
        }
        if (call.name === 'phoenix.store_command:persistence:applyWalBatch') {
            counters['applyWalBatchCalls'] += count;
            counters['applyWalBatchRequestBytes'] += requestBytes;
            counters['applyWalBatchResponseBytes'] += responseBytes;
            const payloadCounters = transportPayloadCounterDelta(call, previous);
            counters['applyWalBatchNativeParseMs'] += payloadCounters['payload.timings.parseMs'] || 0;
            counters['applyWalBatchNativeApplyMs'] += payloadCounters['payload.timings.totalMs'] || 0;
            counters['applyWalBatchNativeRelationMs'] += payloadCounters['payload.timings.relationMs'] || 0;
            counters['applyWalBatchNativeLexMs'] += payloadCounters['payload.timings.lexMs'] || 0;
            counters['applyWalBatchNativeLexRebuilt'] += payloadCounters['payload.timings.lexRebuilt'] || 0;
            counters['applyWalBatchNativeScopedDocumentUpserts'] += payloadCounters['payload.timings.scopedDocumentUpserts'] || 0;
        }
        if (call.name === 'phoenix.store_command:graphRebuild:compileDualWrite') {
            counters['compileDualWriteCalls'] += count;
            counters['compileDualWriteRequestBytes'] += requestBytes;
            counters['compileDualWriteResponseBytes'] += responseBytes;
            const payloadCounters = transportPayloadCounterDelta(call, previous);
            counters['compileDualWriteRawBytes'] += payloadCounters['payload.factGraphPayload.rawBytes'] || 0;
            counters['compileDualWriteCompressedBytes'] += payloadCounters['payload.factGraphPayload.compressedBytes'] || 0;
        }
        if (call.name === 'phoenix.compile_galaxy_scene') {
            counters['compileGalaxySceneCalls'] += count;
            counters['compileGalaxySceneRequestBytes'] += requestBytes;
            counters['compileGalaxySceneResponseBytes'] += responseBytes;
        }
        if (call.name === 'phoenix.graph_scene_packet_json') {
            counters['graphScenePacketCalls'] += count;
            counters['graphScenePacketRequestBytes'] += requestBytes;
            counters['graphScenePacketResponseBytes'] += responseBytes;
        }
    }
    for (const key of Object.keys(counters)) {
        counters[key] = Math.round(counters[key] || 0);
    }
    return counters;
}

function addTransportFamilyCounters(
    counters: Record<string, number>,
    prefix: string,
    count: number,
    totalMs: number,
    requestBytes: number,
    responseBytes: number,
): void {
    counters[`${prefix}Calls`] = (counters[`${prefix}Calls`] || 0) + count;
    counters[`${prefix}TotalMs`] = (counters[`${prefix}TotalMs`] || 0) + totalMs;
    counters[`${prefix}RequestBytes`] = (counters[`${prefix}RequestBytes`] || 0) + requestBytes;
    counters[`${prefix}ResponseBytes`] = (counters[`${prefix}ResponseBytes`] || 0) + responseBytes;
}

function transportAggregateKey(call: TransportAggregate): string {
    return `${call.kind}:${call.name}`;
}

function transportPayloadCounterDelta(
    call: TransportAggregate,
    previous: TransportAggregate | undefined,
): Record<string, number> {
    const out: Record<string, number> = {};
    const current = call.counters || {};
    const before = previous?.counters || {};
    for (const [key, value] of Object.entries(current)) {
        out[key] = Math.max(0, value - (before[key] || 0));
    }
    return out;
}

function prefixedCounters(counters: Record<string, number>, prefix: string): Record<string, number> {
    const out: Record<string, number> = {};
    for (const [key, value] of Object.entries(counters)) {
        out[`${prefix}${key.slice(0, 1).toUpperCase()}${key.slice(1)}`] = value;
    }
    return out;
}

function appendSignalCoverageStages(
    stageReceipts: GraphIndexStageReceipt[],
    snapshot: GraphRebuildSnapshot,
): void {
    const targetCounts = countEmbeddingTargetFamilies(snapshot);
    const targetTotal = snapshot.embeddingTargets?.length || 0;
    const plan = snapshot.embeddingTargetPlan;
    stageReceipts.push(instrumentationStage(
        'signalTargetCoverage',
        'Signal Target Coverage',
        0,
        {
            targets: targetTotal,
            candidateTargets: plan?.candidateCount || targetTotal,
            deferredTargets: plan?.deferredCount || 0,
            documentSpine: planLaneCount(plan, 'document_spine'),
            documentSpineCandidates: planLaneCandidates(plan, 'document_spine'),
            documentSpineDeferred: planLaneDeferred(plan, 'document_spine'),
            chunkSpine: planLaneCount(plan, 'chunk_spine'),
            chunkSpineCandidates: planLaneCandidates(plan, 'chunk_spine'),
            chunkSpineDeferred: planLaneDeferred(plan, 'chunk_spine'),
            entityAnchors: planLaneCount(plan, 'entity_anchor'),
            entityAnchorsCandidates: planLaneCandidates(plan, 'entity_anchor'),
            entityAnchorsDeferred: planLaneDeferred(plan, 'entity_anchor'),
            relationshipFacts: planLaneCount(plan, 'relationship_fact'),
            relationshipFactsCandidates: planLaneCandidates(plan, 'relationship_fact'),
            relationshipFactsDeferred: planLaneDeferred(plan, 'relationship_fact'),
            temporalFacts: planLaneCount(plan, 'temporal_fact'),
            temporalFactsCandidates: planLaneCandidates(plan, 'temporal_fact'),
            temporalFactsDeferred: planLaneDeferred(plan, 'temporal_fact'),
            causalFacts: planLaneCount(plan, 'causal_fact'),
            causalFactsCandidates: planLaneCandidates(plan, 'causal_fact'),
            causalFactsDeferred: planLaneDeferred(plan, 'causal_fact'),
            memoryStates: planLaneCount(plan, 'memory_state'),
            memoryStatesCandidates: planLaneCandidates(plan, 'memory_state'),
            memoryStatesDeferred: planLaneDeferred(plan, 'memory_state'),
            eventIdentities: planLaneCount(plan, 'event_identity'),
            eventIdentitiesCandidates: planLaneCandidates(plan, 'event_identity'),
            eventIdentitiesDeferred: planLaneDeferred(plan, 'event_identity'),
            anchorEvidence: planLaneCount(plan, 'anchor_evidence'),
            anchorEvidenceCandidates: planLaneCandidates(plan, 'anchor_evidence'),
            anchorEvidenceDeferred: planLaneDeferred(plan, 'anchor_evidence'),
            weakCooccurrence: planLaneCount(plan, 'cooccurrence_weak'),
            weakCooccurrenceCandidates: planLaneCandidates(plan, 'cooccurrence_weak'),
            weakCooccurrenceDeferred: planLaneDeferred(plan, 'cooccurrence_weak'),
            entityTargets: targetCounts['entity'],
            graphFactTargets: targetCounts['graphFact'],
            eventTargets: targetCounts['event'],
            temporalFactTargets: targetCounts['temporalFact'],
            causalFactTargets: targetCounts['causalFact'],
            memoryStateTargets: targetCounts['memoryState'],
            anchorTargets: targetCounts['anchor'],
            chunkTargets: targetCounts['chunk'],
            noteTargets: targetCounts['note'],
            acceptedRelationships: snapshot.counters.acceptedRelationships || 0,
            reviewRelationships: snapshot.counters.reviewRelationships || 0,
            rejectedRelationships: snapshot.counters.rejectedRelationships || 0,
            events: snapshot.counters.events || 0,
            temporalEdges: snapshot.counters.temporalEdges || 0,
            causalEdges: snapshot.counters.causalEdges || 0,
            memoryState: snapshot.counters.memoryState || 0,
        },
        'Embedding target family coverage and graph signal starvation audit',
    ));
}

function appendGraphTruthContractStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const contract = assertGraphSnapshotAuthority(snapshot);
    const counts = contract.counts;
    stageReceipts.push(instrumentationStage(
        'snapshotAuthorityContract',
        'Snapshot Authority Contract',
        0,
        {
            authorityParity: 1,
            chunks: counts.chunks,
            mentions: counts.mentions,
            anchors: counts.anchors,
            relationships: counts.relationships,
            temporalEdges: counts.temporalEdges,
            causalEdges: counts.causalEdges,
            coreferenceRecoveries: counts.coreferenceRecoveries,
            nodes: counts.nodes,
            edges: counts.edges,
            embeddingTargets: counts.embeddingTargets,
            admittedEmbeddingTargets: counts.admittedEmbeddingTargets,
            packetObjects: counts.packetObjects,
            packetTargets: counts.packetTargets,
            packetParentLinks: counts.packetParentLinks,
        },
        `${contract.authority} / ${contract.contentHash}`,
    ));
}

function appendEntityLinkerPlanStage(
    stageReceipts: GraphIndexStageReceipt[],
    snapshot: GraphRebuildSnapshot,
    enabled: boolean,
): void {
    const counters: Partial<GraphRebuildEntityLinkCounters> = snapshot.counters.entityLinking || {};
    stageReceipts.push(instrumentationStage(
        'entityLinkerPlan',
        'Entity Linker Plan',
        0,
        {
            entityLinkerEnabled: enabled ? 1 : 0,
            narrowRetrieverReady: 1,
            modelRunnerReady: 0,
            modelCalls: 0,
            shadowLinks: counters.shadowLinks || snapshot.counters.shadowLinkSuggestions || 0,
            candidateLinks: counters.candidateLinks || snapshot.counters.shadowLinkSuggestions || snapshot.counters.entityLinkSuggestions || 0,
            linkerCandidates: counters.linkerCandidates || 0,
            finalLinkPatches: snapshot.counters.finalLinkPatches || 0,
            finalLinkReceiptFailures: snapshot.counters.finalLinkReceiptFailures || 0,
            autoConfirmableLinks: counters.autoConfirmable || 0,
            ambiguousLinks: counters.ambiguous || 0,
            rejectedLinks: counters.rejected || 0,
        },
        `${GLINER_LINKER_MODEL_ID} inference pending; ShadowLinker stages candidates, FinalLinker waits for promoted clean receipts`,
    ));
}

function appendDeltaPostProcessPlanStage(
    stageReceipts: GraphIndexStageReceipt[],
    input: {
        policy: GraphIndexRunRequest['policy'];
        docs: ScopedDocument[];
        entities: Array<{ id: string; label: string; kind: string; aliases?: string[] }>;
        cachedSnapshot: GraphRebuildSnapshot | null | undefined;
        fingerprintMatched: boolean;
    },
): GraphRebuildDeltaPostProcessPlan {
    const plan = buildGraphRebuildDeltaPostProcessPlan(input);
    stageReceipts.push(instrumentationStage(
        'deltaPostprocessPlan',
        'Delta Postprocess Plan',
        0,
        deltaPostProcessPlanCounters(plan),
        'Delta orchestration lanes selected before graph postprocess work',
    ));
    return plan;
}

function appendEdgeJudgmentPlanStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const plan = buildGraphRebuildEdgeJudgmentPlan(snapshot);
    stageReceipts.push(instrumentationStage(
        'edgeTypeJudgmentPlan',
        'Edge Type Judgment Plan',
        0,
        edgeJudgmentPlanCounters(plan),
        'GLiClass edge/type candidate plan ready; no graph mutation yet',
    ));
}

function appendSemanticRerankStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.semanticRerankSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'semanticRerankPlan',
        'Semantic Rerank Plan',
        0,
        {
            inputs: summary.counters.inputCount,
            judgments: summary.counters.judgmentCount,
            receipts: summary.counters.receiptCount,
            plannedModelCalls: summary.counters.plannedModelCalls,
            accepted: summary.counters.byDecision['accept'] || 0,
            reviewed: summary.counters.byDecision['review'] || 0,
            deferred: summary.counters.byDecision['defer'] || 0,
            rejected: summary.counters.byDecision['reject'] || 0,
            deterministicCalibration: summary.counters.byScoreSource['deterministic_calibration'] || 0,
            modelScored: summary.counters.byScoreSource['gliclass_instruct'] || 0,
        },
        `${summary.modelId} query-label rerank plan ready; smoke uses calibration until model scores are attached`,
    ));
}

function appendSemanticAdjudicationStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.semanticAdjudicationSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'semanticAdjudicationDag',
        'Semantic Adjudication DAG',
        summary.counters.mutationCount,
        {
            decisions: summary.counters.decisionCount,
            mutations: summary.counters.mutationCount,
            appliedMutations: summary.counters.appliedMutationCount,
            receipts: summary.counters.receiptCount,
            ledgerOnly: summary.counters.ledgerOnlyCount,
            accepted: summary.counters.byState['accepted'] || 0,
            supported: summary.counters.byState['supported'] || 0,
            deferred: summary.counters.byState['deferred'] || 0,
            rejected: summary.counters.byState['rejected'] || 0,
            invalidated: summary.counters.byState['invalidated'] || 0,
            superseded: summary.counters.byState['superseded'] || 0,
        },
        'Accepted semantic topology is applied by the frozen graph-rebuild live contract with reversible receipts',
    ));
}

function appendSemanticEvalLedgerStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.semanticEvalLedgerSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'semanticEvalLedger',
        'Semantic Eval Ledger',
        summary.counters.rowCount,
        {
            rows: summary.counters.rowCount,
            acceptedCandidates: summary.counters.acceptedCandidates,
            rejectedCandidates: summary.counters.rejectedCandidates,
            ambiguousCases: summary.counters.ambiguousCases,
            userCorrections: summary.counters.userCorrections,
            modelDisagreements: summary.counters.modelDisagreements,
            manifoldDisagreements: summary.counters.manifoldDisagreements,
            graphChangeRows: summary.counters.graphChangeRows,
        },
        'Phase 6 compact dataset export ready for classifier, reranker, router, and model-swap evals',
    ));
}

function appendMemoryGraphRagBridgeStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.memoryGraphRagBridgeSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'memoryGraphRagBridge',
        'MemoryGraphRAG Bridge',
        summary.counters.evalRowCount,
        {
            records: summary.counters.recordCount,
            schemaRecords: summary.counters.schemaRecords,
            factRecords: summary.counters.factRecords,
            passageRecords: summary.counters.passageRecords,
            evalRows: summary.counters.evalRowCount,
            passedEvalRows: summary.counters.passedEvalRows,
            failedEvalRows: summary.counters.failedEvalRows,
            observerSeeds: summary.counters.observerSeedRecords,
            reflectorSeeds: summary.counters.reflectorSeedRecords,
            retrievalRecords: summary.counters.retrievalRecords,
            conflictRecords: summary.counters.conflictRecords,
            receipts: summary.counters.receiptCount,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        'MemGraphRAG-style schema/fact/passage bridge ready for OM observer, reflector, and retrieval evals',
    ));
}

function appendDiscourseSpineStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.discourseSpineSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'discourseSpine',
        'Discourse Spine',
        0,
        {
            targets: summary.counters.targetCount,
            documentRoots: summary.counters.documentRoots,
            documents: summary.counters.documents,
            chunks: summary.counters.chunks,
            labels: summary.counters.labelCount,
            clusters: summary.counters.clusterCount,
            bridges: summary.counters.bridgeCount,
            resonance: summary.counters.resonanceCandidates,
            resolution: summary.counters.resolutionCandidates,
            proposedBridges: summary.counters.proposedBridges,
            deferredBridges: summary.counters.deferredBridges,
            receipts: summary.counters.receiptCount,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        'Document roots, documents, chunks, and wormhole proposals indexed as read-only discourse receipts',
    ));
}

function appendDiscourseBridgeCandidateStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.discourseBridgeCandidateSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'discourseBridgeCandidates',
        'Discourse Bridge Candidates',
        0,
        {
            candidates: summary.counters.candidateCount,
            inputs: summary.counters.inputCount,
            judgments: summary.counters.judgmentCount,
            evalRows: summary.counters.evalRowCount,
            plannedModelCalls: summary.counters.plannedModelCalls,
            acceptedLookingResonance: summary.counters.acceptedLookingResonance,
            weakResonance: summary.counters.weakResonance,
            resolverPressure: summary.counters.crossDocResolverPressure,
            entityOnlyOverlap: summary.counters.entityOverlapWithoutMeaning,
            meaningOnlyOverlap: summary.counters.meaningOverlapWithoutEntity,
            accepted: summary.counters.byDecision['accept'] || 0,
            reviewed: summary.counters.byDecision['review'] || 0,
            deferred: summary.counters.byDecision['defer'] || 0,
            rejected: summary.counters.byDecision['reject'] || 0,
            deterministicCalibration: summary.counters.byScoreSource['deterministic_calibration'] || 0,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        'Discourse wormholes packaged as GLiClass-shaped eval candidates; topology remains sealed',
    ));
}

function appendDiscourseBridgeAdjudicationStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.discourseBridgeAdjudicationSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'discourseBridgeAdjudication',
        'Discourse Bridge Adjudication',
        0,
        {
            decisions: summary.counters.decisionCount,
            accepted: summary.counters.acceptedCount,
            supported: summary.counters.supportedCount,
            deferred: summary.counters.deferredCount,
            rejected: summary.counters.rejectedCount,
            invalidated: summary.counters.invalidatedCount,
            superseded: summary.counters.supersededCount,
            receipts: summary.counters.receiptCount,
            ledgerOnly: summary.counters.ledgerOnlyCount,
            topologyCommits: summary.counters.topologyCommitCount,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        'Discourse bridge decisions are reversible ledger rows; accepted rows wait for a future promotion lane',
    ));
}

function appendDiscourseEvalLedgerStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.discourseEvalLedgerSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'discourseEvalLedger',
        'Discourse Eval Ledger',
        summary.counters.rowCount,
        {
            rows: summary.counters.rowCount,
            acceptedCandidates: summary.counters.acceptedCandidates,
            rejectedCandidates: summary.counters.rejectedCandidates,
            ambiguousCases: summary.counters.ambiguousCases,
            userCorrections: summary.counters.userCorrections,
            modelDisagreements: summary.counters.modelDisagreements,
            manifoldDisagreements: summary.counters.manifoldDisagreements,
            evalDisagreements: summary.counters.evalDisagreements,
            resonanceRows: summary.counters.resonanceRows,
            resolutionRows: summary.counters.resolutionRows,
            clusterReviewRows: summary.counters.clusterReviewRows,
            graphChangeRows: summary.counters.graphChangeRows,
        },
        'Compact discourse dataset export ready for document classifiers, bridge rerankers, resolver evals, and model swaps',
    ));
}

function appendDiscoursePromotionSurfaceStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.discoursePromotionSurfaceSummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'discoursePromotionSurface',
        'Discourse Promotion Surface',
        summary.counters.compilerHintCount,
        {
            chunkWormholes: summary.counters.chunkWormholeCount,
            documentClusters: summary.counters.documentClusterCount,
            resolverCandidates: summary.counters.resolverCandidateCount,
            compilerHints: summary.counters.compilerHintCount,
            acceptedRows: summary.counters.acceptedRows,
            ambiguousRows: summary.counters.ambiguousRows,
            receipts: summary.counters.receiptCount,
            graphPatches: summary.counters.graphPatchCount,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        'Discourse wormholes, document clusters, and resolver hints are surfaced for UI/compiler consumers without graph patches',
    ));
}

function appendDiscourseCompilerOverlayStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.discourseCompilerOverlaySummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'discourseCompilerOverlay',
        'Discourse Compiler Overlay',
        summary.counters.overlayEdgeCount,
        {
            overlayEdges: summary.counters.overlayEdgeCount,
            chunkWormholes: summary.counters.chunkWormholeEdges,
            documentClusters: summary.counters.documentClusterEdges,
            resolvers: summary.counters.resolverEdges,
            receipts: summary.counters.receiptCount,
            graphPatches: summary.counters.graphPatchCount,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        'Promotion hints are exposed as read-only compiler overlay edges for atlas consumers without topology writes',
    ));
}

function appendCalendarRegistryStage(stageReceipts: GraphIndexStageReceipt[], snapshot: GraphRebuildSnapshot): void {
    const summary = snapshot.calendarRegistrySummary;
    if (!summary) return;
    stageReceipts.push(instrumentationStage(
        'calendarRegistryBridge',
        'Calendar Registry Bridge',
        0,
        {
            anchors: summary.counters.anchorCount,
            receipts: summary.counters.receiptCount,
            acceptedTemporalReceipts: summary.counters.acceptedTemporalReceipts,
            registryOnly: summary.counters.registryOnlyReceipts,
            deferredInvalid: summary.counters.deferredInvalidReceipts,
            realEpochReceipts: summary.counters.realEpochReceipts,
            customOrdinalReceipts: summary.counters.customOrdinalReceipts,
            eventReceipts: summary.counters.eventReceipts,
            folderReceipts: summary.counters.folderReceipts,
            periodReceipts: summary.counters.periodReceipts,
            markerReceipts: summary.counters.markerReceipts,
            mutationAllowed: summary.counters.mutationAllowedCount,
        },
        `${summary.calendarMode} calendar anchors bridged as temporal receipts; graph mutations remain adjudication-controlled`,
    ));
}

function planLaneCount(
    plan: GraphRebuildSnapshot['embeddingTargetPlan'] | undefined,
    lane: string,
): number {
    return plan?.lanes.find((row) => row.lane === lane)?.admitted || 0;
}

function planLaneCandidates(
    plan: GraphRebuildSnapshot['embeddingTargetPlan'] | undefined,
    lane: string,
): number {
    return plan?.lanes.find((row) => row.lane === lane)?.candidates || 0;
}

function planLaneDeferred(
    plan: GraphRebuildSnapshot['embeddingTargetPlan'] | undefined,
    lane: string,
): number {
    return plan?.lanes.find((row) => row.lane === lane)?.deferred || 0;
}

function appendNliStagingStages(stageReceipts: GraphIndexStageReceipt[], rawResult: unknown): void {
    const stages = arrayField(rawResult, 'stageSummaries');
    for (const row of stages) {
        if (!row || typeof row !== 'object') continue;
        const record = row as Record<string, unknown>;
        const stage = stringField(record, 'stage');
        const label = nliStageLabel(stage);
        if (!label) continue;
        const durationMs = numberField(record, 'durationMs');
        const counters = numberCounts(record['counts']);
        stageReceipts.push(instrumentationStage(
            `nli${stage.slice(0, 1).toUpperCase()}${stage.slice(1)}`,
            label,
            durationMs,
            counters,
            `${label} completed`,
        ));
    }
}

function nliStageLabel(stage: string): string {
    switch (stage) {
        case 'candidatePlan': return 'NLI Candidate Plan';
        case 'modelWarm': return 'NLI Model Warm';
        case 'classification': return 'NLI Classification';
        case 'apply': return 'NLI Apply';
        default: return '';
    }
}

function signalCandidatePlanStage(input: {
    discoveryStage: GraphIndexStageReceipt;
    docs: ScopedDocument[];
    entities: Array<{ id: string }>;
    cachedSnapshot: GraphRebuildSnapshot | null | undefined;
    sourceEvidenceOccurrences?: unknown[];
}): GraphIndexStageReceipt {
    const discovery = input.discoveryStage.counters || {};
    const discoveryCandidates = discovery['candidateSuggestions'] || discovery['suggestions'] || discovery['candidates'] || 0;
    const exportableMentions = discovery['exportableMentions'] || discovery['mentions'] || discovery['acceptedAnchors'] || 0;
    const documentChars = input.docs.reduce((sum, doc) => sum + doc.plainText.length, 0);
    const prior = input.cachedSnapshot;
    return instrumentationStage(
        'signalCandidatePlan',
        'Signal Candidate Plan',
        0,
        {
            documents: input.docs.length,
            documentChars,
            entities: input.entities.length,
            discoveryCandidates,
            exportableMentions,
            discoveryCacheHit: discovery['discoveryCacheHit'] || 0,
            discoverySkipped: discovery['postprocessDiscoverySkipped'] || 0,
            priorTargets: prior?.counters.embeddingTargets || 0,
            priorMentions: prior?.counters.mentions || 0,
            priorAnchors: prior?.counters.acceptedAnchors || 0,
            priorGraphLinks: prior?.counters.graphAwareLinkSuggestions || 0,
            priorEntityLinks: prior?.counters.entityLinkSuggestions || 0,
            sourceEvidenceAnchors: input.sourceEvidenceOccurrences?.length || 0,
            plannedModelCalls: 0,
        },
        'Candidate ledger ready for label-conditioned signal adjudication',
    );
}

function countEmbeddingTargetFamilies(snapshot: GraphRebuildSnapshot): Record<string, number> {
    const counts: Record<string, number> = {
        note: 0,
        chunk: 0,
        entity: 0,
        anchor: 0,
        graphFact: 0,
        event: 0,
        temporalFact: 0,
        causalFact: 0,
        memoryState: 0,
    };
    for (const target of snapshot.embeddingTargets || []) {
        const key = normalizedTargetFamily(target.kind);
        counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
}

function normalizedTargetFamily(kind: string): string {
    const normalized = String(kind || '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase().replace(/[-_\s]+/g, '');
    if (normalized === 'graphfact') return 'graphFact';
    if (normalized === 'temporalfact') return 'temporalFact';
    if (normalized === 'causalfact') return 'causalFact';
    if (normalized === 'memorystate') return 'memoryState';
    return normalized || 'unknown';
}

function instrumentationStage(
    id: string,
    label: string,
    durationMs: number,
    counters: Record<string, number>,
    message: string,
): GraphIndexStageReceipt {
    const completedAt = Date.now();
    const safeDuration = Math.max(0, Math.round(durationMs || 0));
    return {
        id,
        label,
        status: 'completed',
        startedAt: completedAt - safeDuration,
        completedAt,
        durationMs: safeDuration,
        outputCount: 0,
        counters,
        message,
    };
}

function snapshotOwnedProjectionReceipt(
    mode: GraphIndexProjectionMode,
    snapshot: GraphRebuildSnapshot | null,
): GraphIndexProjectionReceipt {
    const now = Date.now();
    const targetCount = snapshot?.counters.embeddingTargets || 0;
    const contract = snapshot ? assertGraphSnapshotAuthority(snapshot) : undefined;
    return {
        mode,
        status: 'synced',
        startedAt: now,
        completedAt: now,
        durationMs: 0,
        targetCount,
        vectorCount: targetCount,
        snapshotId: contract?.snapshotId,
        snapshotHash: contract?.contentHash,
        counters: {
            graphRebuildTargets: targetCount,
            graphRebuildReadModelProjection: 1,
            nativeSemanticSidecarBypassed: 1,
        },
        message: 'Graph-rebuild snapshot projection synced; native Semantic Atlas sidecar bypassed because the snapshot owns postprocess topology',
    };
}

export function assertRunReceiptParity(receipt: GraphIndexRunReceipt, snapshot: GraphRebuildSnapshot): void {
    const contract = assertGraphSnapshotAuthority(snapshot);
    const issues: string[] = [];
    if (receipt.snapshotId !== contract.snapshotId) issues.push('snapshot id');
    const receiptCounts = receipt.counters;
    const expected = contract.counts;
    const countPairs: Array<[string, number, number]> = [
        ['chunks', receiptCounts.chunks, expected.chunks],
        ['mentions', receiptCounts.mentions, expected.mentions],
        ['anchors', receiptCounts.acceptedAnchors, expected.anchors],
        ['relationships', receiptCounts.relationships, expected.relationships],
        ['temporal edges', receiptCounts.temporalEdges, expected.temporalEdges],
        ['causal edges', receiptCounts.causalEdges, expected.causalEdges],
        ['nodes', receiptCounts.nodes, expected.nodes],
        ['edges', receiptCounts.edges, expected.edges],
        ['embedding targets', receiptCounts.embeddingTargets, expected.embeddingTargets],
    ];
    for (const [label, actual, required] of countPairs) {
        if (actual !== required) issues.push(`${label} ${actual} != ${required}`);
    }
    const authorityStage = receipt.stageReceipts.find((stage) => stage.id === 'snapshotAuthorityContract');
    if (!authorityStage || authorityStage.status !== 'completed' || authorityStage.counters['authorityParity'] !== 1) {
        issues.push('snapshot authority stage');
    }
    for (const projection of receipt.projectionReceipts) {
        if (projection.targetCount !== expected.embeddingTargets) {
            issues.push(`${projection.mode} targets ${projection.targetCount} != ${expected.embeddingTargets}`);
        }
        projection.snapshotId = contract.snapshotId;
        projection.snapshotHash = contract.contentHash;
    }
    const requiredLayerIds = [
        'input-signals',
        'snapshot-truth',
        'native-atlas-packet',
        'authority-seal',
        'persistence-payload',
        'projection-lenses',
        'diagnostic-ledgers',
        'transport-boundary',
        'ui-commit',
    ];
    const layerById = new Map((receipt.layerReceipts || []).map((layer) => [layer.id, layer]));
    for (const id of requiredLayerIds) {
        const layer = layerById.get(id);
        if (!layer) {
            issues.push(`layer receipt ${id}`);
            continue;
        }
        if (!layer.owner || !layer.source || !layer.message) issues.push(`layer explanation ${id}`);
        if (layer.id === 'authority-seal' && layer.contentHash !== contract.contentHash) {
            issues.push('authority layer hash');
        }
        if (layer.id === 'projection-lenses' && layer.status !== 'complete') {
            issues.push('projection layer status');
        }
    }
    if (issues.length) {
        throw new Error(`Graph run receipt parity failed for ${snapshot.id}: ${issues.join(', ')}`);
    }
    receipt.authorityContract = contract;
}

function atlasScopeFromGraphScope(scope: GraphIndexRunScope): AtlasBuildScope {
    if (scope.kind === 'note') return { mode: 'note', noteId: scope.noteIds[0] || scope.scopeId.replace(/^note:/, '') };
    if (scope.kind === 'multiNote') return { mode: 'multiNote', noteIds: scope.noteIds };
    if (scope.kind === 'folder') return { mode: 'folder', folderId: scope.scopeId.replace(/^folder:/, '') };
    if (scope.kind === 'narrative') return { mode: 'folder', folderId: scope.scopeId };
    return { mode: 'global' };
}

function appendStagedNativeScenePacketSkippedStage(
    stageReceipts: GraphIndexStageReceipt[],
    snapshot: GraphRebuildSnapshot | null,
): void {
    if (!snapshot?.counters.embeddingTargets) return;
    stageReceipts.push(instrumentationStage(
        'stagedNativeScenePacket',
        'Staged Native Scene Packet',
        0,
        {
            scenePacketAvailable: 0,
            rendererWired: 0,
            skippedCriticalPath: 1,
            expectedNodes: snapshot.embeddingTargets?.length || snapshot.counters.embeddingTargets || 0,
            embeddingBackboneEdges: snapshot.counters.embeddingBackboneEdges || 0,
            cleanGraphEdges: snapshot.counters.edges || 0,
        },
        'Skipped during postprocess; native scene-packet benchmarks must not block UI commit',
    ));
}

function appendInteractivePostCommitStage(
    stageReceipts: GraphIndexStageReceipt[],
    snapshot: GraphRebuildSnapshot,
): void {
    stageReceipts.push(instrumentationStage(
        'interactivePostCommitEnrichment',
        'Post-Commit Enrichment',
        0,
        {
            scheduledAfterUiCommit: 1,
            nativeCompilerDeferred: snapshot.buildTimings?.nativeCompilerSkipped ? 1 : 0,
            diagnosticArmsDeferred: 1,
            diagnosticIdleScheduled: 1,
            diagnosticDebounceMs: POST_COMMIT_DIAGNOSTIC_DEBOUNCE_MS,
            diagnosticOneFlightQueue: 1,
            diagnosticCancelOnNewerSnapshot: 1,
            packetObjects: snapshot.atlasPacket?.objects.length || 0,
            packetTargets: snapshot.atlasPacket?.manifoldTargets.length || 0,
        },
        'Native enrichment plus MemoryGraphRAG/discourse diagnostics are debounced, idle-scheduled, and queued outside the interactive UI path',
    ));
}

function capabilityLabel(id: AtlasCapabilityId): string {
    switch (id) {
        case 'semanticAtlas': return 'Semantic Atlas';
        case 'nliAdjudication': return 'NLI Adjudication';
        case 'relationGraph': return 'Relationship Rows';
        case 'temporalGraph': return 'Temporal Rows';
        case 'eventIdentity': return 'Event Identity Rows';
        case 'memoryState': return 'Memory/State Rows';
        case 'causalGraph': return 'Causal Rows';
        case 'hybridManifold': return 'Hybrid Projection';
        case 'hopfProjection': return 'Hopf Projection';
        case 'lorentzForest': return 'Hierarchy Caps Projection';
        case 'productManifold': return 'Product Manifold';
        default: return id;
    }
}

function numberCounts(value: unknown, prefix = ''): Record<string, number> {
    if (!value || typeof value !== 'object') return {};
    const counts: Record<string, number> = {};
    for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
        const name = prefix ? `${prefix}.${key}` : key;
        if (typeof raw === 'number' && Number.isFinite(raw)) {
            counts[name] = raw;
        } else if (Array.isArray(raw)) {
            counts[name] = raw.length;
            Object.assign(counts, atlasStageSummaryCounts(raw));
        } else if (raw && typeof raw === 'object') {
            Object.assign(counts, numberCounts(raw, name));
        }
    }
    return counts;
}

function atlasStageSummaryCounts(value: unknown[]): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const item of value) {
        if (!item || typeof item !== 'object') continue;
        const row = item as Record<string, unknown>;
        const stage = typeof row['stage'] === 'string' ? row['stage'] : '';
        if (!stage) continue;
        const prefix = stage.replace(/[^a-z0-9]+/gi, '');
        if (!prefix) continue;
        const duration = row['durationMs'];
        if (typeof duration === 'number' && Number.isFinite(duration)) {
            counts[`${prefix}Ms`] = duration;
        }
        const stageCounts = row['counts'];
        if (!stageCounts || typeof stageCounts !== 'object' || Array.isArray(stageCounts)) continue;
        for (const [key, raw] of Object.entries(stageCounts as Record<string, unknown>)) {
            if (typeof raw === 'number' && Number.isFinite(raw)) {
                counts[`${prefix}${capitalizeCounterKey(key)}`] = raw;
            }
        }
    }
    return counts;
}

function capitalizeCounterKey(value: string): string {
    return value ? `${value.slice(0, 1).toUpperCase()}${value.slice(1)}` : value;
}

function elapsedTimingMs(started: number): number {
    return Math.max(0, Math.round(performance.now() - started));
}

function jsonPayloadChars(value: unknown): number {
    try {
        return JSON.stringify(value ?? null).length;
    } catch {
        return 0;
    }
}

function receiptPersistenceKey(receipt: GraphIndexRunReceipt): string {
    return `${receipt.scope.kind}:${receipt.scope.scopeId}:${receipt.durabilityMode || 'durable'}`;
}

function graphIndexReceiptForPersistence(receipt: GraphIndexRunReceipt): GraphIndexRunReceipt {
    if (receipt.durabilityMode === 'interactive') return compactInteractiveReceiptForPersistence(receipt);
    return {
        ...receipt,
        modelReadiness: receipt.modelReadiness.map((model) => ({ ...model })),
        stageReceipts: receipt.stageReceipts
            .filter((stage) => stage.id !== 'receiptDbOps')
            .map((stage) => ({ ...stage, counters: { ...stage.counters } })),
        projectionReceipts: receipt.projectionReceipts.map((projection) => ({
            ...projection,
            counters: projection.counters ? { ...projection.counters } : undefined,
        })),
        layerReceipts: receipt.layerReceipts.map((layer) => ({
            ...layer,
            consumes: [...layer.consumes],
            produces: [...layer.produces],
            stageIds: [...layer.stageIds],
            projectionModes: layer.projectionModes ? [...layer.projectionModes] : undefined,
            counters: { ...layer.counters },
        })),
        counters: {
            ...receipt.counters,
            dropReasons: { ...receipt.counters.dropReasons },
        },
        dropReasons: { ...receipt.dropReasons },
        authorityContract: receipt.authorityContract ? { ...receipt.authorityContract } : undefined,
    };
}

function compactInteractiveReceiptForPersistence(receipt: GraphIndexRunReceipt): GraphIndexRunReceipt {
    const stages = receipt.stageReceipts
        .filter((stage) => stage.id !== 'receiptDbOps'
            && (stage.status === 'failed' || INTERACTIVE_PERSISTED_RECEIPT_STAGE_IDS.has(stage.id)))
        .map(compactStageReceiptForPersistence);
    const persistedStageIds = new Set(stages.map((stage) => stage.id));
    return {
        ...receipt,
        modelReadiness: receipt.modelReadiness.map((model) => ({ ...model })),
        stageReceipts: stages,
        projectionReceipts: receipt.projectionReceipts.map((projection) => ({
            mode: projection.mode,
            status: projection.status,
            startedAt: projection.startedAt,
            completedAt: projection.completedAt,
            durationMs: projection.durationMs,
            targetCount: projection.targetCount,
            vectorCount: projection.vectorCount,
            counters: projection.counters ? { ...projection.counters } : undefined,
            snapshotId: projection.snapshotId,
            snapshotHash: projection.snapshotHash,
            message: projection.message,
        })),
        layerReceipts: receipt.layerReceipts.map((layer) => ({
            id: layer.id,
            label: layer.label,
            kind: layer.kind,
            status: layer.status,
            owner: layer.owner,
            source: layer.source,
            consumes: [...layer.consumes],
            produces: [...layer.produces],
            stageIds: layer.stageIds.filter((id) => persistedStageIds.has(id)),
            projectionModes: layer.projectionModes ? [...layer.projectionModes] : undefined,
            authority: layer.authority,
            contentHash: layer.contentHash,
            counters: { ...layer.counters },
            message: layer.message,
        })),
        counters: {
            ...receipt.counters,
            dropReasons: { ...receipt.counters.dropReasons },
        },
        dropReasons: { ...receipt.dropReasons },
        authorityContract: receipt.authorityContract ? { ...receipt.authorityContract } : undefined,
    };
}

function compactStageReceiptForPersistence(stage: GraphIndexStageReceipt): GraphIndexStageReceipt {
    return {
        id: stage.id,
        label: stage.label,
        status: stage.status,
        startedAt: stage.startedAt,
        completedAt: stage.completedAt,
        durationMs: stage.durationMs,
        outputCount: stage.outputCount,
        counters: { ...stage.counters },
        message: stage.message,
    };
}

function waitForUiFrame(): Promise<void> {
    if (typeof requestAnimationFrame !== 'function') return Promise.resolve();
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function deferReceiptPersistenceTurn(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function postCommitSchedulerWindow(): PostCommitSchedulerWindow | null {
    return typeof window === 'undefined' ? null : window as PostCommitSchedulerWindow;
}

function schedulePostCommitIdleWork(
    scheduler: PostCommitSchedulerWindow,
    callback: () => void,
): () => void {
    if (typeof scheduler.requestIdleCallback === 'function') {
        const idleHandle = scheduler.requestIdleCallback(callback, {
            timeout: POST_COMMIT_DIAGNOSTIC_IDLE_TIMEOUT_MS,
        });
        return () => scheduler.cancelIdleCallback?.(idleHandle);
    }
    const timeoutHandle = scheduler.setTimeout(callback, 0);
    return () => scheduler.clearTimeout(timeoutHandle);
}

function sumOutputCounts(counts: Record<string, number>): number {
    return Object.entries(counts)
        .filter(([key, value]) => isOutputCountKey(key) && Number.isFinite(value) && value > 0)
        .reduce((sum, [, value]) => sum + value, 0);
}

function isOutputCountKey(key: string): boolean {
    return !/(started|completed|duration|elapsed|wall|timestamp|time)/i.test(key);
}

function relationshipHintsFromNliResult(rawResult: unknown): GraphRebuildRelationshipHint[] {
    const judgments = arrayField(rawResult, 'judgments');
    return judgments
        .map((row): GraphRebuildRelationshipHint | null => {
            if (!row || typeof row !== 'object') return null;
            const record = row as Record<string, unknown>;
            const sourceId = stringField(record, 'sourceId', 'source_id');
            const targetId = stringField(record, 'targetId', 'target_id');
            const predictedLabel = stringField(record, 'predictedLabel', 'predicted_label');
            if (!sourceId || !targetId || !predictedLabel) return null;
            const hint: GraphRebuildRelationshipHint = {
                sourceId,
                targetId,
                relationType: stringField(record, 'edgeType', 'edge_type') || undefined,
                status: nliStatus(predictedLabel),
                confidence: numberField(record, 'confidence'),
                source: 'nli:modernbert',
                evidence: [
                    `judgment:${stringField(record, 'judgmentId', 'judgment_id') || 'unknown'}`,
                    `label:${predictedLabel}`,
                ],
            };
            return hint;
        })
        .filter((row): row is GraphRebuildRelationshipHint => !!row);
}

function nliStatus(label: string): GraphRebuildRelationshipHint['status'] {
    const normalized = label.trim().toLowerCase();
    if (normalized === 'entailment' || normalized === 'entails' || normalized === 'support') return 'accepted';
    if (normalized === 'contradiction' || normalized === 'contradicts') return 'rejected';
    return 'review';
}

function arrayField(value: unknown, key: string): unknown[] {
    return value && typeof value === 'object' && Array.isArray((value as Record<string, unknown>)[key])
        ? ((value as Record<string, unknown>)[key] as unknown[])
        : [];
}

function stringField(record: Record<string, unknown>, primary: string, fallback?: string): string {
    const value = record[primary] ?? (fallback ? record[fallback] : undefined);
    return typeof value === 'string' ? value : '';
}

function numberField(record: Record<string, unknown>, key: string): number {
    const value = record[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function assertStageCompleted(receipt: GraphIndexStageReceipt): void {
    if (receipt.status !== 'completed') {
        throw new Error(receipt.message || `${receipt.label} failed.`);
    }
}

function postProcessFingerprint(
    scope: GraphIndexRunScope,
    docs: ScopedDocument[],
    entities: Array<{ id: string; label: string; kind: string; aliases?: string[] }>,
    modelSelection: GraphIndexRunRequest['modelSelection'],
    embeddingStagePolicy?: GraphIndexRunRequest['embeddingStagePolicy'],
): string {
    const payload = JSON.stringify({
        scope: {
            kind: scope.kind,
            scopeId: scope.scopeId,
            noteIds: [...scope.noteIds].sort(),
        },
        docs: docs
            .map((doc) => ({
                id: doc.id,
                version: doc.version || 0,
                updatedAt: doc.updatedAt || 0,
                textHash: simpleHash(doc.plainText),
            }))
            .sort((left, right) => left.id.localeCompare(right.id)),
        entities: entities
            .map((entity) => ({
                id: entity.id,
                label: entity.label,
                kind: entity.kind,
                aliases: [...(entity.aliases || [])].sort(),
            }))
            .sort((left, right) => left.id.localeCompare(right.id)),
        modelSelection,
        embeddingStagePolicy: normalizedEmbeddingStagePolicy(embeddingStagePolicy),
    });
    return simpleHash(payload);
}

function normalizedEmbeddingStagePolicy(
    policy?: GraphIndexRunRequest['embeddingStagePolicy'],
): { enabledLanes: string[]; entityLinkerEnabled: boolean } {
    return {
        enabledLanes: [...(policy?.enabledLanes || [])].sort(),
        entityLinkerEnabled: policy?.entityLinkerEnabled !== false,
    };
}

function simpleHash(value: string): string {
    let out = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        out ^= value.charCodeAt(index);
        out = Math.imul(out, 16777619);
    }
    return (out >>> 0).toString(16).padStart(8, '0');
}

function emptyCounters(): GraphRebuildCounters {
    return {
        entities: 0,
        aliases: 0,
        candidates: 0,
        mentions: 0,
        acceptedAnchors: 0,
        chunks: 0,
        relationshipCandidates: 0,
        relationships: 0,
        acceptedRelationships: 0,
        reviewRelationships: 0,
        rejectedRelationships: 0,
        events: 0,
        episodes: 0,
        temporalEdges: 0,
        causalEdges: 0,
        memoryState: 0,
        embeddingTargets: 0,
        embeddingVectors: 0,
        projectionRefs: 0,
        nodes: 0,
        edges: 0,
        dropReasons: emptyDropReasons(),
    };
}

function emptyDropReasons(): GraphRebuildDropReasons {
    return {
        missingEntity: 0,
        invalidSpan: 0,
        duplicateAnchor: 0,
        singletonBucket: 0,
        missingChunk: 0,
    };
}
