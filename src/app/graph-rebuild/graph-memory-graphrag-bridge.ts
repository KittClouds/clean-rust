import type {
    GraphRebuildEmbeddingTarget,
    GraphRebuildEntityAnchor,
    GraphRebuildSnapshot,
    GraphSemanticEvalLedgerEntry,
} from './graph-rebuild-snapshot';

export type GraphMemoryGraphRagLayer = 'schema' | 'fact' | 'passage';
export type GraphMemoryGraphRagSurface =
    | 'observer_extraction'
    | 'reflector_compression'
    | 'retrieval_context'
    | 'conflict_resolution';
export type GraphMemoryGraphRagEvalKind =
    | 'hierarchical_retrieval'
    | 'reflection_seed'
    | 'observer_seed'
    | 'conflict_route';

export interface GraphMemoryGraphRagPaperShape {
    paperName: 'MemGraphRAG: Memory-based Multi-Agent System for Graph Retrieval-Augmented Generation';
    arxivId: '2606.00610';
    implementationMode: 'phoenix_bridge_contract';
    mappedLayers: Array<{
        paperLayer: 'schema_layer' | 'fact_layer' | 'passage_layer';
        phoenixLayer: GraphMemoryGraphRagLayer;
        source: string;
    }>;
    skippedRuntimePieces: string[];
}

export interface GraphMemoryGraphRagAgentContract {
    surface: GraphMemoryGraphRagSurface;
    promptSource: string;
    acceptsLayers: GraphMemoryGraphRagLayer[];
    outputShape: string;
}

export interface GraphMemoryGraphRagRecord {
    id: string;
    layer: GraphMemoryGraphRagLayer;
    sourceId: string;
    sourceKind: string;
    label: string;
    text: string;
    entityIds: string[];
    evidenceIds: string[];
    parentRecordIds: string[];
    agentSurfaces: GraphMemoryGraphRagSurface[];
    retrievalWeight: number;
    reflectionWeight: number;
    conflictWeight: number;
}

export interface GraphMemoryGraphRagEvalRow {
    id: string;
    kind: GraphMemoryGraphRagEvalKind;
    query: string;
    expectedLayer: GraphMemoryGraphRagLayer;
    seedRecordIds: string[];
    retrievedRecordIds: string[];
    score: number;
    passed: boolean;
    failureModes: string[];
    rationale: string[];
}

export interface GraphMemoryGraphRagReceipt {
    id: string;
    recordId?: string;
    evalRowId?: string;
    reversible: true;
    mutationAllowed: false;
    invariant: 'memorygraphrag_bridge_no_topology_commit';
    evidenceIds: string[];
    undoHint: string;
    detail: string;
}

export interface GraphMemoryGraphRagBridgeCounters {
    byLayer: Record<string, number>;
    bySurface: Record<string, number>;
    byEvalKind: Record<string, number>;
    recordCount: number;
    schemaRecords: number;
    factRecords: number;
    passageRecords: number;
    observerSeedRecords: number;
    reflectorSeedRecords: number;
    retrievalRecords: number;
    conflictRecords: number;
    evalRowCount: number;
    passedEvalRows: number;
    failedEvalRows: number;
    receiptCount: number;
    reversibleReceiptCount: number;
    mutationAllowedCount: number;
}

export interface GraphMemoryGraphRagBridgeSummary {
    schemaVersion: 'phoenix-memory-graphrag-bridge/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    paperShape: GraphMemoryGraphRagPaperShape;
    agentContracts: GraphMemoryGraphRagAgentContract[];
    records: GraphMemoryGraphRagRecord[];
    evalRows: GraphMemoryGraphRagEvalRow[];
    receipts: GraphMemoryGraphRagReceipt[];
    compactEvalLedger: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            kind: GraphMemoryGraphRagEvalKind;
            expectedLayer: GraphMemoryGraphRagLayer;
            score: number;
            passed: boolean;
            retrieved: number;
            failures: string[];
        }>;
    };
    counters: GraphMemoryGraphRagBridgeCounters;
}

const MAX_SCHEMA_RECORDS = 96;
const MAX_FACT_RECORDS = 192;
const MAX_PASSAGE_RECORDS = 96;
const MAX_EVAL_ROWS = 64;

export function buildGraphMemoryGraphRagBridgeSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphMemoryGraphRagBridgeSummary {
    const schemas = schemaRecords(snapshot);
    const facts = factRecords(snapshot, schemas);
    const passages = passageRecords(snapshot, facts);
    const records = [...schemas, ...facts, ...passages];
    const evalRows = buildEvalRows(snapshot, records);
    const receipts = [
        ...records.map((record) => receiptForRecord(record)),
        ...evalRows.map((row) => receiptForEvalRow(row)),
    ];
    return {
        schemaVersion: 'phoenix-memory-graphrag-bridge/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        paperShape: paperShape(),
        agentContracts: agentContracts(),
        records,
        evalRows,
        receipts,
        compactEvalLedger: compactEvalLedger(snapshot, evalRows),
        counters: counters(records, evalRows, receipts),
    };
}

function schemaRecords(snapshot: GraphRebuildSnapshot): GraphMemoryGraphRagRecord[] {
    const nodeById = new Map(snapshot.nodes.map((node) => [node.entityId, node]));
    const buckets = new Map<string, { label: string; entityIds: string[]; evidenceIds: string[]; count: number }>();
    for (const relationship of snapshot.relationships.filter((row) => row.status !== 'rejected')) {
        const sourceKind = nodeById.get(relationship.sourceEntityId)?.kind || 'ENTITY';
        const targetKind = nodeById.get(relationship.targetEntityId)?.kind || 'ENTITY';
        const key = `${sourceKind}:${relationship.relationType}:${targetKind}`;
        upsertSchemaBucket(buckets, key, {
            label: `${sourceKind} ${relationship.relationType} ${targetKind}`,
            entityIds: [relationship.sourceEntityId, relationship.targetEntityId],
            evidenceIds: relationship.evidenceAnchorIds,
        });
    }
    for (const edge of snapshot.temporalEdges) {
        upsertSchemaBucket(buckets, `EVENT:${edge.relationType}:EVENT`, {
            label: `EVENT ${edge.relationType} EVENT`,
            entityIds: [],
            evidenceIds: edge.evidenceIds,
        });
    }
    for (const edge of snapshot.causalEdges) {
        upsertSchemaBucket(buckets, `EVENT:${edge.relationKind || edge.relationType}:EVENT`, {
            label: `EVENT ${edge.relationKind || edge.relationType} EVENT`,
            entityIds: [],
            evidenceIds: edge.evidenceIds,
        });
    }
    for (const state of snapshot.memoryState) {
        upsertSchemaBucket(buckets, `ENTITY:memory.${state.key}:VALUE`, {
            label: `ENTITY memory.${state.key} VALUE`,
            entityIds: [state.entityId],
            evidenceIds: state.evidenceIds,
        });
    }
    return [...buckets.entries()]
        .sort(([, left], [, right]) => right.count - left.count || left.label.localeCompare(right.label))
        .slice(0, MAX_SCHEMA_RECORDS)
        .map(([key, bucket]) => record({
            layer: 'schema',
            sourceId: key,
            sourceKind: 'ontology_pattern',
            label: bucket.label,
            text: `schema_pattern:${bucket.label} supporting_facts:${bucket.count}`,
            entityIds: bucket.entityIds,
            evidenceIds: bucket.evidenceIds,
            parentRecordIds: [],
            agentSurfaces: ['retrieval_context', 'reflector_compression'],
            retrievalWeight: clamp(0.54 + Math.min(0.32, bucket.count * 0.025)),
            reflectionWeight: 0.52,
            conflictWeight: 0.28,
        }));
}

function factRecords(
    snapshot: GraphRebuildSnapshot,
    schemas: GraphMemoryGraphRagRecord[],
): GraphMemoryGraphRagRecord[] {
    const targets = targetMap(snapshot.embeddingTargets);
    const schemaBySource = new Map(schemas.map((schema) => [schema.sourceId, schema.id]));
    const nodeById = new Map(snapshot.nodes.map((node) => [node.entityId, node]));
    const out: GraphMemoryGraphRagRecord[] = [];
    for (const relationship of snapshot.relationships.filter((row) => row.status !== 'rejected')) {
        const target = targets.get(relationship.id);
        const sourceKind = nodeById.get(relationship.sourceEntityId)?.kind || 'ENTITY';
        const targetKind = nodeById.get(relationship.targetEntityId)?.kind || 'ENTITY';
        out.push(record({
            layer: 'fact',
            sourceId: relationship.id,
            sourceKind: 'relationship',
            label: target?.label || relationship.relationType,
            text: target?.text || relationship.rationale,
            entityIds: [relationship.sourceEntityId, relationship.targetEntityId],
            evidenceIds: relationship.evidenceAnchorIds,
            parentRecordIds: compact([schemaBySource.get(`${sourceKind}:${relationship.relationType}:${targetKind}`)]),
            agentSurfaces: ['retrieval_context', 'reflector_compression'],
            retrievalWeight: relationship.confidence,
            reflectionWeight: relationship.status === 'accepted' ? 0.76 : 0.58,
            conflictWeight: relationship.status === 'review' ? 0.52 : 0.18,
        }));
    }
    for (const event of snapshot.events) {
        const target = targets.get(event.id);
        out.push(record({
            layer: 'fact',
            sourceId: event.id,
            sourceKind: 'event',
            label: event.label,
            text: target?.text || event.label,
            entityIds: event.entityIds,
            evidenceIds: event.evidenceAnchorIds,
            parentRecordIds: [],
            agentSurfaces: ['retrieval_context', 'observer_extraction'],
            retrievalWeight: event.confidence,
            reflectionWeight: 0.66,
            conflictWeight: 0.16,
        }));
    }
    for (const edge of [...snapshot.temporalEdges, ...snapshot.causalEdges]) {
        const target = targets.get(edge.id);
        out.push(record({
            layer: 'fact',
            sourceId: edge.id,
            sourceKind: 'status' in edge ? 'causal_edge' : 'temporal_edge',
            label: target?.label || edge.relationType,
            text: target?.text || edge.relationType,
            entityIds: [],
            evidenceIds: edge.evidenceIds,
            parentRecordIds: compact([schemaBySource.get(`EVENT:${'relationKind' in edge ? edge.relationKind || edge.relationType : edge.relationType}:EVENT`)]),
            agentSurfaces: ['retrieval_context', 'reflector_compression', 'conflict_resolution'],
            retrievalWeight: edge.confidence,
            reflectionWeight: 0.7,
            conflictWeight: 'status' in edge && edge.status !== 'accepted' ? 0.64 : 0.24,
        }));
    }
    for (const state of snapshot.memoryState) {
        const target = targets.get(state.id);
        out.push(record({
            layer: 'fact',
            sourceId: state.id,
            sourceKind: 'memory_state',
            label: state.key,
            text: target?.text || `${state.key} ${state.value}`,
            entityIds: [state.entityId],
            evidenceIds: state.evidenceIds,
            parentRecordIds: compact([schemaBySource.get(`ENTITY:memory.${state.key}:VALUE`)]),
            agentSurfaces: ['observer_extraction', 'reflector_compression', 'retrieval_context'],
            retrievalWeight: 0.72,
            reflectionWeight: 0.9,
            conflictWeight: 0.28,
        }));
    }
    const evalRecords = (snapshot.semanticEvalLedgerSummary?.entries || [])
        .map((entry) => evalDecisionRecord(entry))
        .sort(compareMemoryRecords)
        .slice(0, Math.min(48, MAX_FACT_RECORDS));
    const selectedFacts = out
        .sort(compareMemoryRecords)
        .slice(0, MAX_FACT_RECORDS - evalRecords.length);
    return [...evalRecords, ...selectedFacts].sort(compareMemoryRecords);
}

function passageRecords(
    snapshot: GraphRebuildSnapshot,
    facts: GraphMemoryGraphRagRecord[],
): GraphMemoryGraphRagRecord[] {
    const targets = targetMap(snapshot.embeddingTargets);
    const anchorsByChunk = groupAnchorsByChunk(snapshot.entityAnchors);
    return snapshot.chunks
        .map((chunk) => {
            const target = targets.get(chunk.id);
            const anchors = anchorsByChunk.get(chunk.id) || [];
            const entityIds = unique(anchors.map((anchor) => anchor.entityId));
            const evidenceIds = anchors.map((anchor) => anchor.id);
            return record({
                layer: 'passage',
                sourceId: chunk.id,
                sourceKind: 'chunk',
                label: `Chunk ${chunk.ordinal + 1}`,
                text: target?.text || `${chunk.noteId}:${chunk.start}-${chunk.end}`,
                entityIds,
                evidenceIds,
                parentRecordIds: passageParentFactIds(entityIds, evidenceIds, facts),
                agentSurfaces: ['observer_extraction', 'retrieval_context'],
                retrievalWeight: clamp(0.42 + Math.min(0.34, anchors.length * 0.018)),
                reflectionWeight: chunk.meaningFrame?.temporalCues.length ? 0.74 : 0.48,
                conflictWeight: 0.12,
            });
        })
        .sort((left, right) => right.retrievalWeight - left.retrievalWeight || left.sourceId.localeCompare(right.sourceId))
        .slice(0, MAX_PASSAGE_RECORDS);
}

function buildEvalRows(
    snapshot: GraphRebuildSnapshot,
    records: GraphMemoryGraphRagRecord[],
): GraphMemoryGraphRagEvalRow[] {
    const out: GraphMemoryGraphRagEvalRow[] = [];
    const facts = records.filter((recordRow) => recordRow.layer === 'fact');
    const schemas = records.filter((recordRow) => recordRow.layer === 'schema');
    const passages = records.filter((recordRow) => recordRow.layer === 'passage');
    for (const row of schemas.slice(0, 16)) out.push(evalRow('hierarchical_retrieval', row, records, `Follow graph memory schema ${row.label}.`, 'schema'));
    for (const row of facts.filter((fact) => fact.reflectionWeight >= 0.68).slice(0, 18)) {
        out.push(evalRow('reflection_seed', row, records, `Reflect on durable Phoenix memory fact ${row.label}.`, 'fact'));
    }
    for (const row of passages.filter((passage) => passage.entityIds.length).slice(0, 14)) {
        out.push(evalRow('observer_seed', row, records, `Extract observations from passage around ${row.entityIds.slice(0, 3).join(', ')}.`, 'passage'));
    }
    const disagreementEntries = (snapshot.semanticEvalLedgerSummary?.entries || [])
        .filter((entry) => entry.flags.includes('model_disagreement') || entry.flags.includes('manifold_disagreement') || entry.label !== 'accepted_candidate');
    for (const entry of disagreementEntries.slice(0, 16)) {
        const seed = facts.find((fact) => fact.sourceId === entry.id) || facts.find((fact) => fact.sourceId === entry.decisionId);
        if (seed) out.push(evalRow('conflict_route', seed, records, `Route adjudication disagreement ${entry.label} without poisoning graph topology.`, 'fact'));
    }
    return out.slice(0, MAX_EVAL_ROWS);
}

function evalRow(
    kind: GraphMemoryGraphRagEvalKind,
    seed: GraphMemoryGraphRagRecord,
    records: GraphMemoryGraphRagRecord[],
    query: string,
    expectedLayer: GraphMemoryGraphRagLayer,
): GraphMemoryGraphRagEvalRow {
    const retrieved = retrieve(seed, records);
    const layerHits = new Set(retrieved.map((row) => row.layer));
    const expectedHit = layerHits.has(expectedLayer) ? 0.42 : 0;
    const hierarchyHit = (layerHits.has('schema') ? 0.2 : 0) + (layerHits.has('fact') ? 0.2 : 0) + (layerHits.has('passage') ? 0.12 : 0);
    const overlapHit = retrieved.some((row) => overlap(row.entityIds, seed.entityIds) > 0 || overlap(row.evidenceIds, seed.evidenceIds) > 0) ? 0.16 : 0;
    const score = round(clamp(expectedHit + hierarchyHit + overlapHit + seed.retrievalWeight * 0.1));
    const failureModes = [
        !layerHits.has('schema') ? 'missing_schema_layer' : '',
        !layerHits.has('fact') ? 'missing_fact_layer' : '',
        !layerHits.has('passage') ? 'missing_passage_layer' : '',
        overlapHit ? '' : 'missing_entity_or_evidence_overlap',
    ].filter(Boolean);
    return {
        id: `memorygraphrag-eval:${kind}:${slug(seed.id)}`,
        kind,
        query,
        expectedLayer,
        seedRecordIds: [seed.id],
        retrievedRecordIds: retrieved.map((row) => row.id),
        score,
        passed: score >= 0.58,
        failureModes,
        rationale: [
            `seed:${seed.layer}:${seed.sourceKind}`,
            `retrieved_layers:${[...layerHits].sort().join(',')}`,
            `retrieved:${retrieved.length}`,
        ],
    };
}

function retrieve(seed: GraphMemoryGraphRagRecord, records: GraphMemoryGraphRagRecord[]): GraphMemoryGraphRagRecord[] {
    return records
        .map((row) => ({ row, score: retrievalScore(seed, row) }))
        .filter(({ score }) => score > 0)
        .sort((left, right) => right.score - left.score || left.row.id.localeCompare(right.row.id))
        .slice(0, 8)
        .map(({ row }) => row);
}

function retrievalScore(seed: GraphMemoryGraphRagRecord, row: GraphMemoryGraphRagRecord): number {
    if (seed.id === row.id) return 2;
    const entityScore = overlap(seed.entityIds, row.entityIds) * 0.28;
    const evidenceScore = overlap(seed.evidenceIds, row.evidenceIds) * 0.34;
    const layerScore = seed.layer === row.layer ? 0.12 : 0.24;
    const surfaceScore = overlap(seed.agentSurfaces, row.agentSurfaces) * 0.08;
    return entityScore + evidenceScore + layerScore + surfaceScore + row.retrievalWeight * 0.12;
}

function memoryUtility(row: GraphMemoryGraphRagRecord): number {
    return Math.max(row.retrievalWeight, row.reflectionWeight, row.conflictWeight);
}

function compareMemoryRecords(left: GraphMemoryGraphRagRecord, right: GraphMemoryGraphRagRecord): number {
    return memoryUtility(right) - memoryUtility(left)
        || right.reflectionWeight - left.reflectionWeight
        || left.id.localeCompare(right.id);
}

function evalDecisionRecord(entry: GraphSemanticEvalLedgerEntry): GraphMemoryGraphRagRecord {
    const conflictWeight = entry.flags.includes('model_disagreement') || entry.flags.includes('manifold_disagreement') ? 0.88 : 0.42;
    return record({
        layer: 'fact',
        sourceId: entry.id,
        sourceKind: 'eval_decision',
        label: `${entry.label}:${entry.candidateKind}`,
        text: [
            entry.sourceHypothesis,
            `state:${entry.adjudicationState} score:${entry.score.toFixed(3)}`,
            `flags:${entry.flags.join(',') || 'none'}`,
            `rationale:${entry.rationale.slice(0, 3).join(' ')}`,
        ].join('\n'),
        entityIds: entityIdsFromTargets(entry.evidenceTargetIds),
        evidenceIds: entry.evidenceTargetIds,
        parentRecordIds: [],
        agentSurfaces: ['reflector_compression', 'retrieval_context', 'conflict_resolution'],
        retrievalWeight: entry.score,
        reflectionWeight: entry.label === 'accepted_candidate' ? 0.62 : 0.74,
        conflictWeight,
    });
}

function record(input: Omit<GraphMemoryGraphRagRecord, 'id'>): GraphMemoryGraphRagRecord {
    return {
        ...input,
        id: `memorygraphrag:${input.layer}:${slug(`${input.sourceKind}:${input.sourceId}`)}`,
        text: limitText(input.text, input.layer === 'passage' ? 1700 : 1100),
        entityIds: unique(input.entityIds).slice(0, 24),
        evidenceIds: unique(input.evidenceIds).slice(0, 32),
        parentRecordIds: unique(input.parentRecordIds).slice(0, 12),
        retrievalWeight: round(clamp(input.retrievalWeight)),
        reflectionWeight: round(clamp(input.reflectionWeight)),
        conflictWeight: round(clamp(input.conflictWeight)),
    };
}

function targetMap(targets: GraphRebuildEmbeddingTarget[]): Map<string, GraphRebuildEmbeddingTarget> {
    const out = new Map<string, GraphRebuildEmbeddingTarget>();
    for (const target of targets) {
        out.set(target.sourceId, target);
        out.set(target.id, target);
    }
    return out;
}

function upsertSchemaBucket(
    buckets: Map<string, { label: string; entityIds: string[]; evidenceIds: string[]; count: number }>,
    key: string,
    value: { label: string; entityIds: string[]; evidenceIds: string[] },
): void {
    const current = buckets.get(key) || { label: value.label, entityIds: [], evidenceIds: [], count: 0 };
    current.count += 1;
    current.entityIds = unique([...current.entityIds, ...value.entityIds]);
    current.evidenceIds = unique([...current.evidenceIds, ...value.evidenceIds]);
    buckets.set(key, current);
}

function groupAnchorsByChunk(anchors: GraphRebuildEntityAnchor[]): Map<string, GraphRebuildEntityAnchor[]> {
    const groups = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of anchors) {
        if (!anchor.chunkId) continue;
        groups.set(anchor.chunkId, [...(groups.get(anchor.chunkId) || []), anchor]);
    }
    return groups;
}

function passageParentFactIds(
    entityIds: string[],
    evidenceIds: string[],
    facts: GraphMemoryGraphRagRecord[],
): string[] {
    return facts
        .map((fact) => ({
            fact,
            score: overlap(entityIds, fact.entityIds) * 0.4 + overlap(evidenceIds, fact.evidenceIds) * 0.6,
        }))
        .filter(({ score }) => score > 0)
        .sort((left, right) => right.score - left.score || left.fact.id.localeCompare(right.fact.id))
        .slice(0, 4)
        .map(({ fact }) => fact.id);
}

function receiptForRecord(recordRow: GraphMemoryGraphRagRecord): GraphMemoryGraphRagReceipt {
    return {
        id: `memorygraphrag-receipt:${slug(recordRow.id)}`,
        recordId: recordRow.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'memorygraphrag_bridge_no_topology_commit',
        evidenceIds: recordRow.evidenceIds,
        undoHint: 'drop this bridge record; no graph atom was mutated',
        detail: `${recordRow.layer} record routes Phoenix graph receipts into OM memory surfaces`,
    };
}

function receiptForEvalRow(row: GraphMemoryGraphRagEvalRow): GraphMemoryGraphRagReceipt {
    return {
        id: `memorygraphrag-eval-receipt:${slug(row.id)}`,
        evalRowId: row.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'memorygraphrag_bridge_no_topology_commit',
        evidenceIds: row.seedRecordIds,
        undoHint: 'drop this eval row; no graph atom was mutated',
        detail: `${row.kind} eval ${row.passed ? 'passed' : 'failed'} at ${Math.round(row.score * 100)}%`,
    };
}

function compactEvalLedger(snapshot: GraphRebuildSnapshot, rows: GraphMemoryGraphRagEvalRow[]): GraphMemoryGraphRagBridgeSummary['compactEvalLedger'] {
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: rows.length,
        rows: rows.map((row) => ({
            id: row.id,
            kind: row.kind,
            expectedLayer: row.expectedLayer,
            score: row.score,
            passed: row.passed,
            retrieved: row.retrievedRecordIds.length,
            failures: row.failureModes,
        })),
    };
}

function counters(
    records: GraphMemoryGraphRagRecord[],
    evalRows: GraphMemoryGraphRagEvalRow[],
    receipts: GraphMemoryGraphRagReceipt[],
): GraphMemoryGraphRagBridgeCounters {
    return {
        byLayer: countBy(records, (row) => row.layer),
        bySurface: countBy(records.flatMap((row) => row.agentSurfaces), (surface) => surface),
        byEvalKind: countBy(evalRows, (row) => row.kind),
        recordCount: records.length,
        schemaRecords: records.filter((row) => row.layer === 'schema').length,
        factRecords: records.filter((row) => row.layer === 'fact').length,
        passageRecords: records.filter((row) => row.layer === 'passage').length,
        observerSeedRecords: records.filter((row) => row.agentSurfaces.includes('observer_extraction')).length,
        reflectorSeedRecords: records.filter((row) => row.agentSurfaces.includes('reflector_compression')).length,
        retrievalRecords: records.filter((row) => row.agentSurfaces.includes('retrieval_context')).length,
        conflictRecords: records.filter((row) => row.agentSurfaces.includes('conflict_resolution')).length,
        evalRowCount: evalRows.length,
        passedEvalRows: evalRows.filter((row) => row.passed).length,
        failedEvalRows: evalRows.filter((row) => !row.passed).length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        mutationAllowedCount: receipts.filter((receipt) => receipt.mutationAllowed).length,
    };
}

function paperShape(): GraphMemoryGraphRagPaperShape {
    return {
        paperName: 'MemGraphRAG: Memory-based Multi-Agent System for Graph Retrieval-Augmented Generation',
        arxivId: '2606.00610',
        implementationMode: 'phoenix_bridge_contract',
        mappedLayers: [
            { paperLayer: 'schema_layer', phoenixLayer: 'schema', source: 'relationship kinds, event relation kinds, memory-state keys' },
            { paperLayer: 'fact_layer', phoenixLayer: 'fact', source: 'relationships, events, temporal/causal edges, memory states, semantic eval decisions' },
            { paperLayer: 'passage_layer', phoenixLayer: 'passage', source: 'bounded graph-rebuild chunks with entity anchor evidence' },
        ],
        skippedRuntimePieces: [
            'upstream multi-agent graph construction',
            'LLM relation extraction',
            'LLM conflict resolution',
            'embedding-backed semantic search',
        ],
    };
}

function agentContracts(): GraphMemoryGraphRagAgentContract[] {
    return [
        {
            surface: 'observer_extraction',
            promptSource: 'docs/observer-agent.md',
            acceptsLayers: ['passage', 'fact'],
            outputShape: '<observations>, <current-task>, <suggested-response>',
        },
        {
            surface: 'reflector_compression',
            promptSource: 'docs/reflector-agent.md',
            acceptsLayers: ['schema', 'fact'],
            outputShape: 'consolidated observations with temporal anchors preserved',
        },
        {
            surface: 'retrieval_context',
            promptSource: 'phoenix graph retrieval receipts',
            acceptsLayers: ['schema', 'fact', 'passage'],
            outputShape: 'hierarchical route from schema to facts to source passages',
        },
        {
            surface: 'conflict_resolution',
            promptSource: 'Phase 5/6 adjudication ledger',
            acceptsLayers: ['fact'],
            outputShape: 'ledger-only conflict material for future classifiers and evals',
        },
    ];
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function entityIdsFromTargets(values: string[]): string[] {
    return values
        .filter((value) => value.startsWith('entity:') || value.includes(':entity:'))
        .map((value) => value.split(':').pop() || value);
}

function overlap(left: string[], right: string[]): number {
    if (!left.length || !right.length) return 0;
    const rightSet = new Set(right);
    return left.filter((value) => rightSet.has(value)).length;
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values.filter(Boolean))];
}

function compact(values: Array<string | undefined>): string[] {
    return values.filter((value): value is string => Boolean(value));
}

function limitText(value: string, max: number): string {
    const text = value.replace(/\s+/g, ' ').trim();
    if (text.length <= max) return text;
    const head = Math.floor(max * 0.72);
    const tail = Math.max(120, max - head - 7);
    return `${text.slice(0, head)} ... ${text.slice(text.length - tail)}`;
}

function slug(value: string): string {
    const normalized = value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '') || 'x';
    return `${normalized.slice(0, 104)}:${stableHash(value)}`;
}

function stableHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
}

function clamp(value: number, min = 0, max = 1): number {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
