import {
    decodeGalaxyScenePacketV2GuideDetails,
    openGalaxyScenePacketV2Page,
    type GalaxyScenePacketV2GuideDetails,
} from '../graph-galaxy-scene-packet-v2';
import type {
    GalaxyScenePacketV2StringRange,
    VerifiedGalaxyScenePacketV2,
} from '../graph-galaxy-scene-packet-v2.model';
import type { GalaxyRendererV3ResidentPages } from './galaxy-renderer-v3-contract';

const NODE_IDENTITY_KEYS = 'shared/node-identity-keys';
const EDGE_PAIRS = 'shared/edge-pairs';
const POSITIONS_3D = 'manifold/positions-3d';
const RADII = 'manifold/radii';
const NODE_COLORS = 'manifold/node-colors-rgba8';
const NODE_PALETTE_SLOTS = 'manifold/node-palette-slots-u8';
const NODE_FLAGS = 'manifold/node-flags';
const EDGE_COLORS = 'manifold/edge-colors-rgba8';
const EDGE_ALPHA = 'manifold/edge-alpha';
const EDGE_FLAGS = 'manifold/edge-flags';
const STRING_OFFSETS = 'detail/string-offsets';
const STRING_SLAB = 'detail/string-slab';

export interface GalaxyRendererV3PacketResources {
    residentPages: GalaxyRendererV3ResidentPages;
    guideDetails: GalaxyScenePacketV2GuideDetails;
}

export function galaxyRendererV3ResidentPages(packet: VerifiedGalaxyScenePacketV2): GalaxyRendererV3ResidentPages {
    return residentPagesFromVerifiedPacket(packet);
}

export function galaxyRendererV3PacketResources(packet: VerifiedGalaxyScenePacketV2): GalaxyRendererV3PacketResources {
    return {
        residentPages: residentPagesFromVerifiedPacket(packet),
        guideDetails: decodeGalaxyScenePacketV2GuideDetails(packet),
    };
}

function residentPagesFromVerifiedPacket(packet: VerifiedGalaxyScenePacketV2): GalaxyRendererV3ResidentPages {
    return {
        nodeCount: packet.manifest.nodeCount,
        edgeCount: packet.manifest.edgeCount,
        positions3d: new Float32Array(page(packet, POSITIONS_3D)),
        radii: new Float32Array(page(packet, RADII)),
        nodeColorsRgba8: new Uint8Array(page(packet, NODE_COLORS)),
        nodePaletteSlots: new Uint8Array(page(packet, NODE_PALETTE_SLOTS)),
        nodeFlags: new Uint8Array(page(packet, NODE_FLAGS)),
        nodeIdentityKeys: new Uint32Array(page(packet, NODE_IDENTITY_KEYS)),
        edgePairs: new Uint32Array(page(packet, EDGE_PAIRS)),
        edgeColorsRgba8: new Uint8Array(page(packet, EDGE_COLORS)),
        edgeAlpha: new Float32Array(page(packet, EDGE_ALPHA)),
        edgeFlags: new Uint8Array(page(packet, EDGE_FLAGS)),
    };
}

export function galaxyRendererV3NodeIds(packet: VerifiedGalaxyScenePacketV2): string[] {
    return decodeStringRange(packet, packet.manifest.stringRanges.nodeIds);
}

export function galaxyRendererV3Labels(packet: VerifiedGalaxyScenePacketV2, indexes: readonly number[]): Map<number, string> {
    const range = packet.manifest.stringRanges.nodeLabels;
    const requested = new Set(indexes.filter((index) => index >= 0 && index < range.count));
    return decodeSelectedStrings(packet, range, requested);
}

export function galaxyRendererV3NodeDetails(
    packet: VerifiedGalaxyScenePacketV2,
    indexes: readonly number[],
): Map<number, { label: string; kind: string }> {
    const requested = new Set(indexes.filter((index) => index >= 0 && index < packet.manifest.nodeCount));
    const labels = decodeSelectedStrings(packet, packet.manifest.stringRanges.nodeLabels, requested);
    const kinds = decodeSelectedStrings(packet, packet.manifest.stringRanges.nodeKinds, requested);
    const output = new Map<number, { label: string; kind: string }>();
    for (const index of requested) {
        output.set(index, {
            label: labels.get(index) || '',
            kind: kinds.get(index) || 'graph-node',
        });
    }
    return output;
}

export function galaxyRendererV3PacketResidentBytes(packet: VerifiedGalaxyScenePacketV2): number {
    return packet.manifest.pages
        .filter((entry) => entry.loadPolicy === 'resident')
        .reduce((total, entry) => total + entry.byteLength, 0);
}

function decodeStringRange(packet: VerifiedGalaxyScenePacketV2, range: GalaxyScenePacketV2StringRange): string[] {
    const requested = new Set(Array.from({ length: range.count }, (_, index) => index));
    const decoded = decodeSelectedStrings(packet, range, requested);
    return Array.from({ length: range.count }, (_, index) => decoded.get(index) || '');
}

function decodeSelectedStrings(
    packet: VerifiedGalaxyScenePacketV2,
    range: GalaxyScenePacketV2StringRange,
    requested: ReadonlySet<number>,
): Map<number, string> {
    const offsets = new Uint32Array(page(packet, STRING_OFFSETS));
    const bytes = new Uint8Array(page(packet, STRING_SLAB));
    const decoder = new TextDecoder();
    const output = new Map<number, string>();
    for (const localIndex of requested) {
        const index = range.start + localIndex;
        const start = offsets[index];
        const end = offsets[index + 1];
        output.set(localIndex, decoder.decode(bytes.subarray(start, end)));
    }
    return output;
}

function page(packet: VerifiedGalaxyScenePacketV2, id: string): ArrayBuffer {
    return openGalaxyScenePacketV2Page(packet, id);
}
