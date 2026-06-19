import { describe, expect, it } from 'vitest';

import {
    applyGraphOperatorMutationDecisionToSnapshot,
    graphOperatorMutationJournalFromTruthCommits,
    replayGraphOperatorMutationJournal,
} from './graph-operator-mutation-journal';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import type { GraphDocumentSemanticSummary } from './graph-document-semantic';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import type { GraphTruthCommitLike } from './graph-truth-commit-ledger';

describe('graph operator mutation journal', () => {
    it('replays operator review decisions onto a rebuilt snapshot', () => {
        const base = snapshotFixture(10);
        const factId = firstFactObjectId(base);
        const mutated = applyGraphOperatorMutationDecisionToSnapshot(base, [factId], 'accepted', 20);
        expect(mutated?.operatorMutationJournal?.counters).toMatchObject({
            intents: 1,
            applied: 1,
            receipts: 1,
        });
        expect(rowState(mutated!, factId)).toBe('accepted');

        const rebuilt = snapshotFixture(30, mutated!.operatorMutationJournal);
        expect(rowState(rebuilt, factId)).toBe('accepted');
        expect(rebuilt.documentReviewSummary?.receipts).toHaveLength(1);
        expect(rebuilt.operatorMutationJournal?.intents[0]).toMatchObject({
            targetObjectId: factId,
            requestedState: 'accepted',
            status: 'applied',
        });
    });

    it('marks stale operator decisions conflicted when the source row no longer matches', () => {
        const base = snapshotFixture(40);
        const factId = firstFactObjectId(base);
        const mutated = applyGraphOperatorMutationDecisionToSnapshot(base, [factId], 'accepted', 41);
        const stale = {
            ...snapshotFixture(42),
            documentReviewSummary: {
                ...snapshotFixture(42).documentReviewSummary!,
                rows: snapshotFixture(42).documentReviewSummary!.rows.map((row) =>
                    row.objectId === factId ? { ...row, detector: 'changed_detector' } : row,
                ),
            },
        };
        const replayed = replayGraphOperatorMutationJournal(stale, mutated!.operatorMutationJournal!, 43).snapshot;

        expect(rowState(replayed, factId)).toBe('proposed');
        expect(replayed.operatorMutationJournal?.counters).toMatchObject({
            intents: 1,
            conflicted: 1,
            receipts: 1,
        });
        expect(replayed.operatorMutationJournal?.intents[0].conflictReason).toBe('source_fingerprint_changed');
    });

    it('replays compile decisions before building manifold targets', () => {
        const base = semanticSnapshotFixture(50);
        const factId = firstFactObjectId(base);
        const compiled = applyGraphOperatorMutationDecisionToSnapshot(base, [factId], 'compiled_to_graph', 51);
        expect(compiled).toBeTruthy();

        const rebuilt = semanticSnapshotFixture(52, compiled!.operatorMutationJournal);
        const pendingFactIds = new Set(
            rebuilt.documentCompilerSummary?.hyperedges
                .filter((hyperedge) => hyperedge.status === 'pending_commit')
                .map((hyperedge) => `fact:document-hyperedge:${hyperedge.id}`),
        );
        const situationTargets = rebuilt.embeddingTargets.filter((target) => target.id.startsWith('embed:fact:document-hyperedge:'));

        expect(rowState(rebuilt, factId)).toBe('compiled_to_graph');
        expect(pendingFactIds.size).toBeGreaterThan(0);
        expect(situationTargets.length).toBe(pendingFactIds.size);
        expect(situationTargets.every((target) => pendingFactIds.has(target.sourceId))).toBe(true);
        expect(situationTargets.every((target) => target.lane === 'relationship_fact')).toBe(true);
    });

    it('projects operator read-model states from the canonical GraphTruthCommit ledger', () => {
        const journal = graphOperatorMutationJournalFromTruthCommits('scope-1', graphTruthFixtures(), 100);

        expect(journal.counters).toMatchObject({
            canonicalAccepted: 2,
            canonicalReverted: 2,
            canonicalSuperseded: 2,
        });
        expect(journal.intents.find((intent) => intent.targetObjectId === 'receipt-active')).toMatchObject({
            canonicalState: 'accepted',
            status: 'applied',
            requestedState: 'accepted',
        });
        expect(journal.intents.find((intent) => intent.targetObjectId === 'receipt-reverted')).toMatchObject({
            canonicalState: 'reverted',
            status: 'undone',
        });
        expect(journal.receipts.find((receipt) => receipt.targetObjectId === 'source-old')).toMatchObject({
            canonicalState: 'superseded',
            canonicalCommitId: 'commit-old',
        });
    });
});

function snapshotFixture(
    builtAt: number,
    operatorMutationJournal?: GraphRebuildSnapshot['operatorMutationJournal'],
): GraphRebuildSnapshot {
    const text = [
        '# Operator Journal Note',
        'Policy means Amara moved from Red Mesa to Halcyon because Captain Ilya changed the archive route.',
        'Therefore Morgan shows the evidence to Kai and Hazel before the council decision.',
    ].join('\n\n');
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'operator-journal-note',
        noteIds: ['operator-journal-note'],
        entities: [],
        occurrences: [],
        chunks: buildAdaptiveGraphRebuildChunks('operator-journal-note', text),
        noteTexts: { 'operator-journal-note': text },
        builtAt,
        postProcessMode: 'core',
        embeddingStagePolicy: { entityLinkerEnabled: false },
        operatorMutationJournal,
    });
}

function semanticSnapshotFixture(
    builtAt: number,
    operatorMutationJournal?: GraphRebuildSnapshot['operatorMutationJournal'],
): GraphRebuildSnapshot {
    const noteId = 'semantic-journal-note';
    const text = 'Kai gave Hazel the key.';
    const documentSemanticSummary = {
        schemaVersion: 'phoenix-document-semantics/v1',
        source: 'native_rust',
        documents: [{
            noteId,
            textChars: text.length,
            propositions: [{
                id: `${noteId}:prop:0`,
                noteId,
                sentenceIndex: 0,
                start: 0,
                end: text.length,
                preview: text,
                predicate: 'give',
                relationType: 'transfer',
                predicateQuality: 'finite_verb',
                predicateAdmission: 'review',
                qualityReasons: ['finite_subject_frame'],
                triggerStart: 4,
                triggerEnd: 8,
                frame: {
                    frame: 'transfer_possession',
                    family: 'transfer',
                    target: 'gave',
                    lexicalUnit: 'give.v',
                    definition: 'An actor transfers a theme to a recipient.',
                    source: 'lexical_table',
                    confidenceMillis: 920,
                    expectedRoles: ['actor', 'theme', 'recipient'],
                    matchedRoles: ['actor', 'theme', 'recipient'],
                    missingRoles: [],
                    reasons: ['lexical_unit_match'],
                    failureReasons: [],
                },
                factuality: {
                    factuality: 'asserted',
                    polarity: 'positive',
                    speechAct: 'assertion',
                    asserted: true,
                    negated: false,
                    modal: false,
                    hypothetical: false,
                    conditional: false,
                    quoted: false,
                    reported: false,
                    believed: false,
                    questioned: false,
                    commanded: false,
                    confidenceMillis: 950,
                    scopeKinds: ['assertion'],
                    detectorReasons: ['finite_assertion'],
                    failureReasons: [],
                },
                arguments: [
                    { role: 'subject', syntacticRole: 'subject', semanticRole: 'actor', surface: 'Kai', entityId: 'entity-kai', start: 0, end: 3, roleConfidenceMillis: 930, roleFailureReasons: [] },
                    { role: 'recipient', syntacticRole: 'recipient', semanticRole: 'recipient', surface: 'Hazel', entityId: 'entity-hazel', start: 9, end: 14, roleConfidenceMillis: 910, roleFailureReasons: [] },
                    { role: 'object', syntacticRole: 'object', semanticRole: 'theme', surface: 'the key', start: 15, end: 22, roleConfidenceMillis: 760, roleFailureReasons: ['unresolved_entity'] },
                ],
                scope: [{ kind: 'assertion' }],
                evidence: [{ label: text, kind: 'sentence', start: 0, end: text.length }],
                confidenceMillis: 920,
                reviewState: 'proposed',
            }],
            situations: [{
                id: `${noteId}:situation:0`,
                propositionId: `${noteId}:prop:0`,
                noteId,
                sentenceIndex: 0,
                start: 0,
                end: text.length,
                predicate: 'give',
                frame: 'transfer_possession',
                situationKind: 'event',
                participantEntityIds: ['entity-kai', 'entity-hazel'],
                participantSurfaces: ['Kai', 'Hazel', 'the key'],
                factuality: 'asserted',
                worldStateEligible: true,
                recurrenceIndex: 0,
                confidenceMillis: 920,
                detectorReasons: ['native_proposition_situation'],
                failureReasons: [],
            }],
            stateIntervals: [],
            eventOrderings: [],
            temporalConflicts: [],
            counters: semanticCounters(),
        }],
        counters: semanticCounters(),
    } as GraphDocumentSemanticSummary;
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: noteId,
        noteIds: [noteId],
        entities: [
            { id: 'entity-kai', label: 'Kai', aliases: [], kind: 'CHARACTER' },
            { id: 'entity-hazel', label: 'Hazel', aliases: [], kind: 'CHARACTER' },
        ],
        occurrences: [
            { noteId, entityId: 'entity-kai', surface: 'Kai', sourceStart: 0, sourceEnd: 3, confidence: 0.99, source: 'registry', generation: builtAt },
            { noteId, entityId: 'entity-hazel', surface: 'Hazel', sourceStart: 9, sourceEnd: 14, confidence: 0.99, source: 'registry', generation: builtAt },
        ],
        chunks: buildAdaptiveGraphRebuildChunks(noteId, text),
        noteTexts: { [noteId]: text },
        documentSemanticSummary,
        builtAt,
        postProcessMode: 'core',
        embeddingStagePolicy: { entityLinkerEnabled: false },
        operatorMutationJournal,
    });
}

function semanticCounters() {
    return {
        documents: 1,
        sentences: 1,
        propositions: 1,
        arguments: 3,
        resolvedArguments: 2,
        negated: 0,
        modal: 0,
        conditional: 0,
        attributed: 0,
        quoted: 0,
        questions: 0,
        directives: 0,
        nAry: 1,
        reviewable: 1,
        ledgerOnly: 0,
        predicateModifiers: 0,
        predicateNoise: 0,
    };
}

function firstFactObjectId(snapshot: GraphRebuildSnapshot): string {
    const row = snapshot.documentReviewSummary?.rows.find((candidate) => candidate.objectKind === 'graph_fact_candidate');
    expect(row).toBeTruthy();
    return row!.objectId;
}

function rowState(snapshot: GraphRebuildSnapshot, objectId: string): string | undefined {
    return snapshot.documentReviewSummary?.rows.find((row) => row.objectId === objectId)?.state;
}

function graphTruthFixtures(): GraphTruthCommitLike[] {
    return [
        truthCommit('commit-reverted', 1, 'assert', [], null, ['receipt-reverted'], ['source-reverted']),
        truthCommit('commit-old', 2, 'assert', [], null, ['receipt-old'], ['source-old']),
        truthCommit('commit-active', 3, 'supersede', ['commit-old'], null, ['receipt-active'], ['source-active']),
        truthCommit('commit-reverter', 4, 'revert', [], 'commit-reverted', ['receipt-reverter'], ['source-reverter'], false),
    ];
}

function truthCommit(
    commitId: string,
    generation: number,
    operation: GraphTruthCommitLike['operation'],
    predecessorCommitIds: string[],
    reversesCommitId: string | null,
    receiptIds: string[],
    sourceIds: string[],
    withBatch = true,
): GraphTruthCommitLike {
    return {
        commitId,
        generation,
        operation,
        predecessorCommitIds,
        reversesCommitId,
        receiptIds,
        sourceGenerations: sourceIds.map((sourceId) => ({ sourceId, generation })),
        committedAt: generation * 10,
        batch: withBatch ? {
            vertices: [{ id: `vertex:${commitId}` }],
            edges: [{ sourceId: `vertex:${commitId}`, targetId: 'entity:kai', edgeType: 'supports' }],
        } : { vertices: [], edges: [] },
    };
}
