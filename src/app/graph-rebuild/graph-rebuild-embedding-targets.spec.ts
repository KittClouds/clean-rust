import { describe, expect, it } from 'vitest';

import type { GraphDocumentCompilerSummary, GraphDocumentHyperedge } from './graph-document-compiler-types';
import { buildGraphRebuildEmbeddingTargetPlan } from './graph-rebuild-embedding-targets';
import type {
    BuildGraphRebuildSnapshotInput,
    GraphRebuildEntityAnchor,
    GraphRebuildNode,
} from './graph-rebuild-snapshot';

describe('graph rebuild hypergraph embedding targets', () => {
    it('admits native-eligible situations with their n-ary role endpoints', () => {
        const valid = hyperedge('valid');
        const conflicted = {
            ...hyperedge('conflicted'),
            temporalConflictIds: ['temporal-conflict:1'],
        };
        const missingFrame = {
            ...hyperedge('missing-frame'),
            frame: undefined,
        };
        const plan = buildGraphRebuildEmbeddingTargetPlan(
            input(),
            [],
            [anchor('entity-kai', 'Kai', 0, 3), anchor('entity-hazel', 'Hazel', 9, 14)],
            [entityNode('entity-kai'), entityNode('entity-hazel')],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            { hyperedges: [valid, conflicted, missingFrame] } as GraphDocumentCompilerSummary,
        );

        const ids = new Set(plan.targets.map((target) => target.id));
        const situation = plan.targets.find((target) => target.id === 'embed:fact:document-hyperedge:valid');
        const roleTargets = plan.targets.filter((target) => target.id.startsWith('embed:atom:'));

        expect(ids.has('embed:fact:document-hyperedge:conflicted')).toBe(false);
        expect(ids.has('embed:fact:document-hyperedge:missing-frame')).toBe(false);
        expect(situation).toMatchObject({
            sourceId: 'fact:document-hyperedge:valid',
            lane: 'relationship_fact',
            admissionStatus: 'admitted',
            workStatus: 'queued',
        });
        expect(situation?.parentIds).toEqual(expect.arrayContaining([
            'embed:entity:entity-kai',
            'embed:entity:entity-hazel',
            'embed:atom:documentMention:key',
            'embed:atom:documentEvidence:evidence-1',
            'embed:atom:documentUnit:unit-1',
        ]));
        expect(roleTargets).toEqual(expect.arrayContaining([
            expect.objectContaining({ id: 'embed:atom:documentMention:key', kind: 'concept', lane: 'entity_linker', admissionStatus: 'admitted' }),
            expect.objectContaining({ id: 'embed:atom:documentEvidence:evidence-1', kind: 'evidenceSpan', lane: 'anchor_evidence', admissionStatus: 'admitted' }),
            expect.objectContaining({ id: 'embed:atom:documentUnit:unit-1', kind: 'documentUnit', lane: 'chunk_spine', admissionStatus: 'admitted' }),
        ]));
    });

    it('keeps native-eligible situation targets shadow-only when source rows are hollow', () => {
        const plan = buildGraphRebuildEmbeddingTargetPlan(
            input(),
            [],
            [],
            [entityNode('entity-kai'), entityNode('entity-hazel')],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            { hyperedges: [hyperedge('hollow')] } as GraphDocumentCompilerSummary,
        );

        expect(plan.targets.some((target) => target.id === 'embed:fact:document-hyperedge:hollow')).toBe(false);
        expect(plan.targets.some((target) => target.id.startsWith('embed:atom:'))).toBe(false);
    });
});

function input(): BuildGraphRebuildSnapshotInput {
    return {
        scopeKind: 'note',
        scopeId: 'note-1',
        noteIds: ['note-1'],
        entities: [],
        occurrences: [],
        noteTexts: { 'note-1': 'Kai gave Hazel the key beside the archive.' },
        builtAt: 1,
    };
}

function entityNode(id: string): GraphRebuildNode {
    return {
        id,
        entityId: id,
        label: id === 'entity-kai' ? 'Kai' : 'Hazel',
        aliases: [],
        kind: 'CHARACTER',
        anchorIds: [`anchor:${id}`],
        noteIds: ['note-1'],
        totalMentions: 1,
    };
}

function anchor(entityId: string, surface: string, sourceStart: number, sourceEnd: number): GraphRebuildEntityAnchor {
    return {
        id: `anchor:${entityId}`,
        noteId: 'note-1',
        chunkId: 'note-1:chunk:0',
        entityId,
        surface,
        sourceStart,
        sourceEnd,
        source: 'dynamic-ner',
        confidence: 0.94,
        status: 'accepted',
        generation: 1,
    };
}

function hyperedge(id: string): GraphDocumentHyperedge {
    return {
        id,
        predicate: 'give',
        triggerPredicate: 'gave',
        frame: 'transfer_possession',
        frameFamily: 'transfer',
        situationKind: 'event',
        factuality: 'asserted',
        speechAct: 'assertion',
        worldStateEligible: true,
        semanticSituationId: `semantic-situation:${id}`,
        compilationBasis: 'semantic_situation_frame',
        sourceKind: 'relation_bundle',
        roles: [
            { id: `${id}:actor`, role: 'subject', semanticRole: 'actor', targetId: 'entity-kai', targetKind: 'entity', surface: 'Kai', confidence: 0.94, resolved: true },
            { id: `${id}:recipient`, role: 'recipient', semanticRole: 'recipient', targetId: 'entity-hazel', targetKind: 'entity', surface: 'Hazel', confidence: 0.91, resolved: true },
            { id: `${id}:theme`, role: 'object', semanticRole: 'theme', targetId: 'key', targetKind: 'entity_mention', surface: 'the key', confidence: 0.78, resolved: false },
            { id: `${id}:evidence`, role: 'evidence', semanticRole: 'evidence', targetId: 'evidence-1', targetKind: 'evidence_span', confidence: 0.9, resolved: true },
            { id: `${id}:context`, role: 'context', semanticRole: 'location', targetId: 'unit-1', targetKind: 'document_unit', surface: 'the archive', confidence: 0.72, resolved: true },
        ],
        evidenceSpanIds: ['evidence-1'],
        confidence: 0.92,
        status: 'pending_commit',
        nary: true,
        temporalConflictIds: [],
        provenance: {
            sourceObjectId: 'fact-1',
            sourceObjectKind: 'relation_bundle',
            reviewState: 'accepted',
            noteId: 'note-1',
            sourceStart: 0,
            sourceEnd: 43,
            evidenceSpanIds: ['evidence-1'],
            lineageUnitIds: ['unit-1'],
            reasons: ['test'],
        },
    };
}
