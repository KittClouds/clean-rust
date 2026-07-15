import { createTauRPCProxy, type Router as PhoenixTaurpcRouter } from '../generated/phoenix-taurpc';
import { registerPhoenixNativeBackend, type PhoenixNativeBridge } from './phoenix-backend.service';
import type { PhoenixBootSnapshotRows } from './phoenix-boot-snapshot.model';
import type { PhoenixGalaxyScene, PhoenixGalaxySceneRequest } from './phoenix-galaxy-scene.model';
import type {
    PhoenixGraphScenePacket,
    PhoenixGraphScenePacketRequest,
} from './phoenix-graph-scene-packet.model';
import { phoenixTransportAudit } from './phoenix-transport-audit';
import type { PhoenixSnapshotPartition } from './phoenix-wasm.service';
import type {
    PhoenixMentionBatchRequest,
    PhoenixMentionBatchResult,
    PhoenixGraphRunOpenResult,
} from './phoenix-backend.service';
import {
    errorMessage,
    extractText,
    fetchOpenRouter,
    fetchOpenRouterStream,
    modelResponse,
    numberOr,
    responseFormat,
    safeParseObject,
    stringOr,
    toolCallingBody,
    type TaurpcChatCallbacks,
} from './phoenix-taurpc-openrouter';

type PhoenixRpc = ReturnType<typeof createTauRPCProxy>;
type ReadyCallback = () => void;
const GRAPH_REBUILD_NAMESPACE_AUDIT = 'phoenix_graph_rebuild_v1';
const GRAPH_REBUILD_OVERGRAPH_DOCUMENT_KEY = 'graph-model-v2-overgraph';
const GRAPH_REBUILD_POSTPROCESS_CACHE_PREFIX = 'postprocess-cache';

export function registerPhoenixTaurpcBackendIfAvailable(): boolean {
    if (typeof window === 'undefined' || !window.__TAURI_INTERNALS__) {
        return false;
    }
    if (window.__PHOENIX_NATIVE_BACKEND__) {
        return true;
    }
    registerPhoenixNativeBackend(new PhoenixTaurpcBridge(createTauRPCProxy()));
    return true;
}

function storeCommandAuditName(command: string, payload: Record<string, unknown> = {}): string {
    const base = `phoenix.store_command:${command}`;
    if (command === 'relation:getFirst' || command === 'relation:list') {
        const relation = auditToken(payload['relation']);
        if (!relation) return base;
        const filter = objectRecord(payload['filter']);
        if (relation === 'scoped_documents') {
            const documentKey = scopedDocumentAuditKey(filter);
            return documentKey ? `${base}:${relation}:${documentKey}` : `${base}:${relation}`;
        }
        return `${base}:${relation}`;
    }
    if (command === 'note:list' || command === 'note:listByIds' || command === 'note:get') {
        return `${base}:${payload['includeBody'] === true ? 'body' : 'meta'}`;
    }
    return base;
}

function scopedDocumentAuditKey(filter: Record<string, unknown> | null): string {
    if (!filter) return '';
    const namespace = stringValue(filter['namespace']);
    const documentKey = stringValue(filter['documentKey']) || stringValue(filter['document_key']);
    if (!documentKey) return '';
    if (namespace === GRAPH_REBUILD_NAMESPACE_AUDIT) {
        if (documentKey === 'snapshot') return 'snapshot';
        if (documentKey === 'receipt') return 'receipt';
        if (documentKey === GRAPH_REBUILD_OVERGRAPH_DOCUMENT_KEY) return 'overgraph';
        if (documentKey.startsWith(`${GRAPH_REBUILD_POSTPROCESS_CACHE_PREFIX}:`)) return 'postprocess-cache';
    }
    return auditToken(documentKey);
}

function objectRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function stringValue(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function auditToken(value: unknown): string {
    if (typeof value !== 'string') return '';
    return value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '')
        .slice(0, 64);
}

export function canonicalRewardObserverDelayMs(report: unknown, now = Date.now()): number {
    const row = objectRecord(report);
    const nextEligibleAt = typeof row?.['nextEligibleAt'] === 'number'
        ? row['nextEligibleAt']
        : null;
    return nextEligibleAt === null
        ? 5 * 60 * 1_000
        : Math.min(Math.max(nextEligibleAt - now, 1_000), 2_147_483_647);
}

export function graphAnalysisResidentDocumentRequest(
    request: unknown,
    residentDocuments: Map<string, { text: string; textHash: string }>,
    pendingRun: { runHandle: string; signature: string } | null,
): unknown {
    const record = objectRecord(request);
    const documents = Array.isArray(record?.['documents']) ? record['documents'] : null;
    if (!record || !documents) return request;
    let changed = false;
    const compactDocuments = documents.map((value) => {
        const document = objectRecord(value);
        const noteId = stringValue(document?.['noteId']);
        const text = stringValue(document?.['text']);
        const resident = residentDocuments.get(noteId);
        if (!resident || resident.text !== text) return value;
        changed = true;
        return { noteId, text: null, textHash: resident.textHash };
    });
    const compactRequest = changed ? { ...record, documents: compactDocuments } : record;
    const signature = graphRunDocumentSignature(compactDocuments, 'noteId');
    return pendingRun?.signature === signature
        ? { ...compactRequest, runHandle: pendingRun.runHandle }
        : compactRequest;
}

function graphRunDocumentSignature(documents: unknown[], idField: 'documentId' | 'noteId'): string {
    return documents
        .map((value) => {
            const document = objectRecord(value);
            return `${stringValue(document?.[idField])}:${stringValue(document?.['textHash'])}`;
        })
        .sort()
        .join('|');
}

class PhoenixTaurpcBridge implements PhoenixNativeBridge {
    private ready = false;
    private loading: Promise<void> | null = null;
    private readonly readyCallbacks = new Set<ReadyCallback>();
    private readonly residentGraphDocuments = new Map<string, { text: string; textHash: string }>();
    private pendingGraphRun: { runHandle: string; signature: string } | null = null;
    private reportedBuild = '';
    private rewardHorizonTimer: ReturnType<typeof setTimeout> | null = null;

    constructor(private readonly rpc: PhoenixRpc) {}

    get isReady(): boolean {
        return this.ready;
    }

    onReady(callback: ReadyCallback): void {
        if (this.ready) {
            queueMicrotask(callback);
            return;
        }
        this.readyCallbacks.add(callback);
    }

    async loadRuntime(): Promise<void> {
        if (!this.loading) {
            this.loading = this.initRuntime(false).then(() => undefined);
        }
        await this.loading;
    }

    async initRuntime(forceReset = false): Promise<any> {
        if (forceReset) {
            this.loading = null;
            if (this.rewardHorizonTimer !== null) {
                clearTimeout(this.rewardHorizonTimer);
                this.rewardHorizonTimer = null;
            }
        }
        const request = {
            forceReset,
            storagePath: null,
            storage: 'nativeLocal',
        };
        const info = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.init_runtime',
            () => this.rpc.phoenix.init_runtime(request),
        );
        const build = `${info.buildProfile}:${info.buildGitSha}`;
        if (build !== this.reportedBuild) {
            this.reportedBuild = build;
            console.info(`[PhoenixNative] ${info.buildProfile} ${info.buildGitSha.slice(0, 12)}`);
        }
        await this.observeNativeRewardHorizons();
        this.markReady(Boolean(info.ready));
        return info;
    }

    async createSession(label: string, scope: Record<string, unknown> = {}): Promise<any> {
        return this.callJson('create_session_json', { sessionId: null, label, scope });
    }

    async ingest(request: Record<string, unknown>): Promise<any> {
        return this.callJson('ingest_json', request);
    }

    async query(request: Record<string, unknown>): Promise<any> {
        return this.callJson('query_json', request);
    }

    async commit(sessionId: string, request: Record<string, unknown> = {}): Promise<any> {
        return this.callJson('commit_json', { ...request, sessionId });
    }

    async rebuild(request: Record<string, unknown> = {}): Promise<any> {
        return this.callJson('rebuild_json', request);
    }

    async scan(request: Record<string, unknown>): Promise<any> {
        return this.callJson('scan_json', request);
    }

    async scanMentionsBatch(request: PhoenixMentionBatchRequest): Promise<PhoenixMentionBatchResult[]> {
        await this.loadRuntime();
        const response = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.scan_mentions_batch',
            () => this.rpc.phoenix.scan_mentions_batch(request),
        );
        const textByDocument = new Map(request.documents.map((document) => [document.documentId, document.text]));
        for (const document of response.documents) {
            const text = textByDocument.get(document.documentId);
            if (text !== undefined) {
                this.residentGraphDocuments.set(document.documentId, {
                    text,
                    textHash: document.textHash,
                });
            }
        }
        return response.documents.map((document) => {
            const text = textByDocument.get(document.documentId) || '';
            const mentions = document.mentions.map((row) => ({
                start: Number(row[0] || 0),
                end: Number(row[1] || 0),
                kindIndex: Number(row[2] ?? -1),
                entityIndex: Number(row[3] ?? -1),
                confidence: Number(row[4] || 0),
                sentenceIndex: Number(row[5] || 0),
            }));
            const offsets = utf8MentionOffsets(text, mentions);
            return {
                documentId: document.documentId,
                mentions: mentions.map((mention) => ({
                    range: { start: mention.start, end: mention.end },
                    surface: text.slice(
                        offsets.get(mention.start) ?? mention.start,
                        offsets.get(mention.end) ?? mention.end,
                    ),
                    kind: mention.kindIndex < 0 ? null : response.kinds[mention.kindIndex] || null,
                    entityRef: mention.entityIndex < 0
                        ? null
                        : response.entityRefs[mention.entityIndex] || null,
                    source: 'discovery' as const,
                    confidence: mention.confidence,
                    sentenceIndex: mention.sentenceIndex,
                })),
            };
        });
    }

    async openGraphRun(request: PhoenixMentionBatchRequest): Promise<PhoenixGraphRunOpenResult> {
        await this.loadRuntime();
        const response = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.open_graph_run',
            () => this.rpc.phoenix.open_graph_run(request),
        );
        const textByDocument = new Map(request.documents.map((document) => [document.documentId, document.text]));
        for (const document of response.documents) {
            const text = textByDocument.get(document.documentId);
            if (text !== undefined) {
                this.residentGraphDocuments.set(document.documentId, { text, textHash: document.textHash });
            }
        }
        this.pendingGraphRun = {
            runHandle: response.runHandle,
            signature: graphRunDocumentSignature(response.documents, 'documentId'),
        };
        return response;
    }

    async analyzeGraphSnapshot(request: unknown): Promise<unknown> {
        await this.loadRuntime();
        const residentRequest = graphAnalysisResidentDocumentRequest(
            request,
            this.residentGraphDocuments,
            this.pendingGraphRun,
        );
        return phoenixTransportAudit.measureTypedRpc(
            'phoenix.analyze_graph_snapshot',
            () => this.rpc.phoenix.analyze_graph_snapshot(residentRequest as never),
        );
    }

    async readGraphRunPage(request: { runHandle: string; offset: number; limit: number }): Promise<unknown> {
        await this.loadRuntime();
        return phoenixTransportAudit.measureTypedRpc(
            'phoenix.read_graph_run_page',
            () => this.rpc.phoenix.read_graph_run_page(request),
        );
    }

    async persistGraphRun(runHandle: string): Promise<unknown> {
        await this.loadRuntime();
        return phoenixTransportAudit.measureTypedRpc(
            'phoenix.persist_graph_run',
            () => this.rpc.phoenix.persist_graph_run({ runHandle }),
        );
    }

    async beginNativeOperatorDecision(request: unknown): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.begin_native_operator_decision_json(
            JSON.stringify(request),
        );
        return JSON.parse(response);
    }

    async completeNativeOperatorDecision(request: unknown): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.complete_native_operator_decision_json(
            JSON.stringify(request),
        );
        return JSON.parse(response);
    }

    async commitCanonicalEpisodeAssignment(request: unknown): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.commit_canonical_episode_assignment_json(
            JSON.stringify(request),
        );
        return JSON.parse(response);
    }

    async nativeDecisionCensus(): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.native_decision_census_json();
        return JSON.parse(response);
    }

    async linkNativeOperatorDecisionGraphTruth(request: unknown): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.link_native_operator_decision_graph_truth_json(
            JSON.stringify(request),
        );
        return JSON.parse(response);
    }

    async recordNativeRewardObservation(request: unknown): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.record_native_reward_observation_json(
            JSON.stringify(request),
        );
        return JSON.parse(response);
    }

    async nativeRewardObservationCensus(): Promise<unknown> {
        await this.loadRuntime();
        const response = await this.rpc.phoenix.native_reward_observation_census_json();
        return JSON.parse(response);
    }

    async observeNativeRewardHorizons(): Promise<unknown> {
        const response = await this.rpc.phoenix.observe_native_reward_horizons_json();
        const report = JSON.parse(response);
        const delayMs = canonicalRewardObserverDelayMs(report);
        if (this.rewardHorizonTimer !== null) clearTimeout(this.rewardHorizonTimer);
        this.rewardHorizonTimer = setTimeout(() => {
            this.observeNativeRewardHorizons().catch((error) => {
                console.error('[PhoenixNative] canonical reward horizon observer failed', error);
            });
        }, delayMs);
        return report;
    }

    async closeGraphRun(runHandle: string): Promise<boolean> {
        await this.loadRuntime();
        return this.rpc.phoenix.close_graph_run(runHandle);
    }

    async atlasRichScan(request: Record<string, unknown>): Promise<any> {
        return this.callJson('atlas_rich_scan_json', request);
    }

    async manifoldSnapshot(request: Record<string, unknown>): Promise<any> {
        return this.callJson('manifold_snapshot_json', request);
    }

    async graphScenePacket(request: PhoenixGraphScenePacketRequest): Promise<PhoenixGraphScenePacket> {
        return this.callJson('graph_scene_packet_json', request);
    }

    async nliAdjudicateClaims(request: Record<string, unknown>): Promise<any> {
        return this.callJson('nli_adjudicate_claims_json', request);
    }

    async lorentzForestCache(request: Record<string, unknown>): Promise<any> {
        return this.callJson('lorentz_forest_cache_json', request);
    }

    async lorentzForestBuild(request: Record<string, unknown>): Promise<any> {
        return this.callJson('lorentz_forest_build_json', request);
    }

    async lorentzForestQuery(request: Record<string, unknown>): Promise<any> {
        return this.callJson('lorentz_forest_query_json', request);
    }

    async siegelFinslerReceipt(request: Record<string, unknown>): Promise<any> {
        return this.callJson('siegel_finsler_receipt_json', request);
    }

    async buildStructure(request: Record<string, unknown>): Promise<any> {
        return this.callJson('build_structure_json', request);
    }

    async analyzeText(text: string): Promise<any> {
        return this.callJson('analyze_text_json', { text });
    }

    async graphDelta(request: Record<string, unknown>): Promise<any> {
        return this.callJson('graph_delta_json', request);
    }

    async sessionState(sessionId: string): Promise<any> {
        return this.callJson('session_state_json', { sessionId });
    }

    async sessionStats(sessionId: string): Promise<any> {
        return this.callJson('session_stats_json', { sessionId });
    }

    async exportSnapshot(partition: PhoenixSnapshotPartition = 'all', _capacityHint = 0): Promise<Uint8Array> {
        await this.loadRuntime();
        const bytes = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.export_snapshot',
            () => this.rpc.phoenix.export_snapshot(partition),
        );
        return bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    }

    async importSnapshot(bytes: Uint8Array): Promise<any> {
        await this.loadRuntime();
        const payload = Array.from(bytes);
        return phoenixTransportAudit.measureTypedRpc(
            'phoenix.import_snapshot',
            () => this.rpc.phoenix.import_snapshot(payload),
        );
    }

    async bootSnapshot(): Promise<PhoenixBootSnapshotRows> {
        await this.loadRuntime();
        try {
            return await phoenixTransportAudit.measureJsonRpc(
                'phoenix.boot_snapshot_json',
                '',
                () => this.rpc.phoenix.boot_snapshot_json(),
                (raw) => parseJson<PhoenixBootSnapshotRows>(raw),
            );
        } catch (error) {
            if (!isMissingTaurpcProcedure(error, 'boot_snapshot_json')) {
                throw error;
            }
            console.warn(
                '[PhoenixTaurpcBridge] boot_snapshot unavailable on current native binary; using store-command boot hydration.',
            );
            return this.storeCommandBootSnapshot();
        }
    }

    async compileGalaxyScene(request: PhoenixGalaxySceneRequest): Promise<PhoenixGalaxyScene> {
        const response = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.compile_galaxy_scene',
            () => this.rpc.phoenix.compile_galaxy_scene({
                entities: request.entities.map((entity) => ({
                    ...entity,
                    totalMentions: entity.totalMentions ?? null,
                    atlasX: entity.atlasX ?? null,
                    atlasY: entity.atlasY ?? null,
                    atlasZ: entity.atlasZ ?? null,
                    colorHsl: entity.colorHsl ?? null,
                })),
                edges: request.edges.map((edge) => ({ ...edge })),
                settings: request.settings,
            }),
        );
        return {
            nodes: response.nodes.map((node) => ({
                ...node,
                entity: {
                    ...node.entity,
                    totalMentions: node.entity.totalMentions ?? undefined,
                },
            })),
            links: response.links.map((link) => ({ ...link })),
        };
    }

    async storeCommand(command: string, payload: Record<string, unknown> = {}): Promise<any> {
        await this.loadRuntime();
        const payloadJson = JSON.stringify(payload ?? {});
        const auditName = storeCommandAuditName(command, payload);
        const result = await phoenixTransportAudit.measureJsonRpc(
            auditName,
            payloadJson,
            () => this.rpc.phoenix.store_command(command, payloadJson),
            (raw) => parseJson<{ success?: boolean; payload?: unknown; error?: string }>(raw),
        );
        if (!result?.success) {
            throw new Error(result?.error || `Phoenix store command failed: ${command}`);
        }
        phoenixTransportAudit.recordPayloadCounters(
            auditName,
            'taurpc-json',
            flattenNumericCounters(result.payload, 'payload'),
        );
        return result.payload ?? null;
    }

    async chatInit(config: Record<string, unknown>): Promise<any> {
        return this.storeCommand('chat:init', { config });
    }

    async chatCreateThread(worldId: string, narrativeId: string, title?: string): Promise<any> {
        return this.storeCommand('chat:createThread', { worldId, narrativeId, ...(title ? { title } : {}) });
    }

    async chatGetThread(id: string): Promise<any> {
        return this.storeCommand('chat:getThread', { id });
    }

    async chatListThreads(worldId?: string): Promise<any> {
        return this.storeCommand('chat:listThreads', worldId ? { worldId } : {});
    }

    async chatDeleteThread(id: string): Promise<void> {
        await this.storeCommand('chat:deleteThread', { id });
    }

    async chatAddMessage(threadId: string, role: string, content: string, narrativeId?: string): Promise<any> {
        return this.storeCommand('chat:addMessage', { threadId, role, content, ...(narrativeId ? { narrativeId } : {}) });
    }

    async chatListMessages(threadId: string): Promise<any> {
        return this.storeCommand('chat:listMessages', { threadId });
    }

    async chatUpdateMessage(messageId: string, content: string): Promise<any> {
        return this.storeCommand('chat:updateMessage', { messageId, content });
    }

    async chatAppendMessage(messageId: string, chunk: string): Promise<any> {
        return this.storeCommand('chat:appendMessage', { messageId, chunk });
    }

    async chatStartStreamingMessage(threadId: string, narrativeId?: string): Promise<any> {
        return this.storeCommand('chat:startStreamingMessage', { threadId, ...(narrativeId ? { narrativeId } : {}) });
    }

    async chatClearThread(threadId: string): Promise<void> {
        await this.storeCommand('chat:clearThread', { threadId });
    }

    async chatExportThread(threadId: string): Promise<string> {
        return (await this.storeCommand('chat:exportThread', { threadId })) || '{}';
    }

    async chatStartRun(threadId: string, prompt: string, options: Record<string, unknown>): Promise<any> {
        return this.storeCommand('chat:startRun', { threadId, prompt, options });
    }

    async chatPollRun(runId: string): Promise<any> {
        return this.storeCommand('chat:pollRun', { runId });
    }

    async chatResumeRun(runId: string): Promise<any> {
        return this.storeCommand('chat:resumeRun', { runId });
    }

    async chatCancelRun(runId: string): Promise<any> {
        return this.storeCommand('chat:cancelRun', { runId });
    }

    async chatListRunEvents(threadId: string, limit = 100): Promise<any> {
        return this.storeCommand('chat:listRunEvents', { threadId, limit });
    }

    async chatMarkRunStreaming(runId: string, assistantMessageId: string): Promise<any> {
        return this.storeCommand('chat:markRunStreaming', { runId, assistantMessageId });
    }

    async chatCompleteRun(runId: string, assistantMessageId: string, finalResponse: string, finalError?: string): Promise<any> {
        return this.storeCommand('chat:completeRun', {
            runId,
            assistantMessageId,
            finalResponse,
            ...(finalError ? { finalError } : {}),
        });
    }

    async chatGetPlannerStep(runId: string): Promise<any> {
        return this.storeCommand('chat:getPlannerStep', { runId });
    }

    async chatSubmitPlannerModelResponse(runId: string, response: any): Promise<any> {
        return this.storeCommand('chat:submitPlannerModelResponse', { runId, response });
    }

    async chatAdvancePlannerRun(runId: string): Promise<any> {
        return this.storeCommand('chat:advancePlannerRun', { runId });
    }

    async chatDegradePlannerRun(runId: string, reason: string): Promise<any> {
        return this.storeCommand('chat:degradePlannerRun', { runId, reason });
    }

    async chatListPlannerArtifacts(runId: string): Promise<any[]> {
        const payload = await this.storeCommand('chat:listPlannerArtifacts', { runId });
        return Array.isArray(payload) ? payload : [];
    }

    async chatPinPlannerArtifact(runId: string, key: string, pinned = true): Promise<any> {
        return this.storeCommand('chat:pinPlannerArtifact', { runId, key, pinned });
    }

    async chatPrepareOm(threadId: string): Promise<any> {
        return this.storeCommand('chat:prepareOm', { threadId });
    }

    async chatApplyOmAction(action: any, response: string): Promise<boolean> {
        return !!(await this.storeCommand('chat:applyOmAction', { action, response }));
    }

    async chatProcessOm(threadId: string, config: any): Promise<boolean> {
        if (!config?.apiKey?.trim()) {
            return false;
        }
        let mutated = false;
        for (let iteration = 0; iteration < 4; iteration += 1) {
            const action = await this.chatPrepareOm(threadId);
            if (!action) {
                break;
            }
            const response = await this.runOmAction(action, config);
            mutated = (await this.chatApplyOmAction(action, response)) || mutated;
        }
        return mutated;
    }

    async chatProcessPlannerRun(runId: string, config: any): Promise<boolean> {
        if (!config?.apiKey?.trim()) {
            await this.chatDegradePlannerRun(runId, 'Planner requires an OpenRouter API key.').catch(() => undefined);
            return false;
        }
        try {
            let step = await this.chatGetPlannerStep(runId);
            while (step) {
                if (step.kind === 'complete') {
                    return true;
                }
                if (step.kind === 'toolCalls') {
                    step = await this.chatAdvancePlannerRun(step.runId);
                    continue;
                }
                const payload = await fetchOpenRouter(step.request.model || config.defaultModel, config, {
                    ...toolCallingBody(step.request),
                    model: step.request.model || config.defaultModel,
                });
                step = await this.chatSubmitPlannerModelResponse(step.request.runId, modelResponse(payload));
            }
            return false;
        } catch (error) {
            await this.chatDegradePlannerRun(runId, errorMessage(error)).catch(() => undefined);
            return false;
        }
    }

    async chatSubmitToolResults(runId: string, results: unknown[]): Promise<any> {
        return this.storeCommand('chat:submitToolResults', { runId, results });
    }

    async chatSubmitApproval(runId: string, approvalId: string, approved: boolean, decisionJSON?: string): Promise<any> {
        return this.storeCommand('chat:submitApproval', {
            runId,
            approvalId,
            approved,
            ...(decisionJSON ? { decisionJson: decisionJSON } : {}),
        });
    }

    async streamChat(request: any, callbacks: TaurpcChatCallbacks): Promise<void> {
        try {
            const config = request?.config ?? {};
            const messages = request?.systemPrompt
                ? [{ role: 'system', content: request.systemPrompt }, ...(request.messages ?? [])]
                : request.messages ?? [];
            const response = await fetchOpenRouterStream(config.model, config, {
                messages,
                response_format: responseFormat(request?.requestOptions?.structuredOutput),
            }, callbacks);
            callbacks.onComplete(response);
        } catch (error) {
            callbacks.onEvent?.({ stage: 'stream', status: 'error', detail: errorMessage(error) });
            callbacks.onError(error instanceof Error ? error : new Error(String(error)));
        }
    }

    private async callJson(command: keyof PhoenixTaurpcRouter['phoenix'], payload: unknown): Promise<any> {
        await this.loadRuntime();
        const fn = this.rpc.phoenix[command as keyof PhoenixTaurpcRouter['phoenix']] as (requestJson: string) => Promise<string>;
        const requestJson = JSON.stringify(payload ?? {});
        return phoenixTransportAudit.measureJsonRpc(
            `phoenix.${String(command)}`,
            requestJson,
            () => fn(requestJson),
            (raw) => parseJson(raw),
        );
    }

    private async runOmAction(action: any, config: any): Promise<string> {
        if (action.kind === 'reflect' && action.reflectorToolingEnabled) {
            return this.runReflectorWithRuntime(action, config);
        }
        const payload = await fetchOpenRouter(action.model || config.omModel || config.defaultModel, config, {
            model: action.model || config.omModel || config.defaultModel,
            messages: [
                { role: 'system', content: action.systemPrompt },
                { role: 'user', content: action.userPrompt },
            ],
        });
        const content = extractText(payload?.choices?.[0]?.message?.content) || extractText(payload?.choices?.[0]?.content);
        if (!content) {
            throw new Error('OM response did not include content.');
        }
        return content;
    }

    private async runReflectorWithRuntime(action: any, config: any): Promise<string> {
        let step = await this.storeCommand('om:startReflector', { action });
        let sessionId: string | null = null;
        try {
            while (true) {
                if (step.kind === 'complete') {
                    return step.response;
                }
                if (step.kind === 'toolCalls') {
                    sessionId = step.sessionId;
                    const results = [];
                    for (const toolCall of step.toolCalls ?? []) {
                        results.push(await this.executeOmToolCall(step.threadId, toolCall));
                    }
                    step = await this.storeCommand('om:submitReflectorToolResults', { sessionId: step.sessionId, results });
                    continue;
                }
                sessionId = step.request.sessionId;
                const model = step.request.model || action.model || config.omModel || config.defaultModel;
                const payload = await fetchOpenRouter(model, config, { ...toolCallingBody(step.request), model });
                step = await this.storeCommand('om:submitReflectorModelResponse', {
                    sessionId: step.request.sessionId,
                    response: modelResponse(payload),
                });
            }
        } catch (error) {
            if (sessionId) {
                await this.storeCommand('om:dropReflectorSession', { sessionId }).catch(() => undefined);
            }
            throw error;
        }
    }

    private async executeOmToolCall(threadId: string, toolCall: any): Promise<any> {
        const name = String(toolCall?.name || '');
        const args = safeParseObject(String(toolCall?.argumentsJson || '{}'));
        const result = name === 'recover_lost_memory'
            ? await this.storeCommand('om:recoverLostMemory', { threadId, limit: numberOr(args['limit'], 10), focus: stringOr(args['focus']) })
            : name === 'memory_graph_search'
              ? await this.storeCommand('om:memoryGraphSearch', { threadId, query: stringOr(args['query']) || '', limit: numberOr(args['limit'], 10) })
              : { error: `Unsupported OM tool: ${name}` };
        return { toolCallId: toolCall.id, name, resultJson: JSON.stringify(result) };
    }

    private markReady(ready: boolean): void {
        this.ready = ready;
        if (!ready) {
            return;
        }
        for (const callback of this.readyCallbacks) {
            queueMicrotask(callback);
        }
        this.readyCallbacks.clear();
    }

    private async storeCommandBootSnapshot(): Promise<PhoenixBootSnapshotRows> {
        const [noteHeaders, entities, edges, folders] = await Promise.all([
            this.storeCommand('note:list', { includeBody: false }),
            this.storeCommand('relation:list', { relation: 'entities' }),
            this.storeCommand('relation:list', { relation: 'edges' }),
            this.storeCommand('relation:list', { relation: 'folders' }),
        ]);
        const eventIds = Array.isArray(noteHeaders)
            ? noteHeaders
                  .filter((note) => note?.entity_kind === 'EVENT' && typeof note?.id === 'string')
                  .map((note) => String(note.id))
            : [];
        const eventNotes = eventIds.length
            ? await this.storeCommand('note:listByIds', { ids: eventIds, includeBody: true })
            : [];
        return {
            noteHeaders: Array.isArray(noteHeaders) ? noteHeaders : [],
            eventNotes: Array.isArray(eventNotes) ? eventNotes : [],
            entities: Array.isArray(entities) ? entities : [],
            edges: Array.isArray(edges) ? edges : [],
            folders: Array.isArray(folders) ? folders : [],
        };
    }
}

function parseJson<T = any>(value: string): T {
    return value.trim() ? JSON.parse(value) as T : null as T;
}

export function utf8MentionOffsets(
    text: string,
    mentions: Array<{ start: number; end: number }>,
): Map<number, number> {
    const endpoints = new Set<number>();
    for (const mention of mentions) {
        endpoints.add(mention.start);
        endpoints.add(mention.end);
    }
    const offsets = new Map<number, number>();
    let byteOffset = 0;
    let utf16Offset = 0;
    for (const character of text) {
        if (endpoints.has(byteOffset)) offsets.set(byteOffset, utf16Offset);
        const codePoint = character.codePointAt(0) || 0;
        byteOffset += codePoint <= 0x7f ? 1 : codePoint <= 0x7ff ? 2 : codePoint <= 0xffff ? 3 : 4;
        utf16Offset += character.length;
    }
    if (endpoints.has(byteOffset)) offsets.set(byteOffset, utf16Offset);
    return offsets;
}

function flattenNumericCounters(value: unknown, prefix: string, out: Record<string, number> = {}): Record<string, number> {
    if (!value || typeof value !== 'object') return out;
    for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
        const name = `${prefix}.${key}`;
        if (typeof raw === 'number' && Number.isFinite(raw)) {
            out[name] = raw;
        } else if (typeof raw === 'boolean') {
            out[name] = raw ? 1 : 0;
        } else if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
            flattenNumericCounters(raw, name, out);
        }
    }
    return out;
}

function isMissingTaurpcProcedure(error: unknown, procedure: string): boolean {
    const message = error instanceof Error ? error.message : String(error ?? '');
    return message.includes(`TauRPC__phoenix.${procedure}`) && message.includes('not found');
}
