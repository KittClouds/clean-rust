import type {
    GraphIndexRunReceipt,
    GraphInteractiveRunAuthorityReceipt,
    GraphRebuildContentManifest,
    GraphRebuildScopeKind,
    GraphRebuildSnapshot,
    GraphSnapshotAuthorityContract,
    GraphSnapshotAuthorityCounts,
} from './graph-rebuild-snapshot';

export const GRAPH_GENERATION_RECEIPT_SCHEMA = 'phoenix-graph-generation-receipt/v2' as const;
export const GRAPH_GENERATION_UI_SUMMARY_SCHEMA = 'phoenix-graph-generation-ui-summary/v1' as const;
export const GRAPH_GENERATION_RECEIPT_MAX_BYTES = 64 * 1024;
export const GRAPH_GENERATION_UI_SUMMARY_MAX_BYTES = 16 * 1024;

export type GraphGenerationArtifactStatus = 'pending' | 'ready' | 'unavailable';

export interface GraphGenerationArtifactRef {
    schemaVersion: 'phoenix-graph-generation-artifact-ref/v1';
    kind: 'asserted-query' | 'analysis-run' | 'scene-index' | 'review-ledger' | 'mutation-ledger';
    status: GraphGenerationArtifactStatus;
    id?: string;
    digest?: string;
    schema?: string;
    byteLength?: number;
}

export interface GraphGenerationUiSummaryV1 {
    schemaVersion: typeof GRAPH_GENERATION_UI_SUMMARY_SCHEMA;
    snapshotId: string;
    scopeId: string;
    builtAt: number;
    counts: GraphSnapshotAuthorityCounts;
    suggestions: {
        graphAware: number;
        entityLinks: number;
        shadowLinks: number;
        reviewRows: number;
    };
    build: {
        durationMs: number;
        transportMs: number;
        snapshotPersistMs: number;
        nativeRunPersistMs: number;
    };
}

export interface GraphGenerationReceiptV2 {
    schemaVersion: typeof GRAPH_GENERATION_RECEIPT_SCHEMA;
    receiptId: string;
    runReceiptId: string;
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    snapshotId: string;
    inputIdentity: string;
    builtAt: number;
    authority: GraphSnapshotAuthorityContract;
    authorityDigestSha256: string;
    contentManifest: GraphRebuildContentManifest;
    artifacts: {
        assertedQuery: GraphGenerationArtifactRef;
        analysisRun: GraphGenerationArtifactRef;
        sceneIndex: GraphGenerationArtifactRef;
        reviewLedger: GraphGenerationArtifactRef;
        mutationLedger: GraphGenerationArtifactRef;
    };
    uiSummary: GraphGenerationUiSummaryV1;
    candidateEdgesAdmitted: 0;
    topologyWrites: 0;
    releaseAuthorized: boolean;
    digestSha256: string;
}

export interface BuildGraphGenerationReceiptInput {
    snapshot: GraphRebuildSnapshot;
    runReceipt: GraphIndexRunReceipt;
    inputIdentity: string;
    assertedQuery?: GraphGenerationArtifactRef;
    sceneIndex?: GraphGenerationArtifactRef;
}

export async function buildGraphGenerationReceipt(
    input: BuildGraphGenerationReceiptInput,
): Promise<GraphGenerationReceiptV2> {
    const { snapshot, runReceipt, inputIdentity } = input;
    const authority = requiredAuthority(snapshot);
    const contentManifest = requiredContentManifest(snapshot);
    const artifacts = {
        assertedQuery: input.assertedQuery || pendingArtifact('asserted-query'),
        analysisRun: analysisRunArtifact(snapshot.interactiveRunAuthority),
        sceneIndex: input.sceneIndex || pendingArtifact('scene-index'),
        reviewLedger: ledgerArtifact(
            'review-ledger',
            snapshot.reviewAdjudicationCertificate?.document.snapshotId,
            snapshot.reviewAdjudicationCertificate?.schemaVersion,
        ),
        mutationLedger: ledgerArtifact(
            'mutation-ledger',
            snapshot.operatorMutationJournal?.scopeId,
            snapshot.operatorMutationJournal?.schemaVersion,
        ),
    } satisfies GraphGenerationReceiptV2['artifacts'];
    const authorityDigestSha256 = await sha256Canonical(authority);
    const uiSummary = graphGenerationUiSummary(snapshot);
    assertBoundedJson('Graph generation UI summary', uiSummary, GRAPH_GENERATION_UI_SUMMARY_MAX_BYTES);
    const unsigned = {
        schemaVersion: GRAPH_GENERATION_RECEIPT_SCHEMA,
        receiptId: `graph-generation:${snapshot.scopeId}:${snapshot.id}`,
        runReceiptId: runReceipt.id,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        snapshotId: snapshot.id,
        inputIdentity,
        builtAt: snapshot.builtAt,
        authority,
        authorityDigestSha256,
        contentManifest,
        artifacts,
        uiSummary,
        candidateEdgesAdmitted: 0 as const,
        topologyWrites: 0 as const,
        releaseAuthorized: graphGenerationArtifactsReady(artifacts),
    };
    const receipt: GraphGenerationReceiptV2 = {
        ...unsigned,
        digestSha256: await sha256Canonical(unsigned),
    };
    await assertGraphGenerationReceipt(receipt);
    return receipt;
}

export function graphGenerationUiSummary(snapshot: GraphRebuildSnapshot): GraphGenerationUiSummaryV1 {
    const authority = requiredAuthority(snapshot);
    const timings = snapshot.buildTimings;
    return {
        schemaVersion: GRAPH_GENERATION_UI_SUMMARY_SCHEMA,
        snapshotId: snapshot.id,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        counts: cloneAuthorityCounts(authority.counts),
        suggestions: {
            graphAware: snapshot.counters.graphAwareLinkSuggestions || snapshot.graphAwareLinkSuggestions?.length || 0,
            entityLinks: snapshot.counters.entityLinkSuggestions || snapshot.entityLinkSuggestions?.length || 0,
            shadowLinks: snapshot.counters.shadowLinkSuggestions || snapshot.shadowLinkSuggestions?.length || 0,
            reviewRows: snapshot.documentReviewSummary?.rows.length || 0,
        },
        build: {
            durationMs: finiteNumber(timings?.totalMs),
            transportMs: 0,
            snapshotPersistMs: finiteNumber(timings?.snapshotPersistMs),
            nativeRunPersistMs: finiteNumber(timings?.nativeGraphRunPersistMs),
        },
    };
}

export async function assertGraphGenerationReceipt(
    receipt: GraphGenerationReceiptV2,
): Promise<void> {
    if (receipt.schemaVersion !== GRAPH_GENERATION_RECEIPT_SCHEMA) {
        throw new Error(`Unsupported graph generation receipt: ${receipt.schemaVersion}`);
    }
    if (!receipt.receiptId || !receipt.runReceiptId || !receipt.scopeId || !receipt.snapshotId) {
        throw new Error('Graph generation receipt identity is incomplete.');
    }
    if (!receipt.inputIdentity
        || receipt.receiptId !== `graph-generation:${receipt.scopeId}:${receipt.snapshotId}`) {
        throw new Error('Graph generation receipt identity binding drift.');
    }
    if (!isSha256(receipt.authorityDigestSha256) || !isSha256(receipt.digestSha256)) {
        throw new Error('Graph generation receipt requires canonical SHA-256 digests.');
    }
    if (receipt.authority.scopeId !== receipt.scopeId
        || receipt.authority.snapshotId !== receipt.snapshotId
        || receipt.contentManifest.scopeId !== receipt.scopeId
        || receipt.contentManifest.snapshotId !== receipt.snapshotId) {
        throw new Error('Graph generation receipt authority identity drift.');
    }
    if (receipt.candidateEdgesAdmitted !== 0 || receipt.topologyWrites !== 0) {
        throw new Error('Graph generation receipt violates asserted read-only authority.');
    }
    assertArtifact('assertedQuery', 'asserted-query', receipt.artifacts.assertedQuery, true);
    assertArtifact('analysisRun', 'analysis-run', receipt.artifacts.analysisRun, true);
    assertArtifact('sceneIndex', 'scene-index', receipt.artifacts.sceneIndex, true);
    assertArtifact('reviewLedger', 'review-ledger', receipt.artifacts.reviewLedger, false);
    assertArtifact('mutationLedger', 'mutation-ledger', receipt.artifacts.mutationLedger, false);
    if (receipt.uiSummary.snapshotId !== receipt.snapshotId
        || receipt.uiSummary.scopeId !== receipt.scopeId
        || JSON.stringify(receipt.uiSummary.counts) !== JSON.stringify(receipt.authority.counts)) {
        throw new Error('Graph generation UI summary authority drift.');
    }
    const expectedAuthorityDigest = await sha256Canonical(receipt.authority);
    if (expectedAuthorityDigest !== receipt.authorityDigestSha256) {
        throw new Error('Graph generation authority digest drift.');
    }
    const { digestSha256: _digest, ...unsigned } = receipt;
    if (await sha256Canonical(unsigned) !== receipt.digestSha256) {
        throw new Error('Graph generation receipt digest drift.');
    }
    if (receipt.releaseAuthorized !== graphGenerationArtifactsReady(receipt.artifacts)) {
        throw new Error('Graph generation release authorization drift.');
    }
    assertBoundedJson('Graph generation UI summary', receipt.uiSummary, GRAPH_GENERATION_UI_SUMMARY_MAX_BYTES);
    assertBoundedJson('Graph generation receipt', receipt, GRAPH_GENERATION_RECEIPT_MAX_BYTES);
}

export function graphGenerationArtifactsReady(
    artifacts: GraphGenerationReceiptV2['artifacts'],
): boolean {
    return artifacts.assertedQuery.status === 'ready'
        && artifacts.analysisRun.status === 'ready'
        && artifacts.sceneIndex.status === 'ready';
}

export async function withGraphGenerationArtifact(
    receipt: GraphGenerationReceiptV2,
    key: keyof GraphGenerationReceiptV2['artifacts'],
    artifact: GraphGenerationArtifactRef,
): Promise<GraphGenerationReceiptV2> {
    await assertGraphGenerationReceipt(receipt);
    if (receipt.artifacts[key].kind !== artifact.kind) {
        throw new Error(`Graph generation artifact kind drift for ${key}.`);
    }
    const artifacts = { ...receipt.artifacts, [key]: { ...artifact } };
    const unsigned = {
        ...receipt,
        artifacts,
        releaseAuthorized: graphGenerationArtifactsReady(artifacts),
    };
    const { digestSha256: _digest, ...payload } = unsigned;
    const updated: GraphGenerationReceiptV2 = {
        ...payload,
        digestSha256: await sha256Canonical(payload),
    };
    await assertGraphGenerationReceipt(updated);
    return updated;
}

export function pendingArtifact(kind: GraphGenerationArtifactRef['kind']): GraphGenerationArtifactRef {
    return { schemaVersion: 'phoenix-graph-generation-artifact-ref/v1', kind, status: 'pending' };
}

function analysisRunArtifact(
    receipt: GraphInteractiveRunAuthorityReceipt | undefined,
): GraphGenerationArtifactRef {
    if (!receipt) return pendingArtifact('analysis-run');
    return {
        schemaVersion: 'phoenix-graph-generation-artifact-ref/v1',
        kind: 'analysis-run',
        status: 'ready',
        id: receipt.durable.runHandle,
        digest: receipt.durable.manifestId,
        schema: receipt.durable.schemaVersion,
        byteLength: receipt.durable.compressedBytesWritten,
    };
}

function ledgerArtifact(
    kind: 'review-ledger' | 'mutation-ledger',
    id?: string,
    schema?: string,
): GraphGenerationArtifactRef {
    return id && schema
        ? { schemaVersion: 'phoenix-graph-generation-artifact-ref/v1', kind, status: 'ready', id, digest: id, schema }
        : { schemaVersion: 'phoenix-graph-generation-artifact-ref/v1', kind, status: 'unavailable' };
}

function requiredAuthority(snapshot: GraphRebuildSnapshot): GraphSnapshotAuthorityContract {
    if (!snapshot.authorityContract) throw new Error(`Graph generation ${snapshot.id} is not authority-sealed.`);
    return snapshot.authorityContract;
}

function requiredContentManifest(snapshot: GraphRebuildSnapshot): GraphRebuildContentManifest {
    if (!snapshot.contentManifest) throw new Error(`Graph generation ${snapshot.id} has no content manifest.`);
    return snapshot.contentManifest;
}

function cloneAuthorityCounts(counts: GraphSnapshotAuthorityCounts): GraphSnapshotAuthorityCounts {
    return { ...counts, packetFamilies: { ...counts.packetFamilies } };
}

function finiteNumber(value: number | undefined): number {
    return Number.isFinite(value) ? Math.max(0, value!) : 0;
}

function assertBoundedJson(label: string, value: unknown, maxBytes: number): void {
    const bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength;
    if (bytes > maxBytes) throw new Error(`${label} exceeds ${maxBytes} bytes (${bytes}).`);
}

async function sha256Canonical(value: unknown): Promise<string> {
    const bytes = new TextEncoder().encode(canonicalJson(value));
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return `sha256-${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

function canonicalJson(value: unknown): string {
    if (value === null || typeof value !== 'object') return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(',')}}`;
}

function isSha256(value: string): boolean {
    return /^sha256-[0-9a-f]{64}$/.test(value);
}

function assertArtifact(
    key: string,
    kind: GraphGenerationArtifactRef['kind'],
    artifact: GraphGenerationArtifactRef,
    required: boolean,
): void {
    if (artifact?.schemaVersion !== 'phoenix-graph-generation-artifact-ref/v1'
        || artifact.kind !== kind
        || !['pending', 'ready', 'unavailable'].includes(artifact.status)) {
        throw new Error(`Graph generation artifact ${key} is invalid.`);
    }
    if (required && artifact.status === 'unavailable') {
        throw new Error(`Graph generation artifact ${key} cannot be unavailable.`);
    }
    if (artifact.status === 'ready' && (!artifact.id || !artifact.digest || !artifact.schema)) {
        throw new Error(`Graph generation artifact ${key} has an incomplete ready receipt.`);
    }
}
