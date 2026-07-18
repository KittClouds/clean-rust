import type {
    GraphRebuildEmbeddingBackboneEdge,
    GraphRebuildEntityLinkSuggestion,
    GraphRebuildFinalLinkPatch,
    GraphRebuildLinkSuggestion,
    GraphRebuildResolutionSuggestion,
    GraphRebuildShadowLink,
    GraphRebuildSnapshot,
    GraphSemanticProposalKind,
    GraphSemanticTask,
    GraphSemanticTaskCounters,
    GraphSemanticTaskKind,
    GraphSemanticTaskReceipt,
    GraphSemanticTaskScore,
    GraphSemanticTaskScoreKind,
    GraphSemanticTaskSource,
    GraphSemanticTaskSourceKind,
    GraphSemanticTaskStatus,
} from './graph-rebuild-snapshot';
import type { GraphSemanticDerivationContext } from './graph-semantic-derivation-context';

interface TaskDraft {
    taskKind: GraphSemanticTaskKind;
    proposalKind: GraphSemanticProposalKind;
    status?: GraphSemanticTaskStatus;
    sourceTargetIds: string[];
    targetIds?: string[];
    sources: GraphSemanticTaskSource[];
    scores: GraphSemanticTaskScore[];
    confidence: number;
    rationale: string[];
    evidenceIds: string[];
}

const PER_TASK_PROPOSAL_LIMIT = 48;
const MAX_SOURCE_TARGET_IDS = 18;
const MAX_EVIDENCE_IDS = 24;

export function buildGraphSemanticTaskSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
    context?: GraphSemanticDerivationContext,
) {
    const builder = new SemanticTaskBuilder(snapshot.id, generatedAt);
    addLinkPredictionTasks(builder, snapshot);
    addEdgeClassificationTasks(builder, snapshot);
    addNodeClassificationTasks(builder, snapshot);
    addGraphCompletionTasks(builder, snapshot, context);
    addCommunityDetectionTasks(builder, snapshot);
    addAnomalyDetectionTasks(builder, snapshot, context);
    addPathReasoningTasks(builder, snapshot);
    return builder.summary();
}

function addLinkPredictionTasks(builder: SemanticTaskBuilder, snapshot: GraphRebuildSnapshot): void {
    for (const suggestion of snapshot.graphAwareLinkSuggestions || []) {
        builder.add({
            taskKind: 'link_prediction',
            proposalKind: 'semantic_link',
            status: suggestion.status === 'confirmed' ? 'proposed' : 'prepared',
            sourceTargetIds: [`entity:${suggestion.sourceEntityId}`, `entity:${suggestion.targetEntityId}`],
            targetIds: [`link:${suggestion.sourceEntityId}:${suggestion.targetEntityId}`],
            sources: [
                source('graph_postprocess', suggestion.id, suggestion.kind, { manifold: suggestion.productLane ? 'product' : 'hybrid' }),
                source('manifold', `manifold:${suggestion.embeddingRole || suggestion.structuralRole}`, String(suggestion.embeddingRole || suggestion.structuralRole), { manifold: suggestion.productLane || 'hybrid' }),
            ],
            scores: [
                score('semantic', suggestion.confidence, suggestion.id, 'graph-aware link proposal confidence'),
                score('structural', suggestion.rerankScore ?? suggestion.confidence, suggestion.id, 'topology reranker signal'),
            ],
            confidence: suggestion.rerankScore ?? suggestion.confidence,
            rationale: suggestion.rationale,
            evidenceIds: suggestion.evidenceIds,
        });
    }
    for (const suggestion of snapshot.entityLinkSuggestions || []) addIdentityLinkTask(builder, suggestion);
}

function addIdentityLinkTask(builder: SemanticTaskBuilder, suggestion: GraphRebuildEntityLinkSuggestion | GraphRebuildShadowLink): void {
    builder.add({
        taskKind: 'link_prediction',
        proposalKind: 'identity_link',
        status: suggestion.status === 'confirmed' ? 'proposed' : 'prepared',
        sourceTargetIds: compact([suggestion.mentionId, suggestion.candidateEntityId].map((id) => id ? `identity:${id}` : '')),
        targetIds: compact([suggestion.candidateEntityId ? `entity:${suggestion.candidateEntityId}` : '', suggestion.mentionId ? `mention:${suggestion.mentionId}` : '']),
        sources: [
            source('identity_linker', suggestion.id, suggestion.decision),
            source('manifold', `embedding:${suggestion.embeddingRole || 'identity'}`, String(suggestion.embeddingRole || 'identity'), { manifold: suggestion.productLane || 'hybrid' }),
        ],
        scores: [
            score('identity', suggestion.confidence, suggestion.id, 'identity linker confidence'),
            score('semantic', suggestion.rerankScore, suggestion.id, 'semantic rerank score'),
        ],
        confidence: Math.max(suggestion.confidence, suggestion.rerankScore),
        rationale: suggestion.rationale,
        evidenceIds: suggestion.evidenceIds,
    });
}

function addEdgeClassificationTasks(builder: SemanticTaskBuilder, snapshot: GraphRebuildSnapshot): void {
    for (const relationship of sortedByConfidence(snapshot.relationships).slice(0, 80)) {
        builder.add({
            taskKind: 'edge_classification',
            proposalKind: 'relation_type',
            status: relationship.status === 'accepted' ? 'proposed' : 'prepared',
            sourceTargetIds: [`entity:${relationship.sourceEntityId}`, `entity:${relationship.targetEntityId}`],
            targetIds: [`relationship:${relationship.id}`],
            sources: [source('relationship_fact', relationship.id, relationship.relationType, { lane: 'relationship_fact' })],
            scores: [
                score('semantic', relationship.confidence, relationship.id, 'relationship cue confidence'),
                score('evidence', evidenceScore(relationship.evidenceAnchorIds.length), relationship.id, 'relationship evidence support'),
            ],
            confidence: relationship.confidence,
            rationale: [relationship.rationale],
            evidenceIds: relationship.evidenceAnchorIds,
        });
    }
    for (const edge of snapshot.causalEdges.slice(0, 80)) {
        builder.add({
            taskKind: 'edge_classification',
            proposalKind: 'causal_type',
            status: edge.status === 'accepted' || edge.status === 'supported' ? 'proposed' : 'prepared',
            sourceTargetIds: [`event:${edge.sourceId}`, `event:${edge.targetId}`],
            targetIds: [`causal:${edge.id}`],
            sources: [source('causal_fact', edge.id, edge.sourceKind, { lane: 'causal_fact' })],
            scores: [
                score('causal', edge.confidence, edge.id, edge.rationale || 'causal edge confidence'),
                score('temporal', edge.temporalLegal === false ? 0.15 : 0.72, edge.id, 'temporal legality guard'),
            ],
            confidence: edge.confidence,
            rationale: compact([edge.rationale || '', edge.cue ? `cue:${edge.cue}` : '']),
            evidenceIds: edge.evidenceIds,
        });
    }
    for (const edge of snapshot.temporalEdges.slice(0, 80)) {
        builder.add({
            taskKind: 'edge_classification',
            proposalKind: 'temporal_type',
            sourceTargetIds: [`event:${edge.sourceId}`, `event:${edge.targetId}`],
            targetIds: [`temporal:${edge.id}`],
            sources: [source('temporal_fact', edge.id, edge.relationType, { lane: 'temporal_fact' })],
            scores: [score('temporal', edge.confidence, edge.id, 'temporal edge confidence')],
            confidence: edge.confidence,
            rationale: [`temporal relation:${edge.relationType}`],
            evidenceIds: edge.evidenceIds,
        });
    }
}

function addNodeClassificationTasks(builder: SemanticTaskBuilder, snapshot: GraphRebuildSnapshot): void {
    for (const node of snapshot.nodes.slice(0, 96)) {
        const confidence = clamp(0.48 + Math.min(0.3, node.totalMentions * 0.03) + Math.min(0.12, node.aliases.length * 0.03), 0.48, 0.9);
        builder.add({
            taskKind: 'node_classification',
            proposalKind: node.kind.toUpperCase() === 'CONCEPT' ? 'domain_vote' : 'entity_kind',
            sourceTargetIds: [`entity:${node.entityId}`, ...node.anchorIds.slice(0, 6).map((id) => `anchor:${id}`)],
            targetIds: [`entity:${node.entityId}`],
            sources: [
                source('ontology_policy', `kind:${node.kind}`, node.kind, { lane: 'entity_anchor' }),
                source('evidence_ledger', `anchors:${node.entityId}`, 'entity anchors'),
            ],
            scores: [
                score('ontology', confidence, node.entityId, 'registry kind plus mention support'),
                score('evidence', evidenceScore(node.anchorIds.length), node.entityId, 'anchor support count'),
            ],
            confidence,
            rationale: [`kind:${node.kind}`, `mentions:${node.totalMentions}`, `aliases:${node.aliases.length}`],
            evidenceIds: node.anchorIds,
        });
    }
}

function addGraphCompletionTasks(
    builder: SemanticTaskBuilder,
    snapshot: GraphRebuildSnapshot,
    context?: GraphSemanticDerivationContext,
): void {
    for (const suggestion of (snapshot.graphAwareLinkSuggestions || []).filter((row) => row.kind === 'missing_triangle')) {
        addMissingEdgeTask(builder, suggestion);
    }
    for (const edge of snapshot.embeddingGraphPostProcess?.bridgeEdges || []) addBridgeCompletionTask(builder, edge);
    for (const suggestion of snapshot.resolutionSuggestions || []) addMissingIdentityTask(builder, suggestion);
    for (const patch of snapshot.finalLinkPatchLog?.patches || []) addPatchCompletionTask(builder, patch);
    const eventChunkIds = context?.eventChunkIds()
        || new Set(snapshot.events.map((event) => event.chunkId).filter(Boolean));
    for (const chunk of snapshot.chunks.filter((row) => row.meaningFrame?.eventCues.length && !eventChunkIds.has(row.id)).slice(0, 32)) {
        builder.add({
            taskKind: 'graph_completion',
            proposalKind: 'missing_frame',
            sourceTargetIds: [`chunk:${chunk.id}`],
            targetIds: [`frame:${chunk.id}`],
            sources: [source('embedding_target', `embed:chunk:${chunk.id}`, 'chunk event cues', { lane: 'chunk_spine', targetKind: 'chunk' })],
            scores: [score('semantic', clamp((chunk.meaningFrame?.eventCues.length || 0) / 8, 0.35, 0.85), chunk.id, 'chunk has unresolved event cues')],
            confidence: clamp((chunk.meaningFrame?.eventCues.length || 0) / 8, 0.35, 0.85),
            rationale: [`event_cues:${chunk.meaningFrame?.eventCues.slice(0, 4).join(',')}`],
            evidenceIds: [chunk.id],
        });
    }
}

function addCommunityDetectionTasks(builder: SemanticTaskBuilder, snapshot: GraphRebuildSnapshot): void {
    for (const cluster of (snapshot.embeddingGraphPostProcess?.clusters || []).slice(0, 72)) {
        builder.add({
            taskKind: 'community_detection',
            proposalKind: 'semantic_bundle',
            sourceTargetIds: cluster.targetIds.slice(0, MAX_SOURCE_TARGET_IDS),
            targetIds: [`cluster:${cluster.id}`],
            sources: [
                source('manifold', cluster.id, cluster.role, { manifold: 'hybrid' }),
                source('graph_postprocess', cluster.medoidTargetId, 'cluster medoid'),
            ],
            scores: [
                score('manifold', cluster.confidence, cluster.id, 'embedding cluster confidence'),
                score('semantic', cluster.density, cluster.id, 'cluster density'),
            ],
            confidence: cluster.confidence,
            rationale: [`role:${cluster.role}`, `size:${cluster.size}`, `top_kinds:${cluster.topKinds.join(',')}`],
            evidenceIds: cluster.targetIds.slice(0, MAX_EVIDENCE_IDS),
        });
    }
}

function addAnomalyDetectionTasks(
    builder: SemanticTaskBuilder,
    snapshot: GraphRebuildSnapshot,
    context?: GraphSemanticDerivationContext,
): void {
    const targetRows = context?.targetRows()
        || new Map((snapshot.embeddingGraphPostProcess?.targets || []).map((row) => [row.targetId, row]));
    for (const targetId of snapshot.embeddingGraphPostProcess?.outlierTargetIds || []) {
        const row = targetRows.get(targetId);
        builder.add({
            taskKind: 'anomaly_detection',
            proposalKind: 'outlier_review',
            sourceTargetIds: [targetId],
            targetIds: [`outlier:${targetId}`],
            sources: [source('manifold', targetId, 'embedding outlier', { manifold: 'hybrid' })],
            scores: [score('anomaly', row?.outlierScore || 0.72, targetId, 'embedding target outlier score')],
            confidence: row?.outlierScore || 0.72,
            rationale: [`neighbor_count:${row?.neighborCount ?? 0}`, `cluster:${row?.clusterId || 'unknown'}`],
            evidenceIds: [targetId],
        });
    }
    for (const suggestion of snapshot.resolutionSuggestions || []) addResolutionAnomalyTask(builder, suggestion);
    for (const suggestion of snapshot.shadowLinkSuggestions || []) addShadowAnomalyTask(builder, suggestion);
    for (const receipt of snapshot.finalLinkPatchLog?.receipts.filter((row) => row.status === 'failed') || []) {
        builder.add({
            taskKind: 'anomaly_detection',
            proposalKind: 'brittle_link',
            status: 'blocked',
            sourceTargetIds: [receipt.sourceShadowLinkId],
            targetIds: [`receipt:${receipt.id}`],
            sources: [source('evidence_ledger', receipt.id, receipt.invariant)],
            scores: [score('anomaly', 1, receipt.id, 'failed reversible receipt invariant')],
            confidence: 1,
            rationale: [receipt.detail],
            evidenceIds: [receipt.id],
        });
    }
    for (const cluster of (snapshot.embeddingGraphPostProcess?.clusters || []).filter((row) => row.size === 1).slice(0, 32)) {
        builder.add({
            taskKind: 'anomaly_detection',
            proposalKind: 'outlier_review',
            sourceTargetIds: cluster.targetIds,
            targetIds: [`singleton:${cluster.id}`],
            sources: [source('manifold', cluster.id, 'singleton cluster', { manifold: 'hybrid' })],
            scores: [score('anomaly', 0.58, cluster.id, 'singleton semantic bundle needs review')],
            confidence: 0.58,
            rationale: [`singleton_cluster:${cluster.id}`],
            evidenceIds: cluster.targetIds,
        });
    }
}

function addPathReasoningTasks(builder: SemanticTaskBuilder, snapshot: GraphRebuildSnapshot): void {
    for (const edge of snapshot.causalEdges.slice(0, 80)) {
        builder.add({
            taskKind: 'path_reasoning',
            proposalKind: 'causal_chain',
            status: edge.status === 'accepted' || edge.status === 'supported' ? 'proposed' : 'prepared',
            sourceTargetIds: [`event:${edge.sourceId}`, `event:${edge.targetId}`],
            targetIds: [`path:causal:${edge.id}`],
            sources: [source('causal_fact', edge.id, edge.relationKind || edge.relationType, { lane: 'causal_fact', manifold: 'siegel' })],
            scores: [
                score('causal', edge.confidence, edge.id, edge.rationale || 'causal chain edge'),
                score('evidence', evidenceScore(edge.evidenceIds.length), edge.id, 'causal evidence support'),
            ],
            confidence: edge.confidence,
            rationale: compact([edge.rationale || '', edge.sourceKind, edge.evidenceClass]),
            evidenceIds: edge.evidenceIds,
        });
    }
    for (const edge of snapshot.temporalEdges.slice(0, 80)) {
        builder.add({
            taskKind: 'path_reasoning',
            proposalKind: 'temporal_chain',
            sourceTargetIds: [`event:${edge.sourceId}`, `event:${edge.targetId}`],
            targetIds: [`path:temporal:${edge.id}`],
            sources: [source('temporal_fact', edge.id, edge.relationType, { lane: 'temporal_fact', manifold: 'siegel' })],
            scores: [score('temporal', edge.confidence, edge.id, 'temporal chain edge')],
            confidence: edge.confidence,
            rationale: [`temporal_path:${edge.relationType}`],
            evidenceIds: edge.evidenceIds,
        });
    }
    for (const state of snapshot.memoryState.slice(0, 40)) {
        builder.add({
            taskKind: 'path_reasoning',
            proposalKind: 'belief_chain',
            sourceTargetIds: [`entity:${state.entityId}`, `memory:${state.id}`],
            targetIds: [`belief:${state.id}`],
            sources: [source('embedding_target', `embed:memory:${state.id}`, state.key, { lane: 'memory_state', manifold: 'product' })],
            scores: [score('semantic', 0.72, state.id, 'memory state can seed belief path review')],
            confidence: 0.72,
            rationale: [`memory_key:${state.key}`, state.value],
            evidenceIds: state.evidenceIds,
        });
    }
}

class SemanticTaskBuilder {
    private readonly tasks: GraphSemanticTask[] = [];
    private readonly receipts: GraphSemanticTaskReceipt[] = [];
    private readonly seen = new Set<string>();
    private readonly proposalCounts = new Map<string, number>();

    constructor(private readonly snapshotId: string, private readonly generatedAt: number) {}

    add(draft: TaskDraft): void {
        const countKey = `${draft.taskKind}:${draft.proposalKind}`;
        const count = this.proposalCounts.get(countKey) || 0;
        if (count >= PER_TASK_PROPOSAL_LIMIT) return;
        const key = `${draft.taskKind}|${draft.proposalKind}|${draft.sourceTargetIds.join('|')}|${draft.targetIds?.join('|') || ''}`;
        if (this.seen.has(key)) return;
        this.seen.add(key);
        this.proposalCounts.set(countKey, count + 1);
        const id = `semantic-task:${draft.taskKind}:${draft.proposalKind}:${slug(key)}`;
        const receiptId = `semantic-receipt:${slug(id)}`;
        const evidenceIds = unique(draft.evidenceIds).slice(0, MAX_EVIDENCE_IDS);
        this.tasks.push({
            id,
            taskKind: draft.taskKind,
            proposalKind: draft.proposalKind,
            status: draft.status || 'prepared',
            sourceTargetIds: unique(draft.sourceTargetIds).slice(0, MAX_SOURCE_TARGET_IDS),
            targetIds: unique(draft.targetIds || []),
            sources: draft.sources,
            scores: draft.scores.map((row) => ({ ...row, score: round(clamp(row.score, 0, 1)) })),
            confidence: round(clamp(draft.confidence, 0, 1)),
            rationale: compact(draft.rationale).slice(0, 8),
            evidenceIds,
            reversibleReceiptIds: [receiptId],
            mutationAllowed: false,
            createdAt: this.generatedAt,
        });
        this.receipts.push({
            id: receiptId,
            taskId: id,
            status: draft.status || 'prepared',
            reversible: true,
            mutationAllowed: false,
            invariant: 'phase1_no_topology_mutation',
            evidenceIds,
            undoHint: 'no graph mutation was performed; discard this prepared task to undo',
            detail: `${draft.taskKind}:${draft.proposalKind} prepared from ${draft.sourceTargetIds.length} source target(s)`,
        });
    }

    summary() {
        return {
            schemaVersion: 'phoenix-graph-semantic-tasks/v1' as const,
            generatedAt: this.generatedAt,
            sourceSnapshotId: this.snapshotId,
            tasks: this.tasks.sort((left, right) =>
                taskRank(right) - taskRank(left)
                || left.taskKind.localeCompare(right.taskKind)
                || left.id.localeCompare(right.id)),
            receipts: this.receipts,
            counters: taskCounters(this.tasks, this.receipts),
        };
    }
}

function addMissingEdgeTask(builder: SemanticTaskBuilder, suggestion: GraphRebuildLinkSuggestion): void {
    builder.add({
        taskKind: 'graph_completion',
        proposalKind: 'missing_edge',
        sourceTargetIds: [`entity:${suggestion.sourceEntityId}`, `entity:${suggestion.targetEntityId}`],
        targetIds: [`missing-edge:${suggestion.sourceEntityId}:${suggestion.targetEntityId}`],
        sources: [source('graph_postprocess', suggestion.id, suggestion.kind, { manifold: suggestion.productLane || 'product' })],
        scores: [score('structural', suggestion.rerankScore ?? suggestion.confidence, suggestion.id, 'missing triangle or bridge completion score')],
        confidence: suggestion.rerankScore ?? suggestion.confidence,
        rationale: suggestion.rationale,
        evidenceIds: suggestion.evidenceIds,
    });
}

function addBridgeCompletionTask(builder: SemanticTaskBuilder, edge: GraphRebuildEmbeddingBackboneEdge): void {
    builder.add({
        taskKind: 'graph_completion',
        proposalKind: 'missing_edge',
        sourceTargetIds: [edge.sourceTargetId, edge.targetTargetId],
        targetIds: [`bridge:${edge.id}`],
        sources: [source('manifold', edge.id, edge.role, { manifold: 'product' })],
        scores: [
            score('manifold', edge.score, edge.id, 'embedding bridge score'),
            score('semantic', edge.semanticScore, edge.id, 'semantic bridge component'),
            score('structural', edge.structuralScore, edge.id, 'structural bridge component'),
        ],
        confidence: edge.score,
        rationale: edge.reason,
        evidenceIds: [edge.sourceTargetId, edge.targetTargetId],
    });
}

function addMissingIdentityTask(builder: SemanticTaskBuilder, suggestion: GraphRebuildResolutionSuggestion): void {
    builder.add({
        taskKind: 'graph_completion',
        proposalKind: suggestion.kind === 'possible_alias' ? 'identity_link' : 'missing_entity',
        sourceTargetIds: [`surface:${suggestion.surface}`, ...suggestion.entityIds.map((id) => `entity:${id}`)],
        targetIds: [`resolution:${suggestion.id}`],
        sources: [source('identity_linker', suggestion.id, suggestion.kind)],
        scores: [score('identity', 0.66, suggestion.id, 'resolution hygiene suggestion')],
        confidence: 0.66,
        rationale: [suggestion.rationale],
        evidenceIds: compact([suggestion.id, suggestion.noteId]),
    });
}

function addPatchCompletionTask(builder: SemanticTaskBuilder, patch: GraphRebuildFinalLinkPatch): void {
    builder.add({
        taskKind: 'graph_completion',
        proposalKind: 'identity_link',
        status: patch.status === 'applied' ? 'proposed' : 'prepared',
        sourceTargetIds: compact([patch.sourceEntityId, patch.targetEntityId, patch.canonicalEntityId].map((id) => id ? `entity:${id}` : '')),
        targetIds: [`patch:${patch.id}`],
        sources: [source('identity_linker', patch.sourceShadowLinkId, patch.kind)],
        scores: [score('identity', patch.confidence, patch.id, 'final linker reversible patch confidence')],
        confidence: patch.confidence,
        rationale: [patch.operation],
        evidenceIds: patch.evidenceIds,
    });
}

function addResolutionAnomalyTask(builder: SemanticTaskBuilder, suggestion: GraphRebuildResolutionSuggestion): void {
    const proposalKind: GraphSemanticProposalKind = suggestion.kind === 'possible_duplicate' ? 'duplicate_review' : 'contradiction_review';
    builder.add({
        taskKind: 'anomaly_detection',
        proposalKind,
        sourceTargetIds: [`surface:${suggestion.surface}`, ...suggestion.entityIds.map((id) => `entity:${id}`)],
        targetIds: [`anomaly:${suggestion.id}`],
        sources: [source('identity_linker', suggestion.id, suggestion.kind)],
        scores: [score('anomaly', 0.7, suggestion.id, 'resolution conflict review')],
        confidence: 0.7,
        rationale: [suggestion.rationale],
        evidenceIds: compact([suggestion.id, suggestion.noteId]),
    });
}

function addShadowAnomalyTask(builder: SemanticTaskBuilder, suggestion: GraphRebuildShadowLink): void {
    if (!suggestion.promotionBlockedReasons.length && suggestion.shadowKind !== 'bundle_dedupe') return;
    builder.add({
        taskKind: 'anomaly_detection',
        proposalKind: suggestion.shadowKind === 'bundle_dedupe' ? 'duplicate_review' : 'brittle_link',
        sourceTargetIds: compact([suggestion.mentionId, suggestion.candidateEntityId].map((id) => id ? `identity:${id}` : '')),
        targetIds: [`shadow:${suggestion.id}`],
        sources: [source('identity_linker', suggestion.id, suggestion.shadowKind)],
        scores: [score('anomaly', suggestion.confidence, suggestion.id, 'shadow link review pressure')],
        confidence: suggestion.confidence,
        rationale: [...suggestion.rationale, ...suggestion.promotionBlockedReasons],
        evidenceIds: suggestion.evidenceIds,
    });
}

function taskCounters(tasks: GraphSemanticTask[], receipts: GraphSemanticTaskReceipt[]): GraphSemanticTaskCounters {
    return {
        byTaskKind: countBy(tasks, (task) => task.taskKind),
        byProposalKind: countBy(tasks, (task) => task.proposalKind),
        bySourceKind: countBy(tasks.flatMap((task) => task.sources), (sourceRow) => sourceRow.kind),
        byStatus: countBy(tasks, (task) => task.status),
        byManifold: countBy(tasks.flatMap((task) => task.sources.map((sourceRow) => sourceRow.manifold || '').filter(Boolean)), (value) => value),
        sourceTargetCount: unique(tasks.flatMap((task) => task.sourceTargetIds)).length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        mutationAllowedCount: tasks.filter((task) => task.mutationAllowed).length + receipts.filter((receipt) => receipt.mutationAllowed).length,
    };
}

function source(kind: GraphSemanticTaskSourceKind, id: string, label: string, extra: Partial<GraphSemanticTaskSource> = {}): GraphSemanticTaskSource {
    return { kind, id, label, ...extra };
}

function score(kind: GraphSemanticTaskScoreKind, value: number, sourceId: string, rationale: string, weight = 1): GraphSemanticTaskScore {
    return { kind, score: value, weight, sourceId, rationale };
}

function sortedByConfidence<T extends { confidence: number }>(values: T[]): T[] {
    return [...values].sort((left, right) => right.confidence - left.confidence);
}

function taskRank(task: GraphSemanticTask): number {
    return task.confidence + task.scores.reduce((sum, row) => sum + row.score * row.weight, 0) / Math.max(1, task.scores.length);
}

function evidenceScore(count: number): number {
    return clamp(0.32 + Math.min(0.6, count * 0.08), 0.32, 0.92);
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
    return value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '').slice(0, 96) || 'x';
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
