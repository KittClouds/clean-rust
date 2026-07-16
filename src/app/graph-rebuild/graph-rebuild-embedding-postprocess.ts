import type {
    GraphRebuildEmbeddingBackboneEdge,
    GraphRebuildEmbeddingCluster,
    GraphRebuildEmbeddingClusterRole,
    GraphRebuildEmbeddingGraphPostProcess,
    GraphRebuildEmbeddingProfile,
    GraphRebuildEmbeddingTarget,
    GraphRebuildEmbeddingTargetPostProcess,
    GraphRebuildProductLaneKind,
    GraphRebuildProductLaneFeatures,
    GraphRebuildProductTopologyRegion,
    GraphRebuildProductTopologyRegionRole,
} from './graph-rebuild-snapshot';
import {
    embeddingModelAdapterFromProfile,
    normalizeEmbeddingProfile,
    sparseCosine,
    sparseEmbeddingSignature,
    type SparseEmbeddingSignature,
} from './graph-rebuild-embedding-signatures';
import type { GraphRebuildCpuProfiler } from './graph-rebuild-cpu-profile';

const NEIGHBOR_LIMIT = 6;
const BACKBONE_MIN_SCORE = 0.18;
const BRIDGE_MIN_SCORE = 0.13;
const FULL_PAIR_TARGET_LIMIT = 320;
const PAIRS_PER_TARGET_LIMIT = 72;
const LANE_BUCKET_SAMPLE_LIMIT = 96;
const BRIDGE_REPRESENTATIVE_LIMIT = 28;

interface Neighbor {
    target: number;
    score: number;
}

interface PairPlan {
    pairs: Array<[number, number]>;
    theoreticalPairCount: number;
}

export function buildGraphRebuildEmbeddingGraphPostProcess(
    targets: GraphRebuildEmbeddingTarget[],
    profileInput?: Partial<GraphRebuildEmbeddingProfile>,
    cpuProfiler?: GraphRebuildCpuProfiler,
): GraphRebuildEmbeddingGraphPostProcess {
    const profile = normalizeEmbeddingProfile(profileInput);
    const adapter = embeddingModelAdapterFromProfile(profile);
    let phaseStarted = performance.now();
    const signatures = targets.map((target) => sparseEmbeddingSignature(target, profile.selectedDimensions));
    cpuProfiler?.add('snapshotEmbeddingSignaturesMs', phaseStarted);
    phaseStarted = performance.now();
    const plan = buildNeighborPairPlan(targets);
    cpuProfiler?.add('snapshotEmbeddingPairPlanMs', phaseStarted);
    phaseStarted = performance.now();
    const neighbors = buildMutualNeighbors(signatures, plan);
    cpuProfiler?.add('snapshotEmbeddingNeighborsMs', phaseStarted);
    phaseStarted = performance.now();
    const clusters = clusterTargets(targets, neighbors);
    cpuProfiler?.add('snapshotEmbeddingClustersMs', phaseStarted);
    phaseStarted = performance.now();
    const baseTargetRows = buildTargetRows(targets, clusters, neighbors);
    const backboneEdges = buildBackboneEdges(targets, baseTargetRows, neighbors);
    const { rows: targetRows, regions: productTopologyRegions } = attachProductTopologyRegions(
        baseTargetRows,
        clusters,
        backboneEdges,
    );
    const bridgeEdges = backboneEdges.filter((edge) => edge.role === 'bridge');
    const outlierTargetIds = targetRows.filter((row) => row.outlierScore >= 0.72).map((row) => row.targetId);
    const largestClusterSize = clusters.reduce((max, cluster) => Math.max(max, cluster.size), 0);
    const meanNeighborCount = targetRows.length
        ? targetRows.reduce((sum, row) => sum + row.neighborCount, 0) / targetRows.length
        : 0;
    cpuProfiler?.add('snapshotEmbeddingRowsEdgesMs', phaseStarted);

    return {
        schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
        profile,
        adapter,
        targetCount: targets.length,
        vectorDimensions: profile.selectedDimensions,
        clusters,
        productTopologyRegions,
        targets: targetRows,
        backboneEdges,
        bridgeEdges,
        outlierTargetIds,
        metrics: {
            clusterCount: clusters.length,
            singletonCount: clusters.filter((cluster) => cluster.size === 1).length,
            largestClusterSize,
            largestClusterRatio: targets.length ? round(largestClusterSize / targets.length) : 0,
            backboneEdgeCount: backboneEdges.length,
            bridgeEdgeCount: bridgeEdges.length,
            outlierCount: outlierTargetIds.length,
            maxHubScore: targetRows.reduce((max, row) => Math.max(max, row.hubScore), 0),
            meanNeighborCount: round(meanNeighborCount),
            plannedPairCount: plan.pairs.length,
            theoreticalPairCount: plan.theoreticalPairCount,
            prunedPairCount: Math.max(0, plan.theoreticalPairCount - plan.pairs.length),
        },
    };
}

function buildMutualNeighbors(signatures: SparseEmbeddingSignature[], plan: PairPlan): Neighbor[][] {
    const directed = signatures.map((): Neighbor[] => []);
    for (const [i, j] of plan.pairs) {
        const score = sparseCosine(signatures[i], signatures[j]);
        if (score < BRIDGE_MIN_SCORE) continue;
        pushTopNeighbor(directed[i], { target: j, score });
        pushTopNeighbor(directed[j], { target: i, score });
    }
    return directed.map((list, index) =>
        list.filter((neighbor) => directed[neighbor.target].some((other) => other.target === index)),
    );
}

function buildNeighborPairPlan(targets: GraphRebuildEmbeddingTarget[]): PairPlan {
    const targetCount = targets.length;
    const theoreticalPairCount = Math.max(0, Math.floor((targetCount * (targetCount - 1)) / 2));
    const pairs: Array<[number, number]> = [];
    const seen = new Set<number>();
    const degree = new Uint16Array(targetCount);
    const normalizedKinds = targets.map((target) => normalizeKind(target.kind));
    const signalScores = targets.map(targetSignalScore);
    const add = (left: number, right: number, force = false) => {
        if (left < 0 || right < 0) return;
        if (left === right) return;
        const a = Math.min(left, right);
        const b = Math.max(left, right);
        const key = a * targetCount + b;
        if (seen.has(key)) return;
        if (!force && degree[a] >= PAIRS_PER_TARGET_LIMIT && degree[b] >= PAIRS_PER_TARGET_LIMIT) return;
        seen.add(key);
        degree[a] += 1;
        degree[b] += 1;
        pairs.push([a, b]);
    };

    if (targetCount <= FULL_PAIR_TARGET_LIMIT) {
        for (let i = 0; i < targetCount; i += 1) {
            for (let j = i + 1; j < targetCount; j += 1) add(i, j, true);
        }
        return { pairs, theoreticalPairCount };
    }

    const byId = new Map(targets.map((target, index) => [target.id, index]));
    const buckets = new Map<string, number[]>();
    for (let index = 0; index < targetCount; index += 1) {
        const target = targets[index];
        if (target.noteId) mapArray(buckets, `note:${target.noteId}`).push(index);
        if (target.chunkId) mapArray(buckets, `chunk:${target.chunkId}`).push(index);
        if (target.entityId) mapArray(buckets, `entity:${target.entityId}`).push(index);
        const kind = normalizedKinds[index];
        mapArray(buckets, `kind:${kind}`).push(index);
        if (/event|temporal|causal/.test(kind)) mapArray(buckets, 'lane:story').push(index);
        if (/fact|memory/.test(kind)) mapArray(buckets, 'lane:evidence').push(index);
    }

    for (let index = 0; index < targetCount; index += 1) {
        const target = targets[index];
        if (target.noteId) add(index, byId.get(`embed:note:${target.noteId}`) ?? -1, true);
        if (target.chunkId) add(index, byId.get(`embed:chunk:${target.chunkId}`) ?? -1, true);
        if (target.entityId) add(index, byId.get(`embed:entity:${target.entityId}`) ?? -1, true);
    }

    for (const [key, values] of buckets) {
        const limit = key.startsWith('lane:') || key.startsWith('kind:') ? LANE_BUCKET_SAMPLE_LIMIT : Math.floor(LANE_BUCKET_SAMPLE_LIMIT * 0.7);
        addBucketPairs(spreadRanked(values, targets, limit, signalScores), add);
    }

    const representatives = representativeIndicesByKind(targets, normalizedKinds, signalScores);
    for (let index = 0; index < targetCount; index += 1) {
        for (const rep of representatives) {
            if (normalizedKinds[index] === normalizedKinds[rep]) continue;
            add(index, rep);
        }
    }
    return { pairs, theoreticalPairCount };
}

function addBucketPairs(indices: number[], add: (left: number, right: number) => void): void {
    for (let i = 0; i < indices.length; i += 1) {
        for (let j = i + 1; j < indices.length; j += 1) add(indices[i], indices[j]);
    }
}

function spreadRanked(
    indices: number[],
    targets: GraphRebuildEmbeddingTarget[],
    limit: number,
    signalScores: number[],
): number[] {
    const ranked = [...indices].sort((left, right) =>
        signalScores[right] - signalScores[left]
        || targets[left].id.localeCompare(targets[right].id),
    );
    if (ranked.length <= limit) return ranked;
    const out: number[] = [];
    const step = (ranked.length - 1) / Math.max(1, limit - 1);
    for (let index = 0; index < limit; index += 1) out.push(ranked[Math.round(index * step)]);
    return out;
}

function representativeIndicesByKind(
    targets: GraphRebuildEmbeddingTarget[],
    normalizedKinds: string[],
    signalScores: number[],
): number[] {
    const byKind = new Map<string, number[]>();
    for (let index = 0; index < targets.length; index += 1) {
        mapArray(byKind, normalizedKinds[index]).push(index);
    }
    return [...byKind.values()].flatMap((indices) =>
        spreadRanked(indices, targets, BRIDGE_REPRESENTATIVE_LIMIT, signalScores),
    );
}

function targetSignalScore(target: GraphRebuildEmbeddingTarget): number {
    const kind = normalizeKind(target.kind);
    let score =
        /causal/.test(kind) ? 940 :
        /temporal/.test(kind) ? 930 :
        /event/.test(kind) ? 910 :
        /memory/.test(kind) ? 890 :
        /graph-fact|fact/.test(kind) ? 860 :
        /chunk|note/.test(kind) ? 830 :
        /entity/.test(kind) ? 800 :
        /anchor/.test(kind) ? 760 : 700;
    const text = `${target.label} ${target.text}`.toLowerCase();
    if (text.includes('[accepted]')) score += 42;
    if (/confidence:([0-9.]+)/.test(text)) score += Math.round(Number(text.match(/confidence:([0-9.]+)/)?.[1] || 0) * 60);
    if (/evidence_context:/.test(text)) score += 24;
    if (/before|after|because|causes|memory_key|chunk_role|meaning_cues/.test(text)) score += 18;
    score += Math.min(54, target.evidenceIds.length * 6);
    return score;
}

function pushTopNeighbor(list: Neighbor[], neighbor: Neighbor): void {
    list.push(neighbor);
    list.sort((left, right) => right.score - left.score || left.target - right.target);
    if (list.length > NEIGHBOR_LIMIT) list.length = NEIGHBOR_LIMIT;
}

function clusterTargets(
    targets: GraphRebuildEmbeddingTarget[],
    neighbors: Neighbor[][],
): GraphRebuildEmbeddingCluster[] {
    const visited = new Uint8Array(targets.length);
    const clusters: GraphRebuildEmbeddingCluster[] = [];
    for (let index = 0; index < targets.length; index += 1) {
        if (visited[index]) continue;
        const members = collectComponent(index, neighbors, visited);
        const medoid = medoidIndex(members, neighbors);
        const density = clusterDensity(members, neighbors);
        const outliers = members.filter((member) => outlierScore(member, neighbors) >= 0.72);
        clusters.push({
            id: `embedding-cluster:${clusters.length}`,
            role: clusterRole(members.map((member) => targets[member])),
            targetIds: members.map((member) => targets[member].id),
            medoidTargetId: targets[medoid]?.id || targets[index]?.id || '',
            size: members.length,
            density,
            confidence: round(Math.min(1, 0.42 + density * 0.48 + Math.min(members.length, 8) * 0.012)),
            topKinds: topKinds(members.map((member) => targets[member])),
            outlierTargetIds: outliers.map((member) => targets[member].id),
        });
    }
    return clusters.sort((left, right) => right.size - left.size || left.id.localeCompare(right.id));
}

function collectComponent(start: number, neighbors: Neighbor[][], visited: Uint8Array): number[] {
    const stack = [start];
    const members: number[] = [];
    visited[start] = 1;
    while (stack.length) {
        const current = stack.pop()!;
        members.push(current);
        for (const neighbor of neighbors[current]) {
            if (neighbor.score < BACKBONE_MIN_SCORE || visited[neighbor.target]) continue;
            visited[neighbor.target] = 1;
            stack.push(neighbor.target);
        }
    }
    return members.sort((left, right) => left - right);
}

function buildTargetRows(
    targets: GraphRebuildEmbeddingTarget[],
    clusters: GraphRebuildEmbeddingCluster[],
    neighbors: Neighbor[][],
): GraphRebuildEmbeddingTargetPostProcess[] {
    const clusterByTarget = new Map<string, GraphRebuildEmbeddingCluster>();
    for (const cluster of clusters) {
        for (const targetId of cluster.targetIds) clusterByTarget.set(targetId, cluster);
    }
    return targets.map((target, index) => {
        const cluster = clusterByTarget.get(target.id)!;
        const hubScore = round(Math.min(1, neighbors[index].length / NEIGHBOR_LIMIT));
        const outlier = outlierScore(index, neighbors);
        const lanes = productLaneFeatures(target, cluster, outlier, hubScore);
        return {
            targetId: target.id,
            clusterId: cluster.id,
            clusterRole: cluster.role,
            medoidTargetId: cluster.medoidTargetId,
            outlierScore: outlier,
            hubScore,
            neighborCount: neighbors[index].length,
            productLaneFeatures: lanes,
            productTopologyRegion: productTopologyRegion(target.id, cluster, lanes, 'core', [], []),
        };
    });
}

function buildBackboneEdges(
    targets: GraphRebuildEmbeddingTarget[],
    rows: GraphRebuildEmbeddingTargetPostProcess[],
    neighbors: Neighbor[][],
): GraphRebuildEmbeddingBackboneEdge[] {
    const rowsByIndex = rows;
    const edges: GraphRebuildEmbeddingBackboneEdge[] = [];
    const seen = new Set<string>();
    for (let source = 0; source < neighbors.length; source += 1) {
        for (const neighbor of neighbors[source]) {
            const target = neighbor.target;
            const key = source < target ? `${source}:${target}` : `${target}:${source}`;
            if (seen.has(key) || neighbor.score < BRIDGE_MIN_SCORE) continue;
            seen.add(key);
            const sameCluster = rowsByIndex[source].clusterId === rowsByIndex[target].clusterId;
            const role = sameCluster ? (neighbor.score >= 0.34 ? 'backbone' : 'local') : 'bridge';
            edges.push({
                id: `embedding-backbone:${targets[source].id}:${targets[target].id}`,
                sourceTargetId: targets[source].id,
                targetTargetId: targets[target].id,
                role,
                score: round(neighbor.score),
                semanticScore: round(neighbor.score),
                structuralScore: sameCluster ? 0.7 : 0.42,
                reason: [
                    sameCluster ? 'mutual semantic neighborhood' : 'semantic bridge across clusters',
                    `source_kind:${targets[source].kind}`,
                    `target_kind:${targets[target].kind}`,
                ],
            });
        }
    }
    return edges.sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
}

function attachProductTopologyRegions(
    rows: GraphRebuildEmbeddingTargetPostProcess[],
    clusters: GraphRebuildEmbeddingCluster[],
    edges: GraphRebuildEmbeddingBackboneEdge[],
): { rows: GraphRebuildEmbeddingTargetPostProcess[]; regions: GraphRebuildProductTopologyRegion[] } {
    const clusterById = new Map(clusters.map((cluster) => [cluster.id, cluster]));
    const bridgeTargets = new Map<string, Set<string>>();
    const backboneTargets = new Map<string, Set<string>>();
    for (const edge of edges) {
        const leftMap = edge.role === 'bridge' ? bridgeTargets : edge.role === 'backbone' ? backboneTargets : null;
        if (!leftMap) continue;
        mapSet(leftMap, edge.sourceTargetId).add(edge.targetTargetId);
        mapSet(leftMap, edge.targetTargetId).add(edge.sourceTargetId);
    }
    const regionById = new Map<string, GraphRebuildProductTopologyRegion>();
    const updated = rows.map((row) => {
        const cluster = clusterById.get(row.clusterId);
        const bridgeTargetIds = sortedIds(bridgeTargets.get(row.targetId));
        const backboneTargetIds = sortedIds(backboneTargets.get(row.targetId));
        const role = productRegionRole(row, bridgeTargetIds, backboneTargetIds);
        const region = productTopologyRegion(
            row.targetId,
            cluster,
            row.productLaneFeatures,
            role,
            bridgeTargetIds,
            backboneTargetIds,
        );
        regionById.set(region.id, region);
        return { ...row, productTopologyRegion: region };
    });
    const regions = [...regionById.values()].sort((left, right) => left.id.localeCompare(right.id));
    return { rows: updated, regions };
}

function productRegionRole(
    row: GraphRebuildEmbeddingTargetPostProcess,
    bridgeTargetIds: string[],
    backboneTargetIds: string[],
): GraphRebuildProductTopologyRegionRole {
    if (row.outlierScore >= 0.72) return 'outlier';
    if (bridgeTargetIds.length) return 'bridge';
    if (row.targetId === row.medoidTargetId) return 'core';
    if (backboneTargetIds.length || row.hubScore >= 0.72) return 'backbone';
    if (row.outlierScore >= 0.38 || row.neighborCount <= 1) return 'boundary';
    return 'core';
}

function productTopologyRegion(
    targetId: string,
    cluster: GraphRebuildEmbeddingCluster | undefined,
    lanes: GraphRebuildProductLaneFeatures,
    role: GraphRebuildProductTopologyRegionRole,
    bridgeTargetIds: string[],
    backboneTargetIds: string[],
): GraphRebuildProductTopologyRegion {
    const clusterId = cluster?.id || 'embedding-cluster:unknown';
    const medoidTargetId = cluster?.medoidTargetId || targetId;
    const roleConfidence = role === 'core' ? 0.18 : role === 'backbone' ? 0.16 : role === 'bridge' ? 0.15 : role === 'boundary' ? 0.1 : 0.06;
    return {
        id: `product-region:${clusterId}:${lanes.dominantLane}:${role}`,
        role,
        laneKind: lanes.dominantLane,
        clusterId,
        medoidTargetId,
        memberCount: cluster?.size || 1,
        density: cluster?.density || 0,
        confidence: round(Math.min(1, lanes.confidence * 0.68 + (cluster?.confidence || 0.2) * 0.18 + roleConfidence)),
        bridgeTargetIds,
        backboneTargetIds,
    };
}

function productLaneFeatures(
    target: GraphRebuildEmbeddingTarget,
    cluster: GraphRebuildEmbeddingCluster,
    outlierScoreValue: number,
    hubScore: number,
): GraphRebuildProductLaneFeatures {
    const kind = normalizeKind(target.kind);
    const relationDepth = /fact|event|memory|causal|temporal/.test(kind) ? 0.78 : kind === 'entity' ? 0.42 : 0.34;
    const documentDepth = target.chunkId ? 0.82 : target.noteId ? 0.68 : 0.22;
    const laneWeights: Record<GraphRebuildProductLaneKind, number> = {
        semantic: round(Math.max(0.12, 1 - outlierScoreValue * 0.72)),
        document: documentDepth,
        relation: relationDepth,
        temporal: /temporal|event/.test(kind) ? 0.82 : 0.12,
        causal: /causal/.test(kind) ? 0.86 : 0.1,
        evidence: /fact|memory/.test(kind) || target.evidenceIds.length > 1 ? 0.76 : 0.16,
        entity: /entity|anchor/.test(kind) ? 0.78 : 0.18,
    };
    return {
        semanticDepth: laneWeights.semantic,
        documentDepth,
        relationDepth,
        clusterRadius: round(Math.min(1, Math.sqrt(cluster.size) / 6)),
        fiberPhase: phase(target.id),
        confidence: round(Math.min(1, cluster.confidence * 0.72 + hubScore * 0.28)),
        dominantLane: dominantLane(laneWeights),
        laneWeights,
    };
}

function dominantLane(weights: Record<GraphRebuildProductLaneKind, number>): GraphRebuildProductLaneKind {
    return (Object.entries(weights) as [GraphRebuildProductLaneKind, number][])
        .sort((left, right) => right[1] - left[1] || laneRank(left[0]) - laneRank(right[0]))[0][0];
}

function laneRank(lane: GraphRebuildProductLaneKind): number {
    switch (lane) {
        case 'causal': return 0;
        case 'temporal': return 1;
        case 'entity': return 2;
        case 'document': return 3;
        case 'evidence': return 4;
        case 'relation': return 5;
        case 'semantic': return 6;
    }
}

function medoidIndex(members: number[], neighbors: Neighbor[][]): number {
    return members
        .map((member) => ({
            member,
            score: neighbors[member].reduce((sum, neighbor) => sum + neighbor.score, 0),
        }))
        .sort((left, right) => right.score - left.score || left.member - right.member)[0]?.member ?? members[0];
}

function clusterDensity(members: number[], neighbors: Neighbor[][]): number {
    if (members.length <= 1) return 0;
    const set = new Set(members);
    let links = 0;
    for (const member of members) links += neighbors[member].filter((neighbor) => set.has(neighbor.target)).length;
    return round(links / (members.length * (members.length - 1)));
}

function outlierScore(index: number, neighbors: Neighbor[][]): number {
    const list = neighbors[index];
    if (!list.length) return 1;
    const mean = list.reduce((sum, neighbor) => sum + neighbor.score, 0) / list.length;
    return round(Math.max(0, 1 - mean * 2.2));
}

function clusterRole(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingClusterRole {
    const counts = kindCounts(targets);
    const top = [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || '';
    if (/note|chunk|anchor/.test(top)) return 'document_region';
    if (/entity/.test(top)) return 'entity_region';
    if (/fact|memory/.test(top)) return 'fact_region';
    if (/event|temporal|causal/.test(top)) return 'event_region';
    return 'mixed_region';
}

function topKinds(targets: GraphRebuildEmbeddingTarget[]): string[] {
    return [...kindCounts(targets).entries()]
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .slice(0, 4)
        .map(([kind]) => kind);
}

function kindCounts(targets: GraphRebuildEmbeddingTarget[]): Map<string, number> {
    const counts = new Map<string, number>();
    for (const target of targets) {
        const kind = normalizeKind(target.kind);
        counts.set(kind, (counts.get(kind) || 0) + 1);
    }
    return counts;
}

function normalizeKind(kind: string): string {
    return String(kind || 'target').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

function phase(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return round((hash >>> 0) / 4294967295);
}

function mapSet<K, V>(map: Map<K, Set<V>>, key: K): Set<V> {
    let set = map.get(key);
    if (!set) {
        set = new Set<V>();
        map.set(key, set);
    }
    return set;
}

function mapArray<K, V>(map: Map<K, V[]>, key: K): V[] {
    let values = map.get(key);
    if (!values) {
        values = [];
        map.set(key, values);
    }
    return values;
}

function sortedIds(ids: Set<string> | undefined): string[] {
    return ids ? [...ids].sort().slice(0, 8) : [];
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
