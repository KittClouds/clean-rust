import { describe, expect, it, vi } from 'vitest';

import {
    HOPF_MANIFOLD_CAPABILITIES,
    HYBRID_MANIFOLD_CAPABILITIES,
    type AtlasManifoldMode,
    type ManifoldAtlasSnapshot,
} from '../../../../../services/manifold-atlas.types';
import type { PhoenixUiApiService, SemanticAtlasEmbeddingAtlas } from '../../../../../services/phoenix-ui-api.service';
import {
    HOPF_MANIFOLD_ADAPTER,
    HYBRID_MANIFOLD_ADAPTER,
} from './graph-manifold-atlas';

describe('manifold atlas adapters', () => {
    it('marks Hybrid as the embedding space authority without topology writes', async () => {
        const phoenixUiApi = mockPhoenixUiApi(hybridSnapshot());

        const atlas = await HYBRID_MANIFOLD_ADAPTER.load(phoenixUiApi, {});

        expect(atlas.manifold?.mode).toBe('hybrid');
        expect(atlas.manifold?.embeddingSpace).toMatchObject({
            authority: 'hybrid',
            artifactKind: 'embedding-manifold',
            artifactId: expect.stringMatching(/^hybrid:embedding-space:[0-9a-f]{8}$/),
            cacheKey: expect.stringMatching(/^hybrid_embedding_space:[0-9a-f]{8}$/),
            inputHash: expect.stringMatching(/^input:fnv1a32:[0-9a-f]{8}$/),
            modelId: 'onnx-community/embeddinggemma-300m-ONNX',
            modelVersion: 'hf-main',
            dimensions: 3,
            executionProvider: 'directml',
            runId: 'semantic-run-7',
            normalized: true,
            normalization: 'unit_l2',
            metric: 'cosine',
            candidateOnly: true,
            committedTopologyWrites: 0,
            neighborhood: {
                method: 'top-k',
                k: 4,
                densityPolicy: 'local-density',
                hubnessPolicy: 'mutual-neighbor-required',
                outlierPolicy: 'review-visible',
            },
            validationReceipt: {
                receiptId: expect.stringMatching(/^hybrid-validation:[0-9a-f]{8}$/),
                status: 'pending',
                generatedBy: 'frontend-contract',
                checks: {
                    neighborStability: 'pending',
                    continuity: 'passed',
                    clusterDensity: 'passed',
                    hubness: 'passed',
                    connectedComponents: 'passed',
                    badNeighborRejection: 'passed',
                },
                metrics: {
                    nodeCount: 2,
                    validNodeCount: 2,
                    vectorDimensions: 3,
                    dimensionMismatchCount: 0,
                    candidateEdgesTested: 1,
                    candidateEdgesInNeighborhood: 1,
                    connectedComponents: 1,
                    largestComponentSize: 2,
                    localDensityMin: 1,
                    localDensityAverage: 1,
                    localDensityMax: 1,
                    mutualNeighborPairs: 1,
                    mutualNeighborRatio: 1,
                    maxHubInbound: 1,
                },
            },
        });
    });

    it('keeps Hybrid artifact identity stable for the same embedding inputs', async () => {
        const first = await HYBRID_MANIFOLD_ADAPTER.load(mockPhoenixUiApi(hybridSnapshot([
            semanticNode('entity::kai', [1, 0, 0]),
            semanticNode('entity::rift', [0, 1, 0]),
        ])), {});
        const second = await HYBRID_MANIFOLD_ADAPTER.load(mockPhoenixUiApi(hybridSnapshot([
            semanticNode('entity::rift', [0, 1, 0]),
            semanticNode('entity::kai', [1, 0, 0]),
        ])), {});

        expect(second.manifold?.embeddingSpace?.inputHash).toBe(first.manifold?.embeddingSpace?.inputHash);
        expect(second.manifold?.embeddingSpace?.artifactId).toBe(first.manifold?.embeddingSpace?.artifactId);
        expect(second.manifold?.embeddingSpace?.cacheKey).toBe(first.manifold?.embeddingSpace?.cacheKey);
    });

    it('leaves Hopf as a projection view without owning the embedding space', async () => {
        const phoenixUiApi = mockPhoenixUiApi(hopfSnapshot());

        const atlas = await HOPF_MANIFOLD_ADAPTER.load(phoenixUiApi, {});

        expect(atlas.manifold?.mode).toBe('hopf');
        expect(atlas.manifold?.embeddingSpace).toBeUndefined();
    });
});

function mockPhoenixUiApi(snapshot: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>): PhoenixUiApiService {
    return {
        loadManifoldAtlasSnapshot: vi.fn(async () => snapshot),
    } as unknown as PhoenixUiApiService;
}

function hybridSnapshot(nodes?: SemanticAtlasEmbeddingAtlas['nodes']): ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas> {
    return semanticSnapshot('hybrid', HYBRID_MANIFOLD_CAPABILITIES, nodes);
}

function hopfSnapshot(): ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas> {
    return semanticSnapshot('hopf', HOPF_MANIFOLD_CAPABILITIES);
}

function semanticSnapshot(
    manifold: AtlasManifoldMode,
    capabilities: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>['capabilities'],
    nodes: SemanticAtlasEmbeddingAtlas['nodes'] = [
        semanticNode('entity::kai', [1, 0, 0]),
        semanticNode('entity::rift', [0.95, 0.05, 0]),
    ],
    edges: SemanticAtlasEmbeddingAtlas['edges'] = [{
        id: 'entity::kai:candidate_relation:entity::rift',
        sourceId: 'entity::kai',
        targetId: 'entity::rift',
        type: 'candidate_relation',
        confidence: 0.92,
    }],
): ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas> {
    return {
        manifold,
        geometryVersion: `${manifold}_test_v1`,
        sourceLabel: 'test semantic atlas',
        capabilities,
        payload: {
            sourceLabel: 'test semantic atlas',
            projectionSource: 'semantic_atlas_rows',
            nodes,
            edges,
        },
    };
}

function semanticNode(id: string, vector: number[]): SemanticAtlasEmbeddingAtlas['nodes'][number] {
    return {
        id,
        label: id.replace(/^entity::/, ''),
        sourceType: 'entity',
        vector,
        modelId: 'onnx-community/embeddinggemma-300m-ONNX',
        modelVersion: 'hf-main',
        executionProvider: 'directml',
        runId: 'semantic-run-7',
        kind: 'CONCEPT',
    };
}
