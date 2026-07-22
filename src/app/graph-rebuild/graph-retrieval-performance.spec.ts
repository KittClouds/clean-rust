// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { arch, cpus, platform, release, totalmem } from 'node:os';
import { dirname, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { describe, expect, it } from 'vitest';

import {
    buildGraphEncoderVectorIndex,
    type GraphEncoderVectorIndex,
    type GraphEncoderVectorPage,
} from './graph-encoder-vector-index';
import { assertGraphEvidenceTargetRegistry, sealGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildGraphRetrievalFusionRuntime, type GraphRetrievalFusionRuntime } from './graph-retrieval-fusion';
import type {
    GraphRebuildChunk,
    GraphRebuildEdge,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

const CERTIFICATE_SCHEMA = 'phoenix-graph-retrieval-baseline/v1' as const;
const OUTPUT_PATH = resolve('target/graph-retrieval-baselines/retrieval-index-baseline.json');
const FULL_BASELINE = process.env['GRAPH_RETRIEVAL_BASELINE'] === '1';

interface TimingDistribution {
    samples: number;
    p50Ms: number;
    p95Ms: number;
    maxMs: number;
}

interface ScaleConfig {
    targets: number;
    dimensions: number;
    edgeStride: number;
    indexSamples: number;
    querySamples: number;
}

interface ScaleReceipt {
    targets: number;
    edges: number;
    dimensions: number;
    registry: TimingDistribution;
    indexBuild: TimingDistribution;
    runtimeBuild: TimingDistribution;
    vectorQuery: TimingDistribution;
    fusionQuery: TimingDistribution;
    endToEndQuery: TimingDistribution;
    observedMemory: {
        heapObservedDeltaBytes: number;
        arrayBufferObservedDeltaBytes: number;
        observedDeltaReliable: boolean;
        packedVectorBytes: number;
        packedVectorBytesPerTarget: number;
    };
    work: {
        evaluatedPairs: number;
        neighborCount: number;
        assertedLinks: number;
        vectorCandidates: number;
        visitedTargets: number;
        edgesExamined: number;
        returnedHits: number;
    };
    authority: {
        candidateOnly: true;
        assertedTraversalOnly: true;
        committedTopologyWrites: 0;
        repeatedResultParity: boolean;
        resultHash: string;
    };
}

describe('graph retrieval scale baseline', () => {
    it('captures bounded index and retrieval work without changing graph truth', () => {
        const configs = FULL_BASELINE ? baselineConfigs() : [smokeConfig()];
        const scales = configs.map(runScale);
        const certificate = {
            schemaVersion: CERTIFICATE_SCHEMA,
            emittedAt: new Date().toISOString(),
            commit: gitCommit(),
            implementationHash: implementationHash(),
            runtime: machineReceipt(),
            configuration: {
                fullBaseline: FULL_BASELINE,
                lshBands: 4,
                lshBits: 10,
                neighborhoodK: 8,
                maxCandidatesPerTarget: 96,
                vectorQueryMaxCandidates: 96,
                graphMaxVisited: 256,
                graphMaxEdges: 768,
            },
            scales,
        };

        for (const scale of scales) {
            expect(scale.work.evaluatedPairs).toBeLessThanOrEqual(scale.targets * 96);
            expect(scale.work.vectorCandidates).toBeLessThanOrEqual(96);
            expect(scale.work.visitedTargets).toBeLessThanOrEqual(256);
            expect(scale.work.edgesExamined).toBeLessThanOrEqual(768);
            expect(scale.authority).toMatchObject({
                candidateOnly: true,
                assertedTraversalOnly: true,
                committedTopologyWrites: 0,
                repeatedResultParity: true,
            });
        }

        if (FULL_BASELINE) writeCertificate(certificate);
        console.info(`[graph-retrieval-baseline] ${JSON.stringify(certificate)}`);
    }, FULL_BASELINE ? 600_000 : 30_000);
});

function runScale(config: ScaleConfig): ScaleReceipt {
    const snapshot = benchmarkSnapshot(config.targets, config.edgeStride);
    const registryTimes = sample(config.indexSamples, () => assertGraphEvidenceTargetRegistry(snapshot));
    const registry = assertGraphEvidenceTargetRegistry(snapshot);
    const page = vectorPage(registry.exposedTargets.map((target) => target.id), config.dimensions);
    collectGarbage();
    const memoryBefore = process.memoryUsage();

    let index: GraphEncoderVectorIndex | undefined;
    const indexTimes = sample(config.indexSamples, () => {
        index = buildGraphEncoderVectorIndex(snapshot, page, {
            neighborhoodK: 8,
            lshBands: 4,
            lshBits: 10,
            maxCandidatesPerTarget: 96,
            minimumSimilarity: -1,
        });
    });
    if (!index) throw new Error('Benchmark index was not built');

    let runtime: GraphRetrievalFusionRuntime | undefined;
    const runtimeTimes = sample(config.indexSamples, () => {
        runtime = buildGraphRetrievalFusionRuntime(snapshot);
    });
    if (!runtime) throw new Error('Benchmark retrieval runtime was not built');

    const query = index.vector(index.targetIds[Math.floor(index.targetIds.length / 3)]);
    if (!query) throw new Error('Benchmark query vector was not found');
    const vectorTimes: number[] = [];
    const fusionTimes: number[] = [];
    const endToEndTimes: number[] = [];
    let lastHash = '';
    let firstHash = '';
    let vectorCandidates = 0;
    let assertedLinks = 0;
    let visitedTargets = 0;
    let edgesExamined = 0;
    let returnedHits = 0;

    for (let iteration = 0; iteration < config.querySamples; iteration += 1) {
        const totalStarted = performance.now();
        const vectorStarted = performance.now();
        const vectorResult = index.query(query, {
            limit: 24,
            maxCandidates: 96,
            minimumSimilarity: -1,
        });
        vectorTimes.push(performance.now() - vectorStarted);
        const fusionStarted = performance.now();
        const result = runtime.retrieve({
            query: 'route group 7 evidence',
            limit: 24,
            lexicalLimit: 32,
            lexicalMaxCandidateDocs: 128,
            vectorLimit: 24,
            vectorMaxCandidates: 96,
            graphLimit: 24,
            graphSeedLimit: 12,
            graphMaxHops: 2,
            graphMaxVisited: 256,
            graphMaxEdges: 768,
        }, {
            available: true,
            candidates: vectorResult.neighbors,
            evaluated: vectorResult.evaluatedCandidates,
            truncated: vectorResult.truncated,
        });
        fusionTimes.push(performance.now() - fusionStarted);
        endToEndTimes.push(performance.now() - totalStarted);
        lastHash = hashHits(result.hits.map((hit) => hit.targetId));
        if (!iteration) firstHash = lastHash;
        vectorCandidates = vectorResult.evaluatedCandidates;
        assertedLinks = result.receipt.traversal.assertedLinks;
        visitedTargets = result.receipt.traversal.visitedTargets;
        edgesExamined = result.receipt.traversal.edgesExamined;
        returnedHits = result.hits.length;
        expect(result.receipt.candidateOnly).toBe(true);
        expect(result.receipt.assertedTraversalOnly).toBe(true);
        expect(result.receipt.committedTopologyWrites).toBe(0);
    }

    const memoryAfter = process.memoryUsage();
    const packedVectorBytes = page.values.byteLength;
    const heapObservedDeltaBytes = memoryAfter.heapUsed - memoryBefore.heapUsed;
    const arrayBufferObservedDeltaBytes = memoryAfter.arrayBuffers - memoryBefore.arrayBuffers;
    return {
        targets: config.targets,
        edges: snapshot.edges.length,
        dimensions: config.dimensions,
        registry: distribution(registryTimes),
        indexBuild: distribution(indexTimes),
        runtimeBuild: distribution(runtimeTimes),
        vectorQuery: distribution(vectorTimes),
        fusionQuery: distribution(fusionTimes),
        endToEndQuery: distribution(endToEndTimes),
        observedMemory: {
            heapObservedDeltaBytes,
            arrayBufferObservedDeltaBytes,
            observedDeltaReliable: heapObservedDeltaBytes >= 0 && arrayBufferObservedDeltaBytes >= 0,
            packedVectorBytes,
            packedVectorBytesPerTarget: packedVectorBytes / config.targets,
        },
        work: {
            evaluatedPairs: index.contract.evaluatedPairs,
            neighborCount: index.contract.neighborCount,
            assertedLinks,
            vectorCandidates,
            visitedTargets,
            edgesExamined,
            returnedHits,
        },
        authority: {
            candidateOnly: true,
            assertedTraversalOnly: true,
            committedTopologyWrites: 0,
            repeatedResultParity: firstHash === lastHash,
            resultHash: lastHash,
        },
    };
}

function benchmarkSnapshot(targetCount: number, edgeStride: number): GraphRebuildSnapshot {
    const snapshot = buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: `benchmark:retrieval:${targetCount}`,
        noteIds: ['benchmark-note'],
        entities: [],
        occurrences: [],
        chunks: [],
        builtAt: 1,
        postProcessMode: 'core',
    });
    const chunks = Array.from({ length: targetCount }, (_, ordinal): GraphRebuildChunk => ({
        id: `benchmark-note:block:${ordinal}`,
        noteId: 'benchmark-note',
        start: ordinal * 32,
        end: ordinal * 32 + 24,
        ordinal,
        source: 'note-block',
    }));
    const targets = chunks.map((chunk, ordinal): GraphRebuildEmbeddingTarget => ({
        id: `embed:chunk:${chunk.id}`,
        kind: 'chunk',
        sourceId: chunk.id,
        noteId: chunk.noteId,
        chunkId: chunk.id,
        label: `Route segment ${ordinal}`,
        text: `route group ${ordinal % 31} evidence sector ${ordinal % 127}`,
        evidenceIds: [],
        lane: 'chunk_spine',
        structuralRole: 'spine',
        admissionStatus: 'admitted',
    }));
    const edges: GraphRebuildEdge[] = [];
    for (let ordinal = 0; ordinal < targetCount; ordinal += 1) {
        edges.push(edge(chunks, ordinal, ordinal + 1, 'ring'));
        if (targetCount > edgeStride) edges.push(edge(chunks, ordinal, ordinal + edgeStride, 'stride'));
    }
    snapshot.chunks = chunks;
    snapshot.embeddingTargets = targets;
    snapshot.edges = edges;
    snapshot.embeddingVectors = [];
    snapshot.encoderVectorIndex = undefined;
    snapshot.evidenceTargetRegistry = undefined;
    snapshot.counters.chunks = targetCount;
    snapshot.counters.embeddingTargets = targetCount;
    snapshot.counters.edges = edges.length;
    sealGraphEvidenceTargetRegistry(snapshot);
    return snapshot;
}

function edge(
    chunks: readonly GraphRebuildChunk[],
    source: number,
    target: number,
    type: string,
): GraphRebuildEdge {
    const sourceId = chunks[source % chunks.length].id;
    const targetId = chunks[target % chunks.length].id;
    return {
        id: `benchmark:${type}:${sourceId}:${targetId}`,
        sourceId,
        targetId,
        type,
        weight: 1,
        confidence: 1,
        evidenceAnchorIds: [],
        scopeKeys: ['benchmark'],
        noteIds: ['benchmark-note'],
    };
}

function vectorPage(targetIds: readonly string[], dimensions: number): GraphEncoderVectorPage {
    const values = new Float32Array(targetIds.length * dimensions);
    let state = 0x9e3779b9;
    for (let row = 0; row < targetIds.length; row += 1) {
        const offset = row * dimensions;
        let normSquared = 0;
        for (let dim = 0; dim < dimensions; dim += 1) {
            state ^= state << 13;
            state ^= state >>> 17;
            state ^= state << 5;
            const value = ((state >>> 0) / 0xffffffff) * 2 - 1;
            values[offset + dim] = value;
            normSquared += value * value;
        }
        const inverse = 1 / Math.sqrt(normSquared);
        for (let dim = 0; dim < dimensions; dim += 1) values[offset + dim] *= inverse;
    }
    return {
        modelId: 'benchmark-real-encoder',
        modelVersion: 'deterministic-v1',
        executionProvider: 'external-encoder',
        dimensions,
        generation: 1,
        targetIds,
        values,
        normalized: true,
    };
}

function baselineConfigs(): ScaleConfig[] {
    const dimensions = positiveInt(process.env['GRAPH_RETRIEVAL_DIMENSIONS'], 768);
    const sampleOverride = positiveInt(process.env['GRAPH_RETRIEVAL_INDEX_SAMPLES'], 0);
    const counts = (process.env['GRAPH_RETRIEVAL_SCALE_COUNTS'] || '1000,5000,10000,25000')
        .split(',')
        .map((value) => positiveInt(value, 0))
        .filter((value) => value > 0);
    return counts.map((targets) => ({
        targets,
        dimensions,
        edgeStride: 31,
        indexSamples: sampleOverride || (targets <= 5_000 ? 3 : 1),
        querySamples: 30,
    }));
}

function smokeConfig(): ScaleConfig {
    return { targets: 256, dimensions: 64, edgeStride: 17, indexSamples: 1, querySamples: 3 };
}

function sample(count: number, operation: () => void): number[] {
    const timings: number[] = [];
    for (let iteration = 0; iteration < count; iteration += 1) {
        const started = performance.now();
        operation();
        timings.push(performance.now() - started);
    }
    return timings;
}

function distribution(values: readonly number[]): TimingDistribution {
    const ordered = [...values].sort((left, right) => left - right);
    return {
        samples: ordered.length,
        p50Ms: round(quantile(ordered, 0.5)),
        p95Ms: round(quantile(ordered, 0.95)),
        maxMs: round(ordered[ordered.length - 1] || 0),
    };
}

function quantile(ordered: readonly number[], percentile: number): number {
    if (!ordered.length) return 0;
    return ordered[Math.min(ordered.length - 1, Math.max(0, Math.ceil(ordered.length * percentile) - 1))];
}

function hashHits(targetIds: readonly string[]): string {
    return hashStrings(targetIds);
}

function hashStrings(values: readonly string[]): string {
    let hash = 0x811c9dc5;
    for (const value of values) {
        for (let index = 0; index < value.length; index += 1) {
            hash ^= value.charCodeAt(index);
            hash = Math.imul(hash, 0x01000193) >>> 0;
        }
    }
    return `fnv32-${hash.toString(16).padStart(8, '0')}`;
}

function positiveInt(value: string | undefined, fallback: number): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function round(value: number): number {
    return Math.round(value * 1_000) / 1_000;
}

function collectGarbage(): void {
    const gc = (globalThis as { gc?: () => void }).gc;
    if (gc) gc();
}

function gitCommit(): string {
    return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
}

function implementationHash(): string {
    return hashStrings([
        'src/app/graph-rebuild/graph-encoder-vector-index.ts',
        'src/app/graph-rebuild/graph-encoder-vector-index-native.ts',
        'src/app/graph-rebuild/graph-evidence-target-registry.ts',
        'src/app/graph-rebuild/graph-asserted-target-traversal.ts',
        'src/app/graph-rebuild/graph-retrieval-fusion.ts',
        'src/app/graph-rebuild/graph-retrieval-performance.spec.ts',
        'src/app/services/graph-target-vector-index.service.ts',
        'src-tauri/src/graph_vector_index.rs',
    ].map((path) => `${path}\0${readFileSync(resolve(path), 'utf8')}\0`));
}

function machineReceipt() {
    const cpuRows = cpus();
    return {
        node: process.version,
        platform: platform(),
        release: release(),
        arch: arch(),
        cpu: cpuRows[0]?.model || 'unknown',
        logicalCores: cpuRows.length,
        totalMemoryBytes: totalmem(),
    };
}

function writeCertificate(certificate: object): void {
    mkdirSync(dirname(OUTPUT_PATH), { recursive: true });
    writeFileSync(OUTPUT_PATH, `${JSON.stringify(certificate, null, 2)}\n`, 'utf8');
}
