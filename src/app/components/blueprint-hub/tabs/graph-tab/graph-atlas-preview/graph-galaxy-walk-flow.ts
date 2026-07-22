import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

const DEFAULT_BRANCH_LIMIT = 4096;
const MAX_WALK_DEPTH = 8;
const MAX_VISITED_PER_DOCUMENT = 4096;

const STRUCTURAL_EDGE = /target-parent|note-chunk|chunk-anchor|chunk-entity|anchor-entity|event-chunk|event-entity|memory-entity|contains|contained/i;

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

type WalkBranchData = Pick<GalaxySceneV2,
    'ids' | 'kinds' | 'edgePairs' | 'edgeTypes' | 'edgeKinds' | 'edgeAlpha' | 'hierarchyHints'>
    & Partial<Pick<GalaxySceneV2, 'sourceMode'>>;

export function buildGalaxyWalkBranches(
    data: WalkBranchData,
    limit = DEFAULT_BRANCH_LIMIT,
): GalaxyWalkBranch[] {
    if (data.ids.length === 0 || data.edgePairs.length < 2 || limit <= 0) return [];

    const roots = documentRoots(data.ids, data.kinds);
    const adjacency = buildAdjacency(data);
    const forests = roots.map((root) => branchesForRoot(data, adjacency, root));
    const branches: GalaxyWalkBranch[] = [];
    const walksDisplayedEdges = shouldWalkDisplayedEdges(data);
    const emittedEdges = walksDisplayedEdges ? new Set<number>() : null;
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
                if (emittedEdges?.has(branch.edge)) continue;
                emittedEdges?.add(branch.edge);
                branches.push(branch);
                if (branches.length >= limit) return branches;
            }
        }
    }
    if (shouldSupplementDisplayedEdges(data, branches) && branches.length < limit) {
        const seenEdges = emittedEdges ?? new Set(branches.map((branch) => branch.edge));
        branches.push(...displayedConnectionBranches(data, seenEdges, limit - branches.length));
    }
    return branches;
}

export function galaxyWalkHierarchyRank(id: string, kind: string): number {
    const normalizedId = id.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const normalizedKind = kind.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const value = `${normalizedId} ${normalizedKind}`;
    if (normalizedKind === 'note'
        || normalizedKind === 'document'
        || normalizedKind === 'documentroot'
        || /^atomdocument/.test(normalizedId)
        || /graphmodelv2atomdocument/.test(normalizedKind)
        || /embednote/.test(normalizedId)) return 0;
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
    const compactId = normalizedId.replace(/[^a-z0-9]+/g, '');
    return normalizedKind === 'note'
        || normalizedKind === 'document'
        || normalizedKind === 'documentroot'
        || /graphmodelv2atomdocument/.test(normalizedKind)
        || compactId.startsWith('atomdocument')
        || normalizedId.startsWith('embed:note:')
        || normalizedId.startsWith('note:')
        || normalizedId.startsWith('document:');
}

function buildAdjacency(data: WalkBranchData): OrientedEdge[][] {
    const adjacency = Array.from({ length: data.ids.length }, () => [] as OrientedEdge[]);
    const hintedParents = new Set<string>();
    const includeDisplayedEdges = shouldWalkDisplayedEdges(data);
    for (const hint of data.hierarchyHints || []) {
        if (hint.parentNodeId) hintedParents.add(`${hint.parentNodeId}\u0000${hint.nodeId}`);
    }

    for (let edge = 0; edge < data.edgePairs.length / 2; edge++) {
        const oriented = orientWalkEdge(data, hintedParents, edge, includeDisplayedEdges);
        if (oriented) adjacency[oriented.source].push(oriented);
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

function shouldWalkDisplayedEdges(data: WalkBranchData): boolean {
    return data.sourceMode === 'graph' || isNativePacketScene(data);
}

function shouldSupplementDisplayedEdges(data: WalkBranchData, branches: GalaxyWalkBranch[]): boolean {
    if (shouldWalkDisplayedEdges(data)) return true;
    return branches.length === 0 && isNativePacketScene(data);
}

function isNativePacketScene(data: WalkBranchData): boolean {
    return data.edgeTypes?.some((type) => type.toLowerCase() === 'native_edge') === true;
}

function displayedConnectionBranches(data: WalkBranchData, seenEdges: Set<number>, limit: number): GalaxyWalkBranch[] {
    if (limit <= 0) return [];
    const hintedParents = new Set<string>();
    for (const hint of data.hierarchyHints || []) {
        if (hint.parentNodeId) hintedParents.add(`${hint.parentNodeId}\u0000${hint.nodeId}`);
    }
    const branches: GalaxyWalkBranch[] = [];
    for (let edge = 0; edge < data.edgePairs.length / 2; edge++) {
        if (seenEdges.has(edge)) continue;
        const oriented = orientWalkEdge(data, hintedParents, edge, true);
        if (!oriented) continue;
        const depth = Math.min(
            MAX_WALK_DEPTH - 1,
            galaxyWalkHierarchyRank(data.ids[oriented.source], data.kinds[oriented.source] || ''),
        );
        branches.push({
            key: `displayed:${edge}`,
            root: oriented.source,
            edge,
            source: oriented.source,
            target: oriented.target,
            depth,
            treeDepth: depth + 1,
        });
    }
    branches.sort((left, right) =>
        left.depth - right.depth
        || (data.edgeAlpha[right.edge] || 0) - (data.edgeAlpha[left.edge] || 0)
        || data.ids[left.source].localeCompare(data.ids[right.source])
        || data.ids[left.target].localeCompare(data.ids[right.target]));
    return branches.slice(0, limit);
}

function orientWalkEdge(
    data: WalkBranchData,
    hintedParents: Set<string>,
    edge: number,
    includeDisplayedEdge: boolean,
): OrientedEdge | null {
    const rawSource = data.edgePairs[edge * 2];
    const rawTarget = data.edgePairs[edge * 2 + 1];
    if (rawSource === rawTarget || rawSource >= data.ids.length || rawTarget >= data.ids.length) return null;

    const forwardHint = hintedParents.has(`${data.ids[rawSource]}\u0000${data.ids[rawTarget]}`);
    const reverseHint = hintedParents.has(`${data.ids[rawTarget]}\u0000${data.ids[rawSource]}`);
    const edgeType = data.edgeTypes?.[edge] || '';
    if (!includeDisplayedEdge && data.edgeKinds[edge] !== 2 && !STRUCTURAL_EDGE.test(edgeType) && !forwardHint && !reverseHint) return null;

    const sourceRank = galaxyWalkHierarchyRank(data.ids[rawSource], data.kinds[rawSource] || '');
    const targetRank = galaxyWalkHierarchyRank(data.ids[rawTarget], data.kinds[rawTarget] || '');
    const reverse = reverseHint || (!forwardHint && sourceRank > targetRank);
    const source = reverse ? rawTarget : rawSource;
    const target = reverse ? rawSource : rawTarget;
    return { edge, source, target };
}
