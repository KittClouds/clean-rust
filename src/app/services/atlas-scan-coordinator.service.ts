import { Injectable, computed, signal } from '@angular/core';

import type { PhoenixMachineModelId } from './phoenix-machine-control.service';
import type {
    AtlasRichScanPolicy,
    AtlasRichScanResult as NativeAtlasRichScanResult,
} from './phoenix-ui-api.service';
import type { AtlasBuildScope } from './atlas-capability-runtime.model';
import {
    ATLAS_RICH_SCAN_QUARANTINE_MESSAGE,
    rejectAtlasRichScan,
} from './atlas-rich-scan-quarantine';

export type AtlasScanPhase = 'idle' | 'error';

export interface AtlasScanResult {
    scanId: string;
    startedAt: number;
    completedAt: number;
    durationMs: number;
    scannedNoteId?: string;
    candidateSuggestions: number;
    exportableMentions: number;
    indexedDocuments: number;
    relationCandidates: number;
    nativeResult: NativeAtlasRichScanResult;
    mode: 'rich-embeddings' | 'text-graph';
}

export interface AtlasScanOptions {
    source?: 'search-panel' | 'graph-tab' | 'sidebar' | 'canvas';
    requireActiveNote?: boolean;
    lensMode?: 'global' | 'narrative' | 'note' | 'multiNote';
    buildScope?: AtlasBuildScope;
    noteIds?: string[];
    modelId?: PhoenixMachineModelId;
    modelLabel?: string;
    dimensionLabel?: string;
    policy?: AtlasRichScanPolicy;
    includeSemanticAtlas?: boolean;
}

/**
 * Dormant compatibility facade for stale callers.
 *
 * This service deliberately injects no runtime, store, model, or graph dependency.
 * It cannot initialize the retired pipeline and every execution attempt fails closed.
 */
@Injectable({ providedIn: 'root' })
export class AtlasScanCoordinatorService {
    readonly phase = signal<AtlasScanPhase>('idle');
    readonly message = signal<string | null>(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
    readonly error = signal<string | null>(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
    readonly lastResult = signal<AtlasScanResult | null>(null);
    readonly running = computed(() => false);

    async runRichEmbeddingScan(_options: AtlasScanOptions = {}): Promise<AtlasScanResult> {
        return rejectAtlasRichScan();
    }

    clear(): void {
        this.phase.set('idle');
    }
}
