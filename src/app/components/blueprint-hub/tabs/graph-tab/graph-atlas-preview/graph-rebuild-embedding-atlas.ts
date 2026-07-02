import {
    HOPF_MANIFOLD_CAPABILITIES,
    HYBRID_MANIFOLD_CAPABILITIES,
    LORENTZ_MANIFOLD_CAPABILITIES,
    PRODUCT_MANIFOLD_CAPABILITIES,
    SIEGEL_FINSLER_CAPABILITIES,
    type AtlasManifoldMode,
    type ConeObstructionRecord,
    type ConePathletRecord,
    type ConeProgramRecord,
    type ConeProgramTraceRecord,
    type ManifoldCapabilities,
} from '../../../../../services/manifold-atlas.types';
import type {
    GraphRebuildEmbeddingTargetPostProcess,
    GraphRebuildEmbeddingTarget,
    GraphRebuildProductLaneFeatures,
    GraphRebuildProductLaneKind,
    GraphRebuildProductTopologyRegion,
    GraphRebuildSnapshot,
    GraphRebuildVisualTrace,
} from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import {
    normalizeEmbeddingProfile,
    sparseEmbeddingSignature,
    sparseToDenseVector,
} from '../../../../../graph-rebuild/graph-rebuild-embedding-signatures';
import type {
    HopfResonanceAssignment,
    HopfResonanceFiber,
    HopfResonanceSpace,
} from '../../../../../graph-rebuild/graph-hopf-resonance-space';
import type { GraphModelV2FactBundleCommitment } from '../../../../../graph-rebuild/graph-model-v2';
import { createGraphModelV2ReadModel } from '../../../../../graph-rebuild/graph-model-v2-read-model';
import { buildGraphSignalTruthIndex, type GraphSignalTruthRecord } from '../../../../../graph-rebuild/graph-rebuild-signal-truth';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';
import type { EmbeddingAtlasData, EmbeddingAtlasSearchItem } from './graph-embedding-atlas';
import { relationFamilyFromText } from './graph-relation-visual-style';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { HIERARCHY_SHELL_BANDS, type CapsHierarchyRole, type HierarchyShellBand } from './graph-galaxy-hierarchy-caps';
import {
    graphTopologyDisplayColorKind,
    graphTopologyFallbackVisualTrace,
    graphTopologyStyleForEmbeddingTarget,
    graphTopologyTraceForEmbeddingTarget,
} from './graph-topology-style-contract';
import {
    buildGraphPacketRowAdapter,
    graphPacketEmbeddingTargetCount,
} from './graph-packet-row-adapter';
import { episodeProjectionEmbeddingEdge } from './graph-episode-projection-canvas';

const HOPF_RESONANCE_DIMS = 96;
const HOPF_RESONANCE_NEIGHBORS = 8;
const HOPF_RESONANCE_FIBER_MEMBER_LIMIT = HOPF_RESONANCE_NEIGHBORS + 1;
const HOPF_RESONANCE_THRESHOLD = 0.56;
const HOPF_RESONANCE_EDGE_FLOOR = 0.44;

type HopfBaseAssignment = {
    role: 'anchor' | 'fiber' | 'loose';
    rootBaseId?: string;
    baseId?: string;
    anchorTargetId?: string;
    splitKey?: string;
    fiberKind: string;
    phase: number;
    support: number;
    coherence: number;
    frustration: number;
    neighborCount: number;
    cellId?: string;
    secondaryCellIds?: string[];
    assignmentScore?: number;
    residualScore?: number;
    salience?: number;
    strandKey?: string;
    strandIndex?: number;
    strandCount?: number;
    phaseSpread?: number;
    direction?: readonly number[];
    tangent?: readonly number[];
    receipt?: string;
    resonanceSource?: 'point-formed' | 'snapshot-hopf-resonance-space';
    noTopologyMutation?: boolean;
};

type TargetHierarchyContext = {
    noteId?: string;
    chunkId?: string;
    supportNoteIds?: string[];
    supportChunkIds?: string[];
    folderId?: string;
    folderLabel?: string;
    folderKind?: string;
    folderParentId?: string;
};

type CapsVec3 = { x: number; y: number; z: number };

type CapsHierarchyPath = {
    role: CapsHierarchyRole;
    band: HierarchyShellBand;
    capId: string;
    parentCapIds: string[];
    parentNodeId: string | null;
};

type MentionCompactionReceipt = {
    mode: 'entity_mention_compaction_v1';
    source: 'atlas_view_compaction';
    expanded: false;
    anchorCount: number;
    anchorIds: string[];
    noteIds: string[];
    chunkIds: string[];
    surfaces: string[];
    maxConfidence: number;
};

type MentionCompactionSelection = {
    targets: GraphRebuildEmbeddingTarget[];
    receiptsByEntityTargetId: Map<string, MentionCompactionReceipt>;
};

type ProductTraversalBuild = {
    programs: ConeProgramRecord[];
    pathlets: ConePathletRecord[];
    obstructions: ConeObstructionRecord[];
    traces: ConeProgramTraceRecord[];
    nodeMetadata: Map<string, Record<string, unknown>>;
    edgeMetadata: Map<string, Record<string, unknown>>;
};

export function buildGraphRebuildEmbeddingAtlas(
    snapshot: GraphRebuildSnapshot,
    manifold: AtlasManifoldMode,
): EmbeddingAtlasData {
    // Compatibility adapter: Rust Atlas packets own target membership/coordinates.
    const atlasSnapshot = snapshotWithAtlasPacketTargets(snapshot);
    const entityKindById = new Map(atlasSnapshot.nodes.map((node) => [node.entityId, node.kind]));
    const profile = normalizeEmbeddingProfile(atlasSnapshot.embeddingProfile);
    const postByTarget = new Map((atlasSnapshot.embeddingGraphPostProcess?.targets || []).map((row) => [row.targetId, row]));
    const mentionCompaction = compactEntityMentionTargets(atlasSnapshot, selectEmbeddingTargets(atlasSnapshot));
    const selected = mentionCompaction.targets
        .map((target) => hydrateTargetEntityKind(target, entityKindById));
    const hierarchyByTarget = buildTargetHierarchyContext(atlasSnapshot);
    const truthByTarget = buildGraphSignalTruthIndex(atlasSnapshot);
    const commitmentBySourceId = buildBundleCommitmentIndex(atlasSnapshot);
    const vectors = selected.map((target) => textVector(target, profile.selectedDimensions));
    const capsDocumentDirections = buildCapsDocumentDirections(selected, vectors, manifold);
    const hopfBasePlan = manifold === 'hopf' ? buildHopfAtlasAssignmentPlan(atlasSnapshot, selected, vectors, postByTarget) : undefined;
    const rawNodes = selected.map((target, index) =>
        targetNode(target, vectors[index], index, selected.length, manifold, postByTarget.get(target.id), hopfBasePlan?.get(target.id), hierarchyByTarget.get(target.id), truthByTarget.get(target.id), commitmentBySourceId.get(target.sourceId) || commitmentBySourceId.get(target.id), mentionCompaction.receiptsByEntityTargetId.get(target.id), capsDocumentDirections),
    );
    const nodeIds = new Set(rawNodes.map((node) => node.id));
    const traceByTargetId = new Map(selected.map((target) => [target.id, graphTopologyTraceForEmbeddingTarget(target)]));
    const rawEdges = buildTargetEdges(atlasSnapshot)
        .filter((edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId))
        .map((edge) => edgeWithVisualTrace(edge, traceByTargetId));
    const traversal = manifold === 'product' ? buildGraphRebuildProductTraversal(selected, rawEdges) : emptyProductTraversal();
    const nodes = rawNodes.map((node) => {
        const productTraversal = traversal.nodeMetadata.get(node.id);
        if (!productTraversal) return node;
        return {
            ...node,
            metadata: {
                ...node.metadata,
                productTraversal,
            },
        };
    });
    const edges = rawEdges.map((edge) => {
        const productTraversal = traversal.edgeMetadata.get(edge.id);
        if (!productTraversal) return edge;
        return {
            ...edge,
            metadata: {
                ...(edge.metadata || {}),
                productTraversal,
            },
        };
    });
    return {
        nodes,
        edges,
        sourceLabel: `${atlasProjectionSourceLabel(atlasSnapshot)} -> ${graphRebuildProjectionLabel(manifold)} projection`,
        searchIndex: nodes.map((node, index): EmbeddingAtlasSearchItem => ({
            nodeId: node.id,
            vector: vectors[index],
        })),
        manifold: {
            mode: manifold,
            geometryVersion: graphRebuildGeometryVersion(manifold),
            sourceLabel: atlasProjectionSourceLabel(atlasSnapshot),
            capabilities: graphRebuildCapabilities(manifold),
            projectionSource: atlasSnapshot.atlasPacket ? 'rust_atlas_packet_manifold_targets' : 'graph_rebuild_embedding_targets',
            cells: [],
            charts: [],
            seams: [],
            neighborRings: [],
            coneTraces: [],
            conePrograms: traversal.programs,
            pathlets: traversal.pathlets,
            obstructions: traversal.obstructions,
            coneProgramTraces: traversal.traces,
            anchorProjections: [],
        },
    };
}

export function graphRebuildEmbeddingTargetCount(snapshot: GraphRebuildSnapshot | null | undefined): number {
    return snapshot?.embeddingTargets.length
        || (snapshot?.atlasPacket ? graphPacketEmbeddingTargetCount(snapshot.atlasPacket) : 0)
        || snapshot?.counters.embeddingTargets
        || 0;
}

function snapshotWithAtlasPacketTargets(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    const packet = snapshot.atlasPacket;
    if (!packet?.manifoldTargets?.length && !packet?.objects?.length) return snapshot;
    const rows = buildGraphPacketRowAdapter(packet, snapshot.embeddingTargets);
    const targets = normalizeEmbedStructureParents(rows.embeddingTargets);
    return { ...snapshot, embeddingTargets: targets };
}

function atlasProjectionSourceLabel(snapshot: GraphRebuildSnapshot): string {
    return snapshot.atlasPacket?.sourceContract.authority || 'graph rebuild snapshot';
}

function selectEmbeddingTargets(snapshot: GraphRebuildSnapshot): GraphRebuildEmbeddingTarget[] {
    const candidates = snapshot.embeddingTargets.filter((target) => target.text.trim() || target.label.trim());
    return coverageOrderedTargets(candidates.filter(isVisibleAtlasTarget));
}

function compactEntityMentionTargets(
    snapshot: GraphRebuildSnapshot,
    selected: GraphRebuildEmbeddingTarget[],
): MentionCompactionSelection {
    const allTargetsById = new Map(snapshot.embeddingTargets.map((target) => [target.id, target]));
    const selectedById = new Map(selected.map((target) => [target.id, target]));
    const receiptDrafts = new Map<string, {
        anchorIds: string[];
        noteIds: Set<string>;
        chunkIds: Set<string>;
        surfaces: Set<string>;
        maxConfidence: number;
    }>();
    const recordAnchor = (
        entityId: string | undefined,
        anchorId: string,
        noteId: string | undefined,
        chunkId: string | undefined,
        surface: string | undefined,
        confidence: number,
    ) => {
        if (!entityId || !anchorId) return;
        const entityTargetId = `embed:entity:${entityId}`;
        const entityTarget = selectedById.get(entityTargetId) || allTargetsById.get(entityTargetId);
        if (!entityTarget) return;
        selectedById.set(entityTargetId, entityTarget);
        const draft = receiptDrafts.get(entityTargetId) || {
            anchorIds: [],
            noteIds: new Set<string>(),
            chunkIds: new Set<string>(),
            surfaces: new Set<string>(),
            maxConfidence: 0,
        };
        if (!draft.anchorIds.includes(anchorId)) draft.anchorIds.push(anchorId);
        if (noteId) draft.noteIds.add(noteId);
        if (chunkId) draft.chunkIds.add(chunkId);
        if (surface) draft.surfaces.add(surface);
        draft.maxConfidence = Math.max(draft.maxConfidence, confidence || 0);
        receiptDrafts.set(entityTargetId, draft);
    };

    for (const anchor of snapshot.entityAnchors || []) {
        recordAnchor(anchor.entityId, anchor.id, anchor.noteId, anchor.chunkId, anchor.surface, anchor.confidence);
    }
    for (const target of selected) {
        if (!isEntityMentionAnchorTarget(target) || !target.entityId) continue;
        recordAnchor(target.entityId, target.sourceId || target.id.replace(/^embed:anchor:/, ''), target.noteId, target.chunkId, target.label, targetConfidence(target));
    }

    for (const target of selected) {
        if (!isEntityMentionAnchorTarget(target) || !target.entityId) continue;
        const entityTargetId = `embed:entity:${target.entityId}`;
        if (!selectedById.has(entityTargetId)) continue;
        selectedById.delete(target.id);
    }

    const receiptsByEntityTargetId = new Map<string, MentionCompactionReceipt>();
    for (const [entityTargetId, draft] of receiptDrafts) {
        if (!selectedById.has(entityTargetId) || draft.anchorIds.length === 0) continue;
        receiptsByEntityTargetId.set(entityTargetId, {
            mode: 'entity_mention_compaction_v1',
            source: 'atlas_view_compaction',
            expanded: false,
            anchorCount: draft.anchorIds.length,
            anchorIds: draft.anchorIds.slice(0, 96),
            noteIds: [...draft.noteIds].sort(),
            chunkIds: [...draft.chunkIds].sort(),
            surfaces: [...draft.surfaces].sort().slice(0, 24),
            maxConfidence: clamp01(draft.maxConfidence),
        });
    }

    return {
        targets: [...selectedById.values()],
        receiptsByEntityTargetId,
    };
}

function isEntityMentionAnchorTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return target.kind === 'anchor'
        || displayKind(target.kind) === 'entity-anchor'
        || target.id.startsWith('embed:anchor:')
        || target.lane === 'anchor_evidence'
        || target.styleKey === 'anchor';
}

function isVisibleAtlasTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return isCuratedEmbedManifoldTarget(target) && !isWeakCooccurrenceTarget(target);
}

function isWeakCooccurrenceTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return target.lane === 'cooccurrence_weak'
        || compactEmbedToken(target.styleKey || '') === 'cooccurrence'
        || (displayKind(target.kind) === 'graph-fact'
            && relationFamilyFromText(target.label, target.text, target.sourceId) === 'cooccurrence');
}

const CURATED_EMBED_DROP_KINDS = new Set([
    'sentence',
    'text-sentence',
    'document-sentence',
    'paragraph',
    'text-paragraph',
    'document-paragraph',
    'paragraph-group',
    'section',
    'region',
    'mention',
    'entity-mention',
    'raw-mention',
    'occurrence',
    'raw-occurrence',
    'alias-patch',
    'linker-vote',
    'receipt',
    'debug',
]);

const CURATED_DOCUMENT_UNIT_TOKENS = [
    'leaf',
    'claim',
    'actionblock',
    'action',
    'contrast',
    'looked',
    'glanced',
    'evidence',
    'decision',
];

const SENTENCE_PARAGRAPH_TAXONOMY_TOKENS = [
    'paragraph',
    'paragraphgroup',
    'sentence',
    'textsentence',
    'documentsentence',
    'textparagraph',
    'documentparagraph',
];

function isCuratedEmbedManifoldTarget(target: GraphRebuildEmbeddingTarget): boolean {
    const kind = displayKind(target.kind);
    if (CURATED_EMBED_DROP_KINDS.has(kind) || isSentenceOrParagraphTarget(target, kind)) return false;
    if (isRawEmbedScaffoldTarget(target, kind)) return false;
    if (kind === 'document-unit') return isCuratedDocumentUnitTarget(target);
    return true;
}

function normalizeEmbedStructureParents(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    const targetIds = new Set(targets.map((target) => target.id));
    return targets.map((target) => {
        if (!isDocumentStructureUnitTarget(target) || !target.chunkId) return target;
        const chunkParentId = `embed:chunk:${target.chunkId}`;
        if (!targetIds.has(chunkParentId)) return target;
        const rootParents = (target.parentIds || [])
            .filter((parentId) => parentId.startsWith('embed:structure-root:'));
        const otherParents = (target.parentIds || [])
            .filter((parentId) => parentId !== chunkParentId
                && !parentId.startsWith('embed:document-unit:')
                && !parentId.startsWith('embed:structure-root:'));
        const parentIds = [...new Set([chunkParentId, ...rootParents, ...otherParents])];
        return { ...target, parentIds };
    });
}

function isCuratedDocumentUnitTarget(target: GraphRebuildEmbeddingTarget): boolean {
    const documentUnitKind = compactEmbedToken(target.documentUnitKind || '');
    if (documentUnitKind) {
        return CURATED_DOCUMENT_UNIT_TOKENS.some((token) => documentUnitKind.includes(token));
    }
    const profile = compactEmbedProfileText(target, true);
    return CURATED_DOCUMENT_UNIT_TOKENS.some((token) => profile.includes(token));
}

function compactEmbedToken(value: string): string {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function isSentenceOrParagraphTarget(target: GraphRebuildEmbeddingTarget, kind: string): boolean {
    if (kind.endsWith('-sentence') || kind.endsWith('-paragraph')) return true;
    if ([
        kind,
        target.styleKey || '',
        target.stateContextKind || '',
    ].some(isSentenceOrParagraphTaxonomyToken)) {
        return true;
    }
    if (isDocumentStructureUnitTarget(target)) {
        const unitProfile = compactEmbedProfileText(target, true);
        if (SENTENCE_PARAGRAPH_TAXONOMY_TOKENS.some((token) => unitProfile.includes(token))) {
            return true;
        }
    }
    const documentUnitKind = compactEmbedToken(target.documentUnitKind || '');
    if (documentUnitKind) {
        return SENTENCE_PARAGRAPH_TAXONOMY_TOKENS.some((token) => documentUnitKind === token || documentUnitKind.includes(token));
    }
    const profile = compactEmbedProfileText(target, false);
    return [
        'kindparagraph',
        'kindsentence',
        'documentsidecarparagraph',
        'documentsidecarsentence',
        'paragraphgroup',
        'paragraphindex',
        'sentenceindex',
    ].some((token) => profile.includes(token));
}

function isSentenceOrParagraphTaxonomyToken(value: string): boolean {
    const token = compactEmbedToken(value);
    return Boolean(token && SENTENCE_PARAGRAPH_TAXONOMY_TOKENS.some((dropToken) => token === dropToken || token.includes(dropToken)));
}

function isDocumentStructureUnitTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return displayKind(target.kind) === 'document-unit'
        || target.id.startsWith('embed:document-unit:')
        || target.sourceId.startsWith('document-unit:')
        || target.documentUnitKind !== undefined;
}

function isRawEmbedScaffoldTarget(target: GraphRebuildEmbeddingTarget, kind: string): boolean {
    if (kind.includes('candidate') || kind.includes('receipt') || kind.includes('debug')) return true;
    const profile = compactEmbedProfileText(target, false);
    return [
        'rawmention',
        'rawoccurrence',
        'aliaspatch',
        'linkervote',
        'candidatetrace',
        'debugpacket',
    ].some((token) => profile.includes(token));
}

function compactEmbedProfileText(target: GraphRebuildEmbeddingTarget, includeBody: boolean): string {
    return compactSiegelToken([
        target.id,
        target.kind,
        target.sourceId,
        target.lane,
        target.structuralRole,
        target.label,
        includeBody ? target.text : '',
    ].filter(Boolean).join(' '));
}

function coverageOrderedTargets(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    const weight = (target: GraphRebuildEmbeddingTarget) => {
        switch (displayKind(target.kind)) {
            case 'note': return 900;
            case 'structure-root': return 890;
            case 'chunk': return 880;
            case 'document-unit': return 875;
            case 'causal-fact': return 860;
            case 'temporal-fact': return 850;
            case 'event': return 830;
            case 'memory-state': return 810;
            case 'graph-fact': return 790;
            case 'entity': return 760;
            case 'concept': return 750;
            case 'anchor': return 700;
            case 'evidence-span': return 700;
            default: return 650;
        }
    };
    return [...targets].sort((left, right) =>
        weight(right) - weight(left)
        || targetEvidenceScore(right) - targetEvidenceScore(left)
        || left.id.localeCompare(right.id),
    );
}

function targetEvidenceScore(target: GraphRebuildEmbeddingTarget): number {
    const confidence = targetConfidence(target);
    const text = `${target.label} ${target.text}`.toLowerCase();
    let score = confidence * 100 + Math.min(48, target.evidenceIds.length * 6);
    if (text.includes('[accepted]')) score += 34;
    if (/causal|cause|because|before|after|temporal|memory_key|chunk_role|meaning_cues/.test(text)) score += 24;
    if (/evidence_context:/.test(text)) score += 16;
    return score;
}

const PRODUCT_CONE_TRAVERSAL_GEOMETRY = 'graph_rebuild_product_cone_traversal_v1';
const PRODUCT_ROUTE_LEGAL_MOVES = new Set([
    'evidence>identity',
    'evidence>relationship',
    'evidence>temporal',
    'evidence>causal',
    'identity>relationship',
    'identity>event',
    'identity>temporal',
    'identity>causal',
    'relationship>evidence',
    'relationship>identity',
    'relationship>temporal',
    'relationship>causal',
    'event>temporal',
    'event>causal',
    'temporal>event',
    'temporal>causal',
    'causal>event',
    'causal>temporal',
    'bridge>identity',
    'bridge>relationship',
    'bridge>evidence',
    'semantic>identity',
    'semantic>relationship',
    'semantic>evidence',
]);

function emptyProductTraversal(): ProductTraversalBuild {
    return {
        programs: [],
        pathlets: [],
        obstructions: [],
        traces: [],
        nodeMetadata: new Map(),
        edgeMetadata: new Map(),
    };
}

function buildGraphRebuildProductTraversal(
    targets: GraphRebuildEmbeddingTarget[],
    edges: GalaxyInputEdge[],
): ProductTraversalBuild {
    const out = emptyProductTraversal();
    const targetById = new Map(targets.map((target) => [target.id, target]));
    const obstructionByEdge = new Map<string, string[]>();

    for (const target of targets) {
        const lane = productRouteLaneForTarget(target);
        const obstruction = productTargetObstruction(target, lane);
        if (!obstruction) continue;
        out.obstructions.push(obstruction);
        mergeTraversalNode(out.nodeMetadata, target.id, {
            lane,
            routeStage: productRouteStage(lane),
            supportScore: targetConfidence(target),
            obstructionScore: obstruction.severity,
            obstructionKind: obstruction.kind,
            obstructionIds: [obstruction.obstructionId],
        });
    }

    for (const edge of edges) {
        const source = targetById.get(edge.sourceId);
        const target = targetById.get(edge.targetId);
        if (!source || !target) continue;
        const sourceLane = productRouteLaneForTarget(source);
        const targetLane = productRouteLaneForTarget(target);
        const lane = productPathletLane(edge, sourceLane, targetLane);
        const obstruction = productEdgeObstruction(edge, source, target, sourceLane, targetLane);
        const obstructionIds = obstruction ? [obstruction.obstructionId] : [];
        if (obstruction) {
            out.obstructions.push(obstruction);
            obstructionByEdge.set(edge.id, obstructionIds);
        }
        const supportScore = productPathletSupport(edge, source, target, sourceLane, targetLane);
        const pathlet: ConePathletRecord = {
            pathletId: `pathlet:${normalizeHopfToken(edge.id)}`,
            lane,
            startId: edge.sourceId,
            endId: edge.targetId,
            nodeIds: [edge.sourceId, edge.targetId],
            edgeIds: [edge.id],
            supportScore,
            compressionScore: clamp01(0.42 + supportScore * 0.38 + parentOverlapScore(source, target)),
            obstructionIds,
            geometryVersion: PRODUCT_CONE_TRAVERSAL_GEOMETRY,
        };
        out.pathlets.push(pathlet);
        out.edgeMetadata.set(edge.id, {
            lane,
            pathletId: pathlet.pathletId,
            supportScore,
            obstructionIds,
            obstructionScore: obstruction?.severity ?? 0,
            obstructionKind: obstruction?.kind,
        });
        mergeTraversalNode(out.nodeMetadata, edge.sourceId, productNodeTraversal(sourceLane, pathlet, obstruction));
        mergeTraversalNode(out.nodeMetadata, edge.targetId, productNodeTraversal(targetLane, pathlet, obstruction));
    }

    out.programs = buildProductConePrograms(out.pathlets, out.obstructions);
    out.traces = out.programs.map((program) => productTraceForProgram(program, out.pathlets, out.obstructions, obstructionByEdge));
    return out;
}

function productNodeTraversal(lane: string, pathlet: ConePathletRecord, obstruction: ConeObstructionRecord | null): Record<string, unknown> {
    return {
        lane,
        routeStage: productRouteStage(lane),
        pathletIds: [pathlet.pathletId],
        supportScore: pathlet.supportScore,
        obstructionIds: pathlet.obstructionIds,
        obstructionScore: obstruction?.severity ?? 0,
        obstructionKind: obstruction?.kind,
    };
}

function mergeTraversalNode(target: Map<string, Record<string, unknown>>, nodeId: string, next: Record<string, unknown>): void {
    const current = target.get(nodeId) || {};
    const pathletIds = [...new Set([...(current['pathletIds'] as string[] | undefined || []), ...(next['pathletIds'] as string[] | undefined || [])])];
    const obstructionIds = [...new Set([...(current['obstructionIds'] as string[] | undefined || []), ...(next['obstructionIds'] as string[] | undefined || [])])];
    target.set(nodeId, {
        ...current,
        ...next,
        lane: current['lane'] || next['lane'],
        routeStage: Math.max(Number(current['routeStage'] ?? next['routeStage'] ?? 0), Number(next['routeStage'] ?? 0)),
        supportScore: Math.max(Number(current['supportScore'] || 0), Number(next['supportScore'] || 0)),
        obstructionScore: Math.max(Number(current['obstructionScore'] || 0), Number(next['obstructionScore'] || 0)),
        obstructionKind: next['obstructionKind'] || current['obstructionKind'],
        pathletIds,
        obstructionIds,
    });
}

function productRouteLaneForTarget(target: GraphRebuildEmbeddingTarget): string {
    const lane = String(target.lane || '').toLowerCase();
    if (/document|chunk|anchor_evidence/.test(lane)) return 'evidence';
    if (/entity_anchor|entity_linker/.test(lane)) return 'identity';
    if (/relationship|cooccurrence/.test(lane)) return lane.includes('cooccurrence') ? 'bridge' : 'relationship';
    if (/temporal/.test(lane)) return 'temporal';
    if (/causal/.test(lane)) return 'causal';
    if (/event/.test(lane)) return 'event';
    if (/memory/.test(lane)) return 'relationship';
    const kind = displayKind(target.kind);
    if (/document|chunk|anchor|evidence/.test(kind)) return 'evidence';
    if (/entity|character|location|network|concept/.test(kind)) return 'identity';
    if (/temporal/.test(kind)) return 'temporal';
    if (/causal/.test(kind)) return 'causal';
    if (/event/.test(kind)) return 'event';
    if (/relationship|fact/.test(kind)) return 'relationship';
    return 'semantic';
}

function productRouteStage(lane: string): number {
    if (lane === 'evidence') return 0;
    if (lane === 'identity') return 1;
    if (lane === 'relationship' || lane === 'event' || lane === 'semantic') return 2;
    if (lane === 'temporal') return 3;
    if (lane === 'causal') return 4;
    if (lane === 'bridge') return 5;
    return 6;
}

function productTargetObstruction(target: GraphRebuildEmbeddingTarget, lane: string): ConeObstructionRecord | null {
    if (target.admissionStatus === 'deferred') {
        return productObstruction(
            `target:${target.id}:deferred`,
            'UnsupportedBridge',
            0.66,
            target,
            [target.id],
            [],
            `Deferred ${lane} target: ${target.deferReason || target.admissionReason || 'lane budget held it for review'}`,
        );
    }
    if (requiresEvidence(lane, target.kind) && target.evidenceIds.length === 0) {
        return productObstruction(`target:${target.id}:evidence`, 'EvidenceMissing', 0.72, target, [target.id], [], `No evidence anchors attached to ${target.label || target.id}.`);
    }
    return null;
}

function productEdgeObstruction(
    edge: GalaxyInputEdge,
    source: GraphRebuildEmbeddingTarget,
    target: GraphRebuildEmbeddingTarget,
    sourceLane: string,
    targetLane: string,
): ConeObstructionRecord | null {
    const legal = sourceLane === targetLane || PRODUCT_ROUTE_LEGAL_MOVES.has(`${sourceLane}>${targetLane}`);
    if (!legal) {
        return productObstruction(`edge:${edge.id}:lane`, 'LaneMismatch', 0.74, target, [edge.sourceId, edge.targetId], [edge.id], `${sourceLane} cannot stitch directly to ${targetLane}.`);
    }
    if (edge.confidence < 0.24) {
        return productObstruction(`edge:${edge.id}:evidence`, 'EvidenceMissing', 0.68, target, [edge.sourceId, edge.targetId], [edge.id], `Low-evidence traversal candidate (${Math.round(edge.confidence * 100)}%).`);
    }
    if (edge.type.includes('embedding-bridge') && edge.confidence < 0.52) {
        return productObstruction(`edge:${edge.id}:bridge`, 'UnsupportedBridge', 0.58, target, [edge.sourceId, edge.targetId], [edge.id], 'Embedding bridge needs graph evidence before promotion.');
    }
    return null;
}

function productObstruction(
    id: string,
    kind: string,
    severity: number,
    target: GraphRebuildEmbeddingTarget,
    nodeIds: string[],
    edgeIds: string[],
    explanation: string,
): ConeObstructionRecord {
    return {
        obstructionId: `obstruction:${normalizeHopfToken(id)}`,
        kind,
        severity,
        explanation,
        nodeIds,
        edgeIds,
        chartIds: target.chunkId ? [`chart:chunk:${target.chunkId}`] : target.noteId ? [`chart:note:${target.noteId}`] : [],
        evidenceRefs: target.evidenceIds || [],
        lane: productRouteLaneForTarget(target),
        geometryVersion: PRODUCT_CONE_TRAVERSAL_GEOMETRY,
    };
}

function productPathletLane(edge: GalaxyInputEdge, sourceLane: string, targetLane: string): string {
    const text = edge.type.toLowerCase();
    if (/causal|cause|effect/.test(text)) return 'causal';
    if (/temporal|before|after|timeline/.test(text)) return 'temporal';
    if (/evidence|anchor|chunk|source/.test(text)) return 'evidence';
    if (/identity|entity|alias/.test(text)) return 'identity';
    if (/bridge|backbone/.test(text)) return 'bridge';
    return targetLane !== 'semantic' ? targetLane : sourceLane;
}

function productPathletSupport(
    edge: GalaxyInputEdge,
    source: GraphRebuildEmbeddingTarget,
    target: GraphRebuildEmbeddingTarget,
    sourceLane: string,
    targetLane: string,
): number {
    const evidence = Math.min(0.18, (source.evidenceIds.length + target.evidenceIds.length) * 0.025);
    const lane = sourceLane === targetLane ? 0.08 : PRODUCT_ROUTE_LEGAL_MOVES.has(`${sourceLane}>${targetLane}`) ? 0.04 : -0.16;
    return clamp01(edge.confidence * 0.72 + evidence + lane);
}

function parentOverlapScore(source: GraphRebuildEmbeddingTarget, target: GraphRebuildEmbeddingTarget): number {
    const parents = new Set(source.parentIds || []);
    if (!parents.size) return 0;
    return Math.min(0.16, (target.parentIds || []).filter((parent) => parents.has(parent)).length * 0.08);
}

function requiresEvidence(lane: string, kind: string): boolean {
    return lane === 'relationship' || lane === 'temporal' || lane === 'causal' || /fact|event|memory/i.test(kind);
}

function buildProductConePrograms(pathlets: ConePathletRecord[], obstructions: ConeObstructionRecord[]): ConeProgramRecord[] {
    const seedIds = [...new Set(pathlets.flatMap((pathlet) => [pathlet.startId]).slice(0, 12))];
    const repairSeeds = [...new Set(obstructions.flatMap((obstruction) => obstruction.nodeIds).slice(0, 12))];
    return [
        coneProgram('product:trace-supported-routes', 'trace', seedIds, 'evidence', false),
        coneProgram('product:validate-stitches', 'validate', seedIds, 'relationship', true),
        coneProgram('product:repair-obstructions', 'repair', repairSeeds, 'bridge', true),
    ].filter((program) => program.seedIds.length > 0);
}

function coneProgram(programId: string, intent: string, seedIds: string[], lane: string, requireEvidence: boolean): ConeProgramRecord {
    return {
        programId,
        intent,
        seedIds,
        geometryVersion: PRODUCT_CONE_TRAVERSAL_GEOMETRY,
        ops: [
            { op: 'seed', ids: seedIds },
            { op: 'followField', lane, maxCost: requireEvidence ? 0.72 : 0.92, limit: 64 },
            { op: 'stitch', requiredIds: [], minCompatibility: requireEvidence ? 0.58 : 0.42, requireEvidence },
            { op: 'ground', strict: requireEvidence },
            { op: 'rerank', rankBy: ['support', 'stitchQuality', 'cost'] },
            { op: 'explain', limit: 8 },
        ],
    };
}

function productTraceForProgram(
    program: ConeProgramRecord,
    pathlets: ConePathletRecord[],
    obstructions: ConeObstructionRecord[],
    obstructionByEdge: Map<string, string[]>,
): ConeProgramTraceRecord {
    const lane = String(program.ops.find((op) => op.op === 'followField')?.lane || '');
    const selected = pathlets.filter((pathlet) => !lane || pathlet.lane === lane || program.intent === 'repair').slice(0, 64);
    const selectedObstructions = program.intent === 'repair'
        ? obstructions.slice(0, 64)
        : obstructions.filter((obstruction) => selected.some((pathlet) => pathlet.obstructionIds.includes(obstruction.obstructionId))).slice(0, 64);
    const pathEdgeIds = selected.flatMap((pathlet) => pathlet.edgeIds);
    return {
        traceId: `trace:${program.programId}`,
        programId: program.programId,
        activeIds: [...new Set(selected.flatMap((pathlet) => pathlet.nodeIds))],
        pathletIds: selected.map((pathlet) => pathlet.pathletId),
        obstructionIds: [...new Set([...selectedObstructions.map((obstruction) => obstruction.obstructionId), ...pathEdgeIds.flatMap((edgeId) => obstructionByEdge.get(edgeId) || [])])],
        pathEdgeIds,
        explanations: [
            `${selected.length} pathlets traversed`,
            `${selectedObstructions.length} obstructions surfaced`,
        ],
        geometryVersion: PRODUCT_CONE_TRAVERSAL_GEOMETRY,
    };
}

function hydrateTargetEntityKind(
    target: GraphRebuildEmbeddingTarget,
    entityKindById: Map<string, string>,
): GraphRebuildEmbeddingTarget {
    if (target.entityKind || !target.entityId) return target;
    const entityKind = entityKindById.get(target.entityId);
    return entityKind ? { ...target, entityKind } : target;
}

function buildTargetHierarchyContext(snapshot: GraphRebuildSnapshot): Map<string, TargetHierarchyContext> {
    const contexts = new Map<string, TargetHierarchyContext>();
    const targetById = new Map(snapshot.embeddingTargets.map((target) => [target.id, target]));
    for (const noteId of snapshot.noteIds || []) {
        const context = targetHierarchyBase(targetById.get(`embed:note:${noteId}`), { noteId });
        contexts.set(`embed:note:${noteId}`, context);
        contexts.set(`embed:structure-root:${noteId}:document-structure`, targetHierarchyBase(targetById.get(`embed:structure-root:${noteId}:document-structure`), context));
        contexts.set(`embed:structure-root:${noteId}:identity`, targetHierarchyBase(targetById.get(`embed:structure-root:${noteId}:identity`), context));
        contexts.set(`embed:structure-root:${noteId}:temporal`, targetHierarchyBase(targetById.get(`embed:structure-root:${noteId}:temporal`), context));
        contexts.set(`embed:structure-root:${noteId}:causal`, targetHierarchyBase(targetById.get(`embed:structure-root:${noteId}:causal`), context));
        contexts.set(`embed:structure-root:${noteId}:evidence`, targetHierarchyBase(targetById.get(`embed:structure-root:${noteId}:evidence`), context));
    }
    for (const chunk of snapshot.chunks || []) {
        const fallback = contexts.get(`embed:note:${chunk.noteId}`) || { noteId: chunk.noteId };
        contexts.set(`embed:chunk:${chunk.id}`, targetHierarchyBase(targetById.get(`embed:chunk:${chunk.id}`), { ...fallback, chunkId: chunk.id }));
    }
    const entityContexts = new Map<string, {
        confidence: number;
        context: TargetHierarchyContext;
        supportNoteIds: Set<string>;
        supportChunkIds: Set<string>;
    }>();
    for (const anchor of snapshot.entityAnchors || []) {
        const fallback = contexts.get(`embed:chunk:${anchor.chunkId}`) || contexts.get(`embed:note:${anchor.noteId}`) || { noteId: anchor.noteId };
        const context = targetHierarchyBase(targetById.get(`embed:anchor:${anchor.id}`), { ...fallback, noteId: anchor.noteId, chunkId: anchor.chunkId });
        contexts.set(`embed:anchor:${anchor.id}`, context);
        if (!anchor.entityId) continue;
        const existing = entityContexts.get(anchor.entityId);
        const supportNoteIds = existing?.supportNoteIds || new Set<string>();
        const supportChunkIds = existing?.supportChunkIds || new Set<string>();
        if (anchor.noteId) supportNoteIds.add(anchor.noteId);
        if (anchor.chunkId) supportChunkIds.add(anchor.chunkId);
        if (!existing || anchor.confidence > existing.confidence) {
            entityContexts.set(anchor.entityId, { confidence: anchor.confidence, context, supportNoteIds, supportChunkIds });
        } else {
            existing.supportNoteIds = supportNoteIds;
            existing.supportChunkIds = supportChunkIds;
        }
    }
    for (const [entityId, value] of entityContexts) {
        contexts.set(`embed:entity:${entityId}`, {
            ...value.context,
            supportNoteIds: [...value.supportNoteIds].sort(),
            supportChunkIds: [...value.supportChunkIds].sort(),
        });
    }
    for (const target of snapshot.embeddingTargets) {
        if (contexts.has(target.id)) continue;
        contexts.set(target.id, targetHierarchyBase(target, {
            noteId: target.noteId,
            chunkId: target.chunkId,
        }));
    }
    for (let pass = 0; pass < 4; pass += 1) {
        for (const target of snapshot.embeddingTargets) {
            const parentContexts = (target.parentIds || [])
                .map((parentId) => contexts.get(parentId))
                .filter((context): context is TargetHierarchyContext => !!context);
            if (!parentContexts.length) continue;
            contexts.set(target.id, mergeTargetHierarchyContext(
                targetHierarchyBase(target, contexts.get(target.id) || {}),
                parentContexts,
            ));
        }
    }
    return contexts;
}

function mergeTargetHierarchyContext(
    base: TargetHierarchyContext,
    parents: TargetHierarchyContext[],
): TargetHierarchyContext {
    const noteIds = new Set(base.supportNoteIds || []);
    const chunkIds = new Set(base.supportChunkIds || []);
    if (base.noteId) noteIds.add(base.noteId);
    if (base.chunkId) chunkIds.add(base.chunkId);
    let noteId = base.noteId;
    let chunkId = base.chunkId;
    for (const parent of parents) {
        if (!noteId && parent.noteId) noteId = parent.noteId;
        if (!chunkId && parent.chunkId) chunkId = parent.chunkId;
        if (parent.noteId) noteIds.add(parent.noteId);
        if (parent.chunkId) chunkIds.add(parent.chunkId);
        for (const id of parent.supportNoteIds || []) noteIds.add(id);
        for (const id of parent.supportChunkIds || []) chunkIds.add(id);
    }
    return {
        ...base,
        noteId,
        chunkId,
        supportNoteIds: noteIds.size ? [...noteIds].sort() : undefined,
        supportChunkIds: chunkIds.size ? [...chunkIds].sort() : undefined,
    };
}

function targetHierarchyBase(
    target: GraphRebuildEmbeddingTarget | undefined,
    fallback: TargetHierarchyContext,
): TargetHierarchyContext {
    return {
        ...fallback,
        noteId: target?.noteId || fallback.noteId,
        chunkId: target?.chunkId || fallback.chunkId,
        supportNoteIds: targetSupportNoteIds(target, fallback),
        supportChunkIds: targetSupportChunkIds(target, fallback),
        folderId: target?.folderId || fallback.folderId,
        folderLabel: target?.folderLabel || fallback.folderLabel,
        folderKind: target?.folderKind || fallback.folderKind,
        folderParentId: target?.folderParentId || fallback.folderParentId,
    };
}

function targetSupportNoteIds(
    target: GraphRebuildEmbeddingTarget | undefined,
    fallback: TargetHierarchyContext,
): string[] | undefined {
    const ids = new Set<string>(fallback.supportNoteIds || []);
    if (fallback.noteId) ids.add(fallback.noteId);
    if (target?.noteId) ids.add(target.noteId);
    for (const parentId of target?.parentIds || []) {
        const note = parentId.match(/^embed:note:(.+)$/)?.[1]
            || parentId.match(/^embed:structure-root:([^:]+):/)?.[1];
        if (note) ids.add(note);
    }
    return ids.size ? [...ids].sort() : undefined;
}

function targetSupportChunkIds(
    target: GraphRebuildEmbeddingTarget | undefined,
    fallback: TargetHierarchyContext,
): string[] | undefined {
    const ids = new Set<string>(fallback.supportChunkIds || []);
    if (fallback.chunkId) ids.add(fallback.chunkId);
    if (target?.chunkId) ids.add(target.chunkId);
    for (const parentId of target?.parentIds || []) {
        const chunk = parentId.match(/^embed:chunk:(.+)$/)?.[1];
        if (chunk) ids.add(chunk);
    }
    return ids.size ? [...ids].sort() : undefined;
}

function targetNode(
    target: GraphRebuildEmbeddingTarget,
    vector: Float32Array,
    index: number,
    total: number,
    manifold: AtlasManifoldMode,
    post?: GraphRebuildEmbeddingTargetPostProcess,
    hopfBase?: HopfBaseAssignment,
    hierarchyContext?: TargetHierarchyContext,
    graphTruth?: GraphSignalTruthRecord,
    commitment?: GraphModelV2FactBundleCommitment,
    mentionCompaction?: MentionCompactionReceipt,
    capsDocumentDirections?: Map<string, CapsVec3>,
): GalaxyRenderableNode {
    const point = manifold === 'siegel'
        ? projectSiegelVector(vector, target, index, total, hierarchyContext)
        : projectVector(vector, target.id, index, total, manifold);
    const busemannSignature = graphModelBusemannSignature(commitment);
    const style = graphTopologyStyleForEmbeddingTarget(target);
    const relationFamily = style.relationFamily || null;
    const totalMentions = mentionCompaction?.anchorCount ?? target.evidenceIds.length;
    const lorentzMetadata = manifold === 'lorentz' || post
        ? productLorentzMetadata(target, point, post, hierarchyContext, capsDocumentDirections)
        : undefined;
    const visualTrace = graphTopologyTraceForEmbeddingTarget(target);
    const capsHierarchyRole = typeof lorentzMetadata?.['capsHierarchyRole'] === 'string'
        ? lorentzMetadata['capsHierarchyRole']
        : undefined;
    const canonicalKind = displayKind(target.kind);
    return {
        id: target.id,
        label: target.label || target.id,
        kind: canonicalKind,
        totalMentions: Math.max(1, totalMentions),
        atlasX: point.x,
        atlasY: point.y,
        atlasZ: point.z,
        colorHsl: style.colorHsl,
        metadata: {
            sourceType: target.kind,
            sourceId: target.sourceId,
            sourceContract: visualTrace.sourceContract,
            vectorContract: visualTrace.vectorContract,
            visualTrace,
            visualSourceId: visualTrace.sourceId,
            visualFamily: visualTrace.family,
            packetSnapshotId: visualTrace.packetSnapshotId,
            packetScopeId: visualTrace.packetScopeId,
            entityKind: target.entityKind,
            graphColorKind: graphTopologyDisplayColorKind(style.colorKind),
            graphFamily: visualTrace.family,
            graphRelationFamily: relationFamily || undefined,
            graphMemoryStateKind: displayKind(target.kind) === 'memory-state' ? style.colorKind : undefined,
            atlasKind: canonicalKind,
            atlasFamily: target.atlasFamily,
            atlasStructuralRole: target.structuralRole,
            atlasDocumentUnitKind: target.documentUnitKind,
            atlasStateContextKind: target.stateContextKind,
            atlasObjectId: visualTrace.packetObjectId,
            atlasTargetId: visualTrace.packetTargetId || target.id,
            styleKey: target.styleKey,
            capsHierarchyRole,
            signalLane: target.lane,
            signalStructuralRole: target.structuralRole,
            signalAdmissionTier: target.admissionTier,
            signalAdmissionStatus: target.admissionStatus,
            signalAdmissionReason: target.admissionReason,
            signalParentIds: target.parentIds,
            graphTruth,
            graphTruthStatus: graphTruth?.status,
            graphTruthReason: graphTruth?.reason,
            graphTruthKind: graphTruth?.kind,
            mentionCompaction,
            compactedMentionCount: mentionCompaction?.anchorCount,
            compactedAnchorIds: mentionCompaction?.anchorIds,
            compactedChunkIds: mentionCompaction?.chunkIds,
            commitmentTopPrototypeId: commitment?.topPrototypeId,
            commitmentTopLabel: commitment?.topLabel,
            commitmentConfidence: commitment?.classificationConfidence,
            promotionReady: commitment?.promotionReady,
            busemannSignature,
            hybridInterior: busemannSignature ? {
                mode: 'busemannCommitment',
                signature: busemannSignature,
            } : undefined,
            targetConfidence: targetConfidence(target),
            noteId: target.noteId || hierarchyContext?.noteId,
            chunkId: target.chunkId || hierarchyContext?.chunkId,
            folderId: target.folderId || hierarchyContext?.folderId,
            folderLabel: target.folderLabel || hierarchyContext?.folderLabel,
            folderKind: target.folderKind || hierarchyContext?.folderKind,
            folderParentId: target.folderParentId || hierarchyContext?.folderParentId,
            sourceEntityId: target.entityId,
            embeddingClusterId: post?.clusterId,
            embeddingClusterRole: post?.clusterRole,
            embeddingMedoidTargetId: post?.medoidTargetId,
            embeddingOutlierScore: post?.outlierScore,
            embeddingHubScore: post?.hubScore,
            productRegionId: post?.productTopologyRegion.id,
            productRegionRole: post?.productTopologyRegion.role,
            productLaneKind: post?.productTopologyRegion.laneKind,
            productRegionConfidence: post?.productTopologyRegion.confidence,
            product: post ? {
                role: 'embeddingTarget',
                clusterId: post.clusterId,
                clusterRole: post.clusterRole,
                medoidTargetId: post.medoidTargetId,
                region: post.productTopologyRegion,
                dominantLane: post.productLaneFeatures.dominantLane,
                lanes: post.productLaneFeatures,
            } : undefined,
            siegel: manifold === 'siegel' ? graphRebuildSiegelMetadata(target, post, hierarchyContext) : undefined,
            lorentz: lorentzMetadata,
            hopf: manifold === 'hopf'
                ? graphRebuildHopfMetadata(target, post, manifold, hopfBase)
                : post ? graphRebuildHopfMetadata(target, post, manifold) : undefined,
            graphKind: graphTopologyDisplayColorKind(style.colorKind),
            graphRebuildEmbeddingTarget: true,
            manifold,
            preview: target.text || target.label,
        },
    };
}

function buildBundleCommitmentIndex(snapshot: GraphRebuildSnapshot): Map<string, GraphModelV2FactBundleCommitment> {
    const commitments = new Map<string, GraphModelV2FactBundleCommitment>();
    for (const bundle of snapshot.graphModelV2?.bundles || []) {
        if (!bundle.commitment) continue;
        commitments.set(bundle.id, bundle.commitment);
        commitments.set(bundle.sourceRecordId, bundle.commitment);
        commitments.set(`embed:graph-fact:${bundle.sourceRecordId}`, bundle.commitment);
    }
    return commitments;
}

function graphModelBusemannSignature(commitment?: GraphModelV2FactBundleCommitment): Record<string, unknown> | undefined {
    if (!commitment) return undefined;
    return {
        family: commitment.family,
        topPrototypeId: commitment.topPrototypeId,
        topScore: commitment.topScore,
        topProbability: commitment.topProbability,
        secondPrototypeId: commitment.secondPrototypeId,
        secondScore: commitment.secondScore,
        secondProbability: commitment.secondProbability,
        margin: commitment.margin,
        entropy: commitment.entropy,
        ambiguityScore: commitment.ambiguityScore,
        classificationConfidence: commitment.classificationConfidence,
        promotionReady: commitment.promotionReady,
        radialStrength: commitment.radialStrength,
        topKScores: commitment.topKScores,
    };
}

function targetConfidence(target: GraphRebuildEmbeddingTarget): number {
    const match = target.text.match(/\bconfidence:([0-9.]+)/i);
    if (match) return clamp01(Number(match[1]));
    if (target.kind === 'entity') {
        const mentions = target.text.match(/\bmentions:(\d+)/i);
        const mentionCount = mentions ? Number(mentions[1]) : target.evidenceIds.length;
        return clamp01(0.68 + Math.min(0.24, Math.log1p(Math.max(0, mentionCount)) * 0.08));
    }
    if (target.kind === 'anchor') return 0.86;
    if (target.kind === 'chunk') return 0.78;
    return 0.62;
}

type SiegelBandId =
    | 'document'
    | 'documentRoot'
    | 'chunk'
    | 'event'
    | 'location'
    | 'character'
    | 'entityOther'
    | 'stateContext'
    | 'relationship'
    | 'evidence'
    | 'semantic';

const SIEGEL_BAND_ORDER: Record<SiegelBandId, number> = {
    document: 0,
    documentRoot: 1,
    chunk: 2,
    event: 3,
    location: 4,
    character: 5,
    entityOther: 6,
    stateContext: 7,
    relationship: 8,
    evidence: 9,
    semantic: 10,
};

function graphRebuildSiegelMetadata(
    target: GraphRebuildEmbeddingTarget,
    post?: GraphRebuildEmbeddingTargetPostProcess,
    hierarchyContext?: TargetHierarchyContext,
): Record<string, unknown> {
    const lane = siegelBandForTarget(target, hierarchyContext);
    const confidence = targetConfidence(target);
    const depth = siegelDepth(target, hierarchyContext);
    return {
        role: target.structuralRole || target.admissionStatus || 'signal',
        lane,
        depth,
        confidence,
        ambiguity: post?.outlierScore ?? (target.admissionStatus === 'deferred' ? 0.72 : 0),
        phase: unitHash(`${target.id}:siegel-phase`),
        matrixCells: siegelMatrixCells(target, lane, depth),
        parentIds: target.parentIds || [],
        directed: true,
    };
}

function graphRebuildHopfMetadata(
    target: GraphRebuildEmbeddingTarget,
    post: GraphRebuildEmbeddingTargetPostProcess | undefined,
    manifold: AtlasManifoldMode,
    assignment?: HopfBaseAssignment,
): Record<string, unknown> {
    const fiberKind = assignment?.fiberKind || (post ? productFiberKind(post.clusterRole, post.productTopologyRegion.laneKind) : hopfResonanceKind(target));
    if (manifold !== 'hopf') {
        return {
            role: 'anchor',
            baseId: target.id,
            fiberKind,
            phase: post?.productLaneFeatures.fiberPhase ?? unitHash(`${target.id}:hopf-phase`),
        };
    }

    if (!assignment || assignment.role === 'loose' || !assignment.baseId) {
        return {
            role: 'loose',
            fiberKind,
            phase: assignment?.phase ?? unitHash(`${target.id}:hopf-loose-phase`),
            resonanceSource: 'point-formed',
            resonanceAdmitted: false,
            support: assignment?.support ?? 0,
            coherence: assignment?.coherence ?? 0,
            frustration: assignment?.frustration ?? 1,
            neighborCount: assignment?.neighborCount ?? 0,
        };
    }

    const role = assignment.role === 'anchor' || target.id === assignment.anchorTargetId ? 'anchor' : 'fiber';
    return {
        role,
        baseId: assignment.baseId,
        fiberKind,
        phase: assignment.phase,
        clusterId: post?.clusterId,
        medoidTargetId: post?.medoidTargetId,
        regionId: post?.productTopologyRegion.id,
        laneKind: post?.productTopologyRegion.laneKind,
        rootBaseId: assignment.rootBaseId,
        splitKey: assignment.splitKey,
        cellId: assignment.cellId,
        secondaryCellIds: assignment.secondaryCellIds,
        assignmentScore: assignment.assignmentScore,
        residualScore: assignment.residualScore,
        salience: assignment.salience,
        strandKey: assignment.strandKey,
        strandIndex: assignment.strandIndex,
        strandCount: assignment.strandCount,
        phaseSpread: assignment.phaseSpread,
        direction: assignment.direction,
        tangent: assignment.tangent,
        receipt: assignment.receipt,
        resonanceSource: assignment.resonanceSource || 'point-formed',
        resonanceAdmitted: true,
        noTopologyMutation: assignment.noTopologyMutation,
        support: assignment.support,
        coherence: assignment.coherence,
        frustration: assignment.frustration,
        neighborCount: assignment.neighborCount,
    };
}

function normalizeSiegelLane(lane: string | undefined, kind: string, entityKind?: string): SiegelBandId {
    const raw = [lane, kind, entityKind].map(compactSiegelToken).join(' ');
    if (hasSiegelTerm(raw, ['documentroot', 'structureroot', 'root'])) return 'documentRoot';
    if (hasSiegelTerm(raw, ['document', 'documentatom', 'note', 'doc'])) return 'document';
    if (hasSiegelTerm(raw, ['chunk', 'chunkatom', 'leaf', 'chapter', 'scene', 'beat', 'act', 'arc', 'narrative', 'spine', 'structure'])) {
        return 'chunk';
    }
    if (hasSiegelTerm(raw, ['event', 'eventatom', 'timeline'])) return 'event';
    if (hasSiegelTerm(raw, SIEGEL_STATE_CONTEXT_TERMS)) return 'stateContext';
    if (hasSiegelTerm(raw, ['location', 'place', 'site'])) return 'location';
    if (hasSiegelTerm(raw, ['character', 'npc', 'creature'])) return 'character';
    if (hasSiegelTerm(raw, ['entity', 'identity', 'network', 'item', 'concept', 'object', 'group'])) return 'entityOther';
    if (hasSiegelTerm(raw, [
        'relationship',
        'relationshipfact',
        'graphfact',
        'temporalfact',
        'causalfact',
        'fact',
        'factvertex',
        'relation',
        'cooccurrence',
        'communication',
        'authority',
        'approval',
        'family',
        'intimacy',
        'transfer',
        'temporal',
        'causal',
    ])) {
        return 'relationship';
    }
    if (hasSiegelTerm(raw, ['evidence', 'evidenceanchor', 'anchor', 'mention', 'source', 'provenance'])) return 'evidence';
    return 'semantic';
}

function siegelDepth(target: GraphRebuildEmbeddingTarget, hierarchyContext?: TargetHierarchyContext): number {
    return SIEGEL_BAND_ORDER[siegelBandForTarget(target, hierarchyContext)];
}

function siegelBandForTarget(
    target: GraphRebuildEmbeddingTarget,
    hierarchyContext?: TargetHierarchyContext,
): SiegelBandId {
    const kind = compactSiegelToken(target.kind);
    const entityKind = compactSiegelToken(target.entityKind);
    const lane = normalizeSiegelLane(target.lane, target.kind, target.entityKind);
    if (['note', 'doc', 'document', 'documentatom'].includes(kind)) return 'document';
    if (['structureroot', 'documentroot', 'root'].includes(kind)) return 'documentRoot';
    if (['chunk', 'chunkatom', 'leaf'].includes(kind)) return 'chunk';
    if (['anchor', 'evidenceanchor', 'mention', 'evidence'].includes(kind)) return 'evidence';
    if (['chapter', 'scene', 'beat', 'act', 'arc', 'narrative'].includes(entityKind)) return 'chunk';
    if (['event', 'eventatom', 'timeline'].includes(kind) || ['event', 'timeline'].includes(entityKind)) return 'event';
    if (isSiegelStateContextKind(kind) || isSiegelStateContextKind(target.label) || isSiegelStateContextKind(target.text)) {
        return 'stateContext';
    }
    if (['location', 'place', 'site'].includes(entityKind)) return 'location';
    if (['character', 'npc', 'creature'].includes(entityKind)) return 'character';
    if (kind === 'entity' || ['identity', 'network', 'item', 'concept', 'object', 'group'].includes(entityKind)) return 'entityOther';
    if ([
        'graphfact',
        'relationshipfact',
        'temporalfact',
        'causalfact',
        'memorystate',
        'fact',
        'factvertex',
        'relation',
        'relationship',
    ].includes(kind) || hierarchyContext?.chunkId) {
        return 'relationship';
    }
    if (target.structuralRole === 'root') return 'documentRoot';
    if (target.structuralRole === 'spine') return 'chunk';
    return lane;
}

function siegelMatrixCells(target: GraphRebuildEmbeddingTarget, lane: string, depth: number): number[] {
    const source = `${target.id}:${lane}:${depth}:${target.parentIds?.join('|') || ''}`;
    return Array.from({ length: 6 }, (_, index) => unitHash(`${source}:${index}`));
}

function compactSiegelToken(value: unknown): string {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

const SIEGEL_STATE_CONTEXT_TERMS = [
    'memorystate',
    'memory',
    'state',
    'decisionstate',
    'rankstatus',
    'rankorstatus',
    'servicecontext',
    'servicerank',
    'affiliationcontext',
    'affiliatecontext',
    'affiliantcontext',
    'familycontext',
];

function isSiegelStateContextKind(value: unknown): boolean {
    const token = compactSiegelToken(value);
    return SIEGEL_STATE_CONTEXT_TERMS.some((term) => token === term || (term.length > 3 && token.includes(term)));
}

function hasSiegelTerm(raw: string, terms: string[]): boolean {
    return raw.split(' ').some((term) => terms.some((needle) => term === needle || (needle.length > 3 && term.includes(needle))));
}

type HopfResonanceEntry = {
    target: GraphRebuildEmbeddingTarget;
    post?: GraphRebuildEmbeddingTargetPostProcess;
    vector: Float32Array;
    norm: number;
    kind: string;
};

type HopfResonanceEdge = {
    other: number;
    weight: number;
};

function buildHopfAtlasAssignmentPlan(
    snapshot: GraphRebuildSnapshot,
    targets: GraphRebuildEmbeddingTarget[],
    vectors: Float32Array[],
    postByTarget: Map<string, GraphRebuildEmbeddingTargetPostProcess>,
): Map<string, HopfBaseAssignment> {
    const plan = buildHopfSnapshotAssignmentPlan(snapshot.hopfResonanceSpace, targets);
    if (plan.size === targets.length) return plan;

    const fallback = buildHopfResonancePlan(targets, vectors, postByTarget);
    if (!plan.size) return fallback;
    for (const target of targets) {
        if (!plan.has(target.id)) {
            const assignment = fallback.get(target.id);
            if (assignment) plan.set(target.id, assignment);
        }
    }
    return plan;
}

function buildHopfSnapshotAssignmentPlan(
    space: HopfResonanceSpace | undefined,
    targets: GraphRebuildEmbeddingTarget[],
): Map<string, HopfBaseAssignment> {
    const plan = new Map<string, HopfBaseAssignment>();
    if (!space?.assignments?.length || !targets.length) return plan;

    const visibleTargetIds = new Set(targets.map((target) => target.id));
    const anchorByCell = new Map<string, string>();
    for (const cell of space.cells || []) {
        const anchorId = cell.anchorTargetIds.find((targetId) => visibleTargetIds.has(targetId)) || cell.anchorTargetIds[0];
        if (anchorId) anchorByCell.set(cell.id, anchorId);
    }

    const fiberByTargetId = new Map<string, HopfResonanceFiber>();
    for (const fiber of space.fibers || []) {
        for (const targetId of fiber.targetIds) {
            if (!fiberByTargetId.has(targetId)) fiberByTargetId.set(targetId, fiber);
        }
    }

    for (const assignment of space.assignments) {
        if (!visibleTargetIds.has(assignment.targetId)) continue;
        plan.set(assignment.targetId, hopfSnapshotAssignment(assignment, anchorByCell, fiberByTargetId));
    }
    return plan;
}

function hopfSnapshotAssignment(
    assignment: HopfResonanceAssignment,
    anchorByCell: Map<string, string>,
    fiberByTargetId: Map<string, HopfResonanceFiber>,
): HopfBaseAssignment {
    const fiber = fiberByTargetId.get(assignment.targetId);
    const anchorTargetId = anchorByCell.get(assignment.baseCellId) || fiber?.anchorTargetId || assignment.targetId;
    const structuralAnchor = assignment.role === 'document-chart' || assignment.role === 'structure-root';
    const role: HopfBaseAssignment['role'] = structuralAnchor || assignment.targetId === anchorTargetId ? 'anchor' : 'fiber';
    const residual = clamp01(assignment.residualScore);
    return {
        role,
        rootBaseId: assignment.baseCellId,
        baseId: assignment.baseCellId,
        anchorTargetId,
        splitKey: `${assignment.baseCellId}:${assignment.fiberKind}`,
        fiberKind: assignment.fiberKind,
        phase: clamp01(assignment.phase),
        support: clamp01(assignment.assignmentScore),
        coherence: fiber?.coherence ?? clamp01(1 - residual),
        frustration: fiber?.frustration ?? residual,
        neighborCount: assignment.secondaryCellIds.length,
        cellId: assignment.baseCellId,
        secondaryCellIds: assignment.secondaryCellIds.slice(0, 6),
        assignmentScore: clamp01(assignment.assignmentScore),
        residualScore: residual,
        salience: clamp01(assignment.salience),
        strandKey: assignment.strandKey,
        strandIndex: assignment.strandIndex,
        strandCount: assignment.strandCount,
        phaseSpread: assignment.phaseSpread,
        direction: assignment.direction,
        tangent: assignment.tangent,
        receipt: assignment.receipt,
        resonanceSource: 'snapshot-hopf-resonance-space',
        noTopologyMutation: true,
    };
}

function buildHopfResonancePlan(
    targets: GraphRebuildEmbeddingTarget[],
    vectors: Float32Array[],
    postByTarget: Map<string, GraphRebuildEmbeddingTargetPostProcess>,
): Map<string, HopfBaseAssignment> {
    const plan = new Map<string, HopfBaseAssignment>();
    const count = targets.length;
    if (!count) return plan;

    const dims = Math.min(HOPF_RESONANCE_DIMS, vectors[0]?.length || 0);
    const entries: HopfResonanceEntry[] = targets.map((target, index) => {
        const post = postByTarget.get(target.id);
        return {
            target,
            post,
            vector: vectors[index],
            norm: vectorNorm(vectors[index], dims),
            kind: hopfResonanceKind(target, post),
        };
    });
    const neighbors: HopfResonanceEdge[][] = Array.from({ length: count }, () => []);

    for (let left = 0; left < count; left++) {
        for (let right = left + 1; right < count; right++) {
            const semantic = cosineLimited(entries[left], entries[right], dims);
            const support = hopfPairSupport(entries[left], entries[right]);
            let weight = clamp01(((semantic + 1) * 0.5) * 0.72 + support);
            if (!hopfCrossKindCompatible(entries[left], entries[right], semantic)) {
                weight = Math.min(weight, HOPF_RESONANCE_THRESHOLD - 0.02);
            }
            if (weight >= HOPF_RESONANCE_EDGE_FLOOR) {
                pushHopfNeighbor(neighbors[left], { other: right, weight });
                pushHopfNeighbor(neighbors[right], { other: left, weight });
            }
        }
    }

    const assigned = new Set<number>();
    const anchors = Array.from({ length: count }, (_, index) => index)
        .sort((left, right) =>
            hopfAnchorScore(entries[right], neighbors[right]) - hopfAnchorScore(entries[left], neighbors[left])
            || entries[left].target.id.localeCompare(entries[right].target.id),
        );
    for (const anchorIndex of anchors) {
        if (assigned.has(anchorIndex)) continue;
        const memberIndexes = hopfLocalFiberMembers(anchorIndex, neighbors, assigned);
        if (memberIndexes.length < 2) continue;
        applyHopfComponentPlan(entries, neighbors, memberIndexes, dims, plan);
        const admitted = memberIndexes.filter((index) => {
            const assignment = plan.get(entries[index].target.id);
            return assignment?.role === 'anchor' || assignment?.role === 'fiber';
        });
        if (admitted.length < 2) continue;
        for (const index of admitted) assigned.add(index);
    }

    for (let index = 0; index < count; index++) {
        if (!plan.has(targets[index].id)) {
            plan.set(targets[index].id, looseHopfAssignment(entries[index], neighbors[index]));
        }
    }

    return plan;
}

function hopfAnchorScore(entry: HopfResonanceEntry, neighbors: HopfResonanceEdge[]): number {
    const support = neighbors.length ? neighbors.reduce((sum, edge) => sum + edge.weight, 0) / neighbors.length : 0;
    const structuralPenalty = isHopfStructuralOnly(entry.target) ? -0.18 : 0;
    return support * 10 + targetConfidence(entry.target) + Math.min(0.6, neighbors.length * 0.06) + structuralPenalty;
}

function hopfLocalFiberMembers(anchorIndex: number, neighbors: HopfResonanceEdge[][], assigned: Set<number>): number[] {
    const members = [anchorIndex];
    for (const edge of neighbors[anchorIndex]) {
        if (assigned.has(edge.other)) continue;
        if (edge.weight < HOPF_RESONANCE_THRESHOLD) continue;
        members.push(edge.other);
        if (members.length >= HOPF_RESONANCE_FIBER_MEMBER_LIMIT) break;
    }
    return members;
}

function applyHopfComponentPlan(
    entries: HopfResonanceEntry[],
    neighbors: HopfResonanceEdge[][],
    memberIndexes: number[],
    dims: number,
    plan: Map<string, HopfBaseAssignment>,
): void {
    if (memberIndexes.length < 2) {
        const index = memberIndexes[0];
        if (index !== undefined) plan.set(entries[index].target.id, looseHopfAssignment(entries[index], neighbors[index]));
        return;
    }

    const support = componentSupport(memberIndexes, neighbors);
    if (support < HOPF_RESONANCE_THRESHOLD || memberIndexes.every((index) => isHopfStructuralOnly(entries[index].target))) {
        for (const index of memberIndexes) plan.set(entries[index].target.id, looseHopfAssignment(entries[index], neighbors[index]));
        return;
    }

    const center = normalizedMean(entries, memberIndexes, dims);
    const e1 = dominantResidualAxis(entries, memberIndexes, center, dims);
    const e2 = secondaryResidualAxis(entries, memberIndexes, center, e1, dims);
    const anchorIndex = hopfResonanceAnchor(entries, neighbors, memberIndexes);
    const anchor = entries[anchorIndex];
    const baseId = `hopf:resonance:${normalizeHopfToken(anchor.target.id)}`;
    const fiberKind = dominantHopfFiberKind(entries, memberIndexes);
    const splitKey = `point-formed:${fiberKind}`;
    const phases = new Map<number, number>();

    let sumCos = 0;
    let sumSin = 0;
    for (const index of memberIndexes) {
        const phase = tangentPhase(entries[index], center, e1, e2, dims);
        phases.set(index, phase);
        sumCos += Math.cos(phase * Math.PI * 2);
        sumSin += Math.sin(phase * Math.PI * 2);
    }
    const circularVariance = 1 - Math.min(1, Math.hypot(sumCos, sumSin) / memberIndexes.length);
    const coherence = clamp01(support * 0.72 + (1 - circularVariance) * 0.28);
    const frustration = clamp01(1 - coherence);

    for (const index of memberIndexes) {
        const localSupport = localHopfSupport(neighbors[index], memberIndexes);
        if (isHopfStructuralOnly(entries[index].target) && localSupport < HOPF_RESONANCE_THRESHOLD + 0.08) {
            plan.set(entries[index].target.id, looseHopfAssignment(entries[index], neighbors[index]));
            continue;
        }
        plan.set(entries[index].target.id, {
            role: index === anchorIndex ? 'anchor' : 'fiber',
            rootBaseId: baseId,
            baseId,
            anchorTargetId: anchor.target.id,
            splitKey,
            fiberKind,
            phase: index === anchorIndex ? 0 : phases.get(index) ?? unitHash(`${entries[index].target.id}:hopf-phase`),
            support: localSupport,
            coherence,
            frustration,
            neighborCount: neighbors[index].length,
        });
    }
}

function looseHopfAssignment(entry: HopfResonanceEntry, neighbors: HopfResonanceEdge[]): HopfBaseAssignment {
    const support = neighbors.length ? neighbors.reduce((sum, edge) => sum + edge.weight, 0) / neighbors.length : 0;
    return {
        role: 'loose',
        fiberKind: entry.kind,
        phase: unitHash(`${entry.target.id}:hopf-loose`),
        support: clamp01(support),
        coherence: 0,
        frustration: 1,
        neighborCount: neighbors.length,
    };
}

function pushHopfNeighbor(bucket: HopfResonanceEdge[], edge: HopfResonanceEdge): void {
    bucket.push(edge);
    bucket.sort((left, right) => right.weight - left.weight || left.other - right.other);
    if (bucket.length > HOPF_RESONANCE_NEIGHBORS) bucket.length = HOPF_RESONANCE_NEIGHBORS;
}

function vectorNorm(vector: Float32Array, dims: number): number {
    let sum = 0;
    for (let index = 0; index < dims; index++) sum += vector[index] * vector[index];
    return Math.sqrt(sum);
}

function cosineLimited(left: HopfResonanceEntry, right: HopfResonanceEntry, dims: number): number {
    const denom = left.norm * right.norm;
    if (denom <= 0.000001) return 0;
    let dot = 0;
    for (let index = 0; index < dims; index++) dot += left.vector[index] * right.vector[index];
    return clampRange(dot / denom, -1, 1);
}

function hopfPairSupport(left: HopfResonanceEntry, right: HopfResonanceEntry): number {
    let support = 0;
    if (left.kind === right.kind) support += 0.1;
    if (left.target.entityId && left.target.entityId === right.target.entityId) support += 0.24;
    if (left.target.chunkId && left.target.chunkId === right.target.chunkId) support += 0.12;
    if (left.target.noteId && left.target.noteId === right.target.noteId) support += 0.05;
    if (left.target.lane && left.target.lane === right.target.lane) support += 0.06;
    if (left.post?.clusterId && left.post.clusterId === right.post?.clusterId) support += 0.1;
    if (left.post?.productTopologyRegion.laneKind && left.post.productTopologyRegion.laneKind === right.post?.productTopologyRegion.laneKind) support += 0.05;
    if (parentOverlap(left.target, right.target)) support += 0.08;
    return Math.min(0.34, support);
}

function hopfCrossKindCompatible(left: HopfResonanceEntry, right: HopfResonanceEntry, semantic: number): boolean {
    if (left.kind === right.kind) return true;
    if (left.target.entityId && left.target.entityId === right.target.entityId) return true;
    if (left.target.chunkId && left.target.chunkId === right.target.chunkId) return true;
    if (parentOverlap(left.target, right.target)) return true;
    return semantic > 0.82;
}

function parentOverlap(left: GraphRebuildEmbeddingTarget, right: GraphRebuildEmbeddingTarget): boolean {
    const parents = new Set(left.parentIds || []);
    return Boolean(parents.size && (right.parentIds || []).some((parent) => parents.has(parent)));
}

function componentSupport(memberIndexes: number[], neighbors: HopfResonanceEdge[][]): number {
    let sum = 0;
    let count = 0;
    const members = new Set(memberIndexes);
    for (const index of memberIndexes) {
        for (const edge of neighbors[index]) {
            if (!members.has(edge.other)) continue;
            sum += edge.weight;
            count += 1;
        }
    }
    return count ? sum / count : 0;
}

function localHopfSupport(neighbors: HopfResonanceEdge[], memberIndexes: number[]): number {
    const members = new Set(memberIndexes);
    let sum = 0;
    let count = 0;
    for (const edge of neighbors) {
        if (!members.has(edge.other)) continue;
        sum += edge.weight;
        count += 1;
    }
    return count ? sum / count : 0;
}

function normalizedMean(entries: HopfResonanceEntry[], memberIndexes: number[], dims: number): Float32Array {
    const mean = new Float32Array(dims);
    for (const index of memberIndexes) {
        const entry = entries[index];
        const invNorm = entry.norm > 0.000001 ? 1 / entry.norm : 0;
        for (let dim = 0; dim < dims; dim++) mean[dim] += entry.vector[dim] * invNorm;
    }
    normalizeMutable(mean);
    return mean;
}

function dominantResidualAxis(entries: HopfResonanceEntry[], memberIndexes: number[], center: Float32Array, dims: number): Float32Array {
    let bestIndex = memberIndexes[0];
    let bestNorm = -1;
    for (const index of memberIndexes) {
        const norm = residualNorm(entries[index], center, dims);
        if (norm > bestNorm) {
            bestNorm = norm;
            bestIndex = index;
        }
    }
    return residualAxis(entries[bestIndex], center, dims);
}

function secondaryResidualAxis(entries: HopfResonanceEntry[], memberIndexes: number[], center: Float32Array, e1: Float32Array, dims: number): Float32Array {
    let best: Float32Array | null = null;
    let bestNorm = -1;
    for (const index of memberIndexes) {
        const residual = residualAxis(entries[index], center, dims);
        const dot = dotArray(residual, e1);
        for (let dim = 0; dim < dims; dim++) residual[dim] -= e1[dim] * dot;
        const norm = normalizeMutable(residual);
        if (norm > bestNorm) {
            bestNorm = norm;
            best = residual;
        }
    }
    return bestNorm > 0.000001 && best ? best : fallbackOrthogonalAxis(e1);
}

function residualNorm(entry: HopfResonanceEntry, center: Float32Array, dims: number): number {
    const invNorm = entry.norm > 0.000001 ? 1 / entry.norm : 0;
    let dot = 0;
    for (let dim = 0; dim < dims; dim++) dot += entry.vector[dim] * invNorm * center[dim];
    let sum = 0;
    for (let dim = 0; dim < dims; dim++) {
        const value = entry.vector[dim] * invNorm - center[dim] * dot;
        sum += value * value;
    }
    return Math.sqrt(sum);
}

function residualAxis(entry: HopfResonanceEntry, center: Float32Array, dims: number): Float32Array {
    const out = new Float32Array(dims);
    const invNorm = entry.norm > 0.000001 ? 1 / entry.norm : 0;
    let dot = 0;
    for (let dim = 0; dim < dims; dim++) dot += entry.vector[dim] * invNorm * center[dim];
    for (let dim = 0; dim < dims; dim++) out[dim] = entry.vector[dim] * invNorm - center[dim] * dot;
    normalizeMutable(out);
    return out;
}

function tangentPhase(entry: HopfResonanceEntry, center: Float32Array, e1: Float32Array, e2: Float32Array, dims: number): number {
    const residual = residualAxis(entry, center, dims);
    const angle = Math.atan2(dotArray(residual, e2), dotArray(residual, e1));
    return unitPhase(angle / (Math.PI * 2));
}

function hopfResonanceAnchor(entries: HopfResonanceEntry[], neighbors: HopfResonanceEdge[][], memberIndexes: number[]): number {
    return [...memberIndexes].sort((left, right) =>
        localHopfSupport(neighbors[right], memberIndexes) - localHopfSupport(neighbors[left], memberIndexes)
        || targetConfidence(entries[right].target) - targetConfidence(entries[left].target)
        || entries[left].target.id.localeCompare(entries[right].target.id),
    )[0];
}

function dominantHopfFiberKind(entries: HopfResonanceEntry[], memberIndexes: number[]): string {
    const counts = new Map<string, number>();
    for (const index of memberIndexes) counts.set(entries[index].kind, (counts.get(entries[index].kind) || 0) + 1);
    return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))[0]?.[0] || 'resonance';
}

function hopfResonanceKind(target: GraphRebuildEmbeddingTarget, post?: GraphRebuildEmbeddingTargetPostProcess): string {
    const kind = displayKind(target.kind);
    if (kind === 'graph-fact') return relationFamilyFromText(target.label, target.text, target.sourceId) || 'relationship';
    if (target.kind === 'entity') return normalizeHopfToken(target.entityKind || 'identity');
    if (target.kind === 'chunk' || kind === 'note' || kind === 'structure-root') return 'document-echo';
    if (target.kind === 'event') return 'event';
    if (kind === 'temporal-fact') return 'temporal';
    if (kind === 'causal-fact') return 'causal';
    if (kind === 'memory-state') return 'memory-state';
    return normalizeHopfToken(post?.productTopologyRegion.laneKind || post?.productLaneFeatures.dominantLane || kind || 'resonance');
}

function isHopfStructuralOnly(target: GraphRebuildEmbeddingTarget): boolean {
    const kind = displayKind(target.kind);
    return kind === 'note' || kind === 'structure-root' || ((kind === 'chunk' || target.lane === 'chunk_spine') && target.evidenceIds.length === 0);
}

function normalizeMutable(vector: Float32Array): number {
    const norm = Math.sqrt(dotArray(vector, vector));
    if (norm <= 0.000001) return 0;
    for (let index = 0; index < vector.length; index++) vector[index] /= norm;
    return norm;
}

function dotArray(left: Float32Array, right: Float32Array): number {
    let sum = 0;
    for (let index = 0; index < left.length; index++) sum += left[index] * right[index];
    return sum;
}

function fallbackOrthogonalAxis(axis: Float32Array): Float32Array {
    const fallback = new Float32Array(axis.length);
    let smallest = 0;
    for (let index = 1; index < axis.length; index++) {
        if (Math.abs(axis[index]) < Math.abs(axis[smallest])) smallest = index;
    }
    fallback[smallest] = 1;
    const dot = dotArray(fallback, axis);
    for (let index = 0; index < fallback.length; index++) fallback[index] -= axis[index] * dot;
    normalizeMutable(fallback);
    return fallback;
}

function productLorentzMetadata(
    target: GraphRebuildEmbeddingTarget,
    point: { x: number; y: number; z: number },
    post: GraphRebuildEmbeddingTargetPostProcess | undefined,
    hierarchyContext?: TargetHierarchyContext,
    capsDocumentDirections?: Map<string, CapsVec3>,
): Record<string, unknown> {
    const lane = post?.productLaneFeatures ?? fallbackProductLaneFeatures(target);
    const region = post?.productTopologyRegion ?? fallbackProductTopologyRegion(target, lane);
    const radius = Math.max(0.001, Math.hypot(point.x, point.y, point.z));
    const depth = Math.max(0, Math.min(1, 1 - lane.semanticDepth));
    const scale = 0.22 + depth * 0.66;
    const clusterRole = post?.clusterRole ?? fallbackProductClusterRole(target);
    const treeKind = productFiberKind(clusterRole, region.laneKind);
    const parentNodeId = post?.medoidTargetId && post.medoidTargetId !== target.id ? post.medoidTargetId : null;
    const supportNoteIds = capsSupportNoteIds(target, hierarchyContext);
    const supportChunkIds = capsSupportChunkIds(target, hierarchyContext);
    const hierarchy = capsHierarchyPath(target, hierarchyContext, supportNoteIds, supportChunkIds, parentNodeId);
    const capId = hierarchy.capId;
    const parentId = hierarchy.parentNodeId;
    const parentCapIds = hierarchy.parentCapIds;
    const parentCapId = parentCapIds[0] || null;
    const level = hierarchy.band.rank;
    const specificity = productHierarchySpecificity(target, post);
    const ambiguity = productHierarchyAmbiguity(post);
    const capDirection = capsDirectionForTarget(target, point, hierarchyContext, supportNoteIds, supportChunkIds, capsDocumentDirections);
    return {
        geometry: 'hierarchy_caps_v1',
        klein: [
            (point.x / radius) * scale,
            (point.y / radius) * scale,
            (point.z / radius) * scale,
            lane.fiberPhase,
        ],
        capId,
        parentCapId,
        parentCapIds,
        containmentPath: capsContainmentPath(capId, parentCapIds),
        capDirection: [capDirection.x, capDirection.y, capDirection.z],
        capPhase: lane.fiberPhase,
        shellRadius: hierarchy.band.radius,
        capsHierarchyRole: hierarchy.role,
        hierarchyRole: hierarchy.role,
        hierarchyRank: hierarchy.band.rank,
        parentNodeId: parentId,
        signalLane: target.lane,
        structuralRole: target.structuralRole,
        supportNoteIds,
        supportChunkIds,
        specificity,
        ambiguity,
        level,
        primaryTreeKind: treeKind,
        w: lane.clusterRadius,
        regionId: region.id,
        regionRole: region.role,
        dominantLane: region.laneKind,
        memberships: [{
            treeId: capId,
            treeKind,
            parentNodeId: parentId,
            parentCapId,
            level,
            pathKey: `${parentCapId || 'root'}/${capId}/${target.id}`,
        }, {
            treeId: `product-lane:${region.laneKind}`,
            treeKind: region.laneKind,
            parentNodeId: parentId,
            parentCapId,
            level,
            pathKey: `product-lane:${region.laneKind}/${post?.clusterId || region.clusterId}/${target.id}`,
        }],
    };
}

function fallbackProductLaneFeatures(target: GraphRebuildEmbeddingTarget): GraphRebuildProductLaneFeatures {
    const dominantLane = fallbackProductLaneKind(target);
    const laneWeights: Record<GraphRebuildProductLaneKind, number> = {
        semantic: 0.08,
        document: 0.08,
        relation: 0.08,
        temporal: 0.08,
        causal: 0.08,
        evidence: 0.08,
        entity: 0.08,
    };
    laneWeights[dominantLane] = 0.9;
    return {
        semanticDepth: dominantLane === 'semantic' ? 0.74 : 0.26,
        documentDepth: dominantLane === 'document' ? 0.86 : 0.18,
        relationDepth: dominantLane === 'relation' ? 0.82 : 0.16,
        clusterRadius: 0.18,
        fiberPhase: unitHash(`${target.id}:caps-phase`),
        confidence: targetConfidence(target),
        dominantLane,
        laneWeights,
    };
}

function fallbackProductTopologyRegion(
    target: GraphRebuildEmbeddingTarget,
    lane: GraphRebuildProductLaneFeatures,
): GraphRebuildProductTopologyRegion {
    const laneKind = lane.dominantLane;
    const clusterId = `caps:${laneKind}:${normalizeHopfToken(target.id)}`;
    return {
        id: clusterId,
        role: 'core',
        laneKind,
        clusterId,
        medoidTargetId: target.id,
        memberCount: 1,
        density: 1,
        confidence: targetConfidence(target),
        bridgeTargetIds: [],
        backboneTargetIds: [target.id],
    };
}

function fallbackProductLaneKind(target: GraphRebuildEmbeddingTarget): GraphRebuildProductLaneKind {
    const kind = displayKind(target.kind);
    const lane = String(target.lane || '').toLowerCase();
    if (kind === 'note' || kind === 'structure-root' || kind === 'chunk' || /document|chunk/.test(lane)) return 'document';
    if (kind === 'anchor' || /anchor|evidence/.test(lane)) return 'evidence';
    if (kind === 'entity' || /entity|identity|character|location/.test(lane)) return 'entity';
    if (kind === 'causal-fact' || /causal/.test(lane)) return 'causal';
    if (kind === 'event' || kind === 'temporal-fact' || /event|temporal/.test(lane)) return 'temporal';
    if (kind === 'graph-fact' || /relationship|relation|fact/.test(lane)) return 'relation';
    return 'semantic';
}

function fallbackProductClusterRole(target: GraphRebuildEmbeddingTarget): GraphRebuildEmbeddingTargetPostProcess['clusterRole'] {
    const kind = displayKind(target.kind);
    if (kind === 'note' || kind === 'structure-root' || kind === 'chunk') return 'document_region';
    if (kind === 'entity') return 'entity_region';
    if (kind === 'event') return 'event_region';
    if (kind === 'graph-fact' || kind === 'temporal-fact' || kind === 'causal-fact' || kind === 'memory-state') return 'fact_region';
    return 'mixed_region';
}

function capsHierarchyPath(
    target: GraphRebuildEmbeddingTarget,
    hierarchyContext: TargetHierarchyContext | undefined,
    supportNoteIds: string[],
    supportChunkIds: string[],
    fallbackParentNodeId: string | null,
): CapsHierarchyPath {
    const role = capsHierarchyRoleForTarget(target);
    const band = HIERARCHY_SHELL_BANDS[role];
    const parents = target.parentIds || [];
    const noteIds = [...new Set([target.noteId || '', hierarchyContext?.noteId || '', ...supportNoteIds].filter(Boolean))].sort();
    const chunkIds = [...new Set([target.chunkId || '', hierarchyContext?.chunkId || '', ...supportChunkIds].filter(Boolean))].sort();
    const noteId = target.noteId || hierarchyContext?.noteId || noteIds[0];
    const chunkId = target.chunkId || hierarchyContext?.chunkId || chunkIds[0];
    const rootKey = role === 'documentRoot' ? capsStructureRootKey(target) : capsParentRootKey(target, parents);
    const documentCap = noteId ? `document:${noteId}` : '';
    const rootCap = noteId ? `document:${noteId}:root:${rootKey}` : '';
    const chunkCap = noteId && chunkId ? `document:${noteId}:chunk:${chunkId}` : '';
    const evidenceCap = chunkCap ? `${chunkCap}:evidence` : '';
    const entityId = capsTargetEntityId(target);
    const entityCap = entityId ? capsEntityCapId(entityId, noteId, chunkId, noteIds, chunkIds) : '';
    const eventParent = role === 'event' ? capsEventParentId(target) : null;
    const eventParentCap = eventParent
        ? capsEventCapIdFor(eventParent.slice('embed:event:'.length), entityId, noteId, chunkId, noteIds, chunkIds)
        : '';
    const family = relationFamilyFromText(target.label, target.text, target.sourceId) || 'relationship';
    return {
        role,
        band,
        capId: capsHierarchyCapId(target, role, documentCap, rootCap, chunkCap, evidenceCap, entityCap, eventParentCap, family),
        parentCapIds: capsHierarchyParentCapIds(role, noteIds, chunkIds, rootKey, entityCap, eventParentCap),
        parentNodeId: capsHierarchyParentNodeId(target, role, noteId, chunkId, fallbackParentNodeId),
    };
}

function capsHierarchyRoleForTarget(target: GraphRebuildEmbeddingTarget): CapsHierarchyRole {
    const kind = displayKind(target.kind);
    const lane = target.lane || '';
    if (kind === 'note') return 'document';
    if (kind === 'structure-root') return 'documentRoot';
    if (kind === 'chunk' || kind === 'document-unit' || lane === 'document_spine' || lane === 'chunk_spine') return 'chunk';
    if (kind === 'anchor' || kind === 'evidence-span' || lane === 'anchor_evidence') return 'evidence';
    if (kind === 'entity' || lane === 'entity_anchor') return 'entity';
    if (kind === 'event' || lane === 'event_identity') return 'event';
    if (kind === 'memory-state' || lane === 'memory_state') return 'memory';
    if (kind === 'graph-fact' || lane === 'relationship_fact') return 'fact';
    if (kind === 'causal-fact' || kind === 'temporal-fact' || lane === 'causal_fact' || lane === 'temporal_fact') return 'event';
    return 'memory';
}

function capsHierarchyCapId(
    target: GraphRebuildEmbeddingTarget,
    role: CapsHierarchyRole,
    documentCap: string,
    rootCap: string,
    chunkCap: string,
    evidenceCap: string,
    entityCap: string,
    eventParentCap: string,
    family: string,
): string {
    const sourceKey = normalizeHopfToken(target.sourceId || target.id);
    if (role === 'document') return documentCap || `document:${sourceKey}`;
    if (role === 'documentRoot') return rootCap || `document:unknown:root:${capsStructureRootKey(target)}`;
    if (role === 'chunk') return chunkCap || `chunk:${sourceKey}`;
    if (role === 'evidence') return evidenceCap || `evidence:${sourceKey}`;
    if (role === 'entity') return entityCap || `identity:${normalizeHopfToken(target.entityId || target.sourceId || target.id)}`;
    if (role === 'event') {
        if (displayKind(target.kind) === 'causal-fact') return eventParentCap ? `${eventParentCap}:causal` : `${evidenceCap || chunkCap || 'event'}:causal`;
        if (displayKind(target.kind) === 'temporal-fact') return eventParentCap ? `${eventParentCap}:temporal` : `${evidenceCap || chunkCap || 'event'}:temporal`;
        return `${entityCap || evidenceCap || chunkCap || documentCap || 'event'}:event:${sourceKey}`;
    }
    if (role === 'fact') return `${entityCap || evidenceCap || chunkCap || documentCap || 'signals'}:facts:${family}`;
    return `${entityCap || evidenceCap || chunkCap || documentCap || 'signals'}:memory`;
}

function capsHierarchyParentCapIds(
    role: CapsHierarchyRole,
    noteIds: string[],
    chunkIds: string[],
    rootKey: string,
    entityCap: string,
    eventParentCap: string,
): string[] {
    const rootCaps = capsRootParentCaps(noteIds, rootKey);
    const chunkCaps = capsChunkParentCaps(noteIds, chunkIds);
    const evidenceCaps = capsEvidenceParentCaps(noteIds, chunkIds);
    if (role === 'document') return [];
    if (role === 'documentRoot') return noteIds.map((noteId) => `document:${noteId}`);
    if (role === 'chunk') return rootCaps.length ? rootCaps : noteIds.map((noteId) => `document:${noteId}`);
    if (role === 'evidence') return chunkCaps.length ? chunkCaps : rootCaps;
    if (role === 'entity') return evidenceCaps.length ? evidenceCaps : chunkCaps.length ? chunkCaps : rootCaps;
    if (eventParentCap) return [eventParentCap];
    if (role === 'event' || role === 'fact' || role === 'memory') {
        return entityCap ? [entityCap] : evidenceCaps.length ? evidenceCaps : chunkCaps.length ? chunkCaps : rootCaps;
    }
    return chunkCaps.length ? chunkCaps : rootCaps;
}

function capsHierarchyParentNodeId(
    target: GraphRebuildEmbeddingTarget,
    role: CapsHierarchyRole,
    noteId: string | undefined,
    chunkId: string | undefined,
    fallbackParentNodeId: string | null,
): string | null {
    const parents = target.parentIds || [];
    if (role === 'document') return null;
    if (role === 'documentRoot' && noteId) return `embed:note:${noteId}`;
    if (role === 'chunk') return firstParentWithPrefix(parents, `embed:structure-root:${noteId || ''}:`) || (noteId ? `embed:note:${noteId}` : fallbackParentNodeId);
    if (role === 'evidence' && chunkId) return `embed:chunk:${chunkId}`;
    if (role === 'entity') return firstParentWithPrefix(parents, 'embed:anchor:') || (chunkId ? `embed:chunk:${chunkId}` : fallbackParentNodeId);
    if (role === 'event') return capsEventParentId(target) || firstParentWithPrefix(parents, 'embed:entity:') || (target.entityId ? `embed:entity:${target.entityId}` : fallbackParentNodeId);
    if (role === 'fact') return firstParentWithPrefix(parents, 'embed:entity:') || fallbackParentNodeId;
    if (role === 'memory') return firstParentWithPrefix(parents, 'embed:entity:') || (target.entityId ? `embed:entity:${target.entityId}` : fallbackParentNodeId);
    return fallbackParentNodeId;
}

function capsTargetEntityId(target: GraphRebuildEmbeddingTarget): string {
    const parent = firstParentWithPrefix(target.parentIds || [], 'embed:entity:');
    if (parent) return parent.slice('embed:entity:'.length);
    if (target.entityId) return target.entityId;
    if (displayKind(target.kind) === 'entity') return target.sourceId || target.id.replace(/^embed:entity:/, '');
    return '';
}

function capsEventParentId(target: GraphRebuildEmbeddingTarget): string | null {
    const parents = target.parentIds || [];
    const kind = displayKind(target.kind);
    if (kind === 'causal-fact') return lastParentWithPrefix(parents, 'embed:event:');
    if (kind === 'temporal-fact') return firstParentWithPrefix(parents, 'embed:event:');
    return firstParentWithPrefix(parents, 'embed:event:') || lastParentWithPrefix(parents, 'embed:event:');
}

function productCapId(
    target: GraphRebuildEmbeddingTarget,
    fallback: string,
    hierarchyContext: TargetHierarchyContext | undefined,
    supportNoteIds: string[],
): string {
    const supportChunkIds = capsSupportChunkIds(target, hierarchyContext);
    return capsHierarchyPath(target, hierarchyContext, supportNoteIds, supportChunkIds, null).capId || fallback;
}

function buildCapsDocumentDirections(
    targets: GraphRebuildEmbeddingTarget[],
    vectors: Float32Array[],
    manifold: AtlasManifoldMode,
): Map<string, CapsVec3> {
    const directions = new Map<string, CapsVec3>();
    for (let index = 0; index < targets.length; index += 1) {
        const target = targets[index];
        if (displayKind(target.kind) !== 'note' || !target.noteId) continue;
        directions.set(target.noteId, capsNormalize(projectVector(vectors[index], target.id, index, targets.length, manifold), capsStableVector(`document:${target.noteId}`)));
    }
    return directions;
}

function capsDirectionForTarget(
    target: GraphRebuildEmbeddingTarget,
    point: { x: number; y: number; z: number },
    hierarchyContext: TargetHierarchyContext | undefined,
    supportNoteIds: string[],
    supportChunkIds: string[],
    documentDirections?: Map<string, CapsVec3>,
): CapsVec3 {
    const kind = displayKind(target.kind);
    const noteId = target.noteId || hierarchyContext?.noteId || supportNoteIds[0];
    const fallback = capsNormalize(point, capsStableVector(target.id));
    const docDirection = capsAverageDocumentDirections(supportNoteIds.length ? supportNoteIds : noteId ? [noteId] : [], documentDirections, fallback);
    const chunkDirection = capsAverageChunkDirections(supportChunkIds, supportNoteIds, documentDirections, docDirection);
    if (kind === 'note') return fallback;
    if (kind === 'structure-root') {
        const rootLane = capsStructureRootKey(target);
        return capsNormalize(capsWeighted([
            [docDirection, 0.78],
            [capsLaneDirection(rootLane), 0.18],
            [capsStableVector(`${target.id}:root`), 0.08],
        ]), docDirection);
    }
    if (kind === 'chunk') {
        return capsNormalize(capsWeighted([
            [docDirection, 0.78],
            [chunkDirection, 0.16],
            [fallback, 0.06],
        ]), docDirection);
    }
    if (kind === 'entity') {
        return capsNormalize(capsWeighted([
            [docDirection, supportNoteIds.length > 1 ? 0.62 : 0.5],
            [chunkDirection, supportChunkIds.length ? 0.28 : 0.12],
            [capsLaneDirection('identity'), 0.08],
            [fallback, supportNoteIds.length > 1 ? 0.08 : 0.1],
            [capsStableVector(target.entityId || target.sourceId), 0.04],
        ]), docDirection);
    }
    return capsNormalize(capsWeighted([
        [docDirection, 0.44],
        [chunkDirection, supportChunkIds.length ? 0.34 : 0.1],
        [capsLaneDirection(target.lane || kind), 0.12],
        [fallback, 0.1],
    ]), fallback);
}

function capsAverageDocumentDirections(
    noteIds: string[],
    documentDirections: Map<string, CapsVec3> | undefined,
    fallback: CapsVec3,
): CapsVec3 {
    const uniqueNoteIds = [...new Set(noteIds)].filter(Boolean);
    if (!uniqueNoteIds.length) return fallback;
    const weighted = uniqueNoteIds.map((noteId): [CapsVec3, number] => [
        documentDirections?.get(noteId) || capsStableVector(`document:${noteId}`),
        1,
    ]);
    return capsNormalize(capsWeighted(weighted), fallback);
}

function capsAverageChunkDirections(
    chunkIds: string[],
    noteIds: string[],
    documentDirections: Map<string, CapsVec3> | undefined,
    fallback: CapsVec3,
): CapsVec3 {
    const uniqueChunkIds = [...new Set(chunkIds)].filter(Boolean);
    if (!uniqueChunkIds.length) return fallback;
    const uniqueNoteIds = [...new Set(noteIds)].filter(Boolean);
    const weighted: Array<[CapsVec3, number]> = [];
    for (const chunkId of uniqueChunkIds) {
        const noteDirection = capsAverageDocumentDirections(uniqueNoteIds, documentDirections, fallback);
        weighted.push([capsNormalize(capsWeighted([
            [noteDirection, 0.86],
            [capsStableVector(`chunk:${chunkId}`), 0.14],
        ]), noteDirection), 1]);
    }
    return capsNormalize(capsWeighted(weighted), fallback);
}

function capsSupportNoteIds(target: GraphRebuildEmbeddingTarget, context?: TargetHierarchyContext): string[] {
    const out = new Set<string>(context?.supportNoteIds || []);
    if (context?.noteId) out.add(context.noteId);
    if (target.noteId) out.add(target.noteId);
    for (const parentId of target.parentIds || []) {
        const noteId = parentId.match(/^embed:note:(.+)$/)?.[1]
            || parentId.match(/^embed:structure-root:([^:]+):/)?.[1];
        if (noteId) out.add(noteId);
        const chunkId = parentId.match(/^embed:chunk:(.+)$/)?.[1];
        const embeddedNoteId = chunkId?.match(/^([^:]+):/)?.[1];
        if (embeddedNoteId) out.add(embeddedNoteId);
    }
    return [...out].sort();
}

function capsSupportChunkIds(target: GraphRebuildEmbeddingTarget, context?: TargetHierarchyContext): string[] {
    const out = new Set<string>(context?.supportChunkIds || []);
    if (context?.chunkId) out.add(context.chunkId);
    if (target.chunkId) out.add(target.chunkId);
    for (const parentId of target.parentIds || []) {
        const chunkId = parentId.match(/^embed:chunk:(.+)$/)?.[1];
        if (chunkId) out.add(chunkId);
    }
    return [...out].sort();
}

function capsStructureRootKey(target: GraphRebuildEmbeddingTarget): string {
    const text = `${target.id} ${target.sourceId} ${target.label} ${target.text}`.toLowerCase();
    if (/identity|entity|alias/.test(text)) return 'identity';
    if (/temporal|timeline|before|after/.test(text)) return 'temporal';
    if (/causal|cause|effect/.test(text)) return 'causal';
    if (/evidence|source|provenance/.test(text)) return 'evidence';
    return 'document';
}

function productCapParentIds(
    target: GraphRebuildEmbeddingTarget,
    hierarchyContext: TargetHierarchyContext | undefined,
    supportNoteIds: string[],
    supportChunkIds: string[],
): string[] {
    return capsHierarchyPath(target, hierarchyContext, supportNoteIds, supportChunkIds, null).parentCapIds;
}

function capsParentRootKey(target: GraphRebuildEmbeddingTarget, parentIds: string[]): string {
    for (const parentId of parentIds) {
        const root = parentId.match(/^embed:structure-root:[^:]+:(.+)$/)?.[1];
        if (root) return capsNormalizeRootKey(root);
    }
    return capsStructureRootKey(target);
}

function capsNormalizeRootKey(value: string): string {
    if (/document|structure|chunk/.test(value)) return 'document';
    if (/identity|entity|alias/.test(value)) return 'identity';
    if (/temporal|timeline/.test(value)) return 'temporal';
    if (/causal|cause/.test(value)) return 'causal';
    if (/evidence|source/.test(value)) return 'evidence';
    return normalizeHopfToken(value);
}

function capsRootParentCaps(noteIds: string[], rootKey: string): string[] {
    return noteIds.map((noteId) => `document:${noteId}:root:${rootKey}`);
}

function capsChunkParentCaps(noteIds: string[], chunkIds: string[]): string[] {
    if (!noteIds.length || !chunkIds.length) return [];
    const out = new Set<string>();
    for (const chunkId of chunkIds) {
        const embeddedNote = noteIds.find((noteId) => chunkId.startsWith(`${noteId}:`));
        if (embeddedNote) {
            out.add(`document:${embeddedNote}:chunk:${chunkId}`);
            continue;
        }
        if (noteIds.length === 1) {
            out.add(`document:${noteIds[0]}:chunk:${chunkId}`);
            continue;
        }
        for (const noteId of noteIds) out.add(`document:${noteId}:chunk:${chunkId}`);
    }
    return [...out].sort();
}

function capsEvidenceParentCaps(noteIds: string[], chunkIds: string[]): string[] {
    return capsChunkParentCaps(noteIds, chunkIds).map((capId) => `${capId}:evidence`);
}

function capsEntityCapId(
    entityId: string,
    noteId: string | undefined,
    chunkId: string | undefined,
    supportNoteIds: string[],
    supportChunkIds: string[],
): string {
    const noteIds = [...new Set([noteId || '', ...supportNoteIds].filter(Boolean))];
    const chunkIds = [...new Set([chunkId || '', ...supportChunkIds].filter(Boolean))];
    const primaryNoteId = noteId || noteIds[0];
    const primaryChunkId = chunkId || chunkIds[0];
    if (primaryNoteId && primaryChunkId) return `document:${primaryNoteId}:chunk:${primaryChunkId}:evidence:entity:${entityId}`;
    if (primaryNoteId) return `document:${primaryNoteId}:entity:${entityId}`;
    return `identity:${entityId}`;
}

function capsEventCapId(
    target: GraphRebuildEmbeddingTarget,
    noteId: string | undefined,
    chunkId: string | undefined,
    supportNoteIds: string[],
    supportChunkIds: string[],
): string {
    const entityParent = firstParentWithPrefix(target.parentIds || [], 'embed:entity:') || (target.entityId ? `embed:entity:${target.entityId}` : null);
    const entityId = entityParent ? entityParent.slice('embed:entity:'.length) : '';
    return capsEventCapIdFor(target.sourceId || target.id, entityId, noteId, chunkId, supportNoteIds, supportChunkIds);
}

function capsEventCapIdFor(
    eventId: string,
    entityId: string,
    noteId: string | undefined,
    chunkId: string | undefined,
    supportNoteIds: string[],
    supportChunkIds: string[],
): string {
    const entityCap = entityId ? capsEntityCapId(entityId, noteId, chunkId, supportNoteIds, supportChunkIds) : '';
    if (entityCap && !entityCap.startsWith('identity:')) return `${entityCap}:event:${eventId}`;
    const primaryNoteId = noteId || supportNoteIds[0];
    const primaryChunkId = chunkId || supportChunkIds[0];
    if (primaryNoteId && primaryChunkId) return `document:${primaryNoteId}:chunk:${primaryChunkId}:evidence:event:${eventId}`;
    if (primaryNoteId) return `document:${primaryNoteId}:event:${eventId}`;
    return `event:${eventId}`;
}

function capsContainmentPath(capId: string, parentCapIds: string[]): string {
    return parentCapIds.length ? `${parentCapIds[0]}/${capId}` : capId;
}

function capsLaneDirection(lane: string): CapsVec3 {
    const value = lane.toLowerCase();
    if (/identity|entity/.test(value)) return capsNormalize({ x: -0.62, y: 0.58, z: 0.22 }, { x: -1, y: 1, z: 0 });
    if (/temporal/.test(value)) return capsNormalize({ x: 0.2, y: 0.88, z: -0.28 }, { x: 0, y: 1, z: 0 });
    if (/causal/.test(value)) return capsNormalize({ x: 0.86, y: -0.24, z: 0.34 }, { x: 1, y: 0, z: 0 });
    if (/evidence|anchor/.test(value)) return capsNormalize({ x: -0.58, y: -0.1, z: 0.8 }, { x: -1, y: 0, z: 0 });
    if (/event/.test(value)) return capsNormalize({ x: 0.54, y: 0.36, z: -0.76 }, { x: 0, y: 0, z: -1 });
    if (/relationship|fact|cooccurrence/.test(value)) return capsNormalize({ x: 0.56, y: -0.62, z: -0.2 }, { x: 1, y: -1, z: 0 });
    return capsNormalize({ x: -0.3, y: 0.18, z: 0.94 }, { x: 0, y: 0, z: 1 });
}

function capsWeighted(values: Array<[CapsVec3, number]>): CapsVec3 {
    return values.reduce((sum, [value, weight]) => ({
        x: sum.x + value.x * weight,
        y: sum.y + value.y * weight,
        z: sum.z + value.z * weight,
    }), { x: 0, y: 0, z: 0 });
}

function capsNormalize(value: CapsVec3, fallback: CapsVec3): CapsVec3 {
    const norm = Math.hypot(value.x, value.y, value.z);
    return norm > 0.0001 ? { x: value.x / norm, y: value.y / norm, z: value.z / norm } : fallback;
}

function capsStableVector(id: string): CapsVec3 {
    const a = unitHash(`${id}:caps:a`) * Math.PI * 2;
    const y = unitHash(`${id}:caps:y`) * 2 - 1;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    return { x: Math.cos(a) * radial, y, z: Math.sin(a) * radial };
}

function productCapParentId(
    target: GraphRebuildEmbeddingTarget,
    fallback: string | null,
    hierarchyContext?: TargetHierarchyContext,
): string | null {
    const parents = target.parentIds || [];
    const noteId = target.noteId || hierarchyContext?.noteId;
    const chunkId = target.chunkId || hierarchyContext?.chunkId;
    const kind = displayKind(target.kind);
    if (kind === 'structure-root' && noteId) return `embed:note:${noteId}`;
    if (target.kind === 'chunk' && noteId) return firstParentWithPrefix(parents, `embed:structure-root:${noteId}:document-structure`) || `embed:note:${noteId}`;
    if (target.kind === 'entity' && chunkId) return firstParentWithPrefix(parents, 'embed:anchor:') || `embed:chunk:${chunkId}`;
    if (target.kind === 'entity' && noteId) return firstParentWithPrefix(parents, `embed:structure-root:${noteId}:identity`) || `embed:structure-root:${noteId}:identity`;
    if (target.kind === 'anchor' && chunkId) return `embed:chunk:${chunkId}`;
    if (target.kind === 'anchor' && target.entityId) return `embed:entity:${target.entityId}`;
    if (kind === 'event') return firstParentWithPrefix(parents, 'embed:entity:') || (chunkId ? `embed:chunk:${chunkId}` : fallback);
    if (kind === 'causal-fact') return lastParentWithPrefix(parents, 'embed:event:') || firstParentWithPrefix(parents, `embed:structure-root:${noteId || ''}:causal`) || fallback;
    if (kind === 'temporal-fact') return firstParentWithPrefix(parents, 'embed:event:') || firstParentWithPrefix(parents, `embed:structure-root:${noteId || ''}:temporal`) || fallback;
    if (kind === 'graph-fact') return firstParentWithPrefix(parents, 'embed:entity:') || (chunkId ? `embed:chunk:${chunkId}` : fallback);
    if (kind === 'memory-state' && target.entityId) return `embed:entity:${target.entityId}`;
    if (parents.length) return parents[0];
    return fallback;
}

function productCapShellRadius(
    target: GraphRebuildEmbeddingTarget,
    specificity: number,
    ambiguity: number,
): number {
    void specificity;
    void ambiguity;
    return HIERARCHY_SHELL_BANDS[capsHierarchyRoleForTarget(target)].radius;
}

function productCapShellBand(target: GraphRebuildEmbeddingTarget): [number, number] {
    const band = HIERARCHY_SHELL_BANDS[capsHierarchyRoleForTarget(target)];
    return [band.min, band.max];
}

function productHierarchySpecificity(
    target: GraphRebuildEmbeddingTarget,
    post?: GraphRebuildEmbeddingTargetPostProcess,
): number {
    const kind = displayKind(target.kind);
    let base = 0.58;
    if (kind === 'note') base = 0.22;
    else if (kind === 'structure-root') base = 0.42;
    else if (kind === 'chunk' || kind === 'anchor') base = 0.9;
    else if (kind === 'entity') base = 0.82;
    else if (kind === 'event' || kind === 'temporal-fact' || kind === 'causal-fact') base = 0.74;
    else if (kind === 'graph-fact' || kind === 'memory-state') base = 0.64;
    const role = post?.productTopologyRegion.role || 'core';
    const roleBoost = role === 'outlier' ? 0.14 : role === 'boundary' ? 0.08 : role === 'bridge' ? 0.05 : role === 'core' ? -0.04 : 0;
    return clamp01(base + roleBoost + (post?.productLaneFeatures.semanticDepth ?? 0.26) * 0.08);
}

function productHierarchyAmbiguity(post?: GraphRebuildEmbeddingTargetPostProcess): number {
    if (!post) return 0.08;
    const role = post.productTopologyRegion.role;
    const roleBoost = role === 'outlier' ? 0.22 : role === 'bridge' ? 0.12 : role === 'boundary' ? 0.08 : 0;
    return clamp01(post.productLaneFeatures.clusterRadius * 0.52 + post.outlierScore * 0.28 + roleBoost);
}

function productRegionLevel(target: GraphRebuildEmbeddingTarget, post?: GraphRebuildEmbeddingTargetPostProcess): number {
    void post;
    return HIERARCHY_SHELL_BANDS[capsHierarchyRoleForTarget(target)].rank;
}

function productFiberKind(role: string, laneKind?: string): string {
    if (laneKind === 'causal') return 'causal';
    if (laneKind === 'temporal') return 'timeline';
    if (laneKind === 'evidence') return 'evidence';
    if (laneKind === 'entity') return 'identity';
    if (laneKind === 'document') return 'documentStructure';
    if (laneKind === 'relation') return 'relationship';
    if (laneKind === 'semantic') return 'abstraction';
    if (role === 'document_region') return 'documentStructure';
    if (role === 'event_region') return 'event';
    if (role === 'fact_region') return 'relationship';
    if (role === 'entity_region') return 'identity';
    return 'abstraction';
}

function buildTargetEdges(snapshot: GraphRebuildSnapshot): GalaxyInputEdge[] {
    const edges: GalaxyInputEdge[] = [];
    const add = (id: string, sourceId: string, targetId: string, type: string, confidence: number, metadata?: Record<string, unknown>) => {
        if (sourceId === targetId) return;
        edges.push({ id, sourceId, targetId, type, confidence, metadata });
    };

    for (const chunk of snapshot.chunks) {
        add(`embed:note-chunk:${chunk.id}`, `embed:note:${chunk.noteId}`, `embed:chunk:${chunk.id}`, 'note-chunk', 0.9);
    }
    const targetIds = new Set(snapshot.embeddingTargets.map((target) => target.id));
    const typedIncidenceFactIds = new Set((snapshot.graphModelV2?.projectionEdges || [])
        .filter((edge) => edge.projectionKind === 'factRole' && edge.sourceFactId)
        .map((edge) => edge.sourceFactId as string));
    for (const target of snapshot.embeddingTargets) {
        for (const parentId of target.parentIds || []) {
            if (typedIncidenceFactIds.has(target.sourceId)
                && (parentId.startsWith('embed:entity:') || parentId.startsWith('embed:atom:'))) continue;
            if (targetIds.has(parentId)) add(`embed:target-parent:${parentId}:${target.id}`, parentId, target.id, 'target-parent', 0.88);
        }
    }
    for (const anchor of snapshot.entityAnchors) {
        if (anchor.chunkId) {
            add(`embed:chunk-anchor:${anchor.id}`, `embed:chunk:${anchor.chunkId}`, `embed:anchor:${anchor.id}`, 'chunk-anchor', anchor.confidence);
            add(`embed:chunk-entity:${anchor.chunkId}:${anchor.entityId}`, `embed:chunk:${anchor.chunkId}`, `embed:entity:${anchor.entityId}`, 'chunk-entity', anchor.confidence);
        }
        add(`embed:anchor-entity:${anchor.id}`, `embed:anchor:${anchor.id}`, `embed:entity:${anchor.entityId}`, 'anchor-entity', anchor.confidence);
    }
    for (const relationship of snapshot.relationships) {
        if (relationship.status === 'rejected') continue;
        if (relationFamilyFromText(relationship.relationType, relationship.id) !== 'cooccurrence') continue;
        add(
            `embed:relationship:${relationship.id}`,
            `embed:entity:${relationship.sourceEntityId}`,
            `embed:entity:${relationship.targetEntityId}`,
            relationship.relationType,
            relationship.confidence,
        );
    }
    const v2EdgesAdded = addGraphModelV2ProjectionEdges(snapshot, add);
    if (!v2EdgesAdded) {
        for (const edge of snapshot.edges) {
            add(`embed:graph-edge:${edge.id}`, `embed:entity:${edge.sourceId}`, `embed:entity:${edge.targetId}`, edge.type, edge.confidence);
        }
        for (const relationship of snapshot.relationships) {
            if (relationship.status === 'rejected') continue;
            if (relationFamilyFromText(relationship.relationType, relationship.id) === 'cooccurrence') continue;
            const factId = `embed:graph-fact:${relationship.id}`;
            add(`embed:fact-source:${relationship.id}`, factId, `embed:entity:${relationship.sourceEntityId}`, relationship.relationType, relationship.confidence);
            add(`embed:fact-target:${relationship.id}`, factId, `embed:entity:${relationship.targetEntityId}`, relationship.relationType, relationship.confidence);
        }
    }
    for (const event of snapshot.events) {
        const eventId = `embed:event:${event.id}`;
        if (event.chunkId) add(`embed:event-chunk:${event.id}`, eventId, `embed:chunk:${event.chunkId}`, 'event-chunk', event.confidence);
        for (const entityId of event.entityIds) add(`embed:event-entity:${event.id}:${entityId}`, eventId, `embed:entity:${entityId}`, 'event-entity', event.confidence);
    }
    for (const edge of snapshot.temporalEdges) {
        add(`embed:temporal:${edge.id}`, `embed:temporalFact:${edge.id}`, `embed:event:${edge.sourceId}`, edge.relationType, edge.confidence);
        add(`embed:temporal-target:${edge.id}`, `embed:temporalFact:${edge.id}`, `embed:event:${edge.targetId}`, edge.relationType, edge.confidence);
    }
    for (const edge of snapshot.causalEdges) {
        add(`embed:causal:${edge.id}`, `embed:causalFact:${edge.id}`, `embed:event:${edge.sourceId}`, edge.relationType, edge.confidence);
        add(`embed:causal-target:${edge.id}`, `embed:causalFact:${edge.id}`, `embed:event:${edge.targetId}`, edge.relationType, edge.confidence);
    }
    for (const state of snapshot.memoryState) {
        add(`embed:memory-entity:${state.id}`, `embed:memory:${state.id}`, `embed:entity:${state.entityId}`, 'memory-entity', 0.72);
    }
    for (const edge of snapshot.embeddingGraphPostProcess?.backboneEdges || []) {
        add(edge.id, edge.sourceTargetId, edge.targetTargetId, `embedding-${edge.role}`, edge.score);
    }
    for (const edge of snapshot.episodeProjectionEdges || []) {
        const projectionEdge = episodeProjectionEmbeddingEdge(edge);
        add(
            projectionEdge.id,
            projectionEdge.sourceId,
            projectionEdge.targetId,
            projectionEdge.type,
            projectionEdge.confidence,
            projectionEdge.metadata,
        );
    }
    addDiscourseOverlayEdges(snapshot, add);
    return dedupeEdges(edges);
}

function addDiscourseOverlayEdges(
    snapshot: GraphRebuildSnapshot,
    add: (id: string, sourceId: string, targetId: string, type: string, confidence: number, metadata?: Record<string, unknown>) => void,
): void {
    for (const edge of snapshot.discourseCompilerOverlaySummary?.overlayEdges || []) {
        const type = edge.proposedEdgeType || edge.kind;
        const metadata = discourseOverlayEdgeMetadata(edge);
        if (edge.kind === 'document_cluster') {
            const members = [...new Set([edge.sourceTargetId, edge.targetTargetId || '', ...edge.memberTargetIds].filter(Boolean))];
            const medoid = edge.sourceTargetId || members[0];
            for (const memberId of members) {
                if (!medoid || memberId === medoid) continue;
                add(`${edge.id}:member:${memberId}`, medoid, memberId, type, edge.confidence, {
                    ...metadata,
                    clusterMedoidTargetId: medoid,
                    clusterMemberTargetId: memberId,
                });
            }
            continue;
        }
        if (!edge.targetTargetId) continue;
        add(edge.id, edge.sourceTargetId, edge.targetTargetId, type, edge.confidence, metadata);
    }
}

function discourseOverlayEdgeMetadata(edge: NonNullable<GraphRebuildSnapshot['discourseCompilerOverlaySummary']>['overlayEdges'][number]): Record<string, unknown> {
    const interactionKind = edge.kind === 'chunk_wormhole' ? 'wormhole' : edge.kind;
    return {
        interactionKind,
        overlayEdgeId: edge.id,
        sourceHintId: edge.sourceHintId,
        sourceLedgerEntryId: edge.sourceLedgerEntryId,
        candidateId: edge.candidateId,
        decisionId: edge.decisionId,
        projectionKind: edge.projectionKind,
        status: edge.status,
        reviewState: edge.status,
        graphPatch: false,
        mutationAllowed: false,
        graphImpact: 'Read-only discourse overlay; no graph patch or topology commit exists.',
        detector: 'discourseCompilerOverlay',
        reasons: edge.rationale,
        evidenceIds: edge.evidenceTargetIds,
        memberTargetIds: edge.memberTargetIds,
        proposedEdgeType: edge.proposedEdgeType,
        graphRelationFamily: edge.kind === 'document_cluster' ? 'documentStructure' : 'relationship',
    };
}

function edgeWithVisualTrace(
    edge: GalaxyInputEdge,
    traceByTargetId: Map<string, GraphRebuildVisualTrace>,
): GalaxyInputEdge {
    const sourceTrace = traceByTargetId.get(edge.sourceId) || graphTopologyFallbackVisualTrace(edge.sourceId);
    const targetTrace = traceByTargetId.get(edge.targetId) || graphTopologyFallbackVisualTrace(edge.targetId);
    const packetOwned = sourceTrace.source === 'rust_atlas_packet' || targetTrace.source === 'rust_atlas_packet';
    const packetSnapshotId = sourceTrace.packetSnapshotId || targetTrace.packetSnapshotId;
    const packetScopeId = sourceTrace.packetScopeId || targetTrace.packetScopeId;
    const sourceContract = sourceTrace.sourceContract || targetTrace.sourceContract;
    const vectorContract = sourceTrace.vectorContract || targetTrace.vectorContract;
    const visualTrace: GraphRebuildVisualTrace = {
        source: packetOwned ? 'rust_atlas_packet' : 'graph_rebuild_embedding_target',
        sourceId: sourceTrace.sourceId || edge.sourceId,
        family: targetTrace.family || sourceTrace.family || 'unknown',
        packetSnapshotId,
        packetScopeId,
        sourceContract,
        vectorContract,
        identityAuthority: sourceTrace.identityAuthority || targetTrace.identityAuthority,
        packetObjectId: sourceTrace.packetObjectId || edge.sourceId,
        packetTargetId: targetTrace.packetTargetId || edge.targetId,
        objectKind: sourceTrace.targetKind || sourceTrace.objectKind,
        targetKind: targetTrace.targetKind || targetTrace.objectKind,
        noteIds: uniqueVisualTraceIds(sourceTrace.noteIds, targetTrace.noteIds),
        chunkIds: uniqueVisualTraceIds(sourceTrace.chunkIds, targetTrace.chunkIds),
        evidenceIds: uniqueVisualTraceIds(sourceTrace.evidenceIds, targetTrace.evidenceIds),
    };
    return {
        ...edge,
        metadata: {
            ...(edge.metadata || {}),
            sourceId: visualTrace.sourceId,
            sourceContract,
            vectorContract,
            visualTrace,
            sourceVisualTrace: sourceTrace,
            targetVisualTrace: targetTrace,
            visualSourceId: visualTrace.sourceId,
            visualFamily: visualTrace.family,
            graphFamily: visualTrace.family,
            packetSnapshotId,
            packetScopeId,
        },
    };
}

function uniqueVisualTraceIds(...values: Array<string[] | undefined>): string[] {
    return [...new Set(values.flatMap((ids) => ids || []).filter(Boolean))];
}

function addGraphModelV2ProjectionEdges(
    snapshot: GraphRebuildSnapshot,
    add: (id: string, sourceId: string, targetId: string, type: string, confidence: number) => void,
): boolean {
    if (!snapshot.graphModelV2) return false;
    const readModel = createGraphModelV2ReadModel(snapshot.graphModelV2);
    let added = 0;
    for (const edge of readModel.model.projectionEdges) {
        if (edge.projectionKind === 'structure') continue;
        const sourceId = graphModelV2TargetToEmbeddingId(edge.sourceId);
        const targetId = graphModelV2TargetToEmbeddingId(edge.targetId);
        if (!sourceId || !targetId) continue;
        add(`embed:v2:${edge.id}`, sourceId, targetId, edge.edgeType.replace(/^role:/, ''), edge.confidence);
        added += 1;
    }
    return added > 0;
}

function graphModelV2TargetToEmbeddingId(targetId: string): string | null {
    const [prefix, kind, ...rest] = targetId.split(':');
    const sourceId = rest.join(':');
    if (!sourceId) return null;
    if (prefix === 'atom') {
        if (kind === 'relationFact') return graphModelFactToEmbeddingId(sourceId);
        if (kind === 'document') return `embed:note:${sourceId}`;
        if (kind === 'chunk') return `embed:chunk:${sourceId}`;
        if (kind === 'evidence' || kind === 'sourceSpan') return `embed:anchor:${sourceId}`;
        if (kind === 'documentMention' || kind === 'documentEvidence' || kind === 'documentUnit') return `embed:${targetId}`;
        if (kind === 'entity') return `embed:entity:${sourceId}`;
        if (kind === 'event') return `embed:event:${sourceId}`;
        if (kind === 'state') return `embed:memory:${sourceId}`;
    }
    if (prefix === 'fact') return graphModelFactToEmbeddingId(targetId);
    return null;
}

function graphModelFactToEmbeddingId(factId: string): string | null {
    if (factId.startsWith('fact:document-hyperedge:')) return `embed:${factId}`;
    if (factId.startsWith('fact:relationship:')) return `embed:graph-fact:${factId.slice('fact:relationship:'.length)}`;
    if (factId.startsWith('fact:temporal:')) return `embed:temporalFact:${factId.slice('fact:temporal:'.length)}`;
    if (factId.startsWith('fact:causal:')) return `embed:causalFact:${factId.slice('fact:causal:'.length)}`;
    if (factId.startsWith('fact:memory:')) return `embed:memory:${factId.slice('fact:memory:'.length)}`;
    return null;
}

function dedupeEdges(edges: GalaxyInputEdge[]): GalaxyInputEdge[] {
    const seen = new Set<string>();
    return edges.filter((edge) => {
        const key = `${edge.sourceId}|${edge.targetId}|${edge.type}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function textVector(target: GraphRebuildEmbeddingTarget, dimensions: number): Float32Array {
    return sparseToDenseVector(sparseEmbeddingSignature(target, dimensions), dimensions);
}

function projectVector(
    vector: Float32Array,
    id: string,
    index: number,
    total: number,
    manifold: AtlasManifoldMode,
): { x: number; y: number; z: number } {
    const spiral = index * 2.399963229728653 + unitHash(id);
    const y = total > 1 ? 1 - (index / (total - 1)) * 2 : 0;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const scale = manifold === 'hopf' ? 0.86 : manifold === 'lorentz' ? 1.22 : manifold === 'product' ? 1.08 : manifold === 'siegel' ? 1.12 : 1.48;
    return {
        x: (vector[0] * 0.9 + Math.cos(spiral) * radial) * scale,
        y: (vector[1] * 0.7 + y * 0.64) * scale,
        z: (vector[2] * 0.9 + Math.sin(spiral) * radial) * scale,
    };
}

function projectSiegelVector(
    vector: Float32Array,
    target: GraphRebuildEmbeddingTarget,
    index: number,
    total: number,
    hierarchyContext?: TargetHierarchyContext,
): { x: number; y: number; z: number } {
    const depth = siegelDepth(target, hierarchyContext);
    const lane = siegelBandForTarget(target, hierarchyContext);
    const projectionSeed = siegelProjectionSeed(target);
    const phase = unitHash(`${projectionSeed}:siegel-projection`);
    const localPhase = unitHash(`${target.id}:siegel-local`) - 0.5;
    const angle = phase * Math.PI * 2;
    const semantic = targetSemanticSpread(vector, index, total);
    const layer = siegelDepthLayer(depth);
    const laneShift = siegelLaneShift(lane);
    const structureChildScale = isDocumentStructureUnitTarget(target) && target.chunkId ? 0.42 : 1;
    const radius = (0.58 + semantic.radial * 0.3 * structureChildScale + phase * 0.08 + localPhase * 0.04) * (1 + depth * 0.025);
    return {
        x: (Math.cos(angle) * radius + vector[0] * 0.22 + laneShift.x) * 1.12,
        y: layer + vector[1] * 0.1 + laneShift.y,
        z: (Math.sin(angle) * radius + vector[2] * 0.3 + laneShift.z + semantic.z * 0.18) * 1.28,
    };
}

function siegelProjectionSeed(target: GraphRebuildEmbeddingTarget): string {
    if (isDocumentStructureUnitTarget(target) && target.chunkId) {
        return `embed:chunk:${target.chunkId}`;
    }
    return target.id;
}

function targetSemanticSpread(vector: Float32Array, index: number, total: number): { radial: number; z: number } {
    const ordinal = total > 1 ? index / (total - 1) : 0.5;
    return {
        radial: clampRange(Math.abs(vector[3] ?? 0) + Math.abs(vector[4] ?? 0) + ordinal * 0.35, 0, 1.4),
        z: (vector[5] ?? 0) + (0.5 - ordinal) * 0.4,
    };
}

function siegelDepthLayer(depth: number): number {
    return 1.08 - clampHierarchyDepth(depth) * 0.21;
}

function clampHierarchyDepth(depth: number): number {
    return Math.max(0, Math.min(SIEGEL_BAND_ORDER.semantic, depth));
}

function siegelLaneShift(lane: string): { x: number; y: number; z: number } {
    if (lane === 'document') return { x: -0.42, y: 0.04, z: -0.18 };
    if (lane === 'documentRoot') return { x: -0.34, y: 0.02, z: -0.08 };
    if (lane === 'chunk') return { x: -0.22, y: 0, z: 0.02 };
    if (lane === 'event') return { x: -0.06, y: -0.02, z: -0.32 };
    if (lane === 'location') return { x: 0.12, y: -0.03, z: 0.34 };
    if (lane === 'character') return { x: 0.26, y: -0.04, z: 0.16 };
    if (lane === 'entityOther') return { x: 0.38, y: -0.04, z: 0.02 };
    if (lane === 'stateContext') return { x: 0.48, y: -0.05, z: -0.22 };
    if (lane === 'relationship') return { x: 0.56, y: -0.05, z: -0.12 };
    if (lane === 'evidence') return { x: 0.64, y: -0.06, z: 0.26 };
    return { x: 0.66, y: -0.06, z: 0 };
}

function displayKind(kind: string): string {
    return String(kind || 'target').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

function normalizeHopfToken(value: string): string {
    return String(value || 'unknown').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
}

function graphRebuildGeometryVersion(manifold: AtlasManifoldMode): string {
    if (manifold === 'hopf') return 'graph_rebuild_hopf_v1';
    if (manifold === 'lorentz') return 'graph_rebuild_hierarchy_caps_v1';
    if (manifold === 'product') return 'graph_rebuild_transit_lorentz_hopf_v1';
    if (manifold === 'siegel') return 'graph_rebuild_siegel_finsler_v1';
    return 'graph_rebuild_hybrid_v1';
}

function graphRebuildProjectionLabel(manifold: AtlasManifoldMode): string {
    if (manifold === 'lorentz') return 'hierarchy caps';
    if (manifold === 'siegel') return 'siegel-finsler';
    if (manifold === 'product') return 'transit';
    return manifold;
}

function graphRebuildCapabilities(manifold: AtlasManifoldMode): ManifoldCapabilities {
    if (manifold === 'hopf') return HOPF_MANIFOLD_CAPABILITIES;
    if (manifold === 'lorentz') return LORENTZ_MANIFOLD_CAPABILITIES;
    if (manifold === 'product') return PRODUCT_MANIFOLD_CAPABILITIES;
    if (manifold === 'siegel') return SIEGEL_FINSLER_CAPABILITIES;
    return HYBRID_MANIFOLD_CAPABILITIES;
}

function firstParentWithPrefix(parentIds: string[], prefix: string): string | null {
    return parentIds.find((parentId) => parentId.startsWith(prefix)) || null;
}

function lastParentWithPrefix(parentIds: string[], prefix: string): string | null {
    for (let index = parentIds.length - 1; index >= 0; index -= 1) {
        if (parentIds[index].startsWith(prefix)) return parentIds[index];
    }
    return null;
}

function capsNodeCapToken(nodeId: string): string {
    if (nodeId.startsWith('embed:event:')) return `event:${nodeId.slice('embed:event:'.length)}`;
    if (nodeId.startsWith('embed:entity:')) return `identity:${nodeId.slice('embed:entity:'.length)}`;
    if (nodeId.startsWith('embed:chunk:')) return `chunk:${nodeId.slice('embed:chunk:'.length)}`;
    if (nodeId.startsWith('embed:note:')) return `document:${nodeId.slice('embed:note:'.length)}`;
    return normalizeHopfToken(nodeId);
}

function unitHash(value: string): number {
    return hash(value) / 4294967295;
}

function unitPhase(value: number): number {
    const finite = Number.isFinite(value) ? value : 0;
    return ((finite % 1) + 1) % 1;
}

function clamp01(value: number): number {
    return Math.min(1, Math.max(0, value));
}

function clampRange(value: number, min: number, max: number): number {
    if (!Number.isFinite(value)) return min;
    return Math.min(max, Math.max(min, value));
}

function hash(value: string): number {
    let out = 2166136261;
    for (let index = 0; index < value.length; index++) {
        out ^= value.charCodeAt(index);
        out = Math.imul(out, 16777619);
    }
    return out >>> 0;
}
