// @vitest-environment jsdom
import '@angular/compiler';
import { signal } from '@angular/core';
import { TestBed, getTestBed } from '@angular/core/testing';
import {
    BrowserDynamicTestingModule,
    platformBrowserDynamicTesting,
} from '@angular/platform-browser-dynamic/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const settings = vi.hoisted(() => new Map<string, unknown>());
vi.mock('../dexie/settings.service', () => ({
    getSetting: (key: string, fallback: unknown) => settings.has(key) ? settings.get(key) : fallback,
    setSetting: (key: string, value: unknown) => settings.set(key, value),
}));

import { CanvasAgentRunService } from './canvas-agent-run.service';
import { ChatToolHostService } from './chat-tool-host.service';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import { PhoenixChatService, type ChatRun, type ChatRunSnapshot } from './phoenix-chat.service';
import { NoteEditorStore } from '../store/note-editor.store';

try {
    getTestBed().initTestEnvironment(
        BrowserDynamicTestingModule,
        platformBrowserDynamicTesting(),
    );
} catch {
    // Test environment already initialized for this Vitest worker.
}

describe('CanvasAgentRunService', () => {
    const chat = {
        init: vi.fn(async () => undefined),
        addUserMessage: vi.fn(async () => undefined),
        startRun: vi.fn(),
        pollRun: vi.fn(),
        processPlannerRun: vi.fn(async () => true),
        submitToolResults: vi.fn(),
        submitApproval: vi.fn(),
        startStreamingMessage: vi.fn(),
        markRunStreaming: vi.fn(),
        updateMessage: vi.fn(),
        completeRun: vi.fn(),
        cancelRun: vi.fn(async () => true),
    };
    const workspace = {
        getSnapshot: vi.fn(() => ({
            noteId: 'note-1',
            noteTitle: 'Shortrun B',
            revision: 11,
            markdown: 'their cars like monkeys',
            text: 'their cars like monkeys',
            selection: { from: 8, to: 19, empty: false, text: 'their cars' },
            blocks: [],
        })),
    };
    const noteEditorStore = {
        currentNote: signal({
            id: 'note-1',
            title: 'Shortrun B',
            version: 41,
            updatedAt: 41,
            narrativeId: 'story-1',
        }),
    };

    beforeEach(() => {
        settings.clear();
        settings.set('openrouter:config', {
            apiKey: 'test-key',
            model: 'test-model',
            omEnabled: false,
        });
        vi.clearAllMocks();
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({
            providers: [
                CanvasAgentRunService,
                { provide: PhoenixChatService, useValue: chat },
                { provide: ChatToolHostService, useValue: {
                    executeCall: vi.fn(), applyApproval: vi.fn(), applyTrustedApproval: vi.fn(async () => null),
                    trustApproval: vi.fn(), revokeTrustedRun: vi.fn(),
                } },
                { provide: EditorAgentWorkspaceService, useValue: workspace },
                { provide: NoteEditorStore, useValue: noteEditorStore },
            ],
        });
    });

    it('launches a durable revision-bound run from a toolbar selection', async () => {
        const run = runRecord('run-1', 'planning');
        const waiting = snapshot(runRecord('run-1', 'awaiting_approval'));
        chat.startRun.mockResolvedValue(run);
        chat.pollRun.mockResolvedValue(waiting);
        const service = TestBed.inject(CanvasAgentRunService);

        await service.startSelectionRun(
            'Improve this selected text.',
            { from: 8, to: 19, empty: false, text: 'their cars' },
            'toolbar',
        );

        expect(chat.startRun).toHaveBeenCalledWith(
            expect.stringContaining('Selected text:\ntheir cars'),
            expect.objectContaining({
                plannerEnabled: true,
                mutationsEnabled: true,
                mutationPolicy: 'confirm',
                canvasTarget: {
                    noteUri: 'note://story-1/note-1',
                    noteId: 'note-1',
                    baseRevision: 41,
                    editorRevision: 11,
                    from: 8,
                    to: 19,
                },
            }),
        );
        expect(settings.get('ai-harness:active-canvas-run')).toBe('run-1');
        expect(service.status()).toBe('awaiting_approval');
    });

    it('reopens the same durable run after the app service is recreated', async () => {
        settings.set('ai-harness:active-canvas-run', 'run-persisted');
        chat.pollRun.mockResolvedValue(snapshot(runRecord('run-persisted', 'completed')));

        const service = TestBed.inject(CanvasAgentRunService);

        await vi.waitFor(() => expect(service.status()).toBe('completed'));
        expect(chat.init).toHaveBeenCalled();
        expect(chat.pollRun).toHaveBeenCalledWith('run-persisted');
        expect(service.currentRunId()).toBe('run-persisted');
    });

    it('launches a workspace transaction without requiring a selection', async () => {
        const run = runRecord('run-workspace', 'planning');
        chat.startRun.mockResolvedValue(run);
        chat.pollRun.mockResolvedValue(snapshot(runRecord('run-workspace', 'awaiting_approval')));
        const service = TestBed.inject(CanvasAgentRunService);

        await service.startWorkspaceRun('Rename and move both chapter notes.', 'side-panel');

        expect(chat.startRun).toHaveBeenCalledWith(
            'Rename and move both chapter notes.',
            expect.objectContaining({
                mutationPolicy: 'confirm',
                baseSystemPrompt: expect.stringContaining('multi_note_proposal'),
                initialExternalContext: expect.stringContaining('atomic multi-note workspace'),
            }),
        );
    });
});

function runRecord(id: string, status: ChatRun['status']): ChatRun {
    return {
        id,
        threadId: 'thread-1',
        userPrompt: 'Improve it',
        status,
        options: {} as ChatRun['options'],
        capabilities: {} as ChatRun['capabilities'],
        preparedContext: '',
        preparedSystemPrompt: '',
        plannerMessagesJson: '[]',
        evidenceJson: '[]',
        missingCapabilitiesJson: '[]',
        deadlineAt: 1000,
        createdAt: 1,
        updatedAt: 1,
    };
}

function snapshot(run: ChatRun): ChatRunSnapshot {
    return {
        run,
        events: [],
        toolCalls: [],
        approvals: run.status === 'awaiting_approval'
            ? [{
                id: 'approval-1',
                runId: run.id,
                toolCallId: 'call-1',
                toolName: 'replace_text_proposal',
                status: 'pending',
                summary: 'Replace selection',
                createdAt: 1,
                updatedAt: 1,
            }]
            : [],
        evidence: [],
        missingCapabilities: [],
        artifacts: [],
    };
}
