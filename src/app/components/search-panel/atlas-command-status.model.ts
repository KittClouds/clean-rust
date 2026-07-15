import type { GraphAuditSnapshot } from '../../services/graph-audit.model';
import type { AtlasManifoldMode, PhoenixMachineManifoldStatus } from '../../services/manifold-atlas.types';
import type { PhoenixMachineGraphStatus, PhoenixMachineManifoldStatusMap, PhoenixMachineSummary, PhoenixMachineVectorStatus } from '../../services/phoenix-machine-control.service';
import type { PhoenixMachineStageSnapshot } from '../../services/phoenix-machine-controller.service';
import type { AtlasRichScanResult } from '../../services/phoenix-ui-api.service';
import type { RetrievalLane } from '../../services/retrieval-workbench-state.service';
import {
    buildAtlasLedgerGroups,
    flattenAtlasLedgerGroups,
    type AtlasLedgerGroup,
    type AtlasLedgerMetric,
} from '../../services/atlas-count-ledger.model';
import {
    ATLAS_CAPABILITY_LAYERS,
    ATLAS_CAPABILITY_RECIPES,
    ATLAS_CAPABILITY_REGISTRY,
    atlasCapabilityById,
    type AtlasCapability,
    type AtlasCapabilityId,
    type AtlasRecipeId,
} from './atlas-capability.model';
import { buildAdaptiveGraphRebuildChunks } from '../../graph-rebuild/graph-rebuild-meaning-frames';

export type AtlasPipelineStageId = 'scope' | 'surface' | 'ner' | 'graph' | 'semantic' | 'sidecars' | 'retrieval';
export type { AtlasRecipeId } from './atlas-capability.model';
export type AtlasPipelineTone = 'idle' | 'dirty' | 'running' | 'ready' | 'error';
export type AtlasCapabilityTone = AtlasPipelineTone | 'sleeping';

export interface AtlasInventoryCounts {
    notes: number;
    registryEntities: number | null;
    committedVertices: number | null;
    graphLeaves: number | null;
    evidenceEdges: number | null;
    candidateEdges: number | null;
    embeddingVectors: number | null;
    issues: number | null;
}

export interface AtlasInventoryMetric {
    label: string;
    value: number | null;
    detail: string;
    source: string;
}

export interface AtlasPipelineStageStatus {
    id: AtlasPipelineStageId;
    label: string;
    status: AtlasPipelineTone;
    detail: string;
    input: string;
    output: string;
    action: string;
}

export interface AtlasCapabilityStatusCard {
    id: AtlasCapabilityId;
    label: string;
    family: AtlasCapability['family'];
    status: AtlasCapabilityTone;
    detail: string;
    input: string;
    output: string;
    cost: AtlasCapability['cost'];
    mutationPolicy: AtlasCapability['mutationPolicy'];
    uiCoverage: AtlasCapability['uiCoverage'];
    runnable: boolean;
    backendRoute: string;
}

export interface AtlasCapabilityLayerStatus {
    id: string;
    label: string;
    description: string;
    status: AtlasCapabilityTone;
    capabilities: AtlasCapabilityStatusCard[];
}

export interface AtlasRecipe {
    id: AtlasRecipeId;
    label: string;
    subtitle: string;
    detail: string;
    output: string;
    icon: string;
    primary?: boolean;
}

export interface AtlasRecipeResult {
    recipeId: AtlasRecipeId;
    label: string;
    durationMs: number;
    details?: Record<string, unknown>;
}

export interface AtlasCommandStatus {
    scopeLabel: string;
    state: AtlasPipelineTone;
    inventory: AtlasInventoryCounts;
    ledgerGroups: AtlasLedgerGroup[];
    metrics: AtlasLedgerMetric[];
    stages: AtlasPipelineStageStatus[];
    capabilityLayers: AtlasCapabilityLayerStatus[];
    sleepingCapabilities: AtlasCapabilityStatusCard[];
    sidecars: AtlasInventoryMetric[];
    chunking: {
        chunkSize: number;
        overlap: number;
        sentenceBoundaries: boolean;
        estimatedChunks: number;
        source: string;
    };
    lastRun: {
        label: string;
        detail: string;
        durationMs: number | null;
    };
}

export interface AtlasCommandStatusInput {
    scopeLabel: string;
    noteCount: number;
    estimatedChunks: number;
    audit: GraphAuditSnapshot | null;
    stages: Partial<Record<string, PhoenixMachineStageSnapshot>>;
    activeJob: PhoenixMachineSummary['kind'] | null;
    lastSummary: PhoenixMachineSummary | null;
    lastRichScan: AtlasRichScanResult | null;
    vectorStatus: PhoenixMachineVectorStatus;
    graphStatus: PhoenixMachineGraphStatus;
    manifoldMode: AtlasManifoldMode;
    manifoldStatus: PhoenixMachineManifoldStatus;
    manifoldStatuses: PhoenixMachineManifoldStatusMap;
    dynamicNerStatus: 'cold' | 'ready' | 'warming' | 'running' | 'error';
    enabledLanes: RetrievalLane[];
    embeddingModelLabel: string;
    embeddingDimensionLabel: string;
}

export const ATLAS_RECIPES: AtlasRecipe[] = ATLAS_CAPABILITY_RECIPES.map((recipe) => ({
    id: recipe.id,
    label: recipe.label,
    subtitle: recipe.subtitle,
    detail: recipe.description,
    output: recipe.outputLabel,
    icon: recipe.icon,
    primary: recipe.primary,
}));

const CHUNK_SIZE = 460;
const CHUNK_OVERLAP = 64;

export function estimateDynamicChunks(notes: Array<{ id?: string; content: string }>): number {
    return notes.reduce((total, note, index) => {
        const text = String(note.content || '');
        if (!text.trim()) return total;
        return total + buildAdaptiveGraphRebuildChunks(note.id || `estimate:${index}`, text).length;
    }, 0);
}

export function buildAtlasCommandStatus(input: AtlasCommandStatusInput): AtlasCommandStatus {
    const audit = input.audit;
    const last = input.lastRichScan;
    const embeddingVectors = last
        ? (last.embeddingCounts?.leaf || 0) + (last.embeddingCounts?.entity || 0) + (last.embeddingCounts?.lens || 0)
        : null;
    const candidateEdges = last?.graphDeltaCounts?.['candidateEdges'] ?? null;
    const graphLeaves = audit?.nodeKinds.find((bucket) => ['leaf', 'chunk'].includes(bucket.key))?.count ?? null;
    const inventory: AtlasInventoryCounts = {
        notes: input.noteCount,
        registryEntities: audit ? audit.registryEntities : null,
        committedVertices: audit ? audit.graphNodes : null,
        graphLeaves,
        evidenceEdges: audit ? audit.graphEdges : null,
        candidateEdges,
        embeddingVectors,
        issues: audit ? (audit.orphanEdges || 0) + (audit.duplicateEdges || 0) : null,
    };
    const ledgerGroups = buildAtlasLedgerGroups(inventory, input.scopeLabel);

    return {
        scopeLabel: input.scopeLabel,
        state: overallTone(input),
        inventory,
        ledgerGroups,
        metrics: flattenAtlasLedgerGroups(ledgerGroups),
        stages: buildStages(input, inventory),
        capabilityLayers: buildCapabilityLayers(input, inventory),
        sleepingCapabilities: buildSleepingCapabilities(input, inventory),
        sidecars: buildSidecars(input),
        chunking: {
            chunkSize: CHUNK_SIZE,
            overlap: CHUNK_OVERLAP,
            sentenceBoundaries: true,
            estimatedChunks: input.estimatedChunks,
            source: 'adaptive graph rebuild',
        },
        lastRun: {
            label: input.lastSummary?.label || 'No completed command yet',
            detail: lastRunDetail(last),
            durationMs: input.lastSummary?.durationMs ?? null,
        },
    };
}

function buildCapabilityLayers(input: AtlasCommandStatusInput, counts: AtlasInventoryCounts): AtlasCapabilityLayerStatus[] {
    return ATLAS_CAPABILITY_LAYERS.map((layer) => {
        const capabilities = layer.capabilityIds.map((id) => buildCapabilityStatusCard(atlasCapabilityById(id), input, counts));
        return {
            id: layer.id,
            label: layer.label,
            description: layer.description,
            status: aggregateCapabilityTone(capabilities.map((capability) => capability.status)),
            capabilities,
        };
    });
}

function buildSleepingCapabilities(input: AtlasCommandStatusInput, counts: AtlasInventoryCounts): AtlasCapabilityStatusCard[] {
    return ATLAS_CAPABILITY_REGISTRY
        .filter((capability) => capability.uiCoverage === 'sleeping' || capability.uiCoverage === 'partial')
        .map((capability) => buildCapabilityStatusCard(capability, input, counts));
}

function buildCapabilityStatusCard(
    capability: AtlasCapability,
    input: AtlasCommandStatusInput,
    counts: AtlasInventoryCounts,
): AtlasCapabilityStatusCard {
    const status = capabilityTone(capability, input, counts);
    return {
        id: capability.id,
        label: capability.label,
        family: capability.family,
        status,
        detail: capabilityDetail(capability, input, counts),
        input: capability.inputs.join(' + ') || 'none',
        output: capability.outputs.join(' + ') || 'none',
        cost: capability.cost,
        mutationPolicy: capability.mutationPolicy,
        uiCoverage: capability.uiCoverage,
        runnable: capability.runnable,
        backendRoute: capability.backendRoute,
    };
}

function buildStages(input: AtlasCommandStatusInput, counts: AtlasInventoryCounts): AtlasPipelineStageStatus[] {
    return [
        stage('scope', 'Scope', 'ready', input.scopeLabel, 'workspace notes', `${counts.notes} note${plural(counts.notes)}`, 'Choose scope'),
        stage('surface', 'Text Surface + Dynamic Chunking', toneFromMachine(input.stages['surface']?.status), `${input.estimatedChunks} est. chunks`, `${counts.notes} notes`, countNoun(counts.graphLeaves, 'committed leaf', 'committed leaves'), 'Fast Text Graph'),
        stage('ner', 'Dynamic NER / Review Lanes', nerTone(input.dynamicNerStatus), `Phoenix ${input.dynamicNerStatus}`, 'plain text', 'candidate entities', 'Run NER'),
        stage('graph', 'Text Graph Commit', graphTone(input.graphStatus), `${countNoun(counts.committedVertices, 'vertex', 'vertices')}, ${countNoun(counts.evidenceEdges, 'evidence edge', 'evidence edges')}`, 'surface + mentions', 'committed graph', 'Text Graph'),
        stage('semantic', 'Semantic Sidecar', vectorTone(input.vectorStatus, counts.embeddingVectors), `${input.embeddingModelLabel} ${input.embeddingDimensionLabel}`, 'committed graph + text', valueLabel(counts.embeddingVectors, 'vectors'), 'Semantic Atlas'),
        stage('sidecars', 'Manifold Sidecars', manifoldTone(input.manifoldStatus), `${input.manifoldMode} ${input.manifoldStatus}`, 'semantic atlas', 'Hybrid / Hopf / Lorentz / Product', 'Visualize'),
        stage('retrieval', 'Retrieval / Visualization', input.enabledLanes.length ? 'ready' : 'idle', input.enabledLanes.join(' + ') || 'lexical', 'query text', 'ranked results', 'Search'),
    ];
}

function buildSidecars(input: AtlasCommandStatusInput): AtlasInventoryMetric[] {
    return [
        { label: 'Semantic sidecar', value: null, detail: `${input.vectorStatus} ${input.embeddingDimensionLabel}`, source: input.embeddingModelLabel },
        { label: 'Hybrid embedding manifold', value: null, detail: input.manifoldStatuses.hybrid, source: 'Hybrid' },
        { label: 'Hopf projection', value: null, detail: input.manifoldStatuses.hopf, source: 'Hopf' },
        { label: 'Lorentz forest', value: null, detail: input.manifoldStatuses.lorentz, source: 'Lorentz' },
        { label: 'Product manifold', value: null, detail: input.manifoldStatuses.product, source: 'Product' },
    ];
}

function capabilityTone(
    capability: AtlasCapability,
    input: AtlasCommandStatusInput,
    counts: AtlasInventoryCounts,
): AtlasCapabilityTone {
    if (capability.uiCoverage === 'sleeping') return 'sleeping';

    switch (capability.id) {
        case 'dynamicSurface':
        case 'dynamicChunking':
            return toneFromMachine(input.stages['surface']?.status);
        case 'dynamicNer':
            return nerTone(input.dynamicNerStatus);
        case 'mentionGraph':
        case 'evidenceGraph':
        case 'surfaceGraph':
        case 'assertedKernel':
            return graphTone(input.graphStatus);
        case 'relationGraph':
            if ((input.lastRichScan?.relationCandidateCount || 0) > 0) return 'ready';
            return counts.committedVertices ? 'idle' : 'sleeping';
        case 'semanticEmbedding':
        case 'semanticAtlas':
            return vectorTone(input.vectorStatus, counts.embeddingVectors);
        case 'semanticCandidate':
            return (counts.candidateEdges || 0) > 0 || (input.lastRichScan?.relationCandidateCount || 0) > 0
                ? 'ready'
                : 'idle';
        case 'nliAdjudication':
            return capability.uiCoverage === 'partial' ? 'idle' : 'sleeping';
        case 'hybridManifold':
            return manifoldTone(input.manifoldStatuses.hybrid);
        case 'hopfProjection':
            return manifoldTone(input.manifoldStatuses.hopf);
        case 'lorentzForest':
            return manifoldTone(input.manifoldStatuses.lorentz);
        case 'productManifold':
            return manifoldTone(input.manifoldStatuses.product);
        case 'retrievalWalk':
            return input.enabledLanes.length ? 'ready' : 'idle';
        case 'galaxyVisualization':
            return counts.committedVertices || counts.evidenceEdges ? 'ready' : 'idle';
        case 'temporalGraph':
        case 'eventIdentity':
        case 'memoryState':
        case 'causalGraph':
            return counts.committedVertices ? 'idle' : 'sleeping';
    }
}

function capabilityDetail(
    capability: AtlasCapability,
    input: AtlasCommandStatusInput,
    counts: AtlasInventoryCounts,
): string {
    if (!capability.runnable && capability.backendRoute.startsWith('QUARANTINED:')) {
        return capability.backendRoute;
    }

    if (capability.uiCoverage === 'sleeping') {
        return `${capability.mutationPolicy}; backend types/sidecars detected, not exposed as a runnable recipe yet`;
    }

    switch (capability.id) {
        case 'dynamicSurface':
            return `${input.estimatedChunks} est. chunks; ${stageSummaryDetail(input, capability)}`;
        case 'dynamicChunking':
            return `${input.estimatedChunks} estimated chunks; lens counts ${recordCount(input.lastRichScan?.lensChunkCounts)}`;
        case 'dynamicNer':
            return `Phoenix ${input.dynamicNerStatus}; ${input.lastRichScan?.candidateSuggestions.length ?? 0} last surface suggestions`;
        case 'mentionGraph':
            return `${countNoun(counts.graphLeaves, 'committed leaf', 'committed leaves')}; co-occurrence lane`;
        case 'evidenceGraph':
            return `${countNoun(counts.evidenceEdges, 'evidence edge', 'evidence edges')}; graph delta ${recordCount(input.lastRichScan?.graphDeltaCounts)}`;
        case 'surfaceGraph':
            return `${countNoun(counts.graphLeaves, 'leaf/chunk node', 'leaf/chunk nodes')}; surface topology`;
        case 'assertedKernel':
            return `${countNoun(counts.committedVertices, 'vertex', 'vertices')}, ${countNoun(counts.evidenceEdges, 'edge', 'edges')}`;
        case 'relationGraph':
            return `${input.lastRichScan?.relationCandidateCount || 0} relation candidates from last rich scan`;
        case 'semanticEmbedding':
            return `${input.embeddingModelLabel} ${input.embeddingDimensionLabel}; ${valueLabel(counts.embeddingVectors, 'vectors')}`;
        case 'semanticAtlas':
            return `${valueLabel(counts.embeddingVectors, 'vectors')}; semantic ${input.lastRichScan ? 'last run available' : 'not run yet'}`;
        case 'semanticCandidate':
            return `${valueLabel(counts.candidateEdges, 'candidate edges')}; ${input.lastRichScan?.relationCandidateCount || 0} relation candidates`;
        case 'nliAdjudication':
            return 'NLI model lane can warm, adjudication queue is future/partial';
        case 'hybridManifold':
            return `Hybrid ${input.manifoldStatuses.hybrid}`;
        case 'hopfProjection':
            return `Hopf ${input.manifoldStatuses.hopf}`;
        case 'lorentzForest':
            return `Lorentz ${input.manifoldStatuses.lorentz}; tree kinds include temporal/causal/evidence/provenance`;
        case 'productManifold':
            return `Product ${input.manifoldStatuses.product}; Lorentz skeleton + Hopf fibers + semantic shell`;
        case 'retrievalWalk':
            return input.enabledLanes.join(' + ') || 'lexical fallback';
        case 'galaxyVisualization':
            return counts.committedVertices || counts.evidenceEdges ? 'current graph snapshot available' : 'no committed graph snapshot yet';
        case 'temporalGraph':
        case 'eventIdentity':
        case 'memoryState':
        case 'causalGraph':
            return `${capability.mutationPolicy}; read-only native store probe registered`;
    }
}

function aggregateCapabilityTone(statuses: AtlasCapabilityTone[]): AtlasCapabilityTone {
    if (statuses.includes('error')) return 'error';
    if (statuses.includes('running')) return 'running';
    if (statuses.includes('dirty')) return 'dirty';
    if (statuses.includes('ready')) return 'ready';
    if (statuses.every((status) => status === 'sleeping')) return 'sleeping';
    return 'idle';
}

function stageSummaryDetail(input: AtlasCommandStatusInput, capability: AtlasCapability): string {
    const keys = capability.stageSummaryKeys || [];
    const summary = input.lastRichScan?.stageSummaries.find((stageSummary) => keys.includes(stageSummary.stage));
    if (!summary) return 'stage summary pending';
    return `${summary.status} ${summary.durationMs}ms`;
}

function recordCount(record: Record<string, number> | undefined): string {
    if (!record) return 'not run';
    const total = Object.values(record).reduce((sum, value) => sum + value, 0);
    return `${total} total`;
}

function stage(
    id: AtlasPipelineStageId,
    label: string,
    status: AtlasPipelineTone,
    detail: string,
    input: string,
    output: string,
    action: string,
): AtlasPipelineStageStatus {
    return { id, label, status, detail, input, output, action };
}

function overallTone(input: AtlasCommandStatusInput): AtlasPipelineTone {
    if (input.activeJob && input.activeJob !== 'manifold-load' && input.activeJob !== 'graph-focus') return 'running';
    if (input.graphStatus === 'error' || input.vectorStatus === 'error') return 'error';
    if (input.graphStatus === 'building' || input.vectorStatus === 'loading' || input.vectorStatus === 'indexing') return 'running';
    if (input.graphStatus === 'ready' || input.vectorStatus === 'ready') return 'ready';
    return 'idle';
}

function toneFromMachine(status: string | undefined): AtlasPipelineTone {
    if (status === 'running' || status === 'queued') return 'running';
    if (status === 'dirty') return 'dirty';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    return 'idle';
}

function graphTone(status: PhoenixMachineGraphStatus): AtlasPipelineTone {
    if (status === 'building' || status === 'searching') return 'running';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    return 'idle';
}

function vectorTone(status: PhoenixMachineVectorStatus, vectors: number | null): AtlasPipelineTone {
    if (status === 'loading' || status === 'indexing') return 'running';
    if (status === 'error') return 'error';
    if (status === 'ready' || (vectors || 0) > 0) return 'ready';
    return 'idle';
}

function manifoldTone(status: PhoenixMachineManifoldStatus): AtlasPipelineTone {
    if (status === 'loading') return 'running';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    if (status === 'stale') return 'dirty';
    return 'idle';
}

function nerTone(status: AtlasCommandStatusInput['dynamicNerStatus']): AtlasPipelineTone {
    if (status === 'running' || status === 'warming') return 'running';
    if (status === 'ready') return 'ready';
    if (status === 'error') return 'error';
    return 'idle';
}

function valueLabel(value: number | null, label: string): string {
    return value === null ? 'not run' : `${value} ${label}`;
}

function countNoun(value: number | null, singular: string, pluralLabel: string): string {
    if (value === null) return 'unavailable';
    return `${value} ${value === 1 ? singular : pluralLabel}`;
}

function lastRunDetail(result: AtlasRichScanResult | null): string {
    if (!result) return 'Run a recipe to populate stage counts.';
    const semantic = result.appliedOptions?.includeSemanticAtlas !== false;
    return semantic ? 'semantic sidecar included' : 'text graph only, embeddings skipped';
}

function plural(value: number): string {
    return value === 1 ? '' : 's';
}
