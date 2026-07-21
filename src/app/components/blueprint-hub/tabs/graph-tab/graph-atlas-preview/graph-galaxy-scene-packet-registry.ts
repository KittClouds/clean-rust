import {
    assertGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import type { GalaxyScenePacketV2 } from './graph-galaxy-scene-packet-v2.model';
import type { GalaxySceneSourceMode } from './graph-galaxy-scene-v2';

const MAX_GENERATION_PACKETS = 5;
const MAX_REGISTRY_BYTES = 64 * 1024 * 1024;

interface ResidentPacket {
    packet: GalaxyScenePacketV2;
    bytes: number;
}

const residentPackets = new Map<string, ResidentPacket>();
const packetListeners = new Map<string, Set<(packet: GalaxyScenePacketV2) => void>>();
let residentGeneration = '';
let residentBytes = 0;

export function seedGalaxyScenePacket(packet: GalaxyScenePacketV2): void {
    assertGalaxyScenePacketV2(packet);
    const generation = packet.manifest.generationId;
    if (residentGeneration && residentGeneration !== generation) clearGalaxyScenePacketRegistry();
    residentGeneration = generation;
    const key = packet.manifest.authorityReceipt;
    const previous = residentPackets.get(key);
    if (previous) residentBytes -= previous.bytes;
    const bytes = galaxyScenePacketByteLength(packet);
    residentPackets.delete(key);
    residentPackets.set(key, { packet, bytes });
    residentBytes += bytes;
    trimRegistry(key);
    for (const listener of packetListeners.get(key) || []) listener(packet);
}

export function subscribeGalaxyScenePacket(
    authorityReceipt: string,
    listener: (packet: GalaxyScenePacketV2) => void,
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
): GalaxyScenePacketV2 | null {
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
    residentGeneration = '';
    residentBytes = 0;
}

export function galaxyScenePacketRegistrySnapshot(): { packets: number; bytes: number; generationId: string } {
    return { packets: residentPackets.size, bytes: residentBytes, generationId: residentGeneration };
}

export function galaxyScenePacketByteLength(packet: GalaxyScenePacketV2): number {
    let bytes = 0;
    for (const page of Object.values(packet.pages)) bytes += page.byteLength;
    return bytes;
}

function trimRegistry(currentKey: string): void {
    while (residentPackets.size > 1
        && (residentPackets.size > MAX_GENERATION_PACKETS || residentBytes > MAX_REGISTRY_BYTES)) {
        const oldest = residentPackets.keys().next().value as string | undefined;
        if (!oldest || oldest === currentKey) break;
        const removed = residentPackets.get(oldest);
        residentPackets.delete(oldest);
        residentBytes -= removed?.bytes || 0;
    }
}
