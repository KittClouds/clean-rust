import { AfterViewInit, Component, ElementRef, EventEmitter, inject, Input, OnChanges, OnDestroy, Output, SimpleChanges, ViewChild } from '@angular/core';

import { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { compileGalaxyScene } from './graph-galaxy-scene-compiler';
import { graphGalaxyRuntimeMeter, type GraphGalaxyCanvasTimings } from './graph-galaxy-runtime-meter';
import { budgetGalaxySurface } from './graph-galaxy-surface-budget';
import { galaxySceneToV2, type GalaxySceneSourceMode, type GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { mergeGalaxySettings, type GalaxyInputEdge, type GalaxyQueryFocus, type GalaxyRenderableNode, type GalaxyRenderSettings } from './graph-galaxy-engine';
import { ThreeGalaxyRenderer } from './three-galaxy-renderer';
import type { GraphCanvasHit } from './graph-canvas-interaction';

export interface GraphGalaxySurfaceGate {
    destroyed: boolean;
    documentVisible: boolean;
    isVisible: boolean;
    surfaceActive: boolean;
}

export function canGraphGalaxyCanvasHoldSurface(state: GraphGalaxySurfaceGate): boolean {
    return !state.destroyed && state.documentVisible && state.isVisible && state.surfaceActive;
}

@Component({
    selector: 'app-graph-galaxy-canvas',
    standalone: true,
    template: `
        <div class="canvas-shell">
            <canvas
                #canvas
                class="block h-full min-h-[360px] w-full touch-none select-none rounded-none bg-[#02040a] cursor-grab active:cursor-grabbing"
                [class.cursor-crosshair]="lassoEnabled || lassoSelecting"
                (pointerdown)="onPointerDown($event)"
                (pointermove)="onPointerMove($event)"
                (pointerup)="onPointerUp()"
                (pointerleave)="onPointerLeave()"
                (wheel)="onWheel($event)"
                (contextmenu)="$event.preventDefault()"
                (dblclick)="onDoubleClick($event)"
                (click)="onClick($event)"
            ></canvas>
            @if (lassoRect) {
            <div class="lasso-rect"
                [style.left.px]="lassoRect.left"
                [style.top.px]="lassoRect.top"
                [style.width.px]="lassoRect.right - lassoRect.left"
                [style.height.px]="lassoRect.bottom - lassoRect.top"></div>
            }
        </div>
    `,
    styles: [`
        :host {
            display: block;
            height: 100%;
            background: #02040a;
        }
        .canvas-shell { position: relative; height: 100%; }
        .lasso-rect { position: absolute; z-index: 8; pointer-events: none; border: 1px solid rgba(94,234,212,.95); background: rgba(20,184,166,.12); box-shadow: 0 0 24px rgba(45,212,191,.18) inset; }
    `],
})
export class GraphGalaxyCanvasComponent implements AfterViewInit, OnChanges, OnDestroy {
    private readonly phoenix = inject(PhoenixBackendService);
    @Input() entities: GalaxyRenderableNode[] = [];
    @Input() edges: GalaxyInputEdge[] = [];
    @Input() settings: Partial<GalaxyRenderSettings> | null = null;
    @Input() selectedEntityId: string | null = null;
    @Input() queryFocus: GalaxyQueryFocus | null = null;
    @Input() viewMode: '3d' | 'map' = '3d';
    @Input() sourceMode: GalaxySceneSourceMode = 'entities';
    @Input() surfaceActive = true;
    @Input() lassoEnabled = false;
    @Output() entitySelected = new EventEmitter<GalaxyRenderableNode>();
    @Output() entityHovered = new EventEmitter<GalaxyRenderableNode | null>();
    @Output() objectSelected = new EventEmitter<GraphCanvasHit>();
    @Output() objectHovered = new EventEmitter<GraphCanvasHit | null>();
    @Output() batchSelected = new EventEmitter<string[]>();
    @ViewChild('canvas', { static: true }) private canvasRef!: ElementRef<HTMLCanvasElement>;

    private readonly renderer = new ThreeGalaxyRenderer();
    private resizeObserver?: ResizeObserver;
    private intersectionObserver?: IntersectionObserver;
    private frameId = 0;
    private scene: GalaxySceneV2 | null = null;
    private dragging = false;
    private nodeDragging = false;
    private panning = false;
    private pointerMoved = false;
    private lastPointerX = 0;
    private lastPointerY = 0;
    private hoverKey: string | null = null;
    lassoSelecting = false;
    lassoRect: { left: number; top: number; right: number; bottom: number; width: number; height: number } | null = null;
    private lassoStart: { x: number; y: number } | null = null;
    private needsLayout = true;
    private isVisible = false;
    private documentVisible = typeof document === 'undefined' ? true : !document.hidden;
    private animationActive = false;
    private currentDpr = 1;
    private sceneBuildPromise: Promise<void> | null = null;
    private layoutVersion = 0;
    private destroyed = false;
    private viewReady = false;
    private unsubscribeColors?: () => void;
    private readonly meterId = graphGalaxyRuntimeMeter.nextCanvasId();
    private readonly onVisibilityChange = () => {
        this.documentVisible = !document.hidden;
        this.syncSurface();
    };

    ngAfterViewInit(): void {
        const canvas = this.canvasRef.nativeElement;
        this.viewReady = true;
        this.resizeObserver = new ResizeObserver(() => this.resizeCanvas());
        this.resizeObserver.observe(canvas);
        graphGalaxyRuntimeMeter.registerCanvas(this.meterId);
        this.intersectionObserver = new IntersectionObserver((entries) => {
            const visible = entries.some((entry) => entry.isIntersecting && entry.intersectionRatio > 0.02);
            if (this.isVisible === visible) return;
            this.isVisible = visible;
            this.syncSurface();
        }, { threshold: [0, 0.02, 0.1] });
        this.intersectionObserver.observe(canvas);
        document.addEventListener('visibilitychange', this.onVisibilityChange);
        this.unsubscribeColors = entityColorStore.subscribe(() => this.markLayoutDirty());
        this.resizeCanvas();
        this.requestSceneBuild();
        this.syncSurface();
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['settings']) {
            const previous = this.mergeSettingsForSource(changes['settings'].previousValue);
            const current = this.currentSettings();
            if (this.renderer.hasContext()) this.renderer.setSettings(this.settings);
            if (galaxySettingsNeedSceneRebuild(previous, current)) this.markLayoutDirty();
            if (this.viewReady) this.syncSurface();
        }
        if (changes['entities'] || changes['edges'] || changes['sourceMode']) this.markLayoutDirty();
        if (changes['selectedEntityId'] && this.renderer.hasContext()) {
            this.renderer.selectNode(this.selectedEntityId);
            this.recordRendererTimings();
        }
        if (changes['viewMode'] && this.renderer.hasContext()) this.renderer.setMode(this.viewMode === 'map' ? '2d' : '3d');
        if (changes['surfaceActive'] && this.viewReady) this.syncSurface();
    }

    ngOnDestroy(): void {
        this.destroyed = true;
        this.stop();
        graphGalaxyRuntimeMeter.unregisterCanvas(this.meterId);
        this.resizeObserver?.disconnect();
        this.intersectionObserver?.disconnect();
        document.removeEventListener('visibilitychange', this.onVisibilityChange);
        this.unsubscribeColors?.();
        this.renderer.dispose();
        const canvas = this.canvasRef?.nativeElement;
        if (canvas) { canvas.width = 0; canvas.height = 0; }
    }

    resetCamera(): void {
        if (!this.renderer.hasContext()) return;
        this.renderer.resetCamera();
        this.draw();
    }

    fitToGraph(): void {
        if (!this.renderer.hasContext()) return;
        this.renderer.fitToGraph();
        this.draw();
    }

    focusEntity(entityId: string): void {
        if (!this.renderer.hasContext()) return;
        this.renderer.focusNode(entityId);
        this.draw();
    }

    clearCameraFocus(): void {
        if (!this.renderer.hasContext()) return;
        this.renderer.clearFocus();
        this.draw();
    }

    onPointerDown(event: PointerEvent): void {
        event.preventDefault();
        const settings = this.currentSettings();
        const pointer = this.pointerFromEvent(event);
        const useLasso = event.button === 0 && (this.lassoEnabled || event.shiftKey);
        const picked = useLasso ? null : this.pick(event);
        this.dragging = true;
        this.lassoSelecting = useLasso;
        this.lassoStart = useLasso ? { x: pointer.x, y: pointer.y } : null;
        this.lassoRect = useLasso ? {
            left: pointer.x,
            top: pointer.y,
            right: pointer.x,
            bottom: pointer.y,
            width: pointer.width,
            height: pointer.height,
        } : null;
        this.nodeDragging = Boolean(
            picked && settings.nodeDragMode !== 'camera' && event.button === 0 &&
            this.renderer.beginNodeDrag(picked, pointer),
        );
        this.panning = !this.lassoSelecting && !this.nodeDragging && (event.altKey || event.button === 1 || event.button === 2);
        this.pointerMoved = false;
        this.lastPointerX = event.clientX;
        this.lastPointerY = event.clientY;
        if (picked) this.setHover({ kind: 'node', id: picked });
        this.canvasRef.nativeElement.setPointerCapture(event.pointerId);
        this.syncSurface();
    }

    onPointerMove(event: PointerEvent): void {
        if (!this.dragging) {
            this.updateHover(event);
            return;
        }
        const dx = event.clientX - this.lastPointerX;
        const dy = event.clientY - this.lastPointerY;
        this.lastPointerX = event.clientX;
        this.lastPointerY = event.clientY;
        this.pointerMoved ||= Math.abs(dx) + Math.abs(dy) > 3;
        if (this.lassoSelecting) {
            const pointer = this.pointerFromEvent(event);
            const start = this.lassoStart || pointer;
            this.lassoRect = {
                left: Math.min(start.x, pointer.x),
                top: Math.min(start.y, pointer.y),
                right: Math.max(start.x, pointer.x),
                bottom: Math.max(start.y, pointer.y),
                width: pointer.width,
                height: pointer.height,
            };
        } else if (this.nodeDragging) this.renderer.dragNode(this.pointerFromEvent(event));
        else this.panning ? this.renderer.pan(dx, dy) : this.renderer.rotate(dx, dy);
        if (!this.lassoSelecting) this.draw();
    }

    onPointerUp(): void {
        if (this.lassoSelecting && this.lassoRect) {
            this.batchSelected.emit(this.renderer.nodesInRect(this.lassoRect));
        }
        const relax = this.nodeDragging && this.renderer.endNodeDrag();
        this.dragging = false;
        this.nodeDragging = false;
        this.panning = false;
        this.lassoSelecting = false;
        this.lassoStart = null;
        this.lassoRect = null;
        if (relax) this.start();
        this.syncSurface();
    }

    onPointerLeave(): void {
        this.onPointerUp();
        this.setHover(null);
    }

    onWheel(event: WheelEvent): void {
        event.preventDefault();
        this.renderer.zoomAt(event.deltaY, this.pointerFromEvent(event));
        this.draw();
    }

    onClick(event: MouseEvent): void {
        if (this.pointerMoved) return;
        const hit = this.pickObject(event);
        if (!hit) return;
        const entity = hit.kind === 'node'
            ? this.entities.find((item) => item.id === hit.id || item.metadata?.sourceEntityId === hit.id)
            : null;
        if (entity) {
            const nextId = entity.id === this.selectedEntityId ? null : entity.id;
            this.renderer.selectNode(nextId);
            this.draw();
            this.entitySelected.emit(entity);
        }
        this.objectSelected.emit(hit);
    }

    onDoubleClick(event: MouseEvent): void {
        const hit = this.pickObject(event);
        if (!hit) {
            this.fitToGraph();
            return;
        }
        if (hit.kind === 'node' && this.currentSettings().clickFocus) this.focusEntity(hit.id);
    }

    private start(): void {
        if (this.animationActive) return;
        this.animationActive = true;
        graphGalaxyRuntimeMeter.recordRaf(this.meterId, true);
        const render = () => {
            if (!this.animationActive || !this.shouldAnimate()) {
                this.stop();
                return;
            }
            if (this.renderer.hasActiveForces()) this.renderer.tickForces();
            if (this.currentSettings().autoRotate) this.renderer.rotate(0.18, 0);
            this.draw();
            this.frameId = requestAnimationFrame(render);
        };
        this.frameId = requestAnimationFrame(render);
    }

    private stop(): void {
        this.animationActive = false;
        graphGalaxyRuntimeMeter.recordRaf(this.meterId, false);
        if (this.frameId) cancelAnimationFrame(this.frameId);
        this.frameId = 0;
    }

    private syncSurface(): void {
        graphGalaxyRuntimeMeter.recordSurface(this.meterId, this.canHoldSurface());
        if (!this.canHoldSurface()) {
            this.releaseSurface();
            return;
        }
        this.ensureRendererMounted();
        this.resizeCanvas();
        this.requestSceneBuild();
        this.shouldAnimate() ? this.start() : (this.stop(), this.draw());
    }

    private shouldAnimate(): boolean {
        const settings = this.currentSettings();
        return this.canHoldSurface() && (
            this.dragging ||
            this.renderer.hasActiveForces() ||
            settings.autoRotate ||
            settings.particleFlow
        );
    }

    private canHoldSurface(): boolean {
        return canGraphGalaxyCanvasHoldSurface({
            destroyed: this.destroyed,
            documentVisible: this.documentVisible,
            isVisible: this.isVisible,
            surfaceActive: this.surfaceActive,
        });
    }

    private resizeCanvas(): void {
        const rect = this.canvasRef.nativeElement.getBoundingClientRect();
        const budget = budgetGalaxySurface(rect.width, rect.height, window.devicePixelRatio || 1, this.shouldAnimate());
        this.currentDpr = budget.dpr;
        this.renderer.resize(Math.max(1, Math.floor(rect.width)), Math.max(1, Math.floor(rect.height)), budget.dpr);
        graphGalaxyRuntimeMeter.recordDraw(this.meterId, budget.backingWidth / budget.dpr, budget.backingHeight / budget.dpr, budget.dpr, performance.now(), 0);
    }

    private releaseSurface(): void {
        this.stop();
        this.renderer.releaseContext();
        graphGalaxyRuntimeMeter.recordContext(this.meterId, false);
        const canvas = this.canvasRef?.nativeElement;
        if (canvas) { canvas.width = 0; canvas.height = 0; }
        graphGalaxyRuntimeMeter.recordDraw(this.meterId, 0, 0, 1, performance.now(), 0);
    }

    private ensureRendererMounted(): void {
        const canvas = this.canvasRef.nativeElement;
        const created = this.renderer.mount(canvas);
        if (!created) return;
        graphGalaxyRuntimeMeter.recordContext(this.meterId, true);
        this.renderer.setSettings(this.settings);
        this.renderer.setMode(this.viewMode === 'map' ? '2d' : '3d');
        if (this.scene) {
            const setSceneStarted = performance.now();
            this.renderer.setScene(this.scene);
            this.recordRendererTimings({ rendererSetSceneMs: performance.now() - setSceneStarted });
            this.renderer.selectNode(this.selectedEntityId);
            this.recordRendererTimings();
        }
    }

    private draw(): void {
        if (!this.canHoldSurface()) return;
        this.renderer.render();
        this.recordRendererTimings();
        const canvas = this.canvasRef.nativeElement;
        graphGalaxyRuntimeMeter.recordDraw(this.meterId, canvas.width / this.currentDpr, canvas.height / this.currentDpr, this.currentDpr, performance.now(), 0);
    }

    private markLayoutDirty(): void {
        this.needsLayout = true;
        this.layoutVersion += 1;
        this.requestSceneBuild();
    }

    private requestSceneBuild(): void {
        if (this.destroyed || !this.needsLayout || this.sceneBuildPromise || !this.canHoldSurface()) return;
        this.needsLayout = false;
        const version = this.layoutVersion;
        const buildStarted = performance.now();
        this.sceneBuildPromise = compileGalaxyScene(this.phoenix, this.entities, this.edges, this.currentSettings())
            .then((scene) => {
                if (this.destroyed || this.layoutVersion !== version) return;
                const sceneCompileMs = performance.now() - buildStarted;
                const convertStarted = performance.now();
                this.scene = galaxySceneToV2(scene, this.sourceMode);
                const sceneConvertMs = performance.now() - convertStarted;
                if (!this.renderer.hasContext()) this.ensureRendererMounted();
                const setSceneStarted = performance.now();
                this.renderer.setScene(this.scene);
                const rendererSetSceneMs = performance.now() - setSceneStarted;
                this.renderer.setSettings(this.settings);
                this.renderer.setMode(this.viewMode === 'map' ? '2d' : '3d');
                graphGalaxyRuntimeMeter.recordScene(this.meterId, scene.nodes.length, scene.links.length);
                this.recordRendererTimings({
                    sceneCompileMs,
                    sceneConvertMs,
                    rendererSetSceneMs,
                    sceneBuildMs: performance.now() - buildStarted,
                });
                this.draw();
            })
            .catch((error) => console.error('[GraphGalaxyCanvas] Scene compile failed:', error))
            .finally(() => {
                this.sceneBuildPromise = null;
                if (!this.destroyed && (this.needsLayout || this.layoutVersion !== version)) this.requestSceneBuild();
            });
    }

    private updateHover(event: MouseEvent): void {
        this.setHover(this.pickObject(event));
    }

    private currentSettings(): GalaxyRenderSettings {
        return this.mergeSettingsForSource(this.settings);
    }

    private mergeSettingsForSource(settings: Partial<GalaxyRenderSettings> | null | undefined): GalaxyRenderSettings {
        return mergeGalaxySettings({ ...settings, sourceMode: this.sourceMode });
    }

    private setHover(hit: GraphCanvasHit | null): void {
        const key = hit ? `${hit.kind}:${hit.id}` : null;
        if (this.hoverKey === key) return;
        this.hoverKey = key;
        const nodeId = hit?.kind === 'node' ? hit.id : null;
        this.renderer.hoverNode(nodeId);
        this.recordRendererTimings();
        this.draw();
        const entity = nodeId ? this.entities.find((item) => item.id === nodeId || item.metadata?.sourceEntityId === nodeId) ?? null : null;
        this.entityHovered.emit(entity);
        this.objectHovered.emit(hit);
    }

    private pick(event: MouseEvent): string | null {
        const id = this.renderer.pick(this.pointerFromEvent(event));
        this.recordRendererTimings();
        return id;
    }

    private pickObject(event: MouseEvent): GraphCanvasHit | null {
        const hit = this.renderer.pickObject(this.pointerFromEvent(event));
        this.recordRendererTimings();
        return hit;
    }

    private recordRendererTimings(extra: Partial<GraphGalaxyCanvasTimings> = {}): void {
        graphGalaxyRuntimeMeter.recordTimings(this.meterId, {
            ...this.renderer.snapshotTimings(),
            ...extra,
        });
    }

    private pointerFromEvent(event: MouseEvent): { x: number; y: number; width: number; height: number } {
        const rect = this.canvasRef.nativeElement.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top, width: rect.width, height: rect.height };
    }
}

export function galaxySettingsNeedSceneRebuild(previous: GalaxyRenderSettings, current: GalaxyRenderSettings): boolean {
    return previous.layoutMode !== current.layoutMode ||
        previous.embeddingTopologyMode !== current.embeddingTopologyMode ||
        previous.nodeDistance !== current.nodeDistance ||
        previous.edgeLength !== current.edgeLength ||
        previous.edgeCurveStrength !== current.edgeCurveStrength;
}
