import { Injectable, computed, inject, signal } from '@angular/core';
import { gzipSync, gunzipSync, strFromU8, strToU8 } from 'fflate';

import {
    db,
    type EntityOccurrence,
    type Folder,
    type Note,
    type NoteBlockProjection,
} from '../lib/dexie/db';
import { parseContentToPlainText } from '../lib/analytics';
import * as ops from '../lib/operations';
import type { RegisteredEntity } from '../lib/registry';
import {
    PhoenixBackendService,
    type PhoenixGraphRunPageSection,
} from '../services/phoenix-backend.service';
import {
    PhoenixStoreService,
    type PhoenixContentMutationTiming,
    type StoreScopedDocument,
} from '../services/phoenix-store.service';
import { attachGraphCompilerReadModels } from './graph-compiler-read-model';
import {
    buildFallbackDocumentProfileSummary,
    normalizeDocumentProfileSummary,
    type GraphDocumentProfileSummary,
} from './graph-document-profile';
import {
    isGraphDocumentSemanticSummary,
    type GraphDocumentSemanticSummary,
} from './graph-document-semantic';
import {
    applyGraphOperatorMutationDecisionToSnapshot,
    isGraphOperatorMutationJournal,
    graphOperatorMutationJournalFromTruthCommits,
    mergeGraphOperatorMutationJournals,
    type GraphOperatorMutationDecision,
    type GraphOperatorMutationJournal,
} from './graph-operator-mutation-journal';
import {
    bindNativeDecisionToOperatorMutation,
    isNativeOperatorDecisionBeginResponse,
    isNativeOperatorDecisionCompleteResponse,
    nativeOperatorDecisionBeginRequest,
    nativeOperatorDecisionCompleteRequest,
    pendingNativeOperatorDecisionCompletions,
} from './graph-native-decision-capture';
import {
    CANONICAL_EPISODE_ASSIGNMENT_BATCH_COMMIT_SCHEMA,
    canonicalEpisodeAssignmentCommitRequest,
    isCanonicalEpisodeAssignmentBatchCommitResponse,
    isCanonicalEpisodeAssignmentCommitResponse,
    type CanonicalEpisodeAssignmentBatchCommitResponse,
    type CanonicalEpisodeAssignmentCommitResponse,
    type CanonicalEpisodeAssignmentSelection,
} from './graph-canonical-episode-assignment';
import {
    applyNativeMemoryGovernanceCandidates,
    applyNativeMemoryGovernanceRetrievalExperiment,
    memoryGovernanceRetrievalCandidatesFromSnapshot,
} from './graph-memory-governance';
import {
    applyNativePromotionVerdictCertificate,
    buildGraphPromotionPreviewReceipts,
    isNativePromotionVerdictOutput,
    type NativePromotionVerdictOutput,
} from './graph-promotion-verdict';
import {
    applyReviewAdjudicationCertificate,
    type GraphReviewAdjudicationRunCertificate,
} from './graph-review-adjudication-certificate';
import type {
    GraphAtlasObject,
    GraphAtlasObjectStatus,
    GraphAtlasPacket,
} from './graph-atlas-packet';
import { GraphRebuildCpuProfiler } from './graph-rebuild-cpu-profile';
import {
    GRAPH_ATLAS_BUILDER_ROLE,
    GRAPH_ATLAS_IDENTITY_AUTHORITY,
    GRAPH_ATLAS_PACKET_AUTHORITY,
} from './graph-atlas-packet';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { applyNativeChunkSemanticBridgeCandidates } from './graph-rebuild-derived-facts';
import {
    isGraphCrossDocumentBridgeRunCertificate,
    type GraphCrossDocumentBridgeRunCertificate,
} from './graph-cross-document-bridge-certificate';
import {
    applyNativeStoryContinuityContract,
    isNativeStoryContinuityOutput,
    type GraphStoryContinuityContract,
    type NativeStoryContinuityOutput,
} from './graph-story-continuity';
import { finalizeGraphRebuildSnapshot } from './graph-snapshot-finalizer';
import {
    buildGraphSnapshotSourceEvidence,
    mergeGraphRebuildOccurrences as mergeOccurrenceEvidence,
    type GraphSnapshotSourceEvidenceInput,
} from './graph-snapshot-source-evidence';
import { buildGraphRebuildEmbeddingGraphPostProcess } from './graph-rebuild-embedding-postprocess';
import { selectGraphRebuildEmbeddingTargetPlan } from './graph-rebuild-embedding-target-policy';
import { graphRebuildSiegelNativeRequest } from './graph-rebuild-siegel-backbone';
import {
    emptyGraphDocumentGraphMutationLedger,
    graphDocumentGraphMutationLedgerFromTruthCommits,
    type GraphDocumentGraphMutationLedger,
} from './graph-document-durable-commit';
import {
    graphTruthCommitLedgerFor,
    normalizeGraphTruthCommits,
    type GraphTruthCommitLedger,
    type GraphTruthCommitLike,
} from './graph-truth-commit-ledger';
import {
    buildAdaptiveGraphRebuildChunks,
    buildGraphRebuildChunksFromRanges,
    type GraphRebuildChunkRange,
} from './graph-rebuild-meaning-frames';
import {
    buildGraphModelV2OverGraphExport,
    type GraphModelV2OverGraphExport,
} from './graph-model-v2-overgraph';
import type {
    GraphIndexRunReceipt,
    GraphIndexPostProcessMode,
    GraphIndexEmbeddingStagePolicy,
    GraphIndexPolicy,
    GraphBuildDurabilityMode,
    GraphRebuildBuildTimings,
    GraphRebuildChunk,
    GraphRebuildChunkSemanticBridge,
    GraphRebuildContentBlobField,
    GraphRebuildContentManifest,
    GraphRebuildEmbeddingTarget,
    GraphRebuildEmbeddingTargetPlan,
    GraphRebuildEmbeddingProfile,
    GraphMemoryGovernanceCandidate,
    GraphMemoryGovernanceRetrievalWeightingExperiment,
    GraphRebuildNoteFolderContext,
    GraphRebuildRelationshipHint,
    GraphRebuildScopeKind,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import type { GraphRebuildReplayManifest } from './graph-rebuild-replay-contract';
import {
    assertGraphForceV2ShadowResult,
    buildGraphForceV2RequestFromAuthority,
    buildGraphForceV2Request,
    buildGraphForceV2ShadowRequestFromAuthority,
    buildGraphForceV2ShadowRequest,
    type GraphForceAuthorityPersistReceipt,
    type GraphForceRebuildV2ShadowResult,
} from './graph-force-rebuild-v2';
import type { GraphCompilerDualWriteSidecar } from './graph-compiler-read-model';
import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
import {
    assertGraphGenerationReceipt,
    type GraphGenerationArtifactRef,
    type GraphGenerationReceiptV2,
} from './graph-generation-receipt';
import {
    assertGraphSnapshotAuthority,
    graphSnapshotContentHash,
    graphSnapshotStableContentValue,
    hydrateGraphSnapshotContent,
    sealGraphSnapshotAuthority,
    type GraphSnapshotHydrationBlob,
} from './graph-snapshot-authority';
import {
    recordGraphCollapseBoundary,
    recordGraphCollapseFilteredTargets,
    recordGraphCollapseNativeBoundary,
    recordGraphCollapseSnapshotBoundary,
} from './graph-collapse-trace';
import {
    filterNativeEmbeddingTargetsForCommittedSources,
    mergeNativeEmbeddingTargets,
    normalizeNativeAtlasPacketSourceContract,
    reconcileNativeAtlasPacketForTargets,
} from './graph-native-atlas-packet-reconciler';
import {
    DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY,
    GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY,
    GRAPH_REBUILD_NAMESPACE,
    GENERATION_RECEIPT_DOCUMENT_KEY,
    RECEIPT_DOCUMENT_KEY,
    SNAPSHOT_DOCUMENT_KEY,
    graphIndexReceiptToScopedDocument,
    graphGenerationReceiptToScopedDocument,
    postProcessCacheDocumentKey,
    postProcessCacheToScopedDocument,
    scopedDocumentToGraphIndexReceipt,
    scopedDocumentToGraphGenerationReceipt,
    scopedDocumentToPostProcessCache,
    type GraphRebuildPostProcessCache,
} from './graph-rebuild-persistence-contract';

export { mergeGraphRebuildOccurrences } from './graph-snapshot-source-evidence';
export {
    filterNativeEmbeddingTargetsForCommittedSources,
    mergeNativeEmbeddingTargets,
    reconcileNativeAtlasPacketForTargets,
} from './graph-native-atlas-packet-reconciler';
export {
    DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY,
    GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY,
    GRAPH_REBUILD_NAMESPACE,
    GENERATION_RECEIPT_DOCUMENT_KEY,
    graphIndexReceiptToScopedDocument,
    graphGenerationReceiptToScopedDocument,
    postProcessCacheToScopedDocument,
    scopedDocumentToGraphIndexReceipt,
    scopedDocumentToGraphGenerationReceipt,
    type GraphRebuildPostProcessCache,
} from './graph-rebuild-persistence-contract';

const OPERATOR_MUTATION_JOURNAL_DOCUMENT_KEY = 'operator-mutation-journal';
const SNAPSHOT_CONTENT_BLOB_PREFIX = 'snapshot-blob';
const CONTENT_BLOB_SCHEMA_VERSION = 'phoenix-graph-rebuild-content-blob/v1';
const COMPRESSED_JSON_SCHEMA_VERSION = 'phoenix-graph-rebuild-json-payload/gzip-base64/v1';
const COMPRESSED_SNAPSHOT_SCHEMA_VERSION = 'phoenix-graph-rebuild-payload/gzip-base64/v1';
const COMPRESSED_DOCUMENT_SEMANTIC_SCHEMA_VERSION = 'phoenix-document-semantics/gzip-base64/v1';
const SNAPSHOT_COMPRESSION_MIN_CHARS = 64 * 1024;
const BASE64_CHUNK_SIZE = 0x8000;
const NATIVE_COMPILER_REVIEW_ROW_LIMIT = 128;
const NATIVE_COMPILER_DISCOURSE_CLUSTER_LIMIT = 72;
const NATIVE_COMPILER_DISCOURSE_BRIDGE_LIMIT = 96;
const NATIVE_COMPILER_PACKET_TEXT_LIMIT = 180;
const NATIVE_COMPILER_PACKET_LIST_LIMIT = 12;

interface NativeDocumentChunkOutput {
    noteId: string;
    chunks: GraphRebuildChunkRange[];
}

interface NativeDocumentChunkSummary {
    schemaVersion: 'phoenix-document-chunks/v1';
    source: 'native_rust';
    documents: NativeDocumentChunkOutput[];
}

interface CompressedGraphRebuildJsonPayload {
    schemaVersion: typeof COMPRESSED_JSON_SCHEMA_VERSION;
    sourceSchemaVersion: string;
    encoding: 'gzip+base64';
    rawChars: number;
    compressedBytes: number;
    payload: string;
}

interface CompressedGraphRebuildSnapshotPayload {
    schemaVersion: typeof COMPRESSED_SNAPSHOT_SCHEMA_VERSION;
    sourceSchemaVersion: GraphRebuildSnapshot['schemaVersion'];
    encoding: 'gzip+base64';
    rawChars: number;
    compressedBytes: number;
    payload: string;
}

interface CompressedGraphCompilerFactGraphPayload {
    schemaVersion: 'phoenix-graph-compiler-payload/gzip-base64/v1';
    sourceSchemaVersion: string;
    encoding: 'gzip+base64';
    rawBytes: number;
    compressedBytes: number;
    payload: string;
}

interface NativeEmbeddingTargetOriginCount {
    family: string;
    targets: number;
}

interface NativeAtlasSeed {
    atlasPacket: GraphAtlasPacket;
    embeddingTargets: GraphRebuildEmbeddingTarget[];
    originatingFamilies: NativeEmbeddingTargetOriginCount[];
}

interface CompressedDocumentSemanticPayload {
    schemaVersion: typeof COMPRESSED_DOCUMENT_SEMANTIC_SCHEMA_VERSION;
    sourceSchemaVersion: GraphDocumentSemanticSummary['schemaVersion'];
    encoding: 'gzip+base64';
    rawBytes: number;
    compressedBytes: number;
    payload: string;
    artifactHandle?: string;
    artifactStats?: {
        documentsBuilt?: number;
        documentsReused?: number;
        rawBytesWritten?: number;
        compressedBytesWritten?: number;
        summaryCacheHit?: boolean;
    };
}

interface NativeChunkSemanticBridgeQualityGate {
    total: number;
    accepted: number;
    demotedSameEntityOnly: number;
}

interface NativeChunkSemanticBridgeTiming {
    bridgeBuildMicros: number;
    totalMicros: number;
}

interface NativeChunkSemanticBridgeOutput {
    schemaVersion: 'phoenix-chunk-semantic-bridge-native-output/v1';
    source: 'rust';
    candidates: GraphRebuildChunkSemanticBridge[];
    crossDocumentCertificate: GraphCrossDocumentBridgeRunCertificate;
    qualityGate: NativeChunkSemanticBridgeQualityGate;
    timing: NativeChunkSemanticBridgeTiming;
}

interface NativeMemoryGovernanceTiming {
    governanceBuildMicros: number;
    totalMicros: number;
}

interface NativeMemoryGovernanceOutput {
    schemaVersion: 'phoenix-memory-governance-native-output/v1';
    source: 'rust';
    candidates: GraphMemoryGovernanceCandidate[];
    timing: NativeMemoryGovernanceTiming;
}

interface NativeMemoryGovernanceRetrievalExperimentTiming {
    governanceBuildMicros: number;
    experimentBuildMicros: number;
    totalMicros: number;
}

interface NativeMemoryGovernanceRetrievalExperimentOutput {
    schemaVersion: 'phoenix-memory-governance-retrieval-experiment-native-output/v1';
    source: 'rust';
    experiment: GraphMemoryGovernanceRetrievalWeightingExperiment;
    timing: NativeMemoryGovernanceRetrievalExperimentTiming;
}

export interface NativeSnapshotAnalysisOutput {
    schemaVersion: 'phoenix-graph-snapshot-analysis-native-output/v1';
    source: 'rust';
    bridge: NativeChunkSemanticBridgeOutput;
    continuity: NativeStoryContinuityOutput;
    governance: NativeMemoryGovernanceOutput;
    retrieval?: NativeMemoryGovernanceRetrievalExperimentOutput | null;
    promotion: NativePromotionVerdictOutput;
    siegel?: unknown;
    noTopologyWrites: true;
    timing: {
        bridgeBuildMicros: number;
        continuityBuildMicros: number;
        governanceBuildMicros: number;
        retrievalBuildMicros: number;
        verdictBuildMicros: number;
        totalMicros: number;
    };
}

export interface NativeGraphRunPage {
    schemaVersion: 'phoenix-graph-run-page/v1';
    source: 'rust';
    section?: PhoenixGraphRunPageSection;
    runHandle: string;
    offset: number;
    limit: number;
    detailRows: number;
    returnedDetailRows: number;
    nextOffset?: number | null;
    arena: {
        analysisIdentity: string;
        reused: boolean;
        residentBytes: number;
        activeLeases: number;
        projectionMicros: number;
    };
    counts: {
        bridgeCandidates: number;
        bridgeByType: Record<string, number>;
        crossDocumentPairCoverage: number;
        crossDocumentSelected: number;
        crossDocumentRejected: number;
        crossDocumentWeakest: number;
        promotionRows: number;
        continuityEvents: number;
        continuityBoundaries: number;
        continuityEpisodes: number;
        continuityTemporal: number;
        continuityStates: number;
        continuityCausal: number;
        continuityConnections: number;
        continuityConflicts: number;
        governanceCandidates: number;
        governanceByAction: Record<string, number>;
        retrievalTopRows: number;
        retrievalViolations: number;
    };
    projection: NativeSnapshotAnalysisOutput;
    analysisSource: 'computed' | 'resident_verified' | 'durable_verified';
    analysisKernelMicros: number;
}

export interface NativeGraphRunPagingState {
    snapshotId: string;
    runHandle: string;
    totalRows: number;
    loadedRows: number;
    nextOffset: number | null;
    counts: NativeGraphRunPage['counts'];
}

export interface NativeGraphRunPersistReceipt {
    schemaVersion: 'phoenix-graph-run-durable-receipt/v1';
    runHandle: string;
    scopeId: string;
    snapshotId: string;
    manifestId: string;
    changedSections: number;
    reusedSections: number;
    encodedSections: number;
    compressedSections: number;
    rawBytesWritten: number;
    compressedBytesWritten: number;
}

interface NativeGraphGenerationQueryResponse {
    schemaVersion: 'phoenix-graph-generation-asserted-query/v1';
    manifest: {
        schemaVersion: string;
        artifactDigest: string;
        payloadDigest: string;
        generation: number;
        sourceSnapshotId: string;
        sourceSnapshotDigest: string;
        nodeCount: number;
        edgeCount: number;
        excludedCandidateEdges: number;
        admittedCandidateEdges: number;
        binaryBytes: number;
    };
    communityShadow: {
        manifest: {
            artifactDigest: string;
            payloadDigest: string;
            generation: number;
            binaryBytes: number;
        };
        receipt: NativeOfflineCommunityReceipt;
    } | null;
}

export interface NativeOfflineCommunityReceipt {
    schemaVersion: 'phoenix-offline-community-artifact-shadow/v1';
    executionPathId: 'community_cpu_deterministic_v1' | 'community_gpu_wgpu_resident_v1';
    selectionReason: 'cpu_required' | 'gpu_required'
        | 'structural_gpu_crossover_met' | 'below_structural_gpu_crossover';
    generation: number;
    sourceArtifactDigest: string;
    artifactDigest: string;
    payloadDigest: string;
    nodes: number;
    coreNodes: number;
    selectedEdges: number;
    fallbackCount: 0;
    residentUploads: 0 | 1;
    runtimeReused: boolean;
    runtimeInitMicros: number;
    wallMicros: number;
    gpuPrepareMicros: number;
    gpuExecuteMicros: number;
    gpuReadbackMicros: number;
    cpuPipelineMicros: number;
    cpuLeidenMicros: number;
    cpuMetricsMicros: number;
    sealMicros: number;
    residentBytes: number;
    readbackBytes: number;
    adapter: string | null;
    productionPublished: false;
}

type StoryContinuityRows = Pick<GraphStoryContinuityContract,
    | 'events'
    | 'boundaryReceipts'
    | 'episodes'
    | 'temporalCandidates'
    | 'stateIntervals'
    | 'causalCandidates'
    | 'episodeConnections'
    | 'conflicts'>;

interface CompressedNativeAtlasSeedPayload {
    schemaVersion: 'phoenix-atlas-seed-payload/gzip-base64/v1';
    sourceSchemaVersion: 'phoenix-atlas-seed/v1';
    encoding: 'gzip+base64';
    rawBytes: number;
    compressedBytes: number;
    payload: string;
}

interface GraphTruthCommitProjection {
    commits: GraphTruthCommitLike[];
    ledger: GraphTruthCommitLedger;
}

export interface GraphRebuildContentBlobPayload {
    schemaVersion: typeof CONTENT_BLOB_SCHEMA_VERSION;
    scopeId: string;
    field: GraphRebuildContentBlobField;
    hash: string;
    value: unknown;
}

export type NativeGraphCompilerSidecar = Partial<GraphCompilerDualWriteSidecar> & {
    factGraphPayload?: CompressedGraphCompilerFactGraphPayload;
    atlasSeedPayload?: CompressedNativeAtlasSeedPayload;
    atlasPacket?: GraphAtlasPacket;
    embeddingTargets?: GraphRebuildEmbeddingTarget[];
    originatingFamilies?: NativeEmbeddingTargetOriginCount[];
};

export type NativeGraphCompilerDecodedSidecar = GraphCompilerDualWriteSidecar & {
    atlasPacket?: GraphAtlasPacket;
    embeddingTargets?: GraphRebuildEmbeddingTarget[];
    originatingFamilies?: NativeEmbeddingTargetOriginCount[];
};

export function authorizeGraphRebuildSnapshotForLoad(
    snapshot: GraphRebuildSnapshot,
    onReject?: (error: unknown) => void,
): GraphRebuildSnapshot | null {
    try {
        if (snapshot.authorityContract) assertGraphSnapshotAuthority(snapshot);
        else finalizeGraphRebuildSnapshot({ snapshot });
        return snapshot;
    } catch (error) {
        onReject?.(error);
        return null;
    }
}

export interface GraphRebuildSnapshotDocumentPayloadStats {
    rawChars: number;
    compressedBytes: number;
    savedChars: number;
    ratioPct: number;
}

export interface GraphRebuildBuildRequest {
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    noteIds: string[];
    entities: RegisteredEntity[];
    noteTexts?: Record<string, string>;
    chunks?: GraphRebuildChunk[];
    noteFolders?: Record<string, GraphRebuildNoteFolderContext>;
    previousContentManifest?: GraphRebuildContentManifest;
    sourceEvidence?: GraphSnapshotSourceEvidenceInput;
    relationshipHints?: GraphRebuildRelationshipHint[];
    embeddingProfile?: Partial<GraphRebuildEmbeddingProfile>;
    postProcessMode?: GraphIndexPostProcessMode;
    embeddingStagePolicy?: GraphIndexEmbeddingStagePolicy;
    durabilityMode?: GraphBuildDurabilityMode;
    buildPolicy: GraphIndexPolicy;
    interactiveInputIdentity?: string;
    diagnosticBaseSnapshotId?: string;
    diagnosticBaseSnapshotRunSerial?: number;
    candidateCount?: number;
    calendarRegistrySnapshot?: CalendarRegistrySnapshot;
    replayManifest?: GraphRebuildReplayManifest;
}

type GraphRebuildBuildTimingNumberKey = {
    [Key in keyof GraphRebuildBuildTimings]-?: NonNullable<GraphRebuildBuildTimings[Key]> extends number ? Key : never;
}[keyof GraphRebuildBuildTimings];

@Injectable({ providedIn: 'root' })
export class GraphRebuildService {
    private readonly store = inject(PhoenixStoreService);
    private readonly phoenix = inject(PhoenixBackendService);
    private readonly snapshotState = signal<GraphRebuildSnapshot | null>(null);
    private readonly buildingState = signal(false);
    private readonly errorState = signal<string | null>(null);
    private readonly lastBuildTimingsState = signal<GraphRebuildBuildTimings | null>(null);
    private readonly nativeGraphRunPagingState = signal<NativeGraphRunPagingState | null>(null);
    private readonly absentOperatorMutationJournalScopes = new Set<string>();
    private readonly releasedNativeGraphRunLeases = new Set<string>();
    private readonly contentManifestByScope = new Map<string, GraphRebuildContentManifest>();
    private readonly documentSemanticSummaryByIdentity = new Map<string, GraphDocumentSemanticSummary>();
    private readonly documentSemanticArtifactHandleByIdentity = new Map<string, string>();
    private readonly persistedSnapshotLoads = new Map<string, Promise<GraphRebuildSnapshot | null>>();
    private readonly generationSnapshotContentLoads = new Map<string, Promise<GraphRebuildSnapshot>>();
    private readonly rejectedPersistedSnapshotScopes = new Map<string, string>();
    private readonly offlineCommunityReceiptState = signal<NativeOfflineCommunityReceipt | null>(null);
    private activeNativeGraphRun: { snapshotId: string; runHandle: string } | null = null;
    private nativeStoryContinuityHydration: {
        snapshotId: string;
        runHandle: string;
        promise: Promise<GraphStoryContinuityContract>;
    } | null = null;
    private nativeSiegelReceiptState: { snapshotId: string; receipt: unknown } | null = null;
    private primarySnapshotRunSerial = 0;

    readonly snapshot = computed(() => this.snapshotState());
    readonly isBuilding = computed(() => this.buildingState());
    readonly error = computed(() => this.errorState());
    readonly lastBuildTimings = computed(() => this.lastBuildTimingsState());
    readonly nativeGraphRunPaging = computed(() => this.nativeGraphRunPagingState());
    readonly offlineCommunityReceipt = computed(() => this.offlineCommunityReceiptState());

    currentSnapshotRunSerial(): number {
        return this.primarySnapshotRunSerial;
    }

    nativeGraphRunHandle(snapshotId = this.snapshotState()?.id): string | null {
        return snapshotId && this.activeNativeGraphRun?.snapshotId === snapshotId
            ? this.activeNativeGraphRun.runHandle
            : null;
    }

    async prepareAssertedQueryArtifact(
        snapshot: GraphRebuildSnapshot,
    ): Promise<GraphGenerationArtifactRef> {
        const authority = assertGraphSnapshotAuthority(snapshot);
        if (this.phoenix.target !== 'native') {
            throw new Error('Asserted query artifacts require the native mmap runtime.');
        }
        const response = await this.phoenix.storeCommand('graphGeneration:prepareAssertedQuery', {
            snapshot: graphRebuildSnapshotToNativeQueryPayload(snapshot),
            authorityHash: authority.contentHash,
        }) as NativeGraphGenerationQueryResponse | null;
        const manifest = response?.manifest;
        if (response?.schemaVersion !== 'phoenix-graph-generation-asserted-query/v1'
            || !manifest
            || manifest.sourceSnapshotId !== snapshot.id
            || !manifest.artifactDigest
            || !manifest.payloadDigest
            || manifest.admittedCandidateEdges !== 0) {
            throw new Error('Native asserted query artifact failed authority validation.');
        }
        const community = response.communityShadow;
        if (community) {
            const receipt = community.receipt;
            const gpuPath = receipt.executionPathId === 'community_gpu_wgpu_resident_v1';
            if (receipt.schemaVersion !== 'phoenix-offline-community-artifact-shadow/v1'
                || receipt.generation !== manifest.generation
                || receipt.sourceArtifactDigest !== manifest.artifactDigest
                || receipt.artifactDigest !== community.manifest.artifactDigest
                || receipt.payloadDigest !== community.manifest.payloadDigest
                || receipt.fallbackCount !== 0
                || receipt.productionPublished !== false
                || receipt.residentUploads !== (gpuPath ? 1 : 0)
                || (gpuPath && !receipt.adapter)
                || (!gpuPath && receipt.adapter !== null)) {
                throw new Error('Native offline community shadow receipt failed authority validation.');
            }
            this.offlineCommunityReceiptState.set(receipt);
        } else {
            this.offlineCommunityReceiptState.set(null);
        }
        return {
            schemaVersion: 'phoenix-graph-generation-artifact-ref/v1',
            kind: 'asserted-query',
            status: 'ready',
            id: `asserted-query:${snapshot.id}:${manifest.artifactDigest}`,
            digest: manifest.payloadDigest,
            schema: manifest.schemaVersion,
            byteLength: manifest.binaryBytes,
        };
    }

    residentNativeGraphRunHandle(): string | null {
        return this.activeNativeGraphRun?.runHandle || null;
    }

    async verifyForceV2Shadow(
        replay: GraphRebuildReplayManifest,
        snapshot: GraphRebuildSnapshot,
    ): Promise<GraphForceRebuildV2ShadowResult> {
        const request = buildGraphForceV2ShadowRequest(replay, snapshot);
        const result = await this.phoenix.forceRebuildV2Shadow(request) as GraphForceRebuildV2ShadowResult;
        return assertGraphForceV2ShadowResult(result, request);
    }

    async verifyForceV2(
        replay: GraphRebuildReplayManifest,
        snapshot: GraphRebuildSnapshot,
    ): Promise<GraphForceRebuildV2ShadowResult> {
        const shadowRequest = buildGraphForceV2ShadowRequest(replay, snapshot);
        const result = await this.phoenix.forceRebuildV2(
            buildGraphForceV2Request(replay, snapshot),
        ) as GraphForceRebuildV2ShadowResult;
        return assertGraphForceV2ShadowResult(result, shadowRequest);
    }

    async verifyForceV2FromAuthority(
        replay: GraphRebuildReplayManifest,
        authority: NonNullable<GraphIndexRunReceipt['verifiedForceAuthority']>,
    ): Promise<{ result: GraphForceRebuildV2ShadowResult; snapshot: GraphRebuildSnapshot }> {
        const shadowRequest = buildGraphForceV2ShadowRequestFromAuthority(replay, authority);
        const raw = await this.phoenix.forceRebuildV2(
            buildGraphForceV2RequestFromAuthority(replay, authority),
        ) as GraphForceRebuildV2ShadowResult;
        const result = assertGraphForceV2ShadowResult(raw, shadowRequest);
        const snapshot = result.authorityPacket;
        if (!snapshot) throw new Error('PHX_FORCE_V2_AUTHORITY_PACKET_MISSING: native packet is required.');
        assertGraphCanvasBootSnapshotShell(snapshot);
        const previousRun = this.activeNativeGraphRun;
        this.activeNativeGraphRun = { snapshotId: snapshot.id, runHandle: result.runHandle };
        this.nativeGraphRunPagingState.set(null);
        this.snapshotState.set(snapshot);
        if (previousRun && previousRun.runHandle !== result.runHandle) {
            void this.releaseNativeGraphRunLease(previousRun.runHandle);
        }
        return { result, snapshot };
    }

    async persistForceV2Authority(
        snapshot: GraphRebuildSnapshot,
        receipt: GraphGenerationReceiptV2,
    ): Promise<GraphForceAuthorityPersistReceipt> {
        const durable = snapshot.interactiveRunAuthority?.durable;
        const authorityHash = snapshot.authorityContract?.contentHash;
        if (!durable || !authorityHash || durable.snapshotId !== snapshot.id) {
            throw new Error('PHX_FORCE_V2_AUTHORITY_REQUIRED: sealed native durability is required.');
        }
        const authorityPacket = verifiedForceSnapshotShell(snapshot, receipt);
        const result = await this.phoenix.persistForceV2Authority({
            scopeId: snapshot.scopeId,
            snapshotId: snapshot.id,
            authorityHash,
            manifestId: durable.manifestId,
            authorityPacket,
        }) as GraphForceAuthorityPersistReceipt;
        if (result.schemaVersion !== 'phoenix-force-v2-authority-persist/v1'
            || !result.artifactId || result.rawBytes <= 0 || result.rawBytes > 256 * 1024
            || !Number.isFinite(result.serializerMicros)
            || !Number.isFinite(result.atomicPersistMicros)) {
            throw new Error('PHX_FORCE_V2_AUTHORITY_PERSIST_INVALID: native authority receipt failed validation.');
        }
        return result;
    }

    nativeSiegelReceipt(snapshotId: string): unknown {
        return this.nativeSiegelReceiptState?.snapshotId === snapshotId
            ? this.nativeSiegelReceiptState.receipt
            : undefined;
    }

    async persistResidentNativeGraphRun(
        snapshot: GraphRebuildSnapshot,
    ): Promise<NativeGraphRunPersistReceipt | null> {
        const current = this.snapshotState();
        const runHandle = this.nativeGraphRunHandle(snapshot.id);
        if (!current || !runHandle
            || current.id !== snapshot.id
            || current.scopeId !== snapshot.scopeId
            || current.authorityContract?.contentHash !== snapshot.authorityContract?.contentHash) {
            return null;
        }
        const durable = await this.phoenix.persistGraphRun(runHandle) as NativeGraphRunPersistReceipt;
        this.assertNativeGraphRunPersistReceipt(durable, snapshot, runHandle);
        return durable;
    }

    async restorePersistedNativeGraphRun(
        snapshot: GraphRebuildSnapshot,
        inputIdentity: string,
    ): Promise<NativeGraphRunPersistReceipt | null> {
        const authority = snapshot.interactiveRunAuthority;
        if (!authority || authority.inputIdentity !== inputIdentity) return null;
        if (authority.snapshotId !== snapshot.id || authority.scopeId !== snapshot.scopeId
            || authority.durable.snapshotId !== snapshot.id
            || authority.durable.scopeId !== snapshot.scopeId) {
            throw new Error('Persisted interactive graph-run authority receipt does not match its snapshot.');
        }
        const page = await this.readNativeGraphRunPageForHandle(authority.durable.runHandle, 0, 1);
        if (page.projection.continuity.contract.sourceSnapshotId !== snapshot.id) {
            throw new Error('Durable native graph run does not match the persisted authoritative snapshot.');
        }
        this.activeNativeGraphRun = { snapshotId: snapshot.id, runHandle: page.runHandle };
        this.nativeGraphRunPagingState.set({
            snapshotId: snapshot.id,
            runHandle: page.runHandle,
            totalRows: page.detailRows,
            loadedRows: page.returnedDetailRows,
            nextOffset: page.nextOffset ?? null,
            counts: page.counts,
        });
        const sectionCount = authority.durable.changedSections + authority.durable.reusedSections;
        return {
            ...authority.durable,
            changedSections: 0,
            reusedSections: sectionCount,
            encodedSections: 0,
            compressedSections: 0,
            rawBytesWritten: 0,
            compressedBytesWritten: 0,
        };
    }

    async readNativeGraphRunPage(
        offset: number,
        limit = 32,
        section: PhoenixGraphRunPageSection = 'all',
    ): Promise<NativeGraphRunPage | null> {
        const active = this.activeNativeGraphRun;
        if (!active) return null;
        return this.readNativeGraphRunPageForHandle(active.runHandle, offset, limit, section);
    }

    async readNativeGraphRunPageForHandle(
        runHandle: string,
        offset: number,
        limit = 32,
        section: PhoenixGraphRunPageSection = 'all',
    ): Promise<NativeGraphRunPage> {
        const page = await this.phoenix.readGraphRunPage({
            runHandle,
            offset,
            limit,
            section,
        }) as NativeGraphRunPage | null;
        if (!isNativeGraphRunPage(page)) {
            throw new Error('Rust graph run page returned an invalid v1 payload.');
        }
        if (page.runHandle !== runHandle) {
            throw new Error('Rust graph run page returned a stale lease.');
        }
        if ((page.section ?? 'all') !== section) {
            throw new Error(`Rust graph run page returned the wrong section: ${page.section ?? 'all'}.`);
        }
        return page;
    }

    async hydrateNativeStoryContinuity(): Promise<GraphStoryContinuityContract | null> {
        const snapshot = this.snapshotState();
        if (!snapshot) return null;
        const existing = snapshot.storyContinuity;
        if (existing && isCompleteStoryContinuityContract(existing)) return existing;
        const active = this.activeNativeGraphRun;
        if (!active || active.snapshotId !== snapshot.id) {
            throw new Error('Complete native story continuity requires the resident graph run.');
        }
        if (this.nativeStoryContinuityHydration?.snapshotId === snapshot.id
            && this.nativeStoryContinuityHydration.runHandle === active.runHandle) {
            return this.nativeStoryContinuityHydration.promise;
        }
        const promise = this.hydrateNativeStoryContinuityFromRun(snapshot, active.runHandle);
        this.nativeStoryContinuityHydration = {
            snapshotId: snapshot.id,
            runHandle: active.runHandle,
            promise,
        };
        try {
            return await promise;
        } finally {
            if (this.nativeStoryContinuityHydration?.promise === promise) {
                this.nativeStoryContinuityHydration = null;
            }
        }
    }

    private async hydrateNativeStoryContinuityFromRun(
        sourceSnapshot: GraphRebuildSnapshot,
        runHandle: string,
    ): Promise<GraphStoryContinuityContract> {
        const contract = await this.readCompleteNativeStoryContinuity(sourceSnapshot, runHandle);

        const current = this.snapshotState();
        const active = this.activeNativeGraphRun;
        if (!current || current.id !== sourceSnapshot.id || current.scopeId !== sourceSnapshot.scopeId
            || current.authorityContract?.contentHash !== sourceSnapshot.authorityContract?.contentHash
            || active?.runHandle !== runHandle || active.snapshotId !== sourceSnapshot.id) {
            throw new Error('Graph snapshot changed while native story continuity was paging.');
        }
        const hydrated: GraphRebuildSnapshot = {
            ...current,
            counters: { ...current.counters },
        };
        applyNativeStoryContinuityContract(hydrated, contract);
        await this.persistSnapshot(hydrated, undefined, false, {
            durabilityMode: 'interactive',
            previousContentManifest: current.contentManifest,
        });
        this.snapshotState.set(hydrated);
        dispatchGraphRebuildEvent('graph-rebuild-snapshot-updated', {
            scopeId: hydrated.scopeId,
            snapshotId: hydrated.id,
        });
        return contract;
    }

    private async readCompleteNativeStoryContinuity(
        sourceSnapshot: GraphRebuildSnapshot,
        runHandle: string,
    ): Promise<GraphStoryContinuityContract> {
        const rows: StoryContinuityRows = {
            events: [],
            boundaryReceipts: [],
            episodes: [],
            temporalCandidates: [],
            stateIntervals: [],
            causalCandidates: [],
            episodeConnections: [],
            conflicts: [],
        };
        const rowIds = new Set<string>();
        let offset = 0;
        let contractHeader: GraphStoryContinuityContract | null = null;
        let expectedDetailRows: number | null = null;
        do {
            const page = await this.readNativeGraphRunPageForHandle(
                runHandle,
                offset,
                512,
                'storyContinuity',
            );
            if (page.offset !== offset || page.section !== 'storyContinuity') {
                throw new Error('Native story continuity paging returned a stale cursor or section.');
            }
            const contract = page.projection.continuity.contract;
            if (contract.sourceSnapshotId !== sourceSnapshot.id) {
                throw new Error('Native story continuity paging returned a stale snapshot.');
            }
            if (!contractHeader) {
                contractHeader = contract;
                expectedDetailRows = page.detailRows;
            } else if (!sameStoryContinuityHeader(contractHeader, contract)
                || page.detailRows !== expectedDetailRows) {
                throw new Error('Native story continuity metadata changed during paging.');
            }
            appendUniqueStoryContinuityRows(rows, contract, rowIds);
            const nextOffset = page.nextOffset ?? null;
            if (nextOffset !== null && nextOffset <= offset) {
                throw new Error('Native story continuity paging did not advance.');
            }
            offset = nextOffset ?? -1;
        } while (offset >= 0);
        if (!contractHeader || expectedDetailRows === null) {
            throw new Error('Native story continuity paging returned no contract.');
        }
        const contract: GraphStoryContinuityContract = {
            ...contractHeader,
            ...rows,
            actionReceipts: sourceSnapshot.storyContinuity?.actionReceipts,
            certificate: {
                ...contractHeader.certificate,
                counters: { ...contractHeader.certificate.counters },
            },
        };
        assertCompleteStoryContinuityContract(contract, expectedDetailRows);
        return contract;
    }

    async closeNativeGraphRun(): Promise<boolean> {
        const active = this.activeNativeGraphRun;
        this.activeNativeGraphRun = null;
        return active ? this.releaseNativeGraphRunLease(active.runHandle) : false;
    }

    async releaseNativeGraphRunLease(runHandle: string): Promise<boolean> {
        if (this.releasedNativeGraphRunLeases.has(runHandle)) return false;
        this.releasedNativeGraphRunLeases.add(runHandle);
        return this.phoenix.closeGraphRun(runHandle);
    }

    attachReviewAdjudicationCertificate(certificate: GraphReviewAdjudicationRunCertificate): void {
        const current = this.snapshotState();
        if (!current) return;
        if (certificate.document.snapshotId && certificate.document.snapshotId !== current.id) return;
        const next: GraphRebuildSnapshot = {
            ...current,
            counters: { ...current.counters },
            reviewAdjudicationCertificate: certificate,
        };
        applyReviewAdjudicationCertificate(next, certificate);
        this.snapshotState.set(next);
    }

    async buildAndPersistSnapshot(request: GraphRebuildBuildRequest): Promise<GraphRebuildSnapshot> {
        const durabilityMode = request.durabilityMode || 'durable';
        this.assertBuildPolicyAuthorized(request.scopeId, request.buildPolicy);
        if (request.buildPolicy !== 'force') {
            throw new Error(
                'Snapshot reconstruction requires explicit Force Rebuild. '
                + 'Delta is authority-reuse only and cannot enter the snapshot builder.',
            );
        }
        const commitsPrimarySnapshot = durabilityMode !== 'diagnostic';
        if (commitsPrimarySnapshot) this.buildingState.set(true);
        const totalStarted = performance.now();
        const builtAt = Date.now();
        const timings = emptyBuildTimings();
        const currentSnapshot = this.snapshotState();
        const previousContentManifest = request.previousContentManifest
            || (currentSnapshot?.scopeId === request.scopeId ? currentSnapshot.contentManifest : undefined)
            || this.contentManifestByScope.get(request.scopeId);
        try {
            const persistedOccurrences = await timedAsync(timings, 'occurrenceLoadMs', () =>
                this.loadOccurrences(request.noteIds, request.entities)
            );
            const noteTexts = request.noteTexts || await timedAsync(timings, 'noteTextLoadMs', () =>
                this.loadNoteTexts(request.noteIds, persistedOccurrences)
            );
            if (request.noteTexts) timings.noteTextLoadMs = 0;
            const chunks = request.chunks || await timedAsync(timings, 'chunkLoadMs', () =>
                this.loadChunks(request.noteIds, persistedOccurrences, noteTexts, durabilityMode)
            );
            if (request.chunks) timings.chunkLoadMs = 0;
            if (durabilityMode === 'interactive') timings.nativeChunkerSkipped = 1;
            const noteFolders = request.noteFolders || (durabilityMode === 'interactive'
                ? {}
                : await timedAsync(timings, 'noteFolderLoadMs', () =>
                    this.loadNoteFolderContexts(request.noteIds, persistedOccurrences)
                ));
            if (request.noteFolders || durabilityMode === 'interactive') timings.noteFolderLoadMs = 0;
            const documentProfileSummary = durabilityMode === 'interactive'
                ? undefined
                : await timedAsync(timings, 'documentProfileMs', () =>
                    this.classifyDocumentProfiles(noteTexts, builtAt)
                );
            if (durabilityMode === 'interactive') timings.documentProfileMs = 0;
            const documentSemanticIdentity = graphDocumentSemanticIdentity(noteTexts, request.entities);
            let documentSemanticSummary = this.documentSemanticSummaryByIdentity.get(documentSemanticIdentity);
            if (documentSemanticSummary) {
                timings.documentSemanticMs = 0;
                timings.documentSemanticCacheHit = 1;
            } else {
                documentSemanticSummary = await timedAsync(timings, 'documentSemanticMs', () =>
                    this.buildDocumentSemanticSummary(
                        noteTexts,
                        request.entities,
                        timings,
                        documentSemanticIdentity,
                    )
                );
                if (documentSemanticSummary) {
                    this.documentSemanticSummaryByIdentity.set(documentSemanticIdentity, documentSemanticSummary);
                    trimOldestMapEntries(this.documentSemanticSummaryByIdentity, 8);
                } else {
                    timings.documentSemanticSkipped = 1;
                }
            }
            const operatorMutationJournal = await this.loadOperatorMutationJournal(request.scopeId, {
                allowSnapshotFallback: durabilityMode !== 'interactive',
            });
            const recoverStarted = performance.now();
            const recoveredOccurrences = recoverGraphRebuildOccurrences(noteTexts, request.entities);
            const hasCurrentSourceEvidence = persistedOccurrences.length > 0
                || recoveredOccurrences.length > 0
                || !!request.sourceEvidence?.stagedOccurrences?.length
                || !!request.sourceEvidence?.cachedSnapshotOccurrences?.length;
            let previousSnapshot: GraphRebuildSnapshot | null = null;
            if (durabilityMode === 'interactive' && hasCurrentSourceEvidence) {
                timings.previousSnapshotHydrationSkipped = 1;
            } else {
                previousSnapshot = await this.loadPersistedSnapshot(request.scopeId);
                timings.previousSnapshotHydrationSkipped = 0;
            }
            const priorSnapshotOccurrences = snapshotAnchorsToGraphRebuildOccurrences(
                previousSnapshot,
                builtAt,
                noteTexts,
            );
            const cachedSnapshotOccurrences = mergeOccurrenceEvidence(
                request.sourceEvidence?.cachedSnapshotOccurrences || [],
                priorSnapshotOccurrences,
            );
            const sourceEvidence = buildGraphSnapshotSourceEvidence({
                ...request.sourceEvidence,
                persistedOccurrences,
                cachedSnapshotOccurrences,
                recoveredOccurrences,
            });
            const occurrences = sourceEvidence.allOccurrences;
            timings.occurrenceRecoverMs = elapsedMs(recoverStarted);
            const cpuProfiler = new GraphRebuildCpuProfiler();
            let snapshot = timedSync(timings, 'snapshotBuildMs', () => buildGraphRebuildSnapshot({
                scopeKind: request.scopeKind,
                scopeId: request.scopeId,
                noteIds: request.noteIds,
                entities: request.entities,
                occurrences,
                chunks,
                noteFolders,
                noteTexts,
                relationshipHints: request.relationshipHints,
                embeddingProfile: request.embeddingProfile,
                postProcessMode: request.postProcessMode,
                embeddingStagePolicy: request.embeddingStagePolicy,
                candidateCount: request.candidateCount,
                calendarRegistrySnapshot: request.calendarRegistrySnapshot,
                documentProfileSummary,
                documentSemanticSummary,
                operatorMutationJournal: operatorMutationJournal || undefined,
                durabilityMode,
                cpuProfiler,
                builtAt,
            }));
            snapshot.documentSemanticArtifactHandle = this.documentSemanticArtifactHandleByIdentity
                .get(documentSemanticIdentity);
            Object.assign(timings, cpuProfiler.timings);
            recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'source_evidence', {
                notes: request.noteIds.length,
                registryEntities: request.entities.length,
                persistedOccurrences: sourceEvidence.counters.persisted,
                stagedOccurrences: sourceEvidence.counters.staged,
                cachedSnapshotOccurrences: sourceEvidence.counters.cachedSnapshot,
                previousAcceptedAnchors: previousSnapshot?.entityAnchors.length || 0,
                validatedPriorOccurrences: priorSnapshotOccurrences.length,
                recoveredOccurrences: sourceEvidence.counters.recovered,
                totalOccurrences: sourceEvidence.counters.total,
            });
            recordGraphCollapseSnapshotBoundary(snapshot, 'typescript_snapshot');
            snapshot = await this.reconcileDocumentGraphMutations(snapshot, durabilityMode === 'interactive');
            await this.attachNativeSnapshotAnalysis(
                snapshot,
                noteTexts,
                timings,
                durabilityMode,
            );
            const packetConstructionStarted = performance.now();
            const interactivePacketAttached = durabilityMode === 'interactive'
                && attachInteractiveAtlasPacketForSnapshotTargets(
                    snapshot,
                    currentSnapshot?.scopeId === snapshot.scopeId ? currentSnapshot : previousSnapshot,
                );
            if (interactivePacketAttached) {
                timings.nativeCompilerSkipped = 1;
                timings.nativeCompilerInputBytesByFamily = {};
                timings.nativeTargetsByOriginatingFamily = {
                    interactivePacket: snapshot.embeddingTargets.length,
                };
                recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'native_response', {
                    nativeResponseAvailable: 0,
                    nativeCompilerSkipped: 1,
                    packetObjects: snapshot.atlasPacket?.objects.length || 0,
                    packetTargets: snapshot.atlasPacket?.manifoldTargets.length || 0,
                });
            } else {
                await this.attachNativeGraphCompilerSidecar(snapshot, timings, request);
            }
            timings.packetConstructionMs = elapsedMs(packetConstructionStarted);
            const authoritySealStarted = performance.now();
            finalizeGraphRebuildSnapshot({
                snapshot,
                sourceEvidence,
                previousSnapshot,
                hasNonemptySourceText: Object.values(noteTexts).some((text) => text.trim().length > 0),
            });
            if (durabilityMode === 'interactive') {
                await this.persistNativeGraphRunForVerifiedForce(
                    snapshot,
                    timings,
                    request.interactiveInputIdentity,
                    request.replayManifest,
                );
            }
            const primaryNoOpSnapshot = currentSnapshot?.scopeId === snapshot.scopeId
                ? currentSnapshot
                : previousSnapshot;
            const skipPrimarySnapshotWrite = durabilityMode === 'interactive'
                && reuseInteractivePrimarySnapshotIdentity(snapshot, primaryNoOpSnapshot);
            timings.snapshotPrimaryIdentityReused = skipPrimarySnapshotWrite ? 1 : 0;
            timings.authoritySealMs = elapsedMs(authoritySealStarted);
            finalizeBuildTimings(timings, totalStarted);
            snapshot.buildTimings = timings;
            const diagnosticStillCurrent = durabilityMode !== 'diagnostic'
                || (request.diagnosticBaseSnapshotRunSerial !== undefined
                    ? this.primarySnapshotRunSerial === request.diagnosticBaseSnapshotRunSerial
                    : !request.diagnosticBaseSnapshotId
                        || this.snapshotState()?.id === request.diagnosticBaseSnapshotId);
            const stateStarted = performance.now();
            if (commitsPrimarySnapshot) {
                this.primarySnapshotRunSerial += 1;
                this.snapshotState.set(snapshot);
            }
            timings.stateCommitMs = elapsedMs(stateStarted);
            if (!diagnosticStillCurrent) {
                finalizeBuildTimings(timings, totalStarted);
                snapshot.buildTimings = timings;
                return snapshot;
            }
            const persistStarted = performance.now();
            await this.persistSnapshot(snapshot, timings, false, {
                durabilityMode,
                previousContentManifest: previousContentManifest
                    || previousSnapshot?.contentManifest,
                skipPrimarySnapshotWrite,
            }).then(() => {
                if (commitsPrimarySnapshot) {
                    this.errorState.set(null);
                    this.rejectedPersistedSnapshotScopes.delete(request.scopeId);
                }
            }).catch((error) => {
                const message = error instanceof Error ? error.message : String(error);
                if (commitsPrimarySnapshot) {
                    this.errorState.set(`Overgraph graph-rebuild snapshot persist failed: ${message}`);
                }
                console.warn('[GraphRebuild] Snapshot persist failed', error);
            }).finally(() => {
                timings.snapshotPersistMs = elapsedMs(persistStarted);
            });
            finalizeBuildTimings(timings, totalStarted);
            snapshot.buildTimings = timings;
            if (commitsPrimarySnapshot) this.lastBuildTimingsState.set(timings);
            return snapshot;
        } finally {
            if (commitsPrimarySnapshot) this.buildingState.set(false);
        }
    }

    private async attachNativeSnapshotAnalysis(
        snapshot: GraphRebuildSnapshot,
        noteTexts: Record<string, string>,
        timings: GraphRebuildBuildTimings,
        durabilityMode: GraphBuildDurabilityMode,
    ): Promise<void> {
        const started = performance.now();
        if (this.phoenix.target !== 'native') {
            applyNativeChunkSemanticBridgeCandidates(snapshot, []);
            applyNativeMemoryGovernanceCandidates(snapshot, []);
            applyNativePromotionVerdictCertificate(snapshot, null, timings);
            timings.nativeChunkSemanticBridgeSkipped = 1;
            timings.nativeStoryContinuitySkipped = 1;
            timings.nativeMemoryGovernanceSkipped = 1;
            timings.nativeMemoryGovernanceRetrievalExperimentSkipped = 1;
            timings.nativePromotionVerdictSkipped = 1;
            timings.nativeSnapshotAnalysisMs = elapsedMs(started);
            return;
        }

        const retrievalCandidates = memoryGovernanceRetrievalCandidatesFromSnapshot(snapshot);
        const page = await this.phoenix.analyzeGraphSnapshot({
            snapshot: graphRebuildSnapshotToNativeAnalysisPayload(snapshot),
            documents: snapshot.noteIds.map((noteId) => ({ noteId, text: noteTexts[noteId] || '' })),
            documentSemanticHandle: snapshot.documentSemanticArtifactHandle,
            documentSemanticSummary: snapshot.documentSemanticArtifactHandle
                ? undefined
                : snapshot.documentSemanticSummary,
            retrievalCandidates,
            receipts: buildGraphPromotionPreviewReceipts(snapshot),
            commits: [],
            siegel: graphRebuildSiegelNativeRequest(snapshot),
        }) as NativeGraphRunPage | null;
        if (!isNativeGraphRunPage(page)) {
            throw new Error('Rust graph run analysis returned an invalid v1 page.');
        }
        if (durabilityMode === 'interactive') {
            const previousRun = this.activeNativeGraphRun;
            this.activeNativeGraphRun = { snapshotId: snapshot.id, runHandle: page.runHandle };
            if (previousRun && previousRun.runHandle !== page.runHandle) {
                void this.releaseNativeGraphRunLease(previousRun.runHandle);
            }
            this.nativeGraphRunPagingState.set({
                snapshotId: snapshot.id,
                runHandle: page.runHandle,
                totalRows: page.detailRows,
                loadedRows: page.returnedDetailRows,
                nextOffset: page.nextOffset ?? null,
                counts: page.counts,
            });
        }
        const native = page.projection;
        if (native.siegel) {
            this.nativeSiegelReceiptState = { snapshotId: snapshot.id, receipt: native.siegel };
        }

        applyNativeChunkSemanticBridgeCandidates(
            snapshot,
            native.bridge.candidates,
            native.bridge.crossDocumentCertificate,
        );
        applyNativeStoryContinuityContract(snapshot, native.continuity.contract);
        if (!isCompleteStoryContinuityContract(native.continuity.contract)) {
            const continuity = await this.readCompleteNativeStoryContinuity(snapshot, page.runHandle);
            applyNativeStoryContinuityContract(snapshot, continuity);
        }
        applyNativeMemoryGovernanceCandidates(snapshot, native.governance.candidates);
        if (native.retrieval) {
            applyNativeMemoryGovernanceRetrievalExperiment(snapshot, native.retrieval.experiment);
        }
        applyNativePromotionVerdictCertificate(snapshot, native.promotion.certificate, timings);

        snapshot.counters = {
            ...snapshot.counters,
            chunkSemanticBridges: page.counts.bridgeCandidates,
            chunkSetupPayoffBridges: page.counts.bridgeByType['setup_payoff'] || 0,
            chunkCauseEffectBridges: page.counts.bridgeByType['cause_effect'] || 0,
            chunkStateDeltaBridges: page.counts.bridgeByType['state_delta'] || 0,
            chunkRelationshipDeltaBridges: page.counts.bridgeByType['relationship_delta'] || 0,
            chunkTopicContinuationBridges: page.counts.bridgeByType['topic_continuation'] || 0,
            chunkEvidenceReframeBridges: page.counts.bridgeByType['evidence_reframe'] || 0,
            chunkMotifEchoBridges: page.counts.bridgeByType['motif_echo'] || 0,
            chunkRouteContinuityBridges: page.counts.bridgeByType['route_continuity'] || 0,
            memoryGovernanceCandidates: page.counts.governanceCandidates,
            memoryGovernanceRetain: page.counts.governanceByAction['retain'] || 0,
            memoryGovernanceAttenuate: page.counts.governanceByAction['attenuate'] || 0,
            memoryGovernanceCompress: page.counts.governanceByAction['compress'] || 0,
            memoryGovernanceQuarantine: page.counts.governanceByAction['quarantine'] || 0,
            memoryGovernanceRetire: page.counts.governanceByAction['retire'] || 0,
        };

        const continuityCounters = native.continuity.contract.certificate.counters;
        snapshot.counters = {
            ...snapshot.counters,
            continuityEvents: continuityCounters.events,
            continuityBoundaryReceipts: continuityCounters.boundaryReceipts,
            continuityEpisodes: continuityCounters.episodes,
            continuityTemporalCandidates: continuityCounters.temporalCandidates,
            continuityCausalCandidates: continuityCounters.causalCandidates,
            continuityStateIntervals: continuityCounters.stateIntervals,
            continuityEpisodeConnections: continuityCounters.episodeConnections,
            continuityConflicts: continuityCounters.conflicts,
            continuityCrossDocumentConnections: continuityCounters.crossDocumentConnections,
            continuityReviewRequired: continuityCounters.reviewRequired,
        };
        timings.nativeSnapshotAnalysisMs = elapsedMs(started);
        timings.nativeSnapshotAnalysisRustMicros = page.analysisKernelMicros;
        timings.nativeSnapshotAnalysisSource = page.analysisSource;
        timings.nativeGraphRunArenaReused = page.arena.reused ? 1 : 0;
        timings.nativeGraphRunArenaResidentBytes = page.arena.residentBytes;
        timings.nativeGraphRunArenaActiveLeases = page.arena.activeLeases;
        timings.nativeGraphRunPageProjectionMicros = page.arena.projectionMicros;
        timings.nativeGraphRunDetailRows = page.detailRows;
        timings.nativeGraphRunReturnedDetailRows = page.returnedDetailRows;
        timings.nativeChunkSemanticBridgeMs = timings.nativeSnapshotAnalysisMs;
        timings.nativeChunkSemanticBridgeCandidates = page.counts.bridgeCandidates;
        timings.nativeChunkSemanticBridgeQualityDemotions =
            native.bridge.qualityGate.demotedSameEntityOnly;
        timings.nativeChunkSemanticBridgeRustMicros = native.timing.bridgeBuildMicros;
        timings.nativeStoryContinuityRows = continuityCounters.events
            + continuityCounters.boundaryReceipts
            + continuityCounters.episodes
            + continuityCounters.temporalCandidates
            + continuityCounters.stateIntervals
            + continuityCounters.causalCandidates
            + continuityCounters.episodeConnections
            + continuityCounters.conflicts;
        timings.nativeStoryContinuityRustMicros = native.timing.continuityBuildMicros;
        timings.nativeMemoryGovernanceCandidates = page.counts.governanceCandidates;
        timings.nativeMemoryGovernanceRustMicros = native.timing.governanceBuildMicros;
        timings.nativeMemoryGovernanceRetrievalExperimentCandidates = retrievalCandidates.length;
        timings.nativeMemoryGovernanceRetrievalExperimentRustMicros = native.timing.retrievalBuildMicros;
        timings.nativePromotionVerdictRows = native.promotion.certificate.audit.total;
        timings.nativePromotionVerdictRustMicros = native.timing.verdictBuildMicros;
        if (durabilityMode !== 'interactive') {
            void this.phoenix.closeGraphRun(page.runHandle);
        }
    }

    private async persistNativeGraphRunForVerifiedForce(
        snapshot: GraphRebuildSnapshot,
        timings: GraphRebuildBuildTimings,
        interactiveInputIdentity?: string,
        replay?: GraphRebuildReplayManifest,
    ): Promise<void> {
        const runHandle = this.nativeGraphRunHandle(snapshot.id);
        if (!runHandle) throw new Error('Native graph run was not retained through authority sealing.');
        const persistStarted = performance.now();
        const durable = await this.phoenix.persistGraphRun(runHandle, {
            authorityHash: snapshot.authorityContract?.contentHash || '',
            forceReplayBinding: replay ? {
                schemaVersion: 'phoenix-verified-force/v2',
                cohortId: replay.cohortId,
                sourceMode: replay.sourceMode,
                dependencyIdentity: replay.dependencyIdentity,
                documentSha256: Object.fromEntries(replay.documents.map((row) => [row.noteId, row.sha256])),
                documents: replay.documents.map((row) => ({
                    noteId: row.noteId,
                    sha256: row.sha256,
                    jsCodeUnitChars: row.jsCodeUnitChars,
                    utf8Bytes: row.utf8Bytes,
                    version: row.version,
                    updatedAt: row.updatedAt,
                })),
                dynamicNerId: replay.model.dynamicNerId,
                embeddingModelId: replay.model.embeddingModelId,
                embeddingDimension: replay.model.embeddingDimensionLabel,
                nliModelId: replay.model.nliModelId,
            } : undefined,
        }) as NativeGraphRunPersistReceipt;
        this.assertNativeGraphRunPersistReceipt(durable, snapshot, runHandle);
        if (interactiveInputIdentity) {
            snapshot.interactiveRunAuthority = {
                schemaVersion: 'phoenix-interactive-graph-run-authority/v1',
                inputIdentity: interactiveInputIdentity,
                snapshotId: snapshot.id,
                scopeId: snapshot.scopeId,
                durable,
            };
        }
        timings.nativeGraphRunPersistMs = elapsedMs(persistStarted);
        timings.nativeGraphRunChangedSections = durable.changedSections;
        timings.nativeGraphRunReusedSections = durable.reusedSections;
        timings.nativeGraphRunEncodedSections = durable.encodedSections;
        timings.nativeGraphRunCompressedSections = durable.compressedSections;
        timings.nativeGraphRunRawBytesWritten = durable.rawBytesWritten;
        timings.nativeGraphRunCompressedBytesWritten = durable.compressedBytesWritten;
    }

    private assertNativeGraphRunPersistReceipt(
        durable: NativeGraphRunPersistReceipt,
        snapshot: GraphRebuildSnapshot,
        runHandle: string,
    ): void {
        if (durable.schemaVersion !== 'phoenix-graph-run-durable-receipt/v1'
            || durable.runHandle !== runHandle
            || durable.snapshotId !== snapshot.id
            || durable.scopeId !== snapshot.scopeId) {
            throw new Error('Rust graph run persistence returned a mismatched durable receipt.');
        }
    }

    private async attachNativeGraphCompilerSidecar(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
        request?: Pick<GraphRebuildBuildRequest, 'embeddingStagePolicy' | 'postProcessMode'>,
    ): Promise<void> {
        const started = performance.now();
        try {
            const compilerPayload = graphRebuildSnapshotToNativeCompilerPayload(snapshot);
            if (timings) {
                timings.nativeCompilerInputBytesByFamily = graphRebuildNativeCompilerInputBytes(compilerPayload);
            }
            const rawSidecar = await this.phoenix.storeCommand('graphRebuild:compileDualWrite', {
                snapshot: compilerPayload,
            }) as NativeGraphCompilerSidecar | null;
            const sidecar = decodeNativeGraphCompilerSidecar(rawSidecar);
            if (timings && rawSidecar?.atlasSeedPayload) {
                timings.nativeAtlasSeedRawBytes = rawSidecar.atlasSeedPayload.rawBytes;
                timings.nativeAtlasSeedCompressedBytes = rawSidecar.atlasSeedPayload.compressedBytes;
            }
            if (timings && sidecar?.originatingFamilies) {
                timings.nativeTargetsByOriginatingFamily = Object.fromEntries(
                    sidecar.originatingFamilies.map((row) => [row.family, row.targets]),
                );
            }
            recordGraphCollapseNativeBoundary(snapshot, sidecar);
            if (sidecar?.atlasPacket) snapshot.atlasPacket = sidecar.atlasPacket;
            if (sidecar?.embeddingTargets?.length) {
                const nativeTargets = filterNativeEmbeddingTargetsForCommittedSources(snapshot, sidecar.embeddingTargets);
                recordGraphCollapseFilteredTargets(snapshot, sidecar.embeddingTargets, nativeTargets);
                if (nativeTargets.length) {
                    this.applyNativeEmbeddingTargets(
                        snapshot,
                        mergeNativeEmbeddingTargets(snapshot.embeddingTargets, nativeTargets),
                        request,
                    );
                }
            } else {
                recordGraphCollapseFilteredTargets(snapshot, [], []);
            }
            if (snapshot.atlasPacket) {
                snapshot.atlasPacket = reconcileNativeAtlasPacketForTargets(snapshot, snapshot.atlasPacket);
            }
            if (!sidecar?.factGraph) return;
            attachGraphCompilerReadModels(snapshot, sidecar, 'rust');
        } catch (error) {
            recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'native_response', {
                nativeResponseAvailable: 0,
                nativeError: 1,
            });
            console.warn('[GraphRebuild] Native graph compiler sidecar unavailable; using compatibility sidecar', error);
        } finally {
            if (timings) timings.nativeCompilerMs = elapsedMs(started);
        }
    }

    private applyNativeEmbeddingTargets(
        snapshot: GraphRebuildSnapshot,
        nativeTargets: GraphRebuildEmbeddingTarget[],
        request?: Pick<GraphRebuildBuildRequest, 'embeddingStagePolicy' | 'postProcessMode'>,
    ): void {
        const plan = selectGraphRebuildEmbeddingTargetPlan(
            nativeTargets,
            snapshot.relationships,
            snapshot.temporalEdges,
            snapshot.causalEdges,
            request?.embeddingStagePolicy,
        );
        snapshot.embeddingTargets = plan.targets;
        snapshot.embeddingTargetPlan = plan;
        const queuedTargetIds = new Set(plan.queuedTargetIds || []);
        const workTargets = snapshot.embeddingTargets.filter((target) =>
            queuedTargetIds.size ? queuedTargetIds.has(target.id) : target.admissionStatus === 'admitted',
        );
        const postProcessMode = request?.postProcessMode || (snapshot.embeddingGraphPostProcess ? 'full' : 'core');
        snapshot.embeddingGraphPostProcess = postProcessMode === 'full'
            ? buildGraphRebuildEmbeddingGraphPostProcess(workTargets, snapshot.embeddingProfile)
            : undefined;
        if (snapshot.embeddingGraphPostProcess) {
            snapshot.embeddingProfile = snapshot.embeddingGraphPostProcess.profile;
            snapshot.embeddingModelAdapter = snapshot.embeddingGraphPostProcess.adapter;
        }
        updateEmbeddingTargetCounters(snapshot, plan, workTargets.length);
        refreshTargetDerivedReadModels(snapshot);
    }

    private async classifyDocumentProfiles(
        noteTexts: Record<string, string>,
        builtAt: number,
    ): Promise<GraphDocumentProfileSummary> {
        if (this.phoenix.target !== 'native') {
            return buildFallbackDocumentProfileSummary(noteTexts, builtAt);
        }
        try {
            const native = await this.phoenix.storeCommand('documentProfile:classify', {
                builtAt,
                documents: Object.entries(noteTexts).map(([noteId, text]) => ({ noteId, text })),
            });
            return normalizeDocumentProfileSummary(native)
                || buildFallbackDocumentProfileSummary(noteTexts, builtAt);
        } catch (error) {
            console.warn('[GraphRebuild] Native document profile unavailable; using compatibility classifier', error);
            return buildFallbackDocumentProfileSummary(noteTexts, builtAt);
        }
    }

    private async buildDocumentSemanticSummary(
        noteTexts: Record<string, string>,
        entities: RegisteredEntity[],
        timings: GraphRebuildBuildTimings,
        semanticIdentity: string,
    ): Promise<GraphDocumentSemanticSummary | undefined> {
        if (this.phoenix.target !== 'native') return undefined;
        try {
            const native = await this.phoenix.storeCommand('documentSemantic:build', {
                documents: Object.entries(noteTexts).map(([noteId, text]) => ({ noteId, text })),
                entities: entities.map((entity) => ({
                    id: entity.id,
                    label: entity.label,
                    aliases: entity.aliases || [],
                    kind: entity.kind,
                })),
            });
            if (isCompressedDocumentSemanticPayload(native)) {
                const stats = native.artifactStats;
                timings.documentSemanticDocumentsBuilt = Number(stats?.documentsBuilt || 0);
                timings.documentSemanticDocumentsReused = Number(stats?.documentsReused || 0);
                timings.documentSemanticRawBytesWritten = Number(stats?.rawBytesWritten || 0);
                timings.documentSemanticCompressedBytesWritten = Number(stats?.compressedBytesWritten || 0);
                if (stats?.summaryCacheHit) timings.documentSemanticCacheHit = 1;
                if (native.artifactHandle) {
                    this.documentSemanticArtifactHandleByIdentity.set(
                        semanticIdentity,
                        native.artifactHandle,
                    );
                    trimOldestMapEntries(this.documentSemanticArtifactHandleByIdentity, 8);
                }
            }
            const decoded = decodeDocumentSemanticSummary(native);
            return isGraphDocumentSemanticSummary(decoded) ? decoded : undefined;
        } catch (error) {
            if (!isUnsupportedStoreCommand(error, 'documentSemantic:build')) {
                console.warn('[GraphRebuild] Native document semantics unavailable; retaining compatibility facts', error);
            }
            return undefined;
        }
    }

    async loadPersistedSnapshot(scopeId: string): Promise<GraphRebuildSnapshot | null> {
        const current = this.snapshotState();
        if (current?.scopeId === scopeId) {
            const authorizedCurrent = authorizeGraphRebuildSnapshotForLoad(current, (error) => {
                this.rejectPersistedSnapshot(scopeId, error);
                console.warn('[GraphRebuild] Ignoring in-memory graph rebuild snapshot that failed authority parity', error);
            });
            if (authorizedCurrent) return authorizedCurrent;
            this.snapshotState.set(null);
        }
        const activeLoad = this.persistedSnapshotLoads.get(scopeId);
        if (activeLoad) return activeLoad;
        const load = this.loadPersistedSnapshotFromStore(scopeId);
        this.persistedSnapshotLoads.set(scopeId, load);
        try {
            return await load;
        } finally {
            if (this.persistedSnapshotLoads.get(scopeId) === load) {
                this.persistedSnapshotLoads.delete(scopeId);
            }
        }
    }

    async loadPersistedSnapshotShell(scopeId: string): Promise<GraphRebuildSnapshot | null> {
        const current = this.snapshotState();
        if (current?.scopeId === scopeId) return current;
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, SNAPSHOT_DOCUMENT_KEY);
        const shell = document ? scopedDocumentToGraphRebuildSnapshot(document) : null;
        if (!shell) return null;
        assertGraphCanvasBootSnapshotShell(shell);
        return shell;
    }

    async loadVerifiedGenerationSnapshotContent(
        expectedShell: GraphRebuildSnapshot,
    ): Promise<GraphRebuildSnapshot> {
        assertGraphCanvasBootSnapshotShell(expectedShell);
        if (!expectedShell.generationReceiptId || !expectedShell.generationDigestSha256) {
            throw new Error(
                'PHX_GRAPH_CONTENT_LEASE_REQUIRED: compact snapshot must be bound to a generation receipt.',
            );
        }
        if (!expectedShell.contentManifest?.refs.evidenceTargetRegistryPage) {
            throw new Error(
                'PHX_GRAPH_CONTENT_LEASE_CAPABILITY_MISSING: durable evidence registry page requires explicit V2 bootstrap.',
            );
        }
        const key = `${expectedShell.scopeId}\u0000${expectedShell.id}\u0000${expectedShell.generationReceiptId}`;
        const activeLoad = this.generationSnapshotContentLoads.get(key);
        if (activeLoad) return activeLoad;
        const load = this.loadVerifiedGenerationSnapshotContentFromStore(expectedShell);
        this.generationSnapshotContentLoads.set(key, load);
        try {
            return await load;
        } finally {
            if (this.generationSnapshotContentLoads.get(key) === load) {
                this.generationSnapshotContentLoads.delete(key);
            }
        }
    }

    private async loadVerifiedGenerationSnapshotContentFromStore(
        expectedShell: GraphRebuildSnapshot,
    ): Promise<GraphRebuildSnapshot> {
        const document = await this.store.getScopedDocument(
            expectedShell.scopeId,
            GRAPH_REBUILD_NAMESPACE,
            SNAPSHOT_DOCUMENT_KEY,
        );
        const persisted = document ? scopedDocumentToGraphRebuildSnapshot(document) : null;
        if (!persisted) {
            throw new Error(
                `PHX_GRAPH_CONTENT_LEASE_PRIMARY_MISSING: no durable snapshot exists for ${expectedShell.scopeId}.`,
            );
        }
        assertGenerationContentLeaseIdentity(expectedShell, persisted);
        let authorized: GraphRebuildSnapshot | null = null;
        try {
            const hydrated = await this.hydratePersistedSnapshot(persisted);
            authorized = authorizeGraphRebuildSnapshotForLoad(hydrated, (error) => { throw error; });
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            throw new Error(`PHX_GRAPH_CONTENT_LEASE_AUTHORITY_REJECTED: ${message}`);
        }
        if (!authorized) {
            throw new Error('PHX_GRAPH_CONTENT_LEASE_AUTHORITY_REJECTED: hydrated snapshot was not authorized.');
        }
        assertGenerationContentLeaseIdentity(expectedShell, authorized);
        return authorized;
    }

    private async loadPersistedSnapshotFromStore(scopeId: string): Promise<GraphRebuildSnapshot | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, SNAPSHOT_DOCUMENT_KEY);
        const persisted = document ? scopedDocumentToGraphRebuildSnapshot(document) : null;
        if (!persisted) {
            this.rejectedPersistedSnapshotScopes.delete(scopeId);
            return null;
        }
        let authorized: GraphRebuildSnapshot | null = null;
        try {
            const hydrated = await this.hydratePersistedSnapshot(persisted);
            recordGraphCollapseSnapshotBoundary(hydrated, 'persisted_snapshot', { loadedFromStore: 1 });
            authorized = authorizeGraphRebuildSnapshotForLoad(hydrated, (error) => {
                throw error;
            });
        } catch (error) {
            this.rejectPersistedSnapshot(scopeId, error);
            console.warn('[GraphRebuild] Rejecting persisted graph rebuild snapshot that failed authority parity', error);
            return null;
        }
        if (!authorized) return null;
        this.rejectedPersistedSnapshotScopes.delete(scopeId);
        if (authorized.contentManifest) {
            this.contentManifestByScope.set(scopeId, authorized.contentManifest);
            trimOldestMapEntries(this.contentManifestByScope, 64);
        }
        this.snapshotState.set(authorized);
        await this.recoverNativeOperatorDecisionOutcomes(authorized);
        return authorized;
    }

    assertBuildPolicyAuthorized(scopeId: string, policy: GraphIndexPolicy): void {
        const rejection = this.rejectedPersistedSnapshotScopes.get(scopeId);
        if (!rejection || policy === 'force') return;
        throw new Error(
            `Graph rebuild authority invariant: persisted snapshot for ${scopeId} was rejected (${rejection}). `
            + 'Automatic cold fallback is disabled; use explicit Force Rebuild to replace it.',
        );
    }

    private rejectPersistedSnapshot(scopeId: string, error: unknown): void {
        const message = error instanceof Error ? error.message : String(error);
        this.rejectedPersistedSnapshotScopes.set(scopeId, message);
    }

    async loadPersistedGraphModelV2OverGraph(scopeId: string): Promise<GraphModelV2OverGraphExport | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY);
        return document ? scopedDocumentToGraphModelV2OverGraphExport(document) : null;
    }

    async loadPersistedSnapshotContentBlob(
        scopeId: string,
        documentKey: string,
    ): Promise<GraphRebuildContentBlobPayload | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, documentKey);
        return document ? scopedDocumentToGraphRebuildContentBlob(document) : null;
    }

    private async loadPersistedSnapshotContentManifest(
        scopeId: string,
    ): Promise<GraphRebuildContentManifest | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, SNAPSHOT_DOCUMENT_KEY);
        return document ? scopedDocumentToGraphRebuildSnapshot(document)?.contentManifest || null : null;
    }

    async persistRunReceipt(receipt: GraphIndexRunReceipt): Promise<PhoenixContentMutationTiming> {
        const timing = await this.store.upsertScopedDocument(graphIndexReceiptToScopedDocument(receipt));
        dispatchGraphRebuildEvent('graph-index-run-completed', {
            scopeId: receipt.scope.scopeId,
            receiptId: receipt.id,
            snapshotId: receipt.snapshotId,
        });
        return timing;
    }

    async loadPersistedRunReceipt(scopeId: string): Promise<GraphIndexRunReceipt | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, RECEIPT_DOCUMENT_KEY);
        return document ? scopedDocumentToGraphIndexReceipt(document) : null;
    }

    async loadPostProcessCache(scopeId: string, fingerprint: string): Promise<GraphRebuildPostProcessCache | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, postProcessCacheDocumentKey(fingerprint));
        return document ? scopedDocumentToPostProcessCache(document) : null;
    }

    async persistPostProcessCache(
        fingerprint: string,
        snapshot: GraphRebuildSnapshot,
        receipt: GraphIndexRunReceipt,
    ): Promise<void> {
        await this.store.upsertScopedDocument(postProcessCacheToScopedDocument({
            schemaVersion: 'phoenix-graph-postprocess-cache/v1',
            scopeId: snapshot.scopeId,
            scopeKind: snapshot.scopeKind,
            fingerprint,
            snapshotId: snapshot.id,
            receipt,
            receiptId: receipt.id,
            updatedAt: Date.now(),
        }));
    }

    async restorePersistedSnapshot(snapshot: GraphRebuildSnapshot): Promise<void> {
        const reconciled = await this.reconcileDocumentGraphMutations(snapshot);
        finalizeGraphRebuildSnapshot({ snapshot: reconciled });
        this.snapshotState.set(reconciled);
        if (reconciled.operatorMutationJournal) {
            await this.persistOperatorMutationJournal(reconciled.operatorMutationJournal, reconciled.scopeKind);
        }
        await this.persistSnapshot(reconciled);
    }

    async persistGenerationReceipt(
        receipt: GraphGenerationReceiptV2,
    ): Promise<PhoenixContentMutationTiming> {
        await assertGraphGenerationReceipt(receipt);
        return this.store.upsertScopedDocument(graphGenerationReceiptToScopedDocument(receipt));
    }

    async loadPersistedGenerationReceipt(scopeId: string): Promise<GraphGenerationReceiptV2 | null> {
        const document = await this.store.getScopedDocument(
            scopeId,
            GRAPH_REBUILD_NAMESPACE,
            GENERATION_RECEIPT_DOCUMENT_KEY,
        );
        const receipt = document ? scopedDocumentToGraphGenerationReceipt(document) : null;
        if (!receipt) return null;
        await assertGraphGenerationReceipt(receipt);
        return receipt;
    }

    releaseRichSnapshot(
        receipt: GraphGenerationReceiptV2,
        shell: GraphRebuildSnapshot,
    ): boolean {
        const current = this.snapshotState();
        if (!current
            || current.id !== receipt.snapshotId
            || current.scopeId !== receipt.scopeId
            || current.authorityContract?.contentHash !== receipt.authority.contentHash) return false;
        assertGraphCanvasBootSnapshotShell(shell);
        if (shell.generationReceiptId !== receipt.receiptId
            || shell.generationDigestSha256 !== receipt.digestSha256) {
            throw new Error('Compact graph generation shell receipt drift.');
        }
        this.snapshotState.set(shell);
        return true;
    }

    async applyOperatorReviewDecision(
        targetObjectId: string,
        decision: GraphOperatorMutationDecision,
    ): Promise<boolean> {
        const current = this.snapshotState();
        const row = current?.documentReviewSummary?.rows.find(
            (candidate) => candidate.objectId === targetObjectId,
        );
        if (!current || !row) return false;
        const decidedAt = Date.now();
        const next = applyGraphOperatorMutationDecisionToSnapshot(
            current,
            [targetObjectId],
            decision,
            decidedAt,
        );
        if (!next) return false;
        if (this.phoenix.target !== 'native') {
            await this.restorePersistedSnapshot(next);
            return true;
        }

        const beginValue = await this.phoenix.beginNativeOperatorDecision(
            nativeOperatorDecisionBeginRequest(current, row, decision, decidedAt),
        );
        if (!isNativeOperatorDecisionBeginResponse(beginValue)) {
            throw new Error('Native operator decision begin returned an invalid receipt.');
        }
        const journalReceipt = bindNativeDecisionToOperatorMutation(
            next,
            targetObjectId,
            decidedAt,
            beginValue,
        );
        await this.restorePersistedSnapshot(next);
        const completionValue = await this.phoenix.completeNativeOperatorDecision(
            nativeOperatorDecisionCompleteRequest(next, journalReceipt),
        );
        if (!isNativeOperatorDecisionCompleteResponse(completionValue)
            || completionValue.decisionReceiptId !== beginValue.decisionReceiptId) {
            throw new Error('Native operator decision completion returned a stale receipt.');
        }
        return true;
    }

    async commitCanonicalEpisodeAssignment(
        eventId: string,
        selectedAction: CanonicalEpisodeAssignmentSelection,
    ): Promise<CanonicalEpisodeAssignmentCommitResponse | null> {
        await this.hydrateNativeStoryContinuity();
        const current = this.snapshotState();
        if (!current) return null;
        if (this.phoenix.target !== 'native') {
            throw new Error('Canonical episode assignment requires native durable graph authority.');
        }
        const value = await this.phoenix.commitCanonicalEpisodeAssignment(
            canonicalEpisodeAssignmentCommitRequest(current, eventId, selectedAction),
        );
        if (!isCanonicalEpisodeAssignmentCommitResponse(value)) {
            throw new Error('Canonical episode assignment returned an invalid authority receipt.');
        }
        return value;
    }

    async commitCanonicalEpisodeAssignmentsBatch(
        selections: ReadonlyArray<{
            eventId: string;
            selectedAction: CanonicalEpisodeAssignmentSelection;
        }>,
    ): Promise<CanonicalEpisodeAssignmentBatchCommitResponse | null> {
        await this.hydrateNativeStoryContinuity();
        const current = this.snapshotState();
        if (!current) return null;
        if (this.phoenix.target !== 'native') {
            throw new Error('Canonical episode assignment batching requires native durable graph authority.');
        }
        if (selections.length === 0 || selections.length > 4_096) {
            throw new Error('Canonical episode assignment batch must contain 1..=4096 selections.');
        }
        const decidedAt = Date.now();
        const value = await this.phoenix.commitCanonicalEpisodeAssignmentsBatch({
            schemaVersion: CANONICAL_EPISODE_ASSIGNMENT_BATCH_COMMIT_SCHEMA,
            requests: selections.map((selection, index) => canonicalEpisodeAssignmentCommitRequest(
                current,
                selection.eventId,
                selection.selectedAction,
                decidedAt + index,
            )),
        });
        if (!isCanonicalEpisodeAssignmentBatchCommitResponse(value)) {
            throw new Error('Canonical episode assignment batch returned an invalid authority receipt.');
        }
        return value;
    }

    private async recoverNativeOperatorDecisionOutcomes(snapshot: GraphRebuildSnapshot): Promise<void> {
        if (this.phoenix.target !== 'native') return;
        for (const request of pendingNativeOperatorDecisionCompletions(snapshot)) {
            const value = await this.phoenix.completeNativeOperatorDecision(request);
            if (!isNativeOperatorDecisionCompleteResponse(value)
                || value.decisionReceiptId !== request.decisionReceiptId) {
                throw new Error('Native operator decision recovery returned a stale receipt.');
            }
        }
    }

    async loadPersistedOperatorMutationJournal(scopeId: string): Promise<GraphOperatorMutationJournal | null> {
        return this.loadOperatorMutationJournal(scopeId);
    }

    private async reconcileDocumentGraphMutations(
        snapshot: GraphRebuildSnapshot,
        reuseCurrentProjection = false,
    ): Promise<GraphRebuildSnapshot> {
        const current = this.snapshotState();
        if (reuseCurrentProjection && current?.scopeId === snapshot.scopeId) {
            snapshot.graphTruthCommitLedger = current.graphTruthCommitLedger;
            snapshot.documentGraphMutationLedger = current.documentGraphMutationLedger;
            snapshot.operatorMutationJournal = current.operatorMutationJournal;
            if (snapshot.operatorMutationJournal) {
                snapshot.counters = {
                    ...snapshot.counters,
                    operatorMutationIntents: snapshot.operatorMutationJournal.counters.intents,
                    operatorMutationActive: snapshot.operatorMutationJournal.counters.active,
                    operatorMutationApplied: snapshot.operatorMutationJournal.counters.applied,
                    operatorMutationConflicted: snapshot.operatorMutationJournal.counters.conflicted,
                    operatorMutationUndone: snapshot.operatorMutationJournal.counters.undone,
                    operatorMutationReceipts: snapshot.operatorMutationJournal.counters.receipts,
                };
            }
            return snapshot;
        }
        const truthProjection = await this.loadGraphTruthCommitProjection(snapshot.scopeId);
        if (truthProjection) {
            snapshot.graphTruthCommitLedger = truthProjection.ledger;
            snapshot.documentGraphMutationLedger = graphDocumentGraphMutationLedgerFromTruthCommits(truthProjection.commits);
            snapshot.operatorMutationJournal = mergeGraphOperatorMutationJournals(graphOperatorMutationJournalFromTruthCommits(
                snapshot.scopeId,
                truthProjection.commits,
                snapshot.builtAt,
            ), snapshot.operatorMutationJournal);
            snapshot.counters = {
                ...snapshot.counters,
                operatorMutationIntents: snapshot.operatorMutationJournal.counters.intents,
                operatorMutationActive: snapshot.operatorMutationJournal.counters.active,
                operatorMutationApplied: snapshot.operatorMutationJournal.counters.applied,
                operatorMutationConflicted: snapshot.operatorMutationJournal.counters.conflicted,
                operatorMutationUndone: snapshot.operatorMutationJournal.counters.undone,
                operatorMutationReceipts: snapshot.operatorMutationJournal.counters.receipts,
            };
            return snapshot;
        }
        const previousLedger = await this.loadDocumentGraphMutationLedger(snapshot.scopeId);
        snapshot.documentGraphMutationLedger = previousLedger || emptyGraphDocumentGraphMutationLedger();
        return snapshot;
    }

    private async loadGraphTruthCommitProjection(scopeId: string): Promise<GraphTruthCommitProjection | null> {
        if (this.phoenix.target !== 'native') return null;
        try {
            const payload = await this.phoenix.storeCommand('graphTruth:listCommits', { scopeId });
            const commits = normalizeGraphTruthCommits(payload);
            return commits.length ? { commits, ledger: graphTruthCommitLedgerFor(commits) } : null;
        } catch (error) {
            if (!isUnsupportedStoreCommand(error, 'graphTruth:listCommits')) {
                console.warn('[GraphRebuild] Native graph truth commit ledger unavailable; retaining compatibility ledgers', error);
            }
            return null;
        }
    }

    private async loadDocumentGraphMutationLedger(
        scopeId: string,
    ): Promise<GraphDocumentGraphMutationLedger | undefined> {
        const current = this.snapshotState();
        if (current?.scopeId === scopeId) return current.documentGraphMutationLedger;
        const document = await this.store.getScopedDocument(
            scopeId,
            GRAPH_REBUILD_NAMESPACE,
            SNAPSHOT_DOCUMENT_KEY,
        );
        return document
            ? scopedDocumentToGraphRebuildSnapshot(document)?.documentGraphMutationLedger
            : undefined;
    }

    private async loadOperatorMutationJournal(
        scopeId: string,
        options: { allowSnapshotFallback?: boolean } = {},
    ): Promise<GraphOperatorMutationJournal | null> {
        const current = this.snapshotState();
        if (current?.scopeId === scopeId && current.operatorMutationJournal) {
            return current.operatorMutationJournal;
        }
        const allowSnapshotFallback = options.allowSnapshotFallback !== false;
        if (!allowSnapshotFallback && this.absentOperatorMutationJournalScopes.has(scopeId)) {
            return null;
        }
        const journalDocument = await this.store.getScopedDocument(
            scopeId,
            GRAPH_REBUILD_NAMESPACE,
            OPERATOR_MUTATION_JOURNAL_DOCUMENT_KEY,
        );
        if (journalDocument) {
            this.absentOperatorMutationJournalScopes.delete(scopeId);
            return scopedDocumentToGraphOperatorMutationJournal(journalDocument);
        }
        if (!allowSnapshotFallback) {
            this.absentOperatorMutationJournalScopes.add(scopeId);
            return null;
        }
        const snapshotDocument = await this.store.getScopedDocument(
            scopeId,
            GRAPH_REBUILD_NAMESPACE,
            SNAPSHOT_DOCUMENT_KEY,
        );
        const snapshotJournal = snapshotDocument
            ? scopedDocumentToGraphRebuildSnapshot(snapshotDocument)?.operatorMutationJournal || null
            : null;
        if (snapshotJournal) this.absentOperatorMutationJournalScopes.delete(scopeId);
        return snapshotJournal;
    }

    private async persistOperatorMutationJournal(
        journal: GraphOperatorMutationJournal,
        scopeKind: GraphRebuildScopeKind,
    ): Promise<void> {
        await this.store.upsertScopedDocument(graphOperatorMutationJournalToScopedDocument(journal, scopeKind));
        this.absentOperatorMutationJournalScopes.delete(journal.scopeId);
    }

    private async persistSnapshot(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
        emitEvent = true,
        options: {
            durabilityMode?: GraphBuildDurabilityMode;
            previousContentManifest?: GraphRebuildContentManifest;
            skipPrimarySnapshotWrite?: boolean;
        } = {},
    ): Promise<void> {
        const authorityAssertStarted = performance.now();
        assertGraphSnapshotAuthority(snapshot);
        if (timings) timings.authorityAssertMs = elapsedMs(authorityAssertStarted);
        recordGraphCollapseSnapshotBoundary(snapshot, 'persisted_snapshot');
        const serializeStarted = performance.now();
        const contentBlobEntries = graphRebuildSnapshotContentBlobEntries(snapshot);
        const persistedSnapshot = graphRebuildSnapshotPersistenceView(snapshot, contentBlobEntries);
        if (persistedSnapshot.contentManifest) {
            snapshot.contentManifest = persistedSnapshot.contentManifest;
            this.contentManifestByScope.set(snapshot.scopeId, persistedSnapshot.contentManifest);
            trimOldestMapEntries(this.contentManifestByScope, 64);
        }
        const contentBlobDocuments = graphRebuildSnapshotContentBlobDocuments(snapshot, contentBlobEntries);
        const documentKey = options.durabilityMode === 'diagnostic'
            ? DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY
            : SNAPSHOT_DOCUMENT_KEY;
        const overGraphEncodeStarted = performance.now();
        const overGraphDocument = options.durabilityMode === 'interactive'
            ? null
            : graphModelV2OverGraphExportToScopedDocument(snapshot);
        if (timings) {
            timings.snapshotOverGraphEncodeMs = elapsedMs(overGraphEncodeStarted);
            timings.snapshotOverGraphSkipped = options.durabilityMode === 'interactive' ? 1 : 0;
        }
        const overGraphDocumentPayloadStats = overGraphDocument
            ? graphRebuildSnapshotDocumentPayloadStats(overGraphDocument.payload)
            : undefined;
        let previousContentManifest = options.previousContentManifest;
        let contentBlobReads = 0;
        let missingContentBlobDocuments: StoreScopedDocument[] | null = null;
        if (options.durabilityMode === 'interactive' && previousContentManifest) {
            missingContentBlobDocuments = missingContentBlobDocumentsForManifest(
                contentBlobDocuments,
                contentBlobEntries,
                previousContentManifest,
            );
        }
        const primaryWriteSkipped = options.durabilityMode === 'interactive'
            && !!options.skipPrimarySnapshotWrite
            && !!previousContentManifest
            && missingContentBlobDocuments !== null
            && missingContentBlobDocuments.length === 0
            && !overGraphDocument;
        const primaryEncodeStarted = performance.now();
        const document = primaryWriteSkipped
            ? null
            : graphRebuildSnapshotToScopedDocument(persistedSnapshot, documentKey);
        if (timings) timings.snapshotPrimaryEncodeMs = primaryWriteSkipped ? 0 : elapsedMs(primaryEncodeStarted);
        const documentPayloadStats = document
            ? graphRebuildSnapshotDocumentPayloadStats(document.payload)
            : undefined;
        if (timings) {
            const profileStarted = performance.now();
            timings.snapshotPayloadBreakdown = {
                ...graphRebuildSnapshotPayloadCounters(
                    persistedSnapshot,
                    document?.payload.length || 0,
                    overGraphDocument?.payload.length || 0,
                    documentPayloadStats,
                    overGraphDocumentPayloadStats,
                ),
                ...graphRebuildContentBlobPayloadCounters(contentBlobEntries),
            };
            timings.snapshotPayloadProfileMs = elapsedMs(profileStarted);
            timings.snapshotSerializeMs = elapsedMs(serializeStarted);
            timings.snapshotPayloadChars = document?.payload.length || 0;
            timings.snapshotPrimaryRawPayloadChars = documentPayloadStats?.rawChars || 0;
            timings.snapshotPrimaryCompressedBytes = documentPayloadStats?.compressedBytes || 0;
            timings.snapshotCompressionSavedChars = documentPayloadStats?.savedChars || 0;
            timings.snapshotCompressionRatioPct = documentPayloadStats?.ratioPct || 0;
            timings.snapshotOverGraphPayloadChars = overGraphDocument?.payload.length || 0;
            timings.snapshotOverGraphRawPayloadChars = overGraphDocumentPayloadStats?.rawChars || 0;
            timings.snapshotOverGraphCompressedBytes = overGraphDocumentPayloadStats?.compressedBytes || 0;
            timings.snapshotOverGraphCompressionSavedChars = overGraphDocumentPayloadStats?.savedChars || 0;
            timings.snapshotOverGraphCompressionRatioPct = overGraphDocumentPayloadStats?.ratioPct || 0;
            timings.snapshotTotalPayloadChars = (document?.payload.length || 0)
                + (overGraphDocument?.payload.length || 0)
                + contentBlobDocuments.reduce((sum, blob) => sum + blob.payload.length, 0);
        }
        const storeStarted = performance.now();
        if (!previousContentManifest && options.durabilityMode === 'interactive') {
            previousContentManifest = await this.loadPersistedSnapshotContentManifest(snapshot.scopeId) || undefined;
        }
        if (options.durabilityMode === 'interactive') {
            missingContentBlobDocuments ??= missingContentBlobDocumentsForManifest(
                contentBlobDocuments,
                contentBlobEntries,
                previousContentManifest,
            );
        } else {
            contentBlobReads = contentBlobDocuments.length;
            const existingContentBlobs = await Promise.all(contentBlobDocuments.map((blobDocument) =>
                this.store.getScopedDocument(
                    blobDocument.scopeFolderId,
                    blobDocument.namespace,
                    blobDocument.documentKey,
                ),
            ));
            missingContentBlobDocuments = contentBlobDocuments.filter((_, index) => !existingContentBlobs[index]);
        }
        const contentBlobDocumentsToWrite = missingContentBlobDocuments || [];
        const documentsToWrite = [
            ...contentBlobDocumentsToWrite,
            ...(document ? [document] : []),
            ...(overGraphDocument ? [overGraphDocument] : []),
        ];
        if (documentsToWrite.length) await this.store.upsertScopedDocuments(documentsToWrite);
        if (timings) {
            timings.snapshotPrimaryStoreMs = 0;
            timings.snapshotOverGraphStoreMs = 0;
            timings.snapshotStoreDocuments = documentsToWrite.length;
            timings.snapshotPrimaryWriteSkipped = primaryWriteSkipped ? 1 : 0;
            timings.snapshotWrittenContentBlobs = contentBlobDocumentsToWrite.length;
            timings.snapshotReusedContentBlobs = contentBlobDocuments.length - contentBlobDocumentsToWrite.length;
            timings.snapshotContentBlobReads = contentBlobReads;
            timings.snapshotContentBlobManifestTrusted = options.durabilityMode === 'interactive' && previousContentManifest ? 1 : 0;
            timings.snapshotContentBlobManifestMatches = contentBlobDocuments.length - contentBlobDocumentsToWrite.length;
            timings.snapshotContentBlobManifestMisses = contentBlobDocumentsToWrite.length;
        }
        if (timings) timings.snapshotStoreMs = elapsedMs(storeStarted);
        if (emitEvent) {
            const eventStarted = performance.now();
            dispatchGraphRebuildEvent('graph-rebuild-snapshot-updated', {
                scopeId: snapshot.scopeId,
                snapshotId: snapshot.id,
            });
            if (timings) timings.snapshotEventMs = elapsedMs(eventStarted);
        }
    }

    private async hydratePersistedSnapshot(persisted: GraphRebuildSnapshot): Promise<GraphRebuildSnapshot> {
        const refs = persisted.contentManifest?.refs || {};
        const activeRefs = Object.values(refs).filter((ref): ref is NonNullable<typeof ref> => Boolean(ref));
        const documents = await this.store.getScopedDocumentsByKeys(
            persisted.scopeId,
            GRAPH_REBUILD_NAMESPACE,
            activeRefs.map((ref) => ref.documentKey),
        );
        const documentByKey = new Map(documents.map((document) => [document.documentKey, document]));
        const blobs: Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>> = {};
        for (const ref of activeRefs) {
            const document = documentByKey.get(ref.documentKey);
            const blob = document ? scopedDocumentToGraphRebuildContentBlob(document) : null;
            if (blob) blobs[ref.field] = blob;
        }
        return hydrateGraphSnapshotContent(persisted, blobs);
    }

    private async loadOccurrences(noteIds: string[], entities: RegisteredEntity[]): Promise<EntityOccurrence[]> {
        if (!canUseOccurrenceTable()) return [];
        const entityIds = new Set(entities.map((entity) => entity.id));
        const rows = noteIds.length
            ? (await Promise.all(noteIds.map((noteId) => db.entityOccurrences.where('noteId').equals(noteId).toArray()))).flat()
            : await db.entityOccurrences.toArray();
        return rows.filter((row) => entityIds.has(row.entityId));
    }

    private async loadNoteTexts(noteIds: string[], occurrences: EntityOccurrence[]): Promise<Record<string, string>> {
        if (!canUseNotesTable()) return {};
        const scopedNoteIds = noteIds.length ? noteIds : [...new Set(occurrences.map((row) => row.noteId))];
        const notes = await loadNotesWithBodies(scopedNoteIds);
        return Object.fromEntries(notes.map((note) => [note.id, notePlainText(note)]));
    }

    private async loadNoteFolderContexts(
        noteIds: string[],
        occurrences: EntityOccurrence[],
    ): Promise<Record<string, GraphRebuildNoteFolderContext>> {
        if (!canUseNotesTable()) return {};
        const scopedNoteIds = noteIds.length ? noteIds : [...new Set(occurrences.map((row) => row.noteId))];
        if (!scopedNoteIds.length) return {};
        const notes = await loadNotesWithBodies(scopedNoteIds);
        const folderIds = [...new Set(notes.map((note) => note.folderId || '').filter(Boolean))];
        const folders = await Promise.all(folderIds.map((folderId) => db.folders.get(folderId)));
        const folderById = new Map(folders.filter((folder): folder is Folder => !!folder).map((folder) => [folder.id, folder]));
        const out: Record<string, GraphRebuildNoteFolderContext> = {};
        for (const note of notes) {
            const folder = note.folderId ? folderById.get(note.folderId) : undefined;
            out[note.id] = folderContextForNote(note, folder);
        }
        return out;
    }

    private async loadChunks(
        noteIds: string[],
        occurrences: EntityOccurrence[],
        noteTexts: Record<string, string>,
        durabilityMode: GraphBuildDurabilityMode = 'durable',
    ): Promise<GraphRebuildChunk[]> {
        const scopedNoteIds = noteIds.length ? noteIds : [...new Set(occurrences.map((row) => row.noteId))];
        if (durabilityMode === 'interactive') {
            return scopedNoteIds.flatMap((noteId) =>
                buildAdaptiveGraphRebuildChunks(noteId, noteTexts[noteId] || '')
            );
        }
        if (this.phoenix.target === 'native') {
            try {
                const native = await this.phoenix.storeCommand('documentChunk:build', {
                    chunkSize: 1_840,
                    overlap: 256,
                    documents: scopedNoteIds.map((noteId) => ({ noteId, text: noteTexts[noteId] || '' })),
                }) as NativeDocumentChunkSummary | null;
                if (native?.schemaVersion === 'phoenix-document-chunks/v1') {
                    const byNote = new Map(native.documents.map((document) => [document.noteId, document.chunks]));
                    const chunks = scopedNoteIds.flatMap((noteId) =>
                        buildGraphRebuildChunksFromRanges(noteId, noteTexts[noteId] || '', byNote.get(noteId) || []),
                    );
                    if (chunks.length) return chunks;
                }
            } catch (error) {
                console.warn('[GraphRebuild] Native document chunker unavailable; using adaptive compatibility chunker', error);
            }
        }
        const dynamicChunks = await loadDynamicNoteChunks(scopedNoteIds);
        if (dynamicChunks.length) return dynamicChunks;
        const blockChunks = await loadBlockChunks(scopedNoteIds);
        if (blockChunks.length) return blockChunks;
        return loadFallbackNoteChunks(scopedNoteIds);
    }
}

export function recoverGraphRebuildOccurrences(
    noteTexts: Record<string, string>,
    entities: RegisteredEntity[],
    now = Date.now(),
): EntityOccurrence[] {
    const rows: EntityOccurrence[] = [];
    const searchable = entities
        .filter((entity) => !!entity.id && !!entity.label)
        .map((entity) => ({ entity, surfaces: entitySurfaces(entity) }))
        .filter((entry) => entry.surfaces.length);

    for (const [noteId, text] of Object.entries(noteTexts)) {
        if (!noteId || !text.trim()) continue;
        const lowerText = text.toLocaleLowerCase();
        for (const { entity, surfaces } of searchable) {
            for (const surface of surfaces) {
                const lowerSurface = surface.toLocaleLowerCase();
                let start = lowerText.indexOf(lowerSurface);
                while (start >= 0) {
                    const end = start + surface.length;
                    if (isEntityBoundary(text, start - 1) && isEntityBoundary(text, end)) {
                        rows.push(graphRebuildOccurrence(noteId, text, entity, start, end, now));
                    }
                    start = lowerText.indexOf(lowerSurface, Math.max(start + 1, end));
                }
            }
        }
    }
    return rows;
}

export function snapshotAnchorsToGraphRebuildOccurrences(
    snapshot: GraphRebuildSnapshot | null | undefined,
    now = Date.now(),
    noteTexts?: Record<string, string>,
): EntityOccurrence[] {
    if (!snapshot?.entityAnchors?.length) return [];
    const nodeByEntityId = new Map((snapshot.nodes || []).map((node) => [node.entityId, node]));
    return snapshot.entityAnchors
        .filter((anchor) => Number.isFinite(anchor.sourceStart) && Number.isFinite(anchor.sourceEnd))
        .filter((anchor) => anchorSpanStillMatches(anchor.noteId, anchor.sourceStart, anchor.sourceEnd, anchor.surface, noteTexts))
        .map((anchor): EntityOccurrence => {
            const node = nodeByEntityId.get(anchor.entityId);
            return {
                id: `${anchor.id}:snapshot-fallback`,
                noteId: anchor.noteId,
                entityId: anchor.entityId,
                entityLabel: node?.label || anchor.surface,
                entityKind: node?.kind || 'UNKNOWN',
                sourceStart: anchor.sourceStart,
                sourceEnd: anchor.sourceEnd,
                surface: anchor.surface,
                source: occurrenceSourceFromAnchor(anchor.source),
                confidence: anchor.confidence,
                excerpt: anchor.surface,
                generation: anchor.generation || now,
                createdAt: now,
                updatedAt: now,
            };
        });
}

export function graphRebuildSnapshotToNativeCompilerPayload(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    const documentCompilerSummary = nativeCompilerDocumentCompilerSummary(snapshot);
    return {
        schemaVersion: snapshot.schemaVersion,
        id: snapshot.id,
        source: snapshot.source,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        noteIds: snapshot.noteIds,
        builtAt: snapshot.builtAt,
        chunks: snapshot.chunks,
        mentions: snapshot.mentions,
        entityAnchors: snapshot.entityAnchors,
        relationships: snapshot.relationships,
        events: snapshot.events,
        episodes: [],
        chunkSemanticBridges: [],
        episodeConnections: [],
        episodeProjectionEdges: [],
        temporalEdges: snapshot.temporalEdges,
        causalEdges: snapshot.causalEdges,
        memoryState: snapshot.memoryState,
        embeddingTargets: snapshot.embeddingTargets.filter((target) => target.admissionStatus === 'admitted'),
        embeddingVectors: [],
        projectionRefs: [],
        nodes: snapshot.nodes,
        edges: snapshot.edges,
        calendarRegistrySummary: snapshot.calendarRegistrySummary,
        documentSidecarSummary: nativeCompilerEvidenceSidecar(snapshot, documentCompilerSummary),
        documentReviewSummary: nativeCompilerDocumentReviewSummary(snapshot),
        documentCompilerSummary,
        discourseSpineSummary: nativeCompilerDiscourseSpineSummary(snapshot),
        counters: snapshot.counters,
    };
}

export function graphRebuildSnapshotToNativeAnalysisPayload(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    return {
        schemaVersion: snapshot.schemaVersion,
        id: snapshot.id,
        source: snapshot.source,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        noteIds: snapshot.noteIds,
        builtAt: snapshot.builtAt,
        chunks: snapshot.chunks,
        mentions: [],
        entityAnchors: snapshot.entityAnchors,
        relationships: [],
        events: snapshot.events,
        episodes: snapshot.episodes,
        chunkSemanticBridges: [],
        episodeConnections: [],
        episodeProjectionEdges: [],
        temporalEdges: snapshot.temporalEdges,
        causalEdges: snapshot.causalEdges,
        memoryState: snapshot.memoryState,
        memoryGovernanceCandidates: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: snapshot.nodes,
        edges: [],
        counters: snapshot.counters,
        documentCompilerSummary: nativeCompilerDocumentCompilerSummary(snapshot),
    };
}

export function graphRebuildSnapshotToNativeQueryPayload(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    return {
        schemaVersion: snapshot.schemaVersion,
        id: snapshot.id,
        source: snapshot.source,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        noteIds: snapshot.noteIds,
        builtAt: snapshot.builtAt,
        chunks: snapshot.chunks,
        mentions: [],
        entityAnchors: [],
        relationships: snapshot.relationships,
        events: snapshot.events,
        episodes: snapshot.episodes,
        chunkSemanticBridges: [],
        episodeConnections: [],
        episodeProjectionEdges: [],
        temporalEdges: snapshot.temporalEdges,
        causalEdges: snapshot.causalEdges,
        memoryState: [],
        memoryGovernanceCandidates: [],
        embeddingTargets: snapshot.embeddingTargets,
        embeddingVectors: [],
        projectionRefs: [],
        nodes: snapshot.nodes,
        edges: snapshot.edges,
        counters: snapshot.counters,
    };
}

function isNativeChunkSemanticBridgeOutput(
    value: NativeChunkSemanticBridgeOutput | null | undefined,
): value is NativeChunkSemanticBridgeOutput {
    return value?.schemaVersion === 'phoenix-chunk-semantic-bridge-native-output/v1'
        && value.source === 'rust'
        && Array.isArray(value.candidates)
        && isGraphCrossDocumentBridgeRunCertificate(value.crossDocumentCertificate, true)
        && !!value.qualityGate
        && !!value.timing;
}

function isNativeMemoryGovernanceOutput(
    value: NativeMemoryGovernanceOutput | null | undefined,
): value is NativeMemoryGovernanceOutput {
    return value?.schemaVersion === 'phoenix-memory-governance-native-output/v1'
        && value.source === 'rust'
        && Array.isArray(value.candidates)
        && !!value.timing;
}

function isNativeMemoryGovernanceRetrievalExperimentOutput(
    value: NativeMemoryGovernanceRetrievalExperimentOutput | null | undefined,
): value is NativeMemoryGovernanceRetrievalExperimentOutput {
    return value?.schemaVersion === 'phoenix-memory-governance-retrieval-experiment-native-output/v1'
        && value.source === 'rust'
        && !!value.experiment
        && !!value.timing;
}

function isNativeSnapshotAnalysisOutput(
    value: NativeSnapshotAnalysisOutput | null | undefined,
): value is NativeSnapshotAnalysisOutput {
    return value?.schemaVersion === 'phoenix-graph-snapshot-analysis-native-output/v1'
        && value.source === 'rust'
        && value.noTopologyWrites === true
        && isNativeChunkSemanticBridgeOutput(value.bridge)
        && isNativeStoryContinuityOutput(value.continuity)
        && isNativeMemoryGovernanceOutput(value.governance)
        && (!value.retrieval || isNativeMemoryGovernanceRetrievalExperimentOutput(value.retrieval))
        && isNativePromotionVerdictOutput(value.promotion)
        && !!value.timing;
}

function isNativeGraphRunPage(
    value: NativeGraphRunPage | null | undefined,
): value is NativeGraphRunPage {
    return value?.schemaVersion === 'phoenix-graph-run-page/v1'
        && value.source === 'rust'
        && (value.section === undefined || value.section === 'all' || value.section === 'storyContinuity')
        && typeof value.runHandle === 'string'
        && value.runHandle.startsWith('graph-run:')
        && Number.isInteger(value.offset)
        && Number.isInteger(value.limit)
        && Number.isInteger(value.detailRows)
        && Number.isInteger(value.returnedDetailRows)
        && typeof value.arena?.analysisIdentity === 'string'
        && typeof value.arena.reused === 'boolean'
        && Number.isFinite(value.arena.residentBytes)
        && Number.isInteger(value.arena.activeLeases)
        && Number.isFinite(value.arena.projectionMicros)
        && !!value.counts
        && Number.isInteger(value.counts.bridgeCandidates)
        && Number.isInteger(value.counts.governanceCandidates)
        && [
            value.counts.crossDocumentPairCoverage,
            value.counts.crossDocumentSelected,
            value.counts.crossDocumentRejected,
            value.counts.crossDocumentWeakest,
            value.counts.promotionRows,
            value.counts.continuityEvents,
            value.counts.continuityBoundaries,
            value.counts.continuityEpisodes,
            value.counts.continuityTemporal,
            value.counts.continuityStates,
            value.counts.continuityCausal,
            value.counts.continuityConnections,
            value.counts.continuityConflicts,
            value.counts.retrievalTopRows,
            value.counts.retrievalViolations,
        ].every(Number.isInteger)
        && !!value.counts.bridgeByType
        && !!value.counts.governanceByAction
        && (!value.nextOffset || Number.isInteger(value.nextOffset))
        && isNativeSnapshotAnalysisOutput(value.projection);
}

function isCompleteStoryContinuityContract(contract: GraphStoryContinuityContract): boolean {
    const counts = contract.certificate.counters;
    return contract.events.length === counts.events
        && contract.boundaryReceipts.length === counts.boundaryReceipts
        && contract.episodes.length === counts.episodes
        && contract.temporalCandidates.length === counts.temporalCandidates
        && contract.stateIntervals.length === counts.stateIntervals
        && contract.causalCandidates.length === counts.causalCandidates
        && contract.episodeConnections.length === counts.episodeConnections
        && contract.conflicts.length === counts.conflicts;
}

function assertCompleteStoryContinuityContract(
    contract: GraphStoryContinuityContract,
    expectedDetailRows: number,
): void {
    const rows = contract.events.length
        + contract.boundaryReceipts.length
        + contract.episodes.length
        + contract.temporalCandidates.length
        + contract.stateIntervals.length
        + contract.causalCandidates.length
        + contract.episodeConnections.length
        + contract.conflicts.length;
    if (!isCompleteStoryContinuityContract(contract) || rows !== expectedDetailRows) {
        throw new Error(
            `Native story continuity count mismatch: ${rows}/${expectedDetailRows} rows do not match the certificate.`,
        );
    }
}

function sameStoryContinuityHeader(
    left: GraphStoryContinuityContract,
    right: GraphStoryContinuityContract,
): boolean {
    return left.schemaVersion === right.schemaVersion
        && left.source === right.source
        && left.sourceSnapshotId === right.sourceSnapshotId
        && left.generatedAt === right.generatedAt
        && left.commitPolicy === right.commitPolicy
        && left.noTopologyCommit === right.noTopologyCommit
        && JSON.stringify(left.certificate) === JSON.stringify(right.certificate);
}

function appendUniqueStoryContinuityRows(
    target: StoryContinuityRows,
    source: GraphStoryContinuityContract,
    rowIds: Set<string>,
): void {
    appendUniqueRows(target.events, source.events, rowIds);
    appendUniqueRows(target.boundaryReceipts, source.boundaryReceipts, rowIds);
    appendUniqueRows(target.episodes, source.episodes, rowIds);
    appendUniqueRows(target.temporalCandidates, source.temporalCandidates, rowIds);
    appendUniqueRows(target.stateIntervals, source.stateIntervals, rowIds);
    appendUniqueRows(target.causalCandidates, source.causalCandidates, rowIds);
    appendUniqueRows(target.episodeConnections, source.episodeConnections, rowIds);
    appendUniqueRows(target.conflicts, source.conflicts, rowIds);
}

function appendUniqueRows<T extends { id: string }>(
    target: T[],
    source: readonly T[],
    rowIds: Set<string>,
): void {
    for (const row of source) {
        if (rowIds.has(row.id)) {
            throw new Error(`Native story continuity returned a duplicate row: ${row.id}`);
        }
        rowIds.add(row.id);
        target.push(row);
    }
}

function nativeCompilerDocumentReviewSummary(
    snapshot: GraphRebuildSnapshot,
): GraphRebuildSnapshot['documentReviewSummary'] {
    const rows = (snapshot.documentReviewSummary?.rows || [])
        .slice()
        .sort((left, right) => reviewStateRank(left.state) - reviewStateRank(right.state)
            || String(left.id).localeCompare(String(right.id)))
        .slice(0, NATIVE_COMPILER_REVIEW_ROW_LIMIT)
        .map((row) => ({
            id: row.id,
            objectId: row.objectId,
            objectKind: row.objectKind,
            state: row.state,
            title: boundedNativePacketText(row.title || row.objectId),
            subtitle: boundedNativePacketText(row.subtitle || ''),
            detail: '',
            noteId: row.noteId,
            sourceStart: row.sourceStart || 0,
            sourceEnd: row.sourceEnd || 0,
            confidence: row.confidence || 0,
            detector: boundedNativePacketText(row.detector || 'document_review'),
            parentUnitIds: boundedNativePacketList(row.parentUnitIds),
            childUnitIds: boundedNativePacketList(row.childUnitIds),
            evidenceSpanIds: boundedNativePacketList(row.evidenceSpanIds),
            relatedObjectIds: boundedNativePacketList(row.relatedObjectIds),
            why: [],
        }));
    return rows.length ? { rows } as unknown as GraphRebuildSnapshot['documentReviewSummary'] : undefined;
}

function nativeCompilerDiscourseSpineSummary(
    snapshot: GraphRebuildSnapshot,
): GraphRebuildSnapshot['discourseSpineSummary'] {
    const source = snapshot.discourseSpineSummary;
    if (!source) return undefined;
    const clusters = (source.clusters || [])
        .slice()
        .sort((left, right) => (right.score || 0) - (left.score || 0) || String(left.id).localeCompare(String(right.id)))
        .slice(0, NATIVE_COMPILER_DISCOURSE_CLUSTER_LIMIT)
        .map((cluster) => ({
            id: cluster.id,
            kind: cluster.kind,
            label: boundedNativePacketText(cluster.label),
            targetIds: boundedNativePacketList(cluster.targetIds, NATIVE_COMPILER_PACKET_LIST_LIMIT * 2),
            score: cluster.score || 0,
        }));
    const bridges = (source.bridges || [])
        .slice()
        .sort((left, right) => (right.scoringBundle?.finalScore || 0) - (left.scoringBundle?.finalScore || 0)
            || String(left.id).localeCompare(String(right.id)))
        .slice(0, NATIVE_COMPILER_DISCOURSE_BRIDGE_LIMIT)
        .map((bridge) => ({
            id: bridge.id,
            kind: bridge.kind,
            status: bridge.status,
            sourceTargetId: bridge.sourceTargetId,
            targetTargetId: bridge.targetTargetId,
            label: boundedNativePacketText(bridge.label),
            evidenceTargetIds: boundedNativePacketList(bridge.evidenceTargetIds, NATIVE_COMPILER_PACKET_LIST_LIMIT * 2),
            sharedLabelIds: boundedNativePacketList(bridge.sharedLabelIds),
            sharedEntityIds: boundedNativePacketList(bridge.sharedEntityIds),
        }));
    if (!clusters.length && !bridges.length) return undefined;
    return { clusters, bridges } as unknown as GraphRebuildSnapshot['discourseSpineSummary'];
}

function reviewStateRank(state: string): number {
    switch (state) {
        case 'proposed': return 0;
        case 'compiled_to_graph':
        case 'promoted_to_anchor':
        case 'accepted': return 1;
        case 'rejected':
        case 'muted': return 2;
        case 'ledger_only': return 3;
        default: return 4;
    }
}

function boundedNativePacketText(value: string, limit = NATIVE_COMPILER_PACKET_TEXT_LIMIT): string {
    const text = String(value || '');
    return text.length > limit ? `${text.slice(0, Math.max(0, limit - 3))}...` : text;
}

function boundedNativePacketList(values: readonly string[] | undefined, limit = NATIVE_COMPILER_PACKET_LIST_LIMIT): string[] {
    return (values || []).filter(Boolean).slice(0, limit);
}

function nativeCompilerDocumentCompilerSummary(
    snapshot: GraphRebuildSnapshot,
): GraphRebuildSnapshot['documentCompilerSummary'] {
    const hyperedges = snapshot.documentCompilerSummary?.hyperedges || [];
    if (!hyperedges.length) return undefined;
    return { hyperedges } as GraphRebuildSnapshot['documentCompilerSummary'];
}

function nativeCompilerEvidenceSidecar(
    snapshot: GraphRebuildSnapshot,
    documentCompilerSummary: GraphRebuildSnapshot['documentCompilerSummary'],
): GraphRebuildSnapshot['documentSidecarSummary'] {
    const evidenceSpans = snapshot.documentSidecarSummary?.evidenceSpans || [];
    const evidenceIds = nativeCompilerEvidenceSpanIds(documentCompilerSummary);
    if (!evidenceSpans.length || !evidenceIds.size) return undefined;
    const citedSpans = evidenceSpans.filter((span) => evidenceIds.has(span.id));
    if (!citedSpans.length) return undefined;
    return { evidenceSpans: citedSpans } as GraphRebuildSnapshot['documentSidecarSummary'];
}

function nativeCompilerEvidenceSpanIds(
    documentCompilerSummary: GraphRebuildSnapshot['documentCompilerSummary'],
): Set<string> {
    const ids = new Set<string>();
    for (const hyperedge of documentCompilerSummary?.hyperedges || []) {
        for (const id of hyperedge.evidenceSpanIds || []) ids.add(id);
        for (const id of hyperedge.provenance?.evidenceSpanIds || []) ids.add(id);
        for (const role of hyperedge.roles || []) {
            if (role.targetKind === 'evidence_span') ids.add(role.targetId);
        }
    }
    return ids;
}

export function graphRebuildNativeCompilerInputBytes(
    snapshot: GraphRebuildSnapshot,
): Record<string, number> {
    const families: Record<string, unknown> = {
        envelope: {
            schemaVersion: snapshot.schemaVersion,
            id: snapshot.id,
            source: snapshot.source,
            scopeKind: snapshot.scopeKind,
            scopeId: snapshot.scopeId,
            builtAt: snapshot.builtAt,
        },
        structuralRows: {
            noteIds: snapshot.noteIds,
            chunks: snapshot.chunks,
            mentions: snapshot.mentions,
            entityAnchors: snapshot.entityAnchors,
            nodes: snapshot.nodes,
            edges: snapshot.edges,
        },
        factRows: {
            relationships: snapshot.relationships,
            events: snapshot.events,
            temporalEdges: snapshot.temporalEdges,
            causalEdges: snapshot.causalEdges,
            memoryState: snapshot.memoryState,
        },
        admittedTargets: snapshot.embeddingTargets,
        calendarRegistrySummary: snapshot.calendarRegistrySummary,
        documentSidecarSummary: snapshot.documentSidecarSummary,
        documentReviewSummary: snapshot.documentReviewSummary,
        documentCompilerSummary: snapshot.documentCompilerSummary,
        discourseSpineSummary: snapshot.discourseSpineSummary,
        counters: snapshot.counters,
    };
    return Object.fromEntries(Object.entries(families).map(([family, value]) => [
        family,
        value === undefined ? 0 : strToU8(JSON.stringify(value)).byteLength,
    ]));
}

function updateEmbeddingTargetCounters(
    snapshot: GraphRebuildSnapshot,
    plan: GraphRebuildEmbeddingTargetPlan,
    queuedCount: number,
): void {
    snapshot.counters.embeddingTargets = snapshot.embeddingTargets.length;
    snapshot.counters.embeddingTargetCandidates = plan.candidateCount;
    snapshot.counters.embeddingQueuedTargets = queuedCount;
    snapshot.counters.embeddingTargetDeferred = plan.deferredCount;
    snapshot.counters.embeddingSchedulerDeferredTargets = plan.schedulerDeferredCount;
    snapshot.counters.embeddingPolicyDeferredTargets = plan.policyDeferredCount;
}

export function attachInteractiveAtlasPacketForSnapshotTargets(
    snapshot: GraphRebuildSnapshot,
    previousSnapshot?: GraphRebuildSnapshot | null,
): boolean {
    const previousPacket = previousSnapshot?.atlasPacket;
    const seed = previousPacket && sameEmbeddingTargetIds(previousSnapshot.embeddingTargets, snapshot.embeddingTargets)
        ? graphAtlasPacketSeedForSnapshot(snapshot, previousPacket)
        : graphAtlasPacketSeedForSnapshot(snapshot);
    snapshot.atlasPacket = reconcileNativeAtlasPacketForTargets(snapshot, seed);
    return atlasPacketMatchesSnapshotTargets(snapshot);
}

function graphAtlasPacketSeedForSnapshot(
    snapshot: GraphRebuildSnapshot,
    packet?: GraphAtlasPacket,
): GraphAtlasPacket {
    const normalized = normalizeNativeAtlasPacketSourceContract(packet);
    const objects = mergeAtlasPacketObjects(
        normalized?.objects || [],
        interactiveDiagnosticAtlasObjects(snapshot),
    );
    return {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: snapshot.id,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        sourceContract: {
            authority: GRAPH_ATLAS_PACKET_AUTHORITY,
            identityAuthority: GRAPH_ATLAS_IDENTITY_AUTHORITY,
            vectorContract: normalized?.sourceContract.vectorContract || 'vectors-missing',
            tsGraphBuilderRole: GRAPH_ATLAS_BUILDER_ROLE,
        },
        objects,
        manifoldTargets: normalized?.manifoldTargets || [],
        counters: normalized?.counters || {
            objects: 0,
            manifoldTargets: 0,
            registryEntities: snapshot.nodes.length,
            evidenceAnchors: snapshot.entityAnchors.length,
            modelVectors: 0,
            families: [],
        },
    };
}

const INTERACTIVE_PACKET_REVIEW_OBJECT_LIMIT = 64;
const INTERACTIVE_PACKET_DISCOURSE_OBJECT_LIMIT = 96;

function mergeAtlasPacketObjects(
    base: GraphAtlasObject[],
    extra: GraphAtlasObject[],
): GraphAtlasObject[] {
    const merged = new Map(base.map((object) => [object.id, object]));
    for (const object of extra) merged.set(object.id, object);
    return [...merged.values()];
}

function interactiveDiagnosticAtlasObjects(snapshot: GraphRebuildSnapshot): GraphAtlasObject[] {
    return [
        ...interactiveReviewAtlasObjects(snapshot),
        ...interactiveDiscourseAtlasObjects(snapshot),
    ];
}

function interactiveReviewAtlasObjects(snapshot: GraphRebuildSnapshot): GraphAtlasObject[] {
    return (snapshot.documentReviewSummary?.rows || [])
        .filter((row) => row.state !== 'ledger_only')
        .slice(0, INTERACTIVE_PACKET_REVIEW_OBJECT_LIMIT)
        .map((row): GraphAtlasObject => ({
            id: `review:${row.id}`,
            family: 'review',
            status: reviewStateToAtlasStatus(row.state),
            kind: row.objectKind || 'review',
            label: row.title || row.objectId || row.id,
            styleKey: 'rankStatus',
            lane: 'review_state',
            structuralRole: 'context',
            stateContextKind: row.state,
            noteIds: row.noteId ? [row.noteId] : [],
            chunkIds: [],
            anchorIds: [],
            evidenceIds: row.evidenceSpanIds || [],
            sourceIds: [row.id, row.objectId].filter(Boolean),
            targetIds: [...new Set([...(row.relatedObjectIds || []), row.objectId].filter(Boolean))],
        }));
}

function interactiveDiscourseAtlasObjects(snapshot: GraphRebuildSnapshot): GraphAtlasObject[] {
    const bridges = (snapshot.discourseSpineSummary?.bridges || [])
        .slice(0, INTERACTIVE_PACKET_DISCOURSE_OBJECT_LIMIT)
        .map((bridge): GraphAtlasObject => ({
            id: `discourse:${bridge.id}`,
            family: 'discourse',
            status: bridge.status === 'proposed' ? 'proposed' : bridge.status,
            kind: `discourse_${bridge.kind}`,
            label: bridge.label || bridge.id,
            styleKey: 'communication',
            lane: 'discourse_bridge',
            structuralRole: 'bridge',
            noteIds: [],
            chunkIds: discourseChunkIds(bridge.evidenceTargetIds),
            anchorIds: [],
            evidenceIds: bridge.evidenceTargetIds || [],
            sourceIds: [bridge.id],
            targetIds: [bridge.sourceTargetId, bridge.targetTargetId, ...(bridge.evidenceTargetIds || [])].filter(Boolean),
        }));
    if (bridges.length) return bridges;
    const clusters = (snapshot.discourseSpineSummary?.clusters || [])
        .slice(0, INTERACTIVE_PACKET_DISCOURSE_OBJECT_LIMIT)
        .map((cluster): GraphAtlasObject => ({
            id: `discourse:${cluster.id}`,
            family: 'discourse',
            status: 'proposed',
            kind: `discourse_${cluster.kind}`,
            label: cluster.label || cluster.id,
            styleKey: 'communication',
            lane: 'discourse_cluster',
            structuralRole: 'bridge',
            noteIds: [],
            chunkIds: discourseChunkIds(cluster.targetIds),
            anchorIds: [],
            evidenceIds: cluster.targetIds || [],
            sourceIds: [cluster.id],
            targetIds: cluster.targetIds || [],
        }));
    if (clusters.length) return clusters;
    return snapshot.chunks.slice(1, INTERACTIVE_PACKET_DISCOURSE_OBJECT_LIMIT + 1)
        .map((chunk, index): GraphAtlasObject => {
            const previous = snapshot.chunks[index];
            const evidenceIds = [`embed:chunk:${previous.id}`, `embed:chunk:${chunk.id}`];
            return {
                id: `discourse:continuity:${previous.id}->${chunk.id}`,
                family: 'discourse',
                status: 'proposed',
                kind: 'discourse_continuity',
                label: `Continuity ${previous.ordinal}->${chunk.ordinal}`,
                styleKey: 'communication',
                lane: 'discourse_continuity',
                structuralRole: 'bridge',
                noteIds: [...new Set([previous.noteId, chunk.noteId].filter(Boolean))],
                chunkIds: [previous.id, chunk.id],
                anchorIds: [],
                evidenceIds,
                sourceIds: [`continuity:${previous.id}->${chunk.id}`],
                targetIds: evidenceIds,
            };
        });
}

function discourseChunkIds(targetIds: string[]): string[] {
    return [...new Set((targetIds || [])
        .map((targetId) => targetId.match(/^embed:chunk:(.+)$/)?.[1] || '')
        .filter(Boolean))];
}

function reviewStateToAtlasStatus(state: string): GraphAtlasObjectStatus {
    if (state === 'compiled_to_graph') return 'compiledToGraph';
    if (state === 'promoted_to_anchor') return 'promotedToAnchor';
    if (state === 'ledger_only') return 'ledgerOnly';
    if (state === 'accepted' || state === 'proposed' || state === 'rejected' || state === 'muted') return state;
    return 'review';
}

function sameEmbeddingTargetIds(
    left: GraphRebuildEmbeddingTarget[] | undefined,
    right: GraphRebuildEmbeddingTarget[],
): boolean {
    if (!left || left.length !== right.length) return false;
    const ids = new Set(left.map((target) => target.id));
    return right.every((target) => ids.has(target.id));
}

function atlasPacketMatchesSnapshotTargets(snapshot: GraphRebuildSnapshot): boolean {
    const packet = snapshot.atlasPacket;
    if (!packet || packet.snapshotId !== snapshot.id || packet.scopeId !== snapshot.scopeId) return false;
    if (packet.sourceContract.authority !== GRAPH_ATLAS_PACKET_AUTHORITY
        || packet.sourceContract.identityAuthority !== GRAPH_ATLAS_IDENTITY_AUTHORITY
        || packet.sourceContract.tsGraphBuilderRole !== GRAPH_ATLAS_BUILDER_ROLE) {
        return false;
    }
    if (packet.counters.manifoldTargets !== snapshot.embeddingTargets.length
        || packet.manifoldTargets.length !== snapshot.embeddingTargets.length) {
        return false;
    }
    const packetTargetIds = new Set(packet.manifoldTargets.map((target) => target.id));
    return snapshot.embeddingTargets.every((target) => packetTargetIds.has(target.id));
}

function reuseInteractivePrimarySnapshotIdentity(
    snapshot: GraphRebuildSnapshot,
    previousSnapshot?: GraphRebuildSnapshot | null,
): boolean {
    if (!previousSnapshot?.authorityContract || !snapshot.authorityContract) return false;
    if (JSON.stringify(previousSnapshot.interactiveRunAuthority)
        !== JSON.stringify(snapshot.interactiveRunAuthority)) return false;
    if (previousSnapshot.scopeId !== snapshot.scopeId) return false;
    if (previousSnapshot.authorityContract.contentHash !== snapshot.authorityContract.contentHash) return false;
    if (JSON.stringify(previousSnapshot.authorityContract.counts) !== JSON.stringify(snapshot.authorityContract.counts)) {
        return false;
    }
    snapshot.id = previousSnapshot.id;
    snapshot.builtAt = previousSnapshot.builtAt;
    if (snapshot.atlasPacket) {
        snapshot.atlasPacket = {
            ...snapshot.atlasPacket,
            snapshotId: snapshot.id,
            builtAt: snapshot.builtAt,
        };
    }
    sealGraphSnapshotAuthority(snapshot);
    return true;
}

export function graphDocumentSemanticIdentity(
    noteTexts: Record<string, string>,
    entities: RegisteredEntity[],
): string {
    const documents = Object.entries(noteTexts)
        .sort(([left], [right]) => left.localeCompare(right));
    const semanticEntities = entities
        .map((entity) => ({
            id: entity.id,
            label: entity.label,
            aliases: [...(entity.aliases || [])].sort(),
            kind: entity.kind,
        }))
        .sort((left, right) => left.id.localeCompare(right.id));
    return graphSnapshotContentHash(JSON.stringify(graphSnapshotStableContentValue({
        schemaVersion: 'phoenix-document-semantics-input/v1',
        documents,
        entities: semanticEntities,
    })));
}

function trimOldestMapEntries<K, V>(values: Map<K, V>, limit: number): void {
    while (values.size > limit) {
        const oldest = values.keys().next();
        if (oldest.done) return;
        values.delete(oldest.value);
    }
}

function refreshTargetDerivedReadModels(snapshot: GraphRebuildSnapshot): void {
    // Temporary containment: native target replacement must not hollow the
    // TypeScript compatibility summaries that still feed desktop diagnostics.
    void snapshot;
}

function anchorSpanStillMatches(
    noteId: string,
    start: number,
    end: number,
    surface: string,
    noteTexts?: Record<string, string>,
): boolean {
    if (!noteTexts) return true;
    if (!Object.prototype.hasOwnProperty.call(noteTexts, noteId)) return false;
    const text = noteTexts[noteId] || '';
    if (start < 0 || end > text.length || end <= start) return false;
    return normalizeSurface(text.slice(start, end)).toLocaleLowerCase() === normalizeSurface(surface).toLocaleLowerCase();
}

function occurrenceSourceFromAnchor(source: string): EntityOccurrence['source'] {
    if (source === 'manual_tag' || source === 'dictionary_match' || source === 'machine_evidence' || source === 'machine_suggestion') {
        return source;
    }
    return 'machine_suggestion';
}

function entitySurfaces(entity: RegisteredEntity): string[] {
    const seen = new Set<string>();
    const surfaces: string[] = [];
    for (const value of [entity.label, ...(entity.aliases || [])]) {
        const surface = normalizeSurface(value);
        if (surface.length < 2) continue;
        const key = surface.toLocaleLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        surfaces.push(surface);
    }
    return surfaces.sort((left, right) => right.length - left.length || left.localeCompare(right));
}

function graphRebuildOccurrence(
    noteId: string,
    text: string,
    entity: RegisteredEntity,
    start: number,
    end: number,
    now: number,
): EntityOccurrence {
    const surface = text.slice(start, end);
    return {
        id: `${noteId}:${entity.id}:${start}:${end}:dictionary_match`,
        noteId,
        entityId: entity.id,
        entityLabel: entity.label,
        entityKind: entity.kind,
        targetNoteId: entity.firstNote || undefined,
        sourceStart: start,
        sourceEnd: end,
        surface,
        source: 'dictionary_match',
        confidence: 0.82,
        excerpt: buildGraphRebuildExcerpt(text, start, end),
        generation: now,
        createdAt: now,
        updatedAt: now,
    };
}

function normalizeSurface(value: string): string {
    return String(value || '').trim().replace(/\s+/g, ' ');
}

function isEntityBoundary(text: string, index: number): boolean {
    if (index < 0 || index >= text.length) return true;
    return !isEntityWordChar(text[index]);
}

function isEntityWordChar(char: string): boolean {
    const code = char.charCodeAt(0);
    if (code >= 48 && code <= 57) return true;
    if (code >= 65 && code <= 90) return true;
    if (code >= 97 && code <= 122) return true;
    if (char === '_' || char === '\'' || char === '-') return true;
    return /[\p{L}\p{N}]/u.test(char);
}

function buildGraphRebuildExcerpt(text: string, start: number, end: number): string {
    const radius = 90;
    const from = Math.max(0, start - radius);
    const to = Math.min(text.length, end + radius);
    const prefix = from > 0 ? '...' : '';
    const suffix = to < text.length ? '...' : '';
    return `${prefix}${text.slice(from, to).replace(/\s+/g, ' ').trim()}${suffix}`;
}

export function graphRebuildSnapshotToScopedDocument(
    snapshot: GraphRebuildSnapshot,
    documentKey = SNAPSHOT_DOCUMENT_KEY,
): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${snapshot.scopeId}:${documentKey}`,
        scopeFolderId: snapshot.scopeId,
        narrativeId: snapshot.scopeKind === 'narrative' ? snapshot.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey,
        payload: encodeGraphRebuildSnapshotPayload(graphRebuildSnapshotPersistenceView(snapshot)),
        createdAt: snapshot.builtAt || now,
        updatedAt: now,
    };
}

export interface GraphRebuildContentBlobEntry {
    field: GraphRebuildContentBlobField;
    documentKey: string;
    payload: string;
    payloadStats: GraphRebuildSnapshotDocumentPayloadStats;
    ref: NonNullable<GraphRebuildContentManifest['refs'][GraphRebuildContentBlobField]>;
}

const SNAPSHOT_CONTENT_BLOB_FIELDS: GraphRebuildContentBlobField[] = [
    'sourceRows',
    'renderRows',
    'evidenceTargetRegistryPage',
    'embeddingTargets',
    'embeddingTargetPlan',
    'embeddingGraphPostProcess',
    'graphModelV2',
    'semanticCandidateSummary',
    'manifoldSpecializationSummary',
    'storyContinuity',
    'atlasPacket',
];

export function graphRebuildSnapshotContentBlobDocuments(
    snapshot: GraphRebuildSnapshot,
    entries = graphRebuildSnapshotContentBlobEntries(snapshot),
): StoreScopedDocument[] {
    const now = Date.now();
    return entries.map((entry) => ({
        id: `${GRAPH_REBUILD_NAMESPACE}:${snapshot.scopeId}:${entry.documentKey}`,
        scopeFolderId: snapshot.scopeId,
        narrativeId: snapshot.scopeKind === 'narrative' ? snapshot.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: entry.documentKey,
        payload: entry.payload,
        createdAt: snapshot.builtAt || now,
        updatedAt: now,
    }));
}

function missingContentBlobDocumentsForManifest(
    documents: StoreScopedDocument[],
    entries: GraphRebuildContentBlobEntry[],
    manifest?: GraphRebuildContentManifest,
): StoreScopedDocument[] {
    const refs = manifest?.refs || {};
    return documents.filter((_, index) => {
        const entry = entries[index];
        const ref = refs[entry.field];
        return !ref || ref.hash !== entry.ref.hash || ref.documentKey !== entry.documentKey;
    });
}

export function graphRebuildSnapshotContentManifest(
    snapshot: GraphRebuildSnapshot,
    entries = graphRebuildSnapshotContentBlobEntries(snapshot),
): GraphRebuildContentManifest | undefined {
    if (!entries.length) return undefined;
    const refs: GraphRebuildContentManifest['refs'] = {};
    for (const entry of entries) refs[entry.field] = entry.ref;
    return {
        schemaVersion: 'phoenix-graph-rebuild-content-manifest/v1',
        snapshotId: snapshot.id,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        refs,
    };
}

export function graphRebuildSnapshotContentBlobEntries(
    snapshot: GraphRebuildSnapshot,
): GraphRebuildContentBlobEntry[] {
    const entries: GraphRebuildContentBlobEntry[] = [];
    const createdAt = snapshot.builtAt;
    for (const field of SNAPSHOT_CONTENT_BLOB_FIELDS) {
        const value = snapshotContentBlobValue(snapshot, field);
        if (isEmptySnapshotContentBlobValue(value)) continue;
        const raw = JSON.stringify(value);
        const hash = graphSnapshotContentHash(JSON.stringify(graphSnapshotStableContentValue(value)));
        const documentKey = `${SNAPSHOT_CONTENT_BLOB_PREFIX}:${field}:${hash}`;
        const payload: GraphRebuildContentBlobPayload = {
            schemaVersion: CONTENT_BLOB_SCHEMA_VERSION,
            scopeId: snapshot.scopeId,
            field,
            hash,
            value,
        };
        const encoded = encodeGraphRebuildJsonPayloadWithStats(payload, CONTENT_BLOB_SCHEMA_VERSION);
        entries.push({
            field,
            documentKey,
            payload: encoded.payload,
            payloadStats: encoded.stats,
            ref: {
                schemaVersion: 'phoenix-graph-rebuild-content-blob-ref/v1',
                field,
                hash,
                documentKey,
                sourceSchemaVersion: snapshotContentBlobSourceSchemaVersion(field, value),
                rawChars: raw.length,
                payloadChars: encoded.payload.length,
                compressedBytes: encoded.stats.compressedBytes,
                itemCount: snapshotContentBlobItemCount(value),
                createdAt,
            },
        });
    }
    return entries;
}

export function graphRebuildSnapshotPersistenceView(
    snapshot: GraphRebuildSnapshot,
    contentBlobEntries = graphRebuildSnapshotContentBlobEntries(snapshot),
): GraphRebuildSnapshot {
    const persisted = { ...snapshot };
    const contentManifest = graphRebuildSnapshotContentManifest(snapshot, contentBlobEntries)
        || snapshot.contentManifest;
    if (contentManifest) persisted.contentManifest = contentManifest;
    persisted.chunks = [];
    persisted.mentions = [];
    persisted.entityAnchors = [];
    persisted.relationships = [];
    persisted.events = [];
    persisted.episodes = [];
    persisted.chunkSemanticBridges = [];
    delete persisted.crossDocumentBridgeCertificate;
    persisted.episodeConnections = [];
    persisted.episodeProjectionEdges = [];
    persisted.temporalEdges = [];
    persisted.causalEdges = [];
    persisted.memoryState = [];
    persisted.memoryGovernanceCandidates = [];
    delete persisted.storyContinuity;
    persisted.embeddingTargets = [];
    persisted.projectionRefs = [];
    persisted.nodes = [];
    persisted.edges = [];
    delete persisted.evidenceTargetRegistryPage;
    delete persisted.embeddingTargetPlan;
    delete persisted.embeddingGraphPostProcess;
    delete persisted.structuralPostProcess;
    delete persisted.projectedUiGraph;
    delete persisted.graphModelV2;
    delete persisted.graphAwareLinkSuggestions;
    delete persisted.entityLinkSuggestions;
    delete persisted.shadowLinkSuggestions;
    delete persisted.finalLinkPatchLog;
    delete persisted.semanticCandidateSummary;
    delete persisted.manifoldSpecializationSummary;
    delete persisted.atlasPacket;
    delete persisted.documentSidecarSummary;
    delete persisted.documentSemanticSummary;
    delete persisted.documentReviewSummary;
    delete persisted.documentCompilerSummary;
    delete (persisted as GraphRebuildSnapshot & { atlasDebugSummaries?: unknown }).atlasDebugSummaries;
    delete persisted.graphTruthCommitLedger;
    delete persisted.promotionVerdictCertificate;
    delete persisted.reviewAdjudicationCertificate;
    delete persisted.calendarRegistrySummary;
    if (snapshot.graphCompiler && snapshot.graphModelV2) {
        delete persisted.graphCompiler;
    }
    delete persisted.hopfResonanceSpace;
    delete persisted.memoryGraphRagBridgeSummary;
    delete persisted.discourseSpineSummary;
    delete persisted.discourseBridgeCandidateSummary;
    delete persisted.discourseBridgeAdjudicationSummary;
    delete persisted.discourseEvalLedgerSummary;
    delete persisted.discoursePromotionSurfaceSummary;
    delete persisted.discourseCompilerOverlaySummary;
    delete persisted.semanticTaskSummary;
    delete persisted.semanticRerankSummary;
    delete persisted.semanticAdjudicationSummary;
    delete persisted.semanticEvalLedgerSummary;
    return persisted;
}

export function graphGenerationSnapshotShell(
    snapshot: GraphRebuildSnapshot,
    receipt: GraphGenerationReceiptV2,
): GraphRebuildSnapshot {
    if (!receipt.releaseAuthorized
        || snapshot.id !== receipt.snapshotId
        || snapshot.scopeId !== receipt.scopeId
        || snapshot.authorityContract?.contentHash !== receipt.authority.contentHash) {
        throw new Error('Graph generation is not authorized for compact-shell release.');
    }
    const shell = graphRebuildSnapshotPersistenceView(snapshot, []);
    shell.generationReceiptId = receipt.receiptId;
    shell.generationDigestSha256 = receipt.digestSha256;
    assertGraphCanvasBootSnapshotShell(shell);
    return shell;
}

function assertGenerationContentLeaseIdentity(
    expected: GraphRebuildSnapshot,
    candidate: GraphRebuildSnapshot,
): void {
    const expectedAuthority = expected.authorityContract;
    const candidateAuthority = candidate.authorityContract;
    if (candidate.id !== expected.id
        || candidate.scopeId !== expected.scopeId
        || candidateAuthority?.contentHash !== expectedAuthority?.contentHash
        || candidate.interactiveRunAuthority?.inputIdentity
            !== expected.interactiveRunAuthority?.inputIdentity
        || candidate.contentManifest?.snapshotId !== expected.contentManifest?.snapshotId
        || candidate.contentManifest?.scopeId !== expected.contentManifest?.scopeId) {
        throw new Error(
            `PHX_GRAPH_CONTENT_LEASE_IDENTITY_DRIFT: durable content does not match generation ${expected.id}.`,
        );
    }
}

export function verifiedForceSnapshotShell(
    snapshot: GraphRebuildSnapshot,
    receipt: GraphGenerationReceiptV2,
): GraphRebuildSnapshot {
    const durable = snapshot.interactiveRunAuthority?.durable;
    const analysis = receipt.artifacts.analysisRun;
    if (!durable || analysis.status !== 'ready' || analysis.digest !== durable.manifestId
        || snapshot.id !== receipt.snapshotId || snapshot.scopeId !== receipt.scopeId
        || snapshot.authorityContract?.contentHash !== receipt.authority.contentHash) {
        throw new Error('Verified FORCE authority requires sealed snapshot and native analysis parity.');
    }
    const shell = graphRebuildSnapshotPersistenceView(snapshot, []);
    shell.generationReceiptId = receipt.receiptId;
    shell.generationDigestSha256 = receipt.digestSha256;
    assertGraphCanvasBootSnapshotShell(shell);
    return shell;
}

export function scopedDocumentToGraphRebuildContentBlob(
    document: StoreScopedDocument,
): GraphRebuildContentBlobPayload | null {
    try {
        const parsed = decodeGraphRebuildJsonPayload<GraphRebuildContentBlobPayload>(document.payload);
        return parsed?.schemaVersion === CONTENT_BLOB_SCHEMA_VERSION ? parsed : null;
    } catch {
        return null;
    }
}

function encodeGraphRebuildSnapshotPayload(snapshot: GraphRebuildSnapshot): string {
    return encodeGraphRebuildJsonPayload(snapshot, snapshot.schemaVersion);
}

function encodeGraphRebuildJsonPayload(value: unknown, sourceSchemaVersion: string): string {
    return encodeGraphRebuildJsonPayloadWithStats(value, sourceSchemaVersion).payload;
}

function encodeGraphRebuildJsonPayloadWithStats(
    value: unknown,
    sourceSchemaVersion: string,
): { payload: string; stats: GraphRebuildSnapshotDocumentPayloadStats } {
    const raw = JSON.stringify(value);
    if (raw.length < SNAPSHOT_COMPRESSION_MIN_CHARS) return rawGraphRebuildPayload(raw);
    try {
        const compressed = gzipSync(strToU8(raw), { level: 1 });
        const payload = bytesToBase64(compressed);
        const envelope: CompressedGraphRebuildJsonPayload = {
            schemaVersion: COMPRESSED_JSON_SCHEMA_VERSION,
            sourceSchemaVersion,
            encoding: 'gzip+base64',
            rawChars: raw.length,
            compressedBytes: compressed.byteLength,
            payload,
        };
        const encoded = JSON.stringify(envelope);
        return encoded.length < raw.length
            ? {
                payload: encoded,
                stats: {
                    rawChars: raw.length,
                    compressedBytes: compressed.byteLength,
                    savedChars: Math.max(0, raw.length - encoded.length),
                    ratioPct: raw.length > 0 ? Math.round((encoded.length / raw.length) * 100) : 100,
                },
            }
            : rawGraphRebuildPayload(raw);
    } catch {
        return rawGraphRebuildPayload(raw);
    }
}

function rawGraphRebuildPayload(payload: string): {
    payload: string;
    stats: GraphRebuildSnapshotDocumentPayloadStats;
} {
    return {
        payload,
        stats: {
            rawChars: payload.length,
            compressedBytes: payload.length,
            savedChars: 0,
            ratioPct: 100,
        },
    };
}

function decodeGraphRebuildSnapshotPayload(payload: string): GraphRebuildSnapshot | null {
    return decodeGraphRebuildJsonPayload<GraphRebuildSnapshot>(payload);
}

function decodeGraphRebuildJsonPayload<T>(payload: string): T {
    const parsed = JSON.parse(payload) as T | CompressedGraphRebuildJsonPayload | CompressedGraphRebuildSnapshotPayload;
    if (!isCompressedGraphRebuildJsonPayload(parsed) && !isCompressedGraphRebuildSnapshotPayload(parsed)) {
        return parsed as T;
    }
    const bytes = base64ToBytes(parsed.payload);
    return JSON.parse(strFromU8(gunzipSync(bytes))) as T;
}

export function decodeNativeGraphCompilerSidecar(
    sidecar: NativeGraphCompilerSidecar | null | undefined,
): NativeGraphCompilerDecodedSidecar | null {
    if (!sidecar) return null;
    const raw = sidecar as NativeGraphCompilerSidecar & {
        fact_graph?: GraphCompilerDualWriteSidecar['factGraph'];
        projected_ui_graph?: GraphCompilerDualWriteSidecar['projectedUiGraph'];
        fact_graph_payload?: CompressedGraphCompilerFactGraphPayload;
        atlas_seed_payload?: CompressedNativeAtlasSeedPayload;
        originating_families?: NativeEmbeddingTargetOriginCount[];
    };
    const factGraph = sidecar.factGraph || raw.fact_graph;
    const compressedAtlasSeed = sidecar.atlasSeedPayload || raw.atlas_seed_payload;
    const atlasSeed = isCompressedNativeAtlasSeedPayload(compressedAtlasSeed)
        ? JSON.parse(strFromU8(gunzipSync(base64ToBytes(compressedAtlasSeed.payload)))) as NativeAtlasSeed
        : undefined;
    const embeddingTargets = atlasSeed?.embeddingTargets || sidecar.embeddingTargets || [];
    const atlasPacket = normalizeNativeAtlasPacketSourceContract(atlasSeed?.atlasPacket || sidecar.atlasPacket);
    const originatingFamilies = atlasSeed?.originatingFamilies
        || sidecar.originatingFamilies
        || raw.originating_families
        || [];
    const decodedFields = { ...sidecar };
    delete decodedFields.factGraphPayload;
    delete decodedFields.atlasSeedPayload;
    if (factGraph) {
        return {
            ...decodedFields,
            factGraph,
            projectedUiGraph: sidecar.projectedUiGraph || raw.projected_ui_graph,
            receipts: sidecar.receipts || factGraph.receipts,
            atlasPacket,
            embeddingTargets,
            originatingFamilies,
        } as NativeGraphCompilerDecodedSidecar;
    }
    const compressed = sidecar.factGraphPayload || raw.fact_graph_payload;
    if (!isCompressedGraphCompilerFactGraphPayload(compressed)) {
        return atlasPacket ? {
            ...decodedFields,
            atlasPacket,
            embeddingTargets,
            originatingFamilies,
        } as NativeGraphCompilerDecodedSidecar : null;
    }
    const decodedFactGraph = JSON.parse(strFromU8(gunzipSync(base64ToBytes(compressed.payload))));
    return {
        ...decodedFields,
        factGraph: decodedFactGraph,
        projectedUiGraph: sidecar.projectedUiGraph || raw.projected_ui_graph,
        receipts: sidecar.receipts || decodedFactGraph.receipts,
        atlasPacket,
        embeddingTargets,
        originatingFamilies,
    } as NativeGraphCompilerDecodedSidecar;
}

function isUnsupportedStoreCommand(error: unknown, command: string): boolean {
    const message = error instanceof Error ? error.message : String(error);
    return message.includes(`unsupported store command: ${command}`);
}

function isCompressedGraphRebuildJsonPayload(value: unknown): value is CompressedGraphRebuildJsonPayload {
    const record = value && typeof value === 'object' ? value as Partial<CompressedGraphRebuildJsonPayload> : null;
    return record?.schemaVersion === COMPRESSED_JSON_SCHEMA_VERSION
        && record.encoding === 'gzip+base64'
        && typeof record.payload === 'string';
}

function isCompressedGraphRebuildSnapshotPayload(value: unknown): value is CompressedGraphRebuildSnapshotPayload {
    const record = value && typeof value === 'object' ? value as Partial<CompressedGraphRebuildSnapshotPayload> : null;
    return record?.schemaVersion === COMPRESSED_SNAPSHOT_SCHEMA_VERSION
        && record.encoding === 'gzip+base64'
        && typeof record.payload === 'string';
}

function isCompressedGraphCompilerFactGraphPayload(value: unknown): value is CompressedGraphCompilerFactGraphPayload {
    const record = value && typeof value === 'object' ? value as Partial<CompressedGraphCompilerFactGraphPayload> : null;
    return record?.schemaVersion === 'phoenix-graph-compiler-payload/gzip-base64/v1'
        && record.encoding === 'gzip+base64'
        && typeof record.payload === 'string';
}

export function decodeDocumentSemanticSummary(value: unknown): unknown {
    if (!isCompressedDocumentSemanticPayload(value)) return value;
    return JSON.parse(strFromU8(gunzipSync(base64ToBytes(value.payload))));
}

function isCompressedDocumentSemanticPayload(value: unknown): value is CompressedDocumentSemanticPayload {
    const record = value && typeof value === 'object' ? value as Partial<CompressedDocumentSemanticPayload> : null;
    return record?.schemaVersion === COMPRESSED_DOCUMENT_SEMANTIC_SCHEMA_VERSION
        && record.encoding === 'gzip+base64'
        && typeof record.payload === 'string';
}

export function graphRebuildSnapshotDocumentPayloadStats(payload: string): GraphRebuildSnapshotDocumentPayloadStats {
    try {
        const parsed = JSON.parse(payload) as unknown;
        if (isCompressedGraphRebuildJsonPayload(parsed) || isCompressedGraphRebuildSnapshotPayload(parsed)) {
            const rawChars = Math.max(0, Math.round(parsed.rawChars || 0));
            const compressedBytes = Math.max(0, Math.round(parsed.compressedBytes || 0));
            const savedChars = Math.max(0, rawChars - payload.length);
            return {
                rawChars,
                compressedBytes,
                savedChars,
                ratioPct: rawChars > 0 ? Math.round((payload.length / rawChars) * 100) : 100,
            };
        }
    } catch {
        // Fall through to raw payload stats.
    }
    return {
        rawChars: payload.length,
        compressedBytes: payload.length,
        savedChars: 0,
        ratioPct: 100,
    };
}

function bytesToBase64(bytes: Uint8Array): string {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += BASE64_CHUNK_SIZE) {
        binary += strFromU8(bytes.subarray(offset, offset + BASE64_CHUNK_SIZE), true);
    }
    return btoa(binary);
}

function base64ToBytes(encoded: string): Uint8Array {
    return strToU8(atob(encoded), true);
}

export function graphModelV2OverGraphExportToScopedDocument(snapshot: GraphRebuildSnapshot): StoreScopedDocument | null {
    if (!snapshot.graphModelV2) return null;
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${snapshot.scopeId}:${GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY}`,
        scopeFolderId: snapshot.scopeId,
        narrativeId: snapshot.scopeKind === 'narrative' ? snapshot.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY,
        payload: encodeGraphRebuildJsonPayload(
            buildGraphModelV2OverGraphExport(snapshot),
            'phoenix-graph-model-v2-overgraph/v1',
        ),
        createdAt: snapshot.builtAt || now,
        updatedAt: now,
    };
}

export function graphRebuildSnapshotPayloadCounters(
    snapshot: GraphRebuildSnapshot,
    primaryPayloadChars: number,
    overGraphPayloadChars = 0,
    primaryPayloadStats?: GraphRebuildSnapshotDocumentPayloadStats,
    overGraphPayloadStats?: GraphRebuildSnapshotDocumentPayloadStats,
): Record<string, number> {
    const primaryRawPayloadChars = primaryPayloadStats?.rawChars || primaryPayloadChars;
    const overGraphRawPayloadChars = overGraphPayloadStats?.rawChars || overGraphPayloadChars;
    const counters: Record<string, number> = {
        snapshotPrimaryPayloadChars: primaryPayloadChars,
        snapshotPrimaryRawPayloadChars: primaryRawPayloadChars,
        snapshotPrimaryCompressedBytes: primaryPayloadStats?.compressedBytes || primaryPayloadChars,
        snapshotCompressionSavedChars: primaryPayloadStats?.savedChars || 0,
        snapshotCompressionRatioPct: primaryPayloadStats?.ratioPct || 100,
        snapshotOverGraphPayloadChars: overGraphPayloadChars,
        snapshotOverGraphRawPayloadChars: overGraphRawPayloadChars,
        snapshotOverGraphCompressedBytes: overGraphPayloadStats?.compressedBytes || overGraphPayloadChars,
        snapshotOverGraphCompressionSavedChars: overGraphPayloadStats?.savedChars || 0,
        snapshotOverGraphCompressionRatioPct: overGraphPayloadStats?.ratioPct || 100,
        snapshotTotalScopedPayloadChars: primaryPayloadChars + overGraphPayloadChars,
        snapshotTotalScopedRawPayloadChars: primaryRawPayloadChars + overGraphRawPayloadChars,
    };
    for (const [counterKey, snapshotKey] of SNAPSHOT_PAYLOAD_PROFILE_FIELDS) {
        const chars = jsonPayloadChars((snapshot as unknown as Record<string, unknown>)[snapshotKey]);
        if (chars > 0) counters[counterKey] = chars;
    }
    return counters;
}

function isCompressedNativeAtlasSeedPayload(value: unknown): value is CompressedNativeAtlasSeedPayload {
    const record = value && typeof value === 'object' ? value as Partial<CompressedNativeAtlasSeedPayload> : null;
    return record?.schemaVersion === 'phoenix-atlas-seed-payload/gzip-base64/v1'
        && record.encoding === 'gzip+base64'
        && typeof record.payload === 'string';
}

function graphRebuildContentBlobPayloadCounters(entries: GraphRebuildContentBlobEntry[]): Record<string, number> {
    if (!entries.length) return {};
    const counters: Record<string, number> = {
        snapshotContentBlobDocuments: entries.length,
        snapshotContentBlobPayloadChars: entries.reduce((sum, entry) => sum + entry.payload.length, 0),
    };
    let rawChars = 0;
    let compressedBytes = 0;
    for (const entry of entries) {
        const stats = entry.payloadStats;
        rawChars += stats.rawChars;
        compressedBytes += stats.compressedBytes;
        counters[`snapshotContentBlob.${entry.field}.payloadChars`] = entry.ref.payloadChars;
        counters[`snapshotContentBlob.${entry.field}.rawPayloadChars`] = stats.rawChars;
        counters[`snapshotContentBlob.${entry.field}.rawValueChars`] = entry.ref.rawChars;
        counters[`snapshotContentBlob.${entry.field}.compressedBytes`] = stats.compressedBytes;
        if (entry.ref.itemCount !== undefined) {
            counters[`snapshotContentBlob.${entry.field}.items`] = entry.ref.itemCount;
        }
    }
    counters['snapshotContentBlobRawPayloadChars'] = rawChars;
    counters['snapshotContentBlobCompressedBytes'] = compressedBytes;
    return counters;
}

export function scopedDocumentToGraphRebuildSnapshot(document: StoreScopedDocument): GraphRebuildSnapshot | null {
    try {
        const parsed = decodeGraphRebuildSnapshotPayload(document.payload);
        return parsed?.schemaVersion === 'phoenix-graph-rebuild/v1' ? parsed : null;
    } catch {
        return null;
    }
}

export function scopedDocumentToGraphModelV2OverGraphExport(document: StoreScopedDocument): GraphModelV2OverGraphExport | null {
    try {
        const parsed = decodeGraphRebuildJsonPayload<GraphModelV2OverGraphExport>(document.payload);
        return parsed?.schemaVersion === 'phoenix-graph-model-v2-overgraph/v1' ? parsed : null;
    } catch {
        return null;
    }
}

export function graphOperatorMutationJournalToScopedDocument(
    journal: GraphOperatorMutationJournal,
    scopeKind: GraphRebuildScopeKind,
): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${journal.scopeId}:${OPERATOR_MUTATION_JOURNAL_DOCUMENT_KEY}`,
        scopeFolderId: journal.scopeId,
        narrativeId: scopeKind === 'narrative' ? journal.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: OPERATOR_MUTATION_JOURNAL_DOCUMENT_KEY,
        payload: encodeGraphRebuildJsonPayload(journal, journal.schemaVersion),
        createdAt: journal.updatedAt || now,
        updatedAt: now,
    };
}

export function scopedDocumentToGraphOperatorMutationJournal(
    document: StoreScopedDocument,
): GraphOperatorMutationJournal | null {
    try {
        const parsed = decodeGraphRebuildJsonPayload<GraphOperatorMutationJournal>(document.payload);
        return isGraphOperatorMutationJournal(parsed) ? parsed : null;
    } catch {
        return null;
    }
}

function emptyBuildTimings(): GraphRebuildBuildTimings {
    return {
        occurrenceLoadMs: 0,
        chunkLoadMs: 0,
        noteTextLoadMs: 0,
        noteFolderLoadMs: 0,
        dbLoadMs: 0,
        occurrenceRecoverMs: 0,
        documentProfileMs: 0,
        documentSemanticMs: 0,
        snapshotBuildMs: 0,
        stateCommitMs: 0,
        nativeChunkSemanticBridgeMs: 0,
        nativeChunkSemanticBridgeSkipped: 0,
        nativeChunkSemanticBridgeCandidates: 0,
        nativeChunkSemanticBridgeQualityDemotions: 0,
        nativeChunkSemanticBridgeRustMicros: 0,
        nativeMemoryGovernanceMs: 0,
        nativeMemoryGovernanceSkipped: 0,
        nativeMemoryGovernanceCandidates: 0,
        nativeMemoryGovernanceRustMicros: 0,
        nativeMemoryGovernanceRetrievalExperimentMs: 0,
        nativeMemoryGovernanceRetrievalExperimentSkipped: 0,
        nativeMemoryGovernanceRetrievalExperimentCandidates: 0,
        nativeMemoryGovernanceRetrievalExperimentRustMicros: 0,
        nativePromotionVerdictMs: 0,
        nativePromotionVerdictSkipped: 0,
        nativePromotionVerdictRows: 0,
        nativePromotionVerdictRustMicros: 0,
        nativeCompilerMs: 0,
        nativeCompilerSkipped: 0,
        nativeCompilerInputBytesByFamily: {},
        nativeTargetsByOriginatingFamily: {},
        nativeAtlasSeedRawBytes: 0,
        nativeAtlasSeedCompressedBytes: 0,
        authoritySealMs: 0,
        authorityAssertMs: 0,
        snapshotPersistMs: 0,
        snapshotSerializeMs: 0,
        snapshotPrimaryEncodeMs: 0,
        snapshotPrimaryWriteSkipped: 0,
        snapshotPrimaryIdentityReused: 0,
        snapshotOverGraphEncodeMs: 0,
        snapshotOverGraphSkipped: 0,
        snapshotStoreMs: 0,
        snapshotPrimaryStoreMs: 0,
        snapshotOverGraphStoreMs: 0,
        snapshotStoreDocuments: 0,
        snapshotContentBlobReads: 0,
        snapshotContentBlobManifestTrusted: 0,
        snapshotContentBlobManifestMatches: 0,
        snapshotContentBlobManifestMisses: 0,
        snapshotWrittenContentBlobs: 0,
        snapshotReusedContentBlobs: 0,
        previousSnapshotHydrationSkipped: 0,
        documentSemanticSkipped: 0,
        documentSemanticCacheHit: 0,
        documentSemanticDocumentsBuilt: 0,
        documentSemanticDocumentsReused: 0,
        documentSemanticRawBytesWritten: 0,
        documentSemanticCompressedBytesWritten: 0,
        nativeChunkerSkipped: 0,
        snapshotEventMs: 0,
        snapshotPayloadChars: 0,
        snapshotPrimaryRawPayloadChars: 0,
        snapshotPrimaryCompressedBytes: 0,
        snapshotCompressionSavedChars: 0,
        snapshotCompressionRatioPct: 100,
        snapshotOverGraphPayloadChars: 0,
        snapshotOverGraphRawPayloadChars: 0,
        snapshotOverGraphCompressedBytes: 0,
        snapshotOverGraphCompressionSavedChars: 0,
        snapshotOverGraphCompressionRatioPct: 100,
        snapshotTotalPayloadChars: 0,
        snapshotPayloadProfileMs: 0,
        snapshotPayloadBreakdown: {},
        dbOpsMs: 0,
        totalMs: 0,
    };
}

const SNAPSHOT_PAYLOAD_PROFILE_FIELDS: Array<[string, keyof GraphRebuildSnapshot]> = [
    ['payloadChunksChars', 'chunks'],
    ['payloadMentionsChars', 'mentions'],
    ['payloadEntityAnchorsChars', 'entityAnchors'],
    ['payloadRelationshipsChars', 'relationships'],
    ['payloadEventsChars', 'events'],
    ['payloadTemporalEdgesChars', 'temporalEdges'],
    ['payloadCausalEdgesChars', 'causalEdges'],
    ['payloadMemoryStateChars', 'memoryState'],
    ['payloadMemoryGovernanceCandidatesChars', 'memoryGovernanceCandidates'],
    ['payloadPromotionVerdictCertificateChars', 'promotionVerdictCertificate'],
    ['payloadEmbeddingTargetsChars', 'embeddingTargets'],
    ['payloadEmbeddingTargetPlanChars', 'embeddingTargetPlan'],
    ['payloadEmbeddingGraphPostProcessChars', 'embeddingGraphPostProcess'],
    ['payloadNodesChars', 'nodes'],
    ['payloadEdgesChars', 'edges'],
    ['payloadGraphCompilerChars', 'graphCompiler'],
    ['payloadProjectedUiGraphChars', 'projectedUiGraph'],
    ['payloadGraphModelV2Chars', 'graphModelV2'],
    ['payloadGraphAwareLinkSuggestionsChars', 'graphAwareLinkSuggestions'],
    ['payloadEntityLinkSuggestionsChars', 'entityLinkSuggestions'],
    ['payloadShadowLinkSuggestionsChars', 'shadowLinkSuggestions'],
    ['payloadSemanticTaskSummaryChars', 'semanticTaskSummary'],
    ['payloadSemanticCandidateSummaryChars', 'semanticCandidateSummary'],
    ['payloadManifoldSpecializationSummaryChars', 'manifoldSpecializationSummary'],
    ['payloadAtlasPacketChars', 'atlasPacket'],
    ['payloadSemanticRerankSummaryChars', 'semanticRerankSummary'],
    ['payloadSemanticAdjudicationSummaryChars', 'semanticAdjudicationSummary'],
    ['payloadSemanticEvalLedgerSummaryChars', 'semanticEvalLedgerSummary'],
    ['payloadHopfResonanceSpaceChars', 'hopfResonanceSpace'],
    ['payloadMemoryGraphRagBridgeSummaryChars', 'memoryGraphRagBridgeSummary'],
    ['payloadDiscourseSpineSummaryChars', 'discourseSpineSummary'],
    ['payloadDiscourseBridgeCandidateSummaryChars', 'discourseBridgeCandidateSummary'],
    ['payloadDiscourseBridgeAdjudicationSummaryChars', 'discourseBridgeAdjudicationSummary'],
    ['payloadDiscourseEvalLedgerSummaryChars', 'discourseEvalLedgerSummary'],
    ['payloadDiscoursePromotionSurfaceSummaryChars', 'discoursePromotionSurfaceSummary'],
    ['payloadDiscourseCompilerOverlaySummaryChars', 'discourseCompilerOverlaySummary'],
    ['payloadCalendarRegistrySummaryChars', 'calendarRegistrySummary'],
    ['payloadContentManifestChars', 'contentManifest'],
];

function jsonPayloadChars(value: unknown): number {
    if (value === undefined) return 0;
    return JSON.stringify(value).length;
}

function isEmptySnapshotContentBlobValue(value: unknown): boolean {
    if (value === undefined || value === null) return true;
    return Array.isArray(value) && value.length === 0;
}

function snapshotContentBlobValue(
    snapshot: GraphRebuildSnapshot,
    field: GraphRebuildContentBlobField,
): unknown {
    switch (field) {
        case 'sourceRows':
            return compactBlobGroup({
                chunks: snapshot.chunks,
                mentions: snapshot.mentions,
                entityAnchors: snapshot.entityAnchors,
                relationships: snapshot.relationships,
                events: snapshot.events,
                episodes: snapshot.episodes,
                chunkSemanticBridges: snapshot.chunkSemanticBridges,
                crossDocumentBridgeCertificate: snapshot.crossDocumentBridgeCertificate,
                episodeConnections: snapshot.episodeConnections,
                episodeProjectionEdges: snapshot.episodeProjectionEdges,
                temporalEdges: snapshot.temporalEdges,
                causalEdges: snapshot.causalEdges,
                memoryState: snapshot.memoryState,
                memoryGovernanceCandidates: snapshot.memoryGovernanceCandidates,
            });
        case 'renderRows':
            return compactBlobGroup({
                projectionRefs: snapshot.projectionRefs,
                nodes: snapshot.nodes,
                edges: snapshot.edges,
                structuralPostProcess: snapshot.structuralPostProcess,
                projectedUiGraph: snapshot.projectedUiGraph,
            });
        case 'evidenceTargetRegistryPage':
            return snapshot.evidenceTargetRegistryPage;
        case 'embeddingTargets':
            return snapshot.embeddingTargets;
        case 'embeddingTargetPlan':
            return compactEmbeddingTargetPlan(snapshot.embeddingTargetPlan);
        case 'embeddingGraphPostProcess':
            return snapshot.embeddingGraphPostProcess;
        case 'graphModelV2':
            return snapshot.graphModelV2;
        case 'semanticCandidateSummary':
            return snapshot.semanticCandidateSummary;
        case 'manifoldSpecializationSummary':
            return snapshot.manifoldSpecializationSummary;
        case 'storyContinuity':
            return snapshot.storyContinuity;
        case 'atlasPacket':
            return snapshot.atlasPacket ? {
                ...snapshot.atlasPacket,
                snapshotId: '',
                builtAt: 0,
            } : undefined;
    }
    return undefined;
}

function compactBlobGroup(group: Record<string, unknown>): Record<string, unknown> | undefined {
    const compact: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(group)) {
        if (!isEmptySnapshotContentBlobValue(value)) compact[key] = value;
    }
    return Object.keys(compact).length ? compact : undefined;
}

function compactEmbeddingTargetPlan(
    plan: GraphRebuildEmbeddingTargetPlan | undefined,
): Omit<GraphRebuildEmbeddingTargetPlan, 'targets'> | undefined {
    if (!plan) return undefined;
    const { targets: _targets, ...compact } = plan as GraphRebuildEmbeddingTargetPlan & { targets?: unknown };
    return compact;
}

function snapshotContentBlobSourceSchemaVersion(
    field: GraphRebuildContentBlobField,
    value: unknown,
): string {
    const record = value && typeof value === 'object'
        ? value as { schemaVersion?: unknown }
        : null;
    return typeof record?.schemaVersion === 'string'
        ? record.schemaVersion
        : `phoenix-graph-rebuild-${field}/v1`;
}

function snapshotContentBlobItemCount(value: unknown): number | undefined {
    if (Array.isArray(value)) return value.length;
    const record = value && typeof value === 'object' ? value as Record<string, unknown> : null;
    if (!record) return undefined;
    for (const key of ['targets', 'candidates', 'contributions', 'atoms', 'facts']) {
        const rows = record[key];
        if (Array.isArray(rows)) return rows.length;
    }
    let total = 0;
    let counted = false;
    for (const child of Object.values(record)) {
        if (Array.isArray(child)) {
            total += child.length;
            counted = true;
        }
    }
    if (counted) return total;
    return undefined;
}

async function timedAsync<T>(
    timings: GraphRebuildBuildTimings,
    key: GraphRebuildBuildTimingNumberKey,
    action: () => Promise<T>,
): Promise<T> {
    const started = performance.now();
    try {
        return await action();
    } finally {
        timings[key] = elapsedMs(started);
    }
}

function timedSync<T>(
    timings: GraphRebuildBuildTimings,
    key: GraphRebuildBuildTimingNumberKey,
    action: () => T,
): T {
    const started = performance.now();
    try {
        return action();
    } finally {
        timings[key] = elapsedMs(started);
    }
}

function finalizeBuildTimings(timings: GraphRebuildBuildTimings, totalStarted: number): void {
    timings.dbLoadMs = timings.occurrenceLoadMs + timings.chunkLoadMs + timings.noteTextLoadMs + timings.noteFolderLoadMs;
    timings.dbOpsMs = timings.dbLoadMs + timings.snapshotPersistMs;
    timings.totalMs = elapsedMs(totalStarted);
}

function folderContextForNote(note: Note, folder?: Folder): GraphRebuildNoteFolderContext {
    if (!folder) {
        const fallbackId = note.narrativeId ? `narrative:${note.narrativeId}` : 'global';
        return {
            folderId: fallbackId,
            folderLabel: note.narrativeId ? 'Narrative' : 'Global',
            folderKind: note.narrativeId ? 'narrative' : 'global',
        };
    }
    return {
        folderId: folder.id,
        folderLabel: folder.name || folder.entityLabel || folder.id,
        folderKind: folder.entityKind || folder.entitySubtype || (folder.isNarrativeRoot ? 'narrative' : 'folder'),
        folderParentId: folder.parentId || undefined,
        narrativeId: folder.narrativeId || note.narrativeId || undefined,
        isNarrativeRoot: folder.isNarrativeRoot || undefined,
        isTypedRoot: folder.isTypedRoot || undefined,
    };
}

function elapsedMs(started: number): number {
    return Math.max(0, Math.round(performance.now() - started));
}

export function assertGraphCanvasBootSnapshotShell(snapshot: GraphRebuildSnapshot): void {
    const authority = snapshot.authorityContract;
    if (!snapshot.id || !snapshot.scopeId || !authority?.contentHash) {
        throw new Error('Graph canvas boot snapshot shell requires a complete authority identity.');
    }
    if (authority.snapshotId !== snapshot.id || authority.scopeId !== snapshot.scopeId) {
        throw new Error('Graph canvas boot snapshot shell authority identity drift.');
    }
    const manifest = snapshot.contentManifest;
    if (!manifest || manifest.snapshotId !== snapshot.id || manifest.scopeId !== snapshot.scopeId) {
        throw new Error('Graph canvas boot snapshot shell content manifest drift.');
    }
    if (authority.counts.embeddingTargets !== snapshot.counters.embeddingTargets) {
        throw new Error('Graph canvas boot snapshot shell target count drift.');
    }
}

async function loadDynamicNoteChunks(noteIds: string[]): Promise<GraphRebuildChunk[]> {
    if (!canUseNotesTable() || !noteIds.length) return [];
    const notes = await loadNotesWithBodies(noteIds);
    return notes.flatMap((note) => dynamicChunksForNote(note));
}

export function dynamicChunksForNote(note: Pick<Note, 'id' | 'markdownContent' | 'content'>): GraphRebuildChunk[] {
    const text = notePlainText(note);
    return buildAdaptiveGraphRebuildChunks(note.id, text);
}

async function loadBlockChunks(noteIds: string[]): Promise<GraphRebuildChunk[]> {
    if (!canUseBlockTable() || !noteIds.length) return [];
    const rows = (await Promise.all(noteIds.map((noteId) => db.noteBlocks.where('noteId').equals(noteId).toArray()))).flat();
    return rows
        .sort((left, right) => left.noteId.localeCompare(right.noteId) || left.ordinal - right.ordinal)
        .map(blockToChunk);
}

async function loadFallbackNoteChunks(noteIds: string[]): Promise<GraphRebuildChunk[]> {
    if (!canUseNotesTable() || !noteIds.length) return [];
    const notes = await loadNotesWithBodies(noteIds);
    return notes.map((note, ordinal) => ({
        id: `${note.id}:note-fallback:0`,
        noteId: note.id,
        start: 0,
        end: (note.markdownContent || '').length,
        ordinal,
        source: 'note-fallback',
        textHash: simpleHash(note.markdownContent || ''),
    }));
}

async function loadNotesWithBodies(noteIds: string[]): Promise<Note[]> {
    if (!noteIds.length) return [];
    const hydrated = await ops.getNotesByIds(noteIds) as unknown as Note[];
    if (hydrated.length) return hydrated;
    return (await Promise.all(noteIds.map((noteId) => db.notes.get(noteId)))).filter((note): note is Note => !!note);
}

function notePlainText(note: Pick<Note, 'markdownContent' | 'content'>): string {
    const markdown = String(note.markdownContent || '');
    if (markdown.trim()) return markdown;
    return parseContentToPlainText(String(note.content || ''));
}

function blockToChunk(block: NoteBlockProjection): GraphRebuildChunk {
    return {
        id: block.id || `${block.noteId}:block:${block.ordinal}`,
        noteId: block.noteId,
        start: block.startOffset,
        end: block.endOffset,
        ordinal: block.ordinal,
        source: 'note-block',
        textHash: block.textHash,
    };
}

function canUseOccurrenceTable(): boolean {
    return typeof db.entityOccurrences?.where === 'function'
        && typeof db.entityOccurrences?.toArray === 'function';
}

function canUseBlockTable(): boolean {
    return typeof db.noteBlocks?.where === 'function';
}

function canUseNotesTable(): boolean {
    return typeof db.notes?.get === 'function';
}

function dispatchGraphRebuildEvent(name: string, detail: Record<string, unknown>): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent(name, { detail }));
}

function simpleHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}
