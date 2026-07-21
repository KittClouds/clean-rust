import { Injectable, computed, inject, signal } from '@angular/core';

import { getSetting } from '../lib/dexie/settings.service';
import type { GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';
import {
    assertGraphCanvasBootSnapshotShell,
    graphRebuildSnapshotPersistenceView,
    GraphRebuildService,
} from '../graph-rebuild/graph-rebuild.service';
import type { AtlasManifoldMode } from './manifold-atlas.types';
import type { EmbeddingAtlasData } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-embedding-atlas';
import { DEFAULT_GRAPH_NODE_COLORS, entityColorStore } from '../lib/store/entityColorStore';
import {
    mergeGalaxySettings,
    type GalaxyLayoutMode,
    type GalaxyRenderSettings,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-engine';
import { seedAuthoritativeGalaxyScenePacket } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-compiler';
import { galaxySceneIdentity } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-identity';
import {
    cachedGalaxyScenePacket,
    seedGalaxyScenePacket,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-packet-registry';
import type { GalaxyScenePacketV2 } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-packet-v2.model';
import {
    assertPersistedGalaxySceneMatches,
    loadPersistedGalaxySceneGenerationIndex,
    loadPersistedGalaxyScenePacket,
    persistGalaxyScenePacket,
    type GalaxySceneGenerationIndexReceipt,
    type GalaxyScenePacketPersistenceIdentity,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-packet-persistence';
import {
    cachedGraphRebuildEmbeddingAtlas,
    graphRebuildEmbeddingTargetCount,
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
    requestId: number;
    key: string;
    generationId: string;
    snapshot: GraphRebuildSnapshot;
    snapshotShell: GraphRebuildSnapshot;
    view: PersistedAtlasWarmState;
    manifold: AtlasManifoldMode;
    ready: Deferred;
    installChain: Promise<void>;
    installed: boolean;
    requestedAtlas: EmbeddingAtlasData | null;
    readyResolved: boolean;
    packScenes: boolean;
    generationIndex: GalaxySceneGenerationIndexReceipt | null;
}

interface ResidentFirstPixel {
    identity: GalaxyScenePacketPersistenceIdentity;
    snapshot: GraphRebuildSnapshot;
}

interface PrewarmWorkerReply {
    requestId: number;
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
    private readonly runsByRequestId = new Map<number, PrewarmRun>();
    private prewarmWorker: Worker | null = null;
    private workerGenerationId = '';
    private nextRequestId = 0;
    private globalStart: Promise<void> | null = null;
    private runtimeWarm: Promise<unknown> | null = null;
    private readonly firstPixelLoads = new Map<string, Promise<GraphRebuildSnapshot | null>>();
    private readonly residentFirstPixels = new Map<string, ResidentFirstPixel>();
    private readonly generationIndexState = signal<GalaxySceneGenerationIndexReceipt | null>(null);
    private readonly generationIndexListeners = new Set<(index: GalaxySceneGenerationIndexReceipt) => void>();

    readonly generationIndex = computed(() => this.generationIndexState());

    onGenerationIndex(listener: (index: GalaxySceneGenerationIndexReceipt) => void): () => void {
        this.generationIndexListeners.add(listener);
        const current = this.generationIndexState();
        if (current) listener(current);
        return () => this.generationIndexListeners.delete(listener);
    }

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

    preparePersistedFirstPixel(
        scopeId: string,
        manifold = persistedManifold(getSetting<PersistedAtlasWarmState>(GRAPH_ATLAS_VIEW_STATE_KEY, {})),
        force = false,
    ): Promise<GraphRebuildSnapshot | null> {
        const key = graphCanvasFirstPixelKey(scopeId, manifold);
        const active = this.firstPixelLoads.get(key);
        if (active) return active;
        const load = this.restorePersistedFirstPixel(scopeId, manifold, force).finally(() => {
            if (this.firstPixelLoads.get(key) === load) this.firstPixelLoads.delete(key);
        });
        this.firstPixelLoads.set(key, load);
        return load;
    }

    residentFirstPixelSceneIdentity(
        snapshot: GraphRebuildSnapshot,
        manifold: AtlasManifoldMode,
    ): string | null {
        const resident = this.residentFirstPixels.get(graphCanvasFirstPixelKey(snapshot.scopeId, manifold));
        return resident
            ? graphCanvasResidentFirstPixelReceipt(resident.identity, snapshot, manifold)
            : null;
    }

    async prepareManifold(
        snapshot: GraphRebuildSnapshot,
        manifold: AtlasManifoldMode,
        view = getSetting<PersistedAtlasWarmState>(GRAPH_ATLAS_VIEW_STATE_KEY, {}),
    ): Promise<void> {
        const generationId = snapshot.authorityContract?.contentHash || snapshot.id;
        this.acceptGeneration(generationId);
        const projectionResident = !!cachedGraphRebuildEmbeddingAtlas(snapshot, manifold);
        const packedSceneRequired = view.atlasMode === 'embeddings';
        const packedSceneResident = !packedSceneRequired
            || !!cachedPrewarmScenePacket(snapshot, view, manifold, generationId);
        if (projectionResident && packedSceneResident) return;
        if (!graphCanvasProjectionPayloadResident(snapshot)) {
            if (packedSceneResident) return;
            throw new Error(`Authoritative ${manifold} projection requires hydrated snapshot rows.`);
        }
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
            await this.preparePersistedFirstPixel('global');
        } catch (error) {
            console.warn('[GraphCanvasColdStart] Global first-pixel cache unavailable.', error);
        }
    }

    private async restorePersistedFirstPixel(
        scopeId: string,
        manifold: AtlasManifoldMode,
        force: boolean,
    ): Promise<GraphRebuildSnapshot | null> {
        const view = getSetting<PersistedAtlasWarmState>(GRAPH_ATLAS_VIEW_STATE_KEY, {});
        if (view.atlasMode !== 'embeddings') return null;
        const key = graphCanvasFirstPixelKey(scopeId, manifold);
        const resident = this.residentFirstPixels.get(key);
        if (resident && !force) {
            const expected = graphCanvasPersistedSceneIdentity(resident.snapshot, view, manifold);
            if (samePersistedSceneIdentity(resident.identity, expected)
                && cachedGalaxyScenePacket(expected.authorityReceipt, expected.generationId, 'embeddings')) {
                return resident.snapshot;
            }
            this.residentFirstPixels.delete(key);
        }
        const startedAt = performance.now();
        try {
            const persisted = await loadPersistedGalaxyScenePacket(scopeId, manifold);
            if (!persisted) return null;
            const snapshot = persisted.snapshotShell;
            assertGraphCanvasBootSnapshotShell(snapshot);
            const expected = graphCanvasPersistedSceneIdentity(snapshot, view, manifold);
            assertPersistedGalaxySceneMatches(persisted, expected);
            this.acceptGeneration(expected.generationId);
            seedGalaxyScenePacket(persisted.packet);
            this.residentFirstPixels.set(key, { identity: expected, snapshot });
            console.info(
                `[GraphCanvasColdStart] Restored authoritative ${manifold} first-pixel packet in ${elapsedMs(startedAt)} ms.`,
            );
            return snapshot;
        } catch (error) {
            console.warn('[GraphCanvasColdStart] Persisted first-pixel packet rejected; using full hydration.', error);
            return null;
        }
    }

    private startRun(
        key: string,
        generationId: string,
        snapshot: GraphRebuildSnapshot,
        view: PersistedAtlasWarmState,
        manifold: AtlasManifoldMode,
    ): PrewarmRun {
        const worker = this.requireWorker();
        const requestId = ++this.nextRequestId;
        const compileScenes = view.atlasMode === 'embeddings';
        const packedScenesResident = compileScenes && MANIFOLDS.every((candidate) =>
            !!cachedPrewarmScenePacket(snapshot, view, candidate, generationId));
        const packScenes = compileScenes && !packedScenesResident;
        const run: PrewarmRun = {
            requestId,
            key,
            generationId,
            snapshot,
            snapshotShell: graphRebuildSnapshotPersistenceView(snapshot, []),
            view,
            manifold,
            ready: deferred(),
            installChain: Promise.resolve(),
            installed: false,
            requestedAtlas: null,
            readyResolved: false,
            packScenes,
            generationIndex: null,
        };
        this.runsByRequestId.set(requestId, run);
        const sendSnapshot = this.workerGenerationId !== generationId;
        if (sendSnapshot) this.workerGenerationId = generationId;
        worker.postMessage({
            requestId,
            generationId,
            snapshot: sendSnapshot ? snapshot : undefined,
            jobs: manifoldPrewarmJobOrder(manifold, packScenes).map((manifold) => ({
                manifold,
                publishAtlas: packScenes || manifold === run.manifold,
                shareSearchIndex: manifold !== run.manifold,
                scene: packScenes ? {
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

    private requireWorker(): Worker {
        if (this.prewarmWorker) return this.prewarmWorker;
        const worker = new Worker(new URL('../workers/graph-manifold-prewarm.worker', import.meta.url), { type: 'module' });
        worker.onmessage = ({ data }: MessageEvent<PrewarmWorkerReply>) => {
            const run = this.runsByRequestId.get(data.requestId);
            if (run) this.acceptWorkerReply(run, data);
        };
        worker.onerror = (event) => {
            const error = new Error(event.message || 'Graph manifold prewarm worker failed.');
            this.prewarmWorker = null;
            this.workerGenerationId = '';
            for (const run of new Set(this.runsByRequestId.values())) this.failRun(run, error);
        };
        this.prewarmWorker = worker;
        return worker;
    }

    private acceptWorkerReply(run: PrewarmRun, reply: PrewarmWorkerReply): void {
        if (this.runs.get(run.key) !== run || reply.generationId !== run.generationId) return;
        if (reply.error) {
            this.failRun(run, new Error(reply.error));
            return;
        }
        if (reply.manifold && (reply.atlas || reply.packet)) {
            run.installChain = run.installChain
                .then(() => this.installAtlas(run, reply.manifold!, reply.atlas, reply.packet))
                .catch((error) => this.failRun(run, toError(error)));
        }
        if (reply.complete) {
            void run.installChain.then(() => {
                if (!run.installed) throw new Error(`Authoritative ${run.manifold} prewarm completed without an atlas.`);
                if (!run.requestedAtlas) {
                    throw new Error(`Authoritative ${run.manifold} prewarm omitted the requested atlas.`);
                }
                this.finishRun(run);
            }).catch((error) => this.failRun(run, toError(error)));
        }
    }

    private async installAtlas(
        run: PrewarmRun,
        manifold: AtlasManifoldMode,
        atlas?: EmbeddingAtlasData,
        packet?: GalaxyScenePacketV2,
    ): Promise<void> {
        if (this.runs.get(run.key) !== run) return;
        const installedAtlas = atlas && !atlas.searchIndex.length && run.requestedAtlas
            ? { ...atlas, searchIndex: run.requestedAtlas.searchIndex }
            : atlas;
        if (installedAtlas) seedGraphRebuildEmbeddingAtlas(run.snapshot, manifold, installedAtlas);
        if (manifold === run.manifold && installedAtlas) run.requestedAtlas = installedAtlas;
        if (run.packScenes) {
            const settings = graphCanvasPrewarmSettings(run.view, manifold);
            if (!packet) {
                throw new Error(`Authoritative ${manifold} prewarm omitted its packed scene.`);
            }
            seedGalaxyScenePacket(packet);
            if (manifold === run.manifold) {
                seedAuthoritativeGalaxyScenePacket(
                    packet,
                    settings,
                    prewarmSceneIdentity(run.snapshot, run.view, manifold),
                    'embeddings',
                );
            }
            try {
                await persistGalaxyScenePacket(
                    graphCanvasPersistedSceneIdentity(run.snapshot, run.view, manifold),
                    packet,
                    run.snapshotShell,
                );
                const index = await loadPersistedGalaxySceneGenerationIndex(
                    run.snapshot.scopeId,
                    run.generationId,
                );
                if (index) run.generationIndex = index;
            } catch (error) {
                console.warn('[GraphCanvasColdStart] Packed scene restart cache unavailable.', error);
            }
        }
        if (manifold === run.manifold && installedAtlas) run.installed = true;
        if (manifold === run.manifold && installedAtlas && !run.readyResolved) {
            run.readyResolved = true;
            run.ready.resolve();
        }
    }

    private failRun(run: PrewarmRun, error: Error): void {
        if (this.runs.get(run.key) !== run) return;
        run.ready.reject(error);
        this.runs.delete(run.key);
        this.runsByRequestId.delete(run.requestId);
        console.error('[GraphCanvasColdStart] Authoritative canvas prewarm failed closed.', error);
    }

    private finishRun(run: PrewarmRun): void {
        if (this.runs.get(run.key) !== run) return;
        if (!run.readyResolved) {
            run.readyResolved = true;
            run.ready.resolve();
        }
        this.runs.delete(run.key);
        this.runsByRequestId.delete(run.requestId);
        if (run.generationIndex) this.publishGenerationIndex(run.generationIndex);
        if (!this.runsByRequestId.size && this.generationIndexState()?.generationId === run.generationId) {
            this.prewarmWorker?.terminate();
            this.prewarmWorker = null;
            this.workerGenerationId = '';
        }
    }

    private publishGenerationIndex(index: GalaxySceneGenerationIndexReceipt): void {
        if (index.generationId !== this.generationId) return;
        this.generationIndexState.set(index);
        for (const listener of this.generationIndexListeners) listener(index);
    }

    private acceptGeneration(generationId: string): void {
        if (!this.generationId) {
            this.generationId = generationId;
            return;
        }
        if (this.generationId === generationId) return;
        const error = new Error('Graph canvas prewarm superseded by a newer snapshot.');
        this.prewarmWorker?.terminate();
        this.prewarmWorker = null;
        this.workerGenerationId = '';
        for (const run of new Set(this.runs.values())) run.ready.reject(error);
        this.runs.clear();
        this.runsByRequestId.clear();
        this.residentFirstPixels.clear();
        this.generationIndexState.set(null);
        this.generationId = generationId;
    }

    releaseGeneration(generationId: string): boolean {
        if (!generationId || this.generationId !== generationId) return false;
        const error = new Error('Graph canvas generation released after packed scene publication.');
        this.prewarmWorker?.terminate();
        this.prewarmWorker = null;
        this.workerGenerationId = '';
        for (const run of new Set(this.runs.values())) run.ready.reject(error);
        this.runs.clear();
        this.runsByRequestId.clear();
        this.generationIndexState.set(null);
        this.generationId = '';
        return true;
    }
}

export function manifoldPrewarmOrder(current: AtlasManifoldMode): AtlasManifoldMode[] {
    return [current, ...MANIFOLDS.filter((manifold) => manifold !== current)];
}

export function graphCanvasFirstPixelKey(scopeId: string, manifold: AtlasManifoldMode): string {
    return `${scopeId}\u0000${manifold}`;
}

export function graphCanvasProjectionPayloadResident(snapshot: GraphRebuildSnapshot): boolean {
    return graphRebuildEmbeddingTargetCount(snapshot) === 0
        || snapshot.embeddingTargets.length > 0
        || Boolean(snapshot.atlasPacket?.manifoldTargets?.length);
}

export function graphCanvasResidentFirstPixelReceipt(
    identity: GalaxyScenePacketPersistenceIdentity,
    snapshot: GraphRebuildSnapshot,
    manifold: AtlasManifoldMode,
): string | null {
    const generationId = snapshot.authorityContract?.contentHash || snapshot.id;
    return identity.scopeId === snapshot.scopeId
        && identity.snapshotId === snapshot.id
        && identity.generationId === generationId
        && identity.manifold === manifold
        ? identity.authorityReceipt
        : null;
}

export function manifoldPrewarmJobOrder(
    current: AtlasManifoldMode,
    packScenes: boolean,
): AtlasManifoldMode[] {
    return packScenes ? manifoldPrewarmOrder(current) : [current];
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
    return galaxySceneIdentity({
        graphIdentity: snapshot.authorityContract?.contentHash || snapshot.id,
        sourceMode: 'embeddings',
        manifold,
        settings: graphCanvasPrewarmSettings(view, manifold),
        canvasLens: view.canvasLens || 'entities',
        graphKindFilter: view.graphKindFilter || 'all',
    });
}

export function graphCanvasPersistedSceneIdentity(
    snapshot: GraphRebuildSnapshot,
    view: PersistedAtlasWarmState,
    manifold: AtlasManifoldMode,
): GalaxyScenePacketPersistenceIdentity {
    const generationId = snapshot.authorityContract?.contentHash || snapshot.id;
    return {
        scopeId: snapshot.scopeId,
        snapshotId: snapshot.id,
        generationId,
        manifold,
        authorityReceipt: prewarmSceneIdentity(snapshot, view, manifold),
    };
}

function samePersistedSceneIdentity(
    left: GalaxyScenePacketPersistenceIdentity,
    right: GalaxyScenePacketPersistenceIdentity,
): boolean {
    return left.scopeId === right.scopeId
        && left.snapshotId === right.snapshotId
        && left.generationId === right.generationId
        && left.manifold === right.manifold
        && left.authorityReceipt === right.authorityReceipt;
}

function elapsedMs(startedAt: number): number {
    return Math.max(0, Math.round(performance.now() - startedAt));
}

function cachedPrewarmScenePacket(
    snapshot: GraphRebuildSnapshot,
    view: PersistedAtlasWarmState,
    manifold: AtlasManifoldMode,
    generationId: string,
): GalaxyScenePacketV2 | null {
    return cachedGalaxyScenePacket(
        prewarmSceneIdentity(snapshot, view, manifold),
        generationId,
        'embeddings',
    );
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
