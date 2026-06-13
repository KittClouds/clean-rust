import type {
    GraphDocumentCompilerSummary,
    GraphDocumentHyperedge,
    GraphDocumentTopologyDiff,
    GraphDocumentTopologyReceipt,
} from './graph-document-compiler';
import type { EvidenceSpan, GraphDocumentSidecarSummary } from './graph-document-sidecar';

export interface GraphDocumentDurableVertex {
    id: string;
    kind: 'entity' | 'document_fact' | 'evidence_span';
    label: string;
    removeOnUndo: boolean;
    attributes: Record<string, unknown>;
}

export interface GraphDocumentDurableEdge {
    source: string;
    target: string;
    edgeType: 'document_fact_role' | 'supported_by_evidence_span';
    weight: number;
    attributes: Record<string, unknown>;
}

export interface GraphDocumentDurableCommitRequest {
    schemaVersion: 'phoenix-document-graph-commit/v1';
    commitId: string;
    scopeId: string;
    topologyDiffId: string;
    sourceObjectId: string;
    receiptId: string;
    builtAt: number;
    vertices: GraphDocumentDurableVertex[];
    edges: GraphDocumentDurableEdge[];
}

export interface GraphDocumentDurableUndoRequest {
    schemaVersion: 'phoenix-document-graph-undo/v1';
    commitId: string;
    undoneAt: number;
}

export interface GraphDocumentDurableCommitResult {
    commitId: string;
    createdVertexIds: string[];
    createdEdgeKeys: string[];
    idempotent: boolean;
}

export interface GraphDocumentDurableUndoResult {
    commitId: string;
    removedVertices: number;
    removedEdges: number;
    removedLabels: number;
    idempotent: boolean;
}

export interface GraphDocumentGraphMutationRecord {
    id: string;
    commitId: string;
    topologyDiffId: string;
    sourceObjectId: string;
    receiptId: string;
    status: 'committed' | 'undone';
    vertexIds: string[];
    edgeKeys: string[];
    committedAt: number;
    undoneAt?: number;
}

export interface GraphDocumentGraphMutationLedger {
    schemaVersion: 'phoenix-document-graph-mutation-ledger/v1';
    records: GraphDocumentGraphMutationRecord[];
    counters: {
        commits: number;
        active: number;
        undone: number;
        vertices: number;
        edges: number;
    };
}

export interface GraphDocumentMutationPlan {
    commits: GraphDocumentDurableCommitRequest[];
    undos: GraphDocumentDurableUndoRequest[];
}

export interface BuildGraphDocumentDurableCommitsInput {
    scopeId: string;
    compiler?: GraphDocumentCompilerSummary;
    sidecar?: GraphDocumentSidecarSummary;
}

export function buildGraphDocumentDurableCommitRequests(
    input: BuildGraphDocumentDurableCommitsInput,
): GraphDocumentDurableCommitRequest[] {
    const compiler = input.compiler;
    const sidecar = input.sidecar;
    if (!compiler || !sidecar) return [];
    const hyperedges = new Map(compiler.hyperedges.map((row) => [row.id, row]));
    const receipts = new Map(compiler.receipts.map((row) => [row.topologyDiffId, row]));
    const evidence = new Map(sidecar.evidenceSpans.map((row) => [row.id, row]));
    const requests: GraphDocumentDurableCommitRequest[] = [];
    for (const diff of compiler.topologyDiffs) {
        const request = durableRequestFor(
            input.scopeId,
            compiler.builtAt,
            diff,
            hyperedges.get(diff.outputId),
            receipts.get(diff.id),
            evidence,
        );
        if (request) requests.push(request);
    }
    return requests;
}

export function planGraphDocumentMutationReconciliation(
    desired: GraphDocumentDurableCommitRequest[],
    ledger: GraphDocumentGraphMutationLedger | undefined,
    now: number,
): GraphDocumentMutationPlan {
    const desiredIds = new Set(desired.map((request) => request.commitId));
    const activeIds = new Set(
        (ledger?.records || [])
            .filter((record) => record.status === 'committed')
            .map((record) => record.commitId),
    );
    return {
        commits: desired.filter((request) => !activeIds.has(request.commitId)),
        undos: (ledger?.records || [])
            .filter((record) => record.status === 'committed' && !desiredIds.has(record.commitId))
            .map((record) => ({
                schemaVersion: 'phoenix-document-graph-undo/v1',
                commitId: record.commitId,
                undoneAt: now,
            })),
    };
}

export function recordGraphDocumentCommit(
    ledger: GraphDocumentGraphMutationLedger | undefined,
    request: GraphDocumentDurableCommitRequest,
    result: GraphDocumentDurableCommitResult,
    committedAt: number,
): GraphDocumentGraphMutationLedger {
    const records = withoutCommit(ledger, request.commitId);
    records.push({
        id: `document-graph-mutation:${request.commitId}`,
        commitId: request.commitId,
        topologyDiffId: request.topologyDiffId,
        sourceObjectId: request.sourceObjectId,
        receiptId: request.receiptId,
        status: 'committed',
        vertexIds: unique(result.createdVertexIds),
        edgeKeys: unique(result.createdEdgeKeys),
        committedAt,
    });
    return ledgerFor(records);
}

export function recordGraphDocumentUndo(
    ledger: GraphDocumentGraphMutationLedger | undefined,
    request: GraphDocumentDurableUndoRequest,
): GraphDocumentGraphMutationLedger {
    const records = (ledger?.records || []).map((record) => record.commitId === request.commitId
        ? { ...record, status: 'undone' as const, undoneAt: request.undoneAt }
        : record);
    return ledgerFor(records);
}

export function emptyGraphDocumentGraphMutationLedger(): GraphDocumentGraphMutationLedger {
    return ledgerFor([]);
}

function durableRequestFor(
    scopeId: string,
    builtAt: number,
    diff: GraphDocumentTopologyDiff,
    hyperedge: GraphDocumentHyperedge | undefined,
    receipt: GraphDocumentTopologyReceipt | undefined,
    evidenceById: Map<string, EvidenceSpan>,
): GraphDocumentDurableCommitRequest | null {
    if (
        diff.status !== 'pending_commit'
        || !diff.mutationAllowed
        || !diff.topologyCommit
        || !hyperedge
        || hyperedge.status !== 'pending_commit'
        || !receipt?.mutationAllowed
    ) return null;
    const entityRoles = hyperedge.roles.filter((role) => role.targetKind === 'entity');
    if (!entityRoles.length || !hyperedge.evidenceSpanIds.length) return null;
    const commitId = `document-graph-commit:${diff.id}`;
    const factVertexId = `document-fact:${hyperedge.id}`;
    const common = {
        documentCompilerCommitId: commitId,
        scopeId,
        topologyDiffId: diff.id,
        sourceObjectId: hyperedge.provenance.sourceObjectId,
        receiptId: receipt.id,
    };
    const vertices: GraphDocumentDurableVertex[] = [{
        id: factVertexId,
        kind: 'document_fact',
        label: hyperedge.predicate,
        removeOnUndo: true,
        attributes: {
            ...common,
            predicate: hyperedge.predicate,
            sourceKind: hyperedge.sourceKind,
            confidence: hyperedge.confidence,
            noteId: hyperedge.provenance.noteId,
            sourceStart: hyperedge.provenance.sourceStart,
            sourceEnd: hyperedge.provenance.sourceEnd,
            evidenceSpanIds: hyperedge.evidenceSpanIds,
        },
    }];
    for (const role of entityRoles) {
        vertices.push({
            id: role.targetId,
            kind: 'entity',
            label: role.surface || role.targetId,
            removeOnUndo: false,
            attributes: { registeredEntityReference: true },
        });
    }
    for (const evidenceId of unique(hyperedge.evidenceSpanIds)) {
        const span = evidenceById.get(evidenceId);
        if (!span) continue;
        vertices.push({
            id: `document-evidence:${span.id}`,
            kind: 'evidence_span',
            label: compactLabel(span.preview, 120),
            removeOnUndo: true,
            attributes: {
                ...common,
                evidenceSpanId: span.id,
                noteId: span.noteId,
                chunkId: span.chunkId,
                sourceStart: span.start,
                sourceEnd: span.end,
                textHash: span.textHash,
                preview: span.preview,
                confidence: span.confidence.score,
            },
        });
    }
    const edges = roleEdges(factVertexId, entityRoles, common, hyperedge.confidence);
    for (const vertex of vertices) {
        if (vertex.kind !== 'evidence_span') continue;
        edges.push({
            source: factVertexId,
            target: vertex.id,
            edgeType: 'supported_by_evidence_span',
            weight: confidenceWeight(hyperedge.confidence),
            attributes: { ...common, confidence: hyperedge.confidence },
        });
    }
    return {
        schemaVersion: 'phoenix-document-graph-commit/v1',
        commitId,
        scopeId,
        topologyDiffId: diff.id,
        sourceObjectId: hyperedge.provenance.sourceObjectId,
        receiptId: receipt.id,
        builtAt,
        vertices: dedupeVertices(vertices),
        edges,
    };
}

function roleEdges(
    factVertexId: string,
    roles: GraphDocumentHyperedge['roles'],
    common: Record<string, unknown>,
    confidence: number,
): GraphDocumentDurableEdge[] {
    const rolesByTarget = new Map<string, string[]>();
    for (const role of roles) {
        const values = rolesByTarget.get(role.targetId) || [];
        values.push(role.role);
        rolesByTarget.set(role.targetId, values);
    }
    return [...rolesByTarget].map(([target, targetRoles]) => ({
        source: factVertexId,
        target,
        edgeType: 'document_fact_role',
        weight: confidenceWeight(confidence),
        attributes: { ...common, roles: unique(targetRoles), confidence },
    }));
}

function dedupeVertices(vertices: GraphDocumentDurableVertex[]): GraphDocumentDurableVertex[] {
    return [...new Map(vertices.map((vertex) => [vertex.id, vertex])).values()];
}

function withoutCommit(
    ledger: GraphDocumentGraphMutationLedger | undefined,
    commitId: string,
): GraphDocumentGraphMutationRecord[] {
    return (ledger?.records || []).filter((record) => record.commitId !== commitId);
}

function ledgerFor(records: GraphDocumentGraphMutationRecord[]): GraphDocumentGraphMutationLedger {
    const active = records.filter((record) => record.status === 'committed');
    return {
        schemaVersion: 'phoenix-document-graph-mutation-ledger/v1',
        records,
        counters: {
            commits: records.length,
            active: active.length,
            undone: records.length - active.length,
            vertices: active.reduce((sum, record) => sum + record.vertexIds.length, 0),
            edges: active.reduce((sum, record) => sum + record.edgeKeys.length, 0),
        },
    };
}

function confidenceWeight(confidence: number): number {
    return Math.max(1, Math.round(Math.max(0, Math.min(1, confidence)) * 1000));
}

function compactLabel(value: string, limit: number): string {
    const compact = value.replace(/\s+/g, ' ').trim();
    return compact.length <= limit ? compact : `${compact.slice(0, limit - 3)}...`;
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}
