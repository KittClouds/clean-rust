import type { StoreScopedDocument } from '../services/phoenix-store.service';
import type {
    GraphIndexRunReceipt,
    GraphRebuildScopeKind,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

export const GRAPH_REBUILD_NAMESPACE = 'phoenix_graph_rebuild_v1';
export const SNAPSHOT_DOCUMENT_KEY = 'snapshot';
export const DIAGNOSTIC_SNAPSHOT_DOCUMENT_KEY = 'snapshot:diagnostic';
export const RECEIPT_DOCUMENT_KEY = 'receipt';
export const GRAPH_MODEL_V2_OVERGRAPH_DOCUMENT_KEY = 'graph-model-v2-overgraph';
const POST_PROCESS_CACHE_PREFIX = 'postprocess-cache';

export interface GraphRebuildPostProcessCache {
    schemaVersion: 'phoenix-graph-postprocess-cache/v1';
    scopeId: string;
    scopeKind?: GraphRebuildScopeKind;
    fingerprint: string;
    snapshot?: GraphRebuildSnapshot;
    snapshotId?: string;
    receipt?: GraphIndexRunReceipt;
    receiptId?: string;
    updatedAt: number;
}

export function graphIndexReceiptToScopedDocument(receipt: GraphIndexRunReceipt): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${receipt.scope.scopeId}:${RECEIPT_DOCUMENT_KEY}`,
        scopeFolderId: receipt.scope.scopeId,
        narrativeId: receipt.scope.kind === 'narrative' ? receipt.scope.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: RECEIPT_DOCUMENT_KEY,
        payload: JSON.stringify(receipt),
        createdAt: receipt.startedAt || now,
        updatedAt: now,
    };
}

export function scopedDocumentToGraphIndexReceipt(document: StoreScopedDocument): GraphIndexRunReceipt | null {
    try {
        const parsed = JSON.parse(document.payload) as GraphIndexRunReceipt;
        return parsed?.schemaVersion === 'phoenix-graph-index-run/v1' ? parsed : null;
    } catch {
        return null;
    }
}

export function postProcessCacheDocumentKey(fingerprint: string): string {
    return `${POST_PROCESS_CACHE_PREFIX}:${fingerprint}`;
}

export function postProcessCacheToScopedDocument(cache: GraphRebuildPostProcessCache): StoreScopedDocument {
    const now = Date.now();
    return {
        id: `${GRAPH_REBUILD_NAMESPACE}:${cache.scopeId}:${postProcessCacheDocumentKey(cache.fingerprint)}`,
        scopeFolderId: cache.scopeId,
        narrativeId: cache.scopeKind === 'narrative' ? cache.scopeId : '',
        namespace: GRAPH_REBUILD_NAMESPACE,
        documentKey: postProcessCacheDocumentKey(cache.fingerprint),
        payload: JSON.stringify(cache),
        createdAt: cache.updatedAt || now,
        updatedAt: now,
    };
}

export function scopedDocumentToPostProcessCache(document: StoreScopedDocument): GraphRebuildPostProcessCache | null {
    try {
        const parsed = JSON.parse(document.payload) as GraphRebuildPostProcessCache;
        return parsed?.schemaVersion === 'phoenix-graph-postprocess-cache/v1' ? parsed : null;
    } catch {
        return null;
    }
}
