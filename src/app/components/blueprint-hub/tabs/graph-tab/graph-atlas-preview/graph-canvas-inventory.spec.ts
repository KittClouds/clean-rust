import { describe, expect, it } from 'vitest';

import { buildGraphCanvasInventory } from './graph-canvas-inventory';
import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';

describe('graph canvas inventory', () => {
    it('projects structure, facts, discourse clusters, and wormholes as inspectable graph objects', () => {
        const inventory = buildGraphCanvasInventory(snapshot());

        const structure = inventory.nodes.find((node) => node.id === 'structure:unit:section');
        const fact = inventory.nodes.find((node) => node.id === 'fact:unit:event');
        const discourse = inventory.nodes.find((node) => node.id === 'discourse:target:a');
        const wormhole = inventory.edges.find((edge) => edge.id === 'wormhole:1');
        const factId = 'fact:document-hyperedge:hyperedge:1';
        const situation = inventory.nodes.find((node) => node.id === `situation:${factId}`);
        const actor = inventory.edges.find((edge) => edge.id === `situation-role:${factId}:actor:entity:amara`);

        expect(structure?.metadata?.['canvasLens']).toBe('structure');
        expect(structure?.metadata?.['sourceSnippet']).toBe('The archive opens.');
        expect(fact?.metadata?.['reviewObjectId']).toBe('unit:event');
        expect(fact?.metadata?.['reviewActions']).toContain('accept_fact');
        expect(situation?.metadata?.['sourceType']).toBe('rust-compiled-semantic-situation');
        expect(situation?.metadata?.['compilerSource']).toBe('rust');
        expect(situation?.metadata?.['memberIds']).toEqual(['entity:amara', 'entity:hazel']);
        expect(actor).toMatchObject({
            sourceId: `situation:${factId}`,
            targetId: 'entity:amara',
            type: 'role:actor',
        });
        expect(discourse?.metadata?.galaxyId).toBe('discourse-cluster:cluster:1');
        expect(wormhole?.metadata?.['interactionKind']).toBe('wormhole');
        expect(wormhole?.metadata?.['evidenceIds']).toEqual(['target:a', 'target:b']);
    });
});

function snapshot(): GraphRebuildSnapshot {
    const confidence = { score: 0.84, source: 'surface', reasons: ['heading'] } as const;
    const lineage = {
        noteId: 'note:1',
        documentUnitId: 'unit:section',
        parentUnitIds: [],
        sourceStart: 0,
        sourceEnd: 18,
        lens: 'surface',
    } as const;
    const section = {
        id: 'unit:section', noteId: 'note:1', kind: 'section', label: 'Archive', start: 0, end: 18,
        depth: 1, childIds: ['unit:event'], confidence, lineage, anchorPolicy: 'sidecar_only', ordinal: 0,
    };
    const fact = {
        id: 'unit:event', noteId: 'note:1', kind: 'event', label: 'Event candidate', start: 0, end: 18,
        depth: 2, parentId: 'unit:section', childIds: [],
        confidence: { score: 0.72, source: 'graph_fact', reasons: ['event'] },
        lineage: { ...lineage, documentUnitId: 'unit:event', parentUnitIds: ['unit:section'], lens: 'graph_fact' },
        anchorPolicy: 'sidecar_only', subjectSurfaces: ['Amara'], objectSurfaces: [],
        evidenceSpanIds: ['evidence:1'], reviewState: 'proposed',
    };
    return {
        nodes: [
            { id: 'entity:amara', entityId: 'entity:amara', label: 'Amara', kind: 'character', aliases: [], anchorIds: [], noteIds: ['note:1'], totalMentions: 1 },
            { id: 'entity:hazel', entityId: 'entity:hazel', label: 'Hazel', kind: 'character', aliases: [], anchorIds: [], noteIds: ['note:1'], totalMentions: 1 },
        ],
        edges: [],
        chunks: [],
        entityAnchors: [],
        documentSidecarSummary: {
            units: [section, fact], sections: [section], regions: [], rhetoricalUnits: [], retrievalUnits: [],
            graphFactCandidates: [fact],
            evidenceSpans: [{
                id: 'evidence:1', noteId: 'note:1', unitId: 'unit:section', start: 0, end: 18,
                preview: 'The archive opens.', textHash: 'hash', confidence, lineage, anchorPolicy: 'sidecar_only',
            }],
        },
        documentReviewSummary: {
            rows: [{
                objectId: 'unit:event', title: 'Event candidate', subtitle: 'event', detail: 'A proposed event.',
                state: 'proposed', detector: 'graph_fact', noteId: 'note:1', sourceStart: 0, sourceEnd: 18,
                confidence: 0.72, parentUnitIds: ['unit:section'], childUnitIds: [], evidenceSpanIds: ['evidence:1'],
                relatedObjectIds: [], why: ['event'], receiptIds: [],
                availableActions: [{ kind: 'accept_fact' }, { kind: 'reject_fact' }],
            }],
        },
        documentCompilerSummary: {
            hyperedges: [{
                id: 'hyperedge:1',
                predicate: 'opens_for',
                frame: 'access_enablement',
                frameFamily: 'causation',
                situationKind: 'event',
                sourceKind: 'relation_bundle',
                roles: [
                    {
                        id: 'role:actor', role: 'actor', semanticRole: 'actor',
                        targetId: 'entity:amara', targetKind: 'entity', confidence: 0.91, resolved: true,
                    },
                    {
                        id: 'role:recipient', role: 'recipient', semanticRole: 'recipient',
                        targetId: 'entity:hazel', targetKind: 'entity', confidence: 0.86, resolved: true,
                    },
                ],
                evidenceSpanIds: ['evidence:1'],
                confidence: 0.89,
                status: 'pending_commit',
                nary: true,
                compilationBasis: 'semantic_situation_frame',
                provenance: {
                    sourceObjectId: 'unit:event',
                    sourceObjectKind: 'relation_bundle',
                    reviewState: 'accepted',
                    noteId: 'note:1',
                    sourceStart: 0,
                    sourceEnd: 18,
                    evidenceSpanIds: ['evidence:1'],
                    lineageUnitIds: ['unit:event'],
                    reasons: ['fixture'],
                },
            }],
            entityMentions: [],
        },
        graphCompilerSource: 'rust',
        graphCompiler: {
            facts: [{
                id: 'fact:document-hyperedge:hyperedge:1',
                lane: 'relationshipFact',
                predicate: 'access_enablement',
                sourceRecordId: 'semantic:situation:1',
                status: 'accepted',
                evidenceIds: ['atom:documentEvidence:evidence:1'],
                confidence: 0.89,
                semanticSituationId: 'semantic:situation:1',
                semanticFrame: 'access_enablement',
                factuality: 'asserted',
            }],
            roles: [
                {
                    factId: 'fact:document-hyperedge:hyperedge:1',
                    role: 'actor',
                    semanticRole: 'actor',
                    atomId: 'atom:entity:entity:amara',
                    confidence: 0.91,
                    resolved: true,
                },
                {
                    factId: 'fact:document-hyperedge:hyperedge:1',
                    role: 'recipient',
                    semanticRole: 'recipient',
                    atomId: 'atom:entity:entity:hazel',
                    confidence: 0.86,
                    resolved: true,
                },
            ],
            atoms: [
                { id: 'atom:entity:entity:amara', kind: 'entity', sourceId: 'entity:amara', entityId: 'entity:amara', label: 'Amara', evidenceIds: [] },
                { id: 'atom:entity:entity:hazel', kind: 'entity', sourceId: 'entity:hazel', entityId: 'entity:hazel', label: 'Hazel', evidenceIds: [] },
            ],
            evidenceAnchors: [],
        },
        discourseSpineSummary: {
            implementationMode: 'deterministic_registry',
            targets: [
                { targetId: 'target:a', sourceId: 'a', kind: 'chunk', label: 'Archive opening', parentTargetIds: [], entityIds: ['entity:amara'], labelIds: [] },
                { targetId: 'target:b', sourceId: 'b', kind: 'chunk', label: 'Archive echo', parentTargetIds: [], entityIds: [], labelIds: [] },
            ],
            labels: [],
            clusters: [{ id: 'cluster:1', kind: 'domain_region', label: 'Archive theme', targetIds: ['target:a', 'target:b'], medoidTargetId: 'target:a', score: 0.81, rationale: ['shared domain'], receiptId: 'r:1' }],
        },
        discoursePromotionSurfaceSummary: {
            chunkWormholes: [{
                id: 'wormhole:1', sourceTargetId: 'target:a', targetTargetId: 'target:b', score: 0.88,
                state: 'supported', label: 'accepted_candidate', evidenceTargetIds: ['target:a', 'target:b'], flags: ['shared domain'],
            }],
        },
    } as unknown as GraphRebuildSnapshot;
}
