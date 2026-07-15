// @vitest-environment jsdom
import '@angular/compiler';
import { signal } from '@angular/core';
import { TestBed, getTestBed } from '@angular/core/testing';
import { BrowserDynamicTestingModule, platformBrowserDynamicTesting } from '@angular/platform-browser-dynamic/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const operations = vi.hoisted(() => ({ commitMultiNoteTransaction: vi.fn() }));
vi.mock('../operations', () => ({ commitMultiNoteTransaction: operations.commitMultiNoteTransaction }));

import { CanvasMultiNoteTransactionService } from './canvas-multi-note-transaction.service';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import { PhoenixChatService } from './phoenix-chat.service';
import { NoteEditorStore } from '../store/note-editor.store';
import { PhoenixStoreService } from '../../services/phoenix-store.service';

try {
    getTestBed().initTestEnvironment(BrowserDynamicTestingModule, platformBrowserDynamicTesting());
} catch {}

describe('CanvasMultiNoteTransactionService', () => {
    const store = {
        getNote: vi.fn(),
        listNoteHeaders: vi.fn(async () => []),
    };
    const workspace = {
        parseMarkdownProjection: vi.fn((markdown: string) => ({
            type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: markdown }] }],
        })),
        getDocumentRevision: vi.fn(() => null),
        applyDocumentProjection: vi.fn(() => ({ ok: true })),
    };
    const chat = { putPlannerArtifact: vi.fn(async (_run: string, kind: string) => ({ key: `artifact-${kind}` })) };
    const currentNote = signal(note('note-1', 'before', 10));

    beforeEach(() => {
        vi.clearAllMocks();
        workspace.getDocumentRevision.mockReturnValue(null);
        workspace.applyDocumentProjection.mockReturnValue({ ok: true });
        store.getNote.mockImplementation(async (id: string) => id === 'note-1' ? storedNote('note-1', 'before', 10) : null);
        operations.commitMultiNoteTransaction.mockResolvedValue({
            transactionId: 'txn', status: 'committed', notes: [storedNote('note-1', 'after', 11)],
            conflicts: [], commitMs: 4, indexInvalidationMs: 2,
        });
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [
            CanvasMultiNoteTransactionService,
            { provide: PhoenixStoreService, useValue: store },
            { provide: EditorAgentWorkspaceService, useValue: workspace },
            { provide: PhoenixChatService, useValue: chat },
            { provide: NoteEditorStore, useValue: { currentNote } },
        ] });
    });

    it('stages patch, rename, move, and create as one checkpointed transaction', async () => {
        const service = TestBed.inject(CanvasMultiNoteTransactionService);
        const result = await service.stage('run-1', [
            { kind: 'patch', noteId: 'note-1', expectedRevision: 10, edits: [{ from: 0, to: 6, replacement: 'after', expectedText: 'before' }] },
            { kind: 'rename', noteId: 'note-1', expectedRevision: 10, title: 'Renamed' },
            { kind: 'move', noteId: 'note-1', expectedRevision: 10, folderId: 'folder-2' },
            { kind: 'create', noteId: 'note-2', title: 'Created', folderId: 'folder-2', markdownContent: 'new' },
        ]);

        expect(result.ok).toBe(true);
        expect(result.transaction?.mutations).toHaveLength(2);
        expect(result.transaction?.mutations[0].operationKinds).toEqual(['patch', 'rename', 'move']);
        expect(result.transaction?.mutations[1].operationKinds).toEqual(['create']);
        expect(result.transaction?.checkpointArtifactKey).toContain('canvas_multi_note_checkpoint_v1');
    });

    it('returns every CAS conflict and commits no editor projection', async () => {
        operations.commitMultiNoteTransaction.mockResolvedValue({
            transactionId: 'txn', status: 'conflict', notes: [], commitMs: 0, indexInvalidationMs: 0,
            conflicts: [{ noteId: 'note-1', expectedRevision: 10, actualRevision: 12, reason: 'revision_changed' }],
        });
        const service = TestBed.inject(CanvasMultiNoteTransactionService);
        const staged = await service.stage('run-1', [
            { kind: 'rename', noteId: 'note-1', expectedRevision: 10, title: 'Renamed' },
        ]);
        const result = await service.commit(staged.transaction!);

        expect(result.ok).toBe(false);
        expect(result.receipt.status).toBe('conflict');
        expect(result.receipt.conflicts[0]).toEqual(expect.objectContaining({ actualRevision: 12 }));
        expect(workspace.applyDocumentProjection).not.toHaveBeenCalled();
    });

    it('honors cancellation before entering the atomic commit boundary', async () => {
        const service = TestBed.inject(CanvasMultiNoteTransactionService);
        const staged = await service.stage('run-1', [
            { kind: 'rename', noteId: 'note-1', expectedRevision: 10, title: 'Renamed' },
        ]);
        const controller = new AbortController();
        controller.abort();
        const result = await service.commit(staged.transaction!, controller.signal);

        expect(result.receipt.status).toBe('cancelled');
        expect(operations.commitMultiNoteTransaction).not.toHaveBeenCalled();
    });

    it('refreshes the mounted editor from committed JSON only after the atomic commit', async () => {
        workspace.getDocumentRevision.mockReturnValue(100);
        const service = TestBed.inject(CanvasMultiNoteTransactionService);
        const staged = await service.stage('run-1', [
            { kind: 'patch', noteId: 'note-1', expectedRevision: 10, edits: [{ from: 0, to: 6, replacement: 'after' }] },
        ]);

        const result = await service.commit(staged.transaction!);

        expect(result.ok).toBe(true);
        expect(workspace.applyDocumentProjection).toHaveBeenCalledWith('note-1', { type: 'doc' });
    });
});

function note(id: string, markdown: string, version: number) {
    return { id, title: 'One', content: { type: 'doc' }, markdownContent: markdown, folderId: 'folder-1',
        worldId: '', entityKind: '', entitySubtype: '', isEntity: false, isPinned: false, favorite: false,
        ownerId: '', narrativeId: 'story-1', order: 0, createdAt: 1, updatedAt: version, version };
}

function storedNote(id: string, markdown: string, version: number) {
    return { ...note(id, markdown, version), content: JSON.stringify({ type: 'doc' }) };
}
