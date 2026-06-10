import type { GalaxyEdge, GalaxyNode } from './graph-galaxy-engine';

export interface ProductOwnershipMembership {
    parentId: string;
    parentKind: string;
    relation: string;
    confidence: number;
    primary: boolean;
}

export interface ProductOwnershipRecord {
    nodeId: string;
    sourceType: string;
    role: string;
    lane: string;
    primaryParentId: string;
    ancestorIds: string[];
    memberships: ProductOwnershipMembership[];
    noteIds: string[];
    chunkIds: string[];
    entityIds: string[];
    eventIds: string[];
    evidenceIds: string[];
    ownerEntityId: string;
    ownerRegionId: string;
    regionId: string;
    pathKey: string;
    depth: number;
    localRank: number;
}

export interface ProductOwnershipInfo {
    clusterId: string;
    ownerRegionId: string;
    hierarchyCapId: string;
    hierarchyLevel: number;
}

interface ParentLink {
    parentId: string;
    relation: string;
    confidence: number;
}

interface OwnershipState extends ProductOwnershipRecord {
    parents: ParentLink[];
}

export function applyProductOwnerRegions(nodes: GalaxyNode[], links: GalaxyEdge[], infos: ProductOwnershipInfo[]): void {
    const records = compileProductOwnership(nodes, links);
    for (let index = 0; index < nodes.length; index++) {
        const record = records[index];
        const metadata = nodes[index].entity.metadata ?? {};
        nodes[index].entity.metadata = { ...metadata, productOwnership: record };
        infos[index].ownerRegionId = record.ownerRegionId;
        infos[index].clusterId = record.regionId || infos[index].clusterId;
    }
}

export function compileProductOwnership(nodes: GalaxyNode[], links: GalaxyEdge[]): ProductOwnershipRecord[] {
    const idToIndex = new Map(nodes.map((node, index) => [node.entity.id, index]));
    const states = nodes.map((node) => seedState(node));
    for (let index = 0; index < nodes.length; index++) {
        for (const parentId of arrayText(nodes[index].entity.metadata?.['signalParentIds'])) {
            addParent(states[index], parentId, 'signal-parent', 0.98);
        }
        addImplicitParents(states[index], nodes[index]);
    }
    for (const link of links) addEdgeParents(states, idToIndex, link);
    for (let pass = 0; pass < 5; pass++) {
        for (let index = 0; index < states.length; index++) mergeParentContext(states[index], states, idToIndex);
        mergeChildContextIntoEntityParents(states, idToIndex);
    }
    for (let index = 0; index < states.length; index++) {
        finalizeState(states[index], states, idToIndex);
    }
    return states.map(({ parents: _parents, ...record }) => record);
}

function seedState(node: GalaxyNode): OwnershipState {
    const metadata = node.entity.metadata || {};
    const lorentz = record(metadata['lorentz']);
    const sourceType = kindKey(text(metadata['sourceType'], node.entity.kind));
    const lane = laneKey(text(metadata['signalLane'], metadata['productLaneKind'], sourceType));
    const role = roleKey(text(metadata['signalStructuralRole']), sourceType, lane);
    const state: OwnershipState = {
        nodeId: node.entity.id,
        sourceType,
        role,
        lane,
        primaryParentId: '',
        ancestorIds: [],
        memberships: [],
        noteIds: [],
        chunkIds: [],
        entityIds: [],
        eventIds: [],
        evidenceIds: [],
        ownerEntityId: '',
        ownerRegionId: '',
        regionId: '',
        pathKey: '',
        depth: depthFor(sourceType, role),
        localRank: stableRank(node.entity.id),
        parents: [],
    };
    applyIdContext(state, node.entity.id);
    applyCapContext(state, text(lorentz['capId']));
    addParent(state, text(lorentz['parentNodeId']), 'lorentz-parent', 0.66);
    addContext(state.noteIds, text(metadata['noteId']));
    addContext(state.chunkIds, text(metadata['chunkId']));
    addContext(state.entityIds, text(metadata['sourceEntityId'], metadata['entityId'], metadata['canonicalEntityId']));
    addContext(state.evidenceIds, ...arrayText(metadata['compactedAnchorIds']));
    return state;
}

function applyCapContext(state: OwnershipState, capId: string): void {
    addContext(state.noteIds, capId.match(/^document:([^:]+)/)?.[1]);
    addContext(state.chunkIds, capId.match(/:chunk:([^:]+)/)?.[1]);
    addContext(state.entityIds, capId.match(/^identity:([^:]+)/)?.[1]);
    addContext(state.eventIds, capId.match(/^event:([^:]+)/)?.[1]);
}

function addImplicitParents(state: OwnershipState, node: GalaxyNode): void {
    const metadata = node.entity.metadata || {};
    const noteId = text(metadata['noteId']);
    const chunkId = text(metadata['chunkId']);
    const entityId = text(metadata['sourceEntityId'], metadata['entityId'], metadata['canonicalEntityId']);
    if (noteId && state.sourceType !== 'note') addParent(state, `embed:note:${noteId}`, 'note-context', 0.72);
    if (chunkId && state.sourceType !== 'chunk') addParent(state, `embed:chunk:${chunkId}`, 'chunk-context', 0.86);
    if (entityId && state.sourceType !== 'entity') addParent(state, `embed:entity:${entityId}`, 'entity-context', 0.9);
}

function addEdgeParents(states: OwnershipState[], idToIndex: Map<string, number>, link: GalaxyEdge): void {
    const edge = ownershipEdge(link, states[link.source], states[link.target]);
    if (!edge) return;
    const childIndex = idToIndex.get(edge.childId);
    if (childIndex === undefined) return;
    addParent(states[childIndex], edge.parentId, edge.relation, edge.confidence);
}

function ownershipEdge(link: GalaxyEdge, source?: OwnershipState, target?: OwnershipState): { childId: string; parentId: string; relation: string; confidence: number } | null {
    if (!source || !target) return null;
    const type = link.type.toLowerCase();
    if (/embedding-(backbone|bridge)/.test(type)) return null;
    if (/^(target-parent|note-chunk|chunk-anchor|chunk-entity)$/.test(type)) return parentToChild(source.nodeId, target.nodeId, type, link.confidence);
    if (/^(event-chunk|anchor-entity|event-entity|memory-entity)$/.test(type)) return parentToChild(target.nodeId, source.nodeId, type, link.confidence);
    if (/^(source|target|cause|effect|evidence|subject|state|fact-source|fact-target)$/.test(type)) return parentToChild(target.nodeId, source.nodeId, type, link.confidence);
    if (/causal|temporal/.test(type) && isFact(source.sourceType)) return parentToChild(target.nodeId, source.nodeId, type, link.confidence);
    if (isFact(source.sourceType) && (isEntity(target.sourceType) || target.sourceType === 'event' || target.sourceType === 'anchor')) {
        return parentToChild(target.nodeId, source.nodeId, type, link.confidence);
    }
    return null;
}

function parentToChild(parentId: string, childId: string, relation: string, confidence: number) {
    return { childId, parentId, relation, confidence };
}

function mergeParentContext(state: OwnershipState, states: OwnershipState[], idToIndex: Map<string, number>): void {
    for (const parent of state.parents) {
        applyIdContext(state, parent.parentId);
        const parentState = states[idToIndex.get(parent.parentId) ?? -1];
        if (!parentState) continue;
        if (!state.noteIds.length) mergeList(state.noteIds, parentState.noteIds);
        if (!state.chunkIds.length) mergeList(state.chunkIds, parentState.chunkIds);
        mergeList(state.entityIds, parentState.entityIds);
        mergeList(state.eventIds, parentState.eventIds);
        if (!state.evidenceIds.length) mergeList(state.evidenceIds, parentState.evidenceIds);
    }
}

function mergeChildContextIntoEntityParents(states: OwnershipState[], idToIndex: Map<string, number>): void {
    for (const child of states) {
        for (const parent of child.parents) {
            const parentState = states[idToIndex.get(parent.parentId) ?? -1];
            if (!parentState || parentState.sourceType !== 'entity') continue;
            mergeList(parentState.noteIds, child.noteIds);
            mergeList(parentState.chunkIds, child.chunkIds);
            mergeList(parentState.evidenceIds, child.evidenceIds);
            mergeList(parentState.eventIds, child.eventIds);
        }
    }
}

function finalizeState(state: OwnershipState, states: OwnershipState[], idToIndex: Map<string, number>): void {
    state.noteIds.sort();
    state.chunkIds.sort();
    state.entityIds.sort();
    state.eventIds.sort();
    state.evidenceIds.sort();
    state.primaryParentId = choosePrimaryParent(state, states, idToIndex);
    state.ancestorIds = collectAncestors(state.primaryParentId, states, idToIndex);
    state.ownerEntityId = isEntity(state.sourceType) ? firstId(state.entityIds, entityFromId(state.nodeId)) : firstId(state.entityIds);
    state.ownerRegionId = state.ownerEntityId ? `owner:entity:${state.ownerEntityId}` : '';
    state.regionId = productRegionId(state);
    state.memberships = state.parents
        .slice()
        .sort((left, right) => Number(right.parentId === state.primaryParentId) - Number(left.parentId === state.primaryParentId) || right.confidence - left.confidence || left.parentId.localeCompare(right.parentId))
        .map((parent) => ({
            parentId: parent.parentId,
            parentKind: kindFromId(parent.parentId, states[idToIndex.get(parent.parentId) ?? -1]?.sourceType),
            relation: parent.relation,
            confidence: parent.confidence,
            primary: parent.parentId === state.primaryParentId,
        }));
    state.pathKey = [firstId(state.noteIds, 'global'), firstId(state.chunkIds), state.ownerEntityId, state.sourceType, state.nodeId].filter(Boolean).join('/');
}

function choosePrimaryParent(state: OwnershipState, states: OwnershipState[], idToIndex: Map<string, number>): string {
    let best = '';
    let bestScore = -Infinity;
    for (const parent of state.parents) {
        const parentKind = kindFromId(parent.parentId, states[idToIndex.get(parent.parentId) ?? -1]?.sourceType);
        const score = parent.confidence + parentPriority(state.sourceType, parentKind, parent.relation);
        if (score > bestScore || (score === bestScore && parent.parentId < best)) {
            best = parent.parentId;
            bestScore = score;
        }
    }
    return best;
}

function parentPriority(childKind: string, parentKind: string, relation: string): number {
    if (childKind === 'structure-root') return parentKind === 'note' ? 12 : 0;
    if (childKind === 'chunk') return parentKind === 'structure-root' ? 12 : parentKind === 'note' ? 8 : 0;
    if (childKind === 'entity') return parentKind === 'chunk' ? 12 : parentKind === 'structure-root' ? 9 : parentKind === 'note' ? 4 : 0;
    if (childKind === 'anchor') return parentKind === 'entity' ? 14 : parentKind === 'chunk' ? 12 : parentKind === 'structure-root' ? 6 : 0;
    if (childKind === 'event') return parentKind === 'chunk' ? 13 : parentKind === 'entity' ? 11 : parentKind === 'structure-root' ? 7 : 0;
    if (childKind === 'memory-state') return parentKind === 'entity' ? 15 : parentKind === 'chunk' ? 9 : 0;
    if (isFact(childKind)) {
        if (parentKind === 'entity') return /source|target|subject|entity/.test(relation) ? 16 : 13;
        if (parentKind === 'event') return /cause|effect|temporal|causal/.test(relation) ? 15 : 12;
        if (parentKind === 'chunk') return 10;
        if (parentKind === 'anchor') return 8;
        if (parentKind === 'structure-root') return 5;
    }
    return parentKind === 'note' ? 1 : 0;
}

function collectAncestors(parentId: string, states: OwnershipState[], idToIndex: Map<string, number>): string[] {
    const out: string[] = [];
    const seen = new Set<string>();
    let current = parentId;
    for (let hops = 0; current && hops < 12 && !seen.has(current); hops++) {
        seen.add(current);
        out.push(current);
        const state = states[idToIndex.get(current) ?? -1];
        current = state?.primaryParentId || '';
    }
    return out;
}

function productRegionId(state: OwnershipState): string {
    const note = firstId(state.noteIds, 'global');
    const chunk = firstId(state.chunkIds);
    if (state.sourceType === 'note') return `product:story:${note}:document`;
    if (state.sourceType === 'structure-root') return `product:story:${note}:root:${rootKindFor(state)}`;
    if (state.sourceType === 'chunk' && chunk) return `product:story:${note}:chunk:${chunk}`;
    if (chunk) return `product:story:${note}:chunk:${chunk}`;
    return `product:story:${note}:signals:${state.lane || state.role || 'semantic'}`;
}

function addParent(state: OwnershipState, parentId: string, relation: string, confidence: number): void {
    const id = text(parentId);
    if (!id || id === state.nodeId) return;
    const current = state.parents.find((parent) => parent.parentId === id);
    if (current) {
        current.confidence = Math.max(current.confidence, confidence);
        if (confidence >= current.confidence) current.relation = relation;
        return;
    }
    state.parents.push({ parentId: id, relation, confidence });
}

function applyIdContext(state: OwnershipState, id: string): void {
    const note = id.match(/^embed:note:(.+)$/)?.[1] || id.match(/^embed:structure-root:([^:]+)/)?.[1];
    const chunk = id.match(/^embed:chunk:(.+)$/)?.[1];
    const entity = entityFromId(id);
    const event = id.match(/^embed:event:(.+)$/)?.[1];
    const evidence = id.match(/^embed:anchor:(.+)$/)?.[1];
    addContext(state.noteIds, note);
    addContext(state.chunkIds, chunk);
    addContext(state.entityIds, entity);
    addContext(state.eventIds, event);
    addContext(state.evidenceIds, evidence);
}

function kindFromId(id: string, fallback = ''): string {
    if (fallback) return fallback;
    if (/^embed:note:/.test(id)) return 'note';
    if (/^embed:structure-root:/.test(id)) return 'structure-root';
    if (/^embed:chunk:/.test(id)) return 'chunk';
    if (/^embed:entity:/.test(id)) return 'entity';
    if (/^embed:anchor:/.test(id)) return 'anchor';
    if (/^embed:event:/.test(id)) return 'event';
    if (/^embed:(graph-fact|temporalFact|causalFact|memory):/.test(id)) return kindKey(id.split(':')[1]);
    return '';
}

function kindKey(value: string): string {
    const key = value.trim().toLowerCase().replace(/_/g, '-');
    if (/^(note|doc|document)$/.test(key)) return 'note';
    if (/structure-root|root/.test(key)) return 'structure-root';
    if (/chunk|scene|chapter/.test(key)) return 'chunk';
    if (/entity|character|location|network|npc|creature/.test(key)) return 'entity';
    if (/anchor|evidence|source-span/.test(key)) return 'anchor';
    if (/event/.test(key)) return 'event';
    if (/causalfact|causal-fact/.test(key)) return 'causal-fact';
    if (/temporalfact|temporal-fact/.test(key)) return 'temporal-fact';
    if (/graph-fact|graphfact|relationship/.test(key)) return 'graph-fact';
    if (/memory|state/.test(key)) return 'memory-state';
    return key;
}

function laneKey(value: string): string {
    const key = value.toLowerCase();
    if (/co.?occurrence|weak/.test(key)) return 'cooccurrence';
    if (/causal|cause/.test(key)) return 'causal';
    if (/temporal|timeline/.test(key)) return 'temporal';
    if (/memory|state/.test(key)) return 'memory';
    if (/relationship|relation|authority|communication|approval|family|intimacy|transfer/.test(key)) return 'relationship';
    if (/entity|identity|character|location|network/.test(key)) return 'identity';
    if (/anchor|evidence|source/.test(key)) return 'evidence';
    if (/chunk|document|note|structure/.test(key)) return 'document';
    if (/event|scene/.test(key)) return 'event';
    return key || 'semantic';
}

function roleKey(explicit: string, sourceType: string, lane: string): string {
    if (explicit) return explicit.toLowerCase();
    if (sourceType === 'note' || sourceType === 'structure-root') return 'root';
    if (sourceType === 'chunk') return 'spine';
    if (sourceType === 'anchor') return 'evidence';
    if (lane === 'cooccurrence') return 'bridge';
    if (isFact(sourceType) || sourceType === 'event' || sourceType === 'memory-state') return 'fact';
    return 'child';
}

function depthFor(sourceType: string, role: string): number {
    if (sourceType === 'note') return 0;
    if (sourceType === 'structure-root') return 1;
    if (sourceType === 'chunk') return 2;
    if (sourceType === 'entity' || sourceType === 'event') return 3;
    if (isFact(sourceType) || sourceType === 'memory-state') return 4;
    if (role === 'evidence' || sourceType === 'anchor') return 5;
    return 6;
}

function rootKindFor(state: OwnershipState): string {
    const idRoot = state.nodeId.match(/^embed:structure-root:[^:]+:(.+)$/)?.[1];
    return laneKey(idRoot || state.lane || state.role || 'document');
}

function isFact(kind: string): boolean {
    return kind === 'graph-fact' || kind === 'causal-fact' || kind === 'temporal-fact';
}

function isEntity(kind: string): boolean {
    return kind === 'entity';
}

function entityFromId(id: string): string {
    return id.match(/^embed:entity:(.+)$/)?.[1] || '';
}

function addContext(list: string[], ...values: unknown[]): void {
    for (const value of values) {
        const item = text(value);
        if (item && !list.includes(item)) list.push(item);
    }
}

function mergeList(target: string[], source: string[]): void {
    for (const item of source) if (!target.includes(item)) target.push(item);
}

function firstId(values: string[], fallback = ''): string {
    return values[0] || fallback;
}

function arrayText(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : [];
}

function text(...values: unknown[]): string {
    for (const value of values) {
        const result = String(value || '').trim();
        if (result) return result;
    }
    return '';
}

function record(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function stableRank(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
    return hash >>> 0;
}
