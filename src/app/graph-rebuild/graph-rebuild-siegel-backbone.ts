import type {
    GraphIndexProjectionReceipt,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import {
    normalizeEmbeddingProfile,
    sparseCosine,
    sparseEmbeddingSignature,
    type SparseEmbeddingSignature,
} from './graph-rebuild-embedding-signatures';

const SIEGEL_GENUS = 3;
const MATRIX_CELLS = (SIEGEL_GENUS * (SIEGEL_GENUS + 1)) / 2;
const MAX_EVALUATED_DIRECTED_EDGES = 4096;

interface DirectedPair {
    source: number;
    target: number;
    kind: 'parent' | 'backbone' | 'bridge';
}

interface SiegelBackboneReceiptOptions {
    nativeRunner?: SiegelNativeRunner | null;
    nativeReceipt?: unknown;
    allowRuntimeNative?: boolean;
}

type SiegelNativeRunner = (request: SiegelNativeRunRequest) => Promise<SiegelNativeRunReceipt>;

interface SiegelNativeRunRequest {
    genus: number;
    targets: SiegelNativeTargetInput[];
    edges: SiegelNativeEdgeInput[];
    caps: {
        maxTargets: number;
        maxDirectedEdges: number;
        maxPairs: number;
        maxDistanceEvaluations: number;
    };
}

interface SiegelNativeTargetInput {
    stableHash: number;
    lane: string;
    hierarchyDepth: number;
    confidenceMilli: number;
}

interface SiegelNativeEdgeInput {
    fromOrd: number;
    toOrd: number;
    kind: DirectedPair['kind'];
    weightMilli: number;
}

interface SiegelNativeRunReceipt {
    contract?: Record<string, unknown>;
    counters?: Record<string, unknown>;
    parentPairs?: unknown;
    backbonePairs?: unknown;
    bridgePairs?: unknown;
}

export async function buildSiegelBackboneProjectionReceipt(
    snapshot: GraphRebuildSnapshot | null,
    options: SiegelBackboneReceiptOptions = {},
): Promise<GraphIndexProjectionReceipt> {
    const startedAt = Date.now();
    const targetCount = snapshot?.embeddingTargets.length || 0;
    if (!snapshot || targetCount === 0) {
        return receipt(startedAt, snapshot, {}, 'Siegel-Finsler backbone skipped; no embedding targets');
    }

    if (options.nativeReceipt && typeof options.nativeReceipt === 'object') {
        return receiptFromNative(startedAt, snapshot, options.nativeReceipt as SiegelNativeRunReceipt);
    }

    const nativeRunner = options.allowRuntimeNative === false
        ? options.nativeRunner || null
        : options.nativeRunner ?? runtimeNativeRunner();
    if (nativeRunner) {
        try {
            const nativeReceipt = await nativeRunner(graphRebuildSiegelNativeRequest(snapshot));
            return receiptFromNative(startedAt, snapshot, nativeReceipt);
        } catch {
            return fallbackReceipt(startedAt, snapshot, { siegelNativeError: 1 });
        }
    }

    return fallbackReceipt(startedAt, snapshot, { siegelFallback: 1 });
}

function fallbackReceipt(
    startedAt: number,
    snapshot: GraphRebuildSnapshot,
    extraCounters: Record<string, number>,
): GraphIndexProjectionReceipt {
    const targetCount = snapshot.embeddingTargets.length;

    const profile = normalizeEmbeddingProfile(snapshot.embeddingProfile);
    const dimensions = Math.max(32, profile.selectedDimensions);
    const signatures = snapshot.embeddingTargets.map((target) =>
        sparseEmbeddingSignature(target, Math.min(dimensions, 384)),
    );
    const depths = snapshot.embeddingTargets.map(targetDepth);
    const allPairs = directedPairs(snapshot);
    const pairs = allPairs.slice(0, MAX_EVALUATED_DIRECTED_EDGES);
    const metrics = evaluateFinslerAsymmetry(snapshot.embeddingTargets, signatures, depths, pairs);
    const completedAt = Date.now();

    return {
        mode: 'siegel',
        status: 'synced',
        startedAt,
        completedAt,
        durationMs: completedAt - startedAt,
        targetCount,
        vectorCount: targetCount,
        counters: {
            siegelEnabled: 1,
            siegelGenus: SIEGEL_GENUS,
            siegelMatrixCells: MATRIX_CELLS,
            siegelTargets: targetCount,
            siegelDirectedEdges: pairs.length,
            siegelParentEdges: pairs.filter((pair) => pair.kind === 'parent').length,
            siegelBackboneEdges: pairs.filter((pair) => pair.kind === 'backbone').length,
            siegelBridgeEdges: pairs.filter((pair) => pair.kind === 'bridge').length,
            siegelDistanceEvaluations: metrics.evaluations,
            siegelAsymmetricPairs: metrics.asymmetricPairs,
            siegelMeanAsymmetryPpm: Math.round(metrics.meanAsymmetry * 1_000_000),
            siegelHierarchyViolations: metrics.hierarchyViolations,
            siegelEstimatedBytes: targetCount * MATRIX_CELLS * 2 * Float32Array.BYTES_PER_ELEMENT,
            siegelPrunedDirectedEdges: Math.max(0, allPairs.length - pairs.length),
            ...extraCounters,
        },
        message: `Siegel-Finsler fallback synced: g=${SIEGEL_GENUS}, ${pairs.length} directed edges`,
    };
}

export function graphRebuildSiegelNativeRequest(snapshot: GraphRebuildSnapshot): SiegelNativeRunRequest {
    const pairs = directedPairs(snapshot);
    return {
        genus: SIEGEL_GENUS,
        targets: snapshot.embeddingTargets.map((target, index) => ({
            stableHash: stableTargetHash(target, index),
            lane: target.lane || 'unknown',
            hierarchyDepth: targetDepth(target),
            confidenceMilli: confidenceMilli(target),
        })),
        edges: pairs.map((pair) => ({
            fromOrd: pair.source,
            toOrd: pair.target,
            kind: pair.kind,
            weightMilli: pair.kind === 'bridge' ? 850 : 1_000,
        })),
        caps: {
            maxTargets: Math.max(1, snapshot.embeddingTargets.length),
            maxDirectedEdges: MAX_EVALUATED_DIRECTED_EDGES,
            maxPairs: MAX_EVALUATED_DIRECTED_EDGES,
            maxDistanceEvaluations: MAX_EVALUATED_DIRECTED_EDGES,
        },
    };
}

function receiptFromNative(
    startedAt: number,
    snapshot: GraphRebuildSnapshot,
    nativeReceipt: SiegelNativeRunReceipt,
): GraphIndexProjectionReceipt {
    const completedAt = Date.now();
    const contract = nativeReceipt.contract || {};
    const nativeCounters = nativeReceipt.counters || {};
    const targetCount = counter(contract['targetCount'], snapshot.embeddingTargets.length);
    const directedEdges = counter(contract['directedEdgeCount'], counter(nativeCounters['directedEdgeCount']));
    const timings = objectRecord(contract['timings']);
    return {
        mode: 'siegel',
        status: 'synced',
        startedAt,
        completedAt,
        durationMs: completedAt - startedAt,
        targetCount,
        vectorCount: targetCount,
        counters: {
            siegelEnabled: 1,
            siegelNative: 1,
            siegelGenus: counter(contract['genus'], SIEGEL_GENUS),
            siegelMatrixCells: counter(contract['matrixCells'], MATRIX_CELLS),
            siegelTargets: targetCount,
            siegelDirectedEdges: directedEdges,
            siegelPairs: counter(nativeCounters['pairCount'], directedEdges),
            siegelParentEdges: counter(nativeReceipt.parentPairs),
            siegelBackboneEdges: counter(nativeReceipt.backbonePairs),
            siegelBridgeEdges: counter(nativeReceipt.bridgePairs),
            siegelSkippedEdges: counter(nativeCounters['skippedEdgeCount']),
            siegelCappedEdges: counter(nativeCounters['cappedEdgeCount']),
            siegelCappedPairs: counter(nativeCounters['cappedPairCount']),
            siegelCappedDistances: counter(nativeCounters['cappedDistanceCount']),
            siegelDistanceEvaluations: counter(contract['distanceEvaluations'], counter(nativeCounters['distanceEvaluations'])),
            siegelAsymmetricPairs: counter(contract['asymmetricPairCount'], counter(nativeCounters['asymmetricPairCount'])),
            siegelHierarchyViolations: counter(contract['hierarchyViolationCount'], counter(nativeCounters['hierarchyViolationCount'])),
            siegelEstimatedBytes: counter(contract['estimatedBytes']),
            siegelBuildMs: counter(timings['buildMs']),
            siegelMatrixPlanMs: counter(timings['matrixPlanMs']),
            siegelDistanceMs: counter(timings['distanceMs']),
            siegelHierarchyMs: counter(timings['hierarchyMs']),
            siegelSerializeMs: counter(timings['serializeMs']),
        },
        message: `Native Siegel-Finsler synced: g=${counter(contract['genus'], SIEGEL_GENUS)}, ${directedEdges} directed edges`,
    };
}

function directedPairs(snapshot: GraphRebuildSnapshot): DirectedPair[] {
    const byId = new Map(snapshot.embeddingTargets.map((target, index) => [target.id, index]));
    const pairs: DirectedPair[] = [];
    const seen = new Set<string>();
    const add = (source: number | undefined, target: number | undefined, kind: DirectedPair['kind']) => {
        if (source === undefined || target === undefined || source === target) return;
        const key = `${source}:${target}:${kind}`;
        if (seen.has(key)) return;
        seen.add(key);
        pairs.push({ source, target, kind });
    };

    for (let index = 0; index < snapshot.embeddingTargets.length; index += 1) {
        for (const parentId of snapshot.embeddingTargets[index].parentIds || []) {
            add(byId.get(parentId), index, 'parent');
        }
    }
    for (const edge of snapshot.embeddingGraphPostProcess?.backboneEdges || []) {
        const kind = edge.role === 'bridge' ? 'bridge' : 'backbone';
        add(byId.get(edge.sourceTargetId), byId.get(edge.targetTargetId), kind);
    }
    return pairs.sort((left, right) => kindRank(left.kind) - kindRank(right.kind));
}

function evaluateFinslerAsymmetry(
    targets: GraphRebuildEmbeddingTarget[],
    signatures: SparseEmbeddingSignature[],
    depths: number[],
    pairs: DirectedPair[],
): { evaluations: number; asymmetricPairs: number; meanAsymmetry: number; hierarchyViolations: number } {
    let evaluations = 0;
    let asymmetricPairs = 0;
    let asymmetrySum = 0;
    let hierarchyViolations = 0;
    for (const pair of pairs) {
        const forward = finslerDistance(targets[pair.source], targets[pair.target], signatures[pair.source], signatures[pair.target], depths[pair.source], depths[pair.target]);
        const reverse = finslerDistance(targets[pair.target], targets[pair.source], signatures[pair.target], signatures[pair.source], depths[pair.target], depths[pair.source]);
        const delta = Math.abs(reverse - forward);
        evaluations += 2;
        if (delta > 0.0001) asymmetricPairs += 1;
        asymmetrySum += delta;
        if (pair.kind === 'parent' && forward >= reverse) hierarchyViolations += 1;
    }
    return {
        evaluations,
        asymmetricPairs,
        meanAsymmetry: pairs.length ? asymmetrySum / pairs.length : 0,
        hierarchyViolations,
    };
}

function finslerDistance(
    source: GraphRebuildEmbeddingTarget,
    target: GraphRebuildEmbeddingTarget,
    sourceSignature: SparseEmbeddingSignature,
    targetSignature: SparseEmbeddingSignature,
    sourceDepth: number,
    targetDepth: number,
): number {
    const semantic = 1 - sparseCosine(sourceSignature, targetSignature);
    const depthDelta = targetDepth - sourceDepth;
    const downTreeReward = depthDelta > 0 ? 0.18 * Math.min(3, depthDelta) : 0;
    const upTreePenalty = depthDelta < 0 ? 0.22 * Math.min(3, -depthDelta) : 0;
    const lanePenalty = source.lane && target.lane && source.lane !== target.lane ? 0.04 : 0;
    return Math.max(0, semantic + upTreePenalty + lanePenalty - downTreeReward);
}

function targetDepth(target: GraphRebuildEmbeddingTarget): number {
    if (target.admissionTier !== undefined) return Math.max(0, target.admissionTier);
    switch (target.lane) {
        case 'document_spine': return 0;
        case 'chunk_spine': return 1;
        case 'entity_anchor': return 2;
        case 'relationship_fact':
        case 'temporal_fact':
        case 'causal_fact':
        case 'memory_state':
        case 'event_identity': return 3;
        case 'anchor_evidence':
        case 'cooccurrence_weak': return 4;
        default: return 3;
    }
}

function kindRank(kind: DirectedPair['kind']): number {
    if (kind === 'parent') return 0;
    if (kind === 'backbone') return 1;
    return 2;
}

function stableTargetHash(target: GraphRebuildEmbeddingTarget, index: number): number {
    const text = `${target.id}\u0000${target.sourceId}\u0000${target.lane || ''}\u0000${target.label}\u0000${index}`;
    let hash = 2166136261;
    for (let cursor = 0; cursor < text.length; cursor += 1) {
        hash ^= text.charCodeAt(cursor);
        hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
}

function confidenceMilli(target: GraphRebuildEmbeddingTarget): number {
    if (target.admissionStatus === 'deferred') return 550;
    if (target.admissionStatus === 'admitted') return 950;
    const evidenceBoost = Math.min(150, (target.evidenceIds?.length || 0) * 25);
    return Math.max(500, Math.min(1_000, 800 + evidenceBoost));
}

function runtimeNativeRunner(): SiegelNativeRunner | null {
    if (typeof window === 'undefined') return null;
    const bridge = window.__PHOENIX_NATIVE_BACKEND__;
    if (!bridge?.siegelFinslerReceipt) return null;
    return (request) => bridge.siegelFinslerReceipt!(request as unknown as Record<string, unknown>);
}

function counter(value: unknown, fallback = 0): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function objectRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function receipt(
    startedAt: number,
    snapshot: GraphRebuildSnapshot | null,
    counters: Record<string, number>,
    message: string,
): GraphIndexProjectionReceipt {
    const completedAt = Date.now();
    return {
        mode: 'siegel',
        status: 'skipped',
        startedAt,
        completedAt,
        durationMs: completedAt - startedAt,
        targetCount: snapshot?.embeddingTargets.length || 0,
        vectorCount: 0,
        counters,
        message,
    };
}
