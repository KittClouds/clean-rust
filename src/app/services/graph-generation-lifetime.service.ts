import { Injectable, computed, signal } from '@angular/core';

import {
    assertGraphGenerationReceipt,
    type GraphGenerationReceiptV2,
} from '../graph-rebuild/graph-generation-receipt';
import {
    releaseGraphCanvasInventoryGeneration,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-canvas-inventory';
import {
    releaseGalaxySceneCompilerGeneration,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-compiler';
import {
    releaseGraphRebuildEmbeddingAtlasGeneration,
} from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-rebuild-embedding-atlas';
import { GraphCanvasColdStartService } from './graph-canvas-cold-start.service';
import { GraphRetrievalFusionService } from './graph-retrieval-fusion.service';
import type { GraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-snapshot';

export interface GraphGenerationReleaseResult {
    receiptId: string;
    snapshotId: string;
    released: boolean;
    projectionCache: boolean;
    inventoryCache: boolean;
    expandedScenes: number;
    prewarmWorker: boolean;
    retrievalRuntime: boolean;
}

@Injectable({ providedIn: 'root' })
export class GraphGenerationLifetimeService {
    private readonly currentState = signal<GraphGenerationReceiptV2 | null>(null);
    private readonly lastReleaseState = signal<GraphGenerationReleaseResult | null>(null);
    private readonly releasedShellState = signal<GraphRebuildSnapshot | null>(null);

    readonly current = computed(() => this.currentState());
    readonly lastRelease = computed(() => this.lastReleaseState());
    readonly releasedShell = computed(() => this.releasedShellState());

    constructor(
        private readonly coldStart: GraphCanvasColdStartService,
        private readonly retrieval: GraphRetrievalFusionService,
    ) {}

    async accept(receipt: GraphGenerationReceiptV2): Promise<void> {
        await assertGraphGenerationReceipt(receipt);
        const previous = this.currentState();
        this.currentState.set(receipt);
        if (previous && previous.receiptId !== receipt.receiptId) {
            this.releasedShellState.set(null);
        }
    }

    async releaseRichGeneration(
        receipt: GraphGenerationReceiptV2,
        shell: GraphRebuildSnapshot,
        releaseRichRoots: () => void,
    ): Promise<GraphGenerationReleaseResult> {
        await assertGraphGenerationReceipt(receipt);
        if (!receipt.releaseAuthorized) {
            throw new Error(`Graph generation ${receipt.receiptId} is not release-authorized.`);
        }
        if (this.currentState()?.receiptId !== receipt.receiptId) {
            throw new Error(`Graph generation ${receipt.receiptId} is not the current generation.`);
        }
        if (shell.generationReceiptId !== receipt.receiptId
            || shell.generationDigestSha256 !== receipt.digestSha256
            || shell.id !== receipt.snapshotId
            || shell.scopeId !== receipt.scopeId) {
            throw new Error(`Graph generation ${receipt.receiptId} compact shell is not receipt-bound.`);
        }
        releaseRichRoots();
        this.releasedShellState.set(shell);
        const result = this.releaseDerivedState(receipt);
        const released = { ...result, released: true };
        this.lastReleaseState.set(released);
        return released;
    }

    private releaseDerivedState(receipt: GraphGenerationReceiptV2): GraphGenerationReleaseResult {
        const renderIdentity = graphGenerationRenderIdentity(receipt);
        const result: GraphGenerationReleaseResult = {
            receiptId: receipt.receiptId,
            snapshotId: receipt.snapshotId,
            released: false,
            projectionCache: releaseGraphRebuildEmbeddingAtlasGeneration(renderIdentity),
            inventoryCache: releaseGraphCanvasInventoryGeneration(renderIdentity),
            expandedScenes: releaseGalaxySceneCompilerGeneration(receipt.authority.contentHash),
            prewarmWorker: this.coldStart.releaseGeneration(receipt.authority.contentHash),
            retrievalRuntime: this.retrieval.evict(receipt.snapshotId),
        };
        this.lastReleaseState.set(result);
        return result;
    }
}

export function graphGenerationRenderIdentity(receipt: GraphGenerationReceiptV2): string {
    return `${receipt.scopeId}\u0000${receipt.snapshotId}\u0000${receipt.authority.contentHash}`;
}
