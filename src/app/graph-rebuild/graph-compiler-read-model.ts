import type {
    GraphModelV2Atom,
    GraphModelV2AtomKind,
    GraphModelV2FactBundle,
    GraphModelV2FactFamily,
    GraphModelV2FactRole,
    GraphModelV2ProjectionEdge,
    GraphModelV2RelationFact,
    GraphModelV2Snapshot,
    GraphModelV2StyleTag,
    GraphModelV2StyleTagKind,
} from './graph-model-v2';
import type {
    GraphRebuildAdjudicationStatus,
    GraphRebuildEdge,
    GraphRebuildScopeKind,
    GraphRebuildSignalTargetLane,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export type GraphCompilerSource = 'rust' | 'typescriptCompatibility';
export type GraphCompilerFactLane =
    | 'documentSpine'
    | 'chunkSpine'
    | 'entityAnchor'
    | 'relationshipFact'
    | 'cooccurrenceWeak'
    | 'eventIdentity'
    | 'temporalFact'
    | 'causalFact'
    | 'memoryState'
    | 'entityLinker'
    | 'anchorEvidence';
export type GraphCompilerAtomKind =
    | 'document'
    | 'documentRoot'
    | 'laneRoot'
    | 'chunk'
    | 'frame'
    | 'sourceSpan'
    | 'evidenceAnchor'
    | 'entity'
    | 'concept'
    | 'event'
    | 'state'
    | 'claim'
    | 'relationFact'
    | 'timeAnchor'
    | 'root';
export type GraphCompilerEvidenceKind =
    | 'surfaceHit'
    | 'mentionPacket'
    | 'cueHit'
    | 'lensFrame'
    | 'sourceSpan'
    | 'userAccepted'
    | 'modelVote'
    | 'adjudicationVote'
    | 'eventReference'
    | 'calendarRegistry'
    | 'mentionGraphEdge';
export type GraphCompilerEvidenceBundleKind =
    | 'span'
    | 'frame'
    | 'neighborhood'
    | 'semanticSimilarity'
    | 'shadowIdentity';
export type GraphCompilerBundleCompressionModel = 'jinaV5Nano' | string;
export type GraphCompilerBundleRerankSource = 'gliClass' | string;
export type GraphCompilerGraphPrototypeFamily =
    | 'EntityKind'
    | 'RelationFamily'
    | 'EvidenceAuthority'
    | 'GraphStage'
    | 'ConceptDomain'
    | string;

export interface GraphCompilerFactBundleCompression {
    model: GraphCompilerBundleCompressionModel;
    clusterId: string;
    canonicalBundleId: string;
    duplicateOfBundleId?: string | null;
    outlierScore: number;
    neighborCount: number;
    semanticRank: number;
    rerankScore?: number | null;
    rerankSource?: GraphCompilerBundleRerankSource | null;
    signals: string[];
}

export interface GraphCompilerFactBundlePrototypeScore {
    prototypeId: string;
    family: GraphCompilerGraphPrototypeFamily;
    score: number;
    probability: number;
}

export interface GraphCompilerFactBundleCommitment {
    family: GraphCompilerGraphPrototypeFamily;
    topPrototypeId: string;
    topLabel: string;
    topScore: number;
    topProbability: number;
    secondPrototypeId?: string | null;
    secondScore?: number | null;
    secondProbability?: number | null;
    margin: number;
    entropy: number;
    ambiguityScore: number;
    classificationConfidence: number;
    promotionReady: boolean;
    radialStrength: number;
    topKScores: GraphCompilerFactBundlePrototypeScore[];
}

export interface GraphCompilerAtom {
    id: string;
    kind: GraphCompilerAtomKind;
    sourceId: string;
    label: string;
    noteId?: string | null;
    chunkId?: string | null;
    entityId?: string | null;
    evidenceIds: string[];
}

export interface GraphCompilerEvidenceAnchor {
    id: string;
    kind: GraphCompilerEvidenceKind;
    noteId?: string | null;
    chunkId?: string | null;
    sourceRange?: { start: number; end: number } | null;
    sourceId: string;
    confidence: number;
}

export interface GraphCompilerFactLike {
    id: string;
    lane: GraphCompilerFactLane;
    bundleKind?: GraphCompilerEvidenceBundleKind | string;
    groupKey?: string;
    predicate: string;
    sourceRecordId: string;
    status: GraphRebuildAdjudicationStatus | 'prepared' | string;
    evidenceIds: string[];
    confidence: number;
    compression?: GraphCompilerFactBundleCompression | null;
    commitment?: GraphCompilerFactBundleCommitment | null;
}

export type GraphCompilerFactBundle = GraphCompilerFactLike;
export type GraphCompilerRelationFact = GraphCompilerFactLike;

export interface GraphCompilerFactRole {
    factId: string;
    role: string;
    atomId: string;
    confidence: number;
}

export interface GraphCompilerProjectedEdge {
    id: string;
    sourceId: string;
    targetId: string;
    edgeType: string;
    projectionKind: string;
    sourceFactId?: string | null;
    sourceBundleId?: string | null;
    confidence: number;
}

export interface GraphCompileCounters {
    atoms: number;
    evidenceAnchors: number;
    bundles: number;
    facts: number;
    roles: number;
    projectedEdges: number;
    invariantFailures: number;
}

export interface GraphRootReceipt extends GraphCompileCounters {
    lane: GraphCompilerFactLane;
}

export interface GraphCompileReceipts {
    roots: GraphRootReceipt[];
    counters: GraphCompileCounters;
    invariantFailures: string[];
}

export interface GraphCompilerOutput {
    schemaVersion: 'phoenix-graph-compiler/v1' | string;
    scopeKind: GraphRebuildScopeKind | string;
    scopeId: string;
    builtAt: number;
    atoms: GraphCompilerAtom[];
    evidenceAnchors: GraphCompilerEvidenceAnchor[];
    bundles: GraphCompilerFactBundle[];
    facts: GraphCompilerRelationFact[];
    roles: GraphCompilerFactRole[];
    projectedEdges: GraphCompilerProjectedEdge[];
    receipts: GraphCompileReceipts;
}

export interface GraphCompilerProjectedUiEdge extends Omit<GraphRebuildEdge, 'type'> {
    type?: string;
    edgeType?: string;
}

export interface GraphCompilerDualWriteSidecar {
    factGraph: GraphCompilerOutput;
    projectedUiGraph?: GraphCompilerProjectedUiEdge[];
    receipts?: GraphCompileReceipts;
}

const COMPILER_LANE_TO_SIGNAL: Record<GraphCompilerFactLane, GraphRebuildSignalTargetLane> = {
    documentSpine: 'document_spine',
    chunkSpine: 'chunk_spine',
    entityAnchor: 'entity_anchor',
    relationshipFact: 'relationship_fact',
    cooccurrenceWeak: 'cooccurrence_weak',
    eventIdentity: 'event_identity',
    temporalFact: 'temporal_fact',
    causalFact: 'causal_fact',
    memoryState: 'memory_state',
    entityLinker: 'entity_linker',
    anchorEvidence: 'anchor_evidence',
};

export function attachGraphCompilerReadModels(
    snapshot: GraphRebuildSnapshot,
    sidecar: GraphCompilerDualWriteSidecar,
    source: GraphCompilerSource,
): GraphRebuildSnapshot {
    snapshot.graphCompiler = sidecar.factGraph;
    snapshot.graphCompileReceipts = sidecar.receipts || sidecar.factGraph.receipts;
    snapshot.graphCompilerSource = source;
    snapshot.projectedUiGraph = sidecar.projectedUiGraph || projectUiGraphFromCompilerOutput(sidecar.factGraph);
    snapshot.graphModelV2 = buildGraphModelV2FromCompilerOutput(snapshot.id, sidecar.factGraph);
    return snapshot;
}

export function buildGraphModelV2FromCompilerOutput(
    sourceSnapshotId: string,
    output: GraphCompilerOutput,
): GraphModelV2Snapshot {
    const styleTags: GraphModelV2StyleTag[] = [];
    const atoms = graphModelAtoms(output, styleTags);
    const bundles = output.bundles.map((bundle) => graphModelBundle(bundle, styleTags));
    const facts = output.facts.map((fact) => graphModelFact(fact, styleTags));
    const roles = output.roles.map((role) => ({
        factId: role.factId,
        role: graphModelRole(role.role),
        targetAtomId: role.atomId,
        confidence: role.confidence,
    }));
    const projectionEdges = dedupeProjectionEdges(output.projectedEdges.map(graphModelProjectionEdge));
    const laneRoots = graphModelLaneRoots(output.scopeId, atoms, bundles, facts, styleTags);
    const roleCounts = roleCountsByFact(roles);
    return {
        schemaVersion: 'phoenix-graph-model/v2',
        sourceSnapshotId,
        builtAt: output.builtAt,
        atoms,
        laneRoots,
        bundles,
        facts,
        roles,
        styleTags,
        projectionEdges,
        counters: {
            atoms: atoms.length,
            laneRoots: laneRoots.length,
            bundles: bundles.length,
            facts: facts.length,
            roles: roles.length,
            styleTags: styleTags.length,
            projectionEdges: projectionEdges.length,
            stagedCooccurrenceBundles: bundles.filter((bundle) => bundle.family === 'cooccurrence').length,
            weakCooccurrenceFacts: facts.filter((fact) => fact.family === 'cooccurrence' && fact.lane === 'cooccurrence_weak').length,
            hyperedgeFacts: facts.filter((fact) => (roleCounts.get(fact.id) || 0) > 2).length,
        },
    };
}

export function projectUiGraphFromCompilerOutput(output: GraphCompilerOutput): GraphCompilerProjectedUiEdge[] {
    const edges: GraphCompilerProjectedUiEdge[] = [];
    for (const edge of output.projectedEdges) {
        const sourceId = entityIdFromAtom(edge.sourceId);
        const targetId = entityIdFromAtom(edge.targetId);
        if (!sourceId || !targetId) continue;
        edges.push({
            id: edge.id,
            sourceId,
            targetId,
            type: edge.edgeType,
            edgeType: edge.edgeType,
            weight: Math.round(clamp(edge.confidence, 0, 1) * 1000),
            confidence: edge.confidence,
            evidenceAnchorIds: [edge.sourceFactId, edge.sourceBundleId].filter(Boolean) as string[],
            scopeKeys: [],
            noteIds: [],
        });
    }
    return edges;
}

function graphModelAtoms(output: GraphCompilerOutput, styleTags: GraphModelV2StyleTag[]): GraphModelV2Atom[] {
    const atoms: GraphModelV2Atom[] = [];
    const seen = new Set<string>();
    for (const atomRow of output.atoms) pushGraphModelAtom(atoms, seen, compilerAtomToGraphModelAtom(atomRow), styleTags);
    for (const evidence of output.evidenceAnchors) {
        pushGraphModelAtom(atoms, seen, {
            id: evidence.id,
            kind: 'evidenceAnchor',
            sourceId: evidence.sourceId,
            label: evidenceLabel(evidence),
            noteId: evidence.noteId || undefined,
            chunkId: evidence.chunkId || undefined,
            evidenceIds: [evidence.id],
        }, styleTags);
    }
    return atoms;
}

function compilerAtomToGraphModelAtom(atomRow: GraphCompilerAtom): GraphModelV2Atom | null {
    const kind = graphModelAtomKind(atomRow.kind);
    if (!kind) return null;
    return { id: atomRow.id, kind, sourceId: atomRow.entityId || atomRow.sourceId, label: atomRow.label, noteId: atomRow.noteId || undefined, chunkId: atomRow.chunkId || undefined, entityKind: atomRow.kind === 'concept' ? 'CONCEPT' : atomRow.kind === 'entity' ? 'ENTITY' : undefined, evidenceIds: atomRow.evidenceIds || [] };
}

function pushGraphModelAtom(atoms: GraphModelV2Atom[], seen: Set<string>, atomRow: GraphModelV2Atom | null, styleTags: GraphModelV2StyleTag[]): void {
    if (!atomRow || seen.has(atomRow.id)) return;
    seen.add(atomRow.id);
    atoms.push(atomRow);
    styleTags.push(styleTag(atomRow.id, 'atom', 'structuralKind', atomRow.kind));
}

function graphModelFact(fact: GraphCompilerRelationFact, styleTags: GraphModelV2StyleTag[]): GraphModelV2RelationFact {
    const family = factFamily(fact.predicate);
    styleTags.push(styleTag(fact.id, 'fact', 'relationFamily', family), styleTag(fact.id, 'fact', 'stage', fact.status));
    return { id: fact.id, family, relationType: fact.predicate, lane: signalLane(fact.lane), status: graphStatus(fact.status), confidence: fact.confidence, evidenceIds: fact.evidenceIds, sourceRecordId: fact.sourceRecordId };
}

function graphModelBundle(bundle: GraphCompilerFactBundle, styleTags: GraphModelV2StyleTag[]): GraphModelV2FactBundle {
    const family = factFamily(bundle.predicate);
    styleTags.push(styleTag(bundle.id, 'bundle', 'relationFamily', family), styleTag(bundle.id, 'bundle', 'stage', bundle.status));
    return { id: bundle.id, family, relationType: bundle.predicate, lane: signalLane(bundle.lane), bundleKind: bundle.bundleKind, groupKey: bundle.groupKey, status: graphBundleStatus(bundle.status), confidence: bundle.confidence, evidenceIds: bundle.evidenceIds, sourceRecordId: bundle.sourceRecordId, compression: bundle.compression || undefined, commitment: bundle.commitment || undefined };
}

function graphModelProjectionEdge(edge: GraphCompilerProjectedEdge): GraphModelV2ProjectionEdge {
    return { id: edge.id, sourceId: edge.sourceId, targetId: edge.targetId, edgeType: edge.edgeType, projectionKind: graphProjectionKind(edge.projectionKind), sourceFactId: edge.sourceFactId || undefined, sourceBundleId: edge.sourceBundleId || undefined, confidence: edge.confidence };
}

function graphModelLaneRoots(scopeId: string, atoms: GraphModelV2Atom[], bundles: GraphModelV2FactBundle[], facts: GraphModelV2RelationFact[], styleTags: GraphModelV2StyleTag[]) {
    const targets = new Map<GraphRebuildSignalTargetLane, Set<string>>();
    const add = (lane: GraphRebuildSignalTargetLane, id: string) => {
        const bucket = targets.get(lane) || new Set<string>();
        bucket.add(id);
        targets.set(lane, bucket);
    };
    for (const atomRow of atoms) add(laneForAtom(atomRow.kind), atomRow.id);
    for (const bundle of bundles) add(bundle.lane, bundle.id);
    for (const fact of facts) add(fact.lane, fact.id);
    const roots = [...targets.entries()].map(([lane, ids]) => ({ id: `lane:${scopeId}:${lane}`, lane, scopeId, label: lane.replace(/_/g, ' '), targetIds: [...ids].sort() })).sort((left, right) => left.lane.localeCompare(right.lane));
    for (const root of roots) styleTags.push(styleTag(root.id, 'lane', 'stage', root.lane));
    return roots;
}

function signalLane(lane: GraphCompilerFactLane): GraphRebuildSignalTargetLane {
    return COMPILER_LANE_TO_SIGNAL[lane] || 'relationship_fact';
}

function graphModelAtomKind(kind: GraphCompilerAtomKind): GraphModelV2AtomKind | null {
    return kind === 'root' ? null : kind;
}

function graphModelRole(roleName: string): GraphModelV2FactRole['role'] {
    if (['subject', 'source', 'target', 'actor', 'speaker', 'listener', 'cause', 'effect', 'object', 'location', 'time', 'state', 'leftMention', 'rightMention', 'evidence'].includes(roleName)) return roleName as GraphModelV2FactRole['role'];
    return 'evidence';
}

function graphProjectionKind(kind: string): GraphModelV2ProjectionEdge['projectionKind'] {
    if (kind === 'factRole' || kind === 'structure') return kind;
    return 'legacyBinary';
}

function graphStatus(status: string): GraphRebuildAdjudicationStatus {
    if (status === 'accepted' || status === 'review' || status === 'rejected') return status;
    return 'review';
}

function graphBundleStatus(status: string): GraphModelV2FactBundle['status'] {
    if (status === 'accepted' || status === 'review' || status === 'rejected' || status === 'prepared') return status;
    return 'review';
}

function laneForAtom(kind: GraphModelV2AtomKind): GraphRebuildSignalTargetLane {
    if (kind === 'document' || kind === 'documentRoot' || kind === 'laneRoot') return 'document_spine';
    if (kind === 'chunk') return 'chunk_spine';
    if (kind === 'entity' || kind === 'concept') return 'entity_anchor';
    if (kind === 'event' || kind === 'timeAnchor') return 'event_identity';
    if (kind === 'state') return 'memory_state';
    if (kind === 'relationFact' || kind === 'claim') return 'relationship_fact';
    if (kind === 'frame') return 'anchor_evidence';
    return 'anchor_evidence';
}

function factFamily(type: string): GraphModelV2FactFamily {
    const value = type.toLowerCase();
    if (/co.?occurs?|co.?occurrence|anchored/.test(value)) return 'cooccurrence';
    if (/observ|watch|notice|saw/.test(value)) return 'observation';
    if (/communicat|comment|said|told|warn/.test(value)) return 'communication';
    if (/authority|command|service/.test(value)) return 'authority';
    if (/approv|accept|agree/.test(value)) return 'approval';
    if (/family|father|daughter|house/.test(value)) return 'family';
    if (/intim|close|kiss|hand/.test(value)) return 'intimacy';
    if (/transfer|receive|gave|handed/.test(value)) return 'transfer';
    if (/caus|explain/.test(value)) return 'causal';
    if (/before|after|during|temporal|time/.test(value)) return 'temporal';
    return value ? 'relationship' : 'unknown';
}

function styleTag(targetId: string, targetType: GraphModelV2StyleTag['targetType'], tagKind: GraphModelV2StyleTagKind, value: string): GraphModelV2StyleTag {
    return { targetId, targetType, tagKind, value };
}

function evidenceLabel(evidence: GraphCompilerEvidenceAnchor): string {
    return evidence.sourceRange ? `${evidence.kind} ${evidence.sourceRange.start}-${evidence.sourceRange.end}` : `${evidence.kind} ${evidence.sourceId}`;
}

function entityIdFromAtom(id: string): string | null {
    return id.startsWith('atom:entity:') ? id.slice('atom:entity:'.length) : null;
}

function dedupeProjectionEdges(edges: GraphModelV2ProjectionEdge[]): GraphModelV2ProjectionEdge[] {
    const seen = new Set<string>();
    return edges.filter((edge) => {
        const key = `${edge.sourceId}|${edge.targetId}|${edge.edgeType}|${edge.projectionKind}|${edge.sourceFactId || ''}|${edge.sourceBundleId || ''}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function roleCountsByFact(roles: GraphModelV2FactRole[]): Map<string, number> {
    const counts = new Map<string, number>();
    for (const roleRow of roles) counts.set(roleRow.factId, (counts.get(roleRow.factId) || 0) + 1);
    return counts;
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}
