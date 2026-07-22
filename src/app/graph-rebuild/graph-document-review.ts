import type {
    DocumentRegion,
    DocumentUnit,
    EvidenceSpan,
    GraphDocumentSidecarSummary,
    GraphFactCandidate,
    RetrievalUnit,
    RhetoricalUnit,
} from './graph-document-sidecar';

export type GraphDocumentReviewState =
    | 'proposed'
    | 'accepted'
    | 'rejected'
    | 'muted'
    | 'promoted_to_anchor'
    | 'compiled_to_graph'
    | 'ledger_only';

export type GraphDocumentReviewObjectKind =
    | 'document_unit'
    | 'document_region'
    | 'rhetorical_unit'
    | 'retrieval_unit'
    | 'graph_fact_candidate'
    | 'evidence_span';

export type GraphDocumentReviewActionKind =
    | 'accept_fact'
    | 'reject_fact'
    | 'promote_sidecar_to_anchor'
    | 'merge_duplicate_units'
    | 'demote_graph_fact_to_sidecar'
    | 'mute_detector_pattern'
    | 'jump_to_source_span'
    | 'inspect_evidence_path'
    | 'compare_parent_child_context'
    | 'show_proposal_reason'
    | 'compile_to_graph';

export interface GraphDocumentReviewAction {
    id: string;
    kind: GraphDocumentReviewActionKind;
    label: string;
    targetObjectId: string;
    destructive: boolean;
    requiresUserIntent: boolean;
    nextState?: GraphDocumentReviewState;
}

export interface GraphDocumentReviewStateRecord {
    id: string;
    objectId: string;
    objectKind: GraphDocumentReviewObjectKind;
    state: GraphDocumentReviewState;
    source: 'machine_sidecar';
    confidence: number;
}

export interface GraphDocumentReviewRow {
    id: string;
    objectId: string;
    objectKind: GraphDocumentReviewObjectKind;
    state: GraphDocumentReviewState;
    title: string;
    subtitle: string;
    detail: string;
    noteId: string;
    sourceStart: number;
    sourceEnd: number;
    confidence: number;
    detector: string;
    parentUnitIds: string[];
    childUnitIds: string[];
    evidenceSpanIds: string[];
    relatedObjectIds: string[];
    duplicateGroupId?: string;
    why: string[];
    availableActions: GraphDocumentReviewAction[];
    receiptIds: string[];
}

export interface GraphDocumentReviewActionReceipt {
    id: string;
    actionId: string;
    actionKind: GraphDocumentReviewActionKind;
    targetObjectId: string;
    targetObjectKind: GraphDocumentReviewObjectKind;
    previousState: GraphDocumentReviewState;
    nextState: GraphDocumentReviewState;
    reversible: true;
    mutationAllowed: false;
    invariant: 'document_review_no_topology_commit';
    undoState: GraphDocumentReviewState;
    undoHint: string;
    detail: string;
    createdAt: number;
}

export interface GraphDocumentReviewCounters {
    stateRecords: number;
    rows: number;
    actionableRows: number;
    actions: number;
    receipts: number;
    reversibleReceipts: number;
    acceptedRows: number;
    rejectedRows: number;
    mutedRows: number;
    promotedToAnchorRows: number;
    compiledToGraphRows: number;
    ledgerOnlyRows: number;
    proposedRows: number;
    duplicateGroups: number;
    byState: Record<string, number>;
    byObjectKind: Record<string, number>;
    byActionKind: Record<string, number>;
}

export interface GraphDocumentReviewSummary {
    schemaVersion: 'phoenix-document-review/v1';
    builtAt: number;
    statePolicy: 'machine_objects_are_explicitly_review_stateful';
    topologyPolicy: 'review_actions_emit_receipts_before_graph_mutation';
    states: GraphDocumentReviewStateRecord[];
    rows: GraphDocumentReviewRow[];
    receipts: GraphDocumentReviewActionReceipt[];
    counters: GraphDocumentReviewCounters;
}

export interface GraphDocumentReviewActionInput {
    rowId: string;
    actionKind: GraphDocumentReviewActionKind;
    createdAt: number;
}

type ReviewSourceObject =
    | DocumentUnit
    | DocumentRegion
    | RhetoricalUnit
    | RetrievalUnit
    | GraphFactCandidate
    | EvidenceSpan;

interface ReviewObject {
    object: ReviewSourceObject;
    objectKind: GraphDocumentReviewObjectKind;
    state: GraphDocumentReviewState;
    evidenceSpanIds: string[];
}

const ACTION_LABELS: Record<GraphDocumentReviewActionKind, string> = {
    accept_fact: 'Accept',
    reject_fact: 'Reject',
    promote_sidecar_to_anchor: 'Promote',
    merge_duplicate_units: 'Merge',
    demote_graph_fact_to_sidecar: 'Demote',
    mute_detector_pattern: 'Mute',
    jump_to_source_span: 'Jump',
    inspect_evidence_path: 'Evidence',
    compare_parent_child_context: 'Context',
    show_proposal_reason: 'Why',
    compile_to_graph: 'Compile',
};

export function buildGraphDocumentReviewSummary(
    sidecar: GraphDocumentSidecarSummary,
    builtAt: number,
): GraphDocumentReviewSummary {
    const reviewObjects = collectReviewObjects(sidecar);
    const duplicateGroups = duplicateGroupsFor(reviewObjects);
    const rows = reviewObjects.map((item) => reviewRow(item, duplicateGroups));
    const states = reviewObjects.map((item) => stateRecord(item));
    return {
        schemaVersion: 'phoenix-document-review/v1',
        builtAt,
        statePolicy: 'machine_objects_are_explicitly_review_stateful',
        topologyPolicy: 'review_actions_emit_receipts_before_graph_mutation',
        states,
        rows,
        receipts: [],
        counters: counters(rows, states, []),
    };
}

export function applyGraphDocumentReviewAction(
    summary: GraphDocumentReviewSummary,
    input: GraphDocumentReviewActionInput,
): GraphDocumentReviewSummary {
    const row = summary.rows.find((candidate) => candidate.id === input.rowId);
    if (!row) return summary;
    const action = row.availableActions.find((candidate) => candidate.kind === input.actionKind);
    if (!action) return summary;
    const nextState = action.nextState || row.state;
    const receipt: GraphDocumentReviewActionReceipt = {
        id: `document-review-receipt:${simpleHash(`${input.rowId}:${input.actionKind}:${input.createdAt}`)}`,
        actionId: action.id,
        actionKind: action.kind,
        targetObjectId: row.objectId,
        targetObjectKind: row.objectKind,
        previousState: row.state,
        nextState,
        reversible: true,
        mutationAllowed: false,
        invariant: 'document_review_no_topology_commit',
        undoState: row.state,
        undoHint: `Restore ${row.objectId} to ${row.state}.`,
        detail: `${ACTION_LABELS[action.kind]} ${row.title}`,
        createdAt: input.createdAt,
    };
    const rows = summary.rows.map((candidate) =>
        candidate.id === row.id
            ? { ...candidate, state: nextState, receiptIds: [...candidate.receiptIds, receipt.id] }
            : candidate,
    );
    const states = summary.states.map((candidate) =>
        candidate.objectId === row.objectId ? { ...candidate, state: nextState } : candidate,
    );
    const receipts = [...summary.receipts, receipt];
    return { ...summary, rows, states, receipts, counters: counters(rows, states, receipts) };
}

function collectReviewObjects(sidecar: GraphDocumentSidecarSummary): ReviewObject[] {
    const specializedIds = new Set([
        ...sidecar.graphFactCandidates.map((object) => object.id),
        ...sidecar.rhetoricalUnits.map((object) => object.id),
        ...sidecar.regions.map((object) => object.id),
        ...sidecar.retrievalUnits.map((object) => object.id),
    ]);
    return [
        ...sidecar.graphFactCandidates.map((object) => reviewObject(object, 'graph_fact_candidate', 'proposed', object.evidenceSpanIds)),
        ...sidecar.rhetoricalUnits.map((object) => reviewObject(object, 'rhetorical_unit', 'proposed', object.evidenceSpanIds)),
        ...sidecar.regions.map((object) => reviewObject(object, 'document_region', reviewStateForRegion(object), [])),
        ...sidecar.retrievalUnits.map((object) => reviewObject(object, 'retrieval_unit', 'ledger_only', object.evidenceSpanIds)),
        ...sidecar.evidenceSpans.map((object) => reviewObject(object, 'evidence_span', 'ledger_only', [object.id])),
        ...sidecar.units
            .filter((object) => !specializedIds.has(object.id))
            .map((object) => reviewObject(object, 'document_unit', reviewStateForUnit(object), [])),
    ];
}

function reviewObject(
    object: ReviewSourceObject,
    objectKind: GraphDocumentReviewObjectKind,
    state: GraphDocumentReviewState,
    evidenceSpanIds: string[],
): ReviewObject {
    return { object, objectKind, state, evidenceSpanIds };
}

function reviewStateForRegion(region: DocumentRegion): GraphDocumentReviewState {
    if (region.kind === 'dialogue_block' || region.kind === 'action_block' || region.kind === 'chapter' || region.kind === 'scene') return 'proposed';
    if (region.kind === 'table' || region.kind === 'code_block' || region.kind === 'list') return 'proposed';
    return 'ledger_only';
}

function reviewStateForUnit(unit: DocumentUnit): GraphDocumentReviewState {
    if (unit.kind === 'claim' || unit.kind === 'evidence' || unit.kind === 'decision') return 'proposed';
    return 'ledger_only';
}

function reviewRow(
    item: ReviewObject,
    duplicateGroups: Map<string, string[]>,
): GraphDocumentReviewRow {
    const object = item.object;
    const duplicateKey = duplicateKeyFor(item);
    const duplicateIds = duplicateGroups.get(duplicateKey) || [];
    const duplicateGroupId = duplicateIds.length > 1 ? `duplicate:${simpleHash(duplicateKey)}` : undefined;
    const rowId = `document-review:${item.objectKind}:${object.id}`;
    const actions = actionsFor(item, rowId, duplicateGroupId);
    return {
        id: rowId,
        objectId: object.id,
        objectKind: item.objectKind,
        state: item.state,
        title: titleFor(item),
        subtitle: subtitleFor(item),
        detail: detailFor(item, duplicateIds.length),
        noteId: object.noteId,
        sourceStart: object.start,
        sourceEnd: object.end,
        confidence: object.confidence.score,
        detector: object.confidence.source,
        parentUnitIds: parentIdsFor(object),
        childUnitIds: 'childIds' in object ? object.childIds : [],
        evidenceSpanIds: item.evidenceSpanIds,
        relatedObjectIds: duplicateIds.filter((id) => id !== object.id),
        duplicateGroupId,
        why: object.confidence.reasons,
        availableActions: actions,
        receiptIds: [],
    };
}

function actionsFor(
    item: ReviewObject,
    rowId: string,
    duplicateGroupId: string | undefined,
): GraphDocumentReviewAction[] {
    const object = item.object;
    const actions: GraphDocumentReviewActionKind[] = [
        'jump_to_source_span',
        'inspect_evidence_path',
        'compare_parent_child_context',
        'show_proposal_reason',
    ];
    if (item.objectKind === 'graph_fact_candidate') {
        actions.unshift('accept_fact', 'reject_fact');
        actions.push('demote_graph_fact_to_sidecar', 'compile_to_graph');
    } else if (item.state === 'proposed') {
        actions.unshift('promote_sidecar_to_anchor');
        actions.push('mute_detector_pattern');
    }
    if (duplicateGroupId) actions.push('merge_duplicate_units');
    return actions.map((kind) => action(rowId, object.id, kind));
}

function action(rowId: string, objectId: string, kind: GraphDocumentReviewActionKind): GraphDocumentReviewAction {
    return {
        id: `document-review-action:${simpleHash(`${rowId}:${kind}`)}`,
        kind,
        label: ACTION_LABELS[kind],
        targetObjectId: objectId,
        destructive: kind === 'reject_fact' || kind === 'mute_detector_pattern',
        requiresUserIntent: !kind.startsWith('jump_') && !kind.startsWith('inspect_') && !kind.startsWith('compare_') && kind !== 'show_proposal_reason',
        nextState: nextStateForAction(kind),
    };
}

function nextStateForAction(kind: GraphDocumentReviewActionKind): GraphDocumentReviewState | undefined {
    if (kind === 'accept_fact') return 'accepted';
    if (kind === 'reject_fact') return 'rejected';
    if (kind === 'promote_sidecar_to_anchor') return 'promoted_to_anchor';
    if (kind === 'demote_graph_fact_to_sidecar') return 'ledger_only';
    if (kind === 'mute_detector_pattern') return 'muted';
    if (kind === 'compile_to_graph') return 'compiled_to_graph';
    if (kind === 'merge_duplicate_units') return 'accepted';
    return undefined;
}

function stateRecord(item: ReviewObject): GraphDocumentReviewStateRecord {
    return {
        id: `document-review-state:${item.object.id}`,
        objectId: item.object.id,
        objectKind: item.objectKind,
        state: item.state,
        source: 'machine_sidecar',
        confidence: item.object.confidence.score,
    };
}

function counters(
    rows: GraphDocumentReviewRow[],
    states: GraphDocumentReviewStateRecord[],
    receipts: GraphDocumentReviewActionReceipt[],
): GraphDocumentReviewCounters {
    const byState = countBy(states.map((state) => state.state));
    const byObjectKind = countBy(rows.map((row) => row.objectKind));
    const actions = rows.flatMap((row) => row.availableActions);
    const byActionKind = countBy(actions.map((row) => row.kind));
    return {
        stateRecords: states.length,
        rows: rows.length,
        actionableRows: rows.filter((row) => row.availableActions.some((actionRow) => actionRow.requiresUserIntent)).length,
        actions: actions.length,
        receipts: receipts.length,
        reversibleReceipts: receipts.filter((receipt) => receipt.reversible).length,
        acceptedRows: byState['accepted'] || 0,
        rejectedRows: byState['rejected'] || 0,
        mutedRows: byState['muted'] || 0,
        promotedToAnchorRows: byState['promoted_to_anchor'] || 0,
        compiledToGraphRows: byState['compiled_to_graph'] || 0,
        ledgerOnlyRows: byState['ledger_only'] || 0,
        proposedRows: byState['proposed'] || 0,
        duplicateGroups: unique(rows.map((row) => row.duplicateGroupId).filter(Boolean)).length,
        byState,
        byObjectKind,
        byActionKind,
    };
}

function duplicateGroupsFor(items: ReviewObject[]): Map<string, string[]> {
    const groups = new Map<string, string[]>();
    for (const item of items) {
        const key = duplicateKeyFor(item);
        groups.set(key, [...(groups.get(key) || []), item.object.id]);
    }
    return groups;
}

function duplicateKeyFor(item: ReviewObject): string {
    const object = item.object;
    return `${item.objectKind}:${object.noteId}:${object.start}:${object.end}:${labelFor(object)}`;
}

function parentIdsFor(object: ReviewSourceObject): string[] {
    const parentId = 'parentId' in object ? object.parentId : undefined;
    if ('lineage' in object) return unique([...(object.lineage.parentUnitIds || []), parentId].filter((id): id is string => Boolean(id)));
    return [];
}

function titleFor(item: ReviewObject): string {
    if (item.objectKind === 'graph_fact_candidate') return labelFor(item.object);
    return labelFor(item.object);
}

function subtitleFor(item: ReviewObject): string {
    return `${titleCase(item.objectKind)} / ${titleCase(item.state)}`;
}

function detailFor(item: ReviewObject, duplicateCount: number): string {
    const duplicate = duplicateCount > 1 ? ` / ${duplicateCount} duplicates` : '';
    return `${titleCase(item.object.confidence.source)} / ${percent(item.object.confidence.score)}${duplicate}`;
}

function labelFor(object: ReviewSourceObject): string {
    if ('label' in object && object.label) return object.label;
    if ('preview' in object) return object.preview || object.id;
    return object.id;
}

function countBy(values: string[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values.filter(Boolean))];
}

function percent(value: number): string {
    return `${Math.round(Math.max(0, Math.min(1, value || 0)) * 100)}%`;
}

function titleCase(value: string): string {
    return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function simpleHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}
