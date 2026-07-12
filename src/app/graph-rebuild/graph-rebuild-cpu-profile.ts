export interface GraphRebuildSnapshotCpuProfile {
    snapshotAnchorsMs: number;
    snapshotFactsMs: number;
    snapshotCompatibilityViewsMs: number;
    snapshotTargetsMs: number;
    snapshotPostProcessMs: number;
    snapshotEmbeddingPostProcessMs: number;
    snapshotEmbeddingSignaturesMs: number;
    snapshotEmbeddingPairPlanMs: number;
    snapshotEmbeddingNeighborsMs: number;
    snapshotEmbeddingClustersMs: number;
    snapshotEmbeddingRowsEdgesMs: number;
    snapshotGraphAwareLinksMs: number;
    snapshotEntityLinkingMs: number;
    snapshotAssemblyMs: number;
    snapshotSemanticTasksMs: number;
    snapshotSemanticCandidatesMs: number;
    snapshotManifoldSpecializationMs: number;
    snapshotSemanticRerankMs: number;
    snapshotSemanticAdjudicationMs: number;
    snapshotSemanticEvalLedgerMs: number;
    snapshotSemanticLedgersMs: number;
    snapshotSemanticIndexBuilds: number;
    snapshotSemanticIndexEntries: number;
    snapshotSemanticAvoidedIndexBuilds: number;
    snapshotSemanticAvoidedIndexEntries: number;
}

type GraphRebuildSnapshotCpuCounter = 'snapshotSemanticIndexBuilds'
    | 'snapshotSemanticIndexEntries'
    | 'snapshotSemanticAvoidedIndexBuilds'
    | 'snapshotSemanticAvoidedIndexEntries';
export type GraphRebuildSnapshotCpuPhase = Exclude<keyof GraphRebuildSnapshotCpuProfile, GraphRebuildSnapshotCpuCounter>;

export class GraphRebuildCpuProfiler {
    private lastMark = 0;

    readonly timings: GraphRebuildSnapshotCpuProfile = {
        snapshotAnchorsMs: 0,
        snapshotFactsMs: 0,
        snapshotCompatibilityViewsMs: 0,
        snapshotTargetsMs: 0,
        snapshotPostProcessMs: 0,
        snapshotEmbeddingPostProcessMs: 0,
        snapshotEmbeddingSignaturesMs: 0,
        snapshotEmbeddingPairPlanMs: 0,
        snapshotEmbeddingNeighborsMs: 0,
        snapshotEmbeddingClustersMs: 0,
        snapshotEmbeddingRowsEdgesMs: 0,
        snapshotGraphAwareLinksMs: 0,
        snapshotEntityLinkingMs: 0,
        snapshotAssemblyMs: 0,
        snapshotSemanticTasksMs: 0,
        snapshotSemanticCandidatesMs: 0,
        snapshotManifoldSpecializationMs: 0,
        snapshotSemanticRerankMs: 0,
        snapshotSemanticAdjudicationMs: 0,
        snapshotSemanticEvalLedgerMs: 0,
        snapshotSemanticLedgersMs: 0,
        snapshotSemanticIndexBuilds: 0,
        snapshotSemanticIndexEntries: 0,
        snapshotSemanticAvoidedIndexBuilds: 0,
        snapshotSemanticAvoidedIndexEntries: 0,
    };

    begin(): void {
        this.lastMark = performance.now();
    }

    checkpoint(): void {
        this.lastMark = performance.now();
    }

    mark(phase: GraphRebuildSnapshotCpuPhase): void {
        const now = performance.now();
        this.timings[phase] += Math.max(0, now - this.lastMark);
        this.lastMark = now;
    }

    add(phase: GraphRebuildSnapshotCpuPhase, startedAt: number): void {
        this.timings[phase] += Math.max(0, performance.now() - startedAt);
    }

    setSemanticIndexStats(stats: { builds: number; entries: number; avoidedBuilds: number; avoidedEntries: number }): void {
        this.timings.snapshotSemanticIndexBuilds = stats.builds;
        this.timings.snapshotSemanticIndexEntries = stats.entries;
        this.timings.snapshotSemanticAvoidedIndexBuilds = stats.avoidedBuilds;
        this.timings.snapshotSemanticAvoidedIndexEntries = stats.avoidedEntries;
    }
}
