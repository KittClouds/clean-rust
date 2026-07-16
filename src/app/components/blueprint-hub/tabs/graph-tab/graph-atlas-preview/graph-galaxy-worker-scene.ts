import type { GalaxyNode, GalaxyRenderableNode, GalaxyScene } from './graph-galaxy-engine';

export type CompactGalaxyNode = Omit<GalaxyNode, 'entity'> & { entityId: string };
export type CompactGalaxyScene = Omit<GalaxyScene, 'nodes'> & { nodes: CompactGalaxyNode[] };

export function compactGalaxySceneForTransfer(scene: GalaxyScene): CompactGalaxyScene {
    return {
        ...scene,
        nodes: scene.nodes.map(({ entity, ...node }) => ({ ...node, entityId: entity.id })),
    };
}

export function hydrateGalaxySceneFromTransfer(
    scene: CompactGalaxyScene,
    entities: GalaxyRenderableNode[],
): GalaxyScene {
    const entityById = new Map(entities.map((entity) => [entity.id, entity] as const));
    return {
        ...scene,
        nodes: scene.nodes.map(({ entityId, ...node }) => {
            const entity = entityById.get(entityId);
            if (!entity) throw new Error(`Worker scene references unknown entity: ${entityId}`);
            return { ...node, entity };
        }),
    };
}
