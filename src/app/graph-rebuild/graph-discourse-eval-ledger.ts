import type {
    GraphDiscourseBridgeAdjudicationDecision,
    GraphDiscourseBridgeCandidate,
    GraphDiscourseBridgeEvalRow,
    GraphDiscourseBridgeRerankJudgment,
    GraphDiscourseEvalLedgerCounters,
    GraphDiscourseEvalLedgerEntry,
    GraphDiscourseEvalLedgerLabel,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export interface GraphDiscourseEvalLedgerSummary {
    schemaVersion: 'phoenix-discourse-eval-ledger/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    sourceAdjudicationSummaryId: string;
    datasetPurpose: Array<
        | 'classifier_training'
        | 'reranker_eval'
        | 'router_tuning'
        | 'model_swap_regression'
        | 'document_cluster_eval'
        | 'cross_doc_resolver_training'
    >;
    entries: GraphDiscourseEvalLedgerEntry[];
    compactExport: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            label: GraphDiscourseEvalLedgerLabel;
            kind: string;
            state: string;
            score: number;
            flags: string[];
            evidence: number;
            changedEdges: number;
            changedFacts: number;
        }>;
    };
    counters: GraphDiscourseEvalLedgerCounters;
}

const MAX_LEDGER_ROWS = 192;

export function buildGraphDiscourseEvalLedgerSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphDiscourseEvalLedgerSummary {
    const candidates = new Map((snapshot.discourseBridgeCandidateSummary?.candidates || []).map((row) => [row.id, row]));
    const judgments = new Map((snapshot.discourseBridgeCandidateSummary?.judgments || []).map((row) => [row.candidateId, row]));
    const evalRows = new Map((snapshot.discourseBridgeCandidateSummary?.evalRows || []).map((row) => [row.candidateId, row]));
    const entries: GraphDiscourseEvalLedgerEntry[] = [];

    for (const decision of snapshot.discourseBridgeAdjudicationSummary?.decisions || []) {
        if (entries.length >= MAX_LEDGER_ROWS) break;
        const candidate = candidates.get(decision.candidateId);
        if (!candidate) continue;
        entries.push(entryFor(
            snapshot,
            decision,
            candidate,
            judgments.get(candidate.id),
            evalRows.get(candidate.id),
        ));
    }

    return {
        schemaVersion: 'phoenix-discourse-eval-ledger/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        sourceAdjudicationSummaryId: snapshot.discourseBridgeAdjudicationSummary
            ? `${snapshot.id}:discourse-bridge-adjudication:${snapshot.discourseBridgeAdjudicationSummary.generatedAt}`
            : `${snapshot.id}:discourse-bridge-adjudication:missing`,
        datasetPurpose: [
            'classifier_training',
            'reranker_eval',
            'router_tuning',
            'model_swap_regression',
            'document_cluster_eval',
            'cross_doc_resolver_training',
        ],
        entries,
        compactExport: compactExport(snapshot, entries),
        counters: counters(entries),
    };
}

function entryFor(
    snapshot: GraphRebuildSnapshot,
    decision: GraphDiscourseBridgeAdjudicationDecision,
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
): GraphDiscourseEvalLedgerEntry {
    const label = labelFor(decision);
    const userCorrectionIds = correctionIds(snapshot, decision, candidate);
    const modelDisagreement = modelDisagrees(decision, judgment, evalRow);
    const manifoldDisagreement = manifoldDisagrees(candidate);
    return {
        id: `discourse-eval-ledger:${slug(decision.id)}`,
        candidateId: candidate.id,
        decisionId: decision.id,
        label,
        candidateKind: candidate.kind,
        adjudicationState: decision.state,
        sourceHypothesis: decision.sourceHypothesis,
        evidenceTargetIds: decision.evidenceTargetIds.slice(0, 32),
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
        candidateEval: evalRow ? {
            evalRowId: evalRow.id,
            kind: evalRow.kind,
            expectedLabelKind: evalRow.expectedLabelKind,
            score: evalRow.score,
            passed: evalRow.passed,
            failureModes: evalRow.failureModes,
        } : undefined,
        discourseReceipts: {
            semanticScore: candidate.scoringBundle.semanticScore,
            labelAgreement: candidate.scoringBundle.labelAgreement,
            entityOverlap: candidate.scoringBundle.entityOverlap,
            distanceScore: candidate.scoringBundle.distanceScore,
            corefPressure: candidate.scoringBundle.corefPressure,
            finalScore: candidate.scoringBundle.finalScore,
        },
        flags: compact([
            modelDisagreement ? 'model_disagreement' : '',
            manifoldDisagreement ? 'manifold_disagreement' : '',
            evalRow && !evalRow.passed ? 'eval_disagreement' : '',
            decision.state === 'accepted' ? 'accepted_candidate' : '',
            decision.state === 'rejected' || decision.state === 'invalidated' ? 'rejected_candidate' : '',
            decision.state === 'supported' || decision.state === 'deferred' ? 'ambiguous_case' : '',
            decision.state === 'superseded' ? 'superseded_duplicate' : '',
            candidate.kind === 'cross_doc_resolution' ? 'resolver_training' : '',
            candidate.kind === 'document_cluster_review' ? 'cluster_review' : '',
            userCorrectionIds.length ? 'user_correction' : '',
        ]),
        beforeGraph: {
            edgeCount: snapshot.counters.edges,
            factIds: [],
            edgeIds: [],
        },
        afterGraph: {
            edgeCount: snapshot.counters.edges,
            factIds: [],
            edgeIds: [],
        },
        userCorrectionIds,
        rationale: decision.rationale.slice(0, 8),
    };
}

function compactExport(
    snapshot: GraphRebuildSnapshot,
    entries: GraphDiscourseEvalLedgerEntry[],
): GraphDiscourseEvalLedgerSummary['compactExport'] {
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

function labelFor(decision: GraphDiscourseBridgeAdjudicationDecision): GraphDiscourseEvalLedgerLabel {
    if (decision.state === 'accepted') return 'accepted_candidate';
    if (decision.state === 'rejected' || decision.state === 'invalidated') return 'rejected_candidate';
    if (decision.state === 'supported' || decision.state === 'deferred' || decision.state === 'superseded') return 'ambiguous_case';
    return 'model_disagreement';
}

function modelDisagrees(
    decision: GraphDiscourseBridgeAdjudicationDecision,
    judgment: GraphDiscourseBridgeRerankJudgment | undefined,
    evalRow: GraphDiscourseBridgeEvalRow | undefined,
): boolean {
    if (!judgment || !evalRow) return true;
    if (!evalRow.passed) return true;
    if (judgment.decision === 'accept') {
        return decision.state !== 'accepted' && decision.state !== 'supported' && decision.state !== 'superseded';
    }
    if (judgment.decision === 'reject') return decision.state !== 'rejected' && decision.state !== 'invalidated';
    return decision.state === 'accepted' || decision.state === 'rejected';
}

function manifoldDisagrees(candidate: GraphDiscourseBridgeCandidate): boolean {
    const scores = [
        candidate.scoringBundle.semanticScore,
        candidate.scoringBundle.labelAgreement,
        candidate.scoringBundle.entityOverlap,
        candidate.scoringBundle.distanceScore,
        candidate.scoringBundle.corefPressure,
    ].sort((left, right) => left - right);
    const spread = scores[scores.length - 1] - scores[0];
    if (spread >= 0.5) return true;
    if (candidate.kind === 'cross_doc_resolution') {
        return candidate.scoringBundle.corefPressure >= 0.62 && candidate.scoringBundle.semanticScore <= 0.28;
    }
    if (candidate.kind === 'discourse_resonance') {
        return candidate.scoringBundle.semanticScore >= 0.72 && candidate.scoringBundle.labelAgreement <= 0.24;
    }
    return false;
}

function correctionIds(
    snapshot: GraphRebuildSnapshot,
    decision: GraphDiscourseBridgeAdjudicationDecision,
    candidate: GraphDiscourseBridgeCandidate,
): string[] {
    const evidence = new Set(decision.evidenceTargetIds);
    const sourceIds = new Set([candidate.sourceTargetId, candidate.targetTargetId, ...candidate.sharedEntityIds]);
    return [
        ...(snapshot.resolutionSuggestions || [])
            .filter((row) => row.entityIds.some((id) => sourceIds.has(id) || candidate.sharedEntityIds.includes(id)))
            .map((row) => row.id),
        ...(snapshot.finalLinkPatchLog?.patches || [])
            .filter((patch) => patch.evidenceIds.some((id) => evidence.has(id)))
            .map((patch) => patch.id),
    ].slice(0, 8);
}

function counters(entries: GraphDiscourseEvalLedgerEntry[]): GraphDiscourseEvalLedgerCounters {
    return {
        rowCount: entries.length,
        byLabel: countBy(entries, (row) => row.label),
        byCandidateKind: countBy(entries, (row) => row.candidateKind),
        byState: countBy(entries, (row) => row.adjudicationState),
        acceptedCandidates: entries.filter((row) => row.label === 'accepted_candidate').length,
        rejectedCandidates: entries.filter((row) => row.label === 'rejected_candidate').length,
        ambiguousCases: entries.filter((row) => row.label === 'ambiguous_case').length,
        userCorrections: entries.filter((row) => row.flags.includes('user_correction')).length,
        modelDisagreements: entries.filter((row) => row.flags.includes('model_disagreement')).length,
        manifoldDisagreements: entries.filter((row) => row.flags.includes('manifold_disagreement')).length,
        evalDisagreements: entries.filter((row) => row.flags.includes('eval_disagreement')).length,
        graphChangeRows: entries.filter((row) => row.afterGraph.edgeIds.length || row.afterGraph.factIds.length).length,
        resonanceRows: entries.filter((row) => row.candidateKind === 'discourse_resonance').length,
        resolutionRows: entries.filter((row) => row.candidateKind === 'cross_doc_resolution').length,
        clusterReviewRows: entries.filter((row) => row.candidateKind === 'document_cluster_review').length,
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
