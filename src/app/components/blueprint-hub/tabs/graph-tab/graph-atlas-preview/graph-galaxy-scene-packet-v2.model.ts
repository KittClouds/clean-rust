import type { GalaxyLayoutMode } from './graph-galaxy-engine';
import type { GalaxySceneSourceMode } from './graph-galaxy-scene-v2';

export const GALAXY_SCENE_PACKET_V2_SCHEMA = 'phoenix-galaxy-scene-packet/v2' as const;
export const GALAXY_SCENE_PACKET_V2_NODE_PALETTE_PAGE = 'manifold/node-palette-slots-u8' as const;

export type GalaxyScenePacketV2PageDomain = 'shared' | 'manifold' | 'guide' | 'detail';
export type GalaxyScenePacketV2LoadPolicy = 'resident' | 'on-demand';
export type GalaxyScenePacketV2Encoding =
    | 'u8'
    | 'u32-le'
    | 'f32-le'
    | 'f64-le'
    | 'rgba8'
    | 'utf8'
    | 'utf8-json';

export interface GalaxyScenePacketV2PageManifest {
    id: string;
    domain: GalaxyScenePacketV2PageDomain;
    loadPolicy: GalaxyScenePacketV2LoadPolicy;
    encoding: GalaxyScenePacketV2Encoding;
    elementCount: number;
    byteLength: number;
    generationId: string;
    tileId: string;
    lod: number;
    contentHash: string;
    authorityReceipt: string;
}

export interface GalaxyScenePacketV2StringRange {
    start: number;
    count: number;
}

export interface GalaxyScenePacketV2Manifest {
    schemaVersion: typeof GALAXY_SCENE_PACKET_V2_SCHEMA;
    generationId: string;
    tileId: string;
    lod: number;
    authorityReceipt: string;
    layoutMode: GalaxyLayoutMode;
    sourceMode: GalaxySceneSourceMode;
    identityEncoding: 'fnv1a32-dual-u64';
    positionEncoding: 'float32-tile-local';
    guideEncoding: 'binary-guides-v1';
    tileOrigin: readonly [number, number, number];
    nodeCount: number;
    edgeCount: number;
    nodeCollisionCount: number;
    edgeCollisionCount: number;
    stringRanges: {
        nodeIds: GalaxyScenePacketV2StringRange;
        nodeLabels: GalaxyScenePacketV2StringRange;
        nodeKinds: GalaxyScenePacketV2StringRange;
        nodeGroupIds: GalaxyScenePacketV2StringRange;
        nodeHopfBaseIds: GalaxyScenePacketV2StringRange;
        nodeHopfCellIds?: GalaxyScenePacketV2StringRange;
        nodeHopfFiberIds?: GalaxyScenePacketV2StringRange;
        nodeHopfLaneIds?: GalaxyScenePacketV2StringRange;
        edgeIds: GalaxyScenePacketV2StringRange;
        edgeTypes: GalaxyScenePacketV2StringRange;
    };
    pages: readonly GalaxyScenePacketV2PageManifest[];
    contentHash: string;
}

export interface GalaxyScenePacketV2 {
    manifest: GalaxyScenePacketV2Manifest;
    pages: Record<string, ArrayBuffer>;
}

declare const verifiedGalaxyScenePacketV2: unique symbol;

/** Packet whose manifest and hot pages crossed the V2 trust boundary once. */
export type VerifiedGalaxyScenePacketV2 = GalaxyScenePacketV2 & {
    readonly [verifiedGalaxyScenePacketV2]: true;
};

export interface GalaxyScenePacketV2Context {
    generationId: string;
    authorityReceipt: string;
    tileId?: string;
    lod?: number;
}

export interface GalaxyScenePacketV2CollisionPages {
    records: Uint32Array;
    members: Uint32Array;
    collisionCount: number;
}
