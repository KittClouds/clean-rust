import type { RegisteredEntity } from '../lib/registry';
import type {
    BuildGraphRebuildSnapshotInput,
    GraphRebuildChunk,
    GraphRebuildChunkSemanticBridge,
    GraphRebuildChunkSemanticBridgeType,
    GraphRebuildDropReasons,
    GraphRebuildEdge,
    GraphRebuildEntityAnchor,
    GraphRebuildMention,
    GraphRebuildNode,
    GraphRebuildRelationship,
    GraphRebuildRelationshipHint,
    GraphRebuildSignalTargetLane,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import { deriveGraphRebuildFacts } from './graph-rebuild-derived-facts';
import { buildGraphRebuildEmbeddingTargetPlan } from './graph-rebuild-embedding-targets';
import { buildGraphRebuildEmbeddingGraphPostProcess } from './graph-rebuild-embedding-postprocess';
import { buildGraphRebuildEntityLinkSuggestions } from './graph-rebuild-entity-linking';
import { buildGraphAwareLinkSuggestions } from './graph-rebuild-link-suggestions';
import { buildGraphRebuildFinalLinkPatchLog } from './graph-rebuild-final-linking';
import { buildBundleDedupeShadowLinks } from './graph-rebuild-shadow-linking';
import { buildCompatibilityGraphCompilerSidecar } from './graph-compiler-compat';
import { attachGraphCompilerReadModels } from './graph-compiler-read-model';
import { buildGraphRebuildStructuralPostProcess } from './graph-rebuild-structural-postprocess';
import {
    buildGraphRebuildAliasResolver,
    normalizeGraphRebuildCandidate,
    prepareGraphRebuildAnchors,
} from './graph-rebuild-anchor-hygiene';
import { buildGraphSemanticTaskSummary } from './graph-semantic-tasks';
import { buildGraphSemanticCandidateSummary } from './graph-semantic-candidates';
import { buildGraphManifoldSpecializationSummary } from './graph-manifold-specialization';
import { buildGraphSemanticRerankSummary } from './graph-semantic-rerank';
import {
    buildGraphSemanticAdjudicationDAGSummary,
} from './graph-semantic-adjudication';
import { buildGraphSemanticEvalLedgerSummary } from './graph-semantic-eval-ledger';
import { GraphSemanticDerivationContext } from './graph-semantic-derivation-context';
import { buildGraphCalendarRegistryBridgeSummary } from './graph-calendar-registry-bridge';
import { buildGraphMemoryGraphRagBridgeSummary } from './graph-memory-graphrag-bridge';
import { episodeProjectionEdgeCounters } from './graph-episode-projection';
import { buildGraphDiscourseSpineSummary } from './graph-discourse-spine';
import { buildGraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';
import { buildGraphDiscourseBridgeAdjudicationSummary } from './graph-discourse-bridge-adjudication';
import { buildGraphDiscourseEvalLedgerSummary } from './graph-discourse-eval-ledger';
import { buildGraphDiscoursePromotionSurfaceSummary } from './graph-discourse-promotion-surface';
import { buildGraphDiscourseCompilerOverlaySummary } from './graph-discourse-compiler-overlay';
import { buildHopfResonanceSpace } from './graph-hopf-resonance-space';
import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import { buildGraphDocumentReviewSummary } from './graph-document-review';
import { buildGraphDocumentCompilePlanSummary } from './graph-document-compiler';
import { replayGraphOperatorMutationJournalReview } from './graph-operator-mutation-journal';
import { sealGraphEvidenceTargetRegistry } from './graph-evidence-target-registry';
import { assertGraphSemanticDiscoveriesRemainCandidates } from './graph-semantic-discovery-authority';

export { buildGraphRebuildAliasResolver, normalizeGraphRebuildCandidate };

const CO_OCCURRENCE_MAX_GAP_CHARS = 720;
const CO_OCCURRENCE_LINKS_PER_ANCHOR = 4;

/** Builds the source-evidence snapshot rows that the Rust Atlas packet seals. */
export function buildGraphRebuildSnapshot(input: BuildGraphRebuildSnapshotInput): GraphRebuildSnapshot {
    input.cpuProfiler?.begin();
    const builtAt = input.builtAt ?? Date.now();
    const chunks = normalizeChunks(input.chunks || []);
    const chunksByNote = groupChunksByNote(chunks);
    const entitiesById = new Map(input.entities.map((entity) => [entity.id, entity]));
    const resolver = buildGraphRebuildAliasResolver(input.entities);
    const allowedNotes = new Set(input.noteIds || []);
    const hygiene = prepareGraphRebuildAnchors({
        occurrences: input.occurrences,
        entitiesById,
        resolver,
        chunksByNote,
        allowedNotes,
        builtAt,
    });
    const { mentions, entityAnchors, dropReasons: drops } = hygiene;
    input.cpuProfiler?.mark('snapshotAnchorsMs');

    const nodes = buildNodes(entityAnchors, entitiesById);
    const cooccurrenceEdges = buildEdges(entityAnchors, drops);
    const derived = deriveGraphRebuildFacts(chunks, entityAnchors, input.noteTexts || {}, input.causalSidecar);
    const edges = [...cooccurrenceEdges, ...derived.edges]
        .sort((left, right) => right.weight - left.weight || left.type.localeCompare(right.type) || left.id.localeCompare(right.id));
    const relationships = applyRelationshipHints([...cooccurrenceEdges.map(edgeToRelationship), ...derived.relationships], input.relationshipHints || []);
    const structuralPostProcess = buildGraphRebuildStructuralPostProcess(nodes, edges);
    const acceptedRelationships = relationships.filter((relationship) => relationship.status === 'accepted').length;
    const reviewRelationships = relationships.filter((relationship) => relationship.status === 'review').length;
    const rejectedRelationships = relationships.filter((relationship) => relationship.status === 'rejected').length;
    const noteIds = input.noteIds ? [...input.noteIds] : unique([
        ...chunks.map((chunk) => chunk.noteId),
        ...entityAnchors.map((anchor) => anchor.noteId),
    ]);
    input.cpuProfiler?.mark('snapshotFactsMs');
    const documentSidecarSummary = buildGraphDocumentSidecar({
        noteIds,
        noteTexts: input.noteTexts || {},
        chunks,
        builtAt,
        documentProfileSummary: input.documentProfileSummary,
        documentSemanticSummary: input.documentSemanticSummary,
    });
    const baseDocumentReviewSummary = buildGraphDocumentReviewSummary(documentSidecarSummary, builtAt);
    const operatorReplay = input.operatorMutationJournal
        ? replayGraphOperatorMutationJournalReview(
            baseDocumentReviewSummary,
            input.operatorMutationJournal,
            input.scopeId,
            builtAt,
        )
        : null;
    const documentReviewSummary = operatorReplay?.review || baseDocumentReviewSummary;
    const operatorMutationJournal = operatorReplay?.journal;
    const documentCompilerSummary = buildGraphDocumentCompilePlanSummary({
        sidecar: documentSidecarSummary,
        review: documentReviewSummary,
        builtAt,
        entities: nodes.map((node) => ({ id: node.entityId, label: node.label, aliases: node.aliases })),
        baseline: {
            atomCount: nodes.length,
            factCount: relationships.length
                + derived.events.length
                + derived.temporalEdges.length
                + derived.causalEdges.length
                + derived.memoryState.length,
            edgeCount: edges.length,
        },
    });
    input.cpuProfiler?.mark('snapshotCompatibilityViewsMs');
    const embeddingTargetPlan = buildGraphRebuildEmbeddingTargetPlan(
        input,
        chunks,
        entityAnchors,
        nodes,
        relationships,
        derived.events,
        derived.episodes,
        derived.episodeConnections,
        derived.temporalEdges,
        derived.causalEdges,
        derived.memoryState,
        documentCompilerSummary,
    );
    const embeddingTargets = embeddingTargetPlan.targets;
    const queuedTargetIds = new Set(embeddingTargetPlan.queuedTargetIds || []);
    const embeddingWorkTargets = embeddingTargets.filter((target) =>
        queuedTargetIds.size ? queuedTargetIds.has(target.id) : target.admissionStatus === 'admitted',
    );
    const postProcessMode = input.postProcessMode || 'full';
    const includeDiagnosticArms = input.durabilityMode !== 'interactive';
    input.cpuProfiler?.mark('snapshotTargetsMs');
    const embeddingPostProcessStarted = performance.now();
    const embeddingGraphPostProcess = postProcessMode === 'full'
        ? buildGraphRebuildEmbeddingGraphPostProcess(
            embeddingWorkTargets,
            input.embeddingProfile,
            input.cpuProfiler,
        )
        : undefined;
    input.cpuProfiler?.add('snapshotEmbeddingPostProcessMs', embeddingPostProcessStarted);
    const graphAwareLinksStarted = performance.now();
    const graphAwareLinkSuggestions = postProcessMode === 'full'
        ? buildGraphAwareLinkSuggestions(
            nodes,
            edges,
            relationships,
            structuralPostProcess,
            embeddingGraphPostProcess,
        )
        : [];
    input.cpuProfiler?.add('snapshotGraphAwareLinksMs', graphAwareLinksStarted);
    const entityLinkerEnabled = input.embeddingStagePolicy?.entityLinkerEnabled !== false;
    const entityLinkingStarted = performance.now();
    const entityLinking = postProcessMode === 'full' && entityLinkerEnabled
        ? buildGraphRebuildEntityLinkSuggestions({
            mentions,
            entityAnchors,
            nodes,
            edges,
            relationships,
            structuralPostProcess,
            embeddingGraphPostProcess,
        })
        : { suggestions: [], counters: emptyEntityLinkCounters(mentions) };
    input.cpuProfiler?.add('snapshotEntityLinkingMs', entityLinkingStarted);
    input.cpuProfiler?.mark('snapshotPostProcessMs');
    let snapshot: GraphRebuildSnapshot = {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: `graph-rebuild:${input.scopeKind}:${input.scopeId}:${builtAt}`,
        source: 'phoenix-graph-rebuild',
        scopeKind: input.scopeKind,
        scopeId: input.scopeId,
        noteIds,
        builtAt,
        chunks,
        mentions,
        entityAnchors,
        relationships,
        events: derived.events,
        episodes: derived.episodes,
        chunkSemanticBridges: derived.chunkSemanticBridges,
        episodeConnections: derived.episodeConnections,
        episodeProjectionEdges: derived.episodeProjectionEdges,
        temporalEdges: derived.temporalEdges,
        causalEdges: derived.causalEdges,
        memoryState: derived.memoryState,
        memoryGovernanceCandidates: [],
        embeddingTargets,
        embeddingTargetPlan,
        embeddingVectors: [],
        embeddingProfile: embeddingGraphPostProcess?.profile,
        embeddingModelAdapter: embeddingGraphPostProcess?.adapter,
        embeddingGraphPostProcess,
        projectionRefs: [],
        nodes,
        edges,
        structuralPostProcess,
        graphAwareLinkSuggestions,
        entityLinkSuggestions: entityLinking.suggestions,
        documentSidecarSummary,
        documentSemanticSummary: input.documentSemanticSummary,
        documentReviewSummary,
        documentCompilerSummary,
        operatorMutationJournal,
        counters: {
            entities: input.entities.length,
            aliases: resolver.aliasCount,
            candidates: input.candidateCount ?? 0,
            mentions: mentions.length,
            acceptedAnchors: entityAnchors.length,
            chunks: chunks.length,
            anchorEvidence: entityAnchors.length,
            relationSignals: relationships.length,
            promotedFacts: acceptedRelationships
                + derived.events.length
                + derived.temporalEdges.length
                + derived.causalEdges.length
                + derived.memoryState.length,
            relationshipCandidates: relationships.length,
            relationships: relationships.length,
            acceptedRelationships,
            reviewRelationships,
            rejectedRelationships,
            events: derived.events.length,
            episodes: derived.episodes.length,
            chunkSemanticBridges: derived.chunkSemanticBridges.length,
            chunkSetupPayoffBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'setup_payoff'),
            chunkCauseEffectBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'cause_effect'),
            chunkStateDeltaBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'state_delta'),
            chunkRelationshipDeltaBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'relationship_delta'),
            chunkTopicContinuationBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'topic_continuation'),
            chunkEvidenceReframeBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'evidence_reframe'),
            chunkMotifEchoBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'motif_echo'),
            chunkRouteContinuityBridges: countChunkSemanticBridges(derived.chunkSemanticBridges, 'route_continuity'),
            episodeConnections: derived.episodeConnections.length,
            episodeTemporalConnections: derived.episodeConnections.filter((connection) => connection.kind === 'episode_temporal').length,
            episodeCausalConnections: derived.episodeConnections.filter((connection) => connection.kind === 'episode_causal').length,
            episodeWormholeConnections: derived.episodeConnections.filter((connection) => connection.kind === 'episode_wormhole').length,
            ...episodeProjectionEdgeCounters(derived.episodeProjectionEdges),
            temporalEdges: derived.temporalEdges.length,
            causalEdges: derived.causalEdges.length,
            memoryState: derived.memoryState.length,
            memoryGovernanceCandidates: 0,
            memoryGovernanceBuildMicros: 0,
            memoryGovernanceRetain: 0,
            memoryGovernanceAttenuate: 0,
            memoryGovernanceCompress: 0,
            memoryGovernanceQuarantine: 0,
            memoryGovernanceRetire: 0,
            memoryGovernanceRetrievalCandidates: 0,
            memoryGovernanceRetrievalGoverned: 0,
            memoryGovernanceRetrievalChangedRanks: 0,
            memoryGovernanceRetrievalPolicies: 0,
            promotionVerdictRows: 0,
            promotionVerdictAcceptable: 0,
            promotionVerdictBlocked: 0,
            promotionVerdictAlreadyCommitted: 0,
            promotionVerdictRollbackAvailable: 0,
            embeddingTargets: embeddingTargets.length,
            embeddingTargetCandidates: embeddingTargetPlan.candidateCount,
            embeddingQueuedTargets: embeddingWorkTargets.length,
            embeddingTargetDeferred: embeddingTargetPlan.deferredCount,
            embeddingSchedulerDeferredTargets: embeddingTargetPlan.schedulerDeferredCount,
            embeddingPolicyDeferredTargets: embeddingTargetPlan.policyDeferredCount,
            embeddingDocumentSpine: planLaneCandidates(embeddingTargetPlan, 'document_spine'),
            embeddingChunkSpine: planLaneCandidates(embeddingTargetPlan, 'chunk_spine'),
            embeddingEntityAnchors: planLaneCandidates(embeddingTargetPlan, 'entity_anchor'),
            embeddingRelationshipFacts: planLaneCandidates(embeddingTargetPlan, 'relationship_fact'),
            embeddingTemporalFacts: planLaneCandidates(embeddingTargetPlan, 'temporal_fact'),
            embeddingCausalFacts: planLaneCandidates(embeddingTargetPlan, 'causal_fact'),
            embeddingMemoryStates: planLaneCandidates(embeddingTargetPlan, 'memory_state'),
            embeddingEventIdentities: planLaneCandidates(embeddingTargetPlan, 'event_identity'),
            embeddingAnchorEvidence: planLaneCandidates(embeddingTargetPlan, 'anchor_evidence'),
            embeddingVectors: 0,
            projectionRefs: 0,
            nodes: nodes.length,
            edges: edges.length,
            structuralComponents: structuralPostProcess.components.length,
            structuralHubs: structuralPostProcess.hubEntityIds.length,
            structuralBridgeEdges: structuralPostProcess.bridgeEdgeIds.length,
            embeddingClusters: embeddingGraphPostProcess?.metrics.clusterCount || 0,
            embeddingSingletonClusters: embeddingGraphPostProcess?.metrics.singletonCount || 0,
            embeddingBackboneEdges: embeddingGraphPostProcess?.metrics.backboneEdgeCount || 0,
            embeddingBridgeEdges: embeddingGraphPostProcess?.metrics.bridgeEdgeCount || 0,
            embeddingOutliers: embeddingGraphPostProcess?.metrics.outlierCount || 0,
            embeddingPlannedPairs: embeddingGraphPostProcess?.metrics.plannedPairCount || 0,
            embeddingTheoreticalPairs: embeddingGraphPostProcess?.metrics.theoreticalPairCount || 0,
            embeddingPrunedPairs: embeddingGraphPostProcess?.metrics.prunedPairCount || 0,
            graphAwareLinkSuggestions: graphAwareLinkSuggestions.length,
            entityLinkSuggestions: entityLinking.suggestions.length,
            entityLinking: entityLinking.counters,
            meaningFrameChunks: chunks.filter((chunk) => Boolean(chunk.meaningFrame)).length,
            documentSidecarUnits: documentSidecarSummary.counters.units,
            documentSidecarSections: documentSidecarSummary.counters.sections,
            documentSidecarRegions: documentSidecarSummary.counters.regions,
            documentSidecarRhetoricalUnits: documentSidecarSummary.counters.rhetoricalUnits,
            documentSidecarRetrievalUnits: documentSidecarSummary.counters.retrievalUnits,
            documentSidecarGraphFacts: documentSidecarSummary.counters.graphFactCandidates,
            documentSidecarSituationInstances: documentSidecarSummary.counters.situationInstances,
            documentSidecarStateIntervals: documentSidecarSummary.counters.stateIntervals,
            documentSidecarEventOrderings: documentSidecarSummary.counters.eventOrderings,
            documentSidecarTemporalConflicts: documentSidecarSummary.counters.temporalConflicts,
            documentSidecarEvidenceSpans: documentSidecarSummary.counters.evidenceSpans,
            documentSidecarAnchorPromotions: documentSidecarSummary.counters.userAnchorPromotions,
            documentSemanticPropositions: input.documentSemanticSummary?.counters.propositions || 0,
            documentSemanticArguments: input.documentSemanticSummary?.counters.arguments || 0,
            documentSemanticResolvedArguments: input.documentSemanticSummary?.counters.resolvedArguments || 0,
            documentSemanticRoleAnnotations: input.documentSemanticSummary?.counters.roleAnnotations || 0,
            documentSemanticUnresolvedRoleSurfaces: input.documentSemanticSummary?.counters.unresolvedRoleSurfaces || 0,
            documentSemanticRoleFailureReasons: input.documentSemanticSummary?.counters.roleFailureReasons || 0,
            documentSemanticFrameAnnotations: input.documentSemanticSummary?.counters.frameAnnotations || 0,
            documentSemanticLexicalFrames: input.documentSemanticSummary?.counters.lexicalFrameMatches || 0,
            documentSemanticFallbackFrames: input.documentSemanticSummary?.counters.fallbackFrameMatches || 0,
            documentSemanticLowConfidenceFrames: input.documentSemanticSummary?.counters.lowConfidenceFrames || 0,
            documentSemanticFrameFailureReasons: input.documentSemanticSummary?.counters.frameFailureReasons || 0,
            documentSemanticFactualityAnnotations: input.documentSemanticSummary?.counters.factualityAnnotations || 0,
            documentSemanticScopedFactuality: input.documentSemanticSummary?.counters.scopedFactuality || 0,
            documentSemanticAttributedFactuality: input.documentSemanticSummary?.counters.attributedFactuality || 0,
            documentSemanticQuotedFactuality: input.documentSemanticSummary?.counters.quotedFactuality || 0,
            documentSemanticConditionalFactuality: input.documentSemanticSummary?.counters.conditionalFactuality || 0,
            documentSemanticSpeechOrBeliefFrames: input.documentSemanticSummary?.counters.speechOrBeliefFrames || 0,
            documentSemanticLowConfidenceFactuality: input.documentSemanticSummary?.counters.lowConfidenceFactuality || 0,
            documentSemanticFactualityFailureReasons: input.documentSemanticSummary?.counters.factualityFailureReasons || 0,
            documentSemanticArgumentRecoveries: input.documentSemanticSummary?.counters.documentArgumentRecoveries || 0,
            documentSemanticLocalCoreferenceRecoveries: input.documentSemanticSummary?.counters.localCoreferenceRecoveries || 0,
            documentSemanticAliasContinuityRecoveries: input.documentSemanticSummary?.counters.aliasContinuityRecoveries || 0,
            documentSemanticOmittedSubjectRecoveries: input.documentSemanticSummary?.counters.omittedSubjectRecoveries || 0,
            documentSemanticQuoteSpeakerRecoveries: input.documentSemanticSummary?.counters.quoteSpeakerRecoveries || 0,
            documentSemanticRepeatedEventLinks: input.documentSemanticSummary?.counters.repeatedEventLinks || 0,
            documentSemanticWindowArgumentCompletions: input.documentSemanticSummary?.counters.windowArgumentCompletions || 0,
            documentSemanticLowConfidenceRecoveries: input.documentSemanticSummary?.counters.lowConfidenceRecoveries || 0,
            documentSemanticRecoveryFailureReasons: input.documentSemanticSummary?.counters.recoveryFailureReasons || 0,
            documentSemanticSituationInstances: input.documentSemanticSummary?.counters.situationInstances || 0,
            documentSemanticStateIntervals: input.documentSemanticSummary?.counters.stateIntervals || 0,
            documentSemanticEventOrderings: input.documentSemanticSummary?.counters.eventOrderings || 0,
            documentSemanticExplicitEventOrderings: input.documentSemanticSummary?.counters.explicitEventOrderings || 0,
            documentSemanticRecurrenceOrderings: input.documentSemanticSummary?.counters.recurrenceOrderings || 0,
            documentSemanticPersistentStateIntervals: input.documentSemanticSummary?.counters.persistentStateIntervals || 0,
            documentSemanticTerminatedStateIntervals: input.documentSemanticSummary?.counters.terminatedStateIntervals || 0,
            documentSemanticTemporalConflicts: input.documentSemanticSummary?.counters.temporalConflicts || 0,
            documentSemanticWorldStateIneligibleSituations: input.documentSemanticSummary?.counters.worldStateIneligibleSituations || 0,
            documentSemanticNegated: input.documentSemanticSummary?.counters.negated || 0,
            documentSemanticModal: input.documentSemanticSummary?.counters.modal || 0,
            documentSemanticConditional: input.documentSemanticSummary?.counters.conditional || 0,
            documentSemanticAttributed: input.documentSemanticSummary?.counters.attributed || 0,
            documentSemanticQuoted: input.documentSemanticSummary?.counters.quoted || 0,
            documentSemanticQuestions: input.documentSemanticSummary?.counters.questions || 0,
            documentSemanticDirectives: input.documentSemanticSummary?.counters.directives || 0,
            documentSemanticNary: input.documentSemanticSummary?.counters.nAry || 0,
            documentSemanticReviewable: input.documentSemanticSummary?.counters.reviewable || 0,
            documentSemanticLedgerOnly: input.documentSemanticSummary?.counters.ledgerOnly || 0,
            documentSemanticPredicateModifiers: input.documentSemanticSummary?.counters.predicateModifiers || 0,
            documentSemanticPredicateNoise: input.documentSemanticSummary?.counters.predicateNoise || 0,
            documentReviewRows: documentReviewSummary.counters.rows,
            documentReviewActionableRows: documentReviewSummary.counters.actionableRows,
            documentReviewStateRecords: documentReviewSummary.counters.stateRecords,
            documentReviewActions: documentReviewSummary.counters.actions,
            documentReviewReceipts: documentReviewSummary.counters.receipts,
            documentReviewReversibleReceipts: documentReviewSummary.counters.reversibleReceipts,
            documentReviewProposedRows: documentReviewSummary.counters.proposedRows,
            documentReviewAcceptedRows: documentReviewSummary.counters.acceptedRows,
            documentReviewRejectedRows: documentReviewSummary.counters.rejectedRows,
            documentReviewMutedRows: documentReviewSummary.counters.mutedRows,
            documentReviewPromotedToAnchorRows: documentReviewSummary.counters.promotedToAnchorRows,
            documentReviewCompiledToGraphRows: documentReviewSummary.counters.compiledToGraphRows,
            documentReviewLedgerOnlyRows: documentReviewSummary.counters.ledgerOnlyRows,
            documentCompilerEntityMentions: documentCompilerSummary.counters.entityMentions,
            documentCompilerRelationCandidates: documentCompilerSummary.counters.relationCandidates,
            documentCompilerHyperedges: documentCompilerSummary.counters.hyperedges,
            documentCompilerNaryHyperedges: documentCompilerSummary.counters.naryHyperedges,
            documentCompilerEvidenceEdges: documentCompilerSummary.counters.evidenceBackedEdges,
            documentCompilerCrossDocBridges: documentCompilerSummary.counters.crossDocBridges,
            documentCompilerStructureEdges: documentCompilerSummary.counters.documentStructureEdges,
            documentCompilerRetrievalOverlays: documentCompilerSummary.counters.retrievalOverlays,
            documentCompilerTopologyDiffs: documentCompilerSummary.counters.topologyDiffs,
            documentCompilerTopologyCommits: documentCompilerSummary.counters.topologyCommits,
            documentCompilerNativeCompileCandidates: documentCompilerSummary.counters.nativeCompileCandidates || 0,
            documentCompilerLedgerOnly: documentCompilerSummary.counters.ledgerOnly,
            documentCompilerOverlayOnly: documentCompilerSummary.counters.overlayOnly,
            documentCompilerReviewable: documentCompilerSummary.counters.reviewable,
            documentCompilerBlocked: documentCompilerSummary.counters.blocked,
            documentCompilerReceipts: documentCompilerSummary.counters.receipts,
            documentCompilerReversibleReceipts: documentCompilerSummary.counters.reversibleReceipts,
            documentCompilerMutationAllowed: documentCompilerSummary.counters.mutationAllowed,
            documentCompilerHighConfidenceFacts: documentCompilerSummary.counters.highConfidenceFacts,
            documentCompilerReviewedFacts: documentCompilerSummary.counters.reviewedFacts,
            documentCompilerAmbiguousFacts: documentCompilerSummary.counters.ambiguousFacts,
            operatorMutationIntents: operatorMutationJournal?.counters.intents || 0,
            operatorMutationActive: operatorMutationJournal?.counters.active || 0,
            operatorMutationApplied: operatorMutationJournal?.counters.applied || 0,
            operatorMutationConflicted: operatorMutationJournal?.counters.conflicted || 0,
            operatorMutationUndone: operatorMutationJournal?.counters.undone || 0,
            operatorMutationReceipts: operatorMutationJournal?.counters.receipts || 0,
            eventAspects: derived.events.filter((event) => Boolean(event.aspect)).length,
            dropReasons: drops,
            resolution: hygiene.resolution,
        },
        resolutionSuggestions: hygiene.suggestions,
    };
    sealGraphEvidenceTargetRegistry(snapshot);
    input.cpuProfiler?.mark('snapshotAssemblyMs');
    const hopfResonanceSpace = buildHopfResonanceSpace(snapshot, { generatedAt: builtAt });
    if (hopfResonanceSpace.assignments.length !== snapshot.embeddingTargets.length) {
        throw new Error(
            `Hopf resonance space contract failed: ${hopfResonanceSpace.assignments.length} assignments for ${snapshot.embeddingTargets.length} embedding targets`,
        );
    }
    snapshot.hopfResonanceSpace = hopfResonanceSpace;
    snapshot.counters.hopfResonanceAssignments = hopfResonanceSpace.assignments.length;
    snapshot.counters.hopfResonanceOccupiedCells = hopfResonanceSpace.counters.occupiedCellCount;
    snapshot.counters.hopfResonanceFibers = hopfResonanceSpace.fibers.length;
    snapshot.counters.hopfResonanceDocCharts = hopfResonanceSpace.docCharts.length;
    snapshot.counters.hopfResonanceBraids = hopfResonanceSpace.braids.length;
    snapshot.counters.hopfResonanceDroppedTargets = hopfResonanceSpace.counters.droppedTargets;
    snapshot.counters.hopfResonanceMutationAllowed = hopfResonanceSpace.counters.mutationAllowedCount;
    attachGraphCompilerReadModels(
        snapshot,
        input.graphCompilerSidecar || buildCompatibilityGraphCompilerSidecar(snapshot),
        input.graphCompilerSidecar ? 'rust' : 'typescriptCompatibility',
    );
    const shadowLinkSuggestions = [
        ...entityLinking.suggestions,
        ...buildBundleDedupeShadowLinks(snapshot.graphModelV2?.bundles || []),
    ];
    const finalLinkPatchLog = buildGraphRebuildFinalLinkPatchLog(shadowLinkSuggestions, builtAt);
    snapshot.entityLinkSuggestions = shadowLinkSuggestions;
    snapshot.shadowLinkSuggestions = shadowLinkSuggestions;
    snapshot.finalLinkPatchLog = finalLinkPatchLog;
    snapshot.counters.shadowLinkSuggestions = shadowLinkSuggestions.length;
    snapshot.counters.finalLinkPatches = finalLinkPatchLog.counters.planned;
    snapshot.counters.finalLinkReceiptFailures = finalLinkPatchLog.counters.failedReceipts;
    const semanticLedgersStarted = performance.now();
    input.cpuProfiler?.checkpoint();
    const semanticContext = new GraphSemanticDerivationContext(snapshot);
    const semanticTaskSummary = buildGraphSemanticTaskSummary(snapshot, builtAt, semanticContext);
    input.cpuProfiler?.mark('snapshotSemanticTasksMs');
    snapshot.semanticTaskSummary = semanticTaskSummary;
    snapshot.counters.semanticTasks = semanticTaskSummary.tasks.length;
    snapshot.counters.semanticTaskReceipts = semanticTaskSummary.receipts.length;
    snapshot.counters.semanticTaskMutationAllowed = semanticTaskSummary.counters.mutationAllowedCount;
    const semanticCandidateSummary = buildGraphSemanticCandidateSummary(snapshot, semanticTaskSummary, builtAt, semanticContext);
    input.cpuProfiler?.mark('snapshotSemanticCandidatesMs');
    snapshot.semanticCandidateSummary = semanticCandidateSummary;
    snapshot.counters.semanticCandidates = semanticCandidateSummary.candidates.length;
    snapshot.counters.semanticCandidateReceipts = semanticCandidateSummary.receipts.length;
    snapshot.counters.semanticCandidateMutationAllowed = semanticCandidateSummary.counters.mutationAllowedCount;
    snapshot.counters.semanticCandidateDeferred = semanticCandidateSummary.counters.deferredCount;
    const manifoldSpecializationSummary = buildGraphManifoldSpecializationSummary(
        snapshot,
        semanticCandidateSummary,
        builtAt,
        semanticContext,
    );
    semanticContext.indexContributions(manifoldSpecializationSummary.contributions);
    input.cpuProfiler?.mark('snapshotManifoldSpecializationMs');
    snapshot.manifoldSpecializationSummary = manifoldSpecializationSummary;
    snapshot.counters.manifoldSpecializations = manifoldSpecializationSummary.profiles.length;
    snapshot.counters.manifoldCandidateContributions = manifoldSpecializationSummary.contributions.length;
    snapshot.counters.manifoldContributionReceipts = manifoldSpecializationSummary.receipts.length;
    snapshot.counters.manifoldCandidateExplained = manifoldSpecializationSummary.counters.explainedCandidateCount;
    snapshot.counters.manifoldSpecializationMutationAllowed = manifoldSpecializationSummary.counters.mutationAllowedCount;
    const semanticRerankSummary = buildGraphSemanticRerankSummary(
        snapshot,
        semanticCandidateSummary,
        manifoldSpecializationSummary,
        builtAt,
        semanticContext,
    );
    semanticContext.indexJudgments(semanticRerankSummary.judgments);
    input.cpuProfiler?.mark('snapshotSemanticRerankMs');
    snapshot.semanticRerankSummary = semanticRerankSummary;
    snapshot.counters.semanticRerankInputs = semanticRerankSummary.inputs.length;
    snapshot.counters.semanticRerankJudgments = semanticRerankSummary.judgments.length;
    snapshot.counters.semanticRerankReceipts = semanticRerankSummary.receipts.length;
    snapshot.counters.semanticRerankPlannedModelCalls = semanticRerankSummary.counters.plannedModelCalls;
    snapshot.counters.semanticRerankMutationAllowed = semanticRerankSummary.counters.mutationAllowedCount;
    const semanticAdjudicationSummary = buildGraphSemanticAdjudicationDAGSummary(snapshot, builtAt, semanticContext);
    snapshot.semanticAdjudicationSummary = semanticAdjudicationSummary;
    input.cpuProfiler?.mark('snapshotSemanticAdjudicationMs');
    snapshot.counters.edges = snapshot.edges.length;
    snapshot.counters.semanticAdjudicationDecisions = semanticAdjudicationSummary.decisions.length;
    snapshot.counters.semanticAdjudicationMutations = semanticAdjudicationSummary.mutations.length;
    snapshot.counters.semanticAdjudicationReceipts = semanticAdjudicationSummary.receipts.length;
    snapshot.counters.semanticAdjudicationTopologyCommits = semanticAdjudicationSummary.counters.topologyCommitCount;
    snapshot.counters.semanticAdjudicationLedgerOnly = semanticAdjudicationSummary.counters.ledgerOnlyCount;
    const semanticEvalLedgerSummary = buildGraphSemanticEvalLedgerSummary(snapshot, builtAt, semanticContext);
    input.cpuProfiler?.mark('snapshotSemanticEvalLedgerMs');
    snapshot.semanticEvalLedgerSummary = semanticEvalLedgerSummary;
    snapshot.counters.semanticEvalLedgerRows = semanticEvalLedgerSummary.entries.length;
    snapshot.counters.semanticEvalAcceptedCandidates = semanticEvalLedgerSummary.counters.acceptedCandidates;
    snapshot.counters.semanticEvalRejectedCandidates = semanticEvalLedgerSummary.counters.rejectedCandidates;
    snapshot.counters.semanticEvalAmbiguousCases = semanticEvalLedgerSummary.counters.ambiguousCases;
    snapshot.counters.semanticEvalModelDisagreements = semanticEvalLedgerSummary.counters.modelDisagreements;
    snapshot.counters.semanticEvalManifoldDisagreements = semanticEvalLedgerSummary.counters.manifoldDisagreements;
    snapshot.counters.semanticEvalGraphChangeRows = semanticEvalLedgerSummary.counters.graphChangeRows;
    input.cpuProfiler?.setSemanticIndexStats(semanticContext.stats());
    if (includeDiagnosticArms) {
        const memoryGraphRagBridgeSummary = buildGraphMemoryGraphRagBridgeSummary(snapshot, builtAt);
        snapshot.memoryGraphRagBridgeSummary = memoryGraphRagBridgeSummary;
        snapshot.counters.memoryGraphRagRecords = memoryGraphRagBridgeSummary.counters.recordCount;
        snapshot.counters.memoryGraphRagSchemaRecords = memoryGraphRagBridgeSummary.counters.schemaRecords;
        snapshot.counters.memoryGraphRagFactRecords = memoryGraphRagBridgeSummary.counters.factRecords;
        snapshot.counters.memoryGraphRagPassageRecords = memoryGraphRagBridgeSummary.counters.passageRecords;
        snapshot.counters.memoryGraphRagEvalRows = memoryGraphRagBridgeSummary.counters.evalRowCount;
        snapshot.counters.memoryGraphRagPassedEvalRows = memoryGraphRagBridgeSummary.counters.passedEvalRows;
        snapshot.counters.memoryGraphRagReceipts = memoryGraphRagBridgeSummary.counters.receiptCount;
        snapshot.counters.memoryGraphRagMutationAllowed = memoryGraphRagBridgeSummary.counters.mutationAllowedCount;
        const discourseSpineSummary = buildGraphDiscourseSpineSummary(snapshot, builtAt);
        snapshot.discourseSpineSummary = discourseSpineSummary;
        snapshot.counters.discourseSpineTargets = discourseSpineSummary.counters.targetCount;
        snapshot.counters.discourseSpineLabels = discourseSpineSummary.counters.labelCount;
        snapshot.counters.discourseSpineClusters = discourseSpineSummary.counters.clusterCount;
        snapshot.counters.discourseSpineBridges = discourseSpineSummary.counters.bridgeCount;
        snapshot.counters.discourseSpineResonance = discourseSpineSummary.counters.resonanceCandidates;
        snapshot.counters.discourseSpineResolution = discourseSpineSummary.counters.resolutionCandidates;
        snapshot.counters.discourseSpineReceipts = discourseSpineSummary.counters.receiptCount;
        snapshot.counters.discourseSpineMutationAllowed = discourseSpineSummary.counters.mutationAllowedCount;
        const discourseBridgeCandidateSummary = buildGraphDiscourseBridgeCandidateSummary(snapshot, discourseSpineSummary, builtAt);
        snapshot.discourseBridgeCandidateSummary = discourseBridgeCandidateSummary;
        snapshot.counters.discourseBridgeCandidates = discourseBridgeCandidateSummary.counters.candidateCount;
        snapshot.counters.discourseBridgeInputs = discourseBridgeCandidateSummary.counters.inputCount;
        snapshot.counters.discourseBridgeJudgments = discourseBridgeCandidateSummary.counters.judgmentCount;
        snapshot.counters.discourseBridgeEvalRows = discourseBridgeCandidateSummary.counters.evalRowCount;
        snapshot.counters.discourseBridgeReceipts = discourseBridgeCandidateSummary.counters.receiptCount;
        snapshot.counters.discourseBridgePlannedModelCalls = discourseBridgeCandidateSummary.counters.plannedModelCalls;
        snapshot.counters.discourseBridgeMutationAllowed = discourseBridgeCandidateSummary.counters.mutationAllowedCount;
        const discourseBridgeAdjudicationSummary = buildGraphDiscourseBridgeAdjudicationSummary(snapshot, discourseBridgeCandidateSummary, builtAt);
        snapshot.discourseBridgeAdjudicationSummary = discourseBridgeAdjudicationSummary;
        snapshot.counters.discourseBridgeAdjudicationDecisions = discourseBridgeAdjudicationSummary.counters.decisionCount;
        snapshot.counters.discourseBridgeAdjudicationAccepted = discourseBridgeAdjudicationSummary.counters.acceptedCount;
        snapshot.counters.discourseBridgeAdjudicationSupported = discourseBridgeAdjudicationSummary.counters.supportedCount;
        snapshot.counters.discourseBridgeAdjudicationDeferred = discourseBridgeAdjudicationSummary.counters.deferredCount;
        snapshot.counters.discourseBridgeAdjudicationRejected = discourseBridgeAdjudicationSummary.counters.rejectedCount;
        snapshot.counters.discourseBridgeAdjudicationReceipts = discourseBridgeAdjudicationSummary.counters.receiptCount;
        snapshot.counters.discourseBridgeAdjudicationLedgerOnly = discourseBridgeAdjudicationSummary.counters.ledgerOnlyCount;
        snapshot.counters.discourseBridgeAdjudicationTopologyCommits = discourseBridgeAdjudicationSummary.counters.topologyCommitCount;
        snapshot.counters.discourseBridgeAdjudicationMutationAllowed = discourseBridgeAdjudicationSummary.counters.mutationAllowedCount;
        const discourseEvalLedgerSummary = buildGraphDiscourseEvalLedgerSummary(snapshot, builtAt);
        snapshot.discourseEvalLedgerSummary = discourseEvalLedgerSummary;
        snapshot.counters.discourseEvalLedgerRows = discourseEvalLedgerSummary.counters.rowCount;
        snapshot.counters.discourseEvalAcceptedCandidates = discourseEvalLedgerSummary.counters.acceptedCandidates;
        snapshot.counters.discourseEvalRejectedCandidates = discourseEvalLedgerSummary.counters.rejectedCandidates;
        snapshot.counters.discourseEvalAmbiguousCases = discourseEvalLedgerSummary.counters.ambiguousCases;
        snapshot.counters.discourseEvalModelDisagreements = discourseEvalLedgerSummary.counters.modelDisagreements;
        snapshot.counters.discourseEvalManifoldDisagreements = discourseEvalLedgerSummary.counters.manifoldDisagreements;
        snapshot.counters.discourseEvalGraphChangeRows = discourseEvalLedgerSummary.counters.graphChangeRows;
        const discoursePromotionSurfaceSummary = buildGraphDiscoursePromotionSurfaceSummary(snapshot, builtAt);
        snapshot.discoursePromotionSurfaceSummary = discoursePromotionSurfaceSummary;
        snapshot.counters.discoursePromotionChunkWormholes = discoursePromotionSurfaceSummary.counters.chunkWormholeCount;
        snapshot.counters.discoursePromotionDocumentClusters = discoursePromotionSurfaceSummary.counters.documentClusterCount;
        snapshot.counters.discoursePromotionResolverCandidates = discoursePromotionSurfaceSummary.counters.resolverCandidateCount;
        snapshot.counters.discoursePromotionCompilerHints = discoursePromotionSurfaceSummary.counters.compilerHintCount;
        snapshot.counters.discoursePromotionReceipts = discoursePromotionSurfaceSummary.counters.receiptCount;
        snapshot.counters.discoursePromotionGraphPatches = discoursePromotionSurfaceSummary.counters.graphPatchCount;
        snapshot.counters.discoursePromotionMutationAllowed = discoursePromotionSurfaceSummary.counters.mutationAllowedCount;
        const discourseCompilerOverlaySummary = buildGraphDiscourseCompilerOverlaySummary(snapshot, builtAt);
        snapshot.discourseCompilerOverlaySummary = discourseCompilerOverlaySummary;
        snapshot.counters.discourseCompilerOverlayEdges = discourseCompilerOverlaySummary.counters.overlayEdgeCount;
        snapshot.counters.discourseCompilerOverlayChunkWormholes = discourseCompilerOverlaySummary.counters.chunkWormholeEdges;
        snapshot.counters.discourseCompilerOverlayDocumentClusters = discourseCompilerOverlaySummary.counters.documentClusterEdges;
        snapshot.counters.discourseCompilerOverlayResolvers = discourseCompilerOverlaySummary.counters.resolverEdges;
        snapshot.counters.discourseCompilerOverlayReceipts = discourseCompilerOverlaySummary.counters.receiptCount;
        snapshot.counters.discourseCompilerOverlayGraphPatches = discourseCompilerOverlaySummary.counters.graphPatchCount;
        snapshot.counters.discourseCompilerOverlayMutationAllowed = discourseCompilerOverlaySummary.counters.mutationAllowedCount;
    }
    const calendarRegistrySummary = buildGraphCalendarRegistryBridgeSummary({
        calendarRegistry: input.calendarRegistrySnapshot,
        sourceSnapshotId: snapshot.id,
        scopeKind: input.scopeKind,
        scopeId: input.scopeId,
        noteIds,
        generatedAt: builtAt,
    });
    if (calendarRegistrySummary) {
        snapshot.calendarRegistrySummary = calendarRegistrySummary;
        snapshot.counters.calendarRegistryAnchors = calendarRegistrySummary.counters.anchorCount;
        snapshot.counters.calendarRegistryReceipts = calendarRegistrySummary.counters.receiptCount;
        snapshot.counters.calendarRegistryAcceptedTemporalReceipts = calendarRegistrySummary.counters.acceptedTemporalReceipts;
        snapshot.counters.calendarRegistryRealEpochReceipts = calendarRegistrySummary.counters.realEpochReceipts;
        snapshot.counters.calendarRegistryCustomOrdinalReceipts = calendarRegistrySummary.counters.customOrdinalReceipts;
        snapshot.counters.calendarRegistryMutationAllowed = calendarRegistrySummary.counters.mutationAllowedCount;
    }
    assertGraphSemanticDiscoveriesRemainCandidates(snapshot);
    input.cpuProfiler?.add('snapshotSemanticLedgersMs', semanticLedgersStarted);
    return snapshot;
}

function planLaneCandidates(
    plan: { lanes: Array<{ lane: GraphRebuildSignalTargetLane; candidates: number }> },
    lane: GraphRebuildSignalTargetLane,
): number {
    return plan.lanes.find((row) => row.lane === lane)?.candidates || 0;
}

function countChunkSemanticBridges(
    bridges: GraphRebuildChunkSemanticBridge[],
    bridgeType: GraphRebuildChunkSemanticBridgeType,
): number {
    return bridges.filter((bridge) => bridge.bridgeType === bridgeType).length;
}

function buildNodes(anchors: GraphRebuildEntityAnchor[], entitiesById: Map<string, RegisteredEntity>): GraphRebuildNode[] {
    const byEntity = new Map<string, GraphRebuildNode>();
    for (const anchor of anchors) {
        const entity = entitiesById.get(anchor.entityId);
        if (!entity) continue;
        const node = byEntity.get(entity.id) ?? {
            id: entity.id,
            entityId: entity.id,
            label: entity.label,
            kind: entity.kind,
            aliases: [...(entity.aliases || [])],
            anchorIds: [],
            noteIds: [],
            totalMentions: 0,
        };
        node.anchorIds.push(anchor.id);
        if (!node.noteIds.includes(anchor.noteId)) node.noteIds.push(anchor.noteId);
        node.totalMentions += 1;
        byEntity.set(entity.id, node);
    }
    return [...byEntity.values()].sort((left, right) =>
        right.totalMentions - left.totalMentions
        || left.kind.localeCompare(right.kind)
        || left.label.localeCompare(right.label),
    );
}

function buildEdges(anchors: GraphRebuildEntityAnchor[], drops: GraphRebuildDropReasons): GraphRebuildEdge[] {
    const buckets = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of anchors) {
        const key = anchor.chunkId || `note:${anchor.noteId}`;
        buckets.set(key, [...(buckets.get(key) || []), anchor]);
    }
    const byPair = new Map<string, GraphRebuildEdge>();
    for (const [scopeKey, bucket] of buckets) {
        const pairs = coOccurrencePairs(bucket);
        if (!pairs.length) {
            drops.singletonBucket += 1;
            continue;
        }
        for (const pair of pairs) {
            upsertEdge(byPair, pair.leftId, pair.rightId, pair.evidence, scopeKey);
        }
    }
    return [...byPair.values()].sort((left, right) => right.weight - left.weight || left.id.localeCompare(right.id));
}

function coOccurrencePairs(bucket: GraphRebuildEntityAnchor[]): Array<{
    leftId: string;
    rightId: string;
    evidence: GraphRebuildEntityAnchor[];
}> {
    const anchors = [...bucket].sort((left, right) => left.sourceStart - right.sourceStart || left.sourceEnd - right.sourceEnd);
    const best = new Map<string, { leftId: string; rightId: string; evidence: GraphRebuildEntityAnchor[]; gap: number }>();
    for (let i = 0; i < anchors.length; i += 1) {
        const left = anchors[i];
        let links = 0;
        for (let j = i + 1; j < anchors.length; j += 1) {
            const right = anchors[j];
            const gap = Math.max(0, right.sourceStart - left.sourceEnd);
            if (gap > CO_OCCURRENCE_MAX_GAP_CHARS) break;
            if (left.entityId === right.entityId) continue;
            const [sourceId, targetId] = [left.entityId, right.entityId].sort();
            const key = `${sourceId}\u0000${targetId}`;
            const current = best.get(key);
            if (!current || gap < current.gap) {
                best.set(key, { leftId: sourceId, rightId: targetId, evidence: [left, right], gap });
            }
            links += 1;
            if (links >= CO_OCCURRENCE_LINKS_PER_ANCHOR) break;
        }
    }
    return [...best.values()].sort((left, right) => left.gap - right.gap || left.leftId.localeCompare(right.leftId) || left.rightId.localeCompare(right.rightId));
}

function upsertEdge(
    byPair: Map<string, GraphRebuildEdge>,
    leftId: string,
    rightId: string,
    evidenceAnchors: GraphRebuildEntityAnchor[],
    scopeKey: string,
): void {
    const [sourceId, targetId] = [leftId, rightId].sort();
    const id = `${sourceId}:anchored-cooccurrence:${targetId}`;
    const evidence = evidenceAnchors.map((anchor) => anchor.id);
    const edge = byPair.get(id) ?? {
        id,
        sourceId,
        targetId,
        type: 'anchored-cooccurrence',
        weight: 0,
        confidence: 0,
        evidenceAnchorIds: [],
        scopeKeys: [],
        noteIds: [],
    };
    edge.weight += 1;
    edge.confidence = Math.min(1, edge.confidence + 0.2 + evidence.length * 0.08);
    edge.evidenceAnchorIds = unique([...edge.evidenceAnchorIds, ...evidence]);
    edge.scopeKeys = unique([...edge.scopeKeys, scopeKey]);
    edge.noteIds = unique([...edge.noteIds, ...evidenceAnchors.map((anchor) => anchor.noteId)]);
    byPair.set(id, edge);
}

function edgeToRelationship(edge: GraphRebuildEdge): GraphRebuildRelationship {
    const adjudication = adjudicateEdge(edge);
    return {
        id: `relationship:${edge.id}`,
        sourceEntityId: edge.sourceId,
        targetEntityId: edge.targetId,
        relationType: edge.type === 'anchored-cooccurrence' ? 'co_occurs_with' : edge.type,
        evidenceAnchorIds: edge.evidenceAnchorIds,
        confidence: adjudication.score,
        status: adjudication.status,
        adjudicationSource: 'graph-rebuild-cooccurrence-policy',
        adjudicationScore: adjudication.score,
        rationale: adjudication.rationale,
        decisionEvidence: adjudication.evidence,
    };
}

function applyRelationshipHints(
    relationships: GraphRebuildRelationship[],
    hints: GraphRebuildRelationshipHint[],
): GraphRebuildRelationship[] {
    if (!hints.length || !relationships.length) return relationships;
    const byPair = new Map<string, GraphRebuildRelationshipHint>();
    for (const hint of hints) {
        for (const key of pairKeyVariants(hint.sourceId, hint.targetId)) {
            const current = byPair.get(key);
            if (!current || hint.confidence > current.confidence) byPair.set(key, hint);
        }
    }
    return relationships.map((relationship) => {
        const hint = byPair.get(pairKey(relationship.sourceEntityId, relationship.targetEntityId));
        if (!hint) return relationship;
        const relationType = hint.relationType || relationship.relationType;
        const confidence = clamp(hint.confidence, 0, 1);
        return {
            ...relationship,
            relationType,
            confidence,
            status: hint.status,
            adjudicationSource: hint.source,
            adjudicationScore: confidence,
            rationale: `${hint.status}: NLI adjudication matched this candidate pair`,
            decisionEvidence: unique([
                ...relationship.decisionEvidence,
                ...(hint.evidence || []),
                `nli_confidence:${confidence.toFixed(3)}`,
            ]),
        };
    });
}

function adjudicateEdge(edge: GraphRebuildEdge): { status: 'accepted' | 'review' | 'rejected'; score: number; rationale: string; evidence: string[] } {
    const evidenceCount = edge.evidenceAnchorIds.length;
    const scopeCount = edge.scopeKeys.length;
    const score = Math.min(1, Math.min(edge.weight / 5, 0.65) + Math.min(evidenceCount / 24, 0.25) + Math.min(scopeCount / 12, 0.1));
    const status = evidenceCount >= 2 && scopeCount >= 1 ? 'review' : 'rejected';
    const rationale = status === 'review'
        ? `review: anchor evidence across ${scopeCount} bucket(s); needs typed relation/NLI confirmation before fact promotion`
        : 'rejected: insufficient anchor evidence for a relationship signal';
    return {
        status,
        score,
        rationale,
        evidence: [`weight:${edge.weight}`, `scope_count:${scopeCount}`, `anchor_evidence_count:${evidenceCount}`],
    };
}

function pairKeyVariants(left: string, right: string): string[] {
    const leftIds = idVariants(left);
    const rightIds = idVariants(right);
    const keys: string[] = [];
    for (const source of leftIds) {
        for (const target of rightIds) keys.push(pairKey(source, target));
    }
    return unique(keys);
}

function pairKey(left: string, right: string): string {
    return [left, right].sort().join('\u0000');
}

function idVariants(value: string): string[] {
    const raw = String(value || '').trim();
    if (!raw) return [];
    const variants = [raw];
    if (raw.startsWith('entity:')) variants.push(raw.slice('entity:'.length));
    const parts = raw.split(':').filter(Boolean);
    if (parts.length > 1) variants.push(parts[parts.length - 1]);
    return unique(variants);
}

function normalizeChunks(chunks: GraphRebuildChunk[]): GraphRebuildChunk[] {
    const seen = new Set<string>();
    return [...chunks]
        .filter((chunk) => chunk.id && chunk.noteId && validSpan(chunk.start, chunk.end))
        .sort((left, right) => left.noteId.localeCompare(right.noteId) || left.start - right.start || left.ordinal - right.ordinal)
        .filter((chunk) => {
            if (seen.has(chunk.id)) return false;
            seen.add(chunk.id);
            return true;
        });
}

function groupChunksByNote(chunks: GraphRebuildChunk[]): Map<string, GraphRebuildChunk[]> {
    const byNote = new Map<string, GraphRebuildChunk[]>();
    for (const chunk of chunks) {
        byNote.set(chunk.noteId, [...(byNote.get(chunk.noteId) || []), chunk]);
    }
    return byNote;
}

function validSpan(from: number, to: number): boolean {
    return Number.isFinite(from) && Number.isFinite(to) && from >= 0 && to > from;
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}

function emptyEntityLinkCounters(mentions: GraphRebuildMention[]): GraphRebuildSnapshot['counters']['entityLinking'] {
    return {
        candidateMentions: mentions.filter((mention) => mention.status !== 'accepted').length,
        candidateLinks: 0,
        sameEntity: 0,
        aliasOf: 0,
        newEntity: 0,
        ambiguous: 0,
        rejected: 0,
        shadowLinks: 0,
        autoConfirmable: 0,
    };
}
