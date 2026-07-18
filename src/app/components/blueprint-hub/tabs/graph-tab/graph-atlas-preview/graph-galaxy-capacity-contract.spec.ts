import { describe, expect, it } from 'vitest';

import {
    assertGalaxyTenMillionContract,
    GALAXY_TEN_MILLION_CONTRACT,
    GALAXY_TEN_MILLION_CONTRACT_SCHEMA,
    galaxyTenMillionContractViolations,
    type GalaxyTenMillionCapacityContract,
    type GalaxyTenMillionContractViolation,
} from './graph-galaxy-capacity-contract';

describe('Galaxy 10M capacity contract', () => {
    it('freezes the exact v1 target without claiming current runtime compliance', () => {
        expect(GALAXY_TEN_MILLION_CONTRACT).toEqual({
            schemaVersion: 'phoenix-galaxy-capacity-contract/v1',
            status: 'target',
            corpus: {
                nodeCapacity: 10_000_000,
                edgeCapacity: 10_000_000,
            },
            interactiveWork: {
                mainThread: 'resident-or-visible',
                gpu: 'resident-or-visible',
                interaction: 'resident-or-visible',
                permitsFullCorpusScan: false,
            },
            aggregation: {
                reversible: true,
                identityResolution: 'exact-authoritative-identities',
            },
            manifolds: {
                identityPages: 'shared',
                topologyPages: 'shared',
            },
            detail: {
                fetchScope: 'visible-detail-or-selection',
            },
            lod: {
                authority: 'presentation-only',
                mayCommitTopology: false,
            },
        });
        expect(GALAXY_TEN_MILLION_CONTRACT.schemaVersion).toBe(GALAXY_TEN_MILLION_CONTRACT_SCHEMA);
        expect(galaxyTenMillionContractViolations(GALAXY_TEN_MILLION_CONTRACT)).toEqual([]);
        expect(() => assertGalaxyTenMillionContract(GALAXY_TEN_MILLION_CONTRACT)).not.toThrow();
    });

    it.each([
        ['capacity.nodes_below_10m', (candidate) => { candidate.corpus.nodeCapacity = 9_999_999; }],
        ['capacity.edges_below_10m', (candidate) => { candidate.corpus.edgeCapacity = 9_999_999; }],
        ['work.main_thread_scales_with_corpus', (candidate) => { candidate.interactiveWork.mainThread = 'corpus'; }],
        ['work.gpu_scales_with_corpus', (candidate) => { candidate.interactiveWork.gpu = 'corpus'; }],
        ['work.interaction_scales_with_corpus', (candidate) => { candidate.interactiveWork.interaction = 'corpus'; }],
        ['work.full_corpus_scan_permitted', (candidate) => { candidate.interactiveWork.permitsFullCorpusScan = true; }],
        ['aggregation.not_reversible', (candidate) => { candidate.aggregation.reversible = false; }],
        ['aggregation.identity_not_exact', (candidate) => { candidate.aggregation.identityResolution = 'approximate'; }],
        ['manifold.identity_pages_not_shared', (candidate) => { candidate.manifolds.identityPages = 'per-manifold'; }],
        ['manifold.topology_pages_not_shared', (candidate) => { candidate.manifolds.topologyPages = 'per-manifold'; }],
        ['detail.fetch_scope_too_broad', (candidate) => { candidate.detail.fetchScope = 'corpus'; }],
        ['lod.not_presentation_only', (candidate) => { candidate.lod.authority = 'may-mutate-graph-truth'; }],
        ['lod.may_commit_topology', (candidate) => { candidate.lod.mayCommitTopology = true; }],
    ] satisfies ReadonlyArray<readonly [GalaxyTenMillionContractViolation, (candidate: GalaxyTenMillionCapacityContract) => void]>) (
        'rejects %s',
        (expectedViolation, mutate) => {
            const candidate = structuredClone(GALAXY_TEN_MILLION_CONTRACT) as GalaxyTenMillionCapacityContract;
            mutate(candidate);

            expect(galaxyTenMillionContractViolations(candidate)).toContain(expectedViolation);
            expect(() => assertGalaxyTenMillionContract(candidate)).toThrow(expectedViolation);
        },
    );

    it('reports every violated invariant in one admission result', () => {
        const candidate = structuredClone(GALAXY_TEN_MILLION_CONTRACT) as GalaxyTenMillionCapacityContract;
        candidate.corpus.nodeCapacity = 1;
        candidate.corpus.edgeCapacity = 1;
        candidate.interactiveWork.mainThread = 'corpus';
        candidate.interactiveWork.gpu = 'corpus';
        candidate.interactiveWork.interaction = 'corpus';
        candidate.interactiveWork.permitsFullCorpusScan = true;
        candidate.aggregation.reversible = false;
        candidate.aggregation.identityResolution = 'approximate';
        candidate.manifolds.identityPages = 'per-manifold';
        candidate.manifolds.topologyPages = 'per-manifold';
        candidate.detail.fetchScope = 'resident';
        candidate.lod.authority = 'may-mutate-graph-truth';
        candidate.lod.mayCommitTopology = true;

        expect(galaxyTenMillionContractViolations(candidate)).toHaveLength(13);
    });
});
