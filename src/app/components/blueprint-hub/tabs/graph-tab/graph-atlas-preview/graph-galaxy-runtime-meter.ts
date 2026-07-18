export type GraphGalaxyCompilerSource = 'native' | 'worker' | 'local' | 'fallback' | 'cache';

export interface GraphGalaxyCanvasMeter {
    id: number;
    rafActive: boolean;
    surfaceActive: boolean;
    webglContext: boolean;
    layoutMode: string | null;
    authorityReceipt: string;
    nodes: number;
    links: number;
    lastDrawAgeMs: number | null;
    backingPixels: number;
    canvasBytes: number;
    backdropBytes: number;
    estimatedResidentBytes: number;
    backingWidth: number;
    backingHeight: number;
    dpr: number;
    timings: GraphGalaxyCanvasTimings;
}

export interface GraphGalaxyCanvasTimings {
    sceneCompileMs: number;
    sceneConvertMs: number;
    sceneBuildMs: number;
    rendererSetSceneMs: number;
    applyModeMs: number;
    liveGeometryMs: number;
    focusMs: number;
    instancesMs: number;
    edgeGeometryMs: number;
    labelsMs: number;
    pickMs: number;
    drawMs: number;
}

export interface GraphGalaxyRuntimeSnapshot {
    compilerSource: GraphGalaxyCompilerSource;
    activeCanvases: number;
    activeSurfaces: number;
    webglContexts: number;
    rafActive: number;
    rafSleeping: number;
    nodes: number;
    links: number;
    backingPixels: number;
    canvasBytes: number;
    backdropBytes: number;
    estimatedResidentBytes: number;
    canvases: GraphGalaxyCanvasMeter[];
}

declare const ngDevMode: boolean | undefined;

declare global {
    interface Window {
        __PHOENIX_GALAXY_METER__?: { snapshot: () => GraphGalaxyRuntimeSnapshot };
    }
}

interface CanvasRecord {
    rafActive: boolean;
    surfaceActive: boolean;
    webglContext: boolean;
    layoutMode: string | null;
    authorityReceipt: string;
    nodes: number;
    links: number;
    lastDrawAt: number;
    backingPixels: number;
    canvasBytes: number;
    backdropBytes: number;
    estimatedResidentBytes: number;
    backingWidth: number;
    backingHeight: number;
    dpr: number;
    timings: GraphGalaxyCanvasTimings;
}

class GraphGalaxyRuntimeMeter {
    private nextIdValue = 0;
    private compilerSource: GraphGalaxyCompilerSource = 'local';
    private readonly canvases = new Map<number, CanvasRecord>();
    private readonly enabled = typeof window !== 'undefined'
        && (typeof ngDevMode === 'undefined' || Boolean(ngDevMode));

    constructor() {
        this.publish();
    }

    nextCanvasId(): number {
        return ++this.nextIdValue;
    }

    registerCanvas(id: number): void {
        if (!this.enabled) return;
        this.canvases.set(id, {
            rafActive: false,
            surfaceActive: false,
            webglContext: false,
            layoutMode: null,
            authorityReceipt: '',
            nodes: 0,
            links: 0,
            lastDrawAt: 0,
            backingPixels: 0,
            canvasBytes: 0,
            backdropBytes: 0,
            estimatedResidentBytes: 0,
            backingWidth: 0,
            backingHeight: 0,
            dpr: 1,
            timings: emptyCanvasTimings(),
        });
    }

    unregisterCanvas(id: number): void {
        if (!this.enabled) return;
        this.canvases.delete(id);
    }

    recordCompilerSource(source: GraphGalaxyCompilerSource): void {
        if (!this.enabled) return;
        this.compilerSource = source;
    }

    recordScene(id: number, nodes: number, links: number, layoutMode: string, authorityReceipt: string): void {
        const record = this.canvases.get(id);
        if (!this.enabled || !record) return;
        record.layoutMode = layoutMode;
        record.authorityReceipt = authorityReceipt;
        record.nodes = nodes;
        record.links = links;
    }

    recordRaf(id: number, rafActive: boolean): void {
        const record = this.canvases.get(id);
        if (!this.enabled || !record) return;
        record.rafActive = rafActive;
    }

    recordSurface(id: number, surfaceActive: boolean): void {
        const record = this.canvases.get(id);
        if (!this.enabled || !record) return;
        record.surfaceActive = surfaceActive;
    }

    recordContext(id: number, webglContext: boolean): void {
        const record = this.canvases.get(id);
        if (!this.enabled || !record) return;
        record.webglContext = webglContext;
    }

    recordDraw(id: number, width: number, height: number, dpr: number, time: number, backdropBytes = 0): void {
        const record = this.canvases.get(id);
        if (!this.enabled || !record) return;
        record.lastDrawAt = time;
        record.backingWidth = Math.max(0, Math.floor(width * dpr));
        record.backingHeight = Math.max(0, Math.floor(height * dpr));
        record.backingPixels = record.backingWidth * record.backingHeight;
        record.canvasBytes = record.backingPixels * 4;
        record.backdropBytes = Math.max(0, backdropBytes);
        record.estimatedResidentBytes = Math.round((record.canvasBytes + record.backdropBytes) * 2.4);
        record.dpr = dpr;
    }

    recordTimings(id: number, timings: Partial<GraphGalaxyCanvasTimings>): void {
        const record = this.canvases.get(id);
        if (!this.enabled || !record) return;
        for (const [key, value] of Object.entries(timings) as Array<[keyof GraphGalaxyCanvasTimings, number | undefined]>) {
            if (typeof value === 'number' && Number.isFinite(value)) {
                record.timings[key] = Math.max(0, Math.round(value));
            }
        }
    }

    snapshot(): GraphGalaxyRuntimeSnapshot {
        const now = this.now();
        let rafActive = 0;
        let activeSurfaces = 0;
        let webglContexts = 0;
        let nodes = 0;
        let links = 0;
        let backingPixels = 0;
        let canvasBytes = 0;
        let backdropBytes = 0;
        let estimatedResidentBytes = 0;
        const canvases: GraphGalaxyCanvasMeter[] = [];
        for (const [id, record] of this.canvases) {
            rafActive += record.rafActive ? 1 : 0;
            activeSurfaces += record.surfaceActive ? 1 : 0;
            webglContexts += record.webglContext ? 1 : 0;
            nodes += record.nodes;
            links += record.links;
            backingPixels += record.backingPixels;
            canvasBytes += record.canvasBytes;
            backdropBytes += record.backdropBytes;
            estimatedResidentBytes += record.estimatedResidentBytes;
            canvases.push({
                id,
                rafActive: record.rafActive,
                surfaceActive: record.surfaceActive,
                webglContext: record.webglContext,
                layoutMode: record.layoutMode,
                authorityReceipt: record.authorityReceipt,
                nodes: record.nodes,
                links: record.links,
                lastDrawAgeMs: record.lastDrawAt ? Math.round(now - record.lastDrawAt) : null,
                backingPixels: record.backingPixels,
                canvasBytes: record.canvasBytes,
                backdropBytes: record.backdropBytes,
                estimatedResidentBytes: record.estimatedResidentBytes,
                backingWidth: record.backingWidth,
                backingHeight: record.backingHeight,
                dpr: record.dpr,
                timings: { ...record.timings },
            });
        }
        return {
            compilerSource: this.compilerSource,
            activeCanvases: this.canvases.size,
            activeSurfaces,
            webglContexts,
            rafActive,
            rafSleeping: this.canvases.size - rafActive,
            nodes,
            links,
            backingPixels,
            canvasBytes,
            backdropBytes,
            estimatedResidentBytes,
            canvases,
        };
    }

    private publish(): void {
        if (!this.enabled) return;
        window.__PHOENIX_GALAXY_METER__ = { snapshot: () => this.snapshot() };
    }

    private now(): number {
        return typeof performance !== 'undefined' ? performance.now() : Date.now();
    }
}

function emptyCanvasTimings(): GraphGalaxyCanvasTimings {
    return {
        sceneCompileMs: 0,
        sceneConvertMs: 0,
        sceneBuildMs: 0,
        rendererSetSceneMs: 0,
        applyModeMs: 0,
        liveGeometryMs: 0,
        focusMs: 0,
        instancesMs: 0,
        edgeGeometryMs: 0,
        labelsMs: 0,
        pickMs: 0,
        drawMs: 0,
    };
}

export const graphGalaxyRuntimeMeter = new GraphGalaxyRuntimeMeter();
