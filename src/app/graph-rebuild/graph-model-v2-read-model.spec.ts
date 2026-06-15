import { describe, expect, it } from 'vitest';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { buildGraphModelV2FromCompilerOutput } from './graph-compiler-read-model';
import { createGraphModelV2ReadModel } from './graph-model-v2-read-model';

describe('graph model v2 read model', () => {
    it('indexes atoms, facts, roles, tags, projection edges, and debug counters', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1'],
            entities: [
                entity('kai', 'Kai'),
                entity('hazel', 'Hazel'),
                entity('map', 'map', 'OBJECT'),
            ],
            chunks: [
                { id: 'chunk-1', noteId: 'note-1', start: 0, end: 32, ordinal: 0, source: 'note-block' },
            ],
            occurrences: [
                occurrence('note-1', 'kai', 'Kai', 0, 3),
                occurrence('note-1', 'hazel', 'Hazel', 9, 14),
                occurrence('note-1', 'map', 'map', 19, 22),
            ],
            candidateCount: 3,
            noteTexts: {
                'note-1': 'Kai gave Hazel the map at dawn.',
            },
            builtAt: 1,
        });
        const model = snapshot.graphModelV2;
        expect(model).toBeTruthy();

        const readModel = createGraphModelV2ReadModel(model!);
        const transfer = readModel.getFactsByFamily('transfer')[0];
        const cooccurrenceBundle = readModel.getBundlesByFamily('cooccurrence')[0];
        expect(readModel.getAtomsByKind('entity').map((atom) => atom.sourceId)).toEqual(expect.arrayContaining(['kai', 'hazel']));
        expect(readModel.getBundle(cooccurrenceBundle.id)).toBe(cooccurrenceBundle);
        expect(readModel.getFact(transfer.id)).toBe(transfer);
        expect(readModel.getRolesForFact(transfer.id).map((role) => role.role)).toEqual(expect.arrayContaining(['source', 'target', 'evidence']));
        expect(readModel.getStyleTagsForTarget(transfer.id, 'relationFamily')).toEqual(expect.arrayContaining([
            expect.objectContaining({ value: 'transfer' }),
        ]));
        expect(readModel.getProjectionEdgesForTarget(transfer.id).map((edge) => edge.projectionKind)).toContain('factRole');
        expect(readModel.getProjectionEdgesForTarget(cooccurrenceBundle.id).some((edge) => edge.sourceBundleId === cooccurrenceBundle.id)).toBe(true);

        expect(readModel.debugSummary()).toMatchObject({
            atomsByKind: expect.objectContaining({ entity: expect.any(Number) }),
            bundlesByFamily: expect.objectContaining({ cooccurrence: expect.any(Number) }),
            factsByFamily: expect.objectContaining({ transfer: expect.any(Number) }),
            hyperedgeFacts: expect.any(Number),
            stagedCooccurrenceBundles: expect.any(Number),
            projectionEdges: expect.any(Number),
            styleTags: expect.any(Number),
        });
    });

    it('preserves semantic hypergraph role names in the compiler read model', () => {
        const factId = 'fact:document-hyperedge:transfer-1';
        const model = buildGraphModelV2FromCompilerOutput('snapshot-1', {
            scopeId: 'global',
            builtAt: 1,
            atoms: [],
            bundles: [],
            facts: [{
                id: factId,
                lane: 'relationshipFact',
                predicate: 'transfer_possession',
                sourceRecordId: 'semantic-situation:1',
                status: 'accepted',
                evidenceIds: [],
                confidence: 0.92,
            }],
            roles: [
                { factId, role: 'recipient', semanticRole: 'recipient', atomId: 'atom:entity:hazel', confidence: 0.9 },
                { factId, role: 'theme', semanticRole: 'theme', atomId: 'atom:documentMention:key', confidence: 0.8 },
            ],
            projectedEdges: [],
            evidenceAnchors: [],
        } as any);

        expect(model.roles.map((role) => role.role)).toEqual(['recipient', 'theme']);
    });
});

function entity(id: string, label: string, kind = 'CHARACTER') {
    return {
        id,
        label,
        kind,
        aliases: [],
        createdAt: 1,
        updatedAt: 1,
    } as any;
}

function occurrence(noteId: string, entityId: string, surface: string, sourceStart: number, sourceEnd: number) {
    return {
        id: `${noteId}:${entityId}:${sourceStart}`,
        entityId,
        noteId,
        blockId: 'chunk-1',
        surface,
        sourceStart,
        sourceEnd,
        confidence: 0.9,
        status: 'accepted',
        source: 'accepted_suggestion',
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    } as any;
}
