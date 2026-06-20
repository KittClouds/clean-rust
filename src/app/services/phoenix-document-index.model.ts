export interface PhoenixDocumentIndexReadRequest {
    documentId: string;
    noteId?: string | null;
    title?: string | null;
    text: string;
    maxUnits?: number;
    maxRoutes?: number;
    maxRouteTargets?: number;
    maxFamilyRoutes?: number;
    maxFamilyTargets?: number;
    maxLabelChars?: number;
}

export interface PhoenixDocumentIndexShardRef {
    schemaVersion: number;
    documentId: string;
    noteId?: string | null;
    contentHash: string;
    byteLen: number;
    unitCount: number;
}

export interface PhoenixDocumentIndexReadReceipt {
    bounded: boolean;
    mmap: boolean;
    cacheReused: boolean;
    textBytes: number;
    shardBytes: number;
    unitCount: number;
    unitsReturned: number;
    unitsTruncated: number;
    routeCount: number;
    routesReturned: number;
    routesTruncated: number;
    familyRouteCount: number;
    familyRoutesReturned: number;
    familyRoutesTruncated: number;
    familyTargetCount: number;
    familyTargetsReturned: number;
    familyTargetsTruncated: number;
    maxUnits: number;
    maxRoutes: number;
    maxRouteTargets: number;
    maxFamilyRoutes: number;
    maxFamilyTargets: number;
    maxLabelChars: number;
    buildMs: number;
    persistMs: number;
    mmapMs: number;
    readMs: number;
}

export interface PhoenixDocumentIndexUnit {
    index: number;
    kind: 'document' | 'section' | 'subsection' | 'paragraph';
    depth: number;
    parentIndex?: number | null;
    start: number;
    end: number;
    ordinal: number;
    label: string;
}

export interface PhoenixDocumentOutlineTarget {
    index: number;
    kind: PhoenixDocumentIndexUnit['kind'];
    depth: number;
    label: string;
}

export interface PhoenixDocumentOutlineRoute {
    paragraphIndex: number;
    start: number;
    end: number;
    targets: PhoenixDocumentOutlineTarget[];
}

export type PhoenixDocumentFamilyName = 'entityState' | 'timeline' | 'tension';

export type PhoenixDocumentFamilyTargetKind =
    | 'entityMention'
    | 'stateCue'
    | 'tensionCue'
    | 'date'
    | 'temporalCue';

export interface PhoenixDocumentFamilyTarget {
    kind: PhoenixDocumentFamilyTargetKind;
    start: number;
    end: number;
    label: string;
}

export interface PhoenixDocumentFamilyRoute {
    paragraphIndex: number;
    start: number;
    end: number;
    targets: PhoenixDocumentFamilyTarget[];
}

export interface PhoenixDocumentFamilyRoutes {
    family: PhoenixDocumentFamilyName;
    routeCount: number;
    routesReturned: number;
    routesTruncated: number;
    targetCount: number;
    targetsReturned: number;
    targetsTruncated: number;
    routes: PhoenixDocumentFamilyRoute[];
}

export interface PhoenixDocumentIndexReadResponse {
    schemaVersion: 'phoenix-document-index-read/v1';
    source: 'tauri-editor-mmap';
    reference: PhoenixDocumentIndexShardRef;
    receipt: PhoenixDocumentIndexReadReceipt;
    units: PhoenixDocumentIndexUnit[];
    outlineRoutes: PhoenixDocumentOutlineRoute[];
    families: PhoenixDocumentFamilyRoutes[];
}
