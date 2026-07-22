// @vitest-environment jsdom
import '@angular/compiler';
import { TestBed, getTestBed } from '@angular/core/testing';
import {
    BrowserDynamicTestingModule,
    platformBrowserDynamicTesting,
} from '@angular/platform-browser-dynamic/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const operations = vi.hoisted(() => ({ commitNoteTransaction: vi.fn() }));
vi.mock('../operations', () => ({ commitNoteTransaction: operations.commitNoteTransaction }));

import { CanvasNoteTransactionService } from './canvas-note-transaction.service';
import { CANVAS_NOTE_TRANSACTION_KIND, type CanvasStagedNoteTransaction } from './canvas-note-transaction';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';

try {
    getTestBed().initTestEnvironment(
        BrowserDynamicTestingModule,
        platformBrowserDynamicTesting(),
    );
} catch {
    // Test environment already initialized for this Vitest worker.
}

describe('CanvasNoteTransactionService', () => {
    const workspace = {
        getDocumentRevision: vi.fn(() => 11),
        applyDocumentProjection: vi.fn(() => ({ ok: true, beforeRevision: 11, afterRevision: 12 })),
    };
    let service: CanvasNoteTransactionService;

    beforeEach(() => {
        vi.clearAllMocks();
        workspace.getDocumentRevision.mockReturnValue(11);
        workspace.applyDocumentProjection.mockReturnValue({ ok: true, beforeRevision: 11, afterRevision: 12 });
        TestBed.configureTestingModule({
            providers: [
                CanvasNoteTransactionService,
                { provide: EditorAgentWorkspaceService, useValue: workspace },
            ],
        });
        service = TestBed.inject(CanvasNoteTransactionService);
    });

    it('commits exact staged content and refreshes the editor only after CAS succeeds', async () => {
        operations.commitNoteTransaction.mockResolvedValue(commitResult('committed', 102));

        const result = await service.commit(transaction());

        expect(operations.commitNoteTransaction).toHaveBeenCalledWith(expect.objectContaining({
            transactionId: 'txn-1',
            noteId: 'note-1',
            expectedRevision: 101,
            content: transaction().stagedContent,
            markdownContent: 'after',
        }));
        expect(workspace.applyDocumentProjection).toHaveBeenCalledWith('note-1', transaction().stagedContent);
        expect(result.ok).toBe(true);
        expect(result.receipt).toEqual(expect.objectContaining({
            status: 'committed',
            beforeRevision: 101,
            afterRevision: 102,
            checkpointRevision: 101,
        }));
    });

    it('fails closed on a store conflict without changing the editor projection', async () => {
        operations.commitNoteTransaction.mockResolvedValue(commitResult('conflict', 202));

        const result = await service.commit(transaction());

        expect(result.ok).toBe(false);
        expect(result.receipt.status).toBe('conflict');
        expect(result.error).toContain('expected 101, got 202');
        expect(workspace.applyDocumentProjection).not.toHaveBeenCalled();
    });

    it('rolls a committed transaction back to its exact checkpoint content', async () => {
        workspace.getDocumentRevision.mockReturnValue(12);
        operations.commitNoteTransaction.mockResolvedValue(commitResult('committed', 103));

        const result = await service.rollback(transaction(), 102);

        expect(operations.commitNoteTransaction).toHaveBeenCalledWith(expect.objectContaining({
            expectedRevision: 102,
            content: transaction().baseContent,
            markdownContent: 'before',
        }));
        expect(workspace.applyDocumentProjection).toHaveBeenCalledWith('note-1', transaction().baseContent);
        expect(result.receipt.status).toBe('rolled_back');
        expect(result.receipt.afterRevision).toBe(103);
    });

    it('commits from the AI page when the editor projection is not mounted', async () => {
        workspace.getDocumentRevision.mockReturnValue(null);
        operations.commitNoteTransaction.mockResolvedValue(commitResult('committed', 102));

        const result = await service.commit(transaction());

        expect(result.ok).toBe(true);
        expect(result.receipt.status).toBe('committed');
        expect(workspace.applyDocumentProjection).not.toHaveBeenCalled();
        expect(result.receipt.timings.editorRefreshMs).toBe(0);
    });

    it('keeps a durable commit successful when the mounted editor refresh reports a warning', async () => {
        operations.commitNoteTransaction.mockResolvedValue(commitResult('committed', 102));
        workspace.applyDocumentProjection.mockReturnValue({
            ok: false,
            beforeRevision: 11,
            error: 'projection unavailable',
        });

        const result = await service.commit(transaction());

        expect(result.ok).toBe(true);
        expect(result.receipt.status).toBe('committed');
        expect(result.receipt.afterRevision).toBe(102);
        expect(result.receipt.error).toBe('projection unavailable');
    });
});

function transaction(): CanvasStagedNoteTransaction {
    return {
        kind: CANVAS_NOTE_TRANSACTION_KIND,
        transactionId: 'txn-1',
        runId: 'run-1',
        noteUri: 'note://story/note-1',
        noteId: 'note-1',
        noteTitle: 'Shortrun B',
        baseStoreRevision: 101,
        baseEditorRevision: 11,
        stagedEditorRevision: 12,
        from: 8,
        to: 19,
        beforeText: 'before',
        replacement: 'after',
        baseContent: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'before' }] }] },
        baseMarkdown: 'before',
        stagedContent: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'after' }] }] },
        stagedMarkdown: 'after',
        diffPreview: 'diff',
        stagedAt: 100,
        stageMs: 2,
    };
}

function commitResult(status: 'committed' | 'conflict', actualRevision: number) {
    return {
        transactionId: 'txn-1',
        status,
        note: {},
        expectedRevision: 101,
        actualRevision,
        commitMs: status === 'committed' ? 4 : 0,
        indexInvalidationMs: status === 'committed' ? 2 : 0,
    };
}
