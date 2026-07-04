import { describe, expect, it } from 'vitest';

import { buildGraphPromotionPreviewReceipts } from './graph-promotion-verdict';
import type { GraphRebuildLinkSuggestion, GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('graph promotion verdict preview receipts', () => {
    it('turns graph-aware link suggestions into a deterministic candidate-only receipt', () => {
        const receipts = buildGraphPromotionPreviewReceipts(snapshotWithSuggestions([
            linkSuggestion({
                id: 'suggestion-b',
                sourceEntityId: 'entity:rift',
                targetEntityId: 'entity:tempest',
                suggestedRelationType: 'observes',
                evidenceIds: ['chunk:2', 'chunk:2', 'chunk:3'],
                rerankScore: 0.68,
            }),
            linkSuggestion({
                id: 'suggestion-a',
                kind: 'backbone_promotion',
                sourceEntityId: 'entity:borrik',
                targetEntityId: 'entity:brynwyn',
                suggestedRelationType: 'co_occurs_with',
                evidenceIds: ['chunk:1', 'chunk:4'],
                confidence: 0.98,
            }),
        ]));

        expect(receipts).toHaveLength(1);
        expect(receipts[0]).toEqual(expect.objectContaining({
            schemaVersion: 1,
            scopeKey: 'global',
            compilerPolicy: expect.objectContaining({
                policyId: 'graph-post-proposal:atlas-link-preview',
            }),
            modelId: null,
        }));
        expect(receipts[0].receiptId).toBe('graph-proposal:atlas-preview:ea436c3c');
        expect(receipts[0].proposals.map((proposal) => proposal.proposalId)).toEqual([
            'suggestion-a',
            'suggestion-b',
        ]);
        expect(receipts[0].proposals[0]).toEqual(expect.objectContaining({
            atom: {
                kind: 'edge',
                source_id: 'entity:borrik',
                target_id: 'entity:brynwyn',
                edge_type: 'semantic::co_occurs_with',
            },
            truth: { kind: 'semantic', plane: 'worldState' },
            status: 'reviewedSupport',
            evidenceRefs: ['chunk:1', 'chunk:4'],
            shadowScoreMillis: 980,
        }));
        expect(receipts[0].proposals[0].features).toHaveLength(16);
        expect(receipts[0].proposals[1].evidenceRefs).toEqual(['chunk:2', 'chunk:3']);
    });

    it('deduplicates atoms before Rust receipt validation', () => {
        const receipts = buildGraphPromotionPreviewReceipts(snapshotWithSuggestions([
            linkSuggestion({ id: 'first', evidenceIds: ['chunk:1'] }),
            linkSuggestion({ id: 'second', evidenceIds: ['chunk:2'] }),
        ]));

        expect(receipts).toHaveLength(1);
        expect(receipts[0].proposals).toHaveLength(1);
        expect(receipts[0].proposals[0].proposalId).toBe('first');
    });

    it('does not emit empty preview receipts', () => {
        expect(buildGraphPromotionPreviewReceipts(snapshotWithSuggestions([]))).toEqual([]);
    });
});

function snapshotWithSuggestions(
    graphAwareLinkSuggestions: GraphRebuildLinkSuggestion[],
): GraphRebuildSnapshot {
    return {
        id: 'snapshot:stable',
        scopeId: 'global',
        builtAt: 123456,
        graphAwareLinkSuggestions,
    } as unknown as GraphRebuildSnapshot;
}

function linkSuggestion(
    overrides: Partial<GraphRebuildLinkSuggestion> = {},
): GraphRebuildLinkSuggestion {
    return {
        id: 'suggestion',
        kind: 'missing_triangle',
        sourceEntityId: 'entity:kai',
        targetEntityId: 'entity:rift',
        suggestedRelationType: 'observes',
        status: 'review',
        confidence: 0.72,
        semanticStatus: 'none',
        structuralRole: 'shared_component',
        rationale: ['test row'],
        evidenceIds: ['chunk:1'],
        ...overrides,
    };
}
