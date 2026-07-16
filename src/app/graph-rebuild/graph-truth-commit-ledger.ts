export const GRAPH_TRUTH_COMMIT_LEDGER_SCHEMA_VERSION = 'phoenix-graph-truth-commit-ledger/v1';

export type GraphTruthOperation = 'assert' | 'supersede' | 'retract' | 'revert';
export type GraphTruthUiState = 'accepted' | 'committed' | 'reverted' | 'superseded';

export interface GraphTruthCommitLike {
    schemaVersion?: number;
    commitId: string;
    generation: number;
    operation: GraphTruthOperation;
    sourceGenerations?: Array<{ sourceId: string; generation: number }>;
    receiptIds?: string[];
    predecessorCommitIds?: string[];
    reversesCommitId?: string | null;
    committedAt: number;
    batch?: {
        vertices?: Array<{ id?: unknown }>;
        edges?: Array<{ sourceId?: unknown; targetId?: unknown; edgeType?: unknown }>;
    };
}

export interface GraphTruthCommitLedgerRecord {
    id: string;
    targetKind: 'commit' | 'receipt' | 'source';
    targetId: string;
    commitId: string;
    operation: GraphTruthOperation;
    state: GraphTruthUiState;
    generation: number;
    committedAt: number;
    resolvedAt?: number;
    resolvedByCommitId?: string;
    vertexIds: string[];
    edgeKeys: string[];
}

export interface GraphTruthCommitLedger {
    schemaVersion: typeof GRAPH_TRUTH_COMMIT_LEDGER_SCHEMA_VERSION;
    authority: 'graph_truth_commit';
    records: GraphTruthCommitLedgerRecord[];
    counters: {
        commits: number;
        accepted: number;
        committed: number;
        reverted: number;
        superseded: number;
        vertices: number;
        edges: number;
    };
}

interface CommitResolution {
    state: Exclude<GraphTruthUiState, 'accepted'>;
    resolvedAt?: number;
    resolvedByCommitId?: string;
}

export function graphTruthCommitLedgerFor(commits: GraphTruthCommitLike[]): GraphTruthCommitLedger {
    const sorted = normalizeGraphTruthCommits(commits);
    const resolutionByCommitId = new Map<string, CommitResolution>();

    for (const commit of sorted) {
        if (!resolutionByCommitId.has(commit.commitId)) {
            resolutionByCommitId.set(commit.commitId, { state: 'committed' });
        }
        if (commit.operation === 'supersede') {
            for (const predecessorId of commit.predecessorCommitIds || []) {
                resolutionByCommitId.set(predecessorId, {
                    state: 'superseded',
                    resolvedAt: commit.committedAt,
                    resolvedByCommitId: commit.commitId,
                });
            }
        } else if (commit.operation === 'retract') {
            for (const predecessorId of commit.predecessorCommitIds || []) {
                resolutionByCommitId.set(predecessorId, {
                    state: 'reverted',
                    resolvedAt: commit.committedAt,
                    resolvedByCommitId: commit.commitId,
                });
            }
        } else if (commit.operation === 'revert' && commit.reversesCommitId) {
            resolutionByCommitId.set(commit.reversesCommitId, {
                state: 'reverted',
                resolvedAt: commit.committedAt,
                resolvedByCommitId: commit.commitId,
            });
        }
    }

    const records: GraphTruthCommitLedgerRecord[] = [];
    for (const commit of sorted) {
        const resolution = resolutionByCommitId.get(commit.commitId) || { state: 'committed' };
        const vertexIds = vertexIdsForCommit(commit);
        const edgeKeys = edgeKeysForCommit(commit);
        records.push(recordFor(commit, 'commit', commit.commitId, resolution.state, vertexIds, edgeKeys, resolution));
        for (const receiptId of commit.receiptIds || []) {
            records.push(recordFor(commit, 'receipt', receiptId, receiptStateForCommit(commit, resolution), vertexIds, edgeKeys, resolution));
        }
        for (const source of commit.sourceGenerations || []) {
            records.push(recordFor(commit, 'source', source.sourceId, sourceStateForCommit(commit, resolution), vertexIds, edgeKeys, resolution));
        }
    }

    return {
        schemaVersion: GRAPH_TRUTH_COMMIT_LEDGER_SCHEMA_VERSION,
        authority: 'graph_truth_commit',
        records,
        counters: {
            commits: sorted.length,
            accepted: records.filter((row) => row.state === 'accepted').length,
            committed: records.filter((row) => row.state === 'committed').length,
            reverted: records.filter((row) => row.state === 'reverted').length,
            superseded: records.filter((row) => row.state === 'superseded').length,
            vertices: unique(records.flatMap((row) => row.state === 'accepted' || row.state === 'committed' ? row.vertexIds : [])).length,
            edges: unique(records.flatMap((row) => row.state === 'accepted' || row.state === 'committed' ? row.edgeKeys : [])).length,
        },
    };
}

export function resolveGraphTruthUiState(
    ledger: GraphTruthCommitLedger | null | undefined,
    targetId: string,
): GraphTruthUiState | undefined {
    return ledger?.records.find((record) => record.targetId === targetId)?.state;
}

export function normalizeGraphTruthCommits(values: unknown): GraphTruthCommitLike[] {
    const raw = Array.isArray(values)
        ? values
        : Array.isArray((values as { commits?: unknown[] } | null)?.commits)
          ? (values as { commits: unknown[] }).commits
          : [];
    return raw
        .filter(isGraphTruthCommitLike)
        .sort((left, right) => left.generation - right.generation || left.commitId.localeCompare(right.commitId));
}

export function isGraphTruthCommitLike(value: unknown): value is GraphTruthCommitLike {
    const record = value && typeof value === 'object' ? value as Partial<GraphTruthCommitLike> : null;
    return !!record
        && typeof record.commitId === 'string'
        && Number.isFinite(record.generation)
        && isGraphTruthOperation(record.operation)
        && Number.isFinite(record.committedAt);
}

function isGraphTruthOperation(value: unknown): value is GraphTruthOperation {
    return value === 'assert' || value === 'supersede' || value === 'retract' || value === 'revert';
}

function recordFor(
    commit: GraphTruthCommitLike,
    targetKind: GraphTruthCommitLedgerRecord['targetKind'],
    targetId: string,
    state: GraphTruthUiState,
    vertexIds: string[],
    edgeKeys: string[],
    resolution: CommitResolution,
): GraphTruthCommitLedgerRecord {
    return {
        id: `graph-truth-ledger:${targetKind}:${targetId}`,
        targetKind,
        targetId,
        commitId: commit.commitId,
        operation: commit.operation,
        state,
        generation: commit.generation,
        committedAt: commit.committedAt,
        resolvedAt: resolution.resolvedAt,
        resolvedByCommitId: resolution.resolvedByCommitId,
        vertexIds,
        edgeKeys,
    };
}

function receiptStateForCommit(commit: GraphTruthCommitLike, resolution: CommitResolution): GraphTruthUiState {
    if (resolution.state !== 'committed') return resolution.state;
    return commit.operation === 'assert' || commit.operation === 'supersede' ? 'accepted' : 'committed';
}

function sourceStateForCommit(commit: GraphTruthCommitLike, resolution: CommitResolution): GraphTruthUiState {
    return receiptStateForCommit(commit, resolution);
}

function vertexIdsForCommit(commit: GraphTruthCommitLike): string[] {
    return unique((commit.batch?.vertices || []).map((vertex) => idText(vertex.id)).filter(Boolean));
}

function edgeKeysForCommit(commit: GraphTruthCommitLike): string[] {
    return unique((commit.batch?.edges || [])
        .map((edge) => [idText(edge.sourceId), idText(edge.targetId), idText(edge.edgeType)].filter(Boolean).join('\u0000'))
        .filter(Boolean));
}

function idText(value: unknown): string {
    if (typeof value === 'string') return value;
    if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>;
        if (typeof record['id'] === 'string') return record['id'];
        if (typeof record['value'] === 'string') return record['value'];
        if (typeof record['0'] === 'string') return record['0'];
    }
    return '';
}

function unique(values: string[]): string[] {
    return [...new Set(values)];
}
