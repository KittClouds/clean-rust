import type {
    GraphRebuildEdge,
    GraphRebuildEmbeddingBackboneEdge,
    GraphRebuildEmbeddingGraphPostProcess,
    GraphRebuildEmbeddingTargetPostProcess,
    GraphRebuildEntityAnchor,
    GraphRebuildEntityLinkCounters,
    GraphRebuildEntityLinkDecision,
    GraphRebuildEntityLinkSuggestion,
    GraphRebuildMention,
    GraphRebuildNode,
    GraphRebuildRelationship,
    GraphRebuildShadowLink,
    GraphRebuildStructuralPostProcess,
} from './graph-rebuild-snapshot';
import {
    buildRelationDuplicateShadowLinks,
    shadowEntityLink,
} from './graph-rebuild-shadow-linking';

const MAX_ENTITY_LINK_SUGGESTIONS = 48;
const MAX_LINKER_CANDIDATES_PER_MENTION = 4;
const MIN_LINKER_CANDIDATE_SCORE = 0.42;
export const GLINER_LINKER_MODEL_ID = 'knowledgator/gliner-linker-base-v1.0';

interface EntityLinkIndex {
    nodesById: Map<string, GraphRebuildNode>;
    nodeSurfaceClaims: Map<string, GraphRebuildNode[]>;
    acceptedBySurface: Map<string, GraphRebuildEntityAnchor[]>;
    structuralByEntity: Map<string, GraphRebuildStructuralPostProcess['nodes'][number]>;
    edgeByPair: Map<string, GraphRebuildEdge>;
    embeddingByEntity: Map<string, GraphRebuildEmbeddingTargetPostProcess>;
    embeddingEdgeByPair: Map<string, GraphRebuildEmbeddingBackboneEdge>;
}

export function buildGraphRebuildEntityLinkSuggestions(input: {
    mentions: GraphRebuildMention[];
    entityAnchors: GraphRebuildEntityAnchor[];
    nodes: GraphRebuildNode[];
    edges: GraphRebuildEdge[];
    relationships?: GraphRebuildRelationship[];
    structuralPostProcess: GraphRebuildStructuralPostProcess;
    embeddingGraphPostProcess?: GraphRebuildEmbeddingGraphPostProcess;
}): { suggestions: GraphRebuildShadowLink[]; counters: GraphRebuildEntityLinkCounters } {
    const index = buildIndex(input);
    const suggestions = [
        ...unresolvedMentionSuggestions(input.mentions, index),
        ...linkerCandidateSuggestions(input.mentions, index),
        ...aliasSuggestions(input.entityAnchors, index),
        ...duplicateEntitySuggestions(input.nodes, index),
        ...buildRelationDuplicateShadowLinks(input.relationships || [], input.nodes),
    ];
    const uniqueSuggestions = uniqueById(suggestions)
        .sort((left, right) => right.rerankScore - left.rerankScore || left.id.localeCompare(right.id))
        .slice(0, MAX_ENTITY_LINK_SUGGESTIONS);
    return { suggestions: uniqueSuggestions, counters: countersFor(uniqueSuggestions, input.mentions) };
}

function buildIndex(input: {
    entityAnchors: GraphRebuildEntityAnchor[];
    nodes: GraphRebuildNode[];
    edges: GraphRebuildEdge[];
    structuralPostProcess: GraphRebuildStructuralPostProcess;
    embeddingGraphPostProcess?: GraphRebuildEmbeddingGraphPostProcess;
}): EntityLinkIndex {
    const nodesById = new Map(input.nodes.map((node) => [node.id, node]));
    const nodeSurfaceClaims = new Map<string, GraphRebuildNode[]>();
    for (const node of input.nodes) {
        addNodeClaim(nodeSurfaceClaims, node.label, node);
        for (const alias of node.aliases || []) addNodeClaim(nodeSurfaceClaims, alias, node);
    }
    const acceptedBySurface = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of input.entityAnchors) mapArray(acceptedBySurface, normalize(anchor.surface)).push(anchor);
    const structuralByEntity = new Map(input.structuralPostProcess.nodes.map((row) => [row.entityId, row]));
    const edgeByPair = new Map(input.edges.map((edge) => [pairKey(edge.sourceId, edge.targetId), edge]));
    const embeddingByEntity = new Map<string, GraphRebuildEmbeddingTargetPostProcess>();
    const embeddingEdgeByPair = new Map<string, GraphRebuildEmbeddingBackboneEdge>();
    if (input.embeddingGraphPostProcess) {
        for (const row of input.embeddingGraphPostProcess.targets) {
            const entityId = entityIdFromTarget(row.targetId);
            if (entityId) embeddingByEntity.set(entityId, row);
        }
        for (const edge of input.embeddingGraphPostProcess.backboneEdges) {
            const left = entityIdFromTarget(edge.sourceTargetId);
            const right = entityIdFromTarget(edge.targetTargetId);
            if (left && right) embeddingEdgeByPair.set(pairKey(left, right), edge);
        }
    }
    return { nodesById, nodeSurfaceClaims, acceptedBySurface, structuralByEntity, edgeByPair, embeddingByEntity, embeddingEdgeByPair };
}

function unresolvedMentionSuggestions(mentions: GraphRebuildMention[], index: EntityLinkIndex): GraphRebuildShadowLink[] {
    const out: GraphRebuildShadowLink[] = [];
    for (const mention of mentions) {
        if (mention.status === 'accepted') continue;
        const normalized = normalize(mention.surface);
        if (!normalized) continue;
        const candidates = uniqueNodes(index.nodeSurfaceClaims.get(normalized) || []);
        if (candidates.length === 1) {
            out.push(shadowEntityLink(
                suggestionForMention(mention, candidates[0], 'same_entity', index, ['surface: exact label or alias match']),
                'same_entity_suspicion',
            ));
        } else if (candidates.length > 1) {
            out.push(shadowEntityLink(ambiguousSuggestion(mention, candidates, index), 'query_assist'));
        } else if (mention.status === 'dropped') {
            out.push(shadowEntityLink(newEntitySuggestion(mention), 'query_assist'));
        }
    }
    return out;
}

function linkerCandidateSuggestions(mentions: GraphRebuildMention[], index: EntityLinkIndex): GraphRebuildShadowLink[] {
    const out: GraphRebuildShadowLink[] = [];
    for (const mention of mentions) {
        if (!shouldProbeLinkerCandidates(mention)) continue;
        const candidates = retrieveLinkerCandidates(mention, index).slice(0, MAX_LINKER_CANDIDATES_PER_MENTION);
        if (!candidates.length) continue;
        const best = candidates[0];
        const decision: GraphRebuildEntityLinkDecision = best.score >= 0.72 ? 'same_entity' : 'ambiguous';
        const suggestion = suggestionForMention(mention, best.node, decision, index, [
            `linker: narrow candidate set ${candidates.length}`,
            `linker: lexical prior ${Math.round(best.score * 100)}%`,
        ]);
        suggestion.id = `entity-link:linker:${mention.id}:${best.node.id}`;
        suggestion.status = 'review';
        suggestion.confidence = clamp(suggestion.confidence * 0.72 + best.score * 0.28, 0.2, 0.97);
        suggestion.rerankScore = clamp(suggestion.rerankScore + best.score * 0.08, 0.2, 0.98);
        suggestion.competingEntityIds = candidates.map((candidate) => candidate.node.id);
        suggestion.linkerCandidateEntityIds = suggestion.competingEntityIds;
        suggestion.linkerWindowId = linkerWindowId(mention);
        suggestion.rerankSignals = unique([...suggestion.rerankSignals, `linker:candidate_set:${candidates.length}`, `linker:window:${suggestion.linkerWindowId}`]);
        suggestion.rationale = unique([...suggestion.rationale, ...best.reasons.map((reason) => `linker: ${reason}`)]);
        out.push(shadowEntityLink(suggestion, 'same_entity_suspicion', {
            clusterHintIds: suggestion.rerankSignals.filter((signal) => signal.startsWith('embedding:')),
        }));
    }
    return out;
}

function aliasSuggestions(anchors: GraphRebuildEntityAnchor[], index: EntityLinkIndex): GraphRebuildShadowLink[] {
    const out: GraphRebuildShadowLink[] = [];
    for (const anchor of anchors) {
        const node = index.nodesById.get(anchor.entityId);
        if (!node || knownSurface(node, anchor.surface)) continue;
        const repeated = (index.acceptedBySurface.get(normalize(anchor.surface)) || []).filter((row) => row.entityId === anchor.entityId);
        if (repeated.length < 1) continue;
        out.push(shadowEntityLink(
            suggestionForMention(anchor, node, 'alias_of', index, [
                'surface: accepted anchor uses a non-canonical surface',
                `alias: ${repeated.length} accepted occurrence(s) can become a registry alias`,
            ]),
            'alias_suspicion',
        ));
    }
    return out;
}

function duplicateEntitySuggestions(nodes: GraphRebuildNode[], index: EntityLinkIndex): GraphRebuildShadowLink[] {
    const buckets = new Map<string, GraphRebuildNode[]>();
    for (const node of nodes) {
        for (const token of normalizedTokens(node.label)) mapArray(buckets, token).push(node);
    }
    const out: GraphRebuildShadowLink[] = [];
    const seenPairs = new Set<string>();
    for (const bucket of buckets.values()) {
        if (bucket.length < 2 || bucket.length > 16) continue;
        const uniqueBucket = uniqueNodes(bucket);
        for (let i = 0; i < uniqueBucket.length; i += 1) {
            for (let j = i + 1; j < uniqueBucket.length; j += 1) {
                const left = uniqueBucket[i];
                const right = uniqueBucket[j];
                const key = pairKey(left.id, right.id);
                if (seenPairs.has(key) || kindFamily(left.kind) !== kindFamily(right.kind)) continue;
                seenPairs.add(key);
                const lexical = jaccard(normalizedTokens(left.label), normalizedTokens(right.label));
                if (lexical < 0.5) continue;
                out.push(shadowEntityLink(pairSuggestion(left, right, index, lexical), 'same_entity_suspicion'));
            }
        }
    }
    return out;
}

function suggestionForMention(
    mention: GraphRebuildMention,
    node: GraphRebuildNode,
    decision: GraphRebuildEntityLinkDecision,
    index: EntityLinkIndex,
    rationale: string[],
): GraphRebuildEntityLinkSuggestion {
    const score = scoreEntityLink(node.id, undefined, index, 0.68 + mention.confidence * 0.18);
    return {
        id: `entity-link:${decision}:${mention.id}:${node.id}`,
        mentionId: mention.id,
        surface: mention.surface,
        normalizedSurface: normalize(mention.surface),
        noteId: mention.noteId,
        chunkId: mention.chunkId,
        sourceStart: mention.sourceStart,
        sourceEnd: mention.sourceEnd,
        candidateEntityId: node.id,
        candidateLabel: node.label,
        candidateKind: node.kind,
        decision,
        status: score.score >= 0.92 && decision !== 'ambiguous' ? 'confirmed' : 'review',
        confidence: score.score,
        rerankScore: score.score,
        structuralRole: score.structuralRole,
        embeddingRole: score.embeddingRole,
        productRegionRole: score.productRegionRole,
        productLane: score.productLane,
        competingEntityIds: [],
        evidenceIds: unique([mention.id, ...node.anchorIds.slice(0, 4)]),
        rerankSignals: score.signals,
        rationale: unique([...rationale, ...score.signals.map((signal) => `rerank: ${signal}`)]),
    };
}

function ambiguousSuggestion(mention: GraphRebuildMention, candidates: GraphRebuildNode[], index: EntityLinkIndex): GraphRebuildEntityLinkSuggestion {
    const best = candidates
        .map((node) => ({ node, score: scoreEntityLink(node.id, undefined, index, 0.48 + mention.confidence * 0.12) }))
        .sort((left, right) => right.score.score - left.score.score || left.node.id.localeCompare(right.node.id))[0];
    return {
        ...suggestionForMention(mention, best.node, 'ambiguous', index, ['surface: multiple registered entities claim this text']),
        id: `entity-link:ambiguous:${mention.id}`,
        status: 'review',
        competingEntityIds: candidates.map((node) => node.id).sort(),
    };
}

function newEntitySuggestion(mention: GraphRebuildMention): GraphRebuildEntityLinkSuggestion {
    const score = clamp(0.38 + mention.confidence * 0.28, 0.34, 0.72);
    return {
        id: `entity-link:new_entity:${mention.id}`,
        mentionId: mention.id,
        surface: mention.surface,
        normalizedSurface: normalize(mention.surface),
        noteId: mention.noteId,
        chunkId: mention.chunkId,
        sourceStart: mention.sourceStart,
        sourceEnd: mention.sourceEnd,
        decision: 'new_entity',
        status: 'review',
        confidence: score,
        rerankScore: score,
        competingEntityIds: [],
        evidenceIds: [mention.id],
        rerankSignals: ['surface:new_candidate'],
        rationale: ['surface: no registered entity claims this mention yet'],
    };
}

function pairSuggestion(left: GraphRebuildNode, right: GraphRebuildNode, index: EntityLinkIndex, lexical: number): GraphRebuildEntityLinkSuggestion {
    const score = scoreEntityLink(left.id, right.id, index, 0.42 + lexical * 0.22);
    return {
        id: `entity-link:same_entity:${pairKey(left.id, right.id)}`,
        surface: left.label,
        normalizedSurface: normalize(left.label),
        candidateEntityId: left.id,
        candidateLabel: left.label,
        candidateKind: left.kind,
        decision: 'same_entity',
        status: 'review',
        confidence: score.score,
        rerankScore: score.score,
        structuralRole: score.structuralRole,
        embeddingRole: score.embeddingRole,
        productRegionRole: score.productRegionRole,
        productLane: score.productLane,
        competingEntityIds: [right.id],
        evidenceIds: unique([...left.anchorIds.slice(0, 2), ...right.anchorIds.slice(0, 2)]),
        rerankSignals: score.signals,
        rationale: [`surface: labels share ${Math.round(lexical * 100)}% token overlap`, ...score.signals.map((signal) => `rerank: ${signal}`)],
    };
}

function shouldProbeLinkerCandidates(mention: GraphRebuildMention): boolean {
    if (mention.status === 'accepted') return false;
    const normalized = normalize(mention.surface);
    if (normalized.length < 3) return false;
    const source = String(mention.source || '').toLowerCase();
    return source.includes('machine') || source.includes('suggestion') || source.includes('ner') || source.includes('atlas');
}

function retrieveLinkerCandidates(mention: GraphRebuildMention, index: EntityLinkIndex): Array<{
    node: GraphRebuildNode;
    score: number;
    reasons: string[];
}> {
    const surface = normalize(mention.surface);
    if (!surface || index.nodeSurfaceClaims.has(surface)) return [];
    const mentionTokens = normalizedTokens(surface);
    const candidates: Array<{ node: GraphRebuildNode; score: number; reasons: string[] }> = [];
    for (const node of index.nodesById.values()) {
        const scored = scoreLinkerCandidate(mentionTokens, surface, node);
        if (scored.score < MIN_LINKER_CANDIDATE_SCORE) continue;
        candidates.push({ node, score: scored.score, reasons: scored.reasons });
    }
    return candidates.sort((left, right) =>
        right.score - left.score ||
        right.node.totalMentions - left.node.totalMentions ||
        left.node.id.localeCompare(right.node.id));
}

function scoreLinkerCandidate(mentionTokens: string[], surface: string, node: GraphRebuildNode): { score: number; reasons: string[] } {
    const reasons: string[] = [];
    let score = 0;
    const surfaces = unique([node.label, ...(node.aliases || [])]).map((value) => normalize(value)).filter(Boolean);
    for (const candidate of surfaces) {
        const candidateTokens = normalizedTokens(candidate);
        const tokenOverlap = jaccard(mentionTokens, candidateTokens);
        const contains = candidate.includes(surface) || surface.includes(candidate);
        const prefix = candidateTokens.some((token) => mentionTokens.some((mentionToken) =>
            token.startsWith(mentionToken) ||
            mentionToken.startsWith(token) ||
            (token.length > 3 && mentionToken.length > 3 && token.slice(0, 3) === mentionToken.slice(0, 3))));
        const firstTokenStem = firstTokenStemMatch(mentionTokens, candidateTokens);
        let candidateScore = tokenOverlap;
        if (contains) candidateScore = Math.max(candidateScore, 0.78);
        if (firstTokenStem) candidateScore = Math.max(candidateScore, 0.74);
        if (prefix) candidateScore = Math.max(candidateScore, 0.48);
        if (candidateScore > score) {
            score = candidateScore;
            reasons.length = 0;
            if (tokenOverlap > 0) reasons.push(`token overlap ${Math.round(tokenOverlap * 100)}%`);
            if (contains) reasons.push('surface containment');
            if (firstTokenStem) reasons.push('first-token stem');
            if (prefix) reasons.push('token prefix');
        }
    }
    if (score > 0 && node.totalMentions > 1) {
        score += Math.min(0.08, Math.log2(node.totalMentions) * 0.012);
        reasons.push(`anchor support ${node.totalMentions}`);
    }
    return { score: clamp(score, 0, 1), reasons };
}

function firstTokenStemMatch(mentionTokens: string[], candidateTokens: string[]): boolean {
    const mentionFirst = mentionTokens[0] || '';
    const candidateFirst = candidateTokens[0] || '';
    return candidateFirst.length >= 4
        && mentionFirst.length > candidateFirst.length
        && mentionFirst.startsWith(candidateFirst);
}

function linkerWindowId(mention: GraphRebuildMention): string {
    const note = mention.noteId || 'note';
    const start = Math.max(0, Math.floor((mention.sourceStart || 0) / 900));
    return `${note}:${start}`;
}

function scoreEntityLink(leftId: string, rightId: string | undefined, index: EntityLinkIndex, base: number): {
    score: number;
    structuralRole?: GraphRebuildEntityLinkSuggestion['structuralRole'];
    embeddingRole?: GraphRebuildEntityLinkSuggestion['embeddingRole'];
    productRegionRole?: GraphRebuildEntityLinkSuggestion['productRegionRole'];
    productLane?: GraphRebuildEntityLinkSuggestion['productLane'];
    signals: string[];
} {
    const signals: string[] = [];
    let score = base;
    const leftStructure = index.structuralByEntity.get(leftId);
    const rightStructure = rightId ? index.structuralByEntity.get(rightId) : undefined;
    const structuralRole = rightId && index.edgeByPair.get(pairKey(leftId, rightId)) ? 'shared_component' : leftStructure?.role || rightStructure?.role;
    if (leftStructure?.role === 'hub' || rightStructure?.role === 'hub') score += 0.05;
    if (leftStructure && rightStructure && leftStructure.componentId === rightStructure.componentId) score += 0.06;
    if (structuralRole) signals.push(`structure:${structuralRole}`);
    const leftEmbedding = index.embeddingByEntity.get(leftId);
    const rightEmbedding = rightId ? index.embeddingByEntity.get(rightId) : undefined;
    const embeddingEdge = rightId ? index.embeddingEdgeByPair.get(pairKey(leftId, rightId)) : undefined;
    let embeddingRole: GraphRebuildEntityLinkSuggestion['embeddingRole'];
    if (embeddingEdge) {
        embeddingRole = embeddingEdge.role;
        score += embeddingEdge.role === 'backbone' ? 0.08 : 0.055;
        signals.push(`embedding:${embeddingEdge.role}`);
    } else if (leftEmbedding && rightEmbedding && leftEmbedding.clusterId === rightEmbedding.clusterId) {
        embeddingRole = 'same_cluster';
        score += 0.045;
        signals.push(`embedding:same_cluster:${leftEmbedding.clusterId}`);
    }
    const region = leftEmbedding?.productTopologyRegion || rightEmbedding?.productTopologyRegion;
    if (region) {
        score += region.role === 'core' ? 0.035 : region.role === 'bridge' ? 0.025 : 0.012;
        signals.push(`product_region:${region.role}`);
    }
    const productLane = leftEmbedding?.productLaneFeatures.dominantLane || rightEmbedding?.productLaneFeatures.dominantLane;
    if (productLane) signals.push(`product_lane:${productLane}`);
    return {
        score: clamp(score, 0.2, 0.98),
        structuralRole,
        embeddingRole,
        productRegionRole: region?.role,
        productLane,
        signals,
    };
}

function countersFor(suggestions: GraphRebuildShadowLink[], mentions: GraphRebuildMention[]): GraphRebuildEntityLinkCounters {
    return {
        candidateMentions: mentions.filter((mention) => mention.status !== 'accepted').length,
        candidateLinks: suggestions.length,
        sameEntity: countDecision(suggestions, 'same_entity'),
        aliasOf: countDecision(suggestions, 'alias_of'),
        newEntity: countDecision(suggestions, 'new_entity'),
        ambiguous: countDecision(suggestions, 'ambiguous'),
        rejected: countDecision(suggestions, 'reject'),
        shadowLinks: suggestions.length,
        linkerCandidates: suggestions.filter((suggestion) => suggestion.linkerCandidateEntityIds?.length).length,
        autoConfirmable: suggestions.filter((suggestion) => suggestion.status === 'confirmed').length,
    };
}

function addNodeClaim(map: Map<string, GraphRebuildNode[]>, surface: string, node: GraphRebuildNode): void {
    const normalized = normalize(surface);
    if (normalized) mapArray(map, normalized).push(node);
}

function knownSurface(node: GraphRebuildNode, surface: string): boolean {
    const normalized = normalize(surface);
    return normalized === normalize(node.label) || (node.aliases || []).some((alias) => normalize(alias) === normalized);
}

function entityIdFromTarget(targetId: string): string {
    return targetId.startsWith('embed:entity:') ? targetId.slice('embed:entity:'.length) : '';
}

function normalizedTokens(value: string): string[] {
    return normalize(value).split(' ').filter((token) => token.length > 2);
}

function kindFamily(kind: string): string {
    const normalized = String(kind || '').toUpperCase();
    if (normalized === 'PERSON' || normalized === 'NPC' || normalized === 'CREATURE') return 'CHARACTER';
    if (normalized === 'ORGANIZATION' || normalized === 'FACTION') return 'NETWORK';
    return normalized;
}

function jaccard(left: string[], right: string[]): number {
    const a = new Set(left);
    const b = new Set(right);
    let shared = 0;
    for (const value of a) if (b.has(value)) shared += 1;
    return shared / Math.max(1, a.size + b.size - shared);
}

function countDecision(suggestions: GraphRebuildShadowLink[], decision: GraphRebuildEntityLinkDecision): number {
    return suggestions.filter((suggestion) => suggestion.decision === decision).length;
}

function uniqueNodes(nodes: GraphRebuildNode[]): GraphRebuildNode[] {
    return uniqueBy(nodes, (node) => node.id);
}

function uniqueById(suggestions: GraphRebuildShadowLink[]): GraphRebuildShadowLink[] {
    return uniqueBy(suggestions, (suggestion) => suggestion.id);
}

function uniqueBy<T>(values: T[], keyOf: (value: T) => string): T[] {
    const seen = new Set<string>();
    const out: T[] = [];
    for (const value of values) {
        const key = keyOf(value);
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(value);
    }
    return out;
}

function mapArray<K, V>(map: Map<K, V[]>, key: K): V[] {
    const current = map.get(key);
    if (current) return current;
    const created: V[] = [];
    map.set(key, created);
    return created;
}

function pairKey(left: string, right: string): string {
    return [left, right].sort().join('\u0000');
}

function normalize(value: string): string {
    return String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}
