import { Injectable, inject } from '@angular/core';
import { commitNoteTransaction as commitStoredNoteTransaction } from '../operations';
import {
    CANVAS_NOTE_RECEIPT_KIND,
    emptyCanvasTimings,
    type CanvasStagedNoteTransaction,
    type CanvasTransactionReceipt,
} from './canvas-note-transaction';
import {
    EditorAgentWorkspaceService,
    type WorkspaceEditResult,
} from './editor-agent-workspace.service';

export interface CanvasTransactionResult extends WorkspaceEditResult {
    receipt: CanvasTransactionReceipt;
}

@Injectable({ providedIn: 'root' })
export class CanvasNoteTransactionService {
    private readonly workspace = inject(EditorAgentWorkspaceService);

    commit(transaction: CanvasStagedNoteTransaction): Promise<CanvasTransactionResult> {
        return this.apply(transaction, 'commit', transaction.baseStoreRevision);
    }

    rollback(
        transaction: CanvasStagedNoteTransaction,
        committedRevision: number,
    ): Promise<CanvasTransactionResult> {
        return this.apply(transaction, 'rollback', committedRevision);
    }

    reject(transaction: CanvasStagedNoteTransaction): CanvasTransactionResult {
        return {
            ok: true,
            noteId: transaction.noteId,
            beforeRevision: transaction.baseStoreRevision,
            afterRevision: transaction.baseStoreRevision,
            receipt: this.receipt(transaction, 'rejected', transaction.baseStoreRevision),
        };
    }

    private async apply(
        transaction: CanvasStagedNoteTransaction,
        action: 'commit' | 'rollback',
        expectedStoreRevision: number,
    ): Promise<CanvasTransactionResult> {
        const startedAt = performance.now();
        const targetContent = action === 'commit' ? transaction.stagedContent : transaction.baseContent;
        const targetMarkdown = action === 'commit' ? transaction.stagedMarkdown : transaction.baseMarkdown;
        const allowedEditorRevisions = action === 'commit'
            ? [transaction.baseEditorRevision, transaction.stagedEditorRevision]
            : [transaction.stagedEditorRevision];
        const currentEditorRevision = this.workspace.getDocumentRevision(transaction.noteId);

        if (currentEditorRevision !== null && !allowedEditorRevisions.includes(currentEditorRevision)) {
            return this.failed(
                transaction,
                'conflict',
                `editor revision changed: expected ${allowedEditorRevisions.join(' or ')}, got ${currentEditorRevision}`,
                startedAt,
            );
        }

        try {
            const committed = await commitStoredNoteTransaction({
                transactionId: transaction.transactionId,
                noteId: transaction.noteId,
                expectedRevision: expectedStoreRevision,
                content: targetContent,
                markdownContent: targetMarkdown,
            });
            if (committed.status === 'conflict') {
                return this.failed(
                    transaction,
                    'conflict',
                    `store revision changed: expected ${expectedStoreRevision}, got ${committed.actualRevision}`,
                    startedAt,
                    committed.actualRevision,
                );
            }

            let editorRefreshMs = 0;
            let projectionWarning: string | undefined;
            if (currentEditorRevision !== null) {
                const refreshStarted = performance.now();
                const projection = this.workspace.applyDocumentProjection(transaction.noteId, targetContent);
                editorRefreshMs = performance.now() - refreshStarted;
                if (!projection.ok) {
                    projectionWarning = projection.error || 'editor projection refresh failed after commit';
                }
            }

            const status = action === 'rollback' ? 'rolled_back' : committed.status;
            const receipt = this.receipt(transaction, status, expectedStoreRevision, committed.actualRevision);
            receipt.error = projectionWarning;
            receipt.timings = {
                stageMs: transaction.stageMs,
                commitMs: committed.commitMs,
                indexInvalidationMs: committed.indexInvalidationMs,
                editorRefreshMs,
                totalMs: performance.now() - startedAt,
            };
            return {
                ok: true,
                noteId: transaction.noteId,
                beforeRevision: expectedStoreRevision,
                afterRevision: committed.actualRevision,
                receipt,
            };
        } catch (error) {
            return this.failed(
                transaction,
                'failed',
                error instanceof Error ? error.message : String(error),
                startedAt,
            );
        }
    }

    private failed(
        transaction: CanvasStagedNoteTransaction,
        status: 'conflict' | 'failed',
        error: string,
        startedAt: number,
        actualRevision?: number,
    ): CanvasTransactionResult {
        const receipt = this.receipt(
            transaction,
            status,
            transaction.baseStoreRevision,
            actualRevision,
            error,
        );
        receipt.timings.totalMs = performance.now() - startedAt;
        return {
            ok: false,
            noteId: transaction.noteId,
            beforeRevision: actualRevision ?? transaction.baseStoreRevision,
            error,
            receipt,
        };
    }

    private receipt(
        transaction: CanvasStagedNoteTransaction,
        status: CanvasTransactionReceipt['status'],
        beforeRevision: number,
        afterRevision?: number,
        error?: string,
    ): CanvasTransactionReceipt {
        return {
            kind: CANVAS_NOTE_RECEIPT_KIND,
            transactionId: transaction.transactionId,
            runId: transaction.runId,
            noteUri: transaction.noteUri,
            noteId: transaction.noteId,
            status,
            beforeRevision,
            afterRevision,
            checkpointRevision: transaction.baseStoreRevision,
            from: transaction.from,
            to: transaction.to,
            beforeText: transaction.beforeText,
            replacement: transaction.replacement,
            error,
            timings: emptyCanvasTimings(transaction.stageMs),
            completedAt: Date.now(),
        };
    }
}
