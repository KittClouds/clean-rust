import {
    AfterViewInit,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    inject,
    Input,
    OnChanges,
    OnDestroy,
    Output,
    SimpleChanges,
    ViewChild,
} from '@angular/core';

import type { GraphCanvasHit } from '../graph-canvas-interaction';
import type { GraphRendererPointer } from '../graph-renderer-port';
import {
    type GalaxyInputEdge,
    type GalaxyQueryFocus,
    type GalaxyRenderableNode,
    type GalaxyRenderSettings,
} from '../graph-galaxy-engine';
import type { GalaxySceneSourceMode } from '../graph-galaxy-scene-v2';
import { GALAXY_RENDERER_V3_SCHEMA, type GalaxyRendererV3Backend } from './galaxy-renderer-v3-contract';
import { normalizeGalaxyRendererV3Settings } from './galaxy-renderer-v3-input-adapter';
import {
    GALAXY_RENDERER_V3_CLICK_TRAVEL_LIMIT,
    galaxyRendererV3SuppressNodeActivation,
} from './galaxy-renderer-v3-interaction';
import { galaxyRendererV3Metrics } from './galaxy-renderer-v3-metrics';
import { GalaxyRendererV3PacketSource } from './galaxy-renderer-v3-packet-source';

@Component({
    selector: 'app-graph-galaxy-canvas-v3',
    standalone: true,
    host: {
        '[attr.data-v3-status]': 'status',
        '[attr.data-v3-failure]': 'failure || null',
        '[attr.data-v3-resident]': 'residentCount',
        '[attr.data-v3-shadow]': 'shadowMode',
    },
    template: `
        <div class="v3-shell" [class.v3-shadow]="shadowMode">
            <canvas
                #canvas
                class="v3-canvas"
                (pointerdown)="onPointerDown($event)"
                (pointermove)="onPointerMove($event)"
                (pointerup)="onPointerUp($event)"
                (pointercancel)="onPointerUp($event)"
                (pointerleave)="onPointerLeave()"
                (wheel)="onWheel($event)"
                (click)="onClick($event)"
                (dblclick)="onDoubleClick($event)"
                (contextmenu)="$event.preventDefault()"
            ></canvas>
            @if (!shadowMode) {
                <div class="v3-meter" aria-label="Galaxy Renderer V3 counters">
                    <span><b>v3</b>{{ status }}</span>
                    <span><b>corpus</b>{{ corpusCount }}</span>
                    <span><b>resident</b>{{ residentCount }}</span>
                    <span><b>gpu</b>{{ gpuMiB }} MiB</span>
                </div>
            }
            @if (failure && !shadowMode) {
                <div class="v3-failure" role="alert">
                    <b>V3 failed closed</b>
                    <span>{{ failure }}</span>
                </div>
            }
        </div>
    `,
    styles: [`
        :host { display: block; height: 100%; min-height: 0; background: #02040a; }
        .v3-shell { position: relative; height: 100%; overflow: hidden; background: #02040a; }
        .v3-canvas { display: block; width: 100%; height: 100%; min-height: 360px; touch-action: none; user-select: none; cursor: grab; }
        .v3-canvas:active { cursor: grabbing; }
        .v3-shadow { visibility: hidden; pointer-events: none; }
        .v3-meter { position: absolute; left: 12px; bottom: 10px; z-index: 7; display: flex; gap: 8px; pointer-events: none; color: rgba(203,213,225,.7); font: 600 9px/1.1 ui-monospace, monospace; letter-spacing: .06em; text-transform: uppercase; }
        .v3-meter span { display: inline-flex; gap: 4px; padding: 5px 7px; border: 1px solid rgba(71,85,105,.28); border-radius: 5px; background: rgba(2,6,14,.7); }
        .v3-meter b { color: rgba(94,234,212,.82); }
        .v3-failure { position: absolute; inset: 50% auto auto 50%; width: min(520px, calc(100% - 48px)); transform: translate(-50%,-50%); display: grid; gap: 8px; padding: 18px; border: 1px solid rgba(248,113,113,.35); border-radius: 12px; color: #fecaca; background: rgba(30,5,9,.92); font: 500 12px/1.5 ui-monospace, monospace; }
        .v3-failure b { color: #fca5a5; text-transform: uppercase; letter-spacing: .08em; }
    `],
})
export class GraphGalaxyCanvasV3Component implements AfterViewInit, OnChanges, OnDestroy {
    private readonly changeDetector = inject(ChangeDetectorRef);

    @Input() entities: GalaxyRenderableNode[] = [];
    @Input() edges: GalaxyInputEdge[] = [];
    @Input() settings: Partial<GalaxyRenderSettings> | null = null;
    @Input() selectedEntityIds: readonly string[] = [];
    @Input() queryFocus: GalaxyQueryFocus | null = null;
    @Input() viewMode: '3d' | 'map' = '3d';
    @Input() sourceMode: GalaxySceneSourceMode = 'entities';
    @Input() sceneIdentity = '';
    @Input() surfaceActive = true;
    @Input() lassoEnabled = false;
    @Input() shadowMode = false;

    @Output() entitySelected = new EventEmitter<GalaxyRenderableNode>();
    @Output() entityHovered = new EventEmitter<GalaxyRenderableNode | null>();
    @Output() objectSelected = new EventEmitter<GraphCanvasHit>();
    @Output() objectHovered = new EventEmitter<GraphCanvasHit | null>();
    @Output() batchSelected = new EventEmitter<string[]>();

    @ViewChild('canvas', { static: true }) private canvasRef!: ElementRef<HTMLCanvasElement>;

    status = 'idle';
    failure = '';
    corpusCount = 0;
    residentCount = 0;
    gpuMiB = '0.0';

    private readonly packetSource = new GalaxyRendererV3PacketSource();
    private backend: GalaxyRendererV3Backend | null = null;
    private backendLoad: Promise<GalaxyRendererV3Backend> | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private viewReady = false;
    private destroyed = false;
    private mounted = false;
    private inputVersion = 0;
    private buildQueued = false;
    private dragging = false;
    private nodeDragging = false;
    private panning = false;
    private pointerMoved = false;
    private pointerTravel = 0;
    private pointerDownAt = 0;
    private suppressNextClick = false;
    private lastPointerX = 0;
    private lastPointerY = 0;
    private hoverToken = 0;
    private pointerSession = 0;
    private animationFrame = 0;

    ngAfterViewInit(): void {
        this.viewReady = true;
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(this.canvasRef.nativeElement);
        this.resize();
        this.queueBuild();
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['selectedEntityIds']) {
            this.backend?.setSelectedIdentities(this.selectedEntityIds);
            this.backend?.render();
        }
        if (changes['viewMode']) {
            this.backend?.setMode(this.viewMode === 'map' ? '2d' : '3d');
            this.backend?.render();
        }
        if (changes['settings']) {
            this.backend?.setSettings(this.currentSettings());
            this.syncAnimation();
        }
        if (changes['surfaceActive']) {
            this.syncAnimation();
            if (this.surfaceActive) this.queueBuild();
        }
        if (changes['entities'] || changes['edges'] || changes['sourceMode'] || changes['sceneIdentity']) {
            this.inputVersion++;
            this.queueBuild();
        }
    }

    ngOnDestroy(): void {
        this.destroyed = true;
        this.inputVersion++;
        if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
        this.resizeObserver?.disconnect();
        this.packetSource.dispose();
        this.backend?.dispose();
        const canvas = this.canvasRef?.nativeElement;
        if (canvas) {
            canvas.width = 0;
            canvas.height = 0;
        }
    }

    resetCamera(): void {
        this.backend?.resetCamera();
        this.backend?.render();
    }

    fitToGraph(): void {
        this.backend?.fitToGraph();
        this.backend?.render();
    }

    focusEntity(entityId: string): void {
        this.backend?.focusIdentity(entityId);
        this.backend?.render();
    }

    clearCameraFocus(): void {
        this.fitToGraph();
    }

    onPointerDown(event: PointerEvent): void {
        if (this.shadowMode || !this.backend) return;
        event.preventDefault();
        const backend = this.backend;
        const pointer = this.pointer(event);
        const session = ++this.pointerSession;
        this.dragging = true;
        this.panning = event.altKey || event.button === 1 || event.button === 2;
        this.nodeDragging = false;
        this.pointerMoved = false;
        this.pointerTravel = 0;
        this.pointerDownAt = event.timeStamp;
        this.suppressNextClick = false;
        this.lastPointerX = event.clientX;
        this.lastPointerY = event.clientY;
        this.canvasRef.nativeElement.setPointerCapture(event.pointerId);
        if (!this.panning && event.button === 0 && this.currentSettings().nodeDragMode !== 'camera') {
            void backend.pick(pointer).then((id) => {
                if (!id || this.destroyed || !this.dragging || session !== this.pointerSession) return;
                this.nodeDragging = backend.beginNodeDrag(id, pointer);
                if (this.nodeDragging) {
                    backend.setHoveredIdentity(id);
                    const entity = this.entityForIdentity(id);
                    this.entityHovered.emit(entity);
                    this.objectHovered.emit({ kind: 'node', id });
                }
            });
        }
    }

    onPointerMove(event: PointerEvent): void {
        if (this.shadowMode || !this.backend) return;
        if (!this.dragging) {
            void this.updateHover(this.pointer(event));
            return;
        }
        const dx = event.clientX - this.lastPointerX;
        const dy = event.clientY - this.lastPointerY;
        this.lastPointerX = event.clientX;
        this.lastPointerY = event.clientY;
        this.pointerTravel += Math.hypot(dx, dy);
        this.pointerMoved ||= this.pointerTravel > GALAXY_RENDERER_V3_CLICK_TRAVEL_LIMIT;
        if (this.nodeDragging) this.backend.dragNode(this.pointer(event));
        else this.panning ? this.backend.pan(dx, dy) : this.backend.rotate(dx, dy);
        this.backend.render();
    }

    onPointerUp(event: PointerEvent): void {
        if (!this.dragging) return;
        this.suppressNextClick = galaxyRendererV3SuppressNodeActivation(
            this.nodeDragging,
            this.pointerTravel,
            Math.max(0, event.timeStamp - this.pointerDownAt),
        );
        this.pointerSession++;
        this.backend?.endNodeDrag();
        this.dragging = false;
        this.nodeDragging = false;
        this.panning = false;
        if (this.canvasRef.nativeElement.hasPointerCapture(event.pointerId)) {
            this.canvasRef.nativeElement.releasePointerCapture(event.pointerId);
        }
    }

    onPointerLeave(): void {
        this.hoverToken++;
        this.pointerSession++;
        this.backend?.endNodeDrag();
        this.dragging = false;
        this.nodeDragging = false;
        this.panning = false;
        this.backend?.setHoveredIdentity(null);
        if (!this.shadowMode) {
            this.entityHovered.emit(null);
            this.objectHovered.emit(null);
        }
    }

    onWheel(event: WheelEvent): void {
        if (this.shadowMode || !this.backend) return;
        event.preventDefault();
        this.backend.zoomAt(event.deltaY, this.pointer(event));
        this.backend.render();
    }

    async onClick(event: MouseEvent): Promise<void> {
        if (this.suppressNextClick) {
            this.suppressNextClick = false;
            return;
        }
        if (this.shadowMode || this.pointerMoved || !this.backend) return;
        const id = await this.backend.pick(this.pointer(event));
        if (!id || this.destroyed) return;
        const entity = this.entityForIdentity(id);
        if (entity) this.entitySelected.emit(entity);
        this.objectSelected.emit({ kind: 'node', id });
    }

    async onDoubleClick(event: MouseEvent): Promise<void> {
        if (this.shadowMode || !this.backend) return;
        const id = await this.backend.pick(this.pointer(event));
        id ? this.focusEntity(id) : this.fitToGraph();
    }

    private queueBuild(): void {
        if (!this.viewReady || this.destroyed || this.buildQueued) return;
        this.buildQueued = true;
        queueMicrotask(() => {
            this.buildQueued = false;
            void this.build(this.inputVersion);
        });
    }

    private async build(version: number): Promise<void> {
        if (this.destroyed || !this.surfaceActive) return;
        this.setStatus('packing');
        const settings = normalizeGalaxyRendererV3Settings(this.settings, this.sourceMode);
        const generationId = this.sceneIdentity.split('\u0000', 1)[0] || `v3-ephemeral-${version}`;
        const authorityReceipt = this.sceneIdentity || `${generationId}:unreceipted`;
        try {
            const [backend, packet] = await Promise.all([
                this.ensureBackend(),
                this.packetSource.compile({
                    entities: this.entities,
                    edges: this.edges,
                    settings,
                    sourceMode: this.sourceMode,
                    generationId,
                    authorityReceipt,
                }),
            ]);
            if (this.destroyed || version !== this.inputVersion) return;
            await this.ensureMounted(backend);
            await backend.openGeneration({
                schemaVersion: GALAXY_RENDERER_V3_SCHEMA,
                generationId,
                authorityReceipt,
                packet,
                corpus: { nodes: this.entities.length, edges: this.edges.length },
            }, settings);
            if (this.destroyed || version !== this.inputVersion) return;
            backend.setSettings(this.currentSettings());
            backend.setMode(this.viewMode === 'map' ? '2d' : '3d');
            backend.setSelectedIdentities(this.selectedEntityIds);
            backend.render();
            this.failure = '';
            this.setStatus('first-pixel');
            this.refreshMetrics();
            this.syncAnimation();
        } catch (error) {
            if (this.destroyed || version !== this.inputVersion) return;
            this.failure = error instanceof Error ? error.message : String(error);
            this.setStatus('failed');
            galaxyRendererV3Metrics.update({
                failures: galaxyRendererV3Metrics.snapshot().failures + 1,
            });
            console.error('[GalaxyRendererV3] Isolated generation failed closed.', error);
        }
    }

    private ensureBackend(): Promise<GalaxyRendererV3Backend> {
        if (this.backend) return Promise.resolve(this.backend);
        return this.backendLoad ||= import('./galaxy-renderer-v3-webgpu-backend')
            .then(({ GalaxyRendererV3WebGpuBackend }) => {
                const backend = new GalaxyRendererV3WebGpuBackend();
                if (this.destroyed) backend.dispose();
                this.backend = backend;
                return backend;
            });
    }

    private async ensureMounted(backend: GalaxyRendererV3Backend): Promise<void> {
        if (this.mounted) return;
        await backend.mount(this.canvasRef.nativeElement);
        if (this.destroyed) return;
        this.mounted = true;
        this.resize();
    }

    private resize(): void {
        const canvas = this.canvasRef?.nativeElement;
        if (!canvas || !this.backend) return;
        const rect = canvas.getBoundingClientRect();
        const dpr = Math.min(2, Math.max(0.75, window.devicePixelRatio || 1));
        this.backend.resize(Math.max(1, Math.floor(rect.width)), Math.max(1, Math.floor(rect.height)), dpr);
        this.backend.render();
    }

    private syncAnimation(): void {
        if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
        this.animationFrame = 0;
        if (!this.surfaceActive || !this.backend || !this.currentSettings().autoRotate) return;
        const tick = () => {
            if (this.destroyed || !this.surfaceActive || !this.backend || !this.currentSettings().autoRotate) {
                this.animationFrame = 0;
                return;
            }
            this.backend.rotate(0.18, 0);
            this.backend.render();
            this.animationFrame = requestAnimationFrame(tick);
        };
        this.animationFrame = requestAnimationFrame(tick);
    }

    private async updateHover(pointer: GraphRendererPointer): Promise<void> {
        const token = ++this.hoverToken;
        const id = await this.backend?.pick(pointer) || null;
        if (this.destroyed || token !== this.hoverToken) return;
        this.backend?.setHoveredIdentity(id);
        const entity = id ? this.entityForIdentity(id) : null;
        this.entityHovered.emit(entity);
        this.objectHovered.emit(id ? { kind: 'node', id } : null);
    }

    private entityForIdentity(identity: string): GalaxyRenderableNode | null {
        return this.entities.find((item) => item.id === identity || item.metadata?.sourceEntityId === identity) || null;
    }

    private pointer(event: MouseEvent): GraphRendererPointer {
        const rect = this.canvasRef.nativeElement.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top, width: rect.width, height: rect.height };
    }

    private currentSettings(): GalaxyRenderSettings {
        return normalizeGalaxyRendererV3Settings(this.settings, this.sourceMode);
    }

    private setStatus(status: string): void {
        this.status = status;
        this.changeDetector.markForCheck();
    }

    private refreshMetrics(): void {
        const metrics = this.backend?.metrics;
        if (!metrics) return;
        this.corpusCount = this.entities.length + this.edges.length;
        this.residentCount = metrics.residentNodes + metrics.residentEdges;
        this.gpuMiB = (metrics.gpuBytes / (1024 * 1024)).toFixed(1);
        this.changeDetector.markForCheck();
    }
}
