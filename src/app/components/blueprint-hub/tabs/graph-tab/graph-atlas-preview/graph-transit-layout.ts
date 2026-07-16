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
    const placements = new Map<string, TransitStationPlacement>();
    for (const station of stations) {
        const base = transitVisualLanePoint(station.lane, transitStationLaneOffset(station));
        if (!base) continue;
        placements.set(station.id, base);
    }
    return placements;
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
