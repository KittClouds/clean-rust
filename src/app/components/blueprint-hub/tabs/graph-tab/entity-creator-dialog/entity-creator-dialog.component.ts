import { Component, EventEmitter, Input, Output, signal, computed, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DialogModule } from 'primeng/dialog';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { CheckboxModule } from 'primeng/checkbox';
import { LucideAngularModule, User, MapPin, Users, Package, Network, Calendar, Lightbulb, Sparkles, Plus, X } from 'lucide-angular';
import { entityColorStore, normalizeEntityKind } from '../../../../../lib/store/entityColorStore';

// Entity kinds and icons (colors come from entityColorStore)
const ENTITY_KINDS = ['CHARACTER', 'LOCATION', 'NPC', 'ITEM', 'NETWORK', 'EVENT', 'CONCEPT'] as const;
type EntityKind = typeof ENTITY_KINDS[number] | string;

const ENTITY_ICONS: Record<string, any> = {
    'CHARACTER': User,
    'LOCATION': MapPin,
    'NPC': Users,
    'ITEM': Package,
    'FACTION': Network,
    'NETWORK': Network,
    'EVENT': Calendar,
    'CONCEPT': Lightbulb,
};

interface AutoAliasConfig {
    lastName: boolean;
    firstLast: boolean;
    initials: boolean;
}

function generateAutoAliases(label: string, config: AutoAliasConfig): string[] {
    const tokens = label.toLowerCase().split(/\s+/).filter(t => t && t.length > 1);
    if (tokens.length <= 1) return [];

    const aliases: string[] = [];
    const first = tokens[0];
    const last = tokens[tokens.length - 1];

    if (config.lastName && last.length >= 3) {
        aliases.push(last.charAt(0).toUpperCase() + last.slice(1));
    }

    if (config.firstLast && tokens.length >= 3) {
        const combined = `${first} ${last}`;
        aliases.push(combined.split(' ').map(t => t.charAt(0).toUpperCase() + t.slice(1)).join(' '));
    }

    if (config.initials && tokens.length >= 2) {
        const initials = tokens.map(t => t[0].toUpperCase()).join('');
        if (initials.length >= 2 && initials.length <= 4) {
            aliases.push(initials);
        }
    }

    return aliases;
}

export interface EntityCreatorData {
    id?: string;
    label: string;
    kind: string;
    aliases: string[];
}

@Component({
    selector: 'app-entity-creator-dialog',
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        DialogModule,
        ButtonModule,
        InputTextModule,
        CheckboxModule,
        LucideAngularModule,
    ],
    template: `
        <p-dialog
            [(visible)]="visible"
            [modal]="true"
            [draggable]="false"
            [resizable]="false"
            [closable]="true"
            [style]="{ width: '520px' }"
            [contentStyle]="{ padding: '0' }"
            styleClass="entity-creator-dialog"
            (onHide)="onCancel()"
        >
            <ng-template pTemplate="header">
                <span class="text-lg font-semibold">{{ editEntity ? 'Edit Entity' : 'Create Entity' }}</span>
            </ng-template>

            <ng-template pTemplate="content">
            <div class="p-5 space-y-5">
                <!-- Name Input -->
                <div class="space-y-2">
                    <label class="text-sm text-muted-foreground block">Name</label>
                    <input
                        pInputText
                        type="text"
                        class="w-full h-12 text-base !bg-background !border-border"
                        placeholder="Monkey D. Luffy"
                        [(ngModel)]="label"
                        autofocus
                    />
                </div>

                <!-- Kind Selector Grid -->
                <div class="flex flex-wrap gap-2">
                    @for (k of allKinds; track k) {
                        <button
                            type="button"
                            class="flex flex-col items-center gap-1 px-3 py-2 rounded-xl transition-all border-2"
                            [class.border-current]="selectedKind() === k"
                            [class.border-transparent]="selectedKind() !== k"
                            [class.hover:border-muted]="selectedKind() !== k"
                            [style.color]="selectedKind() === k ? getColor(k) : 'var(--muted-foreground)'"
                            [style.backgroundColor]="selectedKind() === k ? getBgColor(k) : 'transparent'"
                            (click)="selectKind(k)"
                        >
                            <div
                                class="w-10 h-10 rounded-full flex items-center justify-center transition-all"
                                [style.backgroundColor]="getBgColor(k)"
                                [style.borderColor]="getColor(k)"
                                [style.borderWidth]="selectedKind() === k ? '2px' : '1px'"
                                [style.borderStyle]="'solid'"
                            >
                                <lucide-icon [img]="getIcon(k)" class="w-5 h-5" [style.color]="getColor(k)"></lucide-icon>
                            </div>
                            <span class="text-[10px] font-medium uppercase tracking-wide">{{ k.slice(0, 9) }}</span>
                        </button>
                    }

                    <!-- Custom Kind Button -->
                    @if (!showCustomInput()) {
                        <button
                            type="button"
                            class="flex flex-col items-center gap-1 px-3 py-2 rounded-xl border-2 border-dashed border-muted hover:border-muted-foreground transition-colors"
                            (click)="showCustomInput.set(true)"
                        >
                            <div class="w-10 h-10 rounded-full flex items-center justify-center bg-muted/50">
                                <lucide-icon [img]="PlusIcon" class="w-5 h-5 text-muted-foreground"></lucide-icon>
                            </div>
                            <span class="text-[10px] font-medium text-muted-foreground">CUSTOM</span>
                        </button>
                    }
                </div>

                <!-- Custom Kind Input -->
                @if (showCustomInput()) {
                    <div class="flex gap-2">
                        <input
                            pInputText
                            type="text"
                            class="flex-1 uppercase !bg-background !border-border"
                            placeholder="CUSTOM_KIND"
                            [(ngModel)]="customKindInput"
                            (keydown.enter)="addCustomKind()"
                        />
                        <p-button size="small" (onClick)="addCustomKind()">Add</p-button>
                        <p-button size="small" severity="secondary" (onClick)="showCustomInput.set(false)">Cancel</p-button>
                    </div>
                }

                <div class="border-t border-border/50"></div>

                <!-- Aliases Section -->
                <div class="space-y-3">
                    <label class="text-sm text-muted-foreground block">
                        Aliases <span class="text-xs opacity-70">(variations that match this entity)</span>
                    </label>

                    <!-- Alias Chips -->
                    <div class="flex flex-wrap gap-2">
                        @for (alias of aliases; track alias) {
                            <span
                                class="inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-sm border"
                                [style.backgroundColor]="getBgColor(selectedKind())"
                                [style.borderColor]="getColor(selectedKind())"
                                [style.color]="getColor(selectedKind())"
                            >
                                {{ alias }}
                                <button type="button" class="ml-1 hover:opacity-70" (click)="removeAlias(alias)">
                                    <lucide-icon [img]="XIcon" class="w-3 h-3"></lucide-icon>
                                </button>
                            </span>
                        }

                        <!-- Add Alias Input -->
                        <div class="inline-flex items-center gap-1">
                            <input
                                pInputText
                                type="text"
                                class="h-8 w-28 text-sm !bg-background !border-border"
                                placeholder="+ Add alias"
                                [(ngModel)]="newAlias"
                                (keydown.enter)="addAlias()"
                            />
                            @if (newAlias) {
                                <p-button size="small" [text]="true" (onClick)="addAlias()">
                                    <lucide-icon [img]="PlusIcon" class="w-4 h-4"></lucide-icon>
                                </p-button>
                            }
                        </div>
                    </div>

                    <!-- Auto-alias Checkboxes -->
                    <div class="flex flex-wrap gap-4 text-sm">
                        <label class="flex items-center gap-2 cursor-pointer">
                            <p-checkbox [(ngModel)]="autoConfig.lastName" [binary]="true"></p-checkbox>
                            <span class="text-muted-foreground">Last name</span>
                        </label>
                        <label class="flex items-center gap-2 cursor-pointer">
                            <p-checkbox [(ngModel)]="autoConfig.firstLast" [binary]="true"></p-checkbox>
                            <span class="text-muted-foreground">First+Last</span>
                        </label>
                        <label class="flex items-center gap-2 cursor-pointer">
                            <p-checkbox [(ngModel)]="autoConfig.initials" [binary]="true"></p-checkbox>
                            <span class="text-muted-foreground">Initials</span>
                        </label>
                    </div>

                    <!-- Auto-alias Preview -->
                    @if (autoAliases().length > 0) {
                        <div class="text-xs text-muted-foreground">
                            Auto:
                            @for (a of autoAliases(); track a; let last = $last) {
                                <span class="text-foreground/70">{{ a }}{{ last ? '' : ', ' }}</span>
                            }
                        </div>
                    }
                </div>

                <!-- Preview -->
                @if (label.trim()) {
                    <div class="border-t border-border/50"></div>
                    <div class="space-y-2">
                        <label class="text-sm text-muted-foreground block">Preview</label>
                        <div class="rounded-lg p-3 text-sm bg-muted/50">
                            <p class="text-muted-foreground">
                                The winds whispered of
                                <span
                                    class="px-1.5 py-0.5 rounded"
                                    [style.backgroundColor]="getBgColor(selectedKind())"
                                    [style.color]="getColor(selectedKind())"
                                >{{ label }}</span>.
                                @if (aliases.length > 0) {
                                    Known as
                                    <span
                                        class="px-1.5 py-0.5 rounded"
                                        [style.backgroundColor]="getBgColor(selectedKind())"
                                        [style.color]="getColor(selectedKind())"
                                    >{{ aliases[0] }}</span>.
                                }
                            </p>
                        </div>
                    </div>
                }
            </div>
            </ng-template>

            <ng-template pTemplate="footer">
                <div class="flex justify-end gap-2 px-5 pb-5">
                    <p-button severity="secondary" [text]="true" (onClick)="onCancel()">Cancel</p-button>
                    <p-button
                        [disabled]="!label.trim()"
                        [style.backgroundColor]="getColor(selectedKind())"
                        [style.borderColor]="getColor(selectedKind())"
                        (onClick)="onSubmit()"
                    >
                        {{ editEntity ? 'Save Changes' : 'Create Entity' }}
                    </p-button>
                </div>
            </ng-template>
        </p-dialog>
    `,
    styles: [`
        :host ::ng-deep .entity-creator-dialog {
            .p-dialog {
                background: hsl(var(--background));
                border: 1px solid hsl(var(--border));
                border-radius: 1rem;
                overflow: hidden;
            }
            .p-dialog-header {
                background: hsl(var(--background));
                border-bottom: 1px solid hsl(var(--border) / 0.5);
                padding: 1rem 1.25rem;
            }
            .p-dialog-content {
                background: hsl(var(--background));
            }
            .p-dialog-footer {
                background: hsl(var(--background));
                border-top: 1px solid hsl(var(--border) / 0.5);
                padding: 0;
            }
        }
    `]
})
export class EntityCreatorDialogComponent implements OnChanges {
    @Input() visible = false;
    @Input() editEntity?: EntityCreatorData;
    @Output() visibleChange = new EventEmitter<boolean>();
    @Output() save = new EventEmitter<EntityCreatorData>();

    // Icons
    PlusIcon = Plus;
    XIcon = X;

    // Form state
    label = '';
    aliases: string[] = [];
    newAlias = '';
    customKindInput = '';

    selectedKind = signal<string>('CHARACTER');
    showCustomInput = signal(false);
    customKinds = signal<string[]>([]);

    autoConfig: AutoAliasConfig = {
        lastName: true,
        firstLast: true,
        initials: false,
    };

    allKinds: string[] = [...ENTITY_KINDS];

    autoAliases = computed(() => {
        return generateAutoAliases(this.label, this.autoConfig);
    });

    ngOnChanges(changes: SimpleChanges) {
        if (changes['editEntity']?.currentValue?.kind) {
            this.syncAvailableKinds(changes['editEntity'].currentValue.kind);
        }

        if (changes['visible'] && this.visible) {
            if (this.editEntity) {
                this.syncAvailableKinds(this.editEntity.kind);
                this.label = this.editEntity.label;
                this.selectedKind.set(this.canonicalKind(this.editEntity.kind));
                this.aliases = [...this.editEntity.aliases];
            } else {
                this.resetForm();
            }
        }
    }

    resetForm() {
        this.label = '';
        this.selectedKind.set('CHARACTER');
        this.aliases = [];
        this.newAlias = '';
        this.showCustomInput.set(false);
        this.customKindInput = '';
        this.syncAvailableKinds();
    }

    selectKind(kind: string) {
        this.selectedKind.set(kind);
    }

    addCustomKind() {
        const trimmed = this.customKindInput.trim().toUpperCase();
        if (trimmed && !this.allKinds.includes(trimmed as any)) {
            this.customKinds.update(k => [...k, trimmed]);
            this.syncAvailableKinds(trimmed);
            this.selectedKind.set(trimmed);
        }
        this.showCustomInput.set(false);
        this.customKindInput = '';
    }

    addAlias() {
        const trimmed = this.newAlias.trim();
        if (trimmed && !this.aliases.includes(trimmed)) {
            this.aliases = [...this.aliases, trimmed];
            this.newAlias = '';
        }
    }

    removeAlias(alias: string) {
        this.aliases = this.aliases.filter(a => a !== alias);
    }

    getColor(kind: string): string {
        return entityColorStore.getEntityColor(kind);
    }

    getBgColor(kind: string): string {
        return `${this.getColor(kind)}20`;
    }

    getIcon(kind: string): any {
        return ENTITY_ICONS[kind] || Sparkles;
    }

    private syncAvailableKinds(activeKind?: string) {
        const kinds = [...ENTITY_KINDS, ...this.customKinds()];
        const normalizedActiveKind = activeKind ? this.canonicalKind(activeKind) : undefined;
        if (normalizedActiveKind && !kinds.includes(normalizedActiveKind as any)) {
            kinds.push(normalizedActiveKind);
        }
        this.allKinds = Array.from(new Set(kinds));
    }

    private canonicalKind(kind: string): string {
        return normalizeEntityKind(kind) || kind.trim().toUpperCase();
    }

    onCancel() {
        this.resetForm();
        this.visibleChange.emit(false);
    }

    onSubmit() {
        if (!this.label.trim()) return;

        const finalAliases = [...new Set([...this.aliases, ...this.autoAliases()])];

        this.save.emit({
            id: this.editEntity?.id,
            label: this.label.trim(),
            kind: this.selectedKind(),
            aliases: finalAliases,
        });

        this.resetForm();
        this.visibleChange.emit(false);
    }
}
