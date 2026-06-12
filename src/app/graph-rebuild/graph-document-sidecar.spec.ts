import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
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
            'state_change',
            'procedure_step',
            'relation_bundle',
            'n_ary_claim',
        ]));
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
});
