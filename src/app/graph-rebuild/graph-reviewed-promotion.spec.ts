import { describe, expect, it } from 'vitest';

import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { GraphPromotionVerdictCertificate, GraphPromotionVerdictRow } from './graph-promotion-verdict';
import {
    authorizeReviewedGraphPromotion,
    recordGraphPromotionReview,
    type GraphPromotionReviewReceipt,
} from './graph-reviewed-promotion';

describe('explicit reviewed graph promotion authority', () => {
    it('authorizes only an explicitly approved, evidence-backed native commit', () => {
        const snapshot = fixture();
        const row = attachVerdict(snapshot);
        const review = recordGraphPromotionReview(snapshot, row.id, {
            reviewerId: 'operator:shuga',
            decision: 'approve',
            rationale: 'The cited source directly supports this relationship.',
            reviewedAt: 50,
            explicitUserIntent: true,
        });

        const authorization = authorizeReviewedGraphPromotion(snapshot, review);

        expect(review).toMatchObject({
            reviewerKind: 'human',
            explicitUserIntent: true,
            automated: false,
            mutationAllowed: false,
        });
        expect(authorization).toMatchObject({
            operation: 'assert',
            mutationAllowed: true,
            nativeCommitRequired: true,
            snapshotMutationAllowed: false,
            reviewReceiptId: review.id,
            evidenceRefs: [snapshot.chunks[0].id],
            nativeIdempotency: {
                algorithm: 'blake3',
                domain: 'phoenix-reviewed-promotion-commit/v1',
            },
            rollback: {
                operation: 'revert',
                availableAfterCommit: true,
                nativeCommitIdRequired: true,
            },
        });
        expect(authorization.receiptIds).toEqual([row.receiptId, row.id, review.id]);
    });

    it('does not treat an acceptable model verdict as explicit review', () => {
        const snapshot = fixture();
        const row = attachVerdict(snapshot);

        expect(() => authorizeReviewedGraphPromotion(snapshot, {
            verdictRowId: row.id,
        } as GraphPromotionReviewReceipt)).toThrow(/review receipt is stale or invalid/i);
    });

    it('rejects a human rejection receipt', () => {
        const snapshot = fixture();
        const row = attachVerdict(snapshot);
        const review = recordGraphPromotionReview(snapshot, row.id, {
            reviewerId: 'operator:shuga',
            decision: 'reject',
            rationale: 'The evidence does not support this claim.',
            reviewedAt: 50,
            explicitUserIntent: true,
        });

        expect(() => authorizeReviewedGraphPromotion(snapshot, review)).toThrow(/approval/i);
    });

    it('rejects review construction without an explicit user event', () => {
        const snapshot = fixture();
        const row = attachVerdict(snapshot);

        expect(() => recordGraphPromotionReview(snapshot, row.id, {
            reviewerId: 'operator:shuga',
            decision: 'approve',
            rationale: 'Automated caller attempted to reuse review.',
            reviewedAt: 50,
            explicitUserIntent: false,
        } as any)).toThrow(/explicit user intent/i);
    });

    it('rejects stale review receipts after candidate evidence changes', () => {
        const snapshot = fixture();
        const row = attachVerdict(snapshot);
        const review = recordGraphPromotionReview(snapshot, row.id, {
            reviewerId: 'operator:shuga',
            decision: 'approve',
            rationale: 'Evidence reviewed.',
            reviewedAt: 50,
            explicitUserIntent: true,
        });
        row.evidenceRefs = [...row.evidenceRefs, 'evidence:changed'];

        expect(() => authorizeReviewedGraphPromotion(snapshot, review)).toThrow(/source fingerprint|candidate fingerprint/i);
    });

    it('rejects evidence labels that do not resolve to authoritative rows', () => {
        const snapshot = fixture();
        const row = attachVerdict(snapshot, { evidenceRefs: ['model:confidence:0.99'] });
        const review = recordGraphPromotionReview(snapshot, row.id, {
            reviewerId: 'operator:shuga',
            decision: 'approve',
            rationale: 'Attempted approval.',
            reviewedAt: 50,
            explicitUserIntent: true,
        });

        expect(() => authorizeReviewedGraphPromotion(snapshot, review)).toThrow(/does not resolve/i);
    });

    it('rejects blocked native gates and missing asserted endpoints', () => {
        const blockedSnapshot = fixture();
        const blocked = attachVerdict(blockedSnapshot, {
            gates: [
                gate('receipt', 'pass'),
                gate('evidence', 'pass'),
                gate('contradiction', 'block'),
            ],
        });
        const blockedReview = approve(blockedSnapshot, blocked.id);
        expect(() => authorizeReviewedGraphPromotion(blockedSnapshot, blockedReview)).toThrow(/blocked gates/i);

        const orphanSnapshot = fixture();
        const orphan = attachVerdict(orphanSnapshot, {
            atom: {
                kind: 'edge',
                source_id: 'e-kai',
                target_id: 'entity:missing',
                edge_type: 'semantic::guards',
            },
        });
        const orphanReview = approve(orphanSnapshot, orphan.id);
        expect(() => authorizeReviewedGraphPromotion(orphanSnapshot, orphanReview)).toThrow(/not asserted identities/i);
    });
});

function approve(snapshot: ReturnType<typeof fixture>, verdictRowId: string) {
    return recordGraphPromotionReview(snapshot, verdictRowId, {
        reviewerId: 'operator:shuga',
        decision: 'approve',
        rationale: 'Evidence reviewed.',
        reviewedAt: 50,
        explicitUserIntent: true,
    });
}

function attachVerdict(
    snapshot: ReturnType<typeof fixture>,
    overrides: Partial<GraphPromotionVerdictRow> = {},
): GraphPromotionVerdictRow {
    const row: GraphPromotionVerdictRow = {
        id: 'promotion-verdict:receipt-1:proposal-1',
        receiptId: 'receipt-1',
        proposalId: 'proposal-1',
        atom: {
            kind: 'edge',
            source_id: 'e-kai',
            target_id: 'e-rift',
            edge_type: 'semantic::guards',
        },
        family: 'semantic_relationship',
        truth: { kind: 'semantic', plane: 'worldState' },
        candidateStatus: 'generated',
        outcome: 'candidate',
        status: 'acceptable',
        evidenceRefs: [snapshot.chunks[0].id],
        witnessCount: 1,
        applyPlan: { operation: 'assert', rationale: 'new durable truth atom' },
        rollbackPlan: {
            operation: 'revert',
            availableNow: false,
            availableAfterCommit: true,
            rationale: 'revert after commit',
        },
        gates: [gate('receipt', 'pass'), gate('evidence', 'pass')],
        rationale: 'native gates passed',
        ...overrides,
    };
    const certificate: GraphPromotionVerdictCertificate = {
        schemaVersion: 'phoenix-graph-promotion-verdict/v1',
        source: 'rust-deterministic-promotion-verdict',
        noTopologyWrites: true,
        receiptCount: 1,
        commitCount: 0,
        audit: {
            total: 1,
            acceptable: 1,
            alreadyCommitted: 0,
            blocked: 0,
            deferred: 0,
            rejected: 0,
            rollbackAvailable: 0,
            evidenceBlocked: 0,
            contradictionBlocked: 0,
            nliBlocked: 0,
            userOverrides: 0,
        },
        rows: [row],
    };
    snapshot.promotionVerdictCertificate = certificate;
    return row;
}

function gate(kind: any, status: any) {
    return { kind, status, summary: `${kind} ${status}` };
}

function fixture() {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:reviewed-promotion',
        noteIds: ['note-1'],
        entities: [entity('e-kai', 'Kai'), entity('e-rift', 'Rift')],
        chunks: [{
            id: 'note-1:block:0',
            noteId: 'note-1',
            start: 0,
            end: 68,
            ordinal: 0,
            source: 'note-block',
        }],
        occurrences: [
            occurrence('e-kai', 'Kai', 0, 3),
            occurrence('e-rift', 'Rift', 16, 20),
        ],
        noteTexts: { 'note-1': 'Kai guards Rift at the threshold while the storm crosses the valley.' },
        builtAt: 40,
    });
}

function entity(id: string, label: string): RegisteredEntity {
    return {
        id,
        label,
        kind: 'CHARACTER',
        aliases: [],
        firstNote: 'note-1',
        mentionsByNote: new Map(),
        totalMentions: 1,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
    };
}

function occurrence(entityId: string, surface: string, sourceStart: number, sourceEnd: number): EntityOccurrence {
    return {
        id: `note-1:${entityId}`,
        noteId: 'note-1',
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd,
        surface,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: surface,
        chunkId: 'note-1:block:0',
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}
