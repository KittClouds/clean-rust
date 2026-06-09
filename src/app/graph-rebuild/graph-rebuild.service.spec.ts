import { describe, expect, it } from 'vitest';
import { gzipSync, strFromU8, strToU8 } from 'fflate';

import {
    GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY,
    GRAPH_REBUILD_NAMESPACE,
    decodeNativeGraphCompilerSidecar,
    graphModelV2OverGraphExportToScopedDocument,
    graphIndexReceiptToScopedDocument,
    graphRebuildSnapshotDocumentPayloadStats,
    graphRebuildSnapshotPayloadCounters,
    graphRebuildSnapshotPersistenceView,
    graphRebuildSnapshotToNativeCompilerPayload,
    graphRebuildSnapshotToScopedDocument,
    hydrateGraphRebuildSnapshotDerivedViews,
    mergeGraphRebuildOccurrences,
    postProcessCacheToScopedDocument,
    recoverGraphRebuildOccurrences,
    scopedDocumentToGraphModelV2OverGraphExport,
    scopedDocumentToGraphIndexReceipt,
    scopedDocumentToGraphRebuildSnapshot,
    snapshotAnchorsToGraphRebuildOccurrences,
    dynamicChunksForNote,
} from './graph-rebuild.service';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { GraphIndexRunReceipt, GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';

describe('GraphRebuildService persistence helpers', () => {
    it('uses the Full Atlas dynamic chunking contract instead of note-block lines', () => {
        const text = Array.from({ length: 70 }, (_, index) =>
            `Sentence ${index} keeps Kai and Hazel inside a realistic narrative beat for chunk packing.`,
        ).join(' ');
        const chunks = dynamicChunksForNote({ id: 'note-1', markdownContent: text, content: '' });

        expect(chunks.length).toBeGreaterThan(1);
        expect(chunks.length).toBeLessThan(8);
        expect(chunks.every((chunk) => chunk.source === 'dynamic-chunking')).toBe(true);
        expect(chunks[0].id).toBe('note-1:chunk:0');
    });

    it('keeps a 5.5k-word narrative smoke near the 22-chunk target', () => {
        const text = smokeNarrative(5563);
        const chunks = dynamicChunksForNote({ id: 'release-terms', markdownContent: text, content: '' });

        expect(chunks.length).toBeGreaterThanOrEqual(18);
        expect(chunks.length).toBeLessThanOrEqual(28);
    });

    it('recovers graph anchors from loaded note text when the occurrence table is cold', () => {
        const entities = [
            entity('entity-kai', 'Kai', []),
            entity('entity-red-mesa', 'Red Mesa', [], 'LOCATION'),
            entity('entity-allied-table', 'Allied Table', [], 'NETWORK'),
        ];
        const noteTexts = {
            'note-1': 'Kai mapped Red Mesa before the Allied Table answered.',
            'note-2': 'The Allied Table sent Kai back toward Red Mesa.',
        };
        const recovered = recoverGraphRebuildOccurrences(noteTexts, entities, 42);
        const merged = mergeGraphRebuildOccurrences([
            occurrence('note-1', 'entity-kai', 0, 3),
        ], recovered);
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
            entities,
            occurrences: merged,
            chunks: [
                { id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 52, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-2:chunk:0', noteId: 'note-2', start: 0, end: 49, ordinal: 1, source: 'dynamic-chunking' },
            ],
            noteTexts,
            builtAt: 42,
        });

        expect(recovered.map((row) => row.entityId)).toEqual(expect.arrayContaining([
            'entity-kai',
            'entity-red-mesa',
            'entity-allied-table',
        ]));
        expect(merged.filter((row) => row.entityId === 'entity-kai')).toHaveLength(2);
        expect(snapshot.nodes.map((node) => node.id).sort()).toEqual([
            'entity-allied-table',
            'entity-kai',
            'entity-red-mesa',
        ]);
        expect(snapshot.embeddingTargets.filter((target) => target.kind === 'entity')).toHaveLength(3);
        expect(snapshot.embeddingTargetPlan?.lanes.find((lane) => lane.lane === 'anchor_evidence')?.candidates).toBeGreaterThan(3);
        expect(snapshot.embeddingTargets.filter((target) => target.kind === 'anchor').length).toBeGreaterThan(0);
    });

    it('can carry cached snapshot anchors back into postprocess occurrence input', () => {
        const entities = [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])];
        const cached = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:note-1',
            noteIds: ['note-1'],
            entities,
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 32, ordinal: 0, source: 'dynamic-chunking' }],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });
        const fallback = snapshotAnchorsToGraphRebuildOccurrences(cached, 84);
        const rebuilt = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:note-1',
            noteIds: ['note-1'],
            entities,
            occurrences: fallback,
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 32, ordinal: 0, source: 'dynamic-chunking' }],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 84,
        });

        expect(fallback).toHaveLength(2);
        expect(fallback.map((row) => row.entityId).sort()).toEqual(['entity-hazel', 'entity-kai']);
        expect(rebuilt.counters.acceptedAnchors).toBe(2);
        expect(rebuilt.counters.nodes).toBe(2);
    });

    it('roundtrips explicit graph snapshots through Overgraph scoped documents', () => {
        const snapshot: GraphRebuildSnapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'graph-rebuild:global:1',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 100,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: {
                entities: 2,
                aliases: 1,
                candidates: 0,
                mentions: 0,
                acceptedAnchors: 0,
                chunks: 0,
                relationshipCandidates: 0,
                relationships: 0,
                acceptedRelationships: 0,
                reviewRelationships: 0,
                rejectedRelationships: 0,
                events: 0,
                episodes: 0,
                temporalEdges: 0,
                causalEdges: 0,
                memoryState: 0,
                embeddingTargets: 0,
                embeddingVectors: 0,
                projectionRefs: 0,
                nodes: 0,
                edges: 0,
                dropReasons: {
                    missingEntity: 0,
                    invalidSpan: 0,
                    duplicateAnchor: 0,
                    singletonBucket: 0,
                    missingChunk: 0,
                },
            },
        };

        const document = graphRebuildSnapshotToScopedDocument(snapshot);

        expect(document.namespace).toBe(GRAPH_REBUILD_NAMESPACE);
        expect(document.scopeFolderId).toBe('global');
        expect(scopedDocumentToGraphRebuildSnapshot(document)).toEqual(snapshot);
    });

    it('roundtrips Full Atlas Index receipts through Overgraph scoped documents', () => {
        const receipt: GraphIndexRunReceipt = {
            schemaVersion: 'phoenix-graph-index-run/v1',
            id: 'full-atlas:global:1',
            scope: { kind: 'global', scopeId: 'global', label: 'Global', noteIds: ['note-1'] },
            policy: 'delta',
            delta: true,
            status: 'completed',
            modelSelection: {
                dynamicNerId: 'dynamic_ner',
                embeddingModelId: 'mongodb-leaf-mt',
                embeddingModelLabel: 'MDBR Leaf MT',
                embeddingDimensionLabel: '384d',
                nliModelId: 'modernbert-nli',
            },
            modelReadiness: [],
            startedAt: 100,
            completedAt: 120,
            durationMs: 20,
            stageReceipts: [],
            projectionReceipts: [],
            snapshotId: 'graph-rebuild:global:1',
            counters: {
                entities: 2,
                aliases: 1,
                candidates: 2,
                mentions: 2,
                acceptedAnchors: 2,
                chunks: 1,
                relationshipCandidates: 0,
                relationships: 0,
                acceptedRelationships: 0,
                reviewRelationships: 0,
                rejectedRelationships: 0,
                events: 0,
                episodes: 0,
                temporalEdges: 0,
                causalEdges: 0,
                memoryState: 0,
                embeddingTargets: 0,
                embeddingVectors: 0,
                projectionRefs: 0,
                nodes: 2,
                edges: 1,
                dropReasons: {
                    missingEntity: 0,
                    invalidSpan: 0,
                    duplicateAnchor: 0,
                    singletonBucket: 0,
                    missingChunk: 0,
                },
            },
            dropReasons: {
                missingEntity: 0,
                invalidSpan: 0,
                duplicateAnchor: 0,
                singletonBucket: 0,
                missingChunk: 0,
            },
            message: 'Full Atlas Index built 2 nodes and 1 edges.',
        };

        const document = graphIndexReceiptToScopedDocument(receipt);

        expect(document.namespace).toBe(GRAPH_REBUILD_NAMESPACE);
        expect(document.scopeFolderId).toBe('global');
        expect(scopedDocumentToGraphIndexReceipt(document)).toEqual(receipt);
    });

    it('persists graph model v2 as a separate OverGraph export sidecar', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });
        if (!snapshot.graphModelV2?.atoms.length) throw new Error('Expected graph model atoms.');
        const styleTargetId = snapshot.graphModelV2.atoms[0].id;
        for (let index = 0; index < 1024; index += 1) {
            snapshot.graphModelV2.styleTags.push({
                targetId: styleTargetId,
                targetType: 'atom',
                tagKind: 'storySignal',
                value: `overgraph-compression-receipt-${index}:`
                    + 'Kai and Hazel repeat a deliberately large sidecar payload. '.repeat(2),
            });
        }

        const document = graphModelV2OverGraphExportToScopedDocument(snapshot);
        const roundtripped = document ? scopedDocumentToGraphModelV2OverGraphExport(document) : null;
        const stats = document ? graphRebuildSnapshotDocumentPayloadStats(document.payload) : null;

        expect(document?.namespace).toBe(GRAPH_REBUILD_NAMESPACE);
        expect(document?.documentKey).toBe(GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY);
        expect(stats?.savedChars).toBeGreaterThan(0);
        expect(stats?.ratioPct).toBeLessThan(100);
        expect(roundtripped?.schemaVersion).toBe('phoenix-graph-model-v2-overgraph/v1');
        const expectedVertices = (snapshot.graphModelV2?.counters.atoms || 0)
            + (snapshot.graphModelV2?.counters.facts || 0);
        expect(roundtripped?.graphBatch.vertices.length).toBe(expectedVertices);
        expect(roundtripped?.summary.bundleReceipts).toBe(snapshot.graphModelV2?.counters.bundles || 0);
        expect(roundtripped?.graphBatch.edges.some((edge) => edge.edgeType === 'role:source')).toBe(true);
    });

    it('sends only compiler-owned structural fields to the native graph compiler', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });
        (snapshot as GraphRebuildSnapshot & { semanticCandidateSummary: unknown }).semanticCandidateSummary = {
            rows: Array.from({ length: 256 }, (_, index) => ({
                id: `candidate:${index}`,
                text: 'This payload belongs to browser receipts, not the Rust compiler call. '.repeat(12),
            })),
        };

        const payload = graphRebuildSnapshotToNativeCompilerPayload(snapshot);

        expect(payload.chunks).toBe(snapshot.chunks);
        expect(payload.mentions).toBe(snapshot.mentions);
        expect(payload.entityAnchors).toBe(snapshot.entityAnchors);
        expect(payload.nodes).toBe(snapshot.nodes);
        expect(payload.edges).toBe(snapshot.edges);
        expect(payload.embeddingTargets).toEqual([]);
        expect(payload.embeddingVectors).toEqual([]);
        expect(payload.projectionRefs).toEqual([]);
        expect(payload.graphModelV2).toBeUndefined();
        expect(payload.semanticCandidateSummary).toBeUndefined();
        expect(JSON.stringify(payload).length).toBeLessThan(JSON.stringify(snapshot).length / 2);
    });

    it('decodes compressed native graph compiler sidecars without changing the compiler contract', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });
        const factGraph = snapshot.graphCompiler;
        if (!factGraph) throw new Error('Expected graph compiler output.');
        const raw = JSON.stringify(factGraph);
        const compressed = gzipSync(strToU8(raw), { level: 1 });
        const sidecar = decodeNativeGraphCompilerSidecar({
            factGraphPayload: {
                schemaVersion: 'phoenix-graph-compiler-payload/gzip-base64/v1',
                sourceSchemaVersion: factGraph.schemaVersion,
                encoding: 'gzip+base64',
                rawBytes: raw.length,
                compressedBytes: compressed.byteLength,
                payload: btoa(strFromU8(compressed, true)),
            },
        });

        expect(sidecar?.factGraph).toEqual(factGraph);
        expect(sidecar?.projectedUiGraph).toBeUndefined();
    });

    it('profiles snapshot payload sections without changing the scoped document contract', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const overGraphDocument = graphModelV2OverGraphExportToScopedDocument(snapshot);

        const persistedSnapshot = graphRebuildSnapshotPersistenceView(snapshot);
        const counters = graphRebuildSnapshotPayloadCounters(
            persistedSnapshot,
            document.payload.length,
            overGraphDocument?.payload.length || 0,
            graphRebuildSnapshotDocumentPayloadStats(document.payload),
            overGraphDocument ? graphRebuildSnapshotDocumentPayloadStats(overGraphDocument.payload) : undefined,
        );

        expect(counters['snapshotPrimaryPayloadChars']).toBe(document.payload.length);
        expect(counters['snapshotOverGraphPayloadChars']).toBe(overGraphDocument?.payload.length || 0);
        expect(counters['snapshotOverGraphRawPayloadChars']).toBeGreaterThanOrEqual(
            counters['snapshotOverGraphPayloadChars'],
        );
        expect(counters['snapshotTotalScopedPayloadChars']).toBe(
            document.payload.length + (overGraphDocument?.payload.length || 0),
        );
        expect(counters['payloadEmbeddingTargetsChars']).toBeGreaterThan(0);
        expect(counters['payloadGraphModelV2Chars']).toBeGreaterThan(0);
        expect(counters['payloadGraphCompilerChars'] || 0).toBe(0);
    });

    it('persists the embedding target plan as lane/count receipts, not duplicate target rows', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });

        expect((snapshot.embeddingTargetPlan as GraphRebuildSnapshot['embeddingTargetPlan'] & { targets?: unknown[] })?.targets?.length)
            .toBe(snapshot.embeddingTargets.length);

        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);

        expect((persistedView.embeddingTargetPlan as GraphRebuildSnapshot['embeddingTargetPlan'] & { targets?: unknown[] })?.targets)
            .toBeUndefined();
        expect((persisted?.embeddingTargetPlan as GraphRebuildSnapshot['embeddingTargetPlan'] & { targets?: unknown[] })?.targets)
            .toBeUndefined();
        expect(persisted?.embeddingTargetPlan?.lanes).toEqual(snapshot.embeddingTargetPlan?.lanes);
        expect(persisted?.embeddingTargetPlan?.candidateCount).toBe(snapshot.embeddingTargetPlan?.candidateCount);
        expect(persisted?.embeddingTargets).toEqual(snapshot.embeddingTargets);
    });

    it('keeps semantic task plans in memory without making them durable reload payload', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });

        expect(snapshot.semanticTaskSummary?.tasks.length).toBeGreaterThan(0);

        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);

        expect(persistedView.semanticTaskSummary).toBeUndefined();
        expect(persisted?.semanticTaskSummary).toBeUndefined();
        expect(persisted?.semanticCandidateSummary).toEqual(snapshot.semanticCandidateSummary);
        expect(persisted?.semanticRerankSummary).toEqual(snapshot.semanticRerankSummary);
        expect(persisted?.semanticEvalLedgerSummary).toEqual(snapshot.semanticEvalLedgerSummary);
    });

    it('hydrates Hopf resonance as a derived reload view instead of durable payload bulk', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });

        expect(snapshot.hopfResonanceSpace?.assignments.length).toBe(snapshot.embeddingTargets.length);

        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);
        const hydrated = persisted ? hydrateGraphRebuildSnapshotDerivedViews(persisted) : null;

        expect(persistedView.hopfResonanceSpace).toBeUndefined();
        expect(persisted?.hopfResonanceSpace).toBeUndefined();
        expect(hydrated?.hopfResonanceSpace).toEqual(snapshot.hopfResonanceSpace);
        expect(hydrated?.counters.hopfResonanceAssignments).toBe(snapshot.counters.hopfResonanceAssignments);
        expect(hydrated?.embeddingTargets).toEqual(snapshot.embeddingTargets);
    });

    it('hydrates discourse spine as a derived reload view instead of durable payload bulk', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });

        expect(snapshot.discourseSpineSummary?.targets.length).toBeGreaterThan(0);
        expect(snapshot.discourseSpineSummary?.labels.length).toBeGreaterThan(0);

        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);
        const hydrated = persisted ? hydrateGraphRebuildSnapshotDerivedViews(persisted) : null;

        expect(persistedView.discourseSpineSummary).toBeUndefined();
        expect(persisted?.discourseSpineSummary).toBeUndefined();
        expect(hydrated?.discourseSpineSummary).toEqual(snapshot.discourseSpineSummary);
        expect(hydrated?.counters.discourseSpineTargets).toBe(snapshot.counters.discourseSpineTargets);
        expect(hydrated?.discourseBridgeCandidateSummary).toEqual(snapshot.discourseBridgeCandidateSummary);
    });

    it('hydrates MemoryGraphRAG bridge as a derived reload view instead of durable payload bulk', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });

        expect(snapshot.memoryGraphRagBridgeSummary?.schemaVersion).toBe('phoenix-memory-graphrag-bridge/v1');
        expect(snapshot.memoryGraphRagBridgeSummary?.records.length).toBeGreaterThan(0);

        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);
        const hydrated = persisted ? hydrateGraphRebuildSnapshotDerivedViews(persisted) : null;

        expect(persistedView.memoryGraphRagBridgeSummary).toBeUndefined();
        expect(persisted?.memoryGraphRagBridgeSummary).toBeUndefined();
        expect(hydrated?.memoryGraphRagBridgeSummary).toEqual(snapshot.memoryGraphRagBridgeSummary);
        expect(hydrated?.counters.memoryGraphRagRecords).toBe(snapshot.counters.memoryGraphRagRecords);
        expect(hydrated?.semanticEvalLedgerSummary).toEqual(snapshot.semanticEvalLedgerSummary);
    });

    it('persists graph compiler as a derived in-memory sidecar, not primary snapshot payload', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });

        expect(snapshot.graphCompiler).toBeTruthy();
        expect(snapshot.graphModelV2).toBeTruthy();

        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);

        expect(persisted?.graphCompiler).toBeUndefined();
        expect(persisted?.graphModelV2).toEqual(snapshot.graphModelV2);
        expect(persisted?.graphCompileReceipts).toEqual(snapshot.graphCompileReceipts);
        expect(snapshot.graphCompiler).toBeTruthy();
    });

    it('compresses large persisted graph rebuild snapshots and round-trips them', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', []), entity('entity-hazel', 'Hazel', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 30, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('note-1', 'entity-kai', 0, 3),
                occurrence('note-1', 'entity-hazel', 12, 17),
            ],
            noteTexts: { 'note-1': 'Kai approved Hazel.' },
            builtAt: 42,
        });
        (snapshot as GraphRebuildSnapshot & { semanticCandidateSummary: unknown }).semanticCandidateSummary = {
            rows: Array.from({ length: 256 }, (_, index) => ({
                id: `candidate:${index}`,
                text: 'Kai and Hazel carry a deliberately repeated persistence payload. '.repeat(12),
            })),
        };

        const rawChars = JSON.stringify(snapshot).length;
        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const persistedRawChars = JSON.stringify(persistedView).length;
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);
        const jsonPersistedSnapshot = JSON.parse(JSON.stringify(persistedView));
        const stats = graphRebuildSnapshotDocumentPayloadStats(document.payload);
        const counters = graphRebuildSnapshotPayloadCounters(persistedView, document.payload.length, 0, stats);

        expect(document.payload.length).toBeLessThan(rawChars);
        expect(document.payload.length).toBeLessThan(persistedRawChars);
        expect(persisted).toEqual(jsonPersistedSnapshot);
        expect(counters['snapshotPrimaryRawPayloadChars']).toBe(persistedRawChars);
        expect(counters['snapshotCompressionSavedChars']).toBeGreaterThan(0);
        expect(counters['snapshotCompressionRatioPct']).toBeLessThan(100);
    });

    it('keeps postprocess cache documents as lightweight snapshot references', () => {
        const document = postProcessCacheToScopedDocument({
            schemaVersion: 'phoenix-graph-postprocess-cache/v1',
            scopeId: 'global',
            scopeKind: 'global',
            fingerprint: 'fp-1',
            snapshotId: 'snapshot-1',
            receiptId: 'receipt-1',
            receipt: { id: 'receipt-1' } as GraphIndexRunReceipt,
            updatedAt: 42,
        });
        const payload = JSON.parse(document.payload);

        expect(payload.snapshot).toBeUndefined();
        expect(payload.snapshotId).toBe('snapshot-1');
        expect(payload.receiptId).toBe('receipt-1');
    });
});

function smokeNarrative(wordCount: number): string {
    const terms = ['Kai', 'Hazel', 'Tempest', 'Nereus', 'Nemo', 'packet', 'release', 'terms', 'family', 'command'];
    const words = Array.from({ length: wordCount }, (_, index) => terms[index % terms.length]);
    const sentences: string[] = [];
    for (let index = 0; index < words.length; index += 18) {
        sentences.push(`${words.slice(index, index + 18).join(' ')}.`);
    }
    return sentences.join(' ');
}

function entity(id: string, label: string, aliases: string[], kind = 'CHARACTER'): RegisteredEntity {
    return {
        id,
        label,
        kind: kind as any,
        aliases,
        firstNote: `${id}-note`,
        mentionsByNote: new Map(),
        totalMentions: 0,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
    };
}

function occurrence(noteId: string, entityId: string, sourceStart: number, sourceEnd: number): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}:${sourceStart}:${sourceEnd}:dictionary_match`,
        noteId,
        entityId,
        entityLabel: entityId,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd,
        surface: entityId,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: entityId,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}

