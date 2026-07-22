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
import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { GraphGenerationLifetimeService } from '../services/graph-generation-lifetime.service';
import { GraphCanvasColdStartService } from '../services/graph-canvas-cold-start.service';
import type { GalaxySceneGenerationIndexReceipt } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-packet-persistence';
import { resolveGalaxyRendererAuthority } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/v3/galaxy-renderer-v3-authority';
import { buildGraphRebuildDeltaPostProcessPlan, deltaPostProcessPlanCounters, type GraphRebuildDeltaPostProcessPlan } from './graph-rebuild-delta-postprocess-plan';
import { buildGraphRebuildEdgeJudgmentPlan, edgeJudgmentPlanCounters } from './graph-rebuild-edge-type-judgment-plan';
import { embeddingProfileFromModelSelection } from './graph-rebuild-embedding-signatures';
import { GLINER_LINKER_MODEL_ID } from './graph-rebuild-entity-linking';
import { relationshipHintsFromNliResult } from './graph-nli-adjudication-contract';
import { buildGraphIndexLayerReceipts } from './graph-index-layer-receipts';
import {
    applyReviewAdjudicationCertificate,
    buildReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationRunCertificate,
} from './graph-review-adjudication-certificate';
import {
    graphGenerationSnapshotShell,
    GraphRebuildService,
    type NativeGraphRunPersistReceipt,
} from './graph-rebuild.service';
import { buildSiegelBackboneProjectionReceipt } from './graph-rebuild-siegel-backbone';
import { assertGraphSnapshotAuthority } from './graph-snapshot-authority';
import {
    buildGraphGenerationReceipt,
    withGraphGenerationArtifact,
    type GraphGenerationArtifactRef,
    type GraphGenerationReceiptV2,
} from './graph-generation-receipt';
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
    GraphSnapshotAuthorityContract,
    GraphBuildDurabilityMode,
    GraphRebuildCounters,
    GraphRebuildBuildTimings,
    GraphRebuildDropReasons,
    GraphRebuildEntityLinkCounters,
    GraphRebuildRelationshipHint,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import { GraphCoalescingAsyncQueue } from './graph-coalescing-async-queue';
import {
    attachGraphReceiptSpans,
    buildGraphReplayManifest,
    GRAPH_FORCE_V1_PATH_ID,
    GRAPH_FORCE_V2_PATH_ID,
    type GraphRebuildReplayManifest,
} from './graph-rebuild-replay-contract';

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
    'verifiedForceV2',
    'interactiveIdentityReuse',
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
    'forceV2AuthorityPersist',
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

type InteractiveRunReuseState = {
    identity: string;
    snapshot: GraphRebuildSnapshot;
    generationReceipt?: GraphGenerationReceiptV2;
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
    private readonly phoenix = inject(PhoenixBackendService);
    private readonly generationLifetime = inject(GraphGenerationLifetimeService, { optional: true });
    private readonly graphCanvasColdStart = inject(GraphCanvasColdStartService, { optional: true });
    private readonly runningState = signal(false);
    private readonly entityLinkerWarmState = signal(false);
    private readonly lastReceiptState = signal<GraphIndexRunReceipt | null>(null);
    private readonly lastSnapshotState = signal<GraphRebuildSnapshot | null>(null);
    private readonly lastGenerationReceiptState = signal<GraphGenerationReceiptV2 | null>(null);
    private receiptPersistenceQueue: Promise<void> = Promise.resolve();
    private readonly receiptPersistence = new GraphCoalescingAsyncQueue<string, ReceiptPersistenceJob>(
        deferReceiptPersistenceTurn,
        (job) => this.persistRunReceiptWithTiming(job.receipt, job.persistedReceipt, job.receiptStage),
    );
    private postCommitDiagnosticQueue: Promise<void> = Promise.resolve();
    private postCommitDiagnosticToken = 0;
    private cancelScheduledPostCommitDiagnostic: (() => void) | null = null;
    private readonly scopedDocumentBodyCache = new Map<string, { generation: string; note: Note }>();
    private readonly interactiveCapabilityCache = new Map<string, unknown>();
    private interactiveRunReuseState: InteractiveRunReuseState | null = null;
    private reusedRunReceiptSerial = 0;
    private generationArtifactQueue: Promise<void> = Promise.resolve();
    private generationArtifactPending = 0;

    readonly running = computed(() => this.runningState());
    readonly lastReceipt = computed(() => this.lastReceiptState());
    readonly lastSnapshot = computed(() => this.lastSnapshotState());
    readonly lastGenerationReceipt = computed(() => this.lastGenerationReceiptState());

    constructor() {
        this.graphCanvasColdStart?.onGenerationIndex((index) => this.acceptSceneGenerationIndex(index));
    }

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
        return readiness.find((model) => model.id === 'dynamicNer')?.status === 'ready';
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
        this.graphRebuild.assertBuildPolicyAuthorized?.(request.scope.scopeId, request.policy);
        if (request.policy === 'delta') {
            return this.reuseAuthoritativeInteractiveGraph(request);
        }
        const durabilityMode = request.durabilityMode || 'interactive';
        if (verifiedForceV2Required(request)) {
            return this.buildVerifiedForceV2(request);
        }
        const modelReadiness = this.modelReadiness(request);
        const graphCold = modelReadiness
            .filter((model) => model.id === 'dynamicNer')
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
        let rawNliAdjudicationResult: unknown;
        let postProcessFingerprintValue: string | undefined;
        let resumeContentCheckpoints: (() => void) | null = null;
        let acceptedNerOccurrences: EntityOccurrence[] = [];
        let interactiveIdentityValue: string | undefined;
        let replayManifest: GraphRebuildReplayManifest | undefined;
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
            if (durabilityMode === 'interactive') {
                interactiveIdentityValue = await interactiveRunIdentity(scope, docs, entities, request);
            }
            replayManifest = await this.replayManifest(
                scope, request, docs, entities, GRAPH_FORCE_V1_PATH_ID, 0,
            );

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
                const captureResult = (rawResult: unknown) => {
                    rawStageResult = rawResult;
                    if (capability === 'nliAdjudication') {
                        rawNliAdjudicationResult = rawResult;
                        relationshipHints = relationshipHintsFromNliResult(rawResult);
                    }
                };
                const capabilityCacheKey = durabilityMode === 'interactive'
                    ? `${fingerprint}:${capability}`
                    : '';
                const cached = capabilityCacheKey && this.interactiveCapabilityCache.has(capabilityCacheKey)
                    ? { value: this.interactiveCapabilityCache.get(capabilityCacheKey) }
                    : undefined;
                const receipt = await this.runCapabilityStage(capability, options, captureResult, cached);
                if (capabilityCacheKey && receipt.status === 'completed' && !cached) {
                    this.interactiveCapabilityCache.set(capabilityCacheKey, rawStageResult);
                    trimOldestMapEntries(this.interactiveCapabilityCache, 64);
                }
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
                    buildPolicy: request.policy,
                    interactiveInputIdentity: interactiveIdentityValue,
                    embeddingStagePolicy: request.embeddingStagePolicy,
                    candidateCount: nerStage.counters['candidates'] || 0,
                    replayManifest,
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
            const reviewCertificate = buildReviewAdjudicationRunCertificate({
                snapshot: completedSnapshot,
                rawResult: rawNliAdjudicationResult,
                source: 'graph_build',
                modelId: request.modelSelection.nliModelId,
                modelLabel: 'ModernBERT NLI',
            });
            applyReviewAdjudicationCertificate(completedSnapshot, reviewCertificate);
            appendReviewAdjudicationCertificateStage(stageReceipts, reviewCertificate);
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

            const projectionAuthority = assertGraphSnapshotAuthority(completedSnapshot);
            for (const projection of PROJECTION_CAPABILITIES) {
                projectionReceipts.push(snapshotOwnedProjectionReceipt(
                    projection.mode,
                    completedSnapshot,
                    projectionAuthority,
                ));
            }
            projectionReceipts.push(await buildSiegelBackboneProjectionReceipt(completedSnapshot, {
                nativeReceipt: this.graphRebuild.nativeSiegelReceipt?.(completedSnapshot.id),
                allowRuntimeNative: false,
            }));
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
                replayManifest,
                pathId: GRAPH_FORCE_V1_PATH_ID,
                fallbackCount: 0,
                message: `Build Graph produced ${completedSnapshot.counters.nodes} nodes, ${completedSnapshot.counters.edges} edges, and ${completedSnapshot.counters.embeddingTargets} targets.`,
            });
            const generationReceipt = durabilityMode === 'interactive'
                && completedSnapshot.contentManifest
                && completedSnapshot.interactiveRunAuthority
                ? await buildGraphGenerationReceipt({
                    snapshot: completedSnapshot,
                    runReceipt: receipt,
                    inputIdentity: interactiveIdentityValue!,
                })
                : null;
            if (generationReceipt) {
                receipt.generationReceiptId = generationReceipt.receiptId;
                receipt.generationDigestSha256 = generationReceipt.digestSha256;
                const forceAuthority = await this.graphRebuild.persistForceV2Authority(
                    completedSnapshot,
                    generationReceipt,
                );
                stageReceipts.push(instrumentationStage(
                    'forceV2AuthorityPersist',
                    'Verified FORCE Authority',
                    (forceAuthority.serializerMicros + forceAuthority.atomicPersistMicros) / 1_000,
                    {
                        rawBytes: forceAuthority.rawBytes,
                        compressedBytes: forceAuthority.compressedBytes,
                        encoded: forceAuthority.encoded ? 1 : 0,
                        serializerMicros: forceAuthority.serializerMicros,
                        atomicPersistMicros: forceAuthority.atomicPersistMicros,
                        serializerBudgetPassed: forceAuthority.serializerMicros <= 50_000 ? 1 : 0,
                        atomicPersistBudgetPassed: forceAuthority.atomicPersistMicros <= 120_000 ? 1 : 0,
                    },
                    'Compact snapshot authority persisted natively for fail-closed verified FORCE replay.',
                ));
                await this.generationLifetime?.accept(generationReceipt);
                this.lastGenerationReceiptState.set(generationReceipt);
            }
            await this.publishRunReceipt(receipt, completedSnapshot, true);
            if (durabilityMode === 'interactive') {
                appendInteractivePostCommitStage(stageReceipts, completedSnapshot);
                this.refreshLayerReceipts(receipt, completedSnapshot);
            }
            this.enqueueRunReceiptPersistence(receipt);
            if (durabilityMode === 'interactive') {
                this.interactiveRunReuseState = {
                    identity: interactiveIdentityValue!,
                    snapshot: completedSnapshot,
                    generationReceipt: generationReceipt || undefined,
                };
                if (generationReceipt) {
                    void this.persistGenerationReceipt(generationReceipt);
                    void this.prepareGenerationArtifacts(generationReceipt, completedSnapshot);
                }
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
                replayManifest,
                pathId: GRAPH_FORCE_V1_PATH_ID,
                fallbackCount: 0,
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

    async buildVerifiedForceV2(request: GraphIndexRunRequest): Promise<PipelineResult> {
        if (this.runningState()) throw new Error('Full Atlas Index is already running.');
        if (request.policy !== 'force' || (request.durabilityMode || 'interactive') !== 'interactive') {
            throw new Error('PHX_FORCE_V2_OPERATION_REQUIRED: v2 is an interactive FORCE-only contract.');
        }
        this.runningState.set(true);
        const runStarted = Date.now();
        const transportStarted = phoenixTransportAudit.snapshot();
        let replayManifest: GraphRebuildReplayManifest | undefined;
        try {
            if (!this.phoenix.currentRuntimeInfo()) {
                await this.phoenix.initRuntime(false);
            }
            const persistedReceipt = await this.graphRebuild.loadPersistedRunReceipt(request.scope.scopeId);
            const entities = smartGraphRegistry.getAllEntities().length
                ? smartGraphRegistry.getAllEntities()
                : request.entities;
            const dependencyIdentity = await graphDependencyIdentity(
                persistedReceipt?.replayManifest?.scope || request.scope,
                entities,
                request,
            );
            replayManifest = requireVerifiedForceReplay(request, persistedReceipt, dependencyIdentity);
            const nativeStarted = performance.now();
            const verified = await this.graphRebuild.verifyForceV2FromAuthority(
                replayManifest,
                persistedReceipt!.verifiedForceAuthority!,
            );
            const nativeMs = elapsedTimingMs(nativeStarted);
            const replay = replayManifestForVerifiedForceV2(
                replayManifest,
                this.phoenix.currentRuntimeInfo(),
                verified.result,
                {
                    documentBodyEntries: this.scopedDocumentBodyCache.size,
                    capabilityEntries: this.interactiveCapabilityCache.size,
                    residentInteractiveRun: this.interactiveRunReuseState !== null,
                    nativeRuntimeReady: this.phoenix.isReady,
                },
                {
                    receiptPersistencePending: this.receiptPersistence.pendingCount(),
                    postCommitDiagnosticScheduled: this.cancelScheduledPostCommitDiagnostic !== null,
                    postCommitDiagnosticToken: this.postCommitDiagnosticToken,
                    generationArtifactPending: this.generationArtifactPending,
                },
            );
            const durable = verified.snapshot.interactiveRunAuthority?.durable;
            if (!durable || !verified.snapshot.buildTimings) {
                throw new Error('PHX_FORCE_V2_AUTHORITY_PACKET_INVALID: native packet lacks durable timing authority.');
            }
            const snapshot: GraphRebuildSnapshot = {
                ...verified.snapshot,
                buildTimings: reusedGraphBuildTimings(verified.snapshot.buildTimings, {
                    ...durable,
                    changedSections: 0,
                    reusedSections: verified.result.verifiedSections.length,
                    encodedSections: 0,
                    compressedSections: 0,
                    rawBytesWritten: 0,
                    compressedBytesWritten: 0,
                }, nativeMs, 0),
            };
            const stageReceipts: GraphIndexStageReceipt[] = [instrumentationStage(
                'verifiedForceV2',
                'Verified FORCE v2',
                nativeMs,
                {
                    pathVerified: 1,
                    fallbackCount: verified.result.fallbackCount,
                    nativeCrossings: verified.result.nativeCrossings,
                    sourceBodyReads: verified.result.sourceBodyReads,
                    sourceUtf8Bytes: verified.result.sourceUtf8Bytes,
                    transportedSourceBytes: verified.result.transportedSourceBytes,
                    sourceVersionEnvelopeChanged: verified.result.sourceVersionEnvelopeChanged ? 1 : 0,
                    criticalResponseBytes: verified.result.criticalResponseBytes,
                    verifiedSections: verified.result.verifiedSections.length,
                    analysisKernelMicros: verified.result.analysisKernelMicros,
                },
                'Rust verified live source hashes, the immutable eight-section DAG, and compact snapshot authority.',
            )];
            appendVerifiedForceGraphTruthContractStage(stageReceipts, snapshot);
            const authority = snapshot.authorityContract!;
            const projectionReceipts = [...PROJECTION_CAPABILITIES.map((projection) =>
                snapshotOwnedProjectionReceipt(projection.mode, snapshot, authority),
            ), snapshotOwnedProjectionReceipt('siegel', snapshot, authority)];
            appendTransportTimingStage(stageReceipts, transportStarted, phoenixTransportAudit.snapshot());
            const completedAt = Date.now();
            const receipt = this.buildRunReceipt({
                idPrefix: `graph-atlas:verified-force-v2:${++this.reusedRunReceiptSerial}`,
                scope: replay.scope,
                policy: 'force',
                postProcessMode: 'full',
                durabilityMode: 'interactive',
                postProcessCacheHit: true,
                modelSelection: request.modelSelection,
                modelReadiness: this.modelReadiness({ ...request, scope: replay.scope }),
                startedAt: runStarted,
                completedAt,
                stageReceipts,
                projectionReceipts,
                snapshot,
                replayManifest: replay,
                pathId: GRAPH_FORCE_V2_PATH_ID,
                fallbackCount: 0,
                message: `Verified unchanged native graph ${snapshot.id}; ${verified.result.verifiedSections.length} durable sections reused.`,
            });
            receipt.generationReceiptId = persistedReceipt!.generationReceiptId;
            receipt.generationDigestSha256 = persistedReceipt!.generationDigestSha256;
            await this.publishRunReceipt(receipt, snapshot, true);
            appendInteractivePostCommitStage(stageReceipts, snapshot);
            this.refreshLayerReceipts(receipt, snapshot);
            this.enqueueRunReceiptPersistence(receipt);
            this.interactiveRunReuseState = {
                identity: snapshot.interactiveRunAuthority!.inputIdentity,
                snapshot,
            };
            return { receipt, snapshot };
        } catch (error) {
            const completedAt = Date.now();
            const failedReceipt = this.buildRunReceipt({
                idPrefix: 'graph-atlas:verified-force-v2:rejected',
                scope: request.scope,
                policy: 'force',
                postProcessMode: 'full',
                durabilityMode: 'interactive',
                modelSelection: request.modelSelection,
                modelReadiness: this.modelReadiness(request),
                startedAt: runStarted,
                completedAt,
                stageReceipts: [],
                projectionReceipts: [],
                snapshot: null,
                replayManifest,
                pathId: GRAPH_FORCE_V2_PATH_ID,
                fallbackCount: 0,
                status: 'failed',
                message: error instanceof Error ? error.message : String(error),
            });
            this.lastReceiptState.set(failedReceipt);
            throw error;
        } finally {
            this.runningState.set(false);
        }
    }

    private async reuseAuthoritativeInteractiveGraph(request: GraphIndexRunRequest): Promise<PipelineResult> {
        const durabilityMode = request.durabilityMode || 'interactive';
        if (durabilityMode !== 'interactive') {
            throw new Error('Delta Graph Build is an interactive authority-reuse operation. Use explicit Force Rebuild for reconstruction.');
        }

        this.runningState.set(true);
        const runStarted = Date.now();
        const transportStarted = phoenixTransportAudit.snapshot();
        try {
            const docs = await this.loadScopedDocuments(request.scope.noteIds);
            const scope = expandScopeNoteIds(request.scope, docs);
            const entities = smartGraphRegistry.getAllEntities().length
                ? smartGraphRegistry.getAllEntities()
                : request.entities;
            const fingerprint = postProcessFingerprint(
                scope,
                docs,
                entities,
                request.modelSelection,
                request.embeddingStagePolicy,
            );
            const identity = await interactiveRunIdentity(scope, docs, entities, request);
            return await this.reuseAuthoritativeInteractiveRun({
                identity,
                fingerprint,
                request,
                scope,
                runStarted,
                transportStarted,
                modelReadiness: this.modelReadiness({ ...request, scope }),
            });
        } catch (error) {
            const completedAt = Date.now();
            const failedReceipt = this.buildRunReceipt({
                idPrefix: 'graph-atlas:delta-rejected',
                scope: request.scope,
                policy: 'delta',
                postProcessMode: 'full',
                durabilityMode,
                modelSelection: request.modelSelection,
                modelReadiness: this.modelReadiness(request),
                startedAt: runStarted,
                completedAt,
                stageReceipts: [],
                projectionReceipts: [],
                snapshot: null,
                status: 'failed',
                message: error instanceof Error ? error.message : String(error),
            });
            this.lastReceiptState.set(failedReceipt);
            throw error;
        } finally {
            this.runningState.set(false);
        }
    }

    private async reuseAuthoritativeInteractiveRun(input: {
        identity: string;
        fingerprint: string;
        request: GraphIndexRunRequest;
        scope: GraphIndexRunScope;
        runStarted: number;
        transportStarted: PhoenixTransportAuditSnapshot;
        modelReadiness: GraphIndexModelReadiness[];
    }): Promise<PipelineResult> {
        const state = this.interactiveRunReuseState;
        const residentGeneration = state
            && state.identity === input.identity
            && state.generationReceipt?.inputIdentity === input.identity
            ? state.generationReceipt
            : null;
        const persistedGeneration = residentGeneration
            || await this.graphRebuild.loadPersistedGenerationReceipt(input.scope.scopeId);
        if (!persistedGeneration) {
            throw new Error(
                'Delta cannot reconstruct: persisted graph predates the compact generation fast lane. '
                + 'Automatic cold fallback is disabled; run one explicit Force Rebuild to migrate it.',
            );
        }
        if (persistedGeneration.inputIdentity !== input.identity) {
            throw new Error(
                'Graph inputs changed and no sealed graph matches them. '
                + 'Delta cannot reconstruct; use explicit Force Rebuild.',
            );
        }
        const residentSnapshot = state
            && state.identity === input.identity
            && this.lastSnapshotState()?.id === state.snapshot.id
            && this.lastSnapshotState()?.authorityContract?.contentHash
                === state.snapshot.authorityContract?.contentHash
            ? state.snapshot
            : null;
        const currentSnapshot = this.graphRebuild.snapshot?.() || null;
        const restoredSnapshot = !residentSnapshot
            ? currentSnapshot?.scopeId === input.scope.scopeId
                ? currentSnapshot
                : await this.graphRebuild.loadPersistedSnapshotShell(input.scope.scopeId)
            : null;
        const snapshot = residentSnapshot || restoredSnapshot;
        if (!snapshot) {
            throw new Error(
                'No authoritative sealed graph exists for this scope. '
                + 'Delta cannot reconstruct; use explicit Force Rebuild.',
            );
        }
        assertGenerationSnapshotIdentity(persistedGeneration, snapshot);

        const reuseStarted = performance.now();
        const authority = persistedGeneration.authority;
        const persistStarted = performance.now();
        const durable = residentSnapshot
            ? await this.graphRebuild.persistResidentNativeGraphRun?.(snapshot)
            : await this.graphRebuild.restorePersistedNativeGraphRun?.(snapshot, input.identity);
        if (!durable) {
            throw new Error(
                'Authoritative graph fast lane is unavailable. Automatic cold fallback is disabled; '
                + 'use explicit Force Rebuild to replace the durable run.',
            );
        }
        const persistMs = elapsedTimingMs(persistStarted);
        const reusedSnapshot: GraphRebuildSnapshot = {
            ...snapshot,
            buildTimings: reusedGraphBuildTimings(
                snapshot.buildTimings,
                durable,
                elapsedTimingMs(reuseStarted),
                persistMs,
            ),
        };

        const stageReceipts: GraphIndexStageReceipt[] = [instrumentationStage(
            'interactiveIdentityReuse',
            'Interactive Identity Reuse',
            elapsedTimingMs(reuseStarted),
            {
                identityMatched: 1,
                authorityVerified: 1,
                nativeDurableReceipt: 1,
                changedSections: durable.changedSections,
                reusedSections: durable.reusedSections,
                encodedSections: durable.encodedSections,
                compressedSections: durable.compressedSections,
                rawBytesWritten: durable.rawBytesWritten,
                compressedBytesWritten: durable.compressedBytesWritten,
            },
            'Complete semantic input identity matched the current sealed snapshot and resident native run.',
        )];
        const projectionReceipts = PROJECTION_CAPABILITIES.map((projection) =>
            snapshotOwnedProjectionReceipt(projection.mode, reusedSnapshot, authority),
        );
        projectionReceipts.push(graphGenerationSnapshotIsCompact(reusedSnapshot)
            ? snapshotOwnedProjectionReceipt('siegel', reusedSnapshot, authority)
            : await buildSiegelBackboneProjectionReceipt(reusedSnapshot, {
                nativeReceipt: this.graphRebuild.nativeSiegelReceipt?.(reusedSnapshot.id),
                allowRuntimeNative: false,
            }));
        appendTransportTimingStage(stageReceipts, input.transportStarted, phoenixTransportAudit.snapshot());

        const completedAt = Date.now();
        const receipt = this.buildRunReceipt({
            idPrefix: `graph-atlas:identity-reuse:${++this.reusedRunReceiptSerial}`,
            scope: input.scope,
            policy: input.request.policy,
            postProcessMode: 'full',
            durabilityMode: 'interactive',
            postProcessFingerprint: input.fingerprint,
            postProcessCacheHit: true,
            modelSelection: input.request.modelSelection,
            modelReadiness: input.modelReadiness,
            startedAt: input.runStarted,
            completedAt,
            stageReceipts,
            projectionReceipts,
            snapshot: reusedSnapshot,
            message: `Reused sealed graph ${reusedSnapshot.id}; semantic input identity is unchanged.`,
        });
        receipt.generationReceiptId = persistedGeneration.receiptId;
        receipt.generationDigestSha256 = persistedGeneration.digestSha256;
        await this.publishRunReceipt(receipt, reusedSnapshot, true);
        appendInteractivePostCommitStage(stageReceipts, reusedSnapshot);
        this.refreshLayerReceipts(receipt, reusedSnapshot);
        this.enqueueRunReceiptPersistence(receipt);
        this.interactiveRunReuseState = {
            identity: input.identity,
            snapshot: reusedSnapshot,
            generationReceipt: persistedGeneration,
        };
        return { receipt, snapshot: reusedSnapshot };
    }

    private async persistGenerationReceipt(receipt: GraphGenerationReceiptV2): Promise<void> {
        try {
            await this.graphRebuild.persistGenerationReceipt(receipt);
        } catch (error) {
            console.warn('[GraphRebuildPipeline] Generation receipt persistence failed', error);
        }
    }

    private async prepareGenerationArtifacts(
        receipt: GraphGenerationReceiptV2,
        snapshot: GraphRebuildSnapshot,
    ): Promise<void> {
        try {
            const assertedQuery = await this.graphRebuild.prepareAssertedQueryArtifact(snapshot);
            await this.queueGenerationArtifact(receipt.receiptId, 'assertedQuery', assertedQuery);
        } catch (error) {
            console.warn('[GraphRebuildPipeline] Asserted query artifact preparation failed closed', error);
        }
        if (resolveGalaxyRendererAuthority() === 'v3-visible') {
            try {
                await this.graphCanvasColdStart?.preparePersistedManifold(snapshot);
            } catch (error) {
                console.warn('[GraphRebuildPipeline] Packed V3 generation preparation failed closed', error);
            }
        }
        const sceneIndex = this.graphCanvasColdStart?.generationIndex();
        if (sceneIndex) this.acceptSceneGenerationIndex(sceneIndex);
    }

    private acceptSceneGenerationIndex(index: GalaxySceneGenerationIndexReceipt): void {
        const receipt = this.lastGenerationReceiptState();
        if (!receipt
            || index.scopeId !== receipt.scopeId
            || index.snapshotId !== receipt.snapshotId
            || index.generationId !== receipt.authority.contentHash) return;
        void this.queueGenerationArtifact(receipt.receiptId, 'sceneIndex', {
            schemaVersion: 'phoenix-graph-generation-artifact-ref/v1',
            kind: 'scene-index',
            status: 'ready',
            id: `scene-index:${index.snapshotId}:${index.digestSha256}`,
            digest: index.digestSha256,
            schema: index.schemaVersion,
            byteLength: index.totalBytes,
        });
    }

    private queueGenerationArtifact(
        receiptId: string,
        key: 'assertedQuery' | 'sceneIndex',
        artifact: GraphGenerationArtifactRef,
    ): Promise<void> {
        this.generationArtifactPending += 1;
        const queued = this.generationArtifactQueue.then(async () => {
            try {
                const current = this.lastGenerationReceiptState();
                if (!current || current.receiptId !== receiptId) return;
                const updated = await withGraphGenerationArtifact(current, key, artifact);
                this.lastGenerationReceiptState.set(updated);
                if (this.interactiveRunReuseState?.generationReceipt?.receiptId === receiptId) {
                    this.interactiveRunReuseState = { ...this.interactiveRunReuseState, generationReceipt: updated };
                }
                await this.generationLifetime?.accept(updated);
                await this.persistGenerationReceipt(updated);
                if (updated.releaseAuthorized) await this.releaseCurrentGeneration(updated);
            } finally {
                this.generationArtifactPending = Math.max(0, this.generationArtifactPending - 1);
            }
        });
        this.generationArtifactQueue = queued.catch((error) => {
            console.warn('[GraphRebuildPipeline] Generation artifact publication failed closed', error);
        });
        return queued;
    }

    private async releaseCurrentGeneration(receipt: GraphGenerationReceiptV2): Promise<void> {
        const lifetime = this.generationLifetime;
        const snapshot = this.lastSnapshotState();
        if (resolveGalaxyRendererAuthority() !== 'v3-visible'
            || !lifetime || !snapshot || snapshot.generationReceiptId === receipt.receiptId) return;
        this.cancelScheduledPostCommitDiagnostic?.();
        this.cancelScheduledPostCommitDiagnostic = null;
        this.postCommitDiagnosticToken += 1;
        await this.postCommitDiagnosticQueue;
        const current = this.lastSnapshotState();
        if (!current
            || current.id !== receipt.snapshotId
            || current.authorityContract?.contentHash !== receipt.authority.contentHash) return;
        const shell = graphGenerationSnapshotShell(current, receipt);
        await lifetime.releaseRichGeneration(receipt, shell, () => {
            if (!this.graphRebuild.releaseRichSnapshot(receipt, shell)) {
                throw new Error(`Graph generation ${receipt.receiptId} lost its current snapshot root.`);
            }
            this.lastSnapshotState.set(shell);
            if (this.interactiveRunReuseState?.generationReceipt?.receiptId === receipt.receiptId) {
                this.interactiveRunReuseState = {
                    ...this.interactiveRunReuseState,
                    snapshot: shell,
                    generationReceipt: receipt,
                };
            }
        });
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
        replayManifest?: GraphRebuildReplayManifest;
        pathId?: string;
        fallbackCount?: number;
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
            replayManifest: input.replayManifest,
            pathId: input.pathId,
            fallbackCount: input.fallbackCount,
            verifiedForceAuthority: input.snapshot?.interactiveRunAuthority?.durable
                && input.snapshot.authorityContract?.contentHash
                ? {
                    schemaVersion: 'phoenix-verified-force-authority-ref/v1',
                    snapshotId: input.snapshot.id,
                    authorityHash: input.snapshot.authorityContract.contentHash,
                    manifestId: input.snapshot.interactiveRunAuthority.durable.manifestId,
                    runHandle: input.snapshot.interactiveRunAuthority.durable.runHandle,
                }
                : undefined,
        };
        Object.assign(receipt, attachGraphReceiptSpans(receipt.id, receipt.stageReceipts));
        this.refreshLayerReceipts(receipt, input.snapshot);
        return receipt;
    }

    private replayManifest(
        scope: GraphIndexRunScope,
        request: GraphIndexRunRequest,
        documents: ScopedDocument[],
        entities: GraphIndexRunRequest['entities'],
        pathId: string,
        fallbackCount: number,
    ): Promise<GraphRebuildReplayManifest> {
        return graphDependencyIdentity(scope, entities, request).then((dependencyIdentity) => buildGraphReplayManifest({
            scope,
            action: request.policy === 'force' ? 'force' : 'delta',
            documents: documents.map((document) => ({
                noteId: document.id,
                title: document.title,
                text: document.plainText,
                version: document.version,
                updatedAt: document.updatedAt,
            })),
            model: request.modelSelection,
            dependencyIdentity,
            runtime: this.phoenix.currentRuntimeInfo(),
            cache: {
                documentBodyEntries: this.scopedDocumentBodyCache.size,
                capabilityEntries: this.interactiveCapabilityCache.size,
                residentInteractiveRun: this.interactiveRunReuseState !== null,
                nativeRuntimeReady: this.phoenix.isReady,
            },
            queues: {
                receiptPersistencePending: this.receiptPersistence.pendingCount(),
                postCommitDiagnosticScheduled: this.cancelScheduledPostCommitDiagnostic !== null,
                postCommitDiagnosticToken: this.postCommitDiagnosticToken,
                generationArtifactPending: this.generationArtifactPending,
            },
            pathId,
            fallbackCount,
        }));
    }

    private refreshLayerReceipts(receipt: GraphIndexRunReceipt, snapshot: GraphRebuildSnapshot | null): void {
        Object.assign(receipt, attachGraphReceiptSpans(receipt.id, receipt.stageReceipts));
        receipt.layerReceipts = buildGraphIndexLayerReceipts({ receipt, snapshot });
    }

    private async publishRunReceipt(
        receipt: GraphIndexRunReceipt,
        snapshot: GraphRebuildSnapshot | null,
        authorityVerified = false,
    ): Promise<void> {
        if (snapshot) {
            if (authorityVerified) assertRunReceiptParityWithContract(receipt, snapshot);
            else assertRunReceiptParity(receipt, snapshot);
        }
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
                buildPolicy: 'force',
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
        this.receiptPersistenceQueue = this.receiptPersistence.enqueue(
            receiptPersistenceKey(receipt),
            { receipt, persistedReceipt, receiptStage },
        );
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
        const scanDocs = docs.filter((doc) => doc.plainText.trim());
        const scanRequests = scanDocs.map((doc) => ({
                noteId: doc.id,
                noteTitle: doc.title || 'Untitled Note',
                plainText: doc.plainText,
        }));
        if (!scanRequests.length) {
            return {
                counts: { documents: docs.length, candidates, acceptedAnchors, dropped },
                acceptedOccurrences,
            };
        }
        const batchResults = await this.ner.scanDynamicBatch(scanRequests);
        for (let index = 0; index < scanRequests.length; index += 1) {
            const request = scanRequests[index];
            const doc = scanDocs[index];
            await this.ner.applyDynamicScanResult(request, batchResults[index] || []);
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
        cached?: { value: unknown },
    ): Promise<GraphIndexStageReceipt> {
        return this.runStage(capability, capabilityLabel(capability), async () => {
            const rawResult = cached
                ? cached.value
                : (await this.atlasRuntime.runCapability(capability, { ...options, skipModelWarm: true })).rawResult;
            onRawResult?.(rawResult);
            const counters = numberCounts(rawResult);
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
            const headers = await db.notes.bulkGet(noteIds);
            const headerById = new Map(headers.filter((note): note is Note => !!note).map((note) => [note.id, note]));
            const resolved = new Map<string, Note>();
            const missing: string[] = [];
            for (let index = 0; index < noteIds.length; index += 1) {
                const noteId = noteIds[index];
                const header = headers[index];
                const generation = noteBodyGeneration(header);
                const cached = generation ? this.scopedDocumentBodyCache.get(noteId) : undefined;
                if (header && cached?.generation === generation) {
                    resolved.set(noteId, { ...cached.note, ...header,
                        content: cached.note.content, markdownContent: cached.note.markdownContent });
                } else {
                    missing.push(noteId);
                }
            }
            if (missing.length) {
                const hydrated = await ops.getNotesByIds(missing) as unknown as Note[];
                for (const note of hydrated) {
                    const header = headerById.get(note.id);
                    const merged = header
                        ? { ...note, ...header, content: note.content, markdownContent: note.markdownContent }
                        : note;
                    resolved.set(note.id, merged);
                    const generation = noteBodyGeneration(merged);
                    if (generation) this.scopedDocumentBodyCache.set(note.id, { generation, note: merged });
                }
            }
            return noteIds.map((noteId) => resolved.get(noteId)).filter((note): note is Note => !!note);
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
            embeddingDimension: embeddingDimensionFromLabel(request.modelSelection.embeddingDimensionLabel),
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

function noteBodyGeneration(note: Pick<Note, 'version' | 'updatedAt'> | null | undefined): string {
    if (!note || !Number.isFinite(note.updatedAt) || note.updatedAt <= 0) return '';
    return `${note.version || 0}:${note.updatedAt}`;
}

function trimOldestMapEntries<Key, Value>(map: Map<Key, Value>, limit: number): void {
    while (map.size > limit) {
        const oldest = map.keys().next();
        if (oldest.done) return;
        map.delete(oldest.value);
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
            documentSemanticCacheHit: timings.documentSemanticCacheHit || 0,
            documentSemanticDocumentsBuilt: timings.documentSemanticDocumentsBuilt || 0,
            documentSemanticDocumentsReused: timings.documentSemanticDocumentsReused || 0,
            documentSemanticRawBytesWritten: timings.documentSemanticRawBytesWritten || 0,
            documentSemanticCompressedBytesWritten: timings.documentSemanticCompressedBytesWritten || 0,
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
            (timings.nativeSnapshotAnalysisMs || 0)
            + (timings.nativeCompilerMs || 0)
            + timings.occurrenceRecoverMs
            + timings.snapshotBuildMs
            + (timings.authoritySealMs || 0)
            + (timings.authorityAssertMs || 0),
        ),
        {
            occurrenceRecoverMs: timings.occurrenceRecoverMs,
            snapshotBuildMs: timings.snapshotBuildMs,
            nativeSnapshotAnalysisMs: timings.nativeSnapshotAnalysisMs || 0,
            nativeAnalysisRustMs: Math.round((timings.nativeSnapshotAnalysisRustMicros || 0) / 1_000),
            nativeBridgeRustMs: Math.round((timings.nativeChunkSemanticBridgeRustMicros || 0) / 1_000),
            nativeContinuityRustMs: Math.round((timings.nativeStoryContinuityRustMicros || 0) / 1_000),
            nativeGovernanceRustMs: Math.round((timings.nativeMemoryGovernanceRustMicros || 0) / 1_000),
            nativeRetrievalRustMs: Math.round(
                (timings.nativeMemoryGovernanceRetrievalExperimentRustMicros || 0) / 1_000,
            ),
            nativeVerdictRustMs: Math.round((timings.nativePromotionVerdictRustMicros || 0) / 1_000),
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
    const offenders = transportDeltaOffenders(before, after, 12);
    for (const offender of offenders) {
        const prefix = `transportOffender${offender.rank}`;
        counters[`${prefix}Calls`] = offender.count;
        counters[`${prefix}TotalMs`] = offender.totalMs;
        counters[`${prefix}MaxMs`] = offender.maxMs;
        counters[`${prefix}RequestBytes`] = offender.requestBytes;
        counters[`${prefix}ResponseBytes`] = offender.responseBytes;
        counters[`${prefix}RequestBytesUnavailableCalls`] = offender.requestBytesUnavailableCalls;
        counters[`${prefix}ResponseBytesUnavailableCalls`] = offender.responseBytesUnavailableCalls;
        counters[`${prefix}Errors`] = offender.errors;
    }
    stageReceipts.push(instrumentationStage(
        'transportOps',
        'Transport Ops',
        counters['transportTotalMs'],
        counters,
        transportOffenderMessage(offenders),
    ));
}

type TransportAggregate = PhoenixTransportAuditSnapshot['calls'][number];

interface TransportOffender {
    rank: number;
    name: string;
    kind: string;
    count: number;
    totalMs: number;
    maxMs: number;
    requestBytes: number;
    responseBytes: number;
    requestBytesUnavailableCalls: number;
    responseBytesUnavailableCalls: number;
    errors: number;
}

function appendReviewAdjudicationCertificateStage(
    stageReceipts: GraphIndexStageReceipt[],
    certificate: GraphReviewAdjudicationRunCertificate,
): void {
    const queue = certificate.queue;
    stageReceipts.push(instrumentationStage(
        'reviewAdjudicationCertificate',
        'Review Adjudication Certificate',
        certificate.stageSummaries.reduce((sum, stage) => sum + stage.durationMs, 0),
        {
            ledgerRows: queue.ledgerRows,
            manualDecisionRows: queue.manualDecisionRows,
            nliPairRows: queue.nliPairRows,
            nliExcludedRows: queue.nliExcludedRows,
            duplicatePairs: queue.duplicatePairs,
            judgedRows: queue.judgedRows,
            appliedRows: queue.appliedRows,
            topologyWrites: queue.topologyWrites,
            inputContractPassed: certificate.proof.inputContract.status === 'passed' ? 1 : 0,
            noTopologyWrites: certificate.proof.noTopologyWrites.status === 'passed' ? 1 : 0,
        },
        `${queue.manualDecisionRows.toLocaleString()} manual decisions / ${queue.nliPairRows.toLocaleString()} NLI pairs / ${queue.ledgerRows.toLocaleString()} ledger rows`,
    ));
}

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
        transportRequestBytesMeasuredCalls: 0,
        transportRequestBytesUnavailableCalls: 0,
        transportResponseBytesMeasuredCalls: 0,
        transportResponseBytesUnavailableCalls: 0,
        transportEncodeMs: 0,
        transportDecodeMs: 0,
        transportEncodeTimingUnavailableCalls: 0,
        transportDecodeTimingUnavailableCalls: 0,
        jsonRpcCalls: 0,
        jsonRpcRequestBytes: 0,
        jsonRpcResponseBytes: 0,
        typedRpcCalls: 0,
        typedRpcRequestBytes: 0,
        typedRpcResponseBytes: 0,
        typedRpcRequestBytesUnavailableCalls: 0,
        typedRpcResponseBytesUnavailableCalls: 0,
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
        const requestBytesMeasuredCalls = Math.max(0,
            call.requestBytesMeasuredCalls - (previous?.requestBytesMeasuredCalls || 0));
        const requestBytesUnavailableCalls = Math.max(0,
            call.requestBytesUnavailableCalls - (previous?.requestBytesUnavailableCalls || 0));
        const responseBytesMeasuredCalls = Math.max(0,
            call.responseBytesMeasuredCalls - (previous?.responseBytesMeasuredCalls || 0));
        const responseBytesUnavailableCalls = Math.max(0,
            call.responseBytesUnavailableCalls - (previous?.responseBytesUnavailableCalls || 0));
        const encodeMs = Math.max(0, call.totalEncodeMs - (previous?.totalEncodeMs || 0));
        const decodeMs = Math.max(0, call.totalDecodeMs - (previous?.totalDecodeMs || 0));
        const encodeTimingUnavailableCalls = Math.max(0,
            call.encodeTimingUnavailableCalls - (previous?.encodeTimingUnavailableCalls || 0));
        const decodeTimingUnavailableCalls = Math.max(0,
            call.decodeTimingUnavailableCalls - (previous?.decodeTimingUnavailableCalls || 0));
        const errors = Math.max(0, call.errors - (previous?.errors || 0));
        const localMaxMs = call.maxMs > (previous?.maxMs || 0)
            ? call.maxMs
            : (count ? totalMs / count : 0);
        counters['transportCalls'] += count;
        counters['transportErrors'] += errors;
        counters['transportTotalMs'] += totalMs;
        counters['transportRequestBytes'] += requestBytes;
        counters['transportResponseBytes'] += responseBytes;
        counters['transportRequestBytesMeasuredCalls'] += requestBytesMeasuredCalls;
        counters['transportRequestBytesUnavailableCalls'] += requestBytesUnavailableCalls;
        counters['transportResponseBytesMeasuredCalls'] += responseBytesMeasuredCalls;
        counters['transportResponseBytesUnavailableCalls'] += responseBytesUnavailableCalls;
        counters['transportEncodeMs'] += encodeMs;
        counters['transportDecodeMs'] += decodeMs;
        counters['transportEncodeTimingUnavailableCalls'] += encodeTimingUnavailableCalls;
        counters['transportDecodeTimingUnavailableCalls'] += decodeTimingUnavailableCalls;
        counters['transportMaxMs'] = Math.max(counters['transportMaxMs'], localMaxMs);
        if (call.kind === 'taurpc-json') {
            addTransportFamilyCounters(counters, 'jsonRpc', count, totalMs, requestBytes, responseBytes);
        }
        if (call.kind === 'taurpc-typed') {
            addTransportFamilyCounters(counters, 'typedRpc', count, totalMs, requestBytes, responseBytes);
            counters['typedRpcRequestBytesUnavailableCalls'] += requestBytesUnavailableCalls;
            counters['typedRpcResponseBytesUnavailableCalls'] += responseBytesUnavailableCalls;
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

function transportDeltaOffenders(
    before: PhoenixTransportAuditSnapshot,
    after: PhoenixTransportAuditSnapshot,
    limit: number,
): TransportOffender[] {
    const beforeByKey = new Map(before.calls.map((call) => [transportAggregateKey(call), call]));
    const offenders: TransportOffender[] = [];
    for (const call of after.calls) {
        const previous = beforeByKey.get(transportAggregateKey(call));
        const count = Math.max(0, call.count - (previous?.count || 0));
        if (!count) continue;
        const totalMs = Math.round(Math.max(0, call.totalMs - (previous?.totalMs || 0)));
        if (totalMs <= 0) continue;
        offenders.push({
            rank: 0,
            name: call.name || 'unknown',
            kind: call.kind || 'unknown',
            count,
            totalMs,
            maxMs: Math.round(call.maxMs > (previous?.maxMs || 0) ? call.maxMs : totalMs / count),
            requestBytes: Math.round(Math.max(0, call.totalRequestBytes - (previous?.totalRequestBytes || 0))),
            responseBytes: Math.round(Math.max(0, call.totalResponseBytes - (previous?.totalResponseBytes || 0))),
            requestBytesUnavailableCalls: Math.max(0,
                call.requestBytesUnavailableCalls - (previous?.requestBytesUnavailableCalls || 0)),
            responseBytesUnavailableCalls: Math.max(0,
                call.responseBytesUnavailableCalls - (previous?.responseBytesUnavailableCalls || 0)),
            errors: Math.max(0, call.errors - (previous?.errors || 0)),
        });
    }
    return offenders
        .sort((left, right) =>
            right.totalMs - left.totalMs
            || (right.requestBytes + right.responseBytes) - (left.requestBytes + left.responseBytes)
        )
        .slice(0, limit)
        .map((row, index) => ({ ...row, rank: index + 1 }));
}

function transportOffenderMessage(offenders: TransportOffender[]): string {
    if (!offenders.length) return 'TauRPC transport calls and payload volume during this graph run';
    return `TauRPC transport offenders: ${offenders
        .map((row) => `${row.rank}. ${compactTransportName(row.name)} ${row.totalMs} ms / ${row.count} call${row.count === 1 ? '' : 's'}`)
        .join('; ')}`;
}

function compactTransportName(name: string): string {
    return name.replace(/^phoenix\./, '').replace(/^store_command:/, 'store:');
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

function embeddingDimensionFromLabel(label: string | undefined): number {
    const match = String(label || '').match(/(\d+)/);
    return match ? Number(match[1]) : 0;
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
    appendGraphTruthContractReceipt(stageReceipts, contract, 0);
}

function appendVerifiedForceGraphTruthContractStage(
    stageReceipts: GraphIndexStageReceipt[],
    snapshot: GraphRebuildSnapshot,
): void {
    const contract = snapshot.authorityContract;
    if (!contract) throw new Error(`PHX_FORCE_V2_COMPACT_AUTHORITY_INVALID: authority missing for ${snapshot.id}`);
    appendGraphTruthContractReceipt(stageReceipts, contract, 1);
}

function appendGraphTruthContractReceipt(
    stageReceipts: GraphIndexStageReceipt[],
    contract: GraphSnapshotAuthorityContract,
    compactNativeShell: number,
): void {
    const counts = contract.counts;
    stageReceipts.push(instrumentationStage(
        'snapshotAuthorityContract',
        'Snapshot Authority Contract',
        0,
        {
            authorityParity: 1,
            compactNativeShell,
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
        case 'modelRelease': return 'NLI Model Release';
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
    verifiedContract?: GraphSnapshotAuthorityContract,
): GraphIndexProjectionReceipt {
    const now = Date.now();
    const targetCount = snapshot?.counters.embeddingTargets || 0;
    const contract = verifiedContract || (snapshot ? assertGraphSnapshotAuthority(snapshot) : undefined);
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
    assertRunReceiptParityAgainstContract(receipt, snapshot, contract);
}

export function graphGenerationSnapshotIsCompact(snapshot: GraphRebuildSnapshot): boolean {
    return Boolean(snapshot.generationReceiptId && snapshot.generationDigestSha256);
}

export function assertGenerationSnapshotIdentity(
    receipt: GraphGenerationReceiptV2,
    snapshot: GraphRebuildSnapshot,
): void {
    if (snapshot.id !== receipt.snapshotId
        || snapshot.scopeId !== receipt.scopeId
        || snapshot.authorityContract?.contentHash !== receipt.authority.contentHash
        || snapshot.interactiveRunAuthority?.inputIdentity !== receipt.inputIdentity) {
        throw new Error('Compact graph generation shell authority drift.');
    }
    if (graphGenerationSnapshotIsCompact(snapshot)
        && (snapshot.generationReceiptId !== receipt.receiptId
            || snapshot.generationDigestSha256 !== receipt.digestSha256)) {
        throw new Error('Compact graph generation shell receipt drift.');
    }
}

function assertRunReceiptParityWithContract(
    receipt: GraphIndexRunReceipt,
    snapshot: GraphRebuildSnapshot,
): void {
    const contract = snapshot.authorityContract;
    if (!contract) throw new Error(`Graph snapshot authority contract missing for ${snapshot.id}`);
    assertRunReceiptParityAgainstContract(receipt, snapshot, contract);
}

function assertRunReceiptParityAgainstContract(
    receipt: GraphIndexRunReceipt,
    snapshot: GraphRebuildSnapshot,
    contract: GraphSnapshotAuthorityContract,
): void {
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
    const reuseStage = receipt.stageReceipts.find((stage) => stage.id === 'interactiveIdentityReuse');
    if ((!authorityStage || authorityStage.status !== 'completed' || authorityStage.counters['authorityParity'] !== 1)
        && (!reuseStage || reuseStage.status !== 'completed' || reuseStage.counters['authorityVerified'] !== 1)) {
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
            packetObjects: snapshot.atlasPacket?.objects.length
                || snapshot.authorityContract?.counts.packetObjects || 0,
            packetTargets: snapshot.atlasPacket?.manifoldTargets.length
                || snapshot.authorityContract?.counts.packetTargets || 0,
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
        spanId: stage.spanId,
        parentSpanId: stage.parentSpanId,
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

async function interactiveRunIdentity(
    scope: GraphIndexRunScope,
    docs: ScopedDocument[],
    entities: GraphIndexRunRequest['entities'],
    request: GraphIndexRunRequest,
): Promise<string> {
    const documentRows = await Promise.all(docs.map(async (doc) => ({
        id: doc.id,
        textSha256: await sha256Text(doc.plainText),
    })));
    const payload = canonicalJson({
        schemaVersion: 'phoenix-interactive-graph-input-identity/v1',
        scope: {
            kind: scope.kind,
            scopeId: scope.scopeId,
            noteIds: [...scope.noteIds].sort(),
        },
        documents: documentRows.sort((left, right) => left.id.localeCompare(right.id)),
        entities: entities
            .map((entity) => ({
                id: entity.id,
                label: entity.label,
                aliases: [...(entity.aliases || [])].sort(),
                kind: entity.kind,
                firstNote: entity.firstNote || null,
            }))
            .sort((left, right) => left.id.localeCompare(right.id)),
        modelSelection: request.modelSelection,
        embeddingStagePolicy: normalizedEmbeddingStagePolicy(request.embeddingStagePolicy),
        calendarRegistrySnapshot: stableCalendarRegistryIdentity(request.calendarRegistrySnapshot),
        postProcessMode: 'full',
    });
    return sha256Text(payload);
}

function stableCalendarRegistryIdentity(
    snapshot: GraphIndexRunRequest['calendarRegistrySnapshot'],
): unknown {
    if (!snapshot) return null;
    const { id: _volatileId, builtAt: _volatileBuiltAt, ...stable } = snapshot;
    return stable;
}

function requireVerifiedForceReplay(
    request: GraphIndexRunRequest,
    receipt: GraphIndexRunReceipt | null,
    dependencyIdentity: string,
): GraphRebuildReplayManifest {
    const replay = receipt?.replayManifest;
    if (!receipt || !replay) {
        throw new Error('PHX_FORCE_V2_REPLAY_MISSING: no exact persisted replay manifest exists for this scope.');
    }
    const native = receipt.verifiedForceAuthority;
    if (!native || native.schemaVersion !== 'phoenix-verified-force-authority-ref/v1'
        || !native.manifestId || !native.runHandle) {
        throw new Error('PHX_FORCE_V2_DURABLE_AUTHORITY_REQUIRED: no sealed native run reference exists.');
    }
    if (replay.action !== 'force' || replay.sourceMode !== 'scoped-note-store'
        || replay.scope.scopeId !== request.scope.scopeId
        || receipt.scope.scopeId !== request.scope.scopeId
        || receipt.snapshotId !== native.snapshotId
        || receipt.authorityContract?.contentHash !== native.authorityHash) {
        throw new Error('PHX_FORCE_V2_REPLAY_MISMATCH: persisted replay, receipt, and sealed native authority differ.');
    }
    const requestedIds = [...request.scope.noteIds].sort();
    const replayIds = replay.documents.map((row) => row.noteId).sort();
    if (requestedIds.length && JSON.stringify(requestedIds) !== JSON.stringify(replayIds)) {
        throw new Error('PHX_FORCE_V2_NOTE_SET_CHANGED: requested note membership differs from the frozen replay.');
    }
    if (canonicalJson(request.modelSelection) !== canonicalJson(replay.model)) {
        throw new Error('PHX_FORCE_V2_MODEL_CHANGED: requested model selection differs from the frozen replay.');
    }
    if (replay.dependencyIdentity !== dependencyIdentity) {
        throw new Error(
            `PHX_FORCE_V2_DEPENDENCY_CHANGED: ${dependencyIdentity} != frozen ${replay.dependencyIdentity}.`,
        );
    }
    return replay;
}

function verifiedForceV2Required(request: GraphIndexRunRequest): boolean {
    return request.policy === 'force' && (request.durabilityMode || 'interactive') === 'interactive';
}

async function graphDependencyIdentity(
    scope: GraphIndexRunScope,
    entities: GraphIndexRunRequest['entities'],
    request: GraphIndexRunRequest,
): Promise<string> {
    return sha256Text(canonicalJson({
        schemaVersion: 'phoenix-graph-dependency-identity/v1',
        scope: {
            kind: scope.kind,
            scopeId: scope.scopeId,
            noteIds: [...scope.noteIds].sort(),
        },
        entities: entities.map((entity) => ({
            id: entity.id,
            label: entity.label,
            aliases: [...(entity.aliases || [])].sort(),
            kind: entity.kind,
            firstNote: entity.firstNote || null,
        })).sort((left, right) => left.id.localeCompare(right.id)),
        modelSelection: request.modelSelection,
        embeddingStagePolicy: normalizedEmbeddingStagePolicy(request.embeddingStagePolicy),
        calendarRegistrySnapshot: stableCalendarRegistryIdentity(request.calendarRegistrySnapshot),
        postProcessMode: 'full',
    }));
}

function replayManifestForVerifiedForceV2(
    replay: GraphRebuildReplayManifest,
    runtime: ReturnType<PhoenixBackendService['currentRuntimeInfo']>,
    result: {
        sourceBodyReads: number;
        sourceUtf8Bytes: number;
        transportedSourceBytes: number;
        fallbackCount: number;
        sourceDocuments: Array<{
            noteId: string;
            version: number | null;
            updatedAt: number | null;
        }>;
        sourceVersionEnvelopeChanged: boolean;
    },
    cache: GraphRebuildReplayManifest['cache'],
    queues: GraphRebuildReplayManifest['queues'],
): GraphRebuildReplayManifest {
    if (!runtime?.ready || !runtime.binaryBlake3 || !runtime.nativeGraphContract) {
        throw new Error('PHX_FORCE_V2_RUNTIME_IDENTITY_MISSING: exact native binary identity is required.');
    }
    if (result.fallbackCount !== 0 || result.sourceBodyReads !== replay.documents.length
        || result.sourceUtf8Bytes !== replay.aggregate.utf8Bytes || result.transportedSourceBytes !== 0) {
        throw new Error('PHX_FORCE_V2_SOURCE_TELEMETRY_MISMATCH: native source accounting differs from the replay manifest.');
    }
    return {
        ...replay,
        documents: replay.documents.map((document, index) => ({
            ...document,
            version: result.sourceDocuments[index].version,
            updatedAt: result.sourceDocuments[index].updatedAt,
        })),
        runtime: {
            buildGitSha: runtime.buildGitSha,
            buildProfile: runtime.buildProfile,
            target: runtime.target,
            storage: runtime.storage,
            schemaVersion: runtime.schemaVersion,
            binaryBlake3: runtime.binaryBlake3,
            nativeGraphContract: runtime.nativeGraphContract,
        },
        cache: { ...cache },
        queues: { ...queues },
        memory: {
            measurement: 'instrumented-boundaries',
            documentBodyMaterializations: result.sourceBodyReads,
            documentBodyCopies: 0,
            documentUtf8Bytes: result.sourceUtf8Bytes,
            unmeasuredAllocatorEvents: 1,
        },
        pathId: GRAPH_FORCE_V2_PATH_ID,
        fallbackCount: 0,
    };
}

function reusedGraphBuildTimings(
    previous: GraphRebuildBuildTimings | undefined,
    durable: NativeGraphRunPersistReceipt,
    totalMs: number,
    persistMs: number,
): GraphRebuildBuildTimings | undefined {
    if (!previous) return undefined;
    return {
        ...previous,
        occurrenceLoadMs: 0,
        chunkLoadMs: 0,
        noteTextLoadMs: 0,
        noteFolderLoadMs: 0,
        dbLoadMs: 0,
        occurrenceRecoverMs: 0,
        documentProfileMs: 0,
        documentSemanticMs: 0,
        snapshotBuildMs: 0,
        snapshotAnchorsMs: 0,
        snapshotFactsMs: 0,
        snapshotCompatibilityViewsMs: 0,
        snapshotTargetsMs: 0,
        snapshotPostProcessMs: 0,
        snapshotEmbeddingPostProcessMs: 0,
        snapshotEmbeddingSignaturesMs: 0,
        snapshotEmbeddingPairPlanMs: 0,
        snapshotEmbeddingNeighborsMs: 0,
        snapshotEmbeddingClustersMs: 0,
        snapshotEmbeddingRowsEdgesMs: 0,
        snapshotGraphAwareLinksMs: 0,
        snapshotEntityLinkingMs: 0,
        snapshotAssemblyMs: 0,
        snapshotSemanticTasksMs: 0,
        snapshotSemanticCandidatesMs: 0,
        snapshotManifoldSpecializationMs: 0,
        snapshotSemanticRerankMs: 0,
        snapshotSemanticAdjudicationMs: 0,
        snapshotSemanticEvalLedgerMs: 0,
        snapshotSemanticLedgersMs: 0,
        snapshotSemanticIndexBuilds: 0,
        snapshotSemanticIndexEntries: 0,
        snapshotSemanticAvoidedIndexBuilds: 0,
        snapshotSemanticAvoidedIndexEntries: 0,
        packetConstructionMs: 0,
        stateCommitMs: 0,
        nativeSnapshotAnalysisMs: 0,
        nativeSnapshotAnalysisRustMicros: 0,
        nativeSnapshotAnalysisSource: 'durable_verified',
        nativeGraphRunArenaReused: 1,
        nativeGraphRunArenaResidentBytes: undefined,
        nativeGraphRunArenaActiveLeases: undefined,
        nativeGraphRunPageProjectionMicros: 0,
        nativeGraphRunDetailRows: 0,
        nativeGraphRunReturnedDetailRows: 0,
        nativeGraphRunPersistMs: persistMs,
        nativeGraphRunChangedSections: durable.changedSections,
        nativeGraphRunReusedSections: durable.reusedSections,
        nativeGraphRunEncodedSections: durable.encodedSections,
        nativeGraphRunCompressedSections: durable.compressedSections,
        nativeGraphRunRawBytesWritten: durable.rawBytesWritten,
        nativeGraphRunCompressedBytesWritten: durable.compressedBytesWritten,
        nativeChunkSemanticBridgeMs: 0,
        nativeChunkSemanticBridgeSkipped: 1,
        nativeChunkSemanticBridgeCandidates: 0,
        nativeChunkSemanticBridgeQualityDemotions: 0,
        nativeChunkSemanticBridgeRustMicros: 0,
        nativeStoryContinuityMs: 0,
        nativeStoryContinuitySkipped: 1,
        nativeStoryContinuityRows: 0,
        nativeStoryContinuityRustMicros: 0,
        nativeMemoryGovernanceMs: 0,
        nativeMemoryGovernanceSkipped: 1,
        nativeMemoryGovernanceCandidates: 0,
        nativeMemoryGovernanceRustMicros: 0,
        nativeMemoryGovernanceRetrievalExperimentMs: 0,
        nativeMemoryGovernanceRetrievalExperimentSkipped: 1,
        nativeMemoryGovernanceRetrievalExperimentCandidates: 0,
        nativeMemoryGovernanceRetrievalExperimentRustMicros: 0,
        nativePromotionVerdictMs: 0,
        nativePromotionVerdictSkipped: 1,
        nativePromotionVerdictRows: 0,
        nativePromotionVerdictRustMicros: 0,
        nativeCompilerMs: 0,
        nativeCompilerSkipped: 1,
        nativeCompilerInputBytesByFamily: {},
        nativeTargetsByOriginatingFamily: {},
        nativeAtlasSeedRawBytes: 0,
        nativeAtlasSeedCompressedBytes: 0,
        snapshotPersistMs: 0,
        snapshotSerializeMs: 0,
        snapshotPrimaryEncodeMs: 0,
        snapshotPrimaryWriteSkipped: 1,
        snapshotPrimaryIdentityReused: 1,
        snapshotOverGraphEncodeMs: 0,
        snapshotStoreMs: 0,
        snapshotPrimaryStoreMs: 0,
        snapshotOverGraphStoreMs: 0,
        snapshotStoreDocuments: 0,
        snapshotContentBlobReads: 0,
        snapshotContentBlobManifestTrusted: 0,
        snapshotContentBlobManifestMatches: 0,
        snapshotContentBlobManifestMisses: 0,
        snapshotWrittenContentBlobs: 0,
        snapshotReusedContentBlobs: 0,
        previousSnapshotHydrationSkipped: 1,
        documentSemanticSkipped: 0,
        documentSemanticCacheHit: 1,
        documentSemanticDocumentsBuilt: 0,
        documentSemanticDocumentsReused: 0,
        documentSemanticRawBytesWritten: 0,
        documentSemanticCompressedBytesWritten: 0,
        nativeChunkerSkipped: 1,
        snapshotEventMs: 0,
        snapshotPayloadProfileMs: 0,
        authoritySealMs: 0,
        authorityAssertMs: Math.max(0, totalMs - persistMs),
        dbOpsMs: 0,
        totalMs,
    };
}

async function sha256Text(value: string): Promise<string> {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return [...new Uint8Array(digest)]
        .map((byte) => byte.toString(16).padStart(2, '0'))
        .join('');
}

function canonicalJson(value: unknown): string {
    return JSON.stringify(canonicalValue(value));
}

function canonicalValue(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(canonicalValue);
    if (!value || typeof value !== 'object') return value;
    const record = value as Record<string, unknown>;
    return Object.fromEntries(
        Object.keys(record)
            .filter((key) => record[key] !== undefined)
            .sort()
            .map((key) => [key, canonicalValue(record[key])]),
    );
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
