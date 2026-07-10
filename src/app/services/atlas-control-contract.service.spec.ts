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

    beforeEach(() => {
        snapshot = signal<any>(null);
        const graphRebuild = {
            snapshot,
            isBuilding: computed(() => false),
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
