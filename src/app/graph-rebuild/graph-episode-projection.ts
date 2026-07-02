import type {
    GraphRebuildChunk,
    GraphRebuildEpisode,
    GraphRebuildEpisodeConnection,
    GraphRebuildEpisodeProjectionEdge,
    GraphRebuildEpisodeProjectionEdgeStatus,
    GraphRebuildEvent,
} from './graph-rebuild-snapshot';

export function graphEpisodeTargetId(episodeId: string): string {
    return `embed:episode:${episodeId}`;
}

export function graphEventTargetId(eventId: string): string {
    return `embed:event:${eventId}`;
}

export function graphChunkTargetId(chunkId: string): string {
    return `embed:chunk:${chunkId}`;
}

export function graphDocumentStructureTargetId(noteId: string): string {
    return `embed:structure-root:${noteId}:document-structure`;
}

export function buildGraphEpisodeProjectionEdges(
    episodes: readonly GraphRebuildEpisode[],
    events: readonly GraphRebuildEvent[],
    chunks: readonly GraphRebuildChunk[],
    episodeConnections: readonly GraphRebuildEpisodeConnection[],
): GraphRebuildEpisodeProjectionEdge[] {
    const eventById = new Map(events.map((event) => [event.id, event]));
    const chunkById = new Map(chunks.map((chunk) => [chunk.id, chunk]));
    const edges = new Map<string, GraphRebuildEpisodeProjectionEdge>();
    for (const episode of episodes) {
        add(edges, {
            schemaVersion: 'phoenix-episode-projection-edge/v1',
            id: `episode_projection:document_contains_episode:${episode.noteId}:${episode.id}`,
            kind: 'document_contains_episode',
            sourceId: `${episode.noteId}:document-structure`,
            targetId: episode.id,
            sourceTargetId: graphDocumentStructureTargetId(episode.noteId),
            targetTargetId: graphEpisodeTargetId(episode.id),
            noteId: episode.noteId,
            episodeId: episode.id,
            relationType: 'document_contains_episode',
            evidenceIds: [],
            confidence: 1,
            status: 'structural',
            noTopologyCommit: true,
            rationale: ['episode_projection:document_spine:no_topology_commit'],
        });

        const chunkIds = new Set<string>();
        for (const eventId of episode.eventIds) {
            const event = eventById.get(eventId);
            if (!event) continue;
            add(edges, {
                schemaVersion: 'phoenix-episode-projection-edge/v1',
                id: `episode_projection:episode_contains_event:${episode.id}:${event.id}`,
                kind: 'episode_contains_event',
                sourceId: episode.id,
                targetId: event.id,
                sourceTargetId: graphEpisodeTargetId(episode.id),
                targetTargetId: graphEventTargetId(event.id),
                noteId: episode.noteId,
                episodeId: episode.id,
                eventId: event.id,
                relationType: 'episode_contains_event',
                evidenceIds: event.evidenceAnchorIds,
                confidence: event.confidence,
                status: 'structural',
                noTopologyCommit: true,
                rationale: ['episode_projection:event_membership:no_topology_commit'],
            });
            if (event.chunkId) chunkIds.add(event.chunkId);
        }
        for (const chunkId of chunkIds) {
            const chunk = chunkById.get(chunkId);
            add(edges, {
                schemaVersion: 'phoenix-episode-projection-edge/v1',
                id: `episode_projection:episode_contains_chunk:${episode.id}:${chunkId}`,
                kind: 'episode_contains_chunk',
                sourceId: episode.id,
                targetId: chunkId,
                sourceTargetId: graphEpisodeTargetId(episode.id),
                targetTargetId: graphChunkTargetId(chunkId),
                noteId: episode.noteId,
                episodeId: episode.id,
                chunkId,
                relationType: 'episode_contains_chunk',
                evidenceIds: episodeEventEvidenceIds(episode, eventById, chunkId),
                confidence: 0.9,
                status: 'structural',
                noTopologyCommit: true,
                rationale: [
                    'episode_projection:chunk_membership:no_topology_commit',
                    chunk ? `chunk_ordinal:${chunk.ordinal}` : '',
                ].filter(Boolean),
            });
        }
    }

    for (const connection of episodeConnections) {
        const kind = episodeConnectionProjectionKind(connection.kind);
        add(edges, {
            schemaVersion: 'phoenix-episode-projection-edge/v1',
            id: `episode_projection:${connection.id}`,
            kind,
            sourceId: connection.sourceEpisodeId,
            targetId: connection.targetEpisodeId,
            sourceTargetId: graphEpisodeTargetId(connection.sourceEpisodeId),
            targetTargetId: graphEpisodeTargetId(connection.targetEpisodeId),
            sourceEpisodeId: connection.sourceEpisodeId,
            targetEpisodeId: connection.targetEpisodeId,
            episodeConnectionId: connection.id,
            relationType: connection.relationType,
            evidenceIds: connection.evidenceIds,
            confidence: connection.confidence,
            status: episodeConnectionProjectionStatus(connection),
            noTopologyCommit: true,
            rationale: [
                'episode_projection:connection_overlay:no_topology_commit',
                ...connection.rationale,
            ],
        });
    }
    return [...edges.values()].sort((left, right) =>
        projectionRank(left.kind) - projectionRank(right.kind)
        || left.sourceTargetId.localeCompare(right.sourceTargetId)
        || left.targetTargetId.localeCompare(right.targetTargetId)
        || left.id.localeCompare(right.id),
    );
}

export function episodeProjectionEdgeCounters(edges: readonly GraphRebuildEpisodeProjectionEdge[]) {
    return {
        episodeProjectionEdges: edges.length,
        episodeProjectionStructuralEdges: edges.filter((edge) => edge.status === 'structural').length,
        episodeProjectionDerivedEdges: edges.filter((edge) => edge.status === 'derived').length,
        episodeProjectionCandidateEdges: edges.filter((edge) => edge.status === 'candidate_overlay').length,
    };
}

function add(
    edges: Map<string, GraphRebuildEpisodeProjectionEdge>,
    edge: GraphRebuildEpisodeProjectionEdge,
): void {
    if (!edge.sourceTargetId || !edge.targetTargetId || edge.sourceTargetId === edge.targetTargetId) return;
    edges.set(edge.id, edge);
}

function episodeConnectionProjectionKind(
    kind: GraphRebuildEpisodeConnection['kind'],
): GraphRebuildEpisodeProjectionEdge['kind'] {
    if (kind === 'episode_wormhole') return 'episode_wormhole_candidate';
    return kind;
}

function episodeConnectionProjectionStatus(
    connection: GraphRebuildEpisodeConnection,
): GraphRebuildEpisodeProjectionEdgeStatus {
    return connection.status === 'overlay_only' ? 'candidate_overlay' : 'derived';
}

function episodeEventEvidenceIds(
    episode: GraphRebuildEpisode,
    eventById: Map<string, GraphRebuildEvent>,
    chunkId: string,
): string[] {
    return [...new Set(episode.eventIds
        .map((eventId) => eventById.get(eventId))
        .filter((event): event is GraphRebuildEvent => !!event && event.chunkId === chunkId)
        .flatMap((event) => event.evidenceAnchorIds))];
}

function projectionRank(kind: GraphRebuildEpisodeProjectionEdge['kind']): number {
    switch (kind) {
        case 'document_contains_episode': return 0;
        case 'episode_contains_chunk': return 1;
        case 'episode_contains_event': return 2;
        case 'episode_temporal': return 3;
        case 'episode_causal': return 4;
        case 'episode_wormhole_candidate': return 5;
    }
}
