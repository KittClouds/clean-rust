import { describe, expect, it } from 'vitest';

import {
    PHOENIX_STORE_API_VERSION,
    PHOENIX_WASM_MISMATCH_CODE,
    REQUIRED_PHOENIX_RUNTIME_CAPABILITIES,
    assertPhoenixRuntimeCapabilities,
    isPhoenixWasmMismatchError,
    normalizePhoenixRuntimeCompatibilityError,
} from './phoenix-runtime-compat';

describe('phoenix runtime compatibility', () => {
    it('accepts the current runtime capability payload', () => {
        const payload = assertPhoenixRuntimeCapabilities({
            storeApiVersion: PHOENIX_STORE_API_VERSION,
            capabilities: [...REQUIRED_PHOENIX_RUNTIME_CAPABILITIES],
        });

        expect(payload.storeApiVersion).toBe(PHOENIX_STORE_API_VERSION);
        expect(payload.capabilities).toEqual([...REQUIRED_PHOENIX_RUNTIME_CAPABILITIES]);
    });

    it('rejects older store API versions as stale WASM', () => {
        try {
            assertPhoenixRuntimeCapabilities({
                storeApiVersion: PHOENIX_STORE_API_VERSION - 1,
                capabilities: [...REQUIRED_PHOENIX_RUNTIME_CAPABILITIES],
            });
            throw new Error('expected compatibility failure');
        } catch (error) {
            expect(isPhoenixWasmMismatchError(error)).toBe(true);
            expect((error as Error & { code?: string }).code).toBe(PHOENIX_WASM_MISMATCH_CODE);
        }
    });

    it('normalizes missing runtime:capabilities into the stale-WASM error', () => {
        const error = normalizePhoenixRuntimeCompatibilityError(
            new Error('unsupported store command: runtime:capabilities'),
        );

        expect(isPhoenixWasmMismatchError(error)).toBe(true);
        expect(error.message).toContain('stale');
        expect(error.message).toContain('rebuild the active runtime');
    });
});
