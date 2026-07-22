import { describe, expect, it } from 'vitest';
import {
    LFM_EXTRACTIVE_SMOOTHING_DEFAULT_DTYPE,
    LFM_EXTRACTIVE_SMOOTHING_MODEL_ID,
    adjudicateLfmExtractiveSmoothingOutput,
    buildFallbackExtractiveSmoothingBullets,
    buildLfmExtractiveSmoothingMessages,
    parseLfmExtractiveSmoothingOutput,
    verifyLfmExtractiveSmoothingBullets,
    type LfmExtractiveSmoothingRequest,
} from './lfm-extractive-smoothing';

const request: LfmExtractiveSmoothingRequest = {
    title: 'Glass Archive',
    maxBullets: 2,
    evidence: [
        {
            id: 'e1',
            text: 'Mira entered the Glass Archive on March 3 with two sealed keys.',
        },
        {
            id: 'e2',
            text: 'Orin stayed outside because the bronze oath barred him from crossing the threshold.',
        },
        {
            id: 'e3',
            text: 'The archive bell rang once when Mira touched the south ledger.',
        },
    ],
    draftBullets: [
        {
            text: 'Mira went into the Glass Archive on March 3 carrying two sealed keys.',
            evidenceIds: ['e1'],
        },
        {
            text: 'Orin stayed outside because the bronze oath blocked him at the threshold.',
            evidenceIds: ['e2'],
        },
    ],
};

describe('lfm extractive smoothing', () => {
    it('builds a fp16 model-ready rewrite prompt without asking for reasoning', () => {
        const messages = buildLfmExtractiveSmoothingMessages(request);

        expect(LFM_EXTRACTIVE_SMOOTHING_MODEL_ID).toBe('onnx-community/LFM2.5-350M-ONNX');
        expect(LFM_EXTRACTIVE_SMOOTHING_DEFAULT_DTYPE).toBe('fp16');
        expect(messages).toHaveLength(2);
        expect(messages[0].content).toContain('Rewrite only');
        expect(messages[0].content).toContain('Return only valid JSON');
        expect(messages[0].content).toContain('Preserve every name, date, number');
        expect(messages[1].content).toContain('[e1] Mira entered the Glass Archive');
        expect(messages[1].content).toContain('Target bullets: 2');
    });

    it('parses the fp16 smoke shape with separate fenced JSON objects', () => {
        const output = [
            '```json',
            '{',
            '  "text": "Mira went into the Glass Archive on March 3 carrying two sealed keys.",',
            '  "evidenceIds": ["e1"]',
            '}',
            '```',
            '```json',
            '{',
            '  "text": "Orin stayed outside because the bronze oath blocked him at the threshold.",',
            '  "evidenceIds": ["e2"]',
            '}',
            '```',
        ].join('\n');

        const bullets = parseLfmExtractiveSmoothingOutput(output);

        expect(bullets).toEqual([
            {
                text: 'Mira went into the Glass Archive on March 3 carrying two sealed keys.',
                evidenceIds: ['e1'],
                source: 'lfm2.5_fp16',
            },
            {
                text: 'Orin stayed outside because the bronze oath blocked him at the threshold.',
                evidenceIds: ['e2'],
                source: 'lfm2.5_fp16',
            },
        ]);
    });

    it('accepts supported rewrites and avoids fallback when enough bullets survive', () => {
        const output = JSON.stringify([
            {
                text: 'Mira entered the Glass Archive on March 3 with two sealed keys.',
                evidenceIds: ['e1'],
            },
            {
                text: 'Orin stayed outside because the bronze oath barred him from crossing the threshold.',
                evidenceIds: ['e2'],
            },
        ]);

        const result = adjudicateLfmExtractiveSmoothingOutput(request, output, 'lfm2.5_fp16');

        expect(result.outcome).toBe('accepted');
        expect(result.counters).toMatchObject({
            parsedBullets: 2,
            acceptedModelBullets: 2,
            fallbackBullets: 0,
            issueCount: 0,
        });
        expect(result.bullets.every(row => row.source === 'lfm2.5_fp16')).toBe(true);
    });

    it('keeps a valid partial model rewrite and fills the rest deterministically', () => {
        const output = [
            '```json',
            '{',
            '  "text": "Mira went into the Glass Archive on March 3 carrying two sealed keys.",',
            '  "evidenceIds": ["e1"]',
            '}',
            '```',
        ].join('\n');

        const result = adjudicateLfmExtractiveSmoothingOutput(request, output, 'lfm2.5_q4');

        expect(result.outcome).toBe('partial');
        expect(result.counters.acceptedModelBullets).toBe(1);
        expect(result.counters.fallbackBullets).toBe(1);
        expect(result.bullets.map(row => row.source)).toEqual(['lfm2.5_q4', 'deterministic_fallback']);
        expect(result.issues.some(issue => issue.code === 'too_few_supported_bullets')).toBe(true);
    });

    it('rejects hallucinated names and changed numeric anchors', () => {
        const bullets = parseLfmExtractiveSmoothingOutput(JSON.stringify([
            {
                text: 'Mira and Nora entered the Glass Archive on March 4 with two sealed keys.',
                evidenceIds: ['e1'],
            },
        ]));

        const verified = verifyLfmExtractiveSmoothingBullets(request, bullets);

        expect(verified.acceptedBullets).toHaveLength(0);
        expect(verified.issues).toEqual([
            {
                code: 'unsupported_atom',
                bulletIndex: 0,
                detail: '4, Nora',
            },
        ]);
    });

    it('falls back when the model returns no JSON payload', () => {
        const result = adjudicateLfmExtractiveSmoothingOutput(
            request,
            'Mira probably uncovered an ancient prophecy.',
            'lfm2.5_fp16',
        );

        expect(result.outcome).toBe('fallback');
        expect(result.bullets).toEqual(buildFallbackExtractiveSmoothingBullets(request, 2));
        expect(result.issues.map(issue => issue.code)).toContain('no_json_payload');
    });
});
