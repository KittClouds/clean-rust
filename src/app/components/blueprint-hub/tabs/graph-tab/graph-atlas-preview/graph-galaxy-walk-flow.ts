import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

const DEFAULT_BRANCH_LIMIT = 1800;
const MAX_WALK_DEPTH = 8;
const MAX_VISITED_PER_DOCUMENT = 4096;

const STRUCTURAL_EDGE = /target-parent|note-chunk|chunk-anchor|chunk-entity|anchor-entity|event-chunk|event-entity|memory-entity/i;

export interface GalaxyWalkBranch {
    key: string;
    root: number;
    edge: number;
    source: number;
    target: number;
    depth: number;
    treeDepth: number;
}

interface OrientedEdge {
    edge: number;
    source: number;
    target: number;
}

interface PendingNode {
    node: number;
    depth: number;
}

export function buildGalaxyWalkBranches(
    data: Pick<GalaxySceneV2,
        'ids' | 'kinds' | 'edgePairs' | 'edgeTypes' | 'edgeKinds' | 'edgeAlpha' | 'hierarchyHints'>,
    limit = DEFAULT_BRANCH_LIMIT,
): GalaxyWalkBranch[] {
    if (data.ids.length === 0 || data.edgePairs.length < 2 || limit <= 0) return [];

    const roots = documentRoots(data.ids, data.kinds);
    const adjacency = buildAdjacency(data);
    const forests = roots.map((root) => branchesForRoot(data, adjacency, root));
    const branches: GalaxyWalkBranch[] = [];
    const maxDepth = forests.reduce((max, forest) => Math.max(max, forest[0]?.treeDepth || 0), 0);

    // Breadth-first round robin guarantees every document and every first-level
    // root is represented before the performance cap can trim deep leaves.
    for (let depth = 0; depth < maxDepth; depth++) {
        const levelBuckets = forests.map((forest) => forest.filter((branch) => branch.depth === depth));
        const levelWidth = levelBuckets.reduce((max, bucket) => Math.max(max, bucket.length), 0);
        for (let branchIndex = 0; branchIndex < levelWidth; branchIndex++) {
            for (const bucket of levelBuckets) {
                const branch = bucket[branchIndex];
                if (!branch) continue;
                branches.push(branch);
                if (branches.length >= limit) return branches;
            }
        }
    }
    return branches;
}

export function galaxyWalkHierarchyRank(id: string, kind: string): number {
    const normalizedId = id.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const normalizedKind = kind.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const value = `${normalizedId} ${normalizedKind}`;
    if (normalizedKind === 'note' || normalizedKind === 'document' || normalizedKind === 'documentroot' || /embednote/.test(normalizedId)) return 0;
    if (/structureroot|laneroot|section|subsection|chapter/.test(value)) return 1;
    if (/parentchunk|paragraphgroup/.test(value)) return 2;
    if (/leafchunk|chunk|paragraph|sentence|list|table|figure|codeblock|caption|scene|dialogueblock|actionblock/.test(value)) return 3;
    if (/anchor|evidence|claim|fact|event|statechange|relationbundle|procedurestep|nary|citation|rhetorical|method|result|instruction|decision|question/.test(value)) return 4;
    if (/entity|character|location|concept|item|creature|npc|network|state|memory/.test(value)) return 5;
    return 6;
}

function documentRoots(ids: string[], kinds: string[]): number[] {
    const roots: number[] = [];
    for (let index = 0; index < ids.length; index++) {
        if (isDocumentRoot(ids[index], kinds[index] || '')) roots.push(index);
    }
    return roots.sort((left, right) => ids[left].localeCompare(ids[right]));
}

function isDocumentRoot(id: string, kind: string): boolean {
    const normalizedKind = kind.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const normalizedId = id.toLowerCase();
    return normalizedKind === 'note'
        || normalizedKind === 'document'
        || normalizedKind === 'documentroot'
        || normalizedId.startsWith('embed:note:')
        || normalizedId.startsWith('note:')
        || normalizedId.startsWith('document:');
}

function buildAdjacency(
    data: Pick<GalaxySceneV2, 'ids' | 'kinds' | 'edgePairs' | 'edgeTypes' | 'edgeKinds' | 'edgeAlpha' | 'hierarchyHints'>,
): OrientedEdge[][] {
    const adjacency = Array.from({ length: data.ids.length }, () => [] as OrientedEdge[]);
    const hintedParents = new Set<string>();
    for (const hint of data.hierarchyHints || []) {
        if (hint.parentNodeId) hintedParents.add(`${hint.parentNodeId}\u0000${hint.nodeId}`);
    }

    for (let edge = 0; edge < data.edgePairs.length / 2; edge++) {
        const rawSource = data.edgePairs[edge * 2];
        const rawTarget = data.edgePairs[edge * 2 + 1];
        if (rawSource === rawTarget || rawSource >= data.ids.length || rawTarget >= data.ids.length) continue;

        const forwardHint = hintedParents.has(`${data.ids[rawSource]}\u0000${data.ids[rawTarget]}`);
        const reverseHint = hintedParents.has(`${data.ids[rawTarget]}\u0000${data.ids[rawSource]}`);
        const edgeType = data.edgeTypes?.[edge] || '';
        if (data.edgeKinds[edge] !== 2 && !STRUCTURAL_EDGE.test(edgeType) && !forwardHint && !reverseHint) continue;

        const sourceRank = galaxyWalkHierarchyRank(data.ids[rawSource], data.kinds[rawSource] || '');
        const targetRank = galaxyWalkHierarchyRank(data.ids[rawTarget], data.kinds[rawTarget] || '');
        const reverse = reverseHint || (!forwardHint && sourceRank > targetRank);
        const source = reverse ? rawTarget : rawSource;
        const target = reverse ? rawSource : rawTarget;
        adjacency[source].push({ edge, source, target });
    }

    for (const edges of adjacency) {
        edges.sort((left, right) => {
            const rankDelta = galaxyWalkHierarchyRank(data.ids[left.target], data.kinds[left.target] || '')
                - galaxyWalkHierarchyRank(data.ids[right.target], data.kinds[right.target] || '');
            if (rankDelta !== 0) return rankDelta;
            const confidenceDelta = (data.edgeAlpha[right.edge] || 0) - (data.edgeAlpha[left.edge] || 0);
            return confidenceDelta || data.ids[left.target].localeCompare(data.ids[right.target]);
        });
    }
    return adjacency;
}

function branchesForRoot(
    data: Pick<GalaxySceneV2, 'ids' | 'kinds'>,
    adjacency: OrientedEdge[][],
    root: number,
): GalaxyWalkBranch[] {
    const queue: PendingNode[] = [{ node: root, depth: 0 }];
    const nodeDepth = new Map<number, number>([[root, 0]]);
    const seenEdges = new Set<number>();
    const branches: GalaxyWalkBranch[] = [];
    let cursor = 0;

    while (cursor < queue.length && nodeDepth.size < MAX_VISITED_PER_DOCUMENT) {
        const current = queue[cursor++];
        if (current.depth >= MAX_WALK_DEPTH) continue;
        for (const candidate of adjacency[current.node]) {
            if (seenEdges.has(candidate.edge)) continue;
            if (candidate.target !== root && isDocumentRoot(data.ids[candidate.target], data.kinds[candidate.target] || '')) continue;

            const nextDepth = current.depth + 1;
            const knownDepth = nodeDepth.get(candidate.target);
            if (knownDepth !== undefined && knownDepth < nextDepth) continue;
            seenEdges.add(candidate.edge);
            branches.push({
                key: `${data.ids[root]}:${candidate.edge}`,
                root,
                edge: candidate.edge,
                source: candidate.source,
                target: candidate.target,
                depth: current.depth,
                treeDepth: 0,
            });
            if (knownDepth === undefined) {
                nodeDepth.set(candidate.target, nextDepth);
                queue.push({ node: candidate.target, depth: nextDepth });
            }
        }
    }

    const treeDepth = branches.reduce((max, branch) => Math.max(max, branch.depth + 1), 0);
    for (const branch of branches) branch.treeDepth = treeDepth;
    return branches;
}
