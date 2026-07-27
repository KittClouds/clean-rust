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

    it('never disposes the quad geometry shared by Three.js sprites', () => {
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');

        expect(backend).toContain('if (!(drawable instanceof THREE.Sprite)) drawable.geometry?.dispose();');
    });

    it('applies presentation settings in place and recompiles geometry settings', () => {
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');
        const component = source('graph-galaxy-canvas-v3.component.ts');
        const settingsBody = backend.slice(backend.indexOf('setSettings('), backend.indexOf('setMode('));

        expect(settingsBody).not.toContain('openGeneration');
        expect(settingsBody).toContain('syncEdgePresentation');
        expect(settingsBody).toContain('syncGalaxyRendererV3GuidePresentation');
        expect(component).toContain("this.backend?.setSettings(this.currentSettings())");
        expect(component).toContain('galaxyRendererV3SettingsRequireCompilation(');
        expect(component).toContain('settingsRequireCompilation');
    });

    it('restores displaced presentation rows only for stretch mode', () => {
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');

        expect(backend).toContain("this.settings.nodeDragMode === 'stretch'");
        expect(backend).toContain('restoreGalaxyRendererV3Positions(');
    });

    it('contains current-scene compatibility in one named one-way worker membrane', () => {
        const adapter = source('galaxy-renderer-v3-legacy-input-adapter.worker.ts');
        const packetSource = source('galaxy-renderer-v3-packet-source.ts');

        expect(adapter).toContain('buildGalaxyScene');
        expect(adapter).toContain('packGalaxyScenePacketV2');
        expect(packetSource).toContain('galaxy-renderer-v3-legacy-input-adapter.worker');
    });

    it('keeps whole-packet JSON expansion and rehashing out of the V3 hot path', () => {
        const packet = source('../graph-galaxy-scene-packet-v2.ts');
        const packetView = source('galaxy-renderer-v3-packet-view.ts');

        expect(packet).not.toContain('detail/scene-extras');
        expect(packet).not.toContain('typedArrayReplacer');
        expect(packetView).not.toContain('assertGalaxyScenePacketV2');
        expect(packetView).toContain('VerifiedGalaxyScenePacketV2');
        expect(packetView).toContain('openGalaxyScenePacketV2Page');
    });

    it('keeps the V3 surface mounted while an authoritative manifold is preparing', () => {
        const preview = source('../graph-atlas-preview.component.ts');
        const component = source('graph-galaxy-canvas-v3.component.ts');

        expect(preview).toContain('activeNodeCount() === 0 && !graphProjectionPreparing()');
        expect(preview).toContain('this.activeNodeCount() > 0 || this.graphProjectionPreparing()');
        expect(preview).toContain('graphProjectionRequired && !graphSnapshotHasHydratedCanvasPayload(snapshot)');
        const packedBranch = preview.slice(
            preview.indexOf('graphProjectionRequired && !graphSnapshotHasHydratedCanvasPayload(snapshot)'),
            preview.indexOf("if (!force && this.atlasLoadingKeys.get(manifold)"),
        );
        expect(packedBranch).not.toContain('metadataRequested.emit');
        expect(packedBranch).toContain('this.machine.failManifoldLoad(load, error)');
        expect(component).toContain("this.sourceMode === 'embeddings' && this.sceneIdentity");
        expect(component).not.toContain("this.sourceMode === 'embeddings' && this.sceneIdentity && this.entities.length === 0");
        expect(component).toContain('this.entityByIdentity.get(identity)');
        expect(component).toContain('this.packetSource.waitForResident(authorityReceipt, generationId, this.sourceMode');
        expect(component).toContain('await this.ensureMounted(backend);');
        expect(component).toContain('this.firstPixelRendered.emit(this.sceneIdentity);');
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
