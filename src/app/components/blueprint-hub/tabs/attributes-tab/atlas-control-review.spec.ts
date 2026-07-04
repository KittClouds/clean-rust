import { describe, expect, it } from 'vitest';

import type { RegisteredEntity } from '../../../../lib/registry';
import type {
    GraphMemoryGovernanceSignals,
    GraphRebuildSnapshot,
} from '../../../../graph-rebuild/graph-rebuild-snapshot';
import { buildAtlasControlReviewDeck } from './atlas-control-review';

describe('buildAtlasControlReviewDeck', () => {
    it('separates contradiction, supersession, and negative relation review lanes', () => {
        const deck = buildAtlasControlReviewDeck(snapshot(), entities());

        expect(deck.governanceLanes.find((lane) => lane.id === 'contradiction')?.count).toBe(1);
        expect(deck.governanceLanes.find((lane) => lane.id === 'supersession')?.count).toBe(1);
        expect(deck.negativeRelations).toHaveLength(1);
        expect(deck.negativeRelations[0]).toMatchObject({
            relation: 'Opposes',
            pair: 'Kai -> Hazel',
            source: 'negative cue',
        });
        expect(deck.noTopologyCommit).toBe(4);
        expect(deck.attentionCount).toBe(3);
        expect(deck.candidateRows).toHaveLength(4);
        expect(deck.candidateRows.map((row) => row.action)).toEqual([
            'Quarantine',
            'Attenuate',
            'Compress',
            'Keep vivid',
        ]);
        expect(deck.actionSummaries).toEqual(expect.arrayContaining([
            expect.objectContaining({ action: 'retain', count: 1 }),
            expect.objectContaining({ action: 'compress', count: 1 }),
            expect.objectContaining({ action: 'attenuate', count: 1 }),
            expect.objectContaining({ action: 'quarantine', count: 1 }),
        ]));
        expect(deck.runtimeDiagnostics).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'nativeMemoryGovernanceSkipped',
                value: 'Active',
                tone: 'ready',
            }),
            expect.objectContaining({
                id: 'nativeMemoryGovernanceCandidates',
                value: '4',
                tone: 'ready',
            }),
            expect.objectContaining({
                id: 'nativeMemoryGovernanceRustMicros',
                value: '4,337 us',
                tone: 'ready',
            }),
        ]));
    });
});

function entities(): RegisteredEntity[] {
    return [
        { id: 'e-kai', label: 'Kai', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'e-hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
    ] as unknown as RegisteredEntity[];
}

function snapshot(): GraphRebuildSnapshot {
    return {
        id: 'snapshot:atlas-control-review',
        chunks: [
            { id: 'chunk:1', noteId: 'note-1', start: 0, end: 20, ordinal: 0, source: 'dynamic-chunking', role: 'scene_action' },
            { id: 'chunk:2', noteId: 'note-1', start: 20, end: 40, ordinal: 1, source: 'dynamic-chunking', role: 'authority_chain' },
        ],
        episodes: [
            { id: 'episode:1', label: 'Kharon Vel lunch', chunkIds: ['chunk:1', 'chunk:2'] },
            { id: 'episode:2', label: 'Gate repair', chunkIds: ['chunk:2'] },
        ],
        buildTimings: {
            nativeMemoryGovernanceSkipped: 0,
            nativeMemoryGovernanceCandidates: 4,
            nativeMemoryGovernanceRustMicros: 4337,
        },
        relationships: [{
            id: 'rel:negative',
            sourceEntityId: 'e-kai',
            targetEntityId: 'e-hazel',
            relationType: 'opposes',
            evidenceAnchorIds: ['anchor:1'],
            confidence: 0.68,
            status: 'review',
            adjudicationSource: 'graph-rebuild-negative-cue-review-policy',
            adjudicationScore: 0.68,
            rationale: 'review: negative relation cue requires confirmation before promotion: opposes',
            decisionEvidence: ['chunk:1'],
        }],
        memoryGovernanceCandidates: [
            {
                schemaVersion: 'phoenix-memory-governance-candidate/v1',
                id: 'gov:contradiction',
                targetId: 'chunk:1',
                targetKind: 'chunk',
                action: 'quarantine',
                reason: 'target_has_contradictory_memory_evidence',
                evidenceIds: ['anchor:1'],
                supportingEntityIds: ['e-kai'],
                relatedEventIds: [],
                relatedChunkIds: [],
                signals: signals({ contradictionRisk: 0.78 }),
                confidence: 0.75,
                status: 'candidate',
                commitPolicy: 'no_topology_commit',
                noTopologyCommit: true,
                rationale: ['audit:contradictory_memory_evidence', 'memory_governance_candidate:no_topology_commit'],
            },
            {
                schemaVersion: 'phoenix-memory-governance-candidate/v1',
                id: 'gov:supersession',
                targetId: 'chunk:2',
                targetKind: 'chunk',
                action: 'attenuate',
                reason: 'target_superseded_by_later_memory_evidence',
                evidenceIds: ['anchor:2'],
                supportingEntityIds: ['e-hazel'],
                relatedEventIds: [],
                relatedChunkIds: [],
                signals: signals({ age: 0.72 }),
                confidence: 0.64,
                status: 'candidate',
                commitPolicy: 'no_topology_commit',
                noTopologyCommit: true,
                rationale: ['audit:superseded_memory_evidence', 'memory_governance_candidate:no_topology_commit'],
            },
            {
                schemaVersion: 'phoenix-memory-governance-candidate/v1',
                id: 'gov:compress',
                targetId: 'episode:1',
                targetKind: 'episode',
                action: 'compress',
                reason: 'episode_can_compact_child_chunks',
                evidenceIds: ['anchor:1', 'anchor:2'],
                supportingEntityIds: ['e-kai', 'e-hazel'],
                relatedEventIds: ['event:1'],
                relatedChunkIds: ['chunk:1', 'chunk:2'],
                signals: signals({ narrativeSalience: 0.82, evidenceStrength: 0.76 }),
                confidence: 0.71,
                status: 'candidate',
                commitPolicy: 'no_topology_commit',
                noTopologyCommit: true,
                rationale: ['reason:episode_can_compact_child_chunks', 'memory_governance_candidate:no_topology_commit'],
            },
            {
                schemaVersion: 'phoenix-memory-governance-candidate/v1',
                id: 'gov:retain',
                targetId: 'episode:2',
                targetKind: 'episode',
                action: 'retain',
                reason: 'episode_preserves_story_continuity',
                evidenceIds: ['anchor:2'],
                supportingEntityIds: ['e-hazel'],
                relatedEventIds: ['event:2'],
                relatedChunkIds: ['chunk:2'],
                signals: signals({ causalImportance: 0.48, retrievalUtility: 0.66 }),
                confidence: 0.61,
                status: 'candidate',
                commitPolicy: 'no_topology_commit',
                noTopologyCommit: true,
                rationale: ['reason:episode_preserves_story_continuity', 'memory_governance_candidate:no_topology_commit'],
            },
        ],
    } as unknown as GraphRebuildSnapshot;
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
