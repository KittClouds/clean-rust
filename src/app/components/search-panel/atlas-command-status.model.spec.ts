import { describe, expect, it } from 'vitest';

import {
    buildAtlasCommandStatus,
    estimateDynamicChunks,
} from './atlas-command-status.model';
import type { GraphAuditSnapshot } from '../../services/graph-audit.model';
import type { AtlasRichScanResult } from '../../services/phoenix-ui-api.service';

describe('atlas command status model', () => {
    it('labels graph inventory by backend source instead of one fuzzy graph count', () => {
        const status = buildAtlasCommandStatus({
            scopeLabel: 'Global',
            noteCount: 3,
            estimatedChunks: 8,
            audit: audit(),
            stages: {},
            activeJob: null,
            lastSummary: null,
            lastRichScan: null,
            vectorStatus: 'idle',
            graphStatus: 'ready',
            manifoldMode: 'hybrid',
            manifoldStatus: 'ready',
            manifoldStatuses: { hybrid: 'ready', hopf: 'idle', lorentz: 'idle' },
            dynamicNerStatus: 'ready',
            enabledLanes: ['lexical', 'graph'],
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
        });

        expect(status.ledgerGroups.map((group) => group.title)).toEqual([
            'Scope',
            'Registry',
            'Committed Graph',
            'Semantic Atlas',
            'Graph Audit',
        ]);
        expect(status.metrics.map((metric) => metric.label)).toEqual([
            'Scope notes',
            'Registry entities',
            'Committed vertices',
            'Committed evidence edges',
            'Graph leaves',
            'Embedding vectors',
            'Issues',
        ]);
        expect(status.metrics.map((metric) => metric.label)).not.toContain('Graph');
        expect(status.inventory.committedVertices).toBe(88);
        expect(status.inventory.graphLeaves).toBe(64);
        expect(status.inventory.evidenceEdges).toBe(96);
        expect(status.metrics.find((metric) => metric.label === 'Embedding vectors')?.value).toBeNull();
        expect(status.metrics.find((metric) => metric.label === 'Embedding vectors')?.availability).toBe('unavailable');
    });

    it('marks text graph runs as embeddings skipped when includeSemanticAtlas is false', () => {
        const status = buildAtlasCommandStatus({
            scopeLabel: 'Global',
            noteCount: 1,
            estimatedChunks: 2,
            audit: audit(),
            stages: {},
            activeJob: null,
            lastSummary: {
                kind: 'atlas-rich-scan',
                label: 'Text graph processed 1 document without embeddings',
                startedAt: 1,
                completedAt: 5,
                durationMs: 4,
            },
            lastRichScan: richScan(false),
            vectorStatus: 'idle',
            graphStatus: 'ready',
            manifoldMode: 'hopf',
            manifoldStatus: 'stale',
            manifoldStatuses: { hybrid: 'ready', hopf: 'stale', lorentz: 'idle' },
            dynamicNerStatus: 'cold',
            enabledLanes: ['lexical'],
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
        });

        expect(status.inventory.embeddingVectors).toBe(0);
        expect(status.inventory.candidateEdges).toBe(0);
        expect(status.lastRun.detail).toContain('embeddings skipped');
    });

    it('tracks each manifold sidecar status separately', () => {
        const status = buildAtlasCommandStatus({
            scopeLabel: 'Global',
            noteCount: 1,
            estimatedChunks: 2,
            audit: audit(),
            stages: {},
            activeJob: null,
            lastSummary: null,
            lastRichScan: null,
            vectorStatus: 'idle',
            graphStatus: 'ready',
            manifoldMode: 'lorentz',
            manifoldStatus: 'loading',
            manifoldStatuses: { hybrid: 'ready', hopf: 'stale', lorentz: 'loading', product: 'idle' },
            dynamicNerStatus: 'cold',
            enabledLanes: ['lexical'],
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
        });

        expect(status.sidecars.map((sidecar) => [sidecar.label, sidecar.detail])).toEqual([
            ['Semantic sidecar', 'idle 384d'],
            ['Hybrid embedding manifold', 'ready'],
            ['Hopf projection', 'stale'],
            ['Lorentz forest', 'loading'],
            ['Product manifold', 'idle'],
        ]);
    });

    it('maps richer capability layers and sleeping capabilities from command state', () => {
        const status = buildAtlasCommandStatus({
            scopeLabel: 'Global',
            noteCount: 1,
            estimatedChunks: 2,
            audit: audit(),
            stages: { surface: { stage: 'surface', status: 'ready', updatedAt: 1 } },
            activeJob: null,
            lastSummary: null,
            lastRichScan: {
                ...richScan(true),
                stageSummaries: [{ stage: 'surface', status: 'ready', durationMs: 12, counts: { chunks: 2 } }],
                lensChunkCounts: { global: 2 },
                graphDeltaCounts: { candidateEdges: 3 },
                embeddingCounts: { leaf: 2, entity: 1, lens: 1 },
                relationCandidateCount: 5,
            },
            vectorStatus: 'ready',
            graphStatus: 'ready',
            manifoldMode: 'hybrid',
            manifoldStatus: 'ready',
            manifoldStatuses: { hybrid: 'ready', hopf: 'stale', lorentz: 'idle', product: 'idle' },
            dynamicNerStatus: 'ready',
            enabledLanes: ['lexical', 'graph'],
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
        });

        expect(status.capabilityLayers.map((layer) => layer.label)).toContain('Reasoning Graphs');
        expect(status.capabilityLayers.flatMap((layer) => layer.capabilities).map((capability) => capability.id))
            .toContain('causalGraph');
        expect(status.sleepingCapabilities.map((capability) => capability.id)).toEqual([
            'relationGraph',
            'temporalGraph',
            'eventIdentity',
            'memoryState',
            'causalGraph',
            'semanticCandidate',
            'nliAdjudication',
            'lorentzForest',
            'productManifold',
        ]);
        expect(status.sleepingCapabilities.find((capability) => capability.id === 'temporalGraph')?.status).toBe('idle');
        expect(status.sleepingCapabilities.find((capability) => capability.id === 'causalGraph')?.detail).toContain('read-only native store probe');
        expect(status.sleepingCapabilities.find((capability) => capability.id === 'relationGraph')?.status).toBe('ready');
        expect(status.sleepingCapabilities.find((capability) => capability.id === 'semanticCandidate')?.status).toBe('ready');
    });

    it('does not mark the whole command console running for passive manifold loads', () => {
        const status = buildAtlasCommandStatus({
            scopeLabel: 'Global',
            noteCount: 1,
            estimatedChunks: 2,
            audit: audit(),
            stages: {},
            activeJob: 'manifold-load',
            lastSummary: null,
            lastRichScan: null,
            vectorStatus: 'idle',
            graphStatus: 'ready',
            manifoldMode: 'hopf',
            manifoldStatus: 'loading',
            manifoldStatuses: { hybrid: 'ready', hopf: 'loading', lorentz: 'idle' },
            dynamicNerStatus: 'cold',
            enabledLanes: ['lexical'],
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
        });

        expect(status.state).toBe('ready');
        expect(status.stages.find((stage) => stage.id === 'sidecars')?.status).toBe('running');
    });

    it('estimates dynamic chunks from scope text using runtime defaults', () => {
        const chunks = estimateDynamicChunks([
            { content: 'a'.repeat(2400) },
            { content: 'b'.repeat(120) },
        ]);

        expect(chunks).toBeGreaterThan(1);
    });
});

function audit(): GraphAuditSnapshot {
    return {
        notes: 3,
        registryEntities: 9,
        registryEdges: 0,
        graphNodes: 88,
        graphEdges: 96,
        liveDocuments: 3,
        indexedDocuments: 3,
        staleDocuments: 0,
        staleDocumentIds: [],
        staleDocumentSamples: [],
        orphanEdges: 2,
        duplicateEdges: 2,
        nodeKinds: [{ key: 'leaf', count: 64 }],
        edgeTypes: [],
        sampleNodes: [],
        sampleEdges: [],
        orphanEdgeSamples: [],
        duplicateEdgeSamples: [],
        updatedAt: 1,
    };
}

function richScan(includeSemanticAtlas: boolean): AtlasRichScanResult {
    return {
        scanId: 'scan-1',
        processedDocuments: 1,
        skippedDocuments: 0,
        stageSummaries: [],
        lensChunkCounts: {},
        graphDeltaCounts: { candidateEdges: 0 },
        embeddingCounts: { leaf: 0, entity: 0, lens: 0 },
        relationCandidateCount: 0,
        candidateSuggestions: [],
        appliedOptions: { includeSemanticAtlas },
    };
}

