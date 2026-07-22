import { describe, expect, it } from 'vitest';

import { buildGraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { GraphDiscourseSpineSummary } from './graph-discourse-spine';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';

describe('Graph Discourse Bridge Candidates', () => {
    it('packages spine wormholes as GLiClass-shaped read-only candidates', () => {
        const one = 'Chapter four: Brynwyn refused the crown and remembered the oath. Hazel called Brynwyn Northstar.';
        const two = 'Chapter forty: The captain rejected the throne and kept the old promise. Hazel called Northstar back.';
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'multiNote',
            scopeId: 'multi:bridge-candidates',
            noteIds: ['chapter-04', 'chapter-40'],
            entities: [
                entity('e-brynwyn', 'Brynwyn', ['The captain', 'Northstar']),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'chapter-04:chunk:0', noteId: 'chapter-04', start: 0, end: one.length, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'chapter-40:chunk:0', noteId: 'chapter-40', start: 0, end: two.length, ordinal: 40, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('chapter-04', 'e-brynwyn', 'Brynwyn', one.indexOf('Brynwyn'), 'chapter-04:chunk:0'),
                occurrence('chapter-04', 'e-hazel', 'Hazel', one.indexOf('Hazel'), 'chapter-04:chunk:0'),
                occurrence('chapter-40', 'e-brynwyn', 'The captain', two.indexOf('The captain'), 'chapter-40:chunk:0'),
                occurrence('chapter-40', 'e-brynwyn', 'Northstar', two.indexOf('Northstar'), 'chapter-40:chunk:0'),
                occurrence('chapter-40', 'e-hazel', 'Hazel', two.indexOf('Hazel'), 'chapter-40:chunk:0'),
            ],
            noteTexts: { 'chapter-04': one, 'chapter-40': two },
            builtAt: 55,
        });
        const summary = snapshot.discourseBridgeCandidateSummary!;

        expect(summary.schemaVersion).toBe('phoenix-discourse-bridge-candidates/v1');
        expect(summary.modelId).toBe('knowledgator/gliclass-instruct-base-v1.0');
        expect(summary.runner).toBe('gliclass-query-label-rerank');
        expect(summary.scoreSource).toBe('deterministic_calibration');
        expect(summary.invariant).toBe('discourse_bridges_are_candidates_not_edges');
        expect(summary.candidates.length).toBeGreaterThan(0);
        expect(summary.inputs).toHaveLength(summary.candidates.length);
        expect(summary.judgments).toHaveLength(summary.candidates.length);
        expect(summary.evalRows).toHaveLength(summary.candidates.length);
        expect(summary.inputs.every((input) =>
            input.queryLabels.length >= 3
            && input.passage.length <= input.maxPassageChars
            && input.passage.includes('candidate_kind:'),
        )).toBe(true);
        expect(summary.receipts.every((receipt) =>
            receipt.reversible
            && receipt.mutationAllowed === false
            && receipt.invariant === 'discourse_bridge_candidates_no_topology_commit',
        )).toBe(true);
        expect(summary.counters.mutationAllowedCount).toBe(0);
        expect(summary.counters.plannedModelCalls).toBeGreaterThan(summary.counters.inputCount);
        expect(summary.compactEvalLedger.rowCount).toBe(summary.evalRows.length);

        const semanticIds = new Set((snapshot.semanticCandidateSummary?.candidates || []).map((row) => row.id));
        expect(summary.candidates.every((candidate) => !semanticIds.has(candidate.id))).toBe(true);
        const edgeIds = new Set(snapshot.edges.map((edge) => edge.id));
        expect(summary.candidates.every((candidate) => !edgeIds.has(candidate.id))).toBe(true);
    });

    it('keeps entity-only overlap as eval material instead of graph truth', () => {
        const snapshot = {
            id: 'snapshot:entity-only',
            scopeId: 'scope:entity-only',
            builtAt: 77,
            embeddingTargets: [
                target('embed:chunk:a', 'Chunk A', 'Kai appears in a logistics note.', 'note-a', 'chunk-a'),
                target('embed:chunk:b', 'Chunk B', 'Kai appears in a weather report.', 'note-b', 'chunk-b'),
            ],
        } as any;
        const summary = buildGraphDiscourseBridgeCandidateSummary(snapshot, fakeEntityOnlySpine(), 77);

        expect(summary.candidates).toHaveLength(1);
        expect(summary.candidates[0]).toEqual(expect.objectContaining({
            kind: 'cross_doc_resolution',
            mutationAllowed: false,
            sharedEntityIds: ['e-kai'],
        }));
        expect(summary.evalRows[0]).toEqual(expect.objectContaining({
            kind: 'entity_overlap_without_meaning',
            expectedLabelKind: 'entity_only_overlap',
        }));
        expect(summary.judgments[0].topLabelKind).toBe('entity_only_overlap');
        expect(summary.counters.entityOverlapWithoutMeaning).toBe(1);
        expect(summary.counters.mutationAllowedCount).toBe(0);
    });
});

function fakeEntityOnlySpine(): GraphDiscourseSpineSummary {
    return {
        schemaVersion: 'phoenix-discourse-spine/v1',
        generatedAt: 77,
        sourceSnapshotId: 'snapshot:entity-only',
        implementationMode: 'deterministic_registry',
        invariant: 'wormholes_are_proposals_not_edges',
        targets: [],
        labels: [],
        clusters: [],
        bridges: [{
            id: 'bridge:entity-only',
            kind: 'resolution',
            status: 'proposed',
            sourceTargetId: 'embed:chunk:a',
            targetTargetId: 'embed:chunk:b',
            sourceKind: 'chunk',
            targetKind: 'chunk',
            label: 'Chunk A may resolve across Chunk B',
            evidenceTargetIds: ['embed:chunk:a', 'embed:chunk:b'],
            sharedLabelIds: [],
            sharedEntityIds: ['e-kai'],
            scoringBundle: {
                semanticScore: 0.12,
                labelAgreement: 0.05,
                entityOverlap: 0.82,
                distanceScore: 1,
                corefPressure: 0.84,
                finalScore: 0.55,
                scoreParts: [],
            },
            rationale: ['entity overlap without meaning should stay evaluable'],
            adjudicationState: 'proposed',
            mutationAllowed: false,
            receiptId: 'receipt:bridge:entity-only',
            createdAt: 77,
        }],
        receipts: [],
        compactBridgeLedger: { scopeId: 'scope:entity-only', builtAt: 77, rowCount: 1, rows: [] },
        counters: {} as any,
    };
}

function target(id: string, label: string, text: string, noteId: string, chunkId: string) {
    return { id, kind: 'chunk', sourceId: chunkId, noteId, chunkId, label, text, evidenceIds: [] };
}

function entity(id: string, label: string, aliases: string[]): RegisteredEntity {
    return {
        id,
        label,
        kind: 'CHARACTER' as any,
        aliases,
        firstNote: `${id}-note`,
        mentionsByNote: new Map(),
        totalMentions: 0,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
    };
}

function occurrence(
    noteId: string,
    entityId: string,
    surface: string,
    sourceStart: number,
    chunkId: string,
): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}:${sourceStart}:${surface}`,
        noteId,
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd: sourceStart + surface.length,
        surface,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: surface,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
        chunkId,
    };
}
