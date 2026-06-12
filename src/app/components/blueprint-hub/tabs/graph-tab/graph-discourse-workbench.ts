import type { RegisteredEntity } from '../../../../lib/registry';
import type {
    GraphDiscourseEvalLedgerEntry,
    GraphRebuildCausalEdge,
    GraphRebuildEntityLinkSuggestion,
    GraphRebuildLinkSuggestion,
    GraphRebuildRelationship,
    GraphRebuildSnapshot,
    GraphSemanticEvalLedgerEntry,
} from '../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GraphDocumentReviewRow } from '../../../../graph-rebuild/graph-document-review';
import type {
    GraphDocumentCompilerSummary,
    GraphDocumentTopologyDiff,
} from '../../../../graph-rebuild/graph-document-compiler';
import type { GraphDiscourseTabId, GraphDiscourseTone } from './graph-discourse-analytics';

export type GraphDiscourseWorkbenchDecision =
    | 'accepted'
    | 'rejected'
    | 'deferred'
    | 'muted'
    | 'promoted_to_anchor'
    | 'compiled_to_graph'
    | 'ledger_only';

export interface GraphDiscourseFact {
    label: string;
    value: string;
}

export interface GraphDiscourseWorkbenchRecord {
    id: string;
    tab: GraphDiscourseTabId;
    kind: string;
    title: string;
    subtitle: string;
    detail: string;
    status: string;
    score: number | null;
    scoreLabel: string;
    tone: GraphDiscourseTone;
    focusQuery: string;
    candidateId?: string;
    decisionId?: string;
    sourceIds: string[];
    targetIds: string[];
    evidenceIds: string[];
    entityIds: string[];
    receiptIds: string[];
    actionKinds: string[];
    tags: string[];
    rationale: string[];
    facts: GraphDiscourseFact[];
}

export interface GraphDiscourseWorkbenchView {
    records: GraphDiscourseWorkbenchRecord[];
    recordsByTab: Record<GraphDiscourseTabId, GraphDiscourseWorkbenchRecord[]>;
    recordsById: Record<string, GraphDiscourseWorkbenchRecord>;
    openReviewCount: number;
}

type WorkbenchRecordInput =
    Pick<GraphDiscourseWorkbenchRecord, 'id' | 'tab' | 'kind' | 'title' | 'subtitle' | 'detail' | 'status' | 'score' | 'tone' | 'focusQuery'>
    & Partial<Omit<GraphDiscourseWorkbenchRecord,
        'id' | 'tab' | 'kind' | 'title' | 'subtitle' | 'detail' | 'status' | 'score' | 'scoreLabel' | 'tone' | 'focusQuery'
        | 'sourceIds' | 'targetIds' | 'evidenceIds' | 'entityIds' | 'receiptIds' | 'tags' | 'rationale'
        | 'actionKinds'
    >>
    & {
        sourceIds?: Array<string | undefined>;
        targetIds?: Array<string | undefined>;
        evidenceIds?: Array<string | undefined>;
        entityIds?: Array<string | undefined>;
        receiptIds?: Array<string | undefined>;
        actionKinds?: Array<string | undefined>;
        tags?: Array<string | undefined>;
        rationale?: Array<string | undefined>;
    };

const TABS: GraphDiscourseTabId[] = ['insights', 'ideas', 'gaps', 'relations', 'stance', 'stats'];

export function buildGraphDiscourseWorkbenchView(
    snapshot: GraphRebuildSnapshot | null,
    entities: RegisteredEntity[],
): GraphDiscourseWorkbenchView | null {
    if (!snapshot) return null;
    const labels = targetLabels(snapshot, entities);
    const records: GraphDiscourseWorkbenchRecord[] = [];

    for (const entry of snapshot.discourseEvalLedgerSummary?.entries || []) {
        records.push(discourseLedgerRecord(entry, labels, 'insights'));
        if (entry.label !== 'accepted_candidate') records.push(discourseLedgerRecord(entry, labels, 'gaps'));
        if (entry.label === 'rejected_candidate' || entry.label.endsWith('_disagreement')) {
            records.push(discourseLedgerRecord(entry, labels, 'stance'));
        }
    }

    for (const entry of snapshot.semanticEvalLedgerSummary?.entries || []) {
        records.push(semanticLedgerRecord(entry, labels, 'insights'));
        if (entry.label !== 'accepted_candidate') records.push(semanticLedgerRecord(entry, labels, 'gaps'));
        if (entry.label === 'rejected_candidate' || entry.label.endsWith('_disagreement')) {
            records.push(semanticLedgerRecord(entry, labels, 'stance'));
        }
    }

    for (const edge of snapshot.discourseCompilerOverlaySummary?.overlayEdges || []) {
        const tab: GraphDiscourseTabId = edge.kind === 'document_cluster' ? 'ideas' : 'relations';
        records.push(record({
            id: `${tab}:overlay:${edge.id}`,
            tab,
            kind: `overlay:${edge.kind}`,
            title: titleCase(edge.kind),
            subtitle: route(edge.sourceTargetId, edge.targetTargetId, labels),
            detail: edge.proposedEdgeType || 'read-only compiler overlay',
            status: edge.status,
            score: edge.confidence,
            tone: edge.kind === 'cross_doc_resolution' ? 'review' : 'ready',
            focusQuery: focus([edge.sourceTargetId, edge.targetTargetId, ...edge.memberTargetIds], labels),
            candidateId: edge.candidateId,
            decisionId: edge.decisionId,
            sourceIds: [edge.sourceLedgerEntryId, edge.sourceHintId],
            targetIds: [edge.sourceTargetId, edge.targetTargetId, ...edge.memberTargetIds],
            evidenceIds: edge.evidenceTargetIds,
            tags: [edge.kind, edge.projectionKind, edge.graphPatch ? 'graph_patch' : 'overlay_only'],
            rationale: edge.rationale,
            facts: [
                fact('Candidate', edge.candidateId),
                fact('Decision', edge.decisionId),
                fact('Source target', label(edge.sourceTargetId, labels)),
                fact('Target', label(edge.targetTargetId, labels)),
                fact('Members', labelsFor(edge.memberTargetIds, labels)),
                fact('Evidence', edge.evidenceTargetIds.length.toString()),
            ],
        }));
    }

    for (const suggestion of snapshot.graphAwareLinkSuggestions || []) {
        records.push(graphSuggestionRecord(suggestion, labels, 'relations'));
        if (suggestion.status === 'review' || suggestion.semanticStatus === 'review' || suggestion.semanticStatus === 'rejected') {
            records.push(graphSuggestionRecord(suggestion, labels, 'gaps'));
        }
    }

    for (const suggestion of [
        ...(snapshot.shadowLinkSuggestions || []),
        ...(snapshot.entityLinkSuggestions || []),
    ]) {
        records.push(entitySuggestionRecord(suggestion, labels));
    }

    for (const relationship of snapshot.relationships || []) {
        records.push(relationshipRecord(relationship, labels));
    }

    for (const edge of snapshot.causalEdges || []) {
        records.push(causalRecord(edge, labels));
    }

    for (const row of snapshot.documentReviewSummary?.rows || []) {
        records.push(documentReviewRecord(row, labels));
    }

    const documentCompiler = snapshot.documentCompilerSummary;
    if (documentCompiler) {
        for (const diff of documentCompiler.topologyDiffs) {
            records.push(documentCompilerRecord(diff, documentCompiler, labels));
        }
    }

    records.push(...statRecords(snapshot));

    const recordsByTab = emptyTabMap();
    for (const row of records.sort(sortRecords)) {
        recordsByTab[row.tab].push(row);
    }
    for (const tab of TABS) {
        recordsByTab[tab] = recordsByTab[tab].slice(0, 24);
    }
    const visible = TABS.flatMap((tab) => recordsByTab[tab]);
    return {
        records: visible,
        recordsByTab,
        recordsById: Object.fromEntries(visible.map((row) => [row.id, row])),
        openReviewCount: visible.filter((row) => row.tone === 'review' || row.tone === 'danger').length,
    };
}

function discourseLedgerRecord(
    entry: GraphDiscourseEvalLedgerEntry,
    labels: Map<string, string>,
    tab: GraphDiscourseTabId,
): GraphDiscourseWorkbenchRecord {
    const evalDetail = entry.candidateEval
        ? `${titleCase(entry.candidateEval.kind)} / ${entry.candidateEval.passed ? 'passed' : 'failed'}`
        : titleCase(entry.label);
    return record({
        id: `${tab}:discourse-ledger:${entry.id}`,
        tab,
        kind: `discourse:${entry.candidateKind}`,
        title: titleCase(entry.label),
        subtitle: `${titleCase(entry.adjudicationState)} / ${titleCase(entry.candidateKind)}`,
        detail: entry.sourceHypothesis || evalDetail,
        status: entry.adjudicationState,
        score: entry.score,
        tone: toneFor(entry.label, entry.adjudicationState),
        focusQuery: focus(entry.evidenceTargetIds, labels) || entry.sourceHypothesis,
        candidateId: entry.candidateId,
        decisionId: entry.decisionId,
        targetIds: entry.evidenceTargetIds,
        evidenceIds: entry.evidenceTargetIds,
        tags: [
            entry.label,
            entry.rerank?.topLabelKind,
            entry.rerank?.decision,
            ...(entry.flags || []),
        ],
        rationale: entry.rationale,
        facts: [
            fact('Candidate', entry.candidateId),
            fact('Decision', entry.decisionId),
            fact('Rerank', entry.rerank ? `${entry.rerank.decision} / ${entry.rerank.scoreSource}` : ''),
            fact('Eval', evalDetail),
            fact('Before graph', graphDelta(entry.beforeGraph.edgeCount, entry.beforeGraph.factIds)),
            fact('After graph', graphDelta(entry.afterGraph.edgeCount, entry.afterGraph.factIds)),
        ],
    });
}

function semanticLedgerRecord(
    entry: GraphSemanticEvalLedgerEntry,
    labels: Map<string, string>,
    tab: GraphDiscourseTabId,
): GraphDiscourseWorkbenchRecord {
    return record({
        id: `${tab}:semantic-ledger:${entry.id}`,
        tab,
        kind: `semantic:${entry.candidateKind}`,
        title: titleCase(entry.label),
        subtitle: `${titleCase(entry.adjudicationState)} / ${titleCase(entry.candidateKind)}`,
        detail: entry.sourceHypothesis || titleCase(entry.label),
        status: entry.adjudicationState,
        score: entry.score,
        tone: toneFor(entry.label, entry.adjudicationState),
        focusQuery: focus(entry.evidenceTargetIds, labels) || entry.sourceHypothesis,
        candidateId: entry.candidateId,
        decisionId: entry.decisionId,
        targetIds: entry.evidenceTargetIds,
        evidenceIds: entry.evidenceTargetIds,
        tags: [entry.label, entry.rerank?.topLabelKind, ...(entry.flags || [])],
        rationale: entry.rationale,
        facts: [
            fact('Candidate', entry.candidateId),
            fact('Decision', entry.decisionId),
            fact('Rerank', entry.rerank ? `${entry.rerank.decision} / ${entry.rerank.scoreSource}` : ''),
            fact('Manifold votes', (entry.manifoldVotes || []).map((vote) => `${vote.manifold}:${percent(vote.score)}`).join(' / ')),
            fact('Before graph', graphDelta(entry.beforeGraph.edgeCount, entry.beforeGraph.factIds)),
            fact('After graph', graphDelta(entry.afterGraph.edgeCount, entry.afterGraph.factIds)),
        ],
    });
}

function graphSuggestionRecord(
    suggestion: GraphRebuildLinkSuggestion,
    labels: Map<string, string>,
    tab: GraphDiscourseTabId,
): GraphDiscourseWorkbenchRecord {
    return record({
        id: `${tab}:graph-suggestion:${suggestion.id}`,
        tab,
        kind: `graph-link:${suggestion.kind}`,
        title: titleCase(suggestion.suggestedRelationType),
        subtitle: route(suggestion.sourceEntityId, suggestion.targetEntityId, labels),
        detail: `${titleCase(suggestion.status)} / ${titleCase(suggestion.semanticStatus)}`,
        status: suggestion.status,
        score: suggestion.rerankScore || suggestion.confidence,
        tone: suggestion.status === 'confirmed' ? 'ready' : suggestion.semanticStatus === 'rejected' ? 'danger' : 'review',
        focusQuery: focus([suggestion.sourceEntityId, suggestion.targetEntityId], labels),
        sourceIds: [suggestion.sourceEntityId],
        targetIds: [suggestion.targetEntityId],
        evidenceIds: suggestion.evidenceIds,
        entityIds: [suggestion.sourceEntityId, suggestion.targetEntityId],
        tags: [suggestion.kind, suggestion.structuralRole, suggestion.embeddingRole, suggestion.productRegionRole, suggestion.productLane],
        rationale: suggestion.rationale,
        facts: [
            fact('Source', label(suggestion.sourceEntityId, labels)),
            fact('Target', label(suggestion.targetEntityId, labels)),
            fact('Region', suggestion.productRegionRole || ''),
            fact('Lane', suggestion.productLane || ''),
            fact('Signals', (suggestion.rerankSignals || []).join(' / ')),
        ],
    });
}

function entitySuggestionRecord(
    suggestion: GraphRebuildEntityLinkSuggestion,
    labels: Map<string, string>,
): GraphDiscourseWorkbenchRecord {
    return record({
        id: `gaps:entity-suggestion:${suggestion.id}`,
        tab: 'gaps',
        kind: `entity-link:${suggestion.decision}`,
        title: suggestion.surface,
        subtitle: suggestion.candidateLabel || suggestion.candidateEntityId || titleCase(suggestion.decision),
        detail: `${titleCase(suggestion.status)} / ${titleCase(suggestion.decision)}`,
        status: suggestion.status,
        score: suggestion.rerankScore || suggestion.confidence,
        tone: suggestion.decision === 'reject' ? 'danger' : suggestion.status === 'confirmed' ? 'ready' : 'review',
        focusQuery: [suggestion.surface, suggestion.candidateLabel, suggestion.normalizedSurface].filter(Boolean).join(' '),
        sourceIds: [suggestion.mentionId, suggestion.noteId, suggestion.chunkId],
        targetIds: [suggestion.candidateEntityId, ...suggestion.competingEntityIds],
        evidenceIds: suggestion.evidenceIds,
        entityIds: [suggestion.candidateEntityId, ...suggestion.competingEntityIds],
        tags: [suggestion.decision, suggestion.structuralRole, suggestion.embeddingRole, suggestion.productRegionRole, suggestion.productLane],
        rationale: suggestion.rationale,
        facts: [
            fact('Surface', suggestion.surface),
            fact('Candidate', suggestion.candidateLabel || label(suggestion.candidateEntityId, labels)),
            fact('Competing IDs', suggestion.competingEntityIds.join(' / ')),
            fact('Span', span(suggestion.sourceStart, suggestion.sourceEnd)),
            fact('Signals', (suggestion.rerankSignals || []).join(' / ')),
        ],
    });
}

function relationshipRecord(
    row: GraphRebuildRelationship,
    labels: Map<string, string>,
): GraphDiscourseWorkbenchRecord {
    return record({
        id: `relations:relationship:${row.id}`,
        tab: 'relations',
        kind: 'relationship',
        title: titleCase(row.relationType),
        subtitle: route(row.sourceEntityId, row.targetEntityId, labels),
        detail: row.rationale || titleCase(row.status),
        status: row.status,
        score: row.adjudicationScore || row.confidence,
        tone: row.status === 'accepted' ? 'ready' : row.status === 'rejected' ? 'danger' : 'review',
        focusQuery: focus([row.sourceEntityId, row.targetEntityId], labels),
        sourceIds: [row.sourceEntityId],
        targetIds: [row.targetEntityId],
        evidenceIds: [...row.evidenceAnchorIds, ...row.decisionEvidence],
        entityIds: [row.sourceEntityId, row.targetEntityId],
        tags: [row.status, row.adjudicationSource],
        rationale: [row.rationale],
        facts: [
            fact('Source', label(row.sourceEntityId, labels)),
            fact('Target', label(row.targetEntityId, labels)),
            fact('Evidence anchors', row.evidenceAnchorIds.join(' / ')),
            fact('Decision evidence', row.decisionEvidence.join(' / ')),
        ],
    });
}

function causalRecord(edge: GraphRebuildCausalEdge, labels: Map<string, string>): GraphDiscourseWorkbenchRecord {
    return record({
        id: `stance:causal:${edge.id}`,
        tab: 'stance',
        kind: `causal:${edge.polarity}`,
        title: titleCase(edge.relationType),
        subtitle: route(edge.sourceId, edge.targetId, labels),
        detail: `${titleCase(edge.status)} / ${titleCase(edge.modality)} / ${titleCase(edge.sourceSemantics)}`,
        status: edge.status,
        score: edge.confidence,
        tone: edge.polarity === 'contradict' || edge.status === 'rejected' ? 'danger' : edge.status === 'deferred' ? 'review' : 'ready',
        focusQuery: focus([edge.sourceId, edge.targetId, ...(edge.supportIds || [])], labels),
        sourceIds: [edge.sourceId],
        targetIds: [edge.targetId],
        evidenceIds: edge.evidenceIds,
        tags: [edge.polarity, edge.sourceKind, edge.evidenceClass, edge.cue],
        rationale: [edge.rationale],
        facts: [
            fact('Source', label(edge.sourceId, labels)),
            fact('Target', label(edge.targetId, labels)),
            fact('Cue', edge.cue || ''),
            fact('Support IDs', (edge.supportIds || []).join(' / ')),
            fact('Diagnostics', (edge.diagnosticCodes || []).join(' / ')),
        ],
    });
}

function documentReviewRecord(
    row: GraphDocumentReviewRow,
    labels: Map<string, string>,
): GraphDiscourseWorkbenchRecord {
    const tab = tabForDocumentReview(row);
    return record({
        id: `${tab}:document-review:${row.id}`,
        tab,
        kind: `document-review:${row.objectKind}`,
        title: row.title,
        subtitle: row.subtitle,
        detail: row.detail,
        status: row.state,
        score: row.confidence,
        tone: toneForDocumentReview(row),
        focusQuery: [row.title, row.detail, row.why.join(' ')].filter(Boolean).join(' '),
        sourceIds: [row.objectId, ...row.parentUnitIds],
        targetIds: [...row.childUnitIds, ...row.relatedObjectIds],
        evidenceIds: row.evidenceSpanIds,
        receiptIds: row.receiptIds,
        actionKinds: row.availableActions.map((action) => action.kind),
        tags: [
            row.state,
            row.objectKind,
            row.detector,
            row.duplicateGroupId ? 'duplicate_group' : '',
            ...row.availableActions.filter((action) => action.requiresUserIntent).map((action) => action.kind),
        ],
        rationale: row.why,
        facts: [
            fact('Object', row.objectId),
            fact('State', row.state),
            fact('Span', span(row.sourceStart, row.sourceEnd)),
            fact('Actions', row.availableActions.map((action) => action.label).join(' / ')),
            fact('Parents', row.parentUnitIds.join(' / ')),
            fact('Children', row.childUnitIds.slice(0, 6).join(' / ')),
            fact('Evidence', row.evidenceSpanIds.join(' / ')),
            fact('Related', row.relatedObjectIds.join(' / ')),
        ],
    });
}

function documentCompilerRecord(
    diff: GraphDocumentTopologyDiff,
    summary: GraphDocumentCompilerSummary,
    labels: Map<string, string>,
): GraphDiscourseWorkbenchRecord {
    const receipt = summary.receipts.find((row) => row.topologyDiffId === diff.id);
    const hyperedge = summary.hyperedges.find((row) => row.id === diff.outputId);
    const relation = summary.relationCandidates.find((row) => row.id === diff.outputId);
    const bridge = summary.crossDocBridges.find((row) => row.id === diff.outputId);
    const retrieval = summary.retrievalOverlays.find((row) => row.id === diff.outputId);
    const structure = summary.documentStructureEdges.find((row) => row.id === diff.outputId);
    const roleSummary = hyperedge?.roles
        .map((role) => `${role.role}:${label(role.targetId, labels) || role.surface || role.targetId}`)
        .slice(0, 6)
        .join(' / ');
    return record({
        id: `${tabForDocumentCompiler(diff)}:document-compiler:${diff.id}`,
        tab: tabForDocumentCompiler(diff),
        kind: `document-compiler:${diff.outputKind}`,
        title: compilerTitle(diff, summary),
        subtitle: `${titleCase(diff.status)} / ${titleCase(diff.outputKind)}`,
        detail: diff.topologyCommit ? 'topology diff ready for commit' : 'visible ledger or overlay output',
        status: diff.status,
        score: compilerScore(diff, summary),
        tone: toneForDocumentCompiler(diff),
        focusQuery: [
            compilerTitle(diff, summary),
            bridge?.topic,
            retrieval?.retrievalKind,
            structure ? route(structure.parentUnitId, structure.childUnitId, labels) : '',
            roleSummary,
            diff.rationale.join(' '),
        ].filter(Boolean).join(' '),
        sourceIds: [diff.outputId, receipt?.topologyDiffId, ...diff.createdAtomIds],
        targetIds: [...diff.createdFactIds, ...diff.createdEdgeIds],
        evidenceIds: diff.evidenceSpanIds,
        receiptIds: [receipt?.id],
        tags: [
            diff.outputKind,
            diff.operation,
            diff.status,
            diff.topologyCommit ? 'topology_commit' : 'no_topology_commit',
            receipt?.invariant,
        ],
        rationale: diff.rationale,
        facts: [
            fact('Output', diff.outputId),
            fact('Operation', diff.operation),
            fact('Before graph', compilerGraphCounts(diff.beforeGraph)),
            fact('After graph', compilerGraphCounts(diff.afterGraph)),
            fact('Created atoms', labelsFor(diff.createdAtomIds, labels)),
            fact('Created facts', labelsFor(diff.createdFactIds, labels)),
            fact('Created edges', labelsFor(diff.createdEdgeIds, labels)),
            fact('Roles', roleSummary || relationRoleSummary(relation)),
            fact('Evidence', diff.evidenceSpanIds.join(' / ')),
            fact('Undo', receipt?.undoPatch.operation),
        ],
    });
}

function statRecords(snapshot: GraphRebuildSnapshot): GraphDiscourseWorkbenchRecord[] {
    const counters = snapshot.counters;
    const review = snapshot.documentReviewSummary;
    const compiler = snapshot.documentCompilerSummary;
    return [
        statRecord('nodes', 'Graph nodes', counters.nodes, `${counters.edges} edges`),
        statRecord('targets', 'Embedding targets', counters.embeddingTargets, `${counters.embeddingVectors} vectors`),
        statRecord('relationships', 'Relationships', counters.relationships, `${counters.reviewRelationships || 0} review`),
        statRecord('overlay', 'Discourse overlay', snapshot.discourseCompilerOverlaySummary?.counters.overlayEdgeCount || 0, `${snapshot.discourseCompilerOverlaySummary?.counters.receiptCount || 0} receipts`),
        statRecord('ledger', 'Eval ledger', snapshot.discourseEvalLedgerSummary?.counters.rowCount || snapshot.semanticEvalLedgerSummary?.counters.rowCount || 0, 'review rows'),
        statRecord('document-review-proposed', 'Review proposed', review?.counters.proposedRows || 0, `${review?.counters.actionableRows || 0} actionable`),
        statRecord('document-review-ledger', 'Review ledger', review?.counters.ledgerOnlyRows || 0, `${review?.counters.stateRecords || 0} state records`),
        statRecord('document-review-receipts', 'Review receipts', review?.counters.receipts || 0, `${review?.counters.reversibleReceipts || 0} reversible`),
        statRecord('document-compiler-hyperedges', 'Compiler hyperedges', compiler?.counters.hyperedges || 0, `${compiler?.counters.naryHyperedges || 0} n-ary`),
        statRecord('document-compiler-diffs', 'Compiler diffs', compiler?.counters.topologyDiffs || 0, `${compiler?.counters.topologyCommits || 0} commits`),
        statRecord('document-compiler-receipts', 'Compiler receipts', compiler?.counters.receipts || 0, `${compiler?.counters.reversibleReceipts || 0} reversible`),
    ];
}

function statRecord(id: string, title: string, value: number, detail: string): GraphDiscourseWorkbenchRecord {
    return record({
        id: `stats:${id}`,
        tab: 'stats',
        kind: 'stat',
        title,
        subtitle: value.toLocaleString(),
        detail,
        status: 'observed',
        score: null,
        tone: value ? 'ready' : 'quiet',
        focusQuery: title,
        tags: ['stat'],
        facts: [fact('Value', value.toLocaleString()), fact('Detail', detail)],
    });
}

function record(input: WorkbenchRecordInput): GraphDiscourseWorkbenchRecord {
    const score = input.score ?? null;
    return {
        ...input,
        score,
        scoreLabel: score === null ? 'data' : percent(score),
        sourceIds: unique(input.sourceIds || []),
        targetIds: unique(input.targetIds || []),
        evidenceIds: unique(input.evidenceIds || []),
        entityIds: unique(input.entityIds || []),
        receiptIds: unique(input.receiptIds || []),
        actionKinds: unique(input.actionKinds || []),
        tags: unique(input.tags || []).slice(0, 8),
        rationale: unique(input.rationale || []).filter(Boolean),
        facts: (input.facts || []).filter((row) => row.value.trim()),
    };
}

function targetLabels(snapshot: GraphRebuildSnapshot, entities: RegisteredEntity[]): Map<string, string> {
    const labels = new Map<string, string>();
    for (const entity of entities) labels.set(entity.id, entity.label);
    for (const target of snapshot.embeddingTargets || []) {
        labels.set(target.id, target.label || target.text || target.sourceId);
        if (target.sourceId) labels.set(target.sourceId, target.label || target.text || target.sourceId);
    }
    for (const node of snapshot.nodes || []) labels.set(node.id, node.label || node.id);
    for (const unit of snapshot.documentSidecarSummary?.units || []) labels.set(unit.id, unit.label);
    for (const spanRow of snapshot.documentSidecarSummary?.evidenceSpans || []) labels.set(spanRow.id, spanRow.preview || spanRow.id);
    for (const mention of snapshot.documentCompilerSummary?.entityMentions || []) labels.set(mention.id, mention.surface);
    for (const hyperedge of snapshot.documentCompilerSummary?.hyperedges || []) labels.set(hyperedge.id, titleCase(hyperedge.predicate));
    for (const relation of snapshot.documentCompilerSummary?.relationCandidates || []) labels.set(relation.id, titleCase(relation.predicate));
    return labels;
}

function emptyTabMap(): Record<GraphDiscourseTabId, GraphDiscourseWorkbenchRecord[]> {
    return { insights: [], ideas: [], gaps: [], relations: [], stance: [], stats: [] };
}

function sortRecords(left: GraphDiscourseWorkbenchRecord, right: GraphDiscourseWorkbenchRecord): number {
    return (right.score ?? -1) - (left.score ?? -1) || left.title.localeCompare(right.title) || left.id.localeCompare(right.id);
}

function toneFor(labelValue: string, status: string): GraphDiscourseTone {
    if (labelValue === 'rejected_candidate' || status === 'rejected' || status === 'invalidated') return 'danger';
    if (labelValue === 'accepted_candidate' || status === 'accepted' || status === 'supported') return 'ready';
    if (labelValue === 'ambiguous_case' || labelValue.endsWith('_disagreement') || status === 'deferred' || status === 'proposed') return 'review';
    return 'quiet';
}

function tabForDocumentReview(row: GraphDocumentReviewRow): GraphDiscourseTabId {
    if (row.state === 'rejected' || row.state === 'muted') return 'stance';
    if (row.state === 'ledger_only') return 'stats';
    if (row.objectKind === 'graph_fact_candidate') return 'relations';
    if (row.objectKind === 'rhetorical_unit' || row.objectKind === 'document_region') return 'ideas';
    return 'insights';
}

function toneForDocumentReview(row: GraphDocumentReviewRow): GraphDiscourseTone {
    if (row.state === 'rejected' || row.state === 'muted') return 'danger';
    if (row.state === 'accepted' || row.state === 'promoted_to_anchor' || row.state === 'compiled_to_graph') return 'ready';
    if (row.state === 'proposed') return 'review';
    return 'quiet';
}

function tabForDocumentCompiler(diff: GraphDocumentTopologyDiff): GraphDiscourseTabId {
    if (diff.status === 'blocked') return 'stance';
    if (diff.status === 'reviewable') return 'gaps';
    if (diff.outputKind === 'hyperedge' || diff.outputKind === 'relation_candidate' || diff.outputKind === 'evidence_backed_edge') return 'relations';
    if (diff.outputKind === 'cross_doc_bridge' || diff.outputKind === 'document_structure_edge' || diff.outputKind === 'retrieval_overlay') return 'ideas';
    return 'stats';
}

function toneForDocumentCompiler(diff: GraphDocumentTopologyDiff): GraphDiscourseTone {
    if (diff.status === 'blocked') return 'danger';
    if (diff.status === 'reviewable') return 'review';
    if (diff.status === 'pending_commit') return 'ready';
    return 'quiet';
}

function compilerTitle(diff: GraphDocumentTopologyDiff, summary: GraphDocumentCompilerSummary): string {
    const hyperedge = summary.hyperedges.find((row) => row.id === diff.outputId);
    if (hyperedge) return titleCase(hyperedge.predicate);
    const relation = summary.relationCandidates.find((row) => row.id === diff.outputId);
    if (relation) return titleCase(relation.predicate);
    const bridge = summary.crossDocBridges.find((row) => row.id === diff.outputId);
    if (bridge) return bridge.topic;
    const retrieval = summary.retrievalOverlays.find((row) => row.id === diff.outputId);
    if (retrieval) return titleCase(retrieval.retrievalKind);
    return titleCase(diff.outputKind);
}

function compilerScore(diff: GraphDocumentTopologyDiff, summary: GraphDocumentCompilerSummary): number | null {
    return summary.hyperedges.find((row) => row.id === diff.outputId)?.confidence
        ?? summary.relationCandidates.find((row) => row.id === diff.outputId)?.confidence
        ?? summary.crossDocBridges.find((row) => row.id === diff.outputId)?.confidence
        ?? summary.documentStructureEdges.find((row) => row.id === diff.outputId)?.confidence
        ?? summary.retrievalOverlays.find((row) => row.id === diff.outputId)?.confidence
        ?? null;
}

function compilerGraphCounts(counts: { atomCount: number; factCount: number; edgeCount: number }): string {
    return `${counts.atomCount} atoms / ${counts.factCount} facts / ${counts.edgeCount} edges`;
}

function relationRoleSummary(relation: GraphDocumentCompilerSummary['relationCandidates'][number] | undefined): string {
    if (!relation) return '';
    return `${relation.subjectMentionIds.length} subjects / ${relation.objectMentionIds.length} objects`;
}

function focus(ids: Array<string | undefined>, labels: Map<string, string>): string {
    return ids.map((id) => label(id, labels)).filter(Boolean).slice(0, 6).join(' ');
}

function route(source: string | undefined, target: string | undefined, labels: Map<string, string>): string {
    return `${label(source, labels) || 'source'} -> ${label(target, labels) || 'target'}`;
}

function label(id: string | undefined, labels: Map<string, string>): string {
    if (!id) return '';
    return labels.get(id) || id.replace(/^embed:/, '').replace(/:/g, ' ');
}

function labelsFor(ids: string[], labels: Map<string, string>): string {
    const values = ids.map((id) => label(id, labels)).filter(Boolean);
    return values.slice(0, 5).join(' / ') + (values.length > 5 ? ` / +${values.length - 5}` : '');
}

function fact(labelValue: string, value: unknown): GraphDiscourseFact {
    return { label: labelValue, value: String(value ?? '').trim() };
}

function graphDelta(edges: number, facts: string[]): string {
    return `${edges} edges / ${facts.length} facts`;
}

function span(start: number | undefined, end: number | undefined): string {
    return Number.isFinite(start) && Number.isFinite(end) ? `${start}-${end}` : '';
}

function percent(value: number): string {
    return `${Math.round(Math.max(0, Math.min(1, value || 0)) * 100)}%`;
}

function unique(values: Array<string | undefined>): string[] {
    return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
}

function titleCase(value: string): string {
    return value
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}
