import { galaxyIncidentEdges, type GalaxySceneV2 } from './graph-galaxy-scene-v2';
import type { GalaxyPathOverlay } from './graph-galaxy-interaction.model';

export interface GalaxyFocusMask {
    hasFocus: boolean;
    focusIndex: number;
    selectedIndex: number;
    hoverIndex: number;
    selectedIndices: Uint32Array;
    pathNodeIndices: Uint32Array;
    pathEdgeIndices: Uint32Array;
    pathFound: boolean;
    nodeLevels: Uint8Array;
    edgeLevels: Uint8Array;
}

export function buildGalaxyFocusMask(
    data: GalaxySceneV2,
    selected: string | readonly string[] | null,
    hoverId: string | null,
    pathOverlay: GalaxyPathOverlay | null = null,
): GalaxyFocusMask {
    const selectedIds = typeof selected === 'string' ? [selected] : selected?.slice(0, 2) ?? [];
    const selectedValues = selectedIds
        .map((id) => galaxyNodeIndex(data, id))
        .filter((index, position, values) => index >= 0 && values.indexOf(index) === position);
    const selectedIndices = Uint32Array.from(selectedValues);
    const selectedIndex = selectedValues[0] ?? -1;
    const hoverIndex = hoverId ? galaxyNodeIndex(data, hoverId) : -1;
    const focusIndex = hoverIndex >= 0 ? hoverIndex : selectedIndex;
    const nodeLevels = new Uint8Array(data.ids.length);
    const edgeLevels = new Uint8Array(data.edgePairs.length / 2);
    if (selectedValues.length === 2) {
        return selectedPairFocus(
            selectedIds,
            selectedValues,
            hoverIndex,
            nodeLevels,
            edgeLevels,
            pathOverlay,
        );
    }
    const noPath = {
        selectedIndices,
        pathNodeIndices: new Uint32Array(0),
        pathEdgeIndices: new Uint32Array(0),
        pathFound: false,
    };
    if (focusIndex < 0) {
        nodeLevels.fill(1);
        edgeLevels.fill(1);
        return { ...noPath, hasFocus: false, focusIndex, selectedIndex, hoverIndex, nodeLevels, edgeLevels };
    }

    if (data.layoutMode === 'siegelFinsler' && focusDirectedHierarchy(data, focusIndex, nodeLevels, edgeLevels)) {
        return { ...noPath, hasFocus: true, focusIndex, selectedIndex, hoverIndex, nodeLevels, edgeLevels };
    }

    if (data.layoutMode === 'lorentzTree' && focusStructuralHierarchy(data, focusIndex, nodeLevels, edgeLevels)) {
        includeIncidentConnections(data, focusIndex, nodeLevels, edgeLevels);
        return { ...noPath, hasFocus: true, focusIndex, selectedIndex, hoverIndex, nodeLevels, edgeLevels };
    }

    nodeLevels[focusIndex] = 3;
    for (const edge of incidentEdgesFor(data, focusIndex)) {
        const source = data.edgePairs[edge * 2];
        const target = data.edgePairs[edge * 2 + 1];
        edgeLevels[edge] = 2;
        nodeLevels[source] = Math.max(nodeLevels[source], source === focusIndex ? 3 : 2);
        nodeLevels[target] = Math.max(nodeLevels[target], target === focusIndex ? 3 : 2);
    }
    return { ...noPath, hasFocus: true, focusIndex, selectedIndex, hoverIndex, nodeLevels, edgeLevels };
}

function selectedPairFocus(
    selectedIds: string[],
    selectedValues: number[],
    hoverIndex: number,
    nodeLevels: Uint8Array,
    edgeLevels: Uint8Array,
    pathOverlay: GalaxyPathOverlay | null,
): GalaxyFocusMask {
    const [start, target] = selectedValues;
    const selectedIndices = Uint32Array.of(start, target);
    const acceptedOverlay = pathOverlay
        && pathOverlay.sourceNodeId === selectedIds[0]
        && pathOverlay.targetNodeId === selectedIds[1]
        ? pathOverlay
        : null;
    if (!acceptedOverlay?.found) {
        nodeLevels[start] = 3;
        nodeLevels[target] = 3;
        return {
            hasFocus: true,
            focusIndex: target,
            selectedIndex: start,
            hoverIndex,
            selectedIndices,
            pathNodeIndices: selectedIndices,
            pathEdgeIndices: new Uint32Array(0),
            pathFound: false,
            nodeLevels,
            edgeLevels,
        };
    }
    for (const node of acceptedOverlay.nodeIndices) {
        if (node < nodeLevels.length) nodeLevels[node] = node === start || node === target ? 3 : 2;
    }
    for (const edge of acceptedOverlay.edgeIndices) {
        if (edge < edgeLevels.length) edgeLevels[edge] = 3;
    }
    return {
        hasFocus: true,
        focusIndex: target,
        selectedIndex: start,
        hoverIndex,
        selectedIndices,
        pathNodeIndices: acceptedOverlay.nodeIndices,
        pathEdgeIndices: acceptedOverlay.edgeIndices,
        pathFound: true,
        nodeLevels,
        edgeLevels,
    };
}

function focusDirectedHierarchy(
    data: GalaxySceneV2,
    focusIndex: number,
    nodeLevels: Uint8Array,
    edgeLevels: Uint8Array,
): boolean {
    nodeLevels[focusIndex] = 3;
    let found = false;
    found = walkSiegelDirection(data, focusIndex, nodeLevels, edgeLevels, 'ancestor') || found;
    found = walkSiegelDirection(data, focusIndex, nodeLevels, edgeLevels, 'descendant') || found;
    return found;
}

function walkSiegelDirection(
    data: GalaxySceneV2,
    focusIndex: number,
    nodeLevels: Uint8Array,
    edgeLevels: Uint8Array,
    direction: 'ancestor' | 'descendant',
): boolean {
    const seen = new Uint8Array(data.ids.length);
    const queue = new Uint32Array(data.ids.length);
    const depths = new Uint8Array(data.ids.length);
    let head = 0;
    let tail = 0;
    let found = false;
    queue[tail++] = focusIndex;
    seen[focusIndex] = 1;
    while (head < tail) {
        const current = queue[head++];
        const depth = depths[current];
        if (depth >= 6) continue;
        for (const edge of incidentEdgesFor(data, current)) {
            if (data.edgeKinds[edge] !== 2) continue;
            const source = data.edgePairs[edge * 2];
            const target = data.edgePairs[edge * 2 + 1];
            if (source !== current && target !== current) continue;
            const parent = siegelFlowParent(data, source, target);
            const child = parent === source ? target : source;
            const nextNode = direction === 'ancestor' ? parent : child;
            if ((direction === 'ancestor' && child !== current) || (direction === 'descendant' && parent !== current)) continue;
            found = true;
            edgeLevels[edge] = 2;
            nodeLevels[nextNode] = Math.max(nodeLevels[nextNode], depth <= 1 ? 2 : 1);
            if (!seen[nextNode]) {
                seen[nextNode] = 1;
                depths[nextNode] = depth + 1;
                queue[tail++] = nextNode;
            }
        }
    }
    return found;
}

function siegelFlowParent(data: GalaxySceneV2, source: number, target: number): number {
    const sx = data.positions3d[source * 3];
    const tx = data.positions3d[target * 3];
    if (Math.abs(sx - tx) > 0.0001) return sx <= tx ? source : target;
    return structuralParent(data, source, target);
}

function focusStructuralHierarchy(
    data: GalaxySceneV2,
    focusIndex: number,
    nodeLevels: Uint8Array,
    edgeLevels: Uint8Array,
): boolean {
    nodeLevels[focusIndex] = 3;
    let found = false;
    found = walkStructuralDirection(data, focusIndex, nodeLevels, edgeLevels, 'ancestor') || found;
    found = walkStructuralDirection(data, focusIndex, nodeLevels, edgeLevels, 'descendant') || found;
    return found;
}

function walkStructuralDirection(
    data: GalaxySceneV2,
    focusIndex: number,
    nodeLevels: Uint8Array,
    edgeLevels: Uint8Array,
    direction: 'ancestor' | 'descendant',
): boolean {
    const seen = new Uint8Array(data.ids.length);
    const queue = new Uint32Array(data.ids.length);
    const depths = new Uint8Array(data.ids.length);
    let head = 0;
    let tail = 0;
    let found = false;
    queue[tail++] = focusIndex;
    seen[focusIndex] = 1;
    while (head < tail) {
        const current = queue[head++];
        const depth = depths[current];
        if (depth >= 5) continue;
        for (const edge of incidentEdgesFor(data, current)) {
            if (data.edgeKinds[edge] !== 2) continue;
            const source = data.edgePairs[edge * 2];
            const target = data.edgePairs[edge * 2 + 1];
            const next = source === current ? target : target === current ? source : -1;
            if (next < 0) continue;
            const parent = structuralParent(data, source, target);
            const child = parent === current ? next : current;
            const follow = direction === 'ancestor' ? child === current : parent === current;
            const nextNode = direction === 'ancestor' ? parent : child;
            if (!follow) continue;
            found = true;
            edgeLevels[edge] = 2;
            nodeLevels[nextNode] = Math.max(nodeLevels[nextNode], depth <= 1 ? 2 : 1);
            if (!seen[nextNode]) {
                seen[nextNode] = 1;
                depths[nextNode] = depth + 1;
                queue[tail++] = nextNode;
            }
        }
    }
    return found;
}

function includeIncidentConnections(
    data: GalaxySceneV2,
    focusIndex: number,
    nodeLevels: Uint8Array,
    edgeLevels: Uint8Array,
): void {
    for (const edge of incidentEdgesFor(data, focusIndex)) {
        const source = data.edgePairs[edge * 2];
        const target = data.edgePairs[edge * 2 + 1];
        const next = source === focusIndex ? target : target === focusIndex ? source : -1;
        if (next < 0) continue;
        edgeLevels[edge] = 2;
        nodeLevels[next] = Math.max(nodeLevels[next], 2);
    }
}

function galaxyNodeIndex(data: GalaxySceneV2, id: string): number {
    return data.runtimeIndex?.nodeById.get(id) ?? data.ids.indexOf(id);
}

function incidentEdgesFor(data: GalaxySceneV2, node: number): Iterable<number> {
    if (data.runtimeIndex) return galaxyIncidentEdges(data, node);
    const edges: number[] = [];
    for (let edge = 0; edge < data.edgePairs.length / 2; edge++) {
        if (data.edgePairs[edge * 2] === node || data.edgePairs[edge * 2 + 1] === node) edges.push(edge);
    }
    return edges;
}

function structuralParent(data: GalaxySceneV2, source: number, target: number): number {
    const sourceRadius = nodeRadius(data, source);
    const targetRadius = nodeRadius(data, target);
    if (Math.abs(sourceRadius - targetRadius) <= 0.0001) return source;
    return sourceRadius >= targetRadius ? source : target;
}

function nodeRadius(data: GalaxySceneV2, index: number): number {
    const offset = index * 3;
    return Math.hypot(data.positions3d[offset], data.positions3d[offset + 1], data.positions3d[offset + 2]);
}
