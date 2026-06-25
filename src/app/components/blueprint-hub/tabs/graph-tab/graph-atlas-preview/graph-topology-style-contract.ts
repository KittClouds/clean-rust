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
import {
    entityColorStore,
    normalizeEntityKind,
    normalizeGraphNodeColorKind,
    type GraphNodeColorKind,
} from '../../../../../lib/store/entityColorStore';
import { GRAPH_RELATION_FAMILY_HSL, relationFamilyFromText } from './graph-relation-visual-style';

export type GraphTopologyCanvasLane = 'entities' | 'structure' | 'facts' | 'discourse';
export type GraphTopologyReviewState = 'accepted' | 'proposed' | 'rejected' | 'muted';

export interface GraphTopologyVisualStyle {
    colorKind: string;
    relationFamily: string;
    entityKind: string;
    colorHsl: string;
}

export function graphTopologyLaneForFamily(family: GraphAtlasFamily | string): GraphTopologyCanvasLane {
    if (family === 'entity' || family === 'registry') return 'entities';
    if (family === 'structure' || family === 'evidence') return 'structure';
    if (family === 'discourse') return 'discourse';
    return 'facts';
}

export function graphTopologyReviewStateForStatus(
    status: GraphAtlasObjectStatus | GraphTopologyReviewState | string | undefined,
): GraphTopologyReviewState {
    if (status === 'accepted' || status === 'compiledToGraph' || status === 'compiled_to_graph' || status === 'promotedToAnchor' || status === 'promoted_to_anchor') {
        return 'accepted';
    }
    if (status === 'rejected') return 'rejected';
    if (status === 'muted') return 'muted';
    return 'proposed';
}

export function graphTopologyReviewStateForAdmission(
    admission: GraphAtlasManifoldTarget['admission'] | string | undefined,
): GraphTopologyReviewState {
    if (admission === 'admitted') return 'accepted';
    if (admission === 'rejected') return 'rejected';
    return 'proposed';
}

export function graphTopologyConfidenceForStatus(status: GraphAtlasObjectStatus | string | undefined): number {
    const reviewState = graphTopologyReviewStateForStatus(status);
    if (reviewState === 'accepted') return 1;
    if (reviewState === 'rejected' || reviewState === 'muted') return 0.24;
    if (status === 'review' || status === 'proposed') return 0.72;
    return 0.56;
}

export function graphTopologyStyleForPacketRow(input: {
    family: GraphAtlasFamily | string;
    kind: string;
    label: string;
    extraParts?: readonly string[];
    styleKey?: string;
    stateContextKind?: string;
}): GraphTopologyVisualStyle {
    const entityKind = input.family === 'entity' || input.family === 'registry'
        ? normalizeEntityKind(input.styleKey || input.kind) || ''
        : '';
    const explicitGraphKind = !entityKind
        ? normalizeGraphNodeColorKind(input.stateContextKind || input.styleKey)
        : null;
    const directColorKind = explicitGraphKind || graphTopologyStyleKindForFamily(input.family, input.kind, input.label);
    const relationFamily = relationFamilyFromText(input.kind, input.label, ...(input.extraParts || []))
        || graphTopologyRelationFamilyForColor(directColorKind);
    const colorKind = entityKind || directColorKind || relationFamily || 'graphFact';
    return {
        colorKind,
        relationFamily,
        entityKind,
        colorHsl: graphTopologyStyleHsl(input.family, colorKind, entityKind),
    };
}

export function graphTopologyStyleForEmbeddingTarget(target: GraphRebuildEmbeddingTarget): GraphTopologyVisualStyle {
    const kind = displayKind(target.kind);
    const entityKind = kind === 'entity' && target.entityKind
        ? normalizeEntityKind(target.entityKind) || ''
        : '';
    const explicitGraphKind = !entityKind
        ? normalizeGraphNodeColorKind(target.stateContextKind || target.styleKey)
        : null;
    const memoryKind = kind === 'memory-state'
        ? graphTopologyMemoryStyleKind(target.stateContextKind, target.styleKey, target.label, target.text, target.sourceId)
        : null;
    const relationFamily = kind === 'graph-fact'
        ? relationFamilyFromText(target.label, target.text, target.sourceId) || ''
        : '';
    const colorKind = entityKind
        || explicitGraphKind
        || memoryKind
        || relationFamily
        || graphTopologyStyleKindForEmbeddingKind(kind);
    return {
        colorKind,
        relationFamily,
        entityKind,
        colorHsl: graphTopologyStyleHsl(target.atlasFamily || target.kind, colorKind, entityKind),
    };
}

export function graphTopologyTraceForAtlasObject(
    packet: GraphAtlasPacket,
    object: GraphAtlasObject,
    target: GraphAtlasManifoldTarget | undefined,
    family = object.family || 'unknown',
): GraphRebuildVisualTrace {
    return {
        source: 'rust_atlas_packet',
        sourceId: object.sourceIds[0] || target?.sourceId || object.id,
        family,
        packetSnapshotId: packet.snapshotId,
        packetScopeId: packet.scopeId,
        sourceContract: packet.sourceContract.authority,
        vectorContract: packet.sourceContract.vectorContract,
        identityAuthority: packet.sourceContract.identityAuthority,
        packetObjectId: object.id,
        packetTargetId: target?.id || '',
        objectKind: object.kind,
        targetKind: target?.kind || '',
        noteIds: object.noteIds,
        chunkIds: object.chunkIds,
        evidenceIds: object.evidenceIds,
    };
}

export function graphTopologyTraceForAtlasTarget(
    packet: GraphAtlasPacket,
    target: GraphAtlasManifoldTarget,
    family = target.family || 'unknown',
): GraphRebuildVisualTrace {
    return {
        source: 'rust_atlas_packet',
        sourceId: target.sourceId || target.objectId,
        family,
        packetSnapshotId: packet.snapshotId,
        packetScopeId: packet.scopeId,
        sourceContract: packet.sourceContract.authority,
        vectorContract: packet.sourceContract.vectorContract,
        identityAuthority: packet.sourceContract.identityAuthority,
        packetObjectId: target.objectId,
        packetTargetId: target.id,
        objectKind: '',
        targetKind: target.kind,
        noteIds: target.noteId ? [target.noteId] : [],
        chunkIds: target.chunkId ? [target.chunkId] : [],
        evidenceIds: target.evidenceIds,
    };
}

export function graphTopologyTraceForAtlasEdge(
    packet: GraphAtlasPacket,
    input: {
        sourceId: string;
        targetId: string;
        family: GraphAtlasFamily | string;
        type: string;
        evidenceIds: string[];
    },
): GraphRebuildVisualTrace {
    return {
        source: 'rust_atlas_packet',
        sourceId: input.sourceId,
        family: input.family,
        packetSnapshotId: packet.snapshotId,
        packetScopeId: packet.scopeId,
        sourceContract: packet.sourceContract.authority,
        vectorContract: packet.sourceContract.vectorContract,
        identityAuthority: packet.sourceContract.identityAuthority,
        packetObjectId: input.sourceId,
        packetTargetId: input.targetId,
        objectKind: input.type,
        targetKind: input.type,
        noteIds: [],
        chunkIds: [],
        evidenceIds: input.evidenceIds,
    };
}

export function graphTopologyTraceForEmbeddingTarget(target: GraphRebuildEmbeddingTarget): GraphRebuildVisualTrace {
    return target.visualTrace || graphTopologyFallbackVisualTrace(
        target.id,
        target.sourceId || target.id,
        target.atlasFamily || target.styleKey || target.kind || 'unknown',
        target.evidenceIds,
    );
}

export function graphTopologyFallbackVisualTrace(
    targetId: string,
    sourceId = targetId,
    family = 'unknown',
    evidenceIds: string[] = [],
): GraphRebuildVisualTrace {
    return {
        source: 'graph_rebuild_embedding_target',
        sourceId,
        family,
        packetTargetId: targetId,
        evidenceIds,
    };
}

export function graphTopologyMemoryStyleKind(
    stateContextKind = '',
    styleKey = '',
    label = '',
    text = '',
    sourceId = '',
): GraphNodeColorKind {
    const explicit = normalizeGraphNodeColorKind(stateContextKind || styleKey);
    if (explicit) return explicit;
    const token = compactStyleToken(`${label} ${text} ${sourceId}`);
    if (token.includes('decisionstate') || token.includes('approved') || token.includes('accepted') || token.includes('decision')) return 'decisionState';
    if (token.includes('servicecontext') || token.includes('servicerank') || token.includes('service')) return 'serviceContext';
    if (token.includes('rankorstatus') || token.includes('rankstatus') || token.includes('rank')) return 'rankStatus';
    if (token.includes('affiliationcontext') || token.includes('affiliatecontext') || token.includes('affiliantcontext') || token.includes('affiliation')) return 'affiliationContext';
    if (token.includes('familycontext') || token.includes('family')) return 'familyContext';
    return 'memoryState';
}

export function graphTopologyDisplayColorKind(colorKind: string): string {
    return displayKind(colorKind);
}

function graphTopologyStyleKindForFamily(family: GraphAtlasFamily | string, kind: string, label: string): GraphNodeColorKind | '' {
    const token = compactStyleToken(`${kind} ${label}`);
    if (family === 'structure') return token.includes('chunk') || token.includes('documentunit') || token.includes('leaf') ? 'chunk' : 'document';
    if (family === 'evidence') return 'anchor';
    if (family === 'temporal' || token.includes('temporalfact')) return 'temporalFact';
    if (family === 'causal' || token.includes('causalfact')) return 'causalFact';
    if (family === 'memory' || token.includes('memorystate')) return graphTopologyMemoryStyleKind('', '', kind, label);
    if (family === 'discourse') return 'communication';
    if (family === 'review') return 'rankStatus';
    if (family === 'hypergraph') return 'relationship';
    if (family === 'fact') {
        if (token.includes('event')) return 'eventNode';
        if (token.includes('graphfact')) return 'graphFact';
    }
    return normalizeGraphNodeColorKind(kind) || normalizeGraphNodeColorKind(label) || '';
}

function graphTopologyStyleKindForEmbeddingKind(kind: string): GraphNodeColorKind {
    switch (kind) {
        case 'note':
        case 'structure-root':
            return 'document';
        case 'chunk':
        case 'document-unit':
            return 'chunk';
        case 'anchor':
        case 'concept':
        case 'evidence-span':
            return 'anchor';
        case 'event':
            return 'eventNode';
        case 'temporal-fact':
            return 'temporalFact';
        case 'causal-fact':
            return 'causalFact';
        case 'memory-state':
            return 'memoryState';
        case 'graph-fact':
        default:
            return 'graphFact';
    }
}

function graphTopologyRelationFamilyForColor(colorKind: string): GraphNodeColorKind | '' {
    return Object.prototype.hasOwnProperty.call(GRAPH_RELATION_FAMILY_HSL, colorKind) ? colorKind as GraphNodeColorKind : '';
}

function graphTopologyStyleHsl(family: GraphAtlasFamily | string, colorKind: string, entityKind: string): string {
    if (entityKind) return entityColorStore.getRawHsl(entityKind);
    const graphKind = normalizeGraphNodeColorKind(colorKind);
    if (graphKind) return entityColorStore.getRawGraphNodeHsl(graphKind);
    if (family === 'entity' || family === 'registry') return entityColorStore.getRawHsl('CHARACTER');
    if (family === 'structure') return entityColorStore.getRawGraphNodeHsl('document');
    if (family === 'evidence') return entityColorStore.getRawGraphNodeHsl('anchor');
    if (family === 'discourse') return entityColorStore.getRawGraphNodeHsl('communication');
    if (family === 'temporal') return entityColorStore.getRawGraphNodeHsl('temporalFact');
    if (family === 'causal') return entityColorStore.getRawGraphNodeHsl('causalFact');
    if (family === 'memory') return entityColorStore.getRawGraphNodeHsl('memoryState');
    if (family === 'review') return entityColorStore.getRawGraphNodeHsl('rankStatus');
    if (family === 'hypergraph') return entityColorStore.getRawGraphNodeHsl('relationship');
    return entityColorStore.getRawGraphNodeHsl('graphFact') || '220 10% 54%';
}

function displayKind(kind: string): string {
    return String(kind || 'target').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

function compactStyleToken(value: string): string {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}
