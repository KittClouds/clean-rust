import { Injectable, inject } from '@angular/core';
import { NoteEditorStore } from '../store/note-editor.store';
import { PhoenixStoreService, type StoreNote } from '../../services/phoenix-store.service';
import { PhoenixUiApiService, type SearchScope } from '../../services/phoenix-ui-api.service';
import {
    boundedInlinePayload,
    numberFlag,
    parseAppIdeCommand,
    stringFlag,
    utf8Bytes,
    type AppIdeArtifactRef,
    type AppIdeCapabilityProfile,
    type AppIdeCommandDescriptor,
    type AppIdeToolResult,
    type ParsedAppIdeCommand,
} from './app-ide-command.contract';
import { AppIdePolicyRegistry } from './app-ide-policy.registry';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import { PhoenixChatService, type ChatRunSnapshot } from './phoenix-chat.service';

export interface AppIdeExecutionRequest {
    runId: string;
    callId: string;
    toolCallId: string;
    command: string;
    profile: AppIdeCapabilityProfile;
}

@Injectable({ providedIn: 'root' })
export class AppIdeCommandService {
    private readonly policies = inject(AppIdePolicyRegistry);
    private readonly store = inject(PhoenixStoreService);
    private readonly phoenix = inject(PhoenixUiApiService);
    private readonly workspace = inject(EditorAgentWorkspaceService);
    private readonly editorStore = inject(NoteEditorStore);
    private readonly chat = inject(PhoenixChatService);

    async execute(request: AppIdeExecutionRequest): Promise<AppIdeToolResult> {
        const startedAt = Date.now();
        const started = performance.now();
        const command = parseAppIdeCommand(request.command);
        const descriptor = this.policies.resolve(command);
        const policy = this.policies.evaluate(descriptor, request.profile, request.runId, {
            command,
            activeNarrativeId: this.editorStore.currentNote()?.narrativeId || undefined,
        });
        const startedEvent = await this.chat.appendRunEvent(request.runId, {
            phase: 'tool_running',
            kind: 'command',
            label: `Started ${descriptor.name}`,
            detail: command.canonical,
            status: 'running',
            payload: JSON.stringify({ capability: descriptor.name, policyDecisionId: policy.id }),
        });
        if (policy.decision !== 'allow') {
            return this.denied(request, command, descriptor, policy.id, policy.reason, startedAt, started);
        }

        try {
            const payload = await this.withTimeout(
                this.dispatch(command, request.runId),
                descriptor.timeoutMs,
                descriptor.name,
            );
            const totalBytes = utf8Bytes(payload);
            if (totalBytes > descriptor.outputBudget.artifactBytes) {
                throw new Error(
                    `${descriptor.name} output exceeded ${descriptor.outputBudget.artifactBytes} byte artifact budget.`,
                );
            }
            const artifact = await this.chat.putPlannerArtifact(
                request.runId,
                `app_ide/${descriptor.name}/v1`,
                {
                    command: command.raw,
                    capability: descriptor.name,
                    policy,
                    payload,
                    totalBytes,
                },
            );
            const bounded = boundedInlinePayload(payload, descriptor.outputBudget.inlineBytes);
            const artifactRefs = artifact
                ? [this.artifactRef(artifact.key, artifact.kind, totalBytes, artifact.pinned)]
                : [];
            const summary = this.summary(descriptor, payload, totalBytes, bounded.truncated);
            const completedAt = Date.now();
            const latencyMs = performance.now() - started;
            const completedEvent = await this.chat.appendRunEvent(request.runId, {
                phase: 'tool_running',
                kind: 'command',
                label: `Completed ${descriptor.name}`,
                detail: summary,
                status: 'done',
                payload: JSON.stringify({ artifactRefs, totalBytes, truncated: bounded.truncated }),
                latencyMs: Math.round(latencyMs),
            });
            const result: AppIdeToolResult = {
                schemaVersion: 'phoenix-app-ide-tool-result/v1',
                runId: request.runId,
                stepId: request.callId,
                callId: request.toolCallId,
                sequence: completedEvent?.sequence ?? startedEvent?.sequence ?? 0,
                capability: descriptor.name,
                command: command.canonical,
                status: 'ok',
                summary,
                inlinePayload: bounded.payload,
                artifactRefs,
                policyDecisionId: policy.id,
                truncated: bounded.truncated,
                totalBytes: bounded.totalBytes,
                latencyMs,
                startedAt,
                completedAt,
            };
            await this.compactContext(request.runId, result);
            return result;
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            const completedAt = Date.now();
            const latencyMs = performance.now() - started;
            const event = await this.chat.appendRunEvent(request.runId, {
                phase: 'tool_running',
                kind: 'command',
                label: `Failed ${descriptor.name}`,
                detail: message,
                status: 'error',
                latencyMs: Math.round(latencyMs),
            });
            return {
                schemaVersion: 'phoenix-app-ide-tool-result/v1',
                runId: request.runId,
                stepId: request.callId,
                callId: request.toolCallId,
                sequence: event?.sequence ?? 0,
                capability: descriptor.name,
                command: command.canonical,
                status: 'error',
                summary: message,
                inlinePayload: null,
                artifactRefs: [],
                policyDecisionId: policy.id,
                truncated: false,
                totalBytes: 0,
                latencyMs,
                startedAt,
                completedAt,
            };
        }
    }

    private async dispatch(command: ParsedAppIdeCommand, runId: string): Promise<unknown> {
        const route = `${command.domain}:${command.verb}`;
        switch (route) {
            case 'app:pwd': return this.appPwd();
            case 'app:status': return this.appStatus();
            case 'note:ls': return this.noteList(command);
            case 'note:stat': return this.noteStat(command);
            case 'note:cat': return this.noteRead(command);
            case 'search:lexical': return this.search(command, false);
            case 'search:semantic': return this.search(command, true);
            case 'index:status': return this.indexStatus(command);
            case 'graph:neighbors': return this.graphNeighbors(command);
            case 'graph:path': return this.graphPath(command);
            case 'artifact:ls': return this.artifactList(runId, command);
            case 'artifact:cat': return this.artifactRead(runId, command);
            default: throw new Error(`No handler registered for ${route}.`);
        }
    }

    private appPwd(): unknown {
        const note = this.editorStore.currentNote();
        return {
            narrativeId: String(note?.narrativeId || '__global__'),
            noteId: note?.id || null,
            noteUri: note ? this.noteUri(note.id, note.narrativeId) : null,
        };
    }

    private appStatus(): unknown {
        const note = this.editorStore.currentNote();
        const snapshot = this.workspace.getSnapshot();
        return {
            app: 'Phoenix Desktop',
            storeReady: this.store.isReady,
            derivedIndexReady: this.store.isDerivedReady,
            activeNote: note ? {
                id: note.id,
                uri: this.noteUri(note.id, note.narrativeId),
                title: note.title,
                revision: Number(note.version ?? note.updatedAt ?? 0),
            } : null,
            editor: snapshot ? {
                revision: snapshot.revision,
                characters: snapshot.text.length,
                selection: snapshot.selection,
            } : null,
            capabilityProfile: 'read_only',
            assertedGraphWrites: false,
        };
    }

    private async noteList(command: ParsedAppIdeCommand): Promise<unknown> {
        const limit = numberFlag(command, 'limit', 50, 1, 200);
        const uriScope = this.noteLocation(command.positionals[0]);
        const narrativeId = uriScope?.narrativeId || this.scope(command).narrativeId;
        const folderId = uriScope?.folderId || this.scope(command).folderId;
        const notes = (await this.store.listNoteHeaders())
            .filter((note) => !narrativeId || note.narrativeId === narrativeId)
            .filter((note) => !folderId || note.folderId === folderId)
            .slice(0, limit)
            .map((note) => ({
                uri: this.noteUri(note.id, note.narrativeId),
                id: note.id,
                title: note.title,
                folderId: note.folderId,
                revision: Number(note.version ?? note.updatedAt ?? 0),
            }));
        return {
            scope: folderId ? `folder:${folderId}` : narrativeId ? `narrative:${narrativeId}` : 'all',
            count: notes.length,
            notes,
        };
    }

    private async noteStat(command: ParsedAppIdeCommand): Promise<unknown> {
        const note = await this.requiredNote(command.positionals[0]);
        return {
            uri: this.noteUri(note.id, note.narrativeId),
            id: note.id,
            title: note.title,
            folderId: note.folderId,
            narrativeId: note.narrativeId,
            revision: Number(note.version ?? note.updatedAt ?? 0),
            markdownChars: note.markdownContent.length,
            documentBytes: utf8Bytes(note.content),
            updatedAt: note.updatedAt,
        };
    }

    private async noteRead(command: ParsedAppIdeCommand): Promise<unknown> {
        const note = await this.requiredNote(command.positionals[0]);
        const from = numberFlag(command, 'from', 0, 0, note.markdownContent.length);
        const to = numberFlag(command, 'to', note.markdownContent.length, from, note.markdownContent.length);
        return {
            uri: this.noteUri(note.id, note.narrativeId),
            revision: Number(note.version ?? note.updatedAt ?? 0),
            from,
            to,
            content: note.markdownContent.slice(from, to),
        };
    }

    private async search(command: ParsedAppIdeCommand, semantic: boolean): Promise<unknown> {
        const query = command.positionals.join(' ').trim();
        if (!query) throw new Error('Search query is required.');
        const limit = numberFlag(command, 'limit', 10, 1, 50);
        const scope = this.scope(command);
        const hits = semantic
            ? await this.phoenix.semanticSearch(query, limit, scope)
            : await this.store.lineSearch(query, { limit, before: 1, after: 1, scope });
        return { kind: semantic ? 'semantic' : 'lexical', query, scope, count: hits.length, hits };
    }

    private async indexStatus(command: ParsedAppIdeCommand): Promise<unknown> {
        const scope = this.scope(command);
        const notes = (await this.store.listNoteHeaders())
            .filter((note) => !scope.narrativeId || note.narrativeId === scope.narrativeId);
        return {
            scope,
            storeReady: this.store.isReady,
            lexicalReadReady: this.store.isReady,
            semanticDerivedReady: this.store.isDerivedReady,
            noteCount: notes.length,
            revisions: notes.slice(0, 100).map((note) => ({
                noteId: note.id,
                revision: Number(note.version ?? note.updatedAt ?? 0),
            })),
            ensured: false,
            mutated: false,
        };
    }

    private async graphNeighbors(command: ParsedAppIdeCommand): Promise<unknown> {
        const start = command.positionals[0];
        if (!start) throw new Error('Graph node ID is required.');
        const depth = numberFlag(command, 'depth', 1, 1, 4);
        const limit = numberFlag(command, 'limit', 50, 1, 200);
        const graph = await this.assertedGraph(command);
        const seen = new Set<string>([start]);
        let frontier = [start];
        const edges: any[] = [];
        for (let level = 0; level < depth && frontier.length && seen.size <= limit; level++) {
            const next: string[] = [];
            for (const edge of graph.edges) {
                if (!frontier.includes(edge.sourceId) && !frontier.includes(edge.targetId)) continue;
                edges.push(edge);
                const candidate = frontier.includes(edge.sourceId) ? edge.targetId : edge.sourceId;
                if (!seen.has(candidate) && seen.size < limit) {
                    seen.add(candidate);
                    next.push(candidate);
                }
            }
            frontier = next;
        }
        return {
            assertedOnly: true,
            start,
            depth,
            nodes: graph.nodes.filter((node: any) => seen.has(node.nodeId || node.vertexId)),
            edges,
        };
    }

    private async graphPath(command: ParsedAppIdeCommand): Promise<unknown> {
        const [source, target] = command.positionals;
        if (!source || !target) throw new Error('Graph path requires source and target node IDs.');
        const maxDepth = numberFlag(command, 'depth', 6, 1, 12);
        const graph = await this.assertedGraph(command);
        const adjacency = new Map<string, Array<{ id: string; edge: any }>>();
        for (const edge of graph.edges) {
            this.addNeighbor(adjacency, edge.sourceId, edge.targetId, edge);
            this.addNeighbor(adjacency, edge.targetId, edge.sourceId, edge);
        }
        const queue: Array<{ id: string; nodes: string[]; edges: any[] }> = [{ id: source, nodes: [source], edges: [] }];
        const seen = new Set([source]);
        while (queue.length) {
            const current = queue.shift()!;
            if (current.id === target) return { assertedOnly: true, found: true, nodes: current.nodes, edges: current.edges };
            if (current.edges.length >= maxDepth) continue;
            for (const next of adjacency.get(current.id) || []) {
                if (seen.has(next.id)) continue;
                seen.add(next.id);
                queue.push({ id: next.id, nodes: [...current.nodes, next.id], edges: [...current.edges, next.edge] });
            }
        }
        return { assertedOnly: true, found: false, source, target, maxDepth };
    }

    private async artifactList(runId: string, command: ParsedAppIdeCommand): Promise<unknown> {
        const limit = numberFlag(command, 'limit', 50, 1, 200);
        const artifacts = (await this.chat.listPlannerArtifacts(runId)).slice(-limit).map((artifact) => ({
            uri: `artifact://${encodeURIComponent(artifact.key)}`,
            key: artifact.key,
            kind: artifact.kind,
            pinned: artifact.pinned,
            bytes: utf8Bytes(artifact.payload),
            createdAt: artifact.createdAt,
        }));
        return { count: artifacts.length, artifacts };
    }

    private async artifactRead(runId: string, command: ParsedAppIdeCommand): Promise<unknown> {
        const key = this.artifactKey(command.positionals[0]);
        const artifact = (await this.chat.listPlannerArtifacts(runId)).find((item) => item.key === key);
        if (!artifact) throw new Error(`Artifact not found in this run: ${key}`);
        const text = typeof artifact.payload === 'string' ? artifact.payload : JSON.stringify(artifact.payload);
        const from = numberFlag(command, 'from', 0, 0, text.length);
        const to = numberFlag(command, 'to', Math.min(text.length, from + 32_000), from, text.length);
        return { key, kind: artifact.kind, pinned: artifact.pinned, from, to, totalChars: text.length, content: text.slice(from, to) };
    }

    private async assertedGraph(command: ParsedAppIdeCommand): Promise<{ nodes: any[]; edges: any[] }> {
        const delta: any = await this.phoenix.knowledgeGraphDelta(this.scope(command), [], false);
        return { nodes: [...(delta.nodes || []), ...(delta.chunks || [])], edges: delta.edges || [] };
    }

    private async requiredNote(uriOrId?: string): Promise<StoreNote> {
        const id = uriOrId ? this.noteId(uriOrId) : this.editorStore.currentNote()?.id;
        if (!id) throw new Error('Note URI or ID is required.');
        const note = await this.store.getNote(id);
        if (!note) throw new Error(`Note not found: ${id}`);
        return note;
    }

    private scope(command: ParsedAppIdeCommand): SearchScope {
        const raw = stringFlag(command, 'scope');
        if (!raw) {
            const note = this.editorStore.currentNote();
            return note?.narrativeId ? { mode: 'narrative', narrativeId: note.narrativeId } : {};
        }
        const [kind, ...rest] = raw.split(':');
        const value = rest.join(':');
        if (!value) throw new Error(`Invalid scope: ${raw}`);
        if (kind === 'narrative') return { mode: 'narrative', narrativeId: value };
        if (kind === 'note') return { mode: 'note', noteId: value };
        if (kind === 'folder') return { mode: 'folder', folderId: value };
        throw new Error(`Unsupported scope: ${raw}`);
    }

    private noteId(uriOrId: string): string {
        if (!uriOrId.startsWith('note://')) return uriOrId;
        const path = uriOrId.slice('note://'.length).split('#', 1)[0];
        const id = path.split('/').filter(Boolean).at(-1);
        if (!id) throw new Error(`Invalid note URI: ${uriOrId}`);
        return decodeURIComponent(id);
    }

    private noteLocation(uri?: string): { narrativeId: string; folderId: string } | null {
        if (!uri?.startsWith('note://')) return null;
        const parts = uri.slice('note://'.length).split('#', 1)[0].split('/').filter(Boolean).map(decodeURIComponent);
        if (parts.length < 2) throw new Error(`Invalid note location: ${uri}`);
        return { narrativeId: parts[0], folderId: parts.at(-1)! };
    }

    private noteUri(noteId: string, narrativeId?: string | null): string {
        return `note://${encodeURIComponent(narrativeId || '__global__')}/${encodeURIComponent(noteId)}`;
    }

    private artifactKey(uri?: string): string {
        if (!uri) throw new Error('Artifact URI or key is required.');
        return decodeURIComponent(uri.replace(/^artifact:\/\//, ''));
    }

    private addNeighbor(map: Map<string, Array<{ id: string; edge: any }>>, from: string, id: string, edge: any): void {
        const rows = map.get(from) || [];
        rows.push({ id, edge });
        map.set(from, rows);
    }

    private summary(descriptor: AppIdeCommandDescriptor, payload: unknown, bytes: number, truncated: boolean): string {
        const count = payload && typeof payload === 'object' && 'count' in payload
            ? `, ${(payload as any).count} rows`
            : '';
        return `${descriptor.name} completed (${bytes} bytes${count}${truncated ? ', inline truncated' : ''}).`;
    }

    private artifactRef(key: string, kind: string, bytes: number, pinned: boolean): AppIdeArtifactRef {
        return { uri: `artifact://${encodeURIComponent(key)}`, key, kind, bytes, pinned };
    }

    private async compactContext(runId: string, result: AppIdeToolResult): Promise<void> {
        const snapshot = await this.chat.pollRun(runId);
        if (!snapshot) return;
        await this.chat.compactRunContext(runId, this.contextSummary(snapshot, result));
    }

    private contextSummary(snapshot: ChatRunSnapshot, result: AppIdeToolResult): Record<string, unknown> {
        return {
            schemaVersion: 'phoenix-chat-context-projection/v1',
            activeGoal: snapshot.run.userPrompt,
            latestCommand: { capability: result.capability, command: result.command, summary: result.summary },
            decisions: [{ policyDecisionId: result.policyDecisionId, decision: 'allow' }],
            openQuestions: [],
            pendingPermissions: snapshot.approvals.filter((item) => item.status === 'pending').map((item) => item.id),
            transactionState: snapshot.approvals.map((item) => ({ id: item.id, status: item.status, rollbackToken: item.rollbackToken })),
            pinnedArtifacts: snapshot.artifacts.filter((item) => item.pinned).map((item) => item.key),
            definitionOfDone: 'Answer the user request without note or asserted graph mutation.',
        };
    }

    private async denied(
        request: AppIdeExecutionRequest,
        command: ParsedAppIdeCommand,
        descriptor: AppIdeCommandDescriptor,
        policyDecisionId: string,
        reason: string,
        startedAt: number,
        started: number,
    ): Promise<AppIdeToolResult> {
        const event = await this.chat.appendRunEvent(request.runId, {
            phase: 'tool_running',
            kind: 'policy',
            label: `Denied ${descriptor.name}`,
            detail: reason,
            status: 'error',
            payload: JSON.stringify({ policyDecisionId }),
        });
        return {
            schemaVersion: 'phoenix-app-ide-tool-result/v1',
            runId: request.runId,
            stepId: request.callId,
            callId: request.toolCallId,
            sequence: event?.sequence ?? 0,
            capability: descriptor.name,
            command: command.canonical,
            status: 'denied',
            summary: reason,
            inlinePayload: null,
            artifactRefs: [],
            policyDecisionId,
            truncated: false,
            totalBytes: 0,
            latencyMs: performance.now() - started,
            startedAt,
            completedAt: Date.now(),
        };
    }

    private async withTimeout<T>(promise: Promise<T>, timeoutMs: number, capability: string): Promise<T> {
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
            return await Promise.race([
                promise,
                new Promise<T>((_, reject) => {
                    timer = setTimeout(() => reject(new Error(`${capability} timed out after ${timeoutMs} ms.`)), timeoutMs);
                }),
            ]);
        } finally {
            if (timer) clearTimeout(timer);
        }
    }
}
