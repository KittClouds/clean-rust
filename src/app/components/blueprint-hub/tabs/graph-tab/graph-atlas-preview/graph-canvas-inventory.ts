import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { recordGraphCollapseRenderedInventory } from '../../../../../graph-rebuild/graph-collapse-trace';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import type { GraphInventory } from './graph-atlas-preview.component';
import { graphSnapshotRenderIdentity } from '../graph-render-identity';
import { buildEpisodeProjectionCanvasEdges } from './graph-episode-projection-canvas';
import { buildGraphPacketRowAdapter } from './graph-packet-row-adapter';

const EMPTY_PACKET_LABEL = 'rust atlas packet missing';
const MAX_CACHED_INVENTORIES = 4;
const graphCanvasInventoryCache = new Map<string, GraphInventory>();

export function releaseGraphCanvasInventoryGeneration(identity: string): boolean {
    return identity ? graphCanvasInventoryCache.delete(identity) : false;
}

entityColorStore.subscribe(() => graphCanvasInventoryCache.clear());

/**
 * Compatibility boundary: TS no longer builds graph data. Graph mode only
 * adapts the Rust-owned Atlas packet into renderable rows and filters by
 * family/status metadata.
 */
export function buildGraphCanvasInventory(snapshot: GraphRebuildSnapshot | null): GraphInventory {
    const packet = snapshot?.atlasPacket;
    if (!packet) {
        return { nodes: [], edges: [], kindCounts: [], sourceLabel: EMPTY_PACKET_LABEL };
    }
    const identity = graphSnapshotRenderIdentity(snapshot);
    const cached = identity ? graphCanvasInventoryCache.get(identity) : undefined;
    if (cached) {
        graphCanvasInventoryCache.delete(identity);
        graphCanvasInventoryCache.set(identity, cached);
        return cached;
    }
    const rows = buildGraphPacketRowAdapter(packet, snapshot.embeddingTargets || []);
    const episodeEdges = buildEpisodeProjectionCanvasEdges(snapshot, rows.graphNodes);
    const inventory: GraphInventory = {
        nodes: rows.graphNodes,
        edges: [...rows.graphEdges, ...episodeEdges],
        kindCounts: rows.kindCounts,
        sourceLabel: rows.sourceLabel,
    };
    if (identity) {
        graphCanvasInventoryCache.set(identity, inventory);
        while (graphCanvasInventoryCache.size > MAX_CACHED_INVENTORIES) {
            graphCanvasInventoryCache.delete(graphCanvasInventoryCache.keys().next().value!);
        }
    }
    recordGraphCollapseRenderedInventory(snapshot, inventory.nodes.length, inventory.edges.length, inventory.kindCounts);
    return inventory;
}
