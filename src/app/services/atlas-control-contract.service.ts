import { Injectable, computed, inject, signal } from '@angular/core';

import {
    buildAtlasControlContract,
    type AtlasControlContract,
    type AtlasControlRow,
} from '../graph-rebuild/atlas-control-contract';
import { buildAtlasNativeProofRows } from '../graph-rebuild/atlas-control-rows';
import {
    buildReviewAdjudicationRunCertificate,
    buildReviewAdjudicationViewContract,
    type GraphReviewAdjudicationEntrypoint,
    type GraphReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationViewContract,
} from '../graph-rebuild/graph-review-adjudication-certificate';
import {
    GraphRebuildService,
    type NativeGraphRunPage,
} from '../graph-rebuild/graph-rebuild.service';
import { NliWorkerService } from '../lib/services/nli-worker.service';
import { PhoenixProjectionService } from './phoenix-projection.service';

export type AtlasControlNliOperationState = 'idle' | 'loading' | 'running';
export type AtlasProofPagingStatus = 'idle' | 'ready' | 'loading' | 'complete' | 'expired' | 'error';

export interface AtlasProofPagingState {
    runHandle: string | null;
    status: AtlasProofPagingStatus;
    loadedRows: number;
    totalRows: number;
    nextOffset: number | null;
    error: string | null;
}

const EMPTY_PAGING: AtlasProofPagingState = {
    runHandle: null,
    status: 'idle',
    loadedRows: 0,
    totalRows: 0,
    nextOffset: null,
    error: null,
};

@Injectable({ providedIn: 'root' })
export class AtlasControlContractService {
    private readonly graphRebuild = inject(GraphRebuildService);
    private readonly projection = inject(PhoenixProjectionService);
    private readonly nli = inject(NliWorkerService);
    private readonly nliOperationState = signal<AtlasControlNliOperationState>('idle');
    private readonly additionalProofRows = signal<{ runHandle: string; rows: AtlasControlRow[] } | null>(null);
    private readonly pagingState = signal<AtlasProofPagingState>(EMPTY_PAGING);
    private readonly releasedProofLeases = new Set<string>();
    private pagingToken = 0;

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
    readonly proofPaging = computed<AtlasProofPagingState>(() => {
        const native = this.graphRebuild.nativeGraphRunPaging();
        const local = this.pagingState();
        if (!native) return EMPTY_PAGING;
        if (local.runHandle === native.runHandle) return local;
        return {
            runHandle: native.runHandle,
            status: native.nextOffset == null ? 'complete' : 'ready',
            loadedRows: native.loadedRows,
            totalRows: native.totalRows,
            nextOffset: native.nextOffset,
            error: null,
        };
    });

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
        additionalRows: this.additionalRowsForCurrentRun(),
        nativeProofCounts: this.graphRebuild.nativeGraphRunPaging()?.counts ?? null,
    }));

    async loadNextProofPage(): Promise<void> {
        const native = this.graphRebuild.nativeGraphRunPaging();
        if (!native) return;
        const current = this.proofPaging();
        const offset = current.runHandle === native.runHandle
            ? current.nextOffset
            : native.nextOffset;
        if (offset == null || current.status === 'loading') return;
        const token = ++this.pagingToken;
        this.pagingState.set({
            runHandle: native.runHandle,
            status: 'loading',
            loadedRows: current.runHandle === native.runHandle ? current.loadedRows : native.loadedRows,
            totalRows: native.totalRows,
            nextOffset: offset,
            error: null,
        });
        try {
            const page = await this.graphRebuild.readNativeGraphRunPageForHandle(
                native.runHandle,
                offset,
                32,
            );
            if (token !== this.pagingToken
                || this.graphRebuild.nativeGraphRunPaging()?.runHandle !== native.runHandle) return;
            const rows = buildAtlasNativeProofRows(native.snapshotId, nativeProofProjection(page));
            const prior = this.additionalProofRows();
            const combined = prior?.runHandle === native.runHandle
                ? uniqueRows([...prior.rows, ...rows])
                : uniqueRows(rows);
            this.additionalProofRows.set({ runHandle: native.runHandle, rows: combined });
            this.pagingState.set({
                runHandle: native.runHandle,
                status: page.nextOffset == null ? 'complete' : 'ready',
                loadedRows: Math.min(native.totalRows, offset + page.returnedDetailRows),
                totalRows: native.totalRows,
                nextOffset: page.nextOffset ?? null,
                error: null,
            });
        } catch (error) {
            if (token !== this.pagingToken) return;
            const message = error instanceof Error ? error.message : String(error);
            this.pagingState.set({
                runHandle: native.runHandle,
                status: /closed|expired|unavailable/i.test(message) ? 'expired' : 'error',
                loadedRows: current.loadedRows,
                totalRows: native.totalRows,
                nextOffset: offset,
                error: message,
            });
        }
    }

    async releaseProofLease(): Promise<boolean> {
        const native = this.graphRebuild.nativeGraphRunPaging();
        this.pagingToken += 1;
        if (!native || this.releasedProofLeases.has(native.runHandle)) return false;
        this.releasedProofLeases.add(native.runHandle);
        return this.graphRebuild.releaseNativeGraphRunLease(native.runHandle);
    }

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

    private additionalRowsForCurrentRun(): AtlasControlRow[] {
        const native = this.graphRebuild.nativeGraphRunPaging();
        const loaded = this.additionalProofRows();
        return native && loaded?.runHandle === native.runHandle ? loaded.rows : [];
    }
}

function nativeProofProjection(page: NativeGraphRunPage) {
    return {
        bridge: {
            candidates: page.projection.bridge.candidates,
            crossDocumentCertificate: page.projection.bridge.crossDocumentCertificate,
        },
        continuity: { contract: page.projection.continuity.contract },
        governance: { candidates: page.projection.governance.candidates },
        promotion: { certificate: page.projection.promotion.certificate },
    };
}

function uniqueRows(rows: AtlasControlRow[]): AtlasControlRow[] {
    return [...new Map(rows.map((row) => [row.identity.id, row])).values()];
}
