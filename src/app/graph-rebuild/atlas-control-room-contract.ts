import type {
    AtlasControlAction,
    AtlasControlCard,
    AtlasControlInventoryCategory,
    AtlasControlInventoryCategoryId,
    AtlasControlInvariant,
    AtlasControlReceiptPolicy,
    AtlasControlRow,
    AtlasControlTone,
} from './atlas-control-contract';

export type AtlasControlRoomId = 'entities' | 'structure' | 'facts' | 'continuity' | 'review' | 'discourse' | 'metrics';
export type AtlasControlRoomState = 'unavailable' | 'empty' | 'ready' | 'blocked' | 'error';
export type AtlasControlRoomCoverage = 'none' | 'partial' | 'complete';

export interface AtlasControlRoomActionDescriptor {
    id: string;
    roomId: AtlasControlRoomId;
    action: AtlasControlAction;
    label: string;
    enabled: boolean;
    disabledReason: string;
    receiptPolicy: AtlasControlReceiptPolicy;
}

export interface AtlasControlRoomActionRequest {
    roomId: AtlasControlRoomId;
    action: AtlasControlAction;
    rowId: string | null;
}

export interface AtlasControlRoomEmptyState {
    title: string;
    detail: string;
}

export interface AtlasControlRoom {
    id: AtlasControlRoomId;
    label: string;
    purpose: string;
    primaryInventoryCategoryId: AtlasControlInventoryCategoryId;
    inventoryCategoryIds: AtlasControlInventoryCategoryId[];
    summaryCardIds: string[];
    proofIds: string[];
    rowIds: string[];
    actionIds: string[];
    totalRows: number;
    visibleRows: number;
    coverage: AtlasControlRoomCoverage;
    state: AtlasControlRoomState;
    tone: AtlasControlTone;
    emptyState: AtlasControlRoomEmptyState;
}

export interface AtlasControlRoomProjection {
    roomIds: AtlasControlRoomId[];
    roomsById: Record<AtlasControlRoomId, AtlasControlRoom>;
    actionsById: Record<string, AtlasControlRoomActionDescriptor>;
}

export interface BuildAtlasControlRoomsInput {
    snapshotAvailable: boolean;
    inventoryById: Record<AtlasControlInventoryCategoryId, AtlasControlInventoryCategory>;
    cardsById: Record<string, AtlasControlCard>;
    rowsById: Record<string, AtlasControlRow>;
    invariants: Record<string, AtlasControlInvariant>;
}

interface RoomDefinition {
    id: AtlasControlRoomId;
    label: string;
    purpose: string;
    primary: AtlasControlInventoryCategoryId;
    inventories: AtlasControlInventoryCategoryId[];
    cards: string[];
    proofs: string[];
    actions: AtlasControlAction[];
    emptyTitle: string;
    emptyDetail: string;
}

const ROOM_DEFINITIONS: RoomDefinition[] = [
    {
        id: 'entities',
        label: 'Entities',
        purpose: 'Registry identities and their admitted graph topology.',
        primary: 'entities',
        inventories: ['entities', 'graph_edges'],
        cards: ['header-entities', 'header-graph-edges'],
        proofs: ['typedRowIdentities', 'exactInventory'],
        actions: ['add_entity', 'inspect', 'jump_to_source', 'edit_entity', 'delete_entity'],
        emptyTitle: 'No registered entities',
        emptyDetail: 'Index a note or add an entity to establish the registry inventory.',
    },
    {
        id: 'structure',
        label: 'Structure',
        purpose: 'Document, chunk, episode, and hierarchy records.',
        primary: 'structure_rows',
        inventories: ['structure_rows'],
        cards: ['room-structure'],
        proofs: ['typedRowIdentities', 'exactInventory'],
        actions: ['inspect', 'jump_to_source'],
        emptyTitle: 'No structure ledger',
        emptyDetail: 'Build the graph to produce document, chunk, episode, and hierarchy rows.',
    },
    {
        id: 'facts',
        label: 'Facts',
        purpose: 'Relations, events, temporal and causal facts, and memory states.',
        primary: 'fact_rows',
        inventories: ['fact_rows'],
        cards: ['room-facts'],
        proofs: ['typedRowIdentities', 'exactInventory', 'noTopologyWrites'],
        actions: ['inspect', 'jump_to_source', 'compare_context'],
        emptyTitle: 'No fact ledger',
        emptyDetail: 'Build the graph to populate relation and evidence-backed fact rows.',
    },
    {
        id: 'continuity',
        label: 'Continuity',
        purpose: 'Source-derived episodes, temporal order, causality, state history, and conflicts.',
        primary: 'continuity_episode_rows',
        inventories: [
            'continuity_episode_rows',
            'continuity_temporal_rows',
            'continuity_causal_rows',
            'continuity_state_rows',
            'continuity_cross_document_rows',
            'continuity_exception_rows',
        ],
        cards: [],
        proofs: ['typedRowIdentities', 'exactInventory', 'noTopologyWrites'],
        actions: ['inspect', 'jump_to_source', 'compare_context'],
        emptyTitle: 'No continuity contract',
        emptyDetail: 'Build the graph with the native continuity engine to create source-derived episode and relation candidates.',
    },
    {
        id: 'review',
        label: 'Review',
        purpose: 'One audit universe with separate manual-decision, NLI-pair, judgment, and promotion subsets.',
        primary: 'review_ledger_rows',
        inventories: [
            'review_ledger_rows',
            'manual_decision_rows',
            'nli_pair_rows',
            'nli_excluded_rows',
            'nli_judgment_rows',
            'promotion_verdict_rows',
        ],
        cards: ['review-ledger', 'review-manual-action', 'review-nli-pairs', 'review-excluded', 'review-judged'],
        proofs: ['reviewNliSeparated', 'noTopologyWrites', 'promotionReceiptGated'],
        actions: ['refresh_review', 'run_nli', 'inspect', 'jump_to_source', 'compare_context', 'show_reason'],
        emptyTitle: 'No review ledger',
        emptyDetail: 'Run review after a graph build to create the auditable ledger and its actionable subsets.',
    },
    {
        id: 'discourse',
        label: 'Discourse',
        purpose: 'Semantic bridges, episode connections, and cross-document idea packets.',
        primary: 'discourse_rows',
        inventories: ['discourse_rows', 'governance_candidate_rows'],
        cards: ['room-discourse', 'governance-candidates'],
        proofs: ['typedRowIdentities', 'candidateOnlyGovernance', 'noTopologyWrites'],
        actions: ['inspect', 'jump_to_source', 'compare_context', 'preview_promotion'],
        emptyTitle: 'No discourse bridges',
        emptyDetail: 'Build semantic and discourse stages to expose candidate-only bridge records.',
    },
    {
        id: 'metrics',
        label: 'Metrics',
        purpose: 'Run timings, transport diagnostics, certificates, and proof state.',
        primary: 'metrics_rows',
        inventories: ['metrics_rows', 'retrieval_targets'],
        cards: ['room-metrics', 'workflow-graph-build'],
        proofs: ['exactInventory', 'noTopologyWrites'],
        actions: ['inspect'],
        emptyTitle: 'No run metrics',
        emptyDetail: 'Complete a graph build to attach timing and proof records.',
    },
];

export function buildAtlasControlRooms(input: BuildAtlasControlRoomsInput): AtlasControlRoomProjection {
    const actionsById: Record<string, AtlasControlRoomActionDescriptor> = {};
    const roomsById = {} as Record<AtlasControlRoomId, AtlasControlRoom>;

    for (const definition of ROOM_DEFINITIONS) {
        const inventories = definition.inventories.map((id) => input.inventoryById[id]);
        const primary = input.inventoryById[definition.primary];
        const rowIds = unique(inventories.flatMap((inventory) => inventory.rowIds))
            .filter((rowId) => !!input.rowsById[rowId]);
        const roomActions = unique([
            ...definition.actions,
            ...inventories.flatMap((inventory) => inventory.allowedActions),
            ...rowIds.flatMap((rowId) => input.rowsById[rowId]?.allowedActions ?? []),
        ]);
        const actionIds = roomActions.map((action) => {
            const descriptor = actionDescriptor(definition.id, action, inventories, rowIds, input);
            actionsById[descriptor.id] = descriptor;
            return descriptor.id;
        });
        const coverage = coverageFor(primary.totalRows, primary.visibleRows);
        const failedProof = definition.proofs.some((proofId) => input.invariants[proofId]?.status === 'failed');
        const state: AtlasControlRoomState = !input.snapshotAvailable
            ? 'unavailable'
            : failedProof
                ? 'error'
                : primary.totalRows === 0
                    ? 'empty'
                    : 'ready';
        roomsById[definition.id] = {
            id: definition.id,
            label: definition.label,
            purpose: definition.purpose,
            primaryInventoryCategoryId: definition.primary,
            inventoryCategoryIds: [...definition.inventories],
            summaryCardIds: definition.cards.filter((id) => !!input.cardsById[id]),
            proofIds: [...definition.proofs],
            rowIds,
            actionIds,
            totalRows: primary.totalRows,
            visibleRows: primary.visibleRows,
            coverage,
            state,
            tone: failedProof ? 'danger' : primary.totalRows > 0 ? 'ready' : 'quiet',
            emptyState: { title: definition.emptyTitle, detail: definition.emptyDetail },
        };
    }

    return {
        roomIds: ROOM_DEFINITIONS.map((definition) => definition.id),
        roomsById,
        actionsById,
    };
}

function actionDescriptor(
    roomId: AtlasControlRoomId,
    action: AtlasControlAction,
    inventories: AtlasControlInventoryCategory[],
    rowIds: string[],
    input: BuildAtlasControlRoomsInput,
): AtlasControlRoomActionDescriptor {
    const matchingInventory = inventories.find((inventory) => inventory.allowedActions.includes(action));
    const matchingRow = rowIds.map((rowId) => input.rowsById[rowId])
        .find((row) => row?.allowedActions.includes(action));
    const enabled = actionEnabled(action, matchingInventory, matchingRow, rowIds.length, input.snapshotAvailable);
    return {
        id: `${roomId}:${action}`,
        roomId,
        action,
        label: actionLabel(action),
        enabled,
        disabledReason: enabled ? '' : disabledReason(action, input.snapshotAvailable),
        receiptPolicy: matchingRow?.receiptPolicy ?? matchingInventory?.receiptPolicy ?? noReceipt(),
    };
}

function actionEnabled(
    action: AtlasControlAction,
    inventory: AtlasControlInventoryCategory | undefined,
    row: AtlasControlRow | undefined,
    visibleRows: number,
    snapshotAvailable: boolean,
): boolean {
    if (action === 'add_entity') return true;
    if (!snapshotAvailable && action !== 'build_graph') return false;
    if (action === 'refresh_review') return snapshotAvailable;
    if (action === 'run_nli') return inventory?.actionability === 'model_run' && inventory.totalRows > 0;
    if (action === 'inspect' || action === 'jump_to_source' || action === 'compare_context' || action === 'show_reason') {
        return visibleRows > 0;
    }
    return !!row || (!!inventory && inventory.totalRows > 0);
}

function disabledReason(action: AtlasControlAction, snapshotAvailable: boolean): string {
    if (!snapshotAvailable) return 'Build or load a graph snapshot first.';
    if (action === 'run_nli') return 'No premise/hypothesis pairs are available for ModernBERT.';
    return 'No compatible rows are available for this action.';
}

function actionLabel(action: AtlasControlAction): string {
    const labels: Record<AtlasControlAction, string> = {
        build_graph: 'Build graph',
        refresh_review: 'Refresh review',
        run_nli: 'Run NLI',
        inspect: 'Inspect',
        jump_to_source: 'Open source',
        compare_context: 'Compare context',
        show_reason: 'Show rationale',
        accept_review_row: 'Accept',
        reject_review_row: 'Reject',
        promote_to_anchor: 'Promote to anchor',
        merge_duplicates: 'Merge duplicates',
        demote_to_sidecar: 'Demote to sidecar',
        mute_pattern: 'Mute pattern',
        compile_to_graph: 'Compile to graph',
        preview_promotion: 'Preview promotion',
        add_entity: 'Add entity',
        edit_entity: 'Edit entity',
        delete_entity: 'Delete entity',
        split_episode: 'Split episode',
        merge_episodes: 'Merge episodes',
        confirm_boundary: 'Confirm boundary',
        confirm_ordering: 'Confirm ordering',
        reject_ordering: 'Reject ordering',
        confirm_causal_link: 'Confirm causal link',
        reject_causal_link: 'Reject causal link',
        resolve_continuity_conflict: 'Resolve conflict',
    };
    return labels[action];
}

function coverageFor(totalRows: number, visibleRows: number): AtlasControlRoomCoverage {
    if (visibleRows === 0) return 'none';
    return visibleRows >= totalRows ? 'complete' : 'partial';
}

function noReceipt(): AtlasControlReceiptPolicy {
    return { required: false, kind: null, reversible: false, topologyMutationAllowed: false };
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}
