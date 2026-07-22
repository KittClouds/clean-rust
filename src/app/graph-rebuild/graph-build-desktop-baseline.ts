import { Injectable, inject, type Injector } from '@angular/core';
import * as ops from '../lib/operations';
import { smartGraphRegistry } from '../lib/registry';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { CalendarService } from '../services/calendar.service';
import { GraphRebuildPipelineService } from './graph-rebuild-pipeline.service';
import { GraphRebuildService } from './graph-rebuild.service';
import type { GraphIndexRunRequest, GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import {
    GRAPH_BUILD_BASELINE_CERTIFICATE_SCHEMA_VERSION,
    GRAPH_BUILD_REPLAY_MEASURED_RUNS,
    GRAPH_BUILD_REPLAY_WARMUP_RUNS,
    graphBuildIdentityHash,
    graphBuildParity,
    graphBuildPerformanceGate,
    graphBuildRunRow,
    graphBuildVerifiedForceGate,
    sha256,
    summarizeGraphBuildLane,
    type GraphBuildBaselineCertificate,
    type GraphBuildBaselineLane,
    type GraphBuildBaselineRunRow,
    type GraphBuildVerifiedForceGate,
} from './graph-build-baseline-report';

export interface GraphBuildDesktopBaselineInput {
    documents: Array<{ title: string; text: string }>;
    warmForceRuns?: number;
    deltaRuns?: number;
}

export interface GraphBuildMutationLocalityCertificate {
    schemaVersion: 'phoenix-graph-build-mutation-locality/v1';
    materializationMs: number;
    cold: GraphBuildBaselineRunRow;
    changed: GraphBuildBaselineRunRow;
    semanticLocalityPassed: boolean;
    performancePassed: boolean;
}

export interface GraphBuildExactReplayInput {
    scope: GraphIndexRunRequest['scope'];
    documents: Array<{
        noteId: string;
        sha256: string;
        version: number | null;
        updatedAt: number | null;
    }>;
    cohortId: string;
    counts: { nodes: number; edges: number; targets: number; chunks: number; anchors: number };
    modelSelection: GraphIndexRunRequest['modelSelection'];
    embeddingStagePolicy?: GraphIndexRunRequest['embeddingStagePolicy'];
    warmupRuns?: number;
    measuredRuns?: number;
}

export interface GraphBuildExactReplayCertificate {
    schemaVersion: 'phoenix-verified-force-replay-certificate/v1';
    generatedAt: string;
    scopeId: string;
    cohortId: string;
    replayManifest: GraphBuildBaselineCertificate['replayManifest'];
    warmupRuns: number;
    measuredRuns: number;
    runs: GraphBuildBaselineRunRow[];
    summary: ReturnType<typeof summarizeGraphBuildLane>;
    parity: ReturnType<typeof graphBuildParity>;
    execution: {
        exactSeedMatched: boolean;
        cohortStable: boolean;
        pathId: 'native_verified_force_v2';
        fallbackCount: 0;
        machineEligible: boolean;
    };
    machine: {
        hardwareConcurrency: number;
        visibilityState: string;
        eventLoopDriftMs: number;
        nativeRuntimeReady: boolean;
        nativeGraphContract: string;
        binaryBlake3: string;
        buildGitSha: string;
        queuesIdleBefore: boolean;
    };
    performanceGate: GraphBuildVerifiedForceGate;
}

declare global {
    interface Window {
        __PHOENIX_GRAPH_BUILD_BASELINE__?: {
            run(input: GraphBuildDesktopBaselineInput): Promise<GraphBuildBaselineCertificate>;
            runExactReplay(input: GraphBuildExactReplayInput): Promise<GraphBuildExactReplayCertificate>;
            runMutationLocality(input: GraphBuildDesktopBaselineInput): Promise<GraphBuildMutationLocalityCertificate>;
            evictArenaAndReadFirstPage(): Promise<unknown>;
            pageAllNativeProofRows(): Promise<unknown>;
        };
    }
}

@Injectable({ providedIn: 'root' })
export class GraphBuildDesktopBaselineService {
    private readonly pipeline = inject(GraphRebuildPipelineService);
    private readonly graphRebuild = inject(GraphRebuildService);
    private readonly store = inject(PhoenixStoreService);
    private readonly phoenix = inject(PhoenixBackendService);
    private readonly calendar = inject(CalendarService);
    private lastMeasuredRunHandle: string | null = null;
    private lastReplayManifest: GraphBuildBaselineCertificate['replayManifest'] = null;

    async runExactReplay(input: GraphBuildExactReplayInput): Promise<GraphBuildExactReplayCertificate> {
        if (this.pipeline.running()) throw new Error('Graph pipeline is already running.');
        const seed = await this.graphRebuild.loadPersistedRunReceipt(input.scope.scopeId);
        const mismatches = exactReplaySeedMismatches(input, seed);
        if (mismatches.length) {
            throw new Error(`PHX_FORCE_V2_REPLAY_SEED_MISMATCH: ${mismatches.join('; ')}`);
        }
        await this.settleBackgroundWork();
        if (!this.phoenix.currentRuntimeInfo()) await this.phoenix.initRuntime(false);
        const driftStarted = performance.now();
        await new Promise<void>((resolve) => setTimeout(resolve, 100));
        const eventLoopDriftMs = Math.max(0, performance.now() - driftStarted - 100);
        const runtime = this.phoenix.currentRuntimeInfo() as any;
        const replay = seed!.replayManifest!;
        const queuesIdleBefore = replay.queues.receiptPersistencePending === 0
            && replay.queues.generationArtifactPending === 0
            && !replay.queues.postCommitDiagnosticScheduled;
        const machineEligible = runtime?.ready === true
            && runtime?.nativeGraphContract === 'phoenix-verified-force/v2'
            && document.visibilityState === 'visible'
            && eventLoopDriftMs <= 25
            && queuesIdleBefore;
        if (!machineEligible) {
            throw new Error(
                'PHX_FORCE_V2_MACHINE_INELIGIBLE: '
                + `runtimeReady=${runtime?.ready === true} `
                + `contract=${runtime?.nativeGraphContract || 'missing'} `
                + `visibility=${document.visibilityState} `
                + `eventLoopDriftMs=${Math.round(eventLoopDriftMs * 100) / 100} `
                + `queuesIdle=${queuesIdleBefore}.`,
            );
        }
        const request: GraphIndexRunRequest = {
            scope: input.scope,
            policy: 'force',
            durabilityMode: 'interactive',
            modelSelection: input.modelSelection,
            embeddingStagePolicy: input.embeddingStagePolicy,
            calendarRegistrySnapshot: this.calendar.calendarRegistrySnapshot(),
            entities: smartGraphRegistry.getAllEntities(),
        };
        const warmupRuns = Math.max(GRAPH_BUILD_REPLAY_WARMUP_RUNS, Math.min(5,
            Math.floor(input.warmupRuns ?? GRAPH_BUILD_REPLAY_WARMUP_RUNS)));
        const measuredRuns = Math.max(GRAPH_BUILD_REPLAY_MEASURED_RUNS, Math.min(50,
            Math.floor(input.measuredRuns ?? GRAPH_BUILD_REPLAY_MEASURED_RUNS)));
        for (let index = 0; index < warmupRuns; index += 1) {
            await this.measureRun('warm_force', -(index + 1), request);
        }
        const rows: GraphBuildBaselineRunRow[] = [];
        for (let index = 0; index < measuredRuns; index += 1) {
            rows.push(await this.measureRun('warm_force', index + 1, request));
        }
        const summary = summarizeGraphBuildLane(rows);
        const parity = graphBuildParity(rows);
        const cohortStable = rows.every((row) => row.cohortId === input.cohortId);
        const gate = graphBuildVerifiedForceGate(summary, rows);
        gate.passed = gate.passed && parity.exactIdentity && parity.exactAuthority
            && parity.exactCounts && parity.noTopologyWrites && cohortStable;
        return {
            schemaVersion: 'phoenix-verified-force-replay-certificate/v1',
            generatedAt: new Date().toISOString(),
            scopeId: input.scope.scopeId,
            cohortId: input.cohortId,
            replayManifest: this.lastReplayManifest,
            warmupRuns,
            measuredRuns,
            runs: rows,
            summary,
            parity,
            execution: {
                exactSeedMatched: true,
                cohortStable,
                pathId: 'native_verified_force_v2',
                fallbackCount: 0,
                machineEligible,
            },
            machine: {
                hardwareConcurrency: navigator.hardwareConcurrency || 0,
                visibilityState: document.visibilityState,
                eventLoopDriftMs: Math.round(eventLoopDriftMs * 100) / 100,
                nativeRuntimeReady: runtime.ready,
                nativeGraphContract: runtime.nativeGraphContract || '',
                binaryBlake3: runtime.binaryBlake3 || '',
                buildGitSha: runtime.buildGitSha || '',
                queuesIdleBefore,
            },
            performanceGate: gate,
        };
    }

    async evictArenaAndReadFirstPage(): Promise<unknown> {
        const runHandle = await this.resolveNativeRunHandle();
        if (!runHandle) throw new Error('No active native graph run handle is available.');
        const residentClosed = await this.phoenix.closeGraphRun(runHandle);
        const page = await this.phoenix.readGraphRunPage({ runHandle, offset: 0, limit: 1 }) as any;
        return { ...page, evictionState: residentClosed ? 'resident_closed' : 'already_cold' };
    }

    async pageAllNativeProofRows(): Promise<unknown> {
        const runHandle = await this.resolveNativeRunHandle();
        if (!runHandle) throw new Error('No active native graph run handle is available.');
        const keys = new Set<string>();
        let offset = 0;
        let pages = 0;
        let detailRows = 0;
        while (true) {
            const page = await this.phoenix.readGraphRunPage({ runHandle, offset, limit: 64 }) as any;
            if (page?.schemaVersion !== 'phoenix-graph-run-page/v1' || page.runHandle !== runHandle) {
                throw new Error('Native proof paging returned a stale or invalid page.');
            }
            const pageKeys = nativeProofPageKeys(page.projection);
            if (pageKeys.length !== page.returnedDetailRows) {
                throw new Error(`Native proof page row mismatch at ${offset}: ${pageKeys.length} != ${page.returnedDetailRows}`);
            }
            for (const key of pageKeys) {
                if (keys.has(key)) throw new Error(`Native proof page duplicated ${key}`);
                keys.add(key);
            }
            pages += 1;
            detailRows = page.detailRows;
            if (page.nextOffset == null) break;
            if (page.nextOffset <= offset) throw new Error('Native proof page cursor did not advance.');
            offset = page.nextOffset;
        }
        if (keys.size !== detailRows) {
            throw new Error(`Native proof paging incomplete: ${keys.size} != ${detailRows}`);
        }
        return { runHandle, pages, detailRows, uniqueRows: keys.size, complete: true };
    }

    private async resolveNativeRunHandle(): Promise<string | null> {
        if (this.lastMeasuredRunHandle) return this.lastMeasuredRunHandle;
        const receipt = await this.graphRebuild.loadPersistedRunReceipt('global');
        return receipt?.verifiedForceAuthority?.runHandle || null;
    }

    async runMutationLocality(
        input: GraphBuildDesktopBaselineInput,
    ): Promise<GraphBuildMutationLocalityCertificate> {
        if (input.documents.length !== 2 || input.documents.some((document) => !document.text.trim())) {
            throw new Error('Mutation locality requires exactly two non-empty documents.');
        }
        if (this.pipeline.running()) throw new Error('Graph pipeline is already running.');
        const scopeId = `benchmark:graph-mutation:${crypto.randomUUID()}`;
        const priorSnapshot = this.graphRebuild.snapshot();
        const priorReceipt = this.pipeline.lastReceipt();
        const noteIds: string[] = [];
        this.store.pauseSnapshots();
        try {
            for (const [index, document] of input.documents.entries()) {
                noteIds.push(await ops.createNote({
                    worldId: '', title: document.title || `Mutation document ${index + 1}`,
                    content: document.text, markdownContent: document.text, hasBody: true,
                    folderId: '', entityKind: '', entitySubtype: '', isEntity: false,
                    isPinned: false, favorite: false, ownerId: 'graph-mutation-baseline',
                    narrativeId: scopeId,
                }));
            }
            const request = baselineRequest(scopeId, noteIds);
            await this.pipeline.loadGraphModels(request);
            const cold = await this.measureRun('cold_force', 1, request);
            const changedText = `${input.documents[0].text}\n\nKai records one exact locality mutation.`;
            const materializeStarted = performance.now();
            await ops.updateNote(noteIds[0], { content: changedText, markdownContent: changedText });
            await this.store.settleDocumentSemanticMaterialization();
            const materializationMs = performance.now() - materializeStarted;
            const changed = await this.measureRun('delta', 1, { ...request, policy: 'delta' });
            return {
                schemaVersion: 'phoenix-graph-build-mutation-locality/v1',
                materializationMs: Math.round(materializationMs * 100) / 100,
                cold,
                changed,
                semanticLocalityPassed: changed.documentSemanticDocumentsBuilt === 0
                    && changed.documentSemanticDocumentsReused === 2,
                performancePassed: changed.wallMs <= 3_000,
            };
        } finally {
            await this.settleBackgroundWork();
            const scopedDocuments = await this.store.listScopedDocuments(scopeId).catch(() => []);
            for (const document of scopedDocuments) {
                await this.store.deleteScopedDocument(scopeId, document.namespace, document.documentKey);
            }
            for (const noteId of noteIds) await ops.deleteNote(noteId);
            await this.restoreVisibleState(priorSnapshot, priorReceipt);
            this.store.resumeSnapshots();
        }
    }

    async run(input: GraphBuildDesktopBaselineInput): Promise<GraphBuildBaselineCertificate> {
        if (input.documents.length !== 2 || input.documents.some((document) => !document.text.trim())) {
            throw new Error('Desktop graph baseline requires exactly two non-empty documents.');
        }
        if (this.pipeline.running()) throw new Error('Graph pipeline is already running.');

        const warmForceRuns = boundedRunCount(input.warmForceRuns, 10);
        const deltaRuns = boundedRunCount(input.deltaRuns, 10);
        const benchmarkId = crypto.randomUUID();
        const scopeId = `benchmark:graph-two-doc:${benchmarkId}`;
        const priorSnapshot = this.graphRebuild.snapshot();
        const priorReceipt = this.pipeline.lastReceipt();
        const noteIds: string[] = [];
        let deletedNotes = 0;
        let deletedDocuments = 0;
        const rows: GraphBuildBaselineRunRow[] = [];
        let certificate: GraphBuildBaselineCertificate | null = null;

        this.store.pauseSnapshots();
        try {
            for (const [index, document] of input.documents.entries()) {
                noteIds.push(await ops.createNote({
                    worldId: '',
                    title: document.title || `Benchmark document ${index + 1}`,
                    content: document.text,
                    markdownContent: document.text,
                    hasBody: true,
                    folderId: '',
                    entityKind: '',
                    entitySubtype: '',
                    isEntity: false,
                    isPinned: false,
                    favorite: false,
                    ownerId: 'graph-performance-baseline',
                    narrativeId: scopeId,
                }));
            }

            const baseRequest = baselineRequest(scopeId, noteIds);
            await this.pipeline.loadGraphModels(baseRequest);
            rows.push(await this.measureRun('cold_force', 1, baseRequest));
            for (let index = 0; index < warmForceRuns; index += 1) {
                rows.push(await this.measureRun('warm_force', index + 1, baseRequest));
            }
            for (let index = 0; index < deltaRuns; index += 1) {
                rows.push(await this.measureRun('delta', index + 1, { ...baseRequest, policy: 'delta' }));
            }
            await this.settleBackgroundWork();

            const coldRows = rows.filter((row) => row.lane === 'cold_force');
            const warmRows = rows.filter((row) => row.lane === 'warm_force');
            const deltaRows = rows.filter((row) => row.lane === 'delta');
            const coldSummary = summarizeGraphBuildLane(coldRows);
            const warmSummary = summarizeGraphBuildLane(warmRows);
            const deltaSummary = summarizeGraphBuildLane(deltaRows);
            certificate = {
                schemaVersion: GRAPH_BUILD_BASELINE_CERTIFICATE_SCHEMA_VERSION,
                generatedAt: new Date().toISOString(),
                scopeId,
                documents: await Promise.all(input.documents.map(async (document) => ({
                    title: document.title,
                    chars: document.text.length,
                    sha256: await sha256(document.text),
                }))),
                model: {
                    embeddingModelId: baseRequest.modelSelection.embeddingModelId,
                    dimension: baseRequest.modelSelection.embeddingDimensionLabel,
                    nliModelId: baseRequest.modelSelection.nliModelId,
                },
                replayManifest: this.lastReplayManifest,
                cohortStable: rows.length > 0
                    && rows.every((row) => row.cohortId !== '' && row.cohortId === rows[0].cohortId),
                runs: rows,
                summary: {
                    cold_force: coldSummary,
                    warm_force: warmSummary,
                    delta: deltaSummary,
                },
                parity: graphBuildParity(rows),
                performanceGate: graphBuildPerformanceGate(warmSummary, deltaSummary),
                cleanup: { notesDeleted: 0, scopedDocumentsDeleted: 0 },
            };
        } finally {
            try {
                await this.settleBackgroundWork();
                const scopedDocuments = await this.store.listScopedDocuments(scopeId).catch(() => []);
                for (const document of scopedDocuments) {
                    await this.store.deleteScopedDocument(scopeId, document.namespace, document.documentKey);
                    deletedDocuments += 1;
                }
                for (const noteId of noteIds) {
                    await ops.deleteNote(noteId);
                    deletedNotes += 1;
                }
                await this.restoreVisibleState(priorSnapshot, priorReceipt);
                if (rows.length) {
                    const last = rows[rows.length - 1];
                    console.info(
                        `[GraphBaseline] complete scope=${scopeId} runs=${rows.length} `
                        + `last=${last.wallMs}ms cleanupDocs=${deletedDocuments}`,
                    );
                }
            } finally {
                this.store.resumeSnapshots();
            }
        }
        if (!certificate) throw new Error('Desktop graph baseline did not produce a certificate.');
        certificate.cleanup = { notesDeleted: deletedNotes, scopedDocumentsDeleted: deletedDocuments };
        return certificate;
    }

    private async measureRun(
        lane: GraphBuildBaselineLane,
        iteration: number,
        request: GraphIndexRunRequest,
    ): Promise<GraphBuildBaselineRunRow> {
        const started = performance.now();
        const result = await this.pipeline.buildGraph(request);
        this.lastReplayManifest = result.receipt.replayManifest || null;
        this.lastMeasuredRunHandle = this.graphRebuild.residentNativeGraphRunHandle();
        const wallMs = performance.now() - started;
        const settleStarted = performance.now();
        await this.settleBackgroundWork();
        const receiptSettleMs = performance.now() - settleStarted;
        return graphBuildRunRow(
            lane,
            iteration,
            wallMs,
            receiptSettleMs,
            result.receipt,
            result.snapshot,
            await graphBuildIdentityHash(result.snapshot),
        );
    }

    private async settleBackgroundWork(): Promise<void> {
        const pipeline = this.pipeline as unknown as {
            cancelScheduledPostCommitDiagnostic?: () => void;
            postCommitDiagnosticToken: number;
            receiptPersistenceQueue: Promise<void>;
            postCommitDiagnosticQueue: Promise<void>;
        };
        pipeline.cancelScheduledPostCommitDiagnostic?.();
        pipeline.postCommitDiagnosticToken += 1;
        await pipeline.receiptPersistenceQueue;
        await pipeline.postCommitDiagnosticQueue;
    }

    private async restoreVisibleState(
        snapshot: GraphRebuildSnapshot | null,
        receipt: ReturnType<GraphRebuildPipelineService['lastReceipt']>,
    ): Promise<void> {
        if (snapshot) await this.graphRebuild.loadPersistedSnapshot(snapshot.scopeId);
        else (this.graphRebuild as unknown as { snapshotState: { set(value: null): void } }).snapshotState.set(null);
        const pipeline = this.pipeline as unknown as {
            lastReceiptState: { set(value: typeof receipt): void };
            lastSnapshotState: { set(value: GraphRebuildSnapshot | null): void };
        };
        pipeline.lastReceiptState.set(receipt);
        pipeline.lastSnapshotState.set(snapshot);
    }
}

export function installGraphBuildDesktopBaseline(injector: Injector): void {
    const harness = injector.get(GraphBuildDesktopBaselineService);
    window.__PHOENIX_GRAPH_BUILD_BASELINE__ = {
        run: (input) => harness.run(input),
        runExactReplay: (input) => harness.runExactReplay(input),
        runMutationLocality: (input) => harness.runMutationLocality(input),
        evictArenaAndReadFirstPage: () => harness.evictArenaAndReadFirstPage(),
        pageAllNativeProofRows: () => harness.pageAllNativeProofRows(),
    };
    console.info('[GraphBaseline] desktop baseline harness ready');
}

function exactReplaySeedMismatches(
    input: GraphBuildExactReplayInput,
    seed: Awaited<ReturnType<GraphRebuildService['loadPersistedRunReceipt']>>,
): string[] {
    if (!seed?.replayManifest) return ['persisted replay manifest missing'];
    const replay = seed.replayManifest;
    const mismatches: string[] = [];
    if (!seed.verifiedForceAuthority) mismatches.push('sealed native authority reference missing');
    if (replay.cohortId !== input.cohortId) mismatches.push(`cohort ${replay.cohortId} != ${input.cohortId}`);
    if (replay.scope.scopeId !== input.scope.scopeId) mismatches.push('scope identity differs');
    const expectedDocuments = [...input.documents].sort((a, b) => a.noteId.localeCompare(b.noteId));
    const actualDocuments = replay.documents.map(({ noteId, sha256, version, updatedAt }) => ({
        noteId, sha256, version, updatedAt,
    })).sort((a, b) => a.noteId.localeCompare(b.noteId));
    if (JSON.stringify(actualDocuments) !== JSON.stringify(expectedDocuments)) {
        mismatches.push(`document identities ${JSON.stringify(actualDocuments)} != ${JSON.stringify(expectedDocuments)}`);
    }
    const counts = seed.counters;
    const actualCounts = {
        nodes: counts.nodes,
        edges: counts.edges,
        targets: counts.embeddingTargets,
        chunks: counts.chunks,
        anchors: counts.acceptedAnchors,
    };
    if (JSON.stringify(actualCounts) !== JSON.stringify(input.counts)) {
        mismatches.push(`topology ${JSON.stringify(actualCounts)} != ${JSON.stringify(input.counts)}`);
    }
    if (JSON.stringify(replay.model) !== JSON.stringify(input.modelSelection)) {
        mismatches.push('model selection differs');
    }
    return mismatches;
}

function nativeProofPageKeys(projection: any): string[] {
    const keys: string[] = [];
    const add = (family: string, rows: any[], id: (row: any, index: number) => string) => {
        for (const [index, row] of (rows || []).entries()) keys.push(`${family}:${id(row, index)}`);
    };
    const bridge = projection?.bridge;
    const cross = bridge?.crossDocumentCertificate;
    add('bridge', bridge?.candidates, (row) => row.id);
    add('cross-pair', cross?.pairCoverage, (row) => `${row.sourceDocumentId}->${row.targetDocumentId}`);
    add('cross-selected', cross?.selectedRows, (row) => row.id);
    add('cross-rejected', cross?.rejectedRows, (row) => row.id);
    add('cross-weakest', cross?.weakestRows, (row) => row.id);
    add('promotion', projection?.promotion?.certificate?.rows, (row) => row.id);
    const continuity = projection?.continuity?.contract;
    add('continuity-event', continuity?.events, (row) => row.id);
    add('continuity-boundary', continuity?.boundaryReceipts, (row) => row.id);
    add('continuity-episode', continuity?.episodes, (row) => row.id);
    add('continuity-temporal', continuity?.temporalCandidates, (row) => row.id);
    add('continuity-state', continuity?.stateIntervals, (row) => row.id);
    add('continuity-causal', continuity?.causalCandidates, (row) => row.id);
    add('continuity-connection', continuity?.episodeConnections, (row) => row.id);
    add('continuity-conflict', continuity?.conflicts, (row) => row.id);
    add('governance', projection?.governance?.candidates, (row) => row.id);
    for (const variant of projection?.retrieval?.experiment?.variants || []) {
        const policy = variant.policy?.id || 'policy';
        add(`retrieval-top:${policy}`, variant.topRows, (row) => row.id);
        add(`retrieval-violation:${policy}`, variant.fullRowProof?.compressionDominance?.violations,
            (row, index) => `${index}:${String(row)}`);
    }
    return keys;
}

function baselineRequest(scopeId: string, noteIds: string[]): GraphIndexRunRequest {
    return {
        scope: { kind: 'multiNote', scopeId, label: 'Two-document performance baseline', noteIds },
        policy: 'force',
        durabilityMode: 'interactive',
        modelSelection: {
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'jina-v5-nano',
            embeddingModelLabel: 'Jina v5 Nano',
            embeddingDimensionLabel: '768d',
            nliModelId: 'modernbert-nli',
        },
        embeddingStagePolicy: { entityLinkerEnabled: true },
        entities: smartGraphRegistry.getAllEntities(),
    };
}

function boundedRunCount(value: number | undefined, fallback: number): number {
    return Math.max(1, Math.min(20, Math.floor(value ?? fallback)));
}
