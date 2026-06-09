import { Injectable, inject } from '@angular/core';

import type { DecorationSpan, EntityKind } from '../lib/Scanner/types';
import {
    type PhoenixDiscoveryCandidate,
    groupDiscoveryMentions,
} from '../lib/phoenix/phoenix-discovery';
import { getLearnedAliasesByEntityId } from '../lib/entity-learning/entity-feedback';
import { createUtf8ByteRangeConverter } from '../lib/text-offsets';
import { matchLiteralPatterns, type PhoenixLiteralPattern } from '../lib/search/phoenix-literal-matcher';
import {
    type PhoenixLineSearchHit,
    type PhoenixLineSearchScope,
} from '../lib/search/phoenix-line-search';
import { PhoenixBackendService } from './phoenix-backend.service';
import { PhoenixStoreService } from './phoenix-store.service';
import {
    HOPF_MANIFOLD_CAPABILITIES,
    HYBRID_MANIFOLD_CAPABILITIES,
    LORENTZ_MANIFOLD_CAPABILITIES,
    PRODUCT_MANIFOLD_CAPABILITIES,
    SIEGEL_FINSLER_CAPABILITIES,
    type AtlasManifoldMode,
    type LorentzForestBuildRequest,
    type LorentzForestBuildResponse,
    type LorentzForestCacheRequest,
    type LorentzForestCacheStatus,
    type LorentzForestQueryRequest,
    type LorentzForestQueryResponse,
    type ManifoldAtlasSnapshot,
    type ManifoldProjectionSource,
    type ManifoldTopologyPayload,
} from './manifold-atlas.types';
import type {
    PhoenixGraphScenePacket,
    PhoenixGraphScenePacketRequest,
} from './phoenix-graph-scene-packet.model';
import type { PhoenixGraphDeltaBinaryResult } from './phoenix-wasm.service';

export interface ProvenanceContext {
    vaultId?: string;
    worldId: string;
    parentPath?: string;
    folderType?: string;
}

export interface SearchScope {
    mode?: string;
    noteId?: string;
    noteIds?: string[];
    worldId?: string;
    narrativeId?: string;
    folderId?: string;
    folderPath?: string;
}

export type AtlasRichScanPolicy = 'dirty-only' | 'force';

export interface AtlasRichScanDocumentInput {
    documentId: string;
    noteId?: string;
    title: string;
    text: string;
    scope?: SearchScope;
}

export interface AtlasRichScanStageSummary {
    stage: 'surface' | 'evidenceGraph' | 'embeddings' | 'overgraph' | string;
    status: string;
    durationMs: number;
    counts: Record<string, number>;
}

export interface AtlasRichScanKindVoteSummary {
    kind: string;
    source: string;
    confidence: number;
    reason: string;
}

export interface AtlasRichScanCandidateSummary {
    id: string;
    label: string;
    kind: string;
    confidence: number;
    sourceDocumentId?: string;
    sourceNoteId?: string;
    evidence?: string;
    aliases?: string[];
    range?: { start: number; end: number } | null;
    sourceStage?: string;
    kindVotes?: AtlasRichScanKindVoteSummary[];
    decisionStatus?: string;
    reviewReason?: string | null;
}

export type AtlasAliasRelation =
    | 'exactKnownAlias'
    | 'fullDesignation'
    | 'nickname'
    | 'codename'
    | 'spellingVariant'
    | 'titleOrRole'
    | 'sameSurface'
    | 'relatedButDistinct'
    | 'typeConflict'
    | 'ambiguous'
    | 'newEntity';

export type AtlasAliasProposalDecision = 'accept' | 'propose' | 'defer' | 'reject';

export type AtlasAliasProposalTarget =
    | {
          knownEntity: {
              entityId: string;
              canonicalName: string;
              kind?: string | null;
          };
      }
    | {
          runLocalSurface: {
              key: string;
              display: string;
              kind?: string | null;
          };
      }
    | 'newEntity'
    | 'deferred';

export interface AtlasAliasEvidence {
    source: string;
    confidence: number;
    note: string;
}

export interface AtlasAliasProposalSummary {
    caseId: string;
    documentId: string;
    mentionId: string;
    surface: string;
    normalized: string;
    range: { start: number; end: number };
    relation: AtlasAliasRelation;
    target: AtlasAliasProposalTarget;
    confidence: number;
    decision: AtlasAliasProposalDecision;
    evidence?: AtlasAliasEvidence[];
    rationale: string;
}

export type AtlasIdentityReceiptAction =
    | 'knownEntity'
    | 'aliasOfKnown'
    | 'fullDesignation'
    | 'coreference'
    | 'mergeRunLocal'
    | 'split'
    | 'defer'
    | 'newEntity';

export type AtlasIdentityTargetSummary =
    | {
          knownEntity: {
              entityId: string;
              canonicalName: string;
              kind?: string | null;
          };
      }
    | {
          runLocalEntity: {
              key: string;
              display: string;
              kind?: string | null;
          };
      }
    | {
          newEntity: {
              key: string;
              display: string;
              kind?: string | null;
          };
      }
    | 'deferred';

export interface AtlasIdentityReceiptSummary {
    receiptId: string;
    documentId: string;
    action: AtlasIdentityReceiptAction;
    mentionIds?: string[];
    surface: string;
    target: AtlasIdentityTargetSummary;
    confidence: number;
    reversible: boolean;
    evidence?: AtlasAliasEvidence[];
    rationale: string;
}

export interface AtlasIdentityResolutionSummary {
    nodeCount: number;
    edgeCount: number;
    receiptCount: number;
    knownDecisions: number;
    aliasDecisions: number;
    coreferenceDecisions?: number;
    mergeDecisions: number;
    splitDecisions: number;
    deferredDecisions: number;
    newEntityDecisions: number;
    receipts?: AtlasIdentityReceiptSummary[];
}

export type AtlasEvidenceArtifactKind =
    | 'mention'
    | 'kindVote'
    | 'aliasProposal'
    | 'identityReceipt'
    | 'candidateSuggestion'
    | 'graphEdge'
    | 'frameTrigger'
    | 'frameArgument'
    | 'frameFact'
    | 'userCorrection'
    | 'rejection'
    | 'datasetExample';

export type AtlasEvidenceDecisionStatus =
    | 'observed'
    | 'accepted'
    | 'proposed'
    | 'deferred'
    | 'rejected'
    | 'corrected'
    | 'reverted';

export type AtlasDatasetExampleKind =
    | 'nerSpan'
    | 'kindVote'
    | 'aliasDecision'
    | 'identityResolution'
    | 'candidateSuggestion'
    | 'graphEdge'
    | 'frameExtraction';

export interface AtlasEvidenceReceiptSummary {
    receiptId: string;
    scanId: string;
    documentId?: string | null;
    noteId?: string | null;
    stage: string;
    artifactKind: AtlasEvidenceArtifactKind;
    decisionStatus: AtlasEvidenceDecisionStatus;
    subject: string;
    predicate?: string | null;
    object?: string | null;
    surface?: string | null;
    normalized?: string | null;
    range?: { start: number; end: number } | null;
    confidence: number;
    source: string;
    sourceVersion: string;
    mentionIds?: string[];
    evidenceRefs?: string[];
    supersedes?: string[];
    reverts?: string[];
    payload?: unknown;
    createdAt: number;
}

export interface AtlasEvidenceLedgerSummary {
    receiptCount: number;
    countsByStage?: Record<string, number>;
    countsByKind?: Record<string, number>;
    countsByDecision?: Record<string, number>;
}

export interface AtlasDatasetExampleSummary {
    exampleId: string;
    snapshotId: string;
    datasetKind: string;
    exampleKind: AtlasDatasetExampleKind;
    documentId?: string | null;
    label: string;
    inputText: string;
    target?: unknown;
    sourceReceiptIds?: string[];
    split: string;
    payload?: unknown;
    createdAt: number;
}

export interface AtlasDatasetSnapshotSummary {
    snapshotId: string;
    scanId: string;
    datasetKind: string;
    exampleCount: number;
    sourceReceiptCount: number;
    countsByKind?: Record<string, number>;
    examples?: AtlasDatasetExampleSummary[];
    createdAt: number;
}

export interface AtlasDatasetFactorySummary {
    snapshotCount: number;
    exampleCount: number;
    snapshots?: AtlasDatasetSnapshotSummary[];
}

export interface AtlasRichScanResult {
    scanId: string;
    processedDocuments: number;
    skippedDocuments: number;
    manifestDirtyPlan?: Record<string, unknown>;
    stageSummaries: AtlasRichScanStageSummary[];
    lensChunkCounts: Record<string, number>;
    graphDeltaCounts: Record<string, number>;
    embeddingCounts: { leaf: number; entity: number; lens: number };
    relationCandidateCount: number;
    candidateSuggestions: AtlasRichScanCandidateSummary[];
    aliasProposals?: AtlasAliasProposalSummary[];
    identityResolution?: AtlasIdentityResolutionSummary;
    evidenceLedger?: AtlasEvidenceLedgerSummary;
    datasetFactory?: AtlasDatasetFactorySummary;
    appliedOptions?: AtlasRichScanAppliedOptions;
    preservationCounts?: Record<string, number>;
    diagnostics?: Array<{ code: string; message: string }>;
}

export interface AtlasRichScanAppliedOptions {
    policy?: AtlasRichScanPolicy;
    embeddingModelId?: string | null;
    embeddingDimension?: number | null;
    surfaceConfigHash?: string | null;
    graphConfigHash?: string | null;
    returnCandidateSuggestions?: boolean;
    includeSemanticAtlas?: boolean;
}

export interface AtlasRichScanRequest {
    scanId?: string;
    scope?: SearchScope & { mode?: string };
    documents?: AtlasRichScanDocumentInput[];
    changedDocumentIds?: string[];
    policy?: AtlasRichScanPolicy;
    embeddingModelId?: string;
    embeddingDimension?: number;
    surfaceConfigHash?: string;
    graphConfigHash?: string;
    returnCandidateSuggestions?: boolean;
    includeSemanticAtlas?: boolean;
}

export interface SemanticAtlasEmbeddingNode {
    id: string;
    label: string;
    sourceType: 'leaf' | 'entity' | 'lens' | string;
    vector: number[];
    documentId?: string;
    narrativeId?: string;
    folderId?: string;
    preview?: string;
    kind?: string;
    baseVector?: [number, number, number];
    cellId?: string;
    secondaryCellIds?: string[];
    cellDistance?: number;
    boundaryScore?: number;
    phase?: number;
    fiberKind?: string;
    geometryVersion?: string;
}

export interface SemanticAtlasEmbeddingEdge {
    id: string;
    sourceId: string;
    targetId: string;
    type: string;
    confidence: number;
}

export interface SemanticAtlasEmbeddingAtlas extends ManifoldTopologyPayload {
    nodes: SemanticAtlasEmbeddingNode[];
    edges: SemanticAtlasEmbeddingEdge[];
    sourceLabel: string;
    projectionSource?: ManifoldProjectionSource | string;
}

export interface KnowledgeGraphNode {
    id: string;
    kind: string;
    label: string;
    props?: Record<string, unknown>;
}

export interface KnowledgeGraphEdge {
    source: string;
    target: string;
    relation: string;
    weight: number;
    props?: Record<string, unknown>;
}

export interface KnowledgeGraphData {
    nodes: Record<string, KnowledgeGraphNode>;
    edges: KnowledgeGraphEdge[];
}

type NoteIngestInput = {
    id: string;
    title: string;
    text: string;
    narrativeId?: string;
    folderPath?: string;
    version?: number;
};

type DictionaryEntry = {
    id: string;
    label: string;
    kind: string;
    aliases: string[];
};

type PhoenixSearchResult = {
    DocID: string;
    Score: number;
    ChunkID: string;
    LineNumber?: number;
    Snippet?: string;
    LineHits?: PhoenixLineSearchHit[];
};

const DOCUMENT_ID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

@Injectable({ providedIn: 'root' })
export class PhoenixUiApiService {
    private readonly phoenix = inject(PhoenixBackendService);
    private readonly store = inject(PhoenixStoreService);

    private ready = false;
    private readyPromise: Promise<void> | null = null;
    private readonly readyCallbacks = new Set<() => void>();

    private mainSessionId: string | null = null;
    private dictionary: DictionaryEntry[] = [];
    private knowledgeGraph: KnowledgeGraphData = { nodes: {}, edges: [] };

    get isReady(): boolean {
        return this.ready;
    }

    get runtimeTarget(): string {
        return this.phoenix.target;
    }

    invalidateKnowledgeGraphCache(): void {
        this.knowledgeGraph = { nodes: {}, edges: [] };
    }

    async rebuildRuntimeIndexes(reason = 'ui-rebuild'): Promise<any> {
        await this.loadRuntime();
        const result = await this.phoenix.rebuild({ reason });
        this.invalidateKnowledgeGraphCache();
        await this.hydrateWithEntitiesInternal();
        this.store.markDerivedDirty();
        await this.store.triggerSnapshot();
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('phoenix-projection-invalidated'));
        }
        return result;
    }

    onReady(callback: () => void): void {
        if (this.ready) {
            callback();
            return;
        }
        this.readyCallbacks.add(callback);
    }

    async loadRuntime(): Promise<void> {
        if (this.readyPromise) {
            return this.readyPromise;
        }

        this.readyPromise = this.initialize().catch((error) => {
            this.readyPromise = null;
            throw error;
        });
        return this.readyPromise;
    }

    async loadWasm(): Promise<void> {
        if (this.phoenix.target === 'native') {
            throw new Error('PhoenixUiApiService.loadWasm() is disabled in native desktop. Use loadRuntime().');
        }
        await this.loadRuntime();
    }

    async hydrateWithEntities(): Promise<void> {
        await this.loadRuntime();
        await this.hydrateWithEntitiesInternal();
    }

    private async hydrateWithEntitiesInternal(): Promise<void> {
        const entities = (await this.store.listEntities()).map((entity) => ({
            id: entity.id,
            label: entity.label,
            kind: entity.kind,
            aliases: entity.aliases || [],
        }));
        await this.rebuildDictionary(entities);
    }

    async rebuildDictionary(
        entities: Array<{ id: string; label: string; kind: string; aliases?: string[] }>,
    ): Promise<void> {
        const learnedAliases = await getLearnedAliasesByEntityId().catch((error) => {
            console.warn('[PhoenixUiApi] Learned aliases unavailable:', error);
            return new Map<string, string[]>();
        });

        this.dictionary = entities
            .map((entity) => {
                const labelKey = entity.label.trim().toLocaleLowerCase();
                const seen = new Set<string>();
                const aliases: string[] = [];
                for (const alias of [...(entity.aliases || []), ...(learnedAliases.get(entity.id) || [])]) {
                    const cleaned = String(alias || '').trim().replace(/\s+/g, ' ');
                    const aliasKey = cleaned.toLocaleLowerCase();
                    if (!cleaned || aliasKey === labelKey || seen.has(aliasKey)) {
                        continue;
                    }
                    seen.add(aliasKey);
                    aliases.push(cleaned);
                }
                return {
                    id: entity.id,
                    label: entity.label,
                    kind: entity.kind,
                    aliases,
                };
            })
            .sort((left, right) => {
                const leftLen = Math.max(left.label.length, ...left.aliases.map((alias) => alias.length), 0);
                const rightLen = Math.max(right.label.length, ...right.aliases.map((alias) => alias.length), 0);
                return rightLen - leftLen || left.label.localeCompare(right.label);
            });
    }

    async hydrateNotes(
        notes: Array<{
            id: string;
            text: string;
            title?: string;
            version?: number;
            narrativeId?: string;
            folderPath?: string;
        }>,
    ): Promise<{ success: boolean; error?: string }> {
        await this.loadRuntime();
        const sessionId = await this.ensureMainSession();
        const documents = notes.map((note) => this.noteInputToDocument({
            id: note.id,
            title: note.title || note.id,
            text: note.text || '',
            narrativeId: note.narrativeId || undefined,
            folderPath: note.folderPath || undefined,
            version: note.version,
        }));

        if (!documents.length) {
            return { success: true };
        }

        await this.ingestDocumentsIntoSession(sessionId, documents);
        return { success: true };
    }

    async upsertNote(
        id: string,
        text: string,
        version?: number,
        meta?: { title?: string; narrativeId?: string; folderPath?: string },
    ): Promise<{ success: boolean; error?: string }> {
        await this.loadRuntime();
        const note = await this.resolveNoteIngestInput(id, text, version, meta);
        await this.ingestNoteInputs([note], await this.ensureMainSession());
        return { success: true };
    }

    async indexNote(id: string, text: string, scope?: SearchScope): Promise<void> {
        await this.loadRuntime();
        const note = await this.resolveNoteIngestInput(id, text, undefined, {
            narrativeId: scope?.narrativeId,
            folderPath: scope?.folderPath,
        });
        await this.ingestNoteInputs([note], await this.ensureMainSession());
    }

    async search(query: string, limit = 20): Promise<any[]> {
        return this.searchScoped(query, limit);
    }

    async semanticSearch(query: string, limit = 20, scope?: SearchScope): Promise<any[]> {
        await this.loadRuntime();
        if (!query.trim()) {
            return [];
        }

        try {
            const sessionId = await this.ensureMainSession();
            const result = await this.phoenix.query({
                sessionId,
                query,
                scope: this.toPhoenixScope(scope),
                targets: ['chunks', 'semantic'],
                limit,
                temporal: null,
            });

            return (result.chunkHits || []).map((hit: { chunkId: string; score: number }) => ({
                DocID: chunkIdToDocumentId(hit.chunkId),
                Score: hit.score,
                ChunkID: hit.chunkId,
            }));
        } catch (error) {
            console.warn('[PhoenixUiApi] Semantic search failed.', error);
            return [];
        }
    }

    async searchScoped(query: string, limit = 20, scope?: SearchScope): Promise<any[]> {
        await this.loadRuntime();
        if (!query.trim()) {
            return [];
        }

        const byNote = new Map<string, PhoenixSearchResult>();
        const lineHits = await this.store.lineSearch(query, {
            limit: Math.max(limit * 4, limit),
            before: 1,
            after: 1,
            scope: this.toLineSearchScope(scope),
        });
        for (const hit of lineHits) {
            mergeSearchResult(byNote, {
                DocID: hit.noteId,
                Score: hit.score,
                ChunkID: `${hit.noteId}:line:${hit.lineNumber}`,
                LineNumber: hit.lineNumber,
                Snippet: hit.lineText,
                LineHits: [hit],
            });
        }

        try {
            const sessionId = await this.ensureMainSession();
            const result = await this.phoenix.query({
                sessionId,
                query,
                scope: this.toPhoenixScope(scope),
                targets: ['chunks'],
                limit,
                temporal: null,
            });

            for (const hit of result.chunkHits || []) {
                const noteId = chunkIdToDocumentId(hit.chunkId);
                mergeSearchResult(byNote, {
                    DocID: noteId,
                    Score: hit.score,
                    ChunkID: hit.chunkId,
                });
            }
        } catch (error) {
            console.warn('[PhoenixUiApi] Semantic search failed; returning line-search results.', error);
        }

        return Array.from(byNote.values()).sort((left, right) => right.Score - left.Score).slice(0, limit);
    }

    async lineSearch(query: string, limit = 50, scope?: SearchScope): Promise<PhoenixLineSearchHit[]> {
        await this.loadRuntime();
        return this.store.lineSearch(query, {
            limit,
            before: 1,
            after: 1,
            scope: this.toLineSearchScope(scope),
        });
    }

    async scan(text: string, provenance?: ProvenanceContext): Promise<any> {
        await this.loadRuntime();
        if (!this.dictionary.length) {
            await this.hydrateWithEntitiesInternal();
        }
        const scan = await this.phoenix.scan({
            text,
            scope: this.toPhoenixScope({ folderPath: provenance?.parentPath }),
            sessionId: 'phoenix-ui-scan',
            resolverSeed: this.buildResolverSeed({ folderPath: provenance?.parentPath }),
        });
        const structure = await this.phoenix.buildStructure({ text, scan });
        const graph = buildGraphFromScanResult(text, scan, structure);
        return {
            ...scan,
            structure,
            graph: {
                Nodes: graph.nodes,
                Edges: graph.edges,
            },
            timing_us: 0,
        };
    }

    async scanDiscovery(text: string): Promise<PhoenixDiscoveryCandidate[]> {
        await this.loadRuntime();
        if (!this.dictionary.length) {
            await this.hydrateWithEntitiesInternal();
        }
        const scan = await this.phoenix.scan({
            text,
            scope: {},
            sessionId: 'phoenix-ui-discovery',
            resolverSeed: this.buildResolverSeed(),
        });

        const mentions = normalizeScanMentions(text, Array.isArray(scan?.mentions) ? scan.mentions : []);
        return groupDiscoveryMentions(text, mentions);
    }

    async scanImplicitAsync(text: string): Promise<DecorationSpan[]> {
        return this.scanEntityMentionsAsync(text);
    }

    async scanEntityMentionsAsync(text: string, scope?: SearchScope): Promise<DecorationSpan[]> {
        await this.loadRuntime();
        if (!this.dictionary.length) {
            await this.hydrateWithEntities();
        }
        const resolverSeed = this.buildResolverSeed(scope);
        if (!text || !resolverSeed.length) {
            return [];
        }
        const scan = await this.phoenix.scan({
            text,
            scope: this.toPhoenixScope(scope),
            sessionId: 'phoenix-ui-entity-scan',
            resolverSeed,
        });
        return knownMentionsToSpans(text, Array.isArray(scan?.mentions) ? scan.mentions : [], this.dictionary);
    }

    async analyzeText(text: string): Promise<any> {
        await this.loadRuntime();
        return this.phoenix.analyzeText(text);
    }

    async knowledgeInit(): Promise<{ success: boolean; message?: string; error?: string }> {
        await this.loadRuntime();
        await this.refreshKnowledgeGraph();
        return { success: true, message: 'Phoenix knowledge graph ready' };
    }

    async knowledgeLoad(): Promise<{ success: boolean; message?: string; error?: string }> {
        await this.loadRuntime();
        await this.refreshKnowledgeGraph();
        return { success: true, message: 'Phoenix knowledge graph loaded' };
    }

    async knowledgeSync(): Promise<{ success: boolean; message?: string; error?: string }> {
        await this.loadRuntime();
        await this.refreshKnowledgeGraph();
        return { success: true, message: 'Phoenix knowledge graph synced' };
    }

    async knowledgeSave(): Promise<{ success: boolean; message?: string; error?: string }> {
        await this.loadRuntime();
        return { success: true, message: 'Phoenix graph is already persisted' };
    }

    async knowledgeAddNode(node: {
        id: string;
        kind: string;
        label?: string;
        props?: Record<string, unknown>;
    }): Promise<{ success: boolean; message?: string; error?: string }> {
        await this.loadRuntime();
        await this.phoenix.storeCommand('graph:upsertNode', {
            id: node.id,
            kind: node.kind,
            label: node.label || node.id,
            props: node.props || {},
        });
        await this.refreshKnowledgeGraph();
        return { success: true };
    }

    async knowledgeAddEdge(edge: {
        source: string;
        target: string;
        relation: string;
        weight?: number;
        props?: Record<string, unknown>;
    }): Promise<{ success: boolean; message?: string; error?: string }> {
        await this.loadRuntime();
        await this.phoenix.storeCommand('graph:upsertEdge', {
            source: edge.source,
            target: edge.target,
            edgeType: edge.relation,
            weight: edge.weight ?? 1,
            props: edge.props || {},
        });
        await this.refreshKnowledgeGraph();
        return { success: true };
    }

    async knowledgeGetNode(id: string): Promise<any> {
        await this.ensureKnowledgeGraph();
        return this.knowledgeGraph.nodes[id] || null;
    }

    async knowledgeGetChildren(id: string, relation?: string): Promise<any[]> {
        await this.ensureKnowledgeGraph();
        return this.knowledgeGraph.edges
            .filter((edge) => edge.source === id && (!relation || edge.relation === relation))
            .map((edge) => this.knowledgeGraph.nodes[edge.target])
            .filter(Boolean);
    }

    async knowledgeGetParents(id: string, relation?: string): Promise<any[]> {
        await this.ensureKnowledgeGraph();
        return this.knowledgeGraph.edges
            .filter((edge) => edge.target === id && (!relation || edge.relation === relation))
            .map((edge) => this.knowledgeGraph.nodes[edge.source])
            .filter(Boolean);
    }

    async knowledgeGetAncestors(id: string, relation?: string, maxDepth = -1): Promise<any[]> {
        return this.walkKnowledgeGraph(id, 'parents', relation, maxDepth);
    }

    async knowledgeGetDescendants(id: string, relation?: string, maxDepth = -1): Promise<any[]> {
        return this.walkKnowledgeGraph(id, 'children', relation, maxDepth);
    }

    async knowledgeGetNeighborhood(id: string): Promise<any[]> {
        await this.ensureKnowledgeGraph();
        const neighbors = new Map<string, KnowledgeGraphNode>();
        for (const edge of this.knowledgeGraph.edges) {
            if (edge.source === id && this.knowledgeGraph.nodes[edge.target]) {
                neighbors.set(edge.target, this.knowledgeGraph.nodes[edge.target]);
            }
            if (edge.target === id && this.knowledgeGraph.nodes[edge.source]) {
                neighbors.set(edge.source, this.knowledgeGraph.nodes[edge.source]);
            }
        }
        return Array.from(neighbors.values());
    }

    async knowledgeGetGraph(): Promise<KnowledgeGraphData> {
        await this.ensureKnowledgeGraph();
        return this.knowledgeGraph;
    }

    async knowledgeGraphDelta(
        scope?: SearchScope,
        changedDocuments: readonly string[] = [],
        includeCandidateGraph = false,
    ): Promise<PhoenixGraphDeltaBinaryResult> {
        await this.loadRuntime();
        const sessionId = await this.ensureMainSession();
        return this.phoenix.graphDelta({
            sessionId,
            scope: this.toPhoenixScope(scope),
            changedDocuments: Array.from(new Set(changedDocuments.filter(Boolean))),
            limit: null,
            sinceCommit: null,
            includeCandidateGraph,
        });
    }

    async atlasRichScan(request: AtlasRichScanRequest): Promise<AtlasRichScanResult> {
        await this.loadRuntime();
        if (!this.dictionary.length) {
            await this.hydrateWithEntitiesInternal();
        }
        const scope = this.toPhoenixScope(request.scope);
        const result = await this.phoenix.atlasRichScan({
            scanId: request.scanId ?? null,
            sessionId: await this.ensureMainSession(),
            scope: {
                mode: request.scope?.mode || (request.scope?.noteId ? 'note' : request.scope?.folderId ? 'folder' : request.scope?.narrativeId ? 'narrative' : 'global'),
                ...scope,
                noteId: request.scope?.noteId || null,
                noteIds: request.scope?.noteIds || [],
            },
            documents: (request.documents || []).map((document) => ({
                documentId: document.documentId,
                noteId: document.noteId || document.documentId,
                title: document.title || document.documentId,
                text: document.text || '',
                scope: this.toPhoenixScope(document.scope || request.scope),
            })),
            changedDocumentIds: request.changedDocumentIds || [],
            resolverSeed: this.buildResolverSeed(request.scope),
            acceptedCandidateIds: [],
            rejectedCandidateKeys: [],
            options: {
                policy: request.policy || 'dirty-only',
                embeddingModelId: request.embeddingModelId || null,
                embeddingDimension: request.embeddingDimension || null,
                surfaceConfigHash: request.surfaceConfigHash || null,
                graphConfigHash: request.graphConfigHash || null,
                returnCandidateSuggestions: request.returnCandidateSuggestions !== false,
                includeSemanticAtlas: request.includeSemanticAtlas !== false,
            },
        }) as AtlasRichScanResult;
        this.invalidateKnowledgeGraphCache();
        this.store.markDerivedDirty();
        await this.store.triggerSnapshot();
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('phoenix-projection-invalidated'));
            window.dispatchEvent(new CustomEvent('phoenix-semantic-atlas-updated', { detail: result }));
        }
        return result;
    }

    async loadSemanticAtlasEmbeddings(scope?: SearchScope): Promise<SemanticAtlasEmbeddingAtlas | null> {
        await this.loadRuntime();
        try {
            const [documentRows, nodeRows, candidateRows] = await Promise.all([
                this.phoenix.storeCommand('relation:list', { relation: 'semantic_documents' }),
                this.phoenix.storeCommand('relation:list', { relation: 'semantic_node_prototypes' }),
                this.phoenix.storeCommand('relation:list', { relation: 'graph_candidate_edges' }),
            ]);
            return semanticAtlasRowsToPayload(
                Array.isArray(documentRows) ? documentRows : [],
                Array.isArray(nodeRows) ? nodeRows : [],
                Array.isArray(candidateRows) ? candidateRows : [],
                scope,
            );
        } catch (error) {
            console.warn('[PhoenixUiApi] Backend Semantic Atlas embeddings unavailable.', error);
            return null;
        }
    }

    async loadManifoldAtlasSnapshot(
        manifold: AtlasManifoldMode,
        scope?: SearchScope,
    ): Promise<ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas> | null> {
        const totalStarted = performance.now();
        const runtimeStarted = performance.now();
        await this.loadRuntime();
        const runtimeLoadMs = elapsedMs(runtimeStarted);
        try {
            const nativeStarted = performance.now();
            const nativeSnapshot = await this.phoenix.manifoldSnapshot({ manifold, scope: this.toPhoenixScope(scope), limit: 360 });
            if (nativeSnapshot?.payload?.nodes?.length) {
                return withManifoldLoadTimings(nativeSnapshot as ManifoldAtlasSnapshot<SemanticAtlasEmbeddingAtlas>, {
                    runtimeLoadMs,
                    nativeSnapshotMs: elapsedMs(nativeStarted),
                    totalMs: elapsedMs(totalStarted),
                    source: 'native',
                });
            }
        } catch (error) {
            console.warn('[PhoenixUiApi] Native manifold snapshot unavailable; using Semantic Atlas fallback.', error);
        }
        const fallbackStarted = performance.now();
        const payload = await this.loadSemanticAtlasEmbeddings(scope);
        if (!payload) return null;
        const isHopf = manifold === 'hopf';
        const isLorentz = manifold === 'lorentz';
        const isProduct = manifold === 'product';
        const isSiegel = manifold === 'siegel';
        return {
            manifold,
            geometryVersion: isHopf
                ? 'hopf_ico_r5_v1'
                : isLorentz
                  ? 'lorentz_h4_forest_v1'
                  : isProduct
                    ? 'product_lorentz_hopf_v1'
                    : isSiegel
                      ? 'siegel_finsler_v1'
                  : 'hybrid_semantic_v1',
            sourceLabel: isHopf
                ? 'backend semantic atlas -> hopf adapter'
                : isLorentz
                  ? 'backend semantic atlas -> lorentz tree adapter'
                  : isProduct
                    ? 'backend semantic atlas -> product adapter'
                    : isSiegel
                      ? 'backend semantic atlas -> siegel-finsler adapter'
                  : payload.sourceLabel,
            capabilities: isHopf
                ? HOPF_MANIFOLD_CAPABILITIES
                : isLorentz
                  ? LORENTZ_MANIFOLD_CAPABILITIES
                  : isProduct
                    ? PRODUCT_MANIFOLD_CAPABILITIES
                    : isSiegel
                      ? SIEGEL_FINSLER_CAPABILITIES
                : HYBRID_MANIFOLD_CAPABILITIES,
            payload: {
                ...payload,
                projectionSource: 'semantic_atlas_rows',
            },
            timings: {
                runtimeLoadMs,
                fallbackLoadMs: elapsedMs(fallbackStarted),
                totalMs: elapsedMs(totalStarted),
                source: 'fallback',
            },
        };
    }

    async loadStagedGraphScenePacket(request: PhoenixGraphScenePacketRequest): Promise<PhoenixGraphScenePacket | null> {
        await this.loadRuntime();
        try {
            return await this.phoenix.graphScenePacket(request);
        } catch (error) {
            console.warn('[PhoenixUiApi] Native graph scene packet unavailable.', error);
            return null;
        }
    }

    async lorentzForestCacheStatus(
        request: LorentzForestCacheRequest = {},
    ): Promise<LorentzForestCacheStatus> {
        await this.loadRuntime();
        return this.phoenix.lorentzForestCache(this.withNativeScope(request)) as Promise<LorentzForestCacheStatus>;
    }

    async buildLorentzForest(
        request: LorentzForestBuildRequest = {},
    ): Promise<LorentzForestBuildResponse> {
        await this.loadRuntime();
        return this.phoenix.lorentzForestBuild(this.withNativeScope(request)) as Promise<LorentzForestBuildResponse>;
    }

    async queryLorentzForest(request: LorentzForestQueryRequest): Promise<LorentzForestQueryResponse> {
        await this.loadRuntime();
        return this.phoenix.lorentzForestQuery(this.withNativeScope(request)) as Promise<LorentzForestQueryResponse>;
    }

    async systemCreateSession(config: Record<string, unknown> = {}): Promise<{ sessionId: string }> {
        await this.loadRuntime();
        const label = typeof config['label'] === 'string' ? String(config['label']) : 'phoenix-ui-session';
        const scope = this.toPhoenixScope(config['scope'] as SearchScope | undefined);
        const response = await this.phoenix.createSession(label, scope);
        return { sessionId: String(response?.sessionId || '') };
    }

    async systemIngest<T = any>(sessionId: string, request: Record<string, unknown>): Promise<T> {
        await this.loadRuntime();
        const result = await (this.phoenix.ingest({ sessionId, ...request }) as Promise<T>);
        this.store.markDerivedDirty();
        return result;
    }

    async systemSearch<T = any>(sessionId: string, request: Record<string, unknown>): Promise<T> {
        await this.loadRuntime();
        return this.phoenix.query({ sessionId, ...request }) as Promise<T>;
    }

    async systemCommit<T = any>(sessionId: string, request: Record<string, unknown> = {}): Promise<T> {
        await this.loadRuntime();
        return this.phoenix.commit(sessionId, request) as Promise<T>;
    }

    async systemGetState<T = any>(sessionId: string): Promise<T> {
        await this.loadRuntime();
        return this.phoenix.sessionState(sessionId) as Promise<T>;
    }

    async systemGetStats<T = any>(sessionId: string): Promise<T> {
        await this.loadRuntime();
        return this.phoenix.sessionStats(sessionId) as Promise<T>;
    }

    async systemClose(sessionId: string): Promise<{ success: boolean; error?: string }> {
        await this.loadRuntime();
        await this.phoenix.storeCommand('session:close', { sessionId });
        return { success: true };
    }

    async systemRun<T = any>(request: Record<string, unknown>): Promise<T> {
        await this.loadRuntime();
        const created = typeof request['sessionId'] === 'string' ? null : await this.systemCreateSession({});
        const sessionId = typeof request['sessionId'] === 'string' ? String(request['sessionId']) : created!.sessionId;
        const result: Record<string, unknown> = { sessionId };

        try {
            if (request['ingest']) {
                result['ingest'] = await this.systemIngest(sessionId, request['ingest'] as Record<string, unknown>);
            }
            if (request['search']) {
                result['search'] = await this.systemSearch(sessionId, request['search'] as Record<string, unknown>);
            }
            if (request['commit']) {
                result['commit'] = await this.systemCommit(sessionId, request['commit'] as Record<string, unknown>);
            }
            if (request['state']) {
                result['state'] = await this.systemGetState(sessionId);
            }
            if (request['stats']) {
                result['stats'] = await this.systemGetStats(sessionId);
            }
        } finally {
            if (created) {
                try {
                    await this.systemClose(created.sessionId);
                } catch (error) {
                    console.warn('[PhoenixUiApi] Failed to close disposable Phoenix session:', error);
                }
            }
        }

        return result as T;
    }

    private async initialize(): Promise<void> {
        const startedAt = Date.now();
        console.log('[PhoenixUiApi] initialize:start');
        console.log('[PhoenixUiApi] initialize:store.initialize:start');
        await this.store.initialize();
        console.log(`[PhoenixUiApi] initialize:store.initialize:complete (${Date.now() - startedAt}ms)`);
        console.log('[PhoenixUiApi] initialize:ensureMainSession:start');
        await this.ensureMainSession();
        console.log(`[PhoenixUiApi] initialize:ensureMainSession:complete (${Date.now() - startedAt}ms)`);
        if (!this.dictionary.length) {
            console.log('[PhoenixUiApi] initialize:hydrateWithEntities:start');
            await this.hydrateWithEntitiesInternal();
            console.log(`[PhoenixUiApi] initialize:hydrateWithEntities:complete (${Date.now() - startedAt}ms)`);
        }
        this.ready = true;
        const readyCallbacks = Array.from(this.readyCallbacks);
        this.readyCallbacks.clear();
        queueMicrotask(() => {
            if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('phoenix-ready'));
            }
            for (const callback of readyCallbacks) {
                try {
                    callback();
                } catch (error) {
                    console.error('[PhoenixUiApi] Ready callback failed:', error);
                }
            }
        });
        console.log(`[PhoenixUiApi] initialize:complete (${Date.now() - startedAt}ms)`);
    }

    private async ensureMainSession(): Promise<string> {
        if (this.mainSessionId) {
            return this.mainSessionId;
        }
        const response = await this.phoenix.createSession('phoenix-ui-main', {});
        this.mainSessionId = String(response?.sessionId || '');
        return this.mainSessionId;
    }

    private async ingestNoteInputs(notes: NoteIngestInput[], sessionId: string): Promise<void> {
        await this.ingestDocumentsIntoSession(
            sessionId,
            notes.map((note) => this.noteInputToDocument(note)),
        );
    }

    private async ingestDocumentsIntoSession(
        sessionId: string,
        documents: Array<{
            documentId: string;
            noteId: string;
            title: string;
            text: string;
            scope: Record<string, unknown>;
        }>,
    ): Promise<void> {
        if (!documents.length) {
            return;
        }
        await this.phoenix.ingest({
            sessionId,
            documents,
            commit: false,
        });
        this.store.markDerivedDirty();
    }

    private noteInputToDocument(note: NoteIngestInput): {
        documentId: string;
        noteId: string;
        title: string;
        text: string;
        scope: Record<string, unknown>;
    } {
        return {
            documentId: note.id,
            noteId: note.id,
            title: note.title || note.id,
            text: note.text || '',
            scope: this.toPhoenixScope({
                narrativeId: note.narrativeId,
                folderPath: note.folderPath,
            }),
        };
    }

    private async resolveNoteIngestInput(
        id: string,
        text: string,
        version?: number,
        meta?: { title?: string; narrativeId?: string; folderPath?: string },
    ): Promise<NoteIngestInput> {
        if (meta?.title && (meta?.narrativeId !== undefined || meta?.folderPath !== undefined)) {
            return {
                id,
                title: meta.title || id,
                text,
                narrativeId: meta.narrativeId || undefined,
                folderPath: meta.folderPath || undefined,
                version,
            };
        }

        const header = await this.store.getNoteHeader(id);
        return {
            id,
            title: meta?.title || header?.title || id,
            text,
            narrativeId: meta?.narrativeId ?? header?.narrativeId ?? undefined,
            folderPath: meta?.folderPath ?? header?.folderId ?? undefined,
            version,
        };
    }

    private buildResolverSeed(scope?: SearchScope): Array<Record<string, unknown>> {
        const seedScope = this.toPhoenixScope(scope);
        const entities = this.dictionary.length
            ? this.dictionary
            : [];

        return entities
            .filter(entity => entity.id && entity.label)
            .map(entity => ({
                entityId: entity.id,
                canonicalName: entity.label,
                aliases: entity.aliases || [],
                kind: toRustEntityKind(entity.kind),
                gender: null,
                number: null,
                scope: seedScope,
            }));
    }

    private toPhoenixScope(scope?: SearchScope | Record<string, unknown>): Record<string, unknown> {
        if (!scope) {
            return {};
        }
        const scopeRecord = scope as Record<string, unknown>;
        const noteIds = Array.isArray(scopeRecord['noteIds'])
            ? scopeRecord['noteIds'].filter((value): value is string => typeof value === 'string' && value.length > 0)
            : undefined;
        return {
            mode: typeof scopeRecord['mode'] === 'string' ? scopeRecord['mode'] : undefined,
            noteId: typeof scopeRecord['noteId'] === 'string' ? scopeRecord['noteId'] : undefined,
            noteIds,
            narrativeId: typeof scopeRecord['narrativeId'] === 'string' ? scopeRecord['narrativeId'] : undefined,
            folderPath: typeof scopeRecord['folderPath'] === 'string' ? scopeRecord['folderPath'] : undefined,
            worldId: typeof scopeRecord['worldId'] === 'string' ? scopeRecord['worldId'] : undefined,
            folderId: typeof scopeRecord['folderId'] === 'string' ? scopeRecord['folderId'] : undefined,
        };
    }

    private withNativeScope(request: { scope?: Record<string, unknown> }): Record<string, unknown> {
        return {
            ...request,
            scope: this.toPhoenixScope(request.scope),
        };
    }

    private toLineSearchScope(scope?: SearchScope | Record<string, unknown>): PhoenixLineSearchScope | undefined {
        const normalized = this.toPhoenixScope(scope);
        const lineScope: PhoenixLineSearchScope = {
            noteId: typeof (scope as Record<string, unknown> | undefined)?.['noteId'] === 'string'
                ? String((scope as Record<string, unknown>)['noteId'])
                : undefined,
            worldId: typeof normalized['worldId'] === 'string' ? normalized['worldId'] : undefined,
            narrativeId: typeof normalized['narrativeId'] === 'string' ? normalized['narrativeId'] : undefined,
            folderId: typeof normalized['folderId'] === 'string' ? normalized['folderId'] : undefined,
            folderPath: typeof normalized['folderPath'] === 'string' ? normalized['folderPath'] : undefined,
        };
        return Object.values(lineScope).some(Boolean) ? lineScope : undefined;
    }

    private async ensureKnowledgeGraph(): Promise<void> {
        if (Object.keys(this.knowledgeGraph.nodes).length || this.knowledgeGraph.edges.length) {
            return;
        }
        await this.refreshKnowledgeGraph();
    }

    private async refreshKnowledgeGraph(): Promise<void> {
        const delta = await this.knowledgeGraphDelta();
        const nextGraph = graphDeltaToKnowledgeGraph(delta);
        const graphNodes: Record<string, KnowledgeGraphNode> = { ...nextGraph.nodes };
        const graphEdges: KnowledgeGraphEdge[] = [...nextGraph.edges];

        if (!Object.keys(graphNodes).length) {
            const entityRows = await this.store.listEntities();
            for (const entity of entityRows) {
                graphNodes[entity.id] = {
                    id: entity.id,
                    kind: entity.kind,
                    label: entity.label,
                    props: { narrativeId: entity.narrativeId || '' },
                };
            }
        }

        if (!graphEdges.length) {
            const edgeRowsFallback = await this.store.listAllEdges();
            for (const edge of edgeRowsFallback) {
                graphEdges.push({
                    source: edge.sourceId,
                    target: edge.targetId,
                    relation: edge.relType,
                    weight: edge.confidence,
                    props: {},
                });
            }
        }

        this.knowledgeGraph = {
            nodes: graphNodes,
            edges: graphEdges,
        };
    }

    private async walkKnowledgeGraph(
        startId: string,
        direction: 'children' | 'parents',
        relation?: string,
        maxDepth = -1,
    ): Promise<any[]> {
        await this.ensureKnowledgeGraph();
        const results = new Map<string, KnowledgeGraphNode>();
        const queue: Array<{ id: string; depth: number }> = [{ id: startId, depth: 0 }];
        const seen = new Set<string>([startId]);

        while (queue.length) {
            const current = queue.shift();
            if (!current) {
                continue;
            }

            const matches = this.knowledgeGraph.edges.filter((edge) => {
                if (relation && edge.relation !== relation) {
                    return false;
                }
                return direction === 'children' ? edge.source === current.id : edge.target === current.id;
            });

            for (const edge of matches) {
                const nextId = direction === 'children' ? edge.target : edge.source;
                if (seen.has(nextId)) {
                    continue;
                }
                seen.add(nextId);
                const node = this.knowledgeGraph.nodes[nextId];
                if (node) {
                    results.set(nextId, node);
                }
                if (maxDepth < 0 || current.depth + 1 < maxDepth) {
                    queue.push({ id: nextId, depth: current.depth + 1 });
                }
            }
        }

        return Array.from(results.values());
    }
}

function buildGraphFromScanResult(text: string, scan: any, structure: any): {
    nodes: Record<string, { id: string; label: string; kind: string }>;
    edges: Array<{ Source: string; Target: string; Relation: string }>;
} {
    const nodes: Record<string, { id: string; label: string; kind: string }> = {};
    const mentionByKey = new Map<string, { id: string; label: string; kind: string }>();
    const rangeConverter = createUtf8ByteRangeConverter(text);
    const slice = (range: any) => rangeConverter.slice(range);
    const mentions = Array.isArray(scan?.mentions) ? scan.mentions : [];

    for (const mention of mentions) {
        const key = mentionKey(mention, slice);
        if (!key) {
            continue;
        }
        const label = String(mention?.surface || slice(mention?.range) || key);
        const kind = String(mention?.kind || 'UNKNOWN');
        const node = { id: key, label, kind };
        nodes[key] = node;
        mentionByKey.set(key, node);
    }

    const edges: Array<{ Source: string; Target: string; Relation: string }> = [];
    const relations = Array.isArray(structure?.relations) ? structure.relations : [];
    for (const relation of relations) {
        const source = frameSlotToNodeId(relation?.subject, mentionByKey, slice);
        const target = frameSlotToNodeId(relation?.object || relation?.recipient, mentionByKey, slice);
        if (!source || !target) {
            continue;
        }
        edges.push({
            Source: source,
            Target: target,
            Relation: String(relation?.relationType || relation?.lemma || 'RELATED_TO'),
        });
    }

    return { nodes, edges };
}

function frameSlotToNodeId(
    slot: any,
    mentionByKey: Map<string, { id: string; label: string; kind: string }>,
    sliceRange: (range: any) => string,
): string | null {
    if (!slot) {
        return null;
    }
    const entityRef = slot?.entityRef;
    if (typeof entityRef === 'string' && mentionByKey.has(entityRef)) {
        return entityRef;
    }
    if (entityRef && typeof entityRef === 'object') {
        if (typeof entityRef.Known === 'string') return entityRef.Known;
        if (typeof entityRef.known === 'string') return entityRef.known;
        if (typeof entityRef.Speculative === 'string') return entityRef.Speculative;
        if (typeof entityRef.speculative === 'string') return entityRef.speculative;
    }
    const label = sliceRange(slot?.range);
    return label || null;
}

function mentionKey(mention: any, sliceRange: (range: any) => string): string | null {
    const entityRef = mention?.entityRef;
    if (entityRef && typeof entityRef === 'object') {
        if (typeof entityRef.Known === 'string') return entityRef.Known;
        if (typeof entityRef.known === 'string') return entityRef.known;
        if (typeof entityRef.Speculative === 'string') return entityRef.Speculative;
        if (typeof entityRef.speculative === 'string') return entityRef.speculative;
    }
    return String(mention?.surface || sliceRange(mention?.range) || '').trim() || null;
}

function mergeSearchResult(results: Map<string, PhoenixSearchResult>, next: PhoenixSearchResult): void {
    const current = results.get(next.DocID);
    if (!current) {
        results.set(next.DocID, next);
        return;
    }
    current.Score = Math.max(current.Score, next.Score);
    if (next.LineNumber !== undefined && current.LineNumber === undefined) {
        current.LineNumber = next.LineNumber;
        current.Snippet = next.Snippet;
    }
    if (next.Score >= current.Score) {
        current.ChunkID = next.ChunkID;
    }
    if (next.LineHits?.length) {
        current.LineHits = [...(current.LineHits || []), ...next.LineHits];
    }
}

function knownMentionsToSpans(
    text: string,
    mentions: any[],
    dictionary: DictionaryEntry[],
): DecorationSpan[] {
    const byId = new Map(dictionary.map(entity => [entity.id, entity]));
    const rangeConverter = createUtf8ByteRangeConverter(text);
    const spans: DecorationSpan[] = [];
    for (const mention of mentions) {
        const entityId = entityIdFromRef(mention?.entityRef ?? mention?.entity_ref);
        if (!entityId) {
            continue;
        }
        const entity = byId.get(entityId);
        if (!entity) {
            continue;
        }
        const range = rangeConverter.toUtf16Range(mention?.range);
        if (!range || range.from >= range.to || range.to > text.length) {
            continue;
        }
        const source = String(mention?.source || '').toLocaleLowerCase();
        spans.push({
            type: 'entity_implicit',
            from: range.from,
            to: range.to,
            label: entity.label,
            kind: entity.kind as EntityKind,
            target: entity.label,
            matchedText: String(mention?.surface || rangeConverter.slice(mention?.range)),
            entityId,
            resolved: true,
            matchSource: source || 'known',
            confidence: Number(mention?.confidence || 0),
        });
    }
    for (const span of dictionaryLiteralSpans(text, dictionary)) {
        if (spans.some((existing) => spansOverlap(existing, span))) {
            continue;
        }
        spans.push(span);
    }
    return spans.sort((left, right) => left.from - right.from || left.to - right.to);
}

function dictionaryLiteralSpans(text: string, dictionary: DictionaryEntry[]): DecorationSpan[] {
    const patterns: Array<PhoenixLiteralPattern<DictionaryEntry>> = [];
    const seen = new Set<string>();
    for (const entity of dictionary) {
        for (const surface of [entity.label, ...(entity.aliases || [])]) {
            const normalized = String(surface || '').trim().replace(/\s+/g, ' ');
            const key = normalized.toLocaleLowerCase();
            if (!normalized || seen.has(key)) {
                continue;
            }
            seen.add(key);
            patterns.push({ text: normalized, payload: entity });
        }
    }

    return matchLiteralPatterns(text, patterns, {
        wholeWord: true,
    }).map((match) => {
        const entity = match.payload!;
        return {
            type: 'entity_implicit',
            from: match.from,
            to: match.to,
            label: entity.label,
            kind: entity.kind as EntityKind,
            target: entity.label,
            matchedText: match.text,
            entityId: entity.id,
            resolved: true,
            matchSource: 'dictionary',
            confidence: 1,
        };
    });
}

function spansOverlap(left: DecorationSpan, right: DecorationSpan): boolean {
    return left.from < right.to && right.from < left.to;
}

function entityIdFromRef(entityRef: unknown): string {
    if (typeof entityRef === 'string') {
        return entityRef;
    }
    if (entityRef && typeof entityRef === 'object') {
        const keyed = entityRef as Record<string, unknown>;
        if (typeof keyed['known'] === 'string') return keyed['known'];
        if (typeof keyed['Known'] === 'string') return keyed['Known'];
    }
    return '';
}

function toRustEntityKind(kind: string): string | null {
    switch (String(kind || '').toUpperCase()) {
        case 'CHARACTER':
            return 'character';
        case 'LOCATION':
            return 'location';
        case 'NPC':
            return 'npc';
        case 'CREATURE':
            return 'npc';
        case 'ITEM':
            return 'item';
        case 'FACTION':
            return 'faction';
        case 'ORGANIZATION':
            return 'organization';
        case 'EVENT':
            return 'event';
        case 'CONCEPT':
            return 'concept';
        default:
            return 'other';
    }
}

function chunkIdToDocumentId(chunkId: string): string {
    const separator = chunkId.indexOf(':');
    return separator >= 0 ? chunkId.slice(0, separator) : chunkId;
}

function graphDeltaToKnowledgeGraph(delta: PhoenixGraphDeltaBinaryResult): KnowledgeGraphData {
    const nodes: Record<string, KnowledgeGraphNode> = {};
    for (const chunk of delta.chunks || []) {
        if (!chunk.vertexId) continue;
        nodes[chunk.vertexId] = {
            id: chunk.vertexId,
            kind: 'leaf',
            label: chunk.chunkId || chunk.vertexId,
            props: {
                chunkId: chunk.chunkId,
                documentId: chunk.documentId,
                noteId: chunk.noteId || chunk.documentId,
                chapterId: chunk.chapterId,
                start: chunk.start,
                end: chunk.end,
            },
        };
    }
    for (const node of delta.nodes || []) {
        if (!node.nodeId) continue;
        nodes[node.nodeId] = {
            id: node.nodeId,
            kind: node.kind || 'unknown',
            label: node.label || node.entityId || node.nodeId,
            props: {
                entityId: node.entityId,
                documentId: node.documentId,
                chapterId: node.chapterId,
                weight: node.weight,
            },
        };
    }
    const edges = (delta.edges || [])
        .map((edge) => ({
            source: edge.sourceId,
            target: edge.targetId,
            relation: edge.edgeType || 'edge',
            weight: edge.weight,
            props: {},
        }))
        .filter((edge) => edge.source && edge.target && nodes[edge.source] && nodes[edge.target]);
    return { nodes, edges };
}

function semanticAtlasRowsToPayload(
    documentRows: any[],
    nodeRows: any[],
    candidateRows: any[],
    scope?: SearchScope,
): SemanticAtlasEmbeddingAtlas | null {
    const nodes: SemanticAtlasEmbeddingNode[] = [];
    const seen = new Set<string>();
    const noteFilters = new Set([
        ...(scope?.noteIds || []),
        scope?.noteId || '',
    ].filter(Boolean));

    for (const row of documentRows) {
        const documentId = stringField(row, 'document_id', 'documentId');
        if (!documentId || (noteFilters.size && !noteFilters.has(documentId))) {
            continue;
        }
        const vector = vectorField(row, 'vec');
        if (!vector.length) {
            continue;
        }
        const id = `doc::${documentId}`;
        seen.add(id);
        nodes.push({
            id,
            label: `Document ${documentId.slice(0, 8)}`,
            sourceType: 'leaf',
            vector,
            documentId,
            preview: evidencePreview(row),
            kind: 'CONCEPT',
        });
    }

    for (const row of nodeRows) {
        const id = stringField(row, 'node_id', 'nodeId');
        const documentId = stringField(row, 'document_id', 'documentId');
        const narrativeId = stringField(row, 'narrative_id', 'narrativeId');
        const folderId = stringField(row, 'folder_id', 'folderId');
        if (!id || !semanticNodeMatchesScope({ documentId, narrativeId, folderId }, scope)) {
            continue;
        }
        const vector = vectorField(row, 'vec');
        if (!vector.length) {
            continue;
        }
        const nodeKind = stringField(row, 'node_kind', 'nodeKind') || 'entity';
        seen.add(id);
        nodes.push({
            id,
            label: semanticNodeLabel(id),
            sourceType: nodeKind.includes('lens') ? 'lens' : nodeKind.includes('entity') ? 'entity' : nodeKind,
            vector,
            documentId,
            narrativeId,
            folderId,
            preview: evidencePreview(row),
            kind: nodeKind.includes('event') ? 'EVENT' : 'CONCEPT',
        });
    }

    if (!nodes.length) {
        return null;
    }

    const edges = candidateRows
        .map((row) => {
            const sourceId = stringField(row, 'source_id', 'sourceId');
            const targetId = stringField(row, 'target_id', 'targetId');
            if (!sourceId || !targetId || !seen.has(sourceId) || !seen.has(targetId)) {
                return null;
            }
            const type = stringField(row, 'edge_type', 'edgeType') || 'candidate_relation';
            return {
                id: `${sourceId}:${type}:${targetId}`,
                sourceId,
                targetId,
                type,
                confidence: candidateConfidence(row),
            } satisfies SemanticAtlasEmbeddingEdge;
        })
        .filter((edge): edge is SemanticAtlasEmbeddingEdge => !!edge);

    return {
        nodes,
        edges,
        sourceLabel: 'backend semantic atlas',
    };
}

function semanticNodeMatchesScope(
    row: { documentId?: string; narrativeId?: string; folderId?: string },
    scope?: SearchScope,
): boolean {
    if (!scope) return true;
    if (scope.noteIds?.length && !scope.noteIds.includes(row.documentId || '')) return false;
    if (scope.noteId && row.documentId !== scope.noteId) return false;
    if (scope.narrativeId && row.narrativeId !== scope.narrativeId) return false;
    if (scope.folderId && row.folderId !== scope.folderId) return false;
    return true;
}

function stringField(row: any, snake: string, camel: string): string {
    const value = row?.[snake] ?? row?.[camel];
    return typeof value === 'string' ? value : '';
}

function vectorField(row: any, key: string): number[] {
    const value = row?.[key];
    return Array.isArray(value)
        ? value.map((entry) => Number(entry)).filter((entry) => Number.isFinite(entry))
        : [];
}

function evidencePreview(row: any): string {
    const refs = row?.evidence_refs ?? row?.evidenceRefs;
    return Array.isArray(refs) ? refs.slice(0, 3).map(String).join(' · ') : '';
}

function semanticNodeLabel(id: string): string {
    return id
        .replace(/^(entity|event|doc)::/i, '')
        .replace(/^atlas:/i, '')
        .replace(/[-_:]+/g, ' ')
        .trim()
        .slice(0, 48) || id;
}

function candidateConfidence(row: any): number {
    const attributes = asRecord(row?.attributes);
    const graph = asRecord(attributes['graph']);
    const raw = Number(attributes['score'] ?? graph['confidence'] ?? Number(row?.weight || 0) / 1000);
    return Number.isFinite(raw) && raw > 0 ? raw : 0.35;
}

function extractDocumentIds(value: string): string[] {
    if (!value) return [];
    return Array.from(value.matchAll(DOCUMENT_ID_PATTERN), (match) => match[0].toLocaleLowerCase());
}

function asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
}

function normalizeScanMentions(text: string, mentions: any[]): any[] {
    if (!mentions.length) {
        return mentions;
    }

    const rangeConverter = createUtf8ByteRangeConverter(text);
    return mentions.map((mention) => {
        const normalizedRange = rangeConverter.toUtf16Range(mention?.range);
        if (!normalizedRange) {
            return mention;
        }

        return {
            ...mention,
            range: {
                start: normalizedRange.from,
                end: normalizedRange.to,
            },
        };
    });
}

function withManifoldLoadTimings<TPayload>(
    snapshot: ManifoldAtlasSnapshot<TPayload>,
    timings: NonNullable<ManifoldAtlasSnapshot<TPayload>['timings']>,
): ManifoldAtlasSnapshot<TPayload> {
    return {
        ...snapshot,
        timings: {
            ...(snapshot.timings || {}),
            ...timings,
        },
    };
}

function elapsedMs(started: number): number {
    return Math.max(0, Math.round(performance.now() - started));
}

export const phoenixUiApiServiceTestHooks = {
    graphDeltaToKnowledgeGraph,
    knownMentionsToSpans,
};
