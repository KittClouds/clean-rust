import type { GraphRebuildBuildTimings, GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION = 'phoenix-graph-promotion-verdict/v1' as const;

export type GraphPromotionVerdictStatus =
    | 'acceptable'
    | 'alreadyCommitted'
    | 'blocked'
    | 'deferred'
    | 'rejected';

export type GraphPromotionGateKind =
    | 'receipt'
    | 'evidence'
    | 'witnessCount'
    | 'contradiction'
    | 'temporalCausalFit'
    | 'nliFit'
    | 'userOverride'
    | 'rollback';

export type GraphPromotionGateStatus = 'pass' | 'block' | 'notRequired' | 'override';

export interface GraphPromotionVerdictGate {
    kind: GraphPromotionGateKind;
    status: GraphPromotionGateStatus;
    summary: string;
    scoreMillis?: number | null;
}

export interface GraphPromotionTruthDescriptor {
    subject?: string;
    predicate?: string;
    object?: string;
    [key: string]: unknown;
}

export interface GraphPromotionApplyPlan {
    operation?: string | null;
    predecessorCommitId?: string | null;
    rationale: string;
}

export interface GraphPromotionRollbackPlan {
    operation?: string | null;
    reversesCommitId?: string | null;
    availableNow: boolean;
    availableAfterCommit: boolean;
    rationale: string;
}

export interface GraphPromotionVerdictRow {
    id: string;
    receiptId: string;
    proposalId: string;
    family: string;
    truth: GraphPromotionTruthDescriptor;
    candidateStatus: string;
    outcome: string;
    status: GraphPromotionVerdictStatus;
    commitId?: string | null;
    evidenceRefs: string[];
    witnessCount: number;
    nliSupportMillis?: number | null;
    nliContradictionMillis?: number | null;
    userOverride?: string | null;
    deterministicScoreMillis?: number | null;
    applyPlan: GraphPromotionApplyPlan;
    rollbackPlan: GraphPromotionRollbackPlan;
    gates: GraphPromotionVerdictGate[];
    rationale: string;
}

export interface GraphPromotionVerdictAudit {
    total: number;
    acceptable: number;
    alreadyCommitted: number;
    blocked: number;
    deferred: number;
    rejected: number;
    rollbackAvailable: number;
    evidenceBlocked: number;
    contradictionBlocked: number;
    nliBlocked: number;
    userOverrides: number;
}

export interface GraphPromotionVerdictCertificate {
    schemaVersion: typeof GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION;
    source: string;
    noTopologyWrites: true;
    receiptCount: number;
    commitCount: number;
    audit: GraphPromotionVerdictAudit;
    rows: GraphPromotionVerdictRow[];
}

export interface NativePromotionVerdictOutput {
    schemaVersion: 'phoenix-graph-promotion-verdict-native-output/v1';
    source: 'rust';
    certificate: GraphPromotionVerdictCertificate;
    timing: {
        verdictBuildMicros: number;
        totalMicros: number;
    };
}

export function applyNativePromotionVerdictCertificate(
    snapshot: GraphRebuildSnapshot,
    certificate: GraphPromotionVerdictCertificate | null,
    timings?: GraphRebuildBuildTimings,
): void {
    snapshot.promotionVerdictCertificate = certificate || undefined;
    snapshot.counters = {
        ...snapshot.counters,
        promotionVerdictRows: certificate?.audit.total || 0,
        promotionVerdictAcceptable: certificate?.audit.acceptable || 0,
        promotionVerdictBlocked: certificate?.audit.blocked || 0,
        promotionVerdictAlreadyCommitted: certificate?.audit.alreadyCommitted || 0,
        promotionVerdictRollbackAvailable: certificate?.audit.rollbackAvailable || 0,
    };
    if (timings) {
        timings.nativePromotionVerdictRows = certificate?.audit.total || 0;
    }
}

export function isNativePromotionVerdictOutput(value: unknown): value is NativePromotionVerdictOutput {
    const record = objectRecord(value) as Partial<NativePromotionVerdictOutput> | null;
    return record?.schemaVersion === 'phoenix-graph-promotion-verdict-native-output/v1'
        && record.source === 'rust'
        && isGraphPromotionVerdictCertificate(record.certificate)
        && isFiniteNumber(record.timing?.verdictBuildMicros)
        && isFiniteNumber(record.timing?.totalMicros);
}

export function isGraphPromotionVerdictCertificate(
    value: unknown,
): value is GraphPromotionVerdictCertificate {
    const record = objectRecord(value) as Partial<GraphPromotionVerdictCertificate> | null;
    return record?.schemaVersion === GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION
        && typeof record.source === 'string'
        && record.noTopologyWrites === true
        && isNonNegativeNumber(record.receiptCount)
        && isNonNegativeNumber(record.commitCount)
        && isPromotionAudit(record.audit)
        && Array.isArray(record.rows)
        && record.rows.every(isPromotionVerdictRow);
}

function isPromotionAudit(value: unknown): value is GraphPromotionVerdictAudit {
    const record = objectRecord(value) as Partial<GraphPromotionVerdictAudit> | null;
    return !!record
        && isNonNegativeNumber(record.total)
        && isNonNegativeNumber(record.acceptable)
        && isNonNegativeNumber(record.alreadyCommitted)
        && isNonNegativeNumber(record.blocked)
        && isNonNegativeNumber(record.deferred)
        && isNonNegativeNumber(record.rejected)
        && isNonNegativeNumber(record.rollbackAvailable)
        && isNonNegativeNumber(record.evidenceBlocked)
        && isNonNegativeNumber(record.contradictionBlocked)
        && isNonNegativeNumber(record.nliBlocked)
        && isNonNegativeNumber(record.userOverrides);
}

function isPromotionVerdictRow(value: unknown): value is GraphPromotionVerdictRow {
    const record = objectRecord(value) as Partial<GraphPromotionVerdictRow> | null;
    return !!record
        && typeof record.id === 'string'
        && typeof record.receiptId === 'string'
        && typeof record.proposalId === 'string'
        && typeof record.family === 'string'
        && isPromotionStatus(record.status)
        && Array.isArray(record.evidenceRefs)
        && record.evidenceRefs.every((row) => typeof row === 'string')
        && isNonNegativeNumber(record.witnessCount)
        && Array.isArray(record.gates)
        && record.gates.every(isPromotionGate)
        && isPromotionPlan(record.applyPlan)
        && isPromotionRollbackPlan(record.rollbackPlan)
        && typeof record.rationale === 'string';
}

function isPromotionGate(value: unknown): value is GraphPromotionVerdictGate {
    const record = objectRecord(value) as Partial<GraphPromotionVerdictGate> | null;
    return !!record
        && typeof record.kind === 'string'
        && typeof record.status === 'string'
        && typeof record.summary === 'string';
}

function isPromotionPlan(value: unknown): value is GraphPromotionApplyPlan {
    const record = objectRecord(value) as Partial<GraphPromotionApplyPlan> | null;
    return !!record && typeof record.rationale === 'string';
}

function isPromotionRollbackPlan(value: unknown): value is GraphPromotionRollbackPlan {
    const record = objectRecord(value) as Partial<GraphPromotionRollbackPlan> | null;
    return !!record
        && typeof record.availableNow === 'boolean'
        && typeof record.availableAfterCommit === 'boolean'
        && typeof record.rationale === 'string';
}

function isPromotionStatus(value: unknown): value is GraphPromotionVerdictStatus {
    return value === 'acceptable'
        || value === 'alreadyCommitted'
        || value === 'blocked'
        || value === 'deferred'
        || value === 'rejected';
}

function objectRecord(value: unknown): Record<string, any> | null {
    return value && typeof value === 'object' ? value as Record<string, any> : null;
}

function isNonNegativeNumber(value: unknown): value is number {
    return isFiniteNumber(value) && value >= 0;
}

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}
