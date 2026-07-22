import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import {
    applyGraphDocumentReviewAction,
    buildGraphDocumentReviewSummary,
    type GraphDocumentReviewActionKind,
} from './graph-document-review';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';

describe('graph document review model', () => {
    it('assigns explicit states and actions to machine-produced sidecar objects', () => {
        const sidecar = sidecarFixture();
        const review = buildGraphDocumentReviewSummary(sidecar, 20);

        expect(review.schemaVersion).toBe('phoenix-document-review/v1');
        expect(review.statePolicy).toBe('machine_objects_are_explicitly_review_stateful');
        expect(review.topologyPolicy).toBe('review_actions_emit_receipts_before_graph_mutation');
        expect(review.counters.stateRecords).toBe(review.rows.length);
        expect(review.states.every((state) => state.source === 'machine_sidecar')).toBe(true);
        expect(review.counters.proposedRows).toBeGreaterThan(0);
        expect(review.counters.ledgerOnlyRows).toBeGreaterThan(0);
        expect(review.rows.every((row) => row.availableActions.some((action) => action.kind === 'jump_to_source_span'))).toBe(true);
        expect(review.rows.some((row) =>
            row.objectKind === 'graph_fact_candidate'
            && row.availableActions.some((action) => action.kind === 'accept_fact')
            && row.availableActions.some((action) => action.kind === 'compile_to_graph')
        )).toBe(true);
        expect(review.rows.some((row) =>
            row.objectKind === 'document_region'
            && row.availableActions.some((action) => action.kind === 'promote_sidecar_to_anchor')
        )).toBe(true);
    });

    it('emits reversible no-topology receipts for review actions', () => {
        const review = buildGraphDocumentReviewSummary(sidecarFixture(), 21);
        const fact = requireRow(review, 'graph_fact_candidate');
        const accepted = applyGraphDocumentReviewAction(review, {
            rowId: fact.id,
            actionKind: 'accept_fact',
            createdAt: 22,
        });
        const receipt = accepted.receipts[0];

        expect(receipt).toMatchObject({
            actionKind: 'accept_fact',
            previousState: 'proposed',
            nextState: 'accepted',
            reversible: true,
            mutationAllowed: false,
            invariant: 'document_review_no_topology_commit',
            undoState: 'proposed',
        });
        expect(accepted.rows.find((row) => row.id === fact.id)?.state).toBe('accepted');
        expect(accepted.counters.acceptedRows).toBe(1);
        expect(accepted.counters.reversibleReceipts).toBe(1);
    });

    it('supports all requested review state transitions without mutating topology', () => {
        const base = buildGraphDocumentReviewSummary(sidecarFixture(), 23);
        const fact = requireRow(base, 'graph_fact_candidate');
        const region = requireRow(base, 'document_region');
        const actions: Array<[GraphDocumentReviewActionKind, string, string]> = [
            ['reject_fact', fact.id, 'rejected'],
            ['demote_graph_fact_to_sidecar', fact.id, 'ledger_only'],
            ['compile_to_graph', fact.id, 'compiled_to_graph'],
            ['promote_sidecar_to_anchor', region.id, 'promoted_to_anchor'],
            ['mute_detector_pattern', region.id, 'muted'],
        ];

        for (const [actionKind, rowId, nextState] of actions) {
            const updated = applyGraphDocumentReviewAction(base, { rowId, actionKind, createdAt: 24 });
            expect(updated.rows.find((row) => row.id === rowId)?.state).toBe(nextState);
            expect(updated.receipts[0]).toMatchObject({
                actionKind,
                nextState,
                reversible: true,
                mutationAllowed: false,
            });
        }
    });

    it('threads review counters through graph rebuild snapshots', () => {
        const text = fixtureText();
        const chunks = buildAdaptiveGraphRebuildChunks('review-snapshot', text);
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:review-snapshot',
            noteIds: ['review-snapshot'],
            entities: [],
            occurrences: [],
            chunks,
            noteTexts: { 'review-snapshot': text },
            builtAt: 25,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });

        expect(snapshot.documentReviewSummary?.schemaVersion).toBe('phoenix-document-review/v1');
        expect(snapshot.counters.documentReviewRows).toBe(snapshot.documentReviewSummary?.counters.rows);
        expect(snapshot.counters.documentReviewStateRecords).toBe(snapshot.documentReviewSummary?.counters.stateRecords);
        expect(snapshot.counters.documentReviewActionableRows).toBeGreaterThan(0);
        expect(snapshot.counters.documentReviewProposedRows).toBeGreaterThan(0);
    });
});

function requireRow(
    review: ReturnType<typeof buildGraphDocumentReviewSummary>,
    objectKind: string,
) {
    const row = review.rows.find((candidate) => candidate.objectKind === objectKind && candidate.state === 'proposed');
    expect(row).toBeTruthy();
    return row!;
}

function sidecarFixture() {
    const text = fixtureText();
    return buildGraphDocumentSidecar({
        noteIds: ['review-note'],
        noteTexts: { 'review-note': text },
        chunks: buildAdaptiveGraphRebuildChunks('review-note', text),
        builtAt: 19,
    });
}

function fixtureText(): string {
    return [
        '# Review Note',
        'Policy means Amara moved from Red Mesa to Halcyon because the report changed the plan.',
        '- Use the recovered record as evidence.',
        '"Should this become an anchor?" Amara asked.',
        '| Name | Value |\n| --- | --- |\n| latency | 2s |',
    ].join('\n\n');
}
