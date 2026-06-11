import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'graph-style-lab:entity-colors:v1';

describe('entityColorStore', () => {
    beforeEach(() => {
        const values = new Map<string, string>();
        vi.stubGlobal('localStorage', {
            getItem: (key: string) => values.get(key) ?? null,
            setItem: (key: string, value: string) => values.set(key, value),
            removeItem: (key: string) => values.delete(key),
            clear: () => values.clear(),
        });
    });

    afterEach(() => {
        localStorage.removeItem(STORAGE_KEY);
        vi.unstubAllGlobals();
        vi.resetModules();
    });

    it('persists entity and graph color selections across store initialization', async () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            colors: { NETWORK: '123 45% 56%' },
            textColors: { NETWORK: '124 46% 57%' },
            graphNodeColors: { causalFact: '345 67% 45%' },
        }));

        const { entityColorStore } = await import('./entityColorStore');
        entityColorStore.initialize();

        expect(entityColorStore.getRawHsl('NETWORK')).toBe('123 45% 56%');
        expect(entityColorStore.getRawTextHsl('NETWORK')).toBe('124 46% 57%');
        expect(entityColorStore.getRawGraphNodeHsl('causalFact')).toBe('345 67% 45%');
    });

    it('treats legacy faction as network for color writes and reads', async () => {
        const { entityColorStore, normalizeEntityKind } = await import('./entityColorStore');

        entityColorStore.setColor('FACTION', '190 88% 44%');

        expect(normalizeEntityKind('FACTION')).toBe('NETWORK');
        expect(entityColorStore.getRawHsl('NETWORK')).toBe('190 88% 44%');
        expect(entityColorStore.getRawHsl('FACTION')).toBe('190 88% 44%');
    });
});
