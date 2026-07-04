import { describe, expect, it } from 'vitest';

import {
    buildGovernanceRunCertificate,
    GRAPH_GOVERNANCE_RUN_CERTIFICATE_SCHEMA_VERSION,
} from './graph-governance-run-certificate';
import {
    GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
    GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION,
    GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
    type GraphMemoryGovernanceCandidate,
    type GraphMemoryGovernanceSignals,
    type GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

describe('buildGovernanceRunCertificate', () => {
    it('certifies candidate-only governance output separately from empty attention lanes', () => {
        const certificate = buildGovernanceRunCertificate(snapshot());

        expect(certificate.schemaVersion).toBe(GRAPH_GOVERNANCE_RUN_CERTIFICATE_SCHEMA_VERSION);
        expect(certificate.document).toMatchObject({
            snapshotId: 'snapshot:certificate',
            scopeId: 'note:shortrun',
            noteIds: ['note:shortrun'],
        });
        expect(certificate.timings).toMatchObject({
            totalMs: 180,
            snapshotBuildMs: 100,
            nativeMemoryGovernanceRustMicros: 9003,
            nativeMemoryGovernanceRetrievalExperimentRustMicros: 2100,
        });
        expect(certificate.candidatesByAction).toMatchObject({
            total: 4,
            retain: 2,
            compress: 1,
            attenuate: 1,
            quarantine: 0,
            retire: 0,
        });
        expect(certificate.attentionLanes.totalAttentionRows).toBe(0);
        expect(certificate.attentionLanes.contradictionQuarantine.count).toBe(0);
        expect(certificate.attentionLanes.supersessionAttenuation.count).toBe(0);
        expect(certificate.attentionLanes.negativeRelationReview.count).toBe(0);
        expect(certificate.noTopologyProof).toMatchObject({
            passed: true,
            candidateRows: 4,
            candidateOnlyRows: 4,
            noTopologyCommitRows: 4,
            retrievalExperimentReportOnly: true,
            retrievalRows: 2,
            retrievalNoTopologyRows: 2,
        });
        expect(certificate.topRows[0]).toMatchObject({
            id: 'gov:compress',
            action: 'compress',
            confidence: 0.89,
        });
        expect(certificate.weakestRows[0]).toMatchObject({
            id: 'gov:retain:2',
            action: 'retain',
            confidence: 0.61,
        });
        expect(certificate.retrievalDeltas.variants[0]).toMatchObject({
            policyId: 'balanced',
            summary: {
                candidateCount: 4,
                governedCount: 2,
                changedRankCount: 2,
                promotedCount: 1,
                demotedCount: 1,
            },
        });
        expect(certificate.retrievalDeltas.variants[0].strongestBoosts[0]).toMatchObject({
            targetId: 'episode:1',
            scoreDelta: 0.12,
            noTopologyCommit: true,
        });
        expect(certificate.retrievalDeltas.variants[0].strongestDemotions[0]).toMatchObject({
            targetId: 'chunk:2',
            scoreDelta: -0.18,
            noTopologyCommit: true,
        });
    });

    it('marks certificate proof failed when a candidate can write topology', () => {
        const graph = snapshot();
        graph.memoryGovernanceCandidates = [
            {
                ...governanceCandidate('gov:bad', 'chunk:bad', 'chunk', 'retain', 0.7),
                noTopologyCommit: false,
                rationale: [],
            } as unknown as GraphMemoryGovernanceCandidate,
        ];

        const certificate = buildGovernanceRunCertificate(graph);

        expect(certificate.noTopologyProof.passed).toBe(false);
        expect(certificate.noTopologyProof.noTopologyCommitRows).toBe(0);
        expect(certificate.noTopologyProof.missingNoTopologyRationaleRows).toBe(1);
        expect(certificate.noTopologyProof.violations).toEqual(expect.arrayContaining([
            'gov:bad:topology_write',
            'gov:bad:missing_no_topology_rationale',
        ]));
    });

    it('separates contradiction, supersession, and negative relation attention lanes', () => {
        const graph = snapshot();
        graph.memoryGovernanceCandidates = [
            governanceCandidate('gov:contradiction', 'chunk:1', 'chunk', 'quarantine', 0.78, {
                contradictionRisk: 0.92,
            }),
            governanceCandidate('gov:supersession', 'chunk:2', 'chunk', 'attenuate', 0.69, {
                age: 0.8,
            }),
        ];
        graph.relationships = [{
            id: 'rel:negative',
            sourceEntityId: 'character:kai',
            targetEntityId: 'character:hazel',
            relationType: 'opposes',
            evidenceAnchorIds: ['anchor:1'],
            decisionEvidence: ['chunk:1'],
            confidence: 0.68,
            status: 'review',
            adjudicationSource: 'graph-rebuild-negative-cue-review-policy',
            adjudicationScore: 0.68,
            rationale: 'negative relation cue requires confirmation',
        }] as GraphRebuildSnapshot['relationships'];

        const certificate = buildGovernanceRunCertificate(graph);

        expect(certificate.attentionLanes.totalAttentionRows).toBe(3);
        expect(certificate.attentionLanes.contradictionQuarantine.count).toBe(1);
        expect(certificate.attentionLanes.supersessionAttenuation.count).toBe(1);
        expect(certificate.attentionLanes.negativeRelationReview.count).toBe(1);
        expect(certificate.attentionLanes.negativeRelationReview.sampleRows[0]).toMatchObject({
            action: 'negative_relation',
            targetKind: 'opposes',
        });
    });
});

function snapshot(): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot:certificate',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'note',
        scopeId: 'note:shortrun',
        noteIds: ['note:shortrun'],
        builtAt: 1783094429874,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        memoryGovernanceCandidates: [
            governanceCandidate('gov:compress', 'episode:1', 'episode', 'compress', 0.89, {
                narrativeSalience: 0.9,
                evidenceStrength: 0.88,
            }),
            governanceCandidate('gov:retain:1', 'chunk:1', 'chunk', 'retain', 0.83, {
                retrievalUtility: 0.74,
                causalImportance: 0.52,
            }),
            governanceCandidate('gov:attenuate', 'chunk:old', 'chunk', 'attenuate', 0.72, {
                redundancy: 0.68,
            }),
            governanceCandidate('gov:retain:2', 'chunk:2', 'chunk', 'retain', 0.61, {
                evidenceStrength: 0.48,
            }),
        ],
        memoryGovernanceRetrievalExperiment: {
            schemaVersion: GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION,
            baselinePolicyId: 'balanced',
            noTopologyCommit: true,
            variants: [{
                policy: {
                    id: 'balanced',
                    retainConfidenceBoost: 0.08,
                    retainCausalBoost: 0.03,
                    retainRetrievalBoost: 0.02,
                    compressConfidenceBoost: 0.14,
                    compressNarrativeBoost: 0.03,
                    attenuateConfidencePenalty: 0.36,
                    quarantineMultiplier: 0.35,
                    retireMultiplier: 0.05,
                },
                summary: {
                    candidateCount: 4,
                    governedCount: 2,
                    retainedCount: 1,
                    attenuatedCount: 1,
                    compressedCount: 1,
                    unchangedCount: 2,
                    changedRankCount: 2,
                    promotedCount: 1,
                    demotedCount: 1,
                },
                topRows: [
                    {
                        id: 'ret:episode:1',
                        targetId: 'episode:1',
                        targetKind: 'episode',
                        originalRank: 4,
                        adjustedRank: 1,
                        originalScore: 0.72,
                        adjustedScore: 0.84,
                        scoreDelta: 0.12,
                        governanceCandidateId: 'gov:compress',
                        governanceAction: 'compress',
                        governanceConfidence: 0.89,
                        reason: 'episode_can_compact_child_chunks',
                        rationale: [GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT],
                        noTopologyCommit: true,
                    },
                    {
                        id: 'ret:chunk:2',
                        targetId: 'chunk:2',
                        targetKind: 'chunk',
                        originalRank: 1,
                        adjustedRank: 5,
                        originalScore: 0.81,
                        adjustedScore: 0.63,
                        scoreDelta: -0.18,
                        governanceCandidateId: 'gov:attenuate',
                        governanceAction: 'attenuate',
                        governanceConfidence: 0.72,
                        reason: 'memory_is_redundant',
                        rationale: [GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT],
                        noTopologyCommit: true,
                    },
                ],
                meanAbsRankDeltaMillis: 2250,
                retainedMeanScoreDeltaMillis: 120,
                compressedMeanScoreDeltaMillis: 120,
                attenuatedMeanScoreDeltaMillis: -180,
            }],
        },
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
        authorityContract: {
            schemaVersion: 'phoenix-graph-snapshot-authority/v1',
            authority: 'graph_rebuild_live_contract',
            snapshotId: 'snapshot:certificate',
            scopeId: 'note:shortrun',
            contentHash: 'sha256:test',
            counts: {
                notes: 1,
                chunks: 2,
                mentions: 0,
                anchors: 0,
                relationships: 0,
                events: 0,
                temporalEdges: 0,
                causalEdges: 0,
                memoryState: 0,
                coreferenceRecoveries: 0,
                nodes: 0,
                edges: 0,
                embeddingTargets: 0,
                admittedEmbeddingTargets: 0,
                packetObjects: 0,
                packetTargets: 0,
                packetParentLinks: 0,
                packetFamilies: {},
            },
        },
        counters: {
            entities: 0,
            aliases: 0,
            candidates: 0,
            mentions: 0,
            acceptedAnchors: 0,
            chunks: 0,
            relationshipCandidates: 0,
            relationships: 0,
            acceptedRelationships: 0,
            reviewRelationships: 0,
            rejectedRelationships: 0,
            events: 0,
            episodes: 0,
            temporalEdges: 0,
            causalEdges: 0,
            memoryState: 0,
            memoryGovernanceBuildMicros: 9003,
            embeddingTargets: 0,
            embeddingVectors: 0,
            projectionRefs: 0,
            nodes: 0,
            edges: 0,
            dropReasons: {
                missingEntity: 0,
                invalidSpan: 0,
                duplicateAnchor: 0,
                singletonBucket: 0,
                missingChunk: 0,
            },
        },
        buildTimings: {
            occurrenceLoadMs: 1,
            chunkLoadMs: 1,
            noteTextLoadMs: 1,
            noteFolderLoadMs: 0,
            dbLoadMs: 2,
            occurrenceRecoverMs: 0,
            snapshotBuildMs: 100,
            stateCommitMs: 1,
            nativeMemoryGovernanceMs: 10,
            nativeMemoryGovernanceCandidates: 4,
            nativeMemoryGovernanceRustMicros: 9003,
            nativeMemoryGovernanceRetrievalExperimentMs: 3,
            nativeMemoryGovernanceRetrievalExperimentCandidates: 4,
            nativeMemoryGovernanceRetrievalExperimentRustMicros: 2100,
            snapshotPersistMs: 1,
            snapshotSerializeMs: 1,
            snapshotStoreMs: 1,
            snapshotEventMs: 1,
            snapshotPayloadChars: 10,
            dbOpsMs: 1,
            totalMs: 180,
        },
    };
}

function governanceCandidate(
    id: string,
    targetId: string,
    targetKind: GraphMemoryGovernanceCandidate['targetKind'],
    action: GraphMemoryGovernanceCandidate['action'],
    confidence: number,
    signalsOverride: Partial<GraphMemoryGovernanceSignals> = {},
): GraphMemoryGovernanceCandidate {
    return {
        schemaVersion: GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
        id,
        targetId,
        targetKind,
        action,
        reason: `${action}_memory_candidate`,
        evidenceIds: ['anchor:1', 'anchor:2'],
        supportingEntityIds: ['character:kai'],
        relatedEventIds: [],
        relatedChunkIds: [],
        signals: signals(signalsOverride),
        confidence,
        status: 'candidate',
        commitPolicy: GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
        noTopologyCommit: true,
        rationale: [`reason:${action}_memory_candidate`, GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT],
    };
}

function signals(overrides: Partial<GraphMemoryGovernanceSignals>): GraphMemoryGovernanceSignals {
    return {
        age: 0,
        accessFrequency: 0,
        redundancy: 0,
        contradictionRisk: 0,
        causalImportance: 0,
        narrativeSalience: 0,
        retrievalUtility: 0,
        evidenceStrength: 0.7,
        userPinned: false,
        ...overrides,
    };
}
