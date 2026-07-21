import { describe, expect, it, vi } from 'vitest';

import { loadCanonicalEpisodeAssignmentReadiness } from './graph-canonical-episode-readiness';

describe('canonical episode assignment readiness', () => {
    it('keeps a passed count gate separate from a sub-24h train-only corpus', async () => {
        const surface = {
            nativeDecisionCensus: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-native-decision-census/v1',
                behaviorLabels: 1_000,
                canonicalEpisodeAssignmentLabels: 1_000,
                canonicalEpisodeAttachLabels: 996,
                canonicalEpisodeCreateLabels: 3,
                canonicalEpisodeAbstainLabels: 1,
                canonicalEpisodeFirstObservedAt: 100,
                canonicalEpisodeLastObservedAt: 2_760_100,
                canonicalEpisodeCandidateCountTotal: 4_000,
                canonicalEpisodeCandidateCountMin: 3,
                canonicalEpisodeCandidateCountMax: 6,
                operatorPreferenceLabels: 1_000,
                executionOutcomes: 1_000,
                rewardCompleteOutcomes: 0,
                rewardCensoredOutcomes: 1_000,
                counterfactualReadyDecisions: 0,
                graphTruthLinkedDecisions: 1_000,
            }),
            observeNativeRewardHorizons: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-canonical-reward-producer-report/v1',
                observedAt: 200,
                linkedCommits: 1_000,
                humanEvidenceAppended: 0,
                humanObservationsAppended: 0,
                stabilityEvidenceAppended: 2,
                stabilityObservationsAppended: 2,
                alreadyObserved: 2_000,
                pendingHorizons: 0,
                nextEligibleAt: null,
            }),
            nativeRewardObservationCensus: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-native-reward-observation-census/v1',
                observationReceipts: 2_000,
                activeHumanAcceptance: 1_000,
                activeFutureStability: 1_000,
                positiveFutureStability: 999,
                negativeFutureStability: 1,
                matureCanonicalEpisodeAssignments: 1_000,
                positiveCanonicalEpisodeStability: 999,
                negativeCanonicalEpisodeStability: 1,
                pendingCanonicalEpisodeHorizons: 0,
                retractedDimensions: 0,
                partiallyObservedDecisions: 1_000,
                fullyObservedDecisions: 0,
            }),
        };

        const readiness = await loadCanonicalEpisodeAssignmentReadiness(surface);

        expect(readiness).toMatchObject({
            decisions: 1_000,
            attached: 996,
            created: 3,
            abstained: 1,
            chronologicalSpanMs: 2_760_000,
            chronologicalSpanLabel: '46 min',
            chronologicalSpanGate: 'waiting',
            averageCandidates: 4,
            candidateCountRange: '3-6',
            mature: 1_000,
            stable: 999,
            revised: 1,
            pendingHorizons: 0,
            plumbingGate: 'passed',
            pilotGate: 'passed',
            researchCountGate: 'passed',
            datasetRole: 'train-only',
            datasetEligibilityGate: 'blocked',
            splitWitnesses: 'unavailable',
            promotionGate: 'locked',
        });
        expect(surface.observeNativeRewardHorizons).toHaveBeenCalledOnce();
    });

    it('fails closed on incomplete census payloads', async () => {
        const surface = {
            nativeDecisionCensus: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-native-decision-census/v1',
            }),
            observeNativeRewardHorizons: vi.fn(),
            nativeRewardObservationCensus: vi.fn(),
        };
        await expect(loadCanonicalEpisodeAssignmentReadiness(surface)).rejects.toThrow(
            /invalid behaviorLabels/,
        );
        expect(surface.observeNativeRewardHorizons).not.toHaveBeenCalled();
    });
});
