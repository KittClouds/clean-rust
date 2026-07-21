export const GALAXY_RENDERER_V3_AUTHORITY_KEY = 'phoenix.graph.rendererAuthority.v3';

export type GalaxyRendererAuthority = 'legacy-visible' | 'v3-visible';

const AUTHORITIES = new Set<GalaxyRendererAuthority>([
    'legacy-visible',
    'v3-visible',
]);

export function resolveGalaxyRendererAuthority(
    search = typeof location === 'undefined' ? '' : location.search,
    stored = readStoredAuthority(),
): GalaxyRendererAuthority {
    const requested = new URLSearchParams(search).get('graphRenderer');
    if (isGalaxyRendererAuthority(requested)) return requested;
    return stored === 'v3-visible' ? stored : 'v3-visible';
}

export function isGalaxyRendererV3Enabled(authority: GalaxyRendererAuthority): boolean {
    return authority === 'v3-visible';
}

export function isGalaxyRendererLegacyVisible(authority: GalaxyRendererAuthority): boolean {
    return authority === 'legacy-visible';
}

function readStoredAuthority(): string | null {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem(GALAXY_RENDERER_V3_AUTHORITY_KEY);
}

function isGalaxyRendererAuthority(value: unknown): value is GalaxyRendererAuthority {
    return AUTHORITIES.has(value as GalaxyRendererAuthority);
}
