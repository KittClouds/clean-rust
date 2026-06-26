import type { GalaxyEdge, GalaxyNode } from './graph-galaxy-engine';
import {
    transitStationLaneOffset,
    transitVisualLanePoint,
} from './graph-transit-backbone-guides';
import type { TransitLane, TransitPlan, TransitRoute, TransitStation } from './graph-transit-plan';

const TRANSIT_SCENE_RADIUS = 2.12;

interface TransitStationPlacement {
    x: number;
    y: number;
    z: number;
}

export function applyTransitLayout(nodes: GalaxyNode[], links: GalaxyEdge[], plan: TransitPlan | undefined): void {
    const stations = plan?.stations ?? [];
    const stationByNodeId = new Map(stations.map((station) => [station.nodeId, station]));
    const routeByEdgeId = new Map((plan?.routes ?? []).map((route) => [route.edgeId, route]));
    const placementByStationId = transitStationPlacements(stations);

    for (let index = 0; index < nodes.length; index++) {
        const node = nodes[index];
        const station = stationByNodeId.get(node.entity.id);
        if (station?.packetBacked) placeStationNode(node, station, placementByStationId.get(station.id));
        else placeDiagnosticNode(node, index);
    }

    for (const link of links) tuneTransitLink(link, routeByEdgeId.get(link.id));
}

function placeStationNode(
    node: GalaxyNode,
    station: TransitStation,
    placement: TransitStationPlacement | undefined,
): void {
    if (!placement) {
        placeDiagnosticNode(node, 0);
        return;
    }
    const depth = laneDepth(station.lane, station);
    node.x = placement.x;
    node.y = placement.y;
    node.z = placement.z + depth;
    node.baseX = node.x;
    node.baseY = node.y;
    node.baseZ = node.z;
    node.radius *= laneScale(station.lane);
    node.depth = clamp(Math.hypot(node.x, node.y, node.z) / TRANSIT_SCENE_RADIUS, 0, 1);
}

function transitStationPlacements(stations: TransitStation[]): Map<string, TransitStationPlacement> {
    const buckets = new Map<string, Array<{ station: TransitStation; base: TransitStationPlacement }>>();
    for (const station of stations) {
        const base = transitVisualLanePoint(station.lane, transitStationLaneOffset(station));
        if (!base) continue;
        if (station.lane !== 'chunk') {
            buckets.set(station.id, [{ station, base }]);
            continue;
        }
        const key = stationPlacementBucketKey(station);
        buckets.set(key, [...(buckets.get(key) || []), { station, base }]);
    }

    const placements = new Map<string, TransitStationPlacement>();
    for (const bucket of buckets.values()) {
        bucket.sort((left, right) => left.station.nodeId.localeCompare(right.station.nodeId));
        const count = bucket.length;
        const center = count > 1 ? bucketCenter(bucket.map((item) => item.base)) : undefined;
        for (let index = 0; index < count; index++) {
            const { station, base } = bucket[index];
            const fanout = transitFanout(station.lane, station.nodeId, index, count);
            const origin = center || base;
            placements.set(station.id, {
                x: origin.x + fanout.x,
                y: origin.y + fanout.y,
                z: origin.z + fanout.z,
            });
        }
    }
    return placements;
}

function bucketCenter(points: TransitStationPlacement[]): TransitStationPlacement {
    const total = points.reduce((sum, point) => ({
        x: sum.x + point.x,
        y: sum.y + point.y,
        z: sum.z + point.z,
    }), { x: 0, y: 0, z: 0 });
    return {
        x: total.x / points.length,
        y: total.y / points.length,
        z: total.z / points.length,
    };
}

function stationPlacementBucketKey(station: TransitStation): string {
    return [
        station.lane,
        station.chunkIds[0] || station.noteIds[0] || station.packetTargetId || station.packetObjectId || station.sourceId || station.nodeId,
    ].join(':');
}

function transitFanout(
    lane: TransitLane,
    nodeId: string,
    index: number,
    count: number,
): TransitStationPlacement {
    if (lane !== 'chunk') return { x: 0, y: 0, z: 0 };
    if (count <= 1) {
        const phase = hashUnit(`${nodeId}:micro`) - 0.5;
        return { x: phase * 0.018, y: phase * 0.008, z: -phase * 0.012 };
    }
    const columns = Math.min(6, Math.ceil(Math.sqrt(count * 1.45)));
    const rows = Math.ceil(count / columns);
    const col = index % columns;
    const row = Math.floor(index / columns);
    const xStep = laneFanoutX(lane);
    const rowStagger = rows > 1 && row % 2 === 1 ? xStep * 0.5 : 0;
    const x = (col - (columns - 1) / 2) * xStep + rowStagger;
    const y = (row - (rows - 1) / 2) * laneFanoutY(lane);
    const z = (((index % 3) - 1) * laneFanoutZ(lane)) + (hashUnit(`${nodeId}:z`) - 0.5) * 0.012;
    return { x, y, z };
}

function laneFanoutX(lane: TransitLane): number {
    switch (lane) {
        case 'document':
        case 'root': return 0.094;
        case 'chunk': return 0.132;
        case 'evidence':
        case 'identity': return 0.132;
        case 'review':
        case 'proposed':
        case 'discourse': return 0.104;
        default: return 0.088;
    }
}

function laneFanoutY(lane: TransitLane): number {
    switch (lane) {
        case 'document':
        case 'root': return 0.034;
        case 'chunk': return 0.082;
        case 'evidence':
        case 'identity': return 0.082;
        case 'state':
        case 'context': return 0.064;
        default: return 0.046;
    }
}

function laneFanoutZ(lane: TransitLane): number {
    return lane === 'identity' || lane === 'evidence' ? 0.024 : 0.018;
}

function placeDiagnosticNode(node: GalaxyNode, index: number): void {
    const col = index % 7;
    const row = Math.floor(index / 7) % 5;
    node.x = -1.48 + col * 0.34;
    node.y = -1.86 - row * 0.12;
    node.z = -0.92 + (hashUnit(node.entity.id) - 0.5) * 0.18;
    node.baseX = node.x;
    node.baseY = node.y;
    node.baseZ = node.z;
    node.radius *= 0.66;
    node.depth = clamp(Math.hypot(node.x, node.y, node.z) / TRANSIT_SCENE_RADIUS, 0, 1);
}

function tuneTransitLink(link: GalaxyEdge, route: TransitRoute | undefined): void {
    if (!route) {
        link.alpha = Math.min(link.alpha, 0.08);
        link.curve = Math.min(link.curve, 0.18);
        return;
    }
    const confidence = clamp(route.confidence || link.confidence || 0, 0, 1);
    const directedBoost = route.directed ? 0.08 : 0;
    link.alpha = clamp(0.08 + confidence * 0.34 + directedBoost, 0.08, 0.56);
    link.curve = route.lane === 'causal' ? 0.5 : route.lane === 'timeline' ? 0.38 : route.directed ? 0.3 : 0.18;
}

function laneDepth(lane: TransitLane, station: TransitStation): number {
    const statusDepth = station.trace?.packetTargetId || station.packetTargetId ? 0.02 : -0.02;
    switch (lane) {
        case 'document': return -0.035;
        case 'root': return -0.02;
        case 'chunk': return 0;
        case 'evidence': return 0.028;
        case 'identity': return 0.07;
        case 'event': return 0.11;
        case 'timeline': return 0.14;
        case 'causal': return 0.18;
        case 'state':
        case 'context': return 0.09 + statusDepth;
        case 'discourse':
        case 'review':
        case 'proposed': return 0.13 + statusDepth;
        default: return statusDepth;
    }
}

function laneScale(lane: TransitLane): number {
    switch (lane) {
        case 'document': return 1.08;
        case 'root': return 0.9;
        case 'chunk': return 0.76;
        case 'evidence': return 0.7;
        case 'identity': return 1.04;
        case 'event':
        case 'timeline':
        case 'causal': return 0.82;
        case 'state':
        case 'context': return 0.72;
        case 'discourse':
        case 'review':
        case 'proposed': return 0.68;
        default: return 0.64;
    }
}

function hashUnit(value: string): number {
    let hash = 0;
    for (let index = 0; index < value.length; index++) hash = (hash * 31 + value.charCodeAt(index)) | 0;
    return (Math.abs(hash) % 1000) / 1000;
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}
