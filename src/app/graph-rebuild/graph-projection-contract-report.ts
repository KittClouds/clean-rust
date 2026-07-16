import type {
    GraphIndexPostProcessMode,
    GraphRebuildCounters,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export type GraphProjectionContractTone = 'ready' | 'review' | 'danger' | 'quiet';

export type GraphProjectionRepresentationClass =
    | 'semantic_point'
    | 'incidence_object'
    | 'structural_region'
    | 'attached_span'
    | 'bridge'
    | 'excluded';

export interface GraphProjectionContractReceiptLike {
    postProcessMode?: GraphIndexPostProcessMode;
    postProcessCacheHit?: boolean;
    counters?: Partial<GraphRebuildCounters>;
}

export interface GraphProjectionContractOptions {
    receipt?: GraphProjectionContractReceiptLike | null;
    graphNodes?: number;
    embeddingNodes?: number;
    embeddingEdges?: number;
}

export interface GraphProjectionContractCounts {
    presentationDelta: number;
    hypergraphRoles: number;
    representationCounts: Record<GraphProjectionRepresentationClass, number>;
}

export interface GraphProjectionContractReport {
    status: GraphProjectionContractTone;
    summary: string;
    pipelineLabel: string;
    compilerLabel: string;
    vectorLabel: string;
    vectorDetail: string;
    semanticCoordinatesLabel: string;
    parityLabel: string;
    parityDetail: string;
    counts: GraphProjectionContractCounts;
}

const REPRESENTATION_CLASSES: GraphProjectionRepresentationClass[] = [
    'semantic_point',
    'incidence_object',
    'structural_region',
    'attached_span',
    'bridge',
    'excluded',
];

export function buildGraphProjectionContractReport(
    snapshot: GraphRebuildSnapshot | null | undefined,
    options: GraphProjectionContractOptions = {},
): GraphProjectionContractReport {
    if (!snapshot) return emptyReport();

    const counters = snapshot.counters;
    const receiptCounters = options.receipt?.counters;
    const graphNodes = firstNumber(options.graphNodes, counters.nodes, snapshot.nodes.length);
    const embeddingTargets = firstNumber(options.embeddingNodes, counters.embeddingTargets, snapshot.embeddingTargets.length);
    const embeddingLinks = firstNumber(options.embeddingEdges, projectedEmbeddingLinks(snapshot));
    const eligibleTargets = firstNumber(
        snapshot.embeddingTargetPlan?.candidateCount,
        counter(counters, 'embeddingTargetCandidates'),
        counter(receiptCounters, 'embeddingTargetCandidates'),
        snapshot.embeddingTargets.length,
    );
    const admittedTargets = firstNumber(
        snapshot.embeddingTargetPlan?.admittedCount,
        counter(counters, 'embeddingQueuedTargets'),
        counter(receiptCounters, 'embeddingQueuedTargets'),
        snapshot.embeddingTargets.length,
    );
    const nativeVectorsPresent = Math.max(
        snapshot.embeddingVectors.length,
        counter(counters, 'embeddingVectors') || 0,
        counter(receiptCounters, 'embeddingVectors') || 0,
    );
    const nativeVectorsRequired = admittedTargets;
    const representationCounts = countRepresentations(snapshot.embeddingTargets);
    const graphModel = snapshot.graphModelV2;
    const hypergraphRoles = firstNumber(graphModel?.counters.roles, graphModel?.roles.length);
    const unresolvedRoles = graphModel?.roles.filter((role) => role.resolved === false).length || 0;
    const presentationDelta = Math.abs(graphNodes - embeddingTargets);
    const pipelineLabel = pipelineLabelFor(snapshot, options.receipt);
    const compilerLabel = compilerLabelFor(snapshot);
    const vectorSource = snapshot.embeddingProfile?.vectorSource
        || snapshot.embeddingGraphPostProcess?.profile.vectorSource
        || 'signature-preview';
    const hasNativeCoordinates = vectorSource !== 'signature-preview'
        && nativeVectorsRequired > 0
        && nativeVectorsPresent >= nativeVectorsRequired;
    const vectorTone = vectorToneFor(vectorSource, nativeVectorsPresent, nativeVectorsRequired);
    const vectorLabel = hasNativeCoordinates
        ? 'Native semantic vectors'
        : vectorSource === 'signature-preview'
            ? 'Signature preview coordinates'
            : 'Vector cache incomplete';
    const vectorDetail = `${nativeVectorsPresent.toLocaleString()} / ${nativeVectorsRequired.toLocaleString()} vectors; ${snapshot.embeddingProfile?.modelLabel || 'semantic model'} ${snapshot.embeddingProfile?.dimensionLabel || ''}`.trim();
    const membershipTone = ratioTone(embeddingTargets, eligibleTargets, 0.98);
    const roleTone = hypergraphRoles === 0
        ? 'quiet'
        : unresolvedRoles === 0
            ? 'ready'
            : 'danger';
    const status = reportStatus([
        membershipTone,
        vectorTone,
        roleTone,
        presentationDelta ? 'review' : 'ready',
    ]);
    return {
        status,
        summary: status === 'ready' ? `${pipelineLabel}; contract clear` : `${pipelineLabel}; ${vectorLabel}`,
        pipelineLabel,
        compilerLabel,
        vectorLabel,
        vectorDetail,
        semanticCoordinatesLabel: hasNativeCoordinates ? vectorLabel : 'deterministic signature preview',
        parityLabel: presentationDelta ? `${presentationDelta.toLocaleString()} object delta` : 'count parity',
        parityDetail: `${graphNodes.toLocaleString()} graph nodes / ${embeddingTargets.toLocaleString()} embed targets / ${embeddingLinks.toLocaleString()} embed links`,
        counts: {
            presentationDelta,
            hypergraphRoles,
            representationCounts,
        },
    };
}

function emptyReport(): GraphProjectionContractReport {
    const counts = emptyRepresentationCounts();
    return {
        status: 'quiet',
        summary: 'No graph rebuild snapshot yet',
        pipelineLabel: 'No graph run',
        compilerLabel: 'Compiler pending',
        vectorLabel: 'No coordinates',
        vectorDetail: 'Run Build Clean Graph or Full Atlas to populate the ledger',
        semanticCoordinatesLabel: 'unavailable',
        parityLabel: 'unavailable',
        parityDetail: 'No graph or embedding inventory is committed',
        counts: {
            presentationDelta: 0,
            hypergraphRoles: 0,
            representationCounts: counts,
        },
    };
}

function classifyTarget(target: GraphRebuildEmbeddingTarget): GraphProjectionRepresentationClass {
    if (target.admissionStatus === 'deferred' || target.workStatus === 'deferred_by_policy' || target.workStatus === 'deferred_by_scheduler') {
        return 'excluded';
    }
    const kind = target.kind.toLowerCase();
    const lane = target.lane || 'unknown';
    if (target.structuralRole === 'evidence' || lane === 'anchor_evidence' || kind.includes('span') || kind.includes('evidence')) {
        return 'attached_span';
    }
    if (target.structuralRole === 'bridge' || lane === 'cooccurrence_weak' || lane === 'entity_linker') return 'bridge';
    if (target.structuralRole === 'root' || target.structuralRole === 'spine' || target.structuralRole === 'child'
        || lane === 'document_spine' || lane === 'chunk_spine') {
        return 'structural_region';
    }
    if (target.structuralRole === 'fact'
        || lane === 'relationship_fact'
        || lane === 'temporal_fact'
        || lane === 'causal_fact'
        || lane === 'memory_state'
        || lane === 'event_identity'
        || lane === 'story_signal'
        || kind.includes('fact')
        || kind.includes('relation')) {
        return 'incidence_object';
    }
    return 'semantic_point';
}

function countRepresentations(targets: GraphRebuildEmbeddingTarget[]): Record<GraphProjectionRepresentationClass, number> {
    const counts = emptyRepresentationCounts();
    for (const target of targets) counts[classifyTarget(target)] += 1;
    return counts;
}

function emptyRepresentationCounts(): Record<GraphProjectionRepresentationClass, number> {
    return REPRESENTATION_CLASSES.reduce((counts, kind) => {
        counts[kind] = 0;
        return counts;
    }, {} as Record<GraphProjectionRepresentationClass, number>);
}

function pipelineLabelFor(
    snapshot: GraphRebuildSnapshot,
    receipt: GraphProjectionContractReceiptLike | null | undefined,
): string {
    if (receipt?.postProcessMode === 'full') return receipt.postProcessCacheHit ? 'Full postprocess cache' : 'Full postprocess';
    if (receipt?.postProcessMode === 'core') return 'Core graph build';
    if (snapshot.embeddingGraphPostProcess) return 'Full postprocess snapshot';
    return 'Core graph snapshot';
}

function compilerLabelFor(snapshot: GraphRebuildSnapshot): string {
    if (snapshot.graphCompilerSource === 'rust') return 'Rust hypergraph compiler';
    if (snapshot.graphCompilerSource === 'typescriptCompatibility') return 'TS compatibility bridge';
    return snapshot.graphModelV2 ? 'Graph model v2' : 'Compiler pending';
}

function projectedEmbeddingLinks(snapshot: GraphRebuildSnapshot): number {
    return (snapshot.embeddingGraphPostProcess?.backboneEdges.length || 0)
        + (snapshot.embeddingGraphPostProcess?.bridgeEdges.length || 0)
        + snapshot.projectionRefs.length;
}

function vectorToneFor(source: string, present: number, required: number): GraphProjectionContractTone {
    if (!required) return 'quiet';
    if (source === 'signature-preview') return 'danger';
    if (present >= required) return 'ready';
    if (present > 0) return 'review';
    return 'danger';
}

function ratioTone(value: number, total: number, threshold: number): GraphProjectionContractTone {
    if (!total) return 'quiet';
    const ratio = value / total;
    if (ratio >= threshold) return 'ready';
    if (ratio >= threshold * 0.9) return 'review';
    return 'danger';
}

function reportStatus(tones: GraphProjectionContractTone[]): GraphProjectionContractTone {
    if (tones.includes('danger')) return 'danger';
    if (tones.includes('review')) return 'review';
    if (tones.includes('ready')) return 'ready';
    return 'quiet';
}

function firstNumber(...values: Array<number | null | undefined>): number {
    for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, value);
    }
    return 0;
}

function counter(counters: Partial<GraphRebuildCounters> | null | undefined, key: string): number | undefined {
    const value = (counters as Record<string, unknown> | null | undefined)?.[key];
    return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : undefined;
}
