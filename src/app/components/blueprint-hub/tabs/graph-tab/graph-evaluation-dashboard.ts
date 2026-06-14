import type {
    GraphIndexRunReceipt,
    GraphRebuildChunk,
    GraphRebuildSnapshot,
} from '../../../../graph-rebuild/graph-rebuild-snapshot';
import { profileLabel } from '../../../../graph-rebuild/graph-document-profile';

export type GraphEvaluationTone = 'healthy' | 'suspicious' | 'degraded' | 'quiet';
export type GraphEvaluationCategoryId = 'chunking' | 'structure' | 'semantic' | 'graph' | 'retrieval' | 'performance';

export interface GraphEvaluationRecord {
    id: string;
    title: string;
    detail: string;
    meta: string;
    tone: GraphEvaluationTone;
}

export interface GraphEvaluationMetric {
    id: string;
    categoryId: GraphEvaluationCategoryId;
    label: string;
    value: string;
    score: number | null;
    tone: GraphEvaluationTone;
    summary: string;
    why: string[];
    records: GraphEvaluationRecord[];
    distribution?: Array<{ label: string; value: number }>;
}

export interface GraphEvaluationCategory {
    id: GraphEvaluationCategoryId;
    label: string;
    score: number | null;
    tone: GraphEvaluationTone;
    metricIds: string[];
}

export interface GraphEvaluationDashboard {
    verdict: 'Healthy' | 'Suspicious' | 'Degraded' | 'No data';
    score: number | null;
    tone: GraphEvaluationTone;
    headline: string;
    reasons: string[];
    scopeLabel: string;
    builtAt: number | null;
    runStatus: string;
    durationMs: number | null;
    noteIds: string[];
    metrics: GraphEvaluationMetric[];
    metricsById: Record<string, GraphEvaluationMetric>;
    categories: GraphEvaluationCategory[];
    stageRows: GraphEvaluationRecord[];
}

const CATEGORY_LABELS: Record<GraphEvaluationCategoryId, string> = {
    chunking: 'Chunking',
    structure: 'Structure',
    semantic: 'Semantic quality',
    graph: 'Graph impact',
    retrieval: 'Retrieval',
    performance: 'Performance',
};

export function buildGraphEvaluationDashboard(
    snapshot: GraphRebuildSnapshot | null,
    receipt: GraphIndexRunReceipt | null,
): GraphEvaluationDashboard {
    if (!snapshot) return emptyDashboard(receipt);
    const metrics = buildMetrics(snapshot, receipt);
    const scored = metrics.filter((metric) => metric.score !== null);
    const score = scored.length ? Math.round(scored.reduce((sum, metric) => sum + (metric.score || 0), 0) / scored.length) : null;
    const tone = score === null ? 'quiet' : score >= 80 ? 'healthy' : score >= 58 ? 'suspicious' : 'degraded';
    const verdict = score === null ? 'No data' : score >= 80 ? 'Healthy' : score >= 58 ? 'Suspicious' : 'Degraded';
    const concerns = scored.filter((metric) => metric.tone !== 'healthy').sort(scoreAscending).slice(0, 3);
    const strengths = scored.filter((metric) => metric.tone === 'healthy').sort(scoreDescending).slice(0, 2);
    const reasons = [
        ...concerns.map((metric) => `${metric.label}: ${metric.summary}`),
        ...strengths.map((metric) => `${metric.label}: ${metric.summary}`),
    ].slice(0, 4);
    const categories = categoryRows(metrics);
    return {
        verdict,
        score,
        tone,
        headline: verdict === 'Healthy'
            ? 'This indexing run is structurally coherent and retrieval-ready.'
            : verdict === 'Suspicious'
                ? 'The run completed, but a few signals deserve inspection.'
                : 'The run has quality failures that can distort retrieval or graph compilation.',
        reasons: reasons.length ? reasons : ['No scored evaluation signals are available yet.'],
        scopeLabel: receipt?.scope.label || snapshot.scopeId,
        builtAt: snapshot.builtAt,
        runStatus: receipt?.status || 'snapshot only',
        durationMs: receipt?.durationMs ?? snapshot.buildTimings?.totalMs ?? null,
        noteIds: snapshot.noteIds,
        metrics,
        metricsById: Object.fromEntries(metrics.map((metric) => [metric.id, metric])),
        categories,
        stageRows: stageRecords(receipt, snapshot),
    };
}

function buildMetrics(snapshot: GraphRebuildSnapshot, receipt: GraphIndexRunReceipt | null): GraphEvaluationMetric[] {
    const chunks = snapshot.chunks;
    const sizes = chunks.map(chunkSize).sort((a, b) => a - b);
    const mean = average(sizes);
    const deviation = standardDeviation(sizes, mean);
    const variation = mean > 0 ? deviation / mean : 0;
    const sizeScore = clampScore(100 - variation * 42);
    const overlaps = overlapRecords(chunks);
    const overlapChars = overlaps.reduce((sum, row) => sum + Number(row.meta.split(' ')[0] || 0), 0);
    const overlapRate = total(sizes) > 0 ? overlapChars / total(sizes) : 0;
    const overlapScore = clampScore(100 - Math.max(0, overlapRate - 0.16) * 240);
    const sidecar = snapshot.documentSidecarSummary;
    const profileSummary = sidecar?.documentProfileSummary;
    const profileCoverage = snapshot.noteIds.length
        ? (profileSummary?.profiles.length || 0) / snapshot.noteIds.length
        : 0;
    const profileScore = profileSummary
        ? clampScore(profileCoverage * 90 + (profileSummary.source === 'native_rust' ? 10 : 4))
        : null;
    const units = sidecar?.units || [];
    const maxDepth = units.reduce((depth, unit) => Math.max(depth, unit.depth), 0);
    const hierarchyScore = !units.length ? 35 : maxDepth >= 3 && maxDepth <= 8 ? 100 : maxDepth >= 2 ? 72 : 45;
    const coveredChunkIds = new Set<string>();
    for (const unit of units) if (unit.lineage.chunkId) coveredChunkIds.add(unit.lineage.chunkId);
    for (const unit of sidecar?.retrievalUnits || []) for (const id of unit.targetChunkIds) coveredChunkIds.add(id);
    const orphanChunks = chunks.filter((chunk) => !coveredChunkIds.has(chunk.id));
    const coverage = chunks.length ? (chunks.length - orphanChunks.length) / chunks.length : 0;
    const evidenceDensity = chunks.length ? (sidecar?.evidenceSpans.length || 0) / chunks.length : 0;
    const unresolvedPriors = unresolvedEntityPriors(snapshot);
    const priorCount = chunks.reduce((sum, chunk) => sum + (chunk.meaningFrame?.entityPriors.length || 0), 0);
    const priorNoise = priorCount ? unresolvedPriors.length / priorCount : 0;
    const review = snapshot.documentReviewSummary?.counters;
    const semantic = snapshot.semanticEvalLedgerSummary?.counters;
    const propositionSemantics = snapshot.documentSemanticSummary;
    const propositionCount = propositionSemantics?.counters.propositions || 0;
    const scopeCount = propositionSemantics
        ? propositionSemantics.counters.negated
            + propositionSemantics.counters.modal
            + propositionSemantics.counters.conditional
            + propositionSemantics.counters.attributed
            + propositionSemantics.counters.questions
            + propositionSemantics.counters.directives
        : 0;
    const reviewablePropositions = propositionSemantics?.counters.reviewable || 0;
    const ledgerOnlyPropositions = propositionSemantics?.counters.ledgerOnly || 0;
    const modifierPropositions = propositionSemantics?.counters.predicateModifiers || 0;
    const factualityCount = propositionSemantics?.counters.factualityAnnotations || 0;
    const recoveryCount = propositionSemantics?.counters.documentArgumentRecoveries || 0;
    const situationCount = propositionSemantics?.counters.situationInstances || 0;
    const stateIntervalCount = propositionSemantics?.counters.stateIntervals || 0;
    const eventOrderingCount = propositionSemantics?.counters.eventOrderings || 0;
    const explicitOrderingCount = propositionSemantics?.counters.explicitEventOrderings || 0;
    const temporalConflictCount = propositionSemantics?.counters.temporalConflicts || 0;
    const continuityScore = situationCount
        ? clampScore(92 - (temporalConflictCount / situationCount) * 500 + Math.min(8, explicitOrderingCount / Math.max(1, eventOrderingCount) * 8))
        : 35;
    const scopeRate = propositionCount ? Math.min(1, scopeCount / propositionCount) : 0;
    const predicatePrecisionRate = propositionCount ? reviewablePropositions / propositionCount : 0;
    const discourse = snapshot.discourseEvalLedgerSummary?.counters;
    const accepted = (review?.acceptedRows || 0) + (semantic?.acceptedCandidates || 0) + (discourse?.acceptedCandidates || 0);
    const rejected = (review?.rejectedRows || 0) + (semantic?.rejectedCandidates || 0) + (discourse?.rejectedCandidates || 0);
    const ambiguous = (review?.proposedRows || 0) + (semantic?.ambiguousCases || 0) + (discourse?.ambiguousCases || 0);
    const reviewedTotal = accepted + rejected + ambiguous;
    const acceptedRate = reviewedTotal ? accepted / reviewedTotal : 0;
    const compiler = snapshot.documentCompilerSummary;
    const nativeCandidates = compiler?.counters.nativeCompileCandidates || 0;
    const mutationLedger = snapshot.documentGraphMutationLedger;
    const commits = mutationLedger?.counters.active || 0;
    const reversibleReceipts = compiler?.counters.reversibleReceipts || 0;
    const mutationScore = commits === 0 && nativeCandidates >= 0
        ? 100
        : clampScore((commits / Math.max(1, nativeCandidates)) * 100);
    const retrieval = snapshot.memoryGraphRagBridgeSummary?.counters;
    const retrievalRate = retrieval?.evalRowCount ? retrieval.passedEvalRows / retrieval.evalRowCount : 0;
    const bridgeTotal = (discourse?.acceptedCandidates || 0) + (discourse?.rejectedCandidates || 0) + (discourse?.ambiguousCases || 0);
    const bridgeRate = bridgeTotal ? (discourse?.acceptedCandidates || 0) / bridgeTotal : 0;
    const durationMs = receipt?.durationMs ?? snapshot.buildTimings?.totalMs ?? null;
    const durationScore = durationMs === null ? null : durationMs <= 3000 ? 100 : durationMs <= 10000 ? 88 : durationMs <= 20000 ? 66 : 35;
    const compressedBytes = (snapshot.buildTimings?.snapshotPrimaryCompressedBytes || 0)
        + (snapshot.buildTimings?.snapshotOverGraphCompressedBytes || 0);
    return [
        metric('chunk-size', 'chunking', 'Chunk size distribution', `${chunks.length} chunks / ${formatNumber(percentile(sizes, 0.5))} median chars`, sizeScore,
            `${formatNumber(percentile(sizes, 0.1))}-${formatNumber(percentile(sizes, 0.9))} chars across the middle 80%.`,
            [`Variation coefficient ${variation.toFixed(2)}.`, `${sizes.filter((size) => size > 2000).length} chunks exceed 2,000 characters.`],
            longestChunkRecords(chunks), chunkDistribution(sizes)),
        metric('overlap-rate', 'chunking', 'Overlap rate', percent(overlapRate), overlapScore,
            overlaps.length ? `${overlaps.length} adjacent chunk pairs overlap.` : 'Chunk boundaries do not duplicate source ranges.',
            [`${formatNumber(overlapChars)} overlapping characters across ${formatNumber(total(sizes))} indexed characters.`], overlaps),
        metric('hierarchy-depth', 'structure', 'Hierarchy depth', `${maxDepth} levels`, hierarchyScore,
            units.length ? `The deepest document path reaches level ${maxDepth}.` : 'No document hierarchy was emitted.',
            [`${units.length} typed units and ${sidecar?.counters.parentChunks || 0} parent chunks were produced.`], deepestUnitRecords(units)),
        metric('orphan-chunks', 'structure', 'Orphan chunks', String(orphanChunks.length), orphanChunks.length ? clampScore(100 - orphanChunks.length / Math.max(1, chunks.length) * 180) : 100,
            orphanChunks.length ? 'Some leaf chunks have no sidecar lineage.' : 'Every leaf chunk participates in the document hierarchy.',
            [`${coveredChunkIds.size} chunk IDs are referenced by hierarchy or retrieval units.`], chunkRecords(orphanChunks, 'Missing hierarchy lineage')),
        metric('section-coverage', 'structure', 'Section coverage', percent(coverage), coverage * 100,
            `${chunks.length - orphanChunks.length} of ${chunks.length} chunks are reachable through typed document context.`,
            [`${sidecar?.counters.sections || 0} sections and ${sidecar?.counters.paragraphGroups || 0} paragraph groups contribute context.`], chunkRecords(orphanChunks, 'Uncovered chunk')),
        metric('document-adaptation', 'structure', 'Document adaptation', profileSummary?.profiles.length
            ? `${profileLabel(profileSummary.profiles[0].dominantProfile)} / ${percent(profileSummary.profiles[0].confidence)}`
            : 'Not classified', profileScore,
            profileSummary
                ? `${profileSummary.profiles.length} documents and ${profileSummary.counters.regions} regions were profiled by ${profileSummary.source === 'native_rust' ? 'native Rust' : 'the compatibility classifier'}.`
                : 'No document-type weighting profile is attached.',
            profileSummary
                ? [`${profileSummary.counters.signals} evidence signals explain the weighting.`, 'Profiles alter detector ranking and confidence, never the ontology or anchor registry.']
                : ['Run Full Atlas to generate document and region profiles.'], profileRecords(snapshot)),
        metric('evidence-density', 'semantic', 'Evidence density', `${evidenceDensity.toFixed(2)} spans/chunk`, clampScore(evidenceDensity * 82),
            `${sidecar?.evidenceSpans.length || 0} evidence spans support ${chunks.length} chunks.`,
            [`${sidecar?.counters.rhetoricalUnits || 0} rhetorical units and ${sidecar?.counters.graphFactCandidates || 0} graph-fact candidates can cite them.`], evidenceRecords(sidecar?.evidenceSpans || [])),
        metric('entity-prior-noise', 'semantic', 'Entity-prior noise', percent(priorNoise), clampScore(100 - priorNoise * 130),
            priorCount ? `${unresolvedPriors.length} of ${priorCount} entity priors lack a matching mention in their chunk.` : 'No entity priors were emitted.',
            ['Lower is better. A noisy prior can bias relation and event extraction before linking.'], unresolvedPriors),
        metric('proposition-substrate', 'semantic', 'Proposition substrate', propositionCount
            ? `${formatNumber(reviewablePropositions)} / ${formatNumber(propositionCount)} reviewable`
            : 'Not attached', propositionCount ? clampScore(72 + scopeRate * 28) : 35,
            propositionCount
                ? `${formatNumber(propositionSemantics?.counters.arguments || 0)} typed arguments feed reviewable facts, temporal axes, and causal analysis.`
                : 'The native proposition substrate did not run for this snapshot.',
            propositionSemantics
                ? [
                    `${formatNumber(propositionSemantics.counters.resolvedArguments)} arguments resolve directly to registered entities.`,
                    `${formatNumber(scopeCount)} scope readings capture negation, modality, conditionals, attribution, questions, or directives.`,
                    `${formatNumber(factualityCount)} truth envelopes classify assertion, quotation, belief, command, and conditional status.`,
                    `${formatNumber(recoveryCount)} document-window argument recoveries fill omitted subjects, quote speakers, aliases, or repeated event roles.`,
                    `${formatNumber(propositionSemantics.counters.nAry)} propositions preserve three or more semantic roles.`,
                    `${formatNumber(ledgerOnlyPropositions)} predicate readings stay ledger-only; ${formatNumber(modifierPropositions)} are modifier or nominal-event readings.`,
                ]
                : ['Run Full Atlas in the desktop app to attach native document semantics.'],
            semanticPropositionRecords(snapshot)),
        metric('predicate-precision', 'semantic', 'Predicate precision gate', propositionCount
            ? percent(predicatePrecisionRate)
            : 'Not attached', propositionCount ? clampScore(58 + predicatePrecisionRate * 34 - (modifierPropositions / Math.max(1, propositionCount)) * 18) : 35,
            propositionCount
                ? `${formatNumber(reviewablePropositions)} propositions can enter review; ${formatNumber(ledgerOnlyPropositions)} remain inspectable ledger rows.`
                : 'No predicate admission ledger is attached.',
            propositionSemantics
                ? [
                    `${formatNumber(modifierPropositions)} participle modifiers or nominal events were prevented from competing for graph-fact slots.`,
                    `${formatNumber(propositionSemantics.counters.predicateNoise || 0)} predicate readings were classified as noise.`,
                ]
                : ['Run native document semantics to classify predicate admission.'],
            semanticPropositionRecords(snapshot).filter((row) => row.tone === 'quiet').slice(0, 80)),
        metric('temporal-continuity', 'semantic', 'Temporal and state continuity', situationCount
            ? `${formatNumber(situationCount)} situations / ${formatNumber(temporalConflictCount)} conflicts`
            : 'Not attached', continuityScore,
            situationCount
                ? `${formatNumber(stateIntervalCount)} state intervals and ${formatNumber(eventOrderingCount)} event orderings preserve change across the document.`
                : 'No proposition-level situation timeline is attached.',
            propositionSemantics
                ? [
                    `${formatNumber(explicitOrderingCount)} orderings come from explicit before, after, during, or sequence cues.`,
                    `${formatNumber(propositionSemantics.counters.persistentStateIntervals || 0)} intervals persist across repeated mentions; ${formatNumber(propositionSemantics.counters.terminatedStateIntervals || 0)} terminate or transition.`,
                    `${formatNumber(propositionSemantics.counters.recurrenceOrderings || 0)} recurring situations link repeated events without merging their evidence.`,
                    `${formatNumber(propositionSemantics.counters.worldStateIneligibleSituations || 0)} scoped situations are retained but blocked from world-state commitment.`,
                ]
                : ['Run native document semantics to build continuity records.'],
            temporalContinuityRecords(snapshot)),
        metric('review-ratio', 'semantic', 'Accepted / rejected ratio', reviewedTotal ? `${accepted} / ${rejected}` : 'No decisions', reviewedTotal ? clampScore(acceptedRate * 115) : null,
            reviewedTotal ? `${percent(acceptedRate)} accepted across ${reviewedTotal} evaluated objects.` : 'The review ledger has not accumulated decisions yet.',
            [`${ambiguous} objects remain proposed or ambiguous.`], decisionRecords(snapshot)),
        metric('graph-mutations', 'graph', 'Graph mutation count', `${commits} commits / ${nativeCandidates} candidates`, mutationScore,
            commits ? `${commits} native commits are active with ${reversibleReceipts} reversible compiler receipts.` : 'No TypeScript durable topology mutation occurred during this run.',
            [`${nativeCandidates} semantic situation payloads are eligible for native graph compilation.`, `${mutationLedger?.counters.undone || 0} prior commits were undone.`, `${compiler?.counters.ledgerOnly || 0} outputs remained ledger-only.`], topologyRecords(snapshot)),
        metric('retrieval-quality', 'retrieval', 'Retrieval hit quality', retrieval?.evalRowCount ? percent(retrievalRate) : 'No eval rows', retrieval?.evalRowCount ? retrievalRate * 100 : null,
            retrieval?.evalRowCount ? `${retrieval.passedEvalRows} of ${retrieval.evalRowCount} retrieval checks passed.` : 'No retrieval evaluation ledger is available.',
            [`${retrieval?.failedEvalRows || 0} checks failed expected-layer retrieval.`], retrievalRecords(snapshot)),
        metric('bridge-quality', 'retrieval', 'Cross-doc bridge quality', bridgeTotal ? percent(bridgeRate) : 'No eval rows', bridgeTotal ? bridgeRate * 100 : null,
            bridgeTotal ? `${discourse?.acceptedCandidates || 0} of ${bridgeTotal} discourse bridge evaluations were accepted.` : 'No cross-document bridge evaluations are available.',
            [`${discourse?.ambiguousCases || 0} bridge cases remain ambiguous.`, `${discourse?.modelDisagreements || 0} model disagreements were recorded.`], bridgeRecords(snapshot)),
        metric('indexing-time', 'performance', 'Indexing time', durationMs === null ? 'Not captured' : formatDuration(durationMs), durationScore,
            durationMs === null ? 'No run receipt or build timing is attached.' : `${receipt?.stageReceipts.length || 0} pipeline stages completed in ${formatDuration(durationMs)}.`,
            stageTimingReasons(receipt, snapshot), stageRecords(receipt, snapshot)),
        metric('index-memory', 'performance', 'Indexing memory', compressedBytes ? `${formatBytes(compressedBytes)} snapshot` : 'Not captured', null,
            'Peak process memory is not instrumented yet; the displayed value is persisted snapshot footprint only.',
            [`Raw payload ${formatBytes(snapshot.buildTimings?.snapshotTotalPayloadChars || snapshot.buildTimings?.snapshotPayloadChars || 0)}.`, 'Add native RSS/heap high-water telemetry before using this as a memory benchmark.'], payloadRecords(snapshot)),
    ];
}

function metric(id: string, categoryId: GraphEvaluationCategoryId, label: string, value: string, score: number | null, summary: string, why: string[], records: GraphEvaluationRecord[], distribution?: Array<{ label: string; value: number }>): GraphEvaluationMetric {
    const normalizedScore = score === null ? null : clampScore(score);
    return { id, categoryId, label, value, score: normalizedScore, tone: toneForScore(normalizedScore), summary, why, records, distribution };
}

function categoryRows(metrics: GraphEvaluationMetric[]): GraphEvaluationCategory[] {
    return (Object.keys(CATEGORY_LABELS) as GraphEvaluationCategoryId[]).map((id) => {
        const rows = metrics.filter((metric) => metric.categoryId === id);
        const scores = rows.flatMap((metric) => metric.score === null ? [] : [metric.score]);
        const score = scores.length ? Math.round(average(scores)) : null;
        return { id, label: CATEGORY_LABELS[id], score, tone: toneForScore(score), metricIds: rows.map((metric) => metric.id) };
    });
}

function unresolvedEntityPriors(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    const mentionsByChunk = new Map<string, Set<string>>();
    for (const mention of snapshot.mentions) {
        if (!mention.chunkId) continue;
        const values = mentionsByChunk.get(mention.chunkId) || new Set<string>();
        values.add(normalize(mention.surface));
        mentionsByChunk.set(mention.chunkId, values);
    }
    const records: GraphEvaluationRecord[] = [];
    for (const chunk of snapshot.chunks) {
        const mentions = mentionsByChunk.get(chunk.id) || new Set<string>();
        for (const prior of chunk.meaningFrame?.entityPriors || []) {
            if (mentions.has(normalize(prior.surface))) continue;
            records.push({ id: `${chunk.id}:${prior.surface}`, title: prior.surface, detail: prior.reason, meta: `${chunk.id} / ${percent(prior.confidence)}`, tone: prior.confidence >= 0.75 ? 'suspicious' : 'quiet' });
        }
    }
    return records.slice(0, 80);
}

function overlapRecords(chunks: GraphRebuildChunk[]): GraphEvaluationRecord[] {
    const grouped = new Map<string, GraphRebuildChunk[]>();
    for (const chunk of chunks) grouped.set(chunk.noteId, [...(grouped.get(chunk.noteId) || []), chunk]);
    const records: GraphEvaluationRecord[] = [];
    for (const rows of grouped.values()) {
        rows.sort((a, b) => a.start - b.start);
        for (let index = 1; index < rows.length; index += 1) {
            const overlap = Math.max(0, rows[index - 1].end - rows[index].start);
            if (!overlap) continue;
            records.push({ id: `${rows[index - 1].id}:${rows[index].id}`, title: `${rows[index - 1].id} -> ${rows[index].id}`, detail: 'Adjacent source ranges overlap.', meta: `${overlap} chars overlap`, tone: 'suspicious' });
        }
    }
    return records;
}

function longestChunkRecords(chunks: GraphRebuildChunk[]): GraphEvaluationRecord[] {
    return chunks.slice().sort((a, b) => chunkSize(b) - chunkSize(a)).slice(0, 40).map((chunk) => ({ id: chunk.id, title: chunk.id, detail: chunk.splitReason || chunk.role || chunk.source, meta: `${formatNumber(chunkSize(chunk))} chars / ${chunk.noteId}`, tone: chunkSize(chunk) > 2000 ? 'suspicious' : 'quiet' }));
}

function chunkRecords(chunks: GraphRebuildChunk[], detail: string): GraphEvaluationRecord[] {
    return chunks.slice(0, 80).map((chunk) => ({ id: chunk.id, title: chunk.id, detail, meta: `${chunk.noteId} / ${formatNumber(chunkSize(chunk))} chars`, tone: 'suspicious' }));
}

function deepestUnitRecords(units: NonNullable<GraphRebuildSnapshot['documentSidecarSummary']>['units']): GraphEvaluationRecord[] {
    return units.slice().sort((a, b) => b.depth - a.depth).slice(0, 60).map((unit) => ({ id: unit.id, title: unit.label, detail: `${unit.kind} / ${unit.confidence.reasons.join(', ')}`, meta: `depth ${unit.depth} / ${unit.noteId}`, tone: unit.depth < 2 ? 'suspicious' : 'quiet' }));
}

function evidenceRecords(spans: NonNullable<GraphRebuildSnapshot['documentSidecarSummary']>['evidenceSpans']): GraphEvaluationRecord[] {
    return spans.slice(0, 80).map((span) => ({ id: span.id, title: span.preview || span.id, detail: span.confidence.reasons.join(', '), meta: `${span.noteId} / ${percent(span.confidence.score)}`, tone: span.confidence.score < 0.55 ? 'suspicious' : 'quiet' }));
}

function semanticPropositionRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    return (snapshot.documentSemanticSummary?.documents || []).flatMap((document) =>
        document.propositions.map((proposition) => {
            const unresolvedRoles = proposition.arguments.filter((argument) =>
                argument.roleFailureReasons?.includes('unresolved_entity'),
            ).length;
            const recovered = proposition.documentArgumentRecoveries?.length || 0;
            return {
                id: proposition.id,
                title: proposition.predicate || proposition.relationType,
                detail: proposition.preview,
                meta: `${proposition.factuality?.factuality || 'asserted'} / ${proposition.frame?.frame || 'unframed'} / ${proposition.frame?.source || 'no_frame_source'} / ${proposition.predicateQuality || 'predicate'} / ${proposition.arguments.length} roles + ${recovered} recovered / ${unresolvedRoles} unresolved / ${Math.round(proposition.confidenceMillis / 10)}% confidence`,
                tone: proposition.reviewState === 'proposed' ? 'suspicious' as const : 'quiet' as const,
            };
        }),
    );
}

function temporalContinuityRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    return (snapshot.documentSemanticSummary?.documents || []).flatMap((document) => [
        ...(document.temporalConflicts || []).map((conflict) => ({
            id: conflict.id,
            title: conflict.kind.replace(/_/g, ' '),
            detail: conflict.detectorReasons.join(', '),
            meta: `${conflict.severity} / ${Math.round(conflict.confidenceMillis / 10)}% / ${document.noteId}`,
            tone: conflict.severity === 'high' ? 'degraded' as const : 'suspicious' as const,
        })),
        ...(document.stateIntervals || []).slice(0, 40).map((interval) => ({
            id: interval.id,
            title: `${interval.subjectKey}: ${interval.predicate}`,
            detail: interval.detectorReasons.join(', '),
            meta: `${interval.status} / ${interval.polarity} / ${interval.mentionSituationIds.length} mentions`,
            tone: interval.failureReasons.length ? 'suspicious' as const : 'quiet' as const,
        })),
        ...(document.eventOrderings || []).slice(0, 40).map((ordering) => ({
            id: ordering.id,
            title: ordering.relation.replace(/_/g, ' '),
            detail: ordering.detectorReasons.join(', '),
            meta: `${ordering.source} / ${Math.round(ordering.confidenceMillis / 10)}%`,
            tone: ordering.failureReasons.length ? 'suspicious' as const : 'quiet' as const,
        })),
    ]).slice(0, 120);
}

function profileRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    const summary = snapshot.documentSidecarSummary?.documentProfileSummary;
    if (!summary) return [];
    return summary.profiles.map((profile) => ({
        id: `profile:${profile.noteId}`,
        title: profileLabel(profile.dominantProfile),
        detail: profile.signals.slice(0, 4).map((signal) => `${signal.cue} x${signal.occurrences}`).join(', ') || 'No strong lexical cues.',
        meta: `${profile.noteId} / ${percent(profile.confidence)} / ${profile.regions.length} regions`,
        tone: summary.source === 'native_rust' ? 'healthy' : 'quiet',
    }));
}

function decisionRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    const rows = [
        ...(snapshot.semanticEvalLedgerSummary?.compactExport.rows || []),
        ...(snapshot.discourseEvalLedgerSummary?.compactExport.rows || []),
    ];
    return rows.slice(0, 100).map((row) => ({ id: row.id, title: row.kind, detail: row.flags.join(', '), meta: `${row.state} / ${percent(row.score)}`, tone: row.label === 'accepted_candidate' ? 'healthy' : row.label === 'ambiguous_case' ? 'suspicious' : 'degraded' }));
}

function topologyRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    const committed = (snapshot.documentGraphMutationLedger?.records || []).map((row) => ({
        id: row.id,
        title: row.status === 'committed' ? 'Native graph commit' : 'Native graph undo',
        detail: `${row.vertexIds.length} owned vertices / ${row.edgeKeys.length} owned edges`,
        meta: `${row.status} / ${row.topologyDiffId}`,
        tone: row.status === 'committed' ? 'healthy' as const : 'quiet' as const,
    }));
    const diffs = (snapshot.documentCompilerSummary?.topologyDiffs || []).map((row) => ({ id: row.id, title: row.operation, detail: row.rationale.join(', '), meta: `${row.status} / ${row.outputKind}`, tone: row.status === 'blocked' ? 'degraded' as const : row.status === 'reviewable' ? 'suspicious' as const : 'quiet' as const }));
    return [...committed, ...diffs].slice(0, 80);
}

function retrievalRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    return (snapshot.memoryGraphRagBridgeSummary?.compactEvalLedger.rows || []).slice(0, 80).map((row) => ({ id: row.id, title: row.kind, detail: row.failures.length ? row.failures.join(', ') : 'Expected retrieval layer found.', meta: `${row.expectedLayer} / ${percent(row.score)}`, tone: row.passed ? 'healthy' : 'degraded' }));
}

function bridgeRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    return (snapshot.discourseEvalLedgerSummary?.compactExport.rows || []).slice(0, 80).map((row) => ({ id: row.id, title: row.kind, detail: row.flags.join(', '), meta: `${row.state} / ${percent(row.score)}`, tone: row.label === 'accepted_candidate' ? 'healthy' : 'suspicious' }));
}

function stageRecords(receipt: GraphIndexRunReceipt | null, snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    if (receipt?.stageReceipts.length) return receipt.stageReceipts.map((stage) => ({ id: stage.id, title: stage.label, detail: stage.message, meta: `${formatDuration(stage.durationMs)} / ${stage.outputCount} outputs`, tone: stage.status === 'completed' ? 'healthy' : stage.status === 'failed' ? 'degraded' : 'suspicious' }));
    return Object.entries(snapshot.buildTimings || {})
        .filter(([key, value]) => typeof value === 'number' && key.endsWith('Ms'))
        .slice(0, 30)
        .map(([key, value]) => ({ id: key, title: splitWords(key), detail: 'Graph rebuild timing', meta: formatDuration(Number(value)), tone: 'quiet' }));
}

function payloadRecords(snapshot: GraphRebuildSnapshot): GraphEvaluationRecord[] {
    const timings = snapshot.buildTimings;
    if (!timings) return [];
    return [
        { id: 'primary', title: 'Primary snapshot', detail: 'Compressed persisted graph rebuild snapshot.', meta: formatBytes(timings.snapshotPrimaryCompressedBytes || timings.snapshotPayloadChars), tone: 'quiet' },
        { id: 'overgraph', title: 'OverGraph snapshot', detail: 'Compressed projected graph model payload.', meta: formatBytes(timings.snapshotOverGraphCompressedBytes || 0), tone: 'quiet' },
    ];
}

function stageTimingReasons(receipt: GraphIndexRunReceipt | null, snapshot: GraphRebuildSnapshot): string[] {
    const stages = receipt?.stageReceipts || [];
    if (stages.length) return stages.slice().sort((a, b) => b.durationMs - a.durationMs).slice(0, 3).map((stage) => `${stage.label}: ${formatDuration(stage.durationMs)}.`);
    const timings = snapshot.buildTimings;
    return timings ? [`Snapshot build: ${formatDuration(timings.snapshotBuildMs)}.`, `Database operations: ${formatDuration(timings.dbOpsMs)}.`, `Persistence: ${formatDuration(timings.snapshotPersistMs)}.`] : ['No stage timing breakdown is attached.'];
}

function chunkDistribution(sizes: number[]) {
    const bins = [
        { label: '<300', min: 0, max: 300 },
        { label: '300-700', min: 300, max: 700 },
        { label: '700-1.2k', min: 700, max: 1200 },
        { label: '1.2-2k', min: 1200, max: 2000 },
        { label: '2k+', min: 2000, max: Infinity },
    ];
    return bins.map((bin) => ({ label: bin.label, value: sizes.filter((size) => size >= bin.min && size < bin.max).length }));
}

function emptyDashboard(receipt: GraphIndexRunReceipt | null): GraphEvaluationDashboard {
    return { verdict: 'No data', score: null, tone: 'quiet', headline: 'Run Full Atlas to generate an evaluation snapshot.', reasons: ['No graph rebuild snapshot is available for this scope.'], scopeLabel: receipt?.scope.label || 'Current scope', builtAt: null, runStatus: receipt?.status || 'not run', durationMs: receipt?.durationMs ?? null, noteIds: receipt?.scope.noteIds || [], metrics: [], metricsById: {}, categories: categoryRows([]), stageRows: [] };
}

function toneForScore(score: number | null): GraphEvaluationTone { return score === null ? 'quiet' : score >= 80 ? 'healthy' : score >= 58 ? 'suspicious' : 'degraded'; }
function clampScore(value: number): number { return Math.max(0, Math.min(100, Math.round(value))); }
function scoreAscending(a: GraphEvaluationMetric, b: GraphEvaluationMetric): number { return (a.score || 0) - (b.score || 0); }
function scoreDescending(a: GraphEvaluationMetric, b: GraphEvaluationMetric): number { return (b.score || 0) - (a.score || 0); }
function chunkSize(chunk: GraphRebuildChunk): number { return Math.max(0, chunk.end - chunk.start); }
function total(values: number[]): number { return values.reduce((sum, value) => sum + value, 0); }
function average(values: number[]): number { return values.length ? total(values) / values.length : 0; }
function standardDeviation(values: number[], mean: number): number { return values.length ? Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length) : 0; }
function percentile(values: number[], ratio: number): number { return values.length ? values[Math.min(values.length - 1, Math.max(0, Math.round((values.length - 1) * ratio)))] : 0; }
function percent(value: number): string { return `${Math.round(value * 100)}%`; }
function normalize(value: string): string { return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, ' '); }
function formatNumber(value: number): string { return Math.round(value).toLocaleString(); }
function formatDuration(value: number): string { return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`; }
function formatBytes(value: number): string { return value < 1024 ? `${Math.round(value)} B` : value < 1024 ** 2 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 ** 2).toFixed(1)} MB`; }
function splitWords(value: string): string { return value.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/Ms$/, '').replace(/^./, (letter) => letter.toUpperCase()); }
