const DIMMED_NODE_OPACITY = 0.14;
const DIMMED_EDGE_OPACITY = 0.08;

export const GALAXY_RENDERER_V3_DRAG_NODE_LIMIT = 384;
export const GALAXY_RENDERER_V3_NEIGHBOR_LIMIT = 128;
export const GALAXY_RENDERER_V3_FOCUS_EDGE_LIMIT = 4_096;
export const GALAXY_RENDERER_V3_CLICK_TRAVEL_LIMIT = 4;
export const GALAXY_RENDERER_V3_CLICK_HOLD_LIMIT_MS = 350;

export interface GalaxyRendererV3Neighborhood {
    nodes: Uint32Array;
    edges: Uint32Array;
    truncated: boolean;
}

export interface GalaxyRendererV3FocusUpdate extends GalaxyRendererV3Neighborhood {
    changedNodes: Uint32Array;
    changedEdges: Uint32Array;
    fullUpload: boolean;
}

export function galaxyRendererV3SuppressNodeActivation(
    nodeDragging: boolean,
    pointerTravel: number,
    heldMs: number,
): boolean {
    return nodeDragging
        && (pointerTravel > GALAXY_RENDERER_V3_CLICK_TRAVEL_LIMIT
            || heldMs >= GALAXY_RENDERER_V3_CLICK_HOLD_LIMIT_MS);
}

export function captureGalaxyRendererV3Positions(
    positions: Float32Array,
    indexes: Uint32Array,
): Float32Array {
    const snapshot = new Float32Array(indexes.length * 3);
    for (let index = 0; index < indexes.length; index++) {
        const sourceOffset = indexes[index] * 3;
        snapshot.set(positions.subarray(sourceOffset, sourceOffset + 3), index * 3);
    }
    return snapshot;
}

export function restoreGalaxyRendererV3Positions(
    positions: Float32Array,
    indexes: Uint32Array,
    snapshot: Float32Array,
): void {
    for (let index = 0; index < indexes.length; index++) {
        positions.set(snapshot.subarray(index * 3, index * 3 + 3), indexes[index] * 3);
    }
}

/** Packed resident-only interaction index. It never contains corpus objects or strings. */
export class GalaxyRendererV3InteractionState {
    readonly nodeOpacity: Float32Array;
    readonly edgeOpacity: Float32Array;

    private readonly offsets: Uint32Array;
    private readonly incidentEdges: Uint32Array;
    private focusedNode = -1;
    private focusedNeighborhood = emptyNeighborhood();

    constructor(
        readonly nodeCount: number,
        private readonly edgePairs: Uint32Array,
    ) {
        this.nodeOpacity = new Float32Array(nodeCount);
        this.edgeOpacity = new Float32Array(Math.floor(edgePairs.length / 2));
        this.nodeOpacity.fill(1);
        this.edgeOpacity.fill(1);
        const index = buildIncidentCsr(nodeCount, edgePairs);
        this.offsets = index.offsets;
        this.incidentEdges = index.incidentEdges;
    }

    applyFocus(nodeIndex: number): GalaxyRendererV3FocusUpdate {
        if (nodeIndex < 0 || nodeIndex >= this.nodeCount) {
            if (this.focusedNode < 0) return emptyFocusUpdate();
            this.nodeOpacity.fill(1);
            this.edgeOpacity.fill(1);
            this.focusedNode = -1;
            this.focusedNeighborhood = emptyNeighborhood();
            return { ...emptyNeighborhood(), changedNodes: new Uint32Array(0), changedEdges: new Uint32Array(0), fullUpload: true };
        }
        if (nodeIndex === this.focusedNode) {
            return { ...this.focusedNeighborhood, changedNodes: new Uint32Array(0), changedEdges: new Uint32Array(0), fullUpload: false };
        }
        const neighborhood = this.neighborhood(nodeIndex, GALAXY_RENDERER_V3_FOCUS_EDGE_LIMIT);
        const firstFocus = this.focusedNode < 0;
        const changedNodes = firstFocus
            ? new Uint32Array(0)
            : uniqueIndexes(this.focusedNode, this.focusedNeighborhood.nodes, nodeIndex, neighborhood.nodes);
        const changedEdges = firstFocus
            ? new Uint32Array(0)
            : uniqueIndexesFrom(this.focusedNeighborhood.edges, neighborhood.edges);
        if (firstFocus) {
            this.nodeOpacity.fill(DIMMED_NODE_OPACITY);
            this.edgeOpacity.fill(DIMMED_EDGE_OPACITY);
        } else {
            for (const node of changedNodes) this.nodeOpacity[node] = DIMMED_NODE_OPACITY;
            for (const edge of changedEdges) this.edgeOpacity[edge] = DIMMED_EDGE_OPACITY;
        }
        this.nodeOpacity[nodeIndex] = 1;
        for (const edge of neighborhood.edges) {
            const source = this.edgePairs[edge * 2];
            const target = this.edgePairs[edge * 2 + 1];
            this.edgeOpacity[edge] = 1;
            if (source < this.nodeOpacity.length) this.nodeOpacity[source] = 1;
            if (target < this.nodeOpacity.length) this.nodeOpacity[target] = 1;
        }
        this.focusedNode = nodeIndex;
        this.focusedNeighborhood = neighborhood;
        return { ...neighborhood, changedNodes, changedEdges, fullUpload: firstFocus };
    }

    neighborhood(nodeIndex: number, limit: number): GalaxyRendererV3Neighborhood {
        if (nodeIndex < 0 || nodeIndex >= this.nodeCount || limit <= 0) return emptyNeighborhood();
        const start = this.offsets[nodeIndex];
        const end = this.offsets[nodeIndex + 1];
        const count = Math.min(end - start, limit);
        const edges = this.incidentEdges.slice(start, start + count);
        const nodes = new Uint32Array(count);
        for (let index = 0; index < count; index++) {
            const edge = edges[index];
            const source = this.edgePairs[edge * 2];
            const target = this.edgePairs[edge * 2 + 1];
            nodes[index] = source === nodeIndex ? target : source;
        }
        return { nodes, edges, truncated: start + count < end };
    }
}

export function buildIncidentCsr(nodeCount: number, edgePairs: Uint32Array): {
    offsets: Uint32Array;
    incidentEdges: Uint32Array;
} {
    const offsets = new Uint32Array(nodeCount + 1);
    const edgeCount = Math.floor(edgePairs.length / 2);
    for (let edge = 0; edge < edgeCount; edge++) {
        const source = edgePairs[edge * 2];
        const target = edgePairs[edge * 2 + 1];
        if (source < nodeCount) offsets[source + 1]++;
        if (target < nodeCount && target !== source) offsets[target + 1]++;
    }
    for (let node = 1; node < offsets.length; node++) offsets[node] += offsets[node - 1];
    const incidentEdges = new Uint32Array(offsets[nodeCount]);
    const cursors = offsets.slice(0, nodeCount);
    for (let edge = 0; edge < edgeCount; edge++) {
        const source = edgePairs[edge * 2];
        const target = edgePairs[edge * 2 + 1];
        if (source < nodeCount) incidentEdges[cursors[source]++] = edge;
        if (target < nodeCount && target !== source) incidentEdges[cursors[target]++] = edge;
    }
    return { offsets, incidentEdges };
}

function emptyNeighborhood(): GalaxyRendererV3Neighborhood {
    return { nodes: new Uint32Array(0), edges: new Uint32Array(0), truncated: false };
}

function emptyFocusUpdate(): GalaxyRendererV3FocusUpdate {
    return { ...emptyNeighborhood(), changedNodes: new Uint32Array(0), changedEdges: new Uint32Array(0), fullUpload: false };
}

function uniqueIndexes(
    leftIdentity: number,
    left: Uint32Array,
    rightIdentity: number,
    right: Uint32Array,
): Uint32Array {
    const indexes = new Set<number>([leftIdentity, rightIdentity]);
    for (const index of left) indexes.add(index);
    for (const index of right) indexes.add(index);
    return Uint32Array.from(indexes);
}

function uniqueIndexesFrom(left: Uint32Array, right: Uint32Array): Uint32Array {
    const indexes = new Set<number>();
    for (const index of left) indexes.add(index);
    for (const index of right) indexes.add(index);
    return Uint32Array.from(indexes);
}
