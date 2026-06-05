import type {
    GraphRebuildEdge,
    GraphRebuildSnapshot,
    GraphSemanticAdjudicationCounters,
    GraphSemanticAdjudicationDecision,
    GraphSemanticAdjudicationDAGSummary,
    GraphSemanticAdjudicationMutation,
    GraphSemanticAdjudicationReceipt,
    GraphSemanticAdjudicationScoringBundle,
    GraphSemanticAdjudicationState,
    GraphSemanticCandidate,
    GraphSemanticRerankJudgment,
} from './graph-rebuild-snapshot';

const MAX_DECISIONS = 192;
const ACCEPT_THRESHOLD = 0.64;

export function buildGraphSemanticAdjudicationDAGSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphSemanticAdjudicationDAGSummary {
    const candidates = snapshot.semanticCandidateSummary?.candidates || [];
    const judgments = new Map((snapshot.semanticRerankSummary?.judgments || []).map((row) => [row.candidateId, row]));
    const builder = new SemanticAdjudicationBuilder(snapshot, generatedAt);
    for (const candidate of candidates.slice(0, MAX_DECISIONS)) {
        builder.add(candidate, judgments.get(candidate.id));
    }
    return builder.summary();
}

export function applyGraphSemanticAdjudicationMutations(
    snapshot: GraphRebuildSnapshot,
    summary: GraphSemanticAdjudicationDAGSummary | undefined,
): void {
    if (!summary) return;
    const seen = new Set(snapshot.edges.map((edge) => edge.id));
    for (const mutation of summary.mutations) {
        if (mutation.status !== 'applied' || mutation.operation !== 'add_semantic_edge') continue;
        if (!mutation.createdEdge || seen.has(mutation.createdEdge.id)) continue;
        snapshot.edges.push(mutation.createdEdge);
        seen.add(mutation.createdEdge.id);
    }
    snapshot.edges.sort((left, right) =>
        right.weight - left.weight
        || left.type.localeCompare(right.type)
        || left.id.localeCompare(right.id));
}

class SemanticAdjudicationBuilder {
    private readonly decisions: GraphSemanticAdjudicationDecision[] = [];
    private readonly mutations: GraphSemanticAdjudicationMutation[] = [];
    private readonly receipts: GraphSemanticAdjudicationReceipt[] = [];
    private readonly acceptedKeys = new Set<string>();

    constructor(private readonly snapshot: GraphRebuildSnapshot, private readonly generatedAt: number) {}

    add(candidate: GraphSemanticCandidate, judgment: GraphSemanticRerankJudgment | undefined): void {
        const proposalId = `adjudication-proposal:${slug(candidate.id)}`;
        const supportedId = `adjudication-supported:${slug(candidate.id)}`;
        const scoringBundle = scoringBundleFor(candidate, judgment);
        const mutationDraft = mutationFor(this.snapshot, candidate, judgment, this.generatedAt);
        const duplicateKey = mutationDraft ? mutationKey(mutationDraft) : '';
        const alreadyAccepted = duplicateKey ? this.acceptedKeys.has(duplicateKey) : false;
        const state = decisionState(candidate, judgment, mutationDraft, alreadyAccepted);
        const receipt = receiptFor(candidate, state, mutationDraft, judgment);
        const mutation = state === 'accepted' && mutationDraft
            ? { ...mutationDraft, undoReceiptId: receipt.id }
            : undefined;

        if (duplicateKey && state === 'accepted') this.acceptedKeys.add(duplicateKey);
        if (mutation) this.mutations.push(mutation);
        this.receipts.push(receipt);
        this.decisions.push({
            id: `adjudication-decision:${slug(candidate.id)}`,
            proposalNodeId: proposalId,
            supportedNodeId: supportedId,
            candidateId: candidate.id,
            candidateKind: candidate.kind,
            judgmentId: judgment?.id,
            state,
            sourceHypothesis: sourceHypothesis(candidate),
            evidenceTargetIds: evidenceTargets(candidate),
            scoringBundle,
            rationale: rationaleFor(candidate, judgment, state, mutationDraft, alreadyAccepted),
            undoReceiptId: receipt.id,
            mutationId: mutation?.id,
            affectedGraphAtomIds: mutation?.affectedGraphAtomIds || [],
            affectedGraphFactIds: mutation?.affectedGraphFactIds || [],
            ledgerOnly: state !== 'accepted',
            createdAt: this.generatedAt,
        });
    }

    summary(): GraphSemanticAdjudicationDAGSummary {
        const decisions = this.decisions.sort((left, right) =>
            stateRank(left.state) - stateRank(right.state)
            || right.scoringBundle.finalScore - left.scoringBundle.finalScore
            || left.id.localeCompare(right.id));
        return {
            schemaVersion: 'phoenix-semantic-adjudication-dag/v1',
            generatedAt: this.generatedAt,
            sourceSnapshotId: this.snapshot.id,
            states: ['proposed', 'supported', 'accepted', 'deferred', 'rejected', 'invalidated', 'superseded'],
            dagEdges: decisions.flatMap((decision) => dagEdgesFor(decision)),
            decisions,
            mutations: this.mutations,
            receipts: this.receipts,
            counters: adjudicationCounters(decisions, this.mutations, this.receipts),
        };
    }
}

function decisionState(
    candidate: GraphSemanticCandidate,
    judgment: GraphSemanticRerankJudgment | undefined,
    mutation: GraphSemanticAdjudicationMutation | undefined,
    alreadyAccepted: boolean,
): GraphSemanticAdjudicationState {
    if (candidate.status === 'blocked') return 'invalidated';
    if (alreadyAccepted) return 'superseded';
    if (!judgment) return 'deferred';
    if (judgment.decision === 'reject') return 'rejected';
    if (judgment.decision === 'defer' || judgment.decision === 'review') return 'deferred';
    if (judgment.calibratedScore < ACCEPT_THRESHOLD) return 'supported';
    return mutation ? 'accepted' : 'supported';
}

function mutationFor(
    snapshot: GraphRebuildSnapshot,
    candidate: GraphSemanticCandidate,
    judgment: GraphSemanticRerankJudgment | undefined,
    createdAt: number,
): GraphSemanticAdjudicationMutation | undefined {
    if (!judgment || judgment.decision !== 'accept') return undefined;
    if (candidate.kind === 'missing_frame' || candidate.kind === 'contradiction_review' || candidate.kind === 'outlier_review') return undefined;
    const pair = entityPairFor(snapshot, candidate);
    if (!pair) return undefined;
    const edgeType = edgeTypeFor(candidate);
    const edgeId = `semantic-adjudication:${edgeType}:${slug(`${candidate.id}:${pair[0]}:${pair[1]}`)}`;
    const factId = `fact:semantic-adjudication:${slug(edgeId)}`;
    const atomIds = [`atom:entity:${pair[0]}`, `atom:entity:${pair[1]}`];
    const edge: GraphRebuildEdge = {
        id: edgeId,
        sourceId: pair[0],
        targetId: pair[1],
        type: edgeType,
        weight: semanticEdgeWeight(candidate, judgment),
        confidence: judgment.calibratedScore,
        evidenceAnchorIds: candidate.evidenceIds.slice(0, 16),
        scopeKeys: [`semantic-adjudication:${snapshot.scopeId}`],
        noteIds: evidenceNoteIds(snapshot, candidate),
    };
    return {
        id: `adjudication-mutation:${slug(edgeId)}`,
        decisionId: `adjudication-decision:${slug(candidate.id)}`,
        candidateId: candidate.id,
        operation: 'add_semantic_edge',
        status: 'applied',
        createdEdgeId: edge.id,
        createdFactIds: [factId],
        affectedGraphAtomIds: atomIds,
        affectedGraphFactIds: [factId],
        createdEdge: edge,
        undoReceiptId: '',
        reversiblePatch: {
            undoOperation: 'remove_semantic_edge_and_fact',
            removeEdgeId: edge.id,
            removeFactIds: [factId],
        },
        createdAt,
    };
}

function entityPairFor(snapshot: GraphRebuildSnapshot, candidate: GraphSemanticCandidate): [string, string] | null {
    const anchors = new Map(snapshot.entityAnchors.map((anchor) => [anchor.id, anchor.entityId]));
    const nodeIds = snapshot.nodes.map((node) => node.entityId);
    const found: string[] = [];
    const tokens = [
        ...candidate.sourceTargetIds,
        ...candidate.targetIds,
        ...candidate.evidenceIds,
        ...candidate.sources.flatMap((source) => [source.id, source.label]),
    ];
    for (const token of tokens) {
        const anchorEntityId = anchors.get(token);
        if (anchorEntityId) pushUnique(found, anchorEntityId);
        for (const nodeId of nodeIds) {
            if (token === nodeId || token.endsWith(`:${nodeId}`) || token.includes(`entity:${nodeId}`)) {
                pushUnique(found, nodeId);
            }
        }
        if (found.length >= 2) break;
    }
    return found.length >= 2 && found[0] !== found[1] ? [found[0], found[1]] : null;
}

function scoringBundleFor(
    candidate: GraphSemanticCandidate,
    judgment: GraphSemanticRerankJudgment | undefined,
): GraphSemanticAdjudicationScoringBundle {
    const modelScore = judgment?.relevanceScore || 0;
    const calibratedScore = judgment?.calibratedScore || 0;
    const receiptScore = candidate.rank * 0.46 + candidate.confidence * 0.24 + (1 - candidate.noiseScore) * 0.12;
    const finalScore = round(Math.max(calibratedScore, receiptScore));
    return {
        candidateRank: candidate.rank,
        candidateConfidence: candidate.confidence,
        candidateNoise: candidate.noiseScore,
        rerankRelevance: modelScore,
        rerankCalibrated: calibratedScore,
        rerankSource: judgment?.scoreSource || 'missing_rerank',
        topLabelKind: judgment?.topLabelKind,
        finalScore,
        scoreParts: [
            { id: 'candidate_rank', score: candidate.rank, weight: 0.46 },
            { id: 'candidate_confidence', score: candidate.confidence, weight: 0.24 },
            { id: 'candidate_noise_inverse', score: round(1 - candidate.noiseScore), weight: 0.12 },
            { id: 'rerank_calibrated', score: calibratedScore, weight: 0.18 },
        ],
    };
}

function receiptFor(
    candidate: GraphSemanticCandidate,
    state: GraphSemanticAdjudicationState,
    mutation: GraphSemanticAdjudicationMutation | undefined,
    judgment: GraphSemanticRerankJudgment | undefined,
): GraphSemanticAdjudicationReceipt {
    return {
        id: `adjudication-receipt:${slug(candidate.id)}`,
        candidateId: candidate.id,
        judgmentId: judgment?.id,
        state,
        reversible: true,
        mutationAllowed: state === 'accepted',
        invariant: state === 'accepted' ? 'phase5_reversible_topology_commit' : 'phase5_ledger_only_no_topology_commit',
        evidenceTargetIds: evidenceTargets(candidate),
        affectedGraphAtomIds: state === 'accepted' ? mutation?.affectedGraphAtomIds || [] : [],
        affectedGraphFactIds: state === 'accepted' ? mutation?.affectedGraphFactIds || [] : [],
        undoHint: mutation
            ? `remove edge ${mutation.createdEdgeId} and facts ${mutation.createdFactIds.join(',')}`
            : 'ledger-only decision; remove this decision row to undo evaluation',
        detail: `${candidate.kind} ${state}${judgment ? ` from ${judgment.topLabelKind}` : ' without rerank judgment'}`,
    };
}

function dagEdgesFor(decision: GraphSemanticAdjudicationDecision): Array<{ from: string; to: string; label: string }> {
    const edges = [{ from: decision.proposalNodeId, to: decision.supportedNodeId, label: 'score_receipts' }];
    edges.push({ from: decision.supportedNodeId, to: `adjudication-state:${decision.state}:${decision.id}`, label: decision.state });
    if (decision.mutationId) edges.push({ from: `adjudication-state:${decision.state}:${decision.id}`, to: decision.mutationId, label: 'commit' });
    return edges;
}

function adjudicationCounters(
    decisions: GraphSemanticAdjudicationDecision[],
    mutations: GraphSemanticAdjudicationMutation[],
    receipts: GraphSemanticAdjudicationReceipt[],
): GraphSemanticAdjudicationCounters {
    return {
        byState: countBy(decisions, (row) => row.state),
        byCandidateKind: countBy(decisions, (row) => row.candidateKind),
        decisionCount: decisions.length,
        mutationCount: mutations.length,
        appliedMutationCount: mutations.filter((row) => row.status === 'applied').length,
        ledgerOnlyCount: decisions.filter((row) => row.ledgerOnly).length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((row) => row.reversible).length,
        topologyCommitCount: receipts.filter((row) => row.mutationAllowed).length,
    };
}

function sourceHypothesis(candidate: GraphSemanticCandidate): string {
    return [
        candidate.kind,
        candidate.sources.slice(0, 3).map((source) => `${source.kind}:${source.label}`).join(' | '),
    ].filter(Boolean).join(' from ');
}

function evidenceTargets(candidate: GraphSemanticCandidate): string[] {
    return unique([...candidate.evidenceIds, ...candidate.sourceTargetIds, ...candidate.targetIds]).slice(0, 32);
}

function rationaleFor(
    candidate: GraphSemanticCandidate,
    judgment: GraphSemanticRerankJudgment | undefined,
    state: GraphSemanticAdjudicationState,
    mutation: GraphSemanticAdjudicationMutation | undefined,
    alreadyAccepted: boolean,
): string[] {
    return [
        `state:${state}`,
        judgment ? `rerank:${judgment.decision}:${judgment.calibratedScore}` : 'rerank:missing',
        alreadyAccepted ? 'superseded_by_prior_equivalent_mutation' : '',
        mutation ? `topology_commit:${mutation.operation}:${mutation.createdEdgeId}` : 'ledger_only:no_safe_topology_target',
        ...candidate.rationale.slice(0, 5),
    ].filter(Boolean);
}

function edgeTypeFor(candidate: GraphSemanticCandidate): string {
    if (candidate.kind === 'causal_bridge') return 'semantic-causal-bridge';
    if (candidate.kind === 'temporal_bridge') return 'semantic-temporal-bridge';
    if (candidate.kind === 'entity_link') return 'semantic-identity-link';
    return 'semantic-relation-link';
}

function mutationKey(mutation: GraphSemanticAdjudicationMutation): string {
    const edge = mutation.createdEdge;
    return edge ? `${edge.sourceId}|${edge.targetId}|${edge.type}` : mutation.id;
}

function semanticEdgeWeight(
    candidate: GraphSemanticCandidate,
    judgment: GraphSemanticRerankJudgment,
): number {
    return Math.max(1, Math.round(Math.max(candidate.rank, judgment.calibratedScore)));
}

function evidenceNoteIds(snapshot: GraphRebuildSnapshot, candidate: GraphSemanticCandidate): string[] {
    const noteIds = new Set<string>();
    const anchors = new Map(snapshot.entityAnchors.map((anchor) => [anchor.id, anchor.noteId]));
    for (const id of candidate.evidenceIds) {
        const noteId = anchors.get(id);
        if (noteId) noteIds.add(noteId);
    }
    return [...noteIds].sort();
}

function stateRank(state: GraphSemanticAdjudicationState): number {
    return ['accepted', 'supported', 'deferred', 'rejected', 'invalidated', 'superseded', 'proposed'].indexOf(state);
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function pushUnique(values: string[], value: string): void {
    if (!values.includes(value)) values.push(value);
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}

function slug(value: string): string {
    const normalized = value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '') || 'x';
    return `${normalized.slice(0, 112)}:${stableHash(value)}`;
}

function stableHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
