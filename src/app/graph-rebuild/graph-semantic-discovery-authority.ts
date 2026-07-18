import { GRAPH_SEMANTIC_DISCOVERY_POLICY } from './graph-asserted-truth-authority';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export interface GraphSemanticDiscoveryAuthorityReceipt {
    schemaVersion: 'phoenix-semantic-discovery-authority/v1';
    sourceSnapshotId: string;
    policy: typeof GRAPH_SEMANTIC_DISCOVERY_POLICY;
    semanticSurfaces: number;
    candidateRows: number;
    candidateOnly: true;
    explicitPromotionRequired: true;
    assertedTopologyLeaks: 0;
    committedTopologyWrites: 0;
}

interface CandidateSurface {
    label: string;
    value: unknown;
    rowProperties: string[];
}

const WRITE_COUNT_KEYS = new Set([
    'appliedMutationCount',
    'committedTopologyWrites',
    'graphChangeRows',
    'mutationAllowedCount',
    'mutationCount',
    'topologyCommitCount',
]);

export function assertGraphSemanticDiscoveriesRemainCandidates(
    snapshot: GraphRebuildSnapshot,
): GraphSemanticDiscoveryAuthorityReceipt {
    const surfaces = candidateSurfaces(snapshot);
    const issues: string[] = [];
    let candidateRows = 0;
    for (const surface of surfaces) {
        const record = objectRecord(surface.value);
        if (!record) {
            if (Array.isArray(surface.value)) candidateRows += surface.value.length;
            continue;
        }
        if ('sourceSnapshotId' in record && record['sourceSnapshotId'] !== snapshot.id) {
            issues.push(`${surface.label} snapshot identity`);
        }
        candidateRows += surface.rowProperties.reduce(
            (sum, property) => sum + arrayValue(record[property]).length,
            0,
        );
        scanWriteMarkers(surface.label, surface.value, issues);
    }

    const assertedIds = new Set([
        ...snapshot.edges.map((row) => row.id),
        ...snapshot.relationships.filter((row) => row.status === 'accepted').map((row) => row.id),
    ]);
    const candidateIds = candidateOwnedIds(surfaces);
    const identityLeaks = [...candidateIds].filter((id) => assertedIds.has(id));
    if (identityLeaks.length) issues.push(`candidate identities in asserted topology ${identityLeaks.length}`);
    const semanticEdges = snapshot.edges.filter((edge) =>
        isSemanticTopologyToken(edge.id) || isSemanticTopologyToken(edge.type),
    );
    const semanticRelationships = snapshot.relationships.filter((row) =>
        row.status === 'accepted' && isSemanticTopologyToken(row.relationType),
    );
    if (semanticEdges.length) issues.push(`semantic edges in asserted topology ${semanticEdges.length}`);
    if (semanticRelationships.length) {
        issues.push(`semantic relationships in asserted topology ${semanticRelationships.length}`);
    }

    if (issues.length) {
        throw new Error(
            `Semantic discoveries crossed the candidate boundary for ${snapshot.id}: ${issues.join(', ')}`,
        );
    }
    return {
        schemaVersion: 'phoenix-semantic-discovery-authority/v1',
        sourceSnapshotId: snapshot.id,
        policy: GRAPH_SEMANTIC_DISCOVERY_POLICY,
        semanticSurfaces: surfaces.filter((surface) => surface.value !== undefined).length,
        candidateRows,
        candidateOnly: true,
        explicitPromotionRequired: true,
        assertedTopologyLeaks: 0,
        committedTopologyWrites: 0,
    };
}

function candidateSurfaces(snapshot: GraphRebuildSnapshot): CandidateSurface[] {
    return [
        surface('embedding graph postprocess', snapshot.embeddingGraphPostProcess, ['backboneEdges', 'bridgeEdges']),
        surface('graph-aware suggestions', snapshot.graphAwareLinkSuggestions, []),
        surface('entity-link suggestions', snapshot.entityLinkSuggestions, []),
        surface('shadow-link suggestions', snapshot.shadowLinkSuggestions, []),
        surface('semantic tasks', snapshot.semanticTaskSummary, ['tasks']),
        surface('semantic candidates', snapshot.semanticCandidateSummary, ['candidates']),
        surface('manifold specialization', snapshot.manifoldSpecializationSummary, ['contributions']),
        surface('semantic rerank', snapshot.semanticRerankSummary, ['judgments']),
        surface('semantic adjudication', snapshot.semanticAdjudicationSummary, ['decisions']),
        surface('semantic eval ledger', snapshot.semanticEvalLedgerSummary, ['entries']),
        surface('hopf resonance', snapshot.hopfResonanceSpace, ['assignments']),
        surface('memory graphrag bridge', snapshot.memoryGraphRagBridgeSummary, ['records', 'evalRows']),
        surface('discourse spine', snapshot.discourseSpineSummary, ['bridges']),
        surface('discourse bridge candidates', snapshot.discourseBridgeCandidateSummary, ['candidates']),
        surface('discourse bridge adjudication', snapshot.discourseBridgeAdjudicationSummary, ['decisions']),
        surface('discourse eval ledger', snapshot.discourseEvalLedgerSummary, ['entries']),
        surface('discourse promotion preview', snapshot.discoursePromotionSurfaceSummary, ['hints']),
        surface('discourse compiler overlay', snapshot.discourseCompilerOverlaySummary, ['edges']),
        surface('promotion verdict preview', snapshot.promotionVerdictCertificate, ['rows']),
    ];
}

function surface(label: string, value: unknown, rowProperties: string[]): CandidateSurface {
    return { label, value, rowProperties };
}

function scanWriteMarkers(label: string, root: unknown, issues: string[]): void {
    const stack: unknown[] = [root];
    while (stack.length) {
        const value = stack.pop();
        if (Array.isArray(value)) {
            for (const row of value) stack.push(row);
            continue;
        }
        const record = objectRecord(value);
        if (!record) continue;
        for (const [key, child] of Object.entries(record)) {
            if (key === 'mutationAllowed' && child !== false) issues.push(`${label} mutation allowed`);
            else if (WRITE_COUNT_KEYS.has(key) && child !== 0) issues.push(`${label} ${key} ${String(child)}`);
            else if ((key === 'graphPatch' || key === 'topologyCommit') && child !== false) {
                issues.push(`${label} ${key}`);
            } else if (key === 'noTopologyWrites' && child !== true) {
                issues.push(`${label} topology-write certificate`);
            } else if (key === 'mutations' && Array.isArray(child) && child.length) {
                issues.push(`${label} mutations ${child.length}`);
            }
            if (child && typeof child === 'object') stack.push(child);
        }
    }
}

function candidateOwnedIds(surfaces: CandidateSurface[]): Set<string> {
    const ids = new Set<string>();
    for (const candidateSurface of surfaces) {
        const record = objectRecord(candidateSurface.value);
        if (!record) {
            if (Array.isArray(candidateSurface.value)) addDirectIds(ids, candidateSurface.value);
            continue;
        }
        for (const property of candidateSurface.rowProperties) addDirectIds(ids, arrayValue(record[property]));
    }
    return ids;
}

function addDirectIds(ids: Set<string>, rows: unknown[]): void {
    for (const row of rows) {
        const id = objectRecord(row)?.['id'];
        if (typeof id === 'string' && id) ids.add(id);
    }
}

function isSemanticTopologyToken(value: string): boolean {
    const token = value.toLocaleLowerCase();
    return token.startsWith('semantic-adjudication:')
        || token.startsWith('semantic::');
}

function objectRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function arrayValue(value: unknown): unknown[] {
    return Array.isArray(value) ? value : [];
}
