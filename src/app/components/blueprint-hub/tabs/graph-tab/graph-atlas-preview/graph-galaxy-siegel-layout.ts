import type { GalaxyEdge, GalaxyLorentzGuide, GalaxyNode } from './graph-galaxy-engine';
import {
    TAU,
    add,
    clamp,
    firstNumber,
    firstText,
    laneDirection,
    length,
    lineSegments,
    normalize,
    normalizeLane,
    record,
    rgbForKind,
    scale,
    stableUnit,
    tangentFrame,
    vectorOf,
    type Vec3,
} from './graph-galaxy-hierarchy-caps';

const SIEGEL_MAX_GUIDES = 260;
const SIEGEL_FLOW_X_MIN = -1.72;
const SIEGEL_FLOW_X_STEP = 0.48;
const SIEGEL_FLOW_Z = 0.68;

interface SiegelInfo {
    lane: string;
    role: string;
    depth: number;
    row: number;
    phase: number;
    confidence: number;
    ambiguity: number;
    matrixCells: readonly number[];
    parentIds: Set<string>;
}

interface LaneRow {
    lane: string;
    y: number;
    count: number;
}

export function applySiegelFinslerLayout(nodes: GalaxyNode[], links: GalaxyEdge[]): GalaxyLorentzGuide[] {
    if (!nodes.length) return [];
    const infos = nodes.map(siegelInfo);
    const lanes = buildLaneRows(infos);
    const laneByName = new Map(lanes.map((lane) => [lane.lane, lane]));

    for (let index = 0; index < nodes.length; index++) {
        const node = nodes[index];
        const info = infos[index];
        const lane = laneByName.get(info.lane) ?? lanes[0];
        const cells = info.matrixCells;
        const x = SIEGEL_FLOW_X_MIN + info.depth * SIEGEL_FLOW_X_STEP + (cells[0] - 0.5) * 0.18;
        const y = lane.y + (cells[1] - 0.5) * 0.18 + (info.row - 0.5) * 0.1;
        const z = (cells[2] - 0.5) * SIEGEL_FLOW_Z + Math.sin(info.phase * TAU) * 0.12;
        node.x = x;
        node.y = y;
        node.z = z;
        node.depth = clamp((info.depth + info.ambiguity) / 5, 0, 1);
        node.radius *= siegelNodeScale(info);
    }

    relaxDirectedPairs(nodes, links, infos, laneByName);
    normalizeSiegelVolume(nodes);
    tuneSiegelLinks(nodes, links, infos);
    freezeBases(nodes);

    return [
        ...buildLaneGuides(lanes),
        ...buildDirectedGuides(nodes, links, infos),
        buildDirectionGuide(nodes),
    ];
}

function siegelInfo(node: GalaxyNode): SiegelInfo {
    const meta = node.entity.metadata || {};
    const siegel = record(meta['siegel']);
    const product = record(meta['product']);
    const region = record(product['region']);
    const lorentz = record(meta['lorentz']);
    const graphTruth = record(meta['graphTruth']);
    const lane = normalizeSiegelLane(firstText(
        siegel['lane'],
        meta['signalLane'],
        meta['productLaneKind'],
        region['laneKind'],
        lorentz['dominantLane'],
        meta['graphRelationFamily'],
        meta['graphKind'],
        meta['sourceType'],
        node.entity.kind,
    ));
    const role = firstText(siegel['role'], meta['signalStructuralRole'], meta['graphTruthStatus'], graphTruth['status'], region['role']);
    const parentIds = new Set((Array.isArray(meta['signalParentIds']) ? meta['signalParentIds'] : []).map(String));
    const depth = clamp(Math.round(firstNumber(siegel['depth'], lorentz['level'], fallbackDepth(node, lane))), 0, 5);
    const confidence = clamp(firstNumber(siegel['confidence'], meta['targetConfidence'], meta['productRegionConfidence'], region['confidence'], 0.62), 0, 1);
    const ambiguity = clamp(firstNumber(siegel['ambiguity'], lorentz['ambiguity'], meta['embeddingOutlierScore'], 0) * 0.72, 0, 1);
    const cells = Array.isArray(siegel['matrixCells'])
        ? siegel['matrixCells'].map((value) => clamp(Number(value), 0, 1)).slice(0, 6)
        : matrixCells(node.entity.id, lane, depth, role);
    while (cells.length < 6) cells.push(stableUnit(`${node.entity.id}:siegel:${cells.length}`));
    return {
        lane,
        role,
        depth,
        row: stableUnit(`${node.entity.id}:siegel-row`),
        phase: clamp(firstNumber(siegel['phase'], lorentz['capPhase'], stableUnit(`${node.entity.id}:siegel-phase`)), 0, 1),
        confidence,
        ambiguity,
        matrixCells: cells,
        parentIds,
    };
}

function buildLaneRows(infos: SiegelInfo[]): LaneRow[] {
    const counts = new Map<string, number>();
    for (const info of infos) counts.set(info.lane, (counts.get(info.lane) || 0) + 1);
    const ordered = [...counts.entries()]
        .sort((left, right) => laneRank(left[0]) - laneRank(right[0]) || right[1] - left[1] || left[0].localeCompare(right[0]))
        .slice(0, 9);
    const total = Math.max(1, ordered.length - 1);
    return ordered.map(([lane, count], index) => ({
        lane,
        count,
        y: total ? 1.14 - (index / total) * 2.28 : 0,
    }));
}

function relaxDirectedPairs(
    nodes: GalaxyNode[],
    links: GalaxyEdge[],
    infos: SiegelInfo[],
    laneByName: Map<string, LaneRow>,
): void {
    for (let pass = 0; pass < 4; pass++) {
        for (const link of links) {
            const source = nodes[link.source];
            const target = nodes[link.target];
            if (!source || !target) continue;
            const sourceInfo = infos[link.source];
            const targetInfo = infos[link.target];
            if (isStructuralLink(link, source, targetInfo) || sourceInfo.parentIds.has(target.entity.id)) {
                pullDirectedChild(source, target, sourceInfo, targetInfo, link.confidence);
                continue;
            }
            if (isStructuralLink(link, target, sourceInfo) || targetInfo.parentIds.has(source.entity.id)) {
                pullDirectedChild(target, source, targetInfo, sourceInfo, link.confidence);
                continue;
            }
            const sameLane = sourceInfo.lane === targetInfo.lane;
            const bridge = !sameLane || /bridge|temporal|causal|co.?occur|relationship/.test(link.type.toLowerCase());
            const ideal = sameLane ? 0.3 : bridge ? 0.72 : 0.56;
            const strength = sameLane ? 0.028 : 0.014;
            pullPair(source, target, ideal, strength * Math.max(0.4, link.confidence));
            const sourceLane = laneByName.get(sourceInfo.lane);
            const targetLane = laneByName.get(targetInfo.lane);
            if (sourceLane) source.y += (sourceLane.y - source.y) * 0.018;
            if (targetLane) target.y += (targetLane.y - target.y) * 0.018;
        }
    }
}

function pullDirectedChild(parent: GalaxyNode, child: GalaxyNode, parentInfo: SiegelInfo, childInfo: SiegelInfo, confidence: number): void {
    const desiredX = Math.max(child.x, parent.x + 0.28 + Math.max(0, childInfo.depth - parentInfo.depth) * 0.18);
    const lane = laneDirection(childInfo.lane);
    const parentDir = normalize(vectorOf(parent), lane);
    const frame = tangentFrame(parentDir);
    const phase = childInfo.phase * TAU;
    const local = add(scale(frame.a, Math.cos(phase) * 0.12), scale(frame.b, Math.sin(phase) * 0.12));
    const strength = clamp(0.1 + confidence * 0.08, 0.1, 0.2);
    child.x += (desiredX - child.x) * strength;
    child.y += (parent.y + lane.y * 0.12 + local.y - child.y) * strength;
    child.z += (parent.z * 0.42 + lane.z * 0.12 + local.z - child.z) * strength;
}

function normalizeSiegelVolume(nodes: GalaxyNode[]): void {
    let maxRadius = 0.001;
    for (const node of nodes) maxRadius = Math.max(maxRadius, length(vectorOf(node)));
    const scaleFactor = maxRadius > 2.28 ? 2.28 / maxRadius : 1;
    for (const node of nodes) {
        node.x *= scaleFactor;
        node.y *= scaleFactor;
        node.z *= scaleFactor;
        node.depth = clamp(length(vectorOf(node)) / 2.28, 0, 1);
    }
}

function tuneSiegelLinks(nodes: GalaxyNode[], links: GalaxyEdge[], infos: SiegelInfo[]): void {
    for (const link of links) {
        const sourceInfo = infos[link.source];
        const targetInfo = infos[link.target];
        const structural = isStructuralType(link.type);
        const sameLane = sourceInfo?.lane === targetInfo?.lane;
        if (structural) {
            link.alpha = Math.min(0.58, link.alpha * 1.44 + 0.065);
            link.curve *= 0.34;
        } else if (sameLane) {
            link.alpha = Math.min(0.44, link.alpha * 1.12 + 0.026);
            link.curve *= 0.62;
        } else {
            link.alpha = Math.min(0.38, link.alpha * 0.9 + 0.018);
            link.curve *= 1.18;
        }
        const source = nodes[link.source];
        const target = nodes[link.target];
        const dx = source && target ? Math.abs(target.x - source.x) : 0;
        link.curve *= 0.72 + dx * 0.24;
    }
}

function freezeBases(nodes: GalaxyNode[]): void {
    for (const node of nodes) {
        node.baseX = node.x;
        node.baseY = node.y;
        node.baseZ = node.z;
    }
}

function buildLaneGuides(lanes: LaneRow[]): GalaxyLorentzGuide[] {
    return lanes.map((lane, index) => ({
        id: `siegel:lane:${lane.lane}`,
        nodeIds: [],
        positions3d: lineSegments({ x: -1.9, y: lane.y, z: -0.44 }, { x: 1.78, y: lane.y, z: 0.44 }, 48),
        importance: lane.count,
        treeId: `siegel:lane:${lane.lane}`,
        treeKind: lane.lane,
        level: index,
        guideKind: 'rootLane',
        guideWeight: clamp(0.42 + Math.log1p(lane.count) * 0.055, 0.48, 0.86),
        ...rgbForKind(lane.lane),
    }));
}

function buildDirectedGuides(nodes: GalaxyNode[], links: GalaxyEdge[], infos: SiegelInfo[]): GalaxyLorentzGuide[] {
    const guides: GalaxyLorentzGuide[] = [];
    for (const link of links) {
        const source = nodes[link.source];
        const target = nodes[link.target];
        if (!source || !target) continue;
        const sourceInfo = infos[link.source];
        const targetInfo = infos[link.target];
        const kind = isStructuralType(link.type) ? 'documentStructure' : sourceInfo.lane === targetInfo.lane ? sourceInfo.lane : 'bridge';
        guides.push({
            id: `siegel:directed:${link.id}`,
            nodeIds: [source.entity.id, target.entity.id],
            positions3d: directedCurve(source, target, sourceInfo, targetInfo, link),
            importance: (isStructuralType(link.type) ? 2.2 : 0.7) + Math.max(source.radius, target.radius) * 0.36 + link.confidence,
            treeId: sourceInfo.lane === targetInfo.lane ? `siegel:lane:${sourceInfo.lane}` : 'siegel:bridge',
            treeKind: kind,
            level: Math.max(sourceInfo.depth, targetInfo.depth),
            guideKind: 'membership',
            guideWeight: isStructuralType(link.type) ? 0.76 : 0.42 + Math.min(0.26, link.confidence * 0.2),
            ...rgbForKind(kind),
        });
    }
    return guides
        .sort((left, right) => right.importance - left.importance || left.id.localeCompare(right.id))
        .slice(0, SIEGEL_MAX_GUIDES);
}

function buildDirectionGuide(nodes: GalaxyNode[]): GalaxyLorentzGuide {
    const start = { x: -1.96, y: -1.46, z: -0.18 };
    const end = { x: 1.88, y: -1.46, z: 0.18 };
    return {
        id: 'siegel:direction-axis',
        nodeIds: nodes.slice(0, 64).map((node) => node.entity.id),
        positions3d: lineSegments(start, end, 48),
        importance: nodes.length,
        treeId: 'siegel:direction',
        treeKind: 'causal',
        level: 0,
        guideKind: 'wAxis',
        guideWeight: 0.58,
        ...rgbForKind('causal'),
    };
}

function directedCurve(source: GalaxyNode, target: GalaxyNode, sourceInfo: SiegelInfo, targetInfo: SiegelInfo, link: GalaxyEdge): Float32Array {
    const steps = 16;
    const positions = new Float32Array(steps * 6);
    const bridge = sourceInfo.lane !== targetInfo.lane;
    const lift = bridge ? 0.22 : 0.09;
    const sourcePoint = vectorOf(source);
    const targetPoint = vectorOf(target);
    const mid = {
        x: (source.x + target.x) * 0.5 + (target.x >= source.x ? lift : -lift * 0.4),
        y: (source.y + target.y) * 0.5 + (stableUnit(`${link.id}:siegel-y`) - 0.5) * (bridge ? 0.22 : 0.08),
        z: (source.z + target.z) * 0.5 + (stableUnit(`${link.id}:siegel-z`) - 0.5) * (bridge ? 0.56 : 0.18),
    };
    const chord = normalize({
        x: target.x - source.x,
        y: target.y - source.y,
        z: target.z - source.z,
    }, { x: 1, y: 0, z: 0 });
    const lane = laneDirection(bridge ? 'bridge' : targetInfo.lane || sourceInfo.lane);
    const curlNormal = normalize(cross(chord, lane), lane);
    const curlSign = stableUnit(`${link.id}:siegel-terminal`) > 0.5 ? 1 : -1;
    const curlAmount = bridge ? 0.1 : 0.064;
    for (let index = 0; index < steps; index++) {
        writeVec(positions, index * 6, targetBraidedDirectedPoint(sourcePoint, mid, targetPoint, curlNormal, index / steps, curlAmount, curlSign));
        writeVec(positions, index * 6 + 3, targetBraidedDirectedPoint(sourcePoint, mid, targetPoint, curlNormal, (index + 1) / steps, curlAmount, curlSign));
    }
    return positions;
}

function targetBraidedDirectedPoint(a: Vec3, b: Vec3, c: Vec3, normal: Vec3, t: number, amount: number, sign: number): Vec3 {
    const point = quadraticPoint(a, b, c, t);
    const curl = targetFlourish(t, amount) * sign;
    return add(point, scale(normal, curl));
}

function targetFlourish(t: number, amount: number): number {
    const width = 0.28;
    const end = t > 1 - width ? Math.sin(Math.PI * (1 - t) / width) : 0;
    return amount * end * 0.78;
}

function fallbackDepth(node: GalaxyNode, lane: string): number {
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    const kind = String(node.entity.kind || '').toLowerCase();
    if (/note|doc|document/.test(sourceType) || kind === 'note') return 0;
    if (/structure-root/.test(kind) || /structure-root/.test(sourceType)) return 1;
    if (/chunk|leaf/.test(kind) || /chunk|leaf/.test(sourceType)) return 2;
    if (/entity|character|location|network|item|concept|creature|npc/.test(kind) || lane === 'entity') return 3;
    if (/anchor|mention|evidence/.test(kind) || /anchor|mention/.test(sourceType)) return 4;
    return lane === 'document' ? 2 : lane === 'temporal' || lane === 'causal' || lane === 'event' ? 3 : 4;
}

function normalizeSiegelLane(value: string): string {
    const lane = normalizeLane(value).toLowerCase().replace(/[_\s-]+/g, '');
    if (/document|doc|chunk|leaf|structure/.test(lane)) return 'document';
    if (/temporal|timeline|time/.test(lane)) return 'temporal';
    if (/causal|cause|effect/.test(lane)) return 'causal';
    if (/event|scene|beat|chapter/.test(lane)) return 'event';
    if (/relation|relationship|cooccurrence|communication|authority|approval|family|intimacy|transfer/.test(lane)) return 'relationship';
    if (/evidence|memory|state|source|provenance|anchor|mention/.test(lane)) return 'evidence';
    if (/entity|identity|character|location|concept|item|creature|npc|network/.test(lane)) return 'entity';
    return 'semantic';
}

function laneRank(lane: string): number {
    const index = ['document', 'entity', 'relationship', 'event', 'temporal', 'causal', 'evidence', 'semantic'].indexOf(lane);
    return index >= 0 ? index : 99;
}

function isStructuralLink(link: GalaxyEdge, possibleParent: GalaxyNode, possibleChild: SiegelInfo): boolean {
    return isStructuralType(link.type) && possibleChild.parentIds.has(possibleParent.entity.id);
}

function isStructuralType(type: string): boolean {
    return /target-parent|note-chunk|chunk-anchor|chunk-entity|anchor-entity|event-chunk|event-entity|memory-entity/i.test(type);
}

function siegelNodeScale(info: SiegelInfo): number {
    return clamp(0.72 + info.confidence * 0.18 + (info.depth <= 1 ? 0.12 : 0) - info.ambiguity * 0.08, 0.64, 1.08);
}

function matrixCells(id: string, lane: string, depth: number, role: string): number[] {
    return Array.from({ length: 6 }, (_, index) => stableUnit(`${id}:siegel:${lane}:${depth}:${role}:${index}`));
}

function pullPair(source: GalaxyNode, target: GalaxyNode, ideal: number, strength: number): void {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const dz = target.z - source.z;
    const distance = Math.max(0.001, Math.hypot(dx, dy, dz));
    const force = (distance - ideal) * strength;
    source.x += dx / distance * force;
    source.y += dy / distance * force;
    source.z += dz / distance * force;
    target.x -= dx / distance * force;
    target.y -= dy / distance * force;
    target.z -= dz / distance * force;
}

function writeQuadratic(buffer: Float32Array, offset: number, a: Vec3, b: Vec3, c: Vec3, t: number): void {
    writeVec(buffer, offset, quadraticPoint(a, b, c, t));
}

function quadraticPoint(a: Vec3, b: Vec3, c: Vec3, t: number): Vec3 {
    const left = (1 - t) * (1 - t);
    const mid = 2 * (1 - t) * t;
    const right = t * t;
    return {
        x: left * a.x + mid * b.x + right * c.x,
        y: left * a.y + mid * b.y + right * c.y,
        z: left * a.z + mid * b.z + right * c.z,
    };
}

function writeVec(buffer: Float32Array, offset: number, value: Vec3): void {
    buffer[offset] = value.x;
    buffer[offset + 1] = value.y;
    buffer[offset + 2] = value.z;
}

function cross(left: Vec3, right: Vec3): Vec3 {
    return {
        x: left.y * right.z - left.z * right.y,
        y: left.z * right.x - left.x * right.z,
        z: left.x * right.y - left.y * right.x,
    };
}
