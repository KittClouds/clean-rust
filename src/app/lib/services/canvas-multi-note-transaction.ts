import type { CanvasTransactionStatus } from './canvas-note-transaction';

export const CANVAS_MULTI_NOTE_TRANSACTION_KIND = 'canvas_multi_note_transaction_v1' as const;
export const CANVAS_MULTI_NOTE_RECEIPT_KIND = 'canvas_multi_note_receipt_v1' as const;
export const CANVAS_MULTI_NOTE_CHECKPOINT_KIND = 'canvas_multi_note_checkpoint_v1' as const;

export type CanvasNoteOperationKind = 'create' | 'rename' | 'move' | 'patch';

export interface CanvasTextEdit {
    from: number;
    to: number;
    replacement: string;
    expectedText?: string;
}

export type CanvasNoteOperation =
    | {
        kind: 'create';
        noteId?: string;
        title: string;
        folderId: string;
        markdownContent?: string;
    }
    | {
        kind: 'rename';
        noteId: string;
        expectedRevision: number;
        title: string;
    }
    | {
        kind: 'move';
        noteId: string;
        expectedRevision: number;
        folderId: string;
    }
    | {
        kind: 'patch';
        noteId: string;
        expectedRevision: number;
        edits: CanvasTextEdit[];
    };

export interface CanvasStoredNoteSnapshot {
    id: string;
    worldId: string;
    title: string;
    content: object;
    markdownContent: string;
    folderId: string;
    entityKind: string;
    entitySubtype: string;
    isEntity: boolean;
    isPinned: boolean;
    favorite: boolean;
    ownerId: string;
    narrativeId: string;
    order: number;
    createdAt: number;
    updatedAt: number;
    version: number;
}

export interface CanvasStagedNoteMutation {
    noteId: string;
    noteUri: string;
    operationKinds: CanvasNoteOperationKind[];
    expectedRevision: number | null;
    before: CanvasStoredNoteSnapshot | null;
    after: CanvasStoredNoteSnapshot;
}

export interface CanvasMultiNoteTransaction {
    kind: typeof CANVAS_MULTI_NOTE_TRANSACTION_KIND;
    transactionId: string;
    runId: string;
    narrativeId: string;
    mutations: CanvasStagedNoteMutation[];
    diffPreview: string;
    checkpointArtifactKey?: string;
    stagedAt: number;
    stageMs: number;
}

export interface CanvasNoteConflict {
    noteId: string;
    noteUri: string;
    expectedRevision: number | null;
    actualRevision: number | null;
    reason: 'revision_changed' | 'already_exists' | 'missing' | 'scope_changed' | 'partial_state';
}

export interface CanvasCommittedNoteReceipt {
    noteId: string;
    noteUri: string;
    operationKinds: CanvasNoteOperationKind[];
    beforeRevision: number | null;
    afterRevision: number | null;
}

export interface CanvasMultiNoteTimings {
    stageMs: number;
    commitMs: number;
    indexInvalidationMs: number;
    editorRefreshMs: number;
    totalMs: number;
}

export interface CanvasMultiNoteReceipt {
    kind: typeof CANVAS_MULTI_NOTE_RECEIPT_KIND;
    transactionId: string;
    runId: string;
    narrativeId: string;
    status: CanvasTransactionStatus | 'cancelled';
    notes: CanvasCommittedNoteReceipt[];
    conflicts: CanvasNoteConflict[];
    checkpointArtifactKeys: string[];
    error?: string;
    timings: CanvasMultiNoteTimings;
    completedAt: number;
}

export interface CanvasMultiNoteCheckpoint {
    kind: typeof CANVAS_MULTI_NOTE_CHECKPOINT_KIND;
    transactionId: string;
    runId: string;
    status: 'staged' | 'committed' | 'rejected' | 'conflict' | 'cancelled' | 'failed';
    transaction: CanvasMultiNoteTransaction;
    receipt?: CanvasMultiNoteReceipt;
    createdAt: number;
}

export function applyCanvasTextEdits(base: string, edits: readonly CanvasTextEdit[]): string {
    if (!edits.length) throw new Error('patch requires at least one edit');
    const ordered = [...edits].sort((left, right) => left.from - right.from || left.to - right.to);
    let previousTo = -1;
    for (const edit of ordered) {
        if (!Number.isInteger(edit.from) || !Number.isInteger(edit.to) || edit.from < 0 || edit.to < edit.from || edit.to > base.length) {
            throw new Error(`invalid patch range ${edit.from}:${edit.to} for ${base.length} characters`);
        }
        if (edit.from < previousTo) throw new Error(`patch edits overlap at ${edit.from}:${edit.to}`);
        if (edit.expectedText !== undefined && base.slice(edit.from, edit.to) !== edit.expectedText) {
            throw new Error(`patch expected text mismatch at ${edit.from}:${edit.to}`);
        }
        previousTo = edit.to;
    }

    let output = base;
    for (const edit of ordered.reverse()) {
        output = output.slice(0, edit.from) + edit.replacement + output.slice(edit.to);
    }
    return output;
}

export function formatCanvasMultiNoteDiff(mutations: readonly CanvasStagedNoteMutation[]): string {
    return mutations.map((mutation) => {
        const before = mutation.before;
        const metadata = [
            before?.title !== mutation.after.title ? `title: ${before?.title ?? '<new>'} -> ${mutation.after.title}` : '',
            before?.folderId !== mutation.after.folderId ? `folder: ${before?.folderId ?? '<new>'} -> ${mutation.after.folderId}` : '',
        ].filter(Boolean);
        const removed = before ? prefixLines(before.markdownContent, '-') : '';
        const added = prefixLines(mutation.after.markdownContent, '+');
        return [
            `--- ${mutation.noteUri}@${mutation.expectedRevision ?? 'absent'}`,
            `+++ ${mutation.noteUri}@staged`,
            `@@ ${mutation.operationKinds.join(',')} @@`,
            ...metadata,
            removed,
            added,
        ].filter((line) => line.length > 0).join('\n');
    }).join('\n\n');
}

export function parseCanvasMultiNoteTransaction(value: unknown): CanvasMultiNoteTransaction | null {
    const record = asRecord(value);
    if (!record || record['kind'] !== CANVAS_MULTI_NOTE_TRANSACTION_KIND) return null;
    if (!nonEmpty(record['transactionId']) || !nonEmpty(record['runId']) || !nonEmpty(record['narrativeId'])) return null;
    if (!Array.isArray(record['mutations']) || record['mutations'].length === 0) return null;
    for (const mutation of record['mutations']) {
        const item = asRecord(mutation);
        if (!item || !nonEmpty(item['noteId']) || !nonEmpty(item['noteUri'])) return null;
        if (!Array.isArray(item['operationKinds']) || item['operationKinds'].length === 0) return null;
        if (!asRecord(item['after'])) return null;
        if (item['before'] !== null && !asRecord(item['before'])) return null;
        if (item['expectedRevision'] !== null && !finite(item['expectedRevision'])) return null;
    }
    if (!nonEmpty(record['diffPreview']) || !finite(record['stagedAt']) || !finite(record['stageMs'])) return null;
    return record as unknown as CanvasMultiNoteTransaction;
}

export function canvasNoteUri(narrativeId: string, noteId: string): string {
    return `note://${encodeURIComponent(narrativeId)}/${encodeURIComponent(noteId)}`;
}

export function emptyCanvasMultiNoteTimings(stageMs = 0): CanvasMultiNoteTimings {
    return { stageMs, commitMs: 0, indexInvalidationMs: 0, editorRefreshMs: 0, totalMs: 0 };
}

function prefixLines(value: string, prefix: string): string {
    return value.split('\n').map((line) => `${prefix}${line}`).join('\n');
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function nonEmpty(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0;
}

function finite(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}
