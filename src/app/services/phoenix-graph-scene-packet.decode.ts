import type { PhoenixGraphScenePacket } from './phoenix-graph-scene-packet.model';

const LITTLE_ENDIAN = true;

export interface PhoenixGraphScenePacketDecodedBuffers {
    positions3d: Float32Array;
    positions2d: Float32Array;
    radii: Float32Array;
    colors: Float32Array;
    edgePairs: Uint32Array;
    edgeColors: Float32Array;
    edgeAlpha: Float32Array;
    edgeKinds: Uint8Array;
    hierarchyShellRadii?: Float32Array;
    hierarchyShellRanks?: Uint8Array;
}

export function decodeGraphScenePacketBuffers(packet: PhoenixGraphScenePacket): PhoenixGraphScenePacketDecodedBuffers {
    const nodeCount = packet.ids.length;
    const edgeCount = packet.edgeIds.length;
    return {
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

export function graphScenePacketEncodedChars(packet: PhoenixGraphScenePacket): number {
    return packet.positions3d.length
        + packet.positions2d.length
        + packet.radii.length
        + packet.colors.length
        + packet.edgePairs.length
        + packet.edgeColors.length
        + packet.edgeAlpha.length
        + packet.edgeKinds.length
        + (packet.hierarchyShellRadii?.length || 0)
        + (packet.hierarchyShellRanks?.length || 0);
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
