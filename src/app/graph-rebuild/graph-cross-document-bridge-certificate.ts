import type { GraphRebuildChunkSemanticBridgeType } from './graph-rebuild-snapshot';

export const GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-cross-document-bridge-run-certificate/v1' as const;

export interface GraphCrossDocumentBridgePairCoverage {
    sourceDocumentId: string;
    targetDocumentId: string;
    generatedCandidates: number;
    eligibleCandidates: number;
    selectedCandidates: number;
    rejectedCandidates: number;
    selectedBridgeTypes: GraphRebuildChunkSemanticBridgeType[];
    coverageMillis: number;
}

export interface GraphCrossDocumentBridgeAuditRow {
    id: string;
    sourceDocumentId: string;
    targetDocumentId: string;
    sourceChunkId: string;
    targetChunkId: string;
    sourceExcerpt: string;
    targetExcerpt: string;
    bridgeType: GraphRebuildChunkSemanticBridgeType;
    claim: string;
    evidenceIds: string[];
    supportingEntityIds: string[];
    confidenceMillis: number;
    rejectionReason?: string;
    noTopologyCommit: boolean;
}

export interface GraphCrossDocumentBridgeRunCertificate {
    schemaVersion: typeof GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION;
    sourceDocumentIds: string[];
    generatedCandidates: number;
    eligibleCandidates: number;
    selectedCandidates: number;
    rejectedCandidates: number;
    pairCoverage: GraphCrossDocumentBridgePairCoverage[];
    rejectionCounts: Array<{ reason: string; count: number }>;
    selectedRows: GraphCrossDocumentBridgeAuditRow[];
    rejectedRows: GraphCrossDocumentBridgeAuditRow[];
    weakestRows: GraphCrossDocumentBridgeAuditRow[];
    noTopologyWrites: boolean;
    invariantReceipts: string[];
}

export function isGraphCrossDocumentBridgeRunCertificate(
    value: GraphCrossDocumentBridgeRunCertificate | null | undefined,
): value is GraphCrossDocumentBridgeRunCertificate {
    if (value?.schemaVersion !== GRAPH_CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION
        || !Array.isArray(value.sourceDocumentIds)
        || !Array.isArray(value.pairCoverage)
        || !Array.isArray(value.selectedRows)
        || !Array.isArray(value.rejectedRows)
        || !Array.isArray(value.weakestRows)
        || !Array.isArray(value.rejectionCounts)
        || !Array.isArray(value.invariantReceipts)) return false;
    const rows = [...value.selectedRows, ...value.rejectedRows, ...value.weakestRows];
    const counts = [value.generatedCandidates, value.eligibleCandidates,
        value.selectedCandidates, value.rejectedCandidates];
    const pairTotals = value.pairCoverage.reduce((totals, pair) => ({
        generated: totals.generated + pair.generatedCandidates,
        eligible: totals.eligible + pair.eligibleCandidates,
        selected: totals.selected + pair.selectedCandidates,
        rejected: totals.rejected + pair.rejectedCandidates,
    }), { generated: 0, eligible: 0, selected: 0, rejected: 0 });
    const rejectionTotal = value.rejectionCounts.reduce((total, row) => total + row.count, 0);
    return counts.every(isCount)
        && value.eligibleCandidates <= value.generatedCandidates
        && value.selectedCandidates <= value.eligibleCandidates
        && value.selectedCandidates + value.rejectedCandidates === value.generatedCandidates
        && value.selectedRows.length === value.selectedCandidates
        && pairTotals.generated === value.generatedCandidates
        && pairTotals.eligible === value.eligibleCandidates
        && pairTotals.selected === value.selectedCandidates
        && pairTotals.rejected === value.rejectedCandidates
        && rejectionTotal === value.rejectedCandidates
        && value.noTopologyWrites === true
        && value.invariantReceipts.includes('chunk_semantic_bridge_candidate:no_topology_commit')
        && rows.every((row) => row.noTopologyCommit === true
            && !!row.sourceDocumentId && !!row.targetDocumentId
            && !!row.sourceChunkId && !!row.targetChunkId
            && typeof row.sourceExcerpt === 'string'
            && typeof row.targetExcerpt === 'string')
        && value.pairCoverage.every((pair) => !!pair.sourceDocumentId
            && !!pair.targetDocumentId
            && [pair.generatedCandidates, pair.eligibleCandidates, pair.selectedCandidates,
                pair.rejectedCandidates, pair.coverageMillis].every(isCount)
            && pair.eligibleCandidates <= pair.generatedCandidates
            && pair.selectedCandidates <= pair.eligibleCandidates
            && pair.selectedCandidates + pair.rejectedCandidates === pair.generatedCandidates)
        && value.rejectionCounts.every((row) => !!row.reason && isCount(row.count));
}

function isCount(value: number): boolean {
    return Number.isSafeInteger(value) && value >= 0;
}
