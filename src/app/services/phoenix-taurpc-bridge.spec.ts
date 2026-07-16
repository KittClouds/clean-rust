import { describe, expect, it } from 'vitest';

import {
    canonicalRewardObserverDelayMs,
    prepareGraphAnalysisResidentRequest,
    utf8MentionOffsets,
} from './phoenix-taurpc-bridge';

describe('Phoenix TauRPC compact mention projection', () => {
    it('maps UTF-8 byte ranges to JavaScript UTF-16 offsets without changing wire ranges', () => {
        const offsets = utf8MentionOffsets('Aé😀Z', [{ start: 1, end: 7 }]);

        expect(offsets.get(1)).toBe(1);
        expect(offsets.get(7)).toBe(4);
    });

    it('attaches analysis to the matching resident graph run without retransmitting text', () => {
        const request = {
            snapshot: { id: 'snapshot-1' },
            documents: [{ noteId: 'note-1', text: 'Kai met Hazel.' }],
        };
        const prepared = prepareGraphAnalysisResidentRequest(
            request,
            new Map([['note-1', { text: 'Kai met Hazel.', textHash: 'text:abc' }]]),
            { runHandle: 'graph-run:1', signature: 'note-1:text:abc' },
        );

        expect(prepared).toEqual({
            request: {
                snapshot: { id: 'snapshot-1' },
                runHandle: 'graph-run:1',
                documents: [{ noteId: 'note-1', text: null, textHash: 'text:abc' }],
            },
            pendingRun: null,
        });
    });

    it('retains an unmatched discovery lease for its matching analysis request', () => {
        const pending = { runHandle: 'graph-run:2', signature: 'note-2:text:def' };
        const request = { documents: [{ noteId: 'note-1', text: 'Kai met Hazel.' }] };

        expect(prepareGraphAnalysisResidentRequest(request, new Map(), pending)).toEqual({
            request,
            pendingRun: pending,
        });
    });
});

describe('canonical reward horizon scheduling', () => {
    it('sleeps to the exact pending horizon and polls conservatively when none is installed', () => {
        expect(canonicalRewardObserverDelayMs({ nextEligibleAt: 12_000 }, 10_000)).toBe(2_000);
        expect(canonicalRewardObserverDelayMs({ nextEligibleAt: 9_000 }, 10_000)).toBe(1_000);
        expect(canonicalRewardObserverDelayMs({ nextEligibleAt: null }, 10_000)).toBe(300_000);
    });
});
