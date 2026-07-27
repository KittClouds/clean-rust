import { describe, expect, it } from 'vitest';

import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { resolveGalaxyNodePaletteSlot } from './graph-galaxy-engine';
import {
    GALAXY_NODE_PALETTE_UNBOUND,
    galaxyEntityPaletteSlot,
    galaxyGraphPaletteSlot,
    refreshGalaxyNodePaletteRgba8,
} from './graph-galaxy-node-palette';

describe('Galaxy Renderer V3 node palette', () => {
    it('binds entity, episode, and chunk nodes to explicit compact slots', () => {
        expect(resolveGalaxyNodePaletteSlot({ id: 'character:ryan', label: 'Ryan', kind: 'CHARACTER' }))
            .toBe(galaxyEntityPaletteSlot('CHARACTER'));
        expect(resolveGalaxyNodePaletteSlot({
            id: 'episode:1',
            label: 'Episode 1',
            kind: 'structure',
            metadata: { graphKind: 'episode' },
        })).toBe(galaxyGraphPaletteSlot('episode'));
        expect(resolveGalaxyNodePaletteSlot({
            id: 'chunk:1',
            label: 'Chunk 1',
            kind: 'leaf',
            metadata: { sourceType: 'chunk' },
        })).toBe(galaxyGraphPaletteSlot('chunk'));
        expect(resolveGalaxyNodePaletteSlot({ id: 'custom:1', label: 'Custom', kind: 'not-palette-bound' }))
            .toBe(GALAXY_NODE_PALETTE_UNBOUND);
    });

    it('rewrites one prepared RGBA allocation and preserves unbound packed colors', () => {
        const originalCharacter = entityColorStore.getRawHsl('CHARACTER');
        const originalEpisode = entityColorStore.getRawGraphNodeHsl('episode');
        const originalChunk = entityColorStore.getRawGraphNodeHsl('chunk');
        entityColorStore.setColor('CHARACTER', '240 100% 50%');
        entityColorStore.setGraphNodeColor('episode', '120 100% 50%');
        entityColorStore.setGraphNodeColor('chunk', '0 100% 50%');
        try {
            const target = new Uint8Array(16);
            const packed = new Uint8Array([
                1, 2, 3, 255,
                4, 5, 6, 255,
                7, 8, 9, 255,
                10, 11, 12, 255,
            ]);
            const slots = new Uint8Array([
                galaxyEntityPaletteSlot('CHARACTER'),
                galaxyGraphPaletteSlot('episode'),
                galaxyGraphPaletteSlot('chunk'),
                GALAXY_NODE_PALETTE_UNBOUND,
            ]);

            refreshGalaxyNodePaletteRgba8(target, packed, slots, 4);

            expect(Array.from(target)).toEqual([
                0, 0, 255, 255,
                0, 255, 0, 255,
                255, 0, 0, 255,
                10, 11, 12, 255,
            ]);
        } finally {
            entityColorStore.setColor('CHARACTER', originalCharacter);
            entityColorStore.setGraphNodeColor('episode', originalEpisode);
            entityColorStore.setGraphNodeColor('chunk', originalChunk);
        }
    });
});
