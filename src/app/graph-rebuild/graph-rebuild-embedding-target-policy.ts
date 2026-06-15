import type {
    GraphIndexEmbeddingStagePolicy,
    GraphRebuildCausalEdge,
    GraphRebuildEmbeddingTarget,
    GraphRebuildEmbeddingTargetPlan,
    GraphRebuildRelationship,
    GraphRebuildSignalTargetLane,
    GraphRebuildTemporalEdge,
} from './graph-rebuild-snapshot';

const MAX_EMBEDDING_WORK_TARGETS = 960;
const NOTE_TARGET_BUDGET = 48;
const CHUNK_TARGET_BUDGET = 220;
const STORY_EDGE_TARGET_BUDGET = 160;
const EVENT_TARGET_BUDGET = 128;
const MEMORY_TARGET_BUDGET = 128;
const RELATION_TARGET_BUDGET = 220;
const ENTITY_TARGET_BUDGET = 260;
const ANCHOR_TARGET_BUDGET = 160;
const WEAK_COOCCURRENCE_TARGET_BUDGET = 80;
const DEFAULT_STAGE_LANES: GraphRebuildSignalTargetLane[] = [
    'document_spine',
    'chunk_spine',
    'entity_anchor',
    'relationship_fact',
    'temporal_fact',
    'causal_fact',
    'memory_state',
    'event_identity',
    'story_signal',
    'anchor_evidence',
    'entity_linker',
    'cooccurrence_weak',
    'unknown',
];

export function selectGraphRebuildEmbeddingTargetPlan(
    targets: GraphRebuildEmbeddingTarget[],
    relationships: GraphRebuildRelationship[],
    temporalEdges: GraphRebuildTemporalEdge[],
    causalEdges: GraphRebuildCausalEdge[],
    stagePolicy?: GraphIndexEmbeddingStagePolicy,
): GraphRebuildEmbeddingTargetPlan & { targets: GraphRebuildEmbeddingTarget[] } {
    const annotated = targets.map(annotateTarget);
    const enabledLanes = enabledStageLanes(stagePolicy);
    const eligible = annotated.filter((target) => isStructureRoot(target) || enabledLanes.has(target.lane || 'unknown'));
    const disabled = annotated.filter((target) => !isStructureRoot(target) && !enabledLanes.has(target.lane || 'unknown'));
    const queued = selectEmbeddingTargets(eligible, relationships, temporalEdges, causalEdges);
    const queuedIds = new Set(queued.map((target) => target.id));
    const admitted = queued.map((target) => ({
        ...target,
        admissionStatus: 'admitted' as const,
        workStatus: 'queued' as const,
        admissionReason: target.admissionReason || 'admitted_by_hierarchical_plan',
    }));
    const deferredByScheduler = eligible
        .filter((target) => !queuedIds.has(target.id))
        .map((target) => ({
            ...target,
            admissionStatus: 'deferred' as const,
            workStatus: 'deferred_by_scheduler' as const,
            structuralRole: 'deferred' as const,
            deferReason: targetDeferReason(target),
        }));
    const deferredByPolicy = disabled.map((target) => ({
        ...target,
        admissionStatus: 'deferred' as const,
        workStatus: 'deferred_by_policy' as const,
        structuralRole: 'deferred' as const,
        deferReason: 'lane_disabled_by_stage_policy',
    }));
    const deferred = [...deferredByScheduler, ...deferredByPolicy];
    const canonicalTargets = canonicalTargetOrder([...admitted, ...deferred]);
    return {
        schemaVersion: 'phoenix-signal-target-plan/v1',
        candidateCount: annotated.length,
        admittedCount: admitted.length,
        deferredCount: deferred.length,
        maxAdmitted: MAX_EMBEDDING_WORK_TARGETS,
        canonicalCount: canonicalTargets.length,
        queuedCount: admitted.length,
        schedulerDeferredCount: deferredByScheduler.length,
        policyDeferredCount: deferredByPolicy.length,
        maxQueued: MAX_EMBEDDING_WORK_TARGETS,
        queuedTargetIds: admitted.map((target) => target.id),
        schedulerDeferredTargetIds: deferredByScheduler.map((target) => target.id),
        policyDeferredTargetIds: deferredByPolicy.map((target) => target.id),
        lanes: buildLaneReceipts(canonicalTargets),
        targets: canonicalTargets,
    };
}

function selectEmbeddingTargets(
    targets: GraphRebuildEmbeddingTarget[],
    relationships: GraphRebuildRelationship[],
    temporalEdges: GraphRebuildTemporalEdge[],
    causalEdges: GraphRebuildCausalEdge[],
): GraphRebuildEmbeddingTarget[] {
    const selected = new Map<string, GraphRebuildEmbeddingTarget>();
    const byKind = groupTargetsByKind(targets);
    const byLane = groupTargetsByLane(targets);
    const targetById = new Map(targets.map((target) => [target.id, target]));
    const entityById = new Map((byKind.get('entity') || []).map((target) => [target.entityId || target.sourceId, target]));
    const eventById = new Map((byKind.get('event') || []).map((target) => [target.sourceId, target]));
    const relationshipById = new Map(relationships.map((relationship) => [relationship.id, relationship]));
    const storyEdgeById = new Map([...temporalEdges, ...causalEdges].map((edge) => [edge.id, edge]));
    const addGroup = (group: Array<GraphRebuildEmbeddingTarget | undefined>): boolean => {
        const missing = group.filter((target): target is GraphRebuildEmbeddingTarget => !!target && !selected.has(target.id));
        if (selected.size + missing.length > MAX_EMBEDDING_WORK_TARGETS) return false;
        for (const target of missing) selected.set(target.id, target);
        return true;
    };
    const addMany = (values: GraphRebuildEmbeddingTarget[], budget: number): void => {
        for (const target of values.slice(0, budget)) addGroup([target]);
    };

    const structureRoots = ranked(byKind.get('structureroot') || []);
    addMany(structureRoots, structureRoots.length);
    addMany(ranked(byLane.get('document_spine') || []), NOTE_TARGET_BUDGET * 6);
    addMany(spreadSample(documentOrdered(byKind.get('chunk') || []), CHUNK_TARGET_BUDGET), CHUNK_TARGET_BUDGET);
    for (const target of ranked([...(byLane.get('temporal_fact') || []), ...(byLane.get('causal_fact') || [])]).slice(0, STORY_EDGE_TARGET_BUDGET)) {
        const edge = storyEdgeById.get(target.sourceId);
        addGroup([target, edge ? eventById.get(edge.sourceId) : undefined, edge ? eventById.get(edge.targetId) : undefined]);
    }
    addMany(ranked(byLane.get('event_identity') || []), EVENT_TARGET_BUDGET);
    for (const target of ranked(byLane.get('memory_state') || []).slice(0, MEMORY_TARGET_BUDGET)) {
        addGroup([target, target.entityId ? entityById.get(target.entityId) : undefined]);
    }
    for (const target of ranked(byLane.get('relationship_fact') || []).slice(0, RELATION_TARGET_BUDGET)) {
        const relationship = relationshipById.get(target.sourceId);
        const situationRoleTargets = target.sourceId.startsWith('fact:document-hyperedge:')
            ? (target.parentIds || [])
                .filter((id) => id.startsWith('embed:entity:') || id.startsWith('embed:atom:'))
                .map((id) => targetById.get(id))
            : [];
        addGroup([
            target,
            relationship ? entityById.get(relationship.sourceEntityId) : undefined,
            relationship ? entityById.get(relationship.targetEntityId) : undefined,
            ...situationRoleTargets,
        ]);
    }
    addMany(ranked(byKind.get('entity') || []), ENTITY_TARGET_BUDGET);
    for (const target of ranked(byLane.get('cooccurrence_weak') || []).filter((target) => isPromotedWeakCooccurrence(target, relationshipById)).slice(0, WEAK_COOCCURRENCE_TARGET_BUDGET)) {
        const relationship = relationshipById.get(target.sourceId);
        addGroup([
            target,
            relationship ? entityById.get(relationship.sourceEntityId) : undefined,
            relationship ? entityById.get(relationship.targetEntityId) : undefined,
        ]);
    }
    const selectedEntityIds = new Set([...selected.values()]
        .filter((target) => normalizeKind(target.kind) === 'entity')
        .map((target) => target.entityId || target.sourceId));
    for (const target of representativeAnchors(byLane.get('anchor_evidence') || [], selectedEntityIds).slice(0, ANCHOR_TARGET_BUDGET)) {
        addGroup([target, target.entityId ? entityById.get(target.entityId) : undefined]);
    }
    for (const target of coverageFillOrder(targets).filter((target) => isPrimaryTarget(target))) addGroup([target]);
    return [...selected.values()];
}

function annotateTarget(target: GraphRebuildEmbeddingTarget): GraphRebuildEmbeddingTarget {
    const lane = targetLane(target);
    return {
        ...target,
        lane,
        admissionTier: targetTier(target, lane),
        structuralRole: targetStructuralRole(target, lane),
        admissionReason: targetAdmissionReason(target, lane),
        parentIds: targetParentIds(target),
    };
}

function targetLane(target: GraphRebuildEmbeddingTarget): GraphRebuildSignalTargetLane {
    const kind = normalizeKind(target.kind);
    if (kind === 'note') return 'document_spine';
    if (kind === 'structureroot') return structureRootLane(target);
    if (kind === 'chunk') return 'chunk_spine';
    if (kind === 'entity') return 'entity_anchor';
    if (kind === 'anchor') return 'anchor_evidence';
    if (kind === 'concept') return 'entity_linker';
    if (kind === 'evidencespan') return 'anchor_evidence';
    if (kind === 'documentunit') return 'chunk_spine';
    if (kind === 'event') return 'event_identity';
    if (kind === 'temporalfact') return 'temporal_fact';
    if (kind === 'causalfact') return 'causal_fact';
    if (kind === 'memorystate') return 'memory_state';
    if (kind === 'graphfact') {
        const text = `${target.label} ${target.text} ${target.sourceId}`.toLowerCase();
        return /co.?occur/.test(text) ? 'cooccurrence_weak' : 'relationship_fact';
    }
    return 'unknown';
}

function targetStructuralRole(
    target: GraphRebuildEmbeddingTarget,
    lane: GraphRebuildSignalTargetLane,
): GraphRebuildEmbeddingTarget['structuralRole'] {
    if (isStructureRoot(target)) return 'root';
    switch (lane) {
        case 'document_spine': return 'root';
        case 'chunk_spine': return 'spine';
        case 'entity_anchor': return 'child';
        case 'relationship_fact':
        case 'temporal_fact':
        case 'causal_fact':
        case 'event_identity':
        case 'memory_state':
        case 'story_signal':
            return 'fact';
        case 'anchor_evidence': return 'evidence';
        case 'entity_linker': return 'bridge';
        case 'cooccurrence_weak': return 'bridge';
        default: return 'context';
    }
}

function targetAdmissionReason(target: GraphRebuildEmbeddingTarget, lane: GraphRebuildSignalTargetLane): string {
    const rootKey = structureRootKey(target);
    if (rootKey) return `mandatory_${rootKey}_root`;
    switch (lane) {
        case 'document_spine': return 'mandatory_document_spine';
        case 'chunk_spine': return 'mandatory_chunk_spine';
        case 'entity_anchor': return 'accepted_entity_anchor';
        case 'relationship_fact': return 'typed_relationship_fact';
        case 'temporal_fact': return 'typed_temporal_fact';
        case 'causal_fact': return 'typed_causal_fact';
        case 'event_identity': return 'typed_event_identity';
        case 'memory_state': return 'typed_memory_state';
        case 'entity_linker': return 'entity_linker_candidate';
        case 'anchor_evidence': return 'representative_anchor_evidence';
        case 'cooccurrence_weak': return 'weak_cooccurrence_context';
        default: return 'fallback_signal';
    }
}

function targetTier(target: GraphRebuildEmbeddingTarget, lane: GraphRebuildSignalTargetLane): number {
    if (isStructureRoot(target)) return 0;
    if (lane === 'document_spine' || lane === 'chunk_spine') return 0;
    if (lane === 'entity_anchor') return 1;
    if (lane === 'anchor_evidence' || lane === 'cooccurrence_weak' || lane === 'entity_linker') return 3;
    if (lane === 'unknown') return 4;
    return 2;
}

function targetDeferReason(target: GraphRebuildEmbeddingTarget): string {
    if (isStructureRoot(target)) return 'structure_root_deferred_by_scheduler';
    if (target.lane === 'cooccurrence_weak') return 'weak_cooccurrence_not_promoted';
    if (target.lane === 'entity_linker') return 'entity_linker_requires_final_linking';
    if (target.lane === 'anchor_evidence') return 'raw_anchor_evidence_not_promoted';
    return 'outside_current_embedding_budget';
}

function enabledStageLanes(policy?: GraphIndexEmbeddingStagePolicy): Set<GraphRebuildSignalTargetLane> {
    return new Set(policy?.enabledLanes?.length ? policy.enabledLanes : DEFAULT_STAGE_LANES);
}

function buildLaneReceipts(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTargetPlan['lanes'] {
    const byLane = groupTargetsByLane(targets);
    return [...byLane.entries()]
        .map(([lane, values]) => ({
            lane,
            candidates: values.length,
            admitted: values.filter((target) => target.admissionStatus === 'admitted').length,
            deferred: values.filter((target) => target.admissionStatus === 'deferred').length,
            tier: targetTier(values[0], lane),
        }))
        .sort((left, right) => left.tier - right.tier || left.lane.localeCompare(right.lane));
}

function groupTargetsByLane(targets: GraphRebuildEmbeddingTarget[]): Map<GraphRebuildSignalTargetLane, GraphRebuildEmbeddingTarget[]> {
    const groups = new Map<GraphRebuildSignalTargetLane, GraphRebuildEmbeddingTarget[]>();
    for (const target of targets) {
        const lane = target.lane || 'unknown';
        groups.set(lane, [...(groups.get(lane) || []), target]);
    }
    return groups;
}

function groupTargetsByKind(targets: GraphRebuildEmbeddingTarget[]): Map<string, GraphRebuildEmbeddingTarget[]> {
    const groups = new Map<string, GraphRebuildEmbeddingTarget[]>();
    for (const target of targets) {
        const kind = normalizeKind(target.kind);
        groups.set(kind, [...(groups.get(kind) || []), target]);
    }
    return groups;
}

function representativeAnchors(targets: GraphRebuildEmbeddingTarget[], selectedEntityIds = new Set<string>()): GraphRebuildEmbeddingTarget[] {
    const perEntity = new Map<string, GraphRebuildEmbeddingTarget[]>();
    for (const target of ranked(targets)) {
        const key = target.entityId || target.sourceId;
        if (selectedEntityIds.size && !selectedEntityIds.has(key)) continue;
        if (!isPromotedAnchorEvidence(target)) continue;
        if ((perEntity.get(key) || []).length >= 1) continue;
        perEntity.set(key, [target]);
    }
    return [...perEntity.values()].flat().sort(targetOrder);
}

function isPromotedWeakCooccurrence(target: GraphRebuildEmbeddingTarget, relationshipById: Map<string, GraphRebuildRelationship>): boolean {
    const relationship = relationshipById.get(target.sourceId);
    if (relationship?.status === 'accepted') return true;
    if (relationship && relationship.adjudicationSource !== 'graph-rebuild-cooccurrence-policy') return true;
    const text = `${target.text} ${target.label}`.toLowerCase();
    return numericSignal(text, 'scope_count') >= 2
        || numericSignal(text, 'anchor_evidence_count') >= 8
        || numericSignal(text, 'nli_confidence') >= 0.72;
}

function isPromotedAnchorEvidence(target: GraphRebuildEmbeddingTarget): boolean {
    const text = `${target.text} ${target.label}`.toLowerCase();
    if (/source:(accepted_suggestion|manual_tag|user)/.test(text)) return true;
    return numericSignal(text, 'confidence') >= 0.88 && /evidence_context:/.test(text);
}

function documentOrdered(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    return [...targets].sort((left, right) =>
        String(left.noteId || '').localeCompare(String(right.noteId || ''))
        || String(left.chunkId || left.sourceId).localeCompare(String(right.chunkId || right.sourceId))
        || targetOrder(left, right));
}

function spreadSample<T>(values: T[], limit: number): T[] {
    if (values.length <= limit) return values;
    if (limit <= 0) return [];
    const step = (values.length - 1) / Math.max(1, limit - 1);
    const out: T[] = [];
    for (let index = 0; index < limit; index += 1) out.push(values[Math.round(index * step)]);
    return out;
}

function coverageFillOrder(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    return [...targets].sort((left, right) => coverageWeight(right) - coverageWeight(left) || targetOrder(left, right));
}

function canonicalTargetOrder(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    return [...targets].sort((left, right) =>
        (left.admissionTier ?? 9) - (right.admissionTier ?? 9)
        || String(left.noteId || '').localeCompare(String(right.noteId || ''))
        || coverageWeight(right) - coverageWeight(left)
        || left.id.localeCompare(right.id),
    );
}

function coverageWeight(target: GraphRebuildEmbeddingTarget): number {
    const kind = normalizeKind(target.kind);
    if (kind === 'note') return 980;
    if (kind === 'structureroot') return 970;
    if (kind === 'chunk') return 960;
    if (kind === 'causalfact') return 940;
    if (kind === 'temporalfact') return 930;
    if (kind === 'event') return 910;
    if (kind === 'memorystate') return 890;
    if (kind === 'graphfact') return 860;
    if (kind === 'entity') return 830;
    if (kind === 'anchor') return 760;
    return 700;
}

function ranked(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    return [...targets].sort(targetOrder);
}

function targetOrder(left: GraphRebuildEmbeddingTarget, right: GraphRebuildEmbeddingTarget): number {
    return targetScore(right) - targetScore(left) || left.id.localeCompare(right.id);
}

function targetScore(target: GraphRebuildEmbeddingTarget): number {
    const kind = normalizeKind(target.kind);
    let score =
        kind === 'structureroot' ? 980 :
        kind === 'entity' ? 900 :
        kind === 'graphfact' ? 840 :
        kind === 'causalfact' ? 830 :
        kind === 'temporalfact' ? 810 :
        kind === 'event' ? 780 :
        kind === 'memorystate' ? 720 :
        kind === 'note' ? 680 :
        kind === 'chunk' ? 620 :
        kind === 'anchor' ? 540 : 500;
    const text = `${target.label} ${target.text}`.toLowerCase();
    if (text.includes('[accepted]')) score += 90;
    if (text.includes('[review]')) score += 34;
    if (/command|authority|causal|cause|because|before|after|temporal|approved|accepted|warn/.test(text)) score += 44;
    if (/chunk_role:(authority_chain|evidence_block|transition)/.test(text)) score += 36;
    if (/meaning_cues:|entity_priors:/.test(text)) score += 18;
    if (/evidence_context:/.test(text)) score += 42;
    if (/source:(manual_tag|accepted_suggestion|dictionary_match|machine_evidence|machine_suggestion)/.test(text)) score += 24;
    const mentionMatch = text.match(/mentions:(\d+)/);
    if (mentionMatch) score += Math.min(64, Number(mentionMatch[1]) * 2);
    score += Math.round(clamp(numericSignal(text, 'confidence'), 0, 1) * 48);
    score += Math.min(48, target.evidenceIds.length * 6);
    if (target.entityKind) score += 8;
    return score;
}

function targetParentIds(target: GraphRebuildEmbeddingTarget): string[] {
    const parents: string[] = [...(target.parentIds || [])];
    const kind = normalizeKind(target.kind);
    const rooted = Boolean(target.noteId && parents.some((parentId) => parentId.startsWith(`embed:structure-root:${target.noteId}:`)));
    if (target.noteId && kind !== 'note' && (kind === 'structureroot' || !rooted)) parents.push(`embed:note:${target.noteId}`);
    if (target.chunkId && kind !== 'chunk') parents.push(`embed:chunk:${target.chunkId}`);
    if (target.entityId && kind !== 'entity') parents.push(`embed:entity:${target.entityId}`);
    return [...new Set(parents)];
}

function isPrimaryTarget(target: GraphRebuildEmbeddingTarget): boolean {
    if (isStructureRoot(target)) return true;
    return target.lane !== 'anchor_evidence' && target.lane !== 'cooccurrence_weak';
}

function structureRootLane(target: GraphRebuildEmbeddingTarget): GraphRebuildSignalTargetLane {
    switch (structureRootKey(target)) {
        case 'identity': return 'entity_anchor';
        case 'temporal': return 'temporal_fact';
        case 'causal': return 'causal_fact';
        case 'evidence': return 'anchor_evidence';
        default: return 'document_spine';
    }
}

function structureRootKey(target: GraphRebuildEmbeddingTarget): string {
    if (!isStructureRoot(target)) return '';
    const text = `${target.id} ${target.sourceId} ${target.label} ${target.text}`.toLowerCase();
    if (/causal|cause/.test(text)) return 'causal';
    if (/temporal|before|after|timeline/.test(text)) return 'temporal';
    if (/identity|entity|alias/.test(text)) return 'identity';
    if (/evidence|source|provenance/.test(text)) return 'evidence';
    return 'document_structure';
}

function isStructureRoot(target: GraphRebuildEmbeddingTarget): boolean {
    return normalizeKind(target.kind) === 'structureroot';
}

function numericSignal(text: string, key: string): number {
    const match = text.match(new RegExp(`${key}:([0-9.]+)`));
    return match ? Number(match[1]) || 0 : 0;
}

function normalizeKind(kind: string): string {
    return String(kind || '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase().replace(/[-_\s]+/g, '');
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}
