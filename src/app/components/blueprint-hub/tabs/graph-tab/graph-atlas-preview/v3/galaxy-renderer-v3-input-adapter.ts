import { mergeGalaxySettings, type GalaxyRenderSettings } from '../graph-galaxy-engine';
import type { GalaxySceneSourceMode } from '../graph-galaxy-scene-v2';

/**
 * The only main-thread runtime adapter from current Atlas controls into V3.
 * V3 owns no legacy renderer, scene cache, camera, or mutable render resource.
 */
export function normalizeGalaxyRendererV3Settings(
    settings: Partial<GalaxyRenderSettings> | null | undefined,
    sourceMode: GalaxySceneSourceMode,
): GalaxyRenderSettings {
    return mergeGalaxySettings({ ...settings, sourceMode });
}
