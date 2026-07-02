import {
    GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
    GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION,
    GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
    type GraphMemoryGovernanceAction,
    type GraphMemoryGovernanceCandidate,
    type GraphMemoryGovernanceRetrievalCandidate,
    type GraphMemoryGovernanceRetrievalWeightingExperiment,
    type GraphMemoryGovernanceRetrievalWeightingVariant,
    type GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

const RETRIEVAL_EXPERIMENT_ROW_LIMIT = 1_024;

export function applyNativeMemoryGovernanceCandidates(
    snapshot: GraphRebuildSnapshot,
    candidates: GraphMemoryGovernanceCandidate[],
): void {
    const rows = assertMemoryGovernanceCandidateOnly(candidates);
    snapshot.memoryGovernanceCandidates = rows;
    snapshot.counters = {
        ...snapshot.counters,
        memoryGovernanceCandidates: rows.length,
        memoryGovernanceRetain: countAction(rows, 'retain'),
        memoryGovernanceAttenuate: countAction(rows, 'attenuate'),
        memoryGovernanceCompress: countAction(rows, 'compress'),
        memoryGovernanceQuarantine: countAction(rows, 'quarantine'),
        memoryGovernanceRetire: countAction(rows, 'retire'),
    };
}

export function memoryGovernanceRetrievalCandidatesFromSnapshot(
    snapshot: GraphRebuildSnapshot,
    limit = RETRIEVAL_EXPERIMENT_ROW_LIMIT,
): GraphMemoryGovernanceRetrievalCandidate[] {
    const rows: GraphMemoryGovernanceRetrievalCandidate[] = [];
    for (const target of snapshot.embeddingTargets || []) {
        if (!isRetrievalExperimentTarget(target)) continue;
        const targetRef = memoryGovernanceTargetRef(target);
        if (!targetRef) continue;
        rows.push({
            id: `app_embedding_target:${target.id}`,
            targetId: targetRef.targetId,
            targetKind: targetRef.targetKind,
            score: retrievalExperimentScore(target),
        });
    }
    return rows
        .sort((left, right) => right.score - left.score || left.id.localeCompare(right.id))
        .slice(0, Math.max(0, limit));
}

export function applyNativeMemoryGovernanceRetrievalExperiment(
    snapshot: GraphRebuildSnapshot,
    experiment: GraphMemoryGovernanceRetrievalWeightingExperiment,
): void {
    assertMemoryGovernanceRetrievalExperimentReportOnly(experiment);
    const baseline = baselineVariant(experiment);
    snapshot.memoryGovernanceRetrievalExperiment = experiment;
    snapshot.counters = {
        ...snapshot.counters,
        memoryGovernanceRetrievalCandidates: baseline?.summary.candidateCount || 0,
        memoryGovernanceRetrievalGoverned: baseline?.summary.governedCount || 0,
        memoryGovernanceRetrievalChangedRanks: baseline?.summary.changedRankCount || 0,
        memoryGovernanceRetrievalPolicies: experiment.variants.length,
    };
}

export function assertMemoryGovernanceCandidateOnly(
    candidates: GraphMemoryGovernanceCandidate[],
): GraphMemoryGovernanceCandidate[] {
    for (const candidate of candidates) {
        if (candidate.schemaVersion !== GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION) {
            throw new Error(`Invalid memory governance schema: ${candidate.id}`);
        }
        if (candidate.status !== 'candidate') {
            throw new Error(`Invalid memory governance status: ${candidate.id}`);
        }
        if (candidate.commitPolicy !== GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY) {
            throw new Error(`Invalid memory governance commit policy: ${candidate.id}`);
        }
        if (candidate.noTopologyCommit !== true) {
            throw new Error(`Memory governance row may not mutate topology: ${candidate.id}`);
        }
        if (!candidate.rationale?.includes(GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)) {
            throw new Error(`Memory governance row is missing no-topology rationale: ${candidate.id}`);
        }
    }
    return [...candidates].sort((left, right) =>
        actionRank(left.action) - actionRank(right.action)
        || right.confidence - left.confidence
        || left.targetKind.localeCompare(right.targetKind)
        || left.targetId.localeCompare(right.targetId)
        || left.id.localeCompare(right.id));
}

export function assertMemoryGovernanceRetrievalExperimentReportOnly(
    experiment: GraphMemoryGovernanceRetrievalWeightingExperiment,
): GraphMemoryGovernanceRetrievalWeightingExperiment {
    if (experiment.schemaVersion !== GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION) {
        throw new Error(`Invalid memory governance retrieval experiment schema: ${experiment.schemaVersion}`);
    }
    if (experiment.noTopologyCommit !== true) {
        throw new Error('Memory governance retrieval experiment may not mutate topology.');
    }
    for (const variant of experiment.variants || []) {
        for (const row of variant.topRows || []) {
            if (row.noTopologyCommit !== true) {
                throw new Error(`Memory governance retrieval row may not mutate topology: ${row.id}`);
            }
        }
    }
    return experiment;
}

function countAction(rows: GraphMemoryGovernanceCandidate[], action: GraphMemoryGovernanceAction): number {
    return rows.filter((row) => row.action === action).length;
}

function actionRank(action: GraphMemoryGovernanceAction): number {
    switch (action) {
        case 'retain':
            return 0;
        case 'compress':
            return 1;
        case 'attenuate':
            return 2;
        case 'quarantine':
            return 3;
        case 'retire':
            return 4;
    }
}

function baselineVariant(
    experiment: GraphMemoryGovernanceRetrievalWeightingExperiment,
): GraphMemoryGovernanceRetrievalWeightingVariant | undefined {
    return experiment.variants.find((variant) => variant.policy.id === experiment.baselinePolicyId)
        || experiment.variants[0];
}

function memoryGovernanceTargetRef(
    target: GraphRebuildSnapshot['embeddingTargets'][number],
): { targetId: string; targetKind: GraphMemoryGovernanceRetrievalCandidate['targetKind'] } | null {
    const kind = normalizeTargetKind(target.kind);
    if (kind === 'chunk') {
        const targetId = target.chunkId || target.sourceId;
        return targetId ? { targetId, targetKind: 'chunk' } : null;
    }
    if (kind === 'episode') {
        return target.sourceId ? { targetId: target.sourceId, targetKind: 'episode' } : null;
    }
    if (kind === 'documentunit' && target.chunkId && isRetrievalDocumentUnit(target)) {
        return { targetId: target.chunkId, targetKind: 'chunk' };
    }
    return null;
}

function isRetrievalExperimentTarget(target: GraphRebuildSnapshot['embeddingTargets'][number]): boolean {
    if (target.admissionStatus === 'deferred') return false;
    if (target.workStatus === 'deferred_by_policy' || target.workStatus === 'deferred_by_scheduler') return false;
    return true;
}

function isRetrievalDocumentUnit(target: GraphRebuildSnapshot['embeddingTargets'][number]): boolean {
    return target.documentUnitKind === 'retrieval_unit'
        || /\bdocument_sidecar:retrieval_unit\b/i.test(`${target.label} ${target.text}`);
}

function retrievalExperimentScore(target: GraphRebuildSnapshot['embeddingTargets'][number]): number {
    const kind = normalizeTargetKind(target.kind);
    let score =
        kind === 'episode' ? 760 :
        kind === 'documentunit' ? 650 :
        kind === 'chunk' ? 620 : 500;
    const text = `${target.label} ${target.text}`.toLowerCase();
    if (/command|authority|causal|cause|because|before|after|temporal|approved|accepted|warn/.test(text)) score += 44;
    if (/chunk_role:(authority_chain|evidence_block|transition)/.test(text)) score += 36;
    if (/meaning_cues:|entity_priors:/.test(text)) score += 18;
    if (/evidence_context:/.test(text)) score += 42;
    score += Math.min(48, (target.evidenceIds || []).length * 6);
    if (target.admissionStatus === 'admitted') score += 18;
    if (target.workStatus === 'queued') score += 12;
    return Math.round(clamp(score / 1_000, 0.05, 0.99) * 1_000) / 1_000;
}

function normalizeTargetKind(kind: string | undefined): string {
    return String(kind || '').replace(/[^a-z0-9]/gi, '').toLowerCase();
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}
