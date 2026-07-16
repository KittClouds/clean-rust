import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LucideAngularModule, User, Users, MapPin, Calendar, Hash, FileText, Zap, Tag, Shield, Package, Lightbulb, Globe } from 'lucide-angular';
import { EntityKind } from '../../../../../../lib/Scanner/types';
import { RegisteredEntity } from '../../../../../../lib/registry';
import { entityColorStore, normalizeEntityKind } from '../../../../../../lib/store/entityColorStore';

// Entity icons (colors come from entityColorStore)
const ENTITY_ICONS: Record<string, any> = {
    'CHARACTER': User,
    'NPC': Users,
    'CREATURE': Users,
    'FACTION': Globe,
    'ORGANIZATION': Shield,
    'NETWORK': Globe,
    'LOCATION': MapPin,
    'EVENT': Calendar,
    'TIMELINE': Calendar,
    'ITEM': Package,
    'OBJECT': Hash,
    'CONCEPT': Lightbulb,
    'NARRATIVE': FileText,
    'ARC': FileText,
    'ACT': FileText,
    'CHAPTER': FileText,
    'SCENE': FileText,
    'BEAT': Zap,
    'LORE': FileText,
    'UNKNOWN': Tag
};

export interface ConnectionGroup {
    type: string;
    connections: Array<{
        id: string;
        entity: RegisteredEntity;
        direction: 'incoming' | 'outgoing' | 'bidirectional';
        confidence: number;
    }>;
}

@Component({
    selector: 'app-connection-group',
    standalone: true,
    imports: [CommonModule, LucideAngularModule],
    template: `
        <section class="overflow-hidden rounded-[26px] border border-white/5 bg-white/[0.03] shadow-[0_18px_50px_rgba(0,0,0,0.18)]">
            <div class="flex items-center gap-3 border-b border-white/5 px-5 py-4">
                <div class="h-px flex-1 bg-white/5"></div>
                <span class="text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
                    {{ group.type.replace('_', ' ') }}
                </span>
                <span class="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] font-mono text-zinc-300">
                    {{ group.connections.length }}
                </span>
                <div class="h-px flex-1 bg-white/5"></div>
            </div>

            <div class="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
                <button
                    *ngFor="let conn of group.connections"
                    type="button"
                    class="group relative overflow-hidden rounded-2xl border border-white/5 bg-black/20 p-4 text-left transition hover:border-white/10 hover:bg-white/[0.04]"
                    (click)="onNavigate.emit(conn.entity)"
                >
                    <div
                        class="pointer-events-none absolute inset-0 opacity-0 transition group-hover:opacity-100"
                        [style.background]="cardGlow(conn.entity.kind)"
                    ></div>

                    <div class="relative flex items-start gap-3">
                        <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border"
                             [style.backgroundColor]="getBgColor(conn.entity.kind)"
                             [style.borderColor]="getBorderColor(conn.entity.kind)">
                            <lucide-icon [img]="getIcon(conn.entity.kind)" [class]="'h-4 w-4'" [style.color]="getColor(conn.entity.kind)"></lucide-icon>
                        </div>
                        <div class="min-w-0 flex-1">
                            <div class="flex items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <p class="truncate text-sm font-semibold text-white">{{ conn.entity.label }}</p>
                                    <p class="mt-1 text-[11px] uppercase tracking-[0.18em] text-zinc-500">{{ displayKind(conn.entity.kind) }}</p>
                                </div>
                                <span class="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-zinc-400">
                                    {{ conn.direction }}
                                </span>
                            </div>

                            <div class="mt-4 flex items-center justify-between gap-3">
                                <span class="text-[11px] text-zinc-500">Confidence</span>
                                <span class="text-[11px] font-medium text-zinc-300">{{ confidenceLabel(conn.confidence) }}</span>
                            </div>
                            <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-white/5">
                                <div
                                    class="h-full rounded-full"
                                    [style.width.%]="confidencePercent(conn.confidence)"
                                    [style.backgroundColor]="getColor(conn.entity.kind)"
                                ></div>
                            </div>
                        </div>
                    </div>
                </button>
            </div>
        </section>
    `
})
export class ConnectionGroupComponent {
    @Input() group!: ConnectionGroup;
    @Output() onNavigate = new EventEmitter<RegisteredEntity>();

    getColor(kind: string): string {
        return entityColorStore.getEntityColor(kind);
    }

    getBgColor(kind: string): string {
        const color = this.getColor(kind);
        return `${color}20`;
    }

    getBorderColor(kind: string): string {
        const color = this.getColor(kind);
        return `${color}4d`;
    }

    getIcon(kind: string): any {
        return ENTITY_ICONS[this.displayKind(kind) as EntityKind] || ENTITY_ICONS['UNKNOWN'];
    }

    displayKind(kind: string): string {
        return normalizeEntityKind(kind) || String(kind || 'UNKNOWN').toUpperCase();
    }

    confidencePercent(confidence: number): number {
        const normalized = Number.isFinite(confidence) ? confidence : 0;
        return Math.max(8, Math.min(100, Math.round(normalized * 100)));
    }

    confidenceLabel(confidence: number): string {
        const normalized = Number.isFinite(confidence) ? confidence : 0;
        return `${Math.round(normalized * 100)}%`;
    }

    cardGlow(kind: string): string {
        return `radial-gradient(circle at top left, ${this.getBgColor(kind)}, transparent 45%)`;
    }
}
