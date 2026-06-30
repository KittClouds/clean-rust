import {
    entityColorStore,
    normalizeGraphNodeColorKind,
    normalizeEntityKind,
} from '../../../../../lib/store/entityColorStore';
import {
    activeBusemannPrototypeIds,
    applyHybridBusemannLayout,
    buildBusemannHorosphereSpecs,
    readBusemannSignature,
} from './graph-galaxy-hybrid-busemann-layout';
import { applyLorentzTreeLayout } from './graph-galaxy-lorentz-layout';
import { applySiegelFinslerLayout } from './graph-galaxy-siegel-layout';
import {
    buildHopfReceiptRibbons,
    hopfDirectionFromMetadata,
    type HopfReceiptBase,
} from './graph-galaxy-hopf-receipts';
import { relationFamilyFromText } from './graph-relation-visual-style';
import { buildTransitBackboneGuides } from './graph-transit-backbone-guides';
import { applyTransitLayout } from './graph-transit-layout';
import { buildTransitPlan, type TransitPlan } from './graph-transit-plan';

export type GalaxyLabelMode = 'hover' | 'selected' | 'important' | 'always' | 'off';
export type GalaxyEdgeMode = 'curved' | 'straight' | 'tube' | 'hidden';
export type GalaxyEdgeColorMode = 'aqua' | 'orchid' | 'gold' | 'entityBlend' | 'confidence' | 'muted' | 'cyan';
export type GalaxyBackgroundMode = 'nebula' | 'grid' | 'quiet' | 'void';
export type GalaxyNodeDragMode = 'stretch' | 'force' | 'pin' | 'camera';
export type GalaxyNodeShapeMode = 'atom' | 'halo' | 'sphere';
export type GalaxySphereSurfaceMode = 'solid' | 'glass' | 'spellglass' | 'obsidian' | 'starcore';
// Guides adopt the Style Lab color of their source node.
export type GalaxyGuideColorMode = 'sourceNode';
export type GalaxyLayoutMode = 'single' | 'multiGalaxy' | 'hybridSpace' | 'hopfProjection' | 'lorentzTree' | 'transitManifold' | 'productManifold' | 'siegelFinsler';
export type GalaxyEmbeddingTopologyMode = 'off' | 'clusters' | 'regions' | 'lanes' | 'medoids' | 'outliers' | 'backbone' | 'bridges';
export type GalaxyRenderSourceMode = 'entities' | 'graph' | 'embeddings';

export type GalaxyHybridInteriorMode = 'busemannCommitment';

export type GalaxyPrototypeFamily =
    | 'EntityKind'
    | 'RelationFamily'
    | 'EvidenceAuthority'
    | 'GraphStage'
    | 'ConceptDomain';

export interface GalaxyVec3 {
    x: number;
    y: number;
    z: number;
}

export interface GalaxyBusemannPrototypeScore {
    prototypeId: string;
    family: GalaxyPrototypeFamily;
    score: number;
    probability: number;
}

export interface GalaxyBusemannSignature {
    family: GalaxyPrototypeFamily;

    topPrototypeId: string;
    topScore: number;
    topProbability: number;

    secondPrototypeId?: string | null;
    secondScore?: number | null;
    secondProbability?: number | null;

    margin: number;
    entropy: number;
    ambiguityScore: number;
    classificationConfidence: number;
    promotionReady: boolean;
    radialStrength: number;

    topKScores?: GalaxyBusemannPrototypeScore[];
}

export interface GalaxyBusemannPrototype {
    prototypeId: string;
    family: GalaxyPrototypeFamily;
    label: string;

    /**
     * Unit-ish boundary direction on the hybrid shell.
     * Renderer normalizes this defensively.
     */
    direction: GalaxyVec3;

    colorKind?: string;
}

export interface GalaxyHybridInteriorState {
    mode: GalaxyHybridInteriorMode;

    /**
     * Preferred: backend-supplied Poincare/interior render coordinate.
     * If absent, frontend approximates from prototype direction + confidence.
     */
    point?: GalaxyVec3;

    /**
     * Optional semantic direction, useful for ambiguous nodes.
     */
    surfaceDirection?: GalaxyVec3;

    signature?: GalaxyBusemannSignature;
}

export interface GalaxyHybridPlacementPoint extends GalaxyVec3 {
    radius: number;
}

export interface GalaxyHybridShellReceipt {
    mode: 'hybridShell';
    geometryVersion: 'hybrid_shell_anatomy_v1';
    lane: string;
    phase: number;
    specificity: number;
    ambiguity: number;
    level: number;
    strength: number;
    baseRadius: number;
    shellRadius: number;
    laneStrength: number;
    direction: GalaxyVec3;
    point: GalaxyHybridPlacementPoint;
    sourceSignals: string[];
}

export interface GalaxyHybridBusemannReceipt {
    mode: 'busemannCommitment';
    family: GalaxyPrototypeFamily;
    topPrototypeId: string;
    entropy: number;
    margin: number;
    confidence: number;
    promotionReady: boolean;
    radialStrength: number;
    point: GalaxyHybridPlacementPoint;
    source: 'backendPoint' | 'frontendCommitment';
}

export interface GalaxyBusemannHorosphereSpec {
    prototypeId: string;
    family: string;
    label: string;
    tau: number;
    center: GalaxyVec3;
    radius: number;
    opacity: number;
    colorKind?: string;
}

export interface GalaxyRenderSettings {
    labelMode: GalaxyLabelMode;
    edgeMode: GalaxyEdgeMode;
    edgeColorMode: GalaxyEdgeColorMode;
    glow: number;
    edgeOpacity: number;
    edgeWidth: number;
    edgeLength: number;
    edgeCurveStrength: number;
    nodeDistance: number;
    particleFlow: boolean;
    particleFlowMode?: GalaxyParticleFlowMode;
    particleSize: number;
    particleSpeed: number;
    particleOpacity: number;
    autoRotate: boolean;
    backgroundMode: GalaxyBackgroundMode;
    nodeDragMode: GalaxyNodeDragMode;
    nodeShape: GalaxyNodeShapeMode;
    sphereSurface?: GalaxySphereSurfaceMode;
    clickFocus: boolean;
    labelLimit: number;
    selectedPulse: boolean;
    layoutMode: GalaxyLayoutMode;
    hybridShellVisible: boolean;
    hybridShellOpacity: number;

    /**
     * New hybrid interior rendering controls.
     * Still uses layoutMode === 'hybridSpace'.
     */
    hybridInteriorMode?: GalaxyHybridInteriorMode;
    hybridInteriorVisible?: boolean;
    hybridHorospheresVisible?: boolean;
    hybridPrototypeRaysVisible?: boolean;
    hybridAmbiguityHalos?: boolean;
    hybridPromotionPulse?: boolean;
    hybridHorosphereOpacity?: number;
    hybridInteriorOpacity?: number;
    hybridInteriorScale?: number;

    hopfSpaceVisible: boolean;
    hopfSpaceIntensity: number;
    lorentzSpaceVisible: boolean;
    lorentzSpaceIntensity: number;
    embeddingTopologyMode: GalaxyEmbeddingTopologyMode;
    sourceMode: GalaxyRenderSourceMode;

    /**
     * Dedicated guide visibility + color controls.
     *
     * These are intentionally separate from the space visibility controls so
     * routes and fibers can each be turned off on their own regardless of layout
     * mode. When undefined the renderer falls back to the matching space flag,
     * preserving prior behavior for persisted settings.
     */
    guideRoutesVisible?: boolean;
    guideFibersVisible?: boolean;
    /** See {@link GalaxyGuideColorMode}. */
    guideColorMode?: GalaxyGuideColorMode;
}

export interface GalaxyInputEdge {
    id: string;
    sourceId: string;
    targetId: string;
    type: string;
    confidence: number;
    metadata?: Record<string, unknown>;
}

export interface GalaxyQueryFocus {
    queryNodeId: string;
    primaryNodeIds: string[];
    secondaryNodeIds: string[];
    edgeIds: string[];
}

export interface GalaxyRenderableNode {
    id: string;
    label: string;
    kind: string;
    aliases?: string[];
    totalMentions?: number;
    atlasX?: number;
    atlasY?: number;
    atlasZ?: number;
    colorHsl?: string;
    metadata?: Record<string, unknown> & {
        sourceEntityId?: string;
        sourceId?: string;
        sourceTitle?: string;
        sourceType?: string;
        sourceSystem?: string;
        graphColorKind?: string;
        graphRelationFamily?: string;
        noteId?: string;
        galaxyId?: string;
        galaxyRole?: 'primary' | 'context';
        galaxyOffset?: { x: number; y: number; z: number };
        galaxyOpacity?: number;
    };
}

export interface Rgb {
    r: number;
    g: number;
    b: number;
}

export interface GalaxyNode extends Rgb {
    entity: GalaxyRenderableNode;
    x: number;
    y: number;
    z: number;
    baseX: number;
    baseY: number;
    baseZ: number;
    radius: number;
    sx: number;
    sy: number;
    depth: number;
    galaxyOpacity: number;
    groupId?: string;
    hybridShell?: GalaxyHybridShellReceipt;
    hybridShellPoint?: GalaxyHybridPlacementPoint;
    hybridCommitment?: GalaxyHybridBusemannReceipt;
    hybridCommitmentPoint?: GalaxyHybridPlacementPoint;
    hybridRenderPoint?: GalaxyHybridPlacementPoint;
}

export type GalaxyParticleFlowMode = 'swarm' | 'walk';

export interface GalaxyEdge {
    id: string;
    source: number;
    target: number;
    type: string;
    confidence: number;
    alpha: number;
    curve: number;
    flowOffset: number;
    interGalaxy?: boolean;
    metadata?: Record<string, unknown>;
}

export interface GalaxyRelationControl extends Rgb {
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
    x: number;
    y: number;
    z: number;
    confidence: number;
}

export interface GalaxyGroup extends Rgb {
    id: string;
    label: string;
    kind: 'note' | 'folder' | 'narrative' | 'semantic-cluster' | 'entity-cluster' | 'query' | 'other';
    center: { x: number; y: number; z: number };
    radius: number;
    nodeIds: string[];
    importance: number;
}

export interface GalaxyHopfRibbon extends Rgb {
    id: string;
    nodeIds: string[];
    positions3d: Float32Array;
    importance: number;
    guideKind: 'dataFiber' | 'crossFiberBraid' | 'spaceFiber' | 'torusBand' | 'axis';
    guideWeight: number;
}

export interface GalaxyLorentzGuide extends Rgb {
    id: string;
    nodeIds: string[];
    positions3d: Float32Array;
    importance: number;
    treeId: string;
    treeKind: string;
    level: number;
    guideKind: 'membership' | 'rootLane' | 'levelShell' | 'wAxis';
    guideWeight: number;
}

export interface GalaxyScene {
    nodes: GalaxyNode[];
    links: GalaxyEdge[];
    layoutMode: GalaxyLayoutMode;
    groups: GalaxyGroup[];
    transitPlan?: TransitPlan;
    relationControls?: GalaxyRelationControl[];
    hopfRibbons?: GalaxyHopfRibbon[];
    lorentzGuides?: GalaxyLorentzGuide[];
    busemannHorospheres?: GalaxyBusemannHorosphereSpec[];
}

export const DEFAULT_GALAXY_SETTINGS: GalaxyRenderSettings = {
    labelMode: 'hover',
    edgeMode: 'curved',
    edgeColorMode: 'entityBlend',
    glow: 1,
    edgeOpacity: 0.34,
    edgeWidth: 0.45,
    edgeLength: 1,
    edgeCurveStrength: 0.55,
    nodeDistance: 1,
    particleFlow: false,
    particleFlowMode: 'swarm',
    particleSize: 1,
    particleSpeed: 1,
    particleOpacity: 0.72,
    autoRotate: false,
    backgroundMode: 'nebula',
    nodeDragMode: 'stretch',
    nodeShape: 'atom',
    sphereSurface: 'solid',
    clickFocus: false,
    labelLimit: 14,
    selectedPulse: true,
    layoutMode: 'single',
    hybridShellVisible: true,
    hybridShellOpacity: 1,
    hybridInteriorMode: 'busemannCommitment',
    hybridInteriorVisible: true,
    hybridHorospheresVisible: false,
    hybridPrototypeRaysVisible: true,
    hybridAmbiguityHalos: true,
    hybridPromotionPulse: true,
    hybridHorosphereOpacity: 0.6,
    hybridInteriorOpacity: 1,
    hybridInteriorScale: 1,
    hopfSpaceVisible: true,
    hopfSpaceIntensity: 1,
    lorentzSpaceVisible: true,
    lorentzSpaceIntensity: 1,
    embeddingTopologyMode: 'off',
    sourceMode: 'entities',
    guideRoutesVisible: true,
    guideFibersVisible: true,
    guideColorMode: 'sourceNode',
};

export function mergeGalaxySettings(settings?: Partial<GalaxyRenderSettings> | null): GalaxyRenderSettings {
    const merged = { ...DEFAULT_GALAXY_SETTINGS, ...settings };
    if (merged.layoutMode === 'productManifold') merged.layoutMode = 'transitManifold';
    if (merged.particleFlowMode !== 'walk') merged.particleFlowMode = 'swarm';
    if ((merged.sphereSurface as string) === 'lattice') merged.sphereSurface = 'starcore';
    if (!['solid', 'glass', 'spellglass', 'obsidian', 'starcore'].includes(merged.sphereSurface || '')) {
        merged.sphereSurface = 'solid';
    }
    merged.guideColorMode = 'sourceNode';
    if (typeof merged.guideRoutesVisible !== 'boolean') merged.guideRoutesVisible = merged.lorentzSpaceVisible !== false;
    if (typeof merged.guideFibersVisible !== 'boolean') merged.guideFibersVisible = merged.hopfSpaceVisible !== false;
    if (merged.edgeColorMode === 'cyan') merged.edgeColorMode = 'aqua';
    merged.edgeCurveStrength = Math.min(1.2, Math.max(0.25, merged.edgeCurveStrength));
    merged.edgeWidth = Math.min(1.1, Math.max(0.15, merged.edgeWidth));
    merged.hybridShellOpacity = Math.min(1, Math.max(0, merged.hybridShellOpacity));
    merged.hybridHorosphereOpacity = Math.min(1, Math.max(0, merged.hybridHorosphereOpacity ?? 0.6));
    merged.hybridInteriorOpacity = Math.min(1, Math.max(0, merged.hybridInteriorOpacity ?? 1));
    merged.hybridInteriorScale = Math.min(1.4, Math.max(0.35, merged.hybridInteriorScale ?? 1));
    merged.hopfSpaceIntensity = Math.min(1.4, Math.max(0, merged.hopfSpaceIntensity));
    merged.lorentzSpaceIntensity = Math.min(1.4, Math.max(0, merged.lorentzSpaceIntensity));
    return merged;
}

export function isTransitLayoutMode(mode: GalaxyLayoutMode | string | null | undefined): boolean {
    return mode === 'transitManifold' || mode === 'productManifold';
}

export function buildGalaxyScene(
    entitiesInput: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
    settings: GalaxyRenderSettings,
): GalaxyScene {
    const relationPlan = settings.sourceMode === 'embeddings'
        ? { nodes: entitiesInput, edges, controls: [] }
        : compileRelationControlPlan(entitiesInput, edges);
    const entities = orderEntitiesForStableRender(relationPlan.nodes);
    assertNoImplicitNodeDrop(relationPlan.nodes.length, entities.length);
    const preserveAtlasLayout = shouldPreserveAtlasLayout(entities);
    const idToIndex = new Map<string, number>();
    const nodes = entities.map((entity, index) => {
        idToIndex.set(entity.id, index);
        const total = Math.max(1, entities.length);
        const seeded = hasAtlasSeed(entity);
        const y = 1 - (index / Math.max(1, total - 1)) * 2;
        const radial = Math.sqrt(Math.max(0, 1 - y * y));
        const angle = index * 2.399963229728653 + stableUnit(entity.id) * 0.48;
        const kindBias = stableUnit(String(entity.kind)) - 0.5;
        const x = seeded ? clamp(entity.atlasX!, -2.25, 2.25) : Math.cos(angle) * radial * 1.05 + kindBias * 0.18;
        const yy = seeded ? clamp(entity.atlasY!, -1.85, 1.85) : y * 0.74 + (stableUnit(`${entity.id}:y`) - 0.5) * 0.12;
        const z = seeded ? clamp(entity.atlasZ!, -2.25, 2.25) : Math.sin(angle) * radial * 0.95 + kindBias * 0.26;
        return {
            entity,
            x,
            y: yy,
            z,
            baseX: x,
            baseY: yy,
            baseZ: z,
            radius: Math.min(5.8, 2.1 + Math.sqrt(Math.max(1, entity.totalMentions || 1)) * 0.32),
            ...hslToRgb(resolveGalaxyNodeColorHsl(entity)),
            sx: 0,
            sy: 0,
            depth: 0,
            galaxyOpacity: Number(entity.metadata?.galaxyOpacity ?? 1),
        };
    });

    const links = buildLinks(relationPlan.edges, idToIndex);
    applyEmbeddingTopologyLens(nodes, links, settings);
    if (settings.layoutMode === 'hybridSpace') {
        applyGalaxyMetadata(nodes);
        applyHybridSpaceLayout(nodes, links);
        const busemannHorospheres = applyBusemannCommitmentOverlay(nodes, settings);
        return attachRelationControls({ nodes, links, layoutMode: 'hybridSpace', groups: [], busemannHorospheres }, relationPlan.controls);
    }

    if (settings.layoutMode === 'hopfProjection') {
        applyGalaxyMetadata(nodes);
        const hopfRibbons = applyHopfProjectionLayout(nodes, links);
        return attachRelationControls({ nodes, links, layoutMode: 'hopfProjection', groups: [], hopfRibbons }, relationPlan.controls);
    }

    if (settings.layoutMode === 'lorentzTree') {
        applyGalaxyMetadata(nodes);
        const lorentzGuides = applyLorentzTreeLayout(nodes, links, { sourceMode: settings.sourceMode });
        return attachRelationControls({ nodes, links, layoutMode: 'lorentzTree', groups: [], lorentzGuides }, relationPlan.controls);
    }

    if (isTransitLayoutMode(settings.layoutMode)) {
        const transitPlan = buildTransitPlan(entitiesInput, edges);
        applyGalaxyMetadata(nodes);
        applyTransitLayout(nodes, links, transitPlan);
        const lorentzGuides = buildTransitBackboneGuides(transitPlan);
        return attachRelationControls({ nodes, links, layoutMode: 'transitManifold', groups: [], transitPlan, lorentzGuides }, relationPlan.controls);
    }

    if (settings.layoutMode === 'siegelFinsler') {
        applyGalaxyMetadata(nodes);
        const lorentzGuides = applySiegelFinslerLayout(nodes, links);
        return attachRelationControls({ nodes, links, layoutMode: 'siegelFinsler', groups: [], lorentzGuides }, relationPlan.controls);
    }

    const groupPlan = settings.layoutMode === 'multiGalaxy' ? buildGroupPlan(nodes) : [];
    if (groupPlan.length > 1) {
        applyGalaxyMetadata(nodes);
        const groups = applyMultiGalaxyLayout(nodes, links, groupPlan);
        return attachRelationControls({ nodes, links, layoutMode: 'multiGalaxy', groups }, relationPlan.controls);
    }

    if (!preserveAtlasLayout) {
        relaxNodes(nodes, links, settings);
    }
    applyGalaxyMetadata(nodes);
    return attachRelationControls({ nodes, links, layoutMode: 'single', groups: [] }, relationPlan.controls);
}

function hasAtlasSeed(entity: GalaxyRenderableNode): boolean {
    return Number.isFinite(entity.atlasX) && Number.isFinite(entity.atlasY) && Number.isFinite(entity.atlasZ);
}

function shouldPreserveAtlasLayout(entities: GalaxyRenderableNode[]): boolean {
    return entities.length > 0 && entities.every(hasAtlasSeed);
}

interface RelationControlDraft {
    id: string;
    label: string;
    kind: string;
    family: string;
    noteIds: string[];
    chunkIds: string[];
    entityIds: string[];
    eventIds: string[];
    ownerEntityId: string;
    sourceNodeIds: string[];
    targetNodeIds: string[];
    evidenceNodeIds: string[];
    participantNodeIds: string[];
    edgeIds: string[];
    confidence: number;
}

interface RelationControlPlan {
    nodes: GalaxyRenderableNode[];
    edges: GalaxyInputEdge[];
    controls: RelationControlDraft[];
}

export function hasRelationControlNodes(entities: GalaxyRenderableNode[]): boolean {
    return entities.some(isRelationControlNode);
}

function compileRelationControlPlan(entities: GalaxyRenderableNode[], edges: GalaxyInputEdge[]): RelationControlPlan {
    const factNodes = new Map(entities.filter(isRelationControlNode).map((node) => [node.id, node]));
    if (!factNodes.size) return { nodes: entities, edges, controls: [] };
    const controls = new Map<string, RelationControlDraft>();
    for (const fact of factNodes.values()) controls.set(fact.id, relationControlDraft(fact));
    const topologyEdges: GalaxyInputEdge[] = [];
    for (const edge of edges) {
        const sourceFact = factNodes.has(edge.sourceId);
        const targetFact = factNodes.has(edge.targetId);
        if (!sourceFact && !targetFact) {
            topologyEdges.push(edge);
            continue;
        }
        if (sourceFact && !targetFact) addRelationRole(controls.get(edge.sourceId), edge, edge.targetId, edge.type);
        if (targetFact && !sourceFact) addRelationRole(controls.get(edge.targetId), edge, edge.sourceId, edge.type);
    }
    const activeControls = [...controls.values()].filter((control) => uniqueControlIds(control.participantNodeIds).length > 1);
    for (const control of activeControls) {
        for (const [sourceId, targetId] of relationEndpointPairs(control)) {
            topologyEdges.push({
                id: `relation-control:${control.id}:${sourceId}:${targetId}`,
                sourceId,
                targetId,
                type: control.family || control.label || 'relationship',
                confidence: control.confidence,
                metadata: {
                    relationControl: true,
                    relationControlId: control.id,
                    relationFamily: control.family,
                    relationLabel: control.label,
                    noteIds: control.noteIds,
                    chunkIds: control.chunkIds,
                    entityIds: control.entityIds,
                    eventIds: control.eventIds,
                    ownerEntityId: control.ownerEntityId,
                    sourceNodeIds: control.sourceNodeIds,
                    targetNodeIds: control.targetNodeIds,
                    evidenceNodeIds: control.evidenceNodeIds,
                },
            });
        }
    }
    return {
        nodes: entities.filter((node) => !factNodes.has(node.id)),
        edges: topologyEdges,
        controls: activeControls,
    };
}

function isRelationControlNode(entity: GalaxyRenderableNode): boolean {
    const rawSourceType = stringValue(entity.metadata?.['sourceType']);
    const sourceType = relationKindKey(rawSourceType || stringValue(entity.kind));
    if (sourceType === 'graph-fact' || sourceType === 'temporal-fact' || sourceType === 'causal-fact') return true;
    return !rawSourceType && /^embed:(graph-fact|temporalFact|causalFact):/.test(entity.id);
}

function relationControlDraft(fact: GalaxyRenderableNode): RelationControlDraft {
    const metadata = fact.metadata || {};
    const family = firstGraphNodeColorKind(
        stringValue(metadata['graphRelationFamily']),
        stringValue(metadata['graphColorKind']),
        stringValue(metadata['signalLane']),
        stringValue(metadata['productLaneKind']),
        relationFamilyFromText(fact.label, metadata['preview']) || undefined,
        fact.kind,
    ) || 'graphFact';
    const draft: RelationControlDraft = {
        id: fact.id,
        label: fact.label || fact.id,
        kind: relationKindKey(stringValue(metadata['sourceType'] || fact.kind)),
        family,
        noteIds: uniqueControlIds([stringValue(metadata['noteId']), ...arrayStringValues(metadata['supportNoteIds'])]),
        chunkIds: uniqueControlIds([stringValue(metadata['chunkId']), ...arrayStringValues(metadata['supportChunkIds'])]),
        entityIds: uniqueControlIds([stringValue(metadata['sourceEntityId']), stringValue(metadata['entityId']), stringValue(metadata['canonicalEntityId'])]),
        eventIds: uniqueControlIds([stringValue(metadata['eventId']), stringValue(metadata['sourceEventId']), stringValue(metadata['targetEventId'])]),
        ownerEntityId: stringValue(metadata['sourceEntityId'] || metadata['entityId'] || metadata['canonicalEntityId']),
        sourceNodeIds: [],
        targetNodeIds: [],
        evidenceNodeIds: [],
        participantNodeIds: [],
        edgeIds: [],
        confidence: 0,
    };
    for (const parentId of relationParentIds(fact)) {
        addControlId(draft.participantNodeIds, parentId);
        addControlContext(draft, parentId);
        if (/^embed:(entity|event):/.test(parentId)) addControlId(draft.sourceNodeIds, parentId);
        if (/^embed:(chunk|anchor):/.test(parentId)) addControlId(draft.evidenceNodeIds, parentId);
    }
    return draft;
}

function relationParentIds(fact: GalaxyRenderableNode): string[] {
    const metadata = fact.metadata || {};
    const lorentz = (metadata['lorentz'] || {}) as Record<string, unknown>;
    return uniqueControlIds([
        ...arrayStringValues(metadata['signalParentIds']),
        ...arrayStringValues(metadata['parentIds']),
        stringValue(lorentz['parentNodeId']),
    ]);
}

function addRelationRole(control: RelationControlDraft | undefined, edge: GalaxyInputEdge, nodeId: string, roleValue: string): void {
    if (!control || isRelationControlId(nodeId)) return;
    const role = relationRole(roleValue);
    addControlId(control.participantNodeIds, nodeId);
    addControlId(control.edgeIds, edge.id);
    addControlContext(control, nodeId);
    control.confidence = Math.max(control.confidence, edge.confidence || 0.55);
    if (role === 'source') addControlId(control.sourceNodeIds, nodeId);
    else if (role === 'target') addControlId(control.targetNodeIds, nodeId);
    else if (role === 'evidence') addControlId(control.evidenceNodeIds, nodeId);
}

function relationRole(value: string): 'source' | 'target' | 'evidence' | 'other' {
    const role = String(value || '').toLowerCase();
    if (/evidence|anchor|support/.test(role)) return 'evidence';
    if (/target|effect|listener|object|state|location|time/.test(role)) return 'target';
    if (/source|cause|subject|actor|speaker|left/.test(role)) return 'source';
    return 'other';
}

function relationEndpointPairs(control: RelationControlDraft): Array<[string, string]> {
    const sources = uniqueControlIds(control.sourceNodeIds.length ? control.sourceNodeIds : control.participantNodeIds);
    const targets = uniqueControlIds(control.targetNodeIds);
    const pairs: Array<[string, string]> = [];
    if (sources.length && targets.length) {
        for (const source of sources) {
            for (const target of targets) {
                if (source !== target) pairs.push([source, target]);
                if (pairs.length >= 16) return pairs;
            }
        }
        return pairs;
    }
    const participants = uniqueControlIds(control.participantNodeIds);
    for (let left = 0; left < participants.length; left++) {
        for (let right = left + 1; right < participants.length; right++) {
            pairs.push([participants[left], participants[right]]);
            if (pairs.length >= 16) return pairs;
        }
    }
    return pairs;
}

function attachRelationControls(scene: GalaxyScene, drafts: RelationControlDraft[]): GalaxyScene {
    if (!drafts.length) return scene;
    const byId = new Map(scene.nodes.map((node) => [node.entity.id, node]));
    const controls = drafts
        .map((draft) => materializeRelationControl(draft, byId))
        .filter((control): control is GalaxyRelationControl => !!control);
    return controls.length ? { ...scene, relationControls: controls } : scene;
}

function materializeRelationControl(draft: RelationControlDraft, byId: Map<string, GalaxyNode>): GalaxyRelationControl | null {
    const participantIds = uniqueControlIds(draft.participantNodeIds).filter((id) => byId.has(id));
    if (participantIds.length < 2) return null;
    const anchors = uniqueControlIds([...draft.sourceNodeIds, ...draft.targetNodeIds]).filter((id) => byId.has(id));
    const positionIds = anchors.length >= 2 ? anchors : participantIds;
    const point = averageNodePosition(positionIds, byId);
    const color = hslToRgb(entityColorStore.getRawGraphNodeHsl(draft.family));
    const context = materializeRelationContext(draft, participantIds, byId);
    return {
        ...color,
        ...draft,
        ...context,
        sourceNodeIds: draft.sourceNodeIds.filter((id) => byId.has(id)),
        targetNodeIds: draft.targetNodeIds.filter((id) => byId.has(id)),
        evidenceNodeIds: draft.evidenceNodeIds.filter((id) => byId.has(id)),
        participantNodeIds: participantIds,
        x: point.x,
        y: point.y,
        z: point.z,
        confidence: draft.confidence || 0.55,
    };
}

function addControlContext(control: RelationControlDraft, nodeId: string): void {
    addControlId(control.noteIds, nodeId.match(/^embed:note:(.+)$/)?.[1] || nodeId.match(/^embed:structure-root:([^:]+)/)?.[1] || '');
    addControlId(control.chunkIds, nodeId.match(/^embed:chunk:(.+)$/)?.[1] || '');
    addControlId(control.entityIds, entityIdFromNodeId(nodeId));
    addControlId(control.eventIds, nodeId.match(/^embed:event:(.+)$/)?.[1] || '');
}

function materializeRelationContext(
    draft: RelationControlDraft,
    participantIds: string[],
    byId: Map<string, GalaxyNode>,
): Pick<GalaxyRelationControl, 'noteIds' | 'chunkIds' | 'entityIds' | 'eventIds' | 'ownerEntityId' | 'regionId'> {
    const noteIds = [...draft.noteIds];
    const chunkIds = [...draft.chunkIds];
    const entityIds = [...draft.entityIds];
    const eventIds = [...draft.eventIds];
    let ownerEntityId = draft.ownerEntityId;
    for (const id of participantIds) {
        const node = byId.get(id);
        const ownership = (node?.entity.metadata?.['productOwnership'] || {}) as Record<string, unknown>;
        mergeControlContext(noteIds, arrayStringValues(ownership['noteIds']));
        mergeControlContext(chunkIds, arrayStringValues(ownership['chunkIds']));
        mergeControlContext(entityIds, arrayStringValues(ownership['entityIds']));
        mergeControlContext(eventIds, arrayStringValues(ownership['eventIds']));
        addControlId(noteIds, stringValue(node?.entity.metadata?.['noteId']));
        addControlId(chunkIds, stringValue(node?.entity.metadata?.['chunkId']));
        addControlId(entityIds, stringValue(node?.entity.metadata?.['sourceEntityId'] || node?.entity.metadata?.['entityId'] || node?.entity.metadata?.['canonicalEntityId']));
        addControlId(entityIds, entityIdFromNodeId(id));
        addControlId(eventIds, id.match(/^embed:event:(.+)$/)?.[1] || '');
        if (!ownerEntityId) ownerEntityId = stringValue(ownership['ownerEntityId']) || entityIdFromNodeId(id);
    }
    const note = uniqueControlIds(noteIds)[0] || 'global';
    const chunk = uniqueControlIds(chunkIds)[0] || '';
    const owner = ownerEntityId || uniqueControlIds(entityIds)[0] || '';
    const regionId = chunk
        ? `transit:story:${note}:chunk:${chunk}${owner ? `:owner:${owner}` : ''}`
        : owner
            ? `transit:story:${note}:owner:${owner}`
            : `transit:story:${note}:signals:${draft.family || draft.kind || 'relationship'}`;
    return {
        noteIds: uniqueControlIds(noteIds),
        chunkIds: uniqueControlIds(chunkIds),
        entityIds: uniqueControlIds(entityIds),
        eventIds: uniqueControlIds(eventIds),
        ownerEntityId: owner,
        regionId,
    };
}

function mergeControlContext(target: string[], source: string[]): void {
    for (const item of source) addControlId(target, item);
}

function entityIdFromNodeId(id: string): string {
    return id.match(/^embed:entity:(.+)$/)?.[1] || '';
}

function averageNodePosition(ids: string[], byId: Map<string, GalaxyNode>): { x: number; y: number; z: number } {
    let x = 0, y = 0, z = 0, count = 0;
    for (const id of ids) {
        const node = byId.get(id);
        if (!node) continue;
        x += node.x;
        y += node.y;
        z += node.z;
        count += 1;
    }
    return count ? { x: x / count, y: y / count, z: z / count } : { x: 0, y: 0, z: 0 };
}

function addControlId(ids: string[], id: string): void {
    if (id && !ids.includes(id)) ids.push(id);
}

function uniqueControlIds(ids: string[]): string[] {
    return [...new Set(ids.filter(Boolean))].sort();
}

function arrayStringValues(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => stringValue(item)).filter(Boolean) : [];
}

function isRelationControlId(id: string): boolean {
    return /^embed:(graph-fact|temporalFact|causalFact):/.test(id);
}

function relationKindKey(value: string): string {
    const key = String(value || '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
    if (/graph[-_]?fact|relationship/.test(key)) return 'graph-fact';
    if (/temporal[-_]?fact/.test(key)) return 'temporal-fact';
    if (/causal[-_]?fact/.test(key)) return 'causal-fact';
    return key.replace(/_/g, '-');
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

function buildLinks(edges: GalaxyInputEdge[], idToIndex: Map<string, number>): GalaxyEdge[] {
    const seen = new Set<string>();
    const links: GalaxyEdge[] = [];
    const orderedEdges = [...edges].sort((left, right) =>
        galaxyEdgePriority(right) - galaxyEdgePriority(left)
        || right.confidence - left.confidence
        || left.id.localeCompare(right.id),
    );
    for (const edge of orderedEdges) {
        const source = idToIndex.get(edge.sourceId);
        const target = idToIndex.get(edge.targetId);
        if (source === undefined || target === undefined || source === target) {
            continue;
        }
        const key = source < target
            ? `${source}:${target}:${edge.type}`
            : `${target}:${source}:${edge.type}`;
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        links.push({
            id: edge.id,
            source,
            target,
            type: edge.type,
            confidence: edge.confidence,
            alpha: Math.min(0.34, 0.052 + Math.max(0, edge.confidence) * 0.045),
            curve: (stableUnit(`${edge.id}:curve`) - 0.5) * 1.35,
            flowOffset: stableUnit(`${edge.id}:flow`),
            metadata: edge.metadata,
        });
    }
    return links;
}

function galaxyEdgePriority(edge: GalaxyInputEdge): number {
    if (isStructuralGalaxyInputEdge(edge)) return 100;
    const type = String(edge.type || '').toLowerCase();
    if (type === 'embedding-backbone') return 80;
    if (type === 'embedding-bridge') return 70;
    if (/temporal|causal|event/.test(type)) return 60;
    if (/relationship|relation|fact/.test(type)) return 45;
    return 20;
}

function isStructuralGalaxyInputEdge(edge: GalaxyInputEdge): boolean {
    return /target-parent|note-chunk|chunk-anchor|chunk-entity|anchor-entity|event-chunk|event-entity|memory-entity/i.test(String(edge.type || ''));
}

function applyEmbeddingTopologyLens(
    nodes: GalaxyNode[],
    links: GalaxyEdge[],
    settings: GalaxyRenderSettings,
): void {
    const mode = settings.embeddingTopologyMode;
    if (mode === 'off') return;
    const incident = topologyIncidentIndexes(nodes, links, mode);
    for (const [index, node] of nodes.entries()) {
        const meta = node.entity.metadata || {};
        const isMedoid = meta['embeddingMedoidTargetId'] === node.entity.id;
        const outlierScore = Number(meta['embeddingOutlierScore'] || 0);
        const hubScore = Number(meta['embeddingHubScore'] || 0);
        let boost = 0.72;
        if (mode === 'clusters' && meta['embeddingClusterId']) boost = 1 + Math.min(0.32, hubScore * 0.18);
        else if (mode === 'medoids') boost = isMedoid ? 1.55 : 0.62;
        else if (mode === 'outliers') boost = outlierScore >= 0.72 ? 1.72 : 0.54;
        else if (mode === 'regions') boost = productRegionBoost(String(meta['productRegionRole'] || ''));
        else if (mode === 'lanes') boost = 0.72 + productLaneWeight(meta) * 0.58;
        else if (incident.has(index)) boost = 1.32;
        node.radius *= boost;
        if (embeddingLensMayRecolor(node)) {
            if (mode === 'clusters' && meta['embeddingClusterId']) {
                const color = hslToRgb(clusterLensHsl(String(meta['embeddingClusterId'])));
                node.r = Math.round(node.r * 0.58 + color.r * 0.42);
                node.g = Math.round(node.g * 0.58 + color.g * 0.42);
                node.b = Math.round(node.b * 0.58 + color.b * 0.42);
            } else if (mode === 'regions' && meta['productRegionRole']) {
                mixNodeColor(node, productRegionHsl(String(meta['productRegionRole'])), 0.48);
            } else if (mode === 'lanes' && meta['productLaneKind']) {
                mixNodeColor(node, productLaneHsl(String(meta['productLaneKind'])), 0.5);
            }
        }
    }
    for (const link of links) {
        const role = embeddingEdgeRole(link);
        if (!role) {
            link.alpha *= mode === 'clusters' || mode === 'regions' || mode === 'lanes' ? 0.62 : 0.22;
            continue;
        }
        const selected = mode === 'backbone' && role === 'backbone'
            || mode === 'bridges' && role === 'bridge'
            || mode === 'clusters'
            || mode === 'regions'
            || mode === 'lanes';
        link.alpha = selected ? Math.min(0.5, link.alpha * 2.35 + 0.05) : link.alpha * 0.24;
        link.curve *= selected ? 1.12 : 0.72;
    }
}

function topologyIncidentIndexes(
    nodes: GalaxyNode[],
    links: GalaxyEdge[],
    mode: GalaxyEmbeddingTopologyMode,
): Set<number> {
    const out = new Set<number>();
    if (mode !== 'backbone' && mode !== 'bridges') return out;
    const acceptedRole = mode === 'backbone' ? 'backbone' : 'bridge';
    for (const link of links) {
        if (embeddingEdgeRole(link) !== acceptedRole) continue;
        out.add(link.source);
        out.add(link.target);
    }
    return out;
}

function embeddingEdgeRole(link: GalaxyEdge): 'local' | 'backbone' | 'bridge' | '' {
    const type = String(link.type || '').toLowerCase();
    if (type === 'embedding-backbone') return 'backbone';
    if (type === 'embedding-bridge') return 'bridge';
    if (type === 'embedding-local') return 'local';
    return '';
}

function embeddingLensMayRecolor(node: GalaxyNode): boolean {
    return firstGraphNodeColorKind(
        stringValue(node.entity.metadata?.['graphColorKind']),
        stringValue(node.entity.metadata?.['graphKind']),
        stringValue(node.entity.metadata?.['styleKey']),
        stringValue(node.entity.metadata?.['atlasKind']),
        stringValue(node.entity.metadata?.['sourceType']),
        node.entity.kind,
    ) !== 'chunk';
}

function clusterLensHsl(clusterId: string): string {
    const hue = Math.round(stableUnit(clusterId) * 360);
    return `${hue} 72% 61%`;
}

function productRegionBoost(role: string): number {
    if (role === 'core') return 1.38;
    if (role === 'backbone') return 1.24;
    if (role === 'bridge') return 1.44;
    if (role === 'boundary') return 1.05;
    if (role === 'outlier') return 1.56;
    return 0.72;
}

function productLaneWeight(meta: Record<string, unknown>): number {
    const product = meta['product'] as { lanes?: { laneWeights?: Record<string, number> } } | undefined;
    const lane = String(meta['productLaneKind'] || '');
    return Number(product?.lanes?.laneWeights?.[lane] || 0.55);
}

function mixNodeColor(node: GalaxyNode, rawHsl: string, amount: number): void {
    const color = hslToRgb(rawHsl);
    node.r = Math.round(node.r * (1 - amount) + color.r * amount);
    node.g = Math.round(node.g * (1 - amount) + color.g * amount);
    node.b = Math.round(node.b * (1 - amount) + color.b * amount);
}

function productRegionHsl(role: string): string {
    switch (role) {
        case 'core': return '172 72% 56%';
        case 'backbone': return '206 78% 62%';
        case 'bridge': return '45 92% 58%';
        case 'boundary': return '265 72% 64%';
        case 'outlier': return '340 82% 62%';
        default: return '220 12% 58%';
    }
}

function productLaneHsl(lane: string): string {
    switch (lane) {
        case 'document': return entityColorStore.getRawGraphNodeHsl('document');
        case 'relation': return entityColorStore.getRawGraphNodeHsl('graphFact');
        case 'temporal': return entityColorStore.getRawGraphNodeHsl('temporalFact');
        case 'causal': return entityColorStore.getRawGraphNodeHsl('causalFact');
        case 'evidence': return entityColorStore.getRawGraphNodeHsl('memoryState');
        case 'entity': return entityColorStore.getRawHsl('UNKNOWN');
        default: return '180 62% 56%';
    }
}

function relaxNodes(nodes: GalaxyNode[], links: GalaxyEdge[], settings: GalaxyRenderSettings): void {
    const count = nodes.length;
    if (count < 3) {
        return;
    }
    const vx = new Float32Array(count);
    const vy = new Float32Array(count);
    const vz = new Float32Array(count);
    const targetLength = 0.34 + settings.edgeLength * 0.84;
    const repel = 0.012 * settings.nodeDistance;
    const spring = 0.026;
    const ticks = count > 220 ? 24 : count > 160 ? 32 : count > 96 ? 44 : 64;

    for (let tick = 0; tick < ticks; tick++) {
        for (const link of links) {
            const a = nodes[link.source];
            const b = nodes[link.target];
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const dz = b.z - a.z;
            const dist = Math.max(0.001, Math.sqrt(dx * dx + dy * dy + dz * dz));
            const force = (dist - targetLength) * spring;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            const fz = (dz / dist) * force;
            vx[link.source] += fx;
            vy[link.source] += fy;
            vz[link.source] += fz;
            vx[link.target] -= fx;
            vy[link.target] -= fy;
            vz[link.target] -= fz;
        }

        for (let left = 0; left < count; left++) {
            for (let right = left + 1; right < count; right++) {
                const a = nodes[left];
                const b = nodes[right];
                const dx = b.x - a.x;
                const dy = b.y - a.y;
                const dz = b.z - a.z;
                const dist2 = Math.max(0.018, dx * dx + dy * dy + dz * dz);
                const force = repel / dist2;
                vx[left] -= dx * force;
                vy[left] -= dy * force;
                vz[left] -= dz * force;
                vx[right] += dx * force;
                vy[right] += dy * force;
                vz[right] += dz * force;
            }
        }

        for (let index = 0; index < count; index++) {
            const node = nodes[index];
            node.x = clamp(node.x + vx[index], -2.25, 2.25);
            node.y = clamp(node.y + vy[index], -1.85, 1.85);
            node.z = clamp(node.z + vz[index], -2.25, 2.25);
            node.baseX = node.x;
            node.baseY = node.y;
            node.baseZ = node.z;
            vx[index] *= 0.72;
            vy[index] *= 0.72;
            vz[index] *= 0.72;
        }
    }
}

function applyGalaxyMetadata(nodes: GalaxyNode[]): void {
    for (const node of nodes) {
        const offset = node.entity.metadata?.galaxyOffset;
        if (offset) {
            node.x += offset.x;
            node.y += offset.y;
            node.z += offset.z;
            node.baseX += offset.x;
            node.baseY += offset.y;
            node.baseZ += offset.z;
        }
        if (node.entity.metadata?.galaxyRole === 'context') {
            node.radius *= 0.82;
        }
    }
}

interface GalaxyGroupPlan {
    id: string;
    label: string;
    kind: GalaxyGroup['kind'];
    indexes: number[];
}

function buildGroupPlan(nodes: GalaxyNode[]): GalaxyGroupPlan[] {
    const groups = new Map<string, GalaxyGroupPlan>();
    for (let index = 0; index < nodes.length; index++) {
        const info = groupInfoForNode(nodes[index].entity);
        let group = groups.get(info.id);
        if (!group) {
            group = { ...info, indexes: [] };
            groups.set(info.id, group);
        }
        group.indexes.push(index);
    }

    const ordered = [...groups.values()]
        .sort((left, right) => right.indexes.length - left.indexes.length || left.label.localeCompare(right.label));
    const keep = ordered.slice(0, 24);
    const overflow = ordered.slice(24);
    if (overflow.length) {
        keep.push({
            id: 'group:other-sources',
            label: 'Other Sources',
            kind: 'other',
            indexes: overflow.flatMap((group) => group.indexes),
        });
    }
    return keep.filter((group) => group.indexes.length > 0);
}

function groupInfoForNode(entity: GalaxyRenderableNode): Pick<GalaxyGroupPlan, 'id' | 'label' | 'kind'> {
    const metadata = entity.metadata || {};
    const sourceType = String(metadata.sourceType || '').toLowerCase();
    if (sourceType === 'query') {
        return { id: 'group:query', label: 'Query Trace', kind: 'query' };
    }

    const galaxyId = stringValue(metadata.galaxyId);
    if (galaxyId) {
        return {
            id: galaxyId,
            label: stringValue(metadata['galaxyLabel']) || sourceTitleFromLabel(entity.label) || titleCase(entity.kind),
            kind: sourceType === 'entity' ? 'entity-cluster' : 'semantic-cluster',
        };
    }

    const noteId = stringValue(metadata.noteId) || (sourceType === 'doc' ? stringValue(metadata.sourceId) : '');
    if (noteId) {
        const title = stringValue(metadata.sourceTitle) || sourceTitleFromLabel(entity.label) || `Note ${noteId.slice(0, 6)}`;
        return { id: `note:${noteId}`, label: title, kind: 'note' };
    }

    if (sourceType === 'entity') {
        return { id: 'group:registry-anchors', label: 'Registry Anchors', kind: 'entity-cluster' };
    }

    if (sourceType) {
        return { id: `source:${sourceType}`, label: titleCase(sourceType), kind: 'semantic-cluster' };
    }

    return { id: `kind:${entity.kind || 'unknown'}`, label: titleCase(entity.kind || 'Other'), kind: 'other' };
}

function applyMultiGalaxyLayout(nodes: GalaxyNode[], links: GalaxyEdge[], plans: GalaxyGroupPlan[]): GalaxyGroup[] {
    const groupByNode = new Map<number, GalaxyGroupPlan>();
    for (const group of plans) {
        for (const index of group.indexes) groupByNode.set(index, group);
    }

    const count = plans.length;
    const centerRadius = clamp(2.16 + Math.sqrt(count) * 0.22, 2.35, 3.35);
    const groups: GalaxyGroup[] = plans.map((group, index) => {
        const center = fibonacciSpherePoint(index, count, centerRadius, stableUnit(group.id));
        const radius = clamp(0.46 + Math.sqrt(group.indexes.length) * 0.035, 0.5, 0.86);
        const color = groupColor(group.id, index);
        return {
            id: group.id,
            label: group.label,
            kind: group.kind,
            center,
            radius,
            nodeIds: group.indexes.map((nodeIndex) => nodes[nodeIndex].entity.id),
            importance: group.indexes.length,
            ...color,
        };
    });
    const groupMeta = new Map(groups.map((group) => [group.id, group]));

    for (const [index, node] of nodes.entries()) {
        const plan = groupByNode.get(index);
        const group = plan ? groupMeta.get(plan.id) : undefined;
        if (!group) continue;
        node.groupId = group.id;
        const norm = Math.hypot(node.x, node.y, node.z);
        const fallback = stableVector(node.entity.id);
        const localScale = group.radius / Math.max(1.35, norm || 1.35);
        const lx = norm > 0.001 ? node.x * localScale : fallback.x * group.radius * 0.32;
        const ly = norm > 0.001 ? node.y * localScale : fallback.y * group.radius * 0.32;
        const lz = norm > 0.001 ? node.z * localScale : fallback.z * group.radius * 0.32;
        node.x = group.center.x + lx;
        node.y = group.center.y + ly;
        node.z = group.center.z + lz;
        node.baseX = node.x;
        node.baseY = node.y;
        node.baseZ = node.z;
        node.radius *= plan?.kind === 'query' ? 1.05 : 0.86;
    }

    for (const link of links) {
        const sourceGroup = nodes[link.source]?.groupId;
        const targetGroup = nodes[link.target]?.groupId;
        link.interGalaxy = Boolean(sourceGroup && targetGroup && sourceGroup !== targetGroup);
        if (link.interGalaxy) {
            link.alpha = Math.min(0.42, link.alpha * 1.28 + 0.035);
            link.curve *= 1.3;
        }
    }

    return groups;
}

const HYBRID_SHELL_RADIUS = 2.32;
const HOPF_PROJECTION_RADIUS = 0.88;
const HOPF_MAX_RADIUS = 2.05;
const TAU = Math.PI * 2;
const HOPF_RIBBON_SEGMENTS = 96;
const HOPF_DATA_FIBER_GUIDE_LIMIT = 48;
const HOPF_CROSS_FIBER_BRAID_LIMIT = 96;
const HOPF_CROSS_FIBER_BRAID_SEGMENTS = 48;
interface HopfBaseInfo extends Rgb {
    key: string;
    direction: { x: number; y: number; z: number };
    directionWeight: number;
    phases: number[];
    nodeIds: string[];
    fiberKinds: Set<string>;
    secondaryCellIds: Set<string>;
    backendReceiptCount: number;
    documentChartCount: number;
    importance: number;
}

interface HybridHierarchyInfo {
    lane: string;
    phase: number;
    specificity: number;
    ambiguity: number;
    level: number;
    strength: number;
}

function applyBusemannCommitmentOverlay(
    nodes: GalaxyNode[],
    settings: GalaxyRenderSettings,
): GalaxyBusemannHorosphereSpec[] | undefined {
    if (settings.hybridInteriorMode !== 'busemannCommitment' || settings.hybridInteriorVisible === false) {
        return undefined;
    }

    const prototypes = buildBusemannPrototypes(nodes);
    if (!prototypes.length) {
        return undefined;
    }

    const interiorScale = settings.hybridInteriorScale ?? 1;
    applyHybridBusemannLayout(nodes, prototypes, {
        shellRadius: HYBRID_SHELL_RADIUS,
        minInteriorRadius: HYBRID_SHELL_RADIUS * 0.08,
        maxInteriorRadius: HYBRID_SHELL_RADIUS * clamp(0.92 * interiorScale, 0.24, 0.98),
        preferBackendPoint: true,
    });

    const opacity = settings.hybridInteriorOpacity ?? 1;
    if (opacity < 1) {
        for (const node of nodes) {
            if ((node as GalaxyNode & { __hybridInterior?: unknown }).__hybridInterior) {
                node.galaxyOpacity *= opacity;
            }
        }
    }

    const horosphereOpacity = settings.hybridHorosphereOpacity ?? 0.6;
    return buildBusemannHorosphereSpecs(
        prototypes,
        HYBRID_SHELL_RADIUS,
        activeBusemannPrototypeIds(nodes),
    ).map((spec) => ({
        ...spec,
        opacity: spec.opacity * horosphereOpacity,
    }));
}

function buildBusemannPrototypes(nodes: GalaxyNode[]): GalaxyBusemannPrototype[] {
    const prototypes = new Map<string, GalaxyBusemannPrototype>();
    const add = (prototypeId: string | null | undefined, family: string | undefined) => {
        if (!prototypeId || prototypes.has(prototypeId)) return;
        const normalizedFamily = normalizePrototypeFamily(family);
        prototypes.set(prototypeId, {
            prototypeId,
            family: normalizedFamily,
            label: busemannPrototypeLabel(prototypeId),
            direction: busemannPrototypeDirection(normalizedFamily, prototypeId),
            colorKind: busemannPrototypeColorKind(normalizedFamily, prototypeId),
        });
    };

    for (const node of nodes) {
        const signature = readBusemannSignature(node);
        if (!signature) continue;
        add(signature.topPrototypeId, signature.family);
        add(signature.secondPrototypeId || undefined, signature.family);
        for (const score of signature.topKScores || []) add(score.prototypeId, score.family);
    }

    return [...prototypes.values()].sort((left, right) =>
        left.family.localeCompare(right.family) || left.prototypeId.localeCompare(right.prototypeId)
    );
}

function normalizePrototypeFamily(value: string | undefined): GalaxyPrototypeFamily {
    switch (value) {
        case 'EntityKind':
        case 'RelationFamily':
        case 'EvidenceAuthority':
        case 'GraphStage':
        case 'ConceptDomain':
            return value;
        default:
            return 'RelationFamily';
    }
}

function busemannPrototypeDirection(
    family: GalaxyPrototypeFamily,
    prototypeId: string,
): { x: number; y: number; z: number } {
    const semantic = normalizeVector(stableVector(`busemann:${family}:${prototypeId}`), { x: 1, y: 0, z: 0 });
    const lane = busemannFamilyDirection(family);
    return normalizeVector({
        x: semantic.x * 0.78 + lane.x * 0.22,
        y: semantic.y * 0.78 + lane.y * 0.22,
        z: semantic.z * 0.78 + lane.z * 0.22,
    }, semantic);
}

function busemannFamilyDirection(family: GalaxyPrototypeFamily): { x: number; y: number; z: number } {
    switch (family) {
        case 'EntityKind': return { x: -0.58, y: 0.54, z: 0.2 };
        case 'EvidenceAuthority': return { x: -0.7, y: -0.12, z: 0.7 };
        case 'GraphStage': return { x: 0.12, y: 0.74, z: 0.66 };
        case 'ConceptDomain': return { x: 0.0, y: -0.34, z: 0.94 };
        case 'RelationFamily':
        default: return { x: 0.5, y: -0.5, z: 0.0 };
    }
}

function busemannPrototypeLabel(prototypeId: string): string {
    const tail = prototypeId.split(':').filter(Boolean).pop() || prototypeId;
    return titleCase(tail);
}

function busemannPrototypeColorKind(family: GalaxyPrototypeFamily, prototypeId: string): string {
    const tail = prototypeId.split(':').filter(Boolean).pop() || prototypeId;
    if (family === 'RelationFamily') return tail;
    if (family === 'EvidenceAuthority') return 'evidence';
    if (family === 'GraphStage') return 'graphFact';
    if (family === 'ConceptDomain') return 'concept';
    return tail;
}

function applyHybridSpaceLayout(nodes: GalaxyNode[], links: GalaxyEdge[]): void {
    for (const node of nodes) {
        const hierarchy = hybridHierarchyInfo(node);
        const direction = hybridHierarchyDirection(node, hierarchy);
        const baseRadius = hybridRadius(node);
        const radius = hybridHierarchyRadius(node, baseRadius, hierarchy);
        const point = hybridPlacementPoint(direction, radius);
        node.x = point.x;
        node.y = point.y;
        node.z = point.z;
        node.baseX = node.x;
        node.baseY = node.y;
        node.baseZ = node.z;
        node.depth = radius;
        node.radius *= hybridNodeScale(node, radius);
        const receipt: GalaxyHybridShellReceipt = {
            mode: 'hybridShell',
            geometryVersion: 'hybrid_shell_anatomy_v1',
            lane: hierarchy.lane,
            phase: hierarchy.phase,
            specificity: hierarchy.specificity,
            ambiguity: hierarchy.ambiguity,
            level: hierarchy.level,
            strength: hierarchy.strength,
            baseRadius,
            shellRadius: radius,
            laneStrength: hybridLaneStrength(hierarchy),
            direction,
            point,
            sourceSignals: hybridHierarchySourceSignals(node),
        };
        node.hybridShell = receipt;
        node.hybridShellPoint = point;
        node.hybridRenderPoint = point;
        const metadata = node.entity.metadata ?? {};
        node.entity.metadata = {
            ...metadata,
            hybridShell: receipt,
            hybridShellPoint: point,
            hybridRenderPoint: point,
        };
    }

    for (const link of links) {
        const source = nodes[link.source];
        const target = nodes[link.target];
        const radialDelta = Math.abs((source?.depth || 0.68) - (target?.depth || 0.68));
        const lanePair = source && target ? hybridEdgeLanePair(source, target, link) : 'semantic';
        const hierarchyBoost = lanePair === 'document' || lanePair === 'temporal' || lanePair === 'causal' ? 1.12 : 1;
        const diagnosticFloor = lanePair === 'temporal' || lanePair === 'causal' ? 0.045 : lanePair === 'document' ? 0.026 : 0.018;
        const diagnosticCap = lanePair === 'temporal' || lanePair === 'causal' ? 0.18 : lanePair === 'document' ? 0.12 : 0.1;
        link.alpha = Math.min(diagnosticCap, link.alpha * (0.56 + radialDelta * 0.24) * hierarchyBoost + diagnosticFloor);
        link.curve *= (0.78 + radialDelta * 0.9) * (lanePair === 'temporal' ? 1.18 : lanePair === 'document' ? 0.84 : 1);
    }
}

function normalizeVector(
    value: { x: number; y: number; z: number },
    fallback: { x: number; y: number; z: number },
): { x: number; y: number; z: number } {
    const norm = Math.hypot(value.x, value.y, value.z);
    if (norm > 0.0001) return { x: value.x / norm, y: value.y / norm, z: value.z / norm };
    return fallback;
}

function normalizedDirection(node: GalaxyNode): { x: number; y: number; z: number } {
    const x = Number.isFinite(node.entity.atlasX) ? Number(node.entity.atlasX) : node.x;
    const y = Number.isFinite(node.entity.atlasY) ? Number(node.entity.atlasY) : node.y;
    const z = Number.isFinite(node.entity.atlasZ) ? Number(node.entity.atlasZ) : node.z;
    const norm = Math.hypot(x, y, z);
    if (norm > 0.0001) return { x: x / norm, y: y / norm, z: z / norm };
    return stableVector(node.entity.id);
}

function hybridRadius(node: GalaxyNode): number {
    const metadata = node.entity.metadata || {};
    const sourceType = String(metadata.sourceType || '').toLowerCase();
    const tokenCount = Number(metadata['tokenCount'] || 0);
    const mentions = Math.max(1, Number(node.entity.totalMentions || 1));

    if (sourceType === 'query') return 0.92;
    if (sourceType === 'leaf') return clamp(0.5 + Math.min(0.18, Math.log1p(Math.max(1, tokenCount)) * 0.018), 0.5, 0.68);
    if (sourceType === 'doc') return clamp(0.22 + Math.min(0.16, Math.log1p(Math.max(1, tokenCount)) * 0.012), 0.22, 0.38);
    if (sourceType === 'entity') return clamp(0.38 + Math.min(0.18, Math.log1p(mentions) * 0.052), 0.38, 0.56);
    if (node.entity.kind?.toLowerCase().includes('folder')) return 0.18;
    if (node.entity.kind?.toLowerCase().includes('narrative')) return 0.16;
    return 0.42;
}

function hybridHierarchyInfo(node: GalaxyNode): HybridHierarchyInfo {
    const metadata = node.entity.metadata || {};
    const product = recordValue(metadata['product']);
    const region = recordValue(product['region']);
    const lanes = recordValue(product['lanes']);
    const lorentz = recordValue(metadata['lorentz']);
    const lane = normalizeHierarchyLane(firstString(
        metadata['productLaneKind'],
        region['laneKind'],
        product['dominantLane'],
        lanes['dominantLane'],
        lorentz['dominantLane'],
        lorentz['primaryTreeKind'],
        metadata['graphRelationFamily'],
        metadata['graphKind'],
        metadata['sourceType'],
        node.entity.kind,
    ));
    const phase = unitPhase(firstNumber(lorentz['capPhase'], lanes['fiberPhase'], stableUnit(`${node.entity.id}:hybrid-phase`)));
    const specificity = clamp(firstNumber(lorentz['specificity'], hybridFallbackSpecificity(node)), 0, 1);
    const ambiguity = clamp(firstNumber(lorentz['ambiguity'], hybridFallbackAmbiguity(node)), 0, 1);
    const level = clamp(Math.round(firstNumber(lorentz['level'], hybridFallbackLevel(node))), 0, 5);
    const confidence = clamp(firstNumber(metadata['productRegionConfidence'], region['confidence'], 0.62), 0, 1);
    return {
        lane,
        phase,
        specificity,
        ambiguity,
        level,
        strength: clamp(0.16 + specificity * 0.16 + confidence * 0.08 - ambiguity * 0.1, 0.1, 0.34),
    };
}

function hybridHierarchyDirection(node: GalaxyNode, hierarchy: HybridHierarchyInfo): { x: number; y: number; z: number } {
    const base = normalizedDirection(node);
    const lane = hybridLaneDirection(hierarchy);
    const laneStrength = hybridLaneStrength(hierarchy);
    const mixed = {
        x: base.x * (1 - laneStrength) + lane.x * laneStrength,
        y: base.y * (1 - laneStrength) + lane.y * laneStrength,
        z: base.z * (1 - laneStrength) + lane.z * laneStrength,
    };
    return normalizeVector(mixed, base);
}

function hybridLaneStrength(hierarchy: HybridHierarchyInfo): number {
    if (hierarchy.lane === 'temporal') return hierarchy.strength * 1.08;
    if (hierarchy.lane === 'causal') return hierarchy.strength * 1.02;
    if (hierarchy.lane === 'document') return hierarchy.strength * 0.94;
    return hierarchy.strength * 0.72;
}

function hybridPlacementPoint(
    direction: { x: number; y: number; z: number },
    radius: number,
): GalaxyHybridPlacementPoint {
    return {
        x: direction.x * radius * HYBRID_SHELL_RADIUS,
        y: direction.y * radius * HYBRID_SHELL_RADIUS,
        z: direction.z * radius * HYBRID_SHELL_RADIUS,
        radius,
    };
}

function hybridLaneDirection(hierarchy: HybridHierarchyInfo): { x: number; y: number; z: number } {
    const angle = hierarchy.phase * TAU;
    const level = hierarchy.level;
    switch (hierarchy.lane) {
        case 'document': {
            const branch = clamp(0.12 + level * 0.08, 0.12, 0.46);
            return normalizeVector({ x: Math.cos(angle) * branch, y: -0.12 + level * 0.08, z: 1 }, { x: 0, y: 0, z: 1 });
        }
        case 'temporal':
            return normalizeVector({ x: Math.cos(angle), y: 0.16, z: Math.sin(angle) }, { x: 1, y: 0, z: 0 });
        case 'causal': {
            const cone = clamp(0.18 + level * 0.07, 0.18, 0.48);
            return normalizeVector({ x: 0.9, y: Math.cos(angle) * cone, z: Math.sin(angle) * cone }, { x: 1, y: 0, z: 0 });
        }
        case 'event':
            return normalizeVector({ x: -0.42, y: 0.34 + Math.sin(angle) * 0.18, z: Math.cos(angle) * 0.72 }, { x: -0.4, y: 0.3, z: 0.8 });
        case 'relationship':
            return normalizeVector({ x: 0.48, y: -0.52, z: Math.sin(angle) * 0.42 }, { x: 0.5, y: -0.5, z: 0 });
        case 'entity':
            return normalizeVector({ x: -0.58, y: 0.54, z: Math.sin(angle) * 0.26 }, { x: -0.6, y: 0.5, z: 0.2 });
        case 'evidence':
            return normalizeVector({ x: -0.7, y: -0.14, z: 0.68 + Math.sin(angle) * 0.18 }, { x: -0.7, y: -0.1, z: 0.7 });
        default:
            return normalizeVector({ x: 0.18, y: 0.48, z: 0.86 }, { x: 0, y: 0.4, z: 0.9 });
    }
}

function hybridHierarchyRadius(node: GalaxyNode, baseRadius: number, hierarchy: HybridHierarchyInfo): number {
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    let target = 0.48 + hierarchy.specificity * 0.5 - hierarchy.ambiguity * 0.12;
    if (sourceType === 'query') target = 0.92;
    else if (hierarchy.lane === 'document') {
        if (/doc|note|folder/.test(sourceType)) target = 0.22 + hierarchy.specificity * 0.18;
        else if (/leaf|chunk|anchor|mention/.test(sourceType)) target = 0.46 + hierarchy.specificity * 0.22;
        else target = 0.34 + hierarchy.level * 0.045;
    } else if (hierarchy.lane === 'temporal') {
        target = 0.44 + hierarchy.specificity * 0.2;
    } else if (hierarchy.lane === 'causal') {
        target = 0.42 + hierarchy.specificity * 0.24 + hierarchy.level * 0.012;
    } else if (hierarchy.lane === 'entity') {
        target = 0.38 + hierarchy.specificity * 0.2;
    } else if (hierarchy.lane === 'relationship' || hierarchy.lane === 'event') {
        target = 0.36 + hierarchy.specificity * 0.22;
    }
    return clamp(baseRadius * 0.58 + clamp(target, 0.16, 0.92) * 0.42, 0.16, 0.92);
}

function hybridEdgeLanePair(source: GalaxyNode, target: GalaxyNode, link: GalaxyEdge): string {
    const type = `${link.type} ${source.entity.kind} ${target.entity.kind} ${source.entity.metadata?.graphRelationFamily || ''} ${target.entity.metadata?.graphRelationFamily || ''}`.toLowerCase();
    if (/temporal|timeline|before|after/.test(type)) return 'temporal';
    if (/caus|because|effect/.test(type)) return 'causal';
    if (/doc|chunk|leaf|anchor|mention/.test(type)) return 'document';
    return 'semantic';
}

function hybridFallbackSpecificity(node: GalaxyNode): number {
    const kind = String(node.entity.kind || '').toLowerCase();
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    if (/leaf|chunk|anchor|mention/.test(sourceType)) return 0.9;
    if (/doc|note|folder/.test(sourceType)) return 0.32;
    if (/character|location|entity|concept|item|npc|creature/.test(kind)) return 0.78;
    if (/event|temporal|causal/.test(kind)) return 0.72;
    if (/fact|relationship|memory/.test(kind)) return 0.62;
    return 0.58;
}

function hybridFallbackAmbiguity(node: GalaxyNode): number {
    const metadata = node.entity.metadata || {};
    const outlier = Number(metadata['embeddingOutlierScore'] || 0);
    const sourceType = String(metadata.sourceType || '').toLowerCase();
    if (/doc|folder/.test(sourceType)) return 0.34;
    return clamp(outlier * 0.38, 0, 0.36);
}

function hybridFallbackLevel(node: GalaxyNode): number {
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    if (/doc|folder/.test(sourceType)) return 0;
    if (/leaf|chunk/.test(sourceType)) return 3;
    if (/anchor|mention/.test(sourceType)) return 4;
    return 2;
}

function normalizeHierarchyLane(value: string): string {
    const lane = value.trim().toLowerCase().replace(/[_\s-]+/g, '');
    if (/temporal|timeline|time/.test(lane)) return 'temporal';
    if (/causal|cause|effect/.test(lane)) return 'causal';
    if (/document|doc|chunk|leaf|anchor|mention/.test(lane)) return 'document';
    if (/event|scene|beat|act|chapter/.test(lane)) return 'event';
    if (/relation|relationship|cooccurrence|communication|authority|approval|family|intimacy|transfer/.test(lane)) return 'relationship';
    if (/evidence|memory|state|source|provenance/.test(lane)) return 'evidence';
    if (/entity|character|location|concept|item|creature|npc|network/.test(lane)) return 'entity';
    return 'semantic';
}

function hybridHierarchySourceSignals(node: GalaxyNode): string[] {
    const metadata = node.entity.metadata || {};
    const product = recordValue(metadata['product']);
    const region = recordValue(product['region']);
    const lanes = recordValue(product['lanes']);
    const lorentz = recordValue(metadata['lorentz']);
    const signals: string[] = [];
    appendSourceSignal(signals, 'productLaneKind', metadata['productLaneKind']);
    appendSourceSignal(signals, 'product.region.laneKind', region['laneKind']);
    appendSourceSignal(signals, 'product.dominantLane', product['dominantLane']);
    appendSourceSignal(signals, 'product.lanes.dominantLane', lanes['dominantLane']);
    appendSourceSignal(signals, 'lorentz.dominantLane', lorentz['dominantLane']);
    appendSourceSignal(signals, 'lorentz.primaryTreeKind', lorentz['primaryTreeKind']);
    appendSourceSignal(signals, 'graphRelationFamily', metadata['graphRelationFamily']);
    appendSourceSignal(signals, 'graphKind', metadata['graphKind']);
    appendSourceSignal(signals, 'sourceType', metadata['sourceType']);
    appendSourceSignal(signals, 'kind', node.entity.kind);
    return signals;
}

function appendSourceSignal(signals: string[], label: string, value: unknown): void {
    if (typeof value !== 'string' || !value.trim()) return;
    signals.push(`${label}=${value.trim()}`);
}

function recordValue(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function firstString(...values: unknown[]): string {
    for (const value of values) {
        if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return '';
}

function firstNumber(...values: unknown[]): number {
    for (const value of values) {
        const number = Number(value);
        if (Number.isFinite(number)) return number;
    }
    return 0;
}

function unitPhase(value: number): number {
    return value >= 0 && value <= 1 ? value : ((value / TAU) % 1 + 1) % 1;
}

function hybridNodeScale(node: GalaxyNode, radius: number): number {
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    if (sourceType === 'query') return 1.18;
    if (sourceType === 'entity') return 0.98;
    return 0.78 + radius * 0.18;
}

function applyHopfProjectionLayout(nodes: GalaxyNode[], links: GalaxyEdge[]): GalaxyHopfRibbon[] {
    const baseInfos = new Map<string, HopfBaseInfo>();
    for (const node of nodes) {
        const baseKey = hopfBaseKey(node);
        if (!baseKey) continue;
        registerHopfBase(baseInfos, baseKey, node, isHopfAnchor(node));
    }
    normalizeHopfBaseDirections(baseInfos);
    for (const node of nodes) {
        const baseKey = hopfBaseKey(node);
        const baseInfo = baseKey ? baseInfos.get(baseKey) : undefined;
        const direction = baseInfo?.direction ?? normalizedDirection(node);
        const phase = hopfPhase(node, baseKey);
        const point = hopfStereographicProjection(direction, phase, hopfPositionScale(node));
        node.x = point.x;
        node.y = point.y;
        node.z = point.z;
        node.baseX = node.x;
        node.baseY = node.y;
        node.baseZ = node.z;
        node.depth = Math.min(1, Math.hypot(node.x, node.y, node.z) / HOPF_MAX_RADIUS);
        node.radius *= hopfNodeScale(node);
        if (baseInfo && (isHopfAnchor(node) || isHopfFiber(node))) {
            const normalizedPhase = normalizePhaseRadians(phase);
            baseInfo.phases.push(normalizedPhase);
            baseInfo.nodeIds.push(node.entity.id);
            baseInfo.fiberKinds.add(hopfFiberKind(node));
            baseInfo.importance += Math.max(1, Number(node.entity.totalMentions || 1));
        }
    }

    const crossFiberBraids: GalaxyHopfRibbon[] = [];
    for (const link of links) {
        const type = link.type.toLowerCase();
        if (type.includes('anchor-fiber')) {
            link.alpha = Math.min(0.5, link.alpha * 1.55 + 0.07);
            link.curve *= 1.48;
            continue;
        }
        const sourceNode = nodes[link.source];
        const targetNode = nodes[link.target];
        const sourceBase = sourceNode ? hopfBaseKey(sourceNode) : null;
        const targetBase = targetNode ? hopfBaseKey(targetNode) : null;
        if (sourceBase && targetBase && sourceBase !== targetBase) {
            link.alpha = Math.min(0.07, link.alpha * 0.32 + 0.012);
            link.curve *= 2.35;
            if (crossFiberBraids.length < HOPF_CROSS_FIBER_BRAID_LIMIT) {
                crossFiberBraids.push(buildHopfCrossFiberBraid(sourceNode, targetNode, link));
            }
            continue;
        }
        if (type.includes('fiber-edge')) {
            link.alpha = Math.min(0.24, link.alpha * 0.72 + 0.026);
            link.curve *= 1.32;
        }
    }

    return [
        ...buildHopfReceiptRibbons(hopfReceiptBases(baseInfos)),
        ...buildHopfRibbons(baseInfos),
        ...crossFiberBraids,
    ];
}

function registerHopfBase(baseInfos: Map<string, HopfBaseInfo>, baseKey: string, node: GalaxyNode, anchor: boolean): void {
    const existing = baseInfos.get(baseKey);
    const metadata = hopfMetadata(node);
    const direction = hopfDirectionFromMetadata(metadata?.['direction']) || normalizedDirection(node);
    const weight = anchor ? 1.35 : 1;
    if (existing) {
        existing.direction.x += direction.x * weight;
        existing.direction.y += direction.y * weight;
        existing.direction.z += direction.z * weight;
        existing.directionWeight += weight;
        recordHopfReceiptMetadata(existing, node, metadata);
        if (anchor) {
            existing.r = node.r;
            existing.g = node.g;
            existing.b = node.b;
        }
        return;
    }
    baseInfos.set(baseKey, {
        key: baseKey,
        direction: {
            x: direction.x * weight,
            y: direction.y * weight,
            z: direction.z * weight,
        },
        directionWeight: weight,
        phases: [],
        nodeIds: [],
        fiberKinds: new Set<string>(),
        secondaryCellIds: new Set<string>(),
        backendReceiptCount: 0,
        documentChartCount: 0,
        importance: 0,
        r: node.r,
        g: node.g,
        b: node.b,
    });
    recordHopfReceiptMetadata(baseInfos.get(baseKey)!, node, metadata);
}

function normalizeHopfBaseDirections(baseInfos: Map<string, HopfBaseInfo>): void {
    for (const info of baseInfos.values()) {
        const averaged = {
            x: info.direction.x / Math.max(0.0001, info.directionWeight),
            y: info.direction.y / Math.max(0.0001, info.directionWeight),
            z: info.direction.z / Math.max(0.0001, info.directionWeight),
        };
        info.direction = normalizeVector(averaged, stableVector(`${info.key}:hopf-base`));
    }
}

function buildHopfRibbons(baseInfos: Map<string, HopfBaseInfo>): GalaxyHopfRibbon[] {
    return selectHopfDataFibers(baseInfos)
        .map((info): GalaxyHopfRibbon => ({
            id: `hopf:ribbon:${info.key}`,
            nodeIds: [...new Set(info.nodeIds)],
            positions3d: hopfDataFiberSegments(info),
            importance: info.importance,
            guideKind: 'dataFiber' as const,
            guideWeight: 1,
            r: info.r,
            g: info.g,
            b: info.b,
        }));
}

function selectHopfDataFibers(baseInfos: Map<string, HopfBaseInfo>): HopfBaseInfo[] {
    const candidates = [...baseInfos.values()]
        .filter((info) => info.nodeIds.length > 0)
        .sort((left, right) => right.importance - left.importance || left.key.localeCompare(right.key));
    const selected = new Map<string, HopfBaseInfo>();
    const add = (info: HopfBaseInfo | undefined) => {
        if (!info || selected.size >= HOPF_DATA_FIBER_GUIDE_LIMIT) return;
        selected.set(info.key, info);
    };

    const bySemanticKind = new Map<string, HopfBaseInfo>();
    for (const info of candidates) {
        const kind = primaryHopfFiberKind(info);
        const current = bySemanticKind.get(kind);
        if (!current || info.importance > current.importance) bySemanticKind.set(kind, info);
    }
    for (const info of [...bySemanticKind.values()].sort((left, right) => right.importance - left.importance)) add(info);
    for (const info of candidates) add(info);
    return [...selected.values()].sort((left, right) => right.importance - left.importance || left.key.localeCompare(right.key));
}

function primaryHopfFiberKind(info: HopfBaseInfo): string {
    const kinds = [...info.fiberKinds].sort();
    return kinds.find((kind) => kind !== 'identity' && kind !== 'entity') || kinds[0] || 'identity';
}

function buildHopfCrossFiberBraid(source: GalaxyNode, target: GalaxyNode, link: GalaxyEdge): GalaxyHopfRibbon {
    const positions3d = hopfBraidSegments(source, target, link.flowOffset);
    return {
        id: `hopf:braid:${link.id}`,
        nodeIds: [source.entity.id, target.entity.id],
        positions3d,
        importance: Math.max(0.18, link.confidence),
        guideKind: 'crossFiberBraid',
        guideWeight: 0.42 + Math.max(0, link.confidence) * 0.36,
        r: Math.round((source.r + target.r) * 0.5),
        g: Math.round((source.g + target.g) * 0.5),
        b: Math.round((source.b + target.b) * 0.5),
    };
}

function hopfBraidSegments(source: GalaxyNode, target: GalaxyNode, seed: number): Float32Array {
    const segments = HOPF_CROSS_FIBER_BRAID_SEGMENTS;
    const positions = new Float32Array(segments * 2 * 3);
    for (let index = 0; index < segments; index++) {
        const a = index / segments;
        const b = (index + 1) / segments;
        const left = hopfBraidPoint(source, target, a, seed);
        const right = hopfBraidPoint(source, target, b, seed);
        const offset = index * 6;
        positions[offset] = left.x;
        positions[offset + 1] = left.y;
        positions[offset + 2] = left.z;
        positions[offset + 3] = right.x;
        positions[offset + 4] = right.y;
        positions[offset + 5] = right.z;
    }
    return positions;
}

function hopfBraidPoint(
    source: GalaxyNode,
    target: GalaxyNode,
    t: number,
    seed: number,
): { x: number; y: number; z: number } {
    const sourceRadius = Math.max(0.0001, Math.hypot(source.x, source.y, source.z));
    const targetRadius = Math.max(0.0001, Math.hypot(target.x, target.y, target.z));
    const sourceUnit = { x: source.x / sourceRadius, y: source.y / sourceRadius, z: source.z / sourceRadius };
    const targetUnit = { x: target.x / targetRadius, y: target.y / targetRadius, z: target.z / targetRadius };
    const normal = hopfBraidNormal(sourceUnit, targetUnit, seed);
    const sweep = Math.sin(Math.PI * t);
    const sign = seed < 0.5 ? -1 : 1;
    const bend = (0.26 + seed * 0.16) * sweep * sign;
    const spin = Math.sin(TAU * t + seed * TAU) * 0.055 * sweep;
    const direction = normalizeVector({
        x: sourceUnit.x * (1 - t) + targetUnit.x * t + normal.x * bend + (targetUnit.y * normal.z - targetUnit.z * normal.y) * spin,
        y: sourceUnit.y * (1 - t) + targetUnit.y * t + normal.y * bend + (targetUnit.z * normal.x - targetUnit.x * normal.z) * spin,
        z: sourceUnit.z * (1 - t) + targetUnit.z * t + normal.z * bend + (targetUnit.x * normal.y - targetUnit.y * normal.x) * spin,
    }, sourceUnit);
    const radius = sourceRadius * (1 - t) + targetRadius * t + 0.2 * sweep;
    return {
        x: direction.x * radius,
        y: direction.y * radius,
        z: direction.z * radius,
    };
}

function recordHopfReceiptMetadata(info: HopfBaseInfo, node: GalaxyNode, metadata: Record<string, unknown> | null): void {
    if (!metadata || metadata['resonanceSource'] !== 'snapshot-hopf-resonance-space') return;
    info.backendReceiptCount += 1;
    const secondaryCellIds = metadata['secondaryCellIds'];
    if (Array.isArray(secondaryCellIds)) {
        for (const cellId of secondaryCellIds) {
            if (typeof cellId === 'string' && cellId) info.secondaryCellIds.add(cellId);
        }
    }
    const fiberKind = String(metadata['fiberKind'] || '').toLowerCase();
    const role = String(metadata['role'] || '').toLowerCase();
    if (fiberKind === 'document_chart' || role === 'document-chart') {
        info.documentChartCount += Math.max(1, Number(node.entity.totalMentions || 1));
    }
}

function hopfReceiptBases(baseInfos: Map<string, HopfBaseInfo>): HopfReceiptBase[] {
    return [...baseInfos.values()].map((info): HopfReceiptBase => ({
        key: info.key,
        direction: info.direction,
        phases: info.phases,
        nodeIds: info.nodeIds,
        secondaryCellIds: [...info.secondaryCellIds],
        fiberKinds: [...info.fiberKinds],
        importance: info.importance,
        backendReceiptCount: info.backendReceiptCount,
        documentChartCount: info.documentChartCount,
        color: { r: info.r, g: info.g, b: info.b },
    }));
}

function hopfBraidNormal(
    sourceUnit: { x: number; y: number; z: number },
    targetUnit: { x: number; y: number; z: number },
    seed: number,
): { x: number; y: number; z: number } {
    const cross = {
        x: sourceUnit.y * targetUnit.z - sourceUnit.z * targetUnit.y,
        y: sourceUnit.z * targetUnit.x - sourceUnit.x * targetUnit.z,
        z: sourceUnit.x * targetUnit.y - sourceUnit.y * targetUnit.x,
    };
    const fallback = normalizeVector({
        x: sourceUnit.y * (seed < 0.5 ? -1 : 1) - sourceUnit.z * 0.38,
        y: sourceUnit.z + 0.22,
        z: -sourceUnit.x + sourceUnit.y * 0.38,
    }, stableVector(`hopf-braid:${seed.toFixed(6)}`));
    return normalizeVector(cross, fallback);
}

function hopfRibbonSegments(direction: { x: number; y: number; z: number }, phases: number[]): Float32Array {
    const phaseSet = new Set<number>();
    for (let index = 0; index < HOPF_RIBBON_SEGMENTS; index++) {
        phaseSet.add(roundPhase((index / HOPF_RIBBON_SEGMENTS) * TAU));
    }
    for (const phase of phases) phaseSet.add(roundPhase(phase));
    const samples = [...phaseSet].sort((left, right) => left - right);
    const positions = new Float32Array(samples.length * 2 * 3);
    for (let index = 0; index < samples.length; index++) {
        const current = hopfStereographicProjection(direction, samples[index], 1);
        const next = hopfStereographicProjection(direction, samples[(index + 1) % samples.length], 1);
        const offset = index * 6;
        positions[offset] = current.x;
        positions[offset + 1] = current.y;
        positions[offset + 2] = current.z;
        positions[offset + 3] = next.x;
        positions[offset + 4] = next.y;
        positions[offset + 5] = next.z;
    }
    return positions;
}

function hopfDataFiberSegments(info: HopfBaseInfo): Float32Array {
    return hopfRibbonSegments(info.direction, info.phases);
}

function hopfStereographicProjection(direction: { x: number; y: number; z: number }, phase: number, scale: number): { x: number; y: number; z: number } {
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
    const compactNorm = hopfCompactRadius(norm);
    const bound = norm > 0.0001 ? compactNorm / norm : 1;
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

function hopfPhase(node: GalaxyNode, baseKey: string | null): number {
    const metadataPhase = Number(hopfMetadata(node)?.['phase']);
    if (Number.isFinite(metadataPhase)) return metadataPhase >= 0 && metadataPhase <= 1 ? metadataPhase * TAU : metadataPhase;
    if (isHopfAnchor(node)) return stableUnit(`${baseKey || node.entity.id}:anchor-phase`) * 0.08;
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    if (sourceType === 'query') return stableUnit(`${node.entity.id}:query-phase`) * TAU;
    return fiberKindPhase(hopfFiberKind(node)) + (stableUnit(`${node.entity.id}:fiber-phase`) - 0.5) * 0.1;
}

function fiberKindPhase(kind: string): number {
    switch (kind) {
        case 'relationship':
        case 'emotional':
            return TAU * 0.18;
        case 'location':
            return TAU * 0.3;
        case 'event':
        case 'document_structure':
            return TAU * 0.41;
        case 'temporal':
            return TAU * 0.53;
        case 'causal':
        case 'contradiction':
            return TAU * 0.64;
        case 'evidence':
        case 'provenance':
            return TAU * 0.75;
        case 'political':
            return TAU * 0.84;
        case 'mechanical':
        case 'power_system':
            return TAU * 0.92;
        default:
            return TAU * 0.08;
    }
}

function hopfPositionScale(node: GalaxyNode): number {
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    if (sourceType === 'query') return 1.08;
    if (isHopfAnchor(node) || isHopfFiber(node)) return 1;
    if (sourceType === 'entity') return 0.68;
    return 0.88;
}

function normalizePhaseRadians(value: number): number {
    return ((value % TAU) + TAU) % TAU;
}

function roundPhase(value: number): number {
    return Math.round(normalizePhaseRadians(value) * 1000000) / 1000000;
}

function fibonacciUnitDirection(index: number, total: number): { x: number; y: number; z: number } {
    const y = 1 - ((index + 0.5) / total) * 2;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = index * 2.399963229728653;
    return {
        x: Math.cos(angle) * radial,
        y,
        z: Math.sin(angle) * radial,
    };
}

function hopfNodeScale(node: GalaxyNode): number {
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    if (sourceType === 'query') return 1.14;
    if (isHopfAnchor(node)) return 0.98;
    if (isHopfFiber(node)) return 0.74;
    if (sourceType === 'entity') return 0.82;
    return 0.78;
}

function hopfBaseKey(node: GalaxyNode): string | null {
    const metadata = hopfMetadata(node);
    const baseId = String(metadata?.['baseId'] || '');
    if (baseId) return baseId;
    const id = node.entity.id;
    if (id.startsWith('hopf:anchor:')) return id.slice('hopf:anchor:'.length);
    if (!id.startsWith('hopf:fiber:')) return null;
    const rest = id.slice('hopf:fiber:'.length);
    const separator = rest.lastIndexOf(':');
    return separator > 0 ? rest.slice(0, separator) : rest;
}

function hopfFiberKind(node: GalaxyNode): string {
    const metadataKind = String(hopfMetadata(node)?.['fiberKind'] || '').toLowerCase();
    if (metadataKind) return metadataKind;
    const kind = String(node.entity.kind || '').toLowerCase();
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    const id = node.entity.id;
    const kindMatch = kind.match(/hopf_fiber:([a-z0-9_-]+)/);
    if (kindMatch?.[1]) return kindMatch[1];
    if (id.startsWith('hopf:fiber:')) {
        const separator = id.lastIndexOf(':');
        if (separator > 'hopf:fiber:'.length) return id.slice(separator + 1).toLowerCase();
    }
    return sourceType || kind || 'identity';
}

function isHopfAnchor(node: GalaxyNode): boolean {
    if (hopfMetadata(node)?.['role'] === 'anchor') return true;
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    return sourceType === 'hopf_anchor' || node.entity.id.startsWith('hopf:anchor:') || String(node.entity.kind || '').toLowerCase() === 'hopf_anchor';
}

function isHopfFiber(node: GalaxyNode): boolean {
    if (hopfMetadata(node)?.['role'] === 'fiber') return true;
    const sourceType = String(node.entity.metadata?.sourceType || '').toLowerCase();
    return sourceType === 'hopf_fiber' || node.entity.id.startsWith('hopf:fiber:') || String(node.entity.kind || '').toLowerCase().startsWith('hopf_fiber:');
}

function hopfMetadata(node: GalaxyNode): Record<string, unknown> | null {
    const value = node.entity.metadata?.['hopf'];
    return value && typeof value === 'object' ? value as Record<string, unknown> : null;
}

function stringValue(value: unknown): string {
    return typeof value === 'string' && value.trim() ? value.trim() : '';
}

function sourceTitleFromLabel(label: string): string {
    const [first] = label.split(/[>/:]/).map((part) => part.trim()).filter(Boolean);
    return first || label;
}

function titleCase(value: string): string {
    return value
        .replace(/[-_]+/g, ' ')
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function fibonacciSpherePoint(index: number, total: number, radius: number, phase: number): { x: number; y: number; z: number } {
    if (total <= 1) return { x: 0, y: 0, z: 0 };
    const y = 1 - (index / Math.max(1, total - 1)) * 2;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = (index + phase * 0.37) * 2.399963229728653;
    return {
        x: Math.cos(angle) * radial * radius,
        y: y * radius * 0.58,
        z: Math.sin(angle) * radial * radius,
    };
}

function stableVector(id: string): { x: number; y: number; z: number } {
    const a = stableUnit(`${id}:a`) * Math.PI * 2;
    const y = stableUnit(`${id}:y`) * 2 - 1;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    return { x: Math.cos(a) * radial, y, z: Math.sin(a) * radial };
}

function groupColor(id: string, index: number): Rgb {
    const palette = [184, 198, 262, 172, 288, 42, 216, 326];
    const hue = palette[index % palette.length] + (stableUnit(id) - 0.5) * 18;
    return hslToRgb(`${hue} 76% 58%`);
}

function orderEntitiesForStableRender(entities: GalaxyRenderableNode[]): GalaxyRenderableNode[] {
    // Scene assembly must not downsample graph atoms; explicit lenses must filter upstream with receipts.
    return [...entities]
        .sort((left, right) => entityPriority(right) - entityPriority(left) || left.label.localeCompare(right.label));
}

function assertNoImplicitNodeDrop(inputCount: number, outputCount: number): void {
    if (inputCount === outputCount) return;
    throw new Error(`[GraphGalaxy] Scene assembly dropped ${inputCount - outputCount} renderable nodes. Use an explicit atlas lens upstream instead.`);
}

function entityPriority(entity: GalaxyRenderableNode): number {
    const mentions = Math.max(1, Number(entity.totalMentions || 1));
    return semanticNodePriority(entity) + (hasAtlasSeed(entity) ? 100000 : 0) + mentions;
}

const ENTITY_RENDER_KINDS = new Set([
    'character',
    'location',
    'npc',
    'item',
    'faction',
    'network',
    'organization',
    'event',
    'concept',
    'entity',
]);

function semanticNodePriority(entity: GalaxyRenderableNode): number {
    const kind = normalizeRenderKind(String(entity.metadata?.['graphKind'] || entity.kind || ''));
    if (kind === 'chunk' || kind === 'leaf') return 0;
    if (kind === 'mention' || kind === 'anchor') return 30000;
    if (ENTITY_RENDER_KINDS.has(kind) || entity.metadata?.sourceEntityId) return 200000;
    return 80000;
}

function normalizeRenderKind(kind: string): string {
    return kind.trim().toLowerCase().replace(/[_\s]+/g, '-');
}

export function resolveGalaxyNodeColorHsl(entity: GalaxyRenderableNode): string {
    const metadata = entity.metadata || {};
    const structuralColorKind = firstGraphNodeColorKind(
        stringValue(metadata['styleKey']),
        stringValue(metadata['atlasKind']),
        stringValue(metadata['sourceType']),
        stringValue(metadata['graphKind']),
        entity.kind,
    );
    if (structuralColorKind === 'chunk') return entityColorStore.getRawGraphNodeHsl('chunk');

    const graphColorKind = firstGraphNodeColorKind(
        stringValue(metadata['graphColorKind']),
        stringValue(metadata['graphRelationFamily']),
        stringValue(metadata['graphKind']),
    );
    if (graphColorKind) return entityColorStore.getRawGraphNodeHsl(graphColorKind);

    const entityKind = firstEntityColorKind(
        stringValue(metadata['entityKind']),
        stringValue(metadata['graphColorKind']),
        stringValue(metadata['graphKind']),
        entity.kind,
    );
    if (entityKind) return entityColorStore.getRawHsl(entityKind);

    return entity.colorHsl || entityColorStore.getRawHsl(entity.kind);
}

function firstGraphNodeColorKind(...values: Array<string | null | undefined>) {
    for (const value of values) {
        const kind = normalizeGraphNodeColorKind(value);
        if (kind) return kind;
    }
    return null;
}

function firstEntityColorKind(...values: Array<string | null | undefined>) {
    for (const value of values) {
        const kind = normalizeEntityKind(value);
        if (kind) return kind;
    }
    return null;
}

export function hslToRgb(rawHsl: string): Rgb {
    const values = rawHsl.match(/-?\d+(?:\.\d+)?/g)?.map((part) => Number(part)) ?? [];
    const [h = 190, s = 70, l = 55] = values;
    const hue = ((h % 360) + 360) % 360;
    const saturation = clamp(s / 100, 0, 1);
    const lightness = clamp(l / 100, 0, 1);
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const x = chroma * (1 - Math.abs(((hue / 60) % 2) - 1));
    const match = lightness - chroma / 2;
    const [red, green, blue] =
        hue < 60 ? [chroma, x, 0] :
            hue < 120 ? [x, chroma, 0] :
                hue < 180 ? [0, chroma, x] :
                    hue < 240 ? [0, x, chroma] :
                        hue < 300 ? [x, 0, chroma] : [chroma, 0, x];
    return {
        r: Math.round((red + match) * 255),
        g: Math.round((green + match) * 255),
        b: Math.round((blue + match) * 255),
    };
}
