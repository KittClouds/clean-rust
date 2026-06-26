import { describe, expect, it } from 'vitest';

import type { RegisteredEntity } from '../../../../lib/registry';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import { buildGraphDiscourseWorkbenchView } from './graph-discourse-workbench';
import { buildGraphOperatingRoomView } from './graph-operating-room';

describe('buildGraphDiscourseWorkbenchView', () => {
    it('keeps discourse ledger rows inspectable with candidate, decision, and evidence ids', () => {
        const view = buildGraphDiscourseWorkbenchView(snapshot(), entities());
        const row = view?.recordsByTab.gaps.find((record) => record.candidateId === 'candidate-1');

        expect(row).toMatchObject({
            decisionId: 'decision-1',
            evidenceIds: ['embed:chunk:chunk-1', 'embed:chunk:chunk-2'],
            tone: 'review',
        });
        expect(row?.facts.some((fact) => fact.label === 'Rerank' && fact.value.includes('gliclass_instruct'))).toBe(true);
        expect(row?.focusQuery).toContain('Chunk 1');
    });

    it('projects overlay and graph suggestions into actionable section rows', () => {
        const view = buildGraphDiscourseWorkbenchView(snapshot(), entities());

        expect(view?.recordsByTab.relations.some((record) =>
            record.id.includes('overlay') && record.candidateId === 'candidate-1'
        )).toBe(true);
        expect(view?.recordsByTab.gaps.some((record) =>
            record.id.includes('graph-suggestion') && record.entityIds.includes('kai') && record.entityIds.includes('hazel')
        )).toBe(true);
        expect(view?.openReviewCount).toBeGreaterThan(0);
    });

    it('surfaces document review rows with actions, spans, and evidence ids', () => {
        const view = buildGraphDiscourseWorkbenchView(snapshot(), entities());
        const row = view?.recordsByTab.relations.find((record) => record.id.includes('document-review'));

        expect(row).toBeTruthy();
        expect(row?.status).toBe('proposed');
        expect(row?.actionKinds).toEqual(expect.arrayContaining(['accept_fact', 'reject_fact', 'compile_to_graph']));
        expect(row?.evidenceIds).toEqual(['evidence-1']);
        expect(row?.facts.some((fact) => fact.label === 'Actions' && fact.value.includes('Compile'))).toBe(true);
        expect(view?.recordsByTab.stats.some((record) => record.id === 'stats:document-review-proposed')).toBe(true);
    });

    it('surfaces document compile-plan diffs as native payload candidates', () => {
        const view = buildGraphDiscourseWorkbenchView(snapshot(), entities());
        const row = view?.recordsByTab.relations.find((record) => record.id.includes('document-compiler'));

        expect(row).toBeTruthy();
        expect(row?.status).toBe('pending_commit');
        expect(row?.receiptIds).toEqual(['compiler-receipt-1']);
        expect(row?.evidenceIds).toEqual(['evidence-1']);
        expect(row?.targetIds).toEqual(expect.arrayContaining(['fact:document-hyperedge:hyper-1']));
        expect(row?.facts.some((fact) => fact.label === 'Before graph' && fact.value.includes('2 atoms'))).toBe(true);
        expect(row?.detail).toBe('native graph compiler payload candidate');
        expect(row?.tags).toContain('native_compile_candidate');
        expect(row?.facts.some((fact) => fact.label === 'Undo' && fact.value.includes('remove_document_compiler_ledger_row'))).toBe(true);
        expect(view?.recordsByTab.stats.some((record) => record.id === 'stats:document-compiler-diffs')).toBe(true);
    });

    it('builds operating-room rooms where count cards open their underlying rows', () => {
        const snap = snapshot();
        const workbench = buildGraphDiscourseWorkbenchView(snap, entities());
        const room = buildGraphOperatingRoomView(workbench, snap, entities());
        const relations = room.countsById['facts-relations'];
        const receipts = room.countsById['metrics-receipts'];

        expect(room.tabs.map((tab) => tab.id)).toEqual(['entities', 'structure', 'facts', 'review', 'discourse', 'metrics']);
        expect(relations.value).toBe(relations.recordIds.length);
        expect(relations.recordIds.some((id) => room.recordsById[id]?.kind.includes('document-compiler'))).toBe(true);
        expect(receipts.value).toBe(receipts.recordIds.length);
        expect(receipts.recordIds.some((id) => room.recordsById[id]?.receiptIds.includes('compiler-receipt-1'))).toBe(true);
    });

    it('surfaces NLI and GLiClass route votes in the review queue without promotion actions', () => {
        const snap = snapshot();
        snap.relationships = [nliRelationship('supported')];
        snap.counters.relationships = 1;
        snap.counters.reviewRelationships = 1;

        const workbench = buildGraphDiscourseWorkbenchView(snap, entities());
        const room = buildGraphOperatingRoomView(workbench, snap, entities());
        const row = workbench?.recordsById['relations:relationship:relationship-supported'];

        expect(row?.detail).toBe('NLI Supported / GLiClass supports / 94% confidence');
        expect(row?.tags.slice(0, 3)).toEqual(['nli:supported', 'gliclass:supports', 'review_only']);
        expect(row?.receiptIds).toEqual(['nli-receipt-1', 'judgment-supported']);
        expect(row?.actionKinds).toEqual(['inspect']);
        expect(row?.actionKinds.some((kind) => /accept|apply|compile|promote/.test(kind))).toBe(false);
        expect(row?.facts).toEqual(expect.arrayContaining([
            { label: 'NLI confidence', value: '94%' },
            { label: 'Receipts', value: 'nli-receipt-1 / judgment-supported' },
            { label: 'Graph impact', value: 'review vote only / no topology commit' },
        ]));
        expect(row?.facts.some((fact) => fact.label === 'NLI vote' && fact.value.includes('ModernBERT NLI'))).toBe(true);
        expect(row?.facts.some((fact) => fact.label === 'GLiClass route' && fact.value.includes('supports / 88%'))).toBe(true);
        expect(room.recordsByRoom.review.map((record) => record.id)).toContain(row?.id);
    });

    it('keeps contradicted NLI relationship rows review-visible as danger rows', () => {
        const snap = snapshot();
        snap.relationships = [nliRelationship('contradicted')];
        snap.counters.relationships = 1;
        snap.counters.reviewRelationships = 1;

        const workbench = buildGraphDiscourseWorkbenchView(snap, entities());
        const room = buildGraphOperatingRoomView(workbench, snap, entities());
        const row = workbench?.recordsById['relations:relationship:relationship-contradicted'];

        expect(row?.tone).toBe('danger');
        expect(row?.status).toBe('rejected');
        expect(row?.tags).toContain('nli:contradicted');
        expect(row?.facts.some((fact) => fact.label === 'Graph impact' && fact.value.includes('no topology commit'))).toBe(true);
        expect(room.recordsByRoom.review.map((record) => record.id)).toContain(row?.id);
    });

    it('adds operating-room inspection facts to document rows', () => {
        const view = buildGraphDiscourseWorkbenchView(snapshot(), entities());
        const row = view?.recordsByTab.relations.find((record) => record.id.includes('document-review'));

        expect(row?.facts.some((fact) => fact.label === 'Source text' && fact.value.includes('Kai trusts Hazel'))).toBe(true);
        expect(row?.facts.some((fact) => fact.label === 'Lineage' && fact.value.includes('unit-1'))).toBe(true);
        expect(row?.facts.some((fact) => fact.label === 'Detector' && fact.value.includes('graph_fact'))).toBe(true);
        expect(row?.facts.some((fact) => fact.label === 'Graph impact' && fact.value.includes('candidate'))).toBe(true);
    });
});

function entities(): RegisteredEntity[] {
    return [
        { id: 'kai', label: 'Kai', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
    ] as RegisteredEntity[];
}

function nliRelationship(decision: 'supported' | 'contradicted') {
    const supported = decision === 'supported';
    const confidence = supported ? 940 : 890;
    return {
        id: `relationship-${decision}`,
        sourceEntityId: 'kai',
        targetEntityId: 'hazel',
        relationType: 'supports',
        evidenceAnchorIds: ['anchor-1'],
        confidence: confidence / 1000,
        status: supported ? 'accepted' : 'rejected',
        adjudicationSource: 'nli:modernbert',
        adjudicationScore: confidence / 1000,
        rationale: 'ModernBERT NLI review vote',
        decisionEvidence: [
            `judgment:judgment-${decision}`,
            `claim:claim-${decision}`,
            `evidence:evidence-${decision}`,
            'receipt:nli-receipt-1',
            'evidence_ref:evidence-ref-1',
            `nli_decision:${decision}`,
            'nli_source:modernBertNli',
            'nli_role:canonFactAdjudication',
            `nli_confidence_millis:${confidence}`,
            `nli_entailment_millis:${supported ? confidence : 40}`,
            `nli_contradiction_millis:${supported ? 30 : confidence}`,
            'nli_neutral_millis:30',
            'classification_source:gliclass',
            'classification_role:relationFrameClassification',
            'classification_label:supports',
            'classification_score_millis:880',
        ],
    };
}

function snapshot(): GraphRebuildSnapshot {
    return {
        id: 'snap-1',
        schemaVersion: 'phoenix-graph-rebuild/v1',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        builtAt: 1,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: [
            { id: 'embed:chunk:chunk-1', kind: 'chunk', sourceId: 'chunk-1', label: 'Chunk 1', text: 'Kai trusts Hazel.', evidenceIds: [] },
            { id: 'embed:chunk:chunk-2', kind: 'chunk', sourceId: 'chunk-2', label: 'Chunk 2', text: 'Hazel answers Kai.', evidenceIds: [] },
        ],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
        graphAwareLinkSuggestions: [{
            id: 'graph-suggestion-1',
            kind: 'bridge_review',
            sourceEntityId: 'kai',
            targetEntityId: 'hazel',
            suggestedRelationType: 'trusts',
            status: 'review',
            confidence: 0.82,
            semanticStatus: 'review',
            structuralRole: 'shared_component',
            productLane: 'relation',
            productRegionRole: 'bridge',
            rerankSignals: ['manifold:product'],
            rationale: ['needs evidence confirmation'],
            evidenceIds: ['anchor-1'],
        }],
        discourseEvalLedgerSummary: {
            schemaVersion: 'phoenix-discourse-eval-ledger/v1',
            generatedAt: 1,
            sourceSnapshotId: 'snap-1',
            datasetPurpose: ['reranker_eval'],
            entries: [{
                id: 'ledger-1',
                candidateId: 'candidate-1',
                decisionId: 'decision-1',
                label: 'ambiguous_case',
                candidateKind: 'discourse_resonance',
                adjudicationState: 'deferred',
                sourceHypothesis: 'Kai and Hazel share a bridge but the evidence is thin.',
                evidenceTargetIds: ['embed:chunk:chunk-1', 'embed:chunk:chunk-2'],
                score: 0.67,
                scoringBundle: {
                    candidateScore: 0.7,
                    spineFinalScore: 0.6,
                    rerankRelevance: 0.65,
                    rerankCalibrated: 0.67,
                    rerankSource: 'gliclass_instruct',
                    evalScore: 0.6,
                    evalPassed: false,
                    finalScore: 0.67,
                    scoreParts: [],
                },
                rerank: {
                    judgmentId: 'judgment-1',
                    decision: 'review',
                    scoreSource: 'gliclass_instruct',
                    topLabelKind: 'meaningful_resonance',
                    relevanceScore: 0.65,
                    calibratedScore: 0.67,
                },
                candidateEval: {
                    evalRowId: 'eval-1',
                    kind: 'weak_resonance',
                    expectedLabelKind: 'meaningful_resonance',
                    score: 0.6,
                    passed: false,
                    failureModes: ['thin_evidence'],
                },
                discourseReceipts: {
                    semanticScore: 0.6,
                    labelAgreement: 0.5,
                    entityOverlap: 0.8,
                    distanceScore: 0.4,
                    corefPressure: 0.3,
                    finalScore: 0.67,
                },
                flags: ['needs_human_review'],
                beforeGraph: { edgeCount: 1, factIds: [], edgeIds: [] },
                afterGraph: { edgeCount: 1, factIds: [], edgeIds: [] },
                userCorrectionIds: [],
                rationale: ['defer until stronger context appears'],
            }],
            compactExport: { scopeId: 'global', builtAt: 1, rowCount: 1, rows: [] },
            counters: {
                rowCount: 1,
                byLabel: { ambiguous_case: 1 },
                byCandidateKind: { discourse_resonance: 1 },
                byState: { deferred: 1 },
                acceptedCandidates: 0,
                rejectedCandidates: 0,
                ambiguousCases: 1,
                userCorrections: 0,
                modelDisagreements: 0,
                manifoldDisagreements: 0,
                evalDisagreements: 1,
                graphChangeRows: 0,
                resonanceRows: 1,
                resolutionRows: 0,
                clusterReviewRows: 0,
            },
        },
        discourseCompilerOverlaySummary: {
            schemaVersion: 'phoenix-discourse-compiler-overlay/v1',
            generatedAt: 1,
            sourceSnapshotId: 'snap-1',
            sourcePromotionSurfaceId: 'surface-1',
            invariant: 'discourse_compiler_overlay_no_topology_commit',
            overlayEdges: [{
                id: 'overlay-1',
                kind: 'chunk_wormhole',
                sourceHintId: 'hint-1',
                sourceLedgerEntryId: 'ledger-1',
                candidateId: 'candidate-1',
                decisionId: 'decision-1',
                sourceTargetId: 'embed:chunk:chunk-1',
                targetTargetId: 'embed:chunk:chunk-2',
                memberTargetIds: [],
                evidenceTargetIds: ['embed:chunk:chunk-1'],
                proposedEdgeType: 'chunk-resonates-with',
                confidence: 0.91,
                projectionKind: 'discourse_overlay',
                status: 'overlay_only',
                graphPatch: false,
                mutationAllowed: false,
                rationale: ['compiler overlay only'],
            }],
            receipts: [],
            compactOverlay: { scopeId: 'global', builtAt: 1, rowCount: 1, rows: [] },
            counters: {
                byKind: { chunk_wormhole: 1 },
                overlayEdgeCount: 1,
                chunkWormholeEdges: 1,
                documentClusterEdges: 0,
                resolverEdges: 0,
                receiptCount: 0,
                reversibleReceiptCount: 0,
                graphPatchCount: 0,
                mutationAllowedCount: 0,
            },
        },
        documentSidecarSummary: {
            schemaVersion: 'phoenix-document-sidecar/v1',
            anchorPolicy: 'sidecar_never_promotes_anchors',
            builtAt: 1,
            noteIds: ['note-1'],
            units: [{ id: 'unit-1', noteId: 'note-1', kind: 'paragraph', label: 'Paragraph 1', start: 0, end: 30, depth: 1, childIds: [], confidence: { score: 0.9, source: 'surface', reasons: ['blank_line_boundary'] }, lineage: { noteId: 'note-1', documentUnitId: 'unit-1', parentUnitIds: [], sourceStart: 0, sourceEnd: 30, lens: 'surface' }, anchorPolicy: 'sidecar_only' }],
            sections: [],
            regions: [],
            rhetoricalUnits: [],
            retrievalUnits: [],
            graphFactCandidates: [],
            evidenceSpans: [{ id: 'evidence-1', noteId: 'note-1', unitId: 'unit-1', start: 0, end: 30, preview: 'Kai trusts Hazel.', textHash: 'abc', confidence: { score: 0.8, source: 'graph_fact', reasons: ['graph_fact_cue'] }, lineage: { noteId: 'note-1', documentUnitId: 'unit-1', parentUnitIds: ['unit-1'], sourceStart: 0, sourceEnd: 30, lens: 'graph_fact' }, anchorPolicy: 'sidecar_only' }],
            counters: {
                documents: 0,
                units: 1,
                sections: 0,
                regions: 0,
                rhetoricalUnits: 0,
                retrievalUnits: 0,
                graphFactCandidates: 0,
                evidenceSpans: 1,
                paragraphGroups: 0,
                paragraphs: 1,
                sentences: 0,
                leafChunks: 0,
                parentChunks: 0,
                citationSpans: 0,
                crossDocTopicPackets: 0,
                userAnchorPromotions: 0,
                truncatedSentenceUnits: 0,
                byKind: { paragraph: 1 },
            },
        },
        documentReviewSummary: {
            schemaVersion: 'phoenix-document-review/v1',
            builtAt: 1,
            statePolicy: 'machine_objects_are_explicitly_review_stateful',
            topologyPolicy: 'review_actions_emit_receipts_before_graph_mutation',
            states: [{ id: 'state-1', objectId: 'fact-1', objectKind: 'graph_fact_candidate', state: 'proposed', source: 'machine_sidecar', confidence: 0.72 }],
            rows: [{
                id: 'review-row-1',
                objectId: 'fact-1',
                objectKind: 'graph_fact_candidate',
                state: 'proposed',
                title: 'n ary claim',
                subtitle: 'Graph Fact Candidate / Proposed',
                detail: 'Graph Fact / 72%',
                noteId: 'note-1',
                sourceStart: 0,
                sourceEnd: 30,
                confidence: 0.72,
                detector: 'graph_fact',
                parentUnitIds: ['unit-1'],
                childUnitIds: [],
                evidenceSpanIds: ['evidence-1'],
                relatedObjectIds: [],
                why: ['because'],
                availableActions: [
                    { id: 'a-accept', kind: 'accept_fact', label: 'Accept', targetObjectId: 'fact-1', destructive: false, requiresUserIntent: true, nextState: 'accepted' },
                    { id: 'a-reject', kind: 'reject_fact', label: 'Reject', targetObjectId: 'fact-1', destructive: true, requiresUserIntent: true, nextState: 'rejected' },
                    { id: 'a-compile', kind: 'compile_to_graph', label: 'Compile', targetObjectId: 'fact-1', destructive: false, requiresUserIntent: true, nextState: 'compiled_to_graph' },
                ],
                receiptIds: [],
            }],
            receipts: [],
            counters: {
                stateRecords: 1,
                rows: 1,
                actionableRows: 1,
                actions: 3,
                receipts: 0,
                reversibleReceipts: 0,
                acceptedRows: 0,
                rejectedRows: 0,
                mutedRows: 0,
                promotedToAnchorRows: 0,
                compiledToGraphRows: 0,
                ledgerOnlyRows: 0,
                proposedRows: 1,
                duplicateGroups: 0,
                byState: { proposed: 1 },
                byObjectKind: { graph_fact_candidate: 1 },
                byActionKind: { accept_fact: 1, reject_fact: 1, compile_to_graph: 1 },
            },
        },
        documentCompilerSummary: {
            schemaVersion: 'phoenix-document-compiler/v2',
            authority: 'typescript_compile_plan',
            nativeCompilerRequired: true,
            mutationPolicy: 'ts_never_commits_document_graph',
            builtAt: 1,
            sourceSidecarBuiltAt: 1,
            sourceReviewBuiltAt: 1,
            compilePolicy: 'situation_frames_reviewed_or_high_confidence_only',
            sidecarPolicy: 'structure_is_disposable_anchors_are_durable',
            topologyPolicy: 'topology_commits_require_reversible_situation_receipts',
            highConfidenceThreshold: 0.84,
            entityMentions: [{
                id: 'mention-kai',
                surface: 'Kai',
                normalizedSurface: 'kai',
                role: 'subject',
                noteId: 'note-1',
                sourceStart: 0,
                sourceEnd: 30,
                confidence: 0.9,
                status: 'pending_commit',
                anchorPolicy: 'mention_only_not_user_anchor',
                evidenceSpanIds: ['evidence-1'],
                provenance: {
                    sourceObjectId: 'fact-1',
                    sourceObjectKind: 'relation_bundle',
                    sourceReviewRowId: 'review-row-1',
                    reviewState: 'compiled_to_graph',
                    noteId: 'note-1',
                    sourceStart: 0,
                    sourceEnd: 30,
                    evidenceSpanIds: ['evidence-1'],
                    lineageUnitIds: ['unit-1'],
                    reasons: ['because'],
                },
            }, {
                id: 'mention-hazel',
                surface: 'Hazel',
                normalizedSurface: 'hazel',
                role: 'object',
                noteId: 'note-1',
                sourceStart: 0,
                sourceEnd: 30,
                confidence: 0.9,
                status: 'pending_commit',
                anchorPolicy: 'mention_only_not_user_anchor',
                evidenceSpanIds: ['evidence-1'],
                provenance: {
                    sourceObjectId: 'fact-1',
                    sourceObjectKind: 'relation_bundle',
                    sourceReviewRowId: 'review-row-1',
                    reviewState: 'compiled_to_graph',
                    noteId: 'note-1',
                    sourceStart: 0,
                    sourceEnd: 30,
                    evidenceSpanIds: ['evidence-1'],
                    lineageUnitIds: ['unit-1'],
                    reasons: ['because'],
                },
            }],
            relationCandidates: [],
            hyperedges: [{
                id: 'hyper-1',
                predicate: 'trusts',
                sourceKind: 'relation_bundle',
                roles: [
                    { id: 'role-1', role: 'subject', targetId: 'mention-kai', targetKind: 'entity_mention', surface: 'Kai', confidence: 0.9 },
                    { id: 'role-2', role: 'object', targetId: 'mention-hazel', targetKind: 'entity_mention', surface: 'Hazel', confidence: 0.9 },
                    { id: 'role-3', role: 'evidence', targetId: 'evidence-1', targetKind: 'evidence_span', confidence: 0.8 },
                ],
                evidenceSpanIds: ['evidence-1'],
                confidence: 0.9,
                status: 'pending_commit',
                nary: true,
                provenance: {
                    sourceObjectId: 'fact-1',
                    sourceObjectKind: 'relation_bundle',
                    sourceReviewRowId: 'review-row-1',
                    reviewState: 'compiled_to_graph',
                    noteId: 'note-1',
                    sourceStart: 0,
                    sourceEnd: 30,
                    evidenceSpanIds: ['evidence-1'],
                    lineageUnitIds: ['unit-1'],
                    reasons: ['because'],
                },
            }],
            evidenceBackedEdges: [],
            crossDocBridges: [],
            documentStructureEdges: [],
            retrievalOverlays: [],
            topologyDiffs: [{
                id: 'compiler-diff-1',
                outputKind: 'hyperedge',
                outputId: 'hyper-1',
                operation: 'add_hyperedge',
                status: 'pending_commit',
                nativeCompileCandidate: true,
                mutationAllowed: false,
                topologyCommit: false,
                beforeGraph: { atomCount: 2, factCount: 1, edgeCount: 1 },
                afterGraph: { atomCount: 2, factCount: 1, edgeCount: 1 },
                createdAtomIds: ['atom:document-mention:mention-kai', 'atom:document-mention:mention-hazel'],
                createdFactIds: ['fact:document-hyperedge:hyper-1'],
                createdEdgeIds: ['edge:hyper-1:evidence-1'],
                evidenceSpanIds: ['evidence-1'],
                rationale: ['review_state:compiled_to_graph', 'roles:3'],
            }],
            receipts: [{
                id: 'compiler-receipt-1',
                topologyDiffId: 'compiler-diff-1',
                outputKind: 'hyperedge',
                outputId: 'hyper-1',
                reversible: true,
                mutationAllowed: false,
                invariant: 'document_compiler_native_payload_candidate',
                undoPatch: {
                    operation: 'remove_document_compiler_ledger_row',
                    removeAtomIds: ['atom:document-mention:mention-kai', 'atom:document-mention:mention-hazel'],
                    removeFactIds: ['fact:document-hyperedge:hyper-1'],
                    removeEdgeIds: ['edge:hyper-1:evidence-1'],
                    restoreReviewState: 'compiled_to_graph',
                },
                detail: 'add_hyperedge hyper-1 as pending_commit',
                createdAt: 1,
            }],
            counters: {
                entityMentions: 2,
                relationCandidates: 0,
                hyperedges: 1,
                naryHyperedges: 1,
                evidenceBackedEdges: 0,
                crossDocBridges: 0,
                documentStructureEdges: 0,
                retrievalOverlays: 0,
                topologyDiffs: 1,
                topologyCommits: 0,
                nativeCompileCandidates: 1,
                ledgerOnly: 0,
                overlayOnly: 0,
                reviewable: 0,
                blocked: 0,
                receipts: 1,
                reversibleReceipts: 1,
                mutationAllowed: 0,
                highConfidenceFacts: 0,
                reviewedFacts: 1,
                ambiguousFacts: 0,
                byKind: { hyperedge: 1 },
                byStatus: { pending_commit: 1 },
            },
        },
        counters: {
            nodes: 2,
            edges: 1,
            relationships: 0,
            reviewRelationships: 0,
            embeddingTargets: 2,
            embeddingVectors: 0,
        },
        buildTimings: { totalMs: 10 },
    } as unknown as GraphRebuildSnapshot;
}
