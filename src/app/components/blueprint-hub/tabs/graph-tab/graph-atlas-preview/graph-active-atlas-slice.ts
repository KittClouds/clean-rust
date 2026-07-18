import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import type { EmbeddingAtlasData, EmbeddingQueryTrace } from './graph-embedding-atlas';
import { filterGraphForCanvasLens, type GraphCanvasLens } from './graph-canvas-interaction';
import { graphProjectionParitySlice } from './graph-projection-parity';

export type ActiveAtlasMode = 'entities' | 'graph' | 'embeddings';

export interface ActiveAtlasSlice {
    nodes: GalaxyRenderableNode[];
    graphEdges: GalaxyInputEdge[];
}

export interface ActiveAtlasSliceInput {
    mode: ActiveAtlasMode;
    baseEdges: GalaxyInputEdge[];
    entityNodes: GalaxyRenderableNode[];
    graphNodes: GalaxyRenderableNode[];
    graphEdges: GalaxyInputEdge[];
    graphKindFilter: string;
    canvasLens: GraphCanvasLens;
    projectionAtlas: EmbeddingAtlasData | null;
    embeddingNodes: GalaxyRenderableNode[];
    embeddingEdges: GalaxyInputEdge[];
    trace: EmbeddingQueryTrace | null;
}

export function buildActiveAtlasSlice(input: ActiveAtlasSliceInput): ActiveAtlasSlice {
    if (input.mode === 'entities') {
        return { nodes: input.entityNodes, graphEdges: input.baseEdges };
    }
    if (input.mode === 'graph') {
        if (input.projectionAtlas) {
            const slice = graphProjectionParitySlice(
                input.projectionAtlas,
                input.canvasLens,
                input.graphKindFilter,
            );
            return { nodes: slice.nodes, graphEdges: slice.edges };
        }
        const lensSlice = filterGraphForCanvasLens(input.graphNodes, input.graphEdges, input.canvasLens);
        const allowed = input.graphKindFilter === 'all' ? null : new Set(
            lensSlice.nodes
                .filter((node) => normalizeGraphKind(node.kind) === input.graphKindFilter)
                .map((node) => node.id),
        );
        return {
            nodes: allowed ? lensSlice.nodes.filter((node) => allowed.has(node.id)) : lensSlice.nodes,
            graphEdges: allowed
                ? lensSlice.edges.filter((edge) => allowed.has(edge.sourceId) && allowed.has(edge.targetId))
                : lensSlice.edges,
        };
    }
    return {
        nodes: input.trace ? [input.trace.queryNode, ...input.embeddingNodes] : input.embeddingNodes,
        graphEdges: input.trace ? [...input.trace.edges, ...input.embeddingEdges] : input.embeddingEdges,
    };
}

export function normalizeGraphKind(kind: string): string {
    return String(kind || 'generic').trim().toLowerCase().replace(/[_\s]+/g, '-');
}
