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
import { buildGraphDiscourseBridgeAdjudicationSummary } from './graph-discourse-bridge-adjudication';
import { buildGraphDiscourseBridgeCandidateSummary } from './graph-discourse-bridge-candidates';
import { buildGraphDiscourseCompilerOverlaySummary } from './graph-discourse-compiler-overlay';
import { buildGraphDiscourseEvalLedgerSummary } from './graph-discourse-eval-ledger';
import { buildGraphDiscoursePromotionSurfaceSummary } from './graph-discourse-promotion-surface';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildGraphDiscourseSpineSummary } from './graph-discourse-spine';
import { buildHopfResonanceSpace } from './graph-hopf-resonance-space';
import { buildGraphMemoryGraphRagBridgeSummary } from './graph-memory-graphrag-bridge';
import { buildGraphSemanticAdjudicationDAGSummary } from './graph-semantic-adjudication';
import { buildGraphSemanticEvalLedgerSummary } from './graph-semantic-eval-ledger';
import { buildGraphSemanticRerankSummary } from './graph-semantic-rerank';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';
import {
    buildGraphModelV2OverGraphExport,
    type GraphModelV2OverGraphExport,
} from './graph-model-v2-overgraph';
import type {
    GraphIndexRunReceipt,
    GraphIndexPostProcessMode,
    GraphIndexEmbeddingStagePolicy,
    GraphRebuildBuildTimings,
    GraphRebuildChunk,
    GraphRebuildEmbeddingProfile,
    GraphRebuildNoteFolderContext,
    GraphRebuildRelationshipHint,
    GraphRebuildScopeKind,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import type { GraphCompilerDualWriteSidecar } from './graph-compiler-read-model';
import type { CalendarRegistrySnapshot } from '../lib/fantasy-calendar/calendar-registry-snapshot';

export const GRAPH_REBUILD_NAMESPACE = 'phoenix_graph_rebuild_v1';
const SNAPSHOT_DOCUMENT_KEY = 'snapshot';
const RECEIPT_DOCUMENT_KEY = 'receipt';
export const GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY = 'graph-model-v2-overgraph';
const POST_PROCESS_CACHE_PREFIX = 'postprocess-cache';
const COMPRESSED_JSON_SCHEMA_VERSION = 'phoenix-graph-rebuild-json-payload/gzip-base64/v1';
const COMPRESSED_SNAPSHOT_SCHEMA_VERSION = 'phoenix-graph-rebuild-payload/gzip-base64/v1';
const SNAPSHOT_COMPRESSION_MIN_CHARS = 64 * 1024;
const BASE64_CHUNK_SIZE = 0x8000;

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

export type NativeGraphCompilerSidecar = Partial<GraphCompilerDualWriteSidecar> & {
    factGraphPayload?: CompressedGraphCompilerFactGraphPayload;
};

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
    fallbackOccurrences?: EntityOccurrence[];
    relationshipHints?: GraphRebuildRelationshipHint[];
    embeddingProfile?: Partial<GraphRebuildEmbeddingProfile>;
    postProcessMode?: GraphIndexPostProcessMode;
    embeddingStagePolicy?: GraphIndexEmbeddingStagePolicy;
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

    readonly snapshot = computed(() => this.snapshotState());
    readonly isBuilding = computed(() => this.buildingState());
    readonly error = computed(() => this.errorState());
    readonly lastBuildTimings = computed(() => this.lastBuildTimingsState());

    async buildAndPersistSnapshot(request: GraphRebuildBuildRequest): Promise<GraphRebuildSnapshot> {
        this.buildingState.set(true);
        const totalStarted = performance.now();
        const timings = emptyBuildTimings();
        try {
            const persistedOccurrences = await timedAsync(timings, 'occurrenceLoadMs', () =>
                this.loadOccurrences(request.noteIds, request.entities)
            );
            const chunks = await timedAsync(timings, 'chunkLoadMs', () =>
                this.loadChunks(request.noteIds, persistedOccurrences)
            );
            const noteTexts = await timedAsync(timings, 'noteTextLoadMs', () =>
                this.loadNoteTexts(request.noteIds, persistedOccurrences)
            );
            const noteFolders = await timedAsync(timings, 'noteFolderLoadMs', () =>
                this.loadNoteFolderContexts(request.noteIds, persistedOccurrences)
            );
            const recoverStarted = performance.now();
            const fallbackOccurrences = request.fallbackOccurrences || [];
            const occurrences = mergeGraphRebuildOccurrences(
                mergeGraphRebuildOccurrences(persistedOccurrences, fallbackOccurrences),
                recoverGraphRebuildOccurrences(noteTexts, request.entities),
            );
            timings.occurrenceRecoverMs = elapsedMs(recoverStarted);
            const snapshot = timedSync(timings, 'snapshotBuildMs', () => buildGraphRebuildSnapshot({
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
            }));
            await this.attachNativeGraphCompilerSidecar(snapshot, timings);
            finalizeBuildTimings(timings, totalStarted);
            snapshot.buildTimings = timings;
            const stateStarted = performance.now();
            this.snapshotState.set(snapshot);
            timings.stateCommitMs = elapsedMs(stateStarted);
            const persistStarted = performance.now();
            await this.persistSnapshot(snapshot, timings, false).then(() => {
                this.errorState.set(null);
            }).catch((error) => {
                const message = error instanceof Error ? error.message : String(error);
                this.errorState.set(`Overgraph graph-rebuild snapshot persist failed: ${message}`);
                console.warn('[GraphRebuild] Snapshot persist failed', error);
            }).finally(() => {
                timings.snapshotPersistMs = elapsedMs(persistStarted);
            });
            finalizeBuildTimings(timings, totalStarted);
            snapshot.buildTimings = timings;
            this.lastBuildTimingsState.set(timings);
            return snapshot;
        } finally {
            this.buildingState.set(false);
        }
    }

    private async attachNativeGraphCompilerSidecar(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
    ): Promise<void> {
        const started = performance.now();
        try {
            const rawSidecar = await this.phoenix.storeCommand('graphRebuild:compileDualWrite', {
                snapshot: graphRebuildSnapshotToNativeCompilerPayload(snapshot),
            }) as NativeGraphCompilerSidecar | null;
            const sidecar = decodeNativeGraphCompilerSidecar(rawSidecar);
            if (!sidecar?.factGraph) return;
            attachGraphCompilerReadModels(snapshot, sidecar, 'rust');
        } catch (error) {
            console.warn('[GraphRebuild] Native graph compiler sidecar unavailable; using compatibility sidecar', error);
        } finally {
            if (timings) timings.nativeCompilerMs = elapsedMs(started);
        }
    }

    async loadPersistedSnapshot(scopeId: string): Promise<GraphRebuildSnapshot | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, SNAPSHOT_DOCUMENT_KEY);
        const snapshot = document ? scopedDocumentToGraphRebuildSnapshot(document) : null;
        return snapshot ? hydrateGraphRebuildSnapshotDerivedViews(snapshot) : null;
    }

    async loadPersistedGraphModelV2OverGraph(scopeId: string): Promise<GraphModelV2OverGraphExport | null> {
        const document = await this.store.getScopedDocument(scopeId, GRAPH_REBUILD_NAMESPACE, GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY);
        return document ? scopedDocumentToGraphModelV2OverGraphExport(document) : null;
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
        this.snapshotState.set(snapshot);
        await this.persistSnapshot(snapshot);
    }

    private async persistSnapshot(
        snapshot: GraphRebuildSnapshot,
        timings?: GraphRebuildBuildTimings,
        emitEvent = true,
    ): Promise<void> {
        const serializeStarted = performance.now();
        const persistedSnapshot = graphRebuildSnapshotPersistenceView(snapshot);
        const primaryEncodeStarted = performance.now();
        const document = graphRebuildSnapshotToScopedDocument(persistedSnapshot);
        if (timings) timings.snapshotPrimaryEncodeMs = elapsedMs(primaryEncodeStarted);
        const documentPayloadStats = graphRebuildSnapshotDocumentPayloadStats(document.payload);
        const overGraphEncodeStarted = performance.now();
        const overGraphDocument = graphModelV2OverGraphExportToScopedDocument(snapshot);
        if (timings) timings.snapshotOverGraphEncodeMs = elapsedMs(overGraphEncodeStarted);
        const overGraphDocumentPayloadStats = overGraphDocument
            ? graphRebuildSnapshotDocumentPayloadStats(overGraphDocument.payload)
            : undefined;
        if (timings) {
            const profileStarted = performance.now();
            timings.snapshotPayloadBreakdown = graphRebuildSnapshotPayloadCounters(
                persistedSnapshot,
                document.payload.length,
                overGraphDocument?.payload.length || 0,
                documentPayloadStats,
                overGraphDocumentPayloadStats,
            );
            timings.snapshotPayloadProfileMs = elapsedMs(profileStarted);
            timings.snapshotSerializeMs = elapsedMs(serializeStarted);
            timings.snapshotPayloadChars = document.payload.length;
            timings.snapshotPrimaryRawPayloadChars = documentPayloadStats.rawChars;
            timings.snapshotPrimaryCompressedBytes = documentPayloadStats.compressedBytes;
            timings.snapshotCompressionSavedChars = documentPayloadStats.savedChars;
            timings.snapshotCompressionRatioPct = documentPayloadStats.ratioPct;
            timings.snapshotOverGraphPayloadChars = overGraphDocument?.payload.length || 0;
            timings.snapshotOverGraphRawPayloadChars = overGraphDocumentPayloadStats?.rawChars || 0;
            timings.snapshotOverGraphCompressedBytes = overGraphDocumentPayloadStats?.compressedBytes || 0;
            timings.snapshotOverGraphCompressionSavedChars = overGraphDocumentPayloadStats?.savedChars || 0;
            timings.snapshotOverGraphCompressionRatioPct = overGraphDocumentPayloadStats?.ratioPct || 0;
            timings.snapshotTotalPayloadChars = document.payload.length + (overGraphDocument?.payload.length || 0);
        }
        const storeStarted = performance.now();
        const primaryStoreStarted = performance.now();
        await this.store.upsertScopedDocument(document);
        if (timings) timings.snapshotPrimaryStoreMs = elapsedMs(primaryStoreStarted);
        if (overGraphDocument) {
            const overGraphStoreStarted = performance.now();
            await this.store.upsertScopedDocument(overGraphDocument);
            if (timings) timings.snapshotOverGraphStoreMs = elapsedMs(overGraphStoreStarted);
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

    private async loadChunks(noteIds: string[], occurrences: EntityOccurrence[]): Promise<GraphRebuildChunk[]> {
        const scopedNoteIds = noteIds.length ? noteIds : [...new Set(occurrences.map((row) => row.noteId))];
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
        temporalEdges: snapshot.temporalEdges,
        causalEdges: snapshot.causalEdges,
        memoryState: snapshot.memoryState,
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: snapshot.nodes,
        edges: snapshot.edges,
        calendarRegistrySummary: snapshot.calendarRegistrySummary,
        counters: snapshot.counters,
    };
}

function anchorSpanStillMatches(
    noteId: string,
    start: number,
    end: number,
    surface: string,
    noteTexts?: Record<string, string>,
): boolean {
    if (!noteTexts || !Object.prototype.hasOwnProperty.call(noteTexts, noteId)) return true;
    const text = noteTexts[noteId] || '';
    if (start < 0 || end > text.length || end <= start) return false;
    return normalizeSurface(text.slice(start, end)).toLocaleLowerCase() === normalizeSurface(surface).toLocaleLowerCase();
}

export function mergeGraphRebuildOccurrences(
    persisted: EntityOccurrence[],
    recovered: EntityOccurrence[],
): EntityOccurrence[] {
    if (!persisted.length) return recovered;
    if (!recovered.length) return persisted;
    const seen = new Set(persisted.map(occurrenceKey));
    const merged = [...persisted];
    for (const occurrence of recovered) {
        const key = occurrenceKey(occurrence);
        if (seen.has(key)) continue;
        seen.add(key);
        merged.push(occurrence);
    }
    return merged;
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

function occurrenceKey(occurrence: EntityOccurrence): string {
    return `${occurrence.noteId}:${occurrence.entityId}:${occurrence.sourceStart}:${occurrence.sourceEnd}`;
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

export function graphRebuildSnapshotToScopedDocument(snapshot: GraphRebuildSnapshot): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${snapshot.scopeId}:${SNAPSHOT_DOCUMENT_KEY}`,
        scopeFolderId: snapshot.scopeId,
        narrativeId: snapshot.scopeKind === 'narrative' ? snapshot.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: SNAPSHOT_DOCUMENT_KEY,
        payload: encodeGraphRebuildSnapshotPayload(graphRebuildSnapshotPersistenceView(snapshot)),
        createdAt: snapshot.builtAt || now,
        updatedAt: now,
    };
}

export function graphRebuildSnapshotPersistenceView(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    const persisted = { ...snapshot };
    if (snapshot.graphCompiler && snapshot.graphModelV2) {
        delete persisted.graphCompiler;
    }
    if (snapshot.embeddingTargetPlan) {
        const { targets: _targets, ...plan } = snapshot.embeddingTargetPlan as GraphRebuildSnapshot['embeddingTargetPlan'] & {
            targets?: unknown;
        };
        persisted.embeddingTargetPlan = plan;
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

export function hydrateGraphRebuildSnapshotDerivedViews(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    if (!snapshot.embeddingTargets.length) return snapshot;
    let hydrated = snapshot;
    if (!hydrated.hopfResonanceSpace) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const hopfResonanceSpace = buildHopfResonanceSpace(hydrated, { generatedAt: hydrated.builtAt });
        if (hopfResonanceSpace.assignments.length !== hydrated.embeddingTargets.length) {
            throw new Error(
                `Hopf resonance hydration contract failed: ${hopfResonanceSpace.assignments.length} assignments for ${hydrated.embeddingTargets.length} embedding targets`,
            );
        }
        hydrated.hopfResonanceSpace = hopfResonanceSpace;
        hydrated.counters.hopfResonanceAssignments = hopfResonanceSpace.assignments.length;
        hydrated.counters.hopfResonanceOccupiedCells = hopfResonanceSpace.counters.occupiedCellCount;
        hydrated.counters.hopfResonanceFibers = hopfResonanceSpace.fibers.length;
        hydrated.counters.hopfResonanceDocCharts = hopfResonanceSpace.docCharts.length;
        hydrated.counters.hopfResonanceBraids = hopfResonanceSpace.braids.length;
        hydrated.counters.hopfResonanceDroppedTargets = hopfResonanceSpace.counters.droppedTargets;
        hydrated.counters.hopfResonanceMutationAllowed = hopfResonanceSpace.counters.mutationAllowedCount;
    }
    if (!hydrated.semanticRerankSummary && hydrated.semanticCandidateSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const semanticRerankSummary = buildGraphSemanticRerankSummary(
            hydrated,
            hydrated.semanticCandidateSummary,
            hydrated.manifoldSpecializationSummary,
            hydrated.builtAt,
        );
        hydrated.semanticRerankSummary = semanticRerankSummary;
        hydrated.counters.semanticRerankInputs = semanticRerankSummary.inputs.length;
        hydrated.counters.semanticRerankJudgments = semanticRerankSummary.judgments.length;
        hydrated.counters.semanticRerankReceipts = semanticRerankSummary.receipts.length;
        hydrated.counters.semanticRerankPlannedModelCalls = semanticRerankSummary.counters.plannedModelCalls;
        hydrated.counters.semanticRerankMutationAllowed = semanticRerankSummary.counters.mutationAllowedCount;
    }
    if (!hydrated.semanticAdjudicationSummary && hydrated.semanticCandidateSummary && hydrated.semanticRerankSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const semanticAdjudicationSummary = buildGraphSemanticAdjudicationDAGSummary(hydrated, hydrated.builtAt);
        hydrated.semanticAdjudicationSummary = semanticAdjudicationSummary;
        hydrated.counters.semanticAdjudicationDecisions = semanticAdjudicationSummary.decisions.length;
        hydrated.counters.semanticAdjudicationMutations = semanticAdjudicationSummary.mutations.length;
        hydrated.counters.semanticAdjudicationReceipts = semanticAdjudicationSummary.receipts.length;
        hydrated.counters.semanticAdjudicationTopologyCommits = semanticAdjudicationSummary.counters.topologyCommitCount;
        hydrated.counters.semanticAdjudicationLedgerOnly = semanticAdjudicationSummary.counters.ledgerOnlyCount;
    }
    if (
        !hydrated.semanticEvalLedgerSummary
        && hydrated.semanticCandidateSummary
        && hydrated.semanticRerankSummary
        && hydrated.semanticAdjudicationSummary
    ) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const semanticEvalLedgerSummary = buildGraphSemanticEvalLedgerSummary(hydrated, hydrated.builtAt);
        hydrated.semanticEvalLedgerSummary = semanticEvalLedgerSummary;
        hydrated.counters.semanticEvalLedgerRows = semanticEvalLedgerSummary.entries.length;
        hydrated.counters.semanticEvalAcceptedCandidates = semanticEvalLedgerSummary.counters.acceptedCandidates;
        hydrated.counters.semanticEvalRejectedCandidates = semanticEvalLedgerSummary.counters.rejectedCandidates;
        hydrated.counters.semanticEvalAmbiguousCases = semanticEvalLedgerSummary.counters.ambiguousCases;
        hydrated.counters.semanticEvalModelDisagreements = semanticEvalLedgerSummary.counters.modelDisagreements;
        hydrated.counters.semanticEvalManifoldDisagreements = semanticEvalLedgerSummary.counters.manifoldDisagreements;
        hydrated.counters.semanticEvalGraphChangeRows = semanticEvalLedgerSummary.counters.graphChangeRows;
    }
    if (!hydrated.memoryGraphRagBridgeSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const memoryGraphRagBridgeSummary = buildGraphMemoryGraphRagBridgeSummary(hydrated, hydrated.builtAt);
        hydrated.memoryGraphRagBridgeSummary = memoryGraphRagBridgeSummary;
        hydrated.counters.memoryGraphRagRecords = memoryGraphRagBridgeSummary.counters.recordCount;
        hydrated.counters.memoryGraphRagSchemaRecords = memoryGraphRagBridgeSummary.counters.schemaRecords;
        hydrated.counters.memoryGraphRagFactRecords = memoryGraphRagBridgeSummary.counters.factRecords;
        hydrated.counters.memoryGraphRagPassageRecords = memoryGraphRagBridgeSummary.counters.passageRecords;
        hydrated.counters.memoryGraphRagEvalRows = memoryGraphRagBridgeSummary.counters.evalRowCount;
        hydrated.counters.memoryGraphRagPassedEvalRows = memoryGraphRagBridgeSummary.counters.passedEvalRows;
        hydrated.counters.memoryGraphRagReceipts = memoryGraphRagBridgeSummary.counters.receiptCount;
        hydrated.counters.memoryGraphRagMutationAllowed = memoryGraphRagBridgeSummary.counters.mutationAllowedCount;
    }
    if (!hydrated.discourseSpineSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const discourseSpineSummary = buildGraphDiscourseSpineSummary(hydrated, hydrated.builtAt);
        hydrated.discourseSpineSummary = discourseSpineSummary;
        hydrated.counters.discourseSpineTargets = discourseSpineSummary.counters.targetCount;
        hydrated.counters.discourseSpineLabels = discourseSpineSummary.counters.labelCount;
        hydrated.counters.discourseSpineClusters = discourseSpineSummary.counters.clusterCount;
        hydrated.counters.discourseSpineBridges = discourseSpineSummary.counters.bridgeCount;
        hydrated.counters.discourseSpineResonance = discourseSpineSummary.counters.resonanceCandidates;
        hydrated.counters.discourseSpineResolution = discourseSpineSummary.counters.resolutionCandidates;
        hydrated.counters.discourseSpineReceipts = discourseSpineSummary.counters.receiptCount;
        hydrated.counters.discourseSpineMutationAllowed = discourseSpineSummary.counters.mutationAllowedCount;
    }
    if (!hydrated.discourseBridgeCandidateSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const discourseBridgeCandidateSummary = buildGraphDiscourseBridgeCandidateSummary(
            hydrated,
            hydrated.discourseSpineSummary,
            hydrated.builtAt,
        );
        hydrated.discourseBridgeCandidateSummary = discourseBridgeCandidateSummary;
        hydrated.counters.discourseBridgeCandidates = discourseBridgeCandidateSummary.counters.candidateCount;
        hydrated.counters.discourseBridgeInputs = discourseBridgeCandidateSummary.counters.inputCount;
        hydrated.counters.discourseBridgeJudgments = discourseBridgeCandidateSummary.counters.judgmentCount;
        hydrated.counters.discourseBridgeEvalRows = discourseBridgeCandidateSummary.counters.evalRowCount;
        hydrated.counters.discourseBridgeReceipts = discourseBridgeCandidateSummary.counters.receiptCount;
        hydrated.counters.discourseBridgePlannedModelCalls = discourseBridgeCandidateSummary.counters.plannedModelCalls;
        hydrated.counters.discourseBridgeMutationAllowed = discourseBridgeCandidateSummary.counters.mutationAllowedCount;
    }
    if (!hydrated.discourseBridgeAdjudicationSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const discourseBridgeAdjudicationSummary = buildGraphDiscourseBridgeAdjudicationSummary(
            hydrated,
            hydrated.discourseBridgeCandidateSummary,
            hydrated.builtAt,
        );
        hydrated.discourseBridgeAdjudicationSummary = discourseBridgeAdjudicationSummary;
        hydrated.counters.discourseBridgeAdjudicationDecisions = discourseBridgeAdjudicationSummary.counters.decisionCount;
        hydrated.counters.discourseBridgeAdjudicationAccepted = discourseBridgeAdjudicationSummary.counters.acceptedCount;
        hydrated.counters.discourseBridgeAdjudicationSupported = discourseBridgeAdjudicationSummary.counters.supportedCount;
        hydrated.counters.discourseBridgeAdjudicationDeferred = discourseBridgeAdjudicationSummary.counters.deferredCount;
        hydrated.counters.discourseBridgeAdjudicationRejected = discourseBridgeAdjudicationSummary.counters.rejectedCount;
        hydrated.counters.discourseBridgeAdjudicationReceipts = discourseBridgeAdjudicationSummary.counters.receiptCount;
        hydrated.counters.discourseBridgeAdjudicationLedgerOnly = discourseBridgeAdjudicationSummary.counters.ledgerOnlyCount;
        hydrated.counters.discourseBridgeAdjudicationTopologyCommits = discourseBridgeAdjudicationSummary.counters.topologyCommitCount;
        hydrated.counters.discourseBridgeAdjudicationMutationAllowed = discourseBridgeAdjudicationSummary.counters.mutationAllowedCount;
    }
    if (!hydrated.discourseEvalLedgerSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const discourseEvalLedgerSummary = buildGraphDiscourseEvalLedgerSummary(hydrated, hydrated.builtAt);
        hydrated.discourseEvalLedgerSummary = discourseEvalLedgerSummary;
        hydrated.counters.discourseEvalLedgerRows = discourseEvalLedgerSummary.counters.rowCount;
        hydrated.counters.discourseEvalAcceptedCandidates = discourseEvalLedgerSummary.counters.acceptedCandidates;
        hydrated.counters.discourseEvalRejectedCandidates = discourseEvalLedgerSummary.counters.rejectedCandidates;
        hydrated.counters.discourseEvalAmbiguousCases = discourseEvalLedgerSummary.counters.ambiguousCases;
        hydrated.counters.discourseEvalModelDisagreements = discourseEvalLedgerSummary.counters.modelDisagreements;
        hydrated.counters.discourseEvalManifoldDisagreements = discourseEvalLedgerSummary.counters.manifoldDisagreements;
        hydrated.counters.discourseEvalGraphChangeRows = discourseEvalLedgerSummary.counters.graphChangeRows;
    }
    if (!hydrated.discoursePromotionSurfaceSummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const discoursePromotionSurfaceSummary = buildGraphDiscoursePromotionSurfaceSummary(hydrated, hydrated.builtAt);
        hydrated.discoursePromotionSurfaceSummary = discoursePromotionSurfaceSummary;
        hydrated.counters.discoursePromotionChunkWormholes = discoursePromotionSurfaceSummary.counters.chunkWormholeCount;
        hydrated.counters.discoursePromotionDocumentClusters = discoursePromotionSurfaceSummary.counters.documentClusterCount;
        hydrated.counters.discoursePromotionResolverCandidates = discoursePromotionSurfaceSummary.counters.resolverCandidateCount;
        hydrated.counters.discoursePromotionCompilerHints = discoursePromotionSurfaceSummary.counters.compilerHintCount;
        hydrated.counters.discoursePromotionReceipts = discoursePromotionSurfaceSummary.counters.receiptCount;
        hydrated.counters.discoursePromotionGraphPatches = discoursePromotionSurfaceSummary.counters.graphPatchCount;
        hydrated.counters.discoursePromotionMutationAllowed = discoursePromotionSurfaceSummary.counters.mutationAllowedCount;
    }
    if (!hydrated.discourseCompilerOverlaySummary) {
        hydrated = cloneGraphRebuildSnapshotForHydration(hydrated);
        const discourseCompilerOverlaySummary = buildGraphDiscourseCompilerOverlaySummary(hydrated, hydrated.builtAt);
        hydrated.discourseCompilerOverlaySummary = discourseCompilerOverlaySummary;
        hydrated.counters.discourseCompilerOverlayEdges = discourseCompilerOverlaySummary.counters.overlayEdgeCount;
        hydrated.counters.discourseCompilerOverlayChunkWormholes = discourseCompilerOverlaySummary.counters.chunkWormholeEdges;
        hydrated.counters.discourseCompilerOverlayDocumentClusters = discourseCompilerOverlaySummary.counters.documentClusterEdges;
        hydrated.counters.discourseCompilerOverlayResolvers = discourseCompilerOverlaySummary.counters.resolverEdges;
        hydrated.counters.discourseCompilerOverlayReceipts = discourseCompilerOverlaySummary.counters.receiptCount;
        hydrated.counters.discourseCompilerOverlayGraphPatches = discourseCompilerOverlaySummary.counters.graphPatchCount;
        hydrated.counters.discourseCompilerOverlayMutationAllowed = discourseCompilerOverlaySummary.counters.mutationAllowedCount;
    }
    return hydrated;
}

function cloneGraphRebuildSnapshotForHydration(snapshot: GraphRebuildSnapshot): GraphRebuildSnapshot {
    return { ...snapshot, counters: { ...snapshot.counters } };
}

function encodeGraphRebuildSnapshotPayload(snapshot: GraphRebuildSnapshot): string {
    return encodeGraphRebuildJsonPayload(snapshot, snapshot.schemaVersion);
}

function encodeGraphRebuildJsonPayload(value: unknown, sourceSchemaVersion: string): string {
    const raw = JSON.stringify(value);
    if (raw.length < SNAPSHOT_COMPRESSION_MIN_CHARS) return raw;
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
        return encoded.length < raw.length ? encoded : raw;
    } catch {
        return raw;
    }
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
): GraphCompilerDualWriteSidecar | null {
    if (!sidecar) return null;
    if (sidecar.factGraph) return sidecar as GraphCompilerDualWriteSidecar;
    const compressed = sidecar.factGraphPayload;
    if (!isCompressedGraphCompilerFactGraphPayload(compressed)) return null;
    const factGraph = JSON.parse(strFromU8(gunzipSync(base64ToBytes(compressed.payload))));
    return {
        ...sidecar,
        factGraph,
    } as GraphCompilerDualWriteSidecar;
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
        snapshotBuildMs: 0,
        stateCommitMs: 0,
        nativeCompilerMs: 0,
        snapshotPersistMs: 0,
        snapshotSerializeMs: 0,
        snapshotPrimaryEncodeMs: 0,
        snapshotOverGraphEncodeMs: 0,
        snapshotStoreMs: 0,
        snapshotPrimaryStoreMs: 0,
        snapshotOverGraphStoreMs: 0,
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
];

function jsonPayloadChars(value: unknown): number {
    if (value === undefined) return 0;
    return JSON.stringify(value).length;
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
