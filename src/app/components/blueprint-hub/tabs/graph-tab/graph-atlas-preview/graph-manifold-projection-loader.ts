import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { AtlasManifoldMode } from '../../../../../services/manifold-atlas.types';
import type { EmbeddingAtlasData } from './graph-embedding-atlas';
import {
    graphRebuildEmbeddingTargetCount,
    requireCachedGraphRebuildEmbeddingAtlas,
} from './graph-rebuild-embedding-atlas';

export type ManifoldProjectionSource = 'graph-rebuild-snapshot' | 'native-manifold-snapshot';

export interface ManifoldProjectionResolution {
    atlas: EmbeddingAtlasData;
    source: ManifoldProjectionSource;
}

export function manifoldProjectionRequestKey(
    snapshot: GraphRebuildSnapshot | null,
    manifold: AtlasManifoldMode,
    readContextKey: string,
): string {
    return `${snapshot?.id || 'native'}:${manifold}:${readContextKey}`;
}

export async function loadManifoldProjection(
    snapshot: GraphRebuildSnapshot | null,
    manifold: AtlasManifoldMode,
    loadNative: () => Promise<EmbeddingAtlasData>,
): Promise<ManifoldProjectionResolution> {
    if (snapshot && graphRebuildEmbeddingTargetCount(snapshot) > 0) {
        return {
            atlas: requireCachedGraphRebuildEmbeddingAtlas(snapshot, manifold),
            source: 'graph-rebuild-snapshot',
        };
    }
    return {
        atlas: await loadNative(),
        source: 'native-manifold-snapshot',
    };
}
