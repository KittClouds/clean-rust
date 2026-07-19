import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import {
    evaluateGalaxyRendererV3Promotion,
    type GalaxyRendererV3PromotionEvidence,
} from './galaxy-renderer-v3-promotion';

describe('Galaxy Renderer V3 isolation', () => {
    it('keeps the WebGPU resource owner independent from legacy renderer and scene objects', () => {
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');

        expect(backend).not.toContain('ThreeGalaxyRenderer');
        expect(backend).not.toContain('three-galaxy-renderer');
        expect(backend).not.toContain('compileGalaxy');
        expect(backend).not.toContain('unpackGalaxyScenePacketV2');
        expect(backend).not.toContain('graph-galaxy-scene-compiler');
    });

    it('contains current-scene compatibility in one named one-way worker membrane', () => {
        const adapter = source('galaxy-renderer-v3-legacy-input-adapter.worker.ts');
        const packetSource = source('galaxy-renderer-v3-packet-source.ts');

        expect(adapter).toContain('buildGalaxyScene');
        expect(adapter).toContain('packGalaxyScenePacketV2');
        expect(packetSource).toContain('galaxy-renderer-v3-legacy-input-adapter.worker');
    });

    it('refuses promotion until every independent proof gate passes', () => {
        const evidence: GalaxyRendererV3PromotionEvidence = {
            packetAuthority: true,
            identityParity: true,
            topologyParity: true,
            visualParity: false,
            interactionParity: false,
            failureIsolation: true,
            performanceBudget: true,
        };

        expect(evaluateGalaxyRendererV3Promotion(evidence)).toEqual({
            promotable: false,
            blockers: ['visualParity', 'interactionParity'],
        });
        expect(evaluateGalaxyRendererV3Promotion({
            ...evidence,
            visualParity: true,
            interactionParity: true,
        })).toEqual({ promotable: true, blockers: [] });
    });
});

function source(file: string): string {
    return readFileSync(new URL(file, import.meta.url), 'utf8');
}
