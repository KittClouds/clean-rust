import { describe, expect, it } from 'vitest';

import { buildHybridEmbeddingValidationReceipt } from './hybrid-embedding-validation';
import { hybridEmbeddingInputHash, hybridEmbeddingSpaceContract } from './manifold-atlas.types';

describe('buildHybridEmbeddingValidationReceipt', () => {
    it('computes local neighborhood evidence while leaving cross-run stability pending', () => {
        const nodes = [
            { id: 'entity::kai', vector: [1, 0, 0] },
            { id: 'entity::rift', vector: [0.95, 0.05, 0] },
            { id: 'entity::hazel', vector: [0, 1, 0] },
        ];
        const contract = hybridEmbeddingSpaceContract({
            modelId: 'onnx-community/embeddinggemma-300m-ONNX',
            modelVersion: 'hf-main',
            dimensions: 3,
            executionProvider: 'directml',
            runId: 'semantic-run-7',
            inputHash: hybridEmbeddingInputHash(nodes),
        });

        const receipt = buildHybridEmbeddingValidationReceipt(contract, {
            nodes,
            edges: [{ sourceId: 'entity::kai', targetId: 'entity::rift' }],
        });

        expect(receipt.status).toBe('pending');
        expect(receipt.checks).toEqual({
            neighborStability: 'pending',
            continuity: 'passed',
            clusterDensity: 'passed',
            hubness: 'passed',
            connectedComponents: 'passed',
            badNeighborRejection: 'passed',
        });
        expect(receipt.metrics).toMatchObject({
            nodeCount: 3,
            validNodeCount: 3,
            vectorDimensions: 3,
            candidateEdgesTested: 1,
            candidateEdgesInNeighborhood: 1,
            connectedComponents: 1,
            neighborPairKeys: [
                'entity::hazel->entity::kai',
                'entity::hazel->entity::rift',
                'entity::kai->entity::hazel',
                'entity::kai->entity::rift',
                'entity::rift->entity::hazel',
                'entity::rift->entity::kai',
            ],
            previousNeighborPairs: 0,
            stableNeighborPairs: 0,
            neighborStabilityRatio: 0,
            trustworthinessScore: expect.any(Number),
            continuityScore: 1,
            localDensityMin: 1,
            localDensityAverage: 1,
            localDensityMax: 1,
            mutualNeighborRatio: 1,
            componentSizes: [3],
        });
        expect(receipt.evidence).toContain('neighbor_stability:pending:stable_0/0:ratio_0');
        expect(receipt.rejectedNeighborReceipts).toHaveLength(0);
    });

    it('passes neighbor stability when a previous run has the same top-k neighborhood', () => {
        const nodes = [
            { id: 'entity::kai', vector: [1, 0, 0] },
            { id: 'entity::rift', vector: [0.95, 0.05, 0] },
            { id: 'entity::hazel', vector: [0, 1, 0] },
        ];
        const contract = hybridEmbeddingSpaceContract({
            dimensions: 3,
            inputHash: hybridEmbeddingInputHash(nodes),
        });
        const first = buildHybridEmbeddingValidationReceipt(contract, {
            nodes,
            edges: [{ sourceId: 'entity::kai', targetId: 'entity::rift' }],
        });

        const second = buildHybridEmbeddingValidationReceipt(contract, {
            nodes: [...nodes].reverse(),
            edges: [{ sourceId: 'entity::kai', targetId: 'entity::rift' }],
        }, first);

        expect(second.checks.neighborStability).toBe('passed');
        expect(second.metrics?.previousNeighborGraphHash).toBe(first.metrics?.neighborGraphHash);
        expect(second.metrics?.stableNeighborPairs).toBe(first.metrics?.neighborPairs);
        expect(second.metrics?.neighborStabilityRatio).toBe(1);
    });

    it('fails hubness when one point absorbs too many one-way top-k neighborhoods', () => {
        const nodes = [
            { id: 'entity::hub', vector: [1, 0, 0, 0, 0] },
            { id: 'entity::a', vector: [0.8, 0.6, 0, 0, 0] },
            { id: 'entity::b', vector: [0.8, 0, 0.6, 0, 0] },
            { id: 'entity::c', vector: [0.8, 0, 0, 0.6, 0] },
            { id: 'entity::d', vector: [0.8, 0, 0, 0, 0.6] },
        ];
        const contract = hybridEmbeddingSpaceContract({
            dimensions: 5,
            inputHash: hybridEmbeddingInputHash(nodes),
        });

        const receipt = buildHybridEmbeddingValidationReceipt({
            ...contract,
            neighborhood: {
                ...contract.neighborhood,
                k: 1,
            },
        }, { nodes });

        expect(receipt.status).toBe('failed');
        expect(receipt.checks.hubness).toBe('failed');
        expect(receipt.metrics?.maxHubInbound).toBeGreaterThan(receipt.metrics?.hubnessLimit || 0);
        expect(receipt.metrics?.mutualNeighborRatio).toBeLessThan(0.5);
    });

    it('fails closed when vectors do not share one dimensional contract', () => {
        const nodes = [
            { id: 'entity::kai', vector: [1, 0, 0] },
            { id: 'entity::rift', vector: [1, 0] },
        ];
        const contract = hybridEmbeddingSpaceContract({
            dimensions: 3,
            inputHash: hybridEmbeddingInputHash(nodes),
        });

        const receipt = buildHybridEmbeddingValidationReceipt(contract, { nodes });

        expect(receipt.status).toBe('failed');
        expect(receipt.checks.badNeighborRejection).toBe('failed');
        expect(receipt.metrics?.dimensionMismatchCount).toBe(1);
        expect(receipt.rejectedNeighborReceipts).toContain('bad_neighbor:dimension_mismatch:entity::rift:got_2:expected_3');
    });
});
