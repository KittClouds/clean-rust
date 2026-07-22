import { describe, expect, it } from 'vitest';

import {
    isGalaxyRendererLegacyVisible,
    isGalaxyRendererV3Enabled,
    resolveGalaxyRendererAuthority,
} from './galaxy-renderer-v3-authority';

describe('Galaxy Renderer V3 authority', () => {
    it('keeps V3 authoritative when storage is absent or invalid', () => {
        expect(resolveGalaxyRendererAuthority('', null)).toBe('v3-visible');
        expect(resolveGalaxyRendererAuthority('?graphRenderer=unknown', 'broken')).toBe('v3-visible');
    });

    it('allows an explicit query flag to override persisted A/B state', () => {
        expect(resolveGalaxyRendererAuthority('?graphRenderer=v3-shadow', 'v3-visible')).toBe('v3-visible');
        expect(resolveGalaxyRendererAuthority('?graphRenderer=legacy-visible', 'v3-visible')).toBe('legacy-visible');
        expect(resolveGalaxyRendererAuthority('?graphRenderer=v3-visible', 'legacy-visible')).toBe('v3-visible');
    });

    it('keeps an explicit persisted promotion and rejects stale demotions across restart', () => {
        expect(resolveGalaxyRendererAuthority('', 'v3-visible')).toBe('v3-visible');
        expect(resolveGalaxyRendererAuthority('', 'v3-shadow')).toBe('v3-visible');
        expect(resolveGalaxyRendererAuthority('', 'legacy-visible')).toBe('v3-visible');
    });

    it('mounts exactly one renderer for every valid authority', () => {
        expect(isGalaxyRendererV3Enabled('v3-visible')).toBe(true);
        expect(isGalaxyRendererV3Enabled('legacy-visible')).toBe(false);
        expect(isGalaxyRendererLegacyVisible('v3-visible')).toBe(false);
        expect(isGalaxyRendererLegacyVisible('legacy-visible')).toBe(true);
    });
});
