import type { DocumentUnit, EvidenceSpan, GraphFactCandidate, RhetoricalUnit } from '../../../../../graph-rebuild/graph-document-sidecar';
import type { GraphDocumentReviewRow } from '../../../../../graph-rebuild/graph-document-review';
import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import type { GraphInventory } from './graph-atlas-preview.component';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';

const STRUCTURE_KINDS = new Set([
    'document', 'section', 'subsection', 'paragraph_group', 'chapter', 'scene',
    'list', 'table', 'figure', 'code_block', 'caption', 'parent_chunk', 'leaf_chunk',
]);

export function buildGraphCanvasInventory(snapshot: GraphRebuildSnapshot | null): GraphInventory {
    if (!snapshot) return { nodes: [], edges: [], kindCounts: [], sourceLabel: 'graph rebuild snapshot' };
    const nodes: GalaxyRenderableNode[] = [];
    const edges: GalaxyInputEdge[] = [];
    const reviewRows = new Map((snapshot.documentReviewSummary?.rows || []).map((row) => [row.objectId, row]));
    const evidence = snapshot.documentSidecarSummary?.evidenceSpans || [];
    const evidenceByUnit = evidenceByUnitId(evidence);

    addEntityGraph(snapshot, nodes, edges);
    addChunkGraph(snapshot, nodes, edges);
    addStructureGraph(snapshot, reviewRows, evidenceByUnit, nodes, edges);
    addFactGraph(snapshot, reviewRows, evidenceByUnit, nodes, edges);
    addDiscourseGraph(snapshot, nodes, edges);

    return {
        nodes,
        edges,
        kindCounts: graphKindCounts(nodes),
        sourceLabel: 'graph rebuild snapshot + document sidecar',
    };
}

function addEntityGraph(snapshot: GraphRebuildSnapshot, nodes: GalaxyRenderableNode[], edges: GalaxyInputEdge[]): void {
    for (const [index, node] of snapshot.nodes.entries()) {
        nodes.push({
            id: node.id,
            label: node.label,
            kind: node.kind,
            aliases: node.aliases,
            totalMentions: node.totalMentions,
            ...stablePoint(node.id, index),
            colorHsl: entityColorStore.getRawHsl(node.kind as never),
            metadata: {
                sourceType: 'graph-rebuild',
                sourceEntityId: node.entityId,
                graphKind: 'entity',
                canvasLens: 'entities',
                reviewState: 'accepted',
                confidence: 1,
                subtitle: `${node.totalMentions} mentions`,
                sourceSnippet: `${node.label} is registered as ${node.kind}.`,
                searchableText: `${node.label} ${node.aliases.join(' ')} ${node.kind}`,
                relatedEntityIds: [node.entityId],
                anchorIds: node.anchorIds,
                noteIds: node.noteIds,
                graphImpact: `${node.anchorIds.length} accepted anchors across ${node.noteIds.length} documents.`,
            },
        });
    }
    for (const edge of snapshot.edges) {
        edges.push({
            id: edge.id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
            type: edge.type,
            confidence: clampConfidence(edge.confidence + edge.weight * 0.08),
            metadata: {
                canvasLens: 'entities',
                reviewState: 'accepted',
                confidence: edge.confidence,
                evidenceIds: edge.evidenceAnchorIds,
                relatedEntityIds: [edge.sourceId, edge.targetId],
                reasons: edge.scopeKeys,
                searchableText: `${edge.type} ${edge.scopeKeys.join(' ')}`,
                graphImpact: `Durable relation with ${edge.evidenceAnchorIds.length} evidence anchors.`,
            },
        });
    }
}

function addChunkGraph(snapshot: GraphRebuildSnapshot, nodes: GalaxyRenderableNode[], edges: GalaxyInputEdge[]): void {
    const mentionCounts = new Map<string, number>();
    for (const anchor of snapshot.entityAnchors) {
        if (anchor.chunkId) mentionCounts.set(anchor.chunkId, (mentionCounts.get(anchor.chunkId) || 0) + 1);
    }
    const offset = nodes.length;
    for (const [index, chunk] of snapshot.chunks.entries()) {
        nodes.push({
            id: chunkNodeId(chunk.id),
            label: `Chunk ${chunk.ordinal + 1}`,
            kind: 'leaf_chunk',
            totalMentions: Math.max(1, mentionCounts.get(chunk.id) || 0),
            ...stablePoint(chunk.id, offset + index),
            colorHsl: graphKindHsl('structure'),
            metadata: {
                sourceType: 'document-structure',
                graphKind: 'chunk',
                canvasLens: 'structure',
                reviewState: 'ledger_only',
                confidence: 1,
                detector: chunk.source,
                subtitle: chunk.role || chunk.source,
                sourceSnippet: chunk.splitReason || chunk.meaningFrame?.splitReason || '',
                searchableText: `${chunk.role || ''} ${chunk.source} ${chunk.splitReason || ''}`,
                chunkId: chunk.id,
                noteId: chunk.noteId,
                sourceStart: chunk.start,
                sourceEnd: chunk.end,
                galaxyId: `structure-note:${chunk.noteId}`,
                galaxyLabel: 'Document structure',
                graphImpact: 'Retrieval leaf and entity-evidence container.',
            },
        });
    }
    const entityIds = new Set(snapshot.nodes.map((node) => node.id));
    const chunkIds = new Set(snapshot.chunks.map((chunk) => chunk.id));
    for (const anchor of snapshot.entityAnchors) {
        if (!anchor.chunkId || !entityIds.has(anchor.entityId) || !chunkIds.has(anchor.chunkId)) continue;
        edges.push({
            id: `anchor:${anchor.id}`,
            sourceId: chunkNodeId(anchor.chunkId),
            targetId: anchor.entityId,
            type: 'entity_anchor',
            confidence: clampConfidence(anchor.confidence),
            metadata: {
                canvasLens: 'structure',
                reviewState: 'accepted',
                noteId: anchor.noteId,
                sourceStart: anchor.sourceStart,
                sourceEnd: anchor.sourceEnd,
                sourceSnippet: anchor.surface,
                evidenceIds: [anchor.id],
                relatedEntityIds: [anchor.entityId],
                graphImpact: 'Binds a registered entity to its source chunk.',
            },
        });
    }
}

function addStructureGraph(
    snapshot: GraphRebuildSnapshot,
    reviewRows: Map<string, GraphDocumentReviewRow>,
    evidenceByUnit: Map<string, EvidenceSpan[]>,
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
): void {
    const sidecar = snapshot.documentSidecarSummary;
    if (!sidecar) return;
    const selected = uniqueUnits(sidecar.units.filter((unit) => STRUCTURE_KINDS.has(unit.kind)));
    const selectedIds = new Set(selected.map((unit) => unit.id));
    const offset = nodes.length;
    for (const [index, unit] of selected.entries()) {
        nodes.push(sidecarNode(unit, reviewRows.get(unit.id), evidenceByUnit.get(unit.id) || [], 'structure', offset + index));
        if (unit.parentId && selectedIds.has(unit.parentId)) {
            edges.push({
                id: `structure-edge:${unit.parentId}:${unit.id}`,
                sourceId: structureNodeId(unit.parentId),
                targetId: structureNodeId(unit.id),
                type: 'contains',
                confidence: unit.confidence.score,
                metadata: {
                    canvasLens: 'structure',
                    reviewState: reviewRows.get(unit.id)?.state || 'ledger_only',
                    detector: unit.confidence.source,
                    reasons: unit.confidence.reasons,
                    noteId: unit.noteId,
                    sourceStart: unit.start,
                    sourceEnd: unit.end,
                    graphImpact: 'Preserves document parent-child lineage.',
                },
            });
        }
    }
}

function addFactGraph(
    snapshot: GraphRebuildSnapshot,
    reviewRows: Map<string, GraphDocumentReviewRow>,
    evidenceByUnit: Map<string, EvidenceSpan[]>,
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
): void {
    const sidecar = snapshot.documentSidecarSummary;
    if (!sidecar) return;
    const facts: Array<GraphFactCandidate | RhetoricalUnit> = uniqueUnits([
        ...sidecar.graphFactCandidates,
        ...sidecar.rhetoricalUnits,
    ]) as Array<GraphFactCandidate | RhetoricalUnit>;
    const entityBySurface = entitySurfaceIndex(snapshot);
    const offset = nodes.length;
    for (const [index, fact] of facts.entries()) {
        const row = reviewRows.get(fact.id);
        const spans = evidenceByUnit.get(fact.id) || [];
        const relatedEntityIds = factSurfaces(fact).map((surface) => entityBySurface.get(normalize(surface))).filter(isString);
        const baseNode = sidecarNode(fact, row, spans, 'facts', offset + index);
        nodes.push({
            ...baseNode,
            id: factNodeId(fact.id),
            colorHsl: graphKindHsl(fact.kind === 'event' ? 'event' : 'fact'),
            metadata: {
                ...baseNode.metadata,
                relatedEntityIds,
                graphImpact: fact.kind === 'n_ary_claim'
                    ? 'Compiles as an evidence-backed n-ary claim after review.'
                    : 'Remains a reviewable fact candidate until accepted.',
            },
        });
        for (const entityId of relatedEntityIds) {
            edges.push({
                id: `fact-entity:${fact.id}:${entityId}`,
                sourceId: factNodeId(fact.id),
                targetId: entityId,
                type: 'mentions_entity',
                confidence: fact.confidence.score,
                metadata: {
                    canvasLens: 'facts',
                    reviewState: row?.state || 'proposed',
                    evidenceIds: factEvidenceIds(fact),
                    relatedEntityIds: [entityId],
                    graphImpact: 'Candidate participation edge; no topology commit before review.',
                },
            });
        }
    }
}

function addDiscourseGraph(snapshot: GraphRebuildSnapshot, nodes: GalaxyRenderableNode[], edges: GalaxyInputEdge[]): void {
    const spine = snapshot.discourseSpineSummary;
    if (!spine) return;
    const promotion = snapshot.discoursePromotionSurfaceSummary;
    const clusterByTarget = new Map<string, { id: string; label: string; score: number; reasons: string[]; members: string[] }>();
    for (const cluster of spine.clusters) {
        for (const targetId of cluster.targetIds) {
            clusterByTarget.set(targetId, {
                id: cluster.id,
                label: cluster.label,
                score: cluster.score,
                reasons: cluster.rationale,
                members: cluster.targetIds,
            });
        }
    }
    const labelsByTarget = new Map<string, string[]>();
    for (const label of spine.labels) {
        const values = labelsByTarget.get(label.targetId) || [];
        values.push(`${label.labelKind}: ${label.value}`);
        labelsByTarget.set(label.targetId, values);
    }
    const offset = nodes.length;
    for (const [index, target] of spine.targets.entries()) {
        const cluster = clusterByTarget.get(target.targetId);
        const labels = labelsByTarget.get(target.targetId) || [];
        nodes.push({
            id: discourseNodeId(target.targetId),
            label: target.label,
            kind: target.kind,
            totalMentions: Math.max(1, target.entityIds.length),
            ...stablePoint(target.targetId, offset + index),
            colorHsl: graphKindHsl('discourse'),
            metadata: {
                sourceType: 'discourse-spine',
                graphKind: 'discourse',
                canvasLens: 'discourse',
                reviewState: 'proposed',
                confidence: cluster?.score ?? 0.6,
                detector: spine.implementationMode,
                subtitle: labels.slice(0, 2).join(' · ') || target.kind,
                sourceSnippet: target.label,
                searchableText: `${target.label} ${labels.join(' ')}`,
                noteId: target.noteId,
                chunkId: target.chunkId,
                relatedEntityIds: target.entityIds,
                evidenceIds: target.parentTargetIds,
                galaxyId: cluster ? `discourse-cluster:${cluster.id}` : 'discourse-cluster:unclustered',
                galaxyLabel: cluster?.label || 'Unclustered discourse',
                clusterConfidence: cluster?.score ?? 0.5,
                clusterReasons: cluster?.reasons || [],
                clusterSummary: cluster ? `${cluster.label} groups ${cluster.members.length} discourse targets.` : 'No shared semantic cluster yet.',
                memberIds: (cluster?.members || []).map(discourseNodeId),
                graphImpact: 'Retrieval/discourse overlay only until explicitly promoted.',
            },
        });
    }
    for (const wormhole of promotion?.chunkWormholes || []) {
        edges.push({
            id: wormhole.id,
            sourceId: discourseNodeId(wormhole.sourceTargetId),
            targetId: discourseNodeId(wormhole.targetTargetId),
            type: 'chunk_resonates_with',
            confidence: wormhole.score,
            metadata: {
                interactionKind: 'wormhole',
                canvasLens: 'discourse',
                reviewState: wormhole.state,
                detector: 'discourse_promotion_surface',
                sourceSnippet: `${wormhole.sourceTargetId} resonates with ${wormhole.targetTargetId}.`,
                evidenceIds: wormhole.evidenceTargetIds,
                reasons: wormhole.flags,
                searchableText: `${wormhole.label} ${wormhole.flags.join(' ')}`,
                graphImpact: 'Proposed cross-document bridge; topology mutation is disabled.',
            },
        });
    }
}

function sidecarNode(
    unit: DocumentUnit,
    row: GraphDocumentReviewRow | undefined,
    evidence: EvidenceSpan[],
    canvasLens: 'structure' | 'facts',
    index: number,
): GalaxyRenderableNode {
    const nodeId = canvasLens === 'structure' ? structureNodeId(unit.id) : factNodeId(unit.id);
    return {
        id: nodeId,
        label: row?.title || unit.label,
        kind: unit.kind,
        totalMentions: Math.max(1, unit.childIds.length),
        ...stablePoint(unit.id, index),
        colorHsl: graphKindHsl(canvasLens),
        metadata: {
            sourceType: canvasLens === 'structure' ? 'document-structure' : 'document-fact',
            graphKind: canvasLens,
            canvasLens,
            reviewState: row?.state || (canvasLens === 'facts' ? 'proposed' : 'ledger_only'),
            confidence: unit.confidence.score,
            detector: row?.detector || unit.confidence.source,
            subtitle: row?.subtitle || unit.kind,
            sourceSnippet: evidence[0]?.preview || row?.detail || '',
            searchableText: `${unit.label} ${row?.detail || ''} ${unit.confidence.reasons.join(' ')}`,
            noteId: unit.noteId,
            sourceStart: unit.start,
            sourceEnd: unit.end,
            reasons: row?.why || unit.confidence.reasons,
            evidenceIds: row?.evidenceSpanIds || evidence.map((span) => span.id),
            relatedEntityIds: row?.relatedObjectIds || [],
            memberIds: unit.childIds.map((id) => canvasLens === 'structure' ? structureNodeId(id) : factNodeId(id)),
            reviewObjectId: row?.objectId || '',
            reviewActions: row?.availableActions.map((action) => action.kind) || [],
            galaxyId: `${canvasLens}-note:${unit.noteId}`,
            galaxyLabel: canvasLens === 'structure' ? 'Document structure' : 'Reviewable facts',
            graphImpact: canvasLens === 'structure'
                ? 'Disposable sidecar structure; never an anchor without promotion.'
                : 'Reviewable semantic object; no durable topology change yet.',
        },
    };
}

function evidenceByUnitId(spans: EvidenceSpan[]): Map<string, EvidenceSpan[]> {
    const grouped = new Map<string, EvidenceSpan[]>();
    for (const span of spans) {
        const values = grouped.get(span.unitId) || [];
        values.push(span);
        grouped.set(span.unitId, values);
    }
    return grouped;
}

function uniqueUnits<T extends DocumentUnit>(units: T[]): T[] {
    const seen = new Set<string>();
    return units.filter((unit) => seen.has(unit.id) ? false : (seen.add(unit.id), true));
}

function entitySurfaceIndex(snapshot: GraphRebuildSnapshot): Map<string, string> {
    const index = new Map<string, string>();
    for (const entity of snapshot.nodes) {
        index.set(normalize(entity.label), entity.id);
        for (const alias of entity.aliases) index.set(normalize(alias), entity.id);
    }
    return index;
}

function factSurfaces(fact: GraphFactCandidate | RhetoricalUnit): string[] {
    return 'subjectSurfaces' in fact ? [...fact.subjectSurfaces, ...fact.objectSurfaces] : [];
}

function factEvidenceIds(fact: GraphFactCandidate | RhetoricalUnit): string[] {
    return fact.evidenceSpanIds;
}

function graphKindCounts(nodes: GalaxyRenderableNode[]): Array<{ kind: string; count: number }> {
    const counts = new Map<string, number>();
    for (const node of nodes) {
        const kind = String(node.kind || 'unknown').toLowerCase();
        counts.set(kind, (counts.get(kind) || 0) + 1);
    }
    return [...counts.entries()].map(([kind, count]) => ({ kind, count }));
}

function stablePoint(id: string, index: number): { atlasX: number; atlasY: number; atlasZ: number } {
    const angle = index * 2.399963229728653 + hashUnit(id);
    const y = 1 - ((index % 89) / 88) * 2;
    const radius = Math.sqrt(Math.max(0, 1 - y * y)) * 0.92;
    return { atlasX: Math.cos(angle) * radius, atlasY: y * 0.7, atlasZ: Math.sin(angle) * radius };
}

function graphKindHsl(kind: string): string {
    if (kind === 'structure') return '184 72% 48%';
    if (kind === 'facts' || kind === 'fact') return '326 74% 57%';
    if (kind === 'event') return entityColorStore.getRawGraphNodeHsl('eventNode');
    if (kind === 'discourse') return '92 68% 52%';
    return '220 10% 54%';
}

function chunkNodeId(id: string): string { return `chunk:${id}`; }
function structureNodeId(id: string): string { return `structure:${id}`; }
function factNodeId(id: string): string { return `fact:${id}`; }
function discourseNodeId(id: string): string { return `discourse:${id}`; }
function normalize(value: string): string { return value.trim().toLocaleLowerCase(); }
function isString(value: string | undefined): value is string { return Boolean(value); }
function clampConfidence(value: number): number { return Math.max(0.05, Math.min(1.8, value)); }

function hashUnit(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}
