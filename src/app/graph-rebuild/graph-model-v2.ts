import type {
    GraphRebuildAdjudicationStatus,
    GraphRebuildCausalEdge,
    GraphRebuildEdge,
    GraphRebuildEmbeddingTarget,
    GraphRebuildMemoryState,
    GraphRebuildRelationship,
    GraphRebuildSignalTargetLane,
    GraphRebuildSnapshot,
    GraphRebuildTemporalEdge,
} from './graph-rebuild-snapshot';

export type GraphModelV2AtomKind =
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
    | 'timeAnchor';

export type GraphModelV2FactFamily =
    | 'cooccurrence'
    | 'observation'
    | 'communication'
    | 'authority'
    | 'approval'
    | 'family'
    | 'intimacy'
    | 'transfer'
    | 'relationship'
    | 'temporal'
    | 'causal'
    | 'memory'
    | 'unknown';

export type GraphModelV2RoleKind =
    | 'subject'
    | 'source'
    | 'target'
    | 'actor'
    | 'speaker'
    | 'listener'
    | 'cause'
    | 'effect'
    | 'object'
    | 'agent'
    | 'bearer'
    | 'experiencer'
    | 'topic'
    | 'recipient'
    | 'theme'
    | 'location'
    | 'time'
    | 'manner'
    | 'instrument'
    | 'purpose'
    | 'condition'
    | 'state'
    | 'leftMention'
    | 'rightMention'
    | 'evidence';

export type GraphModelV2StyleTagKind =
    | 'entityFamily'
    | 'relationFamily'
    | 'storySignal'
    | 'structuralKind'
    | 'stage';

export interface GraphModelV2Atom {
    id: string;
    kind: GraphModelV2AtomKind;
    sourceId: string;
    label: string;
    noteId?: string;
    chunkId?: string;
    entityKind?: string;
    evidenceIds: string[];
}

export interface GraphModelV2LaneRoot {
    id: string;
    lane: GraphRebuildSignalTargetLane;
    scopeId: string;
    label: string;
    targetIds: string[];
}

export interface GraphModelV2RelationFact {
    id: string;
    family: GraphModelV2FactFamily;
    relationType: string;
    lane: GraphRebuildSignalTargetLane;
    status: GraphRebuildAdjudicationStatus;
    confidence: number;
    evidenceIds: string[];
    sourceRecordId: string;
    semanticSituationId?: string;
    semanticFrame?: string;
    factuality?: string;
    stateIntervalIds?: string[];
    eventOrderingIds?: string[];
    temporalConflictIds?: string[];
}

export interface GraphModelV2FactBundleCompression {
    model: string;
    clusterId: string;
    canonicalBundleId: string;
    duplicateOfBundleId?: string | null;
    outlierScore: number;
    neighborCount: number;
    semanticRank: number;
    rerankScore?: number | null;
    rerankSource?: string | null;
    signals: string[];
}

export type GraphModelV2GraphPrototypeFamily =
    | 'EntityKind'
    | 'RelationFamily'
    | 'EvidenceAuthority'
    | 'GraphStage'
    | 'ConceptDomain'
    | string;

export interface GraphModelV2FactBundlePrototypeScore {
    prototypeId: string;
    family: GraphModelV2GraphPrototypeFamily;
    score: number;
    probability: number;
}

export interface GraphModelV2FactBundleCommitment {
    family: GraphModelV2GraphPrototypeFamily;
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
    topKScores: GraphModelV2FactBundlePrototypeScore[];
}

export interface GraphModelV2FactBundle {
    id: string;
    family: GraphModelV2FactFamily;
    relationType: string;
    lane: GraphRebuildSignalTargetLane;
    bundleKind?: string;
    groupKey?: string;
    status: GraphRebuildAdjudicationStatus | 'prepared';
    confidence: number;
    evidenceIds: string[];
    sourceRecordId: string;
    compression?: GraphModelV2FactBundleCompression;
    commitment?: GraphModelV2FactBundleCommitment;
}

export interface GraphModelV2FactRole {
    factId: string;
    role: GraphModelV2RoleKind;
    targetAtomId: string;
    confidence: number;
    semanticRole?: string;
    slotType?: string;
    required?: boolean;
    resolved?: boolean;
}

export interface GraphModelV2StyleTag {
    targetId: string;
    targetType: 'atom' | 'bundle' | 'fact' | 'role' | 'lane' | 'projectionEdge';
    tagKind: GraphModelV2StyleTagKind;
    value: string;
}

export interface GraphModelV2ProjectionEdge {
    id: string;
    sourceId: string;
    targetId: string;
    edgeType: string;
    projectionKind: 'legacyBinary' | 'factRole' | 'structure';
    sourceFactId?: string;
    sourceBundleId?: string;
    confidence: number;
}

export interface GraphModelV2Counters {
    atoms: number;
    laneRoots: number;
    bundles: number;
    facts: number;
    roles: number;
    styleTags: number;
    projectionEdges: number;
    stagedCooccurrenceBundles: number;
    weakCooccurrenceFacts: number;
    hyperedgeFacts: number;
}

export interface GraphModelV2Snapshot {
    schemaVersion: 'phoenix-graph-model/v2';
    sourceSnapshotId: string;
    builtAt: number;
    atoms: GraphModelV2Atom[];
    laneRoots: GraphModelV2LaneRoot[];
    bundles: GraphModelV2FactBundle[];
    facts: GraphModelV2RelationFact[];
    roles: GraphModelV2FactRole[];
    styleTags: GraphModelV2StyleTag[];
    projectionEdges: GraphModelV2ProjectionEdge[];
    counters: GraphModelV2Counters;
}

export function buildGraphModelV2Snapshot(snapshot: GraphRebuildSnapshot): GraphModelV2Snapshot {
    const atoms: GraphModelV2Atom[] = [];
    const laneTargets = new Map<GraphRebuildSignalTargetLane, Set<string>>();
    const facts: GraphModelV2RelationFact[] = [];
    const roles: GraphModelV2FactRole[] = [];
    const styleTags: GraphModelV2StyleTag[] = [];
    const projectionEdges: GraphModelV2ProjectionEdge[] = [];

    const addLaneTarget = (lane: GraphRebuildSignalTargetLane, id: string) => {
        let targets = laneTargets.get(lane);
        if (!targets) {
            targets = new Set<string>();
            laneTargets.set(lane, targets);
        }
        targets.add(id);
    };
    const addAtom = (atom: GraphModelV2Atom, lane: GraphRebuildSignalTargetLane, tags: GraphModelV2StyleTag[] = []) => {
        atoms.push(atom);
        addLaneTarget(lane, atom.id);
        styleTags.push(...tags);
    };

    for (const noteId of snapshot.noteIds) {
        addAtom({
            id: atomId('document', noteId),
            kind: 'document',
            sourceId: noteId,
            label: `Document ${noteId}`,
            noteId,
            evidenceIds: [],
        }, 'document_spine', [structuralTag(atomId('document', noteId), 'document')]);
    }
    for (const chunk of snapshot.chunks) {
        addAtom({
            id: atomId('chunk', chunk.id),
            kind: 'chunk',
            sourceId: chunk.id,
            label: `Chunk ${chunk.ordinal + 1}`,
            noteId: chunk.noteId,
            chunkId: chunk.id,
            evidenceIds: [],
        }, 'chunk_spine', [structuralTag(atomId('chunk', chunk.id), 'chunk')]);
    }
    for (const anchor of snapshot.entityAnchors) {
        const evidenceId = atomId('evidence', anchor.id);
        addAtom({
            id: atomId('sourceSpan', anchor.id),
            kind: 'sourceSpan',
            sourceId: anchor.id,
            label: anchor.surface,
            noteId: anchor.noteId,
            chunkId: anchor.chunkId,
            evidenceIds: [anchor.id],
        }, 'anchor_evidence', [structuralTag(atomId('sourceSpan', anchor.id), 'sourceSpan')]);
        addAtom({
            id: evidenceId,
            kind: 'evidenceAnchor',
            sourceId: anchor.id,
            label: anchor.surface,
            noteId: anchor.noteId,
            chunkId: anchor.chunkId,
            evidenceIds: [anchor.id],
        }, 'anchor_evidence', [structuralTag(evidenceId, 'evidenceAnchor')]);
    }
    for (const node of snapshot.nodes) {
        const id = atomId('entity', node.entityId);
        addAtom({
            id,
            kind: node.kind.toUpperCase() === 'CONCEPT' ? 'concept' : 'entity',
            sourceId: node.entityId,
            label: node.label,
            entityKind: node.kind,
            evidenceIds: node.anchorIds,
        }, 'entity_anchor', [styleTag(id, 'atom', 'entityFamily', node.kind)]);
    }
    for (const event of snapshot.events) {
        const id = atomId('event', event.id);
        addAtom({
            id,
            kind: 'event',
            sourceId: event.id,
            label: event.label,
            noteId: event.noteId,
            chunkId: event.chunkId,
            evidenceIds: event.evidenceAnchorIds,
        }, 'event_identity', [structuralTag(id, 'event')]);
    }
    for (const state of snapshot.memoryState) {
        const id = atomId('state', state.id);
        addAtom({
            id,
            kind: 'state',
            sourceId: state.id,
            label: state.key,
            noteId: state.noteId,
            evidenceIds: state.evidenceIds,
        }, 'memory_state', [styleTag(id, 'atom', 'storySignal', 'memoryState')]);
    }

    for (const relationship of snapshot.relationships) {
        addRelationshipFact(relationship, facts, roles, styleTags, projectionEdges, addLaneTarget);
    }
    for (const edge of snapshot.temporalEdges) {
        addTemporalFact(edge, 'temporal', facts, roles, styleTags, projectionEdges, addLaneTarget);
    }
    for (const edge of snapshot.causalEdges) {
        addTemporalFact(edge, 'causal', facts, roles, styleTags, projectionEdges, addLaneTarget);
    }
    for (const state of snapshot.memoryState) {
        addMemoryFact(state, facts, roles, styleTags, projectionEdges, addLaneTarget);
    }
    for (const edge of snapshot.edges) {
        addLegacyProjection(edge, projectionEdges);
    }
    for (const target of snapshot.embeddingTargets) {
        if (target.parentIds?.length) addEmbeddingParentProjections(target, projectionEdges);
    }

    const laneRoots = [...laneTargets.entries()]
        .map(([lane, ids]) => ({
            id: `lane:${snapshot.scopeId}:${lane}`,
            lane,
            scopeId: snapshot.scopeId,
            label: lane.replace(/_/g, ' '),
            targetIds: [...ids].sort(),
        }))
        .sort((left, right) => left.lane.localeCompare(right.lane));
    for (const lane of laneRoots) styleTags.push(styleTag(lane.id, 'lane', 'stage', lane.lane));

    const dedupedProjectionEdges = dedupeProjectionEdges(projectionEdges);
    const roleCounts = roleCountsByFact(roles);
    return {
        schemaVersion: 'phoenix-graph-model/v2',
        sourceSnapshotId: snapshot.id,
        builtAt: snapshot.builtAt,
        atoms,
        laneRoots,
        bundles: [],
        facts,
        roles,
        styleTags,
        projectionEdges: dedupedProjectionEdges,
        counters: {
            atoms: atoms.length,
            laneRoots: laneRoots.length,
            bundles: 0,
            facts: facts.length,
            roles: roles.length,
            styleTags: styleTags.length,
            projectionEdges: dedupedProjectionEdges.length,
            stagedCooccurrenceBundles: 0,
            weakCooccurrenceFacts: facts.filter((fact) => fact.family === 'cooccurrence' && fact.lane === 'cooccurrence_weak').length,
            hyperedgeFacts: facts.filter((fact) => (roleCounts.get(fact.id) || 0) > 2).length,
        },
    };
}

function addRelationshipFact(
    relationship: GraphRebuildRelationship,
    facts: GraphModelV2RelationFact[],
    roles: GraphModelV2FactRole[],
    styleTags: GraphModelV2StyleTag[],
    projectionEdges: GraphModelV2ProjectionEdge[],
    addLaneTarget: (lane: GraphRebuildSignalTargetLane, id: string) => void,
): void {
    const id = `fact:relationship:${relationship.id}`;
    const family = relationFamily(relationship.relationType);
    const lane = family === 'cooccurrence' ? 'cooccurrence_weak' : 'relationship_fact';
    facts.push({
        id,
        family,
        relationType: relationship.relationType,
        lane,
        status: relationship.status,
        confidence: relationship.confidence,
        evidenceIds: relationship.evidenceAnchorIds,
        sourceRecordId: relationship.id,
    });
    addLaneTarget(lane, id);
    styleTags.push(styleTag(id, 'fact', 'relationFamily', family), styleTag(id, 'fact', 'stage', relationship.status));
    pushRole(roles, id, 'source', atomId('entity', relationship.sourceEntityId), relationship.confidence);
    pushRole(roles, id, 'target', atomId('entity', relationship.targetEntityId), relationship.confidence);
    for (const evidenceId of relationship.evidenceAnchorIds) pushRole(roles, id, 'evidence', atomId('evidence', evidenceId), relationship.confidence);
    projectionEdges.push({
        id: `projection:fact-role:${relationship.id}:source`,
        sourceId: id,
        targetId: atomId('entity', relationship.sourceEntityId),
        edgeType: 'role:source',
        projectionKind: 'factRole',
        sourceFactId: id,
        confidence: relationship.confidence,
    }, {
        id: `projection:fact-role:${relationship.id}:target`,
        sourceId: id,
        targetId: atomId('entity', relationship.targetEntityId),
        edgeType: 'role:target',
        projectionKind: 'factRole',
        sourceFactId: id,
        confidence: relationship.confidence,
    });
}

function addTemporalFact(
    edge: GraphRebuildTemporalEdge | GraphRebuildCausalEdge,
    family: 'temporal' | 'causal',
    facts: GraphModelV2RelationFact[],
    roles: GraphModelV2FactRole[],
    styleTags: GraphModelV2StyleTag[],
    projectionEdges: GraphModelV2ProjectionEdge[],
    addLaneTarget: (lane: GraphRebuildSignalTargetLane, id: string) => void,
): void {
    const id = `fact:${family}:${edge.id}`;
    const lane: GraphRebuildSignalTargetLane = family === 'causal' ? 'causal_fact' : 'temporal_fact';
    const status = family === 'causal' ? causalGraphStatus(edge as GraphRebuildCausalEdge) : 'accepted';
    facts.push({ id, family, relationType: edge.relationType, lane, status, confidence: edge.confidence, evidenceIds: edge.evidenceIds, sourceRecordId: edge.id });
    addLaneTarget(lane, id);
    styleTags.push(styleTag(id, 'fact', 'relationFamily', family), styleTag(id, 'fact', 'stage', status));
    if (family === 'causal') {
        const causal = edge as GraphRebuildCausalEdge;
        styleTags.push(
            styleTag(id, 'fact', 'storySignal', `source:${causal.sourceKind}`),
            styleTag(id, 'fact', 'storySignal', `evidence:${causal.evidenceClass}`),
            styleTag(id, 'fact', 'storySignal', `modality:${causal.modality}`),
            styleTag(id, 'fact', 'storySignal', `polarity:${causal.polarity}`),
        );
    }
    pushRole(roles, id, family === 'causal' ? 'cause' : 'source', atomId('event', edge.sourceId), edge.confidence);
    pushRole(roles, id, family === 'causal' ? 'effect' : 'target', atomId('event', edge.targetId), edge.confidence);
    for (const evidenceId of causalEvidenceRoleIds(edge, family)) pushRole(roles, id, 'evidence', atomId('evidence', evidenceId), edge.confidence);
    projectionEdges.push({ id: `projection:${family}:${edge.id}`, sourceId: atomId('event', edge.sourceId), targetId: atomId('event', edge.targetId), edgeType: edge.relationType, projectionKind: 'legacyBinary', sourceFactId: id, confidence: edge.confidence });
}

function causalGraphStatus(edge: GraphRebuildCausalEdge): GraphRebuildAdjudicationStatus {
    if (edge.status === 'accepted' || edge.status === 'supported') return 'accepted';
    if (edge.status === 'rejected' || edge.status === 'invalidated' || edge.status === 'contradicted') return 'rejected';
    return 'review';
}

function causalEvidenceRoleIds(edge: GraphRebuildTemporalEdge | GraphRebuildCausalEdge, family: 'temporal' | 'causal'): string[] {
    if (family === 'temporal') return edge.evidenceIds;
    return edge.evidenceIds.filter((id) => !id.startsWith('event:'));
}

function addMemoryFact(
    state: GraphRebuildMemoryState,
    facts: GraphModelV2RelationFact[],
    roles: GraphModelV2FactRole[],
    styleTags: GraphModelV2StyleTag[],
    projectionEdges: GraphModelV2ProjectionEdge[],
    addLaneTarget: (lane: GraphRebuildSignalTargetLane, id: string) => void,
): void {
    const id = `fact:memory:${state.id}`;
    facts.push({ id, family: 'memory', relationType: state.key, lane: 'memory_state', status: 'accepted', confidence: 0.72, evidenceIds: state.evidenceIds, sourceRecordId: state.id });
    addLaneTarget('memory_state', id);
    styleTags.push(styleTag(id, 'fact', 'storySignal', 'memoryState'));
    pushRole(roles, id, 'subject', atomId('entity', state.entityId), 0.72);
    pushRole(roles, id, 'state', atomId('state', state.id), 0.72);
    for (const evidenceId of state.evidenceIds) pushRole(roles, id, 'evidence', atomId('evidence', evidenceId), 0.72);
    projectionEdges.push({ id: `projection:memory:${state.id}`, sourceId: atomId('state', state.id), targetId: atomId('entity', state.entityId), edgeType: 'memory-state', projectionKind: 'factRole', sourceFactId: id, confidence: 0.72 });
}

function addLegacyProjection(edge: GraphRebuildEdge, projectionEdges: GraphModelV2ProjectionEdge[]): void {
    projectionEdges.push({ id: `projection:legacy:${edge.id}`, sourceId: atomId('entity', edge.sourceId), targetId: atomId('entity', edge.targetId), edgeType: edge.type, projectionKind: 'legacyBinary', confidence: edge.confidence });
}

function addEmbeddingParentProjections(target: GraphRebuildEmbeddingTarget, projectionEdges: GraphModelV2ProjectionEdge[]): void {
    for (const parentId of target.parentIds || []) {
        projectionEdges.push({ id: `projection:target-parent:${parentId}:${target.id}`, sourceId: parentId, targetId: target.id, edgeType: 'target-parent', projectionKind: 'structure', confidence: 0.88 });
    }
}

function relationFamily(type: string): GraphModelV2FactFamily {
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

function atomId(kind: string, sourceId: string): string {
    return `atom:${kind}:${sourceId}`;
}

function pushRole(roles: GraphModelV2FactRole[], factId: string, role: GraphModelV2RoleKind, targetAtomId: string, confidence: number): void {
    roles.push({ factId, role, targetAtomId, confidence });
}

function styleTag(targetId: string, targetType: GraphModelV2StyleTag['targetType'], tagKind: GraphModelV2StyleTagKind, value: string): GraphModelV2StyleTag {
    return { targetId, targetType, tagKind, value };
}

function structuralTag(targetId: string, value: string): GraphModelV2StyleTag {
    return styleTag(targetId, 'atom', 'structuralKind', value);
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
    for (const role of roles) counts.set(role.factId, (counts.get(role.factId) || 0) + 1);
    return counts;
}
