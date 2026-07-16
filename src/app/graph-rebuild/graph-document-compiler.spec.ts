import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import {
    applyGraphDocumentReviewAction,
    buildGraphDocumentReviewSummary,
} from './graph-document-review';
import { buildGraphDocumentCompilePlanSummary } from './graph-document-compiler';
import { buildCompatibilityGraphCompilerSidecar } from './graph-compiler-compat';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { GraphDocumentSemanticSummary } from './graph-document-semantic';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

describe('graph document compiler', () => {
    it('plans reviewed semantic situations for native compile without TS topology mutation', () => {
        const sidecar = semanticRoleSidecar({ conflict: false });
        const review = buildGraphDocumentReviewSummary(sidecar, 20);
        const fact = requireFactRow(review);
        const compiledReview = applyGraphDocumentReviewAction(review, {
            rowId: fact.id,
            actionKind: 'compile_to_graph',
            createdAt: 21,
        });
        const summary = buildGraphDocumentCompilePlanSummary({
            sidecar,
            review: compiledReview,
            entities: SEMANTIC_ENTITIES,
            builtAt: 22,
            baseline: { atomCount: 3, factCount: 2, edgeCount: 1 },
        });
        const diff = summary.topologyDiffs.find((row) => row.status === 'pending_commit');
        const receipt = summary.receipts.find((row) => row.topologyDiffId === diff?.id);
        const hyperedge = summary.hyperedges.find((row) => row.id === diff?.outputId);

        expect(summary.schemaVersion).toBe('phoenix-document-compiler/v2');
        expect(summary).toMatchObject({
            authority: 'typescript_compile_plan',
            nativeCompilerRequired: true,
            mutationPolicy: 'ts_never_commits_document_graph',
        });
        expect(diff).toMatchObject({
            outputKind: 'hyperedge',
            nativeCompileCandidate: true,
            mutationAllowed: false,
            topologyCommit: false,
            beforeGraph: { atomCount: 3, factCount: 2, edgeCount: 1 },
        });
        expect(diff?.afterGraph).toEqual(diff?.beforeGraph);
        expect(receipt).toMatchObject({
            reversible: true,
            mutationAllowed: false,
            invariant: 'document_compiler_native_payload_candidate',
            undoPatch: {
                operation: 'remove_document_compiler_ledger_row',
                restoreReviewState: 'compiled_to_graph',
            },
        });
        expect(hyperedge?.nary).toBe(true);
        expect(hyperedge?.roles.length).toBeGreaterThan(2);
        expect(hyperedge?.provenance.sourceReviewRowId).toBe(fact.id);
        expect(summary.counters.reviewedFacts).toBe(1);
        expect(summary.counters.topologyCommits).toBe(0);
        expect(summary.counters.nativeCompileCandidates).toBe(1);
        expect(summary.counters.mutationAllowed).toBe(0);
        expect(summary.counters.situationFrameHyperedges).toBe(1);
    });

    it('keeps ambiguous machine facts reviewable and visible without mutating topology', () => {
        const sidecar = sidecarFixture();
        const review = buildGraphDocumentReviewSummary(sidecar, 30);
        const summary = buildGraphDocumentCompilePlanSummary({
            sidecar,
            review,
            entities: COMPILER_ENTITIES,
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

    it('keeps raw high-confidence facts reviewable while bounding disposable sidecar overlays', () => {
        const sidecar = highConfidenceSidecar(sidecarFixture());
        const review = buildGraphDocumentReviewSummary(sidecar, 40);
        const summary = buildGraphDocumentCompilePlanSummary({
            sidecar,
            review,
            entities: COMPILER_ENTITIES,
            builtAt: 41,
        });

        expect(summary.counters.highConfidenceFacts).toBe(0);
        expect(summary.counters.topologyCommits).toBe(0);
        expect(summary.counters.rawPredicateFactsBlocked).toBeGreaterThan(0);
        expect(summary.counters.hyperedges).toBeLessThanOrEqual(Math.min(sidecar.graphFactCandidates.length, 96));
        expect(summary.counters.documentStructureEdges).toBeLessThanOrEqual(512);
        expect(summary.counters.retrievalOverlays).toBeLessThanOrEqual(256);
        expect(summary.entityMentions.every((row) => row.anchorPolicy === 'mention_only_not_user_anchor')).toBe(true);
    });

    it('compiles normalized semantic roles while preserving role uncertainty', () => {
        const sidecar = semanticRoleSidecar();
        const review = buildGraphDocumentReviewSummary(sidecar, 42);
        const fact = requireFactRow(review);
        const compiledReview = applyGraphDocumentReviewAction(review, {
            rowId: fact.id,
            actionKind: 'compile_to_graph',
            createdAt: 43,
        });
        const summary = buildGraphDocumentCompilePlanSummary({
            sidecar,
            review: compiledReview,
            entities: [
                { id: 'entity-kai', label: 'Kai', aliases: [] },
                { id: 'entity-hazel', label: 'Hazel', aliases: [] },
                { id: 'entity-rome', label: 'New Rome', aliases: [] },
            ],
            builtAt: 44,
        });
        const relation = summary.relationCandidates.find((row) => row.predicate === 'give');
        const themeMention = summary.entityMentions.find((row) => row.role === 'theme' && row.surface === 'the key');
        const actorMention = summary.entityMentions.find((row) => row.role === 'actor' && row.resolvedEntityId === 'entity-kai');

        expect(relation?.frame).toBe('transfer_possession');
        expect(relation?.frameFamily).toBe('transfer');
        expect(relation?.factuality).toBe('asserted');
        expect(relation?.speechAct).toBe('assertion');
        expect(relation?.semanticSituationId).toBe('semantic-compiler:situation:0');
        expect(relation?.stateIntervalIds).toEqual(['semantic-compiler:state:0']);
        expect(relation?.eventOrderingIds).toEqual(['semantic-compiler:ordering:0']);
        expect(relation?.temporalConflictIds).toEqual(['semantic-compiler:conflict:0']);
        expect(relation?.subjectMentionIds.length).toBeGreaterThan(0);
        expect(relation?.objectMentionIds.length).toBeGreaterThan(0);
        expect(actorMention?.syntacticRoles).toEqual(['subject']);
        expect(actorMention?.recoveryKinds).toEqual(['omitted_subject']);
        expect(themeMention?.resolvedEntityId).toBeUndefined();
        expect(themeMention?.roleFailureReasons).toEqual(['unresolved_entity']);
        expect(summary.hyperedges.some((edge) =>
            edge.frame === 'transfer_possession'
            && edge.factuality === 'asserted'
            && edge.roles.some((role) => role.role === 'actor' && role.recoveryKinds?.includes('omitted_subject'))
            && edge.roles.some((role) => role.role === 'theme' && role.failureReasons?.includes('unresolved_entity')),
        )).toBe(true);
    });

    it('keeps pending document hyperedges out of the TypeScript compatibility graph compiler', () => {
        const sidecar = semanticRoleSidecar({ conflict: false });
        const review = buildGraphDocumentReviewSummary(sidecar, 45);
        const fact = requireFactRow(review);
        const compiledReview = applyGraphDocumentReviewAction(review, {
            rowId: fact.id,
            actionKind: 'compile_to_graph',
            createdAt: 46,
        });
        const summary = buildGraphDocumentCompilePlanSummary({
            sidecar,
            review: compiledReview,
            entities: SEMANTIC_ENTITIES,
            builtAt: 46,
        });
        const sidecarOutput = buildCompatibilityGraphCompilerSidecar(snapshotWithCompiler(sidecar, summary));
        const documentFact = sidecarOutput.factGraph.facts.find((fact) => fact.id.startsWith('fact:document-hyperedge:'));

        expect(summary.topologyDiffs.some((row) => row.nativeCompileCandidate)).toBe(true);
        expect(documentFact).toBeUndefined();
        expect(sidecarOutput.factGraph.roles.some((role) => role.factId.startsWith('fact:document-hyperedge:'))).toBe(false);
        expect(sidecarOutput.factGraph.evidenceAnchors.some((evidence) => evidence.id.startsWith('evidence:document:'))).toBe(false);
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

        expect(snapshot.documentCompilerSummary?.schemaVersion).toBe('phoenix-document-compiler/v2');
        expect(snapshot.counters.documentCompilerHyperedges).toBe(snapshot.documentCompilerSummary?.counters.hyperedges);
        expect(snapshot.counters.documentCompilerTopologyDiffs).toBe(snapshot.documentCompilerSummary?.counters.topologyDiffs);
        expect(snapshot.counters.documentCompilerReceipts).toBe(snapshot.documentCompilerSummary?.counters.receipts);
        expect(snapshot.counters.documentCompilerMutationAllowed).toBe(snapshot.documentCompilerSummary?.counters.mutationAllowed);
        expect(snapshot.counters.documentCompilerNativeCompileCandidates).toBe(snapshot.documentCompilerSummary?.counters.nativeCompileCandidates);
    });
});

function requireFactRow(review: ReturnType<typeof buildGraphDocumentReviewSummary>) {
    const row = review.rows.find((candidate) => candidate.objectKind === 'graph_fact_candidate');
    expect(row).toBeTruthy();
    return row!;
}

function highConfidenceSidecar(sidecar: ReturnType<typeof buildGraphDocumentSidecar>) {
    const firstFact = sidecar.graphFactCandidates.find((fact) => fact.kind === 'relation_bundle');
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

const COMPILER_ENTITIES = [
    { id: 'entity:amara', label: 'Amara', aliases: [] },
    { id: 'entity:red-mesa', label: 'Red Mesa', aliases: [] },
    { id: 'entity:halcyon', label: 'Halcyon', aliases: [] },
    { id: 'entity:captain-ilya', label: 'Captain Ilya', aliases: [] },
    { id: 'entity:morgan', label: 'Morgan', aliases: [] },
    { id: 'entity:kai', label: 'Kai', aliases: [] },
    { id: 'entity:hazel', label: 'Hazel', aliases: [] },
];

const SEMANTIC_ENTITIES = [
    { id: 'entity-kai', label: 'Kai', aliases: [] },
    { id: 'entity-hazel', label: 'Hazel', aliases: [] },
    { id: 'entity-rome', label: 'New Rome', aliases: [] },
];

function snapshotWithCompiler(
    sidecar: ReturnType<typeof buildGraphDocumentSidecar>,
    documentCompilerSummary: ReturnType<typeof buildGraphDocumentCompilePlanSummary>,
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

function semanticRoleSidecar(options: { conflict?: boolean } = {}) {
    const includeConflict = options.conflict !== false;
    const text = 'Kai gave Hazel the key in New Rome.';
    const semantics: GraphDocumentSemanticSummary = {
        schemaVersion: 'phoenix-document-semantics/v1',
        source: 'native_rust',
        documents: [{
            noteId: 'semantic-compiler',
            textChars: text.length,
            propositions: [{
                id: 'semantic-compiler:prop:0',
                noteId: 'semantic-compiler',
                sentenceIndex: 0,
                start: 0,
                end: text.length,
                preview: text,
                predicate: 'give',
                relationType: 'communication',
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
                    definition: 'An actor transfers or receives a theme across a possession boundary.',
                    source: 'lexical_table',
                    confidenceMillis: 900,
                    expectedRoles: ['actor', 'theme', 'recipient'],
                    matchedRoles: ['actor', 'theme', 'recipient'],
                    missingRoles: [],
                    reasons: ['lexical_unit_match'],
                    failureReasons: [],
                },
                factuality: assertedFactuality(),
                arguments: [
                    { role: 'subject', syntacticRole: 'subject', semanticRole: 'actor', surface: 'Kai', entityId: 'entity-kai', start: 0, end: 3, roleConfidenceMillis: 900, roleFailureReasons: [] },
                    { role: 'recipient', syntacticRole: 'recipient', semanticRole: 'recipient', surface: 'Hazel', entityId: 'entity-hazel', start: 9, end: 14, roleConfidenceMillis: 890, roleFailureReasons: [] },
                    { role: 'object', syntacticRole: 'object', semanticRole: 'theme', surface: 'the key', start: 15, end: 22, roleConfidenceMillis: 725, roleFailureReasons: ['unresolved_entity'] },
                    { role: 'location', syntacticRole: 'location', semanticRole: 'location', surface: 'New Rome', entityId: 'entity-rome', start: 26, end: 34, roleConfidenceMillis: 830, roleFailureReasons: [] },
                ],
                documentArgumentRecoveries: [recoveredActor()],
                scope: [{ kind: 'assertion' }],
                evidence: [{ label: text, kind: 'sentence', start: 0, end: text.length }],
                confidenceMillis: 910,
                reviewState: 'proposed',
            }],
            situations: [{
                id: 'semantic-compiler:situation:0',
                propositionId: 'semantic-compiler:prop:0',
                noteId: 'semantic-compiler',
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
                confidenceMillis: 900,
                detectorReasons: ['native_proposition_situation'],
                failureReasons: [],
            }],
            stateIntervals: [{
                id: 'semantic-compiler:state:0',
                noteId: 'semantic-compiler',
                stateKey: 'entity-kai:possession:key',
                subjectKey: 'entity-kai',
                predicate: 'possess',
                value: 'the key',
                polarity: 'positive',
                status: 'open',
                startSituationId: 'semantic-compiler:situation:0',
                mentionSituationIds: ['semantic-compiler:situation:0'],
                start: 0,
                persists: false,
                confidenceMillis: 820,
                detectorReasons: ['state_frame_interval'],
                failureReasons: [],
            }],
            eventOrderings: [{
                id: 'semantic-compiler:ordering:0',
                noteId: 'semantic-compiler',
                sourceSituationId: 'semantic-compiler:situation:0',
                targetSituationId: 'semantic-compiler:situation:1',
                relation: 'before',
                source: 'explicit_cue',
                confidenceMillis: 840,
                detectorReasons: ['explicit_cue:before'],
                failureReasons: [],
            }],
            temporalConflicts: includeConflict ? [{
                id: 'semantic-compiler:conflict:0',
                noteId: 'semantic-compiler',
                kind: 'unresolved_state_transition',
                stateKey: 'entity-kai:possession:key',
                situationIds: ['semantic-compiler:situation:0'],
                stateIntervalIds: ['semantic-compiler:state:0'],
                severity: 'medium',
                confidenceMillis: 700,
                detectorReasons: ['opposing_state_polarity_without_transition_cue'],
                failureReasons: ['state_transition_requires_review'],
            }] : [],
            counters: semanticCounters(1, 1, 1),
        }],
        counters: semanticCounters(1, 1, 1),
    };
    return buildGraphDocumentSidecar({
        noteIds: ['semantic-compiler'],
        noteTexts: { 'semantic-compiler': text },
        chunks: buildAdaptiveGraphRebuildChunks('semantic-compiler', text),
        builtAt: 42,
        documentSemanticSummary: semantics,
    });
}

function semanticCounters(propositions: number, frames = 0, recoveries = 0) {
    return {
        documents: 1,
        sentences: 1,
        propositions,
        arguments: 4,
        resolvedArguments: 3,
        roleAnnotations: 4,
        unresolvedRoleSurfaces: 1,
        roleFailureReasons: 1,
        frameAnnotations: frames,
        lexicalFrameMatches: frames,
        fallbackFrameMatches: 0,
        lowConfidenceFrames: 0,
        frameFailureReasons: 0,
        factualityAnnotations: propositions,
        scopedFactuality: 0,
        attributedFactuality: 0,
        quotedFactuality: 0,
        conditionalFactuality: 0,
        speechOrBeliefFrames: 0,
        lowConfidenceFactuality: 0,
        factualityFailureReasons: 0,
        documentArgumentRecoveries: recoveries,
        localCoreferenceRecoveries: 0,
        aliasContinuityRecoveries: 0,
        omittedSubjectRecoveries: recoveries,
        quoteSpeakerRecoveries: 0,
        repeatedEventLinks: 0,
        windowArgumentCompletions: 0,
        lowConfidenceRecoveries: 0,
        recoveryFailureReasons: 0,
        negated: 0,
        modal: 0,
        conditional: 0,
        attributed: 0,
        quoted: 0,
        questions: 0,
        directives: 0,
        nAry: propositions,
        reviewable: propositions,
        ledgerOnly: 0,
        predicateModifiers: 0,
        predicateNoise: 0,
    };
}

function recoveredActor() {
    return {
        kind: 'omitted_subject',
        role: 'actor',
        syntacticRole: 'subject',
        semanticRole: 'actor',
        surface: 'Kai',
        entityId: 'entity-kai',
        start: 0,
        end: 3,
        sourcePropositionId: 'semantic-compiler:prop:prior',
        sourceSentenceIndex: 0,
        confidenceMillis: 690,
        detectorReasons: ['document_window_actor_carryover'],
        failureReasons: [],
    };
}

function assertedFactuality() {
    return {
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
        confidenceMillis: 724,
        scopeKinds: ['assertion'],
        detectorReasons: ['native_scope_substrate'],
        failureReasons: [],
    };
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
