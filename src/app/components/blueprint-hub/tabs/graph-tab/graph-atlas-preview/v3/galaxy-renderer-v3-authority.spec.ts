import { describe, expect, it } from 'vitest';

import {
    isGalaxyRendererLegacyVisible,
    isGalaxyRendererV3Enabled,
    resolveGalaxyRendererAuthority,
} from './galaxy-renderer-v3-authority';

describe('Galaxy Renderer V3 authority', () => {
    it('keeps legacy as the immutable default', () => {
        expect(resolveGalaxyRendererAuthority('', null)).toBe('legacy-visible');
        expect(resolveGalaxyRendererAuthority('?graphRenderer=unknown', 'broken')).toBe('legacy-visible');
    });

    it('allows an explicit query flag to override persisted A/B state', () => {
        expect(resolveGalaxyRendererAuthority('?graphRenderer=v3-shadow', 'v3-visible')).toBe('v3-shadow');
        expect(resolveGalaxyRendererAuthority('?graphRenderer=legacy-visible', 'v3-visible')).toBe('legacy-visible');
        expect(resolveGalaxyRendererAuthority('?graphRenderer=v3-visible', 'legacy-visible')).toBe('v3-visible');
    });

    it('downgrades a persisted visible flag to shadow until promotion is explicit', () => {
        expect(resolveGalaxyRendererAuthority('', 'v3-visible')).toBe('v3-shadow');
    });

    it('never aliases a V3 failure mode to the legacy renderer', () => {
        expect(isGalaxyRendererV3Enabled('v3-shadow')).toBe(true);
        expect(isGalaxyRendererV3Enabled('v3-visible')).toBe(true);
        expect(isGalaxyRendererLegacyVisible('v3-shadow')).toBe(true);
        expect(isGalaxyRendererLegacyVisible('v3-visible')).toBe(false);
    });
});
