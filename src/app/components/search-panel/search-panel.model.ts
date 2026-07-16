import type { GraphAuditSnapshot } from '../../services/graph-audit.model';
import type { RetrievalLane } from '../../services/retrieval-workbench-state.service';
import {
    DEFAULT_GRAPH_EMBEDDING_DIMENSION_LABEL,
    DEFAULT_GRAPH_EMBEDDING_MODEL_ID,
    DEFAULT_GRAPH_EMBEDDING_MODEL_LABEL,
} from '../../lib/embeddings/models/ModelRegistry';
import {
    ATLAS_CAPABILITY_REGISTRY,
    type AtlasCapabilityCost,
    type AtlasGraphTargetId,
} from './atlas-capability.model';

export type { AtlasGraphTargetId } from './atlas-capability.model';

export type SearchMode = 'notes' | 'vector' | 'graph';
export type VectorStatus = 'idle' | 'loading' | 'ready' | 'indexing' | 'error';
export type GraphIndexStatus = 'idle' | 'building' | 'ready' | 'searching' | 'error';
export type ModelId = 'mongodb-leaf-mt' | 'bge-small-en' | 'jina-v5-nano-retrieval' | 'embeddinggemma-300m';
export const DEFAULT_SEARCH_MODEL_ID = DEFAULT_GRAPH_EMBEDDING_MODEL_ID as ModelId;
export const DEFAULT_SEARCH_MODEL_LABEL = DEFAULT_GRAPH_EMBEDDING_MODEL_LABEL;
export const DEFAULT_SEARCH_DIMENSION_LABEL = DEFAULT_GRAPH_EMBEDDING_DIMENSION_LABEL;

export interface AtlasGraphTarget {
    id: AtlasGraphTargetId;
    label: string;
    cost: AtlasCapabilityCost;
    subsystems: number;
    desc: string;
}

export interface SearchPanelNote {
    id: string;
    title: string;
    content: string;
    narrativeId: string;
    folderId: string;
    hasBody?: boolean;
}

export interface SearchResultView {
    noteId: string;
    title: string;
    excerpt: string;
    score: number;
    source: SearchMode;
    sourceLabel: string;
    meta?: string;
    lexScore?: number;
    graphScore?: number;
    matchedEntities?: string[];
    lanes?: RetrievalLane[];
}

export interface RetrievalPreviewNode {
    id: string;
    label: string;
    x: number;
    y: number;
    color: string;
}

export interface RetrievalPreviewEdge {
    id: string;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
}

export interface RetrievalGraphPreview {
    nodes: RetrievalPreviewNode[];
    edges: RetrievalPreviewEdge[];
}

export const RETRIEVAL_LANE_OPTIONS: Array<{ id: RetrievalLane; label: string; icon: string; desc: string }> = [
    { id: 'lexical', label: 'Lexical', icon: 'lucideSparkles', desc: 'Line and note matches' },
    { id: 'semantic', label: 'Semantic', icon: 'lucideZap', desc: 'Local embedding sidecar' },
    { id: 'graph', label: 'Graph', icon: 'lucideLayers', desc: 'Committed evidence graph' },
    { id: 'entities', label: 'Entities', icon: 'lucideCpu', desc: 'Registry and mentions' },
    { id: 'evidence', label: 'Evidence', icon: 'lucideFileText', desc: 'Claims and support paths' },
];

export const EMBEDDING_MODELS: Array<{ id: ModelId; label: string; dims: number; desc: string }> = [
    { id: 'jina-v5-nano-retrieval', label: 'Jina v5 Nano', dims: 768, desc: 'Primary graph compiler semantic runner target.' },
    { id: 'embeddinggemma-300m', label: 'EmbeddingGemma 300M', dims: 768, desc: 'High-accuracy semantic topology candidate target.' },
    { id: 'mongodb-leaf-mt', label: 'MDBR Leaf MT', dims: 384, desc: 'Fast multi-task native runner target.' },
    { id: 'bge-small-en', label: 'BGE-small', dims: 384, desc: 'Native Rust semantic runner target.' },
];

export const ATLAS_GRAPH_TARGETS: AtlasGraphTarget[] = ATLAS_CAPABILITY_REGISTRY
    .filter((capability) => !!capability.graphTargetId)
    .map((capability) => ({
        id: capability.graphTargetId as AtlasGraphTargetId,
        label: capability.graphTargetLabel || capability.label,
        cost: capability.cost,
        subsystems: capability.subsystems,
        desc: capability.description,
    }));

export function buildGraphPreview(snapshot: GraphAuditSnapshot | null): RetrievalGraphPreview {
    if (!snapshot?.sampleNodes.length) {
        return { nodes: [], edges: [] };
    }

    const palette = ['#2dd4bf', '#38bdf8', '#a78bfa', '#fbbf24', '#fb7185', '#34d399'];
    const nodeCount = Math.min(8, snapshot.sampleNodes.length);
    const nodes: RetrievalPreviewNode[] = [];
    const indexById = new Map<string, number>();

    for (let i = 0; i < nodeCount; i++) {
        const sample = snapshot.sampleNodes[i];
        const angle = (Math.PI * 2 * i) / nodeCount - Math.PI / 2;
        const radius = i === 0 ? 0 : 34;
        const x = 50 + Math.cos(angle) * radius;
        const y = 50 + Math.sin(angle) * radius;
        indexById.set(sample.id, i);
        nodes.push({
            id: sample.id,
            label: sample.label || sample.id,
            x,
            y,
            color: palette[i % palette.length],
        });
    }

    const edges: RetrievalPreviewEdge[] = [];
    for (const edge of snapshot.sampleEdges) {
        const source = indexById.get(edge.sourceId);
        const target = indexById.get(edge.targetId);
        if (source === undefined || target === undefined) continue;
        edges.push({
            id: `${edge.sourceId}:${edge.targetId}:${edge.edgeType}:${edges.length}`,
            x1: nodes[source].x,
            y1: nodes[source].y,
            x2: nodes[target].x,
            y2: nodes[target].y,
        });
        if (edges.length >= 10) break;
    }

    return { nodes, edges };
}

export function buildSearchSnippet(content: string, query: string): string {
    const trimmed = content.replace(/\s+/g, ' ').trim();
    if (!trimmed) return 'No note preview available.';

    const normalizedQuery = query.trim().toLowerCase();
    const matchIndex = normalizedQuery ? trimmed.toLowerCase().indexOf(normalizedQuery) : -1;
    if (matchIndex === -1) {
        return trimmed.length > 180 ? `${trimmed.slice(0, 177)}...` : trimmed;
    }

    const start = Math.max(0, matchIndex - 60);
    const end = Math.min(trimmed.length, matchIndex + normalizedQuery.length + 120);
    const snippet = trimmed.slice(start, end);
    return `${start > 0 ? '... ' : ''}${snippet}${end < trimmed.length ? ' ...' : ''}`;
}
