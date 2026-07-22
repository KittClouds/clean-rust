// @vitest-environment jsdom
import '@angular/compiler';
import { TestBed, getTestBed } from '@angular/core/testing';
import { BrowserDynamicTestingModule, platformBrowserDynamicTesting } from '@angular/platform-browser-dynamic/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NoteEditorStore } from '../store/note-editor.store';
import { PhoenixStoreService } from '../../services/phoenix-store.service';
import { PhoenixUiApiService } from '../../services/phoenix-ui-api.service';
import { AppIdeCommandService } from './app-ide-command.service';
import { AppIdePolicyRegistry } from './app-ide-policy.registry';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import { PhoenixChatService } from './phoenix-chat.service';

try {
    getTestBed().initTestEnvironment(BrowserDynamicTestingModule, platformBrowserDynamicTesting());
} catch {
    // Test environment already initialized for this worker.
}

describe('AppIdeCommandService', () => {
    let sequence = 0;
    const store = {
        isReady: true,
        isDerivedReady: true,
        getNote: vi.fn(),
        listNoteHeaders: vi.fn(),
        lineSearch: vi.fn(),
    };
    const phoenix = {
        semanticSearch: vi.fn(),
        knowledgeGraphDelta: vi.fn(),
    };
    const workspace = { getSnapshot: vi.fn() };
    const editor = { currentNote: vi.fn() };
    const chat = {
        appendRunEvent: vi.fn(async () => ({ sequence: ++sequence })),
        putPlannerArtifact: vi.fn(),
        listPlannerArtifacts: vi.fn(),
        pollRun: vi.fn(),
        compactRunContext: vi.fn(),
    };
    let service: AppIdeCommandService;

    beforeEach(() => {
        vi.clearAllMocks();
        sequence = 0;
        editor.currentNote.mockReturnValue({ id: 'note-1', narrativeId: 'story-1', title: 'Shortrun B', version: 41 });
        workspace.getSnapshot.mockReturnValue(null);
        store.listNoteHeaders.mockResolvedValue([]);
        store.getNote.mockResolvedValue({
            id: 'note-1', narrativeId: 'story-1', title: 'Shortrun B', folderId: 'folder-1',
            content: '{"type":"doc"}', markdownContent: 'x'.repeat(12_000), version: 41, updatedAt: 41,
        });
        chat.putPlannerArtifact.mockResolvedValue({
            key: 'rlm:run-1:note.read:1', kind: 'app_ide/note.read/v1', pinned: false,
        });
        chat.pollRun.mockResolvedValue({
            run: { userPrompt: 'Inspect the note' }, approvals: [], artifacts: [],
        });
        chat.compactRunContext.mockResolvedValue({ compacted: false });
        TestBed.configureTestingModule({
            providers: [
                AppIdeCommandService,
                AppIdePolicyRegistry,
                { provide: PhoenixStoreService, useValue: store },
                { provide: PhoenixUiApiService, useValue: phoenix },
                { provide: EditorAgentWorkspaceService, useValue: workspace },
                { provide: NoteEditorStore, useValue: editor },
                { provide: PhoenixChatService, useValue: chat },
            ],
        });
        service = TestBed.inject(AppIdeCommandService);
    });

    it('retains a large exact note read as an artifact and returns only budgeted inline context', async () => {
        const result = await service.execute(request('phx note cat note://story-1/note-1'));

        expect(result.status).toBe('ok');
        expect(result.capability).toBe('note.read');
        expect(result.truncated).toBe(true);
        expect(result.sequence).toBe(2);
        expect(result.artifactRefs[0].uri).toContain('artifact://');
        expect(chat.putPlannerArtifact).toHaveBeenCalledWith(
            'run-1',
            'app_ide/note.read/v1',
            expect.objectContaining({ payload: expect.objectContaining({ content: 'x'.repeat(12_000) }) }),
        );
        expect(chat.compactRunContext).toHaveBeenCalledWith(
            'run-1',
            expect.objectContaining({ activeGoal: 'Inspect the note' }),
        );
    });

    it('reads graph neighbors with candidate graph explicitly disabled', async () => {
        phoenix.knowledgeGraphDelta.mockResolvedValue({
            nodes: [
                { nodeId: 'entity:ryan', label: 'Ryan' },
                { nodeId: 'entity:harbor', label: 'Harbor' },
            ],
            chunks: [],
            edges: [{ sourceId: 'entity:ryan', targetId: 'entity:harbor', edgeType: 'visited' }],
        });

        const result = await service.execute(request('phx graph neighbors entity:ryan --depth 2'));

        expect(result.status).toBe('ok');
        expect((result.inlinePayload as any).assertedOnly).toBe(true);
        expect(phoenix.knowledgeGraphDelta).toHaveBeenCalledWith(
            { mode: 'narrative', narrativeId: 'story-1' },
            [],
            false,
        );
        expect(chat.putPlannerArtifact).toHaveBeenCalledTimes(1);
    });

    it('fails closed before I/O when a read escapes the active narrative', async () => {
        const result = await service.execute(request('phx note cat note://other-story/note-9'));

        expect(result.status).toBe('denied');
        expect(result.summary).toContain('active narrative');
        expect(result.sequence).toBe(2);
        expect(store.getNote).not.toHaveBeenCalled();
        expect(chat.putPlannerArtifact).not.toHaveBeenCalled();
    });
});

function request(command: string) {
    return {
        runId: 'run-1',
        callId: 'call-row-1',
        toolCallId: 'tool-call-1',
        command,
        profile: 'read_only' as const,
    };
}
