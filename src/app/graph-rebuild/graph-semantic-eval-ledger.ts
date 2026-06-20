import type {
    GraphManifoldCandidateContribution,
    GraphRebuildSnapshot,
    GraphSemanticAdjudicationDecision,
    GraphSemanticAdjudicationMutation,
    GraphSemanticCandidate,
    GraphSemanticEvalLedgerCounters,
    GraphSemanticEvalLedgerEntry,
    GraphSemanticEvalLedgerLabel,
    GraphSemanticEvalLedgerSummary,
    GraphSemanticRerankJudgment,
} from './graph-rebuild-snapshot';

const MAX_LEDGER_ROWS = 192;

export function buildGraphSemanticEvalLedgerSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphSemanticEvalLedgerSummary {
    const candidates = new Map((snapshot.semanticCandidateSummary?.candidates || []).map((row) => [row.id, row]));
    const judgments = new Map((snapshot.semanticRerankSummary?.judgments || []).map((row) => [row.candidateId, row]));
    const contributions = new Map((snapshot.manifoldSpecializationSummary?.contributions || []).map((row) => [row.id, row]));
    const mutations = new Map((snapshot.semanticAdjudicationSummary?.mutations || []).map((row) => [row.id, row]));
    const entries: GraphSemanticEvalLedgerEntry[] = [];

    for (const decision of snapshot.semanticAdjudicationSummary?.decisions || []) {
        if (entries.length >= MAX_LEDGER_ROWS) break;
        const candidate = candidates.get(decision.candidateId);
        if (!candidate) continue;
        const judgment = judgments.get(candidate.id);
        const manifoldRows = (candidate.manifoldContributionIds || [])
            .map((id) => contributions.get(id))
            .filter((row): row is GraphManifoldCandidateContribution => Boolean(row));
        entries.push(entryFor(snapshot, decision, candidate, judgment, manifoldRows, decision.mutationId ? mutations.get(decision.mutationId) : undefined));
    }

    return {
        schemaVersion: 'phoenix-semantic-eval-ledger/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        datasetPurpose: [
            'classifier_training',
            'reranker_eval',
            'router_tuning',
            'model_swap_regression',
        ],
        entries,
        compactExport: compactExport(snapshot, entries),
        counters: evalLedgerCounters(entries),
    };
}

function entryFor(
    snapshot: GraphRebuildSnapshot,
    decision: GraphSemanticAdjudicationDecision,
    candidate: GraphSemanticCandidate,
    judgment: GraphSemanticRerankJudgment | undefined,
    manifolds: GraphManifoldCandidateContribution[],
    mutation: GraphSemanticAdjudicationMutation | undefined,
): GraphSemanticEvalLedgerEntry {
    const label = labelFor(decision);
    const modelDisagreement = modelDisagrees(decision, judgment);
    const manifoldDisagreement = manifoldDisagrees(manifolds);
    return {
        id: `eval-ledger:${slug(decision.id)}`,
        candidateId: candidate.id,
        decisionId: decision.id,
        label,
        candidateKind: candidate.kind,
        adjudicationState: decision.state,
        sourceHypothesis: decision.sourceHypothesis,
        evidenceTargetIds: decision.evidenceTargetIds.slice(0, 24),
        score: decision.scoringBundle.finalScore,
        scoringBundle: decision.scoringBundle,
        rerank: judgment ? {
            judgmentId: judgment.id,
            decision: judgment.decision,
            scoreSource: judgment.scoreSource,
            topLabelKind: judgment.topLabelKind,
            relevanceScore: judgment.relevanceScore,
            calibratedScore: judgment.calibratedScore,
        } : undefined,
        manifoldVotes: manifolds.map((row) => ({
            id: row.id,
            manifold: row.manifold,
            role: row.manifoldRole,
            score: row.score,
            ruleId: row.ruleId,
        })),
        flags: compact([
            modelDisagreement ? 'model_disagreement' : '',
            manifoldDisagreement ? 'manifold_disagreement' : '',
            decision.state === 'supported' || decision.state === 'deferred' ? 'ambiguous_case' : '',
            decision.state === 'accepted' ? 'accepted_candidate' : '',
            decision.state === 'rejected' || decision.state === 'invalidated' ? 'rejected_candidate' : '',
            mutation ? 'before_after_graph_change' : '',
            mutation ? 'graph_rebuild_live_contract_graph_change' : '',
            userCorrectionFlag(snapshot, candidate),
        ]),
        beforeGraph: {
            edgeCount: snapshot.counters.edges - (snapshot.semanticAdjudicationSummary?.counters.appliedMutationCount || 0),
            factIds: [],
            edgeIds: [],
        },
        afterGraph: {
            edgeCount: snapshot.counters.edges,
            factIds: mutation?.createdFactIds || [],
            edgeIds: mutation?.createdEdgeId ? [mutation.createdEdgeId] : [],
        },
        userCorrectionIds: userCorrectionIds(snapshot, candidate),
        rationale: decision.rationale.slice(0, 8),
    };
}

function compactExport(
    snapshot: GraphRebuildSnapshot,
    entries: GraphSemanticEvalLedgerEntry[],
): GraphSemanticEvalLedgerSummary['compactExport'] {
    const rows = entries.map((entry) => ({
        id: entry.id,
        label: entry.label,
        kind: entry.candidateKind,
        state: entry.adjudicationState,
        score: entry.score,
        flags: entry.flags,
        evidence: entry.evidenceTargetIds.length,
        changedEdges: entry.afterGraph.edgeIds.length,
        changedFacts: entry.afterGraph.factIds.length,
    }));
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: rows.length,
        rows,
    };
}

function labelFor(decision: GraphSemanticAdjudicationDecision): GraphSemanticEvalLedgerLabel {
    if (decision.state === 'accepted') return 'accepted_candidate';
    if (decision.state === 'rejected' || decision.state === 'invalidated') return 'rejected_candidate';
    if (decision.state === 'supported' || decision.state === 'deferred' || decision.state === 'superseded') return 'ambiguous_case';
    return 'model_disagreement';
}

function modelDisagrees(
    decision: GraphSemanticAdjudicationDecision,
    judgment: GraphSemanticRerankJudgment | undefined,
): boolean {
    if (!judgment) return true;
    if (judgment.decision === 'accept') return decision.state !== 'accepted' && decision.state !== 'supported';
    if (judgment.decision === 'reject') return decision.state !== 'rejected' && decision.state !== 'invalidated';
    return decision.state === 'accepted' || decision.state === 'rejected';
}

function manifoldDisagrees(rows: GraphManifoldCandidateContribution[]): boolean {
    if (rows.length < 2) return false;
    const scores = rows.map((row) => row.score).sort((left, right) => left - right);
    const spread = scores[scores.length - 1] - scores[0];
    return spread >= 0.22 || new Set(rows.map((row) => row.manifoldRole)).size >= 3;
}

function userCorrectionIds(snapshot: GraphRebuildSnapshot, candidate: GraphSemanticCandidate): string[] {
    const evidence = new Set(candidate.evidenceIds);
    return [
        ...(snapshot.resolutionSuggestions || [])
            .filter((row) => row.entityIds.some((id) => candidate.sourceTargetIds.some((target) => target.includes(id))))
            .map((row) => row.id),
        ...(snapshot.finalLinkPatchLog?.patches || [])
            .filter((patch) => patch.evidenceIds.some((id) => evidence.has(id)))
            .map((patch) => patch.id),
    ].slice(0, 8);
}

function userCorrectionFlag(snapshot: GraphRebuildSnapshot, candidate: GraphSemanticCandidate): string {
    return userCorrectionIds(snapshot, candidate).length ? 'user_correction' : '';
}

function evalLedgerCounters(entries: GraphSemanticEvalLedgerEntry[]): GraphSemanticEvalLedgerCounters {
    return {
        rowCount: entries.length,
        byLabel: countBy(entries, (row) => row.label),
        byCandidateKind: countBy(entries, (row) => row.candidateKind),
        acceptedCandidates: entries.filter((row) => row.label === 'accepted_candidate').length,
        rejectedCandidates: entries.filter((row) => row.label === 'rejected_candidate').length,
        ambiguousCases: entries.filter((row) => row.label === 'ambiguous_case').length,
        userCorrections: entries.filter((row) => row.flags.includes('user_correction')).length,
        modelDisagreements: entries.filter((row) => row.flags.includes('model_disagreement')).length,
        manifoldDisagreements: entries.filter((row) => row.flags.includes('manifold_disagreement')).length,
        graphChangeRows: entries.filter((row) => row.flags.includes('before_after_graph_change')).length,
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

function compact(values: string[]): string[] {
    return values.filter(Boolean);
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
