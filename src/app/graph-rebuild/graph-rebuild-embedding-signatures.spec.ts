import { describe, expect, it } from 'vitest';

import {
    embeddingModelAdapterFromSelection,
    normalizeEmbeddingProfile,
} from './graph-rebuild-embedding-signatures';

describe('embedding model adapter boundary', () => {
    it('keeps legacy Leaf-IR adapters as retrieval with derived topology', () => {
        const adapter = embeddingModelAdapterFromSelection({
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'mongodb-leaf-ir',
            embeddingModelLabel: 'MDBR Leaf IR',
            embeddingDimensionLabel: '384d',
            nliModelId: 'nli',
        });

        expect(adapter).toMatchObject({
            modelFamily: 'mdbr-leaf',
            selectedDimensions: 384,
            taskProfile: 'retrieval',
            topologySupport: 'derived',
            supportsMultiVector: false,
        });
        expect(adapter.vectorHeads).toEqual([{
            id: 'dense',
            kind: 'dense',
            dimensions: 384,
            normalized: true,
            required: true,
            purpose: 'single dense semantic vector',
        }]);
    });

    it('keeps Leaf-MT and Jina v5 as config choices with native topology heads', () => {
        const leafMt = normalizeEmbeddingProfile({
            modelId: 'mongodb-leaf-mt',
            modelLabel: 'MDBR Leaf MT',
            dimensionLabel: '384d',
        });
        const jina = normalizeEmbeddingProfile({
            modelId: 'jina-v5-topology',
            modelLabel: 'Jina v5 Topology',
            dimensionLabel: '786d',
        });

        expect(leafMt).toMatchObject({
            modelFamily: 'mdbr-leaf-mt',
            nativeDimensions: 384,
            selectedDimensions: 384,
            taskProfile: 'multi_task',
            topologySupport: 'native',
            supportsMultiVector: true,
        });
        expect(jina).toMatchObject({
            modelFamily: 'jina-v5',
            selectedDimensions: 786,
            taskProfile: 'semantic_topology',
            topologySupport: 'native',
            supportsMultiVector: true,
        });
        expect(leafMt.vectorHeads.map((head) => head.id)).toEqual([
            'document',
            'query',
            'topology',
            'classification',
        ]);
        expect(jina.vectorHeads.map((head) => head.id)).toEqual([
            'document',
            'query',
            'topology',
            'classification',
        ]);
    });

    it('preserves explicit custom vector heads', () => {
        const profile = normalizeEmbeddingProfile({
            modelId: 'external-research-model',
            modelLabel: 'External Research Model',
            modelFamily: 'external',
            dimensionLabel: '1024d',
            taskProfile: 'semantic_topology',
            topologySupport: 'native',
            vectorSource: 'external',
            vectorHeads: [{
                id: 'entity-linker',
                kind: 'topology',
                dimensions: 1024,
                normalized: true,
                required: false,
                purpose: 'entity topology sidecar',
            }],
        });

        expect(profile).toMatchObject({
            vectorSource: 'external',
            selectedDimensions: 1024,
            supportsMultiVector: false,
        });
        expect(profile.vectorHeads[0]).toMatchObject({
            id: 'entity-linker',
            kind: 'topology',
            dimensions: 1024,
        });
    });
});
