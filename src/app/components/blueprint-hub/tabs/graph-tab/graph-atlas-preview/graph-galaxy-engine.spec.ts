import { describe, expect, it } from 'vitest';

import {
    buildGalaxyScene,
    mergeGalaxySettings,
    resolveGalaxyNodeColorHsl,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
} from './graph-galaxy-engine';
import { galaxySceneToV2 } from './graph-galaxy-scene-v2';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';

describe('Graph galaxy scene prioritization', () => {
    it('keeps entity nodes and their edges when chunk evidence floods a graph snapshot', () => {
        const entities = Array.from({ length: 21 }, (_, index) => ({
            id: `entity-${index}`,
            label: index === 0 ? 'Aris' : `Character ${index}`,
            kind: 'CHARACTER',
            totalMentions: 1,
            atlasX: stable(index, 0),
            atlasY: stable(index, 1),
            atlasZ: stable(index, 2),
            metadata: {
                sourceType: 'graph-rebuild',
                graphKind: 'entity',
                sourceEntityId: `entity-${index}`,
            },
        } satisfies GalaxyRenderableNode));
        const chunks = Array.from({ length: 478 }, (_, index) => ({
            id: `chunk-${index}`,
            label: `Chunk ${index + 1}`,
            kind: 'chunk',
            totalMentions: 1,
            atlasX: stable(index + 1000, 0),
            atlasY: stable(index + 1000, 1),
            atlasZ: stable(index + 1000, 2),
            metadata: {
                sourceType: 'graph-rebuild',
                graphKind: 'chunk',
            },
        } satisfies GalaxyRenderableNode));
        const edges: GalaxyInputEdge[] = [
            { id: 'rel-0-1', sourceId: 'entity-0', targetId: 'entity-1', type: 'anchored-cooccurrence', confidence: 0.9 },
            { id: 'anchor-0', sourceId: 'chunk-0', targetId: 'entity-0', type: 'entity_anchor', confidence: 0.8 },
        ];

        const scene = buildGalaxyScene([...entities, ...chunks], edges, mergeGalaxySettings({ layoutMode: 'single' }));

        expect(scene.nodes.filter((node) => String(node.entity.kind).toLowerCase() === 'character')).toHaveLength(21);
        expect(scene.links.map((link) => link.id)).toContain('rel-0-1');
    });

    it('treats relationship facts as edge controls instead of topology nodes', () => {
        const nodes: GalaxyRenderableNode[] = [
            relationNode('embed:entity:kai', 'Kai', 'CHARACTER'),
            relationNode('embed:entity:hazel', 'Hazel', 'CHARACTER'),
            relationNode('embed:anchor:a1', 'source span', 'anchor'),
            {
                ...relationNode('embed:graph-fact:r1', 'Kai commands Hazel', 'graph-fact'),
                metadata: {
                    sourceType: 'graphFact',
                    graphRelationFamily: 'authority',
                    graphColorKind: 'authority',
                },
            },
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'r1:source', sourceId: 'embed:graph-fact:r1', targetId: 'embed:entity:kai', type: 'source', confidence: 0.91 },
            { id: 'r1:target', sourceId: 'embed:graph-fact:r1', targetId: 'embed:entity:hazel', type: 'target', confidence: 0.88 },
            { id: 'r1:evidence', sourceId: 'embed:graph-fact:r1', targetId: 'embed:anchor:a1', type: 'evidence', confidence: 0.82 },
        ];

        const scene = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'single' }));
        const sceneIds = new Set(scene.nodes.map((node) => node.entity.id));
        const control = scene.relationControls?.[0];

        expect(sceneIds.has('embed:graph-fact:r1')).toBe(false);
        expect(control?.id).toBe('embed:graph-fact:r1');
        expect(control?.family).toBe('authority');
        expect(control?.sourceNodeIds).toEqual(['embed:entity:kai']);
        expect(control?.targetNodeIds).toEqual(['embed:entity:hazel']);
        expect(control?.evidenceNodeIds).toEqual(['embed:anchor:a1']);
        expect(scene.links.some((link) =>
            scene.nodes[link.source].entity.id === 'embed:entity:kai'
            && scene.nodes[link.target].entity.id === 'embed:entity:hazel'
            && link.metadata?.['relationControlId'] === 'embed:graph-fact:r1',
        )).toBe(true);

        const packed = galaxySceneToV2(scene, 'embeddings');
        expect(packed.relationControls?.[0]?.id).toBe('embed:graph-fact:r1');
    });

    it('pins structural hierarchy edges when noisy relation edges fill the render queue first', () => {
        const nodes = Array.from({ length: 220 }, (_, index) => ({
            id: index === 0 ? 'embed:note:root' : `embed:chunk:${index}`,
            label: index === 0 ? 'Document root' : `Chunk ${index}`,
            kind: index === 0 ? 'note' : 'chunk',
            totalMentions: 1,
            atlasX: stable(index, 0),
            atlasY: stable(index, 1),
            atlasZ: stable(index, 2),
            metadata: { sourceType: index === 0 ? 'note' : 'chunk', graphKind: index === 0 ? 'note' : 'chunk' },
        } satisfies GalaxyRenderableNode));
        const noisyEdges: GalaxyInputEdge[] = [];
        for (let left = 1; left < 80; left += 1) {
            for (let right = left + 1; right < 96; right += 1) {
                noisyEdges.push({ id: `noise:${left}:${right}`, sourceId: nodes[left].id, targetId: nodes[right].id, type: 'cooccurrence', confidence: 0.22 });
            }
        }
        const structuralEdges: GalaxyInputEdge[] = nodes.slice(1).map((node, index) => ({
            id: `spine:${index + 1}`,
            sourceId: nodes[0].id,
            targetId: node.id,
            type: 'note-chunk',
            confidence: 0.9,
        }));

        const scene = buildGalaxyScene(nodes, [...noisyEdges, ...structuralEdges], mergeGalaxySettings({ layoutMode: 'single' }));
        const renderedIds = new Set(scene.links.map((link) => link.id));

        expect(noisyEdges.length).toBeGreaterThan(900);
        expect(structuralEdges.every((edge) => renderedIds.has(edge.id))).toBe(true);
    });
});

describe('Graph galaxy canonical colors', () => {
    it('resolves entity node colors from Style Lab even when nodes carry stale HSL snapshots', () => {
        entityColorStore.setColor('LOCATION', '0 100% 50%');
        try {
            const scene = buildGalaxyScene([
                {
                    id: 'embed:anchor:baton-rouge',
                    label: 'Baton Rouge',
                    kind: 'anchor',
                    colorHsl: '200 75% 55%',
                    metadata: { entityKind: 'location' },
                },
            ], [], mergeGalaxySettings({ layoutMode: 'single' }));

            expect(scene.nodes[0].r).toBe(255);
            expect(scene.nodes[0].g).toBe(0);
            expect(scene.nodes[0].b).toBe(0);
        } finally {
            entityColorStore.reset();
        }
    });

    it('keeps NER provenance from overriding canonical entity-kind colors', () => {
        entityColorStore.setColor('NETWORK', '0 100% 50%');
        try {
            const node: GalaxyRenderableNode = {
                id: 'network:joint-chiefs',
                label: 'Joint Chiefs',
                kind: 'NETWORK',
                colorHsl: '0 0% 80%',
                metadata: { sourceSystem: 'dynamic-ner' },
            };

            expect(resolveGalaxyNodeColorHsl(node)).toBe('0 100% 50%');
        } finally {
            entityColorStore.reset();
        }
    });

    it('resolves embedding target family colors from graph metadata before stale snapshots', () => {
        entityColorStore.setColor('ITEM', '0 100% 50%');
        try {
            const scene = buildGalaxyScene([
                {
                    id: 'embed:entity:phantom-work',
                    label: 'Phantom work',
                    kind: 'entity',
                    colorHsl: '282 70% 62%',
                    metadata: {
                        graphRebuildEmbeddingTarget: true,
                        graphColorKind: 'item',
                        graphKind: 'item',
                    },
                },
            ], [], mergeGalaxySettings({ layoutMode: 'transitManifold' }));

            expect(scene.nodes[0].r).toBe(255);
            expect(scene.nodes[0].g).toBe(0);
            expect(scene.nodes[0].b).toBe(0);
        } finally {
            entityColorStore.reset();
        }
    });

    it('keeps graph node colors from being overridden by contextual entity kinds', () => {
        entityColorStore.setColor('CHARACTER', '0 100% 50%');
        entityColorStore.setGraphNodeColor('eventNode', '120 100% 50%');
        entityColorStore.setGraphNodeColor('cooccurrence', '240 100% 50%');
        try {
            const scene = buildGalaxyScene([
                {
                    id: 'embed:event:e1',
                    label: 'Kai enters',
                    kind: 'event',
                    metadata: {
                        entityKind: 'CHARACTER',
                        graphColorKind: 'event',
                        graphKind: 'event',
                        graphRebuildEmbeddingTarget: true,
                    },
                },
                { id: 'embed:entity:kai', label: 'Kai', kind: 'entity', metadata: { sourceType: 'entity' } },
                { id: 'embed:entity:hazel', label: 'Hazel', kind: 'entity', metadata: { sourceType: 'entity' } },
                {
                    id: 'embed:graph-fact:co1',
                    label: 'Kai co_occurs_with Hazel',
                    kind: 'graph-fact',
                    metadata: {
                        entityKind: 'CHARACTER',
                        graphColorKind: 'cooccurrence',
                        graphRelationFamily: 'cooccurrence',
                        graphKind: 'graph-fact',
                        graphRebuildEmbeddingTarget: true,
                    },
                },
            ], [
                { id: 'co1:source', sourceId: 'embed:graph-fact:co1', targetId: 'embed:entity:kai', type: 'source', confidence: 0.8 },
                { id: 'co1:target', sourceId: 'embed:graph-fact:co1', targetId: 'embed:entity:hazel', type: 'target', confidence: 0.8 },
            ], mergeGalaxySettings({ layoutMode: 'transitManifold' }));

            expect(scene.nodes.find((node) => node.entity.id === 'embed:event:e1')).toMatchObject({ r: 0, g: 255, b: 0 });
            expect(scene.nodes.find((node) => node.entity.id === 'embed:graph-fact:co1')).toBeUndefined();
            expect(scene.relationControls?.find((control) => control.id === 'embed:graph-fact:co1')).toMatchObject({ r: 0, g: 0, b: 255 });
        } finally {
            entityColorStore.reset();
        }
    });

    it('keeps named state/context colors distinct from the entity they describe', () => {
        entityColorStore.setColor('CHARACTER', '0 100% 50%');
        entityColorStore.setGraphNodeColor('decisionState', '88 100% 50%');
        entityColorStore.setGraphNodeColor('rankStatus', '246 100% 50%');
        try {
            const decision: GalaxyRenderableNode = {
                id: 'embed:memory:m1',
                label: 'decision_state',
                kind: 'decision-state',
                metadata: {
                    sourceType: 'memoryState',
                    entityKind: 'CHARACTER',
                    graphKind: 'decision-state',
                    graphColorKind: 'decision-state',
                    graphMemoryStateKind: 'decisionState',
                    graphRebuildEmbeddingTarget: true,
                },
            };
            const rank: GalaxyRenderableNode = {
                id: 'embed:memory:m2',
                label: 'rank_or_status',
                kind: 'rank-status',
                metadata: {
                    sourceType: 'memoryState',
                    entityKind: 'CHARACTER',
                    graphKind: 'rank-status',
                    graphColorKind: 'rank-or-status',
                    graphMemoryStateKind: 'rankStatus',
                    graphRebuildEmbeddingTarget: true,
                },
            };

            expect(resolveGalaxyNodeColorHsl(decision)).toBe('88 100% 50%');
            expect(resolveGalaxyNodeColorHsl(rank)).toBe('246 100% 50%');
        } finally {
            entityColorStore.reset();
        }
    });

    it('uses relation-family styles for co-occurrence edges without requiring co-occurrence nodes', () => {
        entityColorStore.setColor('CHARACTER', '0 100% 50%');
        entityColorStore.setGraphNodeColor('cooccurrence', '240 100% 50%');
        try {
            const scene = buildGalaxyScene([
                { id: 'embed:entity:kai', label: 'Kai', kind: 'entity', metadata: { entityKind: 'CHARACTER' } },
                { id: 'embed:entity:hazel', label: 'Hazel', kind: 'entity', metadata: { entityKind: 'CHARACTER' } },
            ], [
                { id: 'co-edge', sourceId: 'embed:entity:kai', targetId: 'embed:entity:hazel', type: 'co_occurs_with', confidence: 0.68 },
            ], mergeGalaxySettings({ layoutMode: 'hybridSpace' }));

            const v2 = galaxySceneToV2(scene, 'embeddings');

            expect([...v2.edgeColors.slice(0, 6)]).toEqual([0, 0, 1, 0, 0, 1]);
        } finally {
            entityColorStore.reset();
        }
    });
});

describe('Graph galaxy hybrid hierarchy', () => {
    it('keeps Hybrid as the same shell while promoting broad documents inward from concrete evidence', () => {
        const scene = buildGalaxyScene([
            hybridNode('doc-root', 'Red Mesa', 'doc', 'note', 1, 0.1, 0, { lane: 'document', specificity: 0.24, ambiguity: 0.3, level: 0 }),
            hybridNode('chunk-leaf', 'Claimant mark', 'leaf', 'chunk', 1, 0.1, 0, { lane: 'document', specificity: 0.93, ambiguity: 0.02, level: 4 }),
        ], [], mergeGalaxySettings({ layoutMode: 'hybridSpace' }));
        const doc = scene.nodes.find((node) => node.entity.id === 'doc-root')!;
        const chunk = scene.nodes.find((node) => node.entity.id === 'chunk-leaf')!;

        expect(scene.layoutMode).toBe('hybridSpace');
        expect(hybridRadiusOf(doc)).toBeLessThan(hybridRadiusOf(chunk) - 0.2);
        expect(hybridRadiusOf(chunk)).toBeGreaterThan(0.5);
        expect(hybridRadiusOf(chunk)).toBeLessThan(0.72);
        expect(doc.hybridShell).toMatchObject({
            mode: 'hybridShell',
            geometryVersion: 'hybrid_shell_anatomy_v1',
            lane: 'document',
            level: 0,
        });
        expect(doc.hybridShellPoint?.radius).toBeCloseTo(hybridRadiusOf(doc), 5);
        expect(chunk.hybridShellPoint?.radius).toBeCloseTo(hybridRadiusOf(chunk), 5);
        expect(chunk.hybridRenderPoint).toEqual(chunk.hybridShellPoint);
        expect(chunk.hybridShell?.sourceSignals).toContain('productLaneKind=document');
        expect(chunk.entity.metadata?.['hybridShell']).toMatchObject({ lane: 'document' });
    });

    it('gives temporal and causal facts typed directions without leaving the Hybrid lane', () => {
        const scene = buildGalaxyScene([
            hybridNode('time-1', 'Before the tower pull', 'event', 'event', 1, 0, 0, { lane: 'temporal', specificity: 0.78, ambiguity: 0.04, phase: 0.25, level: 2 }),
            hybridNode('cause-1', 'Signal causes recall', 'event', 'event', 0, 0, 1, { lane: 'causal', specificity: 0.74, ambiguity: 0.04, phase: 0.5, level: 3 }),
        ], [{ id: 'causal-link', sourceId: 'time-1', targetId: 'cause-1', type: 'causal', confidence: 0.9 }], mergeGalaxySettings({ layoutMode: 'hybridSpace' }));
        const temporal = scene.nodes.find((node) => node.entity.id === 'time-1')!;
        const causal = scene.nodes.find((node) => node.entity.id === 'cause-1')!;

        expect(scene.layoutMode).toBe('hybridSpace');
        expect(Math.abs(temporal.y / Math.hypot(temporal.x, temporal.y, temporal.z))).toBeLessThan(0.28);
        expect(causal.x).toBeGreaterThan(0.35);
        expect(scene.links[0].alpha).toBeGreaterThan(0.1);
    });

    it('wires Busemann commitment signatures into the Hybrid interior', () => {
        const scene = buildGalaxyScene([
            {
                id: 'bundle-approval',
                label: 'Kai approves Hazel',
                kind: 'concept',
                totalMentions: 2,
                atlasX: 1,
                atlasY: 0,
                atlasZ: 0,
                metadata: {
                    sourceType: 'concept',
                    graphColorKind: 'approval',
                    graphRelationFamily: 'approval',
                    busemannSignature: {
                        family: 'RelationFamily',
                        topPrototypeId: 'relation:approval',
                        topScore: -1.2,
                        topProbability: 0.86,
                        secondPrototypeId: 'relation:transfer',
                        secondScore: -0.1,
                        secondProbability: 0.14,
                        margin: 1.1,
                        entropy: 0.18,
                        ambiguityScore: 0.18,
                        classificationConfidence: 0.82,
                        promotionReady: true,
                        radialStrength: 0.88,
                        topKScores: [
                            { prototypeId: 'relation:approval', family: 'RelationFamily', score: -1.2, probability: 0.86 },
                            { prototypeId: 'relation:transfer', family: 'RelationFamily', score: -0.1, probability: 0.14 },
                        ],
                    },
                },
            },
        ], [], mergeGalaxySettings({ layoutMode: 'hybridSpace', hybridHorospheresVisible: true }));
        const bundle = scene.nodes[0] as typeof scene.nodes[number] & {
            __hybridInterior?: { topPrototypeId: string; promotionReady: boolean };
        };

        expect(scene.layoutMode).toBe('hybridSpace');
        expect(bundle.__hybridInterior).toMatchObject({
            topPrototypeId: 'relation:approval',
            promotionReady: true,
        });
        expect(bundle.hybridShell).toMatchObject({ lane: 'relationship' });
        expect(bundle.hybridShellPoint).toBeDefined();
        expect(bundle.hybridCommitment).toMatchObject({
            mode: 'busemannCommitment',
            topPrototypeId: 'relation:approval',
            source: 'frontendCommitment',
        });
        expect(bundle.hybridCommitmentPoint?.radius).toBeCloseTo(hybridRadiusOf(bundle), 5);
        expect(bundle.hybridRenderPoint).toEqual(bundle.hybridCommitmentPoint);
        expect(hybridRadiusOf(bundle)).toBeLessThan(0.95);
        expect(scene.busemannHorospheres?.some((spec) => spec.prototypeId === 'relation:approval')).toBe(true);
        const v2 = galaxySceneToV2(scene, 'embeddings');
        const receipt = v2.hybridReceipts?.find((item) => item.nodeId === 'bundle-approval');

        expect(v2.hybridShellPositions?.length).toBe(3);
        expect(v2.hybridCommitmentPositions?.length).toBe(3);
        expect(v2.hybridCommitmentPositions?.[0]).toBeCloseTo(bundle.x, 5);
        expect(receipt).toMatchObject({
            nodeId: 'bundle-approval',
            shell: { lane: 'relationship' },
            commitment: {
                topPrototypeId: 'relation:approval',
                source: 'frontendCommitment',
            },
        });
    });

    it('keeps uncertain Busemann bundles near the interior instead of shell regions', () => {
        const ready = busemannBundleNode('ready-approval', 0.9, 0.08, 0.92, true);
        const uncertain = busemannBundleNode('uncertain-approval', 0.42, 0.88, 0.28, false);
        const scene = buildGalaxyScene([ready, uncertain], [], mergeGalaxySettings({ layoutMode: 'hybridSpace' }));
        const readyNode = scene.nodes.find((node) => node.entity.id === 'ready-approval')!;
        const uncertainNode = scene.nodes.find((node) => node.entity.id === 'uncertain-approval')!;

        expect(hybridRadiusOf(uncertainNode)).toBeLessThan(hybridRadiusOf(readyNode) - 0.2);
        expect(hybridRadiusOf(uncertainNode)).toBeLessThan(0.48);
        expect(scene.busemannHorospheres?.some((spec) => spec.prototypeId === 'relation:approval')).toBe(true);
    });
});

describe('Graph galaxy Siegel-Finsler layout', () => {
    it('orders directed structural targets along the Finsler flow', () => {
        const scene = buildGalaxyScene([
            siegelNode('doc', 'Document', 'note', 'document', 0, []),
            siegelNode('root', 'Document structure', 'structureRoot', 'document', 1, ['doc']),
            siegelNode('chunk', 'Chunk 1', 'chunk', 'document', 2, ['root']),
            siegelNode('entity', 'Kai', 'entity', 'entity', 3, ['chunk']),
        ], [
            { id: 'doc-root', sourceId: 'doc', targetId: 'root', type: 'target-parent', confidence: 0.9 },
            { id: 'root-chunk', sourceId: 'root', targetId: 'chunk', type: 'target-parent', confidence: 0.9 },
            { id: 'chunk-entity', sourceId: 'chunk', targetId: 'entity', type: 'target-parent', confidence: 0.9 },
        ], mergeGalaxySettings({ layoutMode: 'siegelFinsler' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(scene.layoutMode).toBe('siegelFinsler');
        expect(byId.get('root')!.x).toBeGreaterThan(byId.get('doc')!.x);
        expect(byId.get('chunk')!.x).toBeGreaterThan(byId.get('root')!.x);
        expect(byId.get('entity')!.x).toBeGreaterThan(byId.get('chunk')!.x);
        expect(scene.lorentzGuides?.some((guide) => guide.id.startsWith('siegel:lane:document'))).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'siegel:direction-axis')).toBe(true);
    });

    it('keeps graph rebuild hierarchy bands authoritative when Siegel metadata is stale', () => {
        const scene = buildGalaxyScene([
            siegelNode('doc', 'Document', 'note', 'document', 4, []),
            siegelNode('root', 'Identity root', 'structureRoot', 'document', 5, ['doc']),
            siegelNode('chunk', 'Chunk 1', 'chunk', 'document', 5, ['root']),
            siegelNode('event', 'Kai causes signal', 'event', 'causal', 1, ['chunk']),
            siegelNode('location', 'Tempest', 'LOCATION', 'entity', 1, ['chunk']),
            siegelNode('character', 'Kai', 'CHARACTER', 'entity', 5, ['chunk']),
            siegelNode('item', 'Ledger', 'ITEM', 'entity', 2, ['chunk']),
            siegelNode('state', 'decision_state', 'memoryState', 'memory_state', 5, ['character'], {
                metadata: {
                    entityKind: 'CHARACTER',
                    graphKind: 'decision-state',
                    graphColorKind: 'decision-state',
                },
            }),
            siegelNode('anchor', 'Kai mention', 'anchor', 'evidence', 1, ['chunk']),
        ], [
            { id: 'doc-root', sourceId: 'doc', targetId: 'root', type: 'target-parent', confidence: 0.9 },
            { id: 'root-chunk', sourceId: 'root', targetId: 'chunk', type: 'target-parent', confidence: 0.9 },
            { id: 'chunk-event', sourceId: 'chunk', targetId: 'event', type: 'event-chunk', confidence: 0.9 },
            { id: 'chunk-location', sourceId: 'chunk', targetId: 'location', type: 'chunk-entity', confidence: 0.9 },
            { id: 'chunk-character', sourceId: 'chunk', targetId: 'character', type: 'chunk-entity', confidence: 0.9 },
            { id: 'chunk-item', sourceId: 'chunk', targetId: 'item', type: 'chunk-entity', confidence: 0.9 },
            { id: 'character-state', sourceId: 'character', targetId: 'state', type: 'memory-entity', confidence: 0.9 },
            { id: 'chunk-anchor', sourceId: 'chunk', targetId: 'anchor', type: 'chunk-anchor', confidence: 0.84 },
        ], mergeGalaxySettings({ layoutMode: 'siegelFinsler' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(byId.get('root')!.x).toBeGreaterThan(byId.get('doc')!.x);
        expect(byId.get('chunk')!.x).toBeGreaterThan(byId.get('root')!.x);
        expect(byId.get('event')!.x).toBeGreaterThan(byId.get('chunk')!.x);
        expect(byId.get('location')!.x).toBeGreaterThan(byId.get('event')!.x);
        expect(byId.get('character')!.x).toBeGreaterThan(byId.get('location')!.x);
        expect(byId.get('item')!.x).toBeGreaterThan(byId.get('character')!.x);
        expect(byId.get('state')!.x).toBeGreaterThan(byId.get('item')!.x);
        expect(byId.get('anchor')!.x).toBeGreaterThan(byId.get('state')!.x);
        expect(byId.get('chunk')!.x - byId.get('root')!.x).toBeLessThan(0.62);
        expect(byId.get('event')!.x - byId.get('chunk')!.x).toBeLessThan(0.62);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'siegel:lane:event')).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'siegel:lane:location')).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'siegel:lane:character')).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'siegel:lane:stateContext')).toBe(true);
    });

    it('keeps entity and event bands thick on the y and z axes', () => {
        const scene = buildGalaxyScene([
            siegelNode('entity-a', 'Kai', 'entity', 'entity', 3, [], { phase: 0, matrixCells: [0.5, 0.08, 0.08, 0.4, 0.6, 0.5] }),
            siegelNode('entity-b', 'Hazel', 'entity', 'entity', 3, [], { phase: 0.25, matrixCells: [0.5, 0.34, 0.34, 0.4, 0.6, 0.5] }),
            siegelNode('entity-c', 'Rowan', 'entity', 'entity', 3, [], { phase: 0.5, matrixCells: [0.5, 0.66, 0.66, 0.4, 0.6, 0.5] }),
            siegelNode('entity-d', 'Cael', 'entity', 'entity', 3, [], { phase: 0.75, matrixCells: [0.5, 0.92, 0.92, 0.4, 0.6, 0.5] }),
            siegelNode('event-a', 'causal event', 'event', 'causal', 4, [], { phase: 0.1, matrixCells: [0.5, 0.1, 0.1, 0.4, 0.6, 0.5] }),
            siegelNode('event-b', 'causal event', 'event', 'causal', 4, [], { phase: 0.35, matrixCells: [0.5, 0.35, 0.35, 0.4, 0.6, 0.5] }),
            siegelNode('event-c', 'causal event', 'event', 'causal', 4, [], { phase: 0.6, matrixCells: [0.5, 0.65, 0.65, 0.4, 0.6, 0.5] }),
            siegelNode('event-d', 'causal event', 'event', 'causal', 4, [], { phase: 0.85, matrixCells: [0.5, 0.9, 0.9, 0.4, 0.6, 0.5] }),
        ], [], mergeGalaxySettings({ layoutMode: 'siegelFinsler' }));

        expect(yRange(scene.nodes.filter((node) => node.entity.id.startsWith('entity-')))).toBeGreaterThan(0.13);
        expect(yRange(scene.nodes.filter((node) => node.entity.id.startsWith('event-')))).toBeGreaterThan(0.13);
        expect(zRange(scene.nodes.filter((node) => node.entity.id.startsWith('entity-')))).toBeGreaterThan(0.3);
        expect(zRange(scene.nodes.filter((node) => node.entity.id.startsWith('event-')))).toBeGreaterThan(0.3);
    });

    it('keeps directed guides clean at the source and styled near the target', () => {
        const scene = buildGalaxyScene([
            siegelNode('chunk', 'Chunk 1', 'chunk', 'document', 2, []),
            siegelNode('entity', 'Kai', 'entity', 'entity', 4, ['chunk']),
        ], [
            { id: 'chunk-entity', sourceId: 'chunk', targetId: 'entity', type: 'target-parent', confidence: 0.9 },
        ], mergeGalaxySettings({ layoutMode: 'siegelFinsler' }));
        const guide = scene.lorentzGuides?.find((item) => item.id === 'siegel:directed:chunk-entity');

        expect(guide).toBeTruthy();
        const sourceDeviation = chordDeviation(guide!.positions3d, 1);
        const middleDeviation = chordDeviation(guide!.positions3d, Math.floor((guide!.positions3d.length / 3) * 0.5));
        const terminalDeviation = chordDeviation(guide!.positions3d, guide!.positions3d.length / 3 - 2);

        expect(sourceDeviation).toBeLessThan(terminalDeviation);
        expect(terminalDeviation).toBeGreaterThan(0.015);
        expect(terminalDeviation).toBeLessThan(0.075);
        expect(terminalDeviation).toBeLessThan(middleDeviation * 0.55);
    });
});

describe('Graph galaxy Transit manifold', () => {
    it('renders route stages, lane guides, and obstructions without Transit-local Hopf ribbons', () => {
        const scene = buildGalaxyScene([
            productNode('evidence', 'Chunk evidence', 'chunk', 'evidence', 'chunk'),
            productNode('entity', 'Kai', 'entity', 'identity', 'entity'),
            productNode('causal', 'Kai causes signal', 'event', 'causal', 'event'),
            productNode('dead-end', 'unsupported bridge', 'event', 'bridge', 'event', 'outlier'),
        ], [
            { id: 'evidence-entity', sourceId: 'evidence', targetId: 'entity', type: 'evidence_anchor', confidence: 0.9 },
            { id: 'entity-causal', sourceId: 'entity', targetId: 'causal', type: 'causal', confidence: 0.82 },
            { id: 'causal-dead-end', sourceId: 'causal', targetId: 'dead-end', type: 'embedding-bridge', confidence: 0.18 },
        ], mergeGalaxySettings({ layoutMode: 'transitManifold' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(scene.layoutMode).toBe('transitManifold');
        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(byId.get('evidence')!.x).toBeLessThan(byId.get('entity')!.x);
        expect(byId.get('entity')!.x).toBeLessThan(byId.get('causal')!.x);
        expect(byId.get('dead-end')).toBeTruthy();
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'transit:lane:evidence' && guide.guideKind === 'rootLane')).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'transit:route:causal-dead-end' && /unsupported|mismatch|missing/i.test(guide.treeKind))).toBe(true);
    });
});

function stable(index: number, salt: number): number {
    return (((index * 37 + salt * 17) % 101) / 50) - 1;
}

function relationNode(id: string, label: string, kind: string): GalaxyRenderableNode {
    return {
        id,
        label,
        kind,
        totalMentions: 1,
        atlasX: stable(id.length, 0),
        atlasY: stable(id.length, 1),
        atlasZ: stable(id.length, 2),
        metadata: { sourceType: kind },
    };
}

function hybridRadiusOf(node: { x: number; y: number; z: number }): number {
    return Math.hypot(node.x, node.y, node.z) / 2.32;
}

function chordDeviation(buffer: Float32Array, vertex: number): number {
    const last = buffer.length - 3;
    const ax = buffer[0], ay = buffer[1], az = buffer[2];
    const bx = buffer[last], by = buffer[last + 1], bz = buffer[last + 2];
    const px = buffer[vertex * 3], py = buffer[vertex * 3 + 1], pz = buffer[vertex * 3 + 2];
    const dx = bx - ax, dy = by - ay, dz = bz - az;
    const lengthSq = Math.max(0.000001, dx * dx + dy * dy + dz * dz);
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / lengthSq));
    const qx = ax + dx * t, qy = ay + dy * t, qz = az + dz * t;
    return Math.hypot(px - qx, py - qy, pz - qz);
}

function zRange(nodes: Array<{ z: number }>): number {
    const zs = nodes.map((node) => node.z);
    return Math.max(...zs) - Math.min(...zs);
}

function yRange(nodes: Array<{ y: number }>): number {
    const ys = nodes.map((node) => node.y);
    return Math.max(...ys) - Math.min(...ys);
}

function hybridNode(
    id: string,
    label: string,
    sourceType: string,
    kind: string,
    atlasX: number,
    atlasY: number,
    atlasZ: number,
    hierarchy: { lane: string; specificity: number; ambiguity: number; phase?: number; level: number },
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind,
        totalMentions: 1,
        atlasX,
        atlasY,
        atlasZ,
        metadata: {
            sourceType,
            productLaneKind: hierarchy.lane,
            graphKind: kind,
            graphRelationFamily: hierarchy.lane === 'temporal' || hierarchy.lane === 'causal' ? hierarchy.lane : undefined,
            lorentz: {
                dominantLane: hierarchy.lane,
                specificity: hierarchy.specificity,
                ambiguity: hierarchy.ambiguity,
                capPhase: hierarchy.phase ?? 0,
                level: hierarchy.level,
            },
        },
    };
}

function busemannBundleNode(
    id: string,
    confidence: number,
    entropy: number,
    radialStrength: number,
    promotionReady: boolean,
): GalaxyRenderableNode {
    return {
        id,
        label: id,
        kind: 'concept',
        totalMentions: 1,
        atlasX: 1,
        atlasY: 0,
        atlasZ: 0,
        metadata: {
            sourceType: 'concept',
            graphColorKind: 'approval',
            graphRelationFamily: 'approval',
            busemannSignature: {
                family: 'RelationFamily',
                topPrototypeId: 'relation:approval',
                topScore: -1,
                topProbability: confidence,
                secondPrototypeId: 'relation:transfer',
                secondScore: -0.2,
                secondProbability: 1 - confidence,
                margin: Math.max(0, confidence - (1 - confidence)),
                entropy,
                ambiguityScore: entropy,
                classificationConfidence: confidence,
                promotionReady,
                radialStrength,
                topKScores: [
                    { prototypeId: 'relation:approval', family: 'RelationFamily', score: -1, probability: confidence },
                    { prototypeId: 'relation:transfer', family: 'RelationFamily', score: -0.2, probability: 1 - confidence },
                ],
            },
        },
    };
}

function siegelNode(
    id: string,
    label: string,
    kind: string,
    lane: string,
    depth: number,
    parentIds: string[],
    options: { phase?: number; matrixCells?: number[]; metadata?: Record<string, unknown> } = {},
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind,
        totalMentions: 1,
        metadata: {
            sourceType: kind,
            graphKind: kind,
            signalParentIds: parentIds,
            ...options.metadata,
            siegel: {
                lane,
                role: depth <= 1 ? 'root' : 'child',
                depth,
                confidence: 0.9,
                phase: options.phase,
                matrixCells: options.matrixCells || [0.5, 0.5, 0.5, 0.4, 0.6, 0.5],
                parentIds,
            },
        },
    };
}

function productNode(
    id: string,
    label: string,
    kind: string,
    lane: string,
    sourceType: string,
    role = 'core',
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind,
        totalMentions: 1,
        metadata: {
            sourceType,
            productLaneKind: lane,
            productRegionRole: role,
            graphKind: kind,
            graphRelationFamily: lane === 'causal' || lane === 'temporal' ? lane : undefined,
            product: {
                dominantLane: lane,
                region: {
                    laneKind: lane,
                    role,
                    clusterId: `chart:${lane}`,
                    outlierScore: role === 'outlier' ? 0.82 : 0.08,
                    hubScore: role === 'core' ? 0.72 : 0.22,
                },
                fiber: { phase: lane.length * 0.37 },
                lanes: { laneWeights: { [lane]: 0.92 } },
            },
        },
    };
}
