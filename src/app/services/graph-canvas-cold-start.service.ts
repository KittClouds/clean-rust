import { Injectable, inject } from '@angular/core';

import { getSetting } from '../lib/dexie/settings.service';
import type { GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';
import { GraphRebuildService } from '../graph-rebuild/graph-rebuild.service';
import type { AtlasManifoldMode } from './manifold-atlas.types';
import type { EmbeddingAtlasData } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-embedding-atlas';
import { DEFAULT_GRAPH_NODE_COLORS, entityColorStore } from '../lib/store/entityColorStore';
import {
    mergeGalaxySettings,
    type GalaxyLayoutMode,
    type GalaxyRenderSettings,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-engine';
import { seedAuthoritativeGalaxyScenePacket } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-compiler';
import type { GalaxyScenePacketV2 } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-packet-v2.model';
import {
    cachedGraphRebuildEmbeddingAtlas,
    seedGraphRebuildEmbeddingAtlas,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-rebuild-embedding-atlas';

const GRAPH_ATLAS_VIEW_STATE_KEY = 'graph.atlas.viewState.v1';
const MANIFOLDS: readonly AtlasManifoldMode[] = ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'];

export interface PersistedAtlasWarmState {
    atlasMode?: string;
    manifoldMode?: AtlasManifoldMode;
    settings?: Partial<GalaxyRenderSettings>;
    graphKindFilter?: string;
    canvasLens?: string;
}

interface Deferred {
    promise: Promise<void>;
    resolve: () => void;
    reject: (error: Error) => void;
}

interface PrewarmRun {
    key: string;
    generationId: string;
    snapshot: GraphRebuildSnapshot;
    view: PersistedAtlasWarmState;
    manifold: AtlasManifoldMode;
    worker: Worker;
    ready: Deferred;
    installChain: Promise<void>;
    installed: boolean;
}

interface PrewarmWorkerReply {
    generationId: string;
    manifold?: AtlasManifoldMode;
    atlas?: EmbeddingAtlasData;
    packet?: GalaxyScenePacketV2;
    complete?: boolean;
    error?: string;
}

@Injectable({ providedIn: 'root' })
export class GraphCanvasColdStartService {
    private readonly graphRebuild = inject(GraphRebuildService);
    private generationId = '';
    private readonly runs = new Map<string, PrewarmRun>();
    private globalStart: Promise<void> | null = null;
    private runtimeWarm: Promise<unknown> | null = null;

    startGlobal(): void {
        this.warmRuntime();
        this.globalStart ||= this.loadAndPrimeGlobal();
    }

    async preparePersistedManifold(snapshot: GraphRebuildSnapshot): Promise<void> {
        const view = getSetting<PersistedAtlasWarmState>(GRAPH_ATLAS_VIEW_STATE_KEY, {});
        const manifold = persistedManifold(view);
        await Promise.all([
            this.prepareManifold(snapshot, manifold, view),
            this.warmRuntime(),
        ]);
    }

    async prepareManifold(
        snapshot: GraphRebuildSnapshot,
        manifold: AtlasManifoldMode,
        view = getSetting<PersistedAtlasWarmState>(GRAPH_ATLAS_VIEW_STATE_KEY, {}),
    ): Promise<void> {
        const generationId = snapshot.authorityContract?.contentHash || snapshot.id;
        this.acceptGeneration(generationId);
        if (cachedGraphRebuildEmbeddingAtlas(snapshot, manifold)) return;
        const key = `${generationId}\u0000${manifold}`;
        const resident = this.runs.get(key);
        if (resident) return resident.ready.promise;
        const run = this.startRun(key, generationId, snapshot, view, manifold);
        this.runs.set(key, run);
        return run.ready.promise;
    }

    private warmRuntime(): Promise<unknown> {
        return this.runtimeWarm ||= import('../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-residency-controller');
    }

    private async loadAndPrimeGlobal(): Promise<void> {
        try {
            const snapshot = await this.graphRebuild.loadPersistedSnapshot('global');
            if (snapshot) await this.preparePersistedManifold(snapshot);
        } catch (error) {
            console.warn('[GraphCanvasColdStart] Global snapshot prewarm unavailable.', error);
        }
    }

    private startRun(
        key: string,
        generationId: string,
        snapshot: GraphRebuildSnapshot,
        view: PersistedAtlasWarmState,
        manifold: AtlasManifoldMode,
    ): PrewarmRun {
        const worker = new Worker(new URL('../workers/graph-manifold-prewarm.worker', import.meta.url), { type: 'module' });
        const run: PrewarmRun = {
            key,
            generationId,
            snapshot,
            view,
            manifold,
            worker,
            ready: deferred(),
            installChain: Promise.resolve(),
            installed: false,
        };
        worker.onmessage = ({ data }: MessageEvent<PrewarmWorkerReply>) => this.acceptWorkerReply(run, data);
        worker.onerror = (event) => this.failRun(run, new Error(event.message || 'Graph manifold prewarm worker failed.'));
        const compileScenes = view.atlasMode === 'embeddings';
        worker.postMessage({
            generationId,
            snapshot,
            jobs: manifoldPrewarmOrder(manifold).map((manifold) => ({
                manifold,
                scene: compileScenes ? {
                    settings: graphCanvasPrewarmSettings(view, manifold),
                    renderIdentity: prewarmSceneIdentity(snapshot, view, manifold),
                    sourceMode: 'embeddings' as const,
                } : undefined,
            })),
            entityColors: entityColorStore.getSnapshot(),
            graphNodeColors: Object.fromEntries(
                Object.keys(DEFAULT_GRAPH_NODE_COLORS)
                    .map((kind) => [kind, entityColorStore.getRawGraphNodeHsl(kind)]),
            ),
        });
        return run;
    }

    private acceptWorkerReply(run: PrewarmRun, reply: PrewarmWorkerReply): void {
        if (this.runs.get(run.key) !== run || reply.generationId !== run.generationId) return;
        if (reply.error) {
            this.failRun(run, new Error(reply.error));
            return;
        }
        if (reply.manifold && reply.atlas) {
            run.installChain = run.installChain
                .then(() => this.installAtlas(run, reply.manifold!, reply.atlas!, reply.packet))
                .catch((error) => this.failRun(run, toError(error)));
        }
        if (reply.complete) {
            void run.installChain.then(() => {
                if (!run.installed) throw new Error(`Authoritative ${run.manifold} prewarm completed without an atlas.`);
                this.finishRun(run);
            }).catch((error) => this.failRun(run, toError(error)));
        }
    }

    private async installAtlas(
        run: PrewarmRun,
        manifold: AtlasManifoldMode,
        atlas: EmbeddingAtlasData,
        packet?: GalaxyScenePacketV2,
    ): Promise<void> {
        if (this.runs.get(run.key) !== run) return;
        seedGraphRebuildEmbeddingAtlas(run.snapshot, manifold, atlas);
        if (run.view.atlasMode === 'embeddings') {
            const settings = graphCanvasPrewarmSettings(run.view, manifold);
            if (!packet) {
                throw new Error(`Authoritative ${manifold} prewarm omitted its packed scene.`);
            }
            seedAuthoritativeGalaxyScenePacket(
                packet,
                settings,
                prewarmSceneIdentity(run.snapshot, run.view, manifold),
                'embeddings',
            );
        }
        run.installed = true;
    }

    private failRun(run: PrewarmRun, error: Error): void {
        if (this.runs.get(run.key) !== run) return;
        run.worker.terminate();
        run.ready.reject(error);
        this.runs.delete(run.key);
        console.error('[GraphCanvasColdStart] Authoritative canvas prewarm failed closed.', error);
    }

    private finishRun(run: PrewarmRun): void {
        if (this.runs.get(run.key) !== run) return;
        run.worker.terminate();
        run.ready.resolve();
        this.runs.delete(run.key);
    }

    private acceptGeneration(generationId: string): void {
        if (!this.generationId) {
            this.generationId = generationId;
            return;
        }
        if (this.generationId === generationId) return;
        const error = new Error('Graph canvas prewarm superseded by a newer snapshot.');
        for (const run of this.runs.values()) {
            run.worker.terminate();
            run.ready.reject(error);
        }
        this.runs.clear();
        this.generationId = generationId;
    }
}

export function manifoldPrewarmOrder(current: AtlasManifoldMode): AtlasManifoldMode[] {
    return [current];
}

function persistedManifold(view: PersistedAtlasWarmState): AtlasManifoldMode {
    return MANIFOLDS.includes(view.manifoldMode as AtlasManifoldMode)
        ? view.manifoldMode as AtlasManifoldMode
        : 'hybrid';
}

export function graphCanvasPrewarmSettings(
    view: PersistedAtlasWarmState,
    manifold: AtlasManifoldMode,
): GalaxyRenderSettings {
    const current = persistedManifold(view);
    const storedLayout = view.settings?.layoutMode;
    const layoutMode = manifold === 'hybrid' && current === 'hybrid'
        && (storedLayout === 'hybridSpace' || storedLayout === 'multiGalaxy')
        ? storedLayout
        : layoutForManifold(manifold);
    return mergeGalaxySettings({ ...view.settings, layoutMode, sourceMode: 'embeddings' });
}

function layoutForManifold(manifold: AtlasManifoldMode): GalaxyLayoutMode {
    if (manifold === 'hopf') return 'hopfProjection';
    if (manifold === 'lorentz') return 'lorentzTree';
    if (manifold === 'product') return 'transitManifold';
    if (manifold === 'siegel') return 'siegelFinsler';
    return 'hybridSpace';
}

function prewarmSceneIdentity(
    snapshot: GraphRebuildSnapshot,
    view: PersistedAtlasWarmState,
    manifold: AtlasManifoldMode,
): string {
    return [
        snapshot.authorityContract?.contentHash || snapshot.id,
        'embeddings',
        manifold,
        view.canvasLens || 'entities',
        view.graphKindFilter || 'all',
        '',
    ].join('\u0000');
}

function deferred(): Deferred {
    let resolve!: () => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<void>((accept, fail) => {
        resolve = accept;
        reject = fail;
    });
    void promise.catch(() => undefined);
    return { promise, resolve, reject };
}

function toError(error: unknown): Error {
    return error instanceof Error ? error : new Error(String(error));
}
