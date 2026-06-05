import { describe, expect, it } from 'vitest';

import type { RegisteredEntity } from '../../../../lib/registry';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import { buildGraphDiscourseAnalyticsView } from './graph-discourse-analytics';
import type { ProductDiagnosticsView } from './graph-product-diagnostics';

describe('buildGraphDiscourseAnalyticsView', () => {
    it('builds receipt-backed discourse tabs from graph rebuild surfaces', () => {
        const view = buildGraphDiscourseAnalyticsView(snapshot(), diagnostics(), null, entities());

        expect(view?.tabs.map((tab) => tab.id)).toEqual(['insights', 'ideas', 'gaps', 'relations', 'stance', 'stats']);
        expect(view?.summary).toContain('accepted decisions');
        expect(view?.panels.gaps.summary).toContain('ambiguous');
        expect(view?.panels.relations.chips.some((chip) => chip.label === 'Trusts')).toBe(true);
        expect(view?.underlyingIdeas.some((idea) => idea.id === 'memory-bridge')).toBe(true);
        expect(view?.questions[0].prompt).toContain('resolve');
    });

    it('uses the selected entity as the first exploration question', () => {
        const hazel = entities()[1];
        const view = buildGraphDiscourseAnalyticsView(snapshot(), diagnostics(), hazel, entities());

        expect(view?.title).toBe('Hazel');
        expect(view?.questions[0]).toMatchObject({
            id: 'selected-entity',
            query: 'Hazel',
        });
        expect(view?.summary).toContain('Hazel');
    });
});

function entities(): RegisteredEntity[] {
    return [
        { id: 'kai', label: 'Kai', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'red-mesa', label: 'Red Mesa', kind: 'LOCATION', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
    ] as RegisteredEntity[];
}

function diagnostics(): ProductDiagnosticsView {
    return {
        snapshotId: 'snap-1',
        modelLabel: 'bge-small',
        dimensionLabel: '384d',
        summary: {
            targetCount: 14,
            clusterCount: 3,
            regionCount: 2,
            backboneEdges: 4,
            bridgeEdges: 2,
            outliers: 1,
            topRegions: [
                { role: 'core', lane: 'entity', count: 8 },
                { role: 'bridge', lane: 'relation', count: 4 },
            ],
        },
        suggestions: [],
        reviewClusters: [
            {
                id: 'review:trust',
                label: 'Relation: trusts',
                kind: 'graph-link',
                count: 5,
                representativeCount: 2,
                confidence: 0.72,
                impact: 0.8,
                conflicts: 1,
                action: 'Review family',
                examples: ['Kai -> Hazel'],
                signals: ['backbone', 'same_cluster'],
            },
        ],
    };
}

function snapshot(): GraphRebuildSnapshot {
    return {
        id: 'snap-1',
        schemaVersion: 'phoenix-graph-rebuild/v1',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        builtAt: 1,
        relationships: [
            {
                id: 'rel-1',
                sourceEntityId: 'kai',
                targetEntityId: 'hazel',
                relationType: 'trusts',
                evidenceAnchorIds: ['a1'],
                confidence: 0.9,
                status: 'accepted',
                adjudicationSource: 'test',
                adjudicationScore: 0.9,
                rationale: 'strong evidence',
                decisionEvidence: ['a1'],
            },
        ],
        graphAwareLinkSuggestions: [
            {
                id: 's1',
                kind: 'backbone_promotion',
                sourceEntityId: 'kai',
                targetEntityId: 'hazel',
                suggestedRelationType: 'trusts',
                status: 'review',
                confidence: 0.8,
                semanticStatus: 'review',
                structuralRole: 'shared_component',
                productLane: 'relation',
                productRegionRole: 'bridge',
                rerankSignals: ['manifold:product'],
                rationale: ['bridge'],
                evidenceIds: ['a1'],
            },
        ],
        edges: [{ id: 'e1', sourceId: 'kai', targetId: 'hazel', type: 'trusts', weight: 1, confidence: 0.9, evidenceAnchorIds: ['a1'], scopeKeys: [], noteIds: [] }],
        causalEdges: [{
            id: 'c1',
            sourceId: 'event-a',
            targetId: 'event-b',
            relationType: 'causes',
            evidenceIds: ['a1'],
            confidence: 0.7,
            status: 'supported',
            sourceKind: 'graph_support',
            evidenceClass: 'graph_support',
            polarity: 'support',
            modality: 'asserted',
            sourceSemantics: 'world_assertion',
            supportIds: ['rel-1'],
        }],
        temporalEdges: [],
        semanticCandidateSummary: { counters: { byKind: { missing_frame: 2 } } },
        semanticAdjudicationSummary: {
            receipts: [{ id: 'r1' }],
            counters: { byState: { accepted: 1 }, ledgerOnlyCount: 2 },
        },
        semanticEvalLedgerSummary: {
            entries: [{ id: 'row-1' }],
            counters: {
                acceptedCandidates: 1,
                rejectedCandidates: 1,
                ambiguousCases: 1,
                modelDisagreements: 1,
                manifoldDisagreements: 1,
                graphChangeRows: 1,
            },
        },
        semanticRerankSummary: {
            scoreSource: 'deterministic_calibration',
            judgments: [{ id: 'j1' }],
        },
        memoryGraphRagBridgeSummary: {
            counters: {
                evalRowCount: 3,
                receiptCount: 2,
            },
        },
        embeddingGraphPostProcess: {
            metrics: { outlierCount: 1 },
        },
        counters: {
            nodes: 3,
            edges: 1,
            relationships: 1,
            embeddingTargets: 14,
            embeddingVectors: 14,
            semanticEvalAcceptedCandidates: 1,
            semanticEvalRejectedCandidates: 1,
            semanticEvalAmbiguousCases: 1,
            semanticEvalModelDisagreements: 1,
            semanticEvalManifoldDisagreements: 1,
            semanticEvalGraphChangeRows: 1,
            semanticAdjudicationLedgerOnly: 2,
        },
        buildTimings: { totalMs: 42 },
    } as unknown as GraphRebuildSnapshot;
}
