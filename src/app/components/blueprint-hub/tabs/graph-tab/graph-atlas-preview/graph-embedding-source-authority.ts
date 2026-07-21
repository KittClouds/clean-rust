import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';

import type { EmbeddingAtlasData } from './graph-embedding-atlas';
import { graphRebuildEmbeddingTargetCount } from './graph-rebuild-embedding-atlas';

export type EmbeddingAtlasMode = 'entities' | 'graph' | 'embeddings';

export const PREPARING_GRAPH_REBUILD_ATLAS: EmbeddingAtlasData = Object.freeze({
    nodes: [],
    edges: [],
    sourceLabel: 'authoritative graph rebuild projection preparing',
    searchIndex: [],
});

export function graphRebuildOwnsEmbeddingView(
    atlasMode: EmbeddingAtlasMode,
    snapshot: GraphRebuildSnapshot | null,
): boolean {
    return atlasMode === 'embeddings' && graphRebuildEmbeddingTargetCount(snapshot) > 0;
}

export function resolveEmbeddingAtlasAuthority(
    atlasMode: EmbeddingAtlasMode,
    snapshot: GraphRebuildSnapshot | null,
    graphRebuildAtlas: EmbeddingAtlasData | null,
    semanticAtlas: EmbeddingAtlasData,
): EmbeddingAtlasData {
    if (graphRebuildAtlas) return graphRebuildAtlas;
    if (graphRebuildOwnsEmbeddingView(atlasMode, snapshot)) return PREPARING_GRAPH_REBUILD_ATLAS;
    return semanticAtlas;
}
