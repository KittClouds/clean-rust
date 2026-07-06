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
import { PhoenixBackendService } from '../services/phoenix-backend.service';
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
    isGraphOperatorMutationJournal,
    graphOperatorMutationJournalFromTruthCommits,
    type GraphOperatorMutationJournal,
} from './graph-operator-mutation-journal';
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
    GraphAtlasFamily,
    GraphAtlasManifoldTarget,
    GraphAtlasObject,
    GraphAtlasObjectStatus,
    GraphAtlasPacket,
} from './graph-atlas-packet';
import {
    GRAPH_ATLAS_BUILDER_ROLE,
    GRAPH_ATLAS_IDENTITY_AUTHORITY,
    GRAPH_ATLAS_PACKET_AUTHORITY,
} from './graph-atlas-packet';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { applyNativeChunkSemanticBridgeCandidates } from './graph-rebuild-derived-facts';
import { finalizeGraphRebuildSnapshot } from './graph-snapshot-finalizer';
import {
    buildGraphSnapshotSourceEvidence,
    mergeGraphRebuildOccurrences as mergeOccurrenceEvidence,
    type GraphSnapshotSourceEvidenceInput,
} from './graph-snapshot-source-evidence';
import { buildGraphRebuildEmbeddingGraphPostProcess } from './graph-rebuild-embedding-postprocess';
import { selectGraphRebuildEmbeddingTargetPlan } from './graph-rebuild-embedding-target-policy';
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
    GraphMemoryGovernanceRetrievalCandidate,
    GraphMemoryGovernanceRetrievalWeightingExperiment,
    GraphRebuildNoteFolderContext,
    GraphRebuildRelationshipHint,
    GraphRebuildScopeKind,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import type { GraphCompilerDualWriteSidecar } from './graph-compiler-read-model';
import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';
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

export { mergeGraphRebuildOccurrences } from './graph-snapshot-source-evidence';

export const GRAPH_REBUILD_NAMESPACE = 'phoenix_graph_rebuild_v1';
const SNAPSHOT_DOCUMENT_KEY = 'snapshot';
export const DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY = 'snapshot:diagnostic';
const RECEIPT_DOCUMENT_KEY = 'receipt';
const OPERATOR_MUTATION_JOURNAL_DOCUMENT_KEY = 'operator-mutation-journal';
export const GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY = 'graph-model-v2-overgraph';
const POST_PROCESS_CACHE_PREFIX = 'postprocess-cache';
const SNAPSHOT_CONTENT_BLOB_PREFIX = 'snapshot-blob';
const CONTENT_BLOB_SCHEMA_VERSION = 'phoenix-graph-rebuild-content-blob/v1';
const COMPRESSED_JSON_SCHEMA_VERSION = 'phoenix-graph-rebuild-json-payload/gzip-base64/v1';
const COMPRESSED_SNAPSHOT_SCHEMA_VERSION = 'phoenix-graph-rebuild-payload/gzip-base64/v1';
const SNAPSHOT_COMPRESSION_MIN_CHARS = 64 * 1024;
const BASE64_CHUNK_SIZE = 0x8000;
const NATIVE_COMPILER_REVIEW_ROW_LIMIT = 128;
const NATIVE_COMPILER_DISCOURSE_CLUSTER_LIMIT = 72;
const NATIVE_COMPILER_DISCOURSE_BRIDGE_LIMIT = 96;
const NATIVE_COMPILER_PACKET_TEXT_LIMIT = 180;
const NATIVE_COMPILER_PACKET_LIST_LIMIT = 12;

export interface GraphRebuildPostProcessCache {
    schemaVersion: 'phoenix-graph-postprocess-cache/v1';
    scopeId: string;
    scopeKind?: GraphRebuildScopeKind;
    fingerprint: string;
    snapshot?: GraphRebuildSnapshot;
    snapshotId?: string;
    receipt?: GraphIndexRunReceipt;
    receiptId?: string;
    updatedAt: number;
}

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
    diagnosticBaseSnapshotId?: string;
    diagnosticBaseSnapshotRunSerial?: number;
    candidateCount?: number;
    calendarRegistrySnapshot?: CalendarRegistrySnapshot;
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
    private readonly absentOperatorMutationJournalScopes = new Set<string>();
    private primarySnapshotRunSerial = 0;

    readonly snapshot = computed(() => this.snapshotState());
    readonly isBuilding = computed(() => this.buildingState());
    readonly error = computed(() => this.errorState());
    readonly lastBuildTimings = computed(() => this.lastBuildTimingsState());

    currentSnapshotRunSerial(): number {
        return this.primarySnapshotRunSerial;
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
        const commitsPrimarySnapshot = durabilityMode !== 'diagnostic';
        if (commitsPrimarySnapshot) this.buildingState.set(true);
        const totalStarted = performance.now();
        const builtAt = Date.now();
        const timings = emptyBuildTimings();
        const currentSnapshot = this.snapshotState();
        const previousContentManifest = request.previousContentManifest
            || (currentSnapshot?.scopeId === request.scopeId ? currentSnapshot.contentManifest : undefined);
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
            const documentSemanticSummary = durabilityMode === 'interactive'
                ? undefined
                : await timedAsync(timings, 'documentSemanticMs', () =>
                    this.buildDocumentSemanticSummary(noteTexts, request.entities)
                );
            if (durabilityMode === 'interactive') {
                timings.documentSemanticMs = 0;
                timings.documentSemanticSkipped = 1;
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
                builtAt,
            }));
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
            snapshot = await this.reconcileDocumentGraphMutations(snapshot);
            await this.attachNativeChunkSemanticBridges(snapshot, noteTexts, timings);
            await this.attachNativeMemoryGovernance(snapshot, timings);
            await this.attachNativeMemoryGovernanceRetrievalExperiment(snapshot, timings);
            await this.attachNativePromotionVerdictCertificate(snapshot, timings);
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
            const authoritySealStarted = performance.now();
            finalizeGraphRebuildSnapshot({
                snapshot,
                sourceEvidence,
                previousSnapshot,
                hasNonemptySourceText: Object.values(noteTexts).some((text) => text.trim().length > 0),
            });
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
                if (commitsPrimarySnapshot) this.errorState.set(null);
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

    private async attachNativeChunkSemanticBridges(
        snapshot: GraphRebuildSnapshot,
        noteTexts: Record<string, string>,
        timings?: GraphRebuildBuildTimings,
    ): Promise<void> {
        const started = performance.now();
        try {
            if (this.phoenix.target !== 'native') {
                applyNativeChunkSemanticBridgeCandidates(snapshot, []);
                if (timings) timings.nativeChunkSemanticBridgeSkipped = 1;
                return;
            }
            const native = await this.phoenix.storeCommand('graphRebuild:chunkSemanticBridges', {
                snapshot: graphRebuildSnapshotToNativeChunkBridgePayload(snapshot),
                documents: snapshot.noteIds.map((noteId) => ({ noteId, text: noteTexts[noteId] || '' })),
            }) as NativeChunkSemanticBridgeOutput | null;
            if (!isNativeChunkSemanticBridgeOutput(native)) {
                throw new Error('Rust chunk semantic bridge command returned an invalid v1 payload.');
            }
            applyNativeChunkSemanticBridgeCandidates(snapshot, native.candidates);
            if (timings) {
                timings.nativeChunkSemanticBridgeCandidates = native.candidates.length;
                timings.nativeChunkSemanticBridgeQualityDemotions = native.qualityGate.demotedSameEntityOnly;
                timings.nativeChunkSemanticBridgeRustMicros = native.timing.bridgeBuildMicros;
            }
        } catch (error) {
            if (!isUnsupportedStoreCommand(error, 'graphRebuild:chunkSemanticBridges')) throw error;
            applyNativeChunkSemanticBridgeCandidates(snapshot, []);
            if (timings) {
                timings.nativeChunkSemanticBridgeSkipped = 1;
                timings.nativeChunkSemanticBridgeCandidates = 0;
                timings.nativeChunkSemanticBridgeQualityDemotions = 0;
                timings.nativeChunkSemanticBridgeRustMicros = 0;
            }
            console.warn('[GraphRebuild] Native chunk semantic bridge command unavailable; continuing without candidate bridges.', error);
        } finally {
            if (timings) timings.nativeChunkSemanticBridgeMs = elapsedMs(started);
        }
    }

    private async attachNativeMemoryGovernance(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
    ): Promise<void> {
        const started = performance.now();
        try {
            if (this.phoenix.target !== 'native') {
                applyNativeMemoryGovernanceCandidates(snapshot, []);
                if (timings) timings.nativeMemoryGovernanceSkipped = 1;
                return;
            }
            const native = await this.phoenix.storeCommand('graphRebuild:memoryGovernance', {
                snapshot: graphRebuildSnapshotToNativeMemoryGovernancePayload(snapshot),
            }) as NativeMemoryGovernanceOutput | null;
            if (!isNativeMemoryGovernanceOutput(native)) {
                throw new Error('Rust memory governance command returned an invalid v1 payload.');
            }
            applyNativeMemoryGovernanceCandidates(snapshot, native.candidates);
            if (timings) {
                timings.nativeMemoryGovernanceCandidates = native.candidates.length;
                timings.nativeMemoryGovernanceRustMicros = native.timing.governanceBuildMicros;
            }
        } catch (error) {
            if (!isUnsupportedStoreCommand(error, 'graphRebuild:memoryGovernance')) throw error;
            applyNativeMemoryGovernanceCandidates(snapshot, []);
            if (timings) {
                timings.nativeMemoryGovernanceSkipped = 1;
                timings.nativeMemoryGovernanceCandidates = 0;
                timings.nativeMemoryGovernanceRustMicros = 0;
            }
            console.warn('[GraphRebuild] Native memory governance command unavailable; continuing without governance candidates.', error);
        } finally {
            if (timings) timings.nativeMemoryGovernanceMs = elapsedMs(started);
        }
    }

    private async attachNativeMemoryGovernanceRetrievalExperiment(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
    ): Promise<void> {
        const started = performance.now();
        const retrievalCandidates = memoryGovernanceRetrievalCandidatesFromSnapshot(snapshot);
        if (timings) timings.nativeMemoryGovernanceRetrievalExperimentCandidates = retrievalCandidates.length;
        try {
            if (this.phoenix.target !== 'native' || !retrievalCandidates.length) {
                if (timings) timings.nativeMemoryGovernanceRetrievalExperimentSkipped = 1;
                return;
            }
            const native = await this.phoenix.storeCommand('graphRebuild:memoryGovernanceRetrievalExperiment', {
                snapshot: graphRebuildSnapshotToNativeMemoryGovernancePayload(snapshot),
                retrievalCandidates,
            }) as NativeMemoryGovernanceRetrievalExperimentOutput | null;
            if (!isNativeMemoryGovernanceRetrievalExperimentOutput(native)) {
                throw new Error('Rust memory governance retrieval experiment returned an invalid v1 payload.');
            }
            applyNativeMemoryGovernanceRetrievalExperiment(snapshot, native.experiment);
            if (timings) {
                timings.nativeMemoryGovernanceRetrievalExperimentRustMicros =
                    native.timing.experimentBuildMicros;
            }
        } catch (error) {
            if (!isUnsupportedStoreCommand(error, 'graphRebuild:memoryGovernanceRetrievalExperiment')) throw error;
            if (timings) {
                timings.nativeMemoryGovernanceRetrievalExperimentSkipped = 1;
                timings.nativeMemoryGovernanceRetrievalExperimentRustMicros = 0;
            }
            console.warn('[GraphRebuild] Native memory governance retrieval experiment unavailable; continuing without retrieval report.', error);
        } finally {
            if (timings) timings.nativeMemoryGovernanceRetrievalExperimentMs = elapsedMs(started);
        }
    }

    private async attachNativePromotionVerdictCertificate(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
    ): Promise<void> {
        const started = performance.now();
        try {
            if (this.phoenix.target !== 'native') {
                applyNativePromotionVerdictCertificate(snapshot, null, timings);
                if (timings) timings.nativePromotionVerdictSkipped = 1;
                return;
            }
            const previewReceipts = buildGraphPromotionPreviewReceipts(snapshot);
            const native = await this.phoenix.storeCommand('graphPromotion:verdictCertificate', {
                scopeId: snapshot.scopeId,
                receipts: previewReceipts,
                commits: [],
            }) as NativePromotionVerdictOutput | null;
            if (!isNativePromotionVerdictOutput(native)) {
                throw new Error('Rust promotion verdict command returned an invalid v1 payload.');
            }
            applyNativePromotionVerdictCertificate(snapshot, native.certificate, timings);
            if (timings) {
                timings.nativePromotionVerdictRows = native.certificate.audit.total;
                timings.nativePromotionVerdictRustMicros = native.timing.verdictBuildMicros;
            }
        } catch (error) {
            if (!isUnsupportedStoreCommand(error, 'graphPromotion:verdictCertificate')) throw error;
            applyNativePromotionVerdictCertificate(snapshot, null, timings);
            if (timings) {
                timings.nativePromotionVerdictSkipped = 1;
                timings.nativePromotionVerdictRows = 0;
                timings.nativePromotionVerdictRustMicros = 0;
            }
            console.warn('[GraphRebuild] Native promotion verdict command unavailable; continuing without promotion verdict rows.', error);
        } finally {
            if (timings) timings.nativePromotionVerdictMs = elapsedMs(started);
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
            return isGraphDocumentSemanticSummary(native) ? native : undefined;
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
            const authorizedCurrent = authorizeGraphRebuildSnapshotForLoad(current, (error) =>
                console.warn('[GraphRebuild] Ignoring in-memory graph rebuild snapshot that failed authority parity', error),
            );
            if (authorizedCurrent) return authorizedCurrent;
            this.snapshotState.set(null);
        }
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, SNAPSHOT_DOCUMENT_KEY);
        const persisted = document ? scopedDocumentToGraphRebuildSnapshot(document) : null;
        if (!persisted) return null;
        const hydrated = await this.hydratePersistedSnapshot(persisted);
        recordGraphCollapseSnapshotBoundary(hydrated, 'persisted_snapshot', { loadedFromStore: 1 });
        const authorized = authorizeGraphRebuildSnapshotForLoad(hydrated, (error) =>
            console.warn('[GraphRebuild] Ignoring persisted graph rebuild snapshot that failed authority parity', error),
        );
        if (!authorized) return null;
        this.snapshotState.set(authorized);
        return authorized;
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

    async loadPersistedOperatorMutationJournal(scopeId: string): Promise<GraphOperatorMutationJournal | null> {
        return this.loadOperatorMutationJournal(scopeId);
    }

    private async reconcileDocumentGraphMutations(
        snapshot: GraphRebuildSnapshot,
    ): Promise<GraphRebuildSnapshot> {
        const truthProjection = await this.loadGraphTruthCommitProjection(snapshot.scopeId);
        if (truthProjection) {
            snapshot.graphTruthCommitLedger = truthProjection.ledger;
            snapshot.documentGraphMutationLedger = graphDocumentGraphMutationLedgerFromTruthCommits(truthProjection.commits);
            snapshot.operatorMutationJournal = graphOperatorMutationJournalFromTruthCommits(
                snapshot.scopeId,
                truthProjection.commits,
                snapshot.builtAt,
            );
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
        if (persistedSnapshot.contentManifest) snapshot.contentManifest = persistedSnapshot.contentManifest;
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
        const entries = await Promise.all(Object.values(refs).map(async (ref) => {
            if (!ref) return null;
            const blob = await this.loadPersistedSnapshotContentBlob(persisted.scopeId, ref.documentKey);
            return blob ? [ref.field, blob] as const : null;
        }));
        const blobs: Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>> = {};
        for (const entry of entries) {
            if (entry) blobs[entry[0]] = entry[1];
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

export function graphRebuildSnapshotToNativeChunkBridgePayload(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
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
        memoryState: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: snapshot.nodes,
        edges: [],
        counters: snapshot.counters,
    };
}

export function graphRebuildSnapshotToNativeMemoryGovernancePayload(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
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
        nodes: [],
        edges: [],
        counters: snapshot.counters,
    };
}

function isNativeChunkSemanticBridgeOutput(
    value: NativeChunkSemanticBridgeOutput | null | undefined,
): value is NativeChunkSemanticBridgeOutput {
    return value?.schemaVersion === 'phoenix-chunk-semantic-bridge-native-output/v1'
        && value.source === 'rust'
        && Array.isArray(value.candidates)
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

export function filterNativeEmbeddingTargetsForCommittedSources(
    snapshot: GraphRebuildSnapshot,
    targets: GraphRebuildEmbeddingTarget[],
): GraphRebuildEmbeddingTarget[] {
    const committed = committedTargetSources(snapshot);
    return targets.filter((target) => nativeTargetHasCommittedSource(target, committed));
}

export function mergeNativeEmbeddingTargets(
    existing: GraphRebuildEmbeddingTarget[],
    nativeTargets: GraphRebuildEmbeddingTarget[],
): GraphRebuildEmbeddingTarget[] {
    const nativeById = new Map(nativeTargets.map((target) => [target.id, target]));
    const merged = existing.map((target) => nativeById.get(target.id) || target);
    const existingIds = new Set(existing.map((target) => target.id));
    for (const target of nativeTargets) {
        if (!existingIds.has(target.id)) merged.push(target);
    }
    return merged;
}

export function reconcileNativeAtlasPacketForTargets(
    snapshot: GraphRebuildSnapshot,
    packet: GraphAtlasPacket,
): GraphAtlasPacket {
    const packetTargets = new Map(packet.manifoldTargets.map((target) => [target.id, target]));
    const objectsById = new Map(packet.objects.map((object) => [object.id, object]));
    const objectsBySourceId = new Map<string, GraphAtlasObject[]>();
    const objectsByTargetId = new Map<string, GraphAtlasObject[]>();
    for (const object of packet.objects) {
        for (const sourceId of object.sourceIds) pushAtlasObjectLookup(objectsBySourceId, sourceId, object);
        for (const targetId of object.targetIds) pushAtlasObjectLookup(objectsByTargetId, targetId, object);
    }
    const objects = new Map(packet.objects.map((object) => [object.id, object]));
    const targets = snapshot.embeddingTargets.map((target): GraphAtlasManifoldTarget => {
        const existingTarget = packetTargets.get(target.id);
        const existingObject = (existingTarget && objectsById.get(existingTarget.objectId))
            || selectAtlasObjectForTarget(target, objectsByTargetId.get(target.id))
            || selectAtlasObjectForTarget(target, objectsBySourceId.get(target.sourceId));
        const objectId = existingTarget?.objectId || existingObject?.id || `atlas:${target.id}`;
        const family = existingTarget?.family || existingObject?.family || atlasFamilyForTarget(target);
        objects.set(objectId, atlasObjectForTarget(existingObject, objectId, family, target));
        return {
            id: target.id,
            objectId,
            family,
            admission: target.admissionStatus === 'deferred' ? 'deferred' : 'admitted',
            vectorStatus: existingTarget?.vectorStatus || 'missing',
            coordinateSource: existingTarget?.coordinateSource || 'none',
            status: existingTarget?.status || 'accepted',
            kind: target.kind,
            label: target.label,
            entityKind: target.entityKind,
            styleKey: target.styleKey,
            lane: target.lane,
            structuralRole: target.structuralRole,
            documentUnitKind: target.documentUnitKind || existingTarget?.documentUnitKind,
            stateContextKind: target.stateContextKind || existingTarget?.stateContextKind,
            sourceId: target.sourceId,
            registryEntityId: target.entityId,
            noteId: target.noteId,
            chunkId: target.chunkId,
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds,
        };
    });
    const targetIds = new Set(targets.map((target) => target.id));
    for (const parentId of targets.flatMap((target) => target.parentIds || [])) {
        if (targetIds.has(parentId)) continue;
        const parent = objectsById.get(parentId) || objectsBySourceId.get(parentId)?.[0];
        if (parent) objects.set(parent.id, parent);
    }
    const resolvableParents = new Set([
        ...targets.flatMap((target) => [target.id, target.objectId, target.sourceId]),
        ...[...objects.values()].flatMap((object) => [object.id, ...object.sourceIds]),
    ]);
    const reconciledTargets = targets.map((target) => ({
        ...target,
        parentIds: (target.parentIds || []).filter((parentId) => resolvableParents.has(parentId)),
    }));
    const reconciledObjects = [...objects.values()].map((object) => ({
        ...object,
        targetIds: object.targetIds.filter((targetId) => targetIds.has(targetId)),
    }));
    const families = new Map<GraphAtlasFamily, number>();
    for (const object of reconciledObjects) {
        families.set(object.family, (families.get(object.family) || 0) + 1);
    }
    const reconciledPacket: GraphAtlasPacket = {
        ...packet,
        objects: reconciledObjects,
        manifoldTargets: reconciledTargets,
        counters: {
            ...packet.counters,
            objects: reconciledObjects.length,
            manifoldTargets: reconciledTargets.length,
            registryEntities: snapshot.nodes.length,
            evidenceAnchors: snapshot.entityAnchors.length,
            modelVectors: reconciledTargets.filter((target) => target.vectorStatus === 'modelVector').length,
            families: [...families.entries()]
                .sort(([left], [right]) => left.localeCompare(right))
                .map(([family, count]) => ({ family, count })),
        },
    };
    return normalizeNativeAtlasPacketSourceContract(reconciledPacket) || reconciledPacket;
}

function normalizeNativeAtlasPacketSourceContract(packet: GraphAtlasPacket | undefined): GraphAtlasPacket | undefined {
    if (!packet) return undefined;
    const contract = packet.sourceContract;
    if (contract.authority !== GRAPH_ATLAS_PACKET_AUTHORITY
        || contract.identityAuthority !== GRAPH_ATLAS_IDENTITY_AUTHORITY) {
        return packet;
    }
    if (contract.tsGraphBuilderRole === GRAPH_ATLAS_BUILDER_ROLE) return packet;
    if (!isLegacyAtlasBuilderRole(contract.tsGraphBuilderRole)) return packet;
    return {
        ...packet,
        sourceContract: {
            ...contract,
            tsGraphBuilderRole: GRAPH_ATLAS_BUILDER_ROLE,
        },
    };
}

function isLegacyAtlasBuilderRole(role: string): boolean {
    return role === 'compatibility-only'
        || role === 'compatibility_only'
        || role === 'typescript-compatibility'
        || role === 'typescript_compatibility';
}

function pushAtlasObjectLookup(
    lookup: Map<string, GraphAtlasObject[]>,
    key: string,
    object: GraphAtlasObject,
): void {
    const objects = lookup.get(key);
    if (objects) objects.push(object);
    else lookup.set(key, [object]);
}

function selectAtlasObjectForTarget(
    target: GraphRebuildEmbeddingTarget,
    candidates: GraphAtlasObject[] | undefined,
): GraphAtlasObject | undefined {
    if (!candidates?.length) return undefined;
    const preferredFamily = atlasFamilyForTarget(target);
    return candidates.find((object) => object.family === preferredFamily) || candidates[0];
}

function atlasObjectForTarget(
    existing: GraphAtlasObject | undefined,
    id: string,
    family: GraphAtlasFamily,
    target: GraphRebuildEmbeddingTarget,
): GraphAtlasObject {
    return {
        id,
        family,
        status: existing?.status || 'accepted',
        kind: target.kind,
        label: target.label,
        styleKey: target.styleKey,
        lane: target.lane,
        structuralRole: target.structuralRole,
        documentUnitKind: target.documentUnitKind || existing?.documentUnitKind,
        stateContextKind: target.stateContextKind || existing?.stateContextKind,
        registryEntityId: target.entityId,
        noteIds: target.noteId ? [target.noteId] : existing?.noteIds || [],
        chunkIds: target.chunkId ? [target.chunkId] : existing?.chunkIds || [],
        anchorIds: target.kind === 'anchor' ? target.evidenceIds : existing?.anchorIds || [],
        evidenceIds: target.evidenceIds,
        sourceIds: [...new Set([target.sourceId, ...(existing?.sourceIds || [])])],
        targetIds: [...new Set([target.id, ...(existing?.targetIds || [])])],
    };
}

function atlasFamilyForTarget(target: GraphRebuildEmbeddingTarget): GraphAtlasFamily {
    const kind = normalizeTargetKind(target.kind);
    if (kind === 'entity') return 'registry';
    if (kind === 'note' || kind === 'chunk' || kind === 'episode' || kind === 'structureroot' || kind === 'documentunit') return 'structure';
    if (kind === 'anchor' || kind === 'evidencespan') return 'evidence';
    if (kind === 'temporalfact') return 'temporal';
    if (kind === 'causalfact') return 'causal';
    if (kind === 'memorystate') return 'memory';
    if (kind === 'graphfact' || kind === 'event') return 'fact';
    return 'unknown';
}

function nativeTargetHasCommittedSource(
    target: GraphRebuildEmbeddingTarget,
    committed: ReturnType<typeof committedTargetSources>,
): boolean {
    const kind = normalizeTargetKind(target.kind);
    const lane = target.lane || inferredNativeTargetLane(kind);
    if (kind === 'note' || kind === 'chunk' || kind === 'episode' || kind === 'structureroot' || kind === 'documentunit') return true;
    if (lane === 'entity_anchor' || kind === 'entity') {
        return committed.entities.has(target.entityId || target.sourceId);
    }
    if (lane === 'anchor_evidence' || kind === 'anchor' || kind === 'evidencespan') {
        return committed.anchors.size > 0 && targetReferencesAny(target, committed.anchors);
    }
    if (isNativeFactLane(lane) || ['graphfact', 'temporalfact', 'causalfact', 'memorystate', 'event'].includes(kind)) {
        return committed.facts.size > 0 && targetReferencesAny(target, committed.facts);
    }
    return true;
}

function committedTargetSources(snapshot: GraphRebuildSnapshot) {
    const anchors = new Set([
        ...snapshot.mentions.map((row) => row.id),
        ...snapshot.entityAnchors.map((row) => row.id),
    ]);
    const facts = new Set<string>();
    for (const relationship of snapshot.relationships) {
        addSourceVariants(facts, relationship.id, ['relationship', 'graph-fact']);
    }
    for (const event of snapshot.events) addSourceVariants(facts, event.id, ['event']);
    for (const edge of snapshot.temporalEdges) addSourceVariants(facts, edge.id, ['temporalFact']);
    for (const edge of snapshot.causalEdges) addSourceVariants(facts, edge.id, ['causalFact']);
    for (const state of snapshot.memoryState) addSourceVariants(facts, state.id, ['memory']);
    return {
        anchors,
        entities: new Set(snapshot.nodes.map((node) => node.entityId)),
        facts,
    };
}

function addSourceVariants(out: Set<string>, id: string, prefixes: string[]): void {
    if (!id) return;
    out.add(id);
    out.add(`fact:${id}`);
    out.add(`embed:${id}`);
    for (const prefix of prefixes) {
        out.add(`${prefix}:${id}`);
        out.add(`fact:${prefix}:${id}`);
        out.add(`embed:${prefix}:${id}`);
    }
}

function targetReferencesAny(target: GraphRebuildEmbeddingTarget, allowed: Set<string>): boolean {
    if (allowed.has(target.sourceId)) return true;
    if (target.entityId && allowed.has(target.entityId)) return true;
    return target.evidenceIds.some((id) => allowed.has(id));
}

function inferredNativeTargetLane(kind: string): string {
    if (kind === 'episode') return 'document_spine';
    if (kind === 'entity') return 'entity_anchor';
    if (kind === 'anchor' || kind === 'evidencespan') return 'anchor_evidence';
    if (kind === 'graphfact') return 'relationship_fact';
    if (kind === 'temporalfact') return 'temporal_fact';
    if (kind === 'causalfact') return 'causal_fact';
    if (kind === 'memorystate') return 'memory_state';
    if (kind === 'event') return 'event_identity';
    return 'unknown';
}

function isNativeFactLane(lane: string): boolean {
    return lane === 'relationship_fact'
        || lane === 'temporal_fact'
        || lane === 'causal_fact'
        || lane === 'memory_state'
        || lane === 'event_identity';
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

function normalizeTargetKind(kind: string): string {
    return String(kind || '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase().replace(/[-_\s]+/g, '');
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
    'embeddingTargets',
    'embeddingTargetPlan',
    'embeddingGraphPostProcess',
    'graphModelV2',
    'semanticCandidateSummary',
    'manifoldSpecializationSummary',
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
    persisted.episodeConnections = [];
    persisted.episodeProjectionEdges = [];
    persisted.temporalEdges = [];
    persisted.causalEdges = [];
    persisted.memoryState = [];
    persisted.memoryGovernanceCandidates = [];
    persisted.embeddingTargets = [];
    persisted.projectionRefs = [];
    persisted.nodes = [];
    persisted.edges = [];
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

export function graphIndexReceiptToScopedDocument(receipt: GraphIndexRunReceipt): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${receipt.scope.scopeId}:${RECEIPT_DOCUMENT_KEY}`,
        scopeFolderId: receipt.scope.scopeId,
        narrativeId: receipt.scope.kind === 'narrative' ? receipt.scope.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: RECEIPT_DOCUMENT_KEY,
        payload: JSON.stringify(receipt),
        createdAt: receipt.startedAt || now,
        updatedAt: now,
    };
}

export function scopedDocumentToGraphIndexReceipt(document: StoreScopedDocument): GraphIndexRunReceipt | null {
    try {
        const parsed = JSON.parse(document.payload) as GraphIndexRunReceipt;
        return parsed?.schemaVersion === 'phoenix-graph-index-run/v1' ? parsed : null;
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

function postProcessCacheDocumentKey(fingerprint: string): string {
    return `${POST_PROCESS_CACHE_PREFIX}:${fingerprint}`;
}

export function postProcessCacheToScopedDocument(cache: GraphRebuildPostProcessCache): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${cache.scopeId}:${postProcessCacheDocumentKey(cache.fingerprint)}`,
        scopeFolderId: cache.scopeId,
        narrativeId: cache.scopeKind === 'narrative' ? cache.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: postProcessCacheDocumentKey(cache.fingerprint),
        payload: JSON.stringify(cache),
        createdAt: cache.updatedAt || now,
        updatedAt: now,
    };
}

function scopedDocumentToPostProcessCache(document: StoreScopedDocument): GraphRebuildPostProcessCache | null {
    try {
        const parsed = JSON.parse(document.payload) as GraphRebuildPostProcessCache;
        return parsed?.schemaVersion === 'phoenix-graph-postprocess-cache/v1' ? parsed : null;
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
