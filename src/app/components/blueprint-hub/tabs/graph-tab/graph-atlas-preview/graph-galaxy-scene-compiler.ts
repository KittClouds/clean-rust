import type { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import type { PhoenixGalaxySceneRequest } from '../../../../../services/phoenix-galaxy-scene.model';
import { DEFAULT_GRAPH_NODE_COLORS, entityColorStore } from '../../../../../lib/store/entityColorStore';
import {
    buildGalaxyScene,
    hasRelationControlNodes,
    hslToRgb,
    resolveGalaxyNodeColorHsl,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
    type GalaxyRenderSettings,
    type GalaxyScene,
} from './graph-galaxy-engine';
import { graphGalaxyRuntimeMeter } from './graph-galaxy-runtime-meter';

let warnedNativeFallback = false;
let warnedWorkerFallback = false;
const sceneCache = new Map<string, Promise<GalaxyScene>>();
const MAX_CACHED_SCENES = 4;
let sceneWorker: Worker | null | undefined;
let nextWorkerRequestId = 0;
const workerRequests = new Map<number, {
    resolve: (scene: GalaxyScene) => void;
    reject: (error: Error) => void;
}>();

entityColorStore.subscribe(() => sceneCache.clear());

export async function compileGalaxyScene(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
    renderIdentity = '',
): Promise<GalaxyScene> {
    const cacheKey = renderIdentity ? `${renderIdentity}\u0000${JSON.stringify(settings)}` : '';
    const cached = cacheKey ? sceneCache.get(cacheKey) : undefined;
    if (cached) {
        sceneCache.delete(cacheKey);
        sceneCache.set(cacheKey, cached);
        graphGalaxyRuntimeMeter.recordCompilerSource('cache');
        return cached;
    }
    const pending = compileChangedGalaxyScene(backend, entities, edges, settings);
    if (cacheKey) {
        sceneCache.set(cacheKey, pending);
        while (sceneCache.size > MAX_CACHED_SCENES) sceneCache.delete(sceneCache.keys().next().value!);
        pending.catch(() => sceneCache.delete(cacheKey));
    }
    return pending;
}

async function compileChangedGalaxyScene(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
): Promise<GalaxyScene> {
    const hasGalaxyMetadata = entities.some((entity) => Boolean(entity.metadata?.galaxyId));
    const hasAtlasLayout = entities.some((entity) =>
        Number.isFinite(entity.atlasX) && Number.isFinite(entity.atlasY) && Number.isFinite(entity.atlasZ),
    );
    const hasRelationControls = hasRelationControlNodes(entities);
    if (backend.target !== 'native' || hasGalaxyMetadata || hasAtlasLayout || hasRelationControls || settings.layoutMode !== 'single') {
        try {
            const scene = await compileGalaxySceneInWorker(entities, edges, settings);
            if (scene) {
                graphGalaxyRuntimeMeter.recordCompilerSource('worker');
                return scene;
            }
        } catch (error) {
            if (!warnedWorkerFallback) {
                warnedWorkerFallback = true;
                console.warn('[GraphGalaxyScene] Scene worker unavailable; using local exact compiler.', error);
            }
        }
        graphGalaxyRuntimeMeter.recordCompilerSource('local');
        return buildGalaxyScene(entities, edges, settings);
    }
    try {
        const entityById = new Map(entities.map((entity) => [entity.id, entity] as const));
        const scene = await backend.compileGalaxyScene({
            entities: entities.map((entity) => ({
                id: entity.id,
                label: entity.label,
                kind: entity.kind,
                totalMentions: entity.totalMentions,
                atlasX: entity.atlasX,
                atlasY: entity.atlasY,
                atlasZ: entity.atlasZ,
                colorHsl: resolveGalaxyNodeColorHsl(entity),
            })),
            edges,
            settings: {
                edgeLength: settings.edgeLength,
                nodeDistance: settings.nodeDistance,
            },
        } satisfies PhoenixGalaxySceneRequest);
        graphGalaxyRuntimeMeter.recordCompilerSource('native');
        return {
            nodes: scene.nodes.map((node) => {
                const source = entityById.get(node.entity.id);
                const color = hslToRgb(source ? resolveGalaxyNodeColorHsl(source) : resolveGalaxyNodeColorHsl(node.entity));
                return {
                    ...node,
                    ...color,
                    sx: 0,
                    sy: 0,
                    depth: 0,
                    galaxyOpacity: 1,
                };
            }),
            links: scene.links.map((link) => ({ ...link })),
            layoutMode: 'single',
            groups: [],
        };
    } catch (error) {
        if (!warnedNativeFallback) {
            warnedNativeFallback = true;
            console.warn('[GraphGalaxyScene] Native scene compiler unavailable; using local scene builder.', error);
        }
        graphGalaxyRuntimeMeter.recordCompilerSource('fallback');
        return buildGalaxyScene(entities, edges, settings);
    }
}

function compileGalaxySceneInWorker(
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
): Promise<GalaxyScene | null> {
    const worker = galaxySceneWorker();
    if (!worker) return Promise.resolve(null);
    const id = ++nextWorkerRequestId;
    const graphNodeColors = Object.fromEntries(
        Object.keys(DEFAULT_GRAPH_NODE_COLORS).map((kind) => [kind, entityColorStore.getRawGraphNodeHsl(kind)]),
    );
    return new Promise<GalaxyScene>((resolve, reject) => {
        workerRequests.set(id, { resolve, reject });
        worker.postMessage({
            id,
            entities,
            edges,
            settings,
            entityColors: entityColorStore.getSnapshot(),
            graphNodeColors,
        });
    });
}

function galaxySceneWorker(): Worker | null {
    if (sceneWorker !== undefined) return sceneWorker;
    if (typeof Worker === 'undefined') {
        sceneWorker = null;
        return null;
    }
    try {
        const worker = new Worker(new URL('./graph-galaxy-scene.worker', import.meta.url), { type: 'module' });
        worker.onmessage = ({ data }: MessageEvent<{ id: number; scene?: GalaxyScene; error?: string }>) => {
            const pending = workerRequests.get(data.id);
            if (!pending) return;
            workerRequests.delete(data.id);
            data.scene ? pending.resolve(data.scene) : pending.reject(new Error(data.error || 'Scene worker failed'));
        };
        worker.onerror = (event) => {
            const error = new Error(event.message || 'Scene worker failed');
            for (const pending of workerRequests.values()) pending.reject(error);
            workerRequests.clear();
            worker.terminate();
            sceneWorker = null;
        };
        sceneWorker = worker;
    } catch {
        sceneWorker = null;
    }
    return sceneWorker;
}
