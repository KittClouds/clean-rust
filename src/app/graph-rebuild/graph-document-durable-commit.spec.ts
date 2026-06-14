import { describe, expect, it } from 'vitest';

import {
    emptyGraphDocumentGraphMutationLedger,
    graphDocumentGraphMutationLedgerFor,
} from './graph-document-durable-commit';

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
});
