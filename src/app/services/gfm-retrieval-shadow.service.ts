import { Injectable, Injector, inject, signal } from '@angular/core';

import { GraphRebuildService } from '../graph-rebuild/graph-rebuild.service';
import {
    PhoenixBackendService,
    type PhoenixGfmShadowReceipt,
} from './phoenix-backend.service';

const MAX_SHADOW_RESULTS = 50;

@Injectable({ providedIn: 'root' })
export class GfmRetrievalShadowService {
    private readonly phoenix = inject(PhoenixBackendService);
    private readonly injector = inject(Injector);
    private readonly receiptState = signal<PhoenixGfmShadowReceipt | null>(null);
    private readonly failureState = signal<string | null>(null);
    private generation = 0;

    readonly lastReceipt = this.receiptState.asReadonly();
    readonly lastFailure = this.failureState.asReadonly();

    async observe(
        query: string,
        semanticDocumentIds: readonly string[],
        limit: number,
    ): Promise<void> {
        const requestGeneration = ++this.generation;
        this.receiptState.set(null);
        this.failureState.set(null);
        const runHandle = this.injector
            .get(GraphRebuildService)
            .residentNativeGraphRunHandle();
        if (this.phoenix.target !== 'native' || !runHandle || !query.trim()) {
            return;
        }
        try {
            const receipt = await this.phoenix.queryGfmShadow({
                runHandle,
                query,
                requestGeneration,
                semanticDocumentIds: [...new Set(semanticDocumentIds)],
                limit: Math.max(1, Math.min(MAX_SHADOW_RESULTS, Math.trunc(limit))),
            });
            if (requestGeneration !== this.generation) return;
            if (!receipt.noTopologyWrites || !receipt.visibleRankingUnchanged) {
                this.failureState.set('GFM shadow authority shield rejected the receipt.');
                return;
            }
            this.receiptState.set(receipt);
        } catch (error) {
            if (requestGeneration !== this.generation) return;
            this.failureState.set(error instanceof Error ? error.message : String(error));
        }
    }
}
