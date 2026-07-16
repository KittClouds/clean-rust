import { describe, expect, it } from 'vitest';

import type { EmbeddingAtlasData } from './graph-embedding-atlas';
import {
    graphProjectionParityApplies,
    graphProjectionParitySlice,
} from './graph-projection-parity';

describe('graph projection parity', () => {
    it('only replaces graph packet rows for Hopf projection parity', () => {
        expect(graphProjectionParityApplies('hopfProjection', 'hopf')).toBe(true);
        expect(graphProjectionParityApplies('lorentzTree', 'lorentz')).toBe(false);
        expect(graphProjectionParityApplies('transitManifold', 'product')).toBe(false);
        expect(graphProjectionParityApplies('siegelFinsler', 'siegel')).toBe(false);
        expect(graphProjectionParityApplies('hybridSpace', 'hybrid')).toBe(false);
    });

    it('uses graph-rebuild projection nodes in graph mode without replacing Hopf metadata', () => {
        const atlas = projectionAtlas();
        const slice = graphProjectionParitySlice(atlas, 'facts', 'all');

        const ids = slice.nodes.map((node) => node.id).sort();
        const fact = slice.nodes.find((node) => node.id === 'embed:graph-fact:rel-1');

        expect(ids).toEqual(['embed:entity:amara', 'embed:graph-fact:rel-1']);
        expect(ids).not.toContain('fact:rel-1');
        expect(fact?.metadata?.['canvasLens']).toBe('facts');
        expect(fact?.metadata?.['reviewState']).toBe('accepted');
        expect(fact?.metadata?.['hopf']).toEqual({
            role: 'fiber',
            baseId: 'embed:entity:amara',
            fiberKind: 'relationship',
            phase: 0.42,
            resonanceSource: 'snapshot-hopf-resonance-space',
        });
    });

    it('filters projection nodes by graph family instead of display kind spelling', () => {
        const slice = graphProjectionParitySlice(projectionAtlas(), 'facts', 'fact');

        expect(slice.nodes.map((node) => node.id)).toEqual(['embed:graph-fact:rel-1']);
        expect(slice.edges).toEqual([]);
    });
});

function projectionAtlas(): EmbeddingAtlasData {
    return {
        sourceLabel: 'Graph Rebuild Snapshot -> Hopf Projection',
        nodes: [
            {
                id: 'embed:entity:amara',
                label: 'Amara',
                kind: 'entity',
                totalMentions: 8,
                atlasX: 0.1,
                atlasY: 0.2,
                atlasZ: 0.3,
                metadata: {
                    graphFamily: 'entity',
                    signalAdmissionStatus: 'admitted',
                    hopf: {
                        role: 'anchor',
                        baseId: 'embed:entity:amara',
                        fiberKind: 'identity',
                        phase: 0,
                        resonanceSource: 'snapshot-hopf-resonance-space',
                    },
                },
            },
            {
                id: 'embed:graph-fact:rel-1',
                label: 'Amara agrees',
                kind: 'graph-fact',
                totalMentions: 3,
                atlasX: 0.2,
                atlasY: 0.1,
                atlasZ: 0.4,
                metadata: {
                    graphFamily: 'fact',
                    signalAdmissionStatus: 'admitted',
                    hopf: {
                        role: 'fiber',
                        baseId: 'embed:entity:amara',
                        fiberKind: 'relationship',
                        phase: 0.42,
                        resonanceSource: 'snapshot-hopf-resonance-space',
                    },
                },
            },
            {
                id: 'embed:chunk:note-1:0',
                label: 'Chunk 1',
                kind: 'chunk',
                totalMentions: 5,
                atlasX: -0.2,
                atlasY: 0.1,
                atlasZ: 0.3,
                metadata: {
                    graphFamily: 'structure',
                    signalAdmissionStatus: 'admitted',
                },
            },
        ],
        edges: [
            {
                id: 'embed:fact-source:rel-1',
                sourceId: 'embed:graph-fact:rel-1',
                targetId: 'embed:entity:amara',
                type: 'approval',
                confidence: 0.91,
                metadata: { graphFamily: 'fact' },
            },
        ],
        searchIndex: [],
        manifold: {
            mode: 'hopf',
            geometryVersion: 'hopf_ico_r5_v1',
            sourceLabel: 'graph rebuild snapshot',
            capabilities: {
                ann: false,
                anchors: true,
                fibers: true,
                phase: true,
                cones: false,
            },
            projectionSource: 'rust_atlas_packet_manifold_targets',
            cells: [],
            charts: [],
            seams: [],
            neighborRings: [],
            coneTraces: [],
            conePrograms: [],
            pathlets: [],
            obstructions: [],
            coneProgramTraces: [],
            anchorProjections: [],
        },
    };
}
