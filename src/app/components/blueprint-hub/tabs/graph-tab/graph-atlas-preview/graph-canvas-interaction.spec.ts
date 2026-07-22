import { describe, expect, it } from 'vitest';

import {
    buildCanvasSearchFocus,
    filterGraphForCanvasLens,
    graphCanvasInspectorRecord,
} from './graph-canvas-interaction';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';

const nodes: GalaxyRenderableNode[] = [
    {
        id: 'entity:amara',
        label: 'Amara',
        kind: 'character',
        metadata: { canvasLens: 'entities', reviewState: 'accepted', sourceSnippet: 'Amara crossed the archive.' },
    },
    {
        id: 'fact:crossed',
        label: 'Crossing event',
        kind: 'event',
        metadata: {
            canvasLens: 'facts',
            reviewState: 'proposed',
            sourceSnippet: 'Amara crossed the archive.',
            detector: 'graph_fact',
        },
    },
];

const edges: GalaxyInputEdge[] = [{
    id: 'fact-edge:1',
    sourceId: 'fact:crossed',
    targetId: 'entity:amara',
    type: 'mentions_entity',
    confidence: 0.82,
    metadata: { canvasLens: 'facts', reviewState: 'proposed' },
}];

describe('graph canvas interaction model', () => {
    it('keeps entity context attached to a fact lens', () => {
        const slice = filterGraphForCanvasLens(nodes, edges, 'facts');

        expect(slice.nodes.map((node) => node.id)).toEqual(['entity:amara', 'fact:crossed']);
        expect(slice.edges.map((edge) => edge.id)).toEqual(['fact-edge:1']);
    });

    it('builds search focus from source snippets and connected nodes', () => {
        const focus = buildCanvasSearchFocus('archive', nodes, edges);

        expect(focus?.primaryNodeIds).toEqual(['entity:amara', 'fact:crossed']);
        expect(focus?.edgeIds).toEqual(['fact-edge:1']);
    });

    it('surfaces edge endpoints and evidence semantics in the inspector', () => {
        const record = graphCanvasInspectorRecord({
            kind: 'edge',
            id: 'fact-edge:1',
            sourceId: 'fact:crossed',
            targetId: 'entity:amara',
        }, nodes, edges);

        expect(record?.title).toBe('Mentions Entity');
        expect(record?.subtitle).toContain('Crossing event -> Amara');
        expect(record?.members.map((member) => member.label)).toEqual(['Crossing event', 'Amara']);
    });
});
