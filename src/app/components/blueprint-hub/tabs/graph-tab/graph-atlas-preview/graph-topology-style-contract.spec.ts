import { describe, expect, it } from 'vitest';

import type { GraphAtlasPacket } from '../../../../../graph-rebuild/graph-atlas-packet';
import type { GraphRebuildEmbeddingTarget } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import {
    DEFAULT_ENTITY_COLORS,
    DEFAULT_GRAPH_NODE_COLORS,
    normalizeEntityKind,
    normalizeGraphNodeColorKind,
    type GraphNodeColorKind,
} from '../../../../../lib/store/entityColorStore';
import type { EntityKind } from '../../../../../lib/Scanner/types';
import {
    graphTopologyLaneForFamily,
    graphTopologyReviewStateForAdmission,
    graphTopologyReviewStateForStatus,
    graphTopologyStyleForEmbeddingTarget,
    graphTopologyStyleForPacketRow,
    graphTopologyTraceForAtlasObject,
    graphTopologyTraceForEmbeddingTarget,
} from './graph-topology-style-contract';

const STYLE_LAB_ENTITY_KIND_FIXTURE = Object.keys(DEFAULT_ENTITY_COLORS) as EntityKind[];
const STYLE_LAB_GRAPH_NODE_KIND_FIXTURE = Object.keys(DEFAULT_GRAPH_NODE_COLORS) as GraphNodeColorKind[];

describe('graph topology style contract', () => {
    it('maps packet families and states into graph lanes', () => {
        expect(graphTopologyLaneForFamily('registry')).toBe('entities');
        expect(graphTopologyLaneForFamily('entity')).toBe('entities');
        expect(graphTopologyLaneForFamily('structure')).toBe('structure');
        expect(graphTopologyLaneForFamily('evidence')).toBe('structure');
        expect(graphTopologyLaneForFamily('discourse')).toBe('discourse');
        expect(graphTopologyLaneForFamily('review')).toBe('facts');

        expect(graphTopologyReviewStateForStatus('compiledToGraph')).toBe('accepted');
        expect(graphTopologyReviewStateForStatus('promoted_to_anchor')).toBe('accepted');
        expect(graphTopologyReviewStateForStatus('review')).toBe('proposed');
        expect(graphTopologyReviewStateForStatus('muted')).toBe('muted');
        expect(graphTopologyReviewStateForAdmission('admitted')).toBe('accepted');
        expect(graphTopologyReviewStateForAdmission('candidate')).toBe('proposed');
    });

    it('normalizes packet rows into Style Lab graph kinds', () => {
        expect(graphTopologyStyleForPacketRow({
            family: 'discourse',
            kind: 'graphFact',
            label: 'Bridge discussion',
        }).colorKind).toBe('communication');
        expect(graphTopologyStyleForPacketRow({
            family: 'review',
            kind: 'candidate',
            label: 'Needs review',
        }).colorKind).toBe('rankStatus');
        expect(graphTopologyStyleForPacketRow({
            family: 'memory',
            kind: 'memoryState',
            label: 'service rank',
        }).colorKind).toBe('serviceContext');
        expect(graphTopologyStyleForPacketRow({
            family: 'fact',
            kind: 'co_occurs_with',
            label: 'Amara co-occurs',
        }).colorKind).toBe('cooccurrence');
    });

    it('normalizes embedding targets through the same Style Lab contract', () => {
        const serviceState = embeddingTarget({
            kind: 'memoryState',
            label: 'service rank',
            text: 'service context for Kai',
            sourceId: 'memory:service:kai',
        });
        const explicitDecision = embeddingTarget({
            kind: 'memoryState',
            styleKey: 'decision_state',
            label: 'plain state',
            text: '',
        });
        const relationship = embeddingTarget({
            kind: 'graphFact',
            label: 'Rift said yes',
            text: 'communication between entities',
        });

        expect(graphTopologyStyleForEmbeddingTarget(serviceState).colorKind).toBe('serviceContext');
        expect(graphTopologyStyleForEmbeddingTarget(explicitDecision).colorKind).toBe('decisionState');
        expect(graphTopologyStyleForEmbeddingTarget(relationship).colorKind).toBe('communication');
    });

    it('covers every Style Lab entity kind and graph node kind', () => {
        expect(new Set(STYLE_LAB_ENTITY_KIND_FIXTURE)).toEqual(new Set(Object.keys(DEFAULT_ENTITY_COLORS)));
        expect(new Set(STYLE_LAB_GRAPH_NODE_KIND_FIXTURE)).toEqual(new Set(Object.keys(DEFAULT_GRAPH_NODE_COLORS)));

        for (const entityKind of STYLE_LAB_ENTITY_KIND_FIXTURE) {
            const expected = normalizeEntityKind(entityKind);
            expect(expected).toBeTruthy();
            expect(graphTopologyStyleForPacketRow({
                family: 'entity',
                kind: entityKind,
                label: entityKind,
                styleKey: entityKind,
            }).colorKind).toBe(expected);
            expect(graphTopologyStyleForEmbeddingTarget(embeddingTarget({
                kind: 'entity',
                entityKind,
                label: entityKind,
            })).colorKind).toBe(expected);
        }

        for (const graphKind of STYLE_LAB_GRAPH_NODE_KIND_FIXTURE) {
            const expected = normalizeGraphNodeColorKind(graphKind);
            expect(expected).toBe(graphKind);
            expect(graphTopologyStyleForPacketRow({
                family: graphKind === 'document' || graphKind === 'chunk' || graphKind === 'anchor' ? 'structure' : 'fact',
                kind: graphKind,
                label: graphKind,
                styleKey: graphKind,
                stateContextKind: graphKind,
            }).colorKind).toBe(graphKind);
            expect(graphTopologyStyleForEmbeddingTarget(embeddingTarget({
                kind: 'graphFact',
                styleKey: graphKind,
                stateContextKind: graphKind,
                label: graphKind,
            })).colorKind).toBe(graphKind);
        }
    });

    it('emits trace records with packet/source/family identity', () => {
        const packet = atlasPacket();
        const object = packet.objects[0];
        const trace = graphTopologyTraceForAtlasObject(packet, object, undefined);
        const fallback = graphTopologyTraceForEmbeddingTarget(embeddingTarget({
            id: 'embed:fact:1',
            sourceId: 'fact:1',
            atlasFamily: 'fact',
        }));

        expect(trace).toMatchObject({
            source: 'rust_atlas_packet',
            sourceId: 'discourse-bridge:1',
            family: 'discourse',
            packetSnapshotId: 'snapshot-1',
            packetScopeId: 'global',
            packetObjectId: 'discourse:bridge:1',
        });
        expect(fallback).toMatchObject({
            source: 'graph_rebuild_embedding_target',
            sourceId: 'fact:1',
            family: 'fact',
            packetTargetId: 'embed:fact:1',
        });
    });
});

function embeddingTarget(overrides: Partial<GraphRebuildEmbeddingTarget>): GraphRebuildEmbeddingTarget {
    return {
        id: overrides.id || 'embed:target',
        kind: overrides.kind || 'graphFact',
        sourceId: overrides.sourceId || 'source:target',
        label: overrides.label || 'target',
        text: overrides.text || '',
        evidenceIds: overrides.evidenceIds || [],
        ...overrides,
    } as GraphRebuildEmbeddingTarget;
}

function atlasPacket(): GraphAtlasPacket {
    return {
        schemaVersion: 'phoenix-atlas-packet/v1',
        snapshotId: 'snapshot-1',
        scopeKind: 'global',
        scopeId: 'global',
        builtAt: 1,
        sourceContract: {
            authority: 'rust-atlas-packet',
            identityAuthority: 'registry-entities-and-accepted-anchors',
            vectorContract: 'vectors-missing',
            tsGraphBuilderRole: 'native-atlas-packet-authority',
        },
        objects: [{
            id: 'discourse:bridge:1',
            family: 'discourse',
            status: 'review',
            kind: 'discourseBridge',
            label: 'Discourse bridge',
            noteIds: ['note-1'],
            chunkIds: ['chunk-1'],
            anchorIds: [],
            evidenceIds: ['target-1'],
            sourceIds: ['discourse-bridge:1'],
            targetIds: [],
        }],
        manifoldTargets: [],
        counters: {
            objects: 1,
            manifoldTargets: 0,
            registryEntities: 0,
            evidenceAnchors: 0,
            modelVectors: 0,
            families: [{ family: 'discourse', count: 1 }],
        },
    };
}
