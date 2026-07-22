import type {
    DocumentUnit,
    EvidenceSpan,
    GraphFactCandidate,
    RetrievalUnit,
} from './graph-document-sidecar';
import type {
    GraphDocumentSemanticSituationInstance,
    GraphDocumentSemanticTemporalConflict,
} from './graph-document-semantic';
import type {
    GraphDocumentReviewRow,
    GraphDocumentReviewState,
} from './graph-document-review';
import type {
    BuildGraphDocumentCompilerInput,
    GraphDocumentCompilationReviewItem,
    GraphDocumentCompiledEntityMention,
    GraphDocumentCompileStatus,
    GraphDocumentCompilerBaseline,
    GraphDocumentCompilerCounters,
    GraphDocumentCompilerProvenance,
    GraphDocumentCompilerSummary,
    GraphDocumentCrossDocBridge,
    GraphDocumentEvidenceBackedEdge,
    GraphDocumentHyperedge,
    GraphDocumentHyperedgeRole,
    GraphDocumentRelationCandidate,
    GraphDocumentRetrievalOverlay,
    GraphDocumentStructureEdge,
    GraphDocumentTopologyDiff,
    GraphDocumentTopologyReceipt,
} from './graph-document-compiler-types';

export type * from './graph-document-compiler-types';

interface CompilerContext {
    input: BuildGraphDocumentCompilerInput;
    baseline: GraphDocumentCompilerBaseline;
    reviewByObjectId: Map<string, GraphDocumentReviewRow>;
    evidenceById: Map<string, EvidenceSpan>;
    situationById: Map<string, GraphDocumentSemanticSituationInstance>;
    temporalConflictById: Map<string, GraphDocumentSemanticTemporalConflict>;
    entityBySurface: Map<string, string>;
    entityMentions: GraphDocumentCompiledEntityMention[];
    relationCandidates: GraphDocumentRelationCandidate[];
    hyperedges: GraphDocumentHyperedge[];
    evidenceBackedEdges: GraphDocumentEvidenceBackedEdge[];
    crossDocBridges: GraphDocumentCrossDocBridge[];
    documentStructureEdges: GraphDocumentStructureEdge[];
    retrievalOverlays: GraphDocumentRetrievalOverlay[];
    contradictionReviewQueue: GraphDocumentCompilationReviewItem[];
    mergeReviewQueue: GraphDocumentCompilationReviewItem[];
    topologyDiffs: GraphDocumentTopologyDiff[];
    receipts: GraphDocumentTopologyReceipt[];
    highConfidenceFacts: number;
    reviewedFacts: number;
    ambiguousFacts: number;
    rawPredicateFactsBlocked: number;
    factualityBlocked: number;
    temporalBlocked: number;
}

const DEFAULT_HIGH_CONFIDENCE = 0.84;
const MAX_FACTS = 96;
const MAX_ENTITY_MENTIONS = 384;
const MAX_STRUCTURE_EDGES = 512;
const MAX_RETRIEVAL_OVERLAYS = 256;

export function buildGraphDocumentCompilePlanSummary(
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
        situationById: new Map((input.sidecar.situationInstances || []).map((row) => [row.id, row])),
        temporalConflictById: new Map((input.sidecar.temporalConflicts || []).map((row) => [row.id, row])),
        entityBySurface: entitySurfaceIndex(input.entities || []),
        entityMentions: [],
        relationCandidates: [],
        hyperedges: [],
        evidenceBackedEdges: [],
        crossDocBridges: [],
        documentStructureEdges: [],
        retrievalOverlays: [],
        contradictionReviewQueue: [],
        mergeReviewQueue: [],
        topologyDiffs: [],
        receipts: [],
        highConfidenceFacts: 0,
        reviewedFacts: 0,
        ambiguousFacts: 0,
        rawPredicateFactsBlocked: 0,
        factualityBlocked: 0,
        temporalBlocked: 0,
    };
    compileGraphFacts(context);
    compileReviewQueues(context);
    compileDocumentStructure(context);
    compileRetrievalOverlays(context);
    return {
        schemaVersion: 'phoenix-document-compiler/v2',
        authority: 'typescript_compile_plan',
        nativeCompilerRequired: true,
        mutationPolicy: 'ts_never_commits_document_graph',
        builtAt: input.builtAt,
        sourceSidecarBuiltAt: input.sidecar.builtAt,
        sourceReviewBuiltAt: input.review.builtAt,
        compilePolicy: 'situation_frames_reviewed_or_high_confidence_only',
        sidecarPolicy: 'structure_is_disposable_anchors_are_durable',
        topologyPolicy: 'topology_commits_require_reversible_situation_receipts',
        highConfidenceThreshold: input.highConfidenceThreshold || DEFAULT_HIGH_CONFIDENCE,
        entityMentions: context.entityMentions,
        relationCandidates: context.relationCandidates,
        hyperedges: context.hyperedges,
        evidenceBackedEdges: context.evidenceBackedEdges,
        crossDocBridges: context.crossDocBridges,
        documentStructureEdges: context.documentStructureEdges,
        retrievalOverlays: context.retrievalOverlays,
        contradictionReviewQueue: context.contradictionReviewQueue,
        mergeReviewQueue: context.mergeReviewQueue,
        topologyDiffs: context.topologyDiffs,
        receipts: context.receipts,
        counters: counters(context),
    };
}

function compileGraphFacts(context: CompilerContext): void {
    for (const fact of context.input.sidecar.graphFactCandidates.slice(0, MAX_FACTS)) {
        const row = context.reviewByObjectId.get(fact.id);
        const situation = fact.semanticSituationId
            ? context.situationById.get(fact.semanticSituationId)
            : undefined;
        const resolvedEntityIds = resolvedEntitiesForFact(context, fact);
        const status = statusForFact(
            fact,
            row,
            context.input.highConfidenceThreshold || DEFAULT_HIGH_CONFIDENCE,
            resolvedEntityIds.length,
            situation,
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
        if (!situation || !fact.frame?.frame) {
            context.rawPredicateFactsBlocked += 1;
            pushDiffAndReceipt(context, {
                outputKind: 'relation_candidate',
                outputId: relation?.id || fact.id,
                operation: 'add_relation_candidate',
                status,
                restoreReviewState: row?.state,
                createdAtomIds: mentions.map((mention) => `atom:document-mention:${mention.id}`),
                createdFactIds: relation ? [`fact:document-relation:${relation.id}`] : [],
                createdEdgeIds: [],
                evidenceSpanIds: fact.evidenceSpanIds,
                temporalImpact: temporalImpactFor(fact, situation),
                rationale: ['raw_predicate_has_no_compilable_situation_frame', ...fact.confidence.reasons],
            });
            continue;
        }
        if (!situation.worldStateEligible) context.factualityBlocked += 1;
        if (fact.temporalConflictIds?.length) context.temporalBlocked += 1;
        const hyperedge = hyperedgeFor(fact, situation, mentions, status, provenance);
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
            temporalImpact: temporalImpactFor(fact, situation),
            rationale: [
                `review_state:${row?.state || 'missing'}`,
                `confidence:${fact.confidence.score}`,
                `situation:${situation.id}`,
                `frame:${fact.frame.frame}`,
                `world_state_eligible:${situation.worldStateEligible}`,
                `roles:${hyperedge.roles.length}`,
                ...fact.confidence.reasons,
            ],
        });
    }
}

function compileReviewQueues(context: CompilerContext): void {
    for (const conflict of context.temporalConflictById.values()) {
        const hyperedges = context.hyperedges.filter((edge) =>
            (!!edge.semanticSituationId && conflict.situationIds.includes(edge.semanticSituationId))
            || (edge.temporalConflictIds || []).includes(conflict.id)
        );
        const facts = context.input.sidecar.graphFactCandidates.filter((fact) =>
            !!fact.semanticSituationId && conflict.situationIds.includes(fact.semanticSituationId)
        );
        context.contradictionReviewQueue.push({
            id: `document-compilation-review:contradiction:${slug(conflict.id)}`,
            kind: 'contradiction',
            state: 'proposed',
            title: conflict.kind.replace(/_/g, ' '),
            detail: `Temporal conflict spans ${conflict.situationIds.length} semantic situations.`,
            situationIds: conflict.situationIds,
            hyperedgeIds: hyperedges.map((edge) => edge.id),
            evidenceSpanIds: unique(facts.flatMap((fact) => fact.evidenceSpanIds)),
            confidence: conflict.confidenceMillis / 1000,
            reasons: unique([...conflict.detectorReasons, ...conflict.failureReasons]),
            recommendedAction: 'resolve_temporal_conflict',
            mutationAllowed: false,
        });
    }
    const byMergeKey = new Map<string, GraphDocumentHyperedge[]>();
    for (const hyperedge of context.hyperedges) {
        if (hyperedge.status === 'blocked' || !hyperedge.mergeKey) continue;
        byMergeKey.set(hyperedge.mergeKey, [...(byMergeKey.get(hyperedge.mergeKey) || []), hyperedge]);
    }
    for (const [mergeKey, hyperedges] of byMergeKey) {
        const situationIds = unique(hyperedges.map((edge) => edge.semanticSituationId || ''));
        if (situationIds.length < 2) continue;
        context.mergeReviewQueue.push({
            id: `document-compilation-review:merge:${slug(mergeKey)}`,
            kind: 'merge',
            state: 'proposed',
            title: `Possible duplicate ${hyperedges[0].frame} situations`,
            detail: `${situationIds.length} situations share the same frame and participant signature.`,
            situationIds,
            hyperedgeIds: hyperedges.map((edge) => edge.id),
            evidenceSpanIds: unique(hyperedges.flatMap((edge) => edge.evidenceSpanIds)),
            confidence: Math.min(...hyperedges.map((edge) => edge.confidence)),
            reasons: ['same_frame', 'same_role_typed_participants', 'distinct_situation_evidence'],
            recommendedAction: 'merge_duplicate_situations',
            mutationAllowed: false,
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
            temporalImpact: emptyTemporalImpact(),
            rationale: ['sidecar_structure_overlay', ...unit.confidence.reasons],
        });
    }
}

function compileRetrievalOverlays(context: CompilerContext): void {
    for (const unit of context.input.sidecar.retrievalUnits.slice(0, MAX_RETRIEVAL_OVERLAYS)) {
        const row = context.reviewByObjectId.get(unit.id);
        const provenance = provenanceFor(unit, row, unit.evidenceSpanIds);
        const semanticSituationIds = situationIdsForRetrieval(context, unit);
        if (unit.kind === 'cross_doc_topic_packet') {
            const bridge: GraphDocumentCrossDocBridge = {
                id: `document-crossdoc-bridge:${slug(unit.id)}`,
                topic: unit.label,
                noteIds: context.input.sidecar.noteIds,
                retrievalUnitId: unit.id,
                semanticSituationIds,
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
                temporalImpact: emptyTemporalImpact(),
                rationale: ['cross_doc_topic_packet_overlay', ...unit.confidence.reasons],
            });
        }
        const overlay: GraphDocumentRetrievalOverlay = {
            id: `document-retrieval-overlay:${slug(unit.id)}`,
            retrievalUnitId: unit.id,
            retrievalKind: unit.kind,
            semanticSituationIds,
            keyedBy: semanticSituationIds.length ? 'semantic_situation' : 'retrieval_unit_fallback',
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
            temporalImpact: emptyTemporalImpact(),
            rationale: [
                `retrieval:${unit.kind}`,
                `situation_keys:${semanticSituationIds.length}`,
                ...unit.confidence.reasons,
            ],
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
    type MentionSurface = {
        role: string;
        surface: string;
        syntacticRoles?: string[];
        roleConfidence?: number;
        roleFailureReasons?: string[];
        recoveryKinds?: string[];
        roleDetectorReasons?: string[];
    };
    const surfaces: MentionSurface[] = (fact.roles?.length
        ? fact.roles.flatMap((role) => role.surfaces.map((surface) => ({
            role: role.role,
            surface,
            syntacticRoles: role.syntacticRoles,
            roleConfidence: role.confidence,
            roleFailureReasons: role.failureReasons,
            recoveryKinds: role.recoveryKinds,
            roleDetectorReasons: role.detectorReasons,
        })))
        : [
            ...fact.subjectSurfaces.map((surface) => ({ role: 'subject', surface })),
            ...fact.objectSurfaces.map((surface) => ({ role: 'object', surface })),
        ]).slice(0, 8);
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
            syntacticRoles: item.syntacticRoles,
            roleConfidence: item.roleConfidence,
            roleFailureReasons: item.roleFailureReasons,
            recoveryKinds: item.recoveryKinds,
            roleDetectorReasons: item.roleDetectorReasons,
            noteId: fact.noteId,
            sourceStart: fact.start,
            sourceEnd: fact.end,
            confidence: item.roleConfidence ?? fact.confidence.score,
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
    const subjectMentionIds = mentions.filter((mention) => isSubjectLikeRole(mention.role)).map((mention) => mention.id);
    const objectMentionIds = mentions.filter((mention) => !isSubjectLikeRole(mention.role)).map((mention) => mention.id);
    const subjectEntityIds = unique(mentions.filter((mention) => isSubjectLikeRole(mention.role)).map((mention) => mention.resolvedEntityId || ''));
    const objectEntityIds = unique(mentions.filter((mention) => !isSubjectLikeRole(mention.role)).map((mention) => mention.resolvedEntityId || ''));
    if (!subjectMentionIds.length || !objectMentionIds.length) return null;
    return {
        id: `document-relation:${slug(fact.id)}`,
        predicate: fact.predicate || predicateFor(fact.kind),
        frame: fact.frame?.frame,
        frameFamily: fact.frameFamily,
        factuality: fact.factuality?.factuality,
        speechAct: fact.factuality?.speechAct,
        semanticSituationId: fact.semanticSituationId,
        stateIntervalIds: fact.stateIntervalIds,
        eventOrderingIds: fact.eventOrderingIds,
        temporalConflictIds: fact.temporalConflictIds,
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
    situation: GraphDocumentSemanticSituationInstance,
    mentions: GraphDocumentCompiledEntityMention[],
    status: GraphDocumentCompileStatus,
    provenance: GraphDocumentCompilerProvenance,
): GraphDocumentHyperedge {
    const roles: GraphDocumentHyperedgeRole[] = mentions.map((mention, index) => ({
        id: `document-hyperedge-role:${slug(`${fact.id}:${mention.role}:${index}`)}`,
        role: mention.role,
        semanticRole: mention.role,
        slotType: hyperedgeSlotType(mention.role),
        syntacticRoles: mention.syntacticRoles,
        targetId: mention.resolvedEntityId || mention.id,
        targetKind: mention.resolvedEntityId ? 'entity' : 'entity_mention',
        surface: mention.surface,
        confidence: mention.confidence,
        required: fact.frame?.expectedRoles.includes(mention.role) || false,
        resolved: Boolean(mention.resolvedEntityId),
        failureReasons: mention.roleFailureReasons,
        recoveryKinds: mention.recoveryKinds,
        detectorReasons: mention.roleDetectorReasons,
    }));
    for (const evidenceId of fact.evidenceSpanIds.slice(0, 4)) {
        roles.push({
            id: `document-hyperedge-role:${slug(`${fact.id}:evidence:${evidenceId}`)}`,
            role: 'evidence',
            semanticRole: 'evidence',
            slotType: 'evidence',
            targetId: evidenceId,
            targetKind: 'evidence_span',
            confidence: evidenceConfidence(evidenceId, provenance),
            required: true,
            resolved: true,
        });
    }
    if (roles.length < 3) {
        roles.push({
            id: `document-hyperedge-role:${slug(`${fact.id}:claim`)}`,
            role: fact.kind,
            semanticRole: fact.kind,
            slotType: 'source_unit',
            targetId: fact.id,
            targetKind: 'document_unit',
            confidence: fact.confidence.score,
            required: false,
            resolved: true,
        });
    }
    const frame = fact.frame?.frame || 'unclassified_situation';
    return {
        id: `document-situation-hyperedge:${slug(situation.id)}`,
        predicate: frame,
        triggerPredicate: fact.predicate || predicateFor(fact.kind),
        frame,
        frameFamily: fact.frameFamily,
        situationKind: situation.situationKind,
        factuality: fact.factuality?.factuality,
        speechAct: fact.factuality?.speechAct,
        worldStateEligible: situation.worldStateEligible,
        semanticSituationId: situation.id,
        semanticPropositionId: fact.semanticPropositionId,
        stateIntervalIds: fact.stateIntervalIds || [],
        eventOrderingIds: fact.eventOrderingIds || [],
        temporalConflictIds: fact.temporalConflictIds || [],
        compilationBasis: 'semantic_situation_frame',
        mergeKey: hyperedgeMergeKey(frame, roles),
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
    const nativeCompileCandidate = input.status === 'pending_commit' && input.outputKind === 'hyperedge';
    const mutationAllowed = false;
    const beforeGraph = context.baseline;
    const afterGraph = beforeGraph;
    const diff: GraphDocumentTopologyDiff = {
        ...diffInput,
        id: `document-topology-diff:${slug(`${input.outputKind}:${input.outputId}`)}`,
        nativeCompileCandidate,
        mutationAllowed,
        topologyCommit: false,
        beforeGraph,
        afterGraph,
    };
    const receipt: GraphDocumentTopologyReceipt = {
        id: `document-compiler-receipt:${slug(diff.id)}`,
        topologyDiffId: diff.id,
        outputKind: diff.outputKind,
        outputId: diff.outputId,
        semanticSituationId: diff.temporalImpact?.semanticSituationId,
        reversible: true,
        mutationAllowed,
        invariant: nativeCompileCandidate
            ? 'document_compiler_native_payload_candidate'
            : 'document_compiler_ledger_only_no_topology_commit',
        undoPatch: {
            operation: 'remove_document_compiler_ledger_row',
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

function temporalImpactFor(
    fact: GraphFactCandidate,
    situation: GraphDocumentSemanticSituationInstance | undefined,
): GraphDocumentTopologyDiff['temporalImpact'] {
    const conflicts = fact.temporalConflictIds || [];
    return {
        semanticSituationId: situation?.id,
        stateIntervalIds: fact.stateIntervalIds || [],
        eventOrderingIds: fact.eventOrderingIds || [],
        temporalConflictIds: conflicts,
        factualityDecision: !situation
            ? 'not_applicable'
            : situation.worldStateEligible ? 'eligible' : 'review_required',
        temporalDecision: !situation
            ? 'not_applicable'
            : conflicts.length ? 'review_required' : 'stable',
    };
}

function emptyTemporalImpact(): GraphDocumentTopologyDiff['temporalImpact'] {
    return {
        stateIntervalIds: [],
        eventOrderingIds: [],
        temporalConflictIds: [],
        factualityDecision: 'not_applicable',
        temporalDecision: 'not_applicable',
    };
}

function situationIdsForRetrieval(context: CompilerContext, unit: RetrievalUnit): string[] {
    const evidenceIds = new Set(unit.evidenceSpanIds);
    const matches = context.input.sidecar.graphFactCandidates.flatMap((fact) => {
        if (!fact.semanticSituationId || fact.noteId !== unit.noteId) return [];
        const evidenceMatch = fact.evidenceSpanIds.some((id) => evidenceIds.has(id));
        const rangeMatch = fact.start < unit.end && fact.end > unit.start;
        return evidenceMatch || rangeMatch ? [fact.semanticSituationId] : [];
    });
    return unique(matches).slice(0, 24);
}

function statusForFact(
    fact: GraphFactCandidate,
    row: GraphDocumentReviewRow | undefined,
    threshold: number,
    resolvedEntityCount: number,
    situation: GraphDocumentSemanticSituationInstance | undefined,
): GraphDocumentCompileStatus {
    if (row?.state === 'rejected' || row?.state === 'muted') return 'blocked';
    if (row?.state === 'ledger_only') return 'ledger_only';
    if (!situation || !fact.frame?.frame) return 'reviewable';
    if (!situation.worldStateEligible || fact.factuality?.asserted === false) return 'reviewable';
    if (fact.temporalConflictIds?.length) return 'reviewable';
    if (row?.state === 'accepted' || row?.state === 'compiled_to_graph') {
        return resolvedEntityCount > 0 ? 'pending_commit' : 'reviewable';
    }
    if (fact.kind === 'relation_bundle'
        && resolvedEntityCount >= 2
        && fact.confidence.score >= threshold
        && situation.confidenceMillis / 1000 >= threshold) return 'pending_commit';
    return 'reviewable';
}

function hyperedgeSlotType(role: string): GraphDocumentHyperedgeRole['slotType'] {
    return ['location', 'time', 'manner', 'instrument', 'cause', 'purpose', 'condition'].includes(role)
        ? 'context'
        : 'participant';
}

function hyperedgeMergeKey(frame: string, roles: GraphDocumentHyperedgeRole[]): string {
    const signature = roles
        .filter((role) => role.slotType === 'participant')
        .map((role) => `${role.semanticRole}:${normalizeSurface(role.targetId || role.surface || '')}`)
        .sort()
        .join('|');
    return `${frame}|${signature}`;
}

function isSubjectLikeRole(role: string): boolean {
    return ['subject', 'actor', 'agent', 'bearer', 'experiencer', 'topic'].includes(role);
}

function resolvedEntitiesForFact(context: CompilerContext, fact: GraphFactCandidate): string[] {
    const surfaces = fact.roles?.length
        ? fact.roles.flatMap((role) => role.surfaces)
        : [...fact.subjectSurfaces, ...fact.objectSurfaces];
    return unique(surfaces
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
        reasons: unit.confidence.reasons.concat(
            'semanticSituationId' in unit && unit.semanticSituationId
                ? [
                    `situation:${unit.semanticSituationId}`,
                    ...(unit.stateIntervalIds || []).map((id) => `state_interval:${id}`),
                    ...(unit.eventOrderingIds || []).map((id) => `event_ordering:${id}`),
                    ...(unit.temporalConflictIds || []).map((id) => `temporal_conflict:${id}`),
                ]
                : [],
        ),
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
        situationFrameHyperedges: context.hyperedges.filter((row) => row.compilationBasis === 'semantic_situation_frame').length,
        rawPredicateFactsBlocked: context.rawPredicateFactsBlocked,
        factualityBlocked: context.factualityBlocked,
        temporalBlocked: context.temporalBlocked,
        naryHyperedges: context.hyperedges.filter((row) => row.nary).length,
        evidenceBackedEdges: context.evidenceBackedEdges.length,
        crossDocBridges: context.crossDocBridges.length,
        documentStructureEdges: context.documentStructureEdges.length,
        retrievalOverlays: context.retrievalOverlays.length,
        situationKeyedRetrievalOverlays: context.retrievalOverlays.filter((row) => row.keyedBy === 'semantic_situation').length,
        contradictionReviewItems: context.contradictionReviewQueue.length,
        mergeReviewItems: context.mergeReviewQueue.length,
        topologyDiffs: context.topologyDiffs.length,
        topologyCommits: context.topologyDiffs.filter((row) => row.topologyCommit).length,
        nativeCompileCandidates: context.topologyDiffs.filter((row) => row.nativeCompileCandidate).length,
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
