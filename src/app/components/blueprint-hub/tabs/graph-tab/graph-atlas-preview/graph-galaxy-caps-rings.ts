import type { GalaxyNode } from './graph-galaxy-engine';
import {
    TAU,
    add,
    clamp,
    hierarchyShellBandForNode,
    laneDirection,
    normalize,
    scale,
    stableUnit,
    tangentFrame,
    type HierarchyShellBand,
    type Vec3,
} from './graph-galaxy-hierarchy-caps';

interface CapsRingInfo {
    id: string;
    capId: string;
    lane: string;
    level: number;
    phase: number;
    targetRadius: number;
    parentCapIds: string[];
}

interface CapsRingCap {
    id: string;
    lane: string;
    center: Vec3;
}

interface ShellRingGroup {
    band: HierarchyShellBand;
    entries: ShellRingEntry[];
}

interface ShellRingEntry {
    index: number;
    info: CapsRingInfo;
}

interface ShellRingSlot {
    aperture: number;
    count: number;
}

export function arrangeEmbeddingShellRings(
    nodes: GalaxyNode[],
    infos: CapsRingInfo[],
    capById: Map<string, CapsRingCap>,
): void {
    const groups = new Map<string, ShellRingGroup>();
    for (let index = 0; index < nodes.length; index++) {
        const band = hierarchyShellBandForNode(nodes[index]);
        if (!band) continue;
        const group = groups.get(band.id) ?? { band, entries: [] };
        group.entries.push({ index, info: infos[index] });
        groups.set(band.id, group);
    }

    for (const group of groups.values()) arrangeShellRingGroup(nodes, group, capById);
}

function arrangeShellRingGroup(
    nodes: GalaxyNode[],
    group: ShellRingGroup,
    capById: Map<string, CapsRingCap>,
): void {
    if (group.entries.length < 2) return;
    group.entries.sort(compareShellEntries);
    const center = shellGroupCenter(group, capById);
    const frame = tangentFrame(center);
    const slots = shellRingSlots(group.entries.length, group.band, group.entries[0].info.level);
    let cursor = 0;

    for (let ring = 0; ring < slots.length; ring++) {
        const slot = slots[ring];
        const phaseOffset = stableUnit(`${group.band.id}:caps-ring:${ring}`);
        const centerWeight = Math.cos(slot.aperture);
        const ringWeight = Math.sin(slot.aperture);
        for (let ordinal = 0; ordinal < slot.count; ordinal++) {
            const entry = group.entries[cursor + ordinal];
            if (!entry) break;
            const phase = (ordinal / Math.max(1, slot.count) + phaseOffset + entry.info.phase * 0.004) % 1;
            const orbit = add(
                scale(frame.a, Math.cos(phase * TAU) * ringWeight),
                scale(frame.b, Math.sin(phase * TAU) * ringWeight),
            );
            const lanePull = scale(laneDirection(entry.info.lane), 0.018);
            const direction = normalize(add(add(scale(center, centerWeight), orbit), lanePull), center);
            const node = nodes[entry.index];
            node.x = direction.x * entry.info.targetRadius;
            node.y = direction.y * entry.info.targetRadius;
            node.z = direction.z * entry.info.targetRadius;
        }
        cursor += slot.count;
    }
}

function compareShellEntries(left: ShellRingEntry, right: ShellRingEntry): number {
    const leftParent = left.info.parentCapIds[0] || left.info.capId;
    const rightParent = right.info.parentCapIds[0] || right.info.capId;
    return leftParent.localeCompare(rightParent)
        || left.info.capId.localeCompare(right.info.capId)
        || left.info.phase - right.info.phase
        || left.info.id.localeCompare(right.info.id);
}

function shellGroupCenter(group: ShellRingGroup, capById: Map<string, CapsRingCap>): Vec3 {
    const lane = shellLaneDirection(group.band.id);
    let sum = { x: 0, y: 0, z: 0 };
    let count = 0;
    for (const entry of group.entries) {
        const cap = capById.get(entry.info.parentCapIds[0] || '') ?? capById.get(entry.info.capId);
        if (!cap) continue;
        sum = add(sum, cap.center);
        count += 1;
    }
    if (!count) return lane;
    const capCenter = normalize(sum, lane);
    return normalize(add(scale(capCenter, 0.82), scale(lane, 0.18)), lane);
}

function shellLaneDirection(bandId: HierarchyShellBand['id']): Vec3 {
    switch (bandId) {
        case 'document': return laneDirection('document');
        case 'documentRoot': return laneDirection('documentRoot');
        case 'chunk': return laneDirection('chunk');
        case 'evidence': return laneDirection('evidence');
        case 'event': return laneDirection('event');
        case 'fact': return laneDirection('relationship');
        case 'entity': return laneDirection('entity');
        case 'memory': return laneDirection('stateContext');
    }
}

function shellRingSlots(count: number, band: HierarchyShellBand, level: number): ShellRingSlot[] {
    const outerAperture = shellRingAperture(count, band, level);
    const spacing = shellCollisionSpacing(band.id);
    const slots: ShellRingSlot[] = [];
    let remaining = count;
    for (let ring = 0; remaining > 0 && ring < 8; ring++) {
        const aperture = innerRingAperture(outerAperture, ring);
        const capacity = shellRingCapacity(band.radius, aperture, spacing);
        const take = Math.min(remaining, capacity);
        slots.push({ aperture, count: take });
        remaining -= take;
    }
    if (remaining > 0 && slots.length) slots[slots.length - 1].count += remaining;
    return slots;
}

function shellRingCapacity(radius: number, aperture: number, spacing: number): number {
    const circumference = TAU * Math.max(0.001, Math.sin(aperture) * radius);
    return Math.max(6, Math.floor(circumference / spacing));
}

function shellCollisionSpacing(bandId: HierarchyShellBand['id']): number {
    switch (bandId) {
        case 'document': return 0.16;
        case 'documentRoot': return 0.14;
        case 'chunk': return 0.105;
        case 'evidence': return 0.092;
        case 'event':
        case 'fact':
        case 'entity': return 0.086;
        case 'memory': return 0.074;
    }
}

function shellRingAperture(count: number, band: HierarchyShellBand, level: number): number {
    const load = Math.min(1, Math.log2(Math.max(3, count)) / 6);
    const levelBoost = Math.min(0.08, Math.max(0, level - 1) * 0.018);
    const base = band.id === 'document' || band.id === 'documentRoot'
        ? 0.32
        : band.id === 'chunk'
            ? 0.38
            : band.id === 'evidence'
                ? 0.44
                : band.id === 'memory'
                    ? 0.58
                    : 0.5;
    return clamp(base + load * 0.18 + levelBoost, 0.28, 0.72);
}

function innerRingAperture(outer: number, ring: number): number {
    if (ring <= 0) return outer;
    const step = clamp(outer * 0.18, 0.08, 0.13);
    return clamp(outer - ring * step, 0.12, outer);
}
