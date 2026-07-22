import type { EmbeddingAtlasData } from './graph-embedding-atlas';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import {
    filterGraphForCanvasLens,
    type GraphCanvasGraphSlice,
    type GraphCanvasLens,
} from './graph-canvas-interaction';
import {
    graphTopologyLaneForFamily,
    graphTopologyReviewStateForAdmission,
    graphTopologyReviewStateForStatus,
    type GraphTopologyReviewState,
} from './graph-topology-style-contract';

export function graphProjectionParityApplies(layoutMode: string, manifoldMode: string): boolean {
    return layoutMode === 'hopfProjection' && manifoldMode === 'hopf';
}

export function graphProjectionParitySlice(
    atlas: EmbeddingAtlasData,
    canvasLens: GraphCanvasLens,
    graphKindFilter: string,
): GraphCanvasGraphSlice {
    const nodes = atlas.nodes.map(graphProjectionParityNode);
    const edges = atlas.edges.map(graphProjectionParityEdge);
    const lensSlice = filterGraphForCanvasLens(nodes, edges, canvasLens);
    if (graphKindFilter === 'all') return lensSlice;

    const allowed = new Set(
        lensSlice.nodes
            .filter((node) => normalizeGraphKind(graphProjectionFamily(node)) === graphKindFilter)
            .map((node) => node.id),
    );
    return {
        nodes: lensSlice.nodes.filter((node) => allowed.has(node.id)),
        edges: lensSlice.edges.filter((edge) => allowed.has(edge.sourceId) && allowed.has(edge.targetId)),
    };
}

export function graphProjectionParityNode(node: GalaxyRenderableNode): GalaxyRenderableNode {
    const family = graphProjectionFamily(node);
    return {
        ...node,
        metadata: {
            ...(node.metadata || {}),
            graphFamily: family,
            canvasLens: metadataString(node.metadata, 'canvasLens') || graphTopologyLaneForFamily(family),
            reviewState: graphProjectionReviewState(node.metadata),
        },
    };
}

function graphProjectionParityEdge(edge: GalaxyInputEdge): GalaxyInputEdge {
    const family = graphProjectionEdgeFamily(edge);
    return {
        ...edge,
        metadata: {
            ...(edge.metadata || {}),
            graphFamily: family,
            canvasLens: metadataString(edge.metadata, 'canvasLens') || graphTopologyLaneForFamily(family),
            reviewState: graphProjectionReviewState(edge.metadata),
        },
    };
}

function graphProjectionFamily(node: GalaxyRenderableNode): string {
    const metadata = node.metadata;
    return metadataString(metadata, 'graphFamily')
        || metadataString(metadata, 'atlasFamily')
        || metadataString(metadata, 'visualFamily')
        || visualTraceFamily(metadata)
        || familyFromKind(node.kind);
}

function graphProjectionEdgeFamily(edge: GalaxyInputEdge): string {
    return metadataString(edge.metadata, 'graphFamily')
        || metadataString(edge.metadata, 'visualFamily')
        || visualTraceFamily(edge.metadata)
        || familyFromKind(edge.type);
}

function graphProjectionReviewState(metadata: Record<string, unknown> | undefined): GraphTopologyReviewState {
    const explicit = metadataString(metadata, 'reviewState');
    if (explicit === 'accepted' || explicit === 'proposed' || explicit === 'rejected' || explicit === 'muted') {
        return explicit;
    }
    const admission = metadataString(metadata, 'signalAdmissionStatus')
        || metadataString(metadata, 'admissionStatus');
    if (admission) return graphTopologyReviewStateForAdmission(admission);
    return graphTopologyReviewStateForStatus(metadataString(metadata, 'atlasStatus')
        || metadataString(metadata, 'status')
        || metadataString(metadata, 'graphTruthStatus'));
}

function visualTraceFamily(metadata: Record<string, unknown> | undefined): string {
    const trace = metadata?.['visualTrace'];
    if (!trace || typeof trace !== 'object') return '';
    const family = (trace as Record<string, unknown>)['family'];
    return typeof family === 'string' ? family : '';
}

function familyFromKind(value: string): string {
    const normalized = normalizeGraphKind(value);
    if (normalized.includes('entity') || normalized.includes('anchor')) return 'entity';
    if (normalized.includes('chunk') || normalized.includes('note') || normalized.includes('document') || normalized.includes('structure')) return 'structure';
    if (normalized.includes('discourse') || normalized.includes('wormhole')) return 'discourse';
    if (normalized.includes('review') || normalized.includes('candidate')) return 'review';
    return 'fact';
}

function metadataString(metadata: Record<string, unknown> | undefined, key: string): string {
    const value = metadata?.[key];
    return typeof value === 'string' && value.trim() ? value.trim() : '';
}

function normalizeGraphKind(kind: string): string {
    return String(kind || 'generic').trim().toLowerCase().replace(/[_\s]+/g, '-');
}
