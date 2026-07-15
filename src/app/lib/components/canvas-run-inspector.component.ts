import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import {
    CanvasAgentRunService,
    type CanvasHarnessReceipt,
} from '../services/canvas-agent-run.service';
import type { ChatApprovalRequest } from '../services/phoenix-chat.service';

@Component({
    selector: 'app-canvas-run-inspector',
    standalone: true,
    imports: [CommonModule],
    template: `
        @if (runs.currentRunId()) {
            <section class="canvas-console" data-testid="canvas-run-inspector">
                <header>
                    <div>
                        <span class="eyebrow">AI HARNESS RUN</span>
                        <strong>{{ shortRunId(runs.currentRunId()) }}</strong>
                    </div>
                    <div class="header-actions">
                        <span class="state" [attr.data-state]="runs.status()">{{ runs.status() }}</span>
                        @if (!['completed', 'cancelled', 'failed'].includes(runs.status())) {
                            <button class="cancel" (click)="cancel()">Cancel</button>
                        }
                    </div>
                </header>

                @if (runs.error()) {
                    <div class="fault" role="alert">{{ runs.error() }}</div>
                }

                @for (approval of runs.pendingApprovals(); track approval.id) {
                    <article class="approval" data-testid="canvas-approval">
                        <div class="approval-title">
                            <span>STAGED PATCH</span>
                            <code>rev {{ approval.expectedRevision ?? 'multi' }}</code>
                        </div>
                        <p>{{ approval.summary }}</p>
                        <pre>{{ approval.diffPreview }}</pre>
                        <div class="actions">
                            <button class="reject" [disabled]="runs.busy()" (click)="decide(approval, false)">
                                Abort
                            </button>
                            <button class="commit" [disabled]="runs.busy()" (click)="decide(approval, true)">
                                Commit patch
                            </button>
                            @if (approval.toolName === 'multi_note_proposal') {
                                <button class="trust" [disabled]="runs.busy()" (click)="decideTrusted(approval)">
                                    Trust scope + commit
                                </button>
                            }
                        </div>
                    </article>
                }

                @if (runs.receipt(); as receipt) {
                    <article class="receipt" data-testid="canvas-receipt">
                        <div class="receipt-line">
                            <span>{{ receipt.status }}</span>
                            <code>{{ receiptRevision(receipt) }}</code>
                        </div>
                        <div class="uri">{{ receiptLocation(receipt) }}</div>
                        @if (receiptConflicts(receipt).length) {
                            <div class="conflicts" role="alert" data-testid="canvas-conflicts">
                                <b>ATOMIC COMMIT BLOCKED</b>
                                @for (conflict of receiptConflicts(receipt); track conflict.noteId) {
                                    <div>
                                        <code>{{ conflict.noteUri }}</code>
                                        <span>{{ conflict.reason }}</span>
                                        <code>{{ conflict.expectedRevision ?? 'absent' }} → {{ conflict.actualRevision ?? 'missing' }}</code>
                                    </div>
                                }
                            </div>
                        }
                        <div class="timings">
                            <span>stage {{ fixed(receipt.timings.stageMs) }}ms</span>
                            <span>commit {{ fixed(receipt.timings.commitMs) }}ms</span>
                            <span>index {{ fixed(receipt.timings.indexInvalidationMs) }}ms</span>
                            <span>refresh {{ fixed(receipt.timings.editorRefreshMs) }}ms</span>
                            <span>total {{ fixed(receipt.timings.totalMs) }}ms</span>
                        </div>
                    </article>
                }

                @if (!runs.pendingApprovals().length && !runs.receipt()) {
                    <div class="trace">
                        @for (event of recentEvents(); track event.id) {
                            <div>
                                <i [attr.data-status]="event.status"></i>
                                <code class="sequence">#{{ event.sequence }}</code>
                                <span>{{ event.label }}</span>
                                @if (event.latencyMs !== undefined) { <code>{{ event.latencyMs }}ms</code> }
                            </div>
                        }
                    </div>
                }

                @if (recentArtifacts().length) {
                    <div class="artifacts" data-testid="harness-artifacts">
                        <span class="artifact-heading">DURABLE ARTIFACTS</span>
                        @for (artifact of recentArtifacts(); track artifact.key) {
                            <div>
                                <code>{{ artifact.kind }}</code>
                                <span>artifact://{{ artifact.key }}</span>
                                @if (artifact.pinned) { <b>PIN</b> }
                            </div>
                        }
                    </div>
                }
            </section>
        }
    `,
    styles: [`
        :host { display: block; }
        .canvas-console {
            --mint: #6ee7d2; --ink: #07110f; margin: .65rem;
            border: 1px solid color-mix(in srgb, var(--mint) 28%, transparent); border-radius: 10px;
            overflow: hidden; color: #d7e5e2; box-shadow: 0 14px 40px rgba(0, 0, 0, .28);
            background: linear-gradient(90deg, rgba(110, 231, 210, .045) 1px, transparent 1px) 0 0 / 18px 18px, #0b1111;
            font-family: "IBM Plex Mono", "Cascadia Code", monospace;
        }
        header, .header-actions, .approval-title, .receipt-line, .actions { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
        header { padding: .7rem .8rem; border-bottom: 1px solid rgba(110, 231, 210, .14); }
        header > div:first-child { display: grid; gap: .12rem; }
        header strong { color: #f4fffc; font-size: .72rem; font-weight: 600; }
        .eyebrow, .approval-title span { color: var(--mint); font-size: .58rem; letter-spacing: .15em; }
        .state { padding: .22rem .46rem; border: 1px solid rgba(110, 231, 210, .22); border-radius: 999px; font-size: .6rem; text-transform: uppercase; }
        .state[data-state="awaiting_approval"] { color: #ffd384; border-color: rgba(255, 211, 132, .4); }
        .fault { margin: .65rem; padding: .6rem; border-left: 2px solid #fb7185; background: rgba(251, 113, 133, .08); color: #fecdd3; font-size: .69rem; }
        .approval, .receipt { margin: .65rem; padding: .75rem; border: 1px solid rgba(255, 255, 255, .09); border-radius: 7px; background: rgba(2, 8, 7, .78); }
        .approval-title code, .receipt-line code { color: #9db1ad; font-size: .63rem; }
        p { margin: .65rem 0; font: 500 .75rem/1.45 "IBM Plex Sans", sans-serif; }
        pre { max-height: 15rem; overflow: auto; margin: 0; padding: .7rem; border-radius: 5px; background: #050909; color: #c9d8d5; font-size: .66rem; line-height: 1.5; white-space: pre-wrap; }
        .actions { margin-top: .7rem; justify-content: flex-end; flex-wrap: wrap; }
        button { padding: .42rem .65rem; border-radius: 5px; border: 1px solid transparent; font: 600 .66rem "IBM Plex Mono", monospace; cursor: pointer; }
        button:disabled { opacity: .45; cursor: wait; }
        .reject, .cancel { color: #fda4af; border-color: rgba(253, 164, 175, .25); background: transparent; }
        .cancel { padding: .25rem .42rem; }
        .commit { color: var(--ink); background: var(--mint); }
        .trust { color: #171003; background: #ffd384; }
        .receipt { border-color: rgba(110, 231, 210, .28); }
        .receipt-line span { color: var(--mint); text-transform: uppercase; font-size: .68rem; }
        .uri { margin-top: .45rem; color: #a5b8b4; font-size: .62rem; overflow-wrap: anywhere; }
        .timings { display: flex; flex-wrap: wrap; gap: .3rem .7rem; margin-top: .65rem; color: #81938f; font-size: .58rem; }
        .conflicts { display: grid; gap: .4rem; margin-top: .65rem; padding: .6rem; border-left: 2px solid #fb7185; background: rgba(251, 113, 133, .07); }
        .conflicts > b { color: #fda4af; font-size: .55rem; letter-spacing: .12em; }
        .conflicts > div { display: grid; grid-template-columns: 1fr auto auto; gap: .5rem; color: #fecdd3; font-size: .58rem; }
        .trace { display: grid; gap: .4rem; padding: .7rem .8rem; }
        .trace > div { display: grid; grid-template-columns: 8px auto 1fr auto; align-items: center; gap: .45rem; font-size: .64rem; }
        .trace i { width: 6px; height: 6px; border-radius: 50%; background: #5eead4; box-shadow: 0 0 9px rgba(94, 234, 212, .55); }
        .trace i[data-status="running"] { animation: pulse 1.15s infinite; }
        .trace code { color: #70827e; } .trace .sequence { color: #52706a; font-size: .55rem; }
        .artifacts { display: grid; gap: .35rem; padding: .7rem .8rem; border-top: 1px solid rgba(110, 231, 210, .12); background: rgba(2, 8, 7, .5); }
        .artifact-heading { color: var(--mint); font-size: .55rem; letter-spacing: .14em; }
        .artifacts > div { display: grid; grid-template-columns: minmax(7rem, auto) 1fr auto; gap: .5rem; align-items: center; min-width: 0; font-size: .57rem; }
        .artifacts code { color: #9db1ad; } .artifacts span { color: #667c77; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .artifacts b { color: #ffd384; font-size: .5rem; letter-spacing: .08em; }
        @keyframes pulse { 50% { opacity: .3; transform: scale(.72); } }
    `],
})
export class CanvasRunInspectorComponent {
    readonly runs = inject(CanvasAgentRunService);

    recentEvents() { return (this.runs.snapshot()?.events || []).slice(-6); }
    recentArtifacts() { return (this.runs.snapshot()?.artifacts || []).slice(-4); }
    decide(approval: ChatApprovalRequest, approved: boolean): void { void this.runs.decide(approval, approved); }
    decideTrusted(approval: ChatApprovalRequest): void { void this.runs.decideTrusted(approval); }
    cancel(): void { void this.runs.cancel(); }
    shortRunId(runId: string | null): string { return runId ? runId.slice(-18) : ''; }
    fixed(value: number): string { return Number(value || 0).toFixed(1); }

    receiptRevision(receipt: CanvasHarnessReceipt): string {
        if ('notes' in receipt) return `${receipt.notes.length} note${receipt.notes.length === 1 ? '' : 's'}`;
        return `${receipt.beforeRevision} → ${receipt.afterRevision ?? 'unchanged'}`;
    }

    receiptLocation(receipt: CanvasHarnessReceipt): string {
        return 'notes' in receipt ? `narrative://${receipt.narrativeId}` : receipt.noteUri;
    }

    receiptConflicts(receipt: CanvasHarnessReceipt) {
        return 'conflicts' in receipt ? receipt.conflicts : [];
    }
}
