import {
    graphTruthCommitLedgerFor,
    normalizeGraphTruthCommits,
    type GraphTruthCommitLike,
} from './graph-truth-commit-ledger';

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
    authority?: 'graph_truth_commit_projection' | 'legacy_snapshot_read_model';
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

export function graphDocumentGraphMutationLedgerFromTruthCommits(
    commits: GraphTruthCommitLike[] | unknown,
): GraphDocumentGraphMutationLedger {
    const normalized = normalizeGraphTruthCommits(commits);
    const truthLedger = graphTruthCommitLedgerFor(normalized);
    const stateByCommitId = new Map(
        truthLedger.records
            .filter((record) => record.targetKind === 'commit')
            .map((record) => [record.commitId, record]),
    );
    const records = normalized
        .filter((commit) => commit.operation === 'assert' || commit.operation === 'supersede')
        .map((commit): GraphDocumentGraphMutationRecord => {
            const state = stateByCommitId.get(commit.commitId);
            const status = state?.state === 'committed' ? 'committed' : 'undone';
            const sourceObjectId = commit.sourceGenerations?.[0]?.sourceId || commit.commitId;
            const receiptId = commit.receiptIds?.[0] || commit.commitId;
            return {
                id: `document-graph-mutation:${commit.commitId}`,
                commitId: commit.commitId,
                topologyDiffId: receiptId,
                sourceObjectId,
                receiptId,
                status,
                vertexIds: state?.vertexIds || [],
                edgeKeys: state?.edgeKeys || [],
                committedAt: commit.committedAt,
                undoneAt: status === 'undone' ? state?.resolvedAt : undefined,
            };
        });
    return {
        ...graphDocumentGraphMutationLedgerFor(records),
        authority: 'graph_truth_commit_projection',
    };
}
