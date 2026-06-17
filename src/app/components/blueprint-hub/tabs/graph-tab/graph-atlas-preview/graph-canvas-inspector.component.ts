import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Anchor, Check, Crosshair, FileSearch, Palette, VolumeX, X, XCircle } from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import type {
    GraphCanvasInspectorRecord,
    GraphCanvasReviewDecision,
    GraphCanvasReviewRequest,
    GraphCanvasSourceRequest,
} from './graph-canvas-interaction';

@Component({
    selector: 'app-graph-canvas-inspector',
    standalone: true,
    imports: [CommonModule, LucideAngularModule],
    template: `
        @if (record || batchRecords.length) {
        <aside class="canvas-inspector" aria-label="Graph selection details">
            <header class="inspector-header">
                <div class="min-w-0">
                    <p class="inspector-kicker">{{ batchRecords.length ? 'Batch review' : objectKindLabel(record) }}</p>
                    <h3>{{ batchRecords.length ? batchRecords.length + ' selected objects' : record?.title }}</h3>
                    @if (!batchRecords.length && record?.subtitle) {
                    <p class="inspector-subtitle">{{ record?.subtitle }}</p>
                    }
                </div>
                <button type="button" class="icon-button" title="Close inspector" (click)="close.emit()">
                    <lucide-icon [img]="XIcon" class="h-4 w-4"></lucide-icon>
                </button>
            </header>

            @if (batchRecords.length) {
            <div class="batch-list">
                @for (item of batchRecords.slice(0, 40); track item.id) {
                <button type="button" class="batch-row" (click)="focusRequested.emit(item.focusNodeIds)">
                    <span class="batch-dot" [attr.data-state]="item.status"></span>
                    <span class="min-w-0 flex-1">
                        <strong>{{ item.title }}</strong>
                        <small>{{ item.subtitle }} · {{ item.status }}</small>
                    </span>
                    @if (item.confidence !== null) {
                    <span class="confidence">{{ item.confidence | percent:'1.0-0' }}</span>
                    }
                </button>
                }
            </div>
            } @else if (record; as item) {
            <div class="status-strip">
                <span class="status-pill" [attr.data-state]="item.status">{{ item.status }}</span>
                @if (item.confidence !== null) {
                <span>{{ item.confidence | percent:'1.0-0' }} confidence</span>
                }
                @if (item.styleKey) {
                <span>Style key: {{ item.styleKey }}</span>
                }
                @if (item.detector) {
                <span>{{ item.detector }}</span>
                }
            </div>

            @if (item.sourceSnippet) {
            <section class="inspector-section source-preview">
                <p class="section-label">Source</p>
                <blockquote>{{ item.sourceSnippet }}</blockquote>
                @if (item.noteId && item.sourceStart !== null && item.sourceEnd !== null) {
                <button type="button" class="text-action" (click)="jumpToSource(item)">
                    <lucide-icon [img]="FileSearchIcon" class="h-4 w-4"></lucide-icon>
                    Jump to span {{ item.sourceStart }}-{{ item.sourceEnd }}
                </button>
                }
            </section>
            }

            @if (item.reasons.length) {
            <section class="inspector-section">
                <p class="section-label">Why proposed</p>
                @for (reason of item.reasons; track reason) {
                <p class="reason-row">{{ reason }}</p>
                }
            </section>
            }

            @if (item.graphImpact) {
            <section class="inspector-section">
                <p class="section-label">Graph impact</p>
                <p class="body-copy">{{ item.graphImpact }}</p>
            </section>
            }

            @if (item.members.length) {
            <section class="inspector-section">
                <p class="section-label">Members</p>
                <div class="member-list">
                    @for (member of item.members.slice(0, 36); track member.id) {
                    <button type="button" class="member-row" (click)="focusRequested.emit([member.id])">
                        <span>{{ member.label }}</span><small>{{ member.kind }}</small>
                    </button>
                    }
                </div>
            </section>
            }

            @if (item.evidenceIds.length || item.relatedEntityIds.length) {
            <section class="inspector-section evidence-grid">
                <div><span>{{ item.evidenceIds.length }}</span><small>evidence</small></div>
                <div><span>{{ item.relatedEntityIds.length }}</span><small>entities</small></div>
                <div><span>{{ item.memberIds.length }}</span><small>members</small></div>
            </section>
            }

            <button type="button" class="focus-button" (click)="focusRequested.emit(item.focusNodeIds)">
                <lucide-icon [img]="CrosshairIcon" class="h-4 w-4"></lucide-icon>
                Focus on canvas
            </button>
            @if (item.styleKey) {
            <button type="button" class="style-button" (click)="styleRequested.emit(item.styleKey)">
                <lucide-icon [img]="PaletteIcon" class="h-4 w-4"></lucide-icon>
                Style selected kind
            </button>
            }
            }

            @if (reviewObjectIds().length) {
            <footer class="review-actions" [class.review-actions-busy]="busy">
                @if (canReview('accept_fact')) {
                <button type="button" class="review-button accept" [disabled]="busy" (click)="review('accepted')" title="Accept selected facts">
                    <lucide-icon [img]="CheckIcon" class="h-4 w-4"></lucide-icon><span>Accept</span>
                </button>
                }
                @if (canReview('reject_fact')) {
                <button type="button" class="review-button reject" [disabled]="busy" (click)="review('rejected')" title="Reject selected facts">
                    <lucide-icon [img]="RejectIcon" class="h-4 w-4"></lucide-icon><span>Reject</span>
                </button>
                }
                @if (canReview('mute_detector_pattern')) {
                <button type="button" class="review-button" [disabled]="busy" (click)="review('muted')" title="Mute detector pattern">
                    <lucide-icon [img]="MuteIcon" class="h-4 w-4"></lucide-icon><span>Mute</span>
                </button>
                }
                @if (canReview('promote_sidecar_to_anchor')) {
                <button type="button" class="review-button promote" [disabled]="busy" (click)="review('promoted_to_anchor')" title="Promote to user anchor">
                    <lucide-icon [img]="AnchorIcon" class="h-4 w-4"></lucide-icon><span>Promote</span>
                </button>
                }
            </footer>
            }
        </aside>
        }
    `,
    styles: [`
        :host { display: contents; }
        .canvas-inspector { position: absolute; z-index: 42; top: 4.75rem; right: 1rem; bottom: 1rem; width: min(370px, calc(100% - 2rem)); overflow: auto; border: 1px solid rgba(94,234,212,.19); background: rgba(5,8,14,.94); box-shadow: 0 22px 70px rgba(0,0,0,.58); backdrop-filter: blur(22px); color: #e4e4e7; }
        .inspector-header { position: sticky; top: 0; z-index: 2; display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; padding: 1rem; border-bottom: 1px solid rgba(255,255,255,.08); background: rgba(5,8,14,.96); }
        .inspector-kicker,.section-label { margin: 0; color: #5eead4; font-size: .65rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
        h3 { margin: .22rem 0 0; color: white; font-size: 1.08rem; line-height: 1.25; }
        .inspector-subtitle { margin: .3rem 0 0; color: #a1a1aa; font-size: .75rem; }
        .icon-button { display: grid; width: 2rem; height: 2rem; place-items: center; border: 1px solid rgba(255,255,255,.1); background: #090b10; color: #a1a1aa; }
        .icon-button:hover { border-color: rgba(94,234,212,.4); color: white; }
        .status-strip { display: flex; flex-wrap: wrap; gap: .45rem; padding: .8rem 1rem; border-bottom: 1px solid rgba(255,255,255,.06); color: #71717a; font-size: .67rem; text-transform: uppercase; }
        .status-pill { padding: .2rem .48rem; border: 1px solid rgba(94,234,212,.22); color: #99f6e4; }
        .status-pill[data-state="rejected"],.batch-dot[data-state="rejected"] { border-color: #fb7185; color: #fda4af; background: #fb7185; }
        .status-pill[data-state="proposed"],.batch-dot[data-state="proposed"] { border-color: #facc15; color: #fde047; background: #facc15; }
        .inspector-section { margin: 0 1rem; padding: .9rem 0; border-bottom: 1px solid rgba(255,255,255,.07); }
        blockquote { margin: .55rem 0 .65rem; color: #d4d4d8; font-size: .82rem; line-height: 1.55; }
        .text-action,.focus-button,.style-button { display: inline-flex; align-items: center; gap: .45rem; border: 1px solid rgba(94,234,212,.2); background: rgba(20,184,166,.08); color: #99f6e4; font-size: .72rem; font-weight: 700; }
        .text-action { padding: .48rem .62rem; }
        .focus-button { margin: 1rem; padding: .62rem .8rem; }
        .style-button { margin: 0 1rem 1rem; padding: .62rem .8rem; border-color: rgba(168,85,247,.24); background: rgba(88,28,135,.18); color: #ddd6fe; }
        .reason-row,.body-copy { margin: .45rem 0 0; color: #a1a1aa; font-size: .77rem; line-height: 1.45; }
        .reason-row::before { content: ''; display: inline-block; width: .38rem; height: 1px; margin-right: .5rem; vertical-align: middle; background: #2dd4bf; }
        .member-list,.batch-list { display: grid; gap: .35rem; }
        .batch-list { padding: .7rem; max-height: 48%; overflow: auto; border-bottom: 1px solid rgba(255,255,255,.07); }
        .member-row,.batch-row { display: flex; width: 100%; align-items: center; gap: .6rem; border: 1px solid rgba(255,255,255,.07); background: rgba(255,255,255,.025); padding: .55rem .65rem; text-align: left; color: #d4d4d8; }
        .member-row:hover,.batch-row:hover { border-color: rgba(94,234,212,.25); background: rgba(20,184,166,.06); }
        .member-row span,.batch-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .75rem; }
        .member-row small,.batch-row small { display: block; color: #71717a; font-size: .62rem; text-transform: uppercase; }
        .batch-dot { width: .42rem; height: .42rem; flex: none; border-radius: 50%; background: #2dd4bf; }
        .confidence { flex: none; color: #99f6e4; font-size: .68rem; font-weight: 800; }
        .evidence-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: .5rem; }
        .evidence-grid div { border-left: 1px solid rgba(94,234,212,.25); padding-left: .55rem; }
        .evidence-grid span { display: block; color: white; font-size: 1rem; font-weight: 800; }
        .evidence-grid small { color: #71717a; font-size: .6rem; letter-spacing: .1em; text-transform: uppercase; }
        .review-actions { position: sticky; bottom: 0; display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .45rem; padding: .75rem; border-top: 1px solid rgba(255,255,255,.08); background: rgba(5,8,14,.97); }
        .review-button { display: inline-flex; min-height: 2.4rem; align-items: center; justify-content: center; gap: .42rem; border: 1px solid rgba(255,255,255,.1); background: #0b0e14; color: #d4d4d8; font-size: .72rem; font-weight: 800; }
        .review-button.accept { border-color: rgba(45,212,191,.3); color: #99f6e4; }
        .review-button.reject { border-color: rgba(251,113,133,.3); color: #fda4af; }
        .review-button.promote { border-color: rgba(250,204,21,.3); color: #fde047; }
        .review-button:disabled { cursor: wait; opacity: .45; }
    `],
})
export class GraphCanvasInspectorComponent {
    @Input() record: GraphCanvasInspectorRecord | null = null;
    @Input() batchRecords: GraphCanvasInspectorRecord[] = [];
    @Input() busy = false;
    @Output() close = new EventEmitter<void>();
    @Output() focusRequested = new EventEmitter<string[]>();
    @Output() styleRequested = new EventEmitter<string>();
    @Output() sourceRequested = new EventEmitter<GraphCanvasSourceRequest>();
    @Output() reviewRequested = new EventEmitter<GraphCanvasReviewRequest>();

    readonly XIcon = X;
    readonly CheckIcon = Check;
    readonly RejectIcon = XCircle;
    readonly MuteIcon = VolumeX;
    readonly AnchorIcon = Anchor;
    readonly CrosshairIcon = Crosshair;
    readonly FileSearchIcon = FileSearch;
    readonly PaletteIcon = Palette;

    objectKindLabel(record: GraphCanvasInspectorRecord | null): string {
        return record ? `${record.objectKind} detail` : 'Graph detail';
    }

    reviewObjectIds(): string[] {
        const records = this.batchRecords.length ? this.batchRecords : (this.record ? [this.record] : []);
        return [...new Set(records.flatMap((record) => record.reviewObjectIds))];
    }

    canReview(action: string): boolean {
        const records = this.batchRecords.length ? this.batchRecords : (this.record ? [this.record] : []);
        return records.some((record) => record.reviewActions.includes(action));
    }

    review(decision: GraphCanvasReviewDecision): void {
        const objectIds = this.reviewObjectIds();
        if (objectIds.length) this.reviewRequested.emit({ objectIds, decision });
    }

    jumpToSource(record: GraphCanvasInspectorRecord): void {
        if (!record.noteId || record.sourceStart === null || record.sourceEnd === null) return;
        this.sourceRequested.emit({ noteId: record.noteId, sourceStart: record.sourceStart, sourceEnd: record.sourceEnd });
    }
}
