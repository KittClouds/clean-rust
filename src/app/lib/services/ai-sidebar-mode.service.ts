import { Injectable, computed, signal } from '@angular/core';

export type AiSidebarMode = 'chat' | 'canvas';

export interface CanvasSelectionContext {
    noteId: string | null;
    from: number;
    to: number;
    text: string;
    clipId?: string;
    createdAt: number;
}

@Injectable({ providedIn: 'root' })
export class AiSidebarModeService {
    private readonly modeSignal = signal<AiSidebarMode>('chat');
    private readonly composerFocusTicketSignal = signal(0);
    private readonly selectionContextSignal = signal<CanvasSelectionContext | null>(null);

    readonly mode = computed(() => this.modeSignal());
    readonly isCanvasMode = computed(() => this.modeSignal() === 'canvas');
    readonly composerFocusTicket = computed(() => this.composerFocusTicketSignal());
    readonly selectionContext = computed(() => this.selectionContextSignal());

    setMode(mode: AiSidebarMode): void {
        this.modeSignal.set(mode);
    }

    switchToCanvas(selection?: Omit<CanvasSelectionContext, 'createdAt'>): void {
        this.modeSignal.set('canvas');
        if (selection) {
            this.selectionContextSignal.set({
                ...selection,
                createdAt: Date.now(),
            });
        }
        this.requestComposerFocus();
    }

    switchToChat(): void {
        this.modeSignal.set('chat');
        this.requestComposerFocus();
    }

    requestComposerFocus(): void {
        this.composerFocusTicketSignal.update((value) => value + 1);
    }

    setSelectionContext(selection: Omit<CanvasSelectionContext, 'createdAt'> | null): void {
        if (!selection) {
            this.selectionContextSignal.set(null);
            return;
        }
        this.selectionContextSignal.set({
            ...selection,
            createdAt: Date.now(),
        });
    }

    clearSelectionContext(): void {
        this.selectionContextSignal.set(null);
    }
}
