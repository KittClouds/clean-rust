import type {
    HybridEmbeddingSpaceContract,
    HybridEmbeddingValidationReceipt,
    HybridEmbeddingValidationStatus,
} from './manifold-atlas.types';

export interface HybridEmbeddingValidationNode {
    id: string;
    vector?: ArrayLike<number> | null;
}

export interface HybridEmbeddingValidationEdge {
    sourceId: string;
    targetId: string;
}

export interface HybridEmbeddingValidationPayload {
    nodes: readonly HybridEmbeddingValidationNode[];
    edges?: readonly HybridEmbeddingValidationEdge[];
}

interface ValidNode {
    id: string;
    vector: number[];
}

interface Neighbor {
    targetIndex: number;
    score: number;
}

interface LocalDensityStats {
    min: number;
    average: number;
    max: number;
}

interface HubnessStats {
    mutualPairs: number;
    mutualRatio: number;
    maxInbound: number;
    limit: number;
    flaggedNodeIds: string[];
}

interface RejectedNeighborSummary {
    count: number;
    receipts: string[];
}

interface NeighborStabilityStats {
    status: HybridEmbeddingValidationStatus;
    previousHash: string | null;
    stablePairs: number;
    previousPairs: number;
    ratio: number;
}

const FNV_OFFSET = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

export function buildHybridEmbeddingValidationReceipt(
    contract: Pick<HybridEmbeddingSpaceContract, 'artifactId' | 'inputHash' | 'neighborhood'>,
    payload: HybridEmbeddingValidationPayload,
    previousReceipt?: HybridEmbeddingValidationReceipt | null,
): HybridEmbeddingValidationReceipt {
    const { validNodes, dimensions, dimensionMismatchCount, rejectedReceipts } = collectValidNodes(payload.nodes);
    const neighbors = buildNeighbors(validNodes, contract.neighborhood.k, contract.neighborhood.minSimilarity);
    const components = connectedComponents(validNodes.length, neighbors);
    const candidateSupport = candidateNeighborhoodSupport(payload.edges || [], validNodes, neighbors);
    const averageAcceptedSimilarity = averageNeighborSimilarity(neighbors);
    const density = localDensityStats(neighbors, validNodes.length, contract.neighborhood.k);
    const hubness = hubnessStats(neighbors, validNodes);
    const rejectedNeighbors = rejectedNeighborSummary(validNodes, dimensions, contract.neighborhood.minSimilarity);
    const neighborPairKeys = directedNeighborPairKeys(validNodes, neighbors);
    const neighborGraphHash = digest(neighborPairKeys);
    const stability = neighborStabilityStats(neighborPairKeys, neighborGraphHash, previousReceipt || null);
    const trustworthiness = trustworthinessScore(density, hubness, averageAcceptedSimilarity, rejectedNeighbors.count, validNodes.length);
    const checks: HybridEmbeddingValidationReceipt['checks'] = {
        neighborStability: stability.status,
        continuity: continuityStatus(candidateSupport),
        clusterDensity: densityStatus(density, validNodes.length),
        hubness: hubnessStatus(hubness, validNodes.length),
        connectedComponents: validNodes.length > 1 && components.count > 0 ? 'passed' : 'pending',
        badNeighborRejection: dimensionMismatchCount > 0 ? 'failed' : 'passed',
    };
    const status = receiptStatus(Object.values(checks));
    return {
        receiptId: `hybrid-validation:${digest([contract.artifactId, contract.inputHash, status])}`,
        status,
        generatedBy: 'frontend-contract',
        checks,
        metrics: {
            nodeCount: payload.nodes.length,
            validNodeCount: validNodes.length,
            vectorDimensions: dimensions,
            dimensionMismatchCount,
            neighborPairs: neighborPairKeys.length,
            neighborPairKeys,
            neighborGraphHash,
            previousNeighborGraphHash: stability.previousHash,
            stableNeighborPairs: stability.stablePairs,
            previousNeighborPairs: stability.previousPairs,
            neighborStabilityRatio: roundRatio(stability.ratio),
            trustworthinessScore: roundRatio(trustworthiness),
            continuityScore: roundRatio(candidateSupport.ratio),
            rejectedBadNeighbors: rejectedNeighbors.count,
            candidateEdgesTested: candidateSupport.tested,
            candidateEdgesInNeighborhood: candidateSupport.supported,
            candidateNeighborhoodSupport: roundRatio(candidateSupport.ratio),
            connectedComponents: components.count,
            largestComponentSize: components.largest,
            localDensityMin: roundRatio(density.min),
            localDensityAverage: roundRatio(density.average),
            localDensityMax: roundRatio(density.max),
            mutualNeighborPairs: hubness.mutualPairs,
            mutualNeighborRatio: roundRatio(hubness.mutualRatio),
            maxHubInbound: hubness.maxInbound,
            hubnessLimit: hubness.limit,
            hubnessFlaggedNodeIds: hubness.flaggedNodeIds,
            componentSizes: components.sizes,
            averageAcceptedSimilarity: roundRatio(averageAcceptedSimilarity),
        },
        rejectedNeighborReceipts: [...rejectedReceipts, ...rejectedNeighbors.receipts].slice(0, 32),
        evidence: validationEvidence(checks, candidateSupport, components, density, hubness, stability),
    };
}

function collectValidNodes(nodes: readonly HybridEmbeddingValidationNode[]): {
    validNodes: ValidNode[];
    dimensions: number | null;
    dimensionMismatchCount: number;
    rejectedReceipts: string[];
} {
    const validNodes: ValidNode[] = [];
    const rejectedReceipts: string[] = [];
    let dimensions: number | null = null;
    let dimensionMismatchCount = 0;
    for (const node of nodes) {
        const vector = normalizedVector(node.vector);
        if (!vector.length) {
            rejectedReceipts.push(`bad_neighbor:invalid_vector:${node.id}`);
            continue;
        }
        if (dimensions === null) {
            dimensions = vector.length;
        }
        if (vector.length !== dimensions) {
            dimensionMismatchCount += 1;
            rejectedReceipts.push(`bad_neighbor:dimension_mismatch:${node.id}:got_${vector.length}:expected_${dimensions}`);
            continue;
        }
        validNodes.push({ id: node.id, vector });
    }
    return { validNodes, dimensions, dimensionMismatchCount, rejectedReceipts };
}

function normalizedVector(vector: ArrayLike<number> | null | undefined): number[] {
    if (!vector?.length) return [];
    const values: number[] = [];
    let normSquared = 0;
    for (let index = 0; index < vector.length; index += 1) {
        const value = Number(vector[index]);
        if (!Number.isFinite(value)) return [];
        values.push(value);
        normSquared += value * value;
    }
    if (normSquared <= 0) return [];
    const norm = Math.sqrt(normSquared);
    return values.map((value) => value / norm);
}

function buildNeighbors(nodes: readonly ValidNode[], k: number, minSimilarity: number): Neighbor[][] {
    return nodes.map((node, sourceIndex) => {
        const row: Neighbor[] = [];
        for (let targetIndex = 0; targetIndex < nodes.length; targetIndex += 1) {
            if (targetIndex === sourceIndex) continue;
            const score = cosine(node.vector, nodes[targetIndex].vector);
            if (Number.isFinite(score) && score >= minSimilarity) {
                row.push({ targetIndex, score });
            }
        }
        row.sort((left, right) => right.score - left.score || nodes[left.targetIndex].id.localeCompare(nodes[right.targetIndex].id));
        return row.slice(0, Math.max(1, k));
    });
}

function rejectedNeighborSummary(nodes: readonly ValidNode[], dimensions: number | null, minSimilarity: number): RejectedNeighborSummary {
    if (dimensions === null || nodes.length < 2) return { count: 0, receipts: [] };
    let count = 0;
    const receipts: string[] = [];
    for (let source = 0; source < nodes.length; source += 1) {
        for (let target = 0; target < nodes.length; target += 1) {
            if (source === target) continue;
            const score = cosine(nodes[source].vector, nodes[target].vector);
            if (!Number.isFinite(score) || score < minSimilarity) {
                count += 1;
                if (receipts.length < 24) {
                    receipts.push(
                        `bad_neighbor:below_threshold:${nodes[source].id}->${nodes[target].id}:score_${roundRatio(score)}:min_${roundRatio(minSimilarity)}`
                    );
                }
            }
        }
    }
    return { count, receipts };
}

function candidateNeighborhoodSupport(
    edges: readonly HybridEmbeddingValidationEdge[],
    nodes: readonly ValidNode[],
    neighbors: readonly Neighbor[][],
): { tested: number; supported: number; ratio: number } {
    const nodeIndex = new Map(nodes.map((node, index) => [node.id, index]));
    let tested = 0;
    let supported = 0;
    for (const edge of edges) {
        const source = nodeIndex.get(edge.sourceId);
        const target = nodeIndex.get(edge.targetId);
        if (source === undefined || target === undefined) continue;
        tested += 1;
        if (
            neighbors[source].some((neighbor) => neighbor.targetIndex === target)
            || neighbors[target].some((neighbor) => neighbor.targetIndex === source)
        ) {
            supported += 1;
        }
    }
    return {
        tested,
        supported,
        ratio: tested > 0 ? supported / tested : 0,
    };
}

function connectedComponents(nodeCount: number, neighbors: readonly Neighbor[][]): { count: number; largest: number; sizes: number[] } {
    if (nodeCount === 0) return { count: 0, largest: 0, sizes: [] };
    const visited = new Array<boolean>(nodeCount).fill(false);
    const sizes: number[] = [];
    let count = 0;
    let largest = 0;
    for (let start = 0; start < nodeCount; start += 1) {
        if (visited[start]) continue;
        count += 1;
        let size = 0;
        const stack = [start];
        visited[start] = true;
        while (stack.length) {
            const current = stack.pop() as number;
            size += 1;
            for (const neighbor of neighbors[current]) {
                if (visited[neighbor.targetIndex]) continue;
                visited[neighbor.targetIndex] = true;
                stack.push(neighbor.targetIndex);
            }
        }
        largest = Math.max(largest, size);
        sizes.push(size);
    }
    sizes.sort((left, right) => right - left);
    return { count, largest, sizes };
}

function localDensityStats(neighbors: readonly Neighbor[][], nodeCount: number, k: number): LocalDensityStats {
    if (nodeCount < 2 || neighbors.length === 0) return { min: 0, average: 0, max: 0 };
    const denominator = Math.max(1, Math.min(Math.max(1, k), nodeCount - 1));
    let min = Number.POSITIVE_INFINITY;
    let max = 0;
    let total = 0;
    for (const row of neighbors) {
        const density = row.length / denominator;
        min = Math.min(min, density);
        max = Math.max(max, density);
        total += density;
    }
    return {
        min: Number.isFinite(min) ? min : 0,
        average: total / neighbors.length,
        max,
    };
}

function hubnessStats(neighbors: readonly Neighbor[][], nodes: readonly ValidNode[]): HubnessStats {
    const nodeCount = nodes.length;
    if (nodeCount < 2) return { mutualPairs: 0, mutualRatio: 0, maxInbound: 0, limit: 0, flaggedNodeIds: [] };
    const inbound = new Array<number>(nodeCount).fill(0);
    const mutualPairs = new Set<string>();
    let directedEdges = 0;
    let mutualDirectedEdges = 0;
    for (let source = 0; source < neighbors.length; source += 1) {
        for (const neighbor of neighbors[source]) {
            directedEdges += 1;
            inbound[neighbor.targetIndex] += 1;
            if (neighbors[neighbor.targetIndex]?.some((candidate) => candidate.targetIndex === source)) {
                mutualDirectedEdges += 1;
                mutualPairs.add(source < neighbor.targetIndex ? `${source}:${neighbor.targetIndex}` : `${neighbor.targetIndex}:${source}`);
            }
        }
    }
    const averageInbound = directedEdges > 0 ? directedEdges / nodeCount : 0;
    const limit = Math.max(2, Math.ceil(averageInbound * 2.5));
    return {
        mutualPairs: mutualPairs.size,
        mutualRatio: directedEdges > 0 ? mutualDirectedEdges / directedEdges : 0,
        maxInbound: inbound.reduce((max, value) => Math.max(max, value), 0),
        limit,
        flaggedNodeIds: inbound
            .map((count, index) => ({ count, id: nodes[index].id }))
            .filter((entry) => entry.count > limit)
            .map((entry) => entry.id),
    };
}

function directedNeighborPairKeys(nodes: readonly ValidNode[], neighbors: readonly Neighbor[][]): string[] {
    const keys: string[] = [];
    for (let source = 0; source < neighbors.length; source += 1) {
        for (const neighbor of neighbors[source]) {
            keys.push(`${nodes[source].id}->${nodes[neighbor.targetIndex].id}`);
        }
    }
    keys.sort();
    return keys;
}

function neighborStabilityStats(
    currentKeys: readonly string[],
    currentHash: string,
    previousReceipt: HybridEmbeddingValidationReceipt | null,
): NeighborStabilityStats {
    const previousMetrics = previousReceipt?.metrics;
    const previousHash = previousMetrics?.neighborGraphHash || null;
    const previousKeys = previousMetrics?.neighborPairKeys || [];
    if (!previousHash) {
        return { status: 'pending', previousHash: null, stablePairs: 0, previousPairs: 0, ratio: 0 };
    }
    if (!previousKeys.length) {
        const stable = previousHash === currentHash;
        return {
            status: stable ? 'passed' : 'failed',
            previousHash,
            stablePairs: stable ? currentKeys.length : 0,
            previousPairs: previousMetrics?.neighborPairs || 0,
            ratio: stable ? 1 : 0,
        };
    }
    const current = new Set(currentKeys);
    let stablePairs = 0;
    for (const key of previousKeys) {
        if (current.has(key)) stablePairs += 1;
    }
    const ratio = previousKeys.length > 0 ? stablePairs / previousKeys.length : 0;
    return {
        status: ratio >= 0.8 ? 'passed' : 'failed',
        previousHash,
        stablePairs,
        previousPairs: previousKeys.length,
        ratio,
    };
}

function trustworthinessScore(
    density: LocalDensityStats,
    hubness: HubnessStats,
    averageAcceptedSimilarity: number,
    rejectedBadNeighbors: number,
    nodeCount: number,
): number {
    if (nodeCount < 2) return 0;
    const possibleDirectedPairs = nodeCount * (nodeCount - 1);
    const rejectionPenalty = 1 - Math.min(1, rejectedBadNeighbors / Math.max(1, possibleDirectedPairs));
    const hubnessPenalty = hubness.maxInbound <= hubness.limit || hubness.maxInbound === 0
        ? 1
        : hubness.limit / hubness.maxInbound;
    return Math.max(0, averageAcceptedSimilarity)
        * density.average
        * Math.max(0, hubness.mutualRatio)
        * rejectionPenalty
        * hubnessPenalty;
}

function continuityStatus(candidateSupport: { tested: number; ratio: number }): HybridEmbeddingValidationStatus {
    if (candidateSupport.tested === 0) return 'pending';
    return candidateSupport.ratio >= 0.5 ? 'passed' : 'failed';
}

function densityStatus(density: LocalDensityStats, nodeCount: number): HybridEmbeddingValidationStatus {
    if (nodeCount < 2) return 'pending';
    return density.min > 0 && density.average >= 0.5 ? 'passed' : 'failed';
}

function hubnessStatus(hubness: HubnessStats, nodeCount: number): HybridEmbeddingValidationStatus {
    if (nodeCount < 2) return 'pending';
    return hubness.mutualRatio >= 0.5 && hubness.maxInbound <= hubness.limit ? 'passed' : 'failed';
}

function receiptStatus(statuses: readonly HybridEmbeddingValidationStatus[]): HybridEmbeddingValidationStatus {
    if (statuses.includes('failed')) return 'failed';
    if (statuses.includes('pending')) return 'pending';
    return 'passed';
}

function validationEvidence(
    checks: HybridEmbeddingValidationReceipt['checks'],
    candidateSupport: { tested: number; supported: number },
    components: { count: number; largest: number },
    density: LocalDensityStats,
    hubness: HubnessStats,
    stability: NeighborStabilityStats,
): string[] {
    return [
        `neighbor_stability:${checks.neighborStability}:stable_${stability.stablePairs}/${stability.previousPairs}:ratio_${roundRatio(stability.ratio)}`,
        `continuity:${checks.continuity}:${candidateSupport.supported}/${candidateSupport.tested}_candidate_edges_in_topk`,
        `cluster_density:${checks.clusterDensity}:min_${roundRatio(density.min)}:avg_${roundRatio(density.average)}:max_${roundRatio(density.max)}`,
        `hubness:${checks.hubness}:mutual_${roundRatio(hubness.mutualRatio)}:max_inbound_${hubness.maxInbound}:limit_${hubness.limit}:flagged_${hubness.flaggedNodeIds.length}`,
        `connected_components:${checks.connectedComponents}:${components.count}_components:largest_${components.largest}`,
        `bad_neighbor_rejection:${checks.badNeighborRejection}`,
    ];
}

function averageNeighborSimilarity(neighbors: readonly Neighbor[][]): number {
    let total = 0;
    let count = 0;
    for (const row of neighbors) {
        for (const neighbor of row) {
            total += neighbor.score;
            count += 1;
        }
    }
    return count > 0 ? total / count : 0;
}

function cosine(left: readonly number[], right: readonly number[]): number {
    if (left.length !== right.length || !left.length) return Number.NaN;
    let sum = 0;
    for (let index = 0; index < left.length; index += 1) {
        sum += left[index] * right[index];
    }
    return sum;
}

function roundRatio(value: number): number {
    return Number.isFinite(value) ? Math.round(value * 10_000) / 10_000 : 0;
}

function digest(parts: readonly string[]): string {
    let hash = FNV_OFFSET;
    for (const part of parts) {
        hash = updateHashString(hash, part);
        hash = updateHashString(hash, '\u001f');
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

function updateHashString(hash: number, value: string): number {
    let next = hash >>> 0;
    for (let index = 0; index < value.length; index += 1) {
        next ^= value.charCodeAt(index);
        next = Math.imul(next, FNV_PRIME) >>> 0;
    }
    return next;
}
