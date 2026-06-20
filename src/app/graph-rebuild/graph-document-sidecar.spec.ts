import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import type { DocumentUnit } from './graph-document-sidecar';
import type { GraphDocumentSemanticSummary } from './graph-document-semantic';
import { buildFallbackDocumentProfileSummary } from './graph-document-profile';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';

describe('graph document sidecar', () => {
    it.each(loadHierarchyGoldenFixture().cases)('preserves true heading ancestry: $name', (fixture) => {
        const sidecar = buildGraphDocumentSidecar({
            noteIds: [fixture.noteId],
            noteTexts: { [fixture.noteId]: fixture.text },
            chunks: buildAdaptiveGraphRebuildChunks(fixture.noteId, fixture.text),
            builtAt: 9,
        });
        const sectionsByLabel = new Map(sidecar.sections.map((section) => [section.label, section]));

        for (const expected of fixture.sections) {
            const section = sectionsByLabel.get(expected.label);
            const parent = sectionsByLabel.get(expected.parent);
            expect(section, expected.label).toBeDefined();
            expect(parent, expected.parent).toBeDefined();
            expect(section).toMatchObject({
                kind: expected.kind,
                depth: expected.depth,
                parentId: parent?.id,
                start: fixture.text.indexOf(expected.startsAt),
                end: expected.endsBefore === null ? fixture.text.length : fixture.text.indexOf(expected.endsBefore),
            });
            expect(parent?.childIds).toContain(section?.id);
        }

        for (const expected of fixture.paragraphs) {
            const start = fixture.text.indexOf(expected.text);
            const paragraph = sidecar.units.find((unit) => unit.kind === 'paragraph' && unit.start === start);
            expect(paragraph, expected.text).toBeDefined();
            expect(paragraph?.parentId).toBe(sectionsByLabel.get(expected.parent)?.id);
            expect(ancestorLabels(sidecar.units, paragraph)).toEqual(expected.ancestors);
        }
    });

    it('models mixed document structure without promoting machine units to anchors', () => {
        const text = [
            '# Release Notes',
            'Policy means the migration must keep evidence because the record shows why it changed.',
            '- Run the migration',
            '- Apply the index',
            '```ts',
            'const changed = true;',
            '```',
            '| Name | Value |\n| --- | --- |\n| latency | 2s |',
            '"Are we clear?" Amara asked.',
            'Chapter 2',
            'Scene Dock',
            'Ryan moved from Rust Town to New Rome.',
        ].join('\n\n');
        const chunks = buildAdaptiveGraphRebuildChunks('mixed-doc', text);
        const sidecar = buildGraphDocumentSidecar({
            noteIds: ['mixed-doc'],
            noteTexts: { 'mixed-doc': text },
            chunks,
            builtAt: 10,
        });

        expect(sidecar.schemaVersion).toBe('phoenix-document-sidecar/v1');
        expect(sidecar.documentProfileSummary?.source).toBe('typescript_compatibility');
        expect(sidecar.anchorPolicy).toBe('sidecar_never_promotes_anchors');
        expect(sidecar.counters.userAnchorPromotions).toBe(0);
        expect(sidecar.units.every((unit) => unit.anchorPolicy === 'sidecar_only')).toBe(true);
        expect(sidecar.evidenceSpans.every((span) => span.anchorPolicy === 'sidecar_only')).toBe(true);
        expect(sidecar.counters.leafChunks).toBe(chunks.length);
        expect(sidecar.counters.byKind).toEqual(expect.objectContaining({
            section: expect.any(Number),
            paragraph_group: expect.any(Number),
            list: expect.any(Number),
            table: expect.any(Number),
            code_block: expect.any(Number),
            dialogue_block: expect.any(Number),
            chapter: expect.any(Number),
            scene: expect.any(Number),
        }));
        expect(sidecar.rhetoricalUnits.map((unit) => unit.kind)).toEqual(expect.arrayContaining([
            'definition',
            'evidence',
            'instruction',
            'question',
        ]));
        expect(sidecar.graphFactCandidates.map((unit) => unit.kind)).toEqual(expect.arrayContaining([
            'event',
            'relation_bundle',
        ]));
        expect(sidecar.graphFactCandidates.length).toBeLessThanOrEqual(sidecar.counters.paragraphs);
    });

    it('preserves native profile provenance and uses its weighted ontology', () => {
        const text = '# Methods\n\nThe method compares samples.\n\n# Results\n\nEvidence supports the result.';
        const chunks = buildAdaptiveGraphRebuildChunks('weighted-paper', text);
        const profile = buildFallbackDocumentProfileSummary({ 'weighted-paper': text }, 14);
        profile.source = 'native_rust';
        profile.counters.nativeProfiles = 1;
        const sidecar = buildGraphDocumentSidecar({
            noteIds: ['weighted-paper'],
            noteTexts: { 'weighted-paper': text },
            chunks,
            builtAt: 14,
            documentProfileSummary: profile,
        });

        expect(sidecar.documentProfileSummary).toBe(profile);
        expect(sidecar.documentProfileSummary?.source).toBe('native_rust');
        expect(sidecar.rhetoricalUnits.some((unit) =>
            unit.kind === 'method' && unit.confidence.reasons.includes('document_profile_weighted'),
        )).toBe(true);
    });

    it('gives shortrun prose useful structure even without markdown headings', () => {
        const text = readFileSync(new URL('../../../docs/shortrun.md', import.meta.url), 'utf8');
        const chunks = buildAdaptiveGraphRebuildChunks('shortrun', text);
        const sidecar = buildGraphDocumentSidecar({
            noteIds: ['shortrun'],
            noteTexts: { shortrun: text },
            chunks,
            builtAt: 11,
        });

        expect(text).not.toMatch(/^#/m);
        expect(sidecar.counters.sections).toBeGreaterThanOrEqual(2);
        expect(sidecar.counters.paragraphGroups).toBeGreaterThan(100);
        expect(sidecar.counters.paragraphs).toBeGreaterThan(900);
        expect(sidecar.counters.sentences).toBeGreaterThan(900);
        expect(sidecar.counters.leafChunks).toBe(chunks.length);
        expect(sidecar.counters.byKind.dialogue_block).toBeGreaterThan(0);
        expect(sidecar.counters.byKind.action_block).toBeGreaterThan(0);
        expect(sidecar.counters.rhetoricalUnits).toBeGreaterThan(0);
        expect(sidecar.counters.userAnchorPromotions).toBe(0);
    });

    it('threads the sidecar through graph snapshots without changing anchor counts', () => {
        const text = [
            '# Field Note',
            'Amara moved from Red Mesa to Halcyon because the report changed the plan.',
            'Use the recovered record as evidence.',
        ].join('\n\n');
        const chunks = buildAdaptiveGraphRebuildChunks('snapshot-sidecar', text);
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:snapshot-sidecar',
            noteIds: ['snapshot-sidecar'],
            entities: [],
            occurrences: [],
            chunks,
            noteTexts: { 'snapshot-sidecar': text },
            builtAt: 12,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });

        expect(snapshot.chunks).toHaveLength(chunks.length);
        expect(snapshot.counters.acceptedAnchors).toBe(0);
        expect(snapshot.documentSidecarSummary?.schemaVersion).toBe('phoenix-document-sidecar/v1');
        expect(snapshot.documentSidecarSummary?.counters.userAnchorPromotions).toBe(0);
        expect(snapshot.counters.documentSidecarUnits).toBe(snapshot.documentSidecarSummary?.counters.units);
        expect(snapshot.counters.documentSidecarGraphFacts).toBeGreaterThan(0);
    });

    it('uses native semantic propositions as role-aware facts instead of heuristic paragraph facts', () => {
        const text = 'Kai gave Hazel the key in New Rome.';
        const semantics: GraphDocumentSemanticSummary = {
            schemaVersion: 'phoenix-document-semantics/v1',
            source: 'native_rust',
            documents: [{
                noteId: 'semantic-note',
                textChars: text.length,
                propositions: [{
                    id: 'semantic-note:prop:0',
                    noteId: 'semantic-note',
                    sentenceIndex: 0,
                    start: 0,
                    end: text.length,
                    preview: text,
                    predicate: 'give',
                    relationType: 'gives',
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
                    id: 'semantic-note:situation:0',
                    propositionId: 'semantic-note:prop:0',
                    noteId: 'semantic-note',
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
                    id: 'semantic-note:state:0',
                    noteId: 'semantic-note',
                    stateKey: 'entity-kai:possession:key',
                    subjectKey: 'entity-kai',
                    predicate: 'possess',
                    value: 'the key',
                    polarity: 'positive',
                    status: 'open',
                    startSituationId: 'semantic-note:situation:0',
                    mentionSituationIds: ['semantic-note:situation:0'],
                    start: 0,
                    persists: false,
                    confidenceMillis: 820,
                    detectorReasons: ['state_frame_interval'],
                    failureReasons: [],
                }],
                eventOrderings: [{
                    id: 'semantic-note:ordering:0',
                    noteId: 'semantic-note',
                    sourceSituationId: 'semantic-note:situation:0',
                    targetSituationId: 'semantic-note:situation:1',
                    relation: 'before',
                    source: 'explicit_cue',
                    confidenceMillis: 840,
                    detectorReasons: ['explicit_cue:before'],
                    failureReasons: [],
                }],
                temporalConflicts: [{
                    id: 'semantic-note:conflict:0',
                    noteId: 'semantic-note',
                    kind: 'unresolved_state_transition',
                    stateKey: 'entity-kai:possession:key',
                    situationIds: ['semantic-note:situation:0'],
                    stateIntervalIds: ['semantic-note:state:0'],
                    severity: 'medium',
                    confidenceMillis: 700,
                    detectorReasons: ['opposing_state_polarity_without_transition_cue'],
                    failureReasons: ['state_transition_requires_review'],
                }],
                counters: semanticCounters(1, 1, 1),
            }],
            counters: semanticCounters(1, 1, 1),
        };
        const sidecar = buildGraphDocumentSidecar({
            noteIds: ['semantic-note'],
            noteTexts: { 'semantic-note': text },
            chunks: buildAdaptiveGraphRebuildChunks('semantic-note', text),
            builtAt: 20,
            documentSemanticSummary: semantics,
        });

        expect(sidecar.graphFactCandidates).toHaveLength(1);
        expect(sidecar.graphFactCandidates[0]).toEqual(expect.objectContaining({
            kind: 'n_ary_claim',
            predicate: 'give',
            semanticPropositionId: 'semantic-note:prop:0',
            frameFamily: 'transfer',
            frameConfidence: 0.9,
        }));
        expect(sidecar.graphFactCandidates[0].frame?.frame).toBe('transfer_possession');
        expect(sidecar.graphFactCandidates[0].confidence.reasons).toEqual(expect.arrayContaining([
            'frame:transfer_possession',
            'frame_source:lexical_table',
            'factuality:asserted',
            'speech_act:assertion',
            'doc_recovery:omitted_subject',
        ]));
        expect(sidecar.graphFactCandidates[0].factuality?.factuality).toBe('asserted');
        expect(sidecar.graphFactCandidates[0].documentArgumentRecoveries?.[0].kind).toBe('omitted_subject');
        expect(sidecar.graphFactCandidates[0]).toEqual(expect.objectContaining({
            semanticSituationId: 'semantic-note:situation:0',
            stateIntervalIds: ['semantic-note:state:0'],
            eventOrderingIds: ['semantic-note:ordering:0'],
            temporalConflictIds: ['semantic-note:conflict:0'],
        }));
        expect(sidecar.counters).toEqual(expect.objectContaining({
            situationInstances: 1,
            stateIntervals: 1,
            eventOrderings: 1,
            temporalConflicts: 1,
        }));
        expect(sidecar.graphFactCandidates[0].roles?.map((role) => role.role)).toEqual([
            'actor',
            'recipient',
            'theme',
            'location',
        ]);
        expect(sidecar.graphFactCandidates[0].subjectSurfaces).toEqual(['Kai']);
        expect(sidecar.graphFactCandidates[0].roles?.find((role) => role.role === 'actor')?.recoveryKinds).toEqual(['omitted_subject']);
        expect(sidecar.graphFactCandidates[0].objectSurfaces).toEqual(['Hazel', 'the key', 'New Rome']);
        expect(sidecar.graphFactCandidates[0].roles?.find((role) => role.role === 'theme')).toEqual(expect.objectContaining({
            surfaces: ['the key'],
            entityIds: [],
            failureReasons: ['unresolved_entity'],
        }));
    });

    it('keeps modifier-like native predicates in the ledger instead of graph fact review', () => {
        const text = 'Kai found sponsored heroes. Kai warned Hazel.';
        const semantics: GraphDocumentSemanticSummary = {
            schemaVersion: 'phoenix-document-semantics/v1',
            source: 'native_rust',
            documents: [{
                noteId: 'predicate-note',
                textChars: text.length,
                propositions: [
                    {
                        id: 'predicate-note:prop:modifier',
                        noteId: 'predicate-note',
                        sentenceIndex: 0,
                        start: 10,
                        end: 26,
                        preview: 'sponsored heroes',
                        predicate: 'sponsored',
                        relationType: 'relates_to',
                        predicateQuality: 'participle_modifier',
                        predicateAdmission: 'ledger_only',
                        qualityReasons: ['participle_before_nominal'],
                        triggerStart: 10,
                        triggerEnd: 19,
                        arguments: [
                            { role: 'object', surface: 'heroes', start: 20, end: 26 },
                        ],
                        scope: [{ kind: 'assertion' }],
                        evidence: [{ label: 'sponsored heroes', kind: 'sentence', start: 10, end: 26 }],
                        confidenceMillis: 360,
                        reviewState: 'ledger_only',
                    },
                    {
                        id: 'predicate-note:prop:warned',
                        noteId: 'predicate-note',
                        sentenceIndex: 1,
                        start: 28,
                        end: text.length,
                        preview: 'Kai warned Hazel.',
                        predicate: 'warned',
                        relationType: 'communication',
                        predicateQuality: 'relation_cue',
                        predicateAdmission: 'review',
                        qualityReasons: ['typed_relation_cue'],
                        triggerStart: 32,
                        triggerEnd: 38,
                        arguments: [
                            { role: 'subject', surface: 'Kai', entityId: 'entity-kai', start: 28, end: 31 },
                            { role: 'object', surface: 'Hazel', entityId: 'entity-hazel', start: 39, end: 44 },
                        ],
                        scope: [{ kind: 'assertion' }],
                        evidence: [{ label: 'Kai warned Hazel', kind: 'sentence', start: 28, end: text.length }],
                        confidenceMillis: 900,
                        reviewState: 'proposed',
                    },
                ],
                counters: {
                    ...semanticCounters(2),
                    reviewable: 1,
                    ledgerOnly: 1,
                    predicateModifiers: 1,
                },
            }],
            counters: {
                ...semanticCounters(2),
                reviewable: 1,
                ledgerOnly: 1,
                predicateModifiers: 1,
            },
        };
        const sidecar = buildGraphDocumentSidecar({
            noteIds: ['predicate-note'],
            noteTexts: { 'predicate-note': text },
            chunks: buildAdaptiveGraphRebuildChunks('predicate-note', text),
            builtAt: 21,
            documentSemanticSummary: semantics,
        });

        expect(sidecar.graphFactCandidates).toHaveLength(1);
        expect(sidecar.graphFactCandidates[0].predicate).toBe('warned');
        expect(sidecar.graphFactCandidates.some((candidate) => candidate.predicate === 'sponsored')).toBe(false);
    });
});

interface HierarchyGoldenFixture {
    schemaVersion: 'phoenix-document-hierarchy-golden/v1';
    cases: Array<{
        name: string;
        noteId: string;
        text: string;
        sections: Array<{
            label: string;
            kind: 'section' | 'subsection';
            depth: number;
            parent: string;
            startsAt: string;
            endsBefore: string | null;
        }>;
        paragraphs: Array<{
            text: string;
            parent: string;
            ancestors: string[];
        }>;
    }>;
}

function loadHierarchyGoldenFixture(): HierarchyGoldenFixture {
    const raw = readFileSync(new URL('./fixtures/document-hierarchy-golden.json', import.meta.url), 'utf8');
    return JSON.parse(raw) as HierarchyGoldenFixture;
}

function ancestorLabels(units: DocumentUnit[], unit: DocumentUnit | undefined): string[] {
    const unitsById = new Map(units.map((candidate) => [candidate.id, candidate]));
    const labels: string[] = [];
    let parentId = unit?.parentId;
    while (parentId) {
        const parent = unitsById.get(parentId);
        if (!parent) break;
        labels.push(parent.label);
        parentId = parent.parentId;
    }
    return labels;
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
        sourcePropositionId: 'semantic-note:prop:prior',
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
