import { describe, expect, it } from 'vitest';

import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
import { buildCompatibilityGraphCompilerSidecar } from './graph-compiler-compat';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildGraphCalendarRegistryBridgeSummary } from './graph-calendar-registry-bridge';

describe('graph calendar registry bridge', () => {
    it('projects calendar anchors as reversible temporal receipts without mutation rights', () => {
        const summary = buildGraphCalendarRegistryBridgeSummary({
            calendarRegistry: registrySnapshot(),
            sourceSnapshotId: 'snapshot:test',
            scopeKind: 'note',
            scopeId: 'note:note-1',
            noteIds: ['note-1'],
            generatedAt: 55,
        });

        expect(summary?.schemaVersion).toBe('phoenix-calendar-registry-bridge/v1');
        expect(summary?.counters).toMatchObject({
            anchorCount: 1,
            receiptCount: 1,
            acceptedTemporalReceipts: 1,
            customOrdinalReceipts: 1,
            mutationAllowedCount: 0,
        });
        expect(summary?.receipts[0]).toMatchObject({
            status: 'accepted_temporal_receipt',
            sourceKind: 'user_calendar_event',
            dateKey: 'cal:calendar-1|era:era-1|y:2|m:1|d:4',
            ordinal: 393,
            reversible: true,
            mutationAllowed: false,
            affectedGraphAtoms: ['calendar-atom:calendar-anchor:event-1'],
            affectedGraphFacts: ['calendar-temporal-fact:calendar-anchor:event-1'],
        });
    });

    it('attaches bridge counters to graph rebuild snapshots without changing topology', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:note-1',
            noteIds: ['note-1'],
            entities: [],
            occurrences: [],
            calendarRegistrySnapshot: registrySnapshot(),
            builtAt: 77,
        });

        expect(snapshot.calendarRegistrySummary?.counters.acceptedTemporalReceipts).toBe(1);
        expect(snapshot.counters.calendarRegistryReceipts).toBe(1);
        expect(snapshot.counters.calendarRegistryMutationAllowed).toBe(0);
        expect(snapshot.nodes).toHaveLength(0);
        expect(snapshot.edges).toHaveLength(0);
    });

    it('keeps compatibility compiler calendar anchors out of projected topology', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:note-1',
            noteIds: ['note-1'],
            entities: [],
            occurrences: [],
            calendarRegistrySnapshot: registrySnapshot(),
            builtAt: 77,
        });
        const sidecar = buildCompatibilityGraphCompilerSidecar(snapshot);

        expect(sidecar.factGraph.atoms).toEqual(expect.arrayContaining([
            expect.objectContaining({ kind: 'timeAnchor', sourceId: 'calendar-anchor:event-1' }),
        ]));
        expect(sidecar.factGraph.evidenceAnchors).toEqual(expect.arrayContaining([
            expect.objectContaining({ kind: 'calendarRegistry' }),
        ]));
        expect(sidecar.projectedUiGraph).toHaveLength(0);
    });
});

function registrySnapshot(): CalendarRegistrySnapshot {
    return {
        schemaVersion: 'phoenix-calendar-registry/v1',
        id: 'calendar-registry:scope-1',
        builtAt: 44,
        calendar: {
            id: 'calendar-1',
            name: 'New World Calendar',
            fingerprint: 'calendar-fingerprint:one',
            mode: 'customOrdinal',
            createdFrom: 'manual',
            monthCount: 12,
            weekdayCount: 7,
            hasYearZero: false,
            defaultEraId: 'era-1',
        },
        scope: { kind: 'note', scopeId: 'note:note-1', noteIds: ['note-1'] },
        anchors: [{
            id: 'calendar-anchor:event-1',
            kind: 'user_calendar_event',
            sourceId: 'event-1',
            sourceLabel: 'Festival',
            calendarId: 'calendar-1',
            calendarFingerprint: 'calendar-fingerprint:one',
            dateKey: 'cal:calendar-1|era:era-1|y:2|m:1|d:4',
            normalizedValue: 'CAL:calendar-1:cal:calendar-1|era:era-1|y:2|m:1|d:4',
            displayDate: 'Month 2 4, 2 CE',
            granularity: 'day',
            date: { year: 2, monthIndex: 1, dayIndex: 3, eraId: 'era-1' },
            ordinal: 393,
            noteId: 'note-1',
            confidence: 0.92,
            evidenceRefs: ['calendar:event:event-1'],
            attributes: { calendarControlled: true },
        }],
        summary: {
            anchorCount: 1,
            eventAnchorCount: 1,
            folderAnchorCount: 0,
            periodAnchorCount: 0,
            markerAnchorCount: 0,
            realCompatibleAnchorCount: 0,
            customOrdinalAnchorCount: 1,
            sourceKindCounts: { user_calendar_event: 1 },
            diagnostics: {},
            firstOrdinal: 393,
            lastOrdinal: 393,
        },
    };
}
