import '@angular/compiler';
import {
    Injector,
    createEnvironmentInjector,
    runInInjectionContext,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GraphRebuildService } from '../graph-rebuild/graph-rebuild.service';
import { GfmRetrievalShadowService } from './gfm-retrieval-shadow.service';
import { PhoenixBackendService, type PhoenixGfmShadowReceipt } from './phoenix-backend.service';

describe('GfmRetrievalShadowService', () => {
    let injector: EnvironmentInjector;
    let queryGfmShadow: ReturnType<typeof vi.fn>;
    let service: GfmRetrievalShadowService;

    beforeEach(() => {
        queryGfmShadow = vi.fn();
        injector = createEnvironmentInjector(
            [
                {
                    provide: PhoenixBackendService,
                    useValue: { target: 'native', queryGfmShadow },
                },
                {
                    provide: GraphRebuildService,
                    useValue: { residentNativeGraphRunHandle: () => 'graph-run:test' },
                },
            ],
            Injector.create({ providers: [] }),
        );
        service = runInInjectionContext(injector, () => new GfmRetrievalShadowService());
    });

    afterEach(() => injector.destroy());

    it('records a bounded shadow receipt without claiming visible authority', async () => {
        queryGfmShadow.mockResolvedValue(receipt(1));

        await service.observe('where is the harbor', ['doc:a', 'doc:a'], 500);

        expect(queryGfmShadow).toHaveBeenCalledWith({
            runHandle: 'graph-run:test',
            query: 'where is the harbor',
            requestGeneration: 1,
            semanticDocumentIds: ['doc:a'],
            limit: 50,
        });
        expect(service.lastReceipt()?.visibleRankingUnchanged).toBe(true);
        expect(service.lastFailure()).toBeNull();
    });

    it('discards stale completions after a newer query starts', async () => {
        let resolveFirst!: (value: PhoenixGfmShadowReceipt) => void;
        queryGfmShadow
            .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
            .mockResolvedValueOnce(receipt(2));

        const first = service.observe('first', ['doc:a'], 5);
        await service.observe('second', ['doc:b'], 5);
        resolveFirst(receipt(1));
        await first;

        expect(service.lastReceipt()?.requestGeneration).toBe(2);
    });

    it('rejects any receipt that claims graph or ranking authority', async () => {
        queryGfmShadow.mockResolvedValue({
            ...receipt(1),
            noTopologyWrites: false,
        });

        await service.observe('unsafe', ['doc:a'], 5);

        expect(service.lastReceipt()).toBeNull();
        expect(service.lastFailure()).toContain('authority shield');
    });
});

function receipt(requestGeneration: number): PhoenixGfmShadowReceipt {
    return {
        schemaVersion: 'phoenix.gfm-retrieval-shadow/v1',
        source: 'rust-gfm-rag-8m',
        status: 'completed',
        reason: null,
        requestGeneration,
        snapshotId: 'snapshot:test',
        selectedSeedIds: ['entity:a'],
        results: [{ stableId: 'inference:document:doc:a', documentId: 'doc:a' }],
        evidenceEntityIds: ['entity:a'],
        semanticResultCount: 1,
        overlapCount: 1,
        uniqueGfmCount: 0,
        bundleReused: true,
        encoderResidentReused: true,
        relationRowsReused: 1,
        relationRowsComputed: 0,
        excludedCandidateEdges: 2,
        excludedRejectedEdges: 1,
        noTopologyWrites: true,
        visibleRankingUnchanged: true,
        timing: { indexMicros: 1, inferenceMicros: 2, totalMicros: 3 },
    };
}
