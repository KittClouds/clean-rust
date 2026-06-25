import {
    HOPF_MANIFOLD_CAPABILITIES,
    LORENTZ_MANIFOLD_CAPABILITIES,
    PRODUCT_MANIFOLD_CAPABILITIES,
    SIEGEL_FINSLER_CAPABILITIES,
    type AtlasManifoldMode,
    type ManifoldAtlasSnapshot,
} from '../../../../../services/manifold-atlas.types';
import type { PhoenixUiApiService, SearchScope, SemanticAtlasEmbeddingAtlas, SemanticAtlasEmbeddingNode } from '../../../../../services/phoenix-ui-api.service';
import {
    buildBackendEmbeddingAtlas,
    buildEmbeddingQueryTrace,
    type BackendEmbeddingAtlasPayload,
    type EmbeddingAtlasData,
    type EmbeddingQueryTrace,
} from './graph-embedding-atlas';
import { buildLorentzAtlas } from './graph-lorentz-atlas';

type VisualManifoldMode = Extract<AtlasManifoldMode, 'hybrid' | 'hopf' | 'lorentz' | 'product' | 'siegel'>;

export interface ManifoldAtlasAdapter {
    readonly mode: VisualManifoldMode;
    readonly label: string;
    readonly traceLabel: string;
    load(phoenixUiApi: PhoenixUiApiService, scope: SearchScope): Promise<EmbeddingAtlasData>;
    trace(query: string, atlas: EmbeddingAtlasData): EmbeddingQueryTrace | null;
}

export const HYBRID_MANIFOLD_ADAPTER: ManifoldAtlasAdapter = {
    mode: 'hybrid',
    label: 'Hybrid',
    traceLabel: 'Hybrid trace',
    async load(phoenixUiApi, scope) {
        const snapshot = await phoenixUiApi.loadManifoldAtlasSnapshot('hybrid', scope);
        if (snapshot?.payload.nodes.length) {
            return buildHybridAtlas(snapshot);
        }
        return emptyBackendAtlas('hybrid semantic atlas unavailable');
    },
    trace(query, atlas) {
        return buildEmbeddingQueryTrace(query, atlas);
    },
};

export const HOPF_MANIFOLD_ADAPTER: ManifoldAtlasAdapter = {
    mode: 'hopf',
    label: 'Hopf',
    traceLabel: 'Cone trace',
    async load(phoenixUiApi, scope) {
        const snapshot = await phoenixUiApi.loadManifoldAtlasSnapshot('hopf', scope);
        if (snapshot?.payload.nodes.length) {
            return buildHopfAtlas(snapshot);
        }
        return {
            ...emptyBackendAtlas('hopf semantic atlas unavailable'),
            manifold: {
                mode: 'hopf',
                geometryVersion: 'hopf_ico_r5_v1',
                sourceLabel: 'hopf semantic atlas unavailable',
                capabilities: HOPF_MANIFOLD_CAPABILITIES,
                projectionSource: 'semantic_atlas_rows',
                cells: [],
                charts: [],
                seams: [],
                neighborRings: [],
                coneTraces: [],
                anchorProjections: [],
            },
        };
    },
    trace(query, atlas) {
        return buildEmbeddingQueryTrace(query, atlas);
    },
};

export const LORENTZ_MANIFOLD_ADAPTER: ManifoldAtlasAdapter = {
    mode: 'lorentz',
    label: 'Caps',
    traceLabel: 'Cap trace',
    async load(phoenixUiApi, scope) {
        const snapshot = await phoenixUiApi.loadManifoldAtlasSnapshot('lorentz', scope);
        if (snapshot?.payload.nodes.length) {
            return withManifoldMetadata(snapshot, buildLorentzAtlas(snapshot));
        }
        return {
            ...emptyBackendAtlas('hierarchy caps semantic atlas unavailable'),
            manifold: {
                mode: 'lorentz',
                geometryVersion: 'hierarchy_caps_v1',
                sourceLabel: 'hierarchy caps semantic atlas unavailable',
                capabilities: LORENTZ_MANIFOLD_CAPABILITIES,
                projectionSource: 'semantic_atlas_rows',
                cells: [],
                charts: [],
                seams: [],
                neighborRings: [],
                coneTraces: [],
                anchorProjections: [],
                lorentzTrees: [],
                lorentzMemberships: [],
                lorentzCache: null,
            },
        };
    },
    trace(query, atlas) {
        return buildEmbeddingQueryTrace(query, atlas);
    },
};

export const PRODUCT_MANIFOLD_ADAPTER: ManifoldAtlasAdapter = {
    mode: 'product',
    label: 'Transit',
    traceLabel: 'Trace route',
    async load(phoenixUiApi, scope) {
        const snapshot = await phoenixUiApi.loadManifoldAtlasSnapshot('product', scope);
        if (snapshot?.payload.nodes.length) {
            return withManifoldMetadata(snapshot, buildProductAtlas(snapshot));
        }
        return {
            ...emptyBackendAtlas('transit semantic atlas unavailable'),
            manifold: {
                mode: 'product',
                geometryVersion: 'transit_lorentz_hopf_v1',
                sourceLabel: 'transit semantic atlas unavailable',
                capabilities: PRODUCT_MANIFOLD_CAPABILITIES,
                projectionSource: 'semantic_atlas_rows',
                cells: [],
                charts: [],
                seams: [],
                neighborRings: [],
                coneTraces: [],
                anchorProjections: [],
                lorentzTrees: [],
                lorentzMemberships: [],
                lorentzCache: null,
            },
        };
    },
    trace(query, atlas) {
        return buildEmbeddingQueryTrace(query, atlas);
    },
};

export const SIEGEL_MANIFOLD_ADAPTER: ManifoldAtlasAdapter = {
    mode: 'siegel',
    label: 'Siegel',
    traceLabel: 'Siegel trace',
    async load(phoenixUiApi, scope) {
        const snapshot = await phoenixUiApi.loadManifoldAtlasSnapshot('siegel', scope);
        if (snapshot?.payload.nodes.length) {
            return withManifoldMetadata(snapshot, buildBackendEmbeddingAtlas({
                ...snapshot.payload,
                sourceLabel: snapshot.sourceLabel || snapshot.payload.sourceLabel,
            }));
        }
        return {
            ...emptyBackendAtlas('siegel-finsler semantic atlas unavailable'),
            manifold: {
                mode: 'siegel',
                geometryVersion: 'siegel_finsler_v1',
                sourceLabel: 'siegel-finsler semantic atlas unavailable',
                capabilities: SIEGEL_FINSLER_CAPABILITIES,
                projectionSource: 'semantic_atlas_rows',
                cells: [],
                charts: [],
                seams: [],
                neighborRings: [],
                coneTraces: [],
                anchorProjections: [],
                lorentzTrees: [],
                lorentzMemberships: [],
                lorentzCache: null,
            },
        };
    },
    trace(query, atlas) {
        return buildEmbeddingQueryTrace(query, atlas);
    },
};

export const MANIFOLD_ATLAS_ADAPTERS: Record<VisualManifoldMode, ManifoldAtlasAdapter> = {
    hybrid: HYBRID_MANIFOLD_ADAPTER,
    hopf: HOPF_MANIFOLD_ADAPTER,
    lorentz: LORENTZ_MANIFOLD_ADAPTER,
    product: PRODUCT_MANIFOLD_ADAPTER,
    siegel: SIEGEL_MANIFOLD_ADAPTER,
};

export function manifoldAdapter(mode: AtlasManifoldMode): ManifoldAtlasAdapter {
    return MANIFOLD_ATLAS_ADAPTERS[mode] ?? MANIFOLD_ATLAS_ADAPTERS.hybrid;
}

function emptyBackendAtlas(sourceLabel: string): EmbeddingAtlasData {
    return { nodes: [], edges: [], sourceLabel, searchIndex: [] };
}

function buildHybridAtlas(snapshot: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>): EmbeddingAtlasData {
    return withManifoldMetadata(snapshot, buildBackendEmbeddingAtlas({
        ...snapshot.payload,
        sourceLabel: snapshot.sourceLabel || snapshot.payload.sourceLabel,
    }));
}

function buildHopfAtlas(snapshot: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>): EmbeddingAtlasData {
    if (snapshot.payload.nodes.some((node) => node.id.startsWith('hopf:') || String(node.sourceType).startsWith('hopf_'))) {
        return buildHybridAtlas(snapshot);
    }
    return withManifoldMetadata(snapshot, buildBackendEmbeddingAtlas(semanticSnapshotToHopfPayload(snapshot), 360, 4));
}

function withManifoldMetadata(snapshot: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>, atlas: EmbeddingAtlasData): EmbeddingAtlasData {
    return {
        ...atlas,
        manifold: {
            mode: snapshot.manifold,
            geometryVersion: snapshot.geometryVersion,
            sourceLabel: snapshot.sourceLabel,
            capabilities: snapshot.capabilities,
            projectionSource: snapshot.payload.projectionSource,
            cells: snapshot.payload.cells || [],
            charts: snapshot.payload.charts || [],
            seams: snapshot.payload.seams || [],
            neighborRings: snapshot.payload.neighborRings || [],
            coneTraces: snapshot.payload.coneTraces || [],
            conePrograms: snapshot.payload.conePrograms || [],
            pathlets: snapshot.payload.pathlets || [],
            obstructions: snapshot.payload.obstructions || [],
            coneProgramTraces: snapshot.payload.coneProgramTraces || [],
            anchorProjections: snapshot.payload.anchorProjections || [],
            lorentzTrees: snapshot.payload.lorentzTrees || [],
            lorentzMemberships: snapshot.payload.lorentzMemberships || [],
            lorentzCache: snapshot.payload.lorentzCache || null,
        },
    };
}

function buildProductAtlas(snapshot: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>): EmbeddingAtlasData {
    const lorentzAtlas = buildLorentzAtlas(snapshot);
    const traversal = productTraversalMetadata(snapshot.payload);
    const nodes = lorentzAtlas.nodes.map((node, index) => {
        const phase = hashToken(`product:${node.id}:${index}`);
        const fiberKind = inferProductFiberKind(node.kind, node.metadata?.['preview']);
        const kind = node.kind?.startsWith('PRODUCT:')
            ? node.kind
            : node.kind?.startsWith('LORENTZ:')
                ? node.kind.replace('LORENTZ:', 'PRODUCT:')
                : `PRODUCT:${node.kind || 'NODE'}`;
        return {
            ...node,
            kind,
            metadata: {
                ...node.metadata,
                sourceType: node.metadata?.sourceType === 'lorentz_root' ? 'product_root' : 'product_node',
                product: {
                    baseMode: 'lorentzHopf',
                    sourceType: node.metadata?.sourceType,
                    klein: (node.metadata?.['lorentz'] as Record<string, unknown> | undefined)?.['klein'],
                    fiberKind,
                    phase,
                },
                hopf: {
                    role: 'anchor',
                    baseId: node.id,
                    fiberKind,
                    phase,
                },
                ...(traversal.nodeMetadata.get(node.id) ? { productTraversal: traversal.nodeMetadata.get(node.id) } : {}),
            },
        };
    });
    const edges = lorentzAtlas.edges.map((edge) => ({
        ...edge,
        metadata: {
            ...(edge.metadata || {}),
            ...(traversal.edgeMetadata.get(edge.id) ? { productTraversal: traversal.edgeMetadata.get(edge.id) } : {}),
        },
    }));
    return {
        ...lorentzAtlas,
        nodes,
        edges,
        sourceLabel: snapshot.sourceLabel || 'transit Lorentz-Hopf atlas',
    };
}

function productTraversalMetadata(payload: SemanticAtlasEmbeddingAtlas): {
    nodeMetadata: Map<string, Record<string, unknown>>;
    edgeMetadata: Map<string, Record<string, unknown>>;
} {
    const nodeMetadata = new Map<string, Record<string, unknown>>();
    const edgeMetadata = new Map<string, Record<string, unknown>>();
    const obstructionById = new Map((payload.obstructions || []).map((obstruction) => [obstruction.obstructionId, obstruction]));
    for (const pathlet of payload.pathlets || []) {
        const obstructionIds = pathlet.obstructionIds || [];
        const obstructions = obstructionIds
            .map((id) => obstructionById.get(id))
            .filter((obstruction): obstruction is NonNullable<typeof obstruction> => Boolean(obstruction));
        const obstructionScore = obstructions.reduce((max, obstruction) => Math.max(max, obstruction.severity), 0);
        const obstructionKind = obstructions[0]?.kind;
        for (const nodeId of pathlet.nodeIds) {
            const current = nodeMetadata.get(nodeId) || {};
            const pathletIds = Array.isArray(current['pathletIds']) ? current['pathletIds'] as string[] : [];
            nodeMetadata.set(nodeId, {
                ...current,
                lane: pathlet.lane,
                pathletIds: [...new Set([...pathletIds, pathlet.pathletId])],
                obstructionIds: [...new Set([...(current['obstructionIds'] as string[] | undefined || []), ...obstructionIds])],
                supportScore: Math.max(Number(current['supportScore'] || 0), pathlet.supportScore),
                obstructionScore: Math.max(Number(current['obstructionScore'] || 0), obstructionScore),
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

function semanticSnapshotToHopfPayload(snapshot: ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>): BackendEmbeddingAtlasPayload {
    const semantic = snapshot.payload;
    const selected = semantic.nodes.filter((node) => Array.isArray(node.vector) && node.vector.length > 0);
    const anchorIds = new Map<string, string>();
    const fiberIds = new Map<string, string>();
    const nodes: BackendEmbeddingAtlasPayload['nodes'] = [];

    selected.forEach((node, index) => {
        const anchorId = `hopf:anchor:${node.id}`;
        const fiberKind = inferFiberKind(node);
        const fiberId = hopfFiberId(node.id, fiberKind);
        anchorIds.set(node.id, anchorId);
        fiberIds.set(node.id, fiberId);
        nodes.push({
            id: anchorId,
            label: node.label || node.id,
            sourceType: 'hopf_anchor',
            vector: node.vector,
            documentId: node.documentId,
            narrativeId: node.narrativeId,
            folderId: node.folderId,
            preview: node.preview || 'Stable semantic anchor derived from backend Semantic Atlas vectors.',
            kind: 'HOPF_ANCHOR',
        });
        nodes.push({
            id: fiberId,
            label: `${node.label || node.id} / ${fiberKind.replace(/_/g, ' ')}`,
            sourceType: 'hopf_fiber',
            vector: fiberVector(node.vector, fiberKind, index),
            documentId: node.documentId,
            narrativeId: node.narrativeId,
            folderId: node.folderId,
            preview: `${fiberKind} context fiber. ${node.preview || ''}`.trim(),
            kind: `HOPF_FIBER:${fiberKind}`,
        });
    });

    const edges: BackendEmbeddingAtlasPayload['edges'] = [];
    for (const node of selected) {
        const anchorId = anchorIds.get(node.id);
        const fiberId = fiberIds.get(node.id);
        if (!anchorId || !fiberId) continue;
        edges.push({
            id: `hopf:anchor-fiber:${node.id}`,
            sourceId: anchorId,
            targetId: fiberId,
            type: 'hopf-anchor-fiber',
            confidence: 1.25,
        });
    }
    for (const edge of semantic.edges) {
        const sourceFiberId = fiberIds.get(edge.sourceId);
        const targetFiberId = fiberIds.get(edge.targetId);
        if (!sourceFiberId || !targetFiberId || sourceFiberId === targetFiberId) continue;
        edges.push({
            id: `hopf:fiber-edge:${edge.id}`,
            sourceId: sourceFiberId,
            targetId: targetFiberId,
            type: `hopf-fiber-edge:${normalizeToken(edge.type || 'semantic')}`,
            confidence: Math.max(0.25, Number(edge.confidence) || 0.35),
        });
    }

    return {
        nodes,
        edges,
        sourceLabel: snapshot.sourceLabel || 'hopf anchors + fibers',
        projectionSource: snapshot.payload.projectionSource || 'semantic_atlas_rows',
    };
}

function inferFiberKind(node: SemanticAtlasEmbeddingNode): string {
    const text = `${node.kind || ''} ${node.sourceType || ''} ${node.label || ''} ${node.preview || ''}`.toLowerCase();
    if (/caus|because|therefore|effect|operator|echo/.test(text)) return 'causal';
    if (/time|temporal|before|after|timeline|date|countdown/.test(text)) return 'temporal';
    if (/evidence|source|span|leaf|document|log|provenance/.test(text)) return 'evidence';
    if (/relationship|trust|bond|domestic|intimacy|friend|family/.test(text)) return 'relationship';
    if (/power|veir|mechanic|channel|node|domain|technique/.test(text)) return 'power_system';
    if (/politic|corporate|faction|halcyon|surveillance/.test(text)) return 'political';
    if (/location|place|city|tower|realm|arcadia/.test(text)) return 'location';
    if (/event|scene|chapter/.test(text)) return 'event';
    return 'identity';
}

function inferProductFiberKind(kind: string | undefined, preview: unknown): string {
    const text = `${kind || ''} ${typeof preview === 'string' ? preview : ''}`.toLowerCase();
    if (/caus|because|therefore|effect/.test(text)) return 'causal';
    if (/time|temporal|before|after|timeline/.test(text)) return 'temporal';
    if (/evidence|source|document|provenance/.test(text)) return 'evidence';
    if (/location|place|city|tower|realm/.test(text)) return 'location';
    if (/event|scene|chapter/.test(text)) return 'event';
    return 'identity';
}

function hopfFiberId(nodeId: string, fiberKind: string): string {
    return `hopf:fiber:${nodeId}:${fiberKind}`;
}

function fiberVector(values: number[], fiberKind: string, index: number): number[] {
    const seed = hashToken(`${fiberKind}:${index}`);
    const mixed = new Array<number>(values.length);
    for (let dim = 0; dim < values.length; dim++) {
        const value = values[dim];
        const wobble = Math.sin((dim + 1) * 12.9898 + seed * 6.283185307179586) * 0.16;
        mixed[dim] = (Number.isFinite(value) ? value : 0) * 0.88 + wobble;
    }
    normalize(mixed);
    return mixed;
}

function normalize(values: number[]): void {
    let normSquared = 0;
    for (let index = 0; index < values.length; index++) {
        const value = values[index];
        normSquared += value * value;
    }
    const norm = Math.sqrt(normSquared);
    if (!Number.isFinite(norm) || norm <= 1e-8) {
        values.fill(0);
        if (values.length) values[0] = 1;
        return;
    }
    for (let index = 0; index < values.length; index++) values[index] /= norm;
}

function normalizeToken(value: string): string {
    return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'semantic';
}

function hashToken(token: string): number {
    let hash = 2166136261;
    for (let index = 0; index < token.length; index++) {
        hash ^= token.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}
