import type { AtlasManifoldMode } from './manifold-atlas.types';

export type PhoenixGraphSceneLayoutMode =
    | 'single'
    | 'multiGalaxy'
    | 'hybridSpace'
    | 'hopfProjection'
    | 'lorentzTree'
    | 'transitManifold'
    | 'productManifold'
    | 'siegelFinsler';

export type PhoenixGraphSceneSourceMode = 'entities' | 'graph' | 'embeddings';

export interface PhoenixGraphScenePacketSettings {
    edgeLength?: number;
    nodeDistance?: number;
}

export interface PhoenixGraphScenePacketNodeInput {
    id: string;
    label: string;
    kind: string;
    sourceType: string;
    vector: number[];
    baseVector?: [number, number, number] | null;
    totalMentions?: number | null;
    hierarchyHint?: PhoenixGraphScenePacketHierarchyHint | null;
}

export interface PhoenixGraphScenePacketEdgeInput {
    id: string;
    sourceId: string;
    targetId: string;
    edgeType: string;
    confidence: number;
}

export interface PhoenixGraphScenePacketHierarchyMembership {
    treeId: string;
    nodeId: string;
    parentNodeId?: string | null;
    depth: number;
    localRank: number;
    pathKey: string;
    role: string;
    confidence: number;
    primary: boolean;
}

export interface PhoenixGraphScenePacketHierarchyHint {
    nodeId: string;
    primaryTreeId: string;
    capId: string;
    parentNodeId?: string | null;
    shellRadius: number;
    hierarchyLevel: number;
    role: string;
    confidence: number;
    memberships: PhoenixGraphScenePacketHierarchyMembership[];
}

export interface PhoenixGraphScenePacketRequest {
    source?: 'inline' | 'manifoldSnapshot' | 'scopedSnapshot';
    manifold?: AtlasManifoldMode;
    layoutMode?: PhoenixGraphSceneLayoutMode;
    sourceMode?: PhoenixGraphSceneSourceMode;
    scope?: Record<string, unknown>;
    limit?: number;
    settings?: PhoenixGraphScenePacketSettings;
    nodes?: PhoenixGraphScenePacketNodeInput[];
    edges?: PhoenixGraphScenePacketEdgeInput[];
}

export interface PhoenixGraphScenePacketCounters {
    inputNodes: number;
    inputEdges: number;
    renderedNodes: number;
    renderedEdges: number;
    droppedEdges: number;
    bufferBytes: number;
}

export interface PhoenixGraphScenePacket {
    version: 'graph-scene-packet/v1';
    source: string;
    sourceLabel: string;
    manifold: string;
    layoutMode: PhoenixGraphSceneLayoutMode;
    sourceMode: PhoenixGraphSceneSourceMode;
    counters: PhoenixGraphScenePacketCounters;
    ids: string[];
    labels: string[];
    kinds: string[];
    groupIds: string[];
    positions3d: string;
    positions2d: string;
    radii: string;
    colors: string;
    edgeIds: string[];
    edgePairs: string;
    edgeColors: string;
    edgeAlpha: string;
    edgeKinds: string;
    hierarchyShellRadii?: string;
    hierarchyShellRanks?: string;
    hierarchyHints?: PhoenixGraphScenePacketHierarchyHint[];
}
