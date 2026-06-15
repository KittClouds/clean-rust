import type {
    BuildGraphRebuildSnapshotInput,
    GraphRebuildCausalEdge,
    GraphRebuildChunk,
    GraphRebuildEmbeddingTarget,
    GraphRebuildEmbeddingTargetPlan,
    GraphRebuildEntityAnchor,
    GraphRebuildEvent,
    GraphRebuildMemoryState,
    GraphRebuildNode,
    GraphRebuildRelationship,
    GraphRebuildTemporalEdge,
} from './graph-rebuild-snapshot';
import type {
    GraphDocumentCompilerSummary,
    GraphDocumentHyperedge,
    GraphDocumentHyperedgeRole,
} from './graph-document-compiler-types';
import { selectGraphRebuildEmbeddingTargetPlan } from './graph-rebuild-embedding-target-policy';
import { summarizeMeaningFrame } from './graph-rebuild-meaning-frames';

type StructuralRootKey = 'document-structure' | 'identity' | 'temporal' | 'causal' | 'evidence';

const STRUCTURAL_ROOTS: Array<{ key: StructuralRootKey; label: string; text: string }> = [
    { key: 'document-structure', label: 'Document structure', text: 'document spine and chunk hierarchy root' },
    { key: 'identity', label: 'Identity root', text: 'accepted entity and alias provenance root' },
    { key: 'temporal', label: 'Temporal root', text: 'event order and before/after signal root' },
    { key: 'causal', label: 'Causal root', text: 'cause, explanation, authority, and consequence signal root' },
    { key: 'evidence', label: 'Evidence root', text: 'raw anchor evidence and supporting context root' },
];

export function buildGraphRebuildEmbeddingTargetPlan(
    input: BuildGraphRebuildSnapshotInput,
    chunks: GraphRebuildChunk[],
    anchors: GraphRebuildEntityAnchor[],
    nodes: GraphRebuildNode[],
    relationships: GraphRebuildRelationship[],
    events: GraphRebuildEvent[],
    temporalEdges: GraphRebuildTemporalEdge[],
    causalEdges: GraphRebuildCausalEdge[],
    memoryState: GraphRebuildMemoryState[],
    documentCompiler?: GraphDocumentCompilerSummary,
): GraphRebuildEmbeddingTargetPlan & { targets: GraphRebuildEmbeddingTarget[] } {
    const targets: GraphRebuildEmbeddingTarget[] = [];
    const nodeByEntityId = new Map(nodes.map((node) => [node.entityId, node]));
    const anchorById = new Map(anchors.map((anchor) => [anchor.id, anchor]));
    const anchorsByEntityId = groupAnchorsByEntity(anchors);
    const anchorsByChunkId = groupAnchorsByChunk(anchors);
    const eventById = new Map(events.map((event) => [event.id, event]));
    const noteIds = input.noteIds?.length ? input.noteIds : unique([...chunks.map((chunk) => chunk.noteId), ...anchors.map((anchor) => anchor.noteId)]);
    for (const noteId of noteIds) targets.push({
        id: `embed:note:${noteId}`,
        kind: 'note',
        sourceId: noteId,
        noteId,
        ...folderFields(input, noteId),
        label: `Note ${noteId}`,
        text: noteText(input, noteId),
        evidenceIds: [],
    });
    for (const noteId of noteIds) {
        for (const root of STRUCTURAL_ROOTS) {
            targets.push({
                id: structureRootId(noteId, root.key),
                kind: 'structureRoot',
                sourceId: `${noteId}:${root.key}`,
                noteId,
                ...folderFields(input, noteId),
                label: root.label,
                text: `structure_root:${root.key} note:${noteId} ${root.text}`,
                evidenceIds: [],
                parentIds: [`embed:note:${noteId}`],
            });
        }
    }
    for (const chunk of chunks) targets.push({
        id: `embed:chunk:${chunk.id}`,
        kind: 'chunk',
        sourceId: chunk.id,
        noteId: chunk.noteId,
        chunkId: chunk.id,
        ...folderFields(input, chunk.noteId),
        label: `Chunk ${chunk.ordinal + 1}`,
        text: chunkText(input, chunk, anchorsByChunkId.get(chunk.id) || [], nodeByEntityId),
        evidenceIds: [],
        parentIds: [structureRootId(chunk.noteId, 'document-structure')],
    });
    for (const node of nodes) {
        const entityAnchors = anchorsByEntityId.get(node.entityId) || [];
        targets.push({
            id: `embed:entity:${node.entityId}`,
            kind: 'entity',
            sourceId: node.entityId,
            entityId: node.entityId,
            entityKind: node.kind,
            ...entityFolderFields(input, entityAnchors),
            label: node.label,
            text: entityText(input, node, entityAnchors),
            evidenceIds: node.anchorIds,
            parentIds: entityParentIds(entityAnchors),
        });
    }
    for (const anchor of anchors) targets.push({
        id: `embed:anchor:${anchor.id}`,
        kind: 'anchor',
        sourceId: anchor.id,
        noteId: anchor.noteId,
        chunkId: anchor.chunkId,
        entityId: anchor.entityId,
        entityKind: nodeByEntityId.get(anchor.entityId)?.kind,
        ...folderFields(input, anchor.noteId),
        label: anchor.surface,
        text: anchorText(input, anchor, nodeByEntityId.get(anchor.entityId)),
        evidenceIds: [anchor.id],
        parentIds: [structureRootId(anchor.noteId, 'evidence')],
    });
    for (const relationship of relationships) {
        if (relationship.status === 'rejected') continue;
        const sourceLabel = entityLabel(relationship.sourceEntityId, nodeByEntityId);
        const targetLabel = entityLabel(relationship.targetEntityId, nodeByEntityId);
        targets.push({
            id: `embed:graph-fact:${relationship.id}`,
            kind: 'graphFact',
            sourceId: relationship.id,
            ...relationshipFolderFields(input, relationship, anchorById),
            label: `${sourceLabel} ${relationship.relationType} ${targetLabel}`,
            text: relationshipText(input, relationship, nodeByEntityId, anchorById),
            evidenceIds: relationship.evidenceAnchorIds,
            parentIds: relationshipParentIds(relationship, anchorById),
        });
    }
    for (const event of events) targets.push({
        id: `embed:event:${event.id}`,
        kind: 'event',
        sourceId: event.id,
        noteId: event.noteId,
        chunkId: event.chunkId,
        entityId: event.entityIds[0],
        ...folderFields(input, event.noteId),
        label: event.label,
        text: eventText(input, event, nodeByEntityId, anchorById),
        evidenceIds: event.evidenceAnchorIds,
        parentIds: eventParentIds(event),
    });
    for (const edge of temporalEdges) targets.push(temporalTarget(input, edge, 'temporalFact', eventById, anchorById));
    for (const edge of causalEdges) targets.push(temporalTarget(input, edge, 'causalFact', eventById, anchorById));
    for (const state of memoryState) targets.push({
        id: `embed:memory:${state.id}`,
        kind: 'memoryState',
        sourceId: state.id,
        noteId: state.noteId,
        entityId: state.entityId,
        ...folderFields(input, state.noteId),
        label: state.key,
        text: memoryText(input, state, nodeByEntityId, anchorById),
        evidenceIds: state.evidenceIds,
        parentIds: state.noteId ? [structureRootId(state.noteId, 'identity')] : [],
    });
    const targetIds = new Set(targets.map((target) => target.id));
    for (const hyperedge of documentCompiler?.hyperedges || []) {
        if (!isNativeDocumentSituationCandidate(hyperedge)) continue;
        for (const target of documentSituationTargets(input, hyperedge)) {
            if (targetIds.has(target.id)) continue;
            targetIds.add(target.id);
            targets.push(target);
        }
    }
    return selectGraphRebuildEmbeddingTargetPlan(targets, relationships, temporalEdges, causalEdges, input.embeddingStagePolicy);
}

export function buildGraphRebuildEmbeddingTargets(
    input: BuildGraphRebuildSnapshotInput,
    chunks: GraphRebuildChunk[],
    anchors: GraphRebuildEntityAnchor[],
    nodes: GraphRebuildNode[],
    relationships: GraphRebuildRelationship[],
    events: GraphRebuildEvent[],
    temporalEdges: GraphRebuildTemporalEdge[],
    causalEdges: GraphRebuildCausalEdge[],
    memoryState: GraphRebuildMemoryState[],
    documentCompiler?: GraphDocumentCompilerSummary,
): GraphRebuildEmbeddingTarget[] {
    return buildGraphRebuildEmbeddingTargetPlan(
        input,
        chunks,
        anchors,
        nodes,
        relationships,
        events,
        temporalEdges,
        causalEdges,
        memoryState,
        documentCompiler,
    ).targets;
}

function documentSituationTargets(
    input: BuildGraphRebuildSnapshotInput,
    hyperedge: GraphDocumentHyperedge,
): GraphRebuildEmbeddingTarget[] {
    const factId = `fact:document-hyperedge:${hyperedge.id}`;
    const noteId = hyperedge.provenance.noteId;
    const source = input.noteTexts?.[noteId]?.slice(
        hyperedge.provenance.sourceStart,
        hyperedge.provenance.sourceEnd,
    ).trim();
    const roleTargetIds = hyperedge.roles.map(documentRoleEmbeddingTargetId);
    const roleSummary = hyperedge.roles
        .map((role) => `${role.semanticRole || role.role}:${role.surface || role.targetId}`)
        .join(' | ');
    const roleTargets = hyperedge.roles
        .map((role) => documentRoleTarget(hyperedge, role))
        .filter((target): target is GraphRebuildEmbeddingTarget => !!target);
    const situationTarget: GraphRebuildEmbeddingTarget = {
        id: `embed:${factId}`,
        kind: 'graphFact',
        sourceId: factId,
        noteId,
        ...folderFields(input, noteId),
        label: hyperedge.frame || hyperedge.triggerPredicate || hyperedge.predicate,
        text: limitText([
            `semantic_situation:${hyperedge.semanticSituationId || hyperedge.id}`,
            `frame:${hyperedge.frame || hyperedge.predicate}`,
            hyperedge.frameFamily ? `frame_family:${hyperedge.frameFamily}` : '',
            hyperedge.factuality ? `factuality:${hyperedge.factuality}` : '',
            hyperedge.speechAct ? `speech_act:${hyperedge.speechAct}` : '',
            `confidence:${hyperedge.confidence.toFixed(2)}`,
            `roles:${roleSummary}`,
            source ? `evidence_context:${source}` : '',
        ].filter(Boolean).join('\n'), 2200),
        evidenceIds: hyperedge.evidenceSpanIds,
        parentIds: unique([
            structureRootId(noteId, hyperedge.situationKind === 'state' ? 'identity' : 'temporal'),
            ...roleTargetIds,
        ]),
    };
    return [...roleTargets, situationTarget];
}

function isNativeDocumentSituationCandidate(hyperedge: GraphDocumentHyperedge): boolean {
    return hyperedge.status === 'pending_commit'
        && hyperedge.compilationBasis === 'semantic_situation_frame'
        && Boolean(hyperedge.semanticSituationId)
        && Boolean(hyperedge.frame)
        && !(hyperedge.temporalConflictIds?.length);
}

function documentRoleEmbeddingTargetId(role: GraphDocumentHyperedgeRole): string {
    if (role.targetKind === 'entity') return `embed:entity:${role.targetId}`;
    if (role.targetKind === 'entity_mention') return `embed:atom:documentMention:${role.targetId}`;
    if (role.targetKind === 'evidence_span') return `embed:atom:documentEvidence:${role.targetId}`;
    return `embed:atom:documentUnit:${role.targetId}`;
}

function documentRoleTarget(
    hyperedge: GraphDocumentHyperedge,
    role: GraphDocumentHyperedgeRole,
): GraphRebuildEmbeddingTarget | null {
    if (role.targetKind === 'entity') return null;
    const noteId = hyperedge.provenance.noteId;
    const semanticRole = role.semanticRole || role.role;
    const kind = role.targetKind === 'entity_mention'
        ? 'concept'
        : role.targetKind === 'evidence_span'
            ? 'evidenceSpan'
            : 'documentUnit';
    const root = role.targetKind === 'evidence_span'
        ? 'evidence'
        : role.targetKind === 'entity_mention'
            ? 'identity'
            : 'document-structure';
    return {
        id: documentRoleEmbeddingTargetId(role),
        kind,
        sourceId: role.targetId,
        noteId,
        label: role.surface || semanticRole,
        text: limitText([
            `hypergraph_role:${semanticRole}`,
            `target_kind:${role.targetKind}`,
            `slot_type:${role.slotType || 'participant'}`,
            `resolved:${role.resolved !== false}`,
            `confidence:${role.confidence.toFixed(2)}`,
            role.surface ? `surface:${role.surface}` : '',
        ].filter(Boolean).join('\n'), 640),
        evidenceIds: role.targetKind === 'evidence_span'
            ? [role.targetId]
            : hyperedge.evidenceSpanIds,
        parentIds: [structureRootId(noteId, root)],
    };
}

function temporalTarget(
    input: BuildGraphRebuildSnapshotInput,
    edge: GraphRebuildTemporalEdge | GraphRebuildCausalEdge,
    kind: string,
    eventById: Map<string, GraphRebuildEvent>,
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): GraphRebuildEmbeddingTarget {
    const source = eventById.get(edge.sourceId);
    const target = eventById.get(edge.targetId);
    const rootKey: StructuralRootKey = kind === 'causalFact' ? 'causal' : 'temporal';
    return {
        id: `embed:${kind}:${edge.id}`,
        kind,
        sourceId: edge.id,
        noteId: source?.noteId || target?.noteId,
        ...folderFields(input, source?.noteId || target?.noteId || noteIdsFromEvidence(edge.evidenceIds, anchorById)[0]),
        label: edge.relationType,
        text: limitText([
            `${source?.label || edge.sourceId} ${edge.relationType} ${target?.label || edge.targetId}`,
            `confidence:${edge.confidence.toFixed(2)}`,
            ...causalTextLines(edge, kind),
            ...evidenceContexts(input, edge.evidenceIds, anchorById, 4).map((context) => `evidence_context:${context}`),
        ].filter(Boolean).join('\n'), 1800),
        evidenceIds: edge.evidenceIds,
        parentIds: unique([
            ...noteIdsFromEventsAndEvidence(source, target, edge.evidenceIds, anchorById).map((noteId) => structureRootId(noteId, rootKey)),
            `embed:event:${edge.sourceId}`,
            `embed:event:${edge.targetId}`,
        ]),
    };
}

function causalTextLines(edge: GraphRebuildTemporalEdge | GraphRebuildCausalEdge, kind: string): string[] {
    if (kind !== 'causalFact') return [];
    const causal = edge as GraphRebuildCausalEdge;
    return [
        `causal_status:${causal.status}`,
        `causal_source:${causal.sourceKind}`,
        `causal_relation_kind:${causal.relationKind || causal.relationType}`,
        `causal_polarity:${causal.polarity}`,
        `causal_modality:${causal.modality}`,
        `causal_source_semantics:${causal.sourceSemantics}`,
        `causal_evidence_class:${causal.evidenceClass}`,
        causal.cue ? `causal_cue:${causal.cue}` : '',
        typeof causal.temporalLegal === 'boolean' ? `temporal_legal:${causal.temporalLegal}` : '',
        typeof causal.sentenceDistance === 'number' ? `sentence_distance:${causal.sentenceDistance}` : '',
        typeof causal.graphSupportCount === 'number' ? `graph_support_count:${causal.graphSupportCount}` : '',
        causal.supportIds.length ? `support_ids:${causal.supportIds.slice(0, 8).join(',')}` : '',
        causal.rationale ? `rationale:${causal.rationale}` : '',
    ].filter(Boolean);
}

function noteText(input: BuildGraphRebuildSnapshotInput, noteId: string): string {
    const text = input.noteTexts?.[noteId]?.trim();
    const folder = input.noteFolders?.[noteId];
    const prefix = folder?.folderLabel ? `folder:${folder.folderLabel}\n` : '';
    return text ? `${prefix}${text.slice(0, 12000)}` : `${prefix}note:${noteId}`;
}

function chunkText(
    input: BuildGraphRebuildSnapshotInput,
    chunk: GraphRebuildChunk,
    anchors: GraphRebuildEntityAnchor[],
    nodeByEntityId: Map<string, GraphRebuildNode>,
): string {
    const text = input.noteTexts?.[chunk.noteId];
    const slice = text?.slice(chunk.start, chunk.end).trim();
    const fallback = slice || `${chunk.noteId}:${chunk.start}-${chunk.end}`;
    const frameSummary = summarizeMeaningFrame(chunk.meaningFrame);
    const entitySummary = unique(anchors.map((anchor) => entityLabel(anchor.entityId, nodeByEntityId))).slice(0, 16).join(', ');
    return limitText([
        fallback,
        frameSummary,
        entitySummary ? `entities:${entitySummary}` : '',
    ].filter(Boolean).join('\n\n'), 2600);
}

function entityText(
    input: BuildGraphRebuildSnapshotInput,
    node: GraphRebuildNode,
    anchors: GraphRebuildEntityAnchor[],
): string {
    const aliases = node.aliases.length ? `aliases:${node.aliases.join(', ')}` : '';
    return limitText([
        node.label,
        aliases,
        `kind:${node.kind} mentions:${node.totalMentions} notes:${node.noteIds.length}`,
        ...representativeAnchorContexts(input, anchors, 4).map((context) => `evidence_context:${context}`),
    ].filter(Boolean).join('\n'), 1800);
}

function anchorText(
    input: BuildGraphRebuildSnapshotInput,
    anchor: GraphRebuildEntityAnchor,
    node: GraphRebuildNode | undefined,
): string {
    return limitText([
        anchor.surface,
        `entity:${node?.label || anchor.entityId}`,
        `kind:${node?.kind || ''} source:${anchor.source} confidence:${anchor.confidence.toFixed(2)}`,
        `evidence_context:${anchorContext(input, anchor)}`,
    ].filter(Boolean).join('\n'), 900);
}

function relationshipText(
    input: BuildGraphRebuildSnapshotInput,
    relationship: GraphRebuildRelationship,
    nodeByEntityId: Map<string, GraphRebuildNode>,
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): string {
    const sourceLabel = entityLabel(relationship.sourceEntityId, nodeByEntityId);
    const targetLabel = entityLabel(relationship.targetEntityId, nodeByEntityId);
    return limitText([
        `${sourceLabel} ${relationship.relationType} ${targetLabel} [${relationship.status}]`,
        `confidence:${relationship.confidence.toFixed(2)} source:${relationship.adjudicationSource}`,
        relationship.rationale,
        relationship.decisionEvidence.length ? `decision:${relationship.decisionEvidence.slice(0, 6).join(' ')}` : '',
        ...evidenceContexts(input, relationship.evidenceAnchorIds, anchorById, 4).map((context) => `evidence_context:${context}`),
    ].filter(Boolean).join('\n'), 2200);
}

function eventText(
    input: BuildGraphRebuildSnapshotInput,
    event: GraphRebuildEvent,
    nodeByEntityId: Map<string, GraphRebuildNode>,
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): string {
    const entitySummary = event.entityIds.map((id) => entityLabel(id, nodeByEntityId)).join(', ');
    const base = [
        event.label,
        entitySummary ? `entities:${entitySummary}` : '',
        `confidence:${event.confidence.toFixed(2)}`,
    ];
    if (!event.aspect) {
        return limitText([
            ...base,
            ...evidenceContexts(input, event.evidenceAnchorIds, anchorById, 4).map((context) => `evidence_context:${context}`),
        ].filter(Boolean).join('\n'), 1800);
    }
    const cues = event.aspect.cues.length ? ` cues:${event.aspect.cues.join(',')}` : '';
    return limitText([
        ...base,
        `aspect:${event.aspect.kind} completion:${event.aspect.completion}${cues}`,
        ...evidenceContexts(input, event.evidenceAnchorIds, anchorById, 4).map((context) => `evidence_context:${context}`),
    ].filter(Boolean).join('\n'), 1800);
}

function memoryText(
    input: BuildGraphRebuildSnapshotInput,
    state: GraphRebuildMemoryState,
    nodeByEntityId: Map<string, GraphRebuildNode>,
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): string {
    return limitText([
        `${entityLabel(state.entityId, nodeByEntityId)} ${state.key} ${state.value}`,
        `memory_key:${state.key}`,
        ...evidenceContexts(input, state.evidenceIds, anchorById, 3).map((context) => `evidence_context:${context}`),
    ].filter(Boolean).join('\n'), 1400);
}

function folderFields(input: BuildGraphRebuildSnapshotInput, noteId?: string): Pick<GraphRebuildEmbeddingTarget, 'folderId' | 'folderLabel' | 'folderKind' | 'folderParentId'> {
    if (!noteId) return {};
    const folder = input.noteFolders?.[noteId];
    if (!folder?.folderId) return {};
    return {
        folderId: folder.folderId,
        folderLabel: folder.folderLabel,
        folderKind: folder.folderKind,
        folderParentId: folder.folderParentId,
    };
}

function entityFolderFields(
    input: BuildGraphRebuildSnapshotInput,
    anchors: GraphRebuildEntityAnchor[],
): Pick<GraphRebuildEmbeddingTarget, 'folderId' | 'folderLabel' | 'folderKind' | 'folderParentId'> {
    const best = [...anchors].sort(anchorOrder)[0];
    return folderFields(input, best?.noteId);
}

function relationshipFolderFields(
    input: BuildGraphRebuildSnapshotInput,
    relationship: GraphRebuildRelationship,
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): Pick<GraphRebuildEmbeddingTarget, 'folderId' | 'folderLabel' | 'folderKind' | 'folderParentId'> {
    return folderFields(input, noteIdsFromEvidence(relationship.evidenceAnchorIds, anchorById)[0]);
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function groupAnchorsByEntity(anchors: GraphRebuildEntityAnchor[]): Map<string, GraphRebuildEntityAnchor[]> {
    const groups = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of anchors) groups.set(anchor.entityId, [...(groups.get(anchor.entityId) || []), anchor]);
    return groups;
}

function groupAnchorsByChunk(anchors: GraphRebuildEntityAnchor[]): Map<string, GraphRebuildEntityAnchor[]> {
    const groups = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of anchors) {
        if (!anchor.chunkId) continue;
        groups.set(anchor.chunkId, [...(groups.get(anchor.chunkId) || []), anchor]);
    }
    return groups;
}

function structureRootId(noteId: string, key: StructuralRootKey): string {
    return `embed:structure-root:${noteId}:${key}`;
}

function entityParentIds(anchors: GraphRebuildEntityAnchor[]): string[] {
    const chunkParents = anchors
        .map((anchor) => anchor.chunkId ? `embed:chunk:${anchor.chunkId}` : '')
        .filter(Boolean);
    const identityParents = anchors
        .map((anchor) => anchor.noteId ? structureRootId(anchor.noteId, 'identity') : '')
        .filter(Boolean);
    return unique([...chunkParents, ...identityParents]);
}

function relationshipParentIds(
    relationship: GraphRebuildRelationship,
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): string[] {
    return unique([
        ...noteIdsFromEvidence(relationship.evidenceAnchorIds, anchorById).map((noteId) => structureRootId(noteId, 'identity')),
        `embed:entity:${relationship.sourceEntityId}`,
        `embed:entity:${relationship.targetEntityId}`,
    ]);
}

function eventParentIds(event: GraphRebuildEvent): string[] {
    return unique([
        structureRootId(event.noteId, 'temporal'),
        ...(event.chunkId ? [`embed:chunk:${event.chunkId}`] : []),
        ...event.entityIds.map((entityId) => `embed:entity:${entityId}`),
    ]);
}

function noteIdsFromEventsAndEvidence(
    source: GraphRebuildEvent | undefined,
    target: GraphRebuildEvent | undefined,
    evidenceIds: string[],
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): string[] {
    return unique([
        source?.noteId || '',
        target?.noteId || '',
        ...noteIdsFromEvidence(evidenceIds, anchorById),
    ].filter(Boolean));
}

function noteIdsFromEvidence(
    evidenceIds: string[],
    anchorById: Map<string, GraphRebuildEntityAnchor>,
): string[] {
    return unique(evidenceIds
        .map((evidenceId) => anchorById.get(evidenceId)?.noteId || '')
        .filter(Boolean));
}

function representativeAnchorContexts(
    input: BuildGraphRebuildSnapshotInput,
    anchors: GraphRebuildEntityAnchor[],
    max: number,
): string[] {
    const out: string[] = [];
    const seenScopes = new Set<string>();
    for (const anchor of [...anchors].sort(anchorOrder)) {
        const scope = anchor.chunkId || `${anchor.noteId}:${Math.floor(anchor.sourceStart / 1200)}`;
        if (seenScopes.has(scope) && out.length < max - 1) continue;
        seenScopes.add(scope);
        out.push(anchorContext(input, anchor));
        if (out.length >= max) break;
    }
    return out;
}

function evidenceContexts(
    input: BuildGraphRebuildSnapshotInput,
    evidenceIds: string[],
    anchorById: Map<string, GraphRebuildEntityAnchor>,
    max: number,
): string[] {
    const contexts: string[] = [];
    const seen = new Set<string>();
    for (const evidenceId of evidenceIds) {
        const anchor = anchorById.get(evidenceId);
        if (!anchor) continue;
        const context = anchorContext(input, anchor);
        if (seen.has(context)) continue;
        seen.add(context);
        contexts.push(context);
        if (contexts.length >= max) break;
    }
    return contexts;
}

function anchorContext(input: BuildGraphRebuildSnapshotInput, anchor: GraphRebuildEntityAnchor): string {
    const text = input.noteTexts?.[anchor.noteId] || '';
    if (!text) return anchor.surface;
    const radius = 150;
    const start = Math.max(0, anchor.sourceStart - radius);
    const end = Math.min(text.length, anchor.sourceEnd + radius);
    return squash(text.slice(start, end)) || anchor.surface;
}

function entityLabel(entityId: string, nodeByEntityId: Map<string, GraphRebuildNode>): string {
    return nodeByEntityId.get(entityId)?.label || entityId;
}

function anchorOrder(left: GraphRebuildEntityAnchor, right: GraphRebuildEntityAnchor): number {
    return anchorQuality(right) - anchorQuality(left)
        || left.noteId.localeCompare(right.noteId)
        || left.sourceStart - right.sourceStart
        || left.id.localeCompare(right.id);
}

function anchorQuality(anchor: GraphRebuildEntityAnchor): number {
    let score = clamp(anchor.confidence, 0, 1) * 100;
    if (anchor.source === 'manual_tag' || anchor.source === 'accepted_suggestion') score += 50;
    if (anchor.source === 'dictionary_match') score += 40;
    if (anchor.source === 'machine_suggestion' || anchor.source === 'machine_evidence') score += 36;
    if (anchor.chunkId) score += 10;
    score += Math.min(16, anchor.surface.length);
    return score;
}

function limitText(value: string, max: number): string {
    const text = squash(value);
    if (text.length <= max) return text;
    const head = Math.floor(max * 0.72);
    const tail = Math.max(120, max - head - 7);
    return `${text.slice(0, head)} ... ${text.slice(text.length - tail)}`;
}

function squash(value: string): string {
    return value.replace(/\s+/g, ' ').trim();
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}
