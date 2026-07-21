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
import {
    GalaxyScenePacketV2SharedPagePool,
    unpackGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import type { GalaxyScenePacketV2 } from './graph-galaxy-scene-packet-v2.model';
import { galaxySceneCompilationSettingsKey } from './graph-galaxy-scene-compilation-key';
import {
    galaxySceneToV2,
    type GalaxySceneSourceMode,
    type GalaxySceneV2,
} from './graph-galaxy-scene-v2';

let warnedNativeFallback = false;
let warnedWorkerFallback = false;
const sceneCache = new Map<string, Promise<GalaxySceneV2>>();
const sceneCacheWeights = new Map<string, number>();
const sharedScenePages = new GalaxyScenePacketV2SharedPagePool();
// Retain only the active expanded scene. Other manifolds are rebuilt through the
// authoritative worker lane instead of multiplying corpus-sized browser state.
const MAX_CACHED_SCENES = 1;
const MAX_CACHED_SCENE_ELEMENTS = 40_000;
let sceneWorker: Worker | null | undefined;
let nextWorkerRequestId = 0;
const workerRequests = new Map<number, {
    resolve: (scene: GalaxySceneV2) => void;
    reject: (error: Error) => void;
}>();

entityColorStore.subscribe(() => {
    sceneCache.clear();
    sceneCacheWeights.clear();
});

export function releaseGalaxySceneCompilerGeneration(generationId: string): number {
    if (!generationId) return 0;
    const prefix = `${generationId}\u0000`;
    let released = 0;
    for (const key of [...sceneCache.keys()]) {
        if (!key.startsWith(prefix)) continue;
        sceneCache.delete(key);
        sceneCacheWeights.delete(key);
        released += 1;
    }
    return released;
}

export async function compileGalaxyScene(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
    renderIdentity = '',
    sourceMode: GalaxySceneSourceMode = 'entities',
): Promise<GalaxySceneV2> {
    return compileGalaxySceneWithPolicy(backend, entities, edges, settings, renderIdentity, sourceMode, false);
}

export { galaxySceneCompilationSettingsKey } from './graph-galaxy-scene-compilation-key';

export async function compileAuthoritativeGalaxyScene(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
    renderIdentity: string,
    sourceMode: GalaxySceneSourceMode,
): Promise<GalaxySceneV2> {
    if (!renderIdentity) throw new Error('Authoritative packed scene compilation requires a render identity.');
    return compileGalaxySceneWithPolicy(backend, entities, edges, settings, renderIdentity, sourceMode, true);
}

export function seedAuthoritativeGalaxyScenePacket(
    packet: GalaxyScenePacketV2,
    settings: GalaxyRenderSettings,
    renderIdentity: string,
    sourceMode: GalaxySceneSourceMode,
): GalaxySceneV2 {
    if (!renderIdentity) throw new Error('Authoritative packed scene installation requires a render identity.');
    if (packet.manifest.generationId !== galaxySceneGenerationId(renderIdentity)) {
        throw new Error('Authoritative packed scene generation does not match its render identity.');
    }
    if (packet.manifest.authorityReceipt !== renderIdentity) {
        throw new Error('Authoritative packed scene receipt does not match its render identity.');
    }
    if (packet.manifest.sourceMode !== sourceMode) {
        throw new Error('Authoritative packed scene source mode does not match its cache lane.');
    }
    const cacheKey = galaxySceneCacheKey(renderIdentity, sourceMode, settings);
    const scene = unpackGalaxyScenePacketV2(sharedScenePages.reuse(packet));
    const resident = Promise.resolve(scene);
    evictStaleSceneVariant(renderIdentity, cacheKey);
    sceneCache.set(cacheKey, resident);
    sceneCacheWeights.set(cacheKey, scene.ids.length + scene.edgePairs.length / 2);
    trimSceneCache(cacheKey);
    return scene;
}

async function compileGalaxySceneWithPolicy(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
    renderIdentity: string,
    sourceMode: GalaxySceneSourceMode,
    failClosed: boolean,
): Promise<GalaxySceneV2> {
    const cacheKey = renderIdentity ? galaxySceneCacheKey(renderIdentity, sourceMode, settings) : '';
    const cached = cacheKey ? sceneCache.get(cacheKey) : undefined;
    if (cached) {
        const weight = sceneCacheWeights.get(cacheKey) || 0;
        sceneCache.delete(cacheKey);
        sceneCacheWeights.delete(cacheKey);
        sceneCache.set(cacheKey, cached);
        sceneCacheWeights.set(cacheKey, weight);
        graphGalaxyRuntimeMeter.recordCompilerSource('cache');
        return cached;
    }
    const pending = compileChangedGalaxyScene(backend, entities, edges, settings, sourceMode, renderIdentity, failClosed);
    if (cacheKey) {
        evictStaleSceneVariant(renderIdentity, cacheKey);
        sceneCache.set(cacheKey, pending);
        sceneCacheWeights.set(cacheKey, 0);
        trimSceneCache(cacheKey);
        pending.then((scene) => {
            if (sceneCache.get(cacheKey) !== pending) return;
            sceneCacheWeights.set(cacheKey, scene.ids.length + scene.edgePairs.length / 2);
            trimSceneCache(cacheKey);
        }).catch(() => {
            sceneCache.delete(cacheKey);
            sceneCacheWeights.delete(cacheKey);
        });
    }
    return pending;
}

function galaxySceneCacheKey(
    renderIdentity: string,
    sourceMode: GalaxySceneSourceMode,
    settings: GalaxyRenderSettings,
): string {
    return `${renderIdentity}\u0000${sourceMode}\u0000${galaxySceneCompilationSettingsKey(settings)}`;
}

function evictStaleSceneVariant(renderIdentity: string, nextKey: string): void {
    const prefix = `${renderIdentity}\u0000`;
    for (const key of sceneCache.keys()) {
        if (key !== nextKey && key.startsWith(prefix)) {
            sceneCache.delete(key);
            sceneCacheWeights.delete(key);
        }
    }
}

function trimSceneCache(currentKey: string): void {
    while (
        sceneCache.size > 1 &&
        (sceneCache.size > MAX_CACHED_SCENES || cachedSceneElementCount() > MAX_CACHED_SCENE_ELEMENTS)
    ) {
        const oldestKey = sceneCache.keys().next().value as string | undefined;
        if (!oldestKey || oldestKey === currentKey) break;
        sceneCache.delete(oldestKey);
        sceneCacheWeights.delete(oldestKey);
    }
}

function cachedSceneElementCount(): number {
    let total = 0;
    for (const weight of sceneCacheWeights.values()) total += weight;
    return total;
}

async function compileChangedGalaxyScene(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
    sourceMode: GalaxySceneSourceMode,
    renderIdentity: string,
    failClosed: boolean,
): Promise<GalaxySceneV2> {
    const hasGalaxyMetadata = entities.some((entity) => Boolean(entity.metadata?.galaxyId));
    const hasAtlasLayout = entities.some((entity) =>
        Number.isFinite(entity.atlasX) && Number.isFinite(entity.atlasY) && Number.isFinite(entity.atlasZ),
    );
    const hasRelationControls = hasRelationControlNodes(entities);
    if (backend.target !== 'native' || hasGalaxyMetadata || hasAtlasLayout || hasRelationControls || settings.layoutMode !== 'single') {
        try {
            const scene = await compileGalaxySceneInWorker(entities, edges, settings, sourceMode, renderIdentity);
            if (scene) {
                graphGalaxyRuntimeMeter.recordCompilerSource('worker');
                return scene;
            }
        } catch (error) {
            if (failClosed) {
                throw new Error('Authoritative packed scene worker failed; main-thread compilation is forbidden.', { cause: error });
            }
            if (!warnedWorkerFallback) {
                warnedWorkerFallback = true;
                console.warn('[GraphGalaxyScene] Scene worker unavailable; using local exact compiler.', error);
            }
        }
        if (failClosed) {
            throw new Error('Authoritative packed scene worker is unavailable; main-thread compilation is forbidden.');
        }
        graphGalaxyRuntimeMeter.recordCompilerSource('local');
        return galaxySceneToV2(buildGalaxyScene(entities, edges, settings), sourceMode);
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
        const nativeScene: GalaxyScene = {
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
        return galaxySceneToV2(nativeScene, sourceMode);
    } catch (error) {
        if (failClosed) {
            throw new Error('Authoritative native scene compiler failed; local scene compilation is forbidden.', { cause: error });
        }
        if (!warnedNativeFallback) {
            warnedNativeFallback = true;
            console.warn('[GraphGalaxyScene] Native scene compiler unavailable; using local scene builder.', error);
        }
        graphGalaxyRuntimeMeter.recordCompilerSource('fallback');
        return galaxySceneToV2(buildGalaxyScene(entities, edges, settings), sourceMode);
    }
}

function compileGalaxySceneInWorker(
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
    sourceMode: GalaxySceneSourceMode,
    renderIdentity: string,
): Promise<GalaxySceneV2 | null> {
    const worker = galaxySceneWorker();
    if (!worker) return Promise.resolve(null);
    const id = ++nextWorkerRequestId;
    const graphNodeColors = Object.fromEntries(
        Object.keys(DEFAULT_GRAPH_NODE_COLORS).map((kind) => [kind, entityColorStore.getRawGraphNodeHsl(kind)]),
    );
    return new Promise<GalaxySceneV2>((resolve, reject) => {
        workerRequests.set(id, { resolve, reject });
        worker.postMessage({
            id,
            entities,
            edges,
            settings,
            entityColors: entityColorStore.getSnapshot(),
            graphNodeColors,
            sourceMode,
            packetContext: {
                generationId: galaxySceneGenerationId(renderIdentity),
                authorityReceipt: renderIdentity || 'ephemeral:unreceipted-current-graph',
            },
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
        worker.onmessage = ({ data }: MessageEvent<{ id: number; packet?: GalaxyScenePacketV2; error?: string }>) => {
            const pending = workerRequests.get(data.id);
            if (!pending) return;
            workerRequests.delete(data.id);
            data.packet
                ? pending.resolve(unpackGalaxyScenePacketV2(sharedScenePages.reuse(data.packet)))
                : pending.reject(new Error(data.error || 'Scene worker failed'));
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

function galaxySceneGenerationId(renderIdentity: string): string {
    return renderIdentity.split('\u0000', 1)[0] || 'ephemeral-current-graph';
}
