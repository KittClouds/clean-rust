// @vitest-environment jsdom
import '@angular/compiler';
import { TestBed, getTestBed } from '@angular/core/testing';
import {
    BrowserDynamicTestingModule,
    platformBrowserDynamicTesting,
} from '@angular/platform-browser-dynamic/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatToolHostService } from './chat-tool-host.service';
import { CanvasNoteTransactionService } from './canvas-note-transaction.service';
import {
    CANVAS_NOTE_RECEIPT_KIND,
    CANVAS_NOTE_TRANSACTION_KIND,
    type CanvasStagedNoteTransaction,
} from './canvas-note-transaction';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import type { ChatApprovalRequest, ChatToolCall } from './phoenix-chat.service';
import { AppIdeCommandService } from './app-ide-command.service';
import { CanvasMultiNoteTransactionService } from './canvas-multi-note-transaction.service';
import { CanvasTrustedGrantService } from './canvas-trusted-grant.service';

try {
    getTestBed().initTestEnvironment(
        BrowserDynamicTestingModule,
        platformBrowserDynamicTesting(),
    );
} catch {
    // Test environment already initialized for this Vitest worker.
}

describe('ChatToolHostService Canvas transaction', () => {
    const workspace = {
        getSnapshot: vi.fn(),
        stageReplaceText: vi.fn(),
    };
    const transactions = {
        commit: vi.fn(),
        reject: vi.fn(),
        rollback: vi.fn(),
    };
    const appIde = { execute: vi.fn() };
    const multiNoteTransactions = { stage: vi.fn(), commit: vi.fn(), reject: vi.fn() };
    const trustedGrants = { issueForTransaction: vi.fn(), consume: vi.fn(), revokeRun: vi.fn() };
    let service: ChatToolHostService;

    beforeEach(() => {
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            providers: [
                ChatToolHostService,
                { provide: EditorAgentWorkspaceService, useValue: workspace },
                { provide: CanvasNoteTransactionService, useValue: transactions },
                { provide: AppIdeCommandService, useValue: appIde },
                { provide: CanvasMultiNoteTransactionService, useValue: multiNoteTransactions },
                { provide: CanvasTrustedGrantService, useValue: trustedGrants },
            ],
        });
        service = TestBed.inject(ChatToolHostService);
        workspace.getSnapshot.mockReturnValue({
            noteId: 'note-1',
            noteTitle: 'Shortrun B',
            revision: 11,
            blocks: [],
        });
        workspace.stageReplaceText.mockReturnValue({ ok: true, transaction: transaction() });
    });

    it('stages a durable replacement proposal without mutating the editor', async () => {
        const result = await service.executeCall(toolCall());

        expect(workspace.stageReplaceText).toHaveBeenCalledWith('run-1', 8, 19, 'their vehicles', 11);
        expect(result.proposal).toEqual(expect.objectContaining({
            affectedNoteId: 'note-1',
            expectedRevision: 101,
            rollbackToken: 'txn-1',
            diffPreview: 'exact diff',
        }));
        expect(JSON.parse(result.proposal!.payloadJson!)).toEqual(transaction());
        expect(transactions.commit).not.toHaveBeenCalled();
    });

    it('routes app_exec through the typed read-only policy host', async () => {
        appIde.execute.mockResolvedValue({
            schemaVersion: 'phoenix-app-ide-tool-result/v1',
            status: 'ok',
            capability: 'app.status',
        });
        const call = { ...toolCall(), toolName: 'app_exec', argumentsJson: '{"command":"phx app status"}' };

        const result = await service.executeCall(call);

        expect(appIde.execute).toHaveBeenCalledWith({
            runId: 'run-1',
            callId: call.id,
            toolCallId: call.toolCallId,
            command: 'phx app status',
            profile: 'read_only',
        });
        expect(JSON.parse(result.resultJson!)).toEqual(expect.objectContaining({ capability: 'app.status' }));
    });

    it('stages one checkpoint-backed multi-note proposal', async () => {
        multiNoteTransactions.stage.mockResolvedValue({
            ok: true,
            transaction: {
                kind: 'canvas_multi_note_transaction_v1', transactionId: 'multi-1', runId: 'run-1',
                narrativeId: 'story-1', mutations: [{ noteId: 'note-1', expectedRevision: 10 }],
                diffPreview: 'multi diff', checkpointArtifactKey: 'checkpoint-1', stagedAt: 1, stageMs: 1,
            },
        });
        const call = { ...toolCall(), toolName: 'multi_note_proposal', argumentsJson: JSON.stringify({
            operations: [{ kind: 'rename', noteId: 'note-1', expectedRevision: 10, title: 'New' }],
        }) };

        const result = await service.executeCall(call);

        expect(multiNoteTransactions.stage).toHaveBeenCalledWith('run-1', expect.any(Array));
        expect(result.proposal).toEqual(expect.objectContaining({
            summary: 'Atomic 1-note transaction',
            rollbackToken: 'checkpoint-1',
            diffPreview: 'multi diff',
        }));
    });

    it('commits only after approval and returns the durable timing receipt', async () => {
        transactions.commit.mockResolvedValue({
            ok: true,
            noteId: 'note-1',
            beforeRevision: 101,
            afterRevision: 102,
            receipt: receipt('committed'),
        });

        const result = JSON.parse(await service.applyApproval(approval(), true));

        expect(transactions.commit).toHaveBeenCalledWith(transaction());
        expect(result.applied).toBe(true);
        expect(result.receipt).toEqual(receipt('committed'));
    });

    it('rejects without touching the note transaction', async () => {
        transactions.reject.mockReturnValue({
            ok: true,
            noteId: 'note-1',
            receipt: receipt('rejected'),
        });

        const result = JSON.parse(await service.applyApproval(approval(), false));

        expect(transactions.reject).toHaveBeenCalledWith(transaction());
        expect(transactions.commit).not.toHaveBeenCalled();
        expect(result.applied).toBe(false);
        expect(result.receipt.status).toBe('rejected');
    });

    it('auto-applies only a matching trusted multi-note approval', async () => {
        trustedGrants.consume.mockReturnValue({ allowed: true, grantId: 'grant-1' });
        multiNoteTransactions.commit.mockResolvedValue({
            ok: true,
            receipt: { kind: 'canvas_multi_note_receipt_v1', status: 'committed' },
        });
        const approval = multiApproval();

        const result = JSON.parse((await service.applyTrustedApproval(approval))!);

        expect(trustedGrants.consume).toHaveBeenCalledWith(multiTransaction());
        expect(multiNoteTransactions.commit).toHaveBeenCalledWith(multiTransaction(), undefined);
        expect(result).toEqual(expect.objectContaining({ applied: true, trustedGrantId: 'grant-1' }));
    });
});

function toolCall(): ChatToolCall {
    return {
        id: 'call-row-1',
        runId: 'run-1',
        toolCallId: 'call-1',
        toolName: 'replace_text_proposal',
        host: 'typescript',
        class: 'proposal',
        status: 'pending_host',
        argumentsJson: JSON.stringify({ from: 8, to: 19, replacement: 'their vehicles', expectedRevision: 11 }),
    };
}

function approval(): ChatApprovalRequest {
    return {
        id: 'approval-1',
        runId: 'run-1',
        toolCallId: 'call-1',
        toolName: 'replace_text_proposal',
        status: 'pending',
        affectedNoteId: 'note-1',
        summary: 'Replace selection',
        proposalJson: JSON.stringify({ payloadJson: JSON.stringify(transaction()) }),
        createdAt: 100,
        updatedAt: 100,
    };
}

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
        beforeText: 'their cars',
        replacement: 'their vehicles',
        baseContent: { type: 'doc', content: [] },
        baseMarkdown: 'their cars',
        stagedContent: { type: 'doc', content: [{ type: 'paragraph' }] },
        stagedMarkdown: 'their vehicles',
        diffPreview: 'exact diff',
        stagedAt: 100,
        stageMs: 2,
    };
}

function receipt(status: 'committed' | 'rejected') {
    return {
        kind: CANVAS_NOTE_RECEIPT_KIND,
        transactionId: 'txn-1',
        runId: 'run-1',
        noteUri: 'note://story/note-1',
        noteId: 'note-1',
        status,
        beforeRevision: 101,
        afterRevision: status === 'committed' ? 102 : 101,
        checkpointRevision: 101,
        from: 8,
        to: 19,
        beforeText: 'their cars',
        replacement: 'their vehicles',
        timings: { stageMs: 2, commitMs: 4, indexInvalidationMs: 1, editorRefreshMs: 1, totalMs: 8 },
        completedAt: 200,
    };
}

function multiApproval(): ChatApprovalRequest {
    return {
        id: 'approval-multi', runId: 'run-1', toolCallId: 'call-multi', toolName: 'multi_note_proposal',
        status: 'pending', summary: 'Atomic transaction',
        proposalJson: JSON.stringify({ payloadJson: JSON.stringify(multiTransaction()) }),
        createdAt: 1, updatedAt: 1,
    };
}

function multiTransaction() {
    return {
        kind: 'canvas_multi_note_transaction_v1', transactionId: 'multi-1', runId: 'run-1', narrativeId: 'story',
        mutations: [{
            noteId: 'note-1', noteUri: 'note://story/note-1', operationKinds: ['rename'], expectedRevision: 10,
            before: null,
            after: {
                id: 'note-1', worldId: '', title: 'New', content: { type: 'doc' }, markdownContent: '',
                folderId: '', entityKind: '', entitySubtype: '', isEntity: false, isPinned: false, favorite: false,
                ownerId: '', narrativeId: 'story', order: 0, createdAt: 1, updatedAt: 10, version: 10,
            },
        }],
        diffPreview: 'diff', stagedAt: 1, stageMs: 1,
    };
}
