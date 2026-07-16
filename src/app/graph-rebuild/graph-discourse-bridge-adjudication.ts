import type { GraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';
import type {
    GraphDiscourseBridgeAdjudicationCounters,
    GraphDiscourseBridgeAdjudicationDecision,
    GraphDiscourseBridgeAdjudicationReceipt,
    GraphDiscourseBridgeAdjudicationScoringBundle,
    GraphDiscourseBridgeAdjudicationState,
    GraphDiscourseBridgeCandidate,
    GraphDiscourseBridgeEvalRow,
    GraphDiscourseBridgeRerankJudgment,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export interface GraphDiscourseBridgeAdjudicationSummary {
    schemaVersion: 'phoenix-discourse-bridge-adjudication/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    sourceCandidateSummaryId: string;
    invariant: 'discourse_bridge_decisions_are_ledger_only';
    states: GraphDiscourseBridgeAdjudicationState[];
    dagEdges: Array<{ from: string; to: string; label: string }>;
    decisions: GraphDiscourseBridgeAdjudicationDecision[];
    receipts: GraphDiscourseBridgeAdjudicationReceipt[];
    compactDecisionLedger: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            state: GraphDiscourseBridgeAdjudicationState;
            candidateKind: string;
            score: number;
            judgmentDecision: string;
            evalKind: string;
            evidence: number;
            changedAtoms: number;
            changedFacts: number;
            changedEdges: number;
            flags: string[];
        }>;
    };
    counters: GraphDiscourseBridgeAdjudicationCounters;
}

const STATES: GraphDiscourseBridgeAdjudicationState[] = [
    'proposed',
    'supported',
    'accepted',
    'deferred',
    'rejected',
    'invalidated',
    'superseded',
];
const MAX_DECISIONS = 160;
const ACCEPT_THRESHOLD = 0.64;
const SUPPORT_THRESHOLD = 0.56;

export function buildGraphDiscourseBridgeAdjudicationSummary(
    snapshot: GraphRebuildSnapshot,
    candidateSummary: GraphDiscourseBridgeCandidateSummary | undefined = snapshot.discourseBridgeCandidateSummary,
    generatedAt = snapshot.builtAt,
): GraphDiscourseBridgeAdjudicationSummary {
    const judgments = new Map((candidateSummary?.judgments || []).map((row) => [row.candidateId, row]));
    const evalRows = new Map((candidateSummary?.evalRows || []).map((row) => [row.candidateId, row]));
    const builder = new DiscourseBridgeAdjudicationBuilder(generatedAt);
    for (const candidate of (candidateSummary?.candidates || []).slice(0, MAX_DECISIONS)) {
        builder.add(candidate, judgments.get(candidate.id), evalRows.get(candidate.id));
    }
    return builder.summary(snapshot, candidateSummary);
}

class DiscourseBridgeAdjudicationBuilder {
    private readonly decisions: GraphDiscourseBridgeAdjudicationDecision[] = [];
    private readonly receipts: GraphDiscourseBridgeAdjudicationReceipt[] = [];
    private readonly keeperKeys = new Set<string>();

    constructor(private readonly generatedAt: number) {}

    add(
        candidate: GraphDiscourseBridgeCandidate,
        judgment: GraphDiscourseBridgeRerankJudgment | undefined,
        evalRow: GraphDiscourseBridgeEvalRow | undefined,
    ): void {
        const scoringBundle = scoringBundleFor(candidate, judgment, evalRow);
        const duplicateKey = bridgeKey(candidate);
        const duplicate = this.keeperKeys.has(duplicateKey);
        const baseState = decisionState(candidate, judgment, evalRow, scoringBundle);
        const state = duplicate && (baseState === 'accepted' || baseState === 'supported')
            ? 'superseded'
            : baseState;
        const receipt = receiptFor(candidate, judgment, evalRow, state);
        if ((state === 'accepted' || state === 'supported') && duplicateKey) {
            this.keeperKeys.add(duplicateKey);
        }
        this.receipts.push(receipt);
        this.decisions.push({
            id: `discourse-adjudication-decision:${slug(candidate.id)}`,
            proposalNodeId: `discourse-adjudication-proposal:${slug(candidate.id)}`,
            supportedNodeId: `discourse-adjudication-supported:${slug(candidate.id)}`,
            candidateId: candidate.id,
            candidateKind: candidate.kind,
            sourceBridgeId: candidate.sourceBridgeId,
            sourceClusterId: candidate.sourceClusterId,
            judgmentId: judgment?.id,
            evalRowId: evalRow?.id,
            state,
            sourceHypothesis: sourceHypothesis(candidate),
            evidenceTargetIds: evidenceTargets(candidate, judgment, evalRow),
            scoringBundle,
            rationale: rationaleFor(candidate, judgment, evalRow, state, duplicate),
            undoReceiptId: receipt.id,
            affectedGraphAtomIds: [],
            affectedGraphFactIds: [],
            ledgerOnly: true,
            mutationAllowed: false,
            createdAt: this.generatedAt,
        });
    }

    summary(
        snapshot: GraphRebuildSnapshot,
        candidateSummary: GraphDiscourseBridgeCandidateSummary | undefined,
    ): GraphDiscourseBridgeAdjudicationSummary {
        const decisions = [...this.decisions].sort((left, right) =>
            stateRank(left.state) - stateRank(right.state)
            || right.scoringBundle.finalScore - left.scoringBundle.finalScore
            || left.id.localeCompare(right.id));
        return {
            schemaVersion: 'phoenix-discourse-bridge-adjudication/v1',
            generatedAt: this.generatedAt,
            sourceSnapshotId: snapshot.id,
            sourceCandidateSummaryId: candidateSummary
                ? `${candidateSummary.sourceSnapshotId}:discourse-bridge-candidates:${candidateSummary.generatedAt}`
                : `${snapshot.id}:discourse-bridge-candidates:missing`,
            invariant: 'discourse_bridge_decisions_are_ledger_only',
            states: STATES,
            dagEdges: decisions.flatMap((decision) => dagEdgesFor(decision)),
            decisions,
            receipts: this.receipts,
            compactDecisionLedger: compactDecisionLedger(snapshot, decisions),
            counters: counters(decisions, this.receipts),
        };
    }
}

function decisionState(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
    scoringBundle: GraphDiscourseBridgeAdjudicationScoringBundle,
): GraphDiscourseBridgeAdjudicationState {
    if (candidate.status === 'rejected') return 'invalidated';
    if (!judgment) return 'invalidated';
    if (judgment.decision === 'reject') return 'rejected';
    if (judgment.decision === 'defer') return 'deferred';
    if (judgment.decision === 'review') {
        return scoringBundle.finalScore >= SUPPORT_THRESHOLD ? 'supported' : 'deferred';
    }
    if (judgment.decision === 'accept') {
        if (scoringBundle.finalScore >= ACCEPT_THRESHOLD && evalRow?.passed !== false) return 'accepted';
        if (scoringBundle.finalScore >= SUPPORT_THRESHOLD) return 'supported';
    }
    return 'deferred';
}

function scoringBundleFor(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
): GraphDiscourseBridgeAdjudicationScoringBundle {
    const rerankRelevance = judgment?.relevanceScore || 0;
    const rerankCalibrated = judgment?.calibratedScore || 0;
    const evalScore = evalRow?.score || 0;
    const evalPassedScore = evalRow?.passed ? 1 : 0;
    const decisionBoost = judgment?.decision === 'accept' ? 0.04 : judgment?.decision === 'reject' ? -0.12 : 0;
    const statusPenalty = candidate.status === 'deferred' ? -0.05 : candidate.status === 'rejected' ? -0.18 : 0;
    const finalScore = round(
        candidate.score * 0.28
        + candidate.scoringBundle.finalScore * 0.24
        + rerankCalibrated * 0.26
        + rerankRelevance * 0.1
        + evalPassedScore * 0.08
        + decisionBoost
        + statusPenalty,
    );
    return {
        candidateScore: round(candidate.score),
        spineFinalScore: round(candidate.scoringBundle.finalScore),
        rerankRelevance: round(rerankRelevance),
        rerankCalibrated: round(rerankCalibrated),
        rerankSource: judgment?.scoreSource || 'missing_rerank',
        topLabelKind: judgment?.topLabelKind,
        evalScore: round(evalScore),
        evalPassed: Boolean(evalRow?.passed),
        finalScore,
        scoreParts: [
            { id: 'candidate_score', score: round(candidate.score), weight: 0.28 },
            { id: 'spine_final_score', score: round(candidate.scoringBundle.finalScore), weight: 0.24 },
            { id: 'rerank_calibrated', score: round(rerankCalibrated), weight: 0.26 },
            { id: 'rerank_relevance', score: round(rerankRelevance), weight: 0.1 },
            { id: 'eval_passed', score: evalPassedScore, weight: 0.08 },
        ],
    };
}

function receiptFor(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
    state: GraphDiscourseBridgeAdjudicationState,
): GraphDiscourseBridgeAdjudicationReceipt {
    return {
        id: `discourse-adjudication-receipt:${slug(candidate.id)}`,
        candidateId: candidate.id,
        judgmentId: judgment?.id,
        evalRowId: evalRow?.id,
        state,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_bridge_adjudication_ledger_only',
        evidenceTargetIds: evidenceTargets(candidate, judgment, evalRow),
        affectedGraphAtomIds: [],
        affectedGraphFactIds: [],
        undoHint: 'drop this discourse adjudication row; no graph edge or fact exists',
        detail: `${candidate.kind} ${state}${judgment ? ` from ${judgment.topLabelKind}` : ' without judgment'}`,
    };
}

function sourceHypothesis(candidate: GraphDiscourseBridgeCandidate): string {
    const source = candidate.sourceBridgeId ? `bridge:${candidate.sourceBridgeId}` : `cluster:${candidate.sourceClusterId || 'unknown'}`;
    return `${candidate.kind} ${source} proposes ${candidate.sourceTargetId} -> ${candidate.targetTargetId}`;
}

function evidenceTargets(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
): string[] {
    return unique([
        candidate.sourceTargetId,
        candidate.targetTargetId,
        ...candidate.evidenceTargetIds,
        ...(judgment?.evidenceTargetIds || []),
        ...(evalRow?.evidenceTargetIds || []),
    ]).slice(0, 48);
}

function rationaleFor(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
    state: GraphDiscourseBridgeAdjudicationState,
    duplicate: boolean,
): string[] {
    return [
        `state:${state}`,
        `candidate_status:${candidate.status}`,
        judgment ? `rerank:${judgment.decision}:${judgment.calibratedScore}` : 'rerank:missing',
        evalRow ? `eval:${evalRow.kind}:${evalRow.passed ? 'passed' : 'failed'}` : 'eval:missing',
        duplicate ? 'superseded_by_higher_scored_equivalent_bridge' : '',
        'ledger_only:no_topology_commit',
        ...candidate.rationale.slice(0, 5),
    ].filter(Boolean);
}

function dagEdgesFor(decision: GraphDiscourseBridgeAdjudicationDecision): Array<{ from: string; to: string; label: string }> {
    return [
        { from: decision.proposalNodeId, to: decision.supportedNodeId, label: 'score_receipts' },
        { from: decision.supportedNodeId, to: `discourse-adjudication-state:${decision.state}:${decision.id}`, label: decision.state },
    ];
}

function compactDecisionLedger(
    snapshot: GraphRebuildSnapshot,
    decisions: GraphDiscourseBridgeAdjudicationDecision[],
): GraphDiscourseBridgeAdjudicationSummary['compactDecisionLedger'] {
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: decisions.length,
        rows: decisions.map((decision) => ({
            id: decision.id,
            state: decision.state,
            candidateKind: decision.candidateKind,
            score: decision.scoringBundle.finalScore,
            judgmentDecision: decision.rationale.find((row) => row.startsWith('rerank:')) || 'rerank:missing',
            evalKind: decision.rationale.find((row) => row.startsWith('eval:')) || 'eval:missing',
            evidence: decision.evidenceTargetIds.length,
            changedAtoms: decision.affectedGraphAtomIds.length,
            changedFacts: decision.affectedGraphFactIds.length,
            changedEdges: 0,
            flags: decision.rationale.filter((row) => row.includes('ledger_only') || row.includes('superseded') || row.includes('failed')),
        })),
    };
}

function counters(
    decisions: GraphDiscourseBridgeAdjudicationDecision[],
    receipts: GraphDiscourseBridgeAdjudicationReceipt[],
): GraphDiscourseBridgeAdjudicationCounters {
    return {
        byState: countBy(decisions, (row) => row.state),
        byCandidateKind: countBy(decisions, (row) => row.candidateKind),
        decisionCount: decisions.length,
        acceptedCount: decisions.filter((row) => row.state === 'accepted').length,
        supportedCount: decisions.filter((row) => row.state === 'supported').length,
        deferredCount: decisions.filter((row) => row.state === 'deferred').length,
        rejectedCount: decisions.filter((row) => row.state === 'rejected').length,
        invalidatedCount: decisions.filter((row) => row.state === 'invalidated').length,
        supersededCount: decisions.filter((row) => row.state === 'superseded').length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((row) => row.reversible).length,
        ledgerOnlyCount: decisions.filter((row) => row.ledgerOnly).length,
        topologyCommitCount: 0,
        mutationAllowedCount: receipts.filter((row) => row.mutationAllowed).length,
        compactRowCount: decisions.length,
    };
}

function bridgeKey(candidate: GraphDiscourseBridgeCandidate): string {
    const pair = [candidate.sourceTargetId, candidate.targetTargetId].sort().join('|');
    return `${candidate.kind}|${pair}`;
}

function stateRank(state: GraphDiscourseBridgeAdjudicationState): number {
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

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}

function round(value: number): number {
    return Math.round(Math.max(0, Math.min(1, value)) * 1000) / 1000;
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
