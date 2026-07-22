import { describe, expect, it } from 'vitest';

import { mergeGalaxySettings } from '../graph-galaxy-engine';
import { galaxySceneCompilationSettingsKey } from '../graph-galaxy-scene-compilation-key';
import { galaxyRendererV3SettingsRequireCompilation } from './galaxy-renderer-v3-input-adapter';

describe('Galaxy Renderer V3 settings boundary', () => {
    it('keeps interaction and presentation controls on the resident packet', () => {
        const base = mergeGalaxySettings({
            layoutMode: 'lorentzTree',
            nodeDragMode: 'stretch',
            edgeMode: 'curved',
        });
        const presentationOnly = {
            ...base,
            nodeDragMode: 'pin' as const,
            edgeMode: 'hidden' as const,
        };

        expect(galaxyRendererV3SettingsRequireCompilation(base, presentationOnly, 'graph')).toBe(false);
    });

    it.each([
        ['layout', { layoutMode: 'hopfProjection' as const }],
        ['node distance', { nodeDistance: 2.25 }],
        ['edge length', { edgeLength: 1.75 }],
        ['curve geometry', { edgeCurveStrength: 0.42 }],
        ['embedding topology', { embeddingTopologyMode: 'clusters' as const }],
    ])('recompiles when %s changes', (_label, patch) => {
        const base = mergeGalaxySettings({ layoutMode: 'lorentzTree' });

        expect(galaxyRendererV3SettingsRequireCompilation(base, { ...base, ...patch }, 'graph')).toBe(true);
    });

    it('binds every manifold geometry variant into its authority identity', () => {
        const caps = mergeGalaxySettings({ layoutMode: 'lorentzTree' });
        const hopf = mergeGalaxySettings({ layoutMode: 'hopfProjection' });

        expect(galaxySceneCompilationSettingsKey(caps)).not.toBe(galaxySceneCompilationSettingsKey(hopf));
    });
});
