import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { phoenixTransportAudit } from './phoenix-transport-audit';

describe('phoenixTransportAudit', () => {
    beforeEach(() => {
        phoenixTransportAudit.reset();
    });

    afterEach(() => {
        phoenixTransportAudit.reset();
    });

    it('tracks json and typed RPC byte counts separately', async () => {
        const jsonResult = await phoenixTransportAudit.measureJsonRpc(
            'phoenix.store_command:test',
            '{"hello":"world"}',
            async () => '{"success":true,"payload":{"ok":true}}',
            (raw) => JSON.parse(raw) as { success: boolean; payload: { ok: boolean } },
        );
        const typedResult = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.boot_snapshot',
            { noteHeaders: [] },
            async () => ({ noteHeaders: [{ id: 'note-1' }], entities: [], edges: [], folders: [], eventNotes: [] }),
        );

        expect(jsonResult.payload.ok).toBe(true);
        expect(typedResult.noteHeaders).toHaveLength(1);

        const snapshot = phoenixTransportAudit.snapshot();
        expect(snapshot.totalCalls).toBe(2);
        expect(snapshot.totalRequestBytes).toBeGreaterThan(0);
        expect(snapshot.totalResponseBytes).toBeGreaterThan(0);
        expect(snapshot.calls.map((call) => call.kind)).toEqual(['taurpc-json', 'taurpc-typed']);
    });

    it('tracks boot phases without transport payload sizes', async () => {
        await phoenixTransportAudit.measureBootPhase('dexie.snapshotApply', async () => undefined);

        const snapshot = phoenixTransportAudit.snapshot();
        expect(snapshot.totalCalls).toBe(1);
        expect(snapshot.calls[0]).toMatchObject({
            name: 'dexie.snapshotApply',
            kind: 'boot-phase',
            totalRequestBytes: 0,
            totalResponseBytes: 0,
            errors: 0,
        });
    });

    it('attaches payload counters without recording a second transport call', async () => {
        await phoenixTransportAudit.measureJsonRpc(
            'phoenix.store_command:test',
            '{"kind":"ApplyWalBatch"}',
            async () => '{"success":true,"payload":{"replayed":2,"timings":{"totalMs":7}}}',
            (raw) => JSON.parse(raw) as { success: boolean; payload: { replayed: number } },
        );

        phoenixTransportAudit.recordPayloadCounters('phoenix.store_command:test', 'taurpc-json', {
            'payload.replayed': 2,
            'payload.timings.totalMs': 7,
        });

        const snapshot = phoenixTransportAudit.snapshot();
        expect(snapshot.totalCalls).toBe(1);
        expect(snapshot.calls[0]).toMatchObject({
            name: 'phoenix.store_command:test',
            kind: 'taurpc-json',
            count: 1,
        });
        expect(snapshot.calls[0]?.counters).toMatchObject({
            'payload.replayed': 2,
            'payload.timings.totalMs': 7,
        });
        expect(snapshot.recentCalls).toHaveLength(1);
    });
});
