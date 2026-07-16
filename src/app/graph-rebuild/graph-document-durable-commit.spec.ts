import { describe, expect, it } from 'vitest';

import {
    emptyGraphDocumentGraphMutationLedger,
    graphDocumentGraphMutationLedgerFromTruthCommits,
    graphDocumentGraphMutationLedgerFor,
} from './graph-document-durable-commit';
import {
    graphTruthCommitLedgerFor,
    resolveGraphTruthUiState,
    type GraphTruthCommitLike,
} from './graph-truth-commit-ledger';

describe('graph document mutation ledger', () => {
    it('starts empty without creating TypeScript document graph commits', () => {
        expect(emptyGraphDocumentGraphMutationLedger()).toEqual({
            schemaVersion: 'phoenix-document-graph-mutation-ledger/v1',
            records: [],
            counters: { commits: 0, active: 0, undone: 0, vertices: 0, edges: 0 },
        });
    });

    it('keeps persisted native mutation ledger counts readable', () => {
        const ledger = graphDocumentGraphMutationLedgerFor([
            {
                id: 'document-graph-mutation:commit-1',
                commitId: 'commit-1',
                topologyDiffId: 'diff-1',
                sourceObjectId: 'native-fact-1',
                receiptId: 'receipt-1',
                status: 'committed',
                vertexIds: ['fact-1', 'evidence-1'],
                edgeKeys: ['fact-1\u0000entity-1'],
                committedAt: 10,
            },
            {
                id: 'document-graph-mutation:commit-2',
                commitId: 'commit-2',
                topologyDiffId: 'diff-2',
                sourceObjectId: 'native-fact-2',
                receiptId: 'receipt-2',
                status: 'undone',
                vertexIds: ['fact-2'],
                edgeKeys: ['fact-2\u0000entity-2'],
                committedAt: 11,
                undoneAt: 12,
            },
        ]);

        expect(ledger.counters).toEqual({
            commits: 2,
            active: 1,
            undone: 1,
            vertices: 2,
            edges: 1,
        });
    });

    it('projects committed, reverted, and superseded document rows from GraphTruthCommit lineage', () => {
        const commits = graphTruthFixtures();
        const truth = graphTruthCommitLedgerFor(commits);
        const ledger = graphDocumentGraphMutationLedgerFromTruthCommits(commits);

        expect(resolveGraphTruthUiState(truth, 'commit-active')).toBe('committed');
        expect(resolveGraphTruthUiState(truth, 'receipt-active')).toBe('accepted');
        expect(resolveGraphTruthUiState(truth, 'commit-reverted')).toBe('reverted');
        expect(resolveGraphTruthUiState(truth, 'commit-old')).toBe('superseded');
        expect(ledger.authority).toBe('graph_truth_commit_projection');
        expect(ledger.records.map((row) => [row.commitId, row.status])).toEqual([
            ['commit-reverted', 'undone'],
            ['commit-old', 'undone'],
            ['commit-active', 'committed'],
        ]);
        expect(ledger.counters).toMatchObject({
            commits: 3,
            active: 1,
            undone: 2,
            vertices: 1,
            edges: 1,
        });
    });
});

function graphTruthFixtures(): GraphTruthCommitLike[] {
    return [
        commit('commit-reverted', 1, 'assert', [], null, ['receipt-reverted'], ['source-reverted']),
        commit('commit-old', 2, 'assert', [], null, ['receipt-old'], ['source-old']),
        commit('commit-active', 3, 'supersede', ['commit-old'], null, ['receipt-active'], ['source-active']),
        commit('commit-reverter', 4, 'revert', [], 'commit-reverted', ['receipt-reverter'], ['source-reverter'], false),
    ];
}

function commit(
    commitId: string,
    generation: number,
    operation: GraphTruthCommitLike['operation'],
    predecessorCommitIds: string[],
    reversesCommitId: string | null,
    receiptIds: string[],
    sourceIds: string[],
    withBatch = true,
): GraphTruthCommitLike {
    return {
        commitId,
        generation,
        operation,
        predecessorCommitIds,
        reversesCommitId,
        receiptIds,
        sourceGenerations: sourceIds.map((sourceId) => ({ sourceId, generation })),
        committedAt: generation * 10,
        batch: withBatch ? {
            vertices: [{ id: `vertex:${commitId}` }],
            edges: [{ sourceId: `vertex:${commitId}`, targetId: 'entity:kai', edgeType: 'supports' }],
        } : { vertices: [], edges: [] },
    };
}
