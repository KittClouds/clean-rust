import type {
    DocumentUnit,
    EvidenceSpan,
    GraphDocumentSidecarSummary,
    GraphFactCandidate,
    RetrievalUnit,
} from './graph-document-sidecar';
import type {
    GraphDocumentReviewRow,
    GraphDocumentReviewState,
    GraphDocumentReviewSummary,
} from './graph-document-review';

export type GraphDocumentCompileOutputKind =
    | 'entity_mention'
    | 'relation_candidate'
    | 'hyperedge'
    | 'evidence_backed_edge'
    | 'cross_doc_bridge'
    | 'document_structure_edge'
    | 'retrieval_overlay';

export type GraphDocumentCompileStatus =
    | 'pending_commit'
    | 'reviewable'
    | 'blocked'
    | 'ledger_only'
    | 'overlay_only';

export interface GraphDocumentCompilerBaseline {
    atomCount: number;
    factCount: number;
    edgeCount: number;
}

export interface GraphDocumentCompilerProvenance {
    sourceObjectId: string;
    sourceObjectKind: string;
    sourceReviewRowId?: string;
    reviewState?: GraphDocumentReviewState;
    noteId: string;
    sourceStart: number;
    sourceEnd: number;
    evidenceSpanIds: string[];
    lineageUnitIds: string[];
    reasons: string[];
}

export interface GraphDocumentCompiledEntityMention {
    id: string;
    surface: string;
    normalizedSurface: string;
    resolvedEntityId?: string;
    role: 'subject' | 'object';
    noteId: string;
    sourceStart: number;
    sourceEnd: number;
    confidence: number;
    status: GraphDocumentCompileStatus;
    anchorPolicy: 'mention_only_not_user_anchor';
    evidenceSpanIds: string[];
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentRelationCandidate {
    id: string;
    predicate: string;
    subjectMentionIds: string[];
    objectMentionIds: string[];
    subjectEntityIds: string[];
    objectEntityIds: string[];
    evidenceSpanIds: string[];
    confidence: number;
    status: GraphDocumentCompileStatus;
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentHyperedgeRole {
    id: string;
    role: string;
    targetId: string;
    targetKind: 'entity' | 'entity_mention' | 'evidence_span' | 'document_unit' | 'retrieval_unit';
    surface?: string;
    confidence: number;
}

export interface GraphDocumentHyperedge {
    id: string;
    predicate: string;
    sourceKind: GraphFactCandidate['kind'];
    roles: GraphDocumentHyperedgeRole[];
    evidenceSpanIds: string[];
    confidence: number;
    status: GraphDocumentCompileStatus;
    nary: boolean;
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentEvidenceBackedEdge {
    id: string;
    sourceId: string;
    targetId: string;
    relationType: string;
    evidenceSpanIds: string[];
    confidence: number;
    status: GraphDocumentCompileStatus;
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentCrossDocBridge {
    id: string;
    topic: string;
    noteIds: string[];
    retrievalUnitId: string;
    confidence: number;
    status: 'overlay_only';
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentStructureEdge {
    id: string;
    parentUnitId: string;
    childUnitId: string;
    relationType: 'document_contains';
    confidence: number;
    status: 'overlay_only';
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentRetrievalOverlay {
    id: string;
    retrievalUnitId: string;
    retrievalKind: RetrievalUnit['kind'];
    targetChunkIds: string[];
    evidenceSpanIds: string[];
    confidence: number;
    status: 'overlay_only' | 'ledger_only';
    provenance: GraphDocumentCompilerProvenance;
}

export interface GraphDocumentTopologyDiff {
    id: string;
    outputKind: GraphDocumentCompileOutputKind;
    outputId: string;
    operation:
        | 'add_entity_mentions'
        | 'add_relation_candidate'
        | 'add_hyperedge'
        | 'add_evidence_edge'
        | 'add_cross_doc_bridge'
        | 'add_document_structure_edge'
        | 'add_retrieval_overlay';
    status: GraphDocumentCompileStatus;
    mutationAllowed: boolean;
    topologyCommit: boolean;
    beforeGraph: GraphDocumentCompilerBaseline;
    afterGraph: GraphDocumentCompilerBaseline;
    createdAtomIds: string[];
    createdFactIds: string[];
    createdEdgeIds: string[];
    evidenceSpanIds: string[];
    rationale: string[];
}

export interface GraphDocumentTopologyReceipt {
    id: string;
    topologyDiffId: string;
    outputKind: GraphDocumentCompileOutputKind;
    outputId: string;
    reversible: true;
    mutationAllowed: boolean;
    invariant:
        | 'document_compiler_reversible_topology_commit'
        | 'document_compiler_ledger_only_no_topology_commit';
    undoPatch: {
        operation: 'remove_document_compiler_outputs' | 'remove_document_compiler_ledger_row';
        removeAtomIds: string[];
        removeFactIds: string[];
        removeEdgeIds: string[];
        restoreReviewState?: GraphDocumentReviewState;
    };
    detail: string;
    createdAt: number;
}

export interface GraphDocumentCompilerCounters {
    entityMentions: number;
    relationCandidates: number;
    hyperedges: number;
    naryHyperedges: number;
    evidenceBackedEdges: number;
    crossDocBridges: number;
    documentStructureEdges: number;
    retrievalOverlays: number;
    topologyDiffs: number;
    topologyCommits: number;
    ledgerOnly: number;
    overlayOnly: number;
    reviewable: number;
    blocked: number;
    receipts: number;
    reversibleReceipts: number;
    mutationAllowed: number;
    highConfidenceFacts: number;
    reviewedFacts: number;
    ambiguousFacts: number;
    byKind: Record<string, number>;
    byStatus: Record<string, number>;
}

export interface GraphDocumentCompilerSummary {
    schemaVersion: 'phoenix-document-compiler/v1';
    builtAt: number;
    sourceSidecarBuiltAt: number;
    sourceReviewBuiltAt: number;
    compilePolicy: 'reviewed_or_high_confidence_facts_only';
    sidecarPolicy: 'structure_is_disposable_anchors_are_durable';
    topologyPolicy: 'topology_commits_require_reversible_receipts';
    highConfidenceThreshold: number;
    entityMentions: GraphDocumentCompiledEntityMention[];
    relationCandidates: GraphDocumentRelationCandidate[];
    hyperedges: GraphDocumentHyperedge[];
    evidenceBackedEdges: GraphDocumentEvidenceBackedEdge[];
    crossDocBridges: GraphDocumentCrossDocBridge[];
    documentStructureEdges: GraphDocumentStructureEdge[];
    retrievalOverlays: GraphDocumentRetrievalOverlay[];
    topologyDiffs: GraphDocumentTopologyDiff[];
    receipts: GraphDocumentTopologyReceipt[];
    counters: GraphDocumentCompilerCounters;
}

export interface BuildGraphDocumentCompilerInput {
    sidecar: GraphDocumentSidecarSummary;
    review: GraphDocumentReviewSummary;
    builtAt: number;
    baseline?: Partial<GraphDocumentCompilerBaseline>;
    highConfidenceThreshold?: number;
    entities?: Array<{ id: string; label: string; aliases?: string[] }>;
}

interface CompilerContext {
    input: BuildGraphDocumentCompilerInput;
    baseline: GraphDocumentCompilerBaseline;
    reviewByObjectId: Map<string, GraphDocumentReviewRow>;
    evidenceById: Map<string, EvidenceSpan>;
    entityBySurface: Map<string, string>;
    entityMentions: GraphDocumentCompiledEntityMention[];
    relationCandidates: GraphDocumentRelationCandidate[];
    hyperedges: GraphDocumentHyperedge[];
    evidenceBackedEdges: GraphDocumentEvidenceBackedEdge[];
    crossDocBridges: GraphDocumentCrossDocBridge[];
    documentStructureEdges: GraphDocumentStructureEdge[];
    retrievalOverlays: GraphDocumentRetrievalOverlay[];
    topologyDiffs: GraphDocumentTopologyDiff[];
    receipts: GraphDocumentTopologyReceipt[];
    highConfidenceFacts: number;
    reviewedFacts: number;
    ambiguousFacts: number;
}

const DEFAULT_HIGH_CONFIDENCE = 0.84;
const MAX_FACTS = 96;
const MAX_ENTITY_MENTIONS = 384;
const MAX_STRUCTURE_EDGES = 512;
const MAX_RETRIEVAL_OVERLAYS = 256;

export function buildGraphDocumentCompilerSummary(
    input: BuildGraphDocumentCompilerInput,
): GraphDocumentCompilerSummary {
    const context: CompilerContext = {
        input,
        baseline: {
            atomCount: input.baseline?.atomCount || 0,
            factCount: input.baseline?.factCount || 0,
            edgeCount: input.baseline?.edgeCount || 0,
        },
        reviewByObjectId: new Map(input.review.rows.map((row) => [row.objectId, row])),
        evidenceById: new Map(input.sidecar.evidenceSpans.map((span) => [span.id, span])),
        entityBySurface: entitySurfaceIndex(input.entities || []),
        entityMentions: [],
        relationCandidates: [],
        hyperedges: [],
        evidenceBackedEdges: [],
        crossDocBridges: [],
        documentStructureEdges: [],
        retrievalOverlays: [],
        topologyDiffs: [],
        receipts: [],
        highConfidenceFacts: 0,
        reviewedFacts: 0,
        ambiguousFacts: 0,
    };
    compileGraphFacts(context);
    compileDocumentStructure(context);
    compileRetrievalOverlays(context);
    return {
        schemaVersion: 'phoenix-document-compiler/v1',
        builtAt: input.builtAt,
        sourceSidecarBuiltAt: input.sidecar.builtAt,
        sourceReviewBuiltAt: input.review.builtAt,
        compilePolicy: 'reviewed_or_high_confidence_facts_only',
        sidecarPolicy: 'structure_is_disposable_anchors_are_durable',
        topologyPolicy: 'topology_commits_require_reversible_receipts',
        highConfidenceThreshold: input.highConfidenceThreshold || DEFAULT_HIGH_CONFIDENCE,
        entityMentions: context.entityMentions,
        relationCandidates: context.relationCandidates,
        hyperedges: context.hyperedges,
        evidenceBackedEdges: context.evidenceBackedEdges,
        crossDocBridges: context.crossDocBridges,
        documentStructureEdges: context.documentStructureEdges,
        retrievalOverlays: context.retrievalOverlays,
        topologyDiffs: context.topologyDiffs,
        receipts: context.receipts,
        counters: counters(context),
    };
}

function compileGraphFacts(context: CompilerContext): void {
    for (const fact of context.input.sidecar.graphFactCandidates.slice(0, MAX_FACTS)) {
        const row = context.reviewByObjectId.get(fact.id);
        const resolvedEntityIds = resolvedEntitiesForFact(context, fact);
        const status = statusForFact(
            fact,
            row,
            context.input.highConfidenceThreshold || DEFAULT_HIGH_CONFIDENCE,
            resolvedEntityIds.length,
        );
        if (status === 'pending_commit') {
            if (row?.state === 'accepted' || row?.state === 'compiled_to_graph') context.reviewedFacts += 1;
            else context.highConfidenceFacts += 1;
        } else if (status === 'reviewable') {
            context.ambiguousFacts += 1;
        }
        const provenance = provenanceFor(fact, row, fact.evidenceSpanIds);
        const mentions = mentionRowsFor(context, fact, row, status, provenance);
        const relation = relationFor(fact, mentions, status, provenance);
        if (relation) context.relationCandidates.push(relation);
        const hyperedge = hyperedgeFor(fact, mentions, status, provenance);
        context.hyperedges.push(hyperedge);
        const evidenceEdge = evidenceEdgeFor(fact, relation, hyperedge, mentions, status, provenance);
        if (evidenceEdge) context.evidenceBackedEdges.push(evidenceEdge);
        const createdAtomIds = mentions.map((mention) => `atom:document-mention:${mention.id}`);
        const createdFactIds = [`fact:document-hyperedge:${hyperedge.id}`];
        if (relation) createdFactIds.push(`fact:document-relation:${relation.id}`);
        const createdEdgeIds = evidenceEdge ? [evidenceEdge.id] : [];
        pushDiffAndReceipt(context, {
            outputKind: 'hyperedge',
            outputId: hyperedge.id,
            operation: 'add_hyperedge',
            status,
            restoreReviewState: row?.state,
            createdAtomIds,
            createdFactIds,
            createdEdgeIds,
            evidenceSpanIds: fact.evidenceSpanIds,
            rationale: [
                `review_state:${row?.state || 'missing'}`,
                `confidence:${fact.confidence.score}`,
                `roles:${hyperedge.roles.length}`,
                ...fact.confidence.reasons,
            ],
        });
    }
}

function compileDocumentStructure(context: CompilerContext): void {
    const units = context.input.sidecar.units;
    for (const unit of units) {
        if (!unit.parentId || context.documentStructureEdges.length >= MAX_STRUCTURE_EDGES) continue;
        const provenance = provenanceFor(unit, context.reviewByObjectId.get(unit.id), []);
        const edge: GraphDocumentStructureEdge = {
            id: `document-structure-edge:${slug(`${unit.parentId}:${unit.id}`)}`,
            parentUnitId: unit.parentId,
            childUnitId: unit.id,
            relationType: 'document_contains',
            confidence: unit.confidence.score,
            status: 'overlay_only',
            provenance,
        };
        context.documentStructureEdges.push(edge);
        pushDiffAndReceipt(context, {
            outputKind: 'document_structure_edge',
            outputId: edge.id,
            operation: 'add_document_structure_edge',
            status: 'overlay_only',
            restoreReviewState: provenance.reviewState,
            createdAtomIds: [],
            createdFactIds: [],
            createdEdgeIds: [edge.id],
            evidenceSpanIds: [],
            rationale: ['sidecar_structure_overlay', ...unit.confidence.reasons],
        });
    }
}

function compileRetrievalOverlays(context: CompilerContext): void {
    for (const unit of context.input.sidecar.retrievalUnits.slice(0, MAX_RETRIEVAL_OVERLAYS)) {
        const row = context.reviewByObjectId.get(unit.id);
        const provenance = provenanceFor(unit, row, unit.evidenceSpanIds);
        if (unit.kind === 'cross_doc_topic_packet') {
            const bridge: GraphDocumentCrossDocBridge = {
                id: `document-crossdoc-bridge:${slug(unit.id)}`,
                topic: unit.label,
                noteIds: context.input.sidecar.noteIds,
                retrievalUnitId: unit.id,
                confidence: unit.confidence.score,
                status: 'overlay_only',
                provenance,
            };
            context.crossDocBridges.push(bridge);
            pushDiffAndReceipt(context, {
                outputKind: 'cross_doc_bridge',
                outputId: bridge.id,
                operation: 'add_cross_doc_bridge',
                status: 'overlay_only',
                restoreReviewState: provenance.reviewState,
                createdAtomIds: [],
                createdFactIds: [],
                createdEdgeIds: [bridge.id],
                evidenceSpanIds: unit.evidenceSpanIds,
                rationale: ['cross_doc_topic_packet_overlay', ...unit.confidence.reasons],
            });
        }
        const overlay: GraphDocumentRetrievalOverlay = {
            id: `document-retrieval-overlay:${slug(unit.id)}`,
            retrievalUnitId: unit.id,
            retrievalKind: unit.kind,
            targetChunkIds: unit.targetChunkIds,
            evidenceSpanIds: unit.evidenceSpanIds,
            confidence: unit.confidence.score,
            status: row?.state === 'ledger_only' ? 'ledger_only' : 'overlay_only',
            provenance,
        };
        context.retrievalOverlays.push(overlay);
        pushDiffAndReceipt(context, {
            outputKind: 'retrieval_overlay',
            outputId: overlay.id,
            operation: 'add_retrieval_overlay',
            status: overlay.status,
            restoreReviewState: provenance.reviewState,
            createdAtomIds: [],
            createdFactIds: [],
            createdEdgeIds: [],
            evidenceSpanIds: unit.evidenceSpanIds,
            rationale: [`retrieval:${unit.kind}`, ...unit.confidence.reasons],
        });
    }
}

function mentionRowsFor(
    context: CompilerContext,
    fact: GraphFactCandidate,
    row: GraphDocumentReviewRow | undefined,
    status: GraphDocumentCompileStatus,
    provenance: GraphDocumentCompilerProvenance,
): GraphDocumentCompiledEntityMention[] {
    const surfaces = [
        ...fact.subjectSurfaces.map((surface) => ({ role: 'subject' as const, surface })),
        ...fact.objectSurfaces.map((surface) => ({ role: 'object' as const, surface })),
    ].slice(0, 8);
    const mentions: GraphDocumentCompiledEntityMention[] = [];
    for (const [index, item] of surfaces.entries()) {
        if (context.entityMentions.length >= MAX_ENTITY_MENTIONS) break;
        const id = `document-mention:${slug(`${fact.id}:${item.role}:${item.surface}:${index}`)}`;
        const mention: GraphDocumentCompiledEntityMention = {
            id,
            surface: item.surface,
            normalizedSurface: normalizeSurface(item.surface),
            resolvedEntityId: context.entityBySurface.get(normalizeSurface(item.surface)),
            role: item.role,
            noteId: fact.noteId,
            sourceStart: fact.start,
            sourceEnd: fact.end,
            confidence: fact.confidence.score,
            status,
            anchorPolicy: 'mention_only_not_user_anchor',
            evidenceSpanIds: fact.evidenceSpanIds,
            provenance: {
                ...provenance,
                sourceReviewRowId: row?.id,
            },
        };
        context.entityMentions.push(mention);
        mentions.push(mention);
    }
    return mentions;
}

function relationFor(
    fact: GraphFactCandidate,
    mentions: GraphDocumentCompiledEntityMention[],
    status: GraphDocumentCompileStatus,
    provenance: GraphDocumentCompilerProvenance,
): GraphDocumentRelationCandidate | null {
    const subjectMentionIds = mentions.filter((mention) => mention.role === 'subject').map((mention) => mention.id);
    const objectMentionIds = mentions.filter((mention) => mention.role === 'object').map((mention) => mention.id);
    const subjectEntityIds = unique(mentions.filter((mention) => mention.role === 'subject').map((mention) => mention.resolvedEntityId || ''));
    const objectEntityIds = unique(mentions.filter((mention) => mention.role === 'object').map((mention) => mention.resolvedEntityId || ''));
    if (!subjectMentionIds.length || !objectMentionIds.length) return null;
    return {
        id: `document-relation:${slug(fact.id)}`,
        predicate: predicateFor(fact.kind),
        subjectMentionIds,
        objectMentionIds,
        subjectEntityIds,
        objectEntityIds,
        evidenceSpanIds: fact.evidenceSpanIds,
        confidence: fact.confidence.score,
        status,
        provenance,
    };
}

function hyperedgeFor(
    fact: GraphFactCandidate,
    mentions: GraphDocumentCompiledEntityMention[],
    status: GraphDocumentCompileStatus,
    provenance: GraphDocumentCompilerProvenance,
): GraphDocumentHyperedge {
    const roles: GraphDocumentHyperedgeRole[] = mentions.map((mention, index) => ({
        id: `document-hyperedge-role:${slug(`${fact.id}:${mention.role}:${index}`)}`,
        role: mention.role,
        targetId: mention.resolvedEntityId || mention.id,
        targetKind: mention.resolvedEntityId ? 'entity' : 'entity_mention',
        surface: mention.surface,
        confidence: mention.confidence,
    }));
    for (const evidenceId of fact.evidenceSpanIds.slice(0, 4)) {
        roles.push({
            id: `document-hyperedge-role:${slug(`${fact.id}:evidence:${evidenceId}`)}`,
            role: 'evidence',
            targetId: evidenceId,
            targetKind: 'evidence_span',
            confidence: evidenceConfidence(evidenceId, provenance),
        });
    }
    if (roles.length < 3) {
        roles.push({
            id: `document-hyperedge-role:${slug(`${fact.id}:claim`)}`,
            role: fact.kind,
            targetId: fact.id,
            targetKind: 'document_unit',
            confidence: fact.confidence.score,
        });
    }
    return {
        id: `document-hyperedge:${slug(fact.id)}`,
        predicate: predicateFor(fact.kind),
        sourceKind: fact.kind,
        roles,
        evidenceSpanIds: fact.evidenceSpanIds,
        confidence: fact.confidence.score,
        status,
        nary: roles.length > 2,
        provenance,
    };
}

function evidenceEdgeFor(
    fact: GraphFactCandidate,
    relation: GraphDocumentRelationCandidate | null,
    hyperedge: GraphDocumentHyperedge,
    mentions: GraphDocumentCompiledEntityMention[],
    status: GraphDocumentCompileStatus,
    provenance: GraphDocumentCompilerProvenance,
): GraphDocumentEvidenceBackedEdge | null {
    const source = relation?.id || mentions[0]?.id || hyperedge.id;
    const target = fact.evidenceSpanIds[0];
    if (!source || !target) return null;
    return {
        id: `document-evidence-edge:${slug(`${source}:${target}`)}`,
        sourceId: source,
        targetId: target,
        relationType: 'supported_by_evidence_span',
        evidenceSpanIds: fact.evidenceSpanIds,
        confidence: fact.confidence.score,
        status,
        provenance,
    };
}

function pushDiffAndReceipt(
    context: CompilerContext,
    input: Omit<GraphDocumentTopologyDiff, 'id' | 'mutationAllowed' | 'topologyCommit' | 'beforeGraph' | 'afterGraph'>
        & { restoreReviewState?: GraphDocumentReviewState },
): void {
    const { restoreReviewState, ...diffInput } = input;
    const mutationAllowed = input.status === 'pending_commit';
    const beforeGraph = context.baseline;
    const afterGraph = mutationAllowed
        ? {
            atomCount: beforeGraph.atomCount + input.createdAtomIds.length,
            factCount: beforeGraph.factCount + input.createdFactIds.length,
            edgeCount: beforeGraph.edgeCount + input.createdEdgeIds.length,
        }
        : beforeGraph;
    const diff: GraphDocumentTopologyDiff = {
        ...diffInput,
        id: `document-topology-diff:${slug(`${input.outputKind}:${input.outputId}`)}`,
        mutationAllowed,
        topologyCommit: mutationAllowed,
        beforeGraph,
        afterGraph,
    };
    const receipt: GraphDocumentTopologyReceipt = {
        id: `document-compiler-receipt:${slug(diff.id)}`,
        topologyDiffId: diff.id,
        outputKind: diff.outputKind,
        outputId: diff.outputId,
        reversible: true,
        mutationAllowed,
        invariant: mutationAllowed
            ? 'document_compiler_reversible_topology_commit'
            : 'document_compiler_ledger_only_no_topology_commit',
        undoPatch: {
            operation: mutationAllowed ? 'remove_document_compiler_outputs' : 'remove_document_compiler_ledger_row',
            removeAtomIds: input.createdAtomIds,
            removeFactIds: input.createdFactIds,
            removeEdgeIds: input.createdEdgeIds,
            restoreReviewState,
        },
        detail: `${input.operation} ${input.outputId} as ${input.status}`,
        createdAt: context.input.builtAt,
    };
    context.topologyDiffs.push(diff);
    context.receipts.push(receipt);
    context.baseline = afterGraph;
}

function statusForFact(
    fact: GraphFactCandidate,
    row: GraphDocumentReviewRow | undefined,
    threshold: number,
    resolvedEntityCount: number,
): GraphDocumentCompileStatus {
    if (row?.state === 'rejected' || row?.state === 'muted') return 'blocked';
    if (row?.state === 'accepted' || row?.state === 'compiled_to_graph') {
        return resolvedEntityCount > 0 ? 'pending_commit' : 'reviewable';
    }
    if (fact.kind === 'relation_bundle' && resolvedEntityCount >= 2 && fact.confidence.score >= threshold) return 'pending_commit';
    if (row?.state === 'ledger_only') return 'ledger_only';
    return 'reviewable';
}

function resolvedEntitiesForFact(context: CompilerContext, fact: GraphFactCandidate): string[] {
    return unique([...fact.subjectSurfaces, ...fact.objectSurfaces]
        .map((surface) => context.entityBySurface.get(normalizeSurface(surface)) || ''));
}

function entitySurfaceIndex(entities: Array<{ id: string; label: string; aliases?: string[] }>): Map<string, string> {
    const index = new Map<string, string>();
    for (const entity of entities) {
        for (const surface of [entity.label, ...(entity.aliases || [])]) {
            const normalized = normalizeSurface(surface);
            if (normalized && !index.has(normalized)) index.set(normalized, entity.id);
        }
    }
    return index;
}

function provenanceFor(
    unit: DocumentUnit | RetrievalUnit | GraphFactCandidate,
    row: GraphDocumentReviewRow | undefined,
    evidenceSpanIds: string[],
): GraphDocumentCompilerProvenance {
    return {
        sourceObjectId: unit.id,
        sourceObjectKind: unit.kind,
        sourceReviewRowId: row?.id,
        reviewState: row?.state,
        noteId: unit.noteId,
        sourceStart: unit.start,
        sourceEnd: unit.end,
        evidenceSpanIds,
        lineageUnitIds: [unit.lineage.documentUnitId, ...unit.lineage.parentUnitIds].filter(Boolean),
        reasons: unit.confidence.reasons,
    };
}

function evidenceConfidence(evidenceId: string, provenance: GraphDocumentCompilerProvenance): number {
    return provenance.evidenceSpanIds.includes(evidenceId) ? 0.8 : 0.5;
}

function counters(context: CompilerContext): GraphDocumentCompilerCounters {
    const byKind = countBy(context.topologyDiffs.map((diff) => diff.outputKind));
    const byStatus = countBy(context.topologyDiffs.map((diff) => diff.status));
    return {
        entityMentions: context.entityMentions.length,
        relationCandidates: context.relationCandidates.length,
        hyperedges: context.hyperedges.length,
        naryHyperedges: context.hyperedges.filter((row) => row.nary).length,
        evidenceBackedEdges: context.evidenceBackedEdges.length,
        crossDocBridges: context.crossDocBridges.length,
        documentStructureEdges: context.documentStructureEdges.length,
        retrievalOverlays: context.retrievalOverlays.length,
        topologyDiffs: context.topologyDiffs.length,
        topologyCommits: context.topologyDiffs.filter((row) => row.topologyCommit).length,
        ledgerOnly: byStatus['ledger_only'] || 0,
        overlayOnly: byStatus['overlay_only'] || 0,
        reviewable: byStatus['reviewable'] || 0,
        blocked: byStatus['blocked'] || 0,
        receipts: context.receipts.length,
        reversibleReceipts: context.receipts.filter((row) => row.reversible).length,
        mutationAllowed: context.receipts.filter((row) => row.mutationAllowed).length,
        highConfidenceFacts: context.highConfidenceFacts,
        reviewedFacts: context.reviewedFacts,
        ambiguousFacts: context.ambiguousFacts,
        byKind,
        byStatus,
    };
}

function predicateFor(kind: GraphFactCandidate['kind']): string {
    if (kind === 'relation_bundle') return 'related_to';
    if (kind === 'n_ary_claim') return 'claims';
    if (kind === 'procedure_step') return 'performs_step';
    return kind.replace(/_/g, '-');
}

function normalizeSurface(value: string): string {
    return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}

function countBy(values: string[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function slug(value: string): string {
    const clean = value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return clean || simpleHash(value);
}

function simpleHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}
