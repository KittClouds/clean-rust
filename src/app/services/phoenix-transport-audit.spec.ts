import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { phoenixTransportAudit } from './phoenix-transport-audit';

describe('phoenixTransportAudit', () => {
    beforeEach(() => {
        phoenixTransportAudit.reset();
    });

    afterEach(() => {
        phoenixTransportAudit.reset();
    });

    it('tracks owned JSON bytes and marks opaque typed codec bytes unavailable', async () => {
        const jsonResult = await phoenixTransportAudit.measureJsonRpc(
            'phoenix.store_command:test',
            '{"hello":"world"}',
            async () => '{"success":true,"payload":{"ok":true}}',
            (raw) => JSON.parse(raw) as { success: boolean; payload: { ok: boolean } },
        );
        const typedResult = await phoenixTransportAudit.measureTypedRpc(
            'phoenix.boot_snapshot',
            async () => ({ noteHeaders: [{ id: 'note-1' }], entities: [], edges: [], folders: [], eventNotes: [] }),
        );

        expect(jsonResult.payload.ok).toBe(true);
        expect(typedResult.noteHeaders).toHaveLength(1);

        const snapshot = phoenixTransportAudit.snapshot();
        expect(snapshot.totalCalls).toBe(2);
        expect(snapshot.totalRequestBytes).toBeGreaterThan(0);
        expect(snapshot.totalResponseBytes).toBeGreaterThan(0);
        expect(snapshot.calls.map((call) => call.kind).sort()).toEqual(['taurpc-json', 'taurpc-typed']);
        const typed = snapshot.calls.find((call) => call.kind === 'taurpc-typed');
        expect(typed).toMatchObject({
            totalRequestBytes: 0,
            totalResponseBytes: 0,
            requestBytesUnavailableCalls: 1,
            responseBytesUnavailableCalls: 1,
            encodeTimingUnavailableCalls: 1,
            decodeTimingUnavailableCalls: 1,
        });
    });

    it('does not traverse typed payloads to estimate transport bytes', async () => {
        let traversals = 0;
        const response = {
            ok: true,
            toJSON() {
                traversals += 1;
                throw new Error('typed payload must not be stringified by instrumentation');
            },
        };

        await expect(phoenixTransportAudit.measureTypedRpc(
            'phoenix.analyze_graph_snapshot',
            async () => response,
        )).resolves.toBe(response);

        expect(traversals).toBe(0);
        expect(phoenixTransportAudit.snapshot().recentCalls[0]).toMatchObject({
            requestBytes: null,
            responseBytes: null,
            encodeMs: null,
            decodeMs: null,
            ok: true,
        });
    });

    it('accepts byte and codec metrics only from an explicit boundary owner', async () => {
        await phoenixTransportAudit.measureTypedRpc(
            'phoenix.codec_owned',
            async () => ({ ok: true }),
            () => ({ requestBytes: 12, responseBytes: 34, encodeMs: 0.5, decodeMs: 0.75 }),
        );

        expect(phoenixTransportAudit.snapshot().calls[0]).toMatchObject({
            totalRequestBytes: 12,
            totalResponseBytes: 34,
            requestBytesMeasuredCalls: 1,
            responseBytesMeasuredCalls: 1,
            totalEncodeMs: 0.5,
            totalDecodeMs: 0.75,
        });
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
