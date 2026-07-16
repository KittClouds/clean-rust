import type {
    GraphRebuildChunkSemanticBridge,
    GraphRebuildChunkSemanticBridgeType,
} from './graph-rebuild-snapshot';

export interface GraphRebuildChunkSemanticBridgeFalsePositiveAudit {
    total: number;
    reviewedRows: number;
    sameEntityOnlySuspectCount: number;
    opaqueCueRowCount: number;
    substantiveCueRowCount: number;
    byType: Record<string, {
        total: number;
        sameEntityOnlySuspects: number;
        opaqueCueRows: number;
        substantiveCueRows: number;
        weakestConfidence: number;
        strongestConfidence: number;
    }>;
    topRows: GraphRebuildChunkSemanticBridgeAuditRow[];
    weakRowsByType: Record<string, GraphRebuildChunkSemanticBridgeAuditRow[]>;
    suspectRows: GraphRebuildChunkSemanticBridgeAuditRow[];
}

export interface GraphRebuildChunkSemanticBridgeAuditRow {
    id: string;
    bridgeType: GraphRebuildChunkSemanticBridgeType;
    confidence: number;
    sourceChunkId: string;
    targetChunkId: string;
    claim: string;
    semanticVerbs: string[];
    sourceCue?: string;
    targetCue?: string;
    supportingEntityCount: number;
    cueStrength: 'substantive' | 'rationale_only' | 'cue_only' | 'opaque';
    falsePositiveRisk: 'low' | 'medium' | 'high';
    sameEntityOnlySuspect: boolean;
    reasons: string[];
}

const DEFAULT_TOP_LIMIT = 18;
const DEFAULT_WEAK_PER_TYPE = 4;
const OPAQUE_CUES = new Set([
    'activity',
    'arrival_event',
    'authority_chain',
    'authority_chain_event',
    'dialogue_event',
    'evidence_block',
    'evidence_packet_event',
    'positioning_event',
    'process_event',
    'state',
    'transition',
    ' is ',
    ' was ',
    ' are ',
    ' were ',
    ' has ',
    ' had ',
]);

const SUBSTANTIVE_RATIONALE_PREFIXES = [
    'causal_event_edge_seed',
    'causal_language_spans_chunks',
    'evidence_or_documentation_reframes_prior_chunk',
    'later_chunk_changes_prior_state',
    'motif:',
    'relationship_cue_with_shared_participants',
    'route_or_threshold_cue_spans_chunks',
    'setup_cue_plus_later_payoff_cue',
    'temporal_event_edge_route_seed',
];

const OPAQUE_RATIONALES = new Set([
    'same_frame_or_event_type_with_shared_participants',
    'temporal_event_edge_same_event_type',
]);

export function auditChunkSemanticBridgeFalsePositives(
    bridges: GraphRebuildChunkSemanticBridge[],
    options: { topLimit?: number; weakPerType?: number } = {},
): GraphRebuildChunkSemanticBridgeFalsePositiveAudit {
    const topLimit = options.topLimit ?? DEFAULT_TOP_LIMIT;
    const weakPerType = options.weakPerType ?? DEFAULT_WEAK_PER_TYPE;
    const allRows = bridges.map(auditBridge);
    const topRows = [...allRows]
        .sort((left, right) => right.confidence - left.confidence || left.id.localeCompare(right.id))
        .slice(0, topLimit);
    const weakRowsByType: Record<string, GraphRebuildChunkSemanticBridgeAuditRow[]> = {};
    for (const [type, rows] of rowsByType(allRows)) {
        weakRowsByType[type] = rows
            .slice()
            .sort((left, right) => left.confidence - right.confidence || left.id.localeCompare(right.id))
            .slice(0, weakPerType);
    }
    const reviewed = uniqueRows([...topRows, ...Object.values(weakRowsByType).flat()]);
    return {
        total: bridges.length,
        reviewedRows: reviewed.length,
        sameEntityOnlySuspectCount: allRows.filter((row) => row.sameEntityOnlySuspect).length,
        opaqueCueRowCount: allRows.filter((row) => row.cueStrength === 'opaque').length,
        substantiveCueRowCount: allRows.filter((row) => row.cueStrength === 'substantive').length,
        byType: auditStatsByType(allRows),
        topRows,
        weakRowsByType,
        suspectRows: allRows.filter((row) => row.sameEntityOnlySuspect)
            .sort((left, right) => right.confidence - left.confidence || left.id.localeCompare(right.id))
            .slice(0, 24),
    };
}

export function auditBridge(bridge: GraphRebuildChunkSemanticBridge): GraphRebuildChunkSemanticBridgeAuditRow {
    const hasSubstantiveRationale = bridge.rationale.some((entry) =>
        SUBSTANTIVE_RATIONALE_PREFIXES.some((prefix) => entry.startsWith(prefix)),
    );
    const hasOpaqueRationale = bridge.rationale.some((entry) => OPAQUE_RATIONALES.has(entry));
    const hasSubstantiveCue = [bridge.sourceCue, bridge.targetCue].some((cue) => isSubstantiveCue(cue));
    const cueStrength = cueStrengthFor(hasSubstantiveRationale, hasSubstantiveCue);
    const sameEntityOnlySuspect = !hasSubstantiveRationale && !hasSubstantiveCue;
    const reasons = [
        sameEntityOnlySuspect ? 'shared_participants_without_substantive_semantic_cue' : '',
        hasOpaqueRationale ? 'opaque_same_frame_or_event_type_rationale' : '',
        !bridge.semanticVerbs.length ? 'missing_semantic_verbs' : '',
        bridge.supportingEntityIds.length ? `supporting_entities:${bridge.supportingEntityIds.length}` : 'missing_supporting_entities',
    ].filter(Boolean);
    return {
        id: bridge.id,
        bridgeType: bridge.bridgeType,
        confidence: round(bridge.confidence),
        sourceChunkId: bridge.sourceChunkId,
        targetChunkId: bridge.targetChunkId,
        claim: bridge.claim,
        semanticVerbs: bridge.semanticVerbs,
        sourceCue: bridge.sourceCue,
        targetCue: bridge.targetCue,
        supportingEntityCount: bridge.supportingEntityIds.length,
        cueStrength,
        falsePositiveRisk: sameEntityOnlySuspect ? 'high' : hasOpaqueRationale ? 'medium' : 'low',
        sameEntityOnlySuspect,
        reasons,
    };
}

export function isSameEntityOnlyBridgeSuspect(bridge: GraphRebuildChunkSemanticBridge): boolean {
    return auditBridge(bridge).sameEntityOnlySuspect;
}

function cueStrengthFor(
    hasSubstantiveRationale: boolean,
    hasSubstantiveCue: boolean,
): GraphRebuildChunkSemanticBridgeAuditRow['cueStrength'] {
    if (hasSubstantiveRationale && hasSubstantiveCue) return 'substantive';
    if (hasSubstantiveRationale) return 'rationale_only';
    if (hasSubstantiveCue) return 'cue_only';
    return 'opaque';
}

function isSubstantiveCue(cue: string | undefined): boolean {
    if (!cue) return false;
    const normalized = cue.toLowerCase();
    if (!normalized.trim()) return false;
    return !OPAQUE_CUES.has(normalized);
}

function auditStatsByType(
    rows: GraphRebuildChunkSemanticBridgeAuditRow[],
): GraphRebuildChunkSemanticBridgeFalsePositiveAudit['byType'] {
    return Object.fromEntries([...rowsByType(rows)].map(([type, typeRows]) => [type, {
        total: typeRows.length,
        sameEntityOnlySuspects: typeRows.filter((row) => row.sameEntityOnlySuspect).length,
        opaqueCueRows: typeRows.filter((row) => row.cueStrength === 'opaque').length,
        substantiveCueRows: typeRows.filter((row) => row.cueStrength === 'substantive').length,
        weakestConfidence: round(Math.min(...typeRows.map((row) => row.confidence))),
        strongestConfidence: round(Math.max(...typeRows.map((row) => row.confidence))),
    }]));
}

function rowsByType<T extends { bridgeType: GraphRebuildChunkSemanticBridgeType }>(rows: T[]): Map<string, T[]> {
    const byType = new Map<string, T[]>();
    for (const row of rows) byType.set(row.bridgeType, [...(byType.get(row.bridgeType) || []), row]);
    return new Map([...byType.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function uniqueRows(rows: GraphRebuildChunkSemanticBridgeAuditRow[]): GraphRebuildChunkSemanticBridgeAuditRow[] {
    const byId = new Map<string, GraphRebuildChunkSemanticBridgeAuditRow>();
    for (const row of rows) byId.set(row.id, row);
    return [...byId.values()];
}

function round(value: number): number {
    return Number(value.toFixed(3));
}
