import { describe, expect, it } from 'vitest';

import {
    applyNativeMemoryGovernanceCandidates,
    assertMemoryGovernanceCandidateOnly,
} from './graph-memory-governance';
import {
    GRAPH_MEMORY_GOVERNANCE_COMMIT_POLICY,
    GRAPH_MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    GRAPH_MEMORY_GOVERNANCE_SCHEMA_VERSION,
    type GraphMemoryGovernanceCandidate,
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
