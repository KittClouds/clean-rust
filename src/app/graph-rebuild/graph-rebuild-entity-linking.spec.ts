import { describe, expect, it } from 'vitest';

import { buildGraphRebuildFinalLinkPatchLog } from './graph-rebuild-final-linking';
import { buildGraphRebuildEntityLinkSuggestions } from './graph-rebuild-entity-linking';
import { buildBundleDedupeShadowLinks } from './graph-rebuild-shadow-linking';
import { buildGraphRebuildStructuralPostProcess } from './graph-rebuild-structural-postprocess';
import type {
    GraphRebuildEdge,
    GraphRebuildEntityAnchor,
    GraphRebuildMention,
    GraphRebuildNode,
    GraphRebuildRelationship,
} from './graph-rebuild-snapshot';

describe('graph rebuild entity linking', () => {
    it('suggests alias and unresolved mention links from indexed surfaces', () => {
        const anchors = [
            anchor('a-kai', 'e-kai', 'Kai'),
            anchor('a-kai-rowan', 'e-kai', 'Kai Rowan'),
            anchor('a-rowan', 'e-rowan', 'Rowan'),
        ];
        const nodes = [
            node('e-kai', 'Kai', 'CHARACTER', ['K']),
            node('e-rowan', 'Rowan', 'CHARACTER', []),
            node('e-nemo', 'Nemo', 'NETWORK', []),
        ];
        const mentions = [
            ...anchors,
            mention('m-nemo', 'Nemo', 'dropped', 42, 46),
            mention('m-unknown', 'Silver Door', 'dropped', 60, 71),
        ];

        const result = buildGraphRebuildEntityLinkSuggestions({
            mentions,
            entityAnchors: anchors,
            nodes,
            edges: [edge('e-kai', 'e-rowan', 2)],
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, [edge('e-kai', 'e-rowan', 2)]),
        });

        expect(result.suggestions).toEqual(expect.arrayContaining([
            expect.objectContaining({ decision: 'alias_of', surface: 'Kai Rowan', candidateEntityId: 'e-kai' }),
            expect.objectContaining({ decision: 'same_entity', surface: 'Nemo', candidateEntityId: 'e-nemo' }),
            expect.objectContaining({ decision: 'new_entity', surface: 'Silver Door' }),
        ]));
        expect(result.counters).toMatchObject({
            candidateMentions: 2,
            aliasOf: 1,
            newEntity: 1,
        });
    });

    it('keeps candidate output bounded and deterministic for heavy batches', () => {
        const nodes = Array.from({ length: 80 }, (_, index) =>
            node(`e-${index}`, `Entity ${index}`, index % 3 === 0 ? 'NETWORK' : 'CHARACTER', []));
        const anchors = nodes.map((row, index) => anchor(`a-${index}`, row.id, row.label));
        const mentions = [
            ...anchors,
            ...Array.from({ length: 320 }, (_, index) =>
                mention(`m-${index}`, index % 5 === 0 ? 'Unknown Surface' : `Entity ${index % 80}`, 'dropped', index * 3, index * 3 + 2)),
        ];
        const edges = nodes.slice(1).map((row, index) => edge(nodes[index].id, row.id, 1));

        const first = buildGraphRebuildEntityLinkSuggestions({
            mentions,
            entityAnchors: anchors,
            nodes,
            edges,
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, edges),
        });
        const second = buildGraphRebuildEntityLinkSuggestions({
            mentions,
            entityAnchors: anchors,
            nodes,
            edges,
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, edges),
        });

        expect(first.suggestions.length).toBeLessThanOrEqual(48);
        expect(first.suggestions.map((suggestion) => suggestion.id)).toEqual(second.suggestions.map((suggestion) => suggestion.id));
        expect(new Set(first.suggestions.map((suggestion) => suggestion.id)).size).toBe(first.suggestions.length);
    });

    it('builds narrow linker candidate packets from dynamic mentions without exact surface scans', () => {
        const anchors = [
            anchor('a-ryan', 'e-ryan', 'Ryan'),
            anchor('a-new-rome', 'e-new-rome', 'New Rome'),
            anchor('a-dynamis', 'e-dynamis', 'Dynamis'),
        ];
        const nodes = [
            node('e-ryan', 'Ryan', 'CHARACTER', ['Quicksave'], 5),
            node('e-new-rome', 'New Rome', 'LOCATION', [], 4),
            node('e-dynamis', 'Dynamis', 'NETWORK', [], 3),
            node('e-red-mesa', 'Red Mesa', 'LOCATION', [], 2),
        ];
        const mentions = [
            ...anchors,
            mention('m-new-roman', 'New Roman quarter', 'dropped', 900, 917),
        ];

        const result = buildGraphRebuildEntityLinkSuggestions({
            mentions,
            entityAnchors: anchors,
            nodes,
            edges: [edge('e-ryan', 'e-new-rome', 2)],
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, [edge('e-ryan', 'e-new-rome', 2)]),
        });

        expect(result.suggestions).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'entity-link:linker:m-new-roman:e-new-rome',
                candidateEntityId: 'e-new-rome',
                linkerCandidateEntityIds: ['e-new-rome'],
                linkerWindowId: 'note:1',
                phase: 'shadow',
                mutationAllowed: false,
                shadowKind: 'same_entity_suspicion',
            }),
        ]));
        expect(result.counters.linkerCandidates).toBe(1);
        expect(result.counters.shadowLinks).toBe(result.suggestions.length);
    });

    it('links expanded fantasy full names back to their short canonical name', () => {
        const anchors = [
            anchor('a-rift', 'e-rift', 'Rift'),
        ];
        const nodes = [
            node('e-rift', 'Rift', 'CHARACTER', [], 7),
            node('e-kai', 'Kai', 'CHARACTER', [], 5),
        ];
        const mentions = [
            ...anchors,
            mention('m-riftmach', 'Riftmach Gearlock', 'dropped', 220, 238),
        ];

        const result = buildGraphRebuildEntityLinkSuggestions({
            mentions,
            entityAnchors: anchors,
            nodes,
            edges: [],
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, []),
        });

        expect(result.suggestions).toEqual(expect.arrayContaining([
            expect.objectContaining({
                id: 'entity-link:linker:m-riftmach:e-rift',
                surface: 'Riftmach Gearlock',
                candidateEntityId: 'e-rift',
                decision: 'same_entity',
                rationale: expect.arrayContaining([
                    'linker: first-token stem',
                ]),
            }),
        ]));
    });

    it('stages relation duplicate suspicion as shadow-only review data', () => {
        const nodes = [
            node('e-kai', 'Kai', 'CHARACTER', []),
            node('e-hazel', 'Hazel', 'CHARACTER', []),
        ];
        const relationships = [
            relationship('rel-a', 'e-kai', 'e-hazel', 'protects', 'review', 0.7),
            relationship('rel-b', 'e-hazel', 'e-kai', 'protects', 'accepted', 0.82),
        ];

        const result = buildGraphRebuildEntityLinkSuggestions({
            mentions: [],
            entityAnchors: [],
            nodes,
            edges: [],
            relationships,
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, []),
        });

        expect(result.suggestions).toEqual(expect.arrayContaining([
            expect.objectContaining({
                shadowKind: 'relation_duplicate_suspicion',
                mutationAllowed: false,
                promotionState: 'blocked',
                relatedRelationIds: ['rel-b', 'rel-a'],
            }),
        ]));
    });

    it('stages compressed bundle dedupe as shadow-only review data', () => {
        const links = buildBundleDedupeShadowLinks([
            {
                id: 'bundle:canonical',
                family: 'cooccurrence',
                relationType: 'co_occurs_with',
                lane: 'cooccurrence_weak',
                status: 'review',
                confidence: 0.81,
                evidenceIds: ['evidence:a'],
                sourceRecordId: 'rel:a',
            },
            {
                id: 'bundle:duplicate',
                family: 'cooccurrence',
                relationType: 'co_occurs_with',
                lane: 'cooccurrence_weak',
                status: 'review',
                confidence: 0.84,
                evidenceIds: ['evidence:b'],
                sourceRecordId: 'rel:b',
                compression: {
                    model: 'jinaai/jina-embeddings-v5-text-nano',
                    clusterId: 'cluster:co:1',
                    canonicalBundleId: 'bundle:canonical',
                    duplicateOfBundleId: 'bundle:canonical',
                    outlierScore: 0.03,
                    neighborCount: 4,
                    semanticRank: 2,
                    rerankScore: 0.9,
                    rerankSource: 'semantic_cluster',
                    signals: ['compression:near_duplicate'],
                },
            },
        ]);

        expect(links).toEqual([expect.objectContaining({
            shadowKind: 'bundle_dedupe',
            mutationAllowed: false,
            promotionState: 'blocked',
            relatedBundleIds: ['bundle:duplicate', 'bundle:canonical'],
            clusterHintIds: ['cluster:co:1'],
        })]);

        const patchLog = buildGraphRebuildFinalLinkPatchLog([
            { ...links[0], promotionState: 'promoted' },
        ], 456);
        expect(patchLog.patches).toHaveLength(0);
        expect(patchLog.counters.failedReceipts).toBeGreaterThan(0);
    });

    it('final linker writes only promoted clean candidates into a reversible patch log', () => {
        const anchors = [
            anchor('a-kai', 'e-kai', 'Kai'),
            anchor('a-kai-rowan', 'e-kai', 'Kai Rowan'),
        ];
        const nodes = [node('e-kai', 'Kai', 'CHARACTER', ['K'], 8)];
        const result = buildGraphRebuildEntityLinkSuggestions({
            mentions: anchors,
            entityAnchors: anchors,
            nodes,
            edges: [],
            structuralPostProcess: buildGraphRebuildStructuralPostProcess(nodes, []),
        });
        const alias = result.suggestions.find((suggestion) => suggestion.decision === 'alias_of')!;
        const promoted = {
            ...alias,
            confidence: 0.93,
            promotionState: 'promoted' as const,
            promotionBlockedReasons: [],
        };

        const patchLog = buildGraphRebuildFinalLinkPatchLog([
            promoted,
            { ...alias, id: 'shadow:unpromoted-alias' },
        ], 123);

        expect(patchLog.patches).toEqual([
            expect.objectContaining({
                kind: 'alias_of',
                status: 'planned',
                sourceShadowLinkId: alias.id,
                canonicalEntityId: 'e-kai',
                alias: 'Kai Rowan',
                reversiblePatch: expect.objectContaining({
                    undoOperation: 'remove_alias_of',
                    createdAlias: 'Kai Rowan',
                }),
            }),
        ]);
        expect(patchLog.counters).toMatchObject({ planned: 1, failedReceipts: 0 });
        expect(patchLog.patches[0].receipts.every((receipt) => receipt.status === 'passed')).toBe(true);
    });
});

function node(id: string, label: string, kind: string, aliases: string[], totalMentions = 1): GraphRebuildNode {
    return {
        id,
        entityId: id,
        label,
        kind,
        aliases,
        anchorIds: [],
        noteIds: ['note'],
        totalMentions,
    };
}

function anchor(id: string, entityId: string, surface: string): GraphRebuildEntityAnchor {
    return {
        id,
        noteId: 'note',
        chunkId: 'chunk',
        surface,
        sourceStart: 0,
        sourceEnd: surface.length,
        source: 'dictionary_match',
        confidence: 0.9,
        entityId,
        status: 'accepted',
        generation: 1,
    };
}

function mention(id: string, surface: string, status: GraphRebuildMention['status'], sourceStart: number, sourceEnd: number): GraphRebuildMention {
    return {
        id,
        noteId: 'note',
        chunkId: 'chunk',
        surface,
        sourceStart,
        sourceEnd,
        source: 'machine_suggestion',
        confidence: 0.8,
        status,
    };
}

function edge(sourceId: string, targetId: string, weight: number): GraphRebuildEdge {
    return {
        id: `${sourceId}:anchored-cooccurrence:${targetId}`,
        sourceId,
        targetId,
        type: 'anchored-cooccurrence',
        weight,
        confidence: 0.8,
        evidenceAnchorIds: [],
        scopeKeys: ['chunk'],
        noteIds: ['note'],
    };
}

function relationship(
    id: string,
    sourceEntityId: string,
    targetEntityId: string,
    relationType: string,
    status: GraphRebuildRelationship['status'],
    confidence: number,
): GraphRebuildRelationship {
    return {
        id,
        sourceEntityId,
        targetEntityId,
        relationType,
        evidenceAnchorIds: [`evidence:${id}`],
        confidence,
        status,
        adjudicationSource: 'test',
        adjudicationScore: confidence,
        rationale: `${status} ${relationType}`,
        decisionEvidence: [],
    };
}
