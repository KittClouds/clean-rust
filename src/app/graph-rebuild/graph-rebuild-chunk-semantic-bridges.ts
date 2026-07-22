import type {
    GraphRebuildChunkSemanticBridge,
    GraphRebuildChunkSemanticBridgeType,
} from './graph-rebuild-snapshot';
import {
    GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
    GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT,
    GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
} from './graph-rebuild-snapshot';

const BRIDGE_TYPE_ORDER: GraphRebuildChunkSemanticBridgeType[] = [
    'setup_payoff',
    'cause_effect',
    'evidence_reframe',
    'relationship_delta',
    'state_delta',
    'route_continuity',
    'motif_echo',
    'topic_continuation',
];

export function chunkSemanticBridgeTypeRank(type: GraphRebuildChunkSemanticBridgeType): number {
    const index = BRIDGE_TYPE_ORDER.indexOf(type);
    return index < 0 ? BRIDGE_TYPE_ORDER.length : index;
}

export function assertChunkSemanticBridgeCandidateOnly(
    bridges: GraphRebuildChunkSemanticBridge[],
): GraphRebuildChunkSemanticBridge[] {
    for (const bridge of bridges) {
        if (bridge.schemaVersion !== GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION) {
            throw new Error(`Chunk semantic bridge ${bridge.id} must use ${GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION}.`);
        }
        if (bridge.status !== 'candidate') {
            throw new Error(`Chunk semantic bridge ${bridge.id} must stay candidate-only.`);
        }
        if (bridge.commitPolicy !== GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY) {
            throw new Error(`Chunk semantic bridge ${bridge.id} cannot request a topology commit.`);
        }
        if (!bridge.rationale.includes(GRAPH_REBUILD_CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT)) {
            throw new Error(`Chunk semantic bridge ${bridge.id} is missing the no-topology-commit guard.`);
        }
    }
    return bridges;
}
