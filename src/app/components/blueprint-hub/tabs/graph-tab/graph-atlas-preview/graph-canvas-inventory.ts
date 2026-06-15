import type {
    GraphAtlasFamily,
    GraphAtlasManifoldTarget,
    GraphAtlasObject,
    GraphAtlasObjectStatus,
    GraphAtlasPacket,
} from '../../../../../graph-rebuild/graph-atlas-packet';
import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import type { GraphInventory } from './graph-atlas-preview.component';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';

type CanvasLens = 'entities' | 'structure' | 'facts' | 'discourse' | 'accepted' | 'proposed';
type CanvasReviewState = 'accepted' | 'proposed' | 'rejected' | 'muted';

const EMPTY_PACKET_LABEL = 'rust atlas packet missing';

/**
 * Compatibility boundary: TS no longer builds graph data. Graph mode only
 * adapts the Rust-owned Atlas packet into renderable rows and filters by
 * family/status metadata.
 */
export function buildGraphCanvasInventory(snapshot: GraphRebuildSnapshot | null): GraphInventory {
    const packet = snapshot?.atlasPacket;
    if (!packet) {
        return { nodes: [], edges: [], kindCounts: [], sourceLabel: EMPTY_PACKET_LABEL };
    }
    return buildAtlasPacketInventory(packet);
}

function buildAtlasPacketInventory(packet: GraphAtlasPacket): GraphInventory {
    const nodes: GalaxyRenderableNode[] = [];
    const edges: GalaxyInputEdge[] = [];
    const nodeIds = new Set<string>();
    const objectIdBySourceId = new Map<string, string>();
    const targetObjectById = new Map<string, string>();
    const targetByObjectId = new Map<string, GraphAtlasManifoldTarget>();

    for (const object of packet.objects) {
        for (const sourceId of object.sourceIds || []) {
            if (sourceId) objectIdBySourceId.set(sourceId, object.id);
        }
    }
    for (const target of packet.manifoldTargets) {
        targetObjectById.set(target.id, target.objectId);
        targetObjectById.set(target.sourceId, target.objectId);
        targetByObjectId.set(target.objectId, target);
        if (target.sourceId) objectIdBySourceId.set(target.sourceId, target.objectId);
    }

    for (const [index, object] of packet.objects.entries()) {
        nodes.push(atlasObjectNode(object, targetByObjectId.get(object.id), index));
        nodeIds.add(object.id);
    }
    for (const target of packet.manifoldTargets) {
        if (nodeIds.has(target.objectId)) continue;
        nodes.push(atlasTargetNode(target, nodes.length));
        nodeIds.add(target.objectId);
    }

    const edgeIds = new Set<string>();
    for (const object of packet.objects) {
        for (const targetId of object.targetIds || []) {
            const resolvedTargetId = resolveAtlasObjectId(targetId, nodeIds, targetObjectById, objectIdBySourceId);
            if (!resolvedTargetId || resolvedTargetId === object.id) continue;
            pushAtlasPacketEdge(edges, edgeIds, {
                sourceId: object.id,
                targetId: resolvedTargetId,
                family: object.family,
                status: object.status,
                type: 'object_target',
                label: object.kind,
                confidence: confidenceForStatus(object.status),
                evidenceIds: object.evidenceIds,
            });
        }
    }

    for (const target of packet.manifoldTargets) {
        for (const parentId of target.parentIds || []) {
            const parentObjectId = resolveAtlasObjectId(parentId, nodeIds, targetObjectById, objectIdBySourceId);
            if (!parentObjectId || parentObjectId === target.objectId) continue;
            pushAtlasPacketEdge(edges, edgeIds, {
                sourceId: parentObjectId,
                targetId: target.objectId,
                family: target.family,
                status: reviewStateForAdmission(target.admission),
                type: 'manifold_parent',
                label: target.coordinateSource || target.kind,
                confidence: target.vectorStatus === 'modelVector' ? 1 : 0.62,
                evidenceIds: target.evidenceIds,
            });
        }
    }

    return {
        nodes,
        edges,
        kindCounts: graphKindCounts(nodes),
        sourceLabel: `${packet.sourceContract.authority} / ${packet.sourceContract.vectorContract}`,
    };
}

function atlasObjectNode(
    object: GraphAtlasObject,
    target: GraphAtlasManifoldTarget | undefined,
    index: number,
): GalaxyRenderableNode {
    const family = object.family || 'unknown';
    const status = reviewStateForStatus(object.status);
    const noteId = object.noteIds[0] || target?.noteId || '';
    const chunkId = object.chunkIds[0] || target?.chunkId || '';
    return {
        id: object.id,
        label: object.label || object.id,
        kind: family,
        totalMentions: atlasObjectWeight(object, target),
        ...stablePoint(object.id, index),
        colorHsl: atlasFamilyHsl(family),
        metadata: {
            sourceType: 'rust-atlas-packet-object',
            sourceSystem: 'rust',
            sourceId: object.sourceIds[0] || target?.sourceId || object.id,
            atlasObjectId: object.id,
            atlasKind: object.kind,
            atlasFamily: family,
            atlasStatus: object.status,
            atlasTargetId: target?.id || '',
            graphFamily: family,
            graphKind: family,
            graphColorKind: family,
            canvasLens: atlasCanvasLens(family),
            reviewState: status,
            confidence: confidenceForStatus(object.status),
            detector: object.sourceIds.length ? 'rust_atlas_packet' : 'rust_atlas_packet_registry',
            subtitle: `${family} / ${object.status} / ${object.kind}`,
            searchableText: `${object.label} ${object.kind} ${family} ${object.status} ${object.sourceIds.join(' ')}`,
            relatedEntityIds: object.registryEntityId ? [object.registryEntityId] : [],
            noteId,
            chunkId,
            noteIds: object.noteIds,
            chunkIds: object.chunkIds,
            anchorIds: object.anchorIds,
            evidenceIds: object.evidenceIds,
            memberIds: object.targetIds,
            graphImpact: 'Rust Atlas object rendered by family/status filtering; TS graph builders are compatibility only.',
        },
    };
}

function atlasTargetNode(target: GraphAtlasManifoldTarget, index: number): GalaxyRenderableNode {
    const family = target.family || 'unknown';
    const status = reviewStateForAdmission(target.admission);
    return {
        id: target.objectId,
        label: target.label || target.objectId,
        kind: family,
        totalMentions: Math.max(1, target.evidenceIds.length, (target.parentIds || []).length),
        ...stablePoint(target.objectId, index),
        colorHsl: atlasFamilyHsl(family),
        metadata: {
            sourceType: 'rust-atlas-packet-target',
            sourceSystem: 'rust',
            sourceId: target.sourceId,
            atlasObjectId: target.objectId,
            atlasTargetId: target.id,
            atlasKind: target.kind,
            atlasFamily: family,
            atlasStatus: target.admission,
            atlasVectorStatus: target.vectorStatus,
            graphFamily: family,
            graphKind: family,
            graphColorKind: family,
            canvasLens: atlasCanvasLens(family),
            reviewState: status,
            confidence: target.vectorStatus === 'modelVector' ? 1 : 0.56,
            detector: 'rust_atlas_packet',
            subtitle: `${family} / ${target.admission} / ${target.coordinateSource}`,
            searchableText: `${target.label} ${target.kind} ${family} ${target.sourceId}`,
            relatedEntityIds: target.registryEntityId ? [target.registryEntityId] : [],
            noteId: target.noteId || '',
            chunkId: target.chunkId || '',
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds || [],
            graphImpact: 'Rust manifold target admitted as an Atlas object fallback.',
        },
    };
}

function pushAtlasPacketEdge(
    edges: GalaxyInputEdge[],
    seen: Set<string>,
    input: {
        sourceId: string;
        targetId: string;
        family: GraphAtlasFamily;
        status: GraphAtlasObjectStatus | CanvasReviewState;
        type: string;
        label: string;
        confidence: number;
        evidenceIds: string[];
    },
): void {
    const id = `atlas-packet:${input.type}:${input.sourceId}->${input.targetId}`;
    if (seen.has(id)) return;
    seen.add(id);
    const status = normalizeReviewState(input.status);
    edges.push({
        id,
        sourceId: input.sourceId,
        targetId: input.targetId,
        type: input.type,
        confidence: input.confidence,
        metadata: {
            sourceType: 'rust-atlas-packet-edge',
            sourceSystem: 'rust',
            graphFamily: input.family,
            graphKind: input.family,
            graphRelationFamily: input.label,
            graphColorKind: input.family,
            canvasLens: atlasCanvasLens(input.family),
            reviewState: status,
            confidence: input.confidence,
            evidenceIds: input.evidenceIds,
            searchableText: `${input.type} ${input.family} ${input.label}`,
            graphImpact: 'Rust packet topology edge shared by Graph and Embed views.',
        },
    });
}

function resolveAtlasObjectId(
    id: string,
    nodeIds: Set<string>,
    targetObjectById: Map<string, string>,
    objectIdBySourceId: Map<string, string>,
): string {
    if (nodeIds.has(id)) return id;
    const targetObjectId = targetObjectById.get(id);
    if (targetObjectId && nodeIds.has(targetObjectId)) return targetObjectId;
    const sourceObjectId = objectIdBySourceId.get(id);
    if (sourceObjectId && nodeIds.has(sourceObjectId)) return sourceObjectId;
    return '';
}

function atlasObjectWeight(object: GraphAtlasObject, target: GraphAtlasManifoldTarget | undefined): number {
    return Math.max(
        1,
        object.evidenceIds.length,
        object.anchorIds.length,
        object.targetIds.length,
        target?.evidenceIds.length || 0,
        target?.parentIds?.length || 0,
    );
}

function atlasCanvasLens(family: GraphAtlasFamily): CanvasLens {
    if (family === 'entity' || family === 'registry') return 'entities';
    if (family === 'structure' || family === 'evidence') return 'structure';
    if (family === 'discourse') return 'discourse';
    return 'facts';
}

function reviewStateForStatus(status: GraphAtlasObjectStatus): CanvasReviewState {
    return normalizeReviewState(status);
}

function reviewStateForAdmission(admission: GraphAtlasManifoldTarget['admission']): CanvasReviewState {
    if (admission === 'admitted') return 'accepted';
    if (admission === 'rejected') return 'rejected';
    return 'proposed';
}

function normalizeReviewState(status: GraphAtlasObjectStatus | CanvasReviewState): CanvasReviewState {
    if (status === 'accepted' || status === 'compiledToGraph' || status === 'promotedToAnchor') return 'accepted';
    if (status === 'rejected') return 'rejected';
    if (status === 'muted') return 'muted';
    return 'proposed';
}

function confidenceForStatus(status: GraphAtlasObjectStatus): number {
    if (status === 'accepted' || status === 'compiledToGraph' || status === 'promotedToAnchor') return 1;
    if (status === 'review' || status === 'proposed') return 0.72;
    if (status === 'rejected' || status === 'muted') return 0.24;
    return 0.56;
}

function atlasFamilyHsl(family: GraphAtlasFamily): string {
    if (family === 'entity' || family === 'registry') return entityColorStore.getRawHsl('character' as never);
    if (family === 'structure' || family === 'evidence') return '184 72% 48%';
    if (family === 'discourse') return '92 68% 52%';
    if (family === 'temporal' || family === 'causal' || family === 'memory') return entityColorStore.getRawGraphNodeHsl('eventNode');
    if (family === 'review') return '44 84% 58%';
    if (family === 'hypergraph') return '286 70% 62%';
    if (family === 'fact') return '326 74% 57%';
    return '220 10% 54%';
}

function graphKindCounts(nodes: GalaxyRenderableNode[]): Array<{ kind: string; count: number }> {
    const counts = new Map<string, number>();
    for (const node of nodes) {
        const kind = String(node.kind || 'unknown').toLowerCase();
        counts.set(kind, (counts.get(kind) || 0) + 1);
    }
    return [...counts.entries()]
        .map(([kind, count]) => ({ kind, count }))
        .sort((left, right) => right.count - left.count || left.kind.localeCompare(right.kind));
}

function stablePoint(id: string, index: number): { atlasX: number; atlasY: number; atlasZ: number } {
    const angle = index * 2.399963229728653 + hashUnit(id);
    const y = 1 - ((index % 89) / 88) * 2;
    const radius = Math.sqrt(Math.max(0, 1 - y * y)) * 0.92;
    return { atlasX: Math.cos(angle) * radius, atlasY: y * 0.7, atlasZ: Math.sin(angle) * radius };
}

function hashUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}
