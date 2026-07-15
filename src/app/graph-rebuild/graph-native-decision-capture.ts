import type {
    GraphDocumentReviewActionKind,
    GraphDocumentReviewRow,
} from './graph-document-review';
import type {
    GraphOperatorMutationDecision,
    GraphOperatorMutationReceipt,
} from './graph-operator-mutation-journal';
import { fingerprintGraphDocumentReviewRow } from './graph-operator-mutation-journal';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA =
    'phoenix-native-operator-decision-begin/v1' as const;
export const NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA =
    'phoenix-native-operator-decision-complete/v1' as const;
export const NATIVE_OPERATOR_AUTHORITY_ID = 'operator:local-user' as const;
export const NATIVE_DECISION_TRUTH_LINK_SCHEMA = 'phoenix-native-decision-truth-link/v1' as const;
export const NATIVE_REWARD_OBSERVATION_SCHEMA = 'phoenix-native-reward-observation/v1' as const;

export type NativeOperatorReviewDecision =
    | 'accepted'
    | 'rejected'
    | 'deferred'
    | 'muted'
    | 'promoted_to_anchor'
    | 'compiled_to_graph'
    | 'ledger_only';

export interface NativeOperatorDecisionBeginRequest {
    schemaVersion: typeof NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA;
    scopeKey: string;
    sourceSnapshotId: string;
    sourceSnapshotBuiltAt: number;
    sourceAuthorityContentHash: string;
    targetObjectId: string;
    targetObjectKind: string;
    sourceFingerprint: string;
    sourceReceiptIds: string[];
    previousState: string;
    availableDecisions: NativeOperatorReviewDecision[];
    selectedDecision: NativeOperatorReviewDecision;
    decidedAt: number;
    operatorId: string;
}

export interface NativeOperatorDecisionBeginResponse {
    schemaVersion: typeof NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA;
    decisionId: string;
    decisionReceiptId: string;
    preStateSnapshotId: string;
    candidateSetId: string;
    chosenActionIdentity: string;
    candidateCount: number;
    appended: boolean;
}

export interface NativeOperatorDecisionCompleteRequest {
    schemaVersion: typeof NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA;
    decisionId: string;
    decisionReceiptId: string;
    postSnapshotId: string;
    postSnapshotBuiltAt: number;
    postAuthorityContentHash: string;
    operatorMutationReceiptId: string;
    completedAt: number;
    outcomeAuthorityId: string;
    applied: boolean;
}

export interface NativeOperatorDecisionCompleteResponse {
    schemaVersion: typeof NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA;
    decisionId: string;
    decisionReceiptId: string;
    outcomeReceiptId: string;
    postStateSnapshotId: string;
    rewardReady: boolean;
    appended: boolean;
}

export interface NativeDecisionCensus {
    schemaVersion: 'phoenix-native-decision-census/v1';
    behaviorLabels: number;
    canonicalEpisodeAssignmentLabels: number;
    canonicalEpisodeAttachLabels: number;
    canonicalEpisodeCreateLabels: number;
    canonicalEpisodeAbstainLabels: number;
    canonicalEpisodeFirstObservedAt: number | null;
    canonicalEpisodeLastObservedAt: number | null;
    canonicalEpisodeCandidateCountTotal: number;
    canonicalEpisodeCandidateCountMin: number;
    canonicalEpisodeCandidateCountMax: number;
    operatorPreferenceLabels: number;
    executionOutcomes: number;
    rewardCompleteOutcomes: number;
    rewardCensoredOutcomes: number;
    counterfactualReadyDecisions: number;
    graphTruthLinkedDecisions: number;
}

export interface NativeDecisionGraphTruthLinkRequest {
    schemaVersion: typeof NATIVE_DECISION_TRUTH_LINK_SCHEMA;
    decisionReceiptId: string;
    operatorMutationReceiptId: string;
    graphTruthCommitId: string;
    linkedAt: number;
    stabilityHorizonMs: number;
}

export interface NativeDecisionGraphTruthLink {
    schemaVersion: typeof NATIVE_DECISION_TRUTH_LINK_SCHEMA;
    linkId: string;
    decisionId: string;
    decisionReceiptId: string;
    chosenActionIdentity: string;
    operatorMutationReceiptId: string;
    graphTruthCommitId: string;
    committedAt: number;
    linkedAt: number;
    stabilityEligibleAt: number;
    rewardComplete: false;
}

export type NativeRewardObservationDimension = 'human_acceptance' | 'future_stability';
export type NativeRewardObservationOperation = 'observe' | 'revise' | 'retract';
export type NativeRewardObservationAuthority =
    | 'operator_preference'
    | 'authoritative_graph_outcome';

export interface NativeRewardObservationEvidence {
    evidenceId: string;
    authorityId: string;
    availableAt: number;
}

export interface NativeRewardObservationRequest {
    schemaVersion: typeof NATIVE_REWARD_OBSERVATION_SCHEMA;
    truthLink: NativeDecisionGraphTruthLinkRequest;
    truthLinkId: string;
    dimension: NativeRewardObservationDimension;
    operation: NativeRewardObservationOperation;
    scoreMicros: number | null;
    observedAt: number;
    authorityClass: NativeRewardObservationAuthority;
    authorityId: string;
    predecessorObservationReceiptId: string | null;
    evidenceAnchors: NativeRewardObservationEvidence[];
}

export interface NativeRewardObservationResponse {
    schemaVersion: typeof NATIVE_REWARD_OBSERVATION_SCHEMA;
    receiptId: string;
    decisionId: string;
    decisionReceiptId: string;
    candidateActionIdentity: string;
    truthLinkId: string;
    graphTruthCommitId: string;
    dimension: NativeRewardObservationDimension;
    operation: NativeRewardObservationOperation;
    scoreMicros: number | null;
    observedAt: number;
    appended: boolean;
    rewardComplete: false;
}

export interface NativeRewardObservationCensus {
    schemaVersion: 'phoenix-native-reward-observation-census/v1';
    observationReceipts: number;
    activeHumanAcceptance: number;
    activeFutureStability: number;
    positiveFutureStability: number;
    negativeFutureStability: number;
    matureCanonicalEpisodeAssignments: number;
    positiveCanonicalEpisodeStability: number;
    negativeCanonicalEpisodeStability: number;
    pendingCanonicalEpisodeHorizons: number;
    retractedDimensions: number;
    partiallyObservedDecisions: number;
    fullyObservedDecisions: number;
}

export function isNativeRewardObservationResponse(
    value: unknown,
): value is NativeRewardObservationResponse {
    const row = value as Partial<NativeRewardObservationResponse> | null;
    return !!row
        && row.schemaVersion === NATIVE_REWARD_OBSERVATION_SCHEMA
        && typeof row.receiptId === 'string'
        && typeof row.decisionId === 'string'
        && typeof row.decisionReceiptId === 'string'
        && typeof row.candidateActionIdentity === 'string'
        && typeof row.truthLinkId === 'string'
        && typeof row.graphTruthCommitId === 'string'
        && (row.dimension === 'human_acceptance' || row.dimension === 'future_stability')
        && (row.operation === 'observe' || row.operation === 'revise' || row.operation === 'retract')
        && (typeof row.scoreMicros === 'number' || row.scoreMicros === null)
        && typeof row.observedAt === 'number'
        && typeof row.appended === 'boolean'
        && row.rewardComplete === false;
}

export function isNativeOperatorDecisionBeginResponse(
    value: unknown,
): value is NativeOperatorDecisionBeginResponse {
    const row = value as Partial<NativeOperatorDecisionBeginResponse> | null;
    return !!row
        && row.schemaVersion === NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA
        && typeof row.decisionId === 'string'
        && typeof row.decisionReceiptId === 'string'
        && typeof row.preStateSnapshotId === 'string'
        && typeof row.candidateSetId === 'string'
        && typeof row.chosenActionIdentity === 'string'
        && typeof row.candidateCount === 'number'
        && typeof row.appended === 'boolean';
}

export function isNativeOperatorDecisionCompleteResponse(
    value: unknown,
): value is NativeOperatorDecisionCompleteResponse {
    const row = value as Partial<NativeOperatorDecisionCompleteResponse> | null;
    return !!row
        && row.schemaVersion === NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA
        && typeof row.decisionId === 'string'
        && typeof row.decisionReceiptId === 'string'
        && typeof row.outcomeReceiptId === 'string'
        && typeof row.postStateSnapshotId === 'string'
        && row.rewardReady === false
        && typeof row.appended === 'boolean';
}

export function nativeOperatorDecisionBeginRequest(
    snapshot: GraphRebuildSnapshot,
    row: GraphDocumentReviewRow,
    selected: GraphOperatorMutationDecision,
    decidedAt: number,
): NativeOperatorDecisionBeginRequest {
    const authority = snapshot.authorityContract;
    if (!authority || authority.snapshotId !== snapshot.id || authority.scopeId !== snapshot.scopeId) {
        throw new Error('Native operator decision requires an exact graph snapshot authority contract.');
    }
    const selectedDecision = nativeDecisionForMutation(selected);
    const availableDecisions = row.availableActions
        .map((action) => nativeDecisionForAction(action.kind))
        .filter((value): value is NativeOperatorReviewDecision => value !== null)
        .filter((value, index, values) => values.indexOf(value) === index);
    if (!availableDecisions.includes(selectedDecision)) {
        throw new Error(`Selected operator action is absent from the decision-time candidate set: ${selected}`);
    }
    return {
        schemaVersion: NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA,
        scopeKey: snapshot.scopeId,
        sourceSnapshotId: snapshot.id,
        sourceSnapshotBuiltAt: snapshot.builtAt,
        sourceAuthorityContentHash: authority.contentHash,
        targetObjectId: row.objectId,
        targetObjectKind: row.objectKind,
        sourceFingerprint: fingerprintGraphDocumentReviewRow(row),
        sourceReceiptIds: [...row.receiptIds],
        previousState: row.state,
        availableDecisions,
        selectedDecision,
        decidedAt,
        operatorId: NATIVE_OPERATOR_AUTHORITY_ID,
    };
}

export function bindNativeDecisionToOperatorMutation(
    snapshot: GraphRebuildSnapshot,
    targetObjectId: string,
    decidedAt: number,
    decision: NativeOperatorDecisionBeginResponse,
): GraphOperatorMutationReceipt {
    const journal = snapshot.operatorMutationJournal;
    if (!journal) throw new Error('Operator mutation journal missing after decision application.');
    const intent = journal.intents.find((candidate) =>
        candidate.targetObjectId === targetObjectId && candidate.createdAt === decidedAt,
    );
    if (!intent) throw new Error('Applied operator intent is missing from the durable journal.');
    const receipt = journal.receipts.find((candidate) => candidate.intentId === intent.id);
    if (!receipt) throw new Error('Applied operator receipt is missing from the durable journal.');
    intent.nativeDecisionId = decision.decisionId;
    intent.nativeDecisionReceiptId = decision.decisionReceiptId;
    receipt.nativeDecisionId = decision.decisionId;
    receipt.nativeDecisionReceiptId = decision.decisionReceiptId;
    return receipt;
}

export function nativeOperatorDecisionCompleteRequest(
    snapshot: GraphRebuildSnapshot,
    receipt: GraphOperatorMutationReceipt,
): NativeOperatorDecisionCompleteRequest {
    const authority = snapshot.authorityContract;
    if (!authority || !receipt.nativeDecisionId || !receipt.nativeDecisionReceiptId) {
        throw new Error('Native operator outcome requires bound decision and snapshot authority receipts.');
    }
    return {
        schemaVersion: NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA,
        decisionId: receipt.nativeDecisionId,
        decisionReceiptId: receipt.nativeDecisionReceiptId,
        postSnapshotId: snapshot.id,
        postSnapshotBuiltAt: snapshot.builtAt,
        postAuthorityContentHash: authority.contentHash,
        operatorMutationReceiptId: receipt.id,
        completedAt: receipt.createdAt,
        outcomeAuthorityId: NATIVE_OPERATOR_AUTHORITY_ID,
        applied: true,
    };
}

export function pendingNativeOperatorDecisionCompletions(
    snapshot: GraphRebuildSnapshot,
): NativeOperatorDecisionCompleteRequest[] {
    return (snapshot.operatorMutationJournal?.receipts || [])
        .filter((receipt) => receipt.nativeDecisionId && receipt.nativeDecisionReceiptId)
        .map((receipt) => nativeOperatorDecisionCompleteRequest(snapshot, receipt));
}

function nativeDecisionForMutation(
    decision: GraphOperatorMutationDecision,
): NativeOperatorReviewDecision {
    return decision;
}

function nativeDecisionForAction(
    action: GraphDocumentReviewActionKind,
): NativeOperatorReviewDecision | null {
    if (action === 'accept_fact' || action === 'merge_duplicate_units') return 'accepted';
    if (action === 'reject_fact') return 'rejected';
    if (action === 'promote_sidecar_to_anchor') return 'promoted_to_anchor';
    if (action === 'demote_graph_fact_to_sidecar') return 'ledger_only';
    if (action === 'mute_detector_pattern') return 'muted';
    if (action === 'compile_to_graph') return 'compiled_to_graph';
    return null;
}
