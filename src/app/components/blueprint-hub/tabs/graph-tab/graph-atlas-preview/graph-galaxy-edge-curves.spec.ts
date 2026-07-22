import { describe, expect, it } from 'vitest';

import { setHopfEdgeCurvePoint, type GalaxyCurvePoint } from './graph-galaxy-edge-curves';

describe('galaxy edge curves', () => {
    it('keeps Hopf edge arcs in one bend plane without seeded side wobble', () => {
        const point: GalaxyCurvePoint = { x: 0, y: 0, z: 0 };
        const seed = 0.73;

        for (const t of [0.2, 0.37, 0.63, 0.8]) {
            setHopfEdgeCurvePoint(point, 1, 0, 0, 0, 1, 0, 0.18, t, 1, seed, false);

            const baseX = 1 - t;
            const baseY = t;
            const sideX = -baseY;
            const sideY = baseX;
            const sideLength = Math.hypot(sideX, sideY);
            const sideComponent = (point.x * sideX + point.y * sideY) / sideLength;
            expect(Math.abs(sideComponent)).toBeLessThan(0.000001);
        }
    });
});
