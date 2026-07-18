import type { GraphEvidenceTargetObjectKind, GraphRebuildEmbeddingTarget } from './graph-rebuild-snapshot';

export type GraphRetrievalLane = 'lexical' | 'vector' | 'graph';

export interface GraphRetrievalFusionRequest {
    query: string;
    limit?: number;
    lexicalLimit?: number;
    lexicalMaxCandidateDocs?: number;
    vectorLimit?: number;
    vectorMaxCandidates?: number;
    graphLimit?: number;
    graphSeedLimit?: number;
    graphMaxHops?: number;
    graphMaxVisited?: number;
    graphMaxEdges?: number;
    queryVector?: Float32Array;
}

export interface GraphRetrievalLaneCandidate {
    targetId: string;
    score: number;
    rank: number;
    distance?: number;
}

export interface GraphRetrievalLaneReceipt {
    lane: GraphRetrievalLane;
    available: boolean;
    candidates: number;
    evaluated: number;
    limit: number;
    budget: number;
    truncated: boolean;
    reason?: string;
}

export interface GraphRetrievalTraversalReceipt {
    assertedLinks: number;
    seeds: number;
    maxHops: number;
    visitedTargets: number;
    edgesExamined: number;
    candidateEdgesTraversed: 0;
}

export interface GraphRetrievalFusedHit {
    targetId: string;
    kind: GraphRebuildEmbeddingTarget['kind'];
    objectKind?: GraphEvidenceTargetObjectKind;
    sourceId: string;
    label: string;
    text: string;
    noteId?: string;
    chunkId?: string;
    evidenceIds: string[];
    score: number;
    lanes: GraphRetrievalLane[];
    laneScores: Partial<Record<GraphRetrievalLane, number>>;
    laneRanks: Partial<Record<GraphRetrievalLane, number>>;
    graphDistance?: number;
}

export interface GraphRetrievalFusionReceipt {
    schemaVersion: 'phoenix-retrieval-fusion/v1';
    sourceSnapshotId: string;
    sourceRegistryHash: string;
    queryHash: string;
    fusion: 'weighted-reciprocal-rank';
    reciprocalRankK: 60;
    laneWeights: Record<GraphRetrievalLane, number>;
    lanes: GraphRetrievalLaneReceipt[];
    traversal: GraphRetrievalTraversalReceipt;
    returned: number;
    candidateOnly: true;
    assertedTraversalOnly: true;
    committedTopologyWrites: 0;
}

export interface GraphRetrievalFusionResult {
    hits: GraphRetrievalFusedHit[];
    receipt: GraphRetrievalFusionReceipt;
}
