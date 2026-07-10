import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_REVIEW_ADJUDICATION_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-review-adjudication-run-certificate/v2' as const;
export const GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION =
    'phoenix-review-adjudication-view-contract/v2' as const;

export type GraphReviewAdjudicationEntrypoint = 'graph_build' | 'manual_stage8' | 'derived';
export type GraphReviewAdjudicationViewTone = 'ready' | 'review' | 'warning' | 'danger' | 'quiet';
export type GraphReviewProofState = 'pending' | 'passed' | 'failed';
export type GraphReviewInventoryCategoryId =
    | 'review_ledger'
    | 'manual_decision'
    | 'nli_pair'
    | 'nli_excluded'
    | 'nli_duplicate'
    | 'nli_judgment'
    | 'applied_judgment';

export interface GraphReviewProofCheck {
    status: GraphReviewProofState;
    detail: string;
}

export interface GraphReviewInventoryCategory {
    id: GraphReviewInventoryCategoryId;
    label: string;
    rowCount: number;
    source: 'document_review' | 'review_adjudication';
    action: 'inspect' | 'manual_receipt' | 'run_nli' | 'none';
}

export interface GraphReviewQueueExcludedReason {
    id: string;
    label: string;
    count: number;
    detail: string;
}

export interface GraphReviewQueueInventory {
    ledgerRows: number;
    manualDecisionRows: number;
    nliPairRows: number;
    nliExcludedRows: number;
    duplicatePairs: number;
    judgedRows: number;
    appliedRows: number;
    topologyWrites: number;
    nliEligibilityPercent: number;
    categories: GraphReviewInventoryCategory[];
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
        input: {
            kind: 'text_pair';
            premiseField: 'premise';
            hypothesisField: 'hypothesis';
            outputLabels: ['entailment', 'neutral', 'contradiction'];
        };
    };
    queue: GraphReviewQueueInventory;
    proof: {
        status: GraphReviewProofState;
        candidateOnly: GraphReviewProofCheck;
        noTopologyWrites: GraphReviewProofCheck;
        inputContract: GraphReviewProofCheck;
        modelExecution: GraphReviewProofCheck;
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
        inputKind: 'text_pair';
        inputDetail: string;
    };
    proof: {
        status: GraphReviewProofState;
        noTopologyWrites: GraphReviewProofCheck;
        inputContract: GraphReviewProofCheck;
        modelRan: boolean;
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
    const ledgerRows = reviewLedgerRows(snapshot, raw);
    const manualDecisionRows = manualReviewRows(snapshot);
    const rawInputs = numericField(raw, 0, 'inputCount', 'rawInputCount', 'rawInputs', 'input_count')
        || arrayLengthField(raw, 'inputs', 'rawInputs');
    const plannedInputs = numericField(raw, 0, 'plannedInputCount', 'plannedInputs', 'planned_input_count')
        || arrayLengthField(raw, 'plannedInputs');
    const judgedRows = numericField(raw, 0, 'resultCount', 'result_count', 'results', 'judgments')
        || arrayLengthField(raw, 'results', 'judgments');
    const appliedRows = appliedRowCount(raw['applied']);
    const duplicatePairs = numericField(raw, 0, 'duplicateInputCount', 'duplicateInputs');
    const nliPairRows = Math.max(plannedInputs, rawInputs - duplicatePairs, judgedRows, 0);
    const nliExcludedRows = numericField(raw, 0, 'excludedInputCount', 'excludedInputs', 'excluded_input_count')
        || arrayLengthField(raw, 'excludedInputs');
    const topologyWrites = numericField(raw, 0, 'topologyWrites', 'committedTopologyWrites', 'topology_writes');
    const stageSummaries = normalizeStageSummaries(raw['stageSummaries']);
    const rows = normalizeJudgments(raw['judgments']);
    const modelRan = judgedRows > 0 || appliedRows > 0;
    const noTopologyWrites = proofCheck(
        topologyWrites === 0 ? 'passed' : 'failed',
        topologyWrites === 0 ? 'Review adjudication wrote no graph topology.' : `${topologyWrites} topology writes detected.`,
    );
    const inputContract = proofCheck(
        nliPairRows > 0 ? 'passed' : 'pending',
        nliPairRows > 0 ? `${nliPairRows} premise/hypothesis pairs entered the classifier.` : 'No text pairs were available to validate.',
    );
    const modelExecution = proofCheck(
        modelRan ? 'passed' : 'pending',
        modelRan ? `${judgedRows} pair judgments were produced.` : 'ModernBERT did not run for this certificate.',
    );
    const categories = inventoryCategories({
        ledgerRows,
        manualDecisionRows,
        nliPairRows,
        nliExcludedRows,
        duplicatePairs,
        judgedRows,
        appliedRows,
    });
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
            input: {
                kind: 'text_pair',
                premiseField: 'premise',
                hypothesisField: 'hypothesis',
                outputLabels: ['entailment', 'neutral', 'contradiction'],
            },
        },
        queue: {
            ledgerRows,
            manualDecisionRows,
            nliPairRows,
            nliExcludedRows,
            duplicatePairs,
            judgedRows,
            appliedRows,
            topologyWrites,
            nliEligibilityPercent: ledgerRows ? Math.round((nliPairRows / ledgerRows) * 100) : 0,
            categories,
            excludedReasons: excludedReasons(nliPairRows, duplicatePairs, nliExcludedRows),
        },
        proof: {
            status: noTopologyWrites.status === 'failed' ? 'failed' : nliPairRows > 0 && !modelRan ? 'pending' : 'passed',
            candidateOnly: proofCheck('passed', 'Review output is candidate-only.'),
            noTopologyWrites,
            inputContract,
            modelExecution,
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
    snapshot.counters.reviewAdjudicationTotalRows = certificate.queue.ledgerRows;
    snapshot.counters.reviewAdjudicationEligibleRows = certificate.queue.nliPairRows;
    snapshot.counters.reviewAdjudicationExcludedRows = certificate.queue.nliExcludedRows;
    snapshot.counters.reviewAdjudicationDuplicateRows = certificate.queue.duplicatePairs;
    snapshot.counters.reviewAdjudicationJudgedRows = certificate.queue.judgedRows;
    snapshot.counters.reviewAdjudicationAppliedRows = certificate.queue.appliedRows;
    snapshot.counters.reviewAdjudicationTopologyWrites = certificate.queue.topologyWrites;
}

export function buildReviewAdjudicationViewContract(
    certificate: GraphReviewAdjudicationRunCertificate | null,
    options: BuildReviewAdjudicationViewContractOptions = {},
): GraphReviewAdjudicationViewContract {
    const queue = certificate?.queue ?? emptyQueue();
    const proofStatus = certificate?.proof.status ?? 'pending';
    const reason = queue.excludedReasons[0] ?? null;
    const proofTone: GraphReviewAdjudicationViewTone = proofStatus === 'failed'
        ? 'danger'
        : certificate?.proof.modelExecution.status === 'passed'
            ? 'ready'
            : queue.nliPairRows > 0
                ? 'review'
                : 'quiet';
    return {
        schemaVersion: GRAPH_REVIEW_ADJUDICATION_VIEW_CONTRACT_SCHEMA_VERSION,
        source: certificate?.source ?? 'missing',
        queue: {
            ...queue,
            totalLabel: `${formatCount(queue.ledgerRows)} ledger rows`,
            eligibleLabel: `${formatCount(queue.nliPairRows)} NLI pairs`,
            excludedLabel: `${formatCount(queue.nliExcludedRows)} NLI exclusions`,
            judgedLabel: `${formatCount(queue.judgedRows)} judged / ${formatCount(queue.appliedRows)} applied`,
            summary: `${formatCount(queue.manualDecisionRows)} manual decisions / ${formatCount(queue.nliPairRows)} NLI pairs / ${formatCount(queue.ledgerRows)} ledger rows`,
        },
        model: {
            classifierLabel: certificate?.model.modelLabel || 'ModernBERT NLI',
            classifierDetail: 'ModernBERT / pairwise candidate judgments / 0 topology writes',
            inputKind: 'text_pair',
            inputDetail: 'premise + hypothesis text -> entailment / neutral / contradiction',
        },
        proof: {
            status: proofStatus,
            noTopologyWrites: certificate?.proof.noTopologyWrites ?? proofCheck('pending', 'No review certificate is attached.'),
            inputContract: certificate?.proof.inputContract ?? proofCheck('pending', 'No text-pair contract is attached.'),
            modelRan: certificate?.proof.modelExecution.status === 'passed',
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
    if (!certificate) {
        return actionState('Build Graph First', true, 'pending', 'A review certificate requires a graph snapshot.', 'quiet');
    }
    if (certificate.proof.noTopologyWrites.status === 'failed' || certificate.proof.inputContract.status === 'failed') {
        return actionState('Fix Contract', true, 'error', 'Review certificate failed the no-topology or text-pair input proof.', 'danger');
    }
    if (queue.nliPairRows === 0) {
        return actionState(
            'No NLI pairs',
            true,
            'blocked',
            `${formatCount(queue.ledgerRows)} ledger rows exist, but no premise/hypothesis pairs were planned.`,
            'quiet',
        );
    }
    const label = options.modelInitialized ? 'Run NLI' : 'Load + Run';
    return actionState(label, false, certificate.proof.modelExecution.status === 'passed' ? 'ready' : 'planned', 'ModernBERT can score the planned premise/hypothesis pairs.', 'ready');
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
        ledgerRows: 0,
        manualDecisionRows: 0,
        nliPairRows: 0,
        nliExcludedRows: 0,
        duplicatePairs: 0,
        judgedRows: 0,
        appliedRows: 0,
        topologyWrites: 0,
        nliEligibilityPercent: 0,
        categories: [],
        excludedReasons: [],
    };
}

function formatCount(value: number): string {
    return Math.max(0, Math.round(value || 0)).toLocaleString();
}

function reviewLedgerRows(snapshot: GraphRebuildSnapshot | null, raw: Record<string, unknown>): number {
    const rawTotal = numericField(raw, 0, 'totalReviewRows', 'reviewRows', 'total_review_rows', 'review_rows');
    if (rawTotal) return rawTotal;
    const rows = snapshot?.documentReviewSummary?.rows;
    if (rows) return new Set(rows.map((row) => row.id)).size;
    return snapshot?.counters.documentReviewRows || 0;
}

function manualReviewRows(snapshot: GraphRebuildSnapshot | null): number {
    const rows = snapshot?.documentReviewSummary?.rows;
    if (rows) {
        return rows.filter((row) => row.availableActions.some((action) => action.requiresUserIntent)).length;
    }
    return snapshot?.counters.documentReviewActionableRows || 0;
}

function excludedReasons(
    nliPairRows: number,
    duplicatePairs: number,
    nliExcludedRows: number,
): GraphReviewQueueExcludedReason[] {
    const reasons: GraphReviewQueueExcludedReason[] = [];
    if (nliExcludedRows > 0) {
        reasons.push({
            id: 'invalid_nli_pair',
            label: 'Excluded NLI pairs',
            count: nliExcludedRows,
            detail: 'These candidate pairs failed the explicit premise/hypothesis input contract.',
        });
    }
    if (duplicatePairs > 0) {
        reasons.push({
            id: 'duplicate_pair',
            label: 'Duplicate NLI pairs',
            count: duplicatePairs,
            detail: 'Repeated source-target-edge inputs were collapsed before classification.',
        });
    }
    if (nliPairRows === 0 && nliExcludedRows === 0 && duplicatePairs === 0) {
        reasons.push({
            id: 'empty_nli_plan',
            label: 'No planned NLI inputs',
            count: 0,
            detail: 'The review ledger is independent from NLI; no premise/hypothesis pairs were planned for this run.',
        });
    }
    return reasons;
}

function inventoryCategories(
    counts: Omit<GraphReviewQueueInventory, 'topologyWrites' | 'nliEligibilityPercent' | 'categories' | 'excludedReasons'>,
): GraphReviewInventoryCategory[] {
    return [
        category('review_ledger', 'System audit ledger', counts.ledgerRows, 'document_review', 'inspect'),
        category('manual_decision', 'Manual decisions', counts.manualDecisionRows, 'document_review', counts.manualDecisionRows ? 'manual_receipt' : 'none'),
        category('nli_pair', 'NLI pair inputs', counts.nliPairRows, 'review_adjudication', counts.nliPairRows ? 'run_nli' : 'none'),
        category('nli_excluded', 'Excluded NLI pairs', counts.nliExcludedRows, 'review_adjudication', 'inspect'),
        category('nli_duplicate', 'Duplicate NLI pairs', counts.duplicatePairs, 'review_adjudication', 'inspect'),
        category('nli_judgment', 'NLI judgments', counts.judgedRows, 'review_adjudication', 'inspect'),
        category('applied_judgment', 'Applied judgments', counts.appliedRows, 'review_adjudication', 'inspect'),
    ];
}

function category(
    id: GraphReviewInventoryCategoryId,
    label: string,
    rowCount: number,
    source: GraphReviewInventoryCategory['source'],
    action: GraphReviewInventoryCategory['action'],
): GraphReviewInventoryCategory {
    return { id, label, rowCount, source, action };
}

function proofCheck(status: GraphReviewProofState, detail: string): GraphReviewProofCheck {
    return { status, detail };
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
