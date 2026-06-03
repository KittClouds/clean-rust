import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { dynamicChunksForNote } from './graph-rebuild.service';
import type {
    GraphRebuildChunk,
    GraphRebuildScopeKind,
    GraphRebuildSnapshot,
    GraphSemanticManifoldKind,
} from './graph-rebuild-snapshot';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';

interface ParityFixture {
    noteId: string;
    scopeKind: GraphRebuildScopeKind;
    scopeId: string;
    builtAt: number;
    text: string;
    entities: FixtureEntity[];
    chunks: GraphRebuildChunk[];
    occurrences: FixtureOccurrence[];
    expected: StructuralDigest;
}

interface FixtureEntity {
    id: string;
    label: string;
    kind: string;
    aliases: string[];
}

interface FixtureOccurrence {
    entityId: string;
    entityLabel: string;
    entityKind: string;
    surface: string;
    sourceStart: number;
    sourceEnd: number;
    source: string;
    confidence: number;
}

interface RelationshipDigest {
    id: string;
    relationType: string;
    status: string;
}

interface StructuralDigest {
    relationships: RelationshipDigest[];
    eventCount: number;
    memoryStateCount: number;
    embeddingTargetKindCounts: Record<string, number>;
}

describe('Phoenix graph rebuild parity smoke', () => {
    it('matches the shared Rust/Angular structural fixture', () => {
        const fixture = loadFixture();
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: fixture.scopeKind,
            scopeId: fixture.scopeId,
            noteIds: [fixture.noteId],
            entities: fixture.entities.map(toRegisteredEntity),
            chunks: fixture.chunks,
            occurrences: fixture.occurrences.map((occurrence) => toOccurrence(fixture.noteId, occurrence)),
            candidateCount: fixture.occurrences.length,
            noteTexts: { [fixture.noteId]: fixture.text },
            builtAt: fixture.builtAt,
        });

        expect(structuralDigest(snapshot)).toEqual(fixture.expected);
    });

    it('keeps the Kai and Rowan story pass conservative before linker models', () => {
        const text = [
            'Kai held Tempest gaze while Baton Rouge made the room too loud.',
            'Rowan came to stand behind Hazel as Allied Table opened the packet.',
            'Kai Rowan refused to let the command turn into ownership.',
        ].join(' ');
        const kaiStart = text.indexOf('Kai');
        const rowanStart = text.indexOf('Rowan');
        const alliedStart = text.indexOf('Allied Table');
        const batonStart = text.indexOf('Baton Rouge');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:kai-rowan',
            noteIds: ['kai-rowan'],
            entities: [
                registeredEntity('e-kai-rowan', 'Kai Rowan', 'CHARACTER', ['Kai']),
                registeredEntity('e-rowan', 'Rowan', 'CHARACTER', []),
                registeredEntity('e-hazel', 'Hazel', 'CHARACTER', []),
                registeredEntity('e-tempest', 'Tempest', 'CHARACTER', []),
                registeredEntity('e-allied-table', 'Allied Table', 'ORGANIZATION', []),
                registeredEntity('e-baton-rouge', 'Baton Rouge', 'LOCATION', []),
            ],
            chunks: [{ id: 'kai-rowan:chunk:0', noteId: 'kai-rowan', start: 0, end: text.length, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences: [
                occurrence('kai-rowan', 'missing-kai', 'Kai', 'LOCATION', kaiStart, kaiStart + 3, 'machine_suggestion'),
                occurrence('kai-rowan', 'e-kai-rowan', 'Kai', 'CHARACTER', kaiStart, kaiStart + 3, 'dictionary_match'),
                occurrence('kai-rowan', 'e-rowan', 'Rowan', 'CHARACTER', rowanStart, rowanStart + 5, 'dictionary_match'),
                occurrence('kai-rowan', 'missing-allied', 'Allied Table', 'LOCATION', alliedStart, alliedStart + 12, 'machine_suggestion'),
                occurrence('kai-rowan', 'missing-baton', 'Baton Rouge', 'LOCATION', batonStart, batonStart + 11, 'machine_suggestion'),
            ],
            candidateCount: 5,
            noteTexts: { 'kai-rowan': text },
            builtAt: 20,
        });

        expect(snapshot.nodes.map((node) => node.id)).toEqual(expect.arrayContaining(['e-kai-rowan', 'e-rowan', 'e-allied-table', 'e-baton-rouge']));
        expect(snapshot.counters.dropReasons.duplicateAnchor).toBe(1);
        expect(snapshot.counters.dropReasons.missingEntity).toBe(0);
        expect(snapshot.counters.resolution).toMatchObject({
            resolvedById: 2,
            resolvedByAlias: 1,
            resolvedByLabel: 2,
            kindConflicts: 2,
            droppedDuplicateSpans: 1,
        });
        expect(snapshot.resolutionSuggestions?.map((row) => row.kind)).toEqual(expect.arrayContaining(['possible_alias', 'kind_conflict']));
        expect(snapshot.counters.entityLinking).toMatchObject({
            candidateMentions: 1,
        });
        expect(snapshot.counters.entityLinkSuggestions).toBeGreaterThan(0);
        expect(snapshot.counters.entityLinking?.autoConfirmable).toBe(0);
    });

    it('smokes deterministic pre-linking over docs/shortrun.md baseline text', () => {
        const text = readFileSync(new URL('../../../docs/shortrun.md', import.meta.url), 'utf8').slice(0, 24000);
        const occurrences = [
            ...surfaceOccurrences(text, 'shortrun', 'e-ryan', 'Ryan', 'CHARACTER', 'dictionary_match', 2),
            ...surfaceOccurrences(text, 'shortrun', 'missing-quicksave', 'Quicksave', 'CHARACTER', 'machine_suggestion', 2),
            ...surfaceOccurrences(text, 'shortrun', 'missing-new-rome', 'New Rome', 'LOCATION', 'machine_suggestion', 2),
            ...surfaceOccurrences(text, 'shortrun', 'missing-renesco', 'Renesco', 'CHARACTER', 'machine_suggestion', 2),
            ...surfaceOccurrences(text, 'shortrun', 'missing-dynamis', 'Dynamis', 'ORGANIZATION', 'machine_suggestion', 2),
            ...surfaceOccurrences(text, 'shortrun', 'missing-rust-town', 'Rust Town', 'LOCATION', 'machine_suggestion', 2),
        ];
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:shortrun',
            noteIds: ['shortrun'],
            entities: [
                registeredEntity('e-ryan', 'Ryan', 'CHARACTER', ['Quicksave']),
                registeredEntity('e-new-rome', 'New Rome', 'LOCATION', []),
                registeredEntity('e-renesco', 'Renesco', 'CHARACTER', []),
                registeredEntity('e-dynamis', 'Dynamis', 'ORGANIZATION', []),
                registeredEntity('e-rust-town', 'Rust Town', 'LOCATION', []),
            ],
            chunks: [{ id: 'shortrun:chunk:0', noteId: 'shortrun', start: 0, end: text.length, ordinal: 0, source: 'dynamic-chunking' }],
            occurrences,
            candidateCount: occurrences.length,
            noteTexts: { shortrun: text },
            builtAt: 21,
        });

        expect(occurrences.length).toBeGreaterThanOrEqual(8);
        expect(snapshot.counters.dropReasons.missingEntity).toBe(0);
        expect(snapshot.counters.acceptedAnchors).toBe(occurrences.length);
        expect(snapshot.counters.resolution?.resolvedByAlias).toBeGreaterThan(0);
        expect(snapshot.counters.resolution?.resolvedByLabel).toBeGreaterThan(0);
        expect(snapshot.nodes.map((node) => node.id)).toEqual(expect.arrayContaining(['e-ryan', 'e-new-rome', 'e-renesco', 'e-dynamis', 'e-rust-town']));
        expect(kindCounts(snapshot.embeddingTargets.map((target) => target.kind)).graphFact || 0).toBeGreaterThanOrEqual(0);
        expect(snapshot.counters.entityLinkSuggestions).toBeGreaterThanOrEqual(0);
    });

    it('keeps dense shortrun embedding targets signal-weighted before graph postprocess', () => {
        const text = readFileSync(new URL('../../../docs/shortrun.md', import.meta.url), 'utf8');
        const chunks = dynamicChunksForNote({ id: 'shortrun-dense', markdownContent: text, content: '' });
        const surfaces = candidateSurfaces(text).slice(0, 48);
        const entities = surfaces.map((surface, index) =>
            registeredEntity(`dense-${index}:${normalizeId(surface)}`, surface, likelyKind(surface), []),
        );
        const occurrences = entities.flatMap((entity) =>
            surfaceOccurrences(text, 'shortrun-dense', entity.id, entity.label, entity.kind, 'dictionary_match', 120),
        );
        const started = performance.now();
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:shortrun-dense',
            noteIds: ['shortrun-dense'],
            entities,
            chunks,
            occurrences,
            candidateCount: occurrences.length,
            noteTexts: { 'shortrun-dense': text },
            builtAt: 22,
        });
        const elapsedMs = performance.now() - started;
        const counts = kindCounts(snapshot.embeddingTargets.map((target) => target.kind));
        console.info('graph-rebuild-smoke', JSON.stringify({
            doc: 'shortrun',
            chars: text.length,
            chunks: chunks.length,
            occurrences: occurrences.length,
            events: snapshot.counters.events,
            causalEdges: snapshot.counters.causalEdges,
            targets: snapshot.counters.embeddingTargets,
            semanticTasks: snapshot.counters.semanticTasks,
            semanticCandidates: snapshot.counters.semanticCandidates,
            manifoldContributions: snapshot.counters.manifoldCandidateContributions,
            manifoldExplained: snapshot.counters.manifoldCandidateExplained,
            manifoldByManifold: snapshot.manifoldSpecializationSummary?.counters.byManifold,
            semanticRerankInputs: snapshot.counters.semanticRerankInputs,
            semanticRerankCalls: snapshot.counters.semanticRerankPlannedModelCalls,
            semanticRerankDecisions: snapshot.semanticRerankSummary?.counters.byDecision,
            semanticAdjudicationDecisions: snapshot.counters.semanticAdjudicationDecisions,
            semanticAdjudicationCommits: snapshot.counters.semanticAdjudicationTopologyCommits,
            semanticAdjudicationLedgerOnly: snapshot.counters.semanticAdjudicationLedgerOnly,
            semanticAdjudicationStates: snapshot.semanticAdjudicationSummary?.counters.byState,
            semanticEvalLedger: compactEvalLedger(snapshot),
            candidateNoise: snapshot.semanticCandidateSummary?.counters.averageNoiseScore,
            elapsedMs: Math.round(elapsedMs),
        }));

        expect(occurrences.length).toBeGreaterThan(900);
        expect(snapshot.counters.embeddingTargets).toBeLessThanOrEqual(960);
        expect(snapshot.embeddingTargetPlan?.admittedCount).toBe(snapshot.counters.embeddingTargets);
        expect(snapshot.embeddingTargetPlan?.candidateCount).toBeGreaterThanOrEqual(snapshot.counters.embeddingTargets);
        expect(snapshot.counters.embeddingDocumentSpine).toBeGreaterThan(0);
        expect(snapshot.counters.embeddingChunkSpine).toBeGreaterThan(0);
        expect(snapshot.counters.embeddingEntityAnchors).toBe(entities.length + 1);
        expect(snapshot.counters.embeddingRelationshipFacts).toBeGreaterThan(0);
        expect(snapshot.counters.embeddingTemporalFacts).toBeGreaterThan(0);
        expect(snapshot.counters.embeddingCausalFacts).toBeGreaterThan(0);
        expect(snapshot.embeddingGraphPostProcess?.targetCount).toBe(snapshot.counters.embeddingTargets);
        expect(snapshot.embeddingGraphPostProcess?.metrics.plannedPairCount).toBeLessThan(
            snapshot.embeddingGraphPostProcess?.metrics.theoreticalPairCount || 0,
        );
        expect(snapshot.embeddingGraphPostProcess?.metrics.prunedPairCount).toBeGreaterThan(0);
        expect(counts.note).toBeGreaterThan(0);
        expect(counts.chunk).toBeGreaterThan(0);
        expect(counts.entity).toBe(entities.length);
        expect(counts.graphFact).toBeGreaterThanOrEqual(100);
        expect(counts.anchor).toBeLessThan(occurrences.length);
        expect(snapshot.embeddingTargetPlan?.lanes).toEqual(expect.arrayContaining([
            expect.objectContaining({ lane: 'cooccurrence_weak', admitted: 80, deferred: expect.any(Number) }),
            expect.objectContaining({ lane: 'anchor_evidence', admitted: entities.length + 1, deferred: expect.any(Number) }),
        ]));
        expect(snapshot.embeddingTargets.filter((target) => target.kind === 'entity').every((target) => /mentions:\d+/.test(target.text))).toBe(true);
        expect(snapshot.embeddingTargets.filter((target) => target.kind === 'graphFact').every((target) => target.text.includes('evidence_context:'))).toBe(true);
        expect(snapshot.embeddingTargets.filter((target) => target.kind === 'anchor').every((target) => target.text.includes('source:') && target.text.includes('evidence_context:'))).toBe(true);
        expect(snapshot.semanticTaskSummary?.counters.mutationAllowedCount).toBe(0);
        expect(snapshot.semanticTaskSummary?.receipts.length).toBe(snapshot.counters.semanticTaskReceipts);
        expect(snapshot.semanticTaskSummary?.tasks.every((task) => task.mutationAllowed === false)).toBe(true);
        expect(snapshot.semanticTaskSummary?.receipts.every((receipt) => receipt.invariant === 'phase1_no_topology_mutation')).toBe(true);
        expect(snapshot.semanticTaskSummary?.counters.byTaskKind).toEqual(expect.objectContaining({
            link_prediction: expect.any(Number),
            edge_classification: expect.any(Number),
            node_classification: expect.any(Number),
            graph_completion: expect.any(Number),
            community_detection: expect.any(Number),
            anomaly_detection: expect.any(Number),
            path_reasoning: expect.any(Number),
        }));
        expect(snapshot.semanticCandidateSummary?.schemaVersion).toBe('phoenix-semantic-candidate-factory/v1');
        expect(snapshot.semanticCandidateSummary?.counters.mutationAllowedCount).toBe(0);
        expect(snapshot.semanticCandidateSummary?.candidates.length).toBeLessThanOrEqual(240);
        expect(snapshot.semanticCandidateSummary?.candidates.length).toBe(snapshot.counters.semanticCandidates);
        expect(snapshot.semanticCandidateSummary?.receipts.length).toBe(snapshot.counters.semanticCandidateReceipts);
        expect(snapshot.semanticCandidateSummary?.receipts.every((receipt) => receipt.invariant === 'phase2_no_topology_commit')).toBe(true);
        expect(snapshot.semanticCandidateSummary?.counters.averageNoiseScore).toBeLessThan(0.62);
        expect(snapshot.semanticCandidateSummary?.counters.byKind).toEqual(expect.objectContaining({
            entity_link: expect.any(Number),
            relation_link: expect.any(Number),
            causal_bridge: expect.any(Number),
            temporal_bridge: expect.any(Number),
            outlier_review: expect.any(Number),
        }));
        expect(snapshot.manifoldSpecializationSummary?.schemaVersion).toBe('phoenix-manifold-specialization/v1');
        expect(snapshot.manifoldSpecializationSummary?.contributions.length).toBeLessThanOrEqual(480);
        expect(snapshot.manifoldSpecializationSummary?.contributions.length).toBe(snapshot.counters.manifoldCandidateContributions);
        expect(snapshot.manifoldSpecializationSummary?.receipts.length).toBe(snapshot.counters.manifoldContributionReceipts);
        expect(snapshot.manifoldSpecializationSummary?.receipts.every((receipt) => receipt.invariant === 'phase3_no_topology_commit')).toBe(true);
        expect(snapshot.manifoldSpecializationSummary?.counters.mutationAllowedCount).toBe(0);
        expect(snapshot.manifoldSpecializationSummary?.counters.byManifold['product']).toBeGreaterThan(0);
        expect(snapshot.manifoldSpecializationSummary?.counters.byManifold['siegel']).toBeGreaterThan(0);
        expect(snapshot.manifoldSpecializationSummary?.counters.byManifold['hopf']).toBeGreaterThan(0);
        expect(manifoldContributions(snapshot, 'product').some((row) =>
            row.ruleId.startsWith('product-') && /lanes|source-bridge|bridge/.test(row.rationale),
        )).toBe(true);
        expect(manifoldContributions(snapshot, 'siegel').some((row) =>
            row.ruleId.startsWith('siegel-') && /route|branch/.test(row.rationale),
        )).toBe(true);
        expect(manifoldContributions(snapshot, 'hopf').some((row) =>
            row.ruleId.startsWith('hopf-') && /identity|alias|recurrence/.test(row.rationale),
        )).toBe(true);
        expect(declaredRuleCoverage(snapshot)).toBe(true);
        expect(snapshot.semanticCandidateSummary?.candidates.some((candidate) =>
            (candidate.manifoldContributionIds || []).length > 0,
        )).toBe(true);
        expect(snapshot.semanticRerankSummary?.schemaVersion).toBe('phoenix-semantic-rerank/v1');
        expect(snapshot.semanticRerankSummary?.modelId).toBe('knowledgator/gliclass-instruct-base-v1.0');
        expect(snapshot.semanticRerankSummary?.runner).toBe('gliclass-query-label-rerank');
        expect(snapshot.semanticRerankSummary?.inputs.length).toBe(snapshot.counters.semanticRerankInputs);
        expect(snapshot.semanticRerankSummary?.judgments.length).toBe(snapshot.counters.semanticRerankJudgments);
        expect(snapshot.semanticRerankSummary?.receipts.length).toBe(snapshot.counters.semanticRerankReceipts);
        expect(snapshot.semanticRerankSummary?.counters.mutationAllowedCount).toBe(0);
        expect(snapshot.semanticRerankSummary?.receipts.every((receipt) => receipt.invariant === 'phase4_no_topology_commit')).toBe(true);
        expect(snapshot.semanticRerankSummary?.inputs.length).toBeLessThanOrEqual(192);
        expect(snapshot.semanticRerankSummary?.inputs.every((input) =>
            input.queryLabels.length >= 3 && input.queryLabels.every((query) => query.length > 20),
        )).toBe(true);
        expect(snapshot.semanticRerankSummary?.judgments.some((judgment) => judgment.decision === 'accept')).toBe(true);
        expect(snapshot.semanticRerankSummary?.judgments.every((judgment) =>
            judgment.modelId === 'knowledgator/gliclass-instruct-base-v1.0'
            && judgment.runner === 'gliclass-query-label-rerank'
            && judgment.scores.length >= 3,
        )).toBe(true);
        expect(snapshot.semanticAdjudicationSummary?.schemaVersion).toBe('phoenix-semantic-adjudication-dag/v1');
        expect(snapshot.semanticAdjudicationSummary?.counters.topologyCommitCount).toBeGreaterThan(0);
        expect(snapshot.semanticAdjudicationSummary?.mutations.every((mutation) =>
            snapshot.edges.some((edge) => edge.id === mutation.createdEdgeId),
        )).toBe(true);
        expect(snapshot.semanticAdjudicationSummary?.decisions.filter((decision) => decision.state !== 'accepted').every((decision) =>
            decision.ledgerOnly === true
            && decision.affectedGraphAtomIds.length === 0
            && decision.affectedGraphFactIds.length === 0,
        )).toBe(true);
        expect(snapshot.semanticEvalLedgerSummary?.compactExport.rowCount).toBe(snapshot.counters.semanticEvalLedgerRows);
        expect(snapshot.semanticEvalLedgerSummary?.counters.acceptedCandidates).toBeGreaterThan(0);
        expect(snapshot.semanticEvalLedgerSummary?.counters.ambiguousCases).toBeGreaterThan(0);
        expect(snapshot.semanticEvalLedgerSummary?.counters.graphChangeRows).toBe(snapshot.counters.semanticAdjudicationTopologyCommits);
        expect(snapshot.semanticEvalLedgerSummary?.compactExport.rows.every((row) =>
            row.evidence > 0 && row.score >= 0 && row.score <= 1,
        )).toBe(true);
        expect(elapsedMs).toBeLessThan(8000);
    });

    it('ramps causal target smoke over docs/midrun.md without exceeding the signal budget', () => {
        const text = readFileSync(new URL('../../../docs/midrun.md', import.meta.url), 'utf8');
        const chunks = dynamicChunksForNote({ id: 'midrun-dense', markdownContent: text, content: '' });
        const surfaces = candidateSurfaces(text).slice(0, 72);
        const entities = surfaces.map((surface, index) =>
            registeredEntity(`mid-${index}:${normalizeId(surface)}`, surface, likelyKind(surface), []),
        );
        const occurrences = entities.flatMap((entity) =>
            surfaceOccurrences(text, 'midrun-dense', entity.id, entity.label, entity.kind, 'dictionary_match', 48),
        );
        const started = performance.now();
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:midrun-dense',
            noteIds: ['midrun-dense'],
            entities,
            chunks,
            occurrences,
            candidateCount: occurrences.length,
            noteTexts: { 'midrun-dense': text },
            builtAt: 23,
        });
        const elapsedMs = performance.now() - started;
        const causalTargets = snapshot.embeddingTargets.filter((target) => target.kind === 'causalFact');
        console.info('graph-rebuild-smoke', JSON.stringify({
            doc: 'midrun',
            chars: text.length,
            chunks: chunks.length,
            occurrences: occurrences.length,
            events: snapshot.counters.events,
            causalEdges: snapshot.counters.causalEdges,
            targets: snapshot.counters.embeddingTargets,
            semanticTasks: snapshot.counters.semanticTasks,
            semanticCandidates: snapshot.counters.semanticCandidates,
            manifoldContributions: snapshot.counters.manifoldCandidateContributions,
            manifoldExplained: snapshot.counters.manifoldCandidateExplained,
            manifoldByManifold: snapshot.manifoldSpecializationSummary?.counters.byManifold,
            semanticRerankInputs: snapshot.counters.semanticRerankInputs,
            semanticRerankCalls: snapshot.counters.semanticRerankPlannedModelCalls,
            semanticRerankDecisions: snapshot.semanticRerankSummary?.counters.byDecision,
            semanticAdjudicationDecisions: snapshot.counters.semanticAdjudicationDecisions,
            semanticAdjudicationCommits: snapshot.counters.semanticAdjudicationTopologyCommits,
            semanticAdjudicationLedgerOnly: snapshot.counters.semanticAdjudicationLedgerOnly,
            semanticAdjudicationStates: snapshot.semanticAdjudicationSummary?.counters.byState,
            semanticEvalLedger: compactEvalLedger(snapshot),
            candidateNoise: snapshot.semanticCandidateSummary?.counters.averageNoiseScore,
            elapsedMs: Math.round(elapsedMs),
        }));

        expect(text.length).toBeGreaterThan(400000);
        expect(chunks.length).toBeGreaterThan(40);
        expect(occurrences.length).toBeGreaterThan(900);
        expect(snapshot.counters.embeddingTargets).toBeLessThanOrEqual(960);
        expect(snapshot.embeddingTargetPlan?.admittedCount).toBe(snapshot.counters.embeddingTargets);
        expect(snapshot.counters.events).toBeGreaterThan(40);
        expect(snapshot.counters.temporalEdges).toBeGreaterThan(0);
        expect(snapshot.counters.causalEdges).toBeGreaterThan(0);
        expect(causalTargets.length).toBeGreaterThan(0);
        expect(causalTargets.every((target) => target.text.includes('causal_status:'))).toBe(true);
        expect(causalTargets.every((target) => target.text.includes('causal_source:'))).toBe(true);
        expect(snapshot.semanticTaskSummary?.tasks.length).toBeGreaterThan(100);
        expect(snapshot.semanticTaskSummary?.counters.mutationAllowedCount).toBe(0);
        expect(snapshot.semanticTaskSummary?.counters.byTaskKind['path_reasoning']).toBeGreaterThan(0);
        expect(snapshot.semanticTaskSummary?.counters.byTaskKind['community_detection']).toBeGreaterThan(0);
        expect(snapshot.semanticCandidateSummary?.candidates.length).toBeGreaterThan(100);
        expect(snapshot.semanticCandidateSummary?.candidates.length).toBeLessThanOrEqual(240);
        expect(snapshot.semanticCandidateSummary?.counters.mutationAllowedCount).toBe(0);
        expect(snapshot.semanticCandidateSummary?.counters.averageNoiseScore).toBeLessThan(0.66);
        expect(snapshot.semanticCandidateSummary?.counters.byKind['causal_bridge']).toBeGreaterThan(0);
        expect(snapshot.semanticCandidateSummary?.counters.byKind['temporal_bridge']).toBeGreaterThan(0);
        expect(snapshot.manifoldSpecializationSummary?.contributions.length).toBeGreaterThan(40);
        expect(snapshot.manifoldSpecializationSummary?.contributions.length).toBeLessThanOrEqual(480);
        expect(snapshot.manifoldSpecializationSummary?.counters.byManifold['product']).toBeGreaterThan(0);
        expect(snapshot.manifoldSpecializationSummary?.counters.byManifold['siegel']).toBeGreaterThan(0);
        expect(snapshot.manifoldSpecializationSummary?.counters.byManifold['hopf']).toBeGreaterThan(0);
        expect(declaredRuleCoverage(snapshot)).toBe(true);
        expect(snapshot.manifoldSpecializationSummary?.contributions.every((contribution) =>
            Boolean(contribution.scoreInterpretation)
            && Boolean(contribution.rationale)
            && contribution.score >= 0
            && contribution.score <= 1,
        )).toBe(true);
        expect(snapshot.semanticRerankSummary?.inputs.length).toBeGreaterThan(100);
        expect(snapshot.semanticRerankSummary?.inputs.length).toBeLessThanOrEqual(192);
        expect(snapshot.semanticRerankSummary?.counters.plannedModelCalls).toBeGreaterThan(snapshot.semanticRerankSummary?.inputs.length || 0);
        expect(snapshot.semanticRerankSummary?.counters.byScoreSource['deterministic_calibration']).toBe(snapshot.semanticRerankSummary?.judgments.length);
        expect(snapshot.semanticRerankSummary?.judgments.every((judgment) =>
            judgment.relevanceScore >= 0
            && judgment.relevanceScore <= 1
            && judgment.calibratedScore >= 0
            && judgment.calibratedScore <= 1,
        )).toBe(true);
        expect(snapshot.semanticAdjudicationSummary?.decisions.length).toBe(snapshot.counters.semanticAdjudicationDecisions);
        expect(snapshot.semanticAdjudicationSummary?.counters.topologyCommitCount).toBeGreaterThan(0);
        expect(snapshot.semanticAdjudicationSummary?.counters.ledgerOnlyCount).toBeGreaterThan(0);
        expect(snapshot.semanticAdjudicationSummary?.receipts.every((receipt) =>
            receipt.reversible
            && (receipt.mutationAllowed || receipt.affectedGraphAtomIds.length === 0)
            && (receipt.mutationAllowed || receipt.affectedGraphFactIds.length === 0),
        )).toBe(true);
        expect(snapshot.semanticEvalLedgerSummary?.compactExport.rowCount).toBe(snapshot.counters.semanticEvalLedgerRows);
        expect(snapshot.semanticEvalLedgerSummary?.counters.acceptedCandidates).toBeGreaterThan(0);
        expect(snapshot.semanticEvalLedgerSummary?.counters.ambiguousCases).toBeGreaterThan(0);
        expect(snapshot.semanticEvalLedgerSummary?.counters.graphChangeRows).toBe(snapshot.counters.semanticAdjudicationTopologyCommits);
        expect(snapshot.semanticEvalLedgerSummary?.counters.manifoldDisagreements).toBeGreaterThan(0);
        expect(snapshot.embeddingGraphPostProcess?.metrics.plannedPairCount).toBeLessThan(
            snapshot.embeddingGraphPostProcess?.metrics.theoreticalPairCount || 0,
        );
        expect(elapsedMs).toBeLessThan(20000);
    });
});

function loadFixture(): ParityFixture {
    const raw = readFileSync(new URL('./fixtures/graph-rebuild-parity-smoke.json', import.meta.url), 'utf8');
    return JSON.parse(raw) as ParityFixture;
}

function manifoldContributions(snapshot: GraphRebuildSnapshot, manifold: GraphSemanticManifoldKind) {
    return (snapshot.manifoldSpecializationSummary?.contributions || []).filter((row) => row.manifold === manifold);
}

function declaredRuleCoverage(snapshot: GraphRebuildSnapshot): boolean {
    const summary = snapshot.manifoldSpecializationSummary;
    if (!summary) return false;
    const declared = new Set(summary.profiles.flatMap((profile) => profile.contributionRules.map((rule) => rule.id)));
    return summary.contributions.every((contribution) => declared.has(contribution.ruleId));
}

function compactEvalLedger(snapshot: GraphRebuildSnapshot) {
    const ledger = snapshot.semanticEvalLedgerSummary;
    return ledger ? {
        rows: ledger.compactExport.rowCount,
        byLabel: ledger.counters.byLabel,
        accepted: ledger.counters.acceptedCandidates,
        rejected: ledger.counters.rejectedCandidates,
        ambiguous: ledger.counters.ambiguousCases,
        modelDisagreements: ledger.counters.modelDisagreements,
        manifoldDisagreements: ledger.counters.manifoldDisagreements,
        graphChanges: ledger.counters.graphChangeRows,
        sample: ledger.compactExport.rows.slice(0, 3),
    } : null;
}

function toRegisteredEntity(entity: FixtureEntity): RegisteredEntity {
    return {
        id: entity.id,
        label: entity.label,
        kind: entity.kind as RegisteredEntity['kind'],
        aliases: entity.aliases,
        firstNote: 'parity-note',
        mentionsByNote: new Map(),
        totalMentions: 0,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
    };
}

function toOccurrence(noteId: string, occurrence: FixtureOccurrence): EntityOccurrence {
    return {
        id: `${noteId}:${occurrence.entityId}:${occurrence.sourceStart}:${occurrence.sourceEnd}:${occurrence.source}`,
        noteId,
        entityId: occurrence.entityId,
        entityLabel: occurrence.entityLabel,
        entityKind: occurrence.entityKind,
        sourceStart: occurrence.sourceStart,
        sourceEnd: occurrence.sourceEnd,
        surface: occurrence.surface,
        source: occurrence.source as EntityOccurrence['source'],
        confidence: occurrence.confidence,
        excerpt: occurrence.surface,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}

function registeredEntity(id: string, label: string, kind: string, aliases: string[]): RegisteredEntity {
    return {
        id,
        label,
        kind: kind as RegisteredEntity['kind'],
        aliases,
        firstNote: `${id}-note`,
        mentionsByNote: new Map(),
        totalMentions: 0,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
    };
}

function occurrence(
    noteId: string,
    entityId: string,
    surface: string,
    entityKind: string,
    sourceStart: number,
    sourceEnd: number,
    source: EntityOccurrence['source'],
): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}:${sourceStart}:${sourceEnd}:${source}`,
        noteId,
        entityId,
        entityLabel: surface,
        entityKind,
        sourceStart,
        sourceEnd,
        surface,
        source,
        confidence: 0.9,
        excerpt: surface,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}

function surfaceOccurrences(
    text: string,
    noteId: string,
    entityId: string,
    surface: string,
    entityKind: string,
    source: EntityOccurrence['source'],
    limit: number,
): EntityOccurrence[] {
    const out: EntityOccurrence[] = [];
    let from = 0;
    while (out.length < limit) {
        const index = text.indexOf(surface, from);
        if (index < 0) break;
        out.push(occurrence(noteId, entityId, surface, entityKind, index, index + surface.length, source));
        from = index + surface.length;
    }
    return out;
}

function candidateSurfaces(text: string): string[] {
    const stop = new Set([
        'the', 'this', 'that', 'they', 'their', 'there', 'these', 'those', 'when', 'what',
        'with', 'then', 'once', 'after', 'also', 'even', 'could', 'would', 'should', 'chapter',
        'finally', 'however', 'clearly', 'thankfully', 'unfortunately', 'nobody', 'she', 'his',
        'her', 'you', 'and', 'but', 'not', 'one', 'now', 'having', 'since', 'instead', 'may',
    ]);
    const counts = new Map<string, number>();
    const matches = text.match(/\b[A-Z][A-Za-z'’-]*(?:[-\s]+(?:of\s+|the\s+)?[A-Z][A-Za-z'’-]*){0,3}\b/g) || [];
    for (const match of matches) {
        const surface = match.replace(/\s+/g, ' ').trim();
        const key = surface.toLowerCase();
        if (surface.length <= 2 || stop.has(key)) continue;
        counts.set(surface, (counts.get(surface) || 0) + 1);
    }
    return [...counts.entries()]
        .filter(([, count]) => count >= 2)
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .map(([surface]) => surface);
}

function normalizeId(surface: string): string {
    return surface.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'surface';
}

function likelyKind(surface: string): string {
    const lower = surface.toLowerCase();
    if (/\b(rome|town|italy|plymouth|lanka|maghreb|bloodstream)\b/.test(lower)) return 'LOCATION';
    if (/\b(security|genome|genomes|gang|dynamis)\b/.test(lower)) return 'ORGANIZATION';
    return 'CHARACTER';
}

function structuralDigest(snapshot: GraphRebuildSnapshot): StructuralDigest {
    return {
        relationships: snapshot.relationships
            .map((relationship) => ({
                id: relationship.id,
                relationType: relationship.relationType,
                status: relationship.status,
            }))
            .sort((left, right) => left.id.localeCompare(right.id)),
        eventCount: snapshot.events.length,
        memoryStateCount: snapshot.memoryState.length,
        embeddingTargetKindCounts: kindCounts(snapshot.embeddingTargets.map((target) => target.kind)),
    };
}

function kindCounts(kinds: string[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const kind of kinds) counts.set(kind, (counts.get(kind) || 0) + 1);
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}
