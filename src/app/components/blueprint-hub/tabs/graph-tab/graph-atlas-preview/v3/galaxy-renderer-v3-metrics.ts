import type { GalaxyRendererV3Metrics } from './galaxy-renderer-v3-contract';

export type GalaxyRendererV3MetricListener = (metrics: Readonly<GalaxyRendererV3Metrics>) => void;

class GalaxyRendererV3MetricStore {
    private readonly listeners = new Set<GalaxyRendererV3MetricListener>();
    private current: GalaxyRendererV3Metrics = emptyGalaxyRendererV3Metrics();

    snapshot(): Readonly<GalaxyRendererV3Metrics> {
        return { ...this.current };
    }

    update(patch: Partial<GalaxyRendererV3Metrics>): void {
        this.current = { ...this.current, ...patch };
        const snapshot = this.snapshot();
        for (const listener of this.listeners) listener(snapshot);
    }

    subscribe(listener: GalaxyRendererV3MetricListener): () => void {
        this.listeners.add(listener);
        listener(this.snapshot());
        return () => this.listeners.delete(listener);
    }
}

export const galaxyRendererV3Metrics = new GalaxyRendererV3MetricStore();

export function emptyGalaxyRendererV3Metrics(): GalaxyRendererV3Metrics {
    return {
        authorityReceipt: '',
        generationId: '',
        backend: 'unavailable',
        residentNodes: 0,
        residentEdges: 0,
        gpuBytes: 0,
        installMs: 0,
        firstPixelMs: 0,
        sceneComputeMs: 0,
        sceneReadbackBytes: 0,
        nodeSizeScratchBytes: 0,
        frames: 0,
        failures: 0,
    };
}
