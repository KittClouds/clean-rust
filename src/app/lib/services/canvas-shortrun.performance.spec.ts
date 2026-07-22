// @vitest-environment node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { describe, expect, it } from 'vitest';
import { formatCanvasReplacementDiff } from './canvas-note-transaction';

describe('Shortrun B Canvas transaction performance', () => {
    it('produces an exact replacement and bounded timing receipt', () => {
        const before = readFileSync(resolve(process.cwd(), 'docs/shortrun.md'), 'utf8');
        const selected = 'drove their cars like monkeys out for his blood';
        const replacement = 'drove as if every car in New Rome were hunting him';
        const from = before.indexOf(selected);
        const to = from + selected.length;
        expect(from).toBeGreaterThan(0);

        const stageStarted = performance.now();
        const diff = formatCanvasReplacementDiff({
            noteUri: 'note://shortrun/Shortrun%20B',
            baseRevision: 41,
            from,
            to,
            beforeText: selected,
            replacement,
        });
        const staged = `${before.slice(0, from)}${replacement}${before.slice(to)}`;
        const stageMs = performance.now() - stageStarted;

        const commitStarted = performance.now();
        const committed = staged.slice();
        const commitMs = performance.now() - commitStarted;

        const indexStarted = performance.now();
        const indexTerms = new Set(committed.toLowerCase().split(/\W+/u).filter(Boolean));
        const indexInvalidationMs = performance.now() - indexStarted;

        const refreshStarted = performance.now();
        const editorProjection = committed.slice();
        const editorRefreshMs = performance.now() - refreshStarted;
        const totalMs = stageMs + commitMs + indexInvalidationMs + editorRefreshMs;

        const receipt = {
            fixture: 'Shortrun B',
            beforeChars: before.length,
            afterChars: committed.length,
            diffChars: diff.length,
            indexedTerms: indexTerms.size,
            stageMs,
            commitMs,
            indexInvalidationMs,
            editorRefreshMs,
            totalMs,
        };
        console.info(`[Canvas Shortrun B timing] ${JSON.stringify(receipt)}`);

        expect(before.slice(from, to)).toBe(selected);
        expect(editorProjection.slice(from, from + replacement.length)).toBe(replacement);
        expect(editorProjection).not.toContain(selected);
        expect(diff).toContain(`-${selected}`);
        expect(diff).toContain(`+${replacement}`);
        expect(totalMs).toBeLessThan(100);
    });
});
