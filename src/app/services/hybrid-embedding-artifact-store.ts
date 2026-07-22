import type { StoreScopedDocument } from './phoenix-store.service';
import type {
    HybridEmbeddingSpaceContract,
    HybridEmbeddingValidationReceipt,
    ManifoldProjectionSource,
} from './manifold-atlas.types';

export const HYBRID_EMBEDDING_ARTIFACT_NAMESPACE = 'phoenix-hybrid-embedding-artifact';
export const HYBRID_EMBEDDING_ARTIFACT_DOCUMENT_KEY = 'latest';

export interface HybridEmbeddingArtifactScopeInput {
    mode?: string;
    noteId?: string;
    noteIds?: string[];
    narrativeId?: string;
    folderId?: string;
    folderPath?: string;
    worldId?: string;
}

export interface HybridEmbeddingArtifactScope {
    scopeId: string;
    narrativeId: string;
    mode?: string;
    noteId?: string;
    noteIds?: string[];
    folderId?: string;
    folderPath?: string;
    worldId?: string;
}

export interface HybridEmbeddingPersistedArtifact {
    schemaVersion: 'phoenix-hybrid-embedding-artifact/v1';
    persistedAt: number;
    source: 'native' | 'fallback';
    scope: HybridEmbeddingArtifactScope;
    sourceLabel: string;
    projectionSource?: ManifoldProjectionSource | string;
    nodeCount: number;
    edgeCount: number;
    embeddingSpace: HybridEmbeddingSpaceContract;
    validationReceipt: HybridEmbeddingValidationReceipt;
    candidateOnly: true;
    committedTopologyWrites: 0;
}

export interface HybridEmbeddingArtifactPayloadInput {
    nodes: readonly unknown[];
    edges: readonly unknown[];
    sourceLabel: string;
    projectionSource?: ManifoldProjectionSource | string;
}

const HASH_OFFSET = 0x811c9dc5;
const HASH_PRIME = 0x01000193;

export function hybridEmbeddingArtifactScope(scope?: HybridEmbeddingArtifactScopeInput | null): HybridEmbeddingArtifactScope {
    const noteIds = normalizedNoteIds(scope?.noteIds);
    const scopeId = scope?.folderId
        ? `folder:${scope.folderId}`
        : scope?.folderPath
          ? `folder-path:${hashText(scope.folderPath)}`
          : scope?.noteId
            ? `note:${scope.noteId}`
            : noteIds.length
              ? `notes:${hashText(noteIds.join('\u001f'))}`
              : scope?.narrativeId
                ? `narrative:${scope.narrativeId}`
                : scope?.worldId
                  ? `world:${scope.worldId}`
                  : 'global';
    return {
        scopeId,
        narrativeId: scope?.narrativeId || (scope?.mode === 'narrative' ? scopeId.replace(/^narrative:/, '') : ''),
        mode: scope?.mode,
        noteId: scope?.noteId,
        noteIds,
        folderId: scope?.folderId,
        folderPath: scope?.folderPath,
        worldId: scope?.worldId,
    };
}

export function buildHybridEmbeddingPersistedArtifact(
    scope: HybridEmbeddingArtifactScope,
    embeddingSpace: HybridEmbeddingSpaceContract,
    payload: HybridEmbeddingArtifactPayloadInput,
    source: 'native' | 'fallback',
    persistedAt = Date.now(),
): HybridEmbeddingPersistedArtifact {
    return {
        schemaVersion: 'phoenix-hybrid-embedding-artifact/v1',
        persistedAt,
        source,
        scope,
        sourceLabel: payload.sourceLabel,
        projectionSource: payload.projectionSource,
        nodeCount: payload.nodes.length,
        edgeCount: payload.edges.length,
        embeddingSpace,
        validationReceipt: embeddingSpace.validationReceipt,
        candidateOnly: true,
        committedTopologyWrites: 0,
    };
}

export function hybridEmbeddingArtifactToScopedDocument(
    artifact: HybridEmbeddingPersistedArtifact,
    existing?: StoreScopedDocument | null,
): StoreScopedDocument {
    const createdAt = existing?.createdAt || artifact.persistedAt;
    return {
        id: `${HYBRID_EMBEDDING_ARTIFACT_NAMESPACE}:${artifact.scope.scopeId}:${HYBRID_EMBEDDING_ARTIFACT_DOCUMENT_KEY}`,
        scopeFolderId: artifact.scope.scopeId,
        narrativeId: artifact.scope.narrativeId,
        namespace: HYBRID_EMBEDDING_ARTIFACT_NAMESPACE,
        documentKey: HYBRID_EMBEDDING_ARTIFACT_DOCUMENT_KEY,
        payload: JSON.stringify(artifact),
        createdAt,
        updatedAt: artifact.persistedAt,
    };
}

export function scopedDocumentToHybridEmbeddingArtifact(
    document: StoreScopedDocument | null | undefined,
): HybridEmbeddingPersistedArtifact | null {
    if (!document) return null;
    try {
        const parsed = JSON.parse(document.payload) as HybridEmbeddingPersistedArtifact;
        if (parsed?.schemaVersion !== 'phoenix-hybrid-embedding-artifact/v1') return null;
        if (!parsed.candidateOnly || parsed.committedTopologyWrites !== 0) return null;
        if (!parsed.embeddingSpace?.candidateOnly || parsed.embeddingSpace.committedTopologyWrites !== 0) return null;
        return parsed;
    } catch {
        return null;
    }
}

export function comparableHybridEmbeddingReceipt(
    current: HybridEmbeddingSpaceContract,
    previous: HybridEmbeddingPersistedArtifact | null | undefined,
): HybridEmbeddingValidationReceipt | null {
    if (!previous) return null;
    const prior = previous.embeddingSpace;
    if (prior.schemaVersion !== current.schemaVersion) return null;
    if (prior.authority !== 'hybrid' || current.authority !== 'hybrid') return null;
    if (prior.modelId !== current.modelId) return null;
    if (prior.modelVersion !== current.modelVersion) return null;
    if (prior.dimensions !== current.dimensions) return null;
    if (prior.executionProvider !== current.executionProvider) return null;
    if (prior.normalization !== current.normalization || prior.metric !== current.metric) return null;
    if (prior.neighborhood.method !== current.neighborhood.method) return null;
    if (prior.neighborhood.k !== current.neighborhood.k) return null;
    if (prior.neighborhood.minSimilarity !== current.neighborhood.minSimilarity) return null;
    return previous.validationReceipt || prior.validationReceipt || null;
}

function normalizedNoteIds(noteIds: readonly string[] | undefined): string[] {
    return Array.from(new Set((noteIds || []).filter((id) => typeof id === 'string' && id.length > 0))).sort();
}

function hashText(value: string): string {
    let hash = HASH_OFFSET;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, HASH_PRIME) >>> 0;
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}
