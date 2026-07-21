import type { AtlasManifoldMode } from '../../../../../services/manifold-atlas.types';
import { mergeGalaxySettings, type GalaxyRenderSettings } from './graph-galaxy-engine';
import { galaxySceneCompilationSettingsKey } from './graph-galaxy-scene-compilation-key';
import type { GalaxySceneSourceMode } from './graph-galaxy-scene-v2';

export interface GalaxySceneIdentityInput {
    graphIdentity: string;
    sourceMode: GalaxySceneSourceMode;
    manifold: AtlasManifoldMode;
    settings: GalaxyRenderSettings;
    canvasLens: string;
    graphKindFilter: string;
    traceIdentity?: string;
}

export function galaxySceneIdentity(input: GalaxySceneIdentityInput): string {
    const settings = mergeGalaxySettings({
        ...input.settings,
        sourceMode: input.sourceMode,
    });
    return [
        input.graphIdentity,
        input.sourceMode,
        input.manifold,
        galaxySceneCompilationSettingsKey(settings),
        input.canvasLens,
        input.graphKindFilter,
        input.traceIdentity || '',
    ].join('\u0000');
}
