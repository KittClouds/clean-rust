import { describe, expect, it } from 'vitest';

import { mergeGalaxySettings } from './graph-galaxy-engine';
import {
    canGraphGalaxyCanvasHoldSurface,
    galaxySettingsNeedSceneRebuild,
} from './graph-galaxy-canvas.component';

describe('GraphGalaxyCanvasComponent settings rebuild routing', () => {
    it('rebuilds the compiled scene when topology lens changes', () => {
        const previous = mergeGalaxySettings({ embeddingTopologyMode: 'off' });
        const current = mergeGalaxySettings({ embeddingTopologyMode: 'regions' });

        expect(galaxySettingsNeedSceneRebuild(previous, current)).toBe(true);
    });

    it('rebuilds the compiled scene when Atlas source mode changes', () => {
        const previous = mergeGalaxySettings({ sourceMode: 'graph' });
        const current = mergeGalaxySettings({ sourceMode: 'embeddings' });

        expect(galaxySettingsNeedSceneRebuild(previous, current)).toBe(true);
    });

    it('keeps renderer-only settings on the cheap path', () => {
        const previous = mergeGalaxySettings({ labelMode: 'hover' });
        const current = mergeGalaxySettings({ labelMode: 'always' });

        expect(galaxySettingsNeedSceneRebuild(previous, current)).toBe(false);
    });
});

describe('GraphGalaxyCanvasComponent surface lifecycle gate', () => {
    const active = {
        destroyed: false,
        documentVisible: true,
        isVisible: true,
        surfaceActive: true,
    };

    it('allows a WebGL surface only when the document, viewport, and graph panel are active', () => {
        expect(canGraphGalaxyCanvasHoldSurface(active)).toBe(true);
    });

    it('releases hidden or inactive graph surfaces instead of keeping GPU work alive', () => {
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, isVisible: false })).toBe(false);
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, surfaceActive: false })).toBe(false);
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, documentVisible: false })).toBe(false);
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, destroyed: true })).toBe(false);
    });
});
