import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-review-adjudication-run-certificate/v1' as const;

export type GraphReviewAdjudicationEntrypoint = 'graph_build' | 'manual_stage8' | 'derived';

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

export interface BuildReviewAdjudicationRunCertificateInput {
    snapshot: GraphRebuildSnapshot | null;
    rawResult?: unknown;
    source: GraphReviewAdjudicationEntrypoint;
    modelId?: string;
    modelLabel?: string;
    dimensionLabel?: string;
    embeddingDimension?: number;
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
