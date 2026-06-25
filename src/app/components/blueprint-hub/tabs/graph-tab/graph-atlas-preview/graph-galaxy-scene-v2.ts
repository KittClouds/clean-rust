import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import {
    hslToRgb,
    type GalaxyGroup,
    type GalaxyHopfRibbon,
    type GalaxyLayoutMode,
    type GalaxyLorentzGuide,
    type GalaxyHybridBusemannReceipt,
    type GalaxyHybridShellReceipt,
    type GalaxyNode,
    type GalaxyRelationControl,
    type GalaxyScene,
    type GalaxyBusemannHorosphereSpec,
} from './graph-galaxy-engine';
import { hierarchyShellBandForNode } from './graph-galaxy-hierarchy-caps';
import { relationFamilyFromText } from './graph-relation-visual-style';
import type { TransitPlan } from './graph-transit-plan';
import type { PhoenixGraphScenePacketHierarchyHint } from '../../../../../services/phoenix-graph-scene-packet.model';

export type GalaxySceneSourceMode = 'entities' | 'graph' | 'embeddings';

export interface GalaxySceneGroupView {
    id: string;
    label: string;
    kind: GalaxyGroup['kind'];
    center: { x: number; y: number; z: number };
    radius: number;
    color: { r: number; g: number; b: number };
    nodeIds: string[];
    importance: number;
}

export interface GalaxyHopfRibbonView {
    id: string;
    nodeIds: string[];
    positions3d: Float32Array;
    positions2d: Float32Array;
    color: { r: number; g: number; b: number };
    importance: number;
    guideKind: GalaxyHopfRibbon['guideKind'];
    guideWeight: number;
    /**
     * Source-node color resolved from `nodeIds[0]` at scene compile.
     * Only read when the renderer's `guideColorMode === 'sourceNode'`;
     * otherwise the guide falls back to its own `color` / hashed palette.
     * Optional so older persisted scenes merge cleanly.
     */
    sourceColor?: { r: number; g: number; b: number };
}

export interface GalaxyLorentzGuideView {
    id: string;
    nodeIds: string[];
    positions3d: Float32Array;
    positions2d: Float32Array;
    color: { r: number; g: number; b: number };
    importance: number;
    treeId: string;
    treeKind: string;
    level: number;
    guideKind: GalaxyLorentzGuide['guideKind'];
    guideWeight: number;
    /**
     * Source-node color resolved from `nodeIds[0]` at scene compile.
     * See {@link GalaxyHopfRibbonView.sourceColor}.
     */
    sourceColor?: { r: number; g: number; b: number };
}

export interface GalaxyBusemannHorosphereView {
    prototypeId: string;
    family: string;
    label: string;
    tau: number;
    center: { x: number; y: number; z: number };
    radius: number;
    color: { r: number; g: number; b: number };
    opacity: number;
}

export interface GalaxyRelationControlView {
    id: string;
    label: string;
    kind: string;
    family: string;
    noteIds: string[];
    chunkIds: string[];
    entityIds: string[];
    eventIds: string[];
    ownerEntityId: string;
    regionId: string;
    sourceNodeIds: string[];
    targetNodeIds: string[];
    evidenceNodeIds: string[];
    participantNodeIds: string[];
    edgeIds: string[];
    position3d: [number, number, number];
    color: { r: number; g: number; b: number };
    confidence: number;
}

export interface GalaxyHybridShellReceiptView {
    lane: string;
    phase: number;
    specificity: number;
    ambiguity: number;
    level: number;
    strength: number;
    baseRadius: number;
    shellRadius: number;
    laneStrength: number;
    sourceSignals: string[];
}

export interface GalaxyHybridCommitmentReceiptView {
    family: string;
    topPrototypeId: string;
    entropy: number;
    margin: number;
    confidence: number;
    promotionReady: boolean;
    radialStrength: number;
    source: GalaxyHybridBusemannReceipt['source'];
    radius: number;
}

export interface GalaxyHybridNodeReceiptView {
    nodeId: string;
    shell?: GalaxyHybridShellReceiptView;
    commitment?: GalaxyHybridCommitmentReceiptView;
    renderRadius: number;
}

export interface GalaxySceneV2 {
    sourceMode: GalaxySceneSourceMode;
    layoutMode: GalaxyLayoutMode;
    ids: string[];
    labels: string[];
    kinds: string[];
    groupIds: string[];
    hopfBaseIds?: string[];
    hopfRoles?: Uint8Array;
    groups: GalaxySceneGroupView[];
    hopfRibbons: GalaxyHopfRibbonView[];
    lorentzGuides: GalaxyLorentzGuideView[];
    transitPlan?: TransitPlan;
    relationControls?: GalaxyRelationControlView[];
    busemannHorospheres?: GalaxyBusemannHorosphereView[];
    hybridShellPositions?: Float32Array;
    hybridCommitmentPositions?: Float32Array;
    hybridReceipts?: GalaxyHybridNodeReceiptView[];
    hierarchyShellRadii?: Float32Array;
    hierarchyShellRanks?: Uint8Array;
    hierarchyHints?: PhoenixGraphScenePacketHierarchyHint[];
    positions3d: Float32Array;
    positions2d: Float32Array;
    radii: Float32Array;
    colors: Float32Array;
    edgePairs: Uint32Array;
    edgeIds: string[];
    edgeTypes: string[];
    edgeColors: Float32Array;
    edgeAlpha: Float32Array;
    edgeKinds: Uint8Array;
}

export function galaxySceneToV2(scene: GalaxyScene, sourceMode: GalaxySceneSourceMode = 'entities'): GalaxySceneV2 {
    const nodeCount = scene.nodes.length;
    const ids: string[] = new Array(nodeCount);
    const labels: string[] = new Array(nodeCount);
    const kinds: string[] = new Array(nodeCount);
    const groupIds: string[] = new Array(nodeCount);
    const hopfBaseIds: string[] = new Array(nodeCount);
    const hopfRoles = new Uint8Array(nodeCount);
    const positions3d = new Float32Array(nodeCount * 3);
    const positions2d = new Float32Array(nodeCount * 3);
    const radii = new Float32Array(nodeCount);
    const colors = new Float32Array(nodeCount * 3);
    const hasHybridShell = scene.nodes.some((node) => !!node.hybridShellPoint || !!node.hybridShell);
    const hasHybridCommitment = scene.nodes.some((node) => !!node.hybridCommitmentPoint || !!node.hybridCommitment);
    const hasHierarchyShells = scene.nodes.some((node) => hierarchyShellBandForNode(node));
    const hybridShellPositions = hasHybridShell ? new Float32Array(nodeCount * 3) : undefined;
    const hybridCommitmentPositions = hasHybridCommitment ? new Float32Array(nodeCount * 3) : undefined;
    const hierarchyShellRadii = hasHierarchyShells ? new Float32Array(nodeCount) : undefined;
    const hierarchyShellRanks = hasHierarchyShells ? new Uint8Array(nodeCount) : undefined;
    const hybridReceipts: GalaxyHybridNodeReceiptView[] = [];

    for (let index = 0; index < nodeCount; index++) {
        const node = scene.nodes[index];
        ids[index] = node.entity.id;
        labels[index] = node.entity.label;
        kinds[index] = node.entity.kind;
        groupIds[index] = node.groupId || '';
        const hopf = hopfMetadata(node);
        hopfBaseIds[index] = String(hopf?.['baseId'] || '');
        hopfRoles[index] = hopf?.['role'] === 'anchor' ? 1 : hopf?.['role'] === 'fiber' ? 2 : 0;
        writePosition(positions3d, index, node.x, node.y, node.z);
        writePosition(positions2d, index, node.x, node.y, 0);
        radii[index] = node.radius;
        writeColor(colors, index, node);
        if (hybridShellPositions) {
            const point = node.hybridShellPoint ?? node.hybridShell?.point ?? node;
            writePosition(hybridShellPositions, index, point.x, point.y, point.z);
        }
        if (hybridCommitmentPositions) {
            const point = node.hybridCommitmentPoint ?? node.hybridCommitment?.point ?? node;
            writePosition(hybridCommitmentPositions, index, point.x, point.y, point.z);
        }
        const hybridReceipt = hybridNodeReceiptView(node);
        if (hybridReceipt) {
            hybridReceipts.push(hybridReceipt);
        }
        if (hierarchyShellRadii && hierarchyShellRanks) {
            const band = hierarchyShellBandForNode(node);
            if (band) {
                hierarchyShellRadii[index] = band.radius;
                hierarchyShellRanks[index] = band.rank + 1;
            }
        }
    }

    const edgePairs = new Uint32Array(scene.links.length * 2);
    const edgeIds = new Array<string>(scene.links.length);
    const edgeTypes = new Array<string>(scene.links.length);
    const edgeColors = new Float32Array(scene.links.length * 6);
    const edgeAlpha = new Float32Array(scene.links.length);
    const edgeKinds = new Uint8Array(scene.links.length);
    for (let index = 0; index < scene.links.length; index++) {
        const edge = scene.links[index];
        const source = scene.nodes[edge.source];
        const target = scene.nodes[edge.target];
        edgePairs[index * 2] = edge.source;
        edgePairs[index * 2 + 1] = edge.target;
        edgeIds[index] = edge.id;
        edgeTypes[index] = edge.type;
        const relationColor = relationEdgeColor(edge.type, source, target);
        if (relationColor) {
            writeRgbColor(edgeColors, index * 2, relationColor);
            writeRgbColor(edgeColors, index * 2 + 1, relationColor);
        } else {
            writeColor(edgeColors, index * 2, source);
            writeColor(edgeColors, index * 2 + 1, target);
        }
        edgeAlpha[index] = edge.alpha;
        edgeKinds[index] = edge.interGalaxy ? 1 : hierarchyEdgeKind(edge.type);
    }

    return {
        sourceMode,
        layoutMode: scene.layoutMode,
        ids,
        labels,
        kinds,
        groupIds,
        hopfBaseIds,
        hopfRoles,
        groups: scene.groups.map(groupView),
        hopfRibbons: attachSourceColors((scene.hopfRibbons ?? []).map(hopfRibbonView), ids, colors),
        lorentzGuides: attachSourceColors((scene.lorentzGuides ?? []).map(lorentzGuideView), ids, colors),
        transitPlan: scene.transitPlan,
        relationControls: scene.relationControls?.map(relationControlView),
        busemannHorospheres: (scene.busemannHorospheres ?? []).map(busemannHorosphereView),
        hybridShellPositions,
        hybridCommitmentPositions,
        hybridReceipts: hybridReceipts.length ? hybridReceipts : undefined,
        hierarchyShellRadii,
        hierarchyShellRanks,
        positions3d,
        positions2d,
        radii,
        colors,
        edgePairs,
        edgeIds,
        edgeTypes,
        edgeColors,
        edgeAlpha,
        edgeKinds,
    };
}

/**
 * Resolves `sourceColor` from each guide/ribbon's `nodeIds[0]` against the
 * compiled node color buffer. Cheap O(n) pass at compile time only; the
 * renderer reads `sourceColor` when `guideColorMode === 'sourceNode'`.
 * If the source node is missing the guide keeps `sourceColor === undefined`
 * and falls back to its own color/palette.
 */
function attachSourceColors<T extends { nodeIds: string[]; sourceColor?: { r: number; g: number; b: number } }>(
    views: T[],
    ids: string[],
    colors: Float32Array,
): T[] {
    if (!views.length) return views;
    const indexById = new Map<string, number>();
    for (let index = 0; index < ids.length; index++) indexById.set(ids[index], index);
    for (const view of views) {
        const sourceId = view.nodeIds[0];
        const index = sourceId ? indexById.get(sourceId) : undefined;
        if (index === undefined) continue;
        const offset = index * 3;
        view.sourceColor = { r: colors[offset], g: colors[offset + 1], b: colors[offset + 2] };
    }
    return views;
}

function relationControlView(control: GalaxyRelationControl): GalaxyRelationControlView {
    return {
        id: control.id,
        label: control.label,
        kind: control.kind,
        family: control.family,
        noteIds: control.noteIds,
        chunkIds: control.chunkIds,
        entityIds: control.entityIds,
        eventIds: control.eventIds,
        ownerEntityId: control.ownerEntityId,
        regionId: control.regionId,
        sourceNodeIds: control.sourceNodeIds,
        targetNodeIds: control.targetNodeIds,
        evidenceNodeIds: control.evidenceNodeIds,
        participantNodeIds: control.participantNodeIds,
        edgeIds: control.edgeIds,
        position3d: [control.x, control.y, control.z],
        color: { r: control.r / 255, g: control.g / 255, b: control.b / 255 },
        confidence: control.confidence,
    };
}

function hybridNodeReceiptView(node: GalaxyNode): GalaxyHybridNodeReceiptView | null {
    if (!node.hybridShell && !node.hybridCommitment && !node.hybridRenderPoint) {
        return null;
    }

    const renderRadius = node.hybridRenderPoint?.radius ?? Math.hypot(node.x, node.y, node.z);
    return {
        nodeId: node.entity.id,
        shell: node.hybridShell ? hybridShellReceiptView(node.hybridShell) : undefined,
        commitment: node.hybridCommitment ? hybridCommitmentReceiptView(node.hybridCommitment) : undefined,
        renderRadius,
    };
}

function hybridShellReceiptView(receipt: GalaxyHybridShellReceipt): GalaxyHybridShellReceiptView {
    return {
        lane: receipt.lane,
        phase: receipt.phase,
        specificity: receipt.specificity,
        ambiguity: receipt.ambiguity,
        level: receipt.level,
        strength: receipt.strength,
        baseRadius: receipt.baseRadius,
        shellRadius: receipt.shellRadius,
        laneStrength: receipt.laneStrength,
        sourceSignals: receipt.sourceSignals,
    };
}

function hybridCommitmentReceiptView(receipt: GalaxyHybridBusemannReceipt): GalaxyHybridCommitmentReceiptView {
    return {
        family: receipt.family,
        topPrototypeId: receipt.topPrototypeId,
        entropy: receipt.entropy,
        margin: receipt.margin,
        confidence: receipt.confidence,
        promotionReady: receipt.promotionReady,
        radialStrength: receipt.radialStrength,
        source: receipt.source,
        radius: receipt.point.radius,
    };
}

function busemannHorosphereView(spec: GalaxyBusemannHorosphereSpec): GalaxyBusemannHorosphereView {
    const color = hslToRgb(entityColorStore.getRawGraphNodeHsl(spec.colorKind || spec.family || 'graphFact'));
    return {
        prototypeId: spec.prototypeId,
        family: spec.family,
        label: spec.label,
        tau: spec.tau,
        center: spec.center,
        radius: spec.radius,
        color: { r: color.r / 255, g: color.g / 255, b: color.b / 255 },
        opacity: spec.opacity,
    };
}

function hierarchyEdgeKind(type: string): number {
    return /target-parent|note-chunk|chunk-anchor|chunk-entity|anchor-entity|event-chunk|event-entity|memory-entity/i.test(type) ? 2 : 0;
}

function relationEdgeColor(type: string, source: GalaxyNode, target: GalaxyNode): { r: number; g: number; b: number } | null {
    if (hierarchyEdgeKind(type) !== 0) return null;
    const family = relationFamilyFromText(
        type,
        source.entity.label,
        source.entity.metadata?.['preview'],
        target.entity.label,
        target.entity.metadata?.['preview'],
    );
    return family ? hslToRgb(entityColorStore.getRawGraphNodeHsl(family)) : null;
}

function hopfMetadata(node: GalaxyNode): Record<string, unknown> | null {
    const value = node.entity.metadata?.['hopf'];
    return value && typeof value === 'object' ? value as Record<string, unknown> : null;
}

function groupView(group: GalaxyGroup): GalaxySceneGroupView {
    return {
        id: group.id,
        label: group.label,
        kind: group.kind,
        center: group.center,
        radius: group.radius,
        color: { r: group.r / 255, g: group.g / 255, b: group.b / 255 },
        nodeIds: group.nodeIds,
        importance: group.importance,
    };
}

function hopfRibbonView(ribbon: GalaxyHopfRibbon): GalaxyHopfRibbonView {
    const positions2d = ribbon.positions3d.slice();
    for (let index = 2; index < positions2d.length; index += 3) positions2d[index] = 0;
    return {
        id: ribbon.id,
        nodeIds: ribbon.nodeIds,
        positions3d: ribbon.positions3d,
        positions2d,
        color: { r: ribbon.r / 255, g: ribbon.g / 255, b: ribbon.b / 255 },
        importance: ribbon.importance,
        guideKind: ribbon.guideKind,
        guideWeight: ribbon.guideWeight,
    };
}

function lorentzGuideView(guide: GalaxyLorentzGuide): GalaxyLorentzGuideView {
    const positions2d = guide.positions3d.slice();
    for (let index = 2; index < positions2d.length; index += 3) positions2d[index] = 0;
    return {
        id: guide.id,
        nodeIds: guide.nodeIds,
        positions3d: guide.positions3d,
        positions2d,
        color: { r: guide.r / 255, g: guide.g / 255, b: guide.b / 255 },
        importance: guide.importance,
        treeId: guide.treeId,
        treeKind: guide.treeKind,
        level: guide.level,
        guideKind: guide.guideKind,
        guideWeight: guide.guideWeight,
    };
}

function writePosition(buffer: Float32Array, index: number, x: number, y: number, z: number): void {
    const offset = index * 3;
    buffer[offset] = x;
    buffer[offset + 1] = y;
    buffer[offset + 2] = z;
}

function writeColor(buffer: Float32Array, index: number, node: GalaxyNode): void {
    const offset = index * 3;
    buffer[offset] = node.r / 255;
    buffer[offset + 1] = node.g / 255;
    buffer[offset + 2] = node.b / 255;
}

function writeRgbColor(buffer: Float32Array, index: number, color: { r: number; g: number; b: number }): void {
    const offset = index * 3;
    buffer[offset] = color.r / 255;
    buffer[offset + 1] = color.g / 255;
    buffer[offset + 2] = color.b / 255;
}
