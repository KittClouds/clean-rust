import type {
    GraphDiscoursePromotionCompilerHint,
    GraphDiscoursePromotionHintKind,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export type GraphDiscourseCompilerOverlayKind = GraphDiscoursePromotionHintKind;

export interface GraphDiscourseCompilerOverlayEdge {
    id: string;
    kind: GraphDiscourseCompilerOverlayKind;
    sourceHintId: string;
    sourceLedgerEntryId: string;
    candidateId: string;
    decisionId: string;
    sourceTargetId: string;
    targetTargetId?: string;
    memberTargetIds: string[];
    evidenceTargetIds: string[];
    proposedEdgeType?: string;
    confidence: number;
    projectionKind: 'discourse_overlay';
    status: 'overlay_only';
    graphPatch: false;
    mutationAllowed: false;
    rationale: string[];
}

export interface GraphDiscourseCompilerOverlayReceipt {
    id: string;
    sourceHintId: string;
    overlayEdgeId: string;
    reversible: true;
    graphPatch: false;
    mutationAllowed: false;
    invariant: 'discourse_compiler_overlay_no_topology_commit';
    evidenceTargetIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphDiscourseCompilerOverlayCounters {
    byKind: Record<string, number>;
    overlayEdgeCount: number;
    chunkWormholeEdges: number;
    documentClusterEdges: number;
    resolverEdges: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    graphPatchCount: number;
    mutationAllowedCount: number;
}

export interface GraphDiscourseCompilerOverlaySummary {
    schemaVersion: 'phoenix-discourse-compiler-overlay/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    sourcePromotionSurfaceId: string;
    invariant: 'discourse_compiler_overlay_no_topology_commit';
    overlayEdges: GraphDiscourseCompilerOverlayEdge[];
    receipts: GraphDiscourseCompilerOverlayReceipt[];
    compactOverlay: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            kind: GraphDiscourseCompilerOverlayKind;
            score: number;
            evidence: number;
            graphPatch: false;
            mutationAllowed: false;
        }>;
    };
    counters: GraphDiscourseCompilerOverlayCounters;
}

export function buildGraphDiscourseCompilerOverlaySummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphDiscourseCompilerOverlaySummary {
    const hints = snapshot.discoursePromotionSurfaceSummary?.compilerHints || [];
    const overlayEdges = hints.map(edgeForHint).sort((left, right) =>
        right.confidence - left.confidence || left.id.localeCompare(right.id));
    const receipts = overlayEdges.map(receiptFor);

    return {
        schemaVersion: 'phoenix-discourse-compiler-overlay/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        sourcePromotionSurfaceId: snapshot.discoursePromotionSurfaceSummary
            ? `${snapshot.id}:discourse-promotion-surface:${snapshot.discoursePromotionSurfaceSummary.generatedAt}`
            : `${snapshot.id}:discourse-promotion-surface:missing`,
        invariant: 'discourse_compiler_overlay_no_topology_commit',
        overlayEdges,
        receipts,
        compactOverlay: compactOverlay(snapshot, overlayEdges),
        counters: counters(overlayEdges, receipts),
    };
}

function edgeForHint(hint: GraphDiscoursePromotionCompilerHint): GraphDiscourseCompilerOverlayEdge {
    return {
        id: `discourse-overlay-edge:${slug(hint.id)}`,
        kind: hint.kind,
        sourceHintId: hint.id,
        sourceLedgerEntryId: hint.sourceLedgerEntryId,
        candidateId: hint.candidateId,
        decisionId: hint.decisionId,
        sourceTargetId: hint.sourceTargetId,
        targetTargetId: hint.targetTargetId,
        memberTargetIds: [...hint.memberTargetIds],
        evidenceTargetIds: [...hint.evidenceTargetIds],
        proposedEdgeType: hint.proposedEdgeType,
        confidence: hint.confidence,
        projectionKind: 'discourse_overlay',
        status: 'overlay_only',
        graphPatch: false,
        mutationAllowed: false,
        rationale: [...hint.rationale, 'compiler_overlay_only:no_graph_patch'],
    };
}

function receiptFor(edge: GraphDiscourseCompilerOverlayEdge): GraphDiscourseCompilerOverlayReceipt {
    return {
        id: `discourse-overlay-receipt:${slug(edge.id)}`,
        sourceHintId: edge.sourceHintId,
        overlayEdgeId: edge.id,
        reversible: true,
        graphPatch: false,
        mutationAllowed: false,
        invariant: 'discourse_compiler_overlay_no_topology_commit',
        evidenceTargetIds: edge.evidenceTargetIds,
        undoHint: 'drop this discourse compiler overlay row; no graph edge or fact exists',
        detail: `${edge.kind} overlay at ${Math.round(edge.confidence * 100)}%`,
    };
}

function compactOverlay(
    snapshot: GraphRebuildSnapshot,
    edges: GraphDiscourseCompilerOverlayEdge[],
): GraphDiscourseCompilerOverlaySummary['compactOverlay'] {
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: edges.length,
        rows: edges.map((edge) => ({
            id: edge.id,
            kind: edge.kind,
            score: edge.confidence,
            evidence: edge.evidenceTargetIds.length,
            graphPatch: false,
            mutationAllowed: false,
        })),
    };
}

function counters(
    edges: GraphDiscourseCompilerOverlayEdge[],
    receipts: GraphDiscourseCompilerOverlayReceipt[],
): GraphDiscourseCompilerOverlayCounters {
    return {
        byKind: countBy(edges, (edge) => edge.kind),
        overlayEdgeCount: edges.length,
        chunkWormholeEdges: edges.filter((edge) => edge.kind === 'chunk_wormhole').length,
        documentClusterEdges: edges.filter((edge) => edge.kind === 'document_cluster').length,
        resolverEdges: edges.filter((edge) => edge.kind === 'cross_doc_resolution').length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        graphPatchCount: 0,
        mutationAllowedCount: receipts.filter((receipt) => receipt.mutationAllowed).length,
    };
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function slug(value: string): string {
    const normalized = value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '') || 'x';
    return `${normalized.slice(0, 96)}:${stableHash(value)}`;
}

function stableHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
}
