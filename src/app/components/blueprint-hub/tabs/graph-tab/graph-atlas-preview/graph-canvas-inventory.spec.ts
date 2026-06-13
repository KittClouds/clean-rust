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

        expect(structure?.metadata?.['canvasLens']).toBe('structure');
        expect(structure?.metadata?.['sourceSnippet']).toBe('The archive opens.');
        expect(fact?.metadata?.['reviewObjectId']).toBe('unit:event');
        expect(fact?.metadata?.['reviewActions']).toContain('accept_fact');
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
        nodes: [{ id: 'entity:amara', entityId: 'entity:amara', label: 'Amara', kind: 'character', aliases: [], anchorIds: [], noteIds: ['note:1'], totalMentions: 1 }],
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
