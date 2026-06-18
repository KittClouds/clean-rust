import { describe, expect, it } from 'vitest';

import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { buildGalaxyScene, mergeGalaxySettings, type GalaxyRenderableNode } from './graph-galaxy-engine';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';
import { buildGraphRebuildEmbeddingAtlas } from './graph-rebuild-embedding-atlas';
import { hierarchyShellBandsInOrder, validateHierarchyShellContract } from './graph-galaxy-hierarchy-caps';

describe('graph galaxy hierarchy contract', () => {
    it('cannot render inverted Caps shells even when metadata lies', () => {
        const scene = buildGalaxyScene([
            contractNode('embed:note:note-1', 'Document', 'note', 'document_spine', 1.1),
            contractNode('embed:structure-root:note-1:identity', 'Identity root', 'structureRoot', 'document_spine', 0.8),
            contractNode('embed:chunk:chunk-1', 'Chunk', 'chunk', 'chunk_spine', 2.12),
            contractNode('embed:entity:kai', 'Kai', 'entity', 'entity_anchor', 2.08),
            contractNode('embed:event:trust', 'Kai trusts Hazel', 'event', 'event_identity', 1.92),
            contractNode('embed:anchor:mention-1', 'Kai mention', 'anchor', 'anchor_evidence', 1.72),
        ], [
            edge('doc-root', 'embed:note:note-1', 'embed:structure-root:note-1:identity', 'target-parent'),
            edge('root-chunk', 'embed:structure-root:note-1:identity', 'embed:chunk:chunk-1', 'target-parent'),
            edge('chunk-entity', 'embed:chunk:chunk-1', 'embed:entity:kai', 'chunk-entity'),
            edge('entity-event', 'embed:entity:kai', 'embed:event:trust', 'event-entity'),
            edge('entity-anchor', 'embed:entity:kai', 'embed:anchor:mention-1', 'anchor-entity'),
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, radius(node)]));

        expect(validateHierarchyShellContract(scene.nodes)).toEqual([]);
        expect(byId.get('embed:note:note-1')!).toBeGreaterThan(byId.get('embed:structure-root:note-1:identity')!);
        expect(byId.get('embed:structure-root:note-1:identity')!).toBeGreaterThan(byId.get('embed:chunk:chunk-1')!);
        expect(byId.get('embed:chunk:chunk-1')!).toBeGreaterThan(byId.get('embed:anchor:mention-1')!);
        expect(byId.get('embed:anchor:mention-1')!).toBeGreaterThan(byId.get('embed:entity:kai')!);
        expect(byId.get('embed:entity:kai')!).toBeGreaterThan(byId.get('embed:event:trust')!);
    });

    it('preserves document-root-chunk-entity order for graph rebuild Caps snapshots', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas(contractSnapshot(), 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, radius(node)]));

        expect(validateHierarchyShellContract(scene.nodes)).toEqual([]);
        for (const noteId of ['note-a', 'note-b']) {
            expect(byId.get(`embed:note:${noteId}`)!).toBeGreaterThan(byId.get(`embed:structure-root:${noteId}:identity`)!);
            expect(byId.get(`embed:structure-root:${noteId}:identity`)!).toBeGreaterThan(byId.get(`embed:chunk:${noteId}:chunk-1`)!);
        }
        expect(byId.get('embed:chunk:note-a:chunk-1')!).toBeGreaterThan(byId.get('embed:entity:kai')!);
        expect(scene.nodes.some((node) => node.entity.id === 'embed:graph-fact:echo')).toBe(false);
    });

    it('carries hierarchy shells into the runtime scene contract', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas(contractSnapshot(), 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const runtime = galaxySceneToV2(scene, 'embeddings');
        const indexById = new Map(runtime.ids.map((id, index) => [id, index]));

        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:note:note-a')!]).toBeCloseTo(2.1, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:structure-root:note-a:identity')!]).toBeCloseTo(1.78, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:chunk:note-a:chunk-1')!]).toBeCloseTo(1.46, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:entity:kai')!]).toBeCloseTo(0.86, 3);
    });

    it('keeps mixed Atlas taxonomy on the intended Embed Caps shells', () => {
        const scene = buildGalaxyScene([
            mixedNode('embed:note:note-a', 'note', 'document_spine', 'root', '', '', 0.4),
            mixedNode('embed:structure-root:note-a:identity', 'structureRoot', 'document_spine', 'root', '', '', 0.4),
            mixedNode('embed:chunk:note-a:chunk-1', 'chunk', 'chunk_spine', 'child', 'leaf', '', 2.08),
            mixedNode('embed:chunk:note-a:chunk-1:evidence:a1', 'anchor', 'anchor_evidence', 'evidence', 'chunk', '', 1.9),
            mixedNode('embed:entity:kai', 'entity', 'character', 'child', '', '', 1.8),
            mixedNode('embed:entity:kai:rank-state', 'entity', 'character', 'child', '', 'rankStatus', 1.7),
        ], [
            edge('note-root', 'embed:note:note-a', 'embed:structure-root:note-a:identity', 'target-parent'),
            edge('root-chunk', 'embed:structure-root:note-a:identity', 'embed:chunk:note-a:chunk-1', 'target-parent'),
            edge('chunk-evidence', 'embed:chunk:note-a:chunk-1', 'embed:chunk:note-a:chunk-1:evidence:a1', 'target-parent'),
            edge('evidence-entity', 'embed:chunk:note-a:chunk-1:evidence:a1', 'embed:entity:kai', 'anchor-entity'),
            edge('entity-state', 'embed:entity:kai', 'embed:entity:kai:rank-state', 'memory-entity'),
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree', sourceMode: 'embeddings' }));
        const runtime = galaxySceneToV2(scene, 'embeddings');
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, radius(node)]));
        const indexById = new Map(runtime.ids.map((id, index) => [id, index]));

        expect(byId.get('embed:chunk:note-a:chunk-1')!).toBeGreaterThan(byId.get('embed:chunk:note-a:chunk-1:evidence:a1')!);
        expect(byId.get('embed:chunk:note-a:chunk-1:evidence:a1')!).toBeGreaterThan(byId.get('embed:entity:kai')!);
        expect(byId.get('embed:entity:kai')!).toBeGreaterThan(byId.get('embed:entity:kai:rank-state')!);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:chunk:note-a:chunk-1:evidence:a1')!]).toBeCloseTo(1.14, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:entity:kai:rank-state')!]).toBeCloseTo(0.52, 3);
    });

    it('does not cap graph rebuild atlas visibility before the document spine', () => {
        const snapshot = contractSnapshot();
        snapshot.embeddingTargets.push(...Array.from({ length: 1100 }, (_, index) =>
            target(`embed:graph-fact:signal-${index}`, 'graphFact', `signal-${index}`, `Signal ${index} supports Kai [accepted]`, 'relationship_fact'),
        ));
        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const ids = new Set(atlas.nodes.map((node) => node.id));
        const sceneIds = new Set(scene.nodes.map((node) => node.entity.id));

        expect(atlas.nodes.length).toBeGreaterThan(960);
        expect(scene.nodes.length).toBeLessThan(atlas.nodes.length);
        expect(sceneIds.has('embed:graph-fact:signal-0')).toBe(false);
        for (const id of [
            'embed:note:note-a',
            'embed:note:note-b',
            'embed:structure-root:note-a:identity',
            'embed:structure-root:note-b:identity',
            'embed:chunk:note-a:chunk-1',
            'embed:chunk:note-b:chunk-1',
        ]) {
            expect(ids.has(id)).toBe(true);
            expect(sceneIds.has(id)).toBe(true);
        }
    });

    it('keeps every graph rebuild embedding target as a point in Embed Caps', () => {
        const snapshot = contractSnapshot();
        snapshot.embeddingTargets.push(...Array.from({ length: 96 }, (_, index) =>
            target(`embed:graph-fact:signal-${index}`, 'graphFact', `signal-${index}`, `Signal ${index} supports Kai [accepted]`, 'relationship_fact', 'note-a', 'note-a:chunk-1', ['embed:entity:kai']),
        ));
        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree', sourceMode: 'embeddings' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, radius(node)]));

        expect(scene.nodes).toHaveLength(atlas.nodes.length);
        expect(new Set(scene.nodes.map((node) => node.entity.id)).has('embed:graph-fact:signal-0')).toBe(true);
        expect(byId.get('embed:entity:kai')!).toBeGreaterThan(byId.get('embed:graph-fact:signal-0')!);
    });

    it('keeps dense Embed Caps children distributed around their hierarchy shell', () => {
        const snapshot = singleDocumentContractSnapshot();
        snapshot.embeddingTargets.push(...Array.from({ length: 32 }, (_, index) =>
            target(`embed:graph-fact:ring-${index}`, 'graphFact', `ring-${index}`, `Ring fact ${index}`, 'relationship_fact', 'note-a', 'note-a:chunk-1', ['embed:entity:kai']),
        ));
        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree', sourceMode: 'embeddings' }));
        const factNodes = scene.nodes.filter((node) => node.entity.id.startsWith('embed:graph-fact:ring-'));

        expect(validateHierarchyShellContract(scene.nodes)).toEqual([]);
        expect(factNodes).toHaveLength(32);
        for (const node of factNodes) {
            expect(radius(node)).toBeCloseTo(0.66, 2);
        }
        expect(maxPairwiseDistance(factNodes)).toBeGreaterThan(0.5);
    });

    it('uses structural forest ownership instead of flat type caps', () => {
        const snapshot = contractSnapshot();
        snapshot.embeddingTargets.push(
            target('embed:event:event-a', 'event', 'event-a', 'Warning event', 'event_identity', 'note-a', 'note-a:chunk-1', ['embed:chunk:note-a:chunk-1']),
            target('embed:event:event-b', 'event', 'event-b', 'Outcome event', 'event_identity', 'note-a', 'note-a:chunk-1', ['embed:chunk:note-a:chunk-1']),
            target('embed:causalFact:cause-1', 'causalFact', 'cause-1', 'causes_or_explains', 'causal_fact', 'note-a', undefined, [
                'embed:structure-root:note-a:causal',
                'embed:event:event-a',
                'embed:event:event-b',
            ]),
        );
        attachPostProcess(snapshot);

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'lorentz');
        const byId = new Map(atlas.nodes.map((node) => [node.id, node]));
        const entityLorentz = byId.get('embed:entity:kai')?.metadata?.lorentz as Record<string, unknown>;
        const causalLorentz = byId.get('embed:causalFact:cause-1')?.metadata?.lorentz as Record<string, unknown>;

        expect(entityLorentz?.['capId']).toBe('document:note-a:chunk:note-a:chunk-1:evidence:entity:kai');
        expect(entityLorentz?.['parentCapIds']).toContain('document:note-a:chunk:note-a:chunk-1:evidence');
        expect(entityLorentz?.['parentNodeId']).toBe('embed:chunk:note-a:chunk-1');
        expect(causalLorentz?.['capId']).toBe('document:note-a:chunk:note-a:chunk-1:evidence:event:event-b:causal');
        expect(causalLorentz?.['parentCapIds']).toEqual(['document:note-a:chunk:note-a:chunk-1:evidence:event:event-b']);
        expect(causalLorentz?.['parentNodeId']).toBe('embed:event:event-b');
        expect(causalLorentz?.['supportChunkIds']).toEqual(['note-a:chunk-1']);
    });

    it('keeps explicit Embed Caps groups nested instead of flattening to the document cap', () => {
        const scene = buildGalaxyScene([
            capNode('embed:note:note-a', 'note', 'document:note-a', []),
            capNode('embed:structure-root:note-a:identity', 'structureRoot', 'document:note-a:root:identity', ['document:note-a']),
            capNode('embed:chunk:note-a:chunk-1', 'chunk', 'document:note-a:chunk:note-a:chunk-1', ['document:note-a:root:identity']),
            capNode('embed:anchor:mention-1', 'anchor', 'document:note-a:chunk:note-a:chunk-1:evidence', ['document:note-a:chunk:note-a:chunk-1']),
            capNode('embed:entity:kai', 'entity', 'document:note-a:chunk:note-a:chunk-1:evidence:entity:kai', ['document:note-a:chunk:note-a:chunk-1:evidence']),
            capNode('embed:memory:kai:rank', 'memoryState', 'document:note-a:chunk:note-a:chunk-1:evidence:entity:kai:memory', ['document:note-a:chunk:note-a:chunk-1:evidence:entity:kai']),
        ], [
            edge('note-root', 'embed:note:note-a', 'embed:structure-root:note-a:identity', 'target-parent'),
            edge('root-chunk', 'embed:structure-root:note-a:identity', 'embed:chunk:note-a:chunk-1', 'target-parent'),
            edge('chunk-anchor', 'embed:chunk:note-a:chunk-1', 'embed:anchor:mention-1', 'chunk-anchor'),
            edge('anchor-entity', 'embed:anchor:mention-1', 'embed:entity:kai', 'anchor-entity'),
            edge('entity-state', 'embed:entity:kai', 'embed:memory:kai:rank', 'memory-entity'),
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree', sourceMode: 'embeddings' }));
        const boundaryIds = rootLaneTreeIds(scene);

        expect(boundaryIds).toContain('document:note-a');
        expect(boundaryIds).toContain('document:note-a:root:identity');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1:evidence');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1:evidence:entity:kai');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1:evidence:entity:kai:memory');
    });

    it('synthesizes the Embed Caps hierarchy when embedding post-process vectors are missing', () => {
        const snapshot = singleDocumentContractSnapshot();
        snapshot.embeddingTargets.push(
            target('embed:anchor:mention-1', 'anchor', 'mention-1', 'Kai mention', 'anchor_evidence', 'note-a', 'note-a:chunk-1', ['embed:chunk:note-a:chunk-1']),
        );

        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree', sourceMode: 'embeddings' }));
        const byId = new Map(atlas.nodes.map((node) => [node.id, node]));
        const entityLorentz = byId.get('embed:entity:kai')?.metadata?.lorentz as Record<string, unknown>;
        const boundaryIds = rootLaneTreeIds(scene);

        expect(entityLorentz?.['capId']).toBe('document:note-a:chunk:note-a:chunk-1:evidence:entity:kai');
        expect(entityLorentz?.['parentCapIds']).toEqual(['document:note-a:chunk:note-a:chunk-1:evidence']);
        expect(boundaryIds).toContain('document:note-a:root:identity');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1:evidence');
        expect(boundaryIds).toContain('document:note-a:chunk:note-a:chunk-1:evidence:entity:kai');
    });

    it('draws Embed Caps level guides from the hierarchy contract', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas(singleDocumentContractSnapshot(), 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree', sourceMode: 'embeddings' }));
        const shellGuides = new Map((scene.lorentzGuides || [])
            .filter((guide) => guide.guideKind === 'levelShell')
            .map((guide) => [guide.id, guide]));

        for (const band of hierarchyShellBandsInOrder()) {
            const guide = shellGuides.get(`caps:shell:${band.id}`);
            expect(guide).toBeTruthy();
            expect(guideRadius(guide!.positions3d)).toBeCloseTo(band.radius, 3);
        }
    });

    it('does not silently downsample large scene nodes or unique edges', () => {
        const nodes = Array.from({ length: 1300 }, (_, index) =>
            contractNode(`embed:chunk:bulk-${index}`, `Chunk ${index}`, 'chunk', 'chunk_spine', 1.66),
        );
        const edges = Array.from({ length: nodes.length - 1 }, (_, index) =>
            edge(`bulk-edge-${index}`, nodes[index].id, nodes[index + 1].id, index % 3 === 0 ? 'target-parent' : 'embedding-backbone'),
        );

        const scene = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));

        expect(scene.nodes).toHaveLength(nodes.length);
        expect(scene.links).toHaveLength(edges.length);
    });
});

function contractNode(
    id: string,
    label: string,
    sourceType: string,
    signalLane: string,
    shellRadius: number,
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: sourceType,
        atlasX: 0.24,
        atlasY: 0.12,
        atlasZ: 1,
        totalMentions: 2,
        metadata: {
            sourceType,
            signalLane,
            targetConfidence: 0.9,
            lorentz: {
                capId: 'document:note-1',
                capDirection: [0.24, 0.12, 1],
                shellRadius,
                signalLane,
                primaryTreeKind: 'documentStructure',
            },
        },
    };
}

function attachPostProcess(snapshot: GraphRebuildSnapshot): void {
    snapshot.embeddingGraphPostProcess = {
        schemaVersion: 'phoenix-embedding-graph-postprocess/v1',
        profile: { id: 'test', selectedDimensions: 8 } as never,
        adapter: 'deterministic-local' as never,
        targetCount: snapshot.embeddingTargets.length,
        vectorDimensions: 8,
        clusters: [],
        productTopologyRegions: [],
        targets: snapshot.embeddingTargets.map((item, index) => ({
            targetId: item.id,
            clusterId: `cluster:${index}`,
            clusterRole: item.kind === 'entity' ? 'entity_region' : item.kind === 'event' ? 'event_region' : item.kind === 'causalFact' ? 'fact_region' : 'document_region',
            medoidTargetId: item.id,
            outlierScore: 0.05,
            hubScore: 0.1,
            neighborCount: 2,
            productLaneFeatures: {
                semanticDepth: 0.4,
                documentDepth: 0.7,
                relationDepth: 0.3,
                clusterRadius: 0.2,
                fiberPhase: index / Math.max(1, snapshot.embeddingTargets.length),
                confidence: 0.9,
                dominantLane: item.lane === 'causal_fact' ? 'causal' : item.lane === 'entity_anchor' ? 'entity' : item.lane === 'event_identity' ? 'temporal' : 'document',
                laneWeights: {
                    semantic: 0.1,
                    document: item.lane === 'document_spine' || item.lane === 'chunk_spine' ? 0.9 : 0.2,
                    relation: item.lane === 'relationship_fact' ? 0.9 : 0.1,
                    temporal: item.lane === 'event_identity' ? 0.8 : 0.1,
                    causal: item.lane === 'causal_fact' ? 0.9 : 0.1,
                    evidence: item.lane === 'anchor_evidence' ? 0.9 : 0.1,
                    entity: item.lane === 'entity_anchor' ? 0.9 : 0.1,
                },
            },
            productTopologyRegion: {
                id: `region:${index}`,
                role: 'core',
                laneKind: item.lane === 'causal_fact' ? 'causal' : item.lane === 'entity_anchor' ? 'entity' : item.lane === 'event_identity' ? 'temporal' : 'document',
                clusterId: `cluster:${index}`,
                medoidTargetId: item.id,
                memberCount: 1,
                density: 1,
                confidence: 0.9,
                bridgeTargetIds: [],
                backboneTargetIds: [item.id],
            },
        })),
        backboneEdges: [],
        bridgeEdges: [],
        outlierTargetIds: [],
        metrics: {
            clusterCount: snapshot.embeddingTargets.length,
            singletonCount: snapshot.embeddingTargets.length,
            largestClusterSize: 1,
            largestClusterRatio: 0,
            backboneEdgeCount: 0,
            bridgeEdgeCount: 0,
            outlierCount: 0,
            maxHubScore: 0,
            meanNeighborCount: 0,
        },
    };
}

function contractSnapshot(): GraphRebuildSnapshot {
    const targets = [
        target('embed:note:note-a', 'note', 'note-a', 'Note A', 'document_spine', 'note-a'),
        target('embed:note:note-b', 'note', 'note-b', 'Note B', 'document_spine', 'note-b'),
        target('embed:structure-root:note-a:identity', 'structureRoot', 'note-a:identity', 'Identity root A', 'document_spine', 'note-a', undefined, ['embed:note:note-a']),
        target('embed:structure-root:note-b:identity', 'structureRoot', 'note-b:identity', 'Identity root B', 'document_spine', 'note-b', undefined, ['embed:note:note-b']),
        target('embed:chunk:note-a:chunk-1', 'chunk', 'note-a:chunk-1', 'Chunk A', 'chunk_spine', 'note-a', 'note-a:chunk-1', ['embed:structure-root:note-a:identity']),
        target('embed:chunk:note-b:chunk-1', 'chunk', 'note-b:chunk-1', 'Chunk B', 'chunk_spine', 'note-b', 'note-b:chunk-1', ['embed:structure-root:note-b:identity']),
        target('embed:entity:kai', 'entity', 'kai', 'Kai', 'entity_anchor', undefined, undefined, ['embed:chunk:note-a:chunk-1', 'embed:chunk:note-b:chunk-1']),
        target('embed:graph-fact:echo', 'graphFact', 'echo', 'Echo relation', 'relationship_fact', 'note-a', 'note-a:chunk-1', ['embed:entity:kai']),
    ];
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'hierarchy-contract',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-a', 'note-b'],
        builtAt: 1,
        chunks: [
            { id: 'note-a:chunk-1', noteId: 'note-a', start: 0, end: 80, ordinal: 0, source: 'dynamic-chunking' },
            { id: 'note-b:chunk-1', noteId: 'note-b', start: 0, end: 80, ordinal: 0, source: 'dynamic-chunking' },
        ],
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
        nodes: [{ entityId: 'kai', label: 'Kai', kind: 'CHARACTER', anchorIds: [] }],
        edges: [],
        counters: null as never,
    };
}

function target(
    id: string,
    kind: string,
    sourceId: string,
    label: string,
    lane: string,
    noteId?: string,
    chunkId?: string,
    parentIds: string[] = [],
) {
    return { id, kind, sourceId, label, text: label, evidenceIds: [], lane, noteId, chunkId, parentIds };
}

function edge(id: string, sourceId: string, targetId: string, type: string) {
    return { id, sourceId, targetId, type, confidence: 0.9 };
}

function mixedNode(
    id: string,
    atlasKind: string,
    styleKey: string,
    structuralRole: string,
    documentUnitKind: string,
    stateContextKind: string,
    shellRadius: number,
): GalaxyRenderableNode {
    return {
        id,
        label: id,
        kind: atlasKind,
        atlasX: 0.24,
        atlasY: 0.12,
        atlasZ: 1,
        totalMentions: 2,
        metadata: {
            sourceType: atlasKind,
            atlasKind,
            atlasFamily: styleKey,
            atlasStructuralRole: structuralRole,
            atlasDocumentUnitKind: documentUnitKind,
            atlasStateContextKind: stateContextKind,
            styleKey,
            graphColorKind: styleKey,
            targetConfidence: 0.9,
            lorentz: {
                capId: 'document:note-a',
                capDirection: [0.24, 0.12, 1],
                shellRadius,
                signalLane: styleKey,
                primaryTreeKind: 'documentStructure',
            },
        },
    };
}

function capNode(
    id: string,
    sourceType: string,
    capId: string,
    parentCapIds: string[],
): GalaxyRenderableNode {
    const shellRadius = sourceType === 'note'
        ? 2.1
        : sourceType === 'structureRoot'
            ? 1.78
            : sourceType === 'chunk'
                ? 1.46
                : sourceType === 'anchor'
                    ? 1.14
                    : sourceType === 'entity'
                        ? 0.86
                        : 0.58;
    return {
        id,
        label: id,
        kind: sourceType,
        atlasX: 0.24,
        atlasY: 0.12,
        atlasZ: 1,
        totalMentions: 2,
        metadata: {
            sourceType,
            noteId: 'note-a',
            chunkId: id.includes(':chunk-1') || id.includes(':mention-1') || id.includes(':kai') ? 'note-a:chunk-1' : undefined,
            targetConfidence: 0.9,
            lorentz: {
                capId,
                parentCapIds,
                capDirection: [0.24, 0.12, 1],
                shellRadius,
                primaryTreeKind: 'documentStructure',
            },
        },
    };
}

function singleDocumentContractSnapshot(): GraphRebuildSnapshot {
    const snapshot = contractSnapshot();
    snapshot.noteIds = ['note-a'];
    snapshot.chunks = snapshot.chunks.filter((chunk) => chunk.noteId === 'note-a');
    snapshot.embeddingTargets = snapshot.embeddingTargets.filter((item) => !item.id.includes('note-b'));
    const entity = snapshot.embeddingTargets.find((item) => item.id === 'embed:entity:kai');
    if (entity) {
        entity.noteId = 'note-a';
        entity.chunkId = 'note-a:chunk-1';
        entity.parentIds = ['embed:chunk:note-a:chunk-1'];
    }
    return snapshot;
}

function rootLaneTreeIds(scene: { lorentzGuides?: Array<{ guideKind: string; treeId: string }> }): string[] {
    return (scene.lorentzGuides || [])
        .filter((guide) => guide.guideKind === 'rootLane')
        .map((guide) => guide.treeId);
}

function radius(node: { x: number; y: number; z: number }): number {
    return Number(Math.hypot(node.x, node.y, node.z).toFixed(4));
}

function guideRadius(positions: Float32Array): number {
    return Number(Math.hypot(positions[0], positions[1], positions[2]).toFixed(4));
}

function maxPairwiseDistance(nodes: Array<{ x: number; y: number; z: number }>): number {
    let maxDistance = 0;
    for (let left = 0; left < nodes.length; left++) {
        for (let right = left + 1; right < nodes.length; right++) {
            const dx = nodes[left].x - nodes[right].x;
            const dy = nodes[left].y - nodes[right].y;
            const dz = nodes[left].z - nodes[right].z;
            maxDistance = Math.max(maxDistance, Math.hypot(dx, dy, dz));
        }
    }
    return Number(maxDistance.toFixed(4));
}
