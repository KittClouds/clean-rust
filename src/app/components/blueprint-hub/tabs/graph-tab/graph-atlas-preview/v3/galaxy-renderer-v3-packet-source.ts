import { DEFAULT_GRAPH_NODE_COLORS, entityColorStore } from '../../../../../../lib/store/entityColorStore';
import type { GalaxyInputEdge, GalaxyRenderableNode, GalaxyRenderSettings } from '../graph-galaxy-engine';
import type { GalaxyScenePacketV2 } from '../graph-galaxy-scene-packet-v2.model';
import {
    cachedGalaxyScenePacket,
    seedGalaxyScenePacket,
    subscribeGalaxyScenePacket,
} from '../graph-galaxy-scene-packet-registry';
import type { GalaxySceneSourceMode } from '../graph-galaxy-scene-v2';

interface PendingPacket {
    resolve: (packet: GalaxyScenePacketV2) => void;
    reject: (error: Error) => void;
    request: GalaxyRendererV3PacketCompileRequest;
}

export interface GalaxyRendererV3PacketCompileRequest {
    entities: GalaxyRenderableNode[];
    edges: GalaxyInputEdge[];
    settings: GalaxyRenderSettings;
    sourceMode: GalaxySceneSourceMode;
    generationId: string;
    authorityReceipt: string;
}

export class GalaxyRendererV3PacketSource {
    private worker: Worker | null = null;
    private nextRequestId = 0;
    private readonly pending = new Map<number, PendingPacket>();
    private residentUnsubscribe: (() => void) | null = null;

    resident(
        authorityReceipt: string,
        generationId: string,
        sourceMode: GalaxySceneSourceMode,
    ): GalaxyScenePacketV2 | null {
        return cachedGalaxyScenePacket(authorityReceipt, generationId, sourceMode);
    }

    waitForResident(
        authorityReceipt: string,
        generationId: string,
        sourceMode: GalaxySceneSourceMode,
        ready: () => void,
    ): void {
        this.cancelResidentWait();
        if (this.resident(authorityReceipt, generationId, sourceMode)) {
            queueMicrotask(ready);
            return;
        }
        this.residentUnsubscribe = subscribeGalaxyScenePacket(authorityReceipt, (packet) => {
            const manifest = packet.manifest;
            if (manifest.generationId !== generationId || manifest.sourceMode !== sourceMode) return;
            this.cancelResidentWait();
            ready();
        });
    }

    compile(request: GalaxyRendererV3PacketCompileRequest): Promise<GalaxyScenePacketV2> {
        const resident = this.resident(
            request.authorityReceipt,
            request.generationId,
            request.sourceMode,
        );
        if (resident) return Promise.resolve(resident);
        this.cancelActive(new Error('Galaxy Renderer V3 packet compilation superseded by newer input.'));
        const worker = this.requireWorker();
        const id = ++this.nextRequestId;
        const graphNodeColors = Object.fromEntries(
            Object.keys(DEFAULT_GRAPH_NODE_COLORS)
                .map((kind) => [kind, entityColorStore.getRawGraphNodeHsl(kind)]),
        );
        return new Promise<GalaxyScenePacketV2>((resolve, reject) => {
            this.pending.set(id, { resolve, reject, request });
            worker.postMessage({
                id,
                entities: request.entities,
                edges: request.edges,
                settings: request.settings,
                entityColors: entityColorStore.getSnapshot(),
                graphNodeColors,
                sourceMode: request.sourceMode,
                packetContext: {
                    generationId: request.generationId,
                    authorityReceipt: request.authorityReceipt,
                },
            });
        });
    }

    dispose(): void {
        this.cancelResidentWait();
        this.cancelActive(new Error('Galaxy Renderer V3 packet source disposed.'));
    }

    private cancelResidentWait(): void {
        this.residentUnsubscribe?.();
        this.residentUnsubscribe = null;
    }

    private requireWorker(): Worker {
        if (this.worker) return this.worker;
        if (typeof Worker === 'undefined') {
            throw new Error('Galaxy Renderer V3 requires its dedicated packet worker.');
        }
        const worker = new Worker(new URL('./galaxy-renderer-v3-legacy-input-adapter.worker', import.meta.url), { type: 'module' });
        worker.onmessage = ({ data }: MessageEvent<{ id: number; packet?: GalaxyScenePacketV2; error?: string }>) => {
            const pending = this.pending.get(data.id);
            if (!pending) return;
            this.pending.delete(data.id);
            if (data.packet) {
                const manifest = data.packet.manifest;
                if (manifest.generationId !== pending.request.generationId
                    || manifest.authorityReceipt !== pending.request.authorityReceipt
                    || manifest.sourceMode !== pending.request.sourceMode) {
                    pending.reject(new Error('Galaxy Renderer V3 packet receipt does not match its compilation request.'));
                    return;
                }
                seedGalaxyScenePacket(data.packet);
                pending.resolve(data.packet);
            } else {
                pending.reject(new Error(data.error || 'Galaxy Renderer V3 packet compilation failed.'));
            }
        };
        worker.onerror = (event) => {
            const error = new Error(event.message || 'Galaxy Renderer V3 packet worker failed.');
            for (const pending of this.pending.values()) pending.reject(error);
            this.pending.clear();
            worker.terminate();
            if (this.worker === worker) this.worker = null;
        };
        this.worker = worker;
        return worker;
    }

    private cancelActive(error: Error): void {
        if (!this.worker && !this.pending.size) return;
        const worker = this.worker;
        this.worker = null;
        worker?.terminate();
        for (const pending of this.pending.values()) pending.reject(error);
        this.pending.clear();
    }
}
