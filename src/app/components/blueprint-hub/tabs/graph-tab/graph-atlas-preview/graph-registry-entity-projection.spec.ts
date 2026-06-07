import { describe, expect, it } from 'vitest';

import {
    registryEntityKindOrder,
    registryEntityProjectionPoint,
    REGISTRY_ENTITY_PROJECTION_SPACE,
} from './graph-registry-entity-projection';

describe('registry entity projection', () => {
    const entities = Array.from({ length: 16 }, (_, index) => ({
        id: `entity-${index}`,
        kind: index < 10 ? 'CHARACTER' : 'LOCATION',
    }));

    it('uses the toroidal mobius ladder projection label', () => {
        expect(REGISTRY_ENTITY_PROJECTION_SPACE).toBe('toroidal-mobius-ladder');
    });

    it('is deterministic and bounded inside the galaxy view volume', () => {
        const kindOrder = registryEntityKindOrder(entities);
        const first = registryEntityProjectionPoint(entities[3], 3, entities.length, kindOrder.get('character'), kindOrder.size);
        const second = registryEntityProjectionPoint(entities[3], 3, entities.length, kindOrder.get('character'), kindOrder.size);

        expect(first).toEqual(second);
        expect(Math.abs(first.x)).toBeLessThanOrEqual(2.25);
        expect(Math.abs(first.y)).toBeLessThanOrEqual(1.85);
        expect(Math.abs(first.z)).toBeLessThanOrEqual(2.25);
    });

    it('spreads registry entities on a twisted toroidal ribbon instead of cube corners', () => {
        const kindOrder = registryEntityKindOrder(entities);
        const points = entities.map((entity, index) => registryEntityProjectionPoint(
            entity,
            index,
            entities.length,
            kindOrder.get(entity.kind.toLowerCase()),
            kindOrder.size,
        ));
        const radii = points.map((point) => Math.hypot(point.x, point.z));
        const roundedRadii = new Set(radii.map((radius) => radius.toFixed(2)));
        const roundedY = new Set(points.map((point) => point.y.toFixed(2)));
        const cornerish = points.filter((point) => Math.abs(Math.abs(point.x) - 2.25) < 0.01 || Math.abs(Math.abs(point.z) - 2.25) < 0.01);

        expect(roundedRadii.size).toBeGreaterThan(5);
        expect(roundedY.size).toBeGreaterThan(8);
        expect(cornerish.length).toBe(0);
    });
});
