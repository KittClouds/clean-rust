import { describe, expect, it } from 'vitest';

import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import { GraphSemanticDerivationContext } from './graph-semantic-derivation-context';

describe('GraphSemanticDerivationContext', () => {
    it('builds narrow indexes once and certifies repeated consumers', () => {
        const snapshot = {
            embeddingGraphPostProcess: {
                targets: [{ targetId: 'target-1' }],
            },
            events: [{ chunkId: 'chunk-1' }, { chunkId: 'chunk-1' }],
            entityAnchors: [
                { id: 'anchor-1', entityId: 'entity-1', noteId: 'note-1' },
                { id: 'anchor-2', entityId: 'entity-2', noteId: 'note-2' },
            ],
            nodes: [{ entityId: 'entity-1' }, { entityId: 'entity-2' }],
        } as unknown as GraphRebuildSnapshot;
        const context = new GraphSemanticDerivationContext(snapshot);

        expect(context.targetRows()).toBe(context.targetRows());
        expect(context.eventChunkIds()).toBe(context.eventChunkIds());
        expect(context.anchorEntityIds()).toBe(context.anchorEntityIds());
        expect(context.nodeEntityIds()).toBe(context.nodeEntityIds());

        expect(context.stats()).toEqual({
            builds: 5,
            entries: 8,
            avoidedBuilds: 4,
            avoidedEntries: 6,
        });
    });
});
