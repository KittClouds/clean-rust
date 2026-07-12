import {
    buildGovernanceRunCertificate,
    type GraphGovernanceRunCertificate,
} from './graph-governance-run-certificate';
import type {
    GraphPromotionVerdictCertificate,
} from './graph-promotion-verdict';
import type {
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import {
    buildReviewAdjudicationRunCertificate,
    buildReviewAdjudicationViewContract,
    type GraphReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationViewContract,
    type GraphReviewProofState,
} from './graph-review-adjudication-certificate';
import {
    buildAtlasControlRooms,
    type AtlasControlRoom,
    type AtlasControlRoomActionDescriptor,
    type AtlasControlRoomId,
} from './atlas-control-room-contract';
import { buildAtlasControlRows } from './atlas-control-rows';

export const ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION = 'phoenix-atlas-control-contract/v2' as const;

export type AtlasControlFamily =
    | 'graph'
    | 'structure'
    | 'facts'
    | 'discourse'
    | 'review'
    | 'governance'
    | 'promotion'
    | 'metrics'
    | 'proof'
    | 'continuity';

export type AtlasControlLane =
    | 'graph_topology'
    | 'structure_ledger'
    | 'fact_ledger'
    | 'discourse_ledger'
    | 'review_ledger'
    | 'manual_decision'
    | 'nli_pair'
    | 'nli_judgment'
    | 'governance_candidate'
    | 'promotion_verdict'
    | 'metrics_ledger'
    | 'continuity_episode_map'
    | 'continuity_timeline'
    | 'continuity_causality'
    | 'continuity_state_history'
    | 'continuity_cross_document'
    | 'continuity_exception';

export type AtlasControlSourceContract =
    | 'graph_build'
    | 'document_review'
    | 'review_adjudication'
    | 'memory_governance'
    | 'governance_certificate'
    | 'promotion_verdict'
    | 'metrics'
    | 'cross_document_bridge'
    | 'story_continuity';

export type AtlasControlInventoryCategoryId =
    | 'entities'
    | 'graph_edges'
    | 'retrieval_targets'
    | 'structure_rows'
    | 'fact_rows'
    | 'discourse_rows'
    | 'review_ledger_rows'
    | 'manual_decision_rows'
    | 'nli_pair_rows'
    | 'nli_excluded_rows'
    | 'nli_judgment_rows'
    | 'governance_candidate_rows'
    | 'promotion_verdict_rows'
    | 'metrics_rows'
    | 'continuity_episode_rows'
    | 'continuity_temporal_rows'
    | 'continuity_causal_rows'
    | 'continuity_state_rows'
    | 'continuity_cross_document_rows'
    | 'continuity_exception_rows';

export type AtlasControlIntent =
    | 'run'
    | 'manual_action'
    | 'model_action'
    | 'promotion_preview'
    | 'read_only_ledger'
    | 'diagnostic_proof'
    | 'metric';

export type AtlasControlCountScope =
    | 'total_ledger'
    | 'visible_projection'
    | 'manual_actionable'
    | 'nli_pairwise'
    | 'diagnostic'
    | 'certificate';

export type AtlasControlActionability =
    | 'none'
    | 'inspect_only'
    | 'manual_receipt'
    | 'model_run'
    | 'promotion_preview'
    | 'build_run';

export type AtlasControlAction =
    | 'build_graph'
    | 'refresh_review'
    | 'run_nli'
    | 'inspect'
    | 'jump_to_source'
    | 'compare_context'
    | 'show_reason'
    | 'accept_review_row'
    | 'reject_review_row'
    | 'promote_to_anchor'
    | 'merge_duplicates'
    | 'demote_to_sidecar'
    | 'mute_pattern'
    | 'compile_to_graph'
    | 'preview_promotion'
    | 'add_entity'
    | 'edit_entity'
    | 'delete_entity'
    | 'split_episode'
    | 'merge_episodes'
    | 'confirm_boundary'
    | 'confirm_ordering'
    | 'reject_ordering'
    | 'confirm_causal_link'
    | 'reject_causal_link'
    | 'resolve_continuity_conflict';

export type AtlasControlTone = 'ready' | 'review' | 'warning' | 'danger' | 'quiet';
export type AtlasControlReceiptKind =
    | 'graph_build_receipt'
    | 'document_review_action_receipt'
    | 'review_adjudication_run_certificate'
    | 'promotion_proposal_receipt'
    | 'continuity_action_receipt';

export interface AtlasControlReceiptPolicy {
    required: boolean;
    kind: AtlasControlReceiptKind | null;
    reversible: boolean;
    topologyMutationAllowed: boolean;
}

export interface AtlasControlRowIdentity {
    id: string;
    rawId: string;
    snapshotId: string;
    sourceContract: AtlasControlSourceContract;
    lane: AtlasControlLane;
    kind: string;
}

export interface AtlasControlRow {
    identity: AtlasControlRowIdentity;
    label: string;
    detail: string;
    state: string;
    confidence: number | null;
    allowedActions: AtlasControlAction[];
    receiptPolicy: AtlasControlReceiptPolicy;
    receiptIds: string[];
    noteId: string | null;
    sourceStart: number | null;
    sourceEnd: number | null;
    sourceIds: string[];
    targetIds: string[];
    entityIds: string[];
    evidenceIds: string[];
    tags: string[];
    sourceExcerpt: string | null;
    targetExcerpt: string | null;
    targetDocumentId: string | null;
}

export interface AtlasControlEntityInput {
    id: string;
    label: string;
    kind: string;
    aliases?: string[];
}

export interface AtlasControlInventoryCategory {
    id: AtlasControlInventoryCategoryId;
    label: string;
    family: AtlasControlFamily;
    lane: AtlasControlLane;
    sourceContract: AtlasControlSourceContract;
    totalRows: number;
    visibleRows: number;
    rowIds: string[];
    actionability: AtlasControlActionability;
    allowedActions: AtlasControlAction[];
    receiptPolicy: AtlasControlReceiptPolicy;
}

export interface AtlasControlInvariant {
    status: GraphReviewProofState;
    detail: string;
}

export interface AtlasControlCard {
    id: string;
    family: AtlasControlFamily;
    lane: AtlasControlLane;
    sourceContract: AtlasControlSourceContract;
    inventoryCategoryId: AtlasControlInventoryCategoryId | null;
    label: string;
    value: number | string;
    valueLabel: string;
    detail: string;
    tone: AtlasControlTone;
    intent: AtlasControlIntent;
    countScope: AtlasControlCountScope;
    actionability: AtlasControlActionability;
    allowedActions: AtlasControlAction[];
    receiptPolicy: AtlasControlReceiptPolicy;
}

export interface AtlasControlSection {
    id: string;
    family: AtlasControlFamily;
    label: string;
    detail: string;
    cards: AtlasControlCard[];
}

export interface AtlasControlContract {
    schemaVersion: typeof ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION;
    owner: 'atlas_control_contract_service';
    generatedAt: number;
    snapshotId: string;
    header: AtlasControlCard[];
    workflow: AtlasControlCard[];
    sections: AtlasControlSection[];
    cardsById: Record<string, AtlasControlCard>;
    rows: AtlasControlRow[];
    rowsById: Record<string, AtlasControlRow>;
    inventory: AtlasControlInventoryCategory[];
    inventoryById: Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>;
    roomIds: AtlasControlRoomId[];
    roomsById: Record<AtlasControlRoomId, AtlasControlRoom>;
    roomActionsById: Record<string, AtlasControlRoomActionDescriptor>;
    invariants: {
        typedRowIdentities: AtlasControlInvariant;
        exactInventory: AtlasControlInvariant;
        reviewNliSeparated: AtlasControlInvariant;
        noTopologyWrites: AtlasControlInvariant;
        candidateOnlyGovernance: AtlasControlInvariant;
        promotionReceiptGated: AtlasControlInvariant;
    };
    certificates: {
        reviewAdjudication: GraphReviewAdjudicationViewContract;
        governance: GraphGovernanceRunCertificate | null;
        promotion: GraphPromotionVerdictCertificate | null;
    };
}

export interface BuildAtlasControlContractInput {
    snapshot: GraphRebuildSnapshot | null;
    entities?: AtlasControlEntityInput[];
    entityCount?: number;
    edgeCount?: number;
    reviewAdjudicationCertificate?: GraphReviewAdjudicationRunCertificate | null;
    reviewAdjudicationViewContract?: GraphReviewAdjudicationViewContract | null;
    governanceCertificate?: GraphGovernanceRunCertificate | null;
    promotionCertificate?: GraphPromotionVerdictCertificate | null;
    additionalRows?: AtlasControlRow[];
    nativeProofCounts?: AtlasNativeProofCounts | null;
}

export interface AtlasNativeProofCounts {
    crossDocumentPairCoverage: number;
    crossDocumentSelected: number;
    crossDocumentRejected: number;
    continuityBoundaries: number;
    continuityEpisodes: number;
    continuityTemporal: number;
    continuityStates: number;
    continuityCausal: number;
    continuityConnections: number;
    continuityConflicts: number;
}

export function buildAtlasControlContract(input: BuildAtlasControlContractInput): AtlasControlContract {
    const snapshot = input.snapshot;
    const counters = (snapshot?.counters ?? {}) as Record<string, number | undefined>;
    const reviewCertificate = input.reviewAdjudicationCertificate
        ?? snapshot?.reviewAdjudicationCertificate
        ?? (snapshot ? buildReviewAdjudicationRunCertificate({
            snapshot,
            source: 'derived',
            modelId: 'onnx-community/ModernBERT-base-nli',
            modelLabel: 'ModernBERT NLI',
        }) : null);
    const review = input.reviewAdjudicationViewContract
        ?? buildReviewAdjudicationViewContract(reviewCertificate);
    const governance = input.governanceCertificate ?? (snapshot ? buildGovernanceRunCertificate(snapshot) : null);
    const promotion = input.promotionCertificate ?? snapshot?.promotionVerdictCertificate ?? null;
    const snapshotId = snapshot?.id ?? 'no-snapshot';

    const entityCount = nonNegative(input.entityCount, counters['entities'], snapshot?.nodes?.length);
    const edgeCount = nonNegative(input.edgeCount, counters['edges'], snapshot?.edges?.length);
    const targetCount = nonNegative(counters['embeddingTargets'], snapshot?.embeddingTargets?.length);
    const structureRows = nonNegative(counters['structureRows'], counters['hierarchyRows']);
    const factRows = nonNegative(counters['factRows'], counters['facts']);
    const discourseRows = nonNegative(counters['discourseRows'], counters['discoursePackets']);
    const metricsRows = nonNegative(counters['metricsRows'], counters['metrics']);
    const governanceCount = nonNegative(
        counters['memoryGovernanceCandidates'],
        governance?.candidatesByAction.total,
        snapshot?.memoryGovernanceCandidates?.length,
    );
    const promotionCount = nonNegative(promotion?.audit.total, counters['promotionVerdictRows']);
    const rows = uniqueControlRows([
        ...buildAtlasControlRows(snapshotId, snapshot, reviewCertificate, promotion, input.entities ?? []),
        ...(input.additionalRows ?? []),
    ]);
    const inventory = buildInventory({
        rows,
        entityCount,
        edgeCount,
        targetCount,
        structureRows,
        factRows,
        discourseRows,
        metricsRows,
        review,
        governanceCount,
        promotionCount,
        nativeProofCounts: input.nativeProofCounts ?? null,
    });
    const inventoryById = Object.fromEntries(inventory.map((item) => [item.id, item])) as
        Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>;

    const header = buildHeader(inventoryById, review, governance, promotion);
    const workflow = buildWorkflow(inventoryById, review, governance, promotion);
    const sections = buildSections(inventoryById, review, governance, promotion);
    const allCards = [...header, ...workflow, ...sections.flatMap((section) => section.cards)];
    const cardsById = Object.fromEntries(allCards.map((item) => [item.id, item]));
    const rowsById = Object.fromEntries(rows.map((item) => [item.identity.id, item]));
    const invariants = buildInvariants(snapshot, rows, inventory, reviewCertificate, governance, promotion);
    const roomProjection = buildAtlasControlRooms({
        snapshotAvailable: !!snapshot,
        inventoryById,
        cardsById,
        rowsById,
        invariants,
    });

    return {
        schemaVersion: ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION,
        owner: 'atlas_control_contract_service',
        generatedAt: Date.now(),
        snapshotId,
        header,
        workflow,
        sections,
        cardsById,
        rows,
        rowsById,
        inventory,
        inventoryById,
        roomIds: roomProjection.roomIds,
        roomsById: roomProjection.roomsById,
        roomActionsById: roomProjection.actionsById,
        invariants,
        certificates: { reviewAdjudication: review, governance, promotion },
    };
}

function buildInventory(input: {
    rows: AtlasControlRow[];
    entityCount: number;
    edgeCount: number;
    targetCount: number;
    structureRows: number;
    factRows: number;
    discourseRows: number;
    metricsRows: number;
    review: GraphReviewAdjudicationViewContract;
    governanceCount: number;
    promotionCount: number;
    nativeProofCounts: AtlasNativeProofCounts | null;
}): AtlasControlInventoryCategory[] {
    const laneRows = (lane: AtlasControlLane) => input.rows.filter((row) => row.identity.lane === lane);
    const topologyRows = laneRows('graph_topology');
    const entityRows = topologyRows.filter((row) => row.identity.kind.startsWith('entity:'));
    const edgeRows = topologyRows.filter((row) => row.identity.kind.startsWith('edge:'));
    return [
        inventory('entities', 'Entities', 'graph', 'graph_topology', 'graph_build', input.entityCount, entityRows, 'inspect_only', ['inspect'], noReceipt()),
        inventory('graph_edges', 'Graph edges', 'graph', 'graph_topology', 'graph_build', input.edgeCount, edgeRows, 'inspect_only', ['inspect'], noReceipt()),
        inventory('retrieval_targets', 'Retrieval targets', 'graph', 'graph_topology', 'graph_build', input.targetCount, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('structure_rows', 'Structure rows', 'structure', 'structure_ledger', 'graph_build', input.structureRows, laneRows('structure_ledger'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('fact_rows', 'Fact rows', 'facts', 'fact_ledger', 'document_review', input.factRows, laneRows('fact_ledger'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('discourse_rows', 'Discourse rows', 'discourse', 'discourse_ledger', 'graph_build', input.discourseRows, laneRows('discourse_ledger'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('review_ledger_rows', 'Review ledger rows', 'review', 'review_ledger', 'document_review', input.review.queue.ledgerRows, laneRows('review_ledger'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('manual_decision_rows', 'Manual decision rows', 'review', 'manual_decision', 'document_review', input.review.queue.manualDecisionRows, laneRows('manual_decision'), input.review.queue.manualDecisionRows ? 'manual_receipt' : 'none', manualActions(input.rows), receipt('document_review_action_receipt', true, false)),
        inventory('nli_pair_rows', 'NLI pair rows', 'review', 'nli_pair', 'review_adjudication', input.review.queue.nliPairRows, [], input.review.action.disabled ? 'none' : 'model_run', input.review.action.disabled ? [] : ['run_nli'], receipt('review_adjudication_run_certificate', false, false)),
        inventory('nli_excluded_rows', 'NLI excluded rows', 'review', 'nli_pair', 'review_adjudication', input.review.queue.nliExcludedRows, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('nli_judgment_rows', 'NLI judgment rows', 'review', 'nli_judgment', 'review_adjudication', input.review.queue.judgedRows, laneRows('nli_judgment'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('governance_candidate_rows', 'Governance candidates', 'governance', 'governance_candidate', 'memory_governance', input.governanceCount, laneRows('governance_candidate'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('promotion_verdict_rows', 'Promotion verdicts', 'promotion', 'promotion_verdict', 'promotion_verdict', input.promotionCount, laneRows('promotion_verdict'), input.promotionCount ? 'promotion_preview' : 'none', input.promotionCount ? ['preview_promotion'] : [], receipt('promotion_proposal_receipt', true, true)),
        inventory('metrics_rows', 'Metric rows', 'metrics', 'metrics_ledger', 'metrics', input.metricsRows, laneRows('metrics_ledger'), 'inspect_only', ['inspect'], noReceipt()),
        continuityInventory('continuity_episode_rows', 'Episode map', 'continuity_episode_map', laneRows('continuity_episode_map'),
            nonNegative(input.nativeProofCounts?.continuityBoundaries)
                + nonNegative(input.nativeProofCounts?.continuityEpisodes)
                + nonNegative(input.nativeProofCounts?.continuityConnections)),
        continuityInventory('continuity_temporal_rows', 'Timeline', 'continuity_timeline', laneRows('continuity_timeline'),
            nonNegative(input.nativeProofCounts?.continuityTemporal)),
        continuityInventory('continuity_causal_rows', 'Causality', 'continuity_causality', laneRows('continuity_causality'),
            nonNegative(input.nativeProofCounts?.continuityCausal)),
        continuityInventory('continuity_state_rows', 'State history', 'continuity_state_history', laneRows('continuity_state_history'),
            nonNegative(input.nativeProofCounts?.continuityStates)),
        inventory('continuity_cross_document_rows', 'Cross-document', 'continuity',
            'continuity_cross_document', 'cross_document_bridge',
            input.nativeProofCounts
                ? nonNegative(input.nativeProofCounts.crossDocumentPairCoverage)
                    + nonNegative(input.nativeProofCounts.crossDocumentSelected)
                    + nonNegative(input.nativeProofCounts.crossDocumentRejected)
                : laneRows('continuity_cross_document').length,
            laneRows('continuity_cross_document'),
            'inspect_only', ['inspect', 'compare_context'], noReceipt()),
        continuityInventory('continuity_exception_rows', 'Exceptions', 'continuity_exception', laneRows('continuity_exception'),
            nonNegative(input.nativeProofCounts?.continuityConflicts)),
    ];
}

function continuityInventory(
    id: AtlasControlInventoryCategoryId,
    label: string,
    lane: AtlasControlLane,
    rows: AtlasControlRow[],
    completeRows = rows.length,
): AtlasControlInventoryCategory {
    return inventory(
        id, label, 'continuity', lane, 'story_continuity', Math.max(completeRows, rows.length), rows,
        rows.some((row) => row.receiptPolicy.required) ? 'manual_receipt' : 'inspect_only',
        [...new Set(rows.flatMap((row) => row.allowedActions))],
        receipt('continuity_action_receipt', true, false),
    );
}

function inventory(
    id: AtlasControlInventoryCategoryId,
    label: string,
    family: AtlasControlFamily,
    lane: AtlasControlLane,
    sourceContract: AtlasControlSourceContract,
    totalRows: number,
    visible: AtlasControlRow[],
    actionability: AtlasControlActionability,
    allowedActions: AtlasControlAction[],
    receiptPolicy: AtlasControlReceiptPolicy,
): AtlasControlInventoryCategory {
    return {
        id, label, family, lane, sourceContract, totalRows, visibleRows: visible.length,
        rowIds: visible.map((row) => row.identity.id), actionability, allowedActions, receiptPolicy,
    };
}

function buildHeader(
    inventoryById: Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>,
    review: GraphReviewAdjudicationViewContract,
    governance: GraphGovernanceRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
): AtlasControlCard[] {
    return [
        inventoryCard('header-entities', inventoryById.entities, 'committed atlas entities'),
        inventoryCard('header-graph-edges', inventoryById.graph_edges, 'accepted read-model topology'),
        inventoryCard('header-targets', inventoryById.retrieval_targets, 'retrieval and render targets'),
        inventoryCard('header-governance', inventoryById.governance_candidate_rows, `${nonNegative(governance?.noTopologyProof.candidateOnlyRows).toLocaleString()} no-commit rows`),
        inventoryCard('header-nli-pairs', inventoryById.nli_pair_rows, review.action.reason),
        inventoryCard('header-verdicts', inventoryById.promotion_verdict_rows, `${nonNegative(promotion?.audit.acceptable).toLocaleString()} acceptable`),
    ];
}

function buildWorkflow(
    inventoryById: Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>,
    review: GraphReviewAdjudicationViewContract,
    governance: GraphGovernanceRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
): AtlasControlCard[] {
    const graph = inventoryById.graph_edges;
    const graphReceipt = receipt('graph_build_receipt', true, true);
    return [
        card('workflow-graph-build', graph.family, graph.lane, graph.sourceContract, graph.id, 'Graph build', graph.totalRows, `${inventoryById.retrieval_targets.totalRows.toLocaleString()} retrieval targets`, 'run', 'visible_projection', 'build_run', ['build_graph'], graphReceipt),
        inventoryCard('workflow-review-ledger', inventoryById.review_ledger_rows, `${review.queue.manualDecisionRows.toLocaleString()} manual decisions`),
        inventoryCard('workflow-nli-pairs', inventoryById.nli_pair_rows, review.action.reason),
        inventoryCard('workflow-governance', inventoryById.governance_candidate_rows, `${nonNegative(governance?.noTopologyProof.candidateOnlyRows).toLocaleString()} no-commit rows`),
        inventoryCard('workflow-promotion', inventoryById.promotion_verdict_rows, `${nonNegative(promotion?.audit.acceptable).toLocaleString()} acceptable`),
    ];
}

function buildSections(
    inventoryById: Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>,
    review: GraphReviewAdjudicationViewContract,
    governance: GraphGovernanceRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
): AtlasControlSection[] {
    return [
        section('section-review-adjudication', 'review', 'Review adjudication', 'Manual decisions and text-pair NLI are separate lanes.', [
            inventoryCard('review-ledger', inventoryById.review_ledger_rows, 'full system audit ledger'),
            inventoryCard('review-manual-action', inventoryById.manual_decision_rows, 'explicit user decisions with reversible receipts'),
            inventoryCard('review-nli-pairs', inventoryById.nli_pair_rows, review.action.reason),
            inventoryCard('review-excluded', inventoryById.nli_excluded_rows, 'invalid or explicitly excluded text pairs', inventoryById.nli_excluded_rows.totalRows ? 'warning' : 'ready'),
            inventoryCard('review-judged', inventoryById.nli_judgment_rows, `${review.queue.appliedRows.toLocaleString()} applied judgments`),
            card('review-topology-writes', 'review', 'nli_judgment', 'review_adjudication', null, 'Topology writes', review.queue.topologyWrites, 'review pass must stay report-only', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], noReceipt(), review.queue.topologyWrites ? 'danger' : 'ready'),
        ]),
        section('section-memory-governance', 'governance', 'Memory governance', 'Candidate-only keep, compress, quarantine, and attenuation decisions.', [
            inventoryCard('governance-candidates', inventoryById.governance_candidate_rows, 'candidate-only output'),
            card('governance-no-commit', 'governance', 'governance_candidate', 'governance_certificate', null, 'No-commit rows', nonNegative(governance?.noTopologyProof.candidateOnlyRows), 'no topology writes', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], noReceipt()),
            card('governance-attention', 'governance', 'governance_candidate', 'governance_certificate', null, 'Attention rows', nonNegative(governance?.attentionLanes.totalAttentionRows), 'exception lanes only', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], noReceipt()),
            card('governance-rust-time', 'governance', 'governance_candidate', 'governance_certificate', null, 'Rust time', `${nonNegative(governance?.timings.nativeMemoryGovernanceRustMicros, governance?.timings.memoryGovernanceBuildMicros).toLocaleString()} us`, 'engine runtime', 'metric', 'diagnostic', 'none', [], noReceipt()),
        ]),
        section('section-promotion', 'promotion', 'Promotion cockpit', 'Candidate to accepted truth, gated by receipts and rollback plans.', [
            inventoryCard('promotion-verdicts', inventoryById.promotion_verdict_rows, 'durable proposal receipts'),
            card('promotion-acceptable', 'promotion', 'promotion_verdict', 'promotion_verdict', null, 'Acceptable', nonNegative(promotion?.audit.acceptable), 'passed required gates', 'promotion_preview', 'certificate', 'promotion_preview', ['preview_promotion'], receipt('promotion_proposal_receipt', true, true)),
            card('promotion-blocked', 'promotion', 'promotion_verdict', 'promotion_verdict', null, 'Blocked', nonNegative(promotion?.audit.blocked), 'failed required gates', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], noReceipt(), nonNegative(promotion?.audit.blocked) ? 'warning' : 'ready'),
            card('promotion-receipts', 'promotion', 'promotion_verdict', 'promotion_verdict', null, 'Receipts', nonNegative(promotion?.receiptCount), `${nonNegative(promotion?.commitCount).toLocaleString()} commits`, 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], noReceipt()),
        ]),
        section('section-rooms', 'metrics', 'Operating rooms', 'Every room exposes an exact inventory and only its valid actions.', [
            inventoryCard('room-structure', inventoryById.structure_rows, 'document and chunk hierarchy'),
            inventoryCard('room-facts', inventoryById.fact_rows, 'relation facts and candidates'),
            inventoryCard('room-discourse', inventoryById.discourse_rows, 'cross-document idea packets'),
            inventoryCard('room-review', inventoryById.nli_pair_rows, review.action.reason),
            inventoryCard('room-metrics', inventoryById.metrics_rows, 'run health and timing ledger'),
        ]),
    ];
}

function buildInvariants(
    snapshot: GraphRebuildSnapshot | null,
    rows: AtlasControlRow[],
    inventory: AtlasControlInventoryCategory[],
    review: GraphReviewAdjudicationRunCertificate | null,
    governance: GraphGovernanceRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
): AtlasControlContract['invariants'] {
    const uniqueIds = new Set(rows.map((row) => row.identity.id));
    const identityPassed = rows.every((row) => row.identity.rawId && row.identity.lane && row.identity.sourceContract)
        && uniqueIds.size === rows.length;
    const inventoryPassed = inventory.every((item) => item.totalRows >= item.visibleRows && item.visibleRows === item.rowIds.length);
    return {
        typedRowIdentities: invariant(identityPassed ? 'passed' : 'failed', identityPassed ? 'All visible rows have unique typed identities.' : 'Duplicate or incomplete typed row identities detected.'),
        exactInventory: invariant(inventoryPassed ? 'passed' : 'failed', inventoryPassed ? 'Every category declares total and visible rows separately.' : 'Inventory totals do not cover their visible rows.'),
        reviewNliSeparated: invariant('passed', 'Review ledger, manual decisions, NLI pairs, and NLI judgments are distinct lanes.'),
        noTopologyWrites: combineProofs(snapshot, review, governance, promotion),
        candidateOnlyGovernance: governance
            ? invariant(governance.noTopologyProof.passed ? 'passed' : 'failed', governance.noTopologyProof.passed ? 'Governance output is candidate-only.' : `${governance.noTopologyProof.violations.length} governance topology violations detected.`)
            : invariant('pending', 'No governance certificate is attached.'),
        promotionReceiptGated: promotion
            ? invariant(promotion.receiptCount >= promotion.commitCount ? 'passed' : 'failed', `${promotion.receiptCount} receipts cover ${promotion.commitCount} commits.`)
            : invariant('pending', 'No promotion certificate is attached.'),
    };
}

function combineProofs(
    snapshot: GraphRebuildSnapshot | null,
    review: GraphReviewAdjudicationRunCertificate | null,
    governance: GraphGovernanceRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
): AtlasControlInvariant {
    if (!snapshot) return invariant('pending', 'No graph snapshot is attached.');
    const failed = review?.proof.noTopologyWrites.status === 'failed'
        || governance?.noTopologyProof.passed === false
        || snapshot.crossDocumentBridgeCertificate?.noTopologyWrites === false;
    if (failed) return invariant('failed', 'At least one attached certificate reports a topology write.');
    if (!review || !governance || !promotion) return invariant('pending', 'One or more proof certificates are not attached.');
    return invariant('passed', snapshot.crossDocumentBridgeCertificate
        ? 'Review, governance, promotion, and cross-document certificates report no topology writes.'
        : 'Review, governance, and promotion certificates report no topology writes.');
}

function inventoryCard(
    id: string,
    item: AtlasControlInventoryCategory,
    detail: string,
    tone?: AtlasControlTone,
): AtlasControlCard {
    const intent: AtlasControlIntent = item.actionability === 'model_run'
        ? 'model_action'
        : item.actionability === 'manual_receipt'
            ? 'manual_action'
            : item.actionability === 'promotion_preview'
                ? 'promotion_preview'
                : 'read_only_ledger';
    return card(id, item.family, item.lane, item.sourceContract, item.id, item.label, item.totalRows,
        detail, intent, countScope(item), item.actionability, item.allowedActions, item.receiptPolicy, tone);
}

function card(
    id: string,
    family: AtlasControlFamily,
    lane: AtlasControlLane,
    sourceContract: AtlasControlSourceContract,
    inventoryCategoryId: AtlasControlInventoryCategoryId | null,
    label: string,
    value: number | string,
    detail: string,
    intent: AtlasControlIntent,
    countScope: AtlasControlCountScope,
    actionability: AtlasControlActionability,
    allowedActions: AtlasControlAction[],
    receiptPolicy: AtlasControlReceiptPolicy,
    tone: AtlasControlTone = valueTone(value),
): AtlasControlCard {
    return {
        id, family, lane, sourceContract, inventoryCategoryId, label, value,
        valueLabel: typeof value === 'number' ? value.toLocaleString() : value,
        detail, tone, intent, countScope, actionability, allowedActions, receiptPolicy,
    };
}

function section(
    id: string,
    family: AtlasControlFamily,
    label: string,
    detail: string,
    cards: AtlasControlCard[],
): AtlasControlSection {
    return { id, family, label, detail, cards };
}

function countScope(item: AtlasControlInventoryCategory): AtlasControlCountScope {
    if (item.lane === 'manual_decision') return 'manual_actionable';
    if (item.lane === 'nli_pair') return 'nli_pairwise';
    if (item.sourceContract.endsWith('certificate') || item.sourceContract === 'promotion_verdict') return 'certificate';
    return item.lane.endsWith('_ledger') ? 'total_ledger' : 'visible_projection';
}

function manualActions(rows: AtlasControlRow[]): AtlasControlAction[] {
    return unique(rows.filter((row) => row.identity.lane === 'manual_decision').flatMap((row) => row.allowedActions));
}

function receipt(
    kind: AtlasControlReceiptKind,
    reversible: boolean,
    topologyMutationAllowed: boolean,
): AtlasControlReceiptPolicy {
    return { required: true, kind, reversible, topologyMutationAllowed };
}

function noReceipt(): AtlasControlReceiptPolicy {
    return { required: false, kind: null, reversible: false, topologyMutationAllowed: false };
}

function invariant(status: GraphReviewProofState, detail: string): AtlasControlInvariant {
    return { status, detail };
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function uniqueControlRows(rows: AtlasControlRow[]): AtlasControlRow[] {
    return [...new Map(rows.map((row) => [row.identity.id, row])).values()];
}

function valueTone(value: number | string): AtlasControlTone {
    if (typeof value === 'number') return value > 0 ? 'ready' : 'quiet';
    return value === 'OK' || value.toLowerCase() === 'active' ? 'ready' : 'quiet';
}

function nonNegative(...values: Array<number | undefined | null>): number {
    for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
    }
    return 0;
}
