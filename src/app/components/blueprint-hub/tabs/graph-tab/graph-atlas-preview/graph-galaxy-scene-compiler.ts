import type { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import type { PhoenixGalaxySceneRequest } from '../../../../../services/phoenix-galaxy-scene.model';
import {
    buildGalaxyScene,
    hasRelationControlNodes,
    hslToRgb,
    resolveGalaxyNodeColorHsl,
    type GalaxyInputEdge,
    type GalaxyRenderableNode,
    type GalaxyRenderSettings,
    type GalaxyScene,
} from './graph-galaxy-engine';
import { graphGalaxyRuntimeMeter } from './graph-galaxy-runtime-meter';

let warnedNativeFallback = false;

export async function compileGalaxyScene(
    backend: PhoenixBackendService,
    entities: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
): Promise<GalaxyScene> {
    const hasGalaxyMetadata = entities.some((entity) => Boolean(entity.metadata?.galaxyId));
    const hasAtlasLayout = entities.some((entity) =>
        Number.isFinite(entity.atlasX) && Number.isFinite(entity.atlasY) && Number.isFinite(entity.atlasZ),
    );
    const hasRelationControls = hasRelationControlNodes(entities);
    if (backend.target !== 'native' || hasGalaxyMetadata || hasAtlasLayout || hasRelationControls || settings.layoutMode !== 'single') {
        graphGalaxyRuntimeMeter.recordCompilerSource('local');
        return buildGalaxyScene(entities, edges, settings);
    }
    try {
        const scene = await backend.compileGalaxyScene({
            entities: entities.map((entity) => ({
                id: entity.id,
                label: entity.label,
                kind: entity.kind,
                totalMentions: entity.totalMentions,
                atlasX: entity.atlasX,
                atlasY: entity.atlasY,
                atlasZ: entity.atlasZ,
                colorHsl: resolveGalaxyNodeColorHsl(entity),
            })),
            edges,
            settings: {
                edgeLength: settings.edgeLength,
                nodeDistance: settings.nodeDistance,
            },
        } satisfies PhoenixGalaxySceneRequest);
        graphGalaxyRuntimeMeter.recordCompilerSource('native');
        return {
            nodes: scene.nodes.map((node) => {
                const source = entities.find((entity) => entity.id === node.entity.id);
                const color = hslToRgb(source ? resolveGalaxyNodeColorHsl(source) : resolveGalaxyNodeColorHsl(node.entity));
                return {
                    ...node,
                    ...color,
                    sx: 0,
                    sy: 0,
                    depth: 0,
                    galaxyOpacity: 1,
                };
            }),
            links: scene.links.map((link) => ({ ...link })),
            layoutMode: 'single',
            groups: [],
        };
    } catch (error) {
        if (!warnedNativeFallback) {
            warnedNativeFallback = true;
            console.warn('[GraphGalaxyScene] Native scene compiler unavailable; using local scene builder.', error);
        }
        graphGalaxyRuntimeMeter.recordCompilerSource('fallback');
        return buildGalaxyScene(entities, edges, settings);
    }
}
