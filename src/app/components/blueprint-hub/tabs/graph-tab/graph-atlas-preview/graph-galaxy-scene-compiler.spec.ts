import { describe, expect, it } from 'vitest';

import type { PhoenixBackendService } from '../../../../../services/phoenix-backend.service';
import { mergeGalaxySettings, type GalaxyRenderableNode } from './graph-galaxy-engine';
import { compileGalaxyScene } from './graph-galaxy-scene-compiler';

describe('graph galaxy compiled scene cache', () => {
    it('reuses the exact compiled layout for the same render identity', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'a', label: 'A', kind: 'concept' }];
        const settings = mergeGalaxySettings({ layoutMode: 'single' });

        const first = await compileGalaxyScene(backend, entities, [], settings, 'receipt:same');
        const second = await compileGalaxyScene(backend, [...entities], [], settings, 'receipt:same');

        expect(second).toBe(first);
    });

    it('does not reuse a layout when a layout setting changes', async () => {
        const backend = { target: 'web' } as PhoenixBackendService;
        const entities: GalaxyRenderableNode[] = [{ id: 'b', label: 'B', kind: 'concept' }];

        const first = await compileGalaxyScene(backend, entities, [], mergeGalaxySettings({ edgeLength: 1 }), 'receipt:settings');
        const second = await compileGalaxyScene(backend, entities, [], mergeGalaxySettings({ edgeLength: 2 }), 'receipt:settings');

        expect(second).not.toBe(first);
    });
});
