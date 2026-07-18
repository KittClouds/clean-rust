import {
    isGraphPromotionVerdictCertificate,
    type GraphPromotionTruthAtom,
    type GraphPromotionVerdictRow,
} from './graph-promotion-verdict';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export const GRAPH_REVIEWED_PROMOTION_POLICY =
    'explicit_human_review_evidence_backed_native_commit_required' as const;
export const GRAPH_PROMOTION_REVIEW_SCHEMA_VERSION =
    'phoenix-graph-promotion-review/v1' as const;
export const GRAPH_PROMOTION_COMMIT_AUTHORIZATION_SCHEMA_VERSION =
    'phoenix-graph-promotion-commit-authorization/v1' as const;

export type GraphPromotionReviewDecision = 'approve' | 'reject';

export interface GraphPromotionReviewInput {
    reviewerId: string;
    decision: GraphPromotionReviewDecision;
    rationale: string;
    reviewedAt: number;
    explicitUserIntent: true;
}

export interface GraphPromotionReviewReceipt {
    schemaVersion: typeof GRAPH_PROMOTION_REVIEW_SCHEMA_VERSION;
    id: string;
    policy: typeof GRAPH_REVIEWED_PROMOTION_POLICY;
    scopeId: string;
    sourceSnapshotId: string;
    sourceSnapshotBuiltAt: number;
    sourceFingerprint: string;
    verdictRowId: string;
    proposalReceiptId: string;
    proposalId: string;
    candidateFingerprint: string;
    reviewerId: string;
    reviewerKind: 'human';
    decision: GraphPromotionReviewDecision;
    rationale: string;
    reviewedAt: number;
    explicitUserIntent: true;
    automated: false;
    evidenceRefs: string[];
    evidenceFingerprint: string;
    mutationAllowed: false;
    invariant: 'review_receipt_is_not_a_graph_truth_commit';
}

export interface GraphPromotionCommitAuthorization {
    schemaVersion: typeof GRAPH_PROMOTION_COMMIT_AUTHORIZATION_SCHEMA_VERSION;
    id: string;
    policy: typeof GRAPH_REVIEWED_PROMOTION_POLICY;
    scopeId: string;
    sourceSnapshotId: string;
    sourceSnapshotBuiltAt: number;
    sourceFingerprint: string;
    reviewReceiptId: string;
    verdictRowId: string;
    proposalReceiptId: string;
    proposalId: string;
    operation: 'assert' | 'supersede';
    predecessorCommitId?: string;
    atom: GraphPromotionTruthAtom;
    evidenceRefs: string[];
    evidenceFingerprint: string;
    receiptIds: string[];
    nativeIdempotency: {
        algorithm: 'blake3';
        domain: 'phoenix-reviewed-promotion-commit/v1';
        preimageParts: string[];
    };
    mutationAllowed: true;
    nativeCommitRequired: true;
    snapshotMutationAllowed: false;
    rollback: {
        operation: 'revert';
        availableAfterCommit: true;
        nativeCommitIdRequired: true;
        sourceAuthorizationId: string;
    };
}

export function recordGraphPromotionReview(
    snapshot: GraphRebuildSnapshot,
    verdictRowId: string,
    input: GraphPromotionReviewInput,
): GraphPromotionReviewReceipt {
    const row = requireVerdictRow(snapshot, verdictRowId);
    requireReviewInput(input);
    const evidenceRefs = normalizedEvidenceRefs(row.evidenceRefs);
    const candidateFingerprint = fingerprintVerdictRow(row);
    const sourceFingerprint = fingerprintPromotionSource(snapshot, row);
    const evidenceFingerprint = fingerprintValues('evidence', evidenceRefs);
    const id = reviewReceiptId(snapshot, row, sourceFingerprint, candidateFingerprint, input);
    return {
        schemaVersion: GRAPH_PROMOTION_REVIEW_SCHEMA_VERSION,
        id,
        policy: GRAPH_REVIEWED_PROMOTION_POLICY,
        scopeId: snapshot.scopeId,
        sourceSnapshotId: snapshot.id,
        sourceSnapshotBuiltAt: snapshot.builtAt,
        sourceFingerprint,
        verdictRowId: row.id,
        proposalReceiptId: row.receiptId,
        proposalId: row.proposalId,
        candidateFingerprint,
        reviewerId: input.reviewerId.trim(),
        reviewerKind: 'human',
        decision: input.decision,
        rationale: input.rationale.trim(),
        reviewedAt: input.reviewedAt,
        explicitUserIntent: true,
        automated: false,
        evidenceRefs,
        evidenceFingerprint,
        mutationAllowed: false,
        invariant: 'review_receipt_is_not_a_graph_truth_commit',
    };
}

export function authorizeReviewedGraphPromotion(
    snapshot: GraphRebuildSnapshot,
    review: GraphPromotionReviewReceipt,
): GraphPromotionCommitAuthorization {
    const row = requireVerdictRow(snapshot, review.verdictRowId);
    assertReviewBinding(snapshot, row, review);
    assertPromotableVerdict(row);
    assertEvidenceBacked(snapshot, row.evidenceRefs);
    assertAtomEndpoints(snapshot, row.atom);

    const operation = row.applyPlan.operation;
    if (operation !== 'assert' && operation !== 'supersede') {
        throw new Error('Reviewed promotion has no assert or supersede apply operation.');
    }
    if (operation === 'supersede' && !clean(row.applyPlan.predecessorCommitId)) {
        throw new Error('Reviewed supersede promotion is missing its predecessor commit.');
    }
    if (
        row.rollbackPlan.operation !== 'revert'
        || !row.rollbackPlan.availableAfterCommit
    ) {
        throw new Error('Reviewed promotion is missing an after-commit revert plan.');
    }

    const evidenceRefs = normalizedEvidenceRefs(row.evidenceRefs);
    const evidenceFingerprint = fingerprintValues('evidence', evidenceRefs);
    const authorizationId = `promotion-authorization:${fingerprintValues('authorization', [
        review.id,
        row.id,
        operation,
        clean(row.applyPlan.predecessorCommitId),
        atomIdentity(row.atom),
        evidenceFingerprint,
    ])}`;
    return {
        schemaVersion: GRAPH_PROMOTION_COMMIT_AUTHORIZATION_SCHEMA_VERSION,
        id: authorizationId,
        policy: GRAPH_REVIEWED_PROMOTION_POLICY,
        scopeId: snapshot.scopeId,
        sourceSnapshotId: snapshot.id,
        sourceSnapshotBuiltAt: snapshot.builtAt,
        sourceFingerprint: review.sourceFingerprint,
        reviewReceiptId: review.id,
        verdictRowId: row.id,
        proposalReceiptId: row.receiptId,
        proposalId: row.proposalId,
        operation,
        predecessorCommitId: clean(row.applyPlan.predecessorCommitId) || undefined,
        atom: cloneAtom(row.atom!),
        evidenceRefs,
        evidenceFingerprint,
        receiptIds: [row.receiptId, row.id, review.id],
        nativeIdempotency: {
            algorithm: 'blake3',
            domain: 'phoenix-reviewed-promotion-commit/v1',
            preimageParts: [
                snapshot.scopeId,
                row.receiptId,
                row.proposalId,
                review.id,
                atomIdentity(row.atom),
                evidenceFingerprint,
            ],
        },
        mutationAllowed: true,
        nativeCommitRequired: true,
        snapshotMutationAllowed: false,
        rollback: {
            operation: 'revert',
            availableAfterCommit: true,
            nativeCommitIdRequired: true,
            sourceAuthorizationId: authorizationId,
        },
    };
}

function requireVerdictRow(
    snapshot: GraphRebuildSnapshot,
    verdictRowId: string,
): GraphPromotionVerdictRow {
    const certificate = snapshot.promotionVerdictCertificate;
    if (!isGraphPromotionVerdictCertificate(certificate) || !certificate.noTopologyWrites) {
        throw new Error('Reviewed promotion requires a valid no-write native verdict certificate.');
    }
    const row = certificate.rows.find((candidate) => candidate.id === verdictRowId);
    if (!row) throw new Error(`Promotion verdict row is missing: ${verdictRowId}`);
    return row;
}

function requireReviewInput(input: GraphPromotionReviewInput): void {
    if (input.explicitUserIntent !== true) {
        throw new Error('Promotion review requires explicit user intent.');
    }
    if (!clean(input.reviewerId)) throw new Error('Promotion review requires a human reviewer identity.');
    if (!clean(input.rationale)) throw new Error('Promotion review requires a rationale.');
    if (!Number.isSafeInteger(input.reviewedAt) || input.reviewedAt < 0) {
        throw new Error('Promotion review timestamp is invalid.');
    }
}

function assertReviewBinding(
    snapshot: GraphRebuildSnapshot,
    row: GraphPromotionVerdictRow,
    review: GraphPromotionReviewReceipt,
): void {
    const issues: string[] = [];
    if (review.schemaVersion !== GRAPH_PROMOTION_REVIEW_SCHEMA_VERSION) issues.push('schema');
    if (review.policy !== GRAPH_REVIEWED_PROMOTION_POLICY) issues.push('policy');
    if (review.scopeId !== snapshot.scopeId) issues.push('scope');
    if (review.sourceSnapshotId !== snapshot.id) issues.push('snapshot');
    if (review.sourceSnapshotBuiltAt !== snapshot.builtAt) issues.push('snapshot timestamp');
    if (review.sourceFingerprint !== fingerprintPromotionSource(snapshot, row)) issues.push('source fingerprint');
    if (review.verdictRowId !== row.id) issues.push('verdict row');
    if (review.proposalReceiptId !== row.receiptId) issues.push('proposal receipt');
    if (review.proposalId !== row.proposalId) issues.push('proposal');
    if (review.candidateFingerprint !== fingerprintVerdictRow(row)) issues.push('candidate fingerprint');
    if (review.reviewerKind !== 'human' || !clean(review.reviewerId)) issues.push('human reviewer');
    if (!clean(review.rationale)) issues.push('review rationale');
    if (!Number.isSafeInteger(review.reviewedAt) || review.reviewedAt < 0) issues.push('review timestamp');
    if (review.decision !== 'approve') issues.push('approval');
    if (review.explicitUserIntent !== true || review.automated !== false) issues.push('explicit intent');
    if (review.mutationAllowed !== false) issues.push('review mutation authority');
    if (review.invariant !== 'review_receipt_is_not_a_graph_truth_commit') issues.push('review invariant');
    const evidenceRefs = normalizedEvidenceRefs(row.evidenceRefs);
    if (review.evidenceFingerprint !== fingerprintValues('evidence', evidenceRefs)) issues.push('evidence fingerprint');
    if (!Array.isArray(review.evidenceRefs) || !sameValues(review.evidenceRefs, evidenceRefs)) issues.push('evidence refs');
    if (review.id !== reviewReceiptId(snapshot, row, review.sourceFingerprint, review.candidateFingerprint, review)) {
        issues.push('receipt identity');
    }
    if (issues.length) throw new Error(`Promotion review receipt is stale or invalid: ${issues.join(', ')}.`);
}

function assertPromotableVerdict(row: GraphPromotionVerdictRow): void {
    if (row.status !== 'acceptable') throw new Error(`Promotion verdict is not acceptable: ${row.status}.`);
    if (row.commitId) throw new Error('Promotion verdict is already associated with a commit.');
    const blocked = row.gates.filter((gate) => gate.status === 'block');
    if (blocked.length) throw new Error(`Promotion verdict contains blocked gates: ${blocked.map((gate) => gate.kind).join(', ')}.`);
    const receiptGate = row.gates.find((gate) => gate.kind === 'receipt');
    const evidenceGate = row.gates.find((gate) => gate.kind === 'evidence');
    if (receiptGate?.status !== 'pass') throw new Error('Promotion receipt gate did not pass.');
    if (evidenceGate?.status !== 'pass') throw new Error('Promotion evidence gate did not pass.');
    if (!row.evidenceRefs.length || row.witnessCount < 1) {
        throw new Error('Promotion has no evidence witnesses.');
    }
    if (!row.atom) throw new Error('Promotion verdict has no graph truth atom.');
}

function assertEvidenceBacked(snapshot: GraphRebuildSnapshot, refs: string[]): void {
    const authoritativeEvidence = new Set([
        ...snapshot.chunks.map((row) => row.id),
        ...snapshot.entityAnchors.map((row) => row.id),
        ...(snapshot.documentSidecarSummary?.evidenceSpans || []).map((row) => row.id),
    ]);
    const evidenceRefs = normalizedEvidenceRefs(refs);
    const missing = evidenceRefs.filter((id) => !authoritativeEvidence.has(id));
    if (!evidenceRefs.length || missing.length) {
        throw new Error(`Promotion evidence does not resolve to authoritative rows: ${missing.join(', ') || 'empty'}.`);
    }
}

function assertAtomEndpoints(snapshot: GraphRebuildSnapshot, atom: GraphPromotionTruthAtom | undefined): void {
    if (!atom || atom.kind !== 'edge') throw new Error('Only evidence-backed edge promotion is supported.');
    if (!clean(atom.source_id) || !clean(atom.target_id) || atom.source_id === atom.target_id) {
        throw new Error('Promotion edge endpoints are invalid.');
    }
    const identities = new Set(snapshot.nodes.flatMap((node) => [node.id, node.entityId]));
    const missing = [atom.source_id, atom.target_id].filter((id) => !identities.has(id));
    if (missing.length) throw new Error(`Promotion edge endpoints are not asserted identities: ${missing.join(', ')}.`);
}

function fingerprintPromotionSource(snapshot: GraphRebuildSnapshot, row: GraphPromotionVerdictRow): string {
    return fingerprintValues('source', [
        snapshot.id,
        snapshot.scopeId,
        String(snapshot.builtAt),
        snapshot.evidenceTargetRegistry?.identityHash || '',
        fingerprintVerdictRow(row),
    ]);
}

function reviewReceiptId(
    snapshot: GraphRebuildSnapshot,
    row: GraphPromotionVerdictRow,
    sourceFingerprint: string,
    candidateFingerprint: string,
    input: Pick<GraphPromotionReviewReceipt, 'reviewerId' | 'decision' | 'rationale' | 'reviewedAt'>,
): string {
    return `promotion-review:${fingerprintValues('review', [
        snapshot.scopeId,
        snapshot.id,
        sourceFingerprint,
        row.id,
        candidateFingerprint,
        clean(input.reviewerId),
        input.decision,
        clean(input.rationale),
        String(input.reviewedAt),
    ])}`;
}

function fingerprintVerdictRow(row: GraphPromotionVerdictRow): string {
    return fingerprintValues('candidate', [
        row.id,
        row.receiptId,
        row.proposalId,
        row.status,
        row.candidateStatus,
        atomIdentity(row.atom),
        ...normalizedEvidenceRefs(row.evidenceRefs),
        ...row.gates.map((gate) => `${gate.kind}:${gate.status}`),
    ]);
}

function atomIdentity(atom: GraphPromotionTruthAtom | undefined): string {
    if (!atom) return '';
    return atom.kind === 'edge'
        ? `edge:${atom.source_id}:${atom.target_id}:${atom.edge_type}`
        : `vertex:${atom.vertex_id}`;
}

function cloneAtom(atom: GraphPromotionTruthAtom): GraphPromotionTruthAtom {
    return atom.kind === 'edge' ? { ...atom } : { ...atom };
}

function normalizedEvidenceRefs(values: string[]): string[] {
    return [...new Set(values.map(clean).filter(Boolean))].sort();
}

function sameValues(left: string[], right: string[]): boolean {
    return left.length === right.length && left.every((value, index) => value === right[index]);
}

function clean(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function fingerprintValues(domain: string, values: unknown[]): string {
    let hash = 0x811c9dc5;
    for (const value of [domain, ...values]) {
        const normalized = typeof value === 'string' ? value : String(value ?? '');
        const framed = `${normalized.length}\0${normalized}`;
        for (let index = 0; index < framed.length; index += 1) {
            hash ^= framed.charCodeAt(index);
            hash = Math.imul(hash, 0x01000193) >>> 0;
        }
    }
    return `fnv32-${hash.toString(16).padStart(8, '0')}`;
}
