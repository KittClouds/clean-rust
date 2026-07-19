import { Injectable } from '@angular/core';

import {
    buildGraphEncoderVectorIndex,
    installGraphEncoderVectorIndex,
    type GraphEncoderVectorIndex,
    type GraphEncoderVectorIndexOptions,
    type GraphEncoderVectorQueryOptions,
    type GraphEncoderVectorQueryResult,
} from '../graph-rebuild/graph-encoder-vector-index';
import {
    buildNativeGraphEncoderNeighborhoods,
    nativeGraphEncoderIndexAvailable,
    type NativeGraphEncoderNeighborhoodBuild,
} from '../graph-rebuild/graph-encoder-vector-index-native';
import { assertGraphEvidenceTargetRegistry } from '../graph-rebuild/graph-evidence-target-registry';
import { embeddingTargetText } from '../graph-rebuild/graph-rebuild-embedding-signatures';
import type { GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';
import { sealGraphSnapshotAuthority } from '../graph-rebuild/graph-snapshot-authority';
import { EmbeddingModelRegistry } from '../lib/embeddings/models/ModelRegistry';
import { EmbeddingWorkerService } from '../lib/services/embedding-worker.service';

export interface GraphTargetVectorIndexBuildOptions extends GraphEncoderVectorIndexOptions {
    modelId: string;
    modelVersion?: string;
    batchSize?: number;
    generation?: number;
}

@Injectable({ providedIn: 'root' })
export class GraphTargetVectorIndexService {
    private readonly indexes = new Map<string, GraphEncoderVectorIndex>();
    private readonly nativeBuildReceipts = new Map<
        string,
        NativeGraphEncoderNeighborhoodBuild['receipt']
    >();

    constructor(private readonly encoder: EmbeddingWorkerService) {}

    get(snapshotId: string): GraphEncoderVectorIndex | undefined {
        return this.indexes.get(snapshotId);
    }

    nativeBuildReceipt(
        snapshotId: string,
    ): NativeGraphEncoderNeighborhoodBuild['receipt'] | undefined {
        return this.nativeBuildReceipts.get(snapshotId);
    }

    evict(snapshotId: string): boolean {
        this.nativeBuildReceipts.delete(snapshotId);
        return this.indexes.delete(snapshotId);
    }

    searchVector(
        snapshotId: string,
        vector: Float32Array,
        options: GraphEncoderVectorQueryOptions = {},
    ): GraphEncoderVectorQueryResult | undefined {
        return this.indexes.get(snapshotId)?.query(vector, options);
    }

    async search(
        snapshotId: string,
        query: string,
        options: GraphEncoderVectorQueryOptions = {},
    ): Promise<GraphEncoderVectorQueryResult | undefined> {
        const index = this.indexes.get(snapshotId);
        if (!index) return undefined;
        if (index.contract.executionProvider !== 'transformers-worker') {
            throw new Error(`Text query encoder is unavailable for ${index.contract.executionProvider}`);
        }
        await this.encoder.initialize(index.contract.modelId);
        const encoded = await this.encoder.embedFlat([query], 1);
        if (encoded.rows !== 1 || encoded.dims !== index.contract.dimensions) {
            throw new Error(
                `Encoder query shape drift: got ${encoded.rows}x${encoded.dims}, `
                + `expected 1x${index.contract.dimensions}`,
            );
        }
        return index.query(encoded.values, options);
    }

    async build(
        snapshot: GraphRebuildSnapshot,
        options: GraphTargetVectorIndexBuildOptions,
    ): Promise<GraphEncoderVectorIndex> {
        const registry = assertGraphEvidenceTargetRegistry(snapshot);
        const model = EmbeddingModelRegistry.getModel(options.modelId);
        if (!model?.localModel) throw new Error(`Real encoder model is unavailable: ${options.modelId}`);
        const targets = registry.exposedTargets;
        let values: Float32Array = new Float32Array(0);
        let dimensions = model.dimensions;
        if (targets.length) {
            await this.encoder.initialize(options.modelId);
            const encoded = await this.encoder.embedFlat(
                targets.map(embeddingTargetText),
                boundedBatchSize(options.batchSize),
            );
            if (encoded.rows !== targets.length) {
                throw new Error(`Real encoder row count drift: got ${encoded.rows}, expected ${targets.length}`);
            }
            if (encoded.dims !== model.dimensions) {
                throw new Error(`Real encoder dimension drift: got ${encoded.dims}, expected ${model.dimensions}`);
            }
            values = encoded.values;
            dimensions = encoded.dims;
        }
        const page = {
            modelId: model.id,
            modelVersion: options.modelVersion || model.localModel.modelId,
            executionProvider: 'transformers-worker',
            dimensions,
            generation: options.generation ?? snapshot.builtAt,
            targetIds: targets.map((target) => target.id),
            values,
            normalized: true,
        } as const;
        let nativeBuild: NativeGraphEncoderNeighborhoodBuild | undefined;
        if (targets.length && nativeGraphEncoderIndexAvailable()) {
            try {
                nativeBuild = await buildNativeGraphEncoderNeighborhoods(page, options);
            } catch (error) {
                console.debug('[GraphTargetVectorIndex] Packed native build fell back to deterministic TS', error);
            }
        }
        let index: GraphEncoderVectorIndex;
        try {
            index = buildGraphEncoderVectorIndex(snapshot, page, options, nativeBuild);
        } catch (error) {
            if (!nativeBuild) throw error;
            console.debug('[GraphTargetVectorIndex] Native receipt failed validation; rebuilding in TS', error);
            nativeBuild = undefined;
            index = buildGraphEncoderVectorIndex(snapshot, page, options);
        }
        installGraphEncoderVectorIndex(snapshot, index);
        this.indexes.delete(snapshot.id);
        this.nativeBuildReceipts.delete(snapshot.id);
        this.indexes.set(snapshot.id, index);
        if (nativeBuild) this.nativeBuildReceipts.set(snapshot.id, nativeBuild.receipt);
        while (this.indexes.size > 2) {
            const oldest = this.indexes.keys().next().value as string | undefined;
            if (!oldest) break;
            this.indexes.delete(oldest);
            this.nativeBuildReceipts.delete(oldest);
        }
        if (snapshot.authorityContract) sealGraphSnapshotAuthority(snapshot);
        return index;
    }
}

function boundedBatchSize(value: number | undefined): number {
    if (!Number.isFinite(value)) return 16;
    return Math.max(1, Math.min(128, Math.floor(value as number)));
}
