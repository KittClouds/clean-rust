import { describe, expect, it } from 'vitest';

import {
    graphCanvasPrewarmSettings,
    manifoldPrewarmOrder,
} from './graph-canvas-cold-start.service';

describe('GraphCanvasColdStartService', () => {
    it('warms only the requested manifold instead of multiplying expanded graph state', () => {
        expect(manifoldPrewarmOrder('lorentz')).toEqual(['lorentz']);
    });

    it('uses the same source-normalized settings key as the embeddings canvas', () => {
        const settings = graphCanvasPrewarmSettings({
            manifoldMode: 'lorentz',
            settings: { layoutMode: 'lorentzTree', sourceMode: 'entities' },
        }, 'lorentz');

        expect(settings.layoutMode).toBe('lorentzTree');
        expect(settings.sourceMode).toBe('embeddings');
    });
});
