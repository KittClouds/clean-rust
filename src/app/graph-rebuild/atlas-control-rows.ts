import type {
    GraphDocumentReviewActionKind,
    GraphDocumentReviewRow,
} from './graph-document-review';
import type {
    GraphPromotionVerdictCertificate,
    GraphPromotionVerdictRow,
} from './graph-promotion-verdict';
import type {
    GraphMemoryGovernanceCandidate,
    GraphRebuildCausalEdge,
    GraphRebuildChunk,
    GraphRebuildChunkSemanticBridge,
    GraphRebuildEdge,
    GraphRebuildEpisode,
    GraphRebuildEpisodeConnection,
    GraphRebuildEpisodeProjectionEdge,
    GraphRebuildEvent,
    GraphRebuildMemoryState,
    GraphRebuildRelationship,
    GraphRebuildSnapshot,
    GraphRebuildTemporalEdge,
} from './graph-rebuild-snapshot';
import type { GraphReviewAdjudicationRunCertificate } from './graph-review-adjudication-certificate';
import type {
    AtlasControlAction,
    AtlasControlEntityInput,
    AtlasControlLane,
    AtlasControlReceiptKind,
    AtlasControlReceiptPolicy,
    AtlasControlRow,
    AtlasControlSourceContract,
} from './atlas-control-contract';

interface AtlasControlRowTrace {
    noteId?: string;
    sourceStart?: number;
    sourceEnd?: number;
    sourceIds?: string[];
    targetIds?: string[];
    entityIds?: string[];
    evidenceIds?: string[];
    tags?: string[];
}

export function buildAtlasControlRows(
    snapshotId: string,
    snapshot: GraphRebuildSnapshot | null,
    review: GraphReviewAdjudicationRunCertificate | null,
    promotion: GraphPromotionVerdictCertificate | null,
    entities: AtlasControlEntityInput[],
): AtlasControlRow[] {
    const rows: AtlasControlRow[] = [];
    for (const entity of entities) rows.push(entityRow(snapshotId, entity));
    for (const edge of snapshot?.edges ?? []) rows.push(graphEdgeRow(snapshotId, edge));
    for (const chunk of snapshot?.chunks ?? []) rows.push(chunkRow(snapshotId, chunk));
    for (const episode of snapshot?.episodes ?? []) rows.push(episodeRow(snapshotId, episode));
    for (const edge of snapshot?.episodeProjectionEdges ?? []) rows.push(episodeProjectionRow(snapshotId, edge));
    for (const relationship of snapshot?.relationships ?? []) rows.push(relationshipRow(snapshotId, relationship));
    for (const event of snapshot?.events ?? []) rows.push(eventRow(snapshotId, event));
    for (const edge of snapshot?.temporalEdges ?? []) rows.push(temporalRow(snapshotId, edge));
    for (const edge of snapshot?.causalEdges ?? []) rows.push(causalRow(snapshotId, edge));
    for (const state of snapshot?.memoryState ?? []) rows.push(memoryStateRow(snapshotId, state));
    for (const bridge of snapshot?.chunkSemanticBridges ?? []) rows.push(chunkBridgeRow(snapshotId, bridge));
    for (const connection of snapshot?.episodeConnections ?? []) rows.push(episodeConnectionRow(snapshotId, connection));
    for (const entry of snapshot?.discourseEvalLedgerSummary?.entries ?? []) {
        rows.push(typedRow(snapshotId, 'graph_build', 'discourse_ledger', entry.id, entry.candidateKind,
            entry.sourceHypothesis || entry.label, entry.rationale.join(' '), entry.adjudicationState,
            entry.score, ['inspect', 'compare_context'], noReceipt(), [], {
                targetIds: entry.evidenceTargetIds,
                evidenceIds: entry.evidenceTargetIds,
                tags: [entry.label, ...entry.flags],
            }));
    }
    for (const row of snapshot?.documentReviewSummary?.rows ?? []) rows.push(documentReviewRow(snapshotId, row));
    for (const row of review?.rows ?? []) {
        rows.push(typedRow(snapshotId, 'review_adjudication', 'nli_judgment', row.id, 'nli_judgment',
            `${row.sourceId} -> ${row.targetId}`, `${row.edgeType}: ${row.label}`, row.label,
            row.confidence, ['inspect'], noReceipt(), [], {
                sourceIds: [row.sourceId],
                targetIds: [row.targetId],
                evidenceIds: [],
                tags: ['text_pair_nli', row.label],
            }));
    }
    for (const row of snapshot?.memoryGovernanceCandidates ?? []) rows.push(governanceRow(snapshotId, row));
    for (const row of promotion?.rows ?? []) rows.push(promotionRow(snapshotId, row));
    for (const [key, value] of Object.entries(snapshot?.buildTimings ?? {})) {
        if (typeof value !== 'number' || !Number.isFinite(value)) continue;
        rows.push(typedRow(snapshotId, 'metrics', 'metrics_ledger', key, 'timing', humanize(key),
            `${value.toLocaleString()} ${key.toLowerCase().includes('micros') ? 'us' : 'ms'}`,
            'measured', null, ['inspect'], noReceipt(), [], { tags: ['timing'] }));
    }
    return uniquifyRows(rows);
}

function entityRow(snapshotId: string, entity: AtlasControlEntityInput): AtlasControlRow {
    const aliases = entity.aliases?.length ? `${entity.aliases.length} aliases` : 'No aliases';
    return typedRow(snapshotId, 'graph_build', 'graph_topology', entity.id, `entity:${entity.kind}`,
        entity.label, `${humanize(entity.kind)} / ${aliases}`, 'registered', null,
        ['inspect', 'edit_entity', 'delete_entity'], noReceipt(), [], {
            entityIds: [entity.id],
            sourceIds: [entity.id],
            tags: ['registry_entity', entity.kind],
        });
}

function graphEdgeRow(snapshotId: string, edge: GraphRebuildEdge): AtlasControlRow {
    return typedRow(snapshotId, 'graph_build', 'graph_topology', edge.id, `edge:${edge.type}`,
        `${edge.sourceId} -> ${humanize(edge.type)} -> ${edge.targetId}`,
        `${edge.evidenceAnchorIds.length} evidence anchors`, 'accepted', edge.confidence,
        ['inspect', 'compare_context'], noReceipt(), [], {
            sourceIds: [edge.sourceId], targetIds: [edge.targetId], evidenceIds: edge.evidenceAnchorIds,
            tags: ['graph_edge', edge.type],
        });
}

function chunkRow(snapshotId: string, chunk: GraphRebuildChunk): AtlasControlRow {
    return typedRow(snapshotId, 'graph_build', 'structure_ledger', chunk.id, 'chunk',
        `Chunk ${chunk.ordinal + 1}`, `${humanize(chunk.role || chunk.source)} / ${chunk.start}-${chunk.end}`,
        'structural', null, ['inspect', 'jump_to_source'], noReceipt(), [], {
            noteId: chunk.noteId, sourceStart: chunk.start, sourceEnd: chunk.end,
            sourceIds: [chunk.noteId], targetIds: [chunk.id], tags: ['chunk', chunk.role || chunk.source],
        });
}

function episodeRow(snapshotId: string, episode: GraphRebuildEpisode): AtlasControlRow {
    return typedRow(snapshotId, 'graph_build', 'structure_ledger', episode.id, 'episode', episode.label,
        `${episode.eventIds.length} events / ${episode.entityIds.length} entities`, 'derived', null,
        ['inspect', 'jump_to_source'], noReceipt(), [], {
            noteId: episode.noteId, sourceIds: [episode.noteId], targetIds: episode.eventIds,
            entityIds: episode.entityIds, evidenceIds: episode.eventIds, tags: ['episode'],
        });
}

function episodeProjectionRow(snapshotId: string, edge: GraphRebuildEpisodeProjectionEdge): AtlasControlRow {
    return typedRow(snapshotId, 'graph_build', 'structure_ledger', edge.id, edge.kind,
        `${edge.sourceId} -> ${humanize(edge.relationType)} -> ${edge.targetId}`,
        edge.rationale.join(' '), edge.status, edge.confidence, ['inspect', 'compare_context'], noReceipt(), [], {
            noteId: edge.noteId, sourceIds: [edge.sourceId], targetIds: [edge.targetId],
            evidenceIds: edge.evidenceIds, tags: [edge.kind, 'no_topology_commit'],
        });
}

function relationshipRow(snapshotId: string, row: GraphRebuildRelationship): AtlasControlRow {
    return typedRow(snapshotId, 'document_review', 'fact_ledger', row.id, 'relationship',
        `${row.sourceEntityId} -> ${humanize(row.relationType)} -> ${row.targetEntityId}`,
        row.rationale, row.status, row.confidence, ['inspect', 'compare_context'], noReceipt(), [], {
            sourceIds: [row.sourceEntityId], targetIds: [row.targetEntityId],
            entityIds: [row.sourceEntityId, row.targetEntityId], evidenceIds: row.evidenceAnchorIds,
            tags: ['relationship', row.relationType, row.adjudicationSource],
        });
}

function eventRow(snapshotId: string, row: GraphRebuildEvent): AtlasControlRow {
    return typedRow(snapshotId, 'document_review', 'fact_ledger', row.id, 'event', row.label,
        row.aspect ? `${humanize(row.aspect.kind)} / ${humanize(row.aspect.completion)}` : 'Event fact',
        'accepted', row.confidence, ['inspect', 'jump_to_source'], noReceipt(), [], {
            noteId: row.noteId, sourceIds: row.chunkId ? [row.chunkId] : [row.noteId],
            entityIds: row.entityIds, evidenceIds: row.evidenceAnchorIds, tags: ['event'],
        });
}

function temporalRow(snapshotId: string, row: GraphRebuildTemporalEdge): AtlasControlRow {
    return typedRow(snapshotId, 'document_review', 'fact_ledger', row.id, 'temporal',
        `${row.sourceId} -> ${humanize(row.relationType)} -> ${row.targetId}`,
        `${row.evidenceIds.length} evidence rows`, 'accepted', row.confidence,
        ['inspect', 'compare_context'], noReceipt(), [], {
            sourceIds: [row.sourceId], targetIds: [row.targetId], evidenceIds: row.evidenceIds,
            tags: ['temporal', row.relationType],
        });
}

function causalRow(snapshotId: string, row: GraphRebuildCausalEdge): AtlasControlRow {
    return typedRow(snapshotId, 'document_review', 'fact_ledger', row.id, 'causal',
        `${row.sourceId} -> ${humanize(row.relationType)} -> ${row.targetId}`,
        row.rationale || `${humanize(row.sourceKind)} / ${humanize(row.evidenceClass)}`,
        row.status, row.confidence, ['inspect', 'compare_context'], noReceipt(), [], {
            sourceIds: [row.sourceId], targetIds: [row.targetId], evidenceIds: row.evidenceIds,
            tags: ['causal', row.polarity, row.modality],
        });
}

function memoryStateRow(snapshotId: string, row: GraphRebuildMemoryState): AtlasControlRow {
    return typedRow(snapshotId, 'document_review', 'fact_ledger', row.id, 'memory_state',
        `${row.entityId} / ${humanize(row.key)}`, row.value, 'accepted', null,
        ['inspect', 'jump_to_source'], noReceipt(), [], {
            noteId: row.noteId, entityIds: [row.entityId], sourceIds: [row.entityId],
            evidenceIds: row.evidenceIds, tags: ['memory_state', row.key],
        });
}

function chunkBridgeRow(snapshotId: string, row: GraphRebuildChunkSemanticBridge): AtlasControlRow {
    return typedRow(snapshotId, 'memory_governance', 'discourse_ledger', row.id, row.bridgeType,
        row.claim, row.rationale.join(' '), row.status, row.confidence,
        ['inspect', 'compare_context', 'preview_promotion'], noReceipt(), [], {
            sourceIds: [row.sourceChunkId], targetIds: [row.targetChunkId],
            entityIds: row.supportingEntityIds, evidenceIds: row.evidenceIds,
            tags: ['semantic_bridge', row.bridgeType, row.commitPolicy],
        });
}

function episodeConnectionRow(snapshotId: string, row: GraphRebuildEpisodeConnection): AtlasControlRow {
    return typedRow(snapshotId, 'memory_governance', 'discourse_ledger', row.id, row.kind,
        `${row.sourceEpisodeId} -> ${humanize(row.relationType)} -> ${row.targetEpisodeId}`,
        row.claim || row.rationale.join(' '), row.status, row.confidence,
        ['inspect', 'compare_context', 'preview_promotion'], noReceipt(), [], {
            sourceIds: [row.sourceEpisodeId], targetIds: [row.targetEpisodeId],
            entityIds: row.sharedEntityIds, evidenceIds: row.evidenceIds,
            tags: ['episode_connection', row.kind, row.bridgeType || ''],
        });
}

function documentReviewRow(snapshotId: string, row: GraphDocumentReviewRow): AtlasControlRow {
    const actions = unique(row.availableActions.map((action) => reviewAction(action.kind)).filter(isAction));
    const manual = row.availableActions.some((action) => action.requiresUserIntent);
    return typedRow(snapshotId, 'document_review', manual ? 'manual_decision' : 'review_ledger',
        row.id, row.objectKind, row.title, row.detail, row.state, row.confidence, actions,
        manual ? receipt('document_review_action_receipt', true, false) : noReceipt(), row.receiptIds, {
            noteId: row.noteId, sourceStart: row.sourceStart, sourceEnd: row.sourceEnd,
            sourceIds: [row.objectId, ...row.parentUnitIds], targetIds: row.childUnitIds,
            evidenceIds: row.evidenceSpanIds, tags: [row.objectKind, row.detector],
        });
}

function governanceRow(snapshotId: string, row: GraphMemoryGovernanceCandidate): AtlasControlRow {
    return typedRow(snapshotId, 'memory_governance', 'governance_candidate', row.id, row.targetKind,
        row.targetId, row.reason, row.action, row.confidence, ['inspect'], noReceipt(), [], {
            targetIds: [row.targetId], evidenceIds: row.evidenceIds,
            tags: ['governance', row.action, row.commitPolicy],
        });
}

function promotionRow(snapshotId: string, row: GraphPromotionVerdictRow): AtlasControlRow {
    return typedRow(snapshotId, 'promotion_verdict', 'promotion_verdict', row.id, row.family,
        promotionLabel(row), row.rationale, row.status,
        row.deterministicScoreMillis == null ? null : row.deterministicScoreMillis / 1000,
        ['preview_promotion'], receipt('promotion_proposal_receipt', row.rollbackPlan.availableAfterCommit, true),
        row.receiptId ? [row.receiptId] : [], { tags: ['promotion', row.family, row.status] });
}

function typedRow(
    snapshotId: string,
    sourceContract: AtlasControlSourceContract,
    lane: AtlasControlLane,
    rawId: string,
    kind: string,
    label: string,
    detail: string,
    state: string,
    confidence: number | null,
    allowedActions: AtlasControlAction[],
    receiptPolicy: AtlasControlReceiptPolicy,
    receiptIds: string[],
    trace: AtlasControlRowTrace = {},
): AtlasControlRow {
    return {
        identity: {
            id: `${sourceContract}:${lane}:${rawId || 'missing-id'}`,
            rawId: rawId || 'missing-id', snapshotId, sourceContract, lane, kind,
        },
        label, detail, state, confidence, allowedActions, receiptPolicy, receiptIds: [...receiptIds],
        noteId: trace.noteId ?? null,
        sourceStart: trace.sourceStart ?? null,
        sourceEnd: trace.sourceEnd ?? null,
        sourceIds: clean(trace.sourceIds),
        targetIds: clean(trace.targetIds),
        entityIds: clean(trace.entityIds),
        evidenceIds: clean(trace.evidenceIds),
        tags: clean(trace.tags),
    };
}

function reviewAction(kind: GraphDocumentReviewActionKind): AtlasControlAction | null {
    const actions: Record<GraphDocumentReviewActionKind, AtlasControlAction> = {
        accept_fact: 'accept_review_row', reject_fact: 'reject_review_row',
        promote_sidecar_to_anchor: 'promote_to_anchor', merge_duplicate_units: 'merge_duplicates',
        demote_graph_fact_to_sidecar: 'demote_to_sidecar', mute_detector_pattern: 'mute_pattern',
        jump_to_source_span: 'jump_to_source', inspect_evidence_path: 'inspect',
        compare_parent_child_context: 'compare_context', show_proposal_reason: 'show_reason',
        compile_to_graph: 'compile_to_graph',
    };
    return actions[kind] ?? null;
}

function promotionLabel(row: GraphPromotionVerdictRow): string {
    const truth = row.truth;
    if (truth.subject || truth.predicate || truth.object) {
        return [truth.subject, truth.predicate, truth.object].filter(Boolean).join(' -> ');
    }
    if (row.atom?.kind === 'edge') return `${row.atom.source_id} -> ${row.atom.edge_type} -> ${row.atom.target_id}`;
    if (row.atom?.kind === 'vertex') return row.atom.vertex_id;
    return row.proposalId;
}

function uniquifyRows(rows: AtlasControlRow[]): AtlasControlRow[] {
    const seen = new Map<string, number>();
    return rows.map((row) => {
        const count = seen.get(row.identity.id) ?? 0;
        seen.set(row.identity.id, count + 1);
        if (count === 0) return row;
        return { ...row, identity: { ...row.identity, id: `${row.identity.id}#${count + 1}` } };
    });
}

function receipt(
    kind: AtlasControlReceiptKind,
    reversible: boolean,
    topologyMutationAllowed: boolean,
): AtlasControlReceiptPolicy {
    return { required: true, kind, reversible, topologyMutationAllowed };
}

function noReceipt(): AtlasControlReceiptPolicy {
    return { required: false, kind: null, reversible: false, topologyMutationAllowed: false };
}

function humanize(value: string): string {
    return value.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').trim()
        .replace(/\b\w/g, (character) => character.toUpperCase());
}

function clean(values: string[] | undefined): string[] {
    return unique((values ?? []).filter((value) => !!value));
}

function isAction(value: AtlasControlAction | null): value is AtlasControlAction {
    return value !== null;
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}
