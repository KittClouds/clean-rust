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

    it('normalizes state and context graph colors as distinct persisted roles', async () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            graphNodeColors: {
                decisionState: '88 80% 51%',
                rankStatus: '246 81% 52%',
                serviceContext: '32 82% 53%',
                affiliationContext: '176 83% 54%',
                familyContext: '326 84% 55%',
            },
        }));

        const { entityColorStore, normalizeGraphNodeColorKind } = await import('./entityColorStore');
        entityColorStore.initialize();

        expect(normalizeGraphNodeColorKind('decision_state')).toBe('decisionState');
        expect(normalizeGraphNodeColorKind('rank_or_status')).toBe('rankStatus');
        expect(normalizeGraphNodeColorKind('service_context')).toBe('serviceContext');
        expect(normalizeGraphNodeColorKind('affiliant_context')).toBe('affiliationContext');
        expect(normalizeGraphNodeColorKind('family_context')).toBe('familyContext');
        expect(entityColorStore.getRawGraphNodeHsl('decision-state')).toBe('88 80% 51%');
        expect(entityColorStore.getRawGraphNodeHsl('rank_or_status')).toBe('246 81% 52%');
        expect(entityColorStore.getRawGraphNodeHsl('serviceContext')).toBe('32 82% 53%');
        expect(entityColorStore.getRawGraphNodeHsl('affiliation_context')).toBe('176 83% 54%');
        expect(entityColorStore.getRawGraphNodeHsl('familyContext')).toBe('326 84% 55%');
    });
});
