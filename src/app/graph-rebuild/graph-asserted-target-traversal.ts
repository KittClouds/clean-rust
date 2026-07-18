import { assertGraphAssertedTruthAuthority } from './graph-asserted-truth-authority';
import type {
    GraphRetrievalLaneCandidate,
    GraphRetrievalTraversalReceipt,
} from './graph-retrieval-contract';
import { assertGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import type {
    GraphEvidenceTargetObjectKind,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export interface GraphAssertedTraversalOptions {
    limit: number;
    seedLimit: number;
    maxHops: number;
    maxVisited: number;
    maxEdges: number;
}

export interface GraphAssertedTraversalResult {
    candidates: GraphRetrievalLaneCandidate[];
    receipt: GraphRetrievalTraversalReceipt;
    truncated: boolean;
}

export interface GraphAssertedTargetTraversal {
    readonly assertedLinks: number;
    traverse(
        seeds: readonly GraphRetrievalLaneCandidate[],
        options: GraphAssertedTraversalOptions,
    ): GraphAssertedTraversalResult;
}

export function buildGraphAssertedTargetTraversal(snapshot: GraphRebuildSnapshot): GraphAssertedTargetTraversal {
    assertGraphAssertedTruthAuthority(snapshot);
    const registry = assertGraphEvidenceTargetRegistry(snapshot);
    const exposedIds = new Set(registry.exposedTargets.map((target) => target.id));
    const targetIdsBySource = new Map<string, string[]>();
    const targetIdsByObject = new Map<GraphEvidenceTargetObjectKind, Map<string, string[]>>();
    for (const target of registry.exposedTargets) {
        addLookup(targetIdsBySource, target.sourceId, target.id);
        const kind = registry.objectKind(target.id);
        if (kind) {
            let rows = targetIdsByObject.get(kind);
            if (!rows) {
                rows = new Map<string, string[]>();
                targetIdsByObject.set(kind, rows);
            }
            addLookup(rows, target.sourceId, target.id);
        }
    }

    const adjacency = new Map<string, Set<string>>();
    let assertedLinks = 0;
    const connect = (left: string | undefined, right: string | undefined): void => {
        if (!left || !right || left === right || !exposedIds.has(left) || !exposedIds.has(right)) return;
        let leftRows = adjacency.get(left);
        if (!leftRows) {
            leftRows = new Set<string>();
            adjacency.set(left, leftRows);
        }
        if (leftRows.has(right)) return;
        leftRows.add(right);
        let rightRows = adjacency.get(right);
        if (!rightRows) {
            rightRows = new Set<string>();
            adjacency.set(right, rightRows);
        }
        rightRows.add(left);
        assertedLinks += 1;
    };
    const connectSources = (leftSource: string, rightSource: string): void => {
        for (const left of targetIdsBySource.get(leftSource) || []) {
            for (const right of targetIdsBySource.get(rightSource) || []) connect(left, right);
        }
    };
    const connectObject = (
        objectKind: GraphEvidenceTargetObjectKind,
        objectId: string,
        otherSourceId: string,
    ): void => {
        for (const left of targetIdsByObject.get(objectKind)?.get(objectId) || []) {
            for (const right of targetIdsBySource.get(otherSourceId) || []) connect(left, right);
        }
    };

    for (const edge of snapshot.edges) connectSources(edge.sourceId, edge.targetId);
    for (const relationship of snapshot.relationships) {
        if (relationship.status !== 'accepted') continue;
        connectObject('relationship', relationship.id, relationship.sourceEntityId);
        connectObject('relationship', relationship.id, relationship.targetEntityId);
        connectSources(relationship.sourceEntityId, relationship.targetEntityId);
    }
    for (const event of snapshot.events) {
        for (const entityId of event.entityIds) connectObject('event', event.id, entityId);
        if (event.chunkId) connectObject('event', event.id, event.chunkId);
    }
    for (const episode of snapshot.episodes) {
        for (const eventId of episode.eventIds) connectObject('episode', episode.id, eventId);
        for (const entityId of episode.entityIds) connectObject('episode', episode.id, entityId);
    }
    for (const edge of snapshot.temporalEdges) {
        connectObject('temporal_edge', edge.id, edge.sourceId);
        connectObject('temporal_edge', edge.id, edge.targetId);
        connectSources(edge.sourceId, edge.targetId);
    }
    for (const edge of snapshot.causalEdges) {
        if (edge.status !== 'accepted') continue;
        connectObject('causal_edge', edge.id, edge.sourceId);
        connectObject('causal_edge', edge.id, edge.targetId);
        connectSources(edge.sourceId, edge.targetId);
    }
    for (const state of snapshot.memoryState) connectObject('memory_state', state.id, state.entityId);

    const evidenceChunk = new Map<string, string>();
    for (const anchor of snapshot.entityAnchors) {
        if (anchor.chunkId) evidenceChunk.set(anchor.id, anchor.chunkId);
    }
    for (const span of snapshot.documentSidecarSummary?.evidenceSpans || []) {
        if (span.chunkId) evidenceChunk.set(span.id, span.chunkId);
    }
    for (const target of registry.typedGraphObjects) {
        if (target.chunkId) connectSources(target.sourceId, target.chunkId);
        for (const evidenceId of target.evidenceIds) {
            const chunkId = evidenceChunk.get(evidenceId);
            if (chunkId) connectSources(target.sourceId, chunkId);
        }
    }

    return {
        assertedLinks,
        traverse: (seeds, options) => traverseAdjacency(adjacency, assertedLinks, seeds, options),
    };
}

function traverseAdjacency(
    adjacency: ReadonlyMap<string, ReadonlySet<string>>,
    assertedLinks: number,
    inputSeeds: readonly GraphRetrievalLaneCandidate[],
    options: GraphAssertedTraversalOptions,
): GraphAssertedTraversalResult {
    const seeds = bestSeeds(inputSeeds, options.seedLimit);
    const seedIds = new Set(seeds.map((seed) => seed.targetId));
    const queue = seeds.map((seed) => ({ targetId: seed.targetId, distance: 0, seedScore: seed.score }));
    const visited = new Map(queue.map((row) => [row.targetId, 0]));
    const discovered = new Map<string, { score: number; distance: number }>();
    let cursor = 0;
    let edgesExamined = 0;
    let truncated = false;

    while (cursor < queue.length) {
        const current = queue[cursor++];
        if (current.distance >= options.maxHops) continue;
        for (const neighbor of adjacency.get(current.targetId) || []) {
            if (edgesExamined >= options.maxEdges) {
                truncated = true;
                break;
            }
            edgesExamined += 1;
            const distance = current.distance + 1;
            if (!seedIds.has(neighbor)) {
                const score = current.seedScore * Math.pow(0.65, distance);
                const previous = discovered.get(neighbor);
                if (!previous || score > previous.score) discovered.set(neighbor, { score, distance });
            }
            const previousDistance = visited.get(neighbor);
            if (previousDistance !== undefined && previousDistance <= distance) continue;
            if (visited.size >= options.maxVisited) {
                truncated = true;
                continue;
            }
            visited.set(neighbor, distance);
            queue.push({ targetId: neighbor, distance, seedScore: current.seedScore });
        }
        if (edgesExamined >= options.maxEdges) break;
    }
    const candidates = [...discovered.entries()]
        .sort((left, right) => right[1].score - left[1].score || left[1].distance - right[1].distance
            || left[0].localeCompare(right[0]))
        .slice(0, options.limit)
        .map(([targetId, row], index) => ({
            targetId,
            score: roundScore(row.score),
            rank: index + 1,
            distance: row.distance,
        }));
    if (discovered.size > options.limit) truncated = true;
    return {
        candidates,
        truncated,
        receipt: {
            assertedLinks,
            seeds: seeds.length,
            maxHops: options.maxHops,
            visitedTargets: visited.size,
            edgesExamined,
            candidateEdgesTraversed: 0,
        },
    };
}

function bestSeeds(
    candidates: readonly GraphRetrievalLaneCandidate[],
    limit: number,
): GraphRetrievalLaneCandidate[] {
    const best = new Map<string, GraphRetrievalLaneCandidate>();
    for (const candidate of candidates) {
        const previous = best.get(candidate.targetId);
        if (!previous || candidate.score > previous.score) best.set(candidate.targetId, candidate);
    }
    return [...best.values()]
        .sort((left, right) => right.score - left.score || left.rank - right.rank
            || left.targetId.localeCompare(right.targetId))
        .slice(0, limit);
}

function addLookup(map: Map<string, string[]>, sourceId: string, targetId: string): void {
    const rows = map.get(sourceId);
    if (rows) rows.push(targetId);
    else map.set(sourceId, [targetId]);
}

function roundScore(value: number): number {
    return Math.round(value * 1_000_000) / 1_000_000;
}
