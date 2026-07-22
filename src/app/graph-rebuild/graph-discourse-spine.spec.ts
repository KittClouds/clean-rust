import { describe, expect, it } from 'vitest';

import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import type { EntityOccurrence } from '../lib/dexie/db';
import type { RegisteredEntity } from '../lib/registry';

describe('Graph Discourse Spine', () => {
    it('classifies document hierarchy targets and proposes read-only wormholes', () => {
        const noteOne = [
            'Chapter four: Brynwyn refused the crown and remembered the oath.',
            'The quiet room turned into a warning.',
            'Hazel called Brynwyn the north star.',
        ].join(' ');
        const noteTwo = [
            'Chapter forty: The captain rejected the throne and kept the old promise.',
            'The silent hall became a warning.',
            'Hazel called Northstar back.',
        ].join(' ');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'multiNote',
            scopeId: 'multi:resonance',
            noteIds: ['chapter-04', 'chapter-40'],
            entities: [
                entity('e-brynwyn', 'Brynwyn', ['The captain', 'Northstar']),
                entity('e-hazel', 'Hazel', []),
            ],
            chunks: [
                { id: 'chapter-04:chunk:0', noteId: 'chapter-04', start: 0, end: noteOne.length, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'chapter-40:chunk:0', noteId: 'chapter-40', start: 0, end: noteTwo.length, ordinal: 40, source: 'dynamic-chunking' },
            ],
            occurrences: [
                occurrence('chapter-04', 'e-brynwyn', 'Brynwyn', noteOne.indexOf('Brynwyn'), 'chapter-04:chunk:0'),
                occurrence('chapter-04', 'e-hazel', 'Hazel', noteOne.indexOf('Hazel'), 'chapter-04:chunk:0'),
                occurrence('chapter-40', 'e-brynwyn', 'The captain', noteTwo.indexOf('The captain'), 'chapter-40:chunk:0'),
                occurrence('chapter-40', 'e-brynwyn', 'Northstar', noteTwo.indexOf('Northstar'), 'chapter-40:chunk:0'),
                occurrence('chapter-40', 'e-hazel', 'Hazel', noteTwo.indexOf('Hazel'), 'chapter-40:chunk:0'),
            ],
            noteTexts: { 'chapter-04': noteOne, 'chapter-40': noteTwo },
            builtAt: 42,
        });

        const spine = snapshot.discourseSpineSummary;
        expect(spine).toBeTruthy();
        expect(spine?.schemaVersion).toBe('phoenix-discourse-spine/v1');
        expect(spine?.invariant).toBe('wormholes_are_proposals_not_edges');
        expect(spine?.counters).toMatchObject({
            documentRoots: 2,
            documents: 2,
            chunks: 2,
            mutationAllowedCount: 0,
        });
        expect(spine?.counters.byLabelKind.domain).toBe(spine?.counters.targetCount);
        expect(spine?.clusters.map((cluster) => cluster.kind)).toEqual(expect.arrayContaining([
            'domain_region',
            'aspect_region',
            'document_family',
        ]));

        const resonance = spine?.bridges.find((bridge) => bridge.kind === 'resonance');
        const resolution = spine?.bridges.find((bridge) => bridge.kind === 'resolution');
        expect(resonance).toEqual(expect.objectContaining({
            mutationAllowed: false,
            adjudicationState: 'proposed',
        }));
        expect(resonance?.sharedLabelIds.length).toBeGreaterThan(0);
        expect(resolution).toEqual(expect.objectContaining({
            mutationAllowed: false,
            sharedEntityIds: expect.arrayContaining(['e-brynwyn']),
        }));
        expect(resolution?.scoringBundle.corefPressure).toBeGreaterThan(0.5);
        expect(spine?.compactBridgeLedger.rowCount).toBe(spine?.bridges.length);
        expect(spine?.receipts.every((receipt) => receipt.invariant === 'discourse_spine_no_topology_commit')).toBe(true);
        expect(spine?.receipts.some((receipt) => receipt.mutationAllowed)).toBe(false);

        const edgeIds = new Set(snapshot.edges.map((edge) => edge.id));
        expect(spine?.bridges.every((bridge) => !edgeIds.has(bridge.id))).toBe(true);
        expect(snapshot.counters.discourseSpineResonance).toBeGreaterThan(0);
        expect(snapshot.counters.discourseSpineResolution).toBeGreaterThan(0);
    });
});

function entity(id: string, label: string, aliases: string[]): RegisteredEntity {
    return {
        id,
        label,
        kind: 'CHARACTER' as any,
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
    sourceStart: number,
    chunkId: string,
): EntityOccurrence {
    return {
        id: `${noteId}:${entityId}:${sourceStart}:${surface}`,
        noteId,
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd: sourceStart + surface.length,
        surface,
        source: 'dictionary_match',
        confidence: 0.9,
        excerpt: surface,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
        chunkId,
    };
}
