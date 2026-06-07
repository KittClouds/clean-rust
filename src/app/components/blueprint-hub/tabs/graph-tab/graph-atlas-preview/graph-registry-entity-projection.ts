import { clamp, stableUnit, type GalaxyVec3 } from './graph-galaxy-engine';

export const REGISTRY_ENTITY_PROJECTION_SPACE = 'toroidal-mobius-ladder';

export interface RegistryEntityProjectionInput {
    id: string;
    kind?: string | null;
}

export interface RegistryEntityProjectionPoint extends GalaxyVec3 {
    phase: number;
    band: number;
}

const TAU = Math.PI * 2;

export function registryEntityKindOrder(entities: RegistryEntityProjectionInput[]): Map<string, number> {
    const kinds = Array.from(new Set(
        entities
            .map((entity) => normalizeKind(entity.kind))
            .sort((left, right) => left.localeCompare(right)),
    ));
    return new Map(kinds.map((kind, index) => [kind, index]));
}

export function registryEntityProjectionPoint(
    entity: RegistryEntityProjectionInput,
    index: number,
    total: number,
    kindIndex = 0,
    kindCount = 1,
): RegistryEntityProjectionPoint {
    const safeTotal = Math.max(1, total);
    const safeKindCount = Math.max(1, kindCount);
    const id = entity.id || `entity:${index}`;
    const kind = normalizeKind(entity.kind);
    const offset = stableUnit(`${id}:registry-ribbon-offset`) * 0.34;
    const phase = ((index + offset) / safeTotal) * TAU;
    const kindPhase = ((kindIndex % safeKindCount) / safeKindCount) * TAU;
    const twist = phase * 0.5 + kindPhase;
    const braid = stableUnit(`${id}:registry-ribbon-braid`) * TAU;
    const lane = (kindIndex - (safeKindCount - 1) * 0.5) / Math.max(1, safeKindCount - 1);

    const major = 1.34 + stableUnit(`registry-kind:${kind}:major`) * 0.18;
    const minor = 0.34 + stableUnit(`registry-kind:${kind}:minor`) * 0.15;
    const ribbon = major + minor * Math.cos(twist);
    const harmonic = Math.sin(phase * 3 + braid) * 0.11;
    const ladder = Math.cos(phase * 5 + kindPhase) * 0.055;

    return {
        x: clamp((ribbon + harmonic) * Math.cos(phase) + Math.cos(phase * 2 + braid) * 0.08, -2.25, 2.25),
        y: clamp(minor * Math.sin(twist) * 0.95 + lane * 0.2 + ladder, -1.85, 1.85),
        z: clamp((ribbon - harmonic * 0.5) * Math.sin(phase) + Math.sin(phase * 2 + braid) * 0.08, -2.25, 2.25),
        phase,
        band: lane,
    };
}

function normalizeKind(kind: string | null | undefined): string {
    const normalized = String(kind || 'entity').trim().toLowerCase();
    return normalized || 'entity';
}
