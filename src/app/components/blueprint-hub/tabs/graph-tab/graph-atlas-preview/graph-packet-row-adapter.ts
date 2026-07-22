import type {
    GraphAtlasFamily,
    GraphAtlasManifoldTarget,
    GraphAtlasObject,
    GraphAtlasObjectStatus,
    GraphAtlasPacket,
} from '../../../../../graph-rebuild/graph-atlas-packet';
import type {
    GraphRebuildEmbeddingTarget,
    GraphRebuildVisualTrace,
} from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import {
    graphTopologyConfidenceForStatus,
    graphTopologyLaneForFamily,
    graphTopologyReviewStateForAdmission,
    graphTopologyReviewStateForStatus,
    graphTopologyStyleForPacketRow,
    graphTopologyTraceForAtlasEdge,
    graphTopologyTraceForAtlasObject,
    graphTopologyTraceForAtlasTarget,
    type GraphTopologyReviewState,
} from './graph-topology-style-contract';

type CanvasReviewState = GraphTopologyReviewState;

interface GraphPacketRowMaps {
    displayById: Map<string, GraphRebuildEmbeddingTarget>;
    objectById: Map<string, GraphAtlasObject>;
    objectsBySourceRef: Map<string, GraphAtlasObject[]>;
    objectIdBySourceId: Map<string, string>;
    targetByObjectId: Map<string, GraphAtlasManifoldTarget>;
    targetIdByObjectRef: Map<string, string>;
    targetObjectById: Map<string, string>;
    objectForTargetById: Map<string, GraphAtlasObject>;
    representedObjectIds: Set<string>;
}

export interface GraphPacketRowAdapter {
    graphNodes: GalaxyRenderableNode[];
    graphEdges: GalaxyInputEdge[];
    embeddingTargets: GraphRebuildEmbeddingTarget[];
    kindCounts: Array<{ kind: string; count: number }>;
    sourceLabel: string;
}

export function buildGraphPacketRowAdapter(
    packet: GraphAtlasPacket,
    displayTargets: GraphRebuildEmbeddingTarget[] = [],
): GraphPacketRowAdapter {
    const maps = graphPacketRowMaps(packet, displayTargets);
    const graphNodes = graphPacketNodes(packet, maps);
    const graphEdges = graphPacketEdges(packet, maps, new Set(graphNodes.map((node) => node.id)));
    const embeddingTargets = graphPacketEmbeddingTargets(packet, maps);
    return {
        graphNodes,
        graphEdges,
        embeddingTargets,
        kindCounts: graphKindCounts(graphNodes),
        sourceLabel: `${packet.sourceContract.authority} / ${packet.sourceContract.vectorContract}`,
    };
}

export function buildGraphPacketEmbeddingTargets(
    packet: GraphAtlasPacket,
    displayTargets: GraphRebuildEmbeddingTarget[] = [],
): GraphRebuildEmbeddingTarget[] {
    return graphPacketEmbeddingTargets(packet, graphPacketRowMaps(packet, displayTargets));
}

export function graphPacketEmbeddingTargetCount(packet: GraphAtlasPacket): number {
    const maps = graphPacketRowMaps(packet, []);
    return packet.manifoldTargets.length
        + packet.objects.filter((object) => !maps.representedObjectIds.has(object.id)).length;
}

function graphPacketRowMaps(
    packet: GraphAtlasPacket,
    displayTargets: GraphRebuildEmbeddingTarget[],
): GraphPacketRowMaps {
    const objectById = new Map(packet.objects.map((object) => [object.id, object]));
    const objectsBySourceRef = graphPacketObjectsBySourceRef(packet.objects);
    const targetByObjectId = new Map<string, GraphAtlasManifoldTarget>();
    const targetObjectById = new Map<string, string>();
    const objectIdBySourceId = new Map<string, string>();
    const targetIdByObjectRef = graphPacketTargetIdByObjectRef(packet);

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
    const objectForTargetById = new Map<string, GraphAtlasObject>();
    for (const target of packet.manifoldTargets) {
        const object = graphPacketObjectForTarget(target, objectById, objectsBySourceRef);
        if (object) objectForTargetById.set(target.id, object);
    }

    return {
        displayById: new Map(displayTargets.map((target) => [target.id, target])),
        objectById,
        objectsBySourceRef,
        objectIdBySourceId,
        targetByObjectId,
        targetIdByObjectRef,
        targetObjectById,
        objectForTargetById,
        representedObjectIds: graphPacketRepresentedObjectIds(packet, objectForTargetById),
    };
}

function graphPacketNodes(packet: GraphAtlasPacket, maps: GraphPacketRowMaps): GalaxyRenderableNode[] {
    const nodes: GalaxyRenderableNode[] = [];
    const nodeIds = new Set<string>();
    for (const [index, object] of packet.objects.entries()) {
        const target = maps.targetByObjectId.get(object.id);
        nodes.push(graphPacketObjectNode(packet, object, target, graphPacketDisplayTargetForObject(object, target, maps), index));
        nodeIds.add(object.id);
    }
    for (const target of packet.manifoldTargets) {
        if (nodeIds.has(target.objectId)) continue;
        nodes.push(graphPacketTargetNode(packet, target, graphPacketDisplayTargetForTarget(target, maps), nodes.length));
        nodeIds.add(target.objectId);
    }
    return nodes;
}

function graphPacketEdges(
    packet: GraphAtlasPacket,
    maps: GraphPacketRowMaps,
    nodeIds: Set<string>,
): GalaxyInputEdge[] {
    const edges: GalaxyInputEdge[] = [];
    const edgeIds = new Set<string>();
    for (const object of packet.objects) {
        for (const targetId of object.targetIds || []) {
            const resolvedTargetId = resolveAtlasObjectId(targetId, nodeIds, maps.targetObjectById, maps.objectIdBySourceId);
            if (!resolvedTargetId || resolvedTargetId === object.id) continue;
            const objectStatus = object.status || 'unknown';
            pushAtlasPacketEdge(edges, edgeIds, {
                packet,
                sourceId: object.id,
                targetId: resolvedTargetId,
                family: object.family,
                status: objectStatus,
                type: 'object_target',
                label: object.kind,
                confidence: graphTopologyConfidenceForStatus(objectStatus),
                evidenceIds: object.evidenceIds,
            });
        }
    }
    for (const target of packet.manifoldTargets) {
        for (const parentId of target.parentIds || []) {
            const parentObjectId = resolveAtlasObjectId(parentId, nodeIds, maps.targetObjectById, maps.objectIdBySourceId);
            if (!parentObjectId || parentObjectId === target.objectId) continue;
            pushAtlasPacketEdge(edges, edgeIds, {
                packet,
                sourceId: parentObjectId,
                targetId: target.objectId,
                family: target.family,
                status: graphTopologyReviewStateForAdmission(target.admission),
                type: 'manifold_parent',
                label: target.coordinateSource || target.kind,
                confidence: target.vectorStatus === 'modelVector' ? 1 : 0.62,
                evidenceIds: target.evidenceIds,
            });
        }
    }
    return edges;
}

function graphPacketEmbeddingTargets(
    packet: GraphAtlasPacket,
    maps: GraphPacketRowMaps,
): GraphRebuildEmbeddingTarget[] {
    const targets = packet.manifoldTargets.map((target): GraphRebuildEmbeddingTarget => {
        const display = maps.displayById.get(target.id);
        const object = maps.objectForTargetById.get(target.id);
        const style = graphPacketStyleForTarget(target, object, display);
        return {
            ...display,
            id: target.id,
            kind: graphPacketTargetKind(target.kind, object),
            sourceId: target.sourceId || graphPacketObjectSourceId(object) || target.objectId,
            noteId: target.noteId || object?.noteIds[0],
            chunkId: target.chunkId || object?.chunkIds[0],
            entityId: target.registryEntityId || object?.registryEntityId,
            entityKind: display?.entityKind || target.entityKind || graphPacketObjectEntityKind(object),
            label: target.label || object?.label || target.id,
            text: display?.text || graphPacketTargetSummary(target),
            evidenceIds: target.evidenceIds?.length ? target.evidenceIds : object?.evidenceIds || [],
            lane: (target.lane || object?.lane || display?.lane) as GraphRebuildEmbeddingTarget['lane'],
            structuralRole: (target.structuralRole || object?.structuralRole || display?.structuralRole) as GraphRebuildEmbeddingTarget['structuralRole'],
            admissionStatus: graphPacketAdmissionStatus(target.admission) || display?.admissionStatus,
            styleKey: target.styleKey || object?.styleKey || target.stateContextKind || object?.stateContextKind || display?.styleKey || style.colorKind,
            documentUnitKind: target.documentUnitKind || object?.documentUnitKind || display?.documentUnitKind,
            stateContextKind: target.stateContextKind || object?.stateContextKind || display?.stateContextKind,
            atlasFamily: target.family,
            atlasStatus: target.status,
            visualTrace: graphPacketTargetVisualTrace(packet, target, object),
            parentIds: target.parentIds?.length
                ? target.parentIds
                : graphPacketObjectParentIds(object, maps.targetIdByObjectRef, target.id) || display?.parentIds || [],
        };
    });
    for (const object of packet.objects) {
        if (maps.representedObjectIds.has(object.id)) continue;
        const target = graphPacketObjectEmbeddingTarget(packet, object, maps.displayById, maps.targetIdByObjectRef);
        if (target) targets.push(target);
    }
    return targets;
}

function graphPacketDisplayTargetForObject(
    object: GraphAtlasObject,
    target: GraphAtlasManifoldTarget | undefined,
    maps: GraphPacketRowMaps,
): GraphRebuildEmbeddingTarget | undefined {
    const ids = [
        target?.id,
        graphPacketObjectTargetId(object),
        object.id,
        object.registryEntityId,
        ...object.sourceIds,
    ].filter((id): id is string => !!id);
    for (const id of ids) {
        const display = maps.displayById.get(id);
        if (display) return display;
    }
    return undefined;
}

function graphPacketDisplayTargetForTarget(
    target: GraphAtlasManifoldTarget,
    maps: GraphPacketRowMaps,
): GraphRebuildEmbeddingTarget | undefined {
    const ids = [target.id, target.objectId, target.sourceId, target.registryEntityId].filter((id): id is string => !!id);
    for (const id of ids) {
        const display = maps.displayById.get(id);
        if (display) return display;
    }
    return undefined;
}

function graphPacketStyleForObject(
    object: GraphAtlasObject,
    target: GraphAtlasManifoldTarget | undefined,
    display: GraphRebuildEmbeddingTarget | undefined,
) {
    const family = target?.family || display?.atlasFamily || object.family;
    const entityKind = target?.entityKind || display?.entityKind || graphPacketObjectEntityKind(object);
    return graphTopologyStyleForPacketRow({
        family,
        kind: target?.kind || display?.kind || object.kind,
        label: target?.label || display?.label || object.label,
        extraParts: styleParts(object.kind, ...object.sourceIds, target?.sourceId, target?.coordinateSource),
        styleKey: target?.styleKey || object.styleKey || display?.styleKey || entityKind,
        stateContextKind: target?.stateContextKind || object.stateContextKind || display?.stateContextKind,
    });
}

function graphPacketStyleForTarget(
    target: GraphAtlasManifoldTarget,
    object: GraphAtlasObject | undefined,
    display: GraphRebuildEmbeddingTarget | undefined,
) {
    const entityKind = target.entityKind || display?.entityKind || graphPacketObjectEntityKind(object);
    return graphTopologyStyleForPacketRow({
        family: target.family,
        kind: target.kind || display?.kind || object?.kind || '',
        label: target.label || display?.label || object?.label || '',
        extraParts: styleParts(object?.kind, target.sourceId, target.coordinateSource, ...(object?.sourceIds || [])),
        styleKey: target.styleKey || object?.styleKey || display?.styleKey || entityKind,
        stateContextKind: target.stateContextKind || object?.stateContextKind || display?.stateContextKind,
    });
}

function styleParts(...parts: Array<string | undefined>): string[] {
    return parts.filter((part): part is string => !!part);
}

function graphPacketObjectNode(
    packet: GraphAtlasPacket,
    object: GraphAtlasObject,
    target: GraphAtlasManifoldTarget | undefined,
    display: GraphRebuildEmbeddingTarget | undefined,
    index: number,
): GalaxyRenderableNode {
    const family = object.family || 'unknown';
    const objectStatus = object.status || 'unknown';
    const status = graphTopologyReviewStateForStatus(objectStatus);
    const noteId = object.noteIds[0] || target?.noteId || '';
    const chunkId = object.chunkIds[0] || target?.chunkId || '';
    const style = graphPacketStyleForObject(object, target, display);
    const visualTrace = graphTopologyTraceForAtlasObject(packet, object, target, family);
    return {
        id: object.id,
        label: object.label || object.id,
        kind: family,
        totalMentions: graphPacketObjectWeight(object, target),
        ...stablePoint(object.id, index),
        colorHsl: style.colorHsl,
        metadata: {
            sourceType: 'rust-atlas-packet-object',
            sourceSystem: 'rust',
            sourceId: object.sourceIds[0] || target?.sourceId || object.id,
            visualTrace,
            visualSourceId: visualTrace.sourceId,
            visualFamily: visualTrace.family,
            packetSnapshotId: visualTrace.packetSnapshotId,
            packetScopeId: visualTrace.packetScopeId,
            snapshotId: packet.snapshotId,
            scopeId: packet.scopeId,
            builtAt: packet.builtAt,
            sourceContract: packet.sourceContract.authority,
            vectorContract: packet.sourceContract.vectorContract,
            atlasObjectId: object.id,
            atlasKind: object.kind,
            atlasFamily: family,
            atlasStatus: objectStatus,
            atlasLane: object.lane || target?.lane || '',
            atlasStructuralRole: object.structuralRole || target?.structuralRole || '',
            atlasDocumentUnitKind: object.documentUnitKind || target?.documentUnitKind || '',
            atlasStateContextKind: object.stateContextKind || target?.stateContextKind || '',
            atlasTargetId: target?.id || '',
            atlasVectorStatus: target?.vectorStatus || '',
            entityKind: style.entityKind,
            graphFamily: family,
            graphKind: object.styleKey || object.kind || family,
            graphColorKind: style.colorKind,
            styleKey: style.colorKind,
            graphRelationFamily: style.relationFamily,
            canvasLens: graphTopologyLaneForFamily(family),
            reviewState: status,
            confidence: graphTopologyConfidenceForStatus(objectStatus),
            detector: object.sourceIds.length ? 'rust_atlas_packet' : 'rust_atlas_packet_registry',
            subtitle: `${family} / ${objectStatus} / ${object.kind}`,
            searchableText: `${object.label} ${object.kind} ${family} ${objectStatus} ${object.sourceIds.join(' ')}`,
            relatedEntityIds: object.registryEntityId ? [object.registryEntityId] : [],
            noteId,
            chunkId,
            noteIds: object.noteIds,
            chunkIds: object.chunkIds,
            anchorIds: object.anchorIds,
            evidenceIds: object.evidenceIds,
            memberIds: object.targetIds,
            graphImpact: 'Rust Atlas object rendered by family/status filtering.',
        },
    };
}

function graphPacketTargetNode(
    packet: GraphAtlasPacket,
    target: GraphAtlasManifoldTarget,
    display: GraphRebuildEmbeddingTarget | undefined,
    index: number,
): GalaxyRenderableNode {
    const family = target.family || 'unknown';
    const status = graphTopologyReviewStateForAdmission(target.admission);
    const style = graphPacketStyleForTarget(target, undefined, display);
    const visualTrace = graphTopologyTraceForAtlasTarget(packet, target, family);
    return {
        id: target.objectId,
        label: target.label || target.objectId,
        kind: family,
        totalMentions: Math.max(1, target.evidenceIds.length, (target.parentIds || []).length),
        ...stablePoint(target.objectId, index),
        colorHsl: style.colorHsl,
        metadata: {
            sourceType: 'rust-atlas-packet-target',
            sourceSystem: 'rust',
            sourceId: target.sourceId,
            visualTrace,
            visualSourceId: visualTrace.sourceId,
            visualFamily: visualTrace.family,
            packetSnapshotId: visualTrace.packetSnapshotId,
            packetScopeId: visualTrace.packetScopeId,
            snapshotId: packet.snapshotId,
            scopeId: packet.scopeId,
            builtAt: packet.builtAt,
            sourceContract: packet.sourceContract.authority,
            vectorContract: packet.sourceContract.vectorContract,
            atlasObjectId: target.objectId,
            atlasTargetId: target.id,
            atlasKind: target.kind,
            atlasFamily: family,
            atlasStatus: target.admission,
            atlasObjectStatus: target.status,
            atlasLane: target.lane || '',
            atlasStructuralRole: target.structuralRole || '',
            atlasDocumentUnitKind: target.documentUnitKind || '',
            atlasStateContextKind: target.stateContextKind || '',
            atlasVectorStatus: target.vectorStatus,
            entityKind: target.entityKind || style.entityKind,
            graphFamily: family,
            graphKind: target.styleKey || target.stateContextKind || target.kind || family,
            graphColorKind: style.colorKind,
            styleKey: style.colorKind,
            graphRelationFamily: style.relationFamily,
            canvasLens: graphTopologyLaneForFamily(family),
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
            graphImpact: 'Rust manifold target admitted as an Atlas object projection.',
        },
    };
}

function pushAtlasPacketEdge(
    edges: GalaxyInputEdge[],
    seen: Set<string>,
    input: {
        packet: GraphAtlasPacket;
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
    const status = graphTopologyReviewStateForStatus(input.status);
    const style = graphTopologyStyleForPacketRow({
        family: input.family,
        kind: input.label,
        label: input.type,
        extraParts: [input.sourceId, input.targetId],
    });
    const visualTrace = graphTopologyTraceForAtlasEdge(input.packet, input);
    edges.push({
        id,
        sourceId: input.sourceId,
        targetId: input.targetId,
        type: input.type,
        confidence: input.confidence,
        metadata: {
            sourceType: 'rust-atlas-packet-edge',
            sourceSystem: 'rust',
            sourceId: input.sourceId,
            visualTrace,
            visualSourceId: visualTrace.sourceId,
            visualFamily: visualTrace.family,
            packetSnapshotId: visualTrace.packetSnapshotId,
            packetScopeId: visualTrace.packetScopeId,
            sourceContract: visualTrace.sourceContract,
            vectorContract: visualTrace.vectorContract,
            atlasSourceObjectId: input.sourceId,
            atlasTargetObjectId: input.targetId,
            graphFamily: input.family,
            graphKind: input.label || input.family,
            graphRelationFamily: style.relationFamily,
            graphColorKind: style.colorKind,
            canvasLens: graphTopologyLaneForFamily(input.family),
            reviewState: status,
            confidence: input.confidence,
            evidenceIds: input.evidenceIds,
            searchableText: `${input.type} ${input.family} ${input.label}`,
            graphImpact: 'Rust packet topology edge shared by Graph and Embed views.',
        },
    });
}

function graphPacketObjectsBySourceRef(objects: GraphAtlasObject[]): Map<string, GraphAtlasObject[]> {
    const refs = new Map<string, GraphAtlasObject[]>();
    const add = (ref: string | undefined, object: GraphAtlasObject) => {
        if (!ref) return;
        const candidates = refs.get(ref) || [];
        if (candidates[candidates.length - 1]?.id !== object.id) candidates.push(object);
        refs.set(ref, candidates);
    };
    for (const object of objects) {
        add(object.id, object);
        add(object.registryEntityId, object);
        for (const sourceId of object.sourceIds || []) add(sourceId, object);
        for (const noteId of object.noteIds || []) add(noteId, object);
        for (const chunkId of object.chunkIds || []) add(chunkId, object);
        for (const anchorId of object.anchorIds || []) add(anchorId, object);
        for (const evidenceId of object.evidenceIds || []) add(evidenceId, object);
    }
    return refs;
}

function graphPacketRepresentedObjectIds(
    packet: GraphAtlasPacket,
    objectForTargetById: Map<string, GraphAtlasObject>,
): Set<string> {
    return new Set(packet.manifoldTargets
        .map((target) => objectForTargetById.get(target.id)?.id || target.objectId)
        .filter(Boolean));
}

function graphPacketObjectForTarget(
    target: GraphAtlasManifoldTarget,
    objectById: Map<string, GraphAtlasObject>,
    objectsBySourceRef: Map<string, GraphAtlasObject[]>,
): GraphAtlasObject | undefined {
    const seen = new Set<string>();
    let best: GraphAtlasObject | undefined;
    let bestScore = Number.NEGATIVE_INFINITY;
    const consider = (object: GraphAtlasObject | undefined) => {
        if (!object || seen.has(object.id)) return;
        seen.add(object.id);
        const score = graphPacketObjectMatchScore(target, object);
        if (score > bestScore || (score === bestScore && (!best || object.id.localeCompare(best.id) < 0))) {
            best = object;
            bestScore = score;
        }
    };
    consider(objectById.get(target.objectId));
    for (const object of objectsBySourceRef.get(target.sourceId) || []) consider(object);
    if (target.registryEntityId) {
        for (const object of objectsBySourceRef.get(target.registryEntityId) || []) consider(object);
    }
    return best;
}

function graphPacketObjectMatchScore(target: GraphAtlasManifoldTarget, object: GraphAtlasObject): number {
    let score = graphPacketFamiliesCompatible(target.family, object.family) ? 100 : 0;
    if (object.id === target.objectId) score += 30;
    if (displayKind(object.kind) === displayKind(target.kind)) score += 24;
    if (object.sourceIds.includes(target.sourceId)) score += 16;
    if (target.registryEntityId && object.registryEntityId === target.registryEntityId) score += 12;
    if (target.noteId && object.noteIds.includes(target.noteId)) score += 4;
    if (target.chunkId && object.chunkIds.includes(target.chunkId)) score += 4;
    return score;
}

function graphPacketFamiliesCompatible(targetFamily: GraphAtlasFamily, objectFamily: GraphAtlasFamily): boolean {
    if (targetFamily === objectFamily) return true;
    return (targetFamily === 'registry' || targetFamily === 'entity')
        && (objectFamily === 'registry' || objectFamily === 'entity');
}

function graphPacketTargetIdByObjectRef(packet: GraphAtlasPacket): Map<string, string> {
    const refs = new Map<string, string>();
    const add = (ref: string | undefined, targetId: string) => {
        if (!ref || refs.has(ref)) return;
        refs.set(ref, targetId);
    };
    for (const target of packet.manifoldTargets) {
        add(target.objectId, target.id);
        add(target.sourceId, target.id);
        add(target.registryEntityId, target.id);
        add(target.noteId, target.id);
        add(target.chunkId, target.id);
        for (const evidenceId of target.evidenceIds || []) add(evidenceId, target.id);
    }
    for (const object of packet.objects) {
        const targetId = graphPacketObjectTargetId(object);
        add(object.id, targetId);
        add(object.registryEntityId, targetId);
        for (const sourceId of object.sourceIds || []) add(sourceId, targetId);
        for (const noteId of object.noteIds || []) add(noteId, targetId);
        for (const chunkId of object.chunkIds || []) add(chunkId, targetId);
        for (const anchorId of object.anchorIds || []) add(anchorId, targetId);
        for (const evidenceId of object.evidenceIds || []) add(evidenceId, targetId);
    }
    return refs;
}

function graphPacketObjectEmbeddingTarget(
    packet: GraphAtlasPacket,
    object: GraphAtlasObject,
    displayTargets: Map<string, GraphRebuildEmbeddingTarget>,
    targetIdByObjectRef: Map<string, string>,
): GraphRebuildEmbeddingTarget | null {
    const id = graphPacketObjectTargetId(object);
    const display = displayTargets.get(id);
    const sourceId = graphPacketObjectSourceId(object) || object.id;
    const parentIds = graphPacketObjectParentIds(object, targetIdByObjectRef, id);
    const style = graphPacketStyleForObject(object, undefined, display);
    return {
        ...display,
        id,
        kind: graphPacketObjectKind(object),
        sourceId,
        noteId: object.noteIds[0] || display?.noteId,
        chunkId: object.chunkIds[0] || display?.chunkId,
        entityId: object.registryEntityId || display?.entityId,
        entityKind: display?.entityKind || graphPacketObjectEntityKind(object),
        label: object.label || display?.label || object.id,
        text: display?.text || graphPacketObjectSummary(object),
        evidenceIds: object.evidenceIds || [],
        lane: (object.lane || display?.lane) as GraphRebuildEmbeddingTarget['lane'],
        structuralRole: (object.structuralRole || display?.structuralRole) as GraphRebuildEmbeddingTarget['structuralRole'],
        admissionStatus: graphPacketObjectAdmissionStatus(object.status) || display?.admissionStatus,
        styleKey: object.styleKey || object.stateContextKind || display?.styleKey || style.colorKind,
        documentUnitKind: object.documentUnitKind || display?.documentUnitKind,
        stateContextKind: object.stateContextKind || display?.stateContextKind,
        atlasFamily: object.family,
        atlasStatus: object.status,
        visualTrace: graphPacketObjectVisualTrace(packet, object, id),
        parentIds: parentIds?.length ? parentIds : display?.parentIds || [],
    };
}

function graphPacketTargetVisualTrace(
    packet: GraphAtlasPacket,
    target: GraphAtlasManifoldTarget,
    object: GraphAtlasObject | undefined,
): GraphRebuildVisualTrace {
    return {
        ...graphTopologyTraceForAtlasTarget(packet, target, target.family),
        sourceId: target.sourceId || graphPacketObjectSourceId(object) || target.objectId,
        packetObjectId: target.objectId,
        packetTargetId: target.id,
        objectKind: object?.kind || '',
        targetKind: target.kind,
        noteIds: target.noteId ? [target.noteId] : object?.noteIds,
        chunkIds: target.chunkId ? [target.chunkId] : object?.chunkIds,
        evidenceIds: target.evidenceIds.length ? target.evidenceIds : object?.evidenceIds,
    };
}

function graphPacketObjectVisualTrace(
    packet: GraphAtlasPacket,
    object: GraphAtlasObject,
    packetTargetId: string,
): GraphRebuildVisualTrace {
    return {
        ...graphTopologyTraceForAtlasObject(packet, object, undefined, object.family),
        sourceId: graphPacketObjectSourceId(object) || object.id,
        packetTargetId,
        targetKind: graphPacketObjectKind(object),
    };
}

function graphPacketTargetKind(kind: string, object: GraphAtlasObject | undefined): string {
    if (object && (object.family === 'registry' || object.family === 'entity')) return 'entity';
    return kind || (object ? graphPacketObjectKind(object) : 'target');
}

function graphPacketObjectKind(object: GraphAtlasObject): string {
    if (object.family === 'registry' || object.family === 'entity') return 'entity';
    return object.kind;
}

function graphPacketObjectEntityKind(object: GraphAtlasObject | undefined): string | undefined {
    if (!object || (object.family !== 'registry' && object.family !== 'entity')) return undefined;
    return object.kind;
}

function graphPacketObjectSourceId(object: GraphAtlasObject | undefined): string | undefined {
    if (!object) return undefined;
    return object.sourceIds[0] || object.registryEntityId || object.id;
}

function graphPacketObjectParentIds(
    object: GraphAtlasObject | undefined,
    targetIdByObjectRef: Map<string, string>,
    targetId: string,
): string[] | undefined {
    if (!object?.targetIds?.length) return undefined;
    const parentIds = object.targetIds
        .map((ref) => targetIdByObjectRef.get(ref) || ref)
        .filter((ref) => ref && ref !== targetId);
    return parentIds.length ? parentIds : undefined;
}

function graphPacketObjectTargetId(object: GraphAtlasObject): string {
    const sourceId = object.sourceIds[0];
    if ((object.family === 'registry' || object.family === 'entity') && object.registryEntityId) {
        return `embed:entity:${object.registryEntityId}`;
    }
    if (object.kind === 'note' && (sourceId || object.noteIds[0])) return `embed:note:${sourceId || object.noteIds[0]}`;
    if (object.kind === 'chunk' && (sourceId || object.chunkIds[0])) return `embed:chunk:${sourceId || object.chunkIds[0]}`;
    if (object.kind === 'entityAnchor' && (sourceId || object.anchorIds[0])) return `embed:anchor:${sourceId || object.anchorIds[0]}`;
    if (object.kind === 'event' && sourceId) return `embed:event:${sourceId}`;
    if (object.kind === 'memoryState' && sourceId) return `embed:memory:${sourceId}`;
    if (object.family === 'temporal' && sourceId) return `embed:temporalFact:${sourceId}`;
    if (object.family === 'causal' && sourceId) return `embed:causalFact:${sourceId}`;
    if (object.family === 'fact' && sourceId) return `embed:graph-fact:${sourceId}`;
    return `embed:atlas-object:${object.id}`;
}

function graphPacketAdmissionStatus(
    admission: GraphAtlasManifoldTarget['admission'],
): GraphRebuildEmbeddingTarget['admissionStatus'] | undefined {
    if (admission === 'admitted' || admission === 'deferred') return admission;
    if (admission === 'rejected') return 'deferred';
    return undefined;
}

function graphPacketObjectAdmissionStatus(
    status: GraphAtlasObject['status'],
): GraphRebuildEmbeddingTarget['admissionStatus'] | undefined {
    if (status === 'accepted' || status === 'compiledToGraph' || status === 'promotedToAnchor') return 'admitted';
    if (status === 'rejected' || status === 'deferred' || status === 'muted') return 'deferred';
    return undefined;
}

function graphPacketObjectSummary(object: GraphAtlasObject): string {
    return [
        `family:${object.family}`,
        `status:${object.status || 'unknown'}`,
        `style:${object.styleKey || object.stateContextKind || object.kind}`,
        object.lane ? `lane:${object.lane}` : '',
        object.structuralRole ? `role:${object.structuralRole}` : '',
        object.documentUnitKind ? `document_unit:${object.documentUnitKind}` : '',
        object.stateContextKind ? `state_context:${object.stateContextKind}` : '',
        object.registryEntityId ? `registry:${object.registryEntityId}` : '',
        object.sourceIds.length ? `sources:${object.sourceIds.join(',')}` : '',
    ].filter(Boolean).join('\n');
}

function graphPacketTargetSummary(target: GraphAtlasManifoldTarget): string {
    return [
        `family:${target.family}`,
        `style:${target.styleKey || target.stateContextKind || target.kind}`,
        target.lane ? `lane:${target.lane}` : '',
        target.structuralRole ? `role:${target.structuralRole}` : '',
        target.documentUnitKind ? `document_unit:${target.documentUnitKind}` : '',
        target.stateContextKind ? `state_context:${target.stateContextKind}` : '',
        `object:${target.objectId}`,
    ].filter(Boolean).join('\n');
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

function graphPacketObjectWeight(object: GraphAtlasObject, target: GraphAtlasManifoldTarget | undefined): number {
    return Math.max(
        1,
        object.evidenceIds.length,
        object.anchorIds.length,
        object.targetIds.length,
        target?.evidenceIds.length || 0,
        target?.parentIds?.length || 0,
    );
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

function displayKind(kind: string): string {
    return String(kind || 'target').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}
