import type {
    GraphEvidenceTargetObjectKind,
    GraphEvidenceTargetRegistryPage,
    GraphEvidenceTargetRegistryContract,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import { GRAPH_ASSERTED_TRUTH_AUTHORITY } from './graph-asserted-truth-authority';

interface TypedTargetRow {
    target: GraphRebuildEmbeddingTarget;
    objectKind: GraphEvidenceTargetObjectKind;
}

export interface GraphEvidenceTargetRegistry {
    readonly contract: GraphEvidenceTargetRegistryContract;
    readonly canonicalTargets: GraphRebuildEmbeddingTarget[];
    readonly chunks: GraphRebuildEmbeddingTarget[];
    readonly typedGraphObjects: GraphRebuildEmbeddingTarget[];
    readonly exposedTargets: GraphRebuildEmbeddingTarget[];
    get(targetId: string): GraphRebuildEmbeddingTarget | undefined;
    objectKind(targetId: string): GraphEvidenceTargetObjectKind | undefined;
}

export function buildGraphEvidenceTargetRegistry(snapshot: GraphRebuildSnapshot): GraphEvidenceTargetRegistry {
    const targetById = new Map<string, GraphRebuildEmbeddingTarget>();
    const duplicateTargetIds = new Set<string>();
    for (const target of snapshot.embeddingTargets) {
        if (targetById.has(target.id)) duplicateTargetIds.add(target.id);
        else targetById.set(target.id, target);
    }

    const chunkRows = new Set(snapshot.chunks.map((chunk) => chunk.id));
    const nodeRows = new Set(snapshot.nodes.map((node) => node.entityId));
    const acceptedRelationshipRows = new Set(snapshot.relationships
        .filter((row) => row.status === 'accepted')
        .map((row) => row.id));
    const eventRows = new Set(snapshot.events.map((row) => row.id));
    const episodeRows = new Set(snapshot.episodes.map((row) => row.id));
    const temporalRows = new Set(snapshot.temporalEdges.map((row) => row.id));
    const causalRows = new Set(snapshot.causalEdges
        .filter((row) => row.status === 'accepted')
        .map((row) => row.id));
    const memoryRows = new Set(snapshot.memoryState.map((row) => row.id));
    const registryPage = verifiedRegistryPage(snapshot);
    const evidenceRows = new Set([
        ...snapshot.entityAnchors.map((row) => row.id),
        ...(snapshot.documentSidecarSummary?.evidenceSpans || []).map((row) => row.id),
        ...(registryPage?.documentEvidenceIds || []),
    ]);

    const chunks: GraphRebuildEmbeddingTarget[] = [];
    const typedRows: TypedTargetRow[] = [];
    const orphanTargetIds = new Set<string>();
    let evidenceLinks = 0;

    for (const target of snapshot.embeddingTargets) {
        const kind = normalizeKind(target.kind);
        if (kind === 'chunk') {
            if (!chunkRows.has(target.sourceId) || target.chunkId !== target.sourceId) {
                orphanTargetIds.add(target.id);
                continue;
            }
            chunks.push(target);
            continue;
        }
        const objectKind = typedObjectKind(target, {
            nodeRows,
            acceptedRelationshipRows,
            eventRows,
            episodeRows,
            temporalRows,
            causalRows,
            memoryRows,
        });
        if (!objectKind) continue;
        if (!target.evidenceIds.length || target.evidenceIds.some((id) => !evidenceRows.has(id))) {
            // Synthetic and transitional snapshots can carry canonical typed
            // targets before their evidence rows are complete. They remain
            // internal support inventory; the public registry must not expose
            // them as evidence-linked graph truth.
            continue;
        }
        evidenceLinks += target.evidenceIds.length;
        typedRows.push({ target, objectKind });
    }

    const typedGraphObjects = typedRows.map((row) => row.target);
    const exposedTargets = [...chunks, ...typedGraphObjects];
    const contract: GraphEvidenceTargetRegistryContract = {
        schemaVersion: 'phoenix-evidence-target-registry/v1',
        authority: GRAPH_ASSERTED_TRUTH_AUTHORITY,
        sourceSnapshotId: snapshot.id,
        sourceScopeId: snapshot.scopeId,
        canonicalTargets: snapshot.embeddingTargets.length,
        exposedTargets: exposedTargets.length,
        chunks: chunks.length,
        typedGraphObjects: typedGraphObjects.length,
        supportTargets: Math.max(0, snapshot.embeddingTargets.length - exposedTargets.length),
        evidenceLinks,
        duplicateTargets: duplicateTargetIds.size,
        orphanTargets: orphanTargetIds.size,
        identityHash: registryIdentityHash(chunks, typedRows),
    };
    const objectKindById = new Map(typedRows.map((row) => [row.target.id, row.objectKind]));

    return {
        contract,
        canonicalTargets: snapshot.embeddingTargets,
        chunks,
        typedGraphObjects,
        exposedTargets,
        get: (targetId) => targetById.get(targetId),
        objectKind: (targetId) => objectKindById.get(targetId),
    };
}

export function sealGraphEvidenceTargetRegistry(snapshot: GraphRebuildSnapshot): GraphEvidenceTargetRegistry {
    snapshot.evidenceTargetRegistryPage = buildRegistryPage(snapshot);
    const registry = buildGraphEvidenceTargetRegistry(snapshot);
    assertHealthyRegistry(snapshot.id, registry.contract);
    snapshot.evidenceTargetRegistry = registry.contract;
    snapshot.counters.evidenceRegistryExposedTargets = registry.contract.exposedTargets;
    snapshot.counters.evidenceRegistryChunks = registry.contract.chunks;
    snapshot.counters.evidenceRegistryTypedGraphObjects = registry.contract.typedGraphObjects;
    snapshot.counters.evidenceRegistryEvidenceLinks = registry.contract.evidenceLinks;
    return registry;
}

function buildRegistryPage(snapshot: GraphRebuildSnapshot): GraphEvidenceTargetRegistryPage {
    const documentEvidenceIds = [...new Set([
        ...(snapshot.evidenceTargetRegistryPage?.documentEvidenceIds || []),
        ...(snapshot.documentSidecarSummary?.evidenceSpans || []).map((row) => row.id),
    ])].sort();
    return {
        schemaVersion: 'phoenix-evidence-target-registry-page/v1',
        sourceSnapshotId: snapshot.id,
        sourceScopeId: snapshot.scopeId,
        documentEvidenceIds,
    };
}

function verifiedRegistryPage(snapshot: GraphRebuildSnapshot): GraphEvidenceTargetRegistryPage | undefined {
    const page = snapshot.evidenceTargetRegistryPage;
    if (!page) return undefined;
    if (page.schemaVersion !== 'phoenix-evidence-target-registry-page/v1'
        || page.sourceSnapshotId !== snapshot.id
        || page.sourceScopeId !== snapshot.scopeId) {
        throw new Error(`Graph evidence target registry page drift for ${snapshot.id}`);
    }
    return page;
}

export function assertGraphEvidenceTargetRegistry(snapshot: GraphRebuildSnapshot): GraphEvidenceTargetRegistry {
    const expected = snapshot.evidenceTargetRegistry;
    if (!expected) throw new Error(`Graph evidence target registry missing for ${snapshot.id}`);
    const registry = buildGraphEvidenceTargetRegistry(snapshot);
    assertHealthyRegistry(snapshot.id, registry.contract);
    if (JSON.stringify(expected) !== JSON.stringify(registry.contract)) {
        throw new Error(`Graph evidence target registry drift for ${snapshot.id}`);
    }
    if (
        snapshot.counters.evidenceRegistryExposedTargets !== registry.contract.exposedTargets
        || snapshot.counters.evidenceRegistryChunks !== registry.contract.chunks
        || snapshot.counters.evidenceRegistryTypedGraphObjects !== registry.contract.typedGraphObjects
        || snapshot.counters.evidenceRegistryEvidenceLinks !== registry.contract.evidenceLinks
    ) {
        throw new Error(`Graph evidence target registry counters drift for ${snapshot.id}`);
    }
    return registry;
}

function typedObjectKind(
    target: GraphRebuildEmbeddingTarget,
    rows: {
        nodeRows: Set<string>;
        acceptedRelationshipRows: Set<string>;
        eventRows: Set<string>;
        episodeRows: Set<string>;
        temporalRows: Set<string>;
        causalRows: Set<string>;
        memoryRows: Set<string>;
    },
): GraphEvidenceTargetObjectKind | null {
    const kind = normalizeKind(target.kind);
    if (kind === 'entity' && rows.nodeRows.has(target.sourceId)) return 'entity';
    if (kind === 'graphfact' && rows.acceptedRelationshipRows.has(target.sourceId)) return 'relationship';
    if (kind === 'event' && rows.eventRows.has(target.sourceId)) return 'event';
    if (kind === 'episode' && rows.episodeRows.has(target.sourceId)) return 'episode';
    if (kind === 'temporalfact' && rows.temporalRows.has(target.sourceId)) return 'temporal_edge';
    if (kind === 'causalfact' && rows.causalRows.has(target.sourceId)) return 'causal_edge';
    if (kind === 'memorystate' && rows.memoryRows.has(target.sourceId)) return 'memory_state';
    return null;
}

function assertHealthyRegistry(snapshotId: string, contract: GraphEvidenceTargetRegistryContract): void {
    const issues: string[] = [];
    if (contract.duplicateTargets) issues.push(`duplicate targets ${contract.duplicateTargets}`);
    if (contract.orphanTargets) issues.push(`orphan targets ${contract.orphanTargets}`);
    if (issues.length) {
        throw new Error(`Graph evidence target registry failed for ${snapshotId}: ${issues.join(', ')}`);
    }
}

function registryIdentityHash(
    chunks: GraphRebuildEmbeddingTarget[],
    typedRows: TypedTargetRow[],
): string {
    let hash = 0x811c9dc5;
    const add = (value: string): void => {
        for (let index = 0; index < value.length; index += 1) {
            hash ^= value.charCodeAt(index);
            hash = Math.imul(hash, 0x01000193) >>> 0;
        }
    };
    for (const target of chunks) add(`chunk\0${target.id}\0${target.sourceId}\0`);
    for (const row of typedRows) {
        add(`${row.objectKind}\0${row.target.id}\0${row.target.sourceId}\0`);
        for (const evidenceId of row.target.evidenceIds) add(`${evidenceId}\0`);
    }
    return `fnv32-${hash.toString(16).padStart(8, '0')}`;
}

function normalizeKind(kind: string): string {
    return kind.toLowerCase().replace(/[^a-z0-9]+/g, '');
}
