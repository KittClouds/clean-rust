import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnDestroy, Output, signal } from '@angular/core';
import type { EntityKind } from '../../../../../lib/Scanner/types';
import {
    DEFAULT_ENTITY_COLORS,
    DEFAULT_ENTITY_TEXT_COLORS,
    DEFAULT_GRAPH_NODE_COLORS,
    entityColorStore,
    hexColorToHsl,
    hslColorToHex,
    normalizeGraphNodeColorKind,
    type GraphNodeColorKind,
} from '../../../../../lib/store/entityColorStore';
import {
    DEFAULT_HIGHLIGHT_SETTINGS,
    HIGHLIGHT_MODE_DESCRIPTIONS,
    HIGHLIGHT_MODE_LABELS,
    highlightingStore,
    type HighlightMode,
} from '../../../../../lib/store/highlightingStore';

interface EntityCategory {
    name: string;
    kinds: EntityKind[];
}

interface GraphNodeColorCategory {
    name: string;
    kinds: GraphNodeColorKind[];
}

const ENTITY_CATEGORIES: EntityCategory[] = [
    { name: 'Characters', kinds: ['CHARACTER', 'NPC', 'CREATURE'] },
    { name: 'Locations', kinds: ['LOCATION'] },
    { name: 'Groups', kinds: ['NETWORK'] },
    { name: 'Narrative', kinds: ['NARRATIVE', 'ARC', 'ACT', 'CHAPTER', 'SCENE', 'BEAT'] },
    { name: 'Events', kinds: ['EVENT', 'TIMELINE'] },
    { name: 'Objects', kinds: ['ITEM', 'CONCEPT'] },
];

const GRAPH_NODE_COLOR_CATEGORIES: GraphNodeColorCategory[] = [
    { name: 'Relationship colors', kinds: ['cooccurrence', 'observation', 'communication', 'authority', 'approval', 'relationship'] },
    { name: 'Story relationships', kinds: ['family', 'intimacy', 'transfer', 'causal', 'temporal', 'scenePresence'] },
    { name: 'Story structure', kinds: ['document', 'episode', 'chunk', 'anchor', 'graphFact', 'eventNode', 'temporalFact', 'causalFact'] },
    { name: 'State and context', kinds: ['memoryState', 'decisionState', 'rankStatus', 'serviceContext', 'affiliationContext', 'familyContext'] },
];

const GRAPH_NODE_COLOR_LABELS: Record<GraphNodeColorKind, string> = {
    cooccurrence: 'Weak co-occurrence',
    observation: 'Observation',
    communication: 'Communication',
    authority: 'Authority',
    approval: 'Approval',
    family: 'Family',
    intimacy: 'Intimacy',
    transfer: 'Transfer',
    scenePresence: 'Scene presence',
    causal: 'Causal',
    temporal: 'Temporal',
    relationship: 'Relationship',
    document: 'Document',
    episode: 'Episode',
    chunk: 'Chunk',
    anchor: 'Evidence',
    graphFact: 'Relationship midpoint',
    eventNode: 'Event',
    temporalFact: 'Timeline midpoint',
    causalFact: 'Cause midpoint',
    memoryState: 'Memory state',
    decisionState: 'Decision state',
    rankStatus: 'Rank/status',
    serviceContext: 'Service context',
    affiliationContext: 'Affiliation context',
    familyContext: 'Family context',
};

const MODE_ORDER: HighlightMode[] = ['vivid', 'gradient', 'subtle', 'clean', 'off'];

function mixHex(hexA: string, hexB: string, ratio: number): string {
    const parse = (hex: string) => {
        const clean = hex.replace('#', '');
        return {
            r: parseInt(clean.slice(0, 2), 16),
            g: parseInt(clean.slice(2, 4), 16),
            b: parseInt(clean.slice(4, 6), 16),
        };
    };
    const blend = (left: number, right: number) => Math.round(left * (1 - ratio) + right * ratio).toString(16).padStart(2, '0');
    const left = parse(hexA);
    const right = parse(hexB);
    return `#${blend(left.r, right.r)}${blend(left.g, right.g)}${blend(left.b, right.b)}`;
}

@Component({
    selector: 'app-graph-style-drawer',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './graph-style-drawer.component.html',
})
export class GraphStyleDrawerComponent implements OnDestroy {
    @Output() close = new EventEmitter<void>();

    private readonly colorRevision = signal(0);
    private readonly unsubscribeHighlighting = highlightingStore.subscribe(() => {
        const settings = highlightingStore.getSnapshot();
        this.mode.set(settings.mode);
    });
    private readonly unsubscribeColors = entityColorStore.subscribe(() => {
        this.colorRevision.update((revision) => revision + 1);
    });

    readonly categories = ENTITY_CATEGORIES;
    readonly graphNodeColorCategories = GRAPH_NODE_COLOR_CATEGORIES;
    readonly entityColorStore = entityColorStore;
    readonly modeLabels = HIGHLIGHT_MODE_LABELS;
    readonly modeDescriptions = HIGHLIGHT_MODE_DESCRIPTIONS;
    readonly modeOrder = MODE_ORDER;

    readonly selectedKind = signal<EntityKind>('CHARACTER');
    readonly selectedGraphNodeKind = signal<GraphNodeColorKind>('cooccurrence');
    readonly mode = signal<HighlightMode>(highlightingStore.getSnapshot().mode);

    @Input() set initialKind(value: EntityKind | string | null | undefined) {
        if (!value) return;
        const normalized = value.toUpperCase() as EntityKind;
        if (Object.prototype.hasOwnProperty.call(DEFAULT_ENTITY_COLORS, normalized)) {
            this.selectedKind.set(normalized);
        }
    }

    @Input() set initialGraphNodeKind(value: GraphNodeColorKind | string | null | undefined) {
        const normalized = normalizeGraphNodeColorKind(value);
        if (normalized) this.selectedGraphNodeKind.set(normalized);
    }

    ngOnDestroy(): void {
        this.unsubscribeHighlighting();
        this.unsubscribeColors();
    }

    selectKind(kind: EntityKind): void {
        this.selectedKind.set(kind);
    }

    selectGraphNodeKind(kind: GraphNodeColorKind): void {
        this.selectedGraphNodeKind.set(kind);
    }

    selectMode(mode: HighlightMode): void {
        highlightingStore.setMode(mode);
    }

    getHexColor(kind: EntityKind): string {
        this.colorRevision();
        return hslColorToHex(entityColorStore.getRawHsl(kind) || DEFAULT_ENTITY_COLORS[kind]);
    }

    getHexTextColor(kind: EntityKind): string {
        this.colorRevision();
        return hslColorToHex(entityColorStore.getRawTextHsl(kind) || DEFAULT_ENTITY_TEXT_COLORS[kind]);
    }

    getHexGraphNodeColor(kind: GraphNodeColorKind): string {
        this.colorRevision();
        return hslColorToHex(entityColorStore.getRawGraphNodeHsl(kind) || DEFAULT_GRAPH_NODE_COLORS[kind]);
    }

    updateColor(kind: EntityKind, hexColor: string): void {
        entityColorStore.setColor(kind, hexColorToHsl(hexColor));
    }

    updateTextColor(kind: EntityKind, hexColor: string): void {
        entityColorStore.setTextColor(kind, hexColorToHsl(hexColor));
    }

    updateGraphNodeColor(kind: GraphNodeColorKind, hexColor: string): void {
        entityColorStore.setGraphNodeColor(kind, hexColorToHsl(hexColor));
    }

    resetSelected(): void {
        const kind = this.selectedKind();
        entityColorStore.setColor(kind, DEFAULT_ENTITY_COLORS[kind]);
        entityColorStore.setTextColor(kind, DEFAULT_ENTITY_TEXT_COLORS[kind]);
    }

    resetSelectedGraphNode(): void {
        const kind = this.selectedGraphNodeKind();
        entityColorStore.setGraphNodeColor(kind, DEFAULT_GRAPH_NODE_COLORS[kind]);
    }

    resetAll(): void {
        entityColorStore.reset();
        highlightingStore.reset();
        this.mode.set(DEFAULT_HIGHLIGHT_SETTINGS.mode);
    }

    applyToCategory(): void {
        const selectedKind = this.selectedKind();
        const category = this.categories.find((entry) => entry.kinds.includes(selectedKind));
        if (!category) return;
        const color = entityColorStore.getRawHsl(selectedKind);
        const textColor = entityColorStore.getRawTextHsl(selectedKind);
        for (const kind of category.kinds) {
            entityColorStore.setColor(kind, color);
            entityColorStore.setTextColor(kind, textColor);
        }
    }

    formatKindName(kind: EntityKind): string {
        return kind.charAt(0) + kind.slice(1).toLowerCase().replace(/_/g, ' ');
    }

    formatGraphNodeKind(kind: GraphNodeColorKind): string {
        return GRAPH_NODE_COLOR_LABELS[kind];
    }

    currentCategoryName(): string {
        return this.categories.find((entry) => entry.kinds.includes(this.selectedKind()))?.name ?? 'Family';
    }

    modeTone(mode: HighlightMode): string {
        switch (mode) {
            case 'vivid': return 'border-violet-400/40 bg-violet-500/10 text-violet-200';
            case 'gradient': return 'border-cyan-400/40 bg-cyan-500/10 text-cyan-100';
            case 'subtle': return 'border-sky-400/40 bg-sky-500/10 text-sky-100';
            case 'clean': return 'border-teal-400/40 bg-teal-500/10 text-teal-100';
            default: return 'border-zinc-700 bg-zinc-900 text-zinc-300';
        }
    }

    gradientPreview(kind: EntityKind): string {
        const start = this.getHexColor(kind);
        const text = this.getHexTextColor(kind);
        const end = start.toLowerCase() === text.toLowerCase() ? mixHex(text, '#ffffff', 0.3) : text;
        return `linear-gradient(90deg, ${start}, ${end})`;
    }
}
