import { DOCUMENT, isPlatformBrowser } from '@angular/common';
import { DestroyRef, Inject, Injectable, PLATFORM_ID, computed, effect, inject, signal } from '@angular/core';
import { editorViewCtx, parserCtx, serializerCtx } from '@milkdown/kit/core';
import { TextSelection } from '@milkdown/kit/prose/state';
import type { EditorView } from '@milkdown/kit/prose/view';
import { EditorService } from '../../services/editor.service';
import { NoteEditorStore } from '../store/note-editor.store';
import {
    CANVAS_NOTE_TRANSACTION_KIND,
    createCanvasNoteUri,
    formatCanvasReplacementDiff,
    type CanvasStagedNoteTransaction,
} from './canvas-note-transaction';

export interface WorkspaceSelectionSnapshot {
    from: number;
    to: number;
    empty: boolean;
    text: string;
}

export interface WorkspaceBlockSnapshot {
    index: number;
    from: number;
    to: number;
    nodeType: string;
    text: string;
}

export interface WorkspaceDocumentSnapshot {
    noteId: string;
    noteTitle: string | null;
    revision: number;
    markdown: string;
    text: string;
    selection: WorkspaceSelectionSnapshot;
    blocks: WorkspaceBlockSnapshot[];
}

export interface WorkspaceEditResult {
    ok: boolean;
    noteId?: string;
    beforeRevision?: number;
    afterRevision?: number;
    error?: string;
}

export interface WorkspaceStreamingEditResult extends WorkspaceEditResult {
    sessionId?: string;
    insertedLength?: number;
    restoredOriginal?: boolean;
    preservedPartial?: boolean;
}

export interface WorkspaceStageResult {
    ok: boolean;
    transaction?: CanvasStagedNoteTransaction;
    error?: string;
}

interface WorkspaceStreamingSession {
    id: string;
    noteId: string;
    originalFrom: number;
    originalTo: number;
    insertionPoint: number;
    insertedLength: number;
    originalText: string;
    beforeRevision: number;
}

@Injectable({ providedIn: 'root' })
export class EditorAgentWorkspaceService {
    private readonly editorService = inject(EditorService);
    private readonly noteEditorStore = inject(NoteEditorStore);
    private readonly destroyRef = inject(DestroyRef);
    private readonly selectionSignal = signal<WorkspaceSelectionSnapshot | null>(null);
    private activeStreamingSession: WorkspaceStreamingSession | null = null;

    readonly liveSelection = computed(() => this.selectionSignal());

    constructor(
        @Inject(PLATFORM_ID) platformId: Object,
        @Inject(DOCUMENT) document: Document
    ) {
        effect(() => {
            const activeNoteId = this.noteEditorStore.activeNoteId();
            if (this.activeStreamingSession && activeNoteId !== this.activeStreamingSession.noteId) {
                this.activeStreamingSession = null;
            }
            this.refreshLiveSelection();
        }, { allowSignalWrites: true });

        if (isPlatformBrowser(platformId)) {
            const refresh = () => this.refreshLiveSelection();
            document.addEventListener('selectionchange', refresh, { passive: true });
            this.destroyRef.onDestroy(() => {
                document.removeEventListener('selectionchange', refresh);
            });
        }
    }

    hasOpenDocument(): boolean {
        return !!this.noteEditorStore.activeNoteId() && !!this.getEditorView();
    }

    getSelection(): WorkspaceSelectionSnapshot | null {
        const view = this.getEditorView();
        if (!view) return null;

        const { selection, doc } = view.state;
        const { from, to, empty } = selection;
        return {
            from,
            to,
            empty,
            text: empty ? '' : doc.textBetween(from, to, ' ', ' '),
        };
    }

    getBlocks(): WorkspaceBlockSnapshot[] {
        const view = this.getEditorView();
        if (!view) return [];

        const blocks: WorkspaceBlockSnapshot[] = [];
        view.state.doc.forEach((node, offset, index) => {
            const from = offset + 1;
            const to = from + node.nodeSize - 1;
            blocks.push({
                index,
                from,
                to,
                nodeType: node.type.name,
                text: node.textBetween(0, node.content.size, ' ', ' '),
            });
        });

        return blocks;
    }

    getSnapshot(): WorkspaceDocumentSnapshot | null {
        const view = this.getEditorView();
        const note = this.noteEditorStore.currentNote();
        if (!view || !note) return null;

        const selection = this.getSelection();
        if (!selection) return null;

        return {
            noteId: note.id,
            noteTitle: note.title ?? null,
            revision: this.computeRevision(view),
            markdown: this.editorService.getCrepe()?.getMarkdown() ?? '',
            text: view.state.doc.textBetween(0, view.state.doc.content.size, '\n\n', ' '),
            selection,
            blocks: this.getBlocks(),
        };
    }

    stageReplaceText(
        runId: string,
        from: number,
        to: number,
        replacement: string,
        expectedEditorRevision?: number,
    ): WorkspaceStageResult {
        const startedAt = performance.now();
        const view = this.getEditorView();
        const note = this.noteEditorStore.currentNote();
        const crepe = this.editorService.getCrepe();
        if (!view || !note || !crepe) {
            return { ok: false, error: 'no open note/editor' };
        }

        const baseEditorRevision = this.computeRevision(view);
        if (expectedEditorRevision !== undefined && expectedEditorRevision !== baseEditorRevision) {
            return {
                ok: false,
                error: `revision mismatch: expected ${expectedEditorRevision}, got ${baseEditorRevision}`,
            };
        }
        const range = this.normalizeRange(view, from, to);
        if (!range) return { ok: false, error: 'invalid range' };

        try {
            const serializer = crepe.editor.ctx.get(serializerCtx);
            const baseDoc = view.state.doc;
            const stagedDoc = view.state.tr.insertText(replacement, range.from, range.to).doc;
            const noteUri = createCanvasNoteUri(note.narrativeId, note.id);
            const beforeText = baseDoc.textBetween(range.from, range.to, '\n', '\n');
            const baseStoreRevision = note.version ?? note.updatedAt;
            const transaction: CanvasStagedNoteTransaction = {
                kind: CANVAS_NOTE_TRANSACTION_KIND,
                transactionId: this.generateId('canvas-txn'),
                runId,
                noteUri,
                noteId: note.id,
                noteTitle: note.title || note.id,
                baseStoreRevision,
                baseEditorRevision,
                stagedEditorRevision: this.hashString(JSON.stringify(stagedDoc.toJSON())),
                from: range.from,
                to: range.to,
                beforeText,
                replacement,
                baseContent: baseDoc.toJSON(),
                baseMarkdown: serializer(baseDoc),
                stagedContent: stagedDoc.toJSON(),
                stagedMarkdown: serializer(stagedDoc),
                diffPreview: formatCanvasReplacementDiff({
                    noteUri,
                    baseRevision: baseStoreRevision,
                    from: range.from,
                    to: range.to,
                    beforeText,
                    replacement,
                }),
                stagedAt: Date.now(),
                stageMs: performance.now() - startedAt,
            };
            return { ok: true, transaction };
        } catch (error) {
            return { ok: false, error: this.toErrorMessage(error) };
        }
    }

    getDocumentRevision(noteId: string): number | null {
        const note = this.noteEditorStore.currentNote();
        const view = this.getEditorView();
        return note?.id === noteId && view ? this.computeRevision(view) : null;
    }

    applyDocumentProjection(noteId: string, content: object): WorkspaceEditResult {
        const note = this.noteEditorStore.currentNote();
        const view = this.getEditorView();
        if (!note || !view || note.id !== noteId) {
            return { ok: false, noteId, error: 'no matching open note/editor' };
        }
        try {
            const beforeRevision = this.computeRevision(view);
            const nextDoc = view.state.schema.nodeFromJSON(content);
            view.dispatch(view.state.tr.replaceWith(0, view.state.doc.content.size, nextDoc.content));
            this.refreshLiveSelection();
            return {
                ok: true,
                noteId,
                beforeRevision,
                afterRevision: this.computeRevision(view),
            };
        } catch (error) {
            return { ok: false, noteId, error: this.toErrorMessage(error) };
        }
    }

    parseMarkdownProjection(markdown: string): object {
        const crepe = this.editorService.getCrepe();
        if (!crepe) throw new Error('Canvas markdown parser is unavailable without an initialized editor.');
        const parser = crepe.editor.ctx.get(parserCtx);
        const content = parser(markdown)?.toJSON?.();
        if (!content || content.type !== 'doc') throw new Error('Canvas markdown parser returned an invalid document.');
        return content;
    }

    async replaceText(
        from: number,
        to: number,
        replacement: string,
        expectedRevision?: number
    ): Promise<WorkspaceEditResult> {
        return this.applyTextEdit(
            expectedRevision,
            (view) => {
                const range = this.normalizeRange(view, from, to);
                if (!range) throw new Error('invalid range');
                const tr = view.state.tr.insertText(replacement, range.from, range.to);
                view.dispatch(tr);
            }
        );
    }

    async insertText(
        pos: number,
        text: string,
        expectedRevision?: number
    ): Promise<WorkspaceEditResult> {
        return this.applyTextEdit(
            expectedRevision,
            (view) => {
                const range = this.normalizeRange(view, pos, pos);
                if (!range) throw new Error('invalid position');
                const tr = view.state.tr.insertText(text, range.from, range.to);
                view.dispatch(tr);
            }
        );
    }

    async deleteText(
        from: number,
        to: number,
        expectedRevision?: number
    ): Promise<WorkspaceEditResult> {
        return this.replaceText(from, to, '', expectedRevision);
    }

    async rewriteBlock(
        blockIndex: number,
        replacement: string,
        expectedRevision?: number
    ): Promise<WorkspaceEditResult> {
        return this.applyTextEdit(
            expectedRevision,
            (view) => {
                let targetFrom = -1;
                let targetTo = -1;

                view.state.doc.forEach((node, offset, index) => {
                    if (index !== blockIndex) return;
                    targetFrom = offset + 1;
                    targetTo = targetFrom + node.nodeSize - 1;
                });

                if (targetFrom < 0 || targetTo < 0) throw new Error('block not found');
                const tr = view.state.tr.insertText(replacement, targetFrom, targetTo);
                view.dispatch(tr);
            }
        );
    }

    async saveCurrentNote(): Promise<WorkspaceEditResult> {
        const note = this.noteEditorStore.currentNote();
        const view = this.getEditorView();
        const crepe = this.editorService.getCrepe();
        if (!note || !view || !crepe) {
            return { ok: false, error: 'no open note/editor' };
        }

        try {
            await this.noteEditorStore.saveContentNow(
                view.state.doc.toJSON(),
                crepe.getMarkdown(),
                note.id
            );
            const rev = this.computeRevision(view);
            return {
                ok: true,
                noteId: note.id,
                beforeRevision: rev,
                afterRevision: rev,
            };
        } catch (err) {
            return { ok: false, noteId: note.id, error: this.toErrorMessage(err) };
        }
    }

    beginStreamReplace(
        from: number,
        to: number,
        expectedRevision?: number
    ): WorkspaceStreamingEditResult {
        return this.beginStreamingSession(from, to, expectedRevision, true);
    }

    beginStreamInsert(
        pos: number,
        expectedRevision?: number
    ): WorkspaceStreamingEditResult {
        return this.beginStreamingSession(pos, pos, expectedRevision, false);
    }

    appendStreamChunk(sessionId: string, chunk: string): WorkspaceStreamingEditResult {
        if (!chunk) {
            return {
                ok: true,
                sessionId,
                noteId: this.activeStreamingSession?.noteId,
                insertedLength: this.activeStreamingSession?.insertedLength ?? 0,
            };
        }

        const session = this.requireStreamingSession(sessionId);
        if (this.isStreamingSessionError(session)) return session;

        const view = this.getEditorView();
        if (!view) {
            return { ok: false, sessionId, error: 'no open note/editor' };
        }

        const insertAt = session.insertionPoint + session.insertedLength;
        const tr = view.state.tr.insertText(chunk, insertAt, insertAt);
        view.dispatch(tr);
        session.insertedLength += chunk.length;
        this.refreshLiveSelection();

        return {
            ok: true,
            sessionId: session.id,
            noteId: session.noteId,
            beforeRevision: session.beforeRevision,
            afterRevision: this.computeRevision(view),
            insertedLength: session.insertedLength,
        };
    }

    async finalizeStreamEdit(sessionId: string): Promise<WorkspaceStreamingEditResult> {
        const session = this.requireStreamingSession(sessionId);
        if (this.isStreamingSessionError(session)) return session;

        const saveResult = await this.saveCurrentNote();
        if (!saveResult.ok) {
            return { ...saveResult, sessionId };
        }

        this.activeStreamingSession = null;
        this.refreshLiveSelection();
        return {
            ...saveResult,
            sessionId,
            insertedLength: session.insertedLength,
            restoredOriginal: false,
            preservedPartial: false,
        };
    }

    cancelStreamEdit(
        sessionId: string,
        options?: { preservePartial?: boolean }
    ): WorkspaceStreamingEditResult {
        const session = this.requireStreamingSession(sessionId);
        if (this.isStreamingSessionError(session)) return session;

        const preservePartial = !!options?.preservePartial || session.insertedLength > 0;
        const view = this.getEditorView();
        if (!view) {
            this.activeStreamingSession = null;
            return {
                ok: false,
                sessionId,
                noteId: session.noteId,
                insertedLength: session.insertedLength,
                preservedPartial: preservePartial,
                error: 'no open note/editor',
            };
        }

        let restoredOriginal = false;
        if (!preservePartial) {
            const restoreTo = session.insertionPoint + session.insertedLength;
            const tr = view.state.tr.insertText(
                session.originalText,
                session.insertionPoint,
                restoreTo
            );
            if (session.originalText.length > 0) {
                tr.setSelection(
                    TextSelection.create(
                        tr.doc,
                        session.insertionPoint,
                        session.insertionPoint + session.originalText.length
                    )
                );
            }
            view.dispatch(tr);
            restoredOriginal = true;
        }

        this.activeStreamingSession = null;
        this.refreshLiveSelection();
        return {
            ok: true,
            sessionId,
            noteId: session.noteId,
            beforeRevision: session.beforeRevision,
            afterRevision: this.computeRevision(view),
            insertedLength: session.insertedLength,
            restoredOriginal,
            preservedPartial: preservePartial,
        };
    }

    highlightRange(
        from: number,
        to: number
    ): WorkspaceEditResult {
        const view = this.getEditorView();
        const note = this.noteEditorStore.currentNote();
        if (!view || !note) {
            return { ok: false, error: 'no open note/editor' };
        }

        const range = this.normalizeRange(view, from, to);
        if (!range) {
            return { ok: false, noteId: note.id, error: 'invalid range' };
        }

        const minPos = 1;
        const maxPos = Math.max(minPos, view.state.doc.content.size - 1);
        const anchor = Math.max(minPos, Math.min(range.from, maxPos));
        const head = Math.max(minPos, Math.min(range.to, maxPos));
        const tr = view.state.tr
            .setSelection(TextSelection.create(view.state.doc, anchor, head))
            .scrollIntoView();
        view.dispatch(tr);
        view.focus();
        this.refreshLiveSelection();
        const revision = this.computeRevision(view);
        return {
            ok: true,
            noteId: note.id,
            beforeRevision: revision,
            afterRevision: revision,
        };
    }

    private async applyTextEdit(
        expectedRevision: number | undefined,
        mutate: (view: EditorView) => void
    ): Promise<WorkspaceEditResult> {
        const note = this.noteEditorStore.currentNote();
        const view = this.getEditorView();
        const crepe = this.editorService.getCrepe();
        if (!note || !view || !crepe) {
            return { ok: false, error: 'no open note/editor' };
        }

        const beforeRevision = this.computeRevision(view);
        if (expectedRevision !== undefined && expectedRevision !== beforeRevision) {
            return {
                ok: false,
                noteId: note.id,
                beforeRevision,
                error: `revision mismatch: expected ${expectedRevision}, got ${beforeRevision}`,
            };
        }

        try {
            mutate(view);
            const afterRevision = this.computeRevision(view);
            await this.noteEditorStore.saveContentNow(
                view.state.doc.toJSON(),
                crepe.getMarkdown(),
                note.id
            );
            return {
                ok: true,
                noteId: note.id,
                beforeRevision,
                afterRevision,
            };
        } catch (err) {
            return {
                ok: false,
                noteId: note.id,
                beforeRevision,
                error: this.toErrorMessage(err),
            };
        }
    }

    private beginStreamingSession(
        from: number,
        to: number,
        expectedRevision: number | undefined,
        removeOriginalText: boolean
    ): WorkspaceStreamingEditResult {
        if (this.activeStreamingSession) {
            return { ok: false, error: 'another streaming edit is already active' };
        }

        const note = this.noteEditorStore.currentNote();
        const view = this.getEditorView();
        if (!note || !view) {
            return { ok: false, error: 'no open note/editor' };
        }

        const beforeRevision = this.computeRevision(view);
        if (expectedRevision !== undefined && expectedRevision !== beforeRevision) {
            return {
                ok: false,
                noteId: note.id,
                beforeRevision,
                error: `revision mismatch: expected ${expectedRevision}, got ${beforeRevision}`,
            };
        }

        const range = this.normalizeRange(view, from, to);
        if (!range) {
            return { ok: false, noteId: note.id, beforeRevision, error: 'invalid range' };
        }

        const originalText = view.state.doc.textBetween(range.from, range.to, '\n', '\n');
        if (removeOriginalText && range.from !== range.to) {
            view.dispatch(view.state.tr.insertText('', range.from, range.to));
        } else if (range.from === range.to) {
            view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, range.from, range.to)));
        }

        view.focus();
        const sessionId = this.generateId('stream-edit');
        this.activeStreamingSession = {
            id: sessionId,
            noteId: note.id,
            originalFrom: range.from,
            originalTo: range.to,
            insertionPoint: range.from,
            insertedLength: 0,
            originalText,
            beforeRevision,
        };
        this.refreshLiveSelection();
        return {
            ok: true,
            sessionId,
            noteId: note.id,
            beforeRevision,
            afterRevision: this.computeRevision(view),
            insertedLength: 0,
            restoredOriginal: false,
            preservedPartial: false,
        };
    }

    private requireStreamingSession(sessionId: string): WorkspaceStreamingSession | WorkspaceStreamingEditResult {
        const session = this.activeStreamingSession;
        if (!session || session.id !== sessionId) {
            return { ok: false, sessionId, error: `unknown streaming session: ${sessionId}` };
        }
        if (this.noteEditorStore.activeNoteId() !== session.noteId) {
            this.activeStreamingSession = null;
            return {
                ok: false,
                sessionId,
                noteId: session.noteId,
                insertedLength: session.insertedLength,
                preservedPartial: session.insertedLength > 0,
                error: 'active note changed during streaming edit',
            };
        }
        return session;
    }

    private isStreamingSessionError(
        value: WorkspaceStreamingSession | WorkspaceStreamingEditResult
    ): value is WorkspaceStreamingEditResult {
        return !('insertionPoint' in value);
    }

    private normalizeRange(
        view: EditorView,
        from: number,
        to: number
    ): { from: number; to: number } | null {
        const max = view.state.doc.content.size;
        if (!Number.isFinite(from) || !Number.isFinite(to)) return null;

        const safeFrom = Math.max(0, Math.min(Math.floor(from), max));
        const safeTo = Math.max(0, Math.min(Math.floor(to), max));
        if (safeFrom > safeTo) return null;

        return { from: safeFrom, to: safeTo };
    }

    private getEditorView(): EditorView | null {
        const crepe = this.editorService.getCrepe();
        if (!crepe) return null;
        try {
            return crepe.editor.ctx.get(editorViewCtx);
        } catch {
            return null;
        }
    }

    private refreshLiveSelection(): void {
        this.selectionSignal.set(this.getSelection());
    }

    private computeRevision(view: EditorView): number {
        return this.hashString(JSON.stringify(view.state.doc.toJSON()));
    }

    private hashString(value: string): number {
        let hash = 2166136261;
        for (let i = 0; i < value.length; i++) {
            hash ^= value.charCodeAt(i);
            hash = Math.imul(hash, 16777619);
        }
        return hash >>> 0;
    }

    private toErrorMessage(err: unknown): string {
        return err instanceof Error ? err.message : String(err);
    }

    private generateId(prefix: string): string {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return `${prefix}-${crypto.randomUUID()}`;
        }
        return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
}

