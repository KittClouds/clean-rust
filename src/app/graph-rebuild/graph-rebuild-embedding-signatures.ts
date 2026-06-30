import type {
    GraphRebuildEmbeddingModelAdapter,
    GraphRebuildEmbeddingNormalization,
    GraphIndexModelSelection,
    GraphRebuildEmbeddingProfile,
    GraphRebuildEmbeddingTarget,
    GraphRebuildEmbeddingTopologySupport,
    GraphRebuildEmbeddingVectorHead,
} from './graph-rebuild-snapshot';
import { DEFAULT_GRAPH_EMBEDDING_MODEL_ID } from '../lib/embeddings/models/ModelRegistry';

export interface SparseEmbeddingSignature {
    indexes: Uint32Array;
    values: Float32Array;
}

export function embeddingProfileFromModelSelection(
    selection: GraphIndexModelSelection,
): Partial<GraphRebuildEmbeddingProfile> {
    return profileFromEmbeddingAdapter(embeddingModelAdapterFromSelection(selection));
}

export function embeddingModelAdapterFromSelection(
    selection: GraphIndexModelSelection,
): GraphRebuildEmbeddingModelAdapter {
    return embeddingModelAdapterFromConfig({
        modelId: selection.embeddingModelId,
        modelLabel: selection.embeddingModelLabel || selection.embeddingModelId,
        dimensionLabel: selection.embeddingDimensionLabel,
        vectorSource: 'signature-preview',
    });
}

export function embeddingModelAdapterFromProfile(
    profile: Partial<GraphRebuildEmbeddingProfile> | undefined,
): GraphRebuildEmbeddingModelAdapter {
    return embeddingModelAdapterFromConfig(profile || {});
}

export function profileFromEmbeddingAdapter(adapter: GraphRebuildEmbeddingModelAdapter): GraphRebuildEmbeddingProfile {
    return {
        schemaVersion: 'phoenix-embedding-profile/v1',
        modelId: adapter.modelId,
        modelLabel: adapter.modelLabel,
        modelFamily: adapter.modelFamily,
        dimensionLabel: adapter.dimensionLabel,
        nativeDimensions: adapter.nativeDimensions,
        selectedDimensions: adapter.selectedDimensions,
        taskProfile: adapter.taskProfile,
        vectorSource: adapter.vectorSource,
        normalized: adapter.normalized,
        normalization: adapter.normalization,
        topologySupport: adapter.topologySupport,
        supportsMultiVector: adapter.supportsMultiVector,
        vectorHeads: adapter.vectorHeads,
    };
}

export function normalizeEmbeddingProfile(
    profile: Partial<GraphRebuildEmbeddingProfile> | undefined,
): GraphRebuildEmbeddingProfile {
    return profileFromEmbeddingAdapter(embeddingModelAdapterFromProfile(profile));
}

interface EmbeddingAdapterConfig extends Partial<GraphRebuildEmbeddingProfile> {
    supportsTopology?: boolean;
    supportsMultiTask?: boolean;
}

function embeddingModelAdapterFromConfig(config: EmbeddingAdapterConfig): GraphRebuildEmbeddingModelAdapter {
    const modelId = config.modelId || DEFAULT_GRAPH_EMBEDDING_MODEL_ID;
    const modelLabel = config.modelLabel || modelId;
    const family = config.modelFamily || modelFamily(modelId, modelLabel);
    const nativeDimensions = positiveInt(config.nativeDimensions)
        || dimensionsFromLabel(config.dimensionLabel)
        || defaultNativeDimensions(modelId, modelLabel);
    const selectedDimensions = positiveInt(config.selectedDimensions)
        || dimensionsFromLabel(config.dimensionLabel)
        || nativeDimensions;
    const normalized = config.normalized ?? true;
    const normalization = config.normalization || normalizationMode(normalized);
    const task = config.taskProfile || taskProfile(modelId, modelLabel);
    const topologySupport = config.topologySupport || topologySupportForModel(family, task);
    const vectorHeads = normalizeVectorHeads(
        config.vectorHeads,
        family,
        selectedDimensions,
        normalized,
    );

    return {
        schemaVersion: 'phoenix-embedding-model-adapter/v1',
        modelId,
        modelLabel,
        modelFamily: family,
        dimensionLabel: config.dimensionLabel || `${selectedDimensions}d`,
        nativeDimensions,
        selectedDimensions,
        taskProfile: task,
        vectorSource: config.vectorSource || 'signature-preview',
        normalized,
        normalization,
        topologySupport,
        supportsTopology: config.supportsTopology ?? topologySupport !== 'none',
        supportsMultiTask: config.supportsMultiTask ?? task === 'multi_task',
        supportsMultiVector: config.supportsMultiVector ?? vectorHeads.length > 1,
        vectorHeads,
    };
}

export function embeddingTargetText(target: GraphRebuildEmbeddingTarget): string {
    return `${target.kind} ${target.entityKind || ''} ${target.label} ${target.text} ${target.noteId || ''} ${target.chunkId || ''}`;
}

export function sparseEmbeddingSignature(
    target: GraphRebuildEmbeddingTarget,
    dimensions: number,
): SparseEmbeddingSignature {
    const dim = Math.max(8, Math.floor(dimensions));
    const weights = new Map<number, number>();
    const tokens = embeddingTargetText(target).toLowerCase().match(/[a-z0-9_'-]+/g) || [target.id || 'graph'];
    for (const token of tokens) {
        const seed = hash(token);
        addWeight(weights, seed % dim, 1);
        addWeight(weights, (seed >>> 5) % dim, 0.5);
    }
    return sparseFromWeights(weights);
}

export function sparseToDenseVector(signature: SparseEmbeddingSignature, dimensions: number): Float32Array {
    const vector = new Float32Array(Math.max(8, Math.floor(dimensions)));
    for (let index = 0; index < signature.indexes.length; index += 1) {
        vector[signature.indexes[index]] = signature.values[index];
    }
    return vector;
}

export function sparseCosine(left: SparseEmbeddingSignature, right: SparseEmbeddingSignature): number {
    let i = 0;
    let j = 0;
    let dot = 0;
    while (i < left.indexes.length && j < right.indexes.length) {
        const a = left.indexes[i];
        const b = right.indexes[j];
        if (a === b) {
            dot += left.values[i] * right.values[j];
            i += 1;
            j += 1;
        } else if (a < b) {
            i += 1;
        } else {
            j += 1;
        }
    }
    return Math.max(0, Math.min(1, dot));
}

function sparseFromWeights(weights: Map<number, number>): SparseEmbeddingSignature {
    const entries = [...weights.entries()].sort((left, right) => left[0] - right[0]);
    let norm = 0;
    for (const [, value] of entries) norm += value * value;
    const inv = 1 / (Math.sqrt(norm) || 1);
    const indexes = new Uint32Array(entries.length);
    const values = new Float32Array(entries.length);
    for (let index = 0; index < entries.length; index += 1) {
        indexes[index] = entries[index][0];
        values[index] = entries[index][1] * inv;
    }
    return { indexes, values };
}

function addWeight(weights: Map<number, number>, index: number, weight: number): void {
    weights.set(index, (weights.get(index) || 0) + weight);
}

function dimensionsFromLabel(label: string | undefined): number {
    const match = String(label || '').match(/(\d+)/);
    return match ? positiveInt(Number(match[1])) : 0;
}

function defaultNativeDimensions(modelId: string, modelLabel = ''): number {
    const text = `${modelId} ${modelLabel}`;
    if (/jina.*v5/i.test(text)) return 768;
    if (/embeddinggemma|embedding.*gemma|gemma.*embedding/i.test(text)) return 768;
    if (/(mdbr|mongodb.*leaf|leaf).*mt|mt.*(mdbr|leaf)/i.test(text)) return 384;
    return 384;
}

function modelFamily(modelId: string, modelLabel = ''): string {
    const text = `${modelId} ${modelLabel}`;
    if (/jina.*v5/i.test(text)) return 'jina-v5';
    if (/embeddinggemma|embedding.*gemma|gemma.*embedding/i.test(text)) return 'embeddinggemma';
    if (/(mdbr|mongodb.*leaf|leaf).*mt|mt.*(mdbr|leaf)/i.test(text)) return 'mdbr-leaf-mt';
    if (/mdbr|mongodb.*leaf|leaf/i.test(text)) return 'mdbr-leaf';
    if (/bge/i.test(text)) return 'bge';
    return 'unknown';
}

function taskProfile(modelId: string, modelLabel = ''): GraphRebuildEmbeddingProfile['taskProfile'] {
    const text = `${modelId} ${modelLabel}`;
    if (/(mdbr|mongodb.*leaf|leaf).*mt|mt.*(mdbr|leaf)/i.test(text)) return 'multi_task';
    if (/jina.*v5/i.test(text) && !/retrieval|query|ir/i.test(text)) return 'semantic_topology';
    if (/embeddinggemma|embedding.*gemma|gemma.*embedding/i.test(text)) return 'semantic_topology';
    if (/mdbr|mongodb.*leaf|leaf/i.test(text)) return 'retrieval';
    if (/ir|retrieval|bge/i.test(text)) return 'retrieval';
    if (/jina.*v5/i.test(text)) return 'semantic_topology';
    return 'unknown';
}

function normalizationMode(normalized: boolean): GraphRebuildEmbeddingNormalization {
    return normalized ? 'unit_l2' : 'none';
}

function topologySupportForModel(
    family: string,
    task: GraphRebuildEmbeddingProfile['taskProfile'],
): GraphRebuildEmbeddingTopologySupport {
    if (family === 'mdbr-leaf-mt' || family === 'jina-v5') return 'native';
    if (task === 'unknown') return 'none';
    return 'derived';
}

function normalizeVectorHeads(
    heads: GraphRebuildEmbeddingVectorHead[] | undefined,
    family: string,
    dimensions: number,
    normalized: boolean,
): GraphRebuildEmbeddingVectorHead[] {
    const source = heads && heads.length ? heads : defaultVectorHeads(family, dimensions, normalized);
    const seen = new Set<string>();
    const out: GraphRebuildEmbeddingVectorHead[] = [];
    for (const head of source) {
        const id = head.id || head.kind;
        if (seen.has(id)) continue;
        seen.add(id);
        out.push({
            id,
            kind: head.kind || 'dense',
            dimensions: positiveInt(head.dimensions) || dimensions,
            normalized: head.normalized ?? normalized,
            required: head.required ?? (id === 'dense' || id === 'document'),
            purpose: head.purpose || headPurpose(id, head.kind || 'dense'),
        });
    }
    return out.length ? out : defaultVectorHeads('unknown', dimensions, normalized);
}

function defaultVectorHeads(
    family: string,
    dimensions: number,
    normalized: boolean,
): GraphRebuildEmbeddingVectorHead[] {
    if (family === 'mdbr-leaf-mt') {
        return [
            vectorHead('document', 'document', dimensions, normalized, true, 'document and chunk topology vectors'),
            vectorHead('query', 'query', dimensions, normalized, false, 'query-side retrieval vectors'),
            vectorHead('topology', 'topology', dimensions, normalized, false, 'cluster and product-lane vectors'),
            vectorHead('classification', 'classification', dimensions, normalized, false, 'task or genre classification vectors'),
        ];
    }
    if (family === 'jina-v5') {
        return [
            vectorHead('document', 'document', dimensions, normalized, true, 'document and graph topology vectors'),
            vectorHead('query', 'query', dimensions, normalized, false, 'query-side retrieval vectors'),
            vectorHead('topology', 'topology', dimensions, normalized, false, 'product manifold topology vectors'),
            vectorHead('classification', 'classification', dimensions, normalized, false, 'lane and evidence-bundle classification vectors'),
        ];
    }
    return [
        vectorHead('dense', 'dense', dimensions, normalized, true, 'single dense semantic vector'),
    ];
}

function vectorHead(
    id: string,
    kind: GraphRebuildEmbeddingVectorHead['kind'],
    dimensions: number,
    normalized: boolean,
    required: boolean,
    purpose: string,
): GraphRebuildEmbeddingVectorHead {
    return { id, kind, dimensions, normalized, required, purpose };
}

function headPurpose(id: string, kind: GraphRebuildEmbeddingVectorHead['kind']): string {
    if (id === 'dense' || kind === 'dense') return 'single dense semantic vector';
    if (kind === 'query') return 'query-side retrieval vectors';
    if (kind === 'document') return 'document and graph vectors';
    if (kind === 'topology') return 'cluster and product-lane vectors';
    if (kind === 'classification') return 'task or genre classification vectors';
    return 'embedding vector head';
}

function positiveInt(value: unknown): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
}

function hash(value: string): number {
    let out = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        out ^= value.charCodeAt(index);
        out = Math.imul(out, 16777619);
    }
    return out >>> 0;
}
