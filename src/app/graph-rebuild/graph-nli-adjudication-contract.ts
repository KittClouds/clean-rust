import type { GraphRebuildRelationshipHint } from './graph-rebuild-snapshot';

export type PhoenixModelLane = 'gliclass' | 'modernBertNli' | 'hybrid';

export type PhoenixModelRole =
    | 'evidenceClaimAdjudication'
    | 'fastLabelRouting'
    | 'relationFrameClassification'
    | 'hallucinationTriage'
    | 'canonFactAdjudication'
    | 'humanReviewTriage';

export type NliClaimDecisionKind = 'supported' | 'contradicted' | 'unknown';

export interface ClassificationVote {
    source: PhoenixModelLane;
    role: PhoenixModelRole;
    label: string;
    scoreMillis: number;
    rationale?: string | null;
}

export interface NliScores {
    contradiction: number;
    entailment: number;
    neutral: number;
}

export interface NliClaimVote {
    source: 'modernBertNli';
    role: PhoenixModelRole;
    decision: NliClaimDecisionKind;
    scores?: NliScores;
    entailmentMillis?: number;
    contradictionMillis?: number;
    neutralMillis?: number;
    confidenceMillis: number;
    rationale?: string;
}

export interface NliClaimAdjudication {
    schemaVersion?: string;
    claimId?: string;
    evidenceId?: string;
    sourceId?: string;
    targetId?: string;
    sourceEntityId?: string;
    targetEntityId?: string;
    edgeType?: string;
    relationType?: string;
    purpose?: string;
    nliVote: NliClaimVote;
    classificationVote?: ClassificationVote | null;
    reviewPriorityMillis?: number;
    needsHumanReview?: boolean;
    evidenceRefs?: string[];
    receipts?: string[];
}

const NLI_DECISIONS = new Set<NliClaimDecisionKind>([
    'supported',
    'contradicted',
    'unknown',
]);

const MODEL_LANES = new Set<PhoenixModelLane>([
    'gliclass',
    'modernBertNli',
    'hybrid',
]);

const MODEL_ROLES = new Set<PhoenixModelRole>([
    'evidenceClaimAdjudication',
    'fastLabelRouting',
    'relationFrameClassification',
    'hallucinationTriage',
    'canonFactAdjudication',
    'humanReviewTriage',
]);

export function isNliClaimAdjudication(value: unknown): value is NliClaimAdjudication {
    const record = objectRecord(value);
    if (!record) return false;
    const nliVote = voteRecord(record, 'nliVote', 'nli_vote');
    if (!isNliClaimVote(nliVote)) return false;
    const classificationVote = voteRecord(record, 'classificationVote', 'classification_vote');
    return !classificationVote || isClassificationVote(classificationVote);
}

export function isNliClaimVote(value: unknown): value is NliClaimVote {
    const record = objectRecord(value);
    if (!record) return false;
    const source = stringField(record, 'source');
    const role = stringField(record, 'role');
    const decision = stringField(record, 'decision');
    return source === 'modernBertNli'
        && MODEL_ROLES.has(role as PhoenixModelRole)
        && NLI_DECISIONS.has(decision as NliClaimDecisionKind)
        && numberField(record, 'confidenceMillis') >= 0;
}

export function isClassificationVote(value: unknown): value is ClassificationVote {
    const record = objectRecord(value);
    if (!record) return false;
    const source = stringField(record, 'source');
    const role = stringField(record, 'role');
    const label = stringField(record, 'label');
    return MODEL_LANES.has(source as PhoenixModelLane)
        && MODEL_ROLES.has(role as PhoenixModelRole)
        && !!label
        && numberField(record, 'scoreMillis') >= 0;
}

export function relationshipHintsFromNliResult(rawResult: unknown): GraphRebuildRelationshipHint[] {
    return nliRows(rawResult)
        .map(relationshipHintFromNliAdjudication)
        .filter((row): row is GraphRebuildRelationshipHint => !!row);
}

export function relationshipHintFromNliAdjudication(
    adjudication: unknown,
): GraphRebuildRelationshipHint | null {
    if (!isNliClaimAdjudication(adjudication)) return null;
    const record = adjudication as unknown as Record<string, unknown>;
    const sourceId = stringField(record, 'sourceId', 'source_id')
        || stringField(record, 'sourceEntityId', 'source_entity_id');
    const targetId = stringField(record, 'targetId', 'target_id')
        || stringField(record, 'targetEntityId', 'target_entity_id');
    if (!sourceId || !targetId) return null;

    const nliVote = voteRecord(record, 'nliVote', 'nli_vote') as Record<string, unknown>;
    const classificationVote = voteRecord(record, 'classificationVote', 'classification_vote');
    const decision = stringField(nliVote, 'decision') as NliClaimDecisionKind;
    const confidenceMillis = numberField(nliVote, 'confidenceMillis');

    return {
        sourceId,
        targetId,
        relationType: stringField(record, 'edgeType', 'edge_type')
            || stringField(record, 'relationType', 'relation_type')
            || undefined,
        status: nliDecisionToRelationshipStatus(decision),
        confidence: clamp01(confidenceMillis / 1000),
        source: 'nli:modernbert',
        evidence: compactStrings([
            evidenceRecordField(record, 'judgmentId', 'judgment_id', 'judgment'),
            evidenceRecordField(record, 'claimId', 'claim_id', 'claim'),
            evidenceRecordField(record, 'evidenceId', 'evidence_id', 'evidence'),
            ...evidenceRecordArray(record, 'receipts', 'receipts', 'receipt'),
            ...evidenceRecordArray(record, 'evidenceRefs', 'evidence_refs', 'evidence_ref'),
            `nli_decision:${decision}`,
            evidenceField(nliVote, 'source', 'nli_source'),
            evidenceField(nliVote, 'role', 'nli_role'),
            evidenceMillis(nliVote, 'confidenceMillis', 'nli_confidence_millis'),
            evidenceMillis(nliVote, 'entailmentMillis', 'nli_entailment_millis'),
            evidenceMillis(nliVote, 'contradictionMillis', 'nli_contradiction_millis'),
            evidenceMillis(nliVote, 'neutralMillis', 'nli_neutral_millis'),
            evidenceField(classificationVote, 'source', 'classification_source'),
            evidenceField(classificationVote, 'role', 'classification_role'),
            evidenceField(classificationVote, 'label', 'classification_label'),
            evidenceMillis(classificationVote, 'scoreMillis', 'classification_score_millis'),
        ]),
    };
}

export function nliDecisionToRelationshipStatus(
    decision: NliClaimDecisionKind,
): GraphRebuildRelationshipHint['status'] {
    if (decision === 'supported') return 'accepted';
    if (decision === 'contradicted') return 'rejected';
    return 'review';
}

export function nliDecisionRequiresReviewVisibility(decision: NliClaimDecisionKind): boolean {
    return decision === 'contradicted' || decision === 'unknown';
}

function nliRows(rawResult: unknown): unknown[] {
    return [
        ...arrayField(rawResult, 'adjudications'),
        ...arrayField(rawResult, 'judgments'),
        ...arrayField(rawResult, 'results'),
    ];
}

function arrayField(value: unknown, key: string): unknown[] {
    return value && typeof value === 'object' && Array.isArray((value as Record<string, unknown>)[key])
        ? ((value as Record<string, unknown>)[key] as unknown[])
        : [];
}

function voteRecord(
    record: Record<string, unknown>,
    primary: string,
    fallback: string,
): Record<string, unknown> | null {
    return objectRecord(record[primary] ?? record[fallback]);
}

function objectRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function stringField(record: Record<string, unknown>, primary: string, fallback?: string): string {
    const value = record[primary] ?? (fallback ? record[fallback] : undefined);
    return typeof value === 'string' ? value : '';
}

function numberField(record: Record<string, unknown>, key: string): number {
    const value = record[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : -1;
}

function evidenceField(record: Record<string, unknown> | null, key: string, label: string): string {
    if (!record) return '';
    const value = stringField(record, key);
    return value ? `${label}:${value}` : '';
}

function evidenceRecordField(
    record: Record<string, unknown>,
    primary: string,
    fallback: string,
    label: string,
): string {
    const value = stringField(record, primary, fallback);
    return value ? `${label}:${value}` : '';
}

function evidenceRecordArray(
    record: Record<string, unknown>,
    primary: string,
    fallback: string,
    label: string,
): string[] {
    const value = record[primary] ?? record[fallback];
    return Array.isArray(value)
        ? value
            .filter((row): row is string => typeof row === 'string' && !!row.trim())
            .map((row) => `${label}:${row.trim()}`)
        : [];
}

function evidenceMillis(record: Record<string, unknown> | null, key: string, label: string): string {
    if (!record) return '';
    const value = numberField(record, key);
    return value >= 0 ? `${label}:${Math.round(value)}` : '';
}

function compactStrings(values: string[]): string[] {
    return values.filter((value) => !!value);
}

function clamp01(value: number): number {
    return Math.max(0, Math.min(1, value));
}
