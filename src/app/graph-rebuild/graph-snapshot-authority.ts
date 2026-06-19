import type {
    GraphRebuildContentBlobField,
    GraphRebuildEmbeddingTargetPlan,
    GraphRebuildSnapshot,
    GraphSnapshotAuthority,
    GraphSnapshotAuthorityContract,
    GraphSnapshotAuthorityCounts,
} from './graph-rebuild-snapshot';

export const GRAPH_SNAPSHOT_CONTAINMENT_AUTHORITY: GraphSnapshotAuthority =
    'typescript_compatibility_containment';

export interface GraphSnapshotHydrationBlob {
    scopeId: string;
    field: GraphRebuildContentBlobField;
    hash: string;
    value: unknown;
}

export function sealGraphSnapshotAuthority(
    snapshot: GraphRebuildSnapshot,
    authority: GraphSnapshotAuthority = GRAPH_SNAPSHOT_CONTAINMENT_AUTHORITY,
): GraphSnapshotAuthorityContract {
    assertGraphSnapshotParity(snapshot, true);
    const contract = buildGraphSnapshotAuthorityContract(snapshot, authority);
    snapshot.authorityContract = contract;
    return contract;
}

export function assertGraphSnapshotAuthority(snapshot: GraphRebuildSnapshot): GraphSnapshotAuthorityContract {
    const contract = snapshot.authorityContract;
    if (!contract) {
        throw new Error(`Graph snapshot authority contract missing for ${snapshot.id}`);
    }
    assertGraphSnapshotParity(snapshot, true);
    const actual = buildGraphSnapshotAuthorityContract(snapshot, contract.authority);
    const issues: string[] = [];
    if (contract.schemaVersion !== actual.schemaVersion) issues.push('schema version');
    if (contract.snapshotId !== actual.snapshotId) issues.push('snapshot id');
    if (contract.scopeId !== actual.scopeId) issues.push('scope id');
    if (contract.contentHash !== actual.contentHash) issues.push('content hash');
    if (JSON.stringify(contract.counts) !== JSON.stringify(actual.counts)) issues.push('counts');
    if (issues.length) {
        throw new Error(`Graph snapshot authority contract drift for ${snapshot.id}: ${issues.join(', ')}`);
    }
    return contract;
}

export function hydrateGraphSnapshotContent(
    persisted: GraphRebuildSnapshot,
    blobs: Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>,
): GraphRebuildSnapshot {
    const snapshot = { ...persisted };
    const refs = persisted.contentManifest?.refs || {};
    for (const [field, ref] of Object.entries(refs) as Array<[
        GraphRebuildContentBlobField,
        NonNullable<(typeof refs)[GraphRebuildContentBlobField]>,
    ]>) {
        const blob = blobs[field];
        if (!blob) throw new Error(`Graph snapshot content blob missing: ${field}`);
        if (blob.field !== field || blob.scopeId !== snapshot.scopeId) {
            throw new Error(`Graph snapshot content blob identity mismatch: ${field}`);
        }
        const legacyHash = graphSnapshotContentHash(JSON.stringify(blob.value));
        const hash = graphSnapshotContentHash(JSON.stringify(graphSnapshotStableContentValue(blob.value)));
        if (blob.hash !== ref.hash || (hash !== ref.hash && legacyHash !== ref.hash)) {
            throw new Error(`Graph snapshot content blob hash mismatch: ${field}`);
        }
        applyHydratedField(snapshot, field, blob.value);
    }
    if (snapshot.embeddingTargetPlan) {
        snapshot.embeddingTargetPlan = {
            ...snapshot.embeddingTargetPlan,
            targets: snapshot.embeddingTargets,
        } as GraphRebuildEmbeddingTargetPlan;
    }
    return snapshot;
}

export function graphSnapshotContentHash(raw: string): string {
    let left = 0x811c9dc5;
    let right = 0x45d9f3b;
    for (let index = 0; index < raw.length; index += 1) {
        const code = raw.charCodeAt(index);
        left ^= code;
        left = Math.imul(left, 0x01000193) >>> 0;
        right ^= code + index;
        right = Math.imul(right, 0x85ebca6b) >>> 0;
    }
    return `fnv64-${left.toString(16).padStart(8, '0')}${right.toString(16).padStart(8, '0')}`;
}

function buildGraphSnapshotAuthorityContract(
    snapshot: GraphRebuildSnapshot,
    authority: GraphSnapshotAuthority,
): GraphSnapshotAuthorityContract {
    const counts = graphSnapshotAuthorityCounts(snapshot);
    return {
        schemaVersion: 'phoenix-graph-snapshot-authority/v1',
        authority,
        snapshotId: snapshot.id,
        scopeId: snapshot.scopeId,
        contentHash: graphSnapshotContentHash(JSON.stringify(authorityReceipt(snapshot, counts))),
        counts,
    };
}

function graphSnapshotAuthorityCounts(snapshot: GraphRebuildSnapshot): GraphSnapshotAuthorityCounts {
    const packet = snapshot.atlasPacket;
    const packetFamilies = familyCountsFromRows(packet?.objects.map((object) => object.family) || []);
    return {
        notes: snapshot.noteIds.length,
        chunks: snapshot.chunks.length,
        mentions: snapshot.mentions.length,
        anchors: snapshot.entityAnchors.length,
        relationships: snapshot.relationships.length,
        events: snapshot.events.length,
        temporalEdges: snapshot.temporalEdges.length,
        causalEdges: snapshot.causalEdges.length,
        memoryState: snapshot.memoryState.length,
        coreferenceRecoveries: snapshot.counters.documentSemanticLocalCoreferenceRecoveries || 0,
        nodes: snapshot.nodes.length,
        edges: snapshot.edges.length,
        embeddingTargets: snapshot.embeddingTargets.length,
        admittedEmbeddingTargets: packet?.manifoldTargets
            .filter((target) => target.admission === 'admitted').length || 0,
        packetObjects: packet?.objects.length || 0,
        packetTargets: packet?.manifoldTargets.length || 0,
        packetParentLinks: packet?.manifoldTargets.reduce((sum, target) => sum + (target.parentIds?.length || 0), 0) || 0,
        packetFamilies,
    };
}

function assertGraphSnapshotParity(snapshot: GraphRebuildSnapshot, requirePacket: boolean): void {
    const counts = graphSnapshotAuthorityCounts(snapshot);
    const issues: string[] = [];
    compare(issues, 'chunks', snapshot.counters.chunks, counts.chunks);
    compare(issues, 'mentions', snapshot.counters.mentions, counts.mentions);
    compare(issues, 'anchors', snapshot.counters.acceptedAnchors, counts.anchors);
    compare(issues, 'relationships', snapshot.counters.relationships, counts.relationships);
    compare(issues, 'events', snapshot.counters.events, counts.events);
    compare(issues, 'temporal edges', snapshot.counters.temporalEdges, counts.temporalEdges);
    compare(issues, 'causal edges', snapshot.counters.causalEdges, counts.causalEdges);
    compare(issues, 'memory state', snapshot.counters.memoryState, counts.memoryState);
    compare(issues, 'nodes', snapshot.counters.nodes, counts.nodes);
    compare(issues, 'edges', snapshot.counters.edges, counts.edges);
    compare(issues, 'embedding targets', snapshot.counters.embeddingTargets, counts.embeddingTargets);
    assertEmbeddingTargetsHaveSourceRows(issues, snapshot, counts);

    const packet = snapshot.atlasPacket;
    if (requirePacket && !packet) issues.push('Atlas packet missing');
    if (packet) {
        if (packet.snapshotId !== snapshot.id) issues.push('Atlas packet snapshot id');
        if (packet.scopeId !== snapshot.scopeId) issues.push('Atlas packet scope id');
        compare(issues, 'packet objects', packet.counters.objects, counts.packetObjects);
        compare(issues, 'packet targets', packet.counters.manifoldTargets, counts.packetTargets);
        compare(issues, 'packet registry entities', packet.counters.registryEntities, counts.nodes);
        compare(issues, 'packet evidence anchors', packet.counters.evidenceAnchors, counts.anchors);
        compare(issues, 'packet/snapshot targets', counts.packetTargets, counts.embeddingTargets);
        const summarizedFamilies = familyCountsFromCounterRows(packet.counters.families);
        if (!sameFamilyCounts(summarizedFamilies, counts.packetFamilies)) {
            issues.push('packet family counters');
        }
        const resolvableParents = new Set([
            ...packet.objects.flatMap((object) => [object.id, ...object.sourceIds]),
            ...packet.manifoldTargets.flatMap((target) => [target.id, target.objectId, target.sourceId]),
        ]);
        const unresolvedParents = packet.manifoldTargets
            .flatMap((target) => target.parentIds || [])
            .filter((parentId) => !resolvableParents.has(parentId));
        if (unresolvedParents.length) issues.push(`unresolved packet parents (${unresolvedParents.length})`);
    }
    if (issues.length) {
        throw new Error(`Graph snapshot parity failed for ${snapshot.id}: ${issues.join(', ')}`);
    }
}

function assertEmbeddingTargetsHaveSourceRows(
    issues: string[],
    snapshot: GraphRebuildSnapshot,
    counts: GraphSnapshotAuthorityCounts,
): void {
    const lanes = embeddingTargetLaneCounts(snapshot);
    const entityTargets = lanes['entity_anchor'] || 0;
    const evidenceTargets = lanes['anchor_evidence'] || 0;
    const relationTargets = (lanes['relationship_fact'] || 0)
        + (lanes['temporal_fact'] || 0)
        + (lanes['causal_fact'] || 0)
        + (lanes['memory_state'] || 0)
        + (lanes['event_identity'] || 0);
    const factRows = counts.relationships
        + counts.temporalEdges
        + counts.causalEdges
        + counts.memoryState
        + counts.events;

    if (entityTargets && !counts.anchors) {
        issues.push(`entity target lanes without source anchors (${entityTargets})`);
    }
    if (evidenceTargets && !counts.mentions && !counts.anchors) {
        issues.push(`evidence target lanes without mentions or anchors (${evidenceTargets})`);
    }
    if (relationTargets && !factRows) {
        issues.push(`fact target lanes without source fact rows (${relationTargets})`);
    }
    if (counts.nodes && !counts.anchors && (entityTargets || evidenceTargets || relationTargets)) {
        issues.push(`registry nodes without accepted source rows (${counts.nodes})`);
    }
}

function embeddingTargetLaneCounts(snapshot: GraphRebuildSnapshot): Record<string, number> {
    const counts = new Map<string, number>();
    for (const target of snapshot.embeddingTargets) {
        if (target.kind === 'structureRoot') continue;
        const lane = target.lane || 'unknown';
        counts.set(lane, (counts.get(lane) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function compare(issues: string[], label: string, expected: number, actual: number): void {
    if (expected !== actual) issues.push(`${label} ${expected} != ${actual}`);
}

function familyCountsFromRows(families: string[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const family of families) counts.set(family, (counts.get(family) || 0) + 1);
    return sortedFamilyCounts(counts);
}

function familyCountsFromCounterRows(rows: Array<{ family: string; count: number }>): Record<string, number> {
    const counts = new Map<string, number>();
    for (const row of rows) counts.set(row.family, row.count);
    return sortedFamilyCounts(counts);
}

function sortedFamilyCounts(counts: Map<string, number>): Record<string, number> {
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function sameFamilyCounts(left: Record<string, number>, right: Record<string, number>): boolean {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return leftKeys.length === rightKeys.length
        && leftKeys.every((key) => left[key] === right[key]);
}

function authorityReceipt(
    snapshot: GraphRebuildSnapshot,
    counts: GraphSnapshotAuthorityCounts,
): unknown {
    return {
        scopeId: snapshot.scopeId,
        noteIds: [...snapshot.noteIds].sort(),
        counts,
        chunks: authorityRowHashes(snapshot.chunks),
        mentions: authorityRowHashes(snapshot.mentions),
        entityAnchors: authorityRowHashes(snapshot.entityAnchors),
        relationships: authorityRowHashes(snapshot.relationships),
        events: authorityRowHashes(snapshot.events),
        temporalEdges: authorityRowHashes(snapshot.temporalEdges),
        causalEdges: authorityRowHashes(snapshot.causalEdges),
        memoryState: authorityRowHashes(snapshot.memoryState),
        nodes: authorityRowHashes(snapshot.nodes),
        edges: authorityRowHashes(snapshot.edges),
        embeddingTargets: authorityRowHashes(snapshot.embeddingTargets),
        projectionRefs: authorityRowHashes(snapshot.projectionRefs),
        atlasObjects: authorityRowHashes(snapshot.atlasPacket?.objects || []),
        atlasTargets: authorityRowHashes(snapshot.atlasPacket?.manifoldTargets || []),
    };
}

const VOLATILE_AUTHORITY_KEYS = new Set([
    'builtAt',
    'createdAt',
    'updatedAt',
    'generation',
    'snapshotId',
]);

const VOLATILE_CONTENT_HASH_KEYS = new Set([
    'builtAt',
    'createdAt',
    'updatedAt',
    'generatedAt',
    'generation',
    'snapshotId',
    'sourceSnapshotId',
]);

function authorityRowHashes(rows: unknown[]): string[] {
    return rows
        .map((row) => graphSnapshotContentHash(JSON.stringify(stableAuthorityValue(row))))
        .sort();
}

function stableAuthorityValue(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(stableAuthorityValue);
    if (!value || typeof value !== 'object') return value;
    const record = value as Record<string, unknown>;
    const stable: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) {
        if (!VOLATILE_AUTHORITY_KEYS.has(key)) stable[key] = stableAuthorityValue(record[key]);
    }
    return stable;
}

export function graphSnapshotStableContentValue(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(graphSnapshotStableContentValue);
    if (!value || typeof value !== 'object') return value;
    const record = value as Record<string, unknown>;
    const stable: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) {
        if (!VOLATILE_CONTENT_HASH_KEYS.has(key)) {
            stable[key] = graphSnapshotStableContentValue(record[key]);
        }
    }
    return stable;
}

function applyHydratedField(
    snapshot: GraphRebuildSnapshot,
    field: GraphRebuildContentBlobField,
    value: unknown,
): void {
    if (field === 'sourceRows') {
        assignKnown(snapshot, value, [
            'chunks', 'mentions', 'entityAnchors', 'relationships', 'events',
            'temporalEdges', 'causalEdges', 'memoryState',
        ]);
    } else if (field === 'renderRows') {
        assignKnown(snapshot, value, ['projectionRefs', 'nodes', 'edges', 'structuralPostProcess', 'projectedUiGraph']);
    } else if (field === 'atlasPacket') {
        snapshot.atlasPacket = value && typeof value === 'object' ? {
            ...(value as NonNullable<GraphRebuildSnapshot['atlasPacket']>),
            snapshotId: snapshot.id,
            builtAt: snapshot.builtAt,
        } : undefined;
    } else if (field === 'atlasDebugSummaries') {
        assignKnown(snapshot, value, [
            'graphAwareLinkSuggestions', 'entityLinkSuggestions', 'shadowLinkSuggestions',
            'finalLinkPatchLog', 'documentSidecarSummary', 'documentSemanticSummary',
            'documentReviewSummary', 'documentCompilerSummary', 'calendarRegistrySummary',
        ]);
    } else {
        (snapshot as unknown as Record<string, unknown>)[field] = value;
    }
}

function assignKnown(snapshot: GraphRebuildSnapshot, value: unknown, keys: string[]): void {
    if (!value || typeof value !== 'object') return;
    const record = value as Record<string, unknown>;
    const target = snapshot as unknown as Record<string, unknown>;
    for (const key of keys) {
        if (key in record) target[key] = record[key];
    }
}
