import type { PhoenixGraphScenePacket } from '../../../../../services/phoenix-graph-scene-packet.model';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

const LITTLE_ENDIAN = true;

export function graphScenePacketToV2(packet: PhoenixGraphScenePacket): GalaxySceneV2 {
    const nodeCount = packet.ids.length;
    const edgeCount = packet.edgeIds.length;
    return {
        sourceMode: packet.sourceMode,
        layoutMode: packet.layoutMode,
        ids: packet.ids.slice(),
        labels: packet.labels.slice(),
        kinds: packet.kinds.slice(),
        groupIds: packet.groupIds.slice(),
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: decodeF32(packet.positions3d, nodeCount * 3),
        positions2d: decodeF32(packet.positions2d, nodeCount * 3),
        radii: decodeF32(packet.radii, nodeCount),
        colors: decodeF32(packet.colors, nodeCount * 3),
        edgePairs: decodeU32(packet.edgePairs, edgeCount * 2),
        edgeColors: decodeF32(packet.edgeColors, edgeCount * 6),
        edgeAlpha: decodeF32(packet.edgeAlpha, edgeCount),
        edgeKinds: decodeU8(packet.edgeKinds, edgeCount),
        hierarchyShellRadii: packet.hierarchyShellRadii ? decodeF32(packet.hierarchyShellRadii, nodeCount) : undefined,
        hierarchyShellRanks: packet.hierarchyShellRanks ? decodeU8(packet.hierarchyShellRanks, nodeCount) : undefined,
    };
}

function decodeF32(encoded: string, expected: number): Float32Array {
    const bytes = decodeBytes(encoded);
    const count = Math.min(expected, Math.floor(bytes.byteLength / 4));
    const out = new Float32Array(expected);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let index = 0; index < count; index++) {
        out[index] = view.getFloat32(index * 4, LITTLE_ENDIAN);
    }
    return out;
}

function decodeU32(encoded: string, expected: number): Uint32Array {
    const bytes = decodeBytes(encoded);
    const count = Math.min(expected, Math.floor(bytes.byteLength / 4));
    const out = new Uint32Array(expected);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let index = 0; index < count; index++) {
        out[index] = view.getUint32(index * 4, LITTLE_ENDIAN);
    }
    return out;
}

function decodeU8(encoded: string, expected: number): Uint8Array {
    const bytes = decodeBytes(encoded);
    const out = new Uint8Array(expected);
    out.set(bytes.subarray(0, expected));
    return out;
}

function decodeBytes(encoded: string): Uint8Array {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index++) {
        bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
}
