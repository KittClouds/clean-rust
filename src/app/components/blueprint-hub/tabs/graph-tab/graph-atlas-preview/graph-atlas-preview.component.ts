import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output, ViewChild, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Plus, Search, SlidersHorizontal, Zap } from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import { entitySourceSystem, type RegisteredEntity } from '../../../../../lib/registry';
import type { EntitySuggestionProviderId } from '../../../../../lib/entity-suggestions/entity-suggestion.types';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import { PhoenixUiApiService } from '../../../../../services/phoenix-ui-api.service';
import type { PhoenixGraphDeltaBinaryResult } from '../../../../../services/phoenix-wasm.service';
import { PhoenixMachineControlService } from '../../../../../services/phoenix-machine-control.service';
import type { AtlasManifoldMode } from '../../../../../services/manifold-atlas.types';
import { buildAtlasCountReconciliation } from '../../../../../services/atlas-count-ledger.model';
import { BlueprintHubService } from '../../../blueprint-hub.service';
import type { GraphRebuildCounters, GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { type EmbeddingAtlasData, type EmbeddingQueryTrace, type EmbeddingSourcePreview } from './graph-embedding-atlas';
import { manifoldAdapter } from './graph-manifold-atlas';
import { buildGraphRebuildEmbeddingAtlas } from './graph-rebuild-embedding-atlas';
import {
    registryEntityKindOrder,
    registryEntityProjectionPoint,
    REGISTRY_ENTITY_PROJECTION_SPACE,
} from './graph-registry-entity-projection';
import { GraphGalaxyCanvasComponent } from './graph-galaxy-canvas.component';
import {
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
} from './graph-galaxy-engine';
import type { GraphLensMode, GraphLensState } from '../graph-lens';
import { buildGraphAtlasReadContext, graphLensState, type GraphAtlasReadContext } from './graph-atlas-read-context';
import { projectionSummaryRequestsRefresh } from './graph-atlas-refresh-summary';
import { getSetting, setSetting } from '../../../../../lib/dexie/settings.service';

export interface AtlasPreviewEdge extends GalaxyInputEdge {}

interface ActiveAtlasGraph {
    mode: AtlasMode;
    entities: GalaxyRenderableNode[];
    edges: AtlasPreviewEdge[];
    atlas: EmbeddingAtlasData;
    trace: EmbeddingQueryTrace | null;
    graphInventory: GraphInventory;
    graphKindFilter: string;
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
const ATLAS_MANIFOLD_MODES = new Set<AtlasManifoldMode>(['hybrid', 'hopf', 'lorentz', 'product', 'siegel']);

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
        controlsCollapsed: stored.controlsCollapsed === true,
    };
}

@Component({
    selector: 'app-graph-atlas-preview',
    standalone: true,
    imports: [CommonModule, FormsModule, LucideAngularModule, GraphGalaxyCanvasComponent],
    template: `
        <section class="atlas-preview-surface relative h-full min-h-[520px] overflow-hidden rounded-none border border-white/5 bg-[#02040a] shadow-[0_24px_80px_rgba(0,0,0,0.24)]" [attr.data-backdrop]="settings.backgroundMode">
            <div class="relative z-10 flex h-full min-h-[520px] flex-col p-px">
                <div class="pointer-events-none absolute left-5 right-5 top-5 z-30 flex items-start justify-between gap-3">
                    <div class="flex min-w-0 items-start gap-2">
                        <button type="button"
                            class="canvas-chrome-toggle"
                            [class.canvas-chrome-toggle-active]="controlsCollapsed"
                            [attr.aria-label]="controlsCollapsed ? 'Show atlas controls' : 'Hide atlas controls'"
                            (click)="toggleControlsCollapsed()">
                            <lucide-icon [img]="SlidersIcon" class="h-4 w-4"></lucide-icon>
                        </button>
                    @if (!controlsCollapsed) {
                    <div class="canvas-control-rail flex min-w-0 flex-wrap items-center gap-2 rounded-2xl px-2 py-1.5">
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="atlasMode === 'entities'" [class.text-cyan-100]="atlasMode === 'entities'"
                                [class.text-zinc-500]="atlasMode !== 'entities'" (click)="setAtlasMode('entities')">Entities</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="atlasMode === 'graph'" [class.text-cyan-100]="atlasMode === 'graph'"
                                [class.text-zinc-500]="atlasMode !== 'graph'" (click)="setAtlasMode('graph')">Graph</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="atlasMode === 'embeddings'" [class.text-cyan-100]="atlasMode === 'embeddings'"
                                [class.text-zinc-500]="atlasMode !== 'embeddings'" (click)="setAtlasMode('embeddings')">Embeddings</button>
                        </div>
                        <span class="rounded-full border border-cyan-400/15 bg-cyan-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-100">{{ primaryCountLabel() }} {{ activeNodeCount() }}</span>
                        <span class="rounded-full border border-violet-400/15 bg-violet-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-100">{{ secondaryCountLabel() }} {{ activeEdgeCount() }}</span>
                        <span class="rounded-full border border-amber-300/15 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-100">Source: {{ dataSourceLabel() }}</span>
                        @if (atlasMode === 'graph') {
                        <span class="rounded-full border border-emerald-300/15 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-100">Anchors {{ graphAnchorCount() }}</span>
                        <span class="rounded-full border border-sky-300/15 bg-sky-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-sky-100">Chunks {{ graphChunkCount() }}</span>
                        <span class="rounded-full border border-teal-300/15 bg-teal-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-100">Accepted {{ graphAcceptedRelationshipCount() }}</span>
                        <span class="rounded-full border border-fuchsia-300/15 bg-fuchsia-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-fuchsia-100">Review {{ graphReviewRelationshipCount() }}</span>
                        <span class="rounded-full border border-rose-300/15 bg-rose-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-rose-100">Drops {{ graphDropCount() }}</span>
                        }
                        @if (atlasMode === 'embeddings') {
                        <span class="rounded-full border border-cyan-400/15 bg-cyan-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-100">Input graph: {{ semanticGraphAvailabilityLabel() }}</span>
                        }
                        @if (hopfReceiptSummary(); as hopf) {
                        <span class="rounded-full border border-sky-300/15 bg-sky-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-sky-100">Hopf receipts {{ hopf.assignments }} / {{ hopf.occupiedCells }} cells / {{ hopf.docCharts }} charts / {{ hopf.braids }} braids</span>
                        }
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="viewMode === '3d'" [class.text-cyan-100]="viewMode === '3d'"
                                [class.text-zinc-500]="viewMode !== '3d'" (click)="setViewMode('3d')">3D</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="viewMode === 'map'" [class.text-cyan-100]="viewMode === 'map'"
                                [class.text-zinc-500]="viewMode !== 'map'" (click)="setViewMode('map')">Map</button>
                        </div>
                        @if (atlasMode === 'embeddings') {
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'hybrid'" [class.text-violet-100]="manifoldMode() === 'hybrid'"
                                [class.text-zinc-500]="manifoldMode() !== 'hybrid'" (click)="setManifoldMode('hybrid')">Hybrid</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'hopf'" [class.text-violet-100]="manifoldMode() === 'hopf'"
                                [class.text-zinc-500]="manifoldMode() !== 'hopf'" (click)="setManifoldMode('hopf')">Hopf</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'lorentz'" [class.text-violet-100]="manifoldMode() === 'lorentz'"
                                [class.text-zinc-500]="manifoldMode() !== 'lorentz'" (click)="setManifoldMode('lorentz')">Caps</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'product'" [class.text-violet-100]="manifoldMode() === 'product'"
                                [class.text-zinc-500]="manifoldMode() !== 'product'" (click)="setManifoldMode('product')">Product</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-violet-500/20]="manifoldMode() === 'siegel'" [class.text-violet-100]="manifoldMode() === 'siegel'"
                                [class.text-zinc-500]="manifoldMode() !== 'siegel'" (click)="setManifoldMode('siegel')">Siegel</button>
                        </div>
                        @if (manifoldMode() === 'hybrid') {
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="settings.layoutMode === 'hybridSpace'" [class.text-cyan-100]="settings.layoutMode === 'hybridSpace'"
                                [class.text-zinc-500]="settings.layoutMode !== 'hybridSpace'" (click)="setLayoutMode('hybridSpace')">Shell</button>
                            <button type="button" class="rounded-lg px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition"
                                [class.bg-cyan-500/15]="settings.layoutMode === 'multiGalaxy'" [class.text-cyan-100]="settings.layoutMode === 'multiGalaxy'"
                                [class.text-zinc-500]="settings.layoutMode !== 'multiGalaxy'" (click)="setLayoutMode('multiGalaxy')">Multi</button>
                        </div>
                        } @else if (manifoldMode() === 'hopf') {
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg bg-cyan-500/15 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100 transition"
                                (click)="setLayoutMode('hopfProjection')">Projection</button>
                        </div>
                        } @else if (manifoldMode() === 'lorentz') {
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg bg-cyan-500/15 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100 transition"
                                (click)="setLayoutMode('lorentzTree')">Caps</button>
                        </div>
                        } @else if (manifoldMode() === 'siegel') {
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg bg-cyan-500/15 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100 transition"
                                (click)="setLayoutMode('siegelFinsler')">Finsler</button>
                        </div>
                        } @else {
                        <div class="flex rounded-xl border border-white/10 bg-black/40 p-1">
                            <button type="button" class="rounded-lg bg-cyan-500/15 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100 transition"
                                (click)="setLayoutMode('productManifold')">Transit</button>
                        </div>
                        }
                        }
                        <div class="flex shrink-0 items-center gap-2">
                            <button type="button" class="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-semibold text-zinc-200 transition hover:border-cyan-400/20 hover:bg-cyan-500/10"
                                (click)="resetCamera()">Reset</button>
                            <button type="button" class="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-semibold text-zinc-200 transition hover:border-cyan-400/20 hover:bg-cyan-500/10"
                                (click)="fitCamera()">Fit</button>
                        </div>
                    </div>
                    }
                    </div>

                    <div class="flex shrink-0 items-start gap-2">
                        <div class="relative">
                            <button type="button"
                                class="canvas-glass-button rounded-xl px-3 py-1.5 text-xs font-semibold"
                                (click)="toggleLensMenu()">
                                {{ lensLabel() }} Lens
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
                            class="canvas-glass-button rounded-xl px-3 py-1.5 text-xs font-semibold"
                            (click)="toggleSettings()">
                            Settings
                        </button>
                    </div>
                </div>

                <div class="atlas-canvas-surface relative min-h-0 flex-1 overflow-hidden rounded-none border border-white/5 bg-[#02040a] p-px">
                    @if (activeNodeCount() === 0) {
                    <div class="flex h-full min-h-[430px] items-center justify-center rounded-none border border-dashed border-white/10 text-center">
                        <div>
                            <p class="text-lg font-semibold text-white">{{ emptyTitle() }}</p>
                            <p class="mt-2 max-w-md text-sm leading-6 text-zinc-500">{{ emptyMessage() }}</p>
                        </div>
                    </div>
                    } @else {
                    <app-graph-galaxy-canvas #galaxyCanvas class="block h-full min-h-0 w-full"
                        [entities]="activeNodes()" [edges]="activeEdges()" [settings]="settings" [selectedEntityId]="selectedEntityId"
                        [queryFocus]="canvasQueryFocus()" [viewMode]="viewMode" [sourceMode]="atlasMode" [surfaceActive]="isAtlasSurfaceActive()"
                        (entitySelected)="onCanvasEntitySelected($event)" (entityHovered)="hoveredEntity = $event"></app-graph-galaxy-canvas>
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
                        <div class="settings-toggle-grid">
                            <button type="button" class="galaxy-control-button" (click)="cycleLabelMode()">Labels<span>{{ settings.labelMode }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleEdgeMode()">Edges<span>{{ settings.edgeMode }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleEdgeColorMode()">Palette<span>{{ edgeColorLabel() }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="toggleParticles()">Flow<span>{{ settings.particleFlow ? 'on' : 'off' }}</span></button>
                            @if (atlasMode === 'embeddings') {
                            <button type="button" class="galaxy-control-button" (click)="cycleEmbeddingTopologyMode()">Topology<span>{{ embeddingTopologyLabel() }}</span></button>
                            }
                            <button type="button" class="galaxy-control-button" (click)="cycleNodeDragMode()">Drag<span>{{ settings.nodeDragMode }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="toggleClickFocus()">Dbl Focus<span>{{ settings.clickFocus ? 'on' : 'off' }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleNodeShape()">Shape<span>{{ settings.nodeShape }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="toggleAutoRotate()">Rotate<span>{{ settings.autoRotate ? 'on' : 'off' }}</span></button>
                            <button type="button" class="galaxy-control-button" (click)="cycleBackgroundMode()">Backdrop<span>{{ backgroundLabel() }}</span></button>
                            @if (settings.layoutMode === 'hybridSpace' || settings.layoutMode === 'productManifold') {
                            <button type="button" class="galaxy-control-button" (click)="toggleHybridShell()">Shell<span>{{ settings.hybridShellVisible ? 'on' : 'off' }}</span></button>
                            }
                            @if (settings.layoutMode === 'hybridSpace') {
                            <button type="button" class="galaxy-control-button" (click)="toggleHybridField()">Field<span>{{ settings.hybridHorospheresVisible ? 'on' : 'off' }}</span></button>
                            }
                            @if (settings.layoutMode === 'hopfProjection') {
                            <button type="button" class="galaxy-control-button" (click)="toggleHopfSpace()">Hopf Space<span>{{ settings.hopfSpaceVisible ? 'on' : 'off' }}</span></button>
                            }
                            @if (settings.layoutMode === 'lorentzTree' || settings.layoutMode === 'productManifold' || settings.layoutMode === 'siegelFinsler') {
                            <button type="button" class="galaxy-control-button" (click)="toggleLorentzSpace()">{{ settings.layoutMode === 'productManifold' ? 'Routes' : 'Cap Space' }}<span>{{ settings.lorentzSpaceVisible ? 'on' : 'off' }}</span></button>
                            }
                            @if (settings.layoutMode === 'productManifold') {
                            <button type="button" class="galaxy-control-button" (click)="toggleProductKlein()">Klein Ball<span>{{ settings.productKleinVisible ? 'on' : 'off' }}</span></button>
                            }
                        </div>
                        @if ((settings.layoutMode === 'hybridSpace' || settings.layoutMode === 'productManifold') && settings.hybridShellVisible) {
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
                        @if ((settings.layoutMode === 'lorentzTree' || settings.layoutMode === 'productManifold' || settings.layoutMode === 'siegelFinsler') && settings.lorentzSpaceVisible) {
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

        .canvas-control-rail { pointer-events: none; background: transparent; box-shadow: none; }
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
export class GraphAtlasPreviewComponent implements OnInit {
    private readonly phoenixUiApi = inject(PhoenixUiApiService);
    private readonly machine = inject(PhoenixMachineControlService);
    private readonly hubService = inject(BlueprintHubService);
    private graphLoadToken = 0;
    private readonly atlasLoadedKeys = new Map<AtlasManifoldMode, string>();
    private readonly atlasLoadingKeys = new Map<AtlasManifoldMode, string>();
    private activeGraphCache: ActiveAtlasGraph | null = null;
    private _lensMode: GraphLensMode = 'global';
    private _primaryNoteId: string | null = null;
    private _selectedNoteIds: string[] = [];
    private readonly readContextEpoch = signal(0);
    private readonly graphSnapshotSignal = signal<GraphRebuildSnapshot | null>(null);

    @Input() entities: GalaxyRenderableNode[] = [];
    @Input() edges: AtlasPreviewEdge[] = [];
    @Input() sourceLabel = 'registry graph';
    @Input() graphCounters: GraphRebuildCounters | null = null;
    @Input() set graphSnapshot(value: GraphRebuildSnapshot | null | undefined) {
        this.graphSnapshotSignal.set(value ?? null);
        this.activeGraphCache = null;
    }
    @Input() set committedGraphInventory(value: GraphInventory | null | undefined) {
        this.graphInventory.set(value ?? EMPTY_GRAPH_INVENTORY);
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
    @Output() styleRequested = new EventEmitter<void>();
    @Output() atlasModeChange = new EventEmitter<AtlasMode>();
    @Output() lensModeChange = new EventEmitter<GraphLensMode>();
    @Output() atlasSearchChange = new EventEmitter<string>();
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
    queryText = signal('');
    queryTrace = signal<EmbeddingQueryTrace | null>(null);
    readonly manifoldMode = this.machine.manifoldMode;
    readonly manifoldStatus = this.machine.manifoldStatus;
    private readonly embeddingAtlasByMode = signal<Record<AtlasManifoldMode, EmbeddingAtlasData>>({
        hybrid: emptyEmbeddingAtlas('hybrid atlas not loaded'),
        hopf: emptyEmbeddingAtlas('hopf atlas not loaded'),
        lorentz: emptyEmbeddingAtlas('lorentz forest not loaded'),
        product: emptyEmbeddingAtlas('product atlas not loaded'),
        siegel: emptyEmbeddingAtlas('siegel-finsler atlas not loaded'),
    });
    readonly embeddingAtlas = computed(() => this.embeddingAtlasByMode()[this.manifoldMode()]);
    readonly graphRebuildEmbeddingAtlas = computed(() => {
        const snapshot = this.graphSnapshotSignal();
        return snapshot?.embeddingTargets.length
            ? buildGraphRebuildEmbeddingAtlas(snapshot, this.manifoldMode())
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
    readonly PlusIcon = Plus;
    readonly SearchIcon = Search;
    readonly SlidersIcon = SlidersHorizontal;
    readonly ZapIcon = Zap;
    readonly lensModes: { id: GraphLensMode; label: string }[] = [
        { id: 'global', label: 'Global' },
        { id: 'narrative', label: 'Narrative' },
        { id: 'note', label: 'Note' },
        { id: 'multiNote', label: 'Compare' },
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
        this.atlasModeChange.emit(this.atlasMode);
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
        if (mode !== 'embeddings' && this.settings.layoutMode !== 'single') {
            this.updateSettings({ layoutMode: 'single' });
        } else if (mode === 'embeddings') {
            const layoutMode = this.layoutForManifold(this.manifoldMode());
            if (this.settings.layoutMode === 'single' || this.settings.layoutMode !== layoutMode && this.manifoldMode() !== 'hybrid') {
                this.updateSettings(layoutMode === 'hybridSpace'
                    ? { layoutMode, edgeMode: 'hidden', hybridHorospheresVisible: true, hybridShellOpacity: Math.min(this.settings.hybridShellOpacity, 0.72) }
                    : { layoutMode });
            }
            void this.refreshEmbeddingAtlas(this.currentReadContext(), this.manifoldMode());
        }
        this.persistViewState();
    }

    setGraphKindFilter(kind: string): void {
        this.graphKindFilter.set(kind);
        this.selectedEntityId = null;
        this.hoveredEntity = null;
        this.persistViewState();
    }

    setLayoutMode(mode: GalaxyLayoutMode): void {
        if (mode !== 'single' && this.atlasMode !== 'embeddings') return;
        if ((mode === 'hybridSpace' || mode === 'multiGalaxy') && this.manifoldMode() !== 'hybrid') {
            this.machine.setManifoldMode('hybrid');
        } else if (mode === 'hopfProjection' && this.manifoldMode() !== 'hopf') {
            this.machine.setManifoldMode('hopf');
        } else if (mode === 'lorentzTree' && this.manifoldMode() !== 'lorentz') {
            this.machine.setManifoldMode('lorentz');
        } else if (mode === 'productManifold' && this.manifoldMode() !== 'product') {
            this.machine.setManifoldMode('product');
        } else if (mode === 'siegelFinsler' && this.manifoldMode() !== 'siegel') {
            this.machine.setManifoldMode('siegel');
        }
        this.updateSettings(mode === 'hybridSpace'
            ? { layoutMode: mode, edgeMode: 'hidden', hybridHorospheresVisible: true, hybridShellOpacity: Math.min(this.settings.hybridShellOpacity, 0.72) }
            : { layoutMode: mode });
        this.persistViewState();
    }

    setManifoldMode(mode: AtlasManifoldMode): void {
        this.machine.setManifoldMode(mode);
        if (this.atlasMode !== 'embeddings') this.setAtlasMode('embeddings');
        const layoutMode = this.layoutForManifold(mode);
        if (this.settings.layoutMode !== layoutMode) this.updateSettings(layoutMode === 'hybridSpace'
            ? { layoutMode, edgeMode: 'hidden', hybridHorospheresVisible: true, hybridShellOpacity: Math.min(this.settings.hybridShellOpacity, 0.72) }
            : { layoutMode });
        this.queryTrace.set(null);
        this.selectedEntityId = null;
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
            const targets = atlas?.nodes.length ?? snapshot?.embeddingTargets.length ?? 0;
            const totalTargets = snapshot?.embeddingTargets.length ?? targets;
            const targetLabel = totalTargets > targets ? `${targets} visible / ${totalTargets} targets` : `${targets} targets`;
            const chunks = snapshot?.embeddingTargets.filter((target) => target.kind === 'chunk').length ?? snapshot?.chunks.length ?? 0;
            const entities = snapshot?.embeddingTargets.filter((target) => target.kind === 'entity').length ?? snapshot?.nodes.length ?? 0;
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
                        ? 'product_lorentz_hopf_v1'
                        : this.manifoldMode() === 'siegel'
                            ? 'siegel_finsler_v1'
                    : 'hybrid_semantic_v1'
        );
    }

    projectionSourceLabel(): string {
        const source = String(this.displayEmbeddingAtlas().manifold?.projectionSource || 'semantic_atlas_rows');
        return source.replace(/_/g, ' ');
    }

    onCanvasEntitySelected(node: GalaxyRenderableNode): void {
        this.selectedEntityId = this.selectedEntityId === node.id ? null : node.id;
    }

    runAtlasQuery(): void {
        this.atlasMode = 'embeddings';
        this.persistViewState();
        const trace = manifoldAdapter(this.manifoldMode()).trace(this.queryText(), this.displayEmbeddingAtlas());
        this.queryTrace.set(trace);
        this.selectedEntityId = trace?.queryNode.id ?? null;
    }

    clearAtlasQuery(): void {
        this.queryTrace.set(null);
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

    toggleParticles(): void {
        this.updateSettings({ particleFlow: !this.settings.particleFlow });
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

    toggleProductKlein(): void {
        this.updateSettings({ productKleinVisible: !this.settings.productKleinVisible });
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

    activeNodeCount(): number {
        return this.activeNodes().length;
    }

    activeEdgeCount(): number {
        return this.activeEdges().length;
    }

    primaryCountLabel(): string {
        if (this.atlasMode === 'entities') return 'registry entities';
        if (this.atlasMode === 'graph') return 'graph nodes';
        if (this.usesGraphRebuildEmbeddingAtlas()) return 'embedding targets';
        if (this.manifoldMode() === 'siegel') return 'finsler nodes';
        return this.manifoldMode() === 'lorentz' ? 'cap nodes' : 'semantic vectors';
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
        if (this.atlasMode === 'graph') return 'Graph Rebuild Snapshot';
        if (this.usesGraphRebuildEmbeddingAtlas()) return `Graph Rebuild Snapshot -> ${this.currentProjectionLabel()} Space`;
        if (this.manifoldMode() === 'lorentz') return 'Hierarchy Caps Sidecar';
        if (this.manifoldMode() === 'hopf') return 'Semantic Atlas -> Hopf Projection';
        if (this.manifoldMode() === 'product') return 'Semantic Atlas -> Product Space';
        if (this.manifoldMode() === 'siegel') return 'Semantic Atlas -> Siegel-Finsler Space';
        return 'Semantic Atlas -> Hybrid Space';
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
        return trace ? {
            queryNodeId: trace.queryNode.id,
            primaryNodeIds: trace.primaryIds,
            secondaryNodeIds: trace.secondaryIds,
            edgeIds: trace.edgeIds,
        } : null;
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

    private currentProjectionLabel(): string {
        return manifoldAdapter(this.manifoldMode()).label;
    }

    private displayEmbeddingAtlas(): EmbeddingAtlasData {
        return this.graphRebuildEmbeddingAtlas() ?? this.embeddingAtlas();
    }

    private usesGraphRebuildEmbeddingAtlas(): boolean {
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
        if (mode === 'product') return 'productManifold';
        if (mode === 'hopf') return 'hopfProjection';
        if (mode === 'lorentz') return 'lorentzTree';
        if (mode === 'siegel') return 'siegelFinsler';
        return 'hybridSpace';
    }

    private activeGraph(): ActiveAtlasGraph {
        const atlas = this.displayEmbeddingAtlas();
        const trace = this.queryTrace();
        const graphInventory = this.graphInventory();
        const graphKindFilter = this.graphKindFilter();
        const cached = this.activeGraphCache;
        if (
            cached &&
            cached.mode === this.atlasMode &&
            cached.entities === this.entities &&
            cached.edges === this.edges &&
            cached.atlas === atlas &&
            cached.trace === trace &&
            cached.graphInventory === graphInventory &&
            cached.graphKindFilter === graphKindFilter
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
                nodes,
                graphEdges: this.edges,
            };
            return this.activeGraphCache;
        }

        if (this.atlasMode === 'graph') {
            const allowed = graphKindFilter === 'all' ? null : new Set(
                graphInventory.nodes.filter((node) => normalizeGraphKind(node.kind) === graphKindFilter).map((node) => node.id),
            );
            const nodes = allowed ? graphInventory.nodes.filter((node) => allowed.has(node.id)) : graphInventory.nodes;
            const graphEdges = allowed
                ? graphInventory.edges.filter((edge) => allowed.has(edge.sourceId) && allowed.has(edge.targetId))
                : graphInventory.edges;
            this.activeGraphCache = {
                mode: this.atlasMode,
                entities: this.entities,
                edges: this.edges,
                atlas,
                trace,
                graphInventory,
                graphKindFilter,
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
            nodes: trace ? [trace.queryNode, ...embeddingNodes] : embeddingNodes,
            graphEdges: trace ? [...trace.edges, ...embeddingEdges] : embeddingEdges,
        };
        return this.activeGraphCache;
    }

    private embeddingNodesWithEntityAnchors(): GalaxyRenderableNode[] {
        const atlas = this.displayEmbeddingAtlas();
        if (this.usesGraphRebuildEmbeddingAtlas()) return atlas.nodes;
        if (!this.entities.length || !atlas.nodes.length) return atlas.nodes;
        const anchors = this.entities.slice(0, 80).map((entity, index) => {
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
        for (const entity of this.entities.slice(0, 80)) {
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

    private async refreshGraphInventory(context: GraphAtlasReadContext): Promise<void> {
        const token = ++this.graphLoadToken;
        try {
            const delta = await this.phoenixUiApi.knowledgeGraphDelta(context.searchScope);
            if (token === this.graphLoadToken) {
                this.graphInventory.set(filterGraphInventoryForNotes(
                    graphInventoryFromDelta(delta),
                    context.noteIds,
                ));
            }
        } catch (error) {
            console.warn('[GraphAtlasPreview] Failed to load graph inventory', error);
            if (token === this.graphLoadToken) this.graphInventory.set(EMPTY_GRAPH_INVENTORY);
        }
    }

    private async refreshEmbeddingAtlas(context: GraphAtlasReadContext, manifold: AtlasManifoldMode, force = false): Promise<void> {
        const requestKey = `${manifold}:${context.key}`;
        if (!force && this.atlasLoadingKeys.get(manifold) === requestKey) return;
        if (!force && this.atlasLoadedKeys.get(manifold) === requestKey && this.machine.manifoldStatuses()[manifold] === 'ready') return;

        this.atlasLoadingKeys.set(manifold, requestKey);
        const load = this.machine.beginManifoldLoad(manifold);
        try {
            const adapter = manifoldAdapter(manifold);
            const atlas = await adapter.load(this.phoenixUiApi, context.searchScope);
            if (this.machine.isCurrentManifoldLoad(load)) {
                this.setEmbeddingAtlasForMode(manifold, atlas);
                this.atlasLoadedKeys.set(manifold, requestKey);
                if (this.manifoldMode() === manifold) {
                    this.queryTrace.set(adapter.trace(this.queryText(), atlas));
                }
                this.machine.finishManifoldLoad(load, `${adapter.label} manifold ready`, {
                    owner: 'graph-atlas-preview',
                    nodes: atlas.nodes.length,
                    edges: atlas.edges.length,
                    sourceLabel: atlas.sourceLabel,
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

function emptyEmbeddingAtlas(sourceLabel: string): EmbeddingAtlasData {
    return { nodes: [], edges: [], sourceLabel, searchIndex: [] };
}

function graphLeavesFromAudit(audit: { nodeKinds: Array<{ key: string; count: number }> } | null): number | null {
    return audit?.nodeKinds.find((bucket) => ['leaf', 'chunk'].includes(bucket.key))?.count ?? null;
}

function graphInventoryFromDelta(delta: PhoenixGraphDeltaBinaryResult): GraphInventory {
    const nodes: GalaxyRenderableNode[] = [];
    const idSet = new Set<string>();

    for (const chunk of delta.chunks || []) {
        const id = chunk.vertexId || `leaf:${chunk.chunkId}`;
        if (!id || idSet.has(id)) continue;
        idSet.add(id);
        nodes.push({
            id,
            label: `Leaf ${chunk.chapterId}:${chunk.start}-${chunk.end}`,
            kind: 'leaf',
            totalMentions: 1,
            ...stableAtlasPoint(id, nodes.length),
            colorHsl: graphKindHsl('leaf'),
            metadata: {
                sourceType: 'graph',
                graphKind: 'leaf',
                graphColorKind: 'chunk',
                graphNodeId: id,
                chunkId: chunk.chunkId,
                documentId: chunk.documentId,
                noteId: chunk.noteId,
                graphSource: 'graph_delta',
            },
        });
    }

    for (const node of delta.nodes || []) {
        const id = node.nodeId;
        if (!id || idSet.has(id)) continue;
        idSet.add(id);
        const kind = normalizeGraphKind(node.kind || 'generic');
        nodes.push({
            id,
            label: node.label || id,
            kind,
            totalMentions: Math.max(1, Math.abs(Number(node.weight || 1))),
            ...stableAtlasPoint(id, nodes.length),
            colorHsl: graphKindHsl(kind),
            metadata: {
                sourceType: 'graph',
                graphKind: kind,
                graphColorKind: kind,
                graphNodeId: id,
                sourceEntityId: node.entityId,
                documentId: node.documentId,
                graphSource: 'graph_delta',
            },
        });
    }

    const edges: AtlasPreviewEdge[] = [];
    const edgeSeen = new Set<string>();
    for (const edge of delta.edges || []) {
        if (!idSet.has(edge.sourceId) || !idSet.has(edge.targetId)) continue;
        const id = `graph:${edge.sourceId}->${edge.targetId}:${edge.edgeType}`;
        if (edgeSeen.has(id)) continue;
        edgeSeen.add(id);
        edges.push({
            id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
            type: edge.edgeType || 'graph-edge',
            confidence: Math.max(0.25, Math.min(1.8, Math.abs(Number(edge.weight || 1)) / 8)),
        });
    }

    return {
        nodes,
        edges,
        kindCounts: graphKindCounts(nodes),
        sourceLabel: 'backend graph delta',
    };
}

function filterGraphInventoryForNotes(inventory: GraphInventory, noteIds: readonly string[]): GraphInventory {
    if (!noteIds.length) return inventory;
    const allowedNotes = new Set(noteIds);
    const nodes = inventory.nodes.filter((node) => {
        const metadata = node.metadata ?? {};
        const noteId = String(metadata['noteId'] || metadata['documentId'] || '');
        return allowedNotes.has(noteId);
    });
    const ids = new Set(nodes.map((node) => node.id));
    const edges = inventory.edges.filter((edge) => ids.has(edge.sourceId) && ids.has(edge.targetId));
    return {
        ...inventory,
        nodes,
        edges,
        kindCounts: graphKindCounts(nodes),
    };
}

function graphKindCounts(nodes: GalaxyRenderableNode[]): Array<{ kind: string; count: number }> {
    const counts = new Map<string, number>();
    for (const node of nodes) {
        const kind = normalizeGraphKind(node.kind);
        counts.set(kind, (counts.get(kind) || 0) + 1);
    }
    return [...counts.entries()]
        .map(([kind, count]) => ({ kind, count }))
        .sort((left, right) => right.count - left.count || left.kind.localeCompare(right.kind));
}

function normalizeGraphKind(kind: string): string {
    return String(kind || 'generic').trim().toLowerCase().replace(/[_\s]+/g, '-');
}

function graphKindHsl(kind: string): string {
    switch (normalizeGraphKind(kind)) {
        case 'document': return entityColorStore.getRawGraphNodeHsl('document');
        case 'chunk':
        case 'leaf': return entityColorStore.getRawGraphNodeHsl('chunk');
        case 'entity': return '280 70% 60%';
        case 'mention': return entityColorStore.getRawGraphNodeHsl('anchor');
        case 'alias': return '315 72% 58%';
        case 'event': return entityColorStore.getRawGraphNodeHsl('eventNode');
        case 'state': return entityColorStore.getRawGraphNodeHsl('memoryState');
        case 'memory': return entityColorStore.getRawGraphNodeHsl('memoryState');
        case 'timeanchor':
        case 'time-anchor': return entityColorStore.getRawGraphNodeHsl('temporal');
        case 'candidate': return '260 28% 58%';
        default: return '220 10% 54%';
    }
}

function stableAtlasPoint(id: string, index: number): { atlasX: number; atlasY: number; atlasZ: number } {
    const angle = index * 2.399963229728653 + hashUnit(id) * 0.72;
    const y = 1 - ((index % 97) / 96) * 2;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const radius = 0.88 + hashUnit(`${id}:radius`) * 0.16;
    return {
        atlasX: Math.cos(angle) * radial * radius,
        atlasY: y * 0.72,
        atlasZ: Math.sin(angle) * radial * radius,
    };
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
