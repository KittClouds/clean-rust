import '@angular/compiler';
import {
    Injector,
    computed,
    createEnvironmentInjector,
    runInInjectionContext,
    signal,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GraphRebuildService } from '../graph-rebuild/graph-rebuild.service';
import { buildReviewAdjudicationRunCertificate } from '../graph-rebuild/graph-review-adjudication-certificate';
import { NliWorkerService } from '../lib/services/nli-worker.service';
import { PhoenixProjectionService } from './phoenix-projection.service';
import { AtlasControlContractService } from './atlas-control-contract.service';

describe('AtlasControlContractService', () => {
    let injector: EnvironmentInjector;
    let owner: AtlasControlContractService;
    let snapshot: ReturnType<typeof signal<any>>;
    let nativePaging: ReturnType<typeof signal<any>>;
    let readPage: ReturnType<typeof vi.fn>;
    let releaseLease: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        snapshot = signal<any>(null);
        nativePaging = signal<any>(null);
        readPage = vi.fn();
        releaseLease = vi.fn(async () => true);
        const graphRebuild = {
            snapshot,
            isBuilding: computed(() => false),
            nativeGraphRunPaging: computed(() => nativePaging()),
            readNativeGraphRunPageForHandle: readPage,
            releaseNativeGraphRunLease: releaseLease,
            attachReviewAdjudicationCertificate: vi.fn((certificate: unknown) => {
                snapshot.update((current) => current ? { ...current, reviewAdjudicationCertificate: certificate } : current);
            }),
        };
        const nli = {
            isInitialized: signal(false),
            modelId: signal<string | null>(null),
            isProcessing: signal(false),
            progress: signal(null),
        };
        const parent = Injector.create({ providers: [] }) as unknown as EnvironmentInjector;
        injector = createEnvironmentInjector([
            { provide: GraphRebuildService, useValue: graphRebuild },
            { provide: NliWorkerService, useValue: nli },
            {
                provide: PhoenixProjectionService,
                useValue: {
                    entityCount: computed(() => 50),
                    entities: computed(() => []),
                },
            },
        ], parent);
        owner = runInInjectionContext(injector, () => new AtlasControlContractService());
    });

    afterEach(() => injector.destroy());

    it('publishes one count and one action state to every consumer', () => {
        const graph = graphSnapshot();
        graph.reviewAdjudicationCertificate = buildReviewAdjudicationRunCertificate({
            snapshot: graph,
            source: 'graph_build',
            rawResult: { plannedInputCount: 3 },
        });
        snapshot.set(graph);

        expect(owner.reviewView().queue.nliPairRows).toBe(3);
        expect(owner.contract().inventoryById.nli_pair_rows.totalRows).toBe(3);
        expect(owner.reviewView().action.label).toBe('Load + Run');
        expect(owner.contract().cardsById['review-nli-pairs'].allowedActions).toEqual(['run_nli']);

        owner.setNliOperationState('running');

        expect(owner.reviewView().action.label).toBe('Reviewing');
        expect(owner.contract().cardsById['review-nli-pairs'].allowedActions).toEqual([]);
    });

    it('publishes manual run output through the graph snapshot certificate boundary', () => {
        snapshot.set(graphSnapshot());

        const certificate = owner.publishReviewRun({
            plannedInputCount: 2,
            resultCount: 2,
            topologyWrites: 0,
        });

        expect(snapshot().reviewAdjudicationCertificate).toBe(certificate);
        expect(owner.contract().inventoryById.nli_judgment_rows.totalRows).toBe(2);
        expect(owner.contract().invariants.reviewNliSeparated.status).toBe('passed');
    });

    it('drops a late page from a superseded run and publishes only the current page', async () => {
        snapshot.set({ ...graphSnapshot(), counters: { memoryGovernanceCandidates: 1 } });
        nativePaging.set(paging('run:old'));
        const pending = deferred<any>();
        readPage.mockReturnValueOnce(pending.promise);

        const staleLoad = owner.loadNextProofPage();
        nativePaging.set(paging('run:new'));
        pending.resolve(nativePage('run:old', governanceCandidate('stale')));
        await staleLoad;

        expect(owner.proofPaging().runHandle).toBe('run:new');
        expect(owner.contract().rows.some((row) => row.identity.rawId === 'stale')).toBe(false);

        readPage.mockResolvedValueOnce(nativePage('run:new', governanceCandidate('current')));
        await owner.loadNextProofPage();

        expect(owner.proofPaging()).toMatchObject({ status: 'complete', loadedRows: 16 });
        expect(owner.contract().rows.filter((row) => row.identity.rawId === 'current')).toHaveLength(1);
    });

    it('releases one native lease exactly once', async () => {
        nativePaging.set(paging('run:release'));

        expect(await owner.releaseProofLease()).toBe(true);
        expect(await owner.releaseProofLease()).toBe(false);
        expect(releaseLease).toHaveBeenCalledTimes(1);
        expect(releaseLease).toHaveBeenCalledWith('run:release');
    });
});

function graphSnapshot(): any {
    return {
        id: 'snapshot:owner-test',
        scopeKind: 'note',
        scopeId: 'note:test',
        noteIds: ['note:test'],
        counters: { documentReviewRows: 5 },
        memoryGovernanceCandidates: [],
        nodes: [],
        edges: [],
        embeddingTargets: [],
    };
}

function paging(runHandle: string): any {
    return {
        snapshotId: 'snapshot:owner-test',
        runHandle,
        totalRows: 16,
        loadedRows: 8,
        nextOffset: 8,
        counts: {
            crossDocumentPairCoverage: 0,
            crossDocumentSelected: 0,
            crossDocumentRejected: 0,
            continuityBoundaries: 0,
            continuityEpisodes: 0,
            continuityTemporal: 0,
            continuityStates: 0,
            continuityCausal: 0,
            continuityConnections: 0,
            continuityConflicts: 0,
        },
    };
}

function nativePage(runHandle: string, row: any): any {
    return {
        runHandle,
        returnedDetailRows: 8,
        nextOffset: null,
        projection: {
            bridge: { candidates: [], crossDocumentCertificate: null },
            continuity: { contract: null },
            governance: { candidates: [row] },
            promotion: { certificate: null },
        },
    };
}

function governanceCandidate(id: string): any {
    return {
        schemaVersion: 'phoenix-memory-governance-candidate/v1',
        id,
        targetId: 'chunk:1',
        targetKind: 'chunk',
        action: 'retain',
        reason: 'keep vivid',
        evidenceIds: ['evidence:1'],
        supportingEntityIds: [],
        relatedEventIds: [],
        relatedChunkIds: [],
        signals: {},
        confidence: 0.8,
        status: 'candidate',
        commitPolicy: 'candidate_only_no_topology_commit',
        noTopologyCommit: true,
        rationale: [],
    };
}

function deferred<T>(): { promise: Promise<T>; resolve(value: T): void } {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((next) => { resolve = next; });
    return { promise, resolve };
}
