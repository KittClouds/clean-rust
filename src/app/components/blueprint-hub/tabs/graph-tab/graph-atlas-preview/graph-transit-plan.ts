import type { GraphRebuildVisualTrace } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';

export type TransitLane =
    | 'document'
    | 'root'
    | 'chunk'
    | 'evidence'
    | 'identity'
    | 'relationship'
    | 'event'
    | 'timeline'
    | 'causal'
    | 'state'
    | 'context'
    | 'review'
    | 'proposed'
    | 'discourse'
    | 'transfer'
    | 'unknown';

export interface TransitStation {
    id: string;
    nodeId: string;
    label: string;
    lane: TransitLane;
    stage: number;
    family: string;
    kind: string;
    sourceId: string;
    packetBacked: boolean;
    packetSnapshotId?: string;
    packetScopeId?: string;
    sourceContract?: string;
    vectorContract?: string;
    packetObjectId?: string;
    packetTargetId?: string;
    noteIds: string[];
    chunkIds: string[];
    evidenceIds: string[];
    regionIds: string[];
    trace?: GraphRebuildVisualTrace;
}

export interface TransitRoute {
    id: string;
    edgeId: string;
    sourceStationId: string;
    targetStationId: string;
    type: string;
    family: string;
    lane: TransitLane;
    sourceLane: TransitLane;
    targetLane: TransitLane;
    confidence: number;
    directed: boolean;
    packetBacked: boolean;
    sourceTrace?: GraphRebuildVisualTrace;
    targetTrace?: GraphRebuildVisualTrace;
    trace?: GraphRebuildVisualTrace;
    regionIds: string[];
}

export interface TransitRegion {
    id: string;
    kind: 'document' | 'chunk' | 'family';
    label: string;
    lane: TransitLane;
    family?: string;
    noteId?: string;
    chunkId?: string;
    stationIds: string[];
}

export interface TransitPlanReceipt {
    schemaVersion: 'graph-transit-plan/v1';
    stationCount: number;
    routeCount: number;
    regionCount: number;
    packetBackedStations: number;
    packetBackedRoutes: number;
    droppedUntracedNodes: number;
    missingEndpointRoutes: number;
    edgeTraceFallbackRoutes: number;
    familyCounts: Record<string, number>;
    laneCounts: Record<string, number>;
    routeLaneCounts: Record<string, number>;
}

export interface TransitPlan {
    schemaVersion: 'graph-transit-plan/v1';
    stations: TransitStation[];
    routes: TransitRoute[];
    regions: TransitRegion[];
    receipt: TransitPlanReceipt;
}

export interface TransitPlanOptions {
    includeUntracedNodes?: boolean;
}

const TRANSIT_SCHEMA_VERSION = 'graph-transit-plan/v1' as const;

const LANE_STAGE: Record<TransitLane, number> = {
    document: 0,
    root: 1,
    chunk: 2,
    evidence: 3,
    identity: 4,
    relationship: 5,
    event: 6,
    timeline: 7,
    causal: 8,
    state: 9,
    context: 10,
    review: 11,
    proposed: 12,
    discourse: 13,
    transfer: 14,
    unknown: 99,
};

export function buildTransitPlan(
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    options: TransitPlanOptions = {},
): TransitPlan {
    const includeUntraced = options.includeUntracedNodes === true;
    const droppedUntracedNodes = nodes.filter((node) => !packetTraceFromNode(node)).length;
    const stations = nodes
        .filter((node) => includeUntraced || Boolean(packetTraceFromNode(node)))
        .map(transitStation);
    const stationById = new Map(stations.map((station) => [station.nodeId, station]));
    const routes: TransitRoute[] = [];
    let missingEndpointRoutes = 0;
    let edgeTraceFallbackRoutes = 0;

    for (const edge of edges) {
        const source = stationById.get(edge.sourceId);
        const target = stationById.get(edge.targetId);
        if (!source || !target) {
            missingEndpointRoutes += 1;
            continue;
        }
        const route = transitRoute(edge, source, target);
        if (!packetTraceFromRecord(edge.metadata)) edgeTraceFallbackRoutes += 1;
        routes.push(route);
    }

    const regions = transitRegions(stations);
    const receipt = transitReceipt(stations, routes, regions, droppedUntracedNodes, missingEndpointRoutes, edgeTraceFallbackRoutes);
    return { schemaVersion: TRANSIT_SCHEMA_VERSION, stations, routes, regions, receipt };
}

function transitStation(node: GalaxyRenderableNode): TransitStation {
    const metadata = node.metadata || {};
    const trace = packetTraceFromNode(node);
    const family = cleanToken(
        trace?.family,
        stringValue(metadata['visualFamily']),
        stringValue(metadata['graphFamily']),
        stringValue(metadata['atlasFamily']),
        node.kind,
    );
    const kind = cleanToken(
        stringValue(metadata['atlasKind']),
        stringValue(metadata['graphKind']),
        stringValue(metadata['sourceType']),
        node.kind,
    );
    const lane = transitLane(family, kind, metadata);
    const noteIds = uniqueStrings(trace?.noteIds, arrayStrings(metadata['noteIds']), [stringValue(metadata['noteId'])]);
    const chunkIds = uniqueStrings(trace?.chunkIds, arrayStrings(metadata['chunkIds']), [stringValue(metadata['chunkId'])]);
    const evidenceIds = uniqueStrings(trace?.evidenceIds, arrayStrings(metadata['evidenceIds']));
    const sourceId = cleanToken(trace?.sourceId, stringValue(metadata['visualSourceId']), stringValue(metadata['sourceId']), node.id);
    const station: TransitStation = {
        id: `transit:station:${node.id}`,
        nodeId: node.id,
        label: node.label || node.id,
        lane,
        stage: LANE_STAGE[lane],
        family,
        kind,
        sourceId,
        packetBacked: trace?.source === 'rust_atlas_packet',
        packetSnapshotId: trace?.packetSnapshotId || stringValue(metadata['packetSnapshotId']),
        packetScopeId: trace?.packetScopeId || stringValue(metadata['packetScopeId']),
        sourceContract: trace?.sourceContract || stringValue(metadata['sourceContract']),
        vectorContract: trace?.vectorContract || stringValue(metadata['vectorContract']),
        packetObjectId: trace?.packetObjectId || stringValue(metadata['atlasObjectId']),
        packetTargetId: trace?.packetTargetId || stringValue(metadata['atlasTargetId']),
        noteIds,
        chunkIds,
        evidenceIds,
        regionIds: [],
        trace,
    };
    station.regionIds = stationRegionIds(station);
    return station;
}

function transitRoute(edge: GalaxyInputEdge, source: TransitStation, target: TransitStation): TransitRoute {
    const metadata = edge.metadata || {};
    const edgeTrace = packetTraceFromRecord(metadata);
    const sourceTrace = packetTraceFromRecord(recordValue(metadata['sourceVisualTrace'])) || source.trace;
    const targetTrace = packetTraceFromRecord(recordValue(metadata['targetVisualTrace'])) || target.trace;
    const lane = routeLane(edge, source, target);
    const family = cleanToken(edgeTrace?.family, stringValue(metadata['graphFamily']), target.family, source.family);
    return {
        id: `transit:route:${edge.id}`,
        edgeId: edge.id,
        sourceStationId: source.id,
        targetStationId: target.id,
        type: edge.type,
        family,
        lane,
        sourceLane: source.lane,
        targetLane: target.lane,
        confidence: edge.confidence,
        directed: directedRoute(edge.type),
        packetBacked: source.packetBacked && target.packetBacked,
        sourceTrace,
        targetTrace,
        trace: edgeTrace || sourceTrace || targetTrace,
        regionIds: uniqueStrings(source.regionIds, target.regionIds),
    };
}

function transitRegions(stations: TransitStation[]): TransitRegion[] {
    const regions = new Map<string, TransitRegion>();
    const add = (region: TransitRegion, stationId: string) => {
        const current = regions.get(region.id) || region;
        current.stationIds = uniqueStrings(current.stationIds, [stationId]);
        regions.set(current.id, current);
    };
    for (const station of stations) {
        add({
            id: `transit:family:${station.family}`,
            kind: 'family',
            label: station.family,
            lane: station.lane,
            family: station.family,
            stationIds: [],
        }, station.id);
        for (const noteId of station.noteIds) {
            add({
                id: `transit:document:${noteId}`,
                kind: 'document',
                label: noteId,
                lane: 'document',
                noteId,
                stationIds: [],
            }, station.id);
        }
        for (const chunkId of station.chunkIds) {
            add({
                id: `transit:chunk:${chunkId}`,
                kind: 'chunk',
                label: chunkId,
                lane: 'chunk',
                chunkId,
                stationIds: [],
            }, station.id);
        }
    }
    return [...regions.values()].sort((left, right) => left.id.localeCompare(right.id));
}

function transitReceipt(
    stations: TransitStation[],
    routes: TransitRoute[],
    regions: TransitRegion[],
    droppedUntracedNodes: number,
    missingEndpointRoutes: number,
    edgeTraceFallbackRoutes: number,
): TransitPlanReceipt {
    return {
        schemaVersion: TRANSIT_SCHEMA_VERSION,
        stationCount: stations.length,
        routeCount: routes.length,
        regionCount: regions.length,
        packetBackedStations: stations.filter((station) => station.packetBacked).length,
        packetBackedRoutes: routes.filter((route) => route.packetBacked).length,
        droppedUntracedNodes,
        missingEndpointRoutes,
        edgeTraceFallbackRoutes,
        familyCounts: countBy(stations, (station) => station.family),
        laneCounts: countBy(stations, (station) => station.lane),
        routeLaneCounts: countBy(routes, (route) => route.lane),
    };
}

function stationRegionIds(station: TransitStation): string[] {
    return uniqueStrings(
        [`transit:family:${station.family}`],
        station.noteIds.map((noteId) => `transit:document:${noteId}`),
        station.chunkIds.map((chunkId) => `transit:chunk:${chunkId}`),
    );
}

function transitLane(family: string, kind: string, metadata: Record<string, unknown>): TransitLane {
    const text = `${family} ${kind} ${stringValue(metadata['atlasStructuralRole'])} ${stringValue(metadata['atlasDocumentUnitKind'])} ${stringValue(metadata['atlasStateContextKind'])}`.toLowerCase();
    if (/proposed/.test(text)) return 'proposed';
    if (/review|candidate/.test(text)) return 'review';
    if (/discourse/.test(text)) return 'discourse';
    if (/causal/.test(text)) return 'causal';
    if (/temporal|timeline|before|after/.test(text)) return 'timeline';
    if (/memory|state|rank|decision|status|affiliation|context/.test(text)) return family === 'memory' ? 'state' : 'context';
    if (/event/.test(text)) return 'event';
    if (/anchor|evidence|source-span/.test(text)) return 'evidence';
    if (/chunk/.test(text)) return 'chunk';
    if (/root|section|heading/.test(text)) return 'root';
    if (/document|note/.test(text)) return 'document';
    if (/registry|entity|character|location|organization|concept/.test(text)) return 'identity';
    if (/fact|relationship|relation|hypergraph/.test(text)) return 'relationship';
    return 'unknown';
}

function routeLane(edge: GalaxyInputEdge, source: TransitStation, target: TransitStation): TransitLane {
    const text = edge.type.toLowerCase();
    if (/causal|cause|effect/.test(text)) return 'causal';
    if (/temporal|before|after|timeline/.test(text)) return 'timeline';
    if (/event/.test(text)) return 'event';
    if (/evidence|anchor|chunk|source/.test(text)) return 'evidence';
    if (/identity|entity|alias/.test(text)) return 'identity';
    if (/proposed/.test(text)) return 'proposed';
    if (/review|candidate/.test(text)) return 'review';
    if (/bridge|transfer|target/.test(text)) return 'transfer';
    if (source.lane === target.lane) return source.lane;
    return target.stage >= source.stage ? target.lane : 'transfer';
}

function directedRoute(type: string): boolean {
    return /causal|cause|effect|temporal|before|after|parent|target|source|event|memory/i.test(type);
}

function packetTraceFromNode(node: GalaxyRenderableNode): GraphRebuildVisualTrace | undefined {
    return packetTraceFromRecord(node.metadata);
}

function packetTraceFromRecord(record: Record<string, unknown> | undefined): GraphRebuildVisualTrace | undefined {
    const trace = recordValue(record?.['visualTrace']);
    if (trace && stringValue(trace['source']) === 'rust_atlas_packet') return trace as unknown as GraphRebuildVisualTrace;
    if (stringValue(record?.['sourceContract']) === 'rust-atlas-packet') {
        return {
            source: 'rust_atlas_packet',
            sourceId: cleanToken(stringValue(record?.['visualSourceId']), stringValue(record?.['sourceId'])),
            family: cleanToken(stringValue(record?.['visualFamily']), stringValue(record?.['graphFamily']), stringValue(record?.['atlasFamily'])),
            packetSnapshotId: stringValue(record?.['packetSnapshotId']),
            packetScopeId: stringValue(record?.['packetScopeId']),
            sourceContract: stringValue(record?.['sourceContract']),
            vectorContract: stringValue(record?.['vectorContract']),
            packetObjectId: stringValue(record?.['atlasObjectId']),
            packetTargetId: stringValue(record?.['atlasTargetId']),
            evidenceIds: arrayStrings(record?.['evidenceIds']),
        };
    }
    return undefined;
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function arrayStrings(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => stringValue(item)).filter(Boolean) : [];
}

function stringValue(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function cleanToken(...values: Array<string | undefined>): string {
    return values.find((value) => value && value.trim())?.trim() || 'unknown';
}

function uniqueStrings(...values: Array<string[] | undefined>): string[] {
    return [...new Set(values.flatMap((ids) => ids || []).filter(Boolean))];
}

function countBy<T>(items: T[], key: (item: T) => string): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const item of items) {
        const value = key(item) || 'unknown';
        counts[value] = (counts[value] || 0) + 1;
    }
    return counts;
}
