import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-review-adjudication-run-certificate/v1' as const;
export const GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION =
    'phoenix-review-adjudication-view-contract/v1' as const;

export type GraphReviewAdjudicationEntrypoint = 'graph_build' | 'manual_stage8' | 'derived';
export type GraphReviewAdjudicationViewTone = 'ready' | 'review' | 'warning' | 'danger' | 'quiet';

export interface GraphReviewQueueExcludedReason {
    id: string;
    label: string;
    count: number;
    detail: string;
}

export interface GraphReviewQueueInventory {
    totalReviewRows: number;
    nliEligibleRows: number;
    excludedRows: number;
    duplicateRows: number;
    judgedRows: number;
    appliedRows: number;
    topologyWrites: number;
    nliEligibilityPercent: number;
    excludedReasons: GraphReviewQueueExcludedReason[];
}

export interface GraphReviewAdjudicationStageSummary {
    id: string;
    label: string;
    durationMs: number;
    counters: Record<string, number>;
}

export interface GraphReviewAdjudicationPreviewRow {
    id: string;
    sourceId: string;
    targetId: string;
    edgeType: string;
    label: string;
    confidence: number;
}

export interface GraphReviewAdjudicationRunCertificate {
    schemaVersion: typeof GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION;
    generatedAt: number;
    source: GraphReviewAdjudicationEntrypoint;
    document: {
        snapshotId: string;
        scopeKind: string;
        scopeId: string;
        noteIds: string[];
    };
    model: {
        modelId: string;
        modelLabel: string;
        dimension: number;
        dimensionLabel: string;
    };
    queue: GraphReviewQueueInventory;
    proof: {
        candidateOnly: true;
        noTopologyWrites: boolean;
        dimensionContractPassed: boolean;
        modelRan: boolean;
    };
    rows: GraphReviewAdjudicationPreviewRow[];
    stageSummaries: GraphReviewAdjudicationStageSummary[];
}

export interface GraphReviewAdjudicationActionState {
    label: string;
    disabled: boolean;
    status: string;
    reason: string;
    tone: GraphReviewAdjudicationViewTone;
}

export interface GraphReviewAdjudicationViewContract {
    schemaVersion: typeof GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION;
    source: GraphReviewAdjudicationEntrypoint | 'missing';
    queue: GraphReviewQueueInventory & {
        totalLabel: string;
        eligibleLabel: string;
        excludedLabel: string;
        judgedLabel: string;
        summary: string;
    };
    model: {
        classifierLabel: string;
        classifierDetail: string;
        embeddingDimensionLabel: string;
        embeddingDimensionDetail: string;
    };
    proof: {
        noTopologyWrites: boolean;
        dimensionContractPassed: boolean;
        modelRan: boolean;
        status: string;
        tone: GraphReviewAdjudicationViewTone;
    };
    action: GraphReviewAdjudicationActionState;
    reason: GraphReviewQueueExcludedReason | null;
}

export interface BuildReviewAdjudicationRunCertificateInput {
    snapshot: GraphRebuildSnapshot | null;
    rawResult?: unknown;
    source: GraphReviewAdjudicationEntrypoint;
    modelId?: string;
    modelLabel?: string;
    dimensionLabel?: string;
    embeddingDimension?: number;
}

export interface BuildReviewAdjudicationViewContractOptions {
    modelInitialized?: boolean;
    running?: boolean;
    loading?: boolean;
    busy?: boolean;
    hasScope?: boolean;
}

export function buildReviewAdjudicationRunCertificate(
    input: BuildReviewAdjudicationRunCertificateInput,
): GraphReviewAdjudicationRunCertificate {
    const raw = asRecord(input.rawResult);
    const snapshot = input.snapshot;
    const totalReviewRows = reviewRowTotal(snapshot, raw);
    const rawInputs = numericField(raw, 0, 'inputCount', 'rawInputCount', 'rawInputs', 'input_count')
        || arrayLengthField(raw, 'inputs', 'rawInputs');
    const plannedInputs = numericField(raw, 0, 'plannedInputCount', 'plannedInputs', 'planned_input_count')
        || arrayLengthField(raw, 'plannedInputs');
    const judgedRows = numericField(raw, 0, 'resultCount', 'result_count', 'results', 'judgments')
        || arrayLengthField(raw, 'results', 'judgments');
    const appliedRows = appliedRowCount(raw['applied']);
    const duplicateRows = numericField(raw, 0, 'duplicateInputCount', 'duplicateInputs');
    const nliEligibleRows = Math.max(plannedInputs, rawInputs - duplicateRows, judgedRows, 0);
    const topologyWrites = numericField(raw, 0, 'topologyWrites', 'committedTopologyWrites', 'topology_writes');
    const excludedRows = Math.max(0, totalReviewRows - nliEligibleRows - duplicateRows);
    const dimensionLabel = input.dimensionLabel || snapshot?.embeddingProfile?.dimensionLabel || '';
    const dimension = input.embeddingDimension
        || numericField(raw, 0, 'dimension')
        || parseDimensionLabel(dimensionLabel);
    const expectedDimension = parseDimensionLabel(dimensionLabel);
    const stageSummaries = normalizeStageSummaries(raw['stageSummaries']);
    const rows = normalizeJudgments(raw['judgments']);
    return {
        schemaVersion: GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION,
        generatedAt: Date.now(),
        source: input.source,
        document: {
            snapshotId: snapshot?.id || '',
            scopeKind: snapshot?.scopeKind || 'unknown',
            scopeId: snapshot?.scopeId || 'unknown',
            noteIds: snapshot?.noteIds || [],
        },
        model: {
            modelId: input.modelId || stringField(raw, 'modelId') || 'onnx-community/ModernBERT-base-nli',
            modelLabel: input.modelLabel || stringField(raw, 'modelLabel') || 'ModernBERT NLI',
            dimension,
            dimensionLabel: dimensionLabel || (dimension ? `${dimension}d` : ''),
        },
        queue: {
            totalReviewRows,
            nliEligibleRows,
            excludedRows,
            duplicateRows,
            judgedRows,
            appliedRows,
            topologyWrites,
            nliEligibilityPercent: totalReviewRows ? Math.round((nliEligibleRows / totalReviewRows) * 100) : 0,
            excludedReasons: excludedReasons(totalReviewRows, nliEligibleRows, duplicateRows, excludedRows),
        },
        proof: {
            candidateOnly: true,
            noTopologyWrites: topologyWrites === 0,
            dimensionContractPassed: !expectedDimension || !dimension || expectedDimension === dimension,
            modelRan: judgedRows > 0 || appliedRows > 0,
        },
        rows,
        stageSummaries,
    };
}

export function applyReviewAdjudicationCertificate(
    snapshot: GraphRebuildSnapshot,
    certificate: GraphReviewAdjudicationRunCertificate,
): void {
    snapshot.reviewAdjudicationCertificate = certificate;
    snapshot.counters.reviewAdjudicationTotalRows = certificate.queue.totalReviewRows;
    snapshot.counters.reviewAdjudicationEligibleRows = certificate.queue.nliEligibleRows;
    snapshot.counters.reviewAdjudicationExcludedRows = certificate.queue.excludedRows;
    snapshot.counters.reviewAdjudicationDuplicateRows = certificate.queue.duplicateRows;
    snapshot.counters.reviewAdjudicationJudgedRows = certificate.queue.judgedRows;
    snapshot.counters.reviewAdjudicationAppliedRows = certificate.queue.appliedRows;
    snapshot.counters.reviewAdjudicationTopologyWrites = certificate.queue.topologyWrites;
    snapshot.counters.reviewAdjudicationDimension = certificate.model.dimension;
}

export function buildReviewAdjudicationViewContract(
    certificate: GraphReviewAdjudicationRunCertificate | null,
    options: BuildReviewAdjudicationViewContractOptions = {},
): GraphReviewAdjudicationViewContract {
    const queue = certificate?.queue ?? emptyQueue();
    const failed = !!certificate && (!certificate.proof.noTopologyWrites || !certificate.proof.dimensionContractPassed);
    const reason = queue.excludedReasons[0] ?? null;
    const proofTone: GraphReviewAdjudicationViewTone = failed
        ? 'danger'
        : certificate?.proof.modelRan
            ? 'ready'
            : queue.nliEligibleRows > 0
                ? 'review'
                : 'quiet';
    return {
        schemaVersion: GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION,
        source: certificate?.source ?? 'missing',
        queue: {
            ...queue,
            totalLabel: `${formatCount(queue.totalReviewRows)} review rows`,
            eligibleLabel: `${formatCount(queue.nliEligibleRows)} NLI eligible`,
            excludedLabel: `${formatCount(queue.excludedRows)} excluded`,
            judgedLabel: `${formatCount(queue.judgedRows)} judged / ${formatCount(queue.appliedRows)} applied`,
            summary: `${formatCount(queue.nliEligibleRows)} NLI eligible / ${formatCount(queue.totalReviewRows)} review rows`,
        },
        model: {
            classifierLabel: certificate?.model.modelLabel || 'ModernBERT NLI',
            classifierDetail: 'ModernBERT / pairwise candidate judgments / 0 topology writes',
            embeddingDimensionLabel: certificate?.model.dimensionLabel || '',
            embeddingDimensionDetail: certificate
                ? `${certificate.model.dimensionLabel || `${certificate.model.dimension || 0}d`} embedding target contract`
                : 'embedding target contract pending',
        },
        proof: {
            noTopologyWrites: certificate?.proof.noTopologyWrites ?? true,
            dimensionContractPassed: certificate?.proof.dimensionContractPassed ?? true,
            modelRan: certificate?.proof.modelRan ?? false,
            status: failed ? 'error' : certificate?.proof.modelRan ? 'ready' : queue.nliEligibleRows > 0 ? 'planned' : 'idle',
            tone: proofTone,
        },
        action: buildReviewActionState(certificate, options),
        reason,
    };
}

function buildReviewActionState(
    certificate: GraphReviewAdjudicationRunCertificate | null,
    options: BuildReviewAdjudicationViewContractOptions,
): GraphReviewAdjudicationActionState {
    const queue = certificate?.queue ?? emptyQueue();
    const hasScope = options.hasScope ?? true;
    if (options.running) {
        return actionState('Reviewing', true, 'running', 'ModernBERT review is already running.', 'review');
    }
    if (options.loading) {
        return actionState('Loading NLI', true, 'warming', 'ModernBERT NLI is warming.', 'review');
    }
    if (options.busy) {
        return actionState('Graph busy', true, 'busy', 'Wait for the active graph or model operation to finish.', 'quiet');
    }
    if (!hasScope) {
        return actionState('Pick Scope', true, 'blocked', 'Choose a runnable atlas scope first.', 'warning');
    }
    if (certificate && (!certificate.proof.noTopologyWrites || !certificate.proof.dimensionContractPassed)) {
        return actionState('Fix Contract', true, 'error', 'Review certificate failed the no-topology or embedding dimension proof.', 'danger');
    }
    if (certificate && queue.totalReviewRows > 0 && queue.nliEligibleRows === 0) {
        return actionState(
            'No NLI pairs',
            true,
            'blocked',
            `${formatCount(queue.totalReviewRows)} review rows exist, but none match the pairwise ModernBERT input contract.`,
            'quiet',
        );
    }
    const label = options.modelInitialized ? 'Run NLI' : 'Load + Run';
    return actionState(label, false, certificate?.proof.modelRan ? 'ready' : 'planned', 'ModernBERT can score pairwise candidate rows.', 'ready');
}

function actionState(
    label: string,
    disabled: boolean,
    status: string,
    reason: string,
    tone: GraphReviewAdjudicationViewTone,
): GraphReviewAdjudicationActionState {
    return { label, disabled, status, reason, tone };
}

function emptyQueue(): GraphReviewQueueInventory {
    return {
        totalReviewRows: 0,
        nliEligibleRows: 0,
        excludedRows: 0,
        duplicateRows: 0,
        judgedRows: 0,
        appliedRows: 0,
        topologyWrites: 0,
        nliEligibilityPercent: 0,
        excludedReasons: [],
    };
}

function formatCount(value: number): string {
    return Math.max(0, Math.round(value || 0)).toLocaleString();
}

function reviewRowTotal(snapshot: GraphRebuildSnapshot | null, raw: Record<string, unknown>): number {
    const rawTotal = numericField(raw, 0, 'totalReviewRows', 'reviewRows', 'total_review_rows', 'review_rows');
    if (rawTotal) return rawTotal;
    const counters = snapshot?.counters;
    return Math.max(
        counters?.documentReviewRows || 0,
        snapshot?.documentReviewSummary?.rows?.length || 0,
        (counters?.semanticEvalLedgerRows || 0) + (counters?.discourseEvalLedgerRows || 0),
        counters?.reviewRelationships || 0,
        numericField(raw, 0, 'inputCount', 'rawInputs', 'input_count') || arrayLengthField(raw, 'inputs', 'rawInputs'),
        numericField(raw, 0, 'plannedInputCount', 'plannedInputs', 'planned_input_count') || arrayLengthField(raw, 'plannedInputs'),
    );
}

function excludedReasons(
    totalReviewRows: number,
    nliEligibleRows: number,
    duplicateRows: number,
    excludedRows: number,
): GraphReviewQueueExcludedReason[] {
    const reasons: GraphReviewQueueExcludedReason[] = [];
    if (excludedRows > 0) {
        reasons.push({
            id: 'non_nli_review_row',
            label: 'Non-NLI review rows',
            count: excludedRows,
            detail: 'Graph Review includes gaps, accepted rows, ambiguity, receipts, and diagnostics; only pairwise candidate rows enter ModernBERT.',
        });
    }
    if (duplicateRows > 0) {
        reasons.push({
            id: 'duplicate_pair',
            label: 'Duplicate NLI pairs',
            count: duplicateRows,
            detail: 'Repeated source-target-edge inputs were collapsed before classification.',
        });
    }
    if (totalReviewRows > 0 && nliEligibleRows === 0 && excludedRows === 0) {
        reasons.push({
            id: 'empty_nli_plan',
            label: 'No planned NLI inputs',
            count: totalReviewRows,
            detail: 'The review queue exists, but no rows matched the native NLI pair contract for this run.',
        });
    }
    return reasons;
}

function normalizeStageSummaries(value: unknown): GraphReviewAdjudicationStageSummary[] {
    if (!Array.isArray(value)) return [];
    return value.map((item, index) => {
        const row = asRecord(item);
        const id = stringField(row, 'stage') || stringField(row, 'id') || `stage-${index + 1}`;
        return {
            id,
            label: labelFromId(id),
            durationMs: numericField(row, 0, 'durationMs', 'duration_ms'),
            counters: numericRecord(row['counts'] || row['counters']),
        };
    });
}

function normalizeJudgments(value: unknown): GraphReviewAdjudicationPreviewRow[] {
    if (!Array.isArray(value)) return [];
    return value.slice(0, 12).map((item, index) => {
        const row = asRecord(item);
        return {
            id: stringField(row, 'judgmentId') || `judgment-${index + 1}`,
            sourceId: stringField(row, 'sourceId'),
            targetId: stringField(row, 'targetId'),
            edgeType: stringField(row, 'edgeType'),
            label: stringField(row, 'predictedLabel') || 'unknown',
            confidence: numericField(row, 0, 'confidence'),
        };
    });
}

function appliedRowCount(applied: unknown): number {
    if (Array.isArray(applied)) return applied.length;
    const row = asRecord(applied);
    const direct = numericField(row, 0, 'count', 'applied', 'appliedRows', 'rows');
    if (direct) return direct;
    for (const value of Object.values(row)) {
        if (Array.isArray(value)) return value.length;
    }
    return 0;
}

function parseDimensionLabel(label: string | undefined): number {
    const match = String(label || '').match(/(\d+)/);
    return match ? Number(match[1]) : 0;
}

function numericField(record: Record<string, unknown>, fallback: number, ...keys: string[]): number {
    for (const key of keys) {
        const value = record[key];
        if (typeof value === 'number' && Number.isFinite(value)) return value;
        if (typeof value === 'string') {
            const parsed = Number(value);
            if (Number.isFinite(parsed)) return parsed;
        }
    }
    return fallback;
}

function arrayLengthField(record: Record<string, unknown>, ...keys: string[]): number {
    for (const key of keys) {
        const value = record[key];
        if (Array.isArray(value)) return value.length;
    }
    return 0;
}

function stringField(record: Record<string, unknown>, key: string): string {
    const value = record[key];
    return typeof value === 'string' ? value : '';
}

function numericRecord(value: unknown): Record<string, number> {
    const out: Record<string, number> = {};
    for (const [key, raw] of Object.entries(asRecord(value))) {
        if (typeof raw === 'number' && Number.isFinite(raw)) out[key] = raw;
    }
    return out;
}

function asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
}

function labelFromId(id: string): string {
    return id.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ');
}
