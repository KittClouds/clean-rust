import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule, Pencil, User, Users, MapPin, Calendar, Hash, FileText, Zap, Tag, Shield, Package, Lightbulb, Globe, GitBranch, Clock3, BadgeCheck, Fingerprint, Search, Plus, Merge, Pin, ExternalLink, Copy, Layers3, Target } from 'lucide-angular';
import { entitySourceLabel, entitySourceSystem, smartGraphRegistry } from '../../../../../lib/registry';
import type { Edge, RegisteredEntity } from '../../../../../lib/registry';
import { ConnectionGroup, ConnectionGroupComponent } from './connection-group/connection-group.component';
import { EntityKind } from '../../../../../lib/Scanner/types';
import { entityColorStore, normalizeEntityKind } from '../../../../../lib/store/entityColorStore';

const ENTITY_ICONS: Record<string, any> = {
    CHARACTER: User,
    NPC: Users,
    CREATURE: Users,
    FACTION: Globe,
    ORGANIZATION: Shield,
    NETWORK: Globe,
    LOCATION: MapPin,
    EVENT: Calendar,
    TIMELINE: Calendar,
    ITEM: Package,
    OBJECT: Hash,
    CONCEPT: Lightbulb,
    NARRATIVE: FileText,
    ARC: FileText,
    ACT: FileText,
    CHAPTER: FileText,
    SCENE: FileText,
    BEAT: Zap,
    LORE: FileText,
    UNKNOWN: Tag,
};

@Component({
    selector: 'app-graph-detail',
    standalone: true,
    imports: [CommonModule, FormsModule, LucideAngularModule, ConnectionGroupComponent],
    template: `
        <div class="animate-in fade-in duration-300 space-y-5">
            <section class="relative overflow-hidden border-b border-white/5 bg-[#07090f]">
                <div class="pointer-events-none absolute inset-0 opacity-90" [style.background]="heroGlow(entity.kind)"></div>
                <div class="relative grid gap-5 px-6 py-5 xl:grid-cols-[minmax(0,1fr)_320px]">
                    <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                            <span
                                class="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]"
                                [style.borderColor]="getBorderColor(entity.kind)"
                                [style.backgroundColor]="getBgColor(entity.kind)"
                                [style.color]="getColor(entity.kind)"
                            >
                                <lucide-icon [img]="getIcon(entity.kind)" class="h-3.5 w-3.5"></lucide-icon>
                                {{ displayKind(entity.kind) }}
                            </span>
                            <span class="rounded-full border border-cyan-300/15 bg-cyan-300/5 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-cyan-100/80">
                                {{ sourceLabel() }}
                            </span>
                            <span class="rounded-full border border-white/10 bg-black/30 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-zinc-400">
                                {{ totalConnections }} links
                            </span>
                            <span class="rounded-full border border-white/10 bg-black/30 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-zinc-400">
                                {{ entity.totalMentions || 0 }} mentions
                            </span>
                        </div>

                        <div class="mt-4 flex min-w-0 items-start gap-4">
                            <div
                                class="flex h-16 w-16 shrink-0 items-center justify-center rounded-[22px] border shadow-[0_18px_48px_rgba(0,0,0,0.32)]"
                                [style.backgroundColor]="getBgColor(entity.kind)"
                                [style.borderColor]="getBorderColor(entity.kind)"
                            >
                                <lucide-icon [img]="getIcon(entity.kind)" class="h-7 w-7" [style.color]="getColor(entity.kind)"></lucide-icon>
                            </div>
                            <div class="min-w-0">
                                <h2 class="truncate text-4xl font-semibold tracking-tight text-white">{{ entity.label }}</h2>
                                <p class="mt-2 max-w-4xl text-sm leading-7 text-zinc-300">{{ dossierSummary() }}</p>
                            </div>
                        </div>

                        <div *ngIf="entity.aliases.length > 0" class="mt-4 flex flex-wrap gap-2">
                            <span
                                *ngFor="let alias of entity.aliases"
                                class="rounded-full border border-white/10 bg-black/35 px-3 py-1.5 text-xs text-zinc-300"
                            >
                                {{ alias }}
                            </span>
                        </div>
                    </div>

                    <aside class="rounded-[24px] border border-white/10 bg-black/30 p-4 backdrop-blur-sm">
                        <div class="flex items-center justify-between gap-3">
                            <div>
                                <p class="text-[10px] font-semibold uppercase tracking-[0.22em] text-zinc-500">Dossier Control</p>
                                <p class="mt-1 text-xs text-zinc-400">{{ actionHint() }}</p>
                            </div>
                            <button
                                type="button"
                                class="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-zinc-300 transition hover:bg-white/[0.06]"
                                title="Copy entity id"
                                (click)="copyEntityId()"
                            >
                                <lucide-icon [img]="CopyIcon" class="h-4 w-4"></lucide-icon>
                            </button>
                        </div>
                        <p *ngIf="copiedEntityId" class="mt-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-emerald-300">Copied id</p>

                        <div class="mt-4 grid grid-cols-2 gap-2">
                            <button
                                type="button"
                                class="inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition hover:bg-white/[0.05]"
                                [style.borderColor]="getBorderColor(entity.kind)"
                                [style.color]="getColor(entity.kind)"
                                (click)="editRequested.emit(entity)"
                            >
                                <lucide-icon [img]="PencilIcon" class="h-4 w-4"></lucide-icon>
                                Edit
                            </button>
                            <button
                                type="button"
                                class="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.06]"
                                (click)="navigateRequested.emit(entity)"
                            >
                                <lucide-icon [img]="TargetIcon" class="h-4 w-4"></lucide-icon>
                                Focus
                            </button>
                        </div>

                        <div class="mt-4 grid grid-cols-3 gap-2">
                            <div class="rounded-2xl border border-white/5 bg-white/[0.03] p-3">
                                <p class="text-[9px] uppercase tracking-[0.18em] text-zinc-500">Groups</p>
                                <p class="mt-1 text-xl font-semibold text-white">{{ groupedRelationships.length }}</p>
                            </div>
                            <div class="rounded-2xl border border-white/5 bg-white/[0.03] p-3">
                                <p class="text-[9px] uppercase tracking-[0.18em] text-zinc-500">Notes</p>
                                <p class="mt-1 text-xl font-semibold text-white">{{ noteCount() }}</p>
                            </div>
                            <div class="rounded-2xl border border-white/5 bg-white/[0.03] p-3">
                                <p class="text-[9px] uppercase tracking-[0.18em] text-zinc-500">Aliases</p>
                                <p class="mt-1 text-xl font-semibold text-white">{{ entity.aliases.length }}</p>
                            </div>
                        </div>
                    </aside>
                </div>
            </section>

            <section class="grid gap-4 px-6 xl:grid-cols-[minmax(0,1fr)_340px]">
                <div class="space-y-4">
                    <section class="rounded-[24px] border border-white/5 bg-white/[0.025] p-4">
                        <div class="mb-4 flex items-center justify-between gap-3">
                            <div class="flex items-center gap-2">
                                <lucide-icon [img]="BadgeIcon" class="h-4 w-4 text-cyan-200"></lucide-icon>
                                <h3 class="text-sm font-semibold text-white">Canonical Facts</h3>
                            </div>
                            <span class="text-[10px] uppercase tracking-[0.18em] text-zinc-500">Registry</span>
                        </div>
                        <div class="grid gap-3 md:grid-cols-2">
                            <div
                                *ngFor="let fact of factRows()"
                                class="rounded-2xl border border-white/5 bg-black/25 p-4"
                            >
                                <p class="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{{ fact.label }}</p>
                                <p class="mt-2 text-lg font-semibold text-white">{{ fact.value }}</p>
                                <p class="mt-1 truncate text-xs text-zinc-400">{{ fact.detail }}</p>
                            </div>
                        </div>
                    </section>

                    <section class="rounded-[24px] border border-white/5 bg-white/[0.025] p-4">
                        <div class="mb-4 flex items-center justify-between gap-3">
                            <div class="flex items-center gap-2">
                                <lucide-icon [img]="GitBranchIcon" class="h-4 w-4 text-cyan-200"></lucide-icon>
                                <h3 class="text-sm font-semibold text-white">Graph Neighborhood</h3>
                            </div>
                            <span class="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{{ totalConnections }} accepted</span>
                        </div>

                        <div *ngIf="strongestConnections.length > 0; else noTopology" class="grid gap-3 md:grid-cols-2">
                            <button
                                *ngFor="let conn of strongestConnections"
                                type="button"
                                class="group rounded-2xl border border-white/5 bg-black/25 p-4 text-left transition hover:border-white/10 hover:bg-white/[0.05]"
                                (click)="onNavigate(conn.entity)"
                            >
                                <div class="flex items-center gap-3">
                                    <div
                                        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border"
                                        [style.backgroundColor]="getBgColor(conn.entity.kind)"
                                        [style.borderColor]="getBorderColor(conn.entity.kind)"
                                    >
                                        <lucide-icon [img]="getIcon(conn.entity.kind)" class="h-4 w-4" [style.color]="getColor(conn.entity.kind)"></lucide-icon>
                                    </div>
                                    <div class="min-w-0 flex-1">
                                        <p class="truncate text-sm font-semibold text-white">{{ conn.entity.label }}</p>
                                        <p class="mt-1 text-[10px] uppercase tracking-[0.16em] text-zinc-500">{{ conn.direction }} · {{ confidenceLabel(conn.confidence) }}</p>
                                    </div>
                                    <lucide-icon [img]="ExternalLinkIcon" class="h-4 w-4 text-zinc-600 transition group-hover:text-zinc-300"></lucide-icon>
                                </div>
                            </button>
                        </div>

                        <ng-template #noTopology>
                            <div class="rounded-2xl border border-dashed border-white/10 bg-black/20 p-5">
                                <div class="flex items-start gap-3">
                                    <lucide-icon [img]="SearchIcon" class="mt-0.5 h-5 w-5" [style.color]="getColor(entity.kind)"></lucide-icon>
                                    <div>
                                        <p class="text-sm font-semibold text-white">Topology is still empty</p>
                                        <p class="mt-2 text-xs leading-6 text-zinc-400">
                                            The entity exists in the registry, but no accepted edge points in or out. Index mentions, create a manual relationship, or merge duplicate labels before trusting absence as story truth.
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </ng-template>
                    </section>

                    <section *ngIf="groupedRelationships.length > 0" class="space-y-4">
                        <div class="flex items-center gap-3 px-1">
                            <div class="h-px flex-1 bg-white/5"></div>
                            <span class="text-[11px] font-semibold uppercase tracking-[0.22em] text-zinc-500">Relation Groups</span>
                            <div class="h-px flex-1 bg-white/5"></div>
                        </div>
                        <app-connection-group
                            *ngFor="let group of groupedRelationships"
                            [group]="group"
                            (onNavigate)="onNavigate($event)"
                        ></app-connection-group>
                    </section>
                </div>

                <aside class="space-y-4">
                    <section class="rounded-[24px] border border-white/5 bg-white/[0.025] p-4">
                        <div class="mb-4 flex items-center gap-2">
                            <lucide-icon [img]="LayersIcon" class="h-4 w-4 text-cyan-200"></lucide-icon>
                            <h3 class="text-sm font-semibold text-white">Evidence Receipts</h3>
                        </div>
                        <div *ngIf="evidenceCards.length > 0; else noEvidence" class="space-y-3">
                            <div
                                *ngFor="let card of evidenceCards"
                                class="rounded-2xl border border-white/5 bg-black/25 p-4"
                            >
                                <div class="flex items-start justify-between gap-3">
                                    <div class="min-w-0">
                                        <p class="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{{ card.title }}</p>
                                        <p class="mt-2 truncate text-sm font-semibold text-white">{{ card.value }}</p>
                                        <p class="mt-1 truncate text-xs text-zinc-400">{{ card.detail }}</p>
                                    </div>
                                    <span class="rounded-full border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-zinc-300">
                                        {{ confidenceLabel(card.confidence) }}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <ng-template #noEvidence>
                            <p class="rounded-2xl border border-dashed border-white/10 bg-black/20 p-4 text-xs leading-6 text-zinc-400">
                                No source receipts are attached yet. This should fill with source spans, calendar anchors, and accepted relationship evidence as the ledger matures.
                            </p>
                        </ng-template>
                    </section>

                    <section class="rounded-[24px] border border-white/5 bg-white/[0.025] p-4">
                        <div class="mb-4 flex items-center gap-2">
                            <lucide-icon [img]="ClockIcon" class="h-4 w-4 text-cyan-200"></lucide-icon>
                            <h3 class="text-sm font-semibold text-white">Timeline Pulse</h3>
                        </div>
                        <div class="space-y-3">
                            <div class="rounded-2xl border border-white/5 bg-black/25 p-4">
                                <p class="text-[10px] uppercase tracking-[0.18em] text-zinc-500">Registered</p>
                                <p class="mt-2 text-sm font-semibold text-white">{{ formattedDate(entity.createdAt) }}</p>
                            </div>
                            <div class="rounded-2xl border border-white/5 bg-black/25 p-4">
                                <p class="text-[10px] uppercase tracking-[0.18em] text-zinc-500">Last Seen</p>
                                <p class="mt-2 text-sm font-semibold text-white">{{ formattedDate(entity.lastSeenDate) }}</p>
                            </div>
                        </div>
                    </section>

                    <section class="rounded-[24px] border border-white/5 bg-white/[0.025] p-4">
                        <div class="mb-4 flex items-center gap-2">
                            <lucide-icon [img]="FingerprintIcon" class="h-4 w-4 text-cyan-200"></lucide-icon>
                            <h3 class="text-sm font-semibold text-white">Next Actions</h3>
                        </div>
                        <div class="grid gap-2">
                            <button type="button" class="dossier-action" (click)="editRequested.emit(entity)">
                                <lucide-icon [img]="PencilIcon" class="h-4 w-4"></lucide-icon>
                                Refine aliases and kind
                            </button>
                            <button type="button" class="dossier-action" (click)="navigateRequested.emit(entity)">
                                <lucide-icon [img]="PinIcon" class="h-4 w-4"></lucide-icon>
                                Focus atlas on entity
                            </button>
                            <button type="button" class="dossier-action" (click)="openRelationshipComposer()">
                                <lucide-icon [img]="PlusIcon" class="h-4 w-4"></lucide-icon>
                                Create first relationship
                            </button>
                            <div class="dossier-action dossier-action-passive">
                                <lucide-icon [img]="MergeIcon" class="h-4 w-4"></lucide-icon>
                                Review duplicate candidates
                            </div>
                        </div>
                    </section>

                    <section *ngIf="relationshipComposerOpen" class="rounded-[24px] border border-cyan-300/15 bg-cyan-300/[0.035] p-4">
                        <div class="mb-4 flex items-start justify-between gap-3">
                            <div>
                                <div class="flex items-center gap-2">
                                    <lucide-icon [img]="PlusIcon" class="h-4 w-4 text-cyan-200"></lucide-icon>
                                    <h3 class="text-sm font-semibold text-white">Create Relationship</h3>
                                </div>
                                <p class="mt-1 text-xs leading-5 text-zinc-400">Adds a manual registry edge for this entity.</p>
                            </div>
                            <button
                                type="button"
                                class="rounded-lg border border-white/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-400 transition hover:bg-white/[0.05] hover:text-white"
                                (click)="closeRelationshipComposer()"
                            >
                                Close
                            </button>
                        </div>

                        <div class="space-y-3">
                            <label class="block">
                                <span class="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Target entity</span>
                                <select
                                    class="dossier-input"
                                    [(ngModel)]="relationshipTargetId"
                                >
                                    <option value="">Choose target...</option>
                                    <option *ngFor="let target of relationshipTargets()" [value]="target.id">
                                        {{ target.label }} · {{ displayKind(target.kind) }}
                                    </option>
                                </select>
                            </label>

                            <label class="block">
                                <span class="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Relation</span>
                                <input
                                    class="dossier-input"
                                    [(ngModel)]="relationshipType"
                                    list="graph-relation-presets"
                                    placeholder="knows, appears_with, located_in..."
                                />
                                <datalist id="graph-relation-presets">
                                    <option value="knows"></option>
                                    <option value="appears_with"></option>
                                    <option value="related_to"></option>
                                    <option value="located_in"></option>
                                    <option value="member_of"></option>
                                    <option value="opposes"></option>
                                    <option value="protects"></option>
                                    <option value="owns"></option>
                                </datalist>
                            </label>

                            <div class="grid grid-cols-2 gap-2">
                                <button
                                    type="button"
                                    class="rounded-xl border px-3 py-2 text-xs font-semibold transition"
                                    [class.border-cyan-300/40]="relationshipDirection === 'outgoing'"
                                    [class.bg-cyan-300/10]="relationshipDirection === 'outgoing'"
                                    [class.text-cyan-100]="relationshipDirection === 'outgoing'"
                                    [class.border-white/10]="relationshipDirection !== 'outgoing'"
                                    [class.text-zinc-400]="relationshipDirection !== 'outgoing'"
                                    (click)="relationshipDirection = 'outgoing'"
                                >
                                    {{ entity.label }} -> Target
                                </button>
                                <button
                                    type="button"
                                    class="rounded-xl border px-3 py-2 text-xs font-semibold transition"
                                    [class.border-cyan-300/40]="relationshipDirection === 'incoming'"
                                    [class.bg-cyan-300/10]="relationshipDirection === 'incoming'"
                                    [class.text-cyan-100]="relationshipDirection === 'incoming'"
                                    [class.border-white/10]="relationshipDirection !== 'incoming'"
                                    [class.text-zinc-400]="relationshipDirection !== 'incoming'"
                                    (click)="relationshipDirection = 'incoming'"
                                >
                                    Target -> {{ entity.label }}
                                </button>
                            </div>

                            <p *ngIf="relationshipError" class="text-xs leading-5 text-red-300">{{ relationshipError }}</p>

                            <button
                                type="button"
                                class="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-cyan-300/30 bg-cyan-300/10 px-3 py-2.5 text-xs font-semibold text-cyan-50 transition hover:bg-cyan-300/15"
                                (click)="createRelationship()"
                            >
                                <lucide-icon [img]="GitBranchIcon" class="h-4 w-4"></lucide-icon>
                                Add relationship
                            </button>
                        </div>
                    </section>
                </aside>
            </section>
        </div>
    `,
    styles: [`
        .dossier-action {
            display: inline-flex;
            align-items: center;
            gap: 0.625rem;
            min-height: 2.5rem;
            border-radius: 0.875rem;
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(0,0,0,0.24);
            padding: 0.625rem 0.75rem;
            color: rgb(212 212 216);
            font-size: 0.75rem;
            font-weight: 600;
            text-align: left;
            transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
        }

        .dossier-action:hover {
            border-color: rgba(255,255,255,0.14);
            background: rgba(255,255,255,0.05);
            color: white;
        }

        .dossier-action-passive {
            color: rgb(113 113 122);
            cursor: default;
        }

        .dossier-action-passive:hover {
            border-color: rgba(255,255,255,0.08);
            background: rgba(0,0,0,0.24);
            color: rgb(113 113 122);
        }

        .dossier-input {
            width: 100%;
            min-height: 2.5rem;
            border-radius: 0.875rem;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.34);
            padding: 0.625rem 0.75rem;
            color: white;
            font-size: 0.75rem;
            outline: none;
        }

        .dossier-input:focus {
            border-color: rgba(103,232,249,0.45);
            box-shadow: 0 0 0 1px rgba(103,232,249,0.12);
        }
    `],
})
export class GraphDetailComponent implements OnChanges {
    @Input() entity!: RegisteredEntity;
    @Output() editRequested = new EventEmitter<RegisteredEntity>();
    @Output() navigateRequested = new EventEmitter<RegisteredEntity>();

    groupedRelationships: ConnectionGroup[] = [];
    totalConnections = 0;
    strongestConnections: ConnectionGroup['connections'] = [];
    relationTypes: string[] = [];
    evidenceCards: EntityEvidenceCard[] = [];
    copiedEntityId = false;
    relationshipComposerOpen = false;
    relationshipTargetId = '';
    relationshipType = 'related_to';
    relationshipDirection: 'outgoing' | 'incoming' = 'outgoing';
    relationshipError = '';
    readonly PencilIcon = Pencil;
    readonly GitBranchIcon = GitBranch;
    readonly ClockIcon = Clock3;
    readonly BadgeIcon = BadgeCheck;
    readonly FingerprintIcon = Fingerprint;
    readonly SearchIcon = Search;
    readonly PlusIcon = Plus;
    readonly MergeIcon = Merge;
    readonly PinIcon = Pin;
    readonly ExternalLinkIcon = ExternalLink;
    readonly CopyIcon = Copy;
    readonly LayersIcon = Layers3;
    readonly TargetIcon = Target;

    ngOnChanges(changes: SimpleChanges) {
        if (changes['entity'] && this.entity) {
            this.refreshConnections();
            this.evidenceCards = this.buildEvidenceCards();
            this.copiedEntityId = false;
            this.relationshipError = '';
        }
    }

    refreshConnections() {
        if (!this.entity) {
            return;
        }

        const edges = smartGraphRegistry.getEdgesForEntity(this.entity.id);
        this.totalConnections = edges.length;

        const groups: Record<string, ConnectionGroup> = {};
        const strongest: ConnectionGroup['connections'] = [];

        for (const edge of edges) {
            if (!groups[edge.type]) {
                groups[edge.type] = { type: edge.type, connections: [] };
            }

            const isSource = edge.sourceId === this.entity.id;
            const otherId = isSource ? edge.targetId : edge.sourceId;
            const otherEntity = smartGraphRegistry.getEntityById(otherId);

            if (otherEntity) {
                const connection = {
                    id: edge.id,
                    entity: otherEntity,
                    direction: isSource ? 'outgoing' : 'incoming',
                    confidence: edge.confidence,
                } satisfies ConnectionGroup['connections'][number];
                groups[edge.type].connections.push(connection);
                strongest.push(connection);
            }
        }

        this.groupedRelationships = Object.values(groups)
            .map((group) => ({
                ...group,
                connections: [...group.connections].sort((left, right) => right.confidence - left.confidence),
            }))
            .sort((left, right) => right.connections.length - left.connections.length || left.type.localeCompare(right.type));
        this.strongestConnections = strongest
            .sort((left, right) => right.confidence - left.confidence)
            .slice(0, 4);
        this.relationTypes = this.groupedRelationships.map((group) => group.type);
    }

    onNavigate(target: RegisteredEntity) {
        this.navigateRequested.emit(target);
    }

    getColor(kind: string): string {
        return entityColorStore.getEntityColor(kind);
    }

    getBgColor(kind: string): string {
        return entityColorStore.getEntityBgColor(kind, 0.15);
    }

    getBorderColor(kind: string): string {
        return entityColorStore.getEntityBgColor(kind, 0.4);
    }

    heroGlow(kind: string): string {
        const glow = entityColorStore.getEntityBgColor(kind, 0.22);
        return `radial-gradient(circle at top left, ${glow}, transparent 42%), radial-gradient(circle at 82% 18%, rgba(34,211,238,0.12), transparent 28%), linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))`;
    }

    getIcon(kind: string): any {
        return ENTITY_ICONS[kind as EntityKind] || ENTITY_ICONS['UNKNOWN'];
    }

    sourceLabel(): string {
        return entitySourceLabel(this.entity);
    }

    sourceTone(): string {
        return entitySourceSystem(this.entity);
    }

    dossierSummary(): string {
        const name = this.entity.label;
        const kind = this.readableKind(this.entity.kind);
        const source = this.sourceLabel().toLowerCase();
        if (this.totalConnections > 0) {
            const relations = this.relationTypes.slice(0, 3).map(readableRelation).join(', ');
            return `${name} is a ${kind} with ${this.totalConnections} accepted graph ${this.totalConnections === 1 ? 'link' : 'links'}${relations ? ` across ${relations}` : ''}. The dossier is sourced from ${source} registry data and current atlas relationships.`;
        }
        if (this.entity.totalMentions > 0) {
            return `${name} is a registered ${kind} with ${this.entity.totalMentions} recorded ${this.entity.totalMentions === 1 ? 'mention' : 'mentions'}, but no accepted graph links yet. This is a good candidate for source-span review and relationship extraction.`;
        }
        return `${name} is a registered ${kind}. The atlas knows the identity, but it has not earned graph topology yet. Start by indexing source mentions, attaching aliases, or creating the first relationship.`;
    }

    factRows(): DossierFact[] {
        const rows: DossierFact[] = [
            { label: 'Kind', value: this.readableKind(this.entity.kind), detail: this.entity.subtype || 'Registry type' },
            { label: 'Source', value: this.sourceLabel(), detail: this.sourceTone() },
            { label: 'Mentions', value: String(this.entity.totalMentions || 0), detail: `${this.noteCount()} note ${this.noteCount() === 1 ? 'source' : 'sources'}` },
            { label: 'Links', value: String(this.totalConnections), detail: `${this.groupedRelationships.length} relation ${this.groupedRelationships.length === 1 ? 'group' : 'groups'}` },
        ];
        if (this.entity.aliases.length > 0) {
            rows.push({ label: 'Aliases', value: String(this.entity.aliases.length), detail: this.entity.aliases.slice(0, 2).join(', ') });
        }
        return rows;
    }

    buildEvidenceCards(): EntityEvidenceCard[] {
        const cards: EntityEvidenceCard[] = [];
        if (this.entity.firstNote) {
            cards.push({
                title: 'First Registered Note',
                value: this.entity.firstNote,
                detail: 'Initial source anchor',
                confidence: 0.72,
            });
        }
        if (this.entity.totalMentions > 0) {
            cards.push({
                title: 'Mention Ledger',
                value: `${this.entity.totalMentions} mentions`,
                detail: `${this.noteCount()} note ${this.noteCount() === 1 ? 'source' : 'sources'}`,
                confidence: 0.86,
            });
        }
        for (const edge of this.topEdges(2)) {
            cards.push({
                title: readableRelation(edge.type),
                value: this.edgeCounterpartyLabel(edge),
                detail: edge.sourceNote ? `Source note ${edge.sourceNote}` : edge.provenance || 'Graph edge',
                confidence: edge.confidence,
            });
        }
        return cards.slice(0, 4);
    }

    topEdges(limit: number): Edge[] {
        return smartGraphRegistry.getEdgesForEntity(this.entity.id)
            .sort((left, right) => right.confidence - left.confidence)
            .slice(0, limit);
    }

    edgeCounterpartyLabel(edge: Edge): string {
        const otherId = edge.sourceId === this.entity.id ? edge.targetId : edge.sourceId;
        return smartGraphRegistry.getEntityById(otherId)?.label || otherId;
    }

    noteCount(): number {
        return Math.max(this.entity.mentionsByNote?.size || 0, this.entity.firstNote ? 1 : 0);
    }

    readableKind(kind: string): string {
        return this.displayKind(kind).replace(/_/g, ' ').toLowerCase();
    }

    displayKind(kind: string): string {
        return normalizeEntityKind(kind) || String(kind || 'UNKNOWN').toUpperCase();
    }

    readableRelation(type: string): string {
        return readableRelation(type);
    }

    formattedDate(date: Date | number | undefined): string {
        if (!date) return 'Unknown';
        const value = date instanceof Date ? date : new Date(date);
        if (Number.isNaN(value.getTime())) return 'Unknown';
        return value.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    }

    confidenceLabel(confidence: number): string {
        const normalized = Number.isFinite(confidence) ? confidence : 0;
        return `${Math.round(normalized * 100)}%`;
    }

    actionHint(): string {
        if (this.totalConnections === 0) return 'Run graph indexing or create a relationship to make topology.';
        return 'Review top links and source receipts before mutating the graph.';
    }

    async copyEntityId() {
        try {
            await navigator.clipboard?.writeText(this.entity.id);
            this.copiedEntityId = true;
            setTimeout(() => {
                this.copiedEntityId = false;
            }, 1200);
        } catch {
            this.copiedEntityId = false;
        }
    }

    openRelationshipComposer() {
        this.relationshipComposerOpen = true;
        this.relationshipError = '';
        this.relationshipType = this.relationshipType.trim() || 'related_to';
        const targets = this.relationshipTargets();
        if (!this.relationshipTargetId && targets.length > 0) {
            this.relationshipTargetId = targets[0].id;
        }
    }

    closeRelationshipComposer() {
        this.relationshipComposerOpen = false;
        this.relationshipError = '';
    }

    relationshipTargets(): RegisteredEntity[] {
        return smartGraphRegistry
            .getAll()
            .filter((candidate) => candidate.id !== this.entity.id)
            .sort((left, right) => left.label.localeCompare(right.label));
    }

    createRelationship() {
        this.relationshipError = '';
        const targetId = this.relationshipTargetId.trim();
        const relation = normalizeRelationshipType(this.relationshipType);
        if (!targetId) {
            this.relationshipError = 'Choose a target entity first.';
            return;
        }
        if (!relation) {
            this.relationshipError = 'Name the relationship first.';
            return;
        }
        const target = smartGraphRegistry.getEntityById(targetId);
        if (!target) {
            this.relationshipError = 'That target is no longer in the registry.';
            return;
        }

        const sourceId = this.relationshipDirection === 'outgoing' ? this.entity.id : target.id;
        const finalTargetId = this.relationshipDirection === 'outgoing' ? target.id : this.entity.id;
        smartGraphRegistry.createEdge(sourceId, finalTargetId, relation, {
            weight: 1,
            provenance: 'manual',
            sourceNote: this.entity.firstNote,
        });

        this.refreshConnections();
        this.evidenceCards = this.buildEvidenceCards();
        this.relationshipComposerOpen = false;
    }
}

interface DossierFact {
    label: string;
    value: string;
    detail: string;
}

interface EntityEvidenceCard {
    title: string;
    value: string;
    detail: string;
    confidence: number;
}

function readableRelation(type: string): string {
    return String(type || 'relationship')
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();
}

function normalizeRelationshipType(value: string): string {
    return String(value || '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
}
