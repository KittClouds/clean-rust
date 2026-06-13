import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { dynamicChunksForNote } from './graph-rebuild.service';
import {
    buildGraphRebuildChunksFromRanges,
    summarizeMeaningFrame,
} from './graph-rebuild-meaning-frames';

const KAI_ROWAN_SMOKE = `
Kai looked at Cael first. "This one is official continuity work. The chain exists, even cracked.
Joint Chiefs, Nemo, Atlas, Allied Table. Operators are signed to that table."

Soleya answered from Halcyon. "Clearing Redwater or Black Cypress may require Phantom or Warden force.
Expanding Allied Table city coverage is possible if local continuity has already failed."

Rowan came to stand behind Hazel while Baton Rouge and Lower Mississippi filled the board.
Canton Recovery had its name on too many doors, and the military files mentioned militia escorts.
Operator Office attached the packet before Red Mesa opened in the center.
`;

describe('graph rebuild meaning-frame chunking', () => {
    it('enriches native ranges without changing their source offsets', () => {
        const text = 'Amara entered the archive.\n\nThe report shows the bridge failed because the cable moved.';
        const split = text.indexOf('The report');
        const chunks = buildGraphRebuildChunksFromRanges('native-ranges', text, [
            { start: 0, end: split - 2, ordinal: 0 },
            { start: split, end: text.length, ordinal: 1 },
        ]);

        expect(chunks.map((chunk) => [chunk.start, chunk.end])).toEqual([
            [0, split - 2],
            [split, text.length],
        ]);
        expect(chunks.every((chunk) => chunk.splitReason === 'native-sentence-window')).toBe(true);
        expect(chunks[1].meaningFrame?.evidenceCues.length).toBeGreaterThan(0);
    });

    it('keeps note-sized chunks carrying role, cue, and entity-prior frames', () => {
        const chunks = dynamicChunksForNote({ id: 'kai-rowan', markdownContent: KAI_ROWAN_SMOKE, content: '' });
        const priors = chunks.flatMap((chunk) => chunk.meaningFrame?.entityPriors || []);

        expect(chunks).toHaveLength(1);
        expect(chunks[0].meaningFrame?.role).toBe('authority_chain');
        expect(chunks[0].meaningFrame?.authorityCues).toEqual(expect.arrayContaining(['chiefs', 'table', 'operator']));
        expect(chunks.every((chunk) => chunk.source === 'dynamic-chunking')).toBe(true);
        expect(summarizeMeaningFrame(chunks[0].meaningFrame)).toContain('chunk_role:authority_chain');
        expect(priors).toEqual(expect.arrayContaining([
            expect.objectContaining({ surface: 'Allied Table', likelyKinds: expect.arrayContaining(['NETWORK']) }),
            expect.objectContaining({ surface: 'Operator Office', likelyKinds: expect.arrayContaining(['NETWORK']) }),
            expect.objectContaining({ surface: 'Baton Rouge', likelyKinds: expect.arrayContaining(['LOCATION']) }),
            expect.objectContaining({ surface: 'Lower Mississippi', likelyKinds: expect.arrayContaining(['LOCATION']) }),
            expect.objectContaining({ surface: 'military', likelyKinds: ['NETWORK'] }),
            expect.objectContaining({ surface: 'militia', likelyKinds: ['NETWORK'] }),
        ]));
    });

    it('CLI-smokes shortrun and mother2 with bounded adaptive chunk counts', () => {
        const shortrun = readFileSync(new URL('../../../docs/shortrun.md', import.meta.url), 'utf8');
        const mother2 = readFileSync(new URL('../../../docs/mother2.md', import.meta.url), 'utf8');
        const shortChunks = dynamicChunksForNote({ id: 'shortrun', markdownContent: shortrun, content: '' });
        const motherChunks = dynamicChunksForNote({ id: 'mother2', markdownContent: mother2, content: '' });

        expect(shortChunks.length).toBeGreaterThan(0);
        expect(shortChunks.length).toBeLessThan(180);
        expect(motherChunks.length).toBeGreaterThan(0);
        expect(motherChunks.length).toBeLessThan(900);
        expect([...shortChunks, ...motherChunks].every((chunk) => Boolean(chunk.meaningFrame))).toBe(true);
        expect([...shortChunks, ...motherChunks].every((chunk) => chunk.end > chunk.start)).toBe(true);
    });
});
