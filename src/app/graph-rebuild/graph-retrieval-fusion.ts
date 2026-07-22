import { buildGraphAssertedTargetTraversal, type GraphAssertedTargetTraversal } from './graph-asserted-target-traversal';
import type {
    GraphRetrievalFusedHit,
    GraphRetrievalFusionRequest,
    GraphRetrievalFusionResult,
    GraphRetrievalLane,
    GraphRetrievalLaneCandidate,
    GraphRetrievalLaneReceipt,
} from './graph-retrieval-contract';
import { assertGraphEvidenceTargetRegistry, type GraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import { PhoenixLineSearchIndex } from '../lib/search/phoenix-line-search';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import { assertGraphSemanticDiscoveriesRemainCandidates } from './graph-semantic-discovery-authority';

const RECIPROCAL_RANK_K = 60 as const;
const LANE_WEIGHTS: Record<GraphRetrievalLane, number> = { lexical: 1, vector: 1, graph: 1 };

export interface GraphRetrievalVectorLaneInput {
    available: boolean;
    candidates: GraphRetrievalLaneCandidate[];
    evaluated: number;
    truncated: boolean;
    reason?: string;
}

export interface GraphRetrievalFusionRuntime {
    readonly snapshotId: string;
    retrieve(
        request: GraphRetrievalFusionRequest,
        vectorLane: GraphRetrievalVectorLaneInput,
    ): GraphRetrievalFusionResult;
}

export function buildGraphRetrievalFusionRuntime(snapshot: GraphRebuildSnapshot): GraphRetrievalFusionRuntime {
    assertGraphSemanticDiscoveriesRemainCandidates(snapshot);
    const registry = assertGraphEvidenceTargetRegistry(snapshot);
    const lexical = new PhoenixLineSearchIndex(
        registry.exposedTargets.map((target) => ({
            noteId: target.id,
            title: target.label,
            content: target.text,
            folderId: target.folderId,
        })),
        registry.contract.identityHash,
    );
    const traversal = buildGraphAssertedTargetTraversal(snapshot);
    const exposedIds = new Set(registry.exposedTargets.map((target) => target.id));
    return {
        snapshotId: snapshot.id,
        retrieve: (request, vectorLane) => retrieve(
            snapshot,
            registry,
            exposedIds,
            lexical,
            traversal,
            request,
            vectorLane,
        ),
    };
}

function retrieve(
    snapshot: GraphRebuildSnapshot,
    registry: GraphEvidenceTargetRegistry,
    exposedIds: ReadonlySet<string>,
    lexicalIndex: PhoenixLineSearchIndex,
    traversal: GraphAssertedTargetTraversal,
    request: GraphRetrievalFusionRequest,
    vectorLane: GraphRetrievalVectorLaneInput,
): GraphRetrievalFusionResult {
    const options = normalizeRequest(request);
    const lexicalCandidates = lexicalLane(
        lexicalIndex,
        options.query,
        options.lexicalLimit,
        options.lexicalMaxCandidateDocs,
    );
    const vectorCandidates = vectorLane.candidates.slice(0, options.vectorLimit);
    const graph = traversal.traverse([...lexicalCandidates, ...vectorCandidates], {
        limit: options.graphLimit,
        seedLimit: options.graphSeedLimit,
        maxHops: options.graphMaxHops,
        maxVisited: options.graphMaxVisited,
        maxEdges: options.graphMaxEdges,
    });
    const lanes = new Map<GraphRetrievalLane, GraphRetrievalLaneCandidate[]>([
        ['lexical', lexicalCandidates],
        ['vector', vectorCandidates],
        ['graph', graph.candidates],
    ]);
    const hits = fuseCandidates(registry, exposedIds, lanes, options.limit);
    const laneReceipts: GraphRetrievalLaneReceipt[] = [
        {
            lane: 'lexical',
            available: true,
            candidates: lexicalCandidates.length,
            evaluated: lexicalCandidates.length,
            limit: options.lexicalLimit,
            budget: options.lexicalMaxCandidateDocs,
            truncated: lexicalCandidates.length >= options.lexicalLimit,
        },
        {
            lane: 'vector',
            available: vectorLane.available,
            candidates: vectorCandidates.length,
            evaluated: vectorLane.evaluated,
            limit: options.vectorLimit,
            budget: options.vectorMaxCandidates,
            truncated: vectorLane.truncated || vectorLane.candidates.length > options.vectorLimit,
            reason: vectorLane.reason,
        },
        {
            lane: 'graph',
            available: true,
            candidates: graph.candidates.length,
            evaluated: graph.receipt.visitedTargets,
            limit: options.graphLimit,
            budget: options.graphMaxVisited,
            truncated: graph.truncated,
        },
    ];
    return {
        hits,
        receipt: {
            schemaVersion: 'phoenix-retrieval-fusion/v1',
            sourceSnapshotId: snapshot.id,
            sourceRegistryHash: registry.contract.identityHash,
            queryHash: hashQuery(options.query),
            fusion: 'weighted-reciprocal-rank',
            reciprocalRankK: RECIPROCAL_RANK_K,
            laneWeights: { ...LANE_WEIGHTS },
            lanes: laneReceipts,
            traversal: graph.receipt,
            returned: hits.length,
            candidateOnly: true,
            assertedTraversalOnly: true,
            committedTopologyWrites: 0,
        },
    };
}

function lexicalLane(
    index: PhoenixLineSearchIndex,
    query: string,
    limit: number,
    maxCandidateDocs: number,
): GraphRetrievalLaneCandidate[] {
    const hits = index.search(query, {
        limit: Math.min(maxCandidateDocs, limit * 4),
        maxCandidateDocs,
        before: 0,
        after: 0,
    });
    const best = new Map<string, number>();
    for (const hit of hits) best.set(hit.noteId, Math.max(hit.score, best.get(hit.noteId) || 0));
    const sorted = [...best.entries()]
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .slice(0, limit);
    const maximum = sorted[0]?.[1] || 1;
    return sorted.map(([targetId, score], rank) => ({
        targetId,
        score: roundScore(score / maximum),
        rank: rank + 1,
    }));
}

function fuseCandidates(
    registry: GraphEvidenceTargetRegistry,
    exposedIds: ReadonlySet<string>,
    lanes: ReadonlyMap<GraphRetrievalLane, readonly GraphRetrievalLaneCandidate[]>,
    limit: number,
): GraphRetrievalFusedHit[] {
    const rows = new Map<string, {
        score: number;
        laneScores: Partial<Record<GraphRetrievalLane, number>>;
        laneRanks: Partial<Record<GraphRetrievalLane, number>>;
        graphDistance?: number;
    }>();
    for (const [lane, candidates] of lanes) {
        for (const candidate of candidates) {
            const target = registry.get(candidate.targetId);
            if (!target || !exposedIds.has(candidate.targetId)) continue;
            const row = rows.get(candidate.targetId) || { score: 0, laneScores: {}, laneRanks: {} };
            row.score += LANE_WEIGHTS[lane] / (RECIPROCAL_RANK_K + candidate.rank);
            row.laneScores[lane] = candidate.score;
            row.laneRanks[lane] = candidate.rank;
            if (lane === 'graph') row.graphDistance = candidate.distance;
            rows.set(candidate.targetId, row);
        }
    }
    return [...rows.entries()]
        .sort((left, right) => right[1].score - left[1].score || left[0].localeCompare(right[0]))
        .slice(0, limit)
        .map(([targetId, row]) => {
            const target = registry.get(targetId)!;
            return {
                targetId,
                kind: target.kind,
                objectKind: registry.objectKind(targetId),
                sourceId: target.sourceId,
                label: target.label,
                text: target.text,
                noteId: target.noteId,
                chunkId: target.chunkId,
                evidenceIds: [...target.evidenceIds],
                score: roundScore(row.score),
                lanes: (Object.keys(row.laneRanks) as GraphRetrievalLane[]),
                laneScores: row.laneScores,
                laneRanks: row.laneRanks,
                graphDistance: row.graphDistance,
            };
        });
}

interface NormalizedRequest {
    query: string;
    limit: number;
    lexicalLimit: number;
    lexicalMaxCandidateDocs: number;
    vectorLimit: number;
    vectorMaxCandidates: number;
    graphLimit: number;
    graphSeedLimit: number;
    graphMaxHops: number;
    graphMaxVisited: number;
    graphMaxEdges: number;
}

function normalizeRequest(request: GraphRetrievalFusionRequest): NormalizedRequest {
    const query = request.query.trim();
    if (!query) throw new Error('Retrieval query is required');
    const limit = boundedInt(request.limit, 20, 1, 100);
    const lexicalLimit = boundedInt(request.lexicalLimit, 32, limit, 128);
    const vectorLimit = boundedInt(request.vectorLimit, 32, limit, 128);
    const graphLimit = boundedInt(request.graphLimit, 48, limit, 192);
    return {
        query,
        limit,
        lexicalLimit,
        lexicalMaxCandidateDocs: boundedInt(request.lexicalMaxCandidateDocs, 320, lexicalLimit, 2048),
        vectorLimit,
        vectorMaxCandidates: boundedInt(request.vectorMaxCandidates, 128, vectorLimit, 2048),
        graphLimit,
        graphSeedLimit: boundedInt(request.graphSeedLimit, 24, 1, 96),
        graphMaxHops: boundedInt(request.graphMaxHops, 2, 0, 4),
        graphMaxVisited: boundedInt(request.graphMaxVisited, 192, graphLimit, 2048),
        graphMaxEdges: boundedInt(request.graphMaxEdges, 768, graphLimit, 8192),
    };
}

function boundedInt(value: number | undefined, fallback: number, min: number, max: number): number {
    const normalized = Number.isFinite(value) ? Math.floor(value as number) : fallback;
    return Math.max(min, Math.min(max, normalized));
}

function hashQuery(value: string): string {
    let hash = 0x811c9dc5;
    for (const char of value.toLocaleLowerCase()) {
        hash ^= char.charCodeAt(0);
        hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return `fnv32-${hash.toString(16).padStart(8, '0')}`;
}

function roundScore(value: number): number {
    return Math.round(value * 1_000_000) / 1_000_000;
}
