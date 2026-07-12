import '@angular/compiler';

import { Injector, computed, createEnvironmentInjector, runInInjectionContext, signal, type EnvironmentInjector } from '@angular/core';
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const harnessState = vi.hoisted(() => ({
    notes: [] as any[],
    occurrences: [] as any[],
    entities: [] as any[],
    nliJudgments: [] as any[],
}));

vi.mock('../lib/dexie/db', () => ({
    db: {
        notes: {
            bulkGet: vi.fn(async (ids: string[]) =>
                ids.map((id) => harnessState.notes.find((note) => note.id === id)).filter(Boolean),
            ),
            get: vi.fn(async (id: string) => harnessState.notes.find((note) => note.id === id)),
            toArray: vi.fn(async () => harnessState.notes),
        },
        entityOccurrences: {
            where: vi.fn(() => ({
                equals: (noteId: string) => ({
                    toArray: async () => harnessState.occurrences.filter((row) => row.noteId === noteId),
                }),
            })),
            toArray: vi.fn(async () => harnessState.occurrences),
        },
        folders: {
            get: vi.fn(async () => undefined),
        },
        noteBlocks: {
            where: vi.fn(() => ({
                equals: () => ({
                    toArray: async () => [],
                }),
            })),
        },
    },
}));

vi.mock('../lib/registry', () => ({
    smartGraphRegistry: {
        getAllEntities: vi.fn(() => harnessState.entities),
        updateEntity: vi.fn((id: string, updates: any) => {
            const entity = harnessState.entities.find((row) => row.id === id);
            if (!entity) return null;
            Object.assign(entity, updates, {
                attributes: { ...(entity.attributes || {}), ...(updates.attributes || {}) },
            });
            return entity;
        }),
    },
}));

import { GraphRebuildPipelineService } from './graph-rebuild-pipeline.service';
import {
    DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY,
    GRAPH_REBUILD_NAMESPACE,
    GraphRebuildService,
    scopedDocumentToGraphRebuildSnapshot,
} from './graph-rebuild.service';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import { AtlasCapabilityRuntimeService } from '../services/atlas-capability-runtime.service';
import { NerService } from '../services/ner.service';
import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixStoreService, type PhoenixContentMutationTiming, type StoreScopedDocument } from '../services/phoenix-store.service';
import { PhoenixUiApiService } from '../services/phoenix-ui-api.service';
import type { RegisteredEntity } from '../lib/registry';
import type { EntityKind } from '../lib/Scanner/types';
import type {
    GraphIndexRunReceipt,
    GraphIndexRunRequest,
    GraphIndexStageReceipt,
    GraphRebuildCounters,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import {
    GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
    GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT,
    GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
} from './graph-rebuild-snapshot';
import { buildGraphAtlasTaxonomyAudit } from './graph-atlas-taxonomy-audit';
import { auditChunkSemanticBridgeFalsePositives } from './graph-rebuild-chunk-semantic-bridge-audit';
import { buildGraphPacketRowAdapter } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-packet-row-adapter';

const SHOULD_RUN = process.env['GRAPH_BUILD_BASELINE'] === '1';
const ZEROSHOT_OUTPUT_URL = new URL('../../../target/graph-build-baselines/zero-shot-shortrun.json', import.meta.url);
const TAXONOMY_AUDIT_OUTPUT_URL = new URL('../../../target/graph-build-baselines/atlas-taxonomy-audit-shortrun.json', import.meta.url);
const CHUNK_BRIDGE_GOLDEN_URL = new URL('./fixtures/chunk-semantic-bridge-shortrun-golden.json', import.meta.url);
const SHORTRUN_URL = new URL('../../../docs/shortrun.md', import.meta.url);
const ZEROSHOT_OUTPUT_PATH = fileURLToPath(ZEROSHOT_OUTPUT_URL);
const TAXONOMY_AUDIT_OUTPUT_PATH = fileURLToPath(TAXONOMY_AUDIT_OUTPUT_URL);
const CHUNK_BRIDGE_GOLDEN_PATH = fileURLToPath(CHUNK_BRIDGE_GOLDEN_URL);
const SHORTRUN_PATH = fileURLToPath(SHORTRUN_URL);
const SHOULD_WRITE_TAXONOMY_AUDIT = process.env['GRAPH_BUILD_TAXONOMY_AUDIT'] === '1';

const describeBaseline = describe;
const itZeroShot = SHOULD_RUN ? it : it.skip;

describeBaseline('product graph build gate', () => {
    let injector: EnvironmentInjector;
    let pipeline: GraphRebuildPipelineService;
    let graphRebuild: GraphRebuildService;
    let store: ReturnType<typeof createMemoryStore>;
    let runtime: ReturnType<typeof createRuntimeHarness>;
    let backend: ReturnType<typeof createBackendHarness>;

    beforeEach(() => {
        const text = readFileSync(SHORTRUN_PATH, 'utf8');
        harnessState.notes = [shortrunNote(text)];
        harnessState.occurrences = [];
        harnessState.entities = shortrunEntities();
        harnessState.nliJudgments = [];
        store = createMemoryStore();
        backend = createBackendHarness();
        runtime = createRuntimeHarness();
        injector = createEnvironmentInjector([
            GraphRebuildService,
            GraphRebuildPipelineService,
            { provide: AtlasCapabilityRuntimeService, useValue: runtime },
            { provide: NerService, useValue: createNerHarness() },
            { provide: PhoenixBackendService, useValue: backend },
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixUiApiService, useValue: createPhoenixUiApiHarness() },
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        pipeline = runInInjectionContext(injector, () => injector.get(GraphRebuildPipelineService));
        graphRebuild = runInInjectionContext(injector, () => injector.get(GraphRebuildService));
    });

    afterEach(async () => {
        await flushReceiptPersistence(pipeline);
        injector.destroy();
        vi.clearAllMocks();
    });

    itZeroShot('writes the shortrun zero-shot graph build report', async () => {
        backend.target = 'native';
        const request = graphRunRequest();
        const started = performance.now();
        const graph = await pipeline.buildGraph(request);
        const wallMs = elapsed(started);
        const report = buildZeroShotReport({
            request,
            graph,
            wallMs,
            store,
            runtime,
            backend,
        });

        mkdirSync(dirname(ZEROSHOT_OUTPUT_PATH), { recursive: true });
        writeFileSync(ZEROSHOT_OUTPUT_PATH, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
        writeTaxonomyAuditReport(report);
        console.log(`[graph-build-baseline] wrote ${ZEROSHOT_OUTPUT_PATH}`);
        console.log(`[graph-build-baseline] zeroShotWallMs=${report.totals.wallMs} nodes=${report.finalSnapshot.counters.nodes} edges=${report.finalSnapshot.counters.edges} targets=${report.finalSnapshot.counters.embeddingTargets} vectors=${report.finalSnapshot.counters.embeddingVectors}`);

        expect(graph.receipt.id).toContain('graph-atlas:');
        expect(graph.receipt.postProcessMode).toBe('full');
        expect(report.finalSnapshot.counters.nodes).toBeGreaterThan(0);
        expect(report.finalSnapshot.counters.embeddingTargets).toBeGreaterThan(0);
        expect(report.modelCalls.capabilityCalls).not.toContain('semanticAtlas');
        expect(report.finalSnapshot.counters.embeddingVectors).toBe(0);
        expect(report.totals.scopedDocumentUpserts).toBeLessThanOrEqual(12);
        expectChunkBridgeGolden(report.finalSnapshot.chunkSemanticBridges);
        expect(report.finalSnapshot.chunkSemanticBridges.falsePositiveAudit.sameEntityOnlySuspectCount).toBe(0);
        if (SHOULD_WRITE_TAXONOMY_AUDIT) {
            expect(report.finalSnapshot.atlasPacket?.objectCount).toBeGreaterThan(0);
            expect(report.finalSnapshot.atlasPacket?.targetCount).toBeGreaterThan(0);
            expect(report.finalSnapshot.taxonomyAudit?.warnings).toEqual([]);
        } else {
            expect(report.finalSnapshot.buildTimings.snapshotPayloadChars).toBeLessThan(100_000);
            expect(report.finalSnapshot.buildTimings.snapshotPayloadBreakdown.snapshotContentBlobDocuments)
                .toBeGreaterThan(0);
            expect(report.finalSnapshot.buildTimings.snapshotPayloadBreakdown.payloadEmbeddingTargetsChars)
                .toBe(JSON.stringify([]).length);
        }
    }, SHOULD_WRITE_TAXONOMY_AUDIT ? 180_000 : 30_000);

    it('gates product buildGraph warm interactive latency and write count', async () => {
        backend.target = 'native';
        const text = productGateText();
        const chunks = buildAdaptiveGraphRebuildChunks('shortrun', text);
        harnessState.notes = [shortrunNote(text)];
        harnessState.entities = productGateEntities();
        harnessState.occurrences = productGateOccurrences(415, 16, 2, chunks.map((chunk) => chunk.id));
        harnessState.nliJudgments = productGateNliJudgments(text, chunks);
        const request = { ...graphRunRequest(), durabilityMode: 'interactive' as const };
        const chars = harnessState.notes[0]?.markdownContent.length || 0;
        expect(chars).toBeGreaterThanOrEqual(24_000);
        expect(chars).toBeLessThanOrEqual(26_000);
        const cold = await pipeline.buildGraph(request);
        await flushReceiptPersistence(pipeline);
        const upsertsBeforeWarm = store.upserts.length;
        const operatorJournalReadsBeforeWarm = operatorJournalReadCount(store);
        const started = performance.now();
        const warm = await pipeline.buildGraph(request);
        const warmWallMs = elapsed(started);
        const warmScopedWrites = store.upserts.length - upsertsBeforeWarm;
        const warmOperatorJournalReads = operatorJournalReadCount(store) - operatorJournalReadsBeforeWarm;
        await flushReceiptPersistence(pipeline);
        const warmScopedWritesAfterReceipt = store.upserts.length - upsertsBeforeWarm;
        const parity = productGatePacketParity(warm.snapshot);
        const keys = ['mentions', 'acceptedAnchors', 'nodes', 'edges', 'embeddingTargets'] as const;
        for (const key of keys) expect(warm.snapshot.counters[key]).toBe(cold.snapshot.counters[key]);
        expect(warm.snapshot.id).toBe(cold.snapshot.id);
        expect(warm.snapshot.authorityContract?.snapshotId).toBe(cold.snapshot.id);
        expect(warm.snapshot.counters.nodes).toBe(27);
        expect(warm.snapshot.counters.edges).toBe(233);
        expect(warm.snapshot.counters.embeddingTargets).toBe(666);
        expect(warm.snapshot.atlasPacket?.objects.length).toBe(cold.snapshot.atlasPacket?.objects.length);
        expect(warm.snapshot.atlasPacket?.manifoldTargets.length)
            .toBe(cold.snapshot.atlasPacket?.manifoldTargets.length);
        expect(warm.snapshot.atlasPacket?.sourceContract.authority).toBe('rust-atlas-packet');
        expect(warm.snapshot.atlasPacket?.sourceContract.authority).not.toContain('typescript');
        expect(warm.snapshot.buildTimings?.nativeCompilerSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.snapshotReusedContentBlobs).toBe(0);
        expect(warm.snapshot.buildTimings?.snapshotWrittenContentBlobs).toBe(0);
        expect(warm.snapshot.buildTimings?.snapshotContentBlobReads).toBe(0);
        expect(warm.snapshot.buildTimings?.snapshotContentBlobManifestTrusted).toBe(0);
        expect(warm.snapshot.buildTimings?.snapshotPrimaryIdentityReused).toBe(1);
        expect(warm.snapshot.buildTimings?.snapshotPrimaryWriteSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.snapshotStoreDocuments).toBe(0);
        expect(warm.snapshot.buildTimings?.previousSnapshotHydrationSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.nativeChunkerSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.documentSemanticSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.nativeMemoryGovernanceRetrievalExperimentCandidates).toBe(0);
        expect(warm.snapshot.buildTimings?.nativeMemoryGovernanceRetrievalExperimentSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.nativeGraphRunReusedSections).toBe(7);
        expect(warm.snapshot.buildTimings?.nativeGraphRunChangedSections).toBe(0);
        expect(warm.snapshot.buildTimings?.nativeGraphRunEncodedSections).toBe(0);
        expect(warm.snapshot.buildTimings?.nativeGraphRunCompressedSections).toBe(0);
        expect(parity).toMatchObject({
            graphDiscourse: expect.any(Number),
            graphProposed: expect.any(Number),
            embedDiscourse: expect.any(Number),
            embedProposed: expect.any(Number),
        });
        expect(parity.graphDiscourse).toBeGreaterThan(0);
        expect(parity.graphProposed).toBeGreaterThan(0);
        expect(parity.embedDiscourse).toBeGreaterThan(0);
        expect(parity.embedProposed).toBeGreaterThan(0);
        expect(warmScopedWrites).toBe(0);
        expect(warmScopedWritesAfterReceipt).toBe(1);
        expect(warmOperatorJournalReads).toBe(0);
        expect(warmWallMs).toBeLessThanOrEqual(1_000);
        expect(warm.receipt.layerReceipts.map((layer) => layer.id)).toEqual(expect.arrayContaining([
            'input-signals',
            'snapshot-truth',
            'native-atlas-packet',
            'authority-seal',
            'persistence-payload',
            'projection-lenses',
            'diagnostic-ledgers',
            'transport-boundary',
            'ui-commit',
        ]));
        expect(warm.receipt.layerReceipts.every((layer) =>
            layer.owner && layer.source && layer.message && Array.isArray(layer.consumes) && Array.isArray(layer.produces),
        )).toBe(true);
        expect(warm.receipt.layerReceipts.find((layer) => layer.id === 'authority-seal')?.contentHash)
            .toBe(warm.snapshot.authorityContract?.contentHash);
        expect(backend.commands.filter((row) => row.command === 'graphRebuild:compileDualWrite').length)
            .toBe(0);
        expect(backend.snapshotAnalyses).toHaveLength(1);
        expect(backend.persistGraphRun).toHaveBeenCalledTimes(2);
        expect(backend.closeGraphRun).toHaveBeenCalledTimes(0);
        expect(backend.commands.filter((row) => row.command === 'graphRebuild:analyzeSnapshot'))
            .toHaveLength(0);
        expect(backend.commands.filter((row) => [
            'graphRebuild:chunkSemanticBridges',
            'graphRebuild:storyContinuity',
            'graphRebuild:memoryGovernance',
            'graphRebuild:memoryGovernanceRetrievalExperiment',
            'graphPromotion:verdictCertificate',
        ].includes(row.command))).toHaveLength(0);
        expect(store.upsertScopedDocuments).toHaveBeenCalledTimes(1);
        console.log(`[graph-product-gate] warmMs=${warmWallMs} scopedWrites=${warmScopedWrites} receiptWritesAfterReturn=${warmScopedWritesAfterReceipt} operatorJournalReads=${warmOperatorJournalReads} blobsWritten=${warm.snapshot.buildTimings?.snapshotWrittenContentBlobs || 0} nodes=${warm.snapshot.counters.nodes} edges=${warm.snapshot.counters.edges} targets=${warm.snapshot.counters.embeddingTargets}`);
    }, 30_000);

    it('keeps post-commit diagnostics from replacing the interactive snapshot', async () => {
        const text = 'Ryan entered New Rome. Ryan remembered the Allied Table before dawn.';
        harnessState.notes = [shortrunNote(text)];
        harnessState.entities = shortrunEntities();
        harnessState.occurrences = [];
        const buildRequest = {
            scopeKind: 'note' as const,
            scopeId: 'note:shortrun',
            noteIds: ['shortrun'],
            noteTexts: { shortrun: text },
            chunks: buildAdaptiveGraphRebuildChunks('shortrun', text),
            entities: harnessState.entities,
            postProcessMode: 'full' as const,
        };

        const firstInteractive = await graphRebuild.buildAndPersistSnapshot({
            ...buildRequest,
            durabilityMode: 'interactive',
        });
        const firstInteractiveRunSerial = graphRebuild.currentSnapshotRunSerial();
        const diagnostic = await graphRebuild.buildAndPersistSnapshot({
            ...buildRequest,
            durabilityMode: 'diagnostic',
            diagnosticBaseSnapshotId: firstInteractive.id,
            diagnosticBaseSnapshotRunSerial: firstInteractiveRunSerial,
        });

        expect(diagnostic.id).not.toBe(firstInteractive.id);
        expect(graphRebuild.snapshot()?.id).toBe(firstInteractive.id);
        expect(persistedSnapshotId(store, 'snapshot')).toBe(firstInteractive.id);
        expect(persistedSnapshotId(store, DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY)).toBe(diagnostic.id);

        await new Promise((resolve) => setTimeout(resolve, 2));
        const secondInteractive = await graphRebuild.buildAndPersistSnapshot({
            ...buildRequest,
            durabilityMode: 'interactive',
        });
        const diagnosticIdBeforeStaleRun = persistedSnapshotId(store, DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY);
        await graphRebuild.buildAndPersistSnapshot({
            ...buildRequest,
            durabilityMode: 'diagnostic',
            diagnosticBaseSnapshotId: firstInteractive.id,
            diagnosticBaseSnapshotRunSerial: firstInteractiveRunSerial,
        });

        expect(graphRebuild.snapshot()?.id).toBe(secondInteractive.id);
        expect(persistedSnapshotId(store, 'snapshot')).toBe(secondInteractive.id);
        expect(persistedSnapshotId(store, DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY)).toBe(diagnosticIdBeforeStaleRun);
    }, 30_000);

    it('fails closed when the native snapshot analysis boundary is unavailable', async () => {
        const text = 'Kai approved Hazel near Red Mesa. Hazel opposed Kai before dawn.';
        backend.target = 'native';
        backend.unsupportedCommands.add('graphRebuild:analyzeSnapshot');
        harnessState.notes = [shortrunNote(text)];
        harnessState.entities = shortrunEntities();
        harnessState.occurrences = [];
        await expect(graphRebuild.buildAndPersistSnapshot({
            scopeKind: 'note',
            scopeId: 'note:shortrun',
            noteIds: ['shortrun'],
            noteTexts: { shortrun: text },
            chunks: buildAdaptiveGraphRebuildChunks('shortrun', text),
            entities: harnessState.entities,
            postProcessMode: 'full',
            durabilityMode: 'interactive',
        })).rejects.toThrow('unsupported store command: graphRebuild:analyzeSnapshot');

        expect(backend.snapshotAnalyses).toHaveLength(1);
        expect(backend.commands.map((row) => row.command)).not.toContain('graphRebuild:analyzeSnapshot');
        expect(backend.commands.filter((row) => [
            'graphRebuild:chunkSemanticBridges',
            'graphRebuild:storyContinuity',
            'graphRebuild:memoryGovernance',
            'graphRebuild:memoryGovernanceRetrievalExperiment',
            'graphPromotion:verdictCertificate',
        ].includes(row.command))).toHaveLength(0);
    }, 30_000);
});

function persistedSnapshotId(
    store: ReturnType<typeof createMemoryStore>,
    documentKey: string,
): string | undefined {
    const document = store.documents.get(scopedDocumentKey('note:shortrun', GRAPH_REBUILD_NAMESPACE, documentKey));
    return document ? scopedDocumentToGraphRebuildSnapshot(document)?.id : undefined;
}

function operatorJournalReadCount(store: ReturnType<typeof createMemoryStore>): number {
    return store.reads.filter((row) => row.key.endsWith('/operator-mutation-journal')).length;
}

function productGatePacketParity(snapshot: GraphRebuildSnapshot): {
    graphDiscourse: number;
    graphProposed: number;
    embedDiscourse: number;
    embedProposed: number;
} {
    if (!snapshot.atlasPacket) {
        return { graphDiscourse: 0, graphProposed: 0, embedDiscourse: 0, embedProposed: 0 };
    }
    const rows = buildGraphPacketRowAdapter(snapshot.atlasPacket, snapshot.embeddingTargets);
    return {
        graphDiscourse: rows.graphNodes.filter((node) => node.metadata?.['canvasLens'] === 'discourse').length,
        graphProposed: rows.graphNodes.filter((node) => node.metadata?.['reviewState'] === 'proposed').length,
        embedDiscourse: rows.embeddingTargets.filter((target) => target.atlasFamily === 'discourse').length,
        embedProposed: rows.embeddingTargets.filter((target) =>
            target.atlasStatus === 'review'
            || target.atlasStatus === 'proposed'
            || target.admissionStatus !== 'admitted',
        ).length,
    };
}

function graphRunRequest(): GraphIndexRunRequest {
    return {
        scope: {
            kind: 'note',
            scopeId: 'note:shortrun',
            label: 'Shortrun',
            noteIds: ['shortrun'],
        },
        policy: 'force',
        modelSelection: {
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'jina-v5-nano',
            embeddingModelLabel: 'Jina v5 Nano',
            embeddingDimensionLabel: '768d',
            nliModelId: 'modernbert-nli',
        },
        embeddingStagePolicy: { entityLinkerEnabled: true },
        entities: harnessState.entities,
    };
}

function buildZeroShotReport(input: {
    request: GraphIndexRunRequest;
    graph: { receipt: GraphIndexRunReceipt; snapshot: GraphRebuildSnapshot };
    wallMs: number;
    store: ReturnType<typeof createMemoryStore>;
    runtime: ReturnType<typeof createRuntimeHarness>;
    backend: ReturnType<typeof createBackendHarness>;
}) {
    const text = harnessState.notes[0]?.markdownContent || '';
    const run = runReport('zeroShot', input.graph.receipt, input.graph.snapshot, input.wallMs);
    const finalSnapshot = snapshotReport(input.graph.snapshot);
    return {
        schemaVersion: 'phoenix-graph-build-baseline/v1',
        scenario: 'zero-shot-build-graph-shortrun',
        generatedAt: new Date().toISOString(),
        fixture: {
            path: 'docs/shortrun.md',
            noteId: 'shortrun',
            scopeId: input.request.scope.scopeId,
            chars: text.length,
            words: text.split(/\s+/).filter(Boolean).length,
            lines: text.split(/\r?\n/).length,
            entitySeeds: harnessState.entities.length,
        },
        contract: {
            buildShape: 'zero-shot',
            stages: ['buildGraph'],
            graphModelsRequiredByHarness: ['dynamicNer', 'nli'],
            semanticEmbeddingUsedForGraphBuild: false,
            intermediateCoreSnapshotPersisted: false,
        },
        modelCalls: {
            readinessChecks: input.runtime.readinessChecks,
            warmCalls: input.runtime.warmCalls,
            capabilityCalls: input.runtime.capabilityCalls,
            semanticAtlasInvoked: input.runtime.capabilityCalls.includes('semanticAtlas'),
        },
        persistence: {
            upserts: input.store.upserts,
            reads: input.store.reads,
            pausedSnapshots: input.store.pausedSnapshots,
            resumedSnapshots: input.store.resumedSnapshots,
        },
        backendCommands: input.backend.commands,
        runs: [run],
        totals: {
            wallMs: round(input.wallMs),
            receiptStages: run.receipt.stageCount,
            scopedDocumentUpserts: input.store.upserts.length,
            backendCommands: input.backend.commands.length,
        },
        finalSnapshot,
    };
}

function runReport(
    name: 'zeroShot',
    receipt: GraphIndexRunReceipt,
    snapshot: GraphRebuildSnapshot,
    wallMs: number,
) {
    return {
        name,
        wallMs: round(wallMs),
        receipt: {
            id: receipt.id,
            status: receipt.status,
            policy: receipt.policy,
            postProcessMode: receipt.postProcessMode,
            durationMs: receipt.durationMs,
            stageCount: receipt.stageReceipts.length,
            projectionCount: receipt.projectionReceipts.length,
            modelReadiness: receipt.modelReadiness.map((model) => ({
                id: model.id,
                status: model.status,
                optional: Boolean(model.optional),
            })),
            layers: receipt.layerReceipts.map((layer) => ({
                id: layer.id,
                kind: layer.kind,
                status: layer.status,
                owner: layer.owner,
                source: layer.source,
                consumes: layer.consumes,
                produces: layer.produces,
                stageIds: layer.stageIds,
                projectionModes: layer.projectionModes || [],
                authority: layer.authority || '',
                contentHash: layer.contentHash || '',
                counters: layer.counters,
                message: layer.message,
            })),
            stages: receipt.stageReceipts.map(stageReport),
            projections: receipt.projectionReceipts.map((projection) => ({
                mode: projection.mode,
                status: projection.status,
                targetCount: projection.targetCount,
                vectorCount: projection.vectorCount,
                counters: projection.counters || {},
            })),
        },
        snapshot: snapshotReport(snapshot),
    };
}

function writeTaxonomyAuditReport(report: ReturnType<typeof buildZeroShotReport>) {
    if (!SHOULD_WRITE_TAXONOMY_AUDIT || !report.finalSnapshot.taxonomyAudit) return;
    mkdirSync(dirname(TAXONOMY_AUDIT_OUTPUT_PATH), { recursive: true });
    writeFileSync(TAXONOMY_AUDIT_OUTPUT_PATH, `${JSON.stringify({
        schemaVersion: 'phoenix-atlas-taxonomy-audit-run/v1',
        scenario: report.scenario,
        generatedAt: report.generatedAt,
        fixture: report.fixture,
        finalSnapshot: {
            id: report.finalSnapshot.id,
            scopeId: report.finalSnapshot.scopeId,
            builtAt: report.finalSnapshot.builtAt,
            counters: report.finalSnapshot.counters,
        },
        taxonomyAudit: report.finalSnapshot.taxonomyAudit,
    }, null, 2)}\n`, 'utf8');
    console.log(`[graph-taxonomy-audit] wrote ${TAXONOMY_AUDIT_OUTPUT_PATH}`);
}

function stageReport(stage: GraphIndexStageReceipt) {
    return {
        id: stage.id,
        label: stage.label,
        status: stage.status,
        durationMs: stage.durationMs,
        outputCount: stage.outputCount,
        counters: stage.counters,
        message: stage.message,
    };
}

function snapshotReport(snapshot: GraphRebuildSnapshot) {
    return {
        id: snapshot.id,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        counters: pickCounters(snapshot.counters),
        buildTimings: snapshot.buildTimings || {},
        chunkSemanticBridges: chunkSemanticBridgeReport(snapshot),
        episodeConnections: episodeConnectionReport(snapshot),
        atlasPacket: snapshot.atlasPacket
            ? {
                scopeId: snapshot.atlasPacket.scopeId,
                snapshotId: snapshot.atlasPacket.snapshotId,
                objectCount: snapshot.atlasPacket.objects?.length || 0,
                targetCount: snapshot.atlasPacket.manifoldTargets?.length || 0,
                vectorContract: snapshot.atlasPacket.vectorContract,
            }
            : null,
        taxonomyAudit: SHOULD_WRITE_TAXONOMY_AUDIT
            ? buildGraphAtlasTaxonomyAudit(snapshot)
            : undefined,
    };
}

function pickCounters(counters: GraphRebuildCounters): Record<string, number> {
    const keys: Array<keyof GraphRebuildCounters> = [
        'entities',
        'candidates',
        'mentions',
        'acceptedAnchors',
        'chunks',
        'relationshipCandidates',
        'relationships',
        'acceptedRelationships',
        'reviewRelationships',
        'events',
        'episodes',
        'chunkSemanticBridges',
        'chunkSetupPayoffBridges',
        'chunkCauseEffectBridges',
        'chunkStateDeltaBridges',
        'chunkRelationshipDeltaBridges',
        'chunkTopicContinuationBridges',
        'chunkEvidenceReframeBridges',
        'chunkMotifEchoBridges',
        'chunkRouteContinuityBridges',
        'episodeConnections',
        'episodeTemporalConnections',
        'episodeCausalConnections',
        'episodeWormholeConnections',
        'temporalEdges',
        'causalEdges',
        'memoryState',
        'embeddingTargets',
        'embeddingQueuedTargets',
        'embeddingTargetDeferred',
        'embeddingVectors',
        'nodes',
        'edges',
        'graphAwareLinkSuggestions',
        'entityLinkSuggestions',
    ];
    return Object.fromEntries(keys.map((key) => [key, Number(counters[key] || 0)]));
}

function chunkSemanticBridgeReport(snapshot: GraphRebuildSnapshot) {
    const chunks = new Map((snapshot.chunks || []).map((chunk) => [chunk.id, chunk]));
    const entityLabels = new Map((snapshot.nodes || []).map((node) => [node.entityId, node.label]));
    const byType = new Map<string, number>();
    for (const bridge of snapshot.chunkSemanticBridges || []) {
        byType.set(bridge.bridgeType, (byType.get(bridge.bridgeType) || 0) + 1);
    }
    return {
        schemaVersion: GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
        commitPolicy: GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
        noTopologyCommitGuard: GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT,
        contract: {
            requiredFields: [
                'schemaVersion',
                'id',
                'bridgeType',
                'sourceChunkId',
                'targetChunkId',
                'claim',
                'evidenceIds',
                'supportingEntityIds',
                'confidence',
                'status',
                'commitPolicy',
                'semanticVerbs',
                'rationale',
            ],
            optionalFields: ['sourceEventId', 'targetEventId', 'sourceEpisodeId', 'targetEpisodeId', 'sourceCue', 'targetCue'],
            candidateOnly: true,
        },
        total: snapshot.chunkSemanticBridges?.length || 0,
        byType: Object.fromEntries([...byType.entries()].sort(([left], [right]) => left.localeCompare(right))),
        falsePositiveAudit: auditChunkSemanticBridgeFalsePositives(snapshot.chunkSemanticBridges || []),
        samples: sampleChunkSemanticBridges(snapshot.chunkSemanticBridges || []).map((bridge) => ({
            schemaVersion: bridge.schemaVersion,
            id: bridge.id,
            bridgeType: bridge.bridgeType,
            status: bridge.status,
            commitPolicy: bridge.commitPolicy,
            confidence: Number(bridge.confidence.toFixed(3)),
            sourceChunkId: bridge.sourceChunkId,
            sourceChunkLabel: chunkLabel(chunks.get(bridge.sourceChunkId)),
            targetChunkId: bridge.targetChunkId,
            targetChunkLabel: chunkLabel(chunks.get(bridge.targetChunkId)),
            sourceEventId: bridge.sourceEventId,
            targetEventId: bridge.targetEventId,
            sourceEpisodeId: bridge.sourceEpisodeId,
            targetEpisodeId: bridge.targetEpisodeId,
            claim: bridge.claim,
            semanticVerbs: bridge.semanticVerbs,
            sourceCue: bridge.sourceCue,
            targetCue: bridge.targetCue,
            supportingEntityIds: bridge.supportingEntityIds,
            supportingEntityLabels: bridge.supportingEntityIds.map((entityId) => entityLabels.get(entityId) || entityId),
            evidenceIds: bridge.evidenceIds.slice(0, 8),
            rationale: bridge.rationale,
        })),
    };
}

function sampleChunkSemanticBridges(
    bridges: NonNullable<GraphRebuildSnapshot['chunkSemanticBridges']>,
) {
    const byType = new Map<string, typeof bridges>();
    for (const bridge of bridges) {
        byType.set(bridge.bridgeType, [...(byType.get(bridge.bridgeType) || []), bridge]);
    }
    const out: typeof bridges = [];
    for (const rows of [...byType.entries()].sort(([left], [right]) => left.localeCompare(right)).map((entry) => entry[1])) {
        out.push(...rows.slice(0, 4));
    }
    const seen = new Set(out.map((bridge) => bridge.id));
    for (const bridge of bridges) {
        if (out.length >= 32) break;
        if (seen.has(bridge.id)) continue;
        seen.add(bridge.id);
        out.push(bridge);
    }
    return out.slice(0, 32);
}

function expectChunkBridgeGolden(report: ReturnType<typeof chunkSemanticBridgeReport>) {
    const golden = JSON.parse(readFileSync(CHUNK_BRIDGE_GOLDEN_PATH, 'utf8'));
    expect(report.schemaVersion).toBe(golden.bridgeContract.schemaVersion);
    expect(report.commitPolicy).toBe(golden.bridgeContract.commitPolicy);
    expect(report.noTopologyCommitGuard).toBe(golden.bridgeContract.noTopologyCommitGuard);
    expect(report.total).toBe(golden.counts.total);
    expect(report.byType).toEqual(golden.counts.byType);
    for (const expected of golden.samples) {
        const actual = report.samples.find((sample) => sample.id === expected.id);
        expect(actual).toMatchObject(expected);
    }
}

function episodeConnectionReport(snapshot: GraphRebuildSnapshot) {
    const episodes = new Map((snapshot.episodes || []).map((episode) => [episode.id, episode]));
    const entityLabels = new Map((snapshot.nodes || []).map((node) => [node.entityId, node.label]));
    const byKind = new Map<string, number>();
    for (const connection of snapshot.episodeConnections || []) {
        byKind.set(connection.kind, (byKind.get(connection.kind) || 0) + 1);
    }
    return {
        total: snapshot.episodeConnections?.length || 0,
        byKind: Object.fromEntries([...byKind.entries()].sort(([left], [right]) => left.localeCompare(right))),
        episodes: (snapshot.episodes || []).map((episode) => ({
            id: episode.id,
            label: episode.label,
            eventCount: episode.eventIds.length,
            entityLabels: episode.entityIds.map((entityId) => entityLabels.get(entityId) || entityId).slice(0, 18),
        })),
        samples: (snapshot.episodeConnections || []).slice(0, 24).map((connection) => ({
            id: connection.id,
            kind: connection.kind,
            status: connection.status,
            relationType: connection.relationType,
            sourceEpisodeId: connection.sourceEpisodeId,
            sourceEpisodeLabel: episodes.get(connection.sourceEpisodeId)?.label || connection.sourceEpisodeId,
            targetEpisodeId: connection.targetEpisodeId,
            targetEpisodeLabel: episodes.get(connection.targetEpisodeId)?.label || connection.targetEpisodeId,
            confidence: Number(connection.confidence.toFixed(3)),
            eventEdgeCount: connection.eventEdgeIds.length,
            chunkBridgeIds: connection.chunkBridgeIds || [],
            bridgeType: connection.bridgeType,
            claim: connection.claim,
            semanticVerbs: connection.semanticVerbs || [],
            sharedEntityIds: connection.sharedEntityIds,
            sharedEntityLabels: connection.sharedEntityIds.map((entityId) => entityLabels.get(entityId) || entityId),
            evidenceIds: connection.evidenceIds.slice(0, 8),
            rationale: connection.rationale,
        })),
    };
}

function chunkLabel(chunk: GraphRebuildSnapshot['chunks'][number] | undefined): string {
    return chunk ? `Chunk ${chunk.ordinal + 1}` : '';
}

function shortrunNote(text: string) {
    return {
        id: 'shortrun',
        worldId: 'baseline-world',
        title: 'Shortrun',
        content: '',
        markdownContent: text,
        hasBody: true,
        folderId: '',
        entityKind: '',
        entitySubtype: '',
        isEntity: false,
        isPinned: false,
        favorite: false,
        ownerId: 'baseline',
        narrativeId: '',
        order: 0,
        createdAt: 1,
        updatedAt: 1,
        version: 1,
    };
}

function shortrunEntities(): RegisteredEntity[] {
    return [
        entity('entity-ryan', 'Ryan', 'CHARACTER', ['Quicksave']),
        entity('entity-new-rome', 'New Rome', 'LOCATION'),
        entity('entity-campania', 'Campania', 'LOCATION'),
        entity('entity-italy', 'Italy', 'LOCATION'),
        entity('entity-europe', 'Europe', 'LOCATION'),
        entity('entity-naples', 'Naples', 'LOCATION'),
        entity('entity-mediterranean-sea', 'Mediterranean Sea', 'LOCATION'),
        entity('entity-mechron', 'Mechron', 'CHARACTER'),
        entity('entity-genome-wars', 'Genome Wars', 'EVENT'),
        entity('entity-dynamis', 'Dynamis', 'FACTION'),
        entity('entity-dynamis-tower', 'Dynamis Tower', 'LOCATION'),
        entity('entity-golden-coast', 'Golden Coast', 'LOCATION'),
        entity('entity-wyvern', 'Wyvern', 'CHARACTER'),
        entity('entity-hercules-elixir', 'Hercules Elixir', 'ITEM'),
        entity('entity-renesco', 'Renesco', 'CHARACTER'),
        entity('entity-jolie-wrangler', 'Jolie Wrangler', 'LOCATION'),
        entity('entity-len', 'Len', 'CHARACTER'),
        entity('entity-rust-town', 'Rust Town', 'LOCATION'),
        entity('entity-junkyard', 'Junkyard', 'LOCATION'),
        entity('entity-psychos', 'Psychos', 'FACTION'),
        entity('entity-adam', 'Adam', 'CHARACTER'),
        entity('entity-private-security', 'Private Security', 'FACTION'),
        entity('entity-augusti', 'Augusti', 'FACTION'),
        entity('entity-plymouth-fury', 'Plymouth Fury', 'ITEM'),
        entity('entity-bliss', 'Bliss', 'ITEM'),
    ];
}

function productGateText(): string {
    const paragraphs = Array.from({ length: 16 }, (_, index) =>
        `section ${index}\n${'x '.repeat(780).trim()}`,
    );
    return paragraphs.join('\n\n').slice(0, 24_999).padEnd(24_999, 'x');
}

function productGateEntities(): RegisteredEntity[] {
    return Array.from({ length: 27 }, (_, index) =>
        entity(`entity-${index}`, `Entity ${index}`, 'CHARACTER'),
    );
}

function productGateOccurrences(
    count: number,
    seed: number,
    randomChunks: number,
    chunkIds: string[],
): any[] {
    let state = seed >>> 0;
    const next = () => {
        state = (state * 1664525 + 1013904223) >>> 0;
        return state / 0x100000000;
    };
    const rows: any[] = [];
    let ordinal = 0;
    for (let chunkIndex = 0; chunkIndex < chunkIds.length; chunkIndex += 1) {
        const chunkCount = Math.floor(count / chunkIds.length) + (chunkIndex < count % chunkIds.length ? 1 : 0);
        const sequence = chunkIndex < randomChunks
            ? Array.from({ length: chunkCount }, () => Math.floor(next() * 27))
            : Array.from({ length: chunkCount }, (_, local) => (local + chunkIndex) % 27);
        for (const entityIndex of sequence) {
            const start = ordinal * 3;
            rows.push({
                id: `product-gate-occ:${ordinal}`,
                noteId: 'shortrun',
                entityId: `entity-${entityIndex}`,
                entityLabel: `Entity ${entityIndex}`,
                entityKind: 'CHARACTER',
                sourceStart: start,
                sourceEnd: start + 1,
                surface: `S${entityIndex}`,
                source: 'persisted',
                confidence: 0.9,
                excerpt: `S${entityIndex}`,
                generation: 1,
                createdAt: 1,
                updatedAt: 1,
                chunkId: chunkIds[chunkIndex],
            });
            ordinal += 1;
        }
    }
    return rows;
}

function productGateNliJudgments(text: string, chunks: ReturnType<typeof buildAdaptiveGraphRebuildChunks>): any[] {
    const snapshot = buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:shortrun',
        noteIds: ['shortrun'],
        entities: productGateEntities(),
        occurrences: productGateOccurrences(415, 16, 2, chunks.map((chunk) => chunk.id)),
        chunks,
        noteTexts: { shortrun: text },
        postProcessMode: 'full',
        durabilityMode: 'interactive',
        embeddingStagePolicy: { entityLinkerEnabled: true },
        builtAt: 1,
    });
    return snapshot.relationships.slice(0, 21).map((relationship, index) => ({
        judgmentId: `product-gate-nli-${index}`,
        sourceId: relationship.sourceEntityId,
        targetId: relationship.targetEntityId,
        edgeType: 'supports',
        nliVote: {
            source: 'modernBertNli',
            role: 'canonFactAdjudication',
            decision: 'supported',
            confidenceMillis: 950,
            entailmentMillis: 950,
            contradictionMillis: 20,
            neutralMillis: 30,
        },
        classificationVote: {
            source: 'gliclass',
            role: 'relationFrameClassification',
            label: 'supports',
            scoreMillis: 900,
        },
    }));
}

function entity(id: string, label: string, kind: EntityKind, aliases: string[] = []): RegisteredEntity {
    return {
        id,
        label,
        aliases,
        kind,
        firstNote: 'shortrun',
        noteId: 'shortrun',
        mentionsByNote: new Map([['shortrun', 1]]),
        totalMentions: 1,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        attributes: {},
        registeredAt: 1,
    };
}

function createNerHarness() {
    const suggestions = signal<any[]>([]);
    const suggestionsForText = (plainText: string) => {
        const lower = plainText.toLocaleLowerCase();
        return harnessState.entities
            .filter((entity) => [entity.label, ...(entity.aliases || [])]
                .some((surface) => lower.includes(String(surface).toLocaleLowerCase())))
            .map((entity) => ({
                id: `suggestion:${entity.id}`,
                entityId: entity.id,
                label: entity.label,
                kind: entity.kind,
                confidence: 0.91,
                source: 'dynamic_ner',
            }));
    };
    return {
        suggestions: computed(() => suggestions()),
        runDynamicScan: vi.fn(async (input: { plainText: string }) => {
            suggestions.set(suggestionsForText(input.plainText));
        }),
        scanDynamicBatch: vi.fn(async (requests: Array<{ plainText: string }>) =>
            requests.map((request) => suggestionsForText(request.plainText))),
        applyDynamicScanResult: vi.fn(async (_request: unknown, result: any[]) => {
            suggestions.set(result);
        }),
        acceptSuggestionForContext: vi.fn(async (id: string) => {
            suggestions.set(suggestions().filter((suggestion) => suggestion.id !== id));
            return true;
        }),
    };
}

function createRuntimeHarness() {
    const readinessChecks: string[] = [];
    const warmCalls: string[] = [];
    const capabilityCalls: string[] = [];
    return {
        readinessChecks,
        warmCalls,
        capabilityCalls,
        capabilityState: vi.fn((capability: string) => {
            readinessChecks.push(capability);
            return {
                requiredModels: [{
                    id: capability === 'semanticAtlas' ? 'semanticEmbedding' : capability === 'nliAdjudication' ? 'nli' : 'dynamicNer',
                    readiness: 'ready',
                    statusLabel: 'ready',
                }],
            };
        }),
        warmModelLane: vi.fn(async (lane: string) => {
            warmCalls.push(lane);
        }),
        runCapability: vi.fn(async (capability: string) => {
            capabilityCalls.push(capability);
            return { rawResult: rawCapabilityResult(capability) };
        }),
    };
}

function rawCapabilityResult(capability: string) {
    if (capability === 'nliAdjudication') {
        const judgments = harnessState.nliJudgments.length
            ? harnessState.nliJudgments
            : [{
                judgmentId: 'baseline-nli-1',
                sourceId: 'entity-ryan',
                targetId: 'entity-new-rome',
                edgeType: 'co_occurs_with',
                nliVote: {
                    source: 'modernBertNli',
                    role: 'canonFactAdjudication',
                    decision: 'supported',
                    confidenceMillis: 900,
                    entailmentMillis: 900,
                    contradictionMillis: 30,
                    neutralMillis: 70,
                },
                classificationVote: {
                    source: 'gliclass',
                    role: 'relationFrameClassification',
                    label: 'co_occurs_with',
                    scoreMillis: 820,
                },
            }];
        return {
            inputCount: judgments.length,
            plannedInputCount: judgments.length,
            duplicateInputCount: 0,
            resultCount: judgments.length,
            stageSummaries: [
                { stage: 'candidatePlan', status: 'completed', durationMs: 1, counts: { rawInputs: judgments.length, validInputs: judgments.length, plannedInputs: judgments.length, duplicateInputs: 0, uniquePairs: judgments.length } },
                { stage: 'classification', status: 'completed', durationMs: 1, counts: { plannedInputs: judgments.length, results: judgments.length, batches: 1, entailment: judgments.length } },
                { stage: 'apply', status: 'completed', durationMs: 1, counts: { results: judgments.length, appliedRows: judgments.length } },
            ],
            judgments,
        };
    }
    return {
        stageSummaries: [{
            stage: capability,
            status: 'completed',
            durationMs: 1,
            counts: { rows: 1, plannedModelCalls: 0 },
        }],
        rows: 1,
        plannedModelCalls: 0,
    };
}

function createMemoryStore() {
    const documents = new Map<string, StoreScopedDocument>();
    const upserts: Array<{ key: string; payloadChars: number }> = [];
    const reads: Array<{ key: string; hit: boolean }> = [];
    const store = {
        documents,
        upserts,
        reads,
        pausedSnapshots: 0,
        resumedSnapshots: 0,
        pauseSnapshots: vi.fn(() => {
            store.pausedSnapshots += 1;
        }),
        resumeSnapshots: vi.fn(() => {
            store.resumedSnapshots += 1;
        }),
        upsertScopedDocument: vi.fn(async (document: StoreScopedDocument): Promise<PhoenixContentMutationTiming> => {
            const key = scopedDocumentKey(document.scopeFolderId, document.namespace, document.documentKey);
            documents.set(key, document);
            upserts.push({ key, payloadChars: document.payload.length });
            return {
                records: 1,
                noteMutations: 0,
                relationUpserts: 0,
                relationDeletes: 0,
                scopedDocumentUpserts: 1,
                payloadChars: document.payload.length,
                serializedWaitMs: 0,
                appendWalMs: 0,
                manifestCommitMs: 0,
                runtimeApplyMs: 0,
                runtimeReloadMs: 0,
                totalMs: 0,
                checkpointScheduled: 0,
                runtimeReloaded: 0,
            };
        }),
        upsertScopedDocuments: vi.fn(async (batch: StoreScopedDocument[]): Promise<PhoenixContentMutationTiming> => {
            for (const document of batch) {
                const key = scopedDocumentKey(document.scopeFolderId, document.namespace, document.documentKey);
                documents.set(key, document);
                upserts.push({ key, payloadChars: document.payload.length });
            }
            return {
                records: batch.length, noteMutations: 0, relationUpserts: batch.length, relationDeletes: 0,
                scopedDocumentUpserts: batch.length, payloadChars: batch.reduce((sum, row) => sum + row.payload.length, 0),
                serializedWaitMs: 0, appendWalMs: 0, manifestCommitMs: 0, runtimeApplyMs: 0,
                runtimeReloadMs: 0, totalMs: 0, checkpointScheduled: 0, runtimeReloaded: 0,
            };
        }),
        getScopedDocument: vi.fn(async (scopeId: string, namespace: string, documentKey: string) => {
            const key = scopedDocumentKey(scopeId, namespace, documentKey);
            const document = documents.get(key);
            reads.push({ key, hit: Boolean(document) });
            return document || null;
        }),
    };
    return store;
}

function scopedDocumentKey(scopeId: string, namespace: string, documentKey: string): string {
    return `${scopeId}/${namespace}/${documentKey}`;
}

function createBackendHarness() {
    const commands: Array<{ command: string; payload: unknown; requestChars: number }> = [];
    const snapshotAnalyses: unknown[] = [];
    const unsupportedCommands = new Set<string>();
    let latestNativeSnapshot: { id: string; scopeId: string } | null = null;
    return {
        commands,
        snapshotAnalyses,
        unsupportedCommands,
        target: SHOULD_WRITE_TAXONOMY_AUDIT ? 'native' : 'web',
        analyzeGraphSnapshot: vi.fn(async (payload: unknown) => {
            snapshotAnalyses.push(payload);
            const snapshot = (payload as { snapshot?: { id?: string; scopeId?: string } }).snapshot;
            latestNativeSnapshot = {
                id: snapshot?.id || 'snapshot:test',
                scopeId: snapshot?.scopeId || 'scope:test',
            };
            if (unsupportedCommands.has('graphRebuild:analyzeSnapshot')) {
                throw new Error('unsupported store command: graphRebuild:analyzeSnapshot');
            }
            return emptyNativeGraphRunPage(payload);
        }),
        persistGraphRun: vi.fn(async (runHandle: string) => ({
            schemaVersion: 'phoenix-graph-run-durable-receipt/v1',
            runHandle,
            scopeId: latestNativeSnapshot?.scopeId || 'scope:test',
            snapshotId: latestNativeSnapshot?.id || 'snapshot:test',
            manifestId: 'b3:test',
            changedSections: 0,
            reusedSections: 7,
            encodedSections: 0,
            compressedSections: 0,
            rawBytesWritten: 0,
            compressedBytesWritten: 0,
        })),
        readGraphRunPage: vi.fn(async () => null),
        closeGraphRun: vi.fn(async () => true),
        storeCommand: vi.fn(async (command: string, payload: unknown) => {
            commands.push({ command, payload, requestChars: JSON.stringify(payload || {}).length });
            if (unsupportedCommands.has(command)) {
                throw new Error(`unsupported store command: ${command}`);
            }
            if (SHOULD_WRITE_TAXONOMY_AUDIT && command === 'graphRebuild:compileDualWrite') {
                return compileNativeAuditSidecar(payload);
            }
            if (command === 'graphRebuild:compileDualWrite') {
                const snapshot = (payload as { snapshot: GraphRebuildSnapshot }).snapshot;
                return { atlasPacket: {
                    schemaVersion: 'phoenix-atlas-packet/v1', snapshotId: snapshot.id,
                    scopeKind: snapshot.scopeKind, scopeId: snapshot.scopeId, builtAt: snapshot.builtAt,
                    sourceContract: { authority: 'rust-atlas-packet', identityAuthority: 'registry-entities-and-accepted-anchors', vectorContract: 'vectors-missing', tsGraphBuilderRole: 'native-atlas-packet-authority' },
                    objects: [], manifoldTargets: [],
                    counters: { objects: 0, manifoldTargets: 0, registryEntities: snapshot.nodes.length, evidenceAnchors: snapshot.entityAnchors.length, modelVectors: 0, families: [] },
                } };
            }
            return null;
        }),
    };
}

function emptyNativeSnapshotAnalysisOutput(payload: unknown): unknown {
    const request = payload as {
        snapshot?: { id?: string; builtAt?: number };
        documents?: Array<{ noteId?: string }>;
    };
    const sourceSnapshotId = request.snapshot?.id || 'snapshot:test';
    const sourceDocumentIds = (request.documents || [])
        .map((document) => document.noteId || '')
        .filter(Boolean);
    const continuityCounters = {
        events: 0,
        boundaryReceipts: 0,
        episodes: 0,
        temporalCandidates: 0,
        stateIntervals: 0,
        causalCandidates: 0,
        episodeConnections: 0,
        conflicts: 0,
        crossDocumentConnections: 0,
        reviewRequired: 0,
    };
    return {
        schemaVersion: 'phoenix-graph-snapshot-analysis-native-output/v1',
        source: 'rust',
        bridge: {
            schemaVersion: 'phoenix-chunk-semantic-bridge-native-output/v1',
            source: 'rust',
            candidates: [],
            crossDocumentCertificate: {
                schemaVersion: 'phoenix-cross-document-bridge-run-certificate/v1',
                sourceDocumentIds,
                generatedCandidates: 0,
                eligibleCandidates: 0,
                selectedCandidates: 0,
                rejectedCandidates: 0,
                pairCoverage: [],
                rejectionCounts: [],
                selectedRows: [],
                rejectedRows: [],
                weakestRows: [],
                noTopologyWrites: true,
                invariantReceipts: ['chunk_semantic_bridge_candidate:no_topology_commit'],
            },
            qualityGate: { total: 0, accepted: 0, demotedSameEntityOnly: 0 },
            timing: { bridgeBuildMicros: 0, totalMicros: 0 },
        },
        continuity: {
            schemaVersion: 'phoenix-story-continuity-native-output/v1',
            source: 'rust',
            contract: {
                schemaVersion: 'phoenix-story-continuity/v1',
                source: 'rust_story_continuity',
                sourceSnapshotId,
                generatedAt: request.snapshot?.builtAt || 0,
                commitPolicy: 'candidate_only',
                noTopologyCommit: true,
                events: [],
                boundaryReceipts: [],
                episodes: [],
                temporalCandidates: [],
                stateIntervals: [],
                causalCandidates: [],
                episodeConnections: [],
                conflicts: [],
                certificate: {
                    schemaVersion: 'phoenix-story-continuity-run-certificate/v1',
                    sourceSnapshotId,
                    sourceDocumentIds,
                    buildMicros: 0,
                    eventIdentityMicros: 0,
                    episodeBoundaryMicros: 0,
                    relationResolutionMicros: 0,
                    counters: continuityCounters,
                    noTopologyWrites: true,
                    allRowsEvidenced: true,
                    stableSourceIdentities: true,
                    fixedBatchingDetected: false,
                    invariantReceipts: [],
                },
            },
            timing: { continuityBuildMicros: 0, totalMicros: 0 },
        },
        governance: {
            schemaVersion: 'phoenix-memory-governance-native-output/v1',
            source: 'rust',
            candidates: [],
            timing: { governanceBuildMicros: 0, totalMicros: 0 },
        },
        retrieval: null,
        promotion: emptyNativePromotionVerdictOutput(),
        noTopologyWrites: true,
        timing: {
            bridgeBuildMicros: 0,
            continuityBuildMicros: 0,
            governanceBuildMicros: 0,
            retrievalBuildMicros: 0,
            verdictBuildMicros: 0,
            totalMicros: 0,
        },
    };
}

function emptyNativeGraphRunPage(payload: unknown): unknown {
    const snapshotId = (payload as { snapshot?: { id?: string } })?.snapshot?.id || 'test';
    return {
        schemaVersion: 'phoenix-graph-run-page/v1',
        source: 'rust',
        runHandle: `graph-run:${snapshotId}`,
        offset: 0,
        limit: 8,
        detailRows: 0,
        returnedDetailRows: 0,
        nextOffset: null,
        arena: {
            analysisIdentity: 'b3-test-analysis',
            reused: false,
            residentBytes: 4096,
            activeLeases: 1,
            projectionMicros: 10,
        },
        counts: {
            bridgeCandidates: 0,
            bridgeByType: {},
            crossDocumentPairCoverage: 0,
            crossDocumentSelected: 0,
            crossDocumentRejected: 0,
            crossDocumentWeakest: 0,
            promotionRows: 0,
            continuityEvents: 0,
            continuityBoundaries: 0,
            continuityEpisodes: 0,
            continuityTemporal: 0,
            continuityStates: 0,
            continuityCausal: 0,
            continuityConnections: 0,
            continuityConflicts: 0,
            governanceCandidates: 0,
            governanceByAction: {},
            retrievalTopRows: 0,
            retrievalViolations: 0,
        },
        projection: emptyNativeSnapshotAnalysisOutput(payload),
    };
}

function emptyNativePromotionVerdictOutput(): unknown {
    return {
        schemaVersion: 'phoenix-graph-promotion-verdict-native-output/v1',
        source: 'rust',
        certificate: {
            schemaVersion: 'phoenix-graph-promotion-verdict/v1',
            source: 'rust-deterministic-promotion-verdict',
            noTopologyWrites: true,
            receiptCount: 0,
            commitCount: 0,
            audit: {
                total: 0,
                acceptable: 0,
                alreadyCommitted: 0,
                blocked: 0,
                deferred: 0,
                rejected: 0,
                rollbackAvailable: 0,
                evidenceBlocked: 0,
                contradictionBlocked: 0,
                nliBlocked: 0,
                userOverrides: 0,
            },
            rows: [],
        },
        timing: { verdictBuildMicros: 0, totalMicros: 0 },
    };
}

function compileNativeAuditSidecar(payload: unknown): unknown {
    const result = spawnSync('cargo', [
        'run',
        '--quiet',
        '--manifest-path',
        'rust-native/phoenix/Cargo.toml',
        '-p',
        'phoenix-graph-rebuild',
        '--example',
        'atlas_packet_from_snapshot',
    ], {
        cwd: process.cwd(),
        input: JSON.stringify(payload || {}),
        encoding: 'utf8',
        maxBuffer: 64 * 1024 * 1024,
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
        throw new Error(result.stderr || `native audit sidecar exited ${result.status}`);
    }
    return JSON.parse(result.stdout);
}

function createPhoenixUiApiHarness() {
    return {
        loadStagedGraphScenePacket: vi.fn(async () => null),
    };
}

async function flushReceiptPersistence(pipeline: GraphRebuildPipelineService): Promise<void> {
    await ((pipeline as any).receiptPersistenceQueue as Promise<void>);
}

function elapsed(started: number): number {
    return round(performance.now() - started);
}

function round(value: number): number {
    return Math.max(0, Math.round(value * 100) / 100);
}
