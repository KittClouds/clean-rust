import { describe, expect, it } from 'vitest';
import { gzipSync, strFromU8, strToU8 } from 'fflate';

import {
    GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY,
    GRAPH_REBUILD_NAMESPACE,
    authorizeGraphRebuildSnapshotForLoad,
    decodeNativeGraphCompilerSidecar,
    graphModelV2OverGraphExportToScopedDocument,
    graphIndexReceiptToScopedDocument,
    graphRebuildSnapshotDocumentPayloadStats,
    graphRebuildSnapshotContentBlobDocuments,
    graphRebuildSnapshotPayloadCounters,
    graphRebuildSnapshotPersistenceView,
    graphRebuildSnapshotToNativeCompilerPayload,
    graphRebuildSnapshotToScopedDocument,
    attachInteractiveAtlasPacketForSnapshotTargets,
    filterNativeEmbeddingTargetsForCommittedSources,
    mergeGraphRebuildOccurrences,
    postProcessCacheToScopedDocument,
    reconcileNativeAtlasPacketForTargets,
    recoverGraphRebuildOccurrences,
    scopedDocumentToGraphModelV2OverGraphExport,
    scopedDocumentToGraphIndexReceipt,
    scopedDocumentToGraphRebuildContentBlob,
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

    it('filters native replacement targets that lack committed source rows', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', [])],
            occurrences: [],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 26, ordinal: 0, source: 'dynamic-chunking' }],
            noteTexts: { 'note-1': 'Kai exists in registry only.' },
            builtAt: 42,
        });
        const nativeTargets: GraphRebuildSnapshot['embeddingTargets'] = [
            {
                id: 'embed:note:note-1',
                kind: 'note',
                sourceId: 'note-1',
                noteId: 'note-1',
                label: 'Note note-1',
                text: 'note',
                evidenceIds: [],
            },
            {
                id: 'embed:structure-root:note-1:identity',
                kind: 'structureRoot',
                sourceId: 'note-1:identity',
                noteId: 'note-1',
                label: 'Identity root',
                text: 'identity',
                evidenceIds: [],
                lane: 'entity_anchor',
            },
            {
                id: 'embed:entity:entity-kai',
                kind: 'entity',
                sourceId: 'entity-kai',
                entityId: 'entity-kai',
                label: 'Kai',
                text: 'registry-only',
                evidenceIds: [],
                lane: 'entity_anchor',
            },
            {
                id: 'embed:atom:documentEvidence:evidence-1',
                kind: 'evidenceSpan',
                sourceId: 'evidence-1',
                label: 'Evidence',
                text: 'candidate evidence',
                evidenceIds: ['evidence-1'],
                lane: 'anchor_evidence',
            },
            {
                id: 'embed:fact:document-hyperedge:candidate',
                kind: 'graphFact',
                sourceId: 'fact:document-hyperedge:candidate',
                label: 'Candidate fact',
                text: 'candidate-only fact',
                evidenceIds: ['evidence-1'],
                lane: 'relationship_fact',
            },
        ];
        const packet = snapshotAtlasPacket({
            ...snapshot,
            embeddingTargets: nativeTargets,
            counters: { ...snapshot.counters, embeddingTargets: nativeTargets.length },
        });
        const filtered = filterNativeEmbeddingTargetsForCommittedSources(snapshot, nativeTargets);

        expect(filtered.map((target) => target.id)).toEqual([
            'embed:note:note-1',
            'embed:structure-root:note-1:identity',
        ]);
        snapshot.embeddingTargets = filtered;
        snapshot.counters.embeddingTargets = filtered.length;
        snapshot.atlasPacket = reconcileNativeAtlasPacketForTargets(snapshot, packet);
        expect(snapshot.atlasPacket.manifoldTargets.map((target) => target.id)).toEqual(
            filtered.map((target) => target.id),
        );
        expect(snapshot.atlasPacket.counters.manifoldTargets).toBe(filtered.length);
        expect(authorizeGraphRebuildSnapshotForLoad(snapshot)).toBe(snapshot);
    });

    it('builds interactive Atlas packets from committed targets without dropping visual metadata', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [],
            occurrences: [],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 26, ordinal: 0, source: 'dynamic-chunking' }],
            noteTexts: { 'note-1': 'A paragraph sits under a known document root.' },
            builtAt: 42,
        });
        const chunkTarget = snapshot.embeddingTargets.find((target) => target.kind === 'chunk');
        expect(chunkTarget).toBeTruthy();
        Object.assign(chunkTarget!, {
            documentUnitKind: 'chunk',
            stateContextKind: 'memory-state',
        });

        expect(attachInteractiveAtlasPacketForSnapshotTargets(snapshot)).toBe(true);
        const packetTarget = snapshot.atlasPacket?.manifoldTargets.find((target) => target.id === chunkTarget?.id);
        const packetObject = snapshot.atlasPacket?.objects.find((object) => object.targetIds.includes(chunkTarget!.id));

        expect(snapshot.atlasPacket?.sourceContract).toMatchObject({
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        });
        expect(packetTarget).toMatchObject({
            documentUnitKind: 'chunk',
            stateContextKind: 'memory-state',
        });
        expect(packetObject).toMatchObject({
            documentUnitKind: 'chunk',
            stateContextKind: 'memory-state',
        });
    });

    it('quarantines persisted snapshots that fail target source authority', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', [])],
            occurrences: [],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 26, ordinal: 0, source: 'dynamic-chunking' }],
            noteTexts: { 'note-1': 'Kai exists in registry only.' },
            builtAt: 42,
        });
        snapshot.atlasPacket = snapshotAtlasPacket(snapshot);
        const invalid: GraphRebuildSnapshot = {
            ...snapshot,
            embeddingTargets: [
                ...snapshot.embeddingTargets,
                {
                    id: 'embed:fact:document-hyperedge:candidate',
                    kind: 'graphFact',
                    sourceId: 'fact:document-hyperedge:candidate',
                    label: 'Candidate fact',
                    text: 'candidate-only fact',
                    evidenceIds: ['evidence-1'],
                    lane: 'relationship_fact',
                },
            ],
            counters: {
                ...snapshot.counters,
                embeddingTargets: snapshot.counters.embeddingTargets + 1,
            },
        };
        invalid.atlasPacket = snapshotAtlasPacket(invalid);
        const rejects: unknown[] = [];

        expect(authorizeGraphRebuildSnapshotForLoad(snapshot)).toBe(snapshot);
        expect(authorizeGraphRebuildSnapshotForLoad(invalid, (error) => rejects.push(error))).toBeNull();
        expect(String(rejects[0])).toContain('fact target lanes without source fact rows');
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
            documentGraphMutationLedger: {
                schemaVersion: 'phoenix-document-graph-mutation-ledger/v1',
                records: [{
                    id: 'document-graph-mutation:commit-1',
                    commitId: 'commit-1',
                    topologyDiffId: 'diff-1',
                    sourceObjectId: 'fact-1',
                    receiptId: 'receipt-1',
                    status: 'committed',
                    vertexIds: ['fact-vertex-1'],
                    edgeKeys: ['fact-vertex-1\u0000entity-1'],
                    committedAt: 99,
                }],
                counters: { commits: 1, active: 1, undone: 0, vertices: 1, edges: 1 },
            },
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
        expect(scopedDocumentToGraphRebuildSnapshot(document)).toEqual(graphRebuildSnapshotPersistenceView(snapshot));
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
        (snapshot as any).documentSidecarSummary = {
            units: Array.from({ length: 128 }, (_, index) => ({
                id: `unit:${index}`,
                noteId: 'note-1',
                kind: 'sentence',
                label: 'Disposable structure '.repeat(8),
            })),
            evidenceSpans: [
                evidenceSpan('ev-1', 0, 3),
                evidenceSpan('ev-2', 4, 12),
                evidenceSpan('ev-3', 13, 18),
                evidenceSpan('ev-unused', 19, 25),
            ],
        };
        (snapshot as any).documentReviewSummary = {
            rows: Array.from({ length: 160 }, (_, index) => ({
                id: `review:${index}`,
                objectId: `object:${index}`,
                objectKind: 'document_unit',
                state: 'proposed',
                title: 'Disposable review row',
                subtitle: 'Slim packet subtitle',
                detail: 'This should not be sent to native. '.repeat(32),
                noteId: 'note-1',
                sourceStart: 0,
                sourceEnd: 12,
                confidence: 0.5,
                detector: 'test-detector',
                parentUnitIds: [`parent:${index}`],
                childUnitIds: [`child:${index}`],
                evidenceSpanIds: ['ev-1'],
                relatedObjectIds: [`related:${index}`],
                why: ['Review UI only '.repeat(16)],
            })),
        };
        (snapshot as any).documentCompilerSummary = {
            relationCandidates: Array.from({ length: 64 }, (_, index) => ({
                id: `candidate:${index}`,
                predicate: 'candidate payload '.repeat(16),
            })),
            hyperedges: [{
                id: 'hyperedge:approved',
                predicate: 'approved',
                frame: 'approved',
                semanticSituationId: 'situation:approved',
                compilationBasis: 'semantic_situation_frame',
                temporalConflictIds: [],
                roles: [
                    { id: 'role:agent', role: 'agent', targetId: 'entity-kai', targetKind: 'entity', confidence: 0.9 },
                    { id: 'role:evidence', role: 'evidence', targetId: 'ev-2', targetKind: 'evidence_span', confidence: 0.8 },
                ],
                evidenceSpanIds: ['ev-1'],
                confidence: 0.92,
                status: 'pending_commit',
                provenance: {
                    sourceObjectId: 'situation:approved',
                    sourceObjectKind: 'semantic_situation',
                    noteId: 'note-1',
                    sourceStart: 0,
                    sourceEnd: 18,
                    evidenceSpanIds: ['ev-3'],
                    lineageUnitIds: [],
                    reasons: [],
                },
            }],
        };
        (snapshot as any).discourseSpineSummary = {
            targets: Array.from({ length: 128 }, (_, index) => ({
                targetId: `target:${index}`,
                sourceId: `source:${index}`,
                kind: 'chunk',
                label: 'Disposable discourse target '.repeat(8),
                parentTargetIds: [],
                entityIds: [],
            })),
            labels: [],
            clusters: [{
                id: 'cluster:1',
                kind: 'domain_region',
                label: 'Disposable discourse cluster '.repeat(8),
                targetIds: ['target:1', 'target:2'],
                medoidTargetId: 'target:1',
                score: 0.9,
                rationale: ['debug-only cluster rationale'],
                receiptId: 'receipt:cluster:1',
            }],
            bridges: [{
                id: 'bridge:1',
                kind: 'resonance',
                status: 'proposed',
                sourceTargetId: 'target:1',
                targetTargetId: 'target:2',
                sourceKind: 'chunk',
                targetKind: 'chunk',
                label: 'Disposable discourse bridge '.repeat(8),
                evidenceTargetIds: ['target:1', 'target:2'],
                sharedLabelIds: ['label:1'],
                sharedEntityIds: ['entity-kai'],
                scoringBundle: { finalScore: 0.92 },
                rationale: ['debug-only bridge rationale'],
                adjudicationState: 'proposed',
                mutationAllowed: false,
                receiptId: 'receipt:bridge:1',
                createdAt: 42,
            }],
        };

        const payload = graphRebuildSnapshotToNativeCompilerPayload(snapshot);

        expect(payload.chunks).toBe(snapshot.chunks);
        expect(payload.mentions).toBe(snapshot.mentions);
        expect(payload.entityAnchors).toBe(snapshot.entityAnchors);
        expect(payload.nodes).toBe(snapshot.nodes);
        expect(payload.edges).toBe(snapshot.edges);
        expect(payload.embeddingTargets).toEqual(
            snapshot.embeddingTargets.filter((target) => target.admissionStatus === 'admitted'),
        );
        expect(payload.embeddingVectors).toEqual([]);
        expect(payload.projectionRefs).toEqual([]);
        expect(payload.documentSidecarSummary?.evidenceSpans.map((span) => span.id).sort())
            .toEqual(['ev-1', 'ev-2', 'ev-3']);
        expect((payload.documentSidecarSummary as any).units).toBeUndefined();
        expect(payload.documentReviewSummary?.rows).toHaveLength(128);
        expect(payload.documentReviewSummary?.rows[0]).toMatchObject({
            id: 'review:0',
            objectId: 'object:0',
            state: 'proposed',
            detail: '',
            why: [],
            evidenceSpanIds: ['ev-1'],
        });
        expect((payload.documentReviewSummary as any).receipts).toBeUndefined();
        expect((payload.documentReviewSummary as any).counters).toBeUndefined();
        expect((payload.documentCompilerSummary as any).relationCandidates).toBeUndefined();
        expect(payload.documentCompilerSummary?.hyperedges).toHaveLength(1);
        expect(payload.discourseSpineSummary?.clusters).toHaveLength(1);
        expect(payload.discourseSpineSummary?.bridges).toHaveLength(1);
        expect((payload.discourseSpineSummary as any).targets).toBeUndefined();
        expect((payload.discourseSpineSummary as any).labels).toBeUndefined();
        expect((payload.discourseSpineSummary as any).receipts).toBeUndefined();
        expect((payload.discourseSpineSummary as any).counters).toBeUndefined();
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

    it('decodes one compressed Atlas seed without a duplicate target array', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global', scopeId: 'global', noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 3, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [occurrence('note-1', 'entity-kai', 0, 3)],
            noteTexts: { 'note-1': 'Kai' }, builtAt: 42,
        });
        const seed = {
            atlasPacket: snapshotAtlasPacket(snapshot),
            embeddingTargets: snapshot.embeddingTargets.slice(0, 2),
            originatingFamilies: [{ family: 'document_spine', targets: 2 }],
        };
        const raw = JSON.stringify(seed);
        const compressed = gzipSync(strToU8(raw), { level: 1 });
        const sidecar = decodeNativeGraphCompilerSidecar({
            atlasSeedPayload: {
                schemaVersion: 'phoenix-atlas-seed-payload/gzip-base64/v1',
                sourceSchemaVersion: 'phoenix-atlas-seed/v1', encoding: 'gzip+base64',
                rawBytes: strToU8(raw).byteLength, compressedBytes: compressed.byteLength,
                payload: btoa(strFromU8(compressed, true)),
            },
        });

        expect(sidecar?.atlasPacket).toEqual(seed.atlasPacket);
        expect(sidecar?.embeddingTargets).toEqual(seed.embeddingTargets);
        expect(sidecar?.originatingFamilies).toEqual(seed.originatingFamilies);
        expect(sidecar).not.toHaveProperty('atlasSeedPayload');
    });

    it('normalizes legacy compatibility-only Atlas builder roles from native seeds', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global', scopeId: 'global', noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 3, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [occurrence('note-1', 'entity-kai', 0, 3)],
            noteTexts: { 'note-1': 'Kai' }, builtAt: 42,
        });
        const atlasPacket = {
            ...snapshotAtlasPacket(snapshot),
            sourceContract: {
                ...snapshotAtlasPacket(snapshot).sourceContract,
                tsGraphBuilderRole: 'compatibility-only',
            },
        } as ReturnType<typeof snapshotAtlasPacket>;
        const seed = {
            atlasPacket,
            embeddingTargets: snapshot.embeddingTargets.slice(0, 2),
            originatingFamilies: [{ family: 'document_spine', targets: 2 }],
        };
        const raw = JSON.stringify(seed);
        const compressed = gzipSync(strToU8(raw), { level: 1 });

        const sidecar = decodeNativeGraphCompilerSidecar({
            atlasSeedPayload: {
                schemaVersion: 'phoenix-atlas-seed-payload/gzip-base64/v1',
                sourceSchemaVersion: 'phoenix-atlas-seed/v1', encoding: 'gzip+base64',
                rawBytes: strToU8(raw).byteLength, compressedBytes: compressed.byteLength,
                payload: btoa(strFromU8(compressed, true)),
            },
        });

        expect(sidecar?.atlasPacket?.sourceContract).toMatchObject({
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        });
    });

    it('decodes native snake-case compiler sidecars at the Rust boundary', () => {
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
            builtAt: 43,
        });
        const factGraph = snapshot.graphCompiler;
        if (!factGraph) throw new Error('Expected graph compiler output.');

        const sidecar = decodeNativeGraphCompilerSidecar({
            fact_graph: factGraph,
            projected_ui_graph: { nodes: [], edges: [] },
        } as never);

        expect(sidecar?.factGraph).toEqual(factGraph);
        expect(sidecar?.projectedUiGraph).toEqual({ nodes: [], edges: [] });
        expect(sidecar?.receipts).toEqual(factGraph.receipts);
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
        const blobDocuments = graphRebuildSnapshotContentBlobDocuments(snapshot);
        const embeddingTargetsBlob = blobDocuments.find((blob) =>
            blob.documentKey.includes(':embeddingTargets:'),
        );

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
        expect(counters['payloadContentManifestChars']).toBeGreaterThan(0);
        expect(counters['payloadEmbeddingTargetsChars']).toBe(JSON.stringify([]).length);
        expect(counters['payloadGraphModelV2Chars'] || 0).toBe(0);
        expect(counters['payloadGraphCompilerChars'] || 0).toBe(0);
        expect(embeddingTargetsBlob).toBeTruthy();
        expect(scopedDocumentToGraphRebuildContentBlob(embeddingTargetsBlob!)?.value)
            .toEqual(snapshot.embeddingTargets);
    });

    it('keeps Atlas content addresses stable across snapshot timestamps', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global', scopeId: 'global', noteIds: ['note-1'],
            entities: [entity('entity-kai', 'Kai', [])],
            chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 3, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [occurrence('note-1', 'entity-kai', 0, 3)],
            noteTexts: { 'note-1': 'Kai' }, builtAt: 42,
        });
        snapshot.atlasPacket = snapshotAtlasPacket(snapshot);
        const next = { ...snapshot, id: 'graph-rebuild:global:global:84', builtAt: 84 };
        next.atlasPacket = { ...snapshot.atlasPacket, snapshotId: next.id, builtAt: next.builtAt };
        const atlasKey = (value: GraphRebuildSnapshot) => graphRebuildSnapshotContentBlobDocuments(value)
            .find((document) => document.documentKey.includes(':atlasPacket:'))?.documentKey;

        expect(atlasKey(next)).toBe(atlasKey(snapshot));
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
        const targetPlanBlob = graphRebuildSnapshotContentBlobDocuments(snapshot).find((blob) =>
            blob.documentKey.includes(':embeddingTargetPlan:'),
        );
        const { targets: _targets, ...compactTargetPlan } = snapshot.embeddingTargetPlan as GraphRebuildSnapshot['embeddingTargetPlan'] & {
            targets?: unknown;
        };

        expect(persistedView.embeddingTargetPlan).toBeUndefined();
        expect(persisted?.embeddingTargetPlan).toBeUndefined();
        expect(persisted?.embeddingTargets).toEqual([]);
        expect(persisted?.contentManifest?.refs.embeddingTargetPlan?.itemCount)
            .toBeGreaterThan(0);
        expect(persisted?.contentManifest?.refs.embeddingTargets?.itemCount)
            .toBe(snapshot.embeddingTargets.length);
        expect(targetPlanBlob).toBeTruthy();
        const targetPlanBlobValue = scopedDocumentToGraphRebuildContentBlob(targetPlanBlob!)?.value;
        expect(targetPlanBlobValue).toEqual(compactTargetPlan);
        expect((targetPlanBlobValue as { targets?: unknown } | undefined)?.targets).toBeUndefined();
    });

    it('does not hydrate semantic decision views when they are absent from compact payloads', () => {
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
        expect(persistedView.semanticRerankSummary).toBeUndefined();
        expect(persistedView.semanticAdjudicationSummary).toBeUndefined();
        expect(persistedView.semanticEvalLedgerSummary).toBeUndefined();
        expect(persistedView.graphTruthCommitLedger).toBeUndefined();
        expect(persisted?.semanticTaskSummary).toBeUndefined();
        expect(persisted?.semanticRerankSummary).toBeUndefined();
        expect(persisted?.semanticAdjudicationSummary).toBeUndefined();
        expect(persisted?.semanticEvalLedgerSummary).toBeUndefined();
        expect(persisted?.graphTruthCommitLedger).toBeUndefined();
        expect(persisted?.semanticCandidateSummary).toBeUndefined();
        expect(persisted?.contentManifest?.refs.semanticCandidateSummary?.itemCount)
            .toBe(snapshot.semanticCandidateSummary?.candidates.length);
    });

    it('does not hydrate Hopf resonance when it is absent from compact payloads', () => {
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

        expect(persistedView.hopfResonanceSpace).toBeUndefined();
        expect(persisted?.hopfResonanceSpace).toBeUndefined();
        expect(persisted?.embeddingTargets).toEqual([]);
    });

    it('keeps heavy diagnostic summaries out of compact snapshot persistence', () => {
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
        (snapshot as GraphRebuildSnapshot & { atlasDebugSummaries?: unknown }).atlasDebugSummaries = {
            sentinel: 'debug-summary-must-not-persist',
            rows: Array.from({ length: 8 }, (_, index) => ({
                id: `debug:${index}`,
                detail: 'large debug payload '.repeat(64),
            })),
        };
        (snapshot as any).documentCompilerSummary = {
            ...(snapshot as any).documentCompilerSummary,
            hyperedges: [{
                id: 'diagnostic-hyperedge-must-not-persist',
                predicate: 'diagnostic',
                roles: [],
                evidenceSpanIds: [],
                confidence: 1,
                status: 'pending_commit',
            }],
        };

        expect(snapshot.documentReviewSummary?.rows.length).toBeGreaterThan(0);
        expect(snapshot.documentCompilerSummary?.hyperedges.length).toBeGreaterThan(0);
        expect(snapshot.discourseSpineSummary?.targets.length).toBeGreaterThan(0);
        expect(snapshot.discourseSpineSummary?.labels.length).toBeGreaterThan(0);

        const persistedView = graphRebuildSnapshotPersistenceView(snapshot);
        const document = graphRebuildSnapshotToScopedDocument(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(document);
        const blobDocuments = graphRebuildSnapshotContentBlobDocuments(snapshot);
        const blobPayloadText = JSON.stringify(blobDocuments
            .map((blob) => scopedDocumentToGraphRebuildContentBlob(blob)?.value)
            .filter(Boolean));

        expect(persistedView.documentReviewSummary).toBeUndefined();
        expect(persistedView.documentCompilerSummary).toBeUndefined();
        expect((persistedView as GraphRebuildSnapshot & { atlasDebugSummaries?: unknown }).atlasDebugSummaries).toBeUndefined();
        expect(persistedView.discourseSpineSummary).toBeUndefined();
        expect(persistedView.discourseBridgeCandidateSummary).toBeUndefined();
        expect(persistedView.discourseBridgeAdjudicationSummary).toBeUndefined();
        expect(persistedView.discourseEvalLedgerSummary).toBeUndefined();
        expect(persistedView.discoursePromotionSurfaceSummary).toBeUndefined();
        expect(persistedView.discourseCompilerOverlaySummary).toBeUndefined();
        expect(persisted?.documentReviewSummary).toBeUndefined();
        expect(persisted?.documentCompilerSummary).toBeUndefined();
        expect((persisted as (GraphRebuildSnapshot & { atlasDebugSummaries?: unknown }) | null)?.atlasDebugSummaries).toBeUndefined();
        expect(persisted?.discourseSpineSummary).toBeUndefined();
        expect(persisted?.discourseBridgeCandidateSummary).toBeUndefined();
        expect(persisted?.discourseBridgeAdjudicationSummary).toBeUndefined();
        expect(persisted?.discourseEvalLedgerSummary).toBeUndefined();
        expect(persisted?.discoursePromotionSurfaceSummary).toBeUndefined();
        expect(persisted?.discourseCompilerOverlaySummary).toBeUndefined();
        expect((persisted?.contentManifest?.refs as Record<string, unknown> | undefined)?.['atlasDebugSummaries']).toBeUndefined();
        expect(blobDocuments.some((blob) => blob.documentKey.includes('atlasDebugSummaries'))).toBe(false);
        expect(blobPayloadText).not.toContain('debug-summary-must-not-persist');
        expect(blobPayloadText).not.toContain('diagnostic-hyperedge-must-not-persist');
        expect(blobPayloadText).not.toContain('documentReviewSummary');
        expect(blobPayloadText).not.toContain('documentCompilerSummary');
    });

    it('does not hydrate MemoryGraphRAG bridge when it is absent from compact payloads', () => {
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

        expect(persistedView.memoryGraphRagBridgeSummary).toBeUndefined();
        expect(persisted?.memoryGraphRagBridgeSummary).toBeUndefined();
        expect(persisted?.semanticEvalLedgerSummary).toBeUndefined();
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
        expect(persisted?.graphModelV2).toBeUndefined();
        expect(persisted?.contentManifest?.refs.graphModelV2?.rawChars).toBeGreaterThan(0);
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
        const blobDocuments = graphRebuildSnapshotContentBlobDocuments(snapshot);
        const semanticBlob = blobDocuments.find((blob) =>
            blob.documentKey.includes(':semanticCandidateSummary:'),
        );
        const semanticBlobStats = semanticBlob
            ? graphRebuildSnapshotDocumentPayloadStats(semanticBlob.payload)
            : null;
        const semanticPayload = semanticBlob ? scopedDocumentToGraphRebuildContentBlob(semanticBlob) : null;

        expect(document.payload.length).toBeLessThan(rawChars);
        expect(persistedRawChars).toBeLessThan(rawChars);
        expect(persisted).toEqual(jsonPersistedSnapshot);
        expect(counters['snapshotPrimaryRawPayloadChars']).toBe(persistedRawChars);
        expect(semanticBlob).toBeTruthy();
        expect(semanticPayload?.value).toEqual(snapshot.semanticCandidateSummary);
        expect(semanticBlobStats?.savedChars).toBeGreaterThan(0);
        expect(semanticBlobStats?.ratioPct).toBeLessThan(100);
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

function evidenceSpan(id: string, start: number, end: number) {
    return {
        id,
        noteId: 'note-1',
        unitId: `unit:${id}`,
        chunkId: 'note-1:chunk:0',
        start,
        end,
        preview: `preview:${id}`,
        confidence: { score: 0.9 },
    };
}

function snapshotAtlasPacket(snapshot: GraphRebuildSnapshot): NonNullable<GraphRebuildSnapshot['atlasPacket']> {
    const objects = snapshot.embeddingTargets.map((target) => ({
        id: `atlas:${target.id}`,
        family: atlasFamily(target.kind),
        status: 'accepted' as const,
        kind: target.kind,
        label: target.label,
        styleKey: target.styleKey,
        lane: target.lane,
        structuralRole: target.structuralRole,
        registryEntityId: target.entityId,
        noteIds: target.noteId ? [target.noteId] : [],
        chunkIds: target.chunkId ? [target.chunkId] : [],
        anchorIds: target.kind === 'anchor' ? target.evidenceIds : [],
        evidenceIds: target.evidenceIds,
        sourceIds: [target.sourceId],
        targetIds: [],
    }));
    const familyCounts = new Map<string, number>();
    for (const object of objects) familyCounts.set(object.family, (familyCounts.get(object.family) || 0) + 1);
    return {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: snapshot.id,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        sourceContract: {
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            vectorContract: 'vectors-missing',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        },
        objects,
        manifoldTargets: snapshot.embeddingTargets.map((target) => ({
            id: target.id,
            objectId: `atlas:${target.id}`,
            family: atlasFamily(target.kind),
            admission: target.admissionStatus === 'deferred' ? 'deferred' : 'admitted',
            vectorStatus: 'missing',
            coordinateSource: 'none',
            status: 'accepted',
            kind: target.kind,
            label: target.label,
            entityKind: target.entityKind,
            styleKey: target.styleKey,
            lane: target.lane,
            structuralRole: target.structuralRole,
            sourceId: target.sourceId,
            registryEntityId: target.entityId,
            noteId: target.noteId,
            chunkId: target.chunkId,
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds,
        })),
        counters: {
            objects: objects.length,
            manifoldTargets: snapshot.embeddingTargets.length,
            registryEntities: snapshot.nodes.length,
            evidenceAnchors: snapshot.entityAnchors.length,
            modelVectors: 0,
            families: [...familyCounts.entries()]
                .sort(([left], [right]) => left.localeCompare(right))
                .map(([family, count]) => ({ family: family as ReturnType<typeof atlasFamily>, count })),
        },
    };
}

function atlasFamily(kind: string): NonNullable<GraphRebuildSnapshot['atlasPacket']>['objects'][number]['family'] {
    if (kind === 'entity') return 'registry';
    if (kind === 'note' || kind === 'chunk' || kind === 'structureRoot' || kind === 'documentUnit') return 'structure';
    if (kind === 'anchor' || kind === 'evidenceSpan') return 'evidence';
    if (kind === 'temporalFact') return 'temporal';
    if (kind === 'causalFact') return 'causal';
    if (kind === 'memoryState') return 'memory';
    if (kind === 'graphFact' || kind === 'event') return 'fact';
    return 'unknown';
}

