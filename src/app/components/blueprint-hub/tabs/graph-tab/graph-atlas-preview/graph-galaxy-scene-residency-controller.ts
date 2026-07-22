import type { GraphRendererMode } from './graph-renderer-port';
import type { GalaxyRenderSettings } from './graph-galaxy-engine';
import { GalaxyTsResidencyManager } from './graph-galaxy-residency-manager';
import {
    assertGalaxyTsMaterializationBound,
    currentGalaxyResidencyBudget,
    galaxyResidencyTileKey,
    type GalaxyResidencyBudget,
    type GalaxyElementCounts,
    type GalaxyResidencyCounters,
    type GalaxyResidencyGpuPort,
    type GalaxyResidencyManifest,
    type GalaxyResidencyTileProvider,
    type GalaxyResidencyView,
    type GalaxyResidentTile,
} from './graph-galaxy-residency.model';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

export interface GalaxySceneResidencyPayload {
    scene: GalaxySceneV2;
    settings: GalaxyRenderSettings;
    mode: GraphRendererMode;
    selectedIds: readonly string[];
}

export interface GalaxySceneResidencyInstall {
    generationId: string;
    authorityReceipt: string;
    corpus: GalaxyElementCounts;
    payload: GalaxySceneResidencyPayload;
}

export interface GalaxySceneResidencyControllerOptions {
    activate: (payload: GalaxySceneResidencyPayload) => void;
    counters: (counters: GalaxyResidencyCounters) => void;
}

export class GalaxySceneResidencyController {
    private readonly pending = new Map<string, GalaxyResidentTile<GalaxySceneResidencyPayload>>();
    private readonly staged = new Map<string, GalaxyResidentTile<GalaxySceneResidencyPayload>>();
    private readonly manager: GalaxyTsResidencyManager<GalaxySceneResidencyPayload>;
    private readonly budget: GalaxyResidencyBudget;
    private view = compatibilityResidencyView();

    constructor(private readonly options: GalaxySceneResidencyControllerOptions) {
        this.budget = currentGalaxyResidencyBudget();
        const provider: GalaxyResidencyTileProvider<GalaxySceneResidencyPayload> = {
            loadTile: async (request, signal) => {
                if (signal.aborted) throw new DOMException('Galaxy tile request aborted', 'AbortError');
                const key = galaxyResidencyTileKey(request.descriptor);
                const tile = this.pending.get(key);
                if (!tile) throw new Error(`Galaxy compatibility tile unavailable: ${request.descriptor.tileId}`);
                return tile;
            },
        };
        const gpu: GalaxyResidencyGpuPort<GalaxySceneResidencyPayload> = {
            installTile: (tile, slot) => {
                this.staged.set(`${slot}\u0000${galaxyResidencyTileKey(tile.descriptor)}`, tile);
            },
            evictTile: (tile, slot) => {
                this.staged.delete(`${slot}\u0000${galaxyResidencyTileKey(tile.descriptor)}`);
            },
            activate: (slot, generationId, manifoldId) => {
                const tile = [...this.staged.entries()]
                    .find(([key, candidate]) =>
                        key.startsWith(`${slot}\u0000`)
                        && candidate.descriptor.generationId === generationId
                        && candidate.descriptor.manifoldId === manifoldId,
                    )?.[1];
                if (!tile) throw new Error(`Galaxy staging buffer has no activatable tile for ${generationId}/${manifoldId}`);
                this.options.activate(tile.payload);
            },
        };
        this.manager = new GalaxyTsResidencyManager({
            budget: this.budget,
            provider,
            gpu,
            onCounters: (counters) => this.options.counters(counters),
            minimumTransitionCoverage: 1,
        });
    }

    async install(input: GalaxySceneResidencyInstall): Promise<void> {
        const descriptor = compatibilityTileDescriptor(input);
        assertGalaxyTsMaterializationBound(input.corpus, {
            nodes: descriptor.nodeCount,
            edges: descriptor.edgeCount,
        }, this.budget);
        const tile = { descriptor, payload: input.payload };
        this.pending.set(galaxyResidencyTileKey(descriptor), tile);
        const manifest: GalaxyResidencyManifest = {
            generationId: descriptor.generationId,
            manifoldId: descriptor.manifoldId,
            authorityReceipt: descriptor.authorityReceipt,
            corpus: input.corpus,
            tiles: [descriptor],
        };
        this.manager.beginTransition(manifest);
        this.manager.updateView(this.view);
        await this.manager.waitForIdle();
        this.prunePending(input.generationId, descriptor.manifoldId);
    }

    updateView(view: GalaxyResidencyView): void {
        this.view = view;
        this.manager.updateView(view);
    }

    snapshotCounters(): GalaxyResidencyCounters {
        return this.manager.snapshotCounters();
    }

    dispose(): void {
        this.manager.dispose();
        this.pending.clear();
        this.staged.clear();
    }

    private prunePending(generationId: string, manifoldId: string): void {
        for (const [key, tile] of this.pending) {
            if (
                tile.descriptor.generationId !== generationId
                || tile.descriptor.manifoldId !== manifoldId
            ) {
                this.pending.delete(key);
            }
        }
    }
}

function compatibilityTileDescriptor(
    input: GalaxySceneResidencyInstall,
): GalaxyResidencyManifest['tiles'][number] {
    const { scene } = input.payload;
    const bounds = sceneBounds(scene.positions3d);
    const generationId = input.generationId || 'ephemeral-current-graph';
    const authorityReceipt = input.authorityReceipt || generationId;
    return {
        generationId,
        manifoldId: scene.layoutMode,
        tileId: 'full',
        spatialKey: 'full',
        lod: 0,
        contentHash: `${authorityReceipt}:${scene.ids.length}:${scene.edgePairs.length / 2}`,
        authorityReceipt,
        bounds,
        geometricError: Math.max(0.001, bounds.radius * 0.002),
        byteLength: estimateSceneBytes(scene),
        nodeCount: scene.ids.length,
        edgeCount: scene.edgePairs.length / 2,
        drawnNodeCount: scene.ids.length,
        drawnEdgeCount: scene.edgePairs.length / 2,
        aggregatedNodeCount: 0,
        aggregatedEdgeCount: 0,
        pinned: true,
    };
}

function sceneBounds(positions: Float32Array): { center: [number, number, number]; radius: number } {
    if (!positions.length) return { center: [0, 0, 0], radius: 1 };
    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    for (let offset = 0; offset < positions.length; offset += 3) {
        minX = Math.min(minX, positions[offset]);
        minY = Math.min(minY, positions[offset + 1]);
        minZ = Math.min(minZ, positions[offset + 2]);
        maxX = Math.max(maxX, positions[offset]);
        maxY = Math.max(maxY, positions[offset + 1]);
        maxZ = Math.max(maxZ, positions[offset + 2]);
    }
    const center: [number, number, number] = [
        (minX + maxX) * 0.5,
        (minY + maxY) * 0.5,
        (minZ + maxZ) * 0.5,
    ];
    let radius = 0;
    for (let offset = 0; offset < positions.length; offset += 3) {
        radius = Math.max(radius, Math.hypot(
            positions[offset] - center[0],
            positions[offset + 1] - center[1],
            positions[offset + 2] - center[2],
        ));
    }
    return { center, radius: Math.max(0.001, radius) };
}

function estimateSceneBytes(scene: GalaxySceneV2): number {
    let bytes = 0;
    for (const value of Object.values(scene)) {
        if (ArrayBuffer.isView(value)) bytes += value.byteLength;
    }
    for (const values of [
        scene.ids,
        scene.labels,
        scene.kinds,
        scene.groupIds,
        scene.hopfBaseIds ?? [],
        scene.edgeIds,
        scene.edgeTypes,
    ]) {
        for (const value of values) bytes += value.length * 2;
    }
    return bytes;
}

function compatibilityResidencyView(): GalaxyResidencyView {
    return {
        camera: [0, 0, 8],
        viewportHeight: 1080,
        verticalFovRadians: Math.PI / 3,
        targetErrorPixels: 1.25,
        frustum: [],
        epoch: 0,
    };
}
