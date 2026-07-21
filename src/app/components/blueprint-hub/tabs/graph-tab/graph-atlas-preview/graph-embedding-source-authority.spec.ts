import { describe, expect, it } from 'vitest';

import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { EmbeddingAtlasData } from './graph-embedding-atlas';
import {
    graphRebuildOwnsEmbeddingView,
    PREPARING_GRAPH_REBUILD_ATLAS,
    resolveEmbeddingAtlasAuthority,
} from './graph-embedding-source-authority';

const semanticAtlas: EmbeddingAtlasData = {
    nodes: [{ id: 'entity:only', label: 'Entity only', kind: 'entity', x: 0, y: 0, z: 0 }],
    edges: [],
    sourceLabel: 'semantic atlas rows',
    searchIndex: [],
};

const graphAtlas: EmbeddingAtlasData = {
    nodes: [{ id: 'target:1', label: 'Target', kind: 'chunk', x: 0, y: 0, z: 0 }],
    edges: [],
    sourceLabel: 'graph rebuild snapshot',
    searchIndex: [],
};

const snapshot = {
    id: 'snapshot-1',
    embeddingTargets: [{ id: 'target:1', kind: 'chunk' }],
} as GraphRebuildSnapshot;

describe('embedding source authority', () => {
    it('never substitutes semantic entity rows while graph-rebuild truth owns Embed mode', () => {
        expect(graphRebuildOwnsEmbeddingView('embeddings', snapshot)).toBe(true);
        expect(resolveEmbeddingAtlasAuthority('embeddings', snapshot, null, semanticAtlas))
            .toBe(PREPARING_GRAPH_REBUILD_ATLAS);
    });

    it('publishes the requested graph-rebuild projection once resident', () => {
        expect(resolveEmbeddingAtlasAuthority('embeddings', snapshot, graphAtlas, semanticAtlas))
            .toBe(graphAtlas);
    });

    it('preserves semantic rows when no graph-rebuild target universe exists', () => {
        expect(resolveEmbeddingAtlasAuthority('embeddings', null, null, semanticAtlas))
            .toBe(semanticAtlas);
    });
});
