import { describe, expect, it } from 'vitest';

import { graphAnalysisResidentDocumentRequest, utf8MentionOffsets } from './phoenix-taurpc-bridge';

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
        const compact = graphAnalysisResidentDocumentRequest(
            request,
            new Map([['note-1', { text: 'Kai met Hazel.', textHash: 'text:abc' }]]),
            { runHandle: 'graph-run:1', signature: 'note-1:text:abc' },
        );

        expect(compact).toMatchObject({
            runHandle: 'graph-run:1',
            documents: [{ noteId: 'note-1', text: null, textHash: 'text:abc' }],
        });
    });
});
