import { describe, expect, it, vi } from 'vitest';

import { loadCanonicalEpisodeAssignmentReadiness } from './graph-canonical-episode-readiness';

describe('canonical episode assignment readiness', () => {
    it('reconciles horizons before declaring count gates', async () => {
        const surface = {
            nativeDecisionCensus: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-native-decision-census/v1',
                behaviorLabels: 14,
                canonicalEpisodeAssignmentLabels: 12,
                canonicalEpisodeAttachLabels: 8,
                canonicalEpisodeCreateLabels: 3,
                canonicalEpisodeAbstainLabels: 1,
                canonicalEpisodeFirstObservedAt: 100,
                canonicalEpisodeLastObservedAt: 86_400_101,
                canonicalEpisodeCandidateCountTotal: 48,
                canonicalEpisodeCandidateCountMin: 3,
                canonicalEpisodeCandidateCountMax: 6,
                operatorPreferenceLabels: 14,
                executionOutcomes: 14,
                rewardCompleteOutcomes: 0,
                rewardCensoredOutcomes: 14,
                counterfactualReadyDecisions: 0,
                graphTruthLinkedDecisions: 11,
            }),
            observeNativeRewardHorizons: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-canonical-reward-producer-report/v1',
                observedAt: 200,
                linkedCommits: 11,
                humanEvidenceAppended: 0,
                humanObservationsAppended: 0,
                stabilityEvidenceAppended: 2,
                stabilityObservationsAppended: 2,
                alreadyObserved: 9,
                pendingHorizons: 1,
                nextEligibleAt: 300,
            }),
            nativeRewardObservationCensus: vi.fn().mockResolvedValue({
                schemaVersion: 'phoenix-native-reward-observation-census/v1',
                observationReceipts: 21,
                activeHumanAcceptance: 11,
                activeFutureStability: 10,
                positiveFutureStability: 9,
                negativeFutureStability: 1,
                matureCanonicalEpisodeAssignments: 10,
                positiveCanonicalEpisodeStability: 9,
                negativeCanonicalEpisodeStability: 1,
                pendingCanonicalEpisodeHorizons: 1,
                retractedDimensions: 0,
                partiallyObservedDecisions: 1,
                fullyObservedDecisions: 10,
            }),
        };

        const readiness = await loadCanonicalEpisodeAssignmentReadiness(surface);

        expect(readiness).toMatchObject({
            decisions: 12,
            attached: 8,
            created: 3,
            abstained: 1,
            chronologicalSpanDays: 2,
            averageCandidates: 4,
            candidateCountRange: '3-6',
            mature: 10,
            stable: 9,
            revised: 1,
            pendingHorizons: 1,
            plumbingGate: 'passed',
            pilotGate: 'waiting',
            researchCountGate: 'waiting',
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
