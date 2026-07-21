import type { GalaxyRenderSettings } from './graph-galaxy-engine';

/** Fields that alter packed scene geometry and therefore require a new receipt. */
export function galaxySceneCompilationSettingsKey(settings: GalaxyRenderSettings): string {
    return JSON.stringify({
        layoutMode: settings.layoutMode,
        sourceMode: settings.sourceMode,
        embeddingTopologyMode: settings.embeddingTopologyMode,
        nodeDistance: settings.nodeDistance,
        edgeLength: settings.edgeLength,
        edgeCurveStrength: settings.edgeCurveStrength,
    });
}
