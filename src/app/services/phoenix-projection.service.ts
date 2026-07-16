import { Injectable, computed, inject, signal } from '@angular/core';

import type { EntityKind } from '../lib/Scanner/types';
import type { CentralRegistrySnapshot, Edge, RegisteredEntity } from '../lib/registry';
import { PhoenixStoreService, type StoreEdge, type StoreEntity } from './phoenix-store.service';

export interface PhoenixProjectionEdge {
    id: string;
    sourceId: string;
    targetId: string;
    type: string;
    confidence: number;
    sourceNote?: string;
}

export interface PhoenixProjectionSnapshot {
    generation: number;
    entities: RegisteredEntity[];
    edges: PhoenixProjectionEdge[];
}

@Injectable({ providedIn: 'root' })
export class PhoenixProjectionService {
    private readonly store = inject(PhoenixStoreService);
    private readonly _generation = signal(0);
    private readonly _entities = signal<RegisteredEntity[]>([]);
    private readonly _edges = signal<PhoenixProjectionEdge[]>([]);
    private refreshPromise: Promise<void> | null = null;
    private liveEpoch = 0;

    readonly generation = computed(() => this._generation());
    readonly entities = computed(() => this._entities());
    readonly edges = computed(() => this._edges());
    readonly entityCount = computed(() => this._entities().length);
    readonly snapshot = computed<PhoenixProjectionSnapshot>(() => ({
        generation: this._generation(),
        entities: this._entities(),
        edges: this._edges(),
    }));

    constructor() {
        this.bindBrowserEvents();
    }

    async refresh(_reason = 'manual'): Promise<void> {
        if (this.refreshPromise) {
            return this.refreshPromise;
        }

        const epoch = this.liveEpoch;
        this.refreshPromise = this.loadNativeSnapshot(epoch)
            .finally(() => {
                this.refreshPromise = null;
            });
        return this.refreshPromise;
    }

    getEntityById(id: string): RegisteredEntity | null {
        return this._entities().find((entity) => entity.id === id) ?? null;
    }

    findEntityByLabel(label: string): RegisteredEntity | null {
        const normalized = label.trim().toLocaleLowerCase();
        return this._entities().find((entity) => entity.label.trim().toLocaleLowerCase() === normalized) ?? null;
    }

    getEdgesForEntity(entityId: string): PhoenixProjectionEdge[] {
        return this._edges().filter((edge) => edge.sourceId === entityId || edge.targetId === entityId);
    }

    private async loadNativeSnapshot(epoch: number): Promise<void> {
        const [entities, edges] = await Promise.all([
            this.store.listEntities(),
            this.store.listAllEdges().catch(() => []),
        ]);
        if (epoch !== this.liveEpoch) {
            return;
        }
        this._entities.set(entities.map(storeEntityToRegistered));
        this._edges.set(edges.map(storeEdgeToProjection));
        this._generation.update((generation) => generation + 1);
    }

    private bindBrowserEvents(): void {
        if (typeof window === 'undefined') {
            return;
        }
        const refresh = (event: Event) => {
            void this.refresh(event.type);
        };
        const liveRegistryRefresh = (event: Event) => {
            const detail = (event as CustomEvent<CentralRegistrySnapshot>).detail;
            if (this.applyLiveRegistrySnapshot(detail)) {
                return;
            }
            void this.refresh(event.type);
        };
        window.addEventListener('entities-changed', liveRegistryRefresh);
        window.addEventListener('phoenix-projection-invalidated', refresh);
    }

    private applyLiveRegistrySnapshot(detail: CentralRegistrySnapshot | undefined): boolean {
        if (!detail || !Array.isArray(detail.entities) || !Array.isArray(detail.edges)) {
            return false;
        }
        this.liveEpoch += 1;
        this._entities.set(detail.entities.map(cloneRegisteredEntity));
        this._edges.set(detail.edges.map(registryEdgeToProjection));
        this._generation.update((generation) => generation + 1);
        return true;
    }
}

export function storeEntityToRegistered(entity: StoreEntity): RegisteredEntity {
    return {
        id: entity.id,
        label: entity.label,
        kind: entity.kind as EntityKind,
        aliases: entity.aliases || [],
        subtype: entity.subtype,
        firstNote: entity.firstNote,
        noteId: entity.firstNote,
        mentionsByNote: new Map(entity.firstNote ? [[entity.firstNote, entity.totalMentions || 1]] : []),
        totalMentions: entity.totalMentions || 0,
        lastSeenDate: new Date(entity.updatedAt || entity.createdAt || Date.now()),
        createdAt: new Date(entity.createdAt || Date.now()),
        createdBy: entity.createdBy || 'user',
        attributes: entity.narrativeId ? { narrativeId: entity.narrativeId } : {},
        registeredAt: entity.createdAt || Date.now(),
    };
}

function storeEdgeToProjection(edge: StoreEdge): PhoenixProjectionEdge {
    return {
        id: edge.id,
        sourceId: edge.sourceId,
        targetId: edge.targetId,
        type: edge.relType,
        confidence: edge.confidence,
        sourceNote: edge.sourceNote,
    };
}

export function registryEdgeToProjection(edge: Edge): PhoenixProjectionEdge {
    return {
        id: edge.id,
        sourceId: edge.sourceId,
        targetId: edge.targetId,
        type: edge.type,
        confidence: edge.confidence,
        sourceNote: edge.sourceNote,
    };
}

function cloneRegisteredEntity(entity: RegisteredEntity): RegisteredEntity {
    return {
        ...entity,
        aliases: [...(entity.aliases || [])],
        mentionsByNote: new Map(entity.mentionsByNote ?? []),
        attributes: { ...(entity.attributes || {}) },
    };
}
