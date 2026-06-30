export type AtlasManifoldMode = 'hybrid' | 'hopf' | 'lorentz' | 'product' | 'siegel';
export type ManifoldProjectionSource =
    | 'real_snapshot_vectors'
    | 'semantic_atlas_rows';

export type PhoenixMachineManifoldStatus = 'idle' | 'loading' | 'ready' | 'stale' | 'error';

export interface ManifoldCapabilities {
    ann: boolean;
    anchors: boolean;
    fibers: boolean;
    phase: boolean;
    cones: boolean;
}

export type HybridEmbeddingValidationStatus = 'pending' | 'passed' | 'failed';

export interface HybridEmbeddingValidationReceipt {
    receiptId: string;
    status: HybridEmbeddingValidationStatus;
    generatedBy: 'frontend-contract' | 'native-runtime';
    checks: {
        neighborStability: HybridEmbeddingValidationStatus;
        continuity: HybridEmbeddingValidationStatus;
        clusterDensity: HybridEmbeddingValidationStatus;
        hubness: HybridEmbeddingValidationStatus;
        connectedComponents: HybridEmbeddingValidationStatus;
        badNeighborRejection: HybridEmbeddingValidationStatus;
    };
    metrics?: {
        nodeCount: number;
        validNodeCount: number;
        vectorDimensions: number | null;
        dimensionMismatchCount: number;
        neighborPairs: number;
        neighborPairKeys: string[];
        neighborGraphHash: string;
        previousNeighborGraphHash?: string | null;
        stableNeighborPairs: number;
        previousNeighborPairs: number;
        neighborStabilityRatio: number;
        trustworthinessScore: number;
        continuityScore: number;
        rejectedBadNeighbors: number;
        candidateEdgesTested: number;
        candidateEdgesInNeighborhood: number;
        candidateNeighborhoodSupport: number;
        connectedComponents: number;
        largestComponentSize: number;
        localDensityMin: number;
        localDensityAverage: number;
        localDensityMax: number;
        mutualNeighborPairs: number;
        mutualNeighborRatio: number;
        maxHubInbound: number;
        hubnessLimit: number;
        hubnessFlaggedNodeIds: string[];
        componentSizes: number[];
        averageAcceptedSimilarity: number;
    };
    rejectedNeighborReceipts: string[];
    evidence: string[];
}

export interface HybridEmbeddingSpaceContract {
    schemaVersion: 'phoenix-hybrid-embedding-space/v1';
    authority: 'hybrid';
    artifactKind: 'embedding-manifold';
    artifactId: string;
    cacheKey: string;
    inputHash: string;
    modelId?: string | null;
    modelVersion: string;
    dimensions?: number | null;
    executionProvider: string;
    runId: string;
    normalized: true;
    normalization: 'unit_l2';
    metric: 'cosine';
    candidateOnly: true;
    committedTopologyWrites: 0;
    neighborhood: {
        method: 'top-k' | 'mutual-knn';
        k: number;
        minSimilarity: number;
        densityPolicy: 'pending' | 'local-density';
        hubnessPolicy: 'pending' | 'mutual-neighbor-required';
        outlierPolicy: 'review-visible';
    };
    validationReceipt: HybridEmbeddingValidationReceipt;
}

export interface HybridEmbeddingSpaceContractOptions {
    artifactId?: string | null;
    cacheKey?: string | null;
    inputHash?: string | null;
    modelId?: string | null;
    modelVersion?: string | null;
    dimensions?: number | null;
    executionProvider?: string | null;
    runId?: string | null;
    validationReceipt?: HybridEmbeddingValidationReceipt | null;
}

export interface HybridEmbeddingInputFingerprintNode {
    id: string;
    vector?: ArrayLike<number> | null;
    modelId?: string | null;
    sourceType?: string | null;
}

export interface ManifoldAtlasSnapshot<TPayload> {
    manifold: AtlasManifoldMode;
    geometryVersion: string;
    sourceLabel: string;
    capabilities: ManifoldCapabilities;
    payload: TPayload;
    timings?: {
        runtimeLoadMs?: number;
        nativeSnapshotMs?: number;
        fallbackLoadMs?: number;
        totalMs?: number;
        source?: 'native' | 'fallback';
    };
}

export interface IcoCellRecord {
    cellId: string;
    resolution: number;
    parentCellId?: string | null;
    childrenCellIds: string[];
    centerVector: [number, number, number];
    normalVector: [number, number, number];
    neighborCellIds: string[];
    areaWeight: number;
    density: number;
    anchorIds: string[];
    geometryVersion: string;
}

export interface IcoChartRecord {
    chartId: string;
    centerCellId: string;
    memberCellIds: string[];
    resolution: number;
    dominantContexts: string[];
    anchorCount: number;
    density: number;
    boundaryCells: string[];
    geometryVersion: string;
}

export interface IcoSeamRecord {
    fromCell: string;
    toCell: string;
    sharedEdge: string[];
    normalDelta: number;
    chartA: string;
    chartB: string;
    seamCost: number;
    compatibilityScore: number;
    obstructionCount: number;
    geometryVersion: string;
}

export interface IcoNeighborRingsRecord {
    cellId: string;
    ring1: string[];
    ring2: string[];
    ring3: string[];
    geometryVersion: string;
}

export interface IcoConeTraceStepRecord {
    cellId: string;
    neighborRing: number;
    axisAlignment: number;
    apertureThreshold: number;
    chartStitchScore: number;
    accepted: boolean;
    reason: string;
}

export interface IcoConeTraceRecord {
    coneId: string;
    apexCell: string;
    axisVector: [number, number, number];
    apertureCos: number;
    maxRing: number;
    acceptedCellIds: string[];
    rejectedCellIds: string[];
    steps: IcoConeTraceStepRecord[];
    geometryVersion: string;
}

export interface AnchorProjectionRecord {
    anchorId: string;
    primaryCellId: string;
    secondaryCellIds: string[];
    cellDistance: number;
    boundaryScore: number;
    projectionVersion: string;
    geometryVersion: string;
}

export interface ConeProgramOpRecord {
    op: string;
    lane?: string;
    ids?: string[];
    requiredIds?: string[];
    maxCost?: number;
    limit?: number;
    minCompatibility?: number;
    requireEvidence?: boolean;
    strict?: boolean;
    pathletId?: string;
    rankBy?: string[];
}

export interface ConeProgramRecord {
    programId: string;
    intent: 'trace' | 'validate' | 'repair' | string;
    seedIds: string[];
    ops: ConeProgramOpRecord[];
    geometryVersion: string;
}

export interface ConePathletRecord {
    pathletId: string;
    lane: string;
    startId: string;
    endId: string;
    nodeIds: string[];
    edgeIds: string[];
    supportScore: number;
    compressionScore: number;
    obstructionIds: string[];
    geometryVersion: string;
}

export interface ConeObstructionRecord {
    obstructionId: string;
    kind: string;
    severity: number;
    explanation: string;
    nodeIds: string[];
    edgeIds: string[];
    chartIds: string[];
    evidenceRefs: string[];
    lane?: string;
    geometryVersion: string;
}

export interface ConeProgramTraceRecord {
    traceId: string;
    programId: string;
    activeIds: string[];
    pathletIds: string[];
    obstructionIds: string[];
    pathEdgeIds: string[];
    explanations: string[];
    geometryVersion: string;
}

export type LorentzTreeKind =
    | 'identity'
    | 'relationship'
    | 'location'
    | 'event'
    | 'temporal'
    | 'causal'
    | 'mechanical'
    | 'emotional'
    | 'political'
    | 'evidence'
    | 'provenance'
    | 'contradiction'
    | 'abstraction'
    | 'species'
    | 'powerSystem'
    | 'documentStructure';

export type LorentzQueryMode =
    | 'anchorSearch'
    | 'directLookup'
    | 'hierarchicalExpansion'
    | 'crossHierarchySynthesis'
    | 'contradiction';

export interface LorentzForestCacheStatus {
    geometryVersion: string;
    cacheKey: string;
    cachePath: string;
    exists: boolean;
    byteLen: number;
    mmap: boolean;
    rebuilt: boolean;
}

export interface LorentzTreeRecord {
    treeId: string;
    treeKind: LorentzTreeKind | string;
    label: string;
    rootNodeId?: string | null;
    geometryVersion: string;
}

export interface LorentzMembershipRecord {
    treeId: string;
    nodeId: string;
    parentNodeId?: string | null;
    level: number;
    localRank: number;
    pathKey: string;
    branchWeight: number;
    confidence: number;
    sourceCount: number;
    geometryVersion: string;
}

export interface LorentzForestSnapshot {
    nodes: Array<{
        id: string;
        label: string;
        sourceType: string;
        vector: number[];
        geometryVersion?: string;
        preview?: string;
        kind?: string;
    }>;
    edges: Array<{
        id: string;
        sourceId: string;
        targetId: string;
        type: string;
        confidence: number;
    }>;
    trees: LorentzTreeRecord[];
    memberships: LorentzMembershipRecord[];
}

export interface LorentzForestCacheRequest {
    scope?: Record<string, unknown>;
    limit?: number;
}

export interface LorentzForestBuildRequest extends LorentzForestCacheRequest {
    force?: boolean;
    includeSnapshot?: boolean;
}

export interface LorentzForestBuildResponse {
    geometryVersion: string;
    sourceLabel: string;
    cache: LorentzForestCacheStatus;
    nodeCount: number;
    treeCount: number;
    membershipCount: number;
    snapshot?: LorentzForestSnapshot | null;
}

export interface LorentzForestQueryRequest extends LorentzForestCacheRequest {
    force?: boolean;
    queryVector?: number[];
    queryNodeId?: string;
    treeKinds?: Array<LorentzTreeKind | string>;
    treeIds?: string[];
    targetLevel?: number;
    mode?: LorentzQueryMode | string;
    topK?: number;
}

export interface LorentzForestQueryHit {
    candidateId: string;
    nodeId: string;
    label: string;
    treeId?: string | null;
    treeKind?: LorentzTreeKind | string | null;
    pathKey?: string | null;
    score: number;
    hyperbolicDistance: number;
    geometrySimilarity: number;
    hierarchyAlignment: number;
    confidence: number;
}

export interface LorentzForestQueryResponse {
    geometryVersion: string;
    cache: LorentzForestCacheStatus;
    queryPoint: [number, number, number, number, number];
    hits: LorentzForestQueryHit[];
}

export interface ManifoldTopologyPayload {
    projectionSource?: ManifoldProjectionSource | string;
    embeddingSpace?: HybridEmbeddingSpaceContract;
    cells?: IcoCellRecord[];
    charts?: IcoChartRecord[];
    seams?: IcoSeamRecord[];
    neighborRings?: IcoNeighborRingsRecord[];
    coneTraces?: IcoConeTraceRecord[];
    conePrograms?: ConeProgramRecord[];
    pathlets?: ConePathletRecord[];
    obstructions?: ConeObstructionRecord[];
    coneProgramTraces?: ConeProgramTraceRecord[];
    anchorProjections?: AnchorProjectionRecord[];
    lorentzTrees?: LorentzTreeRecord[];
    lorentzMemberships?: LorentzMembershipRecord[];
    lorentzCache?: LorentzForestCacheStatus | null;
}

export const HYBRID_MANIFOLD_CAPABILITIES: ManifoldCapabilities = {
    ann: true,
    anchors: false,
    fibers: false,
    phase: false,
    cones: false,
};

export function hybridEmbeddingSpaceContract(
    options: HybridEmbeddingSpaceContractOptions = {},
): HybridEmbeddingSpaceContract {
    const modelId = options.modelId ?? null;
    const modelVersion = options.modelVersion || 'unversioned';
    const executionProvider = options.executionProvider || 'unknown-ep';
    const dimensions = options.dimensions ?? null;
    const inputHash = options.inputHash || 'input:unknown';
    const identityHash = stableContractDigest([
        'phoenix-hybrid-embedding-space/v1',
        modelId || 'unknown-model',
        modelVersion,
        String(dimensions ?? 'unknown-dim'),
        executionProvider,
        inputHash,
        'unit_l2',
        'cosine',
        'top-k',
        '4',
        'local-density',
        'mutual-neighbor-required',
    ]);
    const artifactId = options.artifactId || `hybrid:embedding-space:${identityHash}`;
    const cacheKey = options.cacheKey || `hybrid_embedding_space:${identityHash}`;
    const runId = options.runId || `hybrid-run:${identityHash}`;
    const validationReceipt = options.validationReceipt || pendingHybridValidationReceipt(artifactId, inputHash);
    return {
        schemaVersion: 'phoenix-hybrid-embedding-space/v1',
        authority: 'hybrid',
        artifactKind: 'embedding-manifold',
        artifactId,
        cacheKey,
        inputHash,
        modelId,
        modelVersion,
        dimensions,
        executionProvider,
        runId,
        normalized: true,
        normalization: 'unit_l2',
        metric: 'cosine',
        candidateOnly: true,
        committedTopologyWrites: 0,
        neighborhood: {
            method: 'top-k',
            k: 4,
            minSimilarity: 0,
            densityPolicy: 'local-density',
            hubnessPolicy: 'mutual-neighbor-required',
            outlierPolicy: 'review-visible',
        },
        validationReceipt,
    };
}

export function hybridEmbeddingInputHash(nodes: readonly HybridEmbeddingInputFingerprintNode[]): string {
    let hash = FNV_OFFSET;
    hash = updateHashString(hash, `count:${nodes.length}`);
    const ordered = [...nodes].sort((left, right) => left.id.localeCompare(right.id));
    for (const node of ordered) {
        hash = updateHashString(hash, '|id:');
        hash = updateHashString(hash, node.id);
        hash = updateHashString(hash, '|model:');
        hash = updateHashString(hash, node.modelId || '');
        hash = updateHashString(hash, '|source:');
        hash = updateHashString(hash, node.sourceType || '');
        const vector = node.vector;
        const length = vector?.length || 0;
        hash = updateHashString(hash, `|dim:${length}:`);
        for (let index = 0; index < length; index += 1) {
            const value = Number(vector?.[index]);
            const quantized = Number.isFinite(value) ? Math.round(value * 1_000_000) : 0;
            hash = updateHashString(hash, `${quantized},`);
        }
    }
    return `input:fnv1a32:${toHex32(hash)}`;
}

function pendingHybridValidationReceipt(artifactId: string, inputHash: string): HybridEmbeddingValidationReceipt {
    return {
        receiptId: `hybrid-validation:${stableContractDigest([artifactId, inputHash, 'pending'])}`,
        status: 'pending',
        generatedBy: 'frontend-contract',
        checks: {
            neighborStability: 'pending',
            continuity: 'pending',
            clusterDensity: 'pending',
            hubness: 'pending',
            connectedComponents: 'pending',
            badNeighborRejection: 'pending',
        },
        rejectedNeighborReceipts: [],
        evidence: [
            'validation_pending:neighbor_stability',
            'validation_pending:continuity',
            'validation_pending:cluster_density',
            'validation_pending:hubness',
            'validation_pending:connected_components',
            'validation_pending:bad_neighbor_rejection',
        ],
    };
}

function stableContractDigest(parts: readonly string[]): string {
    let hash = FNV_OFFSET;
    for (const part of parts) {
        hash = updateHashString(hash, part);
        hash = updateHashString(hash, '\u001f');
    }
    return toHex32(hash);
}

const FNV_OFFSET = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

function updateHashString(hash: number, value: string): number {
    let next = hash >>> 0;
    for (let index = 0; index < value.length; index += 1) {
        next ^= value.charCodeAt(index);
        next = Math.imul(next, FNV_PRIME) >>> 0;
    }
    return next;
}

function toHex32(value: number): string {
    return (value >>> 0).toString(16).padStart(8, '0');
}

export const HOPF_MANIFOLD_CAPABILITIES: ManifoldCapabilities = {
    ann: true,
    anchors: true,
    fibers: true,
    phase: true,
    cones: true,
};

export const LORENTZ_MANIFOLD_CAPABILITIES: ManifoldCapabilities = {
    ann: false,
    anchors: false,
    fibers: false,
    phase: false,
    cones: true,
};

export const PRODUCT_MANIFOLD_CAPABILITIES: ManifoldCapabilities = {
    ann: true,
    anchors: true,
    fibers: true,
    phase: true,
    cones: true,
};

export const SIEGEL_FINSLER_CAPABILITIES: ManifoldCapabilities = {
    ann: true,
    anchors: false,
    fibers: false,
    phase: false,
    cones: true,
};
