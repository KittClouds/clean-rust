import type {
    GraphRebuildEpisodeProjectionEdge,
    GraphRebuildSnapshot,
} from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import { graphTopologyStyleForPacketRow } from './graph-topology-style-contract';

export function buildEpisodeProjectionCanvasEdges(
    snapshot: GraphRebuildSnapshot,
    nodes: readonly GalaxyRenderableNode[],
): GalaxyInputEdge[] {
    const projectionEdges = snapshot.episodeProjectionEdges || [];
    if (!projectionEdges.length || !nodes.length) return [];
    const nodeByTarget = nodeIdsByTarget(nodes);
    const nodeIds = new Set(nodes.map((node) => node.id));
    const out: GalaxyInputEdge[] = [];
    const seen = new Set<string>();
    for (const edge of projectionEdges) {
        const sourceId = resolveNodeId(edge.sourceTargetId, nodeByTarget, nodeIds);
        const targetId = resolveNodeId(edge.targetTargetId, nodeByTarget, nodeIds);
        if (!sourceId || !targetId || sourceId === targetId) continue;
        const id = `episode-projection:${edge.id}:${sourceId}->${targetId}`;
        if (seen.has(id)) continue;
        seen.add(id);
        out.push({
            id,
            sourceId,
            targetId,
            type: edge.kind,
            confidence: edge.confidence,
            metadata: episodeProjectionEdgeMetadata(edge),
        });
    }
    return out;
}

export function episodeProjectionEmbeddingEdge(edge: GraphRebuildEpisodeProjectionEdge): GalaxyInputEdge {
    return {
        id: `embed:${edge.id}`,
        sourceId: edge.sourceTargetId,
        targetId: edge.targetTargetId,
        type: edge.kind,
        confidence: edge.confidence,
        metadata: episodeProjectionEdgeMetadata(edge),
    };
}

export function episodeProjectionEdgeMetadata(edge: GraphRebuildEpisodeProjectionEdge): Record<string, unknown> {
    const colorKind = episodeProjectionColorKind(edge);
    const style = graphTopologyStyleForPacketRow({
        family: edge.kind === 'episode_wormhole_candidate' ? 'discourse' : 'structure',
        kind: colorKind,
        label: edge.kind,
        styleKey: colorKind,
    });
    return {
        sourceType: 'episode-projection-edge',
        sourceSystem: 'graph-rebuild',
        sourceId: edge.sourceId,
        visualSourceId: edge.sourceId,
        graphFamily: edge.kind === 'episode_wormhole_candidate' ? 'discourse' : 'structure',
        graphKind: edge.kind,
        graphColorKind: style.colorKind,
        styleKey: style.colorKind,
        graphRelationFamily: style.relationFamily || colorKind,
        canvasLens: edge.kind === 'episode_wormhole_candidate' ? 'discourse' : 'structure',
        reviewState: edge.status === 'candidate_overlay' ? 'proposed' : 'accepted',
        confidence: edge.confidence,
        interactionKind: edge.kind === 'episode_wormhole_candidate' ? 'wormhole' : 'episode_projection',
        noTopologyCommit: edge.noTopologyCommit,
        topologyCommit: false,
        graphPatch: false,
        mutationAllowed: false,
        detector: 'episodeProjection',
        episodeProjectionEdgeId: edge.id,
        episodeProjectionKind: edge.kind,
        episodeProjectionStatus: edge.status,
        relationType: edge.relationType,
        noteId: edge.noteId || '',
        episodeId: edge.episodeId || edge.sourceEpisodeId || '',
        sourceEpisodeId: edge.sourceEpisodeId || '',
        targetEpisodeId: edge.targetEpisodeId || '',
        eventId: edge.eventId || '',
        chunkId: edge.chunkId || '',
        evidenceIds: edge.evidenceIds,
        reasons: edge.rationale,
        searchableText: `${edge.kind} ${edge.relationType} ${edge.rationale.join(' ')}`,
        graphImpact: 'Episode projection edge is render-only; no Overgraph truth write or topology commit exists.',
    };
}

function nodeIdsByTarget(nodes: readonly GalaxyRenderableNode[]): Map<string, string> {
    const out = new Map<string, string>();
    for (const node of nodes) {
        out.set(node.id, node.id);
        addMetadataId(out, node, 'atlasTargetId');
        const trace = node.metadata?.['visualTrace'] as { packetTargetId?: unknown } | undefined;
        if (typeof trace?.packetTargetId === 'string') out.set(trace.packetTargetId, node.id);
    }
    return out;
}

function addMetadataId(out: Map<string, string>, node: GalaxyRenderableNode, key: string): void {
    const value = node.metadata?.[key];
    if (typeof value === 'string' && value) out.set(value, node.id);
}

function resolveNodeId(id: string, byTarget: Map<string, string>, nodeIds: Set<string>): string {
    if (nodeIds.has(id)) return id;
    return byTarget.get(id) || '';
}

function episodeProjectionColorKind(edge: GraphRebuildEpisodeProjectionEdge): string {
    if (edge.kind === 'episode_wormhole_candidate') return 'communication';
    if (edge.kind === 'episode_causal') return 'causalFact';
    if (edge.kind === 'episode_temporal') return 'temporalFact';
    return 'episode';
}
