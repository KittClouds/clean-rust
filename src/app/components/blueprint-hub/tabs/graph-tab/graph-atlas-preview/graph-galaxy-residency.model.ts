export type GalaxyResidencyDeviceClass = 'constrained' | 'balanced' | 'workstation';
export type GalaxyResidencyBufferSlot = 'front' | 'back';

export interface GalaxyElementCounts {
    nodes: number;
    edges: number;
}

export interface GalaxyResidencyCounters {
    generationId: string;
    manifoldId: string;
    transitioning: boolean;
    corpus: GalaxyElementCounts;
    resident: GalaxyElementCounts;
    visible: GalaxyElementCounts;
    drawn: GalaxyElementCounts;
    aggregated: GalaxyElementCounts;
    residentBytes: number;
    residentTiles: number;
    queuedTiles: number;
    inFlightTiles: number;
}

export interface GalaxyResidencyBudget {
    deviceClass: GalaxyResidencyDeviceClass;
    maxBytes: number;
    maxNodes: number;
    maxEdges: number;
    maxTiles: number;
    maxDrawnNodes: number;
    maxDrawnEdges: number;
    maxConcurrentRequests: number;
    transitionHeadroom: number;
}

export interface GalaxyResidencyDeviceProfile {
    deviceMemoryGiB?: number;
    hardwareConcurrency?: number;
    mobile?: boolean;
}

export interface GalaxyResidencySphere {
    center: readonly [number, number, number];
    radius: number;
}

export interface GalaxyResidencyPlane {
    normal: readonly [number, number, number];
    constant: number;
}

export interface GalaxyResidencyView {
    camera: readonly [number, number, number];
    viewportHeight: number;
    verticalFovRadians: number;
    targetErrorPixels: number;
    frustum: readonly GalaxyResidencyPlane[];
    epoch: number;
}

export interface GalaxyResidencyTileDescriptor {
    generationId: string;
    manifoldId: string;
    tileId: string;
    spatialKey: string;
    lod: number;
    contentHash: string;
    authorityReceipt: string;
    bounds: GalaxyResidencySphere;
    geometricError: number;
    byteLength: number;
    nodeCount: number;
    edgeCount: number;
    drawnNodeCount: number;
    drawnEdgeCount: number;
    aggregatedNodeCount: number;
    aggregatedEdgeCount: number;
    pinned?: boolean;
}

export interface GalaxyResidencyManifest {
    generationId: string;
    manifoldId: string;
    authorityReceipt: string;
    corpus: GalaxyElementCounts;
    tiles: readonly GalaxyResidencyTileDescriptor[];
}

export interface GalaxyResidencyRequest {
    token: number;
    slot: GalaxyResidencyBufferSlot;
    descriptor: GalaxyResidencyTileDescriptor;
    priority: number;
    screenSpaceError: number;
    distance: number;
    reason: 'coverage' | 'refinement';
}

export interface GalaxyResidentTile<TPayload> {
    descriptor: GalaxyResidencyTileDescriptor;
    payload: TPayload;
}

export interface GalaxyResidencyTileProvider<TPayload> {
    loadTile(request: GalaxyResidencyRequest, signal: AbortSignal): Promise<GalaxyResidentTile<TPayload>>;
}

export interface GalaxyResidencyGpuPort<TPayload> {
    installTile(
        tile: GalaxyResidentTile<TPayload>,
        slot: GalaxyResidencyBufferSlot,
        signal: AbortSignal,
    ): Promise<void> | void;
    evictTile(tile: GalaxyResidentTile<TPayload>, slot: GalaxyResidencyBufferSlot): Promise<void> | void;
    activate(
        slot: GalaxyResidencyBufferSlot,
        generationId: string,
        manifoldId: string,
    ): Promise<void> | void;
}

export interface GalaxyResidencyManagerOptions<TPayload> {
    budget: GalaxyResidencyBudget;
    provider: GalaxyResidencyTileProvider<TPayload>;
    gpu: GalaxyResidencyGpuPort<TPayload>;
    onCounters?: (counters: GalaxyResidencyCounters) => void;
    minimumTransitionCoverage?: number;
}

export function galaxyResidencyBudgetForDevice(
    profile: GalaxyResidencyDeviceProfile,
): GalaxyResidencyBudget {
    const memory = profile.deviceMemoryGiB ?? 8;
    const cores = profile.hardwareConcurrency ?? 8;
    if (profile.mobile || memory <= 4 || cores <= 4) {
        return {
            deviceClass: 'constrained',
            maxBytes: 128 * 1024 * 1024,
            maxNodes: 150_000,
            maxEdges: 250_000,
            maxTiles: 192,
            maxDrawnNodes: 90_000,
            maxDrawnEdges: 140_000,
            maxConcurrentRequests: 3,
            transitionHeadroom: 1.25,
        };
    }
    if (memory >= 16 && cores >= 12) {
        return {
            deviceClass: 'workstation',
            maxBytes: 768 * 1024 * 1024,
            maxNodes: 800_000,
            maxEdges: 1_400_000,
            maxTiles: 1024,
            maxDrawnNodes: 300_000,
            maxDrawnEdges: 500_000,
            maxConcurrentRequests: 8,
            transitionHeadroom: 1.5,
        };
    }
    return {
        deviceClass: 'balanced',
        maxBytes: 384 * 1024 * 1024,
        maxNodes: 400_000,
        maxEdges: 700_000,
        maxTiles: 512,
        maxDrawnNodes: 180_000,
        maxDrawnEdges: 300_000,
        maxConcurrentRequests: 5,
        transitionHeadroom: 1.35,
    };
}

export function currentGalaxyResidencyBudget(): GalaxyResidencyBudget {
    const runtime = typeof navigator === 'undefined'
        ? undefined
        : navigator as Navigator & { deviceMemory?: number; userAgentData?: { mobile?: boolean } };
    return galaxyResidencyBudgetForDevice({
        deviceMemoryGiB: runtime?.deviceMemory,
        hardwareConcurrency: runtime?.hardwareConcurrency,
        mobile: runtime?.userAgentData?.mobile ?? /Android|iPhone|iPad|Mobile/i.test(runtime?.userAgent || ''),
    });
}

export function galaxyResidencyTileKey(
    descriptor: Pick<GalaxyResidencyTileDescriptor, 'generationId' | 'manifoldId' | 'tileId' | 'lod'>,
): string {
    return `${descriptor.generationId}\u0000${descriptor.manifoldId}\u0000${descriptor.tileId}\u0000${descriptor.lod}`;
}

export function galaxyElementCountTotal(counts: GalaxyElementCounts): number {
    return counts.nodes + counts.edges;
}

export function assertGalaxyTsMaterializationBound(
    corpus: GalaxyElementCounts,
    materialized: GalaxyElementCounts,
    budget: GalaxyResidencyBudget,
): void {
    const wholeOversizedNodes = corpus.nodes > budget.maxNodes && materialized.nodes >= corpus.nodes;
    const wholeOversizedEdges = corpus.edges > budget.maxEdges && materialized.edges >= corpus.edges;
    if (wholeOversizedNodes || wholeOversizedEdges) {
        throw new Error(
            `Galaxy TS whole-corpus materialization rejected: corpus=${corpus.nodes}/${corpus.edges} `
            + `materialized=${materialized.nodes}/${materialized.edges} `
            + `budget=${budget.maxNodes}/${budget.maxEdges}`,
        );
    }
}

export const EMPTY_GALAXY_RESIDENCY_COUNTERS: GalaxyResidencyCounters = {
    generationId: '',
    manifoldId: '',
    transitioning: false,
    corpus: { nodes: 0, edges: 0 },
    resident: { nodes: 0, edges: 0 },
    visible: { nodes: 0, edges: 0 },
    drawn: { nodes: 0, edges: 0 },
    aggregated: { nodes: 0, edges: 0 },
    residentBytes: 0,
    residentTiles: 0,
    queuedTiles: 0,
    inFlightTiles: 0,
};
