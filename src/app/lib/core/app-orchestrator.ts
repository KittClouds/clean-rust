// src/app/lib/core/app-orchestrator.ts
// Application Boot Orchestrator
// Coordinates initialization order to prevent race conditions.

import { Injectable, signal, computed } from '@angular/core';
import { Subject, firstValueFrom, filter, race, timer } from 'rxjs';

/**
 * Boot phases in strict order.
 */
export type BootPhase =
    | 'shell'         // Phase 0: UI shell visible, spinner shown
    | 'runtime_load'  // Phase 1: Phoenix runtime loaded (not yet hydrated)
    | 'registry'      // Phase 2: SmartGraphRegistry hydrated from Dexie cache
    | 'runtime_hydrate' // Phase 3: Phoenix content recovered; optional indexes remain deferred
    | 'ready'         // Phase 4: App interactive, note can open, editor usable
    | 'background';   // Phase 5: Background hydration and sync finished

interface PhaseInfo {
    name: BootPhase;
    started: number;
    completed: number;
    duration?: number;
}

/**
 * AppOrchestrator - Singleton that coordinates boot sequence.
 *
 * Usage:
 *   await orchestrator.waitFor('registry');
 *   orchestrator.completePhase('registry');
 */
@Injectable({
    providedIn: 'root'
})
export class AppOrchestrator {
    private readonly _currentPhase = signal<BootPhase>('shell');
    readonly currentPhase = this._currentPhase.asReadonly();

    private readonly phaseComplete$ = new Subject<BootPhase>();

    private readonly phaseOrder: BootPhase[] = [
        'shell', 'runtime_load', 'registry', 'runtime_hydrate', 'ready', 'background'
    ];

    private phases: Map<BootPhase, PhaseInfo> = new Map();
    private bootStart = Date.now();
    private readyLogged = false;

    readonly isReady = computed(() => this.isPhaseAtLeast('ready'));
    readonly isRuntimeReady = computed(() => this.isPhaseAtLeast('runtime_hydrate'));
    readonly isRegistryReady = computed(() => this.isPhaseAtLeast('registry'));

    constructor() {
        this.startPhase('shell');
        console.log('[Orchestrator] Boot sequence started');
    }

    private isPhaseAtLeast(target: BootPhase): boolean {
        return this.phaseOrder.indexOf(this._currentPhase()) >= this.phaseOrder.indexOf(target);
    }

    /**
     * Start a phase (for timing).
     */
    private startPhase(phase: BootPhase): void {
        if (!this.phases.has(phase)) {
            this.phases.set(phase, {
                name: phase,
                started: Date.now(),
                completed: 0
            });
        }
    }

    /**
     * Complete a phase and advance to the next.
     */
    completePhase(phase: BootPhase): void {
        const info = this.phases.get(phase);
        if (info && info.completed === 0) {
            info.completed = Date.now();
            info.duration = info.completed - info.started;
            console.log(`[Orchestrator] ✓ Phase '${phase}' complete (${info.duration}ms)`);
        }

        const currentIndex = this.phaseOrder.indexOf(this._currentPhase());
        const completedIndex = this.phaseOrder.indexOf(phase);

        if (completedIndex >= currentIndex) {
            const nextIndex = Math.min(completedIndex + 1, this.phaseOrder.length - 1);
            const nextPhase = this.phaseOrder[nextIndex];
            this._currentPhase.set(nextPhase);
            this.startPhase(nextPhase);
        }

        this.phaseComplete$.next(phase);

        if (phase === 'ready' && !this.readyLogged) {
            this.readyLogged = true;
            const totalTime = Date.now() - this.bootStart;
            console.log(`[Orchestrator] App interactive in ${totalTime}ms`);
            this.logTimings();
        }

        if (phase === 'background') {
            const totalTime = Date.now() - this.bootStart;
            console.log(`[Orchestrator] All background tasks done in ${totalTime}ms`);
        }
    }

    /**
     * Wait for a specific phase to complete.
     * Returns immediately if already past that phase.
     */
    async waitFor(phase: BootPhase): Promise<void> {
        const targetIndex = this.phaseOrder.indexOf(phase);
        const currentIndex = this.phaseOrder.indexOf(this._currentPhase());

        if (currentIndex > targetIndex) {
            return;
        }

        const info = this.phases.get(phase);
        if (info && info.completed > 0) {
            return;
        }

        await firstValueFrom(
            race(
                this.phaseComplete$.pipe(
                    filter(p => this.phaseOrder.indexOf(p) >= targetIndex)
                ),
                timer(30000).pipe(
                    filter(() => {
                        console.error(`[Orchestrator] Timeout waiting for phase '${phase}'`);
                        return true;
                    })
                )
            )
        );
    }

    /**
     * Check if a phase is complete.
     */
    isPhaseComplete(phase: BootPhase): boolean {
        const info = this.phases.get(phase);
        return info?.completed !== undefined && info.completed > 0;
    }

    /**
     * Get current phase index for comparisons.
     */
    getPhaseIndex(phase: BootPhase): number {
        return this.phaseOrder.indexOf(phase);
    }

    /**
     * Log timing summary.
     */
    private logTimings(): void {
        console.group('[Orchestrator] Boot Timings');
        for (const phase of this.phaseOrder) {
            const info = this.phases.get(phase);
            if (info && info.duration) {
                console.log(`  ${phase}: ${info.duration}ms`);
            }
        }
        console.groupEnd();
    }

    /**
     * Reset for hot reload (dev only).
     */
    reset(): void {
        this._currentPhase.set('shell');
        this.phases.clear();
        this.bootStart = Date.now();
        this.readyLogged = false;
        this.startPhase('shell');
    }
}

// Singleton export for non-DI contexts (e.g., pretty-text-api.ts).
let _orchestratorInstance: AppOrchestrator | null = null;

export function getAppOrchestrator(): AppOrchestrator {
    if (!_orchestratorInstance) {
        throw new Error('[Orchestrator] Not yet initialized. Inject via DI.');
    }
    return _orchestratorInstance;
}

export function setAppOrchestrator(instance: AppOrchestrator): void {
    _orchestratorInstance = instance;
}
