// src/app/components/sidebar/file-tree/tree-node.component.ts
// Individual tree row - VS Code style with connector lines and inline rename

import { Component, Input, Output, EventEmitter, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule, Folder, FolderOpen, FileText, Star, BookOpen, MoreVertical, GripVertical } from 'lucide-angular';
import type { FlatTreeNode } from '../../../lib/arborist/types';

@Component({
    selector: 'app-tree-node',
    standalone: true,
    imports: [CommonModule, LucideAngularModule, FormsModule],
    template: `
        <div
            class="tree-node relative flex items-center gap-1.5 h-7 w-full pr-2 cursor-pointer transition-colors duration-100"
            [class.bg-accent]="selected"
            [class.hover:bg-muted/50]="!selected && !isEditing"
            [class.narrative-root]="node.isNarrativeRoot"
            [class.opacity-50]="isBeingDragged"
            [class.grab]="isReorderMode"
            [class.cursor-grab]="isReorderMode"
            [style.paddingLeft.px]="node.level * 16"
            [draggable]="!isReorderMode && node.type === 'note'"
            (click)="onNodeClick()"
            (dragstart)="onNoteDragStart($event)">

            <!-- Drag Handle (reorder mode only) -->
            <div
                [class.hidden]="!isReorderMode"
                data-swapy-handle
                class="drag-handle shrink-0 z-10 p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent cursor-grab active:cursor-grabbing select-none touch-none flex items-center justify-center w-6 h-6"
                (mousedown)="onDragStart($event)"
                (click)="$event.stopPropagation()">
                <lucide-icon [img]="GripVertical" size="14"></lucide-icon>
            </div>

            <!-- Connector Lines (VS Code structured style) -->
            <ng-container *ngIf="node.level > 0">
                <!-- Ancestor vertical guides -->
                <ng-container *ngFor="let hasSibling of node.ancestorHasSibling; let i = index">
                    <div
                        *ngIf="hasSibling"
                        class="absolute top-0 bottom-0 opacity-30"
                        [style.left.px]="i * 16 + 8"
                        [style.width.px]="1"
                        [style.backgroundColor]="node.effectiveColor || 'currentColor'">
                    </div>
                </ng-container>

                <!-- Current level vertical line -->
                <div
                    class="absolute opacity-30"
                    [style.left.px]="(node.level - 1) * 16 + 8"
                    [style.top]="0"
                    [style.bottom]="node.isLastChild ? '50%' : '0'"
                    [style.width.px]="1"
                    [style.backgroundColor]="node.effectiveColor || 'currentColor'">
                </div>
            </ng-container>

            <!-- Toggle Dot (folders only) -->
            <button
                *ngIf="node.type === 'folder'"
                class="flex items-center justify-center shrink-0 z-10 w-4 h-4 transition-all duration-150 hover:scale-110"
                [class.invisible]="!node.hasChildren"
                (click)="onToggle($event)">
                <!-- Expanded = hollow ring -->
                <div
                    *ngIf="node.isExpanded"
                    class="w-2 h-2 rounded-full border-[1.5px] transition-all"
                    [style.borderColor]="node.effectiveColor || 'currentColor'">
                </div>
                <!-- Collapsed = filled dot -->
                <div
                    *ngIf="!node.isExpanded"
                    class="w-2 h-2 rounded-full transition-all"
                    [style.backgroundColor]="node.effectiveColor || 'currentColor'">
                </div>
            </button>

            <!-- Spacer for notes (align with folder toggles) -->
            <div *ngIf="node.type === 'note'" class="w-4 h-4 shrink-0"></div>

            <!-- Icon: Narrative roots get special BookOpen icon -->
            <lucide-icon
                *ngIf="node.type === 'folder' && node.isNarrativeRoot"
                [img]="BookOpen"
                size="14"
                class="shrink-0 z-10"
                [style.color]="node.effectiveColor">
            </lucide-icon>
            <lucide-icon
                *ngIf="node.type === 'folder' && !node.isNarrativeRoot"
                [img]="node.isExpanded ? FolderOpen : Folder"
                size="14"
                class="shrink-0 z-10"
                [style.color]="node.effectiveColor">
            </lucide-icon>
            <lucide-icon
                *ngIf="node.type === 'note'"
                [img]="FileText"
                size="14"
                class="shrink-0 z-10 text-muted-foreground">
            </lucide-icon>

            <!-- Name (normal mode) -->
            <span
                *ngIf="!isEditing"
                class="min-w-0 truncate text-xs flex-1 z-10"
                [class.font-semibold]="node.isNarrativeRoot"
                [style.color]="(node.type === 'folder' && (node.isTypedRoot || node.isNarrativeRoot)) ? node.effectiveColor : null"
                (dblclick)="startEditing($event)">
                <span *ngIf="node.manuscriptLabel" class="opacity-50 mr-1 font-mono tracking-tighter">{{ node.manuscriptLabel }}</span>
                {{ node.name || (node.type === 'folder' ? 'New Folder' : 'Untitled') }}
            </span>

            <!-- Name (edit mode) -->
            <input
                *ngIf="isEditing"
                #editInput
                type="text"
                class="min-w-0 flex-1 z-10 text-xs bg-background border border-ring rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-ring"
                [value]="editValue"
                (input)="editValue = $any($event.target).value"
                (blur)="finishEditing()"
                (keydown.enter)="finishEditing()"
                (keydown.escape)="cancelEditing()"
                (click)="$event.stopPropagation()">

            <!-- Narrative Badge (special) -->
            <span
                *ngIf="node.isNarrativeRoot && !isEditing"
                class="text-[9px] px-1.5 py-0.5 rounded font-semibold shrink-0 z-10 uppercase tracking-wider"
                style="background-color: hsl(270, 70%, 60%, 0.15); color: hsl(270, 70%, 60%);">
                NARRATIVE
            </span>

            <!-- Entity Badge (non-narrative) -->
            <span
                *ngIf="node.entityKind && !node.isNarrativeRoot && !isEditing"
                class="text-[9px] px-1 py-0.5 rounded font-semibold shrink-0 z-10 uppercase tracking-wider"
                [style.backgroundColor]="'hsl(var(--entity-' + node.entityKind.toLowerCase() + ') / 0.15)'"
                [style.color]="'hsl(var(--entity-' + node.entityKind.toLowerCase() + '))'">
                {{ node.entitySubtype ? (node.entityKind + ':' + node.entitySubtype) : node.entityKind }}
            </span>

            <!-- Favorite Star -->
            <lucide-icon
                *ngIf="node.favorite && !isEditing"
                [img]="Star"
                size="12"
                class="shrink-0 z-10 fill-yellow-400 text-yellow-400">
            </lucide-icon>

            <!-- Kebab Menu -->
            <button
                *ngIf="!isEditing"
                type="button"
                class="kebab-menu shrink-0 z-10 flex h-6 w-6 items-center justify-center rounded transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                [attr.aria-label]="'Actions for ' + (node.name || (node.type === 'folder' ? 'folder' : 'note'))"
                title="Actions"
                (click)="onMenuClick($event)">
                <lucide-icon [img]="MoreVertical" size="14" class="text-muted-foreground"></lucide-icon>
            </button>
        </div>
    `,
    styles: [`
        :host {
            display: block;
        }
        .narrative-root {
            background: linear-gradient(90deg, hsl(270, 70%, 60%, 0.05) 0%, transparent 100%);
        }
        .kebab-menu {
            opacity: 0.72;
        }
        .tree-node:hover .kebab-menu {
            opacity: 1;
        }
        .tree-node:focus-within .kebab-menu {
            opacity: 1;
        }
    `]
})
export class TreeNodeComponent implements AfterViewChecked {
    @Input() node!: FlatTreeNode;
    @Input() selected = false;
    @Input() isEditing = false;
    @Input() isReorderMode = false;
    @Input() isBeingDragged = false;

    @Output() toggle = new EventEmitter<string>();
    @Output() select = new EventEmitter<FlatTreeNode>();
    @Output() menuClick = new EventEmitter<{ node: FlatTreeNode; event: MouseEvent }>();
    @Output() rename = new EventEmitter<{ node: FlatTreeNode; newName: string }>();
    @Output() startRename = new EventEmitter<FlatTreeNode>();
    @Output() dragState = new EventEmitter<string | null>();

    @ViewChild('editInput') editInput?: ElementRef<HTMLInputElement>;

    editValue = '';
    private needsFocus = false;

    // Icons
    readonly Folder = Folder;
    readonly FolderOpen = FolderOpen;
    readonly FileText = FileText;
    readonly Star = Star;
    readonly BookOpen = BookOpen;
    readonly MoreVertical = MoreVertical;
    readonly GripVertical = GripVertical;

    ngAfterViewChecked(): void {
        if (this.needsFocus && this.editInput) {
            this.editInput.nativeElement.focus();
            this.editInput.nativeElement.select();
            this.needsFocus = false;
        }
    }

    onToggle(event: Event): void {
        event.stopPropagation();
        if (this.node.type === 'folder') {
            this.toggle.emit(this.node.id);
        }
    }

    onNodeClick(): void {
        if (!this.isEditing) {
            this.select.emit(this.node);
        }
    }

    onMenuClick(event: MouseEvent): void {
        event.stopPropagation();
        this.menuClick.emit({ node: this.node, event });
    }

    startEditing(event: Event): void {
        event.stopPropagation();
        this.editValue = this.node.name || '';
        this.startRename.emit(this.node);
        this.needsFocus = true;
    }

    finishEditing(): void {
        const trimmed = this.editValue.trim();
        if (trimmed && trimmed !== this.node.name) {
            this.rename.emit({ node: this.node, newName: trimmed });
        }
        // Parent will clear isEditing
    }

    cancelEditing(): void {
        this.rename.emit({ node: this.node, newName: this.node.name || '' }); // No change
    }

    onDragStart(event: MouseEvent): void {
        this.dragState.emit(this.node.id);
        console.log(`[TreeNode] Drag start for ${this.node.id}`);
    }

    onNoteDragStart(event: DragEvent): void {
        if (!event.dataTransfer || this.isReorderMode || this.node.type !== 'note') return;

        event.dataTransfer.setData('application/x-shuga-note-id', this.node.id);
        event.dataTransfer.setData('text/plain', this.node.name);
        event.dataTransfer.effectAllowed = 'copyLink';
    }
}





