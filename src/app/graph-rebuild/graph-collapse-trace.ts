import type { GraphAtlasPacket } from './graph-atlas-packet';
import type { GraphRebuildEmbeddingTarget, GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export type GraphCollapseBoundary =
    | 'source_evidence'
    | 'typescript_snapshot'
    | 'typescript_atlas_packet'
    | 'native_response'
    | 'filtered_targets'
    | 'sealed_packet'
    | 'persisted_snapshot'
    | 'rendered_inventory';

export interface GraphCollapseSample {
    boundary: GraphCollapseBoundary;
    capturedAt: number;
    counters: Record<string, number>;
}

export interface GraphCollapseTrace {
    schemaVersion: 'phoenix-graph-collapse-trace/v1';
    snapshotId: string;
    scopeId: string;
    samples: GraphCollapseSample[];
}

interface NativeBoundarySidecar {
    embeddingTargets?: GraphRebuildEmbeddingTarget[];
    atlasPacket?: GraphAtlasPacket;
    factGraph?: {
        atoms?: unknown[];
        evidenceAnchors?: unknown[];
        bundles?: unknown[];
        facts?: unknown[];
        roles?: unknown[];
        projectedEdges?: unknown[];
    };
}

const TRACE_LIMIT = 12;
const traces = new Map<string, GraphCollapseTrace>();
let latestSnapshotId = '';

export function recordGraphCollapseBoundary(
    snapshotId: string,
    scopeId: string,
    boundary: GraphCollapseBoundary,
    counters: Record<string, number>,
): GraphCollapseTrace {
    const trace = traces.get(snapshotId) || {
        schemaVersion: 'phoenix-graph-collapse-trace/v1' as const,
        snapshotId,
        scopeId,
        samples: [],
    };
    const normalized = sortedCounters(counters);
    const existing = trace.samples.find((sample) => sample.boundary === boundary);
    if (existing && sameCounters(existing.counters, normalized)) return trace;
    const sample: GraphCollapseSample = { boundary, capturedAt: Date.now(), counters: normalized };
    trace.samples = [...trace.samples.filter((row) => row.boundary !== boundary), sample];
    traces.set(snapshotId, trace);
    latestSnapshotId = snapshotId;
    trimTraces();
    publishTrace(trace, sample);
    return trace;
}

export function recordGraphCollapseSnapshotBoundary(
    snapshot: GraphRebuildSnapshot,
    boundary: Extract<GraphCollapseBoundary, 'typescript_snapshot' | 'typescript_atlas_packet' | 'sealed_packet' | 'persisted_snapshot'>,
    extra: Record<string, number> = {},
): GraphCollapseTrace {
    return recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, boundary, {
        ...snapshotCounters(snapshot),
        ...extra,
    });
}

export function recordGraphCollapseNativeBoundary(
    snapshot: GraphRebuildSnapshot,
    sidecar: NativeBoundarySidecar | null,
): GraphCollapseTrace {
    const factGraph = sidecar?.factGraph;
    return recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'native_response', {
        nativeResponseAvailable: sidecar ? 1 : 0,
        nativeTargets: sidecar?.embeddingTargets?.length || 0,
        nativePacketObjects: sidecar?.atlasPacket?.objects.length || 0,
        nativePacketTargets: sidecar?.atlasPacket?.manifoldTargets.length || 0,
        nativeAtoms: factGraph?.atoms?.length || 0,
        nativeEvidenceAnchors: factGraph?.evidenceAnchors?.length || 0,
        nativeBundles: factGraph?.bundles?.length || 0,
        nativeFacts: factGraph?.facts?.length || 0,
        nativeRoles: factGraph?.roles?.length || 0,
        nativeProjectedEdges: factGraph?.projectedEdges?.length || 0,
        ...familyCounters('nativePacketFamily', sidecar?.atlasPacket),
        ...targetCounters('nativeTargetLane', sidecar?.embeddingTargets || []),
    });
}

export function recordGraphCollapseFilteredTargets(
    snapshot: GraphRebuildSnapshot,
    before: readonly GraphRebuildEmbeddingTarget[],
    after: readonly GraphRebuildEmbeddingTarget[],
): GraphCollapseTrace {
    return recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'filtered_targets', {
        beforeTargets: before.length,
        afterTargets: after.length,
        droppedTargets: Math.max(0, before.length - after.length),
        ...targetCounters('beforeLane', before),
        ...targetCounters('afterLane', after),
    });
}

export function recordGraphCollapseRenderedInventory(
    snapshot: GraphRebuildSnapshot,
    nodes: number,
    edges: number,
    kindCounts: Array<{ kind: string; count: number }>,
): GraphCollapseTrace {
    return recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'rendered_inventory', {
        renderedNodes: nodes,
        renderedEdges: edges,
        ...Object.fromEntries(kindCounts.map((row) => [`renderedKind.${row.kind}`, row.count])),
    });
}

export function graphCollapseTrace(snapshotId: string): GraphCollapseTrace | null {
    return traces.get(snapshotId) || null;
}

export function latestGraphCollapseTrace(): GraphCollapseTrace | null {
    return latestSnapshotId ? graphCollapseTrace(latestSnapshotId) : null;
}

export function clearGraphCollapseTraces(): void {
    traces.clear();
    latestSnapshotId = '';
}

function snapshotCounters(snapshot: GraphRebuildSnapshot): Record<string, number> {
    return {
        notes: snapshot.noteIds.length,
        registryEntities: snapshot.counters.entities || 0,
        chunks: snapshot.chunks.length,
        mentions: snapshot.mentions.length,
        acceptedAnchors: snapshot.entityAnchors.length,
        nodes: snapshot.nodes.length,
        edges: snapshot.edges.length,
        relationships: snapshot.relationships.length,
        events: snapshot.events.length,
        temporalEdges: snapshot.temporalEdges.length,
        causalEdges: snapshot.causalEdges.length,
        memoryStates: snapshot.memoryState.length,
        embeddingTargets: snapshot.embeddingTargets.length,
        compilerAtoms: snapshot.graphCompiler?.atoms.length || 0,
        compilerBundles: snapshot.graphCompiler?.bundles.length || 0,
        compilerFacts: snapshot.graphCompiler?.facts.length || 0,
        compilerProjectedEdges: snapshot.graphCompiler?.projectedEdges.length || 0,
        packetObjects: snapshot.atlasPacket?.objects.length || 0,
        packetTargets: snapshot.atlasPacket?.manifoldTargets.length || 0,
        documentHyperedges: snapshot.documentCompilerSummary?.hyperedges.length || 0,
        ...familyCounters('packetFamily', snapshot.atlasPacket),
        ...targetCounters('targetLane', snapshot.embeddingTargets),
    };
}

function familyCounters(prefix: string, packet: GraphAtlasPacket | undefined): Record<string, number> {
    const counts = new Map<string, number>();
    for (const object of packet?.objects || []) counts.set(object.family, (counts.get(object.family) || 0) + 1);
    return Object.fromEntries([...counts.entries()].map(([family, count]) => [`${prefix}.${family}`, count]));
}

function targetCounters(prefix: string, targets: readonly GraphRebuildEmbeddingTarget[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const target of targets) {
        const lane = target.lane || target.kind || 'unknown';
        counts.set(lane, (counts.get(lane) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].map(([lane, count]) => [`${prefix}.${lane}`, count]));
}

function sortedCounters(counters: Record<string, number>): Record<string, number> {
    return Object.fromEntries(Object.entries(counters).sort(([left], [right]) => left.localeCompare(right)));
}

function sameCounters(left: Record<string, number>, right: Record<string, number>): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
}

function trimTraces(): void {
    while (traces.size > TRACE_LIMIT) traces.delete(traces.keys().next().value as string);
}

function publishTrace(trace: GraphCollapseTrace, sample: GraphCollapseSample): void {
    console.info('[GraphCollapseTrace]', trace.snapshotId, sample.boundary, sample.counters);
    if (typeof window === 'undefined') return;
    const diagnosticWindow = window as typeof window & { __graphCollapseTrace?: GraphCollapseTrace };
    diagnosticWindow.__graphCollapseTrace = trace;
    window.dispatchEvent(new CustomEvent('graph-collapse-trace-updated', { detail: { trace, sample } }));
}
