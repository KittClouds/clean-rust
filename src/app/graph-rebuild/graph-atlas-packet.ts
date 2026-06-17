import type { GraphRebuildScopeKind } from './graph-rebuild-snapshot';

export type GraphAtlasFamily =
    | 'registry'
    | 'entity'
    | 'structure'
    | 'fact'
    | 'discourse'
    | 'review'
    | 'evidence'
    | 'temporal'
    | 'causal'
    | 'memory'
    | 'hypergraph'
    | 'unknown';

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

export interface GraphAtlasSourceContract {
    authority: string;
    identityAuthority: string;
    vectorContract: string;
    tsGraphBuilderRole: string;
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
