import { galaxyScenePacketHashBuffer, galaxyScenePacketHashText } from './graph-galaxy-scene-packet-hash';
import {
    GALAXY_SCENE_PACKET_V2_NODE_PALETTE_PAGE,
    GALAXY_SCENE_PACKET_V2_SCHEMA,
    type GalaxyScenePacketV2,
    type GalaxyScenePacketV2PageManifest,
    type VerifiedGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2.model';

interface VerificationState {
    manifestHash: string;
    verifiedPages: Set<string>;
    hashCount: number;
}

const verificationStates = new WeakMap<GalaxyScenePacketV2, VerificationState>();

/**
 * Opens the packet trust boundary. Ownership and manifest authority are checked
 * once; resident and compact-guide pages are hashed once here. Detail pages are
 * hashed only when explicitly opened.
 */
export function verifyGalaxyScenePacketV2(packet: GalaxyScenePacketV2): VerifiedGalaxyScenePacketV2 {
    const existing = verificationStates.get(packet);
    if (existing) return packet as VerifiedGalaxyScenePacketV2;
    assertManifest(packet);
    const state: VerificationState = {
        manifestHash: packet.manifest.contentHash,
        verifiedPages: new Set(),
        hashCount: 0,
    };
    verificationStates.set(packet, state);
    try {
        for (const manifest of packet.manifest.pages) {
            const buffer = packet.pages[manifest.id];
            if (!buffer) {
                if (manifest.loadPolicy === 'on-demand') continue;
                throw new Error(`Galaxy scene packet missing page: ${manifest.id}`);
            }
            assertPageShape(packet, manifest, buffer);
            if (manifest.loadPolicy === 'resident') verifyPageHash(state, manifest, buffer);
        }
    } catch (error) {
        verificationStates.delete(packet);
        throw error;
    }
    return packet as VerifiedGalaxyScenePacketV2;
}

/** Opens and verifies an on-demand page once for this packet object. */
export function openGalaxyScenePacketV2Page(
    packet: VerifiedGalaxyScenePacketV2,
    id: string,
): ArrayBuffer {
    const state = requiredState(packet);
    const manifest = packet.manifest.pages.find((candidate) => candidate.id === id);
    if (!manifest) throw new Error(`Galaxy scene packet manifest is missing page: ${id}`);
    const buffer = packet.pages[id];
    if (!buffer) throw new Error(`Galaxy scene packet missing required page: ${id}`);
    assertPageShape(packet, manifest, buffer);
    if (!state.verifiedPages.has(id)) verifyPageHash(state, manifest, buffer);
    return buffer;
}

/** Verifies one separately loaded detail page without attaching it to the hot packet. */
export function openDetachedGalaxyScenePacketV2Page(
    packet: VerifiedGalaxyScenePacketV2,
    id: string,
    buffer: ArrayBuffer,
): ArrayBuffer {
    const state = requiredState(packet);
    const manifest = packet.manifest.pages.find((candidate) => candidate.id === id);
    if (!manifest) throw new Error(`Galaxy scene packet manifest is missing page: ${id}`);
    if (manifest.loadPolicy !== 'on-demand') {
        throw new Error(`Galaxy scene detached page must be on-demand: ${id}`);
    }
    assertPageShape(packet, manifest, buffer);
    state.hashCount += 1;
    if (galaxyScenePacketHashBuffer(buffer) !== manifest.contentHash) {
        throw new Error(`Galaxy scene page hash drift: ${manifest.id}`);
    }
    return buffer;
}

/** Creates a hot-page view without re-hashing buffers already verified on the source packet. */
export function projectVerifiedGalaxyScenePacketV2(
    source: VerifiedGalaxyScenePacketV2,
    pages: Record<string, ArrayBuffer>,
): VerifiedGalaxyScenePacketV2 {
    const sourceState = requiredState(source);
    const projected: GalaxyScenePacketV2 = { manifest: source.manifest, pages };
    const verifiedPages = new Set<string>();
    for (const [id, buffer] of Object.entries(pages)) {
        if (source.pages[id] !== buffer || !sourceState.verifiedPages.has(id)) {
            throw new Error(`Galaxy scene hot projection requires a verified source page: ${id}`);
        }
        verifiedPages.add(id);
    }
    verificationStates.set(projected, {
        manifestHash: sourceState.manifestHash,
        verifiedPages,
        hashCount: sourceState.hashCount,
    });
    return projected as VerifiedGalaxyScenePacketV2;
}

/** Full fail-closed assertion for persistence and legacy hydration boundaries. */
export function assertGalaxyScenePacketV2(packet: GalaxyScenePacketV2): asserts packet is VerifiedGalaxyScenePacketV2 {
    const verified = verifyGalaxyScenePacketV2(packet);
    for (const manifest of packet.manifest.pages) openGalaxyScenePacketV2Page(verified, manifest.id);
}

export function galaxyScenePacketV2VerificationSnapshot(packet: GalaxyScenePacketV2): {
    branded: boolean;
    verifiedPages: number;
    hashCount: number;
} {
    const state = verificationStates.get(packet);
    return {
        branded: Boolean(state),
        verifiedPages: state?.verifiedPages.size ?? 0,
        hashCount: state?.hashCount ?? 0,
    };
}

function assertManifest(packet: GalaxyScenePacketV2): void {
    if (packet.manifest.schemaVersion !== GALAXY_SCENE_PACKET_V2_SCHEMA) {
        throw new Error(`Unsupported galaxy scene packet: ${packet.manifest.schemaVersion}`);
    }
    if (!packet.manifest.generationId || !packet.manifest.authorityReceipt) {
        throw new Error('Galaxy scene packet requires generation and authority receipt.');
    }
    if (packet.manifest.guideEncoding !== 'binary-guides-v1') {
        throw new Error('GALAXY_SCENE_PACKET_V2_GUIDE_ENCODING_UNSUPPORTED');
    }
    const ids = new Set<string>();
    for (const page of packet.manifest.pages) {
        if (ids.has(page.id)) throw new Error(`Galaxy scene packet has duplicate page: ${page.id}`);
        ids.add(page.id);
        if (page.generationId !== packet.manifest.generationId
            || page.tileId !== packet.manifest.tileId
            || page.lod !== packet.manifest.lod) {
            throw new Error(`Galaxy scene page ownership drift: ${page.id}`);
        }
        if (page.authorityReceipt !== packet.manifest.authorityReceipt) {
            throw new Error(`Galaxy scene page authority drift: ${page.id}`);
        }
    }
    const palettePage = packet.manifest.pages.find(
        (page) => page.id === GALAXY_SCENE_PACKET_V2_NODE_PALETTE_PAGE,
    );
    if (!palettePage
        || palettePage.domain !== 'manifold'
        || palettePage.loadPolicy !== 'resident'
        || palettePage.encoding !== 'u8'
        || palettePage.elementCount !== packet.manifest.nodeCount) {
        throw new Error('GALAXY_SCENE_PACKET_V2_NODE_PALETTE_UNSUPPORTED');
    }
    const contentHash = galaxyScenePacketHashText(
        packet.manifest.pages.map((page) => `${page.id}:${page.contentHash}`).join('|'),
    );
    if (contentHash !== packet.manifest.contentHash) {
        throw new Error('Galaxy scene packet manifest hash drift.');
    }
}

function assertPageShape(
    _packet: GalaxyScenePacketV2,
    manifest: GalaxyScenePacketV2PageManifest,
    buffer: ArrayBuffer,
): void {
    if (buffer.byteLength !== manifest.byteLength) {
        throw new Error(`Galaxy scene page length drift: ${manifest.id}`);
    }
}

function verifyPageHash(
    state: VerificationState,
    manifest: GalaxyScenePacketV2PageManifest,
    buffer: ArrayBuffer,
): void {
    state.hashCount += 1;
    if (galaxyScenePacketHashBuffer(buffer) !== manifest.contentHash) {
        throw new Error(`Galaxy scene page hash drift: ${manifest.id}`);
    }
    state.verifiedPages.add(manifest.id);
}

function requiredState(packet: GalaxyScenePacketV2): VerificationState {
    const state = verificationStates.get(packet);
    if (!state || state.manifestHash !== packet.manifest.contentHash) {
        throw new Error('Galaxy scene packet page access requires VerifiedGalaxyScenePacketV2.');
    }
    return state;
}
