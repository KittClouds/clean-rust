export const GALAXY_TEN_MILLION_CONTRACT_SCHEMA = 'phoenix-galaxy-capacity-contract/v1' as const;

export const GALAXY_TEN_MILLION_NODES = 10_000_000;
export const GALAXY_TEN_MILLION_EDGES = 10_000_000;

export type GalaxyInteractiveWorkBasis = 'resident-or-visible' | 'corpus';
export type GalaxyAggregateIdentityResolution = 'exact-authoritative-identities' | 'approximate';
export type GalaxyManifoldPageOwnership = 'shared' | 'per-manifold';
export type GalaxyDetailFetchScope = 'visible-detail-or-selection' | 'resident' | 'corpus';
export type GalaxyLodAuthority = 'presentation-only' | 'may-mutate-graph-truth';

export interface GalaxyTenMillionCapacityContract {
    schemaVersion: typeof GALAXY_TEN_MILLION_CONTRACT_SCHEMA;
    status: 'target';
    corpus: {
        nodeCapacity: number;
        edgeCapacity: number;
    };
    interactiveWork: {
        mainThread: GalaxyInteractiveWorkBasis;
        gpu: GalaxyInteractiveWorkBasis;
        interaction: GalaxyInteractiveWorkBasis;
        permitsFullCorpusScan: boolean;
    };
    aggregation: {
        reversible: boolean;
        identityResolution: GalaxyAggregateIdentityResolution;
    };
    manifolds: {
        identityPages: GalaxyManifoldPageOwnership;
        topologyPages: GalaxyManifoldPageOwnership;
    };
    detail: {
        fetchScope: GalaxyDetailFetchScope;
    };
    lod: {
        authority: GalaxyLodAuthority;
        mayCommitTopology: boolean;
    };
}

export type GalaxyTenMillionContractViolation =
    | 'capacity.nodes_below_10m'
    | 'capacity.edges_below_10m'
    | 'work.main_thread_scales_with_corpus'
    | 'work.gpu_scales_with_corpus'
    | 'work.interaction_scales_with_corpus'
    | 'work.full_corpus_scan_permitted'
    | 'aggregation.not_reversible'
    | 'aggregation.identity_not_exact'
    | 'manifold.identity_pages_not_shared'
    | 'manifold.topology_pages_not_shared'
    | 'detail.fetch_scope_too_broad'
    | 'lod.not_presentation_only'
    | 'lod.may_commit_topology';

/**
 * Target architecture contract. This is not a claim that the current renderer
 * is compliant; implementations must produce an independently verified
 * certificate before they may enter the 10M lane.
 */
export const GALAXY_TEN_MILLION_CONTRACT = {
    schemaVersion: GALAXY_TEN_MILLION_CONTRACT_SCHEMA,
    status: 'target',
    corpus: {
        nodeCapacity: GALAXY_TEN_MILLION_NODES,
        edgeCapacity: GALAXY_TEN_MILLION_EDGES,
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
} as const satisfies GalaxyTenMillionCapacityContract;

export function galaxyTenMillionContractViolations(
    candidate: GalaxyTenMillionCapacityContract,
): GalaxyTenMillionContractViolation[] {
    const violations: GalaxyTenMillionContractViolation[] = [];
    if (candidate.corpus.nodeCapacity < GALAXY_TEN_MILLION_NODES) {
        violations.push('capacity.nodes_below_10m');
    }
    if (candidate.corpus.edgeCapacity < GALAXY_TEN_MILLION_EDGES) {
        violations.push('capacity.edges_below_10m');
    }
    if (candidate.interactiveWork.mainThread !== 'resident-or-visible') {
        violations.push('work.main_thread_scales_with_corpus');
    }
    if (candidate.interactiveWork.gpu !== 'resident-or-visible') {
        violations.push('work.gpu_scales_with_corpus');
    }
    if (candidate.interactiveWork.interaction !== 'resident-or-visible') {
        violations.push('work.interaction_scales_with_corpus');
    }
    if (candidate.interactiveWork.permitsFullCorpusScan) {
        violations.push('work.full_corpus_scan_permitted');
    }
    if (!candidate.aggregation.reversible) {
        violations.push('aggregation.not_reversible');
    }
    if (candidate.aggregation.identityResolution !== 'exact-authoritative-identities') {
        violations.push('aggregation.identity_not_exact');
    }
    if (candidate.manifolds.identityPages !== 'shared') {
        violations.push('manifold.identity_pages_not_shared');
    }
    if (candidate.manifolds.topologyPages !== 'shared') {
        violations.push('manifold.topology_pages_not_shared');
    }
    if (candidate.detail.fetchScope !== 'visible-detail-or-selection') {
        violations.push('detail.fetch_scope_too_broad');
    }
    if (candidate.lod.authority !== 'presentation-only') {
        violations.push('lod.not_presentation_only');
    }
    if (candidate.lod.mayCommitTopology) {
        violations.push('lod.may_commit_topology');
    }
    return violations;
}

export function assertGalaxyTenMillionContract(
    candidate: GalaxyTenMillionCapacityContract,
): void {
    const violations = galaxyTenMillionContractViolations(candidate);
    if (violations.length) {
        throw new Error(`Galaxy 10M contract rejected: ${violations.join(', ')}`);
    }
}
