import {
    projectVerifiedGalaxyScenePacketV2,
    verifyGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import type {
    GalaxyScenePacketV2,
    VerifiedGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2.model';
import type { GalaxySceneSourceMode } from './graph-galaxy-scene-v2';

const MAX_GENERATION_PACKETS = 5;
export const MAX_GALAXY_SCENE_HOT_REGISTRY_BYTES = 64 * 1024 * 1024;

interface ResidentPacket {
    packet: VerifiedGalaxyScenePacketV2;
}

const residentPackets = new Map<string, ResidentPacket>();
const packetListeners = new Map<string, Set<(packet: VerifiedGalaxyScenePacketV2) => void>>();
const sharedPages = new Map<string, ArrayBuffer>();
let residentGeneration = '';
let residentBytes = 0;

/**
 * Opens the packet trust boundary and retains only hot renderer/guide pages.
 * On-demand semantic pages remain owned by persistence or the producing task.
 */
export function seedGalaxyScenePacket(packet: GalaxyScenePacketV2): VerifiedGalaxyScenePacketV2 {
    const generation = packet.manifest.generationId;
    if (residentGeneration && residentGeneration !== generation) clearGalaxyScenePacketRegistry();
    residentGeneration = generation;
    deduplicateSharedPages(packet);
    const verified = verifyGalaxyScenePacketV2(packet);
    const hotPages = Object.fromEntries(packet.manifest.pages
        .filter((page) => page.loadPolicy === 'resident')
        .map((page) => [page.id, packet.pages[page.id]]));
    const hotPacket = projectVerifiedGalaxyScenePacketV2(verified, hotPages);
    const hotBytes = uniquePageBytes([hotPacket]);
    assertGalaxySceneHotPacketBudget(hotBytes);
    const key = packet.manifest.authorityReceipt;
    const candidate = new Map(residentPackets);
    candidate.delete(key);
    candidate.set(key, { packet: hotPacket });
    while (candidate.size > MAX_GENERATION_PACKETS) candidate.delete(candidate.keys().next().value!);
    const candidateBytes = uniquePageBytes(Array.from(candidate.values(), (value) => value.packet));
    if (candidateBytes > MAX_GALAXY_SCENE_HOT_REGISTRY_BYTES) {
        throw new Error(`GALAXY_SCENE_HOT_REGISTRY_BUDGET_EXCEEDED:${candidateBytes}`);
    }
    residentPackets.clear();
    for (const entry of candidate) residentPackets.set(...entry);
    residentBytes = candidateBytes;
    rebuildSharedPagePool();
    for (const listener of packetListeners.get(key) || []) listener(hotPacket);
    return hotPacket;
}

export function subscribeGalaxyScenePacket(
    authorityReceipt: string,
    listener: (packet: VerifiedGalaxyScenePacketV2) => void,
): () => void {
    const listeners = packetListeners.get(authorityReceipt) || new Set();
    listeners.add(listener);
    packetListeners.set(authorityReceipt, listeners);
    return () => {
        listeners.delete(listener);
        if (!listeners.size) packetListeners.delete(authorityReceipt);
    };
}

export function cachedGalaxyScenePacket(
    authorityReceipt: string,
    generationId: string,
    sourceMode: GalaxySceneSourceMode,
): VerifiedGalaxyScenePacketV2 | null {
    const resident = residentPackets.get(authorityReceipt);
    if (!resident) return null;
    const manifest = resident.packet.manifest;
    if (manifest.generationId !== generationId || manifest.sourceMode !== sourceMode) return null;
    residentPackets.delete(authorityReceipt);
    residentPackets.set(authorityReceipt, resident);
    return resident.packet;
}

export function clearGalaxyScenePacketRegistry(): void {
    residentPackets.clear();
    sharedPages.clear();
    residentGeneration = '';
    residentBytes = 0;
}

export function galaxyScenePacketRegistrySnapshot(): {
    packets: number;
    bytes: number;
    generationId: string;
    sharedBuffers: number;
} {
    return {
        packets: residentPackets.size,
        bytes: residentBytes,
        generationId: residentGeneration,
        sharedBuffers: sharedPages.size,
    };
}

export function galaxyScenePacketByteLength(packet: GalaxyScenePacketV2): number {
    return uniquePageBytes([packet]);
}

export function assertGalaxySceneHotPacketBudget(bytes: number): void {
    if (bytes > MAX_GALAXY_SCENE_HOT_REGISTRY_BYTES) {
        throw new Error(`GALAXY_SCENE_HOT_PACKET_OVERSIZED:${bytes}`);
    }
}

function deduplicateSharedPages(packet: GalaxyScenePacketV2): void {
    for (const page of packet.manifest.pages) {
        if (page.domain !== 'shared' || page.loadPolicy !== 'resident') continue;
        const key = sharedPageKey(page.id, page.contentHash);
        const retained = sharedPages.get(key);
        if (retained) packet.pages[page.id] = retained;
    }
}

function rebuildSharedPagePool(): void {
    sharedPages.clear();
    for (const { packet } of residentPackets.values()) {
        for (const page of packet.manifest.pages) {
            if (page.domain !== 'shared' || page.loadPolicy !== 'resident') continue;
            const buffer = packet.pages[page.id];
            if (buffer) sharedPages.set(sharedPageKey(page.id, page.contentHash), buffer);
        }
    }
}

function uniquePageBytes(packets: readonly GalaxyScenePacketV2[]): number {
    const buffers = new Set<ArrayBuffer>();
    for (const packet of packets) {
        for (const buffer of Object.values(packet.pages)) buffers.add(buffer);
    }
    let bytes = 0;
    for (const buffer of buffers) bytes += buffer.byteLength;
    return bytes;
}

function sharedPageKey(id: string, hash: string): string {
    return `${id}\u0000${hash}`;
}
