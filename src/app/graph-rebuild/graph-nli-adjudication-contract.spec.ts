import { describe, expect, it } from 'vitest';

import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import {
    isNliClaimAdjudication,
    nliDecisionRequiresReviewVisibility,
    relationshipHintsFromNliResult,
    type NliClaimDecisionKind,
} from './graph-nli-adjudication-contract';

describe('graph NLI adjudication contract', () => {
    it('keeps GLiClass classification votes out of the truth vote', () => {
        const onlyGliclass = {
            sourceId: 'entity-kai',
            targetId: 'entity-hazel',
            classificationVote: gliclassVote('supported', 990),
        };
        const gliclassAsNliVote = adjudication('supported', {
            nliVote: {
                source: 'gliclass',
                role: 'canonFactAdjudication',
                decision: 'supported',
                confidenceMillis: 990,
            },
        });
        const modernBertUnknown = adjudication('unknown', {
            classificationVote: gliclassVote('supported', 990),
            predictedLabel: 'entailment',
            receipts: ['nli-receipt-1'],
            evidenceRefs: ['evidence-ref-1'],
        });

        expect(isNliClaimAdjudication(onlyGliclass)).toBe(false);
        expect(isNliClaimAdjudication(gliclassAsNliVote)).toBe(false);
        expect(relationshipHintsFromNliResult({ adjudications: [onlyGliclass, gliclassAsNliVote] })).toEqual([]);

        const hints = relationshipHintsFromNliResult({ adjudications: [modernBertUnknown] });
        expect(hints).toHaveLength(1);
        expect(hints[0]).toMatchObject({
            status: 'review',
            confidence: 0.51,
            source: 'nli:modernbert',
        });
        expect(hints[0].evidence).toEqual(expect.arrayContaining([
            'receipt:nli-receipt-1',
            'evidence_ref:evidence-ref-1',
            'nli_decision:unknown',
            'classification_source:gliclass',
            'classification_role:relationFrameClassification',
            'classification_label:supported',
            'classification_score_millis:990',
        ]));
    });

    it('uses ModernBERT nliVote for supported contradicted and unknown decisions', () => {
        const hints = relationshipHintsFromNliResult({
            results: [
                adjudication('supported', { predictedLabel: 'contradiction', confidence: 0.01 }),
                adjudication('contradicted', {
                    sourceId: 'entity-kai',
                    targetId: 'entity-rift',
                    predictedLabel: 'entailment',
                    confidence: 0.99,
                    classificationVote: gliclassVote('supported', 970),
                }),
                adjudication('unknown', {
                    sourceId: 'entity-kai',
                    targetId: 'entity-borrik',
                    predictedLabel: 'entailment',
                    confidence: 0.99,
                    classificationVote: gliclassVote('supported', 980),
                }),
            ],
        });

        expect(hints.map((hint) => hint.status)).toEqual(['accepted', 'rejected', 'review']);
        expect(hints.map((hint) => hint.confidence)).toEqual([0.91, 0.88, 0.51]);
        expect(hints[1].evidence).toEqual(expect.arrayContaining([
            'nli_decision:contradicted',
            'classification_label:supported',
        ]));
        expect(hints[2].evidence).toEqual(expect.arrayContaining([
            'nli_decision:unknown',
            'classification_label:supported',
        ]));
    });

    it('keeps unknown and contradiction review-visible instead of dropping them', () => {
        const hints = relationshipHintsFromNliResult({
            adjudications: [
                adjudication('contradicted', { sourceId: 'entity-a', targetId: 'entity-b' }),
                adjudication('unknown', { sourceId: 'entity-a', targetId: 'entity-c' }),
            ],
        });

        expect(nliDecisionRequiresReviewVisibility('contradicted')).toBe(true);
        expect(nliDecisionRequiresReviewVisibility('unknown')).toBe(true);
        expect(nliDecisionRequiresReviewVisibility('supported')).toBe(false);
        expect(hints).toHaveLength(2);
        expect(hints[0]).toMatchObject({ status: 'rejected', source: 'nli:modernbert' });
        expect(hints[1]).toMatchObject({ status: 'review', source: 'nli:modernbert' });
    });

    it('does not let NLI output directly create committed topology', () => {
        const hints = relationshipHintsFromNliResult({
            adjudications: [{
                ...adjudication('supported'),
                nodes: [{ id: 'entity-kai' }],
                edges: [{ sourceId: 'entity-kai', targetId: 'entity-hazel' }],
                relationships: [{ sourceEntityId: 'entity-kai', targetEntityId: 'entity-hazel' }],
            }],
        });
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:nli-contract',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai'), entity('entity-hazel', 'Hazel')],
            occurrences: [],
            relationshipHints: hints,
            builtAt: 1,
        });

        expect(hints).toHaveLength(1);
        expect(hints[0]).not.toHaveProperty('nodes');
        expect(hints[0]).not.toHaveProperty('edges');
        expect(hints[0]).not.toHaveProperty('relationships');
        expect(snapshot.nodes).toHaveLength(0);
        expect(snapshot.edges).toHaveLength(0);
        expect(snapshot.relationships).toHaveLength(0);
    });
});

function adjudication(decision: NliClaimDecisionKind, overrides: Record<string, unknown> = {}) {
    return {
        claimId: `claim-${decision}`,
        evidenceId: `evidence-${decision}`,
        sourceId: 'entity-kai',
        targetId: 'entity-hazel',
        edgeType: 'supports',
        nliVote: {
            source: 'modernBertNli',
            role: 'canonFactAdjudication',
            decision,
            confidenceMillis: confidenceMillis(decision),
            entailmentMillis: decision === 'supported' ? confidenceMillis(decision) : 60,
            contradictionMillis: decision === 'contradicted' ? confidenceMillis(decision) : 40,
            neutralMillis: decision === 'unknown' ? confidenceMillis(decision) : 50,
        },
        classificationVote: gliclassVote('review.route', 600),
        ...overrides,
    };
}

function gliclassVote(label: string, scoreMillis: number) {
    return {
        source: 'gliclass',
        role: 'relationFrameClassification',
        label,
        scoreMillis,
    };
}

function confidenceMillis(decision: NliClaimDecisionKind): number {
    if (decision === 'supported') return 910;
    if (decision === 'contradicted') return 880;
    return 510;
}

function entity(id: string, label: string): RegisteredEntity {
    return {
        id,
        label,
        aliases: [],
        kind: 'CHARACTER',
        firstNote: 'note-1',
        noteId: 'note-1',
        mentionsByNote: new Map(),
        totalMentions: 0,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'test',
        attributes: {},
        registeredAt: 1,
    };
}
