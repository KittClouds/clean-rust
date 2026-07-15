import { Injectable, computed, inject, signal } from '@angular/core';
import { getSetting, setSetting } from '../dexie/settings.service';
import { NoteEditorStore } from '../store/note-editor.store';
import type { WorkspaceSelectionSnapshot } from './editor-agent-workspace.service';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import { ChatToolHostService } from './chat-tool-host.service';
import {
    PhoenixChatService,
    type ChatApprovalRequest,
    type ChatConfig,
    type ChatRunSnapshot,
    type RunOptions,
} from './phoenix-chat.service';
import {
    CANVAS_NOTE_RECEIPT_KIND,
    type CanvasTransactionReceipt,
} from './canvas-note-transaction';
import {
    CANVAS_MULTI_NOTE_RECEIPT_KIND,
    type CanvasMultiNoteReceipt,
} from './canvas-multi-note-transaction';

export type CanvasRunInitiator = 'toolbar' | 'side-panel' | 'ai-page' | 'recovery';
export type CanvasHarnessReceipt = CanvasTransactionReceipt | CanvasMultiNoteReceipt;

const ACTIVE_CANVAS_RUN_KEY = 'ai-harness:active-canvas-run';
const CANVAS_RUN_DEADLINE_MS = 60_000;

@Injectable({ providedIn: 'root' })
export class CanvasAgentRunService {
    private readonly chat = inject(PhoenixChatService);
    private readonly toolHost = inject(ChatToolHostService);
    private readonly workspace = inject(EditorAgentWorkspaceService);
    private readonly noteEditorStore = inject(NoteEditorStore);
    private readonly runIdSignal = signal<string | null>(
        getSetting<string | null>(ACTIVE_CANVAS_RUN_KEY, null),
    );
    private readonly snapshotSignal = signal<ChatRunSnapshot | null>(null);
    private readonly busySignal = signal(false);
    private readonly errorSignal = signal<string | null>(null);
    private readonly receiptSignal = signal<CanvasHarnessReceipt | null>(null);
    private readonly initiatorSignal = signal<CanvasRunInitiator>('recovery');
    private abortController: AbortController | null = null;
    private cancelRequested = false;

    readonly currentRunId = computed(() => this.runIdSignal());
    readonly snapshot = computed(() => this.snapshotSignal());
    readonly busy = computed(() => this.busySignal());
    readonly error = computed(() => this.errorSignal());
    readonly receipt = computed(() => this.receiptSignal());
    readonly initiator = computed(() => this.initiatorSignal());
    readonly pendingApprovals = computed(() =>
        (this.snapshotSignal()?.approvals || []).filter((approval) => approval.status === 'pending'),
    );
    readonly status = computed(() => this.snapshotSignal()?.run.status || 'idle');

    constructor() {
        if (this.runIdSignal()) {
            queueMicrotask(() => void this.resumePersistedRun());
        }
    }

    async startSelectionRun(
        instruction: string,
        selection?: WorkspaceSelectionSnapshot,
        initiator: CanvasRunInitiator = 'side-panel',
    ): Promise<ChatRunSnapshot | null> {
        if (this.busySignal()) return this.snapshotSignal();
        const document = this.workspace.getSnapshot();
        const target = selection || document?.selection;
        const config = getSetting<ChatConfig | null>('openrouter:config', null);
        if (!document || !target || target.empty || !target.text.trim()) {
            this.errorSignal.set('Canvas requires a non-empty selection in the active note.');
            return null;
        }
        if (!config?.apiKey?.trim()) {
            this.errorSignal.set('Canvas transaction requires an OpenRouter API key for the planner.');
            return null;
        }

        this.busySignal.set(true);
        this.abortController = new AbortController();
        this.cancelRequested = false;
        this.errorSignal.set(null);
        this.receiptSignal.set(null);
        this.initiatorSignal.set(initiator);
        try {
            await this.chat.init(config);
            await this.chat.addUserMessage(instruction);
            const run = await this.chat.startRun(
                this.canvasPrompt(instruction, target),
                this.runOptions(document, target, config),
            );
            if (!run) throw new Error('Failed to create durable Canvas run.');
            this.setActiveRun(run.id);
            return await this.drive(run.id);
        } catch (error) {
            this.errorSignal.set(this.errorMessage(error));
            return null;
        } finally {
            this.busySignal.set(false);
        }
    }

    async startWorkspaceRun(
        instruction: string,
        initiator: CanvasRunInitiator = 'side-panel',
    ): Promise<ChatRunSnapshot | null> {
        if (this.busySignal()) return this.snapshotSignal();
        const document = this.workspace.getSnapshot();
        const config = getSetting<ChatConfig | null>('openrouter:config', null);
        if (!document) {
            this.errorSignal.set('Canvas requires an active narrative note.');
            return null;
        }
        if (!config?.apiKey?.trim()) {
            this.errorSignal.set('Canvas transaction requires an OpenRouter API key for the planner.');
            return null;
        }
        this.busySignal.set(true);
        this.abortController = new AbortController();
        this.cancelRequested = false;
        this.errorSignal.set(null);
        this.receiptSignal.set(null);
        this.initiatorSignal.set(initiator);
        try {
            await this.chat.init(config);
            await this.chat.addUserMessage(instruction);
            const run = await this.chat.startRun(
                instruction.trim(),
                this.runOptions(document, document.selection, config, true),
            );
            if (!run) throw new Error('Failed to create durable Canvas workspace run.');
            this.setActiveRun(run.id);
            return await this.drive(run.id);
        } catch (error) {
            this.errorSignal.set(this.errorMessage(error));
            return null;
        } finally {
            this.busySignal.set(false);
        }
    }

    async decide(approval: ChatApprovalRequest, approved: boolean): Promise<ChatRunSnapshot | null> {
        const runId = this.runIdSignal();
        if (!runId || approval.runId !== runId || this.busySignal()) return this.snapshotSignal();
        this.busySignal.set(true);
        this.abortController = new AbortController();
        this.cancelRequested = false;
        this.errorSignal.set(null);
        try {
            const decisionJson = await this.toolHost.applyApproval(
                approval,
                approved,
                this.abortController.signal,
            );
            const decision = this.parseJson(decisionJson);
            const applied = approved && decision?.['applied'] === true;
            const receipt = this.readReceipt(decision?.['receipt']);
            if (receipt) this.receiptSignal.set(receipt);

            const snapshot = await this.chat.submitApproval(
                runId,
                approval.id,
                applied,
                decisionJson,
            );
            if (!snapshot) throw new Error('Canvas approval did not return a durable snapshot.');
            this.snapshotSignal.set(snapshot);
            if (approved && !applied) {
                this.errorSignal.set(receipt?.error || String(decision?.['error'] || 'Canvas commit was not applied.'));
            }
            return await this.drive(runId);
        } catch (error) {
            this.errorSignal.set(this.errorMessage(error));
            return this.snapshotSignal();
        } finally {
            this.busySignal.set(false);
            await this.finishCancellation(runId);
        }
    }

    async decideTrusted(approval: ChatApprovalRequest): Promise<ChatRunSnapshot | null> {
        const grant = this.toolHost.trustApproval(approval);
        if (!grant) {
            this.errorSignal.set('This proposal cannot receive a trusted scoped grant.');
            return this.snapshotSignal();
        }
        await this.chat.appendRunEvent(approval.runId, {
            phase: 'policy',
            kind: 'trusted_scope_grant',
            label: `Trusted ${grant.operations.join(', ')} scope`,
            detail: `run=${grant.runId} narrative=${grant.narrativeId} notes=${grant.noteIds.join(',')}`,
            status: 'completed',
            payload: JSON.stringify({ grantId: grant.id, expiresAt: grant.expiresAt }),
        });
        return this.decide(approval, true);
    }

    async cancel(): Promise<boolean> {
        const runId = this.runIdSignal();
        if (!runId) return false;
        this.cancelRequested = true;
        this.abortController?.abort();
        if (this.busySignal()) return true;
        const cancelled = await this.chat.cancelRun(runId);
        if (cancelled) {
            this.toolHost.revokeTrustedRun(runId);
            await this.refresh();
        }
        return cancelled;
    }

    async refresh(): Promise<ChatRunSnapshot | null> {
        const runId = this.runIdSignal();
        if (!runId) return null;
        const snapshot = await this.chat.pollRun(runId);
        if (snapshot) {
            this.snapshotSignal.set(snapshot);
            this.restoreReceipt(snapshot);
        }
        return snapshot;
    }

    private async resumePersistedRun(): Promise<void> {
        await this.chat.init();
        const snapshot = await this.refresh();
        if (!snapshot) {
            this.clearActiveRun();
            return;
        }
        if (['planning', 'awaiting_tool_host', 'executing_tools', 'queued', 'gathering'].includes(snapshot.run.status)) {
            this.busySignal.set(true);
            try {
                await this.drive(snapshot.run.id);
            } finally {
                this.busySignal.set(false);
            }
        }
    }

    private async drive(runId: string): Promise<ChatRunSnapshot | null> {
        for (let attempt = 0; attempt < 120; attempt++) {
            if (this.cancelRequested) {
                await this.chat.cancelRun(runId);
                this.toolHost.revokeTrustedRun(runId);
                return await this.refresh();
            }
            const snapshot = await this.chat.pollRun(runId);
            if (!snapshot) throw new Error(`Canvas run disappeared: ${runId}`);
            this.snapshotSignal.set(snapshot);
            this.restoreReceipt(snapshot);

            switch (snapshot.run.status) {
                case 'awaiting_tool_host': {
                    const pending = snapshot.toolCalls.filter(
                        (call) => call.host === 'typescript' && call.status === 'pending_host',
                    );
                    if (!pending.length) {
                        await this.sleep(100);
                        continue;
                    }
                    const results = await Promise.all(pending.map((call) => this.toolHost.executeCall(call)));
                    const submitted = await this.chat.submitToolResults(runId, results);
                    if (submitted) this.snapshotSignal.set(submitted);
                    continue;
                }
                case 'planning':
                    await this.chat.processPlannerRun(runId);
                    await this.sleep(50);
                    continue;
                case 'queued':
                case 'gathering':
                case 'executing_tools':
                case 'streaming':
                    await this.sleep(100);
                    continue;
                case 'awaiting_approval': {
                    const pending = snapshot.approvals.filter((approval) => approval.status === 'pending');
                    let appliedTrustedGrant = false;
                    for (const approval of pending) {
                        const decisionJson = await this.toolHost.applyTrustedApproval(
                            approval,
                            this.abortController?.signal,
                        );
                        if (!decisionJson) continue;
                        const decision = this.parseJson(decisionJson);
                        const receipt = this.readReceipt(decision?.['receipt']);
                        if (receipt) this.receiptSignal.set(receipt);
                        const applied = decision?.['applied'] === true;
                        const submitted = await this.chat.submitApproval(
                            runId,
                            approval.id,
                            applied,
                            decisionJson,
                        );
                        if (submitted) this.snapshotSignal.set(submitted);
                        if (!applied) this.errorSignal.set(receipt?.error || 'Trusted transaction was not applied.');
                        appliedTrustedGrant = true;
                    }
                    if (appliedTrustedGrant) continue;
                    return snapshot;
                }
                case 'ready_to_answer':
                case 'degraded':
                    return await this.completeWithReceipt(snapshot);
                case 'cancelled':
                    this.toolHost.revokeTrustedRun(runId);
                    return snapshot;
                default:
                    return snapshot;
            }
        }
        throw new Error('Canvas run exceeded its bounded orchestration loop.');
    }

    private async completeWithReceipt(snapshot: ChatRunSnapshot): Promise<ChatRunSnapshot> {
        const receipt = this.receiptSignal();
        const message = await this.chat.startStreamingMessage();
        if (!message) throw new Error('Failed to create Canvas receipt message.');
        const summary = receipt
            ? this.formatReceipt(receipt)
            : 'Canvas run completed without a note transaction receipt.';
        await this.chat.markRunStreaming(snapshot.run.id, message.id);
        await this.chat.updateMessage(message.id, summary);
        const completed = await this.chat.completeRun(snapshot.run.id, message.id, summary) || snapshot;
        this.toolHost.revokeTrustedRun(snapshot.run.id);
        return completed;
    }

    private runOptions(
        document: NonNullable<ReturnType<EditorAgentWorkspaceService['getSnapshot']>>,
        selection: WorkspaceSelectionSnapshot,
        config: ChatConfig,
        workspaceTransaction = false,
    ): RunOptions {
        const note = this.workspace.getSnapshot();
        const currentNote = note && document.noteId === note.noteId ? note : document;
        const storeRevision = this.currentStoreRevision();
        const noteUri = this.noteUri(currentNote.noteId);
        return {
            finalProvider: 'go-openrouter',
            finalModel: config.model,
            plannerModel: config.model,
            omEnabled: false,
            plannerEnabled: true,
            workspaceEnabled: true,
            mutationsEnabled: true,
            deadlineMs: CANVAS_RUN_DEADLINE_MS,
            mutationPolicy: 'confirm',
            narrativeId: this.currentNarrativeId(),
            scopeId: this.currentNarrativeId(),
            baseSystemPrompt: this.systemPrompt(noteUri, storeRevision, document.revision, selection, workspaceTransaction),
            initialExternalContext: this.targetContext(noteUri, storeRevision, document, selection, workspaceTransaction),
            canvasTarget: {
                noteUri,
                noteId: document.noteId,
                baseRevision: storeRevision,
                editorRevision: document.revision,
                from: selection.from,
                to: selection.to,
            },
        };
    }

    private canvasPrompt(instruction: string, selection: WorkspaceSelectionSnapshot): string {
        return `${instruction.trim()}\n\nSelected text:\n${selection.text}`;
    }

    private systemPrompt(
        noteUri: string,
        storeRevision: number,
        editorRevision: number,
        selection: WorkspaceSelectionSnapshot,
        workspaceTransaction = false,
    ): string {
        if (workspaceTransaction) {
            return `You are executing one Phoenix multi-note transaction in the active narrative.
Anchor: ${noteUri}
Anchor store revision: ${storeRevision}

Read notes with app_exec, then call exactly one multi_note_proposal containing every create, rename, move, and patch operation. Every existing note operation must include its exact store revision. Patch offsets address markdown characters and should include expectedText. Never cross the active narrative, split the transaction, or claim a commit before the durable receipt.`;
        }
        return `You are executing one Phoenix Canvas note transaction.
Target: ${noteUri}
Store revision: ${storeRevision}
Editor revision: ${editorRevision}
Selected ProseMirror range: ${selection.from}-${selection.to}

Inspect the active note if needed, then call exactly one replace_text_proposal for that exact range. The replacement must contain only the edited note text. Never apply edits directly, never call save_note_proposal, and never claim the change was committed before the approval result is returned.`;
    }

    private targetContext(
        noteUri: string,
        storeRevision: number,
        document: NonNullable<ReturnType<EditorAgentWorkspaceService['getSnapshot']>>,
        selection: WorkspaceSelectionSnapshot,
        workspaceTransaction = false,
    ): string {
        return [
            `Canvas target URI: ${noteUri}`,
            `Base store revision: ${storeRevision}`,
            `Base editor revision: ${document.revision}`,
            workspaceTransaction ? 'Transaction mode: atomic multi-note workspace' : `Selected range: ${selection.from}-${selection.to}`,
            workspaceTransaction ? 'Use phx note commands to read every target before staging.' : `Selected text:\n${selection.text}`,
        ].join('\n');
    }

    private currentStoreRevision(): number {
        const note = this.noteEditorStore.currentNote();
        const current = Number(note?.version ?? note?.updatedAt ?? 0);
        if (!current) throw new Error('Active note has no durable store revision.');
        return current;
    }

    private currentNarrativeId(): string {
        return String(this.noteEditorStore.currentNote()?.narrativeId || '');
    }

    private noteUri(noteId: string): string {
        const narrative = encodeURIComponent(this.currentNarrativeId() || '__global__');
        return `note://${narrative}/${encodeURIComponent(noteId)}`;
    }

    private setActiveRun(runId: string): void {
        this.runIdSignal.set(runId);
        setSetting(ACTIVE_CANVAS_RUN_KEY, runId);
    }

    private clearActiveRun(): void {
        this.runIdSignal.set(null);
        this.snapshotSignal.set(null);
        setSetting(ACTIVE_CANVAS_RUN_KEY, null);
    }

    private restoreReceipt(snapshot: ChatRunSnapshot): void {
        for (const approval of [...snapshot.approvals].reverse()) {
            const decision = this.parseJson(approval.decisionJson);
            const receipt = this.readReceipt(decision?.['receipt']);
            if (receipt) {
                this.receiptSignal.set(receipt);
                return;
            }
        }
    }

    private readReceipt(value: unknown): CanvasHarnessReceipt | null {
        const record = value && typeof value === 'object' ? value as Record<string, unknown> : null;
        if (record?.['kind'] === CANVAS_NOTE_RECEIPT_KIND) {
            return record as unknown as CanvasTransactionReceipt;
        }
        if (record?.['kind'] === CANVAS_MULTI_NOTE_RECEIPT_KIND) {
            return record as unknown as CanvasMultiNoteReceipt;
        }
        return null;
    }

    private parseJson(value: string | undefined): Record<string, unknown> | null {
        if (!value) return null;
        try {
            const parsed = JSON.parse(value);
            return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null;
        } catch {
            return null;
        }
    }

    private formatReceipt(receipt: CanvasHarnessReceipt): string {
        const timings = receipt.timings;
        if (receipt.kind === CANVAS_MULTI_NOTE_RECEIPT_KIND) {
            return `Canvas ${receipt.status}: ${receipt.notes.length} notes · stage ${timings.stageMs.toFixed(1)} ms · commit ${timings.commitMs.toFixed(1)} ms · index ${timings.indexInvalidationMs.toFixed(1)} ms · refresh ${timings.editorRefreshMs.toFixed(1)} ms · total ${timings.totalMs.toFixed(1)} ms`;
        }
        return `Canvas ${receipt.status}: ${receipt.noteUri} ${receipt.beforeRevision} → ${receipt.afterRevision ?? 'unchanged'} · stage ${timings.stageMs.toFixed(1)} ms · commit ${timings.commitMs.toFixed(1)} ms · index ${timings.indexInvalidationMs.toFixed(1)} ms · refresh ${timings.editorRefreshMs.toFixed(1)} ms · total ${timings.totalMs.toFixed(1)} ms`;
    }

    private async finishCancellation(runId: string): Promise<void> {
        if (!this.cancelRequested) return;
        await this.chat.cancelRun(runId);
        this.toolHost.revokeTrustedRun(runId);
        await this.refresh();
    }

    private errorMessage(error: unknown): string {
        return error instanceof Error ? error.message : String(error);
    }

    private sleep(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
}
