import { describe, expect, it } from 'vitest';
import { DEFAULT_ENTITY_COLORS, DEFAULT_GRAPH_NODE_COLORS } from '../../../../../lib/store/entityColorStore';
import type { NoteBlockProjection } from '../../../../../lib/dexie/db';
import { buildGraphModelV2Snapshot } from '../../../../../graph-rebuild/graph-model-v2';
import { buildLeafEmbeddingAtlas } from './graph-embedding-atlas';
import { buildGraphRebuildEmbeddingAtlas } from './graph-rebuild-embedding-atlas';

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
        expect(nodes.get('embed:entity:baton')?.kind).toBe('location');
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
            level: 3,
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
            signalLane: 'document_spine',
            parentNodeId: 'embed:note:note-1',
        });
        expect(byId.get('embed:chunk:chunk-1')).toMatchObject({
            capId: 'document:note-1:chunks',
            signalLane: 'chunk_spine',
            parentNodeId: 'embed:structure-root:note-1:document-structure',
        });
        expect(byId.get('embed:entity:kai')).toMatchObject({ capId: 'document:note-1:entities', signalLane: 'entity_anchor' });
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
        expect(chunk['capId']).toBe('document:note-1:chunks');
        expect(entity['capId']).toBe('document:note-1:entities');
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
        expect(entity['capId']).toMatch(/^entity:amara:docs:/);
        expect(entity['supportNoteIds']).toEqual(['note-1', 'note-2']);
        expect(dot3(entity['capDirection'] as number[], average3(noteOne['capDirection'] as number[], noteTwo['capDirection'] as number[]))).toBeGreaterThan(0.82);
        expect(Number(noteOne['shellRadius'])).toBeGreaterThan(Number(rootOne['shellRadius']));
        expect(Number(rootOne['shellRadius'])).toBeGreaterThan(Number(chunkOne['shellRadius']));
        expect(Number(chunkOne['shellRadius'])).toBeGreaterThan(Number(entity['shellRadius']));
        expect(Number(entity['shellRadius'])).toBeGreaterThan(Number(fact['shellRadius']));
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
                { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', noteId: 'note-1', chunkId: 'chunk-1', label: 'Chunk 1', text: 'sharp chunk', evidenceIds: [], lane: 'chunk_spine', structuralRole: 'spine', admissionStatus: 'admitted', parentIds: ['embed:note:note-1'] },
                { id: 'embed:entity:kai', kind: 'entity', sourceId: 'kai', entityId: 'kai', entityKind: 'CHARACTER', label: 'Kai', text: 'mentions:3 evidence_context:Kai', evidenceIds: ['a1'], lane: 'entity_anchor', structuralRole: 'child', admissionStatus: 'admitted', parentIds: ['embed:chunk:chunk-1'] },
            ],
            embeddingVectors: [],
            projectionRefs: [],
            nodes: [],
            edges: [],
            counters: null as any,
        }, 'siegel');

        const kai = atlas.nodes.find((node) => node.id === 'embed:entity:kai')!;
        expect(atlas.manifold).toMatchObject({
            mode: 'siegel',
            geometryVersion: 'graph_rebuild_siegel_finsler_v1',
        });
        expect(atlas.sourceLabel).toContain('siegel-finsler');
        expect(kai.metadata?.siegel).toMatchObject({
            lane: 'entity',
            depth: 3,
            parentIds: ['embed:chunk:chunk-1'],
            directed: true,
        });
        expect(kai.metadata?.siegel?.['matrixCells']).toHaveLength(6);
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
