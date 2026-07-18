import '@angular/compiler';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NliWorkerService } from './nli-worker.service';

type WorkerReplyMode = 'ack' | 'error' | 'silent';

class NliWorkerHarness {
    static instances: NliWorkerHarness[] = [];

    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: ((event: ErrorEvent) => void) | null = null;
    onmessageerror: ((event: MessageEvent) => void) | null = null;
    readonly postMessage = vi.fn((message: { type: string; _id: number }) => this.reply(message));
    readonly terminate = vi.fn();
    disposeMode: WorkerReplyMode = 'ack';
    classifyMode: WorkerReplyMode = 'ack';

    constructor() {
        NliWorkerHarness.instances.push(this);
    }

    emitError(error: Error): void {
        this.onerror?.({ type: 'error', error, message: error.message } as ErrorEvent);
    }

    private reply(message: { type: string; _id: number }): void {
        if (message.type === 'INIT') {
            queueMicrotask(() => this.emit('INIT_COMPLETE', message._id, { device: 'wasm' }));
            return;
        }
        if (message.type === 'CLASSIFY_STREAM') {
            if (this.classifyMode === 'ack') {
                queueMicrotask(() => this.emit('CLASSIFY_COMPLETE', message._id));
            } else if (this.classifyMode === 'error') {
                queueMicrotask(() => this.emit('ERROR', message._id, { message: 'classification failed' }));
            }
            return;
        }
        if (message.type === 'DISPOSE') {
            if (this.disposeMode === 'ack') {
                queueMicrotask(() => this.emit('DISPOSED', message._id));
            } else if (this.disposeMode === 'error') {
                queueMicrotask(() => this.emit('ERROR', message._id, { message: 'dispose failed' }));
            }
        }
    }

    private emit(type: string, id: number, payload?: unknown): void {
        this.onmessage?.({ data: { type, payload, _id: id } } as MessageEvent);
    }
}

describe('NliWorkerService lifecycle', () => {
    let originalWorker: typeof Worker | undefined;

    beforeEach(() => {
        originalWorker = globalThis.Worker;
        NliWorkerHarness.instances = [];
        Object.defineProperty(globalThis, 'Worker', {
            configurable: true,
            writable: true,
            value: NliWorkerHarness,
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
        Object.defineProperty(globalThis, 'Worker', {
            configurable: true,
            writable: true,
            value: originalWorker,
        });
    });

    it('releases an acknowledged worker and resets every residency signal', async () => {
        const service = new NliWorkerService();
        await service.initialize('test-nli');
        const worker = NliWorkerHarness.instances[0];

        expect(service.residencySnapshot()).toEqual({
            resident: true,
            initialized: true,
            disposing: false,
            pendingRequests: 0,
        });

        await service.dispose();

        expect(worker.terminate).toHaveBeenCalledTimes(1);
        expect(service.residencySnapshot()).toEqual({
            resident: false,
            initialized: false,
            disposing: false,
            pendingRequests: 0,
        });
        expect(service.modelId()).toBeNull();
        expect(service.device()).toBe('wasm');
        expect(service.progress()).toBeNull();
    });

    it('forces termination when the worker rejects disposal', async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        const service = new NliWorkerService();
        await service.initialize('test-nli');
        const worker = NliWorkerHarness.instances[0];
        worker.disposeMode = 'error';

        await expect(service.dispose()).resolves.toBeUndefined();

        expect(worker.terminate).toHaveBeenCalledTimes(1);
        expect(service.residencySnapshot().resident).toBe(false);
        expect(service.residencySnapshot().pendingRequests).toBe(0);
    });

    it('bounds a silent disposal and still terminates the worker', async () => {
        vi.useFakeTimers();
        vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        const service = new NliWorkerService();
        await service.initialize('test-nli');
        const worker = NliWorkerHarness.instances[0];
        worker.disposeMode = 'silent';

        const disposal = service.dispose();
        await vi.advanceTimersByTimeAsync(1_500);
        await disposal;

        expect(worker.terminate).toHaveBeenCalledTimes(1);
        expect(service.residencySnapshot()).toEqual({
            resident: false,
            initialized: false,
            disposing: false,
            pendingRequests: 0,
        });
    });

    it('releases the ephemeral session when classification fails', async () => {
        const service = new NliWorkerService();

        await expect(service.withEphemeralSession('test-nli', async () => {
            const worker = NliWorkerHarness.instances[0];
            worker.classifyMode = 'error';
            await service.classifyStream([], () => undefined);
        })).rejects.toThrow('classification failed');

        expect(NliWorkerHarness.instances[0].terminate).toHaveBeenCalledTimes(1);
        expect(service.isProcessing()).toBe(false);
        expect(service.residencySnapshot().resident).toBe(false);
    });

    it('fails closed when the active worker reports an error', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const service = new NliWorkerService();
        await service.initialize('test-nli');
        const worker = NliWorkerHarness.instances[0];

        worker.emitError(new Error('worker crashed'));

        expect(worker.terminate).toHaveBeenCalledTimes(1);
        expect(service.isReady()).toBe(false);
        expect(service.residencySnapshot().resident).toBe(false);
    });

    it('does not retain either worker across consecutive sessions', async () => {
        const service = new NliWorkerService();

        await service.withEphemeralSession('test-nli', async () => undefined);
        await service.withEphemeralSession('test-nli', async () => undefined);

        expect(NliWorkerHarness.instances).toHaveLength(2);
        expect(NliWorkerHarness.instances.every((worker) => worker.terminate.mock.calls.length === 1)).toBe(true);
        expect(service.residencySnapshot().resident).toBe(false);
    });
});
