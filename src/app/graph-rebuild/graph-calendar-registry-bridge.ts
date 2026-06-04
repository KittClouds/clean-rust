import type {
    CalendarRegistryAnchor,
    CalendarRegistrySnapshot,
} from '../lib/fantasy-calendar/calendar-registry-snapshot';

export type GraphCalendarRegistryBridgeStatus =
    | 'accepted_temporal_receipt'
    | 'registry_only'
    | 'deferred_invalid'
    | 'deferred_scope_mismatch';

export interface GraphCalendarRegistryReceipt {
    id: string;
    calendarAnchorId: string;
    sourceKind: CalendarRegistryAnchor['kind'];
    sourceId: string;
    status: GraphCalendarRegistryBridgeStatus;
    dateKey: string;
    normalizedValue: string;
    displayDate: string;
    ordinal: number;
    endOrdinal?: number;
    realEpochMs?: number;
    realIntervalEndMs?: number;
    sourceNoteIds: string[];
    evidenceRefs: string[];
    affectedGraphAtoms: string[];
    affectedGraphFacts: string[];
    reversible: true;
    mutationAllowed: false;
    rationale: string;
}

export interface GraphCalendarRegistryBridgeCounters {
    anchorCount: number;
    receiptCount: number;
    acceptedTemporalReceipts: number;
    registryOnlyReceipts: number;
    deferredInvalidReceipts: number;
    customOrdinalReceipts: number;
    realEpochReceipts: number;
    eventReceipts: number;
    folderReceipts: number;
    periodReceipts: number;
    markerReceipts: number;
    mutationAllowedCount: number;
    diagnostics: Record<string, number>;
}

export interface GraphCalendarRegistryBridgeSummary {
    schemaVersion: 'phoenix-calendar-registry-bridge/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    sourceCalendarRegistryId: string;
    calendarId: string;
    calendarFingerprint: string;
    calendarMode: CalendarRegistrySnapshot['calendar']['mode'];
    scopeKind: string;
    scopeId: string;
    receipts: GraphCalendarRegistryReceipt[];
    counters: GraphCalendarRegistryBridgeCounters;
}

export function buildGraphCalendarRegistryBridgeSummary(input: {
    calendarRegistry?: CalendarRegistrySnapshot;
    sourceSnapshotId: string;
    scopeKind: string;
    scopeId: string;
    noteIds: string[];
    generatedAt: number;
}): GraphCalendarRegistryBridgeSummary | undefined {
    const registry = input.calendarRegistry;
    if (!registry) return undefined;
    const noteIds = new Set(input.noteIds);
    const receipts = registry.anchors.map((anchor) =>
        receiptForAnchor(registry, anchor, noteIds, input.sourceSnapshotId)
    );
    return {
        schemaVersion: 'phoenix-calendar-registry-bridge/v1',
        generatedAt: input.generatedAt,
        sourceSnapshotId: input.sourceSnapshotId,
        sourceCalendarRegistryId: registry.id,
        calendarId: registry.calendar.id,
        calendarFingerprint: registry.calendar.fingerprint,
        calendarMode: registry.calendar.mode,
        scopeKind: input.scopeKind,
        scopeId: input.scopeId,
        receipts,
        counters: bridgeCounters(registry, receipts),
    };
}

function receiptForAnchor(
    registry: CalendarRegistrySnapshot,
    anchor: CalendarRegistryAnchor,
    noteIds: Set<string>,
    sourceSnapshotId: string,
): GraphCalendarRegistryReceipt {
    const status = receiptStatus(registry, anchor, noteIds);
    const atomId = `calendar-atom:${anchor.id}`;
    const factId = `calendar-temporal-fact:${anchor.id}`;
    return {
        id: `calendar-registry-receipt:${sourceSnapshotId}:${anchor.id}`,
        calendarAnchorId: anchor.id,
        sourceKind: anchor.kind,
        sourceId: anchor.sourceId,
        status,
    dateKey: anchor.dateKey,
    normalizedValue: anchor.normalizedValue,
    displayDate: anchor.displayDate,
    ordinal: anchor.ordinal,
    endOrdinal: anchor.endOrdinal,
    realEpochMs: anchor.realEpochMs,
    realIntervalEndMs: anchor.realIntervalEndMs,
    sourceNoteIds: anchor.noteId ? [anchor.noteId] : [],
        evidenceRefs: [
            ...anchor.evidenceRefs,
            `calendar:${registry.calendar.id}`,
            `calendarFingerprint:${registry.calendar.fingerprint}`,
        ],
        affectedGraphAtoms: status === 'accepted_temporal_receipt' ? [atomId] : [],
        affectedGraphFacts: status === 'accepted_temporal_receipt' ? [factId] : [],
        reversible: true,
        mutationAllowed: false,
        rationale: rationaleFor(registry, anchor, status),
    };
}

function receiptStatus(
    registry: CalendarRegistrySnapshot,
    anchor: CalendarRegistryAnchor,
    noteIds: Set<string>,
): GraphCalendarRegistryBridgeStatus {
    if (!anchor.dateKey || !Number.isFinite(anchor.ordinal)) return 'deferred_invalid';
    if (anchor.noteId && !noteIds.has(anchor.noteId)) {
        return 'deferred_scope_mismatch';
    }
    if (registry.calendar.mode === 'realEpochCompatible' && anchor.realEpochMs === undefined) {
        return 'deferred_invalid';
    }
    if (anchor.kind === 'calendar_now_marker') return 'registry_only';
    return 'accepted_temporal_receipt';
}

function rationaleFor(
    registry: CalendarRegistrySnapshot,
    anchor: CalendarRegistryAnchor,
    status: GraphCalendarRegistryBridgeStatus,
): string {
    if (status === 'accepted_temporal_receipt') {
        return registry.calendar.mode === 'realEpochCompatible'
            ? 'Calendar anchor is stable in the active scope and carries an epoch window; graph mutation remains adjudication-controlled.'
            : 'Calendar anchor is stable in the active scope and carries an ordinal fantasy-calendar coordinate; graph mutation remains adjudication-controlled.';
    }
    if (status === 'registry_only') {
        return 'Current-date marker is kept as registry state, not promoted as a historical graph fact.';
    }
    if (status === 'deferred_scope_mismatch') {
        return 'Calendar anchor points at notes outside this graph rebuild scope.';
    }
    return `Calendar anchor ${anchor.id} did not satisfy bridge validity checks.`;
}

function bridgeCounters(
    registry: CalendarRegistrySnapshot,
    receipts: GraphCalendarRegistryReceipt[],
): GraphCalendarRegistryBridgeCounters {
    return {
        anchorCount: registry.summary.anchorCount,
        receiptCount: receipts.length,
        acceptedTemporalReceipts: count(receipts, 'accepted_temporal_receipt'),
        registryOnlyReceipts: count(receipts, 'registry_only'),
        deferredInvalidReceipts: count(receipts, 'deferred_invalid') + count(receipts, 'deferred_scope_mismatch'),
        customOrdinalReceipts: registry.calendar.mode === 'customOrdinal' ? receipts.length : 0,
        realEpochReceipts: receipts.filter((receipt) => receipt.realEpochMs !== undefined).length,
        eventReceipts: sourceCount(receipts, 'user_calendar_event'),
        folderReceipts: sourceCount(receipts, 'user_calendar_folder'),
        periodReceipts: sourceCount(receipts, 'user_calendar_period'),
        markerReceipts: sourceCount(receipts, 'calendar_time_marker') + sourceCount(receipts, 'calendar_now_marker'),
        mutationAllowedCount: 0,
        diagnostics: { ...registry.summary.diagnostics },
    };
}

function count(receipts: GraphCalendarRegistryReceipt[], status: GraphCalendarRegistryBridgeStatus): number {
    return receipts.filter((receipt) => receipt.status === status).length;
}

function sourceCount(receipts: GraphCalendarRegistryReceipt[], kind: CalendarRegistryAnchor['kind']): number {
    return receipts.filter((receipt) => receipt.sourceKind === kind).length;
}
