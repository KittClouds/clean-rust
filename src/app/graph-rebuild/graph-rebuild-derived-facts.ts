import type {
    GraphRebuildChunk,
    GraphRebuildCausalEdge,
    GraphRebuildCausalSidecarInput,
    GraphRebuildEdge,
    GraphRebuildEntityAnchor,
    GraphRebuildEventAspect,
    GraphRebuildEventAspectKind,
    GraphRebuildEventCompletion,
    GraphRebuildChunkSemanticBridge,
    GraphRebuildChunkSemanticBridgeType,
    GraphRebuildEpisode,
    GraphRebuildEpisodeConnection,
    GraphRebuildEpisodeProjectionEdge,
    GraphRebuildEvent,
    GraphRebuildMemoryState,
    GraphRebuildRelationship,
    GraphRebuildSnapshot,
    GraphRebuildTemporalEdge,
} from './graph-rebuild-snapshot';
import type { GraphCrossDocumentBridgeRunCertificate } from './graph-cross-document-bridge-certificate';
import {
    buildGraphEpisodeProjectionEdges,
    episodeProjectionEdgeCounters,
} from './graph-episode-projection';
import { buildGraphRebuildCausalEdges } from './graph-rebuild-causal-graph';
import {
    assertChunkSemanticBridgeCandidateOnly,
    chunkSemanticBridgeTypeRank,
} from './graph-rebuild-chunk-semantic-bridges';

export interface DerivedGraphRebuildFacts {
    relationships: GraphRebuildRelationship[];
    edges: GraphRebuildEdge[];
    events: GraphRebuildEvent[];
    episodes: GraphRebuildEpisode[];
    chunkSemanticBridges: GraphRebuildChunkSemanticBridge[];
    episodeConnections: GraphRebuildEpisodeConnection[];
    episodeProjectionEdges: GraphRebuildEpisodeProjectionEdge[];
    temporalEdges: GraphRebuildTemporalEdge[];
    causalEdges: GraphRebuildCausalEdge[];
    memoryState: GraphRebuildMemoryState[];
}

interface EntityInChunk {
    id: string;
    firstStart: number;
    firstEnd: number;
    anchorIds: string[];
}

interface PairWindow {
    text: string;
    between: string;
}

const TYPED_RELATION_MAX_GAP_CHARS = 260;
const AUTHORITY_RELATION_CUES = ['command', 'admiral', 'phantom', 'military', 'chiefs', 'operator', 'warden', 'table', 'authority'];
const EVIDENCE_RELATION_CUES = ['documented', 'records', 'packet', 'evidence', 'file', 'files', 'attached', 'report'];

export function deriveGraphRebuildFacts(
    chunks: GraphRebuildChunk[],
    anchors: GraphRebuildEntityAnchor[],
    noteTexts: Record<string, string>,
    causalSidecar?: GraphRebuildCausalSidecarInput,
): DerivedGraphRebuildFacts {
    const byChunk = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of anchors) {
        if (!anchor.chunkId) continue;
        byChunk.set(anchor.chunkId, [...(byChunk.get(anchor.chunkId) || []), anchor]);
    }
    const relationships: GraphRebuildRelationship[] = [];
    const events: GraphRebuildEvent[] = [];
    const memoryState: GraphRebuildMemoryState[] = [];
    const edgeMap = new Map<string, GraphRebuildEdge>();
    const memorySeen = new Set<string>();

    for (const chunk of chunks) {
        const bucket = byChunk.get(chunk.id) || [];
        const entities = uniqueEntities(bucket);
        if (!entities.length) continue;
        const chunkText = (noteTexts[chunk.noteId] || '').slice(chunk.start, chunk.end);
        const lower = chunkText.toLowerCase();
        deriveRelationships(chunk, lower, entities, relationships, edgeMap);
        deriveEvent(chunk, lower, entities, events);
        deriveMemory(chunk, lower, entities, memorySeen, memoryState);
    }
    const edges = [...edgeMap.values()].sort((left, right) => right.weight - left.weight || left.type.localeCompare(right.type) || left.id.localeCompare(right.id));
    const episodes = buildEpisodes(events);
    const temporalEdges = buildTemporalEdges(events);
    const causalEdges = buildGraphRebuildCausalEdges(events, chunks, noteTexts, causalSidecar);
    const chunkSemanticBridges = assertChunkSemanticBridgeCandidateOnly([]);
    const episodeConnections = buildEpisodeConnections(episodes, events, temporalEdges, causalEdges, chunkSemanticBridges);
    const episodeProjectionEdges = buildGraphEpisodeProjectionEdges(episodes, events, chunks, episodeConnections);
    return { relationships, edges, events, episodes, chunkSemanticBridges, episodeConnections, episodeProjectionEdges, temporalEdges, causalEdges, memoryState };
}

export function applyNativeChunkSemanticBridgeCandidates(
    snapshot: GraphRebuildSnapshot,
    candidates: GraphRebuildChunkSemanticBridge[],
    crossDocumentCertificate?: GraphCrossDocumentBridgeRunCertificate,
): void {
    const chunkSemanticBridges = assertChunkSemanticBridgeCandidateOnly(attachChunkBridgeEpisodeIds(
        candidates,
        snapshot.episodes || [],
        snapshot.events || [],
    ));
    const episodeConnections = buildEpisodeConnections(
        snapshot.episodes || [],
        snapshot.events || [],
        snapshot.temporalEdges || [],
        snapshot.causalEdges || [],
        chunkSemanticBridges,
    );
    snapshot.chunkSemanticBridges = chunkSemanticBridges;
    snapshot.crossDocumentBridgeCertificate = crossDocumentCertificate;
    snapshot.episodeConnections = episodeConnections;
    snapshot.episodeProjectionEdges = buildGraphEpisodeProjectionEdges(
        snapshot.episodes || [],
        snapshot.events || [],
        snapshot.chunks || [],
        episodeConnections,
    );
    snapshot.counters = {
        ...snapshot.counters,
        chunkSemanticBridges: chunkSemanticBridges.length,
        chunkSetupPayoffBridges: countChunkSemanticBridges(chunkSemanticBridges, 'setup_payoff'),
        chunkCauseEffectBridges: countChunkSemanticBridges(chunkSemanticBridges, 'cause_effect'),
        chunkStateDeltaBridges: countChunkSemanticBridges(chunkSemanticBridges, 'state_delta'),
        chunkRelationshipDeltaBridges: countChunkSemanticBridges(chunkSemanticBridges, 'relationship_delta'),
        chunkTopicContinuationBridges: countChunkSemanticBridges(chunkSemanticBridges, 'topic_continuation'),
        chunkEvidenceReframeBridges: countChunkSemanticBridges(chunkSemanticBridges, 'evidence_reframe'),
        chunkMotifEchoBridges: countChunkSemanticBridges(chunkSemanticBridges, 'motif_echo'),
        chunkRouteContinuityBridges: countChunkSemanticBridges(chunkSemanticBridges, 'route_continuity'),
        episodeConnections: episodeConnections.length,
        episodeTemporalConnections: episodeConnections.filter((connection) => connection.kind === 'episode_temporal').length,
        episodeCausalConnections: episodeConnections.filter((connection) => connection.kind === 'episode_causal').length,
        episodeWormholeConnections: episodeConnections.filter((connection) => connection.kind === 'episode_wormhole').length,
        ...episodeProjectionEdgeCounters(snapshot.episodeProjectionEdges),
    };
}

function uniqueEntities(bucket: GraphRebuildEntityAnchor[]): EntityInChunk[] {
    const byEntity = new Map<string, EntityInChunk>();
    for (const anchor of bucket) {
        const current = byEntity.get(anchor.entityId);
        if (current) {
            current.anchorIds = unique([...current.anchorIds, anchor.id]);
            current.firstStart = Math.min(current.firstStart, anchor.sourceStart);
            current.firstEnd = Math.min(current.firstEnd, anchor.sourceEnd);
            continue;
        }
        byEntity.set(anchor.entityId, {
            id: anchor.entityId,
            firstStart: anchor.sourceStart,
            firstEnd: anchor.sourceEnd,
            anchorIds: [anchor.id],
        });
    }
    return [...byEntity.values()].sort((left, right) => left.firstStart - right.firstStart);
}

function deriveRelationships(
    chunk: GraphRebuildChunk,
    lower: string,
    entities: EntityInChunk[],
    relationships: GraphRebuildRelationship[],
    edgeMap: Map<string, GraphRebuildEdge>,
): void {
    if (entities.length < 2) return;
    for (const { left, right } of typedRelationPairs(entities)) {
        const relationType = inferRelationType(pairWindow(lower, chunk, left, right), chunk);
        if (!relationType) continue;
        const evidence = unique([...left.anchorIds, ...right.anchorIds]);
        const id = `typed:${chunk.noteId}:${chunk.ordinal}:${left.id}:${relationType}:${right.id}`;
        const confidence = relationConfidence(relationType);
        relationships.push({
            id,
            sourceEntityId: left.id,
            targetEntityId: right.id,
            relationType,
            evidenceAnchorIds: evidence,
            confidence,
            status: 'accepted',
            adjudicationSource: 'graph-rebuild-typed-cue-policy',
            adjudicationScore: confidence,
            rationale: `accepted: local pair cue promoted ${relationType} fact`,
            decisionEvidence: [`chunk:${chunk.id}`, `cue:${relationType}`],
        });
        upsertTypedEdge(edgeMap, left.id, right.id, relationType, evidence, chunk.id);
    }
}

function typedRelationPairs(entities: EntityInChunk[]): Array<{ left: EntityInChunk; right: EntityInChunk }> {
    const pairs: Array<{ left: EntityInChunk; right: EntityInChunk; gap: number }> = [];
    const sorted = [...entities].sort((left, right) => left.firstStart - right.firstStart);
    for (let i = 0; i < sorted.length - 1; i += 1) {
        const left = sorted[i];
        const right = sorted[i + 1];
        const gap = Math.max(0, right.firstStart - left.firstEnd);
        if (gap <= TYPED_RELATION_MAX_GAP_CHARS) pairs.push({ left, right, gap });
    }
    return pairs.sort((left, right) => left.gap - right.gap || left.left.id.localeCompare(right.left.id) || left.right.id.localeCompare(right.right.id));
}

function pairWindow(lower: string, chunk: GraphRebuildChunk, left: EntityInChunk, right: EntityInChunk): PairWindow {
    const start = Math.min(left.firstStart, right.firstStart);
    const end = Math.max(left.firstEnd, right.firstEnd);
    const localStart = Math.max(0, start - chunk.start);
    const localEnd = Math.max(localStart, end - chunk.start);
    return {
        text: lower.slice(Math.max(0, localStart - 120), Math.min(lower.length, localEnd + 120)),
        between: lower.slice(Math.min(lower.length, Math.max(0, left.firstEnd - chunk.start)), Math.min(lower.length, Math.max(0, right.firstStart - chunk.start))),
    };
}

function inferRelationType(window: PairWindow, chunk?: GraphRebuildChunk): string | null {
    const between = window.between;
    if ((chunk?.meaningFrame?.role === 'authority_chain' || chunk?.meaningFrame?.authorityCues.length) && hasAny(between, AUTHORITY_RELATION_CUES)) return 'command_or_service_tie';
    if ((chunk?.meaningFrame?.role === 'evidence_block' || chunk?.meaningFrame?.evidenceCues.length) && hasAny(between, EVIDENCE_RELATION_CUES)) return 'documented_in';
    if (hasAny(between, [' father', ' daughter', ' grandfather', ' family'])) return 'family_or_house_tie';
    if (hasAny(between, AUTHORITY_RELATION_CUES)) return 'command_or_service_tie';
    if (hasAny(between, ['approved', 'approval', 'accepted', 'agreed', 'proceed'])) return 'approves_or_accepts';
    if (hasAny(between, ['release', 'terms', 'warning', 'coercion'])) return 'discusses_release_terms';
    if (hasAny(between, EVIDENCE_RELATION_CUES)) return 'documented_in';
    if (hasAny(between, ['kiss', 'took his hand', 'stood beside', 'close enough'])) return 'intimate_or_close_contact';
    if (hasAny(between, ['looked at', 'watched', 'saw ', 'noticed'])) return 'observes';
    if (hasAny(between, ['gave', 'handed', 'took it from', 'received'])) return 'transfers_or_receives';
    if (hasAny(between, ['entered', 'arrived', 'came in', 'stood near'])) return 'scene_presence';
    return null;
}

function relationConfidence(type: string): number {
    if (type === 'family_or_house_tie' || type === 'command_or_service_tie' || type === 'approves_or_accepts') return 0.82;
    if (type === 'transfers_or_receives' || type === 'intimate_or_close_contact') return 0.76;
    if (type === 'discusses_release_terms') return 0.70;
    return 0.64;
}

function upsertTypedEdge(edgeMap: Map<string, GraphRebuildEdge>, left: string, right: string, type: string, evidence: string[], scopeKey: string): void {
    const [sourceId, targetId] = [left, right].sort();
    const id = `${sourceId}:${type}:${targetId}`;
    const edge = edgeMap.get(id) || { id, sourceId, targetId, type, weight: 0, confidence: 0, evidenceAnchorIds: [], scopeKeys: [], noteIds: [] };
    edge.weight += 1;
    edge.confidence = Math.min(1, edge.confidence + 0.25);
    edge.evidenceAnchorIds = unique([...edge.evidenceAnchorIds, ...evidence]);
    edge.scopeKeys = unique([...edge.scopeKeys, scopeKey]);
    edge.noteIds = unique([...edge.noteIds, ...evidence.map((id) => id.split(':')[0]).filter(Boolean)]);
    edgeMap.set(id, edge);
}

function deriveEvent(chunk: GraphRebuildChunk, lower: string, entities: EntityInChunk[], events: GraphRebuildEvent[]): void {
    const type = inferEventType(lower, chunk);
    if (!type) return;
    if ((type === 'dialogue_event' || type === 'positioning_event') && entities.length < 2) return;
    const picked = entities.slice(0, 6);
    events.push({
        id: `event:${chunk.noteId}:${chunk.ordinal}:${type}`,
        noteId: chunk.noteId,
        chunkId: chunk.id,
        label: `${type} in chunk ${chunk.ordinal + 1}`,
        entityIds: unique(picked.map((entity) => entity.id)),
        evidenceAnchorIds: unique(picked.flatMap((entity) => entity.anchorIds)),
        confidence: 0.68,
        aspect: inferEventAspect(lower, type, chunk),
    });
}

function inferEventType(text: string, chunk?: GraphRebuildChunk): string | null {
    if (chunk?.meaningFrame?.role === 'authority_chain' || chunk?.meaningFrame?.authorityCues.length) return 'authority_chain_event';
    if (chunk?.meaningFrame?.role === 'evidence_block' || chunk?.meaningFrame?.evidenceCues.length) return 'evidence_packet_event';
    if (hasAny(text, ['approved', 'signed', 'proceed'])) return 'approval_event';
    if (hasAny(text, ['warn', 'coercion', 'risk', 'prohibited'])) return 'warning_event';
    if (hasAny(text, ['keeps ', 'kept ', 'continues', 'continued', 'started', 'began', 'pulses', 'pulse ', 'selecting', 'selected', 'shifted', 'expanded'])) return 'process_event';
    if (hasAny(text, ['entered', 'arrived', 'came in', 'opened the door'])) return 'arrival_event';
    if (hasAny(text, ['asked', 'answered', 'said', 'spoke', 'read'])) return 'dialogue_event';
    if (hasAny(text, ['kiss', 'took his hand', 'handed', 'gave'])) return 'contact_or_transfer_event';
    if (hasAny(text, ['stood', 'watched', 'looked', 'turned'])) return 'positioning_event';
    return null;
}

function inferEventAspect(text: string, eventType: string, chunk: GraphRebuildChunk): GraphRebuildEventAspect {
    if (hasAny(text, HABITUAL_CUES)) return aspect('habitual', 'ongoing', text, HABITUAL_CUES, 'repeated_or_customary_event_shape', 0.78);
    if (hasAny(text, PLANNED_CUES)) return aspect('endeavor', 'planned', text, PLANNED_CUES, 'intended_or_authorized_event_shape', 0.74);
    if (hasAny(text, ATTEMPT_CUES)) return aspect('endeavor', 'attempted', text, ATTEMPT_CUES, 'attempted_event_shape', 0.72);
    if (hasAny(text, ONGOING_CUES)) return aspect('process', 'ongoing', text, ONGOING_CUES, 'ongoing_process_event_shape', 0.72);
    if (hasAny(text, STATE_CUES) || eventType === 'positioning_event') return aspect('state', 'ongoing', text, STATE_CUES, 'stative_or_position_event_shape', 0.68);
    if (eventType === 'dialogue_event') return aspect('activity', 'ongoing', text, DIALOGUE_CUES, 'unbounded_dialogue_activity', 0.66);
    if (hasAny(text, COMPLETED_CUES) || eventType.endsWith('_event')) return aspect('performance', 'completed', text, COMPLETED_CUES, 'bounded_completed_event_shape', 0.7);
    const role = chunk.meaningFrame?.role;
    if (role === 'transition') return aspect('transition', 'unknown', text, [], 'chunk_transition_shape', 0.62);
    return aspect('activity', 'unknown', text, [], 'fallback_unbounded_event_shape', 0.58);
}

function aspect(
    kind: GraphRebuildEventAspectKind,
    completion: GraphRebuildEventCompletion,
    text: string,
    cuePool: readonly string[],
    rationale: string,
    confidence: number,
): GraphRebuildEventAspect {
    return {
        kind,
        completion,
        confidence,
        cues: cuePool.filter((cue) => text.includes(cue)).slice(0, 8),
        rationale,
    };
}

function deriveMemory(chunk: GraphRebuildChunk, lower: string, entities: EntityInChunk[], seen: Set<string>, memory: GraphRebuildMemoryState[]): void {
    const key = inferMemoryKey(lower);
    if (!key) return;
    for (const entity of entities.slice(0, 4)) {
        const id = `memory:${entity.id}:${key}:${chunk.ordinal}`;
        if (seen.has(id)) continue;
        seen.add(id);
        memory.push({ id, entityId: entity.id, noteId: chunk.noteId, key, value: `chunk:${chunk.ordinal} cue:${key}`, evidenceIds: [...entity.anchorIds] });
    }
}

function inferMemoryKey(text: string): string | null {
    if (hasAny(text, ['diamond', 'sapphire', 'black rank', 'queen'])) return 'rank_or_status';
    if (hasAny(text, ['family', 'father', 'grandfather', 'daughter'])) return 'family_context';
    if (hasAny(text, ['phantom', 'admiral', 'command', 'military'])) return 'service_context';
    if (hasAny(text, ['approved', 'accepted', 'agreed', 'proceed'])) return 'decision_state';
    if (hasAny(text, ['germany', 'atlas', 'barish', 'clayne', 'blazefell'])) return 'affiliation_context';
    return null;
}

function buildEpisodes(events: GraphRebuildEvent[]): GraphRebuildEpisode[] {
    const episodes: GraphRebuildEpisode[] = [];
    for (const noteEvents of eventsByNote(events)) {
        for (let index = 0; index < noteEvents.length; index += 12) {
            const group = noteEvents.slice(index, index + 12);
            const ordinal = Math.floor(index / 12);
            episodes.push({
                id: `episode:${group[0]?.noteId || 'unknown'}:${ordinal}`,
                noteId: group[0]?.noteId || '',
                eventIds: group.map((event) => event.id),
                entityIds: unique(group.flatMap((event) => event.entityIds)),
                label: `Episode ${ordinal + 1}`,
            });
        }
    }
    return episodes;
}

function buildEpisodeConnections(
    episodes: GraphRebuildEpisode[],
    events: GraphRebuildEvent[],
    temporalEdges: GraphRebuildTemporalEdge[],
    causalEdges: GraphRebuildCausalEdge[],
    chunkSemanticBridges: GraphRebuildChunkSemanticBridge[],
): GraphRebuildEpisodeConnection[] {
    const eventEpisode = episodeByEventId(episodes);
    const eventById = new Map(events.map((event) => [event.id, event]));
    const connections = new Map<string, GraphRebuildEpisodeConnection>();
    for (const edge of temporalEdges) {
        addEpisodeEdge(connections, 'episode_temporal', 'derived', edge, eventEpisode, eventById);
    }
    for (const edge of causalEdges) {
        addEpisodeEdge(connections, 'episode_causal', 'derived', edge, eventEpisode, eventById);
    }
    const structuralKeys = new Set([...connections.values()].map((connection) =>
        `${connection.sourceEpisodeId}->${connection.targetEpisodeId}`,
    ));
    for (const connection of buildEpisodeSemanticWormholes(episodes, events, chunkSemanticBridges, structuralKeys)) {
        connections.set(connection.id, connection);
    }
    return [...connections.values()].sort((left, right) =>
        episodeConnectionRank(left.kind) - episodeConnectionRank(right.kind)
        || left.sourceEpisodeId.localeCompare(right.sourceEpisodeId)
        || left.targetEpisodeId.localeCompare(right.targetEpisodeId)
        || right.confidence - left.confidence,
    );
}

function addEpisodeEdge(
    connections: Map<string, GraphRebuildEpisodeConnection>,
    kind: 'episode_temporal' | 'episode_causal',
    status: 'derived',
    edge: GraphRebuildTemporalEdge | GraphRebuildCausalEdge,
    eventEpisode: Map<string, GraphRebuildEpisode>,
    eventById: Map<string, GraphRebuildEvent>,
): void {
    const sourceEpisode = eventEpisode.get(edge.sourceId);
    const targetEpisode = eventEpisode.get(edge.targetId);
    if (!sourceEpisode || !targetEpisode || sourceEpisode.id === targetEpisode.id) return;
    const relationType = kind === 'episode_temporal'
        ? `episode_${edge.relationType}`
        : `episode_${edge.relationType}`;
    const id = `${kind}:${sourceEpisode.id}:${relationType}:${targetEpisode.id}`;
    const sourceEvent = eventById.get(edge.sourceId);
    const targetEvent = eventById.get(edge.targetId);
    const sharedEntityIds = intersect(sourceEpisode.entityIds, targetEpisode.entityIds);
    const current = connections.get(id);
    const eventEdgeIds = current ? unique([...current.eventEdgeIds, edge.id]) : [edge.id];
    const evidenceIds = current ? unique([...current.evidenceIds, ...edge.evidenceIds]) : [...edge.evidenceIds];
    connections.set(id, {
        id,
        kind,
        sourceEpisodeId: sourceEpisode.id,
        targetEpisodeId: targetEpisode.id,
        relationType,
        eventEdgeIds,
        evidenceIds,
        sharedEntityIds,
        confidence: current ? Math.max(current.confidence, edge.confidence) : edge.confidence,
        status,
        rationale: [
            `${kind}:event_edge_aggregate`,
            `event_edges:${eventEdgeIds.length}`,
            sourceEvent && targetEvent ? `boundary:${sourceEvent.label}->${targetEvent.label}` : '',
            sharedEntityIds.length ? `shared_entities:${sharedEntityIds.length}` : '',
        ].filter(Boolean),
    });
}

function buildEpisodeSemanticWormholes(
    episodes: GraphRebuildEpisode[],
    events: GraphRebuildEvent[],
    chunkSemanticBridges: GraphRebuildChunkSemanticBridge[],
    structuralKeys: Set<string>,
): GraphRebuildEpisodeConnection[] {
    const episodeByEvent = episodeByEventId(episodes);
    const episodeById = new Map(episodes.map((episode) => [episode.id, episode]));
    const eventById = new Map(events.map((event) => [event.id, event]));
    const eventByChunk = new Map(events.filter((event) => event.chunkId).map((event) => [event.chunkId as string, event]));
    const byPair = new Map<string, GraphRebuildEpisodeConnection>();
    for (const bridge of chunkSemanticBridges) {
        const sourceEvent = bridge.sourceEventId ? eventById.get(bridge.sourceEventId) : eventByChunk.get(bridge.sourceChunkId);
        const targetEvent = bridge.targetEventId ? eventById.get(bridge.targetEventId) : eventByChunk.get(bridge.targetChunkId);
        const sourceEpisode = bridge.sourceEpisodeId
            ? episodeById.get(bridge.sourceEpisodeId)
            : sourceEvent ? episodeByEvent.get(sourceEvent.id) : undefined;
        const targetEpisode = bridge.targetEpisodeId
            ? episodeById.get(bridge.targetEpisodeId)
            : targetEvent ? episodeByEvent.get(targetEvent.id) : undefined;
        if (!sourceEpisode || !targetEpisode || sourceEpisode.id === targetEpisode.id) continue;
        if (structuralKeys.has(`${sourceEpisode.id}->${targetEpisode.id}`)) continue;
        const relationType = `episode_${bridge.bridgeType}`;
        const id = `episode_wormhole:${sourceEpisode.id}:${bridge.bridgeType}:${targetEpisode.id}`;
        const current = byPair.get(id);
        const chunkBridgeIds = unique([...(current?.chunkBridgeIds || []), bridge.id]);
        byPair.set(id, {
            id,
            kind: 'episode_wormhole',
            sourceEpisodeId: sourceEpisode.id,
            targetEpisodeId: targetEpisode.id,
            relationType,
            bridgeType: bridge.bridgeType,
            claim: current?.claim || bridge.claim,
            eventEdgeIds: [],
            chunkBridgeIds,
            evidenceIds: unique([...(current?.evidenceIds || []), ...bridge.evidenceIds]),
            sharedEntityIds: unique([...(current?.sharedEntityIds || []), ...bridge.supportingEntityIds]),
            confidence: current ? Math.max(current.confidence, bridge.confidence) : bridge.confidence,
            status: 'overlay_only',
            semanticVerbs: unique([...(current?.semanticVerbs || []), ...bridge.semanticVerbs]),
            rationale: unique([
                ...(current?.rationale || []),
                'episode_wormhole_overlay:no_topology_commit',
                'chunk_semantic_bridge_rollup',
                `bridge_type:${bridge.bridgeType}`,
                `chunk_bridge_count:${chunkBridgeIds.length}`,
            ]),
        });
    }
    return [...byPair.values()]
        .map((connection) => ({
            ...connection,
            confidence: clamp(connection.confidence + Math.min(0.08, (connection.chunkBridgeIds?.length || 0) * 0.01), 0, 0.9),
        }))
        .sort((left, right) =>
            chunkSemanticBridgeTypeRank(left.bridgeType || 'topic_continuation') - chunkSemanticBridgeTypeRank(right.bridgeType || 'topic_continuation')
            || right.confidence - left.confidence
            || left.id.localeCompare(right.id),
        )
        .slice(0, 32);
}

function attachChunkBridgeEpisodeIds(
    bridges: GraphRebuildChunkSemanticBridge[],
    episodes: GraphRebuildEpisode[],
    events: GraphRebuildEvent[],
): GraphRebuildChunkSemanticBridge[] {
    const episodeByEvent = episodeByEventId(episodes);
    const eventById = new Map(events.map((event) => [event.id, event]));
    const eventByChunk = new Map(events.filter((event) => event.chunkId).map((event) => [event.chunkId as string, event]));
    return bridges.map((bridge) => {
        const sourceEvent = bridge.sourceEventId ? eventById.get(bridge.sourceEventId) : eventByChunk.get(bridge.sourceChunkId);
        const targetEvent = bridge.targetEventId ? eventById.get(bridge.targetEventId) : eventByChunk.get(bridge.targetChunkId);
        return {
            ...bridge,
            sourceEpisodeId: bridge.sourceEpisodeId || (sourceEvent ? episodeByEvent.get(sourceEvent.id)?.id : undefined),
            targetEpisodeId: bridge.targetEpisodeId || (targetEvent ? episodeByEvent.get(targetEvent.id)?.id : undefined),
        };
    });
}

function countChunkSemanticBridges(
    bridges: GraphRebuildChunkSemanticBridge[],
    bridgeType: GraphRebuildChunkSemanticBridgeType,
): number {
    return bridges.filter((bridge) => bridge.bridgeType === bridgeType).length;
}

function episodeByEventId(episodes: GraphRebuildEpisode[]): Map<string, GraphRebuildEpisode> {
    const out = new Map<string, GraphRebuildEpisode>();
    for (const episode of episodes) {
        for (const eventId of episode.eventIds) out.set(eventId, episode);
    }
    return out;
}

function episodeConnectionRank(kind: GraphRebuildEpisodeConnection['kind']): number {
    if (kind === 'episode_temporal') return 0;
    if (kind === 'episode_causal') return 1;
    return 2;
}

function intersect(left: string[], right: string[]): string[] {
    const rightSet = new Set(right);
    return unique(left.filter((value) => rightSet.has(value)));
}

function buildTemporalEdges(events: GraphRebuildEvent[]): GraphRebuildTemporalEdge[] {
    const out: GraphRebuildTemporalEdge[] = [];
    for (const noteEvents of eventsByNote(events)) {
        for (let index = 1; index < noteEvents.length; index += 1) {
            const previous = noteEvents[index - 1];
            const event = noteEvents[index];
            if (!sharesEntity(previous, event)) continue;
            out.push({
                id: `temporal:${previous.id}:${event.id}`,
                sourceId: previous.id,
                targetId: event.id,
                relationType: 'before',
                evidenceIds: [previous.id, event.id],
                confidence: Math.max(0.62, 0.74 - index * 0.0001),
            });
        }
    }
    return out;
}

function sharesEntity(left: GraphRebuildEvent, right: GraphRebuildEvent): boolean {
    return left.entityIds.some((entityId) => right.entityIds.includes(entityId));
}

function eventsByNote(events: GraphRebuildEvent[]): GraphRebuildEvent[][] {
    const buckets = new Map<string, GraphRebuildEvent[]>();
    for (const event of events) {
        buckets.set(event.noteId, [...(buckets.get(event.noteId) || []), event]);
    }
    return [...buckets.values()];
}

function hasAny(text: string, needles: readonly string[]): boolean {
    return needles.some((needle) => text.includes(needle));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}

const HABITUAL_CUES = ['keeps ', 'kept ', 'every ', 'often', 'usually', 'always', 'again', 'repeated'] as const;
const PLANNED_CUES = ['planned', 'wanted', 'needed', 'would ', 'could ', 'may ', 'might ', 'preparing', 'assigned', 'authorized'] as const;
const ATTEMPT_CUES = ['tried', 'trying', 'attempt', 'attempted', 'struggled'] as const;
const ONGOING_CUES = ['continues', 'continued', 'started', 'began', 'moving', 'selecting', 'expanding', 'breathing', 'stirred'] as const;
const STATE_CUES = [' is ', ' was ', ' are ', ' were ', 'remained', 'stayed', 'stood', 'sat ', 'sits ', 'has ', 'had '] as const;
const DIALOGUE_CUES = ['said', 'asked', 'answered', 'spoke', 'replied', 'murmured'] as const;
const COMPLETED_CUES = ['approved', 'signed', 'entered', 'arrived', 'opened', 'handed', 'gave', 'took ', 'read ', 'moved', 'walked', 'warned'] as const;
