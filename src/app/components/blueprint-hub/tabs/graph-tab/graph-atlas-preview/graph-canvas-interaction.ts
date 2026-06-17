import type { GalaxyInputEdge, GalaxyQueryFocus, GalaxyRenderableNode } from './graph-galaxy-engine';

export type GraphCanvasLens = 'entities' | 'structure' | 'facts' | 'discourse' | 'accepted' | 'proposed';
export type GraphCanvasObjectKind = 'node' | 'edge' | 'cluster';
export type GraphCanvasReviewDecision = 'accepted' | 'rejected' | 'muted' | 'promoted_to_anchor';

export interface GraphCanvasNodeHit {
    kind: 'node';
    id: string;
}

export interface GraphCanvasEdgeHit {
    kind: 'edge';
    id: string;
    sourceId: string;
    targetId: string;
}

export interface GraphCanvasClusterHit {
    kind: 'cluster';
    id: string;
    label: string;
    nodeIds: string[];
}

export type GraphCanvasHit = GraphCanvasNodeHit | GraphCanvasEdgeHit | GraphCanvasClusterHit;

export interface GraphCanvasReviewRequest {
    objectIds: string[];
    decision: GraphCanvasReviewDecision;
}

export interface GraphCanvasSourceRequest {
    noteId: string;
    sourceStart: number;
    sourceEnd: number;
}

export interface GraphCanvasInspectorRecord {
    id: string;
    objectKind: GraphCanvasObjectKind;
    title: string;
    subtitle: string;
    status: string;
    confidence: number | null;
    sourceSnippet: string;
    noteId: string;
    sourceStart: number | null;
    sourceEnd: number | null;
    detector: string;
    reasons: string[];
    evidenceIds: string[];
    relatedEntityIds: string[];
    memberIds: string[];
    members: Array<{ id: string; label: string; kind: string }>;
    graphImpact: string;
    styleKey: string;
    reviewObjectIds: string[];
    reviewActions: string[];
    focusNodeIds: string[];
}

export interface GraphCanvasGraphSlice {
    nodes: GalaxyRenderableNode[];
    edges: GalaxyInputEdge[];
}

export function filterGraphForCanvasLens(
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    lens: GraphCanvasLens,
): GraphCanvasGraphSlice {
    const primaryIds = new Set(nodes.filter((node) => nodeMatchesLens(node, lens)).map((node) => node.id));
    const allowedIds = new Set(primaryIds);
    for (const edge of edges) {
        const edgeMatches = lens === 'accepted' || lens === 'proposed'
            ? edgeMatchesState(edge, lens)
            : metadataString(edge.metadata, 'canvasLens') === lens;
        if (!edgeMatches || (!primaryIds.has(edge.sourceId) && !primaryIds.has(edge.targetId))) continue;
        allowedIds.add(edge.sourceId);
        allowedIds.add(edge.targetId);
    }
    const allowedNodes = nodes.filter((node) => allowedIds.has(node.id));
    const allowedEdges = edges.filter((edge) => {
        if (!allowedIds.has(edge.sourceId) || !allowedIds.has(edge.targetId)) return false;
        if (lens === 'accepted' || lens === 'proposed') return edgeMatchesState(edge, lens) || primaryIds.has(edge.sourceId) || primaryIds.has(edge.targetId);
        const edgeLens = metadataString(edge.metadata, 'canvasLens');
        return edgeLens === lens || primaryIds.has(edge.sourceId) && primaryIds.has(edge.targetId);
    });
    return { nodes: allowedNodes, edges: allowedEdges };
}

export function buildCanvasSearchFocus(
    query: string,
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
): GalaxyQueryFocus | null {
    const terms = normalizeTerms(query);
    if (!terms.length) return null;
    const primaryNodeIds = nodes.filter((node) => terms.every((term) => nodeSearchText(node).includes(term))).map((node) => node.id);
    const primary = new Set(primaryNodeIds);
    const secondary = new Set<string>();
    const edgeIds: string[] = [];
    for (const edge of edges) {
        const edgeMatch = terms.every((term) => edgeSearchText(edge).includes(term));
        if (edgeMatch || primary.has(edge.sourceId) || primary.has(edge.targetId)) {
            edgeIds.push(edge.id);
            if (!primary.has(edge.sourceId)) secondary.add(edge.sourceId);
            if (!primary.has(edge.targetId)) secondary.add(edge.targetId);
        }
    }
    if (!primaryNodeIds.length && !edgeIds.length) return null;
    return {
        queryNodeId: primaryNodeIds[0] || [...secondary][0] || '',
        primaryNodeIds,
        secondaryNodeIds: [...secondary],
        edgeIds,
    };
}

export function graphCanvasInspectorRecord(
    hit: GraphCanvasHit | null,
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
): GraphCanvasInspectorRecord | null {
    if (!hit) return null;
    if (hit.kind === 'node') {
        const node = nodes.find((candidate) => candidate.id === hit.id);
        return node ? nodeRecord(node) : null;
    }
    if (hit.kind === 'edge') {
        const edge = edges.find((candidate) => candidate.id === hit.id);
        if (!edge) return null;
        const source = nodes.find((node) => node.id === edge.sourceId);
        const target = nodes.find((node) => node.id === edge.targetId);
        return edgeRecord(edge, source, target);
    }
    const members = hit.nodeIds.map((id) => nodes.find((node) => node.id === id)).filter(isNode);
    return clusterRecord(hit, members);
}

export function graphCanvasBatchRecords(
    ids: string[],
    nodes: GalaxyRenderableNode[],
): GraphCanvasInspectorRecord[] {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    return ids.map((id) => nodeById.get(id)).filter(isNode).map(nodeRecord);
}

function nodeMatchesLens(node: GalaxyRenderableNode, lens: GraphCanvasLens): boolean {
    const metadata = node.metadata;
    if (lens === 'accepted' || lens === 'proposed') return metadataString(metadata, 'reviewState') === lens;
    const nodeLens = metadataString(metadata, 'canvasLens');
    if (nodeLens) return nodeLens === lens;
    return lens === 'entities';
}

function edgeMatchesState(edge: GalaxyInputEdge, lens: 'accepted' | 'proposed'): boolean {
    return metadataString(edge.metadata, 'reviewState') === lens;
}

function nodeRecord(node: GalaxyRenderableNode): GraphCanvasInspectorRecord {
    const metadata = node.metadata;
    return {
        id: node.id,
        objectKind: 'node',
        title: node.label,
        subtitle: metadataString(metadata, 'subtitle') || titleCase(node.kind),
        status: metadataString(metadata, 'reviewState') || 'accepted',
        confidence: metadataNumber(metadata, 'confidence'),
        sourceSnippet: metadataString(metadata, 'sourceSnippet') || metadataString(metadata, 'preview'),
        noteId: metadataString(metadata, 'noteId'),
        sourceStart: metadataNumber(metadata, 'sourceStart') ?? metadataNumber(metadata, 'start'),
        sourceEnd: metadataNumber(metadata, 'sourceEnd') ?? metadataNumber(metadata, 'end'),
        detector: metadataString(metadata, 'detector'),
        reasons: metadataStrings(metadata, 'reasons'),
        evidenceIds: metadataStrings(metadata, 'evidenceIds'),
        relatedEntityIds: metadataStrings(metadata, 'relatedEntityIds'),
        memberIds: metadataStrings(metadata, 'memberIds'),
        members: [],
        graphImpact: metadataString(metadata, 'graphImpact'),
        styleKey: styleKeyForMetadata(metadata, node.kind),
        reviewObjectIds: metadataString(metadata, 'reviewObjectId') ? [metadataString(metadata, 'reviewObjectId')] : [],
        reviewActions: metadataStrings(metadata, 'reviewActions'),
        focusNodeIds: [node.id],
    };
}

function edgeRecord(
    edge: GalaxyInputEdge,
    source: GalaxyRenderableNode | undefined,
    target: GalaxyRenderableNode | undefined,
): GraphCanvasInspectorRecord {
    const metadata = edge.metadata;
    const wormhole = metadataString(metadata, 'interactionKind') === 'wormhole';
    return {
        id: edge.id,
        objectKind: 'edge',
        title: wormhole ? 'Wormhole' : titleCase(edge.type),
        subtitle: `${source?.label || edge.sourceId} -> ${target?.label || edge.targetId}`,
        status: metadataString(metadata, 'reviewState') || 'accepted',
        confidence: Number.isFinite(edge.confidence) ? edge.confidence : null,
        sourceSnippet: metadataString(metadata, 'sourceSnippet'),
        noteId: metadataString(metadata, 'noteId'),
        sourceStart: metadataNumber(metadata, 'sourceStart'),
        sourceEnd: metadataNumber(metadata, 'sourceEnd'),
        detector: metadataString(metadata, 'detector') || edge.type,
        reasons: metadataStrings(metadata, 'reasons'),
        evidenceIds: metadataStrings(metadata, 'evidenceIds'),
        relatedEntityIds: metadataStrings(metadata, 'relatedEntityIds'),
        memberIds: [edge.sourceId, edge.targetId],
        members: [source, target].filter(isNode).map((node) => ({ id: node.id, label: node.label, kind: node.kind })),
        graphImpact: metadataString(metadata, 'graphImpact') || 'Connects two inspectable graph objects.',
        styleKey: styleKeyForMetadata(metadata, edge.type),
        reviewObjectIds: metadataString(metadata, 'reviewObjectId') ? [metadataString(metadata, 'reviewObjectId')] : [],
        reviewActions: metadataStrings(metadata, 'reviewActions'),
        focusNodeIds: [edge.sourceId, edge.targetId],
    };
}

function clusterRecord(hit: GraphCanvasClusterHit, members: GalaxyRenderableNode[]): GraphCanvasInspectorRecord {
    const lead = members[0]?.metadata;
    const confidence = members.map((node) => metadataNumber(node.metadata, 'clusterConfidence')).filter(isNumber);
    return {
        id: hit.id,
        objectKind: 'cluster',
        title: hit.label,
        subtitle: `${members.length} members`,
        status: metadataString(lead, 'reviewState') || 'proposed',
        confidence: confidence.length ? confidence.reduce((sum, value) => sum + value, 0) / confidence.length : null,
        sourceSnippet: metadataString(lead, 'clusterSummary'),
        noteId: '',
        sourceStart: null,
        sourceEnd: null,
        detector: metadataString(lead, 'detector') || 'semantic_cluster',
        reasons: metadataStrings(lead, 'clusterReasons'),
        evidenceIds: unique(members.flatMap((node) => metadataStrings(node.metadata, 'evidenceIds'))),
        relatedEntityIds: unique(members.flatMap((node) => metadataStrings(node.metadata, 'relatedEntityIds'))),
        memberIds: hit.nodeIds,
        members: members.map((node) => ({ id: node.id, label: node.label, kind: node.kind })),
        graphImpact: 'Groups objects that share a detected semantic region.',
        styleKey: styleKeyForMetadata(lead, members[0]?.kind || ''),
        reviewObjectIds: unique(members.map((node) => metadataString(node.metadata, 'reviewObjectId')).filter(Boolean)),
        reviewActions: unique(members.flatMap((node) => metadataStrings(node.metadata, 'reviewActions'))),
        focusNodeIds: hit.nodeIds,
    };
}

function nodeSearchText(node: GalaxyRenderableNode): string {
    return [
        node.label,
        node.kind,
        ...(node.aliases || []),
        metadataString(node.metadata, 'searchableText'),
        metadataString(node.metadata, 'sourceSnippet'),
        metadataString(node.metadata, 'detector'),
        ...metadataStrings(node.metadata, 'reasons'),
    ].join(' ').toLocaleLowerCase();
}

function edgeSearchText(edge: GalaxyInputEdge): string {
    return [edge.type, metadataString(edge.metadata, 'searchableText'), metadataString(edge.metadata, 'sourceSnippet')]
        .join(' ')
        .toLocaleLowerCase();
}

function normalizeTerms(value: string): string[] {
    return value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean).slice(0, 8);
}

function metadataString(metadata: Record<string, unknown> | undefined, key: string): string {
    const value = metadata?.[key];
    return typeof value === 'string' ? value : '';
}

function metadataNumber(metadata: Record<string, unknown> | undefined, key: string): number | null {
    const value = metadata?.[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function metadataStrings(metadata: Record<string, unknown> | undefined, key: string): string[] {
    const value = metadata?.[key];
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function styleKeyForMetadata(metadata: Record<string, unknown> | undefined, fallback: string): string {
    return metadataString(metadata, 'graphColorKind')
        || metadataString(metadata, 'graphRelationFamily')
        || metadataString(metadata, 'graphKind')
        || metadataString(metadata, 'atlasKind')
        || fallback;
}

function unique(values: string[]): string[] {
    return [...new Set(values)];
}

function isNode(value: GalaxyRenderableNode | undefined): value is GalaxyRenderableNode {
    return Boolean(value);
}

function isNumber(value: number | null): value is number {
    return value !== null;
}

function titleCase(value: string): string {
    return String(value || 'object').replace(/[_-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}
