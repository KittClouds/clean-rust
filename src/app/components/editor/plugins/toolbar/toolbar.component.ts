import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Ctx } from '@milkdown/kit/ctx';
import { commandsCtx, editorViewCtx } from '@milkdown/kit/core';
import { toggleStrongCommand, toggleEmphasisCommand, toggleInlineCodeCommand, linkSchema, strongSchema, emphasisSchema, inlineCodeSchema } from '@milkdown/kit/preset/commonmark';
import { toggleStrikethroughCommand, strikethroughSchema } from '@milkdown/kit/preset/gfm';
import { toggleLinkCommand } from '@milkdown/kit/component/link-tooltip';
import { EditorState } from '@milkdown/kit/prose/state';
import { MarkType } from '@milkdown/kit/prose/model';
import {
    LucideAngularModule,
    Bold, Italic, Underline, Strikethrough, Code, Link2,
    AlignLeft, AlignCenter, AlignRight, AlignJustify,
    Sparkles, Type, Highlighter, ALargeSmall,
    Indent, Outdent, Tag, User, MapPin, Users, Shield, Calendar, Lightbulb, Plus,
    Megaphone,
} from 'lucide-angular';

import { ToolbarDropdownComponent, DropdownItem } from './toolbar-dropdown.component';
import { ColorPickerComponent } from './color-picker.component';

// Custom Plugins
import {
    setTextColorCommand, setUnderlineCommand, setFontFamilyCommand, setFontSizeCommand,
    underlineSchema
} from '../marks';
import { setTextAlignCommand, indentCommand, outdentCommand } from '../nodes';

// Registry for entity creation
import { smartGraphRegistry } from '../../../../lib/registry';
import { recordManualEntityTag } from '../../../../lib/entity-learning/entity-feedback';
import { ChatContextClipStore } from '../../../../lib/store/chat-context-clip.store';
import { FONT_FAMILIES, FONT_SIZES } from '../../../../lib/constants/fonts';
import type { EntityKind } from '../../../../lib/Scanner/types';
import { RightSidebarService } from '../../../../lib/services/right-sidebar.service';
import { AiSidebarModeService } from '../../../../lib/services/ai-sidebar-mode.service';
import { CanvasAgentRunService } from '../../../../lib/services/canvas-agent-run.service';
import { TtsService } from '../../../../services/tts.service';

@Component({
    selector: 'app-editor-toolbar',
    standalone: true,
    imports: [CommonModule, LucideAngularModule, ToolbarDropdownComponent, ColorPickerComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="flex items-center gap-1 p-1 bg-toolbar border border-toolbar-border rounded-lg shadow-xl text-toolbar-foreground animate-in fade-in zoom-in-95 duration-100">
            
            <!-- AI Group -->
            <app-toolbar-dropdown [items]="aiItems" (select)="onAIAction($event)">
                <div trigger class="flex items-center gap-1 px-1">
                    <lucide-icon [img]="SparklesIcon" class="w-4 h-4 text-teal-500"></lucide-icon>
                </div>
            </app-toolbar-dropdown>
            <button
                type="button"
                class="btn-icon text-teal-500"
                title="Read Selection"
                (mousedown)="$event.preventDefault()"
                (click)="readSelection()"
            >
                <lucide-icon [img]="MegaphoneIcon" class="w-4 h-4"></lucide-icon>
            </button>

            <div class="w-px h-5 bg-toolbar-border mx-1"></div>

            <!-- Formatting Group -->
            <button type="button" [class.bg-teal-50]="isActive(strongSchema)" [class.text-teal-900]="isActive(strongSchema)" class="btn-icon" (click)="exec(toggleStrongCommand)" title="Bold">
                <lucide-icon [img]="BoldIcon" class="w-4 h-4"></lucide-icon>
            </button>
            <button type="button" [class.bg-teal-50]="isActive(emphasisSchema)" [class.text-teal-900]="isActive(emphasisSchema)" class="btn-icon" (click)="exec(toggleEmphasisCommand)" title="Italic">
                <lucide-icon [img]="ItalicIcon" class="w-4 h-4"></lucide-icon>
            </button>
            <button type="button" [class.bg-teal-50]="isActive(underlineSchema)" [class.text-teal-900]="isActive(underlineSchema)" class="btn-icon" (click)="exec(setUnderlineCommand)" title="Underline">
                <lucide-icon [img]="UnderlineIcon" class="w-4 h-4"></lucide-icon>
            </button>
            <button type="button" [class.bg-teal-50]="isActive(strikethroughSchema)" [class.text-teal-900]="isActive(strikethroughSchema)" class="btn-icon" (click)="exec(toggleStrikethroughCommand)" title="Strikethrough">
                <lucide-icon [img]="StrikeIcon" class="w-4 h-4"></lucide-icon>
            </button>
            <button type="button" [class.bg-teal-50]="isActive(inlineCodeSchema)" [class.text-teal-900]="isActive(inlineCodeSchema)" class="btn-icon" (click)="exec(toggleInlineCodeCommand)" title="Code">
                <lucide-icon [img]="CodeIcon" class="w-4 h-4"></lucide-icon>
            </button>
            <button type="button" [class.bg-teal-50]="isActive(linkSchema)" [class.text-teal-900]="isActive(linkSchema)" class="btn-icon" (click)="exec(toggleLinkCommand)" title="Link">
                <lucide-icon [img]="LinkIcon" class="w-4 h-4"></lucide-icon>
            </button>

            <div class="w-px h-5 bg-toolbar-border mx-1"></div>

            <!-- Entity Tagging Dropdown -->
            <app-toolbar-dropdown [items]="entityItems" (select)="onEntityAction($event)">
                <div trigger class="flex items-center gap-1 px-1" title="Tag as Entity">
                    <lucide-icon [img]="TagIcon" class="w-4 h-4 text-purple-500"></lucide-icon>
                </div>
            </app-toolbar-dropdown>

            <div class="w-px h-5 bg-toolbar-border mx-1"></div>

            <!-- Color Group -->
             <app-toolbar-dropdown>
                <div trigger class="flex items-center gap-1 px-1" title="Text Color">
                     <div class="flex flex-col items-center">
                        <span class="text-xs font-bold leading-none">A</span>
                        <div class="w-3 h-0.5 bg-foreground"></div>
                     </div>
                </div>
                <div content>
                    <app-color-picker (colorSelect)="setTextColor($event)"></app-color-picker>
                </div>
            </app-toolbar-dropdown>

            <button type="button" class="btn-icon" title="Highlight">
                <lucide-icon [img]="HighlighterIcon" class="w-4 h-4"></lucide-icon>
            </button>


            <div class="w-px h-5 bg-toolbar-border mx-1"></div>

            <!-- Alignment -->
             <app-toolbar-dropdown [items]="alignItems" (select)="onAlignAction($event)">
                <div trigger class="px-1">
                    <lucide-icon [img]="AlignLeftIcon" class="w-4 h-4"></lucide-icon>
                </div>
            </app-toolbar-dropdown>

            <!-- Indent/Outdent -->
            <button type="button" class="btn-icon" (click)="exec(outdentCommand)" title="Outdent">
                 <lucide-icon [img]="OutdentIcon" class="w-4 h-4"></lucide-icon>
            </button>
             <button type="button" class="btn-icon" (click)="exec(indentCommand)" title="Indent">
                 <lucide-icon [img]="IndentIcon" class="w-4 h-4"></lucide-icon>
            </button>

             <div class="w-px h-5 bg-toolbar-border mx-1"></div>

            <!-- Font -->
            <app-toolbar-dropdown [items]="fontItems" (select)="onFontAction($event)">
                 <div trigger class="px-1">
                    <lucide-icon [img]="TypeIcon" class="w-4 h-4"></lucide-icon>
                </div>
            </app-toolbar-dropdown>
             <app-toolbar-dropdown [items]="sizeItems" (select)="onSizeAction($event)">
                 <div trigger class="px-1">
                    <lucide-icon [img]="SizeIcon" class="w-4 h-4"></lucide-icon>
                </div>
            </app-toolbar-dropdown>

        </div>
    `,
    styles: [`
        :host {
            display: block;
            pointer-events: auto;
        }
        .btn-icon {
            @apply p-1.5 rounded hover:bg-teal-50 transition-colors text-slate-500 hover:text-teal-900 flex items-center justify-center;
        }
        /* Make icons bolder */
        :host ::ng-deep svg.lucide {
            stroke-width: 2.25px;
        }
    `]
})
export class EditorToolbarComponent {
    @Input() ctx!: Ctx;
    @Input() editorState?: EditorState;
    @Input() noteId?: string; // Current note ID for entity registration
    @Output() hide = new EventEmitter<void>();

    // Icons
    readonly SparklesIcon = Sparkles;
    readonly BoldIcon = Bold;
    readonly ItalicIcon = Italic;
    readonly UnderlineIcon = Underline;
    readonly StrikeIcon = Strikethrough;
    readonly CodeIcon = Code;
    readonly LinkIcon = Link2;
    readonly HighlighterIcon = Highlighter;
    readonly AlignLeftIcon = AlignLeft;
    readonly OutdentIcon = Outdent;
    readonly IndentIcon = Indent;
    readonly TypeIcon = Type;
    readonly SizeIcon = ALargeSmall;
    readonly TagIcon = Tag;
    readonly MegaphoneIcon = Megaphone;

    // Schemas for checking active state
    strongSchema = strongSchema;
    emphasisSchema = emphasisSchema;
    strikethroughSchema = strikethroughSchema;
    inlineCodeSchema = inlineCodeSchema;
    linkSchema = linkSchema;
    underlineSchema = underlineSchema;

    // Commands references
    toggleStrongCommand = toggleStrongCommand;
    toggleEmphasisCommand = toggleEmphasisCommand;
    toggleStrikethroughCommand = toggleStrikethroughCommand;
    toggleInlineCodeCommand = toggleInlineCodeCommand;
    toggleLinkCommand = toggleLinkCommand;
    setUnderlineCommand = setUnderlineCommand;
    outdentCommand = outdentCommand;
    indentCommand = indentCommand;

    // Data for dropdowns
    aiItems: DropdownItem[] = [
        { id: 'improve', label: 'Improve', icon: Sparkles },
        { id: 'shorten', label: 'Shorten' },
        { id: 'fix', label: 'Fix Grammar' },
        { id: 'continue', label: 'Continue' },
        { id: 'add_to_chat', label: 'Add to Chat' },
    ];

    alignItems: DropdownItem[] = [
        { id: 'left', label: 'Left', icon: AlignLeft },
        { id: 'center', label: 'Center', icon: AlignCenter },
        { id: 'right', label: 'Right', icon: AlignRight },
        { id: 'justify', label: 'Justify', icon: AlignJustify },
    ];

    fontItems: DropdownItem[] = FONT_FAMILIES.map(f => ({
        id: f.value,
        label: f.label,
    }));

    sizeItems: DropdownItem[] = FONT_SIZES.map(s => ({
        id: s.value,
        label: s.label,
    }));

    // Entity type dropdown items
    entityItems: DropdownItem[] = [
        { id: 'CHARACTER', label: 'Character', icon: User },
        { id: 'LOCATION', label: 'Location', icon: MapPin },
        { id: 'NPC', label: 'NPC', icon: Users },
        { id: 'FACTION', label: 'Faction', icon: Shield },
        { id: 'EVENT', label: 'Event', icon: Calendar },
        { id: 'CONCEPT', label: 'Concept', icon: Lightbulb },
        { id: 'CUSTOM', label: 'Custom...', icon: Plus },
    ];

    constructor(
        private cdr: ChangeDetectorRef,
        private readonly chatContextClipStore: ChatContextClipStore,
        private readonly rightSidebar: RightSidebarService,
        private readonly aiSidebarMode: AiSidebarModeService,
        private readonly canvasRuns: CanvasAgentRunService,
        private readonly ttsService: TtsService,
    ) { }

    update(state: EditorState) {
        this.editorState = state;
        this.cdr.detectChanges();
    }

    isActive(schema: any): boolean {
        if (!this.ctx || !this.editorState) return false;
        try {
            let markType: MarkType | undefined;
            if (schema && typeof schema.type === 'function') {
                markType = schema.type(this.ctx);
            }

            if (!markType) return false;

            const { selection, doc, storedMarks } = this.editorState;
            const { from, to, empty, $from } = selection;

            if (empty) {
                return !!(storedMarks || $from.marks()).find(m => m.type === markType);
            }
            return doc.rangeHasMark(from, to, markType);
        } catch (e) {
            return false;
        }
    }

    exec(command: any, payload?: any) {
        if (!this.ctx) return;
        try {
            const key = typeof command === 'string' ? command : command.key;
            this.ctx.get(commandsCtx).call(key, payload);
        } catch (e) {
            console.error('Command failed', e);
        }
    }

    async onAIAction(item: DropdownItem) {
        if (!this.ctx || !this.editorState) return;

        try {
            const view = this.ctx.get(editorViewCtx);
            const { state } = view;
            const { selection, doc } = state;
            const { from, to, empty } = selection;

            if (empty) {
                console.log('[AI] No text selected');
                return;
            }

            const selectedText = doc.textBetween(from, to, ' ');
            if (!selectedText.trim()) return;

            if (item.id === 'add_to_chat') {
                const clip = this.chatContextClipStore.addSelectionClip({
                    noteId: this.noteId ?? null,
                    from,
                    to,
                    text: selectedText.trim(),
                });
                this.rightSidebar.open();
                this.rightSidebar.setActivePanel('ai');
                this.aiSidebarMode.switchToCanvas({
                    noteId: this.noteId ?? null,
                    from,
                    to,
                    text: selectedText.trim(),
                    clipId: clip.id,
                });
                console.log(`[AI] Added highlighted text to chat context (${clip.id})`);
                this.hide.emit();
                return;
            }

            const prompts: Record<string, string> = {
                'improve': 'Improve this selected text for clarity, flow, and impact.',
                'shorten': 'Shorten this selected text while preserving its meaning.',
                'fix': 'Fix all grammar, spelling, and punctuation errors in this selected text.',
                'continue': 'Replace this selected text with the original selection followed by a continuation in the same style and tone.',
            };
            const instruction = prompts[item.id] || prompts['improve'];
            this.rightSidebar.open();
            this.rightSidebar.setActivePanel('ai');
            this.aiSidebarMode.switchToCanvas({
                noteId: this.noteId ?? null,
                from,
                to,
                text: selectedText,
            });
            this.hide.emit();
            await this.canvasRuns.startSelectionRun(
                instruction,
                { from, to, empty: false, text: selectedText },
                'toolbar',
            );
        } catch (e) {
            console.error('[AI] Action failed:', e);
        }
    }

    readSelection(): void {
        const selectedText = this.getSelectedText();
        if (!selectedText) {
            console.log('[TTS] No text selected');
            return;
        }

        this.ttsService.speakOnce(selectedText);
        this.hide.emit();
    }

    onAlignAction(item: DropdownItem) {
        this.exec(setTextAlignCommand, item.id);
    }

    onFontAction(item: DropdownItem) {
        const fontDef = FONT_FAMILIES.find(f => f.value === item.id);
        const family = (!fontDef || item.id === 'default') ? null : fontDef.family;
        this.exec(setFontFamilyCommand, family);
    }

    onSizeAction(item: DropdownItem) {
        const sizeDef = FONT_SIZES.find(s => s.value === item.id);
        const size = (!sizeDef || item.id === 'default') ? null : sizeDef.size;
        this.exec(setFontSizeCommand, size);
    }

    setTextColor(color: string | null) {
        this.exec(setTextColorCommand, color);
    }

    private getSelectedText(): string {
        if (!this.ctx) return '';

        try {
            const view = this.ctx.get(editorViewCtx);
            const { selection, doc } = view.state;
            const { from, to, empty } = selection;

            if (empty) return '';

            return doc
                .textBetween(from, to, '\n', '\n')
                .replace(/[ \t\f\v]+/g, ' ')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        } catch (error) {
            console.error('[TTS] Failed to read selected text:', error);
            return '';
        }
    }

    /**
     * Handle entity tagging from dropdown.
     * Applies entity mark to the selected text and registers the entity.
     * NO parsing syntax - just native marks.
     */
    onEntityAction(item: DropdownItem) {
        if (!this.ctx || !this.editorState) return;

        // Handle custom type (prompt user)
        let entityType = item.id;
        if (entityType === 'CUSTOM') {
            const customType = prompt('Enter custom entity type:');
            if (!customType || customType.trim() === '') return;
            entityType = customType.trim().toUpperCase();
        }

        try {
            const view = this.ctx.get(editorViewCtx);
            const { state } = view;
            const { selection, doc, schema } = state;
            const { from, to, empty } = selection;

            if (empty) {
                console.log('[EntityTag] No text selected');
                return;
            }

            // Get the selected text
            const selectedText = doc.textBetween(from, to, ' ');
            if (!selectedText.trim()) return;


            // Get the entity mark type from schema
            const entityMarkType = schema.marks['entity'];
            if (!entityMarkType) {
                console.error('[EntityTag] Entity mark not found in schema');
                return;
            }

            const noteIdToUse = this.noteId || 'unknown-note';
            const registration = smartGraphRegistry.registerEntity(
                selectedText.trim(),
                entityType as EntityKind,
                noteIdToUse,
                { source: 'user' }
            );
            const entity = registration.entity;

            // Create the entity mark with canonical registry attributes.
            const entityMark = entityMarkType.create({
                type: 'entity',
                kind: entity.kind,
                label: entity.label,
                id: entity.id,
                mode: 'vivid',
            });

            // Apply the mark to the selected text (don't replace text!)
            const tr = state.tr.addMark(from, to, entityMark);
            view.dispatch(tr);

            recordManualEntityTag({
                entityId: entity.id,
                label: entity.label,
                kind: entity.kind,
                surface: selectedText.trim(),
                noteId: noteIdToUse,
            }).catch(error => {
                console.warn('[EntityTag] Failed to record manual feedback:', error);
            });

            console.log(`[EntityTag] Tagged "${selectedText}" as ${entityType}`);

            // Hide toolbar after action
            this.hide.emit();
        } catch (e) {
            console.error('[EntityTag] Failed to tag entity:', e);
        }
    }
}





