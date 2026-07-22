import { describe, expect, it } from 'vitest';

import {
    graphCanvasProjectionPayloadResident,
    graphCanvasFirstPixelKey,
    graphCanvasResidentFirstPixelReceipt,
    graphCanvasPersistedSceneIdentity,
    graphCanvasPrewarmSettings,
    manifoldPrewarmJobOrder,
    manifoldPrewarmOrder,
} from './graph-canvas-cold-start.service';

describe('GraphCanvasColdStartService', () => {
    it('keeps packed restart packets isolated per scope and manifold', () => {
        expect(graphCanvasFirstPixelKey('global', 'hopf')).toBe('global\u0000hopf');
        expect(graphCanvasFirstPixelKey('global', 'hybrid')).not.toBe(graphCanvasFirstPixelKey('global', 'hopf'));
    });

    it('warms the current manifold first and then every remaining projection', () => {
        expect(manifoldPrewarmOrder('lorentz')).toEqual([
            'lorentz',
            'hybrid',
            'hopf',
            'product',
            'siegel',
        ]);
    });

    it('uses the same source-normalized settings key as the embeddings canvas', () => {
        const settings = graphCanvasPrewarmSettings({
            manifoldMode: 'lorentz',
            settings: { layoutMode: 'lorentzTree', sourceMode: 'entities' },
        }, 'lorentz');

        expect(settings.layoutMode).toBe('lorentzTree');
        expect(settings.sourceMode).toBe('embeddings');
    });

    it('builds every manifold only while creating the shared packed scene set', () => {
        expect(manifoldPrewarmJobOrder('hopf', true)).toEqual([
            'hopf',
            'hybrid',
            'lorentz',
            'product',
            'siegel',
        ]);
    });

    it('rebuilds only the requested rich projection after packed scenes are resident', () => {
        expect(manifoldPrewarmJobOrder('hopf', false)).toEqual(['hopf']);
    });

    it('binds restart packets to snapshot, generation, scope, manifold, and view receipt', () => {
        const identity = graphCanvasPersistedSceneIdentity({
            id: 'snapshot:a',
            scopeId: 'global',
            authorityContract: { contentHash: 'authority:a' },
        } as any, {
            atlasMode: 'embeddings',
            manifoldMode: 'hopf',
            graphKindFilter: 'all',
            canvasLens: 'entities',
        }, 'hopf');

        expect(identity).toMatchObject({
            scopeId: 'global',
            snapshotId: 'snapshot:a',
            generationId: 'authority:a',
            manifold: 'hopf',
        });
        expect(identity.authorityReceipt).toContain('authority:a');
        expect(identity.authorityReceipt).toContain('hopf');
    });

    it('never expands a compact first-pixel shell into an empty projection', () => {
        const shell = {
            counters: { embeddingTargets: 2 },
            embeddingTargets: [],
        } as any;
        const hydrated = {
            ...shell,
            embeddingTargets: [{ id: 'a' }, { id: 'b' }],
        } as any;

        expect(graphCanvasProjectionPayloadResident(shell)).toBe(false);
        expect(graphCanvasProjectionPayloadResident(hydrated)).toBe(true);
    });

    it('hands a compact shell the exact validated resident scene receipt', () => {
        const snapshot = {
            id: 'snapshot:a',
            scopeId: 'global',
            authorityContract: { contentHash: 'authority:a' },
        } as any;
        const identity = {
            scopeId: 'global',
            snapshotId: 'snapshot:a',
            generationId: 'authority:a',
            manifold: 'hopf',
            authorityReceipt: 'receipt:exact',
        } as const;

        expect(graphCanvasResidentFirstPixelReceipt(identity, snapshot, 'hopf')).toBe('receipt:exact');
        expect(graphCanvasResidentFirstPixelReceipt(identity, snapshot, 'hybrid')).toBeNull();
        expect(graphCanvasResidentFirstPixelReceipt(identity, { ...snapshot, id: 'snapshot:b' }, 'hopf')).toBeNull();
    });
});
