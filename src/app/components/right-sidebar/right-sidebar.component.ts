import { Component, inject, signal, OnInit, OnDestroy, computed, effect, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule, Sparkles, BarChart3, ChevronDown, Bot, Clock, History } from 'lucide-angular';
import { RightSidebarService } from '../../lib/services/right-sidebar.service';
import { ScopeService } from '../../lib/services/scope.service';
import { EntitySelectionService } from '../../lib/services/entity-selection.service';
import { FactSheetContainerComponent, ParsedEntity } from '../fact-sheets/fact-sheet-container/fact-sheet-container.component';
import { AnalyticsPanelComponent } from '../analytics-panel';
import { TimelineViewComponent } from './timeline-view/timeline-view.component';
import { AiChatPanelComponent } from './ai-chat-panel/ai-chat-panel.component';
import { NoteHistoryPanelComponent } from './note-history-panel/note-history-panel.component';
import { getSetting, setSetting } from '../../lib/dexie/settings.service';

type SidebarView = 'entities' | 'analytics' | 'timeline' | 'ai' | 'history';

interface ViewOption {
    value: SidebarView;
    label: string;
    icon: any; // Lucide icon object
}

const VIEW_OPTIONS: ViewOption[] = [
    { value: 'entities', label: 'Entities', icon: Sparkles },
    { value: 'analytics', label: 'Analytics', icon: BarChart3 },
    { value: 'timeline', label: 'Timeline', icon: Clock },
    { value: 'history', label: 'History', icon: History },
    { value: 'ai', label: 'AI', icon: Bot },
];

const RIGHT_SIDEBAR_SNAP_MS = 150;
const RIGHT_SIDEBAR_CONTENT_READY_MS = 32;

@Component({
    selector: 'app-right-sidebar',
    standalone: true,
    imports: [CommonModule, FormsModule, LucideAngularModule, FactSheetContainerComponent, AnalyticsPanelComponent, TimelineViewComponent, AiChatPanelComponent, NoteHistoryPanelComponent],
    template: `
        <aside
            class="right-sidebar-panel h-full border-l border-sidebar-border bg-sidebar text-sidebar-foreground flex flex-col overflow-hidden relative"
            [class.right-sidebar-panel--open]="service.isOpen()"
            [class.right-sidebar-panel--resizing]="isResizing"
            [style.width.px]="rightPanelVisible() ? rightSidebarWidth : 0">

            @if (service.isOpen()) {
                <div class="absolute top-0 left-0 bottom-0 w-1.5 cursor-col-resize z-50 hover:bg-primary/50 transition-colors"
                (mousedown)="startResize($event)"></div>
            }
            
            @if (rightPanelVisible()) {
                <!-- View Selector Header -->
                <div class="shrink-0 h-10 border-b border-white/10 bg-gradient-to-b from-zinc-800 to-zinc-950 px-2 flex items-center shadow-sm text-white">
                    <div class="view-selector-wrapper h-8 relative">
                        <!-- Trigger Button -->
                        <div class="view-selector-display" (click)="toggleDropdown()">
                            <lucide-icon [img]="currentViewIcon()" class="h-4 w-4"></lucide-icon>
                            <span>{{ currentViewLabel() }}</span>
                            <lucide-icon name="chevron-down" class="h-4 w-4 ml-auto opacity-50 transition-transform duration-200"
                                [class.rotate-180]="isDropdownOpen()"></lucide-icon>
                        </div>

                        <!-- Dropdown Menu -->
                        @if (isDropdownOpen()) {
                            <!-- Backdrop -->
                            <div class="fixed inset-0 z-40" (click)="closeDropdown()"></div>
                            
                            <!-- Menu -->
                            <div class="absolute top-full left-0 right-0 mt-1 z-50 bg-[#18181b] border border-teal-900/50 rounded-md shadow-xl py-1 overflow-hidden animate-in fade-in slide-in-from-top-2 duration-150">
                                @for (opt of viewOptions; track opt.value) {
                                    <button
                                        class="w-full px-3 py-2 text-sm flex items-center gap-2 text-left hover:bg-teal-900/20 transition-colors"
                                        [class.text-teal-400]="activeView() === opt.value"
                                        [class.bg-teal-900-10]="activeView() === opt.value"
                                        (click)="onViewChange(opt.value)"
                                    >
                                        <lucide-icon [img]="opt.icon" class="h-4 w-4 opacity-70"></lucide-icon>
                                        {{ opt.label }}
                                    </button>
                                }
                            </div>
                        }
                    </div>
                </div>

                <!-- Content Area -->
                <div class="flex-1 min-h-0 overflow-hidden flex flex-col">
                    @if (rightPanelContentReady()) {
                    @switch (activeView()) {
                        @case ('entities') {
                            <!-- Entity Selector (only for entities view) -->
                            <div class="p-2 border-b border-border/50 shrink-0 space-y-2">
                                <!-- Scope Indicator (READ-ONLY, shows current entity scope) -->
                                <div class="flex items-center gap-2 px-1 py-1 text-xs text-muted-foreground bg-muted/30 rounded">
                                    <i class="pi text-[10px]" [ngClass]="scopeService.scopeIcon()"></i>
                                    <span class="truncate">{{ scopeService.scopeLabel() }}</span>
                                    <span class="text-[10px] opacity-60 ml-auto">scope</span>
                                </div>

                                <!-- Entity Selector -->
                                @if (entities().length > 0) {
                                    <select
                                        class="w-full px-2 py-1.5 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
                                        [ngModel]="selectedEntityId()"
                                        (ngModelChange)="onEntitySelect($event)"
                                    >
                                        @for (ent of entities(); track ent.id) {
                                            <option [value]="ent.id">{{ ent.kind }} | {{ ent.label }}</option>
                                        }
                                    </select>

                                }
                            </div>
                            
                            <!-- Fact Sheet -->
                            <div class="flex-1 overflow-hidden">
                                <app-fact-sheet-container 
                                    [entity]="selectedEntity()" 
                                    [contextId]="factSheetContextId()"
                                />
                            </div>

                            <!-- Empty state for entities -->
                            @if (entities().length === 0 && !loading()) {
                                <div class="flex-1 flex flex-col items-center justify-center p-6 text-center">
                                    <lucide-icon name="sparkles" class="h-12 w-12 text-muted-foreground/50 mb-4"></lucide-icon>
                                    <p class="text-sm text-muted-foreground">No entities registered</p>
                                    <p class="text-xs text-muted-foreground/70 mt-1">
                                        Create entities in your notes to see them here
                                    </p>
                                </div>
                            }
                        }

                        @case ('analytics') {
                            <!-- Analytics Panel -->
                            <div class="flex-1 overflow-auto custom-scrollbar p-3">
                                <app-analytics-panel />
                            </div>
                        }

                        @case ('timeline') {
                            <!-- Timeline View -->
                            <div class="flex-1 overflow-auto custom-scrollbar">
                                <app-timeline-view />
                            </div>
                        }

                        @case ('ai') {
                            <!-- AI Chat Panel -->
                            <div class="flex-1 overflow-hidden">
                                <app-ai-chat-panel />
                            </div>
                        }

                        @case ('history') {
                            <!-- Note History Panel -->
                            <div class="flex-1 overflow-hidden">
                                <app-note-history-panel />
                            </div>
                        }
                    }
                    }
                </div>

                <!-- Footer -->
                <div class="h-8 flex items-center px-3 border-t border-border shrink-0 text-xs font-medium tracking-wide bg-gradient-to-b from-white to-gray-50 dark:from-zinc-900 dark:to-zinc-950 text-slate-600 dark:text-slate-400 relative z-10 transition-colors duration-300">
                    @if (activeView() === 'entities') {
                        <span>{{ entities().length }} entities</span>
                    } @else if (activeView() === 'ai') {
                        <span>Kammi AI</span>
                    } @else if (activeView() === 'history') {
                        <span>Note history</span>
                    } @else {
                        <span>Real-time analysis</span>
                    }
                </div>
            }
        </aside>
    `,
    styles: [`
        .right-sidebar-panel {
            flex: 0 0 auto;
            transform: translateX(100%);
            transform-origin: right center;
            transition: transform 150ms cubic-bezier(0.22, 1, 0.36, 1);
            will-change: transform;
            contain: paint;
        }

        .right-sidebar-panel--open,
        .right-sidebar-panel--resizing {
            transform: translateX(0);
        }

        .right-sidebar-panel--resizing {
            transition: none;
        }

        .view-selector-wrapper {
            position: relative;
            width: 100%;
        }

        /* Replaced native select hack with real interaction */

        .view-selector-display {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            height: 100%; /* Fill wrapper height (h-8 = 32px) */
            padding: 0 0.75rem;
            background: rgba(255, 255, 255, 0.05); /* Transparent block */
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 0.375rem;
            font-size: 0.875rem;
            font-weight: 500;
            color: #f1f5f9; /* Slate-100/White */
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .view-selector-display:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: rgba(255, 255, 255, 0.2);
        }
        .custom-scrollbar {
            scrollbar-width: thin;
            scrollbar-color: rgba(255, 255, 255, 0.1) transparent;
        }

        .custom-scrollbar::-webkit-scrollbar {
            width: 6px;
        }

        .custom-scrollbar::-webkit-scrollbar-track {
            background: transparent;
        }

        .custom-scrollbar::-webkit-scrollbar-thumb {
            background-color: rgba(255, 255, 255, 0.1);
            border-radius: 3px;
        }

        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
            background-color: rgba(255, 255, 255, 0.2);
        }

        @media (prefers-reduced-motion: reduce) {
            .right-sidebar-panel {
                transition: none;
            }
        }
    `]
})
export class RightSidebarComponent implements OnInit, OnDestroy {
    service = inject(RightSidebarService);
    scopeService = inject(ScopeService);
    private entitySelection = inject(EntitySelectionService);

    readonly viewOptions = VIEW_OPTIONS;

    /** Active view (persisted in AppStateService) */
    activeView = this.service.activePanel;

    /** Dropdown state */
    isDropdownOpen = signal(false);

    /** Loading state */
    loading = signal(false);

    // Resize state for right sidebar
    rightSidebarWidth = getSetting<number>('kittclouds-right-sidebar-width', 320) || 320;
    isResizing = false;
    private startX = 0;
    private startWidth = 0;
    rightPanelVisible = signal(this.service.isOpen());
    rightPanelContentReady = signal(this.service.isOpen());
    private rightCloseTimer: ReturnType<typeof setTimeout> | null = null;
    private rightContentTimer: ReturnType<typeof setTimeout> | null = null;

    /**
     * Entities derived from ScopeService's reactive signal.
     * Maps RegisteredEntity → ParsedEntity for the template.
     */
    entities = computed<ParsedEntity[]>(() => {
        const scoped = this.scopeService.scopedEntities();
        return scoped.map(e => ({
            id: e.id,
            kind: e.kind,
            label: e.label,
            subtype: e.subtype,
            noteId: e.firstNote,
        }));
    });

    /** Currently selected entity ID */
    selectedEntityId = this.entitySelection.selectedEntityId;

    /** Computed selected entity */
    selectedEntity = computed(() => {
        const id = this.selectedEntityId();
        return this.entities().find(e => e.id === id) || null;
    });

    factSheetContextId = computed(() => this.scopeService.resolvedScope().scopeFolderId || 'vault:global');

    /** Current view display helpers */
    currentViewLabel = computed(() => {
        const opt = VIEW_OPTIONS.find(o => o.value === this.activeView());
        return opt?.label || 'Entities';
    });

    currentViewIcon = computed(() => {
        const opt = VIEW_OPTIONS.find(o => o.value === this.activeView());
        return opt?.icon || Sparkles;
    });

    constructor() {
        // Auto-select first entity when scope changes and current selection is no longer in scope
        effect(() => {
            const ents = this.entities();
            this.entitySelection.ensureValid(ents.map((entity) => entity.id));
        });
        effect(() => {
            this.syncRightSidebarMotion(this.service.isOpen());
        });
    }

    ngOnInit() {
        // No manual loading needed — entities are computed from scope signal
    }

    ngOnDestroy() {
        this.clearRightSidebarMotionTimers();
    }

    private syncRightSidebarMotion(open: boolean): void {
        this.clearRightSidebarMotionTimers();
        if (open) {
            this.rightPanelVisible.set(true);
            this.rightContentTimer = setTimeout(() => {
                this.rightPanelContentReady.set(true);
                this.rightContentTimer = null;
            }, RIGHT_SIDEBAR_CONTENT_READY_MS);
            return;
        }
        this.isDropdownOpen.set(false);
        this.rightPanelContentReady.set(false);
        this.rightCloseTimer = setTimeout(() => {
            this.rightPanelVisible.set(false);
            this.rightCloseTimer = null;
        }, RIGHT_SIDEBAR_SNAP_MS);
    }

    private clearRightSidebarMotionTimers(): void {
        if (this.rightCloseTimer) {
            clearTimeout(this.rightCloseTimer);
            this.rightCloseTimer = null;
        }
        if (this.rightContentTimer) {
            clearTimeout(this.rightContentTimer);
            this.rightContentTimer = null;
        }
    }

    onViewChange(view: SidebarView) {
        this.service.setActivePanel(view);
        this.closeDropdown();
    }

    toggleDropdown() {
        this.isDropdownOpen.update(v => !v);
    }

    closeDropdown() {
        this.isDropdownOpen.set(false);
    }

    onEntitySelect(entityId: string) {
        this.entitySelection.select(entityId);
    }

    startResize(event: MouseEvent): void {
        event.preventDefault();
        this.isResizing = true;
        this.startX = event.clientX;
        this.startWidth = this.rightSidebarWidth;
        
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        
        if (this.service.isClosed()) {
            this.service.open();
        }
    }

    @HostListener('window:mousemove', ['$event'])
    onMouseMove(event: MouseEvent): void {
        if (!this.isResizing) return;

        // Pulling cursor LEFT (smaller clientX) makes sidebar WIDER
        const delta = this.startX - event.clientX;
        const newWidth = this.startWidth + delta;

        // Constraints
        const minWidth = 200;
        const maxWidth = 800;

        this.rightSidebarWidth = Math.min(Math.max(newWidth, minWidth), maxWidth);
    }

    @HostListener('window:mouseup')
    onMouseUp(): void {
        if (this.isResizing) {
            this.isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            setSetting('kittclouds-right-sidebar-width', this.rightSidebarWidth);
        }
    }
}
