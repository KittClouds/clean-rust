import { Injectable, inject } from '@angular/core';
import {
    commitMultiNoteTransaction as commitStoredMultiNoteTransaction,
    type Note,
} from '../operations';
import { NoteEditorStore } from '../store/note-editor.store';
import { PhoenixStoreService, type StoreNote } from '../../services/phoenix-store.service';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import { PhoenixChatService } from './phoenix-chat.service';
import {
    CANVAS_MULTI_NOTE_CHECKPOINT_KIND,
    CANVAS_MULTI_NOTE_RECEIPT_KIND,
    CANVAS_MULTI_NOTE_TRANSACTION_KIND,
    applyCanvasTextEdits,
    canvasNoteUri,
    emptyCanvasMultiNoteTimings,
    formatCanvasMultiNoteDiff,
    type CanvasMultiNoteCheckpoint,
    type CanvasMultiNoteReceipt,
    type CanvasMultiNoteTransaction,
    type CanvasNoteConflict,
    type CanvasNoteOperation,
    type CanvasNoteOperationKind,
    type CanvasStagedNoteMutation,
    type CanvasStoredNoteSnapshot,
} from './canvas-multi-note-transaction';

const MAX_OPERATIONS = 64;
const MAX_TRANSACTION_BYTES = 6 * 1024 * 1024;

export interface CanvasMultiNoteStageResult {
    ok: boolean;
    transaction?: CanvasMultiNoteTransaction;
    error?: string;
}

export interface CanvasMultiNoteCommitResult {
    ok: boolean;
    receipt: CanvasMultiNoteReceipt;
    error?: string;
}

@Injectable({ providedIn: 'root' })
export class CanvasMultiNoteTransactionService {
    private readonly store = inject(PhoenixStoreService);
    private readonly workspace = inject(EditorAgentWorkspaceService);
    private readonly chat = inject(PhoenixChatService);
    private readonly noteEditorStore = inject(NoteEditorStore);

    async stage(runId: string, operations: readonly CanvasNoteOperation[]): Promise<CanvasMultiNoteStageResult> {
        const startedAt = performance.now();
        try {
            if (!runId.trim()) throw new Error('Multi-note transaction requires a durable run id.');
            if (!operations.length || operations.length > MAX_OPERATIONS) {
                throw new Error(`Multi-note transaction requires 1-${MAX_OPERATIONS} operations.`);
            }
            const active = this.noteEditorStore.currentNote();
            const narrativeId = String(active?.narrativeId || '').trim();
            if (!active || !narrativeId) throw new Error('Multi-note transaction requires an active narrative scope.');

            const headers = await this.store.listNoteHeaders();
            const orderByFolder = new Map<string, number>();
            for (const header of headers) {
                orderByFolder.set(header.folderId, Math.max(orderByFolder.get(header.folderId) || -1, header.order));
            }
            const states = new Map<string, MutableMutation>();
            for (const operation of operations) {
                await this.applyOperation(operation, states, narrativeId, active, orderByFolder);
            }
            const mutations = [...states.values()].map((state) => this.toMutation(state, narrativeId));
            const transaction: CanvasMultiNoteTransaction = {
                kind: CANVAS_MULTI_NOTE_TRANSACTION_KIND,
                transactionId: this.id('canvas-multi'),
                runId,
                narrativeId,
                mutations,
                diffPreview: formatCanvasMultiNoteDiff(mutations),
                stagedAt: Date.now(),
                stageMs: performance.now() - startedAt,
            };
            if (new TextEncoder().encode(JSON.stringify(transaction)).byteLength > MAX_TRANSACTION_BYTES) {
                throw new Error(`Multi-note transaction exceeds ${MAX_TRANSACTION_BYTES} bytes.`);
            }
            const checkpoint = await this.persistCheckpoint(transaction, 'staged');
            if (!checkpoint) throw new Error('Failed to persist the staged multi-note checkpoint.');
            transaction.checkpointArtifactKey = checkpoint;
            return { ok: true, transaction };
        } catch (error) {
            return { ok: false, error: message(error) };
        }
    }

    async commit(
        transaction: CanvasMultiNoteTransaction,
        signal?: AbortSignal,
    ): Promise<CanvasMultiNoteCommitResult> {
        const startedAt = performance.now();
        if (signal?.aborted) return await this.cancelled(transaction, startedAt);
        try {
            const result = await commitStoredMultiNoteTransaction({
                transactionId: transaction.transactionId,
                mutations: transaction.mutations.map((mutation) => ({
                    noteId: mutation.noteId,
                    expectedRevision: mutation.expectedRevision,
                    after: snapshotToNote(mutation.after),
                })),
                signal,
            });
            const conflicts: CanvasNoteConflict[] = result.conflicts.map((conflict) => ({
                ...conflict,
                noteUri: canvasNoteUri(transaction.narrativeId, conflict.noteId),
            }));
            if (result.status === 'conflict') {
                const receipt = this.receipt(transaction, 'conflict', startedAt, conflicts);
                receipt.timings.commitMs = result.commitMs;
                receipt.timings.indexInvalidationMs = result.indexInvalidationMs;
                receipt.error = `${conflicts.length} note conflict${conflicts.length === 1 ? '' : 's'} blocked the atomic commit.`;
                await this.attachCheckpoint(transaction, receipt, 'conflict');
                return { ok: false, receipt, error: receipt.error };
            }

            const committed = new Map(result.notes.map((note) => [note.id, note]));
            let editorRefreshMs = 0;
            const projectionWarnings: string[] = [];
            for (const mutation of transaction.mutations) {
                if (this.workspace.getDocumentRevision(mutation.noteId) === null) continue;
                const note = committed.get(mutation.noteId);
                if (!note) continue;
                const refreshStarted = performance.now();
                const projection = this.workspace.applyDocumentProjection(
                    mutation.noteId,
                    noteContentProjection(note, this.workspace),
                );
                editorRefreshMs += performance.now() - refreshStarted;
                if (!projection.ok) projectionWarnings.push(`${mutation.noteId}: ${projection.error || 'projection refresh failed'}`);
            }
            const receipt = this.receipt(transaction, result.status, startedAt, []);
            receipt.notes = transaction.mutations.map((mutation) => ({
                noteId: mutation.noteId,
                noteUri: mutation.noteUri,
                operationKinds: mutation.operationKinds,
                beforeRevision: mutation.expectedRevision,
                afterRevision: committed.get(mutation.noteId)?.version ?? committed.get(mutation.noteId)?.updatedAt ?? null,
            }));
            receipt.timings = {
                stageMs: transaction.stageMs,
                commitMs: result.commitMs,
                indexInvalidationMs: result.indexInvalidationMs,
                editorRefreshMs,
                totalMs: performance.now() - startedAt,
            };
            if (projectionWarnings.length) receipt.error = projectionWarnings.join('; ');
            await this.attachCheckpoint(transaction, receipt, 'committed');
            return { ok: true, receipt };
        } catch (error) {
            if (signal?.aborted || isAbort(error)) return await this.cancelled(transaction, startedAt);
            const receipt = this.receipt(transaction, 'failed', startedAt, []);
            receipt.error = message(error);
            await this.attachCheckpoint(transaction, receipt, 'failed');
            return { ok: false, receipt, error: receipt.error };
        }
    }

    async reject(transaction: CanvasMultiNoteTransaction): Promise<CanvasMultiNoteCommitResult> {
        const receipt = this.receipt(transaction, 'rejected', performance.now(), []);
        await this.attachCheckpoint(transaction, receipt, 'rejected');
        return { ok: true, receipt };
    }

    private async applyOperation(
        operation: CanvasNoteOperation,
        states: Map<string, MutableMutation>,
        narrativeId: string,
        active: any,
        orderByFolder: Map<string, number>,
    ): Promise<void> {
        const noteId = operation.noteId?.trim() || this.id('note');
        let state = states.get(noteId);
        if (operation.kind === 'create') {
            if (state || await this.store.getNote(noteId)) throw new Error(`create conflict: note already exists: ${noteId}`);
            const folderId = stringField(operation.folderId, 'create folderId');
            const markdown = operation.markdownContent || '';
            const now = Date.now();
            const nextOrder = (orderByFolder.get(folderId) || -1) + 1;
            orderByFolder.set(folderId, nextOrder);
            state = {
                before: null,
                after: {
                    id: noteId,
                    worldId: String(active.worldId || ''),
                    title: required(operation.title, 'create title'),
                    content: this.workspace.parseMarkdownProjection(markdown),
                    markdownContent: markdown,
                    folderId,
                    entityKind: '', entitySubtype: '', isEntity: false, isPinned: false, favorite: false,
                    ownerId: String(active.ownerId || ''), narrativeId, order: nextOrder,
                    createdAt: now, updatedAt: now, version: now,
                },
                expectedRevision: null,
                operationKinds: [],
            };
            states.set(noteId, state);
        } else {
            state ||= await this.loadExisting(noteId, narrativeId, operation.expectedRevision);
            if (!states.has(noteId)) states.set(noteId, state);
            if (state.expectedRevision !== operation.expectedRevision) {
                throw new Error(`inconsistent expected revision for ${noteId}`);
            }
        }

        if (operation.kind === 'rename') state.after.title = required(operation.title, 'rename title');
        if (operation.kind === 'move') state.after.folderId = stringField(operation.folderId, 'move folderId');
        if (operation.kind === 'patch') {
            state.after.markdownContent = applyCanvasTextEdits(state.after.markdownContent, operation.edits);
            state.after.content = this.workspace.parseMarkdownProjection(state.after.markdownContent);
        }
        pushUnique(state.operationKinds, operation.kind);
    }

    private async loadExisting(noteId: string, narrativeId: string, expectedRevision: number): Promise<MutableMutation> {
        const note = await this.store.getNote(noteId);
        if (!note) throw new Error(`note not found: ${noteId}`);
        if (note.narrativeId !== narrativeId) throw new Error(`note is outside active narrative: ${noteId}`);
        const actualRevision = note.version ?? note.updatedAt;
        if (actualRevision !== expectedRevision) {
            throw new Error(`staging revision conflict for ${noteId}: expected ${expectedRevision}, got ${actualRevision}`);
        }
        const snapshot = storeToSnapshot(note, this.workspace);
        return {
            before: structuredClone(snapshot),
            after: structuredClone(snapshot),
            expectedRevision,
            operationKinds: [],
        };
    }

    private toMutation(state: MutableMutation, narrativeId: string): CanvasStagedNoteMutation {
        return {
            noteId: state.after.id,
            noteUri: canvasNoteUri(narrativeId, state.after.id),
            operationKinds: state.operationKinds,
            expectedRevision: state.expectedRevision,
            before: state.before,
            after: state.after,
        };
    }

    private async cancelled(
        transaction: CanvasMultiNoteTransaction,
        startedAt: number,
    ): Promise<CanvasMultiNoteCommitResult> {
        const receipt = this.receipt(transaction, 'cancelled', startedAt, []);
        receipt.error = 'Transaction cancelled before the atomic commit boundary.';
        await this.attachCheckpoint(transaction, receipt, 'cancelled');
        return { ok: false, receipt, error: receipt.error };
    }

    private receipt(
        transaction: CanvasMultiNoteTransaction,
        status: CanvasMultiNoteReceipt['status'],
        startedAt: number,
        conflicts: CanvasNoteConflict[],
    ): CanvasMultiNoteReceipt {
        const timings = emptyCanvasMultiNoteTimings(transaction.stageMs);
        timings.totalMs = performance.now() - startedAt;
        return {
            kind: CANVAS_MULTI_NOTE_RECEIPT_KIND,
            transactionId: transaction.transactionId,
            runId: transaction.runId,
            narrativeId: transaction.narrativeId,
            status,
            notes: transaction.mutations.map((mutation) => ({
                noteId: mutation.noteId,
                noteUri: mutation.noteUri,
                operationKinds: mutation.operationKinds,
                beforeRevision: mutation.expectedRevision,
                afterRevision: null,
            })),
            conflicts,
            checkpointArtifactKeys: transaction.checkpointArtifactKey ? [transaction.checkpointArtifactKey] : [],
            timings,
            completedAt: Date.now(),
        };
    }

    private async attachCheckpoint(
        transaction: CanvasMultiNoteTransaction,
        receipt: CanvasMultiNoteReceipt,
        status: CanvasMultiNoteCheckpoint['status'],
    ): Promise<void> {
        const key = await this.persistCheckpoint(transaction, status, receipt);
        if (key) receipt.checkpointArtifactKeys.push(key);
    }

    private async persistCheckpoint(
        transaction: CanvasMultiNoteTransaction,
        status: CanvasMultiNoteCheckpoint['status'],
        receipt?: CanvasMultiNoteReceipt,
    ): Promise<string | null> {
        const checkpoint: CanvasMultiNoteCheckpoint = {
            kind: CANVAS_MULTI_NOTE_CHECKPOINT_KIND,
            transactionId: transaction.transactionId,
            runId: transaction.runId,
            status,
            transaction,
            receipt,
            createdAt: Date.now(),
        };
        const artifact = await this.chat.putPlannerArtifact(
            transaction.runId,
            CANVAS_MULTI_NOTE_CHECKPOINT_KIND,
            checkpoint,
            true,
            `canvas-checkpoint:${transaction.transactionId}:${status}:${checkpoint.createdAt}`,
        );
        return artifact?.key || null;
    }

    private id(prefix: string): string {
        return globalThis.crypto?.randomUUID?.() || `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    }
}

interface MutableMutation {
    before: CanvasStoredNoteSnapshot | null;
    after: CanvasStoredNoteSnapshot;
    expectedRevision: number | null;
    operationKinds: CanvasNoteOperationKind[];
}

function storeToSnapshot(note: StoreNote, workspace: EditorAgentWorkspaceService): CanvasStoredNoteSnapshot {
    let content: object;
    try {
        const parsed = JSON.parse(note.content);
        content = parsed && typeof parsed === 'object' ? parsed : workspace.parseMarkdownProjection(note.markdownContent);
    } catch {
        content = workspace.parseMarkdownProjection(note.markdownContent);
    }
    return { ...note, content, version: note.version ?? note.updatedAt };
}

function snapshotToNote(snapshot: CanvasStoredNoteSnapshot): Note {
    return { ...snapshot, content: snapshot.content, hasBody: true };
}

function noteContentProjection(note: Note, workspace: EditorAgentWorkspaceService): object {
    if (note.content && typeof note.content === 'object') return note.content as object;
    try {
        const parsed = JSON.parse(String(note.content || ''));
        if (parsed && typeof parsed === 'object') return parsed;
    } catch {}
    return workspace.parseMarkdownProjection(note.markdownContent || '');
}

function required(value: unknown, field: string): string {
    const result = stringField(value, field).trim();
    if (!result) throw new Error(`${field} is required`);
    return result;
}

function stringField(value: unknown, field: string): string {
    if (typeof value !== 'string') throw new Error(`${field} must be a string`);
    return value;
}

function pushUnique<T>(values: T[], value: T): void {
    if (!values.includes(value)) values.push(value);
}

function message(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}

function isAbort(error: unknown): boolean {
    return error instanceof DOMException && error.name === 'AbortError';
}
