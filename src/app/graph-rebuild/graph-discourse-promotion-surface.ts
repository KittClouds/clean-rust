import type {
    GraphDiscourseChunkWormhole,
    GraphDiscourseDocumentClusterView,
    GraphDiscourseEvalLedgerEntry,
    GraphDiscoursePromotionCompilerHint,
    GraphDiscoursePromotionCounters,
    GraphDiscoursePromotionHintKind,
    GraphDiscoursePromotionReceipt,
    GraphDiscourseResolverCandidateView,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export interface GraphDiscoursePromotionSurfaceSummary {
    schemaVersion: 'phoenix-discourse-promotion-surface/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    sourceEvalLedgerId: string;
    invariant: 'discourse_promotion_surface_no_topology_commit';
    chunkWormholes: GraphDiscourseChunkWormhole[];
    documentClusters: GraphDiscourseDocumentClusterView[];
    resolverCandidates: GraphDiscourseResolverCandidateView[];
    compilerHints: GraphDiscoursePromotionCompilerHint[];
    receipts: GraphDiscoursePromotionReceipt[];
    compactSurface: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            kind: GraphDiscoursePromotionHintKind;
            score: number;
            evidence: number;
            mutationAllowed: false;
            graphPatches: 0;
        }>;
    };
    counters: GraphDiscoursePromotionCounters;
}

const MAX_WORMHOLES = 96;
const MAX_CLUSTERS = 32;
const MAX_RESOLVERS = 48;

export function buildGraphDiscoursePromotionSurfaceSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphDiscoursePromotionSurfaceSummary {
    const candidates = new Map((snapshot.discourseBridgeCandidateSummary?.candidates || []).map((row) => [row.id, row]));
    const chunkWormholes: GraphDiscourseChunkWormhole[] = [];
    const documentClusters: GraphDiscourseDocumentClusterView[] = [];
    const resolverCandidates: GraphDiscourseResolverCandidateView[] = [];
    const compilerHints: GraphDiscoursePromotionCompilerHint[] = [];
    const receipts: GraphDiscoursePromotionReceipt[] = [];

    for (const entry of snapshot.discourseEvalLedgerSummary?.entries || []) {
        const candidate = candidates.get(entry.candidateId);
        if (!candidate) continue;
        if (candidate.kind === 'discourse_resonance' && entry.label === 'accepted_candidate') {
            if (chunkWormholes.length >= MAX_WORMHOLES) continue;
            const hint = hintFor(entry, candidate, 'chunk_wormhole', 'chunk-resonates-with');
            compilerHints.push(hint);
            receipts.push(receiptFor(entry, hint));
            chunkWormholes.push({
                id: `discourse-wormhole:${slug(entry.id)}`,
                sourceLedgerEntryId: entry.id,
                candidateId: candidate.id,
                decisionId: entry.decisionId,
                sourceTargetId: candidate.sourceTargetId,
                targetTargetId: candidate.targetTargetId,
                score: entry.score,
                label: entry.label,
                state: entry.adjudicationState,
                evidenceTargetIds: entry.evidenceTargetIds,
                flags: entry.flags,
                compilerHintId: hint.id,
                mutationAllowed: false,
            });
        } else if (candidate.kind === 'document_cluster_review') {
            if (documentClusters.length >= MAX_CLUSTERS) continue;
            const hint = hintFor(entry, candidate, 'document_cluster', 'document-cluster-member');
            compilerHints.push(hint);
            receipts.push(receiptFor(entry, hint));
            documentClusters.push({
                id: `discourse-document-cluster:${slug(entry.id)}`,
                sourceLedgerEntryId: entry.id,
                candidateId: candidate.id,
                decisionId: entry.decisionId,
                sourceClusterId: candidate.sourceClusterId,
                medoidTargetId: candidate.sourceTargetId,
                memberTargetIds: unique([candidate.sourceTargetId, candidate.targetTargetId, ...candidate.evidenceTargetIds]).slice(0, 24),
                score: entry.score,
                label: entry.label,
                state: entry.adjudicationState,
                flags: entry.flags,
                compilerHintId: hint.id,
                mutationAllowed: false,
            });
        } else if (candidate.kind === 'cross_doc_resolution') {
            if (resolverCandidates.length >= MAX_RESOLVERS) continue;
            const hint = hintFor(entry, candidate, 'cross_doc_resolution', 'cross-doc-resolution-candidate');
            compilerHints.push(hint);
            receipts.push(receiptFor(entry, hint));
            resolverCandidates.push({
                id: `discourse-resolver:${slug(entry.id)}`,
                sourceLedgerEntryId: entry.id,
                candidateId: candidate.id,
                decisionId: entry.decisionId,
                sourceTargetId: candidate.sourceTargetId,
                targetTargetId: candidate.targetTargetId,
                sharedEntityIds: candidate.sharedEntityIds,
                score: entry.score,
                label: entry.label,
                state: entry.adjudicationState,
                evidenceTargetIds: entry.evidenceTargetIds,
                flags: entry.flags,
                compilerHintId: hint.id,
                mutationAllowed: false,
            });
        }
    }

    const orderedHints = compilerHints.sort((left, right) =>
        right.confidence - left.confidence || left.id.localeCompare(right.id));
    return {
        schemaVersion: 'phoenix-discourse-promotion-surface/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        sourceEvalLedgerId: snapshot.discourseEvalLedgerSummary
            ? `${snapshot.id}:discourse-eval-ledger:${snapshot.discourseEvalLedgerSummary.generatedAt}`
            : `${snapshot.id}:discourse-eval-ledger:missing`,
        invariant: 'discourse_promotion_surface_no_topology_commit',
        chunkWormholes: chunkWormholes.sort(scoreSort),
        documentClusters: documentClusters.sort(scoreSort),
        resolverCandidates: resolverCandidates.sort(scoreSort),
        compilerHints: orderedHints,
        receipts,
        compactSurface: compactSurface(snapshot, orderedHints),
        counters: counters(chunkWormholes, documentClusters, resolverCandidates, orderedHints, receipts),
    };
}

function hintFor(
    entry: GraphDiscourseEvalLedgerEntry,
    candidate: {
        id: string;
        sourceTargetId: string;
        targetTargetId: string;
        evidenceTargetIds: string[];
    },
    kind: GraphDiscoursePromotionHintKind,
    edgeType: string,
): GraphDiscoursePromotionCompilerHint {
    return {
        id: `discourse-compiler-hint:${kind}:${slug(entry.id)}`,
        kind,
        sourceLedgerEntryId: entry.id,
        candidateId: candidate.id,
        decisionId: entry.decisionId,
        sourceTargetId: candidate.sourceTargetId,
        targetTargetId: kind === 'document_cluster' ? undefined : candidate.targetTargetId,
        memberTargetIds: kind === 'document_cluster'
            ? unique([candidate.sourceTargetId, candidate.targetTargetId, ...candidate.evidenceTargetIds]).slice(0, 24)
            : [],
        evidenceTargetIds: entry.evidenceTargetIds,
        proposedEdgeType: edgeType,
        confidence: entry.score,
        status: 'read_model_only',
        mutationAllowed: false,
        rationale: [
            `ledger_label:${entry.label}`,
            `state:${entry.adjudicationState}`,
            `score:${entry.score.toFixed(3)}`,
            'compiler_hint_only:no_graph_patch',
        ],
    };
}

function receiptFor(
    entry: GraphDiscourseEvalLedgerEntry,
    hint: GraphDiscoursePromotionCompilerHint,
): GraphDiscoursePromotionReceipt {
    return {
        id: `discourse-promotion-receipt:${slug(hint.id)}`,
        sourceLedgerEntryId: entry.id,
        compilerHintId: hint.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_promotion_surface_no_topology_commit',
        evidenceTargetIds: hint.evidenceTargetIds,
        undoHint: 'drop this discourse promotion surface row; no graph edge or fact exists',
        detail: `${hint.kind} read-model hint at ${Math.round(hint.confidence * 100)}%`,
    };
}

function compactSurface(
    snapshot: GraphRebuildSnapshot,
    hints: GraphDiscoursePromotionCompilerHint[],
): GraphDiscoursePromotionSurfaceSummary['compactSurface'] {
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: hints.length,
        rows: hints.map((hint) => ({
            id: hint.id,
            kind: hint.kind,
            score: hint.confidence,
            evidence: hint.evidenceTargetIds.length,
            mutationAllowed: false,
            graphPatches: 0,
        })),
    };
}

function counters(
    wormholes: GraphDiscourseChunkWormhole[],
    clusters: GraphDiscourseDocumentClusterView[],
    resolvers: GraphDiscourseResolverCandidateView[],
    hints: GraphDiscoursePromotionCompilerHint[],
    receipts: GraphDiscoursePromotionReceipt[],
): GraphDiscoursePromotionCounters {
    return {
        byHintKind: countBy(hints, (row) => row.kind),
        byLabel: countBy([...wormholes, ...clusters, ...resolvers], (row) => row.label),
        chunkWormholeCount: wormholes.length,
        documentClusterCount: clusters.length,
        resolverCandidateCount: resolvers.length,
        compilerHintCount: hints.length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((row) => row.reversible).length,
        graphPatchCount: 0,
        mutationAllowedCount: receipts.filter((row) => row.mutationAllowed).length,
        acceptedRows: [...wormholes, ...clusters, ...resolvers].filter((row) => row.label === 'accepted_candidate').length,
        ambiguousRows: [...wormholes, ...clusters, ...resolvers].filter((row) => row.label === 'ambiguous_case').length,
    };
}

function scoreSort<T extends { score: number; id: string }>(left: T, right: T): number {
    return right.score - left.score || left.id.localeCompare(right.id);
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
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
