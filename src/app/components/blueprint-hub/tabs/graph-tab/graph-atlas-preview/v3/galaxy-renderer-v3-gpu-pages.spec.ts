import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { galaxyRendererV3GpuCapacity, sceneRadiusFromSquaredBits } from './galaxy-renderer-v3-gpu-pages';

describe('Galaxy Renderer V3 browser-GPU pages', () => {
    it('decodes the compact squared-radius reduction exactly', () => {
        expect(sceneRadiusFromSquaredBits(float32Bits(1))).toBe(1);
        expect(sceneRadiusFromSquaredBits(float32Bits(25))).toBe(5);
        expect(sceneRadiusFromSquaredBits(float32Bits(156.25))).toBe(12.5);
    });

    it('grows persistent GPU pages geometrically', () => {
        expect(galaxyRendererV3GpuCapacity(0)).toBe(1);
        expect(galaxyRendererV3GpuCapacity(179)).toBe(256);
        expect(galaxyRendererV3GpuCapacity(257)).toBe(512);
    });

    it('keeps corpus scans and per-node size expansion out of the backend', () => {
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');
        const gpuPages = source('galaxy-renderer-v3-gpu-pages.ts');

        expect(backend).not.toContain('function sceneRadius');
        expect(backend).not.toContain('scaledNodeSizes');
        expect(backend.indexOf('await this.waitForGpuIdle();')).toBeLessThan(
            backend.indexOf('this.clearResidentObjects();'),
        );
        expect(backend).toContain('onSubmittedWorkDone()');
        expect(backend).toContain('await this.flushRetiredResources();');
        expect(backend).toContain('new GalaxyRendererV3GpuPages(pages.nodeCount, pages)');
        expect(backend).toContain('this.gpuPages?.canFit(pages.nodeCount)');
        expect(backend).toContain('gpuPages.install(pages.nodeCount, pages)');
        expect(backend).toContain('this.disposeRetiredResources(true)');
        expect(gpuPages).toContain('atomicMax');
        expect(gpuPages).toContain('getArrayBufferAsync');
        expect(gpuPages).toContain('new THREE.ReadbackBuffer');
        expect(gpuPages).toContain('readback.release()');
        expect(gpuPages).toContain('new Float32Array(this.capacity * 4)');
        expect(gpuPages).toContain('new Uint8Array(this.capacity * 4)');
        expect(gpuPages).toContain('refreshGalaxyNodePaletteRgba8(');
        expect(gpuPages).toContain('this.nodeColorsAttribute.needsUpdate = true');
        expect(gpuPages).toContain("storage(attribute, 'vec4', count)");
        expect(gpuPages).toContain('.element(instanceIndex).xyz');
        expect(gpuPages).toContain('.mul(1.65).clamp(1.5, 18)');
    });

    it('subscribes V3 to the palette without rebuilding or replacing GPU pages', () => {
        const component = source('graph-galaxy-canvas-v3.component.ts');
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');
        const paletteHandler = component.slice(
            component.indexOf('private readonly unsubscribeColors'),
            component.indexOf('private backendLoad'),
        );

        expect(paletteHandler).toContain('this.backend?.refreshPalette()');
        expect(paletteHandler).not.toContain('queueBuild');
        expect(backend).toContain('this.gpuPages.refreshNodeColors(this.pages)');
        expect(backend).not.toContain('new THREE.InstancedBufferAttribute(pages.nodeColorsRgba8');
    });

    it('updates one prepared overlay allocation instead of constructing attributes per hover', () => {
        const backend = source('galaxy-renderer-v3-webgpu-backend.ts');
        const overlay = source('galaxy-renderer-v3-overlay.ts');

        expect(backend).not.toContain('buildOverlaySurface');
        expect(backend).toContain('this.overlay!.update(this.pages, indexes)');
        expect(overlay).toContain('new Float32Array(this.capacity * 3)');
        expect(overlay).toContain('this.object.count = indexes.size');
    });
});

function float32Bits(value: number): number {
    return new Uint32Array(new Float32Array([value]).buffer)[0];
}

function source(file: string): string {
    return readFileSync(new URL(file, import.meta.url), 'utf8');
}
