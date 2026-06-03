import type {
    GraphRebuildSnapshot,
    GraphSemanticCandidate,
    GraphSemanticCandidateCounters,
    GraphSemanticCandidateKind,
    GraphSemanticCandidateReceipt,
    GraphSemanticCandidateSource,
    GraphSemanticCandidateSourceKind,
    GraphSemanticCandidateStatus,
    GraphSemanticCandidateSummary,
    GraphSemanticTask,
    GraphSemanticTaskScore,
    GraphSemanticTaskSummary,
} from './graph-rebuild-snapshot';

interface CandidateDraft {
    kind: GraphSemanticCandidateKind;
    status?: GraphSemanticCandidateStatus;
    sourceTaskIds: string[];
    sourceTargetIds: string[];
    targetIds: string[];
    evidenceIds: string[];
    sources: GraphSemanticCandidateSource[];
    scores: GraphSemanticTaskScore[];
    confidence: number;
    noiseScore?: number;
    rationale: string[];
}

const MAX_CANDIDATES = 240;
const PER_KIND_LIMIT = 48;
const MAX_SOURCE_TARGET_IDS = 24;
const MAX_EVIDENCE_IDS = 32;
const PROPOSE_THRESHOLDS: Record<GraphSemanticCandidateKind, number> = {
    entity_link: 0.58,
    relation_link: 0.56,
    missing_frame: 0.52,
    causal_bridge: 0.56,
    temporal_bridge: 0.56,
    contradiction_review: 0.54,
    outlier_review: 0.54,
};

export function buildGraphSemanticCandidateSummary(
    snapshot: GraphRebuildSnapshot,
    tasks: GraphSemanticTaskSummary | undefined,
    generatedAt = snapshot.builtAt,
): GraphSemanticCandidateSummary {
    const builder = new SemanticCandidateBuilder(snapshot.id, generatedAt);
    for (const task of tasks?.tasks || []) addCandidateFromTask(builder, task);
    addCandidatesFromEmbeddingBridges(builder, snapshot);
    addCandidatesFromOutliers(builder, snapshot);
    addCandidatesFromUnframedChunks(builder, snapshot);
    return builder.summary();
}

function addCandidateFromTask(builder: SemanticCandidateBuilder, task: GraphSemanticTask): void {
    const kind = candidateKindForTask(task);
    if (!kind) return;
    const confidence = candidateConfidence(task);
    builder.add({
        kind,
        status: task.status === 'blocked' ? 'blocked' : confidence >= PROPOSE_THRESHOLDS[kind] ? 'proposed' : 'deferred',
        sourceTaskIds: [task.id],
        sourceTargetIds: task.sourceTargetIds,
        targetIds: task.targetIds,
        evidenceIds: task.evidenceIds,
        sources: [
            candidateSource('semantic_task', task.id, task.proposalKind, task),
            ...task.sources.map((row): GraphSemanticCandidateSource => ({
                kind: candidateSourceKind(row.kind),
                id: row.id,
                label: row.label,
                taskId: task.id,
                taskKind: task.taskKind,
                proposalKind: task.proposalKind,
                manifold: row.manifold,
            })),
        ],
        scores: task.scores,
        confidence,
        noiseScore: candidateNoise(task, confidence),
        rationale: task.rationale,
    });
}

function addCandidatesFromEmbeddingBridges(builder: SemanticCandidateBuilder, snapshot: GraphRebuildSnapshot): void {
    for (const edge of snapshot.embeddingGraphPostProcess?.bridgeEdges || []) {
        const confidence = round(clamp(edge.score * 0.7 + edge.semanticScore * 0.2 + edge.structuralScore * 0.1, 0, 1));
        builder.add({
            kind: 'relation_link',
            status: confidence >= PROPOSE_THRESHOLDS.relation_link ? 'proposed' : 'deferred',
            sourceTaskIds: [],
            sourceTargetIds: [edge.sourceTargetId, edge.targetTargetId],
            targetIds: [`bridge:${edge.id}`],
            evidenceIds: [edge.sourceTargetId, edge.targetTargetId],
            sources: [
                { kind: 'manifold', id: edge.id, label: edge.role, manifold: 'product' },
                { kind: 'graph_postprocess', id: edge.id, label: 'embedding bridge' },
            ],
            scores: [
                score('manifold', edge.score, edge.id, 'embedding bridge score'),
                score('semantic', edge.semanticScore, edge.id, 'semantic bridge score'),
                score('structural', edge.structuralScore, edge.id, 'structural bridge score'),
            ],
            confidence,
            rationale: edge.reason,
        });
    }
}

function addCandidatesFromOutliers(builder: SemanticCandidateBuilder, snapshot: GraphRebuildSnapshot): void {
    const targetRows = new Map((snapshot.embeddingGraphPostProcess?.targets || []).map((row) => [row.targetId, row]));
    for (const targetId of snapshot.embeddingGraphPostProcess?.outlierTargetIds || []) {
        const row = targetRows.get(targetId);
        const confidence = round(clamp(row?.outlierScore || 0.72, 0, 1));
        builder.add({
            kind: 'outlier_review',
            status: confidence >= PROPOSE_THRESHOLDS.outlier_review ? 'proposed' : 'deferred',
            sourceTaskIds: [],
            sourceTargetIds: [targetId],
            targetIds: [`outlier:${targetId}`],
            evidenceIds: [targetId],
            sources: [
                { kind: 'manifold', id: targetId, label: 'embedding outlier', manifold: 'hybrid' },
                { kind: 'embedding_target', id: targetId, label: row?.clusterId || 'target outlier' },
            ],
            scores: [score('anomaly', confidence, targetId, 'embedding outlier score')],
            confidence,
            noiseScore: round(1 - confidence + Math.min(0.18, (row?.neighborCount || 0) * 0.02)),
            rationale: [`cluster:${row?.clusterId || 'unknown'}`, `neighbor_count:${row?.neighborCount ?? 0}`],
        });
    }
}

function addCandidatesFromUnframedChunks(builder: SemanticCandidateBuilder, snapshot: GraphRebuildSnapshot): void {
    const eventChunkIds = new Set(snapshot.events.map((event) => event.chunkId).filter(Boolean));
    for (const chunk of snapshot.chunks) {
        const cues = chunk.meaningFrame?.eventCues || [];
        if (!cues.length || eventChunkIds.has(chunk.id)) continue;
        const confidence = clamp(0.42 + Math.min(0.38, cues.length * 0.08), 0.42, 0.8);
        builder.add({
            kind: 'missing_frame',
            status: confidence >= PROPOSE_THRESHOLDS.missing_frame ? 'proposed' : 'deferred',
            sourceTaskIds: [],
            sourceTargetIds: [`chunk:${chunk.id}`],
            targetIds: [`frame:${chunk.id}`],
            evidenceIds: [chunk.id],
            sources: [
                { kind: 'frame_gap', id: chunk.id, label: 'chunk event cues' },
                { kind: 'embedding_target', id: `embed:chunk:${chunk.id}`, label: 'chunk target' },
            ],
            scores: [score('semantic', confidence, chunk.id, 'unframed chunk event cues')],
            confidence,
            rationale: [`event_cues:${cues.slice(0, 6).join(',')}`],
        });
    }
}

class SemanticCandidateBuilder {
    private readonly candidates: GraphSemanticCandidate[] = [];
    private readonly receipts: GraphSemanticCandidateReceipt[] = [];
    private readonly seen = new Set<string>();
    private readonly kindCounts = new Map<GraphSemanticCandidateKind, number>();

    constructor(private readonly snapshotId: string, private readonly generatedAt: number) {}

    add(draft: CandidateDraft): void {
        if (this.candidates.length >= MAX_CANDIDATES) return;
        const kindCount = this.kindCounts.get(draft.kind) || 0;
        if (kindCount >= PER_KIND_LIMIT) return;
        const key = `${draft.kind}|${draft.sourceTaskIds.join('|')}|${draft.sourceTargetIds.join('|')}|${draft.targetIds.join('|')}`;
        if (this.seen.has(key)) return;
        this.seen.add(key);
        this.kindCounts.set(draft.kind, kindCount + 1);
        const confidence = round(clamp(draft.confidence, 0, 1));
        const noiseScore = round(clamp(draft.noiseScore ?? defaultNoiseScore(draft, confidence), 0, 1));
        const rank = round(confidence * 0.72 + (1 - noiseScore) * 0.28);
        const id = `semantic-candidate:${draft.kind}:${slug(key)}`;
        const receiptId = `semantic-candidate-receipt:${slug(id)}`;
        const status = draft.status || (confidence >= PROPOSE_THRESHOLDS[draft.kind] ? 'proposed' : 'deferred');
        const evidenceIds = unique(draft.evidenceIds).slice(0, MAX_EVIDENCE_IDS);
        this.candidates.push({
            id,
            kind: draft.kind,
            status,
            sourceTaskIds: unique(draft.sourceTaskIds),
            sourceTargetIds: unique(draft.sourceTargetIds).slice(0, MAX_SOURCE_TARGET_IDS),
            targetIds: unique(draft.targetIds),
            evidenceIds,
            sources: uniqueSources(draft.sources),
            scores: draft.scores.map((row) => ({ ...row, score: round(clamp(row.score, 0, 1)) })),
            confidence,
            noiseScore,
            rank,
            rationale: compact(draft.rationale).slice(0, 10),
            reversibleReceiptIds: [receiptId],
            mutationAllowed: false,
            createdAt: this.generatedAt,
        });
        this.receipts.push({
            id: receiptId,
            candidateId: id,
            status,
            reversible: true,
            mutationAllowed: false,
            invariant: 'phase2_no_topology_commit',
            evidenceIds,
            undoHint: 'no graph mutation was performed; drop this candidate to undo',
            detail: `${draft.kind} candidate ${status} at ${Math.round(confidence * 100)}% confidence`,
        });
    }

    summary(): GraphSemanticCandidateSummary {
        const candidates = this.candidates.sort((left, right) =>
            right.rank - left.rank
            || right.confidence - left.confidence
            || left.kind.localeCompare(right.kind)
            || left.id.localeCompare(right.id));
        return {
            schemaVersion: 'phoenix-semantic-candidate-factory/v1',
            generatedAt: this.generatedAt,
            sourceSnapshotId: this.snapshotId,
            candidates,
            receipts: this.receipts,
            counters: candidateCounters(candidates, this.receipts),
        };
    }
}

function candidateKindForTask(task: GraphSemanticTask): GraphSemanticCandidateKind | null {
    switch (task.proposalKind) {
        case 'identity_link':
        case 'missing_entity':
            return 'entity_link';
        case 'semantic_link':
        case 'relation_type':
        case 'missing_edge':
            return 'relation_link';
        case 'missing_frame':
            return 'missing_frame';
        case 'causal_type':
        case 'causal_chain':
            return 'causal_bridge';
        case 'temporal_type':
        case 'temporal_chain':
            return 'temporal_bridge';
        case 'contradiction_review':
        case 'duplicate_review':
        case 'brittle_link':
            return 'contradiction_review';
        case 'outlier_review':
        case 'semantic_bundle':
            return 'outlier_review';
        case 'entity_kind':
        case 'domain_vote':
        case 'belief_chain':
            return null;
    }
}

function candidateConfidence(task: GraphSemanticTask): number {
    const scoreMean = task.scores.length
        ? task.scores.reduce((sum, row) => sum + row.score * row.weight, 0) / task.scores.reduce((sum, row) => sum + row.weight, 0)
        : task.confidence;
    const evidenceLift = Math.min(0.08, task.evidenceIds.length * 0.006);
    return round(clamp(task.confidence * 0.72 + scoreMean * 0.28 + evidenceLift, 0, 1));
}

function candidateNoise(task: GraphSemanticTask, confidence: number): number {
    const weakEvidencePenalty = task.evidenceIds.length ? 0 : 0.16;
    const broadTargetPenalty = Math.min(0.18, Math.max(0, task.sourceTargetIds.length - 6) * 0.015);
    const blockedPenalty = task.status === 'blocked' ? 0.2 : 0;
    return round(clamp(1 - confidence + weakEvidencePenalty + broadTargetPenalty + blockedPenalty, 0, 1));
}

function defaultNoiseScore(draft: CandidateDraft, confidence: number): number {
    const weakEvidencePenalty = draft.evidenceIds.length ? 0 : 0.14;
    const broadTargetPenalty = Math.min(0.18, Math.max(0, draft.sourceTargetIds.length - 6) * 0.015);
    return 1 - confidence + weakEvidencePenalty + broadTargetPenalty;
}

function candidateSource(kind: GraphSemanticCandidateSourceKind, id: string, label: string, task: GraphSemanticTask): GraphSemanticCandidateSource {
    return { kind, id, label, taskId: task.id, taskKind: task.taskKind, proposalKind: task.proposalKind };
}

function candidateSourceKind(kind: string): GraphSemanticCandidateSourceKind {
    if (kind === 'embedding_target') return 'embedding_target';
    if (kind === 'manifold') return 'manifold';
    if (kind === 'graph_postprocess') return 'graph_postprocess';
    if (kind === 'identity_linker') return 'identity_linker';
    if (kind === 'relationship_fact') return 'relationship_fact';
    if (kind === 'temporal_fact') return 'temporal_fact';
    if (kind === 'causal_fact') return 'causal_fact';
    if (kind === 'evidence_ledger') return 'evidence_anchor';
    return 'graph_postprocess';
}

function candidateCounters(candidates: GraphSemanticCandidate[], receipts: GraphSemanticCandidateReceipt[]): GraphSemanticCandidateCounters {
    const averageNoiseScore = candidates.length
        ? round(candidates.reduce((sum, candidate) => sum + candidate.noiseScore, 0) / candidates.length)
        : 0;
    return {
        byKind: countBy(candidates, (candidate) => candidate.kind),
        byStatus: countBy(candidates, (candidate) => candidate.status),
        bySourceKind: countBy(candidates.flatMap((candidate) => candidate.sources), (source) => source.kind),
        sourceTaskCount: unique(candidates.flatMap((candidate) => candidate.sourceTaskIds)).length,
        sourceTargetCount: unique(candidates.flatMap((candidate) => candidate.sourceTargetIds)).length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        mutationAllowedCount: candidates.filter((candidate) => candidate.mutationAllowed).length + receipts.filter((receipt) => receipt.mutationAllowed).length,
        proposedCount: candidates.filter((candidate) => candidate.status === 'proposed').length,
        deferredCount: candidates.filter((candidate) => candidate.status === 'deferred').length,
        blockedCount: candidates.filter((candidate) => candidate.status === 'blocked').length,
        maxCandidates: MAX_CANDIDATES,
        averageNoiseScore,
    };
}

function score(kind: GraphSemanticTaskScore['kind'], value: number, sourceId: string, rationale: string, weight = 1): GraphSemanticTaskScore {
    return { kind, score: value, weight, sourceId, rationale };
}

function uniqueSources(sources: GraphSemanticCandidateSource[]): GraphSemanticCandidateSource[] {
    const seen = new Set<string>();
    return sources.filter((source) => {
        const key = `${source.kind}|${source.id}|${source.taskId || ''}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    }).slice(0, 12);
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function compact(values: Array<string | null | undefined>): string[] {
    return values.filter((value): value is string => Boolean(value && value.trim()));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function slug(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '').slice(0, 104) || 'x';
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
