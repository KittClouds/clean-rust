export const GALAXY_LOCAL_REGION_QUERY_NODE_LIMIT = 4_096;
export const GALAXY_LOCAL_PATH_NODE_LIMIT = 4_096;
export const GALAXY_LOCAL_PATH_EDGE_LIMIT = 16_384;
export const GALAXY_LOCAL_PATH_VISIT_LIMIT = 4_096;
export const GALAXY_PATH_OVERLAY_EDGE_LIMIT = 512;

export interface GalaxyInteractionAuthority {
    generationId: string;
    manifoldId: string;
    authorityReceipt: string;
}

export interface GalaxyInteractionRect {
    left: number;
    top: number;
    right: number;
    bottom: number;
    width: number;
    height: number;
}

export interface GalaxyRegionQueryRequest extends GalaxyInteractionAuthority {
    token: number;
    rect: GalaxyInteractionRect;
    viewProjection: Float32Array;
    maxResults: number;
}

export interface GalaxyRegionQueryResult extends GalaxyInteractionAuthority {
    token: number;
    nodeIndices: Uint32Array;
}

export interface GalaxyPathQueryRequest extends GalaxyInteractionAuthority {
    token: number;
    sourceNodeId: string;
    targetNodeId: string;
    maxVisited: number;
    maxPathEdges: number;
}

export interface GalaxyPathOverlay extends GalaxyInteractionAuthority {
    token: number;
    sourceNodeId: string;
    targetNodeId: string;
    nodeIndices: Uint32Array;
    edgeIndices: Uint32Array;
    found: boolean;
}

export interface GalaxyNativeInteractionQueryPort {
    queryRegion(request: GalaxyRegionQueryRequest, signal: AbortSignal): Promise<GalaxyRegionQueryResult>;
    queryPath(request: GalaxyPathQueryRequest, signal: AbortSignal): Promise<GalaxyPathOverlay>;
}
