import { describe, expect, it } from 'vitest';

import { buildGraphProjectionContractReport } from './graph-projection-contract-report';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('graph projection contract report', () => {
    it('flags signature-preview coordinates while counting hypergraph representations', () => {
        const snapshot = snapshotWithContract({
            vectorSource: 'signature-preview',
            vectorCount: 0,
            graphNodes: 2,
        });

        const report = buildGraphProjectionContractReport(snapshot, { embeddingNodes: 3, embeddingEdges: 2 });

        expect(report.compilerLabel).toBe('Rust hypergraph compiler');
        expect(report.semanticCoordinatesLabel).toBe('deterministic signature preview');
        expect(report.status).toBe('danger');
        expect(report.counts.hypergraphRoles).toBe(2);
        expect(report.counts.representationCounts.incidence_object).toBe(1);
        expect(report.counts.representationCounts.structural_region).toBe(1);
        expect(report.counts.representationCounts.attached_span).toBe(1);
        expect(report.vectorLabel).toBe('Signature preview coordinates');
    });

    it('marks the contract ready when native vectors cover the admitted targets', () => {
        const snapshot = snapshotWithContract({
            vectorSource: 'semantic-runner',
            vectorCount: 3,
            graphNodes: 3,
        });

        const report = buildGraphProjectionContractReport(snapshot, {
            receipt: { postProcessMode: 'full', counters: { embeddingVectors: 3 } },
            embeddingNodes: 3,
            embeddingEdges: 2,
        });

        expect(report.status).toBe('ready');
        expect(report.vectorLabel).toBe('Native semantic vectors');
        expect(report.parityLabel).toBe('count parity');
    });

});

function snapshotWithContract(options: {
    vectorSource: 'signature-preview' | 'semantic-runner';
    vectorCount: number;
    graphNodes: number;
}): GraphRebuildSnapshot {
    const targets = [
        {
            id: 'target:document',
            kind: 'documentUnit',
            sourceId: 'note-1',
            noteId: 'note-1',
            label: 'Document root',
            text: 'Document root',
            evidenceIds: [],
            lane: 'document_spine',
            structuralRole: 'spine',
        },
        {
            id: 'target:hyperedge',
            kind: 'graphFact',
            sourceId: 'fact:transfer',
            noteId: 'note-1',
            chunkId: 'chunk-1',
            label: 'Transfer',
            text: 'Amara gives Hazel the engine key.',
            evidenceIds: ['span-1'],
            lane: 'relationship_fact',
            structuralRole: 'fact',
        },
        {
            id: 'target:span',
            kind: 'evidenceSpan',
            sourceId: 'span-1',
            noteId: 'note-1',
            chunkId: 'chunk-1',
            label: 'engine key',
            text: 'engine key',
            evidenceIds: ['span-1'],
            lane: 'anchor_evidence',
            structuralRole: 'evidence',
        },
    ];
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'snapshot-contract-1',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'note',
        scopeId: 'note-1',
        noteIds: ['note-1'],
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
        embeddingTargets: targets,
        embeddingTargetPlan: {
            schemaVersion: 'phoenix-signal-target-plan/v1',
            candidateCount: targets.length,
            admittedCount: targets.length,
            deferredCount: 0,
            maxAdmitted: targets.length,
            canonicalCount: targets.length,
            queuedCount: targets.length,
            schedulerDeferredCount: 0,
            policyDeferredCount: 0,
            maxQueued: targets.length,
            queuedTargetIds: targets.map((target) => target.id),
            schedulerDeferredTargetIds: [],
            policyDeferredTargetIds: [],
            lanes: [],
        },
        embeddingVectors: Array.from({ length: options.vectorCount }, (_, index) => ({
            targetId: targets[index]?.id || `target:${index}`,
            modelId: 'jina-v5-nano-retrieval',
            dims: 768,
            generation: 1,
        })),
        embeddingProfile: {
            schemaVersion: 'phoenix-embedding-profile/v1',
            modelId: 'jina-v5-nano-retrieval',
            modelLabel: 'Jina v5 Nano',
            modelFamily: 'jina-v5',
            dimensionLabel: '768d',
            nativeDimensions: 768,
            selectedDimensions: 768,
            taskProfile: 'semantic_topology',
            vectorSource: options.vectorSource,
            normalized: true,
            normalization: 'unit_l2',
            topologySupport: 'native',
            supportsMultiVector: false,
            vectorHeads: [],
        },
        projectionRefs: [],
        nodes: Array.from({ length: options.graphNodes }, (_, index) => ({
            entityId: `entity-${index}`,
            label: `Entity ${index}`,
            kind: 'CHARACTER',
            totalMentions: 1,
            noteIds: ['note-1'],
            aliases: [],
        })),
        edges: Array.from({ length: 2 }, (_, index) => ({
            id: `edge-${index}`,
            sourceId: 'entity-0',
            targetId: 'entity-1',
            weight: 1,
            noteIds: ['note-1'],
            evidenceAnchorIds: ['span-1'],
        })),
        graphCompilerSource: 'rust',
        graphModelV2: {
            schemaVersion: 'phoenix-graph-model/v2',
            sourceSnapshotId: 'snapshot-contract-1',
            builtAt: 1,
            atoms: [],
            laneRoots: [],
            bundles: [],
            facts: [{
                id: 'fact:transfer',
                family: 'transfer',
                relationType: 'gives',
                lane: 'relationship_fact',
                status: 'accepted',
                confidence: 0.92,
                evidenceIds: ['span-1'],
                sourceRecordId: 'fact:transfer',
                semanticSituationId: 'situation:transfer',
            }],
            roles: [
                { factId: 'fact:transfer', role: 'actor', targetAtomId: 'atom:entity:amara', confidence: 0.9, resolved: true },
                { factId: 'fact:transfer', role: 'recipient', targetAtomId: 'atom:entity:hazel', confidence: 0.9, resolved: true },
            ],
            styleTags: [],
            projectionEdges: [],
            counters: {
                atoms: 0,
                laneRoots: 0,
                bundles: 0,
                facts: 1,
                roles: 2,
                styleTags: 0,
                projectionEdges: 0,
                stagedCooccurrenceBundles: 0,
                weakCooccurrenceFacts: 0,
                hyperedgeFacts: 1,
            },
        },
        counters: {
            nodes: options.graphNodes,
            edges: 2,
            embeddingTargets: targets.length,
            embeddingTargetCandidates: targets.length,
            embeddingQueuedTargets: targets.length,
            embeddingVectors: options.vectorCount,
            documentReviewAcceptedRows: 3,
            documentReviewProposedRows: 0,
            documentReviewRejectedRows: 0,
            documentCompilerHyperedges: 1,
            dropReasons: {
                missingEntity: 0,
                invalidSpan: 0,
                duplicateAnchor: 0,
                singletonBucket: 0,
            },
        },
    } as unknown as GraphRebuildSnapshot;
}
