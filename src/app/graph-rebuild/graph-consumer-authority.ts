import { GRAPH_ASSERTED_TRUTH_AUTHORITY } from './graph-asserted-truth-authority';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_CONSUMER_AUTHORITY_SCHEMA_VERSION =
    'phoenix-graph-consumer-authority/v1' as const;
export const GRAPH_CONSUMER_READ_ONLY_POLICY =
    'consume_asserted_graph_never_rewrite_truth' as const;

export type GraphConsumerKind = 'manifold' | 'gfm';

export interface GraphConsumerAuthorityReceipt {
    schemaVersion: typeof GRAPH_CONSUMER_AUTHORITY_SCHEMA_VERSION;
    consumer: GraphConsumerKind;
    policy: typeof GRAPH_CONSUMER_READ_ONLY_POLICY;
    sourceIdentity: string;
    inputAuthority: typeof GRAPH_ASSERTED_TRUTH_AUTHORITY;
    outputAuthority: 'projection_or_ranking_only';
    readOnly: true;
    mutationAllowed: false;
    promotionAllowed: false;
    noTopologyWrites: true;
    graphTruthCommitIds: [];
    checkedObjects: number;
    opaqueBulkRows: number;
}

export interface GraphConsumerAuthorityEnvelope {
    consumerAuthority?: GraphConsumerAuthorityReceipt;
}

const ZERO_WRITE_KEYS = new Set([
    'appliedMutationCount',
    'committedTopologyWrites',
    'graphChangeRows',
    'graphPatchCount',
    'mutationAllowedCount',
    'mutationCount',
    'topologyCommitCount',
    'topologyWrites',
]);

const EMPTY_WRITE_KEYS = new Set([
    'graphPatches',
    'graphTruthCommitIds',
    'mutationBatches',
    'mutations',
    'topologyCommits',
    'writeSet',
]);

const TRUTH_OPERATIONS = new Set(['assert', 'supersede', 'retract', 'revert']);

const OPAQUE_BULK_KEYS = new Set([
    'anchorProjections',
    'cells',
    'charts',
    'coneProgramTraces',
    'conePrograms',
    'coneTraces',
    'edges',
    'hits',
    'lorentzMemberships',
    'lorentzTrees',
    'memberships',
    'neighborRings',
    'nodes',
    'obstructions',
    'pathlets',
    'positions',
    'results',
    'seams',
    'trees',
    'vectors',
]);

export function assertGraphConsumerReadOnly(
    consumer: GraphConsumerKind,
    sourceIdentity: string,
    output: unknown,
): GraphConsumerAuthorityReceipt {
    if (!sourceIdentity.trim()) throw new Error(`${consumer} graph consumer source identity is missing.`);
    const issues: string[] = [];
    let checkedObjects = 0;
    let opaqueBulkRows = 0;
    const stack: Array<{ path: string; value: unknown }> = [{ path: consumer, value: output }];
    const seen = new Set<object>();
    while (stack.length) {
        const current = stack.pop()!;
        if (Array.isArray(current.value)) {
            for (let index = 0; index < current.value.length; index += 1) {
                stack.push({ path: `${current.path}[${index}]`, value: current.value[index] });
            }
            continue;
        }
        const record = objectRecord(current.value);
        if (!record || seen.has(record)) continue;
        seen.add(record);
        checkedObjects += 1;
        for (const [key, value] of Object.entries(record)) {
            const path = `${current.path}.${key}`;
            if (key === 'mutationAllowed' && value !== false) issues.push(`${path}=${String(value)}`);
            else if (key === 'promotionAllowed' && value !== false) issues.push(`${path}=${String(value)}`);
            else if (key === 'noTopologyWrites' && value !== true) issues.push(`${path}=${String(value)}`);
            else if (key === 'readOnly' && value !== true) issues.push(`${path}=${String(value)}`);
            else if (key === 'inputAuthority' && value !== GRAPH_ASSERTED_TRUTH_AUTHORITY) {
                issues.push(`${path}=${String(value)}`);
            }
            else if (ZERO_WRITE_KEYS.has(key) && value !== 0) issues.push(`${path}=${String(value)}`);
            else if (EMPTY_WRITE_KEYS.has(key) && (!Array.isArray(value) || value.length !== 0)) {
                issues.push(`${path} is not empty`);
            } else if ((key === 'graphPatch' || key === 'topologyCommit') && value !== false && value != null) {
                issues.push(`${path} is present`);
            } else if (key === 'operation' && typeof value === 'string' && TRUTH_OPERATIONS.has(value)) {
                issues.push(`${path}=${value}`);
            } else if (key === 'nativeCommitRequired' && value === true) {
                issues.push(`${path}=true`);
            } else if (key === 'snapshotMutationAllowed' && value !== false) {
                issues.push(`${path}=${String(value)}`);
            } else if (key === 'outputAuthority' && value !== 'projection_or_ranking_only') {
                issues.push(`${path}=${String(value)}`);
            }
            if (Array.isArray(value) && isOpaqueBulkArray(key)) {
                opaqueBulkRows += value.length;
            } else if (value && typeof value === 'object') {
                stack.push({ path, value });
            }
        }
    }
    if (issues.length) {
        throw new Error(
            `${consumer} graph consumer crossed the read-only authority boundary: ${issues.join(', ')}.`,
        );
    }
    return {
        schemaVersion: GRAPH_CONSUMER_AUTHORITY_SCHEMA_VERSION,
        consumer,
        policy: GRAPH_CONSUMER_READ_ONLY_POLICY,
        sourceIdentity,
        inputAuthority: GRAPH_ASSERTED_TRUTH_AUTHORITY,
        outputAuthority: 'projection_or_ranking_only',
        readOnly: true,
        mutationAllowed: false,
        promotionAllowed: false,
        noTopologyWrites: true,
        graphTruthCommitIds: [],
        checkedObjects,
        opaqueBulkRows,
    };
}

export function withGraphConsumerAuthority<T extends object>(
    consumer: GraphConsumerKind,
    sourceIdentity: string,
    output: T,
): T & { consumerAuthority: GraphConsumerAuthorityReceipt } {
    const consumerAuthority = assertGraphConsumerReadOnly(consumer, sourceIdentity, output);
    return { ...output, consumerAuthority };
}

export function assertSnapshotGraphConsumersReadOnly(snapshot: GraphRebuildSnapshot): void {
    const surfaces: Array<[string, unknown]> = [
        ['manifold-specialization', snapshot.manifoldSpecializationSummary],
        ['hopf-resonance', snapshot.hopfResonanceSpace],
        ['embedding-manifold', snapshot.embeddingGraphPostProcess],
    ];
    for (const [label, output] of surfaces) {
        if (output === undefined) continue;
        assertGraphConsumerReadOnly('manifold', `${snapshot.id}:${label}`, output);
    }
}

function objectRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function isOpaqueBulkArray(key: string): boolean {
    return OPAQUE_BULK_KEYS.has(key) || key.endsWith('Ids') || key.endsWith('Keys');
}
