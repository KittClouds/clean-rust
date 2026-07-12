/// <reference lib="webworker" />

import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { buildGalaxyScene, type GalaxyInputEdge, type GalaxyRenderableNode, type GalaxyRenderSettings } from './graph-galaxy-engine';

interface GalaxySceneWorkerRequest {
    id: number;
    entities: GalaxyRenderableNode[];
    edges: GalaxyInputEdge[];
    settings: GalaxyRenderSettings;
    entityColors: Record<string, string>;
    graphNodeColors: Record<string, string>;
}

addEventListener('message', ({ data }: MessageEvent<GalaxySceneWorkerRequest>) => {
    try {
        entityColorStore.setColors(data.entityColors as Parameters<typeof entityColorStore.setColors>[0]);
        for (const [kind, hsl] of Object.entries(data.graphNodeColors)) {
            entityColorStore.setGraphNodeColor(kind, hsl);
        }
        postMessage({ id: data.id, scene: buildGalaxyScene(data.entities, data.edges, data.settings) });
    } catch (error) {
        postMessage({ id: data.id, error: error instanceof Error ? error.message : String(error) });
    }
});
