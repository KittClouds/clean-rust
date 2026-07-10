import type {
    GraphDocumentReviewActionKind,
    GraphDocumentReviewRow,
} from './graph-document-review';
import {
    buildGovernanceRunCertificate,
    type GraphGovernanceRunCertificate,
} from './graph-governance-run-certificate';
import type {
    GraphPromotionVerdictCertificate,
    GraphPromotionVerdictRow,
} from './graph-promotion-verdict';
import type {
    GraphMemoryGovernanceCandidate,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import {
    buildReviewAdjudicationRunCertificate,
    buildReviewAdjudicationViewContract,
    type GraphReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationViewContract,
    type GraphReviewProofState,
} from './graph-review-adjudication-certificate';

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
    | 'proof';

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
    | 'metrics_ledger';

export type AtlasControlSourceContract =
    | 'graph_build'
    | 'document_review'
    | 'review_adjudication'
    | 'memory_governance'
    | 'governance_certificate'
    | 'promotion_verdict'
    | 'metrics';

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
    | 'metrics_rows';

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
    | 'preview_promotion';

export type AtlasControlTone = 'ready' | 'review' | 'warning' | 'danger' | 'quiet';
export type AtlasControlReceiptKind =
    | 'graph_build_receipt'
    | 'document_review_action_receipt'
    | 'review_adjudication_run_certificate'
    | 'promotion_proposal_receipt';

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
    entityCount?: number;
    edgeCount?: number;
    reviewAdjudicationCertificate?: GraphReviewAdjudicationRunCertificate | null;
    reviewAdjudicationViewContract?: GraphReviewAdjudicationViewContract | null;
    governanceCertificate?: GraphGovernanceRunCertificate | null;
    promotionCertificate?: GraphPromotionVerdictCertificate | null;
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
        governance?.candidatesByAction.total,
        counters['memoryGovernanceCandidates'],
        snapshot?.memoryGovernanceCandidates?.length,
    );
    const promotionCount = nonNegative(promotion?.audit.total, counters['promotionVerdictRows']);
    const rows = buildTypedRows(snapshotId, snapshot, reviewCertificate, promotion);
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
    });
    const inventoryById = Object.fromEntries(inventory.map((item) => [item.id, item])) as
        Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>;

    const header = buildHeader(inventoryById, review, governance, promotion);
    const workflow = buildWorkflow(inventoryById, review, governance, promotion);
    const sections = buildSections(inventoryById, review, governance, promotion);
    const allCards = [...header, ...workflow, ...sections.flatMap((section) => section.cards)];
    const invariants = buildInvariants(snapshot, rows, inventory, reviewCertificate, governance, promotion);

    return {
        schemaVersion: ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION,
        owner: 'atlas_control_contract_service',
        generatedAt: Date.now(),
        snapshotId,
        header,
        workflow,
        sections,
        cardsById: Object.fromEntries(allCards.map((item) => [item.id, item])),
        rows,
        rowsById: Object.fromEntries(rows.map((item) => [item.identity.id, item])),
        inventory,
        inventoryById,
        invariants,
        certificates: { reviewAdjudication: review, governance, promotion },
    };
}

function buildTypedRows(
    snapshotId: string,
    snapshot: GraphRebuildSnapshot | null,
    review: GraphReviewAdjudicationRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
): AtlasControlRow[] {
    const rows: AtlasControlRow[] = [];
    for (const row of snapshot?.documentReviewSummary?.rows ?? []) rows.push(documentReviewRow(snapshotId, row));
    for (const row of review?.rows ?? []) {
        rows.push(typedRow(snapshotId, 'review_adjudication', 'nli_judgment', row.id, 'nli_judgment',
            `${row.sourceId} -> ${row.targetId}`, `${row.edgeType}: ${row.label}`, row.label,
            row.confidence, [], noReceipt(), []));
    }
    for (const row of snapshot?.memoryGovernanceCandidates ?? []) rows.push(governanceRow(snapshotId, row));
    for (const row of promotion?.rows ?? []) rows.push(promotionRow(snapshotId, row));
    return uniquifyRows(rows);
}

function documentReviewRow(snapshotId: string, row: GraphDocumentReviewRow): AtlasControlRow {
    const actions = unique(row.availableActions.map((action) => reviewAction(action.kind)).filter(isAction));
    const manual = row.availableActions.some((action) => action.requiresUserIntent);
    return typedRow(
        snapshotId,
        'document_review',
        manual ? 'manual_decision' : 'review_ledger',
        row.id,
        row.objectKind,
        row.title,
        row.detail,
        row.state,
        row.confidence,
        actions,
        manual ? receipt('document_review_action_receipt', true, false) : noReceipt(),
        row.receiptIds,
    );
}

function governanceRow(snapshotId: string, row: GraphMemoryGovernanceCandidate): AtlasControlRow {
    return typedRow(snapshotId, 'memory_governance', 'governance_candidate', row.id, row.targetKind,
        row.targetId, row.reason, row.action, row.confidence, ['inspect'], noReceipt(), []);
}

function promotionRow(snapshotId: string, row: GraphPromotionVerdictRow): AtlasControlRow {
    return typedRow(snapshotId, 'promotion_verdict', 'promotion_verdict', row.id, row.family,
        promotionLabel(row), row.rationale, row.status, row.deterministicScoreMillis == null
            ? null
            : row.deterministicScoreMillis / 1000,
        ['preview_promotion'], receipt('promotion_proposal_receipt', row.rollbackPlan.availableAfterCommit, true),
        row.receiptId ? [row.receiptId] : []);
}

function typedRow(
    snapshotId: string,
    sourceContract: AtlasControlSourceContract,
    lane: AtlasControlLane,
    rawId: string,
    kind: string,
    label: string,
    detail: string,
    state: string,
    confidence: number | null,
    allowedActions: AtlasControlAction[],
    receiptPolicy: AtlasControlReceiptPolicy,
    receiptIds: string[],
): AtlasControlRow {
    return {
        identity: {
            id: `${sourceContract}:${lane}:${rawId || 'missing-id'}`,
            rawId: rawId || 'missing-id',
            snapshotId,
            sourceContract,
            lane,
            kind,
        },
        label,
        detail,
        state,
        confidence,
        allowedActions,
        receiptPolicy,
        receiptIds: [...receiptIds],
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
}): AtlasControlInventoryCategory[] {
    const laneRows = (lane: AtlasControlLane) => input.rows.filter((row) => row.identity.lane === lane);
    return [
        inventory('entities', 'Entities', 'graph', 'graph_topology', 'graph_build', input.entityCount, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('graph_edges', 'Graph edges', 'graph', 'graph_topology', 'graph_build', input.edgeCount, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('retrieval_targets', 'Retrieval targets', 'graph', 'graph_topology', 'graph_build', input.targetCount, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('structure_rows', 'Structure rows', 'structure', 'structure_ledger', 'graph_build', input.structureRows, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('fact_rows', 'Fact rows', 'facts', 'fact_ledger', 'document_review', input.factRows, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('discourse_rows', 'Discourse rows', 'discourse', 'discourse_ledger', 'graph_build', input.discourseRows, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('review_ledger_rows', 'Review ledger rows', 'review', 'review_ledger', 'document_review', input.review.queue.ledgerRows, laneRows('review_ledger'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('manual_decision_rows', 'Manual decision rows', 'review', 'manual_decision', 'document_review', input.review.queue.manualDecisionRows, laneRows('manual_decision'), input.review.queue.manualDecisionRows ? 'manual_receipt' : 'none', manualActions(input.rows), receipt('document_review_action_receipt', true, false)),
        inventory('nli_pair_rows', 'NLI pair rows', 'review', 'nli_pair', 'review_adjudication', input.review.queue.nliPairRows, [], input.review.action.disabled ? 'none' : 'model_run', input.review.action.disabled ? [] : ['run_nli'], receipt('review_adjudication_run_certificate', false, false)),
        inventory('nli_excluded_rows', 'NLI excluded rows', 'review', 'nli_pair', 'review_adjudication', input.review.queue.nliExcludedRows, [], 'inspect_only', ['inspect'], noReceipt()),
        inventory('nli_judgment_rows', 'NLI judgment rows', 'review', 'nli_judgment', 'review_adjudication', input.review.queue.judgedRows, laneRows('nli_judgment'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('governance_candidate_rows', 'Governance candidates', 'governance', 'governance_candidate', 'memory_governance', input.governanceCount, laneRows('governance_candidate'), 'inspect_only', ['inspect'], noReceipt()),
        inventory('promotion_verdict_rows', 'Promotion verdicts', 'promotion', 'promotion_verdict', 'promotion_verdict', input.promotionCount, laneRows('promotion_verdict'), input.promotionCount ? 'promotion_preview' : 'none', input.promotionCount ? ['preview_promotion'] : [], receipt('promotion_proposal_receipt', true, true)),
        inventory('metrics_rows', 'Metric rows', 'metrics', 'metrics_ledger', 'metrics', input.metricsRows, [], 'inspect_only', ['inspect'], noReceipt()),
    ];
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
        || governance?.noTopologyProof.passed === false;
    if (failed) return invariant('failed', 'At least one attached certificate reports a topology write.');
    if (!review || !governance || !promotion) return invariant('pending', 'One or more proof certificates are not attached.');
    return invariant('passed', 'Review, governance, and promotion certificates report no topology writes.');
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

function reviewAction(kind: GraphDocumentReviewActionKind): AtlasControlAction | null {
    const actions: Record<GraphDocumentReviewActionKind, AtlasControlAction> = {
        accept_fact: 'accept_review_row',
        reject_fact: 'reject_review_row',
        promote_sidecar_to_anchor: 'promote_to_anchor',
        merge_duplicate_units: 'merge_duplicates',
        demote_graph_fact_to_sidecar: 'demote_to_sidecar',
        mute_detector_pattern: 'mute_pattern',
        jump_to_source_span: 'jump_to_source',
        inspect_evidence_path: 'inspect',
        compare_parent_child_context: 'compare_context',
        show_proposal_reason: 'show_reason',
        compile_to_graph: 'compile_to_graph',
    };
    return actions[kind] ?? null;
}

function promotionLabel(row: GraphPromotionVerdictRow): string {
    const truth = row.truth;
    if (truth.subject || truth.predicate || truth.object) {
        return [truth.subject, truth.predicate, truth.object].filter(Boolean).join(' -> ');
    }
    if (row.atom?.kind === 'edge') return `${row.atom.source_id} -> ${row.atom.edge_type} -> ${row.atom.target_id}`;
    if (row.atom?.kind === 'vertex') return row.atom.vertex_id;
    return row.proposalId;
}

function uniquifyRows(rows: AtlasControlRow[]): AtlasControlRow[] {
    const seen = new Map<string, number>();
    return rows.map((row) => {
        const count = seen.get(row.identity.id) ?? 0;
        seen.set(row.identity.id, count + 1);
        if (count === 0) return row;
        return { ...row, identity: { ...row.identity, id: `${row.identity.id}#${count + 1}` } };
    });
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

function isAction(value: AtlasControlAction | null): value is AtlasControlAction {
    return value !== null;
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
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
