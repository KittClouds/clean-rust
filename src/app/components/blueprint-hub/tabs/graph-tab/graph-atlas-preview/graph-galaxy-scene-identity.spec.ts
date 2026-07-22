import { describe, expect, it } from 'vitest';

import { mergeGalaxySettings } from './graph-galaxy-engine';
import { galaxySceneIdentity } from './graph-galaxy-scene-identity';

describe('galaxy scene identity', () => {
    it('binds manifold geometry while ignoring presentation-only controls', () => {
        const caps = identity(mergeGalaxySettings({ layoutMode: 'lorentzTree', nodeDragMode: 'stretch' }));
        const capsPinned = identity(mergeGalaxySettings({ layoutMode: 'lorentzTree', nodeDragMode: 'pin' }));
        const hopf = identity(mergeGalaxySettings({ layoutMode: 'hopfProjection', nodeDragMode: 'pin' }));

        expect(capsPinned).toBe(caps);
        expect(hopf).not.toBe(caps);
    });

    it('takes source authority from the scene boundary instead of stale UI settings', () => {
        const stale = mergeGalaxySettings({ layoutMode: 'hopfProjection', sourceMode: 'entities' });
        const current = mergeGalaxySettings({ layoutMode: 'hopfProjection', sourceMode: 'embeddings' });

        expect(identity(stale)).toBe(identity(current));
    });
});

function identity(settings: ReturnType<typeof mergeGalaxySettings>): string {
    return galaxySceneIdentity({
        graphIdentity: 'generation:a',
        sourceMode: 'embeddings',
        manifold: settings.layoutMode === 'hopfProjection' ? 'hopf' : 'lorentz',
        settings,
        canvasLens: 'entities',
        graphKindFilter: 'all',
    });
}
