import {
    GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
    GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION,
    GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
    type GraphMemoryGovernanceAction,
    type GraphMemoryGovernanceCandidate,
    type GraphMemoryGovernanceRetrievalPreviewRow,
    type GraphMemoryGovernanceRetrievalWeightingVariant,
    type GraphRebuildRelationship,
    type GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export const GRAPH_GOVERNANCE_RUN_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-governance-run-certificate/v1' as const;

const NEGATIVE_RELATION_TYPES = new Set(['opposes', 'threatens', 'betrays', 'rejects']);
const NEGATIVE_RELATION_POLICY = 'graph-rebuild-negative-cue-review-policy';
const PROTECTED_PIN_RATIONALE = 'audit:user_pinned';
const PROTECTED_PIN_SOURCE_RATIONALE = 'audit:pin_source:user_override';
const COMPRESSION_DOMINANCE_POLICY = 'memory_governance:compression_dominance_policy';
const SCORE_EPSILON = 0.001;

export interface GraphGovernanceRunCertificate {
    schemaVersion: typeof GRAPH_GOVERNANCE_RUN_CERTIFICATE_SCHEMA_VERSION;
    generatedAt: number;
    document: GraphGovernanceRunDocumentRef;
    timings: GraphGovernanceRunTimings;
    candidatesByAction: GraphGovernanceRunActionCounts;
    attentionLanes: GraphGovernanceRunAttentionLanes;
    noTopologyProof: GraphGovernanceRunNoTopologyProof;
    protectedMemoryProof: GraphGovernanceRunProtectedMemoryProof;
    compressionDominanceProof: GraphGovernanceRunCompressionDominanceProof;
    topRows: GraphGovernanceRunCandidateRow[];
    weakestRows: GraphGovernanceRunCandidateRow[];
    retrievalDeltas: GraphGovernanceRunRetrievalDeltas;
}

export interface GraphGovernanceRunDocumentRef {
    snapshotId: string;
    scopeKind: string;
    scopeId: string;
    noteIds: string[];
    builtAt: number;
    authorityContentHash?: string;
}

export interface GraphGovernanceRunTimings {
    totalMs?: number;
    snapshotBuildMs?: number;
    nativeMemoryGovernanceMs?: number;
    nativeMemoryGovernanceRustMicros?: number;
    nativeMemoryGovernanceRetrievalExperimentMs?: number;
    nativeMemoryGovernanceRetrievalExperimentRustMicros?: number;
    memoryGovernanceBuildMicros?: number;
}

export interface GraphGovernanceRunActionCounts {
    total: number;
    retain: number;
    attenuate: number;
    compress: number;
    quarantine: number;
    retire: number;
}

export interface GraphGovernanceRunAttentionLanes {
    totalAttentionRows: number;
    contradictionQuarantine: GraphGovernanceRunAttentionLane;
    supersessionAttenuation: GraphGovernanceRunAttentionLane;
    negativeRelationReview: GraphGovernanceRunAttentionLane;
}

export interface GraphGovernanceRunAttentionLane {
    count: number;
    percentOfCandidates: number;
    sampleRows: GraphGovernanceRunCandidateRow[];
}

export interface GraphGovernanceRunNoTopologyProof {
    passed: boolean;
    candidateRows: number;
    candidateOnlyRows: number;
    noTopologyCommitRows: number;
    commitPolicyRows: number;
    missingNoTopologyRationaleRows: number;
    retrievalExperimentReportOnly: boolean;
    retrievalRows: number;
    retrievalNoTopologyRows: number;
    violations: string[];
}

export interface GraphGovernanceRunProtectedMemoryProof {
    passed: boolean;
    protectedRows: number;
    userOverrideRows: number;
    retainRows: number;
    noTopologyCommitRows: number;
    sourceViolationRows: number;
    sampleRows: GraphGovernanceRunCandidateRow[];
    violations: string[];
}

export interface GraphGovernanceRunCompressionDominanceProof {
    passed: boolean;
    compressedRows: number;
    policyRows: number;
    boundedRows: number;
    maxPositiveDelta: number;
    maxAdjustedScore: number;
    sampleRows: GraphGovernanceRunRetrievalRow[];
    violations: string[];
}

export interface GraphGovernanceRunCandidateRow {
    id: string;
    action: GraphMemoryGovernanceAction | 'negative_relation';
    targetId: string;
    targetKind: string;
    reason: string;
    evidenceCount: number;
    confidence: number;
    supportingEntityIds: string[];
    signals: Array<{ label: string; value: number }>;
    noTopologyCommit: boolean;
}

export interface GraphGovernanceRunRetrievalDeltas {
    baselinePolicyId: string;
    variantCount: number;
    reportOnly: boolean;
    variants: GraphGovernanceRunRetrievalVariant[];
}

export interface GraphGovernanceRunRetrievalVariant {
    policyId: string;
    summary: {
        candidateCount: number;
        governedCount: number;
        changedRankCount: number;
        promotedCount: number;
        demotedCount: number;
    };
    meanAbsRankDeltaMillis: number;
    strongestBoosts: GraphGovernanceRunRetrievalRow[];
    strongestDemotions: GraphGovernanceRunRetrievalRow[];
}

export interface GraphGovernanceRunRetrievalRow {
    id: string;
    targetId: string;
    targetKind: string;
    originalRank: number;
    adjustedRank: number;
    scoreDelta: number;
    governanceAction?: GraphMemoryGovernanceAction;
    noTopologyCommit: boolean;
}

export function buildGovernanceRunCertificate(
    snapshot: GraphRebuildSnapshot,
    rowLimit = 8,
): GraphGovernanceRunCertificate {
    const candidates = snapshot.memoryGovernanceCandidates || [];
    const contradictionRows = candidates.filter(isContradictionCandidate).sort(confidenceDesc);
    const supersessionRows = candidates.filter(isSupersessionCandidate).sort(confidenceDesc);
    const negativeRows = (snapshot.relationships || []).filter(isNegativeReviewRelationship);
    const retrievalExperiment = snapshot.memoryGovernanceRetrievalExperiment;

    return {
        schemaVersion: GRAPH_GOVERNANCE_RUN_CERTIFICATE_SCHEMA_VERSION,
        generatedAt: Date.now(),
        document: {
            snapshotId: snapshot.id,
            scopeKind: snapshot.scopeKind,
            scopeId: snapshot.scopeId,
            noteIds: [...snapshot.noteIds],
            builtAt: snapshot.builtAt,
            authorityContentHash: snapshot.authorityContract?.contentHash,
        },
        timings: runTimings(snapshot),
        candidatesByAction: actionCounts(candidates),
        attentionLanes: {
            totalAttentionRows: contradictionRows.length + supersessionRows.length + negativeRows.length,
            contradictionQuarantine: lane(contradictionRows, candidates.length, rowLimit),
            supersessionAttenuation: lane(supersessionRows, candidates.length, rowLimit),
            negativeRelationReview: {
                count: negativeRows.length,
                percentOfCandidates: ratio(negativeRows.length, candidates.length),
                sampleRows: negativeRows
                    .slice()
                    .sort((left, right) => right.confidence - left.confidence || left.id.localeCompare(right.id))
                    .slice(0, rowLimit)
                    .map(negativeRelationRow),
            },
        },
        noTopologyProof: noTopologyProof(candidates, retrievalExperiment?.variants || []),
        protectedMemoryProof: protectedMemoryProof(candidates, rowLimit),
        compressionDominanceProof: compressionDominanceProof(retrievalExperiment?.variants || [], rowLimit),
        topRows: candidates.slice().sort(confidenceDesc).slice(0, rowLimit).map(candidateRow),
        weakestRows: candidates.slice().sort(confidenceAsc).slice(0, rowLimit).map(candidateRow),
        retrievalDeltas: retrievalDeltas(snapshot),
    };
}

function runTimings(snapshot: GraphRebuildSnapshot): GraphGovernanceRunTimings {
    const timings = snapshot.buildTimings;
    return {
        totalMs: timings?.totalMs,
        snapshotBuildMs: timings?.snapshotBuildMs,
        nativeMemoryGovernanceMs: timings?.nativeMemoryGovernanceMs,
        nativeMemoryGovernanceRustMicros: timings?.nativeMemoryGovernanceRustMicros,
        nativeMemoryGovernanceRetrievalExperimentMs: timings?.nativeMemoryGovernanceRetrievalExperimentMs,
        nativeMemoryGovernanceRetrievalExperimentRustMicros:
            timings?.nativeMemoryGovernanceRetrievalExperimentRustMicros,
        memoryGovernanceBuildMicros: snapshot.counters.memoryGovernanceBuildMicros,
    };
}

function actionCounts(rows: GraphMemoryGovernanceCandidate[]): GraphGovernanceRunActionCounts {
    return {
        total: rows.length,
        retain: countAction(rows, 'retain'),
        attenuate: countAction(rows, 'attenuate'),
        compress: countAction(rows, 'compress'),
        quarantine: countAction(rows, 'quarantine'),
        retire: countAction(rows, 'retire'),
    };
}

function lane(
    rows: GraphMemoryGovernanceCandidate[],
    total: number,
    limit: number,
): GraphGovernanceRunAttentionLane {
    return {
        count: rows.length,
        percentOfCandidates: ratio(rows.length, total),
        sampleRows: rows.slice(0, limit).map(candidateRow),
    };
}

function noTopologyProof(
    rows: GraphMemoryGovernanceCandidate[],
    variants: GraphMemoryGovernanceRetrievalWeightingVariant[],
): GraphGovernanceRunNoTopologyProof {
    const retrievalRows = variants.flatMap((variant) => variant.topRows || []);
    const violations: string[] = [];
    for (const row of rows) {
        if (row.schemaVersion !== GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION) violations.push(`${row.id}:schema`);
        if (row.status !== 'candidate') violations.push(`${row.id}:status`);
        if (row.commitPolicy !== GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY) violations.push(`${row.id}:commit_policy`);
        if (row.noTopologyCommit !== true) violations.push(`${row.id}:topology_write`);
        if (!row.rationale?.includes(GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)) {
            violations.push(`${row.id}:missing_no_topology_rationale`);
        }
    }
    for (const row of retrievalRows) {
        if (row.noTopologyCommit !== true) violations.push(`${row.id}:retrieval_topology_write`);
    }
    return {
        passed: violations.length === 0,
        candidateRows: rows.length,
        candidateOnlyRows: rows.filter((row) => row.status === 'candidate').length,
        noTopologyCommitRows: rows.filter((row) => row.noTopologyCommit === true).length,
        commitPolicyRows: rows.filter((row) => row.commitPolicy === GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY).length,
        missingNoTopologyRationaleRows: rows.filter((row) =>
            !row.rationale?.includes(GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)).length,
        retrievalExperimentReportOnly: retrievalRows.every((row) => row.noTopologyCommit === true),
        retrievalRows: retrievalRows.length,
        retrievalNoTopologyRows: retrievalRows.filter((row) => row.noTopologyCommit === true).length,
        violations,
    };
}

function protectedMemoryProof(
    rows: GraphMemoryGovernanceCandidate[],
    limit: number,
): GraphGovernanceRunProtectedMemoryProof {
    const protectedRows = rows.filter(isProtectedMemoryCandidate);
    const violations: string[] = [];
    for (const row of protectedRows) {
        if (row.status !== 'candidate') violations.push(`${row.id}:status`);
        if (row.action !== 'retain') violations.push(`${row.id}:not_retain`);
        if (row.noTopologyCommit !== true) violations.push(`${row.id}:topology_write`);
        if (row.commitPolicy !== GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY) {
            violations.push(`${row.id}:commit_policy`);
        }
        if (row.signals.userPinned !== true) violations.push(`${row.id}:missing_user_pinned_signal`);
        if (!row.rationale?.includes(PROTECTED_PIN_RATIONALE)) {
            violations.push(`${row.id}:missing_pin_rationale`);
        }
        if (!row.rationale?.includes(PROTECTED_PIN_SOURCE_RATIONALE)) {
            violations.push(`${row.id}:missing_user_override_source`);
        }
    }
    return {
        passed: violations.length === 0,
        protectedRows: protectedRows.length,
        userOverrideRows: protectedRows.filter((row) =>
            row.rationale?.includes(PROTECTED_PIN_SOURCE_RATIONALE)).length,
        retainRows: protectedRows.filter((row) => row.action === 'retain').length,
        noTopologyCommitRows: protectedRows.filter((row) => row.noTopologyCommit === true).length,
        sourceViolationRows: protectedRows.filter((row) =>
            !row.rationale?.includes(PROTECTED_PIN_SOURCE_RATIONALE)).length,
        sampleRows: protectedRows.slice().sort(confidenceDesc).slice(0, limit).map(candidateRow),
        violations,
    };
}

function compressionDominanceProof(
    variants: GraphMemoryGovernanceRetrievalWeightingVariant[],
    limit: number,
): GraphGovernanceRunCompressionDominanceProof {
    const rows: GraphMemoryGovernanceRetrievalPreviewRow[] = [];
    const violations: string[] = [];
    let policyRows = 0;
    let boundedRows = 0;

    for (const variant of variants) {
        for (const row of variant.topRows || []) {
            if (row.governanceAction !== 'compress') continue;
            rows.push(row);
            const hasPolicy = row.rationale?.includes(COMPRESSION_DOMINANCE_POLICY);
            if (hasPolicy) policyRows += 1;
            else violations.push(`${row.id}:missing_compression_policy`);

            const maxDelta = variant.policy.compressMaxBoost ?? Number.POSITIVE_INFINITY;
            const scoreCeiling = Math.max(row.originalScore, variant.policy.compressScoreCeiling ?? 1);
            const boundedByDelta = row.scoreDelta <= maxDelta + SCORE_EPSILON;
            const boundedByCeiling = row.adjustedScore <= scoreCeiling + SCORE_EPSILON;
            if (boundedByDelta && boundedByCeiling) boundedRows += 1;
            if (!boundedByDelta) violations.push(`${row.id}:compress_boost_exceeds_cap`);
            if (!boundedByCeiling) violations.push(`${row.id}:compress_score_exceeds_ceiling`);
        }
    }

    return {
        passed: violations.length === 0,
        compressedRows: rows.length,
        policyRows,
        boundedRows,
        maxPositiveDelta: roundMetric(Math.max(0, ...rows.map((row) => row.scoreDelta))),
        maxAdjustedScore: roundMetric(Math.max(0, ...rows.map((row) => row.adjustedScore))),
        sampleRows: rows.slice().sort(scoreDeltaDesc).slice(0, limit).map(retrievalRow),
        violations,
    };
}

function retrievalDeltas(snapshot: GraphRebuildSnapshot): GraphGovernanceRunRetrievalDeltas {
    const experiment = snapshot.memoryGovernanceRetrievalExperiment;
    const variants = experiment?.variants || [];
    return {
        baselinePolicyId: experiment?.baselinePolicyId || '',
        variantCount: variants.length,
        reportOnly: experiment?.schemaVersion === GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION
            && experiment.noTopologyCommit === true,
        variants: variants.map(retrievalVariant),
    };
}

function retrievalVariant(
    variant: GraphMemoryGovernanceRetrievalWeightingVariant,
): GraphGovernanceRunRetrievalVariant {
    const rows = variant.topRows || [];
    return {
        policyId: variant.policy.id,
        summary: {
            candidateCount: variant.summary.candidateCount,
            governedCount: variant.summary.governedCount,
            changedRankCount: variant.summary.changedRankCount,
            promotedCount: variant.summary.promotedCount,
            demotedCount: variant.summary.demotedCount,
        },
        meanAbsRankDeltaMillis: variant.meanAbsRankDeltaMillis,
        strongestBoosts: rows.slice().sort(scoreDeltaDesc).slice(0, 5).map(retrievalRow),
        strongestDemotions: rows.slice().sort(scoreDeltaAsc).slice(0, 5).map(retrievalRow),
    };
}

function candidateRow(row: GraphMemoryGovernanceCandidate): GraphGovernanceRunCandidateRow {
    return {
        id: row.id,
        action: row.action,
        targetId: row.targetId,
        targetKind: row.targetKind,
        reason: row.reason,
        evidenceCount: row.evidenceIds.length,
        confidence: row.confidence,
        supportingEntityIds: row.supportingEntityIds.slice(0, 6),
        signals: topSignals(row),
        noTopologyCommit: row.noTopologyCommit === true,
    };
}

function negativeRelationRow(row: GraphRebuildRelationship): GraphGovernanceRunCandidateRow {
    return {
        id: row.id,
        action: 'negative_relation',
        targetId: `${row.sourceEntityId}->${row.targetEntityId}`,
        targetKind: row.relationType,
        reason: row.rationale || 'negative relation review candidate',
        evidenceCount: row.evidenceAnchorIds.length + row.decisionEvidence.length,
        confidence: row.confidence,
        supportingEntityIds: [row.sourceEntityId, row.targetEntityId],
        signals: [],
        noTopologyCommit: row.status === 'review',
    };
}

function retrievalRow(row: GraphMemoryGovernanceRetrievalPreviewRow): GraphGovernanceRunRetrievalRow {
    return {
        id: row.id,
        targetId: row.targetId,
        targetKind: row.targetKind,
        originalRank: row.originalRank,
        adjustedRank: row.adjustedRank,
        scoreDelta: row.scoreDelta,
        governanceAction: row.governanceAction,
        noTopologyCommit: row.noTopologyCommit === true,
    };
}

function isContradictionCandidate(row: GraphMemoryGovernanceCandidate): boolean {
    return row.action === 'quarantine'
        && (row.reason.includes('contradict')
            || row.signals.contradictionRisk > 0
            || row.rationale.some((line) => line.includes('contradict')));
}

function isSupersessionCandidate(row: GraphMemoryGovernanceCandidate): boolean {
    return row.action === 'attenuate'
        && (row.reason.includes('superseded')
            || row.signals.age > 0
            || row.rationale.some((line) => line.includes('supersession') || line.includes('superseded')));
}

function isNegativeReviewRelationship(row: GraphRebuildRelationship): boolean {
    return row.status === 'review'
        && (NEGATIVE_RELATION_TYPES.has(row.relationType) || row.adjudicationSource === NEGATIVE_RELATION_POLICY);
}

function isProtectedMemoryCandidate(row: GraphMemoryGovernanceCandidate): boolean {
    return row.signals.userPinned === true
        || row.reason === 'target_user_pinned_memory'
        || row.rationale?.includes(PROTECTED_PIN_RATIONALE);
}

function topSignals(row: GraphMemoryGovernanceCandidate): Array<{ label: string; value: number }> {
    const signals: Array<[string, number]> = [
        ['salience', row.signals.narrativeSalience],
        ['evidence', row.signals.evidenceStrength],
        ['causal', row.signals.causalImportance],
        ['utility', row.signals.retrievalUtility],
        ['redundancy', row.signals.redundancy],
        ['contradiction', row.signals.contradictionRisk],
        ['age', row.signals.age],
    ];
    return signals
        .filter((entry) => entry[1] > 0.005)
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .slice(0, 4)
        .map(([label, value]) => ({ label, value }));
}

function countAction(rows: GraphMemoryGovernanceCandidate[], action: GraphMemoryGovernanceAction): number {
    return rows.filter((row) => row.action === action).length;
}

function confidenceDesc(left: GraphMemoryGovernanceCandidate, right: GraphMemoryGovernanceCandidate): number {
    return right.confidence - left.confidence || left.id.localeCompare(right.id);
}

function confidenceAsc(left: GraphMemoryGovernanceCandidate, right: GraphMemoryGovernanceCandidate): number {
    return left.confidence - right.confidence || left.id.localeCompare(right.id);
}

function scoreDeltaDesc(left: GraphMemoryGovernanceRetrievalPreviewRow, right: GraphMemoryGovernanceRetrievalPreviewRow): number {
    return right.scoreDelta - left.scoreDelta || left.id.localeCompare(right.id);
}

function scoreDeltaAsc(left: GraphMemoryGovernanceRetrievalPreviewRow, right: GraphMemoryGovernanceRetrievalPreviewRow): number {
    return left.scoreDelta - right.scoreDelta || left.id.localeCompare(right.id);
}

function ratio(count: number, total: number): number {
    return total > 0 ? Math.round((count / total) * 1_000) / 1_000 : 0;
}

function roundMetric(value: number): number {
    return Math.round(value * 1_000) / 1_000;
}
