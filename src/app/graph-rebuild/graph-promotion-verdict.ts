import type {
    GraphRebuildBuildTimings,
    GraphRebuildLinkSuggestion,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

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

export type GraphPromotionTruthAtom =
    | {
        kind: 'edge';
        source_id: string;
        target_id: string;
        edge_type: string;
    }
    | {
        kind: 'vertex';
        vertex_id: string;
    };

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
    atom?: GraphPromotionTruthAtom;
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

export type GraphPromotionProposalStatus =
    | 'generated'
    | 'reviewedSupport'
    | 'reviewedContradiction'
    | 'deferred'
    | 'rejected';

export interface GraphPromotionProposalReceipt {
    schemaVersion: 1;
    receiptId: string;
    scopeKey: string;
    generation: number;
    createdAt: number;
    compilerPolicy: {
        compilerId: string;
        compilerVersion: string;
        policyId: string;
        policyVersion: string;
    };
    sourceGenerations: Array<{ sourceId: string; generation: number }>;
    modelId: string | null;
    proposals: GraphPromotionProposalObservation[];
}

export interface GraphPromotionProposalObservation {
    proposalId: string;
    atom: {
        kind: 'edge';
        source_id: string;
        target_id: string;
        edge_type: string;
    };
    family: string;
    sourceKind: string;
    targetKind: string;
    truth: { kind: 'semantic'; plane: 'worldState' };
    status: GraphPromotionProposalStatus;
    evidenceRefs: string[];
    features: number[];
    shadowScoreMillis: number | null;
}

const PROMOTION_PREVIEW_FEATURE_DIM = 16;

export function buildGraphPromotionPreviewReceipts(
    snapshot: GraphRebuildSnapshot,
): GraphPromotionProposalReceipt[] {
    const suggestions = (snapshot.graphAwareLinkSuggestions || [])
        .filter(isPromotionPreviewSuggestion)
        .slice()
        .sort(compareLinkSuggestions);
    if (!suggestions.length) return [];

    const generation = Math.max(1, Math.trunc(snapshot.builtAt || Date.now()));
    const proposals = new Map<string, GraphPromotionProposalObservation>();
    for (const suggestion of suggestions) {
        const sourceId = cleanId(suggestion.sourceEntityId);
        const targetId = cleanId(suggestion.targetEntityId);
        const edgeType = `semantic::${cleanId(suggestion.suggestedRelationType)}`;
        const atomKey = `${sourceId}\u0000${targetId}\u0000${edgeType}`;
        if (proposals.has(atomKey)) continue;
        proposals.set(atomKey, {
            proposalId: cleanId(suggestion.id),
            atom: { kind: 'edge', source_id: sourceId, target_id: targetId, edge_type: edgeType },
            family: cleanId(suggestion.kind),
            sourceKind: 'entity',
            targetKind: 'entity',
            truth: { kind: 'semantic', plane: 'worldState' },
            status: promotionStatusFor(suggestion),
            evidenceRefs: evidenceRefsFor(suggestion),
            features: promotionFeaturesFor(suggestion),
            shadowScoreMillis: scoreMillisFor(suggestion),
        });
    }
    const orderedProposals = Array.from(proposals.values());
    if (!orderedProposals.length) return [];

    const receiptHash = stablePreviewHash(snapshot, orderedProposals);
    return [{
        schemaVersion: 1,
        receiptId: `graph-proposal:atlas-preview:${receiptHash}`,
        scopeKey: cleanId(snapshot.scopeId || 'global'),
        generation,
        createdAt: generation,
        compilerPolicy: {
            compilerId: 'phoenix-ts-compatibility-bridge',
            compilerVersion: '1',
            policyId: 'graph-post-proposal:atlas-link-preview',
            policyVersion: '1',
        },
        sourceGenerations: [{
            sourceId: cleanId(snapshot.id || snapshot.scopeId || 'graph-rebuild-snapshot'),
            generation,
        }],
        modelId: null,
        proposals: orderedProposals,
    }];
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
        && (record.atom === undefined || isPromotionTruthAtom(record.atom))
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

function isPromotionTruthAtom(value: unknown): value is GraphPromotionTruthAtom {
    const record = objectRecord(value) as Partial<GraphPromotionTruthAtom> | null;
    if (!record || typeof record.kind !== 'string') return false;
    if (record.kind === 'edge') {
        return typeof (record as any).source_id === 'string'
            && typeof (record as any).target_id === 'string'
            && typeof (record as any).edge_type === 'string';
    }
    if (record.kind === 'vertex') {
        return typeof (record as any).vertex_id === 'string';
    }
    return false;
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

function isPromotionPreviewSuggestion(
    suggestion: GraphRebuildLinkSuggestion,
): boolean {
    return !!cleanId(suggestion.id)
        && !!cleanId(suggestion.sourceEntityId)
        && !!cleanId(suggestion.targetEntityId)
        && !!cleanId(suggestion.suggestedRelationType);
}

function compareLinkSuggestions(
    left: GraphRebuildLinkSuggestion,
    right: GraphRebuildLinkSuggestion,
): number {
    return cleanId(left.kind).localeCompare(cleanId(right.kind))
        || cleanId(left.suggestedRelationType).localeCompare(cleanId(right.suggestedRelationType))
        || cleanId(left.sourceEntityId).localeCompare(cleanId(right.sourceEntityId))
        || cleanId(left.targetEntityId).localeCompare(cleanId(right.targetEntityId))
        || cleanId(left.id).localeCompare(cleanId(right.id));
}

function promotionStatusFor(suggestion: GraphRebuildLinkSuggestion): GraphPromotionProposalStatus {
    return suggestion.status === 'confirmed' ? 'reviewedSupport' : 'reviewedSupport';
}

function evidenceRefsFor(suggestion: GraphRebuildLinkSuggestion): string[] {
    const seen = new Set<string>();
    const rows: string[] = [];
    for (const raw of suggestion.evidenceIds || []) {
        const value = cleanId(raw);
        if (!value || seen.has(value)) continue;
        seen.add(value);
        rows.push(value);
        if (rows.length >= 32) break;
    }
    return rows;
}

function promotionFeaturesFor(suggestion: GraphRebuildLinkSuggestion): number[] {
    const features = Array.from({ length: PROMOTION_PREVIEW_FEATURE_DIM }, () => 0);
    features[0] = scoreMillisFor(suggestion) || 0;
    features[1] = scaledScore(suggestion.confidence);
    features[5] = Math.min(1000, (suggestion.evidenceIds || []).length * 50);
    features[11] = suggestion.status === 'confirmed' ? 1000 : 750;
    return features;
}

function scoreMillisFor(suggestion: GraphRebuildLinkSuggestion): number | null {
    const raw = Number.isFinite(suggestion.rerankScore)
        ? suggestion.rerankScore
        : suggestion.confidence;
    const scaled = scaledScore(raw);
    return scaled > 0 ? scaled : null;
}

function scaledScore(value: unknown): number {
    return clampInt(Math.round((typeof value === 'number' && Number.isFinite(value) ? value : 0) * 1000), 0, 1000);
}

function stablePreviewHash(
    snapshot: GraphRebuildSnapshot,
    proposals: GraphPromotionProposalObservation[],
): string {
    const payload = [
        snapshot.id || '',
        snapshot.scopeId || '',
        String(snapshot.builtAt || ''),
        ...proposals.map((row) => [
            row.proposalId,
            row.atom.source_id,
            row.atom.target_id,
            row.atom.edge_type,
            row.evidenceRefs.join(','),
        ].join('|')),
    ].join('\n');
    let hash = 2166136261;
    for (let index = 0; index < payload.length; index += 1) {
        hash ^= payload.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

function cleanId(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function clampInt(value: number, min: number, max: number): number {
    if (!Number.isFinite(value)) return min;
    return Math.max(min, Math.min(max, value));
}
