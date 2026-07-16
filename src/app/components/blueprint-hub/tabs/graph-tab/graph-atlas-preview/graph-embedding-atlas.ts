import type { Note, NoteBlockProjection } from '../../../../../lib/dexie/db';
import type {
    AtlasManifoldMode,
    ConeObstructionRecord,
    ConePathletRecord,
    ManifoldCapabilities,
    ManifoldProjectionSource,
    ManifoldTopologyPayload,
} from '../../../../../services/manifold-atlas.types';
import {
    normalizeEntityKind,
    normalizeGraphNodeColorKind,
} from '../../../../../lib/store/entityColorStore';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import {
    graphTopologyDisplayColorKind,
    graphTopologyStyleForPacketRow,
} from './graph-topology-style-contract';

export interface EmbeddingAtlasData {
    nodes: GalaxyRenderableNode[];
    edges: GalaxyInputEdge[];
    sourceLabel: string;
    searchIndex: EmbeddingAtlasSearchItem[];
    manifold?: EmbeddingAtlasManifoldMetadata;
}

export interface EmbeddingAtlasManifoldMetadata extends ManifoldTopologyPayload {
    mode: AtlasManifoldMode;
    geometryVersion: string;
    sourceLabel: string;
    capabilities: ManifoldCapabilities;
    projectionSource?: ManifoldProjectionSource | string;
    compileTimings?: Record<string, number>;
}

export interface EmbeddingAtlasSearchItem {
    nodeId: string;
    vector: Float32Array;
}

export interface EmbeddingSourcePreview {
    nodeId: string;
    label: string;
    score: number;
    sourceType: string;
    preview: string;
}

export interface EmbeddingQueryTrace {
    query: string;
    queryNode: GalaxyRenderableNode;
    primaryIds: string[];
    secondaryIds: string[];
    edgeIds: string[];
    edges: GalaxyInputEdge[];
    previews: EmbeddingSourcePreview[];
    manifoldTrace?: EmbeddingManifoldTrace;
}

export interface EmbeddingManifoldTrace {
    mode: AtlasManifoldMode;
    geometryVersion: string;
    coneId?: string;
    programId?: string;
    pathletIds?: string[];
    obstructionIds?: string[];
    cellIds: string[];
    chartIds: string[];
    pathEdgeIds: string[];
}

export interface BackendEmbeddingAtlasNode {
    id: string;
    label: string;
    sourceType: string;
    vector: number[];
    documentId?: string;
    narrativeId?: string;
    folderId?: string;
    preview?: string;
    kind?: string;
    baseVector?: [number, number, number];
    cellId?: string;
    secondaryCellIds?: string[];
    cellDistance?: number;
    boundaryScore?: number;
    phase?: number;
    fiberKind?: string;
    geometryVersion?: string;
}

export interface BackendEmbeddingAtlasEdge {
    id: string;
    sourceId: string;
    targetId: string;
    type: string;
    confidence: number;
    metadata?: Record<string, unknown>;
}

export interface BackendEmbeddingAtlasPayload extends ManifoldTopologyPayload {
    nodes: BackendEmbeddingAtlasNode[];
    edges: BackendEmbeddingAtlasEdge[];
    sourceLabel: string;
}

interface Signature {
    vector: Float32Array;
    tokens: number;
}

const DIMS = 32;
const EMBEDDING_SHELL_RADIUS = 1.52;
const EMBEDDING_SHELL_SMALL_RADIUS = 1.08;

interface EmbeddingAtlasStyle {
    renderKind: string;
    colorKind: string;
    entityKind: string;
    colorHsl: string;
    metadata: Record<string, string | undefined>;
}

function embeddingAtlasStyle(input: {
    kind?: string;
    sourceType?: string;
    label?: string;
    styleKey?: string;
}): EmbeddingAtlasStyle {
    const sourceType = String(input.sourceType || '').trim();
    const kind = String(input.kind || '').trim();
    const styleKey = String(input.styleKey || '').trim();
    const graphKind = normalizeGraphNodeColorKind(styleKey)
        || normalizeGraphNodeColorKind(kind)
        || normalizeGraphNodeColorKind(sourceType);
    const entityKind = graphKind ? null : normalizeEntityKind(styleKey) || normalizeEntityKind(kind) || normalizeEntityKind(sourceType);
    if (entityKind) {
        return {
            renderKind: displayKind(kind || sourceType || entityKind),
            colorKind: displayKind(entityKind),
            entityKind,
            colorHsl: graphTopologyStyleForPacketRow({
                family: 'entity',
                kind: entityKind,
                label: input.label || entityKind,
                styleKey: entityKind,
            }).colorHsl,
            metadata: { entityKind },
        };
    }

    const colorKind = graphKind || 'graphFact';
    const style = graphTopologyStyleForPacketRow({
        family: graphStructureFamily(colorKind),
        kind: colorKind,
        label: input.label || kind || sourceType || colorKind,
        styleKey: colorKind,
    });
    const displayColorKind = graphTopologyDisplayColorKind(style.colorKind);
    return {
        renderKind: renderKindForGraphColor(displayColorKind, kind || sourceType),
        colorKind: displayColorKind,
        entityKind: '',
        colorHsl: style.colorHsl,
        metadata: {
            graphColorKind: displayColorKind,
            graphKind: displayColorKind,
            styleKey: displayColorKind,
        },
    };
}

function graphStructureFamily(colorKind: string): string {
    if (colorKind === 'document' || colorKind === 'episode' || colorKind === 'chunk' || colorKind === 'anchor') return 'structure';
    if (colorKind === 'temporal' || colorKind === 'temporalFact') return 'temporal';
    if (colorKind === 'causal' || colorKind === 'causalFact') return 'causal';
    if (colorKind === 'memoryState') return 'memory';
    return 'fact';
}

function renderKindForGraphColor(colorKind: string, fallback: string): string {
    if (colorKind === 'document') return 'note';
    if (colorKind === 'episode') return 'episode';
    if (colorKind === 'chunk') return 'chunk';
    if (colorKind === 'anchor') return 'anchor';
    return displayKind(fallback || colorKind);
}

function displayKind(kind: string): string {
    return String(kind || '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

export function buildDocEmbeddingAtlas(notes: Note[], limit = 180, topK = 4): EmbeddingAtlasData {
    const selected = notes
        .filter((note) => noteText(note).trim().length > 0)
        .slice(0, limit);
    const signatures = selected.map((note) => textSignature(`${note.title}\n${noteText(note)}`));
    const nodes = selected.map((note, index) => {
        const signature = signatures[index];
        const point = projectSignature(signature.vector, note.id, index, selected.length);
        const style = embeddingAtlasStyle({ kind: 'document', sourceType: 'doc', label: note.title });
        return {
            id: `embed:doc:${note.id}`,
            label: note.title || `Doc ${index + 1}`,
            kind: style.renderKind,
            totalMentions: Math.max(1, Math.round(signature.tokens / 220)),
            atlasX: point.x,
            atlasY: point.y,
            atlasZ: point.z,
            colorHsl: style.colorHsl,
            metadata: {
                ...style.metadata,
                sourceType: 'doc',
                sourceId: note.id,
                sourceTitle: note.title,
                tokenCount: signature.tokens,
                preview: previewText(noteText(note)),
            },
        } satisfies GalaxyRenderableNode;
    });
    return {
        nodes,
        edges: buildKnnEdges(nodes, signatures, topK),
        sourceLabel: 'local preview doc vectors',
        searchIndex: buildSearchIndex(nodes, signatures),
    };
}

export function buildLeafEmbeddingAtlas(blocks: NoteBlockProjection[], limit = 220, topK = 4): EmbeddingAtlasData {
    const selected = blocks
        .filter((block) => block.text.trim().length > 0)
        .slice(0, limit);
    const signatures = selected.map((block) => textSignature(`${block.path}\n${block.text}`));
    const nodes = selected.map((block, index) => {
        const signature = signatures[index];
        const point = projectSignature(signature.vector, block.id, index, selected.length);
        const style = embeddingAtlasStyle({ kind: 'chunk', sourceType: 'leaf', label: block.path });
        return {
            id: `embed:leaf:${block.id}`,
            label: block.path || `Leaf ${index + 1}`,
            kind: style.renderKind,
            totalMentions: Math.max(1, Math.round(signature.tokens / 120)),
            atlasX: point.x,
            atlasY: point.y,
            atlasZ: point.z,
            colorHsl: style.colorHsl,
            metadata: {
                ...style.metadata,
                sourceType: 'leaf',
                sourceId: block.id,
                noteId: block.noteId,
                tokenCount: signature.tokens,
                preview: previewText(block.text),
            },
        } satisfies GalaxyRenderableNode;
    });
    return {
        nodes,
        edges: buildKnnEdges(nodes, signatures, topK),
        sourceLabel: 'local preview leaf vectors',
        searchIndex: buildSearchIndex(nodes, signatures),
    };
}

export function buildBackendEmbeddingAtlas(payload: BackendEmbeddingAtlasPayload, limit = 260, topK = 5): EmbeddingAtlasData {
    const selected = payload.nodes
        .filter((node) => Array.isArray(node.vector) && node.vector.length > 0)
        .slice(0, limit);
    const traversal = buildTraversalMetadata(payload);
    const signatures = selected.map((node) => ({
        vector: normalizeBackendVector(node.vector),
        tokens: Math.max(1, Math.round(node.vector.length / 8)),
    }));
    const nodes = selected.map((node, index) => {
        const signature = signatures[index];
        const point = backendAtlasPoint(node, signature.vector, index, selected.length);
        const hopf = backendHopfMetadata(node);
        const style = embeddingAtlasStyle({ kind: node.kind, sourceType: node.sourceType, label: node.label });
        return {
            id: node.id,
            label: node.label || node.id,
            kind: style.renderKind,
            totalMentions: Math.max(1, signature.tokens),
            atlasX: point.x,
            atlasY: point.y,
            atlasZ: point.z,
            colorHsl: style.colorHsl,
            metadata: {
                ...style.metadata,
                sourceType: node.sourceType || 'semantic_atlas',
                sourceId: node.id,
                documentId: node.documentId,
                narrativeId: node.narrativeId,
                folderId: node.folderId,
                tokenCount: signature.tokens,
                preview: node.preview || `${node.sourceType || 'semantic'} vector from native Semantic Atlas`,
                ...(hopf ? { hopf } : {}),
                ...(traversal.nodeMetadata.get(node.id) ? { productTraversal: traversal.nodeMetadata.get(node.id) } : {}),
            },
        } satisfies GalaxyRenderableNode;
    });
    const nodeIds = new Set(nodes.map((node) => node.id));
    const backendEdges = payload.edges
        .filter((edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId))
        .map((edge) => ({
            id: edge.id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
            type: edge.type || 'semantic-candidate',
            confidence: Number.isFinite(edge.confidence) ? edge.confidence : 0.35,
            metadata: {
                ...(edge.metadata || {}),
                ...(traversal.edgeMetadata.get(edge.id) ? { productTraversal: traversal.edgeMetadata.get(edge.id) } : {}),
            },
        }));
    return {
        nodes,
        edges: backendEdges.length ? backendEdges : buildKnnEdges(nodes, signatures, topK),
        sourceLabel: payload.sourceLabel || 'backend semantic atlas',
        searchIndex: buildSearchIndex(nodes, signatures),
    };
}

function buildTraversalMetadata(payload: ManifoldTopologyPayload): {
    nodeMetadata: Map<string, Record<string, unknown>>;
    edgeMetadata: Map<string, Record<string, unknown>>;
} {
    const nodeMetadata = new Map<string, Record<string, unknown>>();
    const edgeMetadata = new Map<string, Record<string, unknown>>();
    const obstructionById = new Map((payload.obstructions || []).map((obstruction) => [obstruction.obstructionId, obstruction]));
    for (const pathlet of payload.pathlets || []) {
        const obstructionIds = pathlet.obstructionIds || [];
        const obstructions = obstructionIds.map((id) => obstructionById.get(id)).filter(Boolean) as ConeObstructionRecord[];
        const obstructionScore = obstructions.reduce((max, obstruction) => Math.max(max, obstruction.severity), 0);
        const obstructionKind = obstructions[0]?.kind;
        for (const nodeId of pathlet.nodeIds) {
            const current = nodeMetadata.get(nodeId) || {};
            const pathletIds = Array.isArray(current['pathletIds']) ? current['pathletIds'] as string[] : [];
            const currentSupport = Number(current['supportScore'] || 0);
            const currentObstruction = Number(current['obstructionScore'] || 0);
            nodeMetadata.set(nodeId, {
                ...current,
                lane: pathlet.lane,
                pathletIds: [...new Set([...pathletIds, pathlet.pathletId])],
                obstructionIds: [...new Set([...(current['obstructionIds'] as string[] | undefined || []), ...obstructionIds])],
                supportScore: Math.max(currentSupport, pathlet.supportScore),
                obstructionScore: Math.max(currentObstruction, obstructionScore),
                obstructionKind: obstructionKind || current['obstructionKind'],
            });
        }
        for (const edgeId of pathlet.edgeIds) {
            edgeMetadata.set(edgeId, {
                lane: pathlet.lane,
                pathletId: pathlet.pathletId,
                obstructionIds,
                supportScore: pathlet.supportScore,
                obstructionScore,
                obstructionKind,
            });
        }
    }
    return { nodeMetadata, edgeMetadata };
}

function backendAtlasPoint(node: BackendEmbeddingAtlasNode, vector: Float32Array, index: number, total: number): { x: number; y: number; z: number } {
    const base = node.baseVector;
    if (Array.isArray(base) && base.length === 3 && base.every(Number.isFinite)) {
        return { x: base[0], y: base[1], z: base[2] };
    }
    return projectSignature(vector, node.id, index, total);
}

function backendHopfMetadata(node: BackendEmbeddingAtlasNode): Record<string, unknown> | null {
    const sourceType = String(node.sourceType || '').toLowerCase();
    const role = sourceType === 'hopf_anchor'
        ? 'anchor'
        : sourceType === 'hopf_fiber'
            ? 'fiber'
            : '';
    if (!role && !node.cellId) return null;
    return {
        role,
        baseId: hopfBaseId(node.id),
        fiberKind: node.fiberKind,
        cellId: node.cellId,
        secondaryCellIds: node.secondaryCellIds || [],
        cellDistance: node.cellDistance,
        boundaryScore: node.boundaryScore,
        phase: node.phase,
        geometryVersion: node.geometryVersion,
    };
}

function hopfBaseId(id: string): string {
    if (id.startsWith('hopf:anchor:')) return id.slice('hopf:anchor:'.length);
    if (!id.startsWith('hopf:fiber:')) return id;
    const rest = id.slice('hopf:fiber:'.length);
    const separator = rest.lastIndexOf(':');
    return separator > 0 ? rest.slice(0, separator) : rest;
}

export function buildEmbeddingQueryTrace(query: string, atlas: EmbeddingAtlasData, topK = 6): EmbeddingQueryTrace | null {
    const text = query.trim();
    if (!text || atlas.searchIndex.length === 0) return null;
    const signature = textSignature(text, atlas.searchIndex[0]?.vector.length || DIMS);
    const scores = atlas.searchIndex
        .map((item) => ({ nodeId: item.nodeId, score: cosine(signature.vector, item.vector) }))
        .sort((a, b) => b.score - a.score);
    const primary = scores.slice(0, Math.min(topK, scores.length));
    const primaryIds = primary.map((item) => item.nodeId);
    const secondaryIds = multiHopIds(primaryIds, atlas.edges, 10);
    const queryId = `query:${hashToken(text).toString(16)}`;
    const queryPoint = projectSignature(signature.vector, queryId, 0, Math.max(1, atlas.nodes.length));
    const queryNode: GalaxyRenderableNode = {
        id: queryId,
        label: text.length > 28 ? `${text.slice(0, 27)}...` : text,
        kind: 'NETWORK',
        totalMentions: 18,
        atlasX: queryPoint.x,
        atlasY: queryPoint.y,
        atlasZ: queryPoint.z,
        colorHsl: '184 92% 62%',
        metadata: { sourceType: 'query', preview: text },
    };
    const directEdges = primary.map((item, index) => ({
        id: `${queryId}:direct:${item.nodeId}`,
        sourceId: queryId,
        targetId: item.nodeId,
        type: 'query-direct',
        confidence: Math.max(0.25, item.score * 3.2 + (topK - index) * 0.03),
    }));
    const hopEdges = atlas.edges
        .filter((edge) => isQueryHop(edge, primaryIds, secondaryIds))
        .slice(0, 14)
        .map((edge) => ({ ...edge, id: `${queryId}:hop:${edge.id}`, type: 'query-hop', confidence: edge.confidence * 0.8 }));
    const nodeById = new Map(atlas.nodes.map((node) => [node.id, node]));
    return {
        query: text,
        queryNode,
        primaryIds,
        secondaryIds,
        edgeIds: [...directEdges, ...hopEdges].map((edge) => edge.id),
        edges: [...directEdges, ...hopEdges],
        previews: primary.map((item) => sourcePreview(nodeById.get(item.nodeId), item.score)).filter(Boolean) as EmbeddingSourcePreview[],
        manifoldTrace: buildManifoldTrace(atlas, [...primaryIds, ...secondaryIds], [...directEdges, ...hopEdges].map((edge) => edge.id)),
    };
}

function buildManifoldTrace(atlas: EmbeddingAtlasData, nodeIds: string[], pathEdgeIds: string[]): EmbeddingManifoldTrace | undefined {
    const manifold = atlas.manifold;
    if (!manifold) return undefined;
    const nodeById = new Map(atlas.nodes.map((node) => [node.id, node]));
    const cellIds = [...new Set(nodeIds.map((id) => String((nodeById.get(id)?.metadata?.['hopf'] as Record<string, unknown> | undefined)?.['cellId'] || '')).filter(Boolean))];
    const chartIds = manifold.charts
        ?.filter((chart) => chart.memberCellIds.some((cellId) => cellIds.includes(cellId)))
        .map((chart) => chart.chartId) ?? [];
    return {
        mode: manifold.mode,
        geometryVersion: manifold.geometryVersion,
        coneId: manifold.coneTraces?.[0]?.coneId,
        programId: manifold.coneProgramTraces?.[0]?.programId,
        pathletIds: manifold.coneProgramTraces?.[0]?.pathletIds || [],
        obstructionIds: manifold.coneProgramTraces?.[0]?.obstructionIds || [],
        cellIds,
        chartIds: [...new Set(chartIds)],
        pathEdgeIds: [...new Set([...pathEdgeIds, ...(manifold.coneProgramTraces?.[0]?.pathEdgeIds || [])])],
    };
}

function noteText(note: Note): string {
    return note.markdownContent || note.content || note.title || '';
}

function previewText(text: string): string {
    return text.replace(/\s+/g, ' ').trim().slice(0, 180);
}

function textSignature(text: string, dims = DIMS): Signature {
    const vector = new Float32Array(Math.max(1, dims));
    let token = '';
    let tokens = 0;
    for (let index = 0; index <= text.length; index++) {
        const char = index < text.length ? text.charCodeAt(index) : 32;
        const normalized = normalizeChar(char);
        if (normalized) {
            token += normalized;
            continue;
        }
        if (token.length > 2) {
            addToken(vector, token);
            tokens++;
        }
        token = '';
    }
    normalize(vector);
    return { vector, tokens };
}

function normalizeChar(code: number): string {
    if (code >= 65 && code <= 90) return String.fromCharCode(code + 32);
    if ((code >= 97 && code <= 122) || (code >= 48 && code <= 57)) return String.fromCharCode(code);
    return '';
}

function addToken(vector: Float32Array, token: string): void {
    const hash = hashToken(token);
    const first = hash % vector.length;
    const second = (hash >>> 7) % vector.length;
    const sign = (hash & 0x80000000) === 0 ? 1 : -1;
    const weight = 1 + Math.min(9, token.length) * 0.035;
    vector[first] += sign * weight;
    vector[second] += sign * weight * 0.5;
}

function normalizeBackendVector(values: number[]): Float32Array {
    const vector = new Float32Array(values.map((value) => Number.isFinite(value) ? value : 0));
    normalize(vector);
    return vector;
}

function hashToken(token: string): number {
    let hash = 2166136261;
    for (let index = 0; index < token.length; index++) {
        hash ^= token.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
}

function normalize(vector: Float32Array): void {
    let sum = 0;
    for (let index = 0; index < vector.length; index++) sum += vector[index] * vector[index];
    const scale = sum > 0 ? 1 / Math.sqrt(sum) : 1;
    for (let index = 0; index < vector.length; index++) vector[index] *= scale;
}

function projectSignature(vector: Float32Array, id: string, index: number, total: number): { x: number; y: number; z: number } {
    const seed = hashToken(id);
    const raw = projectVectorTo3d(vector, seed);
    const norm = Math.hypot(raw.x, raw.y, raw.z);
    const radius = total < 8 ? EMBEDDING_SHELL_SMALL_RADIUS : EMBEDDING_SHELL_RADIUS;
    if (!Number.isFinite(norm) || norm < 1e-8) {
        return fibonacciSpherePoint(index, Math.max(1, total), radius, seed);
    }

    return {
        x: radius * raw.x / norm,
        y: radius * raw.y / norm,
        z: radius * raw.z / norm,
    };
}

function projectVectorTo3d(vector: Float32Array, seed: number): { x: number; y: number; z: number } {
    const phase = seed / 4294967295;
    let x = 0;
    let y = 0;
    let z = 0;
    for (let dim = 0; dim < vector.length; dim++) {
        const value = vector[dim];
        const n = dim + 1;
        x += value * Math.sin(n * 12.9898 + phase * 6.283185307179586);
        y += value * Math.cos(n * 78.233 + phase * 3.883222077450933);
        z += value * Math.sin(n * 37.719 + phase * 2.399963229728653);
    }
    return { x, y, z };
}

function fibonacciSpherePoint(index: number, total: number, radius: number, seed: number): { x: number; y: number; z: number } {
    const y = 1 - (index / Math.max(1, total - 1)) * 2;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = (index + seed / 4294967295) * 2.399963229728653;
    return {
        x: Math.cos(angle) * radial * radius,
        y: y * radius,
        z: Math.sin(angle) * radial * radius,
    };
}

function buildKnnEdges(nodes: GalaxyRenderableNode[], signatures: Signature[], topK: number): GalaxyInputEdge[] {
    const seen = new Set<string>();
    const edges: GalaxyInputEdge[] = [];
    for (let source = 0; source < nodes.length; source++) {
        const candidates: Array<{ target: number; score: number }> = [];
        for (let target = 0; target < nodes.length; target++) {
            if (source === target) continue;
            candidates.push({ target, score: cosine(signatures[source].vector, signatures[target].vector) });
        }
        candidates.sort((a, b) => b.score - a.score);
        for (const candidate of candidates.slice(0, topK)) {
            if (candidate.score < 0.08 && edges.length > nodes.length) continue;
            const low = Math.min(source, candidate.target);
            const high = Math.max(source, candidate.target);
            const key = `${low}:${high}`;
            if (seen.has(key)) continue;
            seen.add(key);
            edges.push({
                id: `embed:${nodes[low].id}:${nodes[high].id}`,
                sourceId: nodes[low].id,
                targetId: nodes[high].id,
                type: 'semantic-neighbor',
                confidence: Math.max(0.1, candidate.score * 3),
            });
        }
    }
    return edges;
}

function buildSearchIndex(nodes: GalaxyRenderableNode[], signatures: Signature[]): EmbeddingAtlasSearchItem[] {
    return nodes.map((node, index) => ({ nodeId: node.id, vector: signatures[index].vector }));
}

function multiHopIds(primaryIds: string[], edges: GalaxyInputEdge[], limit: number): string[] {
    const primary = new Set(primaryIds);
    const secondary: string[] = [];
    const seen = new Set(primaryIds);
    for (const edge of edges) {
        const next = primary.has(edge.sourceId) ? edge.targetId : primary.has(edge.targetId) ? edge.sourceId : '';
        if (!next || seen.has(next)) continue;
        seen.add(next);
        secondary.push(next);
        if (secondary.length >= limit) break;
    }
    return secondary;
}

function isQueryHop(edge: GalaxyInputEdge, primaryIds: string[], secondaryIds: string[]): boolean {
    const primary = new Set(primaryIds);
    const secondary = new Set(secondaryIds);
    return (primary.has(edge.sourceId) && secondary.has(edge.targetId)) || (primary.has(edge.targetId) && secondary.has(edge.sourceId));
}

function sourcePreview(node: GalaxyRenderableNode | undefined, score: number): EmbeddingSourcePreview | null {
    if (!node) return null;
    const metadata = node.metadata || {};
    const hopf = metadata['hopf'] as Record<string, unknown> | undefined;
    const cell = hopf?.['cellId'] ? `cell ${String(hopf['cellId'])}` : '';
    const boundary = Number(hopf?.['boundaryScore']);
    const topology = cell ? `${cell}${Number.isFinite(boundary) ? `, boundary ${boundary.toFixed(2)}` : ''}. ` : '';
    return {
        nodeId: node.id,
        label: node.label,
        score,
        sourceType: String(metadata['sourceType'] || 'source'),
        preview: `${topology}${String(metadata['preview'] || '')}`,
    };
}

function cosine(a: Float32Array, b: Float32Array): number {
    let dot = 0;
    for (let index = 0; index < a.length; index++) dot += a[index] * b[index];
    return Math.max(0, dot);
}
