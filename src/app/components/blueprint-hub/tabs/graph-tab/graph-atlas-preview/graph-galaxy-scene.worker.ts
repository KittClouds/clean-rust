/// <reference lib="webworker" />

import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { buildGalaxyScene, type GalaxyInputEdge, type GalaxyRenderableNode, type GalaxyRenderSettings } from './graph-galaxy-engine';
import {
    galaxyScenePacketV2TransferList,
    packGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import type { GalaxyScenePacketV2Context } from './graph-galaxy-scene-packet-v2.model';
import { galaxySceneToV2, type GalaxySceneSourceMode } from './graph-galaxy-scene-v2';

interface GalaxySceneWorkerRequest {
    id: number;
    entities: GalaxyRenderableNode[];
    edges: GalaxyInputEdge[];
    settings: GalaxyRenderSettings;
    entityColors: Record<string, string>;
    graphNodeColors: Record<string, string>;
    sourceMode: GalaxySceneSourceMode;
    packetContext: GalaxyScenePacketV2Context;
}

addEventListener('message', ({ data }: MessageEvent<GalaxySceneWorkerRequest>) => {
    try {
        entityColorStore.setColors(data.entityColors as Parameters<typeof entityColorStore.setColors>[0]);
        for (const [kind, hsl] of Object.entries(data.graphNodeColors)) {
            entityColorStore.setGraphNodeColor(kind, hsl);
        }
        const scene = galaxySceneToV2(buildGalaxyScene(data.entities, data.edges, data.settings), data.sourceMode);
        const packet = packGalaxyScenePacketV2(scene, data.packetContext);
        postMessage({ id: data.id, packet }, galaxyScenePacketV2TransferList(packet));
    } catch (error) {
        postMessage({ id: data.id, error: error instanceof Error ? error.message : String(error) });
    }
});
