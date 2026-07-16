import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnDestroy, OnInit, Output, ViewChild, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Plus, ScanSearch, Search, Settings2, SlidersHorizontal, Zap } from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import { entitySourceSystem, type RegisteredEntity } from '../../../../../lib/registry';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import type { EntitySuggestionProviderId } from '../../../../../lib/entity-suggestions/entity-suggestion.types';
import { PhoenixUiApiService } from '../../../../../services/phoenix-ui-api.service';
import { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import { PhoenixMachineControlService } from '../../../../../services/phoenix-machine-control.service';
import type { AtlasManifoldMode } from '../../../../../services/manifold-atlas.types';
import { buildAtlasCountReconciliation } from '../../../../../services/atlas-count-ledger.model';
import { BlueprintHubService } from '../../../blueprint-hub.service';
import type { GraphRebuildCounters, GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { buildGraphProjectionContractReport } from '../../../../../graph-rebuild/graph-projection-contract-report';
import { type EmbeddingAtlasData, type EmbeddingQueryTrace, type EmbeddingSourcePreview } from './graph-embedding-atlas';
import { manifoldAdapter } from './graph-manifold-atlas';
import { cachedGraphRebuildEmbeddingAtlas, graphRebuildEmbeddingTargetCount } from './graph-rebuild-embedding-atlas';
import { loadManifoldProjection, manifoldProjectionRequestKey } from './graph-manifold-projection-loader';
import {
    completeRegistryEntityProjection,
    registryEntityKindOrder,
    registryEntityProjectionPoint,
    REGISTRY_ENTITY_PROJECTION_SPACE,
} from './graph-registry-entity-projection';
import { GraphGalaxyCanvasComponent } from './graph-galaxy-canvas.component';
import { compileGalaxyScene } from './graph-galaxy-scene-compiler';
import { GraphCanvasInspectorComponent } from './graph-canvas-inspector.component';
import { boundedPathSelection, nextPathSelection } from './graph-path-selection';
import {
    buildCanvasSearchFocus,
    filterGraphForCanvasLens,
    graphCanvasBatchRecords,
    graphCanvasInspectorRecord,
    type GraphCanvasHit,
    type GraphCanvasLens,
    type GraphCanvasSourceRequest,
} from './graph-canvas-interaction';
import {
    isTransitLayoutMode,
    mergeGalaxySettings,
    type GalaxyBackgroundMode,
    type GalaxyEmbeddingTopologyMode,
    type GalaxyEdgeColorMode,
    type GalaxyEdgeMode,
    type GalaxyInputEdge,
    type GalaxyLabelMode,
    type GalaxyLayoutMode,
    type GalaxyNodeDragMode,
    type GalaxyNodeShapeMode,
    type GalaxyRenderableNode,
    type GalaxyRenderSettings,
    type GalaxySphereSurfaceMode,
} from './graph-galaxy-engine';
import type { GraphLensMode, GraphLensState } from '../graph-lens';
import { buildGraphAtlasReadContext, graphLensState, type GraphAtlasReadContext } from './graph-atlas-read-context';
import { projectionSummaryRequestsRefresh } from './graph-atlas-refresh-summary';
import { getSetting, setSetting } from '../../../../../lib/dexie/settings.service';
import { buildGraphCanvasInventory } from './graph-canvas-inventory';
import { graphSnapshotRenderIdentity } from '../graph-render-identity';
import { graphProjectionParityApplies, graphProjectionParitySlice } from './graph-projection-parity';

export interface AtlasPreviewEdge extends GalaxyInputEdge {}

const SPHERE_SURFACE_CYCLE: readonly GalaxySphereSurfaceMode[] = [
    'solid',
    'glass',
    'spellglass',
    'obsidian',
    'starcore',
];
const SPHERE_SURFACE_LABELS: Record<GalaxySphereSurfaceMode, string> = {
    solid: 'A - solid',
    glass: 'B - aurora',
    spellglass: 'C - spellglass',
    obsidian: 'D - obsidian',
    starcore: 'E - starcore',
};

interface ActiveAtlasGraph {
    mode: AtlasMode;
    entities: GalaxyRenderableNode[];
    edges: AtlasPreviewEdge[];
    atlas: EmbeddingAtlasData;
    trace: EmbeddingQueryTrace | null;
    graphInventory: GraphInventory;
    graphKindFilter: string;
    canvasLens: GraphCanvasLens;
    nodes: GalaxyRenderableNode[];
    graphEdges: AtlasPreviewEdge[];
}

export type AtlasMode = 'entities' | 'graph' | 'embeddings';
type AtlasViewMode = '3d' | 'map';

interface PersistedAtlasViewState {
    atlasMode: AtlasMode;
    viewMode: AtlasViewMode;
    manifoldMode: AtlasManifoldMode;
    settings: Partial<GalaxyRenderSettings>;
    graphKindFilter: string;
    canvasLens: GraphCanvasLens;
    controlsCollapsed: boolean;
}

interface HopfReceiptSummary {
    assignments: number;
    occupiedCells: number;
    docCharts: number;
    braids: number;
}

const GRAPH_ATLAS_VIEW_STATE_KEY = 'graph.atlas.viewState.v1';
const ATLAS_MODES = new Set<AtlasMode>(['entities', 'graph', 'embeddings']);
const ATLAS_VIEW_MODES = new Set<AtlasViewMode>(['3d', 'map']);
const ATLAS_MANIFOLD_MODE_LIST: readonly AtlasManifoldMode[] = ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'];
const ATLAS_MANIFOLD_MODES = new Set<AtlasManifoldMode>(ATLAS_MANIFOLD_MODE_LIST);
const CANVAS_LENSES = new Set<GraphCanvasLens>(['entities', 'structure', 'facts', 'discourse', 'accepted', 'proposed']);

export interface GraphInventory {
    nodes: GalaxyRenderableNode[];
    edges: AtlasPreviewEdge[];
    kindCounts: Array<{ kind: string; count: number }>;
    sourceLabel: string;
}

export const EMPTY_GRAPH_INVENTORY: GraphInventory = { nodes: [], edges: [], kindCounts: [], sourceLabel: 'graph rebuild snapshot' };

function readPersistedAtlasViewState(): PersistedAtlasViewState {
    const stored = getSetting<Partial<PersistedAtlasViewState>>(GRAPH_ATLAS_VIEW_STATE_KEY, {});
    const atlasMode = ATLAS_MODES.has(stored.atlasMode as AtlasMode) ? stored.atlasMode as AtlasMode : 'graph';
    const viewMode = ATLAS_VIEW_MODES.has(stored.viewMode as AtlasViewMode) ? stored.viewMode as AtlasViewMode : '3d';
    const manifoldMode = ATLAS_MANIFOLD_MODES.has(stored.manifoldMode as AtlasManifoldMode)
        ? stored.manifoldMode as AtlasManifoldMode
        : 'hybrid';
    return {
        atlasMode,
        viewMode,
        manifoldMode,
        settings: stored.settings && typeof stored.settings === 'object' ? stored.settings : {},
        graphKindFilter: typeof stored.graphKindFilter === 'string' && stored.graphKindFilter ? stored.graphKindFilter : 'all',
        canvasLens: CANVAS_LENSES.has(stored.canvasLens as GraphCanvasLens) ? stored.canvasLens as GraphCanvasLens : 'entities',
        controlsCollapsed: stored.controlsCollapsed === true,
    };
}

@Component({
    selector: 'app-graph-atlas-preview',
    standalone: true,
    imports: [CommonModule, FormsModule, LucideAngularModule, GraphGalaxyCanvasComponent, GraphCanvasInspectorComponent],
    template: `
        <section class="atlas-preview-surface relative h-full min-h-[520px] overflow-hidden rounded-none border border-white/5 bg-[#02040a] shadow-[0_24px_80px_rgba(0,0,0,0.24)]" [attr.data-backdrop]="settings.backgroundMode">
            <div class="relative z-10 flex h-full min-h-[520px] flex-col p-px">
                <div class="pointer-events-none absolute left-3 right-3 top-3 z-30 flex items-start justify-between gap-2">
                    <div class="canvas-control-zone flex min-w-0 items-start gap-2 overflow-hidden">
                        <button type="button"
                            class="canvas-chrome-toggle"
                            [class.canvas-chrome-toggle-active]="controlsCollapsed"
                            [attr.aria-label]="controlsCollapsed ? 'Show atlas controls' : 'Hide atlas controls'"
                            (click)="toggleControlsCollapsed()">
                            <lucide-icon [img]="SlidersIcon" class="h-4 w-4"></lucide-icon>
                        </button>
                    @if (!controlsCollapsed) {
                    <div class="canvas-control-rail flex min-w-0 flex-nowrap items-center gap-2 overflow-x-auto rounded-2xl px-2 py-1.5">
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-cyan-500/15]="atlasMode === 'entities'" [class.text-cyan-100]="atlasMode === 'entities'"
                                [class.text-zinc-500]="atlasMode !== 'entities'" (click)="setAtlasMode('entities')">Entities</button>
                            <button type="button" class="rounded-lg px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-cyan-500/15]="atlasMode === 'graph'" [class.text-cyan-100]="atlasMode === 'graph'"
                                [class.text-zinc-500]="atlasMode !== 'graph'" (click)="setAtlasMode('graph')">Graph</button>
                            <button type="button" class="rounded-lg px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-cyan-500/15]="atlasMode === 'embeddings'" [class.text-cyan-100]="atlasMode === 'embeddings'"
                                [class.text-zinc-500]="atlasMode !== 'embeddings'" (click)="setAtlasMode('embeddings')">Embed</button>
                        </div>
                        <div class="atlas-status-rail" aria-label="Atlas status summary">
                            <span class="atlas-status-token atlas-status-token-strong" [title]="primaryCountLabel() + ' ' + activeNodeCount()">{{ primaryCountLabel() }} {{ activeNodeCount() }}</span>
                            <span class="atlas-status-token" [title]="secondaryCountLabel() + ' ' + activeEdgeCount()">{{ secondaryCountLabel() }} {{ activeEdgeCount() }}</span>
                            <span class="atlas-status-token atlas-status-token-source" [title]="'Source: ' + dataSourceLabel()">{{ dataSourceLabel() }}</span>
                            @if (projectionContract(); as contract) {
                            <span class="atlas-status-token atlas-status-token-contract" [title]="'Contract: ' + contract.pipelineLabel + ' / ' + contract.semanticCoordinatesLabel + ' / ' + contract.parityLabel">{{ contract.pipelineLabel }} / {{ contract.parityLabel }}</span>
                            }
                            @if (atlasMode === 'graph') {
                            <span class="atlas-status-token" [title]="'Anchors ' + graphAnchorCount()">anchors {{ graphAnchorCount() }}</span>
                            <span class="atlas-status-token" [title]="'Chunks ' + graphChunkCount()">chunks {{ graphChunkCount() }}</span>
                            <span class="atlas-status-token" [title]="'Accepted ' + graphAcceptedRelationshipCount()">accepted {{ graphAcceptedRelationshipCount() }}</span>
                            <span class="atlas-status-token" [title]="'Review ' + graphReviewRelationshipCount()">review {{ graphReviewRelationshipCount() }}</span>
                            <span class="atlas-status-token" [title]="'Drops ' + graphDropCount()">drops {{ graphDropCount() }}</span>
                            }
                            @if (atlasMode === 'embeddings') {
                            <span class="atlas-status-token" [title]="'Input graph: ' + semanticGraphAvailabilityLabel()">input {{ semanticGraphAvailabilityLabel() }}</span>
                            @if (!usesGraphRebuildEmbeddingAtlas()) {
                            <span class="atlas-status-token" [title]="'Registry anchors ' + registryAnchorCount()">registry anchors {{ registryAnchorCount() }}</span>
                            <span class="atlas-status-token" [title]="'Projection sidecar nodes ' + projectionSidecarNodeCount()">sidecar nodes {{ projectionSidecarNodeCount() }}</span>
                            }
                            }
                            @if (hopfReceiptSummary(); as hopf) {
                            <span class="atlas-status-token atlas-status-token-source" [title]="'Hopf receipts ' + hopf.assignments + ' / ' + hopf.occupiedCells + ' cells / ' + hopf.docCharts + ' charts / ' + hopf.braids + ' braids'">hopf {{ hopf.assignments }} / {{ hopf.occupiedCells }}</span>
                            }
                        </div>
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-cyan-500/15]="viewMode === '3d'" [class.text-cyan-100]="viewMode === '3d'"
                                [class.text-zinc-500]="viewMode !== '3d'" (click)="setViewMode('3d')">3D</button>
                            <button type="button" class="rounded-lg px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-cyan-500/15]="viewMode === 'map'" [class.text-cyan-100]="viewMode === 'map'"
                                [class.text-zinc-500]="viewMode !== 'map'" (click)="setViewMode('map')">Map</button>
                        </div>
                        <div class="flex shrink-0 items-center gap-2">
                            <button type="button" class="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-semibold text-zinc-200 transition hover:border-cyan-400/20 hover:bg-cyan-500/10"
                                (click)="resetCamera()">Reset</button>
                            <button type="button" class="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-semibold text-zinc-200 transition hover:border-cyan-400/20 hover:bg-cyan-500/10"
                                (click)="fitCamera()">Fit</button>
                        </div>
                    </div>
                    }
                    </div>

                    <div class="flex shrink-0 items-start gap-1.5">
                        <div class="relative">
                            <button type="button"
                                class="canvas-glass-button rounded-xl px-2 py-1.5 text-[10px] font-semibold"
                                [attr.title]="lensLabel() + ' lens'"
                                (click)="toggleLensMenu()">
                                {{ lensLabel() }}
                            </button>
                            @if (lensMenuOpen) {
                            <div class="pointer-events-auto absolute right-0 top-10 w-44 rounded-2xl border border-white/10 bg-black/55 p-2 text-xs shadow-2xl backdrop-blur">
                                @for (mode of lensModes; track mode.id) {
                                <button type="button" class="lens-menu-button" [class.lens-menu-button-active]="lensMode === mode.id"
                                    (click)="chooseLens(mode.id)">
                                    {{ mode.label }}
                                </button>
                                }
                            </div>
                            }
                        </div>
                        <button type="button"
                            class="canvas-glass-button inline-flex h-[34px] w-[34px] items-center justify-center rounded-xl"
                            aria-label="Open atlas settings" title="Settings"
                            (click)="toggleSettings()">
                            <lucide-icon [img]="SettingsIcon" class="h-4 w-4"></lucide-icon>
                        </button>
                    </div>
                </div>

                <div class="atlas-canvas-surface relative min-h-0 flex-1 overflow-hidden rounded-none border border-white/5 bg-[#02040a] p-px">
                    @if (atlasMode === 'graph') {
                    <div class="canvas-lens-rail pointer-events-auto absolute left-4 top-16 z-30 flex flex-wrap items-center gap-1 border border-white/10 bg-black/65 p-1 shadow-xl backdrop-blur" aria-label="Graph object lens">
                        @for (lens of canvasLenses; track lens.id) {
                        <button type="button" class="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] transition"
                            [class.bg-teal-500/15]="canvasLens() === lens.id"
                            [class.text-teal-100]="canvasLens() === lens.id"
                            [class.text-zinc-500]="canvasLens() !== lens.id"
                            (click)="setCanvasLens(lens.id)">{{ lens.label }}</button>
                        }
                        <button type="button" class="canvas-chrome-toggle"
                            [class.canvas-chrome-toggle-active]="lassoEnabled()"
                            title="Lasso select" aria-label="Toggle lasso selection"
                            (click)="toggleLasso()">
                            <lucide-icon [img]="LassoIcon" class="h-4 w-4"></lucide-icon>
                        </button>
                    </div>
                    }
                    @if (atlasMode === 'graph' || atlasMode === 'embeddings') {
                    <div class="canvas-projection-rail pointer-events-auto absolute left-4 top-16 z-30 flex flex-wrap items-center gap-0.5 overflow-x-auto border border-white/10 bg-black/65 p-0.5 shadow-xl backdrop-blur"
                        [class.canvas-projection-rail-top]="controlsCollapsed && atlasMode === 'embeddings'"
                        [class.canvas-projection-rail-graph]="atlasMode === 'graph'"
                        [attr.aria-label]="atlasMode === 'graph' ? 'Graph manifold layout' : 'Embedding manifold projection'">
                        <div class="flex border-r border-white/10 pr-1">
                            <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'hybrid'" [class.text-violet-100]="manifoldMode() === 'hybrid'"
                                [class.text-zinc-500]="manifoldMode() !== 'hybrid'" (click)="setManifoldMode('hybrid')">Hybrid</button>
                            <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'hopf'" [class.text-violet-100]="manifoldMode() === 'hopf'"
                                [class.text-zinc-500]="manifoldMode() !== 'hopf'" (click)="setManifoldMode('hopf')">Hopf</button>
                            <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'lorentz'" [class.text-violet-100]="manifoldMode() === 'lorentz'"
                                [class.text-zinc-500]="manifoldMode() !== 'lorentz'" (click)="setManifoldMode('lorentz')">Caps</button>
                            <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'product'" [class.text-violet-100]="manifoldMode() === 'product'"
                                [class.text-zinc-500]="manifoldMode() !== 'product'" (click)="setManifoldMode('product')">Transit</button>
                            <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'siegel'" [class.text-violet-100]="manifoldMode() === 'siegel'"
                                [class.text-zinc-500]="manifoldMode() !== 'siegel'" (click)="setManifoldMode('siegel')">Siegel</button>
                        </div>
                        @if (manifoldMode() === 'hybrid') {
                        <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                            [class.bg-cyan-500/15]="settings.layoutMode === 'hybridSpace'" [class.text-cyan-100]="settings.layoutMode === 'hybridSpace'"
                            [class.text-zinc-500]="settings.layoutMode !== 'hybridSpace'" (click)="setLayoutMode('hybridSpace')">Shell</button>
                        <button type="button" class="px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] transition"
                            [class.bg-cyan-500/15]="settings.layoutMode === 'multiGalaxy'" [class.text-cyan-100]="settings.layoutMode === 'multiGalaxy'"
                            [class.text-zinc-500]="settings.layoutMode !== 'multiGalaxy'" (click)="setLayoutMode('multiGalaxy')">Multi</button>
                        } @else if (manifoldMode() === 'hopf') {
                        <button type="button" class="bg-cyan-500/15 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-cyan-100 transition"
                            (click)="setLayoutMode('hopfProjection')">Projection</button>
                        } @else if (manifoldMode() === 'lorentz') {
                        <button type="button" class="bg-cyan-500/15 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-cyan-100 transition"
                            (click)="setLayoutMode('lorentzTree')">Caps</button>
                        } @else if (manifoldMode() === 'siegel') {
                        <button type="button" class="bg-cyan-500/15 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-cyan-100 transition"
                            (click)="setLayoutMode('siegelFinsler')">Finsler</button>
                        } @else {
                        <button type="button" class="bg-cyan-500/15 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-cyan-100 transition"
                            (click)="setLayoutMode('transitManifold')">Transit</button>
                        }
                    </div>
                    }
                    @if (activeNodeCount() === 0) {
                    <div class="flex h-full min-h-[430px] items-center justify-center rounded-none border border-dashed border-white/10 text-center">
                        <div>
                            <p class="text-lg font-semibold text-white">{{ emptyTitle() }}</p>
                            <p class="mt-2 max-w-md text-sm leading-6 text-zinc-500">{{ emptyMessage() }}</p>
                        </div>
                    </div>
                    } @else {
                    <app-graph-galaxy-canvas #galaxyCanvas class="block h-full min-h-0 w-full"
                        [entities]="activeNodes()" [edges]="activeEdges()" [settings]="settings" [selectedEntityIds]="canvasSelectedNodeIds()"
                        [sceneIdentity]="activeSceneIdentity()"
                        [queryFocus]="canvasQueryFocus()" [viewMode]="viewMode" [sourceMode]="atlasMode" [surfaceActive]="isAtlasSurfaceActive()"
                        [lassoEnabled]="lassoEnabled()"
                        (entityHovered)="hoveredEntity = $event"
                        (objectSelected)="onCanvasObjectSelected($event)" (objectHovered)="hoveredCanvasHit.set($event)"
                        (batchSelected)="onCanvasBatchSelected($event)"></app-graph-galaxy-canvas>
                    @if (settings.detailCardsVisible) {
                    <app-graph-canvas-inspector
                        [record]="canvasInspectorRecord()"
                        [batchRecords]="canvasBatchRecords()"
                        (close)="closeCanvasInspector()"
                        (focusRequested)="focusCanvasNodes($event)"
                        (styleRequested)="styleRequested.emit($event)"
                        (sourceRequested)="sourceRequested.emit($event)">
                    </app-graph-canvas-inspector>
                    }
                    @if ((!settings.detailCardsVisible || (!canvasInspectorRecord() && canvasBatchRecords().length === 0)) && canvasHoverRecord(); as hover) {
                    <div class="pointer-events-none absolute bottom-20 left-4 z-30 max-w-[320px] border border-teal-300/20 bg-black/75 px-3 py-2 text-xs shadow-2xl backdrop-blur">
                        <div class="flex items-center justify-between gap-3">
                            <strong class="truncate text-zinc-100">{{ hover.title }}</strong>
                            @if (hover.confidence !== null) { <span class="text-teal-200">{{ hover.confidence | percent:'1.0-0' }}</span> }
                        </div>
                        <p class="mt-1 line-clamp-2 text-zinc-400">{{ hover.sourceSnippet || hover.subtitle }}</p>
                    </div>
                    }
                    @if (atlasMode === 'graph') {
                    <div class="absolute bottom-4 right-4 z-30 flex max-w-[calc(100%-32px)] flex-col items-end gap-2">
                        <!-- Filter buttons (the 4 important buttons) -->
                        <div class="flex flex-wrap items-center justify-end gap-1 rounded-full border border-white/10 bg-black/50 p-1 shadow-xl backdrop-blur-md">
                            <button type="button" class="graph-kind-chip" [class.graph-kind-chip-active]="graphKindFilter() === 'all'" (click)="setGraphKindFilter('all')">
                                All <span>{{ graphInventory().nodes.length }}</span>
                            </button>
                            @for (kind of graphKindCounts(); track kind.kind) {
                            <button type="button" class="graph-kind-chip" [class.graph-kind-chip-active]="graphKindFilter() === kind.kind" (click)="setGraphKindFilter(kind.kind)">
                                {{ kind.kind }} <span>{{ kind.count }}</span>
                            </button>
                            }
                        </div>
                        
                        <!-- Reconcile counts -->
                        @if (graphCountReconciliation(); as counts) {
                        <div class="flex items-center gap-4 rounded-full border border-cyan-400/20 bg-black/60 px-4 py-2 text-[10px] shadow-2xl backdrop-blur-md">
                            <div class="flex items-center gap-1.5">
                                <span class="uppercase tracking-[0.16em] text-zinc-500">Committed</span>
                                <span class="font-bold text-zinc-200">{{ counts.committed.vertices ?? '?' }}v</span>
                                <span class="font-bold text-zinc-200">{{ counts.committed.evidenceEdges ?? '?' }}e</span>
                            </div>
                            <div class="h-3 w-px bg-white/15"></div>
                            <div class="flex items-center gap-1.5">
                                <span class="uppercase tracking-[0.16em] text-zinc-500">Rendered</span>
                                <span class="font-bold text-cyan-200">{{ counts.rendered.vertices }}v</span>
                                <span class="font-bold text-cyan-200">{{ counts.rendered.links }}e</span>
                            </div>
                        </div>
                        }
                    </div>
                    }
                    @if (atlasMode === 'embeddings') {
                    @if (activePreview(); as preview) {
                    <div class="absolute bottom-4 right-4 max-w-[360px] rounded-2xl border border-white/10 bg-black/60 p-3 text-xs shadow-2xl backdrop-blur">
                        <div class="flex items-center justify-between gap-3">
                            <span class="truncate font-semibold text-white">{{ preview.label }}</span>
                            <span class="shrink-0 rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-cyan-100">{{ preview.sourceType }}</span>
                        </div>
                        <p class="mt-1 text-[10px] uppercase tracking-[0.16em] text-zinc-500">score {{ preview.score | number:'1.2-2' }}</p>
                        <p class="mt-2 line-clamp-3 leading-5 text-zinc-300">{{ preview.preview || 'No source preview available yet.' }}</p>
                    </div>
                    }
                    }
                    @if (atlasMode === 'embeddings') {
                    <form class="atlas-bottom-shelf absolute bottom-4 left-4 z-30 flex max-w-[min(900px,calc(100%-32px))] items-center gap-2"
                        (submit)="runAtlasQuery(); $event.preventDefault()">
                        <label class="atlas-canvas-search atlas-trace-search">
                            <lucide-icon [img]="SearchIcon" class="h-4 w-4 text-zinc-500"></lucide-icon>
                            <input type="text" placeholder="Ask the atlas where an idea lives..." [value]="queryText()"
                                (input)="queryText.set($any($event.target).value)" />
                        </label>
                        <div class="atlas-canvas-actions">
                            <button type="submit" class="atlas-canvas-action trace-action">
                                {{ traceButtonLabel() }}
                            </button>
                            @if (queryTrace()) {
                            <button type="button" class="atlas-canvas-action" (click)="clearAtlasQuery()">Clear</button>
                            }
                            <button type="button" class="atlas-canvas-action" (click)="addEntityRequested.emit()">
                                <lucide-icon [img]="PlusIcon" class="h-4 w-4"></lucide-icon>Add
                            </button>
                        </div>
                    </form>
                    } @else {
                    <div class="atlas-bottom-shelf absolute bottom-4 left-4 z-30 flex max-w-[min(760px,calc(100%-32px))] items-center gap-2">
                        <label class="atlas-canvas-search">
                            <lucide-icon [img]="SearchIcon" class="h-4 w-4 text-zinc-500"></lucide-icon>
                            <input type="text" placeholder="Search labels, aliases, or kinds" [ngModel]="atlasSearch"
                                (ngModelChange)="atlasSearchChange.emit($event)" />
                        </label>
                        <div class="atlas-canvas-actions">
                            <button type="button" class="atlas-canvas-action" (click)="addEntityRequested.emit()">
                                <lucide-icon [img]="PlusIcon" class="h-4 w-4"></lucide-icon>Add
                            </button>
                        </div>
                    </div>
                    }
                    @if (settingsOpen) {
                    <div class="settings-float absolute bottom-4 right-4 top-14 w-[min(360px,calc(100%-2rem))] overflow-y-auto rounded-2xl border border-white/10 p-3 text-xs text-zinc-300">
                        @if (atlasTruth(); as truth) {
                        <div class="atlas-truth-panel mb-3">
                            <div class="atlas-truth-panel-title">Packet trace</div>
                            <dl>
                                <div><dt>Source</dt><dd>{{ truth.source }}</dd></div>
                                <div><dt>Scope</dt><dd>{{ truth.scopeId }}</dd></div>
                                <div><dt>Snapshot</dt><dd>{{ truth.snapshotId }}</dd></div>
                                <div><dt>Built</dt><dd>{{ truth.builtAt }}</dd></div>
                                <div><dt>Lens</dt><dd>{{ truth.lens }}</dd></div>
                                <div><dt>Layout</dt><dd>{{ truth.layout }}</dd></div>
                                <div><dt>Vectors</dt><dd>{{ truth.vectors }}</dd></div>
                            </dl>
                        </div>
                        }
                        <div class="settings-toggle-grid">
                            <button type="button" class="galaxy-control-button" (click)="cycleLabelMode()">Labels<span>{{ settings.labelMode }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleEdgeMode()">Edges<span>{{ settings.edgeMode }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleEdgeColorMode()">Palette<span>{{ edgeColorLabel() }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleParticleFlow()">Flow<span>{{ particleFlowLabel() }}</span></button>
                            @if (atlasMode === 'embeddings') {
                            <button type="button" class="galaxy-control-button" (click)="cycleEmbeddingTopologyMode()">Topology<span>{{ embeddingTopologyLabel() }}</span></button>
                            }
                            <button type="button" class="galaxy-control-button" (click)="cycleNodeDragMode()">Drag<span>{{ settings.nodeDragMode }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="toggleClickFocus()">Dbl Focus<span>{{ settings.clickFocus ? 'on' : 'off' }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleNodeShape()">Shape<span>{{ settings.nodeShape }}</span></button>
                            @if (settings.nodeShape === 'sphere') {
                            <button type="button" class="galaxy-control-button" (click)="cycleSphereSurface()">Sphere<span>{{ sphereSurfaceLabel() }}</span></button>
                            }
                            <button type="button" class="galaxy-control-button" (click)="toggleAutoRotate()">Rotate<span>{{ settings.autoRotate ? 'on' : 'off' }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleBackgroundMode()">Backdrop<span>{{ backgroundLabel() }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="toggleDetailCards()">Detail cards<span>{{ settings.detailCardsVisible ? 'on' : 'off' }}</span></button>
                            @if (settings.layoutMode === 'hybridSpace' || isTransitLayout(settings.layoutMode)) {
                            <button type="button" class="galaxy-control-button" (click)="toggleHybridShell()">Shell<span>{{ settings.hybridShellVisible ? 'on' : 'off' }}</span></button>
                            }
                            @if (settings.layoutMode === 'hybridSpace') {
                            <button type="button" class="galaxy-control-button" (click)="toggleHybridField()">Field<span>{{ settings.hybridHorospheresVisible ? 'on' : 'off' }}</span></button>
                            }
                        </div>
                        <div class="mt-3 rounded-lg border border-zinc-700/40 bg-zinc-900/40 p-2.5">
                            <div class="mb-2 flex items-center justify-between">
                                <span class="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-400">Guides</span>
                                <span class="text-[9px] uppercase tracking-[0.14em] text-zinc-600">per-family</span>
                            </div>
                            <div class="grid grid-cols-2 gap-2">
                                <button type="button" class="galaxy-control-button" (click)="toggleGuideRoutes()">Routes<span>{{ settings.guideRoutesVisible ? 'on' : 'off' }}</span></button>
                                <button type="button" class="galaxy-control-button" (click)="toggleGuideFibers()">Fibers<span>{{ settings.guideFibersVisible ? 'on' : 'off' }}</span></button>
                            </div>
                            <p class="mt-2 text-[9px] leading-snug text-zinc-600">Each guide family toggles independently of shells. Color = node adopts the color of its source node.</p>
                        </div>
                        <div class="mt-3 grid grid-cols-2 gap-2">
                            <button type="button" class="galaxy-control-button" (click)="styleRequested.emit(currentLensStyleKey())">Style this lens<span>{{ currentLensStyleKey() }}</span></button>
                            @if (selectedStyleKey(); as styleKey) {
                            <button type="button" class="galaxy-control-button" (click)="styleRequested.emit(styleKey)">Style selected kind<span>{{ styleKey }}</span></button>
                            } @else {
                            <button type="button" class="galaxy-control-button" (click)="styleRequested.emit(currentLensStyleKey())">Style selected kind<span>lens default</span></button>
                            }
                        </div>
                        @if ((settings.layoutMode === 'hybridSpace' || isTransitLayout(settings.layoutMode)) && settings.hybridShellVisible) {
                        <label class="settings-slider-row mt-3">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Shell opacity</span><span>{{ settings.hybridShellOpacity | number:'1.2-2' }}</span></span>
                            <input type="range" min="0" max="1" step="0.02" [value]="settings.hybridShellOpacity" class="galaxy-slider" (input)="setHybridShellOpacity($any($event.target).value)" />
                        </label>
                        }
                        @if (settings.layoutMode === 'hopfProjection' && settings.hopfSpaceVisible) {
                        <label class="settings-slider-row mt-3">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Space</span><span>{{ settings.hopfSpaceIntensity | number:'1.1-1' }}</span></span>
                            <input type="range" min="0" max="1.4" step="0.05" [value]="settings.hopfSpaceIntensity" class="galaxy-slider" (input)="setHopfSpaceIntensity($any($event.target).value)" />
                        </label>
                        }
                        @if ((settings.layoutMode === 'lorentzTree' || isTransitLayout(settings.layoutMode) || settings.layoutMode === 'siegelFinsler') && settings.lorentzSpaceVisible) {
                        <label class="settings-slider-row mt-3">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Space</span><span>{{ settings.lorentzSpaceIntensity | number:'1.1-1' }}</span></span>
                            <input type="range" min="0" max="1.4" step="0.05" [value]="settings.lorentzSpaceIntensity" class="galaxy-slider" (input)="setLorentzSpaceIntensity($any($event.target).value)" />
                        </label>
                        }
                        <label class="settings-slider-row mt-3">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Glow</span><span>{{ settings.glow | number:'1.1-1' }}</span></span>
                            <input type="range" min="0" max="1.8" step="0.05" [value]="settings.glow" class="galaxy-slider" (input)="setGlow($any($event.target).value)" />
                        </label>
                        <label class="settings-slider-row mt-2">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Distance</span><span>{{ settings.nodeDistance | number:'1.1-1' }}</span></span>
                            <input type="range" min="0.15" max="3.2" step="0.05" [value]="settings.nodeDistance" class="galaxy-slider" (input)="setNodeDistance($any($event.target).value)" />
                        </label>
                        <label class="settings-slider-row mt-2">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Edge length</span><span>{{ settings.edgeLength | number:'1.1-1' }}</span></span>
                            <input type="range" min="0.15" max="3.4" step="0.05" [value]="settings.edgeLength" class="galaxy-slider" (input)="setEdgeLength($any($event.target).value)" />
                        </label>
                        <label class="settings-slider-row mt-2">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Edge width</span><span>{{ settings.edgeWidth | number:'1.1-1' }}</span></span>
                              <input type="range" min="0.15" max="1.1" step="0.05" [value]="settings.edgeWidth" class="galaxy-slider" (input)="setEdgeWidth($any($event.target).value)" />
                        </label>
                        <label class="settings-slider-row mt-2">
                            <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Curve</span><span>{{ settings.edgeCurveStrength | number:'1.1-1' }}</span></span>
                            <input type="range" min="0.25" max="1.2" step="0.05" [value]="settings.edgeCurveStrength" class="galaxy-slider" (input)="setCurveStrength($any($event.target).value)" />
                        </label>
                        @if (settings.particleFlow) {
                        <div class="mt-3 border-t border-white/10 pt-3">
                            <label class="settings-slider-row">
                                <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Particle size</span><span>{{ settings.particleSize | number:'1.1-1' }}</span></span>
                                <input type="range" min="0.35" max="2.6" step="0.05" [value]="settings.particleSize" class="galaxy-slider" (input)="setParticleSize($any($event.target).value)" />
                            </label>
                            <label class="settings-slider-row mt-2">
                                <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Particle speed</span><span>{{ settings.particleSpeed | number:'1.1-1' }}</span></span>
                                <input type="range" min="0.2" max="3" step="0.05" [value]="settings.particleSpeed" class="galaxy-slider" (input)="setParticleSpeed($any($event.target).value)" />
                            </label>
                            <label class="settings-slider-row mt-2">
                                <span class="flex justify-between text-[10px] uppercase tracking-[0.16em] text-zinc-500"><span>Particle opacity</span><span>{{ settings.particleOpacity | number:'1.1-1' }}</span></span>
                                <input type="range" min="0.1" max="1" step="0.05" [value]="settings.particleOpacity" class="galaxy-slider" (input)="setParticleOpacity($any($event.target).value)" />
                            </label>
                        </div>
                        }
                    </div>
                    }
                    }
                </div>
            </div>
        </section>
    `,
    styles: [`
        :host section::before { content: ''; pointer-events: none; position: absolute; inset: 0; opacity: 0; transition: opacity 160ms ease, background 160ms ease; }
        .atlas-preview-surface {
            color-scheme: dark;
            background:
                radial-gradient(circle at 18% 20%, rgba(20,184,166,0.07), transparent 32%),
                radial-gradient(circle at 82% 20%, rgba(153,27,210,0.08), transparent 30%),
                #02040a;
        }

        .atlas-canvas-surface {
            background:
                radial-gradient(circle at 50% 48%, rgba(var(--ui-accent-rgb), 0.04), transparent 44%),
                #02040a;
        }

        :host section[data-backdrop="nebula"]::before { opacity: 1; background: radial-gradient(circle at 18% 20%, rgba(20,184,166,0.09), transparent 32%), radial-gradient(circle at 82% 20%, rgba(153,27,210,0.11), transparent 30%); }
        :host section[data-backdrop="grid"]::before { opacity: 1; background: radial-gradient(circle at 50% 50%, rgba(20,184,166,0.045), transparent 42%); }
        .settings-toggle-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
        }

        .galaxy-control-button {
            display: flex;
            min-width: 0;
            flex-direction: column;
            gap: 2px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(255, 255, 255, 0.035);
            padding: 6px 8px;
            text-align: left;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: rgb(212 212 216);
            transition: border-color 160ms ease, background 160ms ease;
        }

        .galaxy-control-button:hover {
            border-color: rgba(var(--ui-accent-rgb), 0.28);
            background: rgba(var(--ui-accent-rgb), 0.10);
        }

        .galaxy-control-button span {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: var(--ui-accent-bright);
            letter-spacing: 0;
            text-transform: none;
        }

        .galaxy-slider {
            width: 100%;
            accent-color: var(--ui-accent);
        }

        .settings-slider-row {
            display: block;
            min-width: 0;
            padding: 2px 1px 0;
        }

        .canvas-control-rail { pointer-events: auto; background: transparent; box-shadow: none; scrollbar-width: none; }
        .canvas-control-zone { max-width: calc(100% - 102px); }
        .atlas-canvas-surface { container-type: inline-size; }
        .canvas-lens-rail { max-width: calc(100% - 32px); }
        .canvas-projection-rail { max-width: calc(100% - 32px); scrollbar-width: none; }
        .atlas-status-rail {
            display: flex;
            min-width: 0;
            max-width: min(42vw, 640px);
            align-items: center;
            gap: 4px;
            overflow-x: auto;
            border-left: 1px solid rgba(255, 255, 255, 0.08);
            padding-left: 6px;
            scrollbar-width: none;
        }
        .atlas-status-rail::-webkit-scrollbar { display: none; }
        .atlas-status-token {
            display: inline-flex;
            max-width: 132px;
            flex: 0 1 auto;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            border-radius: 999px;
            border: 1px solid rgba(255, 255, 255, 0.075);
            background: rgba(255, 255, 255, 0.032);
            padding: 2px 6px;
            color: rgb(161 161 170);
            font-size: 8.5px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            opacity: 0.82;
        }
        .atlas-status-token-strong {
            border-color: rgba(45, 212, 191, 0.18);
            color: rgb(153 246 228);
            background: rgba(20, 184, 166, 0.07);
        }
        .atlas-status-token-source,
        .atlas-status-token-contract {
            max-width: 180px;
        }
        .canvas-projection-rail-top {
            left: 82px;
            top: 12px;
            max-width: calc(100% - 260px);
            flex-wrap: nowrap;
            transform: none;
        }
        .canvas-projection-rail-graph {
            top: 112px;
            max-width: calc(100% - 32px);
        }
        .canvas-projection-rail::-webkit-scrollbar { display: none; }
        @container (max-width: 820px) {
            .atlas-status-rail {
                max-width: 32vw;
            }
            .canvas-projection-rail-top {
                left: 16px;
                top: 64px;
                max-width: calc(100% - 32px);
                flex-wrap: wrap;
                transform: none;
            }
            .canvas-projection-rail-graph {
                top: 112px;
            }
        }
        .canvas-control-rail::-webkit-scrollbar { display: none; }
        .canvas-control-rail > * { flex: 0 0 auto; }
        .canvas-control-rail button, .canvas-chrome-toggle, .canvas-glass-button, .settings-float button, .settings-float input, .atlas-bottom-shelf, .atlas-bottom-shelf * { pointer-events: auto; }

        .canvas-chrome-toggle {
            display: inline-flex;
            height: 34px;
            width: 34px;
            flex: 0 0 auto;
            align-items: center;
            justify-content: center;
            border-radius: 12px;
            border: 1px solid rgba(var(--ui-accent-rgb), 0.18);
            background: rgba(3, 8, 13, 0.68);
            color: var(--ui-accent-bright);
            box-shadow: 0 12px 26px rgba(0, 0, 0, 0.24);
            backdrop-filter: blur(12px);
            transition: transform 140ms ease, border-color 140ms ease, background 140ms ease, color 140ms ease;
        }

        .canvas-chrome-toggle:hover,
        .canvas-chrome-toggle-active {
            border-color: rgba(168, 85, 247, 0.34);
            background: rgba(88, 28, 135, 0.28);
            color: rgb(245 208 254);
            transform: translateY(-1px);
        }

        .canvas-glass-button {
            border: 1px solid rgba(255, 255, 255, 0.10);
            background: rgba(0, 0, 0, 0.24);
            color: rgb(228 228 231);
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
            backdrop-filter: blur(8px);
            transition: border-color 140ms ease, background 140ms ease, color 140ms ease;
        }

        .settings-float {
            pointer-events: auto;
            background:
                linear-gradient(180deg, rgba(14, 18, 25, 0.86), rgba(4, 8, 14, 0.78));
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.38);
            backdrop-filter: blur(18px);
            overscroll-behavior: contain;
            scrollbar-width: thin;
            scrollbar-color: rgba(var(--ui-accent-rgb), 0.42) rgba(255, 255, 255, 0.05);
        }

        .settings-float::-webkit-scrollbar {
            width: 8px;
        }

        .settings-float::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 999px;
        }

        .settings-float::-webkit-scrollbar-thumb {
            background: rgba(var(--ui-accent-rgb), 0.42);
            border-radius: 999px;
        }

        .atlas-truth-panel {
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.07);
            background: rgba(0, 0, 0, 0.22);
            padding: 8px;
        }

        .atlas-truth-panel-title {
            margin-bottom: 6px;
            color: rgb(161 161 170);
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
        }

        .atlas-truth-panel dl {
            display: grid;
            gap: 4px;
            margin: 0;
        }

        .atlas-truth-panel dl > div {
            display: grid;
            min-width: 0;
            grid-template-columns: 68px minmax(0, 1fr);
            gap: 8px;
            align-items: baseline;
        }

        .atlas-truth-panel dt {
            color: rgb(113 113 122);
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .atlas-truth-panel dd {
            margin: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: rgb(212 212 216);
            font-size: 10px;
        }

        .canvas-glass-button:hover {
            border-color: rgba(var(--ui-accent-rgb), 0.24);
            background: rgba(var(--ui-accent-rgb), 0.10);
            color: var(--ui-accent-bright);
        }

        .lens-menu-button {
            display: flex;
            width: 100%;
            align-items: center;
            justify-content: space-between;
            border-radius: 10px;
            padding: 8px 10px;
            color: rgb(161 161 170);
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            transition: background 140ms ease, color 140ms ease;
        }

        .lens-menu-button:hover,
        .lens-menu-button-active {
            background: rgba(var(--ui-accent-rgb), 0.12);
            color: var(--ui-accent-bright);
        }


        .graph-kind-chip {
            display: inline-flex;
            min-height: 24px;
            align-items: center;
            gap: 5px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.035);
            padding: 0 8px;
            color: rgb(161 161 170);
            font-size: 9px;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            transition: border-color 140ms ease, background 140ms ease, color 140ms ease;
        }

        .graph-kind-chip span {
            color: var(--ui-accent-bright);
            letter-spacing: 0;
        }

        .graph-kind-chip:hover,
        .graph-kind-chip-active {
            border-color: rgba(var(--ui-accent-rgb), 0.28);
            background: rgba(var(--ui-accent-rgb), 0.12);
            color: var(--ui-accent-bright);
        }

        .atlas-bottom-shelf {
            filter: drop-shadow(0 16px 30px rgba(0, 0, 0, 0.34));
        }

        .atlas-canvas-search {
            display: flex;
            min-height: 38px;
            min-width: min(360px, 42vw);
            align-items: center;
            gap: 9px;
            border: 1px solid rgba(var(--ui-accent-rgb), 0.16);
            border-radius: 999px;
            background: rgba(3, 8, 13, 0.72);
            padding: 0 13px;
            backdrop-filter: blur(12px);
        }

        .atlas-trace-search {
            min-width: min(500px, 48vw);
        }

        .atlas-canvas-search input {
            min-width: 0;
            flex: 1;
            background: transparent;
            color: rgb(236 254 255);
            font-size: 13px;
            outline: none;
        }

        .atlas-canvas-search input::placeholder {
            color: rgb(113 113 122);
        }

        .atlas-canvas-actions {
            display: flex;
            align-items: center;
            gap: 6px;
            border: 1px solid rgba(var(--ui-accent-rgb), 0.13);
            border-radius: 999px;
            background: rgba(3, 8, 13, 0.68);
            padding: 4px;
            backdrop-filter: blur(12px);
        }

        .atlas-canvas-action {
            display: inline-flex;
            min-height: 30px;
            align-items: center;
            justify-content: center;
            gap: 5px;
            border-radius: 999px;
            padding: 0 10px;
            color: var(--ui-accent-bright);
            font-size: 11px;
            font-weight: 800;
            transition: background 140ms ease, color 140ms ease, opacity 140ms ease;
        }

        .atlas-canvas-action:hover {
            background: rgba(var(--ui-accent-rgb), 0.13);
            color: var(--ui-accent-bright);
        }

        .atlas-canvas-action:disabled {
            cursor: default;
            opacity: 0.58;
        }

        .atlas-canvas-action.scan-action {
            border: 1px solid rgba(168, 85, 247, 0.32);
            background: rgba(126, 34, 206, 0.22);
            color: rgb(237 233 254);
            box-shadow: 0 0 22px rgba(168, 85, 247, 0.13);
        }

        .scan-action-copy {
            display: inline-flex;
            min-width: 0;
            flex-direction: column;
            align-items: flex-start;
            line-height: 1.05;
        }

        .scan-action-kicker {
            max-width: 150px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: rgba(216, 180, 254, 0.74);
            font-size: 8px;
            font-weight: 900;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }

        .scan-action-main {
            max-width: 170px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .atlas-canvas-action.trace-action {
            border: 1px solid rgba(var(--ui-accent-rgb), 0.28);
            background: rgba(var(--ui-accent-rgb), 0.22);
            color: var(--ui-accent-bright);
        }

        .atlas-canvas-action.scan-action:hover {
            background: rgba(147, 51, 234, 0.34);
            color: rgb(250 245 255);
        }

        @media (max-width: 900px) {
            .graph-reconcile-grid {
                grid-template-columns: minmax(0, 1fr);
            }

            .atlas-bottom-shelf {
                right: 4px;
                flex-wrap: wrap;
            }

            .atlas-canvas-search {
                min-width: min(420px, calc(100vw - 64px));
            }
        }
    `],
})
export class GraphAtlasPreviewComponent implements OnInit, OnDestroy {
    private readonly phoenixUiApi = inject(PhoenixUiApiService);
    private readonly phoenix = inject(PhoenixBackendService);
    private readonly machine = inject(PhoenixMachineControlService);
    private readonly hubService = inject(BlueprintHubService);
    private readonly atlasLoadedKeys = new Map<AtlasManifoldMode, string>();
    private readonly atlasLoadingKeys = new Map<AtlasManifoldMode, string>();
    private activeGraphCache: ActiveAtlasGraph | null = null;
    private _lensMode: GraphLensMode = 'global';
    private _primaryNoteId: string | null = null;
    private _selectedNoteIds: string[] = [];
    private readonly readContextEpoch = signal(0);
    private readonly graphSnapshotSignal = signal<GraphRebuildSnapshot | null>(null);
    private graphSnapshotIdentity = '';
    private manifoldPrewarmGeneration = 0;
    private destroyed = false;
    private readonly unsubscribeColors = entityColorStore.subscribe(() => this.refreshGraphInventoryFromSnapshot());

    @Input() entities: GalaxyRenderableNode[] = [];
    @Input() edges: AtlasPreviewEdge[] = [];
    @Input() sourceLabel = 'registry graph';
    @Input() graphCounters: GraphRebuildCounters | null = null;
    @Input() set graphSnapshot(value: GraphRebuildSnapshot | null | undefined) {
        const snapshot = value ?? null;
        const identity = graphSnapshotRenderIdentity(snapshot);
        if (snapshot === this.graphSnapshotSignal() || (identity && identity === this.graphSnapshotIdentity)) return;
        this.graphSnapshotIdentity = identity;
        this.graphSnapshotSignal.set(snapshot);
        if (snapshot) {
            this.refreshGraphInventoryFromSnapshot();
            this.scheduleManifoldScenePrewarm(snapshot);
        }
        else this.graphInventory.set(EMPTY_GRAPH_INVENTORY);
        this.activeGraphCache = null;
    }
    @Input() set committedGraphInventory(value: GraphInventory | null | undefined) {
        if (!this.graphSnapshotSignal()) this.graphInventory.set(value ?? EMPTY_GRAPH_INVENTORY);
        this.activeGraphCache = null;
    }
    @Input() set lensMode(value: GraphLensMode | null | undefined) {
        this._lensMode = value || 'global';
        this.bumpReadContext();
    }
    get lensMode(): GraphLensMode {
        return this._lensMode;
    }
    @Input() set primaryNoteId(value: string | null | undefined) {
        this._primaryNoteId = value || null;
        this.bumpReadContext();
    }
    @Input() set selectedNoteIds(value: string[] | null | undefined) {
        this._selectedNoteIds = Array.isArray(value) ? [...value] : [];
        this.bumpReadContext();
    }
    @Input() atlasSearch = '';
    @Input() isScanning = false;
    @Input() activeProvider: EntitySuggestionProviderId | null = null;
    @Output() entitySelected = new EventEmitter<RegisteredEntity>();
    @Output() addEntityRequested = new EventEmitter<void>();
    @Output() scanRequested = new EventEmitter<GraphLensState>();
    @Output() styleRequested = new EventEmitter<string | void>();
    @Output() atlasModeChange = new EventEmitter<AtlasMode>();
    @Output() lensModeChange = new EventEmitter<GraphLensMode>();
    @Output() atlasSearchChange = new EventEmitter<string>();
    @Output() sourceRequested = new EventEmitter<GraphCanvasSourceRequest>();
    @ViewChild('galaxyCanvas') private galaxyCanvas?: GraphGalaxyCanvasComponent;

    private readonly persistedViewState = readPersistedAtlasViewState();
    viewMode: AtlasViewMode = this.persistedViewState.viewMode;
    atlasMode: AtlasMode = this.persistedViewState.atlasMode;
    settings: GalaxyRenderSettings = mergeGalaxySettings(this.persistedViewState.settings);
    settingsOpen = false;
    lensMenuOpen = false;
    controlsCollapsed = this.persistedViewState.controlsCollapsed;
    isRefreshingProjection = false;
    selectedEntityId: string | null = null;
    hoveredEntity: GalaxyRenderableNode | null = null;
    readonly canvasLens = signal<GraphCanvasLens>(this.persistedViewState.canvasLens);
    readonly lassoEnabled = signal(false);
    readonly selectedCanvasHit = signal<GraphCanvasHit | null>(null);
    readonly hoveredCanvasHit = signal<GraphCanvasHit | null>(null);
    readonly batchSelectedNodeIds = signal<string[]>([]);
    readonly pathSelectedNodeIds = signal<string[]>([]);
    private canvasSingleSelectionId: string | null = null;
    private canvasSingleSelection: readonly string[] = [];
    queryText = signal('');
    queryTrace = signal<EmbeddingQueryTrace | null>(null);
    readonly manifoldMode = this.machine.manifoldMode;
    readonly manifoldStatus = this.machine.manifoldStatus;
    private readonly embeddingAtlasByMode = signal<Record<AtlasManifoldMode, EmbeddingAtlasData>>({
        hybrid: emptyEmbeddingAtlas('hybrid atlas not loaded'),
        hopf: emptyEmbeddingAtlas('hopf atlas not loaded'),
        lorentz: emptyEmbeddingAtlas('lorentz forest not loaded'),
        product: emptyEmbeddingAtlas('transit atlas not loaded'),
        siegel: emptyEmbeddingAtlas('siegel-finsler atlas not loaded'),
    });
    readonly embeddingAtlas = computed(() => this.embeddingAtlasByMode()[this.manifoldMode()]);
    readonly graphRebuildEmbeddingAtlas = computed(() => {
        const snapshot = this.graphSnapshotSignal();
        if (!snapshot) return null;
        return graphRebuildEmbeddingTargetCount(snapshot) > 0
            ? cachedGraphRebuildEmbeddingAtlas(snapshot, this.manifoldMode())
            : null;
    });
    graphInventory = signal<GraphInventory>(EMPTY_GRAPH_INVENTORY);
    graphKindFilter = signal(this.persistedViewState.graphKindFilter || 'all');
    graphKindCounts = computed(() => this.graphInventory().kindCounts.slice(0, 4));
    graphCountReconciliation = computed(() => buildAtlasCountReconciliation({
        committedVertices: this.graphCounters?.nodes ?? this.graphInventory().nodes.length,
        committedEvidenceEdges: this.graphCounters?.edges ?? this.graphInventory().edges.length,
        committedLeaves: this.graphCounters?.acceptedAnchors ?? null,
        renderedVertices: this.graphInventory().nodes.length,
        renderedLinks: this.graphInventory().edges.length,
        renderedKinds: this.graphInventory().kindCounts,
        sourceLabel: 'Graph Rebuild Snapshot',
    }));
    readonly projectionContract = computed(() => {
        const inventory = this.graphInventory();
        const atlas = this.graphRebuildEmbeddingAtlas() ?? this.embeddingAtlas();
        return buildGraphProjectionContractReport(this.graphSnapshotSignal(), {
            graphNodes: inventory.nodes.length,
            embeddingNodes: atlas.nodes.length,
            embeddingEdges: atlas.edges.length,
        });
    });
    readonly PlusIcon = Plus;
    readonly SearchIcon = Search;
    readonly SettingsIcon = Settings2;
    readonly SlidersIcon = SlidersHorizontal;
    readonly LassoIcon = ScanSearch;
    readonly ZapIcon = Zap;
    readonly lensModes: { id: GraphLensMode; label: string }[] = [
        { id: 'global', label: 'Global' },
        { id: 'narrative', label: 'Narrative' },
        { id: 'note', label: 'Note' },
        { id: 'multiNote', label: 'Compare' },
    ];
    readonly canvasLenses: { id: GraphCanvasLens; label: string }[] = [
        { id: 'entities', label: 'Entities' },
        { id: 'structure', label: 'Structure' },
        { id: 'facts', label: 'Facts' },
        { id: 'discourse', label: 'Discourse' },
        { id: 'accepted', label: 'Accepted' },
        { id: 'proposed', label: 'Proposed' },
    ];

    constructor() {
        if (this.machine.manifoldMode() !== this.persistedViewState.manifoldMode) {
            this.machine.setManifoldMode(this.persistedViewState.manifoldMode);
        }
        effect(() => {
            this.readContextEpoch();
            const manifold = this.manifoldMode();
            const context = this.currentReadContext();
            untracked(() => {
                if (this.atlasMode === 'embeddings') void this.refreshEmbeddingAtlas(context, manifold);
            });
        });
        effect(() => {
            const summary = this.machine.lastSummary();
            this.readContextEpoch();
            const manifold = this.manifoldMode();
            const context = this.currentReadContext();
            if (this.atlasMode !== 'embeddings') return;
            if (!projectionSummaryRequestsRefresh(summary, manifold)) return;
            untracked(() => {
                this.atlasLoadedKeys.delete(manifold);
                void this.refreshCurrentProjectionView(context);
            });
        });
    }

    ngOnInit(): void {
        if (this.atlasMode === 'graph' && this.settings.layoutMode === 'single') {
            this.settings = mergeGalaxySettings({
                ...this.settings,
                ...this.layoutPatchForManifold(this.manifoldMode()),
            });
        }
        this.atlasModeChange.emit(this.atlasMode);
    }

    ngOnDestroy(): void {
        this.destroyed = true;
        this.manifoldPrewarmGeneration += 1;
        this.unsubscribeColors();
    }

    private refreshGraphInventoryFromSnapshot(): void {
        const snapshot = this.graphSnapshotSignal();
        if (!snapshot) return;
        this.graphInventory.set(buildGraphCanvasInventory(snapshot));
        this.activeGraphCache = null;
    }

    setViewMode(mode: AtlasViewMode): void {
        this.viewMode = mode;
        this.persistViewState();
    }

    setAtlasMode(mode: AtlasMode): void {
        const changed = this.atlasMode !== mode;
        this.atlasMode = mode;
        if (changed) this.atlasModeChange.emit(mode);
        this.selectedEntityId = null;
        this.hoveredEntity = null;
        this.closeCanvasInspector();
        if (mode === 'entities' && this.settings.layoutMode !== 'single') {
            this.updateSettings({ layoutMode: 'single' });
        } else if (mode === 'graph' && this.settings.layoutMode === 'single') {
            this.updateSettings(this.layoutPatchForManifold(this.manifoldMode()));
        } else if (mode === 'embeddings') {
            const layoutMode = this.layoutForManifold(this.manifoldMode());
            if (this.settings.layoutMode === 'single' || this.settings.layoutMode !== layoutMode && this.manifoldMode() !== 'hybrid') {
                this.updateSettings(this.layoutPatchForManifold(this.manifoldMode()));
            }
            void this.refreshEmbeddingAtlas(this.currentReadContext(), this.manifoldMode());
        }
        if (mode === 'embeddings') this.scheduleManifoldScenePrewarm(this.graphSnapshotSignal());
        this.persistViewState();
    }

    setGraphKindFilter(kind: string): void {
        this.graphKindFilter.set(kind);
        this.closeCanvasInspector();
        this.hoveredEntity = null;
        this.persistViewState();
    }

    setCanvasLens(lens: GraphCanvasLens): void {
        if (this.canvasLens() === lens) return;
        this.canvasLens.set(lens);
        this.graphKindFilter.set('all');
        this.activeGraphCache = null;
        this.closeCanvasInspector();
        this.persistViewState();
    }

    toggleLasso(): void {
        this.lassoEnabled.update((value) => !value);
    }

    setLayoutMode(mode: GalaxyLayoutMode): void {
        if (this.atlasMode === 'entities' && mode !== 'single') return;
        if ((mode === 'hybridSpace' || mode === 'multiGalaxy') && this.manifoldMode() !== 'hybrid') {
            this.machine.setManifoldMode('hybrid');
        } else if (mode === 'hopfProjection' && this.manifoldMode() !== 'hopf') {
            this.machine.setManifoldMode('hopf');
        } else if (mode === 'lorentzTree' && this.manifoldMode() !== 'lorentz') {
            this.machine.setManifoldMode('lorentz');
        } else if (isTransitLayoutMode(mode) && this.manifoldMode() !== 'product') {
            this.machine.setManifoldMode('product');
        } else if (mode === 'siegelFinsler' && this.manifoldMode() !== 'siegel') {
            this.machine.setManifoldMode('siegel');
        }
        this.updateSettings(mode === 'hybridSpace'
            ? this.hybridShellLayoutPatch(mode)
            : { layoutMode: mode });
        this.persistViewState();
    }

    setManifoldMode(mode: AtlasManifoldMode): void {
        this.machine.setManifoldMode(mode);
        const patch = this.layoutPatchForManifold(mode);
        if (this.settings.layoutMode !== patch.layoutMode) this.updateSettings(patch);
        this.queryTrace.set(null);
        this.closeCanvasInspector();
        if (this.atlasMode === 'embeddings') void this.refreshEmbeddingAtlas(this.currentReadContext(), mode);
        this.persistViewState();
    }

    toggleSettings(): void {
        this.settingsOpen = !this.settingsOpen;
        if (this.settingsOpen) this.lensMenuOpen = false;
    }

    toggleControlsCollapsed(): void {
        this.controlsCollapsed = !this.controlsCollapsed;
        this.persistViewState();
    }

    toggleLensMenu(): void {
        this.lensMenuOpen = !this.lensMenuOpen;
        if (this.lensMenuOpen) this.settingsOpen = false;
    }

    chooseLens(mode: GraphLensMode): void {
        this.lensModeChange.emit(mode);
        this.lensMenuOpen = false;
    }

    lensLabel(): string {
        return this.lensModes.find((mode) => mode.id === this.lensMode)?.label ?? 'Narrative';
    }

    traceButtonLabel(): string {
        return manifoldAdapter(this.manifoldMode()).traceLabel;
    }

    semanticAtlasActionLabel(): string {
        if (this.isScanning) return 'Indexing Semantic Atlas';
        if (this.isRefreshingProjection) return `Refreshing ${this.currentProjectionLabel()}`;
        return this.canRefreshCurrentProjection() ? `Refresh ${this.currentProjectionLabel()}` : 'Index Semantic Atlas';
    }

    semanticAtlasActionKicker(): string {
        if (this.canRefreshCurrentProjection()) return `${this.currentProjectionLabel()} projection`;
        return 'from rendered graph';
    }

    semanticAtlasActionTitle(): string {
        if (this.canRefreshCurrentProjection()) {
            return `Reload existing Semantic Atlas rows into the ${this.currentProjectionLabel()} projection without running embeddings.`;
        }
        return 'Committed graph leaves, documents, entities, and context lanes -> semantic vectors -> candidate links -> manifold projections.';
    }

    semanticGraphAvailabilityLabel(): string {
        if (this.usesGraphRebuildEmbeddingAtlas()) {
            const snapshot = this.graphSnapshotSignal();
            const atlas = this.graphRebuildEmbeddingAtlas();
            const targets = atlas?.nodes.length ?? graphRebuildEmbeddingTargetCount(snapshot);
            const totalTargets = graphRebuildEmbeddingTargetCount(snapshot) || targets;
            const targetLabel = totalTargets > targets ? `${targets} visible / ${totalTargets} targets` : `${targets} targets`;
            const packetTargets = snapshot?.atlasPacket?.manifoldTargets || [];
            const chunks = snapshot?.embeddingTargets.filter((target) => target.kind === 'chunk').length
                || packetTargets.filter((target) => target.kind === 'chunk').length
                || snapshot?.chunks.length
                || 0;
            const entities = snapshot?.embeddingTargets.filter((target) => target.kind === 'entity').length
                || packetTargets.filter((target) => target.kind === 'entity').length
                || snapshot?.nodes.length
                || 0;
            return `${targetLabel} / ${chunks} chunks / ${entities} entities / ${atlas?.edges.length ?? 0} links`;
        }
        const inventory = this.graphInventory();
        const counters = this.graphCounters;
        if (!inventory.nodes.length && !counters?.embeddingTargets) return 'unavailable';
        if (counters?.embeddingTargets) {
            return `${counters.embeddingTargets} targets / ${counters.chunks} chunks / ${counters.nodes} entities`;
        }
        return `${this.graphKindTotal('leaf', 'chunk')} leaves / ${this.graphKindTotal('document')} documents / ${this.graphKindTotal('entity')} entities`;
    }

    hopfReceiptSummary(): HopfReceiptSummary | null {
        if (this.atlasMode !== 'embeddings' || this.manifoldMode() !== 'hopf') return null;
        const space = this.graphSnapshotSignal()?.hopfResonanceSpace;
        if (!space) return null;
        return {
            assignments: space.counters?.assignmentCount ?? space.assignments.length,
            occupiedCells: space.counters?.occupiedCellCount ?? space.cells.filter((cell) => cell.targetCount > 0).length,
            docCharts: space.counters?.docChartCount ?? space.docCharts.length,
            braids: space.counters?.braidCount ?? space.braids.length,
        };
    }

    runSemanticAtlasAction(): void {
        if (this.canRefreshCurrentProjection()) {
            void this.refreshCurrentProjectionView(this.currentReadContext());
            return;
        }
        this.scanRequested.emit(this.currentLensState());
    }

    manifoldGeometryLabel(): string {
        return this.displayEmbeddingAtlas().manifold?.geometryVersion || (
            this.manifoldMode() === 'hopf'
                ? 'hopf_ico_r5_v1'
                : this.manifoldMode() === 'lorentz'
                    ? 'hierarchy_caps_v1'
                    : this.manifoldMode() === 'product'
                        ? 'transit_lorentz_hopf_v1'
                        : this.manifoldMode() === 'siegel'
                            ? 'siegel_finsler_v1'
                    : 'hybrid_semantic_v1'
        );
    }

    projectionSourceLabel(): string {
        const source = String(this.displayEmbeddingAtlas().manifold?.projectionSource || 'semantic_atlas_rows');
        return source.replace(/_/g, ' ');
    }

    onCanvasObjectSelected(hit: GraphCanvasHit): void {
        if (hit.kind !== 'node') {
            if (this.settings.detailCardsVisible) this.selectedCanvasHit.set(hit);
            return;
        }
        this.batchSelectedNodeIds.set([]);
        if (this.settings.detailCardsVisible) {
            this.selectedCanvasHit.set(hit);
            this.pathSelectedNodeIds.set([hit.id]);
            this.selectedEntityId = hit.id;
            return;
        }
        this.selectedCanvasHit.set(null);
        const next = nextPathSelection(this.pathSelectedNodeIds(), hit.id);
        this.pathSelectedNodeIds.set(next);
        this.selectedEntityId = next.at(-1) ?? null;
    }

    onCanvasBatchSelected(ids: string[]): void {
        if (!this.settings.detailCardsVisible) {
            const selected = boundedPathSelection(ids);
            this.pathSelectedNodeIds.set(selected);
            this.selectedCanvasHit.set(null);
            this.batchSelectedNodeIds.set([]);
            this.selectedEntityId = selected.at(-1) ?? null;
            return;
        }
        this.batchSelectedNodeIds.set(ids);
        this.selectedCanvasHit.set(null);
        this.pathSelectedNodeIds.set(ids.length === 1 ? ids : []);
        this.selectedEntityId = ids.length === 1 ? ids[0] : null;
    }

    closeCanvasInspector(): void {
        this.selectedCanvasHit.set(null);
        this.batchSelectedNodeIds.set([]);
        this.pathSelectedNodeIds.set([]);
        this.selectedEntityId = null;
    }

    canvasSelectedNodeIds(): readonly string[] {
        if (!this.settings.detailCardsVisible) return this.pathSelectedNodeIds();
        if (this.canvasSingleSelectionId !== this.selectedEntityId) {
            this.canvasSingleSelectionId = this.selectedEntityId;
            this.canvasSingleSelection = this.selectedEntityId ? [this.selectedEntityId] : [];
        }
        return this.canvasSingleSelection;
    }

    focusCanvasNodes(ids: string[]): void {
        const id = ids.find((candidate) => this.activeNodes().some((node) => node.id === candidate));
        if (!id) return;
        this.selectedEntityId = id;
        this.galaxyCanvas?.focusEntity(id);
    }

    canvasInspectorRecord() {
        return graphCanvasInspectorRecord(this.selectedCanvasHit(), this.activeNodes(), this.activeEdges());
    }

    canvasHoverRecord() {
        return graphCanvasInspectorRecord(this.hoveredCanvasHit(), this.activeNodes(), this.activeEdges());
    }

    canvasBatchRecords() {
        return graphCanvasBatchRecords(this.batchSelectedNodeIds(), this.activeNodes());
    }

    selectedStyleKey(): string {
        return this.canvasInspectorRecord()?.styleKey || this.canvasHoverRecord()?.styleKey || '';
    }

    currentLensStyleKey(): string {
        const selected = this.selectedStyleKey();
        if (selected) return selected;
        if (this.atlasMode === 'entities') return 'CHARACTER';
        if (this.atlasMode === 'embeddings') return this.manifoldMode() === 'lorentz' ? 'temporalFact' : 'graphFact';
        switch (this.canvasLens()) {
            case 'entities': return 'CHARACTER';
            case 'structure': return 'document';
            case 'discourse': return 'communication';
            case 'accepted': return 'approval';
            case 'proposed': return 'rankStatus';
            default: return 'graphFact';
        }
    }

    runAtlasQuery(): void {
        this.atlasMode = 'embeddings';
        this.persistViewState();
        const trace = manifoldAdapter(this.manifoldMode()).trace(this.queryText(), this.displayEmbeddingAtlas());
        this.queryTrace.set(trace);
        this.pathSelectedNodeIds.set([]);
        this.selectedEntityId = trace?.queryNode.id ?? null;
    }

    clearAtlasQuery(): void {
        this.queryTrace.set(null);
        this.pathSelectedNodeIds.set([]);
        this.selectedEntityId = null;
    }

    resetCamera(): void {
        this.galaxyCanvas?.resetCamera();
    }

    fitCamera(): void {
        this.galaxyCanvas?.fitToGraph();
    }

    cycleLabelMode(): void {
        const modes: GalaxyLabelMode[] = ['hover', 'selected', 'important', 'always', 'off'];
        this.updateSettings({ labelMode: modes[(modes.indexOf(this.settings.labelMode) + 1) % modes.length] });
    }

    cycleEdgeMode(): void {
        const modes: GalaxyEdgeMode[] = ['curved', 'straight', 'tube', 'hidden'];
        this.updateSettings({ edgeMode: modes[(modes.indexOf(this.settings.edgeMode) + 1) % modes.length] });
    }

    cycleEdgeColorMode(): void {
        const modes: GalaxyEdgeColorMode[] = ['entityBlend', 'aqua', 'orchid', 'gold', 'confidence', 'muted'];
        const current = this.settings.edgeColorMode === 'cyan' ? 'aqua' : this.settings.edgeColorMode;
        this.updateSettings({ edgeColorMode: modes[(modes.indexOf(current) + 1) % modes.length] });
    }

    edgeColorLabel(): string {
        const labels: Record<GalaxyEdgeColorMode, string> = {
            entityBlend: 'entity',
            aqua: 'aqua',
            orchid: 'orchid',
            gold: 'gold',
            confidence: 'score',
            muted: 'muted',
            cyan: 'aqua',
        };
        return labels[this.settings.edgeColorMode];
    }

    cycleEmbeddingTopologyMode(): void {
        const modes: GalaxyEmbeddingTopologyMode[] = ['off', 'clusters', 'regions', 'lanes', 'medoids', 'outliers', 'backbone', 'bridges'];
        this.updateSettings({ embeddingTopologyMode: modes[(modes.indexOf(this.settings.embeddingTopologyMode) + 1) % modes.length] });
    }

    embeddingTopologyLabel(): string {
        const labels: Record<GalaxyEmbeddingTopologyMode, string> = {
            off: 'off',
            clusters: 'clusters',
            regions: 'regions',
            lanes: 'lanes',
            medoids: 'medoids',
            outliers: 'outliers',
            backbone: 'backbone',
            bridges: 'bridges',
        };
        return labels[this.settings.embeddingTopologyMode || 'off'];
    }

    cycleParticleFlow(): void {
        if (!this.settings.particleFlow) {
            this.updateSettings({ particleFlow: true, particleFlowMode: 'swarm' });
            return;
        }
        if (this.settings.particleFlowMode !== 'walk') {
            this.updateSettings({ particleFlow: true, particleFlowMode: 'walk' });
            return;
        }
        this.updateSettings({ particleFlow: false });
    }

    particleFlowLabel(): string {
        if (!this.settings.particleFlow) return 'off';
        return this.settings.particleFlowMode === 'walk' ? 'walk' : 'swarm';
    }

    cycleNodeDragMode(): void {
        const modes: GalaxyNodeDragMode[] = ['stretch', 'force', 'pin', 'camera'];
        this.updateSettings({ nodeDragMode: modes[(modes.indexOf(this.settings.nodeDragMode) + 1) % modes.length] });
    }

    toggleClickFocus(): void {
        const clickFocus = !this.settings.clickFocus;
        this.updateSettings({ clickFocus });
    }

    cycleNodeShape(): void {
        const modes: GalaxyNodeShapeMode[] = ['atom', 'halo', 'sphere'];
        this.updateSettings({ nodeShape: modes[(modes.indexOf(this.settings.nodeShape) + 1) % modes.length] });
    }

    toggleAutoRotate(): void {
        this.updateSettings({ autoRotate: !this.settings.autoRotate });
    }

    toggleHybridShell(): void {
        this.updateSettings({ hybridShellVisible: !this.settings.hybridShellVisible });
    }

    toggleHybridField(): void {
        this.updateSettings({ hybridHorospheresVisible: !this.settings.hybridHorospheresVisible });
    }

    toggleHopfSpace(): void {
        this.updateSettings({ hopfSpaceVisible: !this.settings.hopfSpaceVisible });
    }

    toggleLorentzSpace(): void {
        this.updateSettings({ lorentzSpaceVisible: !this.settings.lorentzSpaceVisible });
    }

    /** Dedicated guide-family toggles. Each flips one family only, independent of shells. */
    toggleGuideRoutes(): void {
        this.updateSettings({ guideRoutesVisible: !this.settings.guideRoutesVisible });
    }

    toggleGuideFibers(): void {
        this.updateSettings({ guideFibersVisible: !this.settings.guideFibersVisible });
    }

    isTransitLayout(mode: GalaxyLayoutMode | string | null | undefined = this.settings.layoutMode): boolean {
        return isTransitLayoutMode(mode);
    }

    cycleBackgroundMode(): void {
        const modes: GalaxyBackgroundMode[] = ['nebula', 'grid', 'quiet', 'void'];
        this.updateSettings({ backgroundMode: modes[(modes.indexOf(this.settings.backgroundMode) + 1) % modes.length] });
    }

    backgroundLabel(): string {
        const labels: Record<GalaxyBackgroundMode, string> = {
            nebula: 'nebula',
            grid: 'grid',
            quiet: 'quiet',
            void: 'void',
        };
        return labels[this.settings.backgroundMode];
    }

    setGlow(value: string): void {
        this.updateSettings({ glow: Number(value) });
    }

    setHybridShellOpacity(value: string): void {
        this.updateSettings({ hybridShellOpacity: Number(value) });
    }

    setHopfSpaceIntensity(value: string): void {
        this.updateSettings({ hopfSpaceIntensity: Number(value) });
    }

    setLorentzSpaceIntensity(value: string): void {
        this.updateSettings({ lorentzSpaceIntensity: Number(value) });
    }

    setNodeDistance(value: string): void {
        this.updateSettings({ nodeDistance: Number(value) });
    }

    setEdgeLength(value: string): void {
        this.updateSettings({ edgeLength: Number(value) });
    }

    setEdgeWidth(value: string): void {
        this.updateSettings({ edgeWidth: Number(value) });
    }

    setCurveStrength(value: string): void {
        this.updateSettings({ edgeCurveStrength: Number(value) });
    }

    setParticleSize(value: string): void {
        this.updateSettings({ particleSize: Number(value) });
    }

    setParticleSpeed(value: string): void {
        this.updateSettings({ particleSpeed: Number(value) });
    }

    setParticleOpacity(value: string): void {
        this.updateSettings({ particleOpacity: Number(value) });
    }

    activeNodes(): GalaxyRenderableNode[] {
        return this.activeGraph().nodes;
    }

    activeEdges(): AtlasPreviewEdge[] {
        return this.activeGraph().graphEdges;
    }

    toggleDetailCards(): void {
        this.updateSettings({ detailCardsVisible: !this.settings.detailCardsVisible });
        this.closeCanvasInspector();
    }

    activeSceneIdentity(): string {
        const snapshot = this.graphSnapshotSignal();
        if (!snapshot || (this.atlasMode !== 'graph' && !this.usesGraphRebuildEmbeddingAtlas())) return '';
        return this.sceneIdentityForManifold(
            snapshot,
            this.manifoldMode(),
            this.atlasMode,
            this.queryTrace()?.queryNode.id || '',
        );
    }

    activeNodeCount(): number {
        return this.activeNodes().length;
    }

    activeEdgeCount(): number {
        return this.activeEdges().length;
    }

    registryAnchorCount(): number {
        return this.entities.length;
    }

    projectionSidecarNodeCount(): number {
        return this.displayEmbeddingAtlas().nodes.length;
    }

    primaryCountLabel(): string {
        if (this.atlasMode === 'entities') return 'registry entities';
        if (this.atlasMode === 'graph') return 'graph nodes';
        if (this.usesGraphRebuildEmbeddingAtlas()) return 'embedding targets';
        if (this.manifoldMode() === 'siegel') return 'finsler nodes';
        return this.manifoldMode() === 'lorentz' ? 'canvas nodes' : 'semantic vectors';
    }

    secondaryCountLabel(): string {
        if (this.atlasMode === 'entities') return 'registry links';
        if (this.atlasMode === 'graph') return 'graph edges';
        if (this.usesGraphRebuildEmbeddingAtlas()) return 'snapshot links';
        if (this.manifoldMode() === 'siegel') return 'directed links';
        return this.manifoldMode() === 'lorentz' ? 'cap links' : 'candidate links';
    }

    dataSourceLabel(): string {
        if (this.atlasMode === 'entities') return 'Registry';
        if (this.atlasMode === 'graph') return this.graphSnapshotSignal()?.atlasPacket?.sourceContract.authority || 'Graph Rebuild Snapshot';
        if (this.usesGraphRebuildEmbeddingAtlas()) return `Graph Rebuild Snapshot -> ${this.currentProjectionLabel()} Space`;
        if (this.manifoldMode() === 'lorentz') return 'Hierarchy Caps Sidecar';
        if (this.manifoldMode() === 'hopf') return 'Semantic Atlas -> Hopf Projection';
        if (this.manifoldMode() === 'product') return 'Semantic Atlas -> Transit Space';
        if (this.manifoldMode() === 'siegel') return 'Semantic Atlas -> Siegel-Finsler Space';
        return 'Semantic Atlas -> Hybrid Space';
    }

    atlasTruth(): { source: string; scopeId: string; snapshotId: string; builtAt: string; lens: string; layout: string; vectors: string } | null {
        const packet = this.graphSnapshotSignal()?.atlasPacket;
        if (!packet) return null;
        const layout = this.atlasMode === 'entities'
            ? 'registry / single'
            : `${this.manifoldMode()} / ${this.settings.layoutMode}`;
        const lens = this.atlasMode === 'graph'
            ? `lens ${this.canvasLens()}`
            : this.atlasMode === 'embeddings'
                ? `lens ${this.currentProjectionLabel()}`
                : 'lens registry';
        return {
            source: packet.sourceContract.authority || 'rust-atlas-packet',
            scopeId: compactTruthId(packet.scopeId),
            snapshotId: compactTruthId(packet.snapshotId),
            builtAt: builtAtTruthLabel(packet.builtAt),
            lens,
            layout,
            vectors: vectorTruthLabel(packet.counters.modelVectors, packet.sourceContract.vectorContract),
        };
    }

    graphAnchorCount(): number {
        return this.graphCounters?.acceptedAnchors ?? 0;
    }

    graphChunkCount(): number {
        return this.graphCounters?.chunks ?? 0;
    }

    graphAcceptedRelationshipCount(): number {
        return this.graphCounters?.acceptedRelationships ?? 0;
    }

    graphReviewRelationshipCount(): number {
        return this.graphCounters?.reviewRelationships ?? 0;
    }

    graphDropCount(): number {
        const drops = this.graphCounters?.dropReasons;
        return drops ? drops.missingEntity + drops.invalidSpan + drops.duplicateAnchor + drops.singletonBucket : 0;
    }

    isAtlasSurfaceActive(): boolean {
        return this.activeNodeCount() > 0
            && this.hubService.activeTab() === 'graph'
            && (this.hubService.isPageMode() || this.hubService.isHubOpen());
    }

    emptyTitle(): string {
        if (this.atlasMode === 'graph') return 'No accepted graph anchors yet';
        if (this.atlasMode === 'entities') return 'No entities yet';
        if (this.manifoldMode() === 'hopf') return 'No Hopf manifold yet';
        if (this.manifoldMode() === 'lorentz') return 'No hierarchy caps yet';
        if (this.manifoldMode() === 'siegel') return 'No Siegel-Finsler space yet';
        return 'No Semantic Atlas embeddings yet';
    }

    emptyMessage(): string {
        if (this.atlasMode === 'graph') return this.graphEmptyMessage();
        if (this.atlasMode === 'entities') return 'Add or extract entities and the atlas will start drawing the scope.';
        if (this.manifoldMode() === 'hopf') return 'Index the Semantic Atlas from the rendered graph, then project the existing vectors into Hopf space.';
        if (this.manifoldMode() === 'lorentz') return 'Index the Semantic Atlas from the rendered graph, then project it into hierarchy caps.';
        if (this.manifoldMode() === 'siegel') return 'Index the Semantic Atlas from the rendered graph, then project directed structure into Siegel-Finsler space.';
        return 'Index the Semantic Atlas from rendered leaves, documents, entities, and context lanes. A local preview is shown only when native vectors are unavailable.';
    }

    private graphEmptyMessage(): string {
        const counters = this.graphCounters;
        if (!counters || counters.entities === 0) return 'Alex has no registered entities in this lens yet.';
        if (counters.chunks === 0) return 'Graph rebuild has no chunks for this lens yet. Dynamic chunking or note-block projection must run before projection.';
        if (counters.acceptedAnchors === 0) return 'NER or dictionary matching produced no accepted Alex anchors in this lens.';
        if (counters.nodes < 2) return 'Only one Alex entity has anchors in this lens, so no relationship edge can be formed yet.';
        return 'Anchors exist, but no two entities share a note or chunk bucket yet.';
    }

    canvasQueryFocus() {
        const trace = this.queryTrace();
        if (trace) return {
            queryNodeId: trace.queryNode.id,
            primaryNodeIds: trace.primaryIds,
            secondaryNodeIds: trace.secondaryIds,
            edgeIds: trace.edgeIds,
        };
        return buildCanvasSearchFocus(this.atlasSearch, this.activeNodes(), this.activeEdges());
    }

    activePreview(): EmbeddingSourcePreview | null {
        if (this.atlasMode !== 'embeddings') return null;
        const trace = this.queryTrace();
        const node = this.hoveredEntity || (this.selectedEntityId ? this.activeNodes().find((item) => item.id === this.selectedEntityId) : null);
        if (!trace || !node) return null;
        if (node.id === trace.queryNode.id) {
            return { nodeId: node.id, label: 'Query star', score: 1, sourceType: 'query', preview: trace.query };
        }
        return trace.previews.find((preview) => preview.nodeId === node.id) ?? null;
    }

    private updateSettings(patch: Partial<GalaxyRenderSettings>): void {
        this.settings = mergeGalaxySettings({ ...this.settings, ...patch });
        this.persistViewState();
    }

    private persistViewState(): void {
        setSetting<PersistedAtlasViewState>(GRAPH_ATLAS_VIEW_STATE_KEY, {
            atlasMode: this.atlasMode,
            viewMode: this.viewMode,
            manifoldMode: this.manifoldMode(),
            settings: this.settings,
            graphKindFilter: this.graphKindFilter(),
            canvasLens: this.canvasLens(),
            controlsCollapsed: this.controlsCollapsed,
        });
    }

    private setEmbeddingAtlasForMode(mode: AtlasManifoldMode, atlas: EmbeddingAtlasData): void {
        this.embeddingAtlasByMode.update((atlases) => ({ ...atlases, [mode]: atlas }));
    }

    private bumpReadContext(): void {
        this.readContextEpoch.update((value) => value + 1);
        this.activeGraphCache = null;
    }

    currentLensState(): GraphLensState {
        return graphLensState(this._lensMode, this._primaryNoteId, this._selectedNoteIds);
    }

    private currentReadContext(): GraphAtlasReadContext {
        return buildGraphAtlasReadContext(this.currentLensState());
    }

    private graphKindTotal(...kinds: string[]): number {
        const accepted = new Set(kinds.map((kind) => normalizeGraphKind(kind)));
        return this.graphInventory().kindCounts
            .filter((bucket) => accepted.has(normalizeGraphKind(bucket.kind)))
            .reduce((sum, bucket) => sum + bucket.count, 0);
    }

    private semanticAtlasIsCurrent(): boolean {
        const atlas = this.displayEmbeddingAtlas();
        if (!atlas.nodes.length) return false;
        const source = `${atlas.sourceLabel || ''} ${atlas.manifold?.projectionSource || ''}`.toLowerCase();
        return !/preview|fallback|synthetic|not loaded|unavailable/.test(source);
    }

    private canRefreshCurrentProjection(): boolean {
        return this.semanticAtlasIsCurrent() && this.machine.vectorStatus() === 'ready';
    }

    private scheduleManifoldScenePrewarm(snapshot: GraphRebuildSnapshot | null): void {
        const generation = ++this.manifoldPrewarmGeneration;
        if (!snapshot || this.atlasMode !== 'embeddings' || graphRebuildEmbeddingTargetCount(snapshot) === 0) return;
        const activeMode = this.manifoldMode();
        const modes = [activeMode, ...ATLAS_MANIFOLD_MODE_LIST.filter((mode) => mode !== activeMode)];
        const baseSettings = this.settings;
        const runNext = () => scheduleGraphIdleWork(() => {
            if (
                this.destroyed ||
                generation !== this.manifoldPrewarmGeneration ||
                this.graphSnapshotSignal() !== snapshot ||
                this.atlasMode !== 'embeddings'
            ) return;
            const mode = modes.shift();
            if (!mode) return;
            void this.prewarmManifoldScene(snapshot, mode, baseSettings)
                .catch(() => undefined)
                .finally(runNext);
        });
        runNext();
    }

    private async prewarmManifoldScene(
        snapshot: GraphRebuildSnapshot,
        mode: AtlasManifoldMode,
        baseSettings: GalaxyRenderSettings,
    ): Promise<void> {
        const atlas = cachedGraphRebuildEmbeddingAtlas(snapshot, mode);
        const settings = mergeGalaxySettings({
            ...baseSettings,
            layoutMode: this.layoutForManifold(mode),
            sourceMode: 'embeddings',
        });
        await compileGalaxyScene(
            this.phoenix,
            atlas.nodes,
            atlas.edges,
            settings,
            this.sceneIdentityForManifold(snapshot, mode, 'embeddings'),
        );
    }

    private sceneIdentityForManifold(
        snapshot: GraphRebuildSnapshot,
        mode: AtlasManifoldMode,
        atlasMode: AtlasMode,
        traceIdentity = '',
    ): string {
        const graphIdentity = snapshot.authorityContract?.contentHash || snapshot.id;
        return [
            graphIdentity,
            atlasMode,
            mode,
            this.canvasLens(),
            this.graphKindFilter(),
            traceIdentity,
        ].join('\u0000');
    }

    private currentProjectionLabel(): string {
        return manifoldAdapter(this.manifoldMode()).label;
    }

    private displayEmbeddingAtlas(): EmbeddingAtlasData {
        return this.graphRebuildEmbeddingAtlas() ?? this.embeddingAtlas();
    }

    usesGraphRebuildEmbeddingAtlas(): boolean {
        return this.atlasMode === 'embeddings' && !!this.graphRebuildEmbeddingAtlas();
    }

    private async refreshCurrentProjectionView(context: GraphAtlasReadContext): Promise<void> {
        if (this.isRefreshingProjection) return;
        this.isRefreshingProjection = true;
        const mode = this.manifoldMode();
        try {
            this.atlasLoadedKeys.delete(mode);
            await this.refreshEmbeddingAtlas(context, mode, true);
        } finally {
            this.isRefreshingProjection = false;
        }
    }

    private layoutForManifold(mode: AtlasManifoldMode): GalaxyLayoutMode {
        if (mode === 'product') return 'transitManifold';
        if (mode === 'hopf') return 'hopfProjection';
        if (mode === 'lorentz') return 'lorentzTree';
        if (mode === 'siegel') return 'siegelFinsler';
        return 'hybridSpace';
    }

    private layoutPatchForManifold(mode: AtlasManifoldMode): Partial<GalaxyRenderSettings> & { layoutMode: GalaxyLayoutMode } {
        const layoutMode = this.layoutForManifold(mode);
        return layoutMode === 'hybridSpace' ? this.hybridShellLayoutPatch(layoutMode) : { layoutMode };
    }

    private hybridShellLayoutPatch(layoutMode: GalaxyLayoutMode): Partial<GalaxyRenderSettings> & { layoutMode: GalaxyLayoutMode } {
        return {
            layoutMode,
            edgeMode: 'hidden',
            hybridHorospheresVisible: true,
            hybridShellOpacity: Math.min(this.settings.hybridShellOpacity, 0.72),
        };
    }

    private activeGraph(): ActiveAtlasGraph {
        const atlas = this.displayEmbeddingAtlas();
        const trace = this.queryTrace();
        const graphInventory = this.graphInventory();
        const graphKindFilter = this.graphKindFilter();
        const canvasLens = this.canvasLens();
        const cached = this.activeGraphCache;
        if (
            cached &&
            cached.mode === this.atlasMode &&
            cached.entities === this.entities &&
            cached.edges === this.edges &&
            cached.atlas === atlas &&
            cached.trace === trace &&
            cached.graphInventory === graphInventory &&
            cached.graphKindFilter === graphKindFilter &&
            cached.canvasLens === canvasLens
        ) {
            return cached;
        }

        if (this.atlasMode === 'entities') {
            const kindOrder = registryEntityKindOrder(this.entities);
            const nodes = this.entities.map((entity, index) => this.registryEntityProjectionNode(
                entity,
                index,
                this.entities.length,
                kindOrder,
            ));
            this.activeGraphCache = {
                mode: this.atlasMode,
                entities: this.entities,
                edges: this.edges,
                atlas,
                trace,
                graphInventory,
                graphKindFilter,
                canvasLens,
                nodes,
                graphEdges: this.edges,
            };
            return this.activeGraphCache;
        }

        if (this.atlasMode === 'graph') {
            const projectionAtlas = this.graphModeProjectionAtlas();
            if (projectionAtlas) {
                const projectionSlice = graphProjectionParitySlice(projectionAtlas, canvasLens, graphKindFilter);
                this.activeGraphCache = {
                    mode: this.atlasMode,
                    entities: this.entities,
                    edges: this.edges,
                    atlas,
                    trace,
                    graphInventory,
                    graphKindFilter,
                    canvasLens,
                    nodes: projectionSlice.nodes,
                    graphEdges: projectionSlice.edges,
                };
                return this.activeGraphCache;
            }
            const lensSlice = filterGraphForCanvasLens(graphInventory.nodes, graphInventory.edges, canvasLens);
            const allowed = graphKindFilter === 'all' ? null : new Set(
                lensSlice.nodes.filter((node) => normalizeGraphKind(node.kind) === graphKindFilter).map((node) => node.id),
            );
            const nodes = allowed ? lensSlice.nodes.filter((node) => allowed.has(node.id)) : lensSlice.nodes;
            const graphEdges = allowed
                ? lensSlice.edges.filter((edge) => allowed.has(edge.sourceId) && allowed.has(edge.targetId))
                : lensSlice.edges;
            this.activeGraphCache = {
                mode: this.atlasMode,
                entities: this.entities,
                edges: this.edges,
                atlas,
                trace,
                graphInventory,
                graphKindFilter,
                canvasLens,
                nodes,
                graphEdges,
            };
            return this.activeGraphCache;
        }

        const embeddingNodes = this.embeddingNodesWithEntityAnchors();
        const embeddingEdges = this.embeddingEdgesWithEntityAnchors();
        this.activeGraphCache = {
            mode: this.atlasMode,
            entities: this.entities,
            edges: this.edges,
            atlas,
            trace,
            graphInventory,
            graphKindFilter,
            canvasLens,
            nodes: trace ? [trace.queryNode, ...embeddingNodes] : embeddingNodes,
            graphEdges: trace ? [...trace.edges, ...embeddingEdges] : embeddingEdges,
        };
        return this.activeGraphCache;
    }

    private graphModeProjectionAtlas(): EmbeddingAtlasData | null {
        if (!graphProjectionParityApplies(this.settings.layoutMode, this.manifoldMode())) return null;
        return this.graphRebuildEmbeddingAtlas();
    }

    private embeddingNodesWithEntityAnchors(): GalaxyRenderableNode[] {
        const atlas = this.displayEmbeddingAtlas();
        if (this.usesGraphRebuildEmbeddingAtlas()) return atlas.nodes;
        if (!this.entities.length) return atlas.nodes;
        const anchors = completeRegistryEntityProjection(this.entities).map((entity, index) => {
            const sourceSystem = entitySourceSystem(entity as RegisteredEntity);
            const matches = matchingEmbeddingNodes(entity, atlas.nodes).slice(0, 8);
            const point = matches.length
                ? averageAtlasPoint(matches)
                : fallbackEntityPoint(entity.id, index, this.entities.length);
            return {
                id: `embed:entity:${entity.id}`,
                label: entity.label,
                kind: entity.kind,
                aliases: entity.aliases,
                totalMentions: Math.max(4, entity.totalMentions || matches.length || 1),
                atlasX: point.x,
                atlasY: point.y,
                atlasZ: point.z,
                colorHsl: entity.colorHsl,
                metadata: {
                    ...entity.metadata,
                    sourceType: 'entity',
                    sourceSystem,
                    sourceEntityId: entity.id,
                    galaxyId: `embed:entity:${entity.id}`,
                    galaxyRole: 'primary',
                    preview: matches.length ? `Anchored by ${matches.length} nearby text vector${matches.length === 1 ? '' : 's'}.` : 'Registry entity anchor.',
                },
            } satisfies GalaxyRenderableNode;
        });
        return [...atlas.nodes, ...anchors];
    }

    cycleSphereSurface(): void {
        const current = this.settings.sphereSurface || 'solid';
        const index = SPHERE_SURFACE_CYCLE.indexOf(current);
        this.updateSettings({ sphereSurface: SPHERE_SURFACE_CYCLE[(index + 1) % SPHERE_SURFACE_CYCLE.length] });
    }

    sphereSurfaceLabel(): string {
        return SPHERE_SURFACE_LABELS[this.settings.sphereSurface || 'solid'];
    }

    private registryEntityProjectionNode(
        entity: GalaxyRenderableNode,
        index: number,
        total: number,
        kindOrder: Map<string, number>,
    ): GalaxyRenderableNode {
        const sourceNode = this.entityNodeWithSource(entity);
        const normalizedKind = String(sourceNode.kind || 'entity').trim().toLowerCase() || 'entity';
        const point = registryEntityProjectionPoint(
            sourceNode,
            index,
            total,
            kindOrder.get(normalizedKind),
            kindOrder.size,
        );
        return {
            ...sourceNode,
            atlasX: point.x,
            atlasY: point.y,
            atlasZ: point.z,
            metadata: {
                ...sourceNode.metadata,
                projectionSpace: REGISTRY_ENTITY_PROJECTION_SPACE,
                projectionPhase: point.phase,
                projectionBand: point.band,
            },
        };
    }

    private entityNodeWithSource(entity: GalaxyRenderableNode): GalaxyRenderableNode {
        const sourceSystem = entitySourceSystem(entity as RegisteredEntity);
        return {
            ...entity,
            metadata: {
                ...entity.metadata,
                sourceType: entity.metadata?.sourceType || 'registry_entity',
                sourceSystem,
            },
        };
    }

    private embeddingEdgesWithEntityAnchors(): AtlasPreviewEdge[] {
        const atlas = this.displayEmbeddingAtlas();
        if (this.usesGraphRebuildEmbeddingAtlas()) return atlas.edges;
        if (!this.entities.length || !atlas.nodes.length) return atlas.edges;
        const anchorEdges: AtlasPreviewEdge[] = [];
        for (const entity of completeRegistryEntityProjection(this.entities)) {
            const matches = matchingEmbeddingNodes(entity, atlas.nodes).slice(0, 5);
            for (const [index, node] of matches.entries()) {
                anchorEdges.push({
                    id: `embed:entity-edge:${entity.id}:${node.id}`,
                    sourceId: `embed:entity:${entity.id}`,
                    targetId: node.id,
                    type: 'entity-embedding-anchor',
                    confidence: 1.4 - index * 0.12,
                });
            }
        }
        return [...atlas.edges, ...anchorEdges];
    }

    private async refreshEmbeddingAtlas(context: GraphAtlasReadContext, manifold: AtlasManifoldMode, force = false): Promise<void> {
        const requestKey = manifoldProjectionRequestKey(this.graphSnapshotSignal(), manifold, context.key);
        if (!force && this.atlasLoadingKeys.get(manifold) === requestKey) return;
        if (!force && this.atlasLoadedKeys.get(manifold) === requestKey && this.machine.manifoldStatuses()[manifold] === 'ready') return;

        this.atlasLoadingKeys.set(manifold, requestKey);
        const load = this.machine.beginManifoldLoad(manifold);
        try {
            const adapter = manifoldAdapter(manifold);
            const projection = await loadManifoldProjection(
                this.graphSnapshotSignal(),
                manifold,
                () => adapter.load(this.phoenixUiApi, context.searchScope),
            );
            const atlas = projection.atlas;
            if (this.machine.isCurrentManifoldLoad(load)) {
                if (projection.source === 'native-manifold-snapshot') {
                    this.setEmbeddingAtlasForMode(manifold, atlas);
                }
                this.atlasLoadedKeys.set(manifold, requestKey);
                if (this.manifoldMode() === manifold) {
                    this.queryTrace.set(adapter.trace(this.queryText(), atlas));
                }
                this.machine.finishManifoldLoad(load, `${adapter.label} manifold ready`, {
                    owner: 'graph-atlas-preview',
                    nodes: atlas.nodes.length,
                    edges: atlas.edges.length,
                    sourceLabel: atlas.sourceLabel,
                    projectionSource: projection.source,
                    nativeRoundTrips: projection.source === 'graph-rebuild-snapshot' ? 0 : 1,
                });
            }
        } catch (error) {
            console.warn('[GraphAtlasPreview] Failed to load manifold atlas', error);
            if (this.machine.isCurrentManifoldLoad(load)) {
                this.setEmbeddingAtlasForMode(manifold, emptyEmbeddingAtlas(`${manifold} manifold unavailable`));
                this.atlasLoadedKeys.set(manifold, requestKey);
                if (this.manifoldMode() === manifold) {
                    this.queryTrace.set(null);
                }
                this.machine.failManifoldLoad(load, error);
            }
        } finally {
            if (this.atlasLoadingKeys.get(manifold) === requestKey) {
                this.atlasLoadingKeys.delete(manifold);
            }
        }
    }
}

function scheduleGraphIdleWork(callback: () => void): void {
    if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(() => callback(), { timeout: 750 });
        return;
    }
    setTimeout(callback, 16);
}

function emptyEmbeddingAtlas(sourceLabel: string): EmbeddingAtlasData {
    return { nodes: [], edges: [], sourceLabel, searchIndex: [] };
}

function compactTruthId(value: string): string {
    const text = String(value || 'unknown');
    if (text.length <= 18) return text;
    return `${text.slice(0, 8)}...${text.slice(-6)}`;
}

function builtAtTruthLabel(value: number): string {
    if (!Number.isFinite(value) || value <= 0) return 'unknown';
    const millis = value > 10_000_000_000 ? value : value * 1000;
    const date = new Date(millis);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toISOString().replace('T', ' ').slice(0, 16);
}

function vectorTruthLabel(modelVectors: number, contract: string): string {
    if (modelVectors > 0) return `model ${modelVectors}`;
    const normalized = String(contract || '').replace(/[_-]+/g, ' ').trim().toLowerCase();
    if (!normalized || normalized.includes('missing') || normalized.includes('no model') || normalized.includes('none')) return 'missing';
    if (normalized.includes('model')) return 'model';
    return 'missing';
}

function normalizeGraphKind(kind: string): string {
    return String(kind || 'generic').trim().toLowerCase().replace(/[_\s]+/g, '-');
}

function matchingEmbeddingNodes(entity: GalaxyRenderableNode, nodes: GalaxyRenderableNode[]): GalaxyRenderableNode[] {
    const needles = [entity.label, ...(entity.aliases || [])]
        .map((value) => value.trim().toLowerCase())
        .filter((value) => value.length >= 2);
    if (!needles.length) return [];
    return nodes.filter((node) => {
        const metadata = node.metadata || {};
        const haystack = `${node.label} ${String(metadata['preview'] || '')}`.toLowerCase();
        return needles.some((needle) => containsWordish(haystack, needle));
    });
}

function containsWordish(haystack: string, needle: string): boolean {
    const index = haystack.indexOf(needle);
    if (index < 0) return false;
    const before = index === 0 ? ' ' : haystack[index - 1];
    const after = index + needle.length >= haystack.length ? ' ' : haystack[index + needle.length];
    return !isWordChar(before) && !isWordChar(after);
}

function isWordChar(value: string): boolean {
    return /[a-z0-9_]/i.test(value);
}

function averageAtlasPoint(nodes: GalaxyRenderableNode[]): { x: number; y: number; z: number } {
    let x = 0;
    let y = 0;
    let z = 0;
    for (const node of nodes) {
        x += Number(node.atlasX || 0);
        y += Number(node.atlasY || 0);
        z += Number(node.atlasZ || 0);
    }
    const scale = 1 / Math.max(1, nodes.length);
    return { x: x * scale, y: y * scale, z: z * scale };
}

function fallbackEntityPoint(id: string, index: number, total: number): { x: number; y: number; z: number } {
    const angle = index * 2.399963229728653;
    const radius = 0.38 + (hashUnit(id) * 0.32);
    const y = total > 1 ? 0.7 - (index / (total - 1)) * 1.4 : 0;
    return {
        x: Math.cos(angle) * radius,
        y,
        z: Math.sin(angle) * radius,
    };
}

function hashUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}
