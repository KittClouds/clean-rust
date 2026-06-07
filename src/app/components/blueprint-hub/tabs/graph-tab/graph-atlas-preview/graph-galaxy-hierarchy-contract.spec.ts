import { describe, expect, it } from 'vitest';

import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { buildGalaxyScene, mergeGalaxySettings, type GalaxyRenderableNode } from './graph-galaxy-engine';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';
import { buildGraphRebuildEmbeddingAtlas } from './graph-rebuild-embedding-atlas';
import { validateHierarchyShellContract } from './graph-galaxy-hierarchy-caps';

describe('graph galaxy hierarchy contract', () => {
    it('cannot render inverted Caps shells even when metadata lies', () => {
        const scene = buildGalaxyScene([
            contractNode('embed:note:note-1', 'Document', 'note', 'document_spine', 1.1),
            contractNode('embed:structure-root:note-1:identity', 'Identity root', 'structureRoot', 'document_spine', 0.8),
            contractNode('embed:chunk:chunk-1', 'Chunk', 'chunk', 'chunk_spine', 2.12),
            contractNode('embed:entity:kai', 'Kai', 'entity', 'entity_anchor', 2.08),
            contractNode('embed:graph-fact:trust', 'Kai trusts Hazel', 'graphFact', 'relationship_fact', 1.92),
            contractNode('embed:anchor:mention-1', 'Kai mention', 'anchor', 'anchor_evidence', 1.72),
        ], [
            edge('doc-root', 'embed:note:note-1', 'embed:structure-root:note-1:identity', 'target-parent'),
            edge('root-chunk', 'embed:structure-root:note-1:identity', 'embed:chunk:chunk-1', 'target-parent'),
            edge('chunk-entity', 'embed:chunk:chunk-1', 'embed:entity:kai', 'chunk-entity'),
            edge('entity-fact', 'embed:entity:kai', 'embed:graph-fact:trust', 'relationship'),
            edge('entity-anchor', 'embed:entity:kai', 'embed:anchor:mention-1', 'anchor-entity'),
        ], mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, radius(node)]));

        expect(validateHierarchyShellContract(scene.nodes)).toEqual([]);
        expect(byId.get('embed:note:note-1')!).toBeGreaterThan(byId.get('embed:structure-root:note-1:identity')!);
        expect(byId.get('embed:structure-root:note-1:identity')!).toBeGreaterThan(byId.get('embed:chunk:chunk-1')!);
        expect(byId.get('embed:chunk:chunk-1')!).toBeGreaterThan(byId.get('embed:entity:kai')!);
        expect(byId.get('embed:entity:kai')!).toBeGreaterThan(byId.get('embed:graph-fact:trust')!);
        expect(byId.get('embed:graph-fact:trust')!).toBeGreaterThan(byId.get('embed:anchor:mention-1')!);
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
        expect(byId.get('embed:entity:kai')!).toBeGreaterThan(byId.get('embed:graph-fact:echo')!);
    });

    it('carries hierarchy shells into the runtime scene contract', () => {
        const atlas = buildGraphRebuildEmbeddingAtlas(contractSnapshot(), 'lorentz');
        const scene = buildGalaxyScene(atlas.nodes, atlas.edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const runtime = galaxySceneToV2(scene, 'embeddings');
        const indexById = new Map(runtime.ids.map((id, index) => [id, index]));

        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:note:note-a')!]).toBeCloseTo(2.08, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:structure-root:note-a:identity')!]).toBeCloseTo(1.92, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:chunk:note-a:chunk-1')!]).toBeCloseTo(1.66, 3);
        expect(runtime.hierarchyShellRadii?.[indexById.get('embed:entity:kai')!]).toBeCloseTo(1.42, 3);
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
        expect(scene.nodes.length).toBe(atlas.nodes.length);
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

function radius(node: { x: number; y: number; z: number }): number {
    return Number(Math.hypot(node.x, node.y, node.z).toFixed(4));
}
