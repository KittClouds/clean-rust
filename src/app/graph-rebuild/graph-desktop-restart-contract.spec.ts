import '@angular/compiler';
import { describe, expect, it } from 'vitest';

import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { assertRunReceiptParity } from './graph-rebuild-pipeline.service';
import {
    graphRebuildSnapshotContentBlobEntries,
    graphRebuildSnapshotContentBlobDocuments,
    graphRebuildSnapshotPersistenceView,
    graphRebuildSnapshotToScopedDocument,
    scopedDocumentToGraphRebuildContentBlob,
    scopedDocumentToGraphRebuildSnapshot,
} from './graph-rebuild.service';
import {
    assertGraphSnapshotAuthority,
    graphSnapshotContentHash,
    hydrateGraphSnapshotContent,
    sealGraphSnapshotAuthority,
    type GraphSnapshotHydrationBlob,
} from './graph-snapshot-authority';
import { bindGraphSemanticDiscoverySnapshotIdentity } from './graph-semantic-discovery-authority';
import { finalizeGraphRebuildSnapshot } from './graph-snapshot-finalizer';
import type {
    GraphRebuildContentBlobField,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
    GraphIndexRunReceipt,
} from './graph-rebuild-snapshot';
import { buildGraphCanvasInventory } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-canvas-inventory';
import { buildGraphRebuildEmbeddingAtlas } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-rebuild-embedding-atlas';

describe('desktop graph snapshot restart contract', () => {
    it('restarts with identical truth rows, packet families, and rendered hierarchy', () => {
        const before = restartFixture();
        const expected = sealGraphSnapshotAuthority(before);
        const primary = graphRebuildSnapshotToScopedDocument(before);
        const persisted = scopedDocumentToGraphRebuildSnapshot(primary);
        expect(persisted).toBeTruthy();
        expect(persisted?.nodes).toEqual([]);
        expect(persisted?.embeddingTargets).toEqual([]);

        const blobs = Object.fromEntries(graphRebuildSnapshotContentBlobDocuments(before).map((document) => {
            const blob = scopedDocumentToGraphRebuildContentBlob(document);
            expect(blob).toBeTruthy();
            return [blob!.field, blob!];
        })) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;
        const after = hydrateGraphSnapshotContent(persisted!, blobs);
        const actual = assertGraphSnapshotAuthority(after);

        expect(actual.snapshotId).toBe(expected.snapshotId);
        expect(actual.contentHash).toBe(expected.contentHash);
        expect(actual.counts).toEqual(expected.counts);
        expect(actual.counts.mentions).toBeGreaterThan(0);
        expect(actual.counts.causalEdges).toBe(1);
        expect(actual.counts.coreferenceRecoveries).toBe(1);
        expect(actual.counts.packetParentLinks).toBeGreaterThan(0);

        const graph = buildGraphCanvasInventory(after);
        const embed = buildGraphRebuildEmbeddingAtlas(after, 'lorentz');
        const packetTargetIds = new Set(after.atlasPacket?.manifoldTargets.map((target) => target.id) || []);
        expect(graph.nodes.length).toBe(actual.counts.packetObjects);
        expect(embed.nodes.length).toBeGreaterThan(0);
        expect(embed.nodes.every((node) => packetTargetIds.has(node.id))).toBe(true);
        expect(embed.edges.length).toBeGreaterThan(0);
        expect(embed.nodes.some((node) => node.metadata?.['signalParentIds'])).toBe(true);
    });

    it('rebinds stable candidate blobs to the authoritative snapshot identity', () => {
        const first = restartFixture();
        bindGraphSemanticDiscoverySnapshotIdentity(first);
        sealGraphSnapshotAuthority(first);
        const firstEntries = graphRebuildSnapshotContentBlobEntries(first);

        const next = restartFixture();
        next.id = `${first.id}:next`;
        next.builtAt += 1;
        if (next.atlasPacket) {
            next.atlasPacket = { ...next.atlasPacket, snapshotId: next.id, builtAt: next.builtAt };
        }
        bindGraphSemanticDiscoverySnapshotIdentity(next);
        sealGraphSnapshotAuthority(next);
        const nextEntries = graphRebuildSnapshotContentBlobEntries(next);
        const persisted = graphRebuildSnapshotPersistenceView(next, nextEntries);
        const firstEntryByField = new Map(firstEntries.map((entry) => [entry.field, entry]));
        const blobs = Object.fromEntries(nextEntries.map((entry) => {
            const stored = firstEntryByField.get(entry.field) || entry;
            return [entry.field, {
                scopeId: next.scopeId,
                field: entry.field,
                hash: entry.ref.hash,
                value: scopedDocumentToGraphRebuildContentBlob(
                    graphRebuildSnapshotContentBlobDocuments(first, [stored])[0],
                )!.value,
            }];
        })) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;

        expect(firstEntryByField.get('semanticCandidateSummary')?.documentKey)
            .toBe(nextEntries.find((entry) => entry.field === 'semanticCandidateSummary')?.documentKey);
        const hydrated = hydrateGraphSnapshotContent(persisted, blobs);
        expect(hydrated.semanticCandidateSummary?.sourceSnapshotId).toBe(next.id);
        expect(hydrated.manifoldSpecializationSummary?.sourceSnapshotId).toBe(next.id);
        expect(() => assertGraphSnapshotAuthority(hydrated)).not.toThrow();
    });

    it('fails closed when a persisted content blob is changed', () => {
        const snapshot = restartFixture();
        sealGraphSnapshotAuthority(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(graphRebuildSnapshotToScopedDocument(snapshot))!;
        const blobs = Object.fromEntries(graphRebuildSnapshotContentBlobDocuments(snapshot).map((document) => {
            const blob = scopedDocumentToGraphRebuildContentBlob(document)!;
            return [blob.field, blob];
        })) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;
        const source = blobs.sourceRows!;
        blobs.sourceRows = { ...source, value: { ...(source.value as object), mentions: [] } };

        expect(() => hydrateGraphSnapshotContent(persisted, blobs)).toThrow(/hash mismatch/);
    });

    it('hydrates legacy raw-hash content blobs and lets the next persist rewrite them forward', () => {
        const snapshot = restartFixture();
        sealGraphSnapshotAuthority(snapshot);
        const persisted = scopedDocumentToGraphRebuildSnapshot(graphRebuildSnapshotToScopedDocument(snapshot))!;
        const blobs = Object.fromEntries(graphRebuildSnapshotContentBlobDocuments(snapshot).map((document) => {
            const blob = scopedDocumentToGraphRebuildContentBlob(document)!;
            return [blob.field, blob];
        })) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;
        const source = blobs.sourceRows!;
        const legacyHash = graphSnapshotContentHash(JSON.stringify(source.value));
        persisted.contentManifest = {
            ...persisted.contentManifest!,
            refs: {
                ...persisted.contentManifest!.refs,
                sourceRows: {
                    ...persisted.contentManifest!.refs.sourceRows!,
                    hash: legacyHash,
                },
            },
        };
        blobs.sourceRows = { ...source, hash: legacyHash };

        const hydrated = hydrateGraphSnapshotContent(persisted, blobs);

        expect(hydrated.mentions.length).toBe(snapshot.mentions.length);
        expect(assertGraphSnapshotAuthority(hydrated).contentHash).toBe(snapshot.authorityContract?.contentHash);
    });

    it('fails closed when target lanes survive but source rows are hollow', () => {
        const snapshot = restartFixture();
        snapshot.mentions = [];
        snapshot.entityAnchors = [];
        snapshot.relationships = [];
        snapshot.events = [];
        snapshot.temporalEdges = [];
        snapshot.causalEdges = [];
        snapshot.memoryState = [];
        snapshot.counters = {
            ...snapshot.counters,
            mentions: 0,
            acceptedAnchors: 0,
            relationships: 0,
            events: 0,
            temporalEdges: 0,
            causalEdges: 0,
            memoryState: 0,
        };
        if (snapshot.atlasPacket) {
            snapshot.atlasPacket.counters.evidenceAnchors = 0;
        }

        expect(() => sealGraphSnapshotAuthority(snapshot))
            .toThrow(/entity target lanes without source anchors/);
    });

    it('allows source-empty runs to retain only document and structure roots', () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'global',
            scopeId: 'global',
            noteIds: ['note-1', 'note-2', 'note-3'],
            entities: [
                entity('entity-kai', 'Kai', 'CHARACTER'),
            ],
            occurrences: [],
            chunks: [
                { id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: 12, ordinal: 0, source: 'dynamic-chunking' },
                { id: 'note-2:chunk:0', noteId: 'note-2', start: 0, end: 12, ordinal: 1, source: 'dynamic-chunking' },
                { id: 'note-3:chunk:0', noteId: 'note-3', start: 0, end: 12, ordinal: 2, source: 'dynamic-chunking' },
            ],
            noteTexts: {
                'note-1': 'No anchors.',
                'note-2': 'No anchors.',
                'note-3': 'No anchors.',
            },
            builtAt: 43,
        });

        expect(snapshot.nodes).toEqual([]);
        expect(snapshot.embeddingTargets.every((target) =>
            target.kind === 'note' || target.kind === 'chunk' || target.kind === 'structureRoot',
        )).toBe(true);
        snapshot.atlasPacket = atlasPacket(snapshot);
        expect(() => finalizeGraphRebuildSnapshot({ snapshot })).not.toThrow();
    });

    it('finalizer refuses registry-only entities as committed graph topology', () => {
        const snapshot = restartFixture();
        snapshot.nodes.push({
            id: 'entity-registry-only',
            entityId: 'entity-registry-only',
            label: 'Registry Only',
            kind: 'CHARACTER',
            aliases: [],
            anchorIds: [],
            noteIds: [],
            totalMentions: 0,
        });
        snapshot.embeddingTargets.push({
            id: 'embed:entity:entity-registry-only',
            kind: 'entity',
            sourceId: 'entity-registry-only',
            entityId: 'entity-registry-only',
            entityKind: 'CHARACTER',
            label: 'Registry Only',
            text: 'registry-only entity',
            evidenceIds: [],
            parentIds: [],
        } as GraphRebuildEmbeddingTarget);

        expect(() => finalizeGraphRebuildSnapshot({ snapshot }))
            .toThrow(/registry-only graph node entity-registry-only/);
    });

    it('finalizer refuses semantic discovery edges as asserted graph truth', () => {
        const snapshot = restartFixture();
        snapshot.edges.push({
            id: 'semantic-adjudication:semantic-relation-link:leak',
            sourceId: 'entity-kai',
            targetId: 'entity-hazel',
            type: 'semantic-relation-link',
            weight: 1,
            confidence: 0.9,
            evidenceAnchorIds: [snapshot.entityAnchors[0].id],
            scopeKeys: ['semantic-adjudication:global'],
            noteIds: ['note-1'],
        });

        expect(() => finalizeGraphRebuildSnapshot({ snapshot }))
            .toThrow(/asserted truth authority.*deterministic_graph_processing.*semantic adjudication edges/i);
    });

    it('fails closed when any projection receipt diverges from the snapshot', () => {
        const snapshot = restartFixture();
        const contract = sealGraphSnapshotAuthority(snapshot);
        const receipt = {
            schemaVersion: 'phoenix-graph-index-run/v1',
            snapshotId: snapshot.id,
            counters: snapshot.counters,
            stageReceipts: [{
                id: 'snapshotAuthorityContract',
                label: 'Snapshot Authority Contract',
                status: 'completed',
                startedAt: 1,
                completedAt: 1,
                durationMs: 0,
                outputCount: 0,
                counters: { authorityParity: 1 },
                message: contract.contentHash,
            }],
            projectionReceipts: [{
                mode: 'hybrid',
                status: 'synced',
                startedAt: 1,
                completedAt: 1,
                durationMs: 0,
                targetCount: contract.counts.embeddingTargets - 1,
                vectorCount: 0,
                message: 'mismatched projection',
            }],
        } as GraphIndexRunReceipt;

        expect(() => assertRunReceiptParity(receipt, snapshot)).toThrow(/receipt parity failed/);
    });
});

function restartFixture(): GraphRebuildSnapshot {
    const noteText = 'Kai warned Hazel because Rowan opened the gate. He stopped the alarm.';
    const snapshot = buildGraphRebuildSnapshot({
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        entities: [
            entity('entity-kai', 'Kai', 'CHARACTER'),
            entity('entity-hazel', 'Hazel', 'CHARACTER'),
            entity('entity-rowan', 'Rowan', 'CHARACTER'),
        ],
        occurrences: [
            occurrence('entity-kai', 'Kai', 0, 3),
            occurrence('entity-hazel', 'Hazel', 11, 16),
            occurrence('entity-rowan', 'Rowan', 25, 30),
        ],
        chunks: [{ id: 'note-1:chunk:0', noteId: 'note-1', start: 0, end: noteText.length, ordinal: 0, source: 'dynamic-chunking' }],
        noteTexts: { 'note-1': noteText },
        documentSemanticSummary: semanticSummary(),
        builtAt: 42,
    });
    snapshot.causalEdges = [{
        id: 'causal:gate-alarm',
        sourceId: 'event:gate-opened',
        targetId: 'event:alarm-stopped',
        relationType: 'causes',
        relationKind: 'causes',
        status: 'accepted',
        sourceKind: 'explicit_cue',
        evidenceClass: 'world_support',
        polarity: 'support',
        modality: 'asserted',
        sourceSemantics: 'world_assertion',
        evidenceIds: [snapshot.entityAnchors[2].id],
        supportIds: [snapshot.entityAnchors[2].id],
        confidence: 0.91,
    }];
    const causalTarget: GraphRebuildEmbeddingTarget = {
        id: 'embed:causal:gate-alarm',
        kind: 'causalFact',
        sourceId: 'causal:gate-alarm',
        noteId: 'note-1',
        label: 'Opening the gate caused the alarm response',
        text: 'gate opened causes alarm response confidence:0.91',
        evidenceIds: [snapshot.entityAnchors[2].id],
        lane: 'causal_fact',
        structuralRole: 'fact',
        admissionStatus: 'admitted',
        workStatus: 'queued',
        parentIds: ['embed:entity:entity-rowan'],
    };
    snapshot.embeddingTargets.push(causalTarget);
    snapshot.counters.causalEdges = 1;
    snapshot.counters.embeddingTargets = snapshot.embeddingTargets.length;
    if (snapshot.embeddingTargetPlan) {
        const plan = snapshot.embeddingTargetPlan as typeof snapshot.embeddingTargetPlan & { targets: GraphRebuildEmbeddingTarget[] };
        plan.targets = snapshot.embeddingTargets;
        plan.candidateCount = snapshot.embeddingTargets.length;
        plan.canonicalCount = snapshot.embeddingTargets.length;
    }
    snapshot.atlasPacket = atlasPacket(snapshot);
    return snapshot;
}

function atlasPacket(snapshot: GraphRebuildSnapshot): NonNullable<GraphRebuildSnapshot['atlasPacket']> {
    const objects = snapshot.embeddingTargets.map((target) => ({
        id: `atlas:${target.id}`,
        family: family(target.kind),
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
    const familyCounts = new Map<string, number>();
    for (const object of objects) familyCounts.set(object.family, (familyCounts.get(object.family) || 0) + 1);
    const familyRows = [...familyCounts.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([packetFamily, count]) => ({ family: packetFamily as ReturnType<typeof family>, count }));
    return {
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
            family: family(target.kind),
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
            families: familyRows,
        },
    };
}

function family(kind: string): 'registry' | 'structure' | 'fact' | 'evidence' | 'temporal' | 'causal' | 'memory' | 'unknown' {
    if (kind === 'entity') return 'registry';
    if (kind === 'note' || kind === 'chunk' || kind === 'episode' || kind === 'structureRoot' || kind === 'documentUnit') return 'structure';
    if (kind === 'anchor' || kind === 'evidenceSpan') return 'evidence';
    if (kind === 'temporalFact') return 'temporal';
    if (kind === 'causalFact') return 'causal';
    if (kind === 'memoryState') return 'memory';
    if (kind === 'graphFact' || kind === 'event') return 'fact';
    return 'unknown';
}

function entity(id: string, label: string, kind: string) {
    return { id, label, kind, aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 };
}

function occurrence(entityId: string, surface: string, sourceStart: number, sourceEnd: number) {
    return {
        id: `occurrence:${entityId}:${sourceStart}`,
        noteId: 'note-1',
        entityId,
        entityLabel: surface,
        entityKind: 'CHARACTER',
        sourceStart,
        sourceEnd,
        surface,
        source: 'dynamic-ner' as const,
        confidence: 0.96,
        excerpt: surface,
        generation: 1,
        createdAt: 1,
        updatedAt: 1,
    };
}

function semanticSummary() {
    const counters = {
        documents: 1, sentences: 2, propositions: 2, arguments: 4, resolvedArguments: 4,
        localCoreferenceRecoveries: 1, negated: 0, modal: 0, conditional: 0,
        attributed: 0, quoted: 0, questions: 0, directives: 0, nAry: 0, reviewable: 0,
    };
    return {
        schemaVersion: 'phoenix-document-semantics/v1' as const,
        source: 'native_rust' as const,
        documents: [{ noteId: 'note-1', textChars: 72, propositions: [], counters }],
        counters,
    };
}
