import { describe, expect, it } from 'vitest';

import {
    applyNativeMemoryGovernanceCandidates,
    applyNativeMemoryGovernanceRetrievalExperiment,
    assertMemoryGovernanceCandidateOnly,
    assertMemoryGovernanceRetrievalExperimentReportOnly,
    memoryGovernanceRetrievalCandidatesFromSnapshot,
} from './graph-memory-governance';
import {
    GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
    GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    GRAPH_MEMORY_GOVERNANCE_RETRIEVAL_EXPERIMENT_SCHEMA_VERSION,
    GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
    type GraphMemoryGovernanceCandidate,
    type GraphMemoryGovernanceRetrievalWeightingExperiment,
    type GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

describe('graph memory governance', () => {
    it('attaches rust candidate-only governance rows without topology mutation', () => {
        const snapshot = minimalSnapshot();
        const edges = snapshot.edges;
        const row = governanceCandidate('chunk:1', 'chunk', 'attenuate');

        applyNativeMemoryGovernanceCandidates(snapshot, [row]);

        expect(snapshot.edges).toBe(edges);
        expect(snapshot.memoryGovernanceCandidates).toEqual([row]);
        expect(snapshot.counters.memoryGovernanceCandidates).toBe(1);
        expect(snapshot.counters.memoryGovernanceAttenuate).toBe(1);
        expect(snapshot.counters.memoryGovernanceRetain).toBe(0);
    });

    it('rejects governance rows that can commit topology', () => {
        const row = {
            ...governanceCandidate('episode:1', 'episode', 'compress'),
            noTopologyCommit: false,
        } as unknown as GraphMemoryGovernanceCandidate;

        expect(() => assertMemoryGovernanceCandidateOnly([row])).toThrow(/may not mutate topology/);
    });

    it('feeds real app embedding targets into retrieval experiment rows', () => {
        const snapshot = minimalSnapshot();
        snapshot.embeddingTargets = [
            {
                id: 'embed:chunk:chunk:1',
                kind: 'chunk',
                sourceId: 'chunk:1',
                chunkId: 'chunk:1',
                label: 'Chunk 1',
                text: 'because the route changed after the warning',
                evidenceIds: ['evidence:1'],
                admissionStatus: 'admitted',
                workStatus: 'queued',
            },
            {
                id: 'embed:episode:episode:1',
                kind: 'episode',
                sourceId: 'episode:1',
                label: 'Tower access shifts',
                text: 'episode with causal continuity',
                evidenceIds: ['evidence:2', 'evidence:3'],
                admissionStatus: 'admitted',
                workStatus: 'queued',
            },
            {
                id: 'embed:document-unit:retrieval:1',
                kind: 'documentUnit',
                sourceId: 'retrieval:1',
                chunkId: 'chunk:2',
                label: 'Retrieval unit',
                text: 'document_sidecar:retrieval_unit evidence_context:route',
                evidenceIds: ['evidence:4'],
                documentUnitKind: 'retrieval_unit',
                admissionStatus: 'admitted',
                workStatus: 'queued',
            },
            {
                id: 'embed:entity:entity:1',
                kind: 'entity',
                sourceId: 'entity:1',
                entityId: 'entity:1',
                label: 'Kai',
                text: 'entity anchor',
                evidenceIds: [],
                admissionStatus: 'admitted',
                workStatus: 'queued',
            },
        ];

        const rows = memoryGovernanceRetrievalCandidatesFromSnapshot(snapshot);

        expect(rows).toHaveLength(3);
        expect(rows.map((row) => row.targetKind).sort()).toEqual(['chunk', 'chunk', 'episode']);
        expect(rows.map((row) => row.targetId)).toContain('chunk:2');
        expect(rows.every((row) => row.score > 0 && row.score <= 1)).toBe(true);
        expect(snapshot.embeddingTargets).toHaveLength(4);
    });

    it('attaches native retrieval experiment reports without ranking or topology mutation', () => {
        const snapshot = minimalSnapshot();
        const edges = snapshot.edges;
        const experiment = retrievalExperiment();

        applyNativeMemoryGovernanceRetrievalExperiment(snapshot, experiment);

        expect(snapshot.edges).toBe(edges);
        expect(snapshot.memoryGovernanceRetrievalExperiment).toBe(experiment);
        expect(snapshot.counters.memoryGovernanceRetrievalCandidates).toBe(2);
        expect(snapshot.counters.memoryGovernanceRetrievalGoverned).toBe(1);
        expect(snapshot.counters.memoryGovernanceRetrievalChangedRanks).toBe(1);
        expect(snapshot.counters.memoryGovernanceRetrievalPolicies).toBe(1);
    });

    it('rejects retrieval experiment rows that can commit topology', () => {
        const experiment = retrievalExperiment();
        (experiment.variants[0].topRows[0] as unknown as { noTopologyCommit: boolean }).noTopologyCommit = false;

        expect(() => assertMemoryGovernanceRetrievalExperimentReportOnly(experiment))
            .toThrow(/may not mutate topology/);
    });
});

function governanceCandidate(
    targetId: string,
    targetKind: GraphMemoryGovernanceCandidate['targetKind'],
    action: GraphMemoryGovernanceCandidate['action'],
): GraphMemoryGovernanceCandidate {
    return {
        schemaVersion: GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
        id: `memory_governance:${targetKind}:${action}:${targetId}`,
        targetId,
        targetKind,
        action,
        reason: 'test',
        evidenceIds: [],
        supportingEntityIds: [],
        relatedEventIds: [],
        relatedChunkIds: [],
        signals: {
            age: 0,
            accessFrequency: 0,
            redundancy: 0,
            contradictionRisk: 0,
            causalImportance: 0,
            narrativeSalience: 0,
            retrievalUtility: 0,
            evidenceStrength: 0,
            userPinned: false,
        },
        confidence: 0.6,
        status: 'candidate',
        commitPolicy: GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
        noTopologyCommit: true,
        rationale: [GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT],
    };
}

function minimalSnapshot(): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot:memory-governance',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'note',
        scopeId: 'note:1',
        noteIds: ['note:1'],
        builtAt: 1,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
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
    };
}

function retrievalExperiment(): GraphMemoryGovernanceRetrievalWeightingExperiment {
    return {
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
                candidateCount: 2,
                governedCount: 1,
                retainedCount: 1,
                attenuatedCount: 0,
                compressedCount: 0,
                unchangedCount: 1,
                changedRankCount: 1,
                promotedCount: 1,
                demotedCount: 0,
            },
            topRows: [{
                id: 'memory_governance_retrieval_preview:app_embedding_target:embed:episode:episode:1',
                targetId: 'episode:1',
                targetKind: 'episode',
                originalRank: 2,
                adjustedRank: 1,
                originalScore: 0.7,
                adjustedScore: 0.8,
                scoreDelta: 0.1,
                governanceCandidateId: 'memory_governance:episode:retain:episode:1',
                governanceAction: 'retain',
                governanceConfidence: 0.7,
                reason: 'episode_has_causal_or_temporal_role',
                rationale: [GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT],
                noTopologyCommit: true,
            }],
            meanAbsRankDeltaMillis: 500,
            retainedMeanScoreDeltaMillis: 100,
            compressedMeanScoreDeltaMillis: 0,
            attenuatedMeanScoreDeltaMillis: 0,
        }],
    };
}
