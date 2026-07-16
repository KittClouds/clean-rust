import { NATIVE_OPERATOR_AUTHORITY_ID } from './graph-native-decision-capture';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA =
    'phoenix-canonical-episode-assignment-commit/v1' as const;

export type CanonicalEpisodeAssignmentSelection =
    | { kind: 'attach_to_episode'; episodeId: string }
    | { kind: 'create_episode' }
    | { kind: 'abstain' };

export interface CanonicalEpisodeAssignmentCommitRequest {
    schemaVersion: typeof CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA;
    scopeKey: string;
    sourceSnapshotId: string;
    sourceSnapshotBuiltAt: number;
    sourceAuthorityContentHash: string;
    event: {
        id: string;
        noteId: string;
        chunkId: string;
        sourceStart: number;
        sourceEnd: number;
        predicate: string;
        participantEntityIds: string[];
        evidenceIds: string[];
        factuality: string;
        confidenceMillis: number;
        noTopologyCommit: true;
    };
    episodes: Array<{
        id: string;
        noteId: string;
        label: string;
        sourceStart: number;
        sourceEnd: number;
        chunkIds: string[];
        eventIds: string[];
        entityIds: string[];
        boundaryReceiptIds: string[];
        confidenceMillis: number;
        status: string;
        noTopologyCommit: true;
    }>;
    selectedAction: CanonicalEpisodeAssignmentSelection;
    decidedAt: number;
    operatorId: string;
}

export interface CanonicalEpisodeAssignmentCommitResponse {
    schemaVersion: typeof CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA;
    decisionId: string;
    decisionReceiptId: string;
    candidateSetId: string;
    chosenActionIdentity: string;
    chosenActionKind: CanonicalEpisodeAssignmentSelection['kind'];
    candidateCount: number;
    outcomeReceiptId: string;
    operatorMutationReceiptId: string;
    graphTruthCommitId: string | null;
    graphTruthGeneration: number | null;
    commitStatus: 'appended' | 'already_present' | 'already_canonical' | 'no_change';
    decisionAppended: boolean;
    outcomeAppended: boolean;
}

export function canonicalEpisodeAssignmentCommitRequest(
    snapshot: GraphRebuildSnapshot,
    eventId: string,
    selectedAction: CanonicalEpisodeAssignmentSelection,
    decidedAt = Date.now(),
): CanonicalEpisodeAssignmentCommitRequest {
    const authority = snapshot.authorityContract;
    const continuity = snapshot.storyContinuity;
    if (!authority || authority.snapshotId !== snapshot.id || authority.scopeId !== snapshot.scopeId) {
        throw new Error('Canonical episode assignment requires exact snapshot authority.');
    }
    if (!continuity || continuity.sourceSnapshotId !== snapshot.id
        || continuity.commitPolicy !== 'candidate_only' || !continuity.noTopologyCommit) {
        throw new Error('Canonical episode assignment requires the candidate-only continuity contract.');
    }
    const event = continuity.events.find((candidate) => candidate.id === eventId);
    if (!event || !event.noTopologyCommit) {
        throw new Error(`Continuity event is unavailable for canonical assignment: ${eventId}`);
    }
    const compatible = continuity.episodes.filter((episode) =>
        episode.noteId === event.noteId
        && episode.status !== 'blocked'
        && episode.noTopologyCommit,
    );
    if (selectedAction.kind === 'attach_to_episode'
        && !compatible.some((episode) => episode.id === selectedAction.episodeId)) {
        throw new Error(`Canonical episode assignment selected an unavailable episode: ${selectedAction.episodeId}`);
    }
    return {
        schemaVersion: CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA,
        scopeKey: snapshot.scopeId,
        sourceSnapshotId: snapshot.id,
        sourceSnapshotBuiltAt: snapshot.builtAt,
        sourceAuthorityContentHash: authority.contentHash,
        event: {
            id: event.id,
            noteId: event.noteId,
            chunkId: event.chunkId,
            sourceStart: event.sourceStart,
            sourceEnd: event.sourceEnd,
            predicate: event.predicate,
            participantEntityIds: [...event.participantEntityIds],
            evidenceIds: [...event.evidenceIds],
            factuality: event.factuality,
            confidenceMillis: event.confidenceMillis,
            noTopologyCommit: true,
        },
        episodes: continuity.episodes.map((episode) => ({
            id: episode.id,
            noteId: episode.noteId,
            label: episode.label,
            sourceStart: episode.sourceStart,
            sourceEnd: episode.sourceEnd,
            chunkIds: [...episode.chunkIds],
            eventIds: [...episode.eventIds],
            entityIds: [...episode.entityIds],
            boundaryReceiptIds: [...episode.boundaryReceiptIds],
            confidenceMillis: episode.confidenceMillis,
            status: episode.status,
            noTopologyCommit: true,
        })),
        selectedAction,
        decidedAt,
        operatorId: NATIVE_OPERATOR_AUTHORITY_ID,
    };
}

export function isCanonicalEpisodeAssignmentCommitResponse(
    value: unknown,
): value is CanonicalEpisodeAssignmentCommitResponse {
    const row = value as Partial<CanonicalEpisodeAssignmentCommitResponse> | null;
    return !!row
        && row.schemaVersion === CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA
        && typeof row.decisionId === 'string'
        && typeof row.decisionReceiptId === 'string'
        && typeof row.candidateSetId === 'string'
        && typeof row.chosenActionIdentity === 'string'
        && (row.chosenActionKind === 'attach_to_episode'
            || row.chosenActionKind === 'create_episode'
            || row.chosenActionKind === 'abstain')
        && typeof row.candidateCount === 'number'
        && row.candidateCount >= 3
        && typeof row.outcomeReceiptId === 'string'
        && typeof row.operatorMutationReceiptId === 'string'
        && (typeof row.graphTruthCommitId === 'string' || row.graphTruthCommitId === null)
        && (typeof row.graphTruthGeneration === 'number' || row.graphTruthGeneration === null)
        && (row.commitStatus === 'appended'
            || row.commitStatus === 'already_present'
            || row.commitStatus === 'already_canonical'
            || row.commitStatus === 'no_change')
        && typeof row.decisionAppended === 'boolean'
        && typeof row.outcomeAppended === 'boolean';
}
