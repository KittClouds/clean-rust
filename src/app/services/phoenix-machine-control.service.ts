import { Injectable, computed, inject, signal } from '@angular/core';

import { PhoenixGraphOrchestratorService, type PhoenixGraphIndexPolicy } from './phoenix-graph-orchestrator.service';
import { PhoenixMachineControllerService } from './phoenix-machine-controller.service';
import { PhoenixUiApiService, type AtlasRichScanResult, type SearchScope } from './phoenix-ui-api.service';
import { GraphAuditService } from './graph-audit.service';
import type { GraphAuditSnapshot } from './graph-audit.model';
import type { AtlasManifoldMode, PhoenixMachineManifoldStatus } from './manifold-atlas.types';
import {
    RetrievalWorkbenchStateService,
    type RetrievalGraphFocus,
    type RetrievalGraphLensMode,
    type RetrievalLane,
} from './retrieval-workbench-state.service';

export type PhoenixMachineVectorStatus = 'idle' | 'loading' | 'ready' | 'indexing' | 'error';
export type PhoenixMachineGraphStatus = 'idle' | 'building' | 'ready' | 'searching' | 'error';
export type PhoenixMachineModelId = 'mongodb-leaf-mt' | 'bge-small-en' | 'jina-v5-nano-retrieval';
export type PhoenixMachineManifoldStatusMap = Record<AtlasManifoldMode, PhoenixMachineManifoldStatus>;
export interface PhoenixMachineManifoldLoad {
    mode: AtlasManifoldMode;
    startedAt: number;
    loadId: number;
}

const INITIAL_MANIFOLD_STATUSES: PhoenixMachineManifoldStatusMap = {
    hybrid: 'idle',
    hopf: 'idle',
    lorentz: 'idle',
    product: 'idle',
    siegel: 'idle',
};
const INITIAL_MANIFOLD_LOAD_IDS: Record<AtlasManifoldMode, number> = {
    hybrid: 0,
    hopf: 0,
    lorentz: 0,
    product: 0,
    siegel: 0,
};

export interface PhoenixMachineSemanticDocument {
    id: string;
    narrativeId: string;
    title: string;
    content: string;
}

export interface PhoenixMachineSummary {
    kind: 'search' | 'graph-update' | 'graph-rebuild' | 'semantic-load' | 'semantic-index' | 'audit' | 'graph-focus' | 'atlas-rich-scan' | 'manifold-load';
    label: string;
    startedAt: number;
    completedAt: number;
    durationMs: number;
    details?: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class PhoenixMachineControlService {
    private readonly workbench = inject(RetrievalWorkbenchStateService);
    private readonly phoenixUiApi = inject(PhoenixUiApiService);
    private readonly graphOrchestrator = inject(PhoenixGraphOrchestratorService);
    private readonly graphAuditService = inject(GraphAuditService);
    private readonly machineController = inject(PhoenixMachineControllerService);
    private manifoldLoadSeq = 0;
    private readonly manifoldLoadIds: Record<AtlasManifoldMode, number> = { ...INITIAL_MANIFOLD_LOAD_IDS };

    readonly query = this.workbench.query;
    readonly scope = this.workbench.scope;
    readonly lanes = this.workbench.lanes;
    readonly activeLanes = this.workbench.activeLanes;
    readonly graphFocus = this.workbench.graphFocus;
    readonly graphLensMode = this.workbench.graphLensMode;
    readonly stages = this.machineController.stages;
    readonly activeSignals = this.machineController.activeSignals;

    readonly vectorStatus = signal<PhoenixMachineVectorStatus>('idle');
    readonly graphStatus = signal<PhoenixMachineGraphStatus>('idle');
    readonly graphAudit = signal<GraphAuditSnapshot | null>(null);
    readonly manifoldMode = signal<AtlasManifoldMode>('hybrid');
    readonly manifoldStatuses = signal<PhoenixMachineManifoldStatusMap>({ ...INITIAL_MANIFOLD_STATUSES });
    readonly manifoldStatus = computed(() => this.manifoldStatuses()[this.manifoldMode()]);
    readonly notice = signal<string | null>(null);
    readonly error = signal<string | null>(null);
    readonly activeJob = signal<PhoenixMachineSummary['kind'] | null>(null);
    readonly lastSummary = signal<PhoenixMachineSummary | null>(null);

    readonly graphNodes = computed(() => this.graphAudit()?.graphNodes || 0);
    readonly graphEdges = computed(() => this.graphAudit()?.graphEdges || 0);
    readonly registryEntities = computed(() => this.graphAudit()?.registryEntities || 0);
    readonly liveDocuments = computed(() => this.graphAudit()?.liveDocuments || 0);
    readonly indexedDocuments = computed(() => this.graphAudit()?.indexedDocuments || 0);
    readonly staleDocuments = computed(() => this.graphAudit()?.staleDocuments || 0);
    readonly graphIssueCount = computed(() =>
        (this.graphAudit()?.orphanEdges || 0) + (this.graphAudit()?.duplicateEdges || 0)
    );
    readonly hasCommittedGraph = computed(() => this.graphNodes() > 0 || this.graphEdges() > 0);

    setScope(scope: 'global' | string): void {
        this.scope.set(scope || 'global');
    }

    setLane(lane: RetrievalLane, enabled: boolean): void {
        this.workbench.setLane(lane, enabled);
    }

    toggleLane(lane: RetrievalLane): void {
        this.workbench.toggleLane(lane);
    }

    setGraphLensMode(mode: RetrievalGraphLensMode): void {
        this.workbench.setGraphLensMode(mode);
    }

    setManifoldMode(mode: AtlasManifoldMode): void {
        if (this.manifoldMode() === mode) return;
        this.manifoldMode.set(mode);
    }

    beginManifoldLoad(mode = this.manifoldMode()): PhoenixMachineManifoldLoad {
        const startedAt = this.beginJob('manifold-load');
        const loadId = ++this.manifoldLoadSeq;
        this.manifoldLoadIds[mode] = loadId;
        this.setManifoldStatus(mode, 'loading');
        this.error.set(null);
        return { mode, startedAt, loadId };
    }

    isCurrentManifoldLoad(load: PhoenixMachineManifoldLoad): boolean {
        return this.manifoldLoadIds[load.mode] === load.loadId;
    }

    finishManifoldLoad(load: PhoenixMachineManifoldLoad, label: string, details?: Record<string, unknown>): void {
        if (!this.isCurrentManifoldLoad(load)) return;
        this.manifoldLoadIds[load.mode] = 0;
        this.setManifoldStatus(load.mode, 'ready');
        this.recordSummary('manifold-load', label, load.startedAt, { manifold: load.mode, ...details });
        if (!this.hasLoadingManifold() && this.activeJob() === 'manifold-load') {
            this.activeJob.set(null);
        }
    }

    failManifoldLoad(load: PhoenixMachineManifoldLoad, err: unknown): void {
        if (!this.isCurrentManifoldLoad(load)) return;
        this.manifoldLoadIds[load.mode] = 0;
        this.setManifoldStatus(load.mode, 'error');
        this.failJob(err, false);
    }

    requestGraphFocus(focus: Omit<RetrievalGraphFocus, 'requestedAt'>): void {
        const startedAt = performance.now();
        this.workbench.requestGraphFocus(focus);
        this.recordSummary('graph-focus', focus.title || focus.query || 'Graph focus', startedAt, {
            scope: focus.scope,
            noteId: focus.noteId,
        });
    }

    async search(query: string, limit: number, scope?: SearchScope): Promise<any[]> {
        const startedAt = this.beginJob('search');
        const shouldMarkGraph = this.activeLanes().includes('graph') && this.hasCommittedGraph();
        if (shouldMarkGraph) this.graphStatus.set('searching');

        try {
            const results = await this.phoenixUiApi.searchScoped(query, limit, scope);
            if (this.graphStatus() === 'searching') this.graphStatus.set('ready');
            this.finishJob('search', `Search returned ${results.length} hits`, startedAt, { resultCount: results.length });
            return results;
        } catch (err) {
            if (this.graphStatus() === 'searching') this.graphStatus.set('error');
            this.failJob(err);
            throw err;
        }
    }

    async loadSemanticModel(modelId: PhoenixMachineModelId, label: string, dimensionLabel: string): Promise<void> {
        const startedAt = this.beginJob('semantic-load');
        this.machineController.beginStage('embeddings', 'semantic-load');
        this.vectorStatus.set('loading');
        this.error.set(null);

        try {
            this.vectorStatus.set('ready');
            this.machineController.finishStage('embeddings', 'semantic-load');
            this.notice.set(`${label} selected at ${dimensionLabel}. Native Rust semantic runner will execute during Atlas scan.`);
            this.finishJob('semantic-load', `${label} selected`, startedAt, {
                modelId,
                dimensionLabel,
                runner: 'native-rust',
            });
        } catch (err) {
            this.vectorStatus.set('error');
            this.machineController.failStage('embeddings', 'semantic-load', err);
            this.failJob(err);
            throw err;
        }
    }

    async indexSemanticDocuments(documents: PhoenixMachineSemanticDocument[]): Promise<void> {
        const startedAt = this.beginJob('semantic-index');
        this.machineController.beginStage('embeddings', 'semantic-index');
        this.vectorStatus.set('indexing');
        this.error.set(null);

        try {
            this.vectorStatus.set('ready');
            this.machineController.finishStage('embeddings', 'semantic-index');
            this.notice.set(`Native semantic sidecar is ready for ${documents.length} selected note${documents.length === 1 ? '' : 's'}. Run Semantic Graph to embed via Rust.`);
            this.finishJob('semantic-index', `Prepared ${documents.length} native semantic documents`, startedAt, {
                documentCount: documents.length,
                runner: 'native-rust',
            });
        } catch (err) {
            this.vectorStatus.set('error');
            this.machineController.failStage('embeddings', 'semantic-index', err);
            this.failJob(err);
            throw err;
        }
    }

    async runGraphIndex(policy: PhoenixGraphIndexPolicy, reason: string): Promise<number> {
        const kind = policy === 'force' ? 'graph-rebuild' : 'graph-update';
        const startedAt = this.beginJob(kind);
        this.machineController.beginStage('evidenceGraph', kind);
        this.machineController.beginStage('overgraph', kind);
        this.graphStatus.set('building');
        this.error.set(null);
        this.notice.set(null);

        try {
            const scope = this.scope();
            const result = scope === 'global'
                ? await this.graphOrchestrator.indexGlobal({ policy, syncGraph: true, reason })
                : await this.graphOrchestrator.indexFolder(scope, { policy, syncGraph: true, reason });
            this.phoenixUiApi.invalidateKnowledgeGraphCache();
            await this.refreshAuditSafe();
            this.graphStatus.set('ready');
            this.machineController.finishStage('evidenceGraph', kind);
            this.machineController.finishStage('overgraph', kind);
            this.notice.set(`Graph ${policy === 'force' ? 'rebuilt' : 'updated'} for ${result.processedNotes} notes.`);
            this.finishJob(kind, this.notice() || 'Graph index complete', startedAt, {
                processedNotes: result.processedNotes,
                skippedNotes: result.skippedNotes,
                scope,
            });
            return result.processedNotes;
        } catch (err) {
            this.graphStatus.set('error');
            this.machineController.failStage('evidenceGraph', kind, err);
            this.machineController.failStage('overgraph', kind, err);
            this.failJob(err);
            throw err;
        }
    }

    async refreshAuditSafe(): Promise<void> {
        const startedAt = this.beginJob('audit');
        try {
            const snapshot = await this.graphAuditService.snapshot(this.auditScope());
            this.graphAudit.set(snapshot);
            if (this.graphStatus() === 'idle' && (snapshot.graphNodes > 0 || snapshot.graphEdges > 0)) {
                this.graphStatus.set('ready');
            }
            this.finishJob('audit', 'Graph audit refreshed', startedAt, {
                nodes: snapshot.graphNodes,
                edges: snapshot.graphEdges,
                issues: snapshot.orphanEdges + snapshot.duplicateEdges,
            });
        } catch (err) {
            this.graphAudit.set(null);
            this.failJob(err, false);
        }
    }

    beginAtlasRichScan(reason = 'atlas-rich-scan'): number {
        const startedAt = this.beginJob('atlas-rich-scan');
        this.error.set(null);
        this.notice.set(null);
        this.graphStatus.set('building');
        this.machineController.beginStage('surface', `${reason}:queued`);
        this.machineController.beginStage('evidenceGraph', `${reason}:queued`);
        this.machineController.beginStage('embeddings', `${reason}:queued`);
        this.machineController.beginStage('overgraph', `${reason}:queued`);
        return startedAt;
    }

    transitionAtlasRichScanStage(stage: 'surface' | 'evidenceGraph' | 'embeddings' | 'overgraph' | 'dynamic-ner' | 'graph-delta' | 'loading-model' | 'embedding' | 'applying-delta'): void {
        const normalized = this.normalizeAtlasStage(stage);
        const reason = `atlas-rich-scan:${normalized}`;
        switch (normalized) {
            case 'surface':
                this.machineController.beginStage('surface', reason);
                break;
            case 'evidenceGraph':
                this.machineController.finishStage('surface', reason);
                this.machineController.beginStage('evidenceGraph', reason);
                break;
            case 'embeddings':
                this.machineController.finishStage('evidenceGraph', reason);
                this.machineController.beginStage('embeddings', reason);
                break;
            case 'overgraph':
                this.machineController.finishStage('embeddings', reason);
                this.machineController.beginStage('overgraph', reason);
                break;
        }
    }

    finishAtlasRichScanFromResult(result: AtlasRichScanResult, startedAt: number, details: Record<string, unknown> = {}): void {
        this.machineController.finishStage('surface', 'atlas-rich-scan:surface');
        this.machineController.finishStage('evidenceGraph', 'atlas-rich-scan:evidenceGraph');
        this.machineController.finishStage('embeddings', 'atlas-rich-scan:embeddings');
        this.machineController.finishStage('overgraph', 'atlas-rich-scan:overgraph');
        if ((result.embeddingCounts?.leaf || 0) + (result.embeddingCounts?.entity || 0) + (result.embeddingCounts?.lens || 0) > 0) {
            this.vectorStatus.set('ready');
        }
        this.graphStatus.set('ready');
        const semanticIncluded = result.appliedOptions?.includeSemanticAtlas !== false;
        const label = semanticIncluded
            ? `Semantic Atlas processed ${result.processedDocuments} document${result.processedDocuments === 1 ? '' : 's'}`
            : `Text graph processed ${result.processedDocuments} document${result.processedDocuments === 1 ? '' : 's'} without embeddings`;
        this.notice.set(label);
        this.finishJob('atlas-rich-scan', label, startedAt, {
            ...details,
            scanId: result.scanId,
            processedDocuments: result.processedDocuments,
            skippedDocuments: result.skippedDocuments,
            candidateSuggestions: result.candidateSuggestions?.length || 0,
            relationCandidates: result.relationCandidateCount,
            embeddingCounts: result.embeddingCounts,
            graphDeltaCounts: result.graphDeltaCounts,
            lensChunkCounts: result.lensChunkCounts,
        });
    }

    finishAtlasRichScan(label: string, startedAt: number, details?: Record<string, unknown>): void {
        this.machineController.finishStage('surface', 'atlas-rich-scan:complete');
        this.machineController.finishStage('evidenceGraph', 'atlas-rich-scan:complete');
        this.machineController.finishStage('embeddings', 'atlas-rich-scan:complete');
        this.machineController.finishStage('overgraph', 'atlas-rich-scan:complete');
        this.graphStatus.set('ready');
        this.notice.set(label);
        this.finishJob('atlas-rich-scan', label, startedAt, details);
    }

    failAtlasRichScan(err: unknown): void {
        this.graphStatus.set('error');
        this.machineController.failStage('surface', 'atlas-rich-scan', err);
        this.machineController.failStage('evidenceGraph', 'atlas-rich-scan', err);
        this.machineController.failStage('embeddings', 'atlas-rich-scan', err);
        this.machineController.failStage('overgraph', 'atlas-rich-scan', err);
        this.failJob(err);
        this.activeJob.set(null);
    }

    setNotice(message: string | null): void {
        this.notice.set(message);
    }

    clearFeedback(): void {
        this.notice.set(null);
        this.error.set(null);
    }

    private auditScope(): { folderId?: string } {
        const scope = this.scope();
        return scope === 'global' ? {} : { folderId: scope };
    }

    private beginJob(kind: PhoenixMachineSummary['kind']): number {
        if (this.activeJob() !== 'atlas-rich-scan' || kind === 'atlas-rich-scan') {
            this.activeJob.set(kind);
        }
        return performance.now();
    }

    private normalizeAtlasStage(stage: 'surface' | 'evidenceGraph' | 'embeddings' | 'overgraph' | 'dynamic-ner' | 'graph-delta' | 'loading-model' | 'embedding' | 'applying-delta'): 'surface' | 'evidenceGraph' | 'embeddings' | 'overgraph' {
        switch (stage) {
            case 'dynamic-ner':
                return 'surface';
            case 'graph-delta':
                return 'evidenceGraph';
            case 'loading-model':
            case 'embedding':
                return 'embeddings';
            case 'applying-delta':
                return 'overgraph';
            default:
                return stage;
        }
    }

    private finishJob(
        kind: PhoenixMachineSummary['kind'],
        label: string,
        startedAt: number,
        details?: Record<string, unknown>
    ): void {
        this.recordSummary(kind, label, startedAt, details);
        if (this.activeJob() === kind || this.activeJob() !== 'atlas-rich-scan') {
            this.activeJob.set(null);
        }
    }

    private recordSummary(
        kind: PhoenixMachineSummary['kind'],
        label: string,
        startedAt: number,
        details?: Record<string, unknown>
    ): void {
        const completedAt = performance.now();
        this.lastSummary.set({
            kind,
            label,
            startedAt,
            completedAt,
            durationMs: Math.round(completedAt - startedAt),
            details,
        });
    }

    private failJob(err: unknown, expose = true): void {
        if (expose) this.error.set(err instanceof Error ? err.message : String(err));
        if (this.activeJob() !== 'atlas-rich-scan') {
            this.activeJob.set(null);
        }
    }

    private setManifoldStatus(mode: AtlasManifoldMode, status: PhoenixMachineManifoldStatus): void {
        this.manifoldStatuses.update((statuses) => {
            if (statuses[mode] === status) return statuses;
            return { ...statuses, [mode]: status };
        });
    }

    private hasLoadingManifold(): boolean {
        return Object.values(this.manifoldStatuses()).some((status) => status === 'loading');
    }
}
