import type { GraphRendererMode, GraphRendererPointer } from '../graph-renderer-port';
import type { GalaxyRenderSettings } from '../graph-galaxy-engine';
import type { GalaxyScenePacketV2 } from '../graph-galaxy-scene-packet-v2.model';

export const GALAXY_RENDERER_V3_SCHEMA = 'phoenix-galaxy-renderer/v3' as const;

export interface GalaxyRendererV3Generation {
    schemaVersion: typeof GALAXY_RENDERER_V3_SCHEMA;
    generationId: string;
    authorityReceipt: string;
    packet: GalaxyScenePacketV2;
    corpus: { nodes: number; edges: number };
}

export interface GalaxyRendererV3Metrics {
    authorityReceipt: string;
    generationId: string;
    backend: 'webgpu' | 'unavailable';
    residentNodes: number;
    residentEdges: number;
    gpuBytes: number;
    installMs: number;
    firstPixelMs: number;
    frames: number;
    failures: number;
}

export interface GalaxyRendererV3Backend {
    readonly metrics: GalaxyRendererV3Metrics;
    mount(canvas: HTMLCanvasElement): Promise<void>;
    openGeneration(generation: GalaxyRendererV3Generation, settings: GalaxyRenderSettings): Promise<void>;
    setSettings(settings: GalaxyRenderSettings): void;
    setMode(mode: GraphRendererMode): void;
    resize(width: number, height: number, dpr: number): void;
    render(): void;
    rotate(deltaX: number, deltaY: number): void;
    pan(deltaX: number, deltaY: number): void;
    zoomAt(delta: number, pointer: GraphRendererPointer): void;
    resetCamera(): void;
    fitToGraph(): void;
    focusIdentity(identity: string): void;
    setSelectedIdentities(identities: readonly string[]): void;
    setHoveredIdentity(identity: string | null): void;
    pick(pointer: GraphRendererPointer): Promise<string | null>;
    dispose(): void;
}

export interface GalaxyRendererV3ResidentPages {
    nodeCount: number;
    edgeCount: number;
    positions3d: Float32Array;
    radii: Float32Array;
    nodeColorsRgba8: Uint8Array;
    nodeFlags: Uint8Array;
    nodeIdentityKeys: Uint32Array;
    edgePairs: Uint32Array;
    edgeColorsRgba8: Uint8Array;
    edgeAlpha: Float32Array;
    edgeFlags: Uint8Array;
}
