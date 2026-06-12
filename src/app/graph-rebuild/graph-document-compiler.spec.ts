import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import {
    applyGraphDocumentReviewAction,
    buildGraphDocumentReviewSummary,
} from './graph-document-review';
import { buildGraphDocumentCompilerSummary } from './graph-document-compiler';
import { buildCompatibilityGraphCompilerSidecar } from './graph-compiler-compat';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('graph document compiler', () => {
    it('compiles reviewed facts into reversible pending topology diffs', () => {
        const sidecar = sidecarFixture();
        const review = buildGraphDocumentReviewSummary(sidecar, 20);
        const fact = requireFactRow(review);
        const compiledReview = applyGraphDocumentReviewAction(review, {
            rowId: fact.id,
            actionKind: 'compile_to_graph',
            createdAt: 21,
        });
        const summary = buildGraphDocumentCompilerSummary({
            sidecar,
            review: compiledReview,
            builtAt: 22,
            baseline: { atomCount: 3, factCount: 2, edgeCount: 1 },
        });
        const diff = summary.topologyDiffs.find((row) => row.status === 'pending_commit');
        const receipt = summary.receipts.find((row) => row.topologyDiffId === diff?.id);
        const hyperedge = summary.hyperedges.find((row) => row.id === diff?.outputId);

        expect(summary.schemaVersion).toBe('phoenix-document-compiler/v1');
        expect(diff).toMatchObject({
            outputKind: 'hyperedge',
            mutationAllowed: true,
            topologyCommit: true,
            beforeGraph: { atomCount: 3, factCount: 2, edgeCount: 1 },
        });
        expect(diff?.afterGraph.factCount).toBeGreaterThan(diff?.beforeGraph.factCount || 0);
        expect(receipt).toMatchObject({
            reversible: true,
            mutationAllowed: true,
            invariant: 'document_compiler_reversible_topology_commit',
            undoPatch: {
                operation: 'remove_document_compiler_outputs',
                restoreReviewState: 'compiled_to_graph',
            },
        });
        expect(hyperedge?.nary).toBe(true);
        expect(hyperedge?.roles.length).toBeGreaterThan(2);
        expect(hyperedge?.provenance.sourceReviewRowId).toBe(fact.id);
        expect(summary.counters.reviewedFacts).toBe(1);
        expect(summary.counters.topologyCommits).toBe(1);
    });

    it('keeps ambiguous machine facts reviewable and visible without mutating topology', () => {
        const sidecar = sidecarFixture();
        const review = buildGraphDocumentReviewSummary(sidecar, 30);
        const summary = buildGraphDocumentCompilerSummary({
            sidecar,
            review,
            builtAt: 31,
            baseline: { atomCount: 1, factCount: 1, edgeCount: 1 },
        });
        const reviewable = summary.topologyDiffs.find((row) => row.status === 'reviewable');
        const receipt = summary.receipts.find((row) => row.topologyDiffId === reviewable?.id);

        expect(reviewable).toBeTruthy();
        expect(reviewable?.mutationAllowed).toBe(false);
        expect(reviewable?.beforeGraph).toEqual(reviewable?.afterGraph);
        expect(receipt).toMatchObject({
            reversible: true,
            mutationAllowed: false,
            invariant: 'document_compiler_ledger_only_no_topology_commit',
            undoPatch: { operation: 'remove_document_compiler_ledger_row' },
        });
        expect(summary.counters.ambiguousFacts).toBeGreaterThan(0);
        expect(summary.counters.topologyCommits).toBe(0);
    });

    it('allows high-confidence facts to compile while bounding disposable sidecar overlays', () => {
        const sidecar = highConfidenceSidecar(sidecarFixture());
        const review = buildGraphDocumentReviewSummary(sidecar, 40);
        const summary = buildGraphDocumentCompilerSummary({ sidecar, review, builtAt: 41 });

        expect(summary.counters.highConfidenceFacts).toBe(1);
        expect(summary.counters.topologyCommits).toBe(1);
        expect(summary.counters.hyperedges).toBeLessThanOrEqual(Math.min(sidecar.graphFactCandidates.length, 96));
        expect(summary.counters.documentStructureEdges).toBeLessThanOrEqual(512);
        expect(summary.counters.retrievalOverlays).toBeLessThanOrEqual(256);
        expect(summary.entityMentions.every((row) => row.anchorPolicy === 'mention_only_not_user_anchor')).toBe(true);
    });

    it('projects pending document hyperedges into the graph compiler read model', () => {
        const sidecar = highConfidenceSidecar(sidecarFixture());
        const review = buildGraphDocumentReviewSummary(sidecar, 45);
        const summary = buildGraphDocumentCompilerSummary({ sidecar, review, builtAt: 46 });
        const sidecarOutput = buildCompatibilityGraphCompilerSidecar(snapshotWithCompiler(sidecar, summary));
        const documentFact = sidecarOutput.factGraph.facts.find((fact) => fact.id.startsWith('fact:document-hyperedge:'));
        const roleCount = sidecarOutput.factGraph.roles.filter((role) => role.factId === documentFact?.id).length;

        expect(documentFact).toMatchObject({
            lane: 'relationshipFact',
            status: 'accepted',
        });
        expect(roleCount).toBeGreaterThan(2);
        expect(sidecarOutput.factGraph.receipts.counters.facts).toBeGreaterThan(0);
        expect(sidecarOutput.factGraph.evidenceAnchors.some((evidence) => evidence.id.startsWith('evidence:document:'))).toBe(true);
    });

    it('threads compiler counters through graph rebuild snapshots', () => {
        const text = fixtureText();
        const chunks = buildAdaptiveGraphRebuildChunks('compiler-snapshot', text);
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:compiler-snapshot',
            noteIds: ['compiler-snapshot'],
            entities: [],
            occurrences: [],
            chunks,
            noteTexts: { 'compiler-snapshot': text },
            builtAt: 50,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });

        expect(snapshot.documentCompilerSummary?.schemaVersion).toBe('phoenix-document-compiler/v1');
        expect(snapshot.counters.documentCompilerHyperedges).toBe(snapshot.documentCompilerSummary?.counters.hyperedges);
        expect(snapshot.counters.documentCompilerTopologyDiffs).toBe(snapshot.documentCompilerSummary?.counters.topologyDiffs);
        expect(snapshot.counters.documentCompilerReceipts).toBe(snapshot.documentCompilerSummary?.counters.receipts);
        expect(snapshot.counters.documentCompilerMutationAllowed).toBe(snapshot.documentCompilerSummary?.counters.mutationAllowed);
    });
});

function requireFactRow(review: ReturnType<typeof buildGraphDocumentReviewSummary>) {
    const row = review.rows.find((candidate) => candidate.objectKind === 'graph_fact_candidate');
    expect(row).toBeTruthy();
    return row!;
}

function highConfidenceSidecar(sidecar: ReturnType<typeof buildGraphDocumentSidecar>) {
    const firstFact = sidecar.graphFactCandidates[0];
    expect(firstFact).toBeTruthy();
    const upgraded = {
        ...firstFact!,
        confidence: { ...firstFact!.confidence, score: 0.93, reasons: [...firstFact!.confidence.reasons, 'test_high_confidence'] },
    };
    return {
        ...sidecar,
        graphFactCandidates: [upgraded, ...sidecar.graphFactCandidates.slice(1)],
    };
}

function snapshotWithCompiler(
    sidecar: ReturnType<typeof buildGraphDocumentSidecar>,
    documentCompilerSummary: ReturnType<typeof buildGraphDocumentCompilerSummary>,
): GraphRebuildSnapshot {
    return {
        id: 'compiler-read-model-snapshot',
        schemaVersion: 'phoenix-graph-rebuild/v1',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'note',
        scopeId: 'compiler-read-model',
        noteIds: sidecar.noteIds,
        builtAt: documentCompilerSummary.builtAt,
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
        documentSidecarSummary: sidecar,
        documentCompilerSummary,
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

function sidecarFixture() {
    const text = fixtureText();
    return buildGraphDocumentSidecar({
        noteIds: ['compiler-note'],
        noteTexts: { 'compiler-note': text },
        chunks: buildAdaptiveGraphRebuildChunks('compiler-note', text),
        builtAt: 19,
    });
}

function fixtureText(): string {
    return [
        '# Compiler Note',
        'Policy means Amara moved from Red Mesa to Halcyon because Captain Ilya changed the archive route.',
        'Therefore Morgan shows the evidence to Kai and Hazel before the council decision.',
        '- Use the recovered record as evidence.',
        '"Should this become an anchor?" Amara asked.',
    ].join('\n\n');
}
