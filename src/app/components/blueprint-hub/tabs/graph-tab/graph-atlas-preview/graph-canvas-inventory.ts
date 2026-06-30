import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { recordGraphCollapseRenderedInventory } from '../../../../../graph-rebuild/graph-collapse-trace';
import type { GraphInventory } from './graph-atlas-preview.component';
import { buildGraphPacketRowAdapter } from './graph-packet-row-adapter';

const EMPTY_PACKET_LABEL = 'rust atlas packet missing';

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
    const rows = buildGraphPacketRowAdapter(packet, snapshot.embeddingTargets || []);
    const inventory: GraphInventory = {
        nodes: rows.graphNodes,
        edges: rows.graphEdges,
        kindCounts: rows.kindCounts,
        sourceLabel: rows.sourceLabel,
    };
    recordGraphCollapseRenderedInventory(snapshot, inventory.nodes.length, inventory.edges.length, inventory.kindCounts);
    return inventory;
}
