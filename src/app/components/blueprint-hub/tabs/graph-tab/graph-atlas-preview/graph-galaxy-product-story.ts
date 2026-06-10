import type { GalaxyEdge, GalaxyNode } from './graph-galaxy-engine';

export interface ProductStoryVec3 {
    x: number;
    y: number;
    z: number;
}

export interface ProductStoryInfo {
    regionId: string;
    documentId: string;
    rootKind: string;
    chunkId: string;
    ownerEntityId: string;
    parentNodeId: string;
    depth: number;
    localRank: number;
    pathKey: string;
}

export interface ProductStoryLayoutInfo {
    clusterId: string;
    lane: string;
    hierarchyCapId: string;
    hierarchyLevel: number;
    ownerRegionId: string;
    story: ProductStoryInfo;
}

export const EMPTY_PRODUCT_STORY: ProductStoryInfo = {
    regionId: '',
    documentId: '',
    rootKind: '',
    chunkId: '',
    ownerEntityId: '',
    parentNodeId: '',
    depth: -1,
    localRank: 0,
    pathKey: '',
};

export function applyProductStoryRegions(nodes: GalaxyNode[], links: GalaxyEdge[], infos: ProductStoryLayoutInfo[]): void {
    const stories = nodes.map((node, index) => productStoryInfo(node, infos[index]));
    for (let pass = 0; pass < 2; pass++) {
        for (const link of links) {
            const source = stories[link.source];
            const target = stories[link.target];
            if (!source || !target) continue;
            inheritSourceContext(source, target, link.type);
            inheritSourceContext(target, source, link.type);
        }
    }
    for (let index = 0; index < infos.length; index++) {
        const info = infos[index];
        const story = stories[index];
        const compiledRegionId = story.regionId;
        if (!story.ownerEntityId) story.ownerEntityId = ownerIdFromRegion(info.ownerRegionId);
        story.regionId = compiledRegionId || storyRegionId(nodes[index], info, story);
        story.pathKey = storyPathKey(story);
        info.story = story;
        if (story.regionId) info.clusterId = story.regionId;
    }
}

export function productStoryBasinCenter(regionId: string, fallbackLane: string, index: number, total: number): ProductStoryVec3 | null {
    if (!regionId.startsWith('product:story:')) return null;
    const tokens = regionId.split(':');
    const role = tokens.includes('document') ? 'document'
        : tokens.includes('root') ? 'root'
            : tokens.includes('chunk') ? 'chunk'
                : tokens.includes('owner') ? 'owner'
                    : tokens.includes('lane') || tokens.includes('signals') ? 'signal'
                        : 'story';
    const rootKind = tokenAfter(tokens, 'root') || tokenAfter(tokens, 'lane') || tokenAfter(tokens, 'signals') || fallbackLane;
    const docId = tokens[2] || 'global';
    const chunkId = tokenAfter(tokens, 'chunk');
    const ownerId = tokenAfter(tokens, 'owner');
    const x = role === 'document' ? -1.48
        : role === 'root' ? -1.12
            : role === 'chunk' ? -0.54
                : role === 'owner' ? 0.18
                    : 0.5;
    const y = rootBand(rootKind) + (stableUnit(`${docId}:doc-y`) - 0.5) * 0.12
        + (ownerId ? (stableUnit(`${ownerId}:owner-y`) - 0.5) * 0.34 : 0);
    const z = (stableUnit(`${docId}:doc-z`) - 0.5) * 0.44
        + (chunkId ? (stableUnit(`${docId}:${chunkId}:chunk-z`) - 0.5) * 0.72 : 0)
        + (chunkId ? chunkOrdinalBand(chunkId) * 0.14 : 0)
        + (ownerId ? (stableUnit(`${ownerId}:owner-z`) - 0.5) * 0.12 : 0)
        + ((index / Math.max(1, total)) - 0.5) * 0.08;
    return { x, y, z };
}

function productStoryInfo(node: GalaxyNode, info: ProductStoryLayoutInfo): ProductStoryInfo {
    const metadata = record(node.entity.metadata);
    const ownership = productOwnershipStory(metadata);
    if (ownership) return ownership;
    const lorentz = record(metadata['lorentz']);
    const membership = firstMembership(lorentz['memberships']);
    const capId = text(lorentz['capId'], membership['treeId'], info.hierarchyCapId);
    const sourceType = text(metadata['sourceType'], node.entity.kind);
    const story: ProductStoryInfo = {
        ...EMPTY_PRODUCT_STORY,
        documentId: normalizeId(text(metadata['noteId'], firstArrayText(lorentz['supportNoteIds']), documentFromCap(capId), documentFromId(node.entity.id))),
        rootKind: storyRootKind(capId, sourceType, info.lane, text(lorentz['primaryTreeKind'], membership['treeKind'])),
        chunkId: normalizeId(text(metadata['chunkId'], firstArrayText(lorentz['supportChunkIds']), chunkFromCap(capId), chunkFromId(node.entity.id))),
        ownerEntityId: normalizeEntityId(text(metadata['sourceEntityId'], metadata['entityId'], metadata['canonicalEntityId'], metadata['targetEntityId'], ownerIdFromRegion(info.ownerRegionId), entityFromCap(capId), entityFromId(node.entity.id), entityFromId(text(lorentz['parentNodeId'], membership['parentNodeId'])))),
        parentNodeId: text(lorentz['parentNodeId'], membership['parentNodeId']),
        depth: depthFor(sourceType, capId, info.hierarchyLevel),
        localRank: rankFor(metadata, capId, node.entity.id),
    };
    return story;
}

function productOwnershipStory(metadata: Record<string, unknown>): ProductStoryInfo | null {
    const ownership = record(metadata['productOwnership']);
    const regionId = text(ownership['regionId']);
    if (!regionId) return null;
    const story: ProductStoryInfo = {
        ...EMPTY_PRODUCT_STORY,
        regionId,
        documentId: normalizeId(firstArrayText(ownership['noteIds'])),
        rootKind: text(ownership['lane'], ownership['role']),
        chunkId: normalizeId(firstArrayText(ownership['chunkIds'])),
        ownerEntityId: normalizeEntityId(text(ownership['ownerEntityId'])),
        parentNodeId: text(ownership['primaryParentId']),
        depth: finite(ownership['depth']),
        localRank: finite(ownership['localRank']),
        pathKey: text(ownership['pathKey']),
    };
    return story;
}

function inheritSourceContext(source: ProductStoryInfo, target: ProductStoryInfo, edgeType: string): void {
    const key = edgeType.toLowerCase();
    if (!target.documentId && source.documentId && /note|document|chunk|anchor|event|fact|causal|temporal|memory|relationship|entity/.test(key)) target.documentId = source.documentId;
    if (!target.chunkId && source.chunkId && /chunk|anchor|event|fact|causal|temporal|memory|relationship|entity/.test(key)) target.chunkId = source.chunkId;
    if (!target.ownerEntityId && source.ownerEntityId && /anchor-entity|event-entity|fact|causal|temporal|memory|relationship|trust|authority|communication|approval|family|intimacy|transfer/.test(key)) {
        target.ownerEntityId = source.ownerEntityId;
    }
}

function storyRegionId(node: GalaxyNode, info: ProductStoryLayoutInfo, story: ProductStoryInfo): string {
    const type = text(node.entity.metadata?.['sourceType'], node.entity.kind);
    const doc = story.documentId || 'global';
    if (isDocument(type, info.hierarchyCapId)) return `product:story:${doc}:document`;
    if (isRoot(type, info.hierarchyCapId)) return `product:story:${doc}:root:${story.rootKind || 'document'}`;
    if (isChunk(type, info.hierarchyCapId) && story.chunkId) return `product:story:${doc}:chunk:${story.chunkId}`;
    if (story.ownerEntityId) {
        return story.chunkId ? `product:story:${doc}:chunk:${story.chunkId}:owner:${story.ownerEntityId}` : `product:story:${doc}:owner:${story.ownerEntityId}`;
    }
    if (story.chunkId) return `product:story:${doc}:chunk:${story.chunkId}:lane:${story.rootKind || info.lane || 'signals'}`;
    if (story.documentId) return `product:story:${doc}:signals:${story.rootKind || info.lane || 'semantic'}`;
    return info.clusterId;
}

function storyPathKey(story: ProductStoryInfo): string {
    return [story.documentId, story.rootKind, story.chunkId, story.ownerEntityId].filter(Boolean).join('/');
}

function depthFor(sourceType: string, capId: string, level: number): number {
    const type = `${sourceType} ${capId}`.toLowerCase();
    if (/embed:note|^document:[^:]+$|\b(note|document)\b/.test(type)) return 0;
    if (/root:|\bstructure-root\b/.test(type)) return 1;
    if (/:chunk:|\b(chunk|scene|chapter)\b/.test(type)) return 2;
    if (/identity:|\b(entity|event)\b/.test(type)) return 3;
    if (/:facts:|\bfact|memory|state/.test(type)) return 4;
    if (/anchor|evidence/.test(type)) return 5;
    return Number.isFinite(level) && level > 0 ? Math.min(6, Math.max(0, Math.round(level))) : 6;
}

function storyRootKind(capId: string, sourceType: string, lane: string, treeKind: string): string {
    const root = matchOne(capId, /:root:([^:]+)/i);
    if (root) return root.toLowerCase();
    const textValue = `${capId} ${sourceType} ${lane} ${treeKind}`.toLowerCase();
    if (/causal|cause|effect/.test(textValue)) return 'causal';
    if (/temporal|timeline|before|after/.test(textValue)) return 'temporal';
    if (/relationship|relation|authority|communication|approval|family|intimacy|transfer|co.?occurs/.test(textValue)) return 'relationship';
    if (/identity|entity|character|location|network/.test(textValue)) return 'identity';
    if (/evidence|anchor|source|provenance/.test(textValue)) return 'evidence';
    if (/event|scene/.test(textValue)) return 'event';
    return 'document';
}

function isDocument(sourceType: string, capId: string): boolean {
    return /^(document:[^:]+)$/i.test(capId) || /\b(note|document)\b/i.test(sourceType);
}

function isRoot(sourceType: string, capId: string): boolean {
    return /:root:/i.test(capId) || /\bstructure-root\b/i.test(sourceType);
}

function isChunk(sourceType: string, capId: string): boolean {
    return /:chunk:[^:]+$/i.test(capId) || /\b(chunk|scene|chapter)\b/i.test(sourceType);
}

function rankFor(metadata: Record<string, unknown>, capId: string, nodeId: string): number {
    const explicit = Number(metadata['localRank'] ?? metadata['order'] ?? metadata['sourceOrder']);
    if (Number.isFinite(explicit)) return explicit;
    return Math.floor(stableUnit(`${capId}:${nodeId}:rank`) * 100000);
}

function rootBand(rootKind: string): number {
    const key = rootKind.toLowerCase();
    if (/evidence|document/.test(key)) return 0.62;
    if (/identity|entity/.test(key)) return 0.34;
    if (/relationship|relation/.test(key)) return 0.08;
    if (/event|scene/.test(key)) return -0.12;
    if (/temporal|timeline/.test(key)) return -0.34;
    if (/causal|cause/.test(key)) return -0.58;
    return 0;
}

function chunkOrdinalBand(chunkId: string): number {
    const match = chunkId.match(/(\d+)$/);
    if (!match) return stableUnit(`${chunkId}:chunk-ordinal`) - 0.5;
    return ((Number(match[1]) % 9) - 4) / 4;
}

function documentFromCap(capId: string): string { return matchOne(capId, /^document:([^:]+)/i); }
function chunkFromCap(capId: string): string { return matchOne(capId, /:chunk:([^:]+)/i); }
function entityFromCap(capId: string): string { return matchOne(capId, /^identity:([^:]+)/i); }
function documentFromId(id: string): string { return matchOne(id, /^embed:note:([^:]+)/i); }
function chunkFromId(id: string): string { return matchOne(id, /^embed:chunk:([^:]+)/i); }
function entityFromId(id: string): string { return matchOne(id, /^embed:entity:([^:]+)/i); }
function ownerIdFromRegion(regionId: string): string { return normalizeEntityId(regionId.replace(/^owner:entity:/i, '')); }

function tokenAfter(tokens: string[], token: string): string {
    const index = tokens.indexOf(token);
    return index >= 0 ? tokens[index + 1] || '' : '';
}

function firstMembership(value: unknown): Record<string, unknown> {
    return Array.isArray(value) ? record(value[0]) : {};
}

function firstArrayText(value: unknown): string {
    return Array.isArray(value) ? text(value[0]) : '';
}

function normalizeId(value: string): string {
    return value.trim().replace(/^embed:(note|chunk):/i, '');
}

function normalizeEntityId(value: string): string {
    return value.trim().replace(/^embed:entity:/i, '').replace(/^identity:/i, '').replace(/^entity:/i, '');
}

function matchOne(value: string, pattern: RegExp): string {
    return value.match(pattern)?.[1] || '';
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

function finite(value: unknown): number {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
}

function stableUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
    return (hash >>> 0) / 4294967295;
}
