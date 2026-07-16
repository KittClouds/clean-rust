import type { GalaxyLorentzGuide } from './graph-galaxy-engine';
import { rgbForKind } from './graph-galaxy-hierarchy-caps';
import type { TransitLane, TransitPlan, TransitRoute, TransitStation } from './graph-transit-plan';
import type { GraphNodeColorKind } from '../../../../../lib/store/entityColorStore';

const BACKBONE_LANES = ['document', 'root', 'chunk'] as const;
type BackboneLane = typeof BACKBONE_LANES[number];
const PLAN_LANES = ['evidence', 'identity', 'event', 'timeline', 'causal', 'state', 'context', 'discourse', 'review', 'proposed'] as const;
type PlanLane = typeof PLAN_LANES[number];
const ROUTE_LANES = ['event', 'timeline', 'causal'] as const;
type RouteLane = typeof ROUTE_LANES[number];

const BACKBONE_LANE_Y: Record<BackboneLane, number> = {
    document: 0.96,
    root: 0.68,
    chunk: 0.38,
};

const BACKBONE_LANE_Z: Record<BackboneLane, number> = {
    document: -0.64,
    root: -0.5,
    chunk: -0.34,
};

const BACKBONE_COLOR_KIND: Record<BackboneLane, GraphNodeColorKind> = {
    document: 'document',
    root: 'document',
    chunk: 'chunk',
};

const PLAN_LANE_Y: Record<PlanLane, number> = {
    evidence: 0.08,
    discourse: -0.04,
    review: -0.11,
    proposed: -0.18,
    identity: -0.32,
    event: -0.58,
    timeline: -0.84,
    causal: -1.08,
    state: 0.92,
    context: 0.66,
};

const PLAN_LANE_Z: Record<PlanLane, number> = {
    evidence: -0.2,
    discourse: -0.12,
    review: -0.06,
    proposed: 0,
    identity: 0.08,
    event: 0.22,
    timeline: 0.38,
    causal: 0.54,
    state: 0.72,
    context: 0.88,
};

const PLAN_COLOR_KIND: Record<PlanLane, GraphNodeColorKind> = {
    evidence: 'anchor',
    identity: 'relationship',
    event: 'eventNode',
    timeline: 'temporalFact',
    causal: 'causalFact',
    state: 'memoryState',
    context: 'serviceContext',
    discourse: 'communication',
    review: 'rankStatus',
    proposed: 'rankStatus',
};

const BACKBONE_ROUTE_LIMIT = 96;
const PLAN_ROUTE_LIMIT = 160;
const PLAN_STATION_GUIDE_LIMIT = 96;
const GUIDE_SEGMENTS = 12;

export function buildTransitBackboneGuides(plan: TransitPlan | undefined): GalaxyLorentzGuide[] {
    if (!plan?.stations.length) return [];
    const stationById = new Map(plan.stations.map((station) => [station.id, station]));
    const guides: GalaxyLorentzGuide[] = [];

    for (const lane of BACKBONE_LANES) {
        const stations = plan.stations.filter((station) => station.lane === lane);
        if (stations.length) guides.push(backboneLaneGuide(lane, stations, plan.receipt.stationCount));
    }

    const backboneRoutes = plan.routes
        .map((route) => ({ route, source: stationById.get(route.sourceStationId), target: stationById.get(route.targetStationId) }))
        .filter((item): item is { route: TransitRoute; source: TransitStation; target: TransitStation } =>
            Boolean(item.source && item.target && isBackboneLane(item.source.lane) && isBackboneLane(item.target.lane)))
        .sort((left, right) => left.source.stage - right.source.stage || left.target.stage - right.target.stage || left.route.edgeId.localeCompare(right.route.edgeId))
        .slice(0, BACKBONE_ROUTE_LIMIT);

    for (const item of backboneRoutes) guides.push(backboneRouteGuide(item.route, item.source, item.target));
    for (const lane of PLAN_LANES) {
        const stations = plan.stations.filter((station) => station.lane === lane);
        if (stations.length) guides.push(planLaneGuide(lane, stations, plan.receipt.stationCount));
    }
    guides.push(...stationGlyphGuides(plan.stations));
    guides.push(...routeLaneGuides(plan.routes, stationById));
    return guides;
}

export function transitStationLaneOffset(station: TransitStation): number {
    if (station.lane !== 'chunk') return transitNodeLaneOffset(station);
    const anchorKey = station.chunkIds[0]
        || station.noteIds[0]
        || station.packetTargetId
        || station.packetObjectId
        || station.sourceId
        || station.nodeId;
    const localKey = `${station.nodeId}:${station.packetObjectId || ''}:${station.sourceId || ''}`;
    const anchored = 0.18 + hashUnit(anchorKey) * 2.46;
    const localSpread = (hashUnit(localKey) - 0.5) * 0.54;
    return clamp(anchored + localSpread, 0.12, 2.68);
}

function transitNodeLaneOffset(station: TransitStation): number {
    const key = station.packetTargetId || station.packetObjectId || station.nodeId;
    return 0.14 + hashUnit(key) * 2.54;
}

export function transitVisualLanePoint(lane: TransitLane, offset: number): { x: number; y: number; z: number } | null {
    if (isBackboneLane(lane)) return {
        x: -1.42 + offset,
        y: BACKBONE_LANE_Y[lane],
        z: BACKBONE_LANE_Z[lane],
    };
    if (isPlanLane(lane)) return planLanePoint(lane, offset);
    return null;
}

function backboneLaneGuide(lane: BackboneLane, stations: TransitStation[], totalStations: number): GalaxyLorentzGuide {
    const positions3d = new Float32Array(GUIDE_SEGMENTS * 6);
    const y = BACKBONE_LANE_Y[lane];
    const z = BACKBONE_LANE_Z[lane];
    for (let index = 0; index < GUIDE_SEGMENTS; index++) {
        const a = index / GUIDE_SEGMENTS;
        const b = (index + 1) / GUIDE_SEGMENTS;
        writeBackbonePoint(positions3d, index * 6, lane, a, y, z);
        writeBackbonePoint(positions3d, index * 6 + 3, lane, b, y, z);
    }
    return {
        id: `transit:backbone:lane:${lane}`,
        nodeIds: stations.slice(0, 96).map((station) => station.nodeId),
        positions3d,
        importance: 8 + stations.length / Math.max(1, totalStations),
        treeId: 'transit:backbone',
        treeKind: `backbone:${lane}`,
        level: lane === 'document' ? 0 : lane === 'root' ? 1 : 2,
        guideKind: 'rootLane',
        guideWeight: 0.76 + Math.min(0.18, stations.length / Math.max(1, totalStations)),
        ...backboneColor(lane),
    };
}

function backboneRouteGuide(route: TransitRoute, source: TransitStation, target: TransitStation): GalaxyLorentzGuide {
    const positions3d = new Float32Array(GUIDE_SEGMENTS * 6);
    const sourcePoint = lanePoint(source.lane, 0.18 + source.stage * 0.045);
    const targetPoint = lanePoint(target.lane, 0.18 + target.stage * 0.045);
    const lift = 0.06 + Math.abs(target.stage - source.stage) * 0.018;
    const control = {
        x: (sourcePoint.x + targetPoint.x) * 0.5,
        y: (sourcePoint.y + targetPoint.y) * 0.5 + lift,
        z: Math.max(sourcePoint.z, targetPoint.z) + lift,
    };
    for (let index = 0; index < GUIDE_SEGMENTS; index++) {
        const a = index / GUIDE_SEGMENTS;
        const b = (index + 1) / GUIDE_SEGMENTS;
        writeQuadratic(positions3d, index * 6, sourcePoint, control, targetPoint, a);
        writeQuadratic(positions3d, index * 6 + 3, sourcePoint, control, targetPoint, b);
    }
    const lane = isBackboneLane(target.lane) ? target.lane : 'chunk';
    return {
        id: `transit:backbone:route:${route.edgeId}`,
        nodeIds: [source.nodeId, target.nodeId],
        positions3d,
        importance: 6 + Math.max(0, route.confidence),
        treeId: 'transit:backbone',
        treeKind: `backbone:${source.lane}>${target.lane}`,
        level: Math.max(source.stage, target.stage),
        guideKind: 'membership',
        guideWeight: 0.58 + Math.min(0.2, Math.max(0, route.confidence) * 0.18),
        ...backboneColor(lane),
    };
}

function backboneColor(lane: BackboneLane): { r: number; g: number; b: number } {
    return rgbForKind(BACKBONE_COLOR_KIND[lane]);
}

function planColor(lane: PlanLane): { r: number; g: number; b: number } {
    return rgbForKind(PLAN_COLOR_KIND[lane]);
}

function planLaneGuide(lane: PlanLane, stations: TransitStation[], totalStations: number): GalaxyLorentzGuide {
    const positions3d = new Float32Array(GUIDE_SEGMENTS * 6);
    const y = PLAN_LANE_Y[lane];
    const z = PLAN_LANE_Z[lane];
    const sideBand = lane === 'state' || lane === 'context';
    for (let index = 0; index < GUIDE_SEGMENTS; index++) {
        const a = index / GUIDE_SEGMENTS;
        const b = (index + 1) / GUIDE_SEGMENTS;
        writePlanLanePoint(positions3d, index * 6, lane, a, y, z, sideBand);
        writePlanLanePoint(positions3d, index * 6 + 3, lane, b, y, z, sideBand);
    }
    return {
        id: `transit:plan:lane:${lane}`,
        nodeIds: stations.slice(0, 96).map((station) => station.nodeId),
        positions3d,
        importance: 7 + stations.length / Math.max(1, totalStations),
        treeId: sideBand ? 'transit:plan-side-bands' : 'transit:plan-lanes',
        treeKind: sideBand ? `side-band:${lane}` : `lane:${lane}`,
        level: stations[0]?.stage ?? 0,
        guideKind: 'rootLane',
        guideWeight: 0.42 + Math.min(0.2, stations.length / Math.max(1, totalStations) * 0.5),
        ...planColor(lane),
    };
}

function stationGlyphGuides(stations: TransitStation[]): GalaxyLorentzGuide[] {
    const guides: GalaxyLorentzGuide[] = [];
    for (const station of stations) {
        if (guides.length >= PLAN_STATION_GUIDE_LIMIT) break;
        if (station.lane === 'evidence') guides.push(stationGlyphGuide(station, 'stop', 0.052));
        else if (station.lane === 'identity') guides.push(stationGlyphGuide(station, 'hub', 0.074));
    }
    return guides;
}

function stationGlyphGuide(station: TransitStation, kind: 'stop' | 'hub', radius: number): GalaxyLorentzGuide {
    const lane = isPlanLane(station.lane) ? station.lane : 'evidence';
    const center = planLanePoint(lane, transitStationLaneOffset(station));
    const positions3d = kind === 'hub' ? diamondGlyph(center, radius) : stopGlyph(center, radius);
    return {
        id: `transit:plan:${kind}:${station.nodeId}`,
        nodeIds: [station.nodeId],
        positions3d,
        importance: kind === 'hub' ? 7.5 : 7,
        treeId: kind === 'hub' ? 'transit:identity-hubs' : 'transit:evidence-stops',
        treeKind: kind === 'hub' ? 'identity:hub' : 'evidence:stop',
        level: station.stage,
        guideKind: 'rootLane',
        guideWeight: kind === 'hub' ? 0.62 : 0.54,
        ...planColor(lane),
    };
}

function routeLaneGuides(routes: TransitRoute[], stationById: Map<string, TransitStation>): GalaxyLorentzGuide[] {
    const guides: GalaxyLorentzGuide[] = [];
    const candidates = routes
        .map((route) => ({ route, source: stationById.get(route.sourceStationId), target: stationById.get(route.targetStationId) }))
        .filter((item): item is { route: TransitRoute; source: TransitStation; target: TransitStation } =>
            Boolean(item.source && item.target && (isRouteLane(item.route.lane) || isRouteLane(item.source.lane) || isRouteLane(item.target.lane))))
        .sort((left, right) => left.route.lane.localeCompare(right.route.lane) || left.route.edgeId.localeCompare(right.route.edgeId))
        .slice(0, PLAN_ROUTE_LIMIT);
    for (const item of candidates) guides.push(routeGuide(item.route, item.source, item.target));
    return guides;
}

function routeGuide(route: TransitRoute, source: TransitStation, target: TransitStation): GalaxyLorentzGuide {
    const lane = isRouteLane(route.lane) ? route.lane : isRouteLane(target.lane) ? target.lane : isRouteLane(source.lane) ? source.lane : 'event';
    const positions3d = new Float32Array(GUIDE_SEGMENTS * 6);
    const sourcePoint = planLanePoint(isPlanLane(source.lane) ? source.lane : lane, transitStationLaneOffset(source));
    const targetPoint = planLanePoint(isPlanLane(target.lane) ? target.lane : lane, transitStationLaneOffset(target));
    const lift = lane === 'causal' ? 0.22 : lane === 'timeline' ? 0.14 : 0.1;
    const control = {
        x: (sourcePoint.x + targetPoint.x) * 0.5 + (route.directed ? 0.1 : 0),
        y: PLAN_LANE_Y[lane] + lift,
        z: Math.max(sourcePoint.z, targetPoint.z) + lift * 0.7,
    };
    for (let index = 0; index < GUIDE_SEGMENTS; index++) {
        const a = index / GUIDE_SEGMENTS;
        const b = (index + 1) / GUIDE_SEGMENTS;
        writeQuadratic(positions3d, index * 6, sourcePoint, control, targetPoint, a);
        writeQuadratic(positions3d, index * 6 + 3, sourcePoint, control, targetPoint, b);
    }
    return {
        id: `transit:plan:route:${route.edgeId}`,
        nodeIds: [source.nodeId, target.nodeId],
        positions3d,
        importance: 6.5 + Math.max(0, route.confidence),
        treeId: 'transit:plan-routes',
        treeKind: `route:${lane}`,
        level: Math.max(source.stage, target.stage),
        guideKind: 'membership',
        guideWeight: 0.5 + Math.min(0.24, Math.max(0, route.confidence) * 0.24),
        ...planColor(lane),
    };
}

function writeBackbonePoint(output: Float32Array, offset: number, lane: BackboneLane, t: number, y: number, z: number): void {
    const x = -1.58 + t * 3.16;
    const bow = Math.sin(t * Math.PI) * (lane === 'document' ? 0.04 : lane === 'root' ? 0.025 : 0.015);
    output[offset] = x;
    output[offset + 1] = y + bow;
    output[offset + 2] = z + bow * 0.65;
}

function writePlanLanePoint(output: Float32Array, offset: number, lane: PlanLane, t: number, y: number, z: number, sideBand: boolean): void {
    const x = sideBand ? 1.24 + Math.sin(t * Math.PI) * 0.12 : -1.44 + t * 2.88;
    const yBand = sideBand ? y - t * 0.78 : y + Math.sin(t * Math.PI) * 0.018;
    output[offset] = x;
    output[offset + 1] = yBand;
    output[offset + 2] = z + Math.sin(t * Math.PI * 2 + lane.length) * 0.018;
}

function planLanePoint(lane: PlanLane, offset: number): { x: number; y: number; z: number } {
    return {
        x: -1.28 + offset,
        y: PLAN_LANE_Y[lane],
        z: PLAN_LANE_Z[lane],
    };
}

function lanePoint(lane: TransitLane, xOffset: number): { x: number; y: number; z: number } {
    return transitVisualLanePoint(lane, xOffset) ?? transitVisualLanePoint('chunk', xOffset)!;
}

function stopGlyph(center: { x: number; y: number; z: number }, radius: number): Float32Array {
    return new Float32Array([
        center.x, center.y - radius, center.z,
        center.x, center.y + radius, center.z,
        center.x - radius * 0.7, center.y, center.z,
        center.x + radius * 0.7, center.y, center.z,
    ]);
}

function diamondGlyph(center: { x: number; y: number; z: number }, radius: number): Float32Array {
    return new Float32Array([
        center.x, center.y + radius, center.z,
        center.x + radius, center.y, center.z + radius * 0.35,
        center.x + radius, center.y, center.z + radius * 0.35,
        center.x, center.y - radius, center.z,
        center.x, center.y - radius, center.z,
        center.x - radius, center.y, center.z + radius * 0.35,
        center.x - radius, center.y, center.z + radius * 0.35,
        center.x, center.y + radius, center.z,
    ]);
}

function writeQuadratic(
    output: Float32Array,
    offset: number,
    source: { x: number; y: number; z: number },
    control: { x: number; y: number; z: number },
    target: { x: number; y: number; z: number },
    t: number,
): void {
    const inv = 1 - t;
    output[offset] = inv * inv * source.x + 2 * inv * t * control.x + t * t * target.x;
    output[offset + 1] = inv * inv * source.y + 2 * inv * t * control.y + t * t * target.y;
    output[offset + 2] = inv * inv * source.z + 2 * inv * t * control.z + t * t * target.z;
}

function hashUnit(value: string): number {
    let hash = 0;
    for (let index = 0; index < value.length; index++) hash = (hash * 31 + value.charCodeAt(index)) | 0;
    return (Math.abs(hash) % 1000) / 1000;
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}

function isBackboneLane(lane: TransitLane): lane is BackboneLane {
    return lane === 'document' || lane === 'root' || lane === 'chunk';
}

function isPlanLane(lane: TransitLane): lane is PlanLane {
    return PLAN_LANES.includes(lane as PlanLane);
}

function isRouteLane(lane: TransitLane): lane is RouteLane {
    return ROUTE_LANES.includes(lane as RouteLane);
}
