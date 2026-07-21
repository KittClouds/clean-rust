import { mergeGalaxySettings, type GalaxyRenderSettings } from '../graph-galaxy-engine';
import { galaxySceneCompilationSettingsKey } from '../graph-galaxy-scene-compilation-key';
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

export function galaxyRendererV3SettingsRequireCompilation(
    previous: Partial<GalaxyRenderSettings> | null | undefined,
    current: Partial<GalaxyRenderSettings> | null | undefined,
    sourceMode: GalaxySceneSourceMode,
): boolean {
    return galaxySceneCompilationSettingsKey(normalizeGalaxyRendererV3Settings(previous, sourceMode))
        !== galaxySceneCompilationSettingsKey(normalizeGalaxyRendererV3Settings(current, sourceMode));
}
