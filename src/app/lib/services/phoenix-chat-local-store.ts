import { getSetting, setSetting } from '../dexie/settings.service';
import type {
    CapabilityProfile,
    ChatRun,
    ChatRunEvent,
    ChatRunSnapshot,
    ChatWorkspaceArtifact,
    RunOptions,
    Thread,
    ThreadMessage,
} from './phoenix-chat.service';

interface LocalChatState {
    threads: Thread[];
    messagesByThreadId: Record<string, ThreadMessage[]>;
}

const STORAGE_KEY = 'chat:webFallbackState:v1';

export class PhoenixLocalChatStore {
    private readonly runs = new Map<string, ChatRunSnapshot>();

    listThreads(worldId = ''): Thread[] {
        const state = this.readState();
        return state.threads
            .filter((thread) => !worldId || thread.world_id === worldId)
            .sort((left, right) => right.updated_at - left.updated_at);
    }

    getThread(threadId: string): Thread | null {
        return this.readState().threads.find((thread) => thread.id === threadId) ?? null;
    }

    createThread(worldId: string, narrativeId: string): Thread {
        const now = Date.now();
        const thread: Thread = {
            id: localId('thread'),
            world_id: worldId || 'default',
            narrative_id: narrativeId || 'default',
            title: 'New Chat',
            created_at: now,
            updated_at: now,
        };
        const state = this.readState();
        state.threads = [thread, ...state.threads];
        state.messagesByThreadId[thread.id] = [];
        this.writeState(state);
        return thread;
    }

    deleteThread(threadId: string): boolean {
        const state = this.readState();
        const nextThreads = state.threads.filter((thread) => thread.id !== threadId);
        if (nextThreads.length === state.threads.length) {
            return false;
        }
        state.threads = nextThreads;
        delete state.messagesByThreadId[threadId];
        this.writeState(state);
        return true;
    }

    listMessages(threadId: string): ThreadMessage[] {
        return [...(this.readState().messagesByThreadId[threadId] ?? [])];
    }

    addMessage(
        threadId: string,
        role: ThreadMessage['role'],
        content: string,
        narrativeId: string,
        streaming = false,
    ): ThreadMessage | null {
        const state = this.readState();
        const thread = state.threads.find((candidate) => candidate.id === threadId);
        if (!thread) {
            return null;
        }

        const now = Date.now();
        const message: ThreadMessage = {
            id: localId('msg'),
            thread_id: threadId,
            role,
            content,
            narrative_id: narrativeId || thread.narrative_id || 'default',
            created_at: now,
            updated_at: now,
            is_streaming: streaming,
        };
        const messages = state.messagesByThreadId[threadId] ?? [];
        state.messagesByThreadId[threadId] = [...messages, message];
        this.touchThread(thread, now, role === 'user' ? content : undefined);
        this.writeState(state);
        return message;
    }

    updateMessage(messageId: string, content: string): ThreadMessage | null {
        return this.mutateMessage(messageId, (message, now) => ({
            ...message,
            content,
            updated_at: now,
            is_streaming: false,
        }));
    }

    appendMessage(messageId: string, chunk: string): ThreadMessage | null {
        return this.mutateMessage(messageId, (message, now) => ({
            ...message,
            content: `${message.content}${chunk}`,
            updated_at: now,
            is_streaming: true,
        }));
    }

    clearThread(threadId: string): boolean {
        const state = this.readState();
        if (!state.messagesByThreadId[threadId]) {
            return false;
        }
        state.messagesByThreadId[threadId] = [];
        const thread = state.threads.find((candidate) => candidate.id === threadId);
        if (thread) {
            thread.updated_at = Date.now();
            thread.title = 'New Chat';
        }
        this.writeState(state);
        return true;
    }

    exportThread(threadId: string): string {
        const thread = this.getThread(threadId);
        return JSON.stringify(
            {
                thread,
                messages: thread ? this.listMessages(thread.id) : [],
                source: 'browser-local-chat-fallback',
            },
            null,
            2,
        );
    }

    startRun(thread: Thread, prompt: string, options: RunOptions): ChatRunSnapshot {
        const now = Date.now();
        const runId = localId('run');
        const missingCapabilities = this.missingCapabilities(options);
        const preparedSystemPrompt = [options.baseSystemPrompt, options.initialExternalContext]
            .filter((part) => String(part || '').trim())
            .join('\n\n');
        const run: ChatRun = {
            id: runId,
            threadId: thread.id,
            userPrompt: prompt,
            status: 'ready_to_answer',
            options,
            capabilities: localCapabilities(),
            preparedContext: options.initialExternalContext || '',
            preparedSystemPrompt,
            plannerMessagesJson: '[]',
            evidenceJson: '[]',
            missingCapabilitiesJson: JSON.stringify(missingCapabilities),
            deadlineAt: now + Math.max(0, options.deadlineMs || 0),
            createdAt: now,
            updatedAt: now,
        };
        const snapshot = this.snapshot(run, [
            this.event(runId, 'browser', 'status', 'Browser chat ready', 'Streaming directly from the configured provider.', 'done'),
        ]);
        this.runs.set(runId, snapshot);
        return snapshot;
    }

    pollRun(runId: string): ChatRunSnapshot | null {
        return this.runs.get(runId) ?? null;
    }

    markRunStreaming(runId: string, assistantMessageId: string): ChatRunSnapshot | null {
        return this.updateRun(runId, (run) => ({
            ...run,
            assistantMessageId,
            status: 'streaming',
        }), 'Streaming provider response');
    }

    completeRun(
        runId: string,
        assistantMessageId: string,
        finalResponse: string,
        finalError?: string,
    ): ChatRunSnapshot | null {
        return this.updateRun(runId, (run) => ({
            ...run,
            assistantMessageId,
            finalResponse,
            error: finalError || undefined,
            status: finalError ? 'failed' : 'completed',
            completedAt: Date.now(),
        }), finalError ? 'Provider stream failed' : 'Provider stream completed');
    }

    listRunEvents(threadId: string, limit = 100): ChatRunEvent[] {
        return [...this.runs.values()]
            .filter((snapshot) => snapshot.run.threadId === threadId)
            .flatMap((snapshot) => snapshot.events)
            .sort((left, right) => right.createdAt - left.createdAt)
            .slice(0, limit);
    }

    emptyArtifacts(): ChatWorkspaceArtifact[] {
        return [];
    }

    private mutateMessage(
        messageId: string,
        mutate: (message: ThreadMessage, now: number) => ThreadMessage,
    ): ThreadMessage | null {
        const state = this.readState();
        const now = Date.now();
        for (const [threadId, messages] of Object.entries(state.messagesByThreadId)) {
            const index = messages.findIndex((message) => message.id === messageId);
            if (index < 0) {
                continue;
            }
            const next = mutate(messages[index], now);
            state.messagesByThreadId[threadId] = [
                ...messages.slice(0, index),
                next,
                ...messages.slice(index + 1),
            ];
            const thread = state.threads.find((candidate) => candidate.id === threadId);
            if (thread) {
                this.touchThread(thread, now);
            }
            this.writeState(state);
            return next;
        }
        return null;
    }

    private updateRun(
        runId: string,
        mutate: (run: ChatRun) => ChatRun,
        detail: string,
    ): ChatRunSnapshot | null {
        const current = this.runs.get(runId);
        if (!current) {
            return null;
        }
        const now = Date.now();
        const run = mutate({ ...current.run, updatedAt: now });
        const snapshot = this.snapshot(run, [
            ...current.events,
            this.event(runId, 'browser', 'status', detail, undefined, run.status === 'failed' ? 'error' : 'done'),
        ]);
        this.runs.set(runId, snapshot);
        return snapshot;
    }

    private snapshot(run: ChatRun, events: ChatRunEvent[]): ChatRunSnapshot {
        return {
            run,
            events,
            toolCalls: [],
            approvals: [],
            evidence: [],
            missingCapabilities: JSON.parse(run.missingCapabilitiesJson || '[]') as string[],
            plannerStep: null,
            artifacts: [],
        };
    }

    private event(
        runId: string,
        phase: string,
        kind: string,
        label: string,
        detail?: string,
        status?: string,
    ): ChatRunEvent {
        return {
            id: localId('event'),
            runId,
            sequence: (this.runs.get(runId)?.events.length || 0) + 1,
            phase,
            kind,
            label,
            detail,
            status,
            createdAt: Date.now(),
        };
    }

    private missingCapabilities(options: RunOptions): string[] {
        const missing: string[] = [];
        if (options.plannerEnabled) missing.push('native-planner');
        if (options.workspaceEnabled) missing.push('native-workspace-context');
        if (options.omEnabled) missing.push('native-om-memory-extraction');
        return missing;
    }

    private touchThread(thread: Thread, updatedAt: number, titleSeed?: string): void {
        thread.updated_at = updatedAt;
        if (titleSeed && (!thread.title || thread.title === 'New Chat')) {
            thread.title = titleSeed.trim().replace(/\s+/g, ' ').slice(0, 80) || 'New Chat';
        }
    }

    private readState(): LocalChatState {
        const state = getSetting<LocalChatState | null>(STORAGE_KEY, null);
        if (!state || !Array.isArray(state.threads) || !state.messagesByThreadId) {
            return { threads: [], messagesByThreadId: {} };
        }
        return {
            threads: state.threads.map((thread) => ({ ...thread })),
            messagesByThreadId: Object.fromEntries(
                Object.entries(state.messagesByThreadId).map(([threadId, messages]) => [
                    threadId,
                    Array.isArray(messages) ? messages.map((message) => ({ ...message })) : [],
                ]),
            ),
        };
    }

    private writeState(state: LocalChatState): void {
        setSetting(STORAGE_KEY, state);
    }
}

function localCapabilities(): CapabilityProfile {
    return {
        omEnabled: false,
        workspaceEnabled: false,
        plannerEnabled: false,
        goToolHost: false,
        tsToolHost: true,
        blockSearch: false,
    };
}

function localId(prefix: string): string {
    const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
    return `${prefix}-${random}`;
}
