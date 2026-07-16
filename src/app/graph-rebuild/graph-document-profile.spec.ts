import { describe, expect, it } from 'vitest';

import {
    buildFallbackDocumentProfileSummary,
    documentUnitWeight,
    normalizeDocumentProfileSummary,
} from './graph-document-profile';

describe('document profile adaptation', () => {
    it('weights research units without changing the shared ontology', () => {
        const summary = buildFallbackDocumentProfileSummary({
            paper: [
                '# Abstract',
                'We show that retrieval quality improves.',
                '# Methods',
                'The method compares two indexed samples.',
                '# Results',
                'The result is supported by evidence and Smith et al. (2025).',
            ].join('\n\n'),
        }, 10);
        const profile = summary.profiles[0];

        expect(profile.dominantProfile).toBe('research_paper');
        expect(documentUnitWeight(summary, 'paper', 'method')).toBeGreaterThan(1);
        expect(documentUnitWeight(summary, 'paper', 'result')).toBeGreaterThan(1);
        expect(documentUnitWeight(summary, 'paper', 'chapter')).toBeLessThan(1);
        expect(profile.unitWeights.map((row) => row.kind)).toContain('scene');
    });

    it('uses region-local profiles for mixed notebooks', () => {
        const text = [
            '## Agenda\nAttendees: Kai\nAction item: review deployment.',
            '## API\n```rust\nfn deploy() {}\n```\nConfigure the service.',
        ].join('\n\n');
        const summary = buildFallbackDocumentProfileSummary({ mixed: text }, 20);
        const profile = summary.profiles[0];
        const codeStart = text.indexOf('## API');

        expect(profile.regions.some((region) => region.dominantProfile === 'meeting_notes')).toBe(true);
        expect(profile.regions.some((region) =>
            ['technical_docs', 'code_heavy_notes'].includes(region.dominantProfile),
        )).toBe(true);
        expect(documentUnitWeight(summary, 'mixed', 'code_block', codeStart)).toBeGreaterThan(1);
    });

    it('keeps explanatory reference material distinct from fiction and research papers', () => {
        const summary = buildFallbackDocumentProfileSummary({
            reference: [
                '# Earthquake overview',
                'Scientists use instruments to explain how faults move.',
                '# Learn more',
                'For example, a seismometer records ground motion according to physical standards.',
            ].join('\n\n'),
        }, 30);

        expect(summary.profiles[0].dominantProfile).toBe('reference_article');
        expect(documentUnitWeight(summary, 'reference', 'definition')).toBeGreaterThan(1);
        expect(documentUnitWeight(summary, 'reference', 'chapter')).toBeLessThan(1);
    });

    it('rejects incompatible native payloads instead of trusting their shape', () => {
        expect(normalizeDocumentProfileSummary({ schemaVersion: 'old', profiles: [] })).toBeNull();
        expect(normalizeDocumentProfileSummary({
            schemaVersion: 'phoenix-document-profile/v1',
            profiles: [],
        })?.profiles).toEqual([]);
    });
});
