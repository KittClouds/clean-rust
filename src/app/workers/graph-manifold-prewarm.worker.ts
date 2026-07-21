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
    publishAtlas: boolean;
    shareSearchIndex: boolean;
    scene?: {
        settings: GalaxyRenderSettings;
        renderIdentity: string;
        sourceMode: GalaxySceneSourceMode;
    };
}

interface GraphManifoldPrewarmRequest {
    requestId: number;
    generationId: string;
    snapshot?: GraphRebuildSnapshot;
    jobs: GraphManifoldPrewarmJob[];
    entityColors: Record<string, string>;
    graphNodeColors: Record<string, string>;
}

let residentGenerationId = '';
let residentSnapshot: GraphRebuildSnapshot | null = null;

addEventListener('message', ({ data }: MessageEvent<GraphManifoldPrewarmRequest>) => {
    void processRequest(data);
});

async function processRequest(data: GraphManifoldPrewarmRequest): Promise<void> {
    const { requestId, generationId, jobs } = data;
    try {
        if (data.snapshot) {
            residentGenerationId = generationId;
            residentSnapshot = data.snapshot;
        }
        if (!residentSnapshot || residentGenerationId !== generationId) {
            throw new Error(`Graph manifold prewarm snapshot ${generationId} is not resident.`);
        }
        entityColorStore.setColors(data.entityColors as Parameters<typeof entityColorStore.setColors>[0]);
        for (const [kind, hsl] of Object.entries(data.graphNodeColors)) {
            entityColorStore.setGraphNodeColor(kind, hsl);
        }
        for (const { manifold, publishAtlas, shareSearchIndex, scene: sceneRequest } of jobs) {
            const atlas = buildGraphRebuildEmbeddingAtlas(residentSnapshot, manifold);
            const publishedAtlas = publishAtlas
                ? (shareSearchIndex ? { ...atlas, searchIndex: [] } : atlas)
                : undefined;
            if (!sceneRequest) {
                postMessage({ requestId, generationId, manifold, atlas: publishedAtlas });
                await yieldToPriorityRequests();
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
                { requestId, generationId, manifold, atlas: publishedAtlas, packet },
                galaxyScenePacketV2TransferList(packet),
            );
            await yieldToPriorityRequests();
        }
        postMessage({ requestId, generationId, complete: true });
    } catch (error) {
        postMessage({
            requestId,
            generationId,
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

function yieldToPriorityRequests(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}
