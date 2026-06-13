import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import type { GraphDocumentSemanticSummary } from './graph-document-semantic';
import { buildFallbackDocumentProfileSummary } from './graph-document-profile';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';

describe('graph document sidecar', () => {
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
                    arguments: [
                        { role: 'subject', surface: 'Kai', entityId: 'entity-kai', start: 0, end: 3 },
                        { role: 'recipient', surface: 'Hazel', entityId: 'entity-hazel', start: 9, end: 14 },
                        { role: 'object', surface: 'the key', start: 15, end: 22 },
                        { role: 'location', surface: 'New Rome', entityId: 'entity-rome', start: 26, end: 34 },
                    ],
                    scope: [{ kind: 'assertion' }],
                    evidence: [{ label: text, kind: 'sentence', start: 0, end: text.length }],
                    confidenceMillis: 910,
                    reviewState: 'proposed',
                }],
                counters: semanticCounters(1),
            }],
            counters: semanticCounters(1),
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
        }));
        expect(sidecar.graphFactCandidates[0].roles?.map((role) => role.role)).toEqual([
            'subject',
            'recipient',
            'object',
            'location',
        ]);
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

function semanticCounters(propositions: number) {
    return {
        documents: 1,
        sentences: 1,
        propositions,
        arguments: 4,
        resolvedArguments: 3,
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
