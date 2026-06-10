import type { GalaxyEdge, GalaxyNode } from './graph-galaxy-engine';

export interface ProductOwnershipInfo {
    clusterId: string;
    ownerRegionId: string;
    hierarchyCapId: string;
    hierarchyLevel: number;
}

interface OwnerCandidate {
    regionId: string;
    score: number;
}

export function applyProductOwnerRegions(nodes: GalaxyNode[], links: GalaxyEdge[], infos: ProductOwnershipInfo[]): void {
    const owners = new Map<number, OwnerCandidate>();
    const entityRegions = new Map<number, string>();
    for (let index = 0; index < nodes.length; index++) {
        const node = nodes[index];
        const direct = directOwnerRegion(node);
        const canonical = canonicalEntityRegion(node);
        if (canonical) {
            entityRegions.set(index, canonical);
            putOwner(owners, index, canonical, 1);
        } else if (direct && !isDocumentStructural(node, infos[index])) {
            putOwner(owners, index, direct, 0.92);
        }
    }

    for (const link of links) {
        const sourceRegion = entityRegions.get(link.source);
        const targetRegion = entityRegions.get(link.target);
        const score = ownershipEdgeScore(link.type, link.confidence);
        if (sourceRegion && !isDocumentStructural(nodes[link.target], infos[link.target])) putOwner(owners, link.target, sourceRegion, score);
        if (targetRegion && !isDocumentStructural(nodes[link.source], infos[link.source])) putOwner(owners, link.source, targetRegion, score);
    }

    for (let pass = 0; pass < 2; pass++) {
        for (const link of links) {
            if (!canPropagateOwnership(link.type)) continue;
            const sourceOwner = owners.get(link.source);
            const targetOwner = owners.get(link.target);
            const score = ownershipEdgeScore(link.type, link.confidence) * 0.72;
            if (sourceOwner && !targetOwner && !isDocumentStructural(nodes[link.target], infos[link.target])) putOwner(owners, link.target, sourceOwner.regionId, score);
            if (targetOwner && !sourceOwner && !isDocumentStructural(nodes[link.source], infos[link.source])) putOwner(owners, link.source, targetOwner.regionId, score);
        }
    }

    for (let index = 0; index < infos.length; index++) {
        const owner = owners.get(index);
        if (!owner || isDocumentStructural(nodes[index], infos[index])) continue;
        infos[index].ownerRegionId = owner.regionId;
        infos[index].clusterId = owner.regionId;
    }
}

function putOwner(owners: Map<number, OwnerCandidate>, index: number, regionId: string, score: number): void {
    const current = owners.get(index);
    if (current && (current.score > score || (current.score === score && current.regionId <= regionId))) return;
    owners.set(index, { regionId, score });
}

function directOwnerRegion(node: GalaxyNode): string {
    const metadata = node.entity.metadata || {};
    return ownerRegionFromId(
        metadata['sourceEntityId'],
        metadata['entityId'],
        metadata['canonicalEntityId'],
        metadata['targetEntityId'],
    );
}

function canonicalEntityRegion(node: GalaxyNode): string {
    const metadata = node.entity.metadata || {};
    const text = `${node.entity.kind || ''} ${metadata['sourceType'] || ''}`.toLowerCase();
    if (!/\bentity\b/.test(text) && !node.entity.id.startsWith('embed:entity:')) return '';
    return ownerRegionFromId(metadata['sourceEntityId'], metadata['sourceId'], node.entity.id);
}

function ownerRegionFromId(...values: unknown[]): string {
    for (const value of values) {
        const id = normalizeEntityId(value);
        if (id) return `owner:entity:${id}`;
    }
    return '';
}

function normalizeEntityId(value: unknown): string {
    const text = String(value || '').trim();
    if (!text) return '';
    return text
        .replace(/^embed:entity:/i, '')
        .replace(/^identity:/i, '')
        .replace(/^entity:/i, '');
}

function isDocumentStructural(node: GalaxyNode, info: ProductOwnershipInfo): boolean {
    const metadata = node.entity.metadata || {};
    const text = `${node.entity.kind || ''} ${metadata['sourceType'] || ''} ${node.entity.label || ''}`.toLowerCase();
    if (/\b(note|document|doc|structure-root|chunk|chapter|section|scene)\b/.test(text)) return true;
    return !!info.hierarchyCapId && info.hierarchyCapId.startsWith('document:') && info.hierarchyLevel <= 2;
}

function ownershipEdgeScore(type: string, confidence: number): number {
    const key = type.toLowerCase();
    let score = Math.max(0.12, Math.min(1, confidence));
    if (/anchor-entity|event-entity|memory-entity|fact-source|fact-target/.test(key)) score += 0.22;
    if (/relationship|trust|authority|communication|approval|family|intimacy|transfer/.test(key)) score += 0.14;
    if (/causal|temporal/.test(key)) score += 0.08;
    return Math.min(1, score);
}

function canPropagateOwnership(type: string): boolean {
    const key = type.toLowerCase();
    if (/note-chunk|chunk-anchor|chunk-entity|event-chunk/.test(key)) return false;
    return /target-parent|fact|event|memory|causal|temporal|relationship|trust|authority|communication|approval|family|intimacy|transfer/.test(key);
}
