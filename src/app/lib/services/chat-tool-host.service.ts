import { Injectable, inject } from '@angular/core';
import { EditorAgentWorkspaceService } from './editor-agent-workspace.service';
import type { ChatApprovalRequest, ChatToolCall, ToolProposal, ToolResultSubmission } from './phoenix-chat.service';
import { parseCanvasStagedTransaction } from './canvas-note-transaction';
import { CanvasNoteTransactionService } from './canvas-note-transaction.service';
import { AppIdeCommandService } from './app-ide-command.service';
import { parseCanvasMultiNoteTransaction, type CanvasNoteOperation } from './canvas-multi-note-transaction';
import { CanvasMultiNoteTransactionService } from './canvas-multi-note-transaction.service';
import { CanvasTrustedGrantService, type CanvasTrustedGrant } from './canvas-trusted-grant.service';

@Injectable({ providedIn: 'root' })
export class ChatToolHostService {
    private readonly workspace = inject(EditorAgentWorkspaceService);
    private readonly transactions = inject(CanvasNoteTransactionService);
    private readonly appIde = inject(AppIdeCommandService);
    private readonly multiNoteTransactions = inject(CanvasMultiNoteTransactionService);
    private readonly trustedGrants = inject(CanvasTrustedGrantService);

    async executeCall(call: ChatToolCall): Promise<ToolResultSubmission> {
        try {
            const args = this.parseArgs(call.argumentsJson);
            switch (call.toolName) {
                case 'app_exec': {
                    const result = await this.appIde.execute({
                        runId: call.runId,
                        callId: call.id,
                        toolCallId: call.toolCallId,
                        command: String(args['command'] || ''),
                        profile: 'read_only',
                    });
                    return {
                        callId: call.id,
                        toolCallId: call.toolCallId,
                        resultJson: JSON.stringify(result),
                    };
                }
                case 'get_active_note_snapshot': {
                    const snapshot = this.workspace.getSnapshot();
                    if (!snapshot) return { callId: call.id, error: 'No active note/editor snapshot available.' };
                    return { callId: call.id, toolCallId: call.toolCallId, resultJson: JSON.stringify(snapshot) };
                }
                case 'get_selection': {
                    const selection = this.workspace.getSelection();
                    if (!selection) return { callId: call.id, error: 'No active editor selection available.' };
                    return { callId: call.id, toolCallId: call.toolCallId, resultJson: JSON.stringify(selection) };
                }
                case 'highlight_range': {
                    const result = this.workspace.highlightRange(
                        Number(args['from'] ?? 0),
                        Number(args['to'] ?? args['from'] ?? 0)
                    );
                    return result.ok
                        ? { callId: call.id, toolCallId: call.toolCallId, resultJson: JSON.stringify(result) }
                        : { callId: call.id, toolCallId: call.toolCallId, error: result.error || 'Failed to highlight range.' };
                }
                case 'replace_text_proposal':
                    return this.buildReplaceTextProposal(call, args);
                case 'rewrite_block_proposal':
                    return this.buildRewriteBlockProposal(call, args);
                case 'insert_text_proposal':
                    return this.buildInsertTextProposal(call, args);
                case 'save_note_proposal':
                    return this.buildSaveNoteProposal(call);
                case 'multi_note_proposal':
                    return this.buildMultiNoteProposal(call, args);
                default:
                    return { callId: call.id, toolCallId: call.toolCallId, error: `Unsupported tool: ${call.toolName}` };
            }
        } catch (err) {
            return {
                callId: call.id,
                toolCallId: call.toolCallId,
                error: err instanceof Error ? err.message : String(err),
            };
        }
    }

    async applyApproval(approval: ChatApprovalRequest, approved: boolean, signal?: AbortSignal): Promise<string> {
        const proposal = this.parseProposal(approval.proposalJson);
        if (!proposal?.payloadJson) {
            return JSON.stringify({ approved, applied: false, error: 'Missing proposal payload.' });
        }

        try {
            const payload = JSON.parse(proposal.payloadJson) as Record<string, any>;
            const multiNoteTransaction = parseCanvasMultiNoteTransaction(payload);
            if (multiNoteTransaction) {
                const result = approved
                    ? await this.multiNoteTransactions.commit(multiNoteTransaction, signal)
                    : await this.multiNoteTransactions.reject(multiNoteTransaction);
                return JSON.stringify({
                    approved,
                    applied: result.ok && result.receipt.status !== 'rejected',
                    ...result,
                });
            }
            const transaction = parseCanvasStagedTransaction(payload);
            if (transaction) {
                const result = approved
                    ? await this.transactions.commit(transaction)
                    : this.transactions.reject(transaction);
                return JSON.stringify({
                    approved,
                    applied: result.ok && result.receipt.status !== 'rejected',
                    ...result,
                });
            }
            if (!approved) {
                return JSON.stringify({ approved: false, applied: false, reason: 'User rejected proposal.' });
            }
            switch (approval.toolName) {
                case 'replace_text_proposal': {
                    const result = await this.workspace.replaceText(
                        Number(payload['from'] ?? 0),
                        Number(payload['to'] ?? 0),
                        String(payload['replacement'] ?? ''),
                        payload['expectedRevision'] ?? undefined
                    );
                    return JSON.stringify({ approved: true, applied: result.ok, ...result });
                }
                case 'rewrite_block_proposal': {
                    const result = await this.workspace.rewriteBlock(
                        Number(payload['blockIndex'] ?? -1),
                        String(payload['replacement'] ?? ''),
                        payload['expectedRevision'] ?? undefined
                    );
                    return JSON.stringify({ approved: true, applied: result.ok, ...result });
                }
                case 'insert_text_proposal': {
                    const result = await this.workspace.insertText(
                        Number(payload['pos'] ?? 0),
                        String(payload['text'] ?? ''),
                        payload['expectedRevision'] ?? undefined
                    );
                    return JSON.stringify({ approved: true, applied: result.ok, ...result });
                }
                case 'save_note_proposal': {
                    const result = await this.workspace.saveCurrentNote();
                    return JSON.stringify({ approved: true, applied: result.ok, ...result });
                }
                default:
                    return JSON.stringify({ approved: true, applied: false, error: `Unsupported proposal tool: ${approval.toolName}` });
            }
        } catch (err) {
            return JSON.stringify({
                approved: true,
                applied: false,
                error: err instanceof Error ? err.message : String(err),
            });
        }
    }

    private async buildReplaceTextProposal(call: ChatToolCall, args: Record<string, any>): Promise<ToolResultSubmission> {
        const snapshot = this.workspace.getSnapshot();
        if (!snapshot) return { callId: call.id, error: 'No active note/editor snapshot available.' };

        const from = Number(args['from'] ?? 0);
        const to = Number(args['to'] ?? from);
        const replacement = String(args['replacement'] ?? '');
        const expectedRevision = args['expectedRevision'] ?? snapshot.revision;
        return this.buildStagedReplacement(
            call,
            from,
            to,
            replacement,
            expectedRevision,
            `Replace text in ${snapshot.noteTitle || 'active note'}`,
        );
    }

    trustApproval(approval: ChatApprovalRequest): CanvasTrustedGrant | null {
        const proposal = this.parseProposal(approval.proposalJson);
        if (!proposal?.payloadJson) return null;
        try {
            const transaction = parseCanvasMultiNoteTransaction(JSON.parse(proposal.payloadJson));
            return transaction ? this.trustedGrants.issueForTransaction(transaction) : null;
        } catch {
            return null;
        }
    }

    async applyTrustedApproval(approval: ChatApprovalRequest, signal?: AbortSignal): Promise<string | null> {
        const proposal = this.parseProposal(approval.proposalJson);
        if (!proposal?.payloadJson) return null;
        try {
            const transaction = parseCanvasMultiNoteTransaction(JSON.parse(proposal.payloadJson));
            if (!transaction) return null;
            const grant = this.trustedGrants.consume(transaction);
            if (!grant.allowed) return null;
            const decision = JSON.parse(await this.applyApproval(approval, true, signal));
            return JSON.stringify({ ...decision, trustedGrantId: grant.grantId });
        } catch {
            return null;
        }
    }

    revokeTrustedRun(runId: string): void {
        this.trustedGrants.revokeRun(runId);
    }

    private buildRewriteBlockProposal(call: ChatToolCall, args: Record<string, any>): ToolResultSubmission {
        const snapshot = this.workspace.getSnapshot();
        if (!snapshot) return { callId: call.id, error: 'No active note/editor snapshot available.' };

        const blockIndex = Number(args['blockIndex'] ?? -1);
        const replacement = String(args['replacement'] ?? '');
        const expectedRevision = args['expectedRevision'] ?? snapshot.revision;
        const block = snapshot.blocks.find((item) => item.index === blockIndex);
        if (!block) return { callId: call.id, toolCallId: call.toolCallId, error: `Block ${blockIndex} not found.` };
        return this.buildStagedReplacement(
            call,
            block.from,
            block.to,
            replacement,
            expectedRevision,
            `Rewrite block ${blockIndex} in ${snapshot.noteTitle || 'active note'}`,
        );
    }

    private async buildInsertTextProposal(call: ChatToolCall, args: Record<string, any>): Promise<ToolResultSubmission> {
        const snapshot = this.workspace.getSnapshot();
        if (!snapshot) return { callId: call.id, error: 'No active note/editor snapshot available.' };

        const pos = Number(args['pos'] ?? 0);
        const text = String(args['text'] ?? '');
        const expectedRevision = args['expectedRevision'] ?? snapshot.revision;
        return this.buildStagedReplacement(
            call,
            pos,
            pos,
            text,
            expectedRevision,
            `Insert text into ${snapshot.noteTitle || 'active note'}`,
        );
    }

    private buildSaveNoteProposal(call: ChatToolCall): ToolResultSubmission {
        const snapshot = this.workspace.getSnapshot();
        if (!snapshot) return { callId: call.id, error: 'No active note/editor snapshot available.' };

        const proposal: ToolProposal = {
            proposalId: this.generateId('proposal'),
            toolName: call.toolName,
            affectedNoteId: snapshot.noteId,
            summary: `Save ${snapshot.noteTitle || 'active note'}`,
            diffPreview: 'Persist the current editor state to the note store.',
            expectedRevision: snapshot.revision,
            rollbackToken: `${snapshot.noteId}:${snapshot.revision}`,
            payloadJson: JSON.stringify({ kind: 'save_note', expectedRevision: snapshot.revision }),
        };
        return { callId: call.id, toolCallId: call.toolCallId, proposal };
    }

    private parseArgs(raw: string): Record<string, any> {
        if (!raw?.trim()) return {};
        try {
            return JSON.parse(raw) as Record<string, any>;
        } catch {
            return {};
        }
    }

    private parseProposal(raw?: string): ToolProposal | null {
        if (!raw?.trim()) return null;
        try {
            return JSON.parse(raw) as ToolProposal;
        } catch {
            return null;
        }
    }

    private async buildMultiNoteProposal(
        call: ChatToolCall,
        args: Record<string, any>,
    ): Promise<ToolResultSubmission> {
        if (!Array.isArray(args['operations'])) {
            return { callId: call.id, toolCallId: call.toolCallId, error: 'multi_note_proposal requires operations.' };
        }
        const staged = await this.multiNoteTransactions.stage(
            call.runId,
            args['operations'] as CanvasNoteOperation[],
        );
        if (!staged.ok || !staged.transaction) {
            return {
                callId: call.id,
                toolCallId: call.toolCallId,
                error: staged.error || 'Failed to stage multi-note transaction.',
            };
        }
        const transaction = staged.transaction;
        const proposal: ToolProposal = {
            proposalId: this.generateId('proposal'),
            toolName: call.toolName,
            affectedNoteId: transaction.mutations[0]?.noteId,
            summary: `Atomic ${transaction.mutations.length}-note transaction`,
            diffPreview: transaction.diffPreview,
            expectedRevision: transaction.mutations.length === 1
                ? transaction.mutations[0].expectedRevision ?? undefined
                : undefined,
            rollbackToken: transaction.checkpointArtifactKey || transaction.transactionId,
            payloadJson: JSON.stringify(transaction),
        };
        return { callId: call.id, toolCallId: call.toolCallId, proposal };
    }

    async rollbackApproval(approval: ChatApprovalRequest): Promise<string> {
        const proposal = this.parseProposal(approval.proposalJson);
        if (!proposal?.payloadJson) {
            return JSON.stringify({ rolledBack: false, error: 'Missing transaction payload.' });
        }
        try {
            const transaction = parseCanvasStagedTransaction(JSON.parse(proposal.payloadJson));
            const decision = approval.decisionJson ? JSON.parse(approval.decisionJson) : null;
            const committedRevision = Number(decision?.receipt?.afterRevision ?? decision?.afterRevision);
            if (!transaction || !Number.isFinite(committedRevision)) {
                return JSON.stringify({ rolledBack: false, error: 'Missing committed transaction receipt.' });
            }
            const result = await this.transactions.rollback(transaction, committedRevision);
            return JSON.stringify({ rolledBack: result.ok, ...result });
        } catch (error) {
            return JSON.stringify({
                rolledBack: false,
                error: error instanceof Error ? error.message : String(error),
            });
        }
    }

    private buildStagedReplacement(
        call: ChatToolCall,
        from: number,
        to: number,
        replacement: string,
        expectedRevision: number,
        summary: string,
    ): ToolResultSubmission {
        const staged = this.workspace.stageReplaceText(
            call.runId,
            from,
            to,
            replacement,
            expectedRevision,
        );
        if (!staged.ok || !staged.transaction) {
            return {
                callId: call.id,
                toolCallId: call.toolCallId,
                error: staged.error || 'Failed to stage Canvas note transaction.',
            };
        }
        const transaction = staged.transaction;
        const proposal: ToolProposal = {
            proposalId: this.generateId('proposal'),
            toolName: call.toolName,
            affectedNoteId: transaction.noteId,
            summary,
            diffPreview: transaction.diffPreview,
            expectedRevision: transaction.baseStoreRevision,
            rollbackToken: transaction.transactionId,
            payloadJson: JSON.stringify(transaction),
        };
        return { callId: call.id, toolCallId: call.toolCallId, proposal };
    }

    private generateId(prefix: string): string {
        return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
    }
}
