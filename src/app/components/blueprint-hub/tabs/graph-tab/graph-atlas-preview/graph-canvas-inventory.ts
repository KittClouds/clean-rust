import type { DocumentUnit, EvidenceSpan, GraphFactCandidate, RhetoricalUnit } from '../../../../../graph-rebuild/graph-document-sidecar';
import type { GraphCompilerAtom, GraphCompilerFactRole } from '../../../../../graph-rebuild/graph-compiler-read-model';
import type { GraphDocumentReviewRow } from '../../../../../graph-rebuild/graph-document-review';
import type { GraphAtlasFamily, GraphAtlasManifoldTarget, GraphAtlasObject, GraphAtlasPacket } from '../../../../../graph-rebuild/graph-atlas-packet';
import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import { entityColorStore } from '../../../../../lib/store/entityColorStore';
import type { GraphInventory } from './graph-atlas-preview.component';
import type { GalaxyInputEdge, GalaxyRenderableNode } from './graph-galaxy-engine';

const STRUCTURE_KINDS = new Set([
    'document', 'section', 'subsection', 'paragraph_group', 'chapter', 'scene',
    'list', 'table', 'figure', 'code_block', 'caption', 'parent_chunk', 'leaf_chunk',
]);

/**
 * Compatibility adapter over GraphRebuildSnapshot. Rust Atlas packets should
 * become the graph-family source; TS keeps filtering/rendering only.
 */
export function buildGraphCanvasInventory(snapshot: GraphRebuildSnapshot | null): GraphInventory {
    if (!snapshot) return { nodes: [], edges: [], kindCounts: [], sourceLabel: 'graph rebuild snapshot' };
    const packetInventory = buildAtlasPacketInventory(snapshot.atlasPacket);
    if (packetInventory) return packetInventory;
    const nodes: GalaxyRenderableNode[] = [];
    const edges: GalaxyInputEdge[] = [];
    const reviewRows = new Map((snapshot.documentReviewSummary?.rows || []).map((row) => [row.objectId, row]));
    const evidence = snapshot.documentSidecarSummary?.evidenceSpans || [];
    const evidenceByUnit = evidenceByUnitId(evidence);

    addEntityGraph(snapshot, nodes, edges);
    addChunkGraph(snapshot, nodes, edges);
    addStructureGraph(snapshot, reviewRows, evidenceByUnit, nodes, edges);
    addFactGraph(snapshot, reviewRows, evidenceByUnit, nodes, edges);
    addCompiledSituationGraph(snapshot, reviewRows, nodes, edges);
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

function buildAtlasPacketInventory(packet: GraphAtlasPacket | undefined): GraphInventory | null {
    if (!packet || (!packet.objects.length && !packet.manifoldTargets.length)) return null;
    const nodes: GalaxyRenderableNode[] = [];
    const edges: GalaxyInputEdge[] = [];
    const nodeIds = new Set<string>();
    const targetObjectById = new Map(packet.manifoldTargets.map((target) => [target.id, target.objectId]));

    for (const [index, object] of packet.objects.entries()) {
        nodes.push(atlasObjectNode(object, index));
        nodeIds.add(object.id);
    }
    for (const [index, target] of packet.manifoldTargets.entries()) {
        if (nodeIds.has(target.objectId)) continue;
        nodes.push(atlasTargetNode(target, nodes.length + index));
        nodeIds.add(target.objectId);
    }
    const edgeIds = new Set<string>();
    for (const object of packet.objects) {
        for (const targetId of object.targetIds || []) {
            const resolvedTargetId = nodeIds.has(targetId) ? targetId : targetObjectById.get(targetId);
            if (!resolvedTargetId || resolvedTargetId === object.id || !nodeIds.has(resolvedTargetId)) continue;
            pushAtlasPacketEdge(edges, edgeIds, object.id, resolvedTargetId, object.family, 'object_target');
        }
    }
    for (const target of packet.manifoldTargets) {
        for (const parentId of target.parentIds || []) {
            const parentObjectId = targetObjectById.get(parentId) || (nodeIds.has(parentId) ? parentId : '');
            if (!parentObjectId || parentObjectId === target.objectId || !nodeIds.has(parentObjectId)) continue;
            pushAtlasPacketEdge(edges, edgeIds, parentObjectId, target.objectId, target.family, 'manifold_parent');
        }
    }
    return {
        nodes,
        edges,
        kindCounts: graphKindCounts(nodes),
        sourceLabel: `${packet.sourceContract.authority} / ${packet.sourceContract.vectorContract}`,
    };
}

function atlasObjectNode(object: GraphAtlasObject, index: number): GalaxyRenderableNode {
    const family = object.family || 'unknown';
    return {
        id: object.id,
        label: object.label || object.id,
        kind: object.kind || family,
        totalMentions: Math.max(1, object.evidenceIds.length || object.anchorIds.length || object.targetIds.length),
        ...stablePoint(object.id, index),
        colorHsl: atlasFamilyHsl(family),
        metadata: {
            sourceType: 'rust-atlas-packet',
            sourceSystem: 'rust',
            sourceId: object.sourceIds[0] || object.id,
            atlasObjectId: object.id,
            graphFamily: family,
            graphKind: family,
            canvasLens: atlasCanvasLens(family),
            reviewState: object.status,
            confidence: object.status === 'accepted' ? 1 : 0.64,
            subtitle: `${family} / ${object.status}`,
            searchableText: `${object.label} ${object.kind} ${family} ${object.sourceIds.join(' ')}`,
            relatedEntityIds: object.registryEntityId ? [object.registryEntityId] : [],
            noteIds: object.noteIds,
            chunkIds: object.chunkIds,
            anchorIds: object.anchorIds,
            evidenceIds: object.evidenceIds,
            memberIds: object.targetIds,
            graphImpact: 'Rust Atlas packet object; Graph and Embed modes share this packet.',
        },
    };
}

function atlasTargetNode(target: GraphAtlasManifoldTarget, index: number): GalaxyRenderableNode {
    const family = target.family || 'unknown';
    return {
        id: target.objectId,
        label: target.label || target.objectId,
        kind: target.kind || family,
        totalMentions: Math.max(1, target.evidenceIds.length),
        ...stablePoint(target.objectId, index),
        colorHsl: atlasFamilyHsl(family),
        metadata: {
            sourceType: 'rust-atlas-packet-target',
            sourceSystem: 'rust',
            sourceId: target.sourceId,
            atlasObjectId: target.objectId,
            atlasTargetId: target.id,
            graphFamily: family,
            graphKind: family,
            canvasLens: atlasCanvasLens(family),
            reviewState: target.admission,
            confidence: target.vectorStatus === 'modelVector' ? 1 : 0.56,
            subtitle: `${family} / ${target.coordinateSource}`,
            searchableText: `${target.label} ${target.kind} ${family} ${target.sourceId}`,
            relatedEntityIds: target.registryEntityId ? [target.registryEntityId] : [],
            noteId: target.noteId,
            chunkId: target.chunkId,
            evidenceIds: target.evidenceIds,
            parentIds: target.parentIds || [],
            graphImpact: 'Rust manifold target projected as an Atlas object fallback.',
        },
    };
}

function pushAtlasPacketEdge(
    edges: GalaxyInputEdge[],
    seen: Set<string>,
    sourceId: string,
    targetId: string,
    family: GraphAtlasFamily,
    type: string,
): void {
    const id = `atlas-packet:${type}:${sourceId}->${targetId}`;
    if (seen.has(id)) return;
    seen.add(id);
    edges.push({
        id,
        sourceId,
        targetId,
        type,
        confidence: 0.86,
        metadata: {
            sourceType: 'rust-atlas-packet',
            graphFamily: family,
            canvasLens: atlasCanvasLens(family),
            reviewState: 'accepted',
            graphImpact: 'Packet topology edge shared by Graph and Embed views.',
        },
    });
}

function atlasCanvasLens(family: GraphAtlasFamily): string {
    if (family === 'entity' || family === 'registry') return 'entities';
    if (family === 'structure' || family === 'evidence') return 'structure';
    if (family === 'discourse') return 'discourse';
    return family === 'review' ? 'proposed' : 'facts';
}

function atlasFamilyHsl(family: GraphAtlasFamily): string {
    if (family === 'entity' || family === 'registry') return graphKindHsl('entity');
    if (family === 'structure' || family === 'evidence') return graphKindHsl('structure');
    if (family === 'discourse') return graphKindHsl('discourse');
    if (family === 'temporal' || family === 'causal' || family === 'memory') return entityColorStore.getRawGraphNodeHsl('eventNode');
    if (family === 'review') return '44 84% 58%';
    if (family === 'hypergraph') return '286 70% 62%';
    return graphKindHsl('fact');
}

function addCompiledSituationGraph(
    snapshot: GraphRebuildSnapshot,
    reviewRows: Map<string, GraphDocumentReviewRow>,
    nodes: GalaxyRenderableNode[],
    edges: GalaxyInputEdge[],
): void {
    const compiler = snapshot.documentCompilerSummary;
    const factGraph = snapshot.graphCompiler;
    if (!compiler || !factGraph) return;
    const nodeIds = new Set(nodes.map((node) => node.id));
    const entityNodes = new Map<string, string>();
    for (const entity of snapshot.nodes) {
        entityNodes.set(entity.id, entity.id);
        entityNodes.set(entity.entityId, entity.id);
    }
    const atomById = new Map(factGraph.atoms.map((atom) => [atom.id, atom]));
    const evidenceByCompilerId = new Map(factGraph.evidenceAnchors.map((evidence) => [evidence.id, evidence]));
    const rolesByFact = new Map<string, GraphCompilerFactRole[]>();
    for (const role of factGraph.roles) {
        rolesByFact.set(role.factId, [...(rolesByFact.get(role.factId) || []), role]);
    }
    const evidenceById = new Map((snapshot.documentSidecarSummary?.evidenceSpans || []).map((span) => [span.id, span]));

    for (const fact of factGraph.facts.filter((candidate) =>
        candidate.status === 'accepted' && Boolean(candidate.semanticSituationId)
    )) {
        const hyperedge = compiler.hyperedges.find((candidate) =>
            `fact:document-hyperedge:${candidate.id}` === fact.id
        );
        if (!hyperedge) continue;
        const row = reviewRows.get(hyperedge.provenance.sourceObjectId)
            || (hyperedge.provenance.sourceReviewRowId
                ? reviewRows.get(hyperedge.provenance.sourceReviewRowId)
                : undefined);
        const roleTargets = (rolesByFact.get(fact.id) || [])
            .map((role) => compiledRoleTarget(
                role,
                atomById,
                evidenceByCompilerId,
                entityNodes,
                nodeIds,
                nodes,
            ))
            .filter((target): target is { role: GraphCompilerFactRole; nodeId: string } => !!target);
        const participantIds = new Set(roleTargets
            .filter((target) => target.role.role !== 'evidence')
            .map((target) => target.nodeId));
        if (participantIds.size < 2) continue;

        const id = `situation:${fact.id}`;
        const firstEvidence = hyperedge.evidenceSpanIds.map((evidenceId) => evidenceById.get(evidenceId)).find(Boolean);
        const reviewState = row?.state || hyperedge.provenance.reviewState || fact.status;
        nodes.push({
            id,
            label: fact.semanticFrame || hyperedge.frame || fact.predicate,
            kind: hyperedge.frameFamily || hyperedge.sourceKind || 'semantic_situation',
            totalMentions: roleTargets.length,
            ...stablePoint(fact.id, nodes.length),
            colorHsl: graphKindHsl('fact'),
            metadata: {
                sourceType: 'rust-compiled-semantic-situation',
                compilerSource: snapshot.graphCompilerSource,
                compilerFactId: fact.id,
                graphKind: 'facts',
                canvasLens: 'facts',
                reviewState,
                confidence: fact.confidence,
                detector: 'rust_graph_compiler',
                subtitle: `${hyperedge.frameFamily || hyperedge.sourceKind} / ${participantIds.size} participants`,
                sourceSnippet: firstEvidence?.preview || row?.detail || fact.predicate,
                searchableText: `${fact.semanticFrame || ''} ${fact.predicate} ${hyperedge.roles.map((role) => role.surface || '').join(' ')}`,
                noteId: hyperedge.provenance.noteId,
                sourceStart: hyperedge.provenance.sourceStart,
                sourceEnd: hyperedge.provenance.sourceEnd,
                reasons: hyperedge.provenance.reasons,
                evidenceIds: hyperedge.evidenceSpanIds,
                relatedEntityIds: roleTargets
                    .filter((target) => entityNodes.has(target.nodeId))
                    .map((target) => target.nodeId),
                memberIds: roleTargets.map((target) => target.nodeId),
                reviewObjectId: hyperedge.provenance.sourceReviewRowId || hyperedge.provenance.sourceObjectId,
                reviewActions: row?.availableActions.map((action) => action.kind) || [],
                graphImpact: 'Compiled semantic situation rendered as one incidence node with typed role edges.',
            },
        });
        nodeIds.add(id);

        for (const target of roleTargets) {
            edges.push({
                id: `situation-role:${fact.id}:${target.role.role}:${target.nodeId}`,
                sourceId: id,
                targetId: target.nodeId,
                type: `role:${target.role.semanticRole || target.role.role}`,
                confidence: target.role.confidence,
                metadata: {
                    canvasLens: 'facts',
                    reviewState,
                    confidence: target.role.confidence,
                    detector: 'rust_graph_compiler',
                    evidenceIds: hyperedge.evidenceSpanIds,
                    relatedEntityIds: [target.nodeId],
                    role: target.role.role,
                    semanticRole: target.role.semanticRole,
                    graphImpact: 'Typed role incidence rendered through the standard edge buffer.',
                },
            });
        }
    }
}

function compiledRoleTarget(
    role: GraphCompilerFactRole,
    atomById: Map<string, GraphCompilerAtom>,
    evidenceByCompilerId: Map<string, { id: string; sourceId: string; kind: string; confidence: number }>,
    entityNodes: Map<string, string>,
    nodeIds: Set<string>,
    nodes: GalaxyRenderableNode[],
): { role: GraphCompilerFactRole; nodeId: string } | null {
    const atom = atomById.get(role.atomId);
    if (atom?.kind === 'entity' || atom?.kind === 'concept') {
        const entityId = atom.entityId || atom.sourceId;
        const nodeId = entityNodes.get(entityId);
        if (nodeId) return { role, nodeId };
    }
    const evidence = evidenceByCompilerId.get(role.atomId);
    const nodeId = `compiler-atom:${role.atomId}`;
    if (!atom && !evidence) return null;
    if (!nodeIds.has(nodeId)) {
        const label = atom?.label || evidence?.sourceId || role.role;
        nodes.push({
            id: nodeId,
            label,
            kind: atom?.kind || 'evidenceAnchor',
            totalMentions: 1,
            ...stablePoint(role.atomId, nodes.length),
            colorHsl: graphKindHsl(role.role === 'evidence' ? 'structure' : 'fact'),
            metadata: {
                sourceType: role.role === 'evidence' ? 'compiler-evidence' : 'compiler-role-atom',
                graphKind: role.role === 'evidence' ? 'structure' : 'facts',
                canvasLens: 'facts',
                reviewState: 'accepted',
                confidence: role.confidence,
                detector: 'rust_graph_compiler',
                subtitle: role.semanticRole || role.role,
                sourceSnippet: label,
                searchableText: `${label} ${role.role} ${role.semanticRole || ''}`,
                evidenceIds: evidence ? [evidence.sourceId] : atom?.evidenceIds || [],
                graphImpact: 'Compiled role target from the authoritative graph fact.',
            },
        });
        nodeIds.add(nodeId);
    }
    return { role, nodeId };
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
