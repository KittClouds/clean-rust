import { Injectable, NgZone, computed, signal } from '@angular/core';

import { createNoopNgZone, createWorkerOutsideAngular } from '../core/worker-zone';
import type { PhoenixNliCanonicalLabel } from '../nli/nli-utils';

export interface NliProgress {
    type: 'init' | 'batch' | 'complete';
    current: number;
    total: number;
    message: string;
}

export interface NliPairClassificationInput {
    judgmentId: string;
    groupId: string;
    sourceId: string;
    targetId: string;
    edgeType: string;
    direction: string;
    premise: string;
    hypothesis: string;
}

export interface NliClassificationResult extends NliPairClassificationInput {
    entailment: number;
    neutral: number;
    contradiction: number;
    predictedLabel: PhoenixNliCanonicalLabel;
    confidence: number;
}

export interface NliBatch {
    results: NliClassificationResult[];
    batchIndex: number;
    totalBatches: number;
}

export type NliProgressCallback = (progress: NliProgress) => void;
export type NliBatchCallback = (batch: NliBatch) => void;

const NLI_DISPOSE_TIMEOUT_MS = 1_500;

type PendingNliCallback = {
    resolve: (value?: any) => void;
    reject: (reason?: unknown) => void;
    onProgress?: NliProgressCallback;
    onBatch?: NliBatchCallback;
};

@Injectable({ providedIn: 'root' })
export class NliWorkerService {
    private worker: Worker | null = null;
    private pendingCallbacks = new Map<number, PendingNliCallback>();
    private disposal: Promise<void> | null = null;
    private callbackId = 0;

    readonly isInitialized = signal(false);
    readonly modelId = signal<string | null>(null);
    readonly device = signal<string>('wasm');
    readonly isProcessing = signal(false);
    readonly isDisposing = signal(false);
    readonly progress = signal<NliProgress | null>(null);

    readonly isReady = computed(() => this.isInitialized() && !this.isProcessing() && !this.isDisposing());

    constructor(private readonly ngZone: NgZone = createNoopNgZone()) {}

    async initialize(modelId: string, onProgress?: NliProgressCallback): Promise<void> {
        if (this.disposal) {
            await this.disposal;
        }
        if (this.isInitialized() && this.modelId() === modelId) {
            return;
        }

        if (this.worker) {
            await this.dispose();
        }

        this.progress.set({ type: 'init', current: 0, total: 100, message: 'Starting...' });
        onProgress?.({ type: 'init', current: 0, total: 100, message: 'Starting...' });

        this.worker = createWorkerOutsideAngular(
            this.ngZone,
            () =>
                new Worker(new URL('../../workers/nli.worker', import.meta.url), {
                    type: 'module',
                }),
            (worker) => {
                worker.onmessage = (event) => this.handleWorkerMessage(event);
                worker.onerror = (event) => {
                    this.ngZone.run(() => {
                        const error = this.formatWorkerError(event);
                        console.error('[NliWorkerService] Worker error:', error);
                        this.failWorker(worker, error);
                    });
                };
                worker.onmessageerror = (event) => {
                    this.ngZone.run(() => {
                        const error = new Error(`NLI worker message error: ${String(event.data)}`);
                        console.error('[NliWorkerService] Worker message error:', error);
                        this.failWorker(worker, error);
                    });
                };
            },
        );

        const id = this.nextId();
        const promise = new Promise<void>((resolve, reject) => {
            this.pendingCallbacks.set(id, {
                resolve: (payload?: { device?: string }) => {
                    this.isInitialized.set(true);
                    this.modelId.set(modelId);
                    if (payload?.device) {
                        this.device.set(payload.device);
                    }
                    resolve();
                },
                reject,
                onProgress,
            });
        });

        try {
            this.worker.postMessage({
                type: 'INIT',
                payload: { modelId },
                _id: id,
            });
        } catch (error) {
            this.pendingCallbacks.delete(id);
            this.failWorker(this.worker, asError(error));
            throw error;
        }

        return promise;
    }

    async classifyStream(
        pairs: NliPairClassificationInput[],
        onBatch: NliBatchCallback,
        batchSize = 4,
        onProgress?: NliProgressCallback,
    ): Promise<void> {
        if (!this.isReady()) {
            throw new Error('Worker not ready. Call initialize() first.');
        }

        this.isProcessing.set(true);
        this.progress.set({
            type: 'batch',
            current: 0,
            total: Math.ceil(pairs.length / batchSize),
            message: 'Starting...',
        });

        const id = this.nextId();
        const promise = new Promise<void>((resolve, reject) => {
            this.pendingCallbacks.set(id, { resolve, reject, onBatch, onProgress });
        });

        try {
            this.worker!.postMessage({
                type: 'CLASSIFY_STREAM',
                payload: { pairs, batchSize },
                _id: id,
            });
            await promise;
            this.isProcessing.set(false);
            this.progress.set({ type: 'complete', current: 1, total: 1, message: 'Complete' });
        } catch (error) {
            this.pendingCallbacks.delete(id);
            this.isProcessing.set(false);
            this.progress.set(null);
            throw error;
        }
    }

    async getStatus(): Promise<{ initialized: boolean; modelId: string | null; device: string }> {
        if (!this.worker) {
            return { initialized: false, modelId: null, device: 'wasm' };
        }

        const id = this.nextId();
        const promise = new Promise<{ initialized: boolean; modelId: string | null; device: string }>(
            (resolve, reject) => {
                this.pendingCallbacks.set(id, { resolve, reject });
            },
        );

        try {
            this.worker.postMessage({ type: 'GET_STATUS', _id: id });
        } catch (error) {
            this.pendingCallbacks.delete(id);
            throw error;
        }
        return promise;
    }

    async dispose(): Promise<void> {
        if (this.disposal) return this.disposal;
        const worker = this.worker;
        if (!worker) {
            this.resetWorkerState();
            return;
        }

        const disposal = this.disposeWorker(worker);
        this.disposal = disposal;
        try {
            await disposal;
        } finally {
            if (this.disposal === disposal) this.disposal = null;
        }
    }

    async withEphemeralSession<T>(modelId: string, task: () => Promise<T>): Promise<T> {
        try {
            await this.initialize(modelId);
            return await task();
        } finally {
            await this.dispose();
        }
    }

    residencySnapshot(): { resident: boolean; initialized: boolean; disposing: boolean; pendingRequests: number } {
        return {
            resident: this.worker !== null,
            initialized: this.isInitialized(),
            disposing: this.isDisposing(),
            pendingRequests: this.pendingCallbacks.size,
        };
    }

    private async disposeWorker(worker: Worker): Promise<void> {
        this.isDisposing.set(true);
        const id = this.nextId();
        let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
        const acknowledgement = new Promise<void>((resolve, reject) => {
            this.pendingCallbacks.set(id, { resolve, reject });
            timeoutHandle = setTimeout(
                () => reject(new Error(`NLI worker disposal exceeded ${NLI_DISPOSE_TIMEOUT_MS} ms`)),
                NLI_DISPOSE_TIMEOUT_MS,
            );
        });

        try {
            worker.postMessage({ type: 'DISPOSE', _id: id });
            await acknowledgement;
        } catch (error) {
            console.warn('[NliWorkerService] Forcing worker termination after disposal failure:', asError(error));
        } finally {
            if (timeoutHandle !== null) clearTimeout(timeoutHandle);
            this.pendingCallbacks.delete(id);
            this.rejectPending(new Error('NLI worker session closed'));
            worker.terminate();
            if (this.worker === worker) this.worker = null;
            this.resetWorkerState();
        }
    }

    private failWorker(worker: Worker, error: Error): void {
        this.rejectPending(error);
        worker.terminate();
        if (this.worker === worker) this.worker = null;
        this.resetWorkerState();
    }

    private resetWorkerState(): void {
        this.isInitialized.set(false);
        this.modelId.set(null);
        this.isProcessing.set(false);
        this.isDisposing.set(false);
        this.progress.set(null);
        this.device.set('wasm');
    }

    private nextId(): number {
        return ++this.callbackId;
    }

    private rejectPending(error: Error): void {
        for (const { reject } of this.pendingCallbacks.values()) {
            reject(error);
        }
        this.pendingCallbacks.clear();
        this.isProcessing.set(false);
    }

    private formatWorkerError(event: ErrorEvent | Event): Error {
        if ('error' in event && event.error instanceof Error) {
            return event.error;
        }
        if ('message' in event && typeof event.message === 'string' && event.message.length) {
            const location = [
                'filename' in event ? event.filename : '',
                'lineno' in event && event.lineno ? event.lineno : '',
                'colno' in event && event.colno ? event.colno : '',
            ].filter(Boolean).join(':');
            return new Error(location ? `${event.message} (${location})` : event.message);
        }
        return new Error(`NLI worker failed with ${event.type || 'unknown'} event`);
    }

    private handleWorkerMessage(event: MessageEvent): void {
        const { type, payload, _id } = event.data;

        if (type === 'init_progress' || type === 'classify_progress') {
            const progress: NliProgress = {
                type: type === 'init_progress' ? 'init' : 'batch',
                current: event.data.current,
                total: event.data.total,
                message: event.data.message,
            };
            this.progress.set(progress);
            if (_id !== undefined && this.pendingCallbacks.has(_id)) {
                const { onProgress } = this.pendingCallbacks.get(_id)!;
                onProgress?.(progress);
            }
            return;
        }

        if (type === 'CLASSIFY_BATCH') {
            if (_id !== undefined && this.pendingCallbacks.has(_id)) {
                const { onBatch, onProgress } = this.pendingCallbacks.get(_id)!;
                onBatch?.(payload);
                onProgress?.({
                    type: 'batch',
                    current: payload.batchIndex,
                    total: payload.totalBatches,
                    message: `Batch ${payload.batchIndex}/${payload.totalBatches}`,
                });
            }
            return;
        }

        if (type === 'CLASSIFY_COMPLETE') {
            if (_id !== undefined && this.pendingCallbacks.has(_id)) {
                const { resolve } = this.pendingCallbacks.get(_id)!;
                this.pendingCallbacks.delete(_id);
                resolve();
            }
            return;
        }

        if (type === 'STATUS') {
            if (_id !== undefined && this.pendingCallbacks.has(_id)) {
                const { resolve } = this.pendingCallbacks.get(_id)!;
                this.pendingCallbacks.delete(_id);
                this.ngZone.run(() => resolve(payload));
            }
            return;
        }

        if (_id !== undefined && this.pendingCallbacks.has(_id)) {
            const { resolve, reject } = this.pendingCallbacks.get(_id)!;
            this.pendingCallbacks.delete(_id);

            if (type === 'ERROR') {
                this.ngZone.run(() => reject(new Error(payload?.message || 'Worker error')));
                return;
            }

            if (type === 'INIT_COMPLETE') {
                this.ngZone.run(() => resolve(payload));
                return;
            }

            if (type === 'DISPOSED') {
                this.ngZone.run(() => resolve());
                return;
            }

            this.ngZone.run(() => resolve(payload));
        }
    }
}

function asError(value: unknown): Error {
    return value instanceof Error ? value : new Error(String(value));
}
