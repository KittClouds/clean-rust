import { invoke } from '@tauri-apps/api/core';

import type { GraphEncoderCandidateNeighborhood } from './graph-rebuild-snapshot';
import {
    normalizeGraphEncoderVectorIndexOptions,
    type GraphEncoderNeighborhoodBuild,
    type GraphEncoderVectorIndexOptions,
    type GraphEncoderVectorPage,
} from './graph-encoder-vector-index';

const COMMAND = 'build_graph_encoder_index_packed';
const REQUEST_MAGIC = 'PHXVIDX2';
const RESPONSE_MAGIC = 'PHXVOUT2';
const VERSION = 2;
const REQUEST_HEADER_BYTES = 64;
const RESPONSE_HEADER_BYTES = 104;
const MAX_RESIDENT_ROWS = 250_000;
const MAX_DIMENSIONS = 4_096;
const MAX_VECTOR_BYTES = 512 * 1024 * 1024;

export interface NativeGraphEncoderNeighborhoodBuild extends GraphEncoderNeighborhoodBuild {
    receipt: {
        schemaVersion: 'phoenix-native-vector-index/v2';
        engine: 'rust-avx2-f64' | 'rust-scalar-f64';
        requestDigest: string;
        durationMs: number;
        vectorBytes: number;
        responseBytes: number;
    };
}

export function nativeGraphEncoderIndexAvailable(): boolean {
    return typeof window !== 'undefined' && Boolean(window.__TAURI_INTERNALS__);
}

export async function buildNativeGraphEncoderNeighborhoods(
    page: GraphEncoderVectorPage,
    options: GraphEncoderVectorIndexOptions,
): Promise<NativeGraphEncoderNeighborhoodBuild> {
    if (!nativeGraphEncoderIndexAvailable()) throw new Error('Native packed vector index is unavailable');
    if (!page.normalized) throw new Error('Native packed vector index requires normalized vectors');
    assertLittleEndian();
    const config = normalizeGraphEncoderVectorIndexOptions(options);
    const packet = encodeRequest(page, config);
    const raw = await invoke<ArrayBuffer | Uint8Array | number[]>(COMMAND, packet.bytes);
    return decodeResponse(raw, page, packet.nonce, config.neighborhoodK);
}

function encodeRequest(
    page: GraphEncoderVectorPage,
    options: ReturnType<typeof normalizeGraphEncoderVectorIndexOptions>,
): { bytes: Uint8Array; nonce: number } {
    const rows = page.targetIds.length;
    const vectorBytes = page.values.byteLength;
    if (rows > MAX_RESIDENT_ROWS) throw new Error(`Native vector residency exceeds ${MAX_RESIDENT_ROWS} rows`);
    if (page.dimensions > MAX_DIMENSIONS) throw new Error(`Native vector dimensions exceed ${MAX_DIMENSIONS}`);
    if (!Number.isSafeInteger(page.generation) || page.generation < 0) {
        throw new Error('Native vector generation must be a non-negative safe integer');
    }
    if (vectorBytes > MAX_VECTOR_BYTES) throw new Error('Native packed vector page exceeds 512 MiB');
    if (page.values.length !== rows * page.dimensions) throw new Error('Native vector page shape drift');
    const hashesBytes = checkedBytes(rows, 4);
    const ranksBytes = checkedBytes(rows, 4);
    const totalBytes = REQUEST_HEADER_BYTES + hashesBytes + ranksBytes + vectorBytes;
    const bytes = new Uint8Array(totalBytes);
    const view = new DataView(bytes.buffer);
    writeMagic(bytes, REQUEST_MAGIC);
    view.setUint16(8, VERSION, true);
    view.setUint16(10, REQUEST_HEADER_BYTES, true);
    view.setUint32(12, 1, true);
    view.setUint32(16, rows, true);
    view.setUint32(20, page.dimensions, true);
    view.setBigUint64(24, BigInt(page.generation), true);
    view.setUint16(32, options.neighborhoodK, true);
    view.setUint16(34, options.lshBands, true);
    view.setUint16(36, options.lshBits, true);
    view.setUint16(38, options.maxCandidatesPerTarget, true);
    view.setFloat64(40, options.minimumSimilarity, true);
    view.setUint32(48, hashesBytes, true);
    view.setUint32(52, ranksBytes, true);
    view.setUint32(56, vectorBytes, true);
    const nonce = requestNonce(page, options);
    view.setUint32(60, nonce, true);

    let offset = REQUEST_HEADER_BYTES;
    for (const targetId of page.targetIds) {
        view.setUint32(offset, hashText(targetId), true);
        offset += 4;
    }
    const lexicalRanks = targetLexicalRanks(page.targetIds);
    for (const rank of lexicalRanks) {
        view.setUint32(offset, rank, true);
        offset += 4;
    }
    bytes.set(new Uint8Array(page.values.buffer, page.values.byteOffset, vectorBytes), offset);
    return { bytes, nonce };
}

function decodeResponse(
    raw: ArrayBuffer | Uint8Array | number[],
    page: GraphEncoderVectorPage,
    nonce: number,
    expectedK: number,
): NativeGraphEncoderNeighborhoodBuild {
    const bytes = raw instanceof Uint8Array
        ? raw
        : raw instanceof ArrayBuffer
            ? new Uint8Array(raw)
            : Uint8Array.from(raw);
    if (bytes.byteLength < RESPONSE_HEADER_BYTES) throw new Error('Native vector response is truncated');
    assertMagic(bytes, RESPONSE_MAGIC);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const version = view.getUint16(8, true);
    const headerBytes = view.getUint16(10, true);
    const flags = view.getUint32(12, true);
    const rows = view.getUint32(16, true);
    const dimensions = view.getUint32(20, true);
    const neighborhoodK = view.getUint32(24, true);
    const rowStride = view.getUint32(28, true);
    const evaluatedPairs = safeInteger(view.getBigUint64(32, true), 'evaluated pair count');
    const neighborCount = safeInteger(view.getBigUint64(40, true), 'neighbor count');
    const durationMicros = safeInteger(view.getBigUint64(48, true), 'native duration');
    const generation = safeInteger(view.getBigUint64(56, true), 'generation');
    const responseNonce = view.getUint32(64, true);
    if (
        version !== VERSION
        || headerBytes !== RESPONSE_HEADER_BYTES
        || rows !== page.targetIds.length
        || dimensions !== page.dimensions
        || generation !== page.generation
        || neighborhoodK !== expectedK
        || responseNonce !== nonce
        || rowStride !== 4 + expectedK * 8
        || bytes.byteLength !== headerBytes + rows * rowStride
    ) {
        throw new Error('Native vector response contract drift');
    }

    const neighborhoods: GraphEncoderCandidateNeighborhood[] = new Array(rows);
    let decodedNeighbors = 0;
    for (let source = 0; source < rows; source += 1) {
        const rowOffset = headerBytes + source * rowStride;
        const count = view.getUint16(rowOffset, true);
        if (count > expectedK) throw new Error('Native vector response exceeded neighborhood K');
        const neighbors = new Array(count);
        for (let rank = 0; rank < count; rank += 1) {
            const entryOffset = rowOffset + 4 + rank * 8;
            const target = view.getUint32(entryOffset, true);
            if (target >= rows || target === source) throw new Error('Native vector response target is invalid');
            neighbors[rank] = {
                targetId: page.targetIds[target],
                score: view.getInt32(entryOffset + 4, true) / 1_000_000,
                rank: rank + 1,
            };
        }
        decodedNeighbors += count;
        neighborhoods[source] = { sourceTargetId: page.targetIds[source], neighbors };
    }
    if (decodedNeighbors !== neighborCount) throw new Error('Native vector neighbor receipt drift');
    return {
        neighborhoods,
        evaluatedPairs,
        receipt: {
            schemaVersion: 'phoenix-native-vector-index/v2',
            engine: flags & 1 ? 'rust-avx2-f64' : 'rust-scalar-f64',
            requestDigest: hex(bytes.subarray(72, 104)),
            durationMs: durationMicros / 1_000,
            vectorBytes: page.values.byteLength,
            responseBytes: bytes.byteLength,
        },
    };
}

function targetLexicalRanks(targetIds: readonly string[]): Uint32Array {
    const ordered = Array.from({ length: targetIds.length }, (_, row) => row)
        .sort((left, right) => targetIds[left].localeCompare(targetIds[right]));
    const ranks = new Uint32Array(targetIds.length);
    let collationGroup = 0;
    ordered.forEach((row, index) => {
        if (index && targetIds[ordered[index - 1]].localeCompare(targetIds[row]) !== 0) {
            collationGroup += 1;
        }
        ranks[row] = collationGroup;
    });
    return ranks;
}

function requestNonce(
    page: GraphEncoderVectorPage,
    options: ReturnType<typeof normalizeGraphEncoderVectorIndexOptions>,
): number {
    let hash = hashText(`${page.generation}\0${page.dimensions}\0${page.targetIds.length}`);
    hash = fnvWord(hash, options.neighborhoodK);
    hash = fnvWord(hash, options.lshBands);
    hash = fnvWord(hash, options.lshBits);
    hash = fnvWord(hash, options.maxCandidatesPerTarget);
    if (page.targetIds.length) {
        hash = fnvWord(hash, hashText(page.targetIds[0]));
        hash = fnvWord(hash, hashText(page.targetIds[page.targetIds.length - 1]));
    }
    return hash;
}

function checkedBytes(count: number, stride: number): number {
    const bytes = count * stride;
    if (!Number.isSafeInteger(bytes)) throw new Error('Native vector packet size overflow');
    return bytes;
}

function assertLittleEndian(): void {
    const word = new Uint32Array([0x01020304]);
    if (new Uint8Array(word.buffer)[0] !== 4) throw new Error('Native vector packets require little-endian floats');
}

function writeMagic(bytes: Uint8Array, magic: string): void {
    for (let index = 0; index < magic.length; index += 1) bytes[index] = magic.charCodeAt(index);
}

function assertMagic(bytes: Uint8Array, magic: string): void {
    for (let index = 0; index < magic.length; index += 1) {
        if (bytes[index] !== magic.charCodeAt(index)) throw new Error('Native vector response magic is invalid');
    }
}

function safeInteger(value: bigint, label: string): number {
    const number = Number(value);
    if (!Number.isSafeInteger(number)) throw new Error(`Native ${label} overflow`);
    return number;
}

function hex(bytes: Uint8Array): string {
    let value = '';
    for (const byte of bytes) value += byte.toString(16).padStart(2, '0');
    return `b3-${value}`;
}

function hashText(value: string): number {
    let hash = 0x811c9dc5;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash;
}

function fnvWord(hash: number, word: number): number {
    let out = hash;
    for (let byte = 0; byte < 4; byte += 1) {
        out ^= (word >>> (byte * 8)) & 0xff;
        out = Math.imul(out, 0x01000193) >>> 0;
    }
    return out;
}
