import type {
    GraphDiscourseBridgeCandidate,
    GraphDiscourseBridgeCandidateCounters,
    GraphDiscourseBridgeCandidateKind,
    GraphDiscourseBridgeCandidateReceipt,
    GraphDiscourseBridgeCandidateStatus,
    GraphDiscourseBridgeEvalKind,
    GraphDiscourseBridgeEvalRow,
    GraphDiscourseBridgeRerankInput,
    GraphDiscourseBridgeRerankJudgment,
    GraphDiscourseBridgeRerankLabel,
    GraphDiscourseBridgeRerankLabelKind,
    GraphDiscourseBridgeRerankScore,
    GraphDiscourseSpineBridge,
    GraphDiscourseSpineCluster,
    GraphDiscourseSpineScoringBundle,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
    GraphSemanticRerankDecision,
    GraphSemanticRerankScoreSource,
} from './graph-rebuild-snapshot';
import type { GraphDiscourseSpineSummary } from './graph-discourse-spine';

export interface GraphDiscourseBridgeCandidateSummary {
    schemaVersion: 'phoenix-discourse-bridge-candidates/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    sourceDiscourseSpineId: string;
    modelId: 'knowledgator/gliclass-instruct-base-v1.0';
    runner: 'gliclass-query-label-rerank';
    scoreSource: GraphSemanticRerankScoreSource;
    invariant: 'discourse_bridges_are_candidates_not_edges';
    labels: GraphDiscourseBridgeRerankLabel[];
    candidates: GraphDiscourseBridgeCandidate[];
    inputs: GraphDiscourseBridgeRerankInput[];
    judgments: GraphDiscourseBridgeRerankJudgment[];
    evalRows: GraphDiscourseBridgeEvalRow[];
    receipts: GraphDiscourseBridgeCandidateReceipt[];
    compactEvalLedger: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            kind: GraphDiscourseBridgeEvalKind;
            candidateKind: GraphDiscourseBridgeCandidateKind;
            decision: GraphSemanticRerankDecision;
            score: number;
            passed: boolean;
            flags: string[];
        }>;
    };
    counters: GraphDiscourseBridgeCandidateCounters;
}

const MODEL_ID = 'knowledgator/gliclass-instruct-base-v1.0';
const RUNNER = 'gliclass-query-label-rerank';
const SCORE_SOURCE: GraphSemanticRerankScoreSource = 'deterministic_calibration';
const MAX_CANDIDATES = 128;
const MAX_PASSAGE_CHARS = 2200;

const LABELS: GraphDiscourseBridgeRerankLabel[] = [
    label('meaningful_resonance', 'This document or chunk meaningfully resonates with another distant document or chunk.', 0.62, ['discourse_resonance']),
    label('cross_doc_resolution', 'This bridge should be reviewed as a cross-document entity, coreference, or context resolution candidate.', 0.6, ['cross_doc_resolution']),
    label('document_cluster_review', 'This document or chunk belongs in a document-level semantic cluster that should be reviewed.', 0.58, ['document_cluster_review']),
    label('weak_resonance', 'This pair has a weak or ambiguous resonance signal that should stay in the ledger.', 0.52, ['discourse_resonance', 'document_cluster_review']),
    label('entity_only_overlap', 'This pair shares entities but does not carry enough semantic resonance.', 0.54, ['cross_doc_resolution', 'discourse_resonance']),
    label('meaning_only_overlap', 'This pair shares meaning, tone, or motif without relying on shared entities.', 0.56, ['discourse_resonance']),
    label('reject_noise', 'This proposed discourse bridge is probably noisy and should not affect graph topology.', 0.5, ['discourse_resonance', 'cross_doc_resolution', 'document_cluster_review']),
];

export function buildGraphDiscourseBridgeCandidateSummary(
    snapshot: GraphRebuildSnapshot,
    spine: GraphDiscourseSpineSummary | undefined = snapshot.discourseSpineSummary,
    generatedAt = snapshot.builtAt,
): GraphDiscourseBridgeCandidateSummary {
    const targetById = new Map(snapshot.embeddingTargets.map((target) => [target.id, target]));
    const labelById = new Map((spine?.labels || []).map((row) => [row.id, row]));
    const candidates = [
        ...bridgeCandidates(spine?.bridges || [], generatedAt),
        ...clusterCandidates(spine?.clusters || [], generatedAt),
    ].sort((left, right) => right.score - left.score || left.id.localeCompare(right.id)).slice(0, MAX_CANDIDATES);
    const inputs = candidates.map((candidate) => inputFor(candidate, targetById, labelById));
    const judgments = inputs.map((input) => judgmentFor(candidates.find((row) => row.id === input.candidateId)!, input));
    const evalRows = judgments.map((judgment) =>
        evalRowFor(candidates.find((row) => row.id === judgment.candidateId)!, judgment),
    );
    const receipts = [
        ...candidates.map(receiptForCandidate),
        ...judgments.map(receiptForJudgment),
        ...evalRows.map(receiptForEvalRow),
    ];
    return {
        schemaVersion: 'phoenix-discourse-bridge-candidates/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        sourceDiscourseSpineId: spine?.sourceSnapshotId || snapshot.id,
        modelId: MODEL_ID,
        runner: RUNNER,
        scoreSource: SCORE_SOURCE,
        invariant: 'discourse_bridges_are_candidates_not_edges',
        labels: LABELS,
        candidates,
        inputs,
        judgments,
        evalRows,
        receipts,
        compactEvalLedger: compactEvalLedger(snapshot, evalRows, judgments),
        counters: counters(candidates, inputs, judgments, evalRows, receipts),
    };
}

function bridgeCandidates(bridges: GraphDiscourseSpineBridge[], generatedAt: number): GraphDiscourseBridgeCandidate[] {
    return bridges.map((bridge) => {
        const kind: GraphDiscourseBridgeCandidateKind = bridge.kind === 'resolution' ? 'cross_doc_resolution' : 'discourse_resonance';
        const id = `discourse-candidate:${kind}:${slug(bridge.id)}`;
        return {
            id,
            kind,
            status: bridge.status,
            sourceBridgeId: bridge.id,
            sourceTargetId: bridge.sourceTargetId,
            targetTargetId: bridge.targetTargetId,
            evidenceTargetIds: bridge.evidenceTargetIds,
            sharedLabelIds: bridge.sharedLabelIds,
            sharedEntityIds: bridge.sharedEntityIds,
            score: bridge.scoringBundle.finalScore,
            scoringBundle: bridge.scoringBundle,
            rationale: bridge.rationale,
            reversibleReceiptIds: [`discourse-candidate-receipt:${slug(id)}`],
            mutationAllowed: false,
            createdAt: generatedAt,
        };
    });
}

function clusterCandidates(clusters: GraphDiscourseSpineCluster[], generatedAt: number): GraphDiscourseBridgeCandidate[] {
    return clusters
        .filter((cluster) => cluster.kind !== 'document_family' && cluster.targetIds.length >= 3)
        .slice(0, 24)
        .map((cluster) => {
            const target = cluster.targetIds.find((id) => id !== cluster.medoidTargetId) || cluster.targetIds[0];
            const id = `discourse-candidate:document_cluster_review:${slug(cluster.id)}`;
            return {
                id,
                kind: 'document_cluster_review',
                status: cluster.score >= 0.58 ? 'proposed' : 'deferred',
                sourceClusterId: cluster.id,
                sourceTargetId: cluster.medoidTargetId,
                targetTargetId: target,
                evidenceTargetIds: cluster.targetIds.slice(0, 12),
                sharedLabelIds: [],
                sharedEntityIds: [],
                score: cluster.score,
                scoringBundle: clusterScoringBundle(cluster),
                rationale: cluster.rationale,
                reversibleReceiptIds: [`discourse-candidate-receipt:${slug(id)}`],
                mutationAllowed: false,
                createdAt: generatedAt,
            };
        });
}

function inputFor(
    candidate: GraphDiscourseBridgeCandidate,
    targetById: Map<string, GraphRebuildEmbeddingTarget>,
    labelById: Map<string, { labelKind: string; value: string }>,
): GraphDiscourseBridgeRerankInput {
    const labels = labelsForCandidate(candidate.kind);
    return {
        id: `discourse-rerank-input:${slug(candidate.id)}`,
        candidateId: candidate.id,
        candidateKind: candidate.kind,
        passage: passageFor(candidate, targetById, labelById),
        labelIds: labels.map((row) => row.id),
        queryLabels: labels.map((row) => row.query),
        evidenceTargetIds: candidate.evidenceTargetIds,
        maxPassageChars: MAX_PASSAGE_CHARS,
    };
}

function judgmentFor(
    candidate: GraphDiscourseBridgeCandidate,
    input: GraphDiscourseBridgeRerankInput,
): GraphDiscourseBridgeRerankJudgment {
    const scores = labelsForCandidate(candidate.kind).map((row) => scoreFor(candidate, row));
    const top = [...scores].sort((left, right) => right.score - left.score || left.labelId.localeCompare(right.labelId))[0];
    const calibratedScore = round(candidate.score * 0.72 + top.score * 0.28);
    const decision = decisionFor(top, calibratedScore);
    const id = `discourse-rerank-judgment:${slug(candidate.id)}`;
    return {
        id,
        candidateId: candidate.id,
        candidateKind: candidate.kind,
        inputId: input.id,
        decision,
        topLabelId: top.labelId,
        topLabelKind: top.labelKind,
        modelId: MODEL_ID,
        runner: RUNNER,
        scoreSource: SCORE_SOURCE,
        relevanceScore: top.score,
        calibratedScore,
        scores,
        evidenceTargetIds: candidate.evidenceTargetIds,
        rationale: [
            `top_label:${top.labelKind}`,
            `calibrated:${calibratedScore.toFixed(3)}`,
            `source:${SCORE_SOURCE}`,
            'ledger-only discourse bridge judgment',
        ],
        reversibleReceiptId: `discourse-rerank-receipt:${slug(id)}`,
    };
}

function evalRowFor(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment,
): GraphDiscourseBridgeEvalRow {
    const kind = evalKindFor(candidate, judgment);
    const expected = expectedLabelFor(kind);
    const passed = judgment.topLabelKind === expected || compatible(kind, judgment.topLabelKind);
    const id = `discourse-eval:${kind}:${slug(candidate.id)}`;
    return {
        id,
        kind,
        candidateId: candidate.id,
        judgmentId: judgment.id,
        bridgeId: candidate.sourceBridgeId,
        expectedLabelKind: expected,
        score: judgment.calibratedScore,
        passed,
        failureModes: passed ? [] : [`expected:${expected}`, `actual:${judgment.topLabelKind}`],
        evidenceTargetIds: candidate.evidenceTargetIds,
        flags: compact([
            candidate.sharedEntityIds.length ? 'shared_entity' : '',
            candidate.sharedLabelIds.length ? 'shared_labels' : '',
            judgment.decision === 'accept' ? 'accepted_looking' : '',
            judgment.decision === 'defer' ? 'weak_or_ambiguous' : '',
        ]),
        rationale: [
            `candidate:${candidate.kind}`,
            `decision:${judgment.decision}`,
            `score:${judgment.calibratedScore.toFixed(3)}`,
        ],
    };
}

function scoreFor(
    candidate: GraphDiscourseBridgeCandidate,
    labelRow: GraphDiscourseBridgeRerankLabel,
): GraphDiscourseBridgeRerankScore {
    const score = scoreValue(candidate, labelRow.kind);
    return {
        labelId: labelRow.id,
        labelKind: labelRow.kind,
        query: labelRow.query,
        score,
        source: SCORE_SOURCE,
        rationale: `${labelRow.kind} calibrated from discourse score ${candidate.score.toFixed(3)}`,
    };
}

function scoreValue(candidate: GraphDiscourseBridgeCandidate, kind: GraphDiscourseBridgeRerankLabelKind): number {
    const bundle = candidate.scoringBundle;
    if (kind === 'meaningful_resonance') {
        return round(kindBoost(candidate, 'discourse_resonance') + bundle.finalScore * 0.5 + bundle.semanticScore * 0.24 + bundle.labelAgreement * 0.18 + (1 - bundle.entityOverlap) * 0.04);
    }
    if (kind === 'cross_doc_resolution') {
        return round(kindBoost(candidate, 'cross_doc_resolution') + bundle.finalScore * 0.42 + bundle.entityOverlap * 0.22 + bundle.corefPressure * 0.24 + bundle.labelAgreement * 0.06);
    }
    if (kind === 'document_cluster_review') {
        return round(kindBoost(candidate, 'document_cluster_review') + bundle.finalScore * 0.62 + bundle.labelAgreement * 0.18);
    }
    if (kind === 'weak_resonance') return round((1 - Math.abs(candidate.score - 0.48)) * 0.48 + (candidate.status === 'deferred' ? 0.18 : 0));
    if (kind === 'entity_only_overlap') return round(bundle.entityOverlap * 0.52 + bundle.corefPressure * 0.22 + (1 - bundle.semanticScore) * 0.18);
    if (kind === 'meaning_only_overlap') return round(bundle.semanticScore * 0.42 + bundle.labelAgreement * 0.28 + (candidate.sharedEntityIds.length ? 0 : 0.18));
    return round((1 - bundle.finalScore) * 0.52 + (candidate.status === 'rejected' ? 0.22 : 0));
}

function passageFor(
    candidate: GraphDiscourseBridgeCandidate,
    targetById: Map<string, GraphRebuildEmbeddingTarget>,
    labelById: Map<string, { labelKind: string; value: string }>,
): string {
    const source = targetById.get(candidate.sourceTargetId);
    const target = targetById.get(candidate.targetTargetId);
    const sharedLabels = candidate.sharedLabelIds
        .map((id) => labelById.get(id))
        .filter((row): row is { labelKind: string; value: string } => Boolean(row))
        .map((row) => `${row.labelKind}:${row.value}`);
    return limitText([
        `candidate_kind:${candidate.kind}`,
        `status:${candidate.status}`,
        `score:${candidate.score.toFixed(3)}`,
        `source:${source?.label || candidate.sourceTargetId}`,
        `source_kind:${source?.kind || 'unknown'} note:${source?.noteId || ''} chunk:${source?.chunkId || ''}`,
        `target:${target?.label || candidate.targetTargetId}`,
        `target_kind:${target?.kind || 'unknown'} note:${target?.noteId || ''} chunk:${target?.chunkId || ''}`,
        `shared_labels:${sharedLabels.slice(0, 12).join(',') || 'none'}`,
        `shared_entities:${candidate.sharedEntityIds.slice(0, 12).join(',') || 'none'}`,
        `semantic:${candidate.scoringBundle.semanticScore.toFixed(3)}`,
        `label_agreement:${candidate.scoringBundle.labelAgreement.toFixed(3)}`,
        `entity_overlap:${candidate.scoringBundle.entityOverlap.toFixed(3)}`,
        `coref_pressure:${candidate.scoringBundle.corefPressure.toFixed(3)}`,
        `rationale:${candidate.rationale.slice(0, 6).join(' | ')}`,
        `source_text:${source?.text || ''}`,
        `target_text:${target?.text || ''}`,
    ].join('\n'), MAX_PASSAGE_CHARS);
}

function evalKindFor(
    candidate: GraphDiscourseBridgeCandidate,
    judgment: GraphDiscourseBridgeRerankJudgment,
): GraphDiscourseBridgeEvalKind {
    if (candidate.sharedEntityIds.length && candidate.scoringBundle.semanticScore < 0.25) return 'entity_overlap_without_meaning';
    if (candidate.kind === 'cross_doc_resolution') return 'cross_doc_resolver_pressure';
    if (candidate.kind === 'discourse_resonance' && !candidate.sharedEntityIds.length) return 'meaning_overlap_without_entity';
    if (judgment.decision === 'accept') return 'accepted_looking_resonance';
    return 'weak_resonance';
}

function expectedLabelFor(kind: GraphDiscourseBridgeEvalKind): GraphDiscourseBridgeRerankLabelKind {
    if (kind === 'cross_doc_resolver_pressure') return 'cross_doc_resolution';
    if (kind === 'entity_overlap_without_meaning') return 'entity_only_overlap';
    if (kind === 'meaning_overlap_without_entity') return 'meaning_only_overlap';
    if (kind === 'weak_resonance') return 'weak_resonance';
    return 'meaningful_resonance';
}

function compatible(kind: GraphDiscourseBridgeEvalKind, labelKind: GraphDiscourseBridgeRerankLabelKind): boolean {
    if (kind === 'accepted_looking_resonance') return labelKind === 'meaning_only_overlap';
    if (kind === 'meaning_overlap_without_entity') return labelKind === 'meaningful_resonance';
    return false;
}

function decisionFor(top: GraphDiscourseBridgeRerankScore, calibratedScore: number): GraphSemanticRerankDecision {
    if (top.labelKind === 'reject_noise' && top.score >= 0.5) return 'reject';
    if (top.labelKind === 'weak_resonance' || calibratedScore < 0.54) return 'defer';
    if (top.score >= 0.58 && calibratedScore >= 0.58) return 'accept';
    return 'review';
}

function receiptForCandidate(candidate: GraphDiscourseBridgeCandidate): GraphDiscourseBridgeCandidateReceipt {
    return {
        id: candidate.reversibleReceiptIds[0],
        candidateId: candidate.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_bridge_candidates_no_topology_commit',
        evidenceTargetIds: candidate.evidenceTargetIds,
        undoHint: 'drop this discourse bridge candidate row; no graph edge exists',
        detail: `${candidate.kind} ${candidate.status} at ${Math.round(candidate.score * 100)}%`,
    };
}

function receiptForJudgment(judgment: GraphDiscourseBridgeRerankJudgment): GraphDiscourseBridgeCandidateReceipt {
    return {
        id: judgment.reversibleReceiptId,
        candidateId: judgment.candidateId,
        judgmentId: judgment.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_bridge_candidates_no_topology_commit',
        evidenceTargetIds: judgment.evidenceTargetIds,
        undoHint: 'drop this discourse rerank judgment row; no graph edge exists',
        detail: `${judgment.candidateKind} ${judgment.decision} from ${judgment.topLabelKind}`,
    };
}

function receiptForEvalRow(row: GraphDiscourseBridgeEvalRow): GraphDiscourseBridgeCandidateReceipt {
    return {
        id: `discourse-eval-receipt:${slug(row.id)}`,
        candidateId: row.candidateId,
        judgmentId: row.judgmentId,
        evalRowId: row.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_bridge_candidates_no_topology_commit',
        evidenceTargetIds: row.evidenceTargetIds,
        undoHint: 'drop this discourse bridge eval row',
        detail: `${row.kind} ${row.passed ? 'passed' : 'failed'} at ${Math.round(row.score * 100)}%`,
    };
}

function compactEvalLedger(
    snapshot: GraphRebuildSnapshot,
    rows: GraphDiscourseBridgeEvalRow[],
    judgments: GraphDiscourseBridgeRerankJudgment[],
): GraphDiscourseBridgeCandidateSummary['compactEvalLedger'] {
    const judgmentById = new Map(judgments.map((row) => [row.id, row]));
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: rows.length,
        rows: rows.map((row) => ({
            id: row.id,
            kind: row.kind,
            candidateKind: judgmentById.get(row.judgmentId)?.candidateKind || 'discourse_resonance',
            decision: judgmentById.get(row.judgmentId)?.decision || 'defer',
            score: row.score,
            passed: row.passed,
            flags: row.flags,
        })),
    };
}

function counters(
    candidates: GraphDiscourseBridgeCandidate[],
    inputs: GraphDiscourseBridgeRerankInput[],
    judgments: GraphDiscourseBridgeRerankJudgment[],
    evalRows: GraphDiscourseBridgeEvalRow[],
    receipts: GraphDiscourseBridgeCandidateReceipt[],
): GraphDiscourseBridgeCandidateCounters {
    return {
        byCandidateKind: countBy(candidates, (row) => row.kind),
        byStatus: countBy(candidates, (row) => row.status),
        byDecision: countBy(judgments, (row) => row.decision),
        byEvalKind: countBy(evalRows, (row) => row.kind),
        byScoreSource: countBy(judgments, (row) => row.scoreSource),
        candidateCount: candidates.length,
        inputCount: inputs.length,
        judgmentCount: judgments.length,
        evalRowCount: evalRows.length,
        passedEvalRows: evalRows.filter((row) => row.passed).length,
        failedEvalRows: evalRows.filter((row) => !row.passed).length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((row) => row.reversible).length,
        mutationAllowedCount: receipts.filter((row) => row.mutationAllowed).length,
        plannedModelCalls: inputs.reduce((sum, input) => sum + input.queryLabels.length, 0),
        acceptedLookingResonance: evalRows.filter((row) => row.kind === 'accepted_looking_resonance').length,
        weakResonance: evalRows.filter((row) => row.kind === 'weak_resonance').length,
        crossDocResolverPressure: evalRows.filter((row) => row.kind === 'cross_doc_resolver_pressure').length,
        entityOverlapWithoutMeaning: evalRows.filter((row) => row.kind === 'entity_overlap_without_meaning').length,
        meaningOverlapWithoutEntity: evalRows.filter((row) => row.kind === 'meaning_overlap_without_entity').length,
        maxCandidates: MAX_CANDIDATES,
        maxPassageChars: MAX_PASSAGE_CHARS,
    };
}

function labelsForCandidate(kind: GraphDiscourseBridgeCandidateKind): GraphDiscourseBridgeRerankLabel[] {
    return LABELS.filter((row) => row.candidateKinds.includes(kind));
}

function label(
    kind: GraphDiscourseBridgeRerankLabelKind,
    query: string,
    threshold: number,
    candidateKinds: GraphDiscourseBridgeCandidateKind[],
): GraphDiscourseBridgeRerankLabel {
    return { id: `discourse-label:${kind}`, kind, query, threshold, candidateKinds };
}

function clusterScoringBundle(cluster: GraphDiscourseSpineCluster): GraphDiscourseSpineScoringBundle {
    const finalScore = round(cluster.score);
    return {
        semanticScore: finalScore,
        labelAgreement: round(Math.min(1, cluster.targetIds.length / 8)),
        entityOverlap: 0,
        distanceScore: 0.24,
        corefPressure: 0,
        finalScore,
        scoreParts: [
            { id: 'cluster_score', score: finalScore, weight: 0.72 },
            { id: 'cluster_size', score: round(Math.min(1, cluster.targetIds.length / 8)), weight: 0.28 },
        ],
    };
}

function kindBoost(candidate: GraphDiscourseBridgeCandidate, kind: GraphDiscourseBridgeCandidateKind): number {
    return candidate.kind === kind ? 0.08 : -0.04;
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

function limitText(value: string, maxChars: number): string {
    return value.length <= maxChars ? value : value.slice(0, maxChars - 24).trimEnd() + '\n...[truncated]';
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
