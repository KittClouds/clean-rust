/// <reference lib="webworker" />

import type { GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';
import type { AtlasManifoldMode } from '../services/manifold-atlas.types';
import { entityColorStore } from '../lib/store/entityColorStore';
import {
    buildGalaxyScene,
    type GalaxyRenderSettings,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-engine';
import {
    galaxyScenePacketV2TransferList,
    packGalaxyScenePacketV2,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-packet-v2';
import type { GalaxySceneSourceMode } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-v2';
import { galaxySceneToV2 } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-v2';
import { buildGraphRebuildEmbeddingAtlas } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-rebuild-embedding-atlas';

interface GraphManifoldPrewarmJob {
    manifold: AtlasManifoldMode;
    scene?: {
        settings: GalaxyRenderSettings;
        renderIdentity: string;
        sourceMode: GalaxySceneSourceMode;
    };
}

interface GraphManifoldPrewarmRequest {
    generationId: string;
    snapshot: GraphRebuildSnapshot;
    jobs: GraphManifoldPrewarmJob[];
    entityColors: Record<string, string>;
    graphNodeColors: Record<string, string>;
}

addEventListener('message', ({ data }: MessageEvent<GraphManifoldPrewarmRequest>) => {
    const { generationId, snapshot, jobs } = data;
    try {
        entityColorStore.setColors(data.entityColors as Parameters<typeof entityColorStore.setColors>[0]);
        for (const [kind, hsl] of Object.entries(data.graphNodeColors)) {
            entityColorStore.setGraphNodeColor(kind, hsl);
        }
        for (const { manifold, scene: sceneRequest } of jobs) {
            const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, manifold);
            if (!sceneRequest) {
                postMessage({ generationId, manifold, atlas });
                continue;
            }
            const scene = galaxySceneToV2(
                buildGalaxyScene(atlas.nodes, atlas.edges, sceneRequest.settings),
                sceneRequest.sourceMode,
            );
            const packet = packGalaxyScenePacketV2(scene, {
                generationId,
                authorityReceipt: sceneRequest.renderIdentity,
            });
            postMessage(
                { generationId, manifold, atlas, packet },
                galaxyScenePacketV2TransferList(packet),
            );
        }
        postMessage({ generationId, complete: true });
    } catch (error) {
        postMessage({
            generationId,
            error: error instanceof Error ? error.message : String(error),
        });
    }
});
