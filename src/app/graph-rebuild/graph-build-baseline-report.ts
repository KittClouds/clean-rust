import type { GraphIndexRunReceipt, GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_BUILD_BASELINE_CERTIFICATE_SCHEMA_VERSION =
    'phoenix-graph-build-baseline-certificate/v2' as const;
export const GRAPH_BUILD_WARM_TARGET_P50_MS = 1_000;
export const GRAPH_BUILD_WARM_CEILING_P95_MS = 3_000;

export type GraphBuildBaselineLane = 'cold_force' | 'warm_force' | 'delta';

export interface GraphBuildBaselineRunRow {
    lane: GraphBuildBaselineLane;
    iteration: number;
    wallMs: number;
    receiptSettleMs: number;
    snapshotId: string;
    authorityHash: string;
    identityHash: string;
    nodes: number;
    edges: number;
    targets: number;
    chunks: number;
    anchors: number;
    acceptedRelationships: number;
    interactiveIdentityReused: number;
    storeDocuments: number;
    writtenContentBlobs: number;
    reusedContentBlobs: number;
    snapshotBuildMs: number;
    snapshotPersistMs: number;
    snapshotCpuMs: number;
    snapshotAnchorsMs: number;
    snapshotFactsMs: number;
    snapshotCompatibilityViewsMs: number;
    snapshotTargetsMs: number;
    snapshotPostProcessMs: number;
    snapshotEmbeddingPostProcessMs: number;
    snapshotEmbeddingSignaturesMs: number;
    snapshotEmbeddingPairPlanMs: number;
    snapshotEmbeddingNeighborsMs: number;
    snapshotEmbeddingClustersMs: number;
    snapshotEmbeddingRowsEdgesMs: number;
    snapshotGraphAwareLinksMs: number;
    snapshotEntityLinkingMs: number;
    snapshotAssemblyMs: number;
    snapshotSemanticTasksMs: number;
    snapshotSemanticCandidatesMs: number;
    snapshotManifoldSpecializationMs: number;
    snapshotSemanticRerankMs: number;
    snapshotSemanticAdjudicationMs: number;
    snapshotSemanticEvalLedgerMs: number;
    snapshotSemanticLedgersMs: number;
    snapshotSemanticIndexBuilds: number;
    snapshotSemanticIndexEntries: number;
    snapshotSemanticAvoidedIndexBuilds: number;
    snapshotSemanticAvoidedIndexEntries: number;
    packetConstructionMs: number;
    authoritySealMs: number;
    nativeAnalysisRustMicros: number;
    nativeGraphRunArenaReused: number;
    nativeGraphRunArenaResidentBytes: number;
    nativeGraphRunArenaActiveLeases: number;
    nativeGraphRunPageProjectionMicros: number;
    nativeGraphRunDetailRows: number;
    nativeGraphRunReturnedDetailRows: number;
    nativeGraphRunPersistMs: number;
    nativeGraphRunChangedSections: number;
    nativeGraphRunReusedSections: number;
    nativeGraphRunEncodedSections: number;
    nativeGraphRunCompressedSections: number;
    nativeGraphRunRawBytesWritten: number;
    nativeGraphRunCompressedBytesWritten: number;
    transportCalls: number;
    transportTotalMs: number;
    transportMaxMs: number;
    transportRequestBytes: number;
    transportResponseBytes: number;
    transportRequestBytesMeasuredCalls: number;
    transportRequestBytesUnavailableCalls: number;
    transportResponseBytesMeasuredCalls: number;
    transportResponseBytesUnavailableCalls: number;
    transportEncodeMs: number;
    transportDecodeMs: number;
    transportEncodeTimingUnavailableCalls: number;
    transportDecodeTimingUnavailableCalls: number;
    transportOffenders: string;
    noTopologyWrites: boolean;
}

export interface GraphBuildBaselineLaneSummary {
    runs: number;
    wallP50Ms: number;
    wallP95Ms: number;
    receiptSettleP50Ms: number;
    receiptSettleP95Ms: number;
    transportP50Ms: number;
    transportP95Ms: number;
    requestBytesP50: number;
    responseBytesP50: number;
    requestBytesUnavailableCallsTotal: number;
    responseBytesUnavailableCallsTotal: number;
    encodeP50Ms: number;
    decodeP50Ms: number;
    encodeTimingUnavailableCallsTotal: number;
    decodeTimingUnavailableCallsTotal: number;
    callsP50: number;
    interactiveIdentityReusedTotal: number;
    semanticLedgersP50Ms: number;
    semanticTasksP50Ms: number;
    semanticCandidatesP50Ms: number;
    manifoldSpecializationP50Ms: number;
    semanticRerankP50Ms: number;
    semanticAdjudicationP50Ms: number;
    semanticEvalLedgerP50Ms: number;
    semanticIndexBuildsP50: number;
    semanticIndexEntriesP50: number;
    semanticAvoidedIndexBuildsP50: number;
    semanticAvoidedIndexEntriesP50: number;
    nativeGraphRunArenaReusedTotal: number;
    nativeGraphRunArenaResidentBytesP50: number;
    nativeGraphRunPageProjectionP50Micros: number;
    nativeGraphRunReturnedDetailRowsP50: number;
    nativeGraphRunPersistP50Ms: number;
    nativeGraphRunPersistP95Ms: number;
    nativeGraphRunChangedSectionsTotal: number;
    nativeGraphRunReusedSectionsTotal: number;
    nativeGraphRunEncodedSectionsTotal: number;
    nativeGraphRunCompressedSectionsTotal: number;
    storeDocumentsTotal: number;
    writtenContentBlobsTotal: number;
    reusedContentBlobsTotal: number;
}

export interface GraphBuildBaselineCertificate {
    schemaVersion: typeof GRAPH_BUILD_BASELINE_CERTIFICATE_SCHEMA_VERSION;
    generatedAt: string;
    scopeId: string;
    documents: Array<{ title: string; chars: number; sha256: string }>;
    model: { embeddingModelId: string; dimension: string; nliModelId: string };
    runs: GraphBuildBaselineRunRow[];
    summary: Record<GraphBuildBaselineLane, GraphBuildBaselineLaneSummary>;
    parity: {
        exactIdentity: boolean;
        exactAuthority: boolean;
        exactCounts: boolean;
        noTopologyWrites: boolean;
        mismatchedRuns: string[];
    };
    performanceGate: {
        targetP50Ms: number;
        ceilingP95Ms: number;
        warmPassed: boolean;
        deltaPassed: boolean;
        passed: boolean;
    };
    cleanup: { notesDeleted: number; scopedDocumentsDeleted: number };
}

export async function graphBuildIdentityHash(snapshot: GraphRebuildSnapshot): Promise<string> {
    const continuity = snapshot.storyContinuity;
    const identity = {
        nodes: identityRows(snapshot.nodes),
        edges: identityRows(snapshot.edges),
        targets: identityRows(snapshot.embeddingTargets),
        bridges: identityRows(snapshot.chunkSemanticBridges || []),
        continuity: identityRows([
            ...(continuity?.events || []),
            ...(continuity?.boundaryReceipts || []),
            ...(continuity?.episodes || []),
            ...(continuity?.temporalCandidates || []),
            ...(continuity?.stateIntervals || []),
            ...(continuity?.causalCandidates || []),
            ...(continuity?.episodeConnections || []),
            ...(continuity?.conflicts || []),
        ]),
        governance: identityRows(snapshot.memoryGovernanceCandidates || []),
        promotion: promotionIdentityRows(snapshot.promotionVerdictCertificate?.rows || []),
    };
    return sha256(JSON.stringify(identity));
}

export function graphBuildRunRow(
    lane: GraphBuildBaselineLane,
    iteration: number,
    wallMs: number,
    receiptSettleMs: number,
    receipt: GraphIndexRunReceipt,
    snapshot: GraphRebuildSnapshot,
    identityHash: string,
): GraphBuildBaselineRunRow {
    const timing = snapshot.buildTimings;
    const transport = receipt.stageReceipts.find((stage) => stage.id === 'transportOps');
    const identityReuse = receipt.stageReceipts.find((stage) => stage.id === 'interactiveIdentityReuse');
    const transportCounters = transport?.counters || {};
    return {
        lane,
        iteration,
        wallMs: round(wallMs),
        receiptSettleMs: round(receiptSettleMs),
        snapshotId: snapshot.id,
        authorityHash: snapshot.authorityContract?.contentHash || '',
        identityHash,
        nodes: snapshot.counters.nodes || 0,
        edges: snapshot.counters.edges || 0,
        targets: snapshot.counters.embeddingTargets || 0,
        chunks: snapshot.counters.chunks || 0,
        anchors: snapshot.counters.acceptedAnchors || 0,
        acceptedRelationships: snapshot.counters.acceptedRelationships || 0,
        interactiveIdentityReused: identityReuse?.counters['identityMatched'] || 0,
        storeDocuments: timing?.snapshotStoreDocuments || 0,
        writtenContentBlobs: timing?.snapshotWrittenContentBlobs || 0,
        reusedContentBlobs: timing?.snapshotReusedContentBlobs || 0,
        snapshotBuildMs: timing?.snapshotBuildMs || 0,
        snapshotPersistMs: timing?.snapshotPersistMs || 0,
        snapshotCpuMs: Math.max(0, (timing?.snapshotBuildMs || 0)
            + (timing?.authorityAssertMs || 0)
            + (timing?.authoritySealMs || 0)),
        snapshotAnchorsMs: timing?.snapshotAnchorsMs || 0,
        snapshotFactsMs: timing?.snapshotFactsMs || 0,
        snapshotCompatibilityViewsMs: timing?.snapshotCompatibilityViewsMs || 0,
        snapshotTargetsMs: timing?.snapshotTargetsMs || 0,
        snapshotPostProcessMs: timing?.snapshotPostProcessMs || 0,
        snapshotEmbeddingPostProcessMs: timing?.snapshotEmbeddingPostProcessMs || 0,
        snapshotEmbeddingSignaturesMs: timing?.snapshotEmbeddingSignaturesMs || 0,
        snapshotEmbeddingPairPlanMs: timing?.snapshotEmbeddingPairPlanMs || 0,
        snapshotEmbeddingNeighborsMs: timing?.snapshotEmbeddingNeighborsMs || 0,
        snapshotEmbeddingClustersMs: timing?.snapshotEmbeddingClustersMs || 0,
        snapshotEmbeddingRowsEdgesMs: timing?.snapshotEmbeddingRowsEdgesMs || 0,
        snapshotGraphAwareLinksMs: timing?.snapshotGraphAwareLinksMs || 0,
        snapshotEntityLinkingMs: timing?.snapshotEntityLinkingMs || 0,
        snapshotAssemblyMs: timing?.snapshotAssemblyMs || 0,
        snapshotSemanticTasksMs: timing?.snapshotSemanticTasksMs || 0,
        snapshotSemanticCandidatesMs: timing?.snapshotSemanticCandidatesMs || 0,
        snapshotManifoldSpecializationMs: timing?.snapshotManifoldSpecializationMs || 0,
        snapshotSemanticRerankMs: timing?.snapshotSemanticRerankMs || 0,
        snapshotSemanticAdjudicationMs: timing?.snapshotSemanticAdjudicationMs || 0,
        snapshotSemanticEvalLedgerMs: timing?.snapshotSemanticEvalLedgerMs || 0,
        snapshotSemanticLedgersMs: timing?.snapshotSemanticLedgersMs || 0,
        snapshotSemanticIndexBuilds: timing?.snapshotSemanticIndexBuilds || 0,
        snapshotSemanticIndexEntries: timing?.snapshotSemanticIndexEntries || 0,
        snapshotSemanticAvoidedIndexBuilds: timing?.snapshotSemanticAvoidedIndexBuilds || 0,
        snapshotSemanticAvoidedIndexEntries: timing?.snapshotSemanticAvoidedIndexEntries || 0,
        packetConstructionMs: timing?.packetConstructionMs || 0,
        authoritySealMs: timing?.authoritySealMs || 0,
        nativeAnalysisRustMicros: timing?.nativeSnapshotAnalysisRustMicros || 0,
        nativeGraphRunArenaReused: timing?.nativeGraphRunArenaReused || 0,
        nativeGraphRunArenaResidentBytes: timing?.nativeGraphRunArenaResidentBytes || 0,
        nativeGraphRunArenaActiveLeases: timing?.nativeGraphRunArenaActiveLeases || 0,
        nativeGraphRunPageProjectionMicros: timing?.nativeGraphRunPageProjectionMicros || 0,
        nativeGraphRunDetailRows: timing?.nativeGraphRunDetailRows || 0,
        nativeGraphRunReturnedDetailRows: timing?.nativeGraphRunReturnedDetailRows || 0,
        nativeGraphRunPersistMs: timing?.nativeGraphRunPersistMs || 0,
        nativeGraphRunChangedSections: timing?.nativeGraphRunChangedSections || 0,
        nativeGraphRunReusedSections: timing?.nativeGraphRunReusedSections || 0,
        nativeGraphRunEncodedSections: timing?.nativeGraphRunEncodedSections || 0,
        nativeGraphRunCompressedSections: timing?.nativeGraphRunCompressedSections || 0,
        nativeGraphRunRawBytesWritten: timing?.nativeGraphRunRawBytesWritten || 0,
        nativeGraphRunCompressedBytesWritten: timing?.nativeGraphRunCompressedBytesWritten || 0,
        transportCalls: transportCounters['transportCalls'] || 0,
        transportTotalMs: transportCounters['transportTotalMs'] || 0,
        transportMaxMs: transportCounters['transportMaxMs'] || 0,
        transportRequestBytes: transportCounters['transportRequestBytes'] || 0,
        transportResponseBytes: transportCounters['transportResponseBytes'] || 0,
        transportRequestBytesMeasuredCalls: transportCounters['transportRequestBytesMeasuredCalls'] || 0,
        transportRequestBytesUnavailableCalls: transportCounters['transportRequestBytesUnavailableCalls'] || 0,
        transportResponseBytesMeasuredCalls: transportCounters['transportResponseBytesMeasuredCalls'] || 0,
        transportResponseBytesUnavailableCalls: transportCounters['transportResponseBytesUnavailableCalls'] || 0,
        transportEncodeMs: transportCounters['transportEncodeMs'] || 0,
        transportDecodeMs: transportCounters['transportDecodeMs'] || 0,
        transportEncodeTimingUnavailableCalls: transportCounters['transportEncodeTimingUnavailableCalls'] || 0,
        transportDecodeTimingUnavailableCalls: transportCounters['transportDecodeTimingUnavailableCalls'] || 0,
        transportOffenders: transport?.message || '',
        noTopologyWrites: graphBuildNoTopologyProof(snapshot),
    };
}

export function summarizeGraphBuildLane(rows: GraphBuildBaselineRunRow[]): GraphBuildBaselineLaneSummary {
    return {
        runs: rows.length,
        wallP50Ms: percentile(rows.map((row) => row.wallMs), 0.5),
        wallP95Ms: percentile(rows.map((row) => row.wallMs), 0.95),
        receiptSettleP50Ms: percentile(rows.map((row) => row.receiptSettleMs), 0.5),
        receiptSettleP95Ms: percentile(rows.map((row) => row.receiptSettleMs), 0.95),
        transportP50Ms: percentile(rows.map((row) => row.transportTotalMs), 0.5),
        transportP95Ms: percentile(rows.map((row) => row.transportTotalMs), 0.95),
        requestBytesP50: percentile(rows.map((row) => row.transportRequestBytes), 0.5),
        responseBytesP50: percentile(rows.map((row) => row.transportResponseBytes), 0.5),
        requestBytesUnavailableCallsTotal: sum(rows, (row) => row.transportRequestBytesUnavailableCalls),
        responseBytesUnavailableCallsTotal: sum(rows, (row) => row.transportResponseBytesUnavailableCalls),
        encodeP50Ms: percentile(rows.map((row) => row.transportEncodeMs), 0.5),
        decodeP50Ms: percentile(rows.map((row) => row.transportDecodeMs), 0.5),
        encodeTimingUnavailableCallsTotal: sum(rows, (row) => row.transportEncodeTimingUnavailableCalls),
        decodeTimingUnavailableCallsTotal: sum(rows, (row) => row.transportDecodeTimingUnavailableCalls),
        callsP50: percentile(rows.map((row) => row.transportCalls), 0.5),
        interactiveIdentityReusedTotal: sum(rows, (row) => row.interactiveIdentityReused),
        semanticLedgersP50Ms: percentile(rows.map((row) => row.snapshotSemanticLedgersMs), 0.5),
        semanticTasksP50Ms: percentile(rows.map((row) => row.snapshotSemanticTasksMs), 0.5),
        semanticCandidatesP50Ms: percentile(rows.map((row) => row.snapshotSemanticCandidatesMs), 0.5),
        manifoldSpecializationP50Ms: percentile(
            rows.map((row) => row.snapshotManifoldSpecializationMs),
            0.5,
        ),
        semanticRerankP50Ms: percentile(rows.map((row) => row.snapshotSemanticRerankMs), 0.5),
        semanticAdjudicationP50Ms: percentile(rows.map((row) => row.snapshotSemanticAdjudicationMs), 0.5),
        semanticEvalLedgerP50Ms: percentile(rows.map((row) => row.snapshotSemanticEvalLedgerMs), 0.5),
        semanticIndexBuildsP50: percentile(rows.map((row) => row.snapshotSemanticIndexBuilds), 0.5),
        semanticIndexEntriesP50: percentile(rows.map((row) => row.snapshotSemanticIndexEntries), 0.5),
        semanticAvoidedIndexBuildsP50: percentile(
            rows.map((row) => row.snapshotSemanticAvoidedIndexBuilds),
            0.5,
        ),
        semanticAvoidedIndexEntriesP50: percentile(
            rows.map((row) => row.snapshotSemanticAvoidedIndexEntries),
            0.5,
        ),
        nativeGraphRunArenaReusedTotal: sum(rows, (row) => row.nativeGraphRunArenaReused),
        nativeGraphRunArenaResidentBytesP50: percentile(
            rows.map((row) => row.nativeGraphRunArenaResidentBytes),
            0.5,
        ),
        nativeGraphRunPageProjectionP50Micros: percentile(
            rows.map((row) => row.nativeGraphRunPageProjectionMicros),
            0.5,
        ),
        nativeGraphRunReturnedDetailRowsP50: percentile(
            rows.map((row) => row.nativeGraphRunReturnedDetailRows),
            0.5,
        ),
        nativeGraphRunPersistP50Ms: percentile(rows.map((row) => row.nativeGraphRunPersistMs), 0.5),
        nativeGraphRunPersistP95Ms: percentile(rows.map((row) => row.nativeGraphRunPersistMs), 0.95),
        nativeGraphRunChangedSectionsTotal: sum(rows, (row) => row.nativeGraphRunChangedSections),
        nativeGraphRunReusedSectionsTotal: sum(rows, (row) => row.nativeGraphRunReusedSections),
        nativeGraphRunEncodedSectionsTotal: sum(rows, (row) => row.nativeGraphRunEncodedSections),
        nativeGraphRunCompressedSectionsTotal: sum(rows, (row) => row.nativeGraphRunCompressedSections),
        storeDocumentsTotal: sum(rows, (row) => row.storeDocuments),
        writtenContentBlobsTotal: sum(rows, (row) => row.writtenContentBlobs),
        reusedContentBlobsTotal: sum(rows, (row) => row.reusedContentBlobs),
    };
}

export function graphBuildPerformanceGate(
    warm: GraphBuildBaselineLaneSummary,
    delta: GraphBuildBaselineLaneSummary,
): GraphBuildBaselineCertificate['performanceGate'] {
    const passes = (lane: GraphBuildBaselineLaneSummary) =>
        lane.wallP50Ms <= GRAPH_BUILD_WARM_TARGET_P50_MS
        && lane.wallP95Ms <= GRAPH_BUILD_WARM_CEILING_P95_MS;
    const warmPassed = passes(warm);
    const deltaPassed = passes(delta);
    return {
        targetP50Ms: GRAPH_BUILD_WARM_TARGET_P50_MS,
        ceilingP95Ms: GRAPH_BUILD_WARM_CEILING_P95_MS,
        warmPassed,
        deltaPassed,
        passed: warmPassed && deltaPassed,
    };
}

export function graphBuildParity(rows: GraphBuildBaselineRunRow[]): GraphBuildBaselineCertificate['parity'] {
    const baseline = rows[0];
    if (!baseline) {
        return {
            exactIdentity: false,
            exactAuthority: false,
            exactCounts: false,
            noTopologyWrites: false,
            mismatchedRuns: ['missing_baseline'],
        };
    }
    const mismatchedRuns: string[] = [];
    let exactIdentity = true;
    let exactAuthority = true;
    let exactCounts = true;
    for (const row of rows) {
        const key = `${row.lane}:${row.iteration}`;
        if (row.identityHash !== baseline.identityHash) {
            exactIdentity = false;
            mismatchedRuns.push(`${key}:identity`);
        }
        if (row.authorityHash !== baseline.authorityHash) {
            exactAuthority = false;
            mismatchedRuns.push(`${key}:authority`);
        }
        if (countSignature(row) !== countSignature(baseline)) {
            exactCounts = false;
            mismatchedRuns.push(`${key}:counts`);
        }
    }
    return {
        exactIdentity,
        exactAuthority,
        exactCounts,
        noTopologyWrites: rows.every((row) => row.noTopologyWrites),
        mismatchedRuns,
    };
}

export async function sha256(value: string): Promise<string> {
    const bytes = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function identityRows(rows: unknown[]): string[] {
    return rows.map((row) => {
        const value = row as Record<string, unknown>;
        const id = value?.['id'] || value?.['receiptId'] || value?.['targetId'] || '';
        return String(id);
    }).filter(Boolean).sort();
}

function promotionIdentityRows(rows: unknown[]): string[] {
    return rows.map((value) => {
        const row = value as Record<string, unknown>;
        return JSON.stringify({
        proposalId: row['proposalId'],
        atom: row['atom'],
        family: row['family'],
        truth: row['truth'],
        candidateStatus: row['candidateStatus'],
        outcome: row['outcome'],
        status: row['status'],
        evidenceRefs: row['evidenceRefs'],
        witnessCount: row['witnessCount'],
        gates: row['gates'],
        rationale: row['rationale'],
        });
    }).sort();
}

function graphBuildNoTopologyProof(snapshot: GraphRebuildSnapshot): boolean {
    const bridgesCandidateOnly = (snapshot.chunkSemanticBridges || [])
        .every((row) => row.commitPolicy === 'no_topology_commit');
    const governanceCandidateOnly = (snapshot.memoryGovernanceCandidates || [])
        .every((row) => row.noTopologyCommit === true && row.commitPolicy === 'no_topology_commit');
    return bridgesCandidateOnly
        && governanceCandidateOnly
        && (!snapshot.storyContinuity || snapshot.storyContinuity.noTopologyCommit === true)
        && (!snapshot.storyContinuity || snapshot.storyContinuity.certificate.noTopologyWrites === true)
        && (!snapshot.promotionVerdictCertificate
            || snapshot.promotionVerdictCertificate.noTopologyWrites === true);
}

function countSignature(row: GraphBuildBaselineRunRow): string {
    return [row.nodes, row.edges, row.targets, row.chunks, row.anchors, row.acceptedRelationships].join(':');
}

function percentile(values: number[], quantile: number): number {
    if (!values.length) return 0;
    const sorted = [...values].sort((left, right) => left - right);
    const index = Math.max(0, Math.ceil(sorted.length * quantile) - 1);
    return round(sorted[index] || 0);
}

function sum<T>(rows: T[], select: (row: T) => number): number {
    return rows.reduce((total, row) => total + select(row), 0);
}

function round(value: number): number {
    return Math.round(Math.max(0, value) * 100) / 100;
}
