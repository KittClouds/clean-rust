export const CANVAS_NOTE_TRANSACTION_KIND = 'canvas_note_replace_v1' as const;
export const CANVAS_NOTE_RECEIPT_KIND = 'canvas_note_transaction_receipt_v1' as const;

export type CanvasTransactionStatus =
    | 'staged'
    | 'committed'
    | 'already_committed'
    | 'rejected'
    | 'conflict'
    | 'rolled_back'
    | 'failed';

export interface CanvasStagedNoteTransaction {
    kind: typeof CANVAS_NOTE_TRANSACTION_KIND;
    transactionId: string;
    runId: string;
    noteUri: string;
    noteId: string;
    noteTitle: string;
    baseStoreRevision: number;
    baseEditorRevision: number;
    stagedEditorRevision: number;
    from: number;
    to: number;
    beforeText: string;
    replacement: string;
    baseContent: object;
    baseMarkdown: string;
    stagedContent: object;
    stagedMarkdown: string;
    diffPreview: string;
    stagedAt: number;
    stageMs: number;
}

export interface CanvasTransactionTimings {
    stageMs: number;
    commitMs: number;
    indexInvalidationMs: number;
    editorRefreshMs: number;
    totalMs: number;
}

export interface CanvasTransactionReceipt {
    kind: typeof CANVAS_NOTE_RECEIPT_KIND;
    transactionId: string;
    runId: string;
    noteUri: string;
    noteId: string;
    status: CanvasTransactionStatus;
    beforeRevision: number;
    afterRevision?: number;
    checkpointRevision: number;
    from: number;
    to: number;
    beforeText: string;
    replacement: string;
    error?: string;
    timings: CanvasTransactionTimings;
    completedAt: number;
}

export function createCanvasNoteUri(narrativeId: string | undefined, noteId: string): string {
    const narrative = encodeURIComponent(narrativeId?.trim() || '__global__');
    return `note://${narrative}/${encodeURIComponent(noteId)}`;
}

export function formatCanvasReplacementDiff(input: {
    noteUri: string;
    baseRevision: number;
    from: number;
    to: number;
    beforeText: string;
    replacement: string;
}): string {
    const removed = prefixDiffLines(input.beforeText, '-');
    const added = prefixDiffLines(input.replacement, '+');
    return [
        `--- ${input.noteUri}@${input.baseRevision}`,
        `+++ ${input.noteUri}@staged`,
        `@@ selection ${input.from}:${input.to} @@`,
        removed || '-',
        added || '+',
    ].join('\n');
}

export function parseCanvasStagedTransaction(value: unknown): CanvasStagedNoteTransaction | null {
    const record = asRecord(value);
    if (!record || record['kind'] !== CANVAS_NOTE_TRANSACTION_KIND) return null;
    if (!isNonEmptyString(record['transactionId']) || !isNonEmptyString(record['runId'])) return null;
    if (!isNonEmptyString(record['noteUri']) || !isNonEmptyString(record['noteId'])) return null;
    if (!isFiniteNumber(record['baseStoreRevision']) || !isFiniteNumber(record['baseEditorRevision'])) return null;
    if (!isFiniteNumber(record['from']) || !isFiniteNumber(record['to'])) return null;
    if (!asRecord(record['baseContent']) || !asRecord(record['stagedContent'])) return null;
    return record as unknown as CanvasStagedNoteTransaction;
}

export function emptyCanvasTimings(stageMs = 0): CanvasTransactionTimings {
    return {
        stageMs,
        commitMs: 0,
        indexInvalidationMs: 0,
        editorRefreshMs: 0,
        totalMs: 0,
    };
}

export function contentMatchesTransaction(
    content: string,
    markdown: string,
    transaction: CanvasStagedNoteTransaction,
): boolean {
    return content === JSON.stringify(transaction.stagedContent) && markdown === transaction.stagedMarkdown;
}

function prefixDiffLines(value: string, prefix: string): string {
    return value.split('\n').map((line) => `${prefix}${line}`).join('\n');
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}
