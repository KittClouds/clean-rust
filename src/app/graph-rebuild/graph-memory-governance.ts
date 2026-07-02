import {
    GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
    GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
    type GraphMemoryGovernanceAction,
    type GraphMemoryGovernanceCandidate,
    type GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export function applyNativeMemoryGovernanceCandidates(
    snapshot: GraphRebuildSnapshot,
    candidates: GraphMemoryGovernanceCandidate[],
): void {
    const rows = assertMemoryGovernanceCandidateOnly(candidates);
    snapshot.memoryGovernanceCandidates = rows;
    snapshot.counters = {
        ...snapshot.counters,
        memoryGovernanceCandidates: rows.length,
        memoryGovernanceRetain: countAction(rows, 'retain'),
        memoryGovernanceAttenuate: countAction(rows, 'attenuate'),
        memoryGovernanceCompress: countAction(rows, 'compress'),
        memoryGovernanceQuarantine: countAction(rows, 'quarantine'),
        memoryGovernanceRetire: countAction(rows, 'retire'),
    };
}

export function assertMemoryGovernanceCandidateOnly(
    candidates: GraphMemoryGovernanceCandidate[],
): GraphMemoryGovernanceCandidate[] {
    for (const candidate of candidates) {
        if (candidate.schemaVersion !== GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION) {
            throw new Error(`Invalid memory governance schema: ${candidate.id}`);
        }
        if (candidate.status !== 'candidate') {
            throw new Error(`Invalid memory governance status: ${candidate.id}`);
        }
        if (candidate.commitPolicy !== GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY) {
            throw new Error(`Invalid memory governance commit policy: ${candidate.id}`);
        }
        if (candidate.noTopologyCommit !== true) {
            throw new Error(`Memory governance row may not mutate topology: ${candidate.id}`);
        }
        if (!candidate.rationale?.includes(GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)) {
            throw new Error(`Memory governance row is missing no-topology rationale: ${candidate.id}`);
        }
    }
    return [...candidates].sort((left, right) =>
        actionRank(left.action) - actionRank(right.action)
        || left.targetKind.localeCompare(right.targetKind)
        || left.targetId.localeCompare(right.targetId)
        || left.id.localeCompare(right.id));
}

function countAction(rows: GraphMemoryGovernanceCandidate[], action: GraphMemoryGovernanceAction): number {
    return rows.filter((row) => row.action === action).length;
}

function actionRank(action: GraphMemoryGovernanceAction): number {
    switch (action) {
        case 'retain':
            return 0;
        case 'compress':
            return 1;
        case 'attenuate':
            return 2;
        case 'quarantine':
            return 3;
        case 'retire':
            return 4;
    }
}
