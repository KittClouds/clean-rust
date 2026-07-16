import { describe, expect, it } from 'vitest';
import { buildGraphDiscourseCompilerOverlaySummary } from './graph-discourse-compiler-overlay';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('buildGraphDiscourseCompilerOverlaySummary', () => {
    it('converts promotion hints into read-only compiler overlay edges', () => {
        const summary = buildGraphDiscourseCompilerOverlaySummary(snapshotWithHints(), 77);

        expect(summary.schemaVersion).toBe('phoenix-discourse-compiler-overlay/v1');
        expect(summary.invariant).toBe('discourse_compiler_overlay_no_topology_commit');
        expect(summary.overlayEdges).toHaveLength(3);
        expect(summary.compactOverlay.rowCount).toBe(3);
        expect(summary.counters).toMatchObject({
            byKind: {
                chunk_wormhole: 1,
                cross_doc_resolution: 1,
                document_cluster: 1,
            },
            overlayEdgeCount: 3,
            chunkWormholeEdges: 1,
            documentClusterEdges: 1,
            resolverEdges: 1,
            receiptCount: 3,
            reversibleReceiptCount: 3,
            graphPatchCount: 0,
            mutationAllowedCount: 0,
        });
        expect(summary.overlayEdges.every((edge) =>
            edge.projectionKind === 'discourse_overlay'
            && edge.status === 'overlay_only'
            && edge.graphPatch === false
            && edge.mutationAllowed === false,
        )).toBe(true);
        expect(summary.receipts.every((receipt) =>
            receipt.reversible
            && receipt.graphPatch === false
            && receipt.mutationAllowed === false
            && receipt.invariant === 'discourse_compiler_overlay_no_topology_commit',
        )).toBe(true);
        expect(summary.compactOverlay.rows.every((row) =>
            row.graphPatch === false && row.mutationAllowed === false,
        )).toBe(true);
    });

    it('emits an empty overlay when no promotion surface is available', () => {
        const summary = buildGraphDiscourseCompilerOverlaySummary({
            id: 'snapshot:empty',
            scopeId: 'note:empty',
            builtAt: 2,
        } as GraphRebuildSnapshot);

        expect(summary.overlayEdges).toEqual([]);
        expect(summary.receipts).toEqual([]);
        expect(summary.compactOverlay.rowCount).toBe(0);
        expect(summary.counters.overlayEdgeCount).toBe(0);
        expect(summary.counters.graphPatchCount).toBe(0);
        expect(summary.counters.mutationAllowedCount).toBe(0);
    });
});

function snapshotWithHints(): GraphRebuildSnapshot {
    return {
        id: 'snapshot:test',
        scopeId: 'note:test',
        builtAt: 7,
        discoursePromotionSurfaceSummary: {
            schemaVersion: 'phoenix-discourse-promotion-surface/v1',
            generatedAt: 7,
            sourceSnapshotId: 'snapshot:test',
            sourceEvalLedgerId: 'snapshot:test:discourse-eval-ledger:7',
            invariant: 'discourse_promotion_surface_no_topology_commit',
            chunkWormholes: [],
            documentClusters: [],
            resolverCandidates: [],
            compilerHints: [
                hint('chunk_wormhole', 'chunk-a', 'chunk-b', [], 0.91),
                hint('document_cluster', 'doc-a', undefined, ['doc-a', 'doc-b'], 0.88),
                hint('cross_doc_resolution', 'chunk-c', 'chunk-d', [], 0.72),
            ],
            receipts: [],
            compactSurface: { scopeId: 'note:test', builtAt: 7, rowCount: 3, rows: [] },
            counters: {
                byHintKind: { chunk_wormhole: 1, document_cluster: 1, cross_doc_resolution: 1 },
                byLabel: {},
                chunkWormholeCount: 1,
                documentClusterCount: 1,
                resolverCandidateCount: 1,
                compilerHintCount: 3,
                receiptCount: 3,
                reversibleReceiptCount: 3,
                graphPatchCount: 0,
                mutationAllowedCount: 0,
                acceptedRows: 2,
                ambiguousRows: 1,
            },
        },
    } as GraphRebuildSnapshot;
}

function hint(
    kind: 'chunk_wormhole' | 'document_cluster' | 'cross_doc_resolution',
    sourceTargetId: string,
    targetTargetId: string | undefined,
    memberTargetIds: string[],
    confidence: number,
) {
    return {
        id: `hint:${kind}:${sourceTargetId}`,
        kind,
        sourceLedgerEntryId: `ledger:${sourceTargetId}`,
        candidateId: `candidate:${sourceTargetId}`,
        decisionId: `decision:${sourceTargetId}`,
        sourceTargetId,
        targetTargetId,
        memberTargetIds,
        evidenceTargetIds: ['evidence:1', 'evidence:2'],
        proposedEdgeType: `${kind}:edge`,
        confidence,
        status: 'read_model_only' as const,
        mutationAllowed: false as const,
        rationale: ['test_hint'],
    };
}
