import type { GalaxyNode, Rgb } from './graph-galaxy-engine';
import { GRAPH_RELATION_FAMILY_HSL, relationFamilyFromText } from './graph-relation-visual-style';
import { entityColorStore, normalizeGraphNodeColorKind } from '../../../../../lib/store/entityColorStore';

export const TAU = Math.PI * 2;

const CAP_RING_SEGMENTS = 96;

const KIND_HSL: Record<string, string> = {
    identity: '188 80% 66%',
    relationship: '326 76% 66%',
    location: '166 66% 58%',
    event: '42 88% 62%',
    temporal: '260 76% 68%',
    causal: '24 82% 62%',
    evidence: '136 70% 62%',
    document: '214 78% 62%',
    documentRoot: '214 72% 58%',
    documentStructure: '214 78% 62%',
    chunk: '178 66% 58%',
    character: '286 74% 66%',
    entityOther: '184 62% 58%',
    stateContext: '146 72% 56%',
    semantic: '176 72% 58%',
    abstraction: '228 66% 66%',
    bridge: '302 76% 66%',
    outlier: '354 82% 65%',
    ...GRAPH_RELATION_FAMILY_HSL,
};

export interface Vec3 {
    x: number;
    y: number;
    z: number;
}

export interface HierarchyShellBand {
    id: 'document' | 'documentRoot' | 'chunk' | 'entity' | 'event' | 'fact' | 'memory' | 'evidence';
    rank: number;
    radius: number;
    min: number;
    max: number;
}

export type CapsHierarchyRole = HierarchyShellBand['id'];

interface BridgeInfo {
    capId: string;
    lane: string;
    direction: Vec3;
}

export function capBridgeSegments(source: GalaxyNode, target: GalaxyNode, treeKind: string, sourceInfo: BridgeInfo, targetInfo: BridgeInfo): Float32Array {
    const sourcePoint = vectorOf(source);
    const targetPoint = vectorOf(target);
    const sourceDir = normalize(sourcePoint, sourceInfo.direction);
    const targetDir = normalize(targetPoint, targetInfo.direction);
    const bridge = sourceInfo.capId !== targetInfo.capId
        || sourceInfo.lane !== targetInfo.lane
        || /bridge|co.?occur|causal|temporal/.test(treeKind.toLowerCase());
    const lane = laneDirection(treeKind);
    const midDir = normalize(add(add(sourceDir, targetDir), scale(lane, bridge ? 0.42 : 0.18)), lane);
    const midRadius = Math.max(0.5, (length(sourcePoint) + length(targetPoint)) * (bridge ? 0.46 : 0.5));
    return quadraticSegments(sourcePoint, scale(midDir, midRadius), targetPoint, 12);
}

export function capRingSegments(center: Vec3, radius: number, aperture: number): Float32Array {
    const frame = tangentFrame(center);
    const ringRadius = Math.sin(aperture) * radius;
    const centerRadius = Math.cos(aperture) * radius;
    const positions = new Float32Array(CAP_RING_SEGMENTS * 6);
    for (let index = 0; index < CAP_RING_SEGMENTS; index++) {
        const a = (index / CAP_RING_SEGMENTS) * TAU;
        const b = ((index + 1) / CAP_RING_SEGMENTS) * TAU;
        writeVec(positions, index * 6, ringPoint(center, frame, centerRadius, ringRadius, a));
        writeVec(positions, index * 6 + 3, ringPoint(center, frame, centerRadius, ringRadius, b));
    }
    return positions;
}

export function shellRingSegments(radius: number): Float32Array {
    const positions = new Float32Array(3 * CAP_RING_SEGMENTS * 6);
    let cursor = 0;
    for (let plane = 0; plane < 3; plane++) {
        for (let index = 0; index < CAP_RING_SEGMENTS; index++) {
            const a = (index / CAP_RING_SEGMENTS) * TAU;
            const b = ((index + 1) / CAP_RING_SEGMENTS) * TAU;
            cursor = writeRingPoint(positions, cursor, plane, radius, a);
            cursor = writeRingPoint(positions, cursor, plane, radius, b);
        }
    }
    return positions;
}

export function lineSegments(a: Vec3, b: Vec3, steps: number): Float32Array {
    const positions = new Float32Array(steps * 6);
    for (let index = 0; index < steps; index++) {
        writeVec(positions, index * 6, lerp(a, b, index / steps));
        writeVec(positions, index * 6 + 3, lerp(a, b, (index + 1) / steps));
    }
    return positions;
}

export function rawDirection(node: GalaxyNode, lorentz: Record<string, unknown>): Vec3 {
    const cap = lorentz['capDirection'];
    if (Array.isArray(cap) && cap.length >= 3) return normalize({ x: finite(cap[0]), y: finite(cap[1]), z: finite(cap[2]) }, stableVector(node.entity.id));
    const klein = lorentz['klein'];
    if (Array.isArray(klein) && klein.length >= 3) return normalize({ x: finite(klein[0]), y: finite(klein[1]), z: finite(klein[2]) }, stableVector(node.entity.id));
    return normalize({ x: node.x, y: node.y, z: node.z }, stableVector(node.entity.id));
}

export function laneDirection(lane: string): Vec3 {
    switch (normalizeLane(lane)) {
        case 'document':
        case 'documentRoot':
        case 'documentStructure':
            return normalize({ x: -0.3, y: 0.18, z: 0.94 }, { x: 0, y: 0, z: 1 });
        case 'chunk':
            return normalize({ x: -0.24, y: 0.62, z: 0.74 }, { x: 0, y: 1, z: 0 });
        case 'temporal':
            return normalize({ x: 0.2, y: 0.88, z: -0.28 }, { x: 0, y: 1, z: 0 });
        case 'causal':
            return normalize({ x: 0.86, y: -0.24, z: 0.34 }, { x: 1, y: 0, z: 0 });
        case 'event':
            return normalize({ x: 0.54, y: 0.36, z: -0.76 }, { x: 0, y: 0, z: -1 });
        case 'evidence':
            return normalize({ x: -0.58, y: -0.1, z: 0.8 }, { x: -1, y: 0, z: 0 });
        case 'location':
            return normalize({ x: 0.14, y: 0.74, z: 0.66 }, { x: 0, y: 1, z: 0 });
        case 'character':
            return normalize({ x: 0.36, y: 0.34, z: -0.86 }, { x: 0, y: 0, z: -1 });
        case 'relationship':
            return normalize({ x: 0.56, y: -0.62, z: -0.2 }, { x: 1, y: -1, z: 0 });
        case 'stateContext':
            return normalize({ x: 0.52, y: -0.18, z: -0.84 }, { x: 1, y: 0, z: -1 });
        case 'entity':
        case 'entityOther':
            return normalize({ x: -0.62, y: 0.58, z: 0.22 }, { x: -1, y: 1, z: 0 });
        default:
            return normalize({ x: 0.18, y: 0.48, z: 0.86 }, { x: 0, y: 0, z: 1 });
    }
}

export function temporalRingDirection(phase: number): Vec3 {
    return normalize({ x: Math.cos(phase * TAU), y: 0.2, z: Math.sin(phase * TAU) }, { x: 1, y: 0, z: 0 });
}

export function causalConeDirection(phase: number, level: number): Vec3 {
    const cone = clamp(0.18 + level * 0.08, 0.18, 0.48);
    return normalize({ x: 1, y: Math.cos(phase * TAU) * cone, z: Math.sin(phase * TAU) * cone }, { x: 1, y: 0, z: 0 });
}

export function documentTreeDirection(phase: number, level: number): Vec3 {
    const branch = clamp(0.12 + level * 0.1, 0.12, 0.46);
    return normalize({ x: Math.cos(phase * TAU) * branch, y: 0.18 * level, z: 1 }, { x: 0, y: 0, z: 1 });
}

export function fallbackLane(node: GalaxyNode): string {
    const text = `${node.entity.kind || ''} ${node.entity.metadata?.sourceType || ''} ${node.entity.label || ''}`.toLowerCase();
    const relation = relationFamilyFromText(text, node.entity.metadata?.['preview']);
    if (relation) return relation;
    if (/causal|cause|effect/.test(text)) return 'causal';
    if (/temporal|timeline|time/.test(text)) return 'temporal';
    if (/event|scene/.test(text)) return 'event';
    if (/decision|rank|service|affiliation|affiliate|family-context|memory|state/.test(text)) return 'stateContext';
    if (/memory|evidence|source|provenance/.test(text)) return 'evidence';
    if (/relationship|relation|graph-fact|graphfact|fact/.test(text)) return 'relationship';
    if (/chunk|anchor|note|document|doc/.test(text)) return 'document';
    if (/entity|character|location|creature|concept/.test(text)) return 'entity';
    return 'semantic';
}

export function derivedRole(node: GalaxyNode): string {
    const outlier = finite(node.entity.metadata?.['embeddingOutlierScore']);
    const hub = finite(node.entity.metadata?.['embeddingHubScore']);
    if (outlier > 0.74) return 'outlier';
    if (hub > 0.7) return 'core';
    return '';
}

export function dominantLane(weights: Record<string, number>): string {
    let best = '';
    let value = -Infinity;
    for (const [lane, weight] of Object.entries(weights)) {
        if (weight > value) {
            best = lane;
            value = weight;
        }
    }
    return best;
}

export function normalizeLane(value: string): string {
    const lane = String(value || '').trim();
    if (lane === 'timeline') return 'temporal';
    if (lane === 'relation') return 'relationship';
    if (lane === 'identity') return 'entity';
    if (lane === 'document_structure') return 'documentStructure';
    return lane || 'semantic';
}

export function pullPair(source: GalaxyNode, target: GalaxyNode, ideal: number, strength: number): void {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const dz = target.z - source.z;
    const distance = Math.max(0.001, Math.hypot(dx, dy, dz));
    const force = (distance - ideal) * strength;
    const x = dx / distance * force;
    const y = dy / distance * force;
    const z = dz / distance * force;
    source.x += x; source.y += y; source.z += z;
    target.x -= x; target.y -= y; target.z -= z;
}

export function projectNodeToRadius(node: GalaxyNode, radius: number): void {
    const direction = normalize(vectorOf(node), stableVector(node.entity.id));
    node.x = direction.x * radius;
    node.y = direction.y * radius;
    node.z = direction.z * radius;
}

export function contractShellRadiusForNode(node: GalaxyNode, fallback: number): number {
    const band = hierarchyShellBandForNode(node);
    return band ? clamp(fallback || band.radius, band.min, band.max) : fallback;
}

export function enforceHierarchyShellContract(nodes: GalaxyNode[]): void {
    for (const node of nodes) {
        const band = hierarchyShellBandForNode(node);
        if (!band) continue;
        const radius = contractShellRadiusForNode(node, length(vectorOf(node)) || band.radius);
        projectNodeToRadius(node, radius);
        node.depth = clamp(radius / 2.18, 0, 1);
    }
}

export function validateHierarchyShellContract(nodes: GalaxyNode[]): string[] {
    const violations: string[] = [];
    for (const node of nodes) {
        const band = hierarchyShellBandForNode(node);
        if (!band) continue;
        const radius = length(vectorOf(node));
        if (radius < band.min - 0.0001 || radius > band.max + 0.0001) {
            violations.push(`${node.entity.id}:${band.id}:radius:${radius.toFixed(3)} not in ${band.min}-${band.max}`);
        }
    }
    return violations;
}

export function hierarchyShellBandForNode(node: GalaxyNode): HierarchyShellBand | null {
    const explicit = explicitHierarchyRoleForNode(node);
    if (explicit) return HIERARCHY_SHELL_BANDS[explicit];
    const text = hierarchyKindText(node);
    if (/embed:note:|source:note|kind:note|document(?!_spine)|source:doc|kind:doc/.test(text)) {
        return HIERARCHY_SHELL_BANDS.document;
    }
    if (/embed:structure-root:|structure.?root|document.?root|lane.?root/.test(text)) {
        return HIERARCHY_SHELL_BANDS.documentRoot;
    }
    if (/embed:anchor:|anchor_evidence|source:anchor|kind:anchor|evidence|mention|provenance/.test(text)) {
        return HIERARCHY_SHELL_BANDS.evidence;
    }
    if (/embed:chunk:|source:chunk|kind:chunk|chunk_spine/.test(text)) {
        return HIERARCHY_SHELL_BANDS.chunk;
    }
    if (/memory_state|memory|state|context|rank.?status|service|affiliation/.test(text)) {
        return HIERARCHY_SHELL_BANDS.memory;
    }
    if (/event_identity|source:event|kind:event|temporal_fact|causal_fact|temporal|causal/.test(text)) {
        return HIERARCHY_SHELL_BANDS.event;
    }
    if (/relationship_fact|graph.?fact|relation.?fact|relationship|relation/.test(text)) {
        return HIERARCHY_SHELL_BANDS.fact;
    }
    if (/embed:entity:|entity_anchor|source:entity|kind:entity|character|location|creature|concept/.test(text)) {
        return HIERARCHY_SHELL_BANDS.entity;
    }
    return null;
}

export function hierarchyShellBandForRole(role: string | null | undefined): HierarchyShellBand | null {
    const normalized = normalizeHierarchyRole(role);
    return normalized ? HIERARCHY_SHELL_BANDS[normalized] : null;
}

export function hierarchyShellBandsInOrder(): HierarchyShellBand[] {
    return HIERARCHY_SHELL_ORDER.map((role) => HIERARCHY_SHELL_BANDS[role]);
}

export function vectorOf(node: GalaxyNode): Vec3 {
    return { x: node.x, y: node.y, z: node.z };
}

export function add(left: Vec3, right: Vec3): Vec3 {
    return { x: left.x + right.x, y: left.y + right.y, z: left.z + right.z };
}

export function scale(value: Vec3, amount: number): Vec3 {
    return { x: value.x * amount, y: value.y * amount, z: value.z * amount };
}

export function normalize(value: Vec3, fallback: Vec3): Vec3 {
    const norm = length(value);
    if (norm > 0.0001) return { x: value.x / norm, y: value.y / norm, z: value.z / norm };
    return fallback;
}

export function length(value: Vec3): number {
    return Math.hypot(value.x, value.y, value.z);
}

export function record(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function numberRecord(value: unknown): Record<string, number> {
    const raw = record(value);
    const out: Record<string, number> = {};
    for (const [key, item] of Object.entries(raw)) out[key] = finite(item);
    return out;
}

export function firstText(...values: unknown[]): string {
    for (const value of values) {
        const text = typeof value === 'string' ? value.trim() : '';
        if (text) return text;
    }
    return '';
}

export function firstNumber(...values: unknown[]): number {
    for (const value of values) {
        const number = Number(value);
        if (Number.isFinite(number)) return number;
    }
    return 0;
}

export function rgbForKind(kind: string): Rgb {
    const graphNodeKind = normalizeGraphNodeColorKind(kind);
    if (graphNodeKind) return hslToRgb(entityColorStore.getRawGraphNodeHsl(graphNodeKind));
    return hslToRgb(KIND_HSL[kind] ?? '198 74% 64%');
}

export function stableUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}

export function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

export function finite(value: unknown): number {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
}

export const HIERARCHY_SHELL_BANDS: Record<HierarchyShellBand['id'], HierarchyShellBand> = {
    document: { id: 'document', rank: 0, radius: 2.1, min: 2.04, max: 2.14 },
    documentRoot: { id: 'documentRoot', rank: 1, radius: 1.78, min: 1.7, max: 1.86 },
    chunk: { id: 'chunk', rank: 2, radius: 1.46, min: 1.38, max: 1.54 },
    evidence: { id: 'evidence', rank: 3, radius: 1.14, min: 1.06, max: 1.22 },
    entity: { id: 'entity', rank: 4, radius: 0.86, min: 0.76, max: 0.94 },
    event: { id: 'event', rank: 5, radius: 0.7, min: 0.62, max: 0.78 },
    fact: { id: 'fact', rank: 6, radius: 0.66, min: 0.58, max: 0.74 },
    memory: { id: 'memory', rank: 7, radius: 0.52, min: 0.42, max: 0.62 },
};

export const HIERARCHY_SHELL_ORDER: readonly CapsHierarchyRole[] = [
    'document',
    'documentRoot',
    'chunk',
    'evidence',
    'entity',
    'event',
    'fact',
    'memory',
];

function explicitHierarchyRoleForNode(node: GalaxyNode): CapsHierarchyRole | null {
    const metadata = node.entity.metadata || {};
    const lorentz = record(metadata['lorentz']);
    return normalizeHierarchyRole(
        metadata['capsHierarchyRole']
            || metadata['hierarchyRole']
            || lorentz['capsHierarchyRole']
            || lorentz['hierarchyRole'],
    );
}

function normalizeHierarchyRole(value: unknown): CapsHierarchyRole | null {
    const text = String(value || '').trim().replace(/[-_\s]+/g, '').toLowerCase();
    switch (text) {
        case 'document':
        case 'note':
        case 'doc':
            return 'document';
        case 'documentroot':
        case 'root':
        case 'structureroot':
            return 'documentRoot';
        case 'chunk':
        case 'documentunit':
            return 'chunk';
        case 'evidence':
        case 'anchor':
        case 'evidencespan':
            return 'evidence';
        case 'entity':
        case 'identity':
            return 'entity';
        case 'event':
            return 'event';
        case 'fact':
        case 'graphfact':
        case 'relationshipfact':
            return 'fact';
        case 'memory':
        case 'memorystate':
        case 'state':
        case 'context':
            return 'memory';
        default:
            return null;
    }
}

function hierarchyKindText(node: GalaxyNode): string {
    const metadata = node.entity.metadata || {};
    const lorentz = record(metadata['lorentz']);
    return [
        node.entity.id,
        `kind:${node.entity.kind || ''}`,
        `source:${metadata['sourceType'] || ''}`,
        metadata['signalLane'],
        lorentz['signalLane'],
        metadata['signalStructuralRole'],
        lorentz['structuralRole'],
        metadata['atlasStructuralRole'],
        metadata['atlasDocumentUnitKind'],
        metadata['atlasStateContextKind'],
        metadata['styleKey'],
        metadata['graphKind'],
        metadata['graphColorKind'],
    ].join(' ').toLowerCase();
}

function quadraticSegments(a: Vec3, b: Vec3, c: Vec3, steps: number): Float32Array {
    const positions = new Float32Array(steps * 6);
    for (let index = 0; index < steps; index++) {
        writeQuadratic(positions, index * 6, a, b, c, index / steps);
        writeQuadratic(positions, index * 6 + 3, a, b, c, (index + 1) / steps);
    }
    return positions;
}

export function tangentFrame(direction: Vec3): { a: Vec3; b: Vec3 } {
    const pole = Math.abs(direction.y) > 0.82 ? { x: 1, y: 0, z: 0 } : { x: 0, y: 1, z: 0 };
    const a = normalize(cross(direction, pole), { x: 1, y: 0, z: 0 });
    return { a, b: normalize(cross(direction, a), { x: 0, y: 0, z: 1 }) };
}

function ringPoint(center: Vec3, frame: { a: Vec3; b: Vec3 }, centerRadius: number, ringRadius: number, angle: number): Vec3 {
    return add(scale(center, centerRadius), add(scale(frame.a, Math.cos(angle) * ringRadius), scale(frame.b, Math.sin(angle) * ringRadius)));
}

function writeRingPoint(buffer: Float32Array, cursor: number, plane: number, radius: number, angle: number): number {
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle) * radius;
    if (plane === 0) buffer.set([x, y, 0], cursor);
    else if (plane === 1) buffer.set([x, 0, y], cursor);
    else buffer.set([0, x, y], cursor);
    return cursor + 3;
}

function writeQuadratic(buffer: Float32Array, offset: number, a: Vec3, b: Vec3, c: Vec3, t: number): void {
    const left = (1 - t) * (1 - t);
    const mid = 2 * (1 - t) * t;
    const right = t * t;
    buffer[offset] = left * a.x + mid * b.x + right * c.x;
    buffer[offset + 1] = left * a.y + mid * b.y + right * c.y;
    buffer[offset + 2] = left * a.z + mid * b.z + right * c.z;
}

function writeVec(buffer: Float32Array, offset: number, value: Vec3): void {
    buffer[offset] = value.x;
    buffer[offset + 1] = value.y;
    buffer[offset + 2] = value.z;
}

function lerp(left: Vec3, right: Vec3, t: number): Vec3 {
    return { x: left.x + (right.x - left.x) * t, y: left.y + (right.y - left.y) * t, z: left.z + (right.z - left.z) * t };
}

function cross(left: Vec3, right: Vec3): Vec3 {
    return {
        x: left.y * right.z - left.z * right.y,
        y: left.z * right.x - left.x * right.z,
        z: left.x * right.y - left.y * right.x,
    };
}

function hslToRgb(rawHsl: string): Rgb {
    const values = rawHsl.match(/-?\d+(?:\.\d+)?/g)?.map((part) => Number(part)) ?? [];
    const [h = 190, s = 70, l = 55] = values;
    const hue = ((h % 360) + 360) % 360;
    const saturation = clamp(s / 100, 0, 1);
    const lightness = clamp(l / 100, 0, 1);
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const x = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
    const match = lightness - chroma / 2;
    const [red, green, blue] = hue < 60 ? [chroma, x, 0] : hue < 120 ? [x, chroma, 0] : hue < 180 ? [0, chroma, x] : hue < 240 ? [0, x, chroma] : hue < 300 ? [x, 0, chroma] : [chroma, 0, x];
    return { r: Math.round((red + match) * 255), g: Math.round((green + match) * 255), b: Math.round((blue + match) * 255) };
}

function stableVector(id: string): Vec3 {
    const a = stableUnit(`${id}:a`) * TAU;
    const y = stableUnit(`${id}:y`) * 2 - 1;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    return { x: Math.cos(a) * radial, y, z: Math.sin(a) * radial };
}
