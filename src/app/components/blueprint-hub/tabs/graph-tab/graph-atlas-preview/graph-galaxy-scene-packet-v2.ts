import {
    attachGalaxySceneRuntimeIndex,
    type GalaxySceneV2,
} from './graph-galaxy-scene-v2';
import {
    GALAXY_SCENE_PACKET_V2_SCHEMA,
    type GalaxyScenePacketV2,
    type GalaxyScenePacketV2CollisionPages,
    type GalaxyScenePacketV2Context,
    type GalaxyScenePacketV2Encoding,
    type GalaxyScenePacketV2LoadPolicy,
    type GalaxyScenePacketV2Manifest,
    type GalaxyScenePacketV2PageDomain,
    type GalaxyScenePacketV2PageManifest,
    type GalaxyScenePacketV2StringRange,
} from './graph-galaxy-scene-packet-v2.model';

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
const SCENE_DETAILS = 'detail/scene-extras';
export const GALAXY_SCENE_PACKET_LITTLE_ENDIAN_RUNTIME =
    new Uint8Array(new Uint32Array([0x01020304]).buffer)[0] === 0x04;

interface GalaxyScenePacketV2Details {
    groups: GalaxySceneV2['groups'];
    hopfRibbons: GalaxySceneV2['hopfRibbons'];
    lorentzGuides: GalaxySceneV2['lorentzGuides'];
    transitPlan?: GalaxySceneV2['transitPlan'];
    relationControls?: GalaxySceneV2['relationControls'];
    busemannHorospheres?: GalaxySceneV2['busemannHorospheres'];
    hybridReceipts?: GalaxySceneV2['hybridReceipts'];
    hierarchyHints?: GalaxySceneV2['hierarchyHints'];
}

export type GalaxyScenePacketV2GuideDetails = Pick<
    GalaxyScenePacketV2Details,
    'hopfRibbons' | 'lorentzGuides'
>;

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
    addPage(pages, pageManifests, NODE_FLAGS, 'manifold', 'resident', 'u8', scene.hopfRoles ?? new Uint8Array(scene.ids.length), pageContext);
    addPage(pages, pageManifests, EDGE_COLORS, 'manifold', 'resident', 'rgba8', packRgbAsRgba8(scene.edgeColors), pageContext);
    addPage(pages, pageManifests, EDGE_ALPHA, 'manifold', 'resident', 'f32-le', scene.edgeAlpha, pageContext);
    addPage(pages, pageManifests, EDGE_FLAGS, 'manifold', 'resident', 'u8', scene.edgeKinds, pageContext);
    addOptionalPage(pages, pageManifests, HYBRID_SHELL_POSITIONS, 'f32-le', scene.hybridShellPositions, pageContext);
    addOptionalPage(pages, pageManifests, HYBRID_COMMITMENT_POSITIONS, 'f32-le', scene.hybridCommitmentPositions, pageContext);
    addOptionalPage(pages, pageManifests, HIERARCHY_SHELL_RADII, 'f32-le', scene.hierarchyShellRadii, pageContext);
    addOptionalPage(pages, pageManifests, HIERARCHY_SHELL_RANKS, 'u8', scene.hierarchyShellRanks, pageContext);
    addPage(pages, pageManifests, STRING_OFFSETS, 'detail', 'on-demand', 'u32-le', strings.offsets, pageContext);
    addPage(pages, pageManifests, STRING_SLAB, 'detail', 'on-demand', 'utf8', strings.bytes, pageContext);
    addPage(
        pages,
        pageManifests,
        SCENE_DETAILS,
        'detail',
        'on-demand',
        'utf8-json',
        encodeSceneDetails(scene),
        pageContext,
    );

    const contentHash = hashText(pageManifests.map((page) => `${page.id}:${page.contentHash}`).join('|'));
    return {
        manifest: {
            schemaVersion: GALAXY_SCENE_PACKET_V2_SCHEMA,
            ...pageContext,
            layoutMode: scene.layoutMode,
            sourceMode: scene.sourceMode,
            identityEncoding: 'fnv1a32-dual-u64',
            positionEncoding: 'float32-tile-local',
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
        new Uint32Array(requiredPage(pages, STRING_OFFSETS)),
        new Uint8Array(requiredPage(pages, STRING_SLAB)),
    );
    const details = decodeSceneDetails(new Uint8Array(requiredPage(pages, SCENE_DETAILS)));
    const positions3d = new Float32Array(requiredPage(pages, POSITIONS_3D));
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
        groups: details.groups,
        hopfRibbons: details.hopfRibbons,
        lorentzGuides: details.lorentzGuides,
        transitPlan: details.transitPlan,
        relationControls: details.relationControls,
        busemannHorospheres: details.busemannHorospheres,
        hybridShellPositions: optionalFloat32Page(pages, HYBRID_SHELL_POSITIONS),
        hybridCommitmentPositions: optionalFloat32Page(pages, HYBRID_COMMITMENT_POSITIONS),
        hybridReceipts: details.hybridReceipts,
        hierarchyShellRadii: optionalFloat32Page(pages, HIERARCHY_SHELL_RADII),
        hierarchyShellRanks: optionalUint8Page(pages, HIERARCHY_SHELL_RANKS),
        hierarchyHints: details.hierarchyHints,
        positions3d,
        positions2d: flattenPositions2d(positions3d),
        radii: new Float32Array(requiredPage(pages, RADII)),
        colors: unpackRgba8AsRgb(new Uint8Array(requiredPage(pages, NODE_COLORS))),
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

export function assertGalaxyScenePacketV2(packet: GalaxyScenePacketV2): void {
    if (packet.manifest.schemaVersion !== GALAXY_SCENE_PACKET_V2_SCHEMA) {
        throw new Error(`Unsupported galaxy scene packet: ${packet.manifest.schemaVersion}`);
    }
    if (!packet.manifest.generationId || !packet.manifest.authorityReceipt) {
        throw new Error('Galaxy scene packet requires generation and authority receipt.');
    }
    for (const page of packet.manifest.pages) {
        const buffer = packet.pages[page.id];
        if (!buffer) throw new Error(`Galaxy scene packet missing page: ${page.id}`);
        if (buffer.byteLength !== page.byteLength) throw new Error(`Galaxy scene page length drift: ${page.id}`);
        if (hashBuffer(buffer) !== page.contentHash) throw new Error(`Galaxy scene page hash drift: ${page.id}`);
        if (page.generationId !== packet.manifest.generationId || page.tileId !== packet.manifest.tileId || page.lod !== packet.manifest.lod) {
            throw new Error(`Galaxy scene page ownership drift: ${page.id}`);
        }
        if (page.authorityReceipt !== packet.manifest.authorityReceipt) {
            throw new Error(`Galaxy scene page authority drift: ${page.id}`);
        }
    }
    const contentHash = hashText(packet.manifest.pages.map((page) => `${page.id}:${page.contentHash}`).join('|'));
    if (contentHash !== packet.manifest.contentHash) {
        throw new Error('Galaxy scene packet manifest hash drift.');
    }
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

function addOptionalPage(
    pages: Record<string, ArrayBuffer>,
    manifests: GalaxyScenePacketV2PageManifest[],
    id: string,
    encoding: GalaxyScenePacketV2Encoding,
    view: ArrayBufferView | undefined,
    context: Pick<GalaxyScenePacketV2PageManifest, 'generationId' | 'tileId' | 'lod' | 'authorityReceipt'>,
): void {
    if (view) addPage(pages, manifests, id, 'manifold', 'resident', encoding, view, context);
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
        contentHash: hashBuffer(buffer),
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

function encodeSceneDetails(scene: GalaxySceneV2): Uint8Array {
    const details: GalaxyScenePacketV2Details = {
        groups: scene.groups,
        hopfRibbons: scene.hopfRibbons,
        lorentzGuides: scene.lorentzGuides,
        transitPlan: scene.transitPlan,
        relationControls: scene.relationControls,
        busemannHorospheres: scene.busemannHorospheres,
        hybridReceipts: scene.hybridReceipts,
        hierarchyHints: scene.hierarchyHints,
    };
    return new TextEncoder().encode(JSON.stringify(details, typedArrayReplacer));
}

function decodeSceneDetails(bytes: Uint8Array): GalaxyScenePacketV2Details {
    return JSON.parse(new TextDecoder().decode(bytes), typedArrayReviver) as GalaxyScenePacketV2Details;
}

/**
 * Decodes only the bounded guide families from an already authority-checked
 * scene-extras page. Packet ownership and hashing remain the caller's job.
 */
export function decodeGalaxyScenePacketV2GuideDetails(
    buffer: ArrayBuffer,
): GalaxyScenePacketV2GuideDetails {
    const details = decodeSceneDetails(new Uint8Array(buffer));
    return {
        hopfRibbons: details.hopfRibbons ?? [],
        lorentzGuides: details.lorentzGuides ?? [],
    };
}

function typedArrayReplacer(_key: string, value: unknown): unknown {
    if (value instanceof Float32Array) return { __galaxyTypedArray: 'f32', values: Array.from(value) };
    if (value instanceof Uint32Array) return { __galaxyTypedArray: 'u32', values: Array.from(value) };
    if (value instanceof Uint8Array) return { __galaxyTypedArray: 'u8', values: Array.from(value) };
    return value;
}

function typedArrayReviver(_key: string, value: unknown): unknown {
    if (!value || typeof value !== 'object' || !('__galaxyTypedArray' in value)) return value;
    const encoded = value as { __galaxyTypedArray: string; values: number[] };
    if (encoded.__galaxyTypedArray === 'f32') return Float32Array.from(encoded.values);
    if (encoded.__galaxyTypedArray === 'u32') return Uint32Array.from(encoded.values);
    if (encoded.__galaxyTypedArray === 'u8') return Uint8Array.from(encoded.values);
    return value;
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

function hashBuffer(buffer: ArrayBuffer): string {
    let low = 0x811c9dc5;
    let high = 0x9e3779b9;
    for (const byte of new Uint8Array(buffer)) {
        low = Math.imul(low ^ byte, 0x01000193) >>> 0;
        high = Math.imul(high ^ byte, 0x85ebca6b) >>> 0;
    }
    return `fnv1a64:${high.toString(16).padStart(8, '0')}${low.toString(16).padStart(8, '0')}`;
}

function hashText(value: string): string {
    return hashBuffer(new TextEncoder().encode(value).buffer as ArrayBuffer);
}
