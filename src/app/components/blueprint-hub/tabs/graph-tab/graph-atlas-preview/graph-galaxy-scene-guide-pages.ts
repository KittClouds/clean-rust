import type {
    GalaxyHopfRibbonView,
    GalaxyLorentzGuideView,
    GalaxySceneV2,
} from './graph-galaxy-scene-v2';

export const GALAXY_GUIDE_PAGE_IDS = {
    header: 'guide/header',
    metadata: 'guide/metadata',
    offsets: 'guide/offsets',
    colors: 'guide/colors-f64',
    positions: 'guide/positions-f32',
    nodeRefs: 'guide/node-string-refs',
    stringOffsets: 'guide/string-offsets',
    stringSlab: 'guide/string-slab',
} as const;

export type GalaxyScenePacketV2GuideDetails = Pick<GalaxySceneV2, 'hopfRibbons' | 'lorentzGuides'>;

const MAGIC = 0x3247_4850;
const VERSION = 1;
const HEADER_WORDS = 10;
const METADATA_STRIDE = 10;
const OFFSETS_STRIDE = 4;
const NO_STRING = 0xffff_ffff;

const HOPF_KINDS: readonly GalaxyHopfRibbonView['guideKind'][] = [
    'dataFiber', 'crossFiberBraid', 'spaceFiber', 'torusBand', 'axis',
];
const LORENTZ_KINDS: readonly GalaxyLorentzGuideView['guideKind'][] = [
    'membership', 'rootLane', 'levelShell', 'wAxis',
];

type Guide = GalaxyHopfRibbonView | GalaxyLorentzGuideView;

interface StringTable {
    offsets: Uint32Array;
    bytes: Uint8Array;
}

export function packGalaxySceneGuidePages(scene: GalaxySceneV2): Record<string, ArrayBufferView> {
    const hopfRibbons = scene.hopfRibbons ?? [];
    const lorentzGuides = scene.lorentzGuides ?? [];
    const guides: Guide[] = [...hopfRibbons, ...lorentzGuides];
    const hopfCount = hopfRibbons.length;
    const metadata = new Uint32Array(guides.length * METADATA_STRIDE);
    const offsets = new Uint32Array(guides.length * OFFSETS_STRIDE);
    const colors = new Float64Array(guides.length * 6);
    const positions = new Float32Array(guides.reduce((sum, guide) => sum + guide.positions3d.length, 0));
    const nodeRefs = new Uint32Array(guides.reduce((sum, guide) => sum + guide.nodeIds.length, 0));
    const strings: string[] = [];
    const stringIndexes = new Map<string, number>();
    const intern = (value: string): number => {
        const existing = stringIndexes.get(value);
        if (existing !== undefined) return existing;
        const index = strings.length;
        strings.push(value);
        stringIndexes.set(value, index);
        return index;
    };
    let positionCursor = 0;
    let nodeCursor = 0;
    for (let index = 0; index < guides.length; index++) {
        const guide = guides[index];
        const meta = index * METADATA_STRIDE;
        const span = index * OFFSETS_STRIDE;
        const lorentz = index >= hopfCount ? guide as GalaxyLorentzGuideView : null;
        metadata[meta] = lorentz ? 1 : 0;
        metadata[meta + 1] = intern(guide.id);
        metadata.set(float64Bits(guide.importance), meta + 2);
        metadata.set(float64Bits(guide.guideWeight), meta + 4);
        metadata[meta + 6] = guideKindCode(guide);
        metadata[meta + 7] = lorentz ? intern(lorentz.treeId) : NO_STRING;
        metadata[meta + 8] = lorentz ? intern(lorentz.treeKind) : NO_STRING;
        metadata[meta + 9] = lorentz ? lorentz.level >>> 0 : 0;
        offsets[span] = positionCursor;
        offsets[span + 1] = guide.positions3d.length;
        offsets[span + 2] = nodeCursor;
        offsets[span + 3] = guide.nodeIds.length;
        positions.set(guide.positions3d, positionCursor);
        positionCursor += guide.positions3d.length;
        for (const nodeId of guide.nodeIds) nodeRefs[nodeCursor++] = intern(nodeId);
        writeColor(colors, index * 6, guide.color);
        if (guide.sourceColor) writeColor(colors, index * 6 + 3, guide.sourceColor);
        else colors.fill(Number.NaN, index * 6 + 3, index * 6 + 6);
    }
    const stringTable = buildStringTable(strings);
    const header = Uint32Array.of(
        MAGIC,
        VERSION,
        hopfCount,
        lorentzGuides.length,
        guides.length,
        METADATA_STRIDE,
        OFFSETS_STRIDE,
        positions.length,
        nodeRefs.length,
        strings.length,
    );
    return {
        [GALAXY_GUIDE_PAGE_IDS.header]: header,
        [GALAXY_GUIDE_PAGE_IDS.metadata]: metadata,
        [GALAXY_GUIDE_PAGE_IDS.offsets]: offsets,
        [GALAXY_GUIDE_PAGE_IDS.colors]: colors,
        [GALAXY_GUIDE_PAGE_IDS.positions]: positions,
        [GALAXY_GUIDE_PAGE_IDS.nodeRefs]: nodeRefs,
        [GALAXY_GUIDE_PAGE_IDS.stringOffsets]: stringTable.offsets,
        [GALAXY_GUIDE_PAGE_IDS.stringSlab]: stringTable.bytes,
    };
}

export function decodeGalaxySceneGuidePages(
    page: (id: string) => ArrayBuffer,
): GalaxyScenePacketV2GuideDetails {
    const header = new Uint32Array(page(GALAXY_GUIDE_PAGE_IDS.header));
    if (header.length !== HEADER_WORDS || header[0] !== MAGIC || header[1] !== VERSION) {
        throw new Error('Galaxy guide page header is unsupported.');
    }
    const hopfCount = header[2];
    const lorentzCount = header[3];
    const recordCount = header[4];
    if (recordCount !== hopfCount + lorentzCount
        || header[5] !== METADATA_STRIDE
        || header[6] !== OFFSETS_STRIDE) {
        throw new Error('Galaxy guide page record contract drift.');
    }
    const metadata = new Uint32Array(page(GALAXY_GUIDE_PAGE_IDS.metadata));
    const offsets = new Uint32Array(page(GALAXY_GUIDE_PAGE_IDS.offsets));
    const colors = new Float64Array(page(GALAXY_GUIDE_PAGE_IDS.colors));
    const positions = new Float32Array(page(GALAXY_GUIDE_PAGE_IDS.positions));
    const nodeRefs = new Uint32Array(page(GALAXY_GUIDE_PAGE_IDS.nodeRefs));
    const stringOffsets = new Uint32Array(page(GALAXY_GUIDE_PAGE_IDS.stringOffsets));
    const stringSlab = new Uint8Array(page(GALAXY_GUIDE_PAGE_IDS.stringSlab));
    if (metadata.length !== recordCount * METADATA_STRIDE
        || offsets.length !== recordCount * OFFSETS_STRIDE
        || colors.length !== recordCount * 6
        || positions.length !== header[7]
        || nodeRefs.length !== header[8]
        || stringOffsets.length !== header[9] + 1) {
        throw new Error('Galaxy guide page length drift.');
    }
    const strings = decodeStringTable(stringOffsets, stringSlab);
    const hopfRibbons: GalaxyHopfRibbonView[] = [];
    const lorentzGuides: GalaxyLorentzGuideView[] = [];
    for (let index = 0; index < recordCount; index++) {
        const meta = index * METADATA_STRIDE;
        const span = index * OFFSETS_STRIDE;
        const positionStart = offsets[span];
        const positionCount = offsets[span + 1];
        const nodeStart = offsets[span + 2];
        const nodeCount = offsets[span + 3];
        if (positionStart + positionCount > positions.length || nodeStart + nodeCount > nodeRefs.length) {
            throw new Error(`Galaxy guide page offset drift at record ${index}.`);
        }
        const positions3d = positions.slice(positionStart, positionStart + positionCount);
        const common = {
            id: requiredString(strings, metadata[meta + 1]),
            nodeIds: Array.from(nodeRefs.subarray(nodeStart, nodeStart + nodeCount), (value) => requiredString(strings, value)),
            positions3d,
            positions2d: flattenPositions2d(positions3d),
            color: readColor(colors, index * 6),
            importance: bitsFloat64(metadata[meta + 2], metadata[meta + 3]),
            guideWeight: bitsFloat64(metadata[meta + 4], metadata[meta + 5]),
            sourceColor: Number.isFinite(colors[index * 6 + 3]) ? readColor(colors, index * 6 + 3) : undefined,
        };
        if (metadata[meta] === 0) {
            hopfRibbons.push({
                ...common,
                guideKind: requiredKind(HOPF_KINDS, metadata[meta + 6], index),
            });
        } else if (metadata[meta] === 1) {
            lorentzGuides.push({
                ...common,
                treeId: requiredString(strings, metadata[meta + 7]),
                treeKind: requiredString(strings, metadata[meta + 8]),
                level: metadata[meta + 9] | 0,
                guideKind: requiredKind(LORENTZ_KINDS, metadata[meta + 6] - HOPF_KINDS.length, index),
            });
        } else {
            throw new Error(`Galaxy guide family drift at record ${index}.`);
        }
    }
    return { hopfRibbons, lorentzGuides };
}

function guideKindCode(guide: Guide): number {
    if ('treeId' in guide) {
        const index = LORENTZ_KINDS.indexOf(guide.guideKind);
        if (index < 0) throw new Error(`Unsupported Lorentz guide kind: ${guide.guideKind}`);
        return HOPF_KINDS.length + index;
    }
    const index = HOPF_KINDS.indexOf(guide.guideKind);
    if (index < 0) throw new Error(`Unsupported Hopf guide kind: ${guide.guideKind}`);
    return index;
}

function buildStringTable(values: readonly string[]): StringTable {
    const encoder = new TextEncoder();
    const encoded = values.map((value) => encoder.encode(value));
    const offsets = new Uint32Array(values.length + 1);
    for (let index = 0; index < encoded.length; index++) offsets[index + 1] = offsets[index] + encoded[index].length;
    const bytes = new Uint8Array(offsets[offsets.length - 1]);
    for (let index = 0; index < encoded.length; index++) bytes.set(encoded[index], offsets[index]);
    return { offsets, bytes };
}

function decodeStringTable(offsets: Uint32Array, bytes: Uint8Array): string[] {
    const decoder = new TextDecoder();
    const strings = new Array<string>(Math.max(0, offsets.length - 1));
    for (let index = 0; index < strings.length; index++) {
        const start = offsets[index];
        const end = offsets[index + 1];
        if (end < start || end > bytes.length) throw new Error(`Galaxy guide string offset drift at ${index}.`);
        strings[index] = decoder.decode(bytes.subarray(start, end));
    }
    return strings;
}

function writeColor(target: Float64Array, offset: number, color: { r: number; g: number; b: number }): void {
    target[offset] = color.r;
    target[offset + 1] = color.g;
    target[offset + 2] = color.b;
}

function readColor(source: Float64Array, offset: number): { r: number; g: number; b: number } {
    return { r: source[offset], g: source[offset + 1], b: source[offset + 2] };
}

function flattenPositions2d(positions3d: Float32Array): Float32Array {
    const positions2d = positions3d.slice();
    for (let index = 2; index < positions2d.length; index += 3) positions2d[index] = 0;
    return positions2d;
}

function requiredString(strings: readonly string[], index: number): string {
    const value = strings[index];
    if (value === undefined) throw new Error(`Galaxy guide string index drift: ${index}.`);
    return value;
}

function requiredKind<T extends string>(kinds: readonly T[], index: number, record: number): T {
    const value = kinds[index];
    if (!value) throw new Error(`Galaxy guide kind drift at record ${record}.`);
    return value;
}

function float64Bits(value: number): Uint32Array {
    return new Uint32Array(Float64Array.of(value).buffer);
}

function bitsFloat64(low: number, high: number): number {
    return new Float64Array(Uint32Array.of(low, high).buffer)[0];
}
