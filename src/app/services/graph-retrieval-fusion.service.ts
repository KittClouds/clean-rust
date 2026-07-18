import { Injectable } from '@angular/core';

import type {
    GraphRetrievalFusionRequest,
    GraphRetrievalFusionResult,
} from '../graph-rebuild/graph-retrieval-contract';
import {
    buildGraphRetrievalFusionRuntime,
    type GraphRetrievalFusionRuntime,
    type GraphRetrievalVectorLaneInput,
} from '../graph-rebuild/graph-retrieval-fusion';
import type { GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';
import { GraphTargetVectorIndexService } from './graph-target-vector-index.service';

@Injectable({ providedIn: 'root' })
export class GraphRetrievalFusionService {
    private readonly runtimes = new Map<string, GraphRetrievalFusionRuntime>();

    constructor(private readonly vectors: GraphTargetVectorIndexService) {}

    evict(snapshotId: string): boolean {
        return this.runtimes.delete(snapshotId);
    }

    async retrieve(
        snapshot: GraphRebuildSnapshot,
        request: GraphRetrievalFusionRequest,
    ): Promise<GraphRetrievalFusionResult> {
        const runtime = this.runtime(snapshot);
        const vectorLane = await this.vectorLane(snapshot.id, request);
        return runtime.retrieve(request, vectorLane);
    }

    private runtime(snapshot: GraphRebuildSnapshot): GraphRetrievalFusionRuntime {
        let runtime = this.runtimes.get(snapshot.id);
        if (runtime) return runtime;
        runtime = buildGraphRetrievalFusionRuntime(snapshot);
        this.runtimes.set(snapshot.id, runtime);
        while (this.runtimes.size > 2) {
            const oldest = this.runtimes.keys().next().value as string | undefined;
            if (!oldest) break;
            this.runtimes.delete(oldest);
        }
        return runtime;
    }

    private async vectorLane(
        snapshotId: string,
        request: GraphRetrievalFusionRequest,
    ): Promise<GraphRetrievalVectorLaneInput> {
        const limit = boundedInt(request.vectorLimit, 32, 1, 128);
        const options = {
            limit,
            maxCandidates: boundedInt(request.vectorMaxCandidates, 128, limit, 2048),
        };
        try {
            const result = request.queryVector
                ? this.vectors.searchVector(snapshotId, request.queryVector, options)
                : await this.vectors.search(snapshotId, request.query, options);
            if (!result) {
                return {
                    available: false,
                    candidates: [],
                    evaluated: 0,
                    truncated: false,
                    reason: 'real encoder index is not resident',
                };
            }
            return {
                available: true,
                candidates: result.neighbors,
                evaluated: result.evaluatedCandidates,
                truncated: result.truncated,
            };
        } catch (error) {
            return {
                available: false,
                candidates: [],
                evaluated: 0,
                truncated: false,
                reason: error instanceof Error ? error.message : String(error),
            };
        }
    }
}

function boundedInt(value: number | undefined, fallback: number, min: number, max: number): number {
    const normalized = Number.isFinite(value) ? Math.floor(value as number) : fallback;
    return Math.max(min, Math.min(max, normalized));
}
