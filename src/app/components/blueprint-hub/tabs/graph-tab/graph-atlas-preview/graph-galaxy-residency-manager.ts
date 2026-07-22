import {
    EMPTY_GALAXY_RESIDENCY_COUNTERS,
    galaxyResidencyTileKey,
    type GalaxyElementCounts,
    type GalaxyResidencyBufferSlot,
    type GalaxyResidencyCounters,
    type GalaxyResidencyManagerOptions,
    type GalaxyResidencyManifest,
    type GalaxyResidencyRequest,
    type GalaxyResidencyTileDescriptor,
    type GalaxyResidencyView,
    type GalaxyResidentTile,
} from './graph-galaxy-residency.model';
import {
    galaxySphereIntersectsFrustum,
    planGalaxyResidencyRequests,
} from './graph-galaxy-residency-priority';

interface ResidentEntry<TPayload> {
    tile: GalaxyResidentTile<TPayload>;
    lastUsed: number;
}

interface InFlightEntry {
    request: GalaxyResidencyRequest;
    controller: AbortController;
}

interface ResidencyBuffer<TPayload> {
    slot: GalaxyResidencyBufferSlot;
    manifest: GalaxyResidencyManifest | null;
    token: number;
    resident: Map<string, ResidentEntry<TPayload>>;
    inFlight: Map<string, InFlightEntry>;
    queue: GalaxyResidencyRequest[];
}

export class GalaxyTsResidencyManager<TPayload> {
    private readonly buffers: Record<GalaxyResidencyBufferSlot, ResidencyBuffer<TPayload>> = {
        front: createBuffer('front'),
        back: createBuffer('back'),
    };
    private activeSlot: GalaxyResidencyBufferSlot = 'front';
    private stagingSlot: GalaxyResidencyBufferSlot | null = null;
    private token = 0;
    private accessClock = 0;
    private view: GalaxyResidencyView | null = null;
    private disposed = false;
    private readonly tasks = new Set<Promise<void>>();
    private counters: GalaxyResidencyCounters = structuredClone(EMPTY_GALAXY_RESIDENCY_COUNTERS);
    private readonly minimumTransitionCoverage: number;

    constructor(private readonly options: GalaxyResidencyManagerOptions<TPayload>) {
        this.minimumTransitionCoverage = Math.max(0.05, Math.min(1, options.minimumTransitionCoverage ?? 0.7));
        this.emitCounters();
    }

    beginTransition(manifest: GalaxyResidencyManifest): number {
        this.assertManifest(manifest);
        this.abortRequests(this.buffers.front);
        this.abortRequests(this.buffers.back);
        const active = this.buffers[this.activeSlot];
        const slot = active.manifest ? otherSlot(this.activeSlot) : this.activeSlot;
        const staging = this.buffers[slot];
        this.clearBuffer(staging);
        this.token += 1;
        staging.manifest = manifest;
        staging.token = this.token;
        this.stagingSlot = slot;
        this.refreshQueue(staging);
        this.pump(staging);
        this.emitCounters();
        return this.token;
    }

    updateView(view: GalaxyResidencyView): void {
        if (this.disposed) return;
        this.view = view;
        for (const buffer of Object.values(this.buffers)) {
            this.cancelInvisibleRequests(buffer);
            this.touchVisibleTiles(buffer);
            if (this.stagingSlot && buffer.slot !== this.stagingSlot) {
                buffer.queue = [];
                continue;
            }
            this.refreshQueue(buffer);
            this.pump(buffer);
        }
        this.emitCounters();
    }

    snapshotCounters(): GalaxyResidencyCounters {
        return structuredClone(this.counters);
    }

    async waitForIdle(): Promise<void> {
        while (this.tasks.size) await Promise.all([...this.tasks]);
    }

    dispose(): void {
        if (this.disposed) return;
        this.disposed = true;
        for (const buffer of Object.values(this.buffers)) {
            this.abortRequests(buffer);
            this.clearBuffer(buffer);
        }
        this.stagingSlot = null;
        this.emitCounters();
    }

    private refreshQueue(buffer: ResidencyBuffer<TPayload>): void {
        if (!buffer.manifest || !this.view || buffer.token !== this.token && buffer.slot === this.stagingSlot) {
            buffer.queue = [];
            return;
        }
        const residentKeys = new Set(buffer.resident.keys());
        const inFlightKeys = new Set(buffer.inFlight.keys());
        const planned = planGalaxyResidencyRequests(buffer.manifest, this.view, {
            token: buffer.token,
            slot: buffer.slot,
            residentKeys,
            inFlightKeys,
        });
        buffer.queue = this.fitRequestsToBudget(buffer, planned);
    }

    private pump(buffer: ResidencyBuffer<TPayload>): void {
        if (this.disposed || !buffer.manifest) return;
        while (
            buffer.inFlight.size < this.options.budget.maxConcurrentRequests
            && buffer.queue.length
        ) {
            const request = buffer.queue.shift()!;
            const key = galaxyResidencyTileKey(request.descriptor);
            if (buffer.resident.has(key) || buffer.inFlight.has(key)) continue;
            const controller = new AbortController();
            buffer.inFlight.set(key, { request, controller });
            const task = this.loadAndInstall(buffer, request, controller)
                .finally(() => {
                    buffer.inFlight.delete(key);
                    this.tasks.delete(task);
                    if (!this.disposed) {
                        this.refreshQueue(buffer);
                        this.pump(buffer);
                        this.emitCounters();
                    }
                });
            this.tasks.add(task);
        }
    }

    private async loadAndInstall(
        buffer: ResidencyBuffer<TPayload>,
        request: GalaxyResidencyRequest,
        controller: AbortController,
    ): Promise<void> {
        try {
            const tile = await this.options.provider.loadTile(request, controller.signal);
            if (!this.acceptsResult(buffer, request, tile, controller.signal)) return;
            this.assertTileFitsBaseBudget(tile.descriptor);
            await this.options.gpu.installTile(tile, buffer.slot, controller.signal);
            if (!this.acceptsResult(buffer, request, tile, controller.signal)) {
                await this.options.gpu.evictTile(tile, buffer.slot);
                return;
            }
            const key = galaxyResidencyTileKey(tile.descriptor);
            buffer.resident.set(key, { tile, lastUsed: ++this.accessClock });
            await this.replaceCoarserLod(buffer, tile.descriptor);
            await this.enforceBufferBudget(buffer);
            await this.enforceTransitionBudget();
            await this.maybeCommitTransition(buffer);
        } catch (error) {
            if (!controller.signal.aborted) {
                console.error('[GalaxyResidency] Tile request failed:', request.descriptor.tileId, error);
            }
        }
    }

    private acceptsResult(
        buffer: ResidencyBuffer<TPayload>,
        request: GalaxyResidencyRequest,
        tile: GalaxyResidentTile<TPayload>,
        signal: AbortSignal,
    ): boolean {
        if (this.disposed || signal.aborted || buffer.token !== request.token) return false;
        if (!buffer.manifest || buffer.manifest.generationId !== tile.descriptor.generationId) return false;
        if (buffer.manifest.manifoldId !== tile.descriptor.manifoldId) return false;
        return galaxyResidencyTileKey(request.descriptor) === galaxyResidencyTileKey(tile.descriptor)
            && request.descriptor.contentHash === tile.descriptor.contentHash
            && request.descriptor.authorityReceipt === tile.descriptor.authorityReceipt;
    }

    private async replaceCoarserLod(
        buffer: ResidencyBuffer<TPayload>,
        installed: GalaxyResidencyTileDescriptor,
    ): Promise<void> {
        for (const [key, entry] of [...buffer.resident]) {
            const descriptor = entry.tile.descriptor;
            if (
                key !== galaxyResidencyTileKey(installed)
                && descriptor.spatialKey === installed.spatialKey
                && descriptor.lod > installed.lod
                && !descriptor.pinned
            ) {
                buffer.resident.delete(key);
                await this.options.gpu.evictTile(entry.tile, buffer.slot);
            }
        }
    }

    private async maybeCommitTransition(buffer: ResidencyBuffer<TPayload>): Promise<void> {
        if (buffer.slot !== this.stagingSlot || !buffer.manifest) return;
        const visibleSpatialKeys = this.visibleSpatialKeys(buffer.manifest);
        const residentSpatialKeys = new Set(
            [...buffer.resident.values()]
                .filter((entry) => this.isVisible(entry.tile.descriptor))
                .map((entry) => entry.tile.descriptor.spatialKey),
        );
        const coverage = visibleSpatialKeys.size
            ? residentSpatialKeys.size / visibleSpatialKeys.size
            : buffer.resident.size > 0 ? 1 : 0;
        if (coverage < this.minimumTransitionCoverage) return;

        const oldSlot = this.activeSlot;
        await this.options.gpu.activate(buffer.slot, buffer.manifest.generationId, buffer.manifest.manifoldId);
        this.activeSlot = buffer.slot;
        this.stagingSlot = null;
        if (oldSlot !== this.activeSlot) await this.clearBufferAsync(this.buffers[oldSlot]);
    }

    private async enforceBufferBudget(buffer: ResidencyBuffer<TPayload>): Promise<void> {
        while (this.bufferExceedsBudget(buffer)) {
            const candidate = this.evictionCandidates(buffer)[0];
            if (!candidate) break;
            buffer.resident.delete(candidate.key);
            await this.options.gpu.evictTile(candidate.entry.tile, buffer.slot);
        }
    }

    private async enforceTransitionBudget(): Promise<void> {
        if (!this.stagingSlot) return;
        const limits = this.options.budget;
        const counts = this.allResidentCounts();
        const over = counts.bytes > limits.maxBytes * limits.transitionHeadroom
            || counts.nodes > limits.maxNodes * limits.transitionHeadroom
            || counts.edges > limits.maxEdges * limits.transitionHeadroom
            || counts.tiles > limits.maxTiles * limits.transitionHeadroom;
        if (!over) return;
        const staging = this.buffers[this.stagingSlot];
        const candidate = this.evictionCandidates(staging)[0];
        if (!candidate) return;
        staging.resident.delete(candidate.key);
        await this.options.gpu.evictTile(candidate.entry.tile, staging.slot);
    }

    private bufferExceedsBudget(buffer: ResidencyBuffer<TPayload>): boolean {
        const counts = residentCounts(buffer.resident.values());
        const budget = this.options.budget;
        return counts.bytes > budget.maxBytes
            || counts.nodes > budget.maxNodes
            || counts.edges > budget.maxEdges
            || counts.tiles > budget.maxTiles;
    }

    private fitRequestsToBudget(
        buffer: ResidencyBuffer<TPayload>,
        requests: GalaxyResidencyRequest[],
    ): GalaxyResidencyRequest[] {
        const budget = this.options.budget;
        const counts = residentCounts(buffer.resident.values());
        for (const entry of buffer.inFlight.values()) {
            counts.bytes += entry.request.descriptor.byteLength;
            counts.nodes += entry.request.descriptor.nodeCount;
            counts.edges += entry.request.descriptor.edgeCount;
            counts.tiles += 1;
        }
        const accepted: GalaxyResidencyRequest[] = [];
        for (const request of requests) {
            const replacement = [...buffer.resident.values()]
                .find((entry) =>
                    entry.tile.descriptor.spatialKey === request.descriptor.spatialKey
                    && entry.tile.descriptor.lod > request.descriptor.lod
                    && !entry.tile.descriptor.pinned,
                )?.tile.descriptor;
            const next = {
                bytes: counts.bytes + request.descriptor.byteLength - (replacement?.byteLength ?? 0),
                nodes: counts.nodes + request.descriptor.nodeCount - (replacement?.nodeCount ?? 0),
                edges: counts.edges + request.descriptor.edgeCount - (replacement?.edgeCount ?? 0),
                tiles: counts.tiles + 1 - (replacement ? 1 : 0),
            };
            if (
                next.bytes > budget.maxBytes
                || next.nodes > budget.maxNodes
                || next.edges > budget.maxEdges
                || next.tiles > budget.maxTiles
            ) {
                continue;
            }
            accepted.push(request);
            counts.bytes = next.bytes;
            counts.nodes = next.nodes;
            counts.edges = next.edges;
            counts.tiles = next.tiles;
        }
        return accepted;
    }

    private evictionCandidates(
        buffer: ResidencyBuffer<TPayload>,
    ): Array<{ key: string; entry: ResidentEntry<TPayload> }> {
        const coverageCounts = new Map<string, number>();
        for (const entry of buffer.resident.values()) {
            if (!this.isVisible(entry.tile.descriptor)) continue;
            coverageCounts.set(
                entry.tile.descriptor.spatialKey,
                (coverageCounts.get(entry.tile.descriptor.spatialKey) ?? 0) + 1,
            );
        }
        return [...buffer.resident.entries()]
            .filter(([, entry]) => {
                const descriptor = entry.tile.descriptor;
                if (descriptor.pinned) return false;
                return !this.isVisible(descriptor)
                    || (coverageCounts.get(descriptor.spatialKey) ?? 0) > 1;
            })
            .map(([key, entry]) => ({ key, entry }))
            .sort((left, right) => {
                const leftVisible = this.isVisible(left.entry.tile.descriptor) ? 1 : 0;
                const rightVisible = this.isVisible(right.entry.tile.descriptor) ? 1 : 0;
                return leftVisible - rightVisible
                    || right.entry.tile.descriptor.lod - left.entry.tile.descriptor.lod
                    || left.entry.lastUsed - right.entry.lastUsed;
            });
    }

    private cancelInvisibleRequests(buffer: ResidencyBuffer<TPayload>): void {
        for (const entry of buffer.inFlight.values()) {
            if (!entry.request.descriptor.pinned && !this.isVisible(entry.request.descriptor)) {
                entry.controller.abort();
            }
        }
    }

    private touchVisibleTiles(buffer: ResidencyBuffer<TPayload>): void {
        for (const entry of buffer.resident.values()) {
            if (this.isVisible(entry.tile.descriptor)) entry.lastUsed = ++this.accessClock;
        }
    }

    private isVisible(descriptor: GalaxyResidencyTileDescriptor): boolean {
        return this.view ? galaxySphereIntersectsFrustum(descriptor.bounds, this.view) : true;
    }

    private visibleSpatialKeys(manifest: GalaxyResidencyManifest): Set<string> {
        return new Set(
            manifest.tiles
                .filter((tile) => this.isVisible(tile))
                .map((tile) => tile.spatialKey),
        );
    }

    private abortRequests(buffer: ResidencyBuffer<TPayload>): void {
        for (const entry of buffer.inFlight.values()) entry.controller.abort();
        buffer.inFlight.clear();
        buffer.queue = [];
    }

    private clearBuffer(buffer: ResidencyBuffer<TPayload>): void {
        this.abortRequests(buffer);
        for (const entry of buffer.resident.values()) void this.options.gpu.evictTile(entry.tile, buffer.slot);
        buffer.resident.clear();
        buffer.manifest = null;
        buffer.token = 0;
    }

    private async clearBufferAsync(buffer: ResidencyBuffer<TPayload>): Promise<void> {
        this.abortRequests(buffer);
        await Promise.all(
            [...buffer.resident.values()].map((entry) => this.options.gpu.evictTile(entry.tile, buffer.slot)),
        );
        buffer.resident.clear();
        buffer.manifest = null;
        buffer.token = 0;
    }

    private assertManifest(manifest: GalaxyResidencyManifest): void {
        if (!manifest.generationId || !manifest.manifoldId || !manifest.authorityReceipt) {
            throw new Error('Galaxy residency manifest requires generation, manifold, and authority receipt.');
        }
        for (const tile of manifest.tiles) {
            if (
                tile.generationId !== manifest.generationId
                || tile.manifoldId !== manifest.manifoldId
                || tile.authorityReceipt !== manifest.authorityReceipt
            ) {
                throw new Error(`Galaxy residency tile ownership drift: ${tile.tileId}`);
            }
        }
    }

    private assertTileFitsBaseBudget(tile: GalaxyResidencyTileDescriptor): void {
        const budget = this.options.budget;
        if (
            tile.byteLength > budget.maxBytes
            || tile.nodeCount > budget.maxNodes
            || tile.edgeCount > budget.maxEdges
        ) {
            throw new Error(`Galaxy residency tile exceeds ${budget.deviceClass} device budget: ${tile.tileId}`);
        }
    }

    private allResidentCounts(): ResidentCounts {
        const front = residentCounts(this.buffers.front.resident.values());
        const back = residentCounts(this.buffers.back.resident.values());
        return {
            bytes: front.bytes + back.bytes,
            nodes: front.nodes + back.nodes,
            edges: front.edges + back.edges,
            tiles: front.tiles + back.tiles,
        };
    }

    private emitCounters(): void {
        const target = this.stagingSlot ? this.buffers[this.stagingSlot] : this.buffers[this.activeSlot];
        const display = this.buffers[this.activeSlot].manifest ? this.buffers[this.activeSlot] : target;
        const all = this.allResidentCounts();
        const visible = sumDescriptorCounts(display.resident.values(), (descriptor) => this.isVisible(descriptor));
        const drawn = sumDescriptorCounts(
            display.resident.values(),
            (descriptor) => this.isVisible(descriptor),
            'drawn',
        );
        const aggregated = sumDescriptorCounts(
            display.resident.values(),
            (descriptor) => this.isVisible(descriptor),
            'aggregated',
        );
        const manifest = target.manifest;
        this.counters = {
            generationId: manifest?.generationId ?? '',
            manifoldId: manifest?.manifoldId ?? '',
            transitioning: Boolean(this.stagingSlot),
            corpus: manifest?.corpus ?? { nodes: 0, edges: 0 },
            resident: { nodes: all.nodes, edges: all.edges },
            visible,
            drawn: {
                nodes: Math.min(drawn.nodes, this.options.budget.maxDrawnNodes),
                edges: Math.min(drawn.edges, this.options.budget.maxDrawnEdges),
            },
            aggregated,
            residentBytes: all.bytes,
            residentTiles: all.tiles,
            queuedTiles: this.buffers.front.queue.length + this.buffers.back.queue.length,
            inFlightTiles: this.buffers.front.inFlight.size + this.buffers.back.inFlight.size,
        };
        this.options.onCounters?.(this.snapshotCounters());
    }
}

interface ResidentCounts {
    bytes: number;
    nodes: number;
    edges: number;
    tiles: number;
}

function createBuffer<TPayload>(slot: GalaxyResidencyBufferSlot): ResidencyBuffer<TPayload> {
    return {
        slot,
        manifest: null,
        token: 0,
        resident: new Map(),
        inFlight: new Map(),
        queue: [],
    };
}

function otherSlot(slot: GalaxyResidencyBufferSlot): GalaxyResidencyBufferSlot {
    return slot === 'front' ? 'back' : 'front';
}

function residentCounts<TPayload>(entries: Iterable<ResidentEntry<TPayload>>): ResidentCounts {
    const counts: ResidentCounts = { bytes: 0, nodes: 0, edges: 0, tiles: 0 };
    for (const entry of entries) {
        counts.bytes += entry.tile.descriptor.byteLength;
        counts.nodes += entry.tile.descriptor.nodeCount;
        counts.edges += entry.tile.descriptor.edgeCount;
        counts.tiles += 1;
    }
    return counts;
}

function sumDescriptorCounts<TPayload>(
    entries: Iterable<ResidentEntry<TPayload>>,
    include: (descriptor: GalaxyResidencyTileDescriptor) => boolean,
    mode: 'resident' | 'drawn' | 'aggregated' = 'resident',
): GalaxyElementCounts {
    const counts = { nodes: 0, edges: 0 };
    for (const entry of entries) {
        const descriptor = entry.tile.descriptor;
        if (!include(descriptor)) continue;
        if (mode === 'drawn') {
            counts.nodes += descriptor.drawnNodeCount;
            counts.edges += descriptor.drawnEdgeCount;
        } else if (mode === 'aggregated') {
            counts.nodes += descriptor.aggregatedNodeCount;
            counts.edges += descriptor.aggregatedEdgeCount;
        } else {
            counts.nodes += descriptor.nodeCount;
            counts.edges += descriptor.edgeCount;
        }
    }
    return counts;
}
