import {
    GRAPH_ATLAS_BUILDER_ROLE,
    GRAPH_ATLAS_IDENTITY_AUTHORITY,
    GRAPH_ATLAS_PACKET_AUTHORITY,
    type GraphAtlasFamily,
    type GraphAtlasManifoldTarget,
    type GraphAtlasObject,
    type GraphAtlasPacket,
} from './graph-atlas-packet';
import type {
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export function filterNativeEmbeddingTargetsForCommittedSources(
    snapshot: GraphRebuildSnapshot,
    targets: GraphRebuildEmbeddingTarget[],
): GraphRebuildEmbeddingTarget[] {
    const committed = committedTargetSources(snapshot);
    return targets.filter((target) => nativeTargetHasCommittedSource(target, committed));
}

export function mergeNativeEmbeddingTargets(
    existing: GraphRebuildEmbeddingTarget[],
    nativeTargets: GraphRebuildEmbeddingTarget[],
): GraphRebuildEmbeddingTarget[] {
    const nativeById = new Map(nativeTargets.map((target) => [target.id, target]));
    const merged = existing.map((target) => nativeById.get(target.id) || target);
    const existingIds = new Set(existing.map((target) => target.id));
    for (const target of nativeTargets) {
        if (!existingIds.has(target.id)) merged.push(target);
    }
    return merged;
}

export function reconcileNativeAtlasPacketForTargets(
    snapshot: GraphRebuildSnapshot,
    packet: GraphAtlasPacket,
): GraphAtlasPacket {
    const packetTargets = new Map(packet.manifoldTargets.map((target) => [target.id, target]));
    const objectsById = new Map(packet.objects.map((object) => [object.id, object]));
    const objectsBySourceId = new Map<string, GraphAtlasObject[]>();
    const objectsByTargetId = new Map<string, GraphAtlasObject[]>();
    for (const object of packet.objects) {
        for (const sourceId of object.sourceIds) pushAtlasObjectLookup(objectsBySourceId, sourceId, object);
        for (const targetId of object.targetIds) pushAtlasObjectLookup(objectsByTargetId, targetId, object);
    }
    const objects = new Map(packet.objects.map((object) => [object.id, object]));
    const targets = snapshot.embeddingTargets.map((target): GraphAtlasManifoldTarget => {
        const existingTarget = packetTargets.get(target.id);
        const existingObject = (existingTarget && objectsById.get(existingTarget.objectId))
            || selectAtlasObjectForTarget(target, objectsByTargetId.get(target.id))
            || selectAtlasObjectForTarget(target, objectsBySourceId.get(target.sourceId));
        const objectId = existingTarget?.objectId || existingObject?.id || `atlas:${target.id}`;
        const family = existingTarget?.family || existingObject?.family || atlasFamilyForTarget(target);
        objects.set(objectId, atlasObjectForTarget(existingObject, objectId, family, target));
        return {
            id: target.id,
            objectId,
            family,
            admission: target.admissionStatus === 'deferred' ? 'deferred' : 'admitted',
            vectorStatus: existingTarget?.vectorStatus || 'missing',
            coordinateSource: existingTarget?.coordinateSource || 'none',
            status: existingTarget?.status || 'accepted',
            kind: target.kind,
            label: target.label,
            entityKind: target.entityKind,
            styleKey: target.styleKey,
            lane: target.lane,
            structuralRole: target.structuralRole,
            documentUnitKind: target.documentUnitKind || existingTarget?.documentUnitKind,
            stateContextKind: target.stateContextKind || existingTarget?.stateContextKind,
            sourceId: target.sourceId,
            registryEntityId: target.entityId,
            noteId: target.noteId,
            chunkId: target.chunkId,
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds,
        };
    });
    const targetIds = new Set(targets.map((target) => target.id));
    for (const parentId of targets.flatMap((target) => target.parentIds || [])) {
        if (targetIds.has(parentId)) continue;
        const parent = objectsById.get(parentId) || objectsBySourceId.get(parentId)?.[0];
        if (parent) objects.set(parent.id, parent);
    }
    const resolvableParents = new Set([
        ...targets.flatMap((target) => [target.id, target.objectId, target.sourceId]),
        ...[...objects.values()].flatMap((object) => [object.id, ...object.sourceIds]),
    ]);
    const reconciledTargets = targets.map((target) => ({
        ...target,
        parentIds: (target.parentIds || []).filter((parentId) => resolvableParents.has(parentId)),
    }));
    const reconciledObjects = [...objects.values()].map((object) => ({
        ...object,
        targetIds: object.targetIds.filter((targetId) => targetIds.has(targetId)),
    }));
    const families = new Map<GraphAtlasFamily, number>();
    for (const object of reconciledObjects) {
        families.set(object.family, (families.get(object.family) || 0) + 1);
    }
    const reconciledPacket: GraphAtlasPacket = {
        ...packet,
        objects: reconciledObjects,
        manifoldTargets: reconciledTargets,
        counters: {
            ...packet.counters,
            objects: reconciledObjects.length,
            manifoldTargets: reconciledTargets.length,
            registryEntities: snapshot.nodes.length,
            evidenceAnchors: snapshot.entityAnchors.length,
            modelVectors: reconciledTargets.filter((target) => target.vectorStatus === 'modelVector').length,
            families: [...families.entries()]
                .sort(([left], [right]) => left.localeCompare(right))
                .map(([family, count]) => ({ family, count })),
        },
    };
    return normalizeNativeAtlasPacketSourceContract(reconciledPacket) || reconciledPacket;
}

export function normalizeNativeAtlasPacketSourceContract(packet: GraphAtlasPacket | undefined): GraphAtlasPacket | undefined {
    if (!packet) return undefined;
    const contract = packet.sourceContract;
    if (contract.authority !== GRAPH_ATLAS_PACKET_AUTHORITY
        || contract.identityAuthority !== GRAPH_ATLAS_IDENTITY_AUTHORITY) {
        return packet;
    }
    if (contract.tsGraphBuilderRole === GRAPH_ATLAS_BUILDER_ROLE) return packet;
    if (!isLegacyAtlasBuilderRole(contract.tsGraphBuilderRole)) return packet;
    return {
        ...packet,
        sourceContract: {
            ...contract,
            tsGraphBuilderRole: GRAPH_ATLAS_BUILDER_ROLE,
        },
    };
}

function isLegacyAtlasBuilderRole(role: string): boolean {
    return role === 'compatibility-only'
        || role === 'compatibility_only'
        || role === 'typescript-compatibility'
        || role === 'typescript_compatibility';
}

function pushAtlasObjectLookup(
    lookup: Map<string, GraphAtlasObject[]>,
    key: string,
    object: GraphAtlasObject,
): void {
    const objects = lookup.get(key);
    if (objects) objects.push(object);
    else lookup.set(key, [object]);
}

function selectAtlasObjectForTarget(
    target: GraphRebuildEmbeddingTarget,
    candidates: GraphAtlasObject[] | undefined,
): GraphAtlasObject | undefined {
    if (!candidates?.length) return undefined;
    const preferredFamily = atlasFamilyForTarget(target);
    return candidates.find((object) => object.family === preferredFamily) || candidates[0];
}

function atlasObjectForTarget(
    existing: GraphAtlasObject | undefined,
    id: string,
    family: GraphAtlasFamily,
    target: GraphRebuildEmbeddingTarget,
): GraphAtlasObject {
    return {
        id,
        family,
        status: existing?.status || 'accepted',
        kind: target.kind,
        label: target.label,
        styleKey: target.styleKey,
        lane: target.lane,
        structuralRole: target.structuralRole,
        documentUnitKind: target.documentUnitKind || existing?.documentUnitKind,
        stateContextKind: target.stateContextKind || existing?.stateContextKind,
        registryEntityId: target.entityId,
        noteIds: target.noteId ? [target.noteId] : existing?.noteIds || [],
        chunkIds: target.chunkId ? [target.chunkId] : existing?.chunkIds || [],
        anchorIds: target.kind === 'anchor' ? target.evidenceIds : existing?.anchorIds || [],
        evidenceIds: target.evidenceIds,
        sourceIds: [...new Set([target.sourceId, ...(existing?.sourceIds || [])])],
        targetIds: [...new Set([target.id, ...(existing?.targetIds || [])])],
    };
}

function atlasFamilyForTarget(target: GraphRebuildEmbeddingTarget): GraphAtlasFamily {
    const kind = normalizeTargetKind(target.kind);
    if (kind === 'entity') return 'registry';
    if (kind === 'note' || kind === 'chunk' || kind === 'episode' || kind === 'structureroot' || kind === 'documentunit') return 'structure';
    if (kind === 'anchor' || kind === 'evidencespan') return 'evidence';
    if (kind === 'temporalfact') return 'temporal';
    if (kind === 'causalfact') return 'causal';
    if (kind === 'memorystate') return 'memory';
    if (kind === 'graphfact' || kind === 'event') return 'fact';
    return 'unknown';
}

function nativeTargetHasCommittedSource(
    target: GraphRebuildEmbeddingTarget,
    committed: ReturnType<typeof committedTargetSources>,
): boolean {
    const kind = normalizeTargetKind(target.kind);
    const lane = target.lane || inferredNativeTargetLane(kind);
    if (kind === 'note' || kind === 'chunk' || kind === 'episode' || kind === 'structureroot' || kind === 'documentunit') return true;
    if (lane === 'entity_anchor' || kind === 'entity') {
        return committed.entities.has(target.entityId || target.sourceId);
    }
    if (lane === 'anchor_evidence' || kind === 'anchor' || kind === 'evidencespan') {
        return committed.anchors.size > 0 && targetReferencesAny(target, committed.anchors);
    }
    if (isNativeFactLane(lane) || ['graphfact', 'temporalfact', 'causalfact', 'memorystate', 'event'].includes(kind)) {
        return committed.facts.size > 0 && targetReferencesAny(target, committed.facts);
    }
    return true;
}

function committedTargetSources(snapshot: GraphRebuildSnapshot) {
    const anchors = new Set([
        ...snapshot.mentions.map((row) => row.id),
        ...snapshot.entityAnchors.map((row) => row.id),
    ]);
    const facts = new Set<string>();
    for (const relationship of snapshot.relationships) {
        addSourceVariants(facts, relationship.id, ['relationship', 'graph-fact']);
    }
    for (const event of snapshot.events) addSourceVariants(facts, event.id, ['event']);
    for (const edge of snapshot.temporalEdges) addSourceVariants(facts, edge.id, ['temporalFact']);
    for (const edge of snapshot.causalEdges) addSourceVariants(facts, edge.id, ['causalFact']);
    for (const state of snapshot.memoryState) addSourceVariants(facts, state.id, ['memory']);
    return {
        anchors,
        entities: new Set(snapshot.nodes.map((node) => node.entityId)),
        facts,
    };
}

function addSourceVariants(out: Set<string>, id: string, prefixes: string[]): void {
    if (!id) return;
    out.add(id);
    out.add(`fact:${id}`);
    out.add(`embed:${id}`);
    for (const prefix of prefixes) {
        out.add(`${prefix}:${id}`);
        out.add(`fact:${prefix}:${id}`);
        out.add(`embed:${prefix}:${id}`);
    }
}

function targetReferencesAny(target: GraphRebuildEmbeddingTarget, allowed: Set<string>): boolean {
    if (allowed.has(target.sourceId)) return true;
    if (target.entityId && allowed.has(target.entityId)) return true;
    return target.evidenceIds.some((id) => allowed.has(id));
}

function inferredNativeTargetLane(kind: string): string {
    if (kind === 'episode') return 'document_spine';
    if (kind === 'entity') return 'entity_anchor';
    if (kind === 'anchor' || kind === 'evidencespan') return 'anchor_evidence';
    if (kind === 'graphfact') return 'relationship_fact';
    if (kind === 'temporalfact') return 'temporal_fact';
    if (kind === 'causalfact') return 'causal_fact';
    if (kind === 'memorystate') return 'memory_state';
    if (kind === 'event') return 'event_identity';
    return 'unknown';
}

function isNativeFactLane(lane: string): boolean {
    return lane === 'relationship_fact'
        || lane === 'temporal_fact'
        || lane === 'causal_fact'
        || lane === 'memory_state'
        || lane === 'event_identity';
}

function normalizeTargetKind(kind: string): string {
    return kind.toLocaleLowerCase().replace(/[^a-z]/g, '');
}
