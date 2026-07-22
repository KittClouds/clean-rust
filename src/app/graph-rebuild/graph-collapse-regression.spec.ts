import '@angular/compiler';
import { beforeEach, describe, expect, it } from 'vitest';

import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import {
    clearGraphCollapseTraces,
    graphCollapseTrace,
    recordGraphCollapseBoundary,
    recordGraphCollapseSnapshotBoundary,
} from './graph-collapse-trace';
import {
    GRAPH_ATLAS_FAMILIES,
    type GraphAtlasFamily,
    type GraphAtlasPacket,
} from './graph-atlas-packet';
import type { GraphRebuildSnapshot } from './graph-rebuild-snapshot';
import type { PhoenixDocumentFamilyName } from '../services/phoenix-document-index.model';
import {
    reconcileNativeAtlasPacketForTargets,
    recoverGraphRebuildOccurrences,
    snapshotAnchorsToGraphRebuildOccurrences,
} from './graph-rebuild.service';
import { finalizeGraphRebuildSnapshot } from './graph-snapshot-finalizer';
import { buildGraphSnapshotSourceEvidence } from './graph-snapshot-source-evidence';
import { buildGraphCanvasInventory } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-canvas-inventory';

describe('graph collapse audit regressions', () => {
    beforeEach(() => clearGraphCollapseTraces());

    it('records source and snapshot counts without changing snapshot rows', () => {
        const snapshot = anchoredSnapshot(10);
        recordGraphCollapseBoundary(snapshot.id, snapshot.scopeId, 'source_evidence', {
            persistedOccurrences: 0,
            stagedOccurrences: 2,
            recoveredOccurrences: 2,
            totalOccurrences: 2,
        });
        recordGraphCollapseSnapshotBoundary(snapshot, 'typescript_snapshot');

        const trace = graphCollapseTrace(snapshot.id);
        expect(trace?.samples.map((sample) => sample.boundary)).toEqual([
            'source_evidence',
            'typescript_snapshot',
        ]);
        expect(trace?.samples[1].counters).toMatchObject({
            mentions: 2,
            acceptedAnchors: 2,
            nodes: 2,
        });
        expect(snapshot.entityAnchors).toHaveLength(2);
    });

    it('carries validated prior anchors into the same-note rebuild when occurrence storage is cold', () => {
        const noteTexts = { 'note-1': 'Kai met Hazel. Hazel answered Kai.' };
        const entities = [entity('entity-kai', 'Kai'), entity('entity-hazel', 'Hazel')];
        const first = buildSnapshotFromRecoveredText(noteTexts, entities, 10);
        const cachedSnapshotOccurrences = snapshotAnchorsToGraphRebuildOccurrences(
            first,
            20,
            noteTexts,
        );
        const sourceEvidence = buildGraphSnapshotSourceEvidence({ cachedSnapshotOccurrences });
        const second = buildSnapshotFromOccurrences(
            noteTexts,
            entities,
            sourceEvidence.allOccurrences,
            20,
        );

        expect(sourceEvidence.counters.cachedSnapshot).toBeGreaterThan(0);
        expect(second.counters.mentions).toBe(first.counters.mentions);
        expect(second.counters.acceptedAnchors).toBe(first.counters.acceptedAnchors);
        expect(second.counters.nodes).toBe(first.counters.nodes);
        expect(second.counters.embeddingTargets).toBe(first.counters.embeddingTargets);
        expect(second.entityAnchors.map((anchor) => anchor.id)).toEqual(
            first.entityAnchors.map((anchor) => anchor.id),
        );
        expect(
            snapshotAnchorsToGraphRebuildOccurrences(first, 30, {
                'note-1': 'Mia met Rowan. Rowan answered Mia.',
            }),
        ).toEqual([]);
    });

    it('preserves native Atlas objects that do not require manifold targets', () => {
        const snapshot = rootsOnlySnapshot();
        const packet = realisticPacket(snapshot);

        const reconciled = reconcileNativeAtlasPacketForTargets(snapshot, packet);

        expect(packet.objects.length).toBeGreaterThan(packet.manifoldTargets.length);
        expect(reconciled.objects.length).toBe(packet.objects.length);
        expect(reconciled.counters.objects).toBe(packet.counters.objects);
        expect(
            Object.fromEntries(reconciled.counters.families.map((row) => [row.family, row.count])),
        ).toEqual(
            Object.fromEntries(packet.counters.families.map((row) => [row.family, row.count])),
        );
        expect(reconciled.objects.map((object) => object.id)).toEqual(
            expect.arrayContaining(['atlas:review:pending', 'atlas:hypergraph:pending']),
        );
    });

    it('keeps candidate and review objects visible without mutating committed topology', () => {
        const snapshot = rootsOnlySnapshot();
        snapshot.atlasPacket = reconcileNativeAtlasPacketForTargets(
            snapshot,
            realisticPacket(snapshot),
        );

        const inventory = buildGraphCanvasInventory(snapshot);

        expect(snapshot.nodes).toEqual([]);
        expect(snapshot.edges).toEqual([]);
        expect(inventory.nodes.map((node) => node.id)).toEqual(
            expect.arrayContaining(['atlas:review:pending', 'atlas:hypergraph:pending']),
        );
    });

    it('binds entity targets to registry objects when hypergraph roles share their source ids', () => {
        const snapshot = anchoredSnapshot(20);
        const packet = packetForTargets(snapshot);
        const entityTarget = snapshot.embeddingTargets.find((target) => target.kind === 'entity')!;
        const registryObject = packet.objects.find((object) =>
            object.sourceIds.includes(entityTarget.sourceId),
        )!;
        packet.objects.push({
            ...registryObject,
            id: 'atlas:hypergraph-role:collision',
            family: 'hypergraph',
            kind: 'actor',
            sourceIds: ['role:collision', entityTarget.sourceId],
        });
        packet.manifoldTargets = [];

        const reconciled = reconcileNativeAtlasPacketForTargets(snapshot, packet);
        const target = reconciled.manifoldTargets.find((row) => row.id === entityTarget.id)!;

        expect(target.objectId).toBe(registryObject.id);
        expect(target.family).toBe('registry');
        expect(reconciled.objects).toContainEqual(
            expect.objectContaining({ id: 'atlas:hypergraph-role:collision' }),
        );
    });

    it('refuses to replace a previously anchored nonempty scope with roots-only', () => {
        const previousSnapshot = anchoredSnapshot(20);
        const snapshot = rootsOnlySnapshot('note', 'note:note-1');
        snapshot.atlasPacket = packetForTargets(snapshot);
        const sourceEvidence = buildGraphSnapshotSourceEvidence({});

        expect(() =>
            finalizeGraphRebuildSnapshot({
                snapshot,
                sourceEvidence,
                previousSnapshot,
                hasNonemptySourceText: true,
            }),
        ).toThrow(/source-empty|roots-only|accepted source/i);
    });

    it('keeps tension routing out of Atlas truth families', () => {
        const documentFamilies: PhoenixDocumentFamilyName[] = [
            'entityState',
            'timeline',
            'tension',
        ];

        expect(documentFamilies).toContain('tension');
        expect(GRAPH_ATLAS_FAMILIES).not.toContain('tension');
    });
});

function buildSnapshotFromRecoveredText(
    noteTexts: Record<string, string>,
    entities: ReturnType<typeof entity>[],
    builtAt: number,
): GraphRebuildSnapshot {
    return buildSnapshotFromOccurrences(
        noteTexts,
        entities,
        recoverGraphRebuildOccurrences(noteTexts, entities, builtAt),
        builtAt,
    );
}

function buildSnapshotFromOccurrences(
    noteTexts: Record<string, string>,
    entities: ReturnType<typeof entity>[],
    occurrences: ReturnType<typeof recoverGraphRebuildOccurrences>,
    builtAt: number,
): GraphRebuildSnapshot {
    return buildGraphRebuildSnapshot({
        scopeKind: 'note',
        scopeId: 'note:note-1',
        noteIds: ['note-1'],
        entities,
        occurrences,
        chunks: [
            {
                id: 'note-1:chunk:0',
                noteId: 'note-1',
                start: 0,
                end: noteTexts['note-1'].length,
                ordinal: 0,
                source: 'dynamic-chunking',
            },
        ],
        noteTexts,
        builtAt,
    });
}

function anchoredSnapshot(builtAt: number): GraphRebuildSnapshot {
    const noteTexts = { 'note-1': 'Kai met Hazel.' };
    const entities = [entity('entity-kai', 'Kai'), entity('entity-hazel', 'Hazel')];
    return buildSnapshotFromRecoveredText(noteTexts, entities, builtAt);
}

function rootsOnlySnapshot(
    scopeKind: GraphRebuildSnapshot['scopeKind'] = 'global',
    scopeId = 'global',
): GraphRebuildSnapshot {
    return buildGraphRebuildSnapshot({
        scopeKind,
        scopeId,
        noteIds: ['note-1'],
        entities: [entity('entity-kai', 'Kai')],
        occurrences: [],
        chunks: [
            {
                id: 'note-1:chunk:0',
                noteId: 'note-1',
                start: 0,
                end: 18,
                ordinal: 0,
                source: 'dynamic-chunking',
            },
        ],
        noteTexts: { 'note-1': 'Kai crossed the gate.' },
        builtAt: 30,
    });
}

function realisticPacket(snapshot: GraphRebuildSnapshot): GraphAtlasPacket {
    const packet = packetForTargets(snapshot);
    packet.objects.push(
        {
            id: 'atlas:review:pending',
            family: 'review',
            status: 'review',
            kind: 'documentReview',
            label: 'Pending document review',
            noteIds: ['note-1'],
            chunkIds: ['note-1:chunk:0'],
            anchorIds: [],
            evidenceIds: ['evidence:pending'],
            sourceIds: ['review:pending'],
            targetIds: [],
        },
        {
            id: 'atlas:hypergraph:pending',
            family: 'hypergraph',
            status: 'proposed',
            kind: 'semanticSituation',
            label: 'Pending semantic situation',
            noteIds: ['note-1'],
            chunkIds: ['note-1:chunk:0'],
            anchorIds: [],
            evidenceIds: ['evidence:pending'],
            sourceIds: ['hypergraph:pending'],
            targetIds: [],
        },
    );
    packet.counters.objects = packet.objects.length;
    packet.counters.families = familyRows(packet);
    return packet;
}

function packetForTargets(snapshot: GraphRebuildSnapshot): GraphAtlasPacket {
    const objects = snapshot.embeddingTargets.map((target) => ({
        id: `atlas:${target.id}`,
        family: familyFor(target.kind),
        status: 'accepted' as const,
        kind: target.kind,
        label: target.label,
        styleKey: target.styleKey,
        lane: target.lane,
        structuralRole: target.structuralRole,
        registryEntityId: target.entityId,
        noteIds: target.noteId ? [target.noteId] : [],
        chunkIds: target.chunkId ? [target.chunkId] : [],
        anchorIds: target.kind === 'anchor' ? target.evidenceIds : [],
        evidenceIds: target.evidenceIds,
        sourceIds: [target.sourceId],
        targetIds: [],
    }));
    const packet: GraphAtlasPacket = {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: snapshot.id,
        scopeKind: snapshot.scopeKind,
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        sourceContract: {
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            vectorContract: 'vectors-missing',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        },
        objects,
        manifoldTargets: snapshot.embeddingTargets.map((target) => ({
            id: target.id,
            objectId: `atlas:${target.id}`,
            family: familyFor(target.kind),
            admission: target.admissionStatus === 'deferred' ? 'deferred' : 'admitted',
            vectorStatus: 'missing',
            coordinateSource: 'none',
            status: 'accepted',
            kind: target.kind,
            label: target.label,
            entityKind: target.entityKind,
            styleKey: target.styleKey,
            lane: target.lane,
            structuralRole: target.structuralRole,
            sourceId: target.sourceId,
            registryEntityId: target.entityId,
            noteId: target.noteId,
            chunkId: target.chunkId,
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds,
        })),
        counters: {
            objects: objects.length,
            manifoldTargets: snapshot.embeddingTargets.length,
            registryEntities: snapshot.nodes.length,
            evidenceAnchors: snapshot.entityAnchors.length,
            modelVectors: 0,
            families: [],
        },
    };
    packet.counters.families = familyRows(packet);
    return packet;
}

function familyRows(packet: GraphAtlasPacket): Array<{ family: GraphAtlasFamily; count: number }> {
    const counts = new Map<GraphAtlasFamily, number>();
    for (const object of packet.objects)
        counts.set(object.family, (counts.get(object.family) || 0) + 1);
    return [...counts.entries()].map(([family, count]) => ({ family, count }));
}

function familyFor(kind: string): GraphAtlasFamily {
    if (kind === 'entity') return 'registry';
    if (kind === 'anchor' || kind === 'evidenceSpan') return 'evidence';
    if (kind === 'graphFact' || kind === 'event') return 'fact';
    return 'structure';
}

function entity(id: string, label: string) {
    return {
        id,
        label,
        kind: 'CHARACTER' as const,
        aliases: [],
        attributes: {},
        firstNote: 'note-1',
        totalMentions: 1,
        createdAt: new Date(1),
        lastSeenDate: new Date(1),
        createdBy: 'extraction' as const,
    };
}
