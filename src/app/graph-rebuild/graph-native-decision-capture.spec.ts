import { describe, expect, it } from 'vitest';

import type { GraphDocumentReviewRow } from './graph-document-review';
import {
    bindNativeDecisionToOperatorMutation,
    isNativeRewardObservationResponse,
    nativeOperatorDecisionBeginRequest,
    nativeOperatorDecisionCompleteRequest,
    pendingNativeOperatorDecisionCompletions,
    type NativeOperatorDecisionBeginResponse,
} from './graph-native-decision-capture';
import { fingerprintGraphDocumentReviewRow } from './graph-operator-mutation-journal';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('native operator decision capture', () => {
    it('freezes pre-choice alternatives and binds the durable operator effect', () => {
        const row = reviewRow();
        const snapshot = snapshotFixture(row);
        const request = nativeOperatorDecisionBeginRequest(snapshot, row, 'accepted', 200);
        expect(request.availableDecisions).toEqual(['accepted', 'rejected', 'ledger_only']);
        expect(request.selectedDecision).toBe('accepted');
        expect(request.sourceFingerprint).toBe(fingerprintGraphDocumentReviewRow(row));

        const begin: NativeOperatorDecisionBeginResponse = {
            schemaVersion: 'phoenix-native-operator-decision-begin/v1',
            decisionId: 'operator:decision-1',
            decisionReceiptId: 'b3-decision-receipt',
            preStateSnapshotId: 'b3-prestate',
            candidateSetId: 'b3-candidates',
            chosenActionIdentity: 'b3-action',
            candidateCount: 4,
            appended: true,
        };
        const receipt = bindNativeDecisionToOperatorMutation(
            snapshot,
            row.objectId,
            200,
            begin,
        );
        expect(receipt.nativeDecisionReceiptId).toBe(begin.decisionReceiptId);
        const completion = nativeOperatorDecisionCompleteRequest(snapshot, receipt);
        expect(completion).toMatchObject({
            decisionId: begin.decisionId,
            decisionReceiptId: begin.decisionReceiptId,
            operatorMutationReceiptId: receipt.id,
            completedAt: 200,
            applied: true,
        });
        expect(pendingNativeOperatorDecisionCompletions(snapshot)).toEqual([completion]);
    });

    it('fails before capture when authority or selected-candidate coverage is absent', () => {
        const row = reviewRow();
        const snapshot = snapshotFixture(row);
        snapshot.authorityContract = undefined;
        expect(() => nativeOperatorDecisionBeginRequest(snapshot, row, 'accepted', 200))
            .toThrow(/authority contract/i);

        const authorized = snapshotFixture(row);
        row.availableActions = row.availableActions.filter((action) => action.kind !== 'accept_fact');
        expect(() => nativeOperatorDecisionBeginRequest(authorized, row, 'accepted', 200))
            .toThrow(/candidate set/i);
    });

    it('accepts only dimension-scoped reward responses that remain incomplete', () => {
        expect(isNativeRewardObservationResponse({
            schemaVersion: 'phoenix-native-reward-observation/v1',
            receiptId: 'b3-observation',
            decisionId: 'decision-1',
            decisionReceiptId: 'b3-decision',
            candidateActionIdentity: 'b3-action',
            truthLinkId: 'b3-link',
            graphTruthCommitId: 'commit-1',
            dimension: 'human_acceptance',
            operation: 'observe',
            scoreMicros: 1_000_000,
            observedAt: 300,
            appended: true,
            rewardComplete: false,
        })).toBe(true);
        expect(isNativeRewardObservationResponse({
            schemaVersion: 'phoenix-native-reward-observation/v1',
            rewardComplete: true,
        })).toBe(false);
    });
});

function reviewRow(): GraphDocumentReviewRow {
    return {
        id: 'review-row:fact-1',
        objectId: 'fact-1',
        objectKind: 'graph_fact_candidate',
        state: 'proposed',
        title: 'Iris lives in Arcadia',
        subtitle: 'relation candidate',
        detail: 'source-backed fact',
        noteId: 'note-1',
        sourceStart: 10,
        sourceEnd: 31,
        confidence: 0.9,
        detector: 'graph-fact-compiler',
        parentUnitIds: [],
        childUnitIds: [],
        evidenceSpanIds: ['span-1'],
        relatedObjectIds: [],
        why: ['source evidence'],
        availableActions: [
            action('accept_fact', 'accepted'),
            action('reject_fact', 'rejected'),
            action('demote_graph_fact_to_sidecar', 'ledger_only'),
            action('jump_to_source_span'),
        ],
        receiptIds: ['source-receipt-1'],
    };
}

function action(
    kind: GraphDocumentReviewRow['availableActions'][number]['kind'],
    nextState?: GraphDocumentReviewRow['state'],
): GraphDocumentReviewRow['availableActions'][number] {
    return {
        id: `action:${kind}`,
        kind,
        label: kind,
        targetObjectId: 'fact-1',
        destructive: false,
        requiresUserIntent: true,
        nextState,
    };
}

function snapshotFixture(row: GraphDocumentReviewRow): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot-1',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        builtAt: 100,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
        documentReviewSummary: {
            schemaVersion: 'phoenix-document-review/v1',
            builtAt: 100,
            statePolicy: 'machine_objects_are_explicitly_review_stateful',
            topologyPolicy: 'review_actions_emit_receipts_before_graph_mutation',
            rows: [row],
            states: [],
            receipts: [],
            counters: {} as never,
        },
        operatorMutationJournal: {
            schemaVersion: 'phoenix-graph-operator-mutation-journal/v1',
            scopeId: 'global',
            updatedAt: 200,
            intents: [{
                schemaVersion: 'phoenix-graph-operator-mutation-intent/v1',
                id: 'intent-1',
                scopeId: 'global',
                sourceSnapshotId: 'snapshot-1',
                sourceSnapshotBuiltAt: 100,
                targetObjectId: 'fact-1',
                targetObjectKind: 'graph_fact_candidate',
                actionKind: 'accept_fact',
                previousState: 'proposed',
                requestedState: 'accepted',
                sourceFingerprint: fingerprintGraphDocumentReviewRow(row),
                sourceReceiptIds: ['source-receipt-1'],
                status: 'applied',
                createdAt: 200,
                appliedAt: 200,
            }],
            receipts: [{
                id: 'operator-receipt-1',
                intentId: 'intent-1',
                actionKind: 'accept_fact',
                targetObjectId: 'fact-1',
                targetObjectKind: 'graph_fact_candidate',
                previousState: 'proposed',
                nextState: 'accepted',
                reversible: true,
                mutationAllowed: false,
                invariant: 'operator_mutation_journal_replays_review_state_before_topology_commit',
                sourceFingerprint: fingerprintGraphDocumentReviewRow(row),
                detail: 'accepted',
                createdAt: 200,
            }],
            counters: {} as never,
        },
        authorityContract: {
            schemaVersion: 'phoenix-graph-snapshot-authority/v1',
            authority: 'graph_rebuild_live_contract',
            snapshotId: 'snapshot-1',
            scopeId: 'global',
            contentHash: 'fnv64-authority',
            counts: {} as never,
        },
        counters: {} as never,
    };
}
