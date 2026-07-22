import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import type { GraphRebuildReplayManifest } from './graph-rebuild-replay-contract';

export const GRAPH_FORCE_V2_CONTRACT_VERSION = 'phoenix-verified-force/v2' as const;
export const GRAPH_FORCE_V2_PATH_ID = 'native_verified_force_v2' as const;

export interface GraphForceRebuildV2ShadowRequest {
    contractVersion: typeof GRAPH_FORCE_V2_CONTRACT_VERSION;
    operation: 'force';
    sourceMode: 'scoped-note-store';
    scopeId: string;
    cohortId: string;
    scopeKind: GraphRebuildReplayManifest['scope']['kind'];
    dependencyIdentity: string;
    documents: Array<{
        noteId: string;
        sha256: string;
        jsCodeUnitChars: number;
        utf8Bytes: number;
        version: number | null;
        updatedAt: number | null;
    }>;
    model: {
        dynamicNerId: string;
        embeddingModelId: string;
        embeddingDimension: string;
        nliModelId: string;
    };
    expectedSnapshotId: string;
    expectedAuthorityHash: string;
    expectedManifestId: string | null;
}

export type GraphForceRebuildV2Request = Omit<GraphForceRebuildV2ShadowRequest, 'documents'> & {
    noteIds: string[];
};

export interface GraphForceRebuildV2Error {
    code: string;
    message: string;
    retryable: false;
}

export interface GraphForceRebuildV2ShadowResult {
    schemaVersion: 'phoenix-force-rebuild-v2-shadow-result/v1';
    contractVersion: typeof GRAPH_FORCE_V2_CONTRACT_VERSION;
    pathId: typeof GRAPH_FORCE_V2_PATH_ID;
    fallbackCount: 0;
    status: 'durable_verified' | 'rejected';
    scopeId: string;
    snapshotId: string;
    authorityHash: string;
    manifestId: string;
    runHandle: string;
    analysisSource: 'durable_verified' | 'none';
    analysisKernelMicros: number;
    verifiedSections: Array<{
        name: string;
        identity: string;
        rowCount: number;
        rawBytes: number;
        compressedBytes: number;
    }>;
    criticalResponseBytes: number;
    nativeCrossings: number;
    sourceBodyReads: number;
    sourceUtf8Bytes: number;
    transportedSourceBytes: number;
    sourceDocuments: GraphForceRebuildV2ShadowRequest['documents'];
    sourceVersionEnvelopeChanged: boolean;
    authorityPacket: GraphRebuildSnapshot | null;
    parentSpanId: string;
    spanId: string;
    error: GraphForceRebuildV2Error | null;
}

export interface GraphForceAuthorityPersistRequest {
    scopeId: string;
    snapshotId: string;
    authorityHash: string;
    manifestId: string;
    authorityPacket: GraphRebuildSnapshot;
}

export interface GraphForceAuthorityPersistReceipt {
    schemaVersion: 'phoenix-force-v2-authority-persist/v1';
    artifactId: string;
    rawBytes: number;
    compressedBytes: number;
    encoded: boolean;
    serializerMicros: number;
    atomicPersistMicros: number;
}

export interface GraphForceV2AuthorityReference {
    snapshotId: string;
    authorityHash: string;
    manifestId: string;
}

export function buildGraphForceV2ShadowRequest(
    replay: GraphRebuildReplayManifest,
    snapshot: GraphRebuildSnapshot,
): GraphForceRebuildV2ShadowRequest {
    const authority = snapshot.authorityContract;
    const durable = snapshot.interactiveRunAuthority?.durable;
    if (!authority?.contentHash || !durable || durable.snapshotId !== snapshot.id) {
        throw new Error('PHX_FORCE_V2_AUTHORITY_REQUIRED: the snapshot must have sealed native durability.');
    }
    return buildGraphForceV2ShadowRequestFromAuthority(replay, {
        snapshotId: snapshot.id,
        authorityHash: authority.contentHash,
        manifestId: durable.manifestId,
    });
}

export function buildGraphForceV2ShadowRequestFromAuthority(
    replay: GraphRebuildReplayManifest,
    authority: GraphForceV2AuthorityReference,
): GraphForceRebuildV2ShadowRequest {
    if (replay.action !== 'force' || replay.sourceMode !== 'scoped-note-store') {
        throw new Error('PHX_FORCE_V2_REPLAY_INVALID: a scoped FORCE replay manifest is required.');
    }
    if (!authority.snapshotId || !authority.authorityHash || !authority.manifestId) {
        throw new Error('PHX_FORCE_V2_AUTHORITY_REQUIRED: a complete native authority reference is required.');
    }
    return {
        contractVersion: GRAPH_FORCE_V2_CONTRACT_VERSION,
        operation: 'force',
        sourceMode: 'scoped-note-store',
        scopeId: replay.scope.scopeId,
        cohortId: replay.cohortId,
        scopeKind: replay.scope.kind,
        dependencyIdentity: replay.dependencyIdentity,
        documents: replay.documents.map((row) => ({
            noteId: row.noteId,
            sha256: row.sha256,
            jsCodeUnitChars: row.jsCodeUnitChars,
            utf8Bytes: row.utf8Bytes,
            version: row.version,
            updatedAt: row.updatedAt,
        })),
        model: {
            dynamicNerId: replay.model.dynamicNerId,
            embeddingModelId: replay.model.embeddingModelId,
            embeddingDimension: replay.model.embeddingDimensionLabel,
            nliModelId: replay.model.nliModelId,
        },
        expectedSnapshotId: authority.snapshotId,
        expectedAuthorityHash: authority.authorityHash,
        expectedManifestId: authority.manifestId,
    };
}

export function buildGraphForceV2RequestFromAuthority(
    replay: GraphRebuildReplayManifest,
    authority: GraphForceV2AuthorityReference,
): GraphForceRebuildV2Request {
    const shadow = buildGraphForceV2ShadowRequestFromAuthority(replay, authority);
    const { documents, ...request } = shadow;
    return { ...request, noteIds: documents.map((row) => row.noteId) };
}

export function buildGraphForceV2Request(
    replay: GraphRebuildReplayManifest,
    snapshot: GraphRebuildSnapshot,
): GraphForceRebuildV2Request {
    const shadow = buildGraphForceV2ShadowRequest(replay, snapshot);
    const { documents, ...request } = shadow;
    return { ...request, noteIds: documents.map((row) => row.noteId) };
}

export function assertGraphForceV2ShadowResult(
    result: GraphForceRebuildV2ShadowResult,
    request: GraphForceRebuildV2ShadowRequest,
): GraphForceRebuildV2ShadowResult {
    if (result.schemaVersion !== 'phoenix-force-rebuild-v2-shadow-result/v1'
        || result.contractVersion !== GRAPH_FORCE_V2_CONTRACT_VERSION
        || result.pathId !== GRAPH_FORCE_V2_PATH_ID || result.fallbackCount !== 0) {
        throw new Error('PHX_FORCE_V2_RESPONSE_INVALID: native verified-FORCE identity is missing.');
    }
    if (result.status !== 'durable_verified') {
        const code = result.error?.code || 'PHX_FORCE_V2_REJECTED';
        throw new Error(`${code}: ${result.error?.message || 'native authority rejected the replay'}`);
    }
    if (result.scopeId !== request.scopeId || result.snapshotId !== request.expectedSnapshotId
        || result.authorityHash !== request.expectedAuthorityHash
        || result.manifestId !== request.expectedManifestId
        || result.analysisSource !== 'durable_verified' || result.analysisKernelMicros !== 0
        || result.verifiedSections.length !== 8 || result.nativeCrossings > 3
        || result.criticalResponseBytes > 256 * 1024 || result.transportedSourceBytes !== 0) {
        throw new Error('PHX_FORCE_V2_PARITY_MISMATCH: native durable authority differs from the replay contract.');
    }
    const sourceAuthorityMatches = result.sourceDocuments.length === request.documents.length
        && result.sourceDocuments.every((source, index) => {
            const expected = request.documents[index];
            return source.noteId === expected.noteId && source.sha256 === expected.sha256
                && source.jsCodeUnitChars === expected.jsCodeUnitChars
                && source.utf8Bytes === expected.utf8Bytes;
        });
    const versionEnvelopeChangedFromRequest = sourceAuthorityMatches && result.sourceDocuments.some((source, index) => {
        const expected = request.documents[index];
        return source.version !== expected.version || source.updatedAt !== expected.updatedAt;
    });
    if (!sourceAuthorityMatches || (versionEnvelopeChangedFromRequest && !result.sourceVersionEnvelopeChanged)) {
        throw new Error('PHX_FORCE_V2_SOURCE_IDENTITY_MISMATCH: native source identity differs from the replay contract.');
    }
    const packet = result.authorityPacket;
    if (!packet || packet.id !== result.snapshotId || packet.scopeId !== result.scopeId
        || packet.authorityContract?.contentHash !== result.authorityHash
        || packet.interactiveRunAuthority?.durable.manifestId !== result.manifestId) {
        throw new Error('PHX_FORCE_V2_AUTHORITY_PACKET_MISMATCH: compact native authority is not sealed to the durable run.');
    }
    assertCompactVerifiedForceAuthority(packet, result);
    return result;
}

function assertCompactVerifiedForceAuthority(
    packet: GraphRebuildSnapshot,
    result: GraphForceRebuildV2ShadowResult,
): void {
    const authority = packet.authorityContract;
    const durable = packet.interactiveRunAuthority?.durable;
    const manifest = packet.contentManifest;
    const registry = packet.evidenceTargetRegistry;
    const counts = authority?.counts;
    const counters = packet.counters;
    if (packet.schemaVersion !== 'phoenix-graph-rebuild/v1'
        || authority?.schemaVersion !== 'phoenix-graph-snapshot-authority/v1'
        || authority.authority !== 'graph_rebuild_live_contract'
        || authority.snapshotId !== packet.id || authority.scopeId !== packet.scopeId
        || manifest?.snapshotId !== packet.id || manifest.scopeId !== packet.scopeId
        || durable?.snapshotId !== packet.id || durable.scopeId !== packet.scopeId
        || durable.manifestId !== result.manifestId || durable.runHandle !== result.runHandle
        || !packet.generationReceiptId || !packet.generationDigestSha256?.startsWith('sha256-')
        || !counts || !registry) {
        throw new Error('PHX_FORCE_V2_COMPACT_AUTHORITY_INVALID: compact identity or durability drift.');
    }
    const countPairs: Array<[number, number]> = [
        [counts.chunks, counters.chunks],
        [counts.mentions, counters.mentions], [counts.anchors, counters.acceptedAnchors],
        [counts.relationships, counters.relationships], [counts.events, counters.events],
        [counts.temporalEdges, counters.temporalEdges], [counts.causalEdges, counters.causalEdges],
        [counts.memoryState, counters.memoryState],
        [counts.coreferenceRecoveries, counters.documentSemanticLocalCoreferenceRecoveries || 0],
        [counts.nodes, counters.nodes], [counts.edges, counters.edges],
        [counts.embeddingTargets, counters.embeddingTargets],
    ];
    const record = packet as unknown as Record<string, unknown>;
    const materializedArrays = [
        'chunks', 'mentions', 'entityAnchors', 'relationships', 'events', 'episodes',
        'temporalEdges', 'causalEdges', 'memoryState', 'embeddingTargets', 'embeddingVectors',
        'nodes', 'edges', 'projectionRefs', 'resolutionSuggestions', 'chunkSemanticBridges',
        'memoryGovernanceCandidates', 'episodeConnections', 'episodeProjectionEdges',
    ];
    if (countPairs.some(([expected, actual]) => expected !== actual)
        || counts.notes !== packet.noteIds.length
        || counts.admittedEmbeddingTargets > counts.embeddingTargets
        || counts.packetTargets !== counts.embeddingTargets || counts.packetObjects <= 0
        || !counts.packetFamilies || counts.packetParentLinks < 0
        || materializedArrays.some((name) => Array.isArray(record[name]) && (record[name] as unknown[]).length > 0)
        || registry.sourceSnapshotId !== packet.id || registry.sourceScopeId !== packet.scopeId
        || registry.canonicalTargets !== counts.embeddingTargets || registry.chunks !== counts.chunks
        || registry.exposedTargets + registry.supportTargets !== registry.canonicalTargets
        || registry.chunks + registry.typedGraphObjects !== registry.exposedTargets
        || registry.duplicateTargets !== 0 || registry.orphanTargets !== 0
        || !registry.identityHash.startsWith('fnv32-')) {
        throw new Error('PHX_FORCE_V2_COMPACT_AUTHORITY_INVALID: compact counts or registry drift.');
    }
}
