import { describe, expect, it } from 'vitest';

import {
    buildGraphRebuildAliasResolver,
    buildGraphRebuildSnapshot,
    normalizeGraphRebuildCandidate,
} from './graph-rebuild-builder';
import {
    embeddingModelAdapterFromSelection,
    normalizeEmbeddingProfile,
} from './graph-rebuild-embedding-signatures';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';
import type { GraphCompilerDualWriteSidecar } from './graph-compiler-read-model';
import { buildGraphSemanticAdjudicationDAGSummary } from './graph-semantic-adjudication';

describe('Phoenix graph rebuild builder', () => {
    it('resolves canonical Alex entities by label and alias', () => {
        const resolver = buildGraphRebuildAliasResolver([
            entity('e-kai', 'Kai', ['Captain Kai']),
            entity('e-rift', 'Rift', ['The Rift']),
        ]);

        expect(resolver.resolve(' captain kai ')?.id).toBe('e-kai');
        expect(resolver.resolve('The Rift')?.id).toBe('e-rift');
        expect(resolver.aliasCount).toBe(2);
    });

    it('normalizes NER candidates before they can feed Alex', () => {
        expect(normalizeGraphRebuildCandidate({
            label: '  Kai   Varo ',
            kind: 'character',
            aliases: ['Kai Varo', '  Captain   Kai  ', 'Captain Kai'],
            confidence: 2,
        })).toEqual({
            label: 'Kai Varo',
            kind: 'CHARACTER',
            aliases: ['Captain Kai'],
            confidence: 1,
        });
    });

    it('builds cooccurrence rows, typed facts, memory state, and embedding targets', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:one',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', ['Captain Kai']),
                entity('e-rift', 'Rift', []),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'note-1:block:0', noteId: 'note-1', start: 0, end: 120, ordinal: 0, source: 'note-block' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
                occurrence('note-1', 'e-rift', 'Rift', 20, 24),
                occurrence('note-1', 'e-hazel', 'Hazel', 90, 95),
                occurrence('note-2', 'e-hazel', 'Hazel', 0, 5),
            ],
            candidateCount: 4,
            noteTexts: {
                'note-1': 'Kai approved the packet with Rift because Hazel warned Kai. Hazel stood beside Kai as Diamond rank was confirmed.',
            },
            builtAt: 10,
        });

        expect(snapshot.schemaVersion).toBe('phoenix-graph-rebuild/v1');
        expect(snapshot.nodes.map((node) => node.id).sort()).toEqual(['e-hazel', 'e-kai', 'e-rift']);
        expect(snapshot.edges.filter((edge) => edge.type === 'anchored-cooccurrence').map((edge) => [edge.sourceId, edge.targetId]).sort()).toEqual([
            ['e-hazel', 'e-kai'],
            ['e-hazel', 'e-rift'],
            ['e-kai', 'e-rift'],
        ]);
        expect(snapshot.relationships).toHaveLength(5);
        expect(snapshot.relationships.filter((row) => row.adjudicationSource === 'graph-rebuild-cooccurrence-policy')).toHaveLength(3);
        expect(snapshot.relationships.filter((row) => row.adjudicationSource === 'graph-rebuild-typed-cue-policy')).toHaveLength(2);
        expect(snapshot.relationships.map((row) => [row.relationType, row.status])).toEqual(expect.arrayContaining([
            ['co_occurs_with', 'review'],
            ['approves_or_accepts', 'accepted'],
        ]));
        expect(snapshot.counters.relationshipCandidates).toBe(5);
        expect(snapshot.counters.acceptedRelationships).toBe(2);
        expect(snapshot.counters.reviewRelationships).toBe(3);
        expect(snapshot.counters.rejectedRelationships).toBe(0);
        expect(snapshot.counters).toMatchObject({
            anchorEvidence: 3,
            relationSignals: 5,
            promotedFacts: 6,
        });
        expect(snapshot.events.map((event) => event.id)).toEqual(['event:note-1:0:approval_event']);
        expect(snapshot.memoryState.map((state) => [state.entityId, state.key]).sort()).toEqual([
            ['e-hazel', 'rank_or_status'],
            ['e-kai', 'rank_or_status'],
            ['e-rift', 'rank_or_status'],
        ]);
        expect(kindCounts(snapshot.embeddingTargets.map((target) => target.kind))).toEqual({
            anchor: 3,
            chunk: 1,
            entity: 3,
            event: 1,
            graphFact: 5,
            memoryState: 3,
            note: 1,
            structureRoot: 5,
        });
        expect(snapshot.embeddingTargetPlan).toMatchObject({
            schemaVersion: 'phoenix-signal-target-plan/v1',
            candidateCount: 22,
            canonicalCount: 22,
            admittedCount: 19,
            queuedCount: 19,
            deferredCount: 3,
            schedulerDeferredCount: 3,
            policyDeferredCount: 0,
        });
        expect(snapshot.embeddingTargetPlan?.lanes).toEqual(expect.arrayContaining([
            expect.objectContaining({ lane: 'document_spine', admitted: 2 }),
            expect.objectContaining({ lane: 'chunk_spine', admitted: 1 }),
            expect.objectContaining({ lane: 'entity_anchor', admitted: 4 }),
            expect.objectContaining({ lane: 'temporal_fact', admitted: 1, tier: 0 }),
            expect.objectContaining({ lane: 'causal_fact', admitted: 1, tier: 0 }),
            expect.objectContaining({ lane: 'anchor_evidence', admitted: 4, tier: 0 }),
            expect.objectContaining({ lane: 'relationship_fact', admitted: 2 }),
            expect.objectContaining({ lane: 'cooccurrence_weak', candidates: 3, admitted: 0, deferred: 3 }),
            expect.objectContaining({ lane: 'memory_state', admitted: 3 }),
        ]));
        expect(snapshot.embeddingTargets.find((target) => target.id === 'embed:entity:e-kai')?.text)
            .toContain('mentions:1');
        expect(snapshot.embeddingTargets.find((target) => target.id === 'embed:entity:e-kai')?.text)
            .toContain('evidence_context:Kai approved the packet');
        expect(snapshot.embeddingTargets.find((target) => target.id === 'embed:entity:e-kai')?.parentIds)
            .toEqual(expect.arrayContaining(['embed:chunk:note-1:block:0', 'embed:structure-root:note-1:identity']));
        const approvedFact = snapshot.embeddingTargets.find((target) => target.id.includes('approves_or_accepts'));
        expect(approvedFact?.label).toContain('Kai approves_or_accepts Rift');
        expect(approvedFact?.text).toContain('confidence:');
        expect(approvedFact?.text).toContain('evidence_context:Kai approved the packet with Rift');
        expect(snapshot.embeddingTargets
            .filter((target) => target.kind === 'entity')
            .map((target) => target.entityKind)
        ).toEqual(['CHARACTER', 'CHARACTER', 'CHARACTER']);
        expect(snapshot.counters).toMatchObject({
            entities: 3,
            aliases: 1,
            candidates: 4,
            acceptedAnchors: 3,
            chunks: 1,
            events: 1,
            episodes: 1,
            memoryState: 3,
            embeddingTargets: 22,
            embeddingTargetCandidates: 22,
            embeddingQueuedTargets: 19,
            embeddingTargetDeferred: 3,
            embeddingSchedulerDeferredTargets: 3,
            embeddingPolicyDeferredTargets: 0,
            embeddingDocumentSpine: 2,
            embeddingChunkSpine: 1,
            embeddingEntityAnchors: 4,
            embeddingRelationshipFacts: 2,
            embeddingTemporalFacts: 1,
            embeddingCausalFacts: 1,
            embeddingMemoryStates: 3,
            embeddingAnchorEvidence: 4,
            nodes: 3,
            edges: 5,
            structuralComponents: 1,
            structuralHubs: 3,
        });
        expect(snapshot.structuralPostProcess).toMatchObject({
            schemaVersion: 'phoenix-graph-structure/v1',
            hubEntityIds: ['e-hazel', 'e-kai', 'e-rift'],
        });
        expect(snapshot.structuralPostProcess?.components).toHaveLength(1);
    });

    it('keeps registry-only Alex entities out of graph truth nodes and targets', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:registry',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', ['Captain Kai']),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'note-1:block:0', noteId: 'note-1', start: 0, end: 40, ordinal: 0, source: 'note-block' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
            ],
            noteTexts: {
                'note-1': 'Kai checked the registry before leaving.',
            },
            builtAt: 20,
        });

        expect(snapshot.nodes.map((node) => [node.entityId, node.totalMentions]).sort()).toEqual([
            ['e-kai', 1],
        ]);
        expect(snapshot.embeddingTargets.find((target) => target.id === 'embed:entity:e-hazel')).toBeUndefined();
        expect(snapshot.counters.entities).toBe(2);
        expect(snapshot.counters.nodes).toBe(1);
        expect(snapshot.counters.embeddingTargets).toBeGreaterThan(0);
    });

    it('uses an injected Rust compiler sidecar as the graph model authority', () => {
        const receipts = {
            roots: [],
            counters: { atoms: 2, evidenceAnchors: 1, bundles: 2, facts: 0, roles: 0, projectedEdges: 1, invariantFailures: 0 },
            invariantFailures: [],
        };
        const graphCompilerSidecar = {
            factGraph: {
                schemaVersion: 'phoenix-graph-compiler/v1',
                scopeKind: 'note',
                scopeId: 'note:rust',
                builtAt: 77,
                atoms: [
                    { id: 'atom:entity:kai', kind: 'entity', sourceId: 'kai', label: 'Kai', entityId: 'kai', evidenceIds: ['evidence:anchor:kai'] },
                    { id: 'atom:entity:hazel', kind: 'entity', sourceId: 'hazel', label: 'Hazel', entityId: 'hazel', evidenceIds: ['evidence:anchor:hazel'] },
                ],
                evidenceAnchors: [{ id: 'evidence:anchor:kai', kind: 'sourceSpan', sourceId: 'kai:anchor', confidence: 0.9 }],
                bundles: [
                    {
                        id: 'bundle:rust:co',
                        lane: 'cooccurrenceWeak',
                        predicate: 'co_occurs_with',
                        sourceRecordId: 'rust-co',
                        status: 'review',
                        evidenceIds: ['evidence:anchor:kai'],
                        confidence: 0.8,
                        commitment: {
                            family: 'RelationFamily',
                            topPrototypeId: 'relation:cooccurrence',
                            topLabel: 'cooccurrence',
                            topScore: -0.9,
                            topProbability: 0.82,
                            secondPrototypeId: 'relation:approval',
                            secondScore: -0.2,
                            secondProbability: 0.18,
                            margin: 0.7,
                            entropy: 0.28,
                            ambiguityScore: 0.28,
                            classificationConfidence: 0.76,
                            promotionReady: true,
                            radialStrength: 0.72,
                            topKScores: [
                                { prototypeId: 'relation:cooccurrence', family: 'RelationFamily', score: -0.9, probability: 0.82 },
                                { prototypeId: 'relation:approval', family: 'RelationFamily', score: -0.2, probability: 0.18 },
                            ],
                        },
                    },
                    {
                        id: 'bundle:rust:co-duplicate',
                        lane: 'cooccurrenceWeak',
                        predicate: 'co_occurs_with',
                        sourceRecordId: 'rust-co-duplicate',
                        status: 'review',
                        evidenceIds: ['evidence:anchor:hazel'],
                        confidence: 0.84,
                        compression: {
                            model: 'jinaV5Nano',
                            clusterId: 'cluster:rust:co',
                            canonicalBundleId: 'bundle:rust:co',
                            duplicateOfBundleId: 'bundle:rust:co',
                            outlierScore: 0.04,
                            neighborCount: 3,
                            semanticRank: 2,
                            rerankScore: 0.91,
                            rerankSource: 'gliClass',
                            signals: ['compression:near_duplicate'],
                        },
                    },
                ],
                facts: [],
                roles: [],
                projectedEdges: [{ id: 'projection:rust:co', sourceId: 'atom:entity:kai', targetId: 'atom:entity:hazel', edgeType: 'co_occurs_with', projectionKind: 'legacyBinary', sourceBundleId: 'bundle:rust:co', confidence: 0.8 }],
                receipts,
            },
            projectedUiGraph: [{ id: 'ui:rust:co', sourceId: 'kai', targetId: 'hazel', type: 'co_occurs_with', edgeType: 'co_occurs_with', weight: 800, confidence: 0.8, evidenceAnchorIds: ['bundle:rust:co'], scopeKeys: [], noteIds: [] }],
            receipts,
        } satisfies GraphCompilerDualWriteSidecar;

        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:rust',
            noteIds: ['note-1'],
            entities: [entity('kai', 'Kai', []), entity('hazel', 'Hazel', [])],
            chunks: [{ id: 'chunk-1', noteId: 'note-1', start: 0, end: 18, ordinal: 0, source: 'note-block' }],
            occurrences: [occurrence('note-1', 'kai', 'Kai', 0, 3), occurrence('note-1', 'hazel', 'Hazel', 8, 13)],
            graphCompilerSidecar,
            builtAt: 77,
        });

        expect(snapshot.graphCompilerSource).toBe('rust');
        expect(snapshot.graphCompiler).toBe(graphCompilerSidecar.factGraph);
        expect(snapshot.projectedUiGraph).toBe(graphCompilerSidecar.projectedUiGraph);
        expect(snapshot.graphModelV2?.facts).toHaveLength(0);
        expect(snapshot.graphModelV2?.bundles).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'bundle:rust:co',
                family: 'cooccurrence',
                commitment: expect.objectContaining({
                    topPrototypeId: 'relation:cooccurrence',
                    promotionReady: true,
                }),
            }),
        ]));
        expect(snapshot.graphModelV2?.projectionEdges[0]).toMatchObject({ sourceBundleId: 'bundle:rust:co' });
        expect(snapshot.shadowLinkSuggestions).toEqual(expect.arrayContaining([
            expect.objectContaining({
                shadowKind: 'bundle_dedupe',
                relatedBundleIds: ['bundle:rust:co-duplicate', 'bundle:rust:co'],
            }),
        ]));

        const compactSidecar = {
            factGraph: graphCompilerSidecar.factGraph,
            receipts,
        } satisfies GraphCompilerDualWriteSidecar;
        const compactSnapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:rust',
            noteIds: ['note-1'],
            entities: [entity('kai', 'Kai', []), entity('hazel', 'Hazel', [])],
            chunks: [{ id: 'chunk-1', noteId: 'note-1', start: 0, end: 18, ordinal: 0, source: 'note-block' }],
            occurrences: [occurrence('note-1', 'kai', 'Kai', 0, 3), occurrence('note-1', 'hazel', 'Hazel', 8, 13)],
            graphCompilerSidecar: compactSidecar,
            builtAt: 77,
        });
        expect(compactSnapshot.projectedUiGraph).toEqual([
            expect.objectContaining({
                sourceId: 'kai',
                targetId: 'hazel',
                edgeType: 'co_occurs_with',
                evidenceAnchorIds: ['bundle:rust:co'],
            }),
        ]);
    });

    it('defers disabled embedding lanes without hiding their candidates', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:lane-policy',
            noteIds: ['note-1'],
            entities: [entity('e-kai', 'Kai', [])],
            chunks: [
                { id: 'note-1:block:0', noteId: 'note-1', start: 0, end: 60, ordinal: 0, source: 'note-block' },
            ],
            occurrences: [occurrence('note-1', 'e-kai', 'Kai', 0, 3)],
            noteTexts: { 'note-1': 'Kai watched the red mesa gate.' },
            embeddingStagePolicy: {
                enabledLanes: ['document_spine', 'chunk_spine', 'entity_anchor'],
            },
            builtAt: 20,
        });

        expect(snapshot.embeddingTargetPlan).toMatchObject({
            candidateCount: 9,
            canonicalCount: 9,
            admittedCount: 8,
            queuedCount: 8,
            deferredCount: 1,
            policyDeferredCount: 1,
        });
        expect(snapshot.embeddingTargets.map((target) => target.kind).sort()).toEqual([
            'anchor',
            'chunk',
            'entity',
            'note',
            'structureRoot',
            'structureRoot',
            'structureRoot',
            'structureRoot',
            'structureRoot',
        ]);
        expect(snapshot.embeddingTargets.find((target) => target.kind === 'anchor')).toMatchObject({
            admissionStatus: 'deferred',
            workStatus: 'deferred_by_policy',
            deferReason: 'lane_disabled_by_stage_policy',
        });
        expect(snapshot.embeddingTargetPlan?.lanes).toEqual(expect.arrayContaining([
            expect.objectContaining({ lane: 'anchor_evidence', candidates: 2, admitted: 1, deferred: 1 }),
            expect.objectContaining({ lane: 'causal_fact', candidates: 1, admitted: 1, deferred: 0 }),
            expect.objectContaining({ lane: 'temporal_fact', candidates: 1, admitted: 1, deferred: 0 }),
        ]));
    });

    it('adds deterministic topology roles for structural post-processing', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:structure',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-hazel', 'Hazel', []),
                entity('e-rowan', 'Rowan', []),
                entity('e-rook', 'Rook', []),
            ],
            chunks: [
                { id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 80, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-1:chunk:1', noteId: 'note-1', start: 81, end: 160, ordinal: 1, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
                occurrence('note-1', 'e-hazel', 'Hazel', 10, 15),
                occurrence('note-1', 'e-rowan', 'Rowan', 20, 25),
                occurrence('note-1', 'e-rook', 'Rook', 90, 94),
                occurrence('note-1', 'e-rowan', 'Rowan', 100, 105),
            ],
            builtAt: 13,
        });

        const structure = snapshot.structuralPostProcess!;
        expect(structure.components.map((component) => component.size)).toEqual([4]);
        expect(structure.bridgeEdgeIds).toEqual(['e-rook:anchored-cooccurrence:e-rowan']);
        expect(structure.nodes.map((node) => [node.entityId, node.role]).sort()).toEqual([
            ['e-hazel', 'connector'],
            ['e-kai', 'connector'],
            ['e-rook', 'leaf'],
            ['e-rowan', 'hub'],
        ]);
        expect(structure.edges.find((edge) => edge.edgeId === 'e-rook:anchored-cooccurrence:e-rowan')?.role).toBe('bridge');
        expect(snapshot.graphAwareLinkSuggestions?.map((suggestion) => suggestion.kind)).toEqual(expect.arrayContaining([
            'bridge_review',
            'suspicious_leaf',
        ]));
        expect(snapshot.counters.structuralBridgeEdges).toBe(1);
        expect(snapshot.counters.graphAwareLinkSuggestions).toBeGreaterThanOrEqual(2);
    });

    it('adds model-profile-aware embedding graph post-processing without hardcoded dimensions', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:embedding-graph',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-rowan', 'Rowan', []),
                entity('e-allied-table', 'Allied Table', [], 'NETWORK'),
            ],
            chunks: [
                { id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 90, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-1:chunk:1', noteId: 'note-1', start: 91, end: 180, ordinal: 1, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
                occurrence('note-1', 'e-rowan', 'Rowan', 22, 27),
                occurrence('note-1', 'e-allied-table', 'Allied Table', 98, 110),
                occurrence('note-1', 'e-kai', 'Kai', 130, 133),
            ],
            noteTexts: {
                'note-1': 'Kai and Rowan mapped the first authority packet. Allied Table reviewed the network lane while Kai prepared the graph.',
            },
            embeddingProfile: {
                modelId: 'jina-v5-nano-retrieval',
                modelLabel: 'Jina v5 Nano',
                modelFamily: 'jina-v5',
                dimensionLabel: '786d',
                nativeDimensions: 786,
                selectedDimensions: 786,
                taskProfile: 'semantic_topology',
                vectorSource: 'signature-preview',
                normalized: true,
            },
            builtAt: 15,
        });

        expect(snapshot.embeddingProfile).toMatchObject({
            modelId: 'jina-v5-nano-retrieval',
            selectedDimensions: 786,
            taskProfile: 'semantic_topology',
            topologySupport: 'native',
        });
        expect(snapshot.embeddingModelAdapter).toMatchObject({
            modelId: 'jina-v5-nano-retrieval',
            selectedDimensions: 786,
            topologySupport: 'native',
        });
        expect(snapshot.embeddingGraphPostProcess?.schemaVersion).toBe('phoenix-embedding-graph-postprocess/v1');
        expect(snapshot.embeddingGraphPostProcess?.vectorDimensions).toBe(786);
        expect(snapshot.embeddingGraphPostProcess?.clusters.length).toBeGreaterThan(0);
        expect(snapshot.embeddingGraphPostProcess?.productTopologyRegions.length).toBeGreaterThan(0);
        expect(snapshot.embeddingGraphPostProcess?.targets[0].productLaneFeatures).toMatchObject({
            semanticDepth: expect.any(Number),
            fiberPhase: expect.any(Number),
            dominantLane: expect.any(String),
            laneWeights: expect.any(Object),
        });
        expect(snapshot.embeddingGraphPostProcess?.targets[0].productTopologyRegion).toMatchObject({
            id: expect.stringContaining('product-region:'),
            role: expect.any(String),
            laneKind: expect.any(String),
        });
        expect(snapshot.counters.embeddingClusters).toBe(snapshot.embeddingGraphPostProcess?.metrics.clusterCount);
        expect(snapshot.counters.embeddingBackboneEdges).toBe(snapshot.embeddingGraphPostProcess?.metrics.backboneEdgeCount);
    });

    it('prepares model adapters for retrieval, multi-task, and high-dimension topology models', () => {
        const leafMt = embeddingModelAdapterFromSelection({
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'mongodb-leaf-mt',
            embeddingModelLabel: 'MDBR Leaf MT',
            embeddingDimensionLabel: '384d',
            nliModelId: 'nli',
        });
        const jina = embeddingModelAdapterFromSelection({
            dynamicNerId: 'dynamic_ner',
            embeddingModelId: 'jina-v5-nano-retrieval',
            embeddingModelLabel: 'Jina v5 Nano Retrieval',
            embeddingDimensionLabel: '768d',
            nliModelId: 'nli',
        });

        expect(leafMt).toMatchObject({
            dimensionLabel: '384d',
            nativeDimensions: 384,
            selectedDimensions: 384,
            modelFamily: 'mdbr-leaf-mt',
            taskProfile: 'multi_task',
            topologySupport: 'native',
            supportsTopology: true,
            supportsMultiTask: true,
            supportsMultiVector: true,
        });
        expect(leafMt.vectorHeads.map((head) => head.id)).toEqual([
            'document',
            'query',
            'topology',
            'classification',
        ]);
        expect(jina).toMatchObject({
            selectedDimensions: 768,
            modelFamily: 'jina-v5',
            taskProfile: 'retrieval',
            topologySupport: 'native',
            supportsTopology: true,
            supportsMultiVector: true,
        });
    });

    it('normalizes embedding profiles through adapter defaults for odd dimensions', () => {
        const profile = normalizeEmbeddingProfile({
            modelId: 'jina-v5-topology',
            modelLabel: 'Jina v5 Topology 786',
            dimensionLabel: '786d',
        });

        expect(profile).toMatchObject({
            selectedDimensions: 786,
            nativeDimensions: 786,
            taskProfile: 'semantic_topology',
            topologySupport: 'native',
            normalization: 'unit_l2',
            supportsMultiVector: true,
        });
        expect(profile.vectorHeads.every((head) => head.dimensions === 786)).toBe(true);
    });

    it('suggests network hub affiliations from semantic status and structural role', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:network',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', [], 'CHARACTER'),
                entity('e-allied-table', 'Allied Table', [], 'NETWORK'),
            ],
            chunks: [
                { id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 80, ordinal: 0, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
                occurrence('note-1', 'e-allied-table', 'Allied Table', 20, 32),
            ],
            builtAt: 14,
        });

        expect(snapshot.graphAwareLinkSuggestions).toEqual(expect.arrayContaining([
            expect.objectContaining({
                kind: 'hub_affiliation',
                sourceEntityId: 'e-allied-table',
                targetEntityId: 'e-kai',
                suggestedRelationType: 'affiliated_with',
                semanticStatus: 'review',
                structuralRole: 'bridge',
                rerankScore: expect.any(Number),
                rerankSignals: expect.arrayContaining(['semantic:review', 'structure:bridge', expect.stringContaining('product_')]),
            }),
        ]));
    });

    it('re-resolves stale occurrence chunk ids so multi-note temporal facts survive', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-tempest', 'Tempest', []),
                entity('e-red-mesa', 'Red Mesa', [], 'LOCATION'),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'note-1:chunk:0:fresh', noteId: 'note-1', start: 0, end: 80, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-1:chunk:1:fresh', noteId: 'note-1', start: 81, end: 180, ordinal: 1, source: 'dynamic-chunking' },
                { id: 'note-2:chunk:0:fresh', noteId: 'note-2', start: 0, end: 90, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-2:chunk:1:fresh', noteId: 'note-2', start: 91, end: 180, ordinal: 1, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3, 'note-1:chunk:0:stale'),
                occurrence('note-1', 'e-tempest', 'Tempest', 20, 27, 'note-1:chunk:0:stale'),
                occurrence('note-1', 'e-kai', 'Kai', 92, 95, 'note-1:chunk:1:stale'),
                occurrence('note-1', 'e-red-mesa', 'Red Mesa', 121, 129, 'note-1:chunk:1:stale'),
                occurrence('note-2', 'e-hazel', 'Hazel', 0, 5, 'note-2:chunk:0:stale'),
                occurrence('note-2', 'e-kai', 'Kai', 35, 38, 'note-2:chunk:0:stale'),
                occurrence('note-2', 'e-hazel', 'Hazel', 104, 109, 'note-2:chunk:1:stale'),
                occurrence('note-2', 'e-red-mesa', 'Red Mesa', 130, 138, 'note-2:chunk:1:stale'),
            ],
            noteTexts: {
                'note-1': 'Kai said Tempest watched the room.                                                  Because Kai started tracking Red Mesa and the roads shifted.',
                'note-2': 'Hazel read while Kai approved the packet.                                                   Hazel continued because Red Mesa kept selecting.',
            },
            builtAt: 16,
        });

        expect(snapshot.counters.dropReasons.missingChunk).toBe(0);
        expect(snapshot.entityAnchors.every((anchor) => anchor.chunkId?.endsWith(':fresh'))).toBe(true);
        expect(snapshot.events.map((event) => event.noteId)).toEqual(['note-1', 'note-1', 'note-2', 'note-2']);
        expect(snapshot.temporalEdges).toHaveLength(2);
        expect(snapshot.causalEdges).toHaveLength(2);
        expect(snapshot.causalEdges.every((edge) => edge.status === 'candidate')).toBe(true);
        expect(snapshot.causalEdges.every((edge) => edge.sourceKind === 'candidate_cue')).toBe(true);
        expect(snapshot.causalEdges.every((edge) => edge.evidenceIds.every((id) => !id.startsWith('event:')))).toBe(true);
        expect(snapshot.temporalEdges.every((edge) => sameNoteEdge(edge, snapshot.events))).toBe(true);
        expect(snapshot.causalEdges.every((edge) => sameNoteEdge(edge, snapshot.events))).toBe(true);
        expect(snapshot.embeddingTargets.map((target) => target.kind)).toEqual(expect.arrayContaining([
            'event',
            'temporalFact',
            'causalFact',
        ]));
    });

    it('promotes causal sidecar edges with review metadata into causal graph facts', () => {
        const text = 'Kai warned Hazel before the chamber destabilized. Hazel approved the packet after Kai kept the door open.';
        const secondStart = text.indexOf('Hazel approved');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:causal-sidecar',
            noteIds: ['note-causal'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'note-causal:chunk:0', noteId: 'note-causal', start: 0, end: secondStart - 1, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-causal:chunk:1', noteId: 'note-causal', start: secondStart, end: text.length, ordinal: 1, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('note-causal', 'e-kai', 'Kai', 0, 3),
                occurrence('note-causal', 'e-hazel', 'Hazel', 11, 16),
                occurrence('note-causal', 'e-hazel', 'Hazel', secondStart, secondStart + 5),
                occurrence('note-causal', 'e-kai', 'Kai', text.lastIndexOf('Kai'), text.lastIndexOf('Kai') + 3),
            ],
            causalSidecar: {
                edgeRecords: [{
                    edgeId: 'native-edge-1',
                    caseId: 'review-1',
                    source: 'event:note-causal:0:warning_event',
                    target: 'event:note-causal:1:approval_event',
                    relationKind: 'directCause',
                    status: 'supported',
                    confidenceMillis: 860,
                    cue: 'because',
                    evidenceRefs: ['receipt:causal:1'],
                }],
            },
            noteTexts: { 'note-causal': text },
            builtAt: 19,
        });
        const edge = snapshot.causalEdges.find((row) => row.sourceKind === 'explicit_cue');
        const target = snapshot.embeddingTargets.find((row) => row.kind === 'causalFact' && row.sourceId === edge?.id);

        expect(edge).toMatchObject({
            status: 'supported',
            relationKind: 'direct_cause',
            confidence: 0.86,
            cue: 'because',
            evidenceClass: 'world_support',
        });
        expect(edge?.supportIds).toEqual(expect.arrayContaining(['review-1']));
        expect(target?.text).toContain('causal_status:supported');
        expect(target?.text).toContain('causal_source:explicit_cue');
        expect(target?.text).toContain('causal_relation_kind:direct_cause');
        expect(snapshot.graphModelV2?.facts.find((fact) => fact.sourceRecordId === edge?.id)?.status).toBe('accepted');
    });

    it('stages phase-one semantic graph tasks with reversible no-mutation receipts', () => {
        const text = 'Kai warned Hazel before Rift opened the door. Hazel watched Kai because Rift shifted again. The quiet omen hovered.';
        const secondStart = text.indexOf('Hazel watched');
        const thirdStart = text.indexOf('The quiet omen');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:semantic-tasks',
            noteIds: ['note-semantic'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-hazel', 'Hazel', []),
                entity('e-rift', 'Rift', []),
            ],
            chunks: [
                { id: 'note-semantic:chunk:0', noteId: 'note-semantic', start: 0, end: secondStart - 1, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-semantic:chunk:1', noteId: 'note-semantic', start: secondStart, end: thirdStart - 1, ordinal: 1, source: 'dynamic-chunking' },
                {
                    id: 'note-semantic:chunk:2',
                    noteId: 'note-semantic',
                    start: thirdStart,
                    end: text.length,
                    ordinal: 2,
                    source: 'dynamic-chunking',
                    meaningFrame: {
                        role: 'mixed',
                        splitReason: 'test',
                        breakPressure: 0,
                        mergePressure: 0,
                        entityPriors: [],
                        eventCues: ['omen'],
                        modalCues: [],
                        temporalCues: [],
                        authorityCues: [],
                        evidenceCues: [],
                        carryoverIn: [],
                        carryoverOut: [],
                    },
                },
            ],
            occurrences: [
                occurrence('note-semantic', 'e-kai', 'Kai', 0, 3),
                occurrence('note-semantic', 'e-hazel', 'Hazel', 11, 16),
                occurrence('note-semantic', 'e-rift', 'Rift', 25, 29),
                occurrence('note-semantic', 'e-hazel', 'Hazel', secondStart, secondStart + 5),
                occurrence('note-semantic', 'e-kai', 'Kai', text.indexOf('Kai', secondStart), text.indexOf('Kai', secondStart) + 3),
                occurrence('note-semantic', 'e-rift', 'Rift', text.indexOf('Rift', secondStart), text.indexOf('Rift', secondStart) + 4),
            ],
            noteTexts: { 'note-semantic': text },
            builtAt: 20,
        });
        const summary = snapshot.semanticTaskSummary!;

        expect(summary.schemaVersion).toBe('phoenix-graph-semantic-tasks/v1');
        expect(summary.sourceSnapshotId).toBe(snapshot.id);
        expect(summary.tasks.length).toBe(snapshot.counters.semanticTasks);
        expect(summary.receipts.length).toBe(snapshot.counters.semanticTaskReceipts);
        expect(summary.counters.mutationAllowedCount).toBe(0);
        expect(summary.tasks.every((task) => task.mutationAllowed === false)).toBe(true);
        expect(summary.receipts.every((receipt) => receipt.mutationAllowed === false && receipt.reversible)).toBe(true);
        expect(summary.receipts.every((receipt) => receipt.invariant === 'phase1_no_topology_mutation')).toBe(true);
        expect(summary.counters.byTaskKind).toEqual(expect.objectContaining({
            edge_classification: expect.any(Number),
            node_classification: expect.any(Number),
            path_reasoning: expect.any(Number),
        }));
        expect(summary.tasks.map((task) => task.proposalKind)).toEqual(expect.arrayContaining([
            'relation_type',
            'causal_type',
            'entity_kind',
            'causal_chain',
        ]));
        const candidates = snapshot.semanticCandidateSummary!;
        expect(candidates.schemaVersion).toBe('phoenix-semantic-candidate-factory/v1');
        expect(candidates.sourceSnapshotId).toBe(snapshot.id);
        expect(candidates.candidates.length).toBe(snapshot.counters.semanticCandidates);
        expect(candidates.receipts.length).toBe(snapshot.counters.semanticCandidateReceipts);
        expect(candidates.counters.mutationAllowedCount).toBe(0);
        expect(candidates.candidates.every((candidate) => candidate.mutationAllowed === false)).toBe(true);
        expect(candidates.receipts.every((receipt) => receipt.mutationAllowed === false && receipt.reversible)).toBe(true);
        expect(candidates.receipts.every((receipt) => receipt.invariant === 'phase2_no_topology_commit')).toBe(true);
        expect(candidates.counters.byKind).toEqual(expect.objectContaining({
            relation_link: expect.any(Number),
            causal_bridge: expect.any(Number),
            temporal_bridge: expect.any(Number),
            missing_frame: expect.any(Number),
        }));
        expect(candidates.candidates.every((candidate) => candidate.rank >= 0 && candidate.rank <= 1)).toBe(true);
        expect(candidates.candidates.every((candidate) => candidate.reversibleReceiptIds.length === 1)).toBe(true);
        const manifolds = snapshot.manifoldSpecializationSummary!;
        expect(manifolds.schemaVersion).toBe('phoenix-manifold-specialization/v1');
        expect(manifolds.sourceSnapshotId).toBe(snapshot.id);
        expect(manifolds.profiles.map((profile) => profile.manifold)).toEqual(expect.arrayContaining([
            'hybrid',
            'hopf',
            'caps',
            'product',
            'siegel',
            'lorentz',
            'hyperbolic',
        ]));
        expect(manifolds.contributions.length).toBe(snapshot.counters.manifoldCandidateContributions);
        expect(manifolds.receipts.length).toBe(snapshot.counters.manifoldContributionReceipts);
        expect(manifolds.counters.mutationAllowedCount).toBe(0);
        expect(manifolds.receipts.every((receipt) => receipt.invariant === 'phase3_no_topology_commit')).toBe(true);
        expect(manifolds.contributions.every((contribution) =>
            contribution.score >= 0
            && contribution.score <= 1
            && Boolean(contribution.scoreInterpretation)
            && Boolean(contribution.rationale),
        )).toBe(true);
        expect(candidates.candidates.some((candidate) => candidate.manifoldContributionIds?.length)).toBe(true);
        const rerank = snapshot.semanticRerankSummary!;
        expect(rerank.schemaVersion).toBe('phoenix-semantic-rerank/v1');
        expect(rerank.modelId).toBe('knowledgator/gliclass-instruct-base-v1.0');
        expect(rerank.runner).toBe('gliclass-query-label-rerank');
        expect(rerank.sourceSnapshotId).toBe(snapshot.id);
        expect(rerank.inputs.length).toBe(snapshot.counters.semanticRerankInputs);
        expect(rerank.judgments.length).toBe(snapshot.counters.semanticRerankJudgments);
        expect(rerank.receipts.length).toBe(snapshot.counters.semanticRerankReceipts);
        expect(rerank.counters.mutationAllowedCount).toBe(0);
        expect(rerank.receipts.every((receipt) => receipt.invariant === 'phase4_no_topology_commit')).toBe(true);
        expect(rerank.inputs.every((input) => input.queryLabels.length >= 3 && input.passage.length <= input.maxPassageChars)).toBe(true);
        expect(rerank.judgments.every((judgment) =>
            judgment.scores.every((score) => score.query.length > 20 && score.score >= 0 && score.score <= 1),
        )).toBe(true);
        expect(candidates.candidates.some((candidate) => candidate.semanticRerankJudgmentIds?.length)).toBe(true);
        const adjudication = snapshot.semanticAdjudicationSummary!;
        expect(adjudication.schemaVersion).toBe('phoenix-semantic-adjudication-dag/v1');
        expect(adjudication.sourceSnapshotId).toBe(snapshot.id);
        expect(adjudication.states).toEqual([
            'proposed',
            'supported',
            'accepted',
            'deferred',
            'rejected',
            'invalidated',
            'superseded',
        ]);
        expect(adjudication.decisions.length).toBe(snapshot.counters.semanticAdjudicationDecisions);
        expect(adjudication.mutations.length).toBe(snapshot.counters.semanticAdjudicationMutations);
        expect(adjudication.receipts.length).toBe(snapshot.counters.semanticAdjudicationReceipts);
        expect(adjudication.counters.topologyCommitCount).toBe(snapshot.counters.semanticAdjudicationTopologyCommits);
        expect(adjudication.counters.ledgerOnlyCount).toBe(snapshot.counters.semanticAdjudicationLedgerOnly);
        expect(adjudication.counters.topologyCommitCount).toBeGreaterThan(0);
        expect(adjudication.counters.appliedMutationCount).toBe(adjudication.mutations.length);
        expect(adjudication.receipts.every((receipt) => receipt.reversible)).toBe(true);
        expect(adjudication.decisions.filter((decision) => decision.state === 'accepted').every((decision) =>
            Boolean(decision.sourceHypothesis)
            && decision.evidenceTargetIds.length > 0
            && decision.scoringBundle.finalScore >= 0
            && decision.rationale.length > 0
            && Boolean(decision.undoReceiptId)
            && decision.affectedGraphAtomIds.length >= 2
            && decision.affectedGraphFactIds.length >= 1
            && decision.ledgerOnly === false,
        )).toBe(true);
        expect(adjudication.mutations.every((mutation) =>
            snapshot.edges.some((edge) => edge.id === mutation.createdEdgeId)
            && mutation.status === 'applied'
            && mutation.reversiblePatch.undoOperation === 'remove_semantic_edge_and_fact',
        )).toBe(true);
        expect(adjudication.mutations.every((mutation) =>
            mutation.createdEdge
            && Number.isInteger(mutation.createdEdge.weight)
            && mutation.createdEdge.weight >= 1
            && mutation.createdEdge.confidence >= 0
            && mutation.createdEdge.confidence <= 1,
        )).toBe(true);
        expect(snapshot.edges.every((edge) => Number.isInteger(edge.weight))).toBe(true);
        const evalLedger = snapshot.semanticEvalLedgerSummary!;
        expect(evalLedger.schemaVersion).toBe('phoenix-semantic-eval-ledger/v1');
        expect(evalLedger.sourceSnapshotId).toBe(snapshot.id);
        expect(evalLedger.entries.length).toBe(snapshot.counters.semanticEvalLedgerRows);
        expect(evalLedger.compactExport.rowCount).toBe(evalLedger.entries.length);
        expect(evalLedger.datasetPurpose).toEqual([
            'classifier_training',
            'reranker_eval',
            'router_tuning',
            'model_swap_regression',
        ]);
        expect(evalLedger.counters.acceptedCandidates).toBeGreaterThan(0);
        expect(evalLedger.counters.ambiguousCases).toBeGreaterThan(0);
        expect(evalLedger.counters.graphChangeRows).toBe(adjudication.counters.topologyCommitCount);
        expect(evalLedger.entries.every((entry) =>
            Boolean(entry.sourceHypothesis)
            && entry.evidenceTargetIds.length > 0
            && entry.scoringBundle.scoreParts.length > 0,
        )).toBe(true);
        const memoryBridge = snapshot.memoryGraphRagBridgeSummary!;
        expect(memoryBridge.schemaVersion).toBe('phoenix-memory-graphrag-bridge/v1');
        expect(memoryBridge.sourceSnapshotId).toBe(snapshot.id);
        expect(memoryBridge.paperShape.implementationMode).toBe('phoenix_bridge_contract');
        expect(memoryBridge.paperShape.arxivId).toBe('2606.00610');
        expect(memoryBridge.counters.schemaRecords).toBeGreaterThan(0);
        expect(memoryBridge.counters.factRecords).toBeGreaterThan(0);
        expect(memoryBridge.counters.passageRecords).toBeGreaterThan(0);
        expect(memoryBridge.counters.evalRowCount).toBe(snapshot.counters.memoryGraphRagEvalRows);
        expect(memoryBridge.counters.passedEvalRows).toBe(snapshot.counters.memoryGraphRagPassedEvalRows);
        expect(memoryBridge.counters.mutationAllowedCount).toBe(0);
        expect(memoryBridge.receipts.every((receipt) =>
            receipt.reversible
            && receipt.mutationAllowed === false
            && receipt.invariant === 'memorygraphrag_bridge_no_topology_commit',
        )).toBe(true);
        expect(memoryBridge.agentContracts.map((contract) => contract.surface)).toEqual([
            'observer_extraction',
            'reflector_compression',
            'retrieval_context',
            'conflict_resolution',
        ]);
        expect(memoryBridge.compactEvalLedger.rowCount).toBe(memoryBridge.evalRows.length);
        expect(memoryBridge.evalRows.some((row) => row.kind === 'hierarchical_retrieval')).toBe(true);
        expect(memoryBridge.evalRows.some((row) => row.kind === 'reflection_seed')).toBe(true);
    });

    it('keeps rejected adjudication decisions in the ledger without mutating topology', () => {
        const summary = buildGraphSemanticAdjudicationDAGSummary({
            id: 'graph-rebuild:test:reject',
            builtAt: 30,
            scopeId: 'scope',
            nodes: [
                { id: 'e-kai', entityId: 'e-kai', label: 'Kai', kind: 'CHARACTER', aliases: [], anchorIds: ['a-kai'], noteIds: ['n1'], totalMentions: 1 },
                { id: 'e-hazel', entityId: 'e-hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], anchorIds: ['a-hazel'], noteIds: ['n1'], totalMentions: 1 },
            ],
            entityAnchors: [
                { id: 'a-kai', noteId: 'n1', surface: 'Kai', sourceStart: 0, sourceEnd: 3, source: 'dictionary_match', confidence: 1, entityId: 'e-kai', status: 'accepted', generation: 1 },
                { id: 'a-hazel', noteId: 'n1', surface: 'Hazel', sourceStart: 10, sourceEnd: 15, source: 'dictionary_match', confidence: 1, entityId: 'e-hazel', status: 'accepted', generation: 1 },
            ],
            semanticCandidateSummary: {
                schemaVersion: 'phoenix-semantic-candidate-factory/v1',
                generatedAt: 30,
                sourceSnapshotId: 'graph-rebuild:test:reject',
                candidates: [{
                    id: 'semantic-candidate:relation:test-reject',
                    kind: 'relation_link',
                    status: 'proposed',
                    sourceTaskIds: ['task-1'],
                    sourceTargetIds: ['a-kai', 'a-hazel'],
                    targetIds: ['edge:test'],
                    evidenceIds: ['a-kai', 'a-hazel'],
                    sources: [{ kind: 'semantic_task', id: 'task-1', label: 'semantic_link' }],
                    scores: [{ kind: 'semantic', score: 0.2, weight: 1, sourceId: 'task-1', rationale: 'weak support' }],
                    confidence: 0.2,
                    noiseScore: 0.9,
                    rank: 0.22,
                    rationale: ['weak support'],
                    reversibleReceiptIds: ['receipt-1'],
                    mutationAllowed: false,
                    createdAt: 30,
                }],
                receipts: [],
                counters: {} as any,
            },
            semanticRerankSummary: {
                schemaVersion: 'phoenix-semantic-rerank/v1',
                generatedAt: 30,
                sourceSnapshotId: 'graph-rebuild:test:reject',
                modelId: 'knowledgator/gliclass-instruct-base-v1.0',
                runner: 'gliclass-query-label-rerank',
                scoreSource: 'deterministic_calibration',
                labels: [],
                inputs: [],
                judgments: [{
                    id: 'judgment-reject',
                    candidateId: 'semantic-candidate:relation:test-reject',
                    candidateKind: 'relation_link',
                    inputId: 'input-1',
                    decision: 'reject',
                    topLabelId: 'gliclass-label:reject_as_noise',
                    topLabelKind: 'reject_as_noise',
                    modelId: 'knowledgator/gliclass-instruct-base-v1.0',
                    runner: 'gliclass-query-label-rerank',
                    scoreSource: 'deterministic_calibration',
                    relevanceScore: 0.7,
                    calibratedScore: 0.61,
                    scores: [],
                    evidenceIds: ['a-kai', 'a-hazel'],
                    manifoldContributionIds: [],
                    rationale: ['reject_as_noise'],
                    reversibleReceiptId: 'rerank-receipt-1',
                }],
                receipts: [],
                counters: {} as any,
            },
        } as any, 30);

        expect(summary.decisions).toHaveLength(1);
        expect(summary.decisions[0]).toMatchObject({
            state: 'rejected',
            ledgerOnly: true,
            affectedGraphAtomIds: [],
            affectedGraphFactIds: [],
        });
        expect(summary.mutations).toHaveLength(0);
        expect(summary.receipts[0]).toMatchObject({
            mutationAllowed: false,
            invariant: 'phase5_ledger_only_no_topology_commit',
        });
    });

    it('does not promote broad chunk cues into every distant entity pair', () => {
        const text = `Kai received command from Allied Table. ${'quiet '.repeat(180)}Hazel watched the door.`;
        const alliedStart = text.indexOf('Allied Table');
        const hazelStart = text.indexOf('Hazel');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:local-pair-evidence',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-allied-table', 'Allied Table', [], 'NETWORK'),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [{
                id: 'note-1:chunk:0',
                noteId: 'note-1',
                start: 0,
                end: text.length,
                ordinal: 0,
                source: 'dynamic-chunking',
                role: 'authority_chain',
                meaningFrame: {
                    role: 'authority_chain',
                    splitReason: 'test',
                    breakPressure: 0,
                    mergePressure: 0,
                    entityPriors: [],
                    eventCues: [],
                    modalCues: [],
                    temporalCues: [],
                    authorityCues: ['command', 'table'],
                    evidenceCues: [],
                    carryoverIn: [],
                    carryoverOut: [],
                },
            }],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
                occurrence('note-1', 'e-allied-table', 'Allied Table', alliedStart, alliedStart + 12),
                occurrence('note-1', 'e-hazel', 'Hazel', hazelStart, hazelStart + 5),
            ],
            noteTexts: { 'note-1': text },
            builtAt: 18,
        });
        const relationshipPairs = snapshot.relationships.map((relationship) =>
            [relationship.sourceEntityId, relationship.relationType, relationship.targetEntityId].join('|'),
        );

        expect(relationshipPairs).toEqual(expect.arrayContaining([
            'e-allied-table|co_occurs_with|e-kai',
            'e-kai|command_or_service_tie|e-allied-table',
        ]));
        expect(relationshipPairs.some((pair) => pair.includes('e-hazel'))).toBe(false);
    });

    it('upgrades matching relationship candidates with explicit NLI hints', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:one',
            noteIds: ['note-1'],
            entities: [
                entity('e-kai', 'Kai', []),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 80, ordinal: 0, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('note-1', 'e-kai', 'Kai', 0, 3),
                occurrence('note-1', 'e-hazel', 'Hazel', 10, 15),
            ],
            relationshipHints: [{
                sourceId: 'entity:e-kai',
                targetId: 'entity:e-hazel',
                relationType: 'supports',
                status: 'accepted',
                confidence: 0.94,
                source: 'nli:modernbert',
                evidence: ['judgment:j-1'],
            }],
            builtAt: 12,
        });

        expect(snapshot.relationships).toHaveLength(1);
        expect(snapshot.relationships[0]).toMatchObject({
            relationType: 'supports',
            status: 'accepted',
            adjudicationSource: 'nli:modernbert',
        });
        expect(snapshot.counters.acceptedRelationships).toBe(1);
        expect(snapshot.counters.reviewRelationships).toBe(0);
    });

    it('reports exact missing upstream reasons instead of silent empty output', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            entities: [entity('e-kai', 'Kai', [])],
            occurrences: [
                occurrence('note-1', 'missing', 'Ghost', 0, 5),
                occurrence('note-1', 'e-kai', 'Kai', 4, 4),
                occurrence('note-1', 'e-kai', 'Kai', 6, 9),
            ],
            builtAt: 11,
        });

        expect(snapshot.nodes).toHaveLength(1);
        expect(snapshot.edges).toHaveLength(0);
        expect(snapshot.counters.dropReasons).toMatchObject({
            missingEntity: 1,
            invalidSpan: 1,
            singletonBucket: 1,
        });
    });
});

function entity(id: string, label: string, aliases: string[], kind = 'CHARACTER'): RegisteredEntity {
    return {
        id,
        label,
        kind: kind as any,
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

function occurrence(noteId: string, entityId: string, surface: string, sourceStart: number, sourceEnd: number, chunkId?: string): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}:${sourceStart}:${sourceEnd}`,
        noteId,
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd,
        surface,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: surface,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
        ...(chunkId ? { chunkId } : {}),
    };
}

function sameNoteEdge(edge: { sourceId: string; targetId: string }, events: { id: string; noteId: string }[]): boolean {
    const byId = new Map(events.map((event) => [event.id, event.noteId]));
    return byId.get(edge.sourceId) === byId.get(edge.targetId);
}

function kindCounts(kinds: string[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const kind of kinds) counts.set(kind, (counts.get(kind) || 0) + 1);
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}
