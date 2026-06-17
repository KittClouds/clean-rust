import type { GalaxyEdge, GalaxyLorentzGuide, GalaxyNode, Rgb } from './graph-galaxy-engine';
import { relationFamilyFromText } from './graph-relation-visual-style';
import {
    TAU,
    add,
    capBridgeSegments,
    capRingSegments,
    causalConeDirection,
    clamp,
    contractShellRadiusForNode,
    derivedRole,
    documentTreeDirection,
    dominantLane,
    enforceHierarchyShellContract,
    fallbackLane,
    finite,
    firstNumber,
    firstText,
    laneDirection,
    length,
    lineSegments,
    normalize,
    normalizeLane,
    numberRecord,
    projectNodeToRadius,
    pullPair,
    rawDirection,
    record,
    rgbForKind,
    scale,
    shellRingSegments,
    stableUnit,
    tangentFrame,
    temporalRingDirection,
    vectorOf,
    type Vec3,
} from './graph-galaxy-hierarchy-caps';

const CAP_SCENE_RADIUS = 2.18;
const MAX_CAP_GUIDES = 40;
const MAX_MEMBERSHIP_GUIDES = 260;

interface CapInfo extends Rgb {
    id: string;
    lane: string;
    parentIds: string[];
    center: Vec3;
    indexes: number[];
    radiusSum: number;
    ambiguitySum: number;
    importance: number;
}

interface HierarchyInfo {
    id: string;
    capId: string;
    lane: string;
    role: string;
    treeKind: string;
    level: number;
    phase: number;
    specificity: number;
    ambiguity: number;
    targetRadius: number;
    direction: Vec3;
    parentCapIds: string[];
    confidence: number;
}

export function applyLorentzTreeLayout(nodes: GalaxyNode[], links: GalaxyEdge[], options: { productTopologyGeometry?: boolean } = {}): GalaxyLorentzGuide[] {
    void options;
    if (!nodes.length) return [];

    const infos = nodes.map(hierarchyInfo);
    const caps = buildCaps(nodes, infos);
    const capById = new Map(caps.map((cap) => [cap.id, cap]));

    for (let index = 0; index < nodes.length; index++) {
        const node = nodes[index];
        const info = infos[index];
        const cap = capById.get(info.capId) ?? caps[0];
        const direction = hierarchyDirection(info, cap);
        const radius = info.targetRadius;
        node.x = direction.x * radius;
        node.y = direction.y * radius;
        node.z = direction.z * radius;
        node.depth = clamp(radius / CAP_SCENE_RADIUS, 0, 1);
        node.radius *= hierarchyNodeScale(info);
    }

    relaxCapLinks(nodes, links, infos);
    confineNodesToCaps(nodes, infos, capById);
    for (let index = 0; index < nodes.length; index++) {
        projectNodeToRadius(nodes[index], infos[index].targetRadius);
        nodes[index].depth = clamp(length(vectorOf(nodes[index])) / CAP_SCENE_RADIUS, 0, 1);
    }
    tuneCapLinks(nodes, links, infos);
    enforceHierarchyShellContract(nodes);
    confineNodesToCaps(nodes, infos, capById);
    for (const node of nodes) {
        node.depth = clamp(length(vectorOf(node)) / CAP_SCENE_RADIUS, 0, 1);
        node.baseX = node.x;
        node.baseY = node.y;
        node.baseZ = node.z;
    }

    return [
        ...buildCapBoundaryGuides(caps),
        ...buildMembershipGuides(nodes, links, infos),
        ...buildLevelShellGuides(),
        buildConcentrationAxisGuide(caps),
    ];
}

function hierarchyInfo(node: GalaxyNode): HierarchyInfo {
    const metadata = node.entity.metadata || {};
    const product = record(metadata['product']);
    const region = record(product['region']);
    const lanes = record(product['lanes']);
    const hopf = record(metadata['hopf']);
    const lorentz = record(metadata['lorentz']);
    const memberships = Array.isArray(lorentz['memberships']) ? lorentz['memberships'] as Array<Record<string, unknown>> : [];
    const primary = memberships[0] ?? {};
    const laneWeights = numberRecord(lanes['laneWeights']);
    const lane = normalizeLane(firstText(
        metadata['productLaneKind'],
        product['dominantLane'],
        region['laneKind'],
        lanes['dominantLane'],
        primary['treeKind'],
        lorentz['primaryTreeKind'],
        dominantLane(laneWeights),
        fallbackLane(node),
    ));
    const role = firstText(metadata['productRegionRole'], region['role'], lorentz['regionRole'], derivedRole(node));
    const treeKind = normalizeLane(firstText(primary['treeKind'], lorentz['primaryTreeKind'], lane));
    const phase = normalizePhase(firstNumber(lorentz['capPhase'], lanes['fiberPhase'], hopf['phase'], stableUnit(`${node.entity.id}:${lane}:phase`)));
    const specificity = hierarchySpecificity(node, role, laneWeights, lorentz);
    const ambiguity = hierarchyAmbiguity(node, role, lanes, lorentz);
    const confidence = hierarchyConfidence(node, region, primary, lorentz);
    const level = hierarchyLevel(node, role, lane, lorentz, primary, specificity);
    return {
        id: node.entity.id,
        capId: capIdFor(node, lane, product, region, lorentz, primary),
        lane,
        role,
        treeKind,
        level,
        phase,
        specificity,
        ambiguity,
        targetRadius: hierarchyRadius(node, specificity, role, lane, confidence, ambiguity),
        direction: rawDirection(node, lorentz),
        parentCapIds: parentCapIdsFor(lorentz, primary),
        confidence,
    };
}

function buildCaps(nodes: GalaxyNode[], infos: HierarchyInfo[]): CapInfo[] {
    const byId = new Map<string, CapInfo>();
    for (let index = 0; index < nodes.length; index++) {
        const info = infos[index];
        let cap = byId.get(info.capId);
        if (!cap) {
            const color = rgbForKind(info.treeKind);
            cap = {
                id: info.capId,
                lane: info.lane,
                parentIds: [],
                center: { x: 0, y: 0, z: 0 },
                indexes: [],
                radiusSum: 0,
                ambiguitySum: 0,
                importance: 0,
                ...color,
            };
            byId.set(info.capId, cap);
        }
        for (const parentId of info.parentCapIds) {
            if (parentId && parentId !== info.capId && !cap.parentIds.includes(parentId)) cap.parentIds.push(parentId);
        }
        const lane = laneDirection(info.lane);
        const concentration = clamp(0.86 + info.confidence * 0.28 + info.specificity * 0.18 - info.ambiguity * 0.14, 0.62, 1.28);
        cap.center.x += (info.direction.x * 0.82 + lane.x * 0.18) * concentration;
        cap.center.y += (info.direction.y * 0.82 + lane.y * 0.18) * concentration;
        cap.center.z += (info.direction.z * 0.82 + lane.z * 0.18) * concentration;
        cap.indexes.push(index);
        cap.radiusSum += info.targetRadius;
        cap.ambiguitySum += info.ambiguity;
        cap.importance += 1 + Math.max(0, nodes[index].entity.totalMentions || 0) * 0.15 + info.confidence;
    }
    const caps = [...byId.values()]
        .map((cap) => ({ ...cap, center: normalize(cap.center, laneDirection(cap.lane)) }))
        .sort((left, right) => right.importance - left.importance || left.id.localeCompare(right.id));
    applyCapContainment(caps);
    return caps;
}

function parentCapIdsFor(lorentz: Record<string, unknown>, primary: Record<string, unknown>): string[] {
    const direct = arrayText(lorentz['parentCapIds']);
    const single = firstText(lorentz['parentCapId'], primary['parentCapId']);
    return [...new Set([...direct, single].filter(Boolean))];
}

function arrayText(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
}

function applyCapContainment(caps: CapInfo[]): void {
    const byId = new Map(caps.map((cap) => [cap.id, cap]));
    for (let pass = 0; pass < 6; pass++) {
        for (const cap of caps) {
            const parents = cap.parentIds.map((id) => byId.get(id)).filter((item): item is CapInfo => Boolean(item));
            if (!parents.length) continue;
            const parentCenter = normalize(parents.reduce((sum, parent) => add(sum, parent.center), { x: 0, y: 0, z: 0 }), parents[0].center);
            const lane = laneDirection(cap.lane);
            const weight = containmentWeight(cap);
            cap.center = normalize(add(add(scale(parentCenter, weight), scale(cap.center, 1 - weight)), scale(lane, 0.04)), parentCenter);
        }
    }
}

function containmentWeight(cap: CapInfo): number {
    const id = cap.id.toLowerCase();
    if (/^document:[^:]+:root:/.test(id)) return 0.94;
    if (/^document:[^:]+:chunk:/.test(id)) return 0.9;
    if (/^identity:|:facts:|:memory|:temporal|:causal|event:/.test(id)) return 0.84;
    return 0.78;
}

function hierarchyDirection(info: HierarchyInfo, cap: CapInfo): Vec3 {
    const lane = laneDirection(info.lane);
    const frame = tangentFrame(cap.center);
    const orbit = add(scale(frame.a, Math.cos(info.phase * TAU)), scale(frame.b, Math.sin(info.phase * TAU)));
    const spread = capNodeAperture(info);
    const base = normalize(add(add(scale(cap.center, 0.78), scale(info.direction, 0.16)), scale(lane, 0.06)), cap.center);
    let shaped = normalize(add(scale(base, 1 - spread), scale(orbit, spread)), cap.center);
    if (info.lane === 'temporal') {
        shaped = normalize(add(scale(shaped, 0.82), scale(temporalRingDirection(info.phase), 0.18)), shaped);
    } else if (info.lane === 'causal') {
        shaped = normalize(add(scale(shaped, 0.84), scale(causalConeDirection(info.phase, info.level), 0.16)), shaped);
    } else if (info.lane === 'document') {
        shaped = normalize(add(scale(shaped, 0.86), scale(documentTreeDirection(info.phase, info.level), 0.14)), shaped);
    }
    return limitDirectionToCap(shaped, cap.center, spread);
}

function confineNodesToCaps(nodes: GalaxyNode[], infos: HierarchyInfo[], capById: Map<string, CapInfo>): void {
    for (let index = 0; index < nodes.length; index++) {
        const info = infos[index];
        const cap = capById.get(info.capId);
        if (!cap) continue;
        const direction = limitDirectionToCap(normalize(vectorOf(nodes[index]), info.direction), cap.center, capNodeAperture(info));
        nodes[index].x = direction.x * info.targetRadius;
        nodes[index].y = direction.y * info.targetRadius;
        nodes[index].z = direction.z * info.targetRadius;
    }
}

function capNodeAperture(info: HierarchyInfo): number {
    if (!info.parentCapIds.length && info.level <= 1) return clamp(0.2 + info.ambiguity * 0.08, 0.16, 0.32);
    if (info.level <= 1) return clamp(0.14 + info.ambiguity * 0.08, 0.1, 0.22);
    if (info.level === 2) return clamp(0.12 + info.ambiguity * 0.08, 0.08, 0.2);
    if (info.level === 3) return clamp(0.08 + info.ambiguity * 0.04, 0.06, 0.13);
    return clamp(0.06 + info.ambiguity * 0.04, 0.04, 0.11);
}

function limitDirectionToCap(direction: Vec3, center: Vec3, aperture: number): Vec3 {
    const normalizedCenter = normalize(center, { x: 0, y: 0, z: 1 });
    const normalizedDirection = normalize(direction, normalizedCenter);
    const dot = normalizedDirection.x * normalizedCenter.x + normalizedDirection.y * normalizedCenter.y + normalizedDirection.z * normalizedCenter.z;
    const minDot = Math.cos(aperture);
    if (dot >= minDot) return normalizedDirection;
    const tangent = normalize(add(normalizedDirection, scale(normalizedCenter, -dot)), tangentFrame(normalizedCenter).a);
    const sin = Math.sin(aperture);
    return normalize(add(scale(normalizedCenter, minDot), scale(tangent, sin)), normalizedCenter);
}

function relaxCapLinks(nodes: GalaxyNode[], links: GalaxyEdge[], infos: HierarchyInfo[]): void {
    for (let pass = 0; pass < 8; pass++) {
        for (const link of links) {
            const source = nodes[link.source];
            const target = nodes[link.target];
            if (!source || !target) continue;
            const sourceInfo = infos[link.source];
            const targetInfo = infos[link.target];
            const sameCap = sourceInfo.capId === targetInfo.capId;
            const structural = isStructuralHierarchyLink(link);
            const bridge = isBridgeLink(link, sourceInfo, targetInfo);
            if (structural) {
                pullStructuralChild(source, target, link, sourceInfo, targetInfo);
                continue;
            }
            const levelDelta = Math.abs(sourceInfo.level - targetInfo.level);
            const ideal = sameCap ? 0.28 : bridge ? 0.78 : 0.56 + levelDelta * 0.02;
            const strength = sameCap ? 0.01 : bridge ? 0.004 : 0.006;
            pullPair(source, target, ideal, strength);
            projectNodeToRadius(source, sourceInfo.targetRadius);
            projectNodeToRadius(target, targetInfo.targetRadius);
        }
    }
}

function pullStructuralChild(
    source: GalaxyNode,
    target: GalaxyNode,
    link: GalaxyEdge,
    sourceInfo: HierarchyInfo,
    targetInfo: HierarchyInfo,
): void {
    const sourceIsParent = sourceInfo.targetRadius >= targetInfo.targetRadius;
    const parent = sourceIsParent ? source : target;
    const child = sourceIsParent ? target : source;
    const parentInfo = sourceIsParent ? sourceInfo : targetInfo;
    const childInfo = sourceIsParent ? targetInfo : sourceInfo;
    const parentDirection = normalize(vectorOf(parent), parentInfo.direction);
    const childDirection = normalize(vectorOf(child), childInfo.direction);
    const frame = tangentFrame(parentDirection);
    const phase = stableUnit(`${link.id}:caps-child`);
    const spread = clamp(0.1 + Math.abs(parentInfo.level - childInfo.level) * 0.04 + childInfo.ambiguity * 0.16, 0.1, 0.34);
    const orbit = add(
        scale(frame.a, Math.cos(phase * TAU) * spread),
        scale(frame.b, Math.sin(phase * TAU) * spread),
    );
    const desired = normalize(add(
        add(scale(parentDirection, 0.76), scale(childInfo.direction, 0.14)),
        add(scale(laneDirection(childInfo.lane), 0.08), orbit),
    ), parentDirection);
    const blend = clamp(0.18 + link.confidence * 0.1, 0.18, 0.3);
    const next = normalize(add(scale(childDirection, 1 - blend), scale(desired, blend)), desired);
    child.x = next.x * childInfo.targetRadius;
    child.y = next.y * childInfo.targetRadius;
    child.z = next.z * childInfo.targetRadius;
    projectNodeToRadius(parent, parentInfo.targetRadius);
}

function tuneCapLinks(nodes: GalaxyNode[], links: GalaxyEdge[], infos: HierarchyInfo[]): void {
    for (const link of links) {
        const sourceInfo = infos[link.source];
        const targetInfo = infos[link.target];
        const sameCap = sourceInfo?.capId === targetInfo?.capId;
        const bridge = sourceInfo && targetInfo && isBridgeLink(link, sourceInfo, targetInfo);
        if (isStructuralHierarchyLink(link)) {
            link.alpha = Math.min(0.56, link.alpha * 1.56 + 0.06);
            link.curve *= 0.42;
        } else if (sameCap) {
            link.alpha = Math.min(0.52, link.alpha * 1.22 + 0.035);
            link.curve *= 0.62;
        } else if (bridge) {
            link.alpha = Math.min(0.5, link.alpha * 1.18 + 0.028);
            link.curve *= 1.42;
        } else {
            link.alpha = Math.min(0.42, link.alpha * 0.92 + 0.018);
            link.curve *= 0.96;
        }
        const source = nodes[link.source];
        const target = nodes[link.target];
        const radiusDelta = source && target ? Math.abs(source.depth - target.depth) : 0;
        link.curve *= 0.82 + radiusDelta * 0.42;
    }
}

function buildCapBoundaryGuides(caps: CapInfo[]): GalaxyLorentzGuide[] {
    return caps.slice(0, MAX_CAP_GUIDES).map((cap) => {
        const count = cap.indexes.length || 1;
        const radius = cap.radiusSum / count;
        const ambiguity = cap.ambiguitySum / count;
        return {
            id: `caps:boundary:${cap.id}`,
            nodeIds: [],
            positions3d: capRingSegments(cap.center, radius, clamp(0.18 + Math.sqrt(count) * 0.018 + ambiguity * 0.22, 0.2, 0.64)),
            importance: cap.importance,
            treeId: cap.id,
            treeKind: cap.lane,
            level: 1,
            guideKind: 'rootLane',
            guideWeight: clamp(0.48 + Math.log1p(count) * 0.045, 0.5, 0.86),
            r: cap.r,
            g: cap.g,
            b: cap.b,
        };
    });
}

function buildMembershipGuides(nodes: GalaxyNode[], links: GalaxyEdge[], infos: HierarchyInfo[]): GalaxyLorentzGuide[] {
    const guides: GalaxyLorentzGuide[] = [];
    for (const link of links) {
        const source = nodes[link.source];
        const target = nodes[link.target];
        if (!source || !target) continue;
        const sourceInfo = infos[link.source];
        const targetInfo = infos[link.target];
        const treeKind = guideKindForLink(link, source, target, sourceInfo, targetInfo);
        const confidence = clamp(link.confidence, 0.12, 1);
        const structural = isStructuralHierarchyLink(link);
        guides.push({
            id: `caps:bridge:${link.id}`,
            nodeIds: [source.entity.id, target.entity.id],
            positions3d: capBridgeSegments(source, target, treeKind, sourceInfo, targetInfo),
            importance: Math.max(source.radius, target.radius) * 0.48 + confidence + (structural ? 2 : 0),
            treeId: sourceInfo.capId === targetInfo.capId ? sourceInfo.capId : 'caps:overlap',
            treeKind,
            level: Math.max(sourceInfo.level, targetInfo.level),
            guideKind: 'membership',
            guideWeight: structural ? 0.72 : 0.42 + Math.min(0.36, confidence * 0.24),
            ...rgbForKind(treeKind),
        });
    }
    return guides.sort((left, right) => right.importance - left.importance || left.id.localeCompare(right.id)).slice(0, MAX_MEMBERSHIP_GUIDES);
}

function buildLevelShellGuides(): GalaxyLorentzGuide[] {
    const shells = [
        { level: 0, radius: 2.08, kind: 'documentStructure', weight: 0.52 },
        { level: 1, radius: 1.92, kind: 'semantic', weight: 0.46 },
        { level: 2, radius: 1.66, kind: 'document', weight: 0.42 },
        { level: 3, radius: 1.42, kind: 'identity', weight: 0.38 },
        { level: 4, radius: 1.18, kind: 'relationship', weight: 0.34 },
        { level: 5, radius: 0.92, kind: 'evidence', weight: 0.3 },
    ];
    return shells.map((shell) => ({
        id: `caps:shell:${shell.level}`,
        nodeIds: [],
        positions3d: shellRingSegments(shell.radius),
        importance: 0.2,
        treeId: 'caps:shells',
        treeKind: shell.kind,
        level: shell.level,
        guideKind: 'levelShell',
        guideWeight: shell.weight,
        ...rgbForKind(shell.kind),
    }));
}

function buildConcentrationAxisGuide(caps: CapInfo[]): GalaxyLorentzGuide {
    const dominant = caps[0]?.center ?? { x: 0.32, y: 0.76, z: 0.56 };
    return {
        id: 'caps:concentration-axis',
        nodeIds: [],
        positions3d: lineSegments(scale(dominant, -0.42), scale(dominant, CAP_SCENE_RADIUS * 0.98), 32),
        importance: 0.1,
        treeId: 'caps:axis',
        treeKind: 'semantic',
        level: 0,
        guideKind: 'wAxis',
        guideWeight: 0.18,
        ...rgbForKind('semantic'),
    };
}

function hierarchySpecificity(node: GalaxyNode, role: string, laneWeights: Record<string, number>, lorentz: Record<string, unknown>): number {
    const direct = firstNumber(lorentz['specificity'], NaN);
    if (Number.isFinite(direct)) return clamp(direct, 0, 1);
    const sourceType = String(node.entity.metadata?.sourceType || node.entity.kind || '').toLowerCase();
    let base = 0.58;
    if (/note|document|doc/.test(sourceType)) base = 0.22;
    else if (/chunk|anchor/.test(sourceType)) base = 0.9;
    else if (/entity|character|location|creature|concept/.test(sourceType)) base = 0.82;
    else if (/causal|temporal|event/.test(sourceType)) base = 0.74;
    else if (/graph.?fact|relationship|relation|memory|state/.test(sourceType)) base = 0.64;
    const semantic = clamp(laneWeights['semantic'] || 0, 0, 1);
    const roleBoost = role === 'outlier' ? 0.14 : role === 'boundary' ? 0.08 : role === 'bridge' ? 0.05 : role === 'core' ? -0.04 : 0;
    return clamp(base + roleBoost + semantic * 0.08, 0.12, 0.98);
}

function hierarchyAmbiguity(node: GalaxyNode, role: string, lanes: Record<string, unknown>, lorentz: Record<string, unknown>): number {
    const direct = firstNumber(lorentz['ambiguity'], NaN);
    if (Number.isFinite(direct)) return clamp(direct, 0, 1);
    const radius = clamp(firstNumber(lanes['clusterRadius'], lorentz['w'], 0.36), 0, 1);
    const outlier = clamp(firstNumber(node.entity.metadata?.['embeddingOutlierScore'], 0), 0, 1);
    const roleBoost = role === 'outlier' ? 0.22 : role === 'bridge' ? 0.12 : role === 'boundary' ? 0.08 : 0;
    return clamp(radius * 0.48 + outlier * 0.28 + roleBoost, 0.04, 0.9);
}

function hierarchyLevel(
    node: GalaxyNode,
    role: string,
    lane: string,
    lorentz: Record<string, unknown>,
    primary: Record<string, unknown>,
    specificity: number,
): number {
    const direct = firstNumber(lorentz['level'], primary['level'], NaN);
    if (Number.isFinite(direct)) return clamp(Math.round(direct), 0, 4);
    if (role === 'outlier' || role === 'boundary') return 4;
    if (role === 'bridge' || lane === 'relationship' || lane === 'causal') return 3;
    if (lane === 'temporal' || lane === 'event' || specificity > 0.72) return 2;
    const text = `${node.entity.kind || ''} ${node.entity.metadata?.sourceType || ''}`.toLowerCase();
    if (/note|document|doc/.test(text)) return 0;
    if (/chunk/.test(text)) return 1;
    if (/entity|character|location|creature|npc|item|network|group/.test(text)) return 2;
    return 1;
}

function hierarchyRadius(
    node: GalaxyNode,
    specificity: number,
    role: string,
    lane: string,
    confidence: number,
    ambiguity: number,
): number {
    const lorentz = record(node.entity.metadata?.['lorentz']);
    const explicitRadius = Number(lorentz['shellRadius']);
    if (Number.isFinite(explicitRadius)) return contractShellRadiusForNode(node, clamp(explicitRadius, 0.38, CAP_SCENE_RADIUS * 0.985));
    const sourceType = String(node.entity.metadata?.sourceType || node.entity.kind || '').toLowerCase();
    const kind = String(node.entity.kind || '').toLowerCase();
    let radius = hierarchyShellRadius(sourceType, kind, lane);
    radius += (clamp(specificity, 0, 1) - 0.62) * 0.22;
    radius += (clamp(confidence, 0, 1) - 0.66) * 0.46;
    radius -= clamp(ambiguity, 0, 1) * 0.24;
    if (role === 'bridge') radius += 0.08;
    if (role === 'outlier') radius += 0.16;
    if (/note|document|doc/.test(sourceType)) radius = Math.max(radius, 1.96);
    if (/chunk/.test(sourceType)) radius = clamp(radius, 1.58, 1.86);
    if (/entity|character|location|creature|npc|item|network|group/.test(sourceType) || /character|location|creature|npc|item|network|group/.test(kind)) {
        radius = clamp(radius, 1.28, 1.58);
    }
    if (lane === 'temporal') radius = clamp(radius, 1.08, 1.72);
    return contractShellRadiusForNode(node, clamp(radius, 0.38, CAP_SCENE_RADIUS * 0.985));
}

function hierarchyShellRadius(sourceType: string, kind: string, lane: string): number {
    if (/note|document|doc/.test(sourceType)) return 2.08;
    if (/chunk/.test(sourceType)) return 1.72;
    if (/entity|character|location|creature|npc|item|network|group/.test(sourceType) || /character|location|creature|npc|item|network|group/.test(kind)) return 1.42;
    if (/graph.?fact|relationship|relation/.test(sourceType) || lane === 'relationship') return 1.3;
    if (/event|temporal|causal/.test(sourceType) || lane === 'event' || lane === 'temporal' || lane === 'causal') return 1.34;
    if (/anchor|mention|evidence/.test(sourceType)) return 0.96;
    if (/memory|state|concept|context/.test(sourceType) || /memory|state|concept|context/.test(kind)) return 1.08;
    return 1.18;
}

function hierarchyConfidence(
    node: GalaxyNode,
    region: Record<string, unknown>,
    primary: Record<string, unknown>,
    lorentz: Record<string, unknown>,
): number {
    return clamp(firstNumber(
        node.entity.metadata?.['targetConfidence'],
        lorentz['confidence'],
        region['confidence'],
        primary['confidence'],
        node.entity.totalMentions ? 0.72 : 0.5,
    ), 0, 1);
}

function hierarchyNodeScale(info: HierarchyInfo): number {
    return clamp(0.72 + info.specificity * 0.32 + (info.role === 'core' ? 0.08 : 0) - info.ambiguity * 0.08, 0.68, 1.16);
}

function capIdFor(
    node: GalaxyNode,
    lane: string,
    product: Record<string, unknown>,
    region: Record<string, unknown>,
    lorentz: Record<string, unknown>,
    primary: Record<string, unknown>,
): string {
    const structuralCapId = structuralCapIdFor(node, lane);
    return firstText(
        lorentz['capId'],
        structuralCapId,
        node.entity.metadata?.['embeddingClusterId'],
        region['id'],
        region['clusterId'],
        product['clusterId'],
        primary['treeId'],
        `lane:${lane}`,
    );
}

function structuralCapIdFor(node: GalaxyNode, lane: string): string {
    const metadata = node.entity.metadata || {};
    const folderId = firstText(metadata['folderId'], metadata['folderCapId']);
    if (folderId) return `folder:${folderId}`;
    const noteId = firstText(metadata['noteId'], /note|document|doc/.test(String(metadata['sourceType'] || node.entity.kind || '').toLowerCase()) ? metadata['sourceId'] : '');
    if (noteId) return `document:${noteId}`;
    if (lane === 'document' || lane === 'documentStructure') return 'document:root';
    return '';
}

function guideKindForLink(link: GalaxyEdge, source: GalaxyNode, target: GalaxyNode, sourceInfo: HierarchyInfo, targetInfo: HierarchyInfo): string {
    if (isStructuralHierarchyLink(link)) return targetInfo.level > sourceInfo.level ? targetInfo.treeKind : sourceInfo.treeKind;
    const relation = relationFamilyFromText(link.type, source.entity.label, source.entity.metadata?.['preview'], target.entity.label, target.entity.metadata?.['preview']);
    if (relation) return relation;
    if (sourceInfo.lane === targetInfo.lane) return sourceInfo.treeKind;
    if (sourceInfo.lane === 'causal' || targetInfo.lane === 'causal') return 'causal';
    if (sourceInfo.lane === 'temporal' || targetInfo.lane === 'temporal') return 'temporal';
    if (/bridge|co.?occur|relationship|relation|fact/.test(String(link.type || '').toLowerCase())) return 'relationship';
    return 'bridge';
}

function isStructuralHierarchyLink(link: GalaxyEdge): boolean {
    return /target-parent|note-chunk|chunk-anchor|chunk-entity|anchor-entity|event-chunk|event-entity|memory-entity/i.test(String(link.type || ''));
}

function isBridgeLink(link: GalaxyEdge, source: HierarchyInfo, target: HierarchyInfo): boolean {
    const type = String(link.type || '').toLowerCase();
    return source.capId !== target.capId || source.lane !== target.lane || /bridge|co.?occur|causal|temporal/.test(type);
}

function normalizePhase(value: number): number {
    const finiteValue = Number.isFinite(value) ? value : 0;
    return ((finiteValue % 1) + 1) % 1;
}
