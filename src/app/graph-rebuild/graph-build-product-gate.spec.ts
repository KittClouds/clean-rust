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
import { GraphRebuildService } from './graph-rebuild.service';
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
import { buildGraphAtlasTaxonomyAudit } from './graph-atlas-taxonomy-audit';

const SHOULD_RUN = process.env['GRAPH_BUILD_BASELINE'] === '1';
const ZEROSHOT_OUTPUT_URL = new URL('../../../target/graph-build-baselines/zero-shot-shortrun.json', import.meta.url);
const TAXONOMY_AUDIT_OUTPUT_URL = new URL('../../../target/graph-build-baselines/atlas-taxonomy-audit-shortrun.json', import.meta.url);
const SHORTRUN_URL = new URL('../../../docs/shortrun.md', import.meta.url);
const ZEROSHOT_OUTPUT_PATH = fileURLToPath(ZEROSHOT_OUTPUT_URL);
const TAXONOMY_AUDIT_OUTPUT_PATH = fileURLToPath(TAXONOMY_AUDIT_OUTPUT_URL);
const SHORTRUN_PATH = fileURLToPath(SHORTRUN_URL);
const SHOULD_WRITE_TAXONOMY_AUDIT = process.env['GRAPH_BUILD_TAXONOMY_AUDIT'] === '1';

const describeBaseline = describe;
const itZeroShot = SHOULD_RUN ? it : it.skip;

describeBaseline('product graph build gate', () => {
    let injector: EnvironmentInjector;
    let pipeline: GraphRebuildPipelineService;
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
    });

    afterEach(() => {
        injector.destroy();
        vi.clearAllMocks();
    });

    itZeroShot('writes the shortrun zero-shot graph build report', async () => {
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
        const upsertsBeforeWarm = store.upserts.length;
        const started = performance.now();
        const warm = await pipeline.buildGraph(request);
        const warmWallMs = elapsed(started);
        const warmScopedWrites = store.upserts.length - upsertsBeforeWarm;
        const keys = ['mentions', 'acceptedAnchors', 'nodes', 'edges', 'embeddingTargets'] as const;
        for (const key of keys) expect(warm.snapshot.counters[key]).toBe(cold.snapshot.counters[key]);
        expect(warm.snapshot.counters.nodes).toBe(27);
        expect(warm.snapshot.counters.edges).toBe(233);
        expect(warm.snapshot.counters.embeddingTargets).toBe(666);
        expect(warm.snapshot.atlasPacket?.objects.length).toBe(cold.snapshot.atlasPacket?.objects.length);
        expect(warm.snapshot.atlasPacket?.manifoldTargets.length)
            .toBe(cold.snapshot.atlasPacket?.manifoldTargets.length);
        expect(warm.snapshot.buildTimings?.snapshotReusedContentBlobs).toBeGreaterThan(0);
        expect(warm.snapshot.buildTimings?.snapshotWrittenContentBlobs).toBe(0);
        expect(warm.snapshot.buildTimings?.snapshotContentBlobReads).toBe(0);
        expect(warm.snapshot.buildTimings?.snapshotContentBlobManifestTrusted).toBe(1);
        expect(warm.snapshot.buildTimings?.previousSnapshotHydrationSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.nativeChunkerSkipped).toBe(1);
        expect(warm.snapshot.buildTimings?.documentSemanticSkipped).toBe(1);
        expect(warmScopedWrites).toBeLessThanOrEqual(3);
        expect(warmWallMs).toBeLessThanOrEqual(1_000);
        expect(store.upsertScopedDocuments).toHaveBeenCalledTimes(2);
        console.log(`[graph-product-gate] warmMs=${warmWallMs} scopedWrites=${warmScopedWrites} blobsWritten=${warm.snapshot.buildTimings?.snapshotWrittenContentBlobs || 0} nodes=${warm.snapshot.counters.nodes} edges=${warm.snapshot.counters.edges} targets=${warm.snapshot.counters.embeddingTargets}`);
    }, 30_000);
});

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
        predictedLabel: 'entailment',
        confidence: 0.95,
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
    return {
        suggestions: computed(() => suggestions()),
        runDynamicScan: vi.fn(async (input: { plainText: string }) => {
            const lower = input.plainText.toLocaleLowerCase();
            suggestions.set(harnessState.entities
                .filter((entity) => [entity.label, ...(entity.aliases || [])]
                    .some((surface) => lower.includes(String(surface).toLocaleLowerCase())))
                .map((entity) => ({
                    id: `suggestion:${entity.id}`,
                    entityId: entity.id,
                    label: entity.label,
                    kind: entity.kind,
                    confidence: 0.91,
                    source: 'dynamic_ner',
                })));
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
                predictedLabel: 'entailment',
                confidence: 0.9,
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
    const commands: Array<{ command: string; requestChars: number }> = [];
    return {
        commands,
        target: SHOULD_WRITE_TAXONOMY_AUDIT ? 'native' : 'web',
        storeCommand: vi.fn(async (command: string, payload: unknown) => {
            commands.push({ command, requestChars: JSON.stringify(payload || {}).length });
            if (SHOULD_WRITE_TAXONOMY_AUDIT && command === 'graphRebuild:compileDualWrite') {
                return compileNativeAuditSidecar(payload);
            }
            if (command === 'graphRebuild:compileDualWrite') {
                const snapshot = (payload as { snapshot: GraphRebuildSnapshot }).snapshot;
                return { atlasPacket: {
                    schemaVersion: 'phoenix-atlas-packet/v1', snapshotId: snapshot.id,
                    scopeKind: snapshot.scopeKind, scopeId: snapshot.scopeId, builtAt: snapshot.builtAt,
                    sourceContract: { authority: 'warm-force-harness', identityAuthority: 'source-evidence', vectorContract: 'vectors-missing', tsGraphBuilderRole: 'compatibility-only' },
                    objects: [], manifoldTargets: [],
                    counters: { objects: 0, manifoldTargets: 0, registryEntities: snapshot.nodes.length, evidenceAnchors: snapshot.entityAnchors.length, modelVectors: 0, families: [] },
                } };
            }
            return null;
        }),
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

function elapsed(started: number): number {
    return round(performance.now() - started);
}

function round(value: number): number {
    return Math.max(0, Math.round(value * 100) / 100);
}
