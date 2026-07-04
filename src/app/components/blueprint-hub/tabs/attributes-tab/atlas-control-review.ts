import type { RegisteredEntity } from '../../../../lib/registry';
import type {
    GraphMemoryGovernanceAction,
    GraphMemoryGovernanceCandidate,
    GraphRebuildRelationship,
    GraphRebuildSnapshot,
} from '../../../../graph-rebuild/graph-rebuild-snapshot';

const NEGATIVE_RELATION_TYPES = new Set(['opposes', 'threatens', 'betrays', 'rejects']);
const NEGATIVE_RELATION_POLICY = 'graph-rebuild-negative-cue-review-policy';

export interface AtlasControlGovernanceRow {
    id: string;
    target: string;
    detail: string;
    evidence: string;
    confidence: string;
    metric: string;
    entities: string[];
    tone: 'contradiction' | 'supersession';
}

export interface AtlasControlGovernanceLane {
    id: 'contradiction' | 'supersession';
    label: string;
    action: string;
    count: number;
    metric: string;
    rows: AtlasControlGovernanceRow[];
}

export interface AtlasControlNegativeRelationRow {
    id: string;
    relation: string;
    pair: string;
    evidence: string;
    confidence: string;
    source: string;
    rationale: string;
}

export interface AtlasControlRuntimeDiagnostic {
    id: 'nativeMemoryGovernanceSkipped' | 'nativeMemoryGovernanceCandidates' | 'nativeMemoryGovernanceRustMicros';
    label: string;
    value: string;
    detail: string;
    tone: 'ready' | 'warning' | 'neutral';
}

export interface AtlasControlGovernanceActionSummary {
    action: GraphMemoryGovernanceAction;
    label: string;
    count: number;
    metric: string;
    tone: 'retain' | 'compress' | 'attenuate' | 'quarantine' | 'retire';
}

export interface AtlasControlGovernanceCandidateRow {
    id: string;
    action: string;
    target: string;
    targetKind: string;
    detail: string;
    evidence: string;
    confidence: string;
    signals: string;
    tone: 'retain' | 'compress' | 'attenuate' | 'quarantine' | 'retire';
}

export interface AtlasControlReviewDeck {
    snapshotLabel: string;
    totalGovernance: number;
    noTopologyCommit: number;
    attentionCount: number;
    runtimeDiagnostics: AtlasControlRuntimeDiagnostic[];
    actionSummaries: AtlasControlGovernanceActionSummary[];
    candidateRows: AtlasControlGovernanceCandidateRow[];
    governanceLanes: AtlasControlGovernanceLane[];
    negativeRelations: AtlasControlNegativeRelationRow[];
}

export function buildAtlasControlReviewDeck(
    snapshot: GraphRebuildSnapshot | null | undefined,
    entities: RegisteredEntity[],
): AtlasControlReviewDeck {
    const entityLabels = new Map(entities.map((entity) => [entity.id, entity.label]));
    const candidates = snapshot?.memoryGovernanceCandidates || [];
    const relationships = snapshot?.relationships || [];

    const contradictionRows = candidates
        .filter(isContradictionCandidate)
        .sort(confidenceSort)
        .map((row) => governanceRow(row, snapshot, entityLabels, 'contradiction'));
    const supersessionRows = candidates
        .filter(isSupersessionCandidate)
        .sort(confidenceSort)
        .map((row) => governanceRow(row, snapshot, entityLabels, 'supersession'));
    const negativeRelations = relationships
        .filter(isNegativeReviewRelationship)
        .sort((left, right) => right.confidence - left.confidence || left.id.localeCompare(right.id))
        .slice(0, 8)
        .map((row) => negativeRelationRow(row, entityLabels));

    return {
        snapshotLabel: snapshot ? compactSnapshotLabel(snapshot.id) : 'No graph run',
        totalGovernance: candidates.length,
        noTopologyCommit: candidates.filter((row) => row.noTopologyCommit).length,
        attentionCount: contradictionRows.length + supersessionRows.length + negativeRelations.length,
        runtimeDiagnostics: runtimeDiagnostics(snapshot),
        actionSummaries: actionSummaries(candidates),
        candidateRows: candidates
            .slice()
            .sort((left, right) => actionRank(left.action) - actionRank(right.action) || confidenceSort(left, right))
            .map((row) => candidateRow(row, snapshot)),
        governanceLanes: [
            {
                id: 'contradiction',
                label: 'Contradiction quarantine',
                action: 'quarantine',
                count: contradictionRows.length,
                metric: laneMetric(contradictionRows.length, candidates.length),
                rows: contradictionRows.slice(0, 6),
            },
            {
                id: 'supersession',
                label: 'Supersession attenuation',
                action: 'attenuate older',
                count: supersessionRows.length,
                metric: laneMetric(supersessionRows.length, candidates.length),
                rows: supersessionRows.slice(0, 6),
            },
        ],
        negativeRelations,
    };
}

function runtimeDiagnostics(
    snapshot: GraphRebuildSnapshot | null | undefined,
): AtlasControlRuntimeDiagnostic[] {
    const timings = snapshot?.buildTimings;
    const skipped = timings?.nativeMemoryGovernanceSkipped;
    const candidates = timings?.nativeMemoryGovernanceCandidates;
    const rustMicros = timings?.nativeMemoryGovernanceRustMicros;
    return [
        {
            id: 'nativeMemoryGovernanceSkipped',
            label: 'Native engine',
            value: skipped === undefined ? '--' : skipped ? 'Skipped' : 'Active',
            detail: 'Rust governance command',
            tone: skipped ? 'warning' : skipped === 0 ? 'ready' : 'neutral',
        },
        {
            id: 'nativeMemoryGovernanceCandidates',
            label: 'Candidate rows',
            value: countValue(candidates),
            detail: 'candidate-only output',
            tone: candidates && candidates > 0 ? 'ready' : 'neutral',
        },
        {
            id: 'nativeMemoryGovernanceRustMicros',
            label: 'Rust time',
            value: microsValue(rustMicros),
            detail: 'engine runtime',
            tone: rustMicros && rustMicros > 0 ? 'ready' : 'neutral',
        },
    ];
}

function isContradictionCandidate(row: GraphMemoryGovernanceCandidate): boolean {
    return row.action === 'quarantine'
        && (row.reason.includes('contradict')
            || row.signals.contradictionRisk > 0
            || row.rationale.some((line) => line.includes('contradict')));
}

function isSupersessionCandidate(row: GraphMemoryGovernanceCandidate): boolean {
    return row.action === 'attenuate'
        && (row.reason.includes('superseded')
            || row.signals.age > 0
            || row.rationale.some((line) => line.includes('supersession') || line.includes('superseded')));
}

function isNegativeReviewRelationship(row: GraphRebuildRelationship): boolean {
    return row.status === 'review'
        && (NEGATIVE_RELATION_TYPES.has(row.relationType)
            || row.adjudicationSource === NEGATIVE_RELATION_POLICY);
}

function confidenceSort(left: GraphMemoryGovernanceCandidate, right: GraphMemoryGovernanceCandidate): number {
    return right.confidence - left.confidence || left.targetId.localeCompare(right.targetId);
}

function actionRank(action: GraphMemoryGovernanceAction): number {
    switch (action) {
        case 'quarantine':
            return 0;
        case 'attenuate':
            return 1;
        case 'compress':
            return 2;
        case 'retain':
            return 3;
        case 'retire':
            return 4;
    }
}

function actionSummaries(rows: GraphMemoryGovernanceCandidate[]): AtlasControlGovernanceActionSummary[] {
    return (['retain', 'compress', 'attenuate', 'quarantine', 'retire'] as const)
        .map((action) => {
            const count = rows.filter((row) => row.action === action).length;
            return {
                action,
                label: actionLabel(action),
                count,
                metric: laneMetric(count, rows.length),
                tone: action,
            };
        })
        .filter((row) => row.count > 0);
}

function candidateRow(
    row: GraphMemoryGovernanceCandidate,
    snapshot: GraphRebuildSnapshot | null | undefined,
): AtlasControlGovernanceCandidateRow {
    return {
        id: row.id,
        action: actionLabel(row.action),
        target: targetLabel(row, snapshot),
        targetKind: titleCase(row.targetKind),
        detail: firstHumanRationale(row.rationale) || titleCase(row.reason),
        evidence: countLabel(row.evidenceIds.length, 'evidence'),
        confidence: percent(row.confidence),
        signals: signalSummary(row),
        tone: row.action,
    };
}

function governanceRow(
    row: GraphMemoryGovernanceCandidate,
    snapshot: GraphRebuildSnapshot | null | undefined,
    entityLabels: Map<string, string>,
    tone: AtlasControlGovernanceRow['tone'],
): AtlasControlGovernanceRow {
    return {
        id: row.id,
        target: targetLabel(row, snapshot),
        detail: firstHumanRationale(row.rationale) || titleCase(row.reason),
        evidence: countLabel(row.evidenceIds.length, 'evidence'),
        confidence: percent(row.confidence),
        metric: tone === 'contradiction'
            ? `risk ${percent(row.signals.contradictionRisk)}`
            : `age ${percent(row.signals.age)}`,
        entities: row.supportingEntityIds.slice(0, 4).map((id) => entityLabels.get(id) || compactId(id)),
        tone,
    };
}

function negativeRelationRow(
    row: GraphRebuildRelationship,
    entityLabels: Map<string, string>,
): AtlasControlNegativeRelationRow {
    return {
        id: row.id,
        relation: titleCase(row.relationType),
        pair: `${entityLabels.get(row.sourceEntityId) || compactId(row.sourceEntityId)} -> ${entityLabels.get(row.targetEntityId) || compactId(row.targetEntityId)}`,
        evidence: countLabel(row.evidenceAnchorIds.length + row.decisionEvidence.length, 'evidence'),
        confidence: percent(row.confidence),
        source: sourceLabel(row.adjudicationSource),
        rationale: row.rationale || 'Review required',
    };
}

function targetLabel(
    row: GraphMemoryGovernanceCandidate,
    snapshot: GraphRebuildSnapshot | null | undefined,
): string {
    if (row.targetKind === 'chunk') {
        const chunk = snapshot?.chunks?.find((candidate) => candidate.id === row.targetId);
        if (chunk) {
            const role = chunk.role ? ` / ${titleCase(chunk.role)}` : '';
            return `Chunk ${chunk.ordinal + 1}${role}`;
        }
    }
    if (row.targetKind === 'episode') {
        const episode = snapshot?.episodes?.find((candidate) => candidate.id === row.targetId);
        if (episode) return episode.label || compactId(row.targetId);
    }
    return compactId(row.targetId);
}

function firstHumanRationale(lines: string[]): string {
    const reason = lines.find((candidate) => candidate.startsWith('reason:'));
    if (reason) return titleCase(reason.replace(/^reason:/, ''));
    const line = lines.find((candidate) =>
        !candidate.includes('no_topology_commit')
        && !candidate.startsWith('memory_governance:')
        && !/^audit:(dominant_entity_pressure|contradiction_risk|contradiction_count|supersession_risk|supersession_count)/.test(candidate));
    return line ? titleCase(line.replace(/^audit:/, '')) : '';
}

function laneMetric(count: number, total: number): string {
    if (!total) return '0%';
    return percent(count / total);
}

function countValue(value: number | undefined): string {
    return value === undefined ? '--' : value.toLocaleString();
}

function microsValue(value: number | undefined): string {
    return value === undefined ? '--' : `${value.toLocaleString()} us`;
}

function countLabel(count: number, label: string): string {
    return `${count} ${label}`;
}

function percent(value: number): string {
    return `${Math.round(value * 100)}%`;
}

function actionLabel(action: GraphMemoryGovernanceAction): string {
    switch (action) {
        case 'retain':
            return 'Keep vivid';
        case 'compress':
            return 'Compress';
        case 'attenuate':
            return 'Attenuate';
        case 'quarantine':
            return 'Quarantine';
        case 'retire':
            return 'Retire';
    }
}

function signalSummary(row: GraphMemoryGovernanceCandidate): string {
    const signals: Array<[string, number]> = [
        ['salience', row.signals.narrativeSalience],
        ['evidence', row.signals.evidenceStrength],
        ['causal', row.signals.causalImportance],
        ['utility', row.signals.retrievalUtility],
        ['redundancy', row.signals.redundancy],
        ['contradiction', row.signals.contradictionRisk],
        ['age', row.signals.age],
    ];
    const visible = signals
        .filter(([, value]) => value > 0.005)
        .sort((left, right) => right[1] - left[1])
        .slice(0, 3)
        .map(([label, value]) => `${label} ${percent(value)}`);
    return visible.join(' / ') || 'baseline';
}

function sourceLabel(value: string): string {
    if (value === NEGATIVE_RELATION_POLICY) return 'negative cue';
    return titleCase(value);
}

function compactSnapshotLabel(value: string): string {
    return value.length <= 16 ? value : value.slice(-16);
}

function compactId(value: string): string {
    return value.split(/[:/]/).pop()?.replace(/[-_]+/g, ' ') || value;
}

function titleCase(value: string): string {
    return value
        .replace(/[-_]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
