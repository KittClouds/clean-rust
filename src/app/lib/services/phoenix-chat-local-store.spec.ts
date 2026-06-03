import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../dexie/settings.service', () => {
    const settings = new Map<string, unknown>();
    return {
        getSetting: vi.fn((key: string, fallback: unknown) =>
            settings.has(key) ? settings.get(key) : fallback,
        ),
        setSetting: vi.fn((key: string, value: unknown) => {
            settings.set(key, value);
        }),
        removeSetting: vi.fn((key: string) => {
            settings.delete(key);
        }),
        __clearSettings: () => settings.clear(),
    };
});

import { PhoenixLocalChatStore } from './phoenix-chat-local-store';
import * as settingsMock from '../dexie/settings.service';

const clearSettings = (settingsMock as unknown as { __clearSettings: () => void }).__clearSettings;

describe('PhoenixLocalChatStore', () => {
    beforeEach(() => {
        clearSettings();
    });

    it('persists browser-local threads and messages through settings', () => {
        const store = new PhoenixLocalChatStore();
        const thread = store.createThread('world-1', 'narrative-1');

        const user = store.addMessage(thread.id, 'user', 'hello there', thread.narrative_id);
        const assistant = store.addMessage(thread.id, 'assistant', '', thread.narrative_id, true);

        expect(user?.content).toBe('hello there');
        expect(assistant?.is_streaming).toBe(true);
        expect(store.listThreads('world-1')[0].title).toBe('hello there');

        const updated = store.appendMessage(assistant!.id, 'hi');
        expect(updated?.content).toBe('hi');
        expect(updated?.is_streaming).toBe(true);

        const completed = store.updateMessage(assistant!.id, 'hi back');
        expect(completed?.content).toBe('hi back');
        expect(completed?.is_streaming).toBe(false);

        const restored = new PhoenixLocalChatStore();
        expect(restored.listMessages(thread.id).map((message) => message.content)).toEqual([
            'hello there',
            'hi back',
        ]);
    });

    it('creates a ready-to-answer run snapshot for browser streaming', () => {
        const store = new PhoenixLocalChatStore();
        const thread = store.createThread('world-1', 'narrative-1');
        const snapshot = store.startRun(thread, 'draft it', {
            finalProvider: 'go-openrouter',
            finalModel: 'model-a',
            plannerEnabled: true,
            omEnabled: true,
            workspaceEnabled: true,
            mutationsEnabled: false,
            deadlineMs: 8000,
            mutationPolicy: 'confirm',
            baseSystemPrompt: 'You are Kammi.',
            initialExternalContext: 'Highlighted context',
        });

        expect(snapshot.run.status).toBe('ready_to_answer');
        expect(snapshot.run.preparedSystemPrompt).toContain('You are Kammi.');
        expect(snapshot.run.preparedSystemPrompt).toContain('Highlighted context');
        expect(snapshot.missingCapabilities).toEqual([
            'native-planner',
            'native-workspace-context',
            'native-om-memory-extraction',
        ]);

        const streaming = store.markRunStreaming(snapshot.run.id, 'assistant-1');
        expect(streaming?.run.status).toBe('streaming');

        const completed = store.completeRun(snapshot.run.id, 'assistant-1', 'done');
        expect(completed?.run.status).toBe('completed');
        expect(completed?.run.finalResponse).toBe('done');
    });
});
