import { describe, expect, it } from 'vitest';

import { buildGalaxyScene, mergeGalaxySettings, type GalaxyInputEdge, type GalaxyRenderableNode } from './graph-galaxy-engine';

const productNodes: GalaxyRenderableNode[] = [
    productNode('kai', 'Kai', 0.28, 0, 'identity', null),
    productNode('echo', 'Echo', 0.64, 1, 'causal', 'kai'),
    productNode('ruby', 'Ruby', 0.82, 1, 'evidence', 'kai'),
];

const productEdges: GalaxyInputEdge[] = [
    { id: 'identity:kai:echo', sourceId: 'kai', targetId: 'echo', type: 'lorentz-tree:identity', confidence: 0.9 },
    { id: 'causal:kai:ruby', sourceId: 'kai', targetId: 'ruby', type: 'lorentz-tree:causal', confidence: 0.85 },
];

describe('Product manifold galaxy visualization data', () => {
    it('uses Product traversal positions while adding route guide data', () => {
        const scene = buildGalaxyScene(productNodes, productEdges, mergeGalaxySettings({ layoutMode: 'productManifold' }));

        expect(scene.layoutMode).toBe('productManifold');
        expect(scene.lorentzGuides?.length).toBe(5);
        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(scene.nodes.every((node) => Math.hypot(node.x, node.y, node.z) <= 2.4)).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'product:lane:identity')).toBe(true);
        expect(scene.lorentzGuides?.some((guide) => guide.id === 'product:route:identity:kai:echo')).toBe(true);
        expect(new Set(scene.lorentzGuides?.map((guide) => guide.guideKind))).toEqual(new Set(['rootLane', 'membership']));
        expect(scene.lorentzGuides?.some((guide) => guide.id.startsWith('lorentz:'))).toBe(false);
    });

    it('derives Product route guides from evidence context without rendering extra nodes', () => {
        const nodes: GalaxyRenderableNode[] = [
            graphTargetNode('embed:entity:kai', 'Kai', 'entity', 'kai'),
            graphTargetNode('embed:anchor:a1', 'Kai in Baton Rouge', 'anchor', 'a1', 'kai'),
            graphTargetNode('embed:event:e1', 'Kai opens the Red Mesa board', 'event', 'e1', 'kai'),
            graphTargetNode('embed:graph-fact:r1', 'Kai trusts Cael', 'graph-fact', 'r1', 'kai'),
            graphTargetNode('embed:memory:m1', 'Kai remains cautious', 'memory-state', 'm1', 'kai'),
            graphTargetNode('embed:causalFact:c1', 'Red Mesa pulse changes route', 'causal-fact', 'c1', 'kai'),
            graphTargetNode('embed:graph-fact:co1', 'Kai co_occurs_with Cael', 'graph-fact', 'co1', 'kai'),
            graphTargetNode('embed:graph-fact:ob1', 'Kai observes Cael', 'graph-fact', 'ob1', 'kai'),
            graphTargetNode('embed:graph-fact:cm1', 'Kai comments on Cael', 'graph-fact', 'cm1', 'kai'),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'anchor-entity:a1', sourceId: 'embed:anchor:a1', targetId: 'embed:entity:kai', type: 'anchor-entity', confidence: 0.92 },
            { id: 'event-entity:e1:kai', sourceId: 'embed:event:e1', targetId: 'embed:entity:kai', type: 'event-entity', confidence: 0.82 },
            { id: 'fact-source:r1', sourceId: 'embed:graph-fact:r1', targetId: 'embed:entity:kai', type: 'trusts', confidence: 0.78 },
            { id: 'memory-entity:m1', sourceId: 'embed:memory:m1', targetId: 'embed:entity:kai', type: 'memory-entity', confidence: 0.72 },
            { id: 'causal-source:c1', sourceId: 'embed:causalFact:c1', targetId: 'embed:event:e1', type: 'causes', confidence: 0.8 },
            { id: 'fact-source:co1', sourceId: 'embed:graph-fact:co1', targetId: 'embed:entity:kai', type: 'co_occurs_with', confidence: 0.62 },
            { id: 'fact-source:ob1', sourceId: 'embed:graph-fact:ob1', targetId: 'embed:entity:kai', type: 'observes', confidence: 0.64 },
            { id: 'fact-source:cm1', sourceId: 'embed:graph-fact:cm1', targetId: 'embed:entity:kai', type: 'comments_on', confidence: 0.66 },
        ];

        const scene = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const relationGuides = scene.lorentzGuides?.filter((guide) => guide.id.startsWith('product:route:')) ?? [];
        const relationKinds = new Set(relationGuides.map((guide) => guide.treeKind));

        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(scene.nodes.some((node) => node.entity.id.startsWith('product:context:'))).toBe(false);
        expect(relationGuides.length).toBe(8);
        expect(relationGuides.some((guide) => guide.id === 'product:route:anchor-entity:a1')).toBe(true);
        expect(relationGuides.some((guide) => guide.id === 'product:route:event-entity:e1:kai')).toBe(true);
        expect(relationKinds.has('documentStructure')).toBe(true);
        expect(relationKinds.has('event')).toBe(true);
        expect(relationKinds.has('relationship')).toBe(true);
        expect(relationKinds.has('evidence')).toBe(true);
        expect(relationKinds.has('causal')).toBe(true);
        expect(relationKinds.has('cooccurrence')).toBe(true);
        expect(relationKinds.has('observation')).toBe(true);
        expect(relationKinds.has('communication')).toBe(true);
        expect(relationGuides.every((guide) => guide.positions3d.length > 0)).toBe(true);
    });

    it('anchors Product routes on medoids without promoting local Hopf clutter', () => {
        const nodes: GalaxyRenderableNode[] = [
            clusteredTargetNode('embed:entity:kai', 'Kai', 'entity', 'embed:entity:kai', 'core'),
            clusteredTargetNode('embed:entity:rowan', 'Rowan', 'entity', 'embed:entity:kai', 'boundary'),
            clusteredTargetNode('embed:graph-fact:trust', 'Kai trusts Rowan', 'graph-fact', 'embed:entity:kai', 'boundary'),
            clusteredTargetNode('embed:graph-fact:co', 'Kai co_occurs_with Rowan', 'graph-fact', 'embed:entity:kai', 'boundary', 'weak co_occurs_with evidence'),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'fact-source:trust', sourceId: 'embed:graph-fact:trust', targetId: 'embed:entity:kai', type: 'trusts', confidence: 0.78 },
            { id: 'fact-source:co', sourceId: 'embed:graph-fact:co', targetId: 'embed:entity:kai', type: 'co_occurs_with', confidence: 0.56 },
        ];

        const scene = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));
        const trustRoute = scene.lorentzGuides?.find((guide) => guide.id === 'product:route:fact-source:trust');
        const coRoute = scene.lorentzGuides?.find((guide) => guide.id === 'product:route:fact-source:co');

        expect(scene.hopfRibbons?.length ?? 0).toBe(0);
        expect(byId.get('embed:entity:kai')?.radius || 0).toBeGreaterThan(byId.get('embed:entity:rowan')?.radius || 0);
        expect(trustRoute?.nodeIds).toEqual(['embed:graph-fact:trust', 'embed:entity:kai']);
        expect(coRoute?.treeKind).toBe('cooccurrence');
    });

    it('uses embedding topology as a selectable lens without merging nodes', () => {
        const nodes: GalaxyRenderableNode[] = [
            topologyNode('embed:entity:kai', 'Kai', 'embedding-cluster:0', 'embed:entity:kai', 0.1, 0.9),
            topologyNode('embed:entity:rowan', 'Rowan', 'embedding-cluster:0', 'embed:entity:kai', 0.2, 0.4),
            topologyNode('embed:entity:rook', 'Rook', 'embedding-cluster:1', 'embed:entity:rook', 0.84, 0.2),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'embedding-backbone:kai:rowan', sourceId: 'embed:entity:kai', targetId: 'embed:entity:rowan', type: 'embedding-backbone', confidence: 0.84 },
            { id: 'embedding-bridge:rowan:rook', sourceId: 'embed:entity:rowan', targetId: 'embed:entity:rook', type: 'embedding-bridge', confidence: 0.72 },
        ];

        const medoids = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'medoids' }));
        const outliers = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'outliers' }));
        const backbone = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'backbone' }));
        const regions = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'regions' }));
        const lanes = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ embeddingTopologyMode: 'lanes' }));

        expect(medoids.nodes.find((node) => node.entity.id === 'embed:entity:kai')?.radius)
            .toBeGreaterThan(medoids.nodes.find((node) => node.entity.id === 'embed:entity:rowan')?.radius || 0);
        expect(outliers.nodes.find((node) => node.entity.id === 'embed:entity:rook')?.radius)
            .toBeGreaterThan(outliers.nodes.find((node) => node.entity.id === 'embed:entity:rowan')?.radius || 0);
        expect(backbone.links.find((edge) => edge.type === 'embedding-backbone')?.alpha)
            .toBeGreaterThan(backbone.links.find((edge) => edge.type === 'embedding-bridge')?.alpha || 0);
        expect(regions.nodes.find((node) => node.entity.id === 'embed:entity:rook')?.radius)
            .toBeGreaterThan(regions.nodes.find((node) => node.entity.id === 'embed:entity:rowan')?.radius || 0);
        expect(lanes.nodes.some((node) => node.r !== medoids.nodes.find((other) => other.entity.id === node.entity.id)?.r)).toBe(true);
        expect(new Set(backbone.nodes.map((node) => node.entity.id)).size).toBe(3);
    });

    it('turns Product topology regions into layout pressure', () => {
        const nodes: GalaxyRenderableNode[] = [
            topologyNode('embed:entity:kai', 'Kai', 'embedding-cluster:0', 'embed:entity:kai', 0.1, 0.9),
            topologyNode('embed:entity:rowan', 'Rowan', 'embedding-cluster:0', 'embed:entity:kai', 0.2, 0.4),
            topologyNode('embed:entity:rook', 'Rook', 'embedding-cluster:1', 'embed:entity:rook', 0.84, 0.2),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'embedding-backbone:kai:rowan', sourceId: 'embed:entity:kai', targetId: 'embed:entity:rowan', type: 'embedding-backbone', confidence: 0.84 },
            { id: 'embedding-bridge:rowan:rook', sourceId: 'embed:entity:rowan', targetId: 'embed:entity:rook', type: 'embedding-bridge', confidence: 0.72 },
        ];

        const baseline = buildGalaxyScene(nodes.map(stripTopology), edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const scene = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const core = scene.nodes.find((node) => node.entity.id === 'embed:entity:kai')!;
        const outlier = scene.nodes.find((node) => node.entity.id === 'embed:entity:rook')!;
        const baselineOutlier = baseline.nodes.find((node) => node.entity.id === 'embed:entity:rook')!;
        const backboneEdge = scene.links.find((edge) => edge.type === 'embedding-backbone')!;
        const bridgeEdge = scene.links.find((edge) => edge.type === 'embedding-bridge')!;

        expect(Math.hypot(outlier.x, outlier.y, outlier.z)).toBeGreaterThan(Math.hypot(baselineOutlier.x, baselineOutlier.y, baselineOutlier.z));
        expect(outlier.radius).toBeLessThan(core.radius);
        expect(backboneEdge.curve).toBeLessThan(bridgeEdge.curve);
        expect(backboneEdge.alpha).toBeGreaterThan(bridgeEdge.alpha * 0.7);
    });

    it('lets hierarchy caps own Product basins before embedding clusters', () => {
        const nodes: GalaxyRenderableNode[] = [
            hierarchyProductNode('embed:note:1', 'Doc', 'note', 'document:1', 0),
            hierarchyProductNode('embed:root:1', 'Identity root', 'structure-root', 'document:1:root:identity', 1, 'embed:note:1'),
            hierarchyProductNode('embed:chunk:1', 'Scene chunk', 'chunk', 'document:1:chunk:1', 2, 'embed:root:1'),
            hierarchyProductNode('embed:entity:kai', 'Kai', 'entity', 'identity:kai', 3, 'embed:chunk:1'),
            hierarchyProductNode('embed:fact:cause', 'causes_or_explains', 'causal-fact', 'event:1:causal', 5, 'embed:entity:kai'),
        ];

        const scene = buildGalaxyScene(nodes, [], mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));

        expect(byId.get('embed:note:1')!.x).toBeLessThan(byId.get('embed:root:1')!.x);
        expect(byId.get('embed:root:1')!.x).toBeLessThan(byId.get('embed:chunk:1')!.x);
        expect(byId.get('embed:chunk:1')!.x).toBeLessThan(byId.get('embed:entity:kai')!.x);
        expect(byId.get('embed:entity:kai')!.x).toBeLessThan(byId.get('embed:fact:cause')!.x);
    });

    it('clusters Product children in their owning entity regions', () => {
        const nodes: GalaxyRenderableNode[] = [
            ownedProductNode('embed:note:1', 'Doc', 'note', 'document:1', 0, '', 'document'),
            ownedProductNode('embed:chunk:1', 'Scene chunk', 'chunk', 'document:1:chunk:1', 2, '', 'document'),
            ownedProductNode('embed:entity:kai', 'Kai', 'entity', 'identity:kai', 3, 'kai', 'entity'),
            ownedProductNode('embed:entity:rowan', 'Rowan', 'entity', 'identity:rowan', 3, 'rowan', 'entity'),
            ownedProductNode('embed:anchor:kai', 'Kai mention', 'anchor', 'document:1:chunk:1:evidence', 4, 'kai', 'evidence'),
            ownedProductNode('embed:anchor:rowan', 'Rowan mention', 'anchor', 'document:1:chunk:1:evidence', 4, 'rowan', 'evidence'),
            ownedProductNode('embed:fact:kai', 'Kai trusts Rowan', 'graph-fact', 'document:1:chunk:1:facts:relationship', 4, '', 'relationship'),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'fact-source:kai', sourceId: 'embed:fact:kai', targetId: 'embed:entity:kai', type: 'fact-source', confidence: 0.88 },
        ];

        const scene = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));

        expect(sceneDistance(scene, 'embed:entity:kai', 'embed:anchor:kai')).toBeLessThan(sceneDistance(scene, 'embed:entity:rowan', 'embed:anchor:kai'));
        expect(sceneDistance(scene, 'embed:entity:rowan', 'embed:anchor:rowan')).toBeLessThan(sceneDistance(scene, 'embed:entity:kai', 'embed:anchor:rowan'));
        expect(sceneDistance(scene, 'embed:entity:kai', 'embed:fact:kai')).toBeLessThan(sceneDistance(scene, 'embed:entity:rowan', 'embed:fact:kai'));
    });

    it('keeps Product topology pressure separate from the Lorentz skeleton', () => {
        const nodes: GalaxyRenderableNode[] = [
            topologyNode('embed:entity:kai', 'Kai', 'embedding-cluster:0', 'embed:entity:kai', 0.1, 0.9),
            topologyNode('embed:entity:rowan', 'Rowan', 'embedding-cluster:0', 'embed:entity:kai', 0.2, 0.4),
            topologyNode('embed:entity:rook', 'Rook', 'embedding-cluster:1', 'embed:entity:rook', 0.84, 0.2),
        ];
        const edges: GalaxyInputEdge[] = [
            { id: 'embedding-backbone:kai:rowan', sourceId: 'embed:entity:kai', targetId: 'embed:entity:rowan', type: 'embedding-backbone', confidence: 0.84 },
            { id: 'embedding-bridge:rowan:rook', sourceId: 'embed:entity:rowan', targetId: 'embed:entity:rook', type: 'embedding-bridge', confidence: 0.72 },
        ];

        const lorentz = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'lorentzTree' }));
        const product = buildGalaxyScene(nodes, edges, mergeGalaxySettings({ layoutMode: 'productManifold' }));
        const productById = new Map(product.nodes.map((node) => [node.entity.id, node]));
        const maxDelta = Math.max(...lorentz.nodes.map((node) => {
            const other = productById.get(node.entity.id)!;
            return Math.hypot(node.x - other.x, node.y - other.y, node.z - other.z);
        }));

        expect(maxDelta).toBeGreaterThan(0.2);
        expect(product.hopfRibbons?.length ?? 0).toBe(0);
        expect(product.lorentzGuides?.some((guide) => guide.id.startsWith('product:lane:'))).toBe(true);
        expect(product.lorentzGuides?.some((guide) => guide.id.startsWith('product:route:'))).toBe(true);
        expect(product.lorentzGuides?.some((guide) => guide.id.startsWith('lorentz:root-lane:'))).toBe(false);
    });

    it('keeps Product routes close enough to read as traversal lanes', () => {
        const scene = productPhaseScene(0.18, 0.68);
        const route = scene.lorentzGuides?.find((guide) => guide.id === 'product:route:phase:identity:context');

        expect(route).toBeTruthy();
        expect((route?.positions3d.length || 0) / 6).toBeGreaterThan(12);
        expect(routeEnvelopeDeviation(route!.positions3d)).toBeLessThan(0.24);
    });

    it('uses Hopf phase agreement as Product layout pressure', () => {
        const aligned = productPhaseScene(0.18, 0.2);
        const mismatched = productPhaseScene(0.18, 0.68);
        const alignedDistance = sceneDistance(aligned, 'phase:identity', 'phase:context');
        const mismatchedDistance = sceneDistance(mismatched, 'phase:identity', 'phase:context');

        expect(alignedDistance).not.toBe(mismatchedDistance);
        expect(Math.abs(mismatched.links[0].curve)).toBeGreaterThan(Math.abs(aligned.links[0].curve));
        expect(mismatched.lorentzGuides?.[0]?.positions3d.length).toBeGreaterThan(0);
    });
});

function productPhaseScene(identityPhase: number, contextPhase: number): ReturnType<typeof buildGalaxyScene> {
    const nodes: GalaxyRenderableNode[] = [
        phaseNode('phase:identity', 'Kai identity', 'entity', identityPhase, 'core'),
        phaseNode('phase:context', 'Kai across context', 'evidence', contextPhase, 'bridge'),
    ];
    return buildGalaxyScene(nodes, [{
        id: 'phase:identity:context',
        sourceId: 'phase:identity',
        targetId: 'phase:context',
        type: 'embedding-bridge',
        confidence: 0.86,
    }], mergeGalaxySettings({ layoutMode: 'productManifold' }));
}

function sceneDistance(scene: ReturnType<typeof buildGalaxyScene>, leftId: string, rightId: string): number {
    const left = scene.nodes.find((node) => node.entity.id === leftId)!;
    const right = scene.nodes.find((node) => node.entity.id === rightId)!;
    return Math.hypot(left.x - right.x, left.y - right.y, left.z - right.z);
}

function routeEnvelopeDeviation(positions: Float32Array): number {
    const last = positions.length - 3;
    const ax = positions[0], ay = positions[1], az = positions[2];
    const bx = positions[last], by = positions[last + 1], bz = positions[last + 2];
    const dx = bx - ax, dy = by - ay, dz = bz - az;
    const chord = Math.max(0.000001, Math.hypot(dx, dy, dz));
    let maxDeviation = 0;
    for (let offset = 0; offset < positions.length; offset += 3) {
        const px = positions[offset] - ax;
        const py = positions[offset + 1] - ay;
        const pz = positions[offset + 2] - az;
        const t = Math.min(1, Math.max(0, (px * dx + py * dy + pz * dz) / (chord * chord)));
        const cx = ax + dx * t;
        const cy = ay + dy * t;
        const cz = az + dz * t;
        maxDeviation = Math.max(maxDeviation, Math.hypot(positions[offset] - cx, positions[offset + 1] - cy, positions[offset + 2] - cz));
    }
    return maxDeviation;
}

function productNode(
    id: string,
    label: string,
    radius: number,
    level: number,
    fiberKind: string,
    parentNodeId: string | null,
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: 'PRODUCT:NODE',
        totalMentions: 4,
        atlasX: radius,
        atlasY: radius * 0.2,
        atlasZ: radius * 0.35,
        metadata: {
            sourceType: 'product_node',
            hopf: { role: 'anchor', baseId: id, fiberKind, phase: radius },
            lorentz: {
                klein: [radius, radius * 0.2, radius * 0.35, 0],
                level,
                primaryTreeKind: fiberKind,
                memberships: [{
                    treeId: fiberKind,
                    treeKind: fiberKind,
                    parentNodeId,
                    level,
                    pathKey: parentNodeId ? `${fiberKind}/${parentNodeId}/${id}` : `${fiberKind}/${id}`,
                }],
            },
        },
    };
}

function phaseNode(id: string, label: string, lane: string, phase: number, role: string): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: 'entity',
        totalMentions: 3,
        metadata: {
            embeddingClusterId: 'embedding-cluster:identity-phase',
            embeddingMedoidTargetId: 'phase:identity',
            productRegionRole: role,
            productLaneKind: lane,
            product: {
                fiber: { phase },
                lanes: { laneWeights: { entity: lane === 'entity' ? 0.9 : 0.25, evidence: lane === 'evidence' ? 0.9 : 0.25 } },
            },
            hopf: { role: 'anchor', baseId: 'phase:kai', fiberKind: lane, phase },
        },
    };
}

function graphTargetNode(
    id: string,
    label: string,
    sourceType: string,
    sourceId: string,
    sourceEntityId?: string,
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: sourceType,
        totalMentions: 2,
        atlasX: sourceType === 'entity' ? 0.32 : 0.72,
        atlasY: sourceType === 'event' ? 0.28 : 0.12,
        atlasZ: sourceType === 'anchor' ? 0.44 : 0.18,
        metadata: {
            sourceType,
            sourceId,
            sourceEntityId,
            manifold: 'product',
            graphRebuildEmbeddingTarget: true,
            preview: `${sourceType} context for ${label}`,
            lorentz: {
                level: sourceType === 'entity' ? 0 : 1,
                memberships: [{
                    treeId: 'identity',
                    treeKind: 'identity',
                    parentNodeId: sourceType === 'entity' ? null : 'embed:entity:kai',
                    level: sourceType === 'entity' ? 0 : 1,
                    pathKey: `identity/${id}`,
                }],
            },
        },
    };
}

function topologyNode(
    id: string,
    label: string,
    clusterId: string,
    medoidTargetId: string,
    outlierScore: number,
    hubScore: number,
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: 'entity',
        totalMentions: 3,
        metadata: {
            embeddingClusterId: clusterId,
            embeddingMedoidTargetId: medoidTargetId,
            embeddingOutlierScore: outlierScore,
            embeddingHubScore: hubScore,
            productRegionRole: outlierScore >= 0.72 ? 'outlier' : id === medoidTargetId ? 'core' : 'boundary',
            productLaneKind: id.includes('rook') ? 'document' : 'entity',
            product: {
                lanes: {
                    laneWeights: {
                        semantic: 0.5,
                        document: id.includes('rook') ? 0.9 : 0.2,
                        relation: 0.2,
                        temporal: 0.1,
                        causal: 0.1,
                        evidence: 0.2,
                        entity: id.includes('rook') ? 0.2 : 0.8,
                    },
                },
            },
        },
    };
}

function hierarchyProductNode(id: string, label: string, sourceType: string, capId: string, level: number, parentNodeId = ''): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: sourceType,
        totalMentions: 2,
        metadata: {
            sourceType,
            embeddingClusterId: 'embedding-cluster:flat-type-island',
            productLaneKind: 'document',
            productTraversal: { routeStage: 6, lane: 'causal' },
            lorentz: {
                geometry: 'hierarchy_caps_v1',
                capId,
                level,
                parentNodeId,
                primaryTreeKind: 'document',
            },
        },
    };
}

function ownedProductNode(id: string, label: string, sourceType: string, capId: string, level: number, sourceEntityId: string, lane: string): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: sourceType,
        totalMentions: 2,
        metadata: {
            sourceType,
            sourceId: id.replace(/^embed:[^:]+:/, ''),
            sourceEntityId,
            embeddingClusterId: 'embedding-cluster:flat-owner-test',
            productLaneKind: lane,
            productTraversal: { routeStage: 6 },
            lorentz: {
                geometry: 'hierarchy_caps_v1',
                capId,
                level,
                primaryTreeKind: lane,
            },
        },
    };
}

function clusteredTargetNode(
    id: string,
    label: string,
    sourceType: string,
    medoidTargetId: string,
    role: string,
    preview = '',
): GalaxyRenderableNode {
    return {
        id,
        label,
        kind: sourceType,
        totalMentions: sourceType === 'entity' && id === medoidTargetId ? 3 : 1,
        metadata: {
            sourceType,
            embeddingClusterId: 'embedding-cluster:kai-context',
            embeddingMedoidTargetId: medoidTargetId,
            productRegionRole: role,
            productLaneKind: sourceType === 'entity' ? 'entity' : 'relation',
            preview,
        },
    };
}

function stripTopology(node: GalaxyRenderableNode): GalaxyRenderableNode {
    const metadata = { ...(node.metadata || {}) };
    delete metadata['embeddingClusterId'];
    delete metadata['embeddingMedoidTargetId'];
    delete metadata['embeddingOutlierScore'];
    delete metadata['embeddingHubScore'];
    delete metadata['productRegionRole'];
    delete metadata['productLaneKind'];
    delete metadata['product'];
    return { ...node, metadata };
}
