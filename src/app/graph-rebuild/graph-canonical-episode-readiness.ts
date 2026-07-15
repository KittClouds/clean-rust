import type {
    NativeDecisionCensus,
    NativeRewardObservationCensus,
} from './graph-native-decision-capture';

export interface CanonicalRewardProducerReport {
    schemaVersion: 'phoenix-canonical-reward-producer-report/v1';
    observedAt: number;
    linkedCommits: number;
    humanEvidenceAppended: number;
    humanObservationsAppended: number;
    stabilityEvidenceAppended: number;
    stabilityObservationsAppended: number;
    alreadyObserved: number;
    pendingHorizons: number;
    nextEligibleAt: number | null;
}

export interface CanonicalEpisodeAssignmentReadiness {
    decisions: number;
    attached: number;
    created: number;
    abstained: number;
    chronologicalSpanDays: number;
    averageCandidates: number;
    candidateCountRange: string;
    linked: number;
    partiallyObserved: number;
    mature: number;
    stable: number;
    revised: number;
    pendingHorizons: number;
    nextEligibleAt: number | null;
    plumbingGate: 'waiting' | 'passed';
    pilotGate: 'waiting' | 'passed';
    researchCountGate: 'waiting' | 'passed';
}

export interface CanonicalEpisodeAssignmentResearchSurface {
    nativeDecisionCensus(): Promise<unknown>;
    nativeRewardObservationCensus(): Promise<unknown>;
    observeNativeRewardHorizons(): Promise<unknown>;
}

export async function loadCanonicalEpisodeAssignmentReadiness(
    surface: CanonicalEpisodeAssignmentResearchSurface,
): Promise<CanonicalEpisodeAssignmentReadiness> {
    const decisions = nativeDecisionCensus(await surface.nativeDecisionCensus());
    const [observer, rewards] = await Promise.all([
        surface.observeNativeRewardHorizons().then(canonicalRewardProducerReport),
        surface.nativeRewardObservationCensus().then(nativeRewardCensus),
    ]);
    const mature = rewards.matureCanonicalEpisodeAssignments;
    return {
        decisions: decisions.canonicalEpisodeAssignmentLabels,
        attached: decisions.canonicalEpisodeAttachLabels,
        created: decisions.canonicalEpisodeCreateLabels,
        abstained: decisions.canonicalEpisodeAbstainLabels,
        chronologicalSpanDays: chronologicalSpanDays(decisions),
        averageCandidates: decisions.canonicalEpisodeAssignmentLabels === 0
            ? 0
            : decisions.canonicalEpisodeCandidateCountTotal
                / decisions.canonicalEpisodeAssignmentLabels,
        candidateCountRange: `${decisions.canonicalEpisodeCandidateCountMin}-${decisions.canonicalEpisodeCandidateCountMax}`,
        linked: decisions.graphTruthLinkedDecisions,
        partiallyObserved: rewards.partiallyObservedDecisions,
        mature,
        stable: rewards.positiveCanonicalEpisodeStability,
        revised: rewards.negativeCanonicalEpisodeStability,
        pendingHorizons: rewards.pendingCanonicalEpisodeHorizons,
        nextEligibleAt: observer.nextEligibleAt,
        plumbingGate: mature >= 10 ? 'passed' : 'waiting',
        pilotGate: mature >= 100 ? 'passed' : 'waiting',
        researchCountGate: mature >= 1_000 ? 'passed' : 'waiting',
    };
}

function nativeDecisionCensus(value: unknown): NativeDecisionCensus {
    const row = object(value);
    if (row?.['schemaVersion'] !== 'phoenix-native-decision-census/v1') {
        throw new Error('Native decision census returned an invalid schema.');
    }
    return {
        schemaVersion: row['schemaVersion'],
        behaviorLabels: count(row, 'behaviorLabels'),
        canonicalEpisodeAssignmentLabels: count(row, 'canonicalEpisodeAssignmentLabels'),
        canonicalEpisodeAttachLabels: count(row, 'canonicalEpisodeAttachLabels'),
        canonicalEpisodeCreateLabels: count(row, 'canonicalEpisodeCreateLabels'),
        canonicalEpisodeAbstainLabels: count(row, 'canonicalEpisodeAbstainLabels'),
        canonicalEpisodeFirstObservedAt: nullableTimestamp(row, 'canonicalEpisodeFirstObservedAt'),
        canonicalEpisodeLastObservedAt: nullableTimestamp(row, 'canonicalEpisodeLastObservedAt'),
        canonicalEpisodeCandidateCountTotal: count(row, 'canonicalEpisodeCandidateCountTotal'),
        canonicalEpisodeCandidateCountMin: count(row, 'canonicalEpisodeCandidateCountMin'),
        canonicalEpisodeCandidateCountMax: count(row, 'canonicalEpisodeCandidateCountMax'),
        operatorPreferenceLabels: count(row, 'operatorPreferenceLabels'),
        executionOutcomes: count(row, 'executionOutcomes'),
        rewardCompleteOutcomes: count(row, 'rewardCompleteOutcomes'),
        rewardCensoredOutcomes: count(row, 'rewardCensoredOutcomes'),
        counterfactualReadyDecisions: count(row, 'counterfactualReadyDecisions'),
        graphTruthLinkedDecisions: count(row, 'graphTruthLinkedDecisions'),
    };
}

function nativeRewardCensus(value: unknown): NativeRewardObservationCensus {
    const row = object(value);
    if (row?.['schemaVersion'] !== 'phoenix-native-reward-observation-census/v1') {
        throw new Error('Native reward census returned an invalid schema.');
    }
    return {
        schemaVersion: row['schemaVersion'],
        observationReceipts: count(row, 'observationReceipts'),
        activeHumanAcceptance: count(row, 'activeHumanAcceptance'),
        activeFutureStability: count(row, 'activeFutureStability'),
        positiveFutureStability: count(row, 'positiveFutureStability'),
        negativeFutureStability: count(row, 'negativeFutureStability'),
        matureCanonicalEpisodeAssignments: count(row, 'matureCanonicalEpisodeAssignments'),
        positiveCanonicalEpisodeStability: count(row, 'positiveCanonicalEpisodeStability'),
        negativeCanonicalEpisodeStability: count(row, 'negativeCanonicalEpisodeStability'),
        pendingCanonicalEpisodeHorizons: count(row, 'pendingCanonicalEpisodeHorizons'),
        retractedDimensions: count(row, 'retractedDimensions'),
        partiallyObservedDecisions: count(row, 'partiallyObservedDecisions'),
        fullyObservedDecisions: count(row, 'fullyObservedDecisions'),
    };
}

function canonicalRewardProducerReport(value: unknown): CanonicalRewardProducerReport {
    const row = object(value);
    if (row?.['schemaVersion'] !== 'phoenix-canonical-reward-producer-report/v1') {
        throw new Error('Canonical reward observer returned an invalid schema.');
    }
    const nextEligibleAt = row['nextEligibleAt'];
    if (nextEligibleAt !== null && (typeof nextEligibleAt !== 'number' || !Number.isFinite(nextEligibleAt))) {
        throw new Error('Canonical reward observer returned an invalid horizon.');
    }
    return {
        schemaVersion: row['schemaVersion'],
        observedAt: count(row, 'observedAt'),
        linkedCommits: count(row, 'linkedCommits'),
        humanEvidenceAppended: count(row, 'humanEvidenceAppended'),
        humanObservationsAppended: count(row, 'humanObservationsAppended'),
        stabilityEvidenceAppended: count(row, 'stabilityEvidenceAppended'),
        stabilityObservationsAppended: count(row, 'stabilityObservationsAppended'),
        alreadyObserved: count(row, 'alreadyObserved'),
        pendingHorizons: count(row, 'pendingHorizons'),
        nextEligibleAt,
    };
}

function count(row: Record<string, unknown>, key: string): number {
    const value = row[key];
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
        throw new Error(`Native research census returned an invalid ${key}.`);
    }
    return value;
}

function nullableTimestamp(row: Record<string, unknown>, key: string): number | null {
    const value = row[key];
    if (value === null) return null;
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
        throw new Error(`Native research census returned an invalid ${key}.`);
    }
    return value;
}

function chronologicalSpanDays(census: NativeDecisionCensus): number {
    const first = census.canonicalEpisodeFirstObservedAt;
    const last = census.canonicalEpisodeLastObservedAt;
    if (first === null || last === null) return 0;
    return Math.max(1, Math.ceil((last - first) / 86_400_000));
}

function object(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}
