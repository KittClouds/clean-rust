import { AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, inject, Input, OnChanges, OnDestroy, Output, SimpleChanges, ViewChild } from '@angular/core';

import { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { compileAuthoritativeGalaxyScene, compileGalaxyScene } from './graph-galaxy-scene-compiler';
import { graphGalaxyRuntimeMeter, type GraphGalaxyCanvasTimings } from './graph-galaxy-runtime-meter';
import { budgetGalaxySurface } from './graph-galaxy-surface-budget';
import type { GalaxySceneSourceMode, GalaxySceneV2 } from './graph-galaxy-scene-v2';
import { mergeGalaxySettings, type GalaxyInputEdge, type GalaxyQueryFocus, type GalaxyRenderableNode, type GalaxyRenderSettings } from './graph-galaxy-engine';
import { ThreeGalaxyRenderer } from './three-galaxy-renderer';
import type { GraphCanvasHit } from './graph-canvas-interaction';
import { pathSelectionLocksCanvasFocus } from './graph-path-selection';
import type { GalaxySceneResidencyController } from './graph-galaxy-scene-residency-controller';
import type { GalaxyResidencyCounters } from './graph-galaxy-residency.model';
import type { GalaxyInteractionQueryController } from './graph-galaxy-interaction-query';
import type { GalaxyInteractionAuthority } from './graph-galaxy-interaction.model';

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
            @if (residencyCounters.generationId) {
            <div class="residency-meter" aria-label="Galaxy residency counters">
                <span><b>corpus</b>{{ residencyTotal(residencyCounters.corpus) }}</span>
                <span><b>resident</b>{{ residencyTotal(residencyCounters.resident) }}</span>
                <span><b>visible</b>{{ residencyTotal(residencyCounters.visible) }}</span>
                <span><b>drawn</b>{{ residencyTotal(residencyCounters.drawn) }}</span>
                <span><b>aggregated</b>{{ residencyTotal(residencyCounters.aggregated) }}</span>
            </div>
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
        .residency-meter { position: absolute; left: 12px; bottom: 10px; z-index: 7; display: flex; gap: 10px; pointer-events: none; color: rgba(203,213,225,.68); font: 600 9px/1.1 ui-monospace, monospace; letter-spacing: .06em; text-transform: uppercase; }
        .residency-meter span { display: inline-flex; gap: 4px; padding: 5px 7px; border: 1px solid rgba(71,85,105,.26); border-radius: 5px; background: rgba(2,6,14,.62); backdrop-filter: blur(7px); }
        .residency-meter b { color: rgba(94,234,212,.76); font-weight: 700; }
    `],
})
export class GraphGalaxyCanvasComponent implements AfterViewInit, OnChanges, OnDestroy {
    private readonly phoenix = inject(PhoenixBackendService);
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
    @Output() entitySelected = new EventEmitter<GalaxyRenderableNode>();
    @Output() entityHovered = new EventEmitter<GalaxyRenderableNode | null>();
    @Output() objectSelected = new EventEmitter<GraphCanvasHit>();
    @Output() objectHovered = new EventEmitter<GraphCanvasHit | null>();
    @Output() batchSelected = new EventEmitter<string[]>();
    @ViewChild('canvas', { static: true }) private canvasRef!: ElementRef<HTMLCanvasElement>;

    private readonly renderer = new ThreeGalaxyRenderer();
    residencyCounters: GalaxyResidencyCounters = emptyGalaxyResidencyCounters();
    private residency: GalaxySceneResidencyController | null = null;
    private residencyLoad: Promise<GalaxySceneResidencyController> | null = null;
    private pendingResidencyCounters: GalaxyResidencyCounters | null = null;
    private residencyCounterFlushQueued = false;
    private interaction: GalaxyInteractionQueryController | null = null;
    private interactionLoad: Promise<GalaxyInteractionQueryController> | null = null;
    private resizeObserver?: ResizeObserver;
    private intersectionObserver?: IntersectionObserver;
    private frameId = 0;
    private hoverFrameId = 0;
    private pendingHoverPointer: { x: number; y: number; width: number; height: number } | null = null;
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
            if (this.renderer.hasContext()) this.renderer.setSettings(current);
            if (galaxySettingsNeedSceneRebuild(previous, current)) this.markLayoutDirty();
            if (this.viewReady) this.syncSurface();
        }
        const collectionChanged = Boolean(changes['entities'] || changes['edges']);
        const identityChanged = galaxySceneIdentityNeedsRebuild(
            changes['sceneIdentity']?.previousValue || '',
            this.sceneIdentity,
            collectionChanged,
        );
        if (identityChanged || changes['sourceMode']) this.markLayoutDirty();
        if (changes['selectedEntityIds'] && this.renderer.hasContext()) {
            this.renderer.selectNodes(this.selectedEntityIds);
            void this.refreshPathOverlay();
            this.recordRendererTimings();
        }
        if (changes['viewMode'] && this.renderer.hasContext()) this.renderer.setMode(this.viewMode === 'map' ? '2d' : '3d');
        if (changes['surfaceActive'] && this.viewReady) this.syncSurface();
    }

    ngOnDestroy(): void {
        this.destroyed = true;
        if (this.hoverFrameId) cancelAnimationFrame(this.hoverFrameId);
        this.hoverFrameId = 0;
        this.pendingHoverPointer = null;
        this.stop();
        graphGalaxyRuntimeMeter.unregisterCanvas(this.meterId);
        this.resizeObserver?.disconnect();
        this.intersectionObserver?.disconnect();
        document.removeEventListener('visibilitychange', this.onVisibilityChange);
        this.unsubscribeColors?.();
        this.interaction?.dispose();
        this.residency?.dispose();
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

    residencyTotal(counts: { nodes: number; edges: number }): number {
        return counts.nodes + counts.edges;
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
            this.scheduleHover(event);
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

    async onPointerUp(): Promise<void> {
        const lassoRect = this.lassoSelecting ? this.lassoRect : null;
        const relax = this.nodeDragging && this.renderer.endNodeDrag();
        this.dragging = false;
        this.nodeDragging = false;
        this.panning = false;
        this.lassoSelecting = false;
        this.lassoStart = null;
        this.lassoRect = null;
        if (relax) this.start();
        this.syncSurface();
        if (lassoRect && this.scene) {
            const interaction = await this.ensureInteraction();
            const ids = await interaction.region(
                this.scene,
                this.interactionAuthority(this.scene),
                lassoRect,
                this.renderer.interactionViewProjection(),
                () => this.renderer.nodesInRect(lassoRect),
            );
            if (!this.destroyed) this.batchSelected.emit(ids);
        }
    }

    onPointerLeave(): void {
        if (this.hoverFrameId) cancelAnimationFrame(this.hoverFrameId);
        this.hoverFrameId = 0;
        this.pendingHoverPointer = null;
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
            this.suspendSurface();
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
        if (this.renderer.hasContext()) this.residency?.updateView(this.renderer.residencyView());
        graphGalaxyRuntimeMeter.recordDraw(this.meterId, budget.backingWidth / budget.dpr, budget.backingHeight / budget.dpr, budget.dpr, performance.now(), 0);
    }

    private suspendSurface(): void {
        this.stop();
    }

    private ensureRendererMounted(): void {
        const canvas = this.canvasRef.nativeElement;
        const created = this.renderer.mount(canvas);
        if (!created) return;
        graphGalaxyRuntimeMeter.recordContext(this.meterId, true);
        if (this.scene) {
            const setSceneStarted = performance.now();
            this.renderer.installScene(
                this.scene,
                this.currentSettings(),
                this.viewMode === 'map' ? '2d' : '3d',
                this.selectedEntityIds,
            );
            this.recordRendererTimings({ rendererSetSceneMs: performance.now() - setSceneStarted });
            this.recordDrawMetrics();
            return;
        }
        this.renderer.setSettings(this.currentSettings());
        this.renderer.setMode(this.viewMode === 'map' ? '2d' : '3d');
    }

    private draw(): void {
        if (!this.canHoldSurface()) return;
        this.residency?.updateView(this.renderer.residencyView());
        this.renderer.render();
        this.recordRendererTimings();
        this.recordDrawMetrics();
    }

    private recordDrawMetrics(): void {
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
        const compile = this.sceneIdentity ? compileAuthoritativeGalaxyScene : compileGalaxyScene;
        this.sceneBuildPromise = compile(
            this.phoenix,
            this.entities,
            this.edges,
            this.currentSettings(),
            this.sceneIdentity,
            this.sourceMode,
        )
            .then(async (scene) => {
                if (this.destroyed || this.layoutVersion !== version) return;
                const sceneCompileMs = performance.now() - buildStarted;
                const sceneConvertMs = 0;
                const setSceneStarted = performance.now();
                if (!this.renderer.hasContext()) this.ensureRendererMounted();
                const residency = await this.ensureResidency();
                await residency.install({
                    generationId: galaxyResidencyGenerationId(this.sceneIdentity),
                    authorityReceipt: this.sceneIdentity || 'ephemeral:unreceipted-current-graph',
                    corpus: { nodes: this.entities.length, edges: this.edges.length },
                    payload: {
                        scene,
                        settings: this.currentSettings(),
                        mode: this.viewMode === 'map' ? '2d' : '3d',
                        selectedIds: this.selectedEntityIds,
                    },
                });
                const rendererSetSceneMs = performance.now() - setSceneStarted;
                graphGalaxyRuntimeMeter.recordScene(
                    this.meterId,
                    scene.ids.length,
                    scene.edgePairs.length / 2,
                    scene.layoutMode,
                    this.sceneIdentity || 'ephemeral:unreceipted-current-graph',
                );
                this.recordRendererTimings({
                    sceneCompileMs,
                    sceneConvertMs,
                    rendererSetSceneMs,
                    sceneBuildMs: performance.now() - buildStarted,
                });
                this.recordDrawMetrics();
            })
            .catch((error) => console.error('[GraphGalaxyCanvas] Scene compile failed:', error))
            .finally(() => {
                this.sceneBuildPromise = null;
                if (!this.destroyed && (this.needsLayout || this.layoutVersion !== version)) this.requestSceneBuild();
            });
    }

    private scheduleHover(event: MouseEvent): void {
        this.pendingHoverPointer = this.pointerFromEvent(event);
        if (this.hoverFrameId) return;
        this.hoverFrameId = requestAnimationFrame(() => {
            this.hoverFrameId = 0;
            const pointer = this.pendingHoverPointer;
            this.pendingHoverPointer = null;
            if (!pointer || this.destroyed) return;
            this.setHover(this.pickObjectAt(pointer));
        });
    }

    private ensureResidency(): Promise<GalaxySceneResidencyController> {
        if (this.residency) return Promise.resolve(this.residency);
        if (this.residencyLoad) return this.residencyLoad;
        this.residencyLoad = import('./graph-galaxy-scene-residency-controller')
            .then(({ GalaxySceneResidencyController }) => {
                const controller = new GalaxySceneResidencyController({
                    activate: ({ scene, settings, mode, selectedIds }) => {
                        this.scene = scene;
                        if (!this.renderer.hasContext()) this.ensureRendererMounted();
                        else this.renderer.installScene(scene, settings, mode, selectedIds);
                        void this.refreshPathOverlay();
                    },
                    counters: (counters) => {
                        this.queueResidencyCounters(counters);
                    },
                });
                if (this.destroyed) controller.dispose();
                this.residency = controller;
                return controller;
            });
        return this.residencyLoad;
    }

    private queueResidencyCounters(counters: GalaxyResidencyCounters): void {
        this.pendingResidencyCounters = counters;
        if (this.residencyCounterFlushQueued) return;
        this.residencyCounterFlushQueued = true;
        queueMicrotask(() => {
            this.residencyCounterFlushQueued = false;
            const pending = this.pendingResidencyCounters;
            this.pendingResidencyCounters = null;
            if (!pending || this.destroyed) return;
            this.residencyCounters = pending;
            this.changeDetector.markForCheck();
        });
    }

    private ensureInteraction(): Promise<GalaxyInteractionQueryController> {
        if (this.interaction) return Promise.resolve(this.interaction);
        if (this.interactionLoad) return this.interactionLoad;
        this.interactionLoad = import('./graph-galaxy-interaction-query')
            .then(({ GalaxyInteractionQueryController }) => {
                const controller = new GalaxyInteractionQueryController();
                if (this.destroyed) controller.dispose();
                this.interaction = controller;
                return controller;
            });
        return this.interactionLoad;
    }

    private async refreshPathOverlay(): Promise<void> {
        const scene = this.scene;
        const [sourceNodeId, targetNodeId] = this.selectedEntityIds;
        if (!scene || !sourceNodeId || !targetNodeId) {
            this.renderer.setPathOverlay(null);
            return;
        }
        const interaction = await this.ensureInteraction();
        const overlay = await interaction.path(
            scene,
            this.interactionAuthority(scene),
            sourceNodeId,
            targetNodeId,
        );
        if (
            this.destroyed
            || this.scene !== scene
            || this.selectedEntityIds[0] !== sourceNodeId
            || this.selectedEntityIds[1] !== targetNodeId
        ) {
            return;
        }
        this.renderer.setPathOverlay(overlay);
        this.draw();
    }

    private interactionAuthority(scene: GalaxySceneV2): GalaxyInteractionAuthority {
        const generationId = galaxyResidencyGenerationId(this.sceneIdentity);
        return {
            generationId,
            manifoldId: scene.layoutMode,
            authorityReceipt: this.sceneIdentity || generationId,
        };
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
        if (!pathSelectionLocksCanvasFocus(this.selectedEntityIds)) {
            this.renderer.hoverNode(nodeId);
            this.recordRendererTimings();
            this.draw();
        }
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
        return this.pickObjectAt(this.pointerFromEvent(event));
    }

    private pickObjectAt(pointer: { x: number; y: number; width: number; height: number }): GraphCanvasHit | null {
        const hit = this.renderer.pickObject(pointer);
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
        previous.sourceMode !== current.sourceMode ||
        previous.embeddingTopologyMode !== current.embeddingTopologyMode ||
        previous.nodeDistance !== current.nodeDistance ||
        previous.edgeLength !== current.edgeLength ||
        previous.edgeCurveStrength !== current.edgeCurveStrength;
}

export function galaxySceneIdentityNeedsRebuild(
    previousIdentity: string,
    currentIdentity: string,
    collectionsChanged: boolean,
): boolean {
    if (previousIdentity !== currentIdentity) return true;
    return !currentIdentity && collectionsChanged;
}

export function galaxyResidencyGenerationId(sceneIdentity: string): string {
    return sceneIdentity.split('\u0000', 1)[0] || 'ephemeral-current-graph';
}

function emptyGalaxyResidencyCounters(): GalaxyResidencyCounters {
    return {
        generationId: '',
        manifoldId: '',
        transitioning: false,
        corpus: { nodes: 0, edges: 0 },
        resident: { nodes: 0, edges: 0 },
        visible: { nodes: 0, edges: 0 },
        drawn: { nodes: 0, edges: 0 },
        aggregated: { nodes: 0, edges: 0 },
        residentBytes: 0,
        residentTiles: 0,
        queuedTiles: 0,
        inFlightTiles: 0,
    };
}
