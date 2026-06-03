import type {
    GraphManifoldCandidateContribution,
    GraphManifoldSpecializationSummary,
    GraphRebuildSnapshot,
    GraphSemanticCandidate,
    GraphSemanticCandidateKind,
    GraphSemanticCandidateSummary,
    GraphSemanticRerankCounters,
    GraphSemanticRerankDecision,
    GraphSemanticRerankInput,
    GraphSemanticRerankJudgment,
    GraphSemanticRerankLabel,
    GraphSemanticRerankLabelKind,
    GraphSemanticRerankReceipt,
    GraphSemanticRerankScore,
    GraphSemanticRerankScoreSource,
    GraphSemanticRerankSummary,
} from './graph-rebuild-snapshot';

const GLICLASS_INSTRUCT_MODEL_ID = 'knowledgator/gliclass-instruct-base-v1.0';
const RUNNER = 'gliclass-query-label-rerank' as const;
const MAX_RERANK_INPUTS = 192;
const MAX_PASSAGE_CHARS = 1800;
const SCORE_SOURCE: GraphSemanticRerankScoreSource = 'deterministic_calibration';

const LABELS: GraphSemanticRerankLabel[] = [
    label('strong_identity_alias', 'This candidate is a valid entity identity, alias, or full designation link.', 0.66, ['entity_link']),
    label('strong_relation_bridge', 'This candidate is a valid semantic relation bridge supported by evidence.', 0.64, ['relation_link']),
    label('strong_missing_frame', 'This candidate supports creating a missing event, state, or relation frame.', 0.62, ['missing_frame']),
    label('strong_causal_bridge', 'This candidate is a valid causal bridge or cause-effect chain.', 0.65, ['causal_bridge']),
    label('strong_temporal_bridge', 'This candidate is a valid temporal ordering or temporal chain.', 0.64, ['temporal_bridge']),
    label('strong_contradiction_review', 'This candidate should be reviewed for duplicate, contradiction, or brittle fact risk.', 0.62, ['contradiction_review']),
    label('strong_outlier_review', 'This candidate is a meaningful semantic outlier that deserves review instead of deletion.', 0.61, ['outlier_review']),
    label('defer_for_review', 'This candidate is ambiguous or partially supported and should be deferred for review.', 0.52, [
        'entity_link',
        'relation_link',
        'missing_frame',
        'causal_bridge',
        'temporal_bridge',
        'contradiction_review',
        'outlier_review',
    ]),
    label('reject_as_noise', 'This candidate should be rejected as noise because evidence is weak, broad, or unsupported.', 0.58, [
        'entity_link',
        'relation_link',
        'missing_frame',
        'causal_bridge',
        'temporal_bridge',
        'contradiction_review',
        'outlier_review',
    ]),
];

export function buildGraphSemanticRerankSummary(
    snapshot: GraphRebuildSnapshot,
    candidates: GraphSemanticCandidateSummary | undefined,
    manifolds: GraphManifoldSpecializationSummary | undefined,
    generatedAt = snapshot.builtAt,
): GraphSemanticRerankSummary {
    const manifoldById = new Map((manifolds?.contributions || []).map((row) => [row.id, row]));
    const builder = new SemanticRerankBuilder(snapshot.id, generatedAt);
    for (const candidate of selectCandidates(candidates?.candidates || [])) {
        const contributions = (candidate.manifoldContributionIds || [])
            .map((id) => manifoldById.get(id))
            .filter((row): row is GraphManifoldCandidateContribution => Boolean(row));
        builder.add(candidate, contributions);
    }
    const summary = builder.summary(candidates?.candidates || []);
    attachRerankJudgmentIds(candidates, summary);
    return summary;
}

function attachRerankJudgmentIds(
    candidates: GraphSemanticCandidateSummary | undefined,
    summary: GraphSemanticRerankSummary,
): void {
    if (!candidates) return;
    const idsByCandidate = new Map<string, string[]>();
    for (const judgment of summary.judgments) {
        const ids = idsByCandidate.get(judgment.candidateId) || [];
        ids.push(judgment.id);
        idsByCandidate.set(judgment.candidateId, ids);
    }
    for (const candidate of candidates.candidates) {
        const ids = idsByCandidate.get(candidate.id);
        if (ids?.length) candidate.semanticRerankJudgmentIds = ids;
    }
}

class SemanticRerankBuilder {
    private readonly inputs: GraphSemanticRerankInput[] = [];
    private readonly judgments: GraphSemanticRerankJudgment[] = [];
    private readonly receipts: GraphSemanticRerankReceipt[] = [];

    constructor(private readonly snapshotId: string, private readonly generatedAt: number) {}

    add(candidate: GraphSemanticCandidate, contributions: GraphManifoldCandidateContribution[]): void {
        if (this.inputs.length >= MAX_RERANK_INPUTS) return;
        const labels = labelsForCandidate(candidate.kind);
        const input = buildInput(candidate, contributions, labels);
        const scores = labels.map((row) => scoreLabel(candidate, contributions, row));
        const top = scores.sort((left, right) => right.score - left.score || left.labelId.localeCompare(right.labelId))[0];
        const calibratedScore = calibratedCandidateScore(candidate, contributions, top);
        const decision = decisionFor(top, calibratedScore, candidate);
        const judgmentId = `semantic-rerank:${slug(`${candidate.id}:${top.labelId}`)}`;
        const receiptId = `semantic-rerank-receipt:${slug(judgmentId)}`;
        this.inputs.push(input);
        this.judgments.push({
            id: judgmentId,
            candidateId: candidate.id,
            candidateKind: candidate.kind,
            inputId: input.id,
            decision,
            topLabelId: top.labelId,
            topLabelKind: top.labelKind,
            modelId: GLICLASS_INSTRUCT_MODEL_ID,
            runner: RUNNER,
            scoreSource: SCORE_SOURCE,
            relevanceScore: top.score,
            calibratedScore,
            scores,
            evidenceIds: candidate.evidenceIds,
            manifoldContributionIds: contributions.map((row) => row.id),
            rationale: judgmentRationale(candidate, contributions, top, decision),
            reversibleReceiptId: receiptId,
        });
        this.receipts.push({
            id: receiptId,
            judgmentId,
            candidateId: candidate.id,
            reversible: true,
            mutationAllowed: false,
            invariant: 'phase4_no_topology_commit',
            evidenceIds: candidate.evidenceIds.slice(0, 12),
            undoHint: 'no graph mutation was performed; discard this rerank judgment to undo',
            detail: `${candidate.kind} ${decision} via ${top.labelKind} at ${Math.round(calibratedScore * 100)}%`,
        });
    }

    summary(allCandidates: GraphSemanticCandidate[]): GraphSemanticRerankSummary {
        const judgments = this.judgments.sort((left, right) =>
            decisionRank(left.decision) - decisionRank(right.decision)
            || right.calibratedScore - left.calibratedScore
            || left.id.localeCompare(right.id));
        return {
            schemaVersion: 'phoenix-semantic-rerank/v1',
            generatedAt: this.generatedAt,
            sourceSnapshotId: this.snapshotId,
            modelId: GLICLASS_INSTRUCT_MODEL_ID,
            runner: RUNNER,
            scoreSource: SCORE_SOURCE,
            labels: LABELS,
            inputs: this.inputs,
            judgments,
            receipts: this.receipts,
            counters: rerankCounters(allCandidates, this.inputs, judgments, this.receipts),
        };
    }
}

function selectCandidates(candidates: GraphSemanticCandidate[]): GraphSemanticCandidate[] {
    return [...candidates]
        .sort((left, right) =>
            right.rank - left.rank
            || right.confidence - left.confidence
            || left.id.localeCompare(right.id))
        .slice(0, MAX_RERANK_INPUTS);
}

function buildInput(
    candidate: GraphSemanticCandidate,
    contributions: GraphManifoldCandidateContribution[],
    labels: GraphSemanticRerankLabel[],
): GraphSemanticRerankInput {
    return {
        id: `semantic-rerank-input:${slug(candidate.id)}`,
        candidateId: candidate.id,
        candidateKind: candidate.kind,
        passage: candidatePassage(candidate, contributions).slice(0, MAX_PASSAGE_CHARS),
        labelIds: labels.map((row) => row.id),
        queryLabels: labels.map((row) => row.query),
        manifoldContributionIds: contributions.map((row) => row.id),
        evidenceIds: candidate.evidenceIds.slice(0, 12),
        maxPassageChars: MAX_PASSAGE_CHARS,
    };
}

function candidatePassage(
    candidate: GraphSemanticCandidate,
    contributions: GraphManifoldCandidateContribution[],
): string {
    const sources = candidate.sources.map((source) =>
        compact([source.kind, source.label, source.manifold ? `manifold=${source.manifold}` : '']).join(':'));
    const manifoldText = contributions.map((row) =>
        `${row.manifold}/${row.manifoldRole} score=${row.score} rule=${row.ruleId} rationale=${row.rationale}`);
    const scoreText = candidate.scores.map((row) => `${row.kind}:${row.score}:${row.rationale}`);
    return compact([
        `candidate_kind=${candidate.kind}`,
        `status=${candidate.status}`,
        `rank=${candidate.rank}`,
        `confidence=${candidate.confidence}`,
        `noise=${candidate.noiseScore}`,
        `source_targets=${candidate.sourceTargetIds.join(',')}`,
        `targets=${candidate.targetIds.join(',')}`,
        `evidence_count=${candidate.evidenceIds.length}`,
        `sources=${sources.join(' | ')}`,
        `scores=${scoreText.join(' | ')}`,
        `manifold_contributions=${manifoldText.join(' | ')}`,
        `rationale=${candidate.rationale.join(' | ')}`,
    ]).join('\n');
}

function scoreLabel(
    candidate: GraphSemanticCandidate,
    contributions: GraphManifoldCandidateContribution[],
    labelRow: GraphSemanticRerankLabel,
): GraphSemanticRerankScore {
    const support = supportScore(candidate, contributions);
    const ambiguity = ambiguityScore(candidate, contributions);
    const noise = noisePressure(candidate);
    let score: number;
    if (labelRow.kind === 'defer_for_review') {
        score = clamp(0.28 + ambiguity * 0.42 + support * 0.18 + noise * 0.12, 0, 1);
    } else if (labelRow.kind === 'reject_as_noise') {
        score = clamp(0.18 + noise * 0.58 + (1 - support) * 0.18 + (candidate.status === 'blocked' ? 0.14 : 0), 0, 1);
    } else {
        score = clamp(kindLabelBoost(candidate.kind, labelRow.kind) + support * 0.78 - noise * 0.16, 0, 1);
    }
    return {
        labelId: labelRow.id,
        labelKind: labelRow.kind,
        query: labelRow.query,
        score: round(score),
        source: SCORE_SOURCE,
        rationale: SCORE_SOURCE === 'deterministic_calibration'
            ? 'local calibration shell for GLiClass query-label runner'
            : 'GLiClass query-label relevance score',
    };
}

function supportScore(candidate: GraphSemanticCandidate, contributions: GraphManifoldCandidateContribution[]): number {
    const manifoldMax = contributions.length ? Math.max(...contributions.map((row) => row.score)) : 0;
    const evidenceLift = Math.min(0.16, candidate.evidenceIds.length * 0.012);
    const sourceLift = Math.min(0.1, candidate.sources.length * 0.01);
    return clamp(candidate.rank * 0.38 + candidate.confidence * 0.34 + manifoldMax * 0.18 + evidenceLift + sourceLift, 0, 1);
}

function ambiguityScore(candidate: GraphSemanticCandidate, contributions: GraphManifoldCandidateContribution[]): number {
    const broadTargetPenalty = Math.min(0.24, Math.max(0, candidate.sourceTargetIds.length - 4) * 0.03);
    const manifoldSpread = Math.min(0.18, new Set(contributions.map((row) => row.manifold)).size * 0.03);
    const statusLift = candidate.status === 'deferred' ? 0.18 : candidate.status === 'blocked' ? 0.26 : 0;
    return clamp(candidate.noiseScore * 0.45 + broadTargetPenalty + manifoldSpread + statusLift, 0, 1);
}

function noisePressure(candidate: GraphSemanticCandidate): number {
    const weakEvidence = candidate.evidenceIds.length ? 0 : 0.14;
    const lowRank = Math.max(0, 0.58 - candidate.rank) * 0.8;
    return clamp(candidate.noiseScore * 0.64 + weakEvidence + lowRank, 0, 1);
}

function calibratedCandidateScore(
    candidate: GraphSemanticCandidate,
    contributions: GraphManifoldCandidateContribution[],
    top: GraphSemanticRerankScore,
): number {
    const support = supportScore(candidate, contributions);
    return round(clamp(top.score * 0.62 + support * 0.28 + (1 - candidate.noiseScore) * 0.1, 0, 1));
}

function decisionFor(
    top: GraphSemanticRerankScore,
    calibratedScore: number,
    candidate: GraphSemanticCandidate,
): GraphSemanticRerankDecision {
    if (top.labelKind === 'reject_as_noise') return calibratedScore >= 0.58 ? 'reject' : 'defer';
    if (top.labelKind === 'defer_for_review') return 'defer';
    const threshold = labelById(top.labelId).threshold;
    if (calibratedScore >= threshold && candidate.status !== 'blocked') {
        return top.labelKind.includes('review') ? 'review' : 'accept';
    }
    return top.labelKind.includes('review') ? 'review' : 'defer';
}

function judgmentRationale(
    candidate: GraphSemanticCandidate,
    contributions: GraphManifoldCandidateContribution[],
    top: GraphSemanticRerankScore,
    decision: GraphSemanticRerankDecision,
): string[] {
    const manifolds = [...new Set(contributions.map((row) => row.manifold))].sort();
    return compact([
        `query_label:${top.labelKind}`,
        `decision:${decision}`,
        `score_source:${SCORE_SOURCE}`,
        `candidate_rank:${candidate.rank}`,
        `candidate_noise:${candidate.noiseScore}`,
        manifolds.length ? `manifolds:${manifolds.join(',')}` : 'manifolds:none',
    ]);
}

function labelsForCandidate(kind: GraphSemanticCandidateKind): GraphSemanticRerankLabel[] {
    const specific = LABELS.find((row) => row.candidateKinds.includes(kind) && row.kind !== 'defer_for_review' && row.kind !== 'reject_as_noise');
    return [
        ...(specific ? [specific] : []),
        labelByKind('defer_for_review'),
        labelByKind('reject_as_noise'),
    ];
}

function kindLabelBoost(candidateKind: GraphSemanticCandidateKind, labelKind: GraphSemanticRerankLabelKind): number {
    const expected: Record<GraphSemanticCandidateKind, GraphSemanticRerankLabelKind> = {
        entity_link: 'strong_identity_alias',
        relation_link: 'strong_relation_bridge',
        missing_frame: 'strong_missing_frame',
        causal_bridge: 'strong_causal_bridge',
        temporal_bridge: 'strong_temporal_bridge',
        contradiction_review: 'strong_contradiction_review',
        outlier_review: 'strong_outlier_review',
    };
    return expected[candidateKind] === labelKind ? 0.16 : 0.04;
}

function rerankCounters(
    candidates: GraphSemanticCandidate[],
    inputs: GraphSemanticRerankInput[],
    judgments: GraphSemanticRerankJudgment[],
    receipts: GraphSemanticRerankReceipt[],
): GraphSemanticRerankCounters {
    const averageCalibratedScore = judgments.length
        ? round(judgments.reduce((sum, row) => sum + row.calibratedScore, 0) / judgments.length)
        : 0;
    return {
        byDecision: countBy(judgments, (row) => row.decision),
        byTopLabelKind: countBy(judgments, (row) => row.topLabelKind),
        byCandidateKind: countBy(judgments, (row) => row.candidateKind),
        byScoreSource: countBy(judgments, (row) => row.scoreSource),
        inputCount: inputs.length,
        judgmentCount: judgments.length,
        receiptCount: receipts.length,
        plannedModelCalls: inputs.reduce((sum, input) => sum + input.queryLabels.length, 0),
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        mutationAllowedCount: receipts.filter((receipt) => receipt.mutationAllowed).length,
        maxInputs: Math.min(MAX_RERANK_INPUTS, candidates.length),
        averageCalibratedScore,
    };
}

function labelByKind(kind: GraphSemanticRerankLabelKind): GraphSemanticRerankLabel {
    return LABELS.find((row) => row.kind === kind)!;
}

function labelById(id: string): GraphSemanticRerankLabel {
    return LABELS.find((row) => row.id === id)!;
}

function label(
    kind: GraphSemanticRerankLabelKind,
    query: string,
    threshold: number,
    candidateKinds: GraphSemanticCandidateKind[],
): GraphSemanticRerankLabel {
    return {
        id: `gliclass-label:${kind}`,
        kind,
        query,
        threshold,
        candidateKinds,
    };
}

function decisionRank(decision: GraphSemanticRerankDecision): number {
    if (decision === 'accept') return 0;
    if (decision === 'review') return 1;
    if (decision === 'defer') return 2;
    return 3;
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

function slug(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '').slice(0, 112) || 'x';
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
