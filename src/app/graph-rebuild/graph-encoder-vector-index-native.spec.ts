// @vitest-environment jsdom
import { invoke } from '@tauri-apps/api/core';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { buildNativeGraphEncoderNeighborhoods } from './graph-encoder-vector-index-native';
import type { GraphEncoderVectorPage } from './graph-encoder-vector-index';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

const invokeMock = vi.mocked(invoke);

describe('packed native graph encoder boundary', () => {
    afterEach(() => {
        invokeMock.mockReset();
        delete (window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
    });

    it('sends one octet-stream page and decodes bounded fixed-width neighborhoods', async () => {
        (window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
        invokeMock.mockImplementation(async (command, args) => {
            expect(command).toBe('build_graph_encoder_index_packed');
            expect(args).toBeInstanceOf(Uint8Array);
            const request = args as Uint8Array;
            const requestView = new DataView(request.buffer, request.byteOffset, request.byteLength);
            expect(String.fromCharCode(...request.subarray(0, 8))).toBe('PHXVIDX2');
            expect(requestView.getUint32(16, true)).toBe(2);
            expect(requestView.getUint32(20, true)).toBe(4);
            expect(requestView.getBigUint64(24, true)).toBe(7n);
            expect(requestView.getUint16(32, true)).toBe(1);
            expect(requestView.getUint32(56, true)).toBe(32);
            return responsePacket(requestView.getUint32(60, true));
        });

        const result = await buildNativeGraphEncoderNeighborhoods(page(), {
            neighborhoodK: 1,
            maxCandidatesPerTarget: 1,
            minimumSimilarity: -1,
        });

        expect(result.neighborhoods).toEqual([
            { sourceTargetId: 'target:b', neighbors: [{ targetId: 'target:a', score: 0.75, rank: 1 }] },
            { sourceTargetId: 'target:a', neighbors: [{ targetId: 'target:b', score: 0.75, rank: 1 }] },
        ]);
        expect(result.evaluatedPairs).toBe(2);
        expect(result.receipt).toMatchObject({
            schemaVersion: 'phoenix-native-vector-index/v2',
            engine: 'rust-avx2-f64',
            durationMs: 1.5,
            vectorBytes: 32,
        });
    });

    it('fails before IPC when the resident page exceeds native bounds', async () => {
        (window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
        const oversized = { ...page(), dimensions: 4_097 } as GraphEncoderVectorPage;

        await expect(buildNativeGraphEncoderNeighborhoods(oversized, {}))
            .rejects.toThrow(/dimensions exceed 4096/);
        expect(invokeMock).not.toHaveBeenCalled();
    });
});

function page(): GraphEncoderVectorPage {
    return {
        modelId: 'packed-test',
        modelVersion: 'v1',
        executionProvider: 'transformers-worker',
        dimensions: 4,
        generation: 7,
        targetIds: ['target:b', 'target:a'],
        values: new Float32Array([1, 0, 0, 0, 0.75, Math.sqrt(0.4375), 0, 0]),
        normalized: true,
    };
}

function responsePacket(nonce: number): Uint8Array {
    const headerBytes = 104;
    const rowStride = 12;
    const bytes = new Uint8Array(headerBytes + rowStride * 2);
    const view = new DataView(bytes.buffer);
    writeMagic(bytes, 'PHXVOUT2');
    view.setUint16(8, 2, true);
    view.setUint16(10, headerBytes, true);
    view.setUint32(12, 1, true);
    view.setUint32(16, 2, true);
    view.setUint32(20, 4, true);
    view.setUint32(24, 1, true);
    view.setUint32(28, rowStride, true);
    view.setBigUint64(32, 2n, true);
    view.setBigUint64(40, 2n, true);
    view.setBigUint64(48, 1_500n, true);
    view.setBigUint64(56, 7n, true);
    view.setUint32(64, nonce, true);
    for (let row = 0; row < 2; row += 1) {
        const offset = headerBytes + row * rowStride;
        view.setUint16(offset, 1, true);
        view.setUint32(offset + 4, row ? 0 : 1, true);
        view.setInt32(offset + 8, 750_000, true);
    }
    return bytes;
}

function writeMagic(bytes: Uint8Array, magic: string): void {
    for (let index = 0; index < magic.length; index += 1) bytes[index] = magic.charCodeAt(index);
}
