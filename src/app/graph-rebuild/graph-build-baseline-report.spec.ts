import { describe, expect, it } from 'vitest';
import {
    graphBuildParity,
    graphBuildPerformanceGate,
    summarizeGraphBuildLane,
    type GraphBuildBaselineRunRow,
} from './graph-build-baseline-report';

describe('graph build baseline report', () => {
    it('reports nearest-rank p50 and p95 without averaging away spikes', () => {
        const rows = Array.from({ length: 10 }, (_, index) => row(index + 1, (index + 1) * 100));
        const summary = summarizeGraphBuildLane(rows);
        expect(summary.wallP50Ms).toBe(500);
        expect(summary.wallP95Ms).toBe(1000);
        expect(summary.transportP50Ms).toBe(50);
        expect(summary.storeDocumentsTotal).toBe(10);
    });

    it('requires exact identity, authority, counts, and no-topology proof', () => {
        const baseline = row(1, 100);
        const mismatch = { ...row(2, 90), identityHash: 'changed', noTopologyWrites: false };
        expect(graphBuildParity([baseline, mismatch])).toMatchObject({
            exactIdentity: false,
            exactAuthority: true,
            exactCounts: true,
            noTopologyWrites: false,
            mismatchedRuns: ['warm_force:2:identity'],
        });
    });

    it('enforces the one-second target and three-second p95 ceiling', () => {
        const passing = summarizeGraphBuildLane([row(1, 900), row(2, 2_500)]);
        const failing = summarizeGraphBuildLane([row(1, 1_100), row(2, 3_100)]);

        expect(graphBuildPerformanceGate(passing, passing)).toMatchObject({ passed: true });
        expect(graphBuildPerformanceGate(passing, failing)).toMatchObject({
            warmPassed: true,
            deltaPassed: false,
            passed: false,
        });
    });
});

function row(iteration: number, wallMs: number): GraphBuildBaselineRunRow {
    return {
        lane: 'warm_force', iteration, wallMs, receiptSettleMs: wallMs / 2,
        snapshotId: 'snapshot', authorityHash: 'authority', identityHash: 'identity',
        nodes: 27, edges: 256, targets: 941, chunks: 34, anchors: 519,
        acceptedRelationships: 32, documentHyperedges: 12, interactiveIdentityReused: 1,
        documentSemanticDocumentsBuilt: 0, documentSemanticDocumentsReused: 2,
        documentSemanticRawBytesWritten: 0, documentSemanticCompressedBytesWritten: 0,
        storeDocuments: 1, writtenContentBlobs: 0,
        reusedContentBlobs: 10, snapshotBuildMs: 500, snapshotPersistMs: 100,
        snapshotCpuMs: 550, snapshotAnchorsMs: 10, snapshotFactsMs: 20,
        snapshotCompatibilityViewsMs: 30, snapshotTargetsMs: 40,
        snapshotPostProcessMs: 50, snapshotAssemblyMs: 60,
        snapshotEmbeddingPostProcessMs: 20, snapshotGraphAwareLinksMs: 10,
        snapshotEntityLinkingMs: 20,
        snapshotEmbeddingSignaturesMs: 4, snapshotEmbeddingPairPlanMs: 4,
        snapshotEmbeddingNeighborsMs: 4, snapshotEmbeddingClustersMs: 4,
        snapshotEmbeddingRowsEdgesMs: 4,
        snapshotSemanticTasksMs: 50, snapshotSemanticCandidatesMs: 40,
        snapshotManifoldSpecializationMs: 30, snapshotSemanticRerankMs: 60,
        snapshotSemanticAdjudicationMs: 80, snapshotSemanticEvalLedgerMs: 30,
        snapshotSemanticLedgersMs: 290, snapshotSemanticIndexBuilds: 7,
        snapshotSemanticIndexEntries: 4000, snapshotSemanticAvoidedIndexBuilds: 300,
        snapshotSemanticAvoidedIndexEntries: 300000, packetConstructionMs: 20,
        authoritySealMs: 30, nativeAnalysisRustMicros: 1000,
        nativeGraphRunArenaReused: 1, nativeGraphRunArenaResidentBytes: 100,
        nativeGraphRunArenaActiveLeases: 1, nativeGraphRunPageProjectionMicros: 100,
        nativeGraphRunDetailRows: 10, nativeGraphRunReturnedDetailRows: 8,
        nativeGraphRunPersistMs: 20, nativeGraphRunChangedSections: 0,
        nativeGraphRunReusedSections: 7, nativeGraphRunEncodedSections: 0,
        nativeGraphRunCompressedSections: 0, nativeGraphRunRawBytesWritten: 0,
        nativeGraphRunCompressedBytesWritten: 0,
        transportCalls: 20, transportTotalMs: wallMs / 10,
        transportMaxMs: wallMs / 20, transportRequestBytes: 1000,
        transportResponseBytes: 900, transportRequestBytesMeasuredCalls: 20,
        transportRequestBytesUnavailableCalls: 0, transportResponseBytesMeasuredCalls: 20,
        transportResponseBytesUnavailableCalls: 0, transportEncodeMs: 2,
        transportDecodeMs: 3, transportEncodeTimingUnavailableCalls: 0,
        transportDecodeTimingUnavailableCalls: 0, transportOffenders: '', noTopologyWrites: true,
    };
}
