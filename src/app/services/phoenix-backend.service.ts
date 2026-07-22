import { Injectable, Injector, inject } from '@angular/core';

import {
    type PhoenixChatPlannerModelResponse,
    type PhoenixChatPlannerTransportConfig,
    type PhoenixChatPlannerStep,
    type PhoenixGraphDeltaBinaryResult,
    type PhoenixOmPendingAction,
    type PhoenixOmTransportConfig,
    type PhoenixQueryBinaryResult,
    type PhoenixSessionStateBinaryResult,
    type PhoenixSessionStatsBinaryResult,
    type PhoenixSnapshotPartition,
    type PhoenixChatWorkspaceArtifact,
    PhoenixWasmService,
} from './phoenix-wasm.service';
import type { PhoenixBootSnapshotRows as PhoenixBootSnapshotPayload } from './phoenix-boot-snapshot.model';
import type { PhoenixGalaxyScene, PhoenixGalaxySceneRequest } from './phoenix-galaxy-scene.model';
import type {
    PhoenixGraphScenePacket,
    PhoenixGraphScenePacketRequest,
} from './phoenix-graph-scene-packet.model';
import type {
    PhoenixDocumentIndexReadRequest,
    PhoenixDocumentIndexReadResponse,
} from './phoenix-document-index.model';
import type {
    DesktopMentionBatchRequest,
    DesktopRuntimeInfo,
} from '../generated/phoenix-taurpc';
import { rejectAtlasRichScan } from './atlas-rich-scan-quarantine';

export type PhoenixMentionBatchRequest = DesktopMentionBatchRequest;
export type PhoenixGraphRunPageSection = 'all' | 'storyContinuity';
export interface PhoenixGraphRunPageRequest {
    runHandle: string;
    offset: number;
    limit: number;
    section?: PhoenixGraphRunPageSection;
}
export interface PhoenixGfmShadowQueryRequest {
    runHandle: string;
    query: string;
    requestGeneration: number;
    semanticDocumentIds: string[];
    limit: number;
}
export interface PhoenixGfmShadowReceipt {
    schemaVersion: string;
    source: string;
    status: string;
    reason: string | null;
    requestGeneration: number;
    snapshotId: string;
    selectedSeedIds: string[];
    results: Array<{ stableId: string; documentId: string }>;
    evidenceEntityIds: string[];
    semanticResultCount: number;
    overlapCount: number;
    uniqueGfmCount: number;
    bundleReused: boolean;
    encoderResidentReused: boolean;
    relationRowsReused: number;
    relationRowsComputed: number;
    excludedCandidateEdges: number;
    excludedRejectedEdges: number;
    noTopologyWrites: boolean;
    visibleRankingUnchanged: boolean;
    consumerAuthority?: GraphConsumerAuthorityReceipt;
    timing: { indexMicros: number; inferenceMicros: number; totalMicros: number };
}
export interface PhoenixMentionBatchResult {
    documentId: string;
    mentions: Array<{
        range: { start: number; end: number };
        surface: string;
        kind: string | null;
        entityRef: string | null;
        source: 'discovery';
        confidence: number;
        sentenceIndex: number;
    }>;
}
export interface PhoenixGraphRunOpenResult {
    runHandle: string;
    documentsBuilt?: number;
    documentsReused?: number;
    documents: Array<{
        documentId: string;
        textHash: string;
        candidates: Array<{ key: string; token: string; kind: string; score: number; count: number; status: number }>;
    }>;
}
export interface PhoenixGraphRunPersistOptions {
    authorityHash?: string;
    forceReplayBinding?: {
        schemaVersion: string;
        cohortId: string;
        sourceMode: string;
        dependencyIdentity: string;
        documentSha256: Record<string, string>;
        documents: Array<{
            noteId: string;
            sha256: string;
            jsCodeUnitChars: number;
            utf8Bytes: number;
            version: number | null;
            updatedAt: number | null;
        }>;
        dynamicNerId: string;
        embeddingModelId: string;
        embeddingDimension: string;
        nliModelId: string;
    };
}

const PHOENIX_CONTENT_COMMAND_TIMEOUT_MS = 10_000;

export class PhoenixStoreCommandTimeoutError extends Error {
    readonly code = 'PHOENIX_STORE_COMMAND_TIMEOUT';

    constructor(readonly command: string, readonly timeoutMs: number) {
        super(`Phoenix store command timed out after ${timeoutMs} ms: ${command}`);
        this.name = 'PhoenixStoreCommandTimeoutError';
    }
}

export function isPhoenixStoreCommandTimeout(error: unknown): error is PhoenixStoreCommandTimeoutError {
    return error instanceof PhoenixStoreCommandTimeoutError;
}

export function withPhoenixStoreCommandTimeout<T>(
    command: string,
    operation: Promise<T>,
    timeoutMs: number = PHOENIX_CONTENT_COMMAND_TIMEOUT_MS,
): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const timeout = setTimeout(
            () => reject(new PhoenixStoreCommandTimeoutError(command, timeoutMs)),
            timeoutMs,
        );
        operation.then(
            value => {
                clearTimeout(timeout);
                resolve(value);
            },
            error => {
                clearTimeout(timeout);
                reject(error);
            },
        );
    });
}

function isContentStoreCommand(command: string): boolean {
    return command.startsWith('note:')
        || command.startsWith('folder:')
        || command.startsWith('relation:')
        || command === 'persistence:applyWalBatch';
}

type PhoenixTransportMethodName =
    | 'onReady'
    | 'loadWasm'
    | 'initRuntime'
    | 'createSession'
    | 'ingest'
    | 'query'
    | 'commit'
    | 'rebuild'
    | 'scan'
    | 'atlasRichScan'
    | 'manifoldSnapshot'
    | 'lorentzForestCache'
    | 'lorentzForestBuild'
    | 'lorentzForestQuery'
    | 'buildStructure'
    | 'analyzeText'
    | 'graphDelta'
    | 'sessionState'
    | 'sessionStats'
    | 'exportSnapshot'
    | 'importSnapshot'
    | 'storeCommand'
    | 'chatInit'
    | 'chatCreateThread'
    | 'chatGetThread'
    | 'chatListThreads'
    | 'chatDeleteThread'
    | 'chatAddMessage'
    | 'chatListMessages'
    | 'chatUpdateMessage'
    | 'chatAppendMessage'
    | 'chatStartStreamingMessage'
    | 'chatClearThread'
    | 'chatExportThread'
    | 'chatStartRun'
    | 'chatPollRun'
    | 'chatResumeRun'
    | 'chatCancelRun'
    | 'chatListRunEvents'
    | 'chatMarkRunStreaming'
    | 'chatCompleteRun'
    | 'chatGetPlannerStep'
    | 'chatSubmitPlannerModelResponse'
    | 'chatAdvancePlannerRun'
    | 'chatDegradePlannerRun'
    | 'chatListPlannerArtifacts'
    | 'chatPinPlannerArtifact'
    | 'chatPrepareOm'
    | 'chatApplyOmAction'
    | 'chatProcessOm'
    | 'chatProcessPlannerRun'
    | 'chatSubmitToolResults'
    | 'chatSubmitApproval'
    | 'streamChat';

type PhoenixNativeMethodName = Exclude<PhoenixTransportMethodName, 'loadWasm'>;

export type PhoenixTransportSurface = Pick<PhoenixWasmService, 'isReady' | PhoenixTransportMethodName>;

export type PhoenixNativeBridge = Pick<PhoenixWasmService, 'isReady' | PhoenixNativeMethodName> & {
    loadRuntime(): Promise<void>;
    bootSnapshot(): Promise<PhoenixBootSnapshotPayload>;
    compileGalaxyScene(request: PhoenixGalaxySceneRequest): Promise<PhoenixGalaxyScene>;
    scanMentionsBatch?(request: PhoenixMentionBatchRequest): Promise<PhoenixMentionBatchResult[]>;
    openGraphRun?(request: PhoenixMentionBatchRequest): Promise<PhoenixGraphRunOpenResult>;
    analyzeGraphSnapshot?(request: unknown): Promise<unknown>;
    queryGfmShadow?(request: PhoenixGfmShadowQueryRequest): Promise<PhoenixGfmShadowReceipt>;
    readGraphRunPage?(request: PhoenixGraphRunPageRequest): Promise<unknown>;
    persistGraphRun?(runHandle: string, options?: PhoenixGraphRunPersistOptions): Promise<unknown>;
    forceRebuildV2Shadow?(request: unknown): Promise<unknown>;
    forceRebuildV2(request: unknown): Promise<unknown>;
    persistForceV2Authority(request: unknown): Promise<unknown>;
    beginNativeOperatorDecision?(request: unknown): Promise<unknown>;
    completeNativeOperatorDecision?(request: unknown): Promise<unknown>;
    commitCanonicalEpisodeAssignment?(request: unknown): Promise<unknown>;
    commitCanonicalEpisodeAssignmentsBatch?(request: unknown): Promise<unknown>;
    nativeDecisionCensus?(): Promise<unknown>;
    linkNativeOperatorDecisionGraphTruth?(request: unknown): Promise<unknown>;
    recordNativeRewardObservation?(request: unknown): Promise<unknown>;
    nativeRewardObservationCensus?(): Promise<unknown>;
    observeNativeRewardHorizons?(): Promise<unknown>;
    closeGraphRun?(runHandle: string): Promise<boolean>;
    graphScenePacket?(request: PhoenixGraphScenePacketRequest): Promise<PhoenixGraphScenePacket>;
    nliAdjudicateClaims?(request: Record<string, unknown>): Promise<any>;
    siegelFinslerReceipt?(request: Record<string, unknown>): Promise<any>;
};

export type PhoenixRuntimeTarget = 'web' | 'native';

declare global {
    interface Window {
        __PHOENIX_RUNTIME_TARGET__?: PhoenixRuntimeTarget;
        __PHOENIX_NATIVE_BACKEND__?: PhoenixNativeBridge;
        __TAURI_INTERNALS__?: unknown;
    }
}

export function registerPhoenixNativeBackend(bridge: PhoenixNativeBridge): void {
    if (typeof window === 'undefined') {
        return;
    }
    window.__PHOENIX_NATIVE_BACKEND__ = bridge;
    window.__PHOENIX_RUNTIME_TARGET__ = 'native';
}

export function setPhoenixRuntimeTarget(target: PhoenixRuntimeTarget): void {
    if (typeof window === 'undefined') {
        return;
    }
    window.__PHOENIX_RUNTIME_TARGET__ = target;
}

export function detectPhoenixRuntimeTarget(): PhoenixRuntimeTarget {
    if (typeof window === 'undefined') {
        return 'web';
    }
    const explicit = window.__PHOENIX_RUNTIME_TARGET__;
    if (explicit === 'native' || explicit === 'web') {
        return explicit;
    }
    return window.__TAURI_INTERNALS__ ? 'native' : 'web';
}

@Injectable({ providedIn: 'root' })
export class PhoenixBackendService {
    private readonly injector = inject(Injector);
    private wasmInstance: PhoenixWasmService | null = null;
    private runtimeInfoValue: DesktopRuntimeInfo | null = null;

    currentRuntimeInfo(): DesktopRuntimeInfo | null {
        return this.runtimeInfoValue;
    }

    get target(): PhoenixRuntimeTarget {
        return detectPhoenixRuntimeTarget();
    }

    get isReady(): boolean {
        return this.target === 'native'
            ? Boolean(this.nativeBridgeOrNull()?.isReady)
            : this.wasm.isReady;
    }

    onReady(callback: () => void): void {
        if (this.target === 'native') {
            this.requireNativeBridge().onReady(callback);
            return;
        }
        this.wasm.onReady(callback);
    }

    async loadRuntime(): Promise<void> {
        if (this.target === 'native') {
            await this.requireNativeBridge().loadRuntime();
            return;
        }
        await this.wasm.loadWasm();
    }

    async loadWasm(): Promise<void> {
        if (this.target === 'native') {
            throw new Error(
                'PhoenixBackendService.loadWasm() is disabled in native desktop. Use loadRuntime().',
            );
        }
        await this.wasm.loadWasm();
    }

    async initRuntime(forceReset = false): Promise<any> {
        const info = await (this.target === 'native'
            ? this.requireNativeBridge().initRuntime(forceReset)
            : this.wasm.initRuntime(forceReset));
        if (this.target === 'native') this.runtimeInfoValue = info as DesktopRuntimeInfo;
        return info;
    }

    async createSession(
        label: string,
        scope: Parameters<PhoenixWasmService['createSession']>[1] = {},
    ): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().createSession(label, scope)
            : this.wasm.createSession(label, scope);
    }

    async ingest(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().ingest(request)
            : this.wasm.ingest(request);
    }

    async query(request: Record<string, unknown>): Promise<PhoenixQueryBinaryResult> {
        return this.target === 'native'
            ? this.requireNativeBridge().query(request)
            : this.wasm.query(request);
    }

    async commit(sessionId: string, request: Record<string, unknown> = {}): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().commit(sessionId, request)
            : this.wasm.commit(sessionId, request);
    }

    async rebuild(request: Record<string, unknown> = {}): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().rebuild(request)
            : this.wasm.rebuild(request);
    }

    async scan(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().scan(request)
            : this.wasm.scan(request);
    }

    async scanMentionsBatch(request: PhoenixMentionBatchRequest): Promise<PhoenixMentionBatchResult[]> {
        if (this.target === 'native') {
            const bridge = this.requireNativeBridge();
            if (bridge.scanMentionsBatch) {
                return bridge.scanMentionsBatch(request);
            }
        }
        return Promise.all(request.documents.map(async (document) => {
            const scan = await this.scan({
                text: document.text,
                scope: {},
                sessionId: 'phoenix-ui-discovery-batch',
                resolverSeed: request.resolverSeed,
            });
            return {
                documentId: document.documentId,
                mentions: Array.isArray(scan?.mentions) ? scan.mentions : [],
            };
        }));
    }

    async openGraphRun(request: PhoenixMentionBatchRequest): Promise<PhoenixGraphRunOpenResult> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.openGraphRun() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.openGraphRun) throw new Error('Native graph run open RPC is unavailable.');
        return bridge.openGraphRun(request);
    }

    async analyzeGraphSnapshot(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.analyzeGraphSnapshot() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.analyzeGraphSnapshot) {
            throw new Error('Native graph snapshot analysis RPC is unavailable.');
        }
        return bridge.analyzeGraphSnapshot(request);
    }

    async queryGfmShadow(request: PhoenixGfmShadowQueryRequest): Promise<PhoenixGfmShadowReceipt> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.queryGfmShadow() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.queryGfmShadow) throw new Error('Native GFM shadow RPC is unavailable.');
        return bridge.queryGfmShadow(request);
    }

    async readGraphRunPage(request: PhoenixGraphRunPageRequest): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.readGraphRunPage() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.readGraphRunPage) throw new Error('Native graph run paging RPC is unavailable.');
        return bridge.readGraphRunPage(request);
    }

    async persistGraphRun(runHandle: string, options: PhoenixGraphRunPersistOptions = {}): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.persistGraphRun() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.persistGraphRun) throw new Error('Native graph run persistence RPC is unavailable.');
        return bridge.persistGraphRun(runHandle, options);
    }

    async forceRebuildV2Shadow(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PHX_FORCE_V2_NATIVE_REQUIRED: verified FORCE v2 requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.forceRebuildV2Shadow) {
            throw new Error('PHX_FORCE_V2_CAPABILITY_MISSING: the native v2 contract is not registered.');
        }
        return bridge.forceRebuildV2Shadow(request);
    }

    async forceRebuildV2(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PHX_FORCE_V2_NATIVE_REQUIRED: verified FORCE v2 requires the native runtime.');
        }
        return this.requireNativeBridge().forceRebuildV2(request);
    }

    async persistForceV2Authority(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PHX_FORCE_V2_NATIVE_REQUIRED: verified FORCE v2 requires the native runtime.');
        }
        return this.requireNativeBridge().persistForceV2Authority(request);
    }

    async beginNativeOperatorDecision(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.beginNativeOperatorDecision() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.beginNativeOperatorDecision) {
            throw new Error('Native operator decision begin RPC is unavailable.');
        }
        return bridge.beginNativeOperatorDecision(request);
    }

    async completeNativeOperatorDecision(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.completeNativeOperatorDecision() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.completeNativeOperatorDecision) {
            throw new Error('Native operator decision completion RPC is unavailable.');
        }
        return bridge.completeNativeOperatorDecision(request);
    }

    async commitCanonicalEpisodeAssignment(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.commitCanonicalEpisodeAssignment() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.commitCanonicalEpisodeAssignment) {
            throw new Error('Native canonical episode assignment RPC is unavailable.');
        }
        return bridge.commitCanonicalEpisodeAssignment(request);
    }

    async commitCanonicalEpisodeAssignmentsBatch(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.commitCanonicalEpisodeAssignmentsBatch() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.commitCanonicalEpisodeAssignmentsBatch) {
            throw new Error('Native canonical episode assignment batch RPC is unavailable.');
        }
        return bridge.commitCanonicalEpisodeAssignmentsBatch(request);
    }

    async nativeDecisionCensus(): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.nativeDecisionCensus() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.nativeDecisionCensus) throw new Error('Native decision census RPC is unavailable.');
        return bridge.nativeDecisionCensus();
    }

    async linkNativeOperatorDecisionGraphTruth(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.linkNativeOperatorDecisionGraphTruth() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.linkNativeOperatorDecisionGraphTruth) {
            throw new Error('Native decision graph-truth link RPC is unavailable.');
        }
        return bridge.linkNativeOperatorDecisionGraphTruth(request);
    }

    async recordNativeRewardObservation(request: unknown): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.recordNativeRewardObservation() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.recordNativeRewardObservation) {
            throw new Error('Native reward observation RPC is unavailable.');
        }
        return bridge.recordNativeRewardObservation(request);
    }

    async nativeRewardObservationCensus(): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.nativeRewardObservationCensus() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.nativeRewardObservationCensus) {
            throw new Error('Native reward observation census RPC is unavailable.');
        }
        return bridge.nativeRewardObservationCensus();
    }

    async observeNativeRewardHorizons(): Promise<unknown> {
        if (this.target !== 'native') {
            throw new Error('PhoenixBackendService.observeNativeRewardHorizons() requires the native runtime.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.observeNativeRewardHorizons) {
            throw new Error('Native reward horizon observer RPC is unavailable.');
        }
        return bridge.observeNativeRewardHorizons();
    }

    async closeGraphRun(runHandle: string): Promise<boolean> {
        if (this.target !== 'native') return false;
        return this.requireNativeBridge().closeGraphRun?.(runHandle) ?? false;
    }

    async atlasRichScan(request: Record<string, unknown>): Promise<any> {
        void request;
        return rejectAtlasRichScan();
    }

    async manifoldSnapshot(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().manifoldSnapshot(request)
            : this.wasm.manifoldSnapshot(request);
    }

    async lorentzForestCache(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().lorentzForestCache(request)
            : this.wasm.lorentzForestCache(request);
    }

    async lorentzForestBuild(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().lorentzForestBuild(request)
            : this.wasm.lorentzForestBuild(request);
    }

    async lorentzForestQuery(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().lorentzForestQuery(request)
            : this.wasm.lorentzForestQuery(request);
    }

    async buildStructure(request: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().buildStructure(request)
            : this.wasm.buildStructure(request);
    }

    async analyzeText(text: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().analyzeText(text)
            : this.wasm.analyzeText(text);
    }

    async graphDelta(request: Record<string, unknown>): Promise<PhoenixGraphDeltaBinaryResult> {
        return this.target === 'native'
            ? this.requireNativeBridge().graphDelta(request)
            : this.wasm.graphDelta(request);
    }

    async sessionState(sessionId: string): Promise<PhoenixSessionStateBinaryResult> {
        return this.target === 'native'
            ? this.requireNativeBridge().sessionState(sessionId)
            : this.wasm.sessionState(sessionId);
    }

    async sessionStats(sessionId: string): Promise<PhoenixSessionStatsBinaryResult> {
        return this.target === 'native'
            ? this.requireNativeBridge().sessionStats(sessionId)
            : this.wasm.sessionStats(sessionId);
    }

    async exportSnapshot(
        partition: PhoenixSnapshotPartition = 'all',
        capacityHint = 8 * 1024 * 1024,
    ): Promise<Uint8Array> {
        return this.target === 'native'
            ? this.requireNativeBridge().exportSnapshot(partition, capacityHint)
            : this.wasm.exportSnapshot(partition, capacityHint);
    }

    async importSnapshot(bytes: Uint8Array): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().importSnapshot(bytes)
            : this.wasm.importSnapshot(bytes);
    }

    async bootSnapshot(): Promise<PhoenixBootSnapshotPayload> {
        if (this.target === 'native') {
            return this.requireNativeBridge().bootSnapshot();
        }
        await this.wasm.loadWasm();
        const [noteHeaders, entities, edges, folders] = await Promise.all([
            this.wasm.storeCommand('note:list', { includeBody: false }),
            this.wasm.storeCommand('relation:list', { relation: 'entities' }),
            this.wasm.storeCommand('relation:list', { relation: 'edges' }),
            this.wasm.storeCommand('relation:list', { relation: 'folders' }),
        ]);
        const eventIds = Array.isArray(noteHeaders)
            ? noteHeaders
                  .filter((note) => note?.entity_kind === 'EVENT' && typeof note?.id === 'string')
                  .map((note) => String(note.id))
            : [];
        const eventNotes = eventIds.length
            ? await this.wasm.storeCommand('note:listByIds', { ids: eventIds, includeBody: true })
            : [];
        return {
            noteHeaders: Array.isArray(noteHeaders) ? noteHeaders : [],
            eventNotes: Array.isArray(eventNotes) ? eventNotes : [],
            entities: Array.isArray(entities) ? entities : [],
            edges: Array.isArray(edges) ? edges : [],
            folders: Array.isArray(folders) ? folders : [],
        };
    }

    async compileGalaxyScene(request: PhoenixGalaxySceneRequest): Promise<PhoenixGalaxyScene> {
        if (this.target !== 'native') {
            throw new Error('Phoenix galaxy scene compilation is only available on native desktop.');
        }
        return this.requireNativeBridge().compileGalaxyScene(request);
    }

    async graphScenePacket(request: PhoenixGraphScenePacketRequest): Promise<PhoenixGraphScenePacket> {
        if (this.target !== 'native') {
            throw new Error('Phoenix graph scene packets are only available on native desktop.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.graphScenePacket) {
            throw new Error('Phoenix native graph scene packet compiler is unavailable.');
        }
        return bridge.graphScenePacket(request);
    }

    async nliAdjudicateClaims(request: Record<string, unknown>): Promise<any> {
        if (this.target !== 'native') {
            throw new Error('Phoenix NLI claim adjudication is only available on native desktop.');
        }
        const bridge = this.requireNativeBridge();
        if (!bridge.nliAdjudicateClaims) {
            throw new Error('Phoenix native NLI claim adjudication is unavailable.');
        }
        return bridge.nliAdjudicateClaims(request);
    }

    async storeCommand(command: string, payload: Record<string, unknown> = {}): Promise<any> {
        const operation = this.target === 'native'
            ? this.requireNativeBridge().storeCommand(command, payload)
            : this.wasm.storeCommand(command, payload);
        return this.target === 'native' && isContentStoreCommand(command)
            ? withPhoenixStoreCommandTimeout(command, operation)
            : operation;
    }

    async readDocumentIndex(
        request: PhoenixDocumentIndexReadRequest,
    ): Promise<PhoenixDocumentIndexReadResponse> {
        return this.storeCommand('documentIndex:read', request as unknown as Record<string, unknown>);
    }

    async chatInit(config: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatInit(config)
            : this.wasm.chatInit(config);
    }

    async chatCreateThread(worldId: string, narrativeId: string, title?: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatCreateThread(worldId, narrativeId, title)
            : this.wasm.chatCreateThread(worldId, narrativeId, title);
    }

    async chatGetThread(id: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatGetThread(id)
            : this.wasm.chatGetThread(id);
    }

    async chatListThreads(worldId?: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatListThreads(worldId)
            : this.wasm.chatListThreads(worldId);
    }

    async chatDeleteThread(id: string): Promise<void> {
        if (this.target === 'native') {
            await this.requireNativeBridge().chatDeleteThread(id);
            return;
        }
        await this.wasm.chatDeleteThread(id);
    }

    async chatAddMessage(threadId: string, role: string, content: string, narrativeId?: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatAddMessage(threadId, role, content, narrativeId)
            : this.wasm.chatAddMessage(threadId, role, content, narrativeId);
    }

    async chatListMessages(threadId: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatListMessages(threadId)
            : this.wasm.chatListMessages(threadId);
    }

    async chatUpdateMessage(messageId: string, content: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatUpdateMessage(messageId, content)
            : this.wasm.chatUpdateMessage(messageId, content);
    }

    async chatAppendMessage(messageId: string, chunk: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatAppendMessage(messageId, chunk)
            : this.wasm.chatAppendMessage(messageId, chunk);
    }

    async chatStartStreamingMessage(threadId: string, narrativeId?: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatStartStreamingMessage(threadId, narrativeId)
            : this.wasm.chatStartStreamingMessage(threadId, narrativeId);
    }

    async chatClearThread(threadId: string): Promise<void> {
        if (this.target === 'native') {
            await this.requireNativeBridge().chatClearThread(threadId);
            return;
        }
        await this.wasm.chatClearThread(threadId);
    }

    async chatExportThread(threadId: string): Promise<string> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatExportThread(threadId)
            : this.wasm.chatExportThread(threadId);
    }

    async chatStartRun(threadId: string, prompt: string, options: Record<string, unknown>): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatStartRun(threadId, prompt, options)
            : this.wasm.chatStartRun(threadId, prompt, options);
    }

    async chatPollRun(runId: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatPollRun(runId)
            : this.wasm.chatPollRun(runId);
    }

    async chatResumeRun(runId: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatResumeRun(runId)
            : this.wasm.chatResumeRun(runId);
    }

    async chatCancelRun(runId: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatCancelRun(runId)
            : this.wasm.chatCancelRun(runId);
    }

    async chatListRunEvents(threadId: string, limit = 100): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatListRunEvents(threadId, limit)
            : this.wasm.chatListRunEvents(threadId, limit);
    }

    async chatMarkRunStreaming(runId: string, assistantMessageId: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatMarkRunStreaming(runId, assistantMessageId)
            : this.wasm.chatMarkRunStreaming(runId, assistantMessageId);
    }

    async chatCompleteRun(
        runId: string,
        assistantMessageId: string,
        finalResponse: string,
        finalError?: string,
    ): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatCompleteRun(runId, assistantMessageId, finalResponse, finalError)
            : this.wasm.chatCompleteRun(runId, assistantMessageId, finalResponse, finalError);
    }

    async chatGetPlannerStep(runId: string): Promise<PhoenixChatPlannerStep | null> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatGetPlannerStep(runId)
            : this.wasm.chatGetPlannerStep(runId);
    }

    async chatSubmitPlannerModelResponse(
        runId: string,
        response: PhoenixChatPlannerModelResponse,
    ): Promise<PhoenixChatPlannerStep | null> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatSubmitPlannerModelResponse(runId, response)
            : this.wasm.chatSubmitPlannerModelResponse(runId, response);
    }

    async chatAdvancePlannerRun(runId: string): Promise<PhoenixChatPlannerStep | null> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatAdvancePlannerRun(runId)
            : this.wasm.chatAdvancePlannerRun(runId);
    }

    async chatDegradePlannerRun(runId: string, reason: string): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatDegradePlannerRun(runId, reason)
            : this.wasm.chatDegradePlannerRun(runId, reason);
    }

    async chatListPlannerArtifacts(runId: string): Promise<PhoenixChatWorkspaceArtifact[]> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatListPlannerArtifacts(runId)
            : this.wasm.chatListPlannerArtifacts(runId);
    }

    async chatPinPlannerArtifact(runId: string, key: string, pinned = true): Promise<PhoenixChatWorkspaceArtifact | null> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatPinPlannerArtifact(runId, key, pinned)
            : this.wasm.chatPinPlannerArtifact(runId, key, pinned);
    }

    async chatPrepareOm(threadId: string): Promise<PhoenixOmPendingAction | null> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatPrepareOm(threadId)
            : this.wasm.chatPrepareOm(threadId);
    }

    async chatApplyOmAction(action: PhoenixOmPendingAction, response: string): Promise<boolean> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatApplyOmAction(action, response)
            : this.wasm.chatApplyOmAction(action, response);
    }

    async chatProcessOm(threadId: string, config: PhoenixOmTransportConfig): Promise<boolean> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatProcessOm(threadId, config)
            : this.wasm.chatProcessOm(threadId, config);
    }

    async chatProcessPlannerRun(
        runId: string,
        config: PhoenixChatPlannerTransportConfig,
    ): Promise<boolean> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatProcessPlannerRun(runId, config)
            : this.wasm.chatProcessPlannerRun(runId, config);
    }

    async chatSubmitToolResults(runId: string, results: unknown[]): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatSubmitToolResults(runId, results)
            : this.wasm.chatSubmitToolResults(runId, results);
    }

    async chatSubmitApproval(
        runId: string,
        approvalId: string,
        approved: boolean,
        decisionJSON?: string,
    ): Promise<any> {
        return this.target === 'native'
            ? this.requireNativeBridge().chatSubmitApproval(runId, approvalId, approved, decisionJSON)
            : this.wasm.chatSubmitApproval(runId, approvalId, approved, decisionJSON);
    }

    async streamChat(
        request: Parameters<PhoenixWasmService['streamChat']>[0],
        callbacks: Parameters<PhoenixWasmService['streamChat']>[1],
    ): Promise<void> {
        if (this.target === 'native') {
            await this.requireNativeBridge().streamChat(request, callbacks);
            return;
        }
        await this.wasm.streamChat(request, callbacks);
    }

    private nativeBridgeOrNull(): PhoenixNativeBridge | null {
        if (typeof window === 'undefined') {
            return null;
        }
        return window.__PHOENIX_NATIVE_BACKEND__ ?? null;
    }

    private requireNativeBridge(): PhoenixNativeBridge {
        const bridge = this.nativeBridgeOrNull();
        if (bridge) {
            return bridge;
        }
        throw new Error(
            'Phoenix native backend was selected, but no native bridge was registered. ' +
            'Register a taurpc-backed bridge with registerPhoenixNativeBackend() before Angular boot.',
        );
    }

    private get wasm(): PhoenixWasmService {
        if (this.target === 'native') {
            throw new Error('Phoenix WASM transport is disabled in native desktop.');
        }
        this.wasmInstance ??= this.injector.get(PhoenixWasmService);
        return this.wasmInstance;
    }
}
import type { GraphConsumerAuthorityReceipt } from '../graph-rebuild/graph-consumer-authority';
