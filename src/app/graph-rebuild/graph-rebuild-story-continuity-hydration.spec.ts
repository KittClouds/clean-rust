import '@angular/compiler';
import { Injector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import { GraphRebuildService, type NativeGraphRunPage } from './graph-rebuild.service';
import type { GraphStoryContinuityContract } from './graph-story-continuity';

describe('GraphRebuildService native story continuity hydration', () => {
    it('coalesces paging, installs exact certificate counts, and persists once', async () => {
        const { injector, service } = serviceFixture();
        const events = Array.from({ length: 513 }, (_, index) => ({ id: `event:${index}` }));
        const episode = { id: 'episode:1' };
        const header = continuityContract(513, 1);
        const first = pageFixture(header, {
            events: events.slice(0, 512),
            episodes: [],
        }, 0, 512, 514);
        const second = pageFixture(header, {
            events: events.slice(512),
            episodes: [episode],
        }, 512, null, 514);
        const read = vi.spyOn(service, 'readNativeGraphRunPageForHandle')
            .mockResolvedValueOnce(first)
            .mockResolvedValueOnce(second);
        const persist = vi.spyOn(service as any, 'persistSnapshot').mockResolvedValue(undefined);

        const [left, right] = await Promise.all([
            service.hydrateNativeStoryContinuity(),
            service.hydrateNativeStoryContinuity(),
        ]);

        expect(left).toBe(right);
        expect(left?.events).toHaveLength(513);
        expect(left?.episodes).toHaveLength(1);
        expect(read).toHaveBeenCalledTimes(2);
        expect(read).toHaveBeenNthCalledWith(1, 'graph-run:test', 0, 512, 'storyContinuity');
        expect(read).toHaveBeenNthCalledWith(2, 'graph-run:test', 512, 512, 'storyContinuity');
        expect(persist).toHaveBeenCalledTimes(1);
        expect(service.snapshot()?.storyContinuity).toBe(left);
        injector.destroy();
    });

    it('fails closed before installation when rows do not match the certificate', async () => {
        const { injector, service } = serviceFixture();
        const header = continuityContract(1, 0);
        vi.spyOn(service, 'readNativeGraphRunPageForHandle').mockResolvedValue(
            pageFixture(header, { events: [{ id: 'event:0' }], episodes: [] }, 0, null, 2),
        );
        const persist = vi.spyOn(service as any, 'persistSnapshot').mockResolvedValue(undefined);

        await expect(service.hydrateNativeStoryContinuity()).rejects.toThrow(
            'Native story continuity count mismatch',
        );
        expect(persist).not.toHaveBeenCalled();
        expect(service.snapshot()?.storyContinuity?.events).toHaveLength(0);
        injector.destroy();
    });
});

function serviceFixture(): {
    injector: ReturnType<typeof createEnvironmentInjector>;
    service: GraphRebuildService;
} {
    const injector = createEnvironmentInjector([
        { provide: PhoenixStoreService, useValue: {} },
        { provide: PhoenixBackendService, useValue: { target: 'native' } },
    ], Injector.create({ providers: [] }));
    const service = runInInjectionContext(injector, () => new GraphRebuildService());
    const partial = continuityContract(513, 1);
    (service as any).snapshotState.set({
        id: 'snapshot:test',
        scopeId: 'scope:test',
        counters: {},
        contentManifest: undefined,
        authorityContract: { contentHash: 'hash:test' },
        storyContinuity: { ...partial, events: [], episodes: [] },
    });
    (service as any).activeNativeGraphRun = {
        snapshotId: 'snapshot:test',
        runHandle: 'graph-run:test',
    };
    return { injector, service };
}

function continuityContract(events: number, episodes: number): GraphStoryContinuityContract {
    return {
        schemaVersion: 'phoenix-story-continuity/v1',
        source: 'rust_story_continuity',
        sourceSnapshotId: 'snapshot:test',
        generatedAt: 1,
        commitPolicy: 'candidate_only',
        noTopologyCommit: true,
        events: [],
        boundaryReceipts: [],
        episodes: [],
        temporalCandidates: [],
        stateIntervals: [],
        causalCandidates: [],
        episodeConnections: [],
        conflicts: [],
        certificate: {
            schemaVersion: 'phoenix-story-continuity-run-certificate/v1',
            sourceSnapshotId: 'snapshot:test',
            sourceDocumentIds: ['note:test'],
            buildMicros: 1,
            eventIdentityMicros: 1,
            episodeBoundaryMicros: 1,
            relationResolutionMicros: 1,
            counters: {
                events,
                boundaryReceipts: 0,
                episodes,
                temporalCandidates: 0,
                stateIntervals: 0,
                causalCandidates: 0,
                episodeConnections: 0,
                conflicts: 0,
                crossDocumentConnections: 0,
                reviewRequired: 0,
            },
            noTopologyWrites: true,
            allRowsEvidenced: true,
            stableSourceIdentities: true,
            fixedBatchingDetected: false,
            invariantReceipts: [],
        },
    };
}

function pageFixture(
    header: GraphStoryContinuityContract,
    rows: { events: Array<{ id: string }>; episodes: Array<{ id: string }> },
    offset: number,
    nextOffset: number | null,
    detailRows: number,
): NativeGraphRunPage {
    return {
        section: 'storyContinuity',
        runHandle: 'graph-run:test',
        offset,
        nextOffset,
        detailRows,
        projection: {
            continuity: {
                contract: {
                    ...header,
                    events: rows.events,
                    episodes: rows.episodes,
                },
            },
        },
    } as NativeGraphRunPage;
}
