import '@angular/compiler';
import { describe, expect, it } from 'vitest';

import { buildAtlasNativeProofRows } from './atlas-control-rows';
import {
    canonicalEpisodeAssignmentCommitRequest,
    isCanonicalEpisodeAssignmentCommitResponse,
} from './graph-canonical-episode-assignment';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import type { GraphStoryContinuityContract } from './graph-story-continuity';

describe('canonical episode assignment producer', () => {
    it('freezes the exact event, full episode universe, and explicit operator choice', () => {
        const request = canonicalEpisodeAssignmentCommitRequest(
            snapshotFixture(),
            'event:1',
            { kind: 'attach_to_episode', episodeId: 'episode:1' },
            200,
        );

        expect(request).toMatchObject({
            schemaVersion: 'phoenix-canonical-episode-assignment-commit/v1',
            sourceSnapshotId: 'snapshot:episode:1',
            selectedAction: { kind: 'attach_to_episode', episodeId: 'episode:1' },
            decidedAt: 200,
            operatorId: 'operator:local-user',
        });
        expect(request.event.noTopologyCommit).toBe(true);
        expect(request.episodes.map((episode) => episode.id)).toEqual(['episode:1', 'episode:2']);
        expect(request.episodes.every((episode) => episode.noTopologyCommit)).toBe(true);
    });

    it('allows an explicit compatible override but rejects unavailable episodes', () => {
        expect(canonicalEpisodeAssignmentCommitRequest(
            snapshotFixture(), 'event:1', { kind: 'attach_to_episode', episodeId: 'episode:2' }, 200,
        ).selectedAction).toEqual({ kind: 'attach_to_episode', episodeId: 'episode:2' });
        expect(() => canonicalEpisodeAssignmentCommitRequest(
            snapshotFixture(), 'event:1', { kind: 'attach_to_episode', episodeId: 'missing' }, 200,
        )).toThrow(/selected an unavailable episode/);
    });

    it('surfaces the complete operator inbox without auto-selecting a choice', () => {
        const continuity = continuityFixture();
        const rows = buildAtlasNativeProofRows('snapshot:episode:1', {
            bridge: { candidates: [], crossDocumentCertificate: null },
            continuity: { contract: continuity },
            governance: { candidates: [] },
            promotion: { certificate: null },
        });
        const event = rows.find((row) => row.identity.rawId === 'event:1');
        expect(event?.allowedActions).toContain('commit_episode_assignment');
        expect(event?.episodeAssignmentOptions.map((option) => option.kind)).toEqual([
            'attach_to_episode', 'attach_to_episode', 'create_episode', 'abstain',
        ]);
        expect(event?.episodeAssignmentOptions.filter((option) => option.proposed)).toHaveLength(1);
        expect(event?.receiptPolicy).toEqual({
            required: true,
            kind: 'native_decision_receipt',
            reversible: true,
            topologyMutationAllowed: true,
        });

    });

    it('accepts only complete native authority responses', () => {
        expect(isCanonicalEpisodeAssignmentCommitResponse({
            schemaVersion: 'phoenix-canonical-episode-assignment-commit/v1',
            decisionId: 'decision:1',
            decisionReceiptId: 'b3-a',
            candidateSetId: 'b3-b',
            chosenActionIdentity: 'b3-c',
            chosenActionKind: 'attach_to_episode',
            candidateCount: 4,
            outcomeReceiptId: 'b3-d',
            operatorMutationReceiptId: 'b3-e',
            graphTruthCommitId: 'b3-f',
            graphTruthGeneration: 1,
            commitStatus: 'appended',
            decisionAppended: true,
            outcomeAppended: true,
        })).toBe(true);
        expect(isCanonicalEpisodeAssignmentCommitResponse({
            schemaVersion: 'phoenix-canonical-episode-assignment-commit/v1',
            candidateCount: 1,
        })).toBe(false);
    });
});

function snapshotFixture(): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot:episode:1',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note:1'],
        builtAt: 100,
        storyContinuity: continuityFixture(),
        authorityContract: {
            schemaVersion: 'phoenix-graph-snapshot-authority/v1',
            authority: 'graph_rebuild_live_contract',
            snapshotId: 'snapshot:episode:1',
            scopeId: 'global',
            contentHash: 'authority:episode:1',
            counts: {} as never,
        },
        counters: {} as never,
    } as GraphRebuildSnapshot;
}

function continuityFixture(): GraphStoryContinuityContract {
    return {
        schemaVersion: 'phoenix-story-continuity/v1',
        source: 'rust_story_continuity',
        sourceSnapshotId: 'snapshot:episode:1',
        generatedAt: 100,
        commitPolicy: 'candidate_only',
        noTopologyCommit: true,
        events: [{
            id: 'event:1', noteId: 'note:1', chunkId: 'chunk:1', sourceStart: 10,
            sourceEnd: 20, predicate: 'arrives', participantEntityIds: ['entity:1'],
            evidenceIds: ['evidence:event:1'], factuality: 'asserted', confidenceMillis: 900,
            status: 'candidate', noTopologyCommit: true,
        }],
        boundaryReceipts: [],
        episodes: [
            {
                id: 'episode:1', noteId: 'note:1', label: 'Arrival', sourceStart: 0,
                sourceEnd: 30, chunkIds: ['chunk:1'], eventIds: ['event:1'],
                entityIds: ['entity:1'], boundaryReceiptIds: ['boundary:1'],
                confidenceMillis: 850, status: 'candidate', noTopologyCommit: true,
            },
            {
                id: 'episode:2', noteId: 'note:1', label: 'Aftermath', sourceStart: 31,
                sourceEnd: 60, chunkIds: ['chunk:2'], eventIds: [], entityIds: ['entity:1'],
                boundaryReceiptIds: ['boundary:2'], confidenceMillis: 800,
                status: 'candidate', noTopologyCommit: true,
            },
        ],
        temporalCandidates: [], stateIntervals: [], causalCandidates: [],
        episodeConnections: [], conflicts: [],
        certificate: {
            schemaVersion: 'phoenix-story-continuity-run-certificate/v1',
            sourceSnapshotId: 'snapshot:episode:1', sourceDocumentIds: ['note:1'],
            buildMicros: 1, eventIdentityMicros: 1, episodeBoundaryMicros: 1,
            relationResolutionMicros: 1,
            counters: {
                events: 1, boundaryReceipts: 0, episodes: 2, temporalCandidates: 0,
                stateIntervals: 0, causalCandidates: 0, episodeConnections: 0,
                conflicts: 0, crossDocumentConnections: 0, reviewRequired: 0,
            },
            noTopologyWrites: true, allRowsEvidenced: true, stableSourceIdentities: true,
            fixedBatchingDetected: false, invariantReceipts: ['candidate_only'],
        },
    };
}
