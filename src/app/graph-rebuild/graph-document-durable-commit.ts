export interface GraphDocumentGraphMutationRecord {
    id: string;
    commitId: string;
    topologyDiffId: string;
    sourceObjectId: string;
    receiptId: string;
    status: 'committed' | 'undone';
    vertexIds: string[];
    edgeKeys: string[];
    committedAt: number;
    undoneAt?: number;
}

export interface GraphDocumentGraphMutationLedger {
    schemaVersion: 'phoenix-document-graph-mutation-ledger/v1';
    records: GraphDocumentGraphMutationRecord[];
    counters: {
        commits: number;
        active: number;
        undone: number;
        vertices: number;
        edges: number;
    };
}

export function emptyGraphDocumentGraphMutationLedger(): GraphDocumentGraphMutationLedger {
    return graphDocumentGraphMutationLedgerFor([]);
}

export function graphDocumentGraphMutationLedgerFor(
    records: GraphDocumentGraphMutationRecord[],
): GraphDocumentGraphMutationLedger {
    const active = records.filter((record) => record.status === 'committed');
    return {
        schemaVersion: 'phoenix-document-graph-mutation-ledger/v1',
        records,
        counters: {
            commits: records.length,
            active: active.length,
            undone: records.length - active.length,
            vertices: active.reduce((sum, record) => sum + record.vertexIds.length, 0),
            edges: active.reduce((sum, record) => sum + record.edgeKeys.length, 0),
        },
    };
}
