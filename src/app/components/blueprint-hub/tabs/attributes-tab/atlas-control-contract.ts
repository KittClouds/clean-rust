import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import {
    buildGovernanceRunCertificate,
    type GraphGovernanceRunCertificate,
} from '../../../../graph-rebuild/graph-governance-run-certificate';
import type {
    GraphPromotionVerdictCertificate,
} from '../../../../graph-rebuild/graph-promotion-verdict';
import {
    buildReviewAdjudicationRunCertificate,
    buildReviewAdjudicationViewContract,
    type GraphReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationViewContract,
} from '../../../../graph-rebuild/graph-review-adjudication-certificate';

export const ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION = 'phoenix-atlas-control-contract/v1' as const;

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

export type AtlasControlSourceContract =
    | 'graph_build'
    | 'document_review'
    | 'review_adjudication'
    | 'memory_governance'
    | 'governance_certificate'
    | 'promotion_verdict'
    | 'metrics';

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
    | 'promotion_preview';

export type AtlasControlAction =
    | 'build_graph'
    | 'refresh_review'
    | 'run_nli'
    | 'inspect'
    | 'accept_review_row'
    | 'reject_review_row'
    | 'preview_promotion';

export type AtlasControlTone = 'ready' | 'review' | 'warning' | 'danger' | 'quiet';

export interface AtlasControlCard {
    id: string;
    family: AtlasControlFamily;
    sourceContract: AtlasControlSourceContract;
    label: string;
    value: number | string;
    valueLabel: string;
    detail: string;
    tone: AtlasControlTone;
    intent: AtlasControlIntent;
    countScope: AtlasControlCountScope;
    actionability: AtlasControlActionability;
    allowedActions: AtlasControlAction[];
    noTopologyWrites: boolean;
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
    generatedAt: number;
    snapshotId: string;
    header: AtlasControlCard[];
    workflow: AtlasControlCard[];
    sections: AtlasControlSection[];
    cardsById: Record<string, AtlasControlCard>;
    invariants: {
        graphTabSourceOfTruth: 'atlas_control';
        reviewNliSeparated: boolean;
        noTopologyWrites: boolean;
        candidateOnlyGovernance: boolean;
        promotionReceiptGated: boolean;
    };
    certificates: {
        reviewAdjudication: GraphReviewAdjudicationViewContract;
        governance: GraphGovernanceRunCertificate | null;
        promotion: GraphPromotionVerdictCertificate | null;
    };
}

interface BuildAtlasControlContractInput {
    snapshot: GraphRebuildSnapshot | null;
    entityCount?: number;
    edgeCount?: number;
    reviewAdjudicationCertificate?: GraphReviewAdjudicationRunCertificate | null;
    reviewAdjudicationViewContract?: GraphReviewAdjudicationViewContract | null;
    governanceCertificate?: GraphGovernanceRunCertificate | null;
    promotionCertificate?: GraphPromotionVerdictCertificate | null;
}

export function buildAtlasControlContract(
    input: BuildAtlasControlContractInput,
): AtlasControlContract {
    const snapshot = input.snapshot;
    const counters = (snapshot?.counters ?? {}) as Record<string, number | undefined>;
    const reviewAdjudication = input.reviewAdjudicationViewContract
        ?? buildReviewAdjudicationViewContract(
            input.reviewAdjudicationCertificate
                ?? snapshot?.reviewAdjudicationCertificate
                ?? (snapshot ? buildReviewAdjudicationRunCertificate({
                    snapshot,
                    source: 'derived',
                    modelId: 'onnx-community/ModernBERT-base-nli',
                    modelLabel: 'ModernBERT NLI',
                    dimensionLabel: snapshot.embeddingProfile?.dimensionLabel,
                    embeddingDimension: snapshot.embeddingProfile?.selectedDimensions,
                }) : null),
        );
    const governance = input.governanceCertificate ?? (snapshot ? buildGovernanceRunCertificate(snapshot) : null);
    const promotion = input.promotionCertificate ?? snapshot?.promotionVerdictCertificate ?? null;

    const entityCount = positiveNumber(input.entityCount, counters['entities'], snapshot?.nodes?.length);
    const edgeCount = positiveNumber(input.edgeCount, counters['edges'], snapshot?.edges?.length);
    const targetCount = positiveNumber(counters['embeddingTargets'], snapshot?.embeddingTargets?.length);
    const governanceCount = positiveNumber(
        governance?.candidatesByAction.total,
        counters['memoryGovernanceCandidates'],
        snapshot?.memoryGovernanceCandidates?.length,
    );
    const governanceNoCommit = positiveNumber(
        governance?.noTopologyProof.candidateOnlyRows,
        governanceCount,
    );
    const promotionCount = positiveNumber(
        promotion?.audit.total,
        counters['promotionVerdictRows'],
    );
    const acceptablePromotionCount = positiveNumber(promotion?.audit.acceptable);
    const manualReviewRows = positiveNumber(
        counters['documentReviewActionableRows'],
        counters['graphReviewActionableRows'],
        counters['reviewQueueRows'],
    );
    const proofOk = !!governance
        && governance.noTopologyProof.passed
        && governance.protectedMemoryProof.passed
        && governance.compressionDominanceProof.passed;
    const nliActionAllowed = !reviewAdjudication.action.disabled;

    const header = [
        card('header-entities', 'graph', 'graph_build', 'Entities', entityCount, 'committed atlas entities', 'metric', 'visible_projection', 'inspect_only', ['inspect']),
        card('header-graph-edges', 'graph', 'graph_build', 'Graph edges', edgeCount, 'accepted read-model topology', 'metric', 'visible_projection', 'inspect_only', ['inspect']),
        card('header-targets', 'graph', 'graph_build', 'Targets', targetCount, 'retrieval and render targets', 'metric', 'visible_projection', 'inspect_only', ['inspect']),
        card('header-governance', 'governance', 'memory_governance', 'Governance', governanceCount, `${governanceNoCommit.toLocaleString()} no-commit rows`, 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
        card('header-nli-eligible', 'review', 'review_adjudication', 'NLI eligible', reviewAdjudication.queue.nliEligibleRows, 'pairwise ModernBERT inputs', 'model_action', 'nli_pairwise', nliActionAllowed ? 'model_run' : 'none', nliActionAllowed ? ['run_nli'] : []),
        card('header-verdicts', 'promotion', 'promotion_verdict', 'Verdicts', promotionCount, `${acceptablePromotionCount.toLocaleString()} acceptable`, 'diagnostic_proof', 'certificate', 'promotion_preview', ['preview_promotion']),
    ];

    const workflow = [
        card('workflow-graph-build', 'graph', 'graph_build', 'Graph build', edgeCount, `${targetCount.toLocaleString()} retrieval targets`, 'run', 'visible_projection', 'none', ['build_graph']),
        card('workflow-review-ledger', 'review', 'document_review', 'Review ledger', reviewAdjudication.queue.totalReviewRows, `${manualReviewRows.toLocaleString()} manual rows`, 'read_only_ledger', 'total_ledger', manualReviewRows > 0 ? 'manual_receipt' : 'inspect_only', manualReviewRows > 0 ? ['accept_review_row', 'reject_review_row'] : ['inspect']),
        card('workflow-nli-pairs', 'review', 'review_adjudication', 'NLI pairs', reviewAdjudication.queue.nliEligibleRows, reviewAdjudication.action.reason, 'model_action', 'nli_pairwise', nliActionAllowed ? 'model_run' : 'none', nliActionAllowed ? ['run_nli'] : []),
        card('workflow-governance', 'governance', 'memory_governance', 'Governance', governanceCount, `${governanceNoCommit.toLocaleString()} no-commit rows`, 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
        card('workflow-promotion', 'promotion', 'promotion_verdict', 'Promotion', promotionCount, `${acceptablePromotionCount.toLocaleString()} acceptable`, 'promotion_preview', 'certificate', 'promotion_preview', ['preview_promotion']),
        card('workflow-run-proof', 'proof', 'governance_certificate', 'Run proof', proofOk ? 'OK' : '--', proofOk ? 'candidate-only verified' : 'waiting for run', 'diagnostic_proof', 'certificate', 'none', []),
    ];

    const sections = [
        reviewSection(reviewAdjudication, manualReviewRows),
        governanceSection(governance, governanceCount, governanceNoCommit),
        promotionSection(promotion, promotionCount),
        roomSection(counters, reviewAdjudication),
    ];
    const allCards = [...header, ...workflow, ...sections.flatMap((section) => section.cards)];

    return {
        schemaVersion: ATLAS_CONTROL_CONTRACT_SCHEMA_VERSION,
        generatedAt: Date.now(),
        snapshotId: snapshot?.id ?? 'no-snapshot',
        header,
        workflow,
        sections,
        cardsById: Object.fromEntries(allCards.map((item) => [item.id, item])),
        invariants: {
            graphTabSourceOfTruth: 'atlas_control',
            reviewNliSeparated: true,
            noTopologyWrites: reviewAdjudication.proof.noTopologyWrites
                && (governance?.noTopologyProof.passed ?? true)
                && (promotion?.noTopologyWrites ?? true),
            candidateOnlyGovernance: (governance?.noTopologyProof.violations.length ?? 0) === 0,
            promotionReceiptGated: (promotion?.receiptCount ?? 0) >= (promotion?.commitCount ?? 0),
        },
        certificates: {
            reviewAdjudication,
            governance,
            promotion,
        },
    };
}

function reviewSection(
    review: GraphReviewAdjudicationViewContract,
    manualReviewRows: number,
): AtlasControlSection {
    const nliActionAllowed = !review.action.disabled;
    return {
        id: 'section-review-adjudication',
        family: 'review',
        label: 'Review adjudication',
        detail: 'Separates manual review rows from pairwise ModernBERT inputs.',
        cards: [
            card('review-ledger', 'review', 'document_review', 'Review rows', review.queue.totalReviewRows, 'full inspectable ledger', 'read_only_ledger', 'total_ledger', 'inspect_only', ['inspect']),
            card('review-manual-action', 'review', 'document_review', 'Manual decisions', manualReviewRows, 'accept/reject receipt rows', 'manual_action', 'manual_actionable', manualReviewRows > 0 ? 'manual_receipt' : 'none', manualReviewRows > 0 ? ['accept_review_row', 'reject_review_row'] : []),
            card('review-nli-pairs', 'review', 'review_adjudication', 'NLI pair queue', review.queue.nliEligibleRows, review.action.reason, 'model_action', 'nli_pairwise', nliActionAllowed ? 'model_run' : 'none', nliActionAllowed ? ['run_nli'] : []),
            card('review-excluded', 'review', 'review_adjudication', 'Excluded rows', review.queue.excludedRows, 'not valid pairwise NLI inputs', 'diagnostic_proof', 'diagnostic', 'inspect_only', ['inspect'], review.queue.excludedRows > 0 ? 'warning' : 'ready'),
            card('review-judged', 'review', 'review_adjudication', 'Judged rows', review.queue.judgedRows, `${review.queue.appliedRows.toLocaleString()} applied judgments`, 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
            card('review-topology-writes', 'review', 'review_adjudication', 'Topology writes', review.queue.topologyWrites, 'review pass must stay report-only', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], review.queue.topologyWrites > 0 ? 'danger' : 'ready'),
        ],
    };
}

function governanceSection(
    governance: GraphGovernanceRunCertificate | null,
    governanceCount: number,
    governanceNoCommit: number,
): AtlasControlSection {
    return {
        id: 'section-memory-governance',
        family: 'governance',
        label: 'Memory governance',
        detail: 'Candidate-only keep, compress, quarantine, and attenuation decisions.',
        cards: [
            card('governance-candidates', 'governance', 'memory_governance', 'Candidate rows', governanceCount, 'candidate-only output', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
            card('governance-no-commit', 'governance', 'governance_certificate', 'No-commit rows', governanceNoCommit, 'no topology writes', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
            card('governance-attention', 'governance', 'governance_certificate', 'Attention rows', positiveNumber(governance?.attentionLanes.totalAttentionRows), 'exception lanes only', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
            card('governance-rust-time', 'governance', 'governance_certificate', 'Rust time', `${positiveNumber(governance?.timings.nativeMemoryGovernanceRustMicros, governance?.timings.memoryGovernanceBuildMicros).toLocaleString()} us`, 'engine runtime', 'metric', 'diagnostic', 'none', []),
        ],
    };
}

function promotionSection(
    promotion: GraphPromotionVerdictCertificate | null,
    promotionCount: number,
): AtlasControlSection {
    return {
        id: 'section-promotion',
        family: 'promotion',
        label: 'Promotion cockpit',
        detail: 'Candidate to accepted truth, gated by receipts and rollback plans.',
        cards: [
            card('promotion-verdicts', 'promotion', 'promotion_verdict', 'Verdict rows', promotionCount, 'durable proposal receipts', 'promotion_preview', 'certificate', 'promotion_preview', ['preview_promotion']),
            card('promotion-acceptable', 'promotion', 'promotion_verdict', 'Acceptable', positiveNumber(promotion?.audit.acceptable), 'passed required gates', 'promotion_preview', 'certificate', 'promotion_preview', ['preview_promotion']),
            card('promotion-blocked', 'promotion', 'promotion_verdict', 'Blocked', positiveNumber(promotion?.audit.blocked), 'failed required gates', 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect'], positiveNumber(promotion?.audit.blocked) > 0 ? 'warning' : 'ready'),
            card('promotion-receipts', 'promotion', 'promotion_verdict', 'Receipts', positiveNumber(promotion?.receiptCount), `${positiveNumber(promotion?.commitCount).toLocaleString()} commits`, 'diagnostic_proof', 'certificate', 'inspect_only', ['inspect']),
        ],
    };
}

function roomSection(
    counters: Record<string, number | undefined>,
    review: GraphReviewAdjudicationViewContract,
): AtlasControlSection {
    const factRows = positiveNumber(counters['factRows'], counters['facts']);
    return {
        id: 'section-rooms',
        family: 'metrics',
        label: 'Operating rooms',
        detail: 'Room labels describe the data contract before any action is offered.',
        cards: [
            card('room-structure', 'structure', 'graph_build', 'Structure ledger', positiveNumber(counters['structureRows'], counters['hierarchyRows'], 0), 'document and chunk hierarchy', 'read_only_ledger', 'total_ledger', 'inspect_only', ['inspect']),
            card('room-facts', 'facts', 'document_review', 'Fact review rows', factRows, 'candidate relation facts', 'manual_action', 'manual_actionable', factRows > 0 ? 'manual_receipt' : 'none', factRows > 0 ? ['accept_review_row', 'reject_review_row'] : []),
            card('room-discourse', 'discourse', 'graph_build', 'Discourse packets', positiveNumber(counters['discourseRows'], counters['discoursePackets'], 0), 'cross-document idea packets', 'read_only_ledger', 'total_ledger', 'inspect_only', ['inspect']),
            card('room-review', 'review', 'review_adjudication', 'NLI pair inputs', review.queue.nliEligibleRows, 'ModernBERT pairwise candidates', 'model_action', 'nli_pairwise', review.action.disabled ? 'none' : 'model_run', review.action.disabled ? [] : ['run_nli']),
            card('room-metrics', 'metrics', 'metrics', 'Metrics', positiveNumber(counters['metricsRows'], counters['metrics'], 0), 'run health and timing ledger', 'metric', 'diagnostic', 'inspect_only', ['inspect']),
        ],
    };
}

function card(
    id: string,
    family: AtlasControlFamily,
    sourceContract: AtlasControlSourceContract,
    label: string,
    value: number | string,
    detail: string,
    intent: AtlasControlIntent,
    countScope: AtlasControlCountScope,
    actionability: AtlasControlActionability,
    allowedActions: AtlasControlAction[],
    tone: AtlasControlTone = valueTone(value),
): AtlasControlCard {
    return {
        id,
        family,
        sourceContract,
        label,
        value,
        valueLabel: typeof value === 'number' ? value.toLocaleString() : value,
        detail,
        tone,
        intent,
        countScope,
        actionability,
        allowedActions,
        noTopologyWrites: sourceContract !== 'promotion_verdict' || intent !== 'run',
    };
}

function valueTone(value: number | string): AtlasControlTone {
    if (typeof value === 'number') return value > 0 ? 'ready' : 'quiet';
    return value === 'OK' || value.toLowerCase() === 'active' ? 'ready' : 'quiet';
}

function positiveNumber(...values: Array<number | undefined | null>): number {
    for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
    }
    return 0;
}
