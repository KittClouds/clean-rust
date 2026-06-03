import type {
    GraphRebuildCausalEdge,
    GraphRebuildCausalEvidenceClass,
    GraphRebuildCausalModality,
    GraphRebuildCausalPolarity,
    GraphRebuildCausalSidecarEdge,
    GraphRebuildCausalSidecarInput,
    GraphRebuildCausalSidecarNodeRef,
    GraphRebuildCausalSidecarReviewCase,
    GraphRebuildCausalSourceKind,
    GraphRebuildCausalSourceSemantics,
    GraphRebuildCausalStatus,
    GraphRebuildChunk,
    GraphRebuildEvent,
} from './graph-rebuild-snapshot';

interface CausalCueRule {
    cue: string;
    relationKind: string;
    relationType: string;
    sourceKind: GraphRebuildCausalSourceKind;
    confidence: number;
}

const CUE_RULES: readonly CausalCueRule[] = [
    { cue: 'because', relationKind: 'direct_cause', relationType: 'causes_or_explains', sourceKind: 'candidate_cue', confidence: 0.72 },
    { cue: 'therefore', relationKind: 'mediated_cause', relationType: 'leads_to', sourceKind: 'candidate_cue', confidence: 0.70 },
    { cue: 'which meant', relationKind: 'mediated_cause', relationType: 'leads_to', sourceKind: 'candidate_cue', confidence: 0.68 },
    { cue: 'that meant', relationKind: 'mediated_cause', relationType: 'leads_to', sourceKind: 'candidate_cue', confidence: 0.68 },
    { cue: 'as a result', relationKind: 'mediated_cause', relationType: 'leads_to', sourceKind: 'candidate_cue', confidence: 0.70 },
    { cue: 'so ', relationKind: 'hypothesized_cause', relationType: 'causes_or_explains', sourceKind: 'local_temporal_pair', confidence: 0.62 },
];

export function buildGraphRebuildCausalEdges(
    events: GraphRebuildEvent[],
    chunks: GraphRebuildChunk[],
    noteTexts: Record<string, string>,
    sidecar?: GraphRebuildCausalSidecarInput,
): GraphRebuildCausalEdge[] {
    const byChunk = new Map(chunks.map((chunk) => [chunk.id, chunk]));
    const eventLookup = buildEventLookup(events);
    const edges = new Map<string, GraphRebuildCausalEdge>();
    for (const edge of [...(sidecar?.edgeRecords || []), ...(sidecar?.edgeAdditions || [])]) {
        upsertEdge(edges, causalEdgeFromSidecar(edge, eventLookup));
    }
    for (const review of [...(sidecar?.reviewCases || []), ...(sidecar?.shadowLocalPairCases || [])]) {
        upsertEdge(edges, causalEdgeFromReviewCase(review, eventLookup));
    }
    for (const edge of localCausalEdges(events, byChunk, noteTexts)) upsertEdge(edges, edge);
    return [...edges.values()].sort((left, right) =>
        statusRank(right.status) - statusRank(left.status)
        || right.confidence - left.confidence
        || left.id.localeCompare(right.id));
}

function causalEdgeFromSidecar(
    edge: GraphRebuildCausalSidecarEdge,
    eventLookup: Map<string, GraphRebuildEvent>,
): GraphRebuildCausalEdge | null {
    const source = resolveEvent(edge.canonicalCauseEventId, edge.source, eventLookup);
    const target = resolveEvent(edge.canonicalEffectEventId, edge.target, eventLookup);
    if (!source || !target) return null;
    const relationKind = normalizeRelationKind(edge.relationKind || edge.kind);
    const cue = edge.cue?.trim() || undefined;
    return {
        id: stableCausalId(edge.edgeId || edge.caseId || 'sidecar', source.id, target.id, relationKind),
        sourceId: source.id,
        targetId: target.id,
        relationType: relationType(relationKind),
        relationKind,
        evidenceIds: causalEvidenceIds(source, target, edge.evidenceRefs),
        confidence: confidence(edge.confidenceMillis, cue ? 0.74 : 0.68),
        status: normalizeStatus(edge.status),
        sourceKind: cue ? 'explicit_cue' : 'graph_support',
        evidenceClass: 'world_support',
        polarity: normalizePolarity(edge.polarity),
        modality: 'asserted',
        sourceSemantics: 'world_assertion',
        cue,
        attributedTo: edge.attributedTo || undefined,
        supportIds: compact([edge.caseId, ...(edge.claimAtomIds || []), ...eventSupportIds(source, target)]),
        rationale: 'causal sidecar edge promoted into graph rebuild snapshot',
    };
}

function causalEdgeFromReviewCase(
    review: GraphRebuildCausalSidecarReviewCase,
    eventLookup: Map<string, GraphRebuildEvent>,
): GraphRebuildCausalEdge | null {
    const source = resolveEvent(review.canonicalCauseEventId, review.source, eventLookup);
    const target = resolveEvent(review.canonicalEffectEventId, review.target, eventLookup);
    if (!source || !target) return null;
    const relationKind = normalizeRelationKind(review.relationKind || review.kind);
    const sourceKind = normalizeSourceKind(review.seedSource);
    return {
        id: stableCausalId(review.caseId || 'review', source.id, target.id, relationKind),
        sourceId: source.id,
        targetId: target.id,
        relationType: relationType(relationKind),
        relationKind,
        evidenceIds: causalEvidenceIds(source, target, review.evidenceRefs),
        confidence: confidence(review.baseConfidenceMillis, 0.58),
        status: 'candidate',
        sourceKind,
        evidenceClass: evidenceClassForReview(review),
        polarity: normalizePolarity(review.polarity),
        modality: normalizeModality(review.modalitySemantics),
        sourceSemantics: normalizeSourceSemantics(review.sourceSemantics),
        cue: review.cue?.trim() || undefined,
        attributedTo: review.attributedTo || undefined,
        supportIds: compact([review.caseId, ...eventSupportIds(source, target)]),
        temporalLegal: review.temporalLegal,
        sentenceDistance: review.sentenceDistance,
        graphSupportCount: review.graphSupportCount,
        rationale: 'causal review case staged for graph rebuild review',
    };
}

function localCausalEdges(
    events: GraphRebuildEvent[],
    byChunk: Map<string, GraphRebuildChunk>,
    noteTexts: Record<string, string>,
): GraphRebuildCausalEdge[] {
    const out: GraphRebuildCausalEdge[] = [];
    for (const noteEvents of eventsByNote(events, byChunk)) {
        for (let index = 1; index < noteEvents.length; index += 1) {
            const current = noteEvents[index];
            const chunk = current.chunkId ? byChunk.get(current.chunkId) : undefined;
            const rule = chunk ? causalCue((noteTexts[chunk.noteId] || '').slice(chunk.start, chunk.end).toLowerCase()) : null;
            if (!rule) continue;
            for (let offset = 1; offset <= Math.min(3, index); offset += 1) {
                const previous = noteEvents[index - offset];
                const shared = sharedEntityCount(previous, current);
                if (!shared) continue;
                const confidenceValue = clamp(rule.confidence + Math.min(0.06, shared * 0.02) - (offset - 1) * 0.05, 0.52, 0.78);
                out.push({
                    id: stableCausalId(`local:${rule.cue}`, previous.id, current.id, rule.relationKind),
                    sourceId: previous.id,
                    targetId: current.id,
                    relationType: rule.relationType,
                    relationKind: rule.relationKind,
                    evidenceIds: causalEvidenceIds(previous, current),
                    confidence: confidenceValue,
                    status: 'candidate',
                    sourceKind: rule.sourceKind,
                    evidenceClass: 'local_temporal_pair',
                    polarity: 'support',
                    modality: 'asserted',
                    sourceSemantics: 'world_assertion',
                    cue: rule.cue.trim(),
                    supportIds: eventSupportIds(previous, current),
                    temporalLegal: true,
                    sentenceDistance: offset,
                    graphSupportCount: shared,
                    rationale: `local cue "${rule.cue.trim()}" linked nearby shared-participant events`,
                });
                break;
            }
        }
    }
    return out;
}

function buildEventLookup(events: GraphRebuildEvent[]): Map<string, GraphRebuildEvent> {
    const lookup = new Map<string, GraphRebuildEvent>();
    for (const event of events) {
        for (const key of compact([event.id, event.chunkId, event.id.replace(/^event:/, '')])) lookup.set(normalizeKey(key), event);
    }
    return lookup;
}

function resolveEvent(id: string | null | undefined, node: GraphRebuildCausalSidecarNodeRef | undefined, lookup: Map<string, GraphRebuildEvent>): GraphRebuildEvent | null {
    for (const candidate of compact([id, nodeRefId(node)])) {
        const event = lookup.get(normalizeKey(candidate));
        if (event) return event;
    }
    return null;
}

function nodeRefId(node: GraphRebuildCausalSidecarNodeRef | undefined): string | undefined {
    if (!node) return undefined;
    if (typeof node === 'string') return node;
    return readNodeString(node, 'canonicalEventId')
        || readNodeString(node, 'id')
        || readNodeString(node, 'nodeId')
        || readNodeString(node, 'semanticNodeId')
        || readNodeString(node, 'label');
}

function readNodeString(node: Record<string, unknown>, key: string): string | undefined {
    const value = node[key];
    return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function causalCue(text: string): CausalCueRule | null {
    return CUE_RULES.find((rule) => text.includes(rule.cue)) || null;
}

function causalEvidenceIds(source: GraphRebuildEvent, target: GraphRebuildEvent, refs: string[] = []): string[] {
    return unique([...refs, ...source.evidenceAnchorIds, ...target.evidenceAnchorIds]).slice(0, 24);
}

function eventSupportIds(source: GraphRebuildEvent, target: GraphRebuildEvent): string[] {
    return compact([source.id, target.id, source.chunkId, target.chunkId]);
}

function upsertEdge(edges: Map<string, GraphRebuildCausalEdge>, edge: GraphRebuildCausalEdge | null): void {
    if (!edge) return;
    const key = `${edge.sourceId}|${edge.targetId}|${edge.relationKind || edge.relationType}|${edge.sourceKind}`;
    const current = edges.get(key);
    if (!current || edgeRank(edge) > edgeRank(current)) edges.set(key, edge);
}

function edgeRank(edge: GraphRebuildCausalEdge): number {
    return statusRank(edge.status) * 10 + edge.confidence;
}

function statusRank(status: GraphRebuildCausalStatus): number {
    switch (status) {
        case 'accepted': return 8;
        case 'supported': return 7;
        case 'candidate': return 5;
        case 'deferred': return 4;
        case 'contradicted': return 3;
        case 'superseded': return 2;
        case 'invalidated': return 1;
        case 'rejected': return 0;
    }
}

function relationType(kind: string): string {
    if (kind === 'direct_cause') return 'causes';
    if (kind === 'contributing_cause') return 'contributes_to';
    if (kind === 'enabling_condition') return 'enables';
    if (kind === 'preventing_factor') return 'prevents';
    if (kind === 'trigger') return 'triggers';
    if (kind === 'mediated_cause') return 'leads_to';
    return 'causes_or_explains';
}

function normalizeStatus(value: string | undefined): GraphRebuildCausalStatus {
    const key = normalizeEnum(value);
    if (key === 'active' || key === 'accepted') return 'accepted';
    if (key === 'supported') return 'supported';
    if (key === 'contradicted') return 'contradicted';
    if (key === 'superseded') return 'superseded';
    if (key === 'invalidated') return 'invalidated';
    if (key === 'deferred') return 'deferred';
    if (key === 'rejected') return 'rejected';
    return 'candidate';
}

function normalizeRelationKind(value: string | undefined): string {
    const key = normalizeEnum(value);
    if (key === 'causes') return 'direct_cause';
    if (key === 'results_in') return 'mediated_cause';
    if (key === 'enables' || key === 'condition_for') return 'enabling_condition';
    if (key === 'prevents' || key === 'hinders') return 'preventing_factor';
    return key || 'hypothesized_cause';
}

function normalizeSourceKind(value: string | undefined): GraphRebuildCausalSourceKind {
    const key = normalizeEnum(value);
    if (key === 'explicit_link') return 'explicit_link';
    if (key === 'explicit_cue') return 'explicit_cue';
    if (key === 'candidate_cue') return 'candidate_cue';
    if (key === 'local_temporal_pair') return 'local_temporal_pair';
    if (key === 'graph_support') return 'graph_support';
    if (key === 'reverse_conflict') return 'reverse_conflict';
    if (key === 'quote_attribution') return 'quote_attribution';
    if (key === 'counterfactual_competition') return 'counterfactual_competition';
    if (key === 'chain_bridge') return 'chain_bridge';
    return 'sidecar_review';
}

function normalizePolarity(value: string | undefined): GraphRebuildCausalPolarity {
    const key = normalizeEnum(value);
    if (key.includes('contradict') || key === 'negative') return 'contradict';
    if (key.includes('underspec')) return 'underspecify';
    if (key === 'support' || key === 'positive') return 'support';
    return 'unknown';
}

function normalizeModality(value: string | undefined): GraphRebuildCausalModality {
    const key = normalizeEnum(value);
    if (key.includes('conditional')) return 'conditional';
    if (key.includes('planned')) return 'planned';
    if (key.includes('hypothetical') || key.includes('speculative')) return 'hypothetical';
    if (key.includes('negated') || key.includes('negative')) return 'negated';
    if (key.includes('assert')) return 'asserted';
    return 'unknown';
}

function normalizeSourceSemantics(value: string | undefined): GraphRebuildCausalSourceSemantics {
    const key = normalizeEnum(value);
    if (key.includes('reported')) return 'reported_speech';
    if (key.includes('attributed')) return 'attributed_claim';
    if (key.includes('world') || key.includes('assert')) return 'world_assertion';
    return 'unknown';
}

function evidenceClassForReview(review: GraphRebuildCausalSidecarReviewCase): GraphRebuildCausalEvidenceClass {
    if (review.attributedEvidence || review.quotedOrAttributed || review.attributedTo) return 'attributed_support';
    if (review.quotedEvidence) return 'reported_support';
    if ((review.graphSupportCount || 0) > 0) return 'graph_support';
    return 'world_support';
}

function eventsByNote(events: GraphRebuildEvent[], byChunk: Map<string, GraphRebuildChunk>): GraphRebuildEvent[][] {
    const buckets = new Map<string, GraphRebuildEvent[]>();
    for (const event of events) buckets.set(event.noteId, [...(buckets.get(event.noteId) || []), event]);
    return [...buckets.values()].map((values) => values.sort((left, right) => eventOrdinal(left, byChunk) - eventOrdinal(right, byChunk) || left.id.localeCompare(right.id)));
}

function eventOrdinal(event: GraphRebuildEvent, byChunk: Map<string, GraphRebuildChunk>): number {
    return event.chunkId ? byChunk.get(event.chunkId)?.ordinal ?? Number.MAX_SAFE_INTEGER : Number.MAX_SAFE_INTEGER;
}

function sharedEntityCount(left: GraphRebuildEvent, right: GraphRebuildEvent): number {
    const rightIds = new Set(right.entityIds);
    return left.entityIds.filter((entityId) => rightIds.has(entityId)).length;
}

function confidence(millis: number | undefined, fallback: number): number {
    return clamp(typeof millis === 'number' ? millis / 1000 : fallback, 0, 1);
}

function stableCausalId(seed: string, sourceId: string, targetId: string, relationKind: string): string {
    return `causal:${slug(seed)}:${slug(sourceId)}:${slug(relationKind)}:${slug(targetId)}`;
}

function normalizeEnum(value: string | undefined): string {
    return (value || '').replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '').toLowerCase();
}

function normalizeKey(value: string): string {
    return value.trim().toLowerCase();
}

function slug(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '').slice(0, 96) || 'x';
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}

function compact(values: Array<string | null | undefined>): string[] {
    return values.filter((value): value is string => Boolean(value && value.trim()));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}
