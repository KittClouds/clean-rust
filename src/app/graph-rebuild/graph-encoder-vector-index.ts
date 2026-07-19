import type {
    GraphEncoderCandidateNeighborhood,
    GraphEncoderVectorIndexContract,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import { assertGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';

const DEFAULT_K = 8;
const DEFAULT_MINIMUM_SIMILARITY = 0.2;
const DEFAULT_LSH_BANDS = 4;
const DEFAULT_LSH_BITS = 10;
const DEFAULT_MAX_CANDIDATES = 96;

export interface GraphEncoderVectorPage {
    modelId: string;
    modelVersion: string;
    executionProvider: GraphEncoderVectorIndexContract['executionProvider'];
    dimensions: number;
    generation: number;
    targetIds: readonly string[];
    values: Float32Array;
    normalized: boolean;
}

export interface GraphEncoderVectorIndexOptions {
    neighborhoodK?: number;
    minimumSimilarity?: number;
    lshBands?: number;
    lshBits?: number;
    maxCandidatesPerTarget?: number;
    requireCompleteRegistry?: boolean;
}

export interface GraphEncoderNeighborhoodBuild {
    neighborhoods: readonly GraphEncoderCandidateNeighborhood[];
    evaluatedPairs: number;
}

export interface GraphEncoderVectorQueryOptions {
    limit?: number;
    minimumSimilarity?: number;
    maxCandidates?: number;
}

export interface GraphEncoderVectorQueryResult {
    neighbors: GraphEncoderCandidateNeighborhood['neighbors'];
    evaluatedCandidates: number;
    truncated: boolean;
}

export interface GraphEncoderVectorIndex {
    readonly contract: GraphEncoderVectorIndexContract;
    readonly targetIds: readonly string[];
    readonly values: Float32Array;
    readonly neighborhoods: readonly GraphEncoderCandidateNeighborhood[];
    vector(targetId: string): Float32Array | undefined;
    neighborhood(targetId: string): GraphEncoderCandidateNeighborhood | undefined;
    query(vector: Float32Array, options?: GraphEncoderVectorQueryOptions): GraphEncoderVectorQueryResult;
}

export function buildGraphEncoderVectorIndex(
    snapshot: GraphRebuildSnapshot,
    page: GraphEncoderVectorPage,
    options: GraphEncoderVectorIndexOptions = {},
    prebuiltNeighborhoods?: GraphEncoderNeighborhoodBuild,
): GraphEncoderVectorIndex {
    const registry = assertGraphEvidenceTargetRegistry(snapshot);
    const config = normalizeGraphEncoderVectorIndexOptions(options);
    assertPageShape(page);
    const exposedIds = new Set(registry.exposedTargets.map((target) => target.id));
    const rowByTargetId = new Map<string, number>();
    for (let row = 0; row < page.targetIds.length; row += 1) {
        const targetId = page.targetIds[row];
        if (!exposedIds.has(targetId)) {
            throw new Error(`Encoder vector target is outside the evidence registry: ${targetId}`);
        }
        if (rowByTargetId.has(targetId)) {
            throw new Error(`Encoder vector target identity collides: ${targetId}`);
        }
        rowByTargetId.set(targetId, row);
    }
    const missingRegistryTargets = Math.max(0, exposedIds.size - rowByTargetId.size);
    if (config.requireCompleteRegistry && missingRegistryTargets) {
        throw new Error(`Encoder vector page is missing ${missingRegistryTargets} evidence registry targets`);
    }

    const values = normalizedPageValues(page);
    const lsh = buildLshBuckets(page.targetIds, values, page.dimensions, config);
    const { neighborhoods, evaluatedPairs } = prebuiltNeighborhoods
        ? validatePrebuiltNeighborhoods(prebuiltNeighborhoods, page.targetIds, rowByTargetId, config)
        : buildCandidateNeighborhoods(page.targetIds, values, page.dimensions, lsh, config);
    const neighborCount = neighborhoods.reduce((sum, row) => sum + row.neighbors.length, 0);
    const contract: GraphEncoderVectorIndexContract = {
        schemaVersion: 'phoenix-encoder-vector-index/v1',
        authority: 'real_encoder',
        sourceSnapshotId: snapshot.id,
        sourceRegistryHash: registry.contract.identityHash,
        modelId: page.modelId,
        modelVersion: page.modelVersion,
        executionProvider: page.executionProvider,
        dimensions: page.dimensions,
        generation: page.generation,
        vectorCount: page.targetIds.length,
        normalized: true,
        metric: 'cosine',
        indexMethod: 'bounded-lsh',
        candidateOnly: true,
        committedTopologyWrites: 0,
        neighborhoodK: config.neighborhoodK,
        minimumSimilarity: config.minimumSimilarity,
        lshBands: config.lshBands,
        lshBits: config.lshBits,
        maxCandidatesPerTarget: config.maxCandidatesPerTarget,
        evaluatedPairs,
        neighborhoodCount: neighborhoods.length,
        neighborCount,
        missingRegistryTargets,
        rejectedVectors: 0,
        indexHash: vectorIndexHash(page, values, registry.contract.identityHash),
        neighborhoodHash: neighborhoodRowsHash(neighborhoods),
    };
    const neighborhoodByTargetId = new Map(neighborhoods.map((row) => [row.sourceTargetId, row]));

    return {
        contract,
        targetIds: page.targetIds,
        values,
        neighborhoods,
        vector: (targetId) => {
            const row = rowByTargetId.get(targetId);
            return row === undefined
                ? undefined
                : values.subarray(row * page.dimensions, (row + 1) * page.dimensions);
        },
        neighborhood: (targetId) => neighborhoodByTargetId.get(targetId),
        query: (vector, queryOptions = {}) => queryVectorIndex(
            page.targetIds,
            values,
            page.dimensions,
            lsh.buckets,
            lsh.signatureSpace,
            config,
            vector,
            queryOptions,
        ),
    };
}

function validatePrebuiltNeighborhoods(
    build: GraphEncoderNeighborhoodBuild,
    targetIds: readonly string[],
    rowByTargetId: ReadonlyMap<string, number>,
    options: NormalizedGraphEncoderVectorIndexOptions,
): { neighborhoods: GraphEncoderCandidateNeighborhood[]; evaluatedPairs: number } {
    if (
        !Number.isInteger(build.evaluatedPairs)
        || build.evaluatedPairs < 0
        || build.evaluatedPairs > targetIds.length * options.maxCandidatesPerTarget
    ) {
        throw new Error('Prebuilt encoder neighborhood work exceeded its bounded contract');
    }
    if (build.neighborhoods.length !== targetIds.length) {
        throw new Error('Prebuilt encoder neighborhood rows do not match the vector page');
    }
    const neighborhoods = build.neighborhoods.map((row, sourceRow) => {
        if (row.sourceTargetId !== targetIds[sourceRow]) {
            throw new Error(`Prebuilt encoder source identity drift: ${row.sourceTargetId}`);
        }
        if (row.neighbors.length > options.neighborhoodK) {
            throw new Error(`Prebuilt encoder neighborhood exceeded K: ${row.sourceTargetId}`);
        }
        const seen = new Set<string>();
        let previousScore = Number.POSITIVE_INFINITY;
        const neighbors = row.neighbors.map((neighbor, rank) => {
            const targetRow = rowByTargetId.get(neighbor.targetId);
            if (
                targetRow === undefined
                || targetRow === sourceRow
                || seen.has(neighbor.targetId)
                || neighbor.rank !== rank + 1
                || !Number.isFinite(neighbor.score)
                || neighbor.score < options.minimumSimilarity
                || neighbor.score > 1
                || neighbor.score < -1
                || neighbor.score > previousScore
            ) {
                throw new Error(`Prebuilt encoder neighbor receipt is invalid: ${neighbor.targetId}`);
            }
            seen.add(neighbor.targetId);
            previousScore = neighbor.score;
            return { ...neighbor };
        });
        return { sourceTargetId: row.sourceTargetId, neighbors };
    });
    return { neighborhoods, evaluatedPairs: build.evaluatedPairs };
}

export function installGraphEncoderVectorIndex(
    snapshot: GraphRebuildSnapshot,
    index: GraphEncoderVectorIndex,
): void {
    snapshot.encoderVectorIndex = index.contract;
    snapshot.embeddingVectors = index.targetIds.map((targetId) => ({
        targetId,
        modelId: index.contract.modelId,
        dims: index.contract.dimensions,
        generation: index.contract.generation,
    }));
    snapshot.counters.embeddingVectors = index.contract.vectorCount;
    snapshot.counters.encoderIndexedTargets = index.contract.vectorCount;
    snapshot.counters.encoderCandidateNeighborhoods = index.contract.neighborhoodCount;
    snapshot.counters.encoderCandidateNeighbors = index.contract.neighborCount;
    snapshot.counters.encoderEvaluatedPairs = index.contract.evaluatedPairs;
}

export function assertGraphEncoderVectorIndex(snapshot: GraphRebuildSnapshot): void {
    const contract = snapshot.encoderVectorIndex;
    if (!contract) return;
    if (
        contract.authority !== 'real_encoder'
        || !contract.candidateOnly
        || contract.committedTopologyWrites !== 0
    ) {
        throw new Error(`Encoder vector index crossed the graph truth boundary for ${snapshot.id}`);
    }
    const registry = assertGraphEvidenceTargetRegistry(snapshot);
    const exposedIds = new Set(registry.exposedTargets.map((target) => target.id));
    const vectorTargetIds = new Set<string>();
    for (const vector of snapshot.embeddingVectors) {
        if (
            !exposedIds.has(vector.targetId)
            || vectorTargetIds.has(vector.targetId)
            || vector.modelId !== contract.modelId
            || vector.dims !== contract.dimensions
            || vector.generation !== contract.generation
        ) {
            throw new Error(`Encoder vector receipt row is invalid: ${vector.targetId}`);
        }
        vectorTargetIds.add(vector.targetId);
    }
    if (
        contract.sourceSnapshotId !== snapshot.id
        || contract.sourceRegistryHash !== registry.contract.identityHash
        || contract.vectorCount !== snapshot.embeddingVectors.length
        || contract.neighborhoodCount > contract.vectorCount
        || contract.neighborCount > contract.vectorCount * contract.neighborhoodK
        || contract.evaluatedPairs > contract.vectorCount * contract.maxCandidatesPerTarget
        || snapshot.counters.encoderIndexedTargets !== contract.vectorCount
        || snapshot.counters.encoderCandidateNeighborhoods !== contract.neighborhoodCount
        || snapshot.counters.encoderCandidateNeighbors !== contract.neighborCount
        || snapshot.counters.encoderEvaluatedPairs !== contract.evaluatedPairs
    ) {
        throw new Error(`Encoder vector index receipt drift for ${snapshot.id}`);
    }
}

export interface NormalizedGraphEncoderVectorIndexOptions {
    neighborhoodK: number;
    minimumSimilarity: number;
    lshBands: number;
    lshBits: number;
    maxCandidatesPerTarget: number;
    requireCompleteRegistry: boolean;
}

export function normalizeGraphEncoderVectorIndexOptions(
    options: GraphEncoderVectorIndexOptions,
): NormalizedGraphEncoderVectorIndexOptions {
    const neighborhoodK = boundedInt(options.neighborhoodK, DEFAULT_K, 1, 64);
    return {
        neighborhoodK,
        minimumSimilarity: boundedNumber(options.minimumSimilarity, DEFAULT_MINIMUM_SIMILARITY, -1, 1),
        lshBands: boundedInt(options.lshBands, DEFAULT_LSH_BANDS, 1, 12),
        lshBits: boundedInt(options.lshBits, DEFAULT_LSH_BITS, 4, 20),
        maxCandidatesPerTarget: boundedInt(
            options.maxCandidatesPerTarget,
            DEFAULT_MAX_CANDIDATES,
            neighborhoodK,
            512,
        ),
        requireCompleteRegistry: options.requireCompleteRegistry !== false,
    };
}

function assertPageShape(page: GraphEncoderVectorPage): void {
    if (!page.modelId.trim() || !page.modelVersion.trim()) throw new Error('Encoder identity is required');
    if (!['native-rust', 'transformers-worker', 'external-encoder'].includes(page.executionProvider)) {
        throw new Error(`Encoder execution provider is not real: ${page.executionProvider}`);
    }
    if (!Number.isInteger(page.dimensions) || page.dimensions <= 0) throw new Error('Encoder dimensions are invalid');
    if (!Number.isInteger(page.generation) || page.generation < 0) throw new Error('Encoder generation is invalid');
    if (page.values.length !== page.targetIds.length * page.dimensions) {
        throw new Error('Encoder vector page shape does not match target identities');
    }
}

function normalizedPageValues(page: GraphEncoderVectorPage): Float32Array {
    const values = page.normalized ? page.values : new Float32Array(page.values.length);
    for (let row = 0; row < page.targetIds.length; row += 1) {
        const offset = row * page.dimensions;
        let normSquared = 0;
        for (let dim = 0; dim < page.dimensions; dim += 1) {
            const value = page.values[offset + dim];
            if (!Number.isFinite(value)) throw new Error(`Encoder vector is not finite: ${page.targetIds[row]}`);
            normSquared += value * value;
        }
        const norm = Math.sqrt(normSquared);
        if (!(norm > 0)) throw new Error(`Encoder vector has zero norm: ${page.targetIds[row]}`);
        if (page.normalized) {
            if (Math.abs(norm - 1) > 0.025) throw new Error(`Encoder vector is not unit normalized: ${page.targetIds[row]}`);
        } else {
            const inverse = 1 / norm;
            for (let dim = 0; dim < page.dimensions; dim += 1) {
                values[offset + dim] = page.values[offset + dim] * inverse;
            }
        }
    }
    return values;
}

interface PackedLshBuckets {
    buckets: Map<number, number[]>;
    signatures: Uint32Array;
    signatureSpace: number;
}

function buildLshBuckets(
    targetIds: readonly string[],
    values: Float32Array,
    dimensions: number,
    options: NormalizedGraphEncoderVectorIndexOptions,
): PackedLshBuckets {
    const buckets = new Map<number, number[]>();
    const signatures = new Uint32Array(targetIds.length * options.lshBands);
    const signatureSpace = 2 ** options.lshBits;
    for (let row = 0; row < targetIds.length; row += 1) {
        const offset = row * dimensions;
        for (let band = 0; band < options.lshBands; band += 1) {
            let signature = 0;
            for (let bit = 0; bit < options.lshBits; bit += 1) {
                const dim = lshDimension(band, bit, dimensions);
                if (values[offset + dim] >= 0) signature |= 1 << bit;
            }
            signatures[row * options.lshBands + band] = signature;
            const key = band * signatureSpace + signature;
            const bucket = buckets.get(key);
            if (bucket) bucket.push(row);
            else buckets.set(key, [row]);
        }
    }
    return { buckets, signatures, signatureSpace };
}

function buildCandidateNeighborhoods(
    targetIds: readonly string[],
    values: Float32Array,
    dimensions: number,
    lsh: PackedLshBuckets,
    options: NormalizedGraphEncoderVectorIndexOptions,
): { neighborhoods: GraphEncoderCandidateNeighborhood[]; evaluatedPairs: number } {
    const neighborhoods: GraphEncoderCandidateNeighborhood[] = [];
    const candidateRows = new Uint32Array(options.maxCandidatesPerTarget);
    const candidateMarks = new Uint32Array(targetIds.length);
    const topRows = new Uint32Array(options.neighborhoodK);
    const topScores = new Float64Array(options.neighborhoodK);
    let evaluatedPairs = 0;
    for (let source = 0; source < targetIds.length; source += 1) {
        let candidateCount = 0;
        const mark = source + 1;
        for (let band = 0; band < options.lshBands && candidateCount < options.maxCandidatesPerTarget; band += 1) {
            const signature = lsh.signatures[source * options.lshBands + band];
            candidateCount = addPackedBucketCandidates(
                candidateRows,
                candidateMarks,
                candidateCount,
                lsh.buckets.get(band * lsh.signatureSpace + signature) || [],
                source,
                targetIds[source],
                options.maxCandidatesPerTarget,
                mark,
            );
        }
        let topCount = 0;
        for (let candidateIndex = 0; candidateIndex < candidateCount; candidateIndex += 1) {
            const target = candidateRows[candidateIndex];
            evaluatedPairs += 1;
            const score = cosineRow(values, dimensions, source, target);
            if (score < options.minimumSimilarity) continue;
            topCount = insertBoundedNeighbor(
                topRows,
                topScores,
                topCount,
                target,
                score,
                targetIds,
            );
        }
        const neighbors = new Array(topCount);
        for (let rank = 0; rank < topCount; rank += 1) {
            neighbors[rank] = {
                targetId: targetIds[topRows[rank]],
                score: roundScore(topScores[rank]),
                rank: rank + 1,
            };
        }
        neighborhoods.push({
            sourceTargetId: targetIds[source],
            neighbors,
        });
    }
    return { neighborhoods, evaluatedPairs };
}

function queryVectorIndex(
    targetIds: readonly string[],
    values: Float32Array,
    dimensions: number,
    buckets: Map<number, number[]>,
    signatureSpace: number,
    indexOptions: NormalizedGraphEncoderVectorIndexOptions,
    query: Float32Array,
    options: GraphEncoderVectorQueryOptions,
): GraphEncoderVectorQueryResult {
    if (query.length !== dimensions) {
        throw new Error(`Encoder query dimension drift: got ${query.length}, expected ${dimensions}`);
    }
    const normalized = normalizeQueryVector(query);
    const limit = boundedInt(options.limit, indexOptions.neighborhoodK, 1, 256);
    const minimumSimilarity = boundedNumber(
        options.minimumSimilarity,
        indexOptions.minimumSimilarity,
        -1,
        1,
    );
    const maxCandidates = boundedInt(
        options.maxCandidates,
        Math.max(indexOptions.maxCandidatesPerTarget, limit),
        limit,
        2048,
    );
    const candidates = new Set<number>();
    const queryKey = vectorSignatureHash(normalized);
    for (let band = 0; band < indexOptions.lshBands && candidates.size < maxCandidates; band += 1) {
        const signature = lshSignature(normalized, 0, dimensions, band, indexOptions.lshBits);
        addQueryBucketCandidates(
            candidates,
            buckets.get(band * signatureSpace + signature) || [],
            queryKey,
            maxCandidates,
        );
    }
    const scored = [...candidates]
        .map((row) => ({ row, score: cosineVectorRow(normalized, values, dimensions, row) }))
        .filter((candidate) => candidate.score >= minimumSimilarity)
        .sort((left, right) => right.score - left.score || targetIds[left.row].localeCompare(targetIds[right.row]))
        .slice(0, limit)
        .map((candidate, rank) => ({
            targetId: targetIds[candidate.row],
            score: roundScore(candidate.score),
            rank: rank + 1,
        }));
    return {
        neighbors: scored,
        evaluatedCandidates: candidates.size,
        truncated: candidates.size >= maxCandidates,
    };
}

function addPackedBucketCandidates(
    out: Uint32Array,
    marks: Uint32Array,
    count: number,
    bucket: readonly number[],
    source: number,
    sourceTargetId: string,
    limit: number,
    mark: number,
): number {
    if (bucket.length < 2 || count >= limit) return count;
    const start = hashText(sourceTargetId) % bucket.length;
    for (let step = 0; step < bucket.length && count < limit; step += 1) {
        const candidate = bucket[(start + step) % bucket.length];
        if (candidate === source || marks[candidate] === mark) continue;
        marks[candidate] = mark;
        out[count++] = candidate;
    }
    return count;
}

function insertBoundedNeighbor(
    rows: Uint32Array,
    scores: Float64Array,
    count: number,
    row: number,
    score: number,
    targetIds: readonly string[],
): number {
    let insertion = count;
    while (insertion > 0 && neighborRanksBefore(
        score,
        row,
        scores[insertion - 1],
        rows[insertion - 1],
        targetIds,
    )) insertion -= 1;
    if (insertion >= rows.length) return count;
    const nextCount = Math.min(rows.length, count + 1);
    for (let index = nextCount - 1; index > insertion; index -= 1) {
        rows[index] = rows[index - 1];
        scores[index] = scores[index - 1];
    }
    rows[insertion] = row;
    scores[insertion] = score;
    return nextCount;
}

function neighborRanksBefore(
    score: number,
    row: number,
    otherScore: number,
    otherRow: number,
    targetIds: readonly string[],
): boolean {
    return score > otherScore
        || (score === otherScore && targetIds[row].localeCompare(targetIds[otherRow]) < 0);
}

function addQueryBucketCandidates(
    out: Set<number>,
    bucket: readonly number[],
    queryKey: number,
    limit: number,
): void {
    if (!bucket.length || out.size >= limit) return;
    const start = queryKey % bucket.length;
    for (let step = 0; step < bucket.length && out.size < limit; step += 1) {
        out.add(bucket[(start + step) % bucket.length]);
    }
}

function normalizeQueryVector(query: Float32Array): Float32Array {
    let normSquared = 0;
    for (const value of query) {
        if (!Number.isFinite(value)) throw new Error('Encoder query vector is not finite');
        normSquared += value * value;
    }
    const norm = Math.sqrt(normSquared);
    if (!(norm > 0)) throw new Error('Encoder query vector has zero norm');
    const normalized = new Float32Array(query.length);
    const inverse = 1 / norm;
    for (let dim = 0; dim < query.length; dim += 1) normalized[dim] = query[dim] * inverse;
    return normalized;
}

function cosineRow(values: Float32Array, dimensions: number, left: number, right: number): number {
    const leftOffset = left * dimensions;
    const rightOffset = right * dimensions;
    let dot = 0;
    let dim = 0;
    const wideEnd = dimensions - (dimensions % 8);
    for (; dim < wideEnd; dim += 8) {
        dot += values[leftOffset + dim] * values[rightOffset + dim];
        dot += values[leftOffset + dim + 1] * values[rightOffset + dim + 1];
        dot += values[leftOffset + dim + 2] * values[rightOffset + dim + 2];
        dot += values[leftOffset + dim + 3] * values[rightOffset + dim + 3];
        dot += values[leftOffset + dim + 4] * values[rightOffset + dim + 4];
        dot += values[leftOffset + dim + 5] * values[rightOffset + dim + 5];
        dot += values[leftOffset + dim + 6] * values[rightOffset + dim + 6];
        dot += values[leftOffset + dim + 7] * values[rightOffset + dim + 7];
    }
    for (; dim < dimensions; dim += 1) dot += values[leftOffset + dim] * values[rightOffset + dim];
    return Math.max(-1, Math.min(1, dot));
}

function cosineVectorRow(query: Float32Array, values: Float32Array, dimensions: number, row: number): number {
    const offset = row * dimensions;
    let dot = 0;
    let dim = 0;
    const wideEnd = dimensions - (dimensions % 8);
    for (; dim < wideEnd; dim += 8) {
        dot += query[dim] * values[offset + dim];
        dot += query[dim + 1] * values[offset + dim + 1];
        dot += query[dim + 2] * values[offset + dim + 2];
        dot += query[dim + 3] * values[offset + dim + 3];
        dot += query[dim + 4] * values[offset + dim + 4];
        dot += query[dim + 5] * values[offset + dim + 5];
        dot += query[dim + 6] * values[offset + dim + 6];
        dot += query[dim + 7] * values[offset + dim + 7];
    }
    for (; dim < dimensions; dim += 1) dot += query[dim] * values[offset + dim];
    return Math.max(-1, Math.min(1, dot));
}

function lshSignature(
    values: Float32Array,
    offset: number,
    dimensions: number,
    band: number,
    bits: number,
): number {
    let signature = 0;
    for (let bit = 0; bit < bits; bit += 1) {
        const dim = lshDimension(band, bit, dimensions);
        if (values[offset + dim] >= 0) signature |= 1 << bit;
    }
    return signature;
}

function vectorSignatureHash(vector: Float32Array): number {
    let hash = 0x811c9dc5;
    const words = new Uint32Array(vector.buffer, vector.byteOffset, vector.length);
    for (const word of words) hash = fnvWord(hash, word);
    return hash;
}

function lshDimension(band: number, bit: number, dimensions: number): number {
    return ((band + 1) * 2654435761 + (bit + 1) * 2246822519) % dimensions;
}

function vectorIndexHash(page: GraphEncoderVectorPage, values: Float32Array, registryHash: string): string {
    let hash = hashText(`${page.modelId}\0${page.modelVersion}\0${registryHash}\0${page.dimensions}`);
    const words = new Uint32Array(values.buffer, values.byteOffset, values.length);
    for (const targetId of page.targetIds) hash = fnvWord(hash, hashText(targetId));
    for (let index = 0; index < words.length; index += 1) hash = fnvWord(hash, words[index]);
    return `fnv32-${hash.toString(16).padStart(8, '0')}`;
}

function neighborhoodRowsHash(neighborhoods: readonly GraphEncoderCandidateNeighborhood[]): string {
    let hash = 0x811c9dc5;
    for (const row of neighborhoods) {
        hash = fnvWord(hash, hashText(row.sourceTargetId));
        for (const neighbor of row.neighbors) {
            hash = fnvWord(hash, hashText(neighbor.targetId));
            hash = fnvWord(hash, hashText(`${neighbor.rank}:${neighbor.score}`));
        }
    }
    return `fnv32-${hash.toString(16).padStart(8, '0')}`;
}

function hashText(value: string): number {
    let hash = 0x811c9dc5;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash;
}

function fnvWord(hash: number, word: number): number {
    let out = hash;
    for (let byte = 0; byte < 4; byte += 1) {
        out ^= (word >>> (byte * 8)) & 0xff;
        out = Math.imul(out, 0x01000193) >>> 0;
    }
    return out;
}

function boundedInt(value: number | undefined, fallback: number, min: number, max: number): number {
    const normalized = Number.isFinite(value) ? Math.floor(value as number) : fallback;
    return Math.max(min, Math.min(max, normalized));
}

function boundedNumber(value: number | undefined, fallback: number, min: number, max: number): number {
    const normalized = Number.isFinite(value) ? Number(value) : fallback;
    return Math.max(min, Math.min(max, normalized));
}

function roundScore(value: number): number {
    return Math.round(value * 1_000_000) / 1_000_000;
}
