import { describe, expect, it } from 'vitest';

import type { GraphAtlasPacket } from '../../../../../graph-rebuild/graph-atlas-packet';
import type {
    GraphRebuildEmbeddingTarget,
    GraphRebuildVisualTrace,
} from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { GalaxyRenderableNode } from './graph-galaxy-engine';
import {
    buildGraphPacketEmbeddingTargets,
    buildGraphPacketRowAdapter,
    graphPacketEmbeddingTargetCount,
} from './graph-packet-row-adapter';
import {
    graphTopologyReviewStateForStatus,
    graphTopologyStyleForEmbeddingTarget,
    graphTopologyTraceForEmbeddingTarget,
} from './graph-topology-style-contract';

describe('graph packet row adapter', () => {
    it('feeds Graph and Embed from the same packet rows for review and discourse lanes', () => {
        const rows = buildGraphPacketRowAdapter(packet());
        const graphById = new Map(rows.graphNodes.map((node) => [node.id, node]));
        const embedById = new Map(rows.embeddingTargets.map((target) => [target.id, target]));

        const reviewGraph = graphById.get('review:row-1');
        const reviewEmbed = embedById.get('embed:review:row-1');
        const discourseGraph = graphById.get('discourse:bridge-1');
        const discourseEmbed = embedById.get('embed:discourse:bridge-1');
        const graphRows = new Map(rows.graphNodes.map((node) => [canonicalGraphPacketRow(node).id, canonicalGraphPacketRow(node)]));
        const embedRows = new Map(rows.embeddingTargets.map((target) => [canonicalEmbedPacketRow(target).id, canonicalEmbedPacketRow(target)]));

        expect(rows.kindCounts).toEqual([
            { kind: 'discourse', count: 1 },
            { kind: 'review', count: 1 },
        ]);
        expect(graphPacketEmbeddingTargetCount(packet())).toBe(2);
        expect([...graphRows.keys()].sort()).toEqual([...embedRows.keys()].sort());
        for (const [id, graphRow] of graphRows) {
            expect(embedRows.get(id)).toEqual(graphRow);
        }

        expect(reviewGraph?.metadata).toMatchObject({
            canvasLens: 'facts',
            reviewState: 'proposed',
            atlasFamily: 'review',
            visualTrace: expect.objectContaining({
                source: 'rust_atlas_packet',
                family: 'review',
                packetObjectId: 'review:row-1',
                packetTargetId: 'embed:review:row-1',
            }),
        });
        expect(reviewEmbed).toMatchObject({
            id: 'embed:review:row-1',
            atlasFamily: 'review',
            atlasStatus: 'review',
            admissionStatus: undefined,
            visualTrace: expect.objectContaining({
                source: 'rust_atlas_packet',
                family: 'review',
                packetObjectId: 'review:row-1',
                packetTargetId: 'embed:review:row-1',
            }),
        });

        expect(discourseGraph?.metadata).toMatchObject({
            canvasLens: 'discourse',
            reviewState: 'proposed',
            graphColorKind: 'communication',
            visualTrace: expect.objectContaining({
                source: 'rust_atlas_packet',
                family: 'discourse',
                packetObjectId: 'discourse:bridge-1',
                packetTargetId: 'embed:discourse:bridge-1',
            }),
        });
        expect(discourseEmbed).toMatchObject({
            id: 'embed:discourse:bridge-1',
            atlasFamily: 'discourse',
            visualTrace: expect.objectContaining({
                source: 'rust_atlas_packet',
                family: 'discourse',
                packetObjectId: 'discourse:bridge-1',
                packetTargetId: 'embed:discourse:bridge-1',
            }),
        });
    });

    it('adapts a 6,000-row shared-reference packet below one second without losing exact matches', () => {
        const fixture = sharedReferencePacket(6_000);
        const startedAt = performance.now();

        const rows = buildGraphPacketRowAdapter(fixture);
        const durationMs = performance.now() - startedAt;

        expect(durationMs).toBeLessThan(1_000);
        expect(rows.graphNodes).toHaveLength(6_000);
        expect(rows.embeddingTargets).toHaveLength(6_000);
        expect(rows.embeddingTargets[5_999].visualTrace).toMatchObject({
            packetObjectId: 'fact:5999',
            packetTargetId: 'embed:fact:5999',
        });
    });

    it('projects only embedding rows without constructing the graph surface', () => {
        const fixture = sharedReferencePacket(6_000);
        const expected = buildGraphPacketRowAdapter(fixture).embeddingTargets;
        const startedAt = performance.now();

        const targets = buildGraphPacketEmbeddingTargets(fixture);
        const durationMs = performance.now() - startedAt;

        expect(durationMs).toBeLessThan(500);
        expect(targets).toEqual(expected);
    });
});

function sharedReferencePacket(count: number): GraphAtlasPacket {
    const fixture = packet();
    fixture.objects = Array.from({ length: count }, (_, index) => ({
        id: `fact:${index}`,
        family: 'fact' as const,
        status: 'accepted' as const,
        kind: 'relationshipFact',
        label: `Fact ${index}`,
        noteIds: ['note-shared'],
        chunkIds: ['chunk-shared'],
        anchorIds: [],
        evidenceIds: ['evidence-shared'],
        sourceIds: [`source:${index}`],
        targetIds: [],
    }));
    fixture.manifoldTargets = fixture.objects.map((object, index) => ({
        id: `embed:fact:${index}`,
        objectId: object.id,
        family: 'fact' as const,
        admission: 'admitted' as const,
        status: 'accepted' as const,
        vectorStatus: 'missing' as const,
        coordinateSource: 'deterministic-signature',
        kind: object.kind,
        label: object.label,
        sourceId: object.sourceIds[0],
        noteId: 'note-shared',
        chunkId: 'chunk-shared',
        evidenceIds: ['evidence-shared'],
        parentIds: [],
    }));
    fixture.counters.objects = count;
    fixture.counters.manifoldTargets = count;
    fixture.counters.families = [{ family: 'fact', count }];
    return fixture;
}

function packet(): GraphAtlasPacket {
    return {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: 'snapshot-row-adapter',
        scopeKind: 'global',
        scopeId: 'global',
        builtAt: 1,
        sourceContract: {
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            vectorContract: 'vectors-missing',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        },
        objects: [
            {
                id: 'review:row-1',
                family: 'review',
                status: 'review',
                kind: 'candidate',
                label: 'Proposed relationship',
                noteIds: ['note-1'],
                chunkIds: ['chunk-1'],
                anchorIds: [],
                evidenceIds: ['evidence-1'],
                sourceIds: ['review-row-1'],
                targetIds: [],
            },
            {
                id: 'discourse:bridge-1',
                family: 'discourse',
                status: 'review',
                kind: 'discourseBridge',
                label: 'Echo across chunks',
                noteIds: ['note-1'],
                chunkIds: ['chunk-1'],
                anchorIds: [],
                evidenceIds: ['chunk-1'],
                sourceIds: ['discourse-bridge-1'],
                targetIds: [],
            },
        ],
        manifoldTargets: [
            {
                id: 'embed:review:row-1',
                objectId: 'review:row-1',
                family: 'review',
                admission: 'candidate',
                status: 'review',
                vectorStatus: 'missing',
                coordinateSource: 'packet-row',
                kind: 'candidate',
                label: 'Proposed relationship',
                sourceId: 'review-row-1',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                evidenceIds: ['evidence-1'],
                parentIds: [],
            },
            {
                id: 'embed:discourse:bridge-1',
                objectId: 'discourse:bridge-1',
                family: 'discourse',
                admission: 'candidate',
                status: 'review',
                vectorStatus: 'missing',
                coordinateSource: 'packet-row',
                kind: 'discourseBridge',
                label: 'Echo across chunks',
                sourceId: 'discourse-bridge-1',
                noteId: 'note-1',
                chunkId: 'chunk-1',
                evidenceIds: ['chunk-1'],
                parentIds: [],
            },
        ],
        counters: {
            objects: 2,
            manifoldTargets: 2,
            registryEntities: 0,
            evidenceAnchors: 0,
            modelVectors: 0,
            families: [
                { family: 'review', count: 1 },
                { family: 'discourse', count: 1 },
            ],
        },
    };
}

function canonicalGraphPacketRow(node: GalaxyRenderableNode) {
    const metadata = node.metadata || {};
    const trace = metadata['visualTrace'] as GraphRebuildVisualTrace;
    return {
        id: trace.packetTargetId || trace.packetObjectId || node.id,
        family: String(metadata['atlasFamily'] || trace.family || node.kind),
        status: String(metadata['reviewState'] || ''),
        styleKind: String(metadata['graphColorKind'] || ''),
        trace: canonicalTrace(trace),
    };
}

function canonicalEmbedPacketRow(target: GraphRebuildEmbeddingTarget) {
    const trace = graphTopologyTraceForEmbeddingTarget(target);
    return {
        id: trace.packetTargetId || trace.packetObjectId || target.id,
        family: String(target.atlasFamily || trace.family || target.kind),
        status: graphTopologyReviewStateForStatus(target.atlasStatus || target.admissionStatus),
        styleKind: graphTopologyStyleForEmbeddingTarget(target).colorKind,
        trace: canonicalTrace(trace),
    };
}

function canonicalTrace(trace: GraphRebuildVisualTrace) {
    return {
        source: trace.source,
        sourceId: trace.sourceId,
        family: trace.family,
        packetSnapshotId: trace.packetSnapshotId,
        packetScopeId: trace.packetScopeId,
        packetObjectId: trace.packetObjectId,
        packetTargetId: trace.packetTargetId,
        sourceContract: trace.sourceContract,
        vectorContract: trace.vectorContract,
    };
}
