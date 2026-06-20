import { describe, expect, it } from 'vitest';
import { DEFAULT_ENTITY_COLORS, DEFAULT_GRAPH_NODE_COLORS } from '../../../../../lib/store/entityColorStore';
import type { NoteBlockProjection } from '../../../../../lib/dexie/db';
import { buildGraphAtlasTaxonomyAudit } from '../../../../../graph-rebuild/graph-atlas-taxonomy-audit';
import { buildGraphModelV2Snapshot } from '../../../../../graph-rebuild/graph-model-v2';
import { buildLeafEmbeddingAtlas } from './graph-embedding-atlas';
import { buildGraphRebuildEmbeddingAtlas, graphRebuildEmbeddingTargetCount } from './graph-rebuild-embedding-atlas';
import { buildGalaxyScene, mergeGalaxySettings } from './graph-galaxy-engine';

function block(id: string, text: string, ordinal: number): NoteBlockProjection {
    return {
        id,
        noteId: 'note-1',
        worldId: 'world-1',
        narrativeId: 'narrative-1',
        folderId: 'folder-1',
        ordinal,
        path: `block-${ordinal}`,
        nodeType: 'paragraph',
        text,
        textHash: id,
        startOffset: ordinal * 10,
        endOffset: ordinal * 10 + text.length,
        lineCount: 1,
        updatedAt: 1,
    };
}

function hopfPost(targetId: string, medoidTargetId: string, phase: number) {
    return {
        targetId,
        clusterId: 'embedding-cluster:0',
        clusterRole: 'entity_region',
        medoidTargetId,
        outlierScore: 0.1,
        hubScore: 0.6,
        neighborCount: 1,
        productLaneFeatures: {
            semanticDepth: 0.8,
            documentDepth: 0.2,
            relationDepth: 0.2,
            clusterRadius: 0.35,
            fiberPhase: phase,
            confidence: 0.86,
            dominantLane: 'entity',
            laneWeights: {
                semantic: 0.8,
                document: 0.2,
                relation: 0.2,
                temporal: 0.1,
                causal: 0.1,
                evidence: 0.12,
                entity: 0.9,
            },
        },
        productTopologyRegion: {
            id: 'product-region:embedding-cluster:0:entity:core',
            role: 'core',
            laneKind: 'entity',
            clusterId: 'embedding-cluster:0',
            medoidTargetId,
            memberCount: 2,
            density: 0.8,
            confidence: 0.9,
            bridgeTargetIds: [],
            backboneTargetIds: [],
        },
    };
}

function overloadedHopfPost(targetId: string, medoidTargetId: string, phase: number, kind: string) {
    const laneKind = kind === 'chunk' ? 'document' : kind === 'graphFact' ? 'relation' : 'entity';
    const post = hopfPost(targetId, medoidTargetId, phase);
    return {
        ...post,
        productLaneFeatures: {
            ...post.productLaneFeatures,
            dominantLane: laneKind,
        },
        productTopologyRegion: {
            ...post.productTopologyRegion,
            id: `product-region:embedding-cluster:0:${laneKind}:core`,
            laneKind,
            memberCount: 140,
        },
    };
}

function dot3(left: number[], right: number[]): number {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

function average3(left: number[], right: number[]): number[] {
    const x = left[0] + right[0];
    const y = left[1] + right[1];
    const z = left[2] + right[2];
    const norm = Math.max(0.000001, Math.hypot(x, y, z));
    return [x / norm, y / norm, z / norm];
}

describe('embedding atlas projection', () => {
    it('places embedding nodes on a sphere shell instead of an axis-clamped box', () => {
        const atlas = buildLeafEmbeddingAtlas([
            block('a', 'Aella and Kai crossed the lantern refuge.', 0),
            block('b', 'Iriane watched the rain and named the seam.', 1),
            block('c', 'Rowan kept the door while Siofra listened.', 2),
            block('d', 'Aurora charted old routes through the storm.', 3),
            block('e', 'Phaeris laughed at the impossible timing.', 4),
            block('f', 'Isolde measured the silence before moving.', 5),
        ]);

        const radii = atlas.nodes.map(node => Math.hypot(node.atlasX || 0, node.atlasY || 0, node.atlasZ || 0));
        for (const radius of radii) {
            expect(radius).toBeGreaterThan(1.03);
            expect(radius).toBeLessThan(1.13);
        }

        const maxAxis = Math.max(...atlas.nodes.flatMap(node => [
            Math.abs(node.atlasX || 0),
            Math.abs(node.atlasY || 0),
            Math.abs(node.atlasZ || 0),
        ]));
        expect(maxAxis).toBeLessThanOrEqual(1.08);
    });

    it('renders graph-rebuild embedding targets while compacting entity mention anchors', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-1',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [{ id: 'chunk-1', noteId: 'note-1', start: 0, end: 40, ordinal: 0, source: 'dynamic-chunking' }],
            mentions: [],
            entityAnchors: [{
                id: 'anchor-1',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                surface: 'Kai',
                sourceStart: 0,
                sourceEnd: 3,
                source: 'accepted_suggestion',
                confidence: 0.9,
                entityId: 'kai',
                status: 'accepted',
                generation: 1,
            }],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:note:note-1', kind: 'note', sourceId: 'note-1', noteId: 'note-1', label: 'Note 1', text: 'chapter text', evidenceIds: [] },
                { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Chunk 1', text: 'Kai entered the room.', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionTier: 0, admissionStatus: 'admitted', parentIds: ['embed:note:note-1'] },
                { id: 'embed:anchor:anchor-1', kind: 'anchor', sourceId: 'anchor-1', noteId: 'note-1', chunkId: 'chunk-1', entityId: 'kai', label: 'Kai', text: 'Kai', evidenceIds: ['anchor-1'] },
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', label: 'Kai', text: 'Kai', evidenceIds: ['anchor-1'], parentIds: ['embed:chunk:chunk-1', 'embed:note:note-1'] },
                { id: 'embed:entity:hazel', kind: 'entity', sourceId: 'hazel', entityId: 'hazel', label: 'Hazel', text: 'Hazel', evidenceIds: [] },
                { id: 'embed:entity:baton', kind: 'entity', sourceId: 'baton', entityId: 'baton', entityKind: 'LOCATION', label: 'Baton Rouge', text: 'Baton Rouge', evidenceIds: ['anchor-location'] },
                { id: 'embed:anchor:anchor-location', kind: 'anchor', sourceId: 'anchor-location', noteId: 'note-1', chunkId: 'chunk-1', entityId: 'baton', entityKind: 'LOCATION', label: 'Baton Rouge', text: 'Baton Rouge', evidenceIds: ['anchor-location'] },
                { id: 'embed:graph-fact:co', kind: 'graphFact', sourceId: 'co', label: 'Kai co_occurs_with Hazel', text: 'Kai co_occurs_with Hazel [review]', evidenceIds: [] },
                { id: 'embed:graph-fact:observe', kind: 'graphFact', sourceId: 'observe', label: 'Kai observes Hazel', text: 'Kai observes Hazel [accepted]', evidenceIds: [] },
                { id: 'embed:graph-fact:comment', kind: 'graphFact', sourceId: 'comment', label: 'Kai comments on Hazel', text: 'Kai comments on Hazel [accepted]', evidenceIds: [] },
                { id: 'embed:graph-fact:authority', kind: 'graphFact', sourceId: 'authority', label: 'authority_chain_event', text: 'Joint Chiefs authority chain event [accepted]', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [{ id: 'edge-1', sourceId: 'kai', targetId: 'hazel', type: 'co_occurs_with', weight: 1, confidence: 0.7, evidenceAnchorIds: ['anchor-1'], scopeKeys: ['chunk-1'], noteIds: ['note-1'] }],
            counters: null as any,
        }, 'hybrid');

        expect(atlas.nodes.map((node) => node.id)).toEqual(expect.arrayContaining([
            'embed:chunk:chunk-1',
            'embed:entity:kai',
        ]));
        expect(atlas.edges.map((edge) => edge.type)).toEqual(expect.arrayContaining([
            'note-chunk',
            'chunk-entity',
            'co_occurs_with',
        ]));
        const nodes = new Map(atlas.nodes.map((node) => [node.id, node]));
        const colors = new Map(atlas.nodes.map((node) => [node.id, node.colorHsl]));
        const styleLabDefaults = new Set(Object.values(DEFAULT_ENTITY_COLORS));
        expect(nodes.has('embed:anchor:anchor-1')).toBe(false);
        expect(nodes.has('embed:anchor:anchor-location')).toBe(false);
        expect(nodes.get('embed:entity:baton')).toMatchObject({
            kind: 'entity',
            metadata: expect.objectContaining({ graphColorKind: 'location' }),
        });
        expect(nodes.get('embed:chunk:chunk-1')?.metadata).toEqual(expect.objectContaining({
            signalLane: 'chunk_spine',
            signalStructuralRole: 'spine',
            signalAdmissionTier: 0,
            signalAdmissionStatus: 'admitted',
            signalParentIds: ['embed:note:note-1'],
            graphTruthStatus: 'accepted',
            graphTruthKind: 'target',
        }));
        expect(nodes.get('embed:entity:kai')?.metadata?.mentionCompaction).toMatchObject({
            mode: 'entity_mention_compaction_v1',
            anchorCount: 1,
            anchorIds: ['anchor-1'],
            chunkIds: ['chunk-1'],
            expanded: false,
        });
        expect(nodes.get('embed:entity:kai')?.metadata?.signalParentIds).toEqual(['embed:chunk:chunk-1', 'embed:note:note-1']);
        expect(nodes.get('embed:entity:baton')?.metadata?.mentionCompaction).toMatchObject({
            anchorCount: 1,
            anchorIds: ['anchor-location'],
        });
        expect(nodes.has('embed:graph-fact:co')).toBe(false);
        expect(colors.get('embed:entity:baton')).toBe(DEFAULT_ENTITY_COLORS.LOCATION);
        expect(colors.get('embed:graph-fact:observe')).toBe(DEFAULT_GRAPH_NODE_COLORS.observation);
        expect(colors.get('embed:graph-fact:comment')).toBe(DEFAULT_GRAPH_NODE_COLORS.communication);
        expect(colors.get('embed:graph-fact:authority')).toBe(DEFAULT_GRAPH_NODE_COLORS.authority);
        expect(styleLabDefaults.has(colors.get('embed:graph-fact:observe') || '')).toBe(false);
        expect(styleLabDefaults.has(colors.get('embed:graph-fact:comment') || '')).toBe(false);
        expect(atlas.sourceLabel).toContain('graph rebuild snapshot');
    });

    it('renders compact Rust Atlas packet manifold targets when target rows are blobbed', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-compact-packet',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
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
            counters: { embeddingTargets: 2 },
            atlasPacket: {
                schemaVersion: 'phoenix-atlas-packet/v1',
                snapshotId: 'snapshot-compact-packet',
                scopeKind: 'global',
                scopeId: 'global',
                builtAt: 1,
                sourceContract: {
                    authority: 'rust-atlas-packet',
                    identityAuthority: 'registry-entities-and-accepted-anchors',
                    vectorContract: 'vectors missing',
                    tsGraphBuilderRole: 'native-atlas-packet-authority',
                },
                objects: [],
                manifoldTargets: [
                    {
                        id: 'embed:entity:kai',
                        objectId: 'object:entity:kai',
                        family: 'entity',
                        admission: 'admitted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'entity',
                        label: 'Kai',
                        sourceId: 'kai',
                        registryEntityId: 'kai',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:chunk:chunk-1',
                        objectId: 'object:chunk:chunk-1',
                        family: 'structure',
                        admission: 'admitted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'chunk',
                        label: 'Chunk 1',
                        sourceId: 'chunk-1',
                        noteId: 'note-1',
                        chunkId: 'chunk-1',
                        evidenceIds: [],
                        parentIds: ['embed:entity:kai'],
                    },
                ],
                counters: {
                    objects: 0,
                    manifoldTargets: 2,
                    registryEntities: 1,
                    evidenceAnchors: 0,
                    modelVectors: 0,
                    families: [],
                },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'hopf');

        expect(graphRebuildEmbeddingTargetCount(snapshot)).toBe(2);
        expect(atlas.nodes.map((node) => node.id)).toEqual(expect.arrayContaining([
            'embed:entity:kai',
            'embed:chunk:chunk-1',
        ]));
        expect(atlas.edges).toEqual(expect.arrayContaining([
            expect.objectContaining({
                sourceId: 'embed:entity:kai',
                targetId: 'embed:chunk:chunk-1',
                type: 'target-parent',
            }),
        ]));
        expect(atlas.manifold?.projectionSource).toBe('rust_atlas_packet_manifold_targets');
    });

    it('filters packet-only embed targets from Rust taxonomy fields instead of fallback text', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-packet-taxonomy',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
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
            counters: { embeddingTargets: 6 },
            atlasPacket: {
                schemaVersion: 'phoenix-atlas-packet/v1',
                snapshotId: 'snapshot-packet-taxonomy',
                scopeKind: 'global',
                scopeId: 'global',
                builtAt: 1,
                sourceContract: {
                    authority: 'rust-atlas-packet',
                    identityAuthority: 'registry-entities-and-accepted-anchors',
                    vectorContract: 'vectors missing',
                    tsGraphBuilderRole: 'native-atlas-packet-authority',
                },
                objects: [],
                manifoldTargets: [
                    {
                        id: 'embed:document-unit:paragraph-1',
                        objectId: 'object:paragraph-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Paragraph',
                        styleKey: 'chunk',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        documentUnitKind: 'paragraph',
                        sourceId: 'paragraph-1',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:document-unit:leaf-1',
                        objectId: 'object:leaf-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Leaf',
                        styleKey: 'chunk',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        documentUnitKind: 'leaf',
                        sourceId: 'leaf-1',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:document-unit:style-sentence-1',
                        objectId: 'object:style-sentence-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Styled sentence',
                        styleKey: 'sentence',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        sourceId: 'style-sentence-1',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:document-unit:style-paragraph-1',
                        objectId: 'object:style-paragraph-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Styled paragraph',
                        styleKey: 'paragraph',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        sourceId: 'style-paragraph-1',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:memory:rank-1',
                        objectId: 'object:memory-1',
                        family: 'memory',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'memoryState',
                        label: 'memory',
                        styleKey: 'rankStatus',
                        lane: 'memory_state',
                        structuralRole: 'child',
                        stateContextKind: 'rankStatus',
                        sourceId: 'rank-1',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:graph-fact:weak-co',
                        objectId: 'object:weak-co',
                        family: 'fact',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'graphFact',
                        label: 'weak relation',
                        styleKey: 'cooccurrence',
                        lane: 'cooccurrence_weak',
                        structuralRole: 'fact',
                        sourceId: 'weak-co',
                        evidenceIds: [],
                    },
                ],
                counters: {
                    objects: 0,
                    manifoldTargets: 6,
                    registryEntities: 0,
                    evidenceAnchors: 0,
                    modelVectors: 0,
                    families: [],
                },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'product');
        const ids = new Set(atlas.nodes.map((node) => node.id));
        const memory = atlas.nodes.find((node) => node.id === 'embed:memory:rank-1');

        expect(ids.has('embed:document-unit:paragraph-1')).toBe(false);
        expect(ids.has('embed:document-unit:style-sentence-1')).toBe(false);
        expect(ids.has('embed:document-unit:style-paragraph-1')).toBe(false);
        expect(ids.has('embed:document-unit:leaf-1')).toBe(true);
        expect(ids.has('embed:graph-fact:weak-co')).toBe(false);
        expect(memory?.metadata?.['graphMemoryStateKind']).toBe('rankStatus');
    });

    it('parents packet structure units through chunks and keeps sentence/paragraph out of Embed', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-packet-structure-parentage',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
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
            counters: { embeddingTargets: 5 },
            atlasPacket: {
                schemaVersion: 'phoenix-atlas-packet/v1',
                snapshotId: 'snapshot-packet-structure-parentage',
                scopeKind: 'global',
                scopeId: 'global',
                builtAt: 1,
                sourceContract: {
                    authority: 'rust-atlas-packet',
                    identityAuthority: 'registry-entities-and-accepted-anchors',
                    vectorContract: 'vectors missing',
                    tsGraphBuilderRole: 'native-atlas-packet-authority',
                },
                objects: [],
                manifoldTargets: [
                    {
                        id: 'embed:structure-root:note-1:document-structure',
                        objectId: 'atlas:root:note-1:document-structure',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'structureRoot',
                        label: 'Document structure',
                        styleKey: 'document',
                        lane: 'document_spine',
                        structuralRole: 'root',
                        sourceId: 'note-1:document-structure',
                        noteId: 'note-1',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:chunk:chunk-1',
                        objectId: 'atlas:chunk:chunk-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'chunk',
                        label: 'Chunk 1',
                        styleKey: 'chunk',
                        lane: 'chunk_spine',
                        structuralRole: 'spine',
                        sourceId: 'chunk-1',
                        noteId: 'note-1',
                        chunkId: 'chunk-1',
                        evidenceIds: [],
                        parentIds: ['embed:structure-root:note-1:document-structure'],
                    },
                    {
                        id: 'embed:document-unit:paragraph-1',
                        objectId: 'atlas:document-unit:paragraph-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Paragraph 1',
                        styleKey: 'chunk',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        sourceId: 'paragraph-1',
                        noteId: 'note-1',
                        chunkId: 'chunk-1',
                        evidenceIds: [],
                        parentIds: ['embed:structure-root:note-1:document-structure'],
                    },
                    {
                        id: 'embed:document-unit:sentence-1',
                        objectId: 'atlas:document-unit:sentence-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Sentence 1',
                        styleKey: 'chunk',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        sourceId: 'sentence-1',
                        noteId: 'note-1',
                        chunkId: 'chunk-1',
                        evidenceIds: [],
                        parentIds: ['embed:document-unit:paragraph-1'],
                    },
                    {
                        id: 'embed:document-unit:leaf-1',
                        objectId: 'atlas:document-unit:leaf-1',
                        family: 'structure',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'documentUnit',
                        label: 'Leaf',
                        styleKey: 'chunk',
                        lane: 'chunk_spine',
                        structuralRole: 'child',
                        documentUnitKind: 'leaf',
                        sourceId: 'leaf-1',
                        noteId: 'note-1',
                        chunkId: 'chunk-1',
                        evidenceIds: [],
                        parentIds: ['embed:document-unit:paragraph-1', 'embed:structure-root:note-1:document-structure'],
                    },
                ],
                counters: {
                    objects: 0,
                    manifoldTargets: 5,
                    registryEntities: 0,
                    evidenceAnchors: 0,
                    modelVectors: 0,
                    families: [],
                },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'siegel');
        const ids = new Set(atlas.nodes.map((node) => node.id));
        const leaf = atlas.nodes.find((node) => node.id === 'embed:document-unit:leaf-1');

        expect(ids.has('embed:document-unit:paragraph-1')).toBe(false);
        expect(ids.has('embed:document-unit:sentence-1')).toBe(false);
        expect(ids.has('embed:document-unit:leaf-1')).toBe(true);
        expect(leaf?.metadata?.signalParentIds).toEqual([
            'embed:chunk:chunk-1',
            'embed:structure-root:note-1:document-structure',
        ]);
        expect(atlas.edges).toEqual(expect.arrayContaining([
            expect.objectContaining({
                sourceId: 'embed:chunk:chunk-1',
                targetId: 'embed:document-unit:leaf-1',
                type: 'target-parent',
            }),
        ]));
        expect(atlas.edges.some((edge) =>
            edge.sourceId === 'embed:document-unit:paragraph-1'
            && edge.targetId === 'embed:document-unit:leaf-1',
        )).toBe(false);
    });

    it('preserves canonical graph families through every Embed manifold', () => {
        const targets = [
            packetTarget('embed:note:note-1', 'structure', 'note', 'document', 'note-1'),
            packetTarget('embed:structure-root:note-1:identity', 'structure', 'structureRoot', 'document', 'note-1:identity', {
                noteId: 'note-1', lane: 'document_spine', parentIds: ['embed:note:note-1'],
            }),
            packetTarget('embed:chunk:chunk-1', 'structure', 'chunk', 'chunk', 'chunk-1', {
                noteId: 'note-1', chunkId: 'chunk-1', lane: 'chunk_spine', parentIds: ['embed:structure-root:note-1:identity'],
            }),
            packetTarget('embed:event:event-1', 'fact', 'event', 'eventNode', 'event-1', {
                noteId: 'note-1', chunkId: 'chunk-1', lane: 'event_identity', parentIds: ['embed:chunk:chunk-1'],
            }),
            packetTarget('embed:entity:kai', 'registry', 'entity', 'character', 'kai', {
                registryEntityId: 'kai', entityKind: 'CHARACTER', lane: 'entity_anchor', parentIds: ['embed:chunk:chunk-1'],
            }),
            packetTarget('embed:memory:rank-kai', 'memory', 'memoryState', 'rankStatus', 'rank-kai', {
                registryEntityId: 'kai', stateContextKind: 'rankStatus', lane: 'memory_state', parentIds: ['embed:entity:kai'],
            }),
        ];
        const snapshot = packetSnapshot('snapshot-cross-manifold-families', targets);
        const layouts = {
            hybrid: 'hybridSpace', hopf: 'hopfProjection', lorentz: 'lorentzTree',
            product: 'productManifold', siegel: 'siegelFinsler',
        } as const;
        const expectedKinds = new Map([
            ['embed:note:note-1', 'note'],
            ['embed:structure-root:note-1:identity', 'structure-root'],
            ['embed:chunk:chunk-1', 'chunk'],
            ['embed:event:event-1', 'event'],
            ['embed:entity:kai', 'entity'],
            ['embed:memory:rank-kai', 'memory-state'],
        ]);

        for (const mode of ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'] as const) {
            const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, mode);
            const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({
                layoutMode: layouts[mode], sourceMode: 'embeddings',
            }));
            expect(new Map(atlas.nodes.map((node) => [node.id, node.kind]))).toEqual(expectedKinds);
            expect(new Map(scene.nodes.map((node) => [node.entity.id, node.entity.kind]))).toEqual(expectedKinds);
            expect(atlas.nodes.find((node) => node.id.includes('structure-root'))?.metadata?.['graphColorKind']).toBe('document');
            expect(atlas.nodes.find((node) => node.id.startsWith('embed:event:'))?.metadata?.['graphColorKind']).toBe('event-node');
            expect(atlas.nodes.find((node) => node.id === 'embed:entity:kai')?.metadata?.['graphColorKind']).toBe('character');
            expect(atlas.nodes.find((node) => node.id.startsWith('embed:memory:'))?.metadata?.['graphColorKind']).toBe('rank-status');
            for (const node of atlas.nodes) {
                const trace = node.metadata?.['visualTrace'] as Record<string, unknown> | undefined;
                expect(node.metadata).toMatchObject({
                    sourceContract: 'rust-atlas-packet',
                    packetSnapshotId: 'snapshot-cross-manifold-families',
                    visualTrace: expect.objectContaining({
                        source: 'rust_atlas_packet',
                        family: node.metadata?.['atlasFamily'],
                        packetSnapshotId: 'snapshot-cross-manifold-families',
                        sourceContract: 'rust-atlas-packet',
                    }),
                });
                expect(String(trace?.['sourceId'] || '')).not.toBe('');
                expect(String(trace?.['packetTargetId'] || '')).not.toBe('');
            }
            expect(atlas.edges.length).toBeGreaterThan(0);
            for (const edge of atlas.edges) {
                expect(edge.metadata).toMatchObject({
                    sourceContract: 'rust-atlas-packet',
                    packetSnapshotId: 'snapshot-cross-manifold-families',
                    sourceVisualTrace: expect.objectContaining({
                        source: 'rust_atlas_packet',
                        packetSnapshotId: 'snapshot-cross-manifold-families',
                    }),
                    targetVisualTrace: expect.objectContaining({
                        source: 'rust_atlas_packet',
                        packetSnapshotId: 'snapshot-cross-manifold-families',
                    }),
                    visualTrace: expect.objectContaining({
                        source: 'rust_atlas_packet',
                        packetSnapshotId: 'snapshot-cross-manifold-families',
                    }),
                });
            }
            expect(scene.nodes.every((node) => Boolean(node.entity.metadata?.['visualTrace']))).toBe(true);
            expect(scene.links.every((edge) => Boolean(edge.metadata?.['visualTrace']))).toBe(true);
        }
    });

    it('resolves shared packet source ids by family instead of object order', () => {
        const objects = [
            packetObject('hypergraph:kai-role', 'hypergraph', 'agentRole', 'relationship', ['kai'], { registryEntityId: 'kai' }),
            packetObject('causal:event-1', 'causal', 'causalFact', 'causalFact', ['event-1']),
            packetObject('registry:kai', 'registry', 'character', 'character', ['kai'], { registryEntityId: 'kai' }),
            packetObject('event:event-1', 'fact', 'event', 'eventNode', ['event-1']),
            packetObject('memory:rank-kai', 'memory', 'memoryState', 'rankStatus', ['rank-kai'], {
                registryEntityId: 'kai', stateContextKind: 'rankStatus',
            }),
        ];
        const targets = [
            packetTarget('embed:entity:kai', 'registry', 'entity', '', 'kai', {
                objectId: 'hypergraph:kai-role', registryEntityId: 'kai',
            }),
            packetTarget('embed:event:event-1', 'fact', 'event', '', 'event-1', {
                objectId: 'causal:event-1',
            }),
            packetTarget('embed:memory:rank-kai', 'memory', 'memoryState', '', 'rank-kai', {
                objectId: 'registry:kai', registryEntityId: 'kai',
            }),
        ];
        const atlas = buildGraphRebuildEmbeddingAtlas(packetSnapshot('snapshot-family-collisions', targets, objects), 'hybrid');
        const byId = new Map(atlas.nodes.map((node) => [node.id, node]));

        expect(byId.get('embed:entity:kai')).toMatchObject({
            kind: 'entity',
            metadata: expect.objectContaining({ entityKind: 'character', graphColorKind: 'character' }),
        });
        expect(byId.get('embed:event:event-1')).toMatchObject({
            kind: 'event',
            metadata: expect.objectContaining({ graphColorKind: 'event-node' }),
        });
        expect(byId.get('embed:memory:rank-kai')).toMatchObject({
            kind: 'memory-state',
            metadata: expect.objectContaining({ graphColorKind: 'rank-status' }),
        });
    });

    it('renders accepted Rust packet objects in embed when no manifold target row exists yet', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-object-only-packet',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
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
            counters: { embeddingTargets: 2 },
            atlasPacket: {
                schemaVersion: 'phoenix-atlas-packet/v1',
                snapshotId: 'snapshot-object-only-packet',
                scopeKind: 'global',
                scopeId: 'global',
                builtAt: 1,
                sourceContract: {
                    authority: 'rust-atlas-packet',
                    identityAuthority: 'registry-entities-and-accepted-anchors',
                    vectorContract: 'vectors missing',
                    tsGraphBuilderRole: 'native-atlas-packet-authority',
                },
                objects: [
                    {
                        id: 'object:entity:kai',
                        family: 'registry',
                        status: 'accepted',
                        kind: 'character',
                        label: 'Kai',
                        styleKey: 'character',
                        lane: 'entity_anchor',
                        structuralRole: 'child',
                        registryEntityId: 'kai',
                        noteIds: ['note-1'],
                        chunkIds: [],
                        anchorIds: [],
                        evidenceIds: [],
                        sourceIds: ['kai'],
                        targetIds: [],
                    },
                    {
                        id: 'object:memory:rank-1',
                        family: 'memory',
                        status: 'accepted',
                        kind: 'memoryState',
                        label: 'rank',
                        styleKey: 'rankStatus',
                        lane: 'memory_state',
                        structuralRole: 'child',
                        stateContextKind: 'rankStatus',
                        registryEntityId: 'kai',
                        noteIds: ['note-1'],
                        chunkIds: [],
                        anchorIds: [],
                        evidenceIds: ['ev-1'],
                        sourceIds: ['rank-1'],
                        targetIds: ['object:entity:kai'],
                    },
                ],
                manifoldTargets: [],
                counters: {
                    objects: 2,
                    manifoldTargets: 0,
                    registryEntities: 1,
                    evidenceAnchors: 1,
                    modelVectors: 0,
                    families: [],
                },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'siegel');
        const ids = new Set(atlas.nodes.map((node) => node.id));
        const memory = atlas.nodes.find((node) => node.id === 'embed:memory:rank-1');

        expect(graphRebuildEmbeddingTargetCount(snapshot)).toBe(2);
        expect(ids.has('embed:entity:kai')).toBe(true);
        expect(ids.has('embed:memory:rank-1')).toBe(true);
        expect(memory?.kind).toBe('memory-state');
        expect(memory?.metadata?.['graphColorKind']).toBe('rank-status');
        expect(memory?.metadata?.['graphMemoryStateKind']).toBe('rankStatus');
        expect(atlas.edges).toEqual(expect.arrayContaining([
            expect.objectContaining({
                sourceId: 'embed:entity:kai',
                targetId: 'embed:memory:rank-1',
                type: 'target-parent',
            }),
        ]));
    });

    it('keeps registry taxonomy when a manifold target already represents the object', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-represented-registry-packet',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
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
            counters: { embeddingTargets: 2 },
            atlasPacket: {
                schemaVersion: 'phoenix-atlas-packet/v1',
                snapshotId: 'snapshot-represented-registry-packet',
                scopeKind: 'global',
                scopeId: 'global',
                builtAt: 1,
                sourceContract: {
                    authority: 'rust-atlas-packet',
                    identityAuthority: 'registry-entities-and-accepted-anchors',
                    vectorContract: 'vectors missing',
                    tsGraphBuilderRole: 'native-atlas-packet-authority',
                },
                objects: [
                    {
                        id: 'object:entity:amara',
                        family: 'registry',
                        status: 'accepted',
                        kind: 'character',
                        label: 'Amara',
                        styleKey: 'character',
                        lane: 'entity_anchor',
                        structuralRole: 'child',
                        registryEntityId: 'amara',
                        noteIds: ['note-1'],
                        chunkIds: [],
                        anchorIds: [],
                        evidenceIds: [],
                        sourceIds: ['amara'],
                        targetIds: [],
                    },
                    {
                        id: 'object:entity:arcadia',
                        family: 'registry',
                        status: 'accepted',
                        kind: 'location',
                        label: 'Arcadia',
                        styleKey: 'location',
                        lane: 'entity_anchor',
                        structuralRole: 'child',
                        registryEntityId: 'arcadia',
                        noteIds: ['note-1'],
                        chunkIds: [],
                        anchorIds: [],
                        evidenceIds: [],
                        sourceIds: ['arcadia'],
                        targetIds: [],
                    },
                ],
                manifoldTargets: [
                    {
                        id: 'embed:entity:amara',
                        objectId: 'object:entity:amara',
                        family: 'entity',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'entity',
                        label: 'Amara',
                        sourceId: 'amara',
                        registryEntityId: 'amara',
                        evidenceIds: [],
                    },
                    {
                        id: 'embed:entity:arcadia',
                        objectId: 'object:entity:arcadia',
                        family: 'entity',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'entity',
                        label: 'Arcadia',
                        sourceId: 'arcadia',
                        registryEntityId: 'arcadia',
                        evidenceIds: [],
                    },
                ],
                counters: {
                    objects: 2,
                    manifoldTargets: 2,
                    registryEntities: 2,
                    evidenceAnchors: 0,
                    modelVectors: 0,
                    families: [],
                },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'siegel');
        const amara = atlas.nodes.find((node) => node.id === 'embed:entity:amara');
        const arcadia = atlas.nodes.find((node) => node.id === 'embed:entity:arcadia');

        expect(graphRebuildEmbeddingTargetCount(snapshot)).toBe(2);
        expect(amara?.kind).toBe('entity');
        expect(amara?.metadata?.['entityKind']).toBe('character');
        expect(amara?.metadata?.['graphColorKind']).toBe('character');
        expect(arcadia?.kind).toBe('entity');
        expect(arcadia?.metadata?.['entityKind']).toBe('location');
        expect(arcadia?.metadata?.['graphColorKind']).toBe('location');
        expect(atlas.nodes.filter((node) => node.id.startsWith('embed:entity:'))).toHaveLength(2);
    });

    it('repairs packet target object refs so anchors and memory do not duplicate entities', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-entity-duplicate-refs',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [{
                id: 'anchor-kai',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                surface: 'Kai',
                sourceStart: 0,
                sourceEnd: 3,
                source: 'accepted_suggestion',
                confidence: 0.92,
                entityId: 'kai',
                status: 'accepted',
                generation: 1,
            }],
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
            counters: { embeddingTargets: 3 },
            atlasPacket: {
                schemaVersion: 'phoenix-atlas-packet/v1',
                snapshotId: 'snapshot-entity-duplicate-refs',
                scopeKind: 'global',
                scopeId: 'global',
                builtAt: 1,
                sourceContract: {
                    authority: 'rust-atlas-packet',
                    identityAuthority: 'registry-entities-and-accepted-anchors',
                    vectorContract: 'vectors missing',
                    tsGraphBuilderRole: 'native-atlas-packet-authority',
                },
                objects: [
                    {
                        id: 'kai',
                        family: 'registry',
                        status: 'accepted',
                        kind: 'character',
                        label: 'Kai',
                        styleKey: 'character',
                        lane: 'entity_anchor',
                        structuralRole: 'child',
                        registryEntityId: 'kai',
                        noteIds: ['note-1'],
                        chunkIds: [],
                        anchorIds: ['anchor-kai'],
                        evidenceIds: ['anchor-kai'],
                        sourceIds: ['kai'],
                        targetIds: [],
                    },
                    {
                        id: 'atlas:anchor:anchor-kai',
                        family: 'evidence',
                        status: 'accepted',
                        kind: 'entityAnchor',
                        label: 'Kai',
                        styleKey: 'anchor',
                        lane: 'anchor_evidence',
                        structuralRole: 'evidence',
                        registryEntityId: 'kai',
                        noteIds: ['note-1'],
                        chunkIds: ['chunk-1'],
                        anchorIds: ['anchor-kai'],
                        evidenceIds: ['anchor-kai'],
                        sourceIds: ['anchor-kai', 'kai'],
                        targetIds: ['kai'],
                    },
                    {
                        id: 'atlas:memory:rank-kai',
                        family: 'memory',
                        status: 'accepted',
                        kind: 'memoryState',
                        label: 'rank',
                        styleKey: 'rankStatus',
                        lane: 'memory_state',
                        structuralRole: 'child',
                        stateContextKind: 'rankStatus',
                        registryEntityId: 'kai',
                        noteIds: ['note-1'],
                        chunkIds: [],
                        anchorIds: [],
                        evidenceIds: [],
                        sourceIds: ['rank-kai'],
                        targetIds: ['kai'],
                    },
                ],
                manifoldTargets: [
                    {
                        id: 'embed:entity:kai',
                        objectId: 'kai',
                        family: 'registry',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'entity',
                        label: 'Kai',
                        sourceId: 'kai',
                        registryEntityId: 'kai',
                        evidenceIds: ['anchor-kai'],
                    },
                    {
                        id: 'embed:anchor:anchor-kai',
                        objectId: 'kai',
                        family: 'evidence',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'anchor',
                        label: 'Kai',
                        sourceId: 'anchor-kai',
                        registryEntityId: 'kai',
                        evidenceIds: ['anchor-kai'],
                    },
                    {
                        id: 'embed:memory:rank-kai',
                        objectId: 'kai',
                        family: 'memory',
                        admission: 'admitted',
                        status: 'accepted',
                        vectorStatus: 'missing',
                        coordinateSource: 'deterministic-signature',
                        kind: 'memoryState',
                        label: 'rank',
                        sourceId: 'rank-kai',
                        registryEntityId: 'kai',
                        evidenceIds: [],
                    },
                ],
                counters: {
                    objects: 3,
                    manifoldTargets: 3,
                    registryEntities: 1,
                    evidenceAnchors: 1,
                    modelVectors: 0,
                    families: [],
                },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'siegel');
        const ids = new Set(atlas.nodes.map((node) => node.id));
        const memory = atlas.nodes.find((node) => node.id === 'embed:memory:rank-kai');

        expect(ids.has('embed:entity:kai')).toBe(true);
        expect(ids.has('embed:anchor:anchor-kai')).toBe(false);
        expect(ids.has('embed:memory:rank-kai')).toBe(true);
        expect(atlas.nodes.filter((node) => node.id.startsWith('embed:entity:'))).toHaveLength(1);
        expect(memory?.kind).toBe('memory-state');
        expect(memory?.metadata?.['graphColorKind']).toBe('rank-status');
        expect(memory?.metadata?.['graphMemoryStateKind']).toBe('rankStatus');
        expect(atlas.nodes.find((node) => node.id === 'embed:entity:kai')?.metadata?.mentionCompaction).toMatchObject({
            anchorCount: 1,
            anchorIds: ['anchor-kai'],
        });
    });

    it('curates embed manifolds to full graph targets without sentence and paragraph scaffolding', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-curated-embed-targets',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:note:note-1', kind: 'note', sourceId: 'note-1', noteId: 'note-1', label: 'Document 1', text: 'Document spine', evidenceIds: [] },
                { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Chunk 1', text: 'Chunk spine', evidenceIds: [], parentIds: ['embed:note:note-1'] },
                { id: 'embed:document-unit:paragraph-1', kind: 'documentUnit', sourceId: 'paragraph-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Paragraph 1', text: 'document_sidecar:paragraph\nkind:paragraph', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:sentence-1', kind: 'documentUnit', sourceId: 'sentence-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Sentence 1', text: 'document_sidecar:sentence\nkind:sentence', evidenceIds: [], parentIds: ['embed:document-unit:paragraph-1'] },
                { id: 'embed:document-unit:style-paragraph-1', kind: 'documentUnit', sourceId: 'style-paragraph-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Styled paragraph', text: 'structured unit', styleKey: 'paragraph', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:style-sentence-1', kind: 'documentUnit', sourceId: 'style-sentence-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Styled sentence', text: 'structured unit', styleKey: 'sentence', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:leaf-1', kind: 'documentUnit', sourceId: 'leaf-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Leaf', text: 'document_sidecar:retrieval_unit\nkind:leaf', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:claim-1', kind: 'documentUnit', sourceId: 'claim-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Claim', text: 'document_sidecar:rhetorical_unit\nkind:claim', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:action-1', kind: 'documentUnit', sourceId: 'action-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Action block', text: 'document_sidecar:rhetorical_unit\nkind:action_block', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:contrast-1', kind: 'documentUnit', sourceId: 'contrast-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Contrast', text: 'document_sidecar:rhetorical_unit\nkind:contrast', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:looked-1', kind: 'documentUnit', sourceId: 'looked-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Looked', text: 'relation_type:looked\nkind:action', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:glanced-1', kind: 'documentUnit', sourceId: 'glanced-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Glanced', text: 'relation_type:glanced\nkind:action', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-unit:decision-1', kind: 'documentUnit', sourceId: 'decision-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Decision', text: 'semantic_situation:decision\nkind:decision', evidenceIds: [], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:document-evidence:evidence-1', kind: 'evidenceSpan', sourceId: 'evidence-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Evidence', text: 'document_evidence_span:evidence-1', evidenceIds: ['evidence-1'], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:graph-fact:observe-1', kind: 'graphFact', sourceId: 'observe-1', label: 'Kai observes Hazel', text: 'Kai observes Hazel [accepted]', evidenceIds: ['evidence-1'], parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:graph-fact:weak-co', kind: 'graphFact', sourceId: 'weak-co', label: 'Kai co_occurs_with Hazel', text: 'Kai co_occurs_with Hazel', evidenceIds: [], lane: 'cooccurrence_weak' },
                { id: 'embed:raw-mention:kai', kind: 'rawMention', sourceId: 'raw-mention:kai', label: 'Kai mention', text: 'raw mention scaffold', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'product');
        const ids = atlas.nodes.map((node) => node.id);
        const idSet = new Set(ids);

        expect(ids).toEqual(expect.arrayContaining([
            'embed:note:note-1',
            'embed:chunk:chunk-1',
            'embed:document-unit:leaf-1',
            'embed:document-unit:claim-1',
            'embed:document-unit:action-1',
            'embed:document-unit:contrast-1',
            'embed:document-unit:looked-1',
            'embed:document-unit:glanced-1',
            'embed:document-unit:decision-1',
            'embed:document-evidence:evidence-1',
            'embed:graph-fact:observe-1',
        ]));
        expect(idSet.has('embed:document-unit:paragraph-1')).toBe(false);
        expect(idSet.has('embed:document-unit:sentence-1')).toBe(false);
        expect(idSet.has('embed:document-unit:style-paragraph-1')).toBe(false);
        expect(idSet.has('embed:document-unit:style-sentence-1')).toBe(false);
        expect(idSet.has('embed:graph-fact:weak-co')).toBe(false);
        expect(idSet.has('embed:raw-mention:kai')).toBe(false);
    });

    it('audits sentence and paragraph style keys as explicit Embed exclusions', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-style-key-exclusions',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:document-unit:style-paragraph-1', kind: 'documentUnit', sourceId: 'style-paragraph-1', noteId: 'note-1', label: 'Styled paragraph', text: 'structured unit', styleKey: 'paragraph', evidenceIds: [] },
                { id: 'embed:document-unit:style-sentence-1', kind: 'documentUnit', sourceId: 'style-sentence-1', noteId: 'note-1', label: 'Styled sentence', text: 'structured unit', styleKey: 'sentence', evidenceIds: [] },
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'Kai', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
        } as any;

        const audit = buildGraphAtlasTaxonomyAudit(snapshot);
        const exclusions = new Map(audit.embedExclusions.map((row) => [`${row.styleKey}:${row.reason}`, row.count]));

        expect(exclusions.get('paragraph:sentence_or_paragraph')).toBe(1);
        expect(exclusions.get('sentence:sentence_or_paragraph')).toBe(1);
    });

    it('uses graph model v2 projection edges for graph-rebuild relationship rendering', () => {
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-v2-atlas',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [{
                id: 'approval-1',
                sourceEntityId: 'kai',
                targetEntityId: 'hazel',
                relationType: 'approves',
                status: 'accepted',
                confidence: 0.82,
                evidenceAnchorIds: [],
                adjudicationSource: 'test',
                adjudicationScore: 0.82,
                rationale: 'accepted approval',
                decisionEvidence: [],
            }],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'Kai', evidenceIds: [] },
                { id: 'embed:entity:hazel', kind: 'entity', sourceId: 'hazel', entityId: 'hazel', entityKind: 'CHARACTER', label: 'Hazel', text: 'Hazel', evidenceIds: [] },
                { id: 'embed:graph-fact:approval-1', kind: 'graphFact', sourceId: 'approval-1', label: 'Kai approves Hazel', text: 'Kai approves Hazel [accepted]', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [
                { entityId: 'kai', label: 'Kai', kind: 'CHARACTER', anchorIds: [] },
                { entityId: 'hazel', label: 'Hazel', kind: 'CHARACTER', anchorIds: [] },
            ],
            edges: [],
            counters: null as any,
        } as any;
        snapshot.graphModelV2 = buildGraphModelV2Snapshot(snapshot);
        snapshot.graphModelV2.bundles.push({
            id: 'bundle:approval-1',
            family: 'approval',
            relationType: 'approves',
            lane: 'cooccurrence_weak',
            status: 'prepared',
            confidence: 0.72,
            evidenceIds: [],
            sourceRecordId: 'approval-1',
            commitment: {
                family: 'RelationFamily',
                topPrototypeId: 'relation:approval',
                topLabel: 'approval',
                topScore: -1.1,
                topProbability: 0.84,
                secondPrototypeId: 'relation:transfer',
                secondScore: -0.3,
                secondProbability: 0.16,
                margin: 0.8,
                entropy: 0.22,
                ambiguityScore: 0.22,
                classificationConfidence: 0.8,
                promotionReady: true,
                radialStrength: 0.78,
                topKScores: [
                    { prototypeId: 'relation:approval', family: 'RelationFamily', score: -1.1, probability: 0.84 },
                ],
            },
        });

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'hybrid');
        const byId = new Map(atlas.nodes.map((node) => [node.id, node]));

        expect(atlas.edges).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'embed:v2:projection:fact-role:approval-1:source',
                sourceId: 'embed:graph-fact:approval-1',
                targetId: 'embed:entity:kai',
                type: 'source',
            }),
            expect.objectContaining({
                id: 'embed:v2:projection:fact-role:approval-1:target',
                sourceId: 'embed:graph-fact:approval-1',
                targetId: 'embed:entity:hazel',
                type: 'target',
            }),
        ]));
        expect(atlas.edges.some((edge) => edge.id === 'embed:fact-source:approval-1')).toBe(false);
        expect(byId.get('embed:graph-fact:approval-1')?.metadata).toMatchObject({
            commitmentTopPrototypeId: 'relation:approval',
            promotionReady: true,
            hybridInterior: {
                mode: 'busemannCommitment',
                signature: expect.objectContaining({
                    topPrototypeId: 'relation:approval',
                    promotionReady: true,
                }),
            },
        });
    });

    it('projects compiled semantic situations as typed n-ary role incidences', () => {
        const factId = 'fact:document-hyperedge:transfer-1';
        const situationId = `embed:${factId}`;
        const snapshot = {
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-hypergraph-atlas',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'Kai', evidenceIds: [] },
                { id: 'embed:entity:hazel', kind: 'entity', sourceId: 'hazel', entityId: 'hazel', entityKind: 'CHARACTER', label: 'Hazel', text: 'Hazel', evidenceIds: [] },
                { id: 'embed:atom:documentMention:key', kind: 'concept', sourceId: 'key', noteId: 'note-1', label: 'the key', text: 'hypergraph_role:theme', evidenceIds: ['evidence-1'] },
                {
                    id: situationId,
                    kind: 'graphFact',
                    sourceId: factId,
                    noteId: 'note-1',
                    label: 'transfer_possession',
                    text: 'semantic_situation:transfer-1 confidence:0.92',
                    evidenceIds: ['evidence-1'],
                    parentIds: ['embed:entity:kai', 'embed:entity:hazel', 'embed:atom:documentMention:key'],
                },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [
                { entityId: 'kai', label: 'Kai', kind: 'CHARACTER', anchorIds: [] },
                { entityId: 'hazel', label: 'Hazel', kind: 'CHARACTER', anchorIds: [] },
            ],
            edges: [],
            counters: null,
            graphModelV2: {
                schemaVersion: 'phoenix-graph-model/v2',
                sourceSnapshotId: 'snapshot-hypergraph-atlas',
                builtAt: 1,
                atoms: [],
                laneRoots: [],
                bundles: [],
                facts: [{
                    id: factId,
                    family: 'transfer',
                    relationType: 'transfer_possession',
                    lane: 'relationship_fact',
                    status: 'accepted',
                    confidence: 0.92,
                    evidenceIds: ['atom:documentEvidence:evidence-1'],
                    sourceRecordId: 'semantic-situation:transfer-1',
                    semanticSituationId: 'semantic-situation:transfer-1',
                    semanticFrame: 'transfer_possession',
                }],
                roles: [],
                styleTags: [],
                projectionEdges: [
                    { id: 'projection:transfer:actor', sourceId: `atom:relationFact:${factId}`, targetId: 'atom:entity:kai', edgeType: 'role:actor', projectionKind: 'factRole', sourceFactId: factId, confidence: 0.94 },
                    { id: 'projection:transfer:recipient', sourceId: `atom:relationFact:${factId}`, targetId: 'atom:entity:hazel', edgeType: 'role:recipient', projectionKind: 'factRole', sourceFactId: factId, confidence: 0.91 },
                    { id: 'projection:transfer:theme', sourceId: `atom:relationFact:${factId}`, targetId: 'atom:documentMention:key', edgeType: 'role:theme', projectionKind: 'factRole', sourceFactId: factId, confidence: 0.78 },
                ],
                counters: { atoms: 0, laneRoots: 0, bundles: 0, facts: 1, roles: 3, styleTags: 0, projectionEdges: 3, stagedCooccurrenceBundles: 0, weakCooccurrenceFacts: 0, hyperedgeFacts: 1 },
            },
        } as any;

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'hybrid');

        expect(atlas.nodes.map((node) => node.id)).toEqual(expect.arrayContaining([
            situationId,
            'embed:entity:kai',
            'embed:entity:hazel',
            'embed:atom:documentMention:key',
        ]));
        expect(atlas.edges).toEqual(expect.arrayContaining([
            expect.objectContaining({ sourceId: situationId, targetId: 'embed:entity:kai', type: 'actor' }),
            expect.objectContaining({ sourceId: situationId, targetId: 'embed:entity:hazel', type: 'recipient' }),
            expect.objectContaining({ sourceId: situationId, targetId: 'embed:atom:documentMention:key', type: 'theme' }),
        ]));
        expect(atlas.edges.some((edge) => edge.type === 'target-parent' && edge.targetId === situationId)).toBe(false);
    });

    it('carries embedding topology into Product manifold metadata without linking identities', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-product',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', label: 'Kai', text: 'Kai maps Red Mesa', evidenceIds: [] },
                { id: 'embed:entity:rowan', kind: 'entity', sourceId: 'rowan', entityId: 'rowan', label: 'Rowan', text: 'Rowan reads authority lines', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            embeddingProfile: {
                schemaVersion: 'phoenix-embedding-profile/v1',
                modelId: 'mongodb-leaf-mt',
                modelLabel: 'MDBR Leaf MT',
                modelFamily: 'mdbr-leaf-mt',
                dimensionLabel: '384d',
                nativeDimensions: 384,
                selectedDimensions: 384,
                taskProfile: 'multi_task',
                vectorSource: 'signature-preview',
                normalized: true,
                normalization: 'unit_l2',
                topologySupport: 'native',
                supportsMultiVector: true,
                vectorHeads: [
                    { id: 'document', kind: 'document', dimensions: 384, normalized: true, required: true, purpose: 'document and chunk topology vectors' },
                    { id: 'query', kind: 'query', dimensions: 384, normalized: true, required: false, purpose: 'query-side retrieval vectors' },
                    { id: 'topology', kind: 'topology', dimensions: 384, normalized: true, required: false, purpose: 'cluster and product-lane vectors' },
                ],
            },
            embeddingGraphPostProcess: {
                schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
                profile: null as any,
                adapter: {
                    schemaVersion: 'phoenix-embedding-model-adapter/v1',
                    modelId: 'mongodb-leaf-mt',
                    modelLabel: 'MDBR Leaf MT',
                    modelFamily: 'mdbr-leaf-mt',
                    dimensionLabel: '384d',
                    nativeDimensions: 384,
                    selectedDimensions: 384,
                    taskProfile: 'multi_task',
                    vectorSource: 'signature-preview',
                    normalized: true,
                    normalization: 'unit_l2',
                    topologySupport: 'native',
                    supportsTopology: true,
                    supportsMultiTask: true,
                    supportsMultiVector: true,
                    vectorHeads: [
                        { id: 'document', kind: 'document', dimensions: 384, normalized: true, required: true, purpose: 'document and chunk topology vectors' },
                        { id: 'query', kind: 'query', dimensions: 384, normalized: true, required: false, purpose: 'query-side retrieval vectors' },
                        { id: 'topology', kind: 'topology', dimensions: 384, normalized: true, required: false, purpose: 'cluster and product-lane vectors' },
                    ],
                },
                vectorDimensions: 384,
                clusters: [],
                productTopologyRegions: [{
                    id: 'product-region:embedding-cluster:0:entity:core',
                    role: 'core',
                    laneKind: 'entity',
                    clusterId: 'embedding-cluster:0',
                    medoidTargetId: 'embed:entity:kai',
                    memberCount: 2,
                    density: 0.8,
                    confidence: 0.9,
                    bridgeTargetIds: [],
                    backboneTargetIds: ['embed:entity:rowan'],
                }],
                targets: [{
                    targetId: 'embed:entity:kai',
                    clusterId: 'embedding-cluster:0',
                    clusterRole: 'entity_region',
                    medoidTargetId: 'embed:entity:kai',
                    outlierScore: 0.1,
                    hubScore: 0.8,
                    neighborCount: 1,
                    productLaneFeatures: {
                        semanticDepth: 0.9,
                        documentDepth: 0.25,
                        relationDepth: 0.2,
                        clusterRadius: 0.4,
                        fiberPhase: 0.33,
                        confidence: 0.88,
                        dominantLane: 'entity',
                        laneWeights: {
                            semantic: 0.9,
                            document: 0.25,
                            relation: 0.2,
                            temporal: 0.1,
                            causal: 0.1,
                            evidence: 0.16,
                            entity: 0.78,
                        },
                    },
                    productTopologyRegion: {
                        id: 'product-region:embedding-cluster:0:entity:core',
                        role: 'core',
                        laneKind: 'entity',
                        clusterId: 'embedding-cluster:0',
                        medoidTargetId: 'embed:entity:kai',
                        memberCount: 2,
                        density: 0.8,
                        confidence: 0.9,
                        bridgeTargetIds: [],
                        backboneTargetIds: ['embed:entity:rowan'],
                    },
                }],
                backboneEdges: [],
                bridgeEdges: [],
                outlierTargetIds: [],
                metrics: {
                    clusterCount: 1,
                    singletonCount: 0,
                    largestClusterSize: 2,
                    largestClusterRatio: 1,
                    backboneEdgeCount: 0,
                    bridgeEdgeCount: 0,
                    outlierCount: 0,
                    maxHubScore: 0.8,
                    meanNeighborCount: 1,
                },
            },
        }, 'product');

        const kai = atlas.nodes.find((node) => node.id === 'embed:entity:kai')!;
        expect(kai.metadata?.product).toMatchObject({
            role: 'embeddingTarget',
            clusterId: 'embedding-cluster:0',
            medoidTargetId: 'embed:entity:kai',
            dominantLane: 'entity',
            region: expect.objectContaining({
                role: 'core',
                laneKind: 'entity',
            }),
        });
        expect(kai.metadata?.lorentz).toMatchObject({
            level: 6,
            primaryTreeKind: 'identity',
            regionRole: 'core',
            dominantLane: 'entity',
        });
        expect(kai.metadata?.hopf).toMatchObject({
            fiberKind: 'identity',
            phase: 0.33,
        });
    });

    it('feeds Product with ConeProgram pathlets and obstruction trace payloads from graph-rebuild signals', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-product-traversal',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'Kai', evidenceIds: ['a1'], lane: 'entity_anchor' },
                { id: 'embed:entity:rift', kind: 'entity', sourceId: 'rift', entityId: 'rift', entityKind: 'LOCATION', label: 'Rift', text: 'Rift', evidenceIds: [], lane: 'entity_anchor' },
                { id: 'embed:graph-fact:rel-1', kind: 'graphFact', sourceId: 'rel-1', label: 'Kai observes Rift', text: 'Kai observes Rift', evidenceIds: [], lane: 'relationship_fact', admissionStatus: 'deferred', deferReason: 'missing evidence' },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [{
                id: 'rel-1',
                sourceId: 'kai',
                targetId: 'rift',
                type: 'observes',
                weight: 0.2,
                confidence: 0.2,
                evidenceAnchorIds: [],
                scopeKeys: [],
                noteIds: ['note-1'],
            }],
            counters: null as any,
        }, 'product');

        const graphEdge = atlas.edges.find((edge) => edge.id === 'embed:graph-edge:rel-1')!;
        const fact = atlas.nodes.find((node) => node.id === 'embed:graph-fact:rel-1')!;

        expect(atlas.manifold?.conePrograms?.some((program) => program.intent === 'repair')).toBe(true);
        expect(atlas.manifold?.pathlets?.some((pathlet) => pathlet.edgeIds.includes('embed:graph-edge:rel-1'))).toBe(true);
        expect(atlas.manifold?.obstructions?.map((obstruction) => obstruction.kind)).toEqual(expect.arrayContaining(['EvidenceMissing', 'UnsupportedBridge']));
        expect(atlas.manifold?.coneProgramTraces?.some((trace) => trace.obstructionIds.length > 0)).toBe(true);
        expect(graphEdge.metadata?.productTraversal).toMatchObject({ obstructionKind: 'EvidenceMissing' });
        expect(fact.metadata?.productTraversal).toMatchObject({ obstructionKind: 'UnsupportedBridge' });
    });

    it('maps graph-rebuild signal lanes into hierarchy cap shells', () => {
        const targets = [
            { id: 'embed:note:note-1', kind: 'note', sourceId: 'note-1', noteId: 'note-1', label: 'Red Mesa', text: 'chapter text', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionTier: 0 },
            { id: 'embed:structure-root:note-1:document-structure', kind: 'structureRoot', sourceId: 'note-1:document-structure', noteId: 'note-1', label: 'Document structure', text: 'structure_root:document-structure', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionTier: 0, parentIds: ['embed:note:note-1'] },
            { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Chunk 1', text: 'sharp chunk', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionTier: 0, parentIds: ['embed:structure-root:note-1:document-structure'] },
            { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'mentions:4 evidence_context:Kai', evidenceIds: ['a1', 'a2'], lane: 'entity_anchor', structuralRole: 'child', admissionTier: 1, parentIds: ['embed:chunk:chunk-1', 'embed:structure-root:note-1:identity'] },
            { id: 'embed:anchor:a1', kind: 'anchor', sourceId: 'a1', noteId: 'note-1', chunkId: 'chunk-1', entityId: 'kai', label: 'Kai', text: 'source:dynamic evidence_context:Kai', evidenceIds: ['a1'], lane: 'anchor_evidence', structuralRole: 'evidence', admissionTier: 3 },
        ] as const;
        const posts = targets.map((target, index) => overloadedHopfPost(target.id, 'embed:note:note-1', index / targets.length, target.kind));
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-caps',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [{
                id: 'a1',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                surface: 'Kai',
                sourceStart: 0,
                sourceEnd: 3,
                source: 'dynamic-ner',
                confidence: 0.92,
                entityId: 'kai',
                status: 'accepted',
                generation: 1,
            }],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [...targets],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            embeddingGraphPostProcess: {
                schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
                targetCount: targets.length,
                vectorDimensions: 384,
                clusters: [],
                productTopologyRegions: posts.map((post) => post.productTopologyRegion),
                targets: posts,
                backboneEdges: [],
                bridgeEdges: [],
                outlierTargetIds: [],
                metrics: {
                    clusterCount: 1,
                    singletonCount: 0,
                    largestClusterSize: targets.length,
                    largestClusterRatio: 1,
                    backboneEdgeCount: 0,
                    bridgeEdgeCount: 0,
                    outlierCount: 0,
                    maxHubScore: 0.8,
                    meanNeighborCount: 1,
                },
            },
        }, 'lorentz');

        const nodesById = new Map(atlas.nodes.map((node) => [node.id, node]));
        const byId = new Map(atlas.nodes.map((node) => [node.id, node.metadata?.lorentz as Record<string, unknown>]));
        expect(byId.get('embed:note:note-1')).toMatchObject({ capId: 'document:note-1', signalLane: 'document_spine' });
        expect(byId.get('embed:structure-root:note-1:document-structure')).toMatchObject({
            capId: 'document:note-1:root:document',
            parentCapId: 'document:note-1',
            signalLane: 'document_spine',
            parentNodeId: 'embed:note:note-1',
        });
        expect(byId.get('embed:chunk:chunk-1')).toMatchObject({
            capId: 'document:note-1:chunk:chunk-1',
            parentCapId: 'document:note-1:root:document',
            signalLane: 'chunk_spine',
            parentNodeId: 'embed:structure-root:note-1:document-structure',
        });
        expect(byId.get('embed:entity:kai')).toMatchObject({
            capId: 'document:note-1:chunk:chunk-1:evidence:entity:kai',
            parentCapId: 'document:note-1:chunk:chunk-1:evidence',
            signalLane: 'entity_anchor',
        });
        expect(nodesById.has('embed:anchor:a1')).toBe(false);
        expect(nodesById.get('embed:entity:kai')?.metadata?.mentionCompaction).toMatchObject({
            anchorCount: 1,
            anchorIds: ['a1'],
        });
        expect(Number(byId.get('embed:note:note-1')?.['shellRadius'])).toBeGreaterThan(Number(byId.get('embed:chunk:chunk-1')?.['shellRadius']));
        expect(Number(byId.get('embed:structure-root:note-1:document-structure')?.['shellRadius'])).toBeGreaterThan(Number(byId.get('embed:chunk:chunk-1')?.['shellRadius']));
        expect(Number(byId.get('embed:chunk:chunk-1')?.['shellRadius'])).toBeGreaterThan(Number(byId.get('embed:entity:kai')?.['shellRadius']));
    });

    it('keeps folder metadata without collapsing multi-doc hierarchy caps into one folder cap', () => {
        const folderFields = { folderId: 'folder-narrative', folderLabel: 'New Narrative', folderKind: 'NARRATIVE' };
        const targets = [
            { id: 'embed:note:note-1', kind: 'note', sourceId: 'note-1', noteId: 'note-1', ...folderFields, label: 'Untitled Note', text: 'chapter text', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionTier: 0 },
            { id: 'embed:note:note-2', kind: 'note', sourceId: 'note-2', noteId: 'note-2', ...folderFields, label: '6 Chapter', text: 'chapter text', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionTier: 0 },
            { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', ...folderFields, label: 'Chunk 1', text: 'sharp chunk', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionTier: 0, parentIds: ['embed:note:note-1'] },
            { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', ...folderFields, label: 'Kai', text: 'mentions:4', evidenceIds: ['a1'], lane: 'entity_anchor', structuralRole: 'child', admissionTier: 1, parentIds: ['embed:chunk:chunk-1'] },
        ] as const;
        const posts = targets.map((target, index) => overloadedHopfPost(target.id, 'embed:note:note-1', index / targets.length, target.kind));
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-folder-caps',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
            builtAt: 1,
            chunks: [{ id: 'chunk-1', noteId: 'note-1', start: 0, end: 20, ordinal: 0, source: 'dynamic-chunking' }],
            mentions: [],
            entityAnchors: [{
                id: 'a1',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                surface: 'Kai',
                sourceStart: 0,
                sourceEnd: 3,
                source: 'dynamic-ner',
                confidence: 0.92,
                entityId: 'kai',
                status: 'accepted',
                generation: 1,
            }],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [...targets],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            embeddingGraphPostProcess: {
                schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
                targetCount: targets.length,
                vectorDimensions: 384,
                clusters: [],
                productTopologyRegions: posts.map((post) => post.productTopologyRegion),
                targets: posts,
                backboneEdges: [],
                bridgeEdges: [],
                outlierTargetIds: [],
                metrics: {
                    clusterCount: 1,
                    singletonCount: 0,
                    largestClusterSize: targets.length,
                    largestClusterRatio: 1,
                    backboneEdgeCount: 0,
                    bridgeEdgeCount: 0,
                    outlierCount: 0,
                    maxHubScore: 0.8,
                    meanNeighborCount: 1,
                },
            },
        }, 'lorentz');

        for (const node of atlas.nodes) {
            expect(node.metadata?.folderId).toBe('folder-narrative');
        }
        const note = atlas.nodes.find((node) => node.id === 'embed:note:note-1')?.metadata?.lorentz as Record<string, unknown>;
        const noteTwo = atlas.nodes.find((node) => node.id === 'embed:note:note-2')?.metadata?.lorentz as Record<string, unknown>;
        const chunk = atlas.nodes.find((node) => node.id === 'embed:chunk:chunk-1')?.metadata?.lorentz as Record<string, unknown>;
        const entity = atlas.nodes.find((node) => node.id === 'embed:entity:kai')?.metadata?.lorentz as Record<string, unknown>;
        expect(note['capId']).toBe('document:note-1');
        expect(noteTwo['capId']).toBe('document:note-2');
        expect(chunk['capId']).toBe('document:note-1:chunk:chunk-1');
        expect(entity['capId']).toBe('document:note-1:chunk:chunk-1:evidence:entity:kai');
        expect(Number(note['shellRadius'])).toBeGreaterThan(Number(chunk['shellRadius']));
        expect(Number(chunk['shellRadius'])).toBeGreaterThan(Number(entity['shellRadius']));
    });

    it('averages multi-document entity caps between their supporting document spaces', () => {
        const folderFields = { folderId: 'folder-narrative', folderLabel: 'New Narrative', folderKind: 'NARRATIVE' };
        const targets = [
            { id: 'embed:note:note-1', kind: 'note', sourceId: 'note-1', noteId: 'note-1', ...folderFields, label: 'Chapter 1', text: 'first chapter', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionTier: 0 },
            { id: 'embed:note:note-2', kind: 'note', sourceId: 'note-2', noteId: 'note-2', ...folderFields, label: 'Chapter 2', text: 'second chapter', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionTier: 0 },
            { id: 'embed:structure-root:note-1:identity', kind: 'structureRoot', sourceId: 'note-1:identity', noteId: 'note-1', ...folderFields, label: 'Identity root', text: 'structure_root:identity', evidenceIds: [], lane: 'entity_anchor', structuralRole: 'root', admissionTier: 0, parentIds: ['embed:note:note-1'] },
            { id: 'embed:structure-root:note-2:identity', kind: 'structureRoot', sourceId: 'note-2:identity', noteId: 'note-2', ...folderFields, label: 'Identity root', text: 'structure_root:identity', evidenceIds: [], lane: 'entity_anchor', structuralRole: 'root', admissionTier: 0, parentIds: ['embed:note:note-2'] },
            { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', ...folderFields, label: 'Chunk 1', text: 'Amara enters.', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionTier: 0, parentIds: ['embed:structure-root:note-1:document-structure'] },
            { id: 'embed:chunk:chunk-2', kind: 'chunk', sourceId: 'chunk-2', noteId: 'note-2', chunkId: 'chunk-2', ...folderFields, label: 'Chunk 2', text: 'Amara returns.', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionTier: 0, parentIds: ['embed:structure-root:note-2:document-structure'] },
            { id: 'embed:entity:amara', kind: 'entity', sourceId: 'amara', entityId: 'amara', entityKind: 'CHARACTER', ...folderFields, label: 'Amara', text: 'mentions:2 notes:2', evidenceIds: ['a1', 'a2'], lane: 'entity_anchor', structuralRole: 'child', admissionTier: 1, parentIds: ['embed:chunk:chunk-1', 'embed:chunk:chunk-2', 'embed:structure-root:note-1:identity', 'embed:structure-root:note-2:identity'] },
            { id: 'embed:graph-fact:rel-1', kind: 'graphFact', sourceId: 'rel-1', noteId: 'note-1', ...folderFields, label: 'Amara remembers Arcadia', text: 'relationship fact', evidenceIds: ['a1'], lane: 'relationship_fact', structuralRole: 'fact', admissionTier: 2, parentIds: ['embed:entity:amara'] },
        ] as const;
        const posts = targets.map((target, index) => overloadedHopfPost(target.id, 'embed:note:note-1', index / targets.length, target.kind));
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-multidoc-caps',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [{
                id: 'a1',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                surface: 'Amara',
                sourceStart: 0,
                sourceEnd: 5,
                source: 'dynamic-ner',
                confidence: 0.92,
                entityId: 'amara',
                status: 'accepted',
                generation: 1,
            }, {
                id: 'a2',
                noteId: 'note-2',
                chunkId: 'chunk-2',
                surface: 'Amara',
                sourceStart: 0,
                sourceEnd: 5,
                source: 'dynamic-ner',
                confidence: 0.9,
                entityId: 'amara',
                status: 'accepted',
                generation: 1,
            }],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [...targets],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            embeddingGraphPostProcess: {
                schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
                targetCount: targets.length,
                vectorDimensions: 384,
                clusters: [],
                productTopologyRegions: posts.map((post) => post.productTopologyRegion),
                targets: posts,
                backboneEdges: [],
                bridgeEdges: [],
                outlierTargetIds: [],
                metrics: {
                    clusterCount: 1,
                    singletonCount: 0,
                    largestClusterSize: targets.length,
                    largestClusterRatio: 1,
                    backboneEdgeCount: 0,
                    bridgeEdgeCount: 0,
                    outlierCount: 0,
                    maxHubScore: 0.8,
                    meanNeighborCount: 1,
                },
            },
        }, 'lorentz');

        const byId = new Map(atlas.nodes.map((node) => [node.id, node.metadata?.lorentz as Record<string, unknown>]));
        const noteOne = byId.get('embed:note:note-1')!;
        const noteTwo = byId.get('embed:note:note-2')!;
        const rootOne = byId.get('embed:structure-root:note-1:identity')!;
        const rootTwo = byId.get('embed:structure-root:note-2:identity')!;
        const chunkOne = byId.get('embed:chunk:chunk-1')!;
        const entity = byId.get('embed:entity:amara')!;
        const fact = byId.get('embed:graph-fact:rel-1')!;

        expect(rootOne['capId']).toBe('document:note-1:root:identity');
        expect(rootTwo['capId']).toBe('document:note-2:root:identity');
        expect(entity['capId']).toBe('document:note-1:chunk:chunk-1:evidence:entity:amara');
        expect(entity['parentCapIds']).toEqual(expect.arrayContaining([
            'document:note-1:chunk:chunk-1:evidence',
            'document:note-2:chunk:chunk-2:evidence',
        ]));
        expect(entity['supportNoteIds']).toEqual(['note-1', 'note-2']);
        expect(dot3(entity['capDirection'] as number[], average3(noteOne['capDirection'] as number[], noteTwo['capDirection'] as number[]))).toBeGreaterThan(0.82);
        expect(Number(noteOne['shellRadius'])).toBeGreaterThan(Number(rootOne['shellRadius']));
        expect(Number(rootOne['shellRadius'])).toBeGreaterThan(Number(chunkOne['shellRadius']));
        expect(Number(chunkOne['shellRadius'])).toBeGreaterThan(Number(entity['shellRadius']));
        expect(Number(fact['shellRadius'])).toBeGreaterThan(Number(entity['shellRadius']));
    });

    it('carries graph-rebuild targets into Siegel-Finsler metadata', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-siegel',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:note:note-1', kind: 'note', sourceId: 'note-1', noteId: 'note-1', label: 'Red Mesa', text: 'chapter text', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionStatus: 'admitted' },
                { id: 'embed:structure-root:note-1:identity', kind: 'structureRoot', sourceId: 'note-1:identity', noteId: 'note-1', label: 'Identity root', text: 'identity structure', evidenceIds: [], lane: 'document_spine', structuralRole: 'root', admissionStatus: 'admitted', parentIds: ['embed:note:note-1'] },
                { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Chunk 1', text: 'sharp chunk', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionStatus: 'admitted', parentIds: ['embed:structure-root:note-1:identity'] },
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'mentions:3 evidence_context:Kai', evidenceIds: ['a1'], lane: 'entity_anchor', structuralRole: 'child', admissionStatus: 'admitted', parentIds: ['embed:chunk:chunk-1'] },
                { id: 'embed:memory:m1', kind: 'memoryState', sourceId: 'm1', entityId: 'kai', entityKind: 'CHARACTER', noteId: 'note-1', label: 'rank_or_status', text: 'rank_or_status for Kai', evidenceIds: ['a1'], lane: 'memory_state', structuralRole: 'child', admissionStatus: 'admitted', parentIds: ['embed:entity:kai'] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
        }, 'siegel');

        const kai = atlas.nodes.find((node) => node.id === 'embed:entity:kai')!;
        const note = atlas.nodes.find((node) => node.id === 'embed:note:note-1')!;
        const root = atlas.nodes.find((node) => node.id === 'embed:structure-root:note-1:identity')!;
        const chunk = atlas.nodes.find((node) => node.id === 'embed:chunk:chunk-1')!;
        const status = atlas.nodes.find((node) => node.id === 'embed:memory:m1')!;
        const zValues = atlas.nodes.map((node) => Number(node.atlasZ));
        expect(atlas.manifold).toMatchObject({
            mode: 'siegel',
            geometryVersion: 'graph_rebuild_siegel_finsler_v1',
        });
        expect(atlas.sourceLabel).toContain('siegel-finsler');
        expect(kai.metadata?.siegel).toMatchObject({
            lane: 'character',
            depth: 5,
            parentIds: ['embed:chunk:chunk-1'],
            directed: true,
        });
        expect(status).toMatchObject({ kind: 'memory-state' });
        expect(status.metadata).toMatchObject({
            graphColorKind: 'rank-status',
            graphMemoryStateKind: 'rankStatus',
        });
        expect(status.metadata?.siegel).toMatchObject({
            lane: 'stateContext',
            depth: 7,
            parentIds: ['embed:entity:kai'],
            directed: true,
        });
        expect(kai.metadata?.siegel?.['matrixCells']).toHaveLength(6);
        expect(Number(note.atlasY)).toBeGreaterThan(Number(root.atlasY));
        expect(Number(root.atlasY)).toBeGreaterThan(Number(chunk.atlasY));
        expect(Number(chunk.atlasY)).toBeGreaterThan(Number(kai.atlasY));
        expect(Math.max(...zValues) - Math.min(...zValues)).toBeGreaterThan(0.45);
        expect(atlas.edges.map((edge) => edge.type)).toContain('target-parent');
    });

    it('forms Hopf bases from point resonance instead of postprocess medoids', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-hopf',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', label: 'Kai', text: 'Kai maps Red Mesa', evidenceIds: [] },
                { id: 'embed:entity:rowan', kind: 'entity', sourceId: 'rowan', entityId: 'rowan', label: 'Rowan', text: 'Rowan reads authority lines', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            embeddingGraphPostProcess: {
                schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
                profile: null as any,
                adapter: null as any,
                targetCount: 2,
                vectorDimensions: 786,
                clusters: [],
                productTopologyRegions: [],
                targets: [
                    hopfPost('embed:entity:kai', 'embed:entity:kai', 0.2),
                    hopfPost('embed:entity:rowan', 'embed:entity:kai', 0.8),
                ],
                backboneEdges: [],
                bridgeEdges: [],
                outlierTargetIds: [],
                metrics: null as any,
            },
        }, 'hopf');

        const kai = atlas.nodes.find((node) => node.id === 'embed:entity:kai')!;
        const rowan = atlas.nodes.find((node) => node.id === 'embed:entity:rowan')!;
        expect(kai.metadata?.hopf).toMatchObject({
            role: 'anchor',
            baseId: 'hopf:resonance:embed-entity-kai',
            phase: 0,
            resonanceSource: 'point-formed',
            resonanceAdmitted: true,
        });
        expect(rowan.metadata?.hopf).toMatchObject({
            role: 'fiber',
            baseId: 'hopf:resonance:embed-entity-kai',
            fiberKind: 'identity',
            clusterId: 'embedding-cluster:0',
            resonanceSource: 'point-formed',
        });
        expect(rowan.metadata?.hopf?.['phase']).not.toBe(0.8);
    });

    it('uses snapshot Hopf resonance cells when the backend universe is present', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-hopf-contract',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: [
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', label: 'Kai', text: 'Kai maps Red Mesa', evidenceIds: [] },
                { id: 'embed:entity:rowan', kind: 'entity', sourceId: 'rowan', entityId: 'rowan', label: 'Rowan', text: 'Rowan reads authority lines', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            hopfResonanceSpace: {
                schemaVersion: 'phoenix-hopf-resonance-space/v1',
                generatedAt: 1,
                sourceSnapshotId: 'snapshot-hopf-contract',
                profile: null as any,
                cellResolution: 3,
                targetCount: 2,
                assignments: [
                    {
                        targetId: 'embed:entity:kai',
                        targetKind: 'entity',
                        label: 'Kai',
                        entityId: 'kai',
                        role: 'fiber-sample',
                        fiberKind: 'entity_sample',
                        baseCellId: 'hopf:ico:r3:alpha',
                        secondaryCellIds: ['hopf:ico:r3:beta'],
                        direction: [1, 0, 0],
                        tangent: [0, 1, 0],
                        phase: 0.12,
                        phaseRadians: Math.PI * 0.24,
                        assignmentScore: 0.92,
                        residualScore: 0.08,
                        salience: 0.77,
                        evidenceIds: [],
                        parentIds: [],
                        receipt: 'phase1b_no_topology_mutation:kai',
                    },
                    {
                        targetId: 'embed:entity:rowan',
                        targetKind: 'entity',
                        label: 'Rowan',
                        entityId: 'rowan',
                        role: 'fiber-sample',
                        fiberKind: 'entity_sample',
                        baseCellId: 'hopf:ico:r3:alpha',
                        secondaryCellIds: ['hopf:ico:r3:beta'],
                        direction: [0.9, 0.1, 0],
                        tangent: [0, 1, 0],
                        phase: 0.35,
                        phaseRadians: Math.PI * 0.7,
                        assignmentScore: 0.88,
                        residualScore: 0.12,
                        salience: 0.7,
                        evidenceIds: [],
                        parentIds: [],
                        receipt: 'phase1b_no_topology_mutation:rowan',
                    },
                ],
                cells: [{
                    id: 'hopf:ico:r3:alpha',
                    ordinal: 0,
                    resolution: 3,
                    center: [1, 0, 0],
                    neighborCellIds: ['hopf:ico:r3:beta'],
                    targetCount: 2,
                    sampleCount: 2,
                    totalWeight: 1.8,
                    dominantFiberKinds: ['entity_sample'],
                    anchorTargetIds: ['embed:entity:kai'],
                }],
                fibers: [{
                    id: 'hopf:fiber:hopf-ico-r3-alpha:entity_sample',
                    cellId: 'hopf:ico:r3:alpha',
                    fiberKind: 'entity_sample',
                    targetIds: ['embed:entity:kai', 'embed:entity:rowan'],
                    anchorTargetId: 'embed:entity:kai',
                    sampleCount: 2,
                    totalWeight: 1.8,
                    meanPhase: 0.23,
                    coherence: 0.81,
                    frustration: 0.19,
                }],
                docCharts: [],
                braids: [],
                counters: null as any,
            },
        }, 'hopf');

        const kai = atlas.nodes.find((node) => node.id === 'embed:entity:kai')!;
        const rowan = atlas.nodes.find((node) => node.id === 'embed:entity:rowan')!;
        expect(kai.metadata?.hopf).toMatchObject({
            role: 'anchor',
            baseId: 'hopf:ico:r3:alpha',
            cellId: 'hopf:ico:r3:alpha',
            fiberKind: 'entity_sample',
            resonanceSource: 'snapshot-hopf-resonance-space',
            resonanceAdmitted: true,
            noTopologyMutation: true,
            receipt: 'phase1b_no_topology_mutation:kai',
            support: 0.92,
            coherence: 0.81,
            frustration: 0.19,
        });
        expect(rowan.metadata?.hopf).toMatchObject({
            role: 'fiber',
            baseId: 'hopf:ico:r3:alpha',
            phase: 0.35,
            assignmentScore: 0.88,
            residualScore: 0.12,
            salience: 0.7,
            neighborCount: 1,
            resonanceSource: 'snapshot-hopf-resonance-space',
        });
    });

    it('splits overloaded graph-rebuild Hopf bases into semantic subfibers', () => {
        const rootId = 'embed:entity:kai';
        const targets = [
            { id: rootId, kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'Kai maps Red Mesa', evidenceIds: [] },
            ...Array.from({ length: 35 }, (_, index) => ({
                id: `embed:entity:character-${index}`,
                kind: 'entity',
                sourceId: `character-${index}`,
                entityId: `character-${index}`,
                entityKind: 'CHARACTER',
                label: `Character ${index}`,
                text: `Character ${index} crosses the boundary`,
                evidenceIds: [],
            })),
            ...Array.from({ length: 35 }, (_, index) => ({
                id: `embed:relationship:observe-${index}`,
                kind: 'graphFact',
                sourceId: `observe-${index}`,
                label: `Observation ${index}`,
                text: `Kai observes Hazel near Red Mesa ${index}`,
                evidenceIds: [],
            })),
            ...Array.from({ length: 35 }, (_, index) => ({
                id: `embed:chunk:${index}`,
                kind: 'chunk',
                sourceId: `chunk-${index}`,
                noteId: `note-${index % 4}`,
                chunkId: `chunk-${index}`,
                label: `Chunk ${index}`,
                text: `Chunk text ${index}`,
                evidenceIds: [],
            })),
        ];
        const posts = targets.map((target, index) => overloadedHopfPost(target.id, rootId, (index % 17) / 17, target.kind));
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-overloaded-hopf',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-0', 'note-1', 'note-2', 'note-3'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [],
            events: [],
            episodes: [],
            temporalEdges: [],
            causalEdges: [],
            memoryState: [],
            embeddingTargets: targets,
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
            embeddingGraphPostProcess: {
                schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
                profile: null as any,
                adapter: null as any,
                targetCount: targets.length,
                vectorDimensions: 786,
                clusters: [],
                productTopologyRegions: posts.map((post) => post.productTopologyRegion),
                targets: posts,
                backboneEdges: [],
                bridgeEdges: [],
                outlierTargetIds: [],
                metrics: null as any,
            },
        }, 'hopf');

        const counts = new Map<string, number>();
        for (const node of atlas.nodes) {
            const baseId = String(node.metadata?.hopf?.['baseId'] || '');
            if (!baseId) continue;
            counts.set(baseId, (counts.get(baseId) || 0) + 1);
        }
        expect(counts.size).toBeGreaterThan(1);
        expect(Math.max(...counts.values())).toBeLessThanOrEqual(9);
        expect(atlas.nodes.some((node) => String(node.metadata?.hopf?.['fiberKind'] || '').includes('observation'))).toBe(true);
    });

    it('keeps story structure targets visible when multi-note targets exceed the render cap', () => {
        const fillerTargets = Array.from({ length: 470 }, (_, index) => ({
            id: `embed:chunk:filler-${index}`,
            kind: 'chunk',
            sourceId: `filler-${index}`,
            noteId: 'note-fill',
            chunkId: `filler-${index}`,
            label: `Filler ${index}`,
            text: `filler text ${index}`,
            evidenceIds: [],
        }));
        const atlas = buildGraphRebuildEmbeddingAtlas({
            schemaVersion: 'phoenix-graph-rebuild/v1',
            id: 'snapshot-over-cap',
            source: 'phoenix-graph-rebuild',
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
            builtAt: 1,
            chunks: [],
            mentions: [],
            entityAnchors: [],
            relationships: [{
                id: 'co-1',
                sourceEntityId: 'kai',
                targetEntityId: 'hazel',
                relationType: 'co_occurs_with',
                status: 'review',
                confidence: 0.68,
                evidenceAnchorIds: [],
                adjudicationSource: 'graph-rebuild-cooccurrence-policy',
                adjudicationScore: 0.68,
                rationale: 'review: repeated co-occurrence',
                decisionEvidence: [],
            }],
            events: [
                { id: 'event:note-1:0:dialogue_event', noteId: 'note-1', chunkId: 'chunk-a', label: 'dialogue event', entityIds: [], evidenceAnchorIds: [], confidence: 0.7 },
                { id: 'event:note-1:1:process_event', noteId: 'note-1', chunkId: 'chunk-b', label: 'process event', entityIds: [], evidenceAnchorIds: [], confidence: 0.7 },
            ],
            episodes: [],
            temporalEdges: [{
                id: 'temporal:event:note-1:0:dialogue_event:event:note-1:1:process_event',
                sourceId: 'event:note-1:0:dialogue_event',
                targetId: 'event:note-1:1:process_event',
                relationType: 'before',
                evidenceIds: ['event:note-1:0:dialogue_event', 'event:note-1:1:process_event'],
                confidence: 0.7,
            }],
            causalEdges: [{
                id: 'causal:event:note-1:0:dialogue_event:event:note-1:1:process_event',
                sourceId: 'event:note-1:0:dialogue_event',
                targetId: 'event:note-1:1:process_event',
                relationType: 'causes_or_explains',
                evidenceIds: ['event:note-1:0:dialogue_event', 'event:note-1:1:process_event'],
                confidence: 0.7,
            }],
            memoryState: [],
            embeddingTargets: [
                ...fillerTargets,
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'Kai', evidenceIds: [] },
                { id: 'embed:entity:hazel', kind: 'entity', sourceId: 'hazel', entityId: 'hazel', entityKind: 'CHARACTER', label: 'Hazel', text: 'Hazel', evidenceIds: [] },
                { id: 'embed:graph-fact:co-1', kind: 'graphFact', sourceId: 'co-1', label: 'Kai co_occurs_with Hazel', text: 'Kai co_occurs_with Hazel [review]', evidenceIds: [] },
                { id: 'embed:event:event:note-1:0:dialogue_event', kind: 'event', sourceId: 'event:note-1:0:dialogue_event', noteId: 'note-1', label: 'dialogue event', text: 'dialogue event', evidenceIds: [] },
                { id: 'embed:event:event:note-1:1:process_event', kind: 'event', sourceId: 'event:note-1:1:process_event', noteId: 'note-1', label: 'process event', text: 'process event', evidenceIds: [] },
                { id: 'embed:temporalFact:temporal:event:note-1:0:dialogue_event:event:note-1:1:process_event', kind: 'temporalFact', sourceId: 'temporal:event:note-1:0:dialogue_event:event:note-1:1:process_event', label: 'before', text: 'event before event', evidenceIds: [] },
                { id: 'embed:causalFact:causal:event:note-1:0:dialogue_event:event:note-1:1:process_event', kind: 'causalFact', sourceId: 'causal:event:note-1:0:dialogue_event:event:note-1:1:process_event', label: 'causes_or_explains', text: 'event causes event', evidenceIds: [] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
        }, 'product');

        const nodeIds = new Set(atlas.nodes.map((node) => node.id));
        expect(atlas.nodes).toHaveLength(fillerTargets.length + 6);
        expect(nodeIds.has('embed:graph-fact:co-1')).toBe(false);
        expect([...nodeIds].filter((id) => id.includes('kai') || id.includes('hazel') || id.includes('co-1')).sort()).toEqual([
            'embed:entity:hazel',
            'embed:entity:kai',
        ]);
        expect(nodeIds.has('embed:temporalFact:temporal:event:note-1:0:dialogue_event:event:note-1:1:process_event')).toBe(true);
        expect(nodeIds.has('embed:causalFact:causal:event:note-1:0:dialogue_event:event:note-1:1:process_event')).toBe(true);
        expect(atlas.edges.map((edge) => edge.type)).toEqual(expect.arrayContaining(['co_occurs_with', 'before', 'causes_or_explains']));
    });
});

function packetTarget(
    id: string,
    family: string,
    kind: string,
    styleKey: string,
    sourceId: string,
    overrides: Record<string, unknown> = {},
) {
    return {
        id,
        objectId: `object:${sourceId}`,
        family,
        admission: 'admitted',
        status: 'accepted',
        vectorStatus: 'missing',
        coordinateSource: 'deterministic-signature',
        kind,
        label: id,
        styleKey,
        sourceId,
        evidenceIds: [],
        ...overrides,
    };
}

function packetObject(
    id: string,
    family: string,
    kind: string,
    styleKey: string,
    sourceIds: string[],
    overrides: Record<string, unknown> = {},
) {
    return {
        id,
        family,
        status: 'accepted',
        kind,
        label: id,
        styleKey,
        noteIds: [],
        chunkIds: [],
        anchorIds: [],
        evidenceIds: [],
        sourceIds,
        targetIds: [],
        ...overrides,
    };
}

function packetSnapshot(id: string, targets: unknown[], objects: unknown[] = []) {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id,
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        builtAt: 1,
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
        counters: { embeddingTargets: targets.length },
        atlasPacket: {
            schemaVersion: 'phoenix-atlas-packet/v1',
            snapshotId: id,
            scopeKind: 'global',
            scopeId: 'global',
            builtAt: 1,
            sourceContract: {
                authority: 'rust-atlas-packet',
                identityAuthority: 'registry-entities-and-accepted-anchors',
                vectorContract: 'vectors missing',
                tsGraphBuilderRole: 'native-atlas-packet-authority',
            },
            objects,
            manifoldTargets: targets,
            counters: {
                objects: objects.length,
                manifoldTargets: targets.length,
                registryEntities: 0,
                evidenceAnchors: 0,
                modelVectors: 0,
                families: [],
            },
        },
    } as any;
}
