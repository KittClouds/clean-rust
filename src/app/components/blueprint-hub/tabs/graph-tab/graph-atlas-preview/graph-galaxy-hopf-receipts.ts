import type { GalaxyHopfRibbon } from './graph-galaxy-engine';

type Vec3 = { x: number; y: number; z: number };
type Rgb = { r: number; g: number; b: number };

export interface HopfReceiptBase {
    key: string;
    direction: Vec3;
    phases: number[];
    nodeIds: string[];
    secondaryCellIds: string[];
    fiberKinds: string[];
    importance: number;
    backendReceiptCount: number;
    documentChartCount: number;
    color: Rgb;
}

const TAU = Math.PI * 2;
const HOPF_PROJECTION_RADIUS = 0.88;
const HOPF_MAX_RADIUS = 2.05;
const RING_SEGMENTS = 96;
const BRAID_SEGMENTS = 44;
const CELL_RING_LIMIT = 64;
const DOC_CHART_LIMIT = 12;
const RECEIPT_BRAID_LIMIT = 96;

export function buildHopfReceiptRibbons(bases: HopfReceiptBase[]): GalaxyHopfRibbon[] {
    const receiptBases = bases
        .filter((base) => base.backendReceiptCount > 0)
        .sort((left, right) => right.importance - left.importance || left.key.localeCompare(right.key));
    if (!receiptBases.length) return [];
    return [
        ...buildCellRings(receiptBases),
        ...buildDocumentChartBands(receiptBases),
        ...buildReceiptBraids(receiptBases),
        ...buildReceiptAxes(receiptBases.length),
    ];
}

export function hopfDirectionFromMetadata(value: unknown): Vec3 | null {
    if (!Array.isArray(value) || value.length < 3) return null;
    const x = Number(value[0]);
    const y = Number(value[1]);
    const z = Number(value[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
    return normalize({ x, y, z }, null);
}

function buildCellRings(bases: HopfReceiptBase[]): GalaxyHopfRibbon[] {
    return bases.slice(0, CELL_RING_LIMIT).map((base): GalaxyHopfRibbon => ({
        id: `hopf:cell-ring:${base.key}`,
        nodeIds: unique(base.nodeIds),
        positions3d: hopfRingSegments(base.direction, base.phases, 0.94),
        importance: base.importance * 0.48,
        guideKind: 'spaceFiber',
        guideWeight: 0.3 + Math.min(0.52, base.backendReceiptCount * 0.015),
        ...base.color,
    }));
}

function buildDocumentChartBands(bases: HopfReceiptBase[]): GalaxyHopfRibbon[] {
    return bases
        .filter((base) => base.documentChartCount > 0 || base.fiberKinds.includes('document_chart'))
        .slice(0, DOC_CHART_LIMIT)
        .map((base): GalaxyHopfRibbon => ({
            id: `hopf:doc-chart:${base.key}`,
            nodeIds: unique(base.nodeIds),
            positions3d: hopfRingSegments(base.direction, base.phases, 1.04),
            importance: base.importance * 0.82 + base.documentChartCount,
            guideKind: 'torusBand',
            guideWeight: 0.54 + Math.min(0.36, base.documentChartCount * 0.08),
            ...base.color,
        }));
}

function buildReceiptBraids(bases: HopfReceiptBase[]): GalaxyHopfRibbon[] {
    const byKey = new Map(bases.map((base) => [base.key, base]));
    const seen = new Set<string>();
    const braids: GalaxyHopfRibbon[] = [];
    for (const source of bases) {
        for (const targetKey of source.secondaryCellIds) {
            const target = byKey.get(targetKey);
            if (!target || target.key === source.key) continue;
            const pairKey = source.key < target.key ? `${source.key}|${target.key}` : `${target.key}|${source.key}`;
            if (seen.has(pairKey)) continue;
            seen.add(pairKey);
            braids.push({
                id: `hopf:receipt-braid:${pairKey.replace(/[^a-z0-9_-]+/gi, '-')}`,
                nodeIds: unique([...source.nodeIds.slice(0, 4), ...target.nodeIds.slice(0, 4)]),
                positions3d: hopfDirectionBraidSegments(source.direction, target.direction, stableUnit(pairKey)),
                importance: Math.min(source.importance, target.importance),
                guideKind: 'crossFiberBraid',
                guideWeight: 0.34 + Math.min(0.22, (source.backendReceiptCount + target.backendReceiptCount) * 0.006),
                r: Math.round((source.color.r + target.color.r) * 0.5),
                g: Math.round((source.color.g + target.color.g) * 0.5),
                b: Math.round((source.color.b + target.color.b) * 0.5),
            });
            if (braids.length >= RECEIPT_BRAID_LIMIT) return braids;
        }
    }
    return braids.sort((left, right) => right.importance - left.importance || left.id.localeCompare(right.id));
}

function buildReceiptAxes(seedCount: number): GalaxyHopfRibbon[] {
    const axes: Array<[string, Vec3, Rgb]> = [
        ['x', { x: 1, y: 0, z: 0 }, { r: 64, g: 232, b: 221 }],
        ['y', { x: 0, y: 1, z: 0 }, { r: 189, g: 126, b: 255 }],
        ['z', { x: 0, y: 0, z: 1 }, { r: 255, g: 194, b: 86 }],
    ];
    return axes.map(([axis, direction, color], index): GalaxyHopfRibbon => ({
        id: `hopf:receipt-axis:${axis}:${seedCount}`,
        nodeIds: [],
        positions3d: hopfRingSegments(direction, [index / axes.length], 0.9),
        importance: 0.2,
        guideKind: 'axis',
        guideWeight: 0.14,
        ...color,
    }));
}

function hopfRingSegments(direction: Vec3, phases: number[], scale: number): Float32Array {
    const phaseSet = new Set<number>();
    for (let index = 0; index < RING_SEGMENTS; index++) {
        phaseSet.add(roundPhase((index / RING_SEGMENTS) * TAU));
    }
    for (const phase of phases) phaseSet.add(roundPhase(phase));
    const samples = [...phaseSet].sort((left, right) => left - right);
    const positions = new Float32Array(samples.length * 2 * 3);
    for (let index = 0; index < samples.length; index++) {
        const current = hopfStereographicProjection(direction, samples[index], scale);
        const next = hopfStereographicProjection(direction, samples[(index + 1) % samples.length], scale);
        writeSegment(positions, index * 6, current, next);
    }
    return positions;
}

function hopfDirectionBraidSegments(source: Vec3, target: Vec3, seed: number): Float32Array {
    const positions = new Float32Array(BRAID_SEGMENTS * 2 * 3);
    for (let index = 0; index < BRAID_SEGMENTS; index++) {
        const a = index / BRAID_SEGMENTS;
        const b = (index + 1) / BRAID_SEGMENTS;
        writeSegment(positions, index * 6, braidPoint(source, target, a, seed), braidPoint(source, target, b, seed));
    }
    return positions;
}

function braidPoint(source: Vec3, target: Vec3, t: number, seed: number): Vec3 {
    const normal = braidNormal(source, target, seed);
    const sweep = Math.sin(Math.PI * t);
    const twist = Math.sin(TAU * t + seed * TAU) * 0.08 * sweep;
    const mixed = normalize({
        x: source.x * (1 - t) + target.x * t + normal.x * (0.22 + seed * 0.12) * sweep,
        y: source.y * (1 - t) + target.y * t + normal.y * (0.22 + seed * 0.12) * sweep,
        z: source.z * (1 - t) + target.z * t + normal.z * (0.22 + seed * 0.12) * sweep,
    }, source) || source;
    return hopfStereographicProjection(mixed, TAU * (t + twist), 1.02 + 0.12 * sweep);
}

function braidNormal(source: Vec3, target: Vec3, seed: number): Vec3 {
    const cross = {
        x: source.y * target.z - source.z * target.y,
        y: source.z * target.x - source.x * target.z,
        z: source.x * target.y - source.y * target.x,
    };
    const fallback = stableVector(`hopf-receipt-braid:${seed.toFixed(5)}`);
    return normalize(cross, fallback) || fallback;
}

function hopfStereographicProjection(direction: Vec3, phase: number, scale: number): Vec3 {
    const eta = Math.acos(clamp(direction.y, -1, 1));
    const phi = Math.atan2(direction.z, direction.x);
    const halfEta = eta * 0.5;
    const plus = (phi + phase) * 0.5;
    const minus = (phi - phase) * 0.5;
    const cosEta = Math.cos(halfEta);
    const sinEta = Math.sin(halfEta);
    const x1 = cosEta * Math.cos(plus);
    const y1 = cosEta * Math.sin(plus);
    const x2 = sinEta * Math.cos(minus);
    const y2 = sinEta * Math.sin(minus);
    const inverse = 1 / Math.max(0.32, 1 - y2);
    const raw = { x: x1 * inverse, y: x2 * inverse, z: y1 * inverse };
    const norm = Math.hypot(raw.x, raw.y, raw.z);
    const bound = norm > 0.0001 ? hopfCompactRadius(norm) / norm : 1;
    return {
        x: raw.x * bound * HOPF_PROJECTION_RADIUS * scale,
        y: raw.y * bound * HOPF_PROJECTION_RADIUS * scale,
        z: raw.z * bound * HOPF_PROJECTION_RADIUS * scale,
    };
}

function hopfCompactRadius(norm: number): number {
    const knee = HOPF_MAX_RADIUS * 0.76;
    if (norm <= knee) return norm;
    const remaining = HOPF_MAX_RADIUS - knee;
    return knee + remaining * (1 - Math.exp(-(norm - knee) / Math.max(0.0001, remaining)));
}

function writeSegment(positions: Float32Array, offset: number, left: Vec3, right: Vec3): void {
    positions[offset] = left.x;
    positions[offset + 1] = left.y;
    positions[offset + 2] = left.z;
    positions[offset + 3] = right.x;
    positions[offset + 4] = right.y;
    positions[offset + 5] = right.z;
}

function normalize(value: Vec3, fallback: Vec3 | null): Vec3 | null {
    const norm = Math.hypot(value.x, value.y, value.z);
    if (norm > 0.0001) return { x: value.x / norm, y: value.y / norm, z: value.z / norm };
    return fallback;
}

function stableVector(id: string): Vec3 {
    const a = stableUnit(`${id}:a`) * TAU;
    const y = stableUnit(`${id}:y`) * 2 - 1;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    return { x: Math.cos(a) * radial, y, z: Math.sin(a) * radial };
}

function stableUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}

function roundPhase(value: number): number {
    return Math.round((((value % TAU) + TAU) % TAU) * 1000000) / 1000000;
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))];
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}
