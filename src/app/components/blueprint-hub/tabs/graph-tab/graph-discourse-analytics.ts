import type { RegisteredEntity } from '../../../../lib/registry';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import type { ProductDiagnosticsView } from './graph-product-diagnostics';

export type GraphDiscourseTabId = 'insights' | 'ideas' | 'gaps' | 'relations' | 'stance' | 'stats';
export type GraphDiscourseTone = 'ready' | 'review' | 'danger' | 'quiet';

export interface GraphDiscourseTab {
    id: GraphDiscourseTabId;
    label: string;
    index: number;
}

export interface GraphDiscourseMetric {
    id: string;
    label: string;
    value: string;
    detail: string;
    tone: GraphDiscourseTone;
}

export interface GraphDiscourseChip {
    id: string;
    label: string;
    detail: string;
    tone: GraphDiscourseTone;
    query: string;
}

export interface GraphDiscoursePanel {
    id: GraphDiscourseTabId;
    title: string;
    summary: string;
    bullets: string[];
    chips: GraphDiscourseChip[];
}

export interface GraphDiscourseQuestion {
    id: string;
    prompt: string;
    query: string;
    reason: string;
}

export interface GraphDiscourseUnderlyingIdea {
    id: string;
    title: string;
    detail: string;
    evidence: string;
    tone: GraphDiscourseTone;
}

export interface GraphDiscourseAnalyticsView {
    title: string;
    scopeLabel: string;
    summary: string;
    scoreLabel: string;
    tabs: GraphDiscourseTab[];
    metrics: GraphDiscourseMetric[];
    panels: Record<GraphDiscourseTabId, GraphDiscoursePanel>;
    questions: GraphDiscourseQuestion[];
    underlyingIdeas: GraphDiscourseUnderlyingIdea[];
}

const TABS: GraphDiscourseTab[] = [
    { id: 'insights', label: 'Insights', index: 1 },
    { id: 'ideas', label: 'Main Ideas', index: 2 },
    { id: 'gaps', label: 'Gaps', index: 3 },
    { id: 'relations', label: 'Relations', index: 4 },
    { id: 'stance', label: 'Stance', index: 5 },
    { id: 'stats', label: 'Stats', index: 6 },
];

export function buildGraphDiscourseAnalyticsView(
    snapshot: GraphRebuildSnapshot | null,
    diagnostics: ProductDiagnosticsView | null,
    selectedEntity: RegisteredEntity | null,
    entities: RegisteredEntity[],
): GraphDiscourseAnalyticsView | null {
    if (!snapshot) return null;

    const kindCounts = topCounts(entities.map((entity) => entity.kind), 5);
    const relationCounts = relationFamilies(snapshot);
    const stateCounts = topCountRecord(snapshot.semanticAdjudicationSummary?.counters.byState, 6);
    const candidateCounts = topCountRecord(snapshot.semanticCandidateSummary?.counters.byKind, 5);
    const ledgerCounters = snapshot.semanticEvalLedgerSummary?.counters;
    const bridgeCounters = snapshot.memoryGraphRagBridgeSummary?.counters;
    const reviewClusters = diagnostics?.reviewClusters ?? [];
    const topRegion = diagnostics?.summary.topRegions[0];
    const topKind = kindCounts[0];
    const accepted = ledgerCounters?.acceptedCandidates ?? snapshot.counters.semanticEvalAcceptedCandidates ?? 0;
    const rejected = ledgerCounters?.rejectedCandidates ?? snapshot.counters.semanticEvalRejectedCandidates ?? 0;
    const ambiguous = ledgerCounters?.ambiguousCases ?? snapshot.counters.semanticEvalAmbiguousCases ?? 0;
    const graphChanges = ledgerCounters?.graphChangeRows ?? snapshot.counters.semanticEvalGraphChangeRows ?? 0;
    const modelDisagreements = ledgerCounters?.modelDisagreements ?? snapshot.counters.semanticEvalModelDisagreements ?? 0;
    const manifoldDisagreements = ledgerCounters?.manifoldDisagreements ?? snapshot.counters.semanticEvalManifoldDisagreements ?? 0;
    const reviewLoad = reviewClusters.length + ambiguous + modelDisagreements + manifoldDisagreements;
    const title = selectedEntity ? selectedEntity.label : scopeTitle(snapshot);
    const scopeLabel = `${snapshot.scopeKind} / ${snapshot.noteIds.length || 1} notes`;
    const summary = selectedEntity
        ? selectedSummary(selectedEntity, topRegion, relationCounts[0], reviewLoad)
        : globalSummary(topKind, topRegion, relationCounts[0], reviewLoad, graphChanges);
    const scoreLabel = `${accepted} accepted / ${rejected} rejected / ${ambiguous} ambiguous`;
    const ideaChips = ideaChipsFor(diagnostics, kindCounts, relationCounts);
    const gapChips = gapChipsFor(reviewClusters, candidateCounts, snapshot);
    const relationChips = relationCounts.slice(0, 6).map((row) => chip(
        `relation:${row.key}`,
        titleCase(row.key),
        `${row.count} signals`,
        row.count > 8 ? 'ready' : 'quiet',
        row.key,
    ));
    const stanceChips = stanceChipsFor(snapshot);
    const metrics: GraphDiscourseMetric[] = [
        metric('ideas', 'Ideas', String(entities.length), topKind ? `${topKind.key} leads the entity surface` : 'no entity dominance yet', entities.length ? 'ready' : 'quiet'),
        metric('relations', 'Relations', String(snapshot.counters.relationships + (snapshot.graphAwareLinkSuggestions?.length || 0)), relationCounts[0] ? `${relationCounts[0].key} is the strongest relation family` : 'no relation family dominance', relationCounts.length ? 'ready' : 'quiet'),
        metric('gaps', 'Gaps', String(reviewLoad), `${reviewClusters.length} review clusters / ${modelDisagreements + manifoldDisagreements} disagreements`, reviewLoad ? 'review' : 'quiet'),
        metric('receipts', 'Receipts', String((bridgeCounters?.receiptCount || 0) + (snapshot.semanticAdjudicationSummary?.receipts.length || 0)), `${graphChanges} topology commits / ${snapshot.counters.semanticAdjudicationLedgerOnly || 0} ledger-only`, graphChanges ? 'ready' : 'quiet'),
    ];

    return {
        title,
        scopeLabel,
        summary,
        scoreLabel,
        tabs: TABS,
        metrics,
        panels: {
            insights: panel('insights', 'Receipt-backed read', summary, [
                `${scoreLabel} in the Phase 6 ledger.`,
                `${graphChanges} accepted decisions changed graph topology; rejected or deferred decisions stayed ledger-only.`,
                `${bridgeCounters?.evalRowCount || 0} memory bridge eval rows are available for retrieval sanity checks.`,
            ], [
                chip('insight:score-source', snapshot.semanticRerankSummary?.scoreSource || 'no rerank', `${snapshot.semanticRerankSummary?.judgments.length || 0} judgments`, 'ready', 'rerank'),
                chip('insight:commits', 'Topology commits', String(graphChanges), graphChanges ? 'ready' : 'quiet', 'accepted'),
                chip('insight:ledger', 'Eval rows', String(snapshot.semanticEvalLedgerSummary?.entries.length || 0), snapshot.semanticEvalLedgerSummary?.entries.length ? 'ready' : 'quiet', 'eval'),
            ]),
            ideas: panel('ideas', 'Main ideas summary', mainIdeaSummary(topKind, topRegion, relationCounts[0]), [
                topKind ? `${topKind.key} is the largest entity family with ${topKind.count} registered nodes.` : 'No dominant entity family yet.',
                topRegion ? `${topRegion.role}/${topRegion.lane} is the strongest product region.` : 'Product regions are not available yet.',
                relationCounts[0] ? `${titleCase(relationCounts[0].key)} is the most repeated relation surface.` : 'Relation families are still sparse.',
            ], ideaChips),
            gaps: panel('gaps', 'Content gaps', gapSummary(reviewLoad, ambiguous, modelDisagreements, manifoldDisagreements), [
                `${reviewClusters.length} review families are waiting for a human or classifier decision.`,
                `${ambiguous} ambiguous ledger rows need stronger evidence or identity resolution.`,
                `${snapshot.embeddingGraphPostProcess?.metrics.outlierCount || 0} embedding targets are marked as outliers.`,
            ], gapChips),
            relations: panel('relations', 'Relation field', relationSummary(relationCounts[0], snapshot), [
                `${snapshot.relationships.length} accepted or review relationship records are present.`,
                `${snapshot.graphAwareLinkSuggestions?.length || 0} graph-aware relation suggestions are staged.`,
                `${snapshot.causalEdges.length} causal and ${snapshot.temporalEdges.length} temporal edges are available for path questions.`,
            ], relationChips),
            stance: panel('stance', 'Stance and polarity', stanceSummary(snapshot), [
                `${snapshot.causalEdges.filter((edge) => edge.polarity === 'support').length} causal edges carry support polarity.`,
                `${snapshot.causalEdges.filter((edge) => edge.polarity === 'contradict').length} causal edges carry contradiction polarity.`,
                `${snapshot.semanticAdjudicationSummary?.counters.ledgerOnlyCount || 0} decisions trained the ledger without mutating topology.`,
            ], stanceChips),
            stats: panel('stats', 'Graph vitals', statsSummary(snapshot, diagnostics), [
                `${snapshot.counters.nodes} graph nodes / ${snapshot.counters.edges} graph edges.`,
                `${snapshot.counters.embeddingTargets} embedding targets / ${snapshot.counters.embeddingVectors} vectors.`,
                `${snapshot.buildTimings?.totalMs ? `${Math.round(snapshot.buildTimings.totalMs)}ms` : 'No timing'} total rebuild time recorded.`,
            ], [
                chip('stats:nodes', 'Nodes', String(snapshot.counters.nodes), snapshot.counters.nodes ? 'ready' : 'quiet', 'nodes'),
                chip('stats:edges', 'Edges', String(snapshot.counters.edges), snapshot.counters.edges ? 'ready' : 'quiet', 'edges'),
                chip('stats:vectors', 'Vectors', String(snapshot.counters.embeddingVectors), snapshot.counters.embeddingVectors ? 'ready' : 'quiet', 'vectors'),
            ]),
        },
        questions: questionsFor(selectedEntity, reviewClusters, relationCounts[0], topRegion, candidateCounts[0]),
        underlyingIdeas: underlyingIdeasFor(diagnostics, reviewClusters, snapshot, kindCounts, relationCounts),
    };
}

function panel(
    id: GraphDiscourseTabId,
    title: string,
    summary: string,
    bullets: string[],
    chips: GraphDiscourseChip[],
): GraphDiscoursePanel {
    return { id, title, summary, bullets, chips };
}

function metric(id: string, label: string, value: string, detail: string, tone: GraphDiscourseTone): GraphDiscourseMetric {
    return { id, label, value, detail, tone };
}

function chip(id: string, label: string, detail: string, tone: GraphDiscourseTone, query: string): GraphDiscourseChip {
    return { id, label, detail, tone, query };
}

function scopeTitle(snapshot: GraphRebuildSnapshot): string {
    if (snapshot.scopeKind === 'global') return 'Whole Atlas';
    if (snapshot.scopeKind === 'multiNote') return 'Compared Notes';
    return titleCase(snapshot.scopeKind);
}

function globalSummary(
    topKind: CountRow | undefined,
    topRegion: { role: string; lane: string; count: number } | undefined,
    topRelation: CountRow | undefined,
    reviewLoad: number,
    graphChanges: number,
): string {
    const kind = topKind ? `${topKind.key.toLowerCase()} entities` : 'registered entities';
    const region = topRegion ? `${topRegion.role} ${topRegion.lane}` : 'unsettled product regions';
    const relation = topRelation ? `${titleCase(topRelation.key)} relation pressure` : 'sparse relation pressure';
    return `The scope is currently organized around ${kind}, ${region}, and ${relation}. ${graphChanges} accepted decisions have already changed topology, while ${reviewLoad} cases still deserve review before they become graph structure.`;
}

function selectedSummary(
    entity: RegisteredEntity,
    topRegion: { role: string; lane: string; count: number } | undefined,
    topRelation: CountRow | undefined,
    reviewLoad: number,
): string {
    const region = topRegion ? `${topRegion.role}/${topRegion.lane}` : 'the current atlas region';
    const relation = topRelation ? titleCase(topRelation.key) : 'nearby relation';
    return `${entity.label} is being read through ${region} with ${relation} pressure nearby. ${reviewLoad} open review signals can change how this node should connect, summarize, or route retrieval.`;
}

function mainIdeaSummary(
    topKind: CountRow | undefined,
    topRegion: { role: string; lane: string; count: number } | undefined,
    topRelation: CountRow | undefined,
): string {
    const pieces = [
        topKind ? `${topKind.key} is the dominant entity family` : '',
        topRegion ? `${topRegion.role}/${topRegion.lane} is the dominant region` : '',
        topRelation ? `${titleCase(topRelation.key)} is the strongest relation theme` : '',
    ].filter(Boolean);
    return pieces.length ? pieces.join('; ') + '.' : 'The graph needs a fresh atlas run before main ideas can be ranked.';
}

function gapSummary(reviewLoad: number, ambiguous: number, modelDisagreements: number, manifoldDisagreements: number): string {
    if (!reviewLoad) return 'No major discourse gaps are visible in the current snapshot.';
    return `${reviewLoad} cases are not cleanly settled: ${ambiguous} ambiguous, ${modelDisagreements} model disagreements, and ${manifoldDisagreements} manifold disagreements.`;
}

function relationSummary(topRelation: CountRow | undefined, snapshot: GraphRebuildSnapshot): string {
    if (!topRelation) return 'Relations are present, but no single family dominates the current graph.';
    return `${titleCase(topRelation.key)} is the strongest repeated relation family across ${snapshot.relationships.length} relationship records and ${snapshot.graphAwareLinkSuggestions?.length || 0} graph-aware suggestions.`;
}

function stanceSummary(snapshot: GraphRebuildSnapshot): string {
    const support = snapshot.causalEdges.filter((edge) => edge.polarity === 'support').length;
    const contradict = snapshot.causalEdges.filter((edge) => edge.polarity === 'contradict').length;
    const rejected = snapshot.semanticEvalLedgerSummary?.counters.rejectedCandidates || 0;
    return `${support} causal links support claims, ${contradict} contradict them, and ${rejected} candidates were rejected into the eval ledger instead of poisoning topology.`;
}

function statsSummary(snapshot: GraphRebuildSnapshot, diagnostics: ProductDiagnosticsView | null): string {
    const clusters = diagnostics?.summary.clusterCount ?? snapshot.counters.embeddingClusters ?? 0;
    return `${snapshot.counters.nodes} nodes, ${snapshot.counters.edges} edges, ${snapshot.counters.embeddingTargets} embedding targets, and ${clusters} topology clusters are in the latest persisted snapshot.`;
}

function ideaChipsFor(
    diagnostics: ProductDiagnosticsView | null,
    kindCounts: CountRow[],
    relationCounts: CountRow[],
): GraphDiscourseChip[] {
    return [
        ...(diagnostics?.summary.topRegions || []).slice(0, 3).map((region) => chip(
            `region:${region.role}:${region.lane}`,
            `${titleCase(region.role)} ${region.lane}`,
            `${region.count} targets`,
            region.role === 'outlier' ? 'review' : 'ready',
            region.lane,
        )),
        ...kindCounts.slice(0, 2).map((row) => chip(`kind:${row.key}`, titleCase(row.key), `${row.count} entities`, 'ready', row.key)),
        ...relationCounts.slice(0, 2).map((row) => chip(`relation:${row.key}`, titleCase(row.key), `${row.count} relations`, 'ready', row.key)),
    ].slice(0, 6);
}

function gapChipsFor(
    reviewClusters: ProductDiagnosticsView['reviewClusters'],
    candidateCounts: CountRow[],
    snapshot: GraphRebuildSnapshot,
): GraphDiscourseChip[] {
    return [
        ...reviewClusters.slice(0, 3).map((cluster) => chip(
            `review:${cluster.id}`,
            cluster.label,
            `${cluster.count} cases`,
            cluster.conflicts ? 'danger' : 'review',
            cluster.label,
        )),
        ...candidateCounts.slice(0, 3).map((row) => chip(`candidate:${row.key}`, titleCase(row.key), `${row.count} candidates`, 'review', row.key)),
        chip('outliers', 'Outliers', String(snapshot.embeddingGraphPostProcess?.metrics.outlierCount || 0), snapshot.embeddingGraphPostProcess?.metrics.outlierCount ? 'review' : 'quiet', 'outlier'),
    ].slice(0, 6);
}

function stanceChipsFor(snapshot: GraphRebuildSnapshot): GraphDiscourseChip[] {
    const statusRows = topCounts(snapshot.causalEdges.map((edge) => edge.status), 3);
    const polarityRows = topCounts(snapshot.causalEdges.map((edge) => edge.polarity), 3);
    return [
        ...statusRows.map((row) => chip(`causal-status:${row.key}`, titleCase(row.key), `${row.count} edges`, row.key === 'rejected' ? 'danger' : 'ready', row.key)),
        ...polarityRows.map((row) => chip(`causal-polarity:${row.key}`, titleCase(row.key), `${row.count} edges`, row.key === 'contradict' ? 'review' : 'ready', row.key)),
    ].slice(0, 6);
}

function questionsFor(
    selectedEntity: RegisteredEntity | null,
    reviewClusters: ProductDiagnosticsView['reviewClusters'],
    topRelation: CountRow | undefined,
    topRegion: { role: string; lane: string; count: number } | undefined,
    topCandidate: CountRow | undefined,
): GraphDiscourseQuestion[] {
    const questions: GraphDiscourseQuestion[] = [];
    if (selectedEntity) {
        questions.push({
            id: 'selected-entity',
            prompt: `Where does ${selectedEntity.label} bridge ${topRelation ? titleCase(topRelation.key) : 'the strongest relation'} and ${topRegion ? topRegion.lane : 'regional'} pressure?`,
            query: selectedEntity.label,
            reason: 'selected entity focus',
        });
    }
    if (reviewClusters[0]) {
        questions.push({
            id: 'review-cluster',
            prompt: `Which evidence would resolve ${reviewClusters[0].label} without adding noisy graph edges?`,
            query: reviewClusters[0].label,
            reason: 'largest review cluster',
        });
    }
    if (topCandidate) {
        questions.push({
            id: 'candidate-gap',
            prompt: `What would turn ${titleCase(topCandidate.key)} from a candidate family into accepted structure?`,
            query: topCandidate.key,
            reason: 'candidate factory pressure',
        });
    }
    if (!questions.length) {
        questions.push({
            id: 'default',
            prompt: 'Which topic cluster should become the next retrieval route?',
            query: topRegion?.lane || topRelation?.key || '',
            reason: 'atlas overview',
        });
    }
    return questions.slice(0, 3);
}

function underlyingIdeasFor(
    diagnostics: ProductDiagnosticsView | null,
    reviewClusters: ProductDiagnosticsView['reviewClusters'],
    snapshot: GraphRebuildSnapshot,
    kindCounts: CountRow[],
    relationCounts: CountRow[],
): GraphDiscourseUnderlyingIdea[] {
    const ideas: GraphDiscourseUnderlyingIdea[] = [];
    for (const region of diagnostics?.summary.topRegions || []) {
        ideas.push({
            id: `region:${region.role}:${region.lane}`,
            title: `${titleCase(region.role)} ${region.lane}`,
            detail: `${region.count} targets cluster here.`,
            evidence: 'product topology region',
            tone: region.role === 'outlier' ? 'review' : 'ready',
        });
    }
    for (const cluster of reviewClusters.slice(0, 4)) {
        ideas.push({
            id: `review:${cluster.id}`,
            title: cluster.label,
            detail: cluster.action,
            evidence: `${cluster.count} candidates / ${cluster.conflicts} conflicts`,
            tone: cluster.conflicts ? 'danger' : 'review',
        });
    }
    for (const row of [...kindCounts.slice(0, 2), ...relationCounts.slice(0, 2)]) {
        ideas.push({
            id: `count:${row.key}`,
            title: titleCase(row.key),
            detail: `${row.count} repeated signals.`,
            evidence: 'scope frequency',
            tone: 'ready',
        });
    }
    if (snapshot.memoryGraphRagBridgeSummary) {
        ideas.push({
            id: 'memory-bridge',
            title: 'Memory retrieval bridge',
            detail: `${snapshot.memoryGraphRagBridgeSummary.counters.evalRowCount} eval rows are ready.`,
            evidence: 'MemoryGraphRAG bridge contract',
            tone: 'ready',
        });
    }
    return ideas.slice(0, 8);
}

interface CountRow {
    key: string;
    count: number;
}

function relationFamilies(snapshot: GraphRebuildSnapshot): CountRow[] {
    return topCounts([
        ...snapshot.relationships.map((row) => row.relationType),
        ...(snapshot.graphAwareLinkSuggestions || []).map((row) => row.suggestedRelationType),
        ...snapshot.edges.map((row) => row.type),
    ], 8);
}

function topCountRecord(record: Record<string, number> | undefined, limit: number): CountRow[] {
    return Object.entries(record || {})
        .map(([key, count]) => ({ key, count }))
        .filter((row) => row.count > 0)
        .sort(sortCounts)
        .slice(0, limit);
}

function topCounts(values: Array<string | undefined | null>, limit: number): CountRow[] {
    const counts = new Map<string, number>();
    for (const raw of values) {
        const key = String(raw || '').trim();
        if (!key) continue;
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()]
        .map(([key, count]) => ({ key, count }))
        .sort(sortCounts)
        .slice(0, limit);
}

function sortCounts(left: CountRow, right: CountRow): number {
    return right.count - left.count || left.key.localeCompare(right.key);
}

function titleCase(value: string): string {
    return value
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}
