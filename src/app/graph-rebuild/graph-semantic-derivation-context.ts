import type {
    GraphManifoldCandidateContribution,
    GraphRebuildEmbeddingTargetPostProcess,
    GraphRebuildSnapshot,
    GraphSemanticRerankJudgment,
} from './graph-rebuild-snapshot';

export interface GraphSemanticDerivationIndexStats {
    builds: number;
    entries: number;
    avoidedBuilds: number;
    avoidedEntries: number;
}

type IndexName = 'targets' | 'eventChunks' | 'anchorEntities' | 'anchorNotes'
    | 'nodeEntities' | 'contributions' | 'judgments';

interface IndexUsage {
    entries: number;
    consumers: number;
}

export class GraphSemanticDerivationContext {
    private readonly targets: Map<string, GraphRebuildEmbeddingTargetPostProcess>;
    private readonly eventChunks: Set<string>;
    private readonly anchorEntities = new Map<string, string>();
    private readonly anchorNotes = new Map<string, string>();
    private readonly nodeEntities: string[];
    private contributions = new Map<string, GraphManifoldCandidateContribution>();
    private judgments = new Map<string, GraphSemanticRerankJudgment>();
    private readonly usage = new Map<IndexName, IndexUsage>();

    constructor(snapshot: GraphRebuildSnapshot) {
        this.targets = new Map(
            (snapshot.embeddingGraphPostProcess?.targets || []).map((row) => [row.targetId, row]),
        );
        this.eventChunks = new Set(
            snapshot.events.map((event) => event.chunkId).filter((id): id is string => Boolean(id)),
        );
        for (const anchor of snapshot.entityAnchors) {
            this.anchorEntities.set(anchor.id, anchor.entityId);
            this.anchorNotes.set(anchor.id, anchor.noteId);
        }
        this.nodeEntities = snapshot.nodes.map((node) => node.entityId);
        this.register('targets', this.targets.size);
        this.register('eventChunks', this.eventChunks.size);
        this.register('anchorEntities', this.anchorEntities.size);
        this.register('anchorNotes', this.anchorNotes.size);
        this.register('nodeEntities', this.nodeEntities.length);
    }

    targetRows(): ReadonlyMap<string, GraphRebuildEmbeddingTargetPostProcess> {
        this.consume('targets');
        return this.targets;
    }

    eventChunkIds(): ReadonlySet<string> {
        this.consume('eventChunks');
        return this.eventChunks;
    }

    anchorEntityIds(): ReadonlyMap<string, string> {
        this.consume('anchorEntities');
        return this.anchorEntities;
    }

    anchorNoteIds(): ReadonlyMap<string, string> {
        this.consume('anchorNotes');
        return this.anchorNotes;
    }

    nodeEntityIds(): readonly string[] {
        this.consume('nodeEntities');
        return this.nodeEntities;
    }

    indexContributions(rows: GraphManifoldCandidateContribution[]): void {
        this.contributions = new Map(rows.map((row) => [row.id, row]));
        this.register('contributions', this.contributions.size);
    }

    contributionRows(): ReadonlyMap<string, GraphManifoldCandidateContribution> {
        this.consume('contributions');
        return this.contributions;
    }

    indexJudgments(rows: GraphSemanticRerankJudgment[]): void {
        this.judgments = new Map(rows.map((row) => [row.candidateId, row]));
        this.register('judgments', this.judgments.size);
    }

    judgmentRows(): ReadonlyMap<string, GraphSemanticRerankJudgment> {
        this.consume('judgments');
        return this.judgments;
    }

    stats(): GraphSemanticDerivationIndexStats {
        let entries = 0;
        let avoidedBuilds = 0;
        let avoidedEntries = 0;
        for (const usage of this.usage.values()) {
            entries += usage.entries;
            const avoided = Math.max(0, usage.consumers - 1);
            avoidedBuilds += avoided;
            avoidedEntries += avoided * usage.entries;
        }
        return { builds: this.usage.size, entries, avoidedBuilds, avoidedEntries };
    }

    private register(name: IndexName, entries: number): void {
        this.usage.set(name, { entries, consumers: 0 });
    }

    private consume(name: IndexName): void {
        const usage = this.usage.get(name);
        if (usage) usage.consumers += 1;
    }
}
