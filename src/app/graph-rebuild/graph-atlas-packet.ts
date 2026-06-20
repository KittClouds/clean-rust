import type { GraphRebuildScopeKind } from './graph-rebuild-snapshot';

export const GRAPH_ATLAS_FAMILIES = [
    'registry',
    'entity',
    'structure',
    'fact',
    'discourse',
    'review',
    'evidence',
    'temporal',
    'causal',
    'memory',
    'hypergraph',
    'unknown',
] as const;

export type GraphAtlasFamily = (typeof GRAPH_ATLAS_FAMILIES)[number];

export type GraphAtlasObjectStatus =
    | 'accepted'
    | 'proposed'
    | 'review'
    | 'rejected'
    | 'deferred'
    | 'ledgerOnly'
    | 'compiledToGraph'
    | 'muted'
    | 'promotedToAnchor'
    | 'unknown';

export const GRAPH_ATLAS_PACKET_AUTHORITY = 'rust-atlas-packet' as const;
export const GRAPH_ATLAS_IDENTITY_AUTHORITY = 'registry-entities-and-accepted-anchors' as const;
export const GRAPH_ATLAS_BUILDER_ROLE = 'native-atlas-packet-authority' as const;
export const GRAPH_ATLAS_VECTOR_CONTRACTS = ['vectors-missing', 'model-vectors'] as const;

export type GraphAtlasPacketAuthority = typeof GRAPH_ATLAS_PACKET_AUTHORITY;
export type GraphAtlasIdentityAuthority = typeof GRAPH_ATLAS_IDENTITY_AUTHORITY;
export type GraphAtlasBuilderRole = typeof GRAPH_ATLAS_BUILDER_ROLE;
export type GraphAtlasVectorContract = (typeof GRAPH_ATLAS_VECTOR_CONTRACTS)[number];

export interface GraphAtlasSourceContract {
    authority: GraphAtlasPacketAuthority;
    identityAuthority: GraphAtlasIdentityAuthority;
    vectorContract: GraphAtlasVectorContract;
    tsGraphBuilderRole: GraphAtlasBuilderRole;
}

export interface GraphAtlasObject {
    id: string;
    family: GraphAtlasFamily;
    status?: GraphAtlasObjectStatus;
    kind: string;
    label: string;
    styleKey?: string;
    lane?: string;
    structuralRole?: string;
    documentUnitKind?: string;
    stateContextKind?: string;
    registryEntityId?: string;
    noteIds: string[];
    chunkIds: string[];
    anchorIds: string[];
    evidenceIds: string[];
    sourceIds: string[];
    targetIds: string[];
}

export interface GraphAtlasManifoldTarget {
    id: string;
    objectId: string;
    family: GraphAtlasFamily;
    admission: 'candidate' | 'admitted' | 'deferred' | 'rejected';
    vectorStatus: 'missing' | 'modelVector' | 'external';
    coordinateSource: string;
    status: GraphAtlasObjectStatus;
    kind: string;
    label: string;
    entityKind?: string;
    styleKey?: string;
    lane?: string;
    structuralRole?: string;
    documentUnitKind?: string;
    stateContextKind?: string;
    sourceId: string;
    registryEntityId?: string;
    noteId?: string;
    chunkId?: string;
    evidenceIds: string[];
    parentIds?: string[];
}

export interface GraphAtlasPacket {
    schemaVersion: 'phoenix-atlas-packet/v1';
    snapshotId: string;
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    builtAt: number;
    sourceContract: GraphAtlasSourceContract;
    objects: GraphAtlasObject[];
    manifoldTargets: GraphAtlasManifoldTarget[];
    counters: {
        objects: number;
        manifoldTargets: number;
        registryEntities: number;
        evidenceAnchors: number;
        modelVectors: number;
        families: Array<{ family: GraphAtlasFamily; count: number }>;
    };
}
