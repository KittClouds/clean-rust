import { CommonModule } from '@angular/common';
import { ScrollingModule } from '@angular/cdk/scrolling';
import { Component, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, computed, signal } from '@angular/core';
import {
    Calendar,
    ChevronDown,
    ChevronRight,
    Lightbulb,
    MapPin,
    Network,
    Package,
    PanelLeft,
    PanelLeftClose,
    Pencil,
    Plus,
    Search,
    Sparkles,
    Trash2,
    User,
    Users,
    X,
} from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import { entitySourceLabel, type RegisteredEntity } from '../../../../lib/registry';
import {
    entityColorStore,
    hexColorToHsl,
    hslColorToHex,
    normalizeEntityKind,
} from '../../../../lib/store/entityColorStore';

interface EntityGroup {
    kind: string;
    entities: RegisteredEntity[];
    expanded: boolean;
}

type EntitySidebarRow =
    | { type: 'group'; kind: string; count: number; expanded: boolean }
    | { type: 'entity'; entity: RegisteredEntity };

const ENTITY_ICONS: Record<string, any> = {
    CHARACTER: User,
    LOCATION: MapPin,
    NPC: Users,
    ITEM: Package,
    FACTION: Network,
    NETWORK: Network,
    EVENT: Calendar,
    CONCEPT: Lightbulb,
};

@Component({
    selector: 'app-graph-entity-sidebar',
    standalone: true,
    imports: [CommonModule, ScrollingModule, LucideAngularModule],
    templateUrl: './graph-entity-sidebar.component.html',
    styleUrl: './graph-entity-sidebar.component.css',
})
export class GraphEntitySidebarComponent implements OnChanges, OnDestroy {
    @Input() entities: RegisteredEntity[] = [];
    @Input() selectedEntity: RegisteredEntity | null = null;
    @Input() searchText = '';

    @Output() entitySelected = new EventEmitter<RegisteredEntity>();
    @Output() editEntityRequested = new EventEmitter<RegisteredEntity>();
    @Output() deleteEntityRequested = new EventEmitter<RegisteredEntity>();
    @Output() addEntityRequested = new EventEmitter<void>();
    @Output() styleRequested = new EventEmitter<void>();
    @Output() searchTextChange = new EventEmitter<string>();

    readonly isOpen = signal(true);
    readonly entitySearch = signal('');
    readonly expandedKinds = signal<Set<string>>(new Set());
    private readonly dataRevision = signal(0);
    private readonly unsubscribeColors = entityColorStore.subscribe(() => {
        this.dataRevision.update((revision) => revision + 1);
    });

    readonly rows = computed<EntitySidebarRow[]>(() => {
        this.dataRevision();
        return this.flattenRows(this.groupedEntities());
    });
    readonly visibleEntityCount = computed(() => this.rows()
        .filter((row) => row.type === 'entity').length);

    readonly ChevronDownIcon = ChevronDown;
    readonly ChevronRightIcon = ChevronRight;
    readonly PanelLeftIcon = PanelLeft;
    readonly PanelLeftCloseIcon = PanelLeftClose;
    readonly PencilIcon = Pencil;
    readonly PlusIcon = Plus;
    readonly SearchIcon = Search;
    readonly SparklesIcon = Sparkles;
    readonly TrashIcon = Trash2;
    readonly XIcon = X;

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['entities']) {
            const nextKinds = new Set(this.entities.map((entity) => this.canonicalKind(entity.kind)));
            this.expandedKinds.update((current) => new Set([...current, ...nextKinds]));
            this.dataRevision.update((revision) => revision + 1);
        }
        if (changes['searchText'] && this.searchText !== this.entitySearch()) {
            this.entitySearch.set(this.searchText || '');
            this.dataRevision.update((revision) => revision + 1);
        }
    }

    ngOnDestroy(): void {
        this.unsubscribeColors();
    }

    updateEntitySearch(value: string): void {
        this.entitySearch.set(value);
        this.searchTextChange.emit(value);
        this.dataRevision.update((revision) => revision + 1);
    }

    clearSearch(): void {
        this.updateEntitySearch('');
    }

    toggleOpen(): void {
        this.isOpen.update((open) => !open);
    }

    toggleKind(kind: string): void {
        this.expandedKinds.update((current) => {
            const next = new Set(current);
            next.has(kind) ? next.delete(kind) : next.add(kind);
            return next;
        });
    }

    getIcon(kind: string): any {
        return ENTITY_ICONS[this.canonicalKind(kind)] || Sparkles;
    }

    getColor(kind: string): string {
        return entityColorStore.getEntityColor(this.canonicalKind(kind));
    }

    getHexColor(kind: string): string {
        this.dataRevision();
        return hslColorToHex(entityColorStore.getRawHsl(this.canonicalKind(kind)));
    }

    updateKindColor(kind: string, hexColor: string, event: Event): void {
        event.stopPropagation();
        entityColorStore.setColor(this.canonicalKind(kind), hexColorToHsl(hexColor));
    }

    getEntityBadgeColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityColor(this.canonicalKind(entity.kind));
    }

    getEntityBadgeBgColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityBgColor(this.canonicalKind(entity.kind), 0.13);
    }

    getEntityBadgeBorderColor(entity: RegisteredEntity): string {
        return entityColorStore.getEntityBgColor(this.canonicalKind(entity.kind), 0.34);
    }

    displayKind(kind: string): string {
        return this.canonicalKind(kind);
    }

    getEntitySourceLabel(entity: RegisteredEntity): string {
        return entitySourceLabel(entity);
    }

    aliasLabel(entity: RegisteredEntity): string {
        const count = entity.aliases?.length ?? 0;
        return `${count} ${count === 1 ? 'alias' : 'aliases'}`;
    }

    isSelected(entity: RegisteredEntity): boolean {
        return this.selectedEntity?.id === entity.id;
    }

    trackRow(_index: number, row: EntitySidebarRow): string {
        return row.type === 'group' ? `group:${row.kind}` : `entity:${row.entity.id}`;
    }

    editClicked(entity: RegisteredEntity, event: Event): void {
        event.stopPropagation();
        this.editEntityRequested.emit(entity);
    }

    deleteClicked(entity: RegisteredEntity, event: Event): void {
        event.stopPropagation();
        this.deleteEntityRequested.emit(entity);
    }

    private groupedEntities(): EntityGroup[] {
        const query = this.entitySearch().trim().toLowerCase();
        const groups = new Map<string, RegisteredEntity[]>();
        for (const entity of this.entities) {
            if (query && !this.matchesQuery(entity, query)) continue;
            const kind = this.canonicalKind(entity.kind);
            const list = groups.get(kind) ?? [];
            list.push(entity);
            groups.set(kind, list);
        }
        const expanded = this.expandedKinds();
        return [...groups.entries()]
            .sort(([left], [right]) => left.localeCompare(right))
            .map(([kind, entities]) => ({
                kind,
                entities: entities.sort((left, right) => left.label.localeCompare(right.label)),
                expanded: expanded.has(kind),
            }));
    }

    private flattenRows(groups: EntityGroup[]): EntitySidebarRow[] {
        const rows: EntitySidebarRow[] = [];
        for (const group of groups) {
            rows.push({ type: 'group', kind: group.kind, count: group.entities.length, expanded: group.expanded });
            if (group.expanded) rows.push(...group.entities.map((entity) => ({ type: 'entity' as const, entity })));
        }
        return rows;
    }

    private matchesQuery(entity: RegisteredEntity, query: string): boolean {
        const kind = this.canonicalKind(entity.kind);
        return entity.label.toLowerCase().includes(query)
            || kind.toLowerCase().includes(query)
            || (entity.aliases ?? []).some((alias) => alias.toLowerCase().includes(query));
    }

    private canonicalKind(kind: string): string {
        return normalizeEntityKind(kind) || kind;
    }
}
