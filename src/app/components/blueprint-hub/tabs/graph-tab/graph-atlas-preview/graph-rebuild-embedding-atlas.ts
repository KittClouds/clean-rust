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
    GraphRebuildSnapshot,
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
import { relationFamilyFromText, relationHslFromText } from './graph-relation-visual-style';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';

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
    const entityKindById = new Map(snapshot.nodes.map((node) => [node.entityId, node.kind]));
    const profile = normalizeEmbeddingProfile(snapshot.embeddingProfile);
    const postByTarget = new Map((snapshot.embeddingGraphPostProcess?.targets || []).map((row) => [row.targetId, row]));
    const mentionCompaction = compactEntityMentionTargets(snapshot, selectEmbeddingTargets(snapshot));
    const selected = mentionCompaction.targets
        .map((target) => hydrateTargetEntityKind(target, entityKindById));
    const hierarchyByTarget = buildTargetHierarchyContext(snapshot);
    const truthByTarget = buildGraphSignalTruthIndex(snapshot);
    const commitmentBySourceId = buildBundleCommitmentIndex(snapshot);
    const vectors = selected.map((target) => textVector(target, profile.selectedDimensions));
    const capsDocumentDirections = buildCapsDocumentDirections(selected, vectors, manifold);
    const hopfBasePlan = manifold === 'hopf' ? buildHopfAtlasAssignmentPlan(snapshot, selected, vectors, postByTarget) : undefined;
    const rawNodes = selected.map((target, index) =>
        targetNode(target, vectors[index], index, selected.length, manifold, postByTarget.get(target.id), hopfBasePlan?.get(target.id), hierarchyByTarget.get(target.id), truthByTarget.get(target.id), commitmentBySourceId.get(target.sourceId) || commitmentBySourceId.get(target.id), mentionCompaction.receiptsByEntityTargetId.get(target.id), capsDocumentDirections),
    );
    const nodeIds = new Set(rawNodes.map((node) => node.id));
    const rawEdges = buildTargetEdges(snapshot).filter((edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId));
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
        sourceLabel: `graph rebuild snapshot -> ${graphRebuildProjectionLabel(manifold)} projection`,
        searchIndex: nodes.map((node, index): EmbeddingAtlasSearchItem => ({
            nodeId: node.id,
            vector: vectors[index],
        })),
        manifold: {
            mode: manifold,
            geometryVersion: graphRebuildGeometryVersion(manifold),
            sourceLabel: 'graph rebuild snapshot',
            capabilities: graphRebuildCapabilities(manifold),
            projectionSource: 'graph_rebuild_embedding_targets',
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
        if (target.kind !== 'anchor' || !target.entityId) continue;
        recordAnchor(target.entityId, target.sourceId || target.id.replace(/^embed:anchor:/, ''), target.noteId, target.chunkId, target.label, targetConfidence(target));
    }

    for (const target of selected) {
        if (target.kind !== 'anchor' || !target.entityId) continue;
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

function isVisibleAtlasTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return !isWeakCooccurrenceTarget(target);
}

function isWeakCooccurrenceTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return target.lane === 'cooccurrence_weak'
        || (displayKind(target.kind) === 'graph-fact'
            && relationFamilyFromText(target.label, target.text, target.sourceId) === 'cooccurrence');
}

function coverageOrderedTargets(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    const weight = (target: GraphRebuildEmbeddingTarget) => {
        switch (displayKind(target.kind)) {
            case 'note': return 900;
            case 'structure-root': return 890;
            case 'chunk': return 880;
            case 'causal-fact': return 860;
            case 'temporal-fact': return 850;
            case 'event': return 830;
            case 'memory-state': return 810;
            case 'graph-fact': return 790;
            case 'entity': return 760;
            case 'anchor': return 700;
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
    if (/document|chunk|anchor/.test(kind)) return 'evidence';
    if (/entity|character|location|network/.test(kind)) return 'identity';
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
    return contexts;
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
    const point = projectVector(vector, target.id, index, total, manifold);
    const busemannSignature = graphModelBusemannSignature(commitment);
    const relationFamily = displayKind(target.kind) === 'graph-fact'
        ? relationFamilyFromText(target.label, target.text, target.sourceId)
        : null;
    const totalMentions = mentionCompaction?.anchorCount ?? target.evidenceIds.length;
    return {
        id: target.id,
        label: target.label || target.id,
        kind: targetRenderKind(target),
        totalMentions: Math.max(1, totalMentions),
        atlasX: point.x,
        atlasY: point.y,
        atlasZ: point.z,
        colorHsl: targetColorHsl(target),
        metadata: {
            sourceType: target.kind,
            sourceId: target.sourceId,
            entityKind: target.entityKind,
            graphColorKind: relationFamily || targetRenderKind(target),
            graphRelationFamily: relationFamily || undefined,
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
            lorentz: post ? productLorentzMetadata(target, point, post, hierarchyContext, capsDocumentDirections) : undefined,
            hopf: manifold === 'hopf'
                ? graphRebuildHopfMetadata(target, post, manifold, hopfBase)
                : post ? graphRebuildHopfMetadata(target, post, manifold) : undefined,
            graphKind: targetRenderKind(target),
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

function graphRebuildSiegelMetadata(
    target: GraphRebuildEmbeddingTarget,
    post?: GraphRebuildEmbeddingTargetPostProcess,
    hierarchyContext?: TargetHierarchyContext,
): Record<string, unknown> {
    const lane = normalizeSiegelLane(target.lane, target.kind);
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

function normalizeSiegelLane(lane: string | undefined, kind: string): string {
    const raw = String(lane || kind || '').toLowerCase();
    if (/document|chunk|spine|structure/.test(raw)) return 'document';
    if (/entity|anchor/.test(raw)) return 'entity';
    if (/relationship|cooccurrence/.test(raw)) return 'relationship';
    if (/temporal/.test(raw)) return 'temporal';
    if (/causal/.test(raw)) return 'causal';
    if (/memory|evidence/.test(raw)) return 'evidence';
    if (/event|story/.test(raw)) return 'event';
    return 'semantic';
}

function siegelDepth(target: GraphRebuildEmbeddingTarget, hierarchyContext?: TargetHierarchyContext): number {
    const kind = displayKind(target.kind);
    if (kind === 'note') return 0;
    if (kind === 'structure-root') return 1;
    if (kind === 'chunk') return 2;
    if (kind === 'entity') return 3;
    if (kind === 'anchor') return 4;
    if (hierarchyContext?.chunkId) return 4;
    return target.structuralRole === 'root' ? 1 : target.structuralRole === 'spine' ? 2 : 4;
}

function siegelMatrixCells(target: GraphRebuildEmbeddingTarget, lane: string, depth: number): number[] {
    const source = `${target.id}:${lane}:${depth}:${target.parentIds?.join('|') || ''}`;
    return Array.from({ length: 6 }, (_, index) => unitHash(`${source}:${index}`));
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
    const kind = targetRenderKind(target);
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
    post: GraphRebuildEmbeddingTargetPostProcess,
    hierarchyContext?: TargetHierarchyContext,
    capsDocumentDirections?: Map<string, CapsVec3>,
): Record<string, unknown> {
    const lane = post.productLaneFeatures;
    const region = post.productTopologyRegion;
    const radius = Math.max(0.001, Math.hypot(point.x, point.y, point.z));
    const depth = Math.max(0, Math.min(1, 1 - lane.semanticDepth));
    const scale = 0.22 + depth * 0.66;
    const treeKind = productFiberKind(post.clusterRole, region.laneKind);
    const parentNodeId = post.medoidTargetId && post.medoidTargetId !== target.id ? post.medoidTargetId : null;
    const supportNoteIds = capsSupportNoteIds(target, hierarchyContext);
    const supportChunkIds = capsSupportChunkIds(target, hierarchyContext);
    const capId = productCapId(target, region.id, hierarchyContext, supportNoteIds);
    const parentId = productCapParentId(target, parentNodeId, hierarchyContext);
    const level = productRegionLevel(target, post);
    const specificity = productHierarchySpecificity(target, post);
    const ambiguity = productHierarchyAmbiguity(post);
    const capDirection = capsDirectionForTarget(target, point, hierarchyContext, supportNoteIds, capsDocumentDirections);
    return {
        geometry: 'hierarchy_caps_v1',
        klein: [
            (point.x / radius) * scale,
            (point.y / radius) * scale,
            (point.z / radius) * scale,
            lane.fiberPhase,
        ],
        capId,
        capDirection: [capDirection.x, capDirection.y, capDirection.z],
        capPhase: lane.fiberPhase,
        shellRadius: productCapShellRadius(target, specificity, ambiguity),
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
            level,
            pathKey: `${capId}/${parentId || 'root'}/${target.id}`,
        }, {
            treeId: `product-lane:${region.laneKind}`,
            treeKind: region.laneKind,
            parentNodeId: parentId,
            level,
            pathKey: `product-lane:${region.laneKind}/${post.clusterId}/${target.id}`,
        }],
    };
}

function productCapId(
    target: GraphRebuildEmbeddingTarget,
    fallback: string,
    hierarchyContext: TargetHierarchyContext | undefined,
    supportNoteIds: string[],
): string {
    const kind = displayKind(target.kind);
    const noteId = target.noteId || hierarchyContext?.noteId || supportNoteIds[0];
    if (kind === 'note' && noteId) return `document:${noteId}`;
    if (kind === 'structure-root' && noteId) return `document:${noteId}:root:${capsStructureRootKey(target)}`;
    if (kind === 'chunk' && noteId) return `document:${noteId}:chunks`;
    if (kind === 'entity') {
        const entityId = target.entityId || target.sourceId;
        return supportNoteIds.length > 1
            ? `entity:${entityId}:docs:${capsStableToken(supportNoteIds.join('|'))}`
            : noteId ? `document:${noteId}:entities` : `entity:${entityId}`;
    }
    if (kind === 'event' && noteId) return `document:${noteId}:events`;
    if ((kind === 'temporal-fact' || kind === 'causal-fact') && noteId) return `document:${noteId}:${kind}`;
    if ((kind === 'graph-fact' || kind === 'memory-state') && noteId) return `document:${noteId}:facts`;
    if (noteId) return `document:${noteId}:signals`;
    return fallback;
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
    documentDirections?: Map<string, CapsVec3>,
): CapsVec3 {
    const kind = displayKind(target.kind);
    const noteId = target.noteId || hierarchyContext?.noteId || supportNoteIds[0];
    const fallback = capsNormalize(point, capsStableVector(target.id));
    const docDirection = capsAverageDocumentDirections(supportNoteIds.length ? supportNoteIds : noteId ? [noteId] : [], documentDirections, fallback);
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
            [docDirection, 0.68],
            [capsStableVector(target.chunkId || target.sourceId), 0.22],
            [fallback, 0.1],
        ]), docDirection);
    }
    if (kind === 'entity') {
        return capsNormalize(capsWeighted([
            [docDirection, supportNoteIds.length > 1 ? 0.7 : 0.58],
            [capsLaneDirection('identity'), 0.18],
            [fallback, supportNoteIds.length > 1 ? 0.12 : 0.24],
            [capsStableVector(target.entityId || target.sourceId), 0.08],
        ]), docDirection);
    }
    return capsNormalize(capsWeighted([
        [docDirection, 0.52],
        [capsLaneDirection(target.lane || kind), 0.24],
        [fallback, 0.24],
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

function capsSupportNoteIds(target: GraphRebuildEmbeddingTarget, context?: TargetHierarchyContext): string[] {
    const out = new Set<string>(context?.supportNoteIds || []);
    if (context?.noteId) out.add(context.noteId);
    if (target.noteId) out.add(target.noteId);
    for (const parentId of target.parentIds || []) {
        const noteId = parentId.match(/^embed:note:(.+)$/)?.[1]
            || parentId.match(/^embed:structure-root:([^:]+):/)?.[1];
        if (noteId) out.add(noteId);
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

function capsStableToken(value: string): string {
    return Math.round(unitHash(value) * 0xffffff).toString(36);
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
    if (target.kind === 'entity' && chunkId) return `embed:chunk:${chunkId}`;
    if (target.kind === 'entity' && noteId) return firstParentWithPrefix(parents, `embed:structure-root:${noteId}:identity`) || `embed:note:${noteId}`;
    if (target.kind === 'anchor' && target.entityId) return `embed:entity:${target.entityId}`;
    if (target.kind === 'anchor' && chunkId) return `embed:chunk:${chunkId}`;
    if (parents.length) return parents[0];
    return fallback;
}

function productCapShellRadius(
    target: GraphRebuildEmbeddingTarget,
    specificity: number,
    ambiguity: number,
): number {
    const lane = target.lane || 'unknown';
    const kind = displayKind(target.kind);
    let radius = 1.28;
    if (kind === 'note') radius = 2.08;
    else if (kind === 'structure-root') radius = 1.92;
    else if (kind === 'chunk' || lane === 'chunk_spine') radius = 1.66;
    else if (kind === 'entity' || lane === 'entity_anchor') radius = 1.42;
    else if (lane === 'document_spine') radius = 1.72;
    else if (lane === 'event_identity' || lane === 'temporal_fact' || lane === 'causal_fact') radius = 1.24;
    else if (lane === 'relationship_fact') radius = 1.16;
    else if (lane === 'memory_state') radius = 1.08;
    else if (lane === 'cooccurrence_weak') radius = 1.02;
    else if (lane === 'anchor_evidence') radius = 0.92;
    const confidence = targetConfidence(target);
    const confidenceDrop = lane === 'document_spine' ? 0.08 : 0.24;
    radius -= (1 - confidence) * confidenceDrop;
    radius += (specificity - 0.72) * 0.08;
    radius -= ambiguity * 0.08;
    const [min, max] = productCapShellBand(target);
    return clampRange(radius, min, max);
}

function productCapShellBand(target: GraphRebuildEmbeddingTarget): [number, number] {
    const lane = target.lane || 'unknown';
    const kind = displayKind(target.kind);
    if (kind === 'note') return [2.02, 2.12];
    if (kind === 'structure-root') return [1.86, 1.98];
    if (kind === 'chunk' || lane === 'document_spine' || lane === 'chunk_spine') return [1.56, 1.74];
    if (kind === 'entity' || lane === 'entity_anchor') return [1.34, 1.52];
    if (lane === 'event_identity' || lane === 'temporal_fact' || lane === 'causal_fact') return [1.14, 1.34];
    if (lane === 'relationship_fact') return [1.08, 1.26];
    if (lane === 'memory_state') return [0.98, 1.18];
    if (lane === 'cooccurrence_weak') return [0.92, 1.12];
    if (lane === 'anchor_evidence') return [0.78, 1.0];
    return [0.54, 2.12];
}

function productHierarchySpecificity(
    target: GraphRebuildEmbeddingTarget,
    post: GraphRebuildEmbeddingTargetPostProcess,
): number {
    const kind = displayKind(target.kind);
    let base = 0.58;
    if (kind === 'note') base = 0.22;
    else if (kind === 'structure-root') base = 0.42;
    else if (kind === 'chunk' || kind === 'anchor') base = 0.9;
    else if (kind === 'entity') base = 0.82;
    else if (kind === 'event' || kind === 'temporal-fact' || kind === 'causal-fact') base = 0.74;
    else if (kind === 'graph-fact' || kind === 'memory-state') base = 0.64;
    const role = post.productTopologyRegion.role;
    const roleBoost = role === 'outlier' ? 0.14 : role === 'boundary' ? 0.08 : role === 'bridge' ? 0.05 : role === 'core' ? -0.04 : 0;
    return clamp01(base + roleBoost + post.productLaneFeatures.semanticDepth * 0.08);
}

function productHierarchyAmbiguity(post: GraphRebuildEmbeddingTargetPostProcess): number {
    const role = post.productTopologyRegion.role;
    const roleBoost = role === 'outlier' ? 0.22 : role === 'bridge' ? 0.12 : role === 'boundary' ? 0.08 : 0;
    return clamp01(post.productLaneFeatures.clusterRadius * 0.52 + post.outlierScore * 0.28 + roleBoost);
}

function productRegionLevel(target: GraphRebuildEmbeddingTarget, post: GraphRebuildEmbeddingTargetPostProcess): number {
    const kind = displayKind(target.kind);
    if (target.lane === 'document_spine' && kind === 'note') return 0;
    if (kind === 'structure-root') return 1;
    if (target.lane === 'document_spine' || target.lane === 'chunk_spine' || kind === 'chunk') return 2;
    if (target.lane === 'entity_anchor' || kind === 'entity') return 3;
    if (target.lane === 'anchor_evidence' || kind === 'anchor') return 4;
    if (target.lane === 'relationship_fact' || target.lane === 'event_identity' || target.lane === 'temporal_fact' || target.lane === 'causal_fact') return 3;
    if (target.lane === 'memory_state' || target.lane === 'cooccurrence_weak') return 4;
    const role = post.productTopologyRegion.role;
    if (post.medoidTargetId === post.targetId && role === 'core') return 0;
    if (role === 'core') return 1;
    if (role === 'backbone') return 1;
    if (role === 'bridge') return 2;
    if (role === 'boundary') return 3;
    return 4;
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
    const add = (id: string, sourceId: string, targetId: string, type: string, confidence: number) => {
        if (sourceId === targetId) return;
        edges.push({ id, sourceId, targetId, type, confidence });
    };

    for (const chunk of snapshot.chunks) {
        add(`embed:note-chunk:${chunk.id}`, `embed:note:${chunk.noteId}`, `embed:chunk:${chunk.id}`, 'note-chunk', 0.9);
    }
    const targetIds = new Set(snapshot.embeddingTargets.map((target) => target.id));
    for (const target of snapshot.embeddingTargets) {
        for (const parentId of target.parentIds || []) {
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
    return dedupeEdges(edges);
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
        if (kind === 'document') return `embed:note:${sourceId}`;
        if (kind === 'chunk') return `embed:chunk:${sourceId}`;
        if (kind === 'evidence' || kind === 'sourceSpan') return `embed:anchor:${sourceId}`;
        if (kind === 'entity') return `embed:entity:${sourceId}`;
        if (kind === 'event') return `embed:event:${sourceId}`;
        if (kind === 'state') return `embed:memory:${sourceId}`;
    }
    if (prefix === 'fact') {
        if (kind === 'relationship') return `embed:graph-fact:${sourceId}`;
        if (kind === 'temporal') return `embed:temporalFact:${sourceId}`;
        if (kind === 'causal') return `embed:causalFact:${sourceId}`;
        if (kind === 'memory') return `embed:memory:${sourceId}`;
    }
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

function displayKind(kind: string): string {
    return String(kind || 'target').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

function normalizeHopfToken(value: string): string {
    return String(value || 'unknown').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
}

function targetRenderKind(target: GraphRebuildEmbeddingTarget): string {
    if (displayKind(target.kind) === 'entity' && target.entityKind) {
        return displayKind(target.entityKind);
    }
    return displayKind(target.kind);
}

function targetColorHsl(target: GraphRebuildEmbeddingTarget): string {
    const kind = displayKind(target.kind);
    if (kind === 'graph-fact') {
        return relationHslFromText(target.label, target.text, target.sourceId) || kindHsl(kind);
    }
    if (kind === 'entity' && target.entityKind) {
        return entityColorStore.getRawHsl(target.entityKind.toUpperCase() as any);
    }
    return kindHsl(kind);
}

function kindHsl(kind: string): string {
    switch (displayKind(kind)) {
        case 'note': return entityColorStore.getRawGraphNodeHsl('document');
        case 'structure-root': return entityColorStore.getRawGraphNodeHsl('document');
        case 'chunk': return entityColorStore.getRawGraphNodeHsl('chunk');
        case 'entity': return '282 70% 62%';
        case 'anchor': return entityColorStore.getRawGraphNodeHsl('anchor');
        case 'graph-fact': return entityColorStore.getRawGraphNodeHsl('graphFact');
        case 'event': return entityColorStore.getRawGraphNodeHsl('eventNode');
        case 'temporal-fact': return entityColorStore.getRawGraphNodeHsl('temporalFact');
        case 'causal-fact': return entityColorStore.getRawGraphNodeHsl('causalFact');
        case 'memory-state': return entityColorStore.getRawGraphNodeHsl('memoryState');
        default: return '220 12% 58%';
    }
}

function graphRebuildGeometryVersion(manifold: AtlasManifoldMode): string {
    if (manifold === 'hopf') return 'graph_rebuild_hopf_v1';
    if (manifold === 'lorentz') return 'graph_rebuild_hierarchy_caps_v1';
    if (manifold === 'product') return 'graph_rebuild_product_lorentz_hopf_v1';
    if (manifold === 'siegel') return 'graph_rebuild_siegel_finsler_v1';
    return 'graph_rebuild_hybrid_v1';
}

function graphRebuildProjectionLabel(manifold: AtlasManifoldMode): string {
    if (manifold === 'lorentz') return 'hierarchy caps';
    if (manifold === 'siegel') return 'siegel-finsler';
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
