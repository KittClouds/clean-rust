import { describe, expect, it } from 'vitest';

import { buildGraphDocumentCompilerSummary } from './graph-document-compiler';
import {
    buildGraphDocumentDurableCommitRequests,
    emptyGraphDocumentGraphMutationLedger,
    planGraphDocumentMutationReconciliation,
    recordGraphDocumentCommit,
    recordGraphDocumentUndo,
} from './graph-document-durable-commit';
import {
    applyGraphDocumentReviewAction,
    buildGraphDocumentReviewSummary,
} from './graph-document-review';
import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';

describe('graph document durable commits', () => {
    it('materializes reviewed facts as n-ary fact, entity-role, and evidence records', () => {
        const { compiler, sidecar } = compiledFixture(true);
        const requests = buildGraphDocumentDurableCommitRequests({
            scopeId: 'note:durable',
            compiler,
            sidecar,
        });

        expect(requests).toHaveLength(1);
        const request = requests[0];
        expect(request.vertices.some((row) => row.kind === 'document_fact' && row.removeOnUndo)).toBe(true);
        expect(request.vertices.some((row) => row.kind === 'entity' && !row.removeOnUndo)).toBe(true);
        expect(request.vertices.some((row) => row.kind === 'evidence_span' && row.removeOnUndo)).toBe(true);
        expect(request.edges.some((row) => row.edgeType === 'document_fact_role')).toBe(true);
        expect(request.edges.some((row) => row.edgeType === 'supported_by_evidence_span')).toBe(true);
        expect(request.edges.every((row) => row.attributes['documentCompilerCommitId'] === request.commitId)).toBe(true);
    });

    it('does not manufacture topology for unresolved accepted surfaces', () => {
        const { compiler, sidecar } = compiledFixture(false);
        const requests = buildGraphDocumentDurableCommitRequests({
            scopeId: 'note:durable',
            compiler,
            sidecar,
        });

        expect(requests).toEqual([]);
        expect(compiler.topologyDiffs.some((row) => row.status === 'reviewable')).toBe(true);
    });

    it('plans idempotent commits and reversible undo from the ledger', () => {
        const { compiler, sidecar } = compiledFixture(true);
        const [request] = buildGraphDocumentDurableCommitRequests({
            scopeId: 'note:durable',
            compiler,
            sidecar,
        });
        const initial = planGraphDocumentMutationReconciliation([request], undefined, 100);
        expect(initial.commits).toEqual([request]);
        expect(initial.undos).toEqual([]);

        const committed = recordGraphDocumentCommit(emptyGraphDocumentGraphMutationLedger(), request, {
            commitId: request.commitId,
            createdVertexIds: request.vertices.filter((row) => row.removeOnUndo).map((row) => row.id),
            createdEdgeKeys: request.edges.map((row) => `${row.source}\u0000${row.target}`),
            idempotent: false,
        }, 101);
        expect(planGraphDocumentMutationReconciliation([request], committed, 102)).toEqual({ commits: [], undos: [] });

        const removal = planGraphDocumentMutationReconciliation([], committed, 103);
        expect(removal.undos).toEqual([{
            schemaVersion: 'phoenix-document-graph-undo/v1',
            commitId: request.commitId,
            undoneAt: 103,
        }]);
        const undone = recordGraphDocumentUndo(committed, removal.undos[0]);
        expect(undone.counters).toMatchObject({ active: 0, undone: 1, vertices: 0, edges: 0 });
    });
});

function compiledFixture(withEntities: boolean) {
    const text = [
        '# Durable Note',
        'Amara moved from Red Mesa to Halcyon because Captain Ilya changed the archive route.',
        'The recovered record is evidence for the council decision.',
    ].join('\n\n');
    const sidecar = buildGraphDocumentSidecar({
        noteIds: ['durable-note'],
        noteTexts: { 'durable-note': text },
        chunks: buildAdaptiveGraphRebuildChunks('durable-note', text),
        builtAt: 10,
    });
    const review = buildGraphDocumentReviewSummary(sidecar, 11);
    const fact = review.rows.find((row) => row.objectKind === 'graph_fact_candidate');
    expect(fact).toBeTruthy();
    const accepted = applyGraphDocumentReviewAction(review, {
        rowId: fact!.id,
        actionKind: 'compile_to_graph',
        createdAt: 12,
    });
    const compiler = buildGraphDocumentCompilerSummary({
        sidecar,
        review: accepted,
        entities: withEntities ? [
            { id: 'entity:amara', label: 'Amara' },
            { id: 'entity:red-mesa', label: 'Red Mesa' },
            { id: 'entity:halcyon', label: 'Halcyon' },
            { id: 'entity:captain-ilya', label: 'Captain Ilya' },
        ] : [],
        builtAt: 13,
    });
    return { compiler, sidecar };
}
