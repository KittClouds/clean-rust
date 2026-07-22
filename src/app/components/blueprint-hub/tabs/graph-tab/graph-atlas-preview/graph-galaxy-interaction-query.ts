import {
    GALAXY_LOCAL_PATH_EDGE_LIMIT,
    GALAXY_LOCAL_PATH_NODE_LIMIT,
    GALAXY_LOCAL_PATH_VISIT_LIMIT,
    GALAXY_LOCAL_REGION_QUERY_NODE_LIMIT,
    GALAXY_PATH_OVERLAY_EDGE_LIMIT,
    type GalaxyInteractionAuthority,
    type GalaxyInteractionRect,
    type GalaxyNativeInteractionQueryPort,
    type GalaxyPathOverlay,
} from './graph-galaxy-interaction.model';
import { galaxyIncidentEdges, type GalaxySceneV2 } from './graph-galaxy-scene-v2';

export interface GalaxyInteractionQueryControllerOptions {
    native?: GalaxyNativeInteractionQueryPort;
}

export class GalaxyInteractionQueryController {
    private token = 0;
    private regionAbort: AbortController | null = null;
    private pathAbort: AbortController | null = null;

    constructor(private readonly options: GalaxyInteractionQueryControllerOptions = {}) {}

    async region(
        scene: GalaxySceneV2,
        authority: GalaxyInteractionAuthority,
        rect: GalaxyInteractionRect,
        viewProjection: Float32Array,
        local: () => string[],
    ): Promise<string[]> {
        const token = ++this.token;
        this.regionAbort?.abort();
        const controller = new AbortController();
        this.regionAbort = controller;
        if (!this.options.native) {
            return scene.ids.length <= GALAXY_LOCAL_REGION_QUERY_NODE_LIMIT ? local() : [];
        }
        let result;
        try {
            result = await this.options.native.queryRegion({
                ...authority,
                token,
                rect,
                viewProjection,
                maxResults: GALAXY_LOCAL_REGION_QUERY_NODE_LIMIT,
            }, controller.signal);
        } catch (error) {
            if (controller.signal.aborted || isAbortError(error)) return [];
            throw error;
        }
        if (!this.accepts(authority, token, result, controller.signal)) return [];
        const ids: string[] = [];
        for (const index of result.nodeIndices) {
            if (index < scene.ids.length) ids.push(scene.ids[index]);
        }
        return ids;
    }

    async path(
        scene: GalaxySceneV2,
        authority: GalaxyInteractionAuthority,
        sourceNodeId: string,
        targetNodeId: string,
    ): Promise<GalaxyPathOverlay | null> {
        const token = ++this.token;
        this.pathAbort?.abort();
        const controller = new AbortController();
        this.pathAbort = controller;
        if (!this.options.native) {
            return boundedLocalGalaxyPath(scene, authority, token, sourceNodeId, targetNodeId);
        }
        let result;
        try {
            result = await this.options.native.queryPath({
                ...authority,
                token,
                sourceNodeId,
                targetNodeId,
                maxVisited: GALAXY_LOCAL_PATH_VISIT_LIMIT,
                maxPathEdges: GALAXY_PATH_OVERLAY_EDGE_LIMIT,
            }, controller.signal);
        } catch (error) {
            if (controller.signal.aborted || isAbortError(error)) return null;
            throw error;
        }
        if (!this.accepts(authority, token, result, controller.signal)) return null;
        if (
            result.edgeIndices.length > GALAXY_PATH_OVERLAY_EDGE_LIMIT
            || result.nodeIndices.length > GALAXY_PATH_OVERLAY_EDGE_LIMIT + 1
        ) {
            return null;
        }
        return result;
    }

    dispose(): void {
        this.regionAbort?.abort();
        this.pathAbort?.abort();
        this.regionAbort = null;
        this.pathAbort = null;
    }

    private accepts(
        authority: GalaxyInteractionAuthority,
        token: number,
        result: GalaxyInteractionAuthority & { token: number },
        signal: AbortSignal,
    ): boolean {
        return !signal.aborted
            && result.token === token
            && result.generationId === authority.generationId
            && result.manifoldId === authority.manifoldId
            && result.authorityReceipt === authority.authorityReceipt;
    }
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === 'AbortError';
}

export function boundedLocalGalaxyPath(
    scene: GalaxySceneV2,
    authority: GalaxyInteractionAuthority,
    token: number,
    sourceNodeId: string,
    targetNodeId: string,
): GalaxyPathOverlay | null {
    if (
        scene.ids.length > GALAXY_LOCAL_PATH_NODE_LIMIT
        || scene.edgePairs.length / 2 > GALAXY_LOCAL_PATH_EDGE_LIMIT
        || !scene.runtimeIndex
    ) {
        return null;
    }
    const start = scene.runtimeIndex.nodeById.get(sourceNodeId) ?? -1;
    const target = scene.runtimeIndex.nodeById.get(targetNodeId) ?? -1;
    if (start < 0 || target < 0 || start === target) return null;

    const previousNode = new Int32Array(scene.ids.length);
    const previousEdge = new Int32Array(scene.ids.length);
    const queue = new Uint32Array(Math.min(scene.ids.length, GALAXY_LOCAL_PATH_VISIT_LIMIT));
    previousNode.fill(-1);
    previousEdge.fill(-1);
    previousNode[start] = start;
    let head = 0;
    let tail = 0;
    let visited = 0;
    queue[tail++] = start;

    while (head < tail && previousNode[target] < 0 && visited < GALAXY_LOCAL_PATH_VISIT_LIMIT) {
        const current = queue[head++];
        visited += 1;
        for (const edgeIndex of galaxyIncidentEdges(scene, current)) {
            const sourceIndex: number = scene.edgePairs[edgeIndex * 2];
            const destinationIndex: number = scene.edgePairs[edgeIndex * 2 + 1];
            const next = sourceIndex === current
                ? destinationIndex
                : destinationIndex === current ? sourceIndex : -1;
            if (next < 0 || previousNode[next] >= 0) continue;
            previousNode[next] = current;
            previousEdge[next] = edgeIndex;
            if (next === target) break;
            if (tail >= queue.length) break;
            queue[tail++] = next;
        }
    }

    const base = {
        ...authority,
        token,
        sourceNodeId,
        targetNodeId,
    };
    if (previousNode[target] < 0) {
        return {
            ...base,
            nodeIndices: Uint32Array.of(start, target),
            edgeIndices: new Uint32Array(0),
            found: false,
        };
    }

    const nodes: number[] = [target];
    const edges: number[] = [];
    for (let node = target; node !== start && edges.length <= GALAXY_PATH_OVERLAY_EDGE_LIMIT;) {
        const edge = previousEdge[node];
        if (edge < 0) return null;
        edges.push(edge);
        node = previousNode[node];
        nodes.push(node);
    }
    if (edges.length > GALAXY_PATH_OVERLAY_EDGE_LIMIT) return null;
    nodes.reverse();
    edges.reverse();
    return {
        ...base,
        nodeIndices: Uint32Array.from(nodes),
        edgeIndices: Uint32Array.from(edges),
        found: true,
    };
}
