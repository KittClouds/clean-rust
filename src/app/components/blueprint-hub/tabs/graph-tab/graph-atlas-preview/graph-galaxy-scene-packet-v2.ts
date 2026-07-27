import {
    attachGalaxySceneRuntimeIndex,
    type GalaxySceneV2,
} from './graph-galaxy-scene-v2';
import {
    decodeGalaxySceneGuidePages,
    GALAXY_GUIDE_PAGE_IDS,
    packGalaxySceneGuidePages,
    type GalaxyScenePacketV2GuideDetails,
} from './graph-galaxy-scene-guide-pages';
import { galaxyScenePacketHashBuffer, galaxyScenePacketHashText } from './graph-galaxy-scene-packet-hash';
import {
    assertGalaxyScenePacketV2,
    openGalaxyScenePacketV2Page,
} from './graph-galaxy-scene-packet-verification';
import {
    GALAXY_SCENE_PACKET_V2_SCHEMA,
    GALAXY_SCENE_PACKET_V2_NODE_PALETTE_PAGE,
    type GalaxyScenePacketV2,
    type GalaxyScenePacketV2CollisionPages,
    type GalaxyScenePacketV2Context,
    type GalaxyScenePacketV2Encoding,
    type GalaxyScenePacketV2LoadPolicy,
    type GalaxyScenePacketV2Manifest,
    type GalaxyScenePacketV2PageDomain,
    type GalaxyScenePacketV2PageManifest,
    type GalaxyScenePacketV2StringRange,
    type VerifiedGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2.model';

export {
    assertGalaxyScenePacketV2,
    galaxyScenePacketV2VerificationSnapshot,
    openDetachedGalaxyScenePacketV2Page,
    openGalaxyScenePacketV2Page,
    projectVerifiedGalaxyScenePacketV2,
    verifyGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-verification';
export type { GalaxyScenePacketV2GuideDetails } from './graph-galaxy-scene-guide-pages';

const NODE_IDENTITY_KEYS = 'shared/node-identity-keys';
const EDGE_IDENTITY_KEYS = 'shared/edge-identity-keys';
const EDGE_PAIRS = 'shared/edge-pairs';
const NODE_COLLISION_RECORDS = 'shared/node-collision-records';
const NODE_COLLISION_MEMBERS = 'shared/node-collision-members';
const EDGE_COLLISION_RECORDS = 'shared/edge-collision-records';
const EDGE_COLLISION_MEMBERS = 'shared/edge-collision-members';
const POSITIONS_3D = 'manifold/positions-3d';
const RADII = 'manifold/radii';
const NODE_COLORS = 'manifold/node-colors-rgba8';
const NODE_PALETTE_SLOTS = GALAXY_SCENE_PACKET_V2_NODE_PALETTE_PAGE;
const NODE_FLAGS = 'manifold/node-flags';
const EDGE_COLORS = 'manifold/edge-colors-rgba8';
const EDGE_ALPHA = 'manifold/edge-alpha';
const EDGE_FLAGS = 'manifold/edge-flags';
const HYBRID_SHELL_POSITIONS = 'manifold/hybrid-shell-positions';
const HYBRID_COMMITMENT_POSITIONS = 'manifold/hybrid-commitment-positions';
const HIERARCHY_SHELL_RADII = 'manifold/hierarchy-shell-radii';
const HIERARCHY_SHELL_RANKS = 'manifold/hierarchy-shell-ranks';
const STRING_OFFSETS = 'detail/string-offsets';
const STRING_SLAB = 'detail/string-slab';
const GROUPS = 'detail/groups';
const TRANSIT_PLAN = 'detail/transit-plan';
const RELATION_CONTROLS = 'detail/relation-controls';
const BUSEMANN_HOROSPHERES = 'detail/busemann-horospheres';
const HYBRID_RECEIPTS = 'detail/hybrid-receipts';
const HIERARCHY_HINTS = 'detail/hierarchy-hints';
export const GALAXY_SCENE_PACKET_LITTLE_ENDIAN_RUNTIME =
    new Uint8Array(new Uint32Array([0x01020304]).buffer)[0] === 0x04;

interface StringSlab {
    offsets: Uint32Array;
    bytes: Uint8Array;
    ranges: GalaxyScenePacketV2Manifest['stringRanges'];
}

export class GalaxyScenePacketV2SharedPagePool {
    private generationId = '';
    private readonly pages = new Map<string, { contentHash: string; buffer: ArrayBuffer }>();

    reuse(packet: GalaxyScenePacketV2): GalaxyScenePacketV2 {
        if (this.generationId !== packet.manifest.generationId) {
            this.generationId = packet.manifest.generationId;
            this.pages.clear();
        }
        for (const page of packet.manifest.pages) {
            if (page.domain !== 'shared') continue;
            const retained = this.pages.get(page.id);
            if (retained?.contentHash === page.contentHash) {
                packet.pages[page.id] = retained.buffer;
            } else {
                this.pages.set(page.id, { contentHash: page.contentHash, buffer: requiredPage(packet.pages, page.id) });
            }
        }
        return packet;
    }

    clear(): void {
        this.generationId = '';
        this.pages.clear();
    }
}

export function packGalaxyScenePacketV2(
    scene: GalaxySceneV2,
    context: GalaxyScenePacketV2Context,
): GalaxyScenePacketV2 {
    assertGalaxyScenePacketLittleEndianRuntime();
    const pages: Record<string, ArrayBuffer> = {};
    const pageManifests: GalaxyScenePacketV2PageManifest[] = [];
    const pageContext = {
        generationId: context.generationId,
        tileId: context.tileId || 'full',
        lod: context.lod ?? 0,
        authorityReceipt: context.authorityReceipt,
    };
    const nodeIdentityKeys = galaxySceneIdentityKeys(scene.ids);
    const edgeIdentityKeys = galaxySceneIdentityKeys(scene.edgeIds);
    const nodeCollisions = galaxySceneIdentityCollisionPages(scene.ids, nodeIdentityKeys);
    const edgeCollisions = galaxySceneIdentityCollisionPages(scene.edgeIds, edgeIdentityKeys);
    const strings = buildStringSlab([
        ['nodeIds', scene.ids],
        ['nodeLabels', scene.labels],
        ['nodeKinds', scene.kinds],
        ['nodeGroupIds', scene.groupIds],
        ['nodeHopfBaseIds', scene.hopfBaseIds ?? emptyStrings(scene.ids.length)],
        ['nodeHopfCellIds', scene.hopfCellIds ?? scene.hopfBaseIds ?? emptyStrings(scene.ids.length)],
        ['nodeHopfFiberIds', scene.hopfFiberIds ?? scene.hopfBaseIds ?? emptyStrings(scene.ids.length)],
        ['nodeHopfLaneIds', scene.hopfLaneIds ?? scene.hopfFiberIds ?? scene.hopfBaseIds ?? emptyStrings(scene.ids.length)],
        ['edgeIds', scene.edgeIds],
        ['edgeTypes', scene.edgeTypes],
    ]);

    addPage(pages, pageManifests, NODE_IDENTITY_KEYS, 'shared', 'resident', 'u32-le', nodeIdentityKeys, pageContext);
    addPage(pages, pageManifests, EDGE_IDENTITY_KEYS, 'shared', 'resident', 'u32-le', edgeIdentityKeys, pageContext);
    addPage(pages, pageManifests, EDGE_PAIRS, 'shared', 'resident', 'u32-le', scene.edgePairs, pageContext);
    addCollisionPages(pages, pageManifests, NODE_COLLISION_RECORDS, NODE_COLLISION_MEMBERS, nodeCollisions, pageContext);
    addCollisionPages(pages, pageManifests, EDGE_COLLISION_RECORDS, EDGE_COLLISION_MEMBERS, edgeCollisions, pageContext);
    addPage(pages, pageManifests, POSITIONS_3D, 'manifold', 'resident', 'f32-le', scene.positions3d, pageContext);
    addPage(pages, pageManifests, RADII, 'manifold', 'resident', 'f32-le', scene.radii, pageContext);
    addPage(pages, pageManifests, NODE_COLORS, 'manifold', 'resident', 'rgba8', packRgbAsRgba8(scene.colors), pageContext);
    addPage(pages, pageManifests, NODE_PALETTE_SLOTS, 'manifold', 'resident', 'u8', scene.paletteSlots, pageContext);
    addPage(pages, pageManifests, NODE_FLAGS, 'manifold', 'resident', 'u8', scene.hopfRoles ?? new Uint8Array(scene.ids.length), pageContext);
    addPage(pages, pageManifests, EDGE_COLORS, 'manifold', 'resident', 'rgba8', packRgbAsRgba8(scene.edgeColors), pageContext);
    addPage(pages, pageManifests, EDGE_ALPHA, 'manifold', 'resident', 'f32-le', scene.edgeAlpha, pageContext);
    addPage(pages, pageManifests, EDGE_FLAGS, 'manifold', 'resident', 'u8', scene.edgeKinds, pageContext);
    addOptionalDetailPage(pages, pageManifests, HYBRID_SHELL_POSITIONS, 'f32-le', scene.hybridShellPositions, pageContext);
    addOptionalDetailPage(pages, pageManifests, HYBRID_COMMITMENT_POSITIONS, 'f32-le', scene.hybridCommitmentPositions, pageContext);
    addOptionalDetailPage(pages, pageManifests, HIERARCHY_SHELL_RADII, 'f32-le', scene.hierarchyShellRadii, pageContext);
    addOptionalDetailPage(pages, pageManifests, HIERARCHY_SHELL_RANKS, 'u8', scene.hierarchyShellRanks, pageContext);
    addPage(pages, pageManifests, STRING_OFFSETS, 'shared', 'resident', 'u32-le', strings.offsets, pageContext);
    addPage(pages, pageManifests, STRING_SLAB, 'shared', 'resident', 'utf8', strings.bytes, pageContext);
    const guidePages = packGalaxySceneGuidePages(scene);
    for (const [id, view] of Object.entries(guidePages)) {
        addPage(pages, pageManifests, id, 'guide', 'resident', guideEncoding(id), view, pageContext);
    }
    addJsonPage(pages, pageManifests, GROUPS, scene.groups, pageContext);
    addOptionalJsonPage(pages, pageManifests, TRANSIT_PLAN, scene.transitPlan, pageContext);
    addOptionalJsonPage(pages, pageManifests, RELATION_CONTROLS, scene.relationControls, pageContext);
    addOptionalJsonPage(pages, pageManifests, BUSEMANN_HOROSPHERES, scene.busemannHorospheres, pageContext);
    addOptionalJsonPage(pages, pageManifests, HYBRID_RECEIPTS, scene.hybridReceipts, pageContext);
    addOptionalJsonPage(pages, pageManifests, HIERARCHY_HINTS, scene.hierarchyHints, pageContext);

    const contentHash = galaxyScenePacketHashText(pageManifests.map((page) => `${page.id}:${page.contentHash}`).join('|'));
    return {
        manifest: {
            schemaVersion: GALAXY_SCENE_PACKET_V2_SCHEMA,
            ...pageContext,
            layoutMode: scene.layoutMode,
            sourceMode: scene.sourceMode,
            identityEncoding: 'fnv1a32-dual-u64',
            positionEncoding: 'float32-tile-local',
            guideEncoding: 'binary-guides-v1',
            tileOrigin: [0, 0, 0],
            nodeCount: scene.ids.length,
            edgeCount: scene.edgePairs.length / 2,
            nodeCollisionCount: nodeCollisions.collisionCount,
            edgeCollisionCount: edgeCollisions.collisionCount,
            stringRanges: strings.ranges,
            pages: pageManifests,
            contentHash,
        },
        pages,
    };
}

export function unpackGalaxyScenePacketV2(packet: GalaxyScenePacketV2): GalaxySceneV2 {
    assertGalaxyScenePacketLittleEndianRuntime();
    assertGalaxyScenePacketV2(packet);
    const { manifest, pages } = packet;
    const strings = decodeStringSlab(
        new Uint32Array(openGalaxyScenePacketV2Page(packet, STRING_OFFSETS)),
        new Uint8Array(openGalaxyScenePacketV2Page(packet, STRING_SLAB)),
    );
    const guides = decodeGalaxySceneGuidePages((id) => openGalaxyScenePacketV2Page(packet, id));
    const positions3d = new Float32Array(openGalaxyScenePacketV2Page(packet, POSITIONS_3D));
    const hopfCellRange = manifest.stringRanges.nodeHopfCellIds || manifest.stringRanges.nodeHopfBaseIds;
    const hopfFiberRange = manifest.stringRanges.nodeHopfFiberIds || hopfCellRange;
    const hopfLaneRange = manifest.stringRanges.nodeHopfLaneIds || hopfFiberRange;

    return attachGalaxySceneRuntimeIndex({
        sourceMode: manifest.sourceMode,
        layoutMode: manifest.layoutMode,
        ids: stringsInRange(strings, manifest.stringRanges.nodeIds),
        labels: stringsInRange(strings, manifest.stringRanges.nodeLabels),
        kinds: stringsInRange(strings, manifest.stringRanges.nodeKinds),
        groupIds: stringsInRange(strings, manifest.stringRanges.nodeGroupIds),
        hopfBaseIds: stringsInRange(strings, manifest.stringRanges.nodeHopfBaseIds),
        hopfCellIds: stringsInRange(strings, hopfCellRange),
        hopfFiberIds: stringsInRange(strings, hopfFiberRange),
        hopfLaneIds: stringsInRange(strings, hopfLaneRange),
        hopfRoles: new Uint8Array(requiredPage(pages, NODE_FLAGS)),
        groups: decodeJsonPage(packet, GROUPS, []),
        hopfRibbons: guides.hopfRibbons,
        lorentzGuides: guides.lorentzGuides,
        transitPlan: decodeOptionalJsonPage(packet, TRANSIT_PLAN),
        relationControls: decodeOptionalJsonPage(packet, RELATION_CONTROLS),
        busemannHorospheres: decodeOptionalJsonPage(packet, BUSEMANN_HOROSPHERES),
        hybridShellPositions: optionalFloat32Page(pages, HYBRID_SHELL_POSITIONS),
        hybridCommitmentPositions: optionalFloat32Page(pages, HYBRID_COMMITMENT_POSITIONS),
        hybridReceipts: decodeOptionalJsonPage(packet, HYBRID_RECEIPTS),
        hierarchyShellRadii: optionalFloat32Page(pages, HIERARCHY_SHELL_RADII),
        hierarchyShellRanks: optionalUint8Page(pages, HIERARCHY_SHELL_RANKS),
        hierarchyHints: decodeOptionalJsonPage(packet, HIERARCHY_HINTS),
        positions3d,
        positions2d: flattenPositions2d(positions3d),
        radii: new Float32Array(requiredPage(pages, RADII)),
        colors: unpackRgba8AsRgb(new Uint8Array(requiredPage(pages, NODE_COLORS))),
        paletteSlots: new Uint8Array(requiredPage(pages, NODE_PALETTE_SLOTS)),
        edgePairs: new Uint32Array(requiredPage(pages, EDGE_PAIRS)),
        edgeIds: stringsInRange(strings, manifest.stringRanges.edgeIds),
        edgeTypes: stringsInRange(strings, manifest.stringRanges.edgeTypes),
        edgeColors: unpackRgba8AsRgb(new Uint8Array(requiredPage(pages, EDGE_COLORS))),
        edgeAlpha: new Float32Array(requiredPage(pages, EDGE_ALPHA)),
        edgeKinds: new Uint8Array(requiredPage(pages, EDGE_FLAGS)),
    });
}

export function galaxyScenePacketV2TransferList(packet: GalaxyScenePacketV2): Transferable[] {
    return Object.values(packet.pages);
}

function assertGalaxyScenePacketLittleEndianRuntime(): void {
    if (!GALAXY_SCENE_PACKET_LITTLE_ENDIAN_RUNTIME) {
        throw new Error('Galaxy scene packet V2 requires a little-endian runtime.');
    }
}

export function galaxySceneIdentityKeys(ids: readonly string[]): Uint32Array {
    const keys = new Uint32Array(ids.length * 2);
    for (let index = 0; index < ids.length; index++) {
        keys[index * 2] = fnv1a32(ids[index], 0x811c9dc5);
        keys[index * 2 + 1] = fnv1a32(ids[index], 0x9e3779b9);
    }
    return keys;
}

export function galaxySceneIdentityCollisionPages(
    ids: readonly string[],
    keys: Uint32Array,
): GalaxyScenePacketV2CollisionPages {
    if (keys.length !== ids.length * 2) throw new Error('Galaxy identity key count mismatch.');
    const buckets = new Map<string, { low: number; high: number; identities: Map<string, number[]> }>();
    for (let index = 0; index < ids.length; index++) {
        const low = keys[index * 2];
        const high = keys[index * 2 + 1];
        const key = `${low}:${high}`;
        const bucket = buckets.get(key) ?? { low, high, identities: new Map<string, number[]>() };
        const members = bucket.identities.get(ids[index]) ?? [];
        members.push(index);
        bucket.identities.set(ids[index], members);
        buckets.set(key, bucket);
    }
    const records: number[] = [];
    const members: number[] = [];
    let collisionCount = 0;
    for (const bucket of buckets.values()) {
        if (bucket.identities.size < 2) continue;
        const start = members.length;
        for (const indexes of bucket.identities.values()) members.push(...indexes);
        records.push(bucket.low, bucket.high, start, members.length - start);
        collisionCount += 1;
    }
    return { records: Uint32Array.from(records), members: Uint32Array.from(members), collisionCount };
}

function addCollisionPages(
    pages: Record<string, ArrayBuffer>,
    manifests: GalaxyScenePacketV2PageManifest[],
    recordId: string,
    memberId: string,
    collisions: GalaxyScenePacketV2CollisionPages,
    context: Pick<GalaxyScenePacketV2PageManifest, 'generationId' | 'tileId' | 'lod' | 'authorityReceipt'>,
): void {
    addPage(pages, manifests, recordId, 'shared', 'resident', 'u32-le', collisions.records, context);
    addPage(pages, manifests, memberId, 'shared', 'resident', 'u32-le', collisions.members, context);
}

function addOptionalDetailPage(
    pages: Record<string, ArrayBuffer>,
    manifests: GalaxyScenePacketV2PageManifest[],
    id: string,
    encoding: GalaxyScenePacketV2Encoding,
    view: ArrayBufferView | undefined,
    context: Pick<GalaxyScenePacketV2PageManifest, 'generationId' | 'tileId' | 'lod' | 'authorityReceipt'>,
): void {
    if (view) addPage(pages, manifests, id, 'detail', 'on-demand', encoding, view, context);
}

function addPage(
    pages: Record<string, ArrayBuffer>,
    manifests: GalaxyScenePacketV2PageManifest[],
    id: string,
    domain: GalaxyScenePacketV2PageDomain,
    loadPolicy: GalaxyScenePacketV2LoadPolicy,
    encoding: GalaxyScenePacketV2Encoding,
    view: ArrayBufferView,
    context: Pick<GalaxyScenePacketV2PageManifest, 'generationId' | 'tileId' | 'lod' | 'authorityReceipt'>,
): void {
    const buffer = exactArrayBuffer(view);
    pages[id] = buffer;
    manifests.push({
        id,
        domain,
        loadPolicy,
        encoding,
        elementCount: elementCount(view),
        byteLength: buffer.byteLength,
        ...context,
        contentHash: galaxyScenePacketHashBuffer(buffer),
    });
}

function buildStringSlab(
    fields: ReadonlyArray<readonly [keyof GalaxyScenePacketV2Manifest['stringRanges'], readonly string[]]>,
): StringSlab {
    const encoder = new TextEncoder();
    const encoded: Uint8Array[] = [];
    const offsets = [0];
    const ranges = {} as GalaxyScenePacketV2Manifest['stringRanges'];
    let stringIndex = 0;
    let byteLength = 0;
    for (const [name, values] of fields) {
        ranges[name] = { start: stringIndex, count: values.length };
        for (const value of values) {
            const bytes = encoder.encode(value);
            encoded.push(bytes);
            byteLength += bytes.length;
            offsets.push(byteLength);
            stringIndex += 1;
        }
    }
    const slab = new Uint8Array(byteLength);
    let offset = 0;
    for (const bytes of encoded) {
        slab.set(bytes, offset);
        offset += bytes.length;
    }
    return { offsets: Uint32Array.from(offsets), bytes: slab, ranges };
}

function decodeStringSlab(offsets: Uint32Array, bytes: Uint8Array): string[] {
    const decoder = new TextDecoder();
    const values = new Array<string>(Math.max(0, offsets.length - 1));
    for (let index = 0; index < values.length; index++) {
        values[index] = decoder.decode(bytes.subarray(offsets[index], offsets[index + 1]));
    }
    return values;
}

function stringsInRange(strings: string[], range: GalaxyScenePacketV2StringRange): string[] {
    return strings.slice(range.start, range.start + range.count);
}

export function decodeGalaxyScenePacketV2GuideDetails(
    packet: VerifiedGalaxyScenePacketV2,
): GalaxyScenePacketV2GuideDetails {
    return decodeGalaxySceneGuidePages((id) => openGalaxyScenePacketV2Page(packet, id));
}

function packRgbAsRgba8(rgb: Float32Array): Uint8Array {
    const rgba = new Uint8Array((rgb.length / 3) * 4);
    for (let source = 0, target = 0; source < rgb.length; source += 3, target += 4) {
        rgba[target] = normalizedByte(rgb[source]);
        rgba[target + 1] = normalizedByte(rgb[source + 1]);
        rgba[target + 2] = normalizedByte(rgb[source + 2]);
        rgba[target + 3] = 255;
    }
    return rgba;
}

function unpackRgba8AsRgb(rgba: Uint8Array): Float32Array {
    const rgb = new Float32Array((rgba.length / 4) * 3);
    for (let source = 0, target = 0; source < rgba.length; source += 4, target += 3) {
        rgb[target] = rgba[source] / 255;
        rgb[target + 1] = rgba[source + 1] / 255;
        rgb[target + 2] = rgba[source + 2] / 255;
    }
    return rgb;
}

function flattenPositions2d(positions3d: Float32Array): Float32Array {
    const positions2d = positions3d.slice();
    for (let index = 2; index < positions2d.length; index += 3) positions2d[index] = 0;
    return positions2d;
}

function optionalFloat32Page(pages: Record<string, ArrayBuffer>, id: string): Float32Array | undefined {
    return pages[id] ? new Float32Array(pages[id]) : undefined;
}

function optionalUint8Page(pages: Record<string, ArrayBuffer>, id: string): Uint8Array | undefined {
    return pages[id] ? new Uint8Array(pages[id]) : undefined;
}

function requiredPage(pages: Record<string, ArrayBuffer>, id: string): ArrayBuffer {
    const page = pages[id];
    if (!page) throw new Error(`Galaxy scene packet missing required page: ${id}`);
    return page;
}

function exactArrayBuffer(view: ArrayBufferView): ArrayBuffer {
    const buffer = view.buffer as ArrayBuffer;
    if (view.byteOffset === 0 && view.byteLength === buffer.byteLength) return buffer;
    return buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
}

function elementCount(view: ArrayBufferView): number {
    return 'length' in view && typeof view.length === 'number' ? view.length : view.byteLength;
}

function normalizedByte(value: number): number {
    return Math.round(Math.max(0, Math.min(1, value)) * 255);
}

function emptyStrings(length: number): string[] {
    return new Array<string>(length).fill('');
}

function fnv1a32(value: string, seed: number): number {
    let hash = seed >>> 0;
    const bytes = new TextEncoder().encode(value);
    for (const byte of bytes) hash = Math.imul(hash ^ byte, 0x01000193) >>> 0;
    return hash;
}

function guideEncoding(id: string): GalaxyScenePacketV2Encoding {
    if (id === GALAXY_GUIDE_PAGE_IDS.colors) return 'f64-le';
    if (id === GALAXY_GUIDE_PAGE_IDS.positions) return 'f32-le';
    if (id === GALAXY_GUIDE_PAGE_IDS.stringSlab) return 'utf8';
    return 'u32-le';
}

function addJsonPage<T>(
    pages: Record<string, ArrayBuffer>,
    manifests: GalaxyScenePacketV2PageManifest[],
    id: string,
    value: T,
    context: Pick<GalaxyScenePacketV2PageManifest, 'generationId' | 'tileId' | 'lod' | 'authorityReceipt'>,
): void {
    addPage(pages, manifests, id, 'detail', 'on-demand', 'utf8-json', new TextEncoder().encode(JSON.stringify(value)), context);
}

function addOptionalJsonPage<T>(
    pages: Record<string, ArrayBuffer>,
    manifests: GalaxyScenePacketV2PageManifest[],
    id: string,
    value: T | undefined,
    context: Pick<GalaxyScenePacketV2PageManifest, 'generationId' | 'tileId' | 'lod' | 'authorityReceipt'>,
): void {
    if (value !== undefined) addJsonPage(pages, manifests, id, value, context);
}

function decodeJsonPage<T>(packet: VerifiedGalaxyScenePacketV2, id: string, fallback: T): T {
    if (!packet.manifest.pages.some((page) => page.id === id)) return fallback;
    return JSON.parse(new TextDecoder().decode(openGalaxyScenePacketV2Page(packet, id))) as T;
}

function decodeOptionalJsonPage<T>(packet: VerifiedGalaxyScenePacketV2, id: string): T | undefined {
    if (!packet.manifest.pages.some((page) => page.id === id)) return undefined;
    return decodeJsonPage<T | undefined>(packet, id, undefined);
}
