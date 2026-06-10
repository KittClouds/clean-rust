import { describe, expect, it } from 'vitest';

import type { PhoenixGraphScenePacket } from '../../../../../services/phoenix-graph-scene-packet.model';
import { graphScenePacketToV2 } from './graph-native-scene-packet';

describe('graphScenePacketToV2', () => {
    it('decodes native little-endian scene buffers into GalaxySceneV2 arrays', () => {
        const packet: PhoenixGraphScenePacket = {
            version: 'graph-scene-packet/v1',
            source: 'inline',
            sourceLabel: 'Native packet smoke',
            manifold: 'siegel',
            layoutMode: 'siegelFinsler',
            sourceMode: 'embeddings',
            counters: {
                inputNodes: 2,
                inputEdges: 1,
                renderedNodes: 2,
                renderedEdges: 1,
                droppedEdges: 0,
                bufferBytes: 0,
            },
            ids: ['doc:1', 'entity:kai'],
            labels: ['Doc 1', 'Kai'],
            kinds: ['document', 'entity'],
            groupIds: ['document', 'entity'],
            positions3d: encodeF32([1, 2, 3, 4, 5, 6]),
            positions2d: encodeF32([1, 2, 0, 4, 5, 0]),
            radii: encodeF32([0.8, 0.5]),
            colors: encodeF32([0.1, 0.2, 0.3, 0.7, 0.8, 0.9]),
            edgeIds: ['e:1'],
            edgePairs: encodeU32([0, 1]),
            edgeColors: encodeF32([0.1, 0.2, 0.3, 0.7, 0.8, 0.9]),
            edgeAlpha: encodeF32([0.45]),
            edgeKinds: encodeU8([2]),
            hierarchyShellRadii: encodeF32([4, 1]),
            hierarchyShellRanks: encodeU8([1, 4]),
            hierarchyHints: [
                {
                    nodeId: 'entity:kai',
                    primaryTreeId: 'identity:kai',
                    capId: 'identity:kai',
                    parentNodeId: 'embed:structure-root:note-1:identity',
                    shellRadius: 1.42,
                    hierarchyLevel: 3,
                    role: 'canonicalEntity',
                    confidence: 0.94,
                    memberships: [
                        {
                            treeId: 'identity:kai',
                            nodeId: 'entity:kai',
                            parentNodeId: 'embed:structure-root:note-1:identity',
                            depth: 3,
                            localRank: 1,
                            pathKey: 'identity:kai/embed:structure-root:note-1:identity/entity:kai',
                            role: 'canonicalEntity',
                            confidence: 0.94,
                            primary: true,
                        },
                    ],
                },
            ],
        };

        const scene = graphScenePacketToV2(packet);

        expect(scene.ids).toEqual(['doc:1', 'entity:kai']);
        expect(Array.from(scene.positions3d)).toEqual([1, 2, 3, 4, 5, 6]);
        expect(Array.from(scene.edgePairs)).toEqual([0, 1]);
        expect(Array.from(scene.edgeKinds)).toEqual([2]);
        expect(Array.from(scene.hierarchyShellRanks ?? [])).toEqual([1, 4]);
        expect(scene.hierarchyHints?.[0]).toMatchObject({
            nodeId: 'entity:kai',
            capId: 'identity:kai',
            parentNodeId: 'embed:structure-root:note-1:identity',
        });
    });
});

function encodeF32(values: number[]): string {
    const bytes = new Uint8Array(values.length * 4);
    const view = new DataView(bytes.buffer);
    values.forEach((value, index) => view.setFloat32(index * 4, value, true));
    return encodeBytes(bytes);
}

function encodeU32(values: number[]): string {
    const bytes = new Uint8Array(values.length * 4);
    const view = new DataView(bytes.buffer);
    values.forEach((value, index) => view.setUint32(index * 4, value, true));
    return encodeBytes(bytes);
}

function encodeU8(values: number[]): string {
    return encodeBytes(Uint8Array.from(values));
}

function encodeBytes(bytes: Uint8Array): string {
    let binary = '';
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
}
