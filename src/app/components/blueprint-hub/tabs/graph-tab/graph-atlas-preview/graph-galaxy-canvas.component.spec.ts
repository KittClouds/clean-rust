import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { mergeGalaxySettings } from './graph-galaxy-engine';
import {
    canGraphGalaxyCanvasHoldSurface,
    galaxyResidencyGenerationId,
    galaxySceneIdentityNeedsRebuild,
    galaxySettingsNeedSceneRebuild,
} from './graph-galaxy-canvas.component';

const here = dirname(fileURLToPath(import.meta.url));

describe('GraphGalaxyCanvasComponent settings rebuild routing', () => {
    it('rebuilds the compiled scene when topology lens changes', () => {
        const previous = mergeGalaxySettings({ embeddingTopologyMode: 'off' });
        const current = mergeGalaxySettings({ embeddingTopologyMode: 'regions' });

        expect(galaxySettingsNeedSceneRebuild(previous, current)).toBe(true);
    });

    it('rebuilds the compiled scene when Atlas source mode changes', () => {
        const previous = mergeGalaxySettings({ sourceMode: 'graph' });
        const current = mergeGalaxySettings({ sourceMode: 'embeddings' });

        expect(galaxySettingsNeedSceneRebuild(previous, current)).toBe(true);
    });

    it('keeps renderer-only settings on the cheap path', () => {
        const previous = mergeGalaxySettings({ labelMode: 'hover' });
        const current = mergeGalaxySettings({ labelMode: 'always' });

        expect(galaxySettingsNeedSceneRebuild(previous, current)).toBe(false);
    });

    it('terminates collection churn when the graph scene identity is unchanged', () => {
        expect(galaxySceneIdentityNeedsRebuild('graph-a', 'graph-a', true)).toBe(false);
        expect(galaxySceneIdentityNeedsRebuild('graph-a', 'graph-b', true)).toBe(true);
        expect(galaxySceneIdentityNeedsRebuild('', '', true)).toBe(true);
    });

    it('keeps graph authority generation separate from manifold scene identity', () => {
        expect(galaxyResidencyGenerationId('generation-a\u0000caps\u0000settings')).toBe('generation-a');
        expect(galaxyResidencyGenerationId('')).toBe('ephemeral-current-graph');
    });

    it('routes renderer scene installation through the bounded residency controller', () => {
        const source = readFileSync(join(here, 'graph-galaxy-canvas.component.ts'), 'utf8');

        expect(source).toContain('new GalaxySceneResidencyController');
        expect(source).toContain('await residency.install');
        expect(source).toContain('this.residency?.updateView(this.renderer.residencyView())');
        expect(source).toContain("import('./graph-galaxy-scene-residency-controller')");
        expect(source).toContain('corpus</b>');
        expect(source).toContain('aggregated</b>');
        expect(source).toContain('scene.layoutMode');
        expect(source).toContain("this.sceneIdentity || 'ephemeral:unreceipted-current-graph'");
        expect(source).toContain('this.queueResidencyCounters(counters)');
        expect(source).toContain('queueMicrotask(() => {');
        expect(source).toContain('this.changeDetector.markForCheck()');
        expect(source).not.toContain('this.residencyCounters = counters');
    });

    it('keeps interaction queries lazy, cancellable, and outside the renderer truth buffers', () => {
        const source = readFileSync(join(here, 'graph-galaxy-canvas.component.ts'), 'utf8');

        expect(source).toContain("import('./graph-galaxy-interaction-query')");
        expect(source).toContain('await interaction.region(');
        expect(source).toContain('await interaction.path(');
        expect(source).toContain('this.renderer.setPathOverlay(overlay)');
        expect(source).toContain('this.interaction?.dispose()');
    });
});

describe('GraphGalaxyCanvasComponent surface lifecycle gate', () => {
    const active = {
        destroyed: false,
        documentVisible: true,
        isVisible: true,
        surfaceActive: true,
    };

    it('allows a WebGL surface only when the document, viewport, and graph panel are active', () => {
        expect(canGraphGalaxyCanvasHoldSurface(active)).toBe(true);
    });

    it('suspends drawing while the graph surface is hidden or inactive', () => {
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, isVisible: false })).toBe(false);
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, surfaceActive: false })).toBe(false);
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, documentVisible: false })).toBe(false);
        expect(canGraphGalaxyCanvasHoldSurface({ ...active, destroyed: true })).toBe(false);
    });

    it('keeps the retained WebGL context across tab suspension and disposes it on teardown', () => {
        const source = readFileSync(join(here, 'graph-galaxy-canvas.component.ts'), 'utf8');
        const suspendBody = source.match(/private suspendSurface\(\): void \{([\s\S]*?)\n    \}/)?.[1] ?? '';
        const destroyBody = source.match(/ngOnDestroy\(\): void \{([\s\S]*?)\n    \}/)?.[1] ?? '';

        expect(suspendBody).toContain('this.stop()');
        expect(suspendBody).not.toContain('releaseContext');
        expect(suspendBody).not.toContain('canvas.width = 0');
        expect(destroyBody).toContain('this.renderer.dispose()');
    });
});
