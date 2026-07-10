import { Injectable, computed, inject, signal } from '@angular/core';

import {
    buildAtlasControlContract,
    type AtlasControlContract,
} from '../graph-rebuild/atlas-control-contract';
import {
    buildReviewAdjudicationRunCertificate,
    buildReviewAdjudicationViewContract,
    type GraphReviewAdjudicationEntrypoint,
    type GraphReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationViewContract,
} from '../graph-rebuild/graph-review-adjudication-certificate';
import { GraphRebuildService } from '../graph-rebuild/graph-rebuild.service';
import { NliWorkerService } from '../lib/services/nli-worker.service';
import { PhoenixProjectionService } from './phoenix-projection.service';

export type AtlasControlNliOperationState = 'idle' | 'loading' | 'running';

@Injectable({ providedIn: 'root' })
export class AtlasControlContractService {
    private readonly graphRebuild = inject(GraphRebuildService);
    private readonly projection = inject(PhoenixProjectionService);
    private readonly nli = inject(NliWorkerService);
    private readonly nliOperationState = signal<AtlasControlNliOperationState>('idle');

    readonly snapshot = this.graphRebuild.snapshot;
    readonly nliState = computed<AtlasControlNliOperationState>(() => {
        const explicit = this.nliOperationState();
        if (explicit !== 'idle') return explicit;
        if (this.nli.isProcessing()) return 'running';
        const progress = this.nli.progress();
        return progress?.type === 'init' && !this.nli.isInitialized() ? 'loading' : 'idle';
    });
    readonly nliRunning = computed(() => this.nliState() === 'running');
    readonly nliLoading = computed(() => this.nliState() === 'loading');

    readonly reviewCertificate = computed<GraphReviewAdjudicationRunCertificate | null>(() => {
        const snapshot = this.snapshot();
        if (!snapshot) return null;
        return snapshot.reviewAdjudicationCertificate ?? buildReviewAdjudicationRunCertificate({
            snapshot,
            source: 'derived',
            modelId: this.nli.modelId() || 'onnx-community/ModernBERT-base-nli',
            modelLabel: 'ModernBERT NLI',
        });
    });

    readonly reviewView = computed<GraphReviewAdjudicationViewContract>(() =>
        buildReviewAdjudicationViewContract(this.reviewCertificate(), {
            modelInitialized: this.nli.isInitialized(),
            running: this.nliRunning(),
            loading: this.nliLoading(),
            busy: this.graphRebuild.isBuilding(),
            hasScope: !!this.snapshot(),
        }),
    );

    readonly contract = computed<AtlasControlContract>(() => buildAtlasControlContract({
        snapshot: this.snapshot(),
        entities: this.projection.entities(),
        entityCount: this.projection.entityCount(),
        reviewAdjudicationCertificate: this.reviewCertificate(),
        reviewAdjudicationViewContract: this.reviewView(),
    }));

    setNliOperationState(state: AtlasControlNliOperationState): void {
        this.nliOperationState.set(state);
    }

    publishReviewRun(
        rawResult: unknown,
        source: GraphReviewAdjudicationEntrypoint = 'manual_stage8',
    ): GraphReviewAdjudicationRunCertificate {
        const certificate = buildReviewAdjudicationRunCertificate({
            snapshot: this.snapshot(),
            rawResult,
            source,
            modelId: this.nli.modelId() || 'onnx-community/ModernBERT-base-nli',
            modelLabel: 'ModernBERT NLI',
        });
        this.graphRebuild.attachReviewAdjudicationCertificate(certificate);
        return certificate;
    }
}
