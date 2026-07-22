import { describe, expect, it } from 'vitest';

import {
    HYBRID_EMBEDDING_ARTIFACT_DOCUMENT_KEY,
    HYBRID_EMBEDDING_ARTIFACT_NAMESPACE,
    buildHybridEmbeddingPersistedArtifact,
    comparableHybridEmbeddingReceipt,
    hybridEmbeddingArtifactScope,
    hybridEmbeddingArtifactToScopedDocument,
    scopedDocumentToHybridEmbeddingArtifact,
} from './hybrid-embedding-artifact-store';
import { hybridEmbeddingInputHash, hybridEmbeddingSpaceContract } from './manifold-atlas.types';

describe('hybrid embedding artifact persistence helpers', () => {
    it('serializes Hybrid as a scoped candidate-only artifact with validation receipt', () => {
        const nodes = [
            { id: 'entity::kai', vector: [1, 0, 0] },
            { id: 'entity::rift', vector: [0, 1, 0] },
        ];
        const embeddingSpace = hybridEmbeddingSpaceContract({
            modelId: 'onnx-community/embeddinggemma-300m-ONNX',
            modelVersion: 'hf-main',
            dimensions: 3,
            executionProvider: 'directml',
            inputHash: hybridEmbeddingInputHash(nodes),
        });
        const scope = hybridEmbeddingArtifactScope({ mode: 'folder', folderId: 'folder-7', narrativeId: 'story-1' });

        const artifact = buildHybridEmbeddingPersistedArtifact(scope, embeddingSpace, {
            nodes,
            edges: [{ sourceId: 'entity::kai', targetId: 'entity::rift' }],
            sourceLabel: 'backend semantic atlas',
            projectionSource: 'semantic_atlas_rows',
        }, 'fallback', 1234);
        const document = hybridEmbeddingArtifactToScopedDocument(artifact);
        const parsed = scopedDocumentToHybridEmbeddingArtifact(document);

        expect(document).toMatchObject({
            id: `${HYBRID_EMBEDDING_ARTIFACT_NAMESPACE}:folder:folder-7:${HYBRID_EMBEDDING_ARTIFACT_DOCUMENT_KEY}`,
            scopeFolderId: 'folder:folder-7',
            narrativeId: 'story-1',
            namespace: HYBRID_EMBEDDING_ARTIFACT_NAMESPACE,
            documentKey: HYBRID_EMBEDDING_ARTIFACT_DOCUMENT_KEY,
            createdAt: 1234,
            updatedAt: 1234,
        });
        expect(parsed).toMatchObject({
            schemaVersion: 'phoenix-hybrid-embedding-artifact/v1',
            source: 'fallback',
            nodeCount: 2,
            edgeCount: 1,
            candidateOnly: true,
            committedTopologyWrites: 0,
            validationReceipt: embeddingSpace.validationReceipt,
            embeddingSpace: {
                authority: 'hybrid',
                candidateOnly: true,
                committedTopologyWrites: 0,
            },
        });
    });

    it('returns a previous receipt only for the same durable embedding contract', () => {
        const current = hybridEmbeddingSpaceContract({
            modelId: 'onnx-community/embeddinggemma-300m-ONNX',
            modelVersion: 'hf-main',
            dimensions: 768,
            executionProvider: 'directml',
            inputHash: 'input:fnv1a32:current',
        });
        const previous = buildHybridEmbeddingPersistedArtifact(
            hybridEmbeddingArtifactScope(),
            hybridEmbeddingSpaceContract({
                ...current,
                inputHash: 'input:fnv1a32:previous',
            }),
            { nodes: [], edges: [], sourceLabel: 'previous' },
            'native',
            10,
        );

        expect(comparableHybridEmbeddingReceipt(current, previous)).toBe(previous.validationReceipt);
    });

    it('does not compare stability across model or execution-provider contract changes', () => {
        const current = hybridEmbeddingSpaceContract({
            modelId: 'onnx-community/embeddinggemma-300m-ONNX',
            modelVersion: 'hf-main',
            dimensions: 768,
            executionProvider: 'directml',
            inputHash: 'input:fnv1a32:current',
        });
        const previous = buildHybridEmbeddingPersistedArtifact(
            hybridEmbeddingArtifactScope(),
            hybridEmbeddingSpaceContract({
                modelId: 'jinaai/jina-embeddings-v3',
                modelVersion: 'hf-main',
                dimensions: 768,
                executionProvider: 'cpu',
                inputHash: 'input:fnv1a32:previous',
            }),
            { nodes: [], edges: [], sourceLabel: 'previous' },
            'native',
            10,
        );

        expect(comparableHybridEmbeddingReceipt(current, previous)).toBeNull();
    });

    it('rejects persisted artifacts that claim topology writes', () => {
        const embeddingSpace = hybridEmbeddingSpaceContract();
        const artifact = buildHybridEmbeddingPersistedArtifact(
            hybridEmbeddingArtifactScope(),
            embeddingSpace,
            { nodes: [], edges: [], sourceLabel: 'bad' },
            'native',
        );
        const document = hybridEmbeddingArtifactToScopedDocument({
            ...artifact,
            committedTopologyWrites: 1 as 0,
        });

        expect(scopedDocumentToHybridEmbeddingArtifact(document)).toBeNull();
    });
});
